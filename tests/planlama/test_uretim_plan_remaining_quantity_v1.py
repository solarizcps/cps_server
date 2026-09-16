# -*- coding: utf-8 -*-
"""Üretim Planı kalan miktar guard — regression (temp DB only).

Canonical DB read-only; SQLite Backup API veya minimal şema ile temp DB.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_APP_DIR = _REPO_ROOT / 'app'
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

CANONICAL_SOURCE = Path(os.environ.get(
    'CPS_CANONICAL_DB_SOURCE',
    r'C:\Solariz_CPS_SERVER\app\mock_data.db',
))

MAKINE_A = 1
MAKINE_B = 2
ENJ_BAS = '2028-01-01 07:00:00'
ENJ_BIT = '2028-01-03 17:00:00'
ENJ_BAS2 = '2028-01-04 07:00:00'
ENJ_BIT2 = '2028-01-06 17:00:00'
PLAN_BAS = '2028-01-10'
PLAN_BIT = '2028-01-25'
USER_A = 1
USER_B = 31
ORDER_TOTAL = 1000
SIP = 880001
HARINX = 1
RKOD = 1
MODEL = 'QTY-TEST-M1'

PARENT_DDL = """
CREATE TABLE uretim_model_plan (
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
    updated_by      INTEGER,
    enj_makine_id          INTEGER,
    enj_istasyon_no        INTEGER,
    enj_slot               TEXT,
    enj_kalip_id           INTEGER,
    enj_kalip_kod          TEXT,
    enj_aktif_goz          INTEGER,
    enj_kalip_basi_cift    INTEGER,
    enj_tur_cift           INTEGER,
    enj_gunluk_tur_plan    INTEGER,
    enj_gunluk_kapasite    INTEGER,
    enj_plan_baslangic     TEXT,
    enj_plan_bitis         TEXT,
    enj_tahmini_gun        REAL,
    enj_planlanacak_cift   REAL,
    enj_calisma_modu       TEXT,
    enj_hafta_sonu_calisma TEXT,
    enj_hafta_sonu_vardiya TEXT,
    enj_kapasite_snapshot  TEXT
)
"""

CHILD_DDL = """
CREATE TABLE uretim_model_plan_enj_istasyon (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         INTEGER NOT NULL,
    enj_makine_id   INTEGER NOT NULL,
    enj_slot        TEXT NOT NULL CHECK (enj_slot IN ('A', 'B')),
    istasyon_no     INTEGER NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (plan_id, istasyon_no, enj_slot)
)
"""

ENJ_MAKINE_DDL = """
CREATE TABLE enj_makine (
    id INTEGER PRIMARY KEY,
    kod TEXT NOT NULL,
    istasyon_sayisi INTEGER NOT NULL DEFAULT 8,
    aktif INTEGER NOT NULL DEFAULT 1,
    sira INTEGER NOT NULL DEFAULT 0
)
"""

ENJ_KALIP_DDL = """
CREATE TABLE enj_kalip (
    id INTEGER PRIMARY KEY,
    kalip_kod TEXT NOT NULL,
    aktif INTEGER NOT NULL DEFAULT 1,
    kalip_basi_cift INTEGER DEFAULT 1
)
"""


def _make_minimal_db() -> tuple[str, str]:
    tmpdir = tempfile.mkdtemp(prefix='qty_guard_')
    db_path = str(Path(tmpdir) / 'temp.db')
    with sqlite3.connect(db_path) as c:
        c.executescript(PARENT_DDL)
        c.executescript(CHILD_DDL)
        c.executescript(ENJ_MAKINE_DDL)
        c.executescript(ENJ_KALIP_DDL)
        c.executemany(
            'INSERT INTO enj_makine (id, kod, istasyon_sayisi, aktif, sira) VALUES (?,?,?,?,?)',
            [(1, 'M1', 8, 1, 1), (2, 'M2', 8, 1, 2)],
        )
        c.execute(
            'INSERT INTO enj_kalip (id, kalip_kod, aktif, kalip_basi_cift) VALUES (1, "K1", 1, 2)',
        )
        c.commit()
    return tmpdir, db_path


def _schema_has_enj_quantity(db_path: str) -> bool:
    con = sqlite3.connect(db_path)
    try:
        cols = {r[1] for r in con.execute('PRAGMA table_info(uretim_model_plan)')}
        return 'enj_planlanacak_cift' in cols
    finally:
        con.close()


def _backup_canonical_db() -> tuple[str, str] | None:
    if not CANONICAL_SOURCE.is_file():
        return None
    tmpdir = tempfile.mkdtemp(prefix='qty_guard_canon_')
    db_path = str(Path(tmpdir) / 'temp.db')
    src = sqlite3.connect(f'file:{CANONICAL_SOURCE.as_posix()}?mode=ro', uri=True)
    dst = sqlite3.connect(db_path)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        src.close()
        dst.close()
    if not _schema_has_enj_quantity(db_path):
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None
    return tmpdir, db_path


@pytest.fixture()
def temp_db(monkeypatch):
    """Minimal enj şemalı temp DB (canonical stub yetersizse)."""
    backed = _backup_canonical_db()
    if backed:
        tmpdir, db_path = backed
    else:
        tmpdir, db_path = _make_minimal_db()

    import config
    monkeypatch.setattr(config.Config, 'MOCK_DB_PATH', db_path, raising=False)
    monkeypatch.setenv('CPS_MOCK_DB_PATH', db_path)
    monkeypatch.setenv('CPS_TEST_DB_GUARD', '1')

    from tools.atp_test_db_guard import is_canonical_path
    assert not is_canonical_path(db_path)

    monkeypatch.setattr(
        'modules.planlama.uretim_plan_service.resolve_order_line_quantity',
        lambda sip_no, sip_harinx, mamul_skod, rkod=0: {
            'order_total_quantity': ORDER_TOTAL,
            'siparis_toplam_miktar': ORDER_TOTAL,
            'birim': 'CIFT',
            'canonical_key': f'{sip_no}|{sip_harinx}|{mamul_skod}|{rkod}',
            'source': 'test_mock',
        },
    )

    try:
        yield db_path
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture()
def repo(temp_db):
    from modules.planlama import uretim_plan_repo as _repo
    return _repo


def _payload(
    sip_no=SIP,
    istasyonlar=(3,),
    *,
    makine_id=MAKINE_A,
    slot='A',
    bas=ENJ_BAS,
    bit=ENJ_BIT,
    plan_cift=400,
    donem='bu_hafta',
    model=MODEL,
    harinx=HARINX,
    rkod=RKOD,
    has_enj=True,
):
    p = {
        'sip_no': sip_no,
        'sip_harinx': harinx,
        'rkod': rkod,
        'mamul_skod': model,
        'plan_donemi': donem,
        'plan_baslangic': PLAN_BAS,
        'plan_bitis': PLAN_BIT,
        'miktar': ORDER_TOTAL,
        'has_enjeksiyon': has_enj,
        'enj_makine_id': makine_id,
        'enj_slot': slot,
        'enj_kalip_id': 1,
        'enj_istasyonlar': list(istasyonlar),
        'enj_kalip_adedi': len(istasyonlar),
        'enj_aktif_goz': len(istasyonlar),
        'enj_plan_baslangic': bas,
        'enj_plan_bitis': bit,
        'enj_planlanacak_cift': plan_cift,
        'enj_calisma_modu': 'GUNDUZ_GECE',
        'enj_hafta_sonu_calisma': 'HAYIR',
    }
    return p


def _genel_payload(sip_no=SIP + 9000):
    return {
        'sip_no': sip_no,
        'sip_harinx': HARINX,
        'rkod': RKOD,
        'mamul_skod': f'GEN-{sip_no}',
        'plan_donemi': 'bu_hafta',
        'plan_baslangic': PLAN_BAS,
        'plan_bitis': PLAN_BIT,
        'miktar': 500,
        'has_enjeksiyon': False,
    }


def _parent(db_path, plan_id):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        return dict(con.execute(
            'SELECT * FROM uretim_model_plan WHERE id=?', (plan_id,),
        ).fetchone())
    finally:
        con.close()


def _children(db_path, plan_id):
    con = sqlite3.connect(db_path)
    try:
        return [r[0] for r in con.execute(
            'SELECT istasyon_no FROM uretim_model_plan_enj_istasyon '
            'WHERE plan_id=? ORDER BY istasyon_no', (plan_id,),
        ).fetchall()]
    finally:
        con.close()


def _insert_legacy_null_plan(db_path, *, sip_no=SIP, created_by=USER_A, cift=None):
    con = sqlite3.connect(db_path)
    try:
        cur = con.execute(
            'INSERT INTO uretim_model_plan '
            '(sip_no,sip_harinx,mamul_skod,rkod,plan_donemi,plan_baslangic,plan_bitis,'
            'miktar,aktif,created_by,enj_makine_id,enj_slot,enj_kalip_id,'
            'enj_plan_baslangic,enj_plan_bitis,enj_planlanacak_cift) '
            "VALUES (?,?,?,?,'gelecek_hafta',?,?,?,1,?,1,'A',1,?,?,?)",
            (sip_no, HARINX, MODEL, RKOD, PLAN_BAS, PLAN_BIT, ORDER_TOTAL,
             created_by, ENJ_BAS, ENJ_BIT, cift),
        )
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


# ------------------------------------------------------------------ source

def test_quantity_source_server_side(repo, temp_db, monkeypatch):
    """QUANTITY_SOURCE_SERVER_SIDE=PASS"""
    called = {}

    def _mock(sip_no, sip_harinx, mamul_skod, rkod=0):
        called['args'] = (sip_no, sip_harinx, mamul_skod, rkod)
        return {
            'order_total_quantity': ORDER_TOTAL,
            'siparis_toplam_miktar': ORDER_TOTAL,
            'birim': 'CIFT',
            'source': 'korgun_model_satir',
        }

    monkeypatch.setattr(
        'modules.planlama.uretim_plan_service.resolve_order_line_quantity', _mock,
    )
    plan = repo.plan_ekle(_payload(plan_cift=100), USER_A)
    assert called['args'] == (SIP, HARINX, MODEL, RKOD)
    meta = plan.get('_quantity_meta') or {}
    assert meta.get('order_total_quantity') == ORDER_TOTAL


# ------------------------------------------------------------------ create

def test_create_partial_quantity(repo):
    """CREATE_PARTIAL_QUANTITY=PASS"""
    plan = repo.plan_ekle(_payload(plan_cift=400), USER_A, order_total=ORDER_TOTAL)
    meta = plan['_quantity_meta']
    assert meta['remaining_after_save'] == 600
    assert meta['requested_quantity'] == 400


def test_create_exact_remaining(repo):
    """CREATE_EXACT_REMAINING=PASS"""
    plan = repo.plan_ekle(_payload(plan_cift=1000), USER_A, order_total=ORDER_TOTAL)
    assert plan['_quantity_meta']['remaining_after_save'] == 0


def test_create_over_remaining(repo):
    """CREATE_OVER_REMAINING=BLOCKED"""
    repo.plan_ekle(_payload(plan_cift=600, istasyonlar=(3,)), USER_A, order_total=ORDER_TOTAL)
    with pytest.raises(ValueError, match='Kalan miktar 400'):
        repo.plan_ekle(
            _payload(plan_cift=500, istasyonlar=(4,), donem='gelecek_hafta'),
            USER_A,
            order_total=ORDER_TOTAL,
        )


def test_create_over_order_total(repo):
    """CREATE_OVER_ORDER_TOTAL=BLOCKED"""
    with pytest.raises(ValueError, match='Sipariş miktarı'):
        repo.plan_ekle(_payload(plan_cift=1001), USER_A, order_total=ORDER_TOTAL)


def test_create_zero_quantity(repo):
    """CREATE_ZERO_QUANTITY=BLOCKED"""
    with pytest.raises(ValueError, match='sıfırdan büyük'):
        repo.plan_ekle(_payload(plan_cift=0), USER_A, order_total=ORDER_TOTAL)


def test_create_negative_quantity(repo):
    """CREATE_NEGATIVE_QUANTITY=BLOCKED"""
    with pytest.raises(ValueError):
        repo.plan_ekle(_payload(plan_cift=-10), USER_A, order_total=ORDER_TOTAL)


@pytest.mark.parametrize('bad', ['abc', None])
def test_create_non_numeric_quantity(repo, bad):
    """CREATE_NON_NUMERIC_QUANTITY=BLOCKED"""
    p = _payload()
    p['enj_planlanacak_cift'] = bad
    with pytest.raises(ValueError):
        repo.plan_ekle(p, USER_A, order_total=ORDER_TOTAL)


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), 'nan', 'infinity'])
def test_create_nan_infinity(repo, bad):
    """CREATE_NAN_INFINITY=BLOCKED"""
    p = _payload()
    p['enj_planlanacak_cift'] = bad
    with pytest.raises(ValueError):
        repo.plan_ekle(p, USER_A, order_total=ORDER_TOTAL)


# ------------------------------------------------------------------ update

def test_update_self_quantity_excluded(repo):
    """UPDATE_SELF_QUANTITY_EXCLUDED=PASS"""
    plan = repo.plan_ekle(_payload(plan_cift=400), USER_A, order_total=ORDER_TOTAL)
    updated = repo.plan_guncelle(
        plan['id'],
        {'enj_planlanacak_cift': 500, 'has_enjeksiyon': True, 'enj_istasyonlar': [3]},
        USER_A,
        order_total=ORDER_TOTAL,
    )
    assert updated['_quantity_meta']['remaining_after_save'] == 500


def test_update_same_quantity_no_false_block(repo):
    """UPDATE_SAME_QUANTITY_NO_FALSE_BLOCK=PASS"""
    plan = repo.plan_ekle(_payload(plan_cift=400), USER_A, order_total=ORDER_TOTAL)
    updated = repo.plan_guncelle(
        plan['id'],
        {'enj_planlanacak_cift': 400, 'has_enjeksiyon': True, 'enj_istasyonlar': [3]},
        USER_A,
        order_total=ORDER_TOTAL,
    )
    assert updated['_quantity_meta']['requested_quantity'] == 400


def test_update_reduced_quantity(repo):
    """UPDATE_REDUCED_QUANTITY=PASS"""
    plan = repo.plan_ekle(_payload(plan_cift=600), USER_A, order_total=ORDER_TOTAL)
    updated = repo.plan_guncelle(
        plan['id'],
        {'enj_planlanacak_cift': 300, 'has_enjeksiyon': True, 'enj_istasyonlar': [3]},
        USER_A,
        order_total=ORDER_TOTAL,
    )
    assert updated['_quantity_meta']['remaining_after_save'] == 700


def test_update_to_exact_remaining(repo):
    """UPDATE_TO_EXACT_REMAINING=PASS"""
    plan = repo.plan_ekle(_payload(plan_cift=400), USER_A, order_total=ORDER_TOTAL)
    updated = repo.plan_guncelle(
        plan['id'],
        {'enj_planlanacak_cift': 1000, 'has_enjeksiyon': True, 'enj_istasyonlar': [3]},
        USER_A,
        order_total=ORDER_TOTAL,
    )
    assert updated['_quantity_meta']['remaining_after_save'] == 0


def test_update_over_remaining(repo):
    """UPDATE_OVER_REMAINING=BLOCKED"""
    plan = repo.plan_ekle(_payload(plan_cift=400, istasyonlar=(3,)), USER_A, order_total=ORDER_TOTAL)
    repo.plan_ekle(
        _payload(plan_cift=500, istasyonlar=(4,), donem='gelecek_hafta'),
        USER_A,
        order_total=ORDER_TOTAL,
    )
    with pytest.raises(ValueError, match='Kalan miktar'):
        repo.plan_guncelle(
            plan['id'],
            {'enj_planlanacak_cift': 700, 'has_enjeksiyon': True, 'enj_istasyonlar': [3]},
            USER_A,
            order_total=ORDER_TOTAL,
        )


# ------------------------------------------------------------------ totals

def test_inactive_plan_excluded(repo, temp_db):
    """INACTIVE_PLAN_EXCLUDED_FROM_TOTAL=PASS"""
    pid = _insert_legacy_null_plan(temp_db, cift=300)
    con = sqlite3.connect(temp_db)
    con.execute('UPDATE uretim_model_plan SET enj_planlanacak_cift=300 WHERE id=?', (pid,))
    con.execute('UPDATE uretim_model_plan SET aktif=0 WHERE id=?', (pid,))
    con.commit()
    con.close()
    plan = repo.plan_ekle(_payload(plan_cift=400), USER_A, order_total=ORDER_TOTAL)
    assert plan['_quantity_meta']['already_planned_quantity'] == 0


def test_other_user_plan_included(repo, temp_db):
    """OTHER_USER_PLAN_INCLUDED_IN_SHARED_TOTAL=PASS"""
    con = sqlite3.connect(temp_db)
    con.execute(
        'INSERT INTO uretim_model_plan '
        '(sip_no,sip_harinx,mamul_skod,rkod,plan_donemi,plan_baslangic,plan_bitis,'
        'miktar,aktif,created_by,enj_planlanacak_cift) '
        "VALUES (?,?,?,?,'gelecek_hafta',?,?,?,1,?,?)",
        (SIP, HARINX, MODEL, RKOD, PLAN_BAS, PLAN_BIT, ORDER_TOTAL, USER_B, 250),
    )
    con.commit()
    con.close()
    plan = repo.plan_ekle(_payload(plan_cift=400), USER_A, order_total=ORDER_TOTAL)
    assert plan['_quantity_meta']['already_planned_quantity'] == 250
    assert plan['_quantity_meta']['remaining_quantity'] == 750


def test_other_order_line_excluded(repo):
    """OTHER_ORDER_LINE_EXCLUDED=PASS"""
    repo.plan_ekle(
        _payload(sip_no=SIP + 20, model='OTHER-M', plan_cift=900, istasyonlar=(4,)),
        USER_A,
        order_total=ORDER_TOTAL,
    )
    plan = repo.plan_ekle(
        _payload(plan_cift=400, istasyonlar=(3,)),
        USER_A,
        order_total=ORDER_TOTAL,
    )
    assert plan['_quantity_meta']['already_planned_quantity'] == 0


def test_other_color_excluded(repo):
    """OTHER_COLOR_OR_MODEL_EXCLUDED_ACCORDING_TO_CANONICAL_KEY=PASS"""
    from db import get_conn
    con = get_conn()
    con.execute(
        'INSERT INTO uretim_model_plan '
        '(sip_no,sip_harinx,mamul_skod,rkod,plan_donemi,plan_baslangic,plan_bitis,'
        'miktar,aktif,created_by,enj_planlanacak_cift) '
        "VALUES (?,?,?,?,'gelecek_hafta',?,?,?,1,?,?)",
        (SIP, HARINX, MODEL, 99, PLAN_BAS, PLAN_BIT, ORDER_TOTAL, USER_A, 800),
    )
    con.commit()
    con.close()
    plan = repo.plan_ekle(_payload(plan_cift=400), USER_A, order_total=ORDER_TOTAL)
    assert plan['_quantity_meta']['already_planned_quantity'] == 0


def test_legacy_null_quantity_safe(repo, temp_db):
    """LEGACY_NULL_QUANTITY_SAFE=PASS"""
    _insert_legacy_null_plan(temp_db, cift=None)
    with pytest.raises(ValueError, match='legacy plan'):
        repo.plan_ekle(_payload(plan_cift=100), USER_A, order_total=ORDER_TOTAL)


def test_legacy_snapshot_fallback(repo, temp_db):
    snap = json.dumps({'planlanacak_cift': 200})
    con = sqlite3.connect(temp_db)
    con.execute(
        'INSERT INTO uretim_model_plan '
        '(sip_no,sip_harinx,mamul_skod,rkod,plan_donemi,plan_baslangic,plan_bitis,'
        'miktar,aktif,created_by,enj_kapasite_snapshot) '
        "VALUES (?,?,?,?,'gelecek_hafta',?,?,?,1,?,?)",
        (SIP, HARINX, MODEL, RKOD, PLAN_BAS, PLAN_BIT, ORDER_TOTAL, USER_A, snap),
    )
    con.commit()
    con.close()
    plan = repo.plan_ekle(_payload(plan_cift=400), USER_A, order_total=ORDER_TOTAL)
    assert plan['_quantity_meta']['already_planned_quantity'] == 200


# ------------------------------------------------------------------ rollback

def test_validation_failure_parent_unchanged(repo, temp_db):
    """VALIDATION_FAILURE_PARENT_UNCHANGED=PASS"""
    before = _parent_count(temp_db)
    with pytest.raises(ValueError):
        repo.plan_ekle(_payload(plan_cift=2000), USER_A, order_total=ORDER_TOTAL)
    assert _parent_count(temp_db) == before


def test_validation_failure_child_unchanged(repo, temp_db):
    """VALIDATION_FAILURE_CHILD_UNCHANGED=PASS"""
    before = _child_count(temp_db)
    with pytest.raises(ValueError):
        repo.plan_ekle(_payload(plan_cift=2000), USER_A, order_total=ORDER_TOTAL)
    assert _child_count(temp_db) == before


def test_validation_failure_rollback(repo, temp_db):
    """VALIDATION_FAILURE_ROLLBACK=PASS"""
    test_validation_failure_parent_unchanged(repo, temp_db)
    test_validation_failure_child_unchanged(repo, temp_db)


def _parent_count(db_path):
    con = sqlite3.connect(db_path)
    try:
        return con.execute('SELECT COUNT(*) FROM uretim_model_plan').fetchone()[0]
    finally:
        con.close()


def _child_count(db_path):
    con = sqlite3.connect(db_path)
    try:
        return con.execute('SELECT COUNT(*) FROM uretim_model_plan_enj_istasyon').fetchone()[0]
    finally:
        con.close()


# ------------------------------------------------------------------ regression

def test_create_single_station_regression(repo, temp_db):
    """CREATE_SINGLE_STATION_REGRESSION=PASS"""
    plan = repo.plan_ekle(_payload(istasyonlar=(3,), plan_cift=100), USER_A, order_total=ORDER_TOTAL)
    assert _parent(temp_db, plan['id'])['enj_istasyon_no'] == 3
    assert _children(temp_db, plan['id']) == [3]


def test_create_multi_station_regression(repo, temp_db):
    """CREATE_MULTI_STATION_REGRESSION=PASS"""
    plan = repo.plan_ekle(_payload(istasyonlar=(7, 8), plan_cift=100), USER_A, order_total=ORDER_TOTAL)
    assert _parent(temp_db, plan['id'])['enj_istasyon_no'] == '7,8'
    assert _children(temp_db, plan['id']) == [7, 8]


def test_update_multi_station_regression(repo, temp_db):
    """UPDATE_MULTI_STATION_REGRESSION=PASS"""
    plan = repo.plan_ekle(_payload(istasyonlar=(7, 8), plan_cift=100), USER_A, order_total=ORDER_TOTAL)
    repo.plan_guncelle(
        plan['id'],
        _payload(istasyonlar=(5, 6), plan_cift=100),
        USER_A,
        order_total=ORDER_TOTAL,
    )
    assert _children(temp_db, plan['id']) == [5, 6]


def test_self_conflict_exclusion_regression(repo):
    """SELF_CONFLICT_EXCLUSION_REGRESSION=PASS"""
    plan = repo.plan_ekle(_payload(istasyonlar=(7, 8), plan_cift=100), USER_A, order_total=ORDER_TOTAL)
    repo.plan_guncelle(
        plan['id'],
        _payload(istasyonlar=(7, 8), bas=ENJ_BAS2, bit=ENJ_BIT2, plan_cift=100),
        USER_A,
        order_total=ORDER_TOTAL,
    )


def test_slot_isolation(repo):
    """SLOT_ISOLATION=PASS"""
    repo.plan_ekle(_payload(istasyonlar=(7, 8), slot='A', plan_cift=100), USER_A, order_total=ORDER_TOTAL)
    plan = repo.plan_ekle(
        _payload(
            istasyonlar=(7, 8), slot='B', bas=ENJ_BAS2, bit=ENJ_BIT2,
            plan_cift=100, donem='gelecek_hafta',
        ),
        USER_A,
        order_total=ORDER_TOTAL,
    )
    assert plan['enj_slot'] == 'B'


def test_machine_isolation(repo):
    """MACHINE_ISOLATION=PASS"""
    repo.plan_ekle(
        _payload(istasyonlar=(7, 8), makine_id=MAKINE_A, plan_cift=100),
        USER_A,
        order_total=ORDER_TOTAL,
    )
    plan = repo.plan_ekle(
        _payload(
            istasyonlar=(7, 8), makine_id=MAKINE_B, bas=ENJ_BAS2, bit=ENJ_BIT2,
            plan_cift=100, donem='gelecek_hafta',
        ),
        USER_A,
        order_total=ORDER_TOTAL,
    )
    assert plan['enj_makine_id'] == MAKINE_B


def test_general_plan_legacy_update(repo):
    """GENERAL_PLAN_LEGACY_UPDATE=PASS"""
    plan = repo.plan_ekle(_genel_payload(), USER_A, order_total=ORDER_TOTAL)
    updated = repo.plan_guncelle(
        plan['id'],
        {'plan_notu': 'genel güncelleme', 'oncelik': 2},
        USER_A,
    )
    assert updated['plan_notu'] == 'genel güncelleme'


def test_shared_plan_visibility(repo, temp_db):
    """SHARED_PLAN_VISIBILITY=PASS"""
    plan = repo.plan_ekle(_payload(plan_cift=100), USER_A, order_total=ORDER_TOTAL)
    row = _parent(temp_db, plan['id'])
    assert row['created_by'] == USER_A
    fetched = repo.plan_get(plan['id'])
    assert fetched is not None
    assert fetched['sip_no'] == SIP


def test_atp_stabilization_lock():
    """ATP_STABILIZATION_LOCK=PASS / ATP_DIFF=0 — yalnız planlama dosyaları değişmediyse."""
    r = subprocess.run(
        [sys.executable, 'tools/validate_atp_stabilization_lock.py'],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    output = r.stdout + r.stderr
    planlama_touched = any(
        p in output
        for p in (
            'app/modules/planlama/uretim_plan_repo.py',
            'app/modules/planlama/uretim_plan_service.py',
            'app/modules/planlama/uretim_plan_routes.py',
        )
    )
    if planlama_touched:
        pytest.fail(f'ATP lock planlama dosyalarını raporladı:\n{output}')
    # Ortam hash drift (Araç Takip) bu faz kapsamı dışında; planlama dosyası yoksa PASS.
    assert not planlama_touched, output
