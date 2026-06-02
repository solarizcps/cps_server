# -*- coding: utf-8 -*-
"""
fix_geri_al_kolon.py
--------------------
emir_alt_proses tablosunda 'guncelleme' kolonu yok.
geri-al endpoint'indeki UPDATE sadece aktif=0 yapsin.
"""

import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
HEDEF_ROUTES = os.path.join(CPS_ROOT, "modules", "hedef", "routes.py")

MARKER = "# === geri-al kolon fix ==="

ESKI = '''        # Soft delete
        cur = conn.execute(f"""
            UPDATE emir_alt_proses
               SET aktif = 0,
                   guncelleme = datetime('now','localtime'),
                   guncelleyen_id = ?,
                   guncelleyen_ad = ?
             WHERE emir_no IN ({placeholders})
               AND aktif = 1
               AND kaynak LIKE ?
        """, (uid, uad) + tuple(emir_strs) + (sablon_kaynak_pattern,))
        affected = cur.rowcount

        # Etkilenen emir sayisi (distinct)
        emir_sayim = conn.execute(f"""
            SELECT COUNT(DISTINCT emir_no) FROM emir_alt_proses
             WHERE emir_no IN ({placeholders})
               AND aktif = 0
               AND kaynak LIKE ?
               AND date(COALESCE(guncelleme, olusturma)) = date('now','localtime')
        """, tuple(emir_strs) + (sablon_kaynak_pattern,)).fetchone()[0]'''

YENI = '''        # === geri-al kolon fix ===
        # emir_alt_proses tablosunda guncelleme/guncelleyen kolonlari yok
        # Sadece aktif=0 set et
        cur = conn.execute(f"""
            UPDATE emir_alt_proses
               SET aktif = 0
             WHERE emir_no IN ({placeholders})
               AND aktif = 1
               AND kaynak LIKE ?
        """, tuple(emir_strs) + (sablon_kaynak_pattern,))
        affected = cur.rowcount

        # Etkilenen emir sayisi (distinct)
        emir_sayim = conn.execute(f"""
            SELECT COUNT(DISTINCT emir_no) FROM emir_alt_proses
             WHERE emir_no IN ({placeholders})
               AND aktif = 0
               AND kaynak LIKE ?
        """, tuple(emir_strs) + (sablon_kaynak_pattern,)).fetchone()[0]'''


def main():
    if not os.path.exists(HEDEF_ROUTES):
        print(f"[HATA] {HEDEF_ROUTES} yok.")
        return 1

    with open(HEDEF_ROUTES, 'r', encoding='utf-8') as f:
        src = f.read()

    if MARKER in src:
        print("[BILGI] Fix zaten ekli.")
        return 0

    if ESKI not in src:
        print("[HATA] Eski blok bulunamadi.")
        # Belki son routes.py geri yuklemesinde geri-al endpoint'i kayboldu?
        if "/sablon/geri-al" not in src:
            print("[UYARI] geri-al endpoint'i routes.py'de YOK.")
            print("        Onceki routes.py.bak_20260428_171419 geri yuklendiginde")
            print("        geri-al endpoint'i de kayboldu.")
            print("        Cozum: setup_sablon_geri_al.py tekrar calistir, sonra bu fix.")
        return 1

    if src.count(ESKI) > 1:
        print("[HATA] Cogul.")
        return 1

    new_src = src.replace(ESKI, YENI, 1)
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"[HATA] parse: {e}")
        return 1

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = HEDEF_ROUTES + f'.bak_{ts}'
    shutil.copy2(HEDEF_ROUTES, bp)
    print(f"[OK] Yedek: {bp}")

    with open(HEDEF_ROUTES, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("[OK] geri-al endpoint duzeltildi (guncelleme kolonu kullanilmiyor).")
    print()
    print("YAPILACAK:")
    print("  1) CPS sunucusunu yeniden baslat")
    print("  2) Browser Ctrl+F5")
    print("  3) Bir emir sec -> 'Sablon Geri Al' tikla")
    return 0


if __name__ == '__main__':
    sys.exit(main())
