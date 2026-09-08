# -*- coding: utf-8 -*-
"""
Migration 190 — uyumluluk + atomiklik + regression testleri (temp DB only).

AŞAMALAR:
  A. Gerçek eski server şeması (enj_* yok, child yok)
  B. Yarım kalmış durum (enj_* yok, child var ve boş)
  C. Modern şema (enj_* var, child var)
  D. Tamamlanmış durum (idempotent no-op)
  + Atomiklik testi
  + Backfill varyantları
  + Repo katmanı regression
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_APP_DIR = _REPO_ROOT / 'app'
_MIG_PATH = _APP_DIR / 'migrations' / '190_uretim_model_plan_enj_istasyon.py'
for _p in [str(_APP_DIR), str(_APP_DIR / 'migrations')]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

CANONICAL_SOURCE = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))
PARENT = 'uretim_model_plan'
CHILD = 'uretim_model_plan_enj_istasyon'
IDX = 'idx_ump_enj_ist_mak_slot'

# Referans enj_* kolonlar (kanıtlanmış)
REQUIRED_ENJ_COLS = [
    ('enj_makine_id',          'INTEGER'),
    ('enj_istasyon_no',        'INTEGER'),
    ('enj_slot',               'TEXT'),
    ('enj_kalip_id',           'INTEGER'),
    ('enj_kalip_kod',          'TEXT'),
    ('enj_aktif_goz',          'INTEGER'),
    ('enj_kalip_basi_cift',    'INTEGER'),
    ('enj_tur_cift',           'INTEGER'),
    ('enj_gunluk_tur_plan',    'INTEGER'),
    ('enj_gunluk_kapasite',    'INTEGER'),
    ('enj_plan_baslangic',     'TEXT'),
    ('enj_plan_bitis',         'TEXT'),
    ('enj_tahmini_gun',        'REAL'),
    ('enj_planlanacak_cift',   'REAL'),
    ('enj_calisma_modu',       'TEXT'),
    ('enj_hafta_sonu_calisma', 'TEXT'),
    ('enj_hafta_sonu_vardiya', 'TEXT'),
    ('enj_kapasite_snapshot',  'TEXT'),
]
REF_CHILD_LINES = [
    f'CREATE TABLE {CHILD} (',
    'id              INTEGER PRIMARY KEY AUTOINCREMENT,',
    'plan_id         INTEGER NOT NULL,',
    'enj_makine_id   INTEGER NOT NULL,',
    "enj_slot        TEXT NOT NULL CHECK (enj_slot IN ('A', 'B')),",
    'istasyon_no     INTEGER NOT NULL,',
    "created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),",
    f'FOREIGN KEY (plan_id) REFERENCES {PARENT}(id),',
    'UNIQUE (plan_id, istasyon_no, enj_slot)',
    ')',
]

# Repo repo katmanı testleri için
MAKINE_A = 1
ENJ_BAS = '2027-08-01 07:00:00'
ENJ_BIT = '2027-08-03 17:00:00'
ENJ_BAS2 = '2027-08-02 07:00:00'
ENJ_BIT2 = '2027-08-04 17:00:00'
PLAN_BAS = '2027-08-06'
PLAN_BIT = '2027-08-20'
USER_ID = 1

# Görevde kanıtlanan eski server parent DDL (enj_* yok)
OLD_PARENT_DDL = f"""
CREATE TABLE {PARENT} (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sip_no          INTEGER NOT NULL,
    sip_harinx      INTEGER NOT NULL,
    mamul_skod      TEXT NOT NULL,
    rkod            INTEGER NOT NULL DEFAULT 0,
    model_adi       TEXT,
    renk_adi        TEXT,
    miktar          REAL,
    termin          TEXT,
    plan_donemi     TEXT NOT NULL,
    plan_baslangic  TEXT,
    plan_bitis      TEXT,
    oncelik         INTEGER NOT NULL DEFAULT 3,
    plan_gerekce    TEXT,
    plan_notu       TEXT,
    aktif           INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    created_by      INTEGER,
    updated_at      TEXT,
    updated_by      INTEGER
)
"""

SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version          TEXT PRIMARY KEY,
    uygulama_zamani  TEXT DEFAULT (datetime('now','localtime')),
    aciklama         TEXT
)
"""


