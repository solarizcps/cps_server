# -*- coding: utf-8 -*-
"""MOLD_MODEL_FILTER_GUARD_V1 — Kalıp model filtresi ve save guard testleri.

Kapsam:
  - /api/enj/kaliplar endpoint parametre ve filtre doğruluğu
  - create/update save guard (_validate_enj_kalip_model_match)
  - Frontend JS: canonical params, stale temizlik, boş mesaj
  - Manuel mod regresyonu
"""
from __future__ import annotations
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_REPO = Path(__file__).resolve().parents[2]
_ROUTES = _REPO / 'app/modules/planlama/uretim_plan_routes.py'
_REPO_PY = _REPO / 'app/modules/planlama/uretim_plan_repo.py'
_JS = _REPO / 'app/static/js/uretim_plan.js'


@pytest.fixture(scope='module')
def routes_src():
    return _ROUTES.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def repo_src():
    return _REPO_PY.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def js():
    return _JS.read_text(encoding='utf-8')


# ── ROUTE STATIK KONTRAT ──────────────────────────────────────────────────────

def test_endpoint_requires_sip_no(routes_src):
    """Endpoint sip_no parametresini zorunlu tutuyor."""
    assert "sip_no" in routes_src
    assert "sip_harinx" in routes_src
    assert "mamul_skod" in routes_src


def test_endpoint_400_on_missing_params(routes_src):
    """Eksik parametre → 400 response."""
    assert "400" in routes_src
    assert "sip_no, sip_harinx ve mamul_skod zorunludur" in routes_src


def test_endpoint_no_all_molds_fallback(routes_src):
    """Endpoint filtre yokken tüm kalıpları döndürmüyor (eski SELECT * ... WHERE aktif=1 yok)."""
    # Eski saf sorgu:
    assert "WHERE aktif = 1\n            ORDER BY kalip_kod" not in routes_src


def test_endpoint_model_filter_in_sql(routes_src):
    """SQL'de TRIM/UPPER model_kod filtresi var."""
    assert "TRIM(UPPER(model_kod)) = ?" in routes_src


def test_endpoint_409_on_canonical_mismatch(routes_src):
    """Canonical uyuşmazlık → 409."""
    assert "409" in routes_src
    assert "uyuşmuyor" in routes_src


def test_endpoint_empty_result_safe_message(routes_src):
    """Boş sonuçta güvenli mesaj var, fallback yok."""
    assert "Bu model için tanımlı liste kalıbı bulunamadı" in routes_src
    assert "Manuel Kalıp seçeneğini kullanabilirsiniz" in routes_src


# ── REPO SAVE GUARD ───────────────────────────────────────────────────────────

def test_save_guard_function_exists(repo_src):
    """_validate_enj_kalip_model_match fonksiyonu repo'da tanımlı."""
    assert 'def _validate_enj_kalip_model_match' in repo_src


def test_save_guard_skips_no_kalip_id(repo_src):
    """kalip_id yoksa (manuel mod) guard atlanıyor."""
    idx = repo_src.index('def _validate_enj_kalip_model_match')
    block = repo_src[idx:idx+900]
    assert 'if not kalip_id' in block
    assert 'return' in block


def test_save_guard_skips_unchanged_kalip_on_update(repo_src):
    """Update'te kalıp aynıysa geriye uyumluluk için atlanıyor."""
    idx = repo_src.index('def _validate_enj_kalip_model_match')
    block = repo_src[idx:idx+1200]
    assert 'mevcut_kid' in block or 'mevcut.get' in block or 'mevcut is not None' in block


def test_save_guard_raises_on_mismatch(repo_src):
    """Model uyuşmazlığında ValueError fırlatılıyor."""
    idx = repo_src.index('def _validate_enj_kalip_model_match')
    block = repo_src[idx:idx+2000]
    assert 'uyumlu değil' in block


def test_save_guard_called_in_plan_ekle(repo_src):
    """plan_ekle içinde save guard çağrılıyor."""
    idx = repo_src.index('def plan_ekle')
    block = repo_src[idx:idx+2000]
    assert '_validate_enj_kalip_model_match' in block


def test_save_guard_called_in_plan_guncelle(repo_src):
    """plan_guncelle içinde save guard çağrılıyor."""
    idx = repo_src.index('def plan_guncelle')
    block = repo_src[idx:idx+2000]
    assert '_validate_enj_kalip_model_match' in block


def test_save_guard_validate_before_write(repo_src):
    """Save guard, INSERT/UPDATE'ten önce — mold guard satırı INSERT'ten önce."""
    idx = repo_src.index('def plan_ekle')
    block = repo_src[idx:idx+3000]
    guard_pos = block.find('_validate_enj_kalip_model_match')
    insert_pos = block.find('INSERT INTO uretim_model_plan')
    assert guard_pos != -1, "MOLD GUARD plan_ekle'de bulunamadı"
    assert insert_pos != -1, "INSERT plan_ekle'de bulunamadı"
    assert guard_pos < insert_pos, "MOLD GUARD INSERT'ten sonra çağrılıyor!"


# ── SAVE GUARD SQLITE UNIT TEST ───────────────────────────────────────────────

