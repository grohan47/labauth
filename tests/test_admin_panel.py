#!/usr/bin/env python3
"""
Automated tests for the LabAuth Admin Panel (/admin).
Verifies:
1. Hardcoded admin password (labauth@2026) and session cookie generation.
2. Route protection: Unauthenticated access to /admin and /enrollment redirects to /admin-display.
3. Authenticated Admin Panel UI (/admin):
   - Top-left "Admin." in large Helvetica font.
   - Top-right pure SBB clock with no date or digital time.
   - Top-right Exit button.
   - 5 large rectangular Lyne cards in a coordinate grid:
     1) Enrollment (fingerprint-medium icon) -> /enrollment
     2) Logs (document-text-medium icon) -> /logs
     3) Search (magnifying-glass-medium icon) -> /search
     4) Alerts (sign-exclamation-point-medium icon) -> /admin-alerts-dialog
     5) Display settings (controls-medium icon) -> /admin/display-settings
4. Alerts dialog: typing, broadcasting, and clearing an alert via /api/alerts.
5. Enrollment route (/enrollment) validates active admin session.
6. Exit button logs out, clears session, and redirects to /admin-display.
"""

import asyncio
import http.cookiejar
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cdp import Browser, CDPClient, wait_for  # noqa: E402

PORT = 8120
BASE_URL = f"http://127.0.0.1:{PORT}"
ARTIFACT_DIR = "/home/rgcodes/.gemini/antigravity/brain/7f11aec8-5a1b-44ae-b22e-d3863d7469f9"


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def test_auth_and_session_routes():
    print("\n[Test 1] Testing authentication, session management, and route protection...")
    login_url = f"{BASE_URL}/api/admin/login"
    opener_no_redirect = urllib.request.build_opener(NoRedirectHandler)

    # 1a: Unauthenticated access to /admin should redirect to /admin-display
    try:
        opener_no_redirect.open(f"{BASE_URL}/admin")
        assert False, "Expected redirect from /admin without auth"
    except urllib.error.HTTPError as e:
        assert e.code in (302, 307), f"Expected 302/307, got {e.code}"
        loc = e.headers.get("Location")
        assert "/admin-display" in loc, f"Expected redirect to /admin-display, got {loc}"
        print(f"  ✓ Unauthenticated /admin correctly redirects to /admin-display ({e.code} -> {loc}).")

    # 1b: Unauthenticated access to /enrollment should redirect to /admin-display
    try:
        opener_no_redirect.open(f"{BASE_URL}/enrollment")
        assert False, "Expected redirect from /enrollment without auth"
    except urllib.error.HTTPError as e:
        assert e.code in (302, 307), f"Expected 302/307, got {e.code}"
        loc = e.headers.get("Location")
        assert "/admin-display" in loc, f"Expected redirect to /admin-display, got {loc}"
        print(f"  ✓ Unauthenticated /enrollment correctly redirects to /admin-display ({e.code} -> {loc}).")

    # 1c: Login with wrong password rejected
    req = urllib.request.Request(
        login_url,
        data=json.dumps({"password": "incorrect"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            assert False, "Expected 401"
    except urllib.error.HTTPError as e:
        assert e.code == 401, f"Expected 401, got {e.code}"
        print("  ✓ Invalid password rejected with HTTP 401.")

    # 1d: Login with hardcoded password (labauth@2026)
    req = urllib.request.Request(
        login_url,
        data=json.dumps({"password": "labauth@2026"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        data = json.loads(resp.read().decode("utf-8"))
        assert data.get("status") == "ok"
        assert data.get("redirect") == "/admin"
        set_cookie = resp.headers.get("Set-Cookie", "")
        assert "labauth_admin_session=" in set_cookie
        print("  ✓ Valid password authorized with HTTP 200 and session cookie issued.")

    # Extract session cookie
    session_cookie = set_cookie.split(";")[0]

    # 1e: Authenticated access to /admin with cookie succeeds
    req_admin = urllib.request.Request(f"{BASE_URL}/admin", headers={"Cookie": session_cookie})
    with urllib.request.urlopen(req_admin) as resp:
        assert resp.status == 200
        html = resp.read().decode("utf-8")
        assert "Admin." in html
        print("  ✓ Authenticated /admin loaded successfully with session cookie.")

    # 1f: Authenticated access to /enrollment with cookie succeeds
    req_enroll = urllib.request.Request(f"{BASE_URL}/enrollment", headers={"Cookie": session_cookie})
    with urllib.request.urlopen(req_enroll) as resp:
        assert resp.status == 200
        html = resp.read().decode("utf-8")
        assert "step-1" in html
        print("  ✓ Authenticated /enrollment loaded successfully with session cookie.")

    # 1g: Test alerts API (create/list/update/delete). Mutations need a session.
    def alert_request(method, url, payload=None, cookie=session_cookie):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        return urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        urllib.request.urlopen(alert_request("POST", f"{BASE_URL}/api/alerts", {"message": "nope", "severity": "info"}, cookie=None))
        assert False, "Expected an unauthenticated alert mutation to be rejected"
    except urllib.error.HTTPError as e:
        assert e.code == 401, f"Expected 401, got {e.code}"
        print("  ✓ Unauthenticated POST /api/alerts rejected with HTTP 401.")

    with urllib.request.urlopen(alert_request(
        "POST", f"{BASE_URL}/api/alerts",
        {"message": "Attention: Ventilation testing at 17:00", "severity": "caution"},
    )) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert data["alert"]["message"] == "Attention: Ventilation testing at 17:00"
        assert data["alert"]["severity"] == "caution"
        alert_id = data["alert"]["id"]
        print("  ✓ POST /api/alerts created a caution alert.")

    with urllib.request.urlopen(f"{BASE_URL}/api/alerts") as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert any(a["id"] == alert_id for a in data["alerts"])
        print("  ✓ GET /api/alerts lists active alerts.")

    with urllib.request.urlopen(alert_request(
        "PUT", f"{BASE_URL}/api/alerts/{alert_id}",
        {"message": "Updated announcement", "severity": "critical", "ttl_seconds": 3600},
    )) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert data["alert"]["message"] == "Updated announcement"
        assert data["alert"]["severity"] == "critical"
        assert data["alert"]["remaining_seconds"] is not None
        print("  ✓ PUT /api/alerts updated message, severity and expiry.")

    with urllib.request.urlopen(alert_request("DELETE", f"{BASE_URL}/api/alerts/{alert_id}")) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert all(a["id"] != alert_id for a in data["alerts"])
        print("  ✓ DELETE /api/alerts removed the alert.")

    # 1h: Logout invalidates session
    req_logout = urllib.request.Request(
        f"{BASE_URL}/api/admin/logout",
        headers={"Cookie": session_cookie},
        method="POST",
    )
    with urllib.request.urlopen(req_logout) as resp:
        assert resp.status == 200
        clear_cookie = resp.headers.get("Set-Cookie", "")
        assert "labauth_admin_session=" in clear_cookie
        print("  ✓ POST /api/admin/logout cleared cookie and session.")

    # 1i: Accessing /enrollment with old cookie is now rejected
    try:
        opener_no_redirect.open(req_enroll)
        assert False, "Expected redirect from /enrollment after logout"
    except urllib.error.HTTPError as e:
        assert e.code in (302, 307)
        print("  ✓ Old session cookie is rejected after logout.")


async def test_browser_admin_panel():
    print("\n[Test 2] Launching headless browser for end-to-end Admin Panel UI verification...")
    with Browser(f"{BASE_URL}/admin-display") as browser:
        client = await browser.page()

        # Step 2a: Log in through /admin-display dialog
        print("  → Logging into admin via /admin-display dialog...")
        clicked = await wait_for(
            client,
            "(() => { const b = document.querySelector('#admin-access-button');"
            " if (!b) return false; b.click(); return true; })()",
        )
        assert clicked, "Admin access button never appeared"
        time.sleep(0.8)

        # Enter password and submit
        await client.evaluate("""
            (() => {
                const input = document.querySelector('#admin-password-input');
                input.value = 'labauth@2026';
                document.querySelector('#admin-password-form').dispatchEvent(new Event('submit', { cancelable: true }));
            })()
        """)

        # Wait for redirect to /admin
        print("  → Waiting for redirection to /admin...")
        await client.evaluate("""
            new Promise((resolve) => {
                const check = () => {
                    if (window.location.pathname === '/admin' && document.querySelector('.admin-heading')) {
                        resolve(true);
                    } else {
                        setTimeout(check, 100);
                    }
                };
                check();
            })
        """)
        time.sleep(1.0)
        print("  ✓ Arrived at /admin successfully.")

        # Step 2b: Verify Admin Panel structure and layout
        panel_info = await client.evaluate("""
            (() => {
                const heading = document.querySelector('.admin-heading');
                const headingStyle = heading ? window.getComputedStyle(heading) : null;
                const clockWrap = document.querySelector('.admin-clock-wrapper');
                const clock = document.querySelector('.admin-clock-wrapper sbb-clock');
                const dateEl = document.querySelector('#clock-date');
                const digitalEl = document.querySelector('#digital-time');
                const exitBtn = document.querySelector('#admin-exit-btn');
                const grid = document.querySelector('.admin-cards-grid');
                const cards = document.querySelectorAll('.admin-card');

                const cardDetails = Array.from(cards).map(card => {
                    const link = card.querySelector('sbb-card-link');
                    const btn = card.querySelector('sbb-card-button');
                    const icon = card.querySelector('sbb-icon');
                    const label = card.querySelector('.admin-card-label');
                    const rect = card.getBoundingClientRect();
                    return {
                        href: link ? link.getAttribute('href') : null,
                        actionType: link ? 'link' : (btn ? 'button' : null),
                        iconName: icon ? icon.getAttribute('name') : null,
                        label: label ? label.textContent.trim() : null,
                        width: rect.width,
                        height: rect.height
                    };
                });

                return {
                    bodyWidth: document.body.getBoundingClientRect().width,
                    mainWidth: document.querySelector('.admin-panel')?.getBoundingClientRect().width,
                    containerWidth: document.querySelector('.admin-panel-shell')?.getBoundingClientRect().width,
                    gridWidth: grid?.getBoundingClientRect().width,
                    headerWidth: document.querySelector('.admin-header')?.getBoundingClientRect().width,
                    headingText: heading ? heading.textContent.trim() : null,
                    headingFont: headingStyle ? headingStyle.fontFamily : null,
                    headingFontSize: headingStyle ? headingStyle.fontSize : null,
                    headingFontWeight: headingStyle ? headingStyle.fontWeight : null,
                    hasClock: !!clock,
                    hasDate: !!dateEl,
                    hasDigitalTime: !!digitalEl,
                    hasExitBtn: !!exitBtn,
                    cardCount: cards.length,
                    cardDetails: cardDetails,
                    gridDisplay: grid ? window.getComputedStyle(grid).display : null
                };
            })()
        """)
        print("  ✓ Panel layout details:", json.dumps(panel_info, indent=4))

        # Assertions on Admin Panel
        assert panel_info["headingText"] == "Admin.", f"Expected 'Admin.', got '{panel_info['headingText']}'"
        assert "Helvetica" in panel_info["headingFont"], f"Expected Helvetica in font family, got '{panel_info['headingFont']}'"
        assert int(panel_info["headingFontWeight"]) >= 700, f"Expected bold heading, got weight '{panel_info['headingFontWeight']}'"
        assert panel_info["hasClock"], "SBB Clock missing on /admin!"
        assert not panel_info["hasDate"], "Date display should NOT be present on /admin clock!"
        assert not panel_info["hasDigitalTime"], "Digital time display should NOT be present on /admin clock!"
        assert panel_info["hasExitBtn"], "Exit button missing on /admin!"
        assert panel_info["cardCount"] == 5, f"Expected 5 cards, found {panel_info['cardCount']}"
        assert panel_info["gridDisplay"] == "grid", "Cards container is not a CSS grid!"

        # Verify each of the 5 cards
        labels = [c["label"] for c in panel_info["cardDetails"]]
        assert "Enrollment" in labels, "Enrollment card missing!"
        assert "Logs" in labels, "Logs card missing!"
        assert "Search" in labels, "Search card missing!"
        assert "Alerts" in labels, "Alerts card missing!"
        assert "Display settings" in labels, "Display settings card missing!"

        enroll_card = next(c for c in panel_info["cardDetails"] if c["label"] == "Enrollment")
        assert enroll_card["href"] == "/enrollment", f"Expected /enrollment href, got {enroll_card['href']}"
        assert "fingerprint" in enroll_card["iconName"], f"Expected fingerprint icon, got {enroll_card['iconName']}"
        assert enroll_card["height"] >= 140, f"Card height too small ({enroll_card['height']}px)"

        logs_card = next(c for c in panel_info["cardDetails"] if c["label"] == "Logs")
        assert logs_card["href"] == "/logs", f"Expected /logs href, got {logs_card['href']}"
        assert "document-text" in logs_card["iconName"], f"Expected document-text icon, got {logs_card['iconName']}"

        search_card = next(c for c in panel_info["cardDetails"] if c["label"] == "Search")
        assert search_card["href"] == "/search", f"Expected /search href, got {search_card['href']}"
        assert "magnifying-glass" in search_card["iconName"], f"Expected magnifying-glass icon, got {search_card['iconName']}"

        alerts_card = next(c for c in panel_info["cardDetails"] if c["label"] == "Alerts")
        assert "sign-exclamation-point" in alerts_card["iconName"], f"Expected sign-exclamation-point icon, got {alerts_card['iconName']}"

        settings_card = next(c for c in panel_info["cardDetails"] if c["label"] == "Display settings")
        assert settings_card["href"] == "/admin/display-settings", f"Expected /admin/display-settings href, got {settings_card['href']}"
        assert "controls" in settings_card["iconName"], f"Expected controls icon, got {settings_card['iconName']}"

        # Capture screenshot of Admin Panel
        os.makedirs(ARTIFACT_DIR, exist_ok=True)
        screenshot_admin = os.path.join(ARTIFACT_DIR, "admin_panel_overview.png")
        await client.screenshot(screenshot_admin)

        # Step 2c: Test Alerts dialog interaction
        print("\n  → Testing Alerts modal dialog interaction...")
        await client.evaluate("document.querySelector('#admin-alerts-open-btn, #admin-card-alerts').click()")
        time.sleep(1.0)

        dialog_open = await client.evaluate("""
            (() => {
                const dialog = document.querySelector('#admin-alerts-dialog');
                return dialog && (
                    dialog.state === 'opened' ||
                    dialog.state === 'opening' ||
                    dialog.hasAttribute('open') ||
                    window.getComputedStyle(dialog).display === 'block'
                );
            })()
        """)
        assert dialog_open, "Alerts dialog failed to open upon card click!"
        print("  ✓ Alerts dialog opened.")

        # Capture screenshot of Alerts Dialog
        screenshot_alerts = os.path.join(ARTIFACT_DIR, "admin_alerts_dialog.png")
        await client.screenshot(screenshot_alerts)

        # Close Alerts dialog
        await client.evaluate("document.querySelector('#admin-alerts-close').click()")
        time.sleep(0.5)

        # Step 2d: Test Enrollment link navigation
        print("\n  → Testing Enrollment navigation and active session...")
        await client.evaluate("window.location.assign('/enrollment')")
        # The NiceGUI page hydrates asynchronously after navigation commits, so
        # wait for its rendered content instead of guessing with a fixed sleep.
        enroll_title = await wait_for(
            client,
            "(() => { const h = document.querySelector('#heading-1');"
            " return h && h.textContent.trim() === 'Hello!' ? h.textContent.trim() : null; })()",
        )
        assert enroll_title == "Hello!", f"Expected 'Hello!', got '{enroll_title}'"
        print("  ✓ Successfully navigated to /enrollment while authenticated.")

        screenshot_enroll = os.path.join(ARTIFACT_DIR, "admin_enrollment_view.png")
        await client.screenshot(screenshot_enroll)

        # Step 2e: Return to /admin and test Exit button logout
        print("\n  → Returning to /admin to test Exit button logout...")
        await client.evaluate("window.location.assign('/admin')")
        await client.evaluate("""
            new Promise((resolve) => {
                const check = () => {
                    if (window.location.pathname === '/admin' && document.querySelector('#admin-exit-btn')) {
                        resolve(true);
                    } else {
                        setTimeout(check, 100);
                    }
                };
                check();
            })
        """)
        time.sleep(0.8)

        # Click Exit button
        print("  → Clicking Exit button...")
        await client.evaluate("document.querySelector('#admin-exit-btn').click()")
        await client.evaluate("""
            new Promise((resolve) => {
                const check = () => {
                    if (window.location.pathname === '/admin-display') {
                        resolve(true);
                    } else {
                        setTimeout(check, 100);
                    }
                };
                check();
            })
        """)
        time.sleep(1.0)
        print("  ✓ Successfully logged out and returned to /admin-display.")

        screenshot_after_exit = os.path.join(ARTIFACT_DIR, "after_exit_admin_display.png")
        await client.screenshot(screenshot_after_exit)

        # Step 2f: Verify that trying to access /admin or /enrollment after logout redirects back
        print("  → Verifying that /admin redirects to /admin-display after logout...")
        await client.evaluate("window.location.assign('/admin')")
        time.sleep(1.2)
        current_path = await client.evaluate("window.location.pathname")
        assert current_path == "/admin-display", f"Expected redirect to /admin-display, but ended at '{current_path}'"
        print("  ✓ Unauthenticated attempt to return to /admin correctly redirected to /admin-display.")

        await client.close()


def main():
    tmp = tempfile.mkdtemp(prefix="labauth-admin-panel-")
    server_proc = subprocess.Popen(
        [sys.executable, "src/main.py"],
        env=dict(os.environ, PORT=str(PORT), LABAUTH_DB_PATH=str(Path(tmp) / "labauth.db")),
    )
    time.sleep(2)
    try:
        test_auth_and_session_routes()
        asyncio.run(test_browser_admin_panel())
        print("\n" + "=" * 60)
        print("  ALL ADMIN PANEL TESTS PASSED SUCCESSFULLY!")
        print("=" * 60)
    finally:
        server_proc.terminate()


if __name__ == "__main__":
    main()
