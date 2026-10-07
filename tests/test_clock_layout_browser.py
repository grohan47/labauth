#!/usr/bin/env python3
"""Chromium layout regression: clock hierarchy, alerts, headings and card fit.

Uses a disposable database. Screenshots: /tmp/labauth-clock-layout-qa.
"""
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

MEASURE_LAYOUT = '''(() => {
    const r=s=>document.querySelector(s).getBoundingClientRect();
    const panel=r('.time-panel'),face=r('.clock-stack sbb-clock'),stack=r('.clock-stack'),greet=r('#display-greeting'),frame=r('.display-frame');
    const summary=document.querySelector('.display-summary'), range=document.createRange(); range.selectNodeContents(summary);
    const words=range.getBoundingClientRect();
    const band=document.querySelector('#alert-ticker'), tickerBottom=band.hidden?frame.top:band.getBoundingClientRect().bottom;
    const fits=(a,b)=>a.left>=b.left-1&&a.right<=b.right+1&&a.top>=b.top-1&&a.bottom<=b.bottom+1;
    const overlap=(a,b)=>a.left<b.right-1&&a.right>b.left+1&&a.top<b.bottom-1&&a.bottom>b.top+1;
    return {clock:face.height,greeting:greet.height,
        hierarchy:face.height / 1.08 + 1 >= greet.height,
        fits:fits(stack,panel)&&fits(stack,frame),
        square:Math.abs(face.width-face.height)<1,
        centered:Math.abs((face.left+face.right)-(panel.left+panel.right))<2,
        summary:summary.hidden||(words.top>=tickerBottom&&fits(words,frame)&&!overlap(words,face)),
        clear:stack.top>=tickerBottom-1&&(!greet.height||greet.top>=tickerBottom-1),
        digitalBold:getComputedStyle(document.querySelector('.digital-time')).fontWeight==='700',
        cards:[...document.querySelectorAll('.configured-page.is-active .person-card')].every(n=>fits(n.getBoundingClientRect(),frame)&&n.scrollHeight<=n.clientHeight+1&&n.scrollWidth<=n.clientWidth+1&&[...n.querySelectorAll('.card-content')].every(c=>c.scrollHeight<=c.clientHeight+1&&c.scrollWidth<=c.clientWidth+1)),
        errors:window.qaErrors};
})()'''

