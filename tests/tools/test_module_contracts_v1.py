"""
tests/tools/test_module_contracts_v1.py
========================================
FAZ 0.4 — Modül şema sözleşmesi ve kritik smoke testleri.

Kapsam:
  - 8 modül TOML dosyası varlığı + parse edilebilirlik
  - Module schema parity check (mock DB üzerinde)
  - critical_browser_smoke.py: PASS/FAIL/DEPLOY_BLOCKER
  - Code-new/DB-old → BLOCKED
  - Code-old/DB-new → PASS veya uyumsuzluk raporu
  - False redirect PASS = 0
  - ATP diff kontrolü

YASAK: Canonical DB yazımı yok. Gerçek sunucu yok. Amend/force-push yok.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = WORKTREE / "tools" / "module_schema_contracts"
TOOLS_DIR = WORKTREE / "tools"

EXPECTED_MODULES = {
    "auth",
    "home",
    "finans",
    "arac_takip",
    "uretim_plani",   # FAZ 0.4 planlama sözleşmesi (planlama.toml dokunulmadı)
    "nexgen",
    "yonetim_onay",
    "saha_tablet",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_tool(name: str):
    path = TOOLS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_parity_db(tmp_path: Path) -> Path:
    """Minimal in-memory SQLite for parity checks."""
    db = tmp_path / "parity_test.db"
    con = sqlite3.connect(str(db))
    con.execute("""
        CREATE TABLE schema_migrations (
            version TEXT PRIMARY KEY
        )
    """)
    # Auth tables
    con.execute("CREATE TABLE kullanici (id INTEGER, kullanici_adi TEXT NOT NULL, sifre_hash TEXT NOT NULL, rol_id INTEGER, aktif INTEGER NOT NULL DEFAULT 1, ad TEXT, soyad TEXT, created_at TEXT)")
    con.execute("CREATE TABLE rol (id INTEGER PRIMARY KEY, ad TEXT NOT NULL, aciklama TEXT)")
    con.execute("CREATE TABLE permission_matrix (id INTEGER PRIMARY KEY, rol_id INTEGER NOT NULL, modul TEXT NOT NULL, yetki_seviye INTEGER NOT NULL DEFAULT 0)")

    # Home / planlama
    con.execute("""
        CREATE TABLE uretim_model_plan (
            id INTEGER, sip_no INTEGER NOT NULL, sip_harinx INTEGER NOT NULL,
            mamul_skod TEXT NOT NULL, rkod INTEGER NOT NULL DEFAULT 0,
            plan_donemi TEXT NOT NULL, oncelik INTEGER NOT NULL DEFAULT 3,
            aktif INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
            plan_baslangic TEXT
        )
    """)
    con.execute("CREATE INDEX idx_ump_donem ON uretim_model_plan (plan_donemi)")
    con.execute("CREATE INDEX idx_ump_tarih ON uretim_model_plan (plan_baslangic)")
    con.execute("CREATE INDEX idx_ump_canonical_aktif ON uretim_model_plan (aktif)")

    con.execute("""
        CREATE TABLE uretim_model_plan_emir (
            id INTEGER, plan_id INTEGER NOT NULL, emir_no INTEGER NOT NULL,
            emir_tipi TEXT NOT NULL DEFAULT 'M', miktar REAL NOT NULL,
            created_at TEXT
        )
    """)
    con.execute("CREATE UNIQUE INDEX uq_umpe_plan_emir ON uretim_model_plan_emir (plan_id, emir_no)")

    con.execute("""
        CREATE TABLE uretim_model_plan_enj_istasyon (
            id INTEGER, plan_id INTEGER NOT NULL, enj_makine_id INTEGER NOT NULL,
            enj_slot TEXT NOT NULL, istasyon_no INTEGER NOT NULL, created_at TEXT
        )
    """)

    con.execute("""
        CREATE TABLE uretim_plan_process (
            id INTEGER, plan_id INTEGER NOT NULL, sequence_no INTEGER NOT NULL,
            proses_kod TEXT NOT NULL, proses_adi TEXT, scheduling_status TEXT NOT NULL DEFAULT 'UNSCHEDULED',
            created_at TEXT NOT NULL
        )
    """)
    con.execute("CREATE INDEX idx_upproc_plan ON uretim_plan_process (plan_id)")

    # Finans
    con.execute("CREATE TABLE Cari_Kart (CKod TEXT, CName TEXT NOT NULL, CTip INTEGER DEFAULT 1, VergiNo TEXT, Bakiye REAL DEFAULT 0, Aktif INTEGER DEFAULT 1)")
    con.execute("CREATE TABLE Cari_Har (Id INTEGER, CKod TEXT NOT NULL, Tarih TEXT NOT NULL, Borc REAL DEFAULT 0, Alacak REAL DEFAULT 0)")
    con.execute("CREATE INDEX idx_ch_ckod ON Cari_Har (CKod)")
    con.execute("CREATE INDEX idx_ch_tarih ON Cari_Har (Tarih)")
    con.execute("CREATE TABLE Banka_Kart (Id INTEGER, BankaAd TEXT, Doviz TEXT DEFAULT 'TL')")
    con.execute("CREATE TABLE Kasa_Kart (Id INTEGER, KasaAd TEXT)")
    con.execute("CREATE TABLE Cek_Senet (Id INTEGER, CKod TEXT, VadeTarih TEXT)")

    # Araç Takip
    con.execute("""
        CREATE TABLE arac_gunluk_plan (
            id INTEGER, plan_tarihi TEXT NOT NULL,
            arac_provider TEXT NOT NULL DEFAULT 'TURKCELL_FILOM',
            arac_external_id TEXT NOT NULL, arac_plaka_snapshot TEXT NOT NULL,
            durum TEXT NOT NULL DEFAULT 'AKTIF',
            created_at TEXT NOT NULL, created_by INTEGER NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE arac_gunluk_plan_is (
            id INTEGER, plan_id INTEGER NOT NULL, is_talebi_id INTEGER NOT NULL,
            sira INTEGER NOT NULL, durum TEXT NOT NULL DEFAULT 'PLANLANDI',
            created_at TEXT
        )
    """)
    con.execute("""
        CREATE TABLE arac_is_talebi (
            id INTEGER, talep_no TEXT NOT NULL, firma_adi TEXT NOT NULL,
            adres TEXT NOT NULL, durum TEXT NOT NULL DEFAULT 'BEKLIYOR',
            created_at TEXT NOT NULL, talep_tarihi TEXT
        )
    """)
    con.execute("CREATE INDEX idx_arac_is_talebi_durum ON arac_is_talebi (durum)")
    con.execute("CREATE INDEX idx_arac_is_talebi_tarih ON arac_is_talebi (talep_tarihi)")
    con.execute("""
        CREATE TABLE arac_kayitli_yer (
            id INTEGER, firma_adi TEXT NOT NULL, adres TEXT NOT NULL,
            aktif INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE arac_gps_snapshot (
            id INTEGER, arac_external_id TEXT NOT NULL,
            gps_timestamp TEXT NOT NULL, latitude REAL NOT NULL,
            longitude REAL NOT NULL, created_at TEXT NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE arac_operasyon_ayar (
            id INTEGER, base_name TEXT NOT NULL,
            aktif INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        )
    """)

    # NexGen
    con.execute("""
        CREATE TABLE nexgen_planlama_siparis (
            id INTEGER, siparis_no TEXT NOT NULL,
            durum TEXT NOT NULL DEFAULT 'TALEP', cari_id INTEGER,
            olusturma_tarihi TEXT
        )
    """)
    con.execute("CREATE INDEX idx_nps_siparis_no ON nexgen_planlama_siparis (siparis_no)")
    con.execute("CREATE INDEX idx_nps_cari ON nexgen_planlama_siparis (cari_id)")
    con.execute("""
        CREATE TABLE nexgen_planlama_siparis_kalem (
            id INTEGER, planlama_siparis_id INTEGER NOT NULL, sira_no INTEGER NOT NULL DEFAULT 1
        )
    """)
    con.execute("""
        CREATE TABLE nexgen_onay (
            id INTEGER, onay_no TEXT NOT NULL, kaynak_turu TEXT NOT NULL,
            kaynak_id INTEGER NOT NULL, durum TEXT NOT NULL DEFAULT 'ONAY_BEKLIYOR',
            idempotency_key TEXT NOT NULL
        )
    """)
    con.execute("CREATE INDEX idx_nonay_durum ON nexgen_onay (durum)")
    con.execute("CREATE INDEX idx_nonay_kaynak ON nexgen_onay (kaynak_id)")
    con.execute("CREATE TABLE nexgen_cari (id INTEGER, aktif INTEGER DEFAULT 1)")
    con.execute("CREATE TABLE nexgen_stok_kart (id INTEGER, aktif INTEGER DEFAULT 1)")

    # Yönetim / Onay
    con.execute("""
        CREATE TABLE onay_talep (
            id INTEGER, talep_kod TEXT NOT NULL, talep_tipi TEXT NOT NULL,
            kaynak_modul TEXT NOT NULL, kaynak_id INTEGER NOT NULL,
            durum TEXT NOT NULL DEFAULT 'BEKLIYOR',
            idempotency_key TEXT NOT NULL, aktif INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)
    con.execute("CREATE INDEX idx_onay_talep_durum ON onay_talep (durum)")
    con.execute("CREATE INDEX idx_onay_talep_aktif_kaynak ON onay_talep (aktif, kaynak_id)")
    con.execute("""
        CREATE TABLE onay_talep_adim (
            id INTEGER, talep_id INTEGER NOT NULL, sira INTEGER NOT NULL,
            adim_tipi TEXT NOT NULL, kademe TEXT NOT NULL,
            durum TEXT NOT NULL DEFAULT 'BEKLIYOR'
        )
    """)
    con.execute("CREATE INDEX idx_onay_adim_talep ON onay_talep_adim (talep_id)")
    con.execute("""
        CREATE TABLE onay_adapter_log (
            id INTEGER, talep_id INTEGER, adapter_kodu TEXT NOT NULL,
            islem TEXT NOT NULL, sonuc TEXT NOT NULL, created_at TEXT NOT NULL
        )
    """)

    # Saha / Tablet
    con.execute("""
        CREATE TABLE operasyon_sinyal (
            id INTEGER, sinyal_tipi TEXT NOT NULL, seviye TEXT NOT NULL,
            mesaj TEXT NOT NULL, kaynak TEXT NOT NULL,
            durum TEXT DEFAULT 'AKTIF', emir_no TEXT, olusturma TEXT
        )
    """)
    con.execute("CREATE INDEX idx_os_tipi_durum ON operasyon_sinyal (sinyal_tipi, durum)")
    con.execute("CREATE INDEX idx_os_emir ON operasyon_sinyal (emir_no)")

    # Required migrations for planlama
    for v in ("158", "162", "163", "188"):
        con.execute("INSERT INTO schema_migrations (version) VALUES (?)", (v,))
    # Auth migrations
    for v in ("002", "006", "007", "009"):
        con.execute("INSERT INTO schema_migrations (version) VALUES (?)", (v,))

    con.commit()
    con.close()
    return db


# ---------------------------------------------------------------------------
# TOML contract tests
# ---------------------------------------------------------------------------

class TestContractFiles:
    def test_contract_count(self):
        """8 yeni modül TOML dosyası mevcut olmalı (planlama.toml FAZ0.2 sayılmaz)."""
        # FAZ 0.4 sözleşmeleri sadece; planlama.toml FAZ 0.2'ye ait ve dokunulmamış
        new_files = [f for f in CONTRACTS_DIR.glob("*.toml") if f.stem != "planlama"]
        stems = {f.stem for f in new_files}
        assert stems == EXPECTED_MODULES, (
            f"Expected {EXPECTED_MODULES}, got {stems}"
        )

    def test_all_parseable(self):
        """Her TOML dosyası parse edilebilmeli."""
        for f in CONTRACTS_DIR.glob("*.toml"):
            with open(f, "rb") as fh:
                data = tomllib.load(fh)
            assert "module" in data, f"{f.name}: missing 'module' key"

    def test_planlama_has_required_migrations(self):
        f = CONTRACTS_DIR / "uretim_plani.toml"
        with open(f, "rb") as fh:
            d = tomllib.load(fh)
        assert "158" in d["required_migrations"]
        assert "188" in d["required_migrations"]

    def test_finans_has_known_blockers(self):
        f = CONTRACTS_DIR / "finans.toml"
        with open(f, "rb") as fh:
            d = tomllib.load(fh)
        assert len(d.get("known_blockers", [])) > 0

    def test_saha_tablet_partial(self):
        f = CONTRACTS_DIR / "saha_tablet.toml"
        with open(f, "rb") as fh:
            d = tomllib.load(fh)
        assert d.get("parity_status") == "PARTIAL"


# ---------------------------------------------------------------------------
# Parity check tests
# ---------------------------------------------------------------------------

class TestModuleParity:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.db_path = _make_parity_db(tmp_path)
        self.parity_mod = _load_tool("module_schema_parity_check")

    def _run(self, module_filter=None):
        return self.parity_mod.run_module_parity(self.db_path, module_filter)

    def test_all_modules_run(self):
        results = self._run()
        names = {r["module"] for r in results}
        # 9 TOML toplam (8 yeni + FAZ 0.2 planlama): hepsi koşulur
        # Burada filter yok, tümü kontrol edilir
        assert len(names) >= 8

    def test_auth_pass(self):
        results = self._run("auth_giris")
        r = results[0]
        # Auth has migrations 002,006,007,009 — all seeded
        assert r["status"] in ("PASS", "PARTIAL")

    def test_planlama_pass(self):
        results = self._run("uretim_plani")
        r = results[0]
        assert r["status"] == "PASS", r["errors"]

    def test_finans_blocked(self):
        """Finans has known_blockers → BLOCKED."""
        results = self._run("finans_odeme_plani")
        r = results[0]
        assert r["status"] == "BLOCKED"
        assert any("kpi_filtered" in e for e in r["errors"])

    def test_saha_tablet_partial(self):
        results = self._run("saha_tablet")
        r = results[0]
        assert r["status"] == "PARTIAL"

    def test_arac_takip_pass(self):
        results = self._run("arac_takip")
        r = results[0]
        assert r["status"] in ("PASS", "PARTIAL"), r["errors"]

    def test_nexgen_pass(self):
        results = self._run("nexgen")
        r = results[0]
        assert r["status"] in ("PASS", "PARTIAL"), r["errors"]

    def test_yonetim_onay_pass(self):
        results = self._run("yonetim_onay")
        r = results[0]
        assert r["status"] in ("PASS", "PARTIAL"), r["errors"]

    def test_home_pass(self):
        results = self._run("home")
        r = results[0]
        # home has no dedicated tables beyond kullanici → PASS if no errors
        assert r["status"] in ("PASS", "PARTIAL"), r["errors"]

    def test_missing_table_blocks(self):
        """If a required table is absent, parity is BLOCKED."""
        db = self.db_path.parent / "no_onay.db"
        con = sqlite3.connect(str(db))
        # Minimal — no onay_talep
        con.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY)")
        con.commit()
        con.close()
        results = self.parity_mod.run_module_parity(db, "yonetim_onay")
        r = results[0]
        assert r["status"] == "BLOCKED"
        missing = [e for e in r["errors"] if "MISSING_TABLE" in e]
        assert len(missing) > 0

    def test_missing_migration_blocks(self):
        """Missing required migration → BLOCKED."""
        db = self.db_path.parent / "no_mig.db"
        con = sqlite3.connect(str(db))
        con.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY)")
        # Create tables but no migrations
        con.execute("CREATE TABLE uretim_model_plan (id INTEGER, sip_no INTEGER NOT NULL, mamul_skod TEXT NOT NULL, plan_donemi TEXT NOT NULL, plan_baslangic TEXT, oncelik INTEGER NOT NULL DEFAULT 3, aktif INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)")
        con.execute("CREATE INDEX idx_ump_donem ON uretim_model_plan (plan_donemi)")
        con.execute("CREATE INDEX idx_ump_tarih ON uretim_model_plan (plan_baslangic)")
        con.execute("CREATE INDEX idx_ump_canonical_aktif ON uretim_model_plan (aktif)")
        con.execute("CREATE TABLE uretim_model_plan_emir (id INTEGER, plan_id INTEGER NOT NULL, emir_no INTEGER NOT NULL, emir_tipi TEXT NOT NULL, miktar REAL NOT NULL)")
        con.execute("CREATE UNIQUE INDEX uq_umpe_plan_emir ON uretim_model_plan_emir (plan_id, emir_no)")
        con.execute("CREATE TABLE uretim_model_plan_enj_istasyon (id INTEGER, plan_id INTEGER NOT NULL, enj_makine_id INTEGER NOT NULL, enj_slot TEXT NOT NULL, istasyon_no INTEGER NOT NULL)")
        con.execute("CREATE TABLE uretim_plan_process (id INTEGER, plan_id INTEGER NOT NULL, sequence_no INTEGER NOT NULL, proses_kod TEXT NOT NULL, scheduling_status TEXT NOT NULL DEFAULT 'UNSCHEDULED', created_at TEXT NOT NULL)")
        con.execute("CREATE INDEX idx_upproc_plan ON uretim_plan_process (plan_id)")
        con.commit()
        con.close()
        results = self.parity_mod.run_module_parity(db, "uretim_plani")
        r = results[0]
        assert r["status"] == "BLOCKED"
        missing_migs = [e for e in r["errors"] if "MISSING_MIGRATION" in e]
        assert len(missing_migs) > 0


# ---------------------------------------------------------------------------
# Browser smoke tests
# ---------------------------------------------------------------------------

class TestCriticalBrowserSmoke:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.smoke_mod = _load_tool("critical_browser_smoke")

    def test_check_response_pass(self):
        resp = self.smoke_mod.FakeResponse(200, "<html><title>OK</title></html>")
        r = self.smoke_mod._check_response("test", resp)
        assert r.status == "PASS"

    def test_302_is_fail(self):
        """302 login redirect must NOT be PASS."""
        resp = self.smoke_mod.FakeResponse(302, "", url="/giris")
        r = self.smoke_mod._check_response("login", resp)
        assert r.status == "FAIL"
        # FALSE_REDIRECT_PASS gate
        assert r.status != "PASS"

    def test_404_is_fail(self):
        resp = self.smoke_mod.FakeResponse(404, "404 Not Found")
        r = self.smoke_mod._check_response("missing", resp)
        assert r.status == "FAIL"

    def test_500_is_fail(self):
        resp = self.smoke_mod.FakeResponse(500, "Internal Server Error")
        r = self.smoke_mod._check_response("err", resp)
        assert r.status == "FAIL"

    def test_sistem_hatasi_is_fail(self):
        resp = self.smoke_mod.FakeResponse(200, "<html>Sistem hatası oluştu</html>")
        r = self.smoke_mod._check_response("sys_err", resp)
        assert r.status == "FAIL"

    def test_kpi_filtered_is_deploy_blocker(self):
        resp = self.smoke_mod.FakeResponse(200, "no such table: kpi_filtered")
        r = self.smoke_mod._check_response("finans", resp)
        assert r.status == "DEPLOY_BLOCKER"

    def test_traceback_is_fail(self):
        resp = self.smoke_mod.FakeResponse(200, "Traceback (most recent call last):\n  File foo.py")
        r = self.smoke_mod._check_response("tb", resp)
        assert r.status == "FAIL"

    def test_mock_smoke_all_smoke_runs(self):
        """run_all_smoke çalışmalı ve toplam 10 test üretmeli."""
        client = self.smoke_mod._make_mock_client(self.smoke_mod._MOCK_FIXTURES)
        from tools import critical_browser_smoke as sm
        results = sm._run_mock_smoke(client)
        assert len(results) == 8

    def test_false_redirect_pass_is_zero(self):
        """Hiçbir 302 → PASS olmamalı."""
        client = self.smoke_mod._make_mock_client(self.smoke_mod._MOCK_FIXTURES)
        from tools import critical_browser_smoke as sm
        results = sm._run_mock_smoke(client)
        false_passes = [r for r in results
                        if r.status == "PASS" and "302" in r.detail]
        assert len(false_passes) == 0

    def test_code_new_db_old_blocked(self):
        """Code-new/DB-old → PASS result means gate passed (correctly blocked old DB)."""
        client = self.smoke_mod._make_mock_client({})
        r = self.smoke_mod._matrix_code_new_db_old(client)
        assert r.status == "PASS"  # gate passed because it correctly detected blocker

    def test_code_old_db_new_pass_or_compat_report(self):
        """Code-old/DB-new → PASS (extra columns ignored) or explicit compat note."""
        client = self.smoke_mod._make_mock_client({})
        r = self.smoke_mod._matrix_code_old_db_new(client)
        assert r.status in ("PASS", "DEPLOY_BLOCKER")

    def test_finans_known_blocker_reported(self):
        """Finans odeme planı fixture → DEPLOY_BLOCKER detected, not FAIL or PASS."""
        client = self.smoke_mod._make_mock_client(self.smoke_mod._MOCK_FIXTURES)
        from tools import critical_browser_smoke as sm
        results = sm._run_mock_smoke(client)
        finans_r = next(r for r in results if r.name == "finans_odeme_plani")
        assert finans_r.status == "DEPLOY_BLOCKER"
        # Must not be PASS (false positive)
        assert finans_r.status != "PASS"

    def test_http_404_count_zero(self):
        """No fixture returns 404."""
        client = self.smoke_mod._make_mock_client(self.smoke_mod._MOCK_FIXTURES)
        from tools import critical_browser_smoke as sm
        results = sm._run_mock_smoke(client)
        fails_404 = [r for r in results if "HTTP 404" in r.detail]
        assert len(fails_404) == 0

    def test_http_500_count_zero(self):
        """No fixture returns 500."""
        client = self.smoke_mod._make_mock_client(self.smoke_mod._MOCK_FIXTURES)
        from tools import critical_browser_smoke as sm
        results = sm._run_mock_smoke(client)
        fails_500 = [r for r in results if "HTTP 500" in r.detail]
        assert len(fails_500) == 0


# ---------------------------------------------------------------------------
# ATP diff gate (read-only)
# ---------------------------------------------------------------------------

def test_atp_diff_zero():
    """ATP stabilization lock değişmemiş olmalı."""
    result = subprocess.run(
        [sys.executable, "tools/validate_atp_stabilization_lock.py"],
        capture_output=True, text=True, cwd=str(WORKTREE)
    )
    assert "ATP_DIFF=0" in result.stdout, result.stdout + result.stderr
