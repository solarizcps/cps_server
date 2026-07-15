# -*- coding: utf-8 -*-
"""P4A — Read-only DB eşleştirme ve validation."""
from __future__ import annotations

import hashlib
import math
import os
import sqlite3
from typing import Any

from modules.nexgen.import_models import (
    EslesmeGuveni,
    GECERLI_KATEGORILER,
    GECERLI_URETIM_TIPLERI,
    ImportPackage,
    KalemRolu,
    RfDurum,
    ValidationKaydi,
    ValidationResult,
    ValidationSinif,
)
from modules.nexgen.import_normalizer import (
    fingerprint_ana_kalemler,
    fingerprint_boya_kalemler,
    normalize_metin,
)

DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "mock_data.db"
)

KRITIK_TABLOLAR = [
    "nexgen_formul",
    "nexgen_renk_varyant",
    "nexgen_uretim_varyant",
    "nexgen_recete_kalem",
    "nexgen_rf_renk",
    "nexgen_rf_kalem",
    "nexgen_planlama_uygunluk",
    "nexgen_uretim_plan",
    "nexgen_uretim_batch",
]


def sha256_dosya(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def db_readonly_connect(db_path: str | None = None) -> sqlite3.Connection:
    path = os.path.abspath(db_path or DB_PATH)
    uri = f"file:{path}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def db_snapshot(con: sqlite3.Connection, db_path: str | None = None) -> dict[str, Any]:
    path = os.path.abspath(db_path or DB_PATH)
    snap: dict[str, Any] = {"db_sha256": sha256_dosya(path), "tablolar": {}}
    for t in KRITIK_TABLOLAR:
        try:
            snap["tablolar"][t] = con.execute(
                f"SELECT COUNT(*) AS c FROM {t}"
            ).fetchone()["c"]
        except sqlite3.OperationalError:
            snap["tablolar"][t] = None
    return snap


def _stok_map(con: sqlite3.Connection) -> dict[str, dict]:
    rows = con.execute(
        "SELECT id, kod, ad, kategori, birim, aktif FROM nexgen_stok_kart"
    ).fetchall()
    return {r["kod"].strip().upper(): dict(r) for r in rows if r["kod"]}


def _cari_map(con: sqlite3.Connection) -> dict[str, dict]:
    rows = con.execute(
        "SELECT id, cari_kod, unvan, aktif FROM nexgen_cari"
    ).fetchall()
    return {r["cari_kod"].strip(): dict(r) for r in rows if r["cari_kod"]}


def _ut_map(con: sqlite3.Connection) -> dict[str, dict]:
    rows = con.execute(
        "SELECT id, kod, ad, aktif FROM nexgen_uretim_tipi"
    ).fetchall()
    return {r["kod"].strip().upper(): dict(r) for r in rows if r["kod"]}


def _mevcut_formuller(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute("""
        SELECT f.id, f.kod, f.ad, f.urun_ailesi, f.durum, f.aktif,
               rv.id AS rv_id, rv.renk, rv.kod AS rv_kod,
               uv.id AS uv_id, uv.boyut,
               rk.stok_kart_id, sk.kod AS stok_kod, rk.miktar_kg, rk.sira,
               sk.kategori
        FROM nexgen_formul f
        JOIN nexgen_renk_varyant rv ON rv.formul_id = f.id AND rv.aktif = 1
        JOIN nexgen_uretim_varyant uv ON uv.renk_varyant_id = rv.id AND uv.aktif = 1
        LEFT JOIN nexgen_recete_kalem rk ON rk.uretim_varyant_id = uv.id AND rk.aktif = 1
        LEFT JOIN nexgen_stok_kart sk ON sk.id = rk.stok_kart_id
        WHERE f.aktif = 1
        ORDER BY f.id, rv.id, uv.id, rk.sira
    """).fetchall()
    return [dict(r) for r in rows]


def _formul_fingerprint_db(rows: list[dict], formul_id: int) -> dict[str, str]:
    """DB'deki bir formül için boyut bazlı fingerprint."""
    from modules.nexgen.import_models import NormalizedKalem

    fps: dict[str, str] = {}
    subset = [r for r in rows if r["id"] == formul_id]
    if not subset:
        return fps

    boyut_kalemler: dict[str, list] = {}
    for r in subset:
        if not r.get("uv_id") or not r.get("stok_kod"):
            continue
        b = r.get("boyut") or "STANDART"
        boyut_kalemler.setdefault(b, []).append(
            NormalizedKalem(
                stok_kodu=r["stok_kod"],
                miktar_kg=float(r["miktar_kg"] or 0),
                kategori=(r.get("kategori") or "HAMMADDE").upper(),
                rol=KalemRolu.ANA_FORMUL,
                sira=int(r.get("sira") or 0),
            )
        )
    for b, klist in boyut_kalemler.items():
        fps[b] = fingerprint_ana_kalemler(klist, b)
    return fps


def validate_import(
    pkg: ImportPackage,
    db_path: str | None = None,
    db_oncesi: dict[str, Any] | None = None,
) -> ValidationResult:
    con = db_readonly_connect(db_path)
    try:
        if db_oncesi is None:
            db_oncesi = db_snapshot(con, db_path)

        result = ValidationResult(
            import_package=pkg,
            db_oncesi=db_oncesi,
        )

        stok = _stok_map(con)
        cari = _cari_map(con)
        ut = _ut_map(con)
        db_rows = _mevcut_formuller(con)

        db_formul_by_ad: dict[str, list[int]] = {}
        for r in db_rows:
            key = normalize_metin(r.get("ad") or "")
            db_formul_by_ad.setdefault(key, [])
            if r["id"] not in db_formul_by_ad[key]:
                db_formul_by_ad[key].append(r["id"])

        # Stok eşleştirme
        for f in pkg.formuller:
            for rv in f.renk_varyantlari:
                for boyut, nb in rv.boyutlar.items():
                    for k in nb.ana_kalemler + nb.boya_kalemleri:
                        if k.kategori and k.kategori not in GECERLI_KATEGORILER:
                            result.ekle(ValidationKaydi(
                                sinif=ValidationSinif.BLOKER_HATA,
                                nesne_tipi="stok_kategori",
                                anahtar=k.stok_kodu,
                                mesaj=f"Bilinmeyen kategori: {k.kategori}",
                                detay={"hucre": k.kaynak_hucre},
                            ))
                        if k.rol == KalemRolu.BELIRSIZ:
                            result.ekle(ValidationKaydi(
                                sinif=ValidationSinif.BLOKER_HATA,
                                nesne_tipi="masterbatch_rol",
                                anahtar=k.stok_kodu,
                                mesaj="MASTERBATCH kullanım rolü belirsiz",
                                detay={"kategori": k.kategori, "birim": k.birim},
                            ))
                        if k.miktar_kg <= 0 or math.isnan(k.miktar_kg):
                            result.ekle(ValidationKaydi(
                                sinif=ValidationSinif.BLOKER_HATA,
                                nesne_tipi="miktar",
                                anahtar=k.stok_kodu,
                                mesaj=f"Geçersiz miktar: {k.miktar_kg}",
                            ))
                        sk = stok.get(k.stok_kodu.upper())
                        if not sk:
                            result.ekle(ValidationKaydi(
                                sinif=ValidationSinif.BLOKER_HATA,
                                nesne_tipi="stok",
                                anahtar=k.stok_kodu,
                                mesaj="Stok kodu eşleşmedi",
                                guven=EslesmeGuveni.ESLESMEDI,
                            ))
                        elif not sk.get("aktif"):
                            result.ekle(ValidationKaydi(
                                sinif=ValidationSinif.BLOKER_HATA,
                                nesne_tipi="stok",
                                anahtar=k.stok_kodu,
                                mesaj="Stok kartı pasif",
                                guven=EslesmeGuveni.KESIN,
                            ))
                        else:
                            k.stok_kart_id = sk["id"]

        # Duplicate stok aynı boyutta
        for f in pkg.formuller:
            for rv in f.renk_varyantlari:
                for boyut, nb in rv.boyutlar.items():
                    seen: set[str] = set()
                    for k in nb.ana_kalemler:
                        if k.stok_kodu in seen:
                            result.ekle(ValidationKaydi(
                                sinif=ValidationSinif.BLOKER_HATA,
                                nesne_tipi="duplicate_stok",
                                anahtar=f"{f.ad}/{boyut}/{k.stok_kodu}",
                                mesaj="Aynı boyutta duplicate stok",
                            ))
                        seen.add(k.stok_kodu)

        # Cari / üretim tipi
        for ku in pkg.kullanimlar:
            if not ku.cari_kodu:
                result.ekle(ValidationKaydi(
                    sinif=ValidationSinif.BLOKER_HATA,
                    nesne_tipi="cari",
                    anahtar=ku.formul_sutun,
                    mesaj="Cari kodu boş",
                ))
            else:
                cr = cari.get(ku.cari_kodu.strip())
                if not cr:
                    result.ekle(ValidationKaydi(
                        sinif=ValidationSinif.BLOKER_HATA,
                        nesne_tipi="cari",
                        anahtar=ku.cari_kodu,
                        mesaj="Cari eşleşmedi",
                        guven=EslesmeGuveni.ESLESMEDI,
                    ))
                elif not cr.get("aktif"):
                    result.ekle(ValidationKaydi(
                        sinif=ValidationSinif.BLOKER_HATA,
                        nesne_tipi="cari",
                        anahtar=ku.cari_kodu,
                        mesaj="Cari pasif",
                    ))
                else:
                    ku.cari_id = cr["id"]

            ut_kod = (ku.uretim_tipi or "").upper()
            if ut_kod not in GECERLI_URETIM_TIPLERI:
                result.ekle(ValidationKaydi(
                    sinif=ValidationSinif.BLOKER_HATA,
                    nesne_tipi="uretim_tipi",
                    anahtar=ut_kod,
                    mesaj=f"Geçersiz üretim tipi: {ut_kod}",
                ))
            else:
                ut_row = ut.get(ut_kod)
                if not ut_row:
                    result.ekle(ValidationKaydi(
                        sinif=ValidationSinif.BLOKER_HATA,
                        nesne_tipi="uretim_tipi",
                        anahtar=ut_kod,
                        mesaj="Üretim tipi DB'de yok",
                    ))
                elif not ut_row.get("aktif"):
                    result.ekle(ValidationKaydi(
                        sinif=ValidationSinif.UYARI,
                        nesne_tipi="uretim_tipi",
                        anahtar=ut_kod,
                        mesaj="Üretim tipi pasif",
                    ))
                else:
                    ku.uretim_tipi_id = ut_row["id"]

            if ku.kalip_carpani is not None and ku.kalip_carpani <= 0:
                result.ekle(ValidationKaydi(
                    sinif=ValidationSinif.BLOKER_HATA,
                    nesne_tipi="kalip_carpani",
                    anahtar=ku.musteri_formul_kodu,
                    mesaj=f"Geçersiz kalıp çarpanı: {ku.kalip_carpani}",
                ))
            elif ku.kalip_carpani is None:
                result.ekle(ValidationKaydi(
                    sinif=ValidationSinif.UYARI,
                    nesne_tipi="kalip_carpani",
                    anahtar=ku.musteri_formul_kodu,
                    mesaj="Kalıp çarpanı boş",
                ))

            if not ku.mamul_uretim_kodu:
                result.ekle(ValidationKaydi(
                    sinif=ValidationSinif.UYARI,
                    nesne_tipi="mamul_uretim_kodu",
                    anahtar=ku.musteri_formul_kodu,
                    mesaj="Mamul üretim kodu boş",
                ))

            for formul in pkg.formuller:
                if normalize_metin(formul.ad) != normalize_metin(ku.formul_ad):
                    continue
                for rv in formul.renk_varyantlari:
                    if rv.renk_kodu != ku.renk_kodu:
                        continue
                    nb = rv.boyutlar.get(ku.boyut)
                    if rv.rf.durum == RfDurum.EKSIK and nb and nb.boya_kalemleri:
                        result.ekle(ValidationKaydi(
                            sinif=ValidationSinif.UYARI,
                            nesne_tipi="rf",
                            anahtar=f"{ku.formul_ad}/{ku.renk_kodu}",
                            mesaj="RF eksik — boya kalemleri var, RF bağlantısı yok",
                        ))
                    break

        # Kullanım duplicate kontrolü — 6-alan composite identity (P4D.2)
        # musteri_formul_kodu tek başına kimlik değildir.
        # Aynı (cari, ut, formul_ad, varyant, renk_kodu, boyut) = BLOKER_HATA
        # Farklı herhangi bir alan = ayrı geçerli kullanım
        kullanim_identity_set: set[tuple] = set()
        for ku in pkg.kullanimlar:
            if not ku.cari_kodu:
                continue
            composite = (
                ku.cari_kodu.strip(),
                (ku.uretim_tipi or "").strip().upper(),
                normalize_metin(ku.formul_ad),
                normalize_metin(ku.varyant),
                (ku.renk_kodu or "").strip().upper(),
                (ku.boyut or "").strip().upper(),
            )
            if composite in kullanim_identity_set:
                result.ekle(ValidationKaydi(
                    sinif=ValidationSinif.BLOKER_HATA,
                    nesne_tipi="duplicate_kullanim",
                    anahtar=f"{ku.cari_kodu}/{ku.musteri_formul_kodu}/{ku.formul_ad}",
                    mesaj=(
                        f"Birebir tekrar kullanım kaydı (gerçek duplicate): "
                        f"{ku.cari_kodu} / {ku.uretim_tipi} / {ku.formul_ad} / "
                        f"varyant={ku.varyant} renk={ku.renk_kodu} boyut={ku.boyut}"
                    ),
                ))
            else:
                kullanim_identity_set.add(composite)

        # Formül karşılaştırma (fingerprint)
        for f in pkg.formuller:
            ad_key = normalize_metin(f.ad)
            db_ids = db_formul_by_ad.get(ad_key, [])
            if not db_ids:
                result.ekle(ValidationKaydi(
                    sinif=ValidationSinif.YENI,
                    nesne_tipi="formul",
                    anahtar=f.ad,
                    mesaj="Yeni formül adayı",
                    guven=EslesmeGuveni.ESLESMEDI,
                ))
                continue

            eslesen_id = None
            guven = EslesmeGuveni.BELIRSIZ
            for fid in db_ids:
                db_fps = _formul_fingerprint_db(db_rows, fid)
                excel_fps = {
                    b: nb.fingerprint_ana
                    for rv in f.renk_varyantlari
                    for b, nb in rv.boyutlar.items()
                    if nb.fingerprint_ana
                }
                if db_fps == excel_fps:
                    eslesen_id = fid
                    guven = EslesmeGuveni.KESIN
                    break
                overlap = set(db_fps.values()) & set(excel_fps.values())
                if overlap:
                    eslesen_id = fid
                    guven = EslesmeGuveni.YUKSEK

            if eslesen_id and guven == EslesmeGuveni.KESIN:
                result.ekle(ValidationKaydi(
                    sinif=ValidationSinif.AYNI,
                    nesne_tipi="formul",
                    anahtar=f.ad,
                    mesaj=f"Mevcut formül ile aynı (id={eslesen_id})",
                    guven=guven,
                    detay={"formul_id": eslesen_id},
                ))
            elif eslesen_id and guven == EslesmeGuveni.YUKSEK:
                result.ekle(ValidationKaydi(
                    sinif=ValidationSinif.DEGISTI,
                    nesne_tipi="formul",
                    anahtar=f.ad,
                    mesaj=f"Benzer formül, içerik farklı olabilir (id={eslesen_id})",
                    guven=guven,
                    detay={"formul_id": eslesen_id},
                ))
            elif len(db_ids) > 1:
                result.ekle(ValidationKaydi(
                    sinif=ValidationSinif.CAKISMA,
                    nesne_tipi="formul",
                    anahtar=f.ad,
                    mesaj=f"Birden fazla DB formülü aynı ada sahip: {db_ids}",
                    guven=EslesmeGuveni.BELIRSIZ,
                ))
            else:
                result.ekle(ValidationKaydi(
                    sinif=ValidationSinif.DEGISTI,
                    nesne_tipi="formul",
                    anahtar=f.ad,
                    mesaj=f"Ad eşleşti ama içerik farklı (id={db_ids[0]})",
                    guven=EslesmeGuveni.ORTA,
                    detay={"formul_id": db_ids[0]},
                ))

        # Eski formüllerde olup Excel'de olmayan
        excel_adlar = {normalize_metin(f.ad) for f in pkg.formuller}
        for ad_norm, fids in db_formul_by_ad.items():
            if ad_norm and ad_norm not in excel_adlar:
                for fid in fids:
                    result.ekle(ValidationKaydi(
                        sinif=ValidationSinif.ESKIDE_VAR_YENIDE_YOK,
                        nesne_tipi="formul",
                        anahtar=ad_norm,
                        mesaj=f"DB'de var, Excel'de yok (id={fid})",
                        guven=EslesmeGuveni.KESIN,
                    ))

        # Parser uyarıları → UYARI
        for u in pkg.uyarilar:
            if "çakış" in u.lower() or "cakisma" in u.lower():
                result.ekle(ValidationKaydi(
                    sinif=ValidationSinif.CAKISMA,
                    nesne_tipi="parser",
                    anahtar="",
                    mesaj=u,
                ))
            else:
                result.ekle(ValidationKaydi(
                    sinif=ValidationSinif.UYARI,
                    nesne_tipi="parser",
                    anahtar="",
                    mesaj=u,
                ))

        db_sonrasi = db_snapshot(con, db_path)
        result.db_sonrasi = db_sonrasi
        result.db_hash_degisti = (
            db_oncesi.get("db_sha256") != db_sonrasi.get("db_sha256")
            or db_oncesi.get("tablolar") != db_sonrasi.get("tablolar")
        )

        return result
    finally:
        con.close()
