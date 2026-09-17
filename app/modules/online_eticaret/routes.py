# -*- coding: utf-8 -*-
"""
CPS - Online E-Ticaret Routes
===============================
FAZ1-C : Gerçek Trendyol GET verisi.
FAZ2-A : Sipariş Operasyon Listesi — görsel, pagination, filtre, arama.
         Sadece görüntüleme. PUT/POST yok. Korgun yok. Stok yok. DB yok.
"""
import copy
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, render_template, session, redirect, url_for, request
from modules.auth import login_gerekli

from modules.online_eticaret.config_store import get_store, is_store_configured, STORE_NAMES
from modules.online_eticaret.trendyol_client import (
    fetch_orders,
    get_product_cache_maps,
    get_product_enrichment,
    is_product_cache_warm,
    start_product_catalog_background,
    TrendyolError,
)
from modules.online_eticaret.excel_export import (
    dashboard_stats, orders_to_rows, HEADERS, pkg_order_date_map,
)
from modules.online_eticaret.order_poll import (
    check_order_updates,
    get_order_poll_interval_seconds,
    get_poll_store_snapshots,
    get_snapshot_cursor,
    seed_snapshot_from_items,
)

online_eticaret_bp = Blueprint(
    'online_eticaret',
    __name__,
    url_prefix='/online-eticaret',
)

# ── Sabitler ──────────────────────────────────────────────────────────────
FETCH_STATUSES = ['Picking', 'Created']
FETCH_DAYS     = 7
# Açık sipariş penceresi: Trendyol 14 günlük dilim sınırı gözetilerek 30 gün
FETCH_OPEN_DAYS = 30
DATE_FILTER_TODAY = 'today'
DATE_FILTER_7D = '7d'
DATE_FILTER_OPEN = 'open'          # Açık Siparişler (varsayılan)
DEFAULT_DATE_FILTER = DATE_FILTER_OPEN
DATE_FILTER_QUERY_PARAM = 'days'
# Europe/Istanbul = UTC+3 (TRT; yaz saati yok)
TZ_TURKEY = timezone(timedelta(hours=3))
SIPARIS_LIMIT  = 25       # KPI kartı altındaki özet tablo limiti

# ── Sipariş önbelleği (in-memory, process seviyesi) ───────────────────────
# { (store_name, date_filter): (cached_at_ts, orders, model_map, image_map) }
# Ürün cache'e dokunulmaz — trendyol_client._PRODUCT_CACHE zaten 10 dk.
_ORDER_CACHE     = {}
_ORDER_CACHE_TTL = 5 * 60   # 5 dakika
_PAGE_METRICS    = {}
_LAST_PAGE_METRICS = {}
_PAGE_METRICS_LOCK = threading.Lock()
_STORE_FETCH_WORKERS = 2


def _api_mode():
    return os.environ.get('API_MODE', 'mock').strip().lower() or 'mock'


def _template_flags():
    return {
        'api_mode': _api_mode(),
        'api_write_enabled': os.environ.get('API_WRITE_ENABLED', 'false').lower() == 'true',
    }


def reset_order_cache():
    _ORDER_CACHE.clear()


def reset_page_metrics():
    _PAGE_METRICS.clear()
    _PAGE_METRICS.update({
        'page': '',
        'order_cache_hits': 0,
        'order_cache_misses': 0,
        'row_count': 0,
        'package_count': 0,
        'html_bytes': 0,
        'backend_ms': 0.0,
        'orders_critical_ms': 0.0,
        'product_background_blocked_render': False,
        'product_background_started': 0,
        'stores': {},
        'frontend_render_ms': None,
        'frontend_row_count': None,
        'frontend_json_chars': None,
    })


def get_last_page_metrics():
    return copy.deepcopy(_LAST_PAGE_METRICS)


def _begin_page_metrics(page):
    from modules.online_eticaret.trendyol_client import reset_client_metrics
    reset_page_metrics()
    reset_client_metrics()
    _PAGE_METRICS['page'] = page
    _PAGE_METRICS['_started'] = time.perf_counter()


