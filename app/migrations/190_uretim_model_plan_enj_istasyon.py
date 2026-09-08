# -*- coding: utf-8 -*-
"""
Migration 190 — uretim_model_plan_enj_istasyon child tablosu
============================================================

SORUN:
  uretim_plan_repo.py çoklu enjeksiyon istasyonu rezervasyonlarını
  uretim_model_plan_enj_istasyon tablosundan okuyup yazıyor.
  Bu tablo bazı ortamlarda (laptop test DB'si) mevcuttu; bazı ortamlarda
  (canlı kurulum, temiz yükleme) eksikti ve migration kaydı yoktu.

BU MİGRATION:
  1. Tablo yoksa kanonik şema ile oluşturur (idempotent — varsa atlar).
  2. Gerekli index yapısını oluşturur (varsa atlar).
  3. uretim_model_plan.enj_istasyon_no legacy kolonundan backfill yapar:
       INTEGER 7     → [7]
       TEXT '7'      → [7]
       TEXT '7,8'    → [7, 8]
       NULL / boş    → atla
       geçersiz token → güvenli biçimde atla, raporla
  4. Zaten var olan (plan_id, istasyon_no, enj_slot) satırı yeniden eklemez.
  5. Parent planı olmayan child satır üretmez.
  6. Mevcut plan ve kullanıcı satırlarına dokunmaz.
  7. schema_migrations version=190 kaydını yazar.
  8. Hata olursa transaction rollback.
  9. İkinci çalıştırmada hiçbir şey değişmez (tam idempotent).

BAĞIMLILIK:
  Parent tablo uretim_model_plan ve enj_makine tablosunun mevcut olduğu
  varsayılır (önceki migrationlarla kurulmuş durumda).

REFERANS ŞEMA (laptop test DB'sinden alınan CREATE SQL):
  CREATE TABLE uretim_model_plan_enj_istasyon (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      plan_id         INTEGER NOT NULL,
      enj_makine_id   INTEGER NOT NULL,
      enj_slot        TEXT NOT NULL CHECK (enj_slot IN ('A', 'B')),
      istasyon_no     INTEGER NOT NULL,
      created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
      FOREIGN KEY (plan_id) REFERENCES uretim_model_plan(id),
      UNIQUE (plan_id, istasyon_no, enj_slot)
  )
  CREATE INDEX idx_ump_enj_ist_mak_slot
    ON uretim_model_plan_enj_istasyon(enj_makine_id, enj_slot, istasyon_no)
"""
from __future__ import annotations

import os
import sqlite3
import sys

MIGRATION_VERSION = 190
TBL = 'uretim_model_plan_enj_istasyon'
IDX = 'idx_ump_enj_ist_mak_slot'
ACIKLAMA = 'enjeksiyon istasyon rezervasyon child tablosu + legacy backfill'


def _log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _ensure_table(cur: sqlite3.Cursor) -> bool:
    """Tablo yoksa oluştur. Oluşturulduysa True döner."""
    exists = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (TBL,),
    ).fetchone()
    if exists:
        _log(f'  SKIP  tablo zaten mevcut: {TBL}')
        return False
    cur.executescript(f"""
        CREATE TABLE {TBL} (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id         INTEGER NOT NULL,
            enj_makine_id   INTEGER NOT NULL,
            enj_slot        TEXT NOT NULL CHECK (enj_slot IN ('A', 'B')),
            istasyon_no     INTEGER NOT NULL,
            created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (plan_id) REFERENCES uretim_model_plan(id),
            UNIQUE (plan_id, istasyon_no, enj_slot)
        );
    """)
    _log(f'  CREATE tablo: {TBL}')
    return True


def _ensure_index(cur: sqlite3.Cursor) -> None:
    """Performance index yoksa oluştur."""
    exists = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (IDX,),
    ).fetchone()
    if exists:
        _log(f'  SKIP  index zaten mevcut: {IDX}')
        return
    cur.execute(
        f'CREATE INDEX {IDX} ON {TBL}(enj_makine_id, enj_slot, istasyon_no)'
    )
    _log(f'  CREATE index: {IDX}')


def _parse_istasyon_no(raw) -> list[int]:
    """
    enj_istasyon_no alanını normalleştir.

    Desteklenen:
      INTEGER 7      → [7]
      TEXT '7'       → [7]
      TEXT '7,8'     → [7, 8]
      None / ''      → []
      geçersiz token → [] (güvenli atla)
    """
    if raw is None:
        return []
    s = str(raw).strip()
    if not s:
        return []
    result = []
    for token in s.split(','):
        token = token.strip()
        if not token:
            continue
        try:
            v = int(token)
            if v > 0:
                result.append(v)
            else:
                _log(f'  SKIP_TOKEN negatif/sıfır istasyon: {token!r}')
        except ValueError:
            _log(f'  SKIP_TOKEN geçersiz istasyon token: {token!r}')
    return sorted(set(result))


