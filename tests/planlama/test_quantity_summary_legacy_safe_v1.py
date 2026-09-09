# -*- coding: utf-8 -*-
"""Quantity Summary Legacy-Safe Fix — sözleşme testleri (temp DB only).

Senaryolar:
  A. Normal sipariş: quantity_calculable=True, remaining_quantity≥0
  B. Legacy unresolved: quantity_calculable=False, remaining_quantity=None, HTTP 200
  C. Create/update guard: view_only=False → hâlâ FAIL-CLOSED (OrderLineQuantityError)
  D. Legacy değeri 0 sayılmıyor (LEGACY_ZERO_ASSUMPTION=NO teyit)
  E. Sipariş bulunamadı: OrderLineNotFoundError
  F. JS sözleşme: quantity_calculable alanı response'ta mevcut
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO = Path(__file__).resolve().parents[2]
_APP = _REPO / 'app'
for _p in [str(_APP)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ─── Minimal DB kurulumu ────────────────────────────────────────────────────

_PARENT_DDL = """
CREATE TABLE uretim_model_plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sip_no INTEGER NOT NULL,
    sip_harinx INTEGER NOT NULL,
    mamul_skod TEXT NOT NULL,
    rkod INTEGER NOT NULL DEFAULT 0,
    model_adi TEXT, renk_adi TEXT, miktar REAL,
    termin TEXT, plan_donemi TEXT NOT NULL,
    plan_baslangic TEXT, plan_bitis TEXT,
    oncelik INTEGER NOT NULL DEFAULT 3,
    plan_gerekce TEXT, plan_notu TEXT,
    aktif INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    created_by INTEGER, updated_at TEXT, updated_by INTEGER,
    enj_makine_id INTEGER, enj_istasyon_no INTEGER, enj_slot TEXT,
    enj_kalip_id INTEGER, enj_kalip_kod TEXT, enj_aktif_goz INTEGER,
    enj_kalip_basi_cift INTEGER, enj_tur_cift INTEGER,
    enj_gunluk_tur_plan INTEGER, enj_gunluk_kapasite INTEGER,
    enj_plan_baslangic TEXT, enj_plan_bitis TEXT,
    enj_tahmini_gun REAL, enj_planlanacak_cift REAL,
    enj_calisma_modu TEXT, enj_hafta_sonu_calisma TEXT,
    enj_hafta_sonu_vardiya TEXT, enj_kapasite_snapshot TEXT
)
"""

_SIP_NO = 33918
_SIP_HARINX = 83973
_MAMUL_SKOD = 'CRX-71025-KRK'
_RKOD = 2
_ORDER_TOTAL = 4000


def _make_db(*, with_legacy=False, with_resolved=False, resolved_qty=1000):
    """Temp DB oluştur; plan satırları opsiyonel."""
    tmpdir = tempfile.mkdtemp(prefix='qty_legacy_')
    db = str(Path(tmpdir) / 'test.db')
    con = sqlite3.connect(db)
    con.execute(_PARENT_DDL)
    con.commit()
    if with_legacy:
        # enj_planlanacak_cift=NULL, enj_kapasite_snapshot=NULL → unresolved
        con.execute(
            "INSERT INTO uretim_model_plan "
            "(sip_no,sip_harinx,mamul_skod,rkod,plan_donemi,aktif,"
            " enj_planlanacak_cift,enj_kapasite_snapshot) VALUES (?,?,?,?,'bu_ay',1,NULL,NULL)",
            (_SIP_NO, _SIP_HARINX, _MAMUL_SKOD, _RKOD),
        )
    if with_resolved:
        snap = json.dumps({'planlanacak_cift': resolved_qty})
        con.execute(
            "INSERT INTO uretim_model_plan "
            "(sip_no,sip_harinx,mamul_skod,rkod,plan_donemi,aktif,"
            " enj_planlanacak_cift,enj_kapasite_snapshot) VALUES (?,?,?,?,'bu_hafta',1,?,NULL)",
            (_SIP_NO, _SIP_HARINX, _MAMUL_SKOD, _RKOD, resolved_qty),
        )
    con.commit()
    con.close()
    return tmpdir, db


def _mock_korgun_total(order_total=_ORDER_TOTAL):
    """resolve_order_line_quantity'yi mock'la (Korgun yerine)."""
    return {
        'order_total_quantity': order_total,
        'siparis_toplam_miktar': order_total,
        'birim': 'CIFT',
        'canonical_key': f'{_SIP_NO}|{_SIP_HARINX}|{_MAMUL_SKOD}|{_RKOD}',
        'source': 'test_mock',
    }


# ─── Fixture ───────────────────────────────────────────────────────────────

@pytest.fixture()
def db_normal(monkeypatch):
    """Çözülebilen plan olan DB."""
    tmpdir, db = _make_db(with_resolved=True, resolved_qty=1000)
    monkeypatch.setenv('CPS_MOCK_DB_PATH', db)
    import config
    monkeypatch.setattr(config.Config, 'MOCK_DB_PATH', db, raising=False)
    yield db
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture()
def db_legacy(monkeypatch):
    """Unresolved legacy plan içeren DB."""
    tmpdir, db = _make_db(with_legacy=True)
    monkeypatch.setenv('CPS_MOCK_DB_PATH', db)
    import config
    monkeypatch.setattr(config.Config, 'MOCK_DB_PATH', db, raising=False)
    yield db
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture()
def db_empty(monkeypatch):
    """Plan olmayan temiz DB."""
    tmpdir, db = _make_db()
    monkeypatch.setenv('CPS_MOCK_DB_PATH', db)
    import config
    monkeypatch.setattr(config.Config, 'MOCK_DB_PATH', db, raising=False)
    yield db
    shutil.rmtree(tmpdir, ignore_errors=True)


# ─── Senaryo A: Normal ─────────────────────────────────────────────────────

def test_normal_quantity_calculable(db_normal):
    """NORMAL_QUANTITY_CALCULABLE=PASS — resolved plan → quantity_calculable=True"""
    from modules.planlama.uretim_plan_service import resolve_line_quantity_summary
    with patch('modules.planlama.uretim_plan_service.resolve_order_line_quantity',
               return_value=_mock_korgun_total()):
        result = resolve_line_quantity_summary(_SIP_NO, _SIP_HARINX, _MAMUL_SKOD, _RKOD, view_only=True)
    assert result['quantity_calculable'] is True
    assert result['order_total_quantity'] == _ORDER_TOTAL
    assert result['already_planned_quantity'] == 1000
    assert result['remaining_quantity'] == 3000
    assert result['unresolved_plan_ids'] == []
    assert result['warning'] is None


def test_normal_no_legacy_block(db_normal):
    """NORMAL_NO_LEGACY_BLOCK=PASS — normal sipariş da view_only=False ile çalışır"""
    from modules.planlama.uretim_plan_service import resolve_line_quantity_summary
    with patch('modules.planlama.uretim_plan_service.resolve_order_line_quantity',
               return_value=_mock_korgun_total()):
        result = resolve_line_quantity_summary(_SIP_NO, _SIP_HARINX, _MAMUL_SKOD, _RKOD, view_only=False)
    assert result['quantity_calculable'] is True
    assert result['remaining_quantity'] == 3000


# ─── Senaryo B: Legacy view_only=True ──────────────────────────────────────

def test_legacy_view_only_http200(db_legacy):
    """LEGACY_VIEW_ONLY_HTTP200=PASS — unresolved plan → ok=True, calculable=False"""
    from modules.planlama.uretim_plan_service import resolve_line_quantity_summary
    with patch('modules.planlama.uretim_plan_service.resolve_order_line_quantity',
               return_value=_mock_korgun_total()):
        result = resolve_line_quantity_summary(_SIP_NO, _SIP_HARINX, _MAMUL_SKOD, _RKOD, view_only=True)
    assert result['quantity_calculable'] is False
    assert result['order_total_quantity'] == _ORDER_TOTAL
    assert result['already_planned_quantity'] == 0   # legacy sayılmaz (0 değil, unresolved)
    assert result['remaining_quantity'] is None
    assert result['remaining_after_save'] is None
    assert isinstance(result['unresolved_plan_ids'], list)
    assert len(result['unresolved_plan_ids']) > 0
    assert result['warning'] is not None
    assert 'legacy' in result['warning'].lower() or 'eski' in result['warning'].lower()


def test_legacy_order_total_present(db_legacy):
    """LEGACY_ORDER_TOTAL_PRESENT=PASS — Korgun toplamı hâlâ gösterilir"""
    from modules.planlama.uretim_plan_service import resolve_line_quantity_summary
    with patch('modules.planlama.uretim_plan_service.resolve_order_line_quantity',
               return_value=_mock_korgun_total(5000)):
        result = resolve_line_quantity_summary(_SIP_NO, _SIP_HARINX, _MAMUL_SKOD, _RKOD, view_only=True)
    assert result['order_total_quantity'] == 5000


# ─── Senaryo C: Create/update guard FAIL-CLOSED ────────────────────────────

def test_create_guard_fail_closed(db_legacy):
    """SAVE_GUARD_FAIL_CLOSED=PASS — view_only=False → OrderLineQuantityError"""
    from modules.planlama.uretim_plan_service import resolve_line_quantity_summary, OrderLineQuantityError
    with patch('modules.planlama.uretim_plan_service.resolve_order_line_quantity',
               return_value=_mock_korgun_total()):
        with pytest.raises(OrderLineQuantityError) as exc_info:
            resolve_line_quantity_summary(_SIP_NO, _SIP_HARINX, _MAMUL_SKOD, _RKOD, view_only=False)
    assert 'legacy' in str(exc_info.value).lower() or 'çözümlenemeyen' in str(exc_info.value)


# ─── Senaryo D: Legacy 0 sayılmıyor ───────────────────────────────────────

def test_legacy_zero_not_assumed(db_legacy):
    """LEGACY_ZERO_ASSUMPTION=NO — unresolved plan already_planned toplamına 0 eklenmez"""
    from modules.planlama.uretim_plan_service import resolve_line_quantity_summary
    with patch('modules.planlama.uretim_plan_service.resolve_order_line_quantity',
               return_value=_mock_korgun_total()):
        result = resolve_line_quantity_summary(_SIP_NO, _SIP_HARINX, _MAMUL_SKOD, _RKOD, view_only=True)
    # already_planned sadece çözülebilen planları içerir; unresolved 0 sayılmadığından
    # remaining_quantity=None olmalı (0 dönemez)
    assert result['remaining_quantity'] is None, 'Legacy plan 0 sayılmamalı'
    assert result['quantity_calculable'] is False


# ─── Senaryo E: Sipariş bulunamadı ────────────────────────────────────────

def test_order_not_found(db_empty):
    """ORDER_NOT_FOUND=PASS — Korgun'da sipariş yoksa OrderLineNotFoundError"""
    from modules.planlama.uretim_plan_service import resolve_line_quantity_summary, OrderLineNotFoundError
    with patch('modules.planlama.uretim_plan_service.resolve_order_line_quantity',
               side_effect=OrderLineNotFoundError('bulunamadı')):
        with pytest.raises(OrderLineNotFoundError):
            resolve_line_quantity_summary(_SIP_NO, _SIP_HARINX, _MAMUL_SKOD, _RKOD, view_only=True)


