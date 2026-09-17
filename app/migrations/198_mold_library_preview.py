# -*- coding: utf-8 -*-
"""
Migration 198 — Mold Library preview tabloları (Option C, PHASE_5 additive).
Legacy enj_kalip tablosuna dokunmaz.
"""
from __future__ import annotations

import sqlite3
import sys

MIGRATION_VERSION = 198
ACIKLAMA = "mold_library_mold + series + image + legacy_map + audit (preview)"

DDL = """
CREATE TABLE IF NOT EXISTS mold_library_mold (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    library_uuid            TEXT NOT NULL UNIQUE,
    material_group          TEXT NOT NULL CHECK (material_group IN ('EVA','POLI')),
    legacy_enj_kalip_id     INTEGER NULL REFERENCES enj_kalip(id),
    model_code              TEXT NOT NULL,
    inventory_code          TEXT NULL,
    visible_mold_code       TEXT NOT NULL,
    product_type_raw        TEXT NULL,
    product_category        TEXT NULL,
    product_family          TEXT NULL,
    product_variant         TEXT NULL,
    component_role          TEXT NULL,
    component_role_source   TEXT NULL,
    assortment              TEXT NULL,
    working_status          TEXT NULL,
    separate_upper_mold     INTEGER NULL,
    pairs_per_cycle         REAL NULL,
    weight_reference_size   TEXT NULL,
    weight_grams            REAL NULL,
    cycle_time_minutes      REAL NULL,
    note                    TEXT NULL,
    image_present           INTEGER NOT NULL DEFAULT 0,
    source_file_sha256      TEXT NOT NULL,
    source_main_row         INTEGER NOT NULL,
    source_seq              INTEGER NULL,
    business_key            TEXT NOT NULL UNIQUE,
    review_status           TEXT NOT NULL,
    activation_block_reason TEXT NULL,
    is_archived             INTEGER NOT NULL DEFAULT 0,
    archive_reason          TEXT NULL,
    archived_at             TEXT NULL,
    archived_by             TEXT NULL,
    row_version             INTEGER NOT NULL DEFAULT 1,
    created_at              TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    created_by              TEXT NULL,
    updated_at              TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_by              TEXT NULL,
    UNIQUE (source_file_sha256, source_main_row)
);

CREATE INDEX IF NOT EXISTS idx_mlm_material ON mold_library_mold(material_group);
CREATE INDEX IF NOT EXISTS idx_mlm_model_status ON mold_library_mold(model_code, material_group, working_status);
CREATE INDEX IF NOT EXISTS idx_mlm_visible_code ON mold_library_mold(visible_mold_code);
CREATE INDEX IF NOT EXISTS idx_mlm_business_key ON mold_library_mold(business_key);
CREATE INDEX IF NOT EXISTS idx_mlm_legacy ON mold_library_mold(legacy_enj_kalip_id);
CREATE INDEX IF NOT EXISTS idx_mlm_archived ON mold_library_mold(is_archived);

CREATE TABLE IF NOT EXISTS mold_library_series (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    mold_library_uuid        TEXT NOT NULL REFERENCES mold_library_mold(library_uuid) ON DELETE CASCADE,
    display_order            INTEGER NOT NULL,
    numara_asorti            TEXT NOT NULL,
    kalip_adedi              INTEGER NULL CHECK (kalip_adedi IS NULL OR kalip_adedi > 0),
    cevrim_basina_cikis_cift INTEGER NULL CHECK (cevrim_basina_cikis_cift IS NULL OR cevrim_basina_cikis_cift > 0),
    source_col               TEXT NULL,
    created_at               TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (mold_library_uuid, display_order)
);

CREATE INDEX IF NOT EXISTS idx_mls_mold ON mold_library_series(mold_library_uuid);

CREATE TABLE IF NOT EXISTS mold_library_image (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    mold_library_uuid TEXT NOT NULL REFERENCES mold_library_mold(library_uuid) ON DELETE CASCADE,
    storage_key       TEXT NOT NULL,
    original_filename TEXT NULL,
    mime_type         TEXT NULL,
    sha256            TEXT NULL,
    display_order     INTEGER NOT NULL DEFAULT 1,
    is_primary        INTEGER NOT NULL DEFAULT 1,
    source_anchor     TEXT NULL,
    match_method      TEXT NULL,
    created_at        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (mold_library_uuid, sha256)
);

CREATE INDEX IF NOT EXISTS idx_mli_mold ON mold_library_image(mold_library_uuid);

CREATE TABLE IF NOT EXISTS mold_library_legacy_map (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    mold_library_uuid    TEXT NOT NULL REFERENCES mold_library_mold(library_uuid) ON DELETE CASCADE,
    legacy_enj_kalip_id  INTEGER NOT NULL REFERENCES enj_kalip(id),
    match_status         TEXT NOT NULL,
    match_evidence       TEXT NULL,
    approved_by          TEXT NULL,
    approved_at          TEXT NULL,
    UNIQUE (mold_library_uuid, legacy_enj_kalip_id)
);

CREATE TABLE IF NOT EXISTS mold_library_audit (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    mold_library_uuid TEXT NOT NULL,
    action            TEXT NOT NULL,
    changed_at        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    changed_by        TEXT NULL,
    change_reason     TEXT NULL,
    before_json       TEXT NULL,
    after_json        TEXT NULL,
    field_changes     TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_mla_uuid ON mold_library_audit(mold_library_uuid, changed_at);
"""


def _log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


def _write_migration_record(cur: sqlite3.Cursor) -> None:
    try:
        cur.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)",
            (str(MIGRATION_VERSION), ACIKLAMA),
        )
    except sqlite3.OperationalError:
        cur.execute(
            "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
            (str(MIGRATION_VERSION),),
        )


def run(db_path: str | None = None, *, allow_canonical: bool = False, _inject_failure: bool = False) -> dict:
    from migrations._migration_db_guard import resolve_db_path

    path = resolve_db_path(db_path, allow_canonical=allow_canonical)
    _log("=" * 70)
    _log(f"[{MIGRATION_VERSION}] Mold Library preview schema")
    _log(f"[{MIGRATION_VERSION}] DB: {path}")
    _log("=" * 70)

    con = sqlite3.connect(path, timeout=15, isolation_level=None)
    cur = con.cursor()
    result: dict = {"ok": False, "db_path": path, "version": MIGRATION_VERSION}
    try:
        already = cur.execute(
            "SELECT version FROM schema_migrations WHERE version=?",
            (str(MIGRATION_VERSION),),
        ).fetchone()
        if already:
            _log(f"[{MIGRATION_VERSION}] SKIP — zaten uygulanmış")
            result.update({"ok": True, "skipped": True})
            return result

        if _inject_failure:
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("CREATE TABLE IF NOT EXISTS _mig198_rollback_probe (id INTEGER)")
            raise RuntimeError("_inject_failure: rollback testi")
        cur.executescript(DDL)
        cur.execute("BEGIN IMMEDIATE")
        _write_migration_record(cur)
        cur.execute("COMMIT")
        result["ok"] = True
        _log(f"[{MIGRATION_VERSION}] COMMIT OK")
        return result
    except Exception as exc:
        try:
            cur.execute("ROLLBACK")
        except Exception:
            pass
        _log(f"[{MIGRATION_VERSION}] ROLLBACK — {exc}")
        raise
    finally:
        con.close()


if __name__ == "__main__":
    import argparse
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=f"Migration {MIGRATION_VERSION}")
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--allow-canonical", action="store_true")
    args = parser.parse_args()
    print(run(args.db_path, allow_canonical=args.allow_canonical))
