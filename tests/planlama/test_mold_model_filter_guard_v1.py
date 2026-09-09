# -*- coding: utf-8 -*-
"""MOLD_MODEL_FILTER_GUARD_V1 — Kalıp model filtresi ve save guard testleri.

Kapsam:
  - resolve_canonical_mamul_skod: Korgun canonical resolver
  - /api/enj/kaliplar endpoint: canonical Korgun doğrulaması
  - create/update save guard (_validate_enj_kalip_model_match): canonical + mod ayrımı
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
_SERVICE = _REPO / 'app/modules/planlama/uretim_plan_service.py'
_ROUTES  = _REPO / 'app/modules/planlama/uretim_plan_routes.py'
_REPO_PY = _REPO / 'app/modules/planlama/uretim_plan_repo.py'
_JS      = _REPO / 'app/static/js/uretim_plan.js'


@pytest.fixture(scope='module')
def service_src():
    return _SERVICE.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def routes_src():
    return _ROUTES.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def repo_src():
    return _REPO_PY.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def js():
    return _JS.read_text(encoding='utf-8')


# ── SERVICE: resolve_canonical_mamul_skod ────────────────────────────────────

def test_canonical_resolver_function_exists(service_src):
    """resolve_canonical_mamul_skod service'te tanımlı."""
    assert 'def resolve_canonical_mamul_skod' in service_src


def test_canonical_resolver_error_class(service_src):
    """CanonicalResolveError sınıfı tanımlı."""
    assert 'class CanonicalResolveError' in service_src


def test_canonical_resolver_compares_client_value(service_src):
    """Resolver istemci değerini Korgun canonical ile karşılaştırıyor."""
    idx = service_src.index('def resolve_canonical_mamul_skod')
    block = service_src[idx:idx+1500]
    assert 'manipülasyon' in block or 'uyuşmuyor' in block


def test_canonical_resolver_fail_closed(service_src):
    """Korgun erişilemez → CanonicalResolveError (fail-closed)."""
    idx = service_src.index('def resolve_canonical_mamul_skod')
    block = service_src[idx:idx+1500]
    assert 'CanonicalResolveError' in block
    assert 'bağlantısı kurulamadı' in block or 'başarısız' in block


def test_canonical_resolver_unit_correct_model():
    """Korgun doğru model döndürürse PASS."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_service import resolve_canonical_mamul_skod

        mock_con = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = ('BRM-9000',)
        mock_con.cursor.return_value = mock_cur

        with patch('modules.common.korgun._baglan', return_value=mock_con):
            result = resolve_canonical_mamul_skod(33857, 83766, 'BRM-9000', 0)
        assert result.strip().upper() == 'BRM-9000'
    finally:
        sys.path.pop(0)


def test_canonical_resolver_unit_client_tamper_blocked():
    """İstemci farklı model gönderirse CanonicalResolveError."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_service import (
            resolve_canonical_mamul_skod, CanonicalResolveError,
        )
        mock_con = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = ('BRM-9000',)   # Korgun gerçek: BRM-9000
        mock_con.cursor.return_value = mock_cur

        with patch('modules.common.korgun._baglan', return_value=mock_con):
            with pytest.raises(CanonicalResolveError, match='uyuşmuyor'):
                resolve_canonical_mamul_skod(33857, 83766, 'CRP-8100', 0)  # istemci yanlış
    finally:
        sys.path.pop(0)


def test_canonical_resolver_unit_korgun_unavailable():
    """Korgun erişilemez → CanonicalResolveError."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_service import (
            resolve_canonical_mamul_skod, CanonicalResolveError,
        )
        with patch('modules.common.korgun._baglan', side_effect=Exception('timeout')):
            with pytest.raises(CanonicalResolveError):
                resolve_canonical_mamul_skod(33857, 83766, 'BRM-9000', 0)
    finally:
        sys.path.pop(0)


def test_canonical_resolver_unit_row_not_found():
    """Korgun'da satır yok → CanonicalResolveError."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_service import (
            resolve_canonical_mamul_skod, CanonicalResolveError,
        )
        mock_con = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        mock_con.cursor.return_value = mock_cur

        with patch('modules.common.korgun._baglan', return_value=mock_con):
            with pytest.raises(CanonicalResolveError, match='bulunamadı'):
                resolve_canonical_mamul_skod(99999, 99999, 'BRM-9000', 0)
    finally:
        sys.path.pop(0)


