# -*- coding: utf-8 -*-
"""Araç Takip — iş talebi şoför seçimi (snapshot + canonical kullanıcı eşleme)."""
from __future__ import annotations

from db import q, tablo_var_mi

PRESET_DRIVERS = {
    'OKTAY': {
        'display_name': 'Oktay KAŞIKÇI',
        'match_tokens': ('Oktay', 'KAŞIKÇI', 'KASIKCI', 'Kaşıkçı'),
        'login_tokens': ('oktay',),
    },
    'SERHAT': {
        'display_name': 'Serhat GÜLMEN',
        'match_tokens': ('Serhat', 'GÜLMEN', 'GULMEN', 'Gülmen'),
        'login_tokens': ('serhat',),
    },
}


def _normalize(s: str) -> str:
    return (s or '').strip()


def lookup_user_id_by_display(name: str) -> int | None:
    if not name or not tablo_var_mi('sistem_kullanici'):
        return None
    exact = q(
        """
        SELECT Id FROM sistem_kullanici
        WHERE Aktif=1 AND TRIM(AdSoyad)=TRIM(?)
        LIMIT 1
        """,
        (name,),
    )
    if exact:
        return int(exact[0]['Id'])
    parts = [p for p in name.replace('  ', ' ').split(' ') if len(p) >= 3]
    for part in parts[:2]:
        rows = q(
            """
            SELECT Id, AdSoyad, KullaniciAdi FROM sistem_kullanici
            WHERE Aktif=1 AND (AdSoyad LIKE ? OR KullaniciAdi LIKE ?)
            ORDER BY AdSoyad COLLATE NOCASE
            LIMIT 5
            """,
            (f'%{part}%', f'%{part.lower()}%'),
        )
        for row in rows:
            ad = _normalize(row.get('AdSoyad') or '')
            login = _normalize(row.get('KullaniciAdi') or '').lower()
            if part.lower() in ad.lower() or part.lower() in login:
                return int(row['Id'])
    return None


def _lookup_preset(preset_key: str) -> tuple[int | None, str]:
    cfg = PRESET_DRIVERS.get(preset_key) or {}
    display = cfg.get('display_name') or preset_key
    uid = lookup_user_id_by_display(display)
    if uid is None:
        for token in cfg.get('login_tokens') or ():
            rows = q(
                """
                SELECT Id FROM sistem_kullanici
                WHERE Aktif=1 AND LOWER(KullaniciAdi)=LOWER(?)
                LIMIT 1
                """,
                (token,),
            )
            if rows:
                uid = int(rows[0]['Id'])
                break
    if uid is None:
        for token in cfg.get('match_tokens') or ():
            rows = q(
                """
                SELECT Id FROM sistem_kullanici
                WHERE Aktif=1 AND AdSoyad LIKE ?
                LIMIT 1
                """,
                (f'%{token}%',),
            )
            if rows:
                uid = int(rows[0]['Id'])
                break
    return uid, display


def resolve_sofor_from_payload(payload: dict) -> tuple[int | None, str | None]:
    """Return (sofor_id, sofor_adi_snapshot) from request payload."""
    secim = _normalize(payload.get('sofor_secim') or '').upper()
    custom = _normalize(
        payload.get('sofor_adi')
        or payload.get('sofor_adi_snapshot')
        or payload.get('sofor_other')
        or '',
    )

    if secim == 'DIGER':
        if not custom:
            return None, None
        uid = lookup_user_id_by_display(custom)
        return uid, custom

    if secim in PRESET_DRIVERS:
        return _lookup_preset(secim)

    raw_id = payload.get('sofor_id')
    raw_name = _normalize(payload.get('sofor_adi_snapshot') or payload.get('sofor_adi') or '')
    try:
        uid = int(raw_id) if raw_id not in (None, '') else None
    except (TypeError, ValueError):
        uid = None
    if uid is None and raw_name:
        uid = lookup_user_id_by_display(raw_name)
    if raw_name:
        return uid, raw_name
    return uid, None
