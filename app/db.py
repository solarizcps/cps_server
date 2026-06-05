# -*- coding: utf-8 -*-
"""
CPS DEV - DB Katmani
FORCED MOCK MODE.

PLAN v2 (Korgun MSSQL) ve uretim_giris kendi baglantilarini kullanir.
Bu dosya sadece Finans, Yonetim, Grafik, Ithalat, Auth, Audit, Belge icin SQLite saglar.
"""
import sqlite3
from contextlib import contextmanager
from config import Config

# Module-level shortcut - FORCED MOCK
DB_MODE = 'mock'


def _sqlite_conn():
    conn = sqlite3.connect(Config.MOCK_DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _mssql_conn():
    try:
        import pytds
    except ImportError:
        raise RuntimeError("pytds kurulu degil. pip install python-tds")
    return pytds.connect(
        server=Config.MSSQL_HOST,
        database=Config.MSSQL_DATABASE,
        user=Config.MSSQL_USER,
        password=Config.MSSQL_PASSWORD,
        port=Config.MSSQL_PORT,
        autocommit=False,
    )


def get_conn():
    # FORCED MOCK - env bypass edildi
    _mode = 'mock'
    print(f'[DB] get_conn mode = {_mode}', flush=True)
    return _sqlite_conn() if _mode == 'mock' else _mssql_conn()


@contextmanager
def conn_cx():
    c = get_conn()
    try:
        yield c
    finally:
        try: c.close()
        except Exception: pass


def _prep_sql(sql):
    if DB_MODE == 'prod':
        return sql.replace('?', '%s')
    return sql


def _row_to_dict(row, cursor):
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        return dict(row)
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, row))


def qone(sql, params=()):
    c = get_conn()
    try:
        cur = c.cursor()
        cur.execute(_prep_sql(sql), params)
        row = cur.fetchone()
        return _row_to_dict(row, cur)
    finally:
        c.close()


def q(sql, params=()):
    c = get_conn()
    try:
        cur = c.cursor()
        cur.execute(_prep_sql(sql), params)
        rows = cur.fetchall()
        if not rows:
            return []
        if DB_MODE == 'mock':
            return [dict(r) for r in rows]
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]
    finally:
        c.close()


def qscalar(sql, params=()):
    c = get_conn()
    try:
        cur = c.cursor()
        cur.execute(_prep_sql(sql), params)
        row = cur.fetchone()
        if row is None:
            return None
        return row[0] if not isinstance(row, sqlite3.Row) else row[0]
    finally:
        c.close()


def qexec(sql, params=()):
    c = get_conn()
    try:
        cur = c.cursor()
        cur.execute(_prep_sql(sql), params)
        last = cur.lastrowid if DB_MODE == 'mock' else None
        c.commit()
        return last
    finally:
        c.close()


def qexec_many(sql, params_list):
    if not params_list:
        return 0
    c = get_conn()
    try:
        cur = c.cursor()
        cur.executemany(_prep_sql(sql), params_list)
        c.commit()
        return cur.rowcount
    finally:
        c.close()


def tablo_var_mi(tablo):
    if DB_MODE == 'mock':
        r = qone("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablo,))
    else:
        r = qone("""SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_NAME = ?""", (tablo,))
    return r is not None


def kolon_var_mi(tablo, kolon):
    if DB_MODE == 'mock':
        rows = q(f"PRAGMA table_info({tablo})")
        return any(r['name'] == kolon for r in rows)
    else:
        r = qone("""SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_NAME = ? AND COLUMN_NAME = ?""", (tablo, kolon))
        return r is not None