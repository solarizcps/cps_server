# -*- coding: utf-8 -*-
"""
SOLARIZ CPS - FAZ 1 Tablo Kurulumu
faz1_tablolar.sql dosyasini mock_data.db'ye uygular
"""
import sqlite3
import os

DB_PATH = r'C:\cps_dev\mock_data.db'
SQL_PATH = r'C:\cps_dev\faz1_tablolar.sql'

print(f"DB: {DB_PATH}")
print(f"SQL: {SQL_PATH}")

if not os.path.exists(SQL_PATH):
    print(f"HATA: SQL dosyasi bulunamadi: {SQL_PATH}")
    exit(1)

# SQL dosyasini oku
with open(SQL_PATH, 'r', encoding='utf-8') as f:
    sql_script = f.read()

# DB baglan ve calistir
conn = sqlite3.connect(DB_PATH)
try:
    conn.executescript(sql_script)
    conn.commit()
    print("OK: Tablolar olusturuldu, seed data yuklendi.")
    
    # Dogrulama: tablolari listele
    print("\nMevcut tablolar:")
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    for row in cur.fetchall():
        print(f"  - {row[0]}")
    
    # Faz 1 tablolarini ozellikle kontrol et
    print("\nFAZ 1 tablolarinda kayit sayilari:")
    faz1_tablolar = [
        'proses_kategori',
        'proses_usta_atama',
        'siparis_proses_durum',
        'siparis_darbogaz',
        'sapma_olay',
        'usta_kilit_durum',
        'usta_aksiyon',
        'planlama_karar',
        'vardiya_devir_log',
    ]
    for t in faz1_tablolar:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            sayi = cur.fetchone()[0]
            print(f"  {t}: {sayi} kayit")
        except Exception as e:
            print(f"  {t}: HATA - {e}")
            
except Exception as e:
    print(f"HATA: {e}")
    conn.rollback()
finally:
    conn.close()

print("\nBitti.")