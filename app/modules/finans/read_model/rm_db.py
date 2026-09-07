# -*- coding: utf-8 -*-
"""
Read-Model SQLite bağlantı yöneticisi.

Web okuyucu: read-only URI ile açar, DB veya dizin oluşturmaz.
Refresh CLI: read-write açar, gerekirse dizin oluşturur.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Generator, Optional

from .rm_config import get_rm_path, _reject_canonical_path
from .rm_schema import bootstrap_schema, verify_schema_version


# ─── Web (read-only) bağlantı ────────────────────────────────────────────────

@contextmanager
def open_readonly(path: Optional[str] = None) -> Generator[Optional[sqlite3.Connection], None, None]:
    """
    Read-only bağlantı context manager.

    Snapshot yoksa veya DB dosyası mevcut değilse None döner (web kodu
    "henüz hazır değil" durumunu göstermelidir).

    Hiçbir zaman dizin veya DB oluşturmaz.
    """
    db_path = path or get_rm_path()
    _reject_canonical_path(db_path)

    if not os.path.isfile(db_path):
        yield None
        return

    conn: Optional[sqlite3.Connection] = None
    try:
        # SQLite URI ile read-only aç (Python 3.4+)
        uri = "file:" + db_path.replace("\\", "/") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        yield conn
    except sqlite3.OperationalError:
        # DB dosyası var ama açılamıyorsa (kilit, corrupt) → None döndür
        yield None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ─── CLI (read-write) bağlantı ───────────────────────────────────────────────

@contextmanager
def open_readwrite(path: Optional[str] = None) -> Generator[sqlite3.Connection, None, None]:
    """
    Read-write bağlantı context manager (yalnız CLI / refresh worker için).

    Gerekirse runtime dizinini oluşturur.
    Schema bootstrap ve version doğrulama yapar.
    """
    db_path = path or get_rm_path()
    _reject_canonical_path(db_path)

    # Dizin yoksa oluştur (yalnız CLI yetkisi var)
    dir_path = os.path.dirname(db_path)
    if dir_path and not os.path.isdir(dir_path):
        os.makedirs(dir_path, exist_ok=True)

    conn: Optional[sqlite3.Connection] = None
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        bootstrap_schema(conn)
        yield conn
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ─── Snapshot sorgulama (web okuma) ──────────────────────────────────────────

def get_active_snapshot_id(conn: sqlite3.Connection, direction: str = "PAYABLE") -> Optional[str]:
    """rm_pointer tablosundan aktif snapshot id'sini döner."""
    row = conn.execute(
        "SELECT active_snapshot_id FROM rm_pointer WHERE direction=?",
        (direction,),
    ).fetchone()
    if row and row[0]:
        return row[0]
    return None


def get_snapshot_header(
    conn: sqlite3.Connection,
    snapshot_id: str,
) -> Optional[sqlite3.Row]:
    """Snapshot üst veri satırını döner."""
    return conn.execute(
        "SELECT * FROM rm_snapshot WHERE snapshot_id=?",
        (snapshot_id,),
    ).fetchone()


def get_refresh_control(
    conn: sqlite3.Connection,
    direction: str = "PAYABLE",
) -> Optional[sqlite3.Row]:
    """rm_refresh_control satırını döner."""
    return conn.execute(
        "SELECT * FROM rm_refresh_control WHERE direction=?",
        (direction,),
    ).fetchone()
