# -*- coding: utf-8 -*-
"""
fix_sidebar_toggle_delegation.py
--------------------------------
Onceki script bloku event listener baglamamis (onclick null).
Cozum: document-level click delegation ekle, body sonuna inject et.
Bu yontem DOM hazir olsun olmasin calisir.
"""
import os
import shutil
import datetime
import sys
import re

CPS_ROOT = r"C:\cps_dev"
BASE_HTML = os.path.join(CPS_ROOT, "templates", "base.html")

MARKER = "<!-- SIDEBAR_TOGGLE_DELEGATION -->"

YENI_SCRIPT = '''<!-- SIDEBAR_TOGGLE_DELEGATION -->
<script>
(function(){
  // Document-level delegation - DOM hazir olsa olmasa da calisir
  document.addEventListener('click', function(ev){
    var h = ev.target.closest && ev.target.closest('#sidebar .sn-sec.sn-toggle');
    if (!h) return;
    var grup = h.getAttribute('data-grup');
    if (!grup) return;
    var body = document.querySelector('#sidebar .sn-grup[data-grup="' + grup + '"]');
    if (!body) return;
    var simdiKapali = body.classList.toggle('kapali');
    h.classList.toggle('acik', !simdiKapali);
    var ar = h.querySelector('.sn-arrow');
    if (ar) ar.textContent = simdiKapali ? '\\u25BA' : '\\u25BC';
    ev.preventDefault();
    ev.stopPropagation();
  }, false);
  console.log('[CPS LOCAL] Sidebar toggle delegation aktif.');
})();
</script>
'''


def main():
    if not os.path.exists(BASE_HTML):
        print(f"[HATA] {BASE_HTML} yok.")
        return 1
    with open(BASE_HTML, 'r', encoding='utf-8') as f:
        src = f.read()
    if MARKER in src:
        print("[BILGI] Delegation zaten ekli.")
        return 0

    # </body>'den hemen once ekle
    if '</body>' not in src:
        print("[HATA] </body> bulunamadi.")
        return 1
    if src.count('</body>') > 1:
        print("[UYARI] Birden fazla </body> var, ilki kullanilacak.")

    new_src = src.replace('</body>', YENI_SCRIPT + '\n</body>', 1)

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = BASE_HTML + f'.bak_{ts}'
    shutil.copy2(BASE_HTML, bp)
    print(f"[OK] Yedek: {bp}")
    with open(BASE_HTML, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("[OK] Document-level toggle delegation eklendi.")
    print()
    print("YAPILACAK: Ctrl+F5")
    print()
    print("Console'da gormen gereken:")
    print("  [CPS LOCAL] Sidebar toggle delegation aktif.")
    print()
    print("Test:")
    print("  Herhangi bir grup basligina tikla -> aciliyor mu kapaniyor mu?")
    return 0


if __name__ == '__main__':
    sys.exit(main())
