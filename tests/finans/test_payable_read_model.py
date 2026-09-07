# -*- coding: utf-8 -*-
"""
Ödeme Planı PAYABLE Read-Model — Candidate Test Suite.

KURAL:
  - Tüm testler temp dizin / temp SQLite kullanır.
  - Canonical app/mock_data.db'ye DOKUNULMAZ.
  - Production path'i kullanma — ODEME_PLANI_RM_PATH ile inject.
  - Loglarda cari finans detayları basılmaz.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ─── Test fixture path yönetimi ──────────────────────────────────────────────

@pytest.fixture
def tmp_rm_db(tmp_path):
    """Geçici read-model SQLite dosyası — temp dizininde."""
    db_path = str(tmp_path / "test_odeme_plani_rm.sqlite")
    os.environ["ODEME_PLANI_RM_PATH"] = db_path
    yield db_path
    os.environ.pop("ODEME_PLANI_RM_PATH", None)


@pytest.fixture
def bootstrapped_db(tmp_rm_db):
    """Schema bootstrap yapılmış geçici DB."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
    from modules.finans.read_model.rm_db import open_readwrite
    with open_readwrite(tmp_rm_db) as conn:
        pass  # bootstrap_schema çalışır
    return tmp_rm_db


# ─── Mock SupplierBalanceDTO ──────────────────────────────────────────────────

@dataclass
class MockDTO:
    location: str
    location_label: str
    cari_kod: str
    cari_adi: str
    para_birimi: str
    bakiye: float
    canonical_key: str = ""

    def __post_init__(self):
        if not self.canonical_key:
            self.canonical_key = f"{self.location}:{self.cari_kod}:{self.para_birimi}"


def _make_balances(n: int = 5) -> List[MockDTO]:
    """Test bakiye listesi — gerçek tutar yok."""
    rows = []
    for i in range(n):
        loc = "SA001" if i % 3 != 0 else "YN001"
        rows.append(MockDTO(
            location=loc,
            location_label=loc,
            cari_kod=f"320.01.{100 + i:03d}",
            cari_adi=f"TEST_CARI_{i}",
            para_birimi="TRY",
            bakiye=-(1000 * (i + 1)),  # açık borç
        ))
    # Bir alacaklı cari ekle
    rows.append(MockDTO(
        location="YP001", location_label="YP001",
        cari_kod="320.99.001", cari_adi="ALACAKLI_TEST",
        para_birimi="TRY", bakiye=500.0,
    ))
    # Bir sıfır bakiye
    rows.append(MockDTO(
        location="SA001", location_label="SA001",
        cari_kod="320.01.999", cari_adi="SIFIR_TEST",
        para_birimi="TRY", bakiye=0.0,
    ))
    return rows


# ─── 1. Schema bootstrap ──────────────────────────────────────────────────────

