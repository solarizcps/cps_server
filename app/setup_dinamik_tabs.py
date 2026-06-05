# -*- coding: utf-8 -*-
"""
setup_dinamik_tabs.py
---------------------
Ust nav-tabs'i dinamik tab sistemi haline getir:
  - Tab key = pathname + search (hash atlanir)
  - Aktif sayfa otomatik tab olur (ilk acilis bos kalmaz)
  - Max 8 tab, yeni en saga, eski en soldan duser
  - Her tabin saginda X (kapatma)
  - Aktif tab kapanirsa SOL tab'a gecis (yoksa /)

Patch kapsam:
  - Sadece templates/base.html
  - 3 inline degisiklik (head script, nav-tabs replace, body sonu script)
  - Backend dokunulmaz
  - Sol sidebar dokunulmaz
  - Header/sayfa icerigi dokunulmaz

Idempotent (marker kontrolu).
"""

import os
import shutil
import datetime
import sys
import re

CPS_ROOT = r"C:\cps_dev"
BASE_HTML = os.path.join(CPS_ROOT, "templates", "base.html")

MARKER = "<!-- DYN_TABS_V1 -->"


# ====================================================================
# 1) HEAD ICINE - erken state sync (flicker onleme)
# ====================================================================
HEAD_SCRIPT = '''<!-- DYN_TABS_V1 head -->
<script>
(function(){
  // localStorage'dan tab listesini al, aktif sayfayi otomatik ekle
  var KEY = 'cps_tabs_v1';
  var MAX = 8;
  function _curKey(){
    return window.location.pathname + window.location.search;
  }
  function _load(){
    try { return JSON.parse(localStorage.getItem(KEY) || '[]') || []; }
    catch(e){ return []; }
  }
  function _save(list){
    try { localStorage.setItem(KEY, JSON.stringify(list)); } catch(e){}
  }
  var list = _load();
  if (!Array.isArray(list)) list = [];
  // Bozuk kayitlari temizle
  list = list.filter(function(t){ return t && typeof t.key === 'string'; });

  var cur = _curKey();
  var idx = -1;
  for (var i=0;i<list.length;i++){ if(list[i].key === cur){ idx = i; break; } }
  if (idx === -1) {
    // Title'i sayfa yuklendikten sonra dolduracagiz, simdilik path
    list.push({key: cur, title: ''});
    while (list.length > MAX) list.shift();
    _save(list);
  }
  // Window'a expose et
  window._cpsTabsKey = KEY;
  window._cpsTabsMax = MAX;
})();
</script>
'''


# ====================================================================
# 2) NAV-TABS REPLACE - eski statik nav-tabs blok yerine bos div
# ====================================================================
# Eski blok pattern (Jinja ile dolduruluyor)
ESKI_NAV_PATTERN = re.compile(
    r'    <div class="nav-tabs">.*?</div>\s*\n',
    re.DOTALL
)

YENI_NAV = '''    <div id="dynNavTabs" class="nav-tabs"></div>
'''


