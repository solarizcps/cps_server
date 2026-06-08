"""
Migration 028 — FAZ2G-8C
personel_kullanici tablosuna iletişim alanları ekle:
  - Adres TEXT
  - AcilIletisim TEXT

İdempotent: ALTER TABLE sadece kolon yoksa çalışır.
Mevcut veri değişmez.
"""
import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    con = sqlite3.connect(DB_PATH)
    try:
        mevcut = [r[1] for r in con.execute('PRAGMA table_info(personel_kullanici)').fetchall()]

        eklemeler = []
        if 'Adres' not in mevcut:
            con.execute('ALTER TABLE personel_kullanici ADD COLUMN Adres TEXT')
            eklemeler.append('Adres')
        if 'AcilIletisim' not in mevcut:
            con.execute('ALTER TABLE personel_kullanici ADD COLUMN AcilIletisim TEXT')
            eklemeler.append('AcilIletisim')

        con.commit()

        if eklemeler:
            print(f'[028] Eklendi: {", ".join(eklemeler)}')
        else:
            print('[028] Kolonlar zaten mevcut — atlandı.')
    finally:
        con.close()


if __name__ == '__main__':
    run()