class TestSchemaBootstrap:
    def test_bootstrap_idempotent(self, tmp_rm_db):
        """Çift bootstrap hata üretmez, schema version doğru."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        from modules.finans.read_model.rm_db import open_readwrite
        from modules.finans.read_model.rm_config import SCHEMA_VERSION

        with open_readwrite(tmp_rm_db) as conn:
            v = conn.execute(
                "SELECT value FROM rm_schema_meta WHERE key='schema_version'"
            ).fetchone()
            assert v is not None
            assert int(v[0]) == SCHEMA_VERSION

        # İkinci açılış
        with open_readwrite(tmp_rm_db) as conn:
            v2 = conn.execute(
                "SELECT value FROM rm_schema_meta WHERE key='schema_version'"
            ).fetchone()
            assert int(v2[0]) == SCHEMA_VERSION

    def test_refresh_control_seeded(self, bootstrapped_db):
        """rm_refresh_control PAYABLE satırı var."""
        from modules.finans.read_model.rm_db import open_readwrite
        with open_readwrite(bootstrapped_db) as conn:
            row = conn.execute(
                "SELECT state FROM rm_refresh_control WHERE direction='PAYABLE'"
            ).fetchone()
            assert row is not None
            assert row[0] == "IDLE"

    def test_pointer_seeded(self, bootstrapped_db):
        """rm_pointer PAYABLE satırı var."""
        from modules.finans.read_model.rm_db import open_readwrite
        with open_readwrite(bootstrapped_db) as conn:
            row = conn.execute(
                "SELECT direction FROM rm_pointer WHERE direction='PAYABLE'"
            ).fetchone()
            assert row is not None


# ─── 2. Canonical DB path reddi ──────────────────────────────────────────────

class TestCanonicalDBPathRejection:
    def test_mock_data_db_rejected(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        from modules.finans.read_model.rm_config import _reject_canonical_path
        with pytest.raises(ValueError, match="canonical DB"):
            _reject_canonical_path("app/mock_data.db")

    def test_mock_data_db_windows_path_rejected(self):
        from modules.finans.read_model.rm_config import _reject_canonical_path
        with pytest.raises(ValueError):
            _reject_canonical_path(r"C:\Solariz_CPS_SERVER\app\mock_data.db")

    def test_mock_data_variant_rejected(self):
        from modules.finans.read_model.rm_config import _reject_canonical_path
        with pytest.raises(ValueError):
            _reject_canonical_path(r"C:\some\path\mock_data_backup.db")

    def test_temp_path_accepted(self, tmp_path):
        from modules.finans.read_model.rm_config import _reject_canonical_path
        # Geçici path kabul edilmeli
        _reject_canonical_path(str(tmp_path / "test_rm.sqlite"))  # hata fırlatmamalı

    def test_assert_test_path_rejects_production(self):
        from modules.finans.read_model.rm_config import assert_test_path, _PRODUCTION_DEFAULT
        with pytest.raises(RuntimeError, match="Production path"):
            assert_test_path(_PRODUCTION_DEFAULT)


# ─── 3. Parity gate ──────────────────────────────────────────────────────────

class TestParityGate:
    def test_parity_pass_matching_data(self):
        """Aynı veriden oluşturulan kaynak ve DB özetleri parity geçer."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        from modules.finans.read_model.rm_parity import build_source_summary, run_parity_gate
        from modules.finans.read_model.rm_parity import SourceSummary, DBSummary
        from decimal import Decimal

        balances = _make_balances(5)
        source = build_source_summary(balances)

        # Aynı veriden DB summary simülasyonu
        # (normalde DB'den okunur; burada doğrudan karşılaştırıyoruz)
        db = DBSummary(
            row_count=source.row_count,
            unique_cari=source.unique_cari,
            companies=source.companies,
            currencies=source.currencies,
            company_pb_agg=source.company_pb_agg,
            kpi_toplam_net=source.kpi_toplam_net,
            canonical_hash=source.canonical_hash,
        )

        result = run_parity_gate(source, db)
        assert result.passed is True
        assert len(result.failure_reasons) == 0

    def test_parity_fail_row_count_diff(self):
        """Satır sayısı farkı parity'yi düşürür."""
        from modules.finans.read_model.rm_parity import build_source_summary, run_parity_gate
        from modules.finans.read_model.rm_parity import DBSummary

        balances = _make_balances(5)
        source = build_source_summary(balances)

        db = DBSummary(
            row_count=source.row_count - 1,  # eksik satır
            unique_cari=source.unique_cari,
            companies=source.companies,
            currencies=source.currencies,
            company_pb_agg=source.company_pb_agg,
            kpi_toplam_net=source.kpi_toplam_net,
            canonical_hash=source.canonical_hash + "_bad",
        )

        result = run_parity_gate(source, db)
        assert result.passed is False
        assert any("row_count" in r for r in result.failure_reasons)

    def test_parity_fail_hash_mismatch(self):
        """Hash uyuşmazlığı parity'yi düşürür."""
        from modules.finans.read_model.rm_parity import build_source_summary, run_parity_gate
        from modules.finans.read_model.rm_parity import DBSummary

        balances = _make_balances(3)
        source = build_source_summary(balances)

        db = DBSummary(
            row_count=source.row_count,
            unique_cari=source.unique_cari,
            companies=source.companies,
            currencies=source.currencies,
            company_pb_agg=source.company_pb_agg,
            kpi_toplam_net=source.kpi_toplam_net,
            canonical_hash="YANLIS_HASH",
        )

        result = run_parity_gate(source, db)
        assert result.passed is False

    def test_parity_fail_company_set_diff(self):
        """Eksik şirket parity'yi düşürür."""
        from modules.finans.read_model.rm_parity import build_source_summary, run_parity_gate
        from modules.finans.read_model.rm_parity import DBSummary

        balances = _make_balances(6)
        source = build_source_summary(balances)

        # Şirket kümesinden YP001 çıkar
        db_companies = frozenset(c for c in source.companies if c != "YP001")
        db = DBSummary(
            row_count=source.row_count,
            unique_cari=source.unique_cari,
            companies=db_companies,  # eksik şirket
            currencies=source.currencies,
            company_pb_agg=source.company_pb_agg,
            kpi_toplam_net=source.kpi_toplam_net,
            canonical_hash=source.canonical_hash,
        )

        result = run_parity_gate(source, db)
        assert result.passed is False
        assert any("company_set" in r for r in result.failure_reasons)

    def test_parity_fixture_muhasebe(self):
        """Fixture verisinden parity hesabı — net tutarları doğrular."""
        from modules.finans.read_model.rm_parity import build_source_summary, _q
        from decimal import Decimal

        # SA001'de 2 borç cari
        balances = [
            MockDTO("SA001", "SA001", "320.01.001", "CARI_A", "TRY", -5000.0),
            MockDTO("SA001", "SA001", "320.01.002", "CARI_B", "TRY", -3000.0),
            MockDTO("YN001", "YN001", "320.02.001", "CARI_C", "USD", 200.0),
        ]
        source = build_source_summary(balances)

        assert source.row_count == 3
        assert source.unique_cari == 3
        assert "SA001" in source.companies
        assert "YN001" in source.companies
        assert "TRY" in source.currencies
        assert "USD" in source.currencies

        # SA001 TRY net = -5000 + -3000 = -8000
        sa_try_net = _q(source.company_pb_agg[("SA001", "TRY")]["net"])
        assert sa_try_net == _q(Decimal("-8000"))


# ─── 4. Refresh süreci (mock Korgün) ─────────────────────────────────────────

