"""Trendyol Marketplace (Entegrasyon) API sipariş istemcisi.

Sipariş paketlerini çeker. Trendyol tarih aralığını ~14 günle sınırladığı için
geniş aralıklar otomatik dilimlenir; her dilim sayfa sayfa çekilir.

Resmi doküman: https://developers.trendyol.com  (Order Integration)
"""

import base64
import os
import threading
import time

import requests

BASE_URL = "https://apigw.trendyol.com"
PAGE_SIZE = 200
MAX_WINDOW_MS = 14 * 24 * 60 * 60 * 1000  # ~14 gün (Trendyol sınırı)
REQUEST_TIMEOUT = 60

# Ürün bilgisi (barkod -> {model, image}) için basit bellek-içi önbellek.
# Aynı mağaza için 10 dk boyunca tekrar tüm ürünleri çekmeyiz.
_PRODUCT_CACHE = {}  # seller_id -> (timestamp, {barcode: {"model":.., "image":..}})
_PRODUCT_CACHE_TTL = 10 * 60
_PRODUCT_BG_LOCK = threading.Lock()
_PRODUCT_BG_IN_FLIGHT = set()
_METRICS_LOCK = threading.Lock()
_LAST_RETRY_AFTER_SECONDS = None

_CLIENT_METRICS = {
    'api_calls': 0,
    'order_pages': 0,
    'product_pages': 0,
    'product_cache_hits': 0,
    'product_cache_misses': 0,
    '429_retries': 0,
    'order_ms': 0.0,
    'product_ms': 0.0,
    'order_http_attempts': 0,
    'order_http_200_pages': 0,
    'order_http_non_200_count': 0,
    'order_http_429_count': 0,
    'order_http_timeout_count': 0,
    'order_http_status_types': {},
    'product_http_attempts': 0,
    'product_http_200_pages': 0,
    'product_http_non_200_count': 0,
    'product_http_429_count': 0,
    'product_http_timeout_count': 0,
    'product_http_status_types': {},
    'product_function_calls': 0,
    'product_early_return_count': 0,
    'product_early_return_reason_types': {},
    'product_cache_lookups': 0,
    'product_background_workers_started': 0,
    'product_background_duplicate_blocked': 0,
}


def _max_pages():
    try:
        return max(1, int(os.environ.get('API_MAX_PAGES', '20')))
    except (TypeError, ValueError):
        return 20


def _request_timeout():
    try:
        connect = int(os.environ.get('API_CONNECT_TIMEOUT_SECONDS', '5'))
        read = int(os.environ.get('API_READ_TIMEOUT_SECONDS', '30'))
    except (TypeError, ValueError):
        return REQUEST_TIMEOUT
    return (connect, read)


def get_client_metrics():
    with _METRICS_LOCK:
        data = dict(_CLIENT_METRICS)
        data['order_http_status_types'] = dict(_CLIENT_METRICS.get('order_http_status_types') or {})
        data['product_http_status_types'] = dict(_CLIENT_METRICS.get('product_http_status_types') or {})
        data['product_early_return_reason_types'] = dict(
            _CLIENT_METRICS.get('product_early_return_reason_types') or {}
        )
    return data


def reset_client_metrics():
    with _METRICS_LOCK:
        for key in list(_CLIENT_METRICS):
            if key.endswith('_types'):
                _CLIENT_METRICS[key] = {}
            elif key.endswith('_ms'):
                _CLIENT_METRICS[key] = 0.0
            else:
                _CLIENT_METRICS[key] = 0


def get_retry_after_hint():
    return _LAST_RETRY_AFTER_SECONDS


def _capture_retry_after(resp):
    global _LAST_RETRY_AFTER_SECONDS
    raw = resp.headers.get('Retry-After')
    if raw is None:
        return
    try:
        _LAST_RETRY_AFTER_SECONDS = max(1, int(str(raw).strip()))
    except (TypeError, ValueError):
        _LAST_RETRY_AFTER_SECONDS = None


def reset_product_cache():
    with _METRICS_LOCK:
        _PRODUCT_CACHE.clear()
    with _PRODUCT_BG_LOCK:
        _PRODUCT_BG_IN_FLIGHT.clear()


def store_product_cache_entry(seller_id, info):
    """Process-memory product cache write (mock/background safe)."""
    seller_id = str(seller_id).strip()
    with _METRICS_LOCK:
        _PRODUCT_CACHE[seller_id] = (time.time(), info or {})


