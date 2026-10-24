#!/usr/bin/env python3
"""API authorization and credential-forgery checks using an isolated server.

Run: ``uv run python tests/test_reader_api.py``. The Pico port is deliberately
unavailable; identity-only enrollment must still work without reader hardware.
"""
from __future__ import annotations

from http.cookiejar import CookieJar
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class ApiClient:
    def __init__(self, base: str):
        self.base = base
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def request(self, path: str, *, method: str = "GET", body=None, headers=None):
        request_headers = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(self.base + path, data=data, headers=request_headers, method=method)
        try:
            response = self.opener.open(req, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        payload = response.read().decode("utf-8")
        try:
            decoded = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            decoded = payload
        return response.code, decoded

    def login(self, password: str) -> None:
        status, data = self.request("/api/admin/login", method="POST", body={"password": password})
        assert status == 200, (status, data)

    def session_token(self) -> str:
        cookie = next((c for c in self.cookies if c.name == "labauth_admin_session"), None)
        assert cookie is not None, "admin login did not set the session cookie"
        return cookie.value


def run() -> None:
    with tempfile.TemporaryDirectory(prefix="labauth-reader-api-") as tmp:
        db_path = Path(tmp) / "api.db"
        port = _free_port()
        base = f"http://127.0.0.1:{port}"
        password = "reader-api-test"
        env = {
            **os.environ,
            "PORT": str(port),
            "LABAUTH_DB_PATH": str(db_path),
            "LABAUTH_ADMIN_PASSWORD": password,
            "LABAUTH_PICO_PORT": "/nonexistent",
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
                        raise RuntimeError(f"server exited during startup:\n{log.read()}")
                    try:
                        urllib.request.urlopen(base + "/api/presence", timeout=1).close()
                        break
                    except Exception:
                        time.sleep(.15)
                else:
                    log.seek(0)
                    raise RuntimeError(f"server startup timed out:\n{log.read()}")

                anonymous = ApiClient(base)
                status, data = anonymous.request("/api/readers/events?since=0")
                assert status == 200 and isinstance(data.get("events"), list) and isinstance(data.get("cursor"), int), (status, data)

                for path in ("/api/readers/status",):
                    status, _ = anonymous.request(path)
                    assert status == 401, (path, status)
                for path, body in (
                    ("/api/readers/control", {"mode": "IDLE"}),
                    ("/api/readers/enrolments", {}),
                ):
                    status, _ = anonymous.request(path, method="POST", body=body)
                    assert status == 401, (path, status)
                for path in ("/api/readers/enrolments/fake-session",):
                    status, _ = anonymous.request(path)
                    assert status == 401, (path, status)
                    status, _ = anonymous.request(path, method="POST", body={"operation": "skip_nfc"})
                    assert status == 401, (path, status)
                status, _ = anonymous.request(
                    "/api/enrolment/complete", method="POST", body={"name": "Unauthenticated reader user"}
                )
                assert status == 401, status

                first_admin = ApiClient(base)
                first_admin.login(password)
                first_owner = hashlib.sha256(first_admin.session_token().encode()).hexdigest()
                status, data = first_admin.request("/api/readers/status")
                assert status == 200, (status, data)
                assert {"connected", "ready", "configured", "error", "mode", "fp_enabled", "nfc_enabled", "fp", "nfc", "enrollment"} <= data.keys(), data
                assert data["connected"] is False, data

                # Origin checks must reject a cross-site state change even with a valid session.
                status, _ = first_admin.request(
                    "/api/readers/control", method="POST", body={"mode": "IDLE"},
                    headers={"Origin": "https://attacker.invalid"},
                )
                assert status == 403, status

                # Identity-only enrolment remains available without a physical reader.
                status, data = first_admin.request(
                    "/api/enrolment/complete",
                    method="POST",
                    body={"name": "Readerless Identity", "access_area_ids": []},
                )
                assert status == 200 and data.get("user", {}).get("name") == "Readerless Identity", (status, data)

                for key, forged in (
                    ("fingerprint_enrolled", True),
                    ("nfc_uid", "04A1B2C3"),
                    ("credentials", [{"credential_type": "nfc", "identifier": "04A1B2C3"}]),
                ):
                    status, data = first_admin.request(
                        "/api/enrolment/complete", method="POST",
                        body={"name": f"Forged {key}", "access_area_ids": [], key: forged},
                    )
                    assert status == 422, (key, status, data)

                # Create an owner-bound lease in the disposable DB so endpoint ownership
                # checks can be exercised without pretending a reader is connected.
                os.environ["LABAUTH_DB_PATH"] = str(db_path)
                import database as db

                db.init_db()
                draft_id = db.create_draft(first_owner)
                status, own_draft = first_admin.request(f"/api/readers/enrolments/{draft_id}")
                assert status == 200 and own_draft.get("id") == draft_id, (status, own_draft)

                second_admin = ApiClient(base)
                second_admin.login(password)
                for method, body in (("GET", None), ("POST", {"action": "skip_nfc"})):
                    status, response = second_admin.request(
                        f"/api/readers/enrolments/{draft_id}", method=method, body=body
                    )
                    assert status in (403, 404), (method, status, response)

                with sqlite3.connect(db_path) as connection:
                    forged_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE name LIKE 'Forged %'"
                    ).fetchone()[0]
                    saved = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE name='Readerless Identity'"
                    ).fetchone()[0]
                    credentials = connection.execute(
                        "SELECT COUNT(*) FROM credentials c JOIN users u ON u.id=c.user_id WHERE u.name='Readerless Identity'"
                    ).fetchone()[0]
                assert forged_count == 0, forged_count
                assert saved == 1 and credentials == 0, (saved, credentials)
                print("PASS reader API public feed, admin auth, CSRF, draft ownership, and credential forgery checks")
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)


if __name__ == "__main__":
    run()
