# -*- coding: utf-8 -*-
"""
P5B.1 — NexGen Import Apply CLI  (v5 — RF Identity + Bağımlılık)
P5C-3A — kontrollü gerçek DB partial apply (--allow-real-db-partial)
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "app"))

from modules.nexgen.import_parser import parse_excel, sha256_dosya
from modules.nexgen.import_normalizer import normalize_excel
from modules.nexgen.import_validator import DB_PATH, db_readonly_connect
from modules.nexgen.import_diff import diff_excel_vs_db, DiffSinif
from modules.nexgen.import_engine import (
    preflight_kontrol,
    simulate_import,
    execute_import,
    execute_partial_import,
    build_partial_import_plan,
    test_partial_transaction,
    db_yedek_al,
    _sha256,
    AKTIF_BATCH_DURUMLARI,
    PARTIAL_TOKEN_PREFIX,
)

DEFAULT_EXCEL  = os.path.join(ROOT, "import_files", "NexGen_Tum_Formuller_Carili_Sablon.xlsx")
OUTPUT_ROOT    = os.path.join(ROOT, "backup", "import_analysis")
BACKUP_ROOT    = os.path.join(ROOT, "backup", "import_analysis")
REAL_DB_PATH   = os.path.abspath(DB_PATH)

# P5C-3A — exit code'lar (gerçek DB partial apply doğrulama)
EXIT_ARG = 1
EXIT_PREFLIGHT = 2
EXIT_BLOCKED = 3
EXIT_APPLY_ERR = 4
EXIT_TOKEN = 5
EXIT_NO_BYPASS = 6
EXIT_TX_FAIL = 7
EXIT_NO_BACKUP = 8
EXIT_BACKUP_SHA = 9
EXIT_SCHEMA = 10
EXIT_SCHEMA_IDENTITY = 11
EXIT_RV_UNRESOLVED = 12


def _migration101_schema_ok(db_path: str) -> tuple[bool, str]:
    """Migration 101: musteri_renk_kodu, boyut kolonları ve uq_npu_identity."""
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cols = {c[1] for c in cur.execute(
            "PRAGMA table_info(nexgen_planlama_uygunluk)"
        ).fetchall()}
        if "musteri_renk_kodu" not in cols:
            return False, "musteri_renk_kodu kolonu yok"
        if "boyut" not in cols:
            return False, "boyut kolonu yok"
        idx = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='uq_npu_identity'"
        ).fetchone()
        if not idx:
            return False, "uq_npu_identity indexi yok"
        con.close()
        return True, ""
    except sqlite3.Error as e:
        return False, str(e)


def _dogrula_gercek_db_partial(
    *,
    db_path: str,
    confirm: str,
    partial_plan: Any,
    sim: Any,
    allow_real: bool,
    backup_file: str,
    db_sha_once: str,
) -> tuple[int, str]:
    """
    P5C-3A — gerçek DB partial apply ön koşulları.
    Döner: (0, '') başarı; aksi halde (exit_code, mesaj).
    """
    is_real = os.path.abspath(db_path) == REAL_DB_PATH

    if is_real:
        if not allow_real:
            return (
                EXIT_NO_BYPASS,
                "Gerçek DB partial apply için --allow-real-db-partial zorunlu.",
            )
        if confirm != partial_plan.confirm_token:
            return (
                EXIT_TOKEN,
                f"Token uyuşmuyor. Beklenen: {partial_plan.confirm_token}",
            )
        ok, msg = _migration101_schema_ok(db_path)
        if not ok:
            return EXIT_SCHEMA, f"Migration 101 şema eksik: {msg}"
        if partial_plan.schema_identity_eksik:
            return (
                EXIT_SCHEMA_IDENTITY,
                "SCHEMA_IDENTITY_EKSIK: musteri_renk_kodu/boyut şema kontrolü başarısız.",
            )
        rv_unres = sim.ozet.get("PLANLAMA_RV_UNRESOLVED", 0)
        if rv_unres > 0:
            return (
                EXIT_RV_UNRESOLVED,
                f"PLANLAMA_RV_UNRESOLVED={rv_unres} — apply başlamadan durduruldu.",
            )
        if not backup_file or not str(backup_file).strip():
            return (
                EXIT_NO_BACKUP,
                "Gerçek DB partial apply için --backup-file zorunlu.",
            )
        backup_abs = os.path.abspath(backup_file)
        if not os.path.isfile(backup_abs):
            return EXIT_NO_BACKUP, f"Backup dosyası bulunamadı: {backup_abs}"
        backup_sha = _sha256(backup_abs)
        if backup_sha != db_sha_once:
            return (
                EXIT_BACKUP_SHA,
                "Backup SHA apply öncesi DB SHA ile eşleşmiyor.",
            )
        return 0, ""

    # Geçici / alternatif DB — yalnız token kontrolü
    if confirm != partial_plan.confirm_token:
        return (
            EXIT_TOKEN,
            f"Token uyuşmuyor. Beklenen: {partial_plan.confirm_token}",
        )
    return 0, ""


class _Enc(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, Enum):
            return o.value
        if hasattr(o, "__dataclass_fields__"):
            return asdict(o)
        return super().default(o)


def _yaz_json(yol: str, veri: Any) -> None:
    with open(yol, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=2, cls=_Enc)


def _baslik(metin: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {metin}")
    print(f"{'=' * 60}")


def _calistir(args: argparse.Namespace) -> int:
    excel_path = os.path.abspath(args.excel)
    db_path    = os.path.abspath(args.db)
    apply_mod  = args.apply
    partial_mod = getattr(args, "apply_partial", False)
    test_tx_mod = getattr(args, "test_partial_tx", False)
    confirm    = getattr(args, "confirm", "") or ""
    force      = getattr(args, 'force', False)
    allow_real = getattr(args, "allow_real_db_partial", False)
    backup_file = getattr(args, "backup_file", "") or ""

    if apply_mod and partial_mod:
        print("HATA: --apply ve --apply-partial aynı anda kullanılamaz.")
        return 1
    if test_tx_mod and (apply_mod or partial_mod):
        print("HATA: --test-partial-tx yalnız tek başına çalıştırılabilir.")
        return 1

    _baslik("NexGen Import Apply — P5B.2")
    print(f"Excel : {excel_path}")
    print(f"DB    : {db_path}")
    print(f"Mod   : {('TEST-TX (geçici DB)' if test_tx_mod else ('GERÇEK IMPORT (--apply)' if apply_mod else ('KISMI APPLY (--apply-partial)' if partial_mod else 'DRY-RUN (simülasyon)')))}")

    # ── 1. Excel parse ──────────────────────────────────────────────────
    print("\n[1/5] Excel parse ediliyor...")
    if not os.path.isfile(excel_path):
        print(f"HATA: Excel bulunamadı: {excel_path}")
        return 1

    ham = parse_excel(excel_path)
    pkg = normalize_excel(ham)
    excel_sha = ham.dosya_sha256

    print(f"  Excel SHA  : {excel_sha[:16]}...")
    print(f"  Formül     : {len(pkg.formuller)}")
    print(f"  Kullanım   : {len(pkg.kullanimlar)}")
    print(f"  Uyarı      : {len(pkg.uyarilar)}")

    # ── 2. Diff (bloker kontrolü) ───────────────────────────────────────
    print("\n[2/5] Diff çalıştırılıyor (read-only)...")
    diff = diff_excel_vs_db(pkg, db_path=db_path)
    bloker = diff.bloker_sayisi()
    biz    = diff.biz_rule_sayisi()
    uyari  = diff.uyari_sayisi()

    print(f"  BLOCKER            : {bloker}")
    print(f"  BUSINESS_RULE_REV  : {biz}")
    print(f"  UYARI              : {uyari}")
    print(f"  Import uygunluk    : {diff.import_uygunluk}")

    # ── 3. Preflight ────────────────────────────────────────────────────
    print("\n[3/5] Preflight kontrolleri...")
    db_sha_once = _sha256(db_path)
    pf = preflight_kontrol(
        pkg,
        db_path=db_path,
        excel_sha=excel_sha,
        beklenen_db_sha=db_sha_once,
        diff_bloker_sayisi=bloker,
        diff_biz_rule_sayisi=biz,
        is_apply=apply_mod,
    )

    for h in pf.hatalar:
        print(f"  ❌ {h}")
    for u in pf.uyarilar:
        print(f"  ⚠  {u}")
    if pf.gecti:
        print("  ✅ Tüm preflight kontrolleri geçti")
    else:
        print(f"\n  PREFLIGHT BAŞARISIZ — {len(pf.hatalar)} hata")
        if not force:
            print("  Import durduruluyor. --force ile zorlamayı deneyin (tavsiye edilmez).")
            return 2

    # ── 4. Simülasyon ───────────────────────────────────────────────────
    print("\n[4/5] Simülasyon (işlem planı)...")
    sim = simulate_import(pkg, db_path=db_path)

    print(f"  Simülasyon özeti:")
    for aksiyon, adet in sorted(sim.ozet.items()):
        print(f"    {aksiyon:30s}: {adet}")

    toplam_islem = sum(sim.ozet.values())
    print(f"\n  Toplam planlanan işlem: {toplam_islem}")

    # Mapping tablosu
    print(f"\n  Formül Mapping Tablosu (P4F.2F):")
    print(f"  {'Excel Formül':<22} {'Aile':<8} {'UT':<12} {'DB ID':<7} {'DB Ad':<15} {'Kaynak':<12} {'Sonuç'}")
    cnt_match = cnt_insert = cnt_bloker = 0
    for m in sim.mapping_tablosu:
        marker = "✅" if m.sonuc == "MATCH" else ("➕" if m.sonuc == "INSERT_NEW" else "🚫")
        print(
            f"  {marker} {m.excel_formul_ad:<20} {m.excel_aile:<8} {m.excel_uretim_tipi:<12} "
            f"{str(m.db_formul_id or ''):<7} {m.db_ad:<15} {m.kaynak:<12} {m.sonuc}"
        )
        if m.sonuc == "MATCH":
            cnt_match += 1
        elif m.sonuc == "INSERT_NEW":
            cnt_insert += 1
        else:
            cnt_bloker += 1
    print(f"\n  MATCH={cnt_match} INSERT_NEW={cnt_insert} BLOCKER={cnt_bloker}")

    # Batch raporu
    print(f"\n  Aktif Batch Kontrolü (durumlar={AKTIF_BATCH_DURUMLARI}):")
    etkilenen = [b for b in sim.batch_raporu if b.etkileniyor_mu]
    ilişkisiz = [b for b in sim.batch_raporu if not b.etkileniyor_mu]
    print(f"  Toplam aktif batch: {len(sim.batch_raporu)}")
    print(f"  Etkilenen  : {len(etkilenen)}")
    print(f"  İlişkisiz  : {len(ilişkisiz)}")
    if sim.batch_raporu:
        print(f"\n  {'ID':<5} {'Durum':<10} {'Plan':<6} {'UV':<7} {'Formül':<10} {'RV':<7} {'Boyut':<8} {'Op':<22} {'Etkileniyor'}")
        for b in sim.batch_raporu:
            print(
                f"  {b.batch_id:<5} {b.durum:<10} {str(b.plan_id or ''):<6} "
                f"{str(b.uv_id or ''):<7} {b.formul_kod:<10} {b.rv_renk:<7} "
                f"{b.boyut:<8} {b.planlanan_op:<22} {'EVET ⚠' if b.etkileniyor_mu else 'HAYIR'}"
            )

    # P5B.1 — Güvenli / Bloke ayrımı
    guvenli_yaz = {
        k: v for k, v in sim.ozet.items()
        if k.endswith("_GUVENLI")
    }
    bloke_cnt = sim.ozet.get("BLOCKED", 0)
    rf_aday = sim.ozet.get("NEW_RF_CANDIDATE", 0)
    blocked_dep = sim.ozet.get("BLOCKED_DEPENDENCY", 0)
    guvenli_plan = sim.ozet.get("INSERT_PLANLAMA_GUVENLI", sim.ozet.get("INSERT_PLANLAMA", 0))

    print(f"\n  P5B.1 Kısmi Import Planı:")
    print(f"    Güvenli yazma (filtreli): {sim.guvenli_yazma_sayisi}")
    for k, v in sorted(guvenli_yaz.items()):
        print(f"      {k}: {v}")
    print(f"    NEW_RF_CANDIDATE        : {rf_aday}")
    print(f"    BLOCKED (import dışı)   : {bloke_cnt}")
    print(f"    BLOCKED_DEPENDENCY      : {blocked_dep}")
    print(f"    INSERT_PLANLAMA güvenli  : {guvenli_plan}")
    print(f"    REVISION_SNAPSHOT       : {sim.ozet.get('REVISION_SNAPSHOT_REQUIRED', 0)}")
    print(f"    CHANGED_RECIPE          : {sim.ozet.get('CHANGED_RECIPE', 0)}")
    print(f"    RF_CONFLICT             : {sim.ozet.get('RF_CONFLICT', 0)}")
    print(f"    KISMI_IMPORT_HAZIR      : {'EVET' if sim.kismi_import_hazir else 'HAYIR'}")

    # P5B.4 — RV dependency / uygulanabilir sayaçları
    plan_aday = sim.ozet.get("INSERT_PLANLAMA_ADAY", guvenli_plan)
    plan_uyg = sim.ozet.get("INSERT_PLANLAMA_UYGULANABILIR", guvenli_plan)
    rv_unres = sim.ozet.get("PLANLAMA_RV_UNRESOLVED", 0)
    print(f"\n  P5B.4 Planlama RV Dependency:")
    print(f"    Planlama aday (toplam)     : {plan_aday}")
    print(f"    Planlama uygulanabilir     : {plan_uyg}")
    print(f"    PLANLAMA_RV_UNRESOLVED     : {rv_unres}")
    print(f"    Güvenli aday toplam        : {sim.guvenli_aday_sayisi}")
    print(f"    Uygulanabilir toplam (token): {sim.uygulanabilir_yazma_sayisi}")

    # RF aday özeti (Model 1)
    if rf_aday:
        print(f"\n  RF Durum (Model 1 — boya RF katmanında):")
        print(f"    NEW_RF_CANDIDATE : {rf_aday} (RF oluşturma AR-GE sürecinde)")

    # Bloker özeti
    if sim.blokerler:
        print(f"\n  BLOKERLER ({len(sim.blokerler)}):")
        for bk in sim.blokerler[:10]:
            print(f"    🚫 {bk}")

    print(f"\n  IMPORT_APPLY_HAZIR: {'HAYIR (bloker var)' if sim.blokerler else 'EVET'}")

    # P5B.3 — dinamik kısmi apply planı (git + motor + op dağılımı)
    partial_plan = build_partial_import_plan(sim, excel_sha, db_sha_once)
    print(f"\n  P5B.3 Kısmi Apply Hazırlığı:")
    print(f"    SCHEMA_IDENTITY_EKSIK : {'EVET — NO-GO' if partial_plan.schema_identity_eksik else 'HAYIR — OK'}")
    print(f"    Plan fingerprint      : {partial_plan.plan_fingerprint[:16]}...")
    print(f"    Güvenli op sayısı     : {partial_plan.guvenli_op_sayisi}")
    print(f"    Git commit SHA        : {partial_plan.git_sha[:12] if partial_plan.git_sha else 'ALINAMADI'}...")
    print(f"    Motor FP              : {partial_plan.motor_code_fingerprint[:12]}...")
    print(f"    Op dağılımı           : {partial_plan.safe_operation_distribution}")
    print(f"    Token ops= kaynağı    : uygulanabilir ({partial_plan.guvenli_op_sayisi})")
    print(f"    Confirm token         : {partial_plan.confirm_token}")
    if partial_plan.schema_identity_eksik:
        print(f"    *** GERÇEK KISMİ IMPORT NO-GO: renk/boyut kolonu eksik ***")
    elif partial_plan.confirm_token == "GIT_COMMIT_ALINAMADI":
        print(f"    *** GERÇEK KISMİ IMPORT NO-GO: git commit alınamadı ***")
    else:
        print(f"    (Kullanım: --apply-partial --confirm {partial_plan.confirm_token})")
        if os.path.abspath(db_path) == REAL_DB_PATH:
            print(
                "    Gerçek DB: --apply-partial --allow-real-db-partial "
                f"--backup-file <yedek> --confirm {partial_plan.confirm_token}"
            )

    # Çıktı dizini
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sha_kisa = excel_sha[:12]
    out_dir = os.path.join(OUTPUT_ROOT, f"{ts}_P4F_{sha_kisa}")
    os.makedirs(out_dir, exist_ok=True)

    # Simülasyon raporu kaydet
    sim_rapor = {
        "zaman": datetime.now().isoformat(sep=" "),
        "excel_sha": excel_sha,
        "db_sha_once": db_sha_once,
        "mod": "apply" if apply_mod else "dry_run",
        "preflight_gecti": pf.gecti,
        "preflight_hatalar": pf.hatalar,
        "preflight_uyarilar": pf.uyarilar,
        "diff_bloker": bloker,
        "diff_biz_rule": biz,
        "diff_uyari": uyari,
        "simulasyon_ozet": sim.ozet,
        "simulasyon_toplam_islem": toplam_islem,
        "import_apply_hazir": not bool(sim.blokerler),
        "kismi_import_hazir": sim.kismi_import_hazir,
        "guvenli_yazma_sayisi": sim.guvenli_yazma_sayisi,
        "p5a_guvenli_yazma": guvenli_yaz,
        "p5a_blocked": bloke_cnt,
        "p5b_blocked_dependency": blocked_dep,
        "p5b3_schema_raporu": sim.schema_kolon_raporu,
        "p5b3_schema_identity_eksik": sim.schema_identity_eksik,
        "p5b3_git_commit": sim.git_commit,
        "p5b3_motor_code_fingerprint": sim.motor_code_fingerprint,
        "p5b_partial_plan": {
            "plan_fingerprint": partial_plan.plan_fingerprint,
            "confirm_token": partial_plan.confirm_token,
            "guvenli_op_sayisi": partial_plan.guvenli_op_sayisi,
            "git_sha": partial_plan.git_sha,
            "motor_code_fingerprint": partial_plan.motor_code_fingerprint,
            "safe_operation_distribution": partial_plan.safe_operation_distribution,
            "schema_identity_eksik": partial_plan.schema_identity_eksik,
            "operasyonlar": partial_plan.operasyonlar,
        },
        "bagimlilik_grafigi": sim.bagimlilik_grafigi,
        "blokerler": sim.blokerler,
        "aktif_batch_durumlari": list(AKTIF_BATCH_DURUMLARI),
        "mapping_tablosu": [
            {
                "excel_formul_ad": m.excel_formul_ad,
                "excel_aile": m.excel_aile,
                "excel_uretim_tipi": m.excel_uretim_tipi,
                "normalize_key": m.normalize_key,
                "db_formul_id": m.db_formul_id,
                "db_kod": m.db_kod,
                "db_ad": m.db_ad,
                "kaynak": m.kaynak,
                "guven": m.guven,
                "sonuc": m.sonuc,
            }
            for m in sim.mapping_tablosu
        ],
        "batch_raporu": [
            {
                "batch_id": b.batch_id,
                "durum": b.durum,
                "plan_id": b.plan_id,
                "uv_id": b.uv_id,
                "formul_id": b.formul_id,
                "formul_kod": b.formul_kod,
                "formul_ad": b.formul_ad,
                "rv_renk": b.rv_renk,
                "boyut": b.boyut,
                "planlanan_op": b.planlanan_op,
                "etkileniyor_mu": b.etkileniyor_mu,
                "bloker_nedeni": b.bloker_nedeni,
            }
            for b in sim.batch_raporu
        ],
        "simulasyon_islemler": [
            {
                "aksiyon": k.aksiyon,
                "tablo": k.tablo,
                "identity": k.identity,
                "mesaj": k.mesaj,
                "bloker_mi": k.bloker_mi,
                "bloker_nedeni": k.bloker_nedeni,
                "kaynak_hucre": k.kaynak_hucre,
            }
            for k in sim.islemler
        ],
    }
    _yaz_json(os.path.join(out_dir, "p4f_simulasyon.json"), sim_rapor)

    # İnsan okunabilir özet
    _yaz_md(out_dir, sim_rapor, sim)

    # ── 5. Test / Apply modları ───────────────────────────────────────
    if test_tx_mod:
        print("\n[5/5] P5B.3 Transaction testi (geçici DB kopyası)...")
        print(f"  Kaynak DB: {db_path}")
        print(f"  Kaynak SHA: {db_sha_once[:16]}...")
        tx = test_partial_transaction(pkg, db_path, excel_sha, BACKUP_ROOT)
        _yaz_json(os.path.join(out_dir, "p5b2_tx_test.json"), tx)
        print(f"\n  Apply #1 başarılı : {tx.get('apply1_basarili')}")
        print(f"  Apply #1 özet     : {tx.get('apply1_ozet')}")
        print(f"  Idempotent OK     : {tx.get('idempotent_ok')}")
        print(f"  Apply #2 özet     : {tx.get('apply2_ozet')}")
        print(f"  Rollback OK       : {tx.get('rollback_ok')}")
        print(f"  Tüm testler       : {tx.get('tum_testler_gecildi')}")
        print(f"  Temp DB (apply)   : {os.path.basename(tx.get('temp_db_apply', ''))}")
        real_sha = _sha256(REAL_DB_PATH)
        print(f"\n  Gerçek DB SHA     : {real_sha[:16]}... (değişmemeli)")
        print(f"  Kaynak == Gerçek  : {'EVET' if os.path.abspath(db_path) == REAL_DB_PATH and real_sha == db_sha_once else 'N/A (farklı db)'}")
        if os.path.abspath(db_path) == REAL_DB_PATH:
            print(f"  Gerçek DB korundu : {'EVET' if real_sha == db_sha_once else 'HAYIR — HATA!'}")
        return 0 if tx.get("tum_testler_gecildi") else 7

    if partial_mod:
        val_code, val_msg = _dogrula_gercek_db_partial(
            db_path=db_path,
            confirm=confirm,
            partial_plan=partial_plan,
            sim=sim,
            allow_real=allow_real,
            backup_file=backup_file,
            db_sha_once=db_sha_once,
        )
        if val_code != 0:
            print(f"\n[5/5] KISMI APPLY REDDEDİLDİ — {val_msg}")
            if val_code == EXIT_NO_BYPASS:
                print(f"  Dinamik token: {partial_plan.confirm_token}")
                print("  Geçici test: --test-partial-tx")
            elif val_code == EXIT_TOKEN:
                print(f"  Beklenen: {partial_plan.confirm_token}")
                print(f"  Verilen : {confirm or '(boş)'}")
            elif val_code == EXIT_BACKUP_SHA:
                print(f"  DB SHA    : {db_sha_once[:16]}...")
                if backup_file:
                    print(f"  Backup SHA: {_sha256(os.path.abspath(backup_file))[:16]}...")
            print("  Transaction başlamadı. DB yazılmadı.")
            return val_code
        print(f"\n[5/5] --apply-partial başlıyor (hedef: {db_path})...")
        if os.path.abspath(db_path) == REAL_DB_PATH:
            print(f"  P5C-3A: gerçek DB onaylı bypass aktif")
            print(f"  Backup    : {os.path.abspath(backup_file)}")
        sonuc_p = execute_partial_import(
            pkg, db_path, confirm, excel_sha=excel_sha, sim=sim,
            yedek_dizin=BACKUP_ROOT,
        )
        print(f"  Başarılı    : {sonuc_p.basarili}")
        print(f"  Plan FP     : {sonuc_p.plan_fingerprint[:16]}...")
        print(f"  Özet        : {sonuc_p.ozet}")
        if sonuc_p.hatalar:
            print(f"  HATALAR     : {sonuc_p.hatalar}")
            return 4
        db_sha_sonra = _sha256(db_path)
        print(f"\n  DB SHA önce : {db_sha_once[:16]}...")
        print(f"  DB SHA sonra: {db_sha_sonra[:16]}...")
        return 0

    if not apply_mod:
        print("\n[5/5] DRY-RUN tamamlandı. Gerçek import için --apply kullanın.")
        print(f"\n  Rapor : {out_dir}")
        db_sha_sonra = _sha256(db_path)
        print(f"\n  DB SHA önce : {db_sha_once[:16]}...")
        print(f"  DB SHA sonra: {db_sha_sonra[:16]}...")
        print(f"  Hash değişti: {'EVET — HATA!' if db_sha_once != db_sha_sonra else 'HAYIR — OK'}")
        return 0

    # -- apply (tam import) --
    if sim.blokerler:
        print(f"\n  TAM --apply REDDEDİLDİ — {len(sim.blokerler)} bloker var.")
        print("  Kısmi import için --apply-partial --confirm TOKEN kullanın.")
        return 3

    print("\n[5/5] GERÇEK IMPORT BAŞLIYOR...")
    if not pf.gecti and not force:
        print("  Preflight geçmedi, import durduruldu.")
        return 3

    # Yedek
    yedek_yolu = db_yedek_al(db_path, BACKUP_ROOT)
    print(f"  Yedek alındı: {os.path.basename(yedek_yolu)}")

    sonuc = execute_import(
        pkg,
        db_path=db_path,
        yedek_dizin=BACKUP_ROOT,
        onayli_kullanici_id=None,
    )

    print(f"\n  Başarılı    : {sonuc.basarili}")
    print(f"  Batch ID    : {sonuc.batch_id}")
    print(f"  SHA önce    : {sonuc.sha_once[:16]}...")
    print(f"  SHA sonra   : {sonuc.sha_sonra[:16]}...")
    print(f"  Yedek       : {os.path.basename(sonuc.yedek_yolu)}")
    print(f"  Süre        : {sonuc.elapsed_ms:.0f} ms")
    print(f"  Özet        : {sonuc.ozet}")
    if sonuc.hatalar:
        print(f"  HATALAR     : {sonuc.hatalar}")
        return 4

    return 0


def _yaz_md(out_dir: str, sim_rapor: dict, sim) -> None:
    """İnsan okunabilir Markdown rapor (P4F.2B)."""
    satirlar = [
        "# NexGen Import Apply — Simülasyon Raporu (P5A)",
        "",
        f"**Zaman:** {sim_rapor['zaman']}",
        f"**Excel SHA:** `{sim_rapor['excel_sha'][:20]}...`",
        f"**DB SHA önce:** `{sim_rapor['db_sha_once'][:20]}...`",
        f"**Mod:** `{sim_rapor['mod']}`",
        f"**IMPORT_APPLY_HAZIR:** `{sim_rapor.get('import_apply_hazir', '?')}`",
        "",
        "## Preflight",
        f"- Geçti: **{sim_rapor['preflight_gecti']}**",
    ]
    for h in sim_rapor['preflight_hatalar']:
        satirlar.append(f"- ❌ {h}")
    for u in sim_rapor['preflight_uyarilar']:
        satirlar.append(f"- ⚠  {u}")

    satirlar += [
        "",
        "## Diff Özeti",
        f"- BLOCKER: **{sim_rapor['diff_bloker']}**",
        f"- BUSINESS_RULE_REVIEW: **{sim_rapor['diff_biz_rule']}**",
        f"- UYARI: **{sim_rapor['diff_uyari']}**",
        "",
        "## Formül Mapping Tablosu",
        "",
        "| Excel Formül | Aile | UT | DB ID | DB Ad | Kaynak | Sonuç |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in sim_rapor.get("mapping_tablosu", []):
        satirlar.append(
            f"| {m['excel_formul_ad']} | {m['excel_aile']} | {m['excel_uretim_tipi']} "
            f"| {m['db_formul_id'] or '-'} | {m['db_ad'] or '-'} "
            f"| {m['kaynak']} | {m['sonuc']} |"
        )

    satirlar += [
        "",
        "## Aktif Batch Raporu",
        "",
        f"Aktif durumlar: `{sim_rapor.get('aktif_batch_durumlari', [])}`",
        "",
        "| batch_id | durum | plan_id | uv_id | formul_kod | rv | boyut | Op | Etkileniyor |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for b in sim_rapor.get("batch_raporu", []):
        satirlar.append(
            f"| {b['batch_id']} | {b['durum']} | {b['plan_id'] or '-'} "
            f"| {b['uv_id'] or '-'} | {b['formul_kod']} | {b['rv_renk']} "
            f"| {b['boyut']} | {b['planlanan_op']} "
            f"| {'**EVET**' if b['etkileniyor_mu'] else 'Hayır'} |"
        )

    satirlar += [
        "",
        "## Simülasyon İşlem Planı",
        "",
        "| Aksiyon | Adet |",
        "|---------|------|",
    ]
    for aksiyon, adet in sorted(sim_rapor['simulasyon_ozet'].items()):
        satirlar.append(f"| {aksiyon} | {adet} |")

    satirlar += [
        "",
        f"**Toplam planlanan işlem:** {sim_rapor['simulasyon_toplam_islem']}",
        "",
    ]
    if sim_rapor.get("blokerler"):
        satirlar += ["## Blokerler", ""]
        for bk in sim_rapor["blokerler"][:20]:
            satirlar.append(f"- 🚫 {bk}")
        satirlar.append("")

    satirlar += ["## İşlem Detayları (ilk 50)", ""]
    for i, islem in enumerate(sim.islemler[:50]):
        marker = "🚫" if islem.bloker_mi else "•"
        satirlar.append(f"{i+1}. {marker} `{islem.aksiyon}` → {islem.tablo}: {islem.mesaj}")
    if len(sim.islemler) > 50:
        satirlar.append(f"\n_...ve {len(sim.islemler)-50} daha. Tam liste JSON dosyasında._")

    md_yolu = os.path.join(out_dir, "p4f_simulasyon_rapor.md")
    with open(md_yolu, "w", encoding="utf-8") as f:
        f.write("\n".join(satirlar))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="NexGen Excel → DB import (P4F)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--excel",    default=DEFAULT_EXCEL, help="Excel dosyası yolu")
    ap.add_argument("--db",       default=DB_PATH,       help="DB dosyası yolu")
    ap.add_argument("--dry-run",  action="store_true",   help="Simülasyon modu (varsayılan)")
    ap.add_argument("--apply",         action="store_true", help="Tam gerçek import")
    ap.add_argument("--apply-partial", action="store_true", help="Kısmi güvenli import")
    ap.add_argument("--test-partial-tx", action="store_true",
                    help="Geçici DB kopyasında transaction/idempotency/rollback testi")
    ap.add_argument("--confirm", default="", help="Dinamik kısmi import onay tokeni")
    ap.add_argument("--force",         action="store_true", help="Preflight uyarılarını geç")
    ap.add_argument(
        "--allow-real-db-partial",
        action="store_true",
        help="P5C-3A: Gerçek DB üzerinde kısmi apply için açık onay bayrağı",
    )
    ap.add_argument(
        "--backup-file",
        default="",
        help="P5C-3A: Gerçek DB partial apply öncesi doğrulanacak yedek dosyası",
    )

    args = ap.parse_args()

    if args.allow_real_db_partial and not args.apply_partial:
        print("HATA: --allow-real-db-partial yalnız --apply-partial ile kullanılabilir.")
        return EXIT_ARG

    if args.apply and args.dry_run:
        print("HATA: --apply ve --dry-run aynı anda kullanılamaz.")
        return 1
    if args.apply_partial and args.dry_run:
        print("HATA: --apply-partial ve --dry-run aynı anda kullanılamaz.")
        return 1
    if args.test_partial_tx and args.dry_run:
        print("HATA: --test-partial-tx ve --dry-run aynı anda kullanılamaz.")
        return 1

    # Varsayılan: dry-run
    if not args.apply and not args.apply_partial and not args.test_partial_tx:
        args.dry_run = True
        args.apply   = False

    return _calistir(args)


if __name__ == "__main__":
    sys.exit(main())
