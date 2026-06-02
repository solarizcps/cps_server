import sqlite3
c = sqlite3.connect(r'C:\cps_dev\mock_data.db')

print('=== emir_alt_proses 110626 + alt ===')
for r in c.execute("SELECT id, emir_no, proses_adi, siralama, aktif, kaynak FROM emir_alt_proses WHERE emir_no IN ('110626','110648','110649') ORDER BY emir_no, siralama, id"):
    print(r)

print()
print('=== uretim_kayit dagilim ===')
for r in c.execute("SELECT emir_no, proses_kodu, proses_adi, onay_durum, COUNT(1), SUM(miktar) FROM uretim_kayit WHERE emir_no IN (110626, 110648, 110649) GROUP BY emir_no, proses_kodu, proses_adi, onay_durum ORDER BY emir_no, proses_kodu"):
    print(r)

print()
print('=== TUM 110626 emir_alt_proses kaynak dagilimi ===')
for r in c.execute("SELECT kaynak, COUNT(1) FROM emir_alt_proses WHERE emir_no='110626' GROUP BY kaynak"):
    print(r)

c.close()
