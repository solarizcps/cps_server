# -*- coding: utf-8 -*-
"""Turkcell Filom REST adapter — V2.1 (register + getMobiles)."""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import requests

_log = logging.getLogger('cps.filom')

_CONNECT_TIMEOUT = float(os.environ.get('TURKCELL_FILOM_CONNECT_TIMEOUT', '5'))
_READ_TIMEOUT = float(os.environ.get('TURKCELL_FILOM_READ_TIMEOUT', '20'))
_TOKEN_TTL_SEC = int(os.environ.get('TURKCELL_FILOM_TOKEN_TTL_SEC', '3600'))


def _load_env_file() -> None:
    """Load project .env into os.environ if keys missing (local dev)."""
    root = Path(__file__).resolve().parents[5]
    env_path = root / '.env'
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        k, v = k.strip(), v.strip()
        if k and k not in os.environ:
            os.environ[k] = v


_load_env_file()


@dataclass
class _TokenCache:
    token: Optional[str] = None
    acquired_at: float = 0.0

    def valid(self) -> bool:
        return bool(self.token) and (time.time() - self.acquired_at) < _TOKEN_TTL_SEC

    def clear(self) -> None:
        self.token = None
        self.acquired_at = 0.0


_cache = _TokenCache()


class FilomApiError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, category: str = 'api_error'):
        super().__init__(message)
        self.status = status
        self.category = category


def _cfg() -> Tuple[str, str, str]:
    base = (os.environ.get('TURKCELL_FILOM_BASE_URL') or '').rstrip('/')
    user = os.environ.get('TURKCELL_FILOM_USERNAME') or ''
    pwd = os.environ.get('TURKCELL_FILOM_PASSWORD') or ''
    if not base or not user or not pwd:
        raise FilomApiError('Filom credential yapılandırması eksik', category='config')
    return base, user, pwd


def _log_call(endpoint: str, status: int, elapsed_ms: int, extra: str = '') -> None:
    _log.info('filom provider=%s endpoint=%s status=%s elapsed_ms=%s %s',
              'turkcell_filom', endpoint, status, elapsed_ms, extra.strip())


def authenticate(force: bool = False) -> str:
    if not force and _cache.valid():
        return _cache.token  # type: ignore[return-value]

    base, user, pwd = _cfg()
    url = f'{base}/register'
    t0 = time.perf_counter()
    try:
        r = requests.post(
            url,
            params={'language': 'tr'},
            headers={'username': user, 'password': pwd},
            timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
        )
    except requests.Timeout as e:
        raise FilomApiError('Filom register timeout', category='timeout') from e
    except requests.RequestException as e:
        raise FilomApiError(f'Filom register bağlantı hatası: {e.__class__.__name__}', category='network') from e

    elapsed = int((time.perf_counter() - t0) * 1000)
    _log_call('/register', r.status_code, elapsed)

    if r.status_code == 401:
        raise FilomApiError('Filom yetkilendirme başarısız', status=401, category='auth')
    if r.status_code >= 400:
        raise FilomApiError(f'Filom register HTTP {r.status_code}', status=r.status_code)

    try:
        data = r.json()
    except ValueError as e:
        raise FilomApiError('Filom register JSON parse hatası', category='parse') from e

    token = data.get('token') or data.get('Token')
    if not token:
        raise FilomApiError('Filom token alınamadı', category='auth')

    _cache.token = str(token)
    _cache.acquired_at = time.time()
    return _cache.token


def _fetch_mobiles_raw(token: str) -> List[dict]:
    base, user, _ = _cfg()
    url = f'{base}/mobiles'
    t0 = time.perf_counter()
    try:
        r = requests.get(
            url,
            headers={'token': token, 'username': user},
            timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
        )
    except requests.Timeout as e:
        raise FilomApiError('Filom getMobiles timeout', category='timeout') from e
    except requests.RequestException as e:
        raise FilomApiError(f'Filom getMobiles bağlantı hatası: {e.__class__.__name__}', category='network') from e

    elapsed = int((time.perf_counter() - t0) * 1000)
    _log_call('/mobiles', r.status_code, elapsed)

    if r.status_code == 401:
        raise FilomApiError('Filom token geçersiz', status=401, category='auth')
    if r.status_code >= 400:
        raise FilomApiError(f'Filom getMobiles HTTP {r.status_code}', status=r.status_code)

    try:
        data = r.json()
    except ValueError as e:
        raise FilomApiError('Filom getMobiles JSON parse hatası', category='parse') from e

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get('mobile')
        if isinstance(items, list):
            return items
    return []


def normalize_plate_display(plate: str) -> str:
    """Display-only: 34BPY282 → 34 BPY 282. Identity remains mobile_id."""
    compact = re.sub(r'\s+', '', (plate or '').upper())
    if not compact:
        return (plate or '').strip()
    m = re.match(r'^(\d{2})([A-Z]{1,3})(\d{2,4})$', compact)
    if m:
        return f'{m.group(1)} {m.group(2)} {m.group(3)}'
    return (plate or '').strip()


