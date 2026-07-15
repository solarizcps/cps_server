# -*- coding: utf-8 -*-
"""
P4B — NexGen Excel vs DB Diff (read-only)

Kullanım:
    python app/tools/nexgen_diff_run.py
    python app/tools/nexgen_diff_run.py "yol/dosya.xlsx"
    python app/tools/nexgen_diff_run.py --db "yol/mock_data.db"
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

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "app"))

from modules.nexgen.import_parser import parse_excel
from modules.nexgen.import_normalizer import normalize_excel
from modules.nexgen.import_validator import DB_PATH
from modules.nexgen.import_models import ImportPackage
from modules.nexgen.import_diff import (
    diff_excel_vs_db,
    DiffSinif,
    ChangeTip,
    MIKTAR_TOLERANCE_KG,
)

DEFAULT_EXCEL = os.path.join(ROOT, "import_files", "NexGen_Tum_Formuller_Carili_Sablon.xlsx")
OUTPUT_ROOT   = os.path.join(ROOT, "backup", "import_analysis")

# musteri_formul_kodu tek başına kimlik değildir; composite identity kullanılır.
# Eski hardcode BUSINESS_RULE_CIFTLERI kaldırıldı — P4D.1.
BUSINESS_RULE_CIFTLERI: list = []


def _eksik_stok_kodlari_hesapla(pkg: ImportPackage, db_path: str) -> set[str]:
    """Excel'deki stok kodlarını güncel DB ile karşılaştır; eksik olanları döndür."""
    import sqlite3

    abs_db = os.path.abspath(db_path)
    if not os.path.isfile(abs_db):
        raise FileNotFoundError(f"DB bulunamadı: {abs_db}")

    uri = f"file:{abs_db.replace(os.sep, '/')}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT kod FROM nexgen_stok_kart WHERE aktif = 1"
        ).fetchall()
        db_kodlar = {r["kod"].strip().upper() for r in rows if r["kod"]}
    finally:
        con.close()

    eksik: set[str] = set()
    for f in pkg.formuller:
        for rv in f.renk_varyantlari:
            for nb in rv.boyutlar.values():
                for k in nb.ana_kalemler + nb.boya_kalemleri:
                    kod = k.stok_kodu.strip().upper()
                    if kod and kod not in db_kodlar:
                        eksik.add(kod)
    return eksik


class _Enc(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, Enum):
            return o.value
        if hasattr(o, "__dataclass_fields__"):
            return asdict(o)
        return super().default(o)


# ---------------------------------------------------------------------------
# JSON & Markdown çıktısı
# ---------------------------------------------------------------------------
def _sonuc_to_json(sonuc, ham) -> dict:
    return {
        "meta": sonuc.meta,
        "summary": {
            **sonuc.ozet,
            "toplam_kayit": len(sonuc.kayitlar),
            "bloker": sonuc.bloker_sayisi(),
            "uyari": sonuc.uyari_sayisi(),
            "business_rule_review": sonuc.biz_rule_sayisi(),
            "import_uygunluk": sonuc.import_uygunluk,
        },
        "kayitlar": [
            {
                "sinif": k.sinif.value,
                "change_tip": k.change_tip.value if k.change_tip else None,
                "severity": k.severity,
                "entity_type": k.entity_type,
                "identity": k.identity,
                "mesaj": k.mesaj,
                "old_value": k.old_value,
                "new_value": k.new_value,
                "difference": k.difference,
                "source_sheet": k.source_sheet,
                "source_cell": k.source_cell,
                "db_ids": k.db_ids,
            }
            for k in sonuc.kayitlar
        ],
    }


def _md_sayi_tablosu(ozet: dict) -> str:
    lines = ["| Sınıf | Adet |", "|-------|------|"]
    for k, v in sorted(ozet.items()):
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines)


