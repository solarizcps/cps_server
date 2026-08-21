# -*- coding: utf-8 -*-
"""Araç Takip — iş talebi için CPS kullanıcı arama."""
from __future__ import annotations

from db import q, tablo_var_mi


def _display_name(row: dict) -> str:
    return (row.get('AdSoyad') or row.get('KullaniciAdi') or '').strip()


def search_cps_users(query: str = '', limit: int = 20) -> list[dict]:
    if not tablo_var_mi('sistem_kullanici'):
        return []
    lim = max(1, min(int(limit or 20), 50))
    qstr = (query or '').strip()
    if qstr:
        like = f'%{qstr}%'
        rows = q(
            """
            SELECT Id, AdSoyad, KullaniciAdi
            FROM sistem_kullanici
            WHERE Aktif=1 AND (AdSoyad LIKE ? OR KullaniciAdi LIKE ?)
            ORDER BY AdSoyad COLLATE NOCASE, KullaniciAdi COLLATE NOCASE
            LIMIT ?
            """,
            (like, like, lim),
        )
    else:
        rows = q(
            """
            SELECT Id, AdSoyad, KullaniciAdi
            FROM sistem_kullanici
            WHERE Aktif=1
            ORDER BY AdSoyad COLLATE NOCASE, KullaniciAdi COLLATE NOCASE
            LIMIT ?
            """,
            (lim,),
        )
    return [
        {
            'id': int(r['Id']),
            'display_name': _display_name(r),
            'kullanici_adi': (r.get('KullaniciAdi') or '').strip(),
        }
        for r in rows
        if r.get('Id') is not None
    ]


def get_cps_user_by_id(user_id: int) -> dict | None:
    if not user_id or not tablo_var_mi('sistem_kullanici'):
        return None
    row = q(
        """
        SELECT Id, AdSoyad, KullaniciAdi
        FROM sistem_kullanici
        WHERE Id=? AND Aktif=1
        LIMIT 1
        """,
        (int(user_id),),
    )
    if not row:
        return None
    r = row[0]
    return {
        'id': int(r['Id']),
        'display_name': _display_name(r),
        'kullanici_adi': (r.get('KullaniciAdi') or '').strip(),
    }
