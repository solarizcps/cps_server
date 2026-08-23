# -*- coding: utf-8 -*-
"""Load routing secrets from project .env — disk wins for routing keys."""
from __future__ import annotations

import os
from pathlib import Path

_ROUTING_KEYS = frozenset({
    'ORS_API_KEY',
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


def load_routing_env(force_routing: bool = True) -> None:
    """Parse .env with BOM/quote normalization; optionally override routing os.environ."""
    env_path = _project_root() / '.env'
    if not env_path.is_file():
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