# ── ROUTE STATIK KONTRAT ──────────────────────────────────────────────────────

def test_endpoint_uses_canonical_resolver(routes_src):
    """Endpoint resolve_canonical_mamul_skod kullanıyor."""
    assert 'resolve_canonical_mamul_skod' in routes_src
    assert 'CanonicalResolveError' in routes_src


def test_endpoint_requires_sip_no(routes_src):
    """Endpoint sip_no, sip_harinx, mamul_skod zorunlu."""
    assert "sip_no" in routes_src
    assert "sip_harinx" in routes_src
    assert "mamul_skod" in routes_src


def test_endpoint_400_on_missing_params(routes_src):
    """Eksik parametre → 400 response."""
    assert "400" in routes_src
    assert "sip_no, sip_harinx ve mamul_skod zorunludur" in routes_src


def test_endpoint_503_on_canonical_unavailable(routes_src):
    """Canonical erişilemez → 503 fail-closed."""
    assert "503" in routes_src


def test_endpoint_409_on_canonical_mismatch(routes_src):
    """Canonical uyuşmazlık → 409."""
    assert "409" in routes_src
    assert "uyuşmuyor" in routes_src or "manipülasyon" in routes_src


def test_endpoint_no_all_molds_fallback(routes_src):
    """Endpoint filtre yokken tüm kalıpları döndürmüyor."""
    assert "WHERE aktif = 1\n            ORDER BY kalip_kod" not in routes_src


def test_endpoint_model_filter_in_sql(routes_src):
    """SQL'de TRIM/UPPER model_kod filtresi var."""
    assert "TRIM(UPPER(model_kod)) = ?" in routes_src


def test_endpoint_empty_result_safe_message(routes_src):
    """Boş sonuçta güvenli mesaj var, fallback yok."""
    assert "Bu model için tanımlı liste kalıbı bulunamadı" in routes_src
    assert "Manuel Kalıp seçeneğini kullanabilirsiniz" in routes_src


# ── REPO SAVE GUARD STATIK KONTRAT ───────────────────────────────────────────

def test_save_guard_function_exists(repo_src):
    """_validate_enj_kalip_model_match repo'da tanımlı."""
    assert 'def _validate_enj_kalip_model_match' in repo_src


def test_canonical_guard_helper_exists(repo_src):
    """_resolve_canonical_skod_for_guard yardımcısı tanımlı."""
    assert 'def _resolve_canonical_skod_for_guard' in repo_src


def test_save_guard_explicit_manuel_mode(repo_src):
    """Manuel mod açıkça kalip_mode=manuel ile ayrılıyor."""
    idx = repo_src.index('def _validate_enj_kalip_model_match')
    block = repo_src[idx:idx+2500]
    assert "kalip_mode" in block
    assert "'manuel'" in block


def test_save_guard_list_mode_requires_id(repo_src):
    """Liste modunda kalip_id zorunlu."""
    idx = repo_src.index('def _validate_enj_kalip_model_match')
    block = repo_src[idx:idx+2500]
    assert 'enj_kalip_id zorunludur' in block


def test_save_guard_manual_mode_blocks_list_id(repo_src):
    """Manuel modda liste kalıp ID'si reddediliyor."""
    idx = repo_src.index('def _validate_enj_kalip_model_match')
    block = repo_src[idx:idx+2500]
    assert 'bypass' in block or 'gönderilemez' in block


def test_save_guard_skips_unchanged_kalip_on_update(repo_src):
    """Update'te kalıp aynıysa geriye uyumluluk."""
    idx = repo_src.index('def _validate_enj_kalip_model_match')
    block = repo_src[idx:idx+2500]
    assert 'mevcut_kid' in block or 'mevcut.get' in block


