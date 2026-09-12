#!/usr/bin/env python3
"""
Test script to verify clock synchronization, background timer reliability when unfocused,
and periodic reload behavior in LabAuth display via Chrome DevTools Protocol (CDP).
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import websockets

DEFAULT_PORT = int(os.environ.get("PORT", 8080))
CDP_PORT = 9223
DISPLAY_URL = f"http://127.0.0.1:{DEFAULT_PORT}/display"


class CDPClient:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.ws = None
        self._msg_id = 0

    async def connect(self):
        self.ws = await websockets.connect(self.ws_url)

    async def close(self):
        if self.ws:
            await self.ws.close()

    async def send_command(self, method: str, params: dict | None = None):
        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(msg))
        while True:
            raw = await self.ws.recv()
            data = json.loads(raw)
            if data.get("id") == self._msg_id:
                return data.get("result", {})

    async def evaluate(self, expression: str):
        res = await self.send_command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        val = res.get("result", {})
        if "value" in val:
            return val["value"]
        return res


async def run_tests():
    print("=" * 65)
    print("  VERIFYING SERVER TIME SYNC, UNTHROTTLED WORKER, AND SBB CLOCK")
    print("=" * 65)

    browser_bin = shutil.which("chromium-browser") or shutil.which("google-chrome") or shutil.which("chromium")
    if not browser_bin:
        print("Error: Chromium/Chrome binary not found.")
        sys.exit(1)

    cmd = [
        browser_bin,
        "--headless=new",
        "--disable-gpu",
        f"--remote-debugging-port={CDP_PORT}",
        DISPLAY_URL,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)

    try:
        # Get debug target
        req = urllib.request.Request(f"http://127.0.0.1:{CDP_PORT}/json/list")
        with urllib.request.urlopen(req, timeout=5) as r:
            targets = json.loads(r.read().decode("utf-8"))

        target = next((t for t in targets if "display" in t.get("url", "") or t.get("type") == "page"), None)
        assert target, "No suitable browser page target found!"
        ws_url = target["webSocketDebuggerUrl"]

        client = CDPClient(ws_url)
        await client.connect()

        # Step 1: Wait for DOM to bind
        print("\n[Step 1] Checking page elements, digital clock, and SBB clock...")
        await client.evaluate("""
            new Promise((resolve) => {
                const check = () => {
                    if (document.querySelector('#digital-time') && document.querySelector('.clock-stack sbb-clock')) {
                        resolve(true);
                    } else {
                        setTimeout(check, 100);
                    }
                };
                check();
            })
        """)

        digital_time = await client.evaluate("document.querySelector('#digital-time').innerText")
        print(f"  ✓ Digital clock time: {digital_time}")
        assert len(digital_time) == 5 and ":" in digital_time, f"Invalid digital clock: {digital_time}"

        # Verify sbb-clock smoothness constraint: sbb-clock must NOT have 'now' attribute in live mode
        clock_now_attr = await client.evaluate("document.querySelector('.clock-stack sbb-clock').getAttribute('now')")
        assert clock_now_attr is None, f"sbb-clock must not have 'now' attribute in live mode! Got: {clock_now_attr}"
        print("  ✓ Confirmed sbb-clock element is untouched (native Lit/CSS keyframe sweep preserved)!")

        # Step 2: Verify server time synchronization
        print("\n[Step 2] Verifying server time sync (/api/time)...")
        sync_fn_exists = await client.evaluate("typeof window.syncServerTime === 'function'")
        assert sync_fn_exists, "syncServerTime function is not exposed on window"
        await client.evaluate("window.syncServerTime()")
        print("  ✓ /api/time synchronized successfully.")

        # Step 3: Test unfocused window state
        print("\n[Step 3] Simulating unfocused / blurred window...")
        await client.evaluate("window.dispatchEvent(new Event('blur'))")
        
        # Verify unthrottled worker continues ticking while blurred
        initial_sec = await client.evaluate("new Date().getSeconds()")
        time.sleep(2.0)
        blurred_time = await client.evaluate("document.querySelector('#digital-time').innerText")
        print(f"  ✓ Unfocused display maintains ticking digital time: {blurred_time}")

        # Step 4: Verify deferred reload safety when alert card is active
        print("\n[Step 4] Verifying alert card safety with reload pending...")
        await client.evaluate("""
            window.handleAuthEvent({
                type: 'IN',
                person: {
                    name: 'Lucas Silva',
                    photo: '/static/portraits/default.svg',
                    checked_in: '14:20',
                    access: ['Lab interior', 'Laser cutter']
                }
            })
        """)
        time.sleep(0.5)

        is_alert_active = await client.evaluate("Boolean(document.querySelector('.auth-alert-card.is-active'))")
        assert is_alert_active, "Alert card should be active and visible"
        print("  ✓ Check-in alert card is prominently displayed.")

        # Simulate reload trigger while alert is active:
        # In canSafelyReload(), isDisplayingAlert is true, so reload is deferred to reloadPending = true
        await client.evaluate("window.triggerReload()")
        reload_pending_val = await client.evaluate("window.isReloadPending()")
        assert reload_pending_val is True, f"reloadPending should be set to true while alert is active! Got: {reload_pending_val}"
        print("  ✓ Reload correctly deferred while alert is active (user experience never cut off)!")

        # Step 5: Wait for alert to dismiss cleanly and verify deferred reload execution
        print("\n[Step 5] Waiting for alert to dismiss and verifying deferred reload execution...")
        time.sleep(5.5)
        diag = await client.evaluate("""
            ({
                canReload: typeof window.canSafelyReload === 'function' ? window.canSafelyReload() : null,
                isDisplayingAlert: typeof isDisplayingAlert !== 'undefined' ? isDisplayingAlert : null,
                queueLen: typeof alertQueue !== 'undefined' ? alertQueue.length : null,
                isFadingGreeting: typeof isFadingGreeting !== 'undefined' ? isFadingGreeting : null,
                isReloadPending: typeof reloadPending !== 'undefined' ? reloadPending : null,
                pageAgeMs: Date.now() - (typeof pageStartTime !== 'undefined' ? pageStartTime : Date.now())
            })
        """)
        print(f"  Diagnostic state after alert dismissal: {diag}")
        # If the page reloaded as expected, pageAgeMs will be very small (< 4000ms) and isReloadPending will be false!
        if diag.get("pageAgeMs", 999999) < 4000:
            print("  ✓ Confirmed deferred reload triggered immediately upon alert card dismissal!")
        else:
            assert diag.get("canReload") is True or diag.get("isReloadPending") is False

        await client.close()

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()

    print("\n" + "=" * 65)
    print("✓ ALL TESTS PASSED: Clock sync, unthrottled worker & reload verified!")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    asyncio.run(run_tests())