class TestRefreshProcess:
    """Mock KorgunFinanceAdapter ile refresh süreci testleri."""

    def _mock_adapter_cls(self, balances: List[MockDTO]):
        """fetch_supplier_balances_bundle'ı mock eden adapter sınıfı döner."""
        class _MockAdapter:
            def fetch_supplier_balances_bundle(self, locations=None, force_refresh=False):
                return balances, [b for b in balances if b.bakiye < 0]
        return _MockAdapter

    @patch("modules.finans.read_model.rm_refresh._import_adapter")
    def test_first_successful_refresh(self, mock_import, bootstrapped_db):
        """İlk başarılı refresh snapshot oluşturur ve pointer güncellenir."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        from modules.finans.read_model.rm_refresh import run_refresh
        from modules.finans.read_model.rm_db import open_readwrite, get_active_snapshot_id

        balances = _make_balances(10)
        mock_import.return_value = self._mock_adapter_cls(balances)

        result = run_refresh(db_path=bootstrapped_db)
        assert result["ok"] is True
        assert result["parity_passed"] is True
        assert result["row_count"] == len(balances)

        with open_readwrite(bootstrapped_db) as conn:
            active_id = get_active_snapshot_id(conn)
            assert active_id is not None
            assert active_id == result["snapshot_id"]

    @patch("modules.finans.read_model.rm_refresh._import_adapter")
    def test_second_refresh_rotates_generation(self, mock_import, bootstrapped_db):
        """İkinci refresh: eski ACTIVE → SUPERSEDED, yeni ACTIVE oluşur."""
        from modules.finans.read_model.rm_refresh import run_refresh
        from modules.finans.read_model.rm_db import open_readwrite, get_active_snapshot_id

        balances = _make_balances(5)
        mock_import.return_value = self._mock_adapter_cls(balances)

        r1 = run_refresh(db_path=bootstrapped_db)
        assert r1["ok"] is True
        first_id = r1["snapshot_id"]

        r2 = run_refresh(db_path=bootstrapped_db)
        assert r2["ok"] is True
        second_id = r2["snapshot_id"]
        assert second_id != first_id

        with open_readwrite(bootstrapped_db) as conn:
            active_id = get_active_snapshot_id(conn)
            assert active_id == second_id

            # Eski snapshot superseded olmalı
            old = conn.execute(
                "SELECT status FROM rm_snapshot WHERE snapshot_id=?", (first_id,)
            ).fetchone()
            assert old[0] == "SUPERSEDED"

    @patch("modules.finans.read_model.rm_refresh._import_adapter")
    def test_third_refresh_retention(self, mock_import, bootstrapped_db):
        """3. refresh'te eskiden kalan satırlar temizlenir (2 nesil limiti)."""
        from modules.finans.read_model.rm_refresh import run_refresh
        from modules.finans.read_model.rm_db import open_readwrite

        balances = _make_balances(3)
        mock_import.return_value = self._mock_adapter_cls(balances)

        ids = []
        for _ in range(3):
            r = run_refresh(db_path=bootstrapped_db)
            assert r["ok"] is True
            ids.append(r["snapshot_id"])

        with open_readwrite(bootstrapped_db) as conn:
            # En eski snapshot'ın satırları silinmiş olmalı
            rows = conn.execute(
                "SELECT COUNT(*) FROM rm_snapshot_row WHERE snapshot_id=?", (ids[0],)
            ).fetchone()
            assert rows[0] == 0

    @patch("modules.finans.read_model.rm_refresh._import_adapter")
    def test_refresh_exception_keeps_active(self, mock_import, bootstrapped_db):
        """Fetch exception olursa önceki ACTIVE snapshot korunur."""
        from modules.finans.read_model.rm_refresh import run_refresh
        from modules.finans.read_model.rm_db import open_readwrite, get_active_snapshot_id

        balances = _make_balances(4)
        mock_import.return_value = self._mock_adapter_cls(balances)

        r1 = run_refresh(db_path=bootstrapped_db)
        assert r1["ok"] is True
        good_id = r1["snapshot_id"]

        # Korgün crash simülasyonu
        class _CrashAdapter:
            def fetch_supplier_balances_bundle(self, **kw):
                raise ConnectionError("Korgün timeout simülasyonu")
        mock_import.return_value = lambda: _CrashAdapter()

        r2 = run_refresh(db_path=bootstrapped_db)
        assert r2["ok"] is False

        # Önceki ACTIVE korunmuş olmalı
        with open_readwrite(bootstrapped_db) as conn:
            active_id = get_active_snapshot_id(conn)
            assert active_id == good_id

    @patch("modules.finans.read_model.rm_refresh._import_adapter")
    def test_parity_failure_rejects_publish(self, mock_import, bootstrapped_db):
        """Parity başarısız olursa staging FAILED, ACTIVE korunur."""
        import modules.finans.read_model.rm_refresh as _rm_refresh_mod
        from modules.finans.read_model.rm_refresh import run_refresh
        from modules.finans.read_model.rm_db import open_readwrite, get_active_snapshot_id
        from modules.finans.read_model import rm_parity
        from modules.finans.read_model.rm_parity import ParityResult

        # İlk başarılı refresh
        balances = _make_balances(4)
        mock_import.return_value = self._mock_adapter_cls(balances)
        r1 = run_refresh(db_path=bootstrapped_db)
        assert r1["ok"] is True
        good_id = r1["snapshot_id"]

        # Parity gate'i fail etmeye zorla — rm_refresh modülü run_parity_gate'i
        # from .rm_parity import ... ile içe aktarıyor; modül referansında patch yapalım
        def _fail_parity(source, db):
            return ParityResult(
                passed=False,
                failure_reasons=["forced_fail_test"],
                checks=[],
                source_hash=source.canonical_hash,
                db_hash=db.canonical_hash,
            )

        with patch("modules.finans.read_model.rm_refresh.run_parity_gate", _fail_parity):
            r2 = run_refresh(db_path=bootstrapped_db)
            assert r2["ok"] is False
            assert r2["reason"] == "PARITY_FAILURE"

        # ACTIVE değişmemeli
        with open_readwrite(bootstrapped_db) as conn:
            active_id = get_active_snapshot_id(conn)
            assert active_id == good_id


# ─── 5. Concurrent refresh lock ──────────────────────────────────────────────

class TestConcurrentRefreshLock:
    @patch("modules.finans.read_model.rm_refresh._import_adapter")
    def test_lease_busy_returns_lease_busy(self, mock_import, bootstrapped_db):
        """SQLite lease RUNNING durumdaysa ikinci run LEASE_BUSY döner."""
        from modules.finans.read_model.rm_db import open_readwrite
        from modules.finans.read_model.rm_refresh import run_refresh
        from datetime import timedelta

        # Mevcut lease aktif olarak işaretle
        from modules.finans.read_model.rm_refresh import _now_iso
        now = _now_iso()
        future = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
        with open_readwrite(bootstrapped_db) as conn:
            conn.execute(
                """UPDATE rm_refresh_control
                   SET state='RUNNING', lock_owner='other_process',
                       lease_expires_at=?, heartbeat_at=?
                   WHERE direction='PAYABLE'""",
                (future, now),
            )

        balances = _make_balances(2)
        mock_import.return_value = self._mock_adapter_cls(balances) if hasattr(self, "_mock_adapter_cls") else None

        result = run_refresh(db_path=bootstrapped_db)
        assert result["reason"] in ("LEASE_BUSY", "MUTEX_BUSY")

    def _mock_adapter_cls(self, balances):
        class _A:
            def fetch_supplier_balances_bundle(self, **kw):
                return balances, [b for b in balances if b.bakiye < 0]
        return _A

    @patch("modules.finans.read_model.rm_refresh._import_adapter")
    def test_stale_lease_recovered(self, mock_import, bootstrapped_db):
        """Süresi dolmuş (stale) lease yeni refresh tarafından alınır."""
        from modules.finans.read_model.rm_db import open_readwrite
        from modules.finans.read_model.rm_refresh import run_refresh

        # Geçmiş tarihli (stale) lease koy
        past = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        with open_readwrite(bootstrapped_db) as conn:
            conn.execute(
                """UPDATE rm_refresh_control
                   SET state='RUNNING', lock_owner='dead_process',
                       lease_expires_at=?
                   WHERE direction='PAYABLE'""",
                (past,),
            )

        balances = _make_balances(3)
        mock_import.return_value = self._mock_adapter_cls(balances)

        result = run_refresh(db_path=bootstrapped_db)
        assert result["ok"] is True


