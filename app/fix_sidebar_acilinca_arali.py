# -*- coding: utf-8 -*-
"""
fix_sidebar_acilinca_arali.py
-----------------------------
Teshis (base.html'den):
  Iki cakisan #sidebar .si CSS blogu var.
    Satir ~303: padding 4px 8px, margin 2px 6px, min-h 36px (Lucide patch)
    Satir ~470: padding 6px 10px, min-h 28px (compact-v2 kalintisi - OVERRIDE)
  Ikincisi birinciyi eziyor -> item'lar 28px yuksekligi -> ust uste izlenim.
  Ayrica .sn-sub iki yerde tanimli.

Fix:
  1) compact-v2 kalintilari (cakisan ikinci .si + .sn-sub + :not(.expanded))
     KALDIR
  2) Ana .si blogunu rahatlat (margin 4px, min-h 40px, padding 7px 10px)
  3) Ana .sn-sub'a margin-top 10px

DOKUNULMAZ:
  - Backend
  - Sayfa icerikleri
  - Sidebar HTML/menu yapisi/linkler
  - Hover/aktif stilleri
"""
import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
BASE_HTML = os.path.join(CPS_ROOT, "templates", "base.html")
MARKER = "/* SB_ACILINCA_ARALI_V1 */"


# ---------------------------------------------------------
# Ana .si blogu (rahatlat)
# ---------------------------------------------------------
ESKI_ANA_SI = """      /* ============ SIDEBAR ITEM (link) ============ */
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

YENI_ANA_SI = """      /* SB_ACILINCA_ARALI_V1 */
      /* ============ SIDEBAR ITEM (link) ============ */
      #sidebar .si {
        display: flex !important;
        align-items: center;
        gap: 10px;
        padding: 7px 10px !important;
        margin: 4px 6px;
        min-height: 40px !important;
        font-size: 13px !important;
        text-decoration: none;
        color: var(--text2);
        border-radius: 8px;
        transition: background 0.12s, color 0.12s;
        position: relative;
      }"""


# Ana .sn-sub (rahatlat)
ESKI_SUB_1 = """      #sidebar .sn-sub {
        padding: 4px 14px;
        margin-top: 4px;
        font-size: 9px;
        font-weight: 600;
        letter-spacing: 0.5px;
        color: var(--text3);
        text-transform: uppercase;
        opacity: 0.7;
      }"""

YENI_SUB_1 = """      #sidebar .sn-sub {
        padding: 6px 14px 4px 14px;
        margin-top: 10px;
        margin-bottom: 2px;
        font-size: 9px;
        font-weight: 600;
        letter-spacing: 0.5px;
        color: var(--text3);
        text-transform: uppercase;
        opacity: 0.7;
      }"""


# ---------------------------------------------------------
# Cakisan eski compact-v2 kalintilari (KALDIR)
# ---------------------------------------------------------
ESKI_CAKISAN_SI = """      #sidebar .si {
        padding: 6px 10px !important;
        min-height: 28px !important;
        font-size: 12.5px !important;
      }
      #sidebar .si svg {
        width: 16px;
        height: 16px;
      }"""

ESKI_CAKISAN_SUB = """      #sidebar .sn-sub {
        padding: 4px 12px;
        margin-top: 4px;
        font-size: 9px;
        font-weight: 600;
        letter-spacing: 0.5px;
        color: var(--text3);
        text-transform: uppercase;
        opacity: 0.7;
      }"""

ESKI_CAKISAN_NOTEXP = """      #sidebar:not(.expanded) .sn-sub {
        display: none;
      }
      #sidebar:not(.expanded) .sn-sec.sn-toggle {
        padding: 2px;
        margin: 4px 8px;
        height: 1px;
        background: var(--border);
        border-radius: 0;
      }"""


def _bul_temizle(src, blok, ad):
    if blok not in src:
        print(f"  [BILGI] {ad}: zaten yok / once temizlenmis")
        return src
    if src.count(blok) > 1:
        print(f"  [UYARI] {ad}: cogul ({src.count(blok)}) - ilk eslesme silinecek")
    return src.replace(blok, "", 1)


def main():
    print("=" * 64)
    print("Sidebar acilinca aralik fix")
    print("=" * 64)

    if not os.path.exists(BASE_HTML):
        print(f"  [HATA] {BASE_HTML} yok.")
        return 1

    with open(BASE_HTML, 'r', encoding='utf-8') as f:
        src = f.read()

    if MARKER in src:
        print("  [BILGI] Patch zaten ekli (marker var).")
        return 0

    # Yedek
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = BASE_HTML + f'.bak_{ts}'
    shutil.copy2(BASE_HTML, bp)
    print(f"  [OK] Yedek: {bp}")

    new_src = src

    # 1) Cakisan compact-v2 kalintilarini temizle
    new_src = _bul_temizle(new_src, ESKI_CAKISAN_SI, "Cakisan .si (compact-v2)")
    new_src = _bul_temizle(new_src, ESKI_CAKISAN_SUB, "Cakisan ikinci .sn-sub")
    new_src = _bul_temizle(new_src, ESKI_CAKISAN_NOTEXP, "Cakisan :not(.expanded) override")

    # 2) Ana .si rahatlat
    if ESKI_ANA_SI in new_src and new_src.count(ESKI_ANA_SI) == 1:
        new_src = new_src.replace(ESKI_ANA_SI, YENI_ANA_SI, 1)
        print("  [OK] Ana .si rahatlatildi (margin 4px, min-h 40px, padding 7/10)")
    else:
        print("  [HATA] Ana .si bloku bulunamadi/cogul - patch yarim kaldi")
        return 1

    # 3) Ana .sn-sub rahatlat
    if ESKI_SUB_1 in new_src and new_src.count(ESKI_SUB_1) == 1:
        new_src = new_src.replace(ESKI_SUB_1, YENI_SUB_1, 1)
        print("  [OK] Ana .sn-sub rahatlatildi (margin-top 10px)")
    else:
        print("  [BILGI] Ana .sn-sub bulunamadi (zaten degisik olabilir)")

    with open(BASE_HTML, 'w', encoding='utf-8') as f:
        f.write(new_src)

    print()
    print("=" * 64)
    print("TAMAM")
    print("=" * 64)
    print()
    print("DEGISEN: templates/base.html")
    print(f"YEDEK:   {bp}")
    print()
    print("YAPILACAK:")
    print("  Browser Ctrl+F5 (sunucu restart gerekmez)")
    print()
    print("BEKLENEN:")
    print("  - Item'lar arasi nefes payi var (40px min-height)")
    print("  - ITHALAT sub-basligi alti rahat")
    print("  - Cakisan compact-v2 CSS kalintilari temizlendi")
    print("  - Hover/aktif gorunumu DEGISMEDI")
    print("  - Menu yapisi/linkler DEGISMEDI")
    print()
    print("ROLLBACK:")
    print(f'  copy "{bp}" "{BASE_HTML}"')
    return 0


if __name__ == '__main__':
    sys.exit(main())
