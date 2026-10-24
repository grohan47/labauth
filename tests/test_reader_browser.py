#!/usr/bin/env python3
"""Pico reader/admin/display browser integration using a PTY firmware emulator.

Run: ``uv run python tests/test_reader_browser.py``. Use ``--status-only`` for
the polling availability regression. No USB device is opened.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import pty
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(ROOT / "src"))
from cdp import Browser, free_port, wait_for  # noqa: E402
from test_pico_service import PicoEmulator  # noqa: E402
import database as db  # noqa: E402


async def run(*, status_only: bool = False) -> None:
    with tempfile.TemporaryDirectory(prefix="labauth-reader-browser-") as tmp:
        db_path = Path(tmp) / "browser.db"
        os.environ["LABAUTH_DB_PATH"] = str(db_path)
        db.init_db()
        area = db.list_access_areas()[0]
        user = db.create_enrolment(
            "Browser Reader User",
            access_area_ids=[area.id],
            credentials=[("fingerprint", "template:41"), ("nfc", "00112233")],
        )

        master_fd, slave_fd = pty.openpty()
        serial_port = os.ttyname(slave_fd)
        emulator = PicoEmulator(master_fd)
        emulator.start()
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        env = {
            **os.environ,
            "PORT": str(port),
            "LABAUTH_DB_PATH": str(db_path),
            "LABAUTH_ADMIN_PASSWORD": "reader-browser-test",
            "LABAUTH_PICO_PORT": serial_port,
            "PYTHONUNBUFFERED": "1",
        }
        log_path = Path(tmp) / "server.log"
        with log_path.open("w+") as log:
            proc = subprocess.Popen([sys.executable, "src/main.py"], cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(f"app exited during startup:\n{log.read()}")
                    try:
                        urllib.request.urlopen(base + "/api/presence", timeout=1).close()
                        break
                    except Exception:
                        await asyncio.sleep(.15)
                else:
                    log.seek(0)
                    raise RuntimeError(f"app startup timed out:\n{log.read()}")

                with Browser(base + "/display") as display_browser, Browser(base + "/admin-display") as admin_browser:
                    display = await display_browser.page()
                    admin = await admin_browser.page()
                    try:
                        assert await wait_for(display, "!!document.querySelector('#auth-alert-overlay')"), "Display did not mount"
                        login = await admin.evaluate(
                            "fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},"
                            "body:JSON.stringify({password:'reader-browser-test'})}).then(r=>r.json())"
                        )
                        assert login.get("status") == "ok", login
                        await admin.send_command("Page.navigate", {"url": base + "/admin"})
                        assert await wait_for(
                            admin,
                            "!!document.querySelector('#admin-reader-controls') && !!customElements.get('sbb-checkbox')",
                            timeout=45,
                        ), "Reader controls or Lyne checkbox did not mount"
                        assert await wait_for(
                            admin,
                            "document.querySelector('#reader-connection')?.textContent === 'Ready' && "
                            "document.querySelector('#reader-fingerprint-status')?.textContent.includes('READY') && "
                            "document.querySelector('#reader-nfc-status')?.textContent.includes('READY')",
                            timeout=20,
                        ), "Reader status did not initialize after NiceGUI mounted"

                        # Older firmware's normal polling BUSY is availability,
                        # while the original report remains visible in diagnostics.
                        emulator.startup_statuses = 1000
                        emulator.send(emulator._status())
                        assert await wait_for(admin, "fetch('/api/readers/status').then(r=>r.json()).then(s=>s.mode==='POLL' && s.fp==='READY' && s.fp_state==='BUSY')")
                        assert await wait_for(admin, "document.querySelector('#reader-fingerprint-status').textContent==='Enabled · READY'")
                        emulator.startup_statuses = 0
                        if status_only:
                            print('PASS: polling BUSY reports READY in the API and mounted admin UI; raw BUSY remains in diagnostics')
                            return

                        async def set_enabled(element_id: str, key: str, command: str, value: bool):
                            await admin.evaluate(f"document.querySelector('#{element_id}').click()")
                            assert await wait_for(
                                admin,
                                f"fetch('/api/readers/status').then(r=>r.json()).then(s=>s.{key} === {str(value).lower()} "
                                f"&& !document.querySelector('#{element_id}').disabled "
                                f"&& document.querySelector('#{element_id}').checked === {str(value).lower()})",
                            ), key
                            assert command in emulator.commands, (command, emulator.commands)

                        await set_enabled("reader-fingerprint-enabled", "fp_enabled", "FP DISABLE", False)
                        await set_enabled("reader-fingerprint-enabled", "fp_enabled", "FP ENABLE", True)
                        await set_enabled("reader-nfc-enabled", "nfc_enabled", "NFC DISABLE", False)
                        await set_enabled("reader-nfc-enabled", "nfc_enabled", "NFC ENABLE", True)

                        await admin.evaluate("document.querySelector('#reader-mode-check').click()")
                        assert await wait_for(admin, "fetch('/api/readers/status').then(r=>r.json()).then(s=>s.mode === 'CHECK')"), "CHECK click did not reach reader API"
                        assert "MODE CHECK" in emulator.commands
                        before_check = db.get_db
                        with before_check() as connection:
                            presence_before = connection.execute("SELECT COUNT(*) FROM presence_log").fetchone()[0]
                        emulator.send("EVT FP MATCH id=41")
                        assert await wait_for(
                            display,
                            "document.querySelector('#auth-alert-overlay .auth-alert-card:not(.auth-alert-card--error) .alert-bar-label')?.textContent === 'OUT' && "
                            "document.querySelector('#auth-alert-overlay .person-name')?.textContent === 'Browser Reader User' && "
                            "document.querySelector('#auth-alert-overlay sbb-chip-label')?.textContent",
                            timeout=12,
                        ), "CHECK did not show the existing user's OUT card with their access"
                        assert not await display.evaluate("!!document.querySelector('#auth-alert-overlay .reader-alert-title')"), "CHECK must not show generic identity confirmation"
                        assert not db.is_user_inside(user["id"])
                        with db.get_db() as connection:
                            assert connection.execute("SELECT COUNT(*) FROM presence_log").fetchone()[0] == presence_before

                        # CHECK itself logs a successful attempt, so wait for its shared cooldown before POLL.
                        await asyncio.sleep(3.1)
                        await admin.evaluate("document.querySelector('#reader-mode-poll').click()")
                        assert await wait_for(admin, "fetch('/api/readers/status').then(r=>r.json()).then(s=>s.mode === 'POLL')")
                        assert "MODE POLL" in emulator.commands

                        emulator.send("EVT FP NOMATCH")
                        assert await wait_for(
                            display,
                            "document.querySelector('#auth-alert-overlay .auth-alert-card--error .reader-alert-title')?.textContent === 'Fingerprint not found'",
                            timeout=12,
                        ), "Fingerprint NOMATCH was not shown as a Lyne failure card"
                        emulator.send("EVT NFC UID uid=ABCDEF12")
                        assert await wait_for(
                            display,
                            "document.querySelector('#auth-alert-overlay .auth-alert-card--error .reader-alert-title')?.textContent === 'Card UID not found'",
                            timeout=12,
                        ), "Unknown NFC UID was not shown as a Lyne failure card"

                        emulator.send("EVT FP MATCH id=41")
                        # Send the same user's NFC credential immediately at the serial boundary.
                        # Waiting for the browser's presence refresh would outlast the cooldown.
                        emulator.send("EVT NFC UID uid=00112233")
                        deadline = time.monotonic() + 4
                        cooldown = False
                        while time.monotonic() < deadline:
                            with db.get_db() as connection:
                                cooldown = connection.execute(
                                    "SELECT 1 FROM credential_attempts WHERE credential_type='nfc' "
                                    "AND identifier='00112233' AND outcome='cooldown' LIMIT 1"
                                ).fetchone() is not None
                            if cooldown:
                                break
                            await asyncio.sleep(.05)
                        if not cooldown:
                            with db.get_db() as connection:
                                attempts = [tuple(row) for row in connection.execute(
                                    "SELECT credential_type,identifier,outcome FROM credential_attempts ORDER BY id"
                                )]
                            status_snapshot = await admin.evaluate("fetch('/api/readers/status').then(r=>r.json())")
                            raise AssertionError(f"Same-user NFC cooldown missing; attempts={attempts}, status={status_snapshot}, lines={emulator.lines}")
                        assert await wait_for(display, "document.querySelector('.person-card .person-name')?.textContent === 'Browser Reader User'", timeout=12), "Known fingerprint did not appear in public presence"
                        assert await wait_for(admin, "fetch('/api/presence').then(r=>r.json()).then(d=>JSON.stringify(d).includes('Browser Reader User'))")
                        with db.get_db() as connection:
                            assert connection.execute("SELECT COUNT(*) FROM presence_log").fetchone()[0] == presence_before + 1

                        # A second CHECK uses the current presence truth and remains lookup-only.
                        await asyncio.sleep(3.1)
                        await admin.evaluate("document.querySelector('#reader-mode-check').click()")
                        assert await wait_for(admin, "fetch('/api/readers/status').then(r=>r.json()).then(s=>s.mode === 'CHECK')")
                        with db.get_db() as connection:
                            inside_presence = connection.execute("SELECT COUNT(*) FROM presence_log").fetchone()[0]
                        emulator.send("EVT FP MATCH id=41")
                        assert await wait_for(
                            display,
                            "document.querySelector('#auth-alert-overlay .auth-alert-card:not(.auth-alert-card--error) .alert-bar-label')?.textContent === 'IN' && "
                            "document.querySelector('#auth-alert-overlay .person-name')?.textContent === 'Browser Reader User'",
                            timeout=12,
                        ), "CHECK for a present user did not show the normal IN card"
                        assert db.is_user_inside(user["id"])
                        with db.get_db() as connection:
                            assert connection.execute("SELECT COUNT(*) FROM presence_log").fetchone()[0] == inside_presence

                        created = await admin.evaluate(
                            "fetch('/api/readers/enrolments',{method:'POST',headers:{'Content-Type':'application/json'},"
                            "body:'{}'}).then(async r=>({status:r.status,data:await r.json()}))"
                        )
                        assert created["status"] == 200, created
                        lease_id = created["data"]["id"]
                        assert await wait_for(admin, "fetch('/api/readers/status').then(r=>r.json()).then(s=>s.enrollment && s.mode === 'IDLE')"), "Enrollment did not acquire exclusive reader lease"
                        blocked = await admin.evaluate(
                            "fetch('/api/readers/control',{method:'POST',headers:{'Content-Type':'application/json'},"
                            "body:JSON.stringify({mode:'CHECK'})}).then(r=>r.status)"
                        )
                        assert blocked == 409, f"Reader control was not blocked during lease: {blocked}"
                        with db.get_db() as connection:
                            attempt_count = connection.execute("SELECT COUNT(*) FROM credential_attempts").fetchone()[0]
                            presence_count = connection.execute("SELECT COUNT(*) FROM presence_log").fetchone()[0]
                        emulator.send("EVT FP MATCH id=41")
                        await asyncio.sleep(.2)
                        with db.get_db() as connection:
                            assert connection.execute("SELECT COUNT(*) FROM credential_attempts").fetchone()[0] == attempt_count
                            assert connection.execute("SELECT COUNT(*) FROM presence_log").fetchone()[0] == presence_count
                        cancelled = await admin.evaluate(
                            "fetch('/api/readers/enrolments/' + " + repr(lease_id) + ",{method:'POST',headers:{'Content-Type':'application/json'},"
                            "body:JSON.stringify({action:'cancel'})}).then(r=>r.json())"
                        )
                        assert cancelled["status"] == "cancelled", cancelled
                        assert await wait_for(admin, "fetch('/api/readers/status').then(r=>r.json()).then(s=>!s.enrollment && s.mode === 'POLL')")

                        # Use fresh hardware identifiers for the real frontend enrollment/save path.
                        original_reply = emulator._reply

                        def enrollment_reply(command: str):
                            if command == "ENROLL":
                                emulator.commands.append(command)
                                emulator.provisional = True
                                emulator.send("EVT FP PROGRESS phase=FREE_ID id=42")
                                emulator.send("EVT FP PROGRESS phase=LEARN_READY id=42")
                                emulator.send("OK ENROLL")
                            elif command == "ENROLL FINISH":
                                emulator.commands.append(command)
                                emulator.learning = "OFF"
                                emulator.provisional = False
                                emulator.templates.add(42)
                                emulator.send("EVT FP ENROLLED id=42")
                                emulator.send("OK ENROLL FINISH")
                            elif command == "NFC READ":
                                emulator.commands.append(command)
                                emulator.send("EVT NFC UID uid=01020304")
                                emulator.send("OK NFC READ")
                            else:
                                original_reply(command)

                        emulator._reply = enrollment_reply
                        await admin.send_command("Page.navigate", {"url": base + "/enrollment"})
                        assert await wait_for(admin, "!!document.querySelector('#identity-form')", timeout=45), "Enrollment form did not mount"
                        await admin.evaluate(
                            "document.querySelector('#input-fullname').value='Frontend Enrolled User';"
                            "document.querySelector('#input-fullname').dispatchEvent(new Event('input',{bubbles:true}));"
                            "document.querySelector('#btn-step1-next').click()"
                        )
                        assert await wait_for(admin, "!document.querySelector('#step-2').hidden"), "Fingerprint step did not open"
                        assert await wait_for(admin, "!document.querySelector('#btn-fp-start').hidden && !document.querySelector('#btn-fp-start').disabled"), "Connected fingerprint Start was not exposed"
                        await admin.evaluate("document.querySelector('#btn-fp-start').click()")
                        assert await wait_for(admin, "!document.querySelector('#btn-fp-finish').hidden && !document.querySelector('#btn-fp-finish').disabled", timeout=12), "Hardware progress did not reach Finish learning"
                        await admin.evaluate("document.querySelector('#btn-fp-finish').click()")
                        assert await wait_for(admin, "document.querySelector('#fp-status-title')?.textContent === 'Fingerprint enrolled'", timeout=12), "Fingerprint template was not confirmed from hardware"
                        await admin.evaluate("document.querySelector('#btn-fp-skip').click()")
                        assert await wait_for(admin, "!document.querySelector('#step-3').hidden"), "Fingerprint Next did not open NFC"
                        assert await wait_for(admin, "!document.querySelector('#btn-nfc-start').hidden && !document.querySelector('#btn-nfc-start').disabled"), "Connected NFC Start was not exposed"
                        await admin.evaluate("""(() => {
                          window.__realReaderFetch = window.fetch.bind(window);
                          window.__delayReaderGets = true;
                          window.__delayedReaderGetStarted = false;
                          window.fetch = async (input, init = {}) => {
                            const path = new URL(typeof input === 'string' ? input : input.url, location.href).pathname;
                            if (window.__delayReaderGets && path.startsWith('/api/readers/enrolments/') &&
                                (!init.method || init.method === 'GET') && !window.__delayedReaderGetStarted) {
                              const response = await window.__realReaderFetch(input, init);
                              window.__delayedReaderGetStarted = true;
                              await new Promise(resolve => setTimeout(resolve, 1000));
                              return response;
                            }
                            return window.__realReaderFetch(input, init);
                          };
                        })()""")
                        assert await wait_for(admin, "window.__delayedReaderGetStarted === true", timeout=5), "Reader status GET did not enter the delayed response window"
                        await admin.evaluate("document.querySelector('#btn-nfc-start').click()")
                        command_deadline = time.monotonic() + .8
                        while time.monotonic() < command_deadline and "NFC READ" not in emulator.commands:
                            await asyncio.sleep(.01)
                        assert "NFC READ" in emulator.commands, "NFC action did not proceed while a real GET response was delayed"
                        nfc_done = await wait_for(admin, "document.querySelector('#nfc-status-title')?.textContent === 'Card registered'", timeout=12)
                        if not nfc_done:
                            with db.get_db() as connection:
                                draft_state = [tuple(row) for row in connection.execute(
                                    "SELECT id,status,stage,fp_template,nfc_uid,message FROM reader_drafts"
                                )]
                            nfc_title = await admin.evaluate("document.querySelector('#nfc-status-title')?.textContent")
                            nfc_error = await admin.evaluate("document.querySelector('#nfc-error')?.innerText")
                            reader_snapshot = await admin.evaluate("fetch('/api/readers/status').then(r=>r.json())")
                            raise AssertionError(
                                f"NFC UID was not confirmed from hardware; title={nfc_title}, error={nfc_error}, "
                                f"status={reader_snapshot}, "
                                f"drafts={draft_state}, commands={emulator.commands}, lines={emulator.lines}"
                            )
                        await asyncio.sleep(.4)
                        assert await admin.evaluate("document.querySelector('#nfc-status-title')?.textContent === 'Card registered'"), "Stale delayed GET overwrote the completed NFC action"
                        await admin.evaluate("window.__delayReaderGets = false; window.fetch = window.__realReaderFetch")
                        await admin.evaluate("document.querySelector('#btn-nfc-skip').click()")
                        assert await wait_for(admin, "!document.querySelector('#step-4').hidden"), "NFC Next did not open review"
                        assert await admin.evaluate(
                            "document.querySelector('#final-cred-fp .credential-state')?.textContent === 'Enrolled' && "
                            "document.querySelector('#final-cred-nfc .credential-state')?.textContent.includes('Enrolled')"
                        ), "Review did not reflect both reader-backed draft credentials"
                        await admin.evaluate("document.querySelector('#btn-finish-enrolment').click()")
                        assert await wait_for(admin, "!document.querySelector('#step-success').hidden", timeout=12), "Reader-backed identity save failed"
                        with db.get_db() as connection:
                            saved_credentials = {
                                (row[0], row[1]) for row in connection.execute(
                                    "SELECT c.credential_type,c.identifier FROM credentials c "
                                    "JOIN users u ON u.id=c.user_id WHERE u.name='Frontend Enrolled User'"
                                )
                            }
                        assert saved_credentials == {("fingerprint", "template:42"), ("nfc", "01020304")}, saved_credentials
                        assert not any(command.startswith("FP DELETE") and "42" in command for command in emulator.commands), emulator.commands
                        assert {"MODE ENROLL", "ENROLL", "ENROLL FINISH", "NFC READ"} <= set(emulator.commands)

                        print("PASS: mounted admin status, reader controls, CHECK/error display cards, presence/cooldown, exclusive lease, and PTY-backed frontend enrollment/save")
                    finally:
                        await display.close()
                        await admin.close()
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                emulator.stop()
                for fd in (slave_fd, master_fd):
                    try:
                        os.close(fd)
                    except OSError:
                        pass


if __name__ == "__main__":
    asyncio.run(run(status_only="--status-only" in sys.argv))
