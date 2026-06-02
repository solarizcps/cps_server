# -*- coding: utf-8 -*-
"""
diagnose_alt_emir_iliski.py
---------------------------
ALT emir 109815 ve cevresi - kapanacak adetin GERCEK kaynagi nerede?

Sorular:
  1) Alt emir hangi ana emire bagli?
  2) Alt emir hangi siparis satirina bagli?
  3) Alt emrin kapanacak cifti hangi tablodan?
  4) Urt_Em_gch.Giren/Cikan plan mi gerceklesen mi?
  5) Alt emir icin planlanan miktar hangi alan/tablo?
  6) Ana emirlerde 7000/14000 ayrimi nasil?
  7) Siparis_Har 33558 ve 33638 hangi emire bagli?

Sadece SELECT, kod yazma yok.
"""

import sys
import os

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

CPS_ROOT = r"C:\cps_dev"
sys.path.insert(0, CPS_ROOT)

from modules.common import korgun as _kk

ALT_EMIR = 109815
PARENT_EMIR = 109790
ANA_EMIR = 110626  # zaten bildigimiz baska bir ana emir
SIP1, SIP2 = 33558, 33638
MODEL = 'CRX-71033-LCW'


def section(t):
    print()
    print("=" * 78)
    print(t)
    print("=" * 78)


def dump_one(cur, max_cols=50):
    cols = [d[0] for d in cur.description]
    cols = cols[:max_cols]
    rows = cur.fetchall()
    print(f"  Satir sayisi: {len(rows)}")
    for i, r in enumerate(rows[:10]):
        print(f"\n  --- Satir {i+1} ---")
        for c, v in zip(cols, r[:max_cols]):
            vs = repr(v)[:90]
            print(f"    {c:<26} = {vs}")


con = _kk._baglan()
cur = con.cursor()


# ============================================================
section("0) Urt_Emir TABLOSU — TUM KOLONLARI")
# ============================================================
cur.execute("""
    SELECT TOP 1 COLUMN_NAME, DATA_TYPE
      FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_NAME='Urt_Emir'
""")
cur.execute("""
    SELECT COLUMN_NAME, DATA_TYPE
      FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_NAME='Urt_Emir'
     ORDER BY ORDINAL_POSITION
""")
cols = cur.fetchall()
print(f"  Toplam {len(cols)} kolon:")
for c in cols:
    print(f"    {c[0]:<26} {c[1]}")


# ============================================================
section("1) ALT EMIR 109815 — Urt_Emir TUM ALANLAR")
# ============================================================
cur.execute("SELECT * FROM Urt_Emir WHERE EmirNo = %s", (ALT_EMIR,))
dump_one(cur)


# ============================================================
section("2) ANA EMIR 109790 (parent) — Urt_Emir TUM ALANLAR")
# ============================================================
cur.execute("SELECT * FROM Urt_Emir WHERE EmirNo = %s", (PARENT_EMIR,))
dump_one(cur)


# ============================================================
section("3) ANA EMIR 110626 (zaten bildigimiz) — Urt_Emir TUM ALANLAR")
# ============================================================
cur.execute("SELECT * FROM Urt_Emir WHERE EmirNo = %s", (ANA_EMIR,))
dump_one(cur)


# ============================================================
section("4) Urt_Em2Em - parent/child iliskisi 109815 icin")
# ============================================================
cur.execute("""
    SELECT TOP 10 *
      FROM Urt_Em2Em
     WHERE EmirNo = %s OR EmirNo_YM = %s
""", (ALT_EMIR, ALT_EMIR))
dump_one(cur)


# ============================================================
section("5) Urt_Em2Em ANA emir 109790 icin TUM child emirler")
# ============================================================
cur.execute("""
    SELECT *
      FROM Urt_Em2Em
     WHERE EmirNo = %s
""", (PARENT_EMIR,))
dump_one(cur)


# ============================================================
section("6) Siparis_Har TUM KOLONLAR + 33558+33638 satirlari")
# ============================================================
cur.execute("""
    SELECT COLUMN_NAME, DATA_TYPE
      FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_NAME='Siparis_Har'
     ORDER BY ORDINAL_POSITION
""")
sh_cols = cur.fetchall()
print(f"  Siparis_Har kolonlari ({len(sh_cols)}):")
for c in sh_cols:
    print(f"    {c[0]:<26} {c[1]}")

print()
cur.execute("""
    SELECT *
      FROM Siparis_Har
     WHERE SipNo IN (%s, %s)
       AND SKOD = %s
""", (SIP1, SIP2, MODEL))
dump_one(cur)


# ============================================================
section("7) Siparis_Kay 33558 ve 33638 (siparis baslik bilgisi)")
# ============================================================
cur.execute("""
    SELECT TOP 5 *
      FROM Siparis_Kay
     WHERE SipNo IN (%s, %s)
""", (SIP1, SIP2))
dump_one(cur)


