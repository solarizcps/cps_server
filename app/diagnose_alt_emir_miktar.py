# -*- coding: utf-8 -*-
"""
diagnose_alt_emir_miktar.py
---------------------------
ALT emir 109815 icin Korgun MSSQL'de miktar gercekten var mi yok mu?
Sadece SELECT, kod yazma yok, UI dokunma yok.

Yorumlama:
  A) Bir tabloda miktar varsa -> biz yanlis cekiyoruz, FIX gerek
  B) Hicbir tabloda miktar yoksa -> ALT emirler gercekten miktarsiz
"""

import sys
import os

# UTF-8 stdout
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

CPS_ROOT = r"C:\cps_dev"
sys.path.insert(0, CPS_ROOT)

from modules.common import korgun as _kk

EMIR_NO = 109815  # Test edilen alt emir


def section(t):
    print()
    print("=" * 72)
    print(t)
    print("=" * 72)


def dump(cur, max_cols=None):
    cols = [d[0] for d in cur.description]
    if max_cols:
        cols = cols[:max_cols]
    rows = cur.fetchall()
    print(f"  Kolonlar: {cols}")
    print(f"  Satir sayisi: {len(rows)}")
    for i, r in enumerate(rows[:5]):
        print(f"\n  --- Satir {i+1} ---")
        for c, v in zip(cols, r[:max_cols] if max_cols else r):
            vs = repr(v)[:90]
            print(f"    {c:<22} = {vs}")


con = _kk._baglan()
cur = con.cursor()


# -----------------------------------------------------------
section(f"1) Urt_Emir kaydi: EmirNo={EMIR_NO}")
# -----------------------------------------------------------
cur.execute("""
    SELECT TOP 1 *
      FROM Urt_Emir
     WHERE EmirNo = %s
""", (EMIR_NO,))
dump(cur)


# -----------------------------------------------------------
section(f"2) Urt_Em2Em parent eslesmesi (EmirNo_YM={EMIR_NO})")
# -----------------------------------------------------------
cur.execute("""
    SELECT *
      FROM Urt_Em2Em
     WHERE EmirNo_YM = %s
""", (EMIR_NO,))
dump(cur)


# Parent emir no'yu yakala
cur.execute("""
    SELECT TOP 1 EmirNo, Proses, SKod
      FROM Urt_Em2Em
     WHERE EmirNo_YM = %s
""", (EMIR_NO,))
parent_row = cur.fetchone()
parent_no = parent_row[0] if parent_row else None
parent_skod = parent_row[2] if parent_row and len(parent_row) > 2 else None

if parent_no:
    print(f"\n  -> Parent emir bulundu: EmirNo={parent_no}, SKod={parent_skod}")
else:
    print("\n  -> Parent emir yok (Urt_Em2Em'de eslesme bulunamadi)")


# -----------------------------------------------------------
section(f"3) Siparis_Har dogrudan EmirNo={EMIR_NO} ile sorgu (varsa)")
# -----------------------------------------------------------
# Siparis_Har'da EmirNo kolonu var mi diye kontrol et
try:
    cur.execute("""
        SELECT TOP 1 COLUMN_NAME
          FROM INFORMATION_SCHEMA.COLUMNS
         WHERE TABLE_NAME = 'Siparis_Har'
           AND COLUMN_NAME LIKE '%EmirNo%'
    """)
    emir_col = cur.fetchone()
    if emir_col:
        print(f"  Siparis_Har'da '{emir_col[0]}' kolonu var, sorgulanir...")
        cur.execute(f"""
            SELECT TOP 5 SipNo, SKOD, Miktar, Durum
              FROM Siparis_Har
             WHERE {emir_col[0]} = %s
        """, (EMIR_NO,))
        dump(cur)
    else:
        print("  Siparis_Har'da EmirNo kolonu YOK. (zaten model bazinda baglanti vardi)")
except Exception as e:
    print(f"  HATA: {e}")


