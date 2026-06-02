# -*- coding: utf-8 -*-
"""
ESLESEN tip (ayni PartiId + ayni Tip icinde hem TAHMINI hem GERCEKLESEN)
olan partileri bulur, en iyi test adaylarini sirayla gosterir.

Kural:
- Iptal = 0 olan kalemler
- Sum(TAHMINI tutar) > 0 VE Sum(GERCEKLESEN tutar) > 0 olan (PartiId, Tip) ikilileri
- Parti basina eslesme sayisi (N adet eslesen tip) hesaplanir
- En fazla eslesen tipe sahip partiler ustte

Cikti:
- Ozet tablo: parti bazinda eslesen tip sayisi
- Detay: her eslesen (parti, tip) icin tahmini & gerceklesen tutarlari
"""

import sqlite3

conn = sqlite3.connect('mock_data.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

# =========================================================
# 1) Eslesen (PartiId, Tip) ikilileri
# =========================================================
c.execute("""
    SELECT
        k.PartiId,
        p.Kod        AS parti_kod,
        p.Baslik     AS parti_baslik,
        p.Durum      AS parti_durum,
        p.ParaBirimi AS parti_para,
        k.Tip,
        SUM(CASE WHEN k.Kaynak='TAHMINI'     THEN k.Tutar ELSE 0 END) AS tahmini,
        SUM(CASE WHEN k.Kaynak='GERCEKLESEN' THEN k.Tutar ELSE 0 END) AS gerceklesen,
        COUNT(CASE WHEN k.Kaynak='TAHMINI'     THEN 1 END) AS t_adet,
        COUNT(CASE WHEN k.Kaynak='GERCEKLESEN' THEN 1 END) AS g_adet
    FROM ithalat_maliyet_kalem k
    JOIN ithalat_parti p ON p.Id = k.PartiId
    WHERE (k.Iptal IS NULL OR k.Iptal = 0)
    GROUP BY k.PartiId, k.Tip
    HAVING tahmini > 0 AND gerceklesen > 0
    ORDER BY k.PartiId DESC, k.Tip
""")
rows = [dict(r) for r in c.fetchall()]

if not rows:
    print("=" * 60)
    print("  SONUC: ESLESEN tip (hem TAHMINI hem GERCEKLESEN) bulunamadi.")
    print("=" * 60)
    print()
    print("Yorum:")
    print("  Hic bir partide ayni tip icin hem proforma (TAHMINI) hem")
    print("  fatura (GERCEKLESEN) kalemleri yok. Bu senaryoyu yaratmak icin:")
    print("  - Bir partiye ONCE Proforma yukle -> FOB TAHMINI gelir")
    print("  - Sonra ayni partiye Commercial Invoice yukle -> FOB GERCEKLESEN gelir")
    print("  - Boylece FOB tipi ESLESEN olur, sapma yuzdesi hesaplanir.")
    conn.close()
    raise SystemExit(0)

# =========================================================
# 2) Parti bazinda eslesen tip sayisi
# =========================================================
parti_ozet = {}
for r in rows:
    pid = r['PartiId']
    if pid not in parti_ozet:
        parti_ozet[pid] = {
            'kod': r['parti_kod'],
            'baslik': (r['parti_baslik'] or '')[:50],
            'durum': r['parti_durum'],
            'para': r['parti_para'],
            'eslesen_tipler': [],
        }
    parti_ozet[pid]['eslesen_tipler'].append(r['Tip'])

# En fazla eslesen tipi olan parti ustte
siralamali = sorted(
    parti_ozet.items(),
    key=lambda x: (-len(x[1]['eslesen_tipler']), -x[0]),
)

# =========================================================
# 3) Yazdir — ozet
# =========================================================
print("=" * 60)
print("  ESLESEN TIP'LI PARTILER (en iyi test adaylari ustte)")
print("=" * 60)
print()
for pid, info in siralamali:
    tip_str = ', '.join(info['eslesen_tipler'])
    print(f"  PartiId={pid}  Kod={info['kod']}  [{info['durum']}, {info['para']}]")
    print(f"    Baslik        : {info['baslik']}")
    print(f"    Eslesen tipler: {tip_str}  ({len(info['eslesen_tipler'])} adet)")
    print()

# =========================================================
# 4) Yazdir — detay (her eslesme icin tahmini/gerceklesen)
# =========================================================
print("=" * 60)
print("  DETAY — her (parti, tip) icin tutarlar")
print("=" * 60)
print()
print(f"  {'PartiId':>7} | {'Kod':<16} | {'Tip':<10} | "
      f"{'Tahmini':>12} | {'Gerceklesen':>12} | {'Adet T/G':>9}")
print("  " + "-" * 90)
for r in rows:
    adet_str = f"{r['t_adet']}/{r['g_adet']}"
    print(f"  {r['PartiId']:>7} | {r['parti_kod']:<16} | {r['Tip']:<10} | "
          f"{r['tahmini']:>12.2f} | {r['gerceklesen']:>12.2f} | {adet_str:>9}")

# =========================================================
# 5) Tavsiye
# =========================================================
print()
print("=" * 60)
print("  TAVSIYE")
print("=" * 60)
best_pid, best_info = siralamali[0]
best_count = len(best_info['eslesen_tipler'])
print(f"\n  En iyi test adayi: PartiId = {best_pid}  ({best_info['kod']})")
print(f"  {best_count} eslesen tip icerir — sapma yuzdesi hesaplanabilir.")
print(f"\n  Tarayicida ac:")
print(f"    http://127.0.0.1:5057/ithalat/parti/{best_pid}")
print(f"\n  Sonra F12 -> Console'da su scripti calistir:")
print(f"    (yine fetch('/api/ithalat/parti/' + {best_pid}) + tip_detay tablosu)")

conn.close()
