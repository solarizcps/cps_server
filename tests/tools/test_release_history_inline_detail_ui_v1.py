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


def test_t15_record_count_73(service_mod):
    records, _ = service_mod.load_release_records(ROOT)
    assert len(records) == 73


def test_t16_module_count_12(service_mod):
    ctx = service_mod.build_page_context(ROOT)
    assert ctx["summary"]["total_modules"] == 12


def test_t17_validator_pass():
    proc = subprocess.run([sys.executable, str(VALIDATOR)], cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "records_checked=73" in proc.stdout


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


def test_t19_false_lock_metadata_has_approval():
    toml_paths = sorted(path for path in _FALSE_LOCK_PHASE_FILES if path.endswith(".toml"))
    assert len(toml_paths) == 10
    for rel in toml_paths:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert 'approved_by = "Adem Terzi"' in text
        assert "locked_rules_approval = true" in text


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


def test_label_p3_rules_heading(service_mod):
    ctx = service_mod.build_page_context(
        ROOT,
        detail_module="planlama.atp",
        detail_phase="ATP_GPS_GEOFENCE_P3",
    )
    panel = ctx["module_selected_rules"]["planlama.atp"]
    assert panel["heading"] == "Test Edilen Kurallar"
    assert panel["phase_code"] == "ATP_GPS_GEOFENCE_P3"
    assert "Geofence olayları doğrulanmış koordinatlarda işlenir." in panel["rules"]


def test_label_u1_rules_heading(service_mod):
    ctx = service_mod.build_page_context(
        ROOT,
        detail_module="planlama.atp",
        detail_phase="ATP_U1_ROUTE_ORDER_POLICY",
    )
    panel = ctx["module_selected_rules"]["planlama.atp"]
    assert panel["heading"] == "Kilitli Kurallar"
    assert "Tamamlanmış görevler taşınamaz." in panel["rules"]


def test_label_no_staged_when_production_not_staged(service_mod, monkeypatch):
    monkeypatch.setattr(service_mod, "_has_staged_production_files", lambda _base=None: False)
    records, _ = service_mod.load_release_records(ROOT)
    modules = service_mod.aggregate_modules(records, service_mod.load_deployment_state(ROOT))
    cps = next(item for item in modules if item.module == "cps.release.history")
    assert "staged" not in cps.push_status_label.lower()


def test_label_atp_push_uncommitted(service_mod, monkeypatch):
    monkeypatch.setattr(service_mod, "_has_staged_production_files", lambda _base=None: False)
    records, _ = service_mod.load_release_records(ROOT)
    modules = service_mod.aggregate_modules(records, service_mod.load_deployment_state(ROOT))
    atp = next(item for item in modules if item.module == "planlama.atp")
    assert atp.push_status_label == "Commit bekliyor · Push yapılmadı"


def test_label_p3_dom_rules_heading(route_db_isolation, service_mod):
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions={"*"}, superadmin=True):
        resp = client.get("/yonetim/surum-gecmisi?modul=planlama.atp&faz=ATP_GPS_GEOFENCE_P3")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    chunk = body.split('id="rh-detail-planlama-atp"')[1].split("rh-history-panel")[0]
    assert "Test Edilen Kurallar" in chunk
    assert "Geofence olayları doğrulanmış koordinatlarda işlenir." in chunk
    assert "Ziyaret state machine sırası korunur." in chunk
    assert "Kilitli Kurallar" not in chunk


def test_label_u1_dom_rules_heading(route_db_isolation, service_mod):
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions={"*"}, superadmin=True):
        resp = client.get("/yonetim/surum-gecmisi?modul=planlama.atp&faz=ATP_U1_ROUTE_ORDER_POLICY")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Kilitli Kurallar" in body
    assert "Tamamlanmış görevler taşınamaz." in body


def test_label_aps_counters_unchanged(service_mod, monkeypatch):
    monkeypatch.setattr(service_mod, "_has_staged_production_files", lambda _base=None: False)
    ctx = service_mod.build_page_context(ROOT)
    aps = next(item for item in ctx["modules"] if item.module == "planlama.aps")
    assert aps.last_completed_title == "APS master UI genel plan entegrasyonu tamamlandı."
    assert aps.current_work == "P5.8 anchor zoom + Z2G timeline genişletmesi"
    assert ctx["summary"]["commit_pending_records"] == 18


