# -*- coding: utf-8 -*-
"""MO sipariş tahsilat planı sabitleri."""
from __future__ import annotations

KAYNAK_MUSTERI_OPERASYONU = 'MUSTERI_OPERASYONU'
KAYNAK_MANUEL_FINANS = 'MANUEL_FINANS'

ODEME_SEKILLERI = frozenset({'NAKIT', 'HAVALE', 'CEK', 'SENET', 'DIGER'})
ODEME_SEKLI_ETIKET = {
    'NAKIT': 'Nakit',
    'HAVALE': 'Havale',
    'CEK': 'Çek',
    'SENET': 'Senet',
    'DIGER': 'Diğer',
}

TAHSILAT_KURALLARI = frozenset({
    'SIPARIS_TARIHINDE',
    'SEVKTEN_ONCE',
    'SEVKTE',
    'SEVKTEN_SONRA',
    'SABIT_TARIH',
})
TAHSILAT_KURAL_ETIKET = {
    'SIPARIS_TARIHINDE': 'Sipariş tarihinde',
    'SEVKTEN_ONCE': 'Sevkten önce',
    'SEVKTE': 'Sevkte',
    'SEVKTEN_SONRA': 'Sevkten sonra',
    'SABIT_TARIH': 'Sabit tarihte',
}

# Sipariş tahsilat plan durumları (nexgen_planlama_siparis.tahsilat_durumu)
PLAN_DURUM_SEVK_BEKLIYOR = 'SEVK_BEKLIYOR'
PLAN_DURUM_SEVK_ONCESI = 'SEVK_ONCESI_BEKLIYOR'
PLAN_DURUM_PLANLANDI = 'PLANLANDI'
PLAN_DURUM_KAYIT_GIRILDI = 'KAYIT_GIRILDI'
PLAN_DURUM_MUHASEBE_BEKLIYOR = 'MUHASEBE_BEKLIYOR'
PLAN_DURUM_TAMAMLANDI = 'TAMAMLANDI'

# Tahsilat kayıt durumları (mo_tahsilat_kayit.durum)
KAYIT_DURUM_TASLAK = 'TASLAK'
KAYIT_DURUM_MUHASEBE_BEKLIYOR = 'MUHASEBE_ONAY_BEKLIYOR'
KAYIT_DURUM_REVIZYON = 'REVIZYON_ISTENDI'
KAYIT_DURUM_REDDEDILDI = 'REDDEDILDI'
KAYIT_DURUM_ONAYLANDI = 'ONAYLANDI'

KAYIT_DURUM_ETIKET = {
    KAYIT_DURUM_TASLAK: 'Taslak',
    KAYIT_DURUM_MUHASEBE_BEKLIYOR: 'Onay Bekliyor',
    KAYIT_DURUM_REVIZYON: 'Revizyon İstendi',
    KAYIT_DURUM_REDDEDILDI: 'Reddedildi',
    KAYIT_DURUM_ONAYLANDI: 'Onaylandı',
}

KAYIT_DUZENLENEBILIR = frozenset({KAYIT_DURUM_TASLAK, KAYIT_DURUM_REVIZYON})

# Sevkiyat → tahsilat V1: kalan hesabına dahil kayıt durumları
TAHSILAT_EDILEN_DURUMLARI = frozenset({
    KAYIT_DURUM_ONAYLANDI,
    KAYIT_DURUM_MUHASEBE_BEKLIYOR,
})

# Tahsilata uygun sevkiyat operasyon durumları
SEVK_TAHSILAT_DURUMLARI = frozenset({
    'SEVK_EDILDI',
    'TESLIM_EDILDI',
    'TAMAMLANDI',
})

CARI_ENTEGRASYON_AKTIF = False
