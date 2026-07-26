# -*- coding: utf-8 -*-
"""
130_finans_yetkileri.py
========================
FAZ-FINANS-1E1 — Finans / Muhasebe Merkezi yetki kodları.

Yalnız sistem_yetki kayıtları + kesin bilinen rol atamaları.
Depo, üretim operatörü ve pazarlamacı rollerine atama yapılmaz.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 130
YONETIM_ROL_ID = 1
MUHASEBE_ROL_ID = 2

YENI_YETKILER = [
    ('nexgen.finans.view', 'nexgen', 'Finans Merkezi Görüntüleme', 'Finans belgesi listesi ve detay', 230),
    ('nexgen.finans.review', 'nexgen', 'Finans İnceleme', 'Belge inceleme ve düzeltmeye gönderme', 231),
    ('nexgen.finans.approve', 'nexgen', 'Finans Onay', 'Finans belgesi onaylama', 232),
    ('nexgen.finans.post', 'nexgen', 'Finans Posting', 'Cari posting işlemi (dry-run / canlı)', 233),
    ('nexgen.finans.reject', 'nexgen', 'Finans Red', 'Finans belgesi reddetme', 234),
]

MUHASEBE_ATAMA = {
    'nexgen.finans.view': (1, 0, 0, 0, 0, 0, 0),
    'nexgen.finans.review': (1, 0, 1, 0, 0, 0, 0),
    'nexgen.finans.approve': (1, 0, 0, 0, 1, 0, 0),
    'nexgen.finans.post': (1, 1, 0, 0, 0, 0, 0),
    'nexgen.finans.reject': (1, 0, 0, 0, 1, 0, 0),
}

YONETIM_ATAMA = {
    'nexgen.finans.view': (1, 0, 0, 0, 0, 0, 1),
    'nexgen.finans.review': (1, 1, 1, 0, 0, 0, 1),
    'nexgen.finans.approve': (1, 0, 0, 0, 1, 0, 1),
    'nexgen.finans.post': (1, 1, 1, 0, 0, 0, 1),
    'nexgen.finans.reject': (1, 0, 0, 0, 1, 0, 1),
}


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _rol_var(con, rol_id: int) -> bool:
    return bool(con.execute(
        'SELECT 1 FROM sistem_rol WHERE Id=? AND Aktif=1', (rol_id,),
    ).fetchone())


def _rol_adi(con, rol_id: int) -> str:
    row = con.execute('SELECT Ad FROM sistem_rol WHERE Id=?', (rol_id,)).fetchone()
    return (row['Ad'] if row else '') or ''


def _yetki_id(con, kod: str) -> int:
    row = con.execute('SELECT Id FROM sistem_yetki WHERE Kod=?', (kod,)).fetchone()
    if row:
        return int(row['Id'])
    spec = next(y for y in YENI_YETKILER if y[0] == kod)
    con.execute(
        'INSERT INTO sistem_yetki (Kod, Modul, Ad, Aciklama, Sira) VALUES (?,?,?,?,?)',
        spec,
    )
    return int(con.execute('SELECT last_insert_rowid()').fetchone()[0])


def _rol_yetki_upsert(
    con,
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
        log(f'[{MIGRATION_VERSION}] Rol {YONETIM_ROL_ID} ({_rol_adi(con, YONETIM_ROL_ID)}) finans yetkileri')
    else:
        log(f'[{MIGRATION_VERSION}] SKIP RolId={YONETIM_ROL_ID} bulunamadi')

    if _rol_var(con, MUHASEBE_ROL_ID):
        ad = _rol_adi(con, MUHASEBE_ROL_ID)
        if ad.casefold() in ('muhasebe', 'finans', 'muhasebe / finans'):
            for kod, flags in MUHASEBE_ATAMA.items():
                _rol_yetki_upsert(con, MUHASEBE_ROL_ID, kod, **dict(zip(
                    ('can_view', 'can_create', 'can_update', 'can_delete',
                     'can_approve', 'can_report', 'can_manage'),
                    flags,
                )))
            log(f'[{MIGRATION_VERSION}] Rol {MUHASEBE_ROL_ID} ({ad}) finans yetkileri')
        else:
            log(f'[{MIGRATION_VERSION}] SKIP RolId={MUHASEBE_ROL_ID} adi muhasebe degil: {ad!r}')
    else:
        log(f'[{MIGRATION_VERSION}] SKIP RolId={MUHASEBE_ROL_ID} bulunamadi')


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] finans_yetkileri')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        pre = {r['Kod'] for r in con.execute(
            "SELECT Kod FROM sistem_yetki WHERE Kod LIKE 'nexgen.finans.%'"
        ).fetchall()}
        if len(pre) >= len(YENI_YETKILER):
            _ensure_yetkiler(con)
            if _table_exists(con, 'schema_migrations'):
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                    (MIGRATION_VERSION,),
                )
                con.commit()
            log(f'[{MIGRATION_VERSION}] SKIP — idempotent')
            return

        con.execute('BEGIN IMMEDIATE')
        _ensure_yetkiler(con)
        if _table_exists(con, 'schema_migrations'):
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (MIGRATION_VERSION,),
            )
        con.commit()
        log(f'[{MIGRATION_VERSION}] OK')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    run()