def _atp_rules_chunk(body: str) -> str:
    return body.split('id="rh-detail-planlama-atp"')[1].split("rh-history-panel")[0]


def _phase_rules_index(service_mod, monkeypatch=None):
    records, _ = service_mod.load_release_records(ROOT)
    ctx = service_mod.build_page_context(ROOT)
    return ctx["module_phase_rules"], ctx


def test_dom_sync_t1_embedded_json_and_apply_js(template_text):
    assert 'id="rh-phase-rules-data"' in template_text
    assert "module_phase_rules | tojson" in template_text
    assert "applyPhaseRules" in template_text
    assert "textContent" in template_text
    assert "data-rh-rules-heading" in template_text
    assert "data-rh-rules-list" in template_text
    assert "data-rh-issues-list" in template_text
    assert "data-rh-push-status" in template_text
    assert "data-rh-deploy-status" in template_text
    assert "data-rh-commit-box" in template_text


def test_dom_sync_t2_p3_index_has_two_rules(service_mod):
    index, _ = _phase_rules_index(service_mod)
    p3 = index["planlama.atp"]["ATP_GPS_GEOFENCE_P3"]
    assert p3["heading"] == "Test Edilen Kurallar"
    assert len(p3["rules"]) == 2
    assert "Geofence olayları doğrulanmış koordinatlarda işlenir." in p3["rules"]
    assert "Ziyaret state machine sırası korunur." in p3["rules"]
    assert p3["status"] == "TEST"
    assert p3["source_type"] == "verified_uncommitted"


def test_dom_sync_t3_u1_index_heading(service_mod):
    index, _ = _phase_rules_index(service_mod)
    u1 = index["planlama.atp"]["ATP_U1_ROUTE_ORDER_POLICY"]
    assert u1["heading"] == "Kilitli Kurallar"
    assert "Tamamlanmış görevler taşınamaz." in u1["rules"]
    assert u1["status"] == "KILITLI"


def test_dom_sync_t4_p3_to_u1_no_cross_rules(service_mod):
    index, _ = _phase_rules_index(service_mod)
    p3_rules = set(index["planlama.atp"]["ATP_GPS_GEOFENCE_P3"]["rules"])
    u1_rules = set(index["planlama.atp"]["ATP_U1_ROUTE_ORDER_POLICY"]["rules"])
    assert not p3_rules.intersection(u1_rules)


def test_dom_sync_t5_u1_to_p3_no_cross_rules(service_mod):
    index, _ = _phase_rules_index(service_mod)
    p3 = index["planlama.atp"]["ATP_GPS_GEOFENCE_P3"]
    u1 = index["planlama.atp"]["ATP_U1_ROUTE_ORDER_POLICY"]
    assert "Tamamlanmış görevler taşınamaz." not in p3["rules"]
    assert "Geofence olayları doğrulanmış koordinatlarda işlenir." not in u1["rules"]


def test_dom_sync_t6_nexgen_etiket_heading(service_mod):
    index, ctx = _phase_rules_index(service_mod)
    etiket = next(item for item in ctx["modules"] if item.module == "nexgen.etiket")
    panel = index["nexgen.etiket"][etiket.latest_phase]
    assert panel["heading"] == "Test Edilen Kurallar"
    assert panel["status"] == "TEST"
    assert panel["source_type"] == "verified_uncommitted"


def test_dom_sync_t7_popstate_applies_rules(template_text):
    chunk = template_text[template_text.index("addEventListener('popstate'"):]
    assert "applyPhaseRules" in chunk or "openBlock" in chunk
    assert "applyPhaseRules(block, moduleId, phase)" in template_text


def test_dom_sync_t8_direct_url_server_render(route_db_isolation):
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions={"*"}, superadmin=True):
        resp = client.get("/yonetim/surum-gecmisi?modul=planlama.atp&faz=ATP_GPS_GEOFENCE_P3")
    body = resp.get_data(as_text=True)
    chunk = _atp_rules_chunk(body)
    assert "Test Edilen Kurallar" in chunk
    assert "Geofence olayları doğrulanmış koordinatlarda işlenir." in chunk


