# -*- coding: utf-8 -*-
"""
P4B — Reçete Diff Motoru (read-only)

Excel'den normalize edilmiş veriyi DB baseline ile karşılaştırır.
DB'ye hiçbir yazma yapılmaz.

Kimlik stratejisi (4 seviye):
  L1  normalize(formul_ad) + urun_ailesi
  L2  L1 + normalize(varyant) + renk_kodu + normalize(renk_adi)
  L3  L2 + boyut
  L4  L3 + stok_kodu

Miktar tolerance: 0.000001 KG
"""
from __future__ import annotations

import hashlib
import math
import os
import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from modules.nexgen.import_normalizer import normalize_metin
from modules.nexgen.import_models import (
    ImportPackage,
    NormalizedFormul,
    NormalizedRenkVaryanti,
    NormalizedBoyut,
    NormalizedKalem,
    NormalizedKullanim,
    KalemRolu,
)
from modules.nexgen.import_validator import (
    db_readonly_connect,
    db_snapshot,
    DB_PATH,
)

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------
MIKTAR_TOLERANCE_KG: float = 1e-6

TEST_TASLAK_KODLARI = {"NX-2026-0001", "NX-2026-0002"}


# ---------------------------------------------------------------------------
# Enum'lar
# ---------------------------------------------------------------------------
class DiffSinif(str, Enum):
    AYNI = "AYNI"
    YENI = "YENI"
    DEGISTI = "DEGISTI"
    ESKIDE_VAR_YENIDE_YOK = "ESKIDE_VAR_YENIDE_YOK"
    BLOCKER = "BLOCKER"
    UYARI = "UYARI"
    BUSINESS_RULE_REVIEW = "BUSINESS_RULE_REVIEW"
    TEST_TASLAK = "TEST_TASLAK"


class ChangeTip(str, Enum):
    FORMUL_EKLENDI = "FORMUL_EKLENDI"
    FORMUL_ESKIDE_VAR = "FORMUL_ESKIDE_VAR"
    FORMUL_ADI_DEGISTI = "FORMUL_ADI_DEGISTI"
    URUN_AILESI_DEGISTI = "URUN_AILESI_DEGISTI"
    VARYANT_EKLENDI = "VARYANT_EKLENDI"
    VARYANT_SILINDI = "VARYANT_SILINDI"
    VARYANT_DEGISTI = "VARYANT_DEGISTI"
    BOYUT_EKLENDI = "BOYUT_EKLENDI"
    BOYUT_SILINDI = "BOYUT_SILINDI"
    BOYUT_DEGISTI = "BOYUT_DEGISTI"
    KALEM_EKLENDI = "KALEM_EKLENDI"
    KALEM_SILINDI = "KALEM_SILINDI"
    MIKTAR_DEGISTI = "MIKTAR_DEGISTI"
    BIRIM_DEGISTI = "BIRIM_DEGISTI"
    SIRA_DEGISTI = "SIRA_DEGISTI"
    STOK_ESLESMEDI = "STOK_ESLESMEDI"
    RF_ESLESTI = "RF_ESLESTI"
    RF_EKSIK = "RF_EKSIK"
    RF_DEGISTI = "RF_DEGISTI"
    PLANLAMA_UYGUNLUK_EKLENDI = "PLANLAMA_UYGUNLUK_EKLENDI"
    PLANLAMA_UYGUNLUK_SILINDI = "PLANLAMA_UYGUNLUK_SILINDI"
    PLANLAMA_UYGUNLUK_DEGISTI = "PLANLAMA_UYGUNLUK_DEGISTI"
    MUSTERI_FORMUL_KODU_DEGISTI = "MUSTERI_FORMUL_KODU_DEGISTI"
    MAMUL_URETIM_KODU_DEGISTI = "MAMUL_URETIM_KODU_DEGISTI"
    KALIP_CARPANI_DEGISTI = "KALIP_CARPANI_DEGISTI"
    STOK_EKSIK = "STOK_EKSIK"
    MAMUL_URETIM_KODU_BOS = "MAMUL_URETIM_KODU_BOS"
    MUSTERI_FORMUL_KODU_CAKISMASI = "MUSTERI_FORMUL_KODU_CAKISMASI"


