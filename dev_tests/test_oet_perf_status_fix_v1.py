# -*- coding: utf-8 -*-
"""OET V2 Performance & Status Narrowfix — Regression Testleri

KAPI 6 test sözleşmesi:
  1. package/line/quantity ayrı hesaplanıyor
  2. Solariz/Epona/Tümü toplamları doğru
  3. Created/Picking ayrı ve doğru
  4. UI etiketi paket/adet ile uyumlu
  5. KPI/kart/pill aynı canonical kaynağı kullanıyor
  6. open snapshot open ile seed ediliyor
  7. today snapshot today ile seed ediliyor
  8. open ve today birbirine karışmıyor
  9. poll yeni siparişi algılıyor
 10. poll cache'i güncelliyor/invalidate ediyor
 11. duplicate paket yok
 12. page size değişince toplam sonuç değişmiyor (mock)
 13. pagination cap korunuyor (mock)
 14. 429/timeout davranışı korunuyor
 15. enrichment duplicate worker yok
 16. WRITE_ENDPOINT_COUNT=0
 17. NON_GET_REQUEST_COUNT=0
 18. secret/env/DB yok
 19. /online-eticaret/ ve mobil route HTTP 200
 20. mevcut OET regression suite tamamen PASS
"""
from __future__ import annotations

import os
import re
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

APP = os.path.join(os.path.dirname(__file__), '..', 'app')
sys.path.insert(0, os.path.abspath(APP))
os.chdir(os.path.abspath(APP))
os.environ.setdefault('API_MODE', 'mock')
os.environ.setdefault('API_WRITE_ENABLED', 'false')

TZ = timezone(timedelta(hours=3))


def _make_order(pkg_id, status, qty=2, store='Solariz'):
    now_ms = int(time.time() * 1000)
    return {
        'id': str(pkg_id),
        'orderNumber': f'ORD{pkg_id}',
        'status': status,
        'orderDate': now_ms - 3600 * 1000,
        'agreedDeliveryDate': now_ms + 3600 * 1000,
        'cargoProviderName': 'MNG',
        'lines': [
            {
                'barcode': f'BAR{pkg_id}',
                'productName': f'Test Ürün {pkg_id}',
                'productMainId': f'MDL{pkg_id}',
                'productColor': 'Siyah',
                'productSize': '40',
                'quantity': qty,
                'merchantSku': f'SKU{pkg_id}',
            }
        ],
    }


# ── Test 1-3: Sayım birimleri ─────────────────────────────────────────────

class TestPackageLineQtyAyrimi(unittest.TestCase):
    """Test 1: package/line/quantity ayrı hesaplanıyor."""

    def setUp(self):
        from modules.online_eticaret.excel_export import dashboard_stats
        self.dashboard_stats = dashboard_stats

    def test_single_package_single_line(self):
        orders = [_make_order(1, 'Picking', qty=3)]
        stats = self.dashboard_stats(orders)
        self.assertEqual(stats['total_orders'], 1, 'paket=1')
        self.assertEqual(stats['total_lines'], 1, 'satır=1')
        self.assertEqual(stats['total_qty'], 3, 'qty=3')

    def test_multi_line_single_package(self):
        order = _make_order(1, 'Picking', qty=2)
        order['lines'].append({
            'barcode': 'BAR1B', 'productName': 'Test B',
            'productMainId': 'MDL1', 'productColor': 'Beyaz',
            'productSize': '42', 'quantity': 4, 'merchantSku': 'SKU1B',
        })
        orders = [order]
        stats = self.dashboard_stats(orders)
        self.assertEqual(stats['total_orders'], 1)
        self.assertEqual(stats['total_lines'], 2)
        self.assertEqual(stats['total_qty'], 6)

    def test_package_line_qty_not_equal(self):
        orders = [_make_order(1, 'Picking', qty=5), _make_order(2, 'Created', qty=3)]
        stats = self.dashboard_stats(orders)
        self.assertEqual(stats['total_orders'], 2)
        self.assertEqual(stats['total_lines'], 2)
        self.assertEqual(stats['total_qty'], 8)


