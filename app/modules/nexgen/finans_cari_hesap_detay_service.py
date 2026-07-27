# -*- coding: utf-8 -*-
"""Cari Kart — Hesap Detayları (Borç / Alacak) read modeli."""
from __future__ import annotations

import sqlite3
from typing import Any

from modules.nexgen.finans_belgesi_repository import tablo_var
from modules.nexgen.finans_cari_account_service import hareket_dokumu
from modules.nexgen.finans_cari_genel_durum_service import _islem_turu
from modules.nexgen.finans_cari_identity_resolver import resolve_by_operasyonel


def _satir_from_hareket(h: dict[str, Any], taraf: str) -> dict[str, Any]:
    borc = float(h.get('borc') or 0)
    alacak = float(h.get('alacak') or 0)
    tutar = borc if taraf == 'BORC' else alacak
    islem = _islem_turu(h.get('islem_turu'), h.get('aciklama'))
    return {
        'id': h['id'],
        'fis_no': str(h['id']),
        'islem_turu': islem,
        'konum': islem,
        'tarih': (h.get('tarih') or '')[:10] or None,
        'evrak_no': h.get('belge_no'),
        'vade_tarihi': None,
        'tutar': round(tutar, 2),
        'borc': round(borc, 2) if taraf == 'BORC' else 0.0,
        'alacak': round(alacak, 2) if taraf == 'ALACAK' else 0.0,
        'para_birimi': 'TRY',
        'aciklama': h.get('aciklama'),
        'kaynak': h.get('kaynak'),
        'kaynak_kodu': h.get('kaynak_kodu'),
        'onceki_donem': bool(h.get('onceki_donem') or h.get('legacy_kaynak')),
        'finans_belgesi_id': h.get('finans_belge_id'),
        'tiklanabilir': bool(h.get('finans_belge_id')),
    }


def _tarih_ok(tarih: str | None, bas: str | None, bit: str | None) -> bool:
    if not tarih:
        return bas is None and bit is None
    t = tarih[:10]
    if bas and t < bas[:10]:
        return False
    if bit and t > bit[:10]:
        return False
    return True


def _satir_filtre(
    h: dict[str, Any],
    *,
    tarih_bas: str | None,
    tarih_bit: str | None,
    islem_f: str,
    belge_f: str,
    tutar_min: float | None,
    tutar_max: float | None,
) -> bool:
    tarih = (h.get('tarih') or '')[:10]
    if not _tarih_ok(tarih, tarih_bas, tarih_bit):
        return False
    islem = _islem_turu(h.get('islem_turu'), h.get('aciklama'))
    if islem_f and islem_f not in islem.casefold():
        return False
    evrak = (h.get('belge_no') or '')
    if belge_f and belge_f not in evrak.casefold():
        return False
    borc = float(h.get('borc') or 0)
    alacak = float(h.get('alacak') or 0)
    tutar = borc if borc > 0.0001 else alacak
    if tutar_min is not None and tutar < tutar_min:
        return False
    if tutar_max is not None and tutar > tutar_max:
        return False
    return True


