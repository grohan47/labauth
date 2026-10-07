#!/usr/bin/env python3
"""Real Chromium regression checks; saves use a disposable database only.

Run: uv run python tests/test_display_settings_browser.py
Screenshots: /tmp/labauth-settings-qa (override LABAUTH_SCREENSHOT_DIR).
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
ARTIFACTS = Path(os.environ.get('LABAUTH_SCREENSHOT_DIR', '/tmp/labauth-settings-qa'))


class FreshBrowser(Browser):
    """Use a fresh profile so another running browser cannot capture the test."""
    def __enter__(self):
        self.profile = tempfile.TemporaryDirectory(prefix='labauth-settings-browser-')
        self.proc = subprocess.Popen([
            find_browser(), '--headless=new', '--disable-gpu', '--no-first-run',
            f'--user-data-dir={self.profile.name}',
            f'--window-size={self.width},{self.height}',
            f'--remote-debugging-port={self.port}', 'about:blank',
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self._wait_for_target()
        return self

    def __exit__(self, *args):
        super().__exit__(*args)
        self.profile.cleanup()


async def check_page(base, password):
    with FreshBrowser('about:blank') as browser:
        client = await browser.page()
        try:
            await client.send_command('Page.enable')
            await client.send_command('Page.addScriptToEvaluateOnNewDocument', {'source': '''
                window.qaErrors = [];
                window.qaResourceErrors = [];
                addEventListener('error', e => {
                    if (e.message) qaErrors.push(e.message);
                    else if (e.target.src || e.target.href) qaResourceErrors.push(e.target.src || e.target.href);
                }, true);
                addEventListener('unhandledrejection', e => qaErrors.push(String(e.reason)));
            '''})

            async def navigate(path):
                await client.send_command('Page.navigate', {'url': base + path})
                assert await wait_for(client, f"location.href.startsWith({json.dumps(base + path)}) && document.readyState === 'complete'")

            async def ready():
                assert await wait_for(client, "!!document.querySelector('#settings-apply') && ['sbb-checkbox','sbb-radio-button','sbb-radio-button-group'].every(t=>!!customElements.get(t)) && document.querySelector('#settings-apply').disabled"), 'Settings components did not initialize'
                await asyncio.sleep(.2)

            async def click(selector):
                # Real pointer events exercise Lyne's default interaction behavior.
                point = await client.evaluate(f'''(() => {{
                    const n = document.querySelector({json.dumps(selector)});
                    n.scrollIntoView({{block:'center'}});
                    const r = n.getBoundingClientRect();
                    return {{x:r.x+r.width/2, y:r.y+r.height/2}};
                }})()''')
                assert 'x' in point and 'y' in point, (selector, point)
                await client.send_command('Input.dispatchMouseEvent', {'type':'mousePressed', 'button':'left', 'clickCount':1, **point})
                await client.send_command('Input.dispatchMouseEvent', {'type':'mouseReleased', 'button':'left', 'clickCount':1, **point})
                await asyncio.sleep(.1)

            async def save():
                await click('#settings-apply')
                assert await wait_for(client, "document.querySelector('#settings-status').textContent === 'Saved' && document.querySelector('#settings-apply').disabled"), 'Settings did not save'

            await navigate('/display')
            code = await client.evaluate("fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:" + json.dumps(password) + "})}).then(r=>r.status)")
            assert code == 200
            await navigate('/admin/display-settings')
            await ready()
            assert await client.evaluate("document.querySelectorAll('[data-setting]').length") == 10
            assert await client.evaluate("document.querySelector('.outline-greeter').textContent") == 'LabAuth'
            assert await client.evaluate("getComputedStyle(document.querySelector('.outline-greeter')).webkitTextStrokeWidth") == '1px'
            keys = await client.evaluate("[...document.querySelectorAll('[data-setting]')].map(n=>n.dataset.setting)")
            for key in keys:
                await click(f'[data-setting="{key}"]')
                assert await client.evaluate(f"document.querySelector('[data-setting=\"{key}\"]').checked === false"), key
                assert await client.evaluate("!document.querySelector('#settings-apply').disabled")
                assert await client.evaluate(f"[...document.querySelectorAll('[data-part=\"{key}\"]')].every(n=>n.hidden && getComputedStyle(n).display==='none')"), key
            await save()
            stored = await client.evaluate("fetch('/api/settings/display/display').then(r=>r.json()).then(d=>d.settings)")
            assert all(value is False for value in stored.values())
            await click('sbb-radio-button[value="admin-display"]')
            assert await client.evaluate("document.querySelector('[data-outline]').dataset.screen === 'admin-display'")
            assert await client.evaluate("[...document.querySelectorAll('[data-setting]')].every(n=>n.checked)")
            assert await client.evaluate("!document.querySelector('[data-part=show_admin_bar]').hidden")
            await click('[data-setting="show_names"]')
            await save()
            await navigate('/admin/display-settings')
            await ready()
            assert await client.evaluate("[...document.querySelectorAll('[data-setting]')].every(n=>!n.checked)")
            await click('sbb-radio-button[value="admin-display"]')
            assert await client.evaluate("!document.querySelector('[data-setting=show_names]').checked && document.querySelector('[data-setting=show_clock]').checked")
            await click('#settings-reset')
            assert await client.evaluate("[...document.querySelectorAll('[data-setting]')].every(n=>n.checked)")
            await save()
            await click('sbb-radio-button[value="display"]')
            assert await client.evaluate("[...document.querySelectorAll('[data-setting]')].every(n=>!n.checked)")
            await click('#settings-reset')
            await save()
            # Keyboard activation must behave like pointer activation.
            await client.evaluate("document.querySelector('[data-setting=show_clock]').focus()")
            await client.send_command('Input.dispatchKeyEvent', {'type':'keyDown','key':' ','code':'Space','windowsVirtualKeyCode':32})
            await client.send_command('Input.dispatchKeyEvent', {'type':'keyUp','key':' ','code':'Space','windowsVirtualKeyCode':32})
            assert await client.evaluate("!document.querySelector('[data-setting=show_clock]').checked")
            await click('#settings-reset')
            await save()

            layouts = []
            for theme_time, theme in [('12:00','light'),('23:00','dark')]:
                await client.evaluate("fetch('/api/time/mock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({time:" + json.dumps(theme_time) + "})}).then(r=>r.status)")
                await navigate('/admin/display-settings')
                await ready()
                assert await client.evaluate('document.documentElement.dataset.theme') == theme
                for width in [375,768,1440]:
                    await client.send_command('Emulation.setDeviceMetricsOverride', {'width':width,'height':1000,'deviceScaleFactor':1,'mobile':False})
                    await client.evaluate("document.querySelector('.admin-panel--settings').scrollTop=0")
                    await asyncio.sleep(.2)
                    info = await client.evaluate('''(() => {
                        const panel = document.querySelector('.admin-panel--settings');
                        return {width:innerWidth, overflow:panel.scrollWidth-panel.clientWidth,
                            controls:[...document.querySelectorAll('[data-setting]')].every(n=>n.shadowRoot && n.getBoundingClientRect().width>24 && n.getBoundingClientRect().height>=24),
                            labels:[...document.querySelectorAll('[data-setting]')].every(n=>n.textContent.trim()),
                            cards:document.querySelectorAll('.card-outline').length};
                    })()''')
                    assert info['overflow'] <= 1, info
                    assert info['controls'] and info['labels'] and info['cards'] == 12, info
                    layouts.append({'theme':theme, **info})
                    await client.screenshot(str(ARTIFACTS / f'settings-{theme}-{width}.png'))
                    await client.evaluate("document.querySelector('#settings-apply').scrollIntoView({block:'end'})")
                    await client.screenshot(str(ARTIFACTS / f'settings-{theme}-{width}-actions.png'))
            assert await client.evaluate('qaErrors') == [], await client.evaluate('qaErrors')
            assert await client.evaluate('qaResourceErrors') == [], await client.evaluate('qaResourceErrors')
            requests = await client.evaluate("performance.getEntriesByType('resource').filter(r=>r.responseStatus>=400).map(r=>({url:r.name,status:r.responseStatus}))")
            assert requests == [], requests
            # Back navigation returns to the existing Lyne admin page.
            await click('a[href="/admin"], sbb-secondary-button-link[href="/admin"]')
            assert await wait_for(client, "location.pathname === '/admin' && !!document.querySelector('.admin-panel')")
            print('PASS: all 10 controls, previews, screen isolation, Apply, Reset, reload persistence, keyboard, Back, 6 responsive/theme layouts, no JS/resource errors')
            (ARTIFACTS / 'results.json').write_text(json.dumps({'layouts':layouts,'errors':[],'failed_requests':requests}, indent=2))
        finally:
            await client.close()


async def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='labauth-settings-') as tmp:
        port = free_port()
        base = f'http://127.0.0.1:{port}'
        env = {**os.environ, 'PORT':str(port), 'LABAUTH_DB_PATH':str(Path(tmp)/'test.db'), 'LABAUTH_ADMIN_PASSWORD':'settings-qa'}
        with open(Path(tmp)/'server.log', 'w+') as log:
            proc = subprocess.Popen([sys.executable,'src/main.py'],cwd=ROOT,env=env,stdout=log,stderr=log)
            try:
                deadline = time.monotonic()+40
                while time.monotonic()<deadline:
                    try:
                        urllib.request.urlopen(base+'/api/presence',timeout=1).close()
                        break
                    except Exception:
                        if proc.poll() is not None:
                            log.seek(0); raise RuntimeError(log.read())
                        await asyncio.sleep(.15)
                else:
                    raise RuntimeError('Test server startup timed out')
                await check_page(base,'settings-qa')
            finally:
                proc.terminate()
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait()


if __name__ == '__main__':
    asyncio.run(main())