def _finalize_page_metrics(html, *, row_count, package_count):
    from modules.online_eticaret import trendyol_client as tc
    started = _PAGE_METRICS.pop('_started', time.perf_counter())
    _PAGE_METRICS['backend_ms'] = round((time.perf_counter() - started) * 1000, 2)
    _PAGE_METRICS['row_count'] = row_count
    _PAGE_METRICS['package_count'] = package_count
    if isinstance(html, str):
        _PAGE_METRICS['html_bytes'] = len(html.encode('utf-8'))
    stores = _PAGE_METRICS.get('stores') or {}
    if stores:
        _PAGE_METRICS['stores'] = {
            name: stores[name]
            for name in STORE_NAMES
            if name in stores
        }
    stores = _PAGE_METRICS.get('stores') or {}
    order_ms_values = [
        float((stores.get(name) or {}).get('orders_ms') or 0)
        for name in STORE_NAMES
        if name in stores
    ]
    if order_ms_values:
        _PAGE_METRICS['orders_critical_ms'] = round(max(order_ms_values), 2)
    _PAGE_METRICS['product_background_blocked_render'] = False
    _PAGE_METRICS['client'] = tc.get_client_metrics()
    _LAST_PAGE_METRICS.clear()
    _LAST_PAGE_METRICS.update(copy.deepcopy(_PAGE_METRICS))


def record_frontend_metrics(payload):
    """Dev-only client timings. Numeric fields only; no order/PII payload."""
    if not isinstance(payload, dict):
        return
    render_ms = payload.get('render_ms')
    row_count = payload.get('row_count')
    json_chars = payload.get('json_chars')
    if isinstance(render_ms, (int, float)):
        _LAST_PAGE_METRICS['frontend_render_ms'] = round(float(render_ms), 2)
    if isinstance(row_count, int):
        _LAST_PAGE_METRICS['frontend_row_count'] = row_count
    if isinstance(json_chars, int):
        _LAST_PAGE_METRICS['frontend_json_chars'] = json_chars

# FAZ0-B korunan (çoklu statü dağılımı FAZ2-B'de yapılacak)
MOCK_DAGITIM = [
    {'durum': 'Yeni',              'kod': 'YENI',             'adet': 0, 'renk': '#1e3a8a'},
    {'durum': 'Toplanıyor',        'kod': 'TOPLANIYOR',       'adet': 0, 'renk': '#b45309'},
    {'durum': 'Toplandı',          'kod': 'TOPLANDI',         'adet': 0, 'renk': '#15803d'},
    {'durum': 'Barkod Basıldı',    'kod': 'BARKOD_BASILDI',  'adet': 0, 'renk': '#6d28d9'},
    {'durum': 'Paketlemede',       'kod': 'PAKETLEMEDE',      'adet': 0, 'renk': '#c2410c'},
    {'durum': 'Paketlendi',        'kod': 'PAKETLENDI',       'adet': 0, 'renk': '#0369a1'},
    {'durum': 'Kargoya Teslim',    'kod': 'KARGOYA_TESLIM',  'adet': 0, 'renk': '#15803d'},
    {'durum': 'Stok Fişi Oluştu',  'kod': 'STOK_FISI_OLUSTU','adet': 0, 'renk': '#0369a1'},
]

MOCK_OPERASYON = {
    'toplayan':    '—',
    'paketleyen':  '—',
    'son_siparis': '—',
}

# ── HEADERS indeksleri ────────────────────────────────────────────────────
_IDX_MAGAZA    = HEADERS.index('Mağaza')
_IDX_TRENDYOL_STATUS = HEADERS.index('Trendyol Status')
_IDX_GECIKME   = HEADERS.index('Gecikme Durumu')
_IDX_SIPARIS_TARIHI = HEADERS.index('Sipariş Tarihi')
_IDX_NO        = HEADERS.index('Sipariş No')          # orderNumber
_IDX_PKG_ID    = HEADERS.index('Paket/Teslimat No')   # id = shipmentPackageId
_IDX_URUN      = HEADERS.index('Ürün Adı')
_IDX_ADET      = HEADERS.index('Adet')
_IDX_MODEL     = HEADERS.index('Model Kodu')
_IDX_RENK      = HEADERS.index('Renk')
_IDX_BEDEN     = HEADERS.index('Beden')
_IDX_BARKOD    = HEADERS.index('Barkod')
_IDX_KARGO     = HEADERS.index('Kargo Firması')
_IDX_KARGO_NO  = HEADERS.index('Kargo Takip No')      # cargoTrackingNumber


# ── Servis fonksiyonları ──────────────────────────────────────────────────

def _ms_aralik(gun):
    """Son N gün (rolling) — 7 Gün filtresi."""
    now_ms   = int(time.time() * 1000)
    start_ms = now_ms - gun * 24 * 60 * 60 * 1000
    return start_ms, now_ms


def _ms_aralik_bugun():
    """Bugün 00:00:00 — şimdi (Europe/Istanbul)."""
    now_dt = datetime.now(TZ_TURKEY)
    start_dt = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(now_dt.timestamp() * 1000)
    return start_ms, end_ms