# ============================================================
section("8) Hangi emir hangi siparis - DOGRUDAN BAGLI MI?")
# ============================================================
print("Soru: Bir emirin hangi sipariste oldugu DOGRUDAN bir alanla mi belli?")
print("Yoksa SKOD uzerinden mi cikariliyor?")
print()
print("Urt_Emir'de Siparis ile ilgili alan var mi diye INFORMATION_SCHEMA'da kontrol:")
cur.execute("""
    SELECT COLUMN_NAME
      FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_NAME='Urt_Emir'
       AND (COLUMN_NAME LIKE '%Sip%'
         OR COLUMN_NAME LIKE '%Belge%'
         OR COLUMN_NAME LIKE '%Order%')
""")
for r in cur.fetchall():
    print(f"    {r[0]}")


# ============================================================
section("9) Urt_Em_gch + Urt_con_gch - SATIRLARDA SipNo VAR MI?")
# ============================================================
cur.execute("""
    SELECT TOP 1 COLUMN_NAME
      FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_NAME='Urt_Em_gch'
       AND COLUMN_NAME LIKE '%Sip%'
""")
for r in cur.fetchall():
    print(f"    Urt_Em_gch'de Sip kolonu: {r[0]}")

print()
print("FisNo alani Siparis_Har.SipNo ile esles mi diye 109815 satirlarinda bak:")
cur.execute("""
    SELECT TOP 10 EmirNo, SKOD, RKOD, FisNo, FisHarinx, Giren, Cikan, Location, Modul
      FROM Urt_Em_gch
     WHERE EmirNo = %s
""", (ALT_EMIR,))
dump_one(cur)


# ============================================================
section("10) Urt_Em_gch.FisNo Siparis_Har.SipNo'ya esit mi?")
# ============================================================
cur.execute("""
    SELECT
        eg.EmirNo, eg.FisNo,
        sh.SipNo, sh.SKOD, sh.Miktar,
        SUM(eg.Giren) AS toplam_giren,
        SUM(eg.Cikan) AS toplam_cikan
      FROM Urt_Em_gch eg
      LEFT JOIN Siparis_Har sh ON sh.SipNo = eg.FisNo
                              AND sh.SKOD = eg.SKOD
     WHERE eg.EmirNo = %s
     GROUP BY eg.EmirNo, eg.FisNo, sh.SipNo, sh.SKOD, sh.Miktar
""", (ALT_EMIR,))
dump_one(cur)


# ============================================================
section("11) Urt_Em_gch SipNo bazli toplamlar (109815)")
# ============================================================
cur.execute("""
    SELECT FisNo, SUM(Giren) AS giren, SUM(Cikan) AS cikan, COUNT(*) AS satir
      FROM Urt_Em_gch
     WHERE EmirNo = %s
     GROUP BY FisNo
""", (ALT_EMIR,))
rows = cur.fetchall()
print(f"  ({len(rows)} farkli FisNo)")
for r in rows:
    print(f"    FisNo={r[0]}, Giren={r[1]}, Cikan={r[2]}, Satir={r[3]}")


# ============================================================
section("12) Urt_Em_gch ANA emir 109790 SipNo bazli toplam")
# ============================================================
cur.execute("""
    SELECT FisNo, SUM(Giren) AS giren, SUM(Cikan) AS cikan, COUNT(*) AS satir
      FROM Urt_Em_gch
     WHERE EmirNo = %s
     GROUP BY FisNo
""", (PARENT_EMIR,))
rows = cur.fetchall()
print(f"  ({len(rows)} farkli FisNo)")
for r in rows:
    print(f"    FisNo={r[0]}, Giren={r[1]}, Cikan={r[2]}, Satir={r[3]}")


# ============================================================
section("13) ANA EMIR 110626 ayni FisNo dagilimi (test)")
# ============================================================
cur.execute("""
    SELECT FisNo, SUM(Giren) AS giren, SUM(Cikan) AS cikan, COUNT(*) AS satir
      FROM Urt_Em_gch
     WHERE EmirNo = %s
     GROUP BY FisNo
""", (ANA_EMIR,))
rows = cur.fetchall()
print(f"  ({len(rows)} farkli FisNo)")
for r in rows:
    print(f"    FisNo={r[0]}, Giren={r[1]}, Cikan={r[2]}, Satir={r[3]}")


# ============================================================
section("14) NIHAI YORUM REHBERI")
# ============================================================
print("""
SECENEKLER:

A) Urt_Em_gch.FisNo == Siparis_Har.SipNo eslesirse:
   Her emir + her FisNo icin -> o siparisin Miktar'i
   Bu en saglam: emir bir SipNo'ya bagli ise miktar Siparis_Har'dan direkt gelir.

B) Eger ALT emir tek FisNo'ya bagliysa (109815 -> 33558):
   ALT emirin gercek kapanacak miktari = Siparis_Har(33558).Miktar = 7000

C) Eger ALT emir BIRDEN COK FisNo'ya bagliysa:
   Toplam = SUM(Siparis_Har.Miktar WHERE SipNo IN o emirin tum FisNo'lari)

D) Eger FisNo Siparis_Har'da yoksa:
   Eski ihtimal: Urt_Em_gch.SUM(Giren) -> hammadde olarak girilmis miktar
   Bu 'plan' degil, 'fiilen baslayan' miktari.

KARAR ICIN BAK: bolum 11 ve 12'deki FisNo dagilimina.
""")


con.close()
print()
print("BITTI.")
