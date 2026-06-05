import sqlite3
c = sqlite3.connect(r'C:\cps_dev\mock_data.db')

print('=== 110649 TUM kayitlar (aktif/pasif) ===')
for r in c.execute("SELECT id, emir_no, proses_adi, siralama, aktif, kaynak FROM emir_alt_proses WHERE emir_no='110649' ORDER BY id"):
    print(r)

print()
print('=== Sayim ===')
for r in c.execute("SELECT aktif, COUNT(1) FROM emir_alt_proses WHERE emir_no='110649' GROUP BY aktif"):
    print(r)

c.close()
print('TAMAM')