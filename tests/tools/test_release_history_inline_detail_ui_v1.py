# -*- coding: utf-8 -*-
"""Inline detail accordion UI tests — CPS_RELEASE_HISTORY_INLINE_DETAIL_UI_V1."""
from __future__ import annotations

import importlib
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
VALIDATOR = ROOT / "tools" / "validate_release_history.py"
TEMPLATE = ROOT / "app" / "templates" / "yonetim" / "surum_gecmisi.html"

if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


@pytest.fixture(scope="module")
def service_mod():
    import services.release_history_service as mod
    return importlib.reload(mod)


@pytest.fixture(scope="module")
def template_text():
    return TEMPLATE.read_text(encoding="utf-8")



def _make_client():
    import app as flask_app
    flask_app.app.config["TESTING"] = True
    return flask_app.app.test_client()


def _admin_session(client):
    with client.session_transaction() as sess:
        sess["kullanici"] = {
            "Id": 1,
            "KullaniciAdi": "admin",
            "AdSoyad": "Admin",
            "Tip": "sistem",
            "RolId": 1,
            "Aktif": 1,
            "AuthVersion": 1,
        }


@contextmanager
def _route_ctx(*, permissions: set[str] | None = None, superadmin: bool = False):
    from unittest.mock import patch

    perms = set(permissions if permissions is not None else {"*"})

    def _yetki_var(kod, action="can_view"):
        if "*" in perms:
            return True
        return (kod + ":" + action) in perms

    def _kullanici_yetkileri(_user_dict):
        return set(perms)

    patches = [
        patch("app.sistem_session_gecerli_mi", return_value=True),
        patch("app.kullanici_yetkileri", side_effect=_kullanici_yetkileri),
        patch("modules.auth.kullanici_yetkileri", side_effect=_kullanici_yetkileri),
        patch("modules.auth.yetki_var", side_effect=_yetki_var),
        patch("modules.auth.is_superadmin", return_value=superadmin),
        patch("modules.yonetim.routes.yetki_var", side_effect=_yetki_var),
        patch("modules.yonetim.routes.is_superadmin", return_value=superadmin),
    ]
    for item in patches:
        item.start()
    try:
        yield
    finally:
        for item in patches:
            item.stop()


def test_t1_page_http_200(route_db_isolation):
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions={"*"}, superadmin=True):
        resp = client.get("/yonetim/surum-gecmisi")
    assert resp.status_code == 200


def test_t2_unauthorized_guard(route_db_isolation):
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions=set(), superadmin=False):
        resp = client.get("/yonetim/surum-gecmisi")
    assert resp.status_code == 403


def test_t3_seven_column_headers(template_text):
    idx = template_text.index('class="rh-row hdr"')
    chunk = template_text[idx: idx + 320]
    cols = re.findall(r"<div>([^<]+)</div>", chunk)
    assert len(cols) == 7
    assert cols[0] == "Modül"
    assert cols[6] == "Detay"


def test_t4_header_row_same_grid(template_text):
    assert "rh-tablo-head" in template_text
    assert template_text.count("grid-template-columns:minmax(130px,1.35fr)") >= 1
    assert "rh-module-block" in template_text
    assert "rh-inline-detail" in template_text


def test_t5_clamp_ellipsis_css(template_text):
    assert "rh-clamp2" in template_text
    assert "-webkit-line-clamp:2" in template_text


def test_t6_inline_detail_follows_row(template_text):
    assert re.search(
        r"rh-module-row.*?rh-inline-detail",
        template_text,
        re.S,
    )


def test_t7_single_open_js(template_text):
    assert "closeAll" in template_text
    assert "is-open" in template_text
    assert "Kapat" in template_text


def test_t8_no_bottom_detail_block(template_text):
    assert 'id="rh-detail"' not in template_text
    assert template_text.count("rh-inline-detail") >= 1


def test_t9_scroll_restore_logic(template_text):
    assert "scrollRestore" in template_text
    assert "behavior: 'smooth'" in template_text


def test_t10_module_timelines_in_context(service_mod):
    ctx = service_mod.build_page_context(ROOT)
    assert "module_timelines" in ctx
    assert isinstance(ctx["module_timelines"], dict)


def test_t11_history_toggle_per_module(template_text):
    assert "data-rh-history" in template_text
    assert "Tüm sürüm geçmişini aç" in template_text


def test_t12_xss_autoescape_template(template_text):
    assert "{{ item.module_label }}" in template_text
    assert "| safe" not in template_text


def test_t13_unauthorized_no_inline_detail(route_db_isolation):
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions={"yonetim:can_view"}, superadmin=False):
        resp = client.get("/yonetim/surum-gecmisi")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'class="rh-inline-detail"' not in body
    assert "data-rh-toggle=" not in body
    assert "Kilitli kurallar" not in body


def test_t14_deep_link_module_in_body(route_db_isolation):
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions={"*"}, superadmin=True):
        resp = client.get("/yonetim/surum-gecmisi?modul=nexgen.mo")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'data-module="nexgen.mo"' in body
    assert "openModule" in body or "openBlock" in body


def test_t15_record_count_70(service_mod):
    records, _ = service_mod.load_release_records(ROOT)
    assert len(records) == 70


