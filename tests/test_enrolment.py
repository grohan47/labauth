#!/usr/bin/env python3
"""Exercise real enrolment UI and persistence in an isolated SQLite database.

Run: uv run python tests/test_enrolment.py
Screenshots: LABAUTH_SCREENSHOT_DIR (default /tmp/labauth-enrolment-qa).
Readers deliberately remain unavailable; no simulated credentials are created.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp import Browser, free_port, wait_for
import database as db
from PIL import Image

ARTIFACTS = Path(os.environ.get('LABAUTH_SCREENSHOT_DIR', '/tmp/labauth-enrolment-qa'))


async def run() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='labauth-enrolment-') as tmp:
        os.environ['LABAUTH_DB_PATH'] = str(Path(tmp) / 'test.db')
        db.init_db()
        # Use actual canonical configuration in screenshots; never add example areas.
        custom = db.get_access_area_by_code('tool_area')
        assert custom
        port = free_port()
        base = f'http://127.0.0.1:{port}'
        env = {**os.environ, 'PORT': str(port), 'LABAUTH_ADMIN_PASSWORD': 'enrolment-test'}
        with open(Path(tmp) / 'server.log', 'w+') as log:
            proc = subprocess.Popen([sys.executable, 'src/main.py'], cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    try:
                        urllib.request.urlopen(base + '/api/presence', timeout=1).close()
                        break
                    except Exception:
                        if proc.poll() is not None:
                            log.seek(0); raise RuntimeError(log.read())
                        await asyncio.sleep(.15)
                else:
                    raise RuntimeError('Server startup timed out')
                with Browser(base + '/enrollment') as browser:
                    client = await browser.page()
                    try:
                        async def click(control, target=None):
                            await client.evaluate(f"document.getElementById('{control}').click()")
                            if target:
                                assert await wait_for(client, f"!document.getElementById('step-{target}').hidden"), control
                                assert await client.evaluate("document.querySelector('#enrolment-progress').getAttribute('aria-valuenow')") == str(100 if target == 'success' else target * 25)
                            # Let native Lyne inert/visibility state settle before the next action.
                            await asyncio.sleep(.15)

                        async def theme(time_value, expected):
                            await client.evaluate("fetch('/api/time/mock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({time:" + json.dumps(time_value) + "})}).then(r=>r.json())")
                            await client.evaluate("window.dispatchEvent(new Event('focus'))")
                            assert await wait_for(client, f"document.documentElement.dataset.theme === '{expected}' && document.documentElement.classList.contains('sbb-{expected}')", timeout=20)
                            await asyncio.sleep(.3)

                        async def full_screenshot(name):
                            await client.evaluate("window.scrollTo(0,0)")
                            height = await client.evaluate("document.documentElement.scrollHeight")
                            width = await client.evaluate("window.innerWidth")
                            original_height = await client.evaluate("window.innerHeight")
                            # Expand the viewport so fixed bottom controls appear at the bottom
                            # of a full-page artifact, instead of obscuring the middle of the card.
                            metrics = {'width':width,'height':height,'deviceScaleFactor':1,'mobile':width<768}
                            await client.send_command('Emulation.setDeviceMetricsOverride', metrics)
                            await asyncio.sleep(.15)
                            result = await client.send_command('Page.captureScreenshot', {'format':'png'})
                            (ARTIFACTS / name).write_bytes(base64.b64decode(result['data']))
                            await client.send_command('Emulation.setDeviceMetricsOverride', {**metrics,'height':original_height})

                        assert await wait_for(client, "location.pathname === '/admin-display'"), 'Route must require admin'
                        no_auth = await client.evaluate("fetch('/api/enrolment/complete',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(r=>r.status)")
                        assert no_auth == 401
                        await client.evaluate("fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:'enrolment-test'})}).then(r=>r.json())")
                        await client.send_command('Page.navigate', {'url': base + '/enrollment'})
                        await client.send_command('Emulation.setDeviceMetricsOverride', {'width':1440,'height':900,'deviceScaleFactor':1,'mobile':False})
                        assert await wait_for(client, "!!document.querySelector('#btn-step1-next') && !!customElements.get('sbb-menu') && !!customElements.get('sbb-checkbox')", timeout=45), 'Lyne components not loaded'
                        assert await wait_for(client, "document.querySelector('.enrolment-page')?.dataset.ready === 'true'")
                        await asyncio.sleep(1)
                        initial = await client.evaluate("({blank:!document.querySelector('#input-fullname').value, next:document.querySelector('#btn-step1-next').hidden, areas:[...document.querySelectorAll('sbb-checkbox[name=access]')].map(c=>({id:Number(c.value),checked:c.checked})),text:document.querySelector('main').innerText})")
                        assert initial['blank'] and initial['next']
                        assert await client.evaluate("document.querySelector('.build-card').querySelectorAll('input').length === 4"), 'All identity inputs belong inside the card'
                        assert all(not a['checked'] for a in initial['areas'])
                        assert {a['id'] for a in initial['areas']} == {a.id for a in db.list_access_areas()}
                        assert await client.evaluate("!document.querySelector('header') && !document.querySelector('.enrolment-progress li')")
                        assert await client.evaluate("Math.abs(document.querySelector('#enrolment-progress').getBoundingClientRect().width - document.documentElement.clientWidth) < 1")
                        assert await client.evaluate("[...document.querySelectorAll('.enrolment-actions > *')].every(b=>b.tagName === 'SBB-BUTTON' || b.tagName === 'SBB-BUTTON-LINK')")
                        assert 'Swiss-style' not in initial['text'] and 'Welcome to' not in initial['text']
                        # Themes follow the server clock at both exact boundaries.
                        await theme('05:59', 'dark')
                        assert await client.evaluate("getComputedStyle(document.documentElement).colorScheme") == 'dark'
                        await full_screenshot('01-details.png')
                        await theme('06:00', 'light')
                        await full_screenshot('01-details-light.png')
                        layout = await client.evaluate("(() => {const p=document.querySelector('#avatar-click-zone').getBoundingClientRect(),n=document.querySelector('#input-fullname').getBoundingClientRect(),c=document.querySelector('.build-card').getBoundingClientRect();return {photoAbove:p.bottom<n.top,vertical:c.height>c.width,width:c.width};})()")
                        assert layout['photoAbove'] and layout['vertical'] and layout['width'] <= 480, layout
                        await client.evaluate("document.querySelector('#avatar-click-zone').click()")
                        assert await wait_for(client, "document.querySelector('#photo-menu').isOpen")
                        await client.screenshot(str(ARTIFACTS / '02-photo-menu.png'))
                        await client.send_command('Browser.setPermission', {'permission': {'name': 'videoCapture'}, 'setting': 'denied', 'origin': base})
                        await client.evaluate("document.querySelector('#btn-choose-camera').click()")
                        assert await wait_for(client, "!document.querySelector('#camera-error').hidden")
                        assert await client.evaluate("document.querySelector('#btn-camera-capture').disabled")
                        assert await wait_for(client, "document.querySelector('#camera-error sbb-notification')?.getBoundingClientRect().height > 0")
                        await client.screenshot(str(ARTIFACTS / '03-camera-unavailable.png'))
                        await client.evaluate("document.querySelector('#camera-dialog').close()")
                        # Upload a real, generated image fixture via the browser file input.
                        picture = Path(tmp) / 'portrait.png'
                        Image.new('RGB', (700, 500), '#c7b2a1').save(picture)
                        dom = await client.send_command('DOM.getDocument')
                        node = await client.send_command('DOM.querySelector', {'nodeId':dom['root']['nodeId'],'selector':'#photo-file-input'})
                        await client.send_command('DOM.setFileInputFiles', {'nodeId':node['nodeId'],'files':[str(picture)]})
                        assert await wait_for(client, "document.querySelector('#mock-card-avatar').src.startsWith('data:image/png')")
                        # Desktop details, validation and back/edit draft preservation.
                        await client.evaluate(f"""(() => {{
                            const fields = {{'input-fullname':'Maya Patel','input-plaksha-id':'PLK-2026-014','input-phone':'+91 98765 43210','input-email':'maya@plaksha.edu.in'}};
                            for (const [id,value] of Object.entries(fields)) {{const i=document.getElementById(id);i.value=value;i.dispatchEvent(new Event('input',{{bubbles:true}}));}}
                            document.querySelector('sbb-checkbox[value="{custom.id}"]').checked=true;
                        }})()""")
                        await full_screenshot('01-details-filled.png')
                        # Typography: Bold Swiss Helvetica across identity elements
                        assert await client.evaluate("getComputedStyle(document.querySelector('#heading-1')).fontWeight") in ('700', '800')
                        assert await client.evaluate("getComputedStyle(document.querySelector('#input-fullname')).fontWeight") in ('700', '800')
                        assert await client.evaluate("getComputedStyle(document.querySelector('label[for=input-fullname]')).fontWeight") in ('700', '800')
                        assert 'helvetica' in (await client.evaluate("getComputedStyle(document.querySelector('#heading-1')).fontFamily")).lower()
                        await client.evaluate("document.querySelector('#btn-step1-next').click()")
                        assert await wait_for(client, "!document.querySelector('#step-2').hidden")
                        assert await client.evaluate("!document.querySelector('#btn-fp-skip').hidden && !document.querySelector('#btn-fp-skip').disabled"), 'Fingerprint Skip is always available'
                        assert await client.evaluate("document.querySelector('#fp-status-title').textContent") == 'Reader ready'
                        assert await client.evaluate("!document.querySelector('#fp-animation').hidden && document.querySelector('#fp-checkmark').hidden")

                        # Test fingerprint status states & large checkmark transition
                        await client.evaluate("window.setFingerprintStatus('complete')")
                        assert await client.evaluate("document.querySelector('#fp-animation').hidden && !document.querySelector('#fp-checkmark').hidden")
                        assert await client.evaluate("document.querySelector('#fp-status-title').textContent") == 'Fingerprint Enrolled'
                        assert await client.evaluate("document.querySelector('#btn-fp-skip').textContent.trim()") == 'Next'
                        await asyncio.sleep(.35)
                        await client.screenshot(str(ARTIFACTS / '04-fingerprint-enrolled.png'))

                        # Click stage toggles back to waiting
                        await client.evaluate("document.querySelector('#fp-stage').click()")
                        assert await client.evaluate("!document.querySelector('#fp-animation').hidden && document.querySelector('#fp-checkmark').hidden")
                        assert await client.evaluate("document.querySelector('#fp-status-title').textContent") == 'Reader ready'

                        # Unavailable state
                        await client.evaluate("window.setFingerprintStatus('unavailable')")
                        assert await client.evaluate("document.querySelector('#fp-status-title').textContent") == 'Reader unavailable'
                        await client.screenshot(str(ARTIFACTS / '04-fingerprint.png'))

                        # Reset to waiting for standard skip path
                        await client.evaluate("window.setFingerprintStatus('waiting')")
                        await client.evaluate("document.querySelector('#btn-fp-skip').click()")
                        assert await client.evaluate("document.querySelector('#enrolment-progress').getAttribute('aria-valuenow')") == '75'
                        assert await wait_for(client, "!document.querySelector('#step-3').hidden")
                        assert await wait_for(client, "document.querySelector('#nfc-tap-animation').dataset.loaded === 'true'", timeout=30), 'Card tap animation not loaded'
                        assert await client.evaluate("!document.querySelector('#btn-nfc-skip').hidden && !document.querySelector('#btn-nfc-skip').disabled"), 'NFC Skip is always available'
                        assert await client.evaluate("getComputedStyle(document.querySelector('#btn-step3-back').shadowRoot.querySelector('.sbb-action-base'),'::before').boxShadow === 'none'"), 'Navigation has no glow'

                        # Transit NFC Tap GIFs exist and switch with theme
                        dark_gif_ok = await client.evaluate("fetch('/static/animations/nfc-tap-dark.gif').then(r=>r.ok)")
                        light_gif_ok = await client.evaluate("fetch('/static/animations/nfc-tap-light.gif').then(r=>r.ok)")
                        assert dark_gif_ok and light_gif_ok, 'Transit NFC GIFs must be accessible'

                        await theme('12:00', 'light')
                        assert await client.evaluate("getComputedStyle(document.querySelector('.nfc-tap-gif--light')).display") == 'block'
                        assert await client.evaluate("getComputedStyle(document.querySelector('.nfc-tap-gif--dark')).display") == 'none'
                        await asyncio.sleep(.3)
                        await client.screenshot(str(ARTIFACTS / '05-nfc.png'))

                        await theme('18:00', 'dark')
                        assert await client.evaluate("getComputedStyle(document.querySelector('.nfc-tap-gif--dark')).display") == 'block'
                        assert await client.evaluate("getComputedStyle(document.querySelector('.nfc-tap-gif--light')).display") == 'none'
                        assert await client.evaluate("getComputedStyle(document.querySelector('#btn-step3-back').shadowRoot.querySelector('.sbb-action-base'),'::before').boxShadow === 'none'"), 'Dark navigation has no glow'
                        assert await client.evaluate("document.querySelector('#input-email').value") == 'maya@plaksha.edu.in'
                        await client.screenshot(str(ARTIFACTS / '05-nfc-dark.png'))

                        # Test NFC status states & large checkmark transition
                        await client.evaluate("window.setNfcStatus('complete', 'C8:CB:70:69:F0')")
                        assert await client.evaluate("document.querySelector('#nfc-tap-animation').hidden && !document.querySelector('#nfc-checkmark').hidden")
                        assert await client.evaluate("document.querySelector('#nfc-status-title').textContent") == 'Card Registered'
                        assert 'C8:CB:70:69:F0' in await client.evaluate("document.querySelector('#nfc-status-desc').textContent")
                        assert await client.evaluate("document.querySelector('#btn-nfc-skip').textContent.trim()") == 'Next'
                        await asyncio.sleep(.35)
                        await client.screenshot(str(ARTIFACTS / '05-nfc-registered.png'))

                        # Click stage toggles back to waiting
                        await client.evaluate("document.querySelector('#nfc-stage').click()")
                        assert await client.evaluate("!document.querySelector('#nfc-tap-animation').hidden && document.querySelector('#nfc-checkmark').hidden")

                        # Unavailable state
                        await client.evaluate("window.setNfcStatus('unavailable')")
                        assert await client.evaluate("document.querySelector('#nfc-status-title').textContent") == 'Reader unavailable'

                        # Reset to waiting and return to light mode for standard skip path
                        await client.evaluate("window.setNfcStatus('waiting')")
                        await theme('12:00', 'light')
                        await client.evaluate("document.querySelector('#btn-nfc-skip').click()")
                        assert await wait_for(client, "!document.querySelector('#step-4').hidden")
                        assert await client.evaluate("document.querySelector('#final-card-name').textContent") == 'Maya Patel'
                        assert await client.evaluate("document.querySelector('#final-card-chips').textContent") == custom.label
                        await full_screenshot('06-review.png')
                        await client.evaluate("document.querySelector('#btn-edit-details').click()")
                        assert await client.evaluate("document.querySelector('#enrolment-progress').getAttribute('aria-valuenow')") == '25'
                        assert await client.evaluate("document.querySelector('#input-email').value") == 'maya@plaksha.edu.in'
                        await client.evaluate("document.querySelector('#enrolment-close-btn').click()")
                        assert await wait_for(client, "document.querySelector('#discard-dialog').isOpen")
                        await client.evaluate("document.querySelector('#discard-dialog').close()")
                        await wait_for(client, "!document.querySelector('#discard-dialog').isOpen")
                        await asyncio.sleep(.4)
                        await click('btn-step1-next', 2)
                        await click('btn-fp-skip', 3)
                        await click('btn-nfc-skip', 4)
                        # A duplicate must show an error and leave no partial user/grants.
                        db.create_user('Existing person', plaksha_id='PLK-2026-014')
                        await client.evaluate("document.querySelector('#btn-finish-enrolment').click()")
                        assert await wait_for(client, "document.querySelector('#save-error sbb-notification')?.getBoundingClientRect().height > 0")
                        await client.screenshot(str(ARTIFACTS / '10-duplicate-id.png'))
                        assert await wait_for(client, "!document.querySelector('#save-error').hidden"), await client.evaluate("({step:[...document.querySelectorAll('.enrolment-step')].filter(s=>!s.hidden).map(s=>s.id),button:document.querySelector('#btn-finish-enrolment').disabled,error:document.querySelector('#save-error').textContent})")
                        assert db.count_users() == 1
                        assert not db.get_active_user_by_name('Maya Patel')
                        assert await client.evaluate("!document.querySelector('#step-4').hidden")
                        # Unknown areas and invented credential claims must also be rejected.
                        for payload, expected in [({'name':'Bad grant','access_area_ids':[999999]},409),({'name':'Fake NFC','nfc_uid':'04:AA:BB'},422),({'name':'Fake fingerprint','fingerprint_enrolled':True},422),({'name':' '},422)]:
                            result = await client.evaluate("fetch('/api/enrolment/complete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(" + json.dumps(payload) + ")}).then(r=>r.status)")
                            assert result == expected, (payload, result)
                        assert db.count_users() == 1
                        await click('btn-edit-details', 1)
                        await client.evaluate("document.querySelector('#input-plaksha-id').value='PLK-2026-015'")
                        await click('btn-step1-next', 2)
                        await click('btn-fp-skip', 3)
                        await click('btn-nfc-skip', 4)
                        await click('btn-finish-enrolment')
                        assert await wait_for(client, "!document.querySelector('#step-success').hidden")
                        user = db.get_active_user_by_name('Maya Patel')
                        assert user and user.email == 'maya@plaksha.edu.in' and user.phone == '+91 98765 43210'
                        assert db.get_user_access_area_labels(user.id) == [custom.label]
                        assert db.list_credentials(user_id=user.id) == []
                        assert not db.is_user_inside(user.id)
                        assert any(a.action == 'enrol_user' and a.entity_id == str(user.id) for a in db.list_audit_log())
                        path = ROOT / 'src' / user.photo.removeprefix('/')
                        assert path.exists()
                        with Image.open(path) as image:
                            assert image.size == (480,480)
                        path.unlink()
                        assert await client.evaluate("document.querySelector('#saved-card-host').innerText.includes('Maya Patel')")
                        await full_screenshot('07-saved.png')
                        await click('btn-enrol-another', 1)
                        await client.evaluate("document.querySelector('#input-fullname').value='Name Only';document.querySelector('#input-fullname').dispatchEvent(new Event('input'))")
                        await click('btn-step1-next', 2)
                        await click('btn-fp-skip', 3)
                        await click('btn-nfc-skip', 4)
                        await click('btn-finish-enrolment')
                        assert await wait_for(client, "!document.querySelector('#step-success').hidden")
                        name_only = db.get_active_user_by_name('Name Only')
                        assert name_only and not db.get_user_access_area_labels(name_only.id) and not db.list_credentials(user_id=name_only.id)
                        assert name_only.photo == db.DEFAULT_PHOTO
                        await client.evaluate("document.querySelector('#btn-enrol-another').click()")
                        await client.send_command('Emulation.setDeviceMetricsOverride', {'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
                        await full_screenshot('08-mobile-details.png')
                        assert await client.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), 'Mobile overflow'
                        assert await client.evaluate("Math.abs(document.querySelector('#step-1 .enrolment-actions').getBoundingClientRect().bottom - innerHeight) < 1"), 'Bottom navigation must stay visible'
                        await client.evaluate("document.querySelector('#input-fullname').value='A person with a longer full name';document.querySelector('#input-fullname').dispatchEvent(new Event('input'))")
                        await click('btn-step1-next', 2)
                        await click('btn-fp-skip', 3)
                        await click('btn-nfc-skip', 4)
                        await client.screenshot(str(ARTIFACTS / '09-mobile-review.png'))
                        assert await client.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), 'Mobile review overflow'
                        print('PASS: vertical card, server-clock themes, transit NFC GIFs, bold Helvetica, reader checkmarks, authentication, Lyne rendering, database areas, photo upload, camera unavailable, draft editing, discard, skips, transactional rejection, record persistence, name-only save, mobile layouts')
                        print(f'Screenshots: {ARTIFACTS}')
                    finally:
                        await client.close()
            finally:
                proc.terminate()
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait()


if __name__ == '__main__':
    asyncio.run(run())
