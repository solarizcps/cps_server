# -*- coding: utf-8 -*-
"""
diagnose_emir_kapsamli.py
-------------------------
5 emir icin kapsamli arastirma. SADECE SELECT, kod yazma yok.

Test emirler:
  ANA: 109772, 110626
  ALT: 109773, 109774, 109815

Cevaplanacak sorular:
  1) Emir cift adet hangi tablodan?
  2) Alt emir cift adet nasil?
  3) Renk hangi alan?
  4) FisNo gercekten SipNo mu?
  5) ModelKod -> Siparis_Har baglantisi dogru mu?
  6) CPS'te neden '-' geliyor?
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

ANA_EMIRLER = [109772, 110626]
ALT_EMIRLER = [109773, 109774, 109815]
HEPSI = ANA_EMIRLER + ALT_EMIRLER


def section(t, lvl=1):
    print()
    if lvl == 1:
        print("=" * 78)
        print(t)
        print("=" * 78)
    else:
        print("-" * 78)
        print(t)
        print("-" * 78)


def dump(cur, max_cols=50, max_rows=8):
    cols = [d[0] for d in cur.description][:max_cols]
    rows = cur.fetchall()
    print(f"  satir: {len(rows)}, kolon: {len(cols)}")
    for i, r in enumerate(rows[:max_rows]):
        print(f"\n  [{i+1}]")
        for c, v in zip(cols, r[:max_cols]):
            vs = repr(v)[:80]
            print(f"    {c:<22} = {vs}")


con = _kk._baglan()
cur = con.cursor()


# ============================================================
section("0) Urt_Emir tablosu - bazi onemli kolonlar")
# ============================================================
cur.execute("""
    SELECT COLUMN_NAME, DATA_TYPE
      FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_NAME='Urt_Emir'
     ORDER BY ORDINAL_POSITION
