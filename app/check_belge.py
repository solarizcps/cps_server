import sqlite3

conn = sqlite3.connect('mock_data.db')
c = conn.cursor()

# Bilir belgesi
print("=== BLR2026000001103 ===")
c.execute("""
    SELECT belge_id, belge_tipi, parse_durumu, belge_ref, dosya_adi
    FROM ithalat_belge
    WHERE belge_ref LIKE '%BLR2026000001103%'
       OR dosya_adi LIKE '%bilir%'
    ORDER BY belge_id DESC
""")
rows = c.fetchall()
if not rows:
    print("Kayit yok — belge_ref veya dosya_adi ile eslesme yok")
else:
    for r in rows:
        print(f"  belge_id={r[0]}  tipi={r[1]}  durum={r[2]}  ref={r[3]}  dosya={r[4]}")

# Son 10 belge genel bakis
print("\n=== SON 10 BELGE ===")
c.execute("""
    SELECT belge_id, belge_tipi, parse_durumu, dosya_adi
    FROM ithalat_belge
    ORDER BY belge_id DESC
    LIMIT 10
""")
for r in c.fetchall():
    print(f"  id={r[0]}  tipi={r[1]}  durum={r[2]}  dosya={r[3]}")

conn.close()
