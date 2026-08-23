# -*- coding: utf-8 -*-
"""Araç Takip V1.2 — kayıtlı lokasyon master, iş talebi snapshot, arama."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import threading
import urllib.error
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

MAPS_COORD_USER_ERROR = (
    'Bu Google Maps bağlantısından konum bulunamadı. '
    'Google Maps\'te Paylaş > Bağlantıyı kopyala ile tekrar deneyin.'
)

_GOOGLE_MAPS_HOSTS = frozenset({
    'maps.google.com',
    'www.google.com',
    'google.com',
    'maps.app.goo.gl',
    'goo.gl',
    'www.google.com.tr',
    'google.com.tr',
})

_SHORT_LINK_HOSTS = frozenset({'maps.app.goo.gl', 'goo.gl'})

_COORD_PATTERNS = (
    r'@(-?\d+\.\d+),(-?\d+\.\d+)',
    r'[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)',
    r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)',
)

_REDIRECT_TIMEOUT_S = 4.0
_MAX_REDIRECTS = 8

_STORE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'arac_takip')
_STORE_FILE = os.path.join(_STORE_DIR, 'store.json')
_LOCK = threading.Lock()

_SEED_LOCATIONS = [
    {
        'firma': 'AVEL Avrupa Elektrik',
        'kisi': 'Mehmet Bey',
        'telefon': '0532 111 2233',
        'adres': 'Tuzla OSB, İstanbul',
        'latitude': 40.818,
        'longitude': 29.305,
        'maps_url': 'https://maps.google.com/?q=40.818,29.305',
    },
    {
        'firma': 'Anıl Torna',
        'kisi': 'Anıl Usta',
        'telefon': '0533 444 5566',
        'adres': 'Pendik, İstanbul',
        'latitude': 40.876,
        'longitude': 29.234,
        'maps_url': 'https://maps.google.com/?q=40.876,29.234',
    },
    {
        'firma': 'B Lojistik',
        'kisi': 'Ayşe Hanım',
        'telefon': '0216 555 0101',
        'adres': 'Çayırova Mah., Kocaeli',
        'latitude': 40.825,
        'longitude': 29.372,
        'maps_url': '',
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _norm_firma(value: str) -> str:
    return re.sub(r'\s+', ' ', (value or '').strip().lower())


def _norm_phone(value: str) -> str:
    return re.sub(r'\D', '', value or '')


def _norm_adres(value: str) -> str:
    return re.sub(r'\s+', ' ', (value or '').strip().lower())


def _short_adres(adres: str, limit: int = 42) -> str:
    s = (adres or '').strip()
    return s if len(s) <= limit else s[: limit - 1] + '…'


def _host_allowed(host: str | None) -> bool:
    h = (host or '').lower().rstrip('.')
    if not h:
        return False
    if h in _GOOGLE_MAPS_HOSTS:
        return True
    return h.endswith('.google.com') or h.endswith('.goo.gl')


def _host_ips_safe(host: str) -> bool:
    try:
        for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
            ip = info[4][0]
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                return False
            if (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_multicast
                or addr.is_reserved
            ):
                return False
    except OSError:
        return False
    return True


def _extract_coords_from_url(url: str) -> tuple[float | None, float | None]:
    if not url:
        return None, None
    for pattern in _COORD_PATTERNS:
        m = re.search(pattern, url)
        if m:
            return float(m.group(1)), float(m.group(2))
    return None, None


def resolve_google_maps_url(maps_url: str, timeout: float = _REDIRECT_TIMEOUT_S) -> str | None:
    """Follow Google Maps short-link redirects; allowlisted hosts only."""
    url = (maps_url or '').strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return None
    host = (parsed.hostname or '').lower()
    if not _host_allowed(host):
        return None
    if not _host_ips_safe(host):
        return None

    lat, lng = _extract_coords_from_url(url)
    if lat is not None and host not in _SHORT_LINK_HOSTS:
        return url

    current = url
    for _ in range(_MAX_REDIRECTS):
        p = urlparse(current)
        hop_host = (p.hostname or '').lower()
        if not _host_allowed(hop_host):
            return None
        if not _host_ips_safe(hop_host):
            return None

        req = urllib.request.Request(
            current,
            method='GET',
            headers={'User-Agent': 'CPS-AracTakip/1.0', 'Accept': 'text/html,*/*'},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                final = resp.geturl() or current
                lat, lng = _extract_coords_from_url(final)
                if lat is not None:
                    return final
                body = resp.read(65536).decode('utf-8', errors='ignore')
                for pattern in _COORD_PATTERNS:
                    m = re.search(pattern, body)
                    if m:
                        return final
                return final if hop_host not in _SHORT_LINK_HOSTS else None
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                loc = exc.headers.get('Location') or exc.headers.get('location')
                if not loc:
                    return None
                current = urllib.request.urljoin(current, loc)
                lat, lng = _extract_coords_from_url(current)
                if lat is not None:
                    return current
                continue
            return None
        except (urllib.error.URLError, TimeoutError, ValueError):
            return None
    return None


def parse_maps_coords(maps_url: str, *, resolve_redirects: bool = True) -> tuple[float | None, float | None]:
    """Extract lat/lng from Google Maps URL; optional short-link redirect resolve."""
    url = (maps_url or '').strip()
    if not url:
        return None, None

    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return None, None
    host = (parsed.hostname or '').lower()
    if not _host_allowed(host):
        return None, None
    if not _host_ips_safe(host):
        return None, None

    lat, lng = _extract_coords_from_url(url)
    if lat is not None:
        return lat, lng

    needs_resolve = resolve_redirects and host in _SHORT_LINK_HOSTS
    if needs_resolve:
        resolved = resolve_google_maps_url(url)
        if resolved:
            lat, lng = _extract_coords_from_url(resolved)
            if lat is not None:
                return lat, lng

    return None, None


def _ensure_store() -> dict[str, Any]:
    os.makedirs(_STORE_DIR, exist_ok=True)
    if not os.path.isfile(_STORE_FILE):
        now = _now_iso()
        locations = []
        for seed in _SEED_LOCATIONS:
            locations.append({
                'id': f'loc-{uuid4().hex[:8]}',
                'created_at': now,
                'created_by_user_id': 0,
                **seed,
            })
        data = {'locations': locations, 'requests': []}
        with open(_STORE_FILE, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        return data
    with open(_STORE_FILE, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def _save_store(data: dict[str, Any]) -> None:
    os.makedirs(_STORE_DIR, exist_ok=True)
    with open(_STORE_FILE, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _load() -> dict[str, Any]:
    with _LOCK:
        return _ensure_store()


def _persist(data: dict[str, Any]) -> None:
    with _LOCK:
        _save_store(data)


def _location_dto(loc: dict, usage: dict | None = None) -> dict:
    usage = usage or {}
    lat = loc.get('latitude')
    lng = loc.get('longitude')
    return {
        'id': loc['id'],
        'firma': loc.get('firma', ''),
        'kisi': loc.get('kisi', ''),
        'telefon': loc.get('telefon', ''),
        'adres': loc.get('adres', ''),
        'latitude': lat,
        'longitude': lng,
        'maps_url': loc.get('maps_url', ''),
        'short_adres': _short_adres(loc.get('adres', '')),
        'has_location': lat is not None and lng is not None,
        'last_used_at': usage.get('last_used_at'),
        'usage_count': usage.get('usage_count', 0),
    }


def _derive_usage(data: dict[str, Any]) -> dict[str, dict]:
    """Derive last_used_at / usage_count from canonical request history only."""
    usage: dict[str, dict] = {}
    for req in data.get('requests') or []:
        loc_id = req.get('location_master_id')
        if not loc_id:
            continue
        ts = req.get('created_at') or ''
        bucket = usage.setdefault(loc_id, {'usage_count': 0, 'last_used_at': None})
        bucket['usage_count'] += 1
        if not bucket['last_used_at'] or ts > bucket['last_used_at']:
            bucket['last_used_at'] = ts
    return usage


def find_duplicate_location(locations: list[dict], candidate: dict) -> dict | None:
    nf = _norm_firma(candidate.get('firma', ''))
    if not nf:
        return None
    np = _norm_phone(candidate.get('telefon', ''))
    na = _norm_adres(candidate.get('adres', ''))
    lat = candidate.get('latitude')
    lng = candidate.get('longitude')
    for existing in locations:
        if _norm_firma(existing.get('firma', '')) != nf:
            continue
        if np and _norm_phone(existing.get('telefon', '')) == np:
            return existing
        if na and _norm_adres(existing.get('adres', '')) == na:
            return existing
        if (
            lat is not None and lng is not None
            and existing.get('latitude') is not None
            and existing.get('longitude') is not None
            and abs(float(lat) - float(existing['latitude'])) < 0.0001
            and abs(float(lng) - float(existing['longitude'])) < 0.0001
        ):
            return existing
    return None


def search_locations(query: str, limit: int = 12) -> list[dict]:
    from modules.planlama.arac_takip_repo import search_locations as db_search, tables_ready
    if tables_ready():
        return db_search(query, limit)
    q = (query or '').strip().lower()
    data = _load()
    usage = _derive_usage(data)
    rows = [_location_dto(loc, usage.get(loc['id'])) for loc in data.get('locations') or []]
    if not q:
        return rows[:limit]
    digits = _norm_phone(q)
    out = []
    for row in rows:
        hay = ' '.join([
            row.get('firma', ''),
            row.get('kisi', ''),
            row.get('telefon', ''),
            row.get('adres', ''),
        ]).lower()
        if q in hay or (digits and digits in _norm_phone(row.get('telefon', ''))):
            out.append(row)
        if len(out) >= limit:
            break
    return out


def get_location_suggestions(user_id: int, recent_limit: int = 5, frequent_limit: int = 5) -> dict:
    from modules.planlama.arac_takip_repo import get_location_suggestions as db_sug, tables_ready
    if tables_ready():
        return db_sug(recent_limit, frequent_limit)
    data = _load()
    usage = _derive_usage(data)
    loc_by_id = {loc['id']: loc for loc in data.get('locations') or []}

    recent_ids: list[str] = []
    for req in reversed(data.get('requests') or []):
        lid = req.get('location_master_id')
        if lid and lid in loc_by_id and lid not in recent_ids:
            recent_ids.append(lid)
        if len(recent_ids) >= recent_limit:
            break

    frequent_sorted = sorted(
        usage.items(),
        key=lambda item: (item[1].get('usage_count', 0), item[1].get('last_used_at') or ''),
        reverse=True,
    )
    frequent_ids = [lid for lid, _ in frequent_sorted if lid in loc_by_id][:frequent_limit]

    return {
        'recent': [_location_dto(loc_by_id[lid], usage.get(lid)) for lid in recent_ids],
        'frequent': [_location_dto(loc_by_id[lid], usage.get(lid)) for lid in frequent_ids if lid not in recent_ids],
    }


def get_location_by_id(location_id: str) -> dict | None:
    data = _load()
    usage = _derive_usage(data)
    for loc in data.get('locations') or []:
        if loc['id'] == location_id:
            return _location_dto(loc, usage.get(loc['id']))
    return None


def _build_snapshot(payload: dict) -> dict:
    lat = payload.get('latitude')
    lng = payload.get('longitude')
    maps_url = (payload.get('maps_url') or payload.get('konum_linki') or '').strip()
    if lat in ('', None) or lng in ('', None):
        parsed_lat, parsed_lng = parse_maps_coords(maps_url)
        if lat in ('', None):
            lat = parsed_lat
        if lng in ('', None):
            lng = parsed_lng
    try:
        lat = float(lat) if lat not in ('', None) else None
    except (TypeError, ValueError):
        lat = None
    try:
        lng = float(lng) if lng not in ('', None) else None
    except (TypeError, ValueError):
        lng = None
    return {
        'firma': (payload.get('firma') or '').strip(),
        'kisi': (payload.get('kisi') or '').strip(),
        'telefon': (payload.get('telefon') or '').strip(),
        'adres': (payload.get('adres') or '').strip(),
        'latitude': lat,
        'longitude': lng,
        'maps_url': maps_url,
    }


def create_job_request(session_user_id: int, payload: dict) -> dict:
    from modules.planlama.arac_takip_repo import create_is_talebi, tables_ready
    if tables_ready():
        return create_is_talebi(session_user_id, payload)
    data = _load()
    snapshot = _build_snapshot(payload)
    save_to_master = bool(payload.get('save_to_master'))
    location_master_id = payload.get('location_master_id') or None
    master_action = 'none'

    try:
        talep_eden_user_id = int(payload.get('talep_eden_user_id') or session_user_id or 0)
    except (TypeError, ValueError):
        talep_eden_user_id = int(session_user_id or 0)
    talep_eden_adi = (payload.get('talep_eden_adi') or payload.get('talep_eden') or '').strip()

    if save_to_master and snapshot['firma']:
        candidate = deepcopy(snapshot)
        dup = find_duplicate_location(data.get('locations') or [], candidate)
        if dup:
            location_master_id = dup['id']
            master_action = 'duplicate_reused'
        else:
            new_loc = {
                'id': f'loc-{uuid4().hex[:8]}',
                'created_at': _now_iso(),
                'created_by_user_id': session_user_id,
                **snapshot,
            }
            data.setdefault('locations', []).append(new_loc)
            location_master_id = new_loc['id']
            master_action = 'created'
    elif location_master_id:
        master_action = 'linked_existing'

    req = {
        'id': f'req-{uuid4().hex[:8]}',
        'status': 'BEKLIYOR',
        'talep_eden_user_id': talep_eden_user_id,
        'talep_eden_adi': talep_eden_adi,
        'talep_eden': talep_eden_adi,
        'olusturan_user_id': int(session_user_id or 0),
        'tarih': payload.get('tarih') or '',
        'istenen_saat': payload.get('istenen_saat') or '',
        'is': payload.get('is') or payload.get('yapilacak_is') or '',
        'oncelik': payload.get('oncelik') or 'NORMAL',
        'not': payload.get('not') or '',
        'location_master_id': location_master_id,
        'save_to_master': save_to_master,
        'master_action': master_action,
        'snapshot': snapshot,
        'created_at': _now_iso(),
    }
    data.setdefault('requests', []).append(req)
    _persist(data)
    return req


def list_requests() -> list[dict]:
    return deepcopy(_load().get('requests') or [])


def reset_store_for_tests() -> None:
    """Test helper — wipe persisted store."""
    with _LOCK:
        if os.path.isfile(_STORE_FILE):
            os.remove(_STORE_FILE)
        _ensure_store()
