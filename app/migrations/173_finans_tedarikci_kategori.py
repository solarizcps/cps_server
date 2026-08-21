# -*- coding: utf-8 -*-
"""
173_finans_tedarikci_kategori.py
================================
FAZ 6C — Tedarikçi kategori referans tablosu + seed.

Korgün write YOK — yalnız CPS SQLite.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 173

KATEGORI_SEED: tuple[tuple[str, str, int], ...] = (
    ('TANIMSIZ', 'Tanımsız', 10),
    ('URETIM', 'Üretim Tedarikçisi', 20),
    ('HAMMADDE', 'Hammadde', 30),
    ('KIMYASAL', 'Kimyasal', 40),
    ('ELEKTRIK_ENERJI', 'Elektrik / Enerji', 50),
    ('SABIT_GIDER', 'Sabit Gider', 60),
    ('DANISMANLIK_HIZMET', 'Danışmanlık / Hizmet', 70),
    ('LOJISTIK_NAKLIYE', 'Lojistik / Nakliye', 80),
    ('YEMEK_CATERING', 'Yemek / Catering', 90),
    ('KIRA', 'Kira', 100),
    ('BAKIM_TEKNIK', 'Bakım / Teknik Servis', 110),
    ('MAKINE_YEDEK_PARCA', 'Makine / Yedek Parça', 120),
    ('RESMI_VERGI_HARC', 'Resmi / Vergi / Harç', 130),
    ('DIGER', 'Diğer', 140),
)


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _seed_categories(con: sqlite3.Connection) -> None:
    for code, label, sort_order in KATEGORI_SEED:
        con.execute(
            """
            INSERT OR IGNORE INTO finans_tedarikci_kategori
                (code, label_tr, sort_order, active)
            VALUES (?, ?, ?, 1)
            """,
            (code, label, sort_order),
        )
        con.execute(
            """
            UPDATE finans_tedarikci_kategori
            SET label_tr=?, sort_order=?, active=1
            WHERE code=?
            """,
            (label, sort_order, code),
        )


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 60)
    log(f'[{MIGRATION_VERSION}] finans_tedarikci_kategori')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if not _table_exists(con, 'finans_tedarikci_kategori'):
            con.executescript("""
                CREATE TABLE finans_tedarikci_kategori (
                    code        TEXT PRIMARY KEY,
                    label_tr    TEXT NOT NULL,
                    sort_order  INTEGER NOT NULL DEFAULT 100,
                    active      INTEGER NOT NULL DEFAULT 1
                        CHECK (active IN (0, 1))
                );
                CREATE INDEX idx_ftk_active_sort
                    ON finans_tedarikci_kategori(active, sort_order);
            """)
            log(f'[{MIGRATION_VERSION}] finans_tedarikci_kategori created')
        else:
            log(f'[{MIGRATION_VERSION}] SKIP finans_tedarikci_kategori — zaten var')

        _seed_categories(con)
        log(f'[{MIGRATION_VERSION}] seed count={len(KATEGORI_SEED)}')

        if con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone():
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (MIGRATION_VERSION,),
            )
        con.commit()
    finally:
        con.close()
    log(f'[{MIGRATION_VERSION}] OK')


if __name__ == '__main__':
    run()
