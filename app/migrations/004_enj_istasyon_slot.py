# -*- coding: utf-8 -*-
"""004_enj_istasyon_slot.py - FAZ 6.5

enj_istasyon_durumu tablosuna 'slot' kolonu ekle (A/B).

Tablo bos oldugu icin DROP + CREATE guvenli.
Yeni schema:
  - slot TEXT NOT NULL CHECK (slot IN ('A','B'))
  - UNIQUE(rapor_id, istasyon_no, slot)

Yedek    : mock_data.db.YEDEK_FAZ_ENJ_F65_<ts>
Rollback : --rollback ile eski (slot'suz) tabloyu geri kurar.
"""
import os
import sys
import shutil
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(os.path.dirname(BASE_DIR), 'mock_data.db')


def yedek_al():
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    yedek = DB_PATH + '.YEDEK_FAZ_ENJ_F65_' + ts
    shutil.copy2(DB_PATH, yedek)
    print('[YEDEK] ' + os.path.basename(yedek))
    return yedek


def migrate(conn):
    c = conn.cursor()
    say = c.execute('SELECT COUNT(*) FROM enj_istasyon_durumu').fetchone()[0]
    if say > 0:
        print('[HATA] enj_istasyon_durumu tablosu BOS DEGIL: %d kayit' % say)
        print('       DROP+CREATE veri kaybi anlamina gelir. Manuel mudahale gerekli.')
        sys.exit(1)
    print('[1/3] Eski tablo DROP ediliyor (bos, guvenli)...')
    c.execute('DROP INDEX IF EXISTS idx_enj_istasyon_rapor')
    c.execute('DROP TABLE IF EXISTS enj_istasyon_durumu')
    print('[2/3] Yeni tablo CREATE (slot kolonu eklendi)...')
    c.execute("""
    CREATE TABLE enj_istasyon_durumu (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        rapor_id    INTEGER NOT NULL REFERENCES enj_gunluk_rapor(id) ON DELETE CASCADE,
        istasyon_no INTEGER NOT NULL,
        slot        TEXT NOT NULL CHECK (slot IN ('A', 'B')),
        aktif       INTEGER DEFAULT 0,
        UNIQUE(rapor_id, istasyon_no, slot)
    )
    """)
    print('[3/3] Index olusturuluyor...')
    c.execute('CREATE INDEX idx_enj_istasyon_rapor ON enj_istasyon_durumu(rapor_id)')
    c.execute('CREATE INDEX idx_enj_istasyon_slot ON enj_istasyon_durumu(rapor_id, istasyon_no, slot)')
    conn.commit()
    print('[OK] Schema guncellendi')


def rollback(conn):
    c = conn.cursor()
    say = c.execute('SELECT COUNT(*) FROM enj_istasyon_durumu').fetchone()[0]
    if say > 0:
        print('[HATA] Tablo BOS DEGIL: %d kayit. Rollback iptal.' % say)
        sys.exit(1)
    print('[1/2] Yeni tablo DROP ediliyor...')
    c.execute('DROP INDEX IF EXISTS idx_enj_istasyon_rapor')
    c.execute('DROP INDEX IF EXISTS idx_enj_istasyon_slot')
    c.execute('DROP TABLE IF EXISTS enj_istasyon_durumu')
    print('[2/2] Eski tablo CREATE (slot YOK)...')
    c.execute("""
    CREATE TABLE enj_istasyon_durumu (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        rapor_id    INTEGER NOT NULL REFERENCES enj_gunluk_rapor(id) ON DELETE CASCADE,
        istasyon_no INTEGER NOT NULL,
        aktif       INTEGER DEFAULT 0,
        UNIQUE(rapor_id, istasyon_no)
    )
    """)
    c.execute('CREATE INDEX idx_enj_istasyon_rapor ON enj_istasyon_durumu(rapor_id)')
    conn.commit()
    print('[OK] Eski schema geri yuklendi')


def dogrula(conn):
    c = conn.cursor()
    cols = c.execute('PRAGMA table_info(enj_istasyon_durumu)').fetchall()
    print('\n[DOGRULAMA] enj_istasyon_durumu kolonlari:')
    for col in cols:
        print('  [%d] %-12s %s%s' % (col[0], col[1], col[2], ' NOT NULL' if col[3] else ''))
    idx = c.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='enj_istasyon_durumu' AND name NOT LIKE 'sqlite_%'").fetchall()
    print('\n  Index sayisi: %d' % len(idx))
    for i in idx:
        print('    - %s' % i[0])


def main():
    if not os.path.exists(DB_PATH):
        print('[HATA] DB bulunamadi: ' + DB_PATH)
        sys.exit(1)
    rb = '--rollback' in sys.argv
    print('=' * 60)
    print('004_enj_istasyon_slot.py - FAZ 6.5')
    print('=' * 60)
    print('[DB] ' + DB_PATH)
    print('[MOD] ' + ('ROLLBACK' if rb else 'MIGRATE'))
    yedek_al()
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA foreign_keys = ON')
    try:
        if rb:
            rollback(conn)
        else:
            migrate(conn)
        dogrula(conn)
        print('\n' + '=' * 60)
        print('[TAMAM] Migration basarili.')
        print('=' * 60)
    except Exception as e:
        print('[HATA] ' + str(e))
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
