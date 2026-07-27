# -*- coding: utf-8 -*-
"""Müşteri Operasyonu — süreç odaklı etiketler (personel ismi yok)."""
from __future__ import annotations

from typing import Any

# Ana MO ekranında gösterilmeyecek iç personel adları
_YASAK_ISIMLER = frozenset({
    'vedat', 'mehmet', 'ferhat', 'muhasebe', 'planlamacı', 'planlamaci',
})


def _temiz_metin(metin: str | None) -> str:
    if not metin:
        return '—'
    t = str(metin).strip()
    for yasak in _YASAK_ISIMLER:
        if yasak in t.lower():
            # Personel adı geçen metinleri süreç etiketine indirgeme — çağıran zaten süreç kullanmalı
            return '—'
    return t or '—'


def numune_asama(durum: str | None, arge_durum: str | None = None, *, arge_test_id: int | None = None) -> dict[str, Any]:
    """Numune talebi süreç aşaması — kişi adı yok."""
    d = (durum or '').upper()
    ad = (arge_durum or '').upper()

    if d == 'REDDEDILDI':
        return {
            'surec_tipi': 'Numune',
            'surec_asama': 'Reddedildi',
            'aksiyon': 'Süreci Aç',
            'aksiyon_tip': 'surec_ac',
        }
    if d == 'REVIZYON_ISTENDI':
        return {
            'surec_tipi': 'Numune',
            'surec_asama': 'Revizyon İstendi',
            'aksiyon': 'Düzenle ve Gönder',
            'aksiyon_tip': 'surec_ac',
        }
    if d == 'ONAYLANDI' and not arge_test_id:
        return {
            'surec_tipi': 'Numune',
            'surec_asama': 'Onaylandı',
            'aksiyon': 'Süreci Aç',
            'aksiyon_tip': 'surec_ac',
        }
    if d in ('ONAYLANDI', 'RECETE_MERKEZINE_AKTARILDI') and arge_test_id:
        return {
            'surec_tipi': 'Numune',
            'surec_asama': 'Hazır',
            'aksiyon': 'Müşteriyi Bilgilendir',
            'aksiyon_tip': 'bilgilendir',
        }
    if d == 'ONAY_BEKLIYOR' or ad in ('ONAY_BEKLIYOR', 'ONAYA_GONDERILDI'):
        return {
            'surec_tipi': 'Numune',
            'surec_asama': 'Merkezi Onay Bekliyor',
            'aksiyon': 'Süreci Aç',
            'aksiyon_tip': 'surec_ac',
        }
    if d == 'FERHAT_TESTINDE' or ad in ('DENEMEDE', 'FERHAT_BEKLIYOR', 'SAHA_BEKLIYOR'):
        return {
            'surec_tipi': 'Numune',
            'surec_asama': 'Enjeksiyon Denemesinde',
            'aksiyon': 'Süreci Aç',
            'aksiyon_tip': 'surec_ac',
        }
    if d in ('CALISILIYOR', 'REVIZYONDA') or ad in ('ARGE_HAZIR', 'REVIZYON_GEREKLI'):
        return {
            'surec_tipi': 'Numune',
            'surec_asama': 'AR-GE Çalışıyor',
            'aksiyon': 'Süreci Aç',
            'aksiyon_tip': 'surec_ac',
        }
    if d == 'BEKLEYEN_NUMUNE':
        return {
            'surec_tipi': 'Numune',
            'surec_asama': 'Operasyon Kuyruğunda',
            'aksiyon': 'Süreci Aç',
            'aksiyon_tip': 'surec_ac',
        }
    if d in ('YENI_TALEP', 'TASLAK'):
        return {
            'surec_tipi': 'Numune',
            'surec_asama': 'Talep Hazırlanıyor',
            'aksiyon': 'Süreci Aç',
            'aksiyon_tip': 'surec_ac',
        }
    return {
        'surec_tipi': 'Numune',
        'surec_asama': 'Süreç Devam Ediyor',
        'aksiyon': 'Süreci Aç',
        'aksiyon_tip': 'surec_ac',
    }


def siparis_asama(durum: str | None) -> dict[str, Any]:
    """Sipariş süreç aşaması — kişi adı yok."""
    d = (durum or '').upper()
    if d == 'ONAY_BEKLIYOR':
        return {
            'surec_tipi': 'Sipariş',
            'surec_asama': 'Merkezi Onay Bekliyor',
            'aksiyon': 'Süreci Aç',
            'aksiyon_tip': 'surec_ac',
        }
    if d == 'ONAYLANDI':
        return {
            'surec_tipi': 'Sipariş',
            'surec_asama': 'Onaylandı',
            'aksiyon': 'Müşteriyi Bilgilendir',
            'aksiyon_tip': 'bilgilendir',
        }
    if d in ('MPR_BEKLIYOR', 'PLANLAMAYA_HAZIR'):
        return {
            'surec_tipi': 'Sipariş',
            'surec_asama': 'Planlamada',
            'aksiyon': 'Süreci Aç',
            'aksiyon_tip': 'surec_ac',
        }
    if d == 'URETIMDE':
        return {
            'surec_tipi': 'Sipariş',
            'surec_asama': 'Üretimde',
            'aksiyon': 'Süreci Aç',
            'aksiyon_tip': 'surec_ac',
        }
    if d in ('TAMAMLANDI', 'PLANLAMAYA_HAZIR'):
        return {
            'surec_tipi': 'Sipariş',
            'surec_asama': 'Sevkiyata Hazır',
            'aksiyon': 'Müşteriyi Bilgilendir',
            'aksiyon_tip': 'bilgilendir',
        }
    if d in ('TASLAK', 'REVIZYON'):
        return {
            'surec_tipi': 'Sipariş',
            'surec_asama': 'Talep Taslak',
            'aksiyon': 'Süreci Aç',
            'aksiyon_tip': 'surec_ac',
        }
    if d == 'REDDEDILDI':
        return {
            'surec_tipi': 'Sipariş',
            'surec_asama': 'Reddedildi',
            'aksiyon': 'Süreci Aç',
            'aksiyon_tip': 'surec_ac',
        }
    return {
        'surec_tipi': 'Sipariş',
        'surec_asama': d.replace('_', ' ').title() if d else '—',
        'aksiyon': 'Süreci Aç',
        'aksiyon_tip': 'surec_ac',
    }


