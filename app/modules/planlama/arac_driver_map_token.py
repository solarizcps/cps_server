# -*- coding: utf-8 -*-
"""Read-only signed token for driver map links (no session)."""
from __future__ import annotations

import hashlib
import hmac


def _secret() -> str:
    try:
        from config import Config
        return str(Config.SECRET_KEY or 'cps-dev-secret-key-change-in-production')
    except Exception:
        return 'cps-dev-secret-key-change-in-production'


def sign_driver_map_token(plan_date: str, vehicle_id: str, plan_id: int) -> str:
    msg = f'{plan_date[:10]}|{str(vehicle_id).strip()}|{int(plan_id)}'
    return hmac.new(_secret().encode('utf-8'), msg.encode('utf-8'), hashlib.sha256).hexdigest()[:32]


def verify_driver_map_token(plan_date: str, vehicle_id: str, plan_id: int, token: str) -> bool:
    if not token or not plan_date or not vehicle_id or not plan_id:
        return False
    expected = sign_driver_map_token(plan_date, vehicle_id, plan_id)
    return hmac.compare_digest(expected, str(token).strip())
