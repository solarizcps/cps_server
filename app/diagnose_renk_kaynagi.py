# -*- coding: utf-8 -*-
"""
diagnose_renk_kaynagi.py
------------------------
Korgun Dashboard'in 'RenkAdi' alanini nasil urettigini bulmaya calis.
Sadece SELECT.

Aday tablolar:
  - StokKart - urun tanimi, OzKod1-11, BLG, MalzemeKod
  - Renk_Kart, Renk_K, RengeYansima, Renk_T, RKOD_Tanim
  - Urt_Em_gch.RKOD ile eslesme yapan baska tablo
"""
import sys, os
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except: pass
sys.path.insert(0, r"C:\cps_dev")
from modules.common import korgun as _kk

con = _kk._baglan()
cur = con.cursor()


def section(t):
    print("\n" + "="*78)
    print(t)
    print("="*78)


# ============================================================
section("1) Renk ile ilgili tablolar (INFORMATION_SCHEMA)")
# ============================================================
cur.execute("""
    SELECT TABLE_NAME
      FROM INFORMATION_SCHEMA.TABLES
     WHERE TABLE_NAME LIKE '%Renk%'
        OR TABLE_NAME LIKE '%RKOD%'
        OR TABLE_NAME LIKE '%Color%'
        OR TABLE_NAME LIKE '%Tanim%'
     ORDER BY TABLE_NAME
""")
for r in cur.fetchall():
    print(f"  {r[0]}")


# ============================================================
section("2) StokKart tum kolonlar")
# ============================================================
cur.execute("""
    SELECT COLUMN_NAME, DATA_TYPE
      FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_NAME='StokKart'
     ORDER BY ORDINAL_POSITION
""")
sk_cols = cur.fetchall()
print(f"  Toplam {len(sk_cols)} kolon:")
renk_kolonlari = []
for c in sk_cols:
    name = c[0].lower()
    is_renk = any(k in name for k in ['renk', 'color', 'rkod'])
    is_ozkod = name.startswith('ozkod')
    if is_renk or is_ozkod:
        print(f"  *** {c[0]:<22} {c[1]}")
        renk_kolonlari.append(c[0])
    else:
        print(f"      {c[0]:<22} {c[1]}")


# ============================================================
section("3) StokKart 109815 SKOD'i icin tum OzKod ve renk alanlari")
# ============================================================
# 109815 SKOD = 'EVA CRX-001'
SKOD = 'EVA CRX-001'
print(f"  SKOD = {SKOD}")
try:
    cur.execute(f"""
        SELECT *
          FROM StokKart
         WHERE SKOD = %s
    """, (SKOD,))
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print(f"  ({len(rows)} satir)")
    if rows:
        for c, v in zip(cols, rows[0]):
            vs = repr(v)[:80]
            print(f"    {c:<22} = {vs}")
except Exception as e:
    print(f"  HATA: {e}")


# ============================================================
section("4) StokKart 110626 ana modeli icin (CRX-71033-LCW)")
# ============================================================
SKOD2 = 'CRX-71033-LCW'
print(f"  SKOD = {SKOD2}")
try:
    cur.execute("""
        SELECT *
          FROM StokKart
         WHERE SKOD = %s
    """, (SKOD2,))
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print(f"  ({len(rows)} satir)")
    if rows:
        for c, v in zip(cols, rows[0]):
            vs = repr(v)[:80]
            print(f"    {c:<22} = {vs}")
except Exception as e:
    print(f"  HATA: {e}")


# ============================================================
section("5) RKOD ile bagli tablo arama")
# ============================================================
# RKOD adli kolon hangi tablolarda var?
cur.execute("""
    SELECT TABLE_NAME
      FROM INFORMATION_SCHEMA.COLUMNS
     WHERE COLUMN_NAME = 'RKOD'
     ORDER BY TABLE_NAME
""")
rkod_tables = [r[0] for r in cur.fetchall()]
print(f"  RKOD kolonu olan tablolar: {len(rkod_tables)}")
for t in rkod_tables[:20]:
    print(f"    {t}")


# ============================================================
section("6) Renk_M veya benzer tabloyu dene")
# ============================================================
for tablo in ['Renk_M', 'Renk_K', 'Renk_T', 'Renk_Kart', 'RKOD_Tanim',
              'Urt_RKOD', 'Color_M', 'StokRenk_M']:
    try:
        cur.execute(f"SELECT TOP 3 * FROM {tablo}")
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print(f"\n  *** {tablo} VAR: {cols}")
        for r in rows[:3]:
            print(f"    {r}")
    except Exception as e:
        pass  # tablo yok, sessiz gec


# ============================================================
section("7) RKOD=4 icin StokKart eslesmesi dene")
# ============================================================
# Belki StokKart'ta RKOD'a denk gelen bir kayit vardir
try:
    cur.execute("""
        SELECT TOP 5 SKOD, ISNULL(Tanim,'') AS Tanim
          FROM StokKart
         WHERE SKOD LIKE '%LCW%' OR SKOD LIKE '%TWG%'
    """)
    print("  LCW/TWG iceren stok kayitlari:")
    for r in cur.fetchall():
        print(f"    {r[0]:<25} | {r[1][:60]}")
except Exception as e:
    print(f"  HATA: {e}")


con.close()
print("\nBITTI.")
