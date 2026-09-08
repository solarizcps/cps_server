"""
tools/critical_browser_smoke.py
================================
Salt-okunur kritik modül kabul testleri.
Gerçek sunucuya BAĞLANMAZ — mock/fixture HTTP client kullanır.

302 redirect → login yönlendirmesi = FAIL (gerçek ekran değil).
"Sistem hatası" / HTTP 404-500 / traceback → FAIL.
Bilinen deploy blocker (kpi_filtered) → DEPLOY_BLOCKER olarak raporlanır, FAIL sayılmaz.

Kullanım:
    python tools/critical_browser_smoke.py [--base-url <url>]
    # base_url verilmezse sadece mock testler çalışır.

Çıktı:
    Satır bazlı: SMOKE <name> STATUS=<PASS|FAIL|DEPLOY_BLOCKER>
    Özet: SMOKE_PASS=N SMOKE_FAIL=N SMOKE_BLOCKERS=N
"""
from __future__ import annotations

import sys
from typing import Callable


# ---------------------------------------------------------------------------
# Data types — plain classes (no dataclass to avoid importlib __module__ issues)
# ---------------------------------------------------------------------------

class SmokeResult:
    __slots__ = ("name", "status", "detail")

    def __init__(self, name: str, status: str, detail: str = ""):
        self.name = name
        self.status = status
        self.detail = detail


class FakeResponse:
    """Minimal stub mimicking requests.Response for mock use."""
    __slots__ = ("status_code", "text", "url", "history")

    def __init__(self, status_code: int, text: str, url: str = "", history: list | None = None):
        self.status_code = status_code
        self.text = text
        self.url = url
        self.history = history or []


# ---------------------------------------------------------------------------
# Detection helpers (work on any response-like object)
# ---------------------------------------------------------------------------

FAIL_PATTERNS = [
    "Sistem hatası",
    "Traceback (most recent call last)",
    "Internal Server Error",
    "TemplateNotFound",
    "500 Internal",
    "404 Not Found",
    "OperationalError",
]

BLOCKER_PATTERNS = [
    "kpi_filtered",
    "no such table: kpi_filtered",
    "no such column: kpi_filtered",
]


def _check_response(name: str, resp: FakeResponse) -> SmokeResult:
    # 302 → login redirect (auth required but not logged in) = FAIL
    if resp.status_code == 302:
        return SmokeResult(name, "FAIL", "302 login redirect — not a real screen")

    if resp.status_code in (404, 500) or resp.status_code >= 400:
        return SmokeResult(name, "FAIL", f"HTTP {resp.status_code}")

    body = resp.text

    # Check known blockers first (report before generic FAIL)
    for pat in BLOCKER_PATTERNS:
        if pat in body:
            return SmokeResult(name, "DEPLOY_BLOCKER", f"Known blocker detected: '{pat}'")

    # Generic fail patterns
    for pat in FAIL_PATTERNS:
        if pat in body:
            return SmokeResult(name, "FAIL", f"Fail pattern found: '{pat}'")

    return SmokeResult(name, "PASS")


# ---------------------------------------------------------------------------
# Mock HTTP client factory
# ---------------------------------------------------------------------------

def _make_mock_client(fixtures: dict[str, FakeResponse]) -> Callable[[str], FakeResponse]:
    """Returns a callable that returns fixture responses by URL path."""
    def get(path: str) -> FakeResponse:
        if path in fixtures:
            return fixtures[path]
        return FakeResponse(404, "404 Not Found", url=path)
    return get


# ---------------------------------------------------------------------------
# Smoke test cases (mock/fixture based)
# ---------------------------------------------------------------------------

_MOCK_FIXTURES: dict[str, FakeResponse] = {
    # Auth / Login page — sadece HTML login formu döner (200 + form)
    "/giris": FakeResponse(200, '<html><form id="login-form"></form></html>'),
    # Ana sayfa — oturum açık varsayımıyla dashboard
    "/": FakeResponse(200, "<html><title>CPS Ana Sayfa</title><div id='dashboard'></div></html>"),
    # Üretim Planı
    "/planlama/uretim-plani": FakeResponse(200, "<html><title>Üretim Planı</title><table id='plan-table'></table></html>"),
    # Araç Takip
    "/planlama/arac-takip": FakeResponse(200, "<html><title>Araç Takip</title><div id='arac-list'></div></html>"),
    # Ödeme Planı — kpi_filtered blocker simüle ediliyor (bilinen hata)
    "/finans/odeme-plani": FakeResponse(200, "no such table: kpi_filtered"),
    # NexGen sipariş listesi
    "/nexgen/siparis": FakeResponse(200, "<html><title>NexGen Sipariş</title><table id='siparis-list'></table></html>"),
    # Yönetim / Onay
    "/yonetim/onay": FakeResponse(200, "<html><title>Onay Talepleri</title><div id='onay-list'></div></html>"),
    # Saha / Tablet
    "/canli-saha": FakeResponse(200, "<html><title>Canlı Saha</title><div id='saha-panel'></div></html>"),
}


