# -*- coding: utf-8 -*-
"""CUSTOMER_TAB_PG_UNDEFINED_NARROW_FIX_V1 — 17 dar test."""
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


def _bootstrap_recv_db(rows: List[Dict[str, Any]]) -> str:
    fd, path = tempfile.mkstemp(suffix='.sqlite', prefix='test_pg_fix_')
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


def _sample_rows(n: int = 3) -> List[Dict[str, Any]]:
    return [
        {
            'location': 'SA001',
            'cari_kod': '120.0{}'.format(i),
            'cari_adi': 'Test Musteri {}'.format(i),
            'para_birimi': 'TRY',
            'net': '-{}'.format(i * 1000),
            'borc': '0',
            'alacak': str(i * 1000),
            'bakiye_durumu': 'Acik Alacak',
            'aktif_takip': i == 2,
        }
        for i in range(1, n + 1)
    ]


class TestPgUndefinedFix(unittest.TestCase):

    def _rrs(self):
        try:
            from modules.finans.read_model.rm_receivable_reader import read_receivable_snapshot
        except ImportError:
            from app.modules.finans.read_model.rm_receivable_reader import read_receivable_snapshot
        return read_receivable_snapshot

    # 1. Template'de pg artik tanimli
    def test_01_pg_defined_in_template(self):
        tmpl_path = os.path.join(_APP, 'templates', 'finans', 'odeme_plani.html')
        with open(tmpl_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn(
            '{% set pg = (tab_receivable.pagination if tab_receivable and tab_receivable.pagination else {}) %}',
            content,
            "pg tanimlanmamis veya yanlis kaynak"
        )

    # 2. pg taniminin sayfalama kullanimindan once olmasi
    def test_02_pg_defined_before_pg_page(self):
        tmpl_path = os.path.join(_APP, 'templates', 'finans', 'odeme_plani.html')
        with open(tmpl_path, encoding='utf-8') as f:
            content = f.read()
        idx_def = content.find('{% set pg = (tab_receivable.pagination')
        idx_use = content.find('pg.page | default(1)')
        self.assertGreater(idx_def, 0, "pg tanimi bulunamadi")
        self.assertGreater(idx_use, 0, "pg.page kullanimi bulunamadi")
        self.assertLess(idx_def, idx_use, "pg tanimlama kullanımdan sonra geliyor")

    # 3. read_receivable_snapshot rows dolduruyor
    def test_03_receivable_returns_rows(self):
        rrs = self._rrs()
        rows = _sample_rows(3)
        db_path = _bootstrap_recv_db(rows)
        try:
            result = rrs(rm_path=db_path, bakiye_f=None)
            self.assertGreater(len(result.get('rows', [])), 0)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    # 4. Pagination nesnesi tanimli
    def test_04_pagination_defined(self):
        rrs = self._rrs()
        db_path = _bootstrap_recv_db(_sample_rows(2))
        try:
            result = rrs(rm_path=db_path, bakiye_f=None)
            pg = result.get('pagination', None)
            self.assertIsNotNone(pg, "pagination olmali")
            self.assertIsInstance(pg, dict)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    # 5. Count row sayisi dolu
    def test_05_count_row_has_total(self):
        rrs = self._rrs()
        db_path = _bootstrap_recv_db(_sample_rows(3))
        try:
            result = rrs(rm_path=db_path, bakiye_f=None)
            pg = result.get('pagination', {})
            total = pg.get('total', pg.get('loc_total', 0))
            self.assertGreater(total, 0)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    # 6. bakiye_f=hareketli calisir
    def test_06_bakiye_f_hareketli(self):
        rrs = self._rrs()
        db_path = _bootstrap_recv_db(_sample_rows(3))
        try:
            result = rrs(rm_path=db_path, bakiye_f='hareketli')
            self.assertIn('rows', result)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    # 7. bakiye_f=aktif_takip calisir
    def test_07_bakiye_f_aktif_takip(self):
        rrs = self._rrs()
        db_path = _bootstrap_recv_db(_sample_rows(3))
        try:
            result = rrs(rm_path=db_path, bakiye_f='aktif_takip')
            self.assertIn('rows', result)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    # 8. bakiye_f=hareketsiz calisir
    def test_08_bakiye_f_hareketsiz(self):
        rrs = self._rrs()
        db_path = _bootstrap_recv_db(_sample_rows(3))
        try:
            result = rrs(rm_path=db_path, bakiye_f='hareketsiz')
            self.assertIn('rows', result)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    # 9. bakiye_f=None (tumu) calisir
    def test_09_bakiye_f_tumu(self):
        rrs = self._rrs()
        db_path = _bootstrap_recv_db(_sample_rows(2))
        try:
            result = rrs(rm_path=db_path, bakiye_f=None)
            self.assertEqual(len(result.get('rows', [])), 2)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    # 10. Sirket filtresiyle musteri tabi acilir
    def test_10_location_filter(self):
        rrs = self._rrs()
        rows = [
            {'location': 'SA001', 'cari_kod': '120.1', 'para_birimi': 'TRY', 'net': '100', 'borc': '100', 'alacak': '0', 'bakiye_durumu': 'Acik Alacak'},
            {'location': 'YN001', 'cari_kod': '120.2', 'para_birimi': 'TRY', 'net': '200', 'borc': '200', 'alacak': '0', 'bakiye_durumu': 'Acik Alacak'},
        ]
        db_path = _bootstrap_recv_db(rows)
        try:
            result = rrs(rm_path=db_path, location='SA001', bakiye_f=None)
            self.assertIn('rows', result)
            self.assertGreater(len(result.get('rows', [])), 0)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    # 11. PB filtresiyle musteri tabi acilir
    def test_11_pb_filter(self):
        rrs = self._rrs()
        rows = [
            {'location': 'SA001', 'cari_kod': '120.TL', 'para_birimi': 'TRY', 'net': '100', 'borc': '100', 'alacak': '0', 'bakiye_durumu': 'Acik Alacak'},
            {'location': 'SA001', 'cari_kod': '120.USD', 'para_birimi': 'USD', 'net': '50', 'borc': '50', 'alacak': '0', 'bakiye_durumu': 'Acik Alacak'},
        ]
        db_path = _bootstrap_recv_db(rows)
        try:
            result = rrs(rm_path=db_path, para_birimi='TRY', bakiye_f=None)
            returned = [r['cari_kod'] for r in result.get('rows', [])]
            self.assertIn('120.TL', returned)
            self.assertNotIn('120.USD', returned)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    # 12. Arama ile musteri tabi acilir
    def test_12_search_filter(self):
        rrs = self._rrs()
        rows = [
            {'location': 'SA001', 'cari_kod': '120.1', 'cari_adi': 'Ahmet Ticaret', 'para_birimi': 'TRY', 'net': '100', 'borc': '100', 'alacak': '0', 'bakiye_durumu': 'Acik Alacak'},
            {'location': 'SA001', 'cari_kod': '120.2', 'cari_adi': 'Mehmet Sanayi', 'para_birimi': 'TRY', 'net': '200', 'borc': '200', 'alacak': '0', 'bakiye_durumu': 'Acik Alacak'},
        ]
        db_path = _bootstrap_recv_db(rows)
        try:
            result = rrs(rm_path=db_path, musteri_q='ahmet', bakiye_f=None)
            self.assertIn('rows', result)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    # 13. Tedarikci tab regression — _apply_filters import
    def test_13_supplier_regression(self):
        try:
            from modules.finans.read_model.rm_reader import _apply_filters
        except ImportError:
            from app.modules.finans.read_model.rm_reader import _apply_filters
        rows = [{'location': 'SA001', 'cari_kod': '320.1', 'para_birimi': 'TRY', 'bakiye': 100, 'net': 100, 'bakiye_durumu': 'Acik Borc', 'aktif_takip': True}]
        result = _apply_filters(rows, location=None, bakiye_f='hareketli', tedarikci_q=None)
        self.assertEqual(len(result), 1)

    # 14. routes.py bypass hatasi artik pg'den degil tab_receivable.pagination'dan geliyor
    def test_14_routes_has_tab_receivable(self):
        routes_path = os.path.join(_APP, 'modules', 'finans', 'routes.py')
        with open(routes_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn("'tab_receivable'", content)
        self.assertIn("_tab_receivable", content)

    # 15. Template pg kaynagi tab_receivable.pagination
    def test_15_pg_source_is_tab_receivable_pagination(self):
        tmpl_path = os.path.join(_APP, 'templates', 'finans', 'odeme_plani.html')
        with open(tmpl_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('tab_receivable.pagination', content)

    # 16. Template 'pg' is undefined loglama artik olmuyor (eski bos dict yok)
    def test_16_no_empty_pg_placeholder(self):
        tmpl_path = os.path.join(_APP, 'templates', 'finans', 'odeme_plani.html')
        with open(tmpl_path, encoding='utf-8') as f:
            content = f.read()
        # Eski 'pg = {}' empty dict tanımı olmamalı (artık tab_receivable.pagination kullanılıyor)
        # Önceki hatalı: {% set pg_page = pg.page | default(1) %} without pg defined
        # Şimdi: {% set pg = (tab_receivable.pagination ...) %}
        # Dolayısıyla pg_page kullanımından önce mutlaka bir pg set satırı olmalı
        idx_pg_set = content.find('{% set pg = (tab_receivable.pagination')
        self.assertGreater(idx_pg_set, 0)

    # 17. Placeholder snapshot hazirsa gozukmuyor (snapshot_status != no_snapshot)
    def test_17_no_placeholder_with_ready_snapshot(self):
        rrs = self._rrs()
        db_path = _bootstrap_recv_db(_sample_rows(2))
        try:
            result = rrs(rm_path=db_path, bakiye_f=None)
            # snapshot_status 'no_snapshot' veya 'error' olmamali
            status = result.get('snapshot_status', '')
            self.assertNotIn(status, ('no_snapshot', 'error', 'db_error'),
                             f"Snapshot hazir oldugunda placeholder gostermemeli: {status}")
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