def _ms_aralik_acik():
    """Son 30 gün — Açık Siparişler filtresi.
    Trendyol 14 günlük API penceresini otomatik dilimlediğinden
    30 gün güvenli şekilde sorgulanabilir.
    """
    now_ms = int(time.time() * 1000)
    return now_ms - FETCH_OPEN_DAYS * 24 * 60 * 60 * 1000, now_ms


def _parse_date_filter(req):
    raw = (req.args.get(DATE_FILTER_QUERY_PARAM) or DEFAULT_DATE_FILTER).strip().lower()
    if raw in ('7', '7d', '7gun', '7_gun'):
        return DATE_FILTER_7D
    if raw == 'today':
        return DATE_FILTER_TODAY
    # 'open' veya tanınmayan her değer → açık siparişler
    return DATE_FILTER_OPEN


def _ms_aralik_for_filter(date_filter):
    if date_filter == DATE_FILTER_7D:
        return _ms_aralik(FETCH_DAYS)
    if date_filter == DATE_FILTER_TODAY:
        return _ms_aralik_bugun()
    return _ms_aralik_acik()   # DATE_FILTER_OPEN (varsayılan)


def _date_filter_label(date_filter):
    if date_filter == DATE_FILTER_TODAY:
        return 'Bugün'
    if date_filter == DATE_FILTER_7D:
        return '7 Gün'
    return 'Açık Siparişler'


def _order_cache_key(store_name, date_filter):
    return (store_name, date_filter)


def _dedupe_orders_by_package(magaza_orders):
    """
    Created ve Picking listelerinde aynı package görünürse tek paket olarak birleştirir.

    Anahtar: store_name|shipmentPackageId
    Öncelik: Picking > Created

    Döner: {store_name: dedupe_orders_list}
    """
    result = {}
    for store_name, orders in magaza_orders.items():
        seen = {}  # pkg_id -> order
        for order in orders:
            pkg_id = str(order.get('id') or '').strip()
            if not pkg_id:
                continue

            key = f"{store_name}|{pkg_id}"
            existing = seen.get(key)

            if existing is None:
                seen[key] = order
            else:
                # Öncelik: Picking > Created
                existing_status = str(existing.get('status') or '').strip()
                current_status = str(order.get('status') or '').strip()

                if current_status == 'Picking' and existing_status == 'Created':
                    seen[key] = order
                # Eğer existing zaten Picking ise değiştirmeyelim

        result[store_name] = list(seen.values())

    return result


def _inc_page_metric(key, delta=1):
    with _PAGE_METRICS_LOCK:
        _PAGE_METRICS[key] = _PAGE_METRICS.get(key, 0) + delta


def _set_store_page_metrics(store_name, store_metrics):
    with _PAGE_METRICS_LOCK:
        _PAGE_METRICS.setdefault('stores', {})[store_name] = store_metrics


def _seller_id_for_store(store_name):
    return str(get_store(store_name).get('sellerId') or '').strip()


def _apply_warm_product_maps(model_map, image_map, seller_id):
    warm_models, warm_images = get_product_cache_maps(seller_id)
    if warm_models:
        model_map = {**model_map, **warm_models}
    if warm_images:
        image_map = {**image_map, **warm_images}
    return model_map, image_map


def _schedule_product_background(store_name, seller_id, api_key, api_secret):
    if start_product_catalog_background(seller_id, api_key, api_secret):
        _inc_page_metric('product_background_started')


def _fetch_magazalar_parallel(start_ms, end_ms, date_filter, force_refresh=False):
    """Mağazaları paralel çek; sonuç sırası STORE_NAMES ile sabit kalır."""
    results = {}
    with ThreadPoolExecutor(max_workers=_STORE_FETCH_WORKERS) as pool:
        futures = {
            store_name: pool.submit(
                _cek_magaza,
                store_name,
                start_ms,
                end_ms,
                date_filter,
                force_refresh=force_refresh,
            )
            for store_name in STORE_NAMES
        }
        for store_name in STORE_NAMES:
            results[store_name] = futures[store_name].result()
    return results


def _cache_age_seconds(date_filter):
    cache_yasi_sn = None
    for store_name in STORE_NAMES:
        entry = _ORDER_CACHE.get(_order_cache_key(store_name, date_filter))
        if entry:
            age = int(time.time() - entry[0])
            cache_yasi_sn = age if cache_yasi_sn is None else max(cache_yasi_sn, age)
    return cache_yasi_sn


