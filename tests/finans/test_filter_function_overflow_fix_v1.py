# -*- coding: utf-8 -*-
"""CARI_HAREKETLER_FILTER_FUNCTION_AND_OVERFLOW_FIX_V1 — 19 test."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from typing import Any, Dict, List

_THIS = os.path.dirname(__file__)
_APP = os.path.normpath(os.path.join(_THIS, '..', '..', 'app'))
if _APP not in sys.path:
    sys.path.insert(0, _APP)


def _make_payable_temp_db(rows: List[Dict[str, Any]]) -> str:
    fd, path = tempfile.mkstemp(suffix='.sqlite', prefix='test_payable_')
    os.close(fd)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS rm_snapshot_header (
            snapshot_id TEXT PRIMARY KEY,
            location TEXT,
            published_at TEXT,
            row_count INTEGER,
            refresh_state TEXT DEFAULT 'ok',
            last_error TEXT
        );
        CREATE TABLE IF NOT EXISTS rm_snapshot_row (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id TEXT,
            location TEXT,
            cari_kod TEXT,
            cari_adi TEXT,
            para_birimi TEXT,
            bakiye REAL DEFAULT 0,
            net REAL DEFAULT 0,
            bakiye_durumu TEXT,
            aktif_takip INTEGER DEFAULT 0,
            enrichment_json TEXT
        );
    """)
    snap_id = 'test-payable-snap-1'
    conn.execute(
        "INSERT INTO rm_snapshot_header (snapshot_id, location, published_at, row_count) "
        "VALUES (?,?,?,?)",
        (snap_id, 'SA001', '2026-01-01T00:00:00', len(rows))
    )
    for r in rows:
        conn.execute(
            "INSERT INTO rm_snapshot_row "
            "(snapshot_id, location, cari_kod, cari_adi, para_birimi, bakiye, net, "
            "bakiye_durumu, aktif_takip, enrichment_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                snap_id,
                r.get('location', 'SA001'),
                r.get('cari_kod', '320.X'),
                r.get('cari_adi', 'Test'),
                r.get('para_birimi', 'TRY'),
                r.get('bakiye', 0.0),
                r.get('net', 0.0),
                r.get('bakiye_durumu', 'Acik Borc'),
                1 if r.get('aktif_takip') else 0,
                r.get('enrichment_json', json.dumps({'direction': 'PAYABLE'})),
            )
        )
    conn.commit()
    conn.close()
    return path


def _bootstrap_receivable_temp_db(rows: List[Dict[str, Any]]) -> str:
    fd, path = tempfile.mkstemp(suffix='.sqlite', prefix='test_recv_')
    os.close(fd)
    os.environ['ODEME_PLANI_RM_PATH'] = path
    try:
        from modules.finans.read_model.rm_schema import bootstrap_schema
    except ImportError:
        from app.modules.finans.read_model.rm_schema import bootstrap_schema
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    bootstrap_schema(conn)
    conn.close()

    import uuid
    from datetime import datetime, timezone
    snap_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("BEGIN")
    conn.execute(
        "INSERT INTO rm_snapshot(snapshot_id, direction, status, schema_version,"
        " refresh_started_at, published_at, row_count, kpi_json, created_at)"
        " VALUES(?, 'RECEIVABLE', 'ACTIVE', 2, ?, ?, ?, '{}', ?)",
        (snap_id, now, now, len(rows), now)
    )
    for r in rows:
        conn.execute(
            "INSERT INTO rm_snapshot_row("
            "snapshot_id, location, location_label, cari_kod, cari_adi,"
            " para_birimi, borc, alacak, net, canonical_key, bakiye_durumu,"
            " display_bakiye, enrichment_json)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                snap_id,
                r.get("location", "SA001"),
                r.get("location", "SA001"),
                r.get("cari_kod", "120.01.001"),
                r.get("cari_adi", "Test"),
                r.get("para_birimi", "TRY"),
                str(r.get("borc", "0")),
                str(r.get("alacak", "1000")),
                str(r.get("net", "-1000")),
                "{0}:{1}:{2}".format(
                    r.get('location', 'SA001'),
                    r.get('cari_kod', '120.01.001'),
                    r.get('para_birimi', 'TRY')
                ),
                r.get("bakiye_durumu", "Acik Alacak"),
                str(r.get("alacak", "1000")),
                json.dumps({
                    "direction": "RECEIVABLE",
                    "parity_status": "ok",
                    "portfoy_cek_cnt": 0,
                    "aktif_takip": r.get("aktif_takip", False),
                }),
            )
        )
    conn.execute(
        "INSERT INTO rm_pointer(direction, active_snapshot_id, updated_at)"
        " VALUES('RECEIVABLE', ?, ?)"
        " ON CONFLICT(direction) DO UPDATE SET active_snapshot_id=excluded.active_snapshot_id",
        (snap_id, now)
    )
    conn.execute("COMMIT")
    conn.close()
    return path


