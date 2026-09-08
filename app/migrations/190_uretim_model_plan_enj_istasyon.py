# -*- coding: utf-8 -*-
"""
Migration 190 — uretim_model_plan enj_* kolonları + child tablo
===============================================================

SORUN (2 ayrı root cause):

  RC-1: Migration parent enj_* kolonlarının zaten var olduğunu varsayıyordu.
        Gerçek server eski şemasında (31ca09d baseline) bu kolonlar yoktu.
        Backfill sırasında "no such column: enj_makine_id" hatası verdi.

  RC-2: Önceki sürüm DDL için executescript() kullanıyordu.
        executescript() her zaman önce COMMIT yapar (Python sqlite3 spec).
        Bu nedenle hata sonrası rollback, DDL değişikliklerini geri almıyordu;
        child tablo/index DB'de kalıyordu.

DÜZELTME:
  - executescript() kullanılmıyor; tüm DDL ve DML tek connection üzerinde
    ayrı execute() çağrılarıyla yapılıyor.
  - Her ADD COLUMN önce PRAGMA table_info ile idempotent kontrol edilir.
  - Tek BEGIN IMMEDIATE transaction — commit ya da tam rollback.

ÇALIŞMA SIRASI:
  1. Canonical guard ile mutlak DB yolunu doğrula.
  2. BEGIN IMMEDIATE ile tek transaction aç.
  3. uretim_model_plan varlığını doğrula.
  4. Her enj_* kolonu için: yoksa ADD COLUMN, varsa atla.
  5. Child tabloyu CREATE TABLE IF NOT EXISTS ile oluştur.
  6. Index'i CREATE INDEX IF NOT EXISTS ile oluştur.
  7. Legacy enj_istasyon_no → child tablo backfill (INSERT OR IGNORE).
  8. schema_migrations version=190 INSERT OR IGNORE.
  9. COMMIT.
  10. Herhangi bir hata: ROLLBACK → parent kolonlar da geri alınır.

UYUMLULUK DURUMLARI:
  A. Gerçek eski server şeması: enj_* yok, child yok  → tam kurulum
  B. Yarım kalmış: child/index var, enj_* yok          → kolonlar eklenir, child korunur
  C. Modern laptop şeması: enj_* var, child var         → backfill + kayıt
  D. Tam kurulu: enj_* var, child var, kayıt var        → no-op (SKIP)

REFERANS ŞEMA (kanıtlanmış):
  enj_makine_id         INTEGER  NULL  DEFAULT None
  enj_istasyon_no       INTEGER  NULL  DEFAULT None
  enj_slot              TEXT     NULL  DEFAULT None
  enj_kalip_id          INTEGER  NULL  DEFAULT None
  enj_kalip_kod         TEXT     NULL  DEFAULT None
  enj_aktif_goz         INTEGER  NULL  DEFAULT None
  enj_kalip_basi_cift   INTEGER  NULL  DEFAULT None
  enj_tur_cift          INTEGER  NULL  DEFAULT None
  enj_gunluk_tur_plan   INTEGER  NULL  DEFAULT None
  enj_gunluk_kapasite   INTEGER  NULL  DEFAULT None
  enj_plan_baslangic    TEXT     NULL  DEFAULT None
  enj_plan_bitis        TEXT     NULL  DEFAULT None
  enj_tahmini_gun       REAL     NULL  DEFAULT None
  enj_planlanacak_cift  REAL     NULL  DEFAULT None
  enj_calisma_modu      TEXT     NULL  DEFAULT None
  enj_hafta_sonu_calisma TEXT    NULL  DEFAULT None
  enj_hafta_sonu_vardiya TEXT    NULL  DEFAULT None
  enj_kapasite_snapshot TEXT     NULL  DEFAULT None

  Child table CREATE SQL (kanıtlanmış):
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
  Index: CREATE INDEX idx_ump_enj_ist_mak_slot
           ON uretim_model_plan_enj_istasyon(enj_makine_id, enj_slot, istasyon_no)
"""
from __future__ import annotations

import sqlite3
import sys

MIGRATION_VERSION = 190
PARENT_TABLE = 'uretim_model_plan'
CHILD_TABLE = 'uretim_model_plan_enj_istasyon'
INDEX_NAME = 'idx_ump_enj_ist_mak_slot'
ACIKLAMA = 'enj_* parent kolonlari + istasyon rezervasyon child tablosu + legacy backfill'

