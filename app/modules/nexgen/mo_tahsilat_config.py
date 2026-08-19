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
# Canonical yönetim onay akışı (normal vade)
KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR = 'YONETIM_ONAY_BEKLIYOR'
# Canonical istisna onay akışı (fazla vade)
KAYIT_DURUM_ISTISNA_ONAY_BEKLIYOR = 'YONETIM_ISTISNA_ONAY_BEKLIYOR'
# Yönetim kararı sonucu
KAYIT_DURUM_YONETIM_ONAYLANDI = 'YONETIM_ONAYLANDI'
KAYIT_DURUM_REVIZYON = 'REVIZYON_ISTENDI'
KAYIT_DURUM_REDDEDILDI = 'REDDEDILDI'
# Legacy — DB'de mevcut 47 kayıt, yeni kayıtta kullanılmaz
KAYIT_DURUM_ONAYLANDI = 'ONAYLANDI'
# Backward-compat alias (import eden kodlar kırılmasın)
KAYIT_DURUM_MUHASEBE_BEKLIYOR = KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR

KAYIT_DURUM_ETIKET = {
    KAYIT_DURUM_TASLAK: 'Taslak',
    KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR: 'Yönetim Onayında',
    KAYIT_DURUM_ISTISNA_ONAY_BEKLIYOR: 'İstisna Onayında',
    KAYIT_DURUM_YONETIM_ONAYLANDI: 'Yönetim Onaylandı',
    KAYIT_DURUM_REVIZYON: 'Revizyon İstendi',
    KAYIT_DURUM_REDDEDILDI: 'Reddedildi',
    KAYIT_DURUM_ONAYLANDI: 'Onaylandı',  # legacy
}

KAYIT_DUZENLENEBILIR = frozenset({KAYIT_DURUM_TASLAK, KAYIT_DURUM_REVIZYON})

# Onay bekleyen tüm state'ler (yeni + eski alias)
KAYIT_ONAY_BEKLIYOR_DURUMLARI = frozenset({
    KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR,
    KAYIT_DURUM_ISTISNA_ONAY_BEKLIYOR,
})

# Sevkiyat → tahsilat V1: kalan hesabına dahil kayıt durumları
# Legacy ONAYLANDI + yeni YONETIM_ONAYLANDI her ikisi de dahil
TAHSILAT_EDILEN_DURUMLARI = frozenset({
    KAYIT_DURUM_ONAYLANDI,           # legacy
    KAYIT_DURUM_YONETIM_ONAYLANDI,   # yeni
    KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR,
    KAYIT_DURUM_ISTISNA_ONAY_BEKLIYOR,
})

# Tahsilata uygun sevkiyat operasyon durumları
SEVK_TAHSILAT_DURUMLARI = frozenset({
    'SEVK_EDILDI',
    'TESLIM_EDILDI',
    'TAMAMLANDI',
})

CARI_ENTEGRASYON_AKTIF = False

# ---------------------------------------------------------------------------
# Tahsilat Tipi — AVANS vs NORMAL discriminator (Migration 164)
# ---------------------------------------------------------------------------
TAHSILAT_TIPI_NORMAL = "NORMAL"
TAHSILAT_TIPI_AVANS = "AVANS"
TAHSILAT_TIPLERI = frozenset({TAHSILAT_TIPI_NORMAL, TAHSILAT_TIPI_AVANS})

# NULL (mevcut kayıtlar) → NORMAL davranışı
TAHSILAT_TIPI_ETIKET = {
    TAHSILAT_TIPI_NORMAL: "Normal Tahsilat",
    TAHSILAT_TIPI_AVANS: "Avans",
    None: "Normal Tahsilat",  # backward-compat
}