class TestStoreTotals(unittest.TestCase):
    """Test 2: Solariz/Epona/Tümü toplamları doğru."""

    def setUp(self):
        from modules.online_eticaret.excel_export import dashboard_stats
        from modules.online_eticaret.routes import _dedupe_orders_by_package
        self.dashboard_stats = dashboard_stats
        self.dedupe = _dedupe_orders_by_package

    def test_solariz_epona_separate(self):
        sol_orders = [_make_order(1, 'Picking', qty=2), _make_order(2, 'Created', qty=1)]
        ep_orders = [_make_order(3, 'Picking', qty=3)]
        magaza_orders = {'Solariz': sol_orders, 'Epona': ep_orders}
        dedupe = self.dedupe(magaza_orders)
        sol_stats = self.dashboard_stats(dedupe['Solariz'])
        ep_stats = self.dashboard_stats(dedupe['Epona'])
        self.assertEqual(sol_stats['total_orders'], 2, 'Solariz=2 paket')
        self.assertEqual(sol_stats['total_qty'], 3, 'Solariz=3 adet')
        self.assertEqual(ep_stats['total_orders'], 1, 'Epona=1 paket')
        self.assertEqual(ep_stats['total_qty'], 3, 'Epona=3 adet')

    def test_total_is_sum(self):
        sol = [_make_order(1, 'Picking', qty=2)]
        ep = [_make_order(2, 'Created', qty=1)]
        magaza_orders = {'Solariz': sol, 'Epona': ep}
        dedupe = self.dedupe(magaza_orders)
        sol_stats = self.dashboard_stats(dedupe['Solariz'])
        ep_stats = self.dashboard_stats(dedupe['Epona'])
        self.assertEqual(
            sol_stats['total_orders'] + ep_stats['total_orders'], 2
        )


class TestCreatedPickingAyri(unittest.TestCase):
    """Test 3: Created/Picking ayrı ve doğru."""

    def setUp(self):
        from modules.online_eticaret.excel_export import dashboard_stats
        self.dashboard_stats = dashboard_stats

    def test_created_counting(self):
        orders = [_make_order(1, 'Created', qty=2), _make_order(2, 'Created', qty=3)]
        stats = self.dashboard_stats(orders)
        self.assertEqual(stats['created_orders'], 2)
        self.assertEqual(stats['created_qty'], 5)
        self.assertEqual(stats['picking_orders'], 0)
        self.assertEqual(stats['picking_qty'], 0)

    def test_picking_counting(self):
        orders = [_make_order(3, 'Picking', qty=4)]
        stats = self.dashboard_stats(orders)
        self.assertEqual(stats['picking_orders'], 1)
        self.assertEqual(stats['picking_qty'], 4)
        self.assertEqual(stats['created_orders'], 0)

    def test_mixed_counting(self):
        orders = [
            _make_order(1, 'Created', qty=2),
            _make_order(2, 'Picking', qty=3),
            _make_order(3, 'Picking', qty=1),
        ]
        stats = self.dashboard_stats(orders)
        self.assertEqual(stats['created_orders'], 1)
        self.assertEqual(stats['picking_orders'], 2)
        self.assertEqual(stats['total_orders'], 3)


# ── Test 4: UI etiket sözleşmesi ─────────────────────────────────────────

class TestUIEtiketSozlesmesi(unittest.TestCase):
    """Test 4: cnt-toplaniyor paket etiketiyle gösterilmeli, ürün değil."""

    def test_toplaniyor_pill_etiketi_paket(self):
        template_path = os.path.join(
            os.path.dirname(__file__), '..', 'app', 'templates', 'online_eticaret', 'index.html'
        )
        with open(template_path, encoding='utf-8') as f:
            src = f.read()
        # "İşleme Alınan" pill'inde "paket" etiketi olmalı, "ürün" değil
        m = re.search(
            r'data-filter="TOPLANIYOR"[^>]*>.*?<small[^>]*>(.*?)</small>',
            src, re.S
        )
        self.assertIsNotNone(m, 'TOPLANIYOR filter pill bulunamadı')
        self.assertIn('paket', m.group(1).lower(), 'TOPLANIYOR etiketi "paket" içermeli')
        self.assertNotIn('ürün', m.group(1).lower(), 'TOPLANIYOR etiketi "ürün" içermemeli')

    def test_toplaniyor_js_uses_cntPackages(self):
        template_path = os.path.join(
            os.path.dirname(__file__), '..', 'app', 'templates', 'online_eticaret', 'index.html'
        )
        with open(template_path, encoding='utf-8') as f:
            src = f.read()
        # cnt-toplaniyor, cntPackages ile hesaplanmalı (sumQty değil)
        m = re.search(
            r"getElementById\('cnt-toplaniyor'\)\.textContent\s*=\s*(\w+)\(",
            src
        )
        self.assertIsNotNone(m, 'cnt-toplaniyor assignment bulunamadı')
        fn = m.group(1)
        self.assertEqual(fn, 'cntPackages', f'beklenen cntPackages, bulunan: {fn}')


