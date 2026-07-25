# -*- coding: utf-8 -*-
"""
126_mo_tahsilat_plani.py
========================
FAZ-MO-SIPARIS-TAHSILAT-PLANI-1 — sipariş tahsilat planı kolonları + mo_tahsilat_kayit.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 126

NPS_KOLONLAR = (
    ('tahsilat_odeme_sekli', 'TEXT'),
    ('tahsilat_kurali', 'TEXT'),
    ('tahsilat_gun_sayisi', 'INTEGER'),
    ('tahsilat_sabit_tarih', 'TEXT'),
    ('planlanan_tahsilat_tarihi', 'TEXT'),
    ('tahsilat_sozu', 'TEXT'),
    ('tahsilat_notu', 'TEXT'),
    ('tahsilat_durumu', 'TEXT'),
    ('tahsilat_tarih_kaynagi', 'TEXT'),
    ('tahsilat_hesaplanan_sevk_ref', 'TEXT'),
    ('cek_teslim_tarihi', 'TEXT'),
    ('cek_vadesi', 'TEXT'),
)


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _kolon_var(con, tablo: str, kolon: str) -> bool:
    if not _table_exists(con, tablo):
        return False
    return kolon in [c[1] for c in con.execute(f'PRAGMA table_info({tablo})').fetchall()]


def _ensure_nps_columns(con: sqlite3.Connection) -> None:
    if not _table_exists(con, 'nexgen_planlama_siparis'):
        log(f'[{MIGRATION_VERSION}] nexgen_planlama_siparis yok — atlanıyor')
        return
    for kolon, tip in NPS_KOLONLAR:
        if _kolon_var(con, 'nexgen_planlama_siparis', kolon):
            continue
        con.execute(f'ALTER TABLE nexgen_planlama_siparis ADD COLUMN {kolon} {tip}')
        log(f'[{MIGRATION_VERSION}] kolon eklendi: {kolon}')
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_nps_tahsilat_plan
        ON nexgen_planlama_siparis(planlanan_tahsilat_tarihi, tahsilat_durumu)
        WHERE planlanan_tahsilat_tarihi IS NOT NULL
        """
    )


def _ensure_mo_tahsilat_kayit(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'mo_tahsilat_kayit'):
        return
    con.execute("""
        CREATE TABLE mo_tahsilat_kayit (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            kayit_kodu              TEXT,
            cari_id                 INTEGER NOT NULL,
            siparis_id              INTEGER,
            kaynak_modul            TEXT NOT NULL DEFAULT 'MUSTERI_OPERASYONU',
            beklenen_tutar          REAL,
            beklenen_tahmini        INTEGER NOT NULL DEFAULT 1,
            alinan_tutar            REAL,
            kalan_tutar             REAL,
            planlanan_tahsilat_tarihi TEXT,
            alinan_tarih            TEXT,
            odeme_tipi              TEXT,
            odeme_referansi         TEXT,
            kismi_mi                INTEGER NOT NULL DEFAULT 0,
            aciklama                TEXT,
            dosya_ref               TEXT,
            onay_notu               TEXT,
            revizyon_gerekce        TEXT,
            durum                   TEXT NOT NULL DEFAULT 'TASLAK',
            cari_entegrasyon_durumu TEXT NOT NULL DEFAULT 'BEKLIYOR',
            idempotency_key         TEXT NOT NULL UNIQUE,
            olusturan_id            INTEGER NOT NULL,
            onaylayan_id            INTEGER,
            aktif                   INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            guncelleme_tarihi       TEXT,
            audit_json              TEXT
        )
    """)
    con.execute('CREATE INDEX IF NOT EXISTS idx_mtk_cari ON mo_tahsilat_kayit(cari_id)')
    con.execute('CREATE INDEX IF NOT EXISTS idx_mtk_siparis ON mo_tahsilat_kayit(siparis_id)')
    con.execute('CREATE INDEX IF NOT EXISTS idx_mtk_durum ON mo_tahsilat_kayit(durum)')
    log(f'[{MIGRATION_VERSION}] mo_tahsilat_kayit created')


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] MO tahsilat planı')
    con = sqlite3.connect(db_path, timeout=60)
    try:
        if _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied and _table_exists(con, 'mo_tahsilat_kayit'):
                if _kolon_var(con, 'nexgen_planlama_siparis', 'tahsilat_kurali'):
                    log(f'[{MIGRATION_VERSION}] SKIP — idempotent')
                    return
        con.execute('BEGIN IMMEDIATE')
        _ensure_nps_columns(con)
        _ensure_mo_tahsilat_kayit(con)
        if _table_exists(con, 'schema_migrations'):
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (MIGRATION_VERSION,),
            )
        con.commit()
        log(f'[{MIGRATION_VERSION}] tamamlandı')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    run()