def _product_cache_entry(seller_id):
    seller_id = str(seller_id).strip()
    with _METRICS_LOCK:
        cached = _PRODUCT_CACHE.get(seller_id)
    if cached and (time.time() - cached[0]) < _PRODUCT_CACHE_TTL:
        return cached[1]
    return None


def is_product_cache_warm(seller_id):
    return _product_cache_entry(seller_id) is not None


def is_product_background_running(seller_id=None):
    with _PRODUCT_BG_LOCK:
        if seller_id is None:
            return bool(_PRODUCT_BG_IN_FLIGHT)
        return str(seller_id).strip() in _PRODUCT_BG_IN_FLIGHT


def get_product_cache_maps(seller_id):
    """Warm product cache -> (model_map, image_map); cold -> empty dicts."""
    info = _product_cache_entry(seller_id) or {}
    model_map = {bc: v['model'] for bc, v in info.items() if v.get('model')}
    image_map = {bc: v['image'] for bc, v in info.items() if v.get('image')}
    return model_map, image_map


def merge_product_cache_maps(model_map, image_map):
    """Merge all warm seller caches (process memory only)."""
    merged_models = dict(model_map or {})
    merged_images = dict(image_map or {})
    with _METRICS_LOCK:
        snapshot = list(_PRODUCT_CACHE.items())
    now = time.time()
    for _seller_id, (cached_at, info) in snapshot:
        if (now - cached_at) >= _PRODUCT_CACHE_TTL:
            continue
        for bc, val in info.items():
            if val.get('model'):
                merged_models.setdefault(bc, val['model'])
            if val.get('image'):
                merged_images.setdefault(bc, val['image'])
    return merged_models, merged_images


def start_product_catalog_background(seller_id, api_key, api_secret):
    """Start one background worker per seller (single-flight)."""
    seller_id = str(seller_id).strip()
    api_key = str(api_key or '').strip()
    api_secret = str(api_secret or '').strip()
    if not (seller_id and api_key and api_secret):
        return False
    if is_product_cache_warm(seller_id):
        return False
    with _PRODUCT_BG_LOCK:
        if seller_id in _PRODUCT_BG_IN_FLIGHT:
            _inc_client_metric('product_background_duplicate_blocked')
            return False
        _PRODUCT_BG_IN_FLIGHT.add(seller_id)
    _inc_client_metric('product_background_workers_started')

    def _worker():
        try:
            fetch_product_info(seller_id, api_key, api_secret)
        except Exception:
            pass
        finally:
            with _PRODUCT_BG_LOCK:
                _PRODUCT_BG_IN_FLIGHT.discard(seller_id)

    threading.Thread(
        target=_worker,
        daemon=True,
        name=f'product-catalog-{seller_id[:12]}',
    ).start()
    return True


def get_product_enrichment(barcodes):
    """Return model/image enrichment for barcodes only; no customer/order payload."""
    needed = []
    seen = set()
    for raw in barcodes or []:
        code = str(raw or '').strip()
        if code and code not in seen:
            seen.add(code)
            needed.append(code)

    items = {}
    for barcode in needed:
        model = ''
        image = ''
        with _METRICS_LOCK:
            snapshot = list(_PRODUCT_CACHE.items())
        now = time.time()
        for _seller_id, (cached_at, info) in snapshot:
            if (now - cached_at) >= _PRODUCT_CACHE_TTL:
                continue
            entry = info.get(barcode)
            if not entry:
                continue
            model = str(entry.get('model') or '')
            image = str(entry.get('image') or '')
            break
        items[barcode] = {'model': model, 'image': image}

    return {
        'ready': not is_product_background_running(),
        'items': items,
    }


def _record_http_status(bucket, resp):
    code = int(resp.status_code)
    with _METRICS_LOCK:
        types = _CLIENT_METRICS[f'{bucket}_http_status_types']
        key = str(code)
        types[key] = types.get(key, 0) + 1
        _CLIENT_METRICS[f'{bucket}_http_attempts'] += 1
        if code == 200:
            _CLIENT_METRICS[f'{bucket}_http_200_pages'] += 1
            _CLIENT_METRICS[f'{bucket}_pages'] += 1
            _CLIENT_METRICS['api_calls'] += 1
        else:
            _CLIENT_METRICS[f'{bucket}_http_non_200_count'] += 1
        if code == 429:
            _CLIENT_METRICS[f'{bucket}_http_429_count'] += 1
            _capture_retry_after(resp)


def _record_product_early_return(reason):
    with _METRICS_LOCK:
        _CLIENT_METRICS['product_early_return_count'] += 1
        reasons = _CLIENT_METRICS['product_early_return_reason_types']
        reasons[reason] = reasons.get(reason, 0) + 1


