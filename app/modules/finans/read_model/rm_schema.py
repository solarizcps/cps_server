# -*- coding: utf-8 -*-
"""
Read-Model SQLite şeması — idempotent bootstrap.

Tablolar:
  - rm_snapshot       : snapshot üst veri + KPI özeti
  - rm_snapshot_row   : cari satırları
  - rm_refresh_control: tek satır lease/lock + nesil pointer'ları
  - rm_pointer        : direction → active / last_success id'leri

Canonical DB'ye tablo eklenmez. Bu şema yalnızca izole read-model DB'sinde.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from .rm_config import SCHEMA_VERSION


# ─── DDL ─────────────────────────────────────────────────────────────────────

_DDL_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS rm_snapshot (
    snapshot_id         TEXT PRIMARY KEY,          -- UUID v4
    direction           TEXT NOT NULL,             -- 'PAYABLE'
    status              TEXT NOT NULL,             -- STAGING | ACTIVE | SUPERSEDED | FAILED
    schema_version      INTEGER NOT NULL,
    refresh_started_at  TEXT,                      -- ISO-8601
    refresh_completed_at TEXT,
    published_at        TEXT,
    source_duration_ms  INTEGER,                   -- fetch_supplier_balances_bundle() süresi
    source_hash         TEXT,                      -- deterministic hash (parity doğrulama)
    row_count           INTEGER DEFAULT 0,
    unique_cari_count   INTEGER DEFAULT 0,
    company_count       INTEGER DEFAULT 0,
    currency_count      INTEGER DEFAULT 0,
    kpi_json            TEXT,                      -- JSON blob (toplam_acik_borc vb.)
    error_code          TEXT,
    error_message       TEXT,                      -- sanitize edilmiş
    created_at          TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
)
"""

_DDL_SNAPSHOT_ROW = """
CREATE TABLE IF NOT EXISTS rm_snapshot_row (
    row_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id     TEXT NOT NULL REFERENCES rm_snapshot(snapshot_id),
    location        TEXT NOT NULL,                 -- şirket kodu: SA001, YN001, YP001
    location_label  TEXT,
    cari_kod        TEXT NOT NULL,                 -- 320.XX.XXX
    cari_adi        TEXT,
    para_birimi     TEXT NOT NULL,                 -- TRY, USD, EUR ...
    borc            TEXT NOT NULL DEFAULT '0',     -- Decimal string (float yasak)
    alacak          TEXT NOT NULL DEFAULT '0',
    net             TEXT NOT NULL DEFAULT '0',     -- net = alacak - borc (KorgunFinanceAdapter semantiği)
    canonical_key   TEXT,                          -- location:cari_kod:para_birimi
    bakiye_durumu   TEXT,                          -- Açık Borç | Alacaklıyız | Bakiye Yok
    display_bakiye  TEXT,                          -- abs(net) Decimal string
    -- V2: Layer2 enrichment (refresh sırasında yazılır; web request Korgün çağırmaz)
    fa_tarih        TEXT,   -- Son Finansal Aksiyon tarihi (ISO)
    fa_turu         TEXT,   -- Çek | Banka | Havale ...
    fa_tutar        TEXT,   -- Decimal string
    fa_pb           TEXT,
    fa_vade         TEXT,   -- ISO, yalnız çek
    fa_is_cek       INTEGER DEFAULT 0,
    fa_vade_short   TEXT,
    fa_cek_no       TEXT,
    son_odeme_tarih TEXT,
    son_odeme_tutar TEXT,
    son_odeme_pb    TEXT,
    son_alim_tarih  TEXT,
    son_alim_tutar  TEXT,
    son_alim_pb     TEXT,
    son_alim_tip    TEXT,
    son_cek_vade    TEXT,
    son_cek_tutar   TEXT,
    son_cek_pb      TEXT,
    son_cek_no      TEXT,
    aktif_takip     INTEGER DEFAULT 0,
    karar_badge     TEXT,
    karar_class     TEXT,
    karar_aksiyon   TEXT,
    anlasma_durumu  TEXT,
    vade_has_term   INTEGER DEFAULT 0,
    vade_gun        INTEGER,
    soz_has_active  INTEGER DEFAULT 0,
    soz_is_overdue  INTEGER DEFAULT 0,
    temas_tarih_iso TEXT,
    -- CPS enrichment overlay (reader'da local DB'den yazılır — V2 plan için yer tutucu)
    enrichment_json TEXT
)
"""

