import sqlite3
c = sqlite3.connect(r'C:\cps_dev\mock_data.db')

print('=== BASELINE: 110980 + alt emirler ===')
for r in c.execute("""
    SELECT id, emir_no, proses_adi, siralama, aktif, kaynak
    FROM emir_alt_proses
    WHERE emir_no IN ('110980','110981','110982')
    ORDER BY emir_no, siralama, id
"""):
    print(r)

print()
print('=== Sayim ===')
for r in c.execute("""
    SELECT emir_no, COUNT(1), SUM(CASE WHEN aktif=1 THEN 1 ELSE 0 END)
    FROM emir_alt_proses
    WHERE emir_no IN ('110980','110981','110982')
    GROUP BY emir_no
"""):
    print(r)

c.close()
print('TAMAM')