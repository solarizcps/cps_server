# -*- coding: utf-8 -*-
"""Depo sade arayüz — Mal Kabul + Sevkiyat Operasyonu (Oktay profili)."""
from __future__ import annotations

_NEXGEN_DEPO_SADE_ROL_ADLAR = frozenset(
    s.casefold() for s in ('Depo',)
)

_NEXGEN_GENIS_MENU_YETKILER = (
    ('nexgen.recete.view', 'can_view'),
    ('nexgen.plan.manage', 'can_manage'),
    ('nexgen.plan.view', 'can_view'),
    ('nexgen.renk.view', 'can_view'),
    ('nexgen.arge.view', 'can_view'),
)

_NEXGEN_DEPO_SADE_HOME = '/nexgen/depo/'
_NEXGEN_DEPO_SADE_OK_PREFIXES = (
    '/nexgen/depo',
    '/nexgen/api/depo/',
    '/nexgen/sevkiyat',
    '/nexgen/api/sevkiyat-operasyon/',
    '/nexgen/api/mo-sevkiyat',
    '/api/tasks/notifications',
    '/static/',
    '/giris',
    '/cikis',
    '/sifre-degistir',
)


def _yk_has(yk: set[str], kod: str, action: str) -> bool:
    if not yk:
        return False
    if '*' in yk:
        return True
    return f'{kod}:{action}' in yk or kod in yk


def is_nexgen_depo_sade_kullanici(user_dict, yk: set[str] | None = None) -> bool:
    """Yalnız Mal Kabul + Sevkiyat kullanan depo profili."""
    from modules.auth import is_superadmin, kullanici_yetkileri

    if not user_dict:
        return False

    ad = (user_dict.get('RolAd') or user_dict.get('Rol') or '').strip()
    if ad.casefold() in _NEXGEN_DEPO_SADE_ROL_ADLAR:
        return True

    kadi = (user_dict.get('KullaniciAdi') or '').strip().lower()
    ad_soyad = (user_dict.get('AdSoyad') or '').strip().lower()
    if kadi == 'oktay' or ad_soyad == 'oktay' or ad_soyad.startswith('oktay '):
        return True

    if is_superadmin(user_dict):
        return False

    if yk is None:
        yk = kullanici_yetkileri(user_dict)
    if '*' in yk:
        return False

    has_depo = (
        _yk_has(yk, 'nexgen.depo.giris', 'can_create')
        or _yk_has(yk, 'nexgen.depo.view', 'can_view')
    )
    has_sevk = (
        _yk_has(yk, 'nexgen.sevkiyat.view', 'can_view')
        or _yk_has(yk, 'nexgen.sevkiyat.write', 'can_create')
        or _yk_has(yk, 'nexgen.sevkiyat.write', 'can_update')
    )
    if not (has_depo and has_sevk):
        return False

    for kod, action in _NEXGEN_GENIS_MENU_YETKILER:
        if _yk_has(yk, kod, action):
            return False
    return True


def nexgen_depo_sade_path_ok(path: str) -> bool:
    """Depo profili yalnız Mal Kabul + Sevkiyat listesi; detay sayfası (/sevkiyat/<id>) yasak."""
    path = path or '/'
    bare = path.split('?', 1)[0].rstrip('/')
    if bare.startswith('/nexgen/sevkiyat/') and bare != '/nexgen/sevkiyat':
        return False
    for pref in _NEXGEN_DEPO_SADE_OK_PREFIXES:
        if path.startswith(pref):
            return True
    return False


def nexgen_depo_sade_sevkiyat_detay_yasak(path: str) -> bool:
    """Depo kullanıcısının erişemeyeceği sevkiyat detay URL'si mi?"""
    bare = (path or '/').split('?', 1)[0].rstrip('/')
    if not bare.startswith('/nexgen/sevkiyat/'):
        return False
    suffix = bare[len('/nexgen/sevkiyat/'):]
    return suffix.isdigit()


def nexgen_depo_sade_home() -> str:
    return _NEXGEN_DEPO_SADE_HOME
