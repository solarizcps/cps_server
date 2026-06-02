# -*- coding: utf-8 -*-
"""
diagnose_gercek_emir_miktari.py
-------------------------------
Eski usta_panel.html ToplamGiren = Urt_Em_gch.SUM(Giren) kullaniyor.
Bu gercekten EMIR MIKTARI mi yoksa baska bir sey mi?

Test edilen emirler: 109772, 110626, 109773, 109815

Sadece SELECT.
"""
import sys, os
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except: pass
sys.path.insert(0, r"C:\cps_dev")
from modules.common import korgun as _kk

EMIRLER = [109772, 109775, 109778, 109790, 110626, 109773, 109815, 110627, 110628]


def section(t):
    print("\n" + "="*78)
    print(t)
    print("="*78)


con = _kk._baglan()
cur = con.cursor()


# ============================================================
section("1) Her emir icin Urt_Em_gch SUM(Giren) ve SUM(Cikan)")
# ============================================================
print(f"{'EmirNo':<10}{'Tip':<5}{'Giren':<10}{'Cikan':<10}{'Satir':<8}")
print("-" * 50)
for emir in EMIRLER:
    cur.execute("""
        SELECT
            (SELECT TOP 1 Tip FROM Urt_Emir WHERE EmirNo=%s),
            COALESCE(SUM(Giren),0) AS giren,
            COALESCE(SUM(Cikan),0) AS cikan,
            COUNT(*) AS k
          FROM Urt_Em_gch WHERE EmirNo=%s
    """, (emir, emir))
    r = cur.fetchone()
    print(f"{emir:<10}{(r[0] or '-'):<5}{int(r[1] or 0):<10}{int(r[2] or 0):<10}{r[3] or 0:<8}")


# ============================================================
section("2) Aynisi Urtx_con_gch + Urtx_Emir icin (paralel tablo)")
# ============================================================
for emir in EMIRLER:
    try:
        cur.execute("""
            SELECT COALESCE(SUM(Cikan),0), COUNT(*) FROM Urtx_con_gch WHERE EmirNo=%s
        """, (emir,))
        r = cur.fetchone()
        if r[1] > 0:
            print(f"  {emir} -> Urtx_con_gch: Cikan={int(r[0])}, satir={r[1]}")
    except: pass


# ============================================================
section("3) Urt_con_gch SUM(Cikan) (proses bazli yapilanlar)")
# ============================================================
for emir in EMIRLER:
    cur.execute("""
        SELECT COALESCE(SUM(Cikan),0), COUNT(*) FROM Urt_con_gch WHERE EmirNo=%s
    """, (emir,))
    r = cur.fetchone()
    if r[1] > 0:
        print(f"  {emir} -> Urt_con_gch: Cikan={int(r[0])}, satir={r[1]}")
    else:
        print(f"  {emir} -> Urt_con_gch: kayit yok")


# ============================================================
section("4) get_emir_ozet eski helper sonuclari (karsilastirma)")
# ============================================================
for emir in EMIRLER[:5]:
    try:
        ozet = _kk.get_emir_ozet(emir)
        if ozet.get('ok'):
            print(f"  {emir} -> hedef={ozet.get('hedef_adet')}, yapilan={ozet.get('yapilan_adet')}, tip={ozet.get('tip')}")
    except Exception as e:
        print(f"  {emir} HATA: {e}")


# ============================================================
section("5) Urt_Emir TUM kolon - emir miktari icin alan var mi?")
# ============================================================
cur.execute("""
    SELECT COLUMN_NAME, DATA_TYPE
      FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_NAME='Urt_Emir'
     ORDER BY ORDINAL_POSITION
""")
print("Urt_Emir tum kolonlari:")
for r in cur.fetchall():
    print(f"  {r[0]:<22} {r[1]}")


# ============================================================
section("6) HIPOTEZ: Toplam Giren = Emir miktari mi?")
# ============================================================
print("""
ESKI SISTEM KAYNAK ANALIZI:
- usta_panel.html satir 822: e.ToplamGiren -> 'Miktar' kolonunda gosteriliyor
- ToplamGiren'in Korgun'da 1:1 karsiligi: SUM(Urt_Em_gch.Giren)
- Bu degerin GERCEKTEN emir cift adetine es olup olmadigi 1. blokta gorulur:

KARAR:
- Eger SUM(Giren) = ana emir cift adeti (mantikli sayi: 400-7000) -> KULLAN
- Eger SUM(Giren) cok kucuk veya 0 -> Cikan'a bak veya baska kaynak
- Sifir olan emirler icin: '-' goster (henuz hammadde girilmemis)
""")


con.close()
print("\nBITTI.")
