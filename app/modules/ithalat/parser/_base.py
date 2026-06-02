# -*- coding: utf-8 -*-
"""
CPS DEV - Parser Base
======================
Tum parser'larin ortak veri yapisi: ParseSonuc.

BLOK 4.6 idempotent update:
  + kaynak_ref   : PI No / Fatura No (idempotency anahtari)
  + dosya_hash   : SHA256 (yardimci bilgi)
  + insan_onayi_bekliyor : ref bulunmazsa True
"""


class ParseSonuc:
    """
    Parser cikti modeli.

    Attributes:
        basarili (bool)
        durum (str)
        mesaj (str)
        kalemler (list of dict)
        parti_bilgi (dict)
        uyarilar (list of str)
        ham (dict)

    BLOK 4.6 eklentileri:
        kaynak_ref (str):  Belgenin kaynak referansi
                           (Proforma: PI No, Fatura: Fatura No, vb.)
                           Idempotency anahtari - ayni ref varsa tekrar islenmez.
                           Parser bulduysa doldurur, bulamadiysa None.
        dosya_hash (str):  SHA256, yardimci kontrol (zorunlu degil).
        insan_onayi_bekliyor (bool):
                           True ise: parse'lanacak veri var ama kaynak_ref yok.
                           Route bu durumda kalemleri yazmaz, belge_parse tablosuna
                           INSAN_ONAYI_BEKLIYOR durumu koyar.
    """

    DURUM_OK                = 'OK'
    DURUM_KISMEN            = 'KISMEN'
    DURUM_BOS               = 'BOS'
    DURUM_FORMAT_HATA       = 'FORMAT_HATA'
    DURUM_PARSER_HATA       = 'PARSER_HATA'
    DURUM_DESTEKLENMIYOR    = 'DESTEKLENMIYOR'
    DURUM_DOSYA_YOK         = 'DOSYA_YOK'
    DURUM_HATA              = 'HATA'
    DURUM_INSAN_ONAYI       = 'INSAN_ONAYI_BEKLIYOR'
    DURUM_ZATEN_ISLENDI     = 'ZATEN_ISLENDI'
    DURUM_BEKLIYOR_ONAY     = 'BEKLIYOR_ONAY'      # guven orta
    DURUM_REDDEDILDI        = 'REDDEDILDI'          # guven dusuk
    DURUM_ONERI_BEKLIYOR    = 'ONERI_BEKLIYOR'     # PDF maliyet oneri
    DURUM_META_GUNCELLENDI  = 'META_GUNCELLENDI'   # YENI: Packing list gibi

    def __init__(self):
        self.basarili = False
        self.durum = self.DURUM_HATA
        self.mesaj = ''
        self.kalemler = []
        self.parti_bilgi = {}
        self.uyarilar = []
        self.ham = {}

        # BLOK 4.6 eklentileri
        self.kaynak_ref = None
        self.dosya_hash = None
        self.insan_onayi_bekliyor = False

        # Guven skoru sistemi
        self.guven_skoru = None
        self.guven_seviyesi = None
        self.guven_detay = []
        self.matematik_ok = None
        self.ekstra_kalemler = []
        self.tespit_edilen_kolonlar = {}
        self.mantiksizlik_uyarilari = []

        # YENI: PDF Maliyet Onerisi akisi
        self.oneriler = []       # [{aciklama, tutar, para_birimi, tip_onerisi, ...}]
        self.meta = {}           # {fatura_no, firma_ad, toplam_ifade, ...}

    def to_dict(self):
        return {
            'basarili':    bool(self.basarili),
            'durum':       self.durum,
            'mesaj':       self.mesaj or '',
            'kalem_sayisi': len(self.kalemler),
            'kalemler':    self.kalemler,
            'parti_bilgi': self.parti_bilgi,
            'uyarilar':    self.uyarilar,
            'kaynak_ref':  self.kaynak_ref,
            'dosya_hash':  self.dosya_hash,
            'insan_onayi_bekliyor': self.insan_onayi_bekliyor,
            # Guven skoru
            'guven_skoru':           self.guven_skoru,
            'guven_seviyesi':        self.guven_seviyesi,
            'guven_detay':           self.guven_detay,
            'matematik_ok':          self.matematik_ok,
            'ekstra_kalemler':       self.ekstra_kalemler,
            'tespit_edilen_kolonlar': self.tespit_edilen_kolonlar,
            'mantiksizlik_uyarilari': self.mantiksizlik_uyarilari,
            # YENI: Maliyet onerisi akisi
            'oneriler':    self.oneriler,
            'meta':        self.meta,
        }

    @classmethod
    def oneri_bekliyor(cls, oneriler, meta=None, mesaj='',
                       kaynak_ref=None, dosya_hash=None, uyarilar=None):
        """
        PDF Maliyet Onerisi akisi - kalem otomatik OLUSMAZ.
        Kullanici oneri ekraninda tiklayip maliyete ekler.

        oneriler: list of dict
          {
            'aciklama': 'IHH-2 Ithalat...',
            'tutar': 4700.00,
            'para_birimi': 'TRY',
            'tip_onerisi': 'GUMRUK',
            'kaynak_onerisi': 'GERCEKLESEN',
            'varsayilan_isaretli': True,
            'uyari': None,  # None | 'cok_yuksek' | 'belirsiz'
            'kaynak_satir': 'Satir 1',
          }
        meta: {
            'fatura_no':    'BLR2026...',
            'firma_ad':     'BILIR GUMRUK...',
            'firma_vkn':    '1750423389',
            'fatura_tarihi': '2026-04-08',
            'toplam_ifade': '8.466,00 TL',
            'para_birimi_ana': 'TRY',
        }
        """
        s = cls()
        s.basarili = False   # otomatik uygulanmaz
        s.durum = cls.DURUM_ONERI_BEKLIYOR
        s.kalemler = []      # kalem YOK, sadece oneriler
        s.oneriler = oneriler or []
        s.meta = meta or {}
        s.mesaj = mesaj or (
            f"PDF icerisinde {len(s.oneriler)} tutar tespit edildi. "
            "Lutfen kalemleri ve tiplerini dogrulayin."
        )
        s.kaynak_ref = kaynak_ref
        s.dosya_hash = dosya_hash
        s.uyarilar = uyarilar or []
        return s

    @classmethod
    def meta_guncellendi(cls, meta=None, parti_bilgi=None, mesaj='',
                         kaynak_ref=None, dosya_hash=None, uyarilar=None):
        """
        Packing List gibi belgeler icin - maliyet kalemi URETMEZ,
        sadece parti metadata'sini gunceller.

        Durum: META_GUNCELLENDI (UYGULANDI degil, BOS da degil)
        UI: "Bilgi Guncellendi" rozeti (yesil)

        Bu bir BASARI durumudur - "UYGULANDI ama BOS" yanlistir cunku
        bu belge tipi hic kalem uretmemesi gerekir.
        """
        s = cls()
        s.basarili = True  # basarili - metadata guncellendi
        s.durum = cls.DURUM_META_GUNCELLENDI
        s.kalemler = []     # kalem YOK
        s.oneriler = []
        s.parti_bilgi = parti_bilgi or {}
        s.meta = meta or {}
        s.mesaj = mesaj or 'Packing List islendi - parti bilgileri guncellendi'
        s.kaynak_ref = kaynak_ref
        s.dosya_hash = dosya_hash
        s.uyarilar = uyarilar or []
        return s

    @classmethod
    def bekliyor_onay(cls, kalemler, guven_skoru, mesaj='',
                      kaynak_ref=None, parti_bilgi=None, uyarilar=None,
                      guven_detay=None, ekstra_kalemler=None,
                      tespit_edilen_kolonlar=None, matematik_ok=True,
                      mantiksizlik_uyarilari=None, dosya_hash=None):
        """
        Guven skoru ne olursa olsun (test fazinda): Kullanici onayi bekliyor.
        Kalemler maliyete YAZILMAZ, preview JSON'a yazilir.

        guven_seviyesi skordan hesaplanir:
          >=90 -> yuksek
          >=60 -> orta
          >0   -> dusuk
          0    -> red
        """
        s = cls()
        s.basarili = False
        s.durum = cls.DURUM_BEKLIYOR_ONAY
        s.kalemler = kalemler or []
        s.kaynak_ref = kaynak_ref
        s.parti_bilgi = parti_bilgi or {}
        s.uyarilar = uyarilar or []
        s.guven_skoru = int(guven_skoru) if guven_skoru is not None else None

        # YENI: Seviye skordan otomatik (eskiden hardcode 'orta' idi)
        if s.guven_skoru is None:
            s.guven_seviyesi = 'orta'
        elif s.guven_skoru >= 90:
            s.guven_seviyesi = 'yuksek'
        elif s.guven_skoru >= 60:
            s.guven_seviyesi = 'orta'
        elif s.guven_skoru > 0:
            s.guven_seviyesi = 'dusuk'
        else:
            s.guven_seviyesi = 'red'

        s.guven_detay = guven_detay or []
        s.matematik_ok = matematik_ok
        s.ekstra_kalemler = ekstra_kalemler or []
        s.tespit_edilen_kolonlar = tespit_edilen_kolonlar or {}
        s.mantiksizlik_uyarilari = mantiksizlik_uyarilari or []
        s.dosya_hash = dosya_hash
        s.mesaj = mesaj or f"Güven skoru {s.guven_skoru}/100"
        return s

    @classmethod
    def reddedildi(cls, guven_skoru, mesaj='', guven_detay=None,
                   mantiksizlik_uyarilari=None, kalemler=None, dosya_hash=None):
        """
        Guven skoru dusuk (< 60) veya guvenlik kurali ihlali:
        Kalem maliyete YAZILMAZ, sadece belge saklanir.
        """
        s = cls()
        s.basarili = False
        s.durum = cls.DURUM_REDDEDILDI
        s.kalemler = kalemler or []  # bilgi amacli, uygulanmayacak
        s.guven_skoru = int(guven_skoru) if guven_skoru is not None else 0
        s.guven_seviyesi = 'dusuk' if s.guven_skoru > 0 else 'red'
        s.guven_detay = guven_detay or []
        s.mantiksizlik_uyarilari = mantiksizlik_uyarilari or []
        s.dosya_hash = dosya_hash
        s.mesaj = mesaj or (
            f"Güven skoru {s.guven_skoru}/100 — parser çözemedi. "
            "Kalem otomatik eklenmedi."
        )
        return s

    def ozet(self):
        if self.basarili:
            if self.kalemler:
                return f"✓ {len(self.kalemler)} kalem okundu."
            return "✓ Dosya okundu, yeni kalem yok."
        if self.durum == self.DURUM_DESTEKLENMIYOR:
            return "Belge saklandı (bu tip için otomatik okuma yok)."
        if self.durum == self.DURUM_FORMAT_HATA:
            return f"Dosya formatı tanınamadı: {self.mesaj}"
        if self.durum == self.DURUM_INSAN_ONAYI:
            return f"İnsan onayı bekliyor: {self.mesaj}"
        if self.durum == self.DURUM_ZATEN_ISLENDI:
            return f"Bu belge zaten işlenmiş: {self.mesaj}"
        return self.mesaj or 'Parse edilemedi.'

    @classmethod
    def basari(cls, kalemler=None, mesaj='', parti_bilgi=None,
               uyarilar=None, kaynak_ref=None, dosya_hash=None):
        s = cls()
        s.basarili = True
        s.durum = cls.DURUM_OK
        s.kalemler = kalemler or []
        s.mesaj = mesaj or f"{len(s.kalemler)} kalem okundu."
        s.parti_bilgi = parti_bilgi or {}
        s.uyarilar = uyarilar or []
        s.kaynak_ref = kaynak_ref
        s.dosya_hash = dosya_hash
        return s

    @classmethod
    def hata(cls, mesaj, durum=None):
        s = cls()
        s.basarili = False
        s.durum = durum or cls.DURUM_HATA
        s.mesaj = mesaj
        return s

    @classmethod
    def bos(cls, mesaj='Dosyada veri bulunamadı.'):
        s = cls()
        s.basarili = True
        s.durum = cls.DURUM_BOS
        s.mesaj = mesaj
        return s

    @classmethod
    def insan_onayi(cls, kalemler, mesaj='', dosya_hash=None):
        """
        Kalem cikardi ama kaynak_ref (PI No vs.) bulamadi.
        Kullanici manuel ref girip 'yine de uygula' butonuna basmali.
        """
        s = cls()
        s.basarili = False  # Otomatik uygulanmasin
        s.durum = cls.DURUM_INSAN_ONAYI
        s.kalemler = kalemler or []
        s.insan_onayi_bekliyor = True
        s.dosya_hash = dosya_hash
        s.mesaj = mesaj or (
            f"Dosyada {len(s.kalemler)} kalem var, fakat PI No / kaynak "
            f"referansi bulunamadi. Kullanici onayi gerekli."
        )
        return s

    @classmethod
    def zaten_islendi(cls, kaynak_ref, onceki_parse_tarih=None):
        s = cls()
        s.basarili = False
        s.durum = cls.DURUM_ZATEN_ISLENDI
        s.kaynak_ref = kaynak_ref
        s.mesaj = (
            f"Bu belge ({kaynak_ref}) zaten işlenmiş"
            + (f" ({onceki_parse_tarih[:10]} tarihinde)." if onceki_parse_tarih else ".")
            + " Yeniden işlemek için 'Yeniden İşle' butonunu kullanın."
        )
        return s
