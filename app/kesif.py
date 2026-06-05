import sqlite3
c = sqlite3.connect(r'C:\cps_dev\mock_data.db')

print('=== SCHEMA: emir_alt_proses ===')
for r in c.execute("SELECT sql FROM sqlite_master WHERE name='emir_alt_proses'"):
    print(r[0])

print()
print('=== SCHEMA: uretim_kayit ===')
for r in c.execute("SELECT sql FROM sqlite_master WHERE name='uretim_kayit'"):
    print(r[0])

print()
print('=== emir_alt_proses 110626 + alt ===')
for r in c.execute("SELECT id, emir_no, proses_kodu, proses_adi, aktif FROM emir_alt_proses WHERE emir_no IN ('110626','110648','110649') ORDER BY emir_no, id"):
    print(r)

print()
print('=== uretim_kayit dagilim ===')
for r in c.execute("SELECT emir_no, proses_kodu, proses_adi, onay_durum, COUNT(1), SUM(miktar) FROM uretim_kayit WHERE emir_no IN (110626, 110648, 110649) GROUP BY emir_no, proses_kodu, proses_adi, onay_durum ORDER BY emir_no, proses_kodu"):
    print(r)

c.close()
