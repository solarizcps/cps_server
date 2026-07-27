# -*- coding: utf-8 -*-
"""Cari Kart — Aylık Durum (12 ay + devir + toplam tablosu)."""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from modules.nexgen.finans_belgesi_repository import tablo_var
from modules.nexgen.finans_cari_identity_resolver import resolve_by_operasyonel

AY_ADLARI = (
    'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran',
    'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık',
)


def _parse_yil_tarih(tarih: str | None) -> tuple[int | None, int | None]:
    if not tarih:
        return None, None
    s = str(tarih).strip()
    if ' ' in s:
        s = s.split(' ')[0]
    if len(s) < 7:
        return None, None
    try:
        parts = s.replace('.', '-').split('-')
        if len(parts[0]) == 4:
            y, m = int(parts[0]), int(parts[1])
        else:
            y, m = int(parts[2]), int(parts[1])
        return y, m
    except (TypeError, ValueError, IndexError):
        return None, None


def aylik_durum_read(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
    *,
    yil: int | None = None,
    para_birimi: str | None = None,
) -> dict[str, Any]:
    yil = int(yil or date.today().year)
    pb = para_birimi or 'TRY'
    resolution = resolve_by_operasyonel(con, cari_tipi, int(operasyonel_id))
    ckod = resolution.finance_card_code
    empty = {
        'yil': yil,
        'para_birimi': pb,
        'cari_kart_ckod': ckod,
        'satirlar': [],
        'toplam': {'donem': 'Toplam', 'borc': 0.0, 'alacak': 0.0, 'borc_bakiye': 0.0, 'alacak_bakiye': 0.0},
        'uyari': None,
    }
    if not ckod or not tablo_var(con, 'Cari_Har'):
        empty['uyari'] = 'Cari kart bağlantısı veya hareket kaydı bulunamadı.'
        return empty

    rows = con.execute(
        'SELECT Tarih, Borc, Alacak FROM Cari_Har WHERE CKod=? ORDER BY Tarih, Id',
        (ckod,),
    ).fetchall()

    devir_borc = devir_alacak = 0.0
    aylik: dict[int, dict[str, float]] = {m: {'borc': 0.0, 'alacak': 0.0} for m in range(1, 13)}

    for r in rows:
        y, m = _parse_yil_tarih(r['Tarih'])
        if y is None or m is None:
            continue
        borc = float(r['Borc'] or 0)
        alacak = float(r['Alacak'] or 0)
        if y < yil:
            devir_borc += borc
            devir_alacak += alacak
        elif y == yil and 1 <= m <= 12:
            aylik[m]['borc'] += borc
            aylik[m]['alacak'] += alacak

    satirlar: list[dict[str, Any]] = []
    kum_borc = devir_borc
    kum_alacak = devir_alacak
    tb = ta = 0.0

    devir_net = devir_borc - devir_alacak
    satirlar.append({
        'donem': 'Geçen Yılın Devri',
        'borc': round(devir_borc, 2),
        'alacak': round(devir_alacak, 2),
        'borc_bakiye': round(devir_net, 2) if devir_net > 0.0001 else 0.0,
        'alacak_bakiye': round(abs(devir_net), 2) if devir_net < -0.0001 else 0.0,
    })

    for m in range(1, 13):
        a = aylik[m]
        tb += a['borc']
        ta += a['alacak']
        kum_borc += a['borc']
        kum_alacak += a['alacak']
        net = kum_borc - kum_alacak
        satirlar.append({
            'donem': AY_ADLARI[m - 1],
            'ay': m,
            'borc': round(a['borc'], 2),
            'alacak': round(a['alacak'], 2),
            'borc_bakiye': round(net, 2) if net > 0.0001 else 0.0,
            'alacak_bakiye': round(abs(net), 2) if net < -0.0001 else 0.0,
        })

    yil_net = (devir_borc + tb) - (devir_alacak + ta)
    toplam = {
        'donem': 'Toplam',
        'borc': round(devir_borc + tb, 2),
        'alacak': round(devir_alacak + ta, 2),
        'borc_bakiye': round(yil_net, 2) if yil_net > 0.0001 else 0.0,
        'alacak_bakiye': round(abs(yil_net), 2) if yil_net < -0.0001 else 0.0,
    }
    satirlar.append(dict(toplam))
    uyari = None
    if tb <= 0.0001 and ta <= 0.0001 and devir_borc <= 0.0001 and devir_alacak <= 0.0001:
        uyari = f'{yil} yılı için hareket bulunmuyor.'
    return {
        'yil': yil,
        'para_birimi': pb,
        'cari_kart_ckod': ckod,
        'satirlar': satirlar,
        'toplam': toplam,
        'uyari': uyari,
    }
