# -*- coding: utf-8 -*-
"""
Mock veriyi gercek Korgun siparisine uydur.
"""
import sqlite3

DB = r'C:\cps_dev\mock_data.db'

c = sqlite3.connect(DB)
cur = c.cursor()

# 33680 icin dogru veri (Korgun ekranindan)
cur.execute("""
    UPDATE siparis_darbogaz
    SET musteri = 'Sahin Taban ve Ayakkabicilik',
        hedef_toplam = 1200
    WHERE siparis_no = '33680'
""")
c.commit()

# Dogrula
cur.execute("SELECT siparis_no, model_kod, musteri, hedef_toplam FROM siparis_darbogaz WHERE siparis_no = '33680'")
print("Guncel kayit:")
for row in cur.fetchall():
    print(f"  Siparis: {row[0]}")
    print(f"  Model:   {row[1]}")
    print(f"  Musteri: {row[2]}")
    print(f"  Hedef:   {row[3]} cift")

c.close()
print("\nTamam.")