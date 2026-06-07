# -*- coding: utf-8 -*-
"""
Migration: 023_personel_yetkinlik_master
Tarih: 2026-06-07
Faz: CORE_PERSONEL_360_FAZ2C-2

Amac:
  Personel 360 Yetkinlik Sistemi icin iki yeni tablo ve seed verisi.
  Hicbir mevcut tabloya dokunulmaz (ALTER/UPDATE/DELETE yok).

Tablolar:
  1. yetkinlik_master  — yetkinlik sozlugu (9 seed kaydi)
  2. kullanici_yetkinlik — personel yetkinlik atamalari (ilk seed yok)

DOKUNULMAZ:
  - ENJ_CORE tablolari (enj_*)
  - Finans, Planlama dosyalari
  - kullanici_profil, kullanici_proses, usta_personel_iliskisi
  - sistem_kullanici, sistem_rol, sistem_yetki, sistem_rol_yetki
  - Template / route dosyalari

Kullanim:
  python 023_personel_yetkinlik_master.py          -> dry-run (varsayilan)
  python 023_personel_yetkinlik_master.py --apply  -> gercek uygulama (SADECE onay sonrasi)

Idempotent:
  CREATE TABLE IF NOT EXISTS + INSERT OR IGNORE — ayni script tekrar calistirilabilir.

Rollback:
  Backup: C:\\CPS_BACKUPS\\mock_data_BEFORE_FAZ2C2_YETKINLIK_<timestamp>.db
  Geri yukle: yedegi app/mock_data.db uzerine kopyala.
"""

import argparse
import sqlite3
import os
import sys
import io
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
MIGRATION_VERSION = '023'
MIGRATION_DESC = '023_personel_yetkinlik_master - FAZ2C-2: yetkinlik_master + kullanici_yetkinlik tablolari'

# ─── DDL ─────────────────────────────────────────────────────────────────────

DDL_YETKINLIK_MASTER = """
CREATE TABLE IF NOT EXISTS yetkinlik_master (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kod         TEXT    NOT NULL UNIQUE,
    ad          TEXT    NOT NULL,
    kategori    TEXT    NOT NULL DEFAULT 'uretim',
    aciklama    TEXT,
    proses_id   INTEGER REFERENCES proses_master_ref(id),
    aktif       INTEGER NOT NULL DEFAULT 1,
    sira        INTEGER NOT NULL DEFAULT 99,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
)
"""

DDL_KULLANICI_YETKINLIK = """
CREATE TABLE IF NOT EXISTS kullanici_yetkinlik (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    kullanici_profil_id   INTEGER NOT NULL REFERENCES kullanici_profil(id),
    yetkinlik_id          INTEGER NOT NULL REFERENCES yetkinlik_master(id),
    seviye                TEXT    NOT NULL DEFAULT 'aday',
    puan                  INTEGER,
    durum                 TEXT    NOT NULL DEFAULT 'onerilen',
    kaynak                TEXT    NOT NULL DEFAULT 'manuel',
    onaylayan_profil_id   INTEGER REFERENCES kullanici_profil(id),
    guncelleme_notu       TEXT,
    baslangic_tarihi      TEXT    NOT NULL DEFAULT (date('now')),
    bitis_tarihi          TEXT,
    aktif                 INTEGER NOT NULL DEFAULT 1,
    created_at            TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at            TEXT    NOT NULL DEFAULT (datetime('now'))
)
"""