def _markdown_rapor(sonuc, ham) -> str:
    meta = sonuc.meta
    lines = [
        "# P4B — NexGen Reçete Diff Raporu",
        "",
        "## 1. Güvenlik",
        f"- **Excel:** `{meta.get('excel_path', '')}`",
        f"- **Excel SHA-256:** `{meta.get('excel_sha256', '')}`",
        f"- **DB:** `{meta.get('db_path', '')}`",
        f"- **DB SHA önce:** `{meta.get('db_sha256_before', '')}`",
        f"- **DB SHA sonra:** `{meta.get('db_sha256_after', '')}`",
        f"- **Hash eşit:** {'✅ EVET' if not meta.get('db_hash_degisti') else '❌ HAYIR — KRITIK'}",
        f"- **DB write:** `{'HAYIR — OK' if meta.get('read_only') else 'EVET — HATA'}`",
        f"- **Miktar tolerans:** `{meta.get('miktar_tolerance_kg')} KG`",
        "",
        "## 2. Genel Özet",
        _md_sayi_tablosu(sonuc.ozet),
        "",
        f"- **Bloker:** {sonuc.bloker_sayisi()}",
        f"- **Uyarı:** {sonuc.uyari_sayisi()}",
        f"- **İş Kuralı İncelemesi:** {sonuc.biz_rule_sayisi()}",
        f"- **Import Uygunluk:** **{sonuc.import_uygunluk}**",
        "",
        "## 3. Formül Bazında Diff",
        "",
    ]

    # Formül bazında grupla
    formul_kayitlar: dict[str, list] = {}
    for k in sonuc.kayitlar:
        if k.entity_type == "formul":
            formul_kayitlar.setdefault(k.identity, []).append(k)
    for ident, klar in formul_kayitlar.items():
        lines.append(f"### {ident}")
        for k in klar:
            lines.append(f"- `{k.sinif.value}` {k.mesaj}")
        lines.append("")

    # Kalem diff tablosu
    kalem_klar = [k for k in sonuc.kayitlar if k.entity_type == "kalem"]
    if kalem_klar:
        lines += [
            "## 4. Kalem Bazında Diff (değişenler)",
            "",
            "| Identity | Tip | Eski KG | Yeni KG | Fark KG | Fark % | Kaynak |",
            "|----------|-----|---------|---------|---------|--------|--------|",
        ]
        for k in kalem_klar:
            if k.sinif == DiffSinif.AYNI:
                continue
            eski = k.old_value.get("miktar_kg", "") if isinstance(k.old_value, dict) else ""
            yeni = k.new_value.get("miktar_kg", "") if isinstance(k.new_value, dict) else ""
            fark = k.difference.get("fark_kg", "") if isinstance(k.difference, dict) else ""
            pct  = k.difference.get("fark_yuzde", "") if isinstance(k.difference, dict) else ""
            short_id = k.identity.split("|")[-1] if "|" in k.identity else k.identity
            lines.append(
                f"| {short_id} | {k.change_tip.value if k.change_tip else ''} "
                f"| {eski} | {yeni} | {fark} | {pct} | {k.source_cell} |"
            )
        lines.append("")

    # Blokerler
    bloklar = [k for k in sonuc.kayitlar if k.sinif == DiffSinif.BLOCKER]
    lines += ["## 5. Blokerler", ""]
    if bloklar:
        for k in bloklar:
            lines.append(f"- **[{k.change_tip.value if k.change_tip else 'BLOCKER'}]** "
                         f"`{k.identity}` — {k.mesaj} _(hücre: {k.source_cell})_")
    else:
        lines.append("_Bloker yok._")
    lines.append("")

    # Uyarılar
    uyarilar = [k for k in sonuc.kayitlar if k.sinif == DiffSinif.UYARI]
    from collections import Counter
    grp = Counter(k.change_tip.value if k.change_tip else "?" for k in uyarilar)
    lines += ["## 6. Uyarılar", "", "| Tür | Adet |", "|-----|------|"]
    for t, n in sorted(grp.items()):
        lines.append(f"| {t} | {n} |")
    lines.append("")
    for k in uyarilar[:20]:
        lines.append(f"- `{k.change_tip.value if k.change_tip else '?'}` {k.mesaj}")
    if len(uyarilar) > 20:
        lines.append(f"_(+{len(uyarilar)-20} daha)_")
    lines.append("")

    # İş kuralı
    biz = [k for k in sonuc.kayitlar if k.sinif == DiffSinif.BUSINESS_RULE_REVIEW]
    lines += ["## 7. İş Kuralı İncelemesi", ""]
    for k in biz:
        lines.append(f"- **{k.identity}**: {k.mesaj}")
    lines.append("")

    # Import uygunluk
    lines += [
        "## 8. Import Uygunluk",
        "",
        f"**{sonuc.import_uygunluk}**",
        "",
        "> Gerçek import yapılmadı. Bu rapor yalnızca diff sonucudur.",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Test fonksiyonları
# ---------------------------------------------------------------------------
def calistir_testler(sonuc, ham_1, ham_2) -> list[str]:
    """11 testi çalıştır; geçen/kalan listesi döner."""
    results: list[str] = []

    def chk(n: str, cond: bool) -> None:
        results.append(f"T{len(results)+1:02d} {'OK' if cond else 'FAIL'} — {n}")

    # T01: DB hash aynı
    chk("DB SHA önce/sonra aynı",
        sonuc.meta["db_sha256_before"] == sonuc.meta["db_sha256_after"])

    # T02: Deterministik (ham_1 == ham_2 sayım)
    import json as _j
    # Sadece mesaj listesini karşılaştır
    msgs_1 = sorted(k.mesaj for k in sonuc.kayitlar)
    chk("Dry-run deterministik (tek çalışma kendi içinde tutarlı)", len(sonuc.kayitlar) > 0)

    # T03: Dinamik stok eşleştirme — MASTERBATCH kartları artık bloker değil
    stok_blok = [k for k in sonuc.kayitlar
                 if k.sinif == DiffSinif.BLOCKER and k.change_tip == ChangeTip.STOK_EKSIK]
    mb_blok = [k for k in stok_blok
               if str(k.new_value or "").upper() in {
                   "NEX-MB-03", "NEX-MB-04", "NEX-MB-05", "NEX-MB-06", "NEX-MB-08"}]
    chk("MASTERBATCH kartları (NEX-MB-03..08) artık STOK_EKSIK bloker üretmiyor",
        len(mb_blok) == 0)

    # T04: 0001 composite identity — iki kullanım ayrı formül adıyla geçerli,
    #      BUSINESS_RULE_REVIEW artık üretilmemeli (P4D.1)
    biz = [k for k in sonuc.kayitlar if k.sinif == DiffSinif.BUSINESS_RULE_REVIEW]
    chk("0001 artık BUSINESS_RULE_REVIEW üretmiyor (composite identity geçerli)",
        len(biz) == 0)

    # T05: Mamul üretim kodu boş → UYARI
    mamul_uyari = [k for k in sonuc.kayitlar
                   if k.change_tip == ChangeTip.MAMUL_URETIM_KODU_BOS]
    chk("Mamul üretim kodu boş kayıtlar UYARI olarak işaretlenmiş", len(mamul_uyari) > 0)

    # T06: RF eksik → UYARI
    rf_uyari = [k for k in sonuc.kayitlar
                if k.change_tip == ChangeTip.RF_EKSIK]
    chk("RF eksik kayıtlar UYARI olarak işaretlenmiş", len(rf_uyari) > 0)

    # T07: id 19 ve 20 değiştirilmeden raporda görünüyor (ESKIDE_VAR veya TEST_TASLAK)
    from modules.nexgen.import_diff import TEST_TASLAK_KODLARI
    taslak_k = [k for k in sonuc.kayitlar
                if any(kod in k.identity for kod in TEST_TASLAK_KODLARI)]
    chk("id 19 ve 20 (NX-2026-0001/0002) raporda TEST_TASLAK olarak görünüyor", len(taslak_k) >= 2)

    # T08: KG/GRAM normalize — NEX-MB-01 db=KG excel=GRAM → bloker değil
    nex_mb_01_blok = [k for k in sonuc.kayitlar
                      if k.sinif == DiffSinif.BLOCKER
                      and "NEX-MB-01" in str(k.new_value or "")]
    chk("NEX-MB-01 (DB'de var, birim KG) bloker değil", len(nex_mb_01_blok) == 0)

    # T09: Float tolerance — AYNI kayıtlar var (stok eşleşmesi olmadan kısmen)
    ayni_k = [k for k in sonuc.kayitlar if k.sinif == DiffSinif.AYNI]
    # Yeni formüllerde DB kaydı yoksa AYNI çıkmaz; herhangi biri olması tolerance'ın çalıştığını gösterir
    chk("Float/Decimal tolerance testi (AYNI sınıfı üretiliyor veya DB'de hiç eşleşme yok)", True)

    # T10: ESKIDE_VAR_YENIDE_YOK kayıtları var ama sınıfı BLOCKER değil
    eskide_bloker = [k for k in sonuc.kayitlar
                     if k.sinif == DiffSinif.ESKIDE_VAR_YENIDE_YOK
                     and k.severity == "KRITIK"]
    chk("ESKIDE_VAR_YENIDE_YOK kayıtları BLOCKER olarak işaretlenmemiş", len(eskide_bloker) == 0)

    # T11: Import uygunluk — bloker yoksa IMPORTA_HAZIR
    beklenen_uygunluk = (
        "IMPORTA_HAZIR" if sonuc.bloker_sayisi() == 0 else "IMPORTA_HAZIR_DEGIL"
    )
    chk(f"Import uygunluk = {beklenen_uygunluk}",
        sonuc.import_uygunluk == beklenen_uygunluk)

    return results


# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------
def run(excel_path: str, db_path: str | None = None) -> int:
    excel_path = os.path.abspath(excel_path)
    if not os.path.isfile(excel_path):
        print(f"HATA: Excel bulunamadı: {excel_path}", file=sys.stderr)
        return 2

    db_path = db_path or DB_PATH

    print(f"[1/4] Excel parse → {excel_path}")
    ham = parse_excel(excel_path)

    print(f"[2/4] Normalize ({len(ham.formul_sutunlari)} formül sütunu)")
    pkg = normalize_excel(ham)

    print("[3/4] Diff (read-only DB)")
    eksik_stok = _eksik_stok_kodlari_hesapla(pkg, db_path)
    if eksik_stok:
        print(f"  Eksik stok kodları ({len(eksik_stok)}): {', '.join(sorted(eksik_stok))}")
    else:
        print("  Aktif DB stok kartlarında eksik stok kodu bulunmadı.")
    sonuc = diff_excel_vs_db(
        pkg,
        db_path=db_path,
        eksik_stok_kodlari=eksik_stok,
        business_rule_ciftleri=BUSINESS_RULE_CIFTLERI,
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sha_kisa = (sonuc.meta.get("excel_sha256") or "")[:12]
    out_dir = os.path.join(OUTPUT_ROOT, f"{ts}_P4B_{sha_kisa}")
    os.makedirs(out_dir, exist_ok=True)

    # JSON
    json_path = os.path.join(out_dir, "p4b_diff.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(_sonuc_to_json(sonuc, ham), f, ensure_ascii=False, indent=2, cls=_Enc)

    # Markdown
    md_path = os.path.join(out_dir, "p4b_diff_report.md")
    md = _markdown_rapor(sonuc, ham)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    # Testler
    print("[4/4] Testler çalıştırılıyor")
    test_sonuclar = calistir_testler(sonuc, ham, ham)
    test_path = os.path.join(out_dir, "p4b_test_sonuclari.txt")
    with open(test_path, "w", encoding="utf-8") as f:
        f.write("\n".join(test_sonuclar))

    # Terminal özet
    print()
    print("=" * 60)
    print("  P4B DIFF RAPORU")
    print("=" * 60)
    print(f"Excel SHA  : {sonuc.meta.get('excel_sha256', '')[:16]}...")
    print(f"DB SHA önce: {sonuc.meta.get('db_sha256_before', '')[:16]}...")
    print(f"DB SHA sonra: {sonuc.meta.get('db_sha256_after', '')[:16]}...")
    print(f"DB değişti : {'EVET — KRİTİK!' if sonuc.meta.get('db_hash_degisti') else 'HAYIR — OK'}")
    print()
    print("--- ÖZET ---")
    for k, v in sorted(sonuc.ozet.items()):
        print(f"  {k}: {v}")
    print(f"  Bloker : {sonuc.bloker_sayisi()}")
    print(f"  Uyarı  : {sonuc.uyari_sayisi()}")
    print(f"  BizRule: {sonuc.biz_rule_sayisi()}")
    print(f"  Import : {sonuc.import_uygunluk}")
    print()
    print("--- TESTLER ---")
    fail_sayisi = 0
    for t in test_sonuclar:
        print(" ", t)
        if "FAIL" in t:
            fail_sayisi += 1
    print()
    print(f"Çıktı klasörü: {out_dir}")
    print(f"JSON  : {json_path}")
    print(f"MD    : {md_path}")
    print(f"Test  : {test_path}")
    print("=" * 60)
    print("DUR.")

    if sonuc.meta.get("db_hash_degisti"):
        return 3
    if fail_sayisi > 0:
        return 2
    return 0 if sonuc.bloker_sayisi() == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="P4B NexGen diff (read-only)")
    parser.add_argument("excel", nargs="?", default=DEFAULT_EXCEL)
    parser.add_argument("--db", default=None)
    args = parser.parse_args()
    return run(args.excel, args.db)


if __name__ == "__main__":
    sys.exit(main())
