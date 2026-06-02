# -*- coding: utf-8 -*-
"""
003_enjeksiyon_tablolari.py
============================
FAZ 1 - Enjeksiyon Takip modulu tablolari (CPS 8080).

Olusturulan 7 tablo:
  1. enj_makine          - Makine master (4 satir seed)
  2. enj_kalip           - Kalip master (Excel import icin hazir, bos baslar)
  3. enj_aksama_sebep    - Durus/aksama sebepleri (11 satir seed)
  4. enj_gunluk_rapor    - Gunluk rapor basligi
  5. enj_istasyon_durumu - Hangi istasyonlar acik
  6. enj_saatlik_kayit   - 12 satir saatlik tur/durum
  7. enj_foto            - Tarti + PLC fotolari (gun sonu)

Idempotent: CREATE TABLE IF NOT EXISTS + INSERT OR IGNORE.
Yedek: calistirma aninda mock_data.db.YEDEK_FAZ_ENJ_F1_<ts> alinir.

Calistirma:
  py 003_enjeksiyon_tablolari.py             # migrate
  py 003_enjeksiyon_tablolari.py --rollback  # geri al

Mevcut tablolara DOKUNMAZ.
"""
import os
import sys
import shutil
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(os.path.dirname(BASE_DIR), 'mock_data.db')

TABLOLAR = [
    'enj_makine',
    'enj_kalip',
    'enj_aksama_sebep',
    'enj_gunluk_rapor',
    'enj_istasyon_durumu',
    'enj_saatlik_kayit',
    'enj_foto',
]


def yedek_al():
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    yedek = DB_PATH + '.YEDEK_FAZ_ENJ_F1_' + ts
    shutil.copy2(DB_PATH, yedek)
    print('[YEDEK] ' + os.path.basename(yedek))
    return yedek


