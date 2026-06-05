import sqlite3

conn = sqlite3.connect('mock_data.db')
c = conn.cursor()

print("=== BILIR / SEBS BELGELERI ===")
c.execute("""
    SELECT
        sb.Id AS belge_id,
        sb.BelgeTipi,
        sb.OrijinalAd,
        sb.YuklemeTarih,
        ibp.ParseDurum,
        ibp.ParseMesaj,
        ibp.UygulananKalemSayisi,
        ibp.KaynakBelgeRef
    FROM sistem_belge sb
    LEFT JOIN ithalat_belge_parse ibp ON ibp.BelgeId = sb.Id
    WHERE LOWER(sb.OrijinalAd) LIKE '%bilir%'
       OR LOWER(sb.OrijinalAd) LIKE '%sebs%'
       OR LOWER(sb.OrijinalAd) LIKE '%nexgen%'
    ORDER BY sb.Id DESC
    LIMIT 20
""")
rows = c.fetchall()
if not rows:
    print("  Eslesme yok")
else:
    for r in rows:
        print(f"  belge_id={r[0]}")
        print(f"    tipi      = {r[1]}")
        print(f"    dosya     = {r[2]}")
        print(f"    yukleme   = {r[3]}")
        print(f"    durum     = {r[4]}")
        print(f"    mesaj     = {r[5]}")
        print(f"    kalem_say = {r[6]}")
        print(f"    ref       = {r[7]}")
        print("  ---")

print("\n=== SON 10 PARSE KAYDI ===")
c.execute("""
    SELECT
        ibp.BelgeId,
        sb.OrijinalAd,
        ibp.BelgeTipi,
        ibp.ParseDurum,
        ibp.UygulananKalemSayisi
    FROM ithalat_belge_parse ibp
    LEFT JOIN sistem_belge sb ON sb.Id = ibp.BelgeId
    ORDER BY ibp.Id DESC
    LIMIT 10
""")
for r in c.fetchall():
    print(f"  id={r[0]}  dosya={r[1]}  tipi={r[2]}  durum={r[3]}  kalem={r[4]}")

conn.close()