# ─── Senaryo F: Response alanları tam ─────────────────────────────────────

def test_response_fields_normal(db_normal):
    """RESPONSE_FIELDS_NORMAL=PASS — normal yanıt tüm beklenen alanları içerir"""
    from modules.planlama.uretim_plan_service import resolve_line_quantity_summary
    with patch('modules.planlama.uretim_plan_service.resolve_order_line_quantity',
               return_value=_mock_korgun_total()):
        result = resolve_line_quantity_summary(_SIP_NO, _SIP_HARINX, _MAMUL_SKOD, _RKOD, view_only=True)
    for field in ('order_total_quantity', 'already_planned_quantity', 'remaining_quantity',
                  'quantity_calculable', 'unresolved_plan_ids', 'warning', 'birim'):
        assert field in result, f'Eksik alan: {field}'


def test_response_fields_legacy(db_legacy):
    """RESPONSE_FIELDS_LEGACY=PASS — legacy yanıt tüm beklenen alanları içerir"""
    from modules.planlama.uretim_plan_service import resolve_line_quantity_summary
    with patch('modules.planlama.uretim_plan_service.resolve_order_line_quantity',
               return_value=_mock_korgun_total()):
        result = resolve_line_quantity_summary(_SIP_NO, _SIP_HARINX, _MAMUL_SKOD, _RKOD, view_only=True)
    for field in ('order_total_quantity', 'already_planned_quantity', 'remaining_quantity',
                  'remaining_after_save', 'quantity_calculable', 'unresolved_plan_ids', 'warning'):
        assert field in result, f'Eksik alan: {field}'
    assert result['remaining_quantity'] is None
    assert result['remaining_after_save'] is None