# ====================================================================
# 3) BODY SONU SCRIPT - render + click handler
# ====================================================================
BODY_SCRIPT = '''<!-- DYN_TABS_V1 body -->
<style>
  /* Dinamik tab gorunumu */
  #dynNavTabs.nav-tabs {
    overflow-x: auto;
    overflow-y: hidden;
    scrollbar-width: none;
  }
  #dynNavTabs.nav-tabs::-webkit-scrollbar { display: none; }
  #dynNavTabs .nav-tab {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    white-space: nowrap;
  }
  #dynNavTabs .tab-x {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    font-size: 13px;
    line-height: 1;
    color: rgba(0,0,0,0.4);
    cursor: pointer;
    margin-left: 4px;
    transition: background 0.12s, color 0.12s;
    user-select: none;
  }
  #dynNavTabs .tab-x:hover {
    background: rgba(220,38,38,0.18);
    color: #dc2626;
  }
  #dynNavTabs .nav-tab.active .tab-x {
    color: rgba(0,0,0,0.55);
  }
  #dynNavTabs .nav-tab.active .tab-x:hover {
    color: #dc2626;
  }
  #dynNavTabs:empty::before {
    content: '';
  }
</style>
<script>
(function(){
  var KEY = window._cpsTabsKey || 'cps_tabs_v1';
  var MAX = window._cpsTabsMax || 8;

  function _load(){
    try { return JSON.parse(localStorage.getItem(KEY) || '[]') || []; }
    catch(e){ return []; }
  }
  function _save(list){
    try { localStorage.setItem(KEY, JSON.stringify(list)); } catch(e){}
  }
  function _curKey(){
    return window.location.pathname + window.location.search;
  }
  function _esc(s){
    if (s == null) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // Title kaynagi: 1) sol sidebar'daki link title, 2) <span class="sl">,
  //                3) document.title, 4) pathname son segment
  function _findTitle(key){
    var path = key.split('?')[0];
    // Sidebar'daki <a href> ile eslesme ara
    var sidebar = document.getElementById('sidebar');
    if (sidebar) {
      var links = sidebar.querySelectorAll('a[href]');
      for (var i=0; i<links.length; i++){
        var href = links[i].getAttribute('href') || '';
        var hrefBase = href.split('?')[0];
        if (href === key || hrefBase === path) {
          // title attribute oncelikli
          var t = links[i].getAttribute('title');
          if (t) return t;
          var sl = links[i].querySelector('.sl');
          if (sl && sl.textContent) return sl.textContent.trim();
        }
      }
    }
    // document title
    if (document.title) {
      var cleaned = document.title.replace(/\\s*[·•|—-]\\s*Solariz.*$/i, '').trim();
      if (cleaned) return cleaned;
    }
    // pathname son segment
    var seg = path.split('/').filter(Boolean).pop() || 'Ozet';
    return seg.charAt(0).toUpperCase() + seg.slice(1);
  }

  function _render(){
    var box = document.getElementById('dynNavTabs');
    if (!box) return;
    var list = _load();
    var cur = _curKey();
    var html = '';
    for (var i=0; i<list.length; i++){
      var t = list[i];
      if (!t || !t.key) continue;
      var aktif = (t.key === cur);
      var title = t.title || _findTitle(t.key);
      // Aktif tab'in title'ini dinamik guncelle (ilk yuklemede bos olabilirdi)
      if (aktif && (!t.title || t.title !== title)) {
        list[i].title = title;
      }
      html += '<a href="' + _esc(t.key) + '" class="nav-tab' +
              (aktif ? ' active' : '') + '" data-tabkey="' + _esc(t.key) + '">';
      html += '<span class="tab-label">' + _esc(title) + '</span>';
      html += '<span class="tab-x" data-tabkey="' + _esc(t.key) +
              '" title="Kapat">×</span>';
      html += '</a>';
    }
    box.innerHTML = html;
    _save(list);
  }

  // Aktif sayfa title'ini state'e yaz
  function _ensureCurTitle(){
    var list = _load();
    var cur = _curKey();
    var changed = false;
    for (var i=0; i<list.length; i++){
      if (list[i].key === cur && !list[i].title){
        list[i].title = _findTitle(cur);
        changed = true;
      }
    }
    if (changed) _save(list);
  }

  // X handler (event delegation)
  document.addEventListener('click', function(ev){
    var x = ev.target.closest && ev.target.closest('#dynNavTabs .tab-x');
    if (!x) return;
    ev.preventDefault();
    ev.stopPropagation();
    var k = x.getAttribute('data-tabkey');
    if (!k) return;
    var list = _load();
    var idx = -1;
    for (var i=0; i<list.length; i++){
      if (list[i].key === k) { idx = i; break; }
    }
    if (idx === -1) return;
    var aktif = (k === _curKey());
    list.splice(idx, 1);
    _save(list);
    if (aktif){
      // Soldaki tab'a gec, yoksa /
      var hedef = '/';
      if (idx > 0 && list[idx-1]) hedef = list[idx-1].key;
      else if (list.length > 0) hedef = list[0].key;
      window.location.href = hedef;
    } else {
      _render();
    }
  }, false);

  // Ilk render
  _ensureCurTitle();
  _render();

  // Disardan cagri
  window._cpsTabsRender = _render;

  console.log('[CPS LOCAL] Dynamic tabs aktif');
})();
</script>
'''


