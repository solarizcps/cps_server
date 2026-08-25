"""
Extended forensic — blur, text drag, scroll gaps, stale-cache check
"""
import json, pathlib, sqlite3, sys

ROOT = pathlib.Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:8080'

HOOK_JS = open(ROOT / '_multi_close_forensic.py').read().split('HOOK_JS = r"""')[1].split('"""')[0]


def _creds():
    db = ROOT / 'app' / 'mock_data.db'
    con = sqlite3.connect(str(db))
    row = con.execute('SELECT KullaniciAdi, Sifre FROM sistem_kullanici WHERE Aktif=1 LIMIT 1').fetchone()
    con.close()
    return row[0], row[1]


def main():
    from playwright.sync_api import sync_playwright
    results = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = ctx.new_page()
        user, pwd = _creds()
        page.goto(BASE + '/giris', wait_until='networkidle')
        page.fill('input[name="kullanici"]', user)
        page.fill('input[name="sifre"]', pwd)
        page.click('button[type="submit"]')
        page.wait_for_url('**/', timeout=20000)
        page.goto(BASE + '/planlama/arac-takip/?tab=gunluk&date=2026-08-24', wait_until='networkidle')
        page.wait_for_timeout(1200)

        assets = page.evaluate("""() => ({
          js: [...document.querySelectorAll('script[src*="planlama_arac_takip.js"]')].map(s=>s.src),
          css: [...document.querySelectorAll('link[href*="planlama_arac_takip.css"]')].map(l=>l.href),
          hasHit: !!document.getElementById('atpMultiBackdropHit'),
          dom: document.getElementById('atpMultiBackdrop')?.innerHTML?.slice(0,120)
        })""")
        print('ASSETS:', json.dumps(assets, indent=2))

        page.evaluate(HOOK_JS)
        page.locator('#atpBtnPlanaIsEkle').click()
        page.wait_for_selector('#atpMultiBackdrop.open')
        page.wait_for_timeout(800)

        def snap(label, fn):
            before = page.locator('#atpMultiBackdrop.open').count() > 0
            fn()
            page.wait_for_timeout(400)
            after = page.locator('#atpMultiBackdrop.open').count() > 0
            ev = page.evaluate('() => window.__atpForensic.events.slice(-6)')
            cl = page.evaluate('() => window.__atpForensic.closes.slice(-2)')
            r = {'label': label, 'closed': before and not after, 'events': ev, 'closes': cl}
            results.append(r)
            print(f"  {label}: closed={r['closed']}")
            if not after:
                page.locator('#atpBtnPlanaIsEkle').click()
                page.wait_for_selector('#atpMultiBackdrop.open')
                page.wait_for_timeout(500)

        modal = page.locator('#atpMultiModal').bounding_box()

        # blur: focus firma then click body gap
        snap('blur_firma_to_body', lambda: (
            page.locator('.row-firma').first.click(),
            page.locator('.row-firma').first.type('TEST'),
            page.mouse.click(modal['x'] + modal['width'] * 0.5, modal['y'] + modal['height'] * 0.45)
        ))

        # text drag from firma toward left backdrop
        def drag():
            f = page.locator('.row-firma').first.bounding_box()
            page.mouse.move(f['x']+5, f['y']+f['height']/2)
            page.mouse.down()
            page.mouse.move(modal['x'] - 20, f['y']+f['height']/2, steps=10)
            page.mouse.up()
        snap('text_drag_to_outside', drag)

        # click table wrap scrollbar area / empty below rows
        snap('table_wrap_blank', lambda: page.locator('.atp-multi-table-wrap').click(position={'x': 20, 'y': 200}))

        # click hdr between title and X (true padding)
        snap('hdr_padding', lambda: page.locator('.atp-multi-hdr').click(position={'x': 300, 'y': 15}))

        # click just below modal bottom edge (might look "inside" UI chrome)
        snap('below_modal_edge', lambda: page.mouse.click(modal['x'] + modal['width']/2, modal['y'] + modal['height'] + 8))

        # add row then click empty tbody area
        snap('after_add_row_blank', lambda: (
            page.click('#atpMultiBtnSatirEkle'),
            page.wait_for_timeout(200),
            page.locator('.atp-multi-table-wrap').click(position={'x': 50, 'y': 120})
        ))

        OUT = ROOT / '_multi_close_forensic_ext.json'
        OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Wrote', OUT)
        browser.close()

    fails = [r for r in results if r['closed']]
    return 1 if fails else 0

if __name__ == '__main__':
    sys.exit(main())