# (kolon_adi, sqlite_type)  — hepsi NULL, DEFAULT yok
# Sıra: referans DB'nin kolon sırası
ENJ_PARENT_COLUMNS: list[tuple[str, str]] = [
    ('enj_makine_id',         'INTEGER'),
    ('enj_istasyon_no',       'INTEGER'),
    ('enj_slot',              'TEXT'),
    ('enj_kalip_id',          'INTEGER'),
    ('enj_kalip_kod',         'TEXT'),
    ('enj_aktif_goz',         'INTEGER'),
    ('enj_kalip_basi_cift',   'INTEGER'),
    ('enj_tur_cift',          'INTEGER'),
    ('enj_gunluk_tur_plan',   'INTEGER'),
    ('enj_gunluk_kapasite',   'INTEGER'),
    ('enj_plan_baslangic',    'TEXT'),
    ('enj_plan_bitis',        'TEXT'),
    ('enj_tahmini_gun',       'REAL'),
    ('enj_planlanacak_cift',  'REAL'),
    ('enj_calisma_modu',      'TEXT'),
    ('enj_hafta_sonu_calisma','TEXT'),
    ('enj_hafta_sonu_vardiya','TEXT'),
    ('enj_kapasite_snapshot', 'TEXT'),
]

CHILD_CREATE_SQL = f"""CREATE TABLE IF NOT EXISTS {CHILD_TABLE} (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         INTEGER NOT NULL,
    enj_makine_id   INTEGER NOT NULL,
    enj_slot        TEXT NOT NULL CHECK (enj_slot IN ('A', 'B')),
    istasyon_no     INTEGER NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (plan_id) REFERENCES {PARENT_TABLE}(id),
    UNIQUE (plan_id, istasyon_no, enj_slot)
)"""

INDEX_CREATE_SQL = (
    f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} "
    f"ON {CHILD_TABLE}(enj_makine_id, enj_slot, istasyon_no)"
)


def _log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _existing_columns(cur: sqlite3.Cursor, table: str) -> set[str]:
    """Tablonun mevcut kolon adlarını döndür."""
    return {r[1] for r in cur.execute(f'PRAGMA table_info({table})').fetchall()}


def _table_exists(cur: sqlite3.Cursor, name: str) -> bool:
    return cur.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()[0] > 0


def _index_exists(cur: sqlite3.Cursor, name: str) -> bool:
    return cur.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name=?",
        (name,),
    ).fetchone()[0] > 0


def _add_parent_columns(cur: sqlite3.Cursor) -> list[str]:
    """Eksik enj_* kolonlarını ADD COLUMN ile ekle; mevcut olanları atla."""
    existing = _existing_columns(cur, PARENT_TABLE)
    added = []
    for col_name, col_type in ENJ_PARENT_COLUMNS:
        if col_name in existing:
            _log(f'  SKIP  parent kolon zaten var: {col_name}')
        else:
            cur.execute(
                f'ALTER TABLE {PARENT_TABLE} ADD COLUMN {col_name} {col_type}'
            )
            added.append(col_name)
            _log(f'  ADD   parent kolon: {col_name} {col_type}')
    return added


def _ensure_child_table(cur: sqlite3.Cursor) -> bool:
    """Child tabloyu oluştur; varsa atla."""
    if _table_exists(cur, CHILD_TABLE):
        _log(f'  SKIP  child tablo zaten var: {CHILD_TABLE}')
        return False
    cur.execute(CHILD_CREATE_SQL)
    _log(f'  CREATE child tablo: {CHILD_TABLE}')
    return True


def _ensure_index(cur: sqlite3.Cursor) -> bool:
    """Index'i oluştur; varsa atla."""
    if _index_exists(cur, INDEX_NAME):
        _log(f'  SKIP  index zaten var: {INDEX_NAME}')
        return False
    cur.execute(INDEX_CREATE_SQL)
    _log(f'  CREATE index: {INDEX_NAME}')
    return True


def _parse_istasyon_no(raw) -> list[int]:
    """enj_istasyon_no → sorted list[int]. Hatalı token güvenli atlanır."""
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
                _log(f'  SKIP_TOKEN negatif/sıfır: {token!r}')
        except ValueError:
            _log(f'  SKIP_TOKEN geçersiz: {token!r}')
    return sorted(set(result))