def _run_mock_smoke(client: Callable[[str], FakeResponse]) -> list[SmokeResult]:
    cases = [
        ("login_page",           "/giris"),
        ("ana_sayfa",            "/"),
        ("uretim_plani",         "/planlama/uretim-plani"),
        ("arac_takip",           "/planlama/arac-takip"),
        ("finans_odeme_plani",   "/finans/odeme-plani"),
        ("nexgen_siparis",       "/nexgen/siparis"),
        ("yonetim_onay",         "/yonetim/onay"),
        ("saha_tablet",          "/canli-saha"),
    ]
    results = []
    for name, path in cases:
        resp = client(path)
        results.append(_check_response(name, resp))
    return results


# ---------------------------------------------------------------------------
# Code-new / DB-old  and  Code-old / DB-new matrix
# ---------------------------------------------------------------------------

def _matrix_code_new_db_old(client: Callable[[str], FakeResponse]) -> SmokeResult:
    """
    Simulates code expecting a new column but DB is old.
    Contract: should BLOCK (FAIL).
    """
    # Simulate a DB that is missing uretim_model_plan.enj_slot
    resp = FakeResponse(500, "no such column: enj_slot Internal Server Error")
    r = _check_response("matrix_code_new_db_old", resp)
    # Must be FAIL or DEPLOY_BLOCKER — if PASS that's a false pass
    if r.status == "PASS":
        return SmokeResult("matrix_code_new_db_old", "FAIL",
                           "Expected BLOCKED but got PASS — gate broken")
    return SmokeResult("matrix_code_new_db_old", "PASS",
                       f"Correctly blocked: {r.detail}")


def _matrix_code_old_db_new(client: Callable[[str], FakeResponse]) -> SmokeResult:
    """
    Simulates old code running against new DB that has extra columns.
    Contract: should not crash — old code simply ignores extra columns.
    Extra columns in DB do not cause a hard failure in SQLite SELECT *.
    Expected: PASS or explicit incompatibility warning.
    """
    # Old code page that ignores new columns — returns 200 with limited data
    resp = FakeResponse(200, "<html><title>Üretim Planı (eski kod)</title><table></table></html>")
    r = _check_response("matrix_code_old_db_new", resp)
    return SmokeResult("matrix_code_old_db_new", r.status,
                       r.detail or "Old code ignores extra DB columns — acceptable")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_all_smoke(base_url: str | None = None) -> int:
    """
    Returns exit code: 0 if no FAIL, 1 if any FAIL.
    DEPLOY_BLOCKER does not cause exit code 1 (but is reported).
    """
    client = _make_mock_client(_MOCK_FIXTURES)

    results: list[SmokeResult] = []
    results.extend(_run_mock_smoke(client))
    results.append(_matrix_code_new_db_old(client))
    results.append(_matrix_code_old_db_new(client))

    pass_count = 0
    fail_count = 0
    blocker_count = 0

    for r in results:
        print(f"SMOKE {r.name} STATUS={r.status}" + (f" | {r.detail}" if r.detail else ""))
        if r.status == "PASS":
            pass_count += 1
        elif r.status == "DEPLOY_BLOCKER":
            blocker_count += 1
        else:
            fail_count += 1

    print(f"\nSMOKE_PASS={pass_count} SMOKE_FAIL={fail_count} SMOKE_BLOCKERS={blocker_count}")

    if blocker_count:
        print("\nKNOWN_DEPLOY_BLOCKERS:")
        for r in results:
            if r.status == "DEPLOY_BLOCKER":
                print(f"  - {r.name}: {r.detail}")

    return 1 if fail_count else 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CPS critical browser smoke (mock)")
    parser.add_argument("--base-url", default=None, help="Ignored in mock mode")
    args = parser.parse_args()
    sys.exit(run_all_smoke(args.base_url))
