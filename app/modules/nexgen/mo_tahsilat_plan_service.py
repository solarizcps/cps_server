# -*- coding: utf-8 -*-
"""MO sipariş tahsilat planı hesaplama ve sorgu."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from modules.nexgen.mo_tahsilat_config import (
    PLAN_DURUM_KAYIT_GIRILDI,
    PLAN_DURUM_MUHASEBE_BEKLIYOR,
    PLAN_DURUM_PLANLANDI,
    PLAN_DURUM_SEVK_BEKLIYOR,
    PLAN_DURUM_SEVK_ONCESI,
    PLAN_DURUM_TAMAMLANDI,
    TAHSILAT_KURAL_ETIKET,
    TAHSILAT_KURALLARI,
)


def _tarih_parcala(raw: str | None) -> date | None:
    if not raw:
        return None
    s = str(raw).strip()[:10]
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError:
        return None


def tahsilat_kural_etiket(kural: str | None) -> str:
    return TAHSILAT_KURAL_ETIKET.get((kural or '').upper(), kural or '—')


def beklenen_tutar_hesapla(row: dict, mo_payload: dict | None) -> tuple[float | None, bool]:
    """(tutar, tahmini_mi) — gerçek fatura yoksa sipariş tahmini."""
    p = mo_payload or {}
    miktar = p.get('miktar')
    if miktar in (None, ''):
        kalemler = row.get('kalemler') if isinstance(row.get('kalemler'), list) else None
        if kalemler:
            try:
                miktar = sum(float(k.get('toplam_kg') or 0) for k in kalemler)
            except (TypeError, ValueError):
                miktar = None
    fiyat = row.get('anlasma_birim_fiyat')
    if miktar in (None, '') or fiyat in (None, ''):
        return None, True
    try:
        return round(float(miktar) * float(fiyat), 2), True
    except (TypeError, ValueError):
        return None, True


def hesapla_tahsilat_plani(
    kural: str,
    *,
    gun_sayisi: int | None = None,
    sabit_tarih: str | None = None,
    referans_tarih: str | None = None,
    gercek_sevk_tarihi: str | None = None,
) -> dict[str, Any]:
    """
    Tahsilat planı hesaplama.
    SEVKTE/SEVKTEN_SONRA: gercek_sevk_tarihi verilirse tarih üretilir;
    yoksa SEVK_BEKLIYOR (gerçek outbound sevk beklenir).
    """
    k = (kural or '').upper()
    if k not in TAHSILAT_KURALLARI:
        return {
            'planlanan_tahsilat_tarihi': None,
            'tahsilat_tarih_kaynagi': None,
            'tahsilat_durumu': None,
            'durum_metin': None,
        }

    if k == 'SABIT_TARIH':
        dt = (sabit_tarih or '')[:10] or None
        return {
            'planlanan_tahsilat_tarihi': dt,
            'tahsilat_tarih_kaynagi': 'SABIT',
            'tahsilat_durumu': PLAN_DURUM_PLANLANDI if dt else None,
            'durum_metin': f'Sabit tahsilat: {dt}' if dt else None,
        }

    if k == 'SIPARIS_TARIHINDE':
        dt = (referans_tarih or '')[:10] or None
        return {
            'planlanan_tahsilat_tarihi': dt,
            'tahsilat_tarih_kaynagi': 'SIPARIS',
            'tahsilat_durumu': PLAN_DURUM_PLANLANDI if dt else None,
            'durum_metin': 'Sipariş/onay tarihinde tahsilat' if dt else None,
        }

    if k == 'SEVKTEN_ONCE':
        return {
            'planlanan_tahsilat_tarihi': None,
            'tahsilat_tarih_kaynagi': 'SEVK_ONCESI',
            'tahsilat_durumu': PLAN_DURUM_SEVK_ONCESI,
            'durum_metin': 'Sevk öncesi tahsilat bekleniyor',
        }

    if k in ('SEVKTE', 'SEVKTEN_SONRA'):
        sevk = (gercek_sevk_tarihi or '')[:10] or None
        if sevk:
            plan_dt = sevk
            kaynak = 'GERCEK_SEVK'
            if k == 'SEVKTEN_SONRA' and gun_sayisi is not None:
                try:
                    plan_dt = (datetime.strptime(sevk, '%Y-%m-%d').date() + timedelta(days=int(gun_sayisi))).isoformat()
                    kaynak = 'GERCEK_SEVK+X_GUN'
                except (ValueError, TypeError):
                    plan_dt = sevk
            gun_txt = f' · {gun_sayisi} gün sonra' if k == 'SEVKTEN_SONRA' and gun_sayisi else ''
            return {
                'planlanan_tahsilat_tarihi': plan_dt,
                'tahsilat_tarih_kaynagi': kaynak,
                'tahsilat_durumu': PLAN_DURUM_PLANLANDI,
                'durum_metin': f'Sevk {sevk} — tahsilat {plan_dt}{gun_txt}',
            }
        gun_txt = f' · {gun_sayisi} gün sonra' if k == 'SEVKTEN_SONRA' and gun_sayisi else ''
        return {
            'planlanan_tahsilat_tarihi': None,
            'tahsilat_tarih_kaynagi': 'SEVK_BEKLIYOR',
            'tahsilat_durumu': PLAN_DURUM_SEVK_BEKLIYOR,
            'durum_metin': f'Gerçek sevk bekleniyor{gun_txt}',
        }

    return {
        'planlanan_tahsilat_tarihi': None,
        'tahsilat_tarih_kaynagi': None,
        'tahsilat_durumu': None,
        'durum_metin': None,
    }


def plan_hatirlatma_grubu(planlanan_tarih: str | None, durum: str | None) -> str | None:
    """Dashboard grubu — sevk bekleyenler sayaca dahil değil."""
    d = (durum or '').upper()
    if d in (PLAN_DURUM_SEVK_BEKLIYOR, PLAN_DURUM_SEVK_ONCESI):
        return 'sevk_bekleyen'
    if d in (PLAN_DURUM_KAYIT_GIRILDI,):
        return 'kayit_girildi'
    if d in (PLAN_DURUM_MUHASEBE_BEKLIYOR,):
        return 'muhasebe_bekliyor'
    if d in (PLAN_DURUM_TAMAMLANDI,):
        return 'tamamlandi'
    dt = _tarih_parcala(planlanan_tarih)
    if not dt:
        return None
    fark = (dt - date.today()).days
    if fark < 0:
        return 'gecikti'
    if fark == 0:
        return 'bugun'
    if fark <= 7:
        return 'yaklasan'
    return 'planli'


def plan_durum_etiket(grup: str | None, durum_metin: str | None = None) -> str:
    if durum_metin:
        return durum_metin
    return {
        'bugun': 'Bugün alınacak',
        'yaklasan': 'Yaklaşıyor',
        'gecikti': 'Gecikti',
        'kayit_girildi': 'Tahsilat kaydı girildi',
        'muhasebe_bekliyor': 'Muhasebe onayı bekliyor',
        'tamamlandi': 'Tahsil edildi',
        'sevk_bekleyen': 'Gerçek sevk bekleniyor',
        'planli': 'Planlandı',
    }.get(grup or '', '—')
