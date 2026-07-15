# -*- coding: utf-8 -*-
"""P4A — Import motoru veri modelleri (salt okuma / dry-run)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class EslesmeGuveni(str, Enum):
    KESIN = "KESIN"
    YUKSEK = "YUKSEK"
    ORTA = "ORTA"
    BELIRSIZ = "BELIRSIZ"
    ESLESMEDI = "ESLESMEDI"


class ValidationSinif(str, Enum):
    AYNI = "AYNI"
    YENI = "YENI"
    DEGISTI = "DEGISTI"
    ESKIDE_VAR_YENIDE_YOK = "ESKIDE_VAR_YENIDE_YOK"
    ESLESMEDI = "ESLESMEDI"
    CAKISMA = "CAKISMA"
    UYARI = "UYARI"
    BLOKER_HATA = "BLOKER_HATA"


class KalemRolu(str, Enum):
    ANA_FORMUL = "ANA_FORMUL"
    BOYA_RECETESI = "BOYA_RECETESI"
    BELIRSIZ = "BELIRSIZ"


class RfDurum(str, Enum):
    ESLESTI = "ESLESTI"
    EKSIK = "EKSIK"
    YENI_ADAY = "YENI_ADAY"


GECERLI_KATEGORILER = frozenset({
    "HAMMADDE", "KATKI", "RECYCLE", "MASTERBATCH", "BOYA",
})
GECERLI_BOYUTLAR = frozenset({"LARGE", "SMALL", "MEDIUM", "STANDART"})
GECERLI_AILELER = frozenset({"TERLIK", "TABAN"})
GECERLI_URETIM_TIPLERI = frozenset({"ENJEKSIYON", "DOKME", "SOGUK_SICAK"})


@dataclass
class KaynakIzi:
    sayfa: str
    satir: int
    sutun_baslik: str = ""
    hucre: str = ""
    ham_deger: Any = None
    normalize_deger: Any = None


@dataclass
class HamStokKaydi:
    stok_kodu: str
    resmi_ad: str = ""
    kategori: str = ""
    birim: str = ""
    kaynak: KaynakIzi | None = None


@dataclass
class HamAramaKaydi:
    kolay_arama: str
    stok_kodu: str
    kaynak: KaynakIzi | None = None


@dataclass
class HamCariKaydi:
    cari_kod: str
    unvan: str = ""
    durum: str = ""
    kaynak: KaynakIzi | None = None


@dataclass
class HamFormulKalemi:
    sira: int = 0
    malzeme_ara: str = ""
    stok_kodu: str = ""
    resmi_ad: str = ""
    kategori: str = ""
    birim: str = ""
    miktar_ham: Any = None
    miktar_kg: float | None = None
    formul_sutun: str = ""
    formul_sutun_idx: int = 0
    kaynak: KaynakIzi | None = None


@dataclass
class HamFormulSutunu:
    """TUM_FORMULLER'de tek sütun = tek formül kullanımı."""
    sutun_harf: str
    sutun_idx: int
    mamul_uretim_kodu: str = ""
    musteri_formul_kodu: str = ""
    formul_ad: str = ""
    urun_ailesi: str = ""
    formul_baslik: str = ""
    varyant: str = ""
    boyut: str = ""
    kalip_carpani: float | None = None
    renk_kodu: str = ""
    renk_adi: str = ""
    formul_tarihi: str = ""
    durum: str = ""
    cari_kodu: str = ""
    cari_unvan: str = ""
    not_alan: str = ""
    kontrol: str = ""
    kalemler: list[HamFormulKalemi] = field(default_factory=list)
    meta_kaynak: dict[str, KaynakIzi] = field(default_factory=dict)