def test_t16_module_count_12(service_mod):
    ctx = service_mod.build_page_context(ROOT)
    assert ctx["summary"]["total_modules"] == 12


def test_t17_validator_pass():
    proc = subprocess.run([sys.executable, str(VALIDATOR)], cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "records_checked=70" in proc.stdout


def test_t18_regression_ui_v2_subset():
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/tools/test_release_history_ui_v2.py", "-q", "--tb=no"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


_FALSE_LOCK_PHASE_FILES = frozenset({
    "changes/fragments/planlama.atp.ATP_GPS_GEOFENCE_P3.release",
    "changes/fragments/planlama.atp.ATP_GPS_HISTORY_TRAIL_V1.release",
    "changes/fragments/planlama.atp.ATP_MAP_LAYER_STABILITY_V1.release",
    "changes/fragments/planlama.atp.ATP_U0_PLAN_OPS_HARDENING.release",
    "changes/fragments/planlama.atp.ATP_U0_WHATSAPP_ROUTE_NOTIFY.release",
    "changes/fragments/planlama.atp.ATP_U2A_U2B_ACIL_INSERT_LOCK.release",
    "changes/fragments/planlama.atp.ATP_U3B_MANUAL_REORDER_POLICY.release",
    "changes/fragments/planlama.atp.ATP_U3C_MANUAL_REORDER_API.release",
    "changes/fragments/server.BACKFILL_SERVER_B5163074.release",
    "changes/fragments/test.infra.BACKFILL_TEST_INFRA_C9FAEA9B.release",
    "changes/records/planlama.atp/ATP_GPS_GEOFENCE_P3.toml",
    "changes/records/planlama.atp/ATP_GPS_HISTORY_TRAIL_V1.toml",
    "changes/records/planlama.atp/ATP_MAP_LAYER_STABILITY_V1.toml",
    "changes/records/planlama.atp/ATP_U0_PLAN_OPS_HARDENING.toml",
    "changes/records/planlama.atp/ATP_U0_WHATSAPP_ROUTE_NOTIFY.toml",
    "changes/records/planlama.atp/ATP_U2A_U2B_ACIL_INSERT_LOCK.toml",
    "changes/records/planlama.atp/ATP_U3B_MANUAL_REORDER_POLICY.toml",
    "changes/records/planlama.atp/ATP_U3C_MANUAL_REORDER_API.toml",
    "changes/records/server/BACKFILL_SERVER_B5163074.toml",
    "changes/records/test.infra/BACKFILL_TEST_INFRA_C9FAEA9B.toml",
})


def test_t19_false_lock_metadata_scope_only():
    unstaged = subprocess.run(
        ["git", "diff", "--name-only", "changes/"], cwd=str(ROOT), capture_output=True, text=True
    )
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "changes/"], cwd=str(ROOT), capture_output=True, text=True
    )
    changed = {
        line.strip().replace("\\", "/")
        for proc in (unstaged, staged)
        for line in proc.stdout.splitlines()
        if line.strip()
    }
    assert changed == _FALSE_LOCK_PHASE_FILES, changed - _FALSE_LOCK_PHASE_FILES


def test_t20_page_has_timeline_in_inline(route_db_isolation):
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions={"*"}, superadmin=True):
        resp = client.get("/yonetim/surum-gecmisi")
    body = resp.get_data(as_text=True)
    assert "Sürüm Zaman Çizelgesi" in body


def test_t21_detail_toggle_data_attr(route_db_isolation):
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions={"*"}, superadmin=True):
        resp = client.get("/yonetim/surum-gecmisi")
    body = resp.get_data(as_text=True)
    assert "data-rh-toggle=" in body
    assert "rh-detail-btn" in body


def test_v11_url_pushstate_and_popstate(template_text):
    assert "history.pushState" in template_text
    assert "addEventListener('popstate'" in template_text
    assert "buildUrl" in template_text
    assert "parseUrlState" in template_text


def test_v11_sticky_header_below_nav(template_text):
    assert "rh-tablo-body" in template_text
    assert "overflow-y:auto" in template_text.replace(" ", "")
    assert "z-index:20" in template_text.replace(" ", "")
    assert "position:sticky" in template_text.replace(" ", "")


def test_v11_module_default_phase_attr(template_text):
    assert "data-default-phase" in template_text


def test_v11_close_clears_url_params(template_text):
    assert "p.delete('modul')" in template_text
    assert "p.delete('faz')" in template_text


def test_v12_compact_summary_strip(template_text):
    assert "rh-summary" in template_text
    assert "rh-summary-primary" in template_text
    assert "rh-summary-secondary" in template_text
    assert "rh-kpi-grid" not in template_text


def test_v12_flex_page_layout(template_text):
    css = template_text.replace(" ", "")
    assert ".rh-page{display:flex" in css or ".rh-page{display:flex;" in css.replace("\n", "")
    assert "flex:1" in css
    assert "min-height:0" in css
    assert "100vh-470px" not in css
    assert "100vh-420px" not in css


def test_v12_single_row_filter(template_text):
    assert "rh-filtre-actions" in template_text
    assert "grid-template-columns:minmax(160px,2fr)" in template_text.replace(" ", "")
    assert "Modül ara" in template_text