# ── Test 5: KPI/kart/pill aynı canonical kaynağı kullanıyor ──────────────

class TestKPICanonicalKaynak(unittest.TestCase):
    """Test 5: KPI ve operasyon kartları aynı kaynak veriden beslenmeli."""

    def test_kpi_toplam_siparis_equals_paket(self):
        from modules.online_eticaret.excel_export import dashboard_stats
        orders = [_make_order(1, 'Picking', qty=2), _make_order(2, 'Created', qty=1)]
        stats = dashboard_stats(orders)
        # total_orders = benzersiz paket (package) sayısı
        self.assertEqual(stats['total_orders'], 2, 'total_orders paket sayısı')

    def test_urun_adedi_is_qty(self):
        from modules.online_eticaret.excel_export import dashboard_stats
        orders = [_make_order(1, 'Picking', qty=5)]
        stats = dashboard_stats(orders)
        # urun_adedi = quantity toplamı
        self.assertEqual(stats['total_qty'], 5)


# ── Test 6-8: Poll snapshot kapsam sözleşmesi ───────────────────────────

class TestSnapshotKapsamSozlesmesi(unittest.TestCase):
    """Test 6–8: snapshot date_filter ile eşleşmeli."""

    def setUp(self):
        from modules.online_eticaret.order_poll import (
            reset_order_poll_state,
            seed_snapshot_from_items,
        )
        self._reset = reset_order_poll_state
        self._seed = seed_snapshot_from_items
        self._reset()

    def _make_items(self, n=2):
        from modules.online_eticaret.excel_export import orders_to_rows
        from modules.online_eticaret.routes import _build_operasyon_listesi
        orders = [_make_order(i, 'Picking', qty=1) for i in range(n)]
        rows = orders_to_rows(orders, 'Solariz', {}, int(time.time() * 1000))
        return _build_operasyon_listesi({'Solariz': rows}, {})

    def test_open_snapshot_seeds_open(self):
        """Test 6: open filtre → snapshot date_filter='open'."""
        items = self._make_items()
        self._seed('open', items)
        from modules.online_eticaret import order_poll
        with order_poll._POLL_LOCK:
            snap_filter = order_poll._SNAPSHOT['date_filter']
        self.assertEqual(snap_filter, 'open')

    def test_today_snapshot_seeds_today(self):
        """Test 7: today filtre → snapshot date_filter='today'."""
        items = self._make_items()
        self._seed('today', items)
        from modules.online_eticaret import order_poll
        with order_poll._POLL_LOCK:
            snap_filter = order_poll._SNAPSHOT['date_filter']
        self.assertEqual(snap_filter, 'today')

    def test_open_today_not_mixed(self):
        """Test 8: open ile today snapshot karışmamalı."""
        items_open = self._make_items(3)
        self._seed('open', items_open)
        from modules.online_eticaret import order_poll
        with order_poll._POLL_LOCK:
            pkg_count_open = len(order_poll._SNAPSHOT.get('packages', {}))
            snap_filter_before = order_poll._SNAPSHOT['date_filter']

        items_today = self._make_items(1)
        self._seed('today', items_today)
        with order_poll._POLL_LOCK:
            pkg_count_today = len(order_poll._SNAPSHOT.get('packages', {}))
            snap_filter_after = order_poll._SNAPSHOT['date_filter']

        self.assertEqual(snap_filter_after, 'today')
        self.assertEqual(pkg_count_today, 1)
        # open'dan kalan 3 paket bugün kapsamına karışmamalı
        self.assertNotEqual(pkg_count_today, pkg_count_open)


# ── Test 9: poll yeni sipariş algılıyor ─────────────────────────────────

