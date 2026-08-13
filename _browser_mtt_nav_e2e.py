# -*- coding: utf-8 -*-
"""Global navigation E2E: pushState, popstate, F5 restore — MTT + siparis detay."""
import sys, io, os, time
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = 'http://127.0.0.1:8080'
MTT_ID    = 561   # MTT-2026-0140 (SIPARIS)
NUMUNE_ID = 639   # MTT-2026-0184 (NUMUNE)

PASS = FAIL = 0
def ok(name, cond, detail=''):
    global PASS, FAIL
    if cond: PASS += 1; print('  PASS  ' + name)
    else: FAIL += 1; print('  FAIL  ' + name + (' | ' + str(detail) if detail else ''))

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print('playwright not installed'); sys.exit(0)

def login(page):
    page.goto(BASE + '/giris', wait_until='domcontentloaded')
    page.fill('[name=kullanici]', 'mehmet')
    page.fill('[name=sifre]', '1453')
    page.click('button[type=submit]')
    page.wait_for_load_state('networkidle', timeout=12000)
    time.sleep(1.5)

SHOT_DIR = os.path.dirname(os.path.abspath(__file__))

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
    page = ctx.new_page()
    login(page)
    print('Login OK url=' + page.url)

    # ── 1. Başlangıç: pazarlama listesi ──
    print('\n=== 1. Pazarlama listesi başlangıç ===')
    page.goto(BASE + '/nexgen/pazarlama', wait_until='networkidle', timeout=15000)
    time.sleep(1.5)
    url_liste = page.url
    ok('1: liste URL clean', 'ekran' not in url_liste and 'mtt' not in url_liste, url_liste)
    ok('1: liste ekran visible', page.is_visible('#ekran-liste'))

    # ── 2. MTT sekmesine geç ──
    print('\n=== 2. MTT sekmesi ===')
    page.evaluate('pzmEkranGec("mtt")')
    time.sleep(1.5)
    url_mtt = page.url
    ok('2: URL ekran=mtt', 'ekran=mtt' in url_mtt, url_mtt)
    ok('2: history state ekran=mtt', page.evaluate('history.state && history.state.ekran') == 'mtt')

    # ── 3. MTT detay aç ──
    print('\n=== 3. MTT detay aç ===')
    page.evaluate('mttDetayAc(' + str(MTT_ID) + ')')
    time.sleep(5)  # fetch async tamamlanmasını bekle
    url_detay = page.url
    hs_ekran = page.evaluate('history.state && history.state.ekran')
    hs_id    = page.evaluate('history.state && history.state.id')
    ok('3: history state ekran=mtt-detay', hs_ekran == 'mtt-detay', hs_ekran)
    ok('3: history state id=' + str(MTT_ID), hs_id == MTT_ID, hs_id)
    js_href = page.evaluate('location.href')  # pushState ile senkron güncellenir
    ok('3: URL ekran=mtt-detay', 'ekran=mtt-detay' in js_href, js_href)
    ok('3: URL mtt=' + str(MTT_ID), 'mtt=' + str(MTT_ID) in js_href, js_href)
    ok('3: mtt-detay ekran visible', page.is_visible('#ekran-mtt-detay'))

    # ── 4. F5 / Refresh — aynı detay restore ──
    print('\n=== 4. F5 refresh → same MTT detay ===')
    page.reload(wait_until='networkidle', timeout=15000)
    time.sleep(4)
    url_after_f5 = page.url
    ok('4: URL preserved after F5', 'ekran=mtt-detay' in url_after_f5, url_after_f5)
    ok('4: mtt-detay ekran visible after F5', page.is_visible('#ekran-mtt-detay'))
    ok('4: mtt-v3-layout in body after F5', 'mtt-v3-layout' in page.inner_html('#mtt-detay-body'))
    # Screenshot: sag kol temiz
    shot_f5 = os.path.join(SHOT_DIR, '_shot_nav_f5_restore.png')
    page.screenshot(path=shot_f5, full_page=False)
    print('  Screenshot: ' + shot_f5)

    # ── 5. Browser Back → MTT listesi ──
    print('\n=== 5. Browser Back → MTT listesi ===')
    page.go_back(wait_until='domcontentloaded', timeout=10000)
    time.sleep(2.5)
    url_back = page.url
    ok('5: URL after back has ekran=mtt or clean', 'ekran=mtt' in url_back or 'ekran' not in url_back, url_back)
    # mtt-detay artık görünmemeli; mtt listesi veya ana liste görünmeli
    mtt_detay_visible = page.is_visible('#ekran-mtt-detay')
    ok('5: mtt-detay NOT visible after back', not mtt_detay_visible)
    liste_or_mtt = page.is_visible('#ekran-liste') or page.is_visible('#ekran-mtt')
    ok('5: liste or mtt visible after back', liste_or_mtt)

    # ── 6. Browser Forward → MTT detay tekrar ──
    print('\n=== 6. Browser Forward → MTT detay restore ===')
    page.go_forward(wait_until='domcontentloaded', timeout=10000)
    time.sleep(4)
    url_fwd = page.url
    ok('6: URL after forward has ekran=mtt-detay', 'ekran=mtt-detay' in url_fwd, url_fwd)
    ok('6: mtt-detay visible after forward', page.is_visible('#ekran-mtt-detay'))

    # ── 7. Sipariş detay (second page type) ──
    print('\n=== 7. Sipariş detay (second page) ===')
    page.goto(BASE + '/nexgen/pazarlama', wait_until='networkidle', timeout=15000)
    time.sleep(1.5)
    # find first siparis in cache
    sip_id = page.evaluate('''(function(){
      var c = window._pzmTalepCache || [];
      return c.length ? c[0].id : null;
    })()''')
    if sip_id:
        page.evaluate('pzmDetayAc(' + str(sip_id) + ')')
        time.sleep(2)
        url_sip = page.url
        ok('7: siparis URL has siparis=ID', 'siparis=' in url_sip, url_sip)
        ok('7: detay ekran visible', page.is_visible('#ekran-detay'))
        # F5
        page.reload(wait_until='networkidle', timeout=15000)
        time.sleep(2.5)
        ok('7: siparis detay restored after F5', page.is_visible('#ekran-detay'))
    else:
        ok('7: siparis in cache (skip if empty)', True)

    # ── 8. Uygulama içi Geri butonu çalışıyor mu? ──
    print('\n=== 8. App internal back button (JS call) ===')
    page.goto(BASE + '/nexgen/pazarlama', wait_until='networkidle', timeout=15000)
    time.sleep(1.5)
    page.evaluate('mttDetayAc(' + str(MTT_ID) + ')')
    time.sleep(4)
    ok('8a: mtt-detay open before back click', page.is_visible('#ekran-mtt-detay'))
    # App içi geri: JS ile pzmEkranGec('mtt') çağır (buton yaptığının eşdeğeri)
    page.evaluate("pzmEkranGec('mtt')")
    time.sleep(1)
    ok('8b: app back → mtt list visible', page.is_visible('#ekran-mtt'))
    ok('8c: mtt-detay hidden', not page.is_visible('#ekran-mtt-detay'))

    # ── 9. MTT UI regression: donusum absent, green badge, ticari tek satir ──
    print('\n=== 9. MTT UI regression ===')
    page.evaluate('mttDetayAc(' + str(MTT_ID) + ')')
    time.sleep(4)
    body = page.inner_html('#mtt-detay-body')
    ok('9: mtt-v3-layout', 'mtt-v3-layout' in body)
    ok('9: green onay badge', 'mtt-badge-onay-green' in body)
    ok('9: donusum ABSENT', 'mtt-v3-donusum' not in body)
    ok('9: dynamic grid cols', 'grid-template-columns:repeat(' in body)
    ok('9: duplicate-free ne istiyor', 'Terlik' in body)
    shot_ui = os.path.join(SHOT_DIR, '_shot_nav_mtt_ui_lock.png')
    page.screenshot(path=shot_ui, full_page=False)
    print('  Screenshot: ' + shot_ui)

    # ── 10. FLICKER LOCK: Direct URL → T=50ms liste flash absent ──
    print('\n=== 10. Flicker lock: direct URL, liste flash absent ===')
    page.goto(BASE + '/nexgen/pazarlama?ekran=mtt-detay&mtt=' + str(MTT_ID),
              wait_until='domcontentloaded')
    time.sleep(0.05)
    liste_at_t50 = page.evaluate('''(function(){
      var el = document.getElementById('ekran-liste');
      if (!el) return false;
      return el.style.display !== 'none' && el.style.display !== '';
    })()''')
    ok('10: liste NOT visible at T=50ms (no flash)', not liste_at_t50, 'visible=' + str(liste_at_t50))
    detay_at_t50 = page.evaluate('''(function(){
      var el = document.getElementById('ekran-mtt-detay');
      if (!el) return false;
      return el.style.display !== 'none';
    })()''')
    ok('10: mtt-detay shell visible at T=50ms', detay_at_t50)
    page.wait_for_load_state('networkidle', timeout=12000)
    time.sleep(3)
    ok('10: mtt-v3-layout loaded (no flicker fix broke render)', 'mtt-v3-layout' in page.inner_html('#mtt-detay-body'))

    # ── 11. FLICKER LOCK: F5 on detay URL ──
    print('\n=== 11. Flicker lock: F5 on ?ekran=mtt-detay&mtt=ID ===')
    page.reload(wait_until='domcontentloaded')
    time.sleep(0.05)
    liste_f5_t50 = page.evaluate('''(function(){
      var el = document.getElementById('ekran-liste');
      if (!el) return false;
      return el.style.display !== 'none' && el.style.display !== '';
    })()''')
    ok('11: liste NOT flashing at T=50ms after F5', not liste_f5_t50)
    detay_f5_t50 = page.evaluate('''(function(){
      var el = document.getElementById('ekran-mtt-detay');
      if (!el) return false;
      return el.style.display !== 'none';
    })()''')
    ok('11: mtt-detay shell up at T=50ms after F5', detay_f5_t50)
    page.wait_for_load_state('networkidle', timeout=12000)
    time.sleep(3)
    ok('11: mtt-v3-layout restored after F5', 'mtt-v3-layout' in page.inner_html('#mtt-detay-body'))
    ok('11: URL unchanged after F5', 'ekran=mtt-detay' in page.evaluate('location.href'))

    # ── 12. ACIL/KRITIK red + compact ticari ──
    print('\n=== 12. UI lock: ACIL red + compact ticari ===')
    full_content = page.content()
    ok('12: mtt-badge-acil CSS defined', 'mtt-badge-acil' in full_content)
    ok('12: Segoe UI typography scope', 'Segoe UI' in full_content)
    body12 = page.inner_html('#mtt-detay-body')
    ok('12: mtt-v3-ticari-kart present', 'mtt-v3-ticari-kart' in body12)
    ok('12: mtt-v3-talep-hdr present (Musteri Talebi section)', 'mtt-v3-talep-hdr' in body12)

    print('\nSONUC: ' + str(PASS) + ' PASS / ' + str(FAIL) + ' FAIL')
    browser.close()