def test_save_guard_raises_on_mismatch(repo_src):
    """Model uyuşmazlığında ValueError fırlatılıyor."""
    idx = repo_src.index('def _validate_enj_kalip_model_match')
    block = repo_src[idx:idx+4000]
    assert 'uyumlu değil' in block


def test_save_guard_uses_canonical_resolver(repo_src):
    """Guard, canonical resolver çağırıyor (istemci değil)."""
    idx = repo_src.index('def _validate_enj_kalip_model_match')
    block = repo_src[idx:idx+5000]
    assert '_resolve_canonical_skod_for_guard' in block


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
    """Save guard INSERT'ten önce."""
    idx = repo_src.index('def plan_ekle')
    block = repo_src[idx:idx+3000]
    guard_pos  = block.find('_validate_enj_kalip_model_match')
    insert_pos = block.find('INSERT INTO uretim_model_plan')
    assert guard_pos  != -1, "MOLD GUARD plan_ekle'de bulunamadı"
    assert insert_pos != -1, "INSERT plan_ekle'de bulunamadı"
    assert guard_pos < insert_pos, "MOLD GUARD INSERT'ten sonra çağrılıyor!"


def test_update_order_model_immutable(repo_src):
    """Update'te sipariş/model kimliği değiştirilemez."""
    assert 'siparis_veya_model değiştirilemez' in repo_src or \
           'Yeni plan oluşturun' in repo_src or \
           'değiştirilemez' in repo_src


# ── UNIT TESTS: GUARD + MOCKED KORGUN ────────────────────────────────────────

def _make_fixture_db() -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE enj_kalip (
        id INTEGER PRIMARY KEY, kalip_kod TEXT, model_kod TEXT, aktif INTEGER DEFAULT 1
    )""")
    con.execute("INSERT INTO enj_kalip VALUES (42, 'TR-21M2', 'BRM-9000', 1)")
    con.execute("INSERT INTO enj_kalip VALUES (2,  'TR-21B1-A', 'CRP-8100', 1)")
    con.execute("INSERT INTO enj_kalip VALUES (99, 'TR-OLD', 'BRM-9000', 0)")
    con.commit()
    return con


def _mock_korgun(skod='BRM-9000'):
    """Korgun bağlantısını canonical skod döndürecek şekilde mock'la."""
    mock_con = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (skod,)
    mock_con.cursor.return_value = mock_cur
    return mock_con


def test_guard_blocks_wrong_model():
    """Yanlış model kalıbı (Korgun canonical mismatch) → ValueError."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        payload = {
            'has_enjeksiyon': True,
            'kalip_mode': 'liste',
            'enj_kalip_id': 2,          # CRP-8100 kalıbı
            'mamul_skod': 'BRM-9000',
            'sip_no': 33857, 'sip_harinx': 83766, 'rkod': 0,
        }
        with patch('modules.common.korgun._baglan', return_value=_mock_korgun('BRM-9000')):
            with pytest.raises(ValueError, match='uyumlu değil'):
                _validate_enj_kalip_model_match(con, payload, mevcut=None)
    finally:
        sys.path.pop(0)


def test_guard_passes_correct_model():
    """Doğru model kalıbı → hata yok."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        payload = {
            'has_enjeksiyon': True,
            'kalip_mode': 'liste',
            'enj_kalip_id': 42,         # BRM-9000 kalıbı
            'mamul_skod': 'BRM-9000',
            'sip_no': 33857, 'sip_harinx': 83766, 'rkod': 0,
        }
        with patch('modules.common.korgun._baglan', return_value=_mock_korgun('BRM-9000')):
            _validate_enj_kalip_model_match(con, payload, mevcut=None)  # hata yok
    finally:
        sys.path.pop(0)


