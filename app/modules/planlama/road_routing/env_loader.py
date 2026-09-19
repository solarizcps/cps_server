# -*- coding: utf-8 -*-
"""Load routing secrets from project .env — disk wins for routing keys."""
from __future__ import annotations

import os
from pathlib import Path

_ROUTING_KEYS = frozenset({
    'ORS_API_KEY',
    'GOOGLE_ROUTES_API_KEY',
    'ARAC_ROUTING_PROVIDER',
    'ORS_PROFILE',
    'ARAC_ROUTING_TIMEOUT',
})

_ALIASES = {
    'ORS_ROUTING_TIMEOUT': 'ARAC_ROUTING_TIMEOUT',
}


def _project_root() -> Path:
    # app/modules/planlama/road_routing/env_loader.py -> repo root
    return Path(__file__).resolve().parents[4]


def _routing_env_file() -> Path | None:
    """Preview/production routing secrets — never log values."""
    explicit = (os.environ.get('CPS_ROUTING_ENV_FILE') or '').strip()
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    default = _project_root() / '.env'
    return default if default.is_file() else None


def routing_env_key_status() -> dict[str, str]:
    """PRESENT/MISSING only — safe for logs and reports."""
    load_routing_env(force_routing=False)
    out: dict[str, str] = {}
    for key in sorted(_ROUTING_KEYS):
        out[key] = 'PRESENT' if (os.environ.get(key) or '').strip() else 'MISSING'
    env_file = _routing_env_file()
    out['CPS_ROUTING_ENV_FILE'] = 'PRESENT' if env_file else 'MISSING'
    return out


def load_routing_env(force_routing: bool = True) -> None:
    """Parse .env with BOM/quote normalization; optionally override routing os.environ."""
    env_path = _routing_env_file()
    if not env_path:
        return
    parsed: dict[str, str] = {}
    for raw in env_path.read_bytes().decode('utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
            v = v[1:-1]
        v = v.strip()
        if k in _ALIASES:
            k = _ALIASES[k]
        if k in _ROUTING_KEYS:
            parsed[k] = v
    for k, v in parsed.items():
        if force_routing or k not in os.environ:
            os.environ[k] = v


def routing_key_metadata() -> dict:
    key = (os.environ.get('ORS_API_KEY') or '').strip()
    return {
        'present': bool(key),
        'length': len(key),
        'provider': os.environ.get('ARAC_ROUTING_PROVIDER'),
        'profile': os.environ.get('ORS_PROFILE'),
        'timeout': os.environ.get('ARAC_ROUTING_TIMEOUT'),
    }


def ors_key_present() -> bool:
    return bool((os.environ.get('ORS_API_KEY') or '').strip())


def google_routes_key_present() -> bool:
    return bool((os.environ.get('GOOGLE_ROUTES_API_KEY') or '').strip())
