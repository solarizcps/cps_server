# -*- coding: utf-8 -*-
"""Müşteri Operasyonu görüşme sabitleri — tek kaynak."""

GORUSME_GUN_ESIK = 45
SIPARIS_ZIYARET_ESIK_GUN = 90

GORUSME_TIPLERI: tuple[str, ...] = (
    'Ziyaret', 'Telefon', 'WhatsApp', 'E-posta', 'Toplantı', 'Diğer',
)

SONUC_TIPLERI: tuple[str, ...] = (
    'Sipariş Bekleniyor',
    'Numune İstedi',
    'Fiyat İstedi',
    'Vade İstedi',
    'Çek / Tahsilat Görüşüldü',
    'Şikayet',
    'Rakip Bilgisi',
    'Makina / Yatırım',
    'Genel Görüşme',
    'Diğer',
)

ONCELIKLER: tuple[str, ...] = ('NORMAL', 'ACIL', 'KRITIK')
KAYNAK_MUSTERI_OPERASYONU = 'MUSTERI_OPERASYONU'
TABLO = 'musteri_operasyon_gorusme'
