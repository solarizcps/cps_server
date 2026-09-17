# -*- coding: utf-8 -*-
"""OET V2 Trendyol Operasyon Kuyruk Pariteleri — Regression Testleri (offline, no real API)"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

APP = os.path.join(os.path.dirname(__file__), '..', 'app')
sys.path.insert(0, os.path.abspath(APP))
os.environ.setdefault('API_MODE', 'mock')
os.environ.setdefault('API_WRITE_ENABLED', 'false')

TZ = timezone(timedelta(hours=3))

# ── Minimal mock orders ─────────────────────────────────────────────────────

def _make_order(pkg_id, status, deadline_offset_s, qty=2, name='Test Ürün', barcode='BAR001',
                order_date_offset_s=-86400):
    """deadline_offset_s: now+X. Negatif → gecikmiş/geçmiş"""
    now_ms = int(time.time() * 1000)
    return {
        'id': str(pkg_id),
        'orderNumber': f'ORD{pkg_id}',
        'status': status,
        'orderDate': now_ms + order_date_offset_s * 1000,
        'agreedDeliveryDate': now_ms + deadline_offset_s * 1000,
        'cargoProviderName': 'MNG',
        'lines': [
            {
                'barcode': barcode,
                'productName': name,
                'productMainId': 'MDL001',
                'productColor': 'Siyah',
                'productSize': '40',
                'quantity': qty,
                'merchantSku': 'SKU001',
            }
        ],
    }


class TestStatusMapping(unittest.TestCase):
    """KAPI 1 — Trendyol status → UI durum eşlemesi."""

    def setUp(self):
        from modules.online_eticaret import routes as r
        self.routes = r

    def test_created_maps_to_yeni(self):
        durum, renk, _ = self.routes._trendyol_status_to_ui('Created', '')
        self.assertEqual(durum, 'YENİ')

    def test_picking_maps_to_toplaniyor(self):
        durum, renk, _ = self.routes._trendyol_status_to_ui('Picking', '')
        self.assertEqual(durum, 'TOPLANIYOR')

    def test_unknown_status_fallback(self):
        durum, _, _ = self.routes._trendyol_status_to_ui('Shipped', '')
        self.assertEqual(durum, 'Shipped')


class TestOpenOrdersFilter(unittest.TestCase):
    """KAPI 2 — Açık Siparişler filtresi geriye dönük siparişleri getirir."""

    def setUp(self):
        from modules.online_eticaret import routes as r
        self.routes = r

    def test_open_filter_ms_range_30_days(self):
        start_ms, end_ms = self.routes._ms_aralik_for_filter('open')
        delta_days = (end_ms - start_ms) / (1000 * 86400)
        self.assertGreaterEqual(delta_days, 28)   # ~30 gün
        self.assertLessEqual(delta_days, 32)

    def test_yesterday_order_visible_in_open_not_in_today(self):
        """Önceki günkü paket Açık Siparişler penceresinde ama Bugün penceresinde değil."""
        from modules.online_eticaret import routes as r
        now = datetime.now(TZ)
        yesterday_ms = int((now - timedelta(days=1)).timestamp() * 1000)
        today_start_ms = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        open_start_ms, _ = r._ms_aralik_for_filter('open')
        self.assertLess(open_start_ms, yesterday_ms)
        self.assertGreater(today_start_ms, yesterday_ms - 1)

    def test_default_filter_is_open(self):
        from modules.online_eticaret.routes import DEFAULT_DATE_FILTER, DATE_FILTER_OPEN
        self.assertEqual(DEFAULT_DATE_FILTER, DATE_FILTER_OPEN)


class TestKpiStatusCounts(unittest.TestCase):
    """KAPI 3 — dashboard_stats Created/Picking ayrımı."""

    def setUp(self):
        from modules.online_eticaret.excel_export import dashboard_stats
        self.dashboard_stats = dashboard_stats

    def test_created_counted_separately(self):
        orders = [_make_order(1, 'Created', 3600)]
        stats = self.dashboard_stats(orders)
        self.assertEqual(stats['created_orders'], 1)
        self.assertEqual(stats['picking_orders'], 0)

    def test_picking_counted_separately(self):
        orders = [_make_order(2, 'Picking', 3600)]
        stats = self.dashboard_stats(orders)
        self.assertEqual(stats['picking_orders'], 1)
        self.assertEqual(stats['created_orders'], 0)

    def test_created_qty_correct(self):
        orders = [_make_order(3, 'Created', 3600, qty=5)]
        stats = self.dashboard_stats(orders)
        self.assertEqual(stats['created_qty'], 5)

    def test_picking_qty_correct(self):
        orders = [_make_order(4, 'Picking', 3600, qty=3)]
        stats = self.dashboard_stats(orders)
        self.assertEqual(stats['picking_qty'], 3)


class TestCountSemantics(unittest.TestCase):
    """KAPI 4 — Paket / line / quantity ayrımı."""

    def setUp(self):
        from modules.online_eticaret.excel_export import dashboard_stats
        self.dashboard_stats = dashboard_stats

    def _make_multi_line_order(self, pkg_id, n_lines=3, qty_each=2):
        now_ms = int(time.time() * 1000)
        return {
            'id': str(pkg_id),
            'orderNumber': f'ORD{pkg_id}',
            'status': 'Created',
            'orderDate': now_ms,
            'agreedDeliveryDate': now_ms + 3600 * 1000,
            'cargoProviderName': 'MNG',
            'lines': [
                {'barcode': f'BAR{i}', 'productName': f'Ürün {i}', 'productMainId': f'MDL{i}',
                 'productColor': 'Siyah', 'productSize': '40', 'quantity': qty_each}
                for i in range(n_lines)
            ],
        }

    def test_package_line_quantity_separated(self):
        orders = [self._make_multi_line_order(1, n_lines=3, qty_each=2)]
        stats = self.dashboard_stats(orders)
        self.assertEqual(stats['total_orders'], 1)      # paket
        self.assertEqual(stats['total_lines'], 3)       # line
        self.assertEqual(stats['total_qty'], 6)         # quantity


class TestKpiPillParity(unittest.TestCase):
    """KAPI 3 — KPI kartı ve pill aynı `aciliyet` alanını kullanır."""

    def setUp(self):
        from modules.online_eticaret import routes as r
        self.routes = r

    def test_acil_24h_uses_aciliyet_1(self):
        """aciliyet=1 → Kalan: X saat (24h içinde) → pill ACIL24H eşleşmeli."""
        gecikme = 'Kalan: 3 saat 20 dk'
        acilyiet = self.routes._aciliyet(gecikme)
        self.assertEqual(acilyiet, 1)

    def test_gecikti_uses_aciliyet_0(self):
        gecikme = 'GECİKTİ (2 saat 10 dk)'
        acilyiet = self.routes._aciliyet(gecikme)
        self.assertEqual(acilyiet, 0)

    def test_dashboard_urgent_equals_aciliyet_1_count(self):
        """dashboard_stats.urgent → operasyon listesindeki aciliyet==1 sayısıyla uyumlu."""
        from modules.online_eticaret.excel_export import dashboard_stats, orders_to_rows
        now_ms = int(time.time() * 1000)
        orders_acil = [_make_order(10, 'Created', 3600)]    # 1 saat → acil
        orders_uzak = [_make_order(11, 'Created', 86400 * 5)]  # 5 gün → uzak
        all_orders = orders_acil + orders_uzak
        stats = dashboard_stats(all_orders, {}, now_ms)
        rows = orders_to_rows(all_orders, 'Solariz', {}, now_ms)
        acil_row_count = sum(1 for r in rows if self.routes._aciliyet(r[2]) == 1)
        self.assertEqual(stats['urgent'], acil_row_count)


class TestMultiItemPackageHeader(unittest.TestCase):
    """KAPI 5 — Çok ürünlü paketin `items[0]` dolu."""

    def setUp(self):
        from modules.online_eticaret import routes as r
        self.routes = r

    def test_multi_item_group_has_items(self):
        from modules.online_eticaret.excel_export import orders_to_rows
        now_ms = int(time.time() * 1000)
        order = {
            'id': '9901',
            'orderNumber': 'ORD9901',
            'status': 'Created',
            'orderDate': now_ms,
            'agreedDeliveryDate': now_ms + 86400000,
            'cargoProviderName': 'MNG',
            'lines': [
                {'barcode': 'B1', 'productName': 'Ürün A', 'productMainId': 'M1',
                 'productColor': 'Kırmızı', 'productSize': '38', 'quantity': 1},
                {'barcode': 'B2', 'productName': 'Ürün B', 'productMainId': 'M2',
                 'productColor': 'Mavi', 'productSize': '40', 'quantity': 2},
            ],
        }
        rows = orders_to_rows([order], 'Solariz', {}, now_ms)
        pkg_ms = {order['id']: order['orderDate']}
        rows_by_store = {'Solariz': rows}
        op_list = self.routes._build_operasyon_listesi(rows_by_store, {}, pkg_ms)
        paketler = self.routes._group_paketler(op_list)
        self.assertEqual(len(paketler), 1)
        pkg = paketler[0]
        self.assertEqual(pkg['kalem'], 2)
        self.assertTrue(len(pkg['urunler']) == 2)
        # items[0] dolu olmalı (template header'ı için)
        first = pkg['urunler'][0]
        self.assertTrue(first.get('urun'), 'items[0].urun boş olmamalı')


class TestStoreIsolation(unittest.TestCase):
    """KAPI 8 — Solariz/Epona karışmamalı."""

    def setUp(self):
        from modules.online_eticaret import routes as r
        self.routes = r

    def test_dedupe_keeps_stores_separate(self):
        magaza_orders = {
            'Solariz': [_make_order(1, 'Created', 3600)],
            'Epona':   [_make_order(1, 'Created', 3600)],  # aynı pkg_id farklı mağaza
        }
        result = self.routes._dedupe_orders_by_package(magaza_orders)
        self.assertIn('Solariz', result)
        self.assertIn('Epona', result)
        self.assertEqual(len(result['Solariz']), 1)
        self.assertEqual(len(result['Epona']), 1)


class TestWriteSafety(unittest.TestCase):
    """KAPI 9/11 — Yazma endpoint ve write guard."""

    def test_no_write_methods_in_routes(self):
        import re
        path = os.path.join(APP, 'modules', 'online_eticaret', 'routes.py')
        src = open(path, encoding='utf-8').read()
        # methods=['POST'...] içeren route decorator olmamalı
        hits = re.findall(
            r"@online_eticaret_bp\.route\([^)]*methods\s*=\s*\[[^\]]*(POST|PUT|PATCH|DELETE)",
            src, re.I
        )
        self.assertEqual(len(hits), 0, f"Yazma route bulundu: {hits}")

    def test_api_write_default_false(self):
        path = os.path.join(APP, 'modules', 'online_eticaret', 'routes.py')
        src = open(path, encoding='utf-8').read()
        self.assertIn("API_WRITE_ENABLED', 'false'", src)


class TestImageEnrichmentNonBlocking(unittest.TestCase):
    """KAPI 6/12 — Görsel başarısız olsa da paket görünür."""

    def setUp(self):
        from modules.online_eticaret import routes as r
        self.routes = r

    def test_missing_image_does_not_hide_package(self):
        from modules.online_eticaret.excel_export import orders_to_rows
        now_ms = int(time.time() * 1000)
        orders = [_make_order(5, 'Created', 3600, barcode='NOIMG')]
        rows = orders_to_rows(orders, 'Solariz', {}, now_ms)
        rows_by_store = {'Solariz': rows}
        # image_map boş → gorsel boş ama kayıt görünmeli
        op_list = self.routes._build_operasyon_listesi(rows_by_store, {})
        self.assertEqual(len(op_list), 1)
        self.assertEqual(op_list[0].get('gorsel'), '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