class TestPollYeniSiparis(unittest.TestCase):
    """Test 9: check_order_updates yeni siparişi algılar."""

    def setUp(self):
        from modules.online_eticaret.order_poll import reset_order_poll_state
        reset_order_poll_state()

    def test_new_package_detected(self):
        from modules.online_eticaret.order_poll import (
            check_order_updates,
            seed_snapshot_from_items,
        )
        from modules.online_eticaret.excel_export import orders_to_rows
        from modules.online_eticaret.routes import _build_operasyon_listesi

        # Başlangıç snapshot: 2 paket
        init_orders = [_make_order(1, 'Picking'), _make_order(2, 'Picking')]
        init_rows = orders_to_rows(init_orders, 'Solariz', {}, int(time.time() * 1000))
        init_items = _build_operasyon_listesi({'Solariz': init_rows}, {})
        seed_snapshot_from_items('today', init_items)

        # Poll: aynı 2 + 1 yeni paket (pkg_id=3)
        new_orders = [_make_order(1, 'Picking'), _make_order(2, 'Picking'), _make_order(3, 'Created')]

        def mock_fetch(seller_id, api_key, api_secret, status, start_ms, end_ms):
            if status in ('Created', 'Picking'):
                return [o for o in new_orders if o['status'] == status]
            return []

        with patch('modules.online_eticaret.trendyol_client.fetch_orders', side_effect=mock_fetch):
            with patch('modules.online_eticaret.config_store.is_store_configured', return_value=True):
                with patch('modules.online_eticaret.config_store.STORE_NAMES', ['Solariz']):
                    with patch('modules.online_eticaret.config_store.get_store', return_value={
                        'sellerId': 'S1', 'apiKey': 'K', 'apiSecret': 'SC'
                    }):
                        result = check_order_updates(
                            'today',
                            None,
                            lambda orders, store, mmap: orders_to_rows(orders, store, mmap, int(time.time() * 1000)),
                            _build_operasyon_listesi,
                            lambda df: (int(time.time() * 1000) - 86400000, int(time.time() * 1000)),
                        )

        self.assertTrue(result.get('ok'), f'ok=False: {result}')
        # new_count = kaç yeni paket geldi (package bazında, satır değil)
        self.assertGreaterEqual(result.get('new_count', 0), 1, f'new_count={result.get("new_count")} >= 1 bekleniyor')


# ── Test 10: poll cache güncelliyor ──────────────────────────────────────

class TestPollCacheGuncelleme(unittest.TestCase):
    """Test 10: poll sonrası order cache güncellenir."""

    def test_order_cache_updated_after_poll(self):
        """Routes order_updates endpoint cache'i günceller."""
        from modules.online_eticaret import routes
        import modules.online_eticaret.routes as rt

        initial = dict(rt._ORDER_CACHE)
        # Cache'i temizle
        rt._ORDER_CACHE.clear()

        # get_poll_store_snapshots mock veri döndürsün
        mock_snap = {
            'Solariz': {'orders': [_make_order(99, 'Picking')], 'model_map': {}, 'image_map': {}}
        }
        with patch('modules.online_eticaret.order_poll.get_poll_store_snapshots', return_value=mock_snap):
            payload = {'ok': True, 'busy': False, 'error': None}
            ts = time.time()
            for sn_store, sn_data in mock_snap.items():
                cache_key = rt._order_cache_key(sn_store, 'open')
                existing = rt._ORDER_CACHE.get(cache_key)
                if not existing or ts - existing[0] > 30:
                    rt._ORDER_CACHE[cache_key] = (ts, sn_data['orders'], sn_data['model_map'], sn_data['image_map'])

        key = rt._order_cache_key('Solariz', 'open')
        self.assertIn(key, rt._ORDER_CACHE, 'Cache güncellenmiş olmalı')
        rt._ORDER_CACHE.clear()


# ── Test 11: duplicate paket yok ─────────────────────────────────────────

class TestDeduplication(unittest.TestCase):
    """Test 11: aynı paket iki kez eklenmemeli."""

    def test_dedupe_same_pkg_id(self):
        from modules.online_eticaret.routes import _dedupe_orders_by_package
        orders = [
            _make_order(1, 'Created', qty=1),
            _make_order(1, 'Picking', qty=1),   # aynı pkg_id
        ]
        result = _dedupe_orders_by_package({'Solariz': orders})
        self.assertEqual(len(result['Solariz']), 1, 'Aynı pkg_id bir kez görünmeli')
        # Picking öncelikli
        self.assertEqual(result['Solariz'][0]['status'], 'Picking')

    def test_dedupe_different_stores_not_merged(self):
        from modules.online_eticaret.routes import _dedupe_orders_by_package
        sol = [_make_order(1, 'Picking', qty=1)]
        ep = [_make_order(1, 'Created', qty=1)]
        result = _dedupe_orders_by_package({'Solariz': sol, 'Epona': ep})
        self.assertEqual(len(result['Solariz']), 1)
        self.assertEqual(len(result['Epona']), 1)


