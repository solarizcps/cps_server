# -*- coding: utf-8 -*-
"""
add_kod_hedef_aliases.py
------------------------
Frontend p.kod ve p.hedef alanlarini kullaniyor; bunlari da ekleyelim.
- kod   -> id (radio value, _aktifProses.kod, payload proses_kodu)
- hedef -> hedef_adet (kaynak='plan' iken gosterilen hedef rakami)
"""

import os
import shutil
import datetime
import sys
import ast

ROUTES_PATH = r"C:\cps_dev\modules\uretim_giris\routes.py"

OLD_BLOCK = """            d['proses'] = d['proses_adi']"""

NEW_BLOCK = """            d['proses'] = d['proses_adi']
            # Frontend p.kod ve p.hedef icin
            d['kod'] = str(d['id'])
            d['hedef'] = d['hedef_adet']"""


def main():
    if not os.path.exists(ROUTES_PATH):
        print(f"[HATA] {ROUTES_PATH} bulunamadi.")
        sys.exit(1)

    with open(ROUTES_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if NEW_BLOCK in src:
        print("[OK] Alias'lar zaten eklenmis.")
        return

    if OLD_BLOCK not in src:
        print("[HATA] Eslesen blok bulunamadi. Once add_proses_aliases.py calistirilmis mi?")
        sys.exit(2)

    if src.count(OLD_BLOCK) > 1:
        print("[HATA] Blok birden fazla.")
        sys.exit(3)

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = ROUTES_PATH + f'.bak_{ts}'
    shutil.copy2(ROUTES_PATH, backup)
    print(f"[OK] Yedek: {backup}")

    new_src = src.replace(OLD_BLOCK, NEW_BLOCK, 1)

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"[HATA] Syntax bozuldu: {e}")
        sys.exit(4)

    with open(ROUTES_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)

    print("[OK] kod ve hedef alias'lari eklendi.")
    print()
    print("YAPILACAK:")
    print("  1) CPS sunucusunu yeniden baslat (eger henuz baslatmadiysan)")
    print("  2) Browser'da Ctrl+F5 -> 110626 sorgula")
    print("  3) 6 proses listelenmeli, her birinin adi gorunmeli")


if __name__ == '__main__':
    main()
