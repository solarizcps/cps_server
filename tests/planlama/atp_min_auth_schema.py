# -*- coding: utf-8 -*-
"""Minimal sistem_rol / sistem_yetki for isolated WhatsApp integration tests.

No canonical row copy — synthetic placeholders only. Idempotent.
"""
from __future__ import annotations

import sqlite3

_DDL_SISTEM_ROL = """
CREATE TABLE IF NOT EXISTS sistem_rol (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Ad TEXT UNIQUE NOT NULL,
    Aciklama TEXT,
    Renk TEXT DEFAULT '#64748b',
    Aktif INTEGER DEFAULT 1,
    SuperAdmin INTEGER DEFAULT 0,
    OlusturmaTarih TEXT,
    OlusturanKullanici TEXT
)
"""

_DDL_SISTEM_YETKI = """
CREATE TABLE IF NOT EXISTS sistem_yetki (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Kod TEXT UNIQUE NOT NULL,
    Ad TEXT NOT NULL,
    Aciklama TEXT,
    Modul TEXT NOT NULL,
    AltModul TEXT,
    Sira INTEGER DEFAULT 0
)
"""

PLANLAMA_ROL_ID = 32


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
    )


def _ensure_tables(con: sqlite3.Connection) -> None:
    con.execute(_DDL_SISTEM_ROL)
    con.execute(_DDL_SISTEM_YETKI)
    con.commit()


def _merge_roles_from_users(con: sqlite3.Connection) -> int:
    if not _table_exists(con, 'sistem_kullanici'):
        return 0
    added = 0
    rows = con.execute(
        """
        SELECT DISTINCT RolId, Rol
        FROM sistem_kullanici
        WHERE RolId IS NOT NULL
        """
    ).fetchall()
    for rol_id, rol_ad in rows:
        if con.execute('SELECT 1 FROM sistem_rol WHERE Id=?', (rol_id,)).fetchone():
            continue
        ad = (rol_ad or f'Test Rol {rol_id}').strip()
        superadmin = 1 if int(rol_id) == 1 else 0
        con.execute(
            """
            INSERT INTO sistem_rol (
                Id, Ad, Aciklama, Renk, Aktif, SuperAdmin, OlusturmaTarih, OlusturanKullanici
            ) VALUES (?, ?, ?, '#64748b', 1, ?, datetime('now'), 'atp_test_fixture')
            """,
            (rol_id, ad, f'Test fixture RolId={rol_id}', superadmin),
        )
        added += 1
    return added


def _fill_missing_yetki_ids(con: sqlite3.Connection) -> int:
    if not _table_exists(con, 'sistem_rol_yetki'):
        return 0
    missing = con.execute(
        """
        SELECT DISTINCT ry.YetkiId
        FROM sistem_rol_yetki ry
        LEFT JOIN sistem_yetki y ON y.Id = ry.YetkiId
        WHERE y.Id IS NULL
        ORDER BY ry.YetkiId
        """
    ).fetchall()
    added = 0
    for (yid,) in missing:
        con.execute(
            """
            INSERT INTO sistem_yetki (Id, Kod, Modul, Ad, Aciklama, Sira)
            VALUES (?, ?, 'test', ?, 'ATP test fixture placeholder yetki', ?)
            """,
            (yid, f'test.yetki.{yid}', f'Test Yetki {yid}', int(yid)),
        )
        added += 1
    return added


def _ensure_planlama_rol32(con: sqlite3.Connection) -> None:
    if con.execute('SELECT 1 FROM sistem_rol WHERE Id=?', (PLANLAMA_ROL_ID,)).fetchone():
        return
    con.execute(
        """
        INSERT INTO sistem_rol (
            Id, Ad, Aciklama, Renk, Aktif, SuperAdmin, OlusturmaTarih, OlusturanKullanici
        ) VALUES (?, 'Planlama Test', 'ATP WhatsApp fixture RolId=32', '#64748b', 1, 0,
                  datetime('now'), 'atp_test_fixture')
        """,
        (PLANLAMA_ROL_ID,),
    )


def ensure_min_auth_schema(db_path: str) -> dict[str, int]:
    """Create auth tables + minimum rows required before migration 189."""
    con = sqlite3.connect(db_path)
    try:
        _ensure_tables(con)
        n_roles = _merge_roles_from_users(con)
        n_yetki = _fill_missing_yetki_ids(con)
        _ensure_planlama_rol32(con)
        con.commit()
        return {'roles_added': n_roles, 'yetki_added': n_yetki}
    finally:
        con.close()
