# -*- coding: utf-8 -*-
"""
debug_cps_proses_dagilim.py
---------------------------
Emir 110626 icin proses dagilimi:
  - CPS DB.uretim_kayit (1.490 onayli)
  - Korgun.Urt_con_gch (480)
  - Korgun.Urt_Em_gch (genel hareket)

Sadece SELECT, kod yazma yok.
"""
import sys, os, sqlite3
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except: pass
sys.path.insert(0, r"C:\cps_dev")
from modules.common import korgun as _kk

EMIR = 110626
CPS_DB = r"C:\cps_dev\mock_data.db"


def section(t):
    print("\n" + "="*78)
    print(t)
    print("="*78)


# ============================================================
section(f"1) CPS uretim_kayit tablosu - tum kolonlar (semasi)")
# ============================================================
conn = sqlite3.connect(CPS_DB)
cur = conn.cursor()
cols = []
for r in cur.execute("PRAGMA table_info(uretim_kayit)"):
    cols.append(r[1])
print(f"  Kolonlar: {cols}")


# ============================================================
section(f"2) CPS uretim_kayit - emir 110626 dagilim (proses bazli)")
# ============================================================
# proses_adi ve proses_kodu kolonlari var mi sema'da kontrol
proses_kolonlari = [c for c in cols if 'proses' in c.lower()]
print(f"  Proses kolonlari: {proses_kolonlari}")

# Onay durum kolonu
onay_kolonu = None
for c in cols:
    if 'onay' in c.lower():
        onay_kolonu = c
        break
print(f"  Onay kolonu: {onay_kolonu}")

# Tum dagilim
sql_proses_kod = "proses_kodu" if "proses_kodu" in cols else None
sql_proses_adi = "proses_adi" if "proses_adi" in cols else None
miktar_kol = "miktar" if "miktar" in cols else None

if not miktar_kol:
    miktar_kol_aday = [c for c in cols if 'miktar' in c.lower() or 'adet' in c.lower()]
    print(f"  Miktar adayi: {miktar_kol_aday}")
    if miktar_kol_aday:
        miktar_kol = miktar_kol_aday[0]

print()
print(f"  Sorgu: SELECT proses, SUM({miktar_kol}) FROM uretim_kayit WHERE emir_no=110626")
print()

if sql_proses_kod and sql_proses_adi and miktar_kol:
    q = f"""
        SELECT
            {sql_proses_kod} AS proses_kod,
            {sql_proses_adi} AS proses_adi,
            COALESCE({onay_kolonu}, '-') AS onay,
            SUM(CAST({miktar_kol} AS INTEGER)) AS toplam,
            COUNT(*) AS kayit
          FROM uretim_kayit
         WHERE CAST(emir_no AS INTEGER) = ?
         GROUP BY {sql_proses_kod}, {sql_proses_adi}, COALESCE({onay_kolonu}, '-')
         ORDER BY {sql_proses_kod}
    """
    try:
        for r in cur.execute(q, (EMIR,)):
            print(f"    proses_kod={r[0]!r:<10} adi={r[1]!r:<22} onay={r[2]!r:<14} toplam={r[3]!r:<6} kayit={r[4]}")
    except Exception as e:
        print(f"  HATA: {e}")
else:
    print("  Sema farkli, manuel kontrol gerek")
    print()
    print("  emir 110626 icin TUM kayitlar (10 ornek):")
    try:
        cur.execute(f"SELECT * FROM uretim_kayit WHERE CAST(emir_no AS INTEGER)=? LIMIT 10", (EMIR,))
        rows = cur.fetchall()
        for r in rows:
            print(f"    {dict(zip(cols, r))}")
    except Exception as e:
        print(f"  HATA: {e}")


# ============================================================
section(f"3) CPS uretim_kayit - SADECE onayli toplam")
# ============================================================
if onay_kolonu and miktar_kol:
    try:
        cur.execute(f"""
            SELECT
                COALESCE({onay_kolonu}, '-') AS onay,
                SUM(CAST({miktar_kol} AS INTEGER)) AS toplam,
                COUNT(*) AS kayit
              FROM uretim_kayit
             WHERE CAST(emir_no AS INTEGER) = ?
             GROUP BY COALESCE({onay_kolonu}, '-')
        """, (EMIR,))
        for r in cur.fetchall():
            print(f"    onay={r[0]!r:<14} toplam={r[1]} kayit={r[2]}")
    except Exception as e:
        print(f"  HATA: {e}")
else:
    print("  Sema farkli")

conn.close()


# ============================================================
section(f"4) Korgun Urt_con_gch - emir 110626 proses dagilim")
# ============================================================
con = _kk._baglan()
cur2 = con.cursor()
try:
    cur2.execute("""
        SELECT
            g.Proses,
            pm.Tanim,
            SUM(g.Cikan) AS toplam,
            COUNT(*) AS kayit,
            MAX(g.EndTarih) AS son_tarih
          FROM Urt_con_gch g WITH(NOLOCK)
          LEFT JOIN Proses_M pm WITH(NOLOCK) ON pm.Pro = g.Proses
         WHERE g.EmirNo = %s
           AND g.Cikan > 0
         GROUP BY g.Proses, pm.Tanim
         ORDER BY MAX(g.EndTarih) DESC
    """, (EMIR,))
    for r in cur2.fetchall():
        print(f"    proses={r[0]!r:<6} adi={r[1]!r:<22} toplam={int(r[2] or 0):<6} kayit={r[3]:<4} son={r[4]}")
except Exception as e:
    print(f"  HATA: {e}")


# ============================================================
section(f"5) Korgun Urt_Em_gch - emir 110626 (FisNo bazli)")
# ============================================================
try:
    cur2.execute("""
        SELECT
            FisNo,
            SUM(Giren) AS giren,
            SUM(Cikan) AS cikan,
            COUNT(*) AS kayit
          FROM Urt_Em_gch WITH(NOLOCK)
         WHERE EmirNo = %s
         GROUP BY FisNo
         ORDER BY FisNo
    """, (EMIR,))
    for r in cur2.fetchall():
        print(f"    FisNo={r[0]!r:<8} giren={r[1]} cikan={r[2]} kayit={r[3]}")
except Exception as e:
    print(f"  HATA: {e}")


con.close()


# ============================================================
section("OZET")
# ============================================================
print("""
Beklenen sonuclar:
  Bolum 2: CPS uretim_kayit dagilimi -> proseslere gore 1490 nasil dagilmis?
  Bolum 4: Korgun Urt_con_gch -> Kesim 480 dogrulanmali
  Bolum 5: Korgun Urt_Em_gch -> genel hareket

Bu bilgilerle birlestirme stratejisi netlesir:
  - Aynı proses ad\u0131 hem CPS hem Korgun'da varsa toplama
  - Sadece CPS'te varsa eklenecek
  - Sadece Korgun'da varsa eklenecek
  - Aktif proses = en son tarihli (CPS+Korgun birlesik)
""")
