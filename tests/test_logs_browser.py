"""Real Chromium QA using a disposable database; no production data changes."""
import asyncio
from datetime import date, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
from unittest.mock import patch
from cdp import free_port, wait_for
from test_display_settings_browser import FreshBrowser

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import database as db
ARTIFACTS=Path(os.environ.get('LABAUTH_SCREENSHOT_DIR','/tmp/labauth-logs-qa'))


async def check(base):
    with FreshBrowser('about:blank') as browser:
        client=await browser.page()
        async def click(selector):
            point=await client.evaluate(f'''(() => {{const n=document.querySelector({json.dumps(selector)}); n.scrollIntoView({{block:'center'}}); const r=n.getBoundingClientRect(); return {{x:r.x+r.width/2,y:r.y+r.height/2}};}})()''')
            await client.send_command('Input.dispatchMouseEvent',{'type':'mousePressed','button':'left','clickCount':1,**point})
            await client.send_command('Input.dispatchMouseEvent',{'type':'mouseReleased','button':'left','clickCount':1,**point})
            await asyncio.sleep(.1)
        async def fill(selector, value):
            await click(selector)
            await client.send_command('Input.dispatchKeyEvent',{'type':'keyDown','key':'a','code':'KeyA','modifiers':2,'windowsVirtualKeyCode':65})
            await client.send_command('Input.dispatchKeyEvent',{'type':'keyUp','key':'a','code':'KeyA','modifiers':2,'windowsVirtualKeyCode':65})
            await client.send_command('Input.insertText',{'text':value})
        async def search(total):
            assert await wait_for(client,f"document.querySelector('#logs-table').getAttribute('aria-busy')!=='true' && document.querySelector('#logs-count').textContent.endsWith('/ {total} visits')"), await client.evaluate("document.querySelector('#logs-error').textContent")
        try:
            await client.send_command('Page.enable')
            await client.send_command('Page.addScriptToEvaluateOnNewDocument',{'source':'''window.qaErrors=[]; window.qaResources=[];
              addEventListener('error',e=>{if(e.message)qaErrors.push(e.message);else if(e.target.src||e.target.href)qaResources.push(e.target.src||e.target.href);},true);
              addEventListener('unhandledrejection',e=>qaErrors.push(String(e.reason)));'''})
            await client.send_command('Page.navigate',{'url':base+'/display'})
            assert await wait_for(client,"document.readyState==='complete'")
            assert await client.evaluate("fetch('/api/logs').then(r=>r.status)")==401
            assert await client.evaluate("fetch('/api/logs/sql',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sql:'SELECT 1'})}).then(r=>r.status)")==401
            assert await client.evaluate("fetch('/api/logs/export').then(r=>r.status)")==401
            assert await client.evaluate("fetch('/api/logs/schema').then(r=>r.status)")==401
            assert await client.evaluate("fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:'logs-qa'})}).then(r=>r.status)")==200
            await client.send_command('Page.navigate',{'url':base+'/logs'})
            assert await wait_for(client,"document.querySelector('#logs-count')?.textContent==='1–50 / 57 visits'"), await client.evaluate("({text:document.body.innerText,errors:qaErrors,resources:qaResources,defined:['sbb-select','sbb-dialog','sbb-image','sbb-button','sbb-transparent-button','sbb-table-wrapper','sbb-tooltip'].map(t=>[t,!!customElements.get(t)])})")
            assert await client.evaluate("document.querySelector('#logs-search')===null")
            assert await client.evaluate("document.querySelector('#logs-from_date').max")==date.today().isoformat()
            await asyncio.sleep(.3)
            await client.screenshot(str(ARTIFACTS/'logs-default.png'))
            assert await client.evaluate("[...document.querySelectorAll('#logs-rows tr')].slice(0,2).every(r=>r.dataset.state==='inside')")
            assert await client.evaluate("document.querySelectorAll('#logs-rows sbb-image').length") == 50
            await click('#logs-next')
            assert await wait_for(client,"document.querySelector('#logs-count').textContent==='51–57 / 57 visits'")
            await click('#logs-prev')
            assert await wait_for(client,"document.querySelector('#logs-count').textContent==='1–50 / 57 visits'")
            await fill('#logs-name','Aisha')
            await search(3)
            assert await client.evaluate("document.querySelectorAll('#logs-rows tr').length")==3
            await click('[data-detail="0"]')
            assert await wait_for(client,"document.querySelector('#logs-detail-dialog').isOpen")
            assert 'Aisha' in await client.evaluate("document.querySelector('#logs-detail-content').textContent")
            await asyncio.sleep(.5)
            await client.screenshot(str(ARTIFACTS/'visit-detail.png'))
            await click('#logs-detail-close')
            await asyncio.sleep(.5)
            await click('#logs-more')
            assert await client.evaluate("!document.querySelector('#logs-extra').hidden")
            await click('#logs-kind')
            assert await wait_for(client,"document.querySelector('#logs-kind').isOpen")
            await click('#logs-kind sbb-option[value="visitor"]')
            assert await client.evaluate("document.querySelector('#logs-kind').value")=='visitor'
            assert await wait_for(client,"document.querySelector('#logs-count').textContent==='0 visits'")
            assert await client.evaluate("document.querySelector('#logs-rows').textContent.trim()")=='No matching visits.'
            await click('#logs-reset')
            assert await wait_for(client,"document.querySelector('#logs-count').textContent==='1–50 / 57 visits'")
            # Native date/time controls use browser input values; exercise submit and the resulting API query.
            await client.evaluate("for(const [key,value] of Object.entries({from_date:'2026-10-07',from_time:'09:00',until_date:'2026-10-07',until_time:'09:30'})){const n=document.getElementById('logs-'+key);n.value=value;n.dispatchEvent(new Event('input',{bubbles:true}));}")
            await search(1)
            assert await client.evaluate("document.querySelector('#logs-rows').textContent.includes('23:30')")
            exported=await client.evaluate("fetch('/api/logs/export'+location.search).then(r=>r.text())")
            assert 'Aisha' in exported and 'Rohan' not in exported
            await client.evaluate("const n=document.querySelector('#logs-from_date'); n.value='2099-10-08'; n.dispatchEvent(new Event('change',{bubbles:true}));")
            assert await wait_for(client,"document.querySelector('#logs-error').textContent==='Future dates are unavailable.'")
            await click('#logs-reset')
            assert await wait_for(client,"document.querySelector('#logs-count').textContent==='1–50 / 57 visits'")
            await click('#logs-sql-open')
            assert await wait_for(client,"document.querySelector('#logs-sql-dialog').isOpen")
            assert await wait_for(client,"document.querySelector('#logs-schema').textContent.includes('user_id')")
            schema=await client.evaluate("fetch('/api/logs/schema').then(r=>r.json())")
            assert await client.evaluate("document.querySelector('#logs-sql_table').options.length")==len(schema['tables'])
            assert 'TEXT' in await client.evaluate("document.querySelector('#logs-schema').textContent")
            await client.screenshot(str(ARTIFACTS/'sql-schema.png'))
            # Selecting a different table updates both its query and its schema.
            await click('#logs-sql_table')
            assert await wait_for(client,"document.querySelector('#logs-sql_table').isOpen")
            await click('#logs-sql_table sbb-option[value="users"]')
            await asyncio.sleep(.4)
            assert await wait_for(client,"document.querySelector('#logs-schema').textContent.includes('plaksha_id') && document.querySelector('#logs-query').value.includes('users')")
            await click('#logs-sql-run')
            assert await wait_for(client,"document.querySelector('#logs-sql-status').textContent==='3 rows'"), await client.evaluate("({status:document.querySelector('#logs-sql-status').textContent,sql:document.querySelector('#logs-query').value,errors:qaErrors})")
            await click('#logs-sql_table')
            await click('#logs-sql_table sbb-option[value="presence_log"]')
            await asyncio.sleep(.4)
            await click('#logs-sql-run')
            assert await wait_for(client,"document.querySelector('#logs-sql-status').textContent==='100 rows'")
            await asyncio.sleep(.5)
            await client.screenshot(str(ARTIFACTS/'sql.png'))
            await fill('#logs-query','DELETE FROM presence_log')
            await click('#logs-sql-run')
            assert await wait_for(client,"document.querySelector('#logs-sql-status').textContent.includes('not authorized')")
            statuses=await client.evaluate('''Promise.all([
              'WITH x AS (SELECT 1) DELETE FROM users RETURNING id',
              'SELECT 1; DELETE FROM presence_log',
              'PRAGMA query_only=OFF', 'DROP TABLE users'
            ].map(sql=>fetch('/api/logs/sql',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sql})}).then(r=>r.status)))''')
            assert statuses==[422,422,422,422],statuses
            await click('#logs-sql-close')
            await asyncio.sleep(.5)
            layouts=[]
            for theme in ('light','dark'):
                await client.evaluate(f"document.documentElement.dataset.theme='{theme}'")
                for width in (1440,1024,768,375):
                    await client.send_command('Emulation.setDeviceMetricsOverride',{'width':width,'height':900,'deviceScaleFactor':1,'mobile':False})
                    await client.evaluate("document.querySelector('.admin-panel--logs').scrollTop=0")
                    await asyncio.sleep(.2)
                    info=await client.evaluate('''(() => {const panel=document.querySelector('.admin-panel--logs');return {
                      overflow:panel.scrollWidth-panel.clientWidth, bodyOverflow:document.body.scrollWidth-innerWidth,
                      fields:[...document.querySelectorAll('#logs-filters sbb-form-field')].every(n=>n.getBoundingClientRect().width>0),
                      images:[...document.querySelectorAll('#logs-rows sbb-image')].every(n=>n.getBoundingClientRect().width===48),
                      footerVisible:document.querySelector('.logs-footer').getBoundingClientRect().bottom<=innerHeight+1,
                      loaded:[...document.querySelectorAll('#logs-rows sbb-image')].every(n=>n.shadowRoot.querySelector('img')?.complete)
                    };})()''')
                    assert info['overflow']<=1 and info['bodyOverflow']<=1,info
                    assert info['fields'] and info['images'] and info['loaded'],info
                    if width>700: assert info['footerVisible'],await client.evaluate("[...document.querySelectorAll('.admin-panel--logs,.admin-panel-shell,#logs-filters,#logs-table,.logs-footer')].map(n=>({tag:n.tagName,cls:n.className,height:n.getBoundingClientRect().height,y:n.getBoundingClientRect().y,style:getComputedStyle(n).display,shadow:n.tagName==='SBB-CONTAINER'?n.shadowRoot.innerHTML.slice(-2500):null}))")
                    layouts.append({'theme':theme,'width':width,**info})
                    await client.screenshot(str(ARTIFACTS/f'logs-{theme}-{width}.png'))
            # Schema and editor remain usable in narrow SQL dialogs.
            await click('#logs-sql-open')
            assert await wait_for(client,"document.querySelector('#logs-schema').textContent.includes('occurred_at')")
            await asyncio.sleep(.5)
            for width in (768,375):
                await client.send_command('Emulation.setDeviceMetricsOverride',{'width':width,'height':900,'deviceScaleFactor':1,'mobile':False})
                await asyncio.sleep(.2)
                info=await client.evaluate("({schema:document.querySelector('#logs-schema').scrollWidth-document.querySelector('#logs-schema').clientWidth,right:document.querySelector('#logs-query').getBoundingClientRect().right,run:document.querySelector('#logs-sql-run').getBoundingClientRect().bottom})")
                assert info['schema']<=1 and info['right']<=width+1 and info['run']<=900,info
                await client.screenshot(str(ARTIFACTS/f'sql-schema-dark-{width}.png'))
            await click('#logs-sql-close')
            await asyncio.sleep(.5)
            assert await client.evaluate('qaErrors')==[],await client.evaluate('qaErrors')
            assert await client.evaluate('qaResources')==[],await client.evaluate('qaResources')
            # Visibility restoration updates in place and keeps the page's controls.
            await client.evaluate("document.querySelector('#logs-filters').dataset.qa='preserved'")
            assert await client.evaluate("fetch('/api/presence/check-in',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'New arrival'})}).then(r=>r.status)")==200
            await client.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            assert await wait_for(client,"document.querySelector('#logs-count').textContent==='1–50 / 58 visits'")
            assert await client.evaluate("document.querySelector('#logs-filters').dataset.qa")=='preserved'
            # Close/reopen secondary row; keyboard Tab reaches actual controls.
            await click('#logs-more')
            await client.send_command('Input.dispatchKeyEvent',{'type':'keyDown','key':'Tab','code':'Tab','windowsVirtualKeyCode':9})
            assert await client.evaluate("document.activeElement.tagName.startsWith('SBB-')")
            await click('sbb-secondary-button-link[href="/admin"]')
            assert await wait_for(client,"location.pathname==='/admin'")
            (ARTIFACTS/'results.json').write_text(json.dumps(layouts,indent=2))
            print('PASS: authentication, live-first ordering, pagination, name search, Lyne dropdown, details, overlap, CSV, errors, SQL protection, all-table schema, automatic filters, future-date exclusion, keyboard, Back, 8 responsive/theme layouts, no JS/resource errors')
        finally: await client.close()