def _aciliyet(gecikme_str):
    """
    0 = gecikmiş   (GECİKTİ)
    1 = bugün çıkacak  (Kalan: saat bazında — gün yok)
    2 = yakın (Kalan: X gün)
    3 = yeni / belirsiz
    """
    s = str(gecikme_str or '')
    if s.startswith('GECİKTİ'):
        return 0
    if s.startswith('Kalan:'):
        return 1 if 'gün' not in s else 2
    return 3


def _trendyol_status_to_ui(trendyol_status, gecikme_str):
    """
    Trendyol status'unu UI durum ve rengine çevirir.

    Created → YENİ (mavi #1e3a8a)
    Picking → TOPLANIYOR (turuncu #b45309)

    Gecikme durumu status'u değiştirmez, yalnız aciliyet bilgisidir.
    """
    status = str(trendyol_status or '').strip()
    gecikme = str(gecikme_str or '')

    if status == 'Created':
        durum = 'YENİ'
        renk = '#1e3a8a'
    elif status == 'Picking':
        durum = 'TOPLANIYOR'
        renk = '#b45309'
    else:
        # Fallback: bilinmeyen status
        durum = status or 'BİLİNMİYOR'
        renk = '#64748b'

    return durum, renk, gecikme


def _format_siparis_tarihi_display(order_ms):
    """Europe/Istanbul sipariş tarihi — yalnız Bugün veya DD.MM.YYYY (saat gösterilmez)."""
    if order_ms is None:
        return '—'
    try:
        ms = int(order_ms)
    except (TypeError, ValueError):
        return '—'
    if ms <= 0:
        return '—'
    dt = datetime.fromtimestamp(ms / 1000, tz=TZ_TURKEY)
    now = datetime.now(TZ_TURKEY)
    if dt.date() == now.date():
        return 'Bugün'
    return dt.strftime('%d.%m.%Y')


def _rows_to_siparis(tum_rows, limit=SIPARIS_LIMIT):
    """Özet KPI tablosu için (üst panel)."""
    result = []
    for row in tum_rows[:limit]:
        trendyol_status = row[_IDX_TRENDYOL_STATUS]
        gecikme = row[_IDX_GECIKME]
        durum, renk, kalan = _trendyol_status_to_ui(trendyol_status, gecikme)
        result.append({
            'no':     str(row[_IDX_NO]    or ''),
            'magaza': str(row[_IDX_MAGAZA] or ''),
            'urun':   str(row[_IDX_URUN]   or ''),
            'adet':   row[_IDX_ADET]       or 0,
            'kalan':  kalan,
            'durum':  durum,
            'renk':   renk,
        })
    return result


def _build_operasyon_listesi(rows_by_store, image_map_global, pkg_date_ms=None):
    """
    Tam operasyon listesi (tüm satırlar, görsel URL dahil).
    Template'e JSON olarak gömülür; JS tarafında filtre/arama/pagination yapılır.
    API key/secret bu fonksiyona girmez.
    Trendyol status bilgisi korunur.
    """
    date_lookup = dict(pkg_date_ms or {})
    result = []
    for store_name, rows in rows_by_store.items():
        for row in rows:
            barkod  = str(row[_IDX_BARKOD] or '')
            trendyol_status = row[_IDX_TRENDYOL_STATUS]
            gecikme = row[_IDX_GECIKME]
            durum, durum_renk, kalan = _trendyol_status_to_ui(trendyol_status, gecikme)
            pkg_id = str(row[_IDX_PKG_ID] or '')
            order_ms = date_lookup.get(pkg_id)
            result.append({
                'magaza':       str(row[_IDX_MAGAZA]   or ''),
                'trendyol_status': trendyol_status,
                'aciliyet':     _aciliyet(gecikme),
                'gorsel':       image_map_global.get(barkod, ''),
                'no':           str(row[_IDX_NO]       or ''),   # orderNumber (referans)
                'pkg_id':       pkg_id,   # shipmentPackageId (ana kimlik)
                'kargo_barkod': str(row[_IDX_KARGO_NO] or ''),   # cargoTrackingNumber
                'siparis_tarihi': _format_siparis_tarihi_display(order_ms),
                'siparis_tarihi_ms': order_ms,
                'urun':         str(row[_IDX_URUN]     or ''),
                'model':        str(row[_IDX_MODEL]    or ''),
                'renk_urun':    str(row[_IDX_RENK]     or ''),
                'beden':        str(row[_IDX_BEDEN]    or ''),
                'adet':         row[_IDX_ADET]         or 0,
                'barkod':       barkod,
                'kargo':        str(row[_IDX_KARGO]    or ''),
                'kalan':        kalan,
                'durum':        durum,
                'durum_renk':   durum_renk,
            })
    result.sort(key=lambda x: x['aciliyet'])
    return result