async def run():
    with tempfile.TemporaryDirectory(prefix='labauth-clock-layout-') as tmp:
        base = f'http://127.0.0.1:{free_port()}'
        env = {**os.environ, 'PORT': base.rsplit(':', 1)[1],
               'LABAUTH_DB_PATH': str(Path(tmp) / 'test.db'), 'LABAUTH_ADMIN_PASSWORD': 'clock-layout'}
        with open(Path(tmp) / 'server.log', 'w+') as log:
            proc = subprocess.Popen([sys.executable, 'src/main.py'], cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    try:
                        urllib.request.urlopen(base + '/api/presence', timeout=1).close(); break
                    except Exception:
                        if proc.poll() is not None:
                            log.seek(0); raise RuntimeError(log.read())
                        await asyncio.sleep(.15)
                else:
                    raise RuntimeError('Server startup timed out')
                with FreshBrowser('about:blank') as browser:
                    client = await browser.page()
                    try:
                        await client.send_command('Page.navigate', {'url': base + '/display'})
                        assert await wait_for(client, "!!document.querySelector('.configured-display') && !!customElements.get('sbb-clock')")
                        await client.evaluate("fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:'clock-layout'})}).then(r=>r.json())")
                        await client.evaluate("fetch('/api/presence/populate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({count:7})}).then(r=>r.json())")
                        artifacts = Path('/tmp/labauth-clock-layout-qa'); artifacts.mkdir(exist_ok=True)
                        await client.send_command('Page.enable')
                        await client.send_command('Page.addScriptToEvaluateOnNewDocument', {'source': "window.qaErrors=[];addEventListener('error',e=>qaErrors.push(e.message||e.target.src||e.target.href),true);addEventListener('unhandledrejection',e=>qaErrors.push(String(e.reason)))"})
                        alerts = []
                        import random
                        rng = random.Random(710)
                        for severity in ['info', 'caution', 'critical']:
                            payload = {'message': rng.choice(['Instrument calibration in progress.', 'Please leave the central walkway clear.', 'Ventilation maintenance: use the marked benches until the inspection is complete.']), 'severity':severity}
                            result = await client.evaluate("fetch('/api/alerts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify("+json.dumps(payload)+")}).then(r=>r.json())")
                            alerts.append(result['alert'])
                        checked = 0
                        measurements = []
                        for screen in ['display', 'admin-display']:
                            await client.send_command('Page.navigate', {'url':base+'/'+screen})
                            assert await wait_for(client,"window.DISPLAY_SCREEN === "+json.dumps(screen)+" && document.readyState === 'complete' && Array.isArray(window.qaErrors) && !!window.applyDisplaySettings && document.querySelectorAll('.person-card').length===7 && !!document.querySelector('.clock-stack sbb-clock').shadowRoot")
                            initial = await client.evaluate("JSON.parse(document.querySelector('.display-frame').dataset.settings)")
                            for width, height in [(2738,1430), (1440,900), (1280,720), (800,600), (768,1000), (375,900)]:
                                await client.send_command('Emulation.setDeviceMetricsOverride', {'width':width,'height':height,'deviceScaleFactor':1,'mobile':False})
                                for greeter in [True,False]:
                                  for date, digital in [(True,True),(False,True),(True,False),(False,False)]:
                                   for summary in [True,False]:
                                    for alert_on in [True,False]:
                                        cfg = {**initial, 'show_greeter':greeter,'show_clock':True,'show_date':date,'show_digital_time':digital,'show_summary':summary}
                                        await client.evaluate("window.setTheme("+json.dumps('light' if checked % 2 else 'dark')+");window.setAlerts("+json.dumps(alerts if alert_on else [])+");window.applyDisplaySettings("+json.dumps(cfg)+")")
                                        # Include multiline and long-language greetings, without waiting for each 10s cycle.
                                        await client.evaluate("document.querySelector('#display-greeting').textContent="+json.dumps(['Good afternoon!', 'Bon après-midi !', 'Guten Morgen!', 'ਸ਼ੁਭ ਦੁਪਹਿਰ!', 'शुभ दोपहर!'][checked % 5]))
                                        assert await wait_for(client, "JSON.parse(document.querySelector('.display-frame').dataset.settings).show_greeter === "+json.dumps(greeter))
                                        await asyncio.sleep(.25)
                                        info = await client.evaluate(MEASURE_LAYOUT)
                                        case = (screen,width,height,cfg,alert_on,info)
                                        assert 'hierarchy' in info, case
                                        if not info['cards']:
                                            await asyncio.sleep(.5)
                                            info = await client.evaluate(MEASURE_LAYOUT)
                                            case = (screen,width,height,cfg,alert_on,info)
                                        assert all(info[k] for k in ['hierarchy','fits','square','centered','summary','clear','digitalBold','cards']), case
                                        assert not info['errors'], case
                                        checked += 1
                                        measurements.append({'screen':screen,'width':width,'height':height,'greeter':greeter,'date':date,'digital':digital,'summary':summary,'alerts':alert_on,**info})
                                        if date and digital and summary and alert_on:
                                            # Freeze only the QA screenshot's fade for a readable greeting.
                                            await client.evaluate("document.querySelector('#display-greeting').style.opacity='1'")
                                            assert await wait_for(client, "document.querySelector('#alert-ticker').classList.contains('is-visible') && !!document.querySelector('.alert-ticker__text').textContent")
                                            await asyncio.sleep(.35)
                                            await client.screenshot(str(artifacts / f'{screen}-{width}-greeter-{greeter}.png'))
                            print(f'PASS: {screen} layout matrix', flush=True)
                        await client.send_command('Emulation.setDeviceMetricsOverride', {'width':1440,'height':900,'deviceScaleFactor':1,'mobile':False})
                        for greeter in [True,False]:
                            await client.evaluate("window.applyDisplaySettings("+json.dumps({**initial,'show_greeter':greeter,'show_clock':True,'show_date':True,'show_digital_time':True,'show_summary':True})+");window.setTheme('light')")
                            for alert in alerts:
                                await client.evaluate("window.setAlerts("+json.dumps([alert])+")")
                                assert await wait_for(client, "document.querySelector('#alert-ticker').classList.contains('is-visible')")
                                await asyncio.sleep(.4)
                                await client.evaluate("document.querySelector('#display-greeting').style.opacity='1'")
                                await client.screenshot(str(artifacts / f"admin-display-1440-{alert['severity']}-greeter-{greeter}.png"))
                        (artifacts/'measurements.json').write_text(json.dumps(measurements,indent=2))
                        print(f'PASS: {checked} layouts; clock >= greeting, contained square face, bold digital time, unobscured summary, alerts on/off, card fit, no JS/resource errors')
                    finally:
                        await client.close()
            finally:
                proc.terminate(); proc.wait(timeout=10)

if __name__ == '__main__':
    asyncio.run(run())
