# -*- coding: utf-8 -*-
"""Finans cari kimlik API yetki anayasasi (FAZ-F1-3)."""
from __future__ import annotations

from typing import Any

from modules.nexgen.finans_yetki import finans_erisim_engelli

YETKI_CARI_KIMLIK_VIEW = 'nexgen.finans.cari_kimlik.view'
YETKI_CARI_KIMLIK_MANAGE = 'nexgen.finans.cari_kimlik.manage'
YETKI_TEDARIKCI_KIMLIK_MANAGE = 'nexgen.finans.tedarikci_kimlik.manage'

CARI_KIMLIK_YETKI_KODLARI = (
    YETKI_CARI_KIMLIK_VIEW,
    YETKI_CARI_KIMLIK_MANAGE,
    YETKI_TEDARIKCI_KIMLIK_MANAGE,
)


def _yk_has(yk: set[str] | frozenset[str], kod: str, action: str = 'can_view') -> bool:
    if '*' in yk:
        return True
    if f'{kod}:{action}' in yk:
        return True
    return kod in yk


def can_cari_kimlik_view(yk: set[str] | frozenset[str]) -> bool:
    return (
        _yk_has(yk, YETKI_CARI_KIMLIK_VIEW, 'can_view')
        or _yk_has(yk, YETKI_CARI_KIMLIK_MANAGE, 'can_view')
        or _yk_has(yk, YETKI_CARI_KIMLIK_MANAGE, 'can_manage')
        or _yk_has(yk, YETKI_TEDARIKCI_KIMLIK_MANAGE, 'can_view')
        or _yk_has(yk, YETKI_TEDARIKCI_KIMLIK_MANAGE, 'can_manage')
    )


def can_cari_kimlik_write_musteri(yk: set[str] | frozenset[str]) -> bool:
    """Normal musteri yazma — can_update veya can_manage."""
    return (
        _yk_has(yk, YETKI_CARI_KIMLIK_MANAGE, 'can_update')
        or _yk_has(yk, YETKI_CARI_KIMLIK_MANAGE, 'can_manage')
    )


def can_cari_kimlik_write_tedarikci(yk: set[str] | frozenset[str]) -> bool:
    return (
        _yk_has(yk, YETKI_TEDARIKCI_KIMLIK_MANAGE, 'can_update')
        or _yk_has(yk, YETKI_TEDARIKCI_KIMLIK_MANAGE, 'can_manage')
        or _yk_has(yk, YETKI_CARI_KIMLIK_MANAGE, 'can_manage')
    )


def can_cari_kimlik_manuel_override(yk: set[str] | frozenset[str], *, tedarikci: bool = False) -> bool:
    """Manuel CTip override — yalnizca can_manage=1."""
    if tedarikci:
        return (
            _yk_has(yk, YETKI_TEDARIKCI_KIMLIK_MANAGE, 'can_manage')
            or _yk_has(yk, YETKI_CARI_KIMLIK_MANAGE, 'can_manage')
        )
    return _yk_has(yk, YETKI_CARI_KIMLIK_MANAGE, 'can_manage')


def cari_kimlik_erisim_engelli(user_dict: dict | None, yk: set[str] | frozenset[str]) -> bool:
    """Depo / uretim operatoru — finans ile ayni kisit."""
    return finans_erisim_engelli(user_dict, yk)


def is_planlama_depo_sevkiyat(user_dict: dict | None) -> bool:
    if not user_dict:
        return False
    rol = (user_dict.get('RolAd') or user_dict.get('Rol') or '').casefold()
    return any(k in rol for k in ('planlama', 'depo', 'sevkiyat'))
