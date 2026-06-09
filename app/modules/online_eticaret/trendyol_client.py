"""Trendyol Marketplace (Entegrasyon) API sipariş istemcisi.

Sipariş paketlerini çeker. Trendyol tarih aralığını ~14 günle sınırladığı için
geniş aralıklar otomatik dilimlenir; her dilim sayfa sayfa çekilir.

Resmi doküman: https://developers.trendyol.com  (Order Integration)
"""

import base64
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
        resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise TrendyolError(
            "Trendyol'a bağlanılamadı. İnternet bağlantını kontrol et. "
            f"(Detay: {exc})"
        ) from exc

    if resp.status_code == 429:
        time.sleep(2)
        try:
            resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            raise TrendyolError(f"Trendyol'a bağlanılamadı. (Detay: {exc})") from exc

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

    all_orders = []
    for win_start, win_end in _date_windows(start_ms, end_ms):
        page = 0
        while True:
            data = _get_page(session, seller_id, status, win_start, win_end, page)
            content = data.get("content") or []
            all_orders.extend(content)

            total_pages = data.get("totalPages", 1)
            page += 1
            if page >= total_pages or not content:
                break

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
    seller_id = str(seller_id).strip()

    cached = _PRODUCT_CACHE.get(seller_id)
    if cached and (time.time() - cached[0]) < _PRODUCT_CACHE_TTL:
        return cached[1]

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
    try:
        while True:
            params = {"page": page, "size": PAGE_SIZE}
            resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
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
            if page >= total_pages or not content:
                break
    except requests.RequestException:
        pass  # ağ hatası -> elde olan kadarıyla devam

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
