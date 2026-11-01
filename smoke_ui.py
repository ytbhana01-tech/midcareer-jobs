"""Browser checks against the built static artifact. Run: python smoke_ui.py."""
import contextlib
import datetime as dt
import functools
import json
import os
from pathlib import Path
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from playwright.sync_api import sync_playwright, expect
from build import build


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    root = build()
    handler = functools.partial(QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as p:
            executable = os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium')
            browser = p.chromium.launch(executable_path=executable, headless=True, args=['--no-sandbox'])
            page = browser.new_page(viewport={'width':1440,'height':1000})
            errors = []
            page.on('pageerror',lambda error:errors.append(str(error)))
            snapshot=json.loads((root/'jobs.json').read_text(encoding='utf-8'))
            page.clock.set_fixed_time(dt.datetime.fromisoformat(snapshot['updated_at']))
            page.goto(base)
            expect(page.locator('.job').first).to_be_visible()
            assert int(page.locator('#total-stat').inner_text().replace(',','')) > 0
            assert '인증 API' in page.locator('#feed-notice').inner_text() or '목록·상세 API' in page.locator('#feed-notice').inner_text()
            page.locator('[data-detail]').first.click()
            assert page.locator('#detail').evaluate('(d)=>d.open')
            assert page.locator('#detail-content').inner_text()
            assert page.locator('#detail-source').get_attribute('href').startswith('https://')
            page.keyboard.press('Escape')
            page.locator('#employment').select_option('')
            page.locator('#education').select_option('학력무관')
            assert int(page.locator('#count').inner_text().replace(',','')) > 0
            page.locator('#q').fill('아무것도없는기관xyz')
            expect(page.locator('.job')).to_have_count(0)
            expect(page.locator('.empty')).to_contain_text('조건에 맞는')
            page.locator('#reset-filters').click()
            expect(page.locator('.job')).to_have_count(20)
            page.locator('#more').click()
            expect(page.locator('.job')).to_have_count(40)
            page.locator('#region').select_option('서울')
            for region in page.locator('.facts dd:first-of-type').all_text_contents():
                assert '서울' in region
            page.locator('#reset-filters').click()
            page.locator('#employment').select_option('focus')
            page.locator('#sort').select_option('recent')
            Path('playwright-artifacts').mkdir(exist_ok=True)
            page.screenshot(path='playwright-artifacts/desktop.png',full_page=False)
            for width in (320,390,768,1440):
                page.set_viewport_size({'width':width,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),width
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path='playwright-artifacts/mobile.png',full_page=True)
            print('PASS: real feed, search, source links, modal/escape, filters, reset, pagination, sort, responsive widths 320/390/768/1440')
            # Controlled feed exercises malicious strings, unknown fields, expiry, and exact matching.
            fixture={'updated_at':'2026-11-01T12:00:00+09:00','source':'alio-public-preview',
                     'authenticated_api_verified':False,'jobs':[
                {'id':'1','title':'공무직 <img src=x onerror=alert(1)>','org':'기관','region':'서울',
                 'type':'무기계약직','career':'신입+경력','education':'학력무관',
                 'tags':['공무직','무기계약직','학력무관'],'start':'2026-10-01','deadline':'2026-11-01',
                 'source_url':'https://example.org/notice','qualifications':'<script>alert(1)</script>'},
                {'id':'2','title':'미확인 조건','org':'기관','region':'경기','type':'','career':'','education':'',
                 'tags':[],'deadline':'2026-11-02','source_url':'https://example.org/other'},
                {'id':'3','title':'마감','org':'기관','tags':['공무직'],'deadline':'2026-10-31',
                 'source_url':'https://example.org/expired'},
                {'id':'4','title':'위험 링크','org':'기관','tags':['공무직'],'deadline':'2026-11-02',
                 'source_url':'javascript:alert(1)'}]}
            page.route('**/jobs.json',lambda route:route.fulfill(json=fixture))
            page.clock.set_fixed_time(dt.datetime(2026,11,1,3,tzinfo=dt.timezone.utc))
            page.reload();expect(page.locator('.job')).to_have_count(1)
            assert page.locator('.job img').count()==0
            assert page.locator('.job h3').inner_text().endswith('<img src=x onerror=alert(1)>')
            page.locator('[data-detail]').first.click()
            assert page.locator('#detail-content script').count()==0
            assert '<script>' in page.locator('#detail-content').inner_text()
            page.keyboard.press('Escape')
            page.locator('#career').select_option('경력무관');expect(page.locator('.job')).to_have_count(0)
            page.locator('#reset-filters').click();expect(page.locator('.job')).to_have_count(2)
            page.locator('#career').select_option('unknown');expect(page.locator('.job')).to_have_count(1)
            expect(page.locator('.job h3')).to_have_text('미확인 조건')
            page.locator('#reset-filters').click()
            page.clock.set_fixed_time(dt.datetime(2026,11,1,15,0,1,tzinfo=dt.timezone.utc))
            page.evaluate('render()');expect(page.locator('.job')).to_have_count(1)
            expect(page.locator('.job h3')).to_have_text('미확인 조건')
            page.unroute('**/jobs.json')
            page.route('**/jobs.json',lambda route:route.fulfill(status=503,body='Unavailable'))
            page.reload();expect(page.locator('#feed-notice')).to_contain_text('불러오지 못했습니다')
            expect(page.locator('.job')).to_have_count(0)
            assert not errors,errors
            print('PASS: XSS escaping, unsafe URL rejection, unknown fields, strict career filter, KST midnight expiry, feed failure; zero page errors')
            browser.close()
    finally:
        server.shutdown();server.server_close()


if __name__ == '__main__':
    main()
