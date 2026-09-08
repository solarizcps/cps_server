# -*- coding: utf-8 -*-
"""plan_guncelle enjeksiyon doğrulama kapıları — regression (temp DB only).

Kök neden: plan_ekle zorunluluk / istasyon uygunluğu / tarih / çakışma
doğrulamalarını çalıştırıyordu, plan_guncelle hiçbirini çalıştırmıyordu.
Mevcut bir plan düzenlenerek başka planla çakışan veya enjeksiyon
rezervasyonu silinmiş (eksik) hâle getirilebiliyordu.

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

# M1 (id=1) ve M2 (id=2) 8 istasyonlu.
MAKINE_A = 1
MAKINE_B = 2
ENJ_BAS = '2027-07-01 07:00:00'
ENJ_BIT = '2027-07-03 17:00:00'
ENJ_BAS_KESISEN = '2027-07-02 07:00:00'
ENJ_BIT_KESISEN = '2027-07-04 17:00:00'
PLAN_BAS = '2027-07-06'
PLAN_BIT = '2027-07-20'
USER_ID = 1


@pytest.fixture()
def temp_db(monkeypatch):
    """Canonical DB'nin read-only kaynağından SQLite Backup API ile temp kopya."""
    if not CANONICAL_SOURCE.is_file():
        pytest.skip(f'kaynak DB yok: {CANONICAL_SOURCE}')

    tmpdir = tempfile.mkdtemp(prefix='enj_update_validation_')
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


def _enj_payload(sip_no, istasyonlar, *, makine_id=MAKINE_A, slot='A',
                 bas=ENJ_BAS, bit=ENJ_BIT, kalip_adedi=None):
    return {
        'sip_no': sip_no, 'sip_harinx': 1, 'rkod': 1,
        'mamul_skod': f'TEST-UPD-{sip_no}',
        'plan_donemi': 'bu_hafta',
        'plan_baslangic': PLAN_BAS, 'plan_bitis': PLAN_BIT,
        'miktar': 1000,
        'has_enjeksiyon': True,
        'enj_makine_id': makine_id, 'enj_slot': slot, 'enj_kalip_id': 1,
        'enj_istasyonlar': list(istasyonlar),
        'enj_kalip_adedi': len(istasyonlar) if kalip_adedi is None else kalip_adedi,
        'enj_aktif_goz': len(istasyonlar),
        'enj_plan_baslangic': bas, 'enj_plan_bitis': bit,
        'enj_calisma_modu': 'GUNDUZ_GECE', 'enj_hafta_sonu_calisma': 'HAYIR',
    }


def _genel_payload(sip_no):
    """Enjeksiyonsuz (legacy/genel) plan payload'ı."""
    return {
        'sip_no': sip_no, 'sip_harinx': 1, 'rkod': 1,
        'mamul_skod': f'TEST-GEN-{sip_no}',
        'plan_donemi': 'bu_hafta',
        'plan_baslangic': PLAN_BAS, 'plan_bitis': PLAN_BIT,
        'miktar': 500, 'has_enjeksiyon': False,
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


def _parent_row(db_path, plan_id):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        return dict(con.execute(
            'SELECT * FROM uretim_model_plan WHERE id=?', (plan_id,)
        ).fetchone())
    finally:
        con.close()


# ---------------------------------------------------------------- create yolu

def test_create_single_station_regression(repo, temp_db):
    """CREATE_SINGLE_STATION_REGRESSION"""
    plan = repo.plan_ekle(_enj_payload(991201, [3]), USER_ID)
    assert _parent_row(temp_db, plan['id'])['enj_istasyon_no'] == 3
    assert _child_stations(temp_db, plan['id']) == [3]
    assert repo.plan_get(plan['id'])['enj_istasyonlar'] == [3]


def test_create_multi_station_regression(repo, temp_db):
    """CREATE_MULTI_STATION_REGRESSION"""
    plan = repo.plan_ekle(_enj_payload(991202, [7, 8]), USER_ID)
    assert _parent_row(temp_db, plan['id'])['enj_istasyon_no'] == '7,8'
    assert _child_stations(temp_db, plan['id']) == [7, 8]
    assert repo.plan_get(plan['id'])['enj_istasyonlar'] == [7, 8]


# ------------------------------------------------------- self-exclusion / çakışma

def test_update_self_no_false_conflict(repo, temp_db):
    """UPDATE_SELF_NO_FALSE_CONFLICT — plan kendi rezervasyonuyla çakışmaz."""
    plan = repo.plan_ekle(_enj_payload(991203, [7, 8]), USER_ID)
    plan_id = plan['id']

    # Aynı makine/slot/istasyon/tarih ile güncelle: yanlış çakışma olmamalı
    guncel = repo.plan_guncelle(
        plan_id, _enj_payload(991203, [7, 8]) | {'plan_notu': 'self-update'},
        USER_ID,
    )
    assert guncel['enj_istasyonlar'] == [7, 8]
    assert guncel['plan_notu'] == 'self-update'
    assert _child_stations(temp_db, plan_id) == [7, 8]


def test_update_self_partial_overlap_no_false_conflict(repo, temp_db):
    """Kendi tarih aralığıyla kesişen kaydırma da self-çakışma üretmemeli."""
    plan = repo.plan_ekle(_enj_payload(991204, [7, 8]), USER_ID)
    plan_id = plan['id']
    guncel = repo.plan_guncelle(
        plan_id,
        _enj_payload(991204, [7, 8], bas=ENJ_BAS_KESISEN, bit=ENJ_BIT_KESISEN),
        USER_ID,
    )
    assert guncel['enj_istasyonlar'] == [7, 8]
    assert guncel['enj_plan_baslangic'] == ENJ_BAS_KESISEN


def test_update_to_other_plan_conflict_blocked(repo, temp_db):
    """UPDATE_TO_OTHER_PLAN_CONFLICT — başka planın istasyonuna geçiş engellenir."""
    a = repo.plan_ekle(_enj_payload(991205, [7, 8]), USER_ID)
    b = repo.plan_ekle(
        _enj_payload(991206, [3, 4], bas=ENJ_BAS_KESISEN, bit=ENJ_BIT_KESISEN),
        USER_ID,
    )

    with pytest.raises(ValueError) as exc:
        repo.plan_guncelle(
            b['id'],
            _enj_payload(991206, [7, 8], bas=ENJ_BAS_KESISEN, bit=ENJ_BIT_KESISEN),
            USER_ID,
        )
    assert 'çakış' in str(exc.value).lower() or 'dolu' in str(exc.value).lower()

    # B değişmemiş, A bozulmamış olmalı
    assert _child_stations(temp_db, b['id']) == [3, 4]
    assert _child_stations(temp_db, a['id']) == [7, 8]


def test_update_slot_isolation(repo, temp_db):
    """SLOT_ISOLATION — aynı makinenin diğer tarafı çakışma sayılmaz."""
    repo.plan_ekle(_enj_payload(991207, [7, 8], slot='A'), USER_ID)
    b = repo.plan_ekle(_enj_payload(991208, [3], slot='B'), USER_ID)

    guncel = repo.plan_guncelle(
        b['id'],
        _enj_payload(991208, [7, 8], slot='B',
                     bas=ENJ_BAS_KESISEN, bit=ENJ_BIT_KESISEN),
        USER_ID,
    )
    assert guncel['enj_istasyonlar'] == [7, 8]
    assert guncel['enj_slot'] == 'B'


def test_update_machine_isolation(repo, temp_db):
    """MACHINE_ISOLATION — diğer makine çakışma sayılmaz."""
    repo.plan_ekle(_enj_payload(991209, [7, 8], makine_id=MAKINE_A), USER_ID)
    b = repo.plan_ekle(_enj_payload(991210, [3], makine_id=MAKINE_B), USER_ID)

    guncel = repo.plan_guncelle(
        b['id'],
        _enj_payload(991210, [7, 8], makine_id=MAKINE_B,
                     bas=ENJ_BAS_KESISEN, bit=ENJ_BIT_KESISEN),
        USER_ID,
    )
    assert guncel['enj_istasyonlar'] == [7, 8]
    assert guncel['enj_makine_id'] == MAKINE_B


# ------------------------------------------------------------ iş kuralı kapıları

def test_update_mold_station_count_mismatch_blocked(repo, temp_db):
    """UPDATE_MOLD_STATION_COUNT_MISMATCH"""
    plan = repo.plan_ekle(_enj_payload(991211, [7, 8]), USER_ID)
    with pytest.raises(ValueError) as exc:
        repo.plan_guncelle(
            plan['id'], _enj_payload(991211, [7, 8], kalip_adedi=3), USER_ID,
        )
    assert 'kalıp aded' in str(exc.value).lower()
    assert _child_stations(temp_db, plan['id']) == [7, 8]


def test_update_out_of_range_station_blocked(repo, temp_db):
    """UPDATE_OUT_OF_RANGE_STATION"""
    plan = repo.plan_ekle(_enj_payload(991212, [7, 8]), USER_ID)
    with pytest.raises(ValueError):
        repo.plan_guncelle(plan['id'], _enj_payload(991212, [7, 99]), USER_ID)
    assert _child_stations(temp_db, plan['id']) == [7, 8]


def test_update_missing_required_enj_field_blocked(repo, temp_db):
    """Zorunlu enjeksiyon alanı silinerek eksik rezervasyona düşürülemez."""
    plan = repo.plan_ekle(_enj_payload(991213, [7, 8]), USER_ID)
    bozuk = _enj_payload(991213, [7, 8]) | {'enj_kalip_id': None}
    with pytest.raises(ValueError) as exc:
        repo.plan_guncelle(plan['id'], bozuk, USER_ID)
    assert 'eksik' in str(exc.value).lower()


def test_update_enj_date_order_blocked(repo, temp_db):
    """Enjeksiyon bitişi başlangıçtan önce olamaz."""
    plan = repo.plan_ekle(_enj_payload(991214, [7, 8]), USER_ID)
    with pytest.raises(ValueError):
        repo.plan_guncelle(
            plan['id'],
            _enj_payload(991214, [7, 8], bas=ENJ_BIT, bit=ENJ_BAS),
            USER_ID,
        )


def test_update_general_start_before_injection_end_blocked(repo, temp_db):
    """UPDATE_GENERAL_START_BEFORE_INJECTION_END — enj alanı gönderilmeden de."""
    plan = repo.plan_ekle(_enj_payload(991215, [7, 8]), USER_ID)
    onceki = _parent_row(temp_db, plan['id'])

    with pytest.raises(ValueError) as exc:
        repo.plan_guncelle(plan['id'], {'plan_baslangic': '2027-07-02'}, USER_ID)
    assert 'enjeksiyon tamamlanmadan' in str(exc.value).lower()

    # Genel alan da yazılmamış olmalı
    assert _parent_row(temp_db, plan['id'])['plan_baslangic'] == onceki['plan_baslangic']


# ------------------------------------------------------------- child tablo sync

def test_update_multi_station_save_reload(repo, temp_db):
    """UPDATE_MULTI_STATION_SAVE_RELOAD — tek istasyon -> çoklu istasyon."""
    plan = repo.plan_ekle(_enj_payload(991216, [3]), USER_ID)
    plan_id = plan['id']
    assert _child_stations(temp_db, plan_id) == [3]

    guncel = repo.plan_guncelle(plan_id, _enj_payload(991216, [7, 8]), USER_ID)
    assert guncel['enj_istasyonlar'] == [7, 8]
    assert _parent_row(temp_db, plan_id)['enj_istasyon_no'] == '7,8'
    assert repo.plan_get(plan_id)['enj_istasyonlar'] == [7, 8]


def test_update_child_rows_synced(repo, temp_db):
    """UPDATE_CHILD_ROWS_SYNCED — child satırlar makine/slot ile eşitlenir."""
    plan = repo.plan_ekle(_enj_payload(991217, [7, 8], slot='A'), USER_ID)
    plan_id = plan['id']

    repo.plan_guncelle(
        plan_id, _enj_payload(991217, [5, 6], slot='B', makine_id=MAKINE_B),
        USER_ID,
    )
    con = sqlite3.connect(temp_db)
    try:
        rows = con.execute(
            'SELECT istasyon_no, enj_makine_id, enj_slot '
            'FROM uretim_model_plan_enj_istasyon WHERE plan_id=? '
            'ORDER BY istasyon_no', (plan_id,)
        ).fetchall()
    finally:
        con.close()
    assert rows == [(5, MAKINE_B, 'B'), (6, MAKINE_B, 'B')]


def test_update_child_rows_removed_when_changed(repo, temp_db):
    """UPDATE_CHILD_ROWS_REMOVED_WHEN_CHANGED — eski satırlar kalmaz."""
    plan = repo.plan_ekle(_enj_payload(991218, [7, 8]), USER_ID)
    plan_id = plan['id']
    assert _child_stations(temp_db, plan_id) == [7, 8]

    repo.plan_guncelle(plan_id, _enj_payload(991218, [5]), USER_ID)
    assert _child_stations(temp_db, plan_id) == [5]
    assert _parent_row(temp_db, plan_id)['enj_istasyon_no'] == 5

    # Eski istasyonlar serbest kaldı: başka plan alabilmeli
    b = repo.plan_ekle(_enj_payload(991219, [7, 8]), USER_ID)
    assert _child_stations(temp_db, b['id']) == [7, 8]


# ------------------------------------------------------------------- rollback

def test_update_validation_failure_rollback(repo, temp_db):
    """UPDATE_VALIDATION_FAILURE_ROLLBACK — kısmi güncelleme olmaz."""
    plan = repo.plan_ekle(_enj_payload(991220, [7, 8]), USER_ID)
    plan_id = plan['id']
    onceki = _parent_row(temp_db, plan_id)
    onceki_child = _child_stations(temp_db, plan_id)

    bozuk = _enj_payload(991220, [7, 99]) | {
        'plan_notu': 'YAZILMAMALI', 'oncelik': 1,
    }
    with pytest.raises(ValueError):
        repo.plan_guncelle(plan_id, bozuk, USER_ID)

    sonraki = _parent_row(temp_db, plan_id)
    assert sonraki['plan_notu'] == onceki['plan_notu']
    assert sonraki['oncelik'] == onceki['oncelik']
    assert sonraki['enj_istasyon_no'] == onceki['enj_istasyon_no']
    assert sonraki['updated_at'] == onceki['updated_at']
    assert _child_stations(temp_db, plan_id) == onceki_child == [7, 8]


def test_update_conflict_failure_rollback(repo, temp_db):
    """Gerçek çakışmada da child tablo dokunulmamış kalır."""
    repo.plan_ekle(_enj_payload(991221, [7, 8]), USER_ID)
    b = repo.plan_ekle(
        _enj_payload(991222, [3, 4], bas=ENJ_BAS_KESISEN, bit=ENJ_BIT_KESISEN),
        USER_ID,
    )
    with pytest.raises(ValueError):
        repo.plan_guncelle(
            b['id'],
            _enj_payload(991222, [7, 8], bas=ENJ_BAS_KESISEN, bit=ENJ_BIT_KESISEN),
            USER_ID,
        )
    assert _child_stations(temp_db, b['id']) == [3, 4]
    assert repo.plan_get(b['id'])['enj_istasyonlar'] == [3, 4]


# ------------------------------------------------------- legacy / genel plan yolu

def test_legacy_general_update_unchanged(repo, temp_db):
    """LEGACY_GENERAL_UPDATE_UNCHANGED — enjeksiyonsuz plan güncellemesi serbest."""
    plan = repo.plan_ekle(_genel_payload(991223), USER_ID)
    plan_id = plan['id']

    guncel = repo.plan_guncelle(
        plan_id,
        {'plan_notu': 'genel not', 'oncelik': 2, 'plan_bitis': '2027-07-25'},
        USER_ID,
    )
    assert guncel['plan_notu'] == 'genel not'
    assert guncel['oncelik'] == 2
    assert guncel['plan_bitis'] == '2027-07-25'
    assert guncel['enj_makine_id'] is None
    assert _child_stations(temp_db, plan_id) == []


def test_general_update_preserves_injection_reservation(repo, temp_db):
    """Enjeksiyon alanına dokunmayan güncelleme rezervasyonu silmez."""
    plan = repo.plan_ekle(_enj_payload(991224, [7, 8]), USER_ID)
    plan_id = plan['id']

    guncel = repo.plan_guncelle(plan_id, {'plan_notu': 'sadece not'}, USER_ID)
    assert guncel['plan_notu'] == 'sadece not'
    assert guncel['enj_makine_id'] == MAKINE_A
    assert guncel['enj_slot'] == 'A'
    assert guncel['enj_istasyonlar'] == [7, 8]
    assert _child_stations(temp_db, plan_id) == [7, 8]


def test_null_invalid_legacy_safe(repo, temp_db):
    """NULL_INVALID_LEGACY_SAFE — bozuk/NULL legacy değer güncellemeyi kırmaz."""
    plan = repo.plan_ekle(_genel_payload(991225), USER_ID)
    plan_id = plan['id']

    con = sqlite3.connect(temp_db)
    try:
        con.execute(
            "UPDATE uretim_model_plan SET enj_istasyon_no='abc' WHERE id=?",
            (plan_id,),
        )
        con.commit()
    finally:
        con.close()

    assert repo.plan_get(plan_id)['enj_istasyonlar'] == []
    guncel = repo.plan_guncelle(plan_id, {'plan_notu': 'legacy ok'}, USER_ID)
    assert guncel['plan_notu'] == 'legacy ok'
    assert guncel['enj_istasyonlar'] == []