def test_dom_sync_t9_xss_payload_text_safe(service_mod):
    from dataclasses import replace

    records, _ = service_mod.load_release_records(ROOT)
    base = next(r for r in records if r.module == "planlama.atp")
    evil = replace(
        base,
        locked_rules=["<img src=x onerror=alert(1)>"],
        known_issues=["<script>alert(1)</script>"],
    )
    panel = service_mod.build_record_phase_panel(evil, {}, service_mod.GitEvidenceCache(ROOT))
    assert panel["rules"][0] == "<img src=x onerror=alert(1)>"
    js_chunk = TEMPLATE.read_text(encoding="utf-8")
    js_part = js_chunk[js_chunk.index("applyPhaseRules"):]
    assert "innerHTML" not in js_part
    assert "textContent" in js_part
    assert "module_phase_rules | tojson" in js_chunk


def test_dom_sync_t10_no_innerhtml_for_rules(template_text):
    js_start = template_text.index('id="rh-phase-rules-data"')
    js_chunk = template_text[js_start: js_start + 4500]
    assert "innerHTML" not in js_chunk
    assert "applyPhaseRules" in js_chunk
    assert "createElement('li')" in js_chunk


def test_dom_sync_t11_accordion_behaviour_preserved(template_text):
    assert "history.pushState" in template_text
    assert "scrollRestore" in template_text
    assert "closeAll" in template_text
    assert "resetPhaseRules" in template_text


def test_dom_sync_t12_page_json_only_visible_modules(service_mod):
    index, ctx = _phase_rules_index(service_mod)
    visible = {item.module for item in ctx["modules"]}
    assert set(index.keys()).issubset(visible)
    assert "planlama.atp" in index
    assert len(index["planlama.atp"]) >= 2


def test_dom_sync_unauthorized_no_json(route_db_isolation):
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions={"yonetim:can_view"}, superadmin=False):
        resp = client.get("/yonetim/surum-gecmisi")
    body = resp.get_data(as_text=True)
    assert 'id="rh-phase-rules-data"' not in body
    assert "applyPhaseRules" not in body


def test_dom_sync_paramsless_page_has_p3_in_json(route_db_isolation):
    import json
    import re

    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions={"*"}, superadmin=True):
        resp = client.get("/yonetim/surum-gecmisi")
    body = resp.get_data(as_text=True)
    match = re.search(
        r'<script type="application/json" id="rh-phase-rules-data">(.+?)</script>',
        body,
        re.S,
    )
    assert match
    data = json.loads(match.group(1))
    p3 = data["planlama.atp"]["ATP_GPS_GEOFENCE_P3"]
    assert p3["heading"] == "Test Edilen Kurallar"
    assert "Geofence olayları doğrulanmış koordinatlarda işlenir." in p3["rules"]


def _mock_git_cache(service_mod, *, head: str, origin: str, head_set: set[str], origin_set: set[str]):
    class _Cache:
        base = ROOT

        def head(self):
            return head

        def origin_main(self):
            return origin

        def resolve_sha(self, value: str):
            text = (value or "").strip().lower()
            return text

        def _reachable_commits(self, ref: str):
            ref = (ref or "").lower()
            if ref == head:
                return set(head_set)
            if ref == origin:
                return set(origin_set)
            return set()

        def is_ancestor(self, ancestor: str, descendant: str):
            anc = self.resolve_sha(ancestor)
            desc = self.resolve_sha(descendant)
            reachable = self._reachable_commits(desc)
            if reachable is None:
                return None
            return anc in reachable

    return _Cache()


