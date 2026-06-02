# -*- coding: utf-8 -*-
"""
CPS DEV - Ithalat Belge Parser Dispatch
========================================
Dispatch router: belge tipine gore uygun parser'i secer, calistirir.

BLOK 4.6 notu:
  - ANLASMA_EXCEL / PROFORMA / COMMERCIAL_INVOICE: ayni yapi (ayni parser)
  - BEYANNAME: gumruk beyannamesi PDF
  - FATURA: tasimacilik/navlun e-Faturasi
"""
import logging
import os
from config import Config
from modules.ithalat.parser._base import ParseSonuc

# Parser modulleri
from modules.ithalat.parser import anlasma_excel
from modules.ithalat.parser import proforma       # placeholder
from modules.ithalat.parser import beyanname
from modules.ithalat.parser import fatura_navlun  # BLOK 4.6-d
from modules.ithalat.parser import packing_list   # BLOK 4.7 - metadata only

log = logging.getLogger("cps.ithalat.parser")


# =====================================================================
# DISPATCH TABLOSU
# =====================================================================
# Belge tipi -> parse fonksiyonu
BELGE_TIPI_PARSER = {
    'ANLASMA_EXCEL':      anlasma_excel.parse,
    'PROFORMA':           anlasma_excel.parse,
    'COMMERCIAL_INVOICE': anlasma_excel.parse,
    'BEYANNAME':          beyanname.parse,
    'FATURA':             fatura_navlun.parse,   # BLOK 4.6-d
    'PACKING_LIST':       packing_list.parse,    # BLOK 4.7 - FOB/NAVLUN URETMEZ
    # Diger tipler (TEKNIK_CIZIM, GORSEL, SERTIFIKA, DIGER) icin
    # parser yok - belge sadece saklanir.
}


# =====================================================================
# API
# =====================================================================
def parser_calistir(belge_row, dosya_tam_yol=None):
    """
    Belgeyi uygun parser ile islet.

    Fail-safe: Parser hatasi durumda ParseSonuc(basarili=False, mesaj=...)
               - exception firlatilmaz.
    """
    sonuc = ParseSonuc()

    try:
        belge_tipi = (belge_row.get('BelgeTipi') or '').upper()
        dosya_ad = belge_row.get('OrijinalAd') or ''

        # Dosya yolu
        if dosya_tam_yol is None:
            disk_yol = belge_row.get('DiskYol') or ''
            dosya_tam_yol = os.path.join(Config.UPLOAD_ROOT, disk_yol)

        # Dosya var mi?
        if not os.path.isfile(dosya_tam_yol):
            sonuc.basarili = False
            sonuc.durum = 'DOSYA_YOK'
            sonuc.mesaj = f"Dosya diskte bulunamadi: {dosya_ad}"
            return sonuc

        # Parser sec
        parser_fn = BELGE_TIPI_PARSER.get(belge_tipi)
        if parser_fn is None:
            sonuc.basarili = False
            sonuc.durum = 'DESTEKLENMIYOR'
            sonuc.mesaj = (
                f"'{belge_tipi}' tipi icin parser tanimli degil. "
                f"Belge sadece saklandi, parse edilmedi."
            )
            return sonuc

        # Calistir
        log.info(
            "Parser calistiriliyor: belge_id=%s tip=%s dosya=%s",
            belge_row.get('Id'), belge_tipi, dosya_ad,
        )
        parser_sonucu = parser_fn(belge_row, dosya_tam_yol)

        if not isinstance(parser_sonucu, ParseSonuc):
            sonuc.basarili = False
            sonuc.durum = 'PARSER_HATA'
            sonuc.mesaj = 'Parser gecersiz sonuc dondu'
            return sonuc

        return parser_sonucu

    except Exception as e:
        log.exception("parser_calistir fail-safe hata: %s", e)
        sonuc.basarili = False
        sonuc.durum = 'HATA'
        sonuc.mesaj = f"Parse sirasinda beklenmedik hata: {str(e)[:200]}"
        return sonuc


def parser_var_mi(belge_tipi):
    """Belirli bir belge tipi icin parser tanimli mi?"""
    return (belge_tipi or '').upper() in BELGE_TIPI_PARSER


__all__ = ['parser_calistir', 'parser_var_mi', 'ParseSonuc']