@dataclass
class HamExcelVerisi:
    dosya_yolu: str
    dosya_sha256: str
    dosya_boyut: int
    dosya_modified: str
    sayfa_adlari: list[str]
    stok_kartlari: list[HamStokKaydi] = field(default_factory=list)
    arama_listesi: list[HamAramaKaydi] = field(default_factory=list)
    cari_listesi: list[HamCariKaydi] = field(default_factory=list)
    formul_sutunlari: list[HamFormulSutunu] = field(default_factory=list)
    kullanim_metni: list[str] = field(default_factory=list)
    parser_uyarilari: list[str] = field(default_factory=list)


@dataclass
class NormalizedKalem:
    stok_kodu: str
    stok_kart_id: int | None = None
    miktar_kg: float = 0.0
    kategori: str = ""
    birim: str = ""
    rol: KalemRolu = KalemRolu.BELIRSIZ
    sira: int = 0
    kaynak_hucre: str = ""


@dataclass
class NormalizedRf:
    durum: RfDurum = RfDurum.EKSIK
    rf_renk_id: int | None = None
    rf_rev_no: int | None = None
    rf_kod: str = ""
    boya_kalemleri: list[NormalizedKalem] = field(default_factory=list)


@dataclass
class NormalizedBoyut:
    boyut: str
    ana_kalemler: list[NormalizedKalem] = field(default_factory=list)
    boya_kalemleri: list[NormalizedKalem] = field(default_factory=list)
    fingerprint_ana: str = ""
    fingerprint_boya: str = ""


@dataclass
class NormalizedRenkVaryanti:
    renk_kodu: str
    renk_adi: str
    boyutlar: dict[str, NormalizedBoyut] = field(default_factory=dict)
    rf: NormalizedRf = field(default_factory=NormalizedRf)


@dataclass
class NormalizedFormul:
    sistem_kodu: str | None = None
    ad: str = ""
    urun_ailesi: str = ""
    normalize_ad: str = ""
    fingerprint_tum: str = ""
    kaynak: str = "EXCEL"
    renk_varyantlari: list[NormalizedRenkVaryanti] = field(default_factory=list)
    formul_grup_anahtari: str = ""


@dataclass
class NormalizedKullanim:
    cari_kodu: str = ""
    cari_id: int | None = None
    uretim_tipi: str = ""
    uretim_tipi_id: int | None = None
    musteri_formul_kodu: str = ""
    mamul_uretim_kodu: str = ""
    kalip_carpani: float | None = None
    renk_kodu: str = ""
    renk_adi: str = ""
    boyut: str = ""
    varyant: str = ""
    formul_ad: str = ""
    urun_ailesi: str = ""
    formul_sutun: str = ""
    kaynak_hucre: str = ""


@dataclass
class ImportPackage:
    formuller: list[NormalizedFormul] = field(default_factory=list)
    kullanimlar: list[NormalizedKullanim] = field(default_factory=list)
    stok_referanslari: list[HamStokKaydi] = field(default_factory=list)
    cari_referanslari: list[HamCariKaydi] = field(default_factory=list)
    uyarilar: list[str] = field(default_factory=list)
    kaynak_bilgisi: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationKaydi:
    sinif: ValidationSinif
    nesne_tipi: str
    anahtar: str
    mesaj: str
    guven: EslesmeGuveni = EslesmeGuveni.ESLESMEDI
    detay: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    kayitlar: list[ValidationKaydi] = field(default_factory=list)
    ozet: dict[str, int] = field(default_factory=dict)
    db_oncesi: dict[str, Any] = field(default_factory=dict)
    db_sonrasi: dict[str, Any] = field(default_factory=dict)
    db_hash_degisti: bool = False
    import_package: ImportPackage | None = None

    def ekle(self, kayit: ValidationKaydi) -> None:
        self.kayitlar.append(kayit)
        key = kayit.sinif.value
        self.ozet[key] = self.ozet.get(key, 0) + 1

    @property
    def bloker_sayisi(self) -> int:
        return self.ozet.get(ValidationSinif.BLOKER_HATA.value, 0)

    @property
    def uyari_sayisi(self) -> int:
        return self.ozet.get(ValidationSinif.UYARI.value, 0)