_DDL_REFRESH_CONTROL = """
CREATE TABLE IF NOT EXISTS rm_refresh_control (
    direction               TEXT PRIMARY KEY,      -- 'PAYABLE'
    state                   TEXT NOT NULL DEFAULT 'IDLE',
                                                   -- IDLE | RUNNING | QUEUED_MANUAL
    lock_owner              TEXT,                  -- CLI process id / hostname
    heartbeat_at            TEXT,
    lease_expires_at        TEXT,                  -- ISO-8601; geçmişte ise stale
    active_snapshot_id      TEXT,
    last_success_id         TEXT,                  -- "current" başarılı nesil
    prev_success_id         TEXT,                  -- "previous" başarılı nesil
    last_attempt_id         TEXT,
    last_success_at         TEXT,                  -- ISO-8601
    last_attempt_at         TEXT,
    last_error              TEXT,                  -- sanitize edilmiş
    updated_at              TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
)
"""

_DDL_POINTER = """
CREATE TABLE IF NOT EXISTS rm_pointer (
    direction           TEXT PRIMARY KEY,
    active_snapshot_id  TEXT,
    last_success_id     TEXT,
    updated_at          TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
)
"""

# ─── İndeksler ────────────────────────────────────────────────────────────────

_DDL_INDEXES = [
    # active snapshot hızlı erişim
    "CREATE INDEX IF NOT EXISTS idx_rm_snap_direction_status ON rm_snapshot(direction, status)",
    # pagination / filtre
    "CREATE INDEX IF NOT EXISTS idx_rm_row_snapshot ON rm_snapshot_row(snapshot_id)",
    "CREATE INDEX IF NOT EXISTS idx_rm_row_location ON rm_snapshot_row(snapshot_id, location)",
    "CREATE INDEX IF NOT EXISTS idx_rm_row_cari ON rm_snapshot_row(snapshot_id, cari_kod)",
    "CREATE INDEX IF NOT EXISTS idx_rm_row_pb ON rm_snapshot_row(snapshot_id, para_birimi)",
    "CREATE INDEX IF NOT EXISTS idx_rm_row_canonical ON rm_snapshot_row(snapshot_id, canonical_key)",
    # cari adi arama
    "CREATE INDEX IF NOT EXISTS idx_rm_row_cari_adi ON rm_snapshot_row(snapshot_id, cari_adi COLLATE NOCASE)",
]

# ─── Schema metadata ─────────────────────────────────────────────────────────

_DDL_META = """
CREATE TABLE IF NOT EXISTS rm_schema_meta (
    key     TEXT PRIMARY KEY,
    value   TEXT
)
"""

# ─── Bootstrap ───────────────────────────────────────────────────────────────

def bootstrap_schema(conn: sqlite3.Connection) -> None:
    """
    Şemayı idempotent olarak oluşturur/doğrular.
    Var olan tablolara dokunmaz (sadece CREATE IF NOT EXISTS).
    Schema version doğrular; uyumsuzsa RuntimeError.
    """
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.execute(_DDL_SNAPSHOT)
    conn.execute(_DDL_SNAPSHOT_ROW)
    conn.execute(_DDL_REFRESH_CONTROL)
    conn.execute(_DDL_POINTER)
    conn.execute(_DDL_META)

    for idx_ddl in _DDL_INDEXES:
        conn.execute(idx_ddl)

    # Schema version kaydet / doğrula
    existing = conn.execute(
        "SELECT value FROM rm_schema_meta WHERE key='schema_version'"
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO rm_schema_meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    else:
        stored = int(existing[0])
        if stored != SCHEMA_VERSION:
            raise RuntimeError(
                f"Read-model schema version uyumsuz: beklenen={SCHEMA_VERSION}, "
                f"mevcut={stored}. Eski read-model silinip yeniden oluşturulabilir."
            )

    # rm_refresh_control — PAYABLE satırı yoksa seed et
    exists = conn.execute(
        "SELECT 1 FROM rm_refresh_control WHERE direction='PAYABLE'"
    ).fetchone()
    if not exists:
        conn.execute(
            """INSERT INTO rm_refresh_control(direction, state)
               VALUES('PAYABLE', 'IDLE')"""
        )
        conn.commit()

    # rm_pointer — PAYABLE satırı yoksa seed et
    exists_ptr = conn.execute(
        "SELECT 1 FROM rm_pointer WHERE direction='PAYABLE'"
    ).fetchone()
    if not exists_ptr:
        conn.execute(
            "INSERT INTO rm_pointer(direction) VALUES('PAYABLE')"
        )
        conn.commit()


def verify_schema_version(conn: sqlite3.Connection) -> None:
    """Mevcut şema versiyonunu doğrular. Yanlışsa RuntimeError."""
    row = conn.execute(
        "SELECT value FROM rm_schema_meta WHERE key='schema_version'"
    ).fetchone()
    if row is None:
        raise RuntimeError("rm_schema_meta bulunamadı — DB bozuk veya bootstrap yapılmamış.")
    stored = int(row[0])
    if stored != SCHEMA_VERSION:
        raise RuntimeError(
            f"Schema version uyumsuz: beklenen={SCHEMA_VERSION}, mevcut={stored}"
        )