# ---------------------------------------------------------------------------
# Dataclass'lar
# ---------------------------------------------------------------------------
@dataclass
class DiffKaydi:
    sinif: DiffSinif
    change_tip: ChangeTip | None
    severity: str
    entity_type: str
    identity: str
    mesaj: str
    old_value: Any = None
    new_value: Any = None
    difference: Any = None
    source_sheet: str = ""
    source_cell: str = ""
    db_ids: list[int] = field(default_factory=list)


@dataclass
class KgToplam:
    ana_formul_kg: float = 0.0
    boya_rf_kg: float = 0.0

    @property
    def genel_toplam_kg(self) -> float:
        return round(self.ana_formul_kg + self.boya_rf_kg, 6)


@dataclass
class DiffSonucu:
    meta: dict[str, Any] = field(default_factory=dict)
    ozet: dict[str, int] = field(default_factory=dict)
    kayitlar: list[DiffKaydi] = field(default_factory=list)
    import_uygunluk: str = "IMPORTA_HAZIR_DEGIL"

    def ekle(self, kayit: DiffKaydi) -> None:
        self.kayitlar.append(kayit)
        self.ozet[kayit.sinif.value] = self.ozet.get(kayit.sinif.value, 0) + 1

    def bloker_sayisi(self) -> int:
        return self.ozet.get(DiffSinif.BLOCKER.value, 0)

    def uyari_sayisi(self) -> int:
        return self.ozet.get(DiffSinif.UYARI.value, 0)

    def biz_rule_sayisi(self) -> int:
        return self.ozet.get(DiffSinif.BUSINESS_RULE_REVIEW.value, 0)


# ---------------------------------------------------------------------------
# DB okuma yardımcıları
# ---------------------------------------------------------------------------
def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _db_formuller(con: sqlite3.Connection) -> list[dict]:
    """DB'deki tüm formüller ve kalemlerini döner."""
    rows = con.execute("""
        SELECT
            f.id          AS f_id,
            f.kod         AS f_kod,
            f.ad          AS f_ad,
            f.urun_ailesi AS f_aile,
            f.durum,
            f.onay_durumu,
            f.aktif       AS f_aktif,
            f.olusturan_id,
            f.olusturma_tarihi,
            rv.id         AS rv_id,
            rv.kod        AS rv_kod,
            rv.ad         AS rv_ad,
            rv.renk       AS rv_renk,
            rv.aktif      AS rv_aktif,
            uv.id         AS uv_id,
            uv.boyut,
            uv.aktif      AS uv_aktif,
            rk.id         AS rk_id,
            rk.stok_kart_id,
            sk.kod        AS stok_kod,
            sk.ad         AS stok_ad,
            sk.kategori   AS stok_kat,
            sk.birim      AS stok_birim,
            rk.miktar_kg,
            rk.sira,
            rk.aktif      AS rk_aktif
        FROM nexgen_formul f
        JOIN nexgen_renk_varyant rv  ON rv.formul_id = f.id
        JOIN nexgen_uretim_varyant uv ON uv.renk_varyant_id = rv.id
        LEFT JOIN nexgen_recete_kalem rk ON rk.uretim_varyant_id = uv.id
        LEFT JOIN nexgen_stok_kart sk ON sk.id = rk.stok_kart_id
        ORDER BY f.id, rv.id, uv.id, rk.sira
    """).fetchall()
    return [dict(r) for r in rows]