def test_guard_client_tamper_blocked():
    """İstemci mamul_skod=CRP-8100 gönderip Korgun BRM-9000 döndürürse → BLOCKED."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        payload = {
            'has_enjeksiyon': True,
            'kalip_mode': 'liste',
            'enj_kalip_id': 2,          # CRP-8100 kalıbı
            'mamul_skod': 'CRP-8100',   # istemci manipüle etti
            'sip_no': 33857, 'sip_harinx': 83766, 'rkod': 0,
        }
        # Korgun gerçek: BRM-9000 → canonical uyuşmazlık → ValueError
        with patch('modules.common.korgun._baglan', return_value=_mock_korgun('BRM-9000')):
            with pytest.raises(ValueError):
                _validate_enj_kalip_model_match(con, payload, mevcut=None)
    finally:
        sys.path.pop(0)


def test_guard_passes_no_enjeksiyon():
    """has_enjeksiyon False → guard tamamen atlanır."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        payload = {'has_enjeksiyon': False, 'enj_kalip_id': 2, 'mamul_skod': 'BRM-9000'}
        _validate_enj_kalip_model_match(con, payload, mevcut=None)  # hata yok
    finally:
        sys.path.pop(0)


def test_guard_list_mode_requires_id():
    """Liste modunda kalip_id yoksa → ValueError."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        payload = {
            'has_enjeksiyon': True,
            'kalip_mode': 'liste',
            # enj_kalip_id yok
            'mamul_skod': 'BRM-9000',
            'sip_no': 33857, 'sip_harinx': 83766,
        }
        with pytest.raises(ValueError, match='enj_kalip_id zorunludur'):
            _validate_enj_kalip_model_match(con, payload, mevcut=None)
    finally:
        sys.path.pop(0)


def test_guard_manuel_mode_with_id_blocked():
    """Manuel modda kalip_id gönderilirse → ValueError."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        payload = {
            'has_enjeksiyon': True,
            'kalip_mode': 'manuel',
            'enj_kalip_id': 42,         # liste ID — bypass girişimi
            'enj_kalip_kod': 'TR-21M2',
            'mamul_skod': 'BRM-9000',
        }
        with pytest.raises(ValueError, match='bypass'):
            _validate_enj_kalip_model_match(con, payload, mevcut=None)
    finally:
        sys.path.pop(0)


def test_guard_manuel_mode_no_kod_blocked():
    """Manuel modda kalıp kodu boşsa → ValueError."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        payload = {
            'has_enjeksiyon': True,
            'kalip_mode': 'manuel',
            'enj_kalip_kod': '',        # boş
            'mamul_skod': 'BRM-9000',
        }
        with pytest.raises(ValueError, match='boş olamaz'):
            _validate_enj_kalip_model_match(con, payload, mevcut=None)
    finally:
        sys.path.pop(0)


def test_guard_manuel_mode_valid_pass():
    """Manuel mod açıkça seçilmiş, geçerli kalıp kodu → hata yok."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        payload = {
            'has_enjeksiyon': True,
            'kalip_mode': 'manuel',
            'enj_kalip_kod': 'OZEL-KALIP-X',
            'mamul_skod': 'BRM-9000',
        }
        _validate_enj_kalip_model_match(con, payload, mevcut=None)  # hata yok
    finally:
        sys.path.pop(0)


