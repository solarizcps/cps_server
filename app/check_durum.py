import sqlite3
c = sqlite3.connect('mock_data.db')
c.row_factory = sqlite3.Row

tablolar = [t[0] for t in c.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
).fetchall()]
print("Tablolar:", tablolar)
print()

aktif = c.execute(
    "SELECT COUNT(*) FROM ithalat_maliyet_kalem WHERE (Iptal IS NULL OR Iptal = 0)"
).fetchone()[0]
iptal = c.execute(
    "SELECT COUNT(*) FROM ithalat_maliyet_kalem WHERE Iptal = 1"
).fetchone()[0]
print(f"Aktif kalem:    {aktif}")
print(f"Iptal kalem:    {iptal}")

uygulandi = c.execute(
    "SELECT COUNT(*) FROM ithalat_belge_parse WHERE ParseDurum = 'UYGULANDI'"
).fetchone()[0]
bos = c.execute(
    "SELECT COUNT(*) FROM ithalat_belge_parse WHERE ParseDurum = 'UYGULANDI_BOS'"
).fetchone()[0]
print(f"UYGULANDI:      {uygulandi}")
print(f"UYGULANDI_BOS:  {bos}")

print("\nUYGULANDI_BOS kayitlari:")
for r in c.execute("""
    SELECT Id, BelgeId, PartiId, BelgeTipi, KaynakBelgeRef
    FROM ithalat_belge_parse
    WHERE ParseDurum = 'UYGULANDI_BOS'
    ORDER BY PartiId, BelgeId
""").fetchall():
    print(f"  Parti={r['PartiId']} BelgeId={r['BelgeId']} Tip={r['BelgeTipi']} Ref={r['KaynakBelgeRef']}")

print("\nParti bazinda aktif kalem:")
for r in c.execute("""
    SELECT PartiId, COUNT(*) AS Adet
    FROM ithalat_maliyet_kalem
    WHERE (Iptal IS NULL OR Iptal = 0)
    GROUP BY PartiId
    ORDER BY PartiId
""").fetchall():
    print(f"  Parti #{r['PartiId']}: {r['Adet']} aktif kalem")