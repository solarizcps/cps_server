# -*- coding: utf-8 -*-
"""
131_finans_cari_kimlik_kopru.py
=================================
FAZ-F1-1 — Finans cari kimlik köprüsü + tedarikçi golden eşleştirme.

1) finans_cari_kimlik — ortak muhasebe kimliği (MUSTERI / TEDARIKCI)
2) tedarikci_eslestirme — tedarikçi → Cari_Kart köprüsü
3) Yetki kodları + Yönetim / Muhasebe rol atamaları (idempotent)

Backfill YOK. cari_eslestirme şeması değişmez.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 131
YONETIM_ROL_ID = 1
MUHASEBE_ROL_ID = 2

YENI_YETKILER = [
    (
        'nexgen.finans.cari_kimlik.view',
        'nexgen',
        'Finans Cari Kimlik Görüntüleme',
        'Müşteri/tedarikçi muhasebe kimlik köprüsü okuma',
        235,
    ),
    (
        'nexgen.finans.cari_kimlik.manage',
        'nexgen',
        'Finans Cari Kimlik Yönetimi',
        'Müşteri golden kimlik eşleştirme yönetimi',
        236,
    ),
    (
        'nexgen.finans.tedarikci_kimlik.manage',
        'nexgen',
        'Tedarikçi Cari Köprüsü Yönetimi',
        'Tedarikçi → Cari_Kart golden eşleştirme yönetimi',
        237,
    ),
]

YONETIM_ATAMA = {
    'nexgen.finans.cari_kimlik.view': (1, 0, 0, 0, 0, 0, 0),
    'nexgen.finans.cari_kimlik.manage': (1, 0, 0, 0, 0, 0, 1),
    'nexgen.finans.tedarikci_kimlik.manage': (1, 0, 0, 0, 0, 0, 1),
}

MUHASEBE_ATAMA = {
    'nexgen.finans.cari_kimlik.view': (1, 0, 0, 0, 0, 0, 0),
    'nexgen.finans.cari_kimlik.manage': (1, 0, 1, 0, 0, 0, 0),
    'nexgen.finans.tedarikci_kimlik.manage': (1, 0, 1, 0, 0, 0, 0),
}


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _index_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,),
    ).fetchone())


def _ensure_finans_cari_kimlik(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'finans_cari_kimlik'):
        log(f'[{MIGRATION_VERSION}] SKIP finans_cari_kimlik — tablo zaten var')
        return
    con.executescript("""
        PRAGMA foreign_keys = ON;

        CREATE TABLE finans_cari_kimlik (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            kimlik_tipi             TEXT NOT NULL
                                    CHECK (kimlik_tipi IN ('MUSTERI', 'TEDARIKCI')),
            nexgen_cari_id          INTEGER UNIQUE
                                    REFERENCES nexgen_cari(id) ON DELETE RESTRICT,
            nexgen_tedarikci_id     INTEGER UNIQUE
                                    REFERENCES nexgen_tedarikci(id) ON DELETE RESTRICT,
            cari_kart_ckod          TEXT
                                    REFERENCES Cari_Kart(CKod) ON DELETE SET NULL,
            unvan_snapshot          TEXT,
            aktif                   INTEGER NOT NULL DEFAULT 1,
            durum                   TEXT NOT NULL DEFAULT 'BEKLIYOR'
                                    CHECK (durum IN (
                                        'BEKLIYOR','DOGRULANDI','MANUEL','IPTAL','CAKISMA'
                                    )),
            notlar                  TEXT,
            created_at              TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at              TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            created_by              INTEGER,
            updated_by              INTEGER,
            CHECK (
                (kimlik_tipi = 'MUSTERI'
                 AND nexgen_cari_id IS NOT NULL
                 AND nexgen_tedarikci_id IS NULL)
                OR
                (kimlik_tipi = 'TEDARIKCI'
                 AND nexgen_tedarikci_id IS NOT NULL
                 AND nexgen_cari_id IS NULL)
            )
        );
    """)
    log(f'[{MIGRATION_VERSION}] OK finans_cari_kimlik oluşturuldu')


def _ensure_finans_cari_kimlik_indexes(con: sqlite3.Connection) -> None:
    specs = (
        (
            'idx_fck_tip_aktif',
            'CREATE INDEX IF NOT EXISTS idx_fck_tip_aktif '
            'ON finans_cari_kimlik(kimlik_tipi, aktif)',
        ),
        (
            'idx_fck_durum',
            'CREATE INDEX IF NOT EXISTS idx_fck_durum ON finans_cari_kimlik(durum)',
        ),
        (
            'idx_fck_ckod_musteri_aktif',
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_fck_ckod_musteri_aktif '
            'ON finans_cari_kimlik(cari_kart_ckod) '
            "WHERE kimlik_tipi = 'MUSTERI' AND aktif = 1 AND cari_kart_ckod IS NOT NULL",
        ),
        (
            'idx_fck_ckod_tedarikci_aktif',
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_fck_ckod_tedarikci_aktif '
            'ON finans_cari_kimlik(cari_kart_ckod) '
            "WHERE kimlik_tipi = 'TEDARIKCI' AND aktif = 1 AND cari_kart_ckod IS NOT NULL",
        ),
    )
    for name, sql in specs:
        if not _index_exists(con, name):
            con.execute(sql)
            log(f'[{MIGRATION_VERSION}] index {name}')


def _ensure_tedarikci_eslestirme(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'tedarikci_eslestirme'):
        log(f'[{MIGRATION_VERSION}] SKIP tedarikci_eslestirme — tablo zaten var')
        return
    con.executescript("""
        PRAGMA foreign_keys = ON;

        CREATE TABLE tedarikci_eslestirme (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            nexgen_tedarikci_id INTEGER NOT NULL UNIQUE
                                REFERENCES nexgen_tedarikci(id) ON DELETE RESTRICT,
            cari_kart_ckod      TEXT
                                REFERENCES Cari_Kart(CKod) ON DELETE SET NULL,
            eslestirme_durumu   TEXT NOT NULL DEFAULT 'BEKLIYOR'
                                CHECK (eslestirme_durumu IN (
                                    'BEKLIYOR','DOGRULANDI','MANUEL','IPTAL'
                                )),
            eslestirme_yontemi  TEXT
                                CHECK (eslestirme_yontemi IS NULL OR eslestirme_yontemi IN (
                                    'CARI_KODU','ERP_KODU','VERGI_NO','MANUEL'
                                )),
            guven_puani         INTEGER,
            eslestiren_id       INTEGER,
            eslestirme_tarihi   TEXT,
            aktif               INTEGER NOT NULL DEFAULT 1,
            notlar              TEXT,
            created_at          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at          TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_te_ckod_aktif
            ON tedarikci_eslestirme(cari_kart_ckod)
            WHERE cari_kart_ckod IS NOT NULL AND aktif = 1;

        CREATE INDEX IF NOT EXISTS idx_te_durum
            ON tedarikci_eslestirme(eslestirme_durumu);

        CREATE INDEX IF NOT EXISTS idx_te_aktif
            ON tedarikci_eslestirme(aktif);
    """)
    log(f'[{MIGRATION_VERSION}] OK tedarikci_eslestirme oluşturuldu')


def _rol_var(con: sqlite3.Connection, rol_id: int) -> bool:
    return bool(con.execute(
        'SELECT 1 FROM sistem_rol WHERE Id=? AND Aktif=1', (rol_id,),
    ).fetchone())


def _rol_adi(con: sqlite3.Connection, rol_id: int) -> str:
    row = con.execute('SELECT Ad FROM sistem_rol WHERE Id=?', (rol_id,)).fetchone()
    return (row['Ad'] if row else '') or ''


def _yetki_id(con: sqlite3.Connection, kod: str) -> int:
    row = con.execute('SELECT Id FROM sistem_yetki WHERE Kod=?', (kod,)).fetchone()
    if row:
        return int(row['Id'])
    spec = next(y for y in YENI_YETKILER if y[0] == kod)
    con.execute(
        'INSERT INTO sistem_yetki (Kod, Modul, Ad, Aciklama, Sira) VALUES (?,?,?,?,?)',
        spec,
    )
    log(f'[{MIGRATION_VERSION}] EKLENDI yetki {kod}')
    return int(con.execute('SELECT last_insert_rowid()').fetchone()[0])


def _rol_yetki_upsert(
    con: sqlite3.Connection,
    rol_id: int,
    kod: str,
    *,
    can_view: int = 0,
    can_create: int = 0,
    can_update: int = 0,
    can_delete: int = 0,
    can_approve: int = 0,
    can_report: int = 0,
    can_manage: int = 0,
) -> None:
    yid = _yetki_id(con, kod)
    mevcut = con.execute(
        'SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?', (rol_id, yid),
    ).fetchone()
    g = 1 if can_view else 0
    d = 1 if (can_create or can_update or can_manage) else 0
    if mevcut:
        con.execute(
            """
            UPDATE sistem_rol_yetki
            SET Gorebilir=?, Duzenleyebilir=?,
                can_view=?, can_create=?, can_update=?, can_delete=?,
                can_approve=?, can_report=?, can_manage=?
            WHERE Id=?
            """,
            (g, d, can_view, can_create, can_update, can_delete,
             can_approve, can_report, can_manage, mevcut['Id']),
        )
    else:
        con.execute(
            """
            INSERT INTO sistem_rol_yetki
                (RolId, YetkiId, Gorebilir, Duzenleyebilir,
                 can_view, can_create, can_update, can_delete,
                 can_approve, can_report, can_manage)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (rol_id, yid, g, d, can_view, can_create, can_update, can_delete,
             can_approve, can_report, can_manage),
        )


def _ensure_yetkiler(con: sqlite3.Connection) -> None:
    for spec in YENI_YETKILER:
        _yetki_id(con, spec[0])

    if _rol_var(con, YONETIM_ROL_ID):
        for kod, flags in YONETIM_ATAMA.items():
            _rol_yetki_upsert(con, YONETIM_ROL_ID, kod, **dict(zip(
                ('can_view', 'can_create', 'can_update', 'can_delete',
                 'can_approve', 'can_report', 'can_manage'),
                flags,
            )))
        log(
            f'[{MIGRATION_VERSION}] Rol {YONETIM_ROL_ID} '
            f'({_rol_adi(con, YONETIM_ROL_ID)}) cari kimlik yetkileri'
        )
    else:
        log(f'[{MIGRATION_VERSION}] SKIP RolId={YONETIM_ROL_ID} — rol bulunamadi')

    if _rol_var(con, MUHASEBE_ROL_ID):
        ad = _rol_adi(con, MUHASEBE_ROL_ID)
        if ad.casefold() in ('muhasebe', 'finans', 'muhasebe / finans'):
            for kod, flags in MUHASEBE_ATAMA.items():
                _rol_yetki_upsert(con, MUHASEBE_ROL_ID, kod, **dict(zip(
                    ('can_view', 'can_create', 'can_update', 'can_delete',
                     'can_approve', 'can_report', 'can_manage'),
                    flags,
                )))
            log(f'[{MIGRATION_VERSION}] Rol {MUHASEBE_ROL_ID} ({ad}) cari kimlik yetkileri')
        else:
            log(
                f'[{MIGRATION_VERSION}] SKIP RolId={MUHASEBE_ROL_ID} '
                f'— ad muhasebe/finans degil: {ad!r}'
            )
    else:
        log(f'[{MIGRATION_VERSION}] SKIP RolId={MUHASEBE_ROL_ID} — rol bulunamadi')

    log(f'[{MIGRATION_VERSION}] NOT: Admin/Finans ayri rol yok — yalnizca Rol 1/2 atandi')


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] finans_cari_kimlik_kopru')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=60)
    con.row_factory = sqlite3.Row
    try:
        con.execute('BEGIN IMMEDIATE')
        con.execute('PRAGMA foreign_keys = ON')
        _ensure_finans_cari_kimlik(con)
        _ensure_finans_cari_kimlik_indexes(con)
        _ensure_tedarikci_eslestirme(con)
        _ensure_yetkiler(con)
        if _table_exists(con, 'schema_migrations'):
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (MIGRATION_VERSION,),
            )
        con.commit()
        log(f'[{MIGRATION_VERSION}] OK — idempotent tamam')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    run()
