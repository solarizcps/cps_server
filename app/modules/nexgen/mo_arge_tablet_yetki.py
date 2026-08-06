# -*- coding: utf-8 -*-
"""AR-GE tablet sade arayüz — yalnız /nexgen/tablet/arge operasyonu."""
from __future__ import annotations

_ARGE_TABLET_ROL_ID = 42

# Login + sistem_rol.Ad ile uyumlu rol adları (kısa + tam + ASCII fallback)
_ARGE_TABLET_ROL_ADLAR = frozenset(
    s.casefold() for s in (
        'AR-GE',
        'AR-GE Operatörü',
        'AR-GE Operatoru',
    )
)

_NEXGEN_ARGE_TABLET_HOME = '/nexgen/tablet/arge'

_NEXGEN_ARGE_TABLET_DENY_PREFIXES = (
    '/nexgen/tablet/ferhat',
)

# tablet_arge.html + modul01–04 + numune_talep_vedat + tablet_etiket_arge
_NEXGEN_ARGE_TABLET_OK_PREFIXES = (
    '/nexgen/tablet/arge',
    '/nexgen/api/tablet/arge',
    '/nexgen/api/numune-talep/',
    '/nexgen/api/arge/',
    '/nexgen/api/etiket/arge/',
    '/static/',
    '/giris',
    '/cikis',
    '/sifre-degistir',
)


def _arge_tablet_rol_id(user_dict) -> int | None:
    """Session RolId — int veya '42' string."""
    raw = user_dict.get('RolId')
    if raw is None or raw == '':
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _arge_tablet_rol_ad_eslesir(ad: str) -> bool:
    """RolAd / Rol — Türkçe karakter bozulmasına toleranslı."""
    n = (ad or '').strip().casefold()
    if not n:
        return False
    if n in _ARGE_TABLET_ROL_ADLAR:
        return True
    # Örn. 'AR-GE Operat�r�' veya kısaltılmış departman rolü
    if n == 'ar-ge':
        return True
    if n.startswith('ar-ge') and 'oper' in n:
        return True
    return False


def is_nexgen_arge_tablet_kullanici(user_dict, yk: set[str] | None = None) -> bool:
    """AR-GE Operatörü (RolId=42) — yalnız tablet/arge profili."""
    from modules.auth import is_superadmin

    if not user_dict:
        return False
    if is_superadmin(user_dict):
        return False

    if _arge_tablet_rol_id(user_dict) == _ARGE_TABLET_ROL_ID:
        return True

    ad = (user_dict.get('RolAd') or user_dict.get('Rol') or '').strip()
    if _arge_tablet_rol_ad_eslesir(ad):
        return True

    # KullaniciAdi fallback — bu sistemde AR-GE tablet kullanıcısı Vedat'tır
    kadi = (user_dict.get('KullaniciAdi') or '').strip().lower()
    return kadi == 'vedat'


def nexgen_arge_tablet_path_ok(path: str) -> bool:
    """AR-GE tablet profili URL allowlist."""
    path = path or '/'
    for deny in _NEXGEN_ARGE_TABLET_DENY_PREFIXES:
        if path.startswith(deny):
            return False
    for pref in _NEXGEN_ARGE_TABLET_OK_PREFIXES:
        if path.startswith(pref):
            return True
    return False


def nexgen_arge_tablet_home() -> str:
    return _NEXGEN_ARGE_TABLET_HOME
