# -*- coding: utf-8 -*-
"""
146_nexgen_musteri_temsilcisi_talep.py
======================================
FAZ-MUSTERI-TEMSILCISI-TALEP-OMURGA-F1-F2

- nexgen_musteri_temsilcisi_talep
- nexgen_musteri_temsilcisi_talep_kalem

UI / sipariş-numune dönüşümü bu migration'da yok.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 146


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _ensure_talep(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'nexgen_musteri_temsilcisi_talep'):
        log(f'[{MIGRATION_VERSION}] SKIP nexgen_musteri_temsilcisi_talep exists')
        return
    con.execute("""
        CREATE TABLE nexgen_musteri_temsilcisi_talep (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            talep_no TEXT NOT NULL UNIQUE,
            talep_turu TEXT NOT NULL,
            durum TEXT NOT NULL DEFAULT 'YENI',
            gorusme_id INTEGER NOT NULL,
            cari_id INTEGER,
            musteri_aday_id INTEGER,
            olusturan_kullanici_id INTEGER NOT NULL,
            atanan_kullanici_id INTEGER,
            oncelik TEXT NOT NULL DEFAULT 'NORMAL',
            aciklama TEXT,
            musteri_notu TEXT,
            geri_gonderme_notu TEXT,
            red_nedeni TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            donusturulen_siparis_id INTEGER,
            donusturulen_numune_talep_id INTEGER,
            isleme_alinma_tarihi TEXT,
            donusturulme_tarihi TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (talep_turu IN ('SIPARIS', 'NUMUNE')),
            CHECK (durum IN (
                'YENI', 'ISLEME_ALINDI', 'EKSIK_BILGI',
                'SIPARISE_DONUSTU', 'NUMUNEYE_DONUSTU',
                'REDDEDILDI', 'IPTAL'
            )),
            CHECK (oncelik IN ('DUSUK', 'NORMAL', 'YUKSEK', 'ACIL')),
            CHECK (
                (cari_id IS NOT NULL AND musteri_aday_id IS NULL)
                OR (cari_id IS NULL AND musteri_aday_id IS NOT NULL)
            )
        )
    """)
    for name, cols in (
        ('idx_nmtt_durum', 'durum'),
        ('idx_nmtt_turu', 'talep_turu'),
        ('idx_nmtt_gorusme', 'gorusme_id'),
        ('idx_nmtt_cari', 'cari_id'),
        ('idx_nmtt_aday', 'musteri_aday_id'),
        ('idx_nmtt_olusturan', 'olusturan_kullanici_id'),
        ('idx_nmtt_atanan', 'atanan_kullanici_id'),
        ('idx_nmtt_created', 'created_at'),
        ('idx_nmtt_siparis_ptr', 'donusturulen_siparis_id'),
        ('idx_nmtt_numune_ptr', 'donusturulen_numune_talep_id'),
    ):
        con.execute(f'CREATE INDEX IF NOT EXISTS {name} ON nexgen_musteri_temsilcisi_talep({cols})')
    log(f'[{MIGRATION_VERSION}] OK CREATE nexgen_musteri_temsilcisi_talep')


def _ensure_kalem(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'nexgen_musteri_temsilcisi_talep_kalem'):
        log(f'[{MIGRATION_VERSION}] SKIP nexgen_musteri_temsilcisi_talep_kalem exists')
        return
    con.execute("""
        CREATE TABLE nexgen_musteri_temsilcisi_talep_kalem (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            talep_id INTEGER NOT NULL,
            sira_no INTEGER NOT NULL,
            urun_ailesi TEXT,
            urun_aciklama TEXT NOT NULL,
            formul_id INTEGER,
            renk_id INTEGER,
            renk_aciklama TEXT,
            boyut TEXT,
            miktar_kg REAL,
            konusulan_tonaj REAL,
            verilen_fiyat REAL,
            para_birimi TEXT,
            fiyat_birimi TEXT NOT NULL DEFAULT 'KG',
            odeme_tipi TEXT,
            vade_gun INTEGER,
            cek_vade_gun INTEGER,
            kalem_notu TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (fiyat_birimi = 'KG'),
            CHECK (miktar_kg IS NULL OR miktar_kg >= 0),
            CHECK (konusulan_tonaj IS NULL OR konusulan_tonaj >= 0),
            CHECK (verilen_fiyat IS NULL OR verilen_fiyat >= 0),
            CHECK (vade_gun IS NULL OR vade_gun >= 0),
            CHECK (cek_vade_gun IS NULL OR cek_vade_gun >= 0),
            UNIQUE (talep_id, sira_no),
            FOREIGN KEY (talep_id) REFERENCES nexgen_musteri_temsilcisi_talep(id)
        )
    """)
    con.execute(
        'CREATE INDEX IF NOT EXISTS idx_nmttk_talep '
        'ON nexgen_musteri_temsilcisi_talep_kalem(talep_id)'
    )
    log(f'[{MIGRATION_VERSION}] OK CREATE nexgen_musteri_temsilcisi_talep_kalem')


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] musteri_temsilcisi_talep starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    try:
        if not _table_exists(con, 'musteri_operasyon_gorusme'):
            raise RuntimeError('musteri_operasyon_gorusme yok — 123/142 gerekli')
        if not _table_exists(con, 'nexgen_musteri_aday'):
            raise RuntimeError('nexgen_musteri_aday yok — 142 gerekli')

        if (
            _table_exists(con, 'nexgen_musteri_temsilcisi_talep')
            and _table_exists(con, 'nexgen_musteri_temsilcisi_talep_kalem')
            and _table_exists(con, 'schema_migrations')
        ):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied:
                log(f'[{MIGRATION_VERSION}] SKIP — already applied')
                return

        con.execute('BEGIN IMMEDIATE')
        _ensure_talep(con)
        _ensure_kalem(con)

        if _table_exists(con, 'schema_migrations'):
            scol = [c[1] for c in con.execute('PRAGMA table_info(schema_migrations)').fetchall()]
            if 'aciklama' in scol:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                    (MIGRATION_VERSION, 'musteri temsilcisi talep + kalem omurga'),
                )
            else:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                    (MIGRATION_VERSION,),
                )
        con.commit()
        log(f'[{MIGRATION_VERSION}] DONE')
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass
        raise
    finally:
        con.close()


if __name__ == '__main__':
    run()