def tablolari_olustur(conn):
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS enj_makine (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        kod             TEXT UNIQUE NOT NULL,
        ad              TEXT NOT NULL,
        istasyon_sayisi INTEGER NOT NULL,
        aktif           INTEGER DEFAULT 1,
        sira            INTEGER DEFAULT 0,
        olusturma_tarih TEXT DEFAULT (datetime('now'))
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS enj_kalip (
        id                     INTEGER PRIMARY KEY AUTOINCREMENT,
        kalip_kodu             TEXT UNIQUE NOT NULL,
        model                  TEXT,
        kalip_tipi             TEXT,
        kalip_basi_cift        INTEGER,
        bagli_kalip_varsayilan INTEGER,
        gorsel_yolu            TEXT,
        excel_import_id        TEXT,
        ekstra_json            TEXT,
        aktif                  INTEGER DEFAULT 1,
        olusturma_tarih        TEXT DEFAULT (datetime('now'))
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS enj_aksama_sebep (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        kod      TEXT UNIQUE NOT NULL,
        ad       TEXT NOT NULL,
        kategori TEXT,
        aktif    INTEGER DEFAULT 1,
        sira     INTEGER DEFAULT 0
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS enj_gunluk_rapor (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        tarih                TEXT NOT NULL,
        makine_id            INTEGER NOT NULL REFERENCES enj_makine(id),
        vardiya              TEXT NOT NULL,
        kullanici_id         INTEGER,
        kullanici_adi        TEXT,
        emir_no              TEXT,
        kalip_id             INTEGER REFERENCES enj_kalip(id),
        kalip_no             TEXT,
        renk                 TEXT,
        bagli_kalip_adet     INTEGER,
        kalip_basi_cift      INTEGER,
        yukseklik_mm         REAL,
        bos_agirlik_gr       REAL,
        fire_agirlik_gr      REAL,
        personel_sayisi      INTEGER,
        teorik_cift_tur      INTEGER,
        teorik_cift_gunluk   INTEGER,
        toplam_tur           INTEGER DEFAULT 0,
        toplam_fire_cift     INTEGER DEFAULT 0,
        fire_kg              REAL,
        fire_gr              REAL,
        net_cikan_cift       INTEGER,
        korgun_kapatti_cift  INTEGER,
        fark_cift            INTEGER,
        fire_orani           REAL,
        gun_sonu_notu        TEXT,
        durum                TEXT DEFAULT 'taslak',
        olusturma_tarih      TEXT DEFAULT (datetime('now')),
        son_guncelleme       TEXT DEFAULT (datetime('now')),
        kapanis_tarih        TEXT,
        UNIQUE(tarih, makine_id, vardiya)
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS enj_istasyon_durumu (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        rapor_id    INTEGER NOT NULL REFERENCES enj_gunluk_rapor(id) ON DELETE CASCADE,
        istasyon_no INTEGER NOT NULL,
        aktif       INTEGER DEFAULT 0,
        UNIQUE(rapor_id, istasyon_no)
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS enj_saatlik_kayit (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        rapor_id        INTEGER NOT NULL REFERENCES enj_gunluk_rapor(id) ON DELETE CASCADE,
        saat_baslangic  TEXT NOT NULL,
        saat_bitis      TEXT NOT NULL,
        tur_adet        INTEGER DEFAULT 0,
        durum           TEXT,
        aksama_sebep_id INTEGER REFERENCES enj_aksama_sebep(id),
        aciklama        TEXT,
        olusturma_tarih TEXT DEFAULT (datetime('now')),
        son_guncelleme  TEXT DEFAULT (datetime('now')),
        UNIQUE(rapor_id, saat_baslangic)
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS enj_foto (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        rapor_id       INTEGER NOT NULL REFERENCES enj_gunluk_rapor(id) ON DELETE CASCADE,
        tip            TEXT NOT NULL,
        dosya_yolu     TEXT NOT NULL,
        dosya_ad       TEXT,
        dosya_boyut    INTEGER,
        yukleyen_id    INTEGER,
        aciklama       TEXT,
        yuklenme_tarih TEXT DEFAULT (datetime('now'))
    )""")

    c.execute('CREATE INDEX IF NOT EXISTS idx_enj_rapor_tarih_makine ON enj_gunluk_rapor(tarih, makine_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_enj_rapor_durum ON enj_gunluk_rapor(durum)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_enj_rapor_emir ON enj_gunluk_rapor(emir_no)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_enj_rapor_kullanici ON enj_gunluk_rapor(kullanici_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_enj_saatlik_rapor ON enj_saatlik_kayit(rapor_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_enj_istasyon_rapor ON enj_istasyon_durumu(rapor_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_enj_foto_rapor_tip ON enj_foto(rapor_id, tip)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_enj_aksama_aktif ON enj_aksama_sebep(aktif, sira)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_enj_kalip_aktif ON enj_kalip(aktif)')

    conn.commit()
    print('[OK] 7 tablo + 9 indeks olusturuldu')


def seed_yukle(conn):
    c = conn.cursor()

    makineler = [
        ('M1', '1 MAKINE', 8, 1),
        ('M2', '2 MAKINE', 8, 2),
        ('M3', '3 MAKINE', 6, 3),
        ('M4', '4 MAKINE', 6, 4),
    ]
    for kod, ad, ist, sira in makineler:
        c.execute('INSERT OR IGNORE INTO enj_makine (kod, ad, istasyon_sayisi, sira) VALUES (?, ?, ?, ?)',
                  (kod, ad, ist, sira))

    sebepler = [
        ('yemek_molasi',       'YEMEK MOLASI',        'mola',     1),
        ('cay_molasi',         'CAY MOLASI',          'mola',     2),
        ('vardiya_devir',      'VARDIYA DEVRI',       'mola',     3),
        ('kalip_temizligi',    'KALIP TEMIZLIGI',     'temizlik', 4),
        ('kalip_degisimi',     'KALIP DEGISIMI',      'kurulum',  5),
        ('kalip_arizasi',      'KALIP ARIZASI',       'ariza',    6),
        ('makine_arizasi',     'MAKINE ARIZASI',      'ariza',    7),
        ('elektrik_kesintisi', 'ELEKTRIK KESINTISI',  'ariza',    8),
        ('hammadde_bekleme',   'HAMMADDE BEKLEME',    'lojistik', 9),
        ('bakim',              'PERIYODIK BAKIM',     'bakim',   10),
        ('diger',              'DIGER',               'diger',   99),
    ]
    for kod, ad, kategori, sira in sebepler:
        c.execute('INSERT OR IGNORE INTO enj_aksama_sebep (kod, ad, kategori, sira) VALUES (?, ?, ?, ?)',
                  (kod, ad, kategori, sira))

    conn.commit()
    print('[OK] Seed yuklendi: 4 makine + 11 aksama sebep')


def dogrula(conn):
    c = conn.cursor()
    print('\n[DOGRULAMA - yeni enj_ tablolari]')
    for t in TABLOLAR:
        say = c.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0]
        kolon_say = len(c.execute('PRAGMA table_info(' + t + ')').fetchall())
        print('  {:30s} -> {:2d} kolon, {:3d} kayit'.format(t, kolon_say, say))

    print('\n[DOGRULAMA - mevcut tablolar (degismedi)]')
    for t in ('sistem_kullanici', 'sistem_rol', 'uretim_kayit', 'proses_kategori', 'usta_gorevleri'):
        try:
            kolon_say = len(c.execute('PRAGMA table_info(' + t + ')').fetchall())
            say = c.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0]
            print('  {:30s} -> {:2d} kolon, {:5d} kayit (DOKUNULMADI)'.format(t, kolon_say, say))
        except sqlite3.OperationalError:
            print('  {:30s} -> (tablo yok, atlandi)'.format(t))


def rollback(conn):
    c = conn.cursor()
    print('\n[ROLLBACK MODU]')
    for t in reversed(TABLOLAR):
        c.execute('DROP TABLE IF EXISTS ' + t)
        print('  [SIL] ' + t)
    conn.commit()
    print('[OK] Tum enj_ tablolari silindi. Mevcut sistem etkilenmedi.')


def main():
    if not os.path.exists(DB_PATH):
        print('[HATA] DB bulunamadi: ' + DB_PATH)
        sys.exit(1)

    rollback_mode = '--rollback' in sys.argv

    print('=' * 60)
    print('003_enjeksiyon_tablolari.py - FAZ 1')
    print('=' * 60)
    print('[DB] ' + DB_PATH)
    yedek_al()

    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA foreign_keys = ON')

    try:
        if rollback_mode:
            rollback(conn)
        else:
            print('\n[MOD] MIGRATE')
            tablolari_olustur(conn)
            seed_yukle(conn)
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