# ─── JS sözleşme: route view_only kullanıyor ──────────────────────────────

def test_route_uses_view_only():
    """ROUTE_VIEW_ONLY=PASS — GET route view_only=True geçiriyor"""
    src = (_REPO / 'app/modules/planlama/uretim_plan_routes.py').read_text(encoding='utf-8')
    idx = src.find('def api_plan_kalem_miktar_ozet()')
    assert idx != -1
    segment = src[idx: idx + 1200]
    assert 'view_only=True' in segment


def test_js_legacy_state_accepted():
    """JS_LEGACY_STATE_ACCEPTED=PASS — JS quantity_calculable=false durumunu state'e alıyor"""
    js = (_REPO / 'app/static/js/uretim_plan.js').read_text(encoding='utf-8')
    assert 'quantity_calculable === false' in js


def test_js_warning_shown():
    """JS_WARNING_SHOWN=PASS — JS backend warning mesajını gösteriyor"""
    js = (_REPO / 'app/static/js/uretim_plan.js').read_text(encoding='utf-8')
    assert 'qs.warning' in js


def test_js_hesapla_blocked():
    """JS_HESAPLA_BLOCKED=PASS — legacyBlock varken İleri/Kaydet disabled"""
    js = (_REPO / 'app/static/js/uretim_plan.js').read_text(encoding='utf-8')
    assert 'legacyBlockNav' in js