# ----------------------------------------------------------------- helpers

def _load_m190():
    spec = importlib.util.spec_from_file_location('mig_190', str(_MIG_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _col_map(db_path: str, table: str) -> dict[str, dict]:
    """Tablo kolonlarını {name: {type, notnull, dflt}} olarak döndür."""
    with sqlite3.connect(db_path) as c:
        return {
            r[1]: {'type': r[2], 'notnull': r[3], 'dflt': r[4]}
            for r in c.execute(f'PRAGMA table_info({table})').fetchall()
        }


def _table_exists(db_path: str, name: str) -> bool:
    with sqlite3.connect(db_path) as c:
        return c.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()[0] > 0


def _index_exists(db_path: str, name: str) -> bool:
    with sqlite3.connect(db_path) as c:
        return c.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name=?",
            (name,),
        ).fetchone()[0] > 0


def _child_stations(db_path: str, plan_id: int) -> list[int]:
    with sqlite3.connect(db_path) as c:
        return [r[0] for r in c.execute(
            f'SELECT istasyon_no FROM {CHILD} WHERE plan_id=? ORDER BY istasyon_no',
            (plan_id,),
        ).fetchall()]


def _make_old_server_db() -> tuple[str, str]:
    """Eski server şemasını birebir oluşturan temp DB (enj_* yok, child yok)."""
    tmpdir = tempfile.mkdtemp(prefix='mig190_old_')
    db_path = str(Path(tmpdir) / 'old_server.db')
    with sqlite3.connect(db_path) as c:
        c.execute(OLD_PARENT_DDL.strip())
        c.execute(SCHEMA_MIGRATIONS_DDL)
        c.commit()
    return tmpdir, db_path


def _make_modern_db() -> tuple[str, str]:
    """Canonical DB'den backup — modern şema (enj_* var, child var)."""
    if not CANONICAL_SOURCE.is_file():
        pytest.skip(f'canonical DB yok: {CANONICAL_SOURCE}')
    tmpdir = tempfile.mkdtemp(prefix='mig190_mod_')
    db_path = str(Path(tmpdir) / 'modern.db')
    src = sqlite3.connect(f'file:{CANONICAL_SOURCE.as_posix()}?mode=ro', uri=True)
    dst = sqlite3.connect(db_path)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        src.close()
        dst.close()
    return tmpdir, db_path


def _insert_plan(db_path: str, sip_no: int, *, enj_makine=1, slot='A',
                 ist_no=None) -> int:
    """Modern şemaya sahip DB'ye plan ekle (enj_* kolonlar mevcut)."""
    with sqlite3.connect(db_path) as c:
        cur = c.execute(
            f'INSERT INTO {PARENT} '
            '(sip_no,sip_harinx,mamul_skod,rkod,plan_donemi,plan_baslangic,plan_bitis,'
            'miktar,enj_makine_id,enj_slot,enj_kalip_id,aktif,created_by,'
            'enj_plan_baslangic,enj_plan_bitis,enj_istasyon_no) '
            "VALUES (?,1,?,1,'bu_hafta','2027-08-10','2027-08-20',"
            "100,?,'A',1,1,1,'2027-08-01 07:00:00','2027-08-03 17:00:00',?)",
            (sip_no, f'BF-{sip_no}', enj_makine, ist_no),
        )
        return cur.lastrowid


def _enj_payload(sip_no, istasyonlar, *, makine_id=MAKINE_A, slot='A',
                 bas=ENJ_BAS, bit=ENJ_BIT):
    return {
        'sip_no': sip_no, 'sip_harinx': 1, 'rkod': 1,
        'mamul_skod': f'MIG190-{sip_no}',
        'plan_donemi': 'bu_hafta',
        'plan_baslangic': PLAN_BAS, 'plan_bitis': PLAN_BIT,
        'miktar': 1000,
        'has_enjeksiyon': True,
        'enj_makine_id': makine_id, 'enj_slot': slot, 'enj_kalip_id': 1,
        'enj_istasyonlar': list(istasyonlar),
        'enj_kalip_adedi': len(istasyonlar),
        'enj_aktif_goz': len(istasyonlar),
        'enj_plan_baslangic': bas, 'enj_plan_bitis': bit,
        'enj_calisma_modu': 'GUNDUZ_GECE', 'enj_hafta_sonu_calisma': 'HAYIR',
    }


# ----------------------------------------------------------------- fixtures

@pytest.fixture(scope='function')
def fresh_db(monkeypatch):
    """Canonical backup + migration uygulanmış; repo katmanı testleri için."""
    if not CANONICAL_SOURCE.is_file():
        pytest.skip(f'canonical DB yok: {CANONICAL_SOURCE}')
    tmpdir = Path(tempfile.mkdtemp(prefix='mig190_repo_'))
    db_path = str(tmpdir / 'repo.db')
    src = sqlite3.connect(f'file:{CANONICAL_SOURCE.as_posix()}?mode=ro', uri=True)
    dst = sqlite3.connect(db_path)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        src.close()
        dst.close()

    m190 = _load_m190()
    # Drop migration record to re-apply
    with sqlite3.connect(db_path) as c:
        c.execute("DELETE FROM schema_migrations WHERE version='190'")
        c.commit()
    m190.run(db_path, allow_canonical=False)

    import config
    monkeypatch.setattr(config.Config, 'MOCK_DB_PATH', db_path, raising=False)
    monkeypatch.setenv('CPS_MOCK_DB_PATH', db_path)
    monkeypatch.setenv('CPS_TEST_DB_GUARD', '1')

    from tools.atp_test_db_guard import is_canonical_path
    assert not is_canonical_path(db_path)

    try:
        yield db_path
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture(scope='function')
def repo(fresh_db):
    from modules.planlama import uretim_plan_repo as _r
    return _r


# ================================================ DURUM A: Gerçek eski server

class TestDurumA:
    """A. Gerçek eski server şeması — enj_* yok, child yok."""

    def test_old_schema_apply_pass(self):
        """OLD_SERVER_SCHEMA_APPLY=PASS — eski şemada migration tamamlanıyor."""
        tmpdir, db_path = _make_old_server_db()
        try:
            m190 = _load_m190()
            result = m190.run(db_path, allow_canonical=False)
            assert result['ok'] is True, f'Migration başarısız: {result}'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_all_required_parent_enj_columns_created(self):
        """ALL_REQUIRED_PARENT_ENJ_COLUMNS_CREATED=PASS"""
        tmpdir, db_path = _make_old_server_db()
        try:
            _load_m190().run(db_path, allow_canonical=False)
            cols = _col_map(db_path, PARENT)
            missing = [name for name, _ in REQUIRED_ENJ_COLS if name not in cols]
            assert not missing, f'Eksik kolonlar: {missing}'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_parent_column_types_match_reference(self):
        """PARENT_COLUMN_TYPES_MATCH_REFERENCE=PASS"""
        tmpdir, db_path = _make_old_server_db()
        try:
            _load_m190().run(db_path, allow_canonical=False)
            cols = _col_map(db_path, PARENT)
            mismatches = []
            for name, expected_type in REQUIRED_ENJ_COLS:
                actual = cols.get(name, {}).get('type', 'MISSING')
                if actual != expected_type:
                    mismatches.append(f'{name}: expected={expected_type} actual={actual}')
            assert not mismatches, f'Tip uyuşmazlıkları: {mismatches}'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_parent_defaults_match_reference(self):
        """PARENT_DEFAULTS_MATCH_REFERENCE=PASS — tüm enj_* NULL default."""
        tmpdir, db_path = _make_old_server_db()
        try:
            _load_m190().run(db_path, allow_canonical=False)
            cols = _col_map(db_path, PARENT)
            bad = []
            for name, _ in REQUIRED_ENJ_COLS:
                dflt = cols.get(name, {}).get('dflt')
                if dflt is not None:
                    bad.append(f'{name}: dflt={dflt!r}')
            assert not bad, f'Beklenen NULL default değil: {bad}'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_child_table_created(self):
        """CHILD_TABLE_CREATED=PASS"""
        tmpdir, db_path = _make_old_server_db()
        try:
            _load_m190().run(db_path, allow_canonical=False)
            assert _table_exists(db_path, CHILD), f'{CHILD} oluşturulmadı'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_child_schema_match_reference(self):
        """CHILD_SCHEMA_MATCH_REFERENCE=PASS"""
        tmpdir, db_path = _make_old_server_db()
        try:
            _load_m190().run(db_path, allow_canonical=False)
            with sqlite3.connect(db_path) as c:
                sql = c.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (CHILD,),
                ).fetchone()[0]
            actual_lines = [ln.strip() for ln in sql.splitlines() if ln.strip()]
            assert actual_lines == REF_CHILD_LINES, (
                f'Schema mismatch:\nACTUAL={actual_lines}\nEXP={REF_CHILD_LINES}'
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_child_index_created(self):
        """CHILD_INDEX_CREATED=PASS"""
        tmpdir, db_path = _make_old_server_db()
        try:
            _load_m190().run(db_path, allow_canonical=False)
            assert _index_exists(db_path, IDX), f'{IDX} oluşturulmadı'
            with sqlite3.connect(db_path) as c:
                idx_cols = [r[2] for r in c.execute(f'PRAGMA index_info({IDX})').fetchall()]
            assert idx_cols == ['enj_makine_id', 'enj_slot', 'istasyon_no']
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_migration_190_recorded(self):
        """MIGRATION_190_RECORDED=PASS"""
        tmpdir, db_path = _make_old_server_db()
        try:
            _load_m190().run(db_path, allow_canonical=False)
            with sqlite3.connect(db_path) as c:
                row = c.execute(
                    "SELECT version FROM schema_migrations WHERE version='190'"
                ).fetchone()
            assert row is not None, 'schema_migrations version=190 kaydı yok'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_parent_plan_count_unchanged(self):
        """PARENT_PLAN_COUNT_UNCHANGED=PASS — sıfır plan var, sıfır kalır."""
        tmpdir, db_path = _make_old_server_db()
        try:
            before = 0  # eski şemada plan yok
            _load_m190().run(db_path, allow_canonical=False)
            with sqlite3.connect(db_path) as c:
                after = c.execute(f'SELECT COUNT(*) FROM {PARENT}').fetchone()[0]
            assert after == before, f'plan sayısı değişti: {before}→{after}'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_db_integrity(self):
        """DB_INTEGRITY=ok"""
        tmpdir, db_path = _make_old_server_db()
        try:
            _load_m190().run(db_path, allow_canonical=False)
            with sqlite3.connect(db_path) as c:
                r = c.execute('PRAGMA integrity_check').fetchone()[0]
            assert r == 'ok'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ================================================ DURUM B: Yarım kalmış

class TestDurumB:
    """B. Yarım kalmış durum — enj_* yok, child/index var ve boş."""

    def _make_partial_db(self) -> tuple[str, str]:
        tmpdir, db_path = _make_old_server_db()
        # Child tabloyu ve index'i elle oluştur (önceki başarısız migration simülasyonu)
        with sqlite3.connect(db_path) as c:
            c.execute(f"""CREATE TABLE {CHILD} (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id         INTEGER NOT NULL,
                enj_makine_id   INTEGER NOT NULL,
                enj_slot        TEXT NOT NULL CHECK (enj_slot IN ('A', 'B')),
                istasyon_no     INTEGER NOT NULL,
                created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (plan_id) REFERENCES {PARENT}(id),
                UNIQUE (plan_id, istasyon_no, enj_slot)
            )""")
            c.execute(
                f'CREATE INDEX {IDX} ON {CHILD}(enj_makine_id, enj_slot, istasyon_no)'
            )
            c.commit()
        return tmpdir, db_path

    def test_partial_child_only_state_recovered(self):
        """PARTIAL_CHILD_ONLY_STATE_RECOVERED=PASS — migration tamamlanıyor."""
        tmpdir, db_path = self._make_partial_db()
        try:
            m190 = _load_m190()
            result = m190.run(db_path, allow_canonical=False)
            assert result['ok'] is True
            # Kolonlar eklendi
            cols = _col_map(db_path, PARENT)
            assert 'enj_makine_id' in cols, 'enj_makine_id eklenmedi'
            # Child korundu
            assert _table_exists(db_path, CHILD), 'child tablo silindi'
            # Kayıt yazıldı
            with sqlite3.connect(db_path) as c:
                rec = c.execute(
                    "SELECT version FROM schema_migrations WHERE version='190'"
                ).fetchone()
            assert rec is not None
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ================================================ DURUM C: Modern şema

class TestDurumC:
    """C. Modern laptop şeması — enj_* var, child var."""

    def test_modern_schema_no_data_loss(self):
        """MODERN_SCHEMA_NO_DATA_LOSS=PASS"""
        tmpdir, db_path = _make_modern_db()
        try:
            # Önce plan ve child satır ekle
            plan_id = _insert_plan(db_path, 996001, ist_no=7)
            with sqlite3.connect(db_path) as c:
                c.execute(
                    f'INSERT OR IGNORE INTO {CHILD} '
                    '(plan_id, enj_makine_id, enj_slot, istasyon_no) VALUES (?,1,?,7)',
                    (plan_id, 'A'),
                )
                c.execute("DELETE FROM schema_migrations WHERE version='190'")
                c.commit()

            before_plans = sqlite3.connect(db_path).execute(
                f'SELECT COUNT(*) FROM {PARENT}'
            ).fetchone()[0]

            _load_m190().run(db_path, allow_canonical=False)

            with sqlite3.connect(db_path) as c:
                after_plans = c.execute(f'SELECT COUNT(*) FROM {PARENT}').fetchone()[0]
                child_row = c.execute(
                    f'SELECT istasyon_no FROM {CHILD} WHERE plan_id=?', (plan_id,)
                ).fetchone()
            assert after_plans == before_plans, 'plan satırı kayboldu'
            assert child_row is not None, 'child satır kayboldu'
            assert child_row[0] == 7
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ================================================ DURUM D: İdempotent

class TestDurumD:
    """D. Tamamlanmış durum — ikinci çalışma no-op."""

    def test_second_run_idempotent(self):
        """SECOND_RUN_IDEMPOTENT=PASS"""
        tmpdir, db_path = _make_old_server_db()
        try:
            m190 = _load_m190()
            r1 = m190.run(db_path, allow_canonical=False)
            assert r1['ok']

            with sqlite3.connect(db_path) as c:
                before_child = c.execute(f'SELECT COUNT(*) FROM {CHILD}').fetchone()[0]

            r2 = m190.run(db_path, allow_canonical=False)
            assert r2['ok'] is True
            assert r2.get('skipped') is True, 'ikinci çalışmada SKIP bekleniyor'

            with sqlite3.connect(db_path) as c:
                after_child = c.execute(f'SELECT COUNT(*) FROM {CHILD}').fetchone()[0]
            assert after_child == before_child
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ================================================ ATOMİKLİK TESTİ

class TestAtomiklik:
    """Migration child tablo sonrası hata alırsa tam rollback olmalı."""

    def test_atomic_failure_raised(self):
        """ATOMIC_FAILURE_RAISED=PASS"""
        tmpdir, db_path = _make_old_server_db()
        try:
            m190 = _load_m190()
            with pytest.raises(RuntimeError, match='_inject_failure'):
                m190.run(db_path, allow_canonical=False, _inject_failure=True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_atomic_parent_columns_rolled_back(self):
        """ATOMIC_PARENT_COLUMNS_ROLLED_BACK=PASS — ADD COLUMN geri alındı."""
        tmpdir, db_path = _make_old_server_db()
        try:
            m190 = _load_m190()
            with pytest.raises(RuntimeError):
                m190.run(db_path, allow_canonical=False, _inject_failure=True)
            cols = _col_map(db_path, PARENT)
            enj_remaining = [c for c in cols if c.startswith('enj')]
            assert not enj_remaining, (
                f'Rollback sonrası enj_* kolonlar kaldı: {enj_remaining}'
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_atomic_child_table_rolled_back(self):
        """ATOMIC_CHILD_TABLE_ROLLED_BACK=PASS — child tablo geri alındı."""
        tmpdir, db_path = _make_old_server_db()
        try:
            m190 = _load_m190()
            with pytest.raises(RuntimeError):
                m190.run(db_path, allow_canonical=False, _inject_failure=True)
            assert not _table_exists(db_path, CHILD), f'{CHILD} rollback sonrası kaldı'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_atomic_index_rolled_back(self):
        """ATOMIC_INDEX_ROLLED_BACK=PASS — index geri alındı."""
        tmpdir, db_path = _make_old_server_db()
        try:
            m190 = _load_m190()
            with pytest.raises(RuntimeError):
                m190.run(db_path, allow_canonical=False, _inject_failure=True)
            assert not _index_exists(db_path, IDX), f'{IDX} rollback sonrası kaldı'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_atomic_migration_record_rolled_back(self):
        """ATOMIC_MIGRATION_RECORD_ROLLED_BACK=PASS"""
        tmpdir, db_path = _make_old_server_db()
        try:
            m190 = _load_m190()
            with pytest.raises(RuntimeError):
                m190.run(db_path, allow_canonical=False, _inject_failure=True)
            with sqlite3.connect(db_path) as c:
                rec = c.execute(
                    "SELECT version FROM schema_migrations WHERE version='190'"
                ).fetchone()
            assert rec is None, 'migration kaydı rollback sonrası kaldı'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_atomic_db_integrity(self):
        """ATOMIC_DB_INTEGRITY=ok — rollback sonrası DB bütünlüğü sağlam."""
        tmpdir, db_path = _make_old_server_db()
        try:
            m190 = _load_m190()
            with pytest.raises(RuntimeError):
                m190.run(db_path, allow_canonical=False, _inject_failure=True)
            with sqlite3.connect(db_path) as c:
                r = c.execute('PRAGMA integrity_check').fetchone()[0]
            assert r == 'ok'
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ================================================ BACKFILL

class TestBackfill:
    """Legacy enj_istasyon_no → child tablo backfill."""

    def test_legacy_single_backfill(self):
        """LEGACY_SINGLE_BACKFILL=PASS — enj_istasyon_no=7 → [7]."""
        tmpdir, db_path = _make_old_server_db()
        try:
            m190 = _load_m190()
            # Önce migration'ı uygula (kolonlar eklensin)
            r = m190.run(db_path, allow_canonical=False)
            assert r['ok']
            # Sonra plan ekle + child'ı sil + migration kaydını sil → tekrar çalıştır
            with sqlite3.connect(db_path) as c:
                cur = c.execute(
                    f'INSERT INTO {PARENT} '
                    "(sip_no,sip_harinx,mamul_skod,rkod,plan_donemi,plan_baslangic,"
                    "plan_bitis,miktar,enj_makine_id,enj_slot,enj_kalip_id,aktif,"
                    "created_by,enj_plan_baslangic,enj_plan_bitis,enj_istasyon_no) "
                    "VALUES (997101,1,'BF-S',1,'bu_hafta','2027-08-10','2027-08-20',"
                    "100,1,'A',1,1,1,'2027-08-01 07:00:00','2027-08-03 17:00:00',7)"
                )
                plan_id = cur.lastrowid
                c.execute(f'DELETE FROM {CHILD} WHERE plan_id=?', (plan_id,))
                c.execute("DELETE FROM schema_migrations WHERE version='190'")
                c.commit()
            r2 = m190.run(db_path, allow_canonical=False)
            assert r2['ok']
            assert _child_stations(db_path, plan_id) == [7]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_legacy_multi_backfill(self):
        """LEGACY_MULTI_BACKFILL=PASS — enj_istasyon_no='7,8' → [7,8]."""
        tmpdir, db_path = _make_old_server_db()
        try:
            m190 = _load_m190()
            m190.run(db_path, allow_canonical=False)
            with sqlite3.connect(db_path) as c:
                cur = c.execute(
                    f'INSERT INTO {PARENT} '
                    "(sip_no,sip_harinx,mamul_skod,rkod,plan_donemi,plan_baslangic,"
                    "plan_bitis,miktar,enj_makine_id,enj_slot,enj_kalip_id,aktif,"
                    "created_by,enj_plan_baslangic,enj_plan_bitis,enj_istasyon_no) "
                    "VALUES (997102,1,'BF-M',1,'bu_hafta','2027-08-10','2027-08-20',"
                    "100,1,'A',1,1,1,'2027-08-01 07:00:00','2027-08-03 17:00:00','7,8')"
                )
                plan_id = cur.lastrowid
                c.execute(f'DELETE FROM {CHILD} WHERE plan_id=?', (plan_id,))
                c.execute("DELETE FROM schema_migrations WHERE version='190'")
                c.commit()
            r = m190.run(db_path, allow_canonical=False)
            assert r['ok']
            assert _child_stations(db_path, plan_id) == [7, 8]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_null_legacy_safe(self):
        """NULL_LEGACY_SAFE=PASS"""
        tmpdir, db_path = _make_old_server_db()
        try:
            m190 = _load_m190()
            m190.run(db_path, allow_canonical=False)
            with sqlite3.connect(db_path) as c:
                cur = c.execute(
                    f'INSERT INTO {PARENT} '
                    "(sip_no,sip_harinx,mamul_skod,rkod,plan_donemi,plan_baslangic,"
                    "plan_bitis,miktar,enj_makine_id,enj_slot,enj_kalip_id,aktif,"
                    "created_by,enj_plan_baslangic,enj_plan_bitis,enj_istasyon_no) "
                    "VALUES (997103,1,'BF-N',1,'bu_hafta','2027-08-10','2027-08-20',"
                    "100,1,'A',1,1,1,'2027-08-01 07:00:00','2027-08-03 17:00:00',NULL)"
                )
                plan_id = cur.lastrowid
                c.execute(f'DELETE FROM {CHILD} WHERE plan_id=?', (plan_id,))
                c.execute("DELETE FROM schema_migrations WHERE version='190'")
                c.commit()
            r = m190.run(db_path, allow_canonical=False)
            assert r['ok']
            assert r['skipped_null'] >= 1
            assert _child_stations(db_path, plan_id) == []
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_invalid_legacy_safe(self):
        """INVALID_LEGACY_SAFE=PASS"""
        tmpdir, db_path = _make_old_server_db()
        try:
            m190 = _load_m190()
            m190.run(db_path, allow_canonical=False)
            with sqlite3.connect(db_path) as c:
                cur = c.execute(
                    f'INSERT INTO {PARENT} '
                    "(sip_no,sip_harinx,mamul_skod,rkod,plan_donemi,plan_baslangic,"
                    "plan_bitis,miktar,enj_makine_id,enj_slot,enj_kalip_id,aktif,"
                    "created_by,enj_plan_baslangic,enj_plan_bitis,enj_istasyon_no) "
                    "VALUES (997104,1,'BF-I',1,'bu_hafta','2027-08-10','2027-08-20',"
                    "100,1,'A',1,1,1,'2027-08-01 07:00:00','2027-08-03 17:00:00','abc')"
                )
                plan_id = cur.lastrowid
                c.execute(f'DELETE FROM {CHILD} WHERE plan_id=?', (plan_id,))
                c.execute("DELETE FROM schema_migrations WHERE version='190'")
                c.commit()
            r = m190.run(db_path, allow_canonical=False)
            assert r['ok']
            assert _child_stations(db_path, plan_id) == []
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ================================================ KULLANICI SAYI

def test_user_count_unchanged():
    """USER_COUNT_UNCHANGED=PASS"""
    if not CANONICAL_SOURCE.is_file():
        pytest.skip('canonical DB yok')
    with sqlite3.connect(f'file:{CANONICAL_SOURCE.as_posix()}?mode=ro', uri=True) as s:
        before = s.execute('SELECT COUNT(*) FROM sistem_kullanici').fetchone()[0]
    tmpdir, db_path = _make_modern_db()
    try:
        with sqlite3.connect(db_path) as c:
            c.execute("DELETE FROM schema_migrations WHERE version='190'")
            c.commit()
        _load_m190().run(db_path, allow_canonical=False)
        with sqlite3.connect(db_path) as d:
            after = d.execute('SELECT COUNT(*) FROM sistem_kullanici').fetchone()[0]
        assert after == before
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ================================================ REPO KATMANI REGRESSION

def test_create_single_station_regression(repo, fresh_db):
    """CREATE_SINGLE_STATION_REGRESSION"""
    plan = repo.plan_ekle(_enj_payload(994801, [3]), USER_ID)
    assert plan['enj_istasyonlar'] == [3]
    assert _child_stations(fresh_db, plan['id']) == [3]


def test_create_multi_station_regression(repo, fresh_db):
    """CREATE_MULTI_STATION_REGRESSION"""
    plan = repo.plan_ekle(_enj_payload(994802, [7, 8]), USER_ID)
    assert plan['enj_istasyonlar'] == [7, 8]
    assert _child_stations(fresh_db, plan['id']) == [7, 8]


def test_update_self_no_false_conflict(repo, fresh_db):
    """PLAN_UPDATE_REGRESSION — self-update çakışma üretmez."""
    plan = repo.plan_ekle(_enj_payload(994803, [7, 8]), USER_ID)
    updated = repo.plan_guncelle(
        plan['id'],
        _enj_payload(994803, [7, 8]) | {'plan_notu': 'self-ok'},
        USER_ID,
    )
    assert updated['enj_istasyonlar'] == [7, 8]


def test_multi_station_conflict_blocked(repo, fresh_db):
    """MULTI_STATION_REGRESSION — gerçek çakışma engellenir."""
    repo.plan_ekle(_enj_payload(994804, [7, 8]), USER_ID)
    b = repo.plan_ekle(_enj_payload(994805, [3, 4], bas=ENJ_BAS2, bit=ENJ_BIT2), USER_ID)
    with pytest.raises(ValueError):
        repo.plan_guncelle(
            b['id'],
            _enj_payload(994805, [7, 8], bas=ENJ_BAS2, bit=ENJ_BIT2),
            USER_ID,
        )
    assert _child_stations(fresh_db, b['id']) == [3, 4]


# ================================================ ATP LOCK

def test_atp_stabilization_lock():
    """ATP_STABILIZATION_LOCK=PASS, ATP_DIFF=0"""
    import subprocess
    r = subprocess.run(
        [sys.executable, 'tools/validate_atp_stabilization_lock.py'],
        cwd=str(_REPO_ROOT),
        capture_output=True, text=True,
    )
    output = r.stdout + r.stderr
    assert 'ATP_STABILIZATION_LOCK=PASS' in output, f'ATP LOCK failed:\n{output}'
    assert 'ATP_DIFF=0' in output, f'ATP DIFF!=0:\n{output}'
