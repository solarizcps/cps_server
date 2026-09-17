# -*- coding: utf-8 -*-
"""In-memory order polling snapshot and diff (GET-only, no PII)."""
from __future__ import annotations

import copy
import hashlib
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from modules.online_eticaret.config_store import STORE_NAMES, get_store, is_store_configured
from modules.online_eticaret import trendyol_client as tc
from modules.online_eticaret.excel_export import pkg_order_date_map

FETCH_STATUSES = ['Picking', 'Created']
ORDER_POLL_INTERVAL_ENV = 'ORDER_POLL_INTERVAL_SECONDS'
DEFAULT_POLL_INTERVAL_SECONDS = 15
MIN_POLL_INTERVAL_SECONDS = 15
POLL_INTERVAL_VISIBLE_SECONDS = DEFAULT_POLL_INTERVAL_SECONDS
BACKOFF_STEPS = (60, 120, 300)


def resolve_order_poll_interval_seconds(raw=None):
    """Validate poll interval: default 30, min 15, invalid -> 30."""
    if raw is None:
        raw = os.environ.get(ORDER_POLL_INTERVAL_ENV, '')
    text = str(raw).strip()
    if not text:
        return DEFAULT_POLL_INTERVAL_SECONDS
    try:
        value = int(text)
    except (TypeError, ValueError):
        return DEFAULT_POLL_INTERVAL_SECONDS
    if value < MIN_POLL_INTERVAL_SECONDS:
        return MIN_POLL_INTERVAL_SECONDS
    return value


def get_order_poll_interval_seconds():
    return resolve_order_poll_interval_seconds()
_STORE_WORKERS = 2

_POLL_LOCK = threading.Lock()
_POLL_IN_FLIGHT = False
_SNAPSHOT = {
    'date_filter': None,
    'packages': {},
    'last_check_at': None,
    'cursor': None,
}
_CONSECUTIVE_ERRORS = 0
_POLL_STATS = {
    'poll_runs': 0,
    'new_packages': 0,
    'updated_packages': 0,
    'removed_packages': 0,
    'duplicate_blocked': 0,
}


def package_identity_key(store_name, pkg_id):
    return f'{store_name}|{pkg_id}'


def line_identity_key(store_name, pkg_id, barkod, line_index):
    return f'{store_name}|{pkg_id}|{barkod}|{line_index}'


def reset_order_poll_state():
    global _CONSECUTIVE_ERRORS
    with _POLL_LOCK:
        _SNAPSHOT['date_filter'] = None
        _SNAPSHOT['packages'] = {}
        _SNAPSHOT['last_check_at'] = None
        _SNAPSHOT['cursor'] = None
        _CONSECUTIVE_ERRORS = 0
        for key in _POLL_STATS:
            _POLL_STATS[key] = 0


def get_order_poll_stats():
    with _POLL_LOCK:
        return dict(_POLL_STATS)


def get_snapshot_cursor():
    with _POLL_LOCK:
        return _SNAPSHOT.get('cursor')


def _line_fingerprint(item):
    """Stable operasyon fields only — excludes time-derived kalan/aciliyet and async gorsel."""
    parts = [
        str(item.get('barkod', '')),
        str(item.get('adet', '')),
        str(item.get('urun', '')),
        str(item.get('renk_urun', '')),
        str(item.get('beden', '')),
        str(item.get('kargo', '')),
        str(item.get('kargo_barkod', '')),
    ]
    return '|'.join(parts)


def _package_fingerprint(items):
    payload = '||'.join(sorted(_line_fingerprint(item) for item in items))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]


def _sanitize_operasyon_item(item):
    allowed = (
        'magaza', 'trendyol_status', 'aciliyet', 'gorsel', 'no', 'pkg_id', 'kargo_barkod',
        'siparis_tarihi', 'siparis_tarihi_ms',
        'urun', 'model', 'renk_urun', 'beden', 'adet', 'barkod', 'kargo',
        'kalan', 'durum', 'durum_renk',
    )
    return {key: copy.deepcopy(item.get(key)) for key in allowed if key in item}


