# -*- coding: utf-8 -*-
"""Solariz Enjeksiyon ana ekran — login/navigation home contract."""
from __future__ import annotations

from typing import Any, Mapping, Optional

ENJEKSIYON_HOME_PATH = '/enjeksiyon/'

_NEXGEN_URETIM_OP_ROL_ADLAR = frozenset({
    'NexGen Üretim Operatörü',
    'NexGen Uretim Operatoru',
})


def _yk_has(yk: set[str] | frozenset[str], kod: str, action: str = 'can_view') -> bool:
    if '*' in yk:
        return True
    if f'{kod}:{action}' in yk:
        return True
    return kod in yk


def is_enjeksiyon_home_user(
    u: Mapping[str, Any] | None,
    yk: set[str] | frozenset[str] | None,
) -> bool:
    """Enjeksiyon rolü ana kullanıcı — Solariz saha operasyonu (NexGen tablet/AR-GE nav hariç)."""
    if not u or not yk:
        return False
    if '*' in yk:
        return False
    if _yk_has(yk, 'yonetim', 'can_view'):
        return False
    if _yk_has(yk, 'planlama', 'can_view'):
        return False
    rol = (u.get('RolAd') or '').strip()
    if rol != 'Enjeksiyon':
        return False
    if rol in _NEXGEN_URETIM_OP_ROL_ADLAR:
        return False
    return _yk_has(yk, 'enjeksiyon', 'can_view')


def enjeksiyon_home_redirect(
    u: Mapping[str, Any] | None,
    yk: set[str] | frozenset[str] | None,
) -> Optional[str]:
    if is_enjeksiyon_home_user(u, yk):
        return ENJEKSIYON_HOME_PATH
    return None
