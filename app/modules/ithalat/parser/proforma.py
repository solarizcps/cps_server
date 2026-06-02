# -*- coding: utf-8 -*-
"""
CPS DEV - Proforma / Commercial Invoice Parser (PLACEHOLDER)
=============================================================
BLOK 4.6-b — Bu parca su an hazir degil.

Kapsam (ileride):
  - PDF proforma/invoice'lari oku
  - XLSX proforma/invoice'lari oku
  - Baslik bloklarindan: satici/alici, tarih, numara, toplam
  - Kalem tablosundan: urun, adet, birim fiyat, toplam
  - Cikti: maliyet kalem listesi (FOB tipinde, GERCEKLESEN kaynak)

Bu dosya BLOK 4.6-b geldiginde implement edilecek.
Dispatch tablosunda tanimli oldugu icin import olmali, ancak parse()
cagrildiginda "henuz hazir degil" mesaji donuyor.
"""
import logging
from modules.ithalat.parser._base import ParseSonuc

log = logging.getLogger("cps.ithalat.parser.proforma")


def parse(belge_row, dosya_yol):
    """
    Proforma / commercial invoice parse et.
    Su an placeholder - her zaman "hazir degil" doner.
    """
    return ParseSonuc.hata(
        "Proforma/Invoice parser'ı henüz hazır değil (BLOK 4.6-b). "
        "Dosya sistem tarafından saklandı, manuel olarak kalem ekleyebilirsiniz.",
        durum=ParseSonuc.DURUM_DESTEKLENMIYOR,
    )