def _group_items_by_package(items):
    grouped = {}
    order = []
    for item in items:
        pkg_id = str(item.get('pkg_id') or item.get('no') or '').strip()
        store = str(item.get('magaza') or '').strip()
        if not pkg_id or not store:
            continue
        key = package_identity_key(store, pkg_id)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(_sanitize_operasyon_item(item))
    return order, grouped


def seed_snapshot_from_items(date_filter, operasyon_items):
    order, grouped = _group_items_by_package(operasyon_items or [])
    packages = {}
    for key in order:
        items = grouped[key]
        packages[key] = {
            'fingerprint': _package_fingerprint(items),
            'items': items,
        }
    checked_at = time.time()
    with _POLL_LOCK:
        _SNAPSHOT['date_filter'] = date_filter
        _SNAPSHOT['packages'] = packages
        _SNAPSHOT['last_check_at'] = checked_at
        _SNAPSHOT['cursor'] = str(int(checked_at * 1000))


def _fetch_store_orders_poll(store_name, start_ms, end_ms):
    if not is_store_configured(store_name):
        return [], {}, {}, 'missing_credentials'
    cfg = get_store(store_name)
    seller_id = cfg['sellerId']
    api_key = cfg['apiKey']
    api_secret = cfg['apiSecret']
    orders = []
    try:
        for status in FETCH_STATUSES:
            orders.extend(
                tc.fetch_orders(seller_id, api_key, api_secret, status, start_ms, end_ms)
            )
    except tc.TrendyolError as exc:
        code = 'http_429' if '429' in str(exc) else 'api_error'
        return [], {}, {}, code
    model_map, image_map = tc.get_product_cache_maps(seller_id)
    return orders, model_map, image_map, None


def _fetch_orders_poll_parallel(start_ms, end_ms, build_rows_fn, build_list_fn):
    rows_by_store = {}
    image_map_global = {}
    errors = []

    def worker(store_name):
        orders, model_map, image_map, err = _fetch_store_orders_poll(
            store_name, start_ms, end_ms
        )
        if err:
            return store_name, None, None, None, err
        rows = build_rows_fn(orders, store_name, model_map)
        return store_name, rows, image_map, orders, None

    pkg_date_ms = {}
    with ThreadPoolExecutor(max_workers=_STORE_WORKERS) as pool:
        futures = {name: pool.submit(worker, name) for name in STORE_NAMES}
        for store_name in STORE_NAMES:
            _, rows, image_map, orders, err = futures[store_name].result()
            if err:
                errors.append(err)
            elif rows is not None:
                rows_by_store[store_name] = rows
                image_map_global.update(image_map or {})
                if orders:
                    pkg_date_ms.update(pkg_order_date_map(orders))

    operasyon_listesi = build_list_fn(rows_by_store, image_map_global, pkg_date_ms)
    return operasyon_listesi, errors


def _backoff_seconds():
    if _CONSECUTIVE_ERRORS <= 0:
        return get_order_poll_interval_seconds()
    idx = min(_CONSECUTIVE_ERRORS - 1, len(BACKOFF_STEPS) - 1)
    hinted = tc.get_retry_after_hint()
    if hinted is not None:
        return max(int(hinted), BACKOFF_STEPS[idx])
    return BACKOFF_STEPS[idx]


