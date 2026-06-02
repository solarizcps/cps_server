# -*- coding: utf-8 -*-
"""
fix_sidebar_arali_genislet.py
-----------------------------
Sidebar item'lar arasi dikey bosluk artir.
- .si margin: 2px 6px -> 4px 6px
- .si min-height: 36px -> 38px
- .si padding biraz artir
"""
import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
BASE_HTML = os.path.join(CPS_ROOT, "templates", "base.html")

MARKER = "/* sidebar-aralikli */"

ESKI = """      /* ============ SIDEBAR ITEM (link) ============ */
      #sidebar .si {
        display: flex !important;
        align-items: center;
        gap: 10px;
        padding: 4px 8px !important;
        margin: 2px 6px;
        min-height: 36px !important;
        font-size: 13px !important;
        text-decoration: none;
        color: var(--text2);
        border-radius: 8px;
        transition: background 0.12s, color 0.12s;
        position: relative;
      }"""

YENI = """      /* sidebar-aralikli */
      /* ============ SIDEBAR ITEM (link) ============ */
      #sidebar .si {
        display: flex !important;
        align-items: center;
        gap: 10px;
        padding: 6px 10px !important;
        margin: 4px 6px;
        min-height: 40px !important;
        font-size: 13px !important;
        text-decoration: none;
        color: var(--text2);
        border-radius: 8px;
        transition: background 0.12s, color 0.12s;
        position: relative;
      }"""


def main():
    if not os.path.exists(BASE_HTML):
        print(f"[HATA] {BASE_HTML} yok.")
        return 1
    with open(BASE_HTML, 'r', encoding='utf-8') as f:
        src = f.read()
    if MARKER in src:
        print("[BILGI] Aralikli zaten ekli.")
        return 0
    if ESKI not in src:
        print("[HATA] Eski blok bulunamadi.")
        return 1
    if src.count(ESKI) > 1:
        print("[HATA] Cogul.")
        return 1

    new_src = src.replace(ESKI, YENI, 1)
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = BASE_HTML + f'.bak_{ts}'
    shutil.copy2(BASE_HTML, bp)
    print(f"[OK] Yedek: {bp}")
    with open(BASE_HTML, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("[OK] Sidebar item arali genisletildi.")
    print()
    print("YAPILACAK: Ctrl+F5")
    return 0


if __name__ == '__main__':
    sys.exit(main())
