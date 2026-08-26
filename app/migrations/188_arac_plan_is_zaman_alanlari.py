# -*- coding: utf-8 -*-
"""
188_arac_plan_is_zaman_alanlari.py
Araç Takip — iş bazlı zaman alanları (semantik ayrım).

SEMANTİK TANIMLAR:
  planlanan_saat         — LEGACY ALAN, KORUNUR (backfill kaynağı, yazılmaz)
  istenen_varis_saati    — canonical istenen varış (HH:mm nullable)
  istenen_saat_kaynak    — 'SISTEM' | 'MANUEL' | 'SERBEST' | 'LEGACY' | 'YOK'
  istenen_saat_manuel    — 0/1
  tahmini_varis_saati    — ETA (salt sistem, başlangıçta NULL)

BACKFILL (planlanan_saat → istenen_varis_saati, planlanan_saat DOKUNULMAZ):
  1. planlanan_saat == talep.istenen_saat  → SISTEM
  2. planlanan_saat dolu, talep.istenen_saat NULL → KULLANICI
  3. kalan dolu planlanan_saat               → LEGACY

Güvenlik:
  run(db_path) zorunlu — no-arg fallback YOK.
  SQLite DDL implicit commit: her ALTER ayrı; tekrar çalıştırma eksik kolonları tamamlar.
  Backfill yalnız istenen_varis_saati IS NULL satırlara uygulanır (ezme yok).

Bağımlılık: 187
"""
from __future__ import annotations

import sqlite3

MIGRATION_VERSION = 188

_NEW_COLS = (
    ('istenen_varis_saati', 'TEXT'),
    ('istenen_saat_kaynak', 'TEXT'),
    ('istenen_saat_manuel', 'INTEGER NOT NULL DEFAULT 0'),
    ('tahmini_varis_saati', 'TEXT'),
)


def _col_exists(con: sqlite3.Connection, table: str, col: str) -> bool:
    return any(
        r[1] == col
        for r in con.execute(f'PRAGMA table_info({table})').fetchall()
    )


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
    )


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _ensure_columns(con: sqlite3.Connection) -> int:
    """Idempotent ALTER — eksik kolonları ekle. DDL SQLite'da implicit commit."""
    added = 0
    for col, col_type in _NEW_COLS:
        if not _col_exists(con, 'arac_gunluk_plan_is', col):
            con.execute(f'ALTER TABLE arac_gunluk_plan_is ADD COLUMN {col} {col_type}')
            log(f'[188] ALTER  — arac_gunluk_plan_is.{col} ({col_type})')
            added += 1
        else:
            log(f'[188] SKIP   — arac_gunluk_plan_is.{col} zaten mevcut')
    return added


def _backfill_istenen(con: sqlite3.Connection) -> int:
    """
    planlanan_saat → istenen_varis_saati (read-only kaynak).
    Yalnız istenen_varis_saati IS NULL satırlar; planlanan_saat değişmez.
    tahmini_varis_saati DOKUNULMAZ.
    """
    pending = con.execute(
        """
        SELECT COUNT(*) FROM arac_gunluk_plan_is
        WHERE planlanan_saat IS NOT NULL
          AND TRIM(planlanan_saat) != ''
          AND istenen_varis_saati IS NULL
          AND (istenen_saat_kaynak IS NULL OR TRIM(istenen_saat_kaynak) = '')
        """
    ).fetchone()[0]
    if pending <= 0:
        log('[188] BACKFILL — gerekli değil (daha önce çalıştırıldı veya planlanan_saat boş)')
        return 0

    log(f'[188] BACKFILL — {pending} satır için istenen_varis_saati backfill...')

    # SISTEM: planlanan_saat == talep.istenen_saat (legacy talep kolonu)
    con.execute(
        """
        UPDATE arac_gunluk_plan_is
        SET istenen_varis_saati = planlanan_saat,
            istenen_saat_kaynak = 'SISTEM',
            istenen_saat_manuel = 0
        WHERE planlanan_saat IS NOT NULL
          AND TRIM(planlanan_saat) != ''
          AND istenen_varis_saati IS NULL
          AND (istenen_saat_kaynak IS NULL OR TRIM(istenen_saat_kaynak) = '')
          AND is_talebi_id IN (
              SELECT id FROM arac_is_talebi
              WHERE istenen_saat IS NOT NULL
                AND arac_gunluk_plan_is.planlanan_saat = arac_is_talebi.istenen_saat
          )
        """
    )
    sis = con.execute('SELECT changes()').fetchone()[0]
    log(f'[188]   SISTEM   = {sis} satır')

    # KULLANICI: talep.istenen_saat NULL, planlanan_saat dolu
    con.execute(
        """
        UPDATE arac_gunluk_plan_is
        SET istenen_varis_saati = planlanan_saat,
            istenen_saat_kaynak = 'KULLANICI',
            istenen_saat_manuel = 0
        WHERE planlanan_saat IS NOT NULL
          AND TRIM(planlanan_saat) != ''
          AND istenen_varis_saati IS NULL
          AND (istenen_saat_kaynak IS NULL OR TRIM(istenen_saat_kaynak) = '')
          AND is_talebi_id IN (
              SELECT id FROM arac_is_talebi WHERE istenen_saat IS NULL
          )
        """
    )
    kul = con.execute('SELECT changes()').fetchone()[0]
    log(f'[188]   KULLANICI = {kul} satır')

    # LEGACY: kalan dolu planlanan_saat
    con.execute(
        """
        UPDATE arac_gunluk_plan_is
        SET istenen_varis_saati = planlanan_saat,
            istenen_saat_kaynak = 'LEGACY',
            istenen_saat_manuel = 0
        WHERE planlanan_saat IS NOT NULL
          AND TRIM(planlanan_saat) != ''
          AND istenen_varis_saati IS NULL
          AND (istenen_saat_kaynak IS NULL OR TRIM(istenen_saat_kaynak) = '')
        """
    )
    leg = con.execute('SELECT changes()').fetchone()[0]
    log(f'[188]   LEGACY    = {leg} satır')

    total = sis + kul + leg
    log(f'[188] BACKFILL DONE — {total} satır işlendi')
    return total


def run(db_path: str, *, allow_canonical: bool = False) -> None:
    """
    db_path: absolute path to target SQLite DB (zorunlu).
    allow_canonical: True değilse canonical mock_data.db reddedilir.
    """
    from migrations._migration_db_guard import resolve_db_path

    path = resolve_db_path(db_path, allow_canonical=allow_canonical)
    log(f'[188] DB: {path}')
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        if not _table_exists(con, 'arac_gunluk_plan_is'):
            log('[188] SKIP — arac_gunluk_plan_is yok (test ortamı)')
            return

        added_cols = _ensure_columns(con)
        total_bf = _backfill_istenen(con)
        con.commit()
        log(f'[188] DONE — {added_cols} kolon eklendi, {total_bf} backfill satır, commit edildi')

    except Exception as exc:
        con.rollback()
        log(f'[188] ERROR — {exc}')
        raise
    finally:
        con.close()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Migration 188 — zaman alanları')
    parser.add_argument('--db-path', required=True, help='Hedef SQLite DB absolute path')
    parser.add_argument(
        '--allow-canonical',
        action='store_true',
        help='Canonical mock_data.db hedefine yazmaya izin ver',
    )
    args = parser.parse_args()
    run(args.db_path, allow_canonical=args.allow_canonical)