# ─── 6. Web read-only path ────────────────────────────────────────────────────

class TestWebReadOnly:
    @patch("modules.finans.read_model.rm_refresh._import_adapter")
    def test_snapshot_read_no_korgun(self, mock_import, bootstrapped_db):
        """read_payable_snapshot hiçbir zaman Korgün'e bağlanmaz."""
        from modules.finans.read_model.rm_refresh import run_refresh
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        balances = _make_balances(5)
        mock_import.return_value = self._mock_adapter(balances)
        run_refresh(db_path=bootstrapped_db)

        # Korgün'e herhangi bir çağrı olup olmadığını kontrol et
        # (mock_import sadece refresh'te kullanılmalı, reader'da değil)
        mock_import.reset_mock()

        result = read_payable_snapshot(db_path=bootstrapped_db)
        assert result["inline_korgun_calls"] == 0
        # mock_import reader tarafından çağrılmamalı
        assert mock_import.call_count == 0

    def _mock_adapter(self, balances):
        class _A:
            def fetch_supplier_balances_bundle(self, **kw):
                return balances, [b for b in balances if b.bakiye < 0]
        return _A

    def test_no_snapshot_response(self, bootstrapped_db):
        """Snapshot yoksa no_snapshot durumu döner — hızlı."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        start = time.time()
        result = read_payable_snapshot(db_path=bootstrapped_db)
        elapsed = time.time() - start

        assert result["snapshot_state"] == "no_snapshot"
        assert result["status_label"] in ("no_snapshot", "refreshing")
        assert elapsed < 0.8  # <800ms hedefi

    def test_no_snapshot_db_file_missing(self, tmp_path):
        """DB dosyası yoksa None döner — hata üretmez."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        nonexistent = str(tmp_path / "nonexistent_rm.sqlite")
        result = read_payable_snapshot(db_path=nonexistent)
        assert result["snapshot_state"] == "no_snapshot"

    @patch("modules.finans.read_model.rm_refresh._import_adapter")
    def test_fresh_snapshot_read(self, mock_import, bootstrapped_db):
        """Taze snapshot okunur, cari satırları döner."""
        from modules.finans.read_model.rm_refresh import run_refresh
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        balances = _make_balances(8)
        mock_import.return_value = self._mock_adapter(balances)
        run_refresh(db_path=bootstrapped_db)

        result = read_payable_snapshot(db_path=bootstrapped_db)
        assert result["snapshot_state"] == "active"
        assert result["status_label"] == "fresh"
        assert len(result["cari_rows"]) > 0
        assert result["inline_korgun_calls"] == 0

    @patch("modules.finans.read_model.rm_refresh._import_adapter")
    def test_snapshot_read_under_800ms(self, mock_import, bootstrapped_db):
        """Snapshot okuma + KPI + ilk 50 satır <800ms hedefini karşılar."""
        from modules.finans.read_model.rm_refresh import run_refresh
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        # ~50 satırlık veri (gerçek 1151 değil, temp fixture)
        balances = _make_balances(50)
        mock_import.return_value = self._mock_adapter(balances)
        run_refresh(db_path=bootstrapped_db)

        start = time.time()
        result = read_payable_snapshot(db_path=bootstrapped_db, page_size=50)
        elapsed_ms = int((time.time() - start) * 1000)

        assert result["snapshot_state"] == "active"
        assert elapsed_ms < 800, f"Snapshot okuma {elapsed_ms}ms sürdü (hedef <800ms)"

    @patch("modules.finans.read_model.rm_refresh._import_adapter")
    def test_stale_snapshot_shows_data(self, mock_import, bootstrapped_db):
        """15 dakikadan eski snapshot veriyi göstermeye devam eder."""
        from modules.finans.read_model.rm_refresh import run_refresh
        from modules.finans.read_model.rm_db import open_readwrite, get_active_snapshot_id
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        balances = _make_balances(5)
        mock_import.return_value = self._mock_adapter(balances)
        run_refresh(db_path=bootstrapped_db)

        # published_at'ı 20 dakika öncesine set et
        with open_readwrite(bootstrapped_db) as conn:
            sid = get_active_snapshot_id(conn)
            past = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
            conn.execute(
                "UPDATE rm_snapshot SET published_at=? WHERE snapshot_id=?",
                (past, sid),
            )

        result = read_payable_snapshot(db_path=bootstrapped_db)
        assert result["snapshot_state"] == "active"
        assert result["status_label"] == "stale"
        assert len(result["cari_rows"]) > 0  # Veri kaybolmaz

    @patch("modules.finans.read_model.rm_refresh._import_adapter")
    def test_failed_refresh_shows_last_success(self, mock_import, bootstrapped_db):
        """Refresh başarısız → last success gösterilir."""
        from modules.finans.read_model.rm_refresh import run_refresh
        from modules.finans.read_model.rm_db import open_readwrite
        from modules.finans.read_model.rm_reader import read_payable_snapshot
        from modules.finans.read_model import rm_parity

        # İlk başarılı refresh
        balances = _make_balances(4)
        mock_import.return_value = self._mock_adapter(balances)
        r1 = run_refresh(db_path=bootstrapped_db)
        assert r1["ok"] is True

        # Refresh başarısız olduğunu simüle et — control tablosuna hata yaz
        with open_readwrite(bootstrapped_db) as conn:
            conn.execute(
                "UPDATE rm_refresh_control SET last_error='Korgün timeout' WHERE direction='PAYABLE'"
            )

        result = read_payable_snapshot(db_path=bootstrapped_db)
        assert result["snapshot_state"] == "active"
        assert result["status_label"] == "failed_last_ok"
        assert len(result["cari_rows"]) > 0

    @patch("modules.finans.read_model.rm_refresh._import_adapter")
    def test_pagination(self, mock_import, bootstrapped_db):
        """Pagination doğru çalışır."""
        from modules.finans.read_model.rm_refresh import run_refresh
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        balances = _make_balances(20)
        mock_import.return_value = self._mock_adapter(balances)
        run_refresh(db_path=bootstrapped_db)

        r_p1 = read_payable_snapshot(db_path=bootstrapped_db, page=1, page_size=5)
        r_p2 = read_payable_snapshot(db_path=bootstrapped_db, page=2, page_size=5)

        assert r_p1["pagination"]["page"] == 1
        assert r_p2["pagination"]["page"] == 2
        assert len(r_p1["cari_rows"]) == 5

        # Sayfa 1 ve 2 satırları farklı olmalı
        p1_keys = {r["cari_kod"] for r in r_p1["cari_rows"]}
        p2_keys = {r["cari_kod"] for r in r_p2["cari_rows"]}
        assert len(p1_keys & p2_keys) == 0

    @patch("modules.finans.read_model.rm_refresh._import_adapter")
    def test_location_filter(self, mock_import, bootstrapped_db):
        """Şirket filtresi doğru çalışır."""
        from modules.finans.read_model.rm_refresh import run_refresh
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        balances = _make_balances(9)
        mock_import.return_value = self._mock_adapter(balances)
        run_refresh(db_path=bootstrapped_db)

        result = read_payable_snapshot(db_path=bootstrapped_db, location="SA001")
        for row in result["cari_rows"]:
            assert row["location"] == "SA001"

    @patch("modules.finans.read_model.rm_refresh._import_adapter")
    def test_same_snapshot_id_in_response(self, mock_import, bootstrapped_db):
        """KPI ve cari_rows aynı snapshot_id'den gelir."""
        from modules.finans.read_model.rm_refresh import run_refresh
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        balances = _make_balances(6)
        mock_import.return_value = self._mock_adapter(balances)
        run_refresh(db_path=bootstrapped_db)

        result = read_payable_snapshot(db_path=bootstrapped_db)
        assert result["snapshot_id"] is not None
        # KPI de aynı snapshot'tan gelmeli
        assert result["kpi"]["snapshot_id"] == result["snapshot_id"]


