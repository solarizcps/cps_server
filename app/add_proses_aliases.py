# -*- coding: utf-8 -*-
"""
add_proses_aliases.py
---------------------
routes.py icindeki uretim_emir_prosesler fonksiyonunda
d['sira'] = d['siralama'] satirindan sonra ek alias'lar ekler.
Frontend'in hangi alan adini bekledigini bilmedigimiz icin yaygin olanlarini gondeririz.
"""

import os
import shutil
import datetime
import sys
import ast

ROUTES_PATH = r"C:\cps_dev\modules\uretim_giris\routes.py"

OLD_BLOCK = """            d['proses_id'] = d['id']
            d['sira'] = d['siralama']"""

NEW_BLOCK = """            d['proses_id'] = d['id']
            d['sira'] = d['siralama']
            # Frontend uyumu icin yaygin alias'lar
            d['adi'] = d['proses_adi']
            d['ad'] = d['proses_adi']
            d['name'] = d['proses_adi']
            d['label'] = d['proses_adi']
            d['proses'] = d['proses_adi']"""


def main():
    if not os.path.exists(ROUTES_PATH):
        print(f"[HATA] {ROUTES_PATH} bulunamadi.")
        sys.exit(1)

    with open(ROUTES_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if NEW_BLOCK in src:
        print("[OK] Alias'lar zaten eklenmis. Yapacak bir sey yok.")
        return

    if OLD_BLOCK not in src:
        print("[HATA] Eslesen blok bulunamadi.")
        sys.exit(2)

    if src.count(OLD_BLOCK) > 1:
        print("[HATA] Blok birden fazla kez var, belirsiz.")
        sys.exit(3)

    # Yedek
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

    print("[OK] Alias'lar eklendi: adi, ad, name, label, proses")
    print()
    print("YAPILACAK:")
    print("  1) CPS sunucusunu yeniden baslat")
    print("  2) Browser'da Ctrl+F5 -> 110626 sorgula")
    print("  3) Proses isimleri gorunmuyorsa F12 Network'ten JSON'i kontrol et")


if __name__ == '__main__':
    main()
