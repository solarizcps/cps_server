# -*- coding: utf-8 -*-
"""
fix_korgun_nolock.py
--------------------
Sorun: Urt_Em_gch SUM(Giren) sorgusu lock bekliyor, timeout veriyor.
Cozum: WITH(NOLOCK) hint ekle (planlama_server.py de bunu kullaniyor).

Etki: Read-only zaten, NOLOCK guvenli. Sadece okuma sirasinda lock bekleme.
"""

import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
KORGUN_PY = os.path.join(CPS_ROOT, "modules", "common", "korgun.py")

KORGUN_MARKER = "# === FAZ 4.6 B3 polish + NOLOCK ==="


# Mevcut polish blok (timeout veren):
ESKI = '''            # === FAZ 4.6 B3 fix_timeout v2 + polish ===
            # Tek batch: SUM(Giren) hem ana hem alt icin gercek miktar
            # RKOD: <100 filtre (BedKod 1000+ ile karismasin)
            tum_emir_nos = [int(d['EmirNo']) for d in ana_dicts] + \\
                           [int(d['EmirNo']) for d in yari_dicts]
            emir_giren_map = {}
            emir_rkod_map = {}
            if tum_emir_nos:
                placeholders = ','.join(['%s'] * len(tum_emir_nos))
                cur.execute(f"""
                    SELECT EmirNo,
                           COALESCE(SUM(Giren), 0) AS toplam_giren,
                           MAX(CASE WHEN RKOD IS NOT NULL AND RKOD < 100
                                    THEN RKOD ELSE NULL END) AS rkod_temiz
                    FROM Urt_Em_gch
                    WHERE EmirNo IN ({placeholders})
                    GROUP BY EmirNo
                """, tuple(tum_emir_nos))
                for r in cur.fetchall():
                    e_no = int(r[0])
                    emir_giren_map[e_no] = float(r[1] or 0)
                    emir_rkod_map[e_no] = r[2]'''

# WITH(NOLOCK) ile yenisi
YENI = '''            # === FAZ 4.6 B3 polish + NOLOCK ===
            # WITH(NOLOCK) ile lock beklemiyoruz, ayni planlama_server.py gibi
            # Read-only, guvenli.
            tum_emir_nos = [int(d['EmirNo']) for d in ana_dicts] + \\
                           [int(d['EmirNo']) for d in yari_dicts]
            emir_giren_map = {}
            emir_rkod_map = {}
            if tum_emir_nos:
                placeholders = ','.join(['%s'] * len(tum_emir_nos))
                cur.execute(f"""
                    SELECT EmirNo,
                           COALESCE(SUM(Giren), 0) AS toplam_giren,
                           MAX(CASE WHEN RKOD IS NOT NULL AND RKOD < 100
                                    THEN RKOD ELSE NULL END) AS rkod_temiz
                    FROM Urt_Em_gch WITH(NOLOCK)
                    WHERE EmirNo IN ({placeholders})
                    GROUP BY EmirNo
                """, tuple(tum_emir_nos))
                for r in cur.fetchall():
                    e_no = int(r[0])
                    emir_giren_map[e_no] = float(r[1] or 0)
                    emir_rkod_map[e_no] = r[2]'''


def main():
    if not os.path.exists(KORGUN_PY):
        print(f"[HATA] {KORGUN_PY} yok.")
        return 1

    with open(KORGUN_PY, 'r', encoding='utf-8') as f:
        src = f.read()

    if KORGUN_MARKER in src:
        print("[BILGI] NOLOCK fix zaten ekli.")
        return 0

    if ESKI not in src:
        print("[HATA] Eski blok bulunamadi.")
        print("       Onceki polish patch'i uygulanmamis olabilir.")
        return 1
    if src.count(ESKI) > 1:
        print("[HATA] Eski blok cogul.")
        return 1

    new_src = src.replace(ESKI, YENI, 1)

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"[HATA] parse: {e}")
        return 1

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = KORGUN_PY + f'.bak_{ts}'
    shutil.copy2(KORGUN_PY, bp)
    print(f"[OK] Yedek: {bp}")

    with open(KORGUN_PY, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("[OK] WITH(NOLOCK) eklendi.")
    print()
    print("YAPILACAK:")
    print("  1) CPS sunucusunu yeniden baslat")
    print("  2) Browser'da Ctrl+F5")
    print("  3) /hedef/ -> SABLON -> 33558 -> Emirleri Getir")
    print()
    print("Beklenen: HEMEN cevap, timeout yok.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