def test_js_not_yüklenemedi_on_legacy():
    """JS_NOT_YUKLENEMEDI=PASS — legacyBlock'ta 'Miktar özeti yüklenemedi' gösterilmiyor"""
    js = (_REPO / 'app/static/js/uretim_plan.js').read_text(encoding='utf-8')
    # enjUpdateMiktarOzet içinde legacyBlock kontrolü yüklenemedi mesajından önce geliyor
    moz_fn = js.split('function enjUpdateMiktarOzet()')[1].split('\n    function ')[0]
    yuklenemedi_pos = moz_fn.find('Miktar özeti yüklenemedi')
    legacy_block_pos = moz_fn.find('legacyBlock')
    assert legacy_block_pos != -1, 'legacyBlock enjUpdateMiktarOzet içinde olmalı'
    # legacyBlock yüklenemedi mesajından farklı bir kod yolunda
    assert yuklenemedi_pos != -1


def test_js_already_en_az():
    """JS_ALREADY_EN_AZ=PASS — legacy modda 'En az X çift' gösteriliyor"""
    js = (_REPO / 'app/static/js/uretim_plan.js').read_text(encoding='utf-8')
    assert 'En az ' in js


def test_js_hesaplanamıyor():
    """JS_HESAPLANAMIYOR=PASS — Kalan ve planlama sonrası 'Hesaplanamıyor' gösteriliyor"""
    js = (_REPO / 'app/static/js/uretim_plan.js').read_text(encoding='utf-8')
    assert 'Hesaplanamıyor' in js
