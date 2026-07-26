# -*- coding: utf-8 -*-
"""Finans Belgesi API serialization."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from modules.nexgen.finans_belgesi_config import DURUM_ETIKET, POSTING_DURUM_ETIKET


def _iso_tarih(v: Any) -> str | None:
    if v in (None, ''):
        return None
    s = str(v).strip()
    if not s:
        return None
    if ' ' in s:
        s = s.split(' ')[0]
    return s[:10] if len(s) >= 10 else s


def _iso_datetime(v: Any) -> str | None:
    if v in (None, ''):
        return None
    return str(v).strip()[:19] or None


def _money(v: Any) -> str | None:
    if v in (None, ''):
        return None
    try:
        d = Decimal(str(v))
        return format(d.quantize(Decimal('0.01')), 'f')
    except Exception:
        return str(v)


def _kg(v: Any) -> str | None:
    if v in (None, ''):
        return None
    try:
        return format(Decimal(str(v)).quantize(Decimal('0.001')), 'f')
    except Exception:
        return str(v)


def _audit_parse(raw: Any) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def belge_liste_satir(row: dict[str, Any]) -> dict[str, Any]:
    durum = row.get('durum')
    pd = row.get('posting_durumu')
    return {
        'id': row.get('id'),
        'belge_no': row.get('belge_kodu'),
        'belge_tipi': row.get('belge_tipi'),
        'durum': durum,
        'durum_etiket': DURUM_ETIKET.get(durum, durum),
        'posting_durumu': pd,
        'posting_durumu_etiket': POSTING_DURUM_ETIKET.get(pd, pd) if pd else None,
        'kaynak_tipi': row.get('kaynak_tipi'),
        'kaynak_id': row.get('kaynak_id'),
        'kaynak_no': row.get('kaynak_no'),
        'cari_id': row.get('cari_id'),
        'cari_unvan': row.get('cari_unvan'),
        'nexgen_cari_kod': row.get('nexgen_cari_kod'),
        'siparis_id': row.get('siparis_id'),
        'siparis_no': row.get('siparis_no'),
        'sevkiyat_id': row.get('sevkiyat_id'),
        'tahsilat_kayit_id': row.get('tahsilat_kayit_id'),
        'gercek_miktar_kg': _kg(row.get('toplam_kg')),
        'birim_fiyat': _money(row.get('birim_fiyat')),
        'para_birimi': row.get('para_birimi'),
        'toplam_tutar': _money(row.get('toplam_tutar')),
        'vade_tarihi': _iso_tarih(row.get('vade_tarihi')),
        'islem_tarihi': _iso_tarih(row.get('islem_tarihi')),
        'olusturma_tarihi': _iso_datetime(row.get('olusturma_tarihi')),
        'onay_tarihi': _iso_datetime(row.get('onay_tarihi')),
        'posting_tarihi': _iso_datetime(row.get('posting_tarihi')),
        'cari_har_id': row.get('cari_har_id'),
    }


def belge_detay_satir(
    belge: dict[str, Any],
    *,
    kaynak_ozet: dict[str, Any] | None = None,
    audit: list[dict[str, Any]] | None = None,
    durum_gecisleri: list[str] | None = None,
    aksiyonlar: dict[str, bool] | None = None,
    posting_onizleme: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = belge_liste_satir(belge)
    base.update({
        'irsaliye_no': belge.get('irsaliye_no'),
        'vade_gun': belge.get('vade_gun'),
        'siparis_kalem_id': belge.get('siparis_kalem_id'),
        'cari_kart_ckod': belge.get('cari_kart_ckod'),
        'muhasebe_notu': belge.get('muhasebe_notu'),
        'red_gerekce': belge.get('red_gerekce'),
        'cari_har_belge_no': belge.get('cari_har_belge_no'),
        'posting_kullanici_id': belge.get('posting_kullanici_id'),
        'posting_idempotency_key': belge.get('posting_idempotency_key'),
        'posting_hata': belge.get('posting_hata'),
        'idempotency_key': belge.get('idempotency_key'),
        'snapshot': {
            'birim_fiyat': _money(belge.get('birim_fiyat')),
            'para_birimi': belge.get('para_birimi'),
            'toplam_kg': _kg(belge.get('toplam_kg')),
            'toplam_tutar': _money(belge.get('toplam_tutar')),
            'vade_gun': belge.get('vade_gun'),
            'vade_tarihi': _iso_tarih(belge.get('vade_tarihi')),
            'islem_tarihi': _iso_tarih(belge.get('islem_tarihi')),
            'irsaliye_no': belge.get('irsaliye_no'),
        },
        'kaynak_ozet': kaynak_ozet or {},
        'audit': audit if audit is not None else _audit_parse(belge.get('audit_json')),
        'durum_gecisleri': durum_gecisleri or [],
        'aksiyonlar': aksiyonlar or {},
        'posting_onizleme': posting_onizleme or {},
    })
    return base


def api_ok(**payload: Any) -> dict[str, Any]:
    out = {'ok': True}
    out.update(payload)
    return out


def api_hata(kod: str, mesaj: str) -> dict[str, Any]:
    return {'ok': False, 'kod': kod, 'mesaj': mesaj}