def _inc_client_metric(key, delta=1):
    with _METRICS_LOCK:
        _CLIENT_METRICS[key] += delta


def _add_client_metric_ms(key, delta_ms):
    with _METRICS_LOCK:
        _CLIENT_METRICS[key] += delta_ms


def record_local_call(kind):
    """Count a mock/dev adapter call (no network). Does not log credentials."""
    if kind == 'order':
        _record_http_status('order', type('Resp', (), {'status_code': 200})())
    elif kind == 'product':
        _inc_client_metric('product_function_calls')
        _inc_client_metric('product_cache_lookups')
        _inc_client_metric('product_cache_misses')
        _record_http_status('product', type('Resp', (), {'status_code': 200})())


class TrendyolError(Exception):
    """Kullanıcıya gösterilecek, okunabilir API hatası."""


def _auth_header(api_key, api_secret):
    raw = f"{api_key}:{api_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _date_windows(start_ms, end_ms):
    """[start, end] aralığını <=14 günlük dilimlere böler."""
    if end_ms < start_ms:
        start_ms, end_ms = end_ms, start_ms
    windows = []
    cursor = start_ms
    while cursor < end_ms:
        window_end = min(cursor + MAX_WINDOW_MS, end_ms)
        windows.append((cursor, window_end))
        cursor = window_end
    if not windows:  # start == end
        windows.append((start_ms, end_ms))
    return windows


def _explain_http_error(resp):
    code = resp.status_code
    if code == 401:
        return TrendyolError(
            "Kimlik doğrulama başarısız (401). API Key veya API Secret hatalı. "
            "Lütfen Trendyol panelindeki 'Entegrasyon Bilgileri'nden kontrol et."
        )
    if code == 403:
        return TrendyolError(
            "Erişim reddedildi (403). Satıcı ID hatalı olabilir ya da bu hesabın "
            "API erişimi açık değildir."
        )
    if code == 429:
        return TrendyolError(
            "Çok fazla istek gönderildi (429). Lütfen biraz bekleyip tekrar dene."
        )
    return TrendyolError(
        f"Trendyol API beklenmedik bir hata döndürdü ({code}). "
        f"Yanıt: {resp.text[:300]}"
    )


def _get_page(session, seller_id, status, start_ms, end_ms, page):
    url = f"{BASE_URL}/integration/order/sellers/{seller_id}/orders"
    params = {
        "status": status,
        "startDate": start_ms,
        "endDate": end_ms,
        "page": page,
        "size": PAGE_SIZE,
        "orderByField": "PackageLastModifiedDate",
        "orderByDirection": "DESC",
    }
    try:
        resp = session.get(url, params=params, timeout=_request_timeout())
    except requests.Timeout as exc:
        _inc_client_metric('order_http_timeout_count')
        raise TrendyolError(
            "Trendyol'a bağlanılamadı. İnternet bağlantını kontrol et. "
            f"(Detay: {exc})"
        ) from exc
    except requests.RequestException as exc:
        raise TrendyolError(
            "Trendyol'a bağlanılamadı. İnternet bağlantını kontrol et. "
            f"(Detay: {exc})"
        ) from exc

    _record_http_status('order', resp)

    if resp.status_code == 429:
        _inc_client_metric('429_retries')
        time.sleep(2)
        try:
            resp = session.get(url, params=params, timeout=_request_timeout())
        except requests.Timeout as exc:
            _inc_client_metric('order_http_timeout_count')
            raise TrendyolError(f"Trendyol'a bağlanılamadı. (Detay: {exc})") from exc
        except requests.RequestException as exc:
            raise TrendyolError(f"Trendyol'a bağlanılamadı. (Detay: {exc})") from exc
        _record_http_status('order', resp)

    if resp.status_code != 200:
        raise _explain_http_error(resp)

    try:
        return resp.json()
    except ValueError as exc:
        raise TrendyolError("Trendyol'dan geçersiz yanıt alındı.") from exc