def check_order_updates(date_filter, since_cursor, build_rows_fn, build_list_fn, ms_range_fn):
    global _POLL_IN_FLIGHT, _CONSECUTIVE_ERRORS

    if date_filter != 'today':
        return {
            'ok': False,
            'error': 'unsupported_filter',
            'backoff_seconds': get_order_poll_interval_seconds(),
        }

    with _POLL_LOCK:
        if _POLL_IN_FLIGHT:
            _POLL_STATS['duplicate_blocked'] += 1
            return {
                'ok': True,
                'busy': True,
                'retry_after_seconds': 5,
                'backoff_seconds': get_order_poll_interval_seconds(),
            }
        _POLL_IN_FLIGHT = True

    started = time.perf_counter()
    metrics_before = tc.get_client_metrics()
    product_http_before = int(metrics_before.get('product_http_attempts', 0) or 0)

    try:
        start_ms, end_ms = ms_range_fn(date_filter)
        operasyon_listesi, errors = _fetch_orders_poll_parallel(
            start_ms, end_ms, build_rows_fn, build_list_fn
        )
        if errors:
            _CONSECUTIVE_ERRORS += 1
            return {
                'ok': False,
                'error': errors[0],
                'poll_ms': round((time.perf_counter() - started) * 1000, 2),
                'backoff_seconds': _backoff_seconds(),
                'product_http_delta': 0,
            }

        order, grouped = _group_items_by_package(operasyon_listesi)
        current_keys = set(order)
        previous = {}
        with _POLL_LOCK:
            if since_cursor and _SNAPSHOT.get('cursor') == since_cursor:
                previous = copy.deepcopy(_SNAPSHOT.get('packages') or {})
            elif _SNAPSHOT.get('packages'):
                previous = copy.deepcopy(_SNAPSHOT.get('packages') or {})

        new_packages = []
        updated_packages = []
        removed_keys = []
        new_count = 0
        updated_count = 0

        for key in order:
            items = grouped[key]
            fingerprint = _package_fingerprint(items)
            prev = previous.get(key)
            if not prev:
                new_packages.extend(items)
                new_count += 1
            elif prev.get('fingerprint') != fingerprint:
                updated_packages.extend(items)
                updated_count += 1

        for key in previous:
            if key not in current_keys:
                removed_keys.append(key)

        packages_snapshot = {
            key: {
                'fingerprint': _package_fingerprint(grouped[key]),
                'items': grouped[key],
            }
            for key in order
        }
        checked_at = time.time()
        cursor = str(int(checked_at * 1000))

        with _POLL_LOCK:
            _SNAPSHOT['date_filter'] = date_filter
            _SNAPSHOT['packages'] = packages_snapshot
            _SNAPSHOT['last_check_at'] = checked_at
            _SNAPSHOT['cursor'] = cursor
            _CONSECUTIVE_ERRORS = 0
            _POLL_STATS['poll_runs'] += 1
            _POLL_STATS['new_packages'] += new_count
            _POLL_STATS['updated_packages'] += updated_count
            _POLL_STATS['removed_packages'] += len(removed_keys)

        metrics_after = tc.get_client_metrics()
        order_http_delta = int(metrics_after.get('order_http_attempts', 0) or 0) - int(
            metrics_before.get('order_http_attempts', 0) or 0
        )
        product_http_delta = int(metrics_after.get('product_http_attempts', 0) or 0) - product_http_before

        total_packages = len(order)
        return {
            'ok': True,
            'busy': False,
            'checked_at': round(checked_at, 3),
            'cursor': cursor,
            'new_packages': new_packages,
            'updated_packages': updated_packages,
            'removed_package_keys': removed_keys,
            'new_count': new_count,
            'updated_count': updated_count,
            'removed_count': len(removed_keys),
            'total_packages': total_packages,
            'total_rows': len(operasyon_listesi),
            'poll_ms': round((time.perf_counter() - started) * 1000, 2),
            'order_http_delta': order_http_delta,
            'product_http_delta': product_http_delta,
            'backoff_seconds': get_order_poll_interval_seconds(),
            'http_429_count': int(metrics_after.get('order_http_429_count', 0) or 0)
            - int(metrics_before.get('order_http_429_count', 0) or 0),
            'timeout_count': int(metrics_after.get('order_http_timeout_count', 0) or 0)
            - int(metrics_before.get('order_http_timeout_count', 0) or 0),
        }
    finally:
        with _POLL_LOCK:
            _POLL_IN_FLIGHT = False
