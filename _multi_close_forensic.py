"""
PHASE=ATP_MULTI_MODAL_CLOSE_ROOT_CAUSE_ONLY — Forensic on live 8080
NO source code changes. Temporary in-page debug hooks only.
"""
import json, pathlib, sqlite3, sys

ROOT = pathlib.Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:8080'
OUT = ROOT / '_multi_close_forensic.json'


def safe_print(s):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode('ascii', 'replace').decode('ascii'))


def _creds():
    db = ROOT / 'app' / 'mock_data.db'
    if not db.exists():
        return 'admin', 'admin123'
    con = sqlite3.connect(str(db))
    row = con.execute('SELECT KullaniciAdi, Sifre FROM sistem_kullanici WHERE Aktif=1 LIMIT 1').fetchone()
    con.close()
    return (row[0], row[1]) if row else ('admin', 'admin123')


HOOK_JS = r"""
(() => {
  window.__atpForensic = { closes: [], events: [], stack: [] };
  const log = (kind, detail) => {
    window.__atpForensic.events.push(Object.assign({ t: Date.now(), kind }, detail));
  };

  const backdrop = document.getElementById('atpMultiBackdrop');
  const hit = document.getElementById('atpMultiBackdropHit');
  const modal = document.getElementById('atpMultiModal');

  function pathInfo(e) {
    const p = (e && e.composedPath) ? e.composedPath().slice(0, 8) : [];
    return p.map(n => {
      if (!n || !n.tagName) return String(n);
      const id = n.id ? ('#' + n.id) : '';
      const cls = (n.className && typeof n.className === 'string') ? ('.' + n.className.split(/\s+/).slice(0,2).join('.')) : '';
      return n.tagName + id + cls;
    });
  }

  function elInfo(el) {
    if (!el) return null;
    return {
      tag: el.tagName,
      id: el.id || '',
      cls: (el.className && typeof el.className === 'string') ? el.className : '',
    };
  }

  ['mousedown','mouseup','click'].forEach(evt => {
    document.addEventListener(evt, e => {
      if (!backdrop || !backdrop.classList.contains('open')) return;
      const insideModal = modal && (modal.contains(e.target) || pathInfo(e).some(x => x.indexOf('atpMultiModal') >= 0));
      log(evt, {
        target: elInfo(e.target),
        currentTarget: 'document-capture',
        path: pathInfo(e),
        insideModal,
        activeElement: document.activeElement ? elInfo(document.activeElement) : null,
      });
    }, true);
  });

  if (backdrop) {
    const obs = new MutationObserver(muts => {
      muts.forEach(m => {
        if (m.attributeName === 'class') {
          const open = backdrop.classList.contains('open');
          if (!open) {
            window.__atpForensic.closes.push({
              t: Date.now(),
              reason: 'backdrop.classList changed — open removed',
              stack: (new Error('close trace')).stack,
            });
          }
        }
      });
    });
    obs.observe(backdrop, { attributes: true, attributeFilter: ['class'] });
  }

  // Wrap native listeners on hit layer if present
  if (hit) {
    const origAdd = hit.addEventListener.bind(hit);
    // can't unwrap existing — add our own capture listeners
    hit.addEventListener('mousedown', e => {
      log('hit-mousedown', { target: elInfo(e.target), path: pathInfo(e) });
    }, true);
    hit.addEventListener('click', e => {
      log('hit-click', { target: elInfo(e.target), path: pathInfo(e) });
    }, true);
  }
  if (modal) {
    modal.addEventListener('click', e => {
      log('modal-click-bubble', { target: elInfo(e.target), path: pathInfo(e) });
    }, false);
  }

  // Detect which element is topmost at coordinate
  window.__atpForensic.elementFromPoint = (x, y) => {
    const el = document.elementFromPoint(x, y);
    return elInfo(el);
  };
})();
"""


