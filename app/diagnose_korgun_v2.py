# -*- coding: utf-8 -*-
"""
diagnose_korgun_v2.py
---------------------
v1'den fark:
  - sys.stdout UTF-8 (cp1252 encoding hatasini onler)
  - Siparis_Har JOIN'i SKOD=ModelKod uzerinden (dogru)
  - Urt_con_gch + Urtx_con_gch + Urt_Em_gch rkod test
"""

import sys
import os

# UTF-8 stdout (Win PowerShell cp1252 hatasi icin)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

CPS_ROOT = r"C:\cps_dev"
sys.path.insert(0, CPS_ROOT)

from modules.common import korgun as _kk


def section(t):
    print()
    print("=" * 72)
    print(t)
    print("=" * 72)


con = _kk._baglan()
cur = con.cursor()

# ----------------------------------------------------------
section("1) Siparis_Har 110626 (JOIN: SKOD=ModelKod)")
# ----------------------------------------------------------
try:
    cur.execute("""
        SELECT sh.SipNo, sh.SKOD, sh.Tanim, sh.Miktar, sh.Birim,
               sh.OzKod1, sh.OzKod2, sh.OzKod3, sh.LotNo,
               LTRIM(RTRIM(ISNULL(sh.Durum,''))) AS Durum,
               sh.TerminTarihi
        FROM Urt_Emir ue
        INNER JOIN Siparis_Har sh ON sh.SKOD = ue.ModelKod
        WHERE ue.EmirNo = 110626
        ORDER BY sh.SipNo
    """)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print(f"  ({len(rows)} satir)")
    for r in rows:
        print()
        for c, v in zip(cols, r):
            vs = repr(v)[:80]
            print(f"    {c:<18} = {vs}")
except Exception as e:
    print(f"  HATA: {type(e).__name__}: {e}")


# ----------------------------------------------------------
section("2) Urt_con_gch 110626 GROUP BY RKOD")
# ----------------------------------------------------------
try:
    cur.execute("""
        SELECT RKOD, SUM(Cikan) AS toplam_cikan, COUNT(*) AS kayit
          FROM Urt_con_gch
         WHERE EmirNo = 110626
         GROUP BY RKOD
         ORDER BY toplam_cikan DESC
    """)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print(f"  ({len(rows)} renk)")
    for r in rows:
        print(f"    {dict(zip(cols, r))}")
except Exception as e:
    print(f"  HATA: {type(e).__name__}: {e}")


# ----------------------------------------------------------
section("3) Urtx_con_gch 110626 GROUP BY RKOD")
# ----------------------------------------------------------
try:
    cur.execute("""
        SELECT RKOD, SUM(Cikan) AS toplam_cikan, COUNT(*) AS kayit
          FROM Urtx_con_gch
         WHERE EmirNo = 110626
         GROUP BY RKOD
         ORDER BY toplam_cikan DESC
    """)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print(f"  ({len(rows)} renk)")
    for r in rows:
        print(f"    {dict(zip(cols, r))}")
except Exception as e:
    print(f"  HATA: {type(e).__name__}: {e}")


# ----------------------------------------------------------
section("4) Urt_Em_gch 110626 ornek 5 satir (get_emir_ozet bunu kullaniyor)")
# ----------------------------------------------------------
try:
    cur.execute("SELECT TOP 1 * FROM Urt_Em_gch WHERE EmirNo = 110626")
    cols = [d[0] for d in cur.description]
    print(f"  Kolonlar: {cols}")
    print()

    cur.execute("""
        SELECT TOP 5 *
          FROM Urt_Em_gch
         WHERE EmirNo = 110626
    """)
    rows = cur.fetchall()
    for r in rows:
        print()
        for c, v in zip(cols, r):
            vs = repr(v)[:80]
            print(f"    {c:<20} = {vs}")
except Exception as e:
    print(f"  HATA: {type(e).__name__}: {e}")


# ----------------------------------------------------------
section("5) Urt_Em_gch 110626 GROUP BY RKOD (eger renk varsa)")
# ----------------------------------------------------------
try:
    cur.execute("""
        SELECT RKOD, SUM(Cikan) AS toplam, COUNT(*) AS k
          FROM Urt_Em_gch
         WHERE EmirNo = 110626
         GROUP BY RKOD
         ORDER BY toplam DESC
    """)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print(f"  ({len(rows)} renk)")
    for r in rows:
        print(f"    {dict(zip(cols, r))}")
except Exception as e:
    print(f"  HATA: {type(e).__name__}: {e}")


# ----------------------------------------------------------
section("6) Renk kataloğu — Renk_M veya benzer tablo var mi?")
# ----------------------------------------------------------
for tablo in ['Renk_M', 'Renk', 'RkodTanim', 'Renk_K']:
    try:
        cur.execute(f"SELECT TOP 1 * FROM {tablo}")
        cols = [d[0] for d in cur.description]
        print(f"  {tablo} VAR. Kolonlar: {cols}")
    except Exception as e:
        print(f"  {tablo} yok ({str(e)[:60]})")


con.close()
print()
print("BITTI.")
