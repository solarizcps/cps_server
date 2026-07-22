# -*- coding: utf-8 -*-
"""
113_nexgen_numune_talep.py
==========================
FAZ-NUMUNE-TALEP-UYGULAMA-1

Pazarlama numune talebi (AT-M-YYYY-NNNN) — tek çalışma kartı.
Bekleyen Numuneler = durum BEKLEYEN_NUMUNE filtresi (duplicate yok).

Idempotent: CREATE IF NOT EXISTS + INSERT OR IGNORE.
"""
from __future__ import annotations

import datetime
import os
import sqlite3

MIGRATION_VERSION = 113


def log(msg: str) -> None:
    print(msg)


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )

    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] nexgen_numune_talep starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        has_sm = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if has_sm:
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied:
                log(f'[{MIGRATION_VERSION}] SKIP — already applied')
                return

        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS nexgen_numune_talep (
                id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                talep_kodu                  TEXT NOT NULL UNIQUE,
                durum                       TEXT NOT NULL DEFAULT 'YENI_TALEP',
                talep_eden_kullanici_id     INTEGER,
                olusturan_kullanici_id      INTEGER NOT NULL,
                olusturma_tarihi            TEXT NOT NULL,
                guncelleme_tarihi           TEXT,
                oncelik                     TEXT NOT NULL DEFAULT 'NORMAL',
                hedef_tarih                 TEXT,
                talep_nedeni                TEXT,
                aciklama                    TEXT,
                ek_not                      TEXT,
                musteri_tipi                TEXT NOT NULL DEFAULT 'MEVCUT',
                cari_id                     INTEGER,
                aday_firma_adi              TEXT,
                ilgili_kisi                 TEXT,
                telefon                     TEXT,
                eposta                      TEXT,
                sehir                       TEXT,
                talep_kaynagi               TEXT,
                urun_tipi                   TEXT,
                urun_adi                    TEXT,
                urun_aciklama               TEXT,
                urun_gorsel_belge_id        INTEGER,
                renk_tipi                   TEXT,
                rf_renk_id                  INTEGER,
                renk_kodu                   TEXT,
                yeni_renk_aciklama          TEXT,
                acik_koyu                   TEXT,
                mat_parlak                  TEXT,
                ref_renk_kodu               TEXT,
                ref_gorsel_belge_id         INTEGER,
                yumusaklik                  TEXT,
                kaymazlik                   TEXT,
                shore_deger                 TEXT,
                pisme_notu                  TEXT,
                diger_beklentiler_json      TEXT,
                vedat_pigment               TEXT,
                vedat_numune_miktari        TEXT,
                vedat_numune_sonucu         TEXT,
                vedat_revizyon_notu         TEXT,
                vedat_sonuc_gorsel_belge_id INTEGER,
                vedat_ferhat_testi          INTEGER NOT NULL DEFAULT 0,
                vedat_sonuc                 TEXT,
                arge_test_id                INTEGER,
                aktif                       INTEGER NOT NULL DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_nnt_durum ON nexgen_numune_talep(durum);
            CREATE INDEX IF NOT EXISTS idx_nnt_kod ON nexgen_numune_talep(talep_kodu);
            CREATE INDEX IF NOT EXISTS idx_nnt_olusturan ON nexgen_numune_talep(olusturan_kullanici_id);
            CREATE INDEX IF NOT EXISTS idx_nnt_talep_eden ON nexgen_numune_talep(talep_eden_kullanici_id);
            """
        )

        if has_sm:
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (MIGRATION_VERSION,),
            )
        con.commit()
        log(f'[{MIGRATION_VERSION}] OK — nexgen_numune_talep ready')
    finally:
        con.close()


if __name__ == '__main__':
    run()