DDL_INDEXES = [
    # Aktif profil-yetkinlik cakismasini engelle
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_kyd_profil_yetkinlik_aktif
       ON kullanici_yetkinlik(kullanici_profil_id, yetkinlik_id)
       WHERE aktif = 1""",
    # Personel 360 detay sorgusu
    """CREATE INDEX IF NOT EXISTS idx_kyd_profil
       ON kullanici_yetkinlik(kullanici_profil_id, aktif)""",
    # Yetkinlik bazli sorgulama
    """CREATE INDEX IF NOT EXISTS idx_kyd_yetkinlik
       ON kullanici_yetkinlik(yetkinlik_id, aktif)""",
    # Onaylayan sorgulama
    """CREATE INDEX IF NOT EXISTS idx_kyd_onaylayan
       ON kullanici_yetkinlik(onaylayan_profil_id)""",
    # Master proses baglantisi
    """CREATE INDEX IF NOT EXISTS idx_ykm_proses
       ON yetkinlik_master(proses_id, aktif)""",
]

# ─── Seed ────────────────────────────────────────────────────────────────────
# proses_id sutunu: proses_master_ref'te karsiligi olan kodlar icin DB'den alinir.
# Karsiligi olmayanlar (regola, capak, tampon, rivet, kalip_baglama) NULL olarak eklenir.

SEED_YETKINLIKLER = [
    # (kod,            ad,                kategori,  proses_kod_ref,    sira)
    ('enjeksiyon',    'Enjeksiyon',       'uretim',  'enjeksiyon',      10),
    ('monta',         'Monta',            'uretim',  'monta',           20),
    ('temizleme',     'Temizleme',        'uretim',  'temizleme',       30),
    ('regola',        'Regola',           'uretim',  None,              40),
    ('kesim',         'Kesim',            'uretim',  'kesim',           50),
    ('capak',         'Capak',            'uretim',  None,              60),
    ('tampon',        'Tampon',           'uretim',  None,              70),
    ('rivet',         'Rivet',            'uretim',  None,              80),
    ('kalip_baglama', 'Kalip Baglama',    'uretim',  None,              90),
]


# ─── Yardimci ─────────────────────────────────────────────────────────────────

def sep():
    print('─' * 60)

def h(baslik):
    print(f'\n{"="*60}')
    print(f'  {baslik}')
    print(f'{"="*60}')

def ok(msg):
    print(f'  [OK ]  {msg}')

def warn(msg):
    print(f'  [WARN] {msg}')

def dry(msg):
    print(f'  [DRY]  {msg}')

def appl(msg):
    print(f'  [APPLY]{msg}')

def skip(msg):
    print(f'  [SKIP] {msg}')


def get_conn(readonly=False):
    if readonly:
        con = sqlite3.connect(f'file:{os.path.abspath(DB_PATH)}?mode=ro', uri=True)
    else:
        con = sqlite3.connect(DB_PATH)
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA foreign_keys=ON')
    con.row_factory = sqlite3.Row
    return con


def tablo_var_mi(con, tablo_adi):
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (tablo_adi,)
    ).fetchone()
    return row is not None


def migration_uygulandi_mi(con):
    try:
        row = con.execute(
            "SELECT version FROM schema_migrations WHERE version=?",
            (MIGRATION_VERSION,)
        ).fetchone()
        return row is not None
    except Exception:
        return False


def proses_id_bul(con, proses_kod):
    if proses_kod is None:
        return None
    row = con.execute(
        "SELECT id FROM proses_master_ref WHERE kod=? AND aktif=1",
        (proses_kod,)
    ).fetchone()
    return row['id'] if row else None


# ─── DRY-RUN ─────────────────────────────────────────────────────────────────

def run_dryrun():
    print()
    print('╔══════════════════════════════════════════════════════╗')
    print('║  023 FAZ2C-2 YETKINLIK MASTER — DRY-RUN              ║')
    print('╚══════════════════════════════════════════════════════╝')
    print(f'  Tarih  : {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'  DB     : {DB_PATH}')
    print()

    con = get_conn(readonly=True)

    h('ADIM 0 — Onceki migration kontrolu')
    if migration_uygulandi_mi(con):
        warn(f"Migration '{MIGRATION_VERSION}' zaten schema_migrations'ta kayitli. Tekrar uygulanmayacak.")
    else:
        ok(f"Migration '{MIGRATION_VERSION}' henuz uygulanmamis. Uygulama yapilabilir.")

    h('ADIM 1 — yetkinlik_master tablosu')
    if tablo_var_mi(con, 'yetkinlik_master'):
        skip("yetkinlik_master zaten mevcut — CREATE atlanacak")
        mevcut = con.execute("SELECT COUNT(*) FROM yetkinlik_master").fetchone()[0]
        ok(f"Mevcut kayit sayisi: {mevcut}")
    else:
        dry("yetkinlik_master tablosu OLUSTURULACAK")
        dry("  CREATE TABLE IF NOT EXISTS yetkinlik_master (...)")

    h('ADIM 2 — kullanici_yetkinlik tablosu')
    if tablo_var_mi(con, 'kullanici_yetkinlik'):
        skip("kullanici_yetkinlik zaten mevcut — CREATE atlanacak")
        mevcut = con.execute("SELECT COUNT(*) FROM kullanici_yetkinlik").fetchone()[0]
        ok(f"Mevcut kayit sayisi: {mevcut}")
    else:
        dry("kullanici_yetkinlik tablosu OLUSTURULACAK")
        dry("  CREATE TABLE IF NOT EXISTS kullanici_yetkinlik (...)")

    h('ADIM 3 — Index\'ler')
    for idx_sql in DDL_INDEXES:
        idx_adi = idx_sql.split('INDEX IF NOT EXISTS')[1].strip().split()[0]
        idx_var = con.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (idx_adi,)
        ).fetchone()
        if idx_var:
            skip(f"{idx_adi} zaten mevcut")
        else:
            dry(f"{idx_adi} OLUSTURULACAK")

    h('ADIM 4 — Seed: yetkinlik_master')
    for kod, ad, kategori, proses_kod_ref, sira in SEED_YETKINLIKLER:
        proses_id = proses_id_bul(con, proses_kod_ref)
        if tablo_var_mi(con, 'yetkinlik_master'):
            mevcut = con.execute(
                "SELECT id FROM yetkinlik_master WHERE kod=?", (kod,)
            ).fetchone()
            if mevcut:
                skip(f"'{kod}' zaten mevcut (id={mevcut['id']}) — INSERT OR IGNORE atlanacak")
                continue
        proses_bilgi = f"proses_id={proses_id}" if proses_id else "proses_id=NULL"
        dry(f"INSERT OR IGNORE: kod='{kod}', ad='{ad}', sira={sira}, {proses_bilgi} — EKLENECEK")

    h('ADIM 5 — Korunan tablolar kontrolu')
    KORUNAN = [
        'enj_gunluk_rapor', 'enj_saatlik_kayit', 'enj_ab_setup', 'enj_kalip',
        'kullanici_profil', 'kullanici_proses', 'usta_personel_iliskisi',
        'sistem_kullanici', 'sistem_rol_yetki',
    ]
    for tablo in KORUNAN:
        mevcut_count = con.execute(f"SELECT COUNT(*) FROM {tablo}").fetchone()[0]
        ok(f"{tablo}: {mevcut_count} kayit — DOKUNULMADI")

    h('DRY-RUN OZET')
    print()
    print('  === --apply ILE UYGULANACAKLAR ===')
    if not tablo_var_mi(con, 'yetkinlik_master'):
        print('  CREATE  yetkinlik_master')
    if not tablo_var_mi(con, 'kullanici_yetkinlik'):
        print('  CREATE  kullanici_yetkinlik')
    print(f'  CREATE  {len(DDL_INDEXES)} index (IF NOT EXISTS)')
    for kod, ad, *_ in SEED_YETKINLIKLER:
        print(f'  SEED    yetkinlik_master: {kod} / {ad}')
    print()
    print('  === KESINLIKLE YAPILMAYACAKLAR ===')
    print('  - Mevcut tablolara ALTER yok')
    print('  - Mevcut dataya UPDATE/DELETE yok')
    print('  - ENJ_CORE tablolari: DOKUNULMAZ')
    print('  - Finans, Planlama: DOKUNULMAZ')
    print('  - kullanici_proses: DOKUNULMAZ')
    print('  - kullanici_yetkinlik SEED: ilk fazda YOK (sadece master seed)')
    print()
    print('  Uygulamak icin: python 023_personel_yetkinlik_master.py --apply')
    print()

    con.close()


# ─── APPLY ───────────────────────────────────────────────────────────────────

def run_apply():
    print()
    print('╔══════════════════════════════════════════════════════╗')
    print('║  023 FAZ2C-2 YETKINLIK MASTER — APPLY                ║')
    print('╚══════════════════════════════════════════════════════╝')
    print(f'  Tarih  : {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'  DB     : {DB_PATH}')
    print()

    con = get_conn(readonly=False)
    try:
        if migration_uygulandi_mi(con):
            warn(f"Migration '{MIGRATION_VERSION}' zaten uygulanmis. Cikiliyor.")
            con.close()
            return

        h('ADIM 1 — yetkinlik_master tablosu')
        con.execute(DDL_YETKINLIK_MASTER)
        appl(" yetkinlik_master CREATE TABLE IF NOT EXISTS — tamamlandi")

        h('ADIM 2 — kullanici_yetkinlik tablosu')
        con.execute(DDL_KULLANICI_YETKINLIK)
        appl(" kullanici_yetkinlik CREATE TABLE IF NOT EXISTS — tamamlandi")

        h('ADIM 3 — Indexler')
        for idx_sql in DDL_INDEXES:
            idx_adi = idx_sql.split('INDEX IF NOT EXISTS')[1].strip().split()[0]
            con.execute(idx_sql)
            appl(f" {idx_adi} — tamamlandi")

        h('ADIM 4 — Seed: yetkinlik_master')
        seed_count = 0
        for kod, ad, kategori, proses_kod_ref, sira in SEED_YETKINLIKLER:
            proses_id = proses_id_bul(con, proses_kod_ref)
            con.execute(
                """INSERT OR IGNORE INTO yetkinlik_master
                   (kod, ad, kategori, proses_id, sira)
                   VALUES (?, ?, ?, ?, ?)""",
                (kod, ad, kategori, proses_id, sira)
            )
            if con.execute("SELECT changes()").fetchone()[0] > 0:
                appl(f" SEED: '{kod}' / '{ad}' — eklendi (proses_id={proses_id})")
                seed_count += 1
            else:
                skip(f"'{kod}' zaten mevcut — atlandi")

        h('ADIM 5 — schema_migrations kaydi')
        con.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, uygulama_zamani, aciklama) VALUES (?, ?, ?)",
            (MIGRATION_VERSION, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), MIGRATION_DESC)
        )
        appl(f" schema_migrations: version='{MIGRATION_VERSION}' eklendi")

        con.commit()

        h('APPLY OZET')
        ym_count = con.execute("SELECT COUNT(*) FROM yetkinlik_master").fetchone()[0]
        ky_count = con.execute("SELECT COUNT(*) FROM kullanici_yetkinlik").fetchone()[0]
        print(f'  yetkinlik_master    : {ym_count} kayit')
        print(f'  kullanici_yetkinlik : {ky_count} kayit (henuz bos)')
        print(f'  Eklenen seed        : {seed_count}')
        print(f'  Migration versiyonu : {MIGRATION_VERSION}')
        print()
        ok("APPLY TAMAMLANDI")

    except Exception as e:
        import traceback
        try:
            con.rollback()
        except Exception:
            pass
        print(f'\n  HATA: {e}')
        traceback.print_exc()
        sys.exit(1)
    finally:
        con.close()


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='023 FAZ2C-2 Yetkinlik Migration')
    parser.add_argument('--apply', action='store_true', help='Gercek uygulama (varsayilan: dry-run)')
    args = parser.parse_args()

    if args.apply:
        run_apply()
    else:
        run_dryrun()
