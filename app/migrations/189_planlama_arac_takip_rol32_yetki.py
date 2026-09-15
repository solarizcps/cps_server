# -*- coding: utf-8 -*-
"""
Migration 189 — planlama.arac_takip dar yetki (RolId=32 Planlama)
==================================================================
  [1] sistem_yetki: planlama.arac_takip
  [2] sistem_rol_yetki: RolId=32 → can_view/create/update=1, manage/delete=0
  [3] schema_migrations version=189

İdempotent. user_permission_override dokunulmaz. Başka rollere atama yok.
Canonical apply bu fazda yapılmaz (resolve_db_path guard).
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 189
PLANLAMA_ROL_ID = 32
YETKI_KOD = 'planlama.arac_takip'
YETKI_MODUL = 'planlama'
YETKI_AD = 'Arac Takip Planlama'
YETKI_ACIKLAMA = 'Gunluk arac plani olusturma ve duzenleme (dar kapsam)'
YETKI_SIRA = 139

ROL32_FLAGS = {
    'Gorebilir': 1,
    'Duzenleyebilir': 0,
    'can_view': 1,
    'can_create': 1,
    'can_update': 1,
    'can_delete': 0,
    'can_approve': 0,
    'can_report': 1,
    'can_manage': 0,
}


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _ensure_yetki(cur: sqlite3.Cursor, con: sqlite3.Connection) -> int:
    row = cur.execute('SELECT Id FROM sistem_yetki WHERE Kod=?', (YETKI_KOD,)).fetchone()
    if row:
        log(f'  SKIP  sistem_yetki {YETKI_KOD} Id={row["Id"]}')
        return int(row['Id'])
    cur.execute(
        """
        INSERT INTO sistem_yetki (Kod, Modul, Ad, Aciklama, Sira)
        VALUES (?, ?, ?, ?, ?)
        """,
        (YETKI_KOD, YETKI_MODUL, YETKI_AD, YETKI_ACIKLAMA, YETKI_SIRA),
    )
    con.commit()
    yid = int(cur.execute('SELECT Id FROM sistem_yetki WHERE Kod=?', (YETKI_KOD,)).fetchone()['Id'])
    log(f'  OK    sistem_yetki {YETKI_KOD} Id={yid}')
    return yid


def _upsert_rol_yetki(cur: sqlite3.Cursor, con: sqlite3.Connection, yetki_id: int) -> None:
    rol = cur.execute(
        'SELECT Id, Ad FROM sistem_rol WHERE Id=? AND Aktif=1',
        (PLANLAMA_ROL_ID,),
    ).fetchone()
    if not rol:
        raise RuntimeError(f'RolId={PLANLAMA_ROL_ID} aktif rol bulunamadi')

    mevcut = cur.execute(
        'SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?',
        (PLANLAMA_ROL_ID, yetki_id),
    ).fetchone()
    if mevcut:
        cur.execute(
            """
            UPDATE sistem_rol_yetki
            SET Gorebilir=?, Duzenleyebilir=?,
                can_view=?, can_create=?, can_update=?, can_delete=?,
                can_approve=?, can_report=?, can_manage=?
            WHERE Id=?
            """,
            (
                ROL32_FLAGS['Gorebilir'],
                ROL32_FLAGS['Duzenleyebilir'],
                ROL32_FLAGS['can_view'],
                ROL32_FLAGS['can_create'],
                ROL32_FLAGS['can_update'],
                ROL32_FLAGS['can_delete'],
                ROL32_FLAGS['can_approve'],
                ROL32_FLAGS['can_report'],
                ROL32_FLAGS['can_manage'],
                mevcut['Id'],
            ),
        )
        log(f'  UPDATE RolId={PLANLAMA_ROL_ID} ({rol["Ad"]}) -> {YETKI_KOD}')
    else:
        cur.execute(
            """
            INSERT INTO sistem_rol_yetki (
                RolId, YetkiId, Gorebilir, Duzenleyebilir,
                can_view, can_create, can_update, can_delete,
                can_approve, can_report, can_manage
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                PLANLAMA_ROL_ID,
                yetki_id,
                ROL32_FLAGS['Gorebilir'],
                ROL32_FLAGS['Duzenleyebilir'],
                ROL32_FLAGS['can_view'],
                ROL32_FLAGS['can_create'],
                ROL32_FLAGS['can_update'],
                ROL32_FLAGS['can_delete'],
                ROL32_FLAGS['can_approve'],
                ROL32_FLAGS['can_report'],
                ROL32_FLAGS['can_manage'],
            ),
        )
        log(f'  INSERT RolId={PLANLAMA_ROL_ID} ({rol["Ad"]}) -> {YETKI_KOD}')
    con.commit()


def _verify(cur: sqlite3.Cursor) -> None:
    row = cur.execute(
        """
        SELECT ry.can_view, ry.can_create, ry.can_update, ry.can_delete, ry.can_manage
        FROM sistem_rol_yetki ry
        JOIN sistem_yetki y ON y.Id = ry.YetkiId
        WHERE ry.RolId=? AND y.Kod=?
        """,
        (PLANLAMA_ROL_ID, YETKI_KOD),
    ).fetchone()
    if not row:
        raise RuntimeError('Dogrulama basarisiz — rol yetki kaydi yok')
    for key, expected in (
        ('can_view', 1),
        ('can_create', 1),
        ('can_update', 1),
        ('can_delete', 0),
        ('can_manage', 0),
    ):
        if int(row[key] or 0) != expected:
            raise RuntimeError(f'Dogrulama basarisiz — {key}={row[key]} beklenen={expected}')
    log(f'  VERIFY OK RolId={PLANLAMA_ROL_ID} {YETKI_KOD}')


def run(db_path: str | None = None, *, allow_canonical: bool = False) -> dict:
    from migrations._migration_db_guard import resolve_db_path

    path = resolve_db_path(db_path, allow_canonical=allow_canonical)
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] planlama.arac_takip RolId=32')
    log(f'[{MIGRATION_VERSION}] DB: {path}')
    log('=' * 70)

    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    result = {'ok': False, 'db_path': path}
    try:
        con.execute('BEGIN IMMEDIATE')
        yetki_id = _ensure_yetki(cur, con)
        _upsert_rol_yetki(cur, con, yetki_id)
        _verify(cur)
        try:
            cur.execute(
                'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                (MIGRATION_VERSION, f'{YETKI_KOD} RolId=32 dar ATP yetkisi'),
            )
        except sqlite3.OperationalError:
            cur.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (MIGRATION_VERSION,),
            )
        con.commit()
        result['ok'] = True
        log(f'[{MIGRATION_VERSION}] COMMIT OK')
        return result
    except Exception as exc:
        con.rollback()
        log(f'[{MIGRATION_VERSION}] ROLLBACK — {exc}')
        raise
    finally:
        con.close()


if __name__ == '__main__':
    import argparse
    import io
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Migration 189 — planlama.arac_takip RolId=32')
    parser.add_argument('--db-path', required=True, help='Hedef SQLite DB absolute path')
    parser.add_argument(
        '--allow-canonical',
        action='store_true',
        help='Canonical mock_data.db hedefine yazmaya izin ver',
    )
    args = parser.parse_args()
    print(run(args.db_path, allow_canonical=args.allow_canonical))
