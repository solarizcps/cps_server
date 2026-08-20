# -*- coding: utf-8 -*-
"""
170_odeme_plani_ibrahim_view.py
================================
P2 — İbrahim Kılıç (user_id=36) için Ödeme Planı VIEW override.

Yalnız finans.odeme_plani.write : can_view
İdari İşler rolüne geniş finans yetkisi VERİLMEZ.
Hardcoded route guard YOK — canonical user_permission_override.
"""
from __future__ import annotations

import datetime
import os
import sqlite3

MIGRATION_VERSION = 170
IBRAHIM_USER_ID = 36
YETKI_KOD = 'finans.odeme_plani.write'


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _yetki_id(con: sqlite3.Connection, kod: str) -> int | None:
    row = con.execute('SELECT Id FROM sistem_yetki WHERE Kod=?', (kod,)).fetchone()
    return int(row['Id']) if row else None


def _user_active(con: sqlite3.Connection, user_id: int) -> bool:
    row = con.execute(
        'SELECT Id FROM sistem_kullanici WHERE Id=? AND Aktif=1', (user_id,),
    ).fetchone()
    return bool(row)


def _upsert_override(con: sqlite3.Connection, user_id: int, yetki_id: int) -> str:
    mevcut = con.execute(
        """
        SELECT Id, can_view, can_create, can_update, can_delete,
               can_approve, can_report, can_manage
        FROM user_permission_override
        WHERE KullaniciId=? AND YetkiId=?
        """,
        (user_id, yetki_id),
    ).fetchone()
    cv, cc, cu, cd, ca, cr, cm = 1, 0, 0, 0, 0, 0, 0
    if mevcut:
        if int(mevcut['can_view'] or 0) == cv and all(int(mevcut[k] or 0) == 0 for k in (
            'can_create', 'can_update', 'can_delete', 'can_approve', 'can_report', 'can_manage'
        )):
            return 'SKIP'
        con.execute(
            """
            UPDATE user_permission_override
            SET can_view=?, can_create=?, can_update=?, can_delete=?,
                can_approve=?, can_report=?, can_manage=?
            WHERE Id=?
            """,
            (cv, cc, cu, cd, ca, cr, cm, mevcut['Id']),
        )
        return 'UPDATE'
    con.execute(
        """
        INSERT INTO user_permission_override
            (KullaniciId, YetkiId, can_view, can_create, can_update,
             can_delete, can_approve, can_report, can_manage)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, yetki_id, cv, cc, cu, cd, ca, cr, cm),
    )
    return 'INSERT'


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 60)
    log(f'[{MIGRATION_VERSION}] odeme_plani_ibrahim_view')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if not _user_active(con, IBRAHIM_USER_ID):
            log(f'[{MIGRATION_VERSION}] WARN user_id={IBRAHIM_USER_ID} aktif değil — atlandı')
            return
        yid = _yetki_id(con, YETKI_KOD)
        if not yid:
            log(f'[{MIGRATION_VERSION}] WARN yetki {YETKI_KOD} bulunamadı — atlandı')
            return
        action = _upsert_override(con, IBRAHIM_USER_ID, yid)
        log(f'[{MIGRATION_VERSION}] ibrahim override {YETKI_KOD}:can_view → {action}')
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