class TestFilterFunctionOverflowFix(unittest.TestCase):

    def _payable_multigroup(self):
        return [
            {'location': 'SA001', 'cari_kod': '320.1', 'para_birimi': 'TRY', 'bakiye': 100, 'net': 100, 'bakiye_durumu': 'Acik Borc', 'aktif_takip': True},
            {'location': 'SB001', 'cari_kod': '320.2', 'para_birimi': 'TRY', 'bakiye': 200, 'net': 200, 'bakiye_durumu': 'Acik Borc', 'aktif_takip': True},
            {'location': 'SH001', 'cari_kod': '320.3', 'para_birimi': 'TRY', 'bakiye': 300, 'net': 300, 'bakiye_durumu': 'Acik Borc', 'aktif_takip': True},
            {'location': 'SU001', 'cari_kod': '320.4', 'para_birimi': 'TRY', 'bakiye': 400, 'net': 400, 'bakiye_durumu': 'Acik Borc', 'aktif_takip': True},
            {'location': 'SD002', 'cari_kod': '320.5', 'para_birimi': 'TRY', 'bakiye': 500, 'net': 500, 'bakiye_durumu': 'Acik Borc', 'aktif_takip': True},
            {'location': 'YN001', 'cari_kod': '320.99', 'para_birimi': 'TRY', 'bakiye': 999, 'net': 999, 'bakiye_durumu': 'Acik Borc', 'aktif_takip': False},
        ]

    def _recv_multigroup(self):
        return [
            {'location': 'SA001', 'cari_kod': '120.1', 'para_birimi': 'TRY', 'net': '100', 'borc': '100', 'alacak': '0', 'bakiye_durumu': 'Acik Alacak'},
            {'location': 'SB001', 'cari_kod': '120.2', 'para_birimi': 'TRY', 'net': '200', 'borc': '200', 'alacak': '0', 'bakiye_durumu': 'Acik Alacak'},
            {'location': 'SH001', 'cari_kod': '120.3', 'para_birimi': 'TRY', 'net': '300', 'borc': '300', 'alacak': '0', 'bakiye_durumu': 'Acik Alacak'},
            {'location': 'SU001', 'cari_kod': '120.4', 'para_birimi': 'TRY', 'net': '400', 'borc': '400', 'alacak': '0', 'bakiye_durumu': 'Acik Alacak'},
            {'location': 'SD002', 'cari_kod': '120.5', 'para_birimi': 'TRY', 'net': '500', 'borc': '500', 'alacak': '0', 'bakiye_durumu': 'Acik Alacak'},
            {'location': 'YN001', 'cari_kod': '120.99', 'para_birimi': 'TRY', 'net': '999', 'borc': '999', 'alacak': '0', 'bakiye_durumu': 'Acik Alacak'},
        ]

    def _af(self):
        try:
            from modules.finans.read_model.rm_reader import _apply_filters
        except ImportError:
            from app.modules.finans.read_model.rm_reader import _apply_filters
        return _apply_filters

    def _rrs(self):
        try:
            from modules.finans.read_model.rm_receivable_reader import read_receivable_snapshot
        except ImportError:
            from app.modules.finans.read_model.rm_receivable_reader import read_receivable_snapshot
        return read_receivable_snapshot

    # 1. Tedarikci SA001 grubu
    def test_01_supplier_sa001_group_expands(self):
        af = self._af()
        rows = self._payable_multigroup()
        result = af(rows, location='SA001', bakiye_f=None, tedarikci_q=None)
        locs = {r['location'] for r in result}
        for loc in ('SA001', 'SB001', 'SH001', 'SU001', 'SD002'):
            self.assertIn(loc, locs)
        self.assertNotIn('YN001', locs)
        self.assertEqual(len(result), 5)

    # 2. Musteri SA001 grubu
    def test_02_customer_sa001_group_expands(self):
        rrs = self._rrs()
        rows = self._recv_multigroup()
        db_path = _bootstrap_receivable_temp_db(rows)
        try:
            result = rrs(rm_path=db_path, location='SA001', bakiye_f=None)
            locs = {r['location'] for r in result.get('rows', [])}
            for loc in ('SA001', 'SB001', 'SH001', 'SU001', 'SD002'):
                self.assertIn(loc, locs)
            self.assertNotIn('YN001', locs)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    # 3. YN001 includes YN002
    def test_03_yn001_includes_yn002(self):
        af = self._af()
        rows = [
            {'location': 'YN001', 'cari_kod': '320.Y1', 'para_birimi': 'TRY', 'bakiye': 100, 'net': 100, 'bakiye_durumu': 'Acik'},
            {'location': 'YN002', 'cari_kod': '320.Y2', 'para_birimi': 'TRY', 'bakiye': 200, 'net': 200, 'bakiye_durumu': 'Acik'},
            {'location': 'SA001', 'cari_kod': '320.S1', 'para_birimi': 'TRY', 'bakiye': 300, 'net': 300, 'bakiye_durumu': 'Acik'},
        ]
        result = af(rows, location='YN001', bakiye_f=None, tedarikci_q=None)
        locs = {r['location'] for r in result}
        self.assertIn('YN001', locs)
        self.assertIn('YN002', locs)
        self.assertNotIn('SA001', locs)

    # 4. YP001 only own group
    def test_04_yp001_only_own_group(self):
        af = self._af()
        rows = [
            {'location': 'YP001', 'cari_kod': '320.P1', 'para_birimi': 'TRY', 'bakiye': 100, 'net': 100, 'bakiye_durumu': 'Acik'},
            {'location': 'YN001', 'cari_kod': '320.N1', 'para_birimi': 'TRY', 'bakiye': 200, 'net': 200, 'bakiye_durumu': 'Acik'},
        ]
        result = af(rows, location='YP001', bakiye_f=None, tedarikci_q=None)
        locs = {r['location'] for r in result}
        self.assertIn('YP001', locs)
        self.assertNotIn('YN001', locs)

    # 5. Musteri Tum Cariler -> bakiye_f=None
    def test_05_customer_tum_cariler_returns_all(self):
        rrs = self._rrs()
        rows = [
            {'location': 'SA001', 'cari_kod': '120.1', 'para_birimi': 'TRY', 'net': '100', 'borc': '100', 'alacak': '0', 'bakiye_durumu': 'Acik Alacak'},
            {'location': 'SA001', 'cari_kod': '120.2', 'para_birimi': 'TRY', 'net': '0', 'borc': '0', 'alacak': '0', 'bakiye_durumu': 'Yok'},
        ]
        db_path = _bootstrap_receivable_temp_db(rows)
        try:
            result = rrs(rm_path=db_path, bakiye_f=None)
            self.assertEqual(len(result.get('rows', [])), 2)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    # 6. Tedarikci Tum Cariler -> bakiye_f=None
    def test_06_supplier_tum_cariler_returns_all(self):
        af = self._af()
        rows = [
            {'location': 'SA001', 'cari_kod': '320.1', 'para_birimi': 'TRY', 'bakiye': 100, 'net': 100, 'bakiye_durumu': 'Acik'},
            {'location': 'SA001', 'cari_kod': '320.2', 'para_birimi': 'TRY', 'bakiye': 0, 'net': 0, 'bakiye_durumu': 'Yok'},
        ]
        result = af(rows, location=None, bakiye_f=None, tedarikci_q=None)
        self.assertEqual(len(result), 2)

    # 7. Musteri hareketli filter
    def test_07_customer_hareketli_filter(self):
        rrs = self._rrs()
        rows = [
            {'location': 'SA001', 'cari_kod': '120.1', 'para_birimi': 'TRY', 'net': '100', 'borc': '100', 'alacak': '0', 'bakiye_durumu': 'Acik Alacak', 'aktif_takip': False},
            {'location': 'SA001', 'cari_kod': '120.2', 'para_birimi': 'TRY', 'net': '0', 'borc': '0', 'alacak': '0', 'bakiye_durumu': 'Yok', 'aktif_takip': False},
        ]
        db_path = _bootstrap_receivable_temp_db(rows)
        try:
            result = rrs(rm_path=db_path, bakiye_f='hareketli')
            codes = [r['cari_kod'] for r in result.get('rows', [])]
            self.assertIn('120.1', codes)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    # 8. Tedarikci varsayilan hareketli
    def test_08_supplier_default_hareketli(self):
        af = self._af()
        rows = [
            {'location': 'SA001', 'cari_kod': '320.H', 'bakiye': 500, 'net': 500, 'bakiye_durumu': 'Acik Borc', 'aktif_takip': True},
            {'location': 'SA001', 'cari_kod': '320.I', 'bakiye': 0, 'net': 0, 'bakiye_durumu': 'Yok', 'aktif_takip': False},
        ]
        result = af(rows, location=None, bakiye_f='hareketli', tedarikci_q=None)
        codes = [r['cari_kod'] for r in result]
        self.assertIn('320.H', codes)
        self.assertNotIn('320.I', codes)

    # 9. qf mapping routes
    def test_09_qf_mapping_in_routes(self):
        routes_path = os.path.join(_APP, 'modules', 'finans', 'routes.py')
        with open(routes_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn("'acik_borc': 'acik_borc'", content)
        self.assertIn("'hareketli': 'hareketli'", content)
        self.assertIn("'tumu': None", content)

    # 10. Temizle -> hareketli varsayilan
    def test_10_temizle_default_hareketli(self):
        routes_path = os.path.join(_APP, 'modules', 'finans', 'routes.py')
        with open(routes_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn("_bakiye_f = 'hareketli'", content)

    # 11. Musteri pagination total
    def test_11_customer_pagination_has_total(self):
        rrs = self._rrs()
        rows = [{'location': 'SA001', 'cari_kod': '120.1', 'para_birimi': 'TRY', 'net': '100', 'borc': '100', 'alacak': '0', 'bakiye_durumu': 'Acik Alacak'}]
        db_path = _bootstrap_receivable_temp_db(rows)
        try:
            result = rrs(rm_path=db_path, bakiye_f=None)
            pg = result.get('pagination', {})
            total = pg.get('total', pg.get('loc_total'))
            self.assertIsNotNone(total)
            self.assertGreater(total, 0)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    # 12. Tedarikci total_count hesabi
    def test_12_supplier_count_exists(self):
        """_apply_filters len() > 0 ise total_count doğru sayılmalı."""
        af = self._af()
        rows = [
            {'location': 'SA001', 'cari_kod': '320.1', 'para_birimi': 'TRY', 'bakiye': 100, 'net': 100, 'bakiye_durumu': 'Acik Borc', 'aktif_takip': True},
            {'location': 'SA001', 'cari_kod': '320.2', 'para_birimi': 'TRY', 'bakiye': 200, 'net': 200, 'bakiye_durumu': 'Acik Borc', 'aktif_takip': True},
        ]
        result = af(rows, location=None, bakiye_f=None, tedarikci_q=None)
        self.assertGreater(len(result), 0)

    # 13. Sirket + PB combined filter
    def test_13_combined_company_pb_filter(self):
        af = self._af()
        rows = [
            {'location': 'SA001', 'cari_kod': '320.TL', 'para_birimi': 'TRY', 'bakiye': 100, 'net': 100, 'bakiye_durumu': 'Acik'},
            {'location': 'SA001', 'cari_kod': '320.USD', 'para_birimi': 'USD', 'bakiye': 200, 'net': 200, 'bakiye_durumu': 'Acik'},
            {'location': 'YN001', 'cari_kod': '320.TL2', 'para_birimi': 'TRY', 'bakiye': 300, 'net': 300, 'bakiye_durumu': 'Acik'},
        ]
        result = af(rows, location='SA001', bakiye_f=None, tedarikci_q=None, para_birimi='TRY')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['cari_kod'], '320.TL')

    # 14. Tab switch sirket korunuyor
    def test_14_tab_switch_sirket_preserved(self):
        tmpl_path = os.path.join(_APP, 'templates', 'finans', 'odeme_plani.html')
        with open(tmpl_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn("location_filter", content)
        self.assertIn("_tab_href", content)

    # 15. qf tumu -> None routes
    def test_15_qf_tumu_maps_to_none(self):
        routes_path = os.path.join(_APP, 'modules', 'finans', 'routes.py')
        with open(routes_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn("'tumu': None", content)

    # 16. Customer bakiye_f tumu -> None routes
    def test_16_customer_bakiye_f_tumu_to_none(self):
        routes_path = os.path.join(_APP, 'modules', 'finans', 'routes.py')
        with open(routes_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn("_bakiye_f == 'tumu'", content)
        self.assertIn("_bakiye_f = None", content)

    # 17. Currency isolation
    def test_17_currency_isolation(self):
        af = self._af()
        rows = [
            {'location': 'SA001', 'cari_kod': '320.TL', 'para_birimi': 'TRY', 'bakiye': 100, 'net': 100, 'bakiye_durumu': 'Acik'},
            {'location': 'SA001', 'cari_kod': '320.USD', 'para_birimi': 'USD', 'bakiye': 50, 'net': 50, 'bakiye_durumu': 'Acik'},
            {'location': 'SA001', 'cari_kod': '320.EUR', 'para_birimi': 'EUR', 'bakiye': 30, 'net': 30, 'bakiye_durumu': 'Acik'},
        ]
        tl = af(rows, location=None, bakiye_f=None, tedarikci_q=None, para_birimi='TRY')
        self.assertEqual(len(tl), 1)
        self.assertEqual(tl[0]['para_birimi'], 'TRY')
        usd = af(rows, location=None, bakiye_f=None, tedarikci_q=None, para_birimi='USD')
        self.assertEqual(len(usd), 1)
        self.assertEqual(usd[0]['para_birimi'], 'USD')

    # 18. CSS overflow rules
    def test_18_css_overflow_rules(self):
        css_path = os.path.join(_APP, 'templates', 'finans', '_odeme_plani_styles.inc.html')
        with open(css_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('min-width: 0', content)
        self.assertIn('.op-ch-controls', content)

    # 19. Company group import
    def test_19_company_group_import(self):
        try:
            from modules.finans.services.korgun_finance_adapter import COMPANY_FINANCE_LOCATION_MAP
        except ImportError:
            from app.modules.finans.services.korgun_finance_adapter import COMPANY_FINANCE_LOCATION_MAP
        self.assertIn('SA001', COMPANY_FINANCE_LOCATION_MAP)
        self.assertEqual(
            set(COMPANY_FINANCE_LOCATION_MAP['SA001']),
            {'SA001', 'SB001', 'SH001', 'SU001', 'SD002'}
        )
        self.assertIn('YN001', COMPANY_FINANCE_LOCATION_MAP)
        self.assertEqual(set(COMPANY_FINANCE_LOCATION_MAP['YN001']), {'YN001', 'YN002'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
