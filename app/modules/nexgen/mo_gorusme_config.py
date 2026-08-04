# -*- coding: utf-8 -*-
"""Müşteri Operasyonu görüşme sabitleri — tek kaynak.

FAZ-YONETIM-CARI360-GORUSMELER-OPERASYONEL-TAMAMLAMA-1
"""

GORUSME_GUN_ESIK = 45
SIPARIS_ZIYARET_ESIK_GUN = 90

# Yeni kayıt / UI seçenekleri
GORUSME_TIPLERI: tuple[str, ...] = (
    'Telefon',
    'WhatsApp',
    'E-posta',
    'Fabrika Ziyareti',
    'Ofis Ziyareti',
    'Online Toplantı',
    'Fuar',
    'Numune Görüşmesi',
    'Diğer',
)

# Eski kayıtlar bozulmadan okunur / güncellemede korunabilir
GORUSME_TIPLERI_LEGACY: tuple[str, ...] = (
    'Ziyaret',
    'Toplantı',
)

GORUSME_TIPLERI_ALL: tuple[str, ...] = GORUSME_TIPLERI + GORUSME_TIPLERI_LEGACY

SONUC_TIPLERI: tuple[str, ...] = (
    'Genel Görüşme',
    'Numune İstedi',
    'Fiyat İstedi',
    'Teklif Gönderilecek',
    'Sipariş Bekleniyor',
    'Sipariş Verecek',
    'Dönüş Bekleniyor',
    'Olumlu',
    'Olumsuz',
    'Beklemede',
    'Tamamlandı',
)

# Eski serbest / önceki kontrollü sonuçlar
SONUC_TIPLERI_LEGACY: tuple[str, ...] = (
    'Vade İstedi',
    'Çek / Tahsilat Görüşüldü',
    'Şikayet',
    'Rakip Bilgisi',
    'Makina / Yatırım',
    'Diğer',
)

SONUC_TIPLERI_ALL: tuple[str, ...] = SONUC_TIPLERI + SONUC_TIPLERI_LEGACY

SONRAKI_AKSIYON_ORNEKLERI: tuple[str, ...] = (
    'Numune gönder',
    'Fiyat çalışması hazırla',
    'Tekrar ara',
    'Teklif gönder',
    'Ziyaret planla',
    'Dönüş bekle',
)

ONCELIKLER: tuple[str, ...] = ('NORMAL', 'ACIL', 'KRITIK')
KAYNAK_MUSTERI_OPERASYONU = 'MUSTERI_OPERASYONU'
TABLO = 'musteri_operasyon_gorusme'

# Görüşme fiyat/ödeme snapshot (finans kaydı değil)
FIYAT_PARA_BIRIMLERI: tuple[str, ...] = ('TRY', 'USD', 'EUR')
FIYAT_BIRIMI_KG = 'KG'
# Eski kayıtlarda CIFT/ADET okunabilir; yeni UI seçim almaz
FIYAT_BIRIMLERI: tuple[str, ...] = (FIYAT_BIRIMI_KG, 'CIFT', 'ADET')
ODEME_TIPLERI: tuple[str, ...] = ('NAKIT', 'VADELI', 'CEK')
VADE_GUN_MAX = 730