def _backfill(cur: sqlite3.Cursor, con: sqlite3.Connection) -> dict:
    """
    uretim_model_plan.enj_istasyon_no → child tablo.

    Kurallar:
    - enj_makine_id IS NOT NULL olan aktif planları tarar.
    - Her istasyon için (plan_id, istasyon_no, enj_slot) UNIQUE kısıtı varsa
      INSERT OR IGNORE kullanır; zaten varsa duplikat oluşmaz.
    - Parent planı mevcut değilse (FK kontrolü) eklemez.
    - Backfill log'unu döner.
    """
    plans = cur.execute(
        'SELECT id, enj_makine_id, enj_slot, enj_istasyon_no '
        'FROM uretim_model_plan '
        'WHERE enj_makine_id IS NOT NULL AND aktif=1 '
        'ORDER BY id'
    ).fetchall()

    backfilled = 0
    skipped_invalid = 0
    skipped_null = 0

    for plan_id, makine_id, slot, raw in plans:
        # slot sağlamlık kontrolü
        if slot not in ('A', 'B'):
            _log(f'  SKIP  plan {plan_id} geçersiz slot={slot!r}')
            skipped_invalid += 1
            continue

        istasyonlar = _parse_istasyon_no(raw)
        if not istasyonlar:
            skipped_null += 1
            _log(f'  SKIP  plan {plan_id} enj_istasyon_no boş/NULL')
            continue

        for ist_no in istasyonlar:
            cur.execute(
                f"""
                INSERT OR IGNORE INTO {TBL}
                    (plan_id, enj_makine_id, enj_slot, istasyon_no)
                VALUES (?, ?, ?, ?)
                """,
                (plan_id, makine_id, slot, ist_no),
            )
            if cur.rowcount > 0:
                backfilled += 1
                _log(f'  BACKFILL plan {plan_id} ist={ist_no} makine={makine_id} slot={slot}')
            else:
                _log(f'  ALREADY plan {plan_id} ist={ist_no} zaten mevcut')

    return {
        'backfilled': backfilled,
        'skipped_null': skipped_null,
        'skipped_invalid': skipped_invalid,
    }


def _verify(cur: sqlite3.Cursor) -> None:
    """Tablo ve index varlığını doğrula."""
    tbl = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (TBL,),
    ).fetchone()
    if not tbl:
        raise RuntimeError(f'Doğrulama başarısız — tablo yok: {TBL}')

    idx = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (IDX,),
    ).fetchone()
    if not idx:
        raise RuntimeError(f'Doğrulama başarısız — index yok: {IDX}')

    _log(f'  VERIFY OK tablo={TBL} index={IDX}')


def run(db_path: str | None = None, *, allow_canonical: bool = False) -> dict:
    """
    Migration 190'ı uygula.

    Args:
        db_path: Hedef SQLite DB mutlak yolu (zorunlu).
        allow_canonical: True olmadan canonical mock_data.db hedefine yazılamaz.
    """
    from migrations._migration_db_guard import resolve_db_path

    path = resolve_db_path(db_path, allow_canonical=allow_canonical)
    _log('=' * 70)
    _log(f'[{MIGRATION_VERSION}] {TBL}')
    _log(f'[{MIGRATION_VERSION}] DB: {path}')
    _log('=' * 70)

    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    result = {
        'ok': False,
        'db_path': path,
        'version': MIGRATION_VERSION,
        'backfilled': 0,
        'skipped_null': 0,
        'skipped_invalid': 0,
    }
    try:
        # İdempotent guard: zaten uygulanmışsa atla
        already = cur.execute(
            'SELECT version FROM schema_migrations WHERE version=?',
            (str(MIGRATION_VERSION),),
        ).fetchone()
        if already:
            _log(f'[{MIGRATION_VERSION}] SKIP — zaten uygulanmış')
            result['ok'] = True
            result['skipped'] = True
            return result

        con.execute('BEGIN IMMEDIATE')

        _ensure_table(cur)
        _ensure_index(cur)

        bf = _backfill(cur, con)
        result.update(bf)

        _verify(cur)

        # schema_migrations kaydı
        try:
            cur.execute(
                'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                (str(MIGRATION_VERSION), ACIKLAMA),
            )
        except sqlite3.OperationalError:
            cur.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (str(MIGRATION_VERSION),),
            )

        con.commit()
        result['ok'] = True
        _log(f'[{MIGRATION_VERSION}] COMMIT OK  backfilled={result["backfilled"]}')
        return result

    except Exception as exc:
        con.rollback()
        _log(f'[{MIGRATION_VERSION}] ROLLBACK — {exc}')
        raise
    finally:
        con.close()


if __name__ == '__main__':
    import argparse
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(
        description=f'Migration {MIGRATION_VERSION} — {TBL}'
    )
    parser.add_argument('--db-path', required=True,
                        help='Hedef SQLite DB mutlak yolu')
    parser.add_argument('--allow-canonical', action='store_true',
                        help='Canonical mock_data.db hedefine yazmaya izin ver')
    args = parser.parse_args()
    result = run(args.db_path, allow_canonical=args.allow_canonical)
    print(result)
