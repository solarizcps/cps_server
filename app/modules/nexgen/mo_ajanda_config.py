# -*- coding: utf-8 -*-
"""Müşteri Operasyonu Ajanda sabitleri."""

TABLO = 'musteri_operasyon_ajanda'

# MO Ajanda — canonical pazarlamacı (Erhan) cross-view owner
MO_AJANDA_ERHAN_UID = 49

DURUM_PLANLANDI = 'PLANLANDI'
DURUM_GERCEKLESTI = 'GERCEKLESTI'
DURUM_IPTAL = 'IPTAL'

DURUMLAR: tuple[str, ...] = (DURUM_PLANLANDI, DURUM_GERCEKLESTI, DURUM_IPTAL)