def _db_planlama(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute("""
        SELECT
            pu.id, pu.cari_id, pu.uretim_tipi_id,
            pu.formul_id, pu.renk_varyant_id,
            pu.rf_renk_id, pu.rf_rev_no,
            pu.kalip_carpani, pu.durum, pu.aktif,
            c.cari_kod,
            ut.kod AS ut_kod,
            rr.rf_kod AS rf_kod
        FROM nexgen_planlama_uygunluk pu
        LEFT JOIN nexgen_cari c ON c.id = pu.cari_id
        LEFT JOIN nexgen_uretim_tipi ut ON ut.id = pu.uretim_tipi_id
        LEFT JOIN nexgen_rf_renk rr ON rr.id = pu.rf_renk_id
        ORDER BY pu.formul_id, pu.id
    """).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# DB yapısını Python dict'e çevir
# ---------------------------------------------------------------------------
def _build_db_tree(rows: list[dict]) -> dict:
    """
    {normalize_ad: {
      "f_id": ..., "f_kod": ..., "f_aile": ...,
      "varyantlar": {
        renk_kodu: {
          "rv_id": ...,
          "boyutlar": {
            boyut: {
              "uv_id": ...,
              "kalemler": [{stok_kod, miktar_kg, sira, ...}]
            }
          }
        }
      }
    }}
    """
    tree: dict = {}
    for r in rows:
        nk = normalize_metin(r["f_ad"] or "")
        if nk not in tree:
            tree[nk] = {
                "f_id": r["f_id"],
                "f_kod": r["f_kod"],
                "f_ad": r["f_ad"],
                "f_aile": r["f_aile"] or "",
                "durum": r["durum"],
                "onay_durumu": r["onay_durumu"],
                "f_aktif": r["f_aktif"],
                "olusturan_id": r["olusturan_id"],
                "olusturma_tarihi": r["olusturma_tarihi"],
                "varyantlar": {},
            }
        rk = r.get("rv_renk") or ""
        if rk not in tree[nk]["varyantlar"]:
            tree[nk]["varyantlar"][rk] = {
                "rv_id": r["rv_id"],
                "rv_kod": r["rv_kod"],
                "rv_ad": r["rv_ad"],
                "boyutlar": {},
            }
        boyut = r.get("boyut") or "STANDART"
        if boyut not in tree[nk]["varyantlar"][rk]["boyutlar"]:
            tree[nk]["varyantlar"][rk]["boyutlar"][boyut] = {
                "uv_id": r["uv_id"],
                "kalemler": [],
            }
        if r.get("rk_id"):
            tree[nk]["varyantlar"][rk]["boyutlar"][boyut]["kalemler"].append({
                "stok_kod": r.get("stok_kod") or "",
                "stok_ad": r.get("stok_ad") or "",
                "kategori": r.get("stok_kat") or "",
                "birim": r.get("stok_birim") or "KG",
                "miktar_kg": float(r.get("miktar_kg") or 0),
                "sira": int(r.get("sira") or 0),
            })
    return tree


# ---------------------------------------------------------------------------
# Miktar karşılaştırması
# ---------------------------------------------------------------------------
def _miktar_ayni(a: float, b: float) -> bool:
    return abs(a - b) <= MIKTAR_TOLERANCE_KG


def _fark_yuzde(eski: float, yeni: float) -> float | None:
    if abs(eski) < MIKTAR_TOLERANCE_KG:
        return None
    return round((yeni - eski) / eski * 100, 4)


def _kg_toplam(kalemler: list) -> KgToplam:
    t = KgToplam()
    for k in kalemler:
        rol = k.get("rol") if isinstance(k, dict) else getattr(k, "rol", None)
        kg = k.get("miktar_kg") if isinstance(k, dict) else getattr(k, "miktar_kg", 0.0)
        kg = float(kg or 0)
        if rol == KalemRolu.BOYA_RECETESI or (isinstance(rol, str) and rol == "BOYA_RECETESI"):
            t.boya_rf_kg = round(t.boya_rf_kg + kg, 6)
        else:
            t.ana_formul_kg = round(t.ana_formul_kg + kg, 6)
    return t


# ---------------------------------------------------------------------------
# Excel kimlik anahtarı (L1–L4)
# ---------------------------------------------------------------------------
def _excel_identity(
    formul_ad: str,
    urun_ailesi: str,
    renk_kodu: str = "",
    renk_adi: str = "",
    varyant: str = "",
    boyut: str = "",
    stok_kodu: str = "",
) -> dict:
    return {
        "L1": f"{normalize_metin(urun_ailesi)}|{normalize_metin(formul_ad)}",
        "L2": f"{normalize_metin(urun_ailesi)}|{normalize_metin(formul_ad)}|{normalize_metin(varyant)}|{renk_kodu}|{normalize_metin(renk_adi)}",
        "L3": f"{normalize_metin(urun_ailesi)}|{normalize_metin(formul_ad)}|{normalize_metin(varyant)}|{renk_kodu}|{normalize_metin(renk_adi)}|{boyut}",
        "L4": f"{normalize_metin(urun_ailesi)}|{normalize_metin(formul_ad)}|{normalize_metin(varyant)}|{renk_kodu}|{normalize_metin(renk_adi)}|{boyut}|{stok_kodu}",
    }


# ---------------------------------------------------------------------------
# Ana Diff fonksiyonu
# ---------------------------------------------------------------------------
def diff_excel_vs_db(
    pkg: ImportPackage,
    db_path: str | None = None,
    eksik_stok_kodlari: set[str] | None = None,
    business_rule_ciftleri: list[tuple[str, str, str]] | None = None,
) -> DiffSonucu:
    """
    pkg            : normalize_excel() çıktısı
    eksik_stok_kodlari : blocker stok kodları (NEX-MB-03 vs.)
    business_rule_ciftleri: [(cari_kodu, mf_kodu, not_str)]
    """
    db_path = db_path or DB_PATH
    abs_db = os.path.abspath(db_path)
    sha_once = _sha256(abs_db)

    con = db_readonly_connect(db_path)
    try:
        snap_once = db_snapshot(con, db_path)
        db_rows = _db_formuller(con)
        db_plan = _db_planlama(con)
        snap_sonra = db_snapshot(con, db_path)
    finally:
        con.close()

    sha_sonra = _sha256(abs_db)
    db_hash_degisti = sha_once != sha_sonra

    sonuc = DiffSonucu()
    sonuc.meta = {
        "excel_path": pkg.kaynak_bilgisi.get("dosya_yolu", ""),
        "excel_sha256": pkg.kaynak_bilgisi.get("dosya_sha256", ""),
        "db_path": abs_db,
        "db_sha256_before": sha_once,
        "db_sha256_after": sha_sonra,
        "read_only": True,
        "db_hash_degisti": db_hash_degisti,
        "miktar_tolerance_kg": MIKTAR_TOLERANCE_KG,
    }

    if db_hash_degisti:
        sonuc.ekle(DiffKaydi(
            sinif=DiffSinif.BLOCKER,
            change_tip=None,
            severity="KRITIK",
            entity_type="db_guvenlik",
            identity="DB_HASH",
            mesaj=f"DB hash değişti! önce={sha_once[:16]} sonra={sha_sonra[:16]}",
        ))
        sonuc.import_uygunluk = "IMPORTA_HAZIR_DEGIL"
        return sonuc

    eksik_stok_kodlari = eksik_stok_kodlari or set()
    business_rule_ciftleri = business_rule_ciftleri or []

    db_tree = _build_db_tree(db_rows)

    # -----------------------------------------------------------------------
    # Planlama tablosunu cari+formul bazlı map'e çevir
    # -----------------------------------------------------------------------
    plan_by_formul: dict[int, list[dict]] = {}
    for pu in db_plan:
        fid = pu.get("formul_id")
        if fid:
            plan_by_formul.setdefault(fid, []).append(pu)

    # Excel kullanımları: (cari, ut, formul_ad, renk_kodu) bazlı küme
    excel_kullanimlar: dict[tuple, list[NormalizedKullanim]] = {}
    for ku in pkg.kullanimlar:
        key = (ku.cari_kodu, ku.uretim_tipi, normalize_metin(ku.formul_ad), ku.renk_kodu, ku.boyut)
        excel_kullanimlar.setdefault(key, []).append(ku)

    # -----------------------------------------------------------------------
    # 1) Business rule review — önceden saptanan çakışmalar
    # -----------------------------------------------------------------------
    for cari, mf_kod, not_str in business_rule_ciftleri:
        sonuc.ekle(DiffKaydi(
            sinif=DiffSinif.BUSINESS_RULE_REVIEW,
            change_tip=ChangeTip.MUSTERI_FORMUL_KODU_CAKISMASI,
            severity="INCELEME",
            entity_type="musteri_formul_kodu",
            identity=f"{cari}/{mf_kod}",
            mesaj=not_str,
            source_sheet="TUM_FORMULLER",
        ))

    # -----------------------------------------------------------------------
    # 2) Excel formülleri → DB karşılaştırması
    # -----------------------------------------------------------------------
    excel_formul_adlar: set[str] = set()

    for formul in pkg.formuller:
        nk = normalize_metin(formul.ad)
        excel_formul_adlar.add(nk)
        ident = _excel_identity(formul.ad, formul.urun_ailesi)["L1"]

        db_entry = db_tree.get(nk)

        if db_entry is None:
            # Tamamen yeni formül
            sonuc.ekle(DiffKaydi(
                sinif=DiffSinif.YENI,
                change_tip=ChangeTip.FORMUL_EKLENDI,
                severity="BILGI",
                entity_type="formul",
                identity=ident,
                mesaj=f"Yeni formül: {formul.ad!r} ({formul.urun_ailesi})",
                new_value={"ad": formul.ad, "urun_ailesi": formul.urun_ailesi},
            ))
            # Kalemler bloker/uyarı kontrolü
            _kalem_blokerleri(formul, sonuc, eksik_stok_kodlari)
            _planlama_uygunluk_diff_excel_only(formul, pkg.kullanimlar, sonuc)
            # RF uyarıları yeni formülde de kontrol et
            for rv in formul.renk_varyantlari:
                _rf_uyarisi(rv, formul, sonuc, db_ids=[])
            continue

        db_f_id = db_entry["f_id"]

        # Ürün ailesi farkı
        db_aile = normalize_metin(db_entry.get("f_aile") or "")
        xl_aile = normalize_metin(formul.urun_ailesi or "")
        if db_aile and xl_aile and db_aile != xl_aile:
            sonuc.ekle(DiffKaydi(
                sinif=DiffSinif.DEGISTI,
                change_tip=ChangeTip.URUN_AILESI_DEGISTI,
                severity="UYARI",
                entity_type="formul",
                identity=ident,
                mesaj=f"Ürün ailesi: DB={db_aile!r} → Excel={xl_aile!r}",
                old_value=db_aile, new_value=xl_aile,
                db_ids=[db_f_id],
            ))

        db_varyantlar = db_entry.get("varyantlar", {})
        excel_renk_kodlari: set[str] = set()

        for rv in formul.renk_varyantlari:
            excel_renk_kodlari.add(rv.renk_kodu)
            rv_ident = _excel_identity(formul.ad, formul.urun_ailesi, rv.renk_kodu, rv.renk_adi)["L2"]

            db_rv = db_varyantlar.get(rv.renk_kodu)
            if db_rv is None:
                sonuc.ekle(DiffKaydi(
                    sinif=DiffSinif.YENI,
                    change_tip=ChangeTip.VARYANT_EKLENDI,
                    severity="BILGI",
                    entity_type="renk_varyant",
                    identity=rv_ident,
                    mesaj=f"Yeni varyant: renk={rv.renk_kodu!r} ({rv.renk_adi})",
                    new_value={"renk_kodu": rv.renk_kodu, "renk_adi": rv.renk_adi},
                    db_ids=[db_f_id],
                ))
                _kalem_blokerleri_rv(rv, formul, sonuc, eksik_stok_kodlari)
                continue

            db_boyutlar = db_rv.get("boyutlar", {})
            excel_boyutlar: set[str] = set()

            for boyut, nb in rv.boyutlar.items():
                excel_boyutlar.add(boyut)
                b_ident = _excel_identity(formul.ad, formul.urun_ailesi, rv.renk_kodu, rv.renk_adi, boyut=boyut)["L3"]

                db_b = db_boyutlar.get(boyut)
                if db_b is None:
                    sonuc.ekle(DiffKaydi(
                        sinif=DiffSinif.YENI,
                        change_tip=ChangeTip.BOYUT_EKLENDI,
                        severity="BILGI",
                        entity_type="boyut",
                        identity=b_ident,
                        mesaj=f"Yeni boyut: {boyut}",
                        db_ids=[db_f_id, db_rv["rv_id"]],
                    ))
                    _kalem_blokerleri_nb(nb, formul, rv, boyut, sonuc, eksik_stok_kodlari)
                    continue

                # Kalem bazlı karşılaştırma
                _kalem_diff(
                    nb.ana_kalemler + nb.boya_kalemleri,
                    db_b["kalemler"],
                    formul, rv, boyut,
                    sonuc, eksik_stok_kodlari,
                    db_ids=[db_f_id, db_rv["rv_id"], db_b["uv_id"]],
                )

            # Boyut silindi
            for db_boyut in db_boyutlar:
                if db_boyut not in excel_boyutlar:
                    b_ident = _excel_identity(formul.ad, formul.urun_ailesi, rv.renk_kodu, rv.renk_adi, boyut=db_boyut)["L3"]
                    sonuc.ekle(DiffKaydi(
                        sinif=DiffSinif.ESKIDE_VAR_YENIDE_YOK,
                        change_tip=ChangeTip.BOYUT_SILINDI,
                        severity="UYARI",
                        entity_type="boyut",
                        identity=b_ident,
                        mesaj=f"DB'de olan boyut Excel'de yok: {db_boyut}",
                        old_value=db_boyut,
                        db_ids=[db_f_id, db_rv["rv_id"]],
                    ))

            # RF uyarıları
            _rf_uyarisi(rv, formul, sonuc, db_ids=[db_f_id, db_rv["rv_id"]])

        # Renk silindi
        for db_renk in db_varyantlar:
            if db_renk not in excel_renk_kodlari:
                rv_ident = _excel_identity(formul.ad, formul.urun_ailesi, db_renk)["L2"]
                sonuc.ekle(DiffKaydi(
                    sinif=DiffSinif.ESKIDE_VAR_YENIDE_YOK,
                    change_tip=ChangeTip.VARYANT_SILINDI,
                    severity="UYARI",
                    entity_type="renk_varyant",
                    identity=rv_ident,
                    mesaj=f"DB'de olan renk Excel'de yok: {db_renk!r}",
                    old_value=db_renk,
                    db_ids=[db_f_id],
                ))

        # Planlama uygunluğu diff
        _planlama_uygunluk_diff(
            formul, pkg.kullanimlar,
            plan_by_formul.get(db_f_id, []),
            sonuc, db_ids=[db_f_id],
        )

    # -----------------------------------------------------------------------
    # 3) DB'de var, Excel'de yok
    # -----------------------------------------------------------------------
    for nk, db_entry in db_tree.items():
        if nk not in excel_formul_adlar:
            f_kod = db_entry.get("f_kod", "")
            sinif = DiffSinif.TEST_TASLAK if f_kod in TEST_TASLAK_KODLARI else DiffSinif.ESKIDE_VAR_YENIDE_YOK
            sonuc.ekle(DiffKaydi(
                sinif=sinif,
                change_tip=ChangeTip.FORMUL_ESKIDE_VAR,
                severity="BILGI",
                entity_type="formul",
                identity=f"DB:{db_entry['f_id']}:{f_kod}",
                mesaj=f"DB'de var, Excel'de yok: {db_entry['f_ad']!r} (id={db_entry['f_id']}, kod={f_kod})",
                old_value={"f_id": db_entry["f_id"], "f_kod": f_kod, "f_ad": db_entry["f_ad"]},
                db_ids=[db_entry["f_id"]],
            ))

    # -----------------------------------------------------------------------
    # 4) Import uygunluğu
    # -----------------------------------------------------------------------
    sonuc.import_uygunluk = (
        "IMPORTA_HAZIR_DEGIL" if sonuc.bloker_sayisi() > 0 else "IMPORTA_HAZIR"
    )

    return sonuc


# ---------------------------------------------------------------------------
# Yardımcı diff fonksiyonları
# ---------------------------------------------------------------------------
def _rf_uyarisi(rv: NormalizedRenkVaryanti, formul: NormalizedFormul, sonuc: DiffSonucu, db_ids: list) -> None:
    from modules.nexgen.import_models import RfDurum
    # Boya kalemleri var ama RF eksikse uyarı
    has_boya = any(
        nb.boya_kalemleri
        for nb in rv.boyutlar.values()
    )
    if has_boya and rv.rf.durum == RfDurum.EKSIK:
        ident = _excel_identity(formul.ad, formul.urun_ailesi, rv.renk_kodu, rv.renk_adi)["L2"]
        sonuc.ekle(DiffKaydi(
            sinif=DiffSinif.UYARI,
            change_tip=ChangeTip.RF_EKSIK,
            severity="UYARI",
            entity_type="rf",
            identity=ident,
            mesaj=f"Boya kalemleri var, RF bağlantısı yok: {formul.ad}/{rv.renk_kodu}",
            db_ids=db_ids,
        ))


def _kalem_blokerleri(formul: NormalizedFormul, sonuc: DiffSonucu, eksik: set[str]) -> None:
    for rv in formul.renk_varyantlari:
        _kalem_blokerleri_rv(rv, formul, sonuc, eksik)


def _kalem_blokerleri_rv(rv: NormalizedRenkVaryanti, formul: NormalizedFormul, sonuc: DiffSonucu, eksik: set[str]) -> None:
    for boyut, nb in rv.boyutlar.items():
        _kalem_blokerleri_nb(nb, formul, rv, boyut, sonuc, eksik)


def _kalem_blokerleri_nb(nb: NormalizedBoyut, formul: NormalizedFormul, rv: NormalizedRenkVaryanti, boyut: str, sonuc: DiffSonucu, eksik: set[str]) -> None:
    seen: set[str] = set()
    for k in nb.ana_kalemler + nb.boya_kalemleri:
        sc = k.stok_kodu.upper() if hasattr(k, 'stok_kodu') else k.get('stok_kodu', '').upper()
        if sc in eksik and sc not in seen:
            seen.add(sc)
            ident = _excel_identity(formul.ad, formul.urun_ailesi, rv.renk_kodu, rv.renk_adi, boyut=boyut, stok_kodu=sc)["L4"]
            hucre = k.kaynak_hucre if hasattr(k, 'kaynak_hucre') else k.get('kaynak_hucre', '')
            sonuc.ekle(DiffKaydi(
                sinif=DiffSinif.BLOCKER,
                change_tip=ChangeTip.STOK_EKSIK,
                severity="KRITIK",
                entity_type="stok",
                identity=ident,
                mesaj=f"Stok kartı DB'de yok: {sc}",
                old_value=None,
                new_value=sc,
                source_sheet="TUM_FORMULLER",
                source_cell=hucre,
            ))


def _kalem_diff(
    excel_kalemler: list,
    db_kalemler: list,
    formul: NormalizedFormul,
    rv: NormalizedRenkVaryanti,
    boyut: str,
    sonuc: DiffSonucu,
    eksik: set[str],
    db_ids: list,
) -> None:
    # DB'yi stok_kod bazlı map
    db_map: dict[str, dict] = {}
    for dk in db_kalemler:
        kod = dk.get("stok_kod", "").upper()
        if kod:
            db_map[kod] = dk

    excel_kodlar: set[str] = set()

    for ek in excel_kalemler:
        sc = (ek.stok_kodu if hasattr(ek, 'stok_kodu') else ek.get('stok_kodu', '')).upper()
        kg_xl = ek.miktar_kg if hasattr(ek, 'miktar_kg') else ek.get('miktar_kg', 0.0)
        hucre = ek.kaynak_hucre if hasattr(ek, 'kaynak_hucre') else ek.get('kaynak_hucre', '')
        ident = _excel_identity(formul.ad, formul.urun_ailesi, rv.renk_kodu, rv.renk_adi, boyut=boyut, stok_kodu=sc)["L4"]

        if sc in eksik:
            if sc not in excel_kodlar:
                sonuc.ekle(DiffKaydi(
                    sinif=DiffSinif.BLOCKER,
                    change_tip=ChangeTip.STOK_EKSIK,
                    severity="KRITIK",
                    entity_type="stok",
                    identity=ident,
                    mesaj=f"Stok kartı DB'de yok: {sc}",
                    new_value=sc,
                    source_sheet="TUM_FORMULLER",
                    source_cell=hucre,
                    db_ids=db_ids,
                ))
            excel_kodlar.add(sc)
            continue

        excel_kodlar.add(sc)
        dk = db_map.get(sc)

        if dk is None:
            sonuc.ekle(DiffKaydi(
                sinif=DiffSinif.DEGISTI,
                change_tip=ChangeTip.KALEM_EKLENDI,
                severity="BILGI",
                entity_type="kalem",
                identity=ident,
                mesaj=f"Yeni kalem: {sc}, {kg_xl:.6f} KG",
                new_value={"stok_kodu": sc, "miktar_kg": kg_xl},
                source_sheet="TUM_FORMULLER",
                source_cell=hucre,
                db_ids=db_ids,
            ))
        else:
            kg_db = float(dk.get("miktar_kg") or 0)
            if not _miktar_ayni(kg_db, kg_xl):
                fark = round(kg_xl - kg_db, 6)
                pct = _fark_yuzde(kg_db, kg_xl)
                sonuc.ekle(DiffKaydi(
                    sinif=DiffSinif.DEGISTI,
                    change_tip=ChangeTip.MIKTAR_DEGISTI,
                    severity="UYARI",
                    entity_type="kalem",
                    identity=ident,
                    mesaj=f"Miktar farkı: {sc} eski={kg_db:.6f} yeni={kg_xl:.6f} fark={fark:+.6f} KG",
                    old_value={"miktar_kg": kg_db},
                    new_value={"miktar_kg": kg_xl},
                    difference={"fark_kg": fark, "fark_yuzde": pct},
                    source_sheet="TUM_FORMULLER",
                    source_cell=hucre,
                    db_ids=db_ids,
                ))
            else:
                sonuc.ekle(DiffKaydi(
                    sinif=DiffSinif.AYNI,
                    change_tip=None,
                    severity="BILGI",
                    entity_type="kalem",
                    identity=ident,
                    mesaj=f"Aynı: {sc} = {kg_xl:.6f} KG",
                    db_ids=db_ids,
                ))

    # DB'de var, Excel'de yok
    for sc, dk in db_map.items():
        if sc not in excel_kodlar:
            ident = _excel_identity(formul.ad, formul.urun_ailesi, rv.renk_kodu, rv.renk_adi, boyut=boyut, stok_kodu=sc)["L4"]
            sonuc.ekle(DiffKaydi(
                sinif=DiffSinif.ESKIDE_VAR_YENIDE_YOK,
                change_tip=ChangeTip.KALEM_SILINDI,
                severity="UYARI",
                entity_type="kalem",
                identity=ident,
                mesaj=f"DB'de olan kalem Excel'de yok: {sc}, {dk.get('miktar_kg'):.6f} KG",
                old_value={"stok_kodu": sc, "miktar_kg": dk.get("miktar_kg")},
                db_ids=db_ids,
            ))


def _planlama_uygunluk_diff(
    formul: NormalizedFormul,
    kullanimlar: list[NormalizedKullanim],
    db_planlamalar: list[dict],
    sonuc: DiffSonucu,
    db_ids: list,
) -> None:
    f_kullanimlar = [k for k in kullanimlar if normalize_metin(k.formul_ad) == normalize_metin(formul.ad)]
    nk = normalize_metin(formul.ad)

    for ku in f_kullanimlar:
        ident = f"{ku.cari_kodu}|{ku.uretim_tipi}|{nk}|{ku.renk_kodu}|{ku.boyut}"
        # Mamul üretim kodu boş uyarısı
        if not ku.mamul_uretim_kodu:
            sonuc.ekle(DiffKaydi(
                sinif=DiffSinif.UYARI,
                change_tip=ChangeTip.MAMUL_URETIM_KODU_BOS,
                severity="UYARI",
                entity_type="planlama",
                identity=ident,
                mesaj=f"Mamul üretim kodu boş: {ku.cari_kodu}/{ku.musteri_formul_kodu}",
                source_sheet="TUM_FORMULLER",
                source_cell=ku.kaynak_hucre,
                db_ids=db_ids,
            ))

        # Kalıp çarpanı uyarısı
        if ku.kalip_carpani is None:
            sonuc.ekle(DiffKaydi(
                sinif=DiffSinif.UYARI,
                change_tip=ChangeTip.KALIP_CARPANI_DEGISTI,
                severity="UYARI",
                entity_type="planlama",
                identity=ident,
                mesaj=f"Kalıp çarpanı boş: {ku.cari_kodu}/{ku.musteri_formul_kodu}",
                source_sheet="TUM_FORMULLER",
                source_cell=ku.kaynak_hucre,
                db_ids=db_ids,
            ))

        # DB'de eşleşen planlama var mı?
        eslesen = [
            p for p in db_planlamalar
            if p.get("cari_kod") == ku.cari_kodu
            and (p.get("ut_kod") or "").upper() == (ku.uretim_tipi or "").upper()
        ]
        if not eslesen:
            sonuc.ekle(DiffKaydi(
                sinif=DiffSinif.YENI,
                change_tip=ChangeTip.PLANLAMA_UYGUNLUK_EKLENDI,
                severity="BILGI",
                entity_type="planlama",
                identity=ident,
                mesaj=f"Yeni planlama uygunluğu: {ku.cari_kodu} / {ku.uretim_tipi}",
                source_sheet="TUM_FORMULLER",
                source_cell=ku.kaynak_hucre,
                db_ids=db_ids,
            ))


def _planlama_uygunluk_diff_excel_only(
    formul: NormalizedFormul,
    kullanimlar: list[NormalizedKullanim],
    sonuc: DiffSonucu,
) -> None:
    _planlama_uygunluk_diff(formul, kullanimlar, [], sonuc, db_ids=[])