def main():
    print("=" * 64)
    print("Dinamik Nav-Tabs Sistemi")
    print("=" * 64)

    if not os.path.exists(BASE_HTML):
        print(f"  [HATA] {BASE_HTML} yok.")
        return 1

    with open(BASE_HTML, 'r', encoding='utf-8') as f:
        src = f.read()

    if MARKER in src:
        print("  [BILGI] Dinamik tabs zaten ekli (marker var).")
        return 0

    # 1) Eski nav-tabs bloku bul ve replace et
    m = ESKI_NAV_PATTERN.search(src)
    if not m:
        print("  [HATA] Eski nav-tabs bloku bulunamadi.")
        print("  Pattern: <div class=\"nav-tabs\">...</div>")
        return 1

    # 2) </head> bul
    head_pos = src.find('</head>')
    if head_pos == -1:
        print("  [HATA] </head> bulunamadi.")
        return 1

    # 3) </body> bul
    body_pos = src.rfind('</body>')
    if body_pos == -1:
        print("  [HATA] </body> bulunamadi.")
        return 1

    # Yedek
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = BASE_HTML + f'.bak_{ts}'
    shutil.copy2(BASE_HTML, bp)
    print(f"  [OK] Yedek: {bp}")

    # Build new content
    new_src = src

    # a) head script ekle (</head>'den hemen once)
    new_src = new_src.replace('</head>', HEAD_SCRIPT + '</head>', 1)

    # b) nav-tabs replace
    new_src = ESKI_NAV_PATTERN.sub(YENI_NAV, new_src, count=1)

    # c) body script ekle (</body>'den hemen once)
    new_src = new_src.replace('</body>', BODY_SCRIPT + '</body>', 1)

    with open(BASE_HTML, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] base.html guncellendi.")
    print()
    print("YAPILACAK:")
    print("  1) Sunucu restart GEREKMEZ. Browser Ctrl+F5.")
    print()
    print("TEST ADIMLARI:")
    print("  1. http://localhost:5057/ ac")
    print("     -> Ust'te 1 tab: 'Ozet' (X'li)")
    print()
    print("  2. Sol sidebar -> 'Hedef Paneli' tikla")
    print("     -> Ust'te 2 tab: [Ozet][Hedef Paneli aktif]")
    print()
    print("  3. Sol sidebar -> 'Sablon / Proses' tikla")
    print("     -> Ust'te 3 tab: [Ozet][Hedef][Sablon aktif]")
    print()
    print("  4. Aktif tab'in X'ine tikla")
    print("     -> Sablon silinir, Hedef'e (sol tab) gecilir otomatik")
    print()
    print("  5. Aktif olmayan tab'in X'ine tikla")
    print("     -> O tab silinir, mevcut sayfada kalirsin")
    print()
    print("  6. 9 farkli sayfa ac")
    print("     -> Hep 8 tab gorur, en eski (en sol) duser")
    print()
    print("  7. Tum X'leri kapat")
    print("     -> Son X kapaninca / (Ozet)'e gidersin")
    print()
    print("  8. Console'da: localStorage.getItem('cps_tabs_v1')")
    print("     -> JSON formatinda kayitli tab listesi")
    print()
    print("ROLLBACK (acil geri donus):")
    print(f"  copy \"{bp}\" \"{BASE_HTML}\"")
    print()
    print("Console kontrol log:")
    print("  [CPS LOCAL] Dynamic tabs aktif")
    return 0


if __name__ == '__main__':
    sys.exit(main())
