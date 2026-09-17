# -*- coding: utf-8 -*-
"""
CPS_FINANS_CUSTOMER_LEDGER_DATA_NARROW_FIX_V1 — direction regression tests.

Canonical 120.* rule: net = Borc - Alacak
  net > 0  → Açık Alacak (müşteri borçlu)
  net < 0  → Müşteri Avansı
  net = 0  → Bakiye Yok
  display_bakiye = abs(net) for non-zero
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))


def _make_temp_rm_db() -> str:
    fd, path = tempfile.mkstemp(suffix='.sqlite', prefix='test_dir_fix_')
    os.close(fd)
    from modules.finans.read_model.rm_schema import bootstrap_schema
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    bootstrap_schema(conn)
    conn.close()
    return path


def _insert_row(rm_path, *, net, borc, alacak, bakiye_durumu, display_bakiye):
    import uuid
    from datetime import datetime, timezone
    snap_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    conn = sqlite3.connect(rm_path, isolation_level=None)
    conn.execute("BEGIN")
    conn.execute("""
        INSERT INTO rm_snapshot(snapshot_id, direction, status, schema_version,
                                refresh_started_at, published_at, row_count, kpi_json, created_at)
        VALUES(?, 'RECEIVABLE', 'ACTIVE', 2, ?, ?, 1, '{}', ?)
    """, (snap_id, now, now, now))
    conn.execute("""
        INSERT INTO rm_snapshot_row(
            snapshot_id, location, location_label, cari_kod, cari_adi,
            para_birimi, borc, alacak, net, canonical_key, bakiye_durumu,
            display_bakiye, enrichment_json
        ) VALUES(?, 'SA001', 'SA001', '120.01.001', 'Test', 'TRY',
                 ?, ?, ?, 'SA001:120.01.001:TRY', ?, ?,
                 '{"direction":"RECEIVABLE","parity_status":"ok","portfoy_cek_cnt":0}')
    """, (snap_id, borc, alacak, net, bakiye_durumu, display_bakiye))
    conn.execute("UPDATE rm_pointer SET active_snapshot_id=?, last_success_id=? WHERE direction='RECEIVABLE'",
                 (snap_id, snap_id))
    conn.execute("COMMIT")
    conn.close()


class TestCanonicalDirectionReader(unittest.TestCase):
    def setUp(self):
        self._tmp = _make_temp_rm_db()

    def tearDown(self):
        os.unlink(self._tmp)

    def test_positive_net_open_receivable(self):
        _insert_row(self._tmp, net="5000", borc="5000", alacak="0",
                    bakiye_durumu="Açık Alacak", display_bakiye="5000")
        from modules.finans.read_model.rm_receivable_reader import read_receivable_snapshot
        row = read_receivable_snapshot(self._tmp)["rows"][0]
        self.assertEqual(row["bakiye_durumu"], "Açık Alacak")
        self.assertEqual(float(row["net"]), 5000.0)
        self.assertEqual(float(row["open_receivable"]), 5000.0)
        self.assertEqual(float(row["borc"]), 5000.0)
        self.assertEqual(float(row["alacak"]), 0.0)

    def test_negative_net_customer_advance(self):
        _insert_row(self._tmp, net="-2000", borc="0", alacak="2000",
                    bakiye_durumu="Müşteri Avansı", display_bakiye="2000")
        from modules.finans.read_model.rm_receivable_reader import read_receivable_snapshot
        row = read_receivable_snapshot(self._tmp)["rows"][0]
        self.assertEqual(row["bakiye_durumu"], "Müşteri Avansı")
        self.assertEqual(float(row["net"]), -2000.0)
        self.assertEqual(float(row["open_receivable"]), 2000.0)

    def test_zero_net(self):
        _insert_row(self._tmp, net="0", borc="0", alacak="0",
                    bakiye_durumu="Bakiye Yok", display_bakiye="0")
        from modules.finans.read_model.rm_receivable_reader import read_receivable_snapshot
        row = read_receivable_snapshot(self._tmp)["rows"][0]
        self.assertEqual(row["bakiye_durumu"], "Bakiye Yok")
        self.assertEqual(float(row["open_receivable"]), 0.0)

    def test_kpi_separates_receivable_and_advance(self):
        import uuid
        from datetime import datetime, timezone
        snap_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        conn = sqlite3.connect(self._tmp, isolation_level=None)
        conn.execute("BEGIN")
        conn.execute("""
            INSERT INTO rm_snapshot(snapshot_id, direction, status, schema_version,
                                    refresh_started_at, published_at, row_count, kpi_json, created_at)
            VALUES(?, 'RECEIVABLE', 'ACTIVE', 2, ?, ?, 2, '{}', ?)
        """, (snap_id, now, now, now))
        for ck, net, borc, alacak, durum, disp in [
            ("120.01.001", "3000", "3000", "0", "Açık Alacak", "3000"),
            ("120.01.002", "-1000", "0", "1000", "Müşteri Avansı", "1000"),
        ]:
            conn.execute("""
                INSERT INTO rm_snapshot_row(
                    snapshot_id, location, location_label, cari_kod, cari_adi,
                    para_birimi, borc, alacak, net, canonical_key, bakiye_durumu,
                    display_bakiye, enrichment_json
                ) VALUES(?, 'SA001', 'SA001', ?, 'T', 'TRY', ?, ?, ?, ?, ?, ?,
                         '{"direction":"RECEIVABLE","parity_status":"ok","portfoy_cek_cnt":0}')
            """, (snap_id, ck, borc, alacak, net, f"SA001:{ck}:TRY", durum, disp))
        conn.execute("UPDATE rm_pointer SET active_snapshot_id=?, last_success_id=? WHERE direction='RECEIVABLE'",
                     (snap_id, snap_id))
        conn.execute("COMMIT")
        conn.close()
        from modules.finans.read_model.rm_receivable_reader import read_receivable_snapshot
        kpis = read_receivable_snapshot(self._tmp)["kpis"]
        self.assertEqual(float(kpis["toplam_acik_alacak"]["TRY"]), 3000.0)
        self.assertEqual(float(kpis["toplam_fazla_odeme"]["TRY"]), 1000.0)

    def test_320_not_in_receivable(self):
        import uuid
        from datetime import datetime, timezone
        snap_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        conn = sqlite3.connect(self._tmp, isolation_level=None)
        conn.execute("BEGIN")
        conn.execute("""
            INSERT INTO rm_snapshot(snapshot_id, direction, status, schema_version,
                                    refresh_started_at, published_at, row_count, kpi_json, created_at)
            VALUES(?, 'RECEIVABLE', 'ACTIVE', 2, ?, ?, 1, '{}', ?)
        """, (snap_id, now, now, now))
        conn.execute("""
            INSERT INTO rm_snapshot_row(
                snapshot_id, location, location_label, cari_kod, cari_adi,
                para_birimi, borc, alacak, net, canonical_key, bakiye_durumu,
                display_bakiye, enrichment_json
            ) VALUES(?, 'SA001', 'SA001', '320.01.001', 'Tedarikçi', 'TRY',
                     '0', '5000', '-5000', 'SA001:320.01.001:TRY', 'Açık Borç', '5000',
                     '{"direction":"PAYABLE","parity_status":"ok","portfoy_cek_cnt":0}')
        """, (snap_id,))
        conn.execute("UPDATE rm_pointer SET active_snapshot_id=?, last_success_id=? WHERE direction='RECEIVABLE'",
                     (snap_id, snap_id))
        conn.execute("COMMIT")
        conn.close()
        from modules.finans.read_model.rm_receivable_reader import read_receivable_snapshot
        data = read_receivable_snapshot(self._tmp)
        self.assertEqual(len(data["rows"]), 0)


class TestRefreshDirectionLogic(unittest.TestCase):
    """Refresh loop direction without Korgün."""

    def _direction(self, net_d: Decimal):
        if net_d > 0:
            bakiye_durumu = "Açık Alacak"
        elif net_d < 0:
            bakiye_durumu = "Müşteri Avansı"
        else:
            bakiye_durumu = "Bakiye Yok"
        display_bakiye = str(abs(net_d)) if net_d != 0 else "0"
        return bakiye_durumu, display_bakiye

    def test_refresh_positive(self):
        d, amt = self._direction(Decimal("3096000"))
        self.assertEqual(d, "Açık Alacak")
        self.assertEqual(amt, "3096000")

    def test_refresh_negative(self):
        d, amt = self._direction(Decimal("-1"))
        self.assertEqual(d, "Müşteri Avansı")
        self.assertEqual(amt, "1")

    def test_fistip_mapping(self):
        from modules.finans.read_model.rm_receivable_reader import _FISTIP_TO_YONTEM
        self.assertEqual(_FISTIP_TO_YONTEM["NT"], "Nakit")
        self.assertEqual(_FISTIP_TO_YONTEM["AD"], "Dekont")
        self.assertNotIn("FATURA", _FISTIP_TO_YONTEM.values())


class TestCustomerSummaryService(unittest.TestCase):
    @patch("modules.finans.read_model.rm_snapshot_lookup.lookup_receivable_row")
    def test_summary_open_receivable_positive_net(self, mock_lookup):
        mock_lookup.return_value = {
            "row": {
                "net": "5000",
                "borc": "5000",
                "alacak": "0",
                "bakiye_durumu": "Açık Alacak",
                "location": "SA001",
            },
            "enrichment": {},
            "snapshot_id": "test-snap",
            "published_at": "2026-01-01T00:00:00+00:00",
        }
        from modules.finans.services.musteri_hareket_service import get_customer_summary
        s = get_customer_summary("120.01.001", "SA001", "TRY")
        self.assertTrue(s["ok"])
        self.assertEqual(s["open_receivable"], "5000")
        self.assertEqual(s["customer_overpayment"], "0")

    @patch("modules.finans.read_model.rm_snapshot_lookup.lookup_receivable_row")
    def test_summary_advance_negative_net(self, mock_lookup):
        mock_lookup.return_value = {
            "row": {
                "net": "-1",
                "borc": "0",
                "alacak": "1",
                "bakiye_durumu": "Müşteri Avansı",
                "location": "SA001",
            },
            "enrichment": {},
            "snapshot_id": "test-snap",
            "published_at": "2026-01-01T00:00:00+00:00",
        }
        from modules.finans.services.musteri_hareket_service import get_customer_summary
        s = get_customer_summary("120.01.001", "SA001", "TRY")
        self.assertTrue(s["ok"])
        self.assertEqual(s["open_receivable"], "0")
        self.assertEqual(s["customer_overpayment"], "1")


class TestLayer2GroupLocation(unittest.TestCase):
    def test_resolve_finance_group_includes_sh001(self):
        from modules.finans.read_model.rm_receivable_reader import _resolve_finance_group
        grp = _resolve_finance_group("SA001")
        self.assertIn("SH001", grp)
        self.assertIn("SA001", grp)


if __name__ == "__main__":
    unittest.main()