def fetch_orders(seller_id, api_key, api_secret, status, start_ms, end_ms):
    """Verilen statü ve tarih aralığındaki tüm sipariş paketlerini döndürür.

    Dönen değer: sipariş paketi dict'lerinden oluşan liste (API 'content' kayıtları).
    """
    seller_id = str(seller_id).strip()
    if not (seller_id and api_key and api_secret):
        raise TrendyolError("Satıcı ID, API Key ve API Secret zorunludur.")

    session = requests.Session()
    session.headers.update(
        {
            "Authorization": _auth_header(api_key, api_secret),
            # User-Agent ZORUNLU; gönderilmezse Trendyol 403 döner.
            "User-Agent": f"{seller_id} - SelfIntegration",
            "Accept": "application/json",
        }
    )

    started = time.perf_counter()
    all_orders = []
    cap = _max_pages()
    for win_start, win_end in _date_windows(start_ms, end_ms):
        page = 0
        while True:
            data = _get_page(session, seller_id, status, win_start, win_end, page)
            content = data.get("content") or []
            all_orders.extend(content)

            total_pages = data.get("totalPages", 1)
            page += 1
            if page >= total_pages or page >= cap or not content:
                break

    _add_client_metric_ms('order_ms', (time.perf_counter() - started) * 1000)
    return all_orders


def _first_image(product):
    images = product.get("images") or []
    if images and isinstance(images[0], dict):
        return images[0].get("url") or ""
    return ""


def fetch_product_info(seller_id, api_key, api_secret):
    """Tüm ürünleri gezip {barcode: {"model": productMainId, "image": url}} döndürür.

    productMainId = panelin 'Model Kodu'su (stok kodu boş olsa bile dolu). image =
    ürünün ilk görseli. Sipariş satırındaki barcode ile eşleştirilir. 10 dk önbellekli.
    Hata olursa elde olan kadarıyla (ya da boş) döner; işlem çökmez.
    """
    _inc_client_metric('product_function_calls')
    seller_id = str(seller_id).strip()
    api_key = str(api_key or '').strip()
    api_secret = str(api_secret or '').strip()

    if not seller_id:
        _record_product_early_return('missing_seller_id')
        return {}
    if not api_key:
        _record_product_early_return('missing_api_key')
        return {}
    if not api_secret:
        _record_product_early_return('missing_api_secret')
        return {}

    _inc_client_metric('product_cache_lookups')
    with _METRICS_LOCK:
        cached = _PRODUCT_CACHE.get(seller_id)
    if cached and (time.time() - cached[0]) < _PRODUCT_CACHE_TTL:
        _inc_client_metric('product_cache_hits')
        _record_product_early_return('cached')
        return cached[1]

    _inc_client_metric('product_cache_misses')
    started = time.perf_counter()
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": _auth_header(api_key, api_secret),
            "User-Agent": f"{seller_id} - SelfIntegration",
            "Accept": "application/json",
        }
    )
    url = f"{BASE_URL}/integration/product/sellers/{seller_id}/products"

    info = {}
    page = 0
    cap = _max_pages()
    try:
        while True:
            params = {"page": page, "size": PAGE_SIZE}
            try:
                resp = session.get(url, params=params, timeout=_request_timeout())
            except requests.Timeout:
                _inc_client_metric('product_http_timeout_count')
                break
            except requests.RequestException:
                break

            _record_http_status('product', resp)

            if resp.status_code == 429:
                _inc_client_metric('429_retries')
                time.sleep(2)
                try:
                    resp = session.get(url, params=params, timeout=_request_timeout())
                except requests.Timeout:
                    _inc_client_metric('product_http_timeout_count')
                    break
                except requests.RequestException:
                    break
                _record_http_status('product', resp)

            if resp.status_code != 200:
                break

            data = resp.json()
            content = data.get("content") or []
            for product in content:
                barcode = product.get("barcode")
                if not barcode:
                    continue
                info[str(barcode)] = {
                    "model": str(product.get("productMainId") or ""),
                    "image": _first_image(product),
                }

            total_pages = data.get("totalPages", 1)
            page += 1
            if page >= total_pages or page >= cap or not content:
                break
    except requests.RequestException:
        pass  # ağ hatası -> elde olan kadarıyla devam

    _add_client_metric_ms('product_ms', (time.perf_counter() - started) * 1000)
    with _METRICS_LOCK:
        _PRODUCT_CACHE[seller_id] = (time.time(), info)
    return info


def fetch_product_model_map(seller_id, api_key, api_secret):
    """{barcode: productMainId} (model kodu) haritası. Excel için kullanılır."""
    info = fetch_product_info(seller_id, api_key, api_secret)
    return {bc: v["model"] for bc, v in info.items() if v.get("model")}


def fetch_product_image_map(seller_id, api_key, api_secret):
    """{barcode: görsel URL} haritası. Arayüzdeki önizleme için kullanılır."""
    info = fetch_product_info(seller_id, api_key, api_secret)
    return {bc: v["image"] for bc, v in info.items() if v.get("image")}
