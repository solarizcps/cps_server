# -*- coding: utf-8 -*-
"""
fix_double_prefix.py
--------------------
routes.py icindeki uretim_emir_prosesler fonksiyonunun decorator path'ini
'/uretim/emir/<emir_no>/prosesler' -> '/emir/<emir_no>/prosesler'
seklinde duzeltir (Blueprint zaten url_prefix='/uretim' ile tanimli, cift prefix oluyordu).

Calistirma:
    cd C:\\cps_dev
    py fix_double_prefix.py
"""

import os
import shutil
import datetime
import sys

ROUTES_PATH = r"C:\cps_dev\modules\uretim_giris\routes.py"
OLD = "@uretim_giris_bp.route('/uretim/emir/<emir_no>/prosesler', methods=['GET'])"
NEW = "@uretim_giris_bp.route('/emir/<emir_no>/prosesler', methods=['GET'])"


def main():
    if not os.path.exists(ROUTES_PATH):
        print(f"[HATA] {ROUTES_PATH} bulunamadi.")
        sys.exit(1)

    with open(ROUTES_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    count = src.count(OLD)
    if count == 0:
        print("[BILGI] Eslesen decorator yok. Belki zaten duzeltilmis.")
        # Yeni hali var mi diye bak
        if NEW in src:
            print("[OK] Yeni hali zaten dosyada mevcut. Yapacak bir sey yok.")
            sys.exit(0)
        print("[HATA] Ne eski ne yeni decorator bulundu. Manuel inceleme gerek.")
        sys.exit(2)
    if count > 1:
        print(f"[HATA] Eslesen decorator {count} kez var, belirsiz. Manuel duzelt.")
        sys.exit(3)

    # Yedek
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = ROUTES_PATH + f'.bak_{ts}'
    shutil.copy2(ROUTES_PATH, backup)
    print(f"[OK] Yedek: {backup}")

    new_src = src.replace(OLD, NEW, 1)

    # Syntax dogrulama
    import ast
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"[HATA] Syntax bozuldu, yazilmadi: {e}")
        sys.exit(4)

    with open(ROUTES_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)

    print("[OK] Decorator path '/uretim/emir/<emir_no>/prosesler' -> '/emir/<emir_no>/prosesler'")
    print()
    print("YAPILACAK:")
    print("  1) CPS sunucusunu yeniden baslat")
    print("  2) Browser'da: http://127.0.0.1:5057/uretim/emir/110626/prosesler")
    print("     -> JSON donmeli, prosesler listesinde 6 eleman")


if __name__ == '__main__':
    main()
