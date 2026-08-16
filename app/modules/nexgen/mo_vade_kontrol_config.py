# -*- coding: utf-8 -*-
"""
mo_vade_kontrol_config.py
=========================
Vade Kontrol V1 — canonical sabitler ve config.

Finansman oranı hardcode değil; bu modülden okunur.
Gelecekte DB/env-based konfigürasyona geçilebilir.
"""
from __future__ import annotations

from decimal import Decimal

# Aylık finansman oranı (varsayılan: %4)
FINANSMAN_AYLIK_ORAN: Decimal = Decimal("0.04")

# Tutar karşılaştırma toleransı (paket_tamamlandi için)
TUTAR_TOLERANS: Decimal = Decimal("0.01")

# Durum kodları
DURUM_VADE_UYGUN = "VADE_UYGUN"
DURUM_FAZLA_VADE = "FAZLA_VADE"
DURUM_AVANTAJ = "AVANTAJ"
DURUM_SEVK_BEKLIYOR = "SEVK_BEKLIYOR"
DURUM_CEK_YOK = "CEK_YOK"
DURUM_NAKIT_PAKET = "NAKIT_PAKET"

# odeme_tipi değeri
CEK_ODEME_TIPI = "CEK"