# -----------------------------------------------------------
section(f"4) Siparis_Har Parent emir uzerinden (parent_no={parent_no})")
# -----------------------------------------------------------
if parent_no:
    # Parent ana emirin ModelKod'u uzerinden Siparis_Har
    cur.execute("""
        SELECT TOP 1 ModelKod
          FROM Urt_Emir
         WHERE EmirNo = %s
    """, (parent_no,))
    parent_model_row = cur.fetchone()
    if parent_model_row:
        parent_model = parent_model_row[0]
        print(f"  Parent ana emir ({parent_no}) ModelKod = {parent_model}")
        cur.execute("""
            SELECT SipNo, SKOD, Miktar, Birim, Durum
              FROM Siparis_Har
             WHERE SKOD = %s
               AND LTRIM(RTRIM(ISNULL(Durum,''))) = ''
        """, (parent_model,))
        rows = cur.fetchall()
        print(f"  ({len(rows)} satir)")
        for r in rows:
            print(f"    SipNo={r[0]}, SKOD={r[1]}, Miktar={r[2]}, Birim={r[3]}")
else:
    print("  Parent yok, sorgu atlanir.")


# -----------------------------------------------------------
section(f"5) Urt_con_gch uretim kayitlari (EmirNo={EMIR_NO})")
# -----------------------------------------------------------
try:
    cur.execute("""
        SELECT TOP 5 EmirNo, RKOD, BedKod, Cikan, Giren, Location, FisTip
          FROM Urt_con_gch
         WHERE EmirNo = %s
    """, (EMIR_NO,))
    dump(cur)

    cur.execute("""
        SELECT SUM(Cikan) AS toplam_cikan, COUNT(*) AS kayit
          FROM Urt_con_gch
         WHERE EmirNo = %s
    """, (EMIR_NO,))
    row = cur.fetchone()
    print(f"\n  TOPLAM Urt_con_gch.Cikan = {row[0]}, kayit = {row[1]}")
except Exception as e:
    print(f"  HATA: {e}")


# -----------------------------------------------------------
section(f"6) Urt_Em_gch (genel emir hareket) toplami (EmirNo={EMIR_NO})")
# -----------------------------------------------------------
try:
    cur.execute("""
        SELECT TOP 3 *
          FROM Urt_Em_gch
         WHERE EmirNo = %s
    """, (EMIR_NO,))
    dump(cur, max_cols=12)

    cur.execute("""
        SELECT COALESCE(SUM(Cikan),0) AS toplam_cikan,
               COALESCE(SUM(Giren),0) AS toplam_giren,
               COUNT(*) AS kayit
          FROM Urt_Em_gch
         WHERE EmirNo = %s
    """, (EMIR_NO,))
    row = cur.fetchone()
    print(f"\n  Urt_Em_gch toplam Cikan={row[0]}, Giren={row[1]}, kayit={row[2]}")
except Exception as e:
    print(f"  HATA: {e}")


# -----------------------------------------------------------
section(f"7) Urt_Emir kendi YazSay/Adet alanlari (EmirNo={EMIR_NO})")
# -----------------------------------------------------------
try:
    cur.execute("""
        SELECT TOP 1
            EmirNo, ModelKod, Tip, Location, YazSay,
            ISNULL(Durum,'') AS Durum
          FROM Urt_Emir
         WHERE EmirNo = %s
    """, (EMIR_NO,))
    row = cur.fetchone()
    if row:
        cols = [d[0] for d in cur.description]
        for c, v in zip(cols, row):
            print(f"    {c:<14} = {repr(v)[:80]}")
        print(f"\n  YazSay = {row[4]} (bu degerin anlami: emirde planlanan miktar olabilir)")
except Exception as e:
    print(f"  HATA: {e}")


# -----------------------------------------------------------
section("8) OZET - Hangi tabloda miktar VAR?")
# -----------------------------------------------------------
print("Yukaridaki sonuclari sectikten sonra:")
print("  - Urt_Emir.YazSay: emirin kendi planlanan miktari (varsa kullan)")
print("  - Urt_Em_gch.SUM(Cikan): fiilen yapilan toplam (uretildi)")
print("  - Siparis_Har.Miktar: sadece ANA emir icin (yari mamulun parent'i)")
print()
print("Yorumlama:")
print("  A) Eger Urt_Emir.YazSay > 0 ise -> ALT emir miktarini buradan cekebiliriz")
print("  B) Eger YazSay null/0 ve Urt_Em_gch'de hareket varsa ->")
print("     'fiilen yapilan' goruluyor ama 'planlanan' yok demektir")
print("  C) Hic biri yoksa -> ALT emirler gercekten miktarsiz, '-' dogru")


con.close()
print()
print("BITTI.")