def hesap_detay_read(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
    *,
    kaynak: str = 'TUMU',
    tarih_bas: str | None = None,
    tarih_bit: str | None = None,
    islem_turu: str | None = None,
    belge_no: str | None = None,
    tutar_min: float | None = None,
    tutar_max: float | None = None,
) -> dict[str, Any]:
    """İki taraflı hesap detayı — toplamlar yalnız görünen satırlardan."""
    resolution = resolve_by_operasyonel(con, cari_tipi, int(operasyonel_id))
    ckod = resolution.finance_card_code
    empty = {
        'cari_tipi': cari_tipi,
        'operasyonel_id': int(operasyonel_id),
        'cari_kart_ckod': ckod,
        'borclar': [],
        'alacaklar': [],
        'toplam_borc': 0.0,
        'toplam_alacak': 0.0,
        'donem_borc': 0.0,
        'donem_alacak': 0.0,
        'devir_borc': 0.0,
        'devir_alacak': 0.0,
        'net_bakiye': 0.0,
        'legacy_borc_sayisi': 0,
        'legacy_alacak_sayisi': 0,
        'nexgen_borc_sayisi': 0,
        'nexgen_alacak_sayisi': 0,
        'kaynak_filtre': kaynak or 'TUMU',
        'filtreler': {
            'tarih_bas': tarih_bas,
            'tarih_bit': tarih_bit,
            'islem_turu': islem_turu,
            'belge_no': belge_no,
        },
        'uyari': None,
        'tablo_bos': True,
    }
    if not ckod or not tablo_var(con, 'Cari_Har'):
        empty['uyari'] = 'Cari kart bağlantısı veya hareket kaydı bulunamadı.'
        return empty

    kaynak_norm = (kaynak or 'TUMU').upper()
    if kaynak_norm not in ('NEXGEN', 'LEGACY', 'TUMU'):
        kaynak_norm = 'TUMU'

    paket = hareket_dokumu(
        con, ckod,
        kaynak=kaynak_norm,
        limit=100000,
        offset=0,
    )
    all_h = paket.get('hareketler') or []

    islem_f = (islem_turu or '').strip().casefold()
    belge_f = (belge_no or '').strip().casefold()

    devir_b = devir_a = 0.0
    for h in all_h:
        tarih = (h.get('tarih') or '')[:10]
        if tarih_bas and tarih and tarih < tarih_bas[:10]:
            if _satir_filtre(h, tarih_bas=None, tarih_bit=tarih_bas, islem_f=islem_f, belge_f=belge_f,
                             tutar_min=tutar_min, tutar_max=tutar_max):
                devir_b += float(h.get('borc') or 0)
                devir_a += float(h.get('alacak') or 0)

    borclar: list[dict[str, Any]] = []
    alacaklar: list[dict[str, Any]] = []
    leg_b = leg_a = nx_b = nx_a = 0
    donem_b = donem_a = 0.0

    for h in all_h:
        if not _satir_filtre(
            h,
            tarih_bas=tarih_bas,
            tarih_bit=tarih_bit,
            islem_f=islem_f,
            belge_f=belge_f,
            tutar_min=tutar_min,
            tutar_max=tutar_max,
        ):
            continue
        borc = float(h.get('borc') or 0)
        alacak = float(h.get('alacak') or 0)
        leg = bool(h.get('legacy_kaynak'))
        if borc > 0.0001:
            borclar.append(_satir_from_hareket(h, 'BORC'))
            donem_b += borc
            if leg:
                leg_b += 1
            else:
                nx_b += 1
        if alacak > 0.0001:
            alacaklar.append(_satir_from_hareket(h, 'ALACAK'))
            donem_a += alacak
            if leg:
                leg_a += 1
            else:
                nx_a += 1

    borclar.reverse()
    alacaklar.reverse()

    if not tarih_bas:
        devir_b = devir_a = 0.0

    tb = round(devir_b + donem_b, 2)
    ta = round(devir_a + donem_a, 2)
    nb = round(tb - ta, 2)

    empty.update({
        'borclar': borclar,
        'alacaklar': alacaklar,
        'toplam_borc': tb,
        'toplam_alacak': ta,
        'donem_borc': round(donem_b, 2),
        'donem_alacak': round(donem_a, 2),
        'devir_borc': round(devir_b, 2),
        'devir_alacak': round(devir_a, 2),
        'net_bakiye': nb,
        'legacy_borc_sayisi': leg_b,
        'legacy_alacak_sayisi': leg_a,
        'nexgen_borc_sayisi': nx_b,
        'nexgen_alacak_sayisi': nx_a,
        'tablo_bos': not borclar and not alacaklar,
    })
    if empty['tablo_bos']:
        empty.update({
            'toplam_borc': 0.0,
            'toplam_alacak': 0.0,
            'donem_borc': 0.0,
            'donem_alacak': 0.0,
            'devir_borc': 0.0,
            'devir_alacak': 0.0,
            'net_bakiye': 0.0,
        })
    return empty