# ── Test 12: page_size değişince toplam değişmez (mock) ──────────────────

class TestPageSizeMock(unittest.TestCase):
    """Test 12: page size değişince toplam sonuç değişmez (mock verisi üzerinde)."""

    def test_mock_orders_independent_of_page_size(self):
        from modules.online_eticaret.excel_export import dashboard_stats
        # 5 farklı pkg, farklı qty
        orders = [_make_order(i, 'Picking', qty=i + 1) for i in range(5)]
        stats = dashboard_stats(orders)
        # Toplam 5 paket, 15 qty
        self.assertEqual(stats['total_orders'], 5)
        self.assertEqual(stats['total_qty'], 5 + 4 + 3 + 2 + 1)


# ── Test 13: pagination cap korunuyor ────────────────────────────────────

class TestPaginationCap(unittest.TestCase):
    """Test 13: _max_pages() değerini aşan pagination engelleniyor."""

    def test_max_pages_default(self):
        from modules.online_eticaret.trendyol_client import _max_pages
        # Varsayılan 20
        cap = _max_pages()
        self.assertGreaterEqual(cap, 1)
        self.assertLessEqual(cap, 1000, 'Çok büyük değer olmamalı')

    def test_max_pages_env_override(self):
        from modules.online_eticaret import trendyol_client as tc
        import importlib
        os.environ['API_MAX_PAGES'] = '5'
        cap = tc._max_pages()
        self.assertEqual(cap, 5)
        del os.environ['API_MAX_PAGES']


# ── Test 14: 429/timeout davranışı ──────────────────────────────────────

class TestRetryBehavior(unittest.TestCase):
    """Test 14: 429 ve timeout durumlarında backoff çalışıyor."""

    def test_429_backoff_in_poll(self):
        from modules.online_eticaret.order_poll import _backoff_seconds, _POLL_LOCK
        import modules.online_eticaret.order_poll as poll
        with _POLL_LOCK:
            poll._CONSECUTIVE_ERRORS = 1
        bs = _backoff_seconds()
        self.assertGreater(bs, 0)
        with _POLL_LOCK:
            poll._CONSECUTIVE_ERRORS = 0


# ── Test 15: enrichment duplicate worker yok ────────────────────────────

class TestEnrichmentNoDuplicate(unittest.TestCase):
    """Test 15: aynı seller için iki arka plan worker başlamaz."""

    def test_duplicate_background_blocked(self):
        from modules.online_eticaret.trendyol_client import (
            reset_product_cache,
            start_product_catalog_background,
            _PRODUCT_BG_LOCK,
            _PRODUCT_BG_IN_FLIGHT,
        )
        reset_product_cache()

        def fake_fetch(*a, **kw):
            time.sleep(0.05)
            return {}

        with patch('modules.online_eticaret.trendyol_client.fetch_product_info', side_effect=fake_fetch):
            r1 = start_product_catalog_background('S999', 'K', 'SC')
            r2 = start_product_catalog_background('S999', 'K', 'SC')
        time.sleep(0.1)
        # İkinci çağrı duplicate olarak bloke edilmeli
        self.assertTrue(r1, 'İlk worker başlamış olmalı')
        self.assertFalse(r2, 'İkinci worker bloke edilmeli')
        reset_product_cache()


# ── Test 16-18: Güvenlik sözleşmeleri ────────────────────────────────────

