# -*- coding: utf-8 -*-
"""
debug_termin_son_proses.py
--------------------------
PLAN icin TERMIN ve SON PROSES alanlarinin Korgun'da nereden gelecegini
test ediyoruz. SADECE SELECT.

Test emir: 110626 (siparisler 33558, 33638)
"""
import sys, json
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except: pass
sys.path.insert(0, r"C:\cps_dev")
from modules.common import korgun as _kk

EMIR = 110626
SIPARISLER = [33558, 33638]
MODEL = 'CRX-71033-LCW'

def section(t):
    print("\n" + "="*78)
    print(t)
    print("="*78)


con = _kk._baglan()
cur = con.cursor()


# ===========================================================
section("1) Siparis_Har TerminTarihi - 33558, 33638")
# ===========================================================
try:
    cur.execute("""
        SELECT SipNo, SKOD, TerminTarihi, ISNULL(Durum,'') AS Durum, Miktar
          FROM Siparis_Har WITH(NOLOCK)
         WHERE SipNo IN (33558, 33638)
           AND SKOD = %s
    """, (MODEL,))
    rows = cur.fetchall()
    print(f"  Satir: {len(rows)}")
    for r in rows:
        print(f"    SipNo={r[0]}, SKOD={r[1]}, TerminTarihi={r[2]!r}, Durum={r[3]!r}, Miktar={r[4]}")
except Exception as e:
    print(f"  HATA: {e}")


# ===========================================================
section("2) Siparis_Kay TerminTarihi - 33558, 33638")
# ===========================================================
try:
    cur.execute("""
        SELECT SipNo, CariKod, TerminTarihi, ISNULL(Durum,'') AS Durum
          FROM Siparis_Kay WITH(NOLOCK)
         WHERE SipNo IN (33558, 33638)
    """)
    rows = cur.fetchall()
    print(f"  Satir: {len(rows)}")
    for r in rows:
        print(f"    SipNo={r[0]}, CariKod={r[1]!r}, TerminTarihi={r[2]!r}, Durum={r[3]!r}")
except Exception as e:
    print(f"  HATA: {e}")


# ===========================================================
section("3) Urt_Emir TerTarih - EmirNo 110626")
# ===========================================================
try:
    cur.execute("""
        SELECT EmirNo, ModelKod, TerTarih, ISNULL(Durum,'') AS Durum, Tip
          FROM Urt_Emir WITH(NOLOCK)
         WHERE EmirNo = %s
    """, (EMIR,))
    rows = cur.fetchall()
    print(f"  Satir: {len(rows)}")
    for r in rows:
        print(f"    EmirNo={r[0]}, ModelKod={r[1]}, TerTarih={r[2]!r}, Durum={r[3]!r}, Tip={r[4]!r}")
except Exception as e:
    print(f"  HATA: {e}")


# ===========================================================
section("4) Urt_con_gch SON proses - EmirNo 110626")
# ===========================================================
try:
    cur.execute("""
        SELECT TOP 5 EmirNo, Proses, Personel,
               Cikan, Giren, EndTarih
          FROM Urt_con_gch WITH(NOLOCK)
         WHERE EmirNo = %s
           AND Cikan > 0
         ORDER BY EndTarih DESC
    """, (EMIR,))
    rows = cur.fetchall()
    print(f"  Satir: {len(rows)}")
    for r in rows:
        print(f"    EmirNo={r[0]}, Proses={r[1]!r}, Personel={r[2]!r}, Cikan={r[3]}, Giren={r[4]}, EndTarih={r[5]!r}")
except Exception as e:
    print(f"  HATA: {e}")


# ===========================================================
section("5) Proses_M ile JOIN - TOP 1 son proses")
# ===========================================================
try:
    cur.execute("""
        SELECT TOP 1
               g.EmirNo,
               g.Proses AS ProsesKod,
               pm.Tanim AS ProsesAdi,
               g.EndTarih
          FROM Urt_con_gch g WITH(NOLOCK)
          LEFT JOIN Proses_M pm ON pm.Pro = g.Proses
         WHERE g.EmirNo = %s
           AND g.Cikan > 0
         ORDER BY g.EndTarih DESC
    """, (EMIR,))
    r = cur.fetchone()
    if r:
        print(f"    EmirNo={r[0]}, ProsesKod={r[1]!r}, ProsesAdi={r[2]!r}, EndTarih={r[3]!r}")
    else:
        print("    Yok")
except Exception as e:
    print(f"  HATA: {e}")


# ===========================================================
section("6) Birlesik termin SQL (3 aday COALESCE) - tek query")
# ===========================================================
try:
    cur.execute("""
        SELECT
          COALESCE(
            (SELECT MIN(sh.TerminTarihi)
               FROM Siparis_Har sh WITH(NOLOCK)
              WHERE sh.SipNo IN (33558, 33638)
                AND sh.SKOD = %s
                AND sh.TerminTarihi IS NOT NULL),
            (SELECT MIN(sk.TerminTarihi)
               FROM Siparis_Kay sk WITH(NOLOCK)
              WHERE sk.SipNo IN (33558, 33638)
                AND sk.TerminTarihi IS NOT NULL),
            (SELECT TOP 1 ue.TerTarih
               FROM Urt_Emir ue WITH(NOLOCK)
              WHERE ue.EmirNo = %s)
          ) AS Termin
    """, (MODEL, EMIR))
    r = cur.fetchone()
    print(f"    Termin (COALESCE sonucu): {r[0]!r}")
except Exception as e:
    print(f"  HATA: {e}")


# ===========================================================
section("OZET")
# ===========================================================
print("""
Hangi alan dolu cikti:
  - Bolum 1 (Siparis_Har) -> dolu mu?
  - Bolum 2 (Siparis_Kay) -> dolu mu?
  - Bolum 3 (Urt_Emir.TerTarih) -> dolu mu?
  - Bolum 4 (Urt_con_gch) -> kayit var mi, en son proses ne?
  - Bolum 5 (Proses_M JOIN) -> proses adi cikiyor mu?
  - Bolum 6 (COALESCE birlesik) -> tek query'le termin doluyor mu?

Patch icin gerekli SQL: Bolum 5 ve Bolum 6.
""")

con.close()
