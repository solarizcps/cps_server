import sqlite3
c = sqlite3.connect(r'C:\cps_dev\mock_data.db')

# Once goster
print('=== ONCESI: 110626 aktif kayitlar ===')
for r in c.execute("SELECT id, proses_adi, kaynak, aktif FROM emir_alt_proses WHERE emir_no='110626' ORDER BY id"):
    print(r)

# Pasiflestir
cur = c.execute("UPDATE emir_alt_proses SET aktif=0 WHERE emir_no='110626' AND aktif=1")
etkilenen = cur.rowcount
c.commit()

print()
print(f'PASIFLESTIRILDI: {etkilenen} kayit')
print()
print('=== SONRASI: 110626 aktif kayitlar ===')
for r in c.execute("SELECT id, proses_adi, kaynak, aktif FROM emir_alt_proses WHERE emir_no='110626'"):
    print(r)
print('(yukarida hepsi aktif=0 olmali)')

c.close()
