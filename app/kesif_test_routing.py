import sqlite3
c = sqlite3.connect(r'C:\cps_dev\mock_data.db')

print('=== emir_alt_proses: 110626 + alt emirler ===')
for r in c.execute("""
    SELECT id, emir_no, proses_adi, siralama, aktif, kaynak
    FROM emir_alt_proses
    WHERE emir_no IN ('110626','110648','110649')
    ORDER BY emir_no, siralama, id
"""):
    print(r)

print()
print('=== Aktif kayit sayilari ===')
for r in c.execute("""
    SELECT emir_no, COUNT(1) AS toplam,
           SUM(CASE WHEN aktif=1 THEN 1 ELSE 0 END) AS aktif_say
    FROM emir_alt_proses
    WHERE emir_no IN ('110626','110648','110649')
    GROUP BY emir_no
    ORDER BY emir_no
"""):
    print(r)

c.close()
print('TAMAM')