# -*- coding: utf-8 -*-
"""Çok istasyonlu enjeksiyon rezervasyon kalıcılığı — regression (temp DB only).

Kök neden: plan_ekle çoklu seçimde enj_istasyon_no='7,8' yazıyordu, _enj_vals
alanı tek int'e zorladığı için değer NULL oluyordu ve NULL kalan istasyonlar
_check_conflicts kontrollerinde görünmüyordu. Tek istasyon çalışıyor, çoklu
istasyon çalışmıyordu.

Bu testler canonical DB'ye yazmaz: kaynak read-only açılır, SQLite Backup API
ile temp kopya üretilir ve yalnız temp kopyaya yazılır.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
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

# M1 (id=1) ve M2 (id=2) 8 istasyonlu; 7-8 çoklu rezervasyon için kullanılır.
MAKINE_A = 1
MAKINE_B = 2
ENJ_BAS = '2027-06-01 07:00:00'
ENJ_BIT = '2027-06-03 17:00:00'
ENJ_BAS_KESISEN = '2027-06-02 07:00:00'
ENJ_BIT_KESISEN = '2027-06-04 17:00:00'
PLAN_BAS = '2027-06-05'
PLAN_BIT = '2027-06-20'
USER_ID = 1


@pytest.fixture()
def temp_db(monkeypatch):
    """Canonical DB'nin read-only kaynağından SQLite Backup API ile temp kopya."""
    if not CANONICAL_SOURCE.is_file():
        pytest.skip(f'kaynak DB yok: {CANONICAL_SOURCE}')

    tmpdir = tempfile.mkdtemp(prefix='enj_istasyon_persist_')
    db_path = str(Path(tmpdir) / 'temp_test.db')

    src = sqlite3.connect(f'file:{CANONICAL_SOURCE.as_posix()}?mode=ro', uri=True)
    dst = sqlite3.connect(db_path)
    try:
        src.backup(dst)
        dst.commit()
        assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    finally:
        src.close()
        dst.close()

    import config
    monkeypatch.setattr(config.Config, 'MOCK_DB_PATH', db_path, raising=False)
    monkeypatch.setenv('CPS_MOCK_DB_PATH', db_path)
    monkeypatch.setenv('CPS_TEST_DB_GUARD', '1')

    from tools.atp_test_db_guard import is_canonical_path
    assert not is_canonical_path(db_path), 'temp DB canonical olarak görülüyor'

    try:
        yield db_path
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture()
def repo(temp_db):
    from modules.planlama import uretim_plan_repo as _repo
    return _repo


def _payload(sip_no, istasyonlar, *, makine_id=MAKINE_A, slot='A',
             bas=ENJ_BAS, bit=ENJ_BIT):
    return {
        'sip_no': sip_no, 'sip_harinx': 1, 'rkod': 1,
        'mamul_skod': f'TEST-ENJ-{sip_no}',
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


def _child_stations(db_path, plan_id):
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            'SELECT istasyon_no FROM uretim_model_plan_enj_istasyon '
            'WHERE plan_id=? ORDER BY istasyon_no', (plan_id,)
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def _raw_istasyon_no(db_path, plan_id):
    con = sqlite3.connect(db_path)
    try:
        return con.execute(
            'SELECT enj_istasyon_no FROM uretim_model_plan WHERE id=?',
            (plan_id,),
        ).fetchone()[0]
    finally:
        con.close()


def _conflicts(repo, istasyonlar, *, makine_id=MAKINE_A, slot='A',
               bas=ENJ_BAS_KESISEN, bit=ENJ_BIT_KESISEN):
    """_check_conflicts'i gerçek tüketici yolundan çağır."""
    from db import get_conn
    from modules.planlama.enj_kapasite_motor import _check_conflicts, _parse_dt

    con = get_conn()
    try:
        return _check_conflicts(
            con, makine_id, slot, list(istasyonlar),
            _parse_dt(bas), _parse_dt(bit),
        )
    finally:
        con.close()


# --------------------------------------------------------------- normalize
@pytest.mark.parametrize('deger, beklenen', [
    (None, []),
    ('', []),
    (7, [7]),
    ('7', [7]),
    ('7,8', [7, 8]),
    (' 7 , 8 ', [7, 8]),
    ('8,7,8', [7, 8]),
    ([7, '8', None, 'x'], [7, 8]),
    ('abc', []),
    ('0', []),
    (-3, []),
    (',,', []),
    ('7,,8', [7, 8]),
])
def test_normalize_istasyon_list(repo, deger, beklenen):
    assert repo._normalize_istasyon_list(deger) == beklenen


def test_istasyon_no_db_degeri_formati(repo):
    assert repo._istasyon_no_db_degeri([]) is None
    assert repo._istasyon_no_db_degeri([7]) == 7
    assert repo._istasyon_no_db_degeri([7, 8]) == '7,8'


# ------------------------------------------------- SINGLE_STATION_SAVE_RELOAD
def test_single_station_save_reload(repo, temp_db):
    plan = repo.plan_ekle(_payload(990101, [7]), USER_ID)
    plan_id = plan['id']

    assert _raw_istasyon_no(temp_db, plan_id) == 7
    assert _child_stations(temp_db, plan_id) == [7]
    assert repo.plan_get(plan_id)['enj_istasyonlar'] == [7]


# ------------------------------------------- MULTI_STATION_7_8_SAVE_RELOAD
def test_multi_station_7_8_save_reload(repo, temp_db):
    plan = repo.plan_ekle(_payload(990102, [7, 8]), USER_ID)
    plan_id = plan['id']

    # Regresyon çekirdeği: eskiden burada NULL kalıyordu.
    assert _raw_istasyon_no(temp_db, plan_id) == '7,8'
    assert _child_stations(temp_db, plan_id) == [7, 8]
    assert repo.plan_get(plan_id)['enj_istasyonlar'] == [7, 8]


# ------------------------------ MULTI_STATION_CONFLICT_ON_7 / _ON_8
@pytest.mark.parametrize('istasyon', [7, 8])
def test_multi_station_conflict_on_each_station(repo, istasyon):
    repo.plan_ekle(_payload(990103, [7, 8]), USER_ID)

    conflicts = _conflicts(repo, [istasyon])
    assert conflicts, f'İST{istasyon} için çakışma görülmedi'
    assert {c['istasyon_no'] for c in conflicts} == {istasyon}

    with pytest.raises(ValueError, match='çakışma'):
        repo._validate_enj_istasyon_availability(
            _open_conn(),
            _payload(990199, [istasyon],
                     bas=ENJ_BAS_KESISEN, bit=ENJ_BIT_KESISEN),
        )


def _open_conn():
    from db import get_conn
    return get_conn()


# ------------------------------------- NON_OVERLAPPING_STATION_ALLOWED
def test_non_overlapping_station_allowed(repo):
    repo.plan_ekle(_payload(990104, [7, 8]), USER_ID)

    assert _conflicts(repo, [5]) == []
    # Kesişmeyen istasyon kaydedilebilmeli
    plan = repo.plan_ekle(
        _payload(990105, [5], bas=ENJ_BAS_KESISEN, bit=ENJ_BIT_KESISEN),
        USER_ID,
    )
    assert plan['enj_istasyonlar'] == [5]


# ------------------------------------------------------- SLOT_A_B_ISOLATION
def test_slot_a_b_isolation(repo):
    repo.plan_ekle(_payload(990106, [7, 8], slot='A'), USER_ID)

    assert _conflicts(repo, [7, 8], slot='B') == []
    plan = repo.plan_ekle(
        _payload(990107, [7, 8], slot='B',
                 bas=ENJ_BAS_KESISEN, bit=ENJ_BIT_KESISEN),
        USER_ID,
    )
    assert plan['enj_istasyonlar'] == [7, 8]
    # A tarafı hâlâ çakışmalı
    assert _conflicts(repo, [7], slot='A')


# ------------------------------------------------------ MACHINE_ISOLATION
def test_machine_isolation(repo):
    repo.plan_ekle(_payload(990108, [7, 8], makine_id=MAKINE_A), USER_ID)

    assert _conflicts(repo, [7, 8], makine_id=MAKINE_B) == []
    plan = repo.plan_ekle(
        _payload(990109, [7, 8], makine_id=MAKINE_B,
                 bas=ENJ_BAS_KESISEN, bit=ENJ_BIT_KESISEN),
        USER_ID,
    )
    assert plan['enj_makine_id'] == MAKINE_B
    assert plan['enj_istasyonlar'] == [7, 8]
    assert _conflicts(repo, [7], makine_id=MAKINE_A)


# ------------------------------------------------- NULL_LEGACY_VALUE_SAFE
def test_null_legacy_value_safe(repo, temp_db):
    """Child satırı olmayan, enj_istasyon_no NULL legacy kayıt hata üretmemeli."""
    plan = repo.plan_ekle(_payload(990110, [7, 8]), USER_ID)
    plan_id = plan['id']

    con = sqlite3.connect(temp_db)
    try:
        con.execute(
            'DELETE FROM uretim_model_plan_enj_istasyon WHERE plan_id=?',
            (plan_id,))
        con.execute(
            'UPDATE uretim_model_plan SET enj_istasyon_no=NULL WHERE id=?',
            (plan_id,))
        con.commit()
    finally:
        con.close()

    assert repo.plan_get(plan_id)['enj_istasyonlar'] == []
    assert _conflicts(repo, [7, 8]) == []


# ---------------------------------------------- INVALID_LEGACY_VALUE_SAFE
def test_invalid_legacy_value_safe(repo, temp_db):
    """Bozuk legacy değer ('abc') okuma ve çakışma yolunu kırmamalı."""
    plan = repo.plan_ekle(_payload(990111, [7, 8]), USER_ID)
    plan_id = plan['id']

    con = sqlite3.connect(temp_db)
    try:
        con.execute(
            'DELETE FROM uretim_model_plan_enj_istasyon WHERE plan_id=?',
            (plan_id,))
        con.execute(
            "UPDATE uretim_model_plan SET enj_istasyon_no='abc' WHERE id=?",
            (plan_id,))
        con.commit()
    finally:
        con.close()

    assert repo.plan_get(plan_id)['enj_istasyonlar'] == []
    assert _conflicts(repo, [7, 8]) == []


# --------------------------------------------------- update path stays synced
def test_plan_guncelle_istasyonlari_esitler(repo, temp_db):
    plan = repo.plan_ekle(_payload(990112, [7, 8]), USER_ID)
    plan_id = plan['id']

    guncel = dict(_payload(990112, [5, 6]))
    guncel['enj_istasyonlar'] = [5, 6]
    repo.plan_guncelle(plan_id, guncel, USER_ID)

    assert _child_stations(temp_db, plan_id) == [5, 6]
    assert _raw_istasyon_no(temp_db, plan_id) == '5,6'
    assert repo.plan_get(plan_id)['enj_istasyonlar'] == [5, 6]
    # Eski istasyonlar serbest kalmalı
    assert _conflicts(repo, [7, 8]) == []


def test_canonical_db_yazilmadi(temp_db):
    """Guard: testler canonical yolu asla RW açmamalı."""
    from tools.atp_test_db_guard import is_canonical_path
    from config import Config
    assert not is_canonical_path(Config.MOCK_DB_PATH)
    assert Config.MOCK_DB_PATH == temp_db