def _group_paketler(operasyon_listesi):
    """
    Flat operasyon_listesi'ni shipmentPackageId bazında paket gruplarına çevirir.

    Gruplama birimi: pkg_id (= id = shipmentPackageId) — fiziksel koli.
    Aynı orderNumber ama farklı pkg_id → ayrı paket (bölünmüş sipariş).
    orderNumber sadece referans olarak saklanır.

    Döner:
      [{ pkg_id, siparis_no, no (=siparis_no compat), magaza,
         aciliyet, kalan, durum, durum_renk, kargo, kargo_barkod,
         kalem, urunler: [item, ...] }]
    """
    groups = {}   # pkg_id -> pkg
    order  = []   # insertion order (sıra bozulmasın)
    for item in operasyon_listesi:
        pkg_id = item['pkg_id'] or item['no']   # fallback: no pkg_id → orderNumber
        if pkg_id not in groups:
            pkg = {
                'pkg_id':       pkg_id,
                'siparis_no':   item['no'],           # orderNumber (referans)
                'no':           item['no'],            # geriye dönük uyumluluk
                'magaza':       item['magaza'],
                'aciliyet':     item['aciliyet'],
                'kalan':        item['kalan'],
                'durum':        item['durum'],
                'durum_renk':   item['durum_renk'],
                'kargo':        item['kargo'],
                'kargo_barkod': item['kargo_barkod'],
                'urunler':      [],
            }
            groups[pkg_id] = pkg
            order.append(pkg)
        pkg = groups[pkg_id]
        # En kötü aciliyeti pakete yansıt
        if item['aciliyet'] < pkg['aciliyet']:
            pkg['aciliyet']   = item['aciliyet']
            pkg['kalan']      = item['kalan']
            pkg['durum']      = item['durum']
            pkg['durum_renk'] = item['durum_renk']
        pkg['urunler'].append(item)
    for pkg in order:
        pkg['kalem'] = len(pkg['urunler'])
    return order


def _cek_magaza(store_name, start_ms, end_ms, date_filter, force_refresh=False):
    """
    Döner: (siparisler, model_map, image_map, hata_mesaji_veya_None)

    Sipariş sonuçları 5 dk memory cache'te tutulur.
    force_refresh=True (veya cache süresi dolmuşsa) Trendyol'dan taze çeker.
    API key/secret ASLA loglanmaz.
    """
    if not is_store_configured(store_name):
        _set_store_page_metrics(store_name, {
            'order_cache': 'skip',
            'orders_ms': 0,
            'products_ms': 0,
            'order_count': 0,
            'configured': False,
            'error': 'missing_credentials',
        })
        return [], {}, {}, f"{store_name}: api_error"

    store_metrics = {
        'order_cache': 'miss',
        'orders_ms': 0.0,
        'products_ms': 0.0,
        'order_count': 0,
        'configured': True,
    }

    # ── Cache kontrolü ──────────────────────────────────────────────────
    cache_key = _order_cache_key(store_name, date_filter)
    cached = _ORDER_CACHE.get(cache_key)
    if cached and not force_refresh:
        try:
            cached_at, c_orders, c_model_map, c_image_map = cached
            if (time.time() - cached_at) < _ORDER_CACHE_TTL:
                store_metrics['order_cache'] = 'hit'
                store_metrics['order_count'] = len(c_orders)
                seller_id = _seller_id_for_store(store_name)
                c_model_map, c_image_map = _apply_warm_product_maps(
                    c_model_map, c_image_map, seller_id
                )
                if not is_product_cache_warm(seller_id):
                    cfg = get_store(store_name)
                    _schedule_product_background(
                        store_name, seller_id, cfg['apiKey'], cfg['apiSecret']
                    )
                _inc_page_metric('order_cache_hits')
                _set_store_page_metrics(store_name, store_metrics)
                return c_orders, c_model_map, c_image_map, None
        except (ValueError, TypeError):
            pass   # eski format (3-tuple) → taze çek

    _inc_page_metric('order_cache_misses')

    # ── Taze çekme ──────────────────────────────────────────────────────
    cfg        = get_store(store_name)
    seller_id  = cfg['sellerId']
    api_key    = cfg['apiKey']
    api_secret = cfg['apiSecret']

    tum_siparisler = []
    t_orders = time.perf_counter()
    for status in FETCH_STATUSES:
        try:
            orders = fetch_orders(
                seller_id, api_key, api_secret,
                status, start_ms, end_ms,
            )
            tum_siparisler.extend(orders)
        except TrendyolError:
            store_metrics['error'] = 'api_error'
            _set_store_page_metrics(store_name, store_metrics)
            return [], {}, {}, f"{store_name}: api_error"
    store_metrics['orders_ms'] = round((time.perf_counter() - t_orders) * 1000, 2)
    store_metrics['order_count'] = len(tum_siparisler)

    model_map = {}
    image_map = {}
    t_products = time.perf_counter()
    model_map, image_map = get_product_cache_maps(seller_id)
    if model_map or image_map:
        store_metrics['product_cache'] = 'hit'
    else:
        store_metrics['product_cache'] = 'background'
        _schedule_product_background(store_name, seller_id, api_key, api_secret)
    store_metrics['products_ms'] = round((time.perf_counter() - t_products) * 1000, 2)
    store_metrics['orders_critical_ms'] = store_metrics['orders_ms']
    _set_store_page_metrics(store_name, store_metrics)

    # Cache'e yaz (model_map dahil — cache hit'te model kodu kaybolmasın)
    _ORDER_CACHE[cache_key] = (time.time(), tum_siparisler, model_map, image_map)

    return tum_siparisler, model_map, image_map, None


