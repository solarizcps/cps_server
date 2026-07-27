# -*- coding: utf-8 -*-
"""
121_cari_sorumlu.py
===================
FAZ-CARI-SORUMLU-VE-PAZARLAMACI-KAPSAMI-F1C

cari_sorumlu tablosu + cari360.sorumlu.manage yetkisi.
Otomatik backfill YOK — tablo boş kalabilir.
"""
from __future__ import annotations

import datetime
import os
import sqlite3

MIGRATION_VERSION = 121
YONETIM_ROL_ID = 1

SORUMLULUK_ROLLERI = ('ANA', 'YEDEK', 'YONETICI', 'DESTEK')

YENI_YETKI = (
    'cari360.sorumlu.manage', 'cari360', 'Cari Sorumlu Yönetimi',
    'Pazarlama sorumlusu atama/değiştirme', 207,
)


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _ensure_table(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'cari_sorumlu'):
        log('[121] SKIP cari_sorumlu — tablo zaten var')
        return
    con.executescript("""
        PRAGMA foreign_keys = ON;

        CREATE TABLE cari_sorumlu (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            cari_id             INTEGER NOT NULL,
            kullanici_id        INTEGER NOT NULL,
            sorumluluk_rolu     TEXT NOT NULL DEFAULT 'ANA'
                                CHECK(sorumluluk_rolu IN ('ANA','YEDEK','YONETICI','DESTEK')),
            baslangic_tarihi    TEXT NOT NULL DEFAULT (date('now','localtime')),
            bitis_tarihi        TEXT,
            aktif               INTEGER NOT NULL DEFAULT 1,
            atayan_kullanici_id INTEGER,
            atama_notu          TEXT,
            created_at          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (cari_id) REFERENCES nexgen_cari(id) ON DELETE RESTRICT,
            FOREIGN KEY (kullanici_id) REFERENCES sistem_kullanici(Id) ON DELETE RESTRICT,
            FOREIGN KEY (atayan_kullanici_id) REFERENCES sistem_kullanici(Id) ON DELETE SET NULL
        );

        CREATE UNIQUE INDEX idx_cari_sorumlu_ana_aktif
            ON cari_sorumlu(cari_id)
            WHERE sorumluluk_rolu='ANA' AND aktif=1 AND bitis_tarihi IS NULL;

        CREATE UNIQUE INDEX idx_cari_sorumlu_kull_rol_aktif
            ON cari_sorumlu(cari_id, kullanici_id, sorumluluk_rolu)
            WHERE aktif=1 AND bitis_tarihi IS NULL;

        CREATE INDEX idx_cari_sorumlu_kullanici
            ON cari_sorumlu(kullanici_id, aktif);

        CREATE INDEX idx_cari_sorumlu_cari
            ON cari_sorumlu(cari_id, aktif);
    """)
    log('[121] OK cari_sorumlu tablosu oluşturuldu')


def _ensure_yetki(con: sqlite3.Connection) -> int:
    kod, modul, ad, acik, sira = YENI_YETKI
    row = con.execute('SELECT Id FROM sistem_yetki WHERE Kod=?', (kod,)).fetchone()
    if row:
        return int(row['Id'])
    con.execute(
        'INSERT INTO sistem_yetki (Kod, Modul, Ad, Aciklama, Sira) VALUES (?,?,?,?,?)',
        (kod, modul, ad, acik, sira),
    )
    log(f'[121] EKLENDI yetki {kod}')
    return int(con.execute('SELECT last_insert_rowid()').fetchone()[0])


def _rol_yetki_upsert(con: sqlite3.Connection, rol_id: int, yetki_id: int) -> None:
    mevcut = con.execute(
        'SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?',
        (rol_id, yetki_id),
    ).fetchone()
    if mevcut:
        con.execute(
            """
            UPDATE sistem_rol_yetki
            SET can_view=1, can_manage=1, Gorebilir=1
            WHERE Id=?
            """,
            (mevcut['Id'],),
        )
        log('[121] UPDATE Yönetim cari360.sorumlu.manage')
        return
    con.execute(
        """
        INSERT INTO sistem_rol_yetki
            (RolId, YetkiId, Gorebilir, Duzenleyebilir,
             can_view, can_create, can_update, can_delete,
             can_approve, can_report, can_manage)
        VALUES (?, ?, 1, 0, 1, 0, 0, 0, 0, 0, 1)
        """,
        (rol_id, yetki_id),
    )
    log('[121] EKLENDI Yönetim cari360.sorumlu.manage')


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )

    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] cari_sorumlu starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.execute('PRAGMA foreign_keys = ON')

        if _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied and _table_exists(con, 'cari_sorumlu'):
                yrow = con.execute(
                    "SELECT 1 FROM sistem_yetki WHERE Kod='cari360.sorumlu.manage'"
                ).fetchone()
                if yrow:
                    log(f'[{MIGRATION_VERSION}] SKIP — already applied (idempotent)')
                    return

        con.execute('BEGIN IMMEDIATE')
        _ensure_table(con)
        yid = _ensure_yetki(con)
        _rol_yetki_upsert(con, YONETIM_ROL_ID, yid)

        cnt = con.execute('SELECT COUNT(*) FROM cari_sorumlu').fetchone()[0]
        log(f'[{MIGRATION_VERSION}] cari_sorumlu satır sayısı: {cnt} (backfill yok)')

        if _table_exists(con, 'schema_migrations'):
            cols = [c[1] for c in con.execute('PRAGMA table_info(schema_migrations)').fetchall()]
            if 'aciklama' in cols:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                    (MIGRATION_VERSION, 'cari_sorumlu + sorumlu.manage yetki'),
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
