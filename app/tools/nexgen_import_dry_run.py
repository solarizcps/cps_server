# -*- coding: utf-8 -*-
"""
P4A — NexGen Excel import dry-run (read-only).

Kullanım:
    python app/tools/nexgen_import_dry_run.py
    python app/tools/nexgen_import_dry_run.py "C:\\Solariz_CPS_SERVER\\import_files\\NexGen_Tum_Formuller_Carili_Sablon.xlsx"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any

# app/ kökünü path'e ekle
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "app"))

from modules.nexgen.import_parser import parse_excel, sha256_dosya
from modules.nexgen.import_normalizer import normalize_excel
from modules.nexgen.import_validator import (
    db_readonly_connect,
    db_snapshot,
    validate_import,
    DB_PATH,
)

DEFAULT_EXCEL = os.path.join(
    ROOT, "import_files", "NexGen_Tum_Formuller_Carili_Sablon.xlsx"
)
OUTPUT_ROOT = os.path.join(ROOT, "backup", "import_analysis")


class _JsonEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, Enum):
            return o.value
        if hasattr(o, "__dataclass_fields__"):
            return asdict(o)
        return super().default(o)


def _paket_json(pkg) -> dict:
    return json.loads(json.dumps(asdict(pkg), cls=_JsonEncoder))


def _validation_json(vr) -> dict:
    return {
        "ozet": vr.ozet,
        "bloker_sayisi": vr.bloker_sayisi,
        "uyari_sayisi": vr.uyari_sayisi,
        "db_hash_degisti": vr.db_hash_degisti,
        "db_oncesi": vr.db_oncesi,
        "db_sonrasi": vr.db_sonrasi,
        "kayitlar": [
            {
                "sinif": k.sinif.value,
                "nesne_tipi": k.nesne_tipi,
                "anahtar": k.anahtar,
                "mesaj": k.mesaj,
                "guven": k.guven.value,
                "detay": k.detay,
            }
            for k in vr.kayitlar
        ],
    }


def _sayimlar(pkg) -> dict[str, int]:
    renk = sum(len(f.renk_varyantlari) for f in pkg.formuller)
    boyut = sum(
        len(rv.boyutlar)
        for f in pkg.formuller
        for rv in f.renk_varyantlari
    )
    ana_k = sum(
        len(nb.ana_kalemler)
        for f in pkg.formuller
        for rv in f.renk_varyantlari
        for nb in rv.boyutlar.values()
    )
    boya_k = sum(
        len(nb.boya_kalemleri)
        for f in pkg.formuller
        for rv in f.renk_varyantlari
        for nb in rv.boyutlar.values()
    )
    return {
        "ana_formul": len(pkg.formuller),
        "renk": renk,
        "boyut": boyut,
        "ana_kalem": ana_k,
        "boya_kalem": boya_k,
        "kullanim": len(pkg.kullanimlar),
        "stok_ref": len(pkg.stok_referanslari),
        "cari_ref": len(pkg.cari_referanslari),
        "formul_sutun": pkg.kaynak_bilgisi.get("formul_sutun_sayisi", 0),
    }


def _human_report(ham, pkg, vr, sayim: dict) -> str:
    lines = [
        "=" * 60,
        "  NEXGEN IMPORT DRY-RUN RAPORU (P4A)",
        "=" * 60,
        "",
        f"Excel:     {ham.dosya_yolu}",
        f"SHA-256:   {ham.dosya_sha256}",
        f"Boyut:     {ham.dosya_boyut:,} byte",
        f"Değişim:   {ham.dosya_modified}",
        f"Sayfalar:  {', '.join(ham.sayfa_adlari)}",
        "",
        "--- OKUNAN VERİ ---",
        f"Formül sütunları:  {sayim['formul_sutun']}",
        f"Ana formül:        {sayim['ana_formul']}",
        f"Renk varyantı:     {sayim['renk']}",
        f"Boyut:             {sayim['boyut']}",
        f"Ana kalem:         {sayim['ana_kalem']}",
        f"Boya kalem:         {sayim['boya_kalem']}",
        f"Kullanım:          {sayim['kullanim']}",
        f"Stok referans:     {sayim['stok_ref']}",
        f"Cari referans:     {sayim['cari_ref']}",
        "",
        "--- VALIDATION ÖZET ---",
    ]
    for sinif, adet in sorted(vr.ozet.items()):
        lines.append(f"  {sinif}: {adet}")
    lines.extend([
        f"  BLOKER toplam: {vr.bloker_sayisi}",
        f"  UYARI toplam:  {vr.uyari_sayisi}",
        "",
        "--- DB GÜVENLİK ---",
        f"DB önce SHA:  {vr.db_oncesi.get('db_sha256', '?')[:16]}...",
        f"DB sonra SHA: {vr.db_sonrasi.get('db_sha256', '?')[:16]}...",
        f"DB değişti:   {'EVET — HATA!' if vr.db_hash_degisti else 'HAYIR — OK'}",
        "",
        "Tablo sayımları (önce → sonra):",
    ])
    for t, once in (vr.db_oncesi.get("tablolar") or {}).items():
        sonra = (vr.db_sonrasi.get("tablolar") or {}).get(t)
        flag = " ***" if once != sonra else ""
        lines.append(f"  {t}: {once} → {sonra}{flag}")

    blokler = [k for k in vr.kayitlar if k.sinif.value == "BLOKER_HATA"]
    if blokler:
        lines.extend(["", "--- BLOKER HATALAR (ilk 30) ---"])
        for k in blokler[:30]:
            lines.append(f"  [{k.nesne_tipi}] {k.anahtar}: {k.mesaj}")

    uyarilar = [k for k in vr.kayitlar if k.sinif.value == "UYARI"]
    if uyarilar:
        lines.extend(["", "--- UYARILAR (ilk 20) ---"])
        for k in uyarilar[:20]:
            lines.append(f"  [{k.nesne_tipi}] {k.anahtar}: {k.mesaj}")

    mb = [k for k in vr.kayitlar if k.nesne_tipi == "masterbatch_rol"]
    if mb:
        lines.extend(["", "--- MASTERBATCH ROL SORUNLARI ---"])
        for k in mb:
            lines.append(f"  {k.anahtar}: {k.mesaj}")

    lines.extend(["", "=" * 60, "DUR."])
    return "\n".join(lines)


def _tekillik_analizi(pkg) -> dict:
    """Migration önerisi için müşteri kodu / mamul kodu çakışma analizi."""
    mfk_cari: dict[str, set[str]] = {}
    mfk_cari_ad: dict[str, dict[str, set[str]]] = {}
    mamul: dict[str, set[str]] = {}

    for ku in pkg.kullanimlar:
        if ku.musteri_formul_kodu and ku.cari_kodu:
            mfk_cari.setdefault(ku.cari_kodu, set()).add(ku.musteri_formul_kodu)
            mfk_cari_ad.setdefault(ku.cari_kodu, {}).setdefault(
                ku.musteri_formul_kodu, set()
            ).add(ku.formul_ad)
        if ku.mamul_uretim_kodu:
            mamul.setdefault(ku.mamul_uretim_kodu, set()).add(ku.formul_ad)

    mfk_cakisma = {
        ck: {code: list(ads) for code, ads in codes.items() if len(ads) > 1}
        for ck, codes in mfk_cari_ad.items()
        if any(len(ads) > 1 for ads in codes.values())
    }
    mamul_cakisma = {k: list(v) for k, v in mamul.items() if len(v) > 1}

    return {
        "musteri_formul_kodu_cari_bazinda_unique_onerisi": (
            "cari_id + musteri_formul_kodu UNIQUE önerilir"
            if mfk_cakisma else
            "Mevcut Excel'de cari bazında müşteri kodu çakışması yok"
        ),
        "musteri_formul_kodu_cakismalar": mfk_cakisma,
        "mamul_uretim_kodu_global_cakisma": mamul_cakisma,
        "mamul_oneri": (
            "global UNIQUE önerilir" if mamul_cakisma else
            "cari bazında UNIQUE yeterli olabilir"
        ),
        "planlama_uygunluk_yeni_kolonlar": [
            "musteri_formul_kodu TEXT NULL",
            "mamul_uretim_kodu TEXT NULL",
        ],
    }


def run_dry_run(excel_path: str, db_path: str | None = None) -> int:
    excel_path = os.path.abspath(excel_path)
    if not os.path.isfile(excel_path):
        print(f"HATA: Dosya bulunamadı: {excel_path}", file=sys.stderr)
        return 2

    db_path = db_path or DB_PATH
    con = db_readonly_connect(db_path)
    db_oncesi = db_snapshot(con, db_path)
    con.close()

    print(f"[1/4] Excel okunuyor: {excel_path}")
    ham = parse_excel(excel_path)

    print(f"[2/4] Normalize ediliyor ({len(ham.formul_sutunlari)} formül sütunu)")
    pkg = normalize_excel(ham)

    print("[3/4] Validation (read-only DB)")
    vr = validate_import(pkg, db_path=db_path, db_oncesi=db_oncesi)

    sayim = _sayimlar(pkg)
    tekillik = _tekillik_analizi(pkg)

    sha_kisa = ham.dosya_sha256[:12]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(OUTPUT_ROOT, f"{ts}_{sha_kisa}")
    os.makedirs(out_dir, exist_ok=True)

    manifest = {
        "excel_path": ham.dosya_yolu,
        "excel_sha256": ham.dosya_sha256,
        "excel_size": ham.dosya_boyut,
        "excel_modified": ham.dosya_modified,
        "sheets": ham.sayfa_adlari,
        "dry_run_time": datetime.now().isoformat(sep=" "),
        "sayimlar": sayim,
        "tekillik_analizi": tekillik,
        "import_log_tasarimi": {
            "nexgen_import_batch": [
                "id", "dosya_adi", "dosya_sha256", "durum",
                "analiz_zamani", "onay_zamani", "import_zamani",
                "analiz_eden_id", "onaylayan_id", "import_eden_id",
                "yeni_formul_sayisi", "degisen_formul_sayisi",
                "hata_sayisi", "uyari_sayisi",
                "kaynak_manifest_json", "rollback_yedek_yolu",
            ],
            "nexgen_import_item_log": [
                "import_batch_id", "kaynak_sayfa", "kaynak_hucre",
                "nesne_tipi", "eski_id", "yeni_id", "aksiyon",
                "eski_fingerprint", "yeni_fingerprint", "detay_json",
            ],
        },
    }

    with open(os.path.join(out_dir, "import_package.json"), "w", encoding="utf-8") as f:
        json.dump(_paket_json(pkg), f, ensure_ascii=False, indent=2, cls=_JsonEncoder)

    with open(os.path.join(out_dir, "validation_result.json"), "w", encoding="utf-8") as f:
        json.dump(_validation_json(vr), f, ensure_ascii=False, indent=2)

    with open(os.path.join(out_dir, "source_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    report = _human_report(ham, pkg, vr, sayim)
    report_path = os.path.join(out_dir, "human_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"[4/4] Raporlar: {out_dir}")
    print(report)

    if vr.db_hash_degisti:
        print("\n*** DB DEĞİŞTİ — DRY-RUN BAŞARISIZ ***", file=sys.stderr)
        return 3

    return 0 if vr.bloker_sayisi == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="NexGen Excel import dry-run")
    parser.add_argument(
        "excel",
        nargs="?",
        default=DEFAULT_EXCEL,
        help="Excel dosya yolu",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite DB yolu (varsayılan: app/mock_data.db)",
    )
    args = parser.parse_args()
    return run_dry_run(args.excel, args.db)


if __name__ == "__main__":
    sys.exit(main())