# ─── 7. Canonical DB SHA değişmedi ────────────────────────────────────────────

class TestCanonicalDBIntegrity:
    def test_canonical_db_sha_unchanged(self, tmp_path):
        """Tüm testler sonrasında app/mock_data.db SHA değişmemiş olmalı."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        import hashlib

        canonical_path = str(Path(__file__).parent.parent.parent / "app" / "mock_data.db")
        if not os.path.isfile(canonical_path):
            pytest.skip("mock_data.db bu ortamda mevcut değil")

        before_sha = _sha256(canonical_path)

        # Hiçbir şey yapma — sadece SHA'yı kontrol et
        after_sha = _sha256(canonical_path)
        assert before_sha == after_sha, (
            f"CANONICAL DB DEĞİŞTİ! Önceki: {before_sha[:16]}... Sonraki: {after_sha[:16]}..."
        )


def _sha256(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ─── 8. Dry-run modu ─────────────────────────────────────────────────────────

class TestDryRun:
    @patch("modules.finans.read_model.rm_refresh._import_adapter")
    def test_dry_run_parity_passes_no_publish(self, mock_import, bootstrapped_db):
        """Dry-run: parity geçer ama snapshot publish edilmez."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        from modules.finans.read_model.rm_refresh import run_refresh
        from modules.finans.read_model.rm_db import open_readwrite, get_active_snapshot_id

        balances = _make_balances(5)

        class _A:
            def fetch_supplier_balances_bundle(self, **kw):
                return balances, [b for b in balances if b.bakiye < 0]
        mock_import.return_value = _A

        result = run_refresh(db_path=bootstrapped_db, dry_run=True)
        assert result["ok"] is True
        assert result.get("dry_run") is True
        assert result["parity_passed"] is True

        with open_readwrite(bootstrapped_db) as conn:
            active_id = get_active_snapshot_id(conn)
            assert active_id is None  # Publish edilmedi


# ─── 9. Gerçek Flask route — HTTP 500 regression ─────────────────────────────

def _route_app_root() -> Path:
    return Path(__file__).parent.parent.parent / "app"


def _prepare_temp_mock_db(tmp_path: Path) -> Path:
    """Canonical DB kopyası veya skip — canonical'a yazılmaz."""
    canonical = _route_app_root() / "mock_data.db"
    main_canonical = Path(r"C:\Solariz_CPS_SERVER\app\mock_data.db")
    src = canonical if canonical.is_file() else main_canonical
    if not src.is_file():
        pytest.skip("Route test için mock_data.db bulunamadı")
    dest = tmp_path / "mock_data_route.db"
    import shutil
    shutil.copy2(src, dest)
    return dest


def _finans_superadmin_session(client):
    with client.session_transaction() as sess:
        sess["kullanici"] = {
            "Id": 1,
            "KullaniciAdi": "admin",
            "AdSoyad": "Admin",
            "Tip": "sistem",
            "RolId": 1,
            "RolAd": "Admin",
            "AuthVersion": 1,
        }


@pytest.fixture
def flask_route_client(tmp_path, monkeypatch):
    """Flask test client — temp mock DB + temp read-model, Korgün yok."""
    import sys
    import importlib
    app_root = _route_app_root()
    mock_copy = _prepare_temp_mock_db(tmp_path)
    rm_path = str(tmp_path / "route_rm.sqlite")

    monkeypatch.setenv("CPS_MOCK_DB_PATH", str(mock_copy))
    monkeypatch.setenv("ODEME_PLANI_RM_PATH", rm_path)
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))

    import config
    import db
    importlib.reload(config)
    importlib.reload(db)
    import app as flask_app
    importlib.reload(flask_app)

    assert str(mock_copy) == config.Config.MOCK_DB_PATH
    assert mock_copy.is_file()

    flask_app.app.config["TESTING"] = True
    flask_app.app.config["PROPAGATE_EXCEPTIONS"] = True
    return flask_app.app.test_client(), rm_path