""")
ue_cols = [(r[0], r[1]) for r in cur.fetchall()]
print(f"  Toplam {len(ue_cols)} kolon. Tum liste:")
for c in ue_cols:
    print(f"    {c[0]:<22} {c[1]}")

# Urt_Emir'de miktar/adet/sip iceren kolonlar?
print("\n  Miktar/adet/sip/ile ilgili kolonlar:")
for c in ue_cols:
    name = c[0].lower()
    if any(k in name for k in ['miktar', 'adet', 'sayi', 'sip', 'belge', 'order', 'cift', 'hedef', 'sayis']):
        print(f"    -> {c[0]:<22} {c[1]}")


# ============================================================
section("1) HER EMIR icin Urt_Emir TUM ALANLAR")
# ============================================================
for emir in HEPSI:
    section(f"1.{emir} -> Urt_Emir", lvl=2)
    cur.execute("SELECT * FROM Urt_Emir WHERE EmirNo = %s", (emir,))
    dump(cur)


# ============================================================
section("2) Urt_Em2Em parent/child iliskileri")
# ============================================================
for emir in HEPSI:
    section(f"2.{emir} -> Urt_Em2Em (hem parent hem child olarak)", lvl=2)
    cur.execute("""
        SELECT *
          FROM Urt_Em2Em
         WHERE EmirNo = %s OR EmirNo_YM = %s
    """, (emir, emir))
    dump(cur)


# ============================================================
section("3) Urt_Em_gch FisNo dagilimi (her emir icin)")
# ============================================================
print("Cevap araniyor: FisNo = Siparis_Har.SipNo mu?")
print()
for emir in HEPSI:
    section(f"3.{emir}", lvl=2)
    cur.execute("""
        SELECT FisNo,
               SUM(Giren) AS toplam_giren,
               SUM(Cikan) AS toplam_cikan,
               COUNT(*) AS satir
          FROM Urt_Em_gch
         WHERE EmirNo = %s
         GROUP BY FisNo
         ORDER BY FisNo
    """, (emir,))
    fis_rows = cur.fetchall()
    if not fis_rows:
        print(f"  Urt_Em_gch'de kayit yok")
        continue
    print(f"  {len(fis_rows)} farkli FisNo:")
    for r in fis_rows:
        print(f"    FisNo={r[0]}, Giren={r[1]}, Cikan={r[2]}, Satir={r[3]}")

    # Her FisNo'nun Siparis_Kay'da karsiligi var mi?
    print(f"\n  -> Bu FisNo'lar Siparis_Kay.SipNo ile esleser mi?")
    fis_list = [str(r[0]) for r in fis_rows if r[0]]
    if fis_list:
        in_clause = ','.join(fis_list)
        cur.execute(f"""
            SELECT sk.SipNo, sk.CariKod,
                   ISNULL(cm.CName, sk.CariKod) AS CariAdi,
                   sk.Durum, sk.SipTip, sh.SKOD, sh.Miktar, sh.Birim
              FROM Siparis_Kay sk
              LEFT JOIN Siparis_Har sh ON sh.SipNo = sk.SipNo
              LEFT JOIN Cari_Kart cm ON cm.CKod = sk.CariKod
             WHERE sk.SipNo IN ({in_clause})
        """)
        rows = cur.fetchall()
        print(f"     ({len(rows)} esleme)")
        for r in rows[:10]:
            print(f"     SipNo={r[0]}, CariAdi={r[2]}, Durum={r[3]}, SipTip={r[4]}, SKOD={r[5]}, Miktar={r[6]}, Birim={r[7]}")


# ============================================================
section("4) Her emir icin Urt_Em_gch RKOD dagilimi (renk var mi?)")
# ============================================================
for emir in HEPSI:
    cur.execute("""
        SELECT RKOD,
               SUM(Giren) AS giren,
               SUM(Cikan) AS cikan,
               COUNT(*) AS k
          FROM Urt_Em_gch
         WHERE EmirNo = %s
         GROUP BY RKOD
         ORDER BY RKOD
    """, (emir,))
    rows = cur.fetchall()
    print(f"\n  Emir {emir}: {len(rows)} farkli RKOD")
    for r in rows:
        print(f"    RKOD={r[0]}, Giren={r[1]}, Cikan={r[2]}, Kayit={r[3]}")


# ============================================================
section("5) ModelKod uzerinden Siparis_Har eslesmesi")
# ============================================================
# Her emirin ModelKod'unu al, sonra Siparis_Har'da o ModelKod'a gore satir bul
for emir in HEPSI:
    section(f"5.{emir}", lvl=2)
    cur.execute("SELECT ModelKod, Tip FROM Urt_Emir WHERE EmirNo = %s", (emir,))
    r = cur.fetchone()
    if not r:
        print(f"  Urt_Emir kaydi yok!")
        continue
    model = r[0]
    tip = r[1]
    print(f"  ModelKod={model}, Tip={tip}")

    # Bu modelle eslesen Siparis_Har satirlari
    cur.execute("""
        SELECT sh.SipNo, sh.SKOD, sh.Miktar, sh.Birim, sh.Durum,
               sk.CariKod, ISNULL(cm.CName, sk.CariKod) AS CariAdi
          FROM Siparis_Har sh
          LEFT JOIN Siparis_Kay sk ON sk.SipNo = sh.SipNo
          LEFT JOIN Cari_Kart cm ON cm.CKod = sk.CariKod
         WHERE sh.SKOD = %s
           AND LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
    """, (model,))
    rows = cur.fetchall()
    print(f"  ModelKod ile {len(rows)} aktif Siparis_Har satiri:")
    for x in rows[:10]:
        print(f"    SipNo={x[0]}, Miktar={x[2]}, Birim={x[3]}, CariAdi={x[6]}")


# ============================================================
section("6) Urtx_Emir kontrol (eski kayitlar oraya gitmis olabilir)")
# ============================================================
for emir in HEPSI:
    cur.execute("SELECT TOP 1 EmirNo, ModelKod, Tip, Location, YazSay FROM Urtx_Emir WHERE EmirNo = %s", (emir,))
    r = cur.fetchone()
    if r:
        print(f"  Emir {emir}: Urtx_Emir'de VAR -> {r}")
    else:
        print(f"  Emir {emir}: Urtx_Emir'de YOK")


# ============================================================
section("7) Urtx_con_gch FisNo dagilimi (paralel uretim tablosu)")
# ============================================================
for emir in HEPSI:
    cur.execute("""
        SELECT FisNo, SUM(Giren) AS giren, SUM(Cikan) AS cikan, COUNT(*) AS k
          FROM Urtx_con_gch
         WHERE EmirNo = %s
         GROUP BY FisNo
    """, (emir,))
    rows = cur.fetchall()
    if rows:
        print(f"\n  Emir {emir} -> Urtx_con_gch:")
        for r in rows:
            print(f"    FisNo={r[0]}, Giren={r[1]}, Cikan={r[2]}, k={r[3]}")
    else:
        print(f"  Emir {emir}: Urtx_con_gch'de kayit yok")


# ============================================================
section("8) NIHAI MAPPING ANALIZI")
# ============================================================
print("""
HER EMIR ICIN dolduralim:
  emir_no, tip, model, cari_adi, lokasyon
  ✓ kapanacak_cift_adet  <-- KRITIK: nereden?

A) Siparis_Har.Miktar uzerinden (ModelKod-bagli)
   Mamul emir icin dogru, cunku Siparis_Har bitmis urun siparisleri tutuyor.

B) Urt_Em_gch.FisNo -> Siparis_Kay.SipNo eslesirse
   Her emir hangi siparise ait oldugunu DIREKT soyler.
   Bu en saglam veri kaynagi!

C) ALT emirler icin:
   ALT emirin Urt_Em_gch.FisNo -> Siparis_Kay -> bu SipNo'nun ayni SKOD/farkli SKOD
   olmasi onemli.
   ALT emir EVA hammaddesi uretiyor, ama hangi siparis icin uretiyor.

KRITIK CIKARIM:
  Eger ALT 109815 -> Urt_Em_gch.FisNo = 33558 ise
  ALT emir 33558 SIPARISI icin uretiliyor demektir.
  Bu siparisin Siparis_Har.Miktar'i da bilinen 7000 ise:
  ALT EMIR KAPANACAK MIKTAR = 7000 (kendi siparisinin miktari kadar)

  Yani ALT emir parent ana emirin TOPLAMINI degil,
  KENDISININ baglandigi sipariSin miktarini almali.
""")


con.close()
print()
print("BITTI.")
