# -*- coding: utf-8 -*-
"""
Migration 190 — uretim_model_plan_enj_istasyon regression (temp DB only).

Canonical DB read-only açılır, SQLite Backup API ile temp DB oluşturulur.
Tüm yazma işlemleri yalnız temp DB'ye yapılır.
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
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))
if str(_APP_DIR / 'migrations') not in sys.path:
    sys.path.insert(0, str(_APP_DIR / 'migrations'))

CANONICAL_SOURCE = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))
TBL = 'uretim_model_plan_enj_istasyon'
IDX = 'idx_ump_enj_ist_mak_slot'

# Referans CREATE SQL (laptop test DB'sinden alınan kanonik şema)
REF_LINES = [
    f'CREATE TABLE {TBL} (',
    'id              INTEGER PRIMARY KEY AUTOINCREMENT,',
    'plan_id         INTEGER NOT NULL,',
    'enj_makine_id   INTEGER NOT NULL,',
    "enj_slot        TEXT NOT NULL CHECK (enj_slot IN ('A', 'B')),",
    'istasyon_no     INTEGER NOT NULL,',
    "created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),",
    'FOREIGN KEY (plan_id) REFERENCES uretim_model_plan(id),',
    'UNIQUE (plan_id, istasyon_no, enj_slot)',
    ')',
]

# Repo-katmanı testleri için sabitler
MAKINE_A = 1
ENJ_BAS = '2027-08-01 07:00:00'
ENJ_BIT = '2027-08-03 17:00:00'
ENJ_BAS2 = '2027-08-02 07:00:00'
ENJ_BIT2 = '2027-08-04 17:00:00'
PLAN_BAS = '2027-08-06'
PLAN_BIT = '2027-08-20'
USER_ID = 1


# ----------------------------------------------------------------- helpers

def _load_m190():
    """Migration modülünü dosya yoluyla yükle (sayısal prefix için importlib.util)."""
    spec = importlib.util.spec_from_file_location('mig_190', str(_MIG_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_temp_db() -> tuple[str, str]:
    """Canonical DB'den backup alarak temp DB oluştur. (tmpdir, db_path) döner."""
    tmpdir = tempfile.mkdtemp(prefix='mig190_')
    db_path = str(Path(tmpdir) / 'test_mig190.db')
    src = sqlite3.connect(f'file:{CANONICAL_SOURCE.as_posix()}?mode=ro', uri=True)
    dst = sqlite3.connect(db_path)
    try:
        src.backup(dst)
        dst.commit()
        assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    finally:
        src.close()
        dst.close()
    return tmpdir, db_path


def _child_stations(db_path, plan_id) -> list[int]:
    with sqlite3.connect(db_path) as c:
        return [r[0] for r in c.execute(
            f'SELECT istasyon_no FROM {TBL} WHERE plan_id=? ORDER BY istasyon_no',
            (plan_id,),
        ).fetchall()]


def _raw_plan_insert(db_path, sip_no, makine=1, slot='A', istasyon_no_val=None):
    """Test için ham plan satırı ekle; migration backfill testi için.

    has_enjeksiyon DB'de kolonu yok — yalnız payload alanıdır. Burada eklemiyoruz.
    Migration backfill enj_makine_id IS NOT NULL koşulunu kullanır.
    """
    with sqlite3.connect(db_path) as c:
        cur = c.execute(
            'INSERT INTO uretim_model_plan '
            '(sip_no,sip_harinx,mamul_skod,rkod,plan_donemi,plan_baslangic,plan_bitis,'
            'miktar,enj_makine_id,enj_slot,enj_kalip_id,aktif,created_by,'
            'enj_plan_baslangic,enj_plan_bitis,enj_istasyon_no) '
            "VALUES (?,1,?,1,'bu_hafta','2027-08-10','2027-08-20',"
            "100,?,'A',1,1,1,'2027-08-01 07:00:00','2027-08-03 17:00:00',?)",
            (sip_no, f'BACKFILL-{sip_no}', makine, istasyon_no_val),
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

@pytest.fixture(scope='module')
def migrated_db():
    """Migration uygulanmış module-scope temp DB."""
    if not CANONICAL_SOURCE.is_file():
        pytest.skip(f'kaynak DB yok: {CANONICAL_SOURCE}')
    tmpdir = Path(tempfile.mkdtemp(prefix='mig190_main_'))
    db_path = str(tmpdir / 'main.db')
    src = sqlite3.connect(f'file:{CANONICAL_SOURCE.as_posix()}?mode=ro', uri=True)
    dst = sqlite3.connect(db_path)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        src.close()
        dst.close()

    # Tabloyu sil (yoksa da hata vermez) ve migration uygula
    with sqlite3.connect(db_path) as c:
        c.execute(f'DROP TABLE IF EXISTS {TBL}')
        c.execute("DELETE FROM schema_migrations WHERE version='190'")
        c.commit()

    m190 = _load_m190()
    result = m190.run(db_path, allow_canonical=False)
    assert result['ok'], f'Migration başarısız: {result}'

    yield db_path
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture(scope='function')
def fresh_db(monkeypatch):
    """Her repo testi için ayrı temp DB; migration uygulanmış."""
    if not CANONICAL_SOURCE.is_file():
        pytest.skip(f'kaynak DB yok: {CANONICAL_SOURCE}')
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


# ======================================================= migration testleri

def test_pre_child_table_state_on_server():
    """PRE_CHILD_TABLE_EXISTS — server DB'de tablo durumunu kaydet."""
    if not CANONICAL_SOURCE.is_file():
        pytest.skip('canonical DB yok')
    with sqlite3.connect(f'file:{CANONICAL_SOURCE.as_posix()}?mode=ro', uri=True) as c:
        row = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (TBL,)
        ).fetchone()
    print(f'\nPRE_CHILD_TABLE_EXISTS={row is not None}')
    # informational — always pass


def test_migration_apply_pass(migrated_db):
    """MIGRATION_APPLY — migration hata vermeden tamamlandı."""
    with sqlite3.connect(migrated_db) as c:
        row = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (TBL,)
        ).fetchone()
    assert row is not None


def test_post_child_table_exists(migrated_db):
    """POST_CHILD_TABLE_EXISTS — tablo migration sonrası kesinlikle var."""
    with sqlite3.connect(migrated_db) as c:
        row = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (TBL,)
        ).fetchone()
    assert row is not None, f'{TBL} bulunamadı'


def test_schema_match_reference(migrated_db):
    """SCHEMA_MATCH_REFERENCE — CREATE SQL referansla eşleşiyor."""
    with sqlite3.connect(migrated_db) as c:
        sql = c.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (TBL,)
        ).fetchone()[0]
    actual_lines = [ln.strip() for ln in sql.splitlines() if ln.strip()]
    assert actual_lines == REF_LINES, (
        f'Schema mismatch:\nACTUAL: {actual_lines}\nEXPECTED: {REF_LINES}'
    )


def test_foreign_key_match(migrated_db):
    """FOREIGN_KEY_MATCH — FK plan_id → uretim_model_plan(id)."""
    with sqlite3.connect(migrated_db) as c:
        fks = c.execute(f'PRAGMA foreign_key_list({TBL})').fetchall()
    assert fks, 'FK tanımı yok'
    assert fks[0][2] == 'uretim_model_plan'
    assert fks[0][3] == 'plan_id'
    assert fks[0][4] == 'id'


def test_index_match(migrated_db):
    """INDEX_MATCH — index mevcut ve kolonlar doğru."""
    with sqlite3.connect(migrated_db) as c:
        idx = c.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (IDX,)
        ).fetchone()
        assert idx is not None, f'{IDX} yok'
        cols = [r[2] for r in c.execute(f'PRAGMA index_info({IDX})').fetchall()]
    assert cols == ['enj_makine_id', 'enj_slot', 'istasyon_no']


def test_legacy_single_backfill():
    """LEGACY_SINGLE_BACKFILL — enj_istasyon_no=7 → child [7]."""
    if not CANONICAL_SOURCE.is_file():
        pytest.skip('canonical DB yok')
    tmpdir, db_path = _make_temp_db()
    try:
        with sqlite3.connect(db_path) as c:
            c.execute(f'DROP TABLE IF EXISTS {TBL}')
            c.execute("DELETE FROM schema_migrations WHERE version='190'")
            c.commit()
        plan_id = _raw_plan_insert(db_path, 997001, istasyon_no_val=7)
        m190 = _load_m190()
        result = m190.run(db_path, allow_canonical=False)
        assert result['ok']
        assert _child_stations(db_path, plan_id) == [7]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_legacy_multi_backfill():
    """LEGACY_MULTI_BACKFILL — enj_istasyon_no='7,8' → child [7,8]."""
    if not CANONICAL_SOURCE.is_file():
        pytest.skip('canonical DB yok')
    tmpdir, db_path = _make_temp_db()
    try:
        with sqlite3.connect(db_path) as c:
            c.execute(f'DROP TABLE IF EXISTS {TBL}')
            c.execute("DELETE FROM schema_migrations WHERE version='190'")
            c.commit()
        plan_id = _raw_plan_insert(db_path, 997002, istasyon_no_val='7,8')
        m190 = _load_m190()
        result = m190.run(db_path, allow_canonical=False)
        assert result['ok']
        assert _child_stations(db_path, plan_id) == [7, 8]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_null_legacy_safe():
    """NULL_LEGACY_SAFE — NULL enj_istasyon_no güvenli atlanıyor."""
    if not CANONICAL_SOURCE.is_file():
        pytest.skip('canonical DB yok')
    tmpdir, db_path = _make_temp_db()
    try:
        with sqlite3.connect(db_path) as c:
            c.execute(f'DROP TABLE IF EXISTS {TBL}')
            c.execute("DELETE FROM schema_migrations WHERE version='190'")
            c.commit()
        plan_id = _raw_plan_insert(db_path, 997003, istasyon_no_val=None)
        m190 = _load_m190()
        result = m190.run(db_path, allow_canonical=False)
        assert result['ok']
        assert result['skipped_null'] >= 1
        assert _child_stations(db_path, plan_id) == []
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_invalid_legacy_safe():
    """INVALID_LEGACY_SAFE — geçersiz 'abc' token güvenli atlanıyor."""
    if not CANONICAL_SOURCE.is_file():
        pytest.skip('canonical DB yok')
    tmpdir, db_path = _make_temp_db()
    try:
        with sqlite3.connect(db_path) as c:
            c.execute(f'DROP TABLE IF EXISTS {TBL}')
            c.execute("DELETE FROM schema_migrations WHERE version='190'")
            c.commit()
        plan_id = _raw_plan_insert(db_path, 997004, istasyon_no_val='abc')
        m190 = _load_m190()
        result = m190.run(db_path, allow_canonical=False)
        assert result['ok']
        assert _child_stations(db_path, plan_id) == []
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_duplicate_backfill_prevented():
    """DUPLICATE_BACKFILL_PREVENTED — aynı satır iki kez eklenmiyor."""
    if not CANONICAL_SOURCE.is_file():
        pytest.skip('canonical DB yok')
    tmpdir, db_path = _make_temp_db()
    try:
        with sqlite3.connect(db_path) as c:
            c.execute(f'DROP TABLE IF EXISTS {TBL}')
            c.execute("DELETE FROM schema_migrations WHERE version='190'")
            c.commit()

        # İlk migration
        plan_id = _raw_plan_insert(db_path, 997005, istasyon_no_val=5)
        m190 = _load_m190()
        r1 = m190.run(db_path, allow_canonical=False)
        assert r1['ok']
        assert _child_stations(db_path, plan_id) == [5]

        # schema_migrations kaydını sil, tabloyu koru → backfill tekrar çalışır
        with sqlite3.connect(db_path) as c:
            c.execute("DELETE FROM schema_migrations WHERE version='190'")
            c.commit()

        r2 = m190.run(db_path, allow_canonical=False)
        assert r2['ok']
        # Yeni ek 0 (zaten vardı)
        assert r2['backfilled'] == 0
        assert _child_stations(db_path, plan_id) == [5]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_orphan_prevented(migrated_db):
    """ORPHAN_PREVENTED — parent olmayan child satır FK ile engelleniyor."""
    with sqlite3.connect(migrated_db) as c:
        c.execute('PRAGMA foreign_keys = ON')
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(
                f'INSERT INTO {TBL} (plan_id, enj_makine_id, enj_slot, istasyon_no) '
                'VALUES (9999999, 1, ?, 5)',
                ('A',),
            )
            c.commit()


def test_second_run_idempotent(migrated_db):
    """SECOND_RUN_IDEMPOTENT — ikinci çalıştırmada hiçbir şey değişmiyor."""
    m190 = _load_m190()
    with sqlite3.connect(migrated_db) as c:
        before = c.execute(f'SELECT COUNT(*) FROM {TBL}').fetchone()[0]

    result = m190.run(migrated_db, allow_canonical=False)
    assert result['ok'] is True
    assert result.get('skipped') is True

    with sqlite3.connect(migrated_db) as c:
        after = c.execute(f'SELECT COUNT(*) FROM {TBL}').fetchone()[0]
    assert after == before


def test_schema_migrations_recorded(migrated_db):
    """SCHEMA_MIGRATIONS_RECORDED — version=190 schema_migrations'a yazıldı."""
    with sqlite3.connect(migrated_db) as c:
        row = c.execute(
            "SELECT version, aciklama FROM schema_migrations WHERE version='190'"
        ).fetchone()
    assert row is not None, 'schema_migrations version=190 kaydı yok'


def test_parent_plan_count_unchanged(migrated_db):
    """PARENT_PLAN_COUNT_UNCHANGED — plan satır sayısı azalmadı."""
    if not CANONICAL_SOURCE.is_file():
        pytest.skip('canonical DB yok')
    with sqlite3.connect(f'file:{CANONICAL_SOURCE.as_posix()}?mode=ro', uri=True) as s:
        before = s.execute('SELECT COUNT(*) FROM uretim_model_plan').fetchone()[0]
    with sqlite3.connect(migrated_db) as d:
        after = d.execute(
            'SELECT COUNT(*) FROM uretim_model_plan WHERE mamul_skod NOT LIKE "BACKFILL-%"'
        ).fetchone()[0]
    assert after >= before


def test_user_count_unchanged(migrated_db):
    """USER_COUNT_UNCHANGED — sistem_kullanici satır sayısı değişmedi."""
    if not CANONICAL_SOURCE.is_file():
        pytest.skip('canonical DB yok')
    with sqlite3.connect(f'file:{CANONICAL_SOURCE.as_posix()}?mode=ro', uri=True) as s:
        before = s.execute('SELECT COUNT(*) FROM sistem_kullanici').fetchone()[0]
    with sqlite3.connect(migrated_db) as d:
        after = d.execute('SELECT COUNT(*) FROM sistem_kullanici').fetchone()[0]
    assert after == before


def test_db_integrity(migrated_db):
    """DB_INTEGRITY — PRAGMA integrity_check = ok."""
    with sqlite3.connect(migrated_db) as c:
        result = c.execute('PRAGMA integrity_check').fetchone()[0]
    assert result == 'ok'


# ============================================= repo katmanı — regression

def test_create_single_station_regression(repo, fresh_db):
    """CREATE_SINGLE_STATION_REGRESSION."""
    plan = repo.plan_ekle(_enj_payload(993801, [3]), USER_ID)
    assert plan['enj_istasyonlar'] == [3]
    assert _child_stations(fresh_db, plan['id']) == [3]


def test_create_multi_station_regression(repo, fresh_db):
    """CREATE_MULTI_STATION_REGRESSION."""
    plan = repo.plan_ekle(_enj_payload(993802, [7, 8]), USER_ID)
    assert plan['enj_istasyonlar'] == [7, 8]
    assert _child_stations(fresh_db, plan['id']) == [7, 8]


def test_update_self_no_false_conflict(repo, fresh_db):
    """PLAN_UPDATE_REGRESSION — self-update çakışma üretmez."""
    plan = repo.plan_ekle(_enj_payload(993803, [7, 8]), USER_ID)
    updated = repo.plan_guncelle(
        plan['id'],
        _enj_payload(993803, [7, 8]) | {'plan_notu': 'self-ok'},
        USER_ID,
    )
    assert updated['enj_istasyonlar'] == [7, 8]


def test_multi_station_conflict_blocked(repo, fresh_db):
    """MULTI_STATION_CONFLICT — başka planla gerçek çakışma engellenir."""
    repo.plan_ekle(_enj_payload(993804, [7, 8]), USER_ID)
    b = repo.plan_ekle(_enj_payload(993805, [3, 4], bas=ENJ_BAS2, bit=ENJ_BIT2), USER_ID)
    with pytest.raises(ValueError):
        repo.plan_guncelle(
            b['id'],
            _enj_payload(993805, [7, 8], bas=ENJ_BAS2, bit=ENJ_BIT2),
            USER_ID,
        )
    assert _child_stations(fresh_db, b['id']) == [3, 4]


# ============================================= ATP lock

def test_atp_stabilization_lock():
    """ATP_STABILIZATION_LOCK — validator PASS, ATP_DIFF=0."""
    import subprocess
    r = subprocess.run(
        [sys.executable, 'tools/validate_atp_stabilization_lock.py'],
        cwd=str(_REPO_ROOT),
        capture_output=True, text=True,
    )
    output = r.stdout + r.stderr
    assert 'ATP_STABILIZATION_LOCK=PASS' in output, f'ATP LOCK failed:\n{output}'
    assert 'ATP_DIFF=0' in output, f'ATP DIFF!=0:\n{output}'
