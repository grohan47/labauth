#!/usr/bin/env python3
"""Check Lyne upgrades on ordinary navigation/reload with browser caching enabled.

Uses a fresh browser profile and disposable database. With a valid local bundle,
blocks CDN component/style requests to catch pages bypassing the shared loader.
Run: uv run python tests/test_asset_navigation_browser.py
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

from cdp import free_port, wait_for
from test_display_settings_browser import FreshBrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ui.lyne import has_vendored_lyne


async def run():
    local = has_vendored_lyne()
    with tempfile.TemporaryDirectory(prefix='labauth-asset-navigation-') as tmp:
        port = free_port()
        base = f'http://127.0.0.1:{port}'
        env = {**os.environ, 'PORT': str(port), 'LABAUTH_DB_PATH': str(Path(tmp) / 'test.db'),
               'LABAUTH_ADMIN_PASSWORD': 'asset-navigation-test'}
        with open(Path(tmp) / 'server.log', 'w+') as log:
            proc = subprocess.Popen([sys.executable, 'src/main.py'], cwd=ROOT, env=env,
                                    stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    try:
                        urllib.request.urlopen(base + '/api/presence', timeout=1).close()
                        break
                    except Exception:
                        if proc.poll() is not None:
                            log.seek(0)
                            raise RuntimeError(log.read())
                        await asyncio.sleep(.15)
                else:
                    raise RuntimeError('Server startup timed out')
                with FreshBrowser('about:blank') as browser:
                    client = await browser.page()
                    try:
                        await client.send_command('Page.enable')
                        await client.send_command('Network.enable')
                        # Explicitly keep HTTP caching on; never use ignoreCache.
                        await client.send_command('Network.setCacheDisabled', {'cacheDisabled': False})
                        if local:
                            await client.send_command('Network.setBlockedURLs', {'urls': [
                                '*cdn.jsdelivr.net/npm/@sbb-esta/lyne-elements@*',
                                '*cdn.jsdelivr.net/npm/@sbb-esta/lyne-design-tokens@*',
                            ]})
                        await client.send_command('Page.addScriptToEvaluateOnNewDocument', {'source': '''
                            window.assetErrors = [];
                            addEventListener('error', e => {
                                if (e.message) assetErrors.push(e.message);
                                else if (e.target.matches?.('script,link[rel=stylesheet]'))
                                    assetErrors.push(e.target.src || e.target.href);
                            }, true);
                            addEventListener('unhandledrejection', e => assetErrors.push(String(e.reason)));
                        '''})

                        async def ready(path, selector):
                            assert await wait_for(client, f"location.pathname === {json.dumps(path)} && !!document.querySelector({json.dumps(selector)})", timeout=30), path
                            assert await wait_for(client, '''(() => {
                                const nodes = [...document.querySelectorAll('*')].filter(n => n.localName.startsWith('sbb-'));
                                return nodes.length && nodes.every(n => customElements.get(n.localName) && n.shadowRoot);
                            })()''', timeout=30), f'Unstyled/unregistered Lyne controls on {path}'
                            assert await wait_for(client, "[...document.querySelectorAll('link[rel=stylesheet]')].every(n=>!!n.sheet)"), f'Missing styles on {path}'
                            if path == '/enrollment':
                                assert await wait_for(client, "document.querySelector('.enrolment-page').dataset.ready==='true'"), 'Enrolment did not initialise'
                                assert await client.evaluate("getComputedStyle(document.querySelector('.enrolment-shell')).paddingTop !== '0px'"), 'Enrolment styles missing'
                                assert await client.evaluate("[...document.querySelectorAll('.portrait')].every(n=>n.complete && n.naturalWidth>0)"), 'Portrait graphics missing'
                            if local:
                                assert await client.evaluate("!!document.querySelector('script[src*=\"/static/vendor/sbb-elements.bundle.js?v=\"]')"), f'{path} bypasses the shared local loader'
                            assert await client.evaluate('assetErrors') == [], await client.evaluate('assetErrors')

                        async def reload_page(path, selector):
                            await client.evaluate('window.assetReloadMarker = true')
                            await client.send_command('Page.reload')
                            assert await wait_for(client, '!window.assetReloadMarker'), 'Reload did not commit'
                            await ready(path, selector)

                        await client.send_command('Page.navigate', {'url': base + '/display'})
                        await ready('/display', '.display-shell')
                        code = await client.evaluate("fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:'asset-navigation-test'})}).then(r=>r.status)")
                        assert code == 200
                        await client.send_command('Page.navigate', {'url': base + '/admin'})
                        await ready('/admin', 'sbb-card-link[href="/enrollment"]')
                        for _ in range(3):
                            # Follow the rendered links, just as a user would.
                            await client.evaluate("document.querySelector('sbb-card-link[href=\"/enrollment\"]').click()")
                            await ready('/enrollment', '#identity-form')
                            await reload_page('/enrollment', '#identity-form')
                            await client.evaluate("document.querySelector('#enrolment-close-btn').click()")
                            await ready('/admin', 'sbb-card-link[href="/enrollment"]')
                        await client.evaluate("history.back()")
                        await ready('/enrollment', '#identity-form')
                        await client.evaluate("history.forward()")
                        await ready('/admin', 'sbb-card-link[href="/enrollment"]')
                        for path, selector in [('/admin/display-settings', '#settings-apply'),
                                               ('/search', '#search-user-input'),
                                               ('/admin-display', '#admin-password-dialog')]:
                            await client.send_command('Page.navigate', {'url': base + path})
                            await ready(path, selector)
                            await reload_page(path, selector)
                        await client.screenshot('/tmp/labauth-asset-navigation.png')
                        print(f'PASS: normal link navigation, 3 enrolment reloads, back/forward, other page reloads, upgraded Lyne controls/styles, no JS/style failures; local bundle={local}')
                    finally:
                        await client.close()
            finally:
                proc.terminate()
                proc.wait(timeout=10)


if __name__ == '__main__':
    asyncio.run(run())