async def main():
    ARTIFACTS.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='labauth-logs-') as tmp:
        port=free_port(); base=f'http://127.0.0.1:{port}'
        env={**os.environ,'PORT':str(port),'LABAUTH_DB_PATH':str(Path(tmp)/'test.db'),'LABAUTH_ADMIN_PASSWORD':'logs-qa','TZ':'Asia/Kolkata'}
        with patch.dict(os.environ,env):
            db.init_db()
            a=db.create_user('Aisha Khan',plaksha_id='P001')
            b=db.create_user('Rohan Gupta',is_temp=True)
            c=db.create_user('Meera Nair')
            for start,end in [('2026-10-06T18:00:00Z','2026-10-07T04:30:00Z'),('2026-10-07T05:00:00Z','2026-10-07T06:00:00Z')]:
                db.log_presence(a.id,'check_in','nfc',occurred_at=start)
                db.log_presence(a.id,'check_out','fingerprint',occurred_at=end)
            db.log_presence(a.id,'check_in',occurred_at='2026-10-07T06:30:00Z')
            db.upsert_current_presence(a.id,'2026-10-07T06:30:00Z')
            db.log_presence(b.id,'check_in',occurred_at='2026-10-07T06:40:00Z')
            db.upsert_current_presence(b.id,'2026-10-07T06:40:00Z')
            for i in range(53):
                at=(date(2026,8,1)+timedelta(days=i)).isoformat()
                db.log_presence(c.id,'check_in',occurred_at=at+'T04:00:00Z')
                db.log_presence(c.id,'check_out',occurred_at=at+'T05:00:00Z')
        with open(Path(tmp)/'server.log','w+') as log:
            proc=subprocess.Popen([sys.executable,'src/main.py'],cwd=ROOT,env=env,stdout=log,stderr=log)
            try:
                for _ in range(200):
                    try: urllib.request.urlopen(base+'/api/presence',timeout=1).close();break
                    except Exception:
                        if proc.poll() is not None: log.seek(0);raise RuntimeError(log.read())
                        await asyncio.sleep(.15)
                await check(base)
            finally:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()

if __name__=='__main__':asyncio.run(main())