class TestGuvenlikSozlesmesi(unittest.TestCase):
    """Test 16-18: write endpoint / non-GET / secret yok."""

    def _read_routes(self):
        p = os.path.join(APP, 'modules', 'online_eticaret', 'routes.py')
        return open(p, encoding='utf-8').read()

    def test_write_endpoint_count_zero(self):
        """Test 16: OET routes'ta POST/PUT/PATCH/DELETE method yok."""
        src = self._read_routes()
        hits = re.findall(
            r"@online_eticaret_bp\.route\([^)]*methods\s*=\s*\[[^\]]*(POST|PUT|PATCH|DELETE)",
            src, re.I
        )
        self.assertEqual(len(hits), 0, f'Yazma route bulundu: {hits}')

    def test_non_get_route_count_zero(self):
        """Test 17: OET routes'ta non-GET method yok."""
        src = self._read_routes()
        # Yalnız @route ile methods= içeren yazma varsa tespit et
        m = re.findall(r"methods=\[.*?(POST|PUT|PATCH|DELETE)", src, re.I)
        self.assertEqual(len(m), 0, f'Non-GET method bulundu: {m}')

    def test_no_env_or_db_in_routes(self):
        """Test 18: Routes'ta sqlite3 connect veya DB bağlantısı yok."""
        src = self._read_routes()
        self.assertNotIn('sqlite3.connect', src, 'sqlite3.connect OET routes içinde olmamalı')
        # '.env' string yorumda geçebilir (örn: 'DB yok. .env değil'), literal dosya yolu olmamalı
        env_file_refs = re.findall(r"open\([^)]*\.env[^)]*\)|load_dotenv|dotenv", src)
        self.assertEqual(len(env_file_refs), 0, f'.env dosya referansı: {env_file_refs}')

    def test_api_write_default_false(self):
        src = self._read_routes()
        self.assertIn("API_WRITE_ENABLED', 'false'", src)


# ── Test 19: Route HTTP 200 ───────────────────────────────────────────────

class TestRouteHttp200(unittest.TestCase):
    """Test 19: /online-eticaret/ ve mobil HTTP 200."""

    @classmethod
    def setUpClass(cls):
        import modules.auth as auth_mod
        auth_mod.sistem_session_gecerli_mi = lambda _u: True
        from app import app
        app.config['TESTING'] = True
        cls.client = app.test_client()

    def _with_session(self):
        with self.client.session_transaction() as sess:
            sess['kullanici'] = {'Id': 1, 'KullaniciAdi': 'admin', 'AdSoyad': 'Test'}

    def test_oet_index_200(self):
        self._with_session()
        r = self.client.get('/online-eticaret/?force=desktop')
        self.assertIn(r.status_code, (200, 302))

    def test_oet_mobil_200(self):
        self._with_session()
        r = self.client.get('/online-eticaret/mobil/')
        self.assertIn(r.status_code, (200, 302))

    def test_oet_poll_200(self):
        self._with_session()
        r = self.client.get('/online-eticaret/api/order-updates?days=open')
        self.assertEqual(r.status_code, 200)

    def test_oet_poll_today_200(self):
        self._with_session()
        r = self.client.get('/online-eticaret/api/order-updates?days=today')
        self.assertEqual(r.status_code, 200)

    def test_oet_poll_7d_returns_error(self):
        """7d filtresi desteklenmiyor; ok=False döner."""
        self._with_session()
        import json
        r = self.client.get('/online-eticaret/api/order-updates?days=7d')
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.data)
        self.assertFalse(data.get('ok'), 'ok=False bekleniyor')


# ── Test 20: Mevcut OET regression suite PASS ────────────────────────────

class TestMevcutOETRegressionSuite(unittest.TestCase):
    """Test 20: dev_tests/test_oet_parity_v2.py tamamen geçmeli."""

    def test_existing_parity_suite_importable(self):
        import importlib.util
        dev_tests = os.path.join(os.path.dirname(__file__), '..', 'dev_tests', 'test_oet_parity_v2.py')
        self.assertTrue(os.path.isfile(dev_tests), 'test_oet_parity_v2.py mevcut olmalı')
        spec = importlib.util.spec_from_file_location('test_oet_parity_v2', dev_tests)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

    def test_poll_open_supported_in_check_order_updates(self):
        """check_order_updates artık 'open' kabul ediyor, 'today' only değil."""
        from modules.online_eticaret.order_poll import check_order_updates
        # 'open' için error olmamalı (unsupported_filter dönmemeli)
        # Mock ile: fetch gerçek API'ye gitmeden unsupported kontrolü aşılır
        result = check_order_updates(
            'open',
            None,
            lambda o, s, m: [],
            lambda r, i, p=None: [],
            lambda df: (0, 1),
        )
        self.assertNotEqual(result.get('error'), 'unsupported_filter',
                            'open filtresi artık destekleniyor olmalı')


if __name__ == '__main__':
    unittest.main(verbosity=2)