def is_valid_location(lat, lon) -> bool:
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if la == 0.0 and lo == 0.0:
        return False
    return -90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0


def _is_stale(pos_str_time: str) -> bool:
    s = (pos_str_time or '').lower()
    return 'yıl' in s or 'yil' in s or 'ay' in s and 'dk' not in s and 'sa' not in s


def map_activity_status(raw: dict) -> Tuple[str, str]:
    """Forensic mapping from real Filom fields (activityStatus, posSpeed, kontakDurumu)."""
    activity = raw.get('activityStatus')
    speed = float(raw.get('posSpeed') or 0)
    kontak = raw.get('kontakDurumu')
    stale = _is_stale(str(raw.get('posTimestampStrtime') or ''))

    if stale:
        return 'PASIF', 'Pasif'
    if activity == 1 and speed > 3:
        return 'HAREKETLI', 'Hareketli'
    if activity == 1 and kontak == 1:
        return 'ROLANTI', 'Duruyor'
    if kontak == 0 and speed == 0:
        return 'DURAN', 'Duran'
    if activity == 0:
        return 'DURAN', 'Duran'
    return 'BILINMIYOR', '—'


def map_vehicle_dto(raw: dict) -> dict:
    status, status_label = map_activity_status(raw)
    driver = (raw.get('driverInfo') or '').strip() or None
    addr_parts = [raw.get('addr1'), raw.get('addr2')]
    address = ', '.join(p for p in addr_parts if p) or raw.get('lbsLocation') or ''
    plate = (raw.get('alias') or '').strip()
    lat = raw.get('posLatitude')
    lon = raw.get('posLongitude')
    stale_label = str(raw.get('posTimestampStrtime') or '')
    valid_loc = is_valid_location(lat, lon)
    return {
        'id': str(raw.get('mobile') or ''),
        'plate': plate,
        'plate_display': normalize_plate_display(plate),
        'driver_name': driver,
        'brand': raw.get('brand') or '',
        'model': raw.get('model') or '',
        'model_year': raw.get('modelYear') or '',
        'speed_kmh': int(float(raw.get('posSpeed') or 0)),
        'latitude': float(lat) if valid_loc else None,
        'longitude': float(lon) if valid_loc else None,
        'has_valid_location': valid_loc,
        'last_seen_at': raw.get('posTimestamp') or '',
        'last_seen_label': stale_label,
        'is_stale_data': _is_stale(stale_label),
        'address': address,
        'activity_status': status,
        'activity_status_label': status_label,
        'ignition': 'Açık' if raw.get('kontakDurumu') == 1 else 'Kapalı',
        'total_distance_km': round(float(raw.get('totalDistanceTravelled') or 0), 1),
        'in_use': raw.get('kullanimda_flag') == 1,
    }


def compute_kpi(vehicles: List[dict]) -> dict:
    total = len(vehicles)
    active = sum(1 for v in vehicles if v.get('in_use', True))
    moving = sum(1 for v in vehicles if v.get('activity_status') == 'HAREKETLI')
    pct = round(moving / active * 100, 1) if active else 0.0
    return {
        'aktif_arac': active,
        'aktif_arac_toplam': total,
        'hareket_halinde': moving,
        'hareket_pct': pct,
    }


def get_live_vehicles(retry_auth: bool = True) -> dict:
    """Returns {ok, data_source, count, vehicles, kpi, error, elapsed_ms}."""
    t0 = time.perf_counter()
    try:
        token = authenticate()
        raw_list = _fetch_mobiles_raw(token)
    except FilomApiError as e:
        if retry_auth and e.status == 401:
            _cache.clear()
            try:
                token = authenticate(force=True)
                raw_list = _fetch_mobiles_raw(token)
            except FilomApiError as e2:
                elapsed = int((time.perf_counter() - t0) * 1000)
                return {
                    'ok': False,
                    'data_source': 'turkcell_filom',
                    'count': 0,
                    'vehicles': [],
                    'kpi': None,
                    'error': str(e2),
                    'error_category': e2.category,
                    'elapsed_ms': elapsed,
                }
        else:
            elapsed = int((time.perf_counter() - t0) * 1000)
            return {
                'ok': False,
                'data_source': 'turkcell_filom',
                'count': 0,
                'vehicles': [],
                'kpi': None,
                'error': str(e),
                'error_category': e.category,
                'elapsed_ms': elapsed,
            }

    vehicles = [map_vehicle_dto(r) for r in raw_list]
    valid_loc = sum(1 for v in vehicles if v.get('has_valid_location'))
    elapsed = int((time.perf_counter() - t0) * 1000)
    _log_call('get_live_vehicles', 200, elapsed, f'vehicle_count={len(vehicles)} valid_location={valid_loc}')
    return {
        'ok': True,
        'data_source': 'turkcell_filom',
        'count': len(vehicles),
        'valid_location_count': valid_loc,
        'missing_location_count': len(vehicles) - valid_loc,
        'vehicles': vehicles,
        'kpi': compute_kpi(vehicles),
        'error': None,
        'elapsed_ms': elapsed,
    }
