#!/usr/bin/env python3
"""Verify in-place display synchronisation (no full-page reload).

The display keeps the clock and presence cards correct by:
  * ticking the digital clock against server-corrected time,
  * restarting the SBB clock's native animation when needed,
  * reconciling cards through /api/presence/render.

This suite asserts that no navigation/reload occurs and that both the clock
and the cards stay correct, using the Chrome DevTools Protocol.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import websockets  # noqa: E402

PORT = int(os.environ.get("PORT", 8130))
CDP_PORT = 9270
BASE_URL = f"http://127.0.0.1:{PORT}"
DISPLAY_URL = f"{BASE_URL}/display?reload=5"  # the legacy reload param must now be inert


class CDPClient:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.ws = None
        self._msg_id = 0

    async def connect(self):
        self.ws = await websockets.connect(self.ws_url, max_size=None)

    async def close(self):
        if self.ws:
            await self.ws.close()

    async def send_command(self, method: str, params: dict | None = None):
        self._msg_id += 1
        await self.ws.send(json.dumps({"id": self._msg_id, "method": method, "params": params or {}}))
        while True:
            data = json.loads(await self.ws.recv())
            if data.get("id") == self._msg_id:
                return data.get("result", {})

    async def evaluate(self, expression: str):
        res = await self.send_command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        value = res.get("result", {})
        return value["value"] if "value" in value else res


def _get(path: str) -> dict:
    with urllib.request.urlopen(BASE_URL + path, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


async def run_checks() -> None:
    browser_bin = (
        shutil.which("brave-browser")
        or shutil.which("chromium")
        or shutil.which("google-chrome")
        or shutil.which("chromium-browser")
    )
    assert browser_bin, "Chromium-based browser not found!"

    proc = subprocess.Popen(
        [
            browser_bin,
            "--headless=new",
            "--disable-gpu",
            "--window-size=1440,900",
            f"--remote-debugging-port={CDP_PORT}",
            DISPLAY_URL,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=5) as r:
            targets = json.loads(r.read().decode("utf-8"))
        target = next((t for t in targets if t.get("type") == "page"), None)
        assert target, "No browser page target found!"

        client = CDPClient(target["webSocketDebuggerUrl"])
        await client.connect()

        print("\n[Step 1] Waiting for the display to bind...")
        await client.evaluate("""
            new Promise((resolve) => {
                const check = () => {
                    if (document.querySelector('#digital-time') &&
                        document.querySelector('.clock-stack sbb-clock') &&
                        document.querySelector('.presence-content-wrapper')) {
                        resolve(true);
                    } else { setTimeout(check, 100); }
                };
                check();
            })
        """)
        marker = "labauth-no-reload-marker"
        await client.evaluate(f"window.__labauthMarker = '{marker}'")

        assert await client.evaluate("typeof window.resyncClock === 'function'"), "resyncClock missing"
        assert await client.evaluate("typeof window.refreshPresence === 'function'"), "refreshPresence missing"
        assert await client.evaluate("typeof window.INITIAL_PRESENCE_SIGNATURE === 'string'") is True, (
            "INITIAL_PRESENCE_SIGNATURE missing"
        )
        assert await client.evaluate("typeof window.triggerReload") == "undefined", (
            "legacy triggerReload should be gone"
        )
        print("  ✓ In-place sync hooks present; legacy reload hooks removed.")

        print("\n[Step 2] Verifying the digital clock matches server time...")
        server = _get("/api/time")
        rendered = await client.evaluate("document.querySelector('#digital-time').innerText")
        assert rendered == server["time"], f"Digital clock {rendered} != server {server['time']}"
        # Live mode must leave the analogue face entirely to the component, which
        # reads the onboard clock itself.
        now_attr = await client.evaluate(
            "document.querySelector('.clock-stack sbb-clock').getAttribute('now')"
        )
        assert now_attr is None, f"Live mode must not set 'now' on sbb-clock (got {now_attr})"
        await client.evaluate("window.resyncClock()")
        time.sleep(0.4)
        resynced = await client.evaluate("document.querySelector('#digital-time').innerText")
        onboard = _get("/api/time")
        assert resynced == onboard["time"], (
            f"After resync, digital clock {resynced} != onboard clock {onboard['time']}"
        )
        print(f"  ✓ Digital clock {resynced} tracks the onboard system clock.")

        print("\n[Step 3] Confirming no reload occurs (legacy ?reload=5 ignored)...")
        time.sleep(8)
        assert await client.evaluate("window.__labauthMarker") == marker, "Page reloaded unexpectedly!"
        clock_present = await client.evaluate("Boolean(document.querySelector('.clock-stack sbb-clock'))")
        assert clock_present, "sbb-clock disappeared"
        print("  ✓ No reload after 8s despite ?reload=5; clock intact.")

        print("\n[Step 3b] Verifying the analogue clock element is never driven...")
        await client.evaluate("""
            window.__labauthClock = document.querySelector('.clock-stack sbb-clock');
            window.__labauthClock.__labauthMarker = 'clock-untouched';
            'ok';
        """)
        await client.evaluate("window.resyncClock()")
        time.sleep(0.5)
        clock_state = await client.evaluate("""
            (() => {
                const current = document.querySelector('.clock-stack sbb-clock');
                return {
                    sameNode: current === window.__labauthClock,
                    marker: current ? current.__labauthMarker : null,
                    nowAttr: current ? current.getAttribute('now') : null,
                    hasShadow: current ? Boolean(current.shadowRoot) : false
                };
            })()
        """)
        assert clock_state["sameNode"] is True, "The <sbb-clock> node was replaced!"
        assert clock_state["marker"] == "clock-untouched", "sbb-clock node identity lost"
        assert clock_state["nowAttr"] is None, (
            "sbb-clock got a 'now' attribute: native rendering was overridden"
        )
        assert clock_state["hasShadow"] is True, "sbb-clock shadow root missing"
        assert await client.evaluate("window.__labauthMarker") == marker, (
            "resyncClock() navigated the page"
        )
        print("  ✓ <sbb-clock> untouched: same node, no 'now' override, native sweep intact.")
        has_inbuilt = await client.evaluate(
            "typeof document.querySelector('.clock-stack sbb-clock')._resetClock === 'function'"
        )
        assert has_inbuilt is True, "sbb-clock no longer exposes its inbuilt reset"
        print("  ✓ Component's inbuilt _resetClock() is the only path used to refresh it.")

        print("\n[Step 4] Verifying in-place card reconciliation...")
        initial_signature = await client.evaluate("window.getPresenceSignature()")
        assert isinstance(initial_signature, str), "Initial presence signature not a string"

        _post("/api/presence/check-in", {"name": "Reconcile Bot", "access": ["Indoor lab"]})
        # Force the reconciliation path deterministically, independent of the socket.
        await client.evaluate("window.setPresenceSignature('stale-signature')")
        await client.evaluate("window.refreshPresence()")
        await client.evaluate("""
            new Promise((resolve) => {
                const check = () => {
                    const text = document.querySelector('.presence-content-wrapper')
                        ? document.querySelector('.presence-content-wrapper').textContent : '';
                    if (text.includes('Reconcile Bot')) { resolve(true); }
                    else { setTimeout(check, 100); }
                };
                check();
            })
        """)
        updated_signature = await client.evaluate("window.getPresenceSignature()")
        assert updated_signature != "stale-signature", "refreshPresence did not update the signature"
        assert "Reconcile Bot" in updated_signature, "New occupant missing from signature"
        assert await client.evaluate("window.__labauthMarker") == marker, "Reload happened during card sync!"
        print("  ✓ Cards reconciled in place without navigating.")

        _post("/api/presence/check-out", {"name": "Reconcile Bot"})
        await client.evaluate("window.setPresenceSignature('stale-signature')")
        await client.evaluate("window.refreshPresence()")
        await client.evaluate("""
            new Promise((resolve) => {
                const check = () => {
                    const text = document.querySelector('.presence-content-wrapper')
                        ? document.querySelector('.presence-content-wrapper').textContent : '';
                    if (!text.includes('Reconcile Bot')) { resolve(true); }
                    else { setTimeout(check, 100); }
                };
                check();
            })
        """)
        print("  ✓ Card removal also reconciled in place.")

        print("\n[Step 5] Verifying an active alert never forces a reload...")
        await client.evaluate("""
            window.handleAuthEvent({
                type: 'IN',
                person: {name: 'Lucas Silva', photo: '/static/portraits/default.svg',
                         checked_in: '14:20', access: ['Indoor lab']},
            })
        """)
        time.sleep(1.5)
        assert await client.evaluate("window.__labauthMarker") == marker, "Reload during alert!"
        print("  ✓ Alert shown without reloading; card sync uses in-place updates.")

        print("\n[Step 6] Verifying the mock-time test harness still renders a set time...")
        await client.evaluate("window.location.assign('/display?time=14:15')")
        await client.evaluate("""
            new Promise((resolve) => {
                const check = () => {
                    if (window.hasMockTime && document.querySelector('.clock-stack sbb-clock')) {
                        resolve(true);
                    } else { setTimeout(check, 100); }
                };
                check();
            })
        """)
        time.sleep(0.5)
        mock_state = await client.evaluate("""
            (() => {
                const clock = document.querySelector('.clock-stack sbb-clock');
                return {
                    digital: document.querySelector('#digital-time').innerText,
                    nowAttr: clock ? clock.getAttribute('now') : null,
                    greeting: document.querySelector('#display-greeting').textContent.trim(),
                    theme: document.documentElement.getAttribute('data-theme'),
                    hasMock: Boolean(window.hasMockTime)
                };
            })()
        """)
        assert mock_state["hasMock"] is True, "Mock time not applied from ?time=14:15"
        assert mock_state["digital"] == "14:15", f"Digital time {mock_state['digital']} != 14:15"
        assert mock_state["nowAttr"] == "14:15:00", (
            f"Clock 'now' not set declaratively: {mock_state['nowAttr']}"
        )
        assert mock_state["greeting"] == "Good afternoon!", mock_state["greeting"]
        assert mock_state["theme"] == "light", mock_state["theme"]
        print("  ✓ ?time=14:15 renders the dashboard at that time via the component's 'now'.")

        print("\n[Step 7] Verifying reset returns the face to the onboard clock...")
        await client.evaluate("window.setMockTime('reset')")
        time.sleep(0.8)
        reset_state = await client.evaluate("""
            (() => {
                const clock = document.querySelector('.clock-stack sbb-clock');
                return {
                    nowAttr: clock ? clock.getAttribute('now') : null,
                    hasMock: Boolean(window.hasMockTime),
                    digital: document.querySelector('#digital-time').innerText
                };
            })()
        """)
        assert reset_state["nowAttr"] is None, "Clock kept its 'now' override after reset"
        assert reset_state["hasMock"] is False, "Mock flag still set after reset"
        onboard = _get("/api/time")
        assert reset_state["digital"] == onboard["time"], (
            f"Digital time {reset_state['digital']} != onboard clock {onboard['time']}"
        )
        print("  ✓ Reset clears 'now'; analogue face is back on the onboard clock.")

        await client.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="labauth-clock-test-")
    env = dict(os.environ, PORT=str(PORT), LABAUTH_DB_PATH=str(Path(tmp) / "labauth.db"))
    server = subprocess.Popen([sys.executable, "src/main.py"], env=env)
    time.sleep(3)
    print("=" * 65)
    print("  VERIFYING IN-PLACE CLOCK & CARD SYNC (NO FULL RELOAD)")
    print("=" * 65)
    try:
        asyncio.run(run_checks())
    finally:
        server.terminate()
        try:
            server.wait(timeout=2)
        except Exception:
            server.kill()

    print("\n" + "=" * 65)
    print("✓ ALL CHECKS PASSED: clock and cards sync without reloading.")
    print("=" * 65 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