def test_state_t1_stale_manifest_does_not_override(service_mod, monkeypatch):
    stale = {"local_head": "2b0d77d9d3425592bd399569b8d54dce59fa63eb", "modules": {"cps.release.history": {"push_status": "COMMIT_PENDING"}}}
    monkeypatch.setattr(service_mod, "_is_deploy_state_stale", lambda _ds, _git: True)
    monkeypatch.setattr(service_mod, "_has_staged_production_files", lambda _base=None: False)
    records, _ = service_mod.load_release_records(ROOT)
    rec = next(r for r in records if r.phase_code == "CPS_RELEASE_HISTORY_ACCORDION_PHASE_DOM_SYNC_FIX")
    git = _mock_git_cache(
        service_mod,
        head="453f98ed5c8461fd8c51bed485e05628bf8b98dd",
        origin="8952aaa0000000000000000000000000000000000",
        head_set={"453f98ed5c8461fd8c51bed485e05628bf8b98dd"},
        origin_set=set(),
    )
    lifecycle = service_mod.resolve_record_lifecycle_state(rec, stale, git)
    assert lifecycle == service_mod.LIFECYCLE_LOCAL_NOT_PUSHED


def test_state_t2_t4_cps_selected_phase_labels(service_mod, monkeypatch):
    monkeypatch.setattr(service_mod, "_has_staged_production_files", lambda _base=None: False)
    git = _mock_git_cache(
        service_mod,
        head="453f98ed5c8461fd8c51bed485e05628bf8b98dd",
        origin="8952aaa0000000000000000000000000000000000",
        head_set={"453f98ed5c8461fd8c51bed485e05628bf8b98dd"},
        origin_set=set(),
    )
    monkeypatch.setattr(service_mod, "GitEvidenceCache", lambda base=ROOT: git)
    ctx = service_mod.build_page_context(
        ROOT,
        detail_module="cps.release.history",
        detail_phase="CPS_RELEASE_HISTORY_ACCORDION_PHASE_DOM_SYNC_FIX",
    )
    panel = ctx["module_phase_rules"]["cps.release.history"]["CPS_RELEASE_HISTORY_ACCORDION_PHASE_DOM_SYNC_FIX"]
    assert panel["lifecycle"] == service_mod.LIFECYCLE_LOCAL_NOT_PUSHED
    assert panel["push_status_label"] == "Yerelde commitli · Push yapılmadı"
    assert panel["deploy_status_label"] == "Deploy edilmedi"
    assert panel["commit_short"] == "453f98ed"


def test_state_t5_push_labels_never_contain_deploy_word(service_mod):
    violations = [label for label in service_mod.PUSH_STATUS_LABELS.values() if "Deploy" in label or "deploy" in label]
    assert violations == []


def test_state_t6_verified_uncommitted_commit_pending(service_mod, monkeypatch):
    monkeypatch.setattr(service_mod, "_has_staged_production_files", lambda _base=None: False)
    git = _mock_git_cache(service_mod, head="a", origin="b", head_set={"a"}, origin_set={"b"})
    monkeypatch.setattr(service_mod, "GitEvidenceCache", lambda base=ROOT: git)
    ctx = service_mod.build_page_context(ROOT, detail_module="planlama.atp", detail_phase="ATP_GPS_GEOFENCE_P3")
    panel = ctx["module_phase_rules"]["planlama.atp"]["ATP_GPS_GEOFENCE_P3"]
    assert panel["push_status_label"] == "Commit bekliyor · Push yapılmadı"
    assert panel["deploy_status_label"] == "Deploy edilmedi"


def test_state_t7_pushed_not_deployed(service_mod):
    git = _mock_git_cache(
        service_mod,
        head="abc1234567890123456789012345678901234567890",
        origin="abc1234567890123456789012345678901234567890",
        head_set={"abc1234567890123456789012345678901234567890", "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"},
        origin_set={"abc1234567890123456789012345678901234567890", "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"},
    )
    records, _ = service_mod.load_release_records(ROOT)
    rec = next(r for r in records if r.module == "planlama.atp" and r.phase_code == "ATP_U1_ROUTE_ORDER_POLICY")
    lifecycle = service_mod.resolve_record_lifecycle_state(rec, {}, git)
    if git.is_ancestor(rec.commit_sha.lower(), git.origin_main()):
        assert lifecycle == service_mod.LIFECYCLE_PUSHED_NOT_DEPLOYED


