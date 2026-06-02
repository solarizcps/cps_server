# -*- coding: utf-8 -*-
"""
fix_plan_musteri_tek_satir.py
-----------------------------
PLAN ekraninda musteri alani icin tek satir patch.

Mantik: get_emir_ozet zaten cari_adi donduruyor (debug ile dogrulandi).
sonuc.append({...}) dict'ine bir alan eklemek yeterli.

DOKUNMAZ:
  - Mevcut dict alanlari
  - Diger fonksiyonlar
  - get_emir_ozet helper'i
  - DB / endpoint / yeni SQL yok
"""
import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
HEDEF_ROUTES = os.path.join(CPS_ROOT, "modules", "hedef", "routes.py")

MARKER = "# === PLAN_MUSTERI_TEK_SATIR ==="

ESKI = """        sonuc.append({
            'emir_no': str(emir_no_int),
            'model': model,
            'siparisler': siparisler_str,
            'hedef': hedef,
            'korgun_yapilan': korgun_yapilan,
            'cps_yapilan': cps_onayli,
            'cps_bekleyen': cps_bekleyen,
            'yapilan': toplam_yapilan,
            'kalan': kalan,
            'yuzde': yuzde,
        })"""

YENI = """        # === PLAN_MUSTERI_TEK_SATIR ===
        sonuc.append({
            'emir_no': str(emir_no_int),
            'model': model,
            'musteri': (ozet.get('cari_adi') if ok else None),
            'siparisler': siparisler_str,
            'hedef': hedef,
            'korgun_yapilan': korgun_yapilan,
            'cps_yapilan': cps_onayli,
            'cps_bekleyen': cps_bekleyen,
            'yapilan': toplam_yapilan,
            'kalan': kalan,
            'yuzde': yuzde,
        })"""


def main():
    if not os.path.exists(HEDEF_ROUTES):
        print(f"[HATA] {HEDEF_ROUTES} yok.")
        return 1

    with open(HEDEF_ROUTES, 'r', encoding='utf-8') as f:
        src = f.read()

    if MARKER in src:
        print("[BILGI] Zaten ekli.")
        return 0

    if ESKI not in src:
        print("[HATA] Eski blok bulunamadi.")
        return 1
    if src.count(ESKI) > 1:
        print("[HATA] Cogul blok.")
        return 1

    new_src = src.replace(ESKI, YENI, 1)

    # Syntax check
    import ast
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"[HATA] parse: {e}")
        return 1

    # Yedek
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = HEDEF_ROUTES + f'.bak_{ts}'
    shutil.copy2(HEDEF_ROUTES, bp)
    print(f"[OK] Yedek: {bp}")

    with open(HEDEF_ROUTES, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("[OK] musteri alani eklendi.")
    print()
    print("YAPILACAK:")
    print("  Flask debug mode reloader otomatik basa donderir.")
    print("  Pencerede '* Restarting with stat' satirini gorunce")
    print("  tarayicida Ctrl+F5 yap.")
    print()
    print("TEST:")
    print("  fetch('/hedef/plan',{credentials:'include'})")
    print("    .then(r=>r.json())")
    print("    .then(d=>console.log(d.emirler[0].musteri))")
    print("  Beklenen: 'Lc Waikiki'")
    print()
    print("ROLLBACK:")
    print(f'  copy "{bp}" "{HEDEF_ROUTES}"')
    return 0


if __name__ == '__main__':
    sys.exit(main())
