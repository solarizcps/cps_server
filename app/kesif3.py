import sqlite3
c = sqlite3.connect(r'C:\cps_dev\mock_data.db')
print('=== SABLONLAR ===')
for r in c.execute("SELECT id, sablon_adi, aktif FROM sablon ORDER BY id"):
    print(r)
print()
print('=== SABLON_PROSES ===')
for r in c.execute("SELECT s.sablon_adi, sp.siralama, sp.proses_adi FROM sablon_proses sp JOIN sablon s ON s.id=sp.sablon_id WHERE s.aktif=1 ORDER BY s.id, sp.siralama"):
    print(r)
c.close()