def test_guard_skips_unchanged_kalip_on_update():
    """Update'te kalıp değişmiyorsa legacy uyumluluk korunur."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        # Mevcut: CRP-8100 kalıbı; payload da aynı → atlanır
        payload = {
            'has_enjeksiyon': True,
            'kalip_mode': 'liste',
            'enj_kalip_id': 2,
            'mamul_skod': 'BRM-9000',
            'sip_no': 33857, 'sip_harinx': 83766,
        }
        mevcut = {'enj_kalip_id': 2, 'sip_no': 33857, 'sip_harinx': 83766,
                  'mamul_skod': 'BRM-9000', 'rkod': 0}
        _validate_enj_kalip_model_match(con, payload, mevcut=mevcut)  # hata yok
    finally:
        sys.path.pop(0)


def test_guard_blocks_new_wrong_kalip_on_update():
    """Update'te yeni yanlış model kalıbı → ValueError."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        payload = {
            'has_enjeksiyon': True,
            'kalip_mode': 'liste',
            'enj_kalip_id': 2,          # CRP-8100 kalıbı
            'mamul_skod': 'BRM-9000',
            'sip_no': 33857, 'sip_harinx': 83766,
        }
        mevcut = {'enj_kalip_id': 42,    # farklı mevcut kalıp
                  'sip_no': 33857, 'sip_harinx': 83766,
                  'mamul_skod': 'BRM-9000', 'rkod': 0}
        with patch('modules.common.korgun._baglan', return_value=_mock_korgun('BRM-9000')):
            with pytest.raises(ValueError, match='uyumlu değil'):
                _validate_enj_kalip_model_match(con, payload, mevcut=mevcut)
    finally:
        sys.path.pop(0)


def test_guard_update_blocks_model_change():
    """Update'te sipariş modeli değiştirilemez."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        payload = {
            'has_enjeksiyon': True,
            'kalip_mode': 'liste',
            'enj_kalip_id': 42,
            'mamul_skod': 'CRP-8100',   # farklı model — manipülasyon
            'sip_no': 33857, 'sip_harinx': 83766,
        }
        mevcut = {'enj_kalip_id': 42,
                  'sip_no': 33857, 'sip_harinx': 83766,
                  'mamul_skod': 'BRM-9000', 'rkod': 0}   # DB'deki canonical model
        with pytest.raises(ValueError, match='değiştirilemez'):
            _validate_enj_kalip_model_match(con, payload, mevcut=mevcut)
    finally:
        sys.path.pop(0)


def test_guard_raises_inactive_mold():
    """Pasif kalıp → ValueError."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        payload = {
            'has_enjeksiyon': True,
            'kalip_mode': 'liste',
            'enj_kalip_id': 99,
            'mamul_skod': 'BRM-9000',
            'sip_no': 33857, 'sip_harinx': 83766,
        }
        with patch('modules.common.korgun._baglan', return_value=_mock_korgun('BRM-9000')):
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
        payload = {
            'has_enjeksiyon': True,
            'kalip_mode': 'liste',
            'enj_kalip_id': 42,
            'mamul_skod': 'brm-9000',
            'sip_no': 33857, 'sip_harinx': 83766,
        }
        with patch('modules.common.korgun._baglan', return_value=_mock_korgun('BRM-9000')):
            _validate_enj_kalip_model_match(con, payload, mevcut=None)  # hata yok
    finally:
        sys.path.pop(0)


def test_guard_canonical_unavailable_fail_closed():
    """Korgun erişilemez → fail-closed ValueError (kayıt yapılmıyor)."""
    sys.path.insert(0, str(_REPO / 'app'))
    try:
        from modules.planlama.uretim_plan_repo import _validate_enj_kalip_model_match
        con = _make_fixture_db()
        payload = {
            'has_enjeksiyon': True,
            'kalip_mode': 'liste',
            'enj_kalip_id': 42,
            'mamul_skod': 'BRM-9000',
            'sip_no': 33857, 'sip_harinx': 83766,
        }
        with patch('modules.common.korgun._baglan', side_effect=Exception('timeout')):
            with pytest.raises(ValueError):
                _validate_enj_kalip_model_match(con, payload, mevcut=None)
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
    """JS'de hata durumunda sessiz tüm kalıplar yüklenmiyor."""
    idx = js.index('function enjYukleKaliplar')
    block = js[idx:idx+1000]
    assert 'return' in block


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
    assert 'sipAsorti' not in block, "sipAsorti hâlâ kalıp label'ına ekleniyor"


# ── Regression: mevcut test_mold_duplicate_display_js ────────────────────────

def test_mold_kayit_n_preserved(js):
    """Aynı kodlu farklı kayıtlar hâlâ 'Kayıt N' ile ayrılıyor."""
    assert 'Kayıt ' in js
