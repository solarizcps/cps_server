# -*- coding: utf-8 -*-
"""
Ödeme Planı yetki anayasası — P1.1 VIEW hazırlığı.

Canonical VIEW: finans.odeme_plani.write:can_view
(migration 120 — can_view P2/P3 write ayrımı için aynı kod, action farklı)

Gelecek write (P3+): finans.odeme_plani.write:can_create / can_update
Şirket kısıtı (ileride): allowed_locations(user) — şimdilik tüm canonical location.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Set

try:
    from modules.auth import is_superadmin, yetki_var
except ImportError:
    from app.modules.auth import is_superadmin, yetki_var

from modules.finans.services.korgun_finance_adapter import CANONICAL_LOCATION_CODES

# Canonical permission codes (sistem_yetki — migration 120)
YETKI_ODEME_PLANI = 'finans.odeme_plani.write'
YETKI_FINANS_MODUL = 'finans'


def can_odeme_plani_view(user_dict: Optional[Dict[str, Any]] = None, yk: Optional[Set[str]] = None) -> bool:
    """
    Ödeme Planı ekranı VIEW yetkisi.
    Hardcoded kullanıcı adı YOK — yalnız sistem_yetki / rol / override.
    """
    if not user_dict:
        return False
    if is_superadmin(user_dict):
        return True
    if yk is None:
        return (
            yetki_var(YETKI_ODEME_PLANI, 'can_view')
            or yetki_var(YETKI_FINANS_MODUL, 'can_view')
        )
    if '*' in yk:
        return True
    if f'{YETKI_ODEME_PLANI}:can_view' in yk:
        return True
    if f'{YETKI_FINANS_MODUL}:can_view' in yk or f'{YETKI_FINANS_MODUL}.goruntule' in yk:
        return True
    return False


def can_odeme_plani_write(user_dict: Optional[Dict[str, Any]] = None, yk: Optional[Set[str]] = None) -> bool:
    """P3+ write — P1.1'de kullanılmaz, API hazır."""
    if not user_dict:
        return False
    if is_superadmin(user_dict):
        return True
    if yk is None:
        return (
            yetki_var(YETKI_ODEME_PLANI, 'can_create')
            or yetki_var(YETKI_ODEME_PLANI, 'can_update')
            or yetki_var(YETKI_ODEME_PLANI, 'can_manage')
        )
    if '*' in yk:
        return True
    for action in ('can_create', 'can_update', 'can_manage'):
        if f'{YETKI_ODEME_PLANI}:{action}' in yk:
            return True
    return False


def allowed_locations(user_dict: Optional[Dict[str, Any]] = None) -> Iterable[str]:
    """
    Şirket görünürlüğü — P1.1: kısıt yok, tüm canonical location.
    İleride user_dict / override ile filtrelenebilir.
    """
    _ = user_dict
    return CANONICAL_LOCATION_CODES


def odeme_plani_menu_visible(user_dict: Optional[Dict[str, Any]] = None, yk: Optional[Set[str]] = None) -> bool:
    """Sidebar Ödeme Planı linki — VIEW yetkisi yeterli."""
    return can_odeme_plani_view(user_dict, yk)