# ── Mobil yardımcıları ────────────────────────────────────────────────────

def _is_mobile_ua(req):
    """User-Agent telefon/tablet ise True döner."""
    ua = req.headers.get('User-Agent', '').lower()
    return any(k in ua for k in ('mobile', 'android', 'iphone', 'ipad', 'tablet'))


def _fetch_operasyon_listesi(date_filter, force_refresh=False):
    """
    Mobil route için sadece operasyon listesini çeker.
    force_refresh=True → cache bypass, Trendyol'dan taze çeker.
    """
    now_ms           = int(time.time() * 1000)
    start_ms, end_ms = _ms_aralik_for_filter(date_filter)
    hatalar          = []
    rows_by_store    = {}
    image_map_global = {}

    magaza_orders = {}
    magaza_maps = {}
    for store_name, (orders, model_map, image_map, hata) in _fetch_magazalar_parallel(
        start_ms, end_ms, date_filter, force_refresh=force_refresh
    ).items():
        if hata:
            hatalar.append(hata)
        else:
            magaza_orders[store_name] = orders
            magaza_maps[store_name] = model_map
            image_map_global.update(image_map)

    # Created/Picking dedupe koruması
    magaza_orders = _dedupe_orders_by_package(magaza_orders)

    for store_name, orders in magaza_orders.items():
        mmap = magaza_maps.get(store_name, {})
        rows_by_store[store_name] = orders_to_rows(orders, store_name, mmap, now_ms)

    pkg_date_ms = {}
    for orders in magaza_orders.values():
        pkg_date_ms.update(pkg_order_date_map(orders))
    operasyon_listesi = _build_operasyon_listesi(rows_by_store, image_map_global, pkg_date_ms)
    return operasyon_listesi, bool(hatalar), hatalar


# ── Route ─────────────────────────────────────────────────────────────────

@online_eticaret_bp.route('/api/order-updates')
@login_gerekli
def order_updates():
    """GET-only incremental order diff; no customer PII."""
    raw_days = (request.args.get(DATE_FILTER_QUERY_PARAM) or DATE_FILTER_OPEN).strip().lower()
    # Polling yalnız 'open' veya 'today' kapsamında çalışır
    if raw_days in ('7d', '7', '7gun'):
        return jsonify({
            'ok': False,
            'error': 'unsupported_filter',
            'backoff_seconds': get_order_poll_interval_seconds(),
            'secrets_logged': False,
        })
    # KAPI-2 FIX: aktif date_filter snapshot ile aynı kapsam.
    # Önceki kod DATE_FILTER_TODAY hardcoded gönderiyordu; open filtresi yüklenince
    # today snapshot ile karşılaştırılıyordu → sahte 'removed' listesi.
    if raw_days == 'today':
        active_filter = DATE_FILTER_TODAY
    else:
        active_filter = DATE_FILTER_OPEN   # 'open' ve bilinmeyen → open kapsamı
    since = (request.args.get('since') or '').strip() or None
    result = check_order_updates(
        active_filter,
        since,
        lambda orders, store_name, model_map: orders_to_rows(
            orders, store_name, model_map, int(time.time() * 1000)
        ),
        _build_operasyon_listesi,
        _ms_aralik_for_filter,
    )
    payload = dict(result)
    payload['secrets_logged'] = False
    # KAPI-2 FIX: poll sonucu taze snapshot ürettiyse order cache'i güncelle
    # → aynı verinin hemen ardından yeniden çekilmesini önler.
    if payload.get('ok') and not payload.get('busy') and not payload.get('error'):
        snap = get_poll_store_snapshots()
        if snap:
            ts = time.time()
            for sn_store, sn_data in snap.items():
                cache_key = _order_cache_key(sn_store, active_filter)
                existing = _ORDER_CACHE.get(cache_key)
                # Yalnız cache yoksa veya poll verisi daha yeniyse güncelle
                if not existing or ts - existing[0] > 30:
                    _ORDER_CACHE[cache_key] = (ts, sn_data['orders'], sn_data['model_map'], sn_data['image_map'])
    return jsonify(payload)