def login(page):
    user, pwd = _creds()
    page.goto(BASE + '/giris', wait_until='networkidle', timeout=30000)
    page.fill('input[name="kullanici"]', user)
    page.fill('input[name="sifre"]', pwd)
    page.click('button[type="submit"]')
    page.wait_for_url('**/', timeout=20000)
    page.goto(BASE + '/planlama/arac-takip/?tab=gunluk&date=2026-08-24', wait_until='networkidle', timeout=30000)
    page.wait_for_timeout(1200)


def is_open(page):
    return page.locator('#atpMultiBackdrop.open').count() > 0


def open_multi(page):
    if is_open(page):
        return
    page.locator('#atpBtnPlanaIsEkle').first.click()
    page.wait_for_selector('#atpMultiBackdrop.open', timeout=10000)
    page.wait_for_timeout(600)


def click_point(page, x, y, label, results):
    open_multi(page)
    before = is_open(page)
    top = page.evaluate('([x,y]) => window.__atpForensic.elementFromPoint(x,y)', [x, y])
    page.mouse.click(x, y)
    page.wait_for_timeout(350)
    after = is_open(page)
    forensic = page.evaluate('() => ({ events: window.__atpForensic.events.slice(-12), closes: window.__atpForensic.closes.slice(-3) })')
    results.append({
        'label': label,
        'x': x, 'y': y,
        'topElement': top,
        'wasOpen': before,
        'stillOpen': after,
        'closed': before and not after,
        'lastEvents': forensic.get('events', []),
        'closes': forensic.get('closes', []),
    })
    safe_print(f"  [{label}] top={top} closed={before and not after}")


def main():
    from playwright.sync_api import sync_playwright
    all_results = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        for vp_name, w, h in [('1920', 1920, 1080), ('1366', 1366, 768)]:
            ctx = browser.new_context(viewport={'width': w, 'height': h})
            page = ctx.new_page()
            login(page)
            page.evaluate(HOOK_JS)

            src = page.eval_on_selector('script[src*="planlama_arac_takip.js"]', 'e=>e.src')
            safe_print(f"\n=== FORENSIC {vp_name} JS={src} ===")

            open_multi(page)
            modal = page.locator('#atpMultiModal').bounding_box()
            hit = page.locator('#atpMultiBackdropHit').bounding_box()
            if not modal or not hit:
                safe_print('  modal/hit bbox missing')
                ctx.close()
                continue

            mx, my, mw, mh = modal['x'], modal['y'], modal['width'], modal['height']

            points = [
                ('header_blank', mx + 40, my + 18),
                ('top_info', mx + 40, my + 110),
                ('table_cell', mx + mw * 0.72, my + 200),
                ('body_white', mx + mw * 0.5, my + mh * 0.55),
                ('footer_blank', mx + 30, my + mh - 25),
                ('info_panel', mx + mw * 0.75, my + mh * 0.72),
                ('mini_map', mx + mw * 0.2, my + mh * 0.72),
                ('outside_backdrop', max(hit['x'] + 10, mx - 30), my + mh / 2),
            ]

            for label, x, y in points:
                click_point(page, x, y, f'{vp_name}_{label}', all_results)

            page.screenshot(path=str(ROOT / f'_forensic_{vp_name}.png'))
            ctx.close()

        browser.close()

    OUT.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding='utf-8')
    safe_print(f"\nWrote {OUT}")

    failures = [r for r in all_results if r['closed'] and 'outside' not in r['label']]
    if failures:
        safe_print(f"\nINTERNAL CLICK CLOSED MODAL: {len(failures)} case(s)")
        for f in failures:
            safe_print(f"  - {f['label']}: top={f['topElement']}")
            if f['lastEvents']:
                le = f['lastEvents'][-1]
                safe_print(f"    lastEvent={le.get('kind')} target={le.get('target')}")
    else:
        safe_print('\nNo internal blank click closed modal in forensic run')

    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
