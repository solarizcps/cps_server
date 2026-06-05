# -*- coding: utf-8 -*-
"""
Sapma testi: Temizleme yapilan miktarini dusur, sonra sapma kontrolu yap.
"""
import sqlite3

DB = r'C:\cps_dev\mock_data.db'

# 1. Mevcut durumu goster
print("=== ONCESI ===")
c = sqlite3.connect(DB)
cur = c.execute("""
    SELECT proses_kod, yapilan_korgun 
    FROM siparis_proses_durum 
    WHERE siparis_no='33680'
    ORDER BY proses_kod
""")
print("proses_kod | yapilan")
for row in cur.fetchall():
    print(f"  {row[0]:5} | {row[1]}")
c.close()

# 2. Temizleme'yi (proses 35) dusur
print("\n=== TEMIZLEME 10'a dusuruluyor ===")
c = sqlite3.connect(DB)
c.execute("""
    UPDATE siparis_proses_durum 
    SET yapilan_korgun = 10 
    WHERE siparis_no = '33680' AND proses_kod = '35'
""")
c.commit()
c.close()
print("OK")

# 3. Sonrasini goster
print("\n=== SONRASI ===")
c = sqlite3.connect(DB)
cur = c.execute("""
    SELECT proses_kod, yapilan_korgun 
    FROM siparis_proses_durum 
    WHERE siparis_no='33680'
    ORDER BY proses_kod
""")
print("proses_kod | yapilan")
for row in cur.fetchall():
    print(f"  {row[0]:5} | {row[1]}")
c.close()

print("\nTamam. Simdi 'python -m modules.uretim_yonetim.sapma' calistir.")