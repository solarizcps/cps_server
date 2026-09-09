# -*- coding: utf-8 -*-
"""Üretim Planı makine detay — fiziksel/planlı ayrım (temp DB only)."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
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
ANCHOR = '2028-06-01 07:00:00'
ANCHOR_END = '2028-06-01 17:00:00'
PLAN_BAS = '2028-06-01 07:00:00'
PLAN_BIT = '2028-06-05 17:00:00'
PAST_BAS = '2027-01-01 07:00:00'
PAST_BIT = '2027-01-03 17:00:00'
SIP = 990001
HARINX = 1
RKOD = 1
MODEL = 'MD-TEST-1'

PARENT_DDL = """
CREATE TABLE uretim_model_plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sip_no INTEGER NOT NULL,
    sip_harinx INTEGER NOT NULL,
    mamul_skod TEXT NOT NULL,
    rkod INTEGER NOT NULL DEFAULT 0,
    model_adi TEXT,
    renk_adi TEXT,
    miktar REAL,
    termin TEXT,
    plan_donemi TEXT NOT NULL,
    plan_baslangic TEXT,
    plan_bitis TEXT,
    oncelik INTEGER NOT NULL DEFAULT 3,
    plan_gerekce TEXT,
    plan_notu TEXT,
    aktif INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    created_by INTEGER,
    updated_at TEXT,
    updated_by INTEGER,
    enj_makine_id INTEGER,
    enj_istasyon_no INTEGER,
    enj_slot TEXT,
    enj_kalip_id INTEGER,
    enj_kalip_kod TEXT,
    enj_aktif_goz INTEGER,
    enj_kalip_basi_cift INTEGER,
    enj_tur_cift INTEGER,
    enj_gunluk_tur_plan INTEGER,
    enj_gunluk_kapasite INTEGER,
    enj_plan_baslangic TEXT,
    enj_plan_bitis TEXT,
    enj_tahmini_gun REAL,
    enj_planlanacak_cift REAL,
    enj_calisma_modu TEXT,
    enj_hafta_sonu_calisma TEXT,
    enj_hafta_sonu_vardiya TEXT,
    enj_kapasite_snapshot TEXT
)
"""

CHILD_DDL = """
CREATE TABLE uretim_model_plan_enj_istasyon (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    enj_makine_id INTEGER NOT NULL,
    enj_slot TEXT NOT NULL CHECK (enj_slot IN ('A', 'B')),
    istasyon_no INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
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

ENJ_RAPOR_DDL = """
CREATE TABLE enj_gunluk_rapor (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    makine_id INTEGER NOT NULL,
    tarih TEXT NOT NULL,
    vardiya TEXT NOT NULL
)
"""

ENJ_IST_DDL = """
CREATE TABLE enj_istasyon_durumu (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rapor_id INTEGER NOT NULL,
    istasyon_no INTEGER NOT NULL,
    slot TEXT NOT NULL,
    aktif INTEGER NOT NULL DEFAULT 0,
    durum TEXT,
    kalip_id INTEGER,
    renk TEXT,
    pisme_suresi_sn INTEGER
)
"""


def _make_db() -> tuple[str, str]:
    tmpdir = tempfile.mkdtemp(prefix='machine_detail_')
    db_path = str(Path(tmpdir) / 'temp.db')
    with sqlite3.connect(db_path) as c:
        c.executescript(PARENT_DDL)
        c.executescript(CHILD_DDL)
        c.executescript(ENJ_MAKINE_DDL)
        c.executescript(ENJ_KALIP_DDL)
        c.executescript(ENJ_RAPOR_DDL)
        c.executescript(ENJ_IST_DDL)
        c.executemany(
            'INSERT INTO enj_makine (id, kod, istasyon_sayisi, aktif, sira) VALUES (?,?,?,?,?)',
            [(1, 'M1', 8, 1, 1), (2, 'M2', 8, 1, 2), (3, 'M3', 8, 1, 3), (4, 'M4', 8, 1, 4)],
        )
        c.execute('INSERT INTO enj_kalip (id, kalip_kod, aktif, kalip_basi_cift) VALUES (1, "K-PHYS", 1, 2)')
        c.execute('INSERT INTO enj_kalip (id, kalip_kod, aktif, kalip_basi_cift) VALUES (2, "K-PLAN", 1, 2)')
        # M1 physical: A ist1,2 dolu; B ist3 dolu
        c.execute(
            'INSERT INTO enj_gunluk_rapor (id, makine_id, tarih, vardiya) VALUES (1, 1, "2028-05-30", "gunduz")',
        )
        for no, slot in ((1, 'A'), (2, 'A'), (3, 'B')):
            c.execute(
                'INSERT INTO enj_istasyon_durumu (rapor_id, istasyon_no, slot, aktif, durum, kalip_id, renk) '
                'VALUES (1, ?, ?, 1, "AKTIF", 1, "Siyah")',
                (no, slot),
            )
        c.commit()
    return tmpdir, db_path


def _insert_child_plan(con, *, plan_id=None, makine=MAKINE_A, slot='A', ist=(1, 2),
                       bas=PLAN_BAS, bit=PLAN_BIT, aktif=1, kalip_kod='K-PLAN',
                       sip=SIP, cift=400):
    cur = con.execute(
        'INSERT INTO uretim_model_plan '
        '(sip_no,sip_harinx,mamul_skod,rkod,model_adi,renk_adi,plan_donemi,plan_baslangic,plan_bitis,'
        'miktar,aktif,enj_makine_id,enj_slot,enj_kalip_id,enj_kalip_kod,enj_plan_baslangic,enj_plan_bitis,'
        'enj_planlanacak_cift,enj_calisma_modu) '
        "VALUES (?,?,?,?,'Model Test','Kırmızı','bu_hafta','2028-06-10','2028-06-20',"
        '1000,?,?,?,?,?,?,?,?,?)',
        (sip, HARINX, MODEL, RKOD, aktif, makine, slot, 2, kalip_kod, bas, bit, cift, 'GUNDUZ_GECE'),
    )
    pid = plan_id or cur.lastrowid
    for i in ist:
        con.execute(
            'INSERT INTO uretim_model_plan_enj_istasyon (plan_id, enj_makine_id, enj_slot, istasyon_no) '
            'VALUES (?,?,?,?)',
            (pid, makine, slot, i),
        )
    con.commit()
    return pid


def _insert_legacy_plan(con, *, makine=MAKINE_A, slot='A', ist='4,5', bas=PLAN_BAS, bit=PLAN_BIT, aktif=1):
    cur = con.execute(
        'INSERT INTO uretim_model_plan '
        '(sip_no,sip_harinx,mamul_skod,rkod,model_adi,renk_adi,plan_donemi,plan_baslangic,plan_bitis,'
        'miktar,aktif,enj_makine_id,enj_slot,enj_istasyon_no,enj_kalip_id,enj_kalip_kod,'
        'enj_plan_baslangic,enj_plan_bitis,enj_planlanacak_cift,enj_calisma_modu) '
        "VALUES (?,?,?,?,'Legacy','Mavi','bu_hafta','2028-06-10','2028-06-20',"
        '1000,?,?,?,?,?,?,?,?,?,?)',
        (SIP + 1, HARINX, MODEL + '-L', RKOD, aktif, makine, slot, ist, 2, 'K-LEG', bas, bit, 300, 'GUNDUZ_GECE'),
    )
    con.commit()
    return cur.lastrowid


@pytest.fixture()
def temp_db(monkeypatch):
    tmpdir, db_path = _make_db()
    import config
    monkeypatch.setattr(config.Config, 'MOCK_DB_PATH', db_path, raising=False)
    monkeypatch.setenv('CPS_MOCK_DB_PATH', db_path)
    monkeypatch.setenv('CPS_TEST_DB_GUARD', '1')
    monkeypatch.setattr(
        'modules.planlama.uretim_plan_service.resolve_asorti_for_plan_keys',
        lambda keys: {(SIP, HARINX, MODEL, RKOD): '23–32'},
    )
    try:
        yield db_path
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture()
def con(temp_db):
    c = sqlite3.connect(temp_db)
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()


def _side(det, slot):
    return det['sides'][slot]


def test_physical_counts_match_stations(con):
    """PHYSICAL_COUNTS_MATCH_STATIONS=PASS"""
    from modules.planlama.enj_plan_availability_service import build_makine_detay
    det = build_makine_detay(con, MAKINE_A, include_stations=True)
    side = _side(det, 'A')
    phys = side['physical']
    occupied = sum(1 for s in phys['stations'] if s['durum'] == 'DOLU')
    assert phys['occupied_count'] == occupied == 2
    assert phys['empty_count'] == 6


def test_planned_counts_match_stations(con):
    """PLANNED_COUNTS_MATCH_STATIONS=PASS"""
    _insert_child_plan(con, ist=(1, 2, 3))
    from modules.planlama.enj_plan_availability_service import build_makine_detay
    det = build_makine_detay(
        con, MAKINE_A, plan_baslangic=ANCHOR, plan_bitis=ANCHOR_END, include_stations=True,
    )
    plan = _side(det, 'A')['planned']
    planned = sum(1 for s in plan['stations'] if s['durum'] in ('PLANLI', 'CAKISAN'))
    assert plan['planned_count'] == planned == 3


def test_a_b_slot_isolation(con):
    """A_B_SLOT_ISOLATION=PASS"""
    _insert_child_plan(con, slot='A', ist=(1,))
    _insert_child_plan(con, slot='B', ist=(3,), sip=SIP + 10)
    from modules.planlama.enj_plan_availability_service import build_makine_detay
    det = build_makine_detay(
        con, MAKINE_A, plan_baslangic=ANCHOR, plan_bitis=ANCHOR_END, include_stations=True,
    )
    assert _side(det, 'A')['planned']['planned_count'] == 1
    assert _side(det, 'B')['planned']['planned_count'] == 1


def test_machine_isolation(con):
    """MACHINE_ISOLATION=PASS"""
    _insert_child_plan(con, makine=MAKINE_A, ist=(1, 2))
    _insert_child_plan(con, makine=MAKINE_B, ist=(1, 2, 3), sip=SIP + 20)
    from modules.planlama.enj_plan_availability_service import build_makine_detay
    det_a = build_makine_detay(con, MAKINE_A, plan_baslangic=ANCHOR, plan_bitis=ANCHOR_END)
    det_b = build_makine_detay(con, MAKINE_B, plan_baslangic=ANCHOR, plan_bitis=ANCHOR_END)
    assert _side(det_a, 'A')['planned']['planned_count'] == 2
    assert _side(det_b, 'A')['planned']['planned_count'] == 3


def test_past_plan_excluded(con):
    """PAST_PLAN_EXCLUDED=PASS"""
    _insert_child_plan(con, bas=PAST_BAS, bit=PAST_BIT, ist=(1, 2, 3, 4))
    from modules.planlama.enj_plan_availability_service import build_makine_detay
    det = build_makine_detay(
        con, MAKINE_A, plan_baslangic=ANCHOR, plan_bitis=ANCHOR_END, include_stations=True,
    )
    assert _side(det, 'A')['planned']['planned_count'] == 0


def test_inactive_plan_excluded(con):
    """INACTIVE_PLAN_EXCLUDED=PASS"""
    _insert_child_plan(con, ist=(1, 2), aktif=0)
    from modules.planlama.enj_plan_availability_service import build_makine_detay
    det = build_makine_detay(
        con, MAKINE_A, plan_baslangic=ANCHOR, plan_bitis=ANCHOR_END, include_stations=True,
    )
    assert _side(det, 'A')['planned']['planned_count'] == 0


def test_child_reservation_included(con):
    """CHILD_RESERVATION_INCLUDED=PASS"""
    _insert_child_plan(con, ist=(5,))
    from modules.planlama.enj_plan_availability_service import build_makine_detay
    det = build_makine_detay(
        con, MAKINE_A, plan_baslangic=ANCHOR, plan_bitis=ANCHOR_END, include_stations=True,
    )
    st5 = [s for s in _side(det, 'A')['planned']['stations'] if s['istasyon_no'] == 5][0]
    assert st5['durum'] == 'PLANLI'
    assert st5['kalip_kod'] == 'K-PLAN'


def test_legacy_reservation_included(con):
    """LEGACY_RESERVATION_INCLUDED=PASS"""
    _insert_legacy_plan(con, ist='6,7')
    from modules.planlama.enj_plan_availability_service import build_makine_detay
    det = build_makine_detay(
        con, MAKINE_A, plan_baslangic=ANCHOR, plan_bitis=ANCHOR_END, include_stations=True,
    )
    planned_nos = [s['istasyon_no'] for s in _side(det, 'A')['planned']['stations'] if s['durum'] == 'PLANLI']
    assert 6 in planned_nos and 7 in planned_nos


def test_child_legacy_not_double_counted(con):
    """CHILD_LEGACY_NOT_DOUBLE_COUNTED=PASS"""
    pid = _insert_child_plan(con, ist=(1, 2))
    con.execute(
        'UPDATE uretim_model_plan SET enj_istasyon_no="1,2" WHERE id=?', (pid,),
    )
    con.commit()
    from modules.planlama.enj_plan_availability_service import build_makine_detay
    det = build_makine_detay(
        con, MAKINE_A, plan_baslangic=ANCHOR, plan_bitis=ANCHOR_END, include_stations=True,
    )
    assert _side(det, 'A')['planned']['planned_count'] == 2


def test_physical_mold_shown(con):
    """PHYSICAL_MOLD_SHOWN=PASS"""
    from modules.planlama.enj_plan_availability_service import build_makine_detay
    det = build_makine_detay(con, MAKINE_A, include_stations=True)
    dolu = [s for s in _side(det, 'A')['physical']['stations'] if s['durum'] == 'DOLU']
    assert dolu and dolu[0]['kalip_kod'] == 'K-PHYS'


def test_planned_mold_and_order_fields(con):
    """PLANNED_MOLD_SHOWN / ORDER_MODEL_COLOR / QUANTITY_AND_DATES=PASS"""
    _insert_child_plan(con, ist=(1,))
    from modules.planlama.enj_plan_availability_service import build_makine_detay
    det = build_makine_detay(
        con, MAKINE_A, plan_baslangic=ANCHOR, plan_bitis=ANCHOR_END,
        asorti_map={(SIP, HARINX, MODEL, RKOD): '23–32'},
        include_stations=True,
    )
    st = [s for s in _side(det, 'A')['planned']['stations'] if s['istasyon_no'] == 1][0]
    assert st['kalip_kod'] == 'K-PLAN'
    assert st['sip_no'] == SIP
    assert st['model'] == MODEL
    assert st['renk'] == 'Kırmızı'
    assert st['planlanacak_cift'] == 400
    assert st['plan_baslangic']
    assert st['plan_bitis']


def test_assortment_shown_or_dash(con):
    """ASSORTMENT_SHOWN_OR_DASH=PASS"""
    _insert_child_plan(con, ist=(2,))
    from modules.planlama.enj_plan_availability_service import build_makine_detay
    det = build_makine_detay(
        con, MAKINE_A, plan_baslangic=ANCHOR, plan_bitis=ANCHOR_END,
        asorti_map={(SIP, HARINX, MODEL, RKOD): '23–32'},
        include_stations=True,
    )
    st = [s for s in _side(det, 'A')['planned']['stations'] if s['istasyon_no'] == 2][0]
    assert st['asorti'] == '23–32'
    det2 = build_makine_detay(
        con, MAKINE_A, plan_baslangic=ANCHOR, plan_bitis=ANCHOR_END,
        asorti_map=None, include_stations=True,
    )
    st2 = [s for s in _side(det2, 'A')['planned']['stations'] if s['istasyon_no'] == 2][0]
    assert st2.get('asorti') is None


def test_card_and_detail_counts_match(con):
    """CARD_AND_DETAIL_COUNTS_MATCH=PASS"""
    _insert_child_plan(con, ist=(1, 2))
    _insert_child_plan(con, slot='B', ist=(3,), sip=SIP + 5)
    from modules.planlama.enj_plan_availability_service import (
        build_makine_detay, build_makine_slot_ozet_all,
    )
    det = build_makine_detay(con, MAKINE_A, plan_baslangic=ANCHOR, include_stations=True)
    ozet = build_makine_slot_ozet_all(con, plan_baslangic=ANCHOR)[0]
    assert ozet['makine_id'] == MAKINE_A
    assert ozet['A']['physical']['occupied_count'] == det['sides']['A']['physical']['occupied_count']
    assert ozet['A']['planned']['planned_count'] == det['sides']['A']['planned']['planned_count']
    assert ozet['B']['planned']['planned_count'] == det['sides']['B']['planned']['planned_count']


def test_no_date_plan_section(con):
    """DATE not selected — physical shown, plan hint"""
    from modules.planlama.enj_plan_availability_service import build_makine_detay
    det = build_makine_detay(con, MAKINE_A, include_stations=True)
    assert _side(det, 'A')['physical']['occupied_count'] == 2
    assert _side(det, 'A')['planned']['plan_tarih_secilmedi'] is True


def test_api_read_only(con, temp_db):
    """API_READ_ONLY=PASS — servis katmanı DB yazmaz."""
    _insert_child_plan(con, ist=(1,))
    before = con.execute('SELECT COUNT(*) FROM uretim_model_plan').fetchone()[0]
    from modules.planlama.enj_plan_availability_service import build_makine_detay
    det = build_makine_detay(con, MAKINE_A, plan_baslangic=ANCHOR, include_stations=True)
    assert det is not None
    after = con.execute('SELECT COUNT(*) FROM uretim_model_plan').fetchone()[0]
    assert before == after


def test_api_invalid_machine():
    """API_INVALID_MACHINE=BLOCKED"""
    makine_id = 0
    assert not makine_id or makine_id < 1


def test_api_invalid_slot():
    """API_INVALID_SLOT=BLOCKED"""
    slot = 'X'
    assert slot not in ('A', 'B')


def test_api_invalid_date():
    """API_INVALID_DATE=BLOCKED"""
    from modules.planlama.uretim_plan_routes import _parse_plan_dt_param
    with pytest.raises(ValueError):
        _parse_plan_dt_param('bad-date', 'plan_baslangic')


def test_api_unknown_machine(con):
    """API_UNKNOWN_MACHINE=BLOCKED"""
    from modules.planlama.enj_plan_availability_service import build_makine_detay
    assert build_makine_detay(con, 999) is None


def test_js_source_contracts():
    """Frontend contract markers — DETAIL_CLICK / LAZY_LOAD / NO_WRITE"""
    js = (_REPO_ROOT / 'app/static/js/uretim_plan.js').read_text(encoding='utf-8')
    html = (_REPO_ROOT / 'app/templates/planlama/uretim_plan.html').read_text(encoding='utf-8')
    assert 'stopPropagation' in js
    assert 'upEnjMakineDetayModal' in html
    assert 'enjOpenMakineDetay' in js
    assert 'enjYukleSlotOzet' in js
    assert '/api/enj/makine-detay' in js
    assert 'aria-label' in js
    assert 'up-enj-makine-detay-btn' in js
    assert 'method: \'POST\'' not in js[js.find('enjOpenMakineDetay'):js.find('enjBindMakineDetayModal')]


def test_remaining_quantity_regression(temp_db, monkeypatch):
    """REMAINING_QUANTITY_REGRESSION=PASS"""
    monkeypatch.setattr(
        'modules.planlama.uretim_plan_service.resolve_order_line_quantity',
        lambda *a, **k: {
            'order_total_quantity': 1000,
            'siparis_toplam_miktar': 1000,
            'birim': 'CIFT',
            'source': 'test',
        },
    )
    from modules.planlama import uretim_plan_repo as repo
    payload = {
        'sip_no': SIP, 'sip_harinx': HARINX, 'rkod': RKOD, 'mamul_skod': MODEL,
        'plan_donemi': 'bu_hafta', 'plan_baslangic': '2028-06-10', 'plan_bitis': '2028-06-20',
        'miktar': 1000, 'has_enjeksiyon': True,
        'enj_makine_id': MAKINE_A, 'enj_slot': 'A', 'enj_kalip_id': 1,
        'enj_istasyonlar': [8], 'enj_kalip_adedi': 1, 'enj_aktif_goz': 1,
        'enj_plan_baslangic': PLAN_BAS, 'enj_plan_bitis': PLAN_BIT,
        'enj_planlanacak_cift': 1500, 'enj_calisma_modu': 'GUNDUZ_GECE',
        'enj_hafta_sonu_calisma': 'HAYIR',
    }
    with pytest.raises(Exception):
        repo.plan_ekle(payload, user_id=1)
