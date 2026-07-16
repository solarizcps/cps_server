# -*- coding: utf-8 -*-
"""P4A — Excel verisini merkezi ImportPackage modeline dönüştürür.
P4F.2F: _formul_grup_anahtari Türkçe/ASCII tekilleştirme için
        normalize_ascii_import kullanır.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

from modules.nexgen.import_models import (
    GECERLI_KATEGORILER,
    HamExcelVerisi,
    HamFormulSutunu,
    ImportPackage,
    KalemRolu,
    NormalizedBoyut,
    NormalizedFormul,
    NormalizedKalem,
    NormalizedKullanim,
    NormalizedRenkVaryanti,
    NormalizedRf,
    RfDurum,
)


def normalize_metin(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.strip().upper()
    s = re.sub(r"\s+", " ", s)
    return s


def miktar_kg_cevir(miktar: float | None, birim: str) -> float | None:
    if miktar is None:
        return None
    b = (birim or "KG").upper().strip()
    if b in ("GR", "GRAM", "G"):
        return round(miktar / 1000.0, 6)
    return round(float(miktar), 6)


def kalem_rolu_belirle(kategori: str, birim: str) -> KalemRolu:
    kat = (kategori or "").upper().strip()
    bir = (birim or "").upper().strip()

    if kat == "BOYA":
        return KalemRolu.BOYA_RECETESI
    if kat == "MASTERBATCH":
        if bir in ("GR", "GRAM", "G"):
            return KalemRolu.BOYA_RECETESI
        if bir == "KG":
            return KalemRolu.ANA_FORMUL
        return KalemRolu.BELIRSIZ
    if kat in ("HAMMADDE", "KATKI", "RECYCLE"):
        return KalemRolu.ANA_FORMUL
    return KalemRolu.BELIRSIZ


def fingerprint_ana_kalemler(kalemler: list[NormalizedKalem], boyut: str) -> str:
    parcalar = []
    for k in sorted(kalemler, key=lambda x: (x.sira, x.stok_kodu)):
        parcalar.append(
            f"{boyut}|{k.stok_kodu}|{k.miktar_kg:.6f}|{k.kategori}|{k.rol.value}|{k.sira}"
        )
    raw = ";".join(parcalar)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def fingerprint_boya_kalemler(kalemler: list[NormalizedKalem]) -> str:
    parcalar = []
    for k in sorted(kalemler, key=lambda x: (x.sira, x.stok_kodu)):
        parcalar.append(
            f"BOYA|{k.stok_kodu}|{k.miktar_kg:.6f}|{k.kategori}|{k.sira}"
        )
    raw = ";".join(parcalar)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _na(s: str) -> str:
    """
    Grup anahtarı için Türkçe-ASCII duyarsız normalizasyon.
    'ENJEKSİYON 18' ve 'ENJEKSIYON 18' aynı anahtar üretir.
    import_engine.normalize_ascii_import ile aynı mantık —
    döngüsel import olmadan burada yeniden tanımlandı.
    """
    if not s:
        return ""
    _MAP = {
        ord("\u0130"): "I", ord("\u0131"): "i",
        ord("\u015e"): "S", ord("\u015f"): "s",
        ord("\u011e"): "G", ord("\u011f"): "g",
        ord("\u00dc"): "U", ord("\u00fc"): "u",
        ord("\u00d6"): "O", ord("\u00f6"): "o",
        ord("\u00c7"): "C", ord("\u00e7"): "c",
    }
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_MAP)
    s = s.strip().upper()
    s = re.sub(r"\s+", " ", s)
    return s


def _formul_grup_anahtari(ad: str, aile: str) -> str:
    """
    Türkçe/ASCII farkından bağımsız formül grubu anahtarı.
    'ENJEKSİYON 18' == 'ENJEKSIYON 18' aynı gruba düşer.
    """
    raw = f"{_na(aile)}|{_na(ad)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _infer_uretim_tipi(formul_ad: str) -> str:
    ad = _na(formul_ad or "")
    if "DOKME" in ad:
        return "DOKME"
    return "ENJEKSIYON"


def _sutundan_kalemler(fs: HamFormulSutunu) -> tuple[list[NormalizedKalem], list[NormalizedKalem], list[str]]:
    ana: list[NormalizedKalem] = []
    boya: list[NormalizedKalem] = []
    uyarilar = []

    for hk in fs.kalemler:
        kg = miktar_kg_cevir(hk.miktar_ham if isinstance(hk.miktar_ham, (int, float)) else None, hk.birim)
        if kg is None:
            continue
        rol = kalem_rolu_belirle(hk.kategori, hk.birim)
        if rol == KalemRolu.BELIRSIZ:
            uyarilar.append(
                f"{fs.sutun_harf}: MASTERBATCH rolü belirsiz "
                f"(stok={hk.stok_kodu}, birim={hk.birim})"
            )
        nk = NormalizedKalem(
            stok_kodu=hk.stok_kodu,
            miktar_kg=kg,
            kategori=hk.kategori,
            birim=hk.birim,
            rol=rol,
            sira=hk.sira,
            kaynak_hucre=hk.kaynak.hucre if hk.kaynak else "",
        )
        if rol == KalemRolu.BOYA_RECETESI:
            boya.append(nk)
        elif rol == KalemRolu.ANA_FORMUL:
            ana.append(nk)

    return ana, boya, uyarilar


def normalize_excel(ham: HamExcelVerisi) -> ImportPackage:
    pkg = ImportPackage(
        stok_referanslari=ham.stok_kartlari,
        cari_referanslari=ham.cari_listesi,
        kaynak_bilgisi={
            "dosya_yolu": ham.dosya_yolu,
            "dosya_sha256": ham.dosya_sha256,
            "dosya_boyut": ham.dosya_boyut,
            "dosya_modified": ham.dosya_modified,
            "sayfa_adlari": ham.sayfa_adlari,
            "formul_sutun_sayisi": len(ham.formul_sutunlari),
        },
    )
    pkg.uyarilar.extend(ham.parser_uyarilari)

    # formul_grup: anahtar -> NormalizedFormul
    gruplar: dict[str, NormalizedFormul] = {}
    # renk içi: (grup_key, renk_kodu) -> NormalizedRenkVaryanti
    renk_map: dict[tuple[str, str], NormalizedRenkVaryanti] = {}
    cakisma_kayitlari: list[str] = []

    for fs in ham.formul_sutunlari:
        if not fs.formul_ad:
            pkg.uyarilar.append(f"{fs.sutun_harf}: Formül adı boş — atlandı")
            continue

        ana_k, boya_k, k_uyari = _sutundan_kalemler(fs)
        pkg.uyarilar.extend(k_uyari)

        boyut = fs.boyut or "STANDART"
        fp_ana = fingerprint_ana_kalemler(ana_k, boyut) if ana_k else ""
        grup_key = _formul_grup_anahtari(fs.formul_ad, fs.urun_ailesi)

        if grup_key not in gruplar:
            gruplar[grup_key] = NormalizedFormul(
                ad=fs.formul_ad,
                urun_ailesi=fs.urun_ailesi,
                normalize_ad=normalize_metin(fs.formul_ad),
                formul_grup_anahtari=grup_key,
                kaynak="EXCEL",
            )

        renk_kodu = fs.renk_kodu or fs.musteri_formul_kodu
        renk_key = (grup_key, renk_kodu)
        if renk_key not in renk_map:
            rv = NormalizedRenkVaryanti(
                renk_kodu=renk_kodu,
                renk_adi=fs.renk_adi,
                rf=NormalizedRf(durum=RfDurum.EKSIK),
            )
            renk_map[renk_key] = rv
            gruplar[grup_key].renk_varyantlari.append(rv)
        else:
            rv = renk_map[renk_key]
            if normalize_metin(rv.renk_adi) != normalize_metin(fs.renk_adi) and fs.renk_adi:
                cakisma_kayitlari.append(
                    f"Renk kodu {renk_kodu}: farklı adlar "
                    f"'{rv.renk_adi}' vs '{fs.renk_adi}' ({fs.sutun_harf})"
                )

        if boyut in rv.boyutlar:
            mevcut = rv.boyutlar[boyut]
            if mevcut.fingerprint_ana and fp_ana and mevcut.fingerprint_ana != fp_ana:
                cakisma_kayitlari.append(
                    f"{fs.sutun_harf}: Aynı formül+renk+boyut içerik çakışması "
                    f"({fs.formul_ad}/{renk_kodu}/{boyut})"
                )
            else:
                cakisma_kayitlari.append(
                    f"{fs.sutun_harf}: Aynı formül+renk+boyut duplicate sütun "
                    f"({fs.formul_ad}/{renk_kodu}/{boyut})"
                )
        else:
            nb = NormalizedBoyut(
                boyut=boyut,
                ana_kalemler=ana_k,
                boya_kalemleri=boya_k,
                fingerprint_ana=fp_ana,
                fingerprint_boya=fingerprint_boya_kalemler(boya_k) if boya_k else "",
            )
            rv.boyutlar[boyut] = nb

        pkg.kullanimlar.append(NormalizedKullanim(
            cari_kodu=fs.cari_kodu,
            uretim_tipi=_infer_uretim_tipi(fs.formul_ad),
            musteri_formul_kodu=fs.musteri_formul_kodu,
            mamul_uretim_kodu=fs.mamul_uretim_kodu or None,
            kalip_carpani=fs.kalip_carpani,
            renk_kodu=renk_kodu,
            renk_adi=fs.renk_adi,
            boyut=boyut,
            varyant=fs.varyant or "",
            formul_ad=fs.formul_ad,
            urun_ailesi=fs.urun_ailesi,
            formul_sutun=fs.sutun_harf,
            kaynak_hucre=f"TUM_FORMULLER!{fs.sutun_harf}4",
        ))

    pkg.formuller = list(gruplar.values())
    pkg.uyarilar.extend(cakisma_kayitlari)

    for f in pkg.formuller:
        fps = []
        for rv in f.renk_varyantlari:
            for b, nb in sorted(rv.boyutlar.items()):
                if nb.fingerprint_ana:
                    fps.append(nb.fingerprint_ana)
        f.fingerprint_tum = hashlib.sha256("|".join(sorted(fps)).encode()).hexdigest() if fps else ""

    return pkg


# ---------------------------------------------------------------------------
# Çekirdek import (1BA/2BA/3BA) — her kolon ayrı ana formül
# ---------------------------------------------------------------------------

CEKIRDEK_KOD_RE = re.compile(r"^[123]BA-(FL|FS|FM)\d{2}$", re.I)
CEKIRDEK_PREFIX_AILE = {"1BA": "TERLIK", "2BA": "TABAN", "3BA": "TABAN"}
CEKIRDEK_SUFFIX_BOYUT = {"FL": "LARGE", "FS": "SMALL", "FM": "MEDIUM"}


def dogrula_cekirdek_kod(kod: str, boyut: str = "") -> tuple[bool, str]:
    """Kod formatı ve FL/FS/FM ↔ boyut uyumu."""
    k = (kod or "").strip().upper()
    if not k:
        return False, "Formül kodu boş"
    if not CEKIRDEK_KOD_RE.match(k):
        return False, f"Geçersiz çekirdek kod formatı: {k!r}"
    prefix = k[:3]
    suffix = k[4:6]
    bek_aile = CEKIRDEK_PREFIX_AILE.get(prefix)
    bek_boyut = CEKIRDEK_SUFFIX_BOYUT.get(suffix)
    if not bek_aile:
        return False, f"Bilinmeyen ürün ön eki: {prefix}"
    b = (boyut or "").strip().upper()
    if b and bek_boyut and b != bek_boyut:
        return False, f"Kod {k} → {bek_boyut} beklenir, Excel boyut={b}"
    return True, ""


def _sutundan_ana_kalemler_cekirdek(fs: HamFormulSutunu) -> tuple[list[NormalizedKalem], list[str]]:
    """Yalnız KG ana kalemler; boya/gram ve sıfır miktar atlanır."""
    ana: list[NormalizedKalem] = []
    uyarilar: list[str] = []
    for hk in fs.kalemler:
        rol = kalem_rolu_belirle(hk.kategori, hk.birim)
        if rol == KalemRolu.BOYA_RECETESI:
            continue
        if rol != KalemRolu.ANA_FORMUL:
            continue
        miktar = hk.miktar_ham if isinstance(hk.miktar_ham, (int, float)) else None
        if miktar is None or float(miktar) <= 0:
            continue
        bir = (hk.birim or "").upper().strip()
        if bir in ("GR", "GRAM", "G"):
            continue
        kg = miktar_kg_cevir(miktar, hk.birim)
        if kg is None or kg <= 0:
            continue
        ana.append(NormalizedKalem(
            stok_kodu=hk.stok_kodu,
            miktar_kg=kg,
            kategori=hk.kategori,
            birim=hk.birim,
            rol=KalemRolu.ANA_FORMUL,
            sira=hk.sira,
            kaynak_hucre=hk.kaynak.hucre if hk.kaynak else "",
        ))
    return ana, uyarilar


def normalize_excel_cekirdek(
    ham: HamExcelVerisi,
    hedef_kodlar: set[str] | None = None,
) -> ImportPackage:
    """
    Çekirdek mod: her dolu Excel kolonu ayrı nexgen_formul kaydı.
    musteri_formul_kodu → gelecekteki nexgen_formul.kod
    """
    pkg = ImportPackage(
        cekirdek_import=True,
        stok_referanslari=ham.stok_kartlari,
        cari_referanslari=ham.cari_listesi,
        kaynak_bilgisi={
            "dosya_yolu": ham.dosya_yolu,
            "dosya_sha256": ham.dosya_sha256,
            "dosya_boyut": ham.dosya_boyut,
            "dosya_modified": ham.dosya_modified,
            "sayfa_adlari": ham.sayfa_adlari,
            "formul_sutun_sayisi": len(ham.formul_sutunlari),
            "cekirdek_import": True,
        },
    )
    pkg.uyarilar.extend(ham.parser_uyarilari)

    from modules.nexgen.import_models import NormalizedCekirdekKolon

    seen_kod: dict[str, str] = {}

    for fs in ham.formul_sutunlari:
        kod = (fs.musteri_formul_kodu or "").strip().upper()
        if not kod:
            pkg.uyarilar.append(f"{fs.sutun_harf}: Formül kodu boş — atlandı")
            continue
        if hedef_kodlar and kod not in {h.upper() for h in hedef_kodlar}:
            continue

        ok, hata = dogrula_cekirdek_kod(kod, fs.boyut or "")
        if not ok:
            pkg.uyarilar.append(f"{fs.sutun_harf}: BLOCKER — {hata}")
            continue

        if kod in seen_kod:
            pkg.uyarilar.append(
                f"{fs.sutun_harf}: DUPLICATE_KOD — {kod} zaten {seen_kod[kod]} kolonunda"
            )
            continue
        seen_kod[kod] = fs.sutun_harf

        ana_k, k_uyari = _sutundan_ana_kalemler_cekirdek(fs)
        pkg.uyarilar.extend(k_uyari)
        boyut = (fs.boyut or CEKIRDEK_SUFFIX_BOYUT.get(kod[4:6], "STANDART")).strip().upper()
        prefix = kod[:3]
        urun_ailesi = CEKIRDEK_PREFIX_AILE.get(prefix, _na(fs.urun_ailesi or ""))

        pkg.cekirdek_kolonlar.append(NormalizedCekirdekKolon(
            formul_kod=kod,
            formul_ad=fs.formul_ad or kod,
            urun_ailesi=urun_ailesi,
            varyant=fs.varyant or "",
            boyut=boyut,
            kalip_carpani=fs.kalip_carpani,
            durum=fs.durum or "",
            cari_kodu=fs.cari_kodu or "",
            sutun_harf=fs.sutun_harf,
            mamul_uretim_kodu=fs.mamul_uretim_kodu or "",
            ana_kalemler=ana_k,
            fingerprint_ana=fingerprint_ana_kalemler(ana_k, boyut) if ana_k else "",
        ))

    return pkg