def _adim(label: str, durum: str) -> dict[str, str]:
    return {'label': label, 'durum': durum}


def numune_timeline(durum: str | None, arge_durum: str | None = None, saha: int = 0) -> list[dict[str, str]]:
    """Kronolojik numune süreci — operasyon aşamaları, personel adı yok."""
    d = (durum or '').upper()
    ad = (arge_durum or '').upper()
    gonderildi = d not in ('YENI_TALEP', 'TASLAK')
    onay_bitti = d in ('ONAYLANDI', 'RECETE_MERKEZINE_AKTARILDI') or ad == 'ONAYLANDI'
    operasyon_bitti = gonderildi
    arge_bitti = ad in (
        'ONAY_BEKLIYOR', 'ONAYA_GONDERILDI', 'ONAYLANDI',
        'FERHAT_BEKLIYOR', 'DENEMEDE', 'REDDEDILDI',
    ) or d in ('FERHAT_TESTINDE', 'ONAY_BEKLIYOR', 'ONAYLANDI', 'RECETE_MERKEZINE_AKTARILDI')
    enjeksiyon_bitti = saha == 0 or ad in ('ONAY_BEKLIYOR', 'ONAYA_GONDERILDI', 'ONAYLANDI', 'REDDEDILDI')
    numune_hazir = onay_bitti

    def st(tamam: bool, aktif: bool) -> str:
        if tamam:
            return 'tamam'
        if aktif:
            return 'aktif'
        return 'bekle'

    adimlar = [
        _adim('Talep Açıldı', st(gonderildi, not gonderildi)),
        _adim('Merkezi Onay', st(d not in ('YENI_TALEP', 'TASLAK', 'ONAY_BEKLIYOR'), d == 'ONAY_BEKLIYOR')),
        _adim('Operasyon', st(operasyon_bitti and d != 'BEKLEYEN_NUMUNE', d == 'BEKLEYEN_NUMUNE')),
        _adim('AR-GE', st(arge_bitti, d in ('CALISILIYOR', 'REVIZYONDA'))),
    ]
    if saha == 1:
        adimlar.append(_adim(
            'Enjeksiyon Denemesi',
            st(enjeksiyon_bitti, d == 'FERHAT_TESTINDE' or ad == 'DENEMEDE'),
        ))
    adimlar.extend([
        _adim('Numune Hazır', st(numune_hazir, d == 'ONAY_BEKLIYOR' and not numune_hazir)),
        _adim('Müşteriye Gönderildi', st(False, numune_hazir)),
    ])
    return adimlar


def siparis_timeline(durum: str | None) -> list[dict[str, str]]:
    """Kronolojik sipariş süreci — personel adı yok."""
    d = (durum or '').upper()
    asamalar = [
        'Talep Açıldı',
        'Merkezi Onay',
        'Planlama',
        'Üretim',
        'Sevkiyata Hazır',
    ]
    durum_idx = {
        'TASLAK': 0, 'REVIZYON': 0, 'REDDEDILDI': 0,
        'ONAY_BEKLIYOR': 1,
        'ONAYLANDI': 2,
        'MPR_BEKLIYOR': 2, 'PLANLAMAYA_HAZIR': 2,
        'URETIMDE': 3,
        'TAMAMLANDI': 4,
    }
    cur = durum_idx.get(d, 0)
    adimlar: list[dict[str, str]] = []
    for i, label in enumerate(asamalar):
        if i < cur:
            adimlar.append(_adim(label, 'tamam'))
        elif i == cur:
            adimlar.append(_adim(label, 'aktif'))
        else:
            adimlar.append(_adim(label, 'bekle'))
    return adimlar


def tahmini_tamamlanma_gun(bekleme_gun: int, durum: str | None) -> int | None:
    """Kaba tahmini kalan gün — bilgi amaçlı."""
    d = (durum or '').upper()
    if d in ('ONAYLANDI', 'RECETE_MERKEZINE_AKTARILDI', 'TAMAMLANDI'):
        return 0
    if d in ('CALISILIYOR', 'REVIZYONDA', 'FERHAT_TESTINDE', 'BEKLEYEN_NUMUNE'):
        return max(1, 5 - min(bekleme_gun, 4))
    if d == 'ONAY_BEKLIYOR':
        return max(1, 3 - min(bekleme_gun, 2))
    return None


def ekranda_yasak_mi(metin: str | None) -> bool:
    if not metin:
        return False
    low = str(metin).lower()
    return any(y in low for y in _YASAK_ISIMLER)