def _backfill(cur: sqlite3.Cursor) -> dict:
    """
    uretim_model_plan.enj_istasyon_no → child tablo backfill.

    enj_makine_id kolonu bu noktada var olmalı (ADD COLUMN yapıldı).
    INSERT OR IGNORE ile duplikat önlenir.
    """
    # enj_makine_id artık tabloda var — güvenle sorgula
    plans = cur.execute(
        f'SELECT id, enj_makine_id, enj_slot, enj_istasyon_no '
        f'FROM {PARENT_TABLE} '
        f'WHERE enj_makine_id IS NOT NULL AND aktif=1 '
        f'ORDER BY id'
    ).fetchall()

    backfilled = skipped_null = skipped_invalid = 0
    for plan_id, makine_id, slot, raw in plans:
        if slot not in ('A', 'B'):
            _log(f'  SKIP  plan {plan_id} geçersiz slot={slot!r}')
            skipped_invalid += 1
            continue
        istasyonlar = _parse_istasyon_no(raw)
        if not istasyonlar:
            skipped_null += 1
            continue
        for ist_no in istasyonlar:
            cur.execute(
                f'INSERT OR IGNORE INTO {CHILD_TABLE} '
                f'(plan_id, enj_makine_id, enj_slot, istasyon_no) '
                f'VALUES (?, ?, ?, ?)',
                (plan_id, makine_id, slot, ist_no),
            )
            if cur.rowcount > 0:
                backfilled += 1
                _log(f'  BACKFILL plan {plan_id} ist={ist_no}')
    return {'backfilled': backfilled, 'skipped_null': skipped_null,
            'skipped_invalid': skipped_invalid}


def _write_migration_record(cur: sqlite3.Cursor) -> None:
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


def run(db_path: str | None = None, *, allow_canonical: bool = False,
        _inject_failure: bool = False) -> dict:
    """
    Migration 190'ı uygula.

    Args:
        db_path:          Hedef SQLite DB mutlak yolu (zorunlu).
        allow_canonical:  True olmadan canonical mock_data.db hedefine yazılamaz.
        _inject_failure:  YALNIZ TEST: child tablo oluşturulduktan sonra exception
                          fırlatır; rollback atomikliğini doğrulamak için.
    """
    from migrations._migration_db_guard import resolve_db_path

    path = resolve_db_path(db_path, allow_canonical=allow_canonical)
    _log('=' * 70)
    _log(f'[{MIGRATION_VERSION}] {CHILD_TABLE}')
    _log(f'[{MIGRATION_VERSION}] DB: {path}')
    _log('=' * 70)

    con = sqlite3.connect(path, timeout=15, isolation_level=None)
    # isolation_level=None → autocommit kapalı; BEGIN/COMMIT/ROLLBACK elle yönetilir
    cur = con.cursor()
    result: dict = {
        'ok': False, 'db_path': path, 'version': MIGRATION_VERSION,
        'added_parent_cols': [], 'backfilled': 0,
        'skipped_null': 0, 'skipped_invalid': 0,
    }
    try:
        # idempotent guard
        already = cur.execute(
            'SELECT version FROM schema_migrations WHERE version=?',
            (str(MIGRATION_VERSION),),
        ).fetchone()
        if already:
            _log(f'[{MIGRATION_VERSION}] SKIP — zaten uygulanmış')
            result.update({'ok': True, 'skipped': True})
            return result

        cur.execute('BEGIN IMMEDIATE')

        # parent tablo varlığını doğrula
        if not _table_exists(cur, PARENT_TABLE):
            raise RuntimeError(f'Parent tablo bulunamadı: {PARENT_TABLE}')

        # parent enj_* kolonları
        added = _add_parent_columns(cur)
        result['added_parent_cols'] = added

        # child tablo
        _ensure_child_table(cur)

        # index
        _ensure_index(cur)

        # TEST HOOK: atomiklik testi için kontrollü hata
        if _inject_failure:
            raise RuntimeError('_inject_failure: atomiklik testi')

        # backfill
        bf = _backfill(cur)
        result.update(bf)

        # migration kaydı
        _write_migration_record(cur)

        cur.execute('COMMIT')
        result['ok'] = True
        _log(f'[{MIGRATION_VERSION}] COMMIT OK  '
             f'added={len(added)}  backfilled={result["backfilled"]}')
        return result

    except Exception as exc:
        try:
            cur.execute('ROLLBACK')
        except Exception:
            pass
        _log(f'[{MIGRATION_VERSION}] ROLLBACK — {exc}')
        raise
    finally:
        con.close()


if __name__ == '__main__':
    import argparse
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(
        description=f'Migration {MIGRATION_VERSION} — {CHILD_TABLE}'
    )
    parser.add_argument('--db-path', required=True,
                        help='Hedef SQLite DB mutlak yolu')
    parser.add_argument('--allow-canonical', action='store_true',
                        help='Canonical mock_data.db hedefine yazmaya izin ver')
    args = parser.parse_args()
    result = run(args.db_path, allow_canonical=args.allow_canonical)
    print(result)
