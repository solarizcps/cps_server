# -*- coding: utf-8 -*-
"""Gerçek outbound müşteri sevkiyat sabitleri + Cari360 olay sözleşmeleri."""
from __future__ import annotations

KAYNAK_MODUL = 'MO_MUSTERI_SEVKIYAT'

DURUMLAR: tuple[str, ...] = (
    'HAZIRLANIYOR',
    'YUKLENIYOR',
    'SEVK_EDILDI',
    'TESLIM_EDILDI',
    'TAMAMLANDI',
)

DURUM_ETIKET = {
    'HAZIRLANIYOR': 'Hazırlanıyor',
    'YUKLENIYOR': 'Yükleniyor',
    'SEVK_EDILDI': 'Sevk Edildi',
    'TESLIM_EDILDI': 'Teslim Edildi',
    'TAMAMLANDI': 'Tamamlandı',
}

# İzin verilen durum geçişleri — sıralı operasyon zinciri (atlama/geri dönüş yok)
DURUM_GECIS: dict[str, frozenset[str]] = {
    'HAZIRLANIYOR': frozenset({'YUKLENIYOR'}),
    'YUKLENIYOR': frozenset({'SEVK_EDILDI'}),
    'SEVK_EDILDI': frozenset({'TESLIM_EDILDI'}),
    'TESLIM_EDILDI': frozenset({'TAMAMLANDI'}),
    'TAMAMLANDI': frozenset(),
}

# Cari360 olay tipleri (UI bu fazda geliştirilmez)
OLAY_SEVK_HAZIR = 'SEVK_HAZIR'
OLAY_SEVK_CIKTI = 'SEVK_CIKTI'
OLAY_SEVK_TESLIM = 'SEVK_TESLIM'
OLAY_SEVK_TAMAMLANDI = 'SEVK_TAMAMLANDI'

YETKI_SEVKIYAT_WRITE = 'nexgen.sevkiyat.write'
YETKI_SEVKIYAT_VIEW = 'nexgen.sevkiyat.view'
