# -*- coding: utf-8 -*-
"""
152_mo_tahsilat_cek_vade_kontrol.py
=====================================
FAZ-VADE-KONTROL-V1

Schema extension:
  - Yeni tablo: mo_tahsilat_cek (cek bazli child satirlar)
  - Parent extension: mo_tahsilat_kayit +5 snapshot kolon

Idempotent. Mevcut NAKIT kayitlarina backfill yok.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 152


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
    )


def _column_exists(con: sqlite3.Connection, table: str, column: str) -> bool:
    if not _table_exists(con, table):
        return False
    return column in [c[1] for c in con.execute(f"PRAGMA table_info({table})").fetchall()]


# ---------------------------------------------------------------------------
# mo_tahsilat_cek (new child table)
# ---------------------------------------------------------------------------

def _ensure_mo_tahsilat_cek(con: sqlite3.Connection) -> None:
    if _table_exists(con, "mo_tahsilat_cek"):
        log(f"[{MIGRATION_VERSION}] mo_tahsilat_cek already exists — skip")
        return
    con.execute(
        """
        CREATE TABLE mo_tahsilat_cek (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            tahsilat_kayit_id       INTEGER NOT NULL,
            sira_no                 INTEGER NOT NULL DEFAULT 1,
            tutar                   REAL NOT NULL,
            para_birimi             TEXT NOT NULL,
            cek_alim_tarihi         TEXT NOT NULL,
            gercek_cek_vade_tarihi  TEXT NOT NULL,
            odeme_referansi         TEXT,
            banka_adi               TEXT,
            durum                   TEXT NOT NULL DEFAULT 'AKTIF',
            aktif                   INTEGER NOT NULL DEFAULT 1,
            idempotency_key         TEXT UNIQUE,
            olusturan_id            INTEGER,
            olusturma_tarihi        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            guncelleme_tarihi       TEXT,
            audit_json              TEXT,
            CHECK (durum IN ('AKTIF', 'IPTAL')),
            CHECK (aktif IN (0, 1)),
            FOREIGN KEY (tahsilat_kayit_id) REFERENCES mo_tahsilat_kayit(id)
        )
        """
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_mtc_kayit_aktif "
        "ON mo_tahsilat_cek(tahsilat_kayit_id, aktif)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_mtc_kayit "
        "ON mo_tahsilat_cek(tahsilat_kayit_id)"
    )
    log(f"[{MIGRATION_VERSION}] mo_tahsilat_cek created")


# ---------------------------------------------------------------------------
# mo_tahsilat_kayit parent extension (+5 snapshot columns)
# ---------------------------------------------------------------------------

PARENT_KOLONLAR = (
    ("paket_hedef_tutar",           "REAL"),
    ("para_birimi",                 "TEXT"),
    ("onaylanan_vade_gun_snapshot", "INTEGER"),
    ("gercek_sevk_tarihi_snapshot", "TEXT"),
    ("hedef_vade_tarihi",           "TEXT"),
)


def _ensure_parent_columns(con: sqlite3.Connection) -> None:
    if not _table_exists(con, "mo_tahsilat_kayit"):
        log(f"[{MIGRATION_VERSION}] mo_tahsilat_kayit missing — parent extension skipped")
        return
    for col, typ in PARENT_KOLONLAR:
        if _column_exists(con, "mo_tahsilat_kayit", col):
            continue
        con.execute(f"ALTER TABLE mo_tahsilat_kayit ADD COLUMN {col} {typ}")
        log(f"[{MIGRATION_VERSION}] mo_tahsilat_kayit: kolon eklendi: {col}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "mock_data.db")
        )
    log("=" * 70)
    log(f"[{MIGRATION_VERSION}] mo_tahsilat_cek + parent snapshot columns")
    log(f"[{MIGRATION_VERSION}] DB: {db_path}")
    log("=" * 70)

    con = sqlite3.connect(db_path, timeout=30)
    try:
        if _table_exists(con, "schema_migrations"):
            applied = con.execute(
                "SELECT version FROM schema_migrations WHERE version=?",
                (MIGRATION_VERSION,),
            ).fetchone()
            if (
                applied
                and _table_exists(con, "mo_tahsilat_cek")
                and _column_exists(con, "mo_tahsilat_kayit", "paket_hedef_tutar")
            ):
                log(f"[{MIGRATION_VERSION}] SKIP — idempotent")
                return

        con.execute("BEGIN IMMEDIATE")
        _ensure_mo_tahsilat_cek(con)
        _ensure_parent_columns(con)
        if _table_exists(con, "schema_migrations"):
            con.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (MIGRATION_VERSION,),
            )
        con.commit()
        log(f"[{MIGRATION_VERSION}] OK")
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == "__main__":
    run()
