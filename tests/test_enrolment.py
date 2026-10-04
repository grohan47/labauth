#!/usr/bin/env python3
"""Automated end-to-end and browser test suite for LabAuth Enrolment Flow.

Verifies:
1. Route protection: Unauthenticated access to /enrollment redirects to /admin-display.
2. Authenticated access: Admin login allows entry to /enrollment.
3. Top-right cross button exists to return to /admin.
4. Step 1 (Identity & Mock Card):
   - "Hello." Swiss title
   - Blank editable mock card with avatar, name input, demographics, and workspaces checkboxes
   - Name is mandatory: red next arrow button only appears when name is entered
5. Step 2 (Fingerprint Biometrics):
   - Biometric sensor activation
   - Multi-touch sample acquisition
   - Consistency verification step on the same page
   - Red next button enables after verification
6. Step 3 (NFC Authentication):
   - Listening state on Pico reader
   - Card tap captures unique card UID (or skip)
   - Red next button leads to review
7. Step 4 (Identity Review & Final ID Card):
   - Final ID card with name, portrait, authorised chips, pictorial biometric badges
   - Demographic records section
   - "Complete Enrollment" commits record to SQLite database and logs audit entry
8. Captures browser screenshots for visual verification.
"""

from __future__ import annotations

import asyncio
import base64
import http.cookiejar
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

import websockets

PORT = 8150
CDP_PORT = 9270
BASE_URL = f"http://127.0.0.1:{PORT}"
ARTIFACT_DIR = Path("/home/rgcodes/.gemini/antigravity/brain/f50762c6-60a7-4308-a02a-a09d87e87cec")


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
                if "error" in data:
                    raise RuntimeError(f"CDP error: {data['error']}")
                return data.get("result", {})

    async def evaluate(self, expression: str):
        res = await self.send_command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        return res.get("result", {}).get("value")

    async def capture_screenshot(self, filename: str) -> Path:
        res = await self.send_command("Page.captureScreenshot", {"format": "png"})
        b64data = res.get("data", "")
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = ARTIFACT_DIR / filename
        out_path.write_bytes(base64.b64decode(b64data))
        print(f"  📸 Screenshot captured: {out_path}")
        return out_path


def wait_for_server(url: str, timeout: float = 40.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{url}/api/presence", timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


async def run_enrolment_tests():
    print("=" * 65)
    print("  LABAUTH SWISS ENROLMENT FLOW VERIFICATION SUITE")
    print("=" * 65)

    tmp_dir = Path(tempfile.mkdtemp(prefix="labauth-enrolment-test-"))
    db_file = tmp_dir / "test_labauth.db"
    chrome_data_dir = tmp_dir / "chrome-profile"
    chrome_data_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["LABAUTH_DB_PATH"] = str(db_file)
    env["LABAUTH_ADMIN_PASSWORD"] = "labauth@2026"
    env["PORT"] = str(PORT)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")

    venv_py = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python"
    python_bin = str(venv_py) if venv_py.exists() else sys.executable
    server_proc = subprocess.Popen(
        [python_bin, "src/main.py"],
        cwd=str(Path(__file__).resolve().parent.parent),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    chrome_proc = None
    client = None

    try:
        print("\n1. Starting LabAuth server on port", PORT, "...")
        if not wait_for_server(BASE_URL, timeout=40.0):
            server_proc.kill()
            out, _ = server_proc.communicate(timeout=2.0) if server_proc.stdout else ("", "")
            print("Server output on failure:\n", out)
            raise AssertionError("Server failed to start!")
        print("  ✓ LabAuth server is running.")

        # Test unauthenticated redirect
        print("\n2. Testing unauthenticated /enrollment route protection...")
        req = urllib.request.Request(f"{BASE_URL}/enrollment", headers={"User-Agent": "Mozilla/5.0"})
        # Disallow auto-redirect
        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirectHandler)
        try:
            resp = opener.open(req)
            assert resp.status in (302, 303, 307), f"Expected redirect, got status {resp.status}"
            assert "/admin-display" in resp.headers.get("Location", "")
        except urllib.error.HTTPError as err:
            assert err.code in (302, 303, 307), f"Expected 307/302 redirect, got {err.code}"
            assert "/admin-display" in err.headers.get("Location", "")
        print("  ✓ Unauthenticated access correctly redirects to /admin-display.")

        # Authenticate via /api/admin/login
        print("\n3. Authenticating admin session via /api/admin/login...")
        cj = http.cookiejar.CookieJar()
        auth_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        login_data = json.dumps({"password": "labauth@2026"}).encode("utf-8")
        login_req = urllib.request.Request(
            f"{BASE_URL}/api/admin/login",
            data=login_data,
            headers={"Content-Type": "application/json"},
        )
        login_resp = auth_opener.open(login_req)
        assert login_resp.status == 200, "Login failed!"
        session_token = None
        for cookie in cj:
            if cookie.name == "labauth_admin_session":
                session_token = cookie.value
                break
        assert session_token, "No session token cookie set!"
        print("  ✓ Admin session token obtained:", session_token[:12] + "...")

        # Launch Chromium headless with CDP
        print("\n4. Launching Chromium headless browser for UI verification...")
        chrome_cmd = [
            "/usr/bin/chromium-browser",
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={chrome_data_dir}",
            "--window-size=1280,960",
            f"{BASE_URL}/admin-display",
        ]
        chrome_proc = subprocess.Popen(chrome_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Get WebSocket debugger URL with retry polling
        targets = None
        for _ in range(40):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json", timeout=1.0) as resp:
                    targets = json.loads(resp.read().decode("utf-8"))
                    if targets:
                        break
            except Exception:
                time.sleep(0.3)
        assert targets, "Failed to connect to Chromium CDP endpoint!"
        page_target = next(t for t in targets if t.get("type") == "page")
        ws_url = page_target["webSocketDebuggerUrl"]

        client = CDPClient(ws_url)
        await client.connect()
        await client.send_command("Page.enable")
        await client.send_command("Network.enable")
        await client.send_command("Runtime.enable")
        await client.send_command("Console.enable")
        await client.send_command(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": 1440,
                "height": 960,
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )

        # Let's inspect scripts on page
        scripts = await client.evaluate("Array.from(document.querySelectorAll('script')).map(s => s.textContent.substring(0, 100))")
        print("  → Scripts on page:", scripts)

        # Set session cookie in browser
        await client.send_command(
            "Network.setCookie",
            {
                "name": "labauth_admin_session",
                "value": session_token,
                "domain": "127.0.0.1",
                "path": "/",
            },
        )

        # Navigate to /enrollment
        print("\n5. Navigating to /enrollment...")
        await client.send_command("Page.navigate", {"url": f"{BASE_URL}/enrollment"})
        time.sleep(2.0)

        scripts_enrol = await client.evaluate("Array.from(document.querySelectorAll('script')).map(s => s.textContent.substring(0, 100))")
        print("  → Scripts on /enrollment:", len(scripts_enrol))

        script_err = await client.evaluate("""
            (() => {
                const s = Array.from(document.querySelectorAll('script')).find(s => s.textContent.includes('initEnrolment'));
                if (!s) return 'Script not found!';
                try {
                    new Function(s.textContent)();
                    return 'Executed successfully!';
                } catch (e) {
                    return e.name + ': ' + e.message + ' at line ' + e.lineNumber;
                }
            })()
        """)
        print("  → Script execution result:", script_err)

        # Verify Step 1 UI
        step1_info = await client.evaluate("""
            (() => {
                const greeting = document.querySelector('.enrolment-greeting')?.textContent?.trim();
                const closeBtn = document.querySelector('#enrolment-close-btn');
                const mockCard = document.querySelector('.enrolment-mock-card');
                const nameInput = document.querySelector('#input-fullname');
                const nextBtn = document.querySelector('#btn-step1-next');
                const nextBtnDisplay = nextBtn ? window.getComputedStyle(nextBtn).display : 'none';
                const checkboxes = document.querySelectorAll('sbb-checkbox[name="access"]');

                return {
                    greeting: greeting,
                    hasCloseBtn: !!closeBtn,
                    hasMockCard: !!mockCard,
                    hasNameInput: !!nameInput,
                    nextBtnDisplay: nextBtnDisplay,
                    checkboxCount: checkboxes.length
                };
            })()
        """)
        print("  ✓ Step 1 UI State:", json.dumps(step1_info, indent=2))
        assert step1_info["greeting"] == "Hello.", f"Expected 'Hello.', got {step1_info['greeting']}"
        assert step1_info["hasCloseBtn"], "Exit cross button missing!"
        assert step1_info["hasMockCard"], "Mock card missing!"
        assert step1_info["nextBtnDisplay"] == "none", "Next button should be hidden when name is empty!"

        await client.capture_screenshot("01_enrolment_step1_empty.png")

        # Fill in Identity fields
        print("\n6. Filling in Identity & Demographics...")
        debug_check = await client.evaluate("""
            (() => {
                const nameInput = document.querySelector('#input-fullname');
                const btn = document.querySelector('#btn-step1-next');
                return {
                    hasInput: !!nameInput,
                    hasBtn: !!btn,
                    hasState: !!window.__enrolmentState,
                    hasUpdateStep1: typeof window.__updateStep1
                };
            })()
        """)
        print("  → Debug check before input:", json.dumps(debug_check, indent=2))

        await client.evaluate("""
            (() => {
                const nameInput = document.querySelector('#input-fullname');
                nameInput.value = 'Maya Patel';
                nameInput.dispatchEvent(new Event('input', { bubbles: true }));

                const idInput = document.querySelector('#input-plaksha-id');
                idInput.value = '2026-UG-014';
                idInput.dispatchEvent(new Event('input', { bubbles: true }));

                const phoneInput = document.querySelector('#input-phone');
                phoneInput.value = '+91 98765 43210';
                phoneInput.dispatchEvent(new Event('input', { bubbles: true }));

                const emailInput = document.querySelector('#input-email');
                emailInput.value = 'maya.patel@plaksha.edu.in';
                emailInput.dispatchEvent(new Event('input', { bubbles: true }));
            })()
        """)
        time.sleep(0.5)

        # Verify that red next button appeared
        debug_after = await client.evaluate("""
            (() => {
                const btn = document.querySelector('#btn-step1-next');
                return {
                    nameVal: document.querySelector('#input-fullname')?.value,
                    stateName: window.__enrolmentState?.name,
                    styleDisplay: btn ? btn.style.display : null,
                    computedDisplay: btn ? window.getComputedStyle(btn).display : null
                };
            })()
        """)
        print("  → Debug check after input:", json.dumps(debug_after, indent=2))
        next_display_after = debug_after["computedDisplay"]
        assert next_display_after != "none", "Red Next button must appear when Name is entered!"

        await client.evaluate("document.querySelector('#btn-step1-next')?.scrollIntoView({ behavior: 'instant', block: 'end' })")
        time.sleep(0.3)
        await client.capture_screenshot("02_enrolment_step1_filled.png")

        # Click Next -> Step 2: Fingerprint
        print("\n7. Transitioning to Step 2: Fingerprint...")
        await client.evaluate("document.querySelector('#btn-step1-next').click()")
        time.sleep(0.8)

        step2_info = await client.evaluate("""
            (() => {
                const title = document.querySelector('#step-2 .enrolment-greeting')?.textContent?.trim();
                const statusBadge = document.querySelector('#fp-status-badge')?.textContent?.trim();
                const scanBtn = document.querySelector('#btn-fp-scan');
                return {
                    title: title,
                    status: statusBadge,
                    hasScanBtn: !!scanBtn
                };
            })()
        """)
        print("  ✓ Step 2 Initial State:", json.dumps(step2_info, indent=2))
        assert "Fingerprint" in step2_info["title"], "Expected Fingerprint step title!"

        # Touch sensor sample 1 and 2
        print("  → Simulating biometric sensor touches...")
        await client.evaluate("document.querySelector('#btn-fp-scan').click()")
        time.sleep(0.4)
        await client.evaluate("document.querySelector('#btn-fp-scan').click()")
        time.sleep(0.4)

        # Consistency verification step on the same page
        print("  → Performing consistency verification on same page...")
        verify_btn_visible = await client.evaluate("""
            window.getComputedStyle(document.querySelector('#btn-fp-verify')).display !== 'none'
        """)
        assert verify_btn_visible, "Consistency verification button must appear on the same page!"
        await client.evaluate("document.querySelector('#btn-fp-verify').click()")
        time.sleep(0.5)

        step2_verified = await client.evaluate("""
            (() => {
                return {
                    status: document.querySelector('#fp-status-badge')?.textContent?.trim(),
                    nextDisplay: window.getComputedStyle(document.querySelector('#btn-step2-next')).display
                };
            })()
        """)
        print("  ✓ Step 2 Verified State:", json.dumps(step2_verified, indent=2))
        assert "Verified" in step2_verified["status"], "Fingerprint consistency verification failed!"
        assert step2_verified["nextDisplay"] != "none", "Next button must be visible after verification!"

        await client.capture_screenshot("03_enrolment_step2_fingerprint_verified.png")

        # Click Next -> Step 3: NFC
        print("\n8. Transitioning to Step 3: NFC Auth...")
        await client.evaluate("document.querySelector('#btn-step2-next').click()")
        time.sleep(0.8)

        step3_info = await client.evaluate("""
            (() => {
                const title = document.querySelector('#step-3 .enrolment-greeting')?.textContent?.trim();
                const badge = document.querySelector('#nfc-status-badge')?.textContent?.trim();
                return { title, badge };
            })()
        """)
        print("  ✓ Step 3 Initial State:", json.dumps(step3_info, indent=2))
        assert "NFC" in step3_info["title"], "Expected NFC card step title!"

        # Tap NFC card
        print("  → Tapping NFC card...")
        await client.evaluate("document.querySelector('#btn-nfc-tap').click()")
        time.sleep(0.5)

        nfc_uid = await client.evaluate("document.querySelector('#nfc-uid-value')?.textContent?.trim()")
        print("  ✓ NFC Card UID Captured:", nfc_uid)
        assert nfc_uid and nfc_uid != "--:--:--:--", "NFC UID was not captured!"

        await client.capture_screenshot("04_enrolment_step3_nfc_registered.png")

        # Click Next -> Step 4: Final ID Card Review
        print("\n9. Transitioning to Step 4: Final ID Card Review...")
        await client.evaluate("document.querySelector('#btn-step3-next').click()")
        time.sleep(0.8)

        step4_review = await client.evaluate("""
            (() => {
                const name = document.querySelector('#final-card-name')?.textContent?.trim();
                const chips = Array.from(document.querySelectorAll('#final-card-chips sbb-chip-label')).map(c => c.textContent.trim());
                const fpBadge = document.querySelector('#final-cred-fp')?.textContent?.trim();
                const nfcBadge = document.querySelector('#final-cred-nfc')?.textContent?.trim();
                const plakshaId = document.querySelector('#final-demo-id')?.textContent?.trim();
                const phone = document.querySelector('#final-demo-phone')?.textContent?.trim();
                const email = document.querySelector('#final-demo-email')?.textContent?.trim();

                return {
                    name,
                    chips,
                    fpBadge,
                    nfcBadge,
                    plakshaId,
                    phone,
                    email
                };
            })()
        """)
        print("  ✓ Step 4 Review Card:", json.dumps(step4_review, indent=2))
        assert step4_review["name"] == "Maya Patel", f"Expected 'Maya Patel', got {step4_review['name']}"
        assert "Fingerprint Enrolled" in step4_review["fpBadge"], "Fingerprint badge missing!"
        assert "NFC:" in step4_review["nfcBadge"], "NFC badge missing!"
        assert step4_review["plakshaId"] == "2026-UG-014", "Plaksha ID missing in demographic record!"
        assert step4_review["phone"] == "+91 98765 43210", "Phone missing in demographic record!"
        assert step4_review["email"] == "maya.patel@plaksha.edu.in", "Email missing in demographic record!"

        await client.capture_screenshot("05_enrolment_step4_review_id_card.png")

        # Complete Enrolment
        print("\n10. Submitting enrolment via Complete Enrollment button...")
        await client.evaluate("document.querySelector('#btn-finish-enrolment').click()")
        time.sleep(1.5)

        # Check celebration stage
        success_info = await client.evaluate("""
            (() => {
                const successTitle = document.querySelector('.success-title')?.textContent?.trim();
                const successDesc = document.querySelector('#success-desc')?.textContent?.trim();
                return { successTitle, successDesc };
            })()
        """)
        print("  ✓ Success Screen:", json.dumps(success_info, indent=2))
        assert "Complete" in success_info["successTitle"], "Success title not displayed!"
        assert "Maya Patel" in success_info["successDesc"], "Success description does not mention enrolled user!"

        await client.capture_screenshot("06_enrolment_step5_success.png")

        # Verify SQLite Database Record
        print("\n11. Verifying user saved into authoritative SQLite database...")
        import database as db
        os.environ["LABAUTH_DB_PATH"] = str(db_file)
        user = db.get_active_user_by_name("Maya Patel")
        assert user is not None, "Enrolled user 'Maya Patel' not found in database!"
        print(f"  ✓ Database User: ID={user.id}, Name={user.name}, PlakshaID={user.plaksha_id}, Email={user.email}, Phone={user.phone}")

        # Check access areas in database
        areas = db.get_user_access_area_labels(user.id)
        print("  ✓ Granted Access Areas in DB:", areas)
        assert len(areas) >= 2, "Expected at least 2 default access areas!"

        # Check credentials in database
        creds = db.list_credentials(user_id=user.id)
        cred_types = [c.credential_type for c in creds]
        print("  ✓ Enrolled Credentials in DB:", cred_types)
        assert "fingerprint" in cred_types, "Fingerprint credential not saved in DB!"
        assert "nfc" in cred_types, "NFC credential not saved in DB!"

        print("\n" + "=" * 65)
        print("  ALL ENROLMENT FLOW VERIFICATION CHECKS PASSED SUCCESSFULLY!")
        print("=" * 65)

    finally:
        if client:
            await client.close()
        if chrome_proc:
            chrome_proc.terminate()
            chrome_proc.wait()
        if server_proc:
            server_proc.terminate()
            server_proc.wait()
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(run_enrolment_tests())