@online_eticaret_bp.route('/api/product-enrichment')
@login_gerekli
def product_enrichment():
    """GET-only model/görsel enrichment; müşteri/sipariş verisi döndürmez."""
    raw = (request.args.get('barcodes') or '').strip()
    barcodes = [part.strip() for part in raw.split(',') if part.strip()][:500]
    payload = get_product_enrichment(barcodes)
    return jsonify({
        'ok': True,
        'ready': bool(payload.get('ready')),
        'items': payload.get('items') or {},
        'secrets_logged': False,
    })


@online_eticaret_bp.route('/')
@online_eticaret_bp.route('')
@login_gerekli
def index():
    # Mobil UA → mobil ekrana yönlendir (force=desktop ile geçilebilir)
    if _is_mobile_ua(request) and request.args.get('force') != 'desktop':
        return redirect('/online-eticaret/mobil/')

    if not session.get('kullanici'):
        return redirect(url_for('auth.login', next='/online-eticaret/'))

    _begin_page_metrics('/online-eticaret/')
    flags = _template_flags()
    date_filter      = _parse_date_filter(request)
    force_refresh    = request.args.get('refresh') == '1'
    from modules.online_eticaret.order_poll import (
        end_scope_live_fetch,
        try_begin_scope_live_fetch,
    )
    scope_live_acquired = False
    if force_refresh:
        if try_begin_scope_live_fetch(date_filter):
            scope_live_acquired = True
        else:
            force_refresh = False
    try:
        now_ms           = int(time.time() * 1000)
        start_ms, end_ms = _ms_aralik_for_filter(date_filter)
        _PAGE_METRICS['date_filter'] = date_filter
        hatalar          = []
        magaza_orders    = {}
        magaza_maps      = {}
        image_map_global = {}
        rows_by_store    = {}

        for store_name, (orders, model_map, image_map, hata) in _fetch_magazalar_parallel(
            start_ms, end_ms, date_filter, force_refresh=force_refresh
        ).items():
            if hata:
                hatalar.append(hata)
            else:
                magaza_orders[store_name] = orders
                magaza_maps[store_name]   = model_map
                image_map_global.update(image_map)

        # Created/Picking dedupe koruması
        magaza_orders = _dedupe_orders_by_package(magaza_orders)

        cache_yasi_sn = _cache_age_seconds(date_filter)

        if not magaza_orders:
            html = render_template(
                'online_eticaret/index.html',
                api_hata=True,
                hata_mesajlari=hatalar,
                kpi={}, magaza={},
                dagitim=MOCK_DAGITIM, siparisler=[],
                operasyon=MOCK_OPERASYON,
                operasyon_listesi=[],
                date_filter=date_filter,
                date_filter_label=_date_filter_label(date_filter),
                cache_yasi_sn=cache_yasi_sn,
                **flags,
            )
            _finalize_page_metrics(html, row_count=0, package_count=0)
            return html

        kpi          = {'toplam_siparis': 0, 'urun_adedi': 0,
                        'geciken': 0, 'acil_24h': 0,
                        'esleme_eksik': 0, 'paketlenen': 0,
                        'yeni': 0, 'yeni_qty': 0,
                        'isleme_alinan': 0, 'isleme_alinan_qty': 0}
        magaza_stats = {}
        tum_rows     = []

        for store_name, orders in magaza_orders.items():
            mmap  = magaza_maps.get(store_name, {})
            stats = dashboard_stats(orders, mmap, now_ms)
            rows  = orders_to_rows(orders, store_name, mmap, now_ms)

            kpi['toplam_siparis'] += stats['total_orders']
            kpi['urun_adedi']     += stats['total_qty']
            kpi['geciken']        += stats['delayed_orders']
            kpi['acil_24h']       += stats['urgent']
            kpi['yeni']           += stats['created_orders']
            kpi['yeni_qty']       += stats['created_qty']
            kpi['isleme_alinan']  += stats['picking_orders']
            kpi['isleme_alinan_qty'] += stats['picking_qty']

            magaza_stats[store_name] = {
                'siparis': stats['total_orders'],
                'adet':    stats['total_qty'],
                'geciken': stats['delayed_orders'],
            }
            rows_by_store[store_name] = rows
            tum_rows.extend(rows)

        def _siralama_key(row):
            g = str(row[_IDX_GECIKME] or '')
            if g.startswith('GECİKTİ'): return 0
            if g.startswith('Kalan:'):  return 1
            return 2

        tum_rows.sort(key=_siralama_key)
        siparisler        = _rows_to_siparis(tum_rows)
        pkg_date_ms = {}
        for orders in magaza_orders.values():
            pkg_date_ms.update(pkg_order_date_map(orders))
        operasyon_listesi = _build_operasyon_listesi(rows_by_store, image_map_global, pkg_date_ms)
        paketler          = _group_paketler(operasyon_listesi)
        seed_snapshot_from_items(date_filter, operasyon_listesi)

        now_tr = datetime.now(TZ_TURKEY)
        _tr_months = (
            'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran',
            'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık',
        )
        _tr_days = ('Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar')
        server_now_display = now_tr.strftime('%d.%m.%Y %H:%M')
        today_summary_label = (
            f'{now_tr.day} {_tr_months[now_tr.month - 1]} {now_tr.year}, '
            f'{_tr_days[now_tr.weekday()]}'
        )
        html = render_template(
            'online_eticaret/index.html',
            api_hata=bool(hatalar),
            hata_mesajlari=hatalar,
            kpi=kpi,
            magaza=magaza_stats,
            dagitim=MOCK_DAGITIM,
            siparisler=siparisler,
            operasyon=MOCK_OPERASYON,
            operasyon_listesi=operasyon_listesi,
            paketler=paketler,
            date_filter=date_filter,
            date_filter_label=_date_filter_label(date_filter),
            cache_yasi_sn=cache_yasi_sn,
            server_now_display=server_now_display,
            today_summary_label=today_summary_label,
            poll_cursor=get_snapshot_cursor() if date_filter in (DATE_FILTER_TODAY, DATE_FILTER_OPEN) else '',
            poll_interval_seconds=get_order_poll_interval_seconds(),
            **flags,
        )
        _finalize_page_metrics(
            html,
            row_count=len(operasyon_listesi),
            package_count=len(paketler),
        )
        return html
    finally:
        if scope_live_acquired:
            end_scope_live_fetch(date_filter)


