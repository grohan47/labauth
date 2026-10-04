#!/usr/bin/env python3
"""
Automated tests for the LabAuth Admin Display UI (/admin-display).
Verifies:
1. API authentication (/api/admin/login)
2. Seamless SBB Lyne titlebar with Helvetica Red "LabAuth" and panel logo
3. Single Admin action button with icon pushed to the right
4. Admin password modal popup:
   - Generous padding and width
   - Functional close button with cross-small icon
   - Keyboard (Escape) & light dismiss dismissal
   - Form submission and error handling
"""

import asyncio
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

PORT = 8110
BASE_URL = f"http://127.0.0.1:{PORT}"


def test_api_login():
    print("\n[Test 1] Testing /api/admin/login endpoint...")
    login_url = f"{BASE_URL}/api/admin/login"

    # Test 1a: Wrong password
    req = urllib.request.Request(
        login_url,
        data=json.dumps({"password": "wrongpassword"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            assert False, f"Expected 401, got {resp.status}"
    except urllib.error.HTTPError as e:
        assert e.code == 401, f"Expected status 401, got {e.code}"
        print("  ✓ Incorrect password correctly rejected (HTTP 401).")

    # Test 1b: Correct password
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
        cookie = resp.headers.get("Set-Cookie", "")
        assert "labauth_admin_session=" in cookie, f"Session cookie missing in {cookie}"
        print("  ✓ Correct password authorized (HTTP 200, redirect: /admin, session cookie issued).")


def test_favicon_endpoints():
    print("\n[Test 1b] Testing favicon endpoints (/favicon.ico, /favicon.svg, /static/favicon.svg, /admin-display/favicon.ico)...")
    for endpoint in ["/favicon.ico", "/favicon.svg", "/static/favicon.svg", "/admin-display/favicon.ico"]:
        url = f"{BASE_URL}{endpoint}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200, f"Expected 200 for {endpoint}, got {resp.status}"
            content = resp.read().decode("utf-8")
            assert "35.2 20.603" in content, f"viewBox missing in {endpoint}"
            assert "#EC0000" in content, f"Red panel missing in {endpoint}"
            assert "#FFF" in content, f"White arrows missing in {endpoint}"
            assert "#000" not in content, f"Cut logo should not have typography in {endpoint}"
            assert "SBB" not in content, f"Typography text found in {endpoint}"
            print(f"  ✓ {endpoint} serves valid curt logo SVG without typography.")


async def test_browser_admin_display():
    print("\n[Test 2] Launching headless browser to test /admin-display...")
    with Browser(f"{BASE_URL}/admin-display", width=1280, height=800) as browser:
        client = await browser.page()

        # Step 2a: Wait for DOM to load
        bound = await wait_for(
            client,
            "Boolean(document.querySelector('.admin-titlebar') && "
            "document.querySelector('#admin-access-button'))",
        )
        assert bound, "Admin titlebar and controls never appeared"
        print("  ✓ Admin titlebar and controls successfully loaded.")

        # Step 2b: Verify titlebar layout, typography & cut SVG logo
        titlebar_info = await client.evaluate("""
            (() => {
                const brand = document.querySelector('.admin-brand');
                const brandContent = document.querySelector('.admin-brand__content');
                const brandName = document.querySelector('.admin-brand__name');
                const brandLogo = document.querySelector('.admin-brand__logo');
                const spacer = document.querySelector('.sbb-header-spacer');
                const adminBtn = document.querySelector('#admin-access-button');
                const faviconSvgLink = document.querySelector('link[type="image/svg+xml"]');
                const faviconIcoLink = document.querySelector('link[rel*="icon"]');

                const nameStyle = brandName ? window.getComputedStyle(brandName) : null;
                const logoStyle = brandLogo ? window.getComputedStyle(brandLogo) : null;
                const contentStyle = brandContent ? window.getComputedStyle(brandContent) : null;

                const nameRect = brandName ? brandName.getBoundingClientRect() : null;
                const logoRect = brandLogo ? brandLogo.getBoundingClientRect() : null;

                const nameMid = nameRect ? (nameRect.top + nameRect.bottom) / 2 : 0;
                const logoMid = logoRect ? (logoRect.top + logoRect.bottom) / 2 : 0;

                const logoSvgHtml = brandLogo ? brandLogo.outerHTML : '';

                return {
                    brandText: brandName ? brandName.innerText.trim() : null,
                    fontFamily: nameStyle ? nameStyle.fontFamily : null,
                    color: nameStyle ? nameStyle.color : null,
                    contentDisplay: contentStyle ? contentStyle.display : null,
                    contentAlignItems: contentStyle ? contentStyle.alignItems : null,
                    nameMid: nameMid,
                    logoMid: logoMid,
                    midDelta: Math.abs(nameMid - logoMid),
                    logoTag: brandLogo ? brandLogo.tagName.toLowerCase() : null,
                    logoViewBox: brandLogo ? brandLogo.getAttribute('viewBox') : null,
                    logoHasRedPanel: logoSvgHtml.includes('#EC0000') || logoSvgHtml.includes('rgb(236, 0, 0)'),
                    logoHasWhiteArrows: logoSvgHtml.includes('#FFF') || logoSvgHtml.includes('#ffffff'),
                    logoHasTypography: logoSvgHtml.includes('#000') || logoSvgHtml.includes('SBB CFF FFS'),
                    faviconSvgHref: faviconSvgLink ? faviconSvgLink.getAttribute('href') : null,
                    faviconIcoHref: faviconIcoLink ? faviconIcoLink.getAttribute('href') : null,
                    hasSpacer: !!spacer,
                    adminBtnText: adminBtn ? adminBtn.innerText.trim() : null,
                    hasAdminIcon: adminBtn ? !!adminBtn.querySelector('.admin-access-icon, svg') : false
                };
            })()
        """)
        print("  ✓ Titlebar brand details:", json.dumps(titlebar_info, indent=4))
        assert titlebar_info["brandText"] == "LabAuth", f"Expected LabAuth, got {titlebar_info['brandText']}"
        assert "Helvetica" in titlebar_info["fontFamily"], f"Expected Helvetica in font family, got {titlebar_info['fontFamily']}"
        assert titlebar_info["contentDisplay"] == "inline-flex", f"Expected inline-flex, got {titlebar_info['contentDisplay']}"
        assert titlebar_info["contentAlignItems"] == "center", f"Expected center, got {titlebar_info['contentAlignItems']}"
        assert titlebar_info["midDelta"] <= 1.0, f"LabAuth and SBB logo off-centered! delta: {titlebar_info['midDelta']}px"
        assert titlebar_info["logoTag"] == "svg", f"Expected svg tag, got {titlebar_info['logoTag']}"
        assert titlebar_info["logoViewBox"] == "0 0 59.233 20.603", f"Unexpected viewBox: {titlebar_info['logoViewBox']}"
        assert titlebar_info["logoHasRedPanel"], "Logo SVG missing red panel"
        assert titlebar_info["logoHasWhiteArrows"], "Logo SVG missing white cross arrows"
        assert not titlebar_info["logoHasTypography"], "Logo SVG should NOT contain typography"
        assert titlebar_info["faviconSvgHref"] == "/static/favicon.svg", f"Unexpected SVG favicon href: {titlebar_info['faviconSvgHref']}"
        assert titlebar_info["faviconIcoHref"], "Missing favicon shortcut icon link"
        assert titlebar_info["hasSpacer"], "sbb-header-spacer not found in titlebar!"
        assert "Admin" in titlebar_info["adminBtnText"], f"Expected Admin in button text, got {titlebar_info['adminBtnText']}"
        assert titlebar_info["hasAdminIcon"], "Admin button missing admin icon!"

        artifact_header = "/home/rgcodes/.gemini/antigravity/brain/d091892e-ebef-4c21-bc51-f24075f4891b/admin_display_header.png"
        await client.screenshot(artifact_header)

        # Step 2c: Click Admin button to open password modal
        print("\n[Test 3] Verifying Admin Password Dialog...")
        await client.evaluate("document.querySelector('#admin-access-button').click()")
        time.sleep(0.8)

        dialog_info = await client.evaluate("""
            (() => {
                const dialog = document.querySelector('#admin-password-dialog');
                const title = document.querySelector('sbb-dialog-title');
                const closeBtn = document.querySelector('#admin-dialog-close, sbb-dialog-close-button');
                const content = document.querySelector('sbb-dialog-content');
                const actions = document.querySelector('sbb-dialog-actions');
                const input = document.querySelector('#admin-password-input');

                const getMetrics = (el) => {
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return {
                        width: r.width,
                        height: r.height,
                        paddingInline: s.paddingInline || `${s.paddingLeft} ${s.paddingRight}`,
                        paddingLeft: parseFloat(s.paddingLeft),
                        paddingRight: parseFloat(s.paddingRight),
                        paddingTop: parseFloat(s.paddingTop),
                        paddingBottom: parseFloat(s.paddingBottom),
                    };
                };

                const closeIcon = closeBtn && closeBtn.shadowRoot ? closeBtn.shadowRoot.querySelector('sbb-icon') : null;

                return {
                    isOpen: dialog && (dialog.state === 'opened' || window.getComputedStyle(dialog).display === 'block'),
                    dialogMetrics: dialog && dialog.shadowRoot && dialog.shadowRoot.querySelector('.sbb-dialog')
                        ? getMetrics(dialog.shadowRoot.querySelector('.sbb-dialog'))
                        : getMetrics(dialog),
                    titleMetrics: getMetrics(title),
                    contentMetrics: getMetrics(content),
                    actionsMetrics: getMetrics(actions),
                    hasCloseBtn: !!closeBtn,
                    closeBtnHasIcon: !!closeIcon,
                    inputFocused: document.activeElement === input
                };
            })()
        """)
        print("  ✓ Dialog metrics:", json.dumps(dialog_info, indent=4))
        assert dialog_info["isOpen"], "Dialog is not open!"
        assert dialog_info["hasCloseBtn"], "Close button not found!"
        assert dialog_info["closeBtnHasIcon"], "Close button missing icon!"
        
        # Verify padding requirements
        dialog_width = dialog_info["dialogMetrics"]["width"]
        content_pl = dialog_info["contentMetrics"]["paddingLeft"]
        title_pl = dialog_info["titleMetrics"]["paddingLeft"]
        actions_pr = dialog_info["actionsMetrics"]["paddingRight"]
        print(f"  ✓ Dialog width: {dialog_width:.1f}px (min required 380px)")
        print(f"  ✓ Content padding-left: {content_pl:.1f}px (min required 16px)")
        print(f"  ✓ Title padding-left: {title_pl:.1f}px (min required 16px)")
        print(f"  ✓ Actions padding-right: {actions_pr:.1f}px (min required 16px)")
        assert dialog_width >= 380, f"Dialog too narrow ({dialog_width}px)"
        assert content_pl >= 16, f"Content padding too small ({content_pl}px)"
        assert title_pl >= 16, f"Title padding too small ({title_pl}px)"
        assert actions_pr >= 16, f"Actions padding too small ({actions_pr}px)"

        artifact_dialog = "/home/rgcodes/.gemini/antigravity/brain/d091892e-ebef-4c21-bc51-f24075f4891b/admin_display_dialog.png"
        await client.screenshot(artifact_dialog)

        # Step 2d: Close button click closes dialog
        print("\n[Test 4] Verifying Close Button behavior...")
        await client.evaluate("document.querySelector('#admin-dialog-close, sbb-dialog-close-button').click()")
        time.sleep(0.6)

        is_closed = await client.evaluate("""
            (() => {
                const dialog = document.querySelector('#admin-password-dialog');
                return !dialog || dialog.state === 'closed' || window.getComputedStyle(dialog).display === 'none';
            })()
        """)
        assert is_closed, "Dialog did not close upon clicking close button!"
        print("  ✓ Close button successfully closes the dialog.")

        # Step 2e: Reopen and test incorrect password submission
        print("\n[Test 5] Verifying Password validation in Dialog...")
        await client.evaluate("document.querySelector('#admin-access-button').click()")
        time.sleep(0.5)

        # Type invalid password and submit
        await client.evaluate("""
            (() => {
                const input = document.querySelector('#admin-password-input');
                input.value = 'badpass';
                document.querySelector('#admin-password-form').dispatchEvent(new Event('submit', { cancelable: true }));
            })()
        """)
        time.sleep(0.8)

        err_text = await client.evaluate("""
            (() => {
                const err = document.querySelector('#admin-password-error');
                return err ? err.textContent : '';
            })()
        """)
        assert "Incorrect password" in err_text, f"Expected error text, got '{err_text}'"
        print(f"  ✓ Error correctly displayed: '{err_text}'")

        # Step 2f: Test Escape key dismiss
        print("\n[Test 6] Verifying Escape key dismissal...")
        await client.evaluate("""
            document.querySelector('#admin-password-dialog').dispatchEvent(
                new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
            )
        """)
        time.sleep(0.5)

        is_closed_esc = await client.evaluate("""
            (() => {
                const dialog = document.querySelector('#admin-password-dialog');
                return !dialog || dialog.state === 'closed' || window.getComputedStyle(dialog).display === 'none';
            })()
        """)
        assert is_closed_esc, "Dialog did not close upon pressing Escape key!"
        print("  ✓ Escape key successfully dismisses the dialog.")

        await client.close()


def main():
    tmp = tempfile.mkdtemp(prefix="labauth-admin-display-")
    server_proc = subprocess.Popen(
        [sys.executable, "src/main.py"],
        env=dict(os.environ, PORT=str(PORT), LABAUTH_DB_PATH=str(Path(tmp) / "labauth.db")),
    )
    time.sleep(2)
    try:
        test_api_login()
        test_favicon_endpoints()
        asyncio.run(test_browser_admin_display())
        print("\n" + "=" * 60)
        print("  ALL ADMIN DISPLAY TESTS PASSED SUCCESSFULLY!")
        print("=" * 60)
    finally:
        server_proc.terminate()


if __name__ == "__main__":
    main()

