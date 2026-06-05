# -*- coding: utf-8 -*-
"""
fix_sidebar_bolme_cizgi.py
--------------------------
Collapsed (daraltilmis) sidebar'da grup basliklari icin
yarim cizgi/arka plan kaldirildi - tamamen gizli olsun.
"""
import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
BASE_HTML = os.path.join(CPS_ROOT, "templates", "base.html")

MARKER = "/* sn-toggle gizle collapsed */"

ESKI = """      #sidebar:not(.expanded) .sn-sec.sn-toggle {
        padding: 4px;
        margin: 8px 8px 2px 8px;
        justify-content: center;
        background: rgba(0,0,0,0.03);
      }"""

YENI = """      /* sn-toggle gizle collapsed */
      #sidebar:not(.expanded) .sn-sec.sn-toggle {
        display: none;
      }"""


def main():
    if not os.path.exists(BASE_HTML):
        print(f"[HATA] {BASE_HTML} yok.")
        return 1
    with open(BASE_HTML, 'r', encoding='utf-8') as f:
        src = f.read()
    if MARKER in src:
        print("[BILGI] Fix zaten ekli.")
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
    print("[OK] Collapsed sidebar'da grup basligi cizgileri kaldirildi.")
    print()
    print("YAPILACAK: Ctrl+F5")
    return 0


if __name__ == '__main__':
    sys.exit(main())
