import sqlite3
c = sqlite3.connect(r'C:\cps_dev\mock_data.db')

print('=== En son 20 kayit (id DESC) ===')
for r in c.execute("""
    SELECT id, emir_no, proses_adi, siralama, aktif, kaynak, created_at
    FROM emir_alt_proses
    ORDER BY id DESC
    LIMIT 20
"""):
    print(r)

print()
print('=== Bugunun aktif kayitlari ===')
for r in c.execute("""
    SELECT id, emir_no, proses_adi, aktif, kaynak, created_at
    FROM emir_alt_proses
    WHERE aktif = 1
    ORDER BY id DESC
    LIMIT 20
"""):
    print(r)

c.close()
print('TAMAM')