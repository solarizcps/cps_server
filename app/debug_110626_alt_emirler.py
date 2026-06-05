# -*- coding: utf-8 -*-
"""
debug_110626_alt_emirler.py
---------------------------
110626 ana emirinin Urt_Em2Em iliskisi var mi?
Eger varsa hangi alt emirler? Onlar atki/govde mi?

Sadece SELECT.
"""
import sys
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except: pass
sys.path.insert(0, r"C:\cps_dev")
from modules.common import korgun as _kk

EMIR = 110626


def section(t):
    print("\n" + "="*78)
    print(t)
    print("="*78)


con = _kk._baglan()
cur = con.cursor()


# ============================================================
section(f"1) Urt_Em2Em - 110626 hem ana hem alt mi?")
# ============================================================
print("Sorgu: WHERE EmirNo=110626 OR EmirNo_YM=110626")
try:
    cur.execute("""
        SELECT *
          FROM Urt_Em2Em WITH(NOLOCK)
         WHERE EmirNo = %s OR EmirNo_YM = %s
    """, (EMIR, EMIR))
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print(f"  Toplam {len(rows)} satir, kolonlar: {cols}")
    for r in rows:
        rec = dict(zip(cols, r))
        print(f"  EmirNo={rec.get('EmirNo')!r}, EmirNo_YM={rec.get('EmirNo_YM')!r}, Tip={rec.get('Tip')!r}")
        # Ekstra kolonlar
        for k, v in rec.items():
            if k not in ('EmirNo', 'EmirNo_YM', 'Tip'):
                if v is not None and str(v).strip():
                    print(f"    {k}={v!r}")
except Exception as e:
    print(f"  HATA: {e}")


# ============================================================
section(f"2) 110626 alt emirleri varsa: detaylari (model, tip, miktar)")
# ============================================================
try:
    cur.execute("""
        SELECT e.EmirNo, e.ModelKod, e.Tip, e.Location, e.YazSay,
               m.Tanim AS ModelAdi
          FROM Urt_Em2Em em WITH(NOLOCK)
          INNER JOIN Urt_Emir e WITH(NOLOCK) ON e.EmirNo = em.EmirNo_YM
          LEFT JOIN StokKart m WITH(NOLOCK) ON m.SKOD = e.ModelKod
         WHERE em.EmirNo = %s
    """, (EMIR,))
    rows = cur.fetchall()
    print(f"  110626'nin alt YM emirleri: {len(rows)} adet")
    for r in rows:
        print(f"    EmirNo={r[0]}, ModelKod={r[1]!r}, Tip={r[2]!r}, Loc={r[3]!r}")
        print(f"      ModelAdi={(r[5] or '')[:60]!r}")
except Exception as e:
    print(f"  HATA: {e}")


# ============================================================
section(f"3) Urt_Emir 110626 detayi - kendi tipi ne?")
# ============================================================
try:
    cur.execute("""
        SELECT EmirNo, ModelKod, Tip, Location, Durum
          FROM Urt_Emir WITH(NOLOCK)
         WHERE EmirNo = %s
    """, (EMIR,))
    r = cur.fetchone()
    if r:
        print(f"  EmirNo={r[0]}, ModelKod={r[1]!r}, Tip={r[2]!r}, Loc={r[3]!r}, Durum={r[4]!r}")
except Exception as e:
    print(f"  HATA: {e}")


# ============================================================
section(f"4) StokKart 110626 modeli - parca ipucu")
# ============================================================
try:
    cur.execute("""
        SELECT TOP 1 sk.SKOD, sk.Tanim, sk.OzKod1, sk.OzKod2, sk.OzKod3, sk.OzKod4
          FROM Urt_Emir e WITH(NOLOCK)
          LEFT JOIN StokKart sk WITH(NOLOCK) ON sk.SKOD = e.ModelKod
         WHERE e.EmirNo = %s
    """, (EMIR,))
    r = cur.fetchone()
    if r:
        print(f"    SKOD={r[0]!r}")
        print(f"    Tanim={(r[1] or '')[:60]!r}")
        print(f"    OzKod1={r[2]!r}, OzKod2={r[3]!r}, OzKod3={r[4]!r}, OzKod4={r[5]!r}")
except Exception as e:
    print(f"  HATA: {e}")


# ============================================================
section(f"5) Urt_con_gch 110626 - tum prosesler dagilimi")
# ============================================================
try:
    cur.execute("""
        SELECT g.Proses, pm.Tanim, SUM(g.Cikan) AS toplam, COUNT(*) AS kayit
          FROM Urt_con_gch g WITH(NOLOCK)
          LEFT JOIN Proses_M pm WITH(NOLOCK) ON pm.Pro = g.Proses
         WHERE g.EmirNo = %s AND g.Cikan > 0
         GROUP BY g.Proses, pm.Tanim
         ORDER BY g.Proses
    """, (EMIR,))
    rows = cur.fetchall()
    print(f"  Korgun proseslari: {len(rows)} farkli")
    for r in rows:
        print(f"    {r[0]!r}: {r[1]!r} = {int(r[2] or 0)} cift, {r[3]} kayit")
except Exception as e:
    print(f"  HATA: {e}")


# ============================================================
section(f"OZET")
# ============================================================
print("""
Beklenen:
  - Bolum 1: Urt_Em2Em'de 110626 alt YM emirleri var mi?
  - Bolum 2: Varsa hangi modeller (Atki/Govde belli mi?)
  - Bolum 3: 110626 kendisi Tip='M' (Mamul) mi?
  - Bolum 4: StokKart'taki OzKod alanlari ipucu veriyor mu?
  - Bolum 5: Korgun'da 110626 icin tek proses (Kesim) mi yoksa daha fazla mi?

Sonuca gore:
  A) Alt emir VAR: Atki/Govde Urt_Em2Em'den gelir
  B) Alt emir YOK: CPS proseslerinden turetilir
""")

con.close()