# ── Mobil Route ────────────────────────────────────────────────────────────

@online_eticaret_bp.route('/mobil/')
@online_eticaret_bp.route('/mobil')
@login_gerekli
def mobil():
    """
    FAZ3: Mobil depo operasyon ekranı.
    Sadece GET — Trendyol POST yok, Korgun yok, stok yok, DB yok.
    Toplandı butonu client-side only.
    """
    # force=web parametresiyle masaüstüne dönülebilir
    if request.args.get('force') == 'web':
        return redirect('/online-eticaret/')

    _begin_page_metrics('/online-eticaret/mobil/')
    flags = _template_flags()
    date_filter = _parse_date_filter(request)
    force_refresh = request.args.get('refresh') == '1'
    _PAGE_METRICS['date_filter'] = date_filter
    operasyon_listesi, api_hata, hatalar = _fetch_operasyon_listesi(
        date_filter, force_refresh=force_refresh
    )
    paketler = _group_paketler(operasyon_listesi)
    cache_yasi_sn = _cache_age_seconds(date_filter)

    html = render_template(
        'online_eticaret/mobil.html',
        operasyon_listesi=operasyon_listesi,
        paketler=paketler,
        api_hata=api_hata,
        hata_mesajlari=hatalar,
        toplam=len(paketler),
        date_filter=date_filter,
        date_filter_label=_date_filter_label(date_filter),
        cache_yasi_sn=cache_yasi_sn,
        **flags,
    )
    _finalize_page_metrics(
        html,
        row_count=len(operasyon_listesi),
        package_count=len(paketler),
    )
    return html