def _make_fixture_db() -> sqlite3.Connection:
    """In-memory SQLite ile minimal fixture DB."""
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE enj_kalip (
        id INTEGER PRIMARY KEY, kalip_kod TEXT, model_kod TEXT, aktif INTEGER DEFAULT 1
    )""")
    # BRM-9000 kalıbı
    con.execute("INSERT INTO enj_kalip VALUES (42, 'TR-21M2', 'BRM-9000', 1)")
    # CRP-8100 kalıbı — yanlış model
    con.execute("INSERT INTO enj_kalip VALUES (2, 'TR-21B1-A', 'CRP-8100', 1)")
    # Pasif kalıp
    con.execute("INSERT INTO enj_kalip VALUES (99, 'TR-OLD', 'BRM-9000', 0)")
    con.commit()
    return con


def test_guard_blocks_wrong_model(tmp_path):
    """Yanlış model kalıbı → ValueError."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        payload = {'enj_kalip_id': 2, 'mamul_skod': 'BRM-9000'}
        with pytest.raises(ValueError, match='uyumlu değil'):
            _validate_enj_kalip_model_match(con, payload, mevcut=None)
    finally:
        sys.path.pop(0)


def test_guard_passes_correct_model(tmp_path):
    """Doğru model kalıbı → ValueError yok."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        payload = {'enj_kalip_id': 42, 'mamul_skod': 'BRM-9000'}
        _validate_enj_kalip_model_match(con, payload, mevcut=None)  # hata yok
    finally:
        sys.path.pop(0)


def test_guard_passes_no_kalip_id():
    """kalip_id yoksa (manuel mod) → hata yok."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        payload = {'mamul_skod': 'BRM-9000'}  # kalip_id yok
        _validate_enj_kalip_model_match(con, payload, mevcut=None)
    finally:
        sys.path.pop(0)


def test_guard_skips_unchanged_kalip_on_update():
    """Update'te kalıp değişmiyorsa atlanır."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        # Mevcut kayıtta CRP-8100 kalıbı var (id=2); payload da aynıyı gönderiyor
        payload = {'enj_kalip_id': 2, 'mamul_skod': 'BRM-9000'}
        mevcut  = {'enj_kalip_id': 2}
        _validate_enj_kalip_model_match(con, payload, mevcut=mevcut)  # hata yok
    finally:
        sys.path.pop(0)


def test_guard_blocks_new_wrong_kalip_on_update():
    """Update'te yeni yanlış model kalıbı → ValueError."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        payload = {'enj_kalip_id': 2, 'mamul_skod': 'BRM-9000'}
        mevcut  = {'enj_kalip_id': 42}  # farklı mevcut kalıp
        with pytest.raises(ValueError, match='uyumlu değil'):
            _validate_enj_kalip_model_match(con, payload, mevcut=mevcut)
    finally:
        sys.path.pop(0)


def test_guard_raises_inactive_mold():
    """Pasif kalıp → ValueError."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        payload = {'enj_kalip_id': 99, 'mamul_skod': 'BRM-9000'}
        with pytest.raises(ValueError, match='pasif'):
            _validate_enj_kalip_model_match(con, payload, mevcut=None)
    finally:
        sys.path.pop(0)


def test_guard_normalize_case():
    """Model kodu UPPER normalize ile küçük harf de eşleşiyor."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        payload = {'enj_kalip_id': 42, 'mamul_skod': 'brm-9000'}  # küçük harf
        _validate_enj_kalip_model_match(con, payload, mevcut=None)  # hata yok
    finally:
        sys.path.pop(0)


# ── FRONTEND JS KONTRATı ─────────────────────────────────────────────────────

def test_js_canonical_params_sent(js):
    """enjYukleKaliplar canonical 4 parametreyi URLSearchParams ile gönderiyor."""
    idx = js.index('function enjYukleKaliplar')
    block = js[idx:idx+800]
    assert 'sip_no' in block
    assert 'sip_harinx' in block
    assert 'mamul_skod' in block
    assert 'rkod' in block
    assert 'URLSearchParams' in block


def test_js_no_all_molds_fallback(js):
    """JS'de kalip listesi yüklenemezse sessiz tüm kalıplar yüklenmiyor."""
    idx = js.index('function enjYukleKaliplar')
    block = js[idx:idx+1000]
    # Eski hata: d.ok false olduğunda da kaliplar listesi oluşturuluyordu
    assert 'return' in block  # hata durumunda erken çıkış var


def test_js_stale_list_cleaned(js):
    """_enjKalipListeTemizle fonksiyonu JS'de tanımlı."""
    assert 'function _enjKalipListeTemizle' in js


def test_js_temizle_called_in_reset(js):
    """enjReset içinde _enjKalipListeTemizle çağrılıyor."""
    idx = js.index('function enjReset')
    block = js[idx:idx+3000]
    assert '_enjKalipListeTemizle' in block


def test_js_empty_result_disabled_selector(js):
    """Boş kalıp listesinde selector disabled yapılıyor."""
    idx = js.index('function enjYukleKaliplar')
    block = js[idx:idx+1000]
    assert 'disabled' in block
    assert 'd.mesaj' in block


def test_js_no_sipAsorti_label_confusion(js):
    """sipAsorti label'ı kalıp filtreleme olarak kullanılmıyor (kaldırıldı)."""
    idx = js.index('function enjBuildKalipSelect')
    block = js[idx:idx+600]
    # sipAsorti her kalıba eklenmiyordu, artık tamamen kaldırıldı
    assert 'sipAsorti' not in block, "sipAsorti hâlâ kalıp label'ına ekleniyor"
