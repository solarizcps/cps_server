# -*- coding: utf-8 -*-
"""Kalıp seri master — CRUD guard testleri."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / 'app') not in sys.path:
    sys.path.insert(0, str(_REPO / 'app'))

from modules.planlama.enj_kalip_seri_service import (  # noqa: E402
    KalipSeriError,
    add_uye,
    create_seri,
    read_series_for_model,
    update_uye,
)


@pytest.fixture
def db():
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE enj_kalip (
            id INTEGER PRIMARY KEY, kalip_kod TEXT, kalip_tipi TEXT,
            model_kod TEXT, model_ad TEXT, asorti TEXT,
            kalip_basi_cift INTEGER, varsayilan_bagli_kalip INTEGER,
            kapasite_cift INTEGER, aktif INTEGER DEFAULT 1,
            aktif_goz_sayisi INTEGER, kapasite_onayli INTEGER DEFAULT 0
        );
        CREATE TABLE enj_kalip_seri (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seri_kod TEXT NOT NULL COLLATE NOCASE,
            seri_ad TEXT, model_kod TEXT NOT NULL, model_ad TEXT,
            aciklama TEXT, aktif INTEGER NOT NULL DEFAULT 1,
            created_at TEXT, updated_at TEXT, created_by INTEGER, updated_by INTEGER,
            UNIQUE(seri_kod)
        );
        CREATE TABLE enj_kalip_seri_uye (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seri_id INTEGER NOT NULL, kalip_id INTEGER NOT NULL,
            uye_rolu TEXT NOT NULL CHECK (uye_rolu IN ('GOVDE','ATKI','DIGER')),
            beden_numara TEXT, sira_no INTEGER,
            varsayilan_fiziksel_adet INTEGER, aktif INTEGER NOT NULL DEFAULT 1,
            created_at TEXT, updated_at TEXT, created_by INTEGER, updated_by INTEGER,
            UNIQUE (seri_id, kalip_id),
            CHECK (varsayilan_fiziksel_adet IS NULL OR varsayilan_fiziksel_adet > 0)
        );
        INSERT INTO enj_kalip (id,kalip_kod,kalip_tipi,model_kod,kalip_basi_cift,aktif,aktif_goz_sayisi,kapasite_onayli)
        VALUES (1,'TR-21M2','GOVDE','BRM-9000',1,1,1,0),
               (2,'TR-21B1','GOVDE','CRP-8100',2,1,2,0),
               (3,'TR-21B1-A','ATKI','CRP-8100',2,0,2,0);
    """)
    yield con
    con.close()


def test_create_seri_and_member_ok(db):
    seri = create_seri(db, {'seri_kod': 'BRM-S1', 'model_kod': 'BRM-9000'}, user_id=1)
    uye = add_uye(db, seri['id'], {'kalip_id': 1, 'uye_rolu': 'GOVDE', 'sira_no': 1}, user_id=1)
    assert uye['kalip_kod'] == 'TR-21M2'
    rows = read_series_for_model(db, 'BRM-9000')
    assert len(rows) == 1
    assert rows[0]['uyeler'][0]['kalip_kod'] == 'TR-21M2'


def test_duplicate_seri_kod_blocked(db):
    create_seri(db, {'seri_kod': 'DUP-1', 'model_kod': 'BRM-9000'})
    with pytest.raises(KalipSeriError, match='zaten mevcut'):
        create_seri(db, {'seri_kod': 'dup-1', 'model_kod': 'BRM-9000'})


def test_wrong_model_member_blocked(db):
    seri = create_seri(db, {'seri_kod': 'BRM-S2', 'model_kod': 'BRM-9000'})
    with pytest.raises(KalipSeriError, match='uyuşmuyor'):
        add_uye(db, seri['id'], {'kalip_id': 2, 'uye_rolu': 'GOVDE'})


def test_inactive_mold_member_blocked(db):
    seri = create_seri(db, {'seri_kod': 'CRP-S1', 'model_kod': 'CRP-8100'})
    with pytest.raises(KalipSeriError, match='Pasif kalıp'):
        add_uye(db, seri['id'], {'kalip_id': 3, 'uye_rolu': 'ATKI'})


def test_duplicate_member_blocked(db):
    seri = create_seri(db, {'seri_kod': 'BRM-S3', 'model_kod': 'BRM-9000'})
    add_uye(db, seri['id'], {'kalip_id': 1, 'uye_rolu': 'GOVDE'})
    with pytest.raises(KalipSeriError, match='zaten seriye ekli'):
        add_uye(db, seri['id'], {'kalip_id': 1, 'uye_rolu': 'ATKI'})


def test_invalid_physical_count_blocked(db):
    seri = create_seri(db, {'seri_kod': 'BRM-S4', 'model_kod': 'BRM-9000'})
    with pytest.raises(KalipSeriError, match='pozitif'):
        add_uye(db, seri['id'], {'kalip_id': 1, 'uye_rolu': 'GOVDE', 'varsayilan_fiziksel_adet': 0})


def test_deactivate_member(db):
    seri = create_seri(db, {'seri_kod': 'BRM-S5', 'model_kod': 'BRM-9000'})
    uye = add_uye(db, seri['id'], {'kalip_id': 1, 'uye_rolu': 'GOVDE'})
    updated = update_uye(db, uye['id'], {'aktif': 0})
    assert updated['aktif'] == 0
    active = read_series_for_model(db, 'BRM-9000')
    assert active[0]['uyeler'] == []


def test_read_empty_for_unknown_model(db):
    assert read_series_for_model(db, 'NO-SUCH-MODEL') == []


def test_read_only_alias_and_template_guard():
    html = (_REPO / 'app/templates/yonetim/kalip_yonetimi.html').read_text(encoding='utf-8')
    routes = (_REPO / 'app/modules/planlama/routes.py').read_text(encoding='utf-8')
    assert 'kalip_read_only' in html
    assert 'ky-read-only' in html
    assert 'ky-write-only' in html
    assert 'kalip_read_only=True' in routes
    assert '/api/enj/kalip-serileri' in (
        _REPO / 'app/modules/planlama/uretim_plan_routes.py'
    ).read_text(encoding='utf-8')
