# -*- coding: utf-8 -*-
"""
fix_sidebar_hover_aktif_gibi.py
-------------------------------
Sidebar'daki .si:hover stilini, .si.active ile AYNI yapar.
Sadece CSS, mevcut yapi bozulmaz.
"""
import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
BASE_HTML = os.path.join(CPS_ROOT, "templates", "base.html")

MARKER = "/* hover-aktif-gibi */"

# Mevcut hover blogu (Lucide patch'inden)
ESKI = """      /* Hover */
      #sidebar .si:hover {
        background: rgba(249, 115, 22, 0.06);
      }
      #sidebar .si:hover .si-icon {
        background: rgba(249, 115, 22, 0.10);
        color: var(--sol, #f97316);
      }"""

# Yeni: aktif gibi gozuksun (BG biraz daha yumusak ama yapi ayni)
YENI = """      /* hover-aktif-gibi */
      /* Hover - aktif item ile ayni gorunum (kutulu ikon + turuncu) */
      #sidebar .si:hover {
        background: rgba(249, 115, 22, 0.10);
        color: var(--sol-dark, #c2410c);
      }
      #sidebar .si:hover .si-icon {
        background: var(--sol, #f97316);
        color: #fff;
      }
      #sidebar .si:hover .sl {
        font-weight: 600;
      }"""


def main():
    if not os.path.exists(BASE_HTML):
        print(f"[HATA] {BASE_HTML} yok.")
        return 1

    with open(BASE_HTML, 'r', encoding='utf-8') as f:
        src = f.read()

    if MARKER in src:
        print("[BILGI] Hover-aktif-gibi zaten ekli.")
        return 0

    if ESKI not in src:
        print("[HATA] Eski hover bloku bulunamadi.")
        print("       Onceki Lucide patch'i uygulanmamis olabilir.")
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
    print("[OK] Hover gorunumu aktif item gibi yapildi.")
    print()
    print("YAPILACAK: Ctrl+F5")
    print()
    print("Beklenen:")
    print("  - Bos satira hover -> turuncu pill + ikon turuncu kutu + bold yazi")
    print("  - Aktif item zaten ayni gorunumde (turuncu pill)")
    print("  - Aktif olan ile hover olan ayni gozukur (sen istedigin gibi)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
