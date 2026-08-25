"""
Simulate pre-FIX3 stacking / many-row layout forensic
"""
import json, pathlib, sqlite3, sys

ROOT = pathlib.Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:8080'


def _creds():
    con = sqlite3.connect(str(ROOT / 'app' / 'mock_data.db'))
    row = con.execute('SELECT KullaniciAdi, Sifre FROM sistem_kullanici WHERE Aktif=1 LIMIT 1').fetchone()
    con.close()
    return row[0], row[1]


def main():
    from playwright.sync_api import sync_playwright
    results = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={'width': 1366, 'height': 768})
        page = ctx.new_page()
        user, pwd = _creds()
        page.goto(BASE + '/giris', wait_until='networkidle')
        page.fill('input[name="kullanici"]', user)
        page.fill('input[name="sifre"]', pwd)
        page.click('button[type="submit"]')
        page.wait_for_url('**/', timeout=20000)
        page.goto(BASE + '/planlama/arac-takip/?tab=gunluk&date=2026-08-24', wait_until='networkidle')
        page.wait_for_timeout(1200)

        page.locator('#atpBtnPlanaIsEkle').click()
        page.wait_for_selector('#atpMultiBackdrop.open')
        page.wait_for_timeout(600)

        # add 4 rows to force scroll / compact layout
        for _ in range(4):
            page.click('#atpMultiBtnSatirEkle')
            page.wait_for_timeout(150)

        modal = page.locator('#atpMultiModal').bounding_box()

        def probe(label, x, y, strip_zindex=False):
            if strip_zindex:
                page.evaluate("""() => {
                  const m = document.getElementById('atpMultiModal');
                  if (m) { m.style.position = 'static'; m.style.zIndex = 'auto'; }
                }""")
            top = page.evaluate('([x,y]) => { const el = document.elementFromPoint(x,y); return el ? {tag:el.tagName,id:el.id,cls:el.className} : null; }', [x, y])
            before = page.locator('#atpMultiBackdrop.open').count() > 0
            page.mouse.click(x, y)
            page.wait_for_timeout(350)
            after = page.locator('#atpMultiBackdrop.open').count() > 0
            results.append({'label': label, 'x': x, 'y': y, 'top': top, 'closed': before and not after, 'strip_zindex': strip_zindex})
            print(f"  {label} top={top} closed={before and not after} strip_z={strip_zindex}")
            if not after:
                page.locator('#atpBtnPlanaIsEkle').click()
                page.wait_for_selector('#atpMultiBackdrop.open')
                page.wait_for_timeout(500)
                for _ in range(4):
                    page.click('#atpMultiBtnSatirEkle')
                    page.wait_for_timeout(100)

        mx, my, mw, mh = modal['x'], modal['y'], modal['width'], modal['height']

        # normal stacking probes
        probe('gap_table_bottom', mx + mw * 0.5, my + mh * 0.58, False)
        probe('scroll_area_right', mx + mw - 8, my + 250, False)
        probe('between_hdr_top', mx + mw * 0.5, my + 55, False)

        # simulate missing CSS z-index (pre-FIX3 CSS cache scenario)
        probe('body_no_zindex', mx + mw * 0.5, my + mh * 0.5, True)
        probe('footer_no_zindex', mx + 40, my + mh - 20, True)
        probe('table_no_zindex', mx + mw * 0.6, my + 280, True)

        OUT = ROOT / '_multi_close_forensic_sim.json'
        OUT.write_text(json.dumps(results, indent=2), encoding='utf-8')
        browser.close()

    fails = [r for r in results if r['closed'] and 'outside' not in r['label']]
    print('FAILS', fails)
    return 1 if fails else 0

if __name__ == '__main__':
    sys.exit(main())
