# -*- coding: utf-8 -*-
"""
142_nexgen_musteri_aday.py
==========================
FAZ-NEXGEN-MUSTERI-ADAY-ORTAK-KIMLIK-VE-ILK-GORUSME-1

- nexgen_musteri_aday ortak aday tablosu
- musteri_operasyon_gorusme.cari_id → NULLABLE
- musteri_operasyon_gorusme.musteri_aday_id
- nexgen_numune_talep.musteri_aday_id (nullable, davranış değişmez)
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 142


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _columns(con, table: str) -> list[tuple]:
    return list(con.execute(f'PRAGMA table_info({table})').fetchall())


def _col_names(con, table: str) -> set[str]:
    return {c[1] for c in _columns(con, table)}


def _col_notnull(con, table: str, col: str) -> bool:
    for c in _columns(con, table):
        if c[1] == col:
            return bool(c[3])
    return False


def _ensure_aday_table(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'nexgen_musteri_aday'):
        log(f'[{MIGRATION_VERSION}] SKIP nexgen_musteri_aday exists')
        return
    con.execute("""
        CREATE TABLE nexgen_musteri_aday (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firma_adi TEXT NOT NULL,
            yetkili_adi TEXT,
            telefon TEXT,
            sehir TEXT,
            not_metni TEXT,
            durum TEXT NOT NULL DEFAULT 'ADAY',
            olusturan_kullanici_id INTEGER NOT NULL,
            nexgen_cari_id INTEGER,
            idempotency_key TEXT UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT,
            donusturulme_tarihi TEXT
        )
    """)
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_nma_durum ON nexgen_musteri_aday(durum)'
    )
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_nma_olusturan ON nexgen_musteri_aday(olusturan_kullanici_id)'
    )
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_nma_cari ON nexgen_musteri_aday(nexgen_cari_id)'
    )
    log(f'[{MIGRATION_VERSION}] OK CREATE nexgen_musteri_aday')


def _rebuild_gorusme_nullable_cari(con: sqlite3.Connection) -> None:
    table = 'musteri_operasyon_gorusme'
    if not _table_exists(con, table):
        raise RuntimeError(f'{table} yok')

    names = _col_names(con, table)
    need_rebuild = _col_notnull(con, table, 'cari_id')
    if 'musteri_aday_id' in names and not need_rebuild:
        log(f'[{MIGRATION_VERSION}] SKIP gorusme schema already OK')
        return

    if 'musteri_aday_id' not in names and not need_rebuild:
        con.execute(f'ALTER TABLE {table} ADD COLUMN musteri_aday_id INTEGER')
        con.execute(
            'CREATE INDEX IF NOT EXISTS idx_mog_aday ON musteri_operasyon_gorusme(musteri_aday_id)'
        )
        log(f'[{MIGRATION_VERSION}] OK ADD musteri_aday_id (cari already nullable)')
        return

    # Full rebuild: cari_id NOT NULL → NULL + musteri_aday_id
    tmp = 'musteri_operasyon_gorusme__mig142'
    if _table_exists(con, tmp):
        con.execute(f'DROP TABLE {tmp}')

    con.execute(f"""
        CREATE TABLE {tmp} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cari_id INTEGER,
            musteri_aday_id INTEGER,
            kullanici_id INTEGER NOT NULL,
            kaynak TEXT NOT NULL DEFAULT 'MUSTERI_OPERASYONU',
            gorusme_tipi TEXT NOT NULL,
            sonuc_tipi TEXT NOT NULL,
            sonuc_etiketler TEXT,
            kisa_not TEXT NOT NULL,
            gorusme_tarihi TEXT NOT NULL,
            sonraki_takip_tarihi TEXT,
            oncelik TEXT NOT NULL DEFAULT 'NORMAL',
            tahmini_siparis_tutari REAL,
            tahmini_siparis_tarihi TEXT,
            istenen_vade_gun INTEGER,
            cek_alim_tarihi TEXT,
            rakip_firma TEXT,
            makina_notu TEXT,
            detay_not TEXT,
            dosya_ref TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            aktif INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            guncelleme_tarihi TEXT,
            olusturan_kullanici_id INTEGER NOT NULL,
            audit_json TEXT,
            yetkili_id INTEGER,
            konu TEXT,
            sonraki_aksiyon TEXT,
            takip_durumu TEXT,
            guncelleyen_kullanici_id INTEGER,
            numune_talep_id INTEGER
        )
    """)

    # Map source columns that exist
    src = _col_names(con, table)
    dest_cols = [
        'id', 'cari_id', 'kullanici_id', 'kaynak', 'gorusme_tipi', 'sonuc_tipi',
        'sonuc_etiketler', 'kisa_not', 'gorusme_tarihi', 'sonraki_takip_tarihi',
        'oncelik', 'tahmini_siparis_tutari', 'tahmini_siparis_tarihi',
        'istenen_vade_gun', 'cek_alim_tarihi', 'rakip_firma', 'makina_notu',
        'detay_not', 'dosya_ref', 'idempotency_key', 'aktif', 'olusturma_tarihi',
        'guncelleme_tarihi', 'olusturan_kullanici_id', 'audit_json',
        'yetkili_id', 'konu', 'sonraki_aksiyon', 'takip_durumu',
        'guncelleyen_kullanici_id', 'numune_talep_id',
    ]
    copy_cols = [c for c in dest_cols if c in src]
    col_sql = ', '.join(copy_cols)
    con.execute(
        f'INSERT INTO {tmp} ({col_sql}, musteri_aday_id) '
        f'SELECT {col_sql}, NULL FROM {table}'
    )
    n = con.execute(f'SELECT COUNT(*) FROM {tmp}').fetchone()[0]
    old_n = con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    if n != old_n:
        raise RuntimeError(f'gorusme copy mismatch {n}!={old_n}')

    con.execute(f'DROP TABLE {table}')
    con.execute(f'ALTER TABLE {tmp} RENAME TO {table}')
    con.execute('CREATE INDEX IF NOT EXISTS idx_mog_cari ON musteri_operasyon_gorusme(cari_id)')
    con.execute('CREATE INDEX IF NOT EXISTS idx_mog_aday ON musteri_operasyon_gorusme(musteri_aday_id)')
    con.execute('CREATE INDEX IF NOT EXISTS idx_mog_gorusme_tarihi ON musteri_operasyon_gorusme(gorusme_tarihi)')
    con.execute('CREATE INDEX IF NOT EXISTS idx_mog_takip ON musteri_operasyon_gorusme(sonraki_takip_tarihi)')
    log(f'[{MIGRATION_VERSION}] OK REBUILD gorusme nullable cari_id + musteri_aday_id n={n}')


def _ensure_numune_aday_col(con: sqlite3.Connection) -> None:
    table = 'nexgen_numune_talep'
    if not _table_exists(con, table):
        log(f'[{MIGRATION_VERSION}] SKIP numune table missing')
        return
    cols = _col_names(con, table)
    if 'musteri_aday_id' in cols:
        log(f'[{MIGRATION_VERSION}] SKIP numune.musteri_aday_id')
        return
    con.execute(f'ALTER TABLE {table} ADD COLUMN musteri_aday_id INTEGER')
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_nt_musteri_aday ON nexgen_numune_talep(musteri_aday_id)'
    )
    log(f'[{MIGRATION_VERSION}] OK ADD nexgen_numune_talep.musteri_aday_id')


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] nexgen_musteri_aday starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=60)
    con.row_factory = sqlite3.Row
    try:
        if _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied and _table_exists(con, 'nexgen_musteri_aday'):
                names = _col_names(con, 'musteri_operasyon_gorusme')
                if 'musteri_aday_id' in names and not _col_notnull(con, 'musteri_operasyon_gorusme', 'cari_id'):
                    log(f'[{MIGRATION_VERSION}] SKIP — already applied')
                    return

        con.execute('BEGIN IMMEDIATE')
        _ensure_aday_table(con)
        _rebuild_gorusme_nullable_cari(con)
        _ensure_numune_aday_col(con)

        # verify
        if not _table_exists(con, 'nexgen_musteri_aday'):
            raise RuntimeError('nexgen_musteri_aday missing')
        if 'musteri_aday_id' not in _col_names(con, 'musteri_operasyon_gorusme'):
            raise RuntimeError('musteri_aday_id missing on gorusme')
        if _col_notnull(con, 'musteri_operasyon_gorusme', 'cari_id'):
            raise RuntimeError('cari_id still NOT NULL')

        if _table_exists(con, 'schema_migrations'):
            scol = [c[1] for c in con.execute('PRAGMA table_info(schema_migrations)').fetchall()]
            if 'aciklama' in scol:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                    (MIGRATION_VERSION, 'nexgen_musteri_aday + gorusme.musteri_aday_id'),
                )
            else:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                    (MIGRATION_VERSION,),
                )
        con.commit()
        log(f'[{MIGRATION_VERSION}] OK — committed')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    run()