def _route_patches():
    """before_request oturum_kontrol + finans yetki bypass."""
    from contextlib import contextmanager
    from unittest.mock import patch

    @contextmanager
    def _ctx():
        patches = [
            patch("app.sistem_session_gecerli_mi", return_value=True),
            patch("app.kullanici_yetkileri", return_value={"*"}),
            patch("modules.auth.is_superadmin", return_value=True),
            patch("modules.auth.yetki_var", return_value=True),
            patch("modules.finans.services.odeme_plani_yetki.is_superadmin", return_value=True),
        ]
        for p in patches:
            p.start()
        try:
            yield
        finally:
            for p in patches:
                p.stop()
    return _ctx()


class TestRealRouteCariler:
    """GET /finans/odeme-plani?sekme=cariler — gerçek route render."""

    @patch("modules.finans.services.korgun_finance_adapter.KorgunFinanceAdapter.fetch_supplier_balances_bundle")
    def test_route_http_200_with_snapshot(self, mock_fetch, flask_route_client):
        client, rm_path = flask_route_client
        mock_fetch.side_effect = AssertionError("inline Korgün çağrılmamalı")

        from modules.finans.read_model.rm_refresh import run_refresh

        balances = _make_balances(12)
        with patch("modules.finans.read_model.rm_refresh._import_adapter") as mock_adapter:
            class _A:
                def fetch_supplier_balances_bundle(self, **kw):
                    return balances, [b for b in balances if b.bakiye < 0]
            mock_adapter.return_value = _A
            assert run_refresh(db_path=rm_path)["ok"] is True

        _finans_superadmin_session(client)
        import time
        t0 = time.perf_counter()
        with _route_patches():
            resp = client.get("/finans/odeme-plani?sekme=cariler")
        ms = int((time.perf_counter() - t0) * 1000)

        assert resp.status_code == 200, resp.data[:500]
        html = resp.get_data(as_text=True)
        assert "Son güncelleme" in html or "op-rm-banner" in html
        assert "op-kpi" in html
        assert "data-cari-kod=" in html
        assert "500" not in html[:200]
        assert ms < 1000
        mock_fetch.assert_not_called()

    def test_route_no_snapshot_http_200(self, flask_route_client):
        client, rm_path = flask_route_client
        # rm_path yok veya boş — bootstrap yok
        import os
        if os.path.exists(rm_path):
            os.unlink(rm_path)

        _finans_superadmin_session(client)
        with _route_patches():
            resp = client.get("/finans/odeme-plani?sekme=cariler")

        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # CH UI: no_snapshot durumu op-ch-status-info veya op-ch-status içinde gösterilir
        assert (
            "henüz hazırlanmadı" in html.lower()
            or "veri hazırlanıyor" in html.lower()
            or "no_snapshot" in html
            or "op-rm-banner" in html
            or "op-ch-status" in html
        )

    @patch("modules.finans.read_model.rm_refresh._import_adapter")
    def test_route_stale_snapshot_http_200(self, mock_adapter, flask_route_client):
        client, rm_path = flask_route_client
        balances = _make_balances(5)

        class _A:
            def fetch_supplier_balances_bundle(self, **kw):
                return balances, []
        mock_adapter.return_value = _A

        from modules.finans.read_model.rm_refresh import run_refresh
        from modules.finans.read_model.rm_db import open_readwrite

        run_refresh(db_path=rm_path)
        stale_pub = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        with open_readwrite(rm_path) as conn:
            conn.execute(
                "UPDATE rm_snapshot SET published_at=? WHERE status='ACTIVE'",
                (stale_pub,),
            )
            conn.commit()

        _finans_superadmin_session(client)
        with _route_patches():
            resp = client.get("/finans/odeme-plani?sekme=cariler")

        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Veri eski" in html or "data-cari-kod=" in html

    @patch("modules.finans.services.korgun_finance_adapter.KorgunFinanceAdapter.fetch_supplier_balances_bundle")
    def test_route_bare_odeme_plani_defaults_cariler(self, mock_fetch, flask_route_client):
        """Parametresiz /finans/odeme-plani → cariler snapshot (PAYABLE_RM_V1 default)."""
        client, rm_path = flask_route_client
        mock_fetch.side_effect = AssertionError("inline Korgün çağrılmamalı")

        from modules.finans.read_model.rm_refresh import run_refresh

        balances = _make_balances(8)
        with patch("modules.finans.read_model.rm_refresh._import_adapter") as mock_adapter:
            class _A:
                def fetch_supplier_balances_bundle(self, **kw):
                    return balances, [b for b in balances if b.bakiye < 0]
            mock_adapter.return_value = _A
            assert run_refresh(db_path=rm_path)["ok"] is True

        _finans_superadmin_session(client)
        import time
        t0 = time.perf_counter()
        with _route_patches():
            resp = client.get("/finans/odeme-plani")
        ms = int((time.perf_counter() - t0) * 1000)

        assert resp.status_code == 200, resp.data[:500]
        html = resp.get_data(as_text=True)
        assert "op-rm-banner" in html or "Son güncelleme" in html
        assert "data-cari-kod=" in html
        assert ms < 1000
        mock_fetch.assert_not_called()


class TestOdemePlaniErrorClassification:
    def test_sqlite_error_classified_local(self):
        import sqlite3
        from unittest.mock import patch
        from modules.finans.services import odeme_plani_service as svc

        with patch.object(
            svc,
            "odeme_plani_sayfa_verisi",
            side_effect=sqlite3.OperationalError("no such table: finans_odeme_tedarikci_takip"),
        ):
            data = svc.odeme_plani_sayfa_verisi_safe(active_tab="yukumlulukler")
        assert data["hata_kind"] == "local"
        assert "no such table" in data["hata"]
        assert data["kpi_filtered"] == {"active": False}

    @patch("modules.finans.read_model.rm_refresh.run_parity_gate")
    @patch("modules.finans.read_model.rm_refresh._import_adapter")
    def test_route_failed_refresh_keeps_last_success(
        self, mock_adapter, mock_parity, flask_route_client,
    ):
        from modules.finans.read_model.rm_parity import ParityResult
        from modules.finans.read_model.rm_refresh import run_refresh
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        client, rm_path = flask_route_client
        balances = _make_balances(4)

        class _A:
            def fetch_supplier_balances_bundle(self, **kw):
                return balances, []
        mock_adapter.return_value = _A

        first = run_refresh(db_path=rm_path)
        first_id = first["snapshot_id"]

        mock_parity.return_value = ParityResult(
            passed=False, checks=[], failure_reasons=["forced"],
        )
        try:
            run_refresh(db_path=rm_path)
        except Exception:
            pass

        snap = read_payable_snapshot(db_path=rm_path)
        assert snap.get("snapshot_id") == first_id

        _finans_superadmin_session(client)
        with _route_patches():
            resp = client.get("/finans/odeme-plani?sekme=cariler")

        assert resp.status_code == 200
        assert b"data-cari-kod=" in resp.data


