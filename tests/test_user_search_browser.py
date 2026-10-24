"""People management Chromium QA with a disposable server and SQLite database."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request
from unittest.mock import patch
from cdp import free_port, wait_for
from test_display_settings_browser import FreshBrowser
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import database as db
ARTIFACTS=Path(os.environ.get('LABAUTH_SCREENSHOT_DIR','/tmp/labauth-people-qa'))


async def check(base):
    with FreshBrowser('about:blank') as browser:
        client=await browser.page()
        async def click(selector):
            assert await wait_for(client, f"(() => {{ const n=document.querySelector({json.dumps(selector)}); return !!n && !n.closest('[inert]') && (!n.closest('sbb-dialog') || n.closest('sbb-dialog').state==='opened') && [...document.querySelectorAll('sbb-dialog')].every(d=>!['opening','closing'].includes(d.state)); }})()"), selector
            point=await client.evaluate(f'''(() => {{const n=document.querySelector({json.dumps(selector)});n.scrollIntoView({{block:'center',behavior:'instant'}});const r=n.getBoundingClientRect();return {{x:r.x+(n.tagName==='SBB-CHECKBOX'?12:r.width/2),y:r.y+r.height/2}};}})()''')
            for kind in ('mousePressed','mouseReleased'):
                await client.send_command('Input.dispatchMouseEvent',{'type':kind,'button':'left','clickCount':1,**point})
            assert await wait_for(client,"[...document.querySelectorAll('sbb-dialog')].every(d=>!['opening','closing'].includes(d.state))")
            closed = {'#search-edit-cancel':'#search-edit-dialog', '#search-profile-close':'#search-profile-dialog', '#search-confirm-cancel':'#search-confirm-dialog'}.get(selector)
            if closed:
                assert await wait_for(client,f"document.querySelector('{closed}').state==='closed'")
        async def fill(selector,value):
            await click(selector)
            await client.send_command('Input.dispatchKeyEvent',{'type':'keyDown','key':'a','code':'KeyA','modifiers':2,'windowsVirtualKeyCode':65})
            await client.send_command('Input.dispatchKeyEvent',{'type':'keyUp','key':'a','code':'KeyA','modifiers':2,'windowsVirtualKeyCode':65})
            await client.send_command('Input.insertText',{'text':value})
        async def api(path,body,method='PATCH',headers=None):
            return await client.evaluate(f"fetch({json.dumps(path)},{{method:{json.dumps(method)},headers:{json.dumps({'Content-Type':'application/json',**(headers or {})})},body:JSON.stringify({json.dumps(body)})}}).then(async r=>({{status:r.status,data:await r.json()}}))")
        async def ready_count(text):
            assert await wait_for(client, f"document.querySelector('#search-count')?.textContent==={json.dumps(text)} && document.querySelector('#search-results-list').getAttribute('aria-busy')!=='true'"), await client.evaluate('document.body.innerText')
        try:
            await client.send_command('Page.enable')
            await client.send_command('Page.addScriptToEvaluateOnNewDocument',{'source':'''window.qaErrors=[];window.qaResources=[];
              addEventListener('error',e=>{if(e.message)qaErrors.push(e.message);else if(e.target.src||e.target.href)qaResources.push(e.target.src||e.target.href);},true);
              addEventListener('unhandledrejection',e=>qaErrors.push(String(e.reason)));'''})
            await client.send_command('Page.navigate',{'url':base+'/display'})
            assert await wait_for(client,"document.readyState==='complete'")
            for path,body,method in [('/api/users/1',{'name':'Intruder'},'PATCH'),('/api/users/delete',{'user_ids':[1]},'POST'),('/api/users/1',None,'DELETE')]:
                assert (await api(path,body,method))['status']==401
            assert (await api('/api/admin/login',{'password':'people-qa'},'POST'))['status']==200
            await client.send_command('Page.navigate',{'url':base+'/people'})
            await ready_count('100 / 105 users')
            assert await client.evaluate("document.querySelectorAll('.search-user-row').length===100 && document.querySelectorAll('#search-results-list sbb-card').length===0")
            await client.screenshot(str(ARTIFACTS/'people-list.png'))
            await click('[data-select-user="1"]')
            assert await wait_for(client,"document.querySelector('#search-selected').textContent==='1 selected'")
            assert not await client.evaluate("document.querySelector('#search-profile-dialog').isOpen")
            await click('#search-more'); await ready_count('105 / 105 users')
            assert await client.evaluate("document.querySelector('[data-select-user=\"1\"]').checked")
            await click('#search-select-all')
            assert await wait_for(client,"document.querySelector('#search-selected').textContent==='105 selected'")
            await click('#search-select-all')
            await click('[data-user-id="1"]')
            assert await wait_for(client,"document.querySelector('#search-profile-content').textContent.includes('template:41')")
            await click('[data-edit-field="email"]')
            assert await wait_for(client,"document.querySelector('#search-edit-dialog').isOpen")
            await fill('#search-edit-value','updated@example.test'); await click('#search-edit-save')
            assert await wait_for(client,"document.querySelector('#search-edit-dialog').state==='closed' && document.querySelector('#search-profile-content').textContent.includes('updated@example.test')"), await client.evaluate("document.querySelector('#search-edit-error').textContent")
            await click('[data-edit-field="plaksha_id"]'); assert await wait_for(client,"document.querySelector('#search-edit-dialog').isOpen && document.querySelector('#search-edit-title').textContent==='Edit Plaksha ID'"); await fill('#search-edit-value','p002'); await click('#search-edit-save')
            assert await wait_for(client,"document.querySelector('#search-edit-error').textContent.includes('already enrolled')"), await client.evaluate("({error:document.querySelector('#search-edit-error').textContent,value:document.querySelector('#search-edit-value')?.value,open:document.querySelector('#search-edit-dialog').isOpen,errors:qaErrors})")
            await click('#search-edit-cancel')
            await click('[data-clear-field="phone"]'); await click('#search-confirm-cancel')
            assert await client.evaluate("document.querySelector('#search-profile-content').textContent.includes('123456')")
            await click('[data-clear-field="phone"]'); await click('#search-confirm-delete')
            assert await wait_for(client,"document.querySelector('#search-confirm-dialog').state==='closed' && !document.querySelector('#search-profile-content').textContent.includes('123456')")
            await click('[data-edit-access]')
            assert await wait_for(client,"document.querySelectorAll('#search-edit-form [data-area]').length===2")
            assert await client.evaluate("!document.querySelector('#search-edit-form [data-area=\"2\"]').checked"), 'New access should start unchecked'
            await click('#search-edit-form [data-area="2"]')
            assert await client.evaluate("document.querySelector('#search-edit-form [data-area=\"2\"]').checked"), 'Click did not check Tool area'
            await click('#search-edit-save')
            assert await wait_for(client,"document.querySelector('#search-profile-content').textContent.includes('Tool area') && document.querySelector('#search-edit-dialog').state==='closed'")
            await click('[data-edit-credential="1"]'); await fill('#search-edit-value','11:22:33:44'); await click('#search-edit-save')
            assert await wait_for(client,"document.querySelector('#search-profile-content').textContent.includes('11223344') && document.querySelector('#search-edit-dialog').state==='closed'")
            await click('[data-delete-credential="1"]'); await click('#search-confirm-delete')
            assert await wait_for(client,"document.querySelector('#search-confirm-dialog').state==='closed' && !document.querySelector('#search-profile-content').textContent.includes('11223344')")
            await click('[data-delete-credential="2"]'); await click('#search-confirm-delete')
            assert await wait_for(client,"document.querySelector('#search-confirm-error').textContent.length>0")
            await click('#search-confirm-cancel')
            # A disconnected sensor cannot silently delete an enrolled fingerprint.
            assert await client.evaluate("document.querySelector('#search-profile-content').textContent.includes('template:41')")
            layouts=[]
            for theme in ('light','dark'):
                await client.evaluate(f"document.documentElement.dataset.theme='{theme}'")
                for width in (1440,768,375):
                    await client.send_command('Emulation.setDeviceMetricsOverride',{'width':width,'height':900,'deviceScaleFactor':1,'mobile':False})
                    await asyncio.sleep(.4)
                    info=await client.evaluate("({overflow:document.querySelector('#search-profile-content').scrollWidth-document.querySelector('#search-profile-content').clientWidth,close:document.querySelector('#search-profile-close').getBoundingClientRect().bottom})")
                    assert info['overflow']<=1 and info['close']<=900,info
                    layouts.append({'theme':theme,'width':width,**info})
                    await client.screenshot(str(ARTIFACTS/f'profile-{theme}-{width}.png'))
            await click('#search-profile-close')
            await fill('#search-user-input','P002'); await ready_count('1 / 1 users')
            await click('[data-user-id="2"]')
            assert await wait_for(client,"document.querySelector('#search-profile-content').textContent.includes('Test ban')")
            await click('[data-edit-ban="1"]'); await fill('#search-edit-value','Updated ban'); await click('#search-edit-save')
            assert await wait_for(client,"document.querySelector('#search-profile-content').textContent.includes('Updated ban') && document.querySelector('#search-edit-dialog').state==='closed'")
            await click('[data-lift-ban="1"]'); await click('#search-confirm-delete')
            assert await wait_for(client,"document.querySelector('#search-profile-content').textContent.includes('Lifted') && document.querySelector('#search-confirm-dialog').state==='closed'")
            await click('#search-profile-delete'); await click('#search-confirm-delete'); await ready_count('0 / 0 users')
            assert not await client.evaluate("document.querySelector('#search-profile-dialog').isOpen")
            await fill('#search-user-input','Person 10'); await ready_count('3 / 3 users')
            await click('#search-select-all'); await click('#search-delete'); await click('#search-confirm-delete');await ready_count('0 / 0 users')
            assert await client.evaluate("document.querySelector('#search-delete').disabled && !document.querySelector('#search-select-all').checked")
            await fill('#search-user-input','Aisha'); await ready_count('1 / 1 users')
            for width in (1440,768,375):
                await client.send_command('Emulation.setDeviceMetricsOverride',{'width':width,'height':900,'deviceScaleFactor':1,'mobile':False})
                await asyncio.sleep(.4)
                assert await client.evaluate("document.querySelector('.admin-panel--search').scrollWidth-document.querySelector('.admin-panel--search').clientWidth<=1")
                await client.screenshot(str(ARTIFACTS/f'people-{width}.png'))
            # Keyboard entry to the profile remains available through the Lyne action.
            await client.evaluate("document.querySelector('[data-user-id=\"1\"]').focus()")
            await client.send_command('Input.dispatchKeyEvent',{'type':'keyDown','key':' ','code':'Space','windowsVirtualKeyCode':32})
            await client.send_command('Input.dispatchKeyEvent',{'type':'keyUp','key':' ','code':'Space','windowsVirtualKeyCode':32})
            assert await wait_for(client,"document.querySelector('#search-profile-dialog').isOpen"), await client.evaluate("({active:document.activeElement.outerHTML,target:document.querySelector('[data-user-id=\"1\"]').outerHTML,errors:qaErrors})")
            await click('#search-profile-close')
            result=await api('/api/enrolment/complete',{'name':'Aisha Khan','plaksha_id':'p001'},'POST')
            assert result['status']==409 and 'already enrolled' in result['data']['detail'],result
            result=await api('/api/enrolment/complete',{'name':'Aisha Khan'},'POST')
            assert result['status']==200,result
            assert (await api('/api/users/999999',{'name':'Missing'}))['status']==404
            assert await client.evaluate('qaErrors')==[],await client.evaluate('qaErrors')
            assert await client.evaluate('qaResources')==[],await client.evaluate('qaResources')
            (ARTIFACTS/'results.json').write_text(json.dumps(layouts,indent=2))
            print('PASS: People list, pagination, selection, edits, duplicate errors, access, UID deletion, fingerprint disconnect protection, bans, single/bulk deletion, keyboard, mobile/themes, admin/CSRF, duplicate-name enrolment, no JS/resource errors')
        except Exception:
            print('Browser state:', await client.evaluate("({profile:document.querySelector('#search-profile-content')?.textContent,edit:document.querySelector('#search-edit-title')?.textContent,error:document.querySelector('#search-edit-error')?.textContent,dialogs:[...document.querySelectorAll('sbb-dialog')].map(d=>({id:d.id,state:d.state})),checks:[...document.querySelectorAll('[data-area]')].map(c=>({id:c.dataset.area,checked:c.checked}))})"))
            await client.screenshot(str(ARTIFACTS/'failure.png'))
            raise
        finally: await client.close()


async def main():
    ARTIFACTS.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='labauth-people-') as tmp:
        port=free_port();base=f'http://127.0.0.1:{port}'
        env={**os.environ,'PORT':str(port),'LABAUTH_DB_PATH':str(Path(tmp)/'test.db'),'LABAUTH_ADMIN_PASSWORD':'people-qa','LABAUTH_PICO_PORT':'/nonexistent'}
        with patch.dict(os.environ,env):
            db.init_db()
            a=db.create_user('Aisha Khan',plaksha_id='P001',email='aisha@example.test',phone='123456')
            b=db.create_user('Rohan Gupta',plaksha_id='P002')
            db.set_user_access_areas(a.id,['Indoor lab'])
            db.enroll_credential(a.id,'nfc','AABBCCDD')
            db.enroll_credential(a.id,'fingerprint','template:41')
            db.create_ban(b.id,reason='Test ban')
            for i in range(103):db.create_user(f'Person {i:03d}',plaksha_id=f'T{i:03d}')
        with open(Path(tmp)/'server.log','w+') as log:
            proc=subprocess.Popen([sys.executable,'src/main.py'],cwd=ROOT,env=env,stdout=log,stderr=log)
            try:
                for _ in range(200):
                    try:urllib.request.urlopen(base+'/api/presence',timeout=1).close();break
                    except Exception:
                        if proc.poll() is not None:log.seek(0);raise RuntimeError(log.read())
                        await asyncio.sleep(.4)
                from test_reader_api import ApiClient
                api_client=ApiClient(base)
                api_client.login('people-qa')
                assert api_client.request('/api/users/1',method='PATCH',body={'name':'Intruder'},headers={'Origin':'https://foreign.test'})[0]==403
                await check(base)
            finally:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()

if __name__=='__main__':asyncio.run(main())
