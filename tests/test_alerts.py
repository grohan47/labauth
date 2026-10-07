#!/usr/bin/env python3
"""Real Chromium regression checks for the operator alerts feature.

Covers the /admin alerts pane (create, order by severity, inline edit, TTL menu,
delete) and the single-line ticker on both display channels (/display and
/admin-display), including vertical scroll of an over-long message.

Run: uv run python tests/test_alerts.py
Screenshots: /tmp/labauth-alerts-qa (override LABAUTH_SCREENSHOT_DIR).
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

from cdp import Browser, find_browser, free_port, wait_for

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(os.environ.get("LABAUTH_SCREENSHOT_DIR", "/tmp/labauth-alerts-qa"))
PASSWORD = "alerts-qa"


class FreshBrowser(Browser):
    """Use a fresh profile so another running browser cannot capture the test."""

    def __enter__(self):
        self.profile = tempfile.TemporaryDirectory(prefix="labauth-alerts-browser-")
        self.proc = subprocess.Popen(
            [
                find_browser(), "--headless=new", "--disable-gpu", "--no-first-run",
                f"--user-data-dir={self.profile.name}",
                f"--window-size={self.width},{self.height}",
                f"--remote-debugging-port={self.port}", "about:blank",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        self._wait_for_target()
        return self

    def __exit__(self, *args):
        super().__exit__(*args)
        self.profile.cleanup()


async def check_alerts(base: str, password: str) -> None:
    with FreshBrowser("about:blank") as browser:
        client = await browser.page()
        try:
            await client.send_command("Page.enable")
            await client.send_command("Page.addScriptToEvaluateOnNewDocument", {"source": """
                window.qaErrors = [];
                window.qaResourceErrors = [];
                addEventListener('error', e => {
                    if (e.message) qaErrors.push(e.message);
                    else if (e.target.src || e.target.href) qaResourceErrors.push(e.target.src || e.target.href);
                }, true);
                addEventListener('unhandledrejection', e => qaErrors.push(String(e.reason)));
            """})

            async def navigate(path):
                await client.send_command("Page.navigate", {"url": base + path})
                assert await wait_for(
                    client,
                    f"location.href.startsWith({json.dumps(base + path)}) && document.readyState === 'complete'",
                )

            async def click(selector):
                point = await client.evaluate(f"""(() => {{
                    const n = document.querySelector({json.dumps(selector)});
                    if (!n) return null;
                    n.scrollIntoView({{block: 'center'}});
                    const r = n.getBoundingClientRect();
                    return {{x: r.x + r.width / 2, y: r.y + r.height / 2}};
                }})()""")
                assert point, f"missing element {selector}"
                await client.send_command("Input.dispatchMouseEvent", {"type": "mousePressed", "button": "left", "clickCount": 1, **point})
                await client.send_command("Input.dispatchMouseEvent", {"type": "mouseReleased", "button": "left", "clickCount": 1, **point})
                await asyncio.sleep(0.15)

            async def add_alert(message, severity):
                await client.evaluate(f"""(() => {{
                    const input = document.querySelector('#admin-alert-input');
                    input.value = {json.dumps(message)};
                    const select = document.querySelector('#admin-alert-severity');
                    select.value = {json.dumps(severity)};
                    document.querySelector('#admin-alerts-form').dispatchEvent(new Event('submit', {{cancelable: true}}));
                }})()""")
                found = await wait_for(
                    client,
                    f"[...document.querySelectorAll('.admin-alert-row__message')].some(n => n.textContent === {json.dumps(message)})",
                )
                assert found, f"alert {message!r} never rendered"

            # Log in on the page origin so the session cookie is stored.
            await navigate("/display")
            code = await client.evaluate(
                "fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},"
                f"body:JSON.stringify({{password:{json.dumps(password)}}})}}).then(r=>r.status)"
            )
            assert code == 200

            # --- Admin pane -------------------------------------------------
            await navigate("/admin")
            assert await wait_for(client, "!!document.querySelector('#admin-alerts-open-btn')")
            await click("#admin-alerts-open-btn")
            assert await wait_for(client, "!!document.querySelector('#admin-alert-input')")
            assert await client.evaluate("document.querySelector('#admin-alerts-list').textContent.includes('No active alerts')")
            await client.screenshot(str(ARTIFACTS / "admin-alerts-empty.png"))

            # Add info, then caution, then critical; the pane must sort by severity.
            await add_alert("Scheduled maintenance window", "info")
            await add_alert("Wet floor near the mill", "caution")
            await add_alert("Evacuate the lab immediately", "critical")
            order = await client.evaluate(
                "[...document.querySelectorAll('.admin-alert-row')].map(r => r.className.match(/admin-alert-row--(\\w+)/)[1])"
            )
            assert order == ["critical", "caution", "info"], order
            labels = await client.evaluate(
                "[...document.querySelectorAll('.admin-alert-row__severity')].map(n => n.textContent.trim())"
            )
            assert labels == ["Critical", "Caution", "Info"], labels
            await client.screenshot(str(ARTIFACTS / "admin-alerts-list.png"))

            # Inline edit: change the caution alert's text and severity.
            edit_id = await client.evaluate(
                "document.querySelector('.admin-alert-row--caution').dataset.alertId"
            )
            await click(f"#alert-edit-{edit_id}")
            assert await wait_for(client, f"!!document.querySelector('#alert-save-{edit_id}')")
            await client.evaluate(f"""(() => {{
                const row = document.querySelector('.admin-alert-row[data-alert-id="{edit_id}"]');
                row.querySelector('.admin-alert-row__input').value = 'Wet floor: use the north entrance';
                row.querySelector('.admin-alert-row__severity').value = 'info';
            }})()""")
            await click(f"#alert-save-{edit_id}")
            assert await wait_for(
                client,
                "[...document.querySelectorAll('.admin-alert-row__message')].some(n => n.textContent === 'Wet floor: use the north entrance')",
            )
            await client.screenshot(str(ARTIFACTS / "admin-alerts-edited.png"))

            # A browser/proxy can return a stale list after a successful write.
            # Save/delete must paint the mutation result, independently of that GET.
            await client.evaluate("""(async () => {
                window.qaUncachedFetch = window.fetch.bind(window);
                const cached = await qaUncachedFetch('/api/alerts').then(r => r.json());
                window.fetch = (url, options = {}) => {
                    if (url === '/api/alerts' && (!options.method || options.method === 'GET')) {
                        return Promise.resolve(new Response(JSON.stringify(cached), {
                            status: 200, headers: {'Content-Type':'application/json'}
                        }));
                    }
                    return qaUncachedFetch(url, options);
                };
            })()""")

            # Inline TTL selector: give the critical alert a one-hour lifetime.
            critical_id = await client.evaluate(
                "document.querySelector('.admin-alert-row--critical').dataset.alertId"
            )
            await click(f"#alert-ttl-{critical_id}")
            assert await wait_for(client, f"!!document.querySelector('.admin-alert-row[data-alert-id=\"{critical_id}\"] .admin-alert-row__ttl-choices')")
            await client.screenshot(str(ARTIFACTS / "admin-alerts-ttl-open.png"))
            await click(f'.admin-alert-row[data-alert-id="{critical_id}"] sbb-secondary-button[data-ttl="3600"]')
            ttl_label = await wait_for(
                client,
                f"(() => {{ const r = document.querySelector('.admin-alert-row[data-alert-id=\"{critical_id}\"] .admin-alert-row__ttl');"
                " return r && /left/.test(r.textContent) ? r.textContent.trim() : null; })()",
            )
            assert ttl_label, "TTL label never appeared"
            await client.screenshot(str(ARTIFACTS / "admin-alerts-ttl.png"))

            # Every preset must persist in the API, including removing expiry.
            for seconds, label in [(28800, 'left'), (86400, 'left'), (604800, 'left'), (0, 'No expiry')]:
                await click(f"#alert-ttl-{critical_id}")
                assert await wait_for(client, "!!document.querySelector('.admin-alert-row__ttl-choices')")
                await click(f'.admin-alert-row[data-alert-id="{critical_id}"] sbb-secondary-button[data-ttl="{seconds}"]')
                assert await wait_for(client, f"document.querySelector('#alert-ttl-{critical_id}') && !document.querySelector('.admin-alert-row__ttl-choices')")
                actual = await client.evaluate("qaUncachedFetch('/api/alerts').then(r=>r.json()).then(d=>d.alerts.find(a=>a.id==="+str(critical_id)+"))")
                if seconds:
                    assert seconds - 10 <= actual['remaining_seconds'] <= seconds, actual
                    assert actual['expires_at'], actual
                else:
                    assert actual['remaining_seconds'] is None and actual['expires_at'] is None, actual
                assert await client.evaluate(f"document.querySelector('.admin-alert-row[data-alert-id=\"{critical_id}\"] .admin-alert-row__ttl').textContent.includes({json.dumps(label)})")

            # A failed duration request must report an error and leave choices
            # open for a retry, with the stored alert untouched.
            await click(f"#alert-ttl-{critical_id}")
            assert await wait_for(client, "!!document.querySelector('.admin-alert-row__ttl-choices')")
            await client.evaluate("""(() => {
                window.qaStaleFetch = window.fetch;
                window.fetch = (url, options={}) => options.method === 'PUT' || options.method === 'DELETE'
                    ? Promise.reject(new TypeError('QA simulated disconnect')) : qaStaleFetch(url, options);
            })()""")
            await click(f'.admin-alert-row[data-alert-id="{critical_id}"] sbb-secondary-button[data-ttl="3600"]')
            assert await wait_for(client, "!document.querySelector('#admin-alerts-error').hidden")
            assert await client.evaluate("!!document.querySelector('.admin-alert-row__ttl-choices')")
            actual = await client.evaluate("qaUncachedFetch('/api/alerts').then(r=>r.json()).then(d=>d.alerts.find(a=>a.id==="+str(critical_id)+"))")
            assert actual['expires_at'] is None, actual
            await client.evaluate('window.fetch = window.qaStaleFetch')
            await click(f'.admin-alert-row[data-alert-id="{critical_id}"] sbb-secondary-button[data-ttl="3600"]')
            assert await wait_for(client, "document.querySelector('#admin-alerts-error').hidden && !document.querySelector('.admin-alert-row__ttl-choices')")

            # Delete the info alert.
            info_id = await client.evaluate(
                "[...document.querySelectorAll('.admin-alert-row')].find(r => r.classList.contains('admin-alert-row--info')).dataset.alertId"
            )
            await client.evaluate("window.fetch = (url, options={}) => options.method === 'DELETE' ? Promise.reject(new TypeError('QA simulated disconnect')) : qaStaleFetch(url, options)")
            await click(f"#alert-delete-{info_id}")
            assert await wait_for(client, "!document.querySelector('#admin-alerts-error').hidden")
            assert await client.evaluate(f"!!document.querySelector('#alert-delete-{info_id}')")
            await client.evaluate('window.fetch = window.qaStaleFetch')
            await click(f"#alert-delete-{info_id}")
            assert await wait_for(
                client,
                f"![...document.querySelectorAll('.admin-alert-row')].some(r => r.dataset.alertId === {json.dumps(info_id)})",
            )

            await client.evaluate('window.fetch = window.qaUncachedFetch')

            # --- Ticker on both display channels ----------------------------
            # Replace everything with one over-long critical alert so the ticker
            # deterministically starts with it and must scroll.
            long_message = (
                "Critical safety notice: the fume extraction system is offline for emergency servicing. "
                "Do not operate the laser cutter, the soldering stations or any resin printer until the "
                "extraction unit has been cleared by the safety officer. Keep the lab doors open, avoid "
                "aerosol adhesives, and report any unusual odour to the administrator immediately."
            )
            await client.evaluate("""(() => {
                const rows = [...document.querySelectorAll('.admin-alert-row')];
                return Promise.all(rows.map(r => fetch('/api/alerts/' + r.dataset.alertId, {method:'DELETE'})));
            })()""")
            await navigate("/admin")
            assert await wait_for(client, "!!document.querySelector('#admin-alerts-open-btn')")
            await click("#admin-alerts-open-btn")
            assert await wait_for(client, "!!document.querySelector('#admin-alert-input')")
            assert await wait_for(client, "document.querySelectorAll('.admin-alert-row').length === 0")
            await add_alert(long_message, "critical")
            await add_alert("Short info line", "info")

            for screen, path in (("display", "/display"), ("admin-display", "/admin-display")):
                await navigate(path)
                assert await wait_for(
                    client,
                    "(() => { const t = document.querySelector('#alert-ticker');"
                    " return t && !t.hidden && t.classList.contains('is-visible'); })()",
                )
                info = await client.evaluate("""(() => {
                    const t = document.querySelector('#alert-ticker');
                    const vp = t.querySelector('.alert-ticker__viewport');
                    const text = t.querySelector('.alert-ticker__text');
                    const style = getComputedStyle(t);
                    return {
                        severity: t.className,
                        hasSeverityIcon: !!t.querySelector('.alert-ticker__severity svg'),
                        text: text.textContent,
                        position: style.position,
                        zIndex: style.zIndex,
                        overflow: text.scrollHeight - vp.clientHeight,
                    };
                })()""")
                assert "alert-ticker--critical" in info["severity"], info
                assert info["hasSeverityIcon"], info
                assert info["text"] == long_message, info
                assert info["position"] == "fixed", info
                assert info["overflow"] > 1, f"long message should overflow: {info}"
                await client.screenshot(str(ARTIFACTS / f"ticker-{screen}-critical.png"))

                # The ticker is an overlay: it must not push the presence layout.
                assert await client.evaluate(
                    "(() => { const t = document.querySelector('#alert-ticker');"
                    " const f = document.querySelector('.display-frame');"
                    " if (!f) return true;"
                    " const tr = t.getBoundingClientRect(); const fr = f.getBoundingClientRect();"
                    " return tr.top <= fr.top + 1; })()"
                )

                # The over-long message is revealed one line at a time, so the
                # text is translated at some point (transform leaves identity).
                moved = False
                for _ in range(48):
                    current = await client.evaluate(
                        "getComputedStyle(document.querySelector('.alert-ticker__text')).transform"
                    )
                    if "matrix" in current and current != "matrix(1, 0, 0, 1, 0, 0)":
                        moved = True
                        break
                    await asyncio.sleep(0.25)
                assert moved, f"ticker text never stepped to another line on {screen}"

                if screen == "display":
                    # Regression: after a multi-line alert, the next (short) alert
                    # must become visible again, not stay translated off-screen.
                    appeared = await wait_for(
                        client,
                        "(() => { const t = document.querySelector('#alert-ticker');"
                        " const txt = t.querySelector('.alert-ticker__text');"
                        " const m = getComputedStyle(txt).transform;"
                        " return (t.classList.contains('alert-ticker--info') && txt.textContent === 'Short info line'"
                        " && (m === 'none' || m === 'matrix(1, 0, 0, 1, 0, 0)')) ? true : null; })()",
                        timeout=25,
                    )
                    assert appeared, "the short alert never became visible after the multi-line alert"

            # Remove the long critical alert; the lone info alert must remain and
            # be shown without any further fading.
            await client.evaluate("""fetch('/api/alerts').then(r => r.json()).then(data => {
                const critical = data.alerts.find(a => a.severity === 'critical');
                return critical ? fetch('/api/alerts/' + critical.id, {method: 'DELETE'}) : null;
            })""")
            await navigate("/display")
            assert await wait_for(
                client,
                "(() => { const t = document.querySelector('#alert-ticker');"
                " return t && !t.hidden && t.classList.contains('alert-ticker--info') && t.classList.contains('is-visible'); })()",
            )
            await asyncio.sleep(1.0)
            assert await client.evaluate(
                "document.querySelector('#alert-ticker').classList.contains('is-visible')"
            ), "lone alert should stay visible without cycling"
            await client.screenshot(str(ARTIFACTS / "ticker-display-info.png"))

            errors = await client.evaluate("qaErrors")
            assert errors == [], errors
            resource_errors = await client.evaluate("qaResourceErrors")
            assert resource_errors == [], resource_errors
            requests = await client.evaluate(
                "performance.getEntriesByType('resource').filter(r => r.responseStatus >= 400).map(r => ({url: r.name, status: r.responseStatus}))"
            )
            assert requests == [], requests
            print("PASS: admin alerts pane (create, order, edit, all TTL presets, delete, stale-list responses, failed requests and retries) and ticker on both channels, no JS/resource errors")
            (ARTIFACTS / "results.json").write_text(json.dumps({"ok": True, "errors": [], "failed_requests": requests}, indent=2))
        finally:
            await client.close()


async def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="labauth-alerts-") as tmp:
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        env = {**os.environ, "PORT": str(port), "LABAUTH_DB_PATH": str(Path(tmp) / "test.db"), "LABAUTH_ADMIN_PASSWORD": PASSWORD}
        with open(Path(tmp) / "server.log", "w+") as log:
            proc = subprocess.Popen([sys.executable, "src/main.py"], cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    try:
                        urllib.request.urlopen(base + "/api/presence", timeout=1).close()
                        break
                    except Exception:
                        if proc.poll() is not None:
                            log.seek(0)
                            raise RuntimeError(log.read())
                        await asyncio.sleep(0.15)
                else:
                    raise RuntimeError("Test server startup timed out")
                await check_alerts(base, PASSWORD)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


if __name__ == "__main__":
    asyncio.run(main())