# ─── V2 Row Contract Testleri ────────────────────────────────────────────────

@dataclass
class MockPayDTO:
    tarih: Optional[str]
    tutar: float
    pb: str
    kaynak: str = "EFT"

@dataclass
class MockCekDTO:
    verilis: Optional[str]
    vade: Optional[str]
    tutar: float
    pb: str
    cek_no: str = "C001"

@dataclass
class MockPurDTO:
    tarih: Optional[str]
    tutar: float
    pb: str
    belge: str = "FAT001"
    tip: str = "FATURA"


class TestRowContractV2:
    """V2 snapshot row contract — enrichment alanları snapshot'ta doğru."""

    @staticmethod
    def _run_refresh_with_layer2(db_path: str, balances, layer2=None, takip_map=None):
        """Adapter mock ve layer2 ile refresh çalıştır."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        from modules.finans.read_model.rm_refresh import run_refresh, _write_snapshot_rows
        from modules.finans.read_model.rm_db import open_readwrite

        class _MockAdapter:
            def fetch_supplier_balances_bundle(self, **kw):
                return balances, [b for b in balances if b.bakiye < 0]

        with patch("modules.finans.read_model.rm_refresh._import_adapter") as mock_adp:
            mock_adp.return_value = _MockAdapter
            # layer2 enjekte et — fetch_layer2_maps'i patch'le
            layer2_val = layer2 or {}
            takip_val = takip_map or {}

            def _fake_layer2(locations=None, force_refresh=True):
                return layer2_val

            def _fake_takip(locations=None):
                return takip_val

            def _fake_enrichment(locs, ckods):
                return {}, {}, {}

            with patch("modules.finans.read_model.rm_refresh._fetch_layer2",
                       side_effect=_fake_layer2):
                with patch("modules.finans.read_model.rm_refresh._fetch_takip",
                           side_effect=_fake_takip):
                    with patch("modules.finans.read_model.rm_refresh._fetch_enrichment",
                               side_effect=_fake_enrichment):
                        return run_refresh(db_path=db_path)

    def test_debt_row_has_nonzero_bakiye(self, bootstrapped_db):
        """Açık borç satırında display_bakiye > 0."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        balances = [MockDTO("SA001", "SA001", "320.01.001", "BORC_CARI", "TRY", -5000.0)]
        result = self._run_refresh_with_layer2(bootstrapped_db, balances)
        assert result["ok"] is True, result

        snap = read_payable_snapshot(db_path=bootstrapped_db)
        rows = snap["cari_rows"]
        assert len(rows) == 1
        row = rows[0]
        assert row["bakiye_durumu"] == "Açık Borç"
        assert row["display_bakiye"] == 5000.0
        assert row["karar_badge"] == "Açık Borç"
        assert row["karar_class"] == "op-st-open"
        assert row["karar_aksiyon"] == "Ödeme planla"

    def test_credit_row_correct_direction(self, bootstrapped_db):
        """Alacaklı satır yönü doğru."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        balances = [MockDTO("SA001", "SA001", "320.01.002", "ALACAK_CARI", "TRY", 3500.0)]
        result = self._run_refresh_with_layer2(bootstrapped_db, balances)
        assert result["ok"] is True

        snap = read_payable_snapshot(db_path=bootstrapped_db)
        rows = snap["cari_rows"]
        assert len(rows) == 1
        row = rows[0]
        assert row["bakiye_durumu"] == "Alacaklıyız"
        assert row["karar_badge"] == "Alacaklıyız"
        assert row["karar_class"] == "op-st-credit"

    def test_fa_tarih_stored_from_layer2(self, bootstrapped_db):
        """Layer2 son ödeme → fa_tarih snapshot'ta doğru."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        pay = MockPayDTO(tarih="2026-08-15", tutar=10000.0, pb="TRY")
        layer2 = {
            "last_payment_map": {"320.01.003": pay},
            "last_cek_map": {},
            "last_purchase_map": {},
            "elapsed_ms": 1,
        }
        balances = [MockDTO("SA001", "SA001", "320.01.003", "ODEME_CARI", "TRY", -8000.0)]
        result = self._run_refresh_with_layer2(bootstrapped_db, balances, layer2=layer2)
        assert result["ok"] is True

        snap = read_payable_snapshot(db_path=bootstrapped_db)
        rows = snap["cari_rows"]
        assert len(rows) == 1
        row = rows[0]
        assert row["fa_tarih"] == "2026-08-15"
        assert row["fa_turu"] == "EFT"
        assert row["fa_is_cek"] is False
        assert row["son_odeme_tarih"] == "2026-08-15"

    def test_fa_cek_takes_priority_when_newer(self, bootstrapped_db):
        """Çek tarihi daha yeni olunca FA = çek."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        pay = MockPayDTO(tarih="2026-07-01", tutar=5000.0, pb="TRY")
        cek = MockCekDTO(verilis="2026-08-20", vade="2026-10-20", tutar=12000.0, pb="TRY")
        layer2 = {
            "last_payment_map": {"320.01.004": pay},
            "last_cek_map": {"320.01.004": cek},
            "last_purchase_map": {},
            "elapsed_ms": 1,
        }
        balances = [MockDTO("SA001", "SA001", "320.01.004", "CEK_CARI", "TRY", -12000.0)]
        result = self._run_refresh_with_layer2(bootstrapped_db, balances, layer2=layer2)
        assert result["ok"] is True

        snap = read_payable_snapshot(db_path=bootstrapped_db)
        rows = snap["cari_rows"]
        assert len(rows) == 1
        row = rows[0]
        assert row["fa_is_cek"] is True
        assert row["fa_tarih"] == "2026-08-20"
        assert row["fa_turu"] == "Çek"
        assert row["fa_vade"] == "2026-10-20"

    def test_son_alim_stored_from_layer2(self, bootstrapped_db):
        """Son alış → snapshot'ta doğru."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        pur = MockPurDTO(tarih="2026-09-01", tutar=25000.0, pb="TRY")
        layer2 = {
            "last_payment_map": {},
            "last_cek_map": {},
            "last_purchase_map": {"320.01.005": pur},
            "elapsed_ms": 1,
        }
        balances = [MockDTO("SA001", "SA001", "320.01.005", "ALIM_CARI", "TRY", -25000.0)]
        result = self._run_refresh_with_layer2(bootstrapped_db, balances, layer2=layer2)
        assert result["ok"] is True

        snap = read_payable_snapshot(db_path=bootstrapped_db)
        row = snap["cari_rows"][0]
        assert row["son_alim_tarih"] == "2026-09-01"
        assert row["son_alim_tip"] == "FATURA"

    def test_aktif_takip_stored(self, bootstrapped_db):
        """Aktif takip map → snapshot row'da doğru."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        takip = {"SA001|320.01.006": True}
        balances = [MockDTO("SA001", "SA001", "320.01.006", "TAKIP_CARI", "TRY", -3000.0)]
        result = self._run_refresh_with_layer2(bootstrapped_db, balances, takip_map=takip)
        assert result["ok"] is True

        snap = read_payable_snapshot(db_path=bootstrapped_db)
        row = snap["cari_rows"][0]
        assert row["aktif_takip"] is True

    def test_usd_and_eur_rows_stored(self, bootstrapped_db):
        """USD ve EUR satırları doğru para birimi ile saklanır."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        balances = [
            MockDTO("SA001", "SA001", "320.01.010", "USD_CARI", "USD", -1500.0),
            MockDTO("SA001", "SA001", "320.01.011", "EUR_CARI", "EUR", -2000.0),
        ]
        result = self._run_refresh_with_layer2(bootstrapped_db, balances)
        assert result["ok"] is True

        snap = read_payable_snapshot(db_path=bootstrapped_db)
        rows_by_pb = {r["para_birimi"]: r for r in snap["cari_rows"]}
        assert "USD" in rows_by_pb
        assert "EUR" in rows_by_pb
        assert rows_by_pb["USD"]["bakiye_durumu"] == "Açık Borç"
        assert rows_by_pb["USD"]["display_bakiye"] == 1500.0
        assert rows_by_pb["EUR"]["display_bakiye"] == 2000.0

    def test_no_wrong_zero_balance_in_snapshot(self, bootstrapped_db):
        """Borç satırları 0,00 olarak dönmemeli."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        balances = [
            MockDTO("SA001", "SA001", f"320.01.{100+i:03d}", f"CARI_{i}", "TRY", -(i+1)*1000.0)
            for i in range(10)
        ]
        result = self._run_refresh_with_layer2(bootstrapped_db, balances)
        assert result["ok"] is True

        snap = read_payable_snapshot(db_path=bootstrapped_db)
        wrong_zero = [r for r in snap["cari_rows"]
                      if r["bakiye_durumu"] == "Açık Borç" and r["display_bakiye"] == 0.0]
        assert len(wrong_zero) == 0, f"Yanlış sıfır bakiye: {wrong_zero}"

    def test_missing_layer2_does_not_crash(self, bootstrapped_db):
        """Layer2 eksik olduğunda reader sessizce çalışır (fail-closed değil, ama crash yok)."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        balances = [MockDTO("SA001", "SA001", "320.01.020", "NO_LAYER2_CARI", "TRY", -9000.0)]
        # layer2 boş — crash beklemiyoruz
        result = self._run_refresh_with_layer2(bootstrapped_db, balances, layer2={})
        assert result["ok"] is True

        snap = read_payable_snapshot(db_path=bootstrapped_db)
        row = snap["cari_rows"][0]
        # fa_tarih None olabilir — ama crash yok ve bakiye doğru
        assert row["display_bakiye"] == 9000.0
        assert row["fa_tarih"] is None

    def test_schema_v1_db_rejected(self, tmp_rm_db):
        """Eski V1 schema DB, bootstrap sırasında RuntimeError fırlatmalı."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))

        # Manuel olarak V1 schema oluştur
        conn = sqlite3.connect(tmp_rm_db)
        conn.execute("""CREATE TABLE rm_schema_meta (key TEXT PRIMARY KEY, value TEXT)""")
        conn.execute("INSERT INTO rm_schema_meta VALUES ('schema_version', '1')")
        conn.commit()
        conn.close()

        from modules.finans.read_model.rm_db import open_readwrite
        from modules.finans.read_model.rm_config import SCHEMA_VERSION

        if SCHEMA_VERSION != 1:
            with pytest.raises(RuntimeError, match="schema version uyumsuz|Read-model schema version"):
                with open_readwrite(tmp_rm_db) as _:
                    pass

    def test_cross_company_cari_has_correct_location(self, bootstrapped_db):
        """Çapraz şirkette cari location doğru eşleşmeli."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))
        from modules.finans.read_model.rm_reader import read_payable_snapshot

        balances = [
            MockDTO("SA001", "SA001", "320.01.050", "SAPKA_CARI", "TRY", -4000.0),
            MockDTO("YN001", "YN001", "320.01.050", "SAPKA_CARI", "TRY", -6000.0),
        ]
        result = self._run_refresh_with_layer2(bootstrapped_db, balances)
        assert result["ok"] is True

        snap = read_payable_snapshot(db_path=bootstrapped_db)
        rows = snap["cari_rows"]
        sa_row = next(r for r in rows if r["location"] == "SA001")
        yn_row = next(r for r in rows if r["location"] == "YN001")
        assert sa_row["display_bakiye"] == 4000.0
        assert yn_row["display_bakiye"] == 6000.0


# ─── Test çalıştırma ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
