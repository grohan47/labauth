"""Chromium search/profile QA; fixtures use a disposable database."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request
from unittest.mock import patch
from cdp import free_port,wait_for
from test_display_settings_browser import FreshBrowser
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import database as db
ARTIFACTS=Path(os.environ.get('LABAUTH_SCREENSHOT_DIR','/tmp/labauth-search-qa'))

async def check(base):
    with FreshBrowser('about:blank') as browser:
        client=await browser.page()
        async def click(selector):
            point=await client.evaluate(f'''(() => {{const n=document.querySelector({json.dumps(selector)});n.scrollIntoView({{block:'center'}});const r=n.getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}};}})()''')
            for kind in ('mousePressed','mouseReleased'):
                await client.send_command('Input.dispatchMouseEvent',{'type':kind,'button':'left','clickCount':1,**point})
            await asyncio.sleep(.15)
        async def type_query(value):
            await click('#search-user-input')
            await client.send_command('Input.dispatchKeyEvent',{'type':'keyDown','key':'a','code':'KeyA','modifiers':2,'windowsVirtualKeyCode':65})
            await client.send_command('Input.dispatchKeyEvent',{'type':'keyUp','key':'a','code':'KeyA','modifiers':2,'windowsVirtualKeyCode':65})
            await client.send_command('Input.insertText',{'text':value})
        try:
            await client.send_command('Page.enable')
            await client.send_command('Page.addScriptToEvaluateOnNewDocument',{'source':'''window.qaErrors=[];window.qaResources=[];
              addEventListener('error',e=>{if(e.message)qaErrors.push(e.message);else if(e.target.src||e.target.href)qaResources.push(e.target.src||e.target.href);},true);
              addEventListener('unhandledrejection',e=>qaErrors.push(String(e.reason)));'''})
            await client.send_command('Page.navigate',{'url':base+'/display'})
            assert await wait_for(client,"document.readyState==='complete'")
            assert await client.evaluate("fetch('/api/users/search').then(r=>r.status)")==401
            assert await client.evaluate("fetch('/api/users/1').then(r=>r.status)")==401
            assert await client.evaluate("fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:'search-qa'})}).then(r=>r.status)")==200
            await client.send_command('Page.navigate',{'url':base+'/search'})
            assert await wait_for(client,"document.querySelector('#search-count')?.textContent==='30 / 55 users'"),await client.evaluate('document.body.innerText')
            await client.send_command('Emulation.setDeviceMetricsOverride',{'width':1440,'height':900,'deviceScaleFactor':1,'mobile':False})
            await asyncio.sleep(.2)
            grid=await client.evaluate("({columns:getComputedStyle(document.querySelector('.search-results')).gridTemplateColumns.split(' ').length,rows:new Set([...document.querySelectorAll('.search-user-card')].map(c=>c.getBoundingClientRect().top)).size,height:document.querySelector('.search-user-card').getBoundingClientRect().height,width:document.querySelector('.search-user-card').getBoundingClientRect().width,ids:[...document.querySelectorAll('.search-labauth-id')].map(n=>n.textContent)})")
            assert grid['columns']==6 and grid['rows']==5 and grid['width']>grid['height'],grid
            assert 'LabAuth #1' in grid['ids'] and 'LabAuth #2' in grid['ids'],grid
            await client.screenshot(str(ARTIFACTS/'search-all.png'))
            await client.send_command('Emulation.setDeviceMetricsOverride',{'width':1920,'height':900,'deviceScaleFactor':1,'mobile':False})
            await asyncio.sleep(.2)
            assert await client.evaluate("getComputedStyle(document.querySelector('.search-results')).gridTemplateColumns.split(' ').length")==7
            await client.screenshot(str(ARTIFACTS/'search-all-wide.png'))
            await click('#search-more')
            assert await wait_for(client,"document.querySelector('#search-count').textContent==='55 / 55 users'")
            assert await client.evaluate("document.querySelectorAll('.search-user-card').length")==55
            assert await client.evaluate("typeof window.injected==='undefined' && document.querySelectorAll('#search-results-list img').length===0")
            assert await client.evaluate("[...document.querySelectorAll('.search-user-card')].every(c=>{const r=c.getBoundingClientRect(),i=c.querySelector('.search-identity').getBoundingClientRect();return i.right<=r.right&&i.bottom<=r.bottom;})")
            await type_query('P002')
            assert await wait_for(client,"document.querySelector('#search-count').textContent==='1 / 1 users' && document.querySelector('#search-results-list').getAttribute('aria-busy')!=='true'")
            assert 'Rohan Gupta' in await client.evaluate("document.querySelector('#search-results-list').textContent")
            await click('[data-user-id="2"]')
            assert await wait_for(client,"document.querySelector('#search-profile-content').textContent.includes('Retained ban')")
            assert 'Inactive' in await client.evaluate("document.querySelector('#search-profile-content').textContent")
            await click('#search-profile-close');await asyncio.sleep(.4)
            await type_query('aisha@example.test')
            assert await wait_for(client,"document.querySelector('#search-count').textContent==='1 / 1 users' && document.querySelector('#search-results-list').getAttribute('aria-busy')!=='true'")
            await click('[data-user-id="1"]')
            assert await wait_for(client,"document.querySelector('#search-profile-content').textContent.includes('template:41')")
            text=await client.evaluate("document.querySelector('#search-profile-content').textContent")
            assert all(value in text for value in ('123456','Indoor lab','card:001','aisha@example.test','Registered','Updated','LabAuth ID')),text
            await asyncio.sleep(.4);await client.screenshot(str(ARTIFACTS/'profile-light.png'))
            await click('#search-profile-close');await asyncio.sleep(.4)
            await type_query('no-such-person')
            assert await wait_for(client,"document.querySelector('#search-count').textContent==='0 / 0 users'")
            assert await client.evaluate("document.querySelector('#search-results-list').textContent.trim()")=='No matching users.'
            await type_query('Aisha')
            assert await wait_for(client,"document.querySelector('#search-count').textContent==='1 / 1 users' && document.querySelector('#search-results-list').getAttribute('aria-busy')!=='true'")
            layouts=[]
            for theme in ('light','dark'):
                await client.evaluate(f"document.documentElement.dataset.theme='{theme}'")
                for width in (1440,1920,768,375):
                    await client.send_command('Emulation.setDeviceMetricsOverride',{'width':width,'height':900,'deviceScaleFactor':1,'mobile':False})
                    await asyncio.sleep(.2)
                    info=await client.evaluate("({overflow:document.querySelector('.admin-panel--search').scrollWidth-document.querySelector('.admin-panel--search').clientWidth,photo:document.querySelector('.search-photo').complete,card:document.querySelector('.search-user-card').getBoundingClientRect().width})")
                    assert info['overflow']<=1 and info['photo'] and info['card']>150,info
                    layouts.append({'theme':theme,'width':width,**info})
                    await client.screenshot(str(ARTIFACTS/f'search-{theme}-{width}.png'))
                    await click('[data-user-id="1"]')
                    assert await wait_for(client,"document.querySelector('#search-profile-content').textContent.includes('template:41')")
                    await asyncio.sleep(.3)
                    info=await client.evaluate("({overflow:document.querySelector('#search-profile-content').scrollWidth-document.querySelector('#search-profile-content').clientWidth,close:document.querySelector('#search-profile-close').getBoundingClientRect().bottom})")
                    assert info['overflow']<=1 and info['close']<=900,info
                    await client.screenshot(str(ARTIFACTS/f'profile-{theme}-{width}.png'))
                    await click('#search-profile-close');await asyncio.sleep(.4)
            # Keyboard can activate the actual Lyne card action.
            await click('#search-user-input')
            await client.send_command('Input.dispatchKeyEvent',{'type':'keyDown','key':'Tab','code':'Tab','windowsVirtualKeyCode':9})
            assert await client.evaluate("document.activeElement.tagName")=='SBB-CARD-BUTTON'
            await client.send_command('Input.dispatchKeyEvent',{'type':'keyDown','key':' ','code':'Space','windowsVirtualKeyCode':32})
            await client.send_command('Input.dispatchKeyEvent',{'type':'keyUp','key':' ','code':'Space','windowsVirtualKeyCode':32})
            assert await wait_for(client,"document.querySelector('#search-profile-dialog').isOpen"), await client.evaluate("({active:document.activeElement.outerHTML,errors:qaErrors})")
            await click('#search-profile-close');await asyncio.sleep(.4)
            assert await client.evaluate("fetch('/api/users/999999').then(r=>r.status)")==404
            assert await client.evaluate("fetch('/api/users/1',{method:'DELETE'}).then(r=>r.status)")==405
            assert await client.evaluate('qaErrors')==[],await client.evaluate('qaErrors')
            assert await client.evaluate('qaResources')==[],await client.evaluate('qaResources')
            await click('sbb-secondary-button-link[href="/admin"]')
            assert await wait_for(client,"location.pathname==='/admin'")
            (ARTIFACTS/'results.json').write_text(json.dumps(layouts,indent=2))
            print('PASS: admin protection, full-user pagination, live ID/contact search, inactive/banned account, all profile fields, empty state, Lyne card clicks and keyboard, 8 themes/layouts and dialogs, Back, no JS/resource errors, no DELETE route')
        finally:await client.close()

async def main():
    ARTIFACTS.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='labauth-search-') as tmp:
        port=free_port();base=f'http://127.0.0.1:{port}'
        env={**os.environ,'PORT':str(port),'LABAUTH_DB_PATH':str(Path(tmp)/'test.db'),'LABAUTH_ADMIN_PASSWORD':'search-qa'}
        with patch.dict(os.environ,env):
            db.init_db()
            a=db.create_user('Aisha Khan',plaksha_id='P001',email='aisha@example.test',phone='123456')
            b=db.create_user('Rohan Gupta',plaksha_id='P002',status='inactive')
            db.create_user('Meera <img src=x onerror=window.injected=1>',is_temp=True)
            db.set_user_access_areas(a.id,['Indoor lab'],granted_by='admin')
            db.enroll_credential(a.id,'nfc','card:001')
            db.enroll_credential(a.id,'fingerprint','template:41',template=b'test-only-biometric')
            db.create_ban(b.id,reason='Retained ban',banned_by='admin')
            for i in range(52):db.create_user(f'User {i:02d}',plaksha_id=f'T{i:03d}')
        with open(Path(tmp)/'server.log','w+') as log:
            proc=subprocess.Popen([sys.executable,'src/main.py'],cwd=ROOT,env=env,stdout=log,stderr=log)
            try:
                for _ in range(200):
                    try:urllib.request.urlopen(base+'/api/presence',timeout=1).close();break
                    except Exception:
                        if proc.poll() is not None:log.seek(0);raise RuntimeError(log.read())
                        await asyncio.sleep(.15)
                await check(base)
            finally:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()

if __name__=='__main__':asyncio.run(main())