def test_state_t8_deployed_verified_requires_manifest(service_mod):
    git = _mock_git_cache(
        service_mod,
        head="453f98ed5c8461fd8c51bed485e05628bf8b98dd",
        origin="8952aaa0000000000000000000000000000000000",
        head_set={"453f98ed5c8461fd8c51bed485e05628bf8b98dd"},
        origin_set=set(),
    )
    records, _ = service_mod.load_release_records(ROOT)
    rec = next(r for r in records if r.phase_code == "CPS_RELEASE_HISTORY_ACCORDION_PHASE_DOM_SYNC_FIX")
    deploy_state = {
        "manifest_check": {
            "status": "DEPLOYED_VERIFIED",
            "sha_resolved": "453f98ed5c8461fd8c51bed485e05628bf8b98dd",
            "smoke_pass": True,
        }
    }
    lifecycle = service_mod.resolve_record_lifecycle_state(rec, deploy_state, git)
    assert lifecycle == service_mod.LIFECYCLE_DEPLOYED_VERIFIED


def test_state_t9_off_branch_needs_review(service_mod):
    git = _mock_git_cache(
        service_mod,
        head="1111111111111111111111111111111111111111",
        origin="2222222222222222222222222222222222222222",
        head_set={"1111111111111111111111111111111111111111"},
        origin_set={"2222222222222222222222222222222222222222"},
    )
    records, _ = service_mod.load_release_records(ROOT)
    rec = next(r for r in records if r.phase_code == "CPS_RELEASE_HISTORY_ACCORDION_PHASE_DOM_SYNC_FIX")
    lifecycle = service_mod.resolve_record_lifecycle_state(rec, {}, git)
    assert lifecycle == service_mod.LIFECYCLE_NEEDS_REVIEW


def test_state_t10_inline_selected_phase_dom(route_db_isolation, service_mod, monkeypatch):
    monkeypatch.setattr(service_mod, "_has_staged_production_files", lambda _base=None: False)
    git = _mock_git_cache(
        service_mod,
        head="453f98ed5c8461fd8c51bed485e05628bf8b98dd",
        origin="8952aaa0000000000000000000000000000000000",
        head_set={"453f98ed5c8461fd8c51bed485e05628bf8b98dd"},
        origin_set=set(),
    )
    monkeypatch.setattr(service_mod, "GitEvidenceCache", lambda base=ROOT: git)
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions={"*"}, superadmin=True):
        resp = client.get(
            "/yonetim/surum-gecmisi?modul=cps.release.history&faz=CPS_RELEASE_HISTORY_ACCORDION_PHASE_DOM_SYNC_FIX"
        )
    body = resp.get_data(as_text=True)
    chunk = body.split('id="rh-detail-cps-release-history"')[1].split("rh-history-panel")[0]
    assert "453f98ed" in chunk
    assert "Yerelde commitli · Push yapılmadı" in chunk
    assert "Deploy edilmedi" in chunk
    assert "Deploy bilinmiyor" not in chunk


def test_state_t11_module_row_aggregate_preserved(service_mod, monkeypatch):
    monkeypatch.setattr(service_mod, "_has_staged_production_files", lambda _base=None: False)
    ctx = service_mod.build_page_context(ROOT)
    cps = next(m for m in ctx["modules"] if m.module == "cps.release.history")
    assert cps.local_version == "v1.3.1"
    assert cps.commit_short == "453f98ed"


def test_state_t12_p3_rules_dom_sync_preserved(route_db_isolation, service_mod):
    client = _make_client()
    _admin_session(client)
    with _route_ctx(permissions={"*"}, superadmin=True):
        resp = client.get("/yonetim/surum-gecmisi?modul=planlama.atp&faz=ATP_GPS_GEOFENCE_P3")
    body = resp.get_data(as_text=True)
    chunk = _atp_rules_chunk(body)
    assert "Test Edilen Kurallar" in chunk
    assert "Geofence olayları doğrulanmış koordinatlarda işlenir." in chunk


def test_state_t14_record_module_counts(service_mod):
    records, skipped = service_mod.load_release_records(ROOT)
    ctx = service_mod.build_page_context(ROOT)
    assert len(records) == 73
    assert skipped == 0
    assert ctx["summary"]["total_modules"] == 12
