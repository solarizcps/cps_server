# -*- coding: utf-8 -*-
"""
fix_sidebar_scroll.py
---------------------
Sidebar tasiyor ama scroll calismiyor.
Cozum: overflow-y:auto + max height set
"""
import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
BASE_HTML = os.path.join(CPS_ROOT, "templates", "base.html")

MARKER = "/* sidebar-scroll-fix */"

# </body> oncesi yeni style ekle
EK_STYLE = '''<!-- sidebar-scroll-fix -->
<style>
  /* sidebar-scroll-fix */
  #sidebar {
    height: calc(100vh - 60px) !important;
    overflow-y: auto !important;
    overflow-x: hidden;
  }
  /* Scrollbar incecik */
  #sidebar::-webkit-scrollbar {
    width: 6px;
  }
  #sidebar::-webkit-scrollbar-track {
    background: transparent;
  }
  #sidebar::-webkit-scrollbar-thumb {
    background: rgba(0,0,0,0.15);
    border-radius: 3px;
  }
  #sidebar::-webkit-scrollbar-thumb:hover {
    background: rgba(0,0,0,0.25);
  }
  /* sb-tog butonu (alt toggle) sticky kalsin scroll'da */
  #sidebar .sb-tog {
    position: sticky !important;
    bottom: 0;
    background: var(--bg, #fafafa);
    z-index: 5;
  }
</style>
'''


def main():
    if not os.path.exists(BASE_HTML):
        print(f"[HATA] {BASE_HTML} yok.")
        return 1
    with open(BASE_HTML, 'r', encoding='utf-8') as f:
        src = f.read()
    if MARKER in src:
        print("[BILGI] Scroll fix zaten ekli.")
        return 0
    if '</body>' not in src:
        print("[HATA] </body> yok.")
        return 1

    new_src = src.replace('</body>', EK_STYLE + '\n</body>', 1)

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = BASE_HTML + f'.bak_{ts}'
    shutil.copy2(BASE_HTML, bp)
    print(f"[OK] Yedek: {bp}")
    with open(BASE_HTML, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("[OK] Scroll fix eklendi.")
    print()
    print("YAPILACAK: Ctrl+F5")
    print()
    print("Beklenen:")
    print("  - Sidebar yukari/asagi scroll edilebilir")
    print("  - Scrollbar incecik, sag kenarda")
    print("  - sb-tog buton alt'ta sabit kalir")
    return 0


if __name__ == '__main__':
    sys.exit(main())
