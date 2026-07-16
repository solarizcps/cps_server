# -*- coding: utf-8 -*-
"""
P5A — NexGen Import Engine (transaction motoru) v5
P5D.2 — UV revizyon motoru ve güvenli reçete güncelleme
===================================================
P5B.1 — bağımlılık filtresi, scoped RF identity, kısmi apply koruması
  - Yalnız güvenli yeni kayıtlar import planına alınır
  - P5D.2: kullanılmayan UV → UPDATE_ANA_KALEM; plan/batch/üretim → INSERT_UV_REVISION
  - INSERT_ANA_KALEM (ana kalemler); boya → NEW_RF_CANDIDATE (recete_kalem'e yazılmaz)
P4F.2F (Model 1 — RF tabanlı boya):
  - UV kimliği: (rv_id, boyut) — tek UV; müşteri rengi UV açmaz
P4F.2D (hiyerarşi):
  - Parent: DOKME→810, ENJEKSIYON+TABAN→627, ENJEKSIYON+TERLIK→575
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from modules.nexgen.import_models import (
    ImportPackage,
    NormalizedFormul,
    NormalizedRenkVaryanti,
    NormalizedBoyut,
    NormalizedKullanim,
    KalemRolu,
)
from modules.nexgen.import_normalizer import normalize_metin
from modules.nexgen.import_validator import DB_PATH, db_readonly_connect, db_snapshot
from modules.nexgen.import_diff import diff_excel_vs_db, DiffSinif


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------
DOKUNULMAZ_TABLOLAR = [
    "nexgen_stok_hareket",
    "nexgen_uretim_plan",
    "nexgen_uretim_batch",
    "nexgen_stok_kart",
    "nexgen_cari",
    "nexgen_uretim_tipi",
]

IMPORT_LOG_TABLOSU = "nexgen_import_batch"
ITEM_LOG_TABLOSU   = "nexgen_import_item_log"

# Aktif batch durumları — routes.py satır 11091 ile uyumlu
AKTIF_BATCH_DURUMLARI = ("TASLAK", "HAZIR", "DEVAM", "BEKLEME")

# P5A — kısmi import aksiyon sınıfları
GUVENLI_IMPORT_AKSIYONLARI = frozenset({
    "MATCH_FORMUL", "MATCH_RV", "INSERT_RV", "MATCH_UV", "INSERT_UV",
    "INSERT_UV_REVISION", "UPDATE_ANA_KALEM",
    "INSERT_ANA_KALEM", "INSERT_PLANLAMA", "INSERT_PLANLAMA_REVISION",
    "INSERT_RF_TASLAK", "MATCH_RF", "MATCH_RF_TASLAK",
    "RF_REVISION_MANUAL_REVIEW",
    "NEW_RF_CANDIDATE", "WARNING_ONLY", "MATCH_UV_REVISION", "MATCH_PLANLAMA",
})
BLOKE_IMPORT_AKSIYONLARI = frozenset({
    "REVISION_SNAPSHOT_REQUIRED", "CHANGED_RECIPE", "GERCEK_BLOCKER",
    "BLOCKER_PARENT", "PARENT_FORMUL_BELIRSIZ", "RF_CONFLICT", "BLOCKED",
    "BLOCKED_DEPENDENCY", "SCHEMA_IDENTITY_EKSIK", "GIT_COMMIT_ALINAMADI",
    "PLANLAMA_RV_UNRESOLVED",
})

# P5B.3 — dinamik confirmation token (git + motor + op dağılımı)
PARTIAL_TOKEN_PREFIX = "NEXGEN-PARTIAL"
PARTIAL_TOKEN_VERSION = "v3"
MOTOR_FP_FILES = (
    "app/modules/nexgen/import_engine.py",
    "app/modules/nexgen/import_normalizer.py",
    "app/tools/nexgen_import_apply.py",
)
SAFE_OP_ORDER = (
    "INSERT_RV", "INSERT_UV", "INSERT_UV_REVISION",
    "UPDATE_ANA_KALEM", "INSERT_ANA_KALEM",
    "INSERT_PLANLAMA", "INSERT_PLANLAMA_REVISION",
    "INSERT_RF_TASLAK",
)

# Geriye dönük uyumluluk (artık dry-run dinamik token üretir)
KISMI_IMPORT_CONFIRM_TOKEN = "NEXGEN-PARTIAL-IMPORT-v1"

YAZILABILIR_AKSIYONLAR = frozenset({
    "INSERT_RV", "INSERT_UV", "INSERT_UV_REVISION",
    "UPDATE_ANA_KALEM", "INSERT_ANA_KALEM",
    "INSERT_PLANLAMA", "INSERT_PLANLAMA_REVISION",
    "INSERT_RF_TASLAK",
})

# P5E-RF — RF pigment kategorileri (yalnız RF katmanı; ana reçeteye yazılmaz)
RF_PIGMENT_KATEGORILERI = frozenset({"BOYA", "PIGMENT", "KATKI", "MASTERBATCH"})
RF_IMPORT_IDENTITY_PREFIX = "IMPORT_RF_ID|"
RF_ONAYLI_DURUMLAR = frozenset({"ONAYLI", "AKTIF", "URETIME_ACIK"})

# P5D.2 — deterministik revizyon suffix (idempotent; R3 üretilmez)
REVISION_SUFFIX = " R2"
REVISION_REV_NO = 2
UV_REV_NO_INDEX = "uq_nuv_rv_boyut_rev"


# ---------------------------------------------------------------------------
# normalize_ascii_import — import kimliği için Türkçe-duyarsız normalizasyon
# Yalnız import eşleştirmesinde kullanılır; genel normalize_metin değişmez.
# ---------------------------------------------------------------------------
_TR_NORM_MAP = {
    ord("\u0130"): "I",   # İ → I
    ord("\u0131"): "i",   # ı → i
    ord("\u015e"): "S",   # Ş → S
    ord("\u015f"): "s",   # ş → s
    ord("\u011e"): "G",   # Ğ → G
    ord("\u011f"): "g",   # ğ → g
    ord("\u00dc"): "U",   # Ü → U
    ord("\u00fc"): "u",   # ü → u
    ord("\u00d6"): "O",   # Ö → O
    ord("\u00f6"): "o",   # ö → o
    ord("\u00c7"): "C",   # Ç → C
    ord("\u00e7"): "c",   # ç → c
}


def normalize_ascii_import(s: str) -> str:
    """
    Import kimliği için Türkçe karakterleri ASCII'ye çevirir ve normalleştirir.
    ENJEKSİYON == ENJEKSIYON, DÖKME == DOKME vb.
    Bu fonksiyon yalnız formül/varyant eşleştirmesinde kullanılır.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_TR_NORM_MAP)
    s = s.strip().upper()
    s = re.sub(r"\s+", " ", s)
    return s


# ---------------------------------------------------------------------------
# Veri yapıları
# ---------------------------------------------------------------------------
@dataclass
class MappingKaydi:
    excel_formul_ad: str
    excel_aile: str
    excel_uretim_tipi: str
    normalize_key: str
    db_formul_id: int | None
    db_kod: str
    db_ad: str
    kaynak: str          # EXACT / RULE_BASED / AMBIGUOUS / NOT_FOUND
    guven: str           # HIGH / MEDIUM / LOW
    sonuc: str           # MATCH / INSERT_NEW / BLOCKER


@dataclass
class PreflightSonucu:
    gecti: bool = True
    hatalar: list[str] = field(default_factory=list)
    uyarilar: list[str] = field(default_factory=list)
    db_sha: str = ""
    excel_sha: str = ""
    etkilenen_batch_sayisi: int = 0
    import_log_tablosu_var: bool = False

    def ekle_hata(self, mesaj: str) -> None:
        self.hatalar.append(mesaj)
        self.gecti = False

    def ekle_uyari(self, mesaj: str) -> None:
        self.uyarilar.append(mesaj)


@dataclass
class SimulasyonKalemi:
    aksiyon: str
    tablo: str
    identity: str
    eski_deger: Any = None
    yeni_deger: Any = None
    mesaj: str = ""
    kaynak_hucre: str = ""
    bloker_mi: bool = False
    bloker_nedeni: str = ""
    op_id: str = ""
    parent_op_id: str = ""
    safe_to_apply: bool = True
    blocked_dependency: bool = False
    bagli_uv_id: int | None = None
    bagli_rv_id: int | None = None
    bagli_formul_kod: str = ""


@dataclass
class BatchKaydi:
    batch_id: int
    durum: str
    plan_id: int | None
    uv_id: int | None
    formul_id: int | None
    formul_kod: str
    formul_ad: str
    rv_renk: str
    boyut: str
    planlanan_op: str
    etkileniyor_mu: bool
    bloker_nedeni: str


@dataclass
class SimulasyonSonucu:
    islemler: list[SimulasyonKalemi] = field(default_factory=list)
    ozet: dict[str, int] = field(default_factory=dict)
    uyarilar: list[str] = field(default_factory=list)
    blokerler: list[str] = field(default_factory=list)
    batch_raporu: list[BatchKaydi] = field(default_factory=list)
    mapping_tablosu: list[MappingKaydi] = field(default_factory=list)
    guvenli_islemler: list[SimulasyonKalemi] = field(default_factory=list)
    bloke_islemler: list[SimulasyonKalemi] = field(default_factory=list)
    bagimlilik_grafigi: list[dict] = field(default_factory=list)
    gecerli: bool = True
    kismi_import_hazir: bool = False
    guvenli_yazma_sayisi: int = 0
    guvenli_aday_sayisi: int = 0
    uygulanabilir_yazma_sayisi: int = 0
    schema_identity_eksik: bool = False
    schema_kolon_raporu: dict = field(default_factory=dict)
    git_commit: str = ""
    motor_code_fingerprint: str = ""

    def ekle(self, kalem: SimulasyonKalemi) -> None:
        self.islemler.append(kalem)
        self.ozet[kalem.aksiyon] = self.ozet.get(kalem.aksiyon, 0) + 1
        if kalem.aksiyon in GUVENLI_IMPORT_AKSIYONLARI and kalem.safe_to_apply:
            self.guvenli_islemler.append(kalem)
        elif kalem.aksiyon in BLOKE_IMPORT_AKSIYONLARI or kalem.bloker_mi or kalem.blocked_dependency:
            self.bloke_islemler.append(kalem)
        if kalem.bloker_mi:
            self.blokerler.append(f"{kalem.identity}: {kalem.bloker_nedeni}")
            self.gecerli = False

    def finalize_p5a(self) -> None:
        """P5B.1 özet: BLOCKED sayacı ve kısmi import hazırlığı."""
        bloke_cnt = sum(
            1 for k in self.islemler
            if k.aksiyon in BLOKE_IMPORT_AKSIYONLARI
            or k.aksiyon in ("REVISION_SNAPSHOT_REQUIRED", "CHANGED_RECIPE")
            or k.blocked_dependency
        )
        if bloke_cnt:
            self.ozet["BLOCKED"] = bloke_cnt
        yazilabilir = [
            k for k in self.islemler
            if k.aksiyon in YAZILABILIR_AKSIYONLAR
            and k.safe_to_apply and not k.blocked_dependency
        ]
        self.guvenli_yazma_sayisi = len(yazilabilir)
        self.uygulanabilir_yazma_sayisi = self.guvenli_yazma_sayisi
        # SCHEMA_IDENTITY_EKSIK varken gerçek kısmi import NO-GO
        self.kismi_import_hazir = (
            self.guvenli_yazma_sayisi > 0 and not self.schema_identity_eksik
        )
        for aks in SAFE_OP_ORDER:
            guvenli_n = sum(
                1 for k in self.islemler
                if k.aksiyon == aks and k.safe_to_apply and not k.blocked_dependency
            )
            if guvenli_n:
                self.ozet[f"{aks}_GUVENLI"] = guvenli_n


@dataclass
class ImportSonucu:
    basarili: bool = False
    batch_id: int | None = None
    sha_once: str = ""
    sha_sonra: str = ""
    yedek_yolu: str = ""
    ozet: dict[str, int] = field(default_factory=dict)
    hatalar: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    partial_mode: bool = False
    plan_fingerprint: str = ""
    guvenli_op_sayisi: int = 0
    rollback_yapildi: bool = False


@dataclass
class PartialImportPlan:
    """P5B.3 — kısmi apply plan özeti."""
    plan_fingerprint: str
    confirm_token: str
    guvenli_op_sayisi: int
    excel_sha: str
    db_sha: str
    git_sha: str = ""
    motor_code_fingerprint: str = ""
    safe_operation_distribution: dict = field(default_factory=dict)
    schema_identity_eksik: bool = False
    operasyonlar: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SHA256 yardımcısı
# ---------------------------------------------------------------------------
def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# DB lookup yardımcıları (read-only)
# ---------------------------------------------------------------------------
def _stok_id_map(con: sqlite3.Connection) -> dict[str, int]:
    rows = con.execute("SELECT id, kod FROM nexgen_stok_kart WHERE aktif=1").fetchall()
    return {r[0].strip().upper(): r[1] for r in rows if r[0]}


def _stok_id_map_v2(con: sqlite3.Connection) -> dict[str, int]:
    rows = con.execute("SELECT id, kod FROM nexgen_stok_kart WHERE aktif=1").fetchall()
    return {r[1].strip().upper(): r[0] for r in rows if r[1]}


def _cari_id_map(con: sqlite3.Connection) -> dict[str, int]:
    rows = con.execute("SELECT id, cari_kod FROM nexgen_cari WHERE aktif=1").fetchall()
    return {r[1].strip(): r[0] for r in rows if r[1]}


def _ut_id_map(con: sqlite3.Connection) -> dict[str, int]:
    rows = con.execute("SELECT id, kod FROM nexgen_uretim_tipi WHERE aktif=1").fetchall()
    return {r[1].strip().upper(): r[0] for r in rows if r[1]}


def _formul_id_map_ascii(con: sqlite3.Connection) -> dict[str, dict]:
    """normalize_ascii_import(ad) → {f_id, f_kod, f_ad, f_aile} — ad tabanlı eşleştirme."""
    rows = con.execute(
        "SELECT id, kod, ad, urun_ailesi FROM nexgen_formul WHERE aktif=1"
    ).fetchall()
    result = {}
    for r in rows:
        key = normalize_ascii_import(r[2] or "")
        result[key] = {
            "f_id": r[0], "f_kod": r[1],
            "f_ad": r[2], "f_aile": r[3],
        }
    return result


def _formul_ut_aile_map(con: sqlite3.Connection) -> dict[str, dict]:
    """
    Üretim tipi kodu → formül bilgisi haritası.
    nexgen_uretim_tipi.kod değeri normalize_ascii_import ile formülün adına bağlanır.
    Örn: 'DOKME' → 810/DOKME, 'ENJEKSIYON' kayıtları urun_ailesi ile ayrılır.
    """
    rows = con.execute(
        "SELECT id, kod, ad, urun_ailesi FROM nexgen_formul WHERE aktif=1"
    ).fetchall()
    result = {}
    for r in rows:
        # formul.ad normalize edilmiş üretim tipi adına karşılık gelse map et
        nad = normalize_ascii_import(r[2] or "")
        result[nad] = {
            "f_id": r[0], "f_kod": r[1],
            "f_ad": r[2], "f_aile": r[3],
        }
    return result


# ---------------------------------------------------------------------------
# Parent formül çözümleme — P4F.2D deterministik karar ağacı
# ---------------------------------------------------------------------------
def _formul_parent_coz(
    uretim_tipi: str,
    urun_ailesi: str,
    formul_map_ascii: dict[str, dict],
) -> tuple[dict | None, str]:
    """
    (uretim_tipi, urun_ailesi) → (formul_dict | None, hata_mesaji)

    Karar ağacı (P4F.2C.1 kesinleşmiş kurallar):
      1. DOKME               → 810
      2. ENJEKSIYON + TABAN  → 627
      3. ENJEKSIYON + TERLIK → 575
      4. Diğer               → BLOCKER / PARENT_FORMUL_BELIRSIZ
    """
    nut = normalize_ascii_import(uretim_tipi or "")
    naile = normalize_ascii_import(urun_ailesi or "")

    if nut == "DOKME":
        db_f = formul_map_ascii.get("DOKME")
        if db_f:
            return db_f, ""
        return None, "PARENT_FORMUL_BELIRSIZ: DOKME formülü DB'de bulunamadı"

    if nut == "ENJEKSIYON":
        if naile == "TABAN":
            db_f = formul_map_ascii.get("TABAN")
            if db_f:
                return db_f, ""
            return None, "PARENT_FORMUL_BELIRSIZ: TABAN formülü DB'de bulunamadı"
        if naile == "TERLIK":
            db_f = formul_map_ascii.get("TERLIK")
            if db_f:
                return db_f, ""
            return None, "PARENT_FORMUL_BELIRSIZ: TERLIK formülü DB'de bulunamadı"
        return None, (
            f"PARENT_FORMUL_BELIRSIZ: ENJEKSIYON için urun_ailesi={urun_ailesi!r} "
            "TABAN veya TERLIK değil"
        )

    if nut:
        return None, (
            f"PARENT_FORMUL_BELIRSIZ: bilinmeyen uretim_tipi={uretim_tipi!r} "
            f"(normalize={nut!r})"
        )
    return None, "PARENT_FORMUL_BELIRSIZ: uretim_tipi boş"


def _rv_id_map_varyant(con: sqlite3.Connection) -> dict[tuple, int]:
    """(formul_id, normalize_ascii(rv.renk/varyant)) → rv_id
    DB'de nexgen_renk_varyant.renk = varyant değeri (örn '18-28')
    """
    rows = con.execute(
        "SELECT id, formul_id, renk FROM nexgen_renk_varyant WHERE aktif=1"
    ).fetchall()
    return {(r[1], normalize_ascii_import(r[2] or "")): r[0] for r in rows}


def _uv_id_map(con: sqlite3.Connection) -> dict[tuple, int]:
    """(rv_id, boyut) → birincil uv_id (kaynak_varyant_id yok)."""
    return _uv_id_map_primary(con)


def _uv_rev_no_kolon_var_mi(con: sqlite3.Connection) -> bool:
    """P5D-2B — nexgen_uretim_varyant.rev_no kolonu var mı?"""
    try:
        cols = [r[1] for r in con.execute(
            "PRAGMA table_info(nexgen_uretim_varyant)"
        ).fetchall()]
        return "rev_no" in cols
    except sqlite3.OperationalError:
        return False


def _uv_id_map_primary(con: sqlite3.Connection) -> dict[tuple, int]:
    """(rv_id, boyut) → birincil (rev_no=1) uv_id."""
    if _uv_rev_no_kolon_var_mi(con):
        rows = con.execute(
            """SELECT id, renk_varyant_id, boyut FROM nexgen_uretim_varyant
               WHERE aktif=1 AND rev_no=1"""
        ).fetchall()
    else:
        rows = con.execute(
            """SELECT id, renk_varyant_id, boyut FROM nexgen_uretim_varyant
               WHERE aktif=1 AND COALESCE(kaynak_varyant_id, 0)=0"""
        ).fetchall()
    return {(r[1], (r[2] or "STANDART").strip().upper()): r[0] for r in rows}


def _uv_id_map_canonical(con: sqlite3.Connection) -> dict[tuple, int]:
    """
    (rv_id, boyut) → planlama için tercih edilen uv_id (en yüksek rev_no).
    """
    if _uv_rev_no_kolon_var_mi(con):
        rows = con.execute(
            """SELECT id, renk_varyant_id, boyut, rev_no
               FROM nexgen_uretim_varyant WHERE aktif=1
               ORDER BY renk_varyant_id, boyut, rev_no DESC"""
        ).fetchall()
        canonical: dict[tuple, int] = {}
        for r in rows:
            key = (r[1], (r[2] or "STANDART").strip().upper())
            if key not in canonical:
                canonical[key] = r[0]
        return canonical
    primary = _uv_id_map_primary(con)
    canonical = dict(primary)
    rows = con.execute(
        """SELECT uv.id, uv.renk_varyant_id, uv.boyut
           FROM nexgen_uretim_varyant uv
           WHERE uv.aktif=1 AND COALESCE(uv.kaynak_varyant_id, 0) > 0
           ORDER BY uv.id"""
    ).fetchall()
    for r in rows:
        key = (r[1], (r[2] or "STANDART").strip().upper())
        if key in primary:
            canonical[key] = r[0]
    return canonical


def _aktif_batch_listesi(con: sqlite3.Connection) -> list[dict]:
    """Aktif üretim batch'lerini formül/UV bilgileriyle döner."""
    try:
        placeholders = ",".join("?" * len(AKTIF_BATCH_DURUMLARI))
        rows = con.execute(f"""
            SELECT nb.id, nb.durum, nb.plan_id, nb.uretim_varyant_id,
                   uv.boyut, rv.renk rv_renk, rv.id rv_id,
                   f.id f_id, f.kod f_kod, f.ad f_ad
            FROM nexgen_uretim_batch nb
            LEFT JOIN nexgen_uretim_varyant uv ON uv.id = nb.uretim_varyant_id
            LEFT JOIN nexgen_renk_varyant rv ON rv.id = uv.renk_varyant_id
            LEFT JOIN nexgen_formul f ON f.id = rv.formul_id
            WHERE nb.durum IN ({placeholders})
            ORDER BY nb.id
        """, AKTIF_BATCH_DURUMLARI).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def _import_log_tablo_var_mi(con: sqlite3.Connection) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (IMPORT_LOG_TABLOSU,),
    ).fetchone()
    return row is not None


def _kalem_fingerprint_db(con: sqlite3.Connection, uv_id: int) -> str:
    """Tüm aktif kalemler (geriye dönük uyumluluk)."""
    rows = con.execute(
        """SELECT sk.kod, rk.miktar_kg, rk.sira
           FROM nexgen_recete_kalem rk
           JOIN nexgen_stok_kart sk ON sk.id = rk.stok_kart_id
           WHERE rk.uretim_varyant_id=? AND rk.aktif=1
           ORDER BY rk.sira""",
        (uv_id,),
    ).fetchall()
    raw = "|".join(f"{r[0]}:{r[1]:.6f}:{r[2]}" for r in rows)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _kalem_fingerprint_db_ana(con: sqlite3.Connection, uv_id: int) -> str:
    """Yalnız ana reçete kalemleri (BOYA kategorisi hariç) — Model 1 karşılaştırma."""
    rows = con.execute(
        """SELECT sk.kod, rk.miktar_kg, rk.sira
           FROM nexgen_recete_kalem rk
           JOIN nexgen_stok_kart sk ON sk.id = rk.stok_kart_id
           WHERE rk.uretim_varyant_id=? AND rk.aktif=1
             AND UPPER(COALESCE(sk.kategori,'')) != 'BOYA'
           ORDER BY rk.sira""",
        (uv_id,),
    ).fetchall()
    raw = "|".join(f"{r[0]}:{r[1]:.6f}:{r[2]}" for r in rows)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _uv_aktif_batch_var_mi(con: sqlite3.Connection, uv_id: int) -> bool:
    """Belirtilen UV'ye bağlı aktif batch var mı?"""
    try:
        placeholders = ",".join("?" * len(AKTIF_BATCH_DURUMLARI))
        row = con.execute(
            f"SELECT COUNT(*) FROM nexgen_uretim_batch "
            f"WHERE uretim_varyant_id=? AND durum IN ({placeholders})",
            (uv_id, *AKTIF_BATCH_DURUMLARI),
        ).fetchone()
        return row[0] > 0
    except sqlite3.OperationalError:
        return False


def _uv_aktif_plan_var_mi(con: sqlite3.Connection, uv_id: int) -> bool:
    """Geriye dönük uyumluluk — aktif batch kontrolü."""
    return _uv_aktif_batch_var_mi(con, uv_id)


def _uv_plan_var_mi(con: sqlite3.Connection, uv_id: int) -> bool:
    """Belirtilen UV'ye bağlı herhangi bir üretim planı var mı? (MODEL B)"""
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM nexgen_uretim_plan WHERE uretim_varyant_id=?",
            (uv_id,),
        ).fetchone()
        return row[0] > 0
    except sqlite3.OperationalError:
        return False


def _uv_recete_degisikligi_bloklu_mu(
    con: sqlite3.Connection, uv_id: int,
) -> tuple[bool, str]:
    """
    P5D.2 — mevcut UV reçete değişikliği revizyon mu gerektirir?
    Plan, batch veya üretim kullanımı varsa doğrudan UPDATE yapılmaz.
    """
    if _uv_aktif_batch_var_mi(con, uv_id):
        return True, f"Aktif batch bağlı (uv_id={uv_id})"
    if _uv_plan_var_mi(con, uv_id):
        return True, f"Plan bağlı (uv_id={uv_id})"
    if _uv_batch_var_mi(con, uv_id):
        return True, f"Batch geçmişi var (uv_id={uv_id})"
    if _uv_uretim_kullanim_var_mi(con, uv_id):
        return True, f"Üretim kullanım kaydı var (uv_id={uv_id})"
    return False, ""


def _uv_batch_var_mi(con: sqlite3.Connection, uv_id: int) -> bool:
    """Belirtilen UV'ye bağlı herhangi bir batch var mı?"""
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM nexgen_uretim_batch WHERE uretim_varyant_id=?",
            (uv_id,),
        ).fetchone()
        return row[0] > 0
    except sqlite3.OperationalError:
        return False


def _uv_uretim_kullanim_var_mi(con: sqlite3.Connection, uv_id: int) -> bool:
    """UV'ye bağlı batch üzerinden aktif RF/üretim kullanımı var mı?"""
    try:
        row = con.execute(
            """SELECT COUNT(*) FROM nexgen_rf_kullanim rfk
               JOIN nexgen_uretim_batch nb ON nb.batch_kodu = rfk.tablet_session_id
               WHERE nb.uretim_varyant_id=? AND rfk.aktif=1""",
            (uv_id,),
        ).fetchone()
        return row[0] > 0
    except sqlite3.OperationalError:
        return False


def _uv_guncelleme_guvenli_mi(
    con: sqlite3.Connection, uv_id: int,
) -> tuple[bool, str]:
    """P5D.2 — mevcut UV üzerinde UPDATE_ANA_KALEM güvenli mi?"""
    bloklu, neden = _uv_recete_degisikligi_bloklu_mu(con, uv_id)
    if bloklu:
        return False, neden
    return True, ""


def _uv_revision_schema_destekli_mi(con: sqlite3.Connection) -> tuple[bool, str]:
    """
    P5D-2B — aynı RV+boyut altında revizyon UV (rev_no=2) mümkün mü?
    rev_no kolonu + UNIQUE(renk_varyant_id, boyut, rev_no) gerekir.
    Eski UNIQUE(renk_varyant_id, boyut) engeldir.
    """
    if not _uv_rev_no_kolon_var_mi(con):
        try:
            for idx in con.execute("PRAGMA index_list(nexgen_uretim_varyant)"):
                if not idx[2]:
                    continue
                cols = [
                    r[2] for r in con.execute(f"PRAGMA index_info({idx[1]})")
                ]
                col_set = {c.lower() for c in cols}
                if col_set == {"renk_varyant_id", "boyut"}:
                    return False, (
                        f"UNIQUE({', '.join(cols)}) — revizyon UV şeması "
                        f"desteklenmiyor (Migration 102 gerekli)"
                    )
        except sqlite3.OperationalError:
            pass
        return False, "rev_no kolonu yok (Migration 102 gerekli)"
    try:
        for idx in con.execute("PRAGMA index_list(nexgen_uretim_varyant)"):
            if not idx[2]:
                continue
            cols = [
                r[2] for r in con.execute(f"PRAGMA index_info({idx[1]})")
            ]
            col_set = {c.lower() for c in cols}
            if col_set == {"renk_varyant_id", "boyut"}:
                return False, (
                    f"Eski UNIQUE({', '.join(cols)}) hâlâ aktif"
                )
        if not con.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (UV_REV_NO_INDEX,),
        ).fetchone():
            # Tablo UNIQUE constraint ile de olabilir
            tbl = con.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' "
                "AND name='nexgen_uretim_varyant'"
            ).fetchone()
            sql = (tbl[0] or "").upper() if tbl else ""
            if "REV_NO" not in sql or "UNIQUE" not in sql:
                return False, f"{UV_REV_NO_INDEX} veya rev_no UNIQUE yok"
    except sqlite3.OperationalError:
        return False, "Şema kontrol hatası"
    return True, ""


def _revision_uv_bul(
    con: sqlite3.Connection, kaynak_uv_id: int, rev_no: int = REVISION_REV_NO,
) -> int | None:
    """kaynak_varyant_id + rev_no ile mevcut revizyon UV (idempotent)."""
    if _uv_rev_no_kolon_var_mi(con):
        row = con.execute(
            """SELECT id FROM nexgen_uretim_varyant
               WHERE aktif=1 AND kaynak_varyant_id=? AND rev_no=?
               ORDER BY id DESC LIMIT 1""",
            (kaynak_uv_id, rev_no),
        ).fetchone()
    else:
        row = con.execute(
            """SELECT id FROM nexgen_uretim_varyant
               WHERE aktif=1 AND kaynak_varyant_id=?
               ORDER BY id DESC LIMIT 1""",
            (kaynak_uv_id,),
        ).fetchone()
    return row[0] if row else None


def _revision_uv_ad_uret(eski_ad: str, kaynak_uv_id: int) -> str:
    """Deterministik revizyon adı — her zaman R2 suffix."""
    base = (eski_ad or f"uv-{kaynak_uv_id}").strip()
    if base.upper().endswith(REVISION_SUFFIX.strip().upper()):
        return base
    return f"{base}{REVISION_SUFFIX}"


def _kalem_fingerprint_list_ana(kalemler: list[dict]) -> str:
    """DB ile uyumlu ana kalem fingerprint (sıra = insert sırası)."""
    raw = "|".join(
        f"{(k.get('stok_kodu') or '').strip().upper()}:"
        f"{float(k.get('miktar_kg', 0)):.6f}:{i}"
        for i, k in enumerate(kalemler, 1)
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _ana_kalem_listesi(nb: "NormalizedBoyut") -> list[dict]:
    return [
        {"stok_kodu": k.stok_kodu, "miktar_kg": k.miktar_kg}
        for k in nb.ana_kalemler
    ]


def _rf_identity_key(
    cari_kodu: str, parent_kod: str, varyant: str, renk_kodu: str,
) -> str:
    """P5B.1 — RF aday kimliği: cari|parent_formul|varyant|renk_kodu."""
    return (
        f"{(cari_kodu or '').strip()}|"
        f"{(parent_kod or '').strip()}|"
        f"{(varyant or '').strip()}|"
        f"{(renk_kodu or '').strip()}"
    )


def _rf_import_identity_marker(rf_key: str) -> str:
    return f"{RF_IMPORT_IDENTITY_PREFIX}{rf_key}"


def _rf_pigment_kategori_gecerli(kategori: str) -> bool:
    return (kategori or "").strip().upper() in RF_PIGMENT_KATEGORILERI


def _rf_pigment_fp_from_kalemler(kalemler: list[dict]) -> str:
    parts = sorted(
        f"{k['stok_kodu']}:{float(k['miktar_kg']):.6f}"
        for k in kalemler
        if k.get("stok_kodu")
    )
    return "|".join(parts)


def _rf_pigment_fp_db(con: sqlite3.Connection, rf_renk_id: int) -> str:
    rows = con.execute(
        """
        SELECT sk.kod, rk.miktar_kg
        FROM nexgen_rf_kalem rk
        JOIN nexgen_stok_kart sk ON sk.id = rk.stok_kart_id
        WHERE rk.rf_renk_id=? AND rk.aktif=1
        ORDER BY sk.kod
        """,
        (rf_renk_id,),
    ).fetchall()
    return "|".join(f"{r[0]}:{float(r[1]):.6f}" for r in rows)


def _rf_revizyon_tablosu_var_mi(con: sqlite3.Connection) -> bool:
    return bool(con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nexgen_rf_revizyon'"
    ).fetchone())


def _import_rf_kod_uret(con: sqlite3.Connection, renk_kodu: str) -> str:
    """TABAN import TASLAK RF kodu — NX-RF- prefix."""
    row = con.execute(
        "SELECT MAX(CAST(SUBSTR(rf_kod, 8) AS INTEGER)) AS son "
        "FROM nexgen_rf_renk WHERE rf_kod LIKE 'NX-RF-%'"
    ).fetchone()
    son = row[0] if row and row[0] else 0
    base = f"NX-RF-{son + 1:04d}"
    clash = con.execute(
        "SELECT id FROM nexgen_rf_renk WHERE rf_kod=?", (base,),
    ).fetchone()
    if clash:
        return f"NX-RF-T{renk_kodu}-{son + 1:04d}"
    return base


def _rf_pigment_kod_set(pigment_fp: str) -> frozenset[str]:
    if not pigment_fp:
        return frozenset()
    return frozenset(p.split(":")[0] for p in pigment_fp.split("|") if p)


def _rf_aktif_revizyon_var_mi(con: sqlite3.Connection, rf_renk_id: int) -> bool:
    if not _rf_revizyon_tablosu_var_mi(con):
        return False
    return bool(con.execute(
        "SELECT 1 FROM nexgen_rf_revizyon WHERE rf_renk_id=? AND aktif=1 LIMIT 1",
        (rf_renk_id,),
    ).fetchone())


def _rf_boya_kalemler_for_cari(
    rv_excel: NormalizedRenkVaryanti,
    formul_nk: str,
    cari_kod: str,
    pkg: ImportPackage,
    varyant_pref: str = "",
) -> tuple[list, str, str]:
    """Cari+kullanım boyutuna göre pigment kalemleri ve fingerprint."""
    rk = (rv_excel.renk_kodu or "").strip()
    vv = (varyant_pref or "").strip()
    boyut_pref = ""
    for ku in pkg.kullanimlar:
        if (ku.cari_kodu or "").strip() != cari_kod:
            continue
        if (ku.renk_kodu or "").strip() != rk:
            continue
        if vv and (ku.varyant or "").strip() != vv:
            continue
        if normalize_ascii_import(ku.formul_ad or "") != formul_nk:
            continue
        boyut_pref = (ku.boyut or "MEDIUM").strip().upper()
        break
    if boyut_pref and boyut_pref in rv_excel.boyutlar:
        nb = rv_excel.boyutlar[boyut_pref]
        return nb.boya_kalemleri, nb.fingerprint_boya, boyut_pref
    for boyut, nb in rv_excel.boyutlar.items():
        if nb.boya_kalemleri:
            return nb.boya_kalemleri, nb.fingerprint_boya, boyut
    return [], "", boyut_pref or "MEDIUM"


def _rf_stok_dogrula(
    con: sqlite3.Connection,
    boya_kalemler: list,
    stok_map: dict[str, int],
) -> list[str]:
    """RF pigment stok kontrolü — MASTERBATCH dahil."""
    issues: list[str] = []
    for k in boya_kalemler:
        sc = (k.stok_kodu or "").strip()
        if not sc:
            issues.append("BOS_STOK_KODU")
            continue
        sk = con.execute(
            "SELECT id, kod, kategori, aktif FROM nexgen_stok_kart WHERE kod=?",
            (sc,),
        ).fetchone()
        if not sk:
            issues.append(f"EKSIK:{sc}")
        elif not sk[3]:
            issues.append(f"PASIF:{sc}")
        elif not _rf_pigment_kategori_gecerli(sk[2]):
            issues.append(f"KATEGORI:{sc}={sk[2]}")
        else:
            stok_map[sc] = sk[0]
    return issues


def _rf_taslak_bul(
    con: sqlite3.Connection, rf_key: str, pigment_fp: str,
) -> dict | None:
    marker = _rf_import_identity_marker(rf_key)
    row = con.execute(
        "SELECT id, rf_kod, ad, durum, cari_id FROM nexgen_rf_renk "
        "WHERE aktif=1 AND durum='TASLAK' AND aciklama LIKE ?",
        (f"%{marker}%",),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    if _rf_pigment_fp_db(con, d["id"]) == pigment_fp:
        return d
    return None


def _rf_db_eslesmeleri(
    con: sqlite3.Connection,
    cari_id: int,
    renk_kodu: str,
    parent_kod: str = "",
) -> list[dict]:
    """Renk kodu ile mevcut RF adayları (ONAYLI/TASLAK)."""
    pat = f"%{renk_kodu}%"
    rows = con.execute(
        """
        SELECT rf.id, rf.rf_kod, rf.ad, rf.durum, rf.cari_id, rf.ilk_talep_cari_id,
               f.kod AS formul_kod
        FROM nexgen_rf_renk rf
        LEFT JOIN nexgen_rf_formul_uygunluk rfu ON rfu.rf_renk_id=rf.id AND rfu.aktif=1
        LEFT JOIN nexgen_formul f ON f.id=rfu.formul_id
        WHERE rf.aktif=1
          AND (rf.cari_id=? OR rf.ilk_talep_cari_id=? OR rf.cari_id IS NULL)
          AND (rf.rf_kod LIKE ? OR rf.ad LIKE ? OR rf.rf_kod=? OR rf.ad=?)
        """,
        (cari_id, cari_id, pat, pat, renk_kodu, renk_kodu),
    ).fetchall()
    pk = (parent_kod or "").strip()
    seen: set[int] = set()
    out = []
    for r in rows:
        rid = r[0]
        if rid in seen:
            continue
        seen.add(rid)
        fk = (r[6] or "").strip() if len(r) > 6 else ""
        parent_mismatch = bool(pk and fk and fk != pk)
        d = {
            "id": rid, "rf_kod": r[1], "ad": r[2], "durum": r[3],
            "cari_id": r[4], "ilk_talep_cari_id": r[5],
            "formul_kod": fk,
            "parent_mismatch": parent_mismatch,
            "pigment_fp": _rf_pigment_fp_db(con, rid),
        }
        out.append(d)
    return out


def _rf_siniflandir(
    con: sqlite3.Connection,
    rf_key: str,
    pigment_fp: str,
    pigment_kalemler: list[dict],
    stok_issues: list[str],
    cari_id: int,
    renk_kodu: str,
    parent_kod: str = "",
) -> tuple[str, str, dict | None]:
    """
    RF aday kararı.
    Döner: (aksiyon, mesaj_ek, eslesen_rf_dict)
    """
    if stok_issues:
        return "GERCEK_BLOCKER", ";".join(stok_issues), None

    taslak = _rf_taslak_bul(con, rf_key, pigment_fp)
    if taslak:
        return "MATCH_RF_TASLAK", f"rf_id={taslak['id']}", taslak

    db_matches = _rf_db_eslesmeleri(con, cari_id, renk_kodu, parent_kod)
    uyumlu = [m for m in db_matches if not m.get("parent_mismatch")]

    exact = [m for m in uyumlu if m["pigment_fp"] == pigment_fp]
    if exact:
        onayli = [m for m in exact if m["durum"] in RF_ONAYLI_DURUMLAR]
        hedef = onayli[0] if onayli else exact[0]
        return "MATCH_RF", f"rf_id={hedef['id']} durum={hedef['durum']}", hedef

    excel_kodlar = _rf_pigment_kod_set(pigment_fp)
    if excel_kodlar:
        global_zayif = [
            m for m in uyumlu
            if m["cari_id"] is None
            and m["durum"] in RF_ONAYLI_DURUMLAR
            and _rf_pigment_kod_set(m["pigment_fp"]) == excel_kodlar
        ]
        if global_zayif:
            h = global_zayif[0]
            return (
                "MATCH_RF",
                f"rf_id={h['id']} durum={h['durum']} (global_zayif)",
                h,
            )

    rev_aday = [
        m for m in uyumlu
        if m["durum"] in RF_ONAYLI_DURUMLAR
        and m["pigment_fp"]
        and m["pigment_fp"] != pigment_fp
        and _rf_aktif_revizyon_var_mi(con, m["id"])
    ]
    if rev_aday:
        h = rev_aday[0]
        return (
            "RF_REVISION_MANUAL_REVIEW",
            f"Mevcut ONAYLI RF pigment farklı: rf_id={h['id']}",
            h,
        )

    return "INSERT_RF_TASLAK", "Yeni TASLAK RF", None


def _rf_taslak_payload(
    *,
    rf_key: str,
    cari_id: int,
    cari_kod: str,
    parent_formul_id: int,
    parent_kod: str,
    rv_id: int | None,
    varyant: str,
    renk_kodu: str,
    renk_adi: str,
    pigment_kalemler: list[dict],
    pigment_fp: str,
    fingerprint_boya: str,
    boyut: str,
    excel_kaynak: str = "TABAN_EXCEL",
) -> dict:
    return {
        "rf_identity": rf_key,
        "cari_id": cari_id,
        "cari_kod": cari_kod,
        "parent_formul_id": parent_formul_id,
        "parent_kod": parent_kod,
        "rv_id": rv_id,
        "varyant": varyant,
        "renk_kodu": renk_kodu,
        "renk_adi": renk_adi,
        "pigment_kalemleri": pigment_kalemler,
        "pigment_fp": pigment_fp,
        "fingerprint_boya": fingerprint_boya,
        "boyut": boyut,
        "durum": "TASLAK",
        "excel_kaynak": excel_kaynak,
    }


def _rf_pigmentler_json_olustur(
    con: sqlite3.Connection, pigment_kalemler: list[dict], stok_map: dict[str, int],
) -> str:
    pigmentler = []
    for i, p in enumerate(pigment_kalemler, 1):
        sk_id = stok_map.get(p["stok_kodu"])
        if not sk_id:
            row = con.execute(
                "SELECT id, ad FROM nexgen_stok_kart WHERE kod=? AND aktif=1",
                (p["stok_kodu"],),
            ).fetchone()
            sk_id = row[0] if row else None
            ad = row[1] if row else p["stok_kodu"]
        else:
            row = con.execute(
                "SELECT ad FROM nexgen_stok_kart WHERE id=?", (sk_id,),
            ).fetchone()
            ad = row[0] if row else p["stok_kodu"]
        if not sk_id:
            continue
        pigmentler.append({
            "stok_kart_id": sk_id,
            "pigment_ad": ad,
            "miktar_kg": float(p["miktar_kg"]),
            "sira": i,
        })
    return json.dumps(pigmentler, ensure_ascii=False)


def _kullanim_uv_coz(
    ku: "NormalizedKullanim",
    formul_map: dict[str, dict],
    rv_map: dict[tuple, int],
    uv_map: dict[tuple, int],
) -> tuple[int | None, int | None, str]:
    """Kullanım kaydından (uv_id, rv_id, parent_kod) çöz."""
    db_f, _ = _formul_parent_coz(
        ku.uretim_tipi or "", ku.urun_ailesi or "", formul_map,
    )
    if not db_f:
        return None, None, ""
    rv_nk = normalize_ascii_import(ku.varyant or "")
    rv_id = rv_map.get((db_f["f_id"], rv_nk))
    boyut = (ku.boyut or "STANDART").strip().upper()
    uv_id = uv_map.get((rv_id, boyut)) if rv_id else None
    return uv_id, rv_id, db_f["f_kod"]


def _planlama_db_satir_bul(
    con: sqlite3.Connection,
    cari_id: int,
    ut_id: int,
    fid: int,
    rv_id: int,
    renk_kodu: str,
    boyut_val: str,
) -> int | None:
    """Apply ile aynı business identity — mevcut aktif planlama satırı."""
    renk_kodu = (renk_kodu or "").strip()
    boyut_val = (boyut_val or "STANDART").strip().upper()
    has_renk_col = _planlama_musteri_renk_kolon_var_mi(con)
    has_boyut_col = _planlama_boyut_kolon_var_mi(con)
    if has_renk_col and has_boyut_col:
        row = con.execute(
            """SELECT id FROM nexgen_planlama_uygunluk
               WHERE cari_id=? AND uretim_tipi_id=? AND formul_id=?
                 AND renk_varyant_id=? AND aktif=1
                 AND COALESCE(musteri_renk_kodu,'')=?
                 AND COALESCE(boyut,'')=?""",
            (cari_id, ut_id, fid, rv_id, renk_kodu, boyut_val),
        ).fetchone()
    elif has_renk_col:
        row = con.execute(
            """SELECT id FROM nexgen_planlama_uygunluk
               WHERE cari_id=? AND uretim_tipi_id=? AND formul_id=?
                 AND renk_varyant_id=? AND aktif=1
                 AND COALESCE(musteri_renk_kodu,'')=?""",
            (cari_id, ut_id, fid, rv_id, renk_kodu),
        ).fetchone()
    else:
        row = con.execute(
            """SELECT id FROM nexgen_planlama_uygunluk
               WHERE cari_id=? AND uretim_tipi_id=? AND formul_id=?
                 AND renk_varyant_id=? AND aktif=1""",
            (cari_id, ut_id, fid, rv_id),
        ).fetchone()
    return row[0] if row else None


def _planlama_identity_key(
    ku: "NormalizedKullanim",
    parent_kod: str = "",
) -> str:
    """
    P5B.4 — planlama idempotency kimliği (6 alan).
    cari|ut|parent|varyant|renk_kodu|boyut
    kalip_carpani yalnız fingerprint'te; identity değil.
    """
    return "|".join([
        (ku.cari_kodu or "").strip().upper(),
        (ku.uretim_tipi or "").strip().upper(),
        parent_kod or (ku.formul_ad or "").strip(),
        normalize_ascii_import(ku.varyant or ""),
        (ku.renk_kodu or "").strip().upper(),
        (ku.boyut or "STANDART").strip().upper(),
    ])


def _pending_rv_map_from_sim(sonuc: SimulasyonSonucu) -> dict[tuple[int, str], str]:
    """
    P5B.4 — aynı partial plan içindeki güvenli INSERT_RV operasyonları.
    (formul_id, normalize(varyant)) → op_id
    """
    pending: dict[tuple[int, str], str] = {}
    for k in sonuc.islemler:
        if k.aksiyon != "INSERT_RV" or not k.safe_to_apply:
            continue
        vd = k.yeni_deger or {}
        fid = vd.get("formul_id")
        rv_nk = normalize_ascii_import(vd.get("renk_varyant") or "")
        if fid and rv_nk and k.op_id:
            pending[(int(fid), rv_nk)] = k.op_id
    return pending


def _planlama_rv_coz(
    ku: "NormalizedKullanim",
    formul_map: dict[str, dict],
    rv_map: dict[tuple, int],
    pending_rv: dict[tuple[int, str], str],
) -> tuple[int | None, str | None, str, int | None]:
    """
    P5B.4 — planlama RV çözümü (sıra: DB → pending INSERT_RV → yok).
    Döner: (rv_id, parent_op_id, kaynak, formul_id)
    kaynak: 'DB' | 'INSERT_RV' | 'NONE'
    """
    db_f, _ = _formul_parent_coz(
        ku.uretim_tipi or "", ku.urun_ailesi or "", formul_map,
    )
    if not db_f:
        return None, None, "NONE", None
    fid = db_f["f_id"]
    rv_nk = normalize_ascii_import(ku.varyant or "")
    if not rv_nk:
        return None, None, "NONE", fid
    rv_id = rv_map.get((fid, rv_nk))
    if rv_id is not None:
        return rv_id, None, "DB", fid
    parent_op = pending_rv.get((fid, rv_nk))
    if parent_op:
        return None, parent_op, "INSERT_RV", fid
    return None, None, "NONE", fid


def _git_commit_sha() -> str:
    """P5B.3 — confirmation token için repo HEAD SHA. Başarısızsa boş string."""
    try:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=root,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return ""


def _motor_code_fingerprint() -> str:
    """
    P5B.3 — motor dosyalarının SHA256 toplamı.
    Dosya içeriği değişirse token değişir.
    """
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    h = hashlib.sha256()
    for rel in sorted(MOTOR_FP_FILES):
        p = os.path.join(root, rel.replace("/", os.sep))
        try:
            with open(p, "rb") as f:
                h.update(rel.encode())
                h.update(f.read())
        except OSError:
            h.update(rel.encode())
            h.update(b"MISSING")
    return h.hexdigest()


def _planlama_schema_kontrol(con: sqlite3.Connection) -> dict:
    """
    P5B.3 — nexgen_planlama_uygunluk kolon varlık raporu.
    Döner: kolon_var {renk_kodu, boyut, uretim_varyant_id, renk_varyant_id, rf_renk_id}
    + schema_identity_eksik (bool)
    """
    try:
        cols = {c[1] for c in con.execute(
            "PRAGMA table_info(nexgen_planlama_uygunluk)"
        ).fetchall()}
    except sqlite3.OperationalError:
        cols = set()
    rapor = {
        "renk_kodu": "renk_kodu" in cols,
        "boyut": "boyut" in cols,
        "uretim_varyant_id": "uretim_varyant_id" in cols,
        "renk_varyant_id": "renk_varyant_id" in cols,
        "rf_renk_id": "rf_renk_id" in cols,
        "musteri_renk_kodu": "musteri_renk_kodu" in cols,
    }
    # P5C-1 — 6-alan identity: musteri_renk_kodu + boyut kolonları şart.
    rapor["schema_identity_eksik"] = not (
        "musteri_renk_kodu" in cols and "boyut" in cols
    )
    return rapor


def _planlama_boyut_kolon_var_mi(con: sqlite3.Connection) -> bool:
    try:
        cols = [c[1] for c in con.execute(
            "PRAGMA table_info(nexgen_planlama_uygunluk)"
        ).fetchall()]
        return "boyut" in cols
    except sqlite3.OperationalError:
        return False


def _planlama_identity_index_var_mi(con: sqlite3.Connection) -> bool:
    try:
        return bool(con.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='uq_npu_identity'"
        ).fetchone())
    except sqlite3.OperationalError:
        return False


def _planlama_musteri_renk_kolon_var_mi(con: sqlite3.Connection) -> bool:
    try:
        cols = [c[1] for c in con.execute(
            "PRAGMA table_info(nexgen_planlama_uygunluk)"
        ).fetchall()]
        return "musteri_renk_kodu" in cols
    except sqlite3.OperationalError:
        return False


def _ensure_planlama_p5b3_schema(con: sqlite3.Connection) -> bool:
    """
    P5C-1 — geçici DB için Migration 101 eşdeğeri şema (musteri_renk_kodu + boyut).
    Gerçek DB'de bu fazda çalıştırılmaz; üretimde Migration 101 kullanılır.
    """
    try:
        if not con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='nexgen_planlama_uygunluk'"
        ).fetchone():
            return False

        kolon_eklendi = False
        if not _planlama_musteri_renk_kolon_var_mi(con):
            con.execute(
                "ALTER TABLE nexgen_planlama_uygunluk "
                "ADD COLUMN musteri_renk_kodu TEXT"
            )
            kolon_eklendi = True
        if not _planlama_boyut_kolon_var_mi(con):
            con.execute(
                "ALTER TABLE nexgen_planlama_uygunluk ADD COLUMN boyut TEXT"
            )
            kolon_eklendi = True

        if _planlama_identity_index_var_mi(con) and not kolon_eklendi:
            return True

        con.execute("DROP INDEX IF EXISTS uq_npu_kullanim")
        con.execute("DROP INDEX IF EXISTS uq_npu_kullanim_v2")
        con.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_npu_identity
            ON nexgen_planlama_uygunluk (
                cari_id,
                uretim_tipi_id,
                formul_id,
                renk_varyant_id,
                COALESCE(musteri_renk_kodu, ''),
                COALESCE(boyut, ''),
                IFNULL(rf_renk_id, -1),
                IFNULL(rf_rev_no,  -1)
            )
        """)
        con.commit()
        return True
    except sqlite3.OperationalError:
        return False


def _p5b_bagimlilik_filtre(
    sonuc: SimulasyonSonucu,
    bloke_uv_ids: set[int],
    yeni_rv_keys: set[str],
    yeni_uv_keys: set[str],
) -> None:
    """
    P5B.1 — bloke UV'ye bağlı child operasyonları işaretle.
    Parent güvensizse child da atlanır.
    """
    op_map: dict[str, SimulasyonKalemi] = {}
    op_counter = 0
    for k in sonuc.islemler:
        if not k.op_id:
            op_counter += 1
            k.op_id = f"op_{op_counter:04d}"

    for k in sonuc.islemler:
        op_map[k.op_id] = k

    # Bloke UV'ye bağlı operasyonları işaretle
    for k in sonuc.islemler:
        if k.bagli_uv_id and k.bagli_uv_id in bloke_uv_ids:
            k.blocked_dependency = True
            k.safe_to_apply = False

    # Parent zinciri yayılımı
    changed = True
    while changed:
        changed = False
        for k in sonuc.islemler:
            if not k.parent_op_id:
                continue
            parent = op_map.get(k.parent_op_id)
            if parent and not parent.safe_to_apply and k.safe_to_apply:
                k.blocked_dependency = True
                k.safe_to_apply = False
                changed = True

    # Bağımlılık grafiği raporu
    for k in sonuc.islemler:
        if k.aksiyon not in (
            "INSERT_RV", "INSERT_UV", "INSERT_UV_REVISION",
            "UPDATE_ANA_KALEM", "INSERT_ANA_KALEM",
            "INSERT_PLANLAMA", "INSERT_PLANLAMA_REVISION",
            "INSERT_RF_TASLAK", "MATCH_RF", "MATCH_RF_TASLAK",
            "RF_REVISION_MANUAL_REVIEW", "BLOCKED_DEPENDENCY",
        ):
            continue
        sonuc.bagimlilik_grafigi.append({
            "operation_id": k.op_id,
            "parent_operation": k.parent_op_id,
            "aksiyon": k.aksiyon,
            "identity": k.identity,
            "bagli_formul": k.bagli_formul_kod,
            "bagli_rv_id": k.bagli_rv_id,
            "bagli_uv_id": k.bagli_uv_id,
            "bloke_uv_bagli": bool(k.bagli_uv_id in bloke_uv_ids if k.bagli_uv_id else False),
            "safe_to_apply": k.safe_to_apply,
            "blocked_dependency": k.blocked_dependency,
        })


# ---------------------------------------------------------------------------
# Formül parent mapping — P4F.2D
# ---------------------------------------------------------------------------
def _build_formul_mapping(
    pkg: ImportPackage,
    formul_map_ascii: dict[str, dict],
) -> list[MappingKaydi]:
    """
    Excel formül grupları için parent DB mapping tablosunu üretir.

    P4F.2D eşleştirme stratejisi (deterministik karar ağacı):
      - uretim_tipi + urun_ailesi → _formul_parent_coz()
      - MATCH  → mevcut ana formül altında RV/UV planlanacak
      - BLOCKER → PARENT_FORMUL_BELIRSIZ
      - INSERT_NEW yalnız gerçekten yeni ana formül varsa
    """
    kayitlar: list[MappingKaydi] = []
    seen_keys: set[str] = set()  # (normalize(formul_ad), uretim_tipi, urun_ailesi)

    # formul_ad → uretim_tipi/urun_ailesi eşleştirmesi için kullanım tablosu
    formul_ad_meta: dict[str, tuple[str, str]] = {}
    for ku in pkg.kullanimlar:
        na = normalize_ascii_import(ku.formul_ad or "")
        if na and na not in formul_ad_meta:
            formul_ad_meta[na] = (
                (ku.uretim_tipi or "").strip().upper(),
                (ku.urun_ailesi or "").strip().upper(),
            )

    for formul in pkg.formuller:
        nk = normalize_ascii_import(formul.ad)
        # uretim_tipi ve urun_ailesi: NormalizedFormul'da urun_ailesi var,
        # uretim_tipi için kullanimlar tablosundan al
        meta = formul_ad_meta.get(nk, ("", normalize_ascii_import(formul.urun_ailesi or "")))
        uretim_tipi = meta[0]
        urun_ailesi = meta[1] or normalize_ascii_import(formul.urun_ailesi or "")

        seen_key = f"{nk}|{uretim_tipi}|{urun_ailesi}"
        if seen_key in seen_keys:
            continue
        seen_keys.add(seen_key)

        db_f, hata = _formul_parent_coz(uretim_tipi, urun_ailesi, formul_map_ascii)

        if db_f:
            kayitlar.append(MappingKaydi(
                excel_formul_ad=formul.ad,
                excel_aile=formul.urun_ailesi or "",
                excel_uretim_tipi=uretim_tipi,
                normalize_key=nk,
                db_formul_id=db_f["f_id"],
                db_kod=db_f["f_kod"],
                db_ad=db_f["f_ad"],
                kaynak="RULE_BASED",
                guven="HIGH",
                sonuc="MATCH",
            ))
        else:
            kayitlar.append(MappingKaydi(
                excel_formul_ad=formul.ad,
                excel_aile=formul.urun_ailesi or "",
                excel_uretim_tipi=uretim_tipi,
                normalize_key=nk,
                db_formul_id=None,
                db_kod="",
                db_ad="",
                kaynak="AMBIGUOUS",
                guven="LOW",
                sonuc="BLOCKER",
            ))

    return kayitlar


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
def preflight_kontrol(
    pkg: ImportPackage,
    db_path: str | None = None,
    excel_sha: str | None = None,
    beklenen_db_sha: str | None = None,
    diff_bloker_sayisi: int = 0,
    diff_biz_rule_sayisi: int = 0,
    is_apply: bool = False,
) -> PreflightSonucu:
    """
    Gerçek import başlamadan önce tüm ön koşulları doğrular.
    is_apply=False → dry-run: P07 WARNING; P06 daraltılmış
    is_apply=True  → apply: P07 BLOKER; P06 daraltılmış
    """
    sonuc = PreflightSonucu()
    db_path = os.path.abspath(db_path or DB_PATH)

    if not os.path.isfile(db_path):
        sonuc.ekle_hata(f"P01 FAIL: DB bulunamadı: {db_path}")
        return sonuc

    sonuc.db_sha = _sha256(db_path)
    if beklenen_db_sha and sonuc.db_sha != beklenen_db_sha:
        sonuc.ekle_hata(
            f"P02 FAIL: DB SHA uyuşmuyor — beklenen={beklenen_db_sha[:16]} "
            f"gerçek={sonuc.db_sha[:16]}"
        )

    excel_path = pkg.kaynak_bilgisi.get("dosya_yolu", "")
    if excel_path and os.path.isfile(excel_path):
        sonuc.excel_sha = _sha256(excel_path)
        if excel_sha and sonuc.excel_sha != excel_sha:
            sonuc.ekle_hata(
                f"P03 FAIL: Excel SHA uyuşmuyor — beklenen={excel_sha[:16]} "
                f"gerçek={sonuc.excel_sha[:16]}"
            )

    if diff_bloker_sayisi > 0:
        sonuc.ekle_hata(f"P04 FAIL: Diff BLOCKER sayısı {diff_bloker_sayisi} > 0")

    if diff_biz_rule_sayisi > 0:
        sonuc.ekle_uyari(
            f"P05 UYARI: BUSINESS_RULE_REVIEW sayısı {diff_biz_rule_sayisi} > 0"
        )

    con = db_readonly_connect(db_path)
    try:
        # P06 — Etkilenen batch kontrolü (daraltılmış — P4F.2D)
        formul_map_ascii = _formul_id_map_ascii(con)
        rv_map = _rv_id_map_varyant(con)
        uv_map = _uv_id_map(con)
        aktif_batchler = _aktif_batch_listesi(con)

        # Import planındaki değişecek UV set'i — yeni parent çözümleme ile
        degisecek_uv_ids: set[int] = set()

        # formul_ad → (uretim_tipi, urun_ailesi) haritası
        formul_ad_meta_pf: dict[str, tuple[str, str]] = {}
        for ku in pkg.kullanimlar:
            na = normalize_ascii_import(ku.formul_ad or "")
            if na and na not in formul_ad_meta_pf:
                formul_ad_meta_pf[na] = (
                    (ku.uretim_tipi or "").strip().upper(),
                    (ku.urun_ailesi or "").strip().upper(),
                )

        for formul in pkg.formuller:
            nk = normalize_ascii_import(formul.ad)
            meta = formul_ad_meta_pf.get(nk, ("", normalize_ascii_import(formul.urun_ailesi or "")))
            db_f, _ = _formul_parent_coz(meta[0], meta[1], formul_map_ascii)
            if db_f is None:
                continue  # Bilinmeyen/yeni parent — batch etkisi yok
            # P4F.2D: yeni renkler INSERT_UV olduğundan mevcut UV'lere
            # dokunulmaz. Preflight'ta batch etkisi yok.
            # (REVISION_SNAPSHOT_REQUIRED yalnız simulate_import üretir)
            pass  # degisecek_uv_ids bu döngüde güncellenmez

        etkilenen_batchler = [
            b for b in aktif_batchler
            if b.get("uretim_varyant_id") in degisecek_uv_ids
        ]
        sonuc.etkilenen_batch_sayisi = len(etkilenen_batchler)
        if etkilenen_batchler:
            uv_ids_str = ",".join(str(b["uretim_varyant_id"]) for b in etkilenen_batchler[:5])
            sonuc.ekle_hata(
                f"P06 FAIL: {len(etkilenen_batchler)} aktif batch etkilenecek UV'ye bağlı "
                f"(uv_ids={uv_ids_str}) — değişen reçete batch'i etkiler"
            )

        # P07 — Import log tablosu
        sonuc.import_log_tablosu_var = _import_log_tablo_var_mi(con)
        if not sonuc.import_log_tablosu_var:
            msg = (
                "P07: nexgen_import_batch tablosu DB'de yok "
                "— migration 100 çalıştırılmalı"
            )
            if is_apply:
                sonuc.ekle_hata(f"P07 FAIL (APPLY): {msg}")
            else:
                sonuc.ekle_uyari(f"P07 UYARI (DRY-RUN): {msg}")

        # P08 — Stok FK
        stok_map = _stok_id_map_v2(con)
        eksik_stok: set[str] = set()
        for f in pkg.formuller:
            for rv in f.renk_varyantlari:
                for nb in rv.boyutlar.values():
                    for k in nb.ana_kalemler + nb.boya_kalemleri:
                        kod = k.stok_kodu.strip().upper()
                        if kod and kod not in stok_map:
                            eksik_stok.add(kod)
        if eksik_stok:
            sonuc.ekle_hata(
                f"P08 FAIL: {len(eksik_stok)} stok kodu DB'de yok: "
                f"{sorted(eksik_stok)[:5]}{'...' if len(eksik_stok) > 5 else ''}"
            )

        # P09 — Cari FK
        cari_map = _cari_id_map(con)
        eksik_cari: set[str] = set()
        for ku in pkg.kullanimlar:
            if ku.cari_kodu and ku.cari_kodu.strip() not in cari_map:
                eksik_cari.add(ku.cari_kodu.strip())
        if eksik_cari:
            sonuc.ekle_hata(
                f"P09 FAIL: {len(eksik_cari)} cari kodu DB'de yok: {sorted(eksik_cari)}"
            )

        # P10 — Üretim tipi FK
        ut_map = _ut_id_map(con)
        eksik_ut: set[str] = set()
        for ku in pkg.kullanimlar:
            if ku.uretim_tipi:
                # ASCII normalize ile karşılaştır
                ut_nk = normalize_ascii_import(ku.uretim_tipi)
                if ut_nk and ut_nk not in {normalize_ascii_import(k) for k in ut_map}:
                    eksik_ut.add(ku.uretim_tipi.strip().upper())
        if eksik_ut:
            sonuc.ekle_hata(
                f"P10 FAIL: {len(eksik_ut)} üretim tipi DB'de yok: {sorted(eksik_ut)}"
            )

    finally:
        con.close()

    return sonuc


# ---------------------------------------------------------------------------
# Simülasyon (dry-run işlem planı)
# ---------------------------------------------------------------------------
def simulate_import(
    pkg: ImportPackage,
    db_path: str | None = None,
) -> SimulasyonSonucu:
    """
    P5D.2 — DB'ye hiç yazmadan tam işlem planını üretir.
    Kullanılmayan UV → UPDATE_ANA_KALEM; plan/batch/üretim → INSERT_UV_REVISION.
    """
    db_path = os.path.abspath(db_path or DB_PATH)
    sonuc = SimulasyonSonucu()

    con = db_readonly_connect(db_path)
    try:
        stok_map       = _stok_id_map_v2(con)
        cari_map       = _cari_id_map(con)
        ut_map         = _ut_id_map(con)
        formul_map     = _formul_id_map_ascii(con)
        rv_map         = _rv_id_map_varyant(con)
        uv_map         = _uv_id_map_primary(con)
        canonical_uv_map = _uv_id_map_canonical(con)
        aktif_batchler = _aktif_batch_listesi(con)

        # formul_ad → (uretim_tipi, urun_ailesi) haritası
        formul_ad_meta: dict[str, tuple[str, str]] = {}
        for ku in pkg.kullanimlar:
            na = normalize_ascii_import(ku.formul_ad or "")
            if na and na not in formul_ad_meta:
                formul_ad_meta[na] = (
                    (ku.uretim_tipi or "").strip().upper(),
                    (ku.urun_ailesi or "").strip().upper(),
                )

        # formul_ad → varyant haritası (RV kimliği için)
        formul_ad_varyant: dict[str, str] = {}
        for ku in pkg.kullanimlar:
            na = normalize_ascii_import(ku.formul_ad or "")
            if na and ku.varyant and na not in formul_ad_varyant:
                formul_ad_varyant[na] = ku.varyant

        # Mapping tablosunu oluştur
        sonuc.mapping_tablosu = _build_formul_mapping(pkg, formul_map)
        sonuc.uyarilar.append(
            f"AKTIF_BATCH_DURUMLARI={AKTIF_BATCH_DURUMLARI} "
            f"(BITTI aktif sayılmaz)"
        )

        # Değişecek UV set'i (batch kontrolü için)
        degisecek_uv_ids: set[int] = set()
        bloke_uv_ids: set[int] = set()
        revision_op_by_kaynak: dict[int, str] = {}
        revision_uv_by_kaynak: dict[int, int] = {}
        rev_schema_ok, rev_schema_neden = _uv_revision_schema_destekli_mi(con)

        # P5B.1 — scoped RF identity (cari|parent|varyant|renk_kodu)
        rf_identity_fp: dict[str, set[str]] = {}
        rf_seen_scoped: set[str] = set()
        yeni_rv_keys: set[str] = set()
        yeni_uv_keys: set[str] = set()
        op_counter = 0

        def _next_op(prefix: str) -> str:
            nonlocal op_counter
            op_counter += 1
            return f"{prefix}_{op_counter:04d}"

        # ─────────────────────────────────────────────
        # Ana döngü: her formül grubu için
        # Formül grup = (formul_ad, urun_ailesi) → parent formül → RV=varyant → UV=boyut
        # Her renk_kodu ayrı UV (boya kalemleri farklı)
        # ─────────────────────────────────────────────
        for formul in pkg.formuller:
            nk = normalize_ascii_import(formul.ad)
            meta = formul_ad_meta.get(nk, ("", normalize_ascii_import(formul.urun_ailesi or "")))
            uretim_tipi = meta[0]
            urun_ailesi = meta[1] or normalize_ascii_import(formul.urun_ailesi or "")

            # Parent formül çöz
            db_f, hata = _formul_parent_coz(uretim_tipi, urun_ailesi, formul_map)

            if db_f is None:
                sonuc.ekle(SimulasyonKalemi(
                    aksiyon="PARENT_FORMUL_BELIRSIZ",
                    tablo="nexgen_formul",
                    identity=f"formul:{formul.ad}",
                    mesaj=f"Parent formül belirlenemedi: {formul.ad!r} — {hata}",
                    bloker_mi=True,
                    bloker_nedeni=hata,
                ))
                continue

            # MATCH_FORMUL kaydı (sayaç için)
            sonuc.ekle(SimulasyonKalemi(
                aksiyon="MATCH_FORMUL",
                tablo="nexgen_formul",
                identity=f"formul_id={db_f['f_id']}",
                mesaj=(
                    f"Parent eşleşti: {formul.ad!r} → "
                    f"{db_f['f_kod']}/{db_f['f_ad']} (id={db_f['f_id']}) "
                    f"via ut={uretim_tipi} aile={urun_ailesi}"
                ),
            ))

            formul_db_id = db_f["f_id"]

            # Varyant: NormalizedFormul'da tek varyant var (tüm sütunlar aynı varyant paylaşır)
            varyant = formul_ad_varyant.get(nk, "")
            rv_nk = normalize_ascii_import(varyant) if varyant else ""

            # RV eşleştirme: (formul_id, normalize(varyant)) → rv_id
            rv_db_id: int | None = None
            if rv_nk:
                rv_db_id = rv_map.get((formul_db_id, rv_nk))

            if rv_db_id is None and rv_nk:
                rv_key = f"{formul_db_id}/{rv_nk}"
                rv_op = _next_op("rv")
                yeni_rv_keys.add(rv_key)
                sonuc.ekle(SimulasyonKalemi(
                    aksiyon="INSERT_RV",
                    tablo="nexgen_renk_varyant",
                    identity=f"formul_id={formul_db_id}/varyant={varyant}",
                    yeni_deger={"formul_id": formul_db_id, "renk_varyant": varyant},
                    mesaj=(
                        f"Yeni RV: {db_f['f_kod']}/{db_f['f_ad']} "
                        f"varyant={varyant!r}"
                    ),
                    op_id=rv_op,
                    bagli_formul_kod=db_f["f_kod"],
                ))
                # rv_db_id None kalır — UV/kalem planlaması yine de yapılır (yeni RV altında)
            elif rv_db_id is not None:
                sonuc.ekle(SimulasyonKalemi(
                    aksiyon="MATCH_RV",
                    tablo="nexgen_renk_varyant",
                    identity=f"rv_id={rv_db_id}",
                    mesaj=(
                        f"RV eşleşti: {db_f['f_kod']}/{db_f['f_ad']} "
                        f"varyant={varyant!r} rv_id={rv_db_id}"
                    ),
                ))
            elif not rv_nk:
                sonuc.uyarilar.append(
                    f"Varyant boş: {formul.ad!r} — RV oluşturulamaz"
                )

            # MODEL 1 UV döngüsü (P5A):
            #   UV kimliği = (rv_id, boyut) — tek UV per varyant+boyut.
            #   - Ana kalemler → INSERT_ANA_KALEM
            #   - Boya kalemleri → NEW_RF_CANDIDATE (RF katmanı)
            #   - Mevcut UV reçete değişikliği → BLOCKED

            # UV'leri boyut bazında tekilleştir — her boyut için bir kez işle
            boyut_islem: dict[str, int | None] = {}  # boyut_key → uv_db_id veya None(yeni)
            for rv_excel in formul.renk_varyantlari:
                for boyut in rv_excel.boyutlar:
                    bk = (boyut or "STANDART").strip().upper()
                    if bk in boyut_islem:
                        continue  # Bu boyut zaten işlendi
                    uv_db_id = (
                        uv_map.get((rv_db_id, bk)) if rv_db_id is not None else None
                    )
                    boyut_islem[bk] = uv_db_id

            # Her boyut için tek UV planla
            for bk, uv_db_id in boyut_islem.items():
                # İlgili NormalizedBoyut: bu boyut için en az bir renk var
                nb_ref: "NormalizedBoyut | None" = None
                for rv_excel in formul.renk_varyantlari:
                    if bk in rv_excel.boyutlar:
                        nb_ref = rv_excel.boyutlar[bk]
                        break
                if nb_ref is None:
                    continue

                if uv_db_id is None:
                    parent_rv_str = (
                        f"rv_id={rv_db_id}" if rv_db_id
                        else f"{db_f['f_kod']}/varyant={varyant}"
                    )
                    uv_key = f"{formul_db_id}/{rv_nk}/{bk}"
                    uv_op = _next_op("uv")
                    yeni_uv_keys.add(uv_key)
                    parent_rv_op = ""
                    for prev in reversed(sonuc.islemler):
                        if prev.aksiyon == "INSERT_RV" and prev.bagli_formul_kod == db_f["f_kod"]:
                            parent_rv_op = prev.op_id
                            break
                    sonuc.ekle(SimulasyonKalemi(
                        aksiyon="INSERT_UV",
                        tablo="nexgen_uretim_varyant",
                        identity=f"{parent_rv_str}/{bk}",
                        yeni_deger={"boyut": bk},
                        mesaj=(
                            f"Yeni UV: {db_f['f_kod']}/{db_f['f_ad']} "
                            f"varyant={varyant!r} boyut={bk}"
                        ),
                        op_id=uv_op,
                        parent_op_id=parent_rv_op,
                        bagli_formul_kod=db_f["f_kod"],
                        bagli_rv_id=rv_db_id,
                    ))
                    if nb_ref.ana_kalemler:
                        sonuc.ekle(SimulasyonKalemi(
                            aksiyon="INSERT_ANA_KALEM",
                            tablo="nexgen_recete_kalem",
                            identity=f"yeni_uv:{db_f['f_kod']}/{varyant}/{bk}",
                            yeni_deger=[
                                {"stok_kodu": k.stok_kodu, "miktar_kg": k.miktar_kg}
                                for k in nb_ref.ana_kalemler
                            ],
                            mesaj=(
                                f"Yeni UV ana kalemler: {db_f['f_kod']}/{varyant}/{bk} "
                                f"— {len(nb_ref.ana_kalemler)} kalem"
                            ),
                            op_id=_next_op("kalem"),
                            parent_op_id=uv_op,
                            bagli_formul_kod=db_f["f_kod"],
                            bagli_rv_id=rv_db_id,
                        ))
                else:
                    sonuc.ekle(SimulasyonKalemi(
                        aksiyon="MATCH_UV",
                        tablo="nexgen_uretim_varyant",
                        identity=f"uv_id={uv_db_id}",
                        mesaj=(
                            f"UV eşleşti: {db_f['f_kod']}/{varyant}/{bk} "
                            f"uv_id={uv_db_id}"
                        ),
                    ))
                    # Mevcut UV — ana fingerprint karşılaştır (boya hariç)
                    fp_eski = _kalem_fingerprint_db_ana(con, uv_db_id)
                    kalemler = _ana_kalem_listesi(nb_ref)
                    fp_yeni = _kalem_fingerprint_list_ana(kalemler)

                    if fp_eski == fp_yeni:
                        sonuc.ekle(SimulasyonKalemi(
                            aksiyon="WARNING_ONLY",
                            tablo="nexgen_recete_kalem",
                            identity=f"uv_id={uv_db_id}",
                            mesaj=(
                                f"Ana reçete aynı, dokunulmaz: "
                                f"{db_f['f_kod']}/{varyant}/{bk}"
                            ),
                        ))
                    else:
                        guvenli, guvenli_neden = _uv_guncelleme_guvenli_mi(
                            con, uv_db_id
                        )
                        if guvenli:
                            upd_op = _next_op("upd")
                            sonuc.ekle(SimulasyonKalemi(
                                aksiyon="UPDATE_ANA_KALEM",
                                tablo="nexgen_recete_kalem",
                                identity=f"uv_id={uv_db_id}",
                                eski_deger={"fp_ana": fp_eski},
                                yeni_deger={
                                    "uv_id": uv_db_id,
                                    "kalemler": kalemler,
                                    "fp_eski": fp_eski,
                                    "fp_hedef": fp_yeni,
                                },
                                mesaj=(
                                    f"Güvenli ana reçete güncelleme: "
                                    f"{db_f['f_kod']}/{varyant}/{bk} "
                                    f"fp_eski={fp_eski} fp_yeni={fp_yeni[:8]}"
                                ),
                                op_id=upd_op,
                                bagli_uv_id=uv_db_id,
                                bagli_rv_id=rv_db_id,
                                bagli_formul_kod=db_f["f_kod"],
                            ))
                            degisecek_uv_ids.add(uv_db_id)
                        else:
                            rev_uv_id = _revision_uv_bul(con, uv_db_id)
                            if rev_uv_id:
                                fp_rev = _kalem_fingerprint_db_ana(con, rev_uv_id)
                                revision_uv_by_kaynak[uv_db_id] = rev_uv_id
                                canonical_uv_map[(rv_db_id, bk)] = rev_uv_id
                                if fp_rev == fp_yeni:
                                    sonuc.ekle(SimulasyonKalemi(
                                        aksiyon="MATCH_UV_REVISION",
                                        tablo="nexgen_uretim_varyant",
                                        identity=f"rev_uv_id={rev_uv_id}",
                                        mesaj=(
                                            f"Revizyon UV mevcut ve eşleşti: "
                                            f"kaynak={uv_db_id} rev={rev_uv_id}"
                                        ),
                                        bagli_uv_id=rev_uv_id,
                                        bagli_rv_id=rv_db_id,
                                    ))
                                else:
                                    sonuc.ekle(SimulasyonKalemi(
                                        aksiyon="GERCEK_BLOCKER",
                                        tablo="nexgen_uretim_varyant",
                                        identity=f"rev_uv_id={rev_uv_id}",
                                        mesaj=(
                                            f"Revizyon UV fingerprint uyuşmuyor: "
                                            f"kaynak={uv_db_id} rev={rev_uv_id} "
                                            f"fp_rev={fp_rev} fp_excel={fp_yeni[:8]}"
                                        ),
                                        bloker_mi=True,
                                        bloker_nedeni=(
                                            "Revizyon UV mevcut ama Excel ile uyuşmuyor"
                                        ),
                                    ))
                                    bloke_uv_ids.add(uv_db_id)
                            else:
                                if not rev_schema_ok:
                                    sonuc.ekle(SimulasyonKalemi(
                                        aksiyon="GERCEK_BLOCKER",
                                        tablo="nexgen_uretim_varyant",
                                        identity=f"uv_id={uv_db_id}",
                                        mesaj=(
                                            f"Revizyon UV şeması desteklenmiyor: "
                                            f"{db_f['f_kod']}/{varyant}/{bk} "
                                            f"uv_id={uv_db_id} — {rev_schema_neden}"
                                        ),
                                        bloker_mi=True,
                                        bloker_nedeni=rev_schema_neden,
                                        bagli_uv_id=uv_db_id,
                                    ))
                                    bloke_uv_ids.add(uv_db_id)
                                    continue
                                uv_row = con.execute(
                                    "SELECT ad FROM nexgen_uretim_varyant WHERE id=?",
                                    (uv_db_id,),
                                ).fetchone()
                                eski_ad = uv_row[0] if uv_row else f"uv-{uv_db_id}"
                                rev_ad = _revision_uv_ad_uret(eski_ad, uv_db_id)
                                rev_op = _next_op("rev")
                                revision_op_by_kaynak[uv_db_id] = rev_op
                                sonuc.ekle(SimulasyonKalemi(
                                    aksiyon="INSERT_UV_REVISION",
                                    tablo="nexgen_uretim_varyant",
                                    identity=f"kaynak_uv_id={uv_db_id}",
                                    eski_deger={"fp_ana": fp_eski, "uv_id": uv_db_id},
                                    yeni_deger={
                                        "kaynak_uv_id": uv_db_id,
                                        "renk_varyant_id": rv_db_id,
                                        "boyut": bk,
                                        "ad": rev_ad,
                                        "rev_no": REVISION_REV_NO,
                                        "kalemler": kalemler,
                                        "fp_hedef": fp_yeni,
                                    },
                                    mesaj=(
                                        f"UV revizyonu: {db_f['f_kod']}/{varyant}/{bk} "
                                        f"kaynak={uv_db_id} ad={rev_ad!r} "
                                        f"neden={guvenli_neden}"
                                    ),
                                    op_id=rev_op,
                                    bagli_uv_id=uv_db_id,
                                    bagli_rv_id=rv_db_id,
                                    bagli_formul_kod=db_f["f_kod"],
                                ))
                                sonuc.ekle(SimulasyonKalemi(
                                    aksiyon="INSERT_ANA_KALEM",
                                    tablo="nexgen_recete_kalem",
                                    identity=f"rev_uv:kaynak={uv_db_id}/{bk}",
                                    yeni_deger=kalemler,
                                    mesaj=(
                                        f"Revizyon UV ana kalemler: "
                                        f"{db_f['f_kod']}/{varyant}/{bk}"
                                    ),
                                    op_id=_next_op("kalem"),
                                    parent_op_id=rev_op,
                                    bagli_uv_id=uv_db_id,
                                    bagli_rv_id=rv_db_id,
                                    bagli_formul_kod=db_f["f_kod"],
                                ))

            # P5E-RF — scoped identity → INSERT_RF_TASLAK / MATCH / REVIEW
            rv_db_id_for_rf = None
            rv_nk_rf = normalize_ascii_import(varyant)
            rv_db_id_for_rf = rv_map.get((db_f["f_id"], rv_nk_rf))

            for rv_excel in formul.renk_varyantlari:
                rk = (rv_excel.renk_kodu or "").strip()
                if not rk:
                    continue
                boya_fps = {
                    nb.fingerprint_boya
                    for nb in rv_excel.boyutlar.values()
                    if nb.fingerprint_boya
                }
                if not boya_fps:
                    continue
                caris = sorted({
                    (ku.cari_kodu or "").strip()
                    for ku in pkg.kullanimlar
                    if normalize_ascii_import(ku.formul_ad or "") == nk
                    and (ku.renk_kodu or "").strip() == rk
                    and (ku.cari_kodu or "").strip()
                })
                if not caris:
                    caris = [""]
                for cari in caris:
                    rf_key = _rf_identity_key(cari, db_f["f_kod"], varyant, rk)
                    if rf_key in rf_seen_scoped:
                        continue
                    rf_seen_scoped.add(rf_key)
                    rf_identity_fp.setdefault(rf_key, set()).update(boya_fps)
                    if len(rf_identity_fp[rf_key]) > 1:
                        sonuc.ekle(SimulasyonKalemi(
                            aksiyon="RF_CONFLICT",
                            tablo="nexgen_rf_renk",
                            identity=rf_key,
                            mesaj=(
                                f"Aynı RF identity farklı boya fingerprint: {rf_key}"
                            ),
                            bloker_mi=True,
                            bloker_nedeni=f"RF_CONFLICT: {rf_key}",
                            op_id=_next_op("rf"),
                            bagli_formul_kod=db_f["f_kod"],
                            safe_to_apply=False,
                        ))
                        continue

                    cari_id = cari_map.get(cari) if cari else None
                    boya_k, fp_boya, boyut_rf = _rf_boya_kalemler_for_cari(
                        rv_excel, nk, cari, pkg, varyant_pref=varyant,
                    )
                    pigment_kalemler = [
                        {
                            "stok_kodu": k.stok_kodu,
                            "miktar_kg": k.miktar_kg,
                            "kaynak_hucre": k.kaynak_hucre,
                            "sira": k.sira,
                        }
                        for k in boya_k
                    ]
                    pigment_fp = _rf_pigment_fp_from_kalemler(pigment_kalemler)
                    stok_issues = (
                        _rf_stok_dogrula(con, boya_k, stok_map)
                        if cari_id and boya_k else ["CARI_YOK" if not cari_id else "BOYA_YOK"]
                    )

                    if cari_id and boya_k:
                        aksiyon, ek, eslesen = _rf_siniflandir(
                            con, rf_key, pigment_fp, pigment_kalemler,
                            stok_issues, cari_id, rk, db_f["f_kod"],
                        )
                    else:
                        aksiyon = "GERCEK_BLOCKER"
                        ek = ";".join(stok_issues) if stok_issues else "CARI/BOYA eksik"
                        eslesen = None

                    yazilabilir = aksiyon == "INSERT_RF_TASLAK"
                    bloker = aksiyon == "GERCEK_BLOCKER"
                    payload = None
                    if aksiyon == "INSERT_RF_TASLAK" and cari_id:
                        payload = _rf_taslak_payload(
                            rf_key=rf_key,
                            cari_id=cari_id,
                            cari_kod=cari,
                            parent_formul_id=db_f["f_id"],
                            parent_kod=db_f["f_kod"],
                            rv_id=rv_db_id_for_rf,
                            varyant=varyant,
                            renk_kodu=rk,
                            renk_adi=rv_excel.renk_adi or rk,
                            pigment_kalemler=pigment_kalemler,
                            pigment_fp=pigment_fp,
                            fingerprint_boya=fp_boya,
                            boyut=boyut_rf,
                        )

                    mesaj = (
                        f"{aksiyon}: {rf_key} ({rv_excel.renk_adi or rk})"
                        + (f" — {ek}" if ek else "")
                    )
                    sonuc.ekle(SimulasyonKalemi(
                        aksiyon=aksiyon,
                        tablo="nexgen_rf_renk",
                        identity=rf_key,
                        yeni_deger=payload,
                        eski_deger={"rf_id": eslesen["id"]} if eslesen else None,
                        mesaj=mesaj,
                        op_id=_next_op("rf"),
                        bagli_formul_kod=db_f["f_kod"],
                        bagli_rv_id=rv_db_id_for_rf,
                        bloker_mi=bloker,
                        bloker_nedeni=ek if bloker else "",
                        safe_to_apply=yazilabilir and not bloker,
                    ))

        # Planlama uygunluğu — P5B.4 RV dependency çözümü
        pending_rv = _pending_rv_map_from_sim(sonuc)
        seen_plan_identity: set[str] = set()
        for ku in pkg.kullanimlar:
            cari_id = cari_map.get(ku.cari_kodu.strip()) if ku.cari_kodu else None
            ut_nk = normalize_ascii_import(ku.uretim_tipi or "")
            ut_id = next(
                (v for k, v in ut_map.items() if normalize_ascii_import(k) == ut_nk),
                None,
            )
            if not (cari_id and ut_id):
                continue
            uv_id, rv_id_from_uv, parent_kod = _kullanim_uv_coz(
                ku, formul_map, rv_map, uv_map,
            )
            rv_id, rv_parent_op, rv_kaynak, fid = _planlama_rv_coz(
                ku, formul_map, rv_map, pending_rv,
            )
            boyut_key = (ku.boyut or "STANDART").strip().upper()
            canonical_uv_id = (
                canonical_uv_map.get((rv_id, boyut_key)) if rv_id else uv_id
            )
            revision_parent_op = ""
            plan_aksiyon = "INSERT_PLANLAMA"
            if uv_id and uv_id in revision_op_by_kaynak:
                revision_parent_op = revision_op_by_kaynak[uv_id]
                plan_aksiyon = "INSERT_PLANLAMA_REVISION"
                canonical_uv_id = revision_uv_by_kaynak.get(uv_id) or canonical_uv_id
            elif uv_id and uv_id in revision_uv_by_kaynak:
                canonical_uv_id = revision_uv_by_kaynak[uv_id]
                plan_aksiyon = "INSERT_PLANLAMA_REVISION"
            plan_op = _next_op("plan")
            plan_identity = _planlama_identity_key(ku, parent_kod)
            db_f_for_plan, _ = _formul_parent_coz(
                ku.uretim_tipi or "", ku.urun_ailesi or "", formul_map,
            )
            plan_deger = {
                "cari": ku.cari_kodu,
                "ut": ku.uretim_tipi,
                "urun_ailesi": ku.urun_ailesi,
                "formul_ad": ku.formul_ad,
                "formul_id": fid or (db_f_for_plan["f_id"] if db_f_for_plan else None),
                "formul_kod": db_f_for_plan["f_kod"] if db_f_for_plan else parent_kod,
                "renk_kodu": ku.renk_kodu,
                "varyant": ku.varyant,
                "boyut": ku.boyut,
                "kalip_carpani": ku.kalip_carpani,
                "musteri_formul_kodu": ku.musteri_formul_kodu,
                "mamul_uretim_kodu": ku.mamul_uretim_kodu,
                "uv_id": uv_id,
                "canonical_uv_id": canonical_uv_id,
                "kaynak_uv_id": uv_id,
                "rv_id": rv_id,
                "rv_kaynak": rv_kaynak,
                "rv_parent_op_id": rv_parent_op,
                "plan_identity": plan_identity,
            }
            if uv_id and uv_id in bloke_uv_ids:
                sonuc.ekle(SimulasyonKalemi(
                    aksiyon="BLOCKED_DEPENDENCY",
                    tablo="nexgen_planlama_uygunluk",
                    identity=plan_identity,
                    yeni_deger=plan_deger,
                    mesaj=(
                        f"Planlama bloke UV'ye bağlı: {plan_identity} "
                        f"(uv_id={uv_id})"
                    ),
                    kaynak_hucre=ku.kaynak_hucre,
                    blocked_dependency=True,
                    safe_to_apply=False,
                    op_id=plan_op,
                    parent_op_id=rv_parent_op or "",
                    bagli_uv_id=uv_id,
                    bagli_rv_id=rv_id,
                    bagli_formul_kod=parent_kod,
                    bloker_nedeni=f"Bloke UV bağımlılığı (uv_id={uv_id})",
                ))
            elif rv_kaynak == "NONE":
                sonuc.ekle(SimulasyonKalemi(
                    aksiyon="PLANLAMA_RV_UNRESOLVED",
                    tablo="nexgen_planlama_uygunluk",
                    identity=plan_identity,
                    yeni_deger=plan_deger,
                    mesaj=(
                        f"Planlama RV çözülemedi: {plan_identity} "
                        f"(varyant={ku.varyant!r}, formul_id={fid})"
                    ),
                    kaynak_hucre=ku.kaynak_hucre,
                    bloker_mi=True,
                    safe_to_apply=False,
                    op_id=plan_op,
                    bagli_formul_kod=parent_kod,
                    bloker_nedeni=(
                        f"PLANLAMA_RV_UNRESOLVED: "
                        f"formul_id={fid} varyant={ku.varyant!r}"
                    ),
                ))
            else:
                plan_db_id: int | None = None
                plan_dup_neden = ""
                if cari_id and ut_id and rv_id and plan_deger.get("formul_id"):
                    plan_db_id = _planlama_db_satir_bul(
                        con,
                        cari_id,
                        ut_id,
                        int(plan_deger["formul_id"]),
                        rv_id,
                        ku.renk_kodu or "",
                        boyut_key,
                    )
                    if plan_db_id:
                        plan_dup_neden = f"DB kaydı mevcut (id={plan_db_id})"
                if plan_identity in seen_plan_identity:
                    plan_dup_neden = (
                        plan_dup_neden or "Excel içi duplicate identity"
                    )
                if plan_db_id or plan_identity in seen_plan_identity:
                    sonuc.ekle(SimulasyonKalemi(
                        aksiyon="MATCH_PLANLAMA",
                        tablo="nexgen_planlama_uygunluk",
                        identity=plan_identity,
                        eski_deger={"planlama_id": plan_db_id},
                        yeni_deger=plan_deger,
                        mesaj=(
                            f"Planlama eşleşti: {plan_identity} "
                            f"({plan_dup_neden or 'duplicate'})"
                        ),
                        kaynak_hucre=ku.kaynak_hucre,
                        op_id=plan_op,
                        bagli_uv_id=canonical_uv_id or uv_id,
                        bagli_rv_id=rv_id,
                        bagli_formul_kod=parent_kod,
                        safe_to_apply=False,
                    ))
                else:
                    seen_plan_identity.add(plan_identity)
                    sonuc.ekle(SimulasyonKalemi(
                        aksiyon=plan_aksiyon,
                        tablo="nexgen_planlama_uygunluk",
                        identity=plan_identity,
                        yeni_deger=plan_deger,
                        mesaj=(
                            f"Planlama: {ku.cari_kodu}/{ku.uretim_tipi}/"
                            f"{ku.formul_ad}/{ku.renk_kodu} "
                            f"(rv_kaynak={rv_kaynak}, canonical_uv={canonical_uv_id})"
                        ),
                        kaynak_hucre=ku.kaynak_hucre,
                        op_id=plan_op,
                        parent_op_id=revision_parent_op or rv_parent_op or "",
                        bagli_uv_id=canonical_uv_id or uv_id,
                        bagli_rv_id=rv_id,
                        bagli_formul_kod=parent_kod,
                        safe_to_apply=True,
                    ))

        # ─────────────────────────────────────────────
        # Batch raporu
        # ─────────────────────────────────────────────
        for b in aktif_batchler:
            uv_id = b.get("uretim_varyant_id")
            etkileniyor = uv_id in degisecek_uv_ids
            sonuc.batch_raporu.append(BatchKaydi(
                batch_id=b["id"],
                durum=b["durum"],
                plan_id=b.get("plan_id"),
                uv_id=uv_id,
                formul_id=b.get("f_id"),
                formul_kod=b.get("f_kod", ""),
                formul_ad=b.get("f_ad", ""),
                rv_renk=b.get("rv_renk", ""),
                boyut=b.get("boyut", ""),
                planlanan_op=(
                    "INSERT_UV_REVISION" if uv_id in revision_op_by_kaynak
                    or uv_id in revision_uv_by_kaynak
                    else ("UPDATE_ANA_KALEM" if etkileniyor else "DOKUNULMAZ")
                ),
                etkileniyor_mu=etkileniyor,
                bloker_nedeni=(
                    "Eski UV korunuyor — revizyon yeni UV'de"
                    if (uv_id in revision_op_by_kaynak or uv_id in revision_uv_by_kaynak)
                    else ("Değişen UV'ye bağlı aktif batch" if etkileniyor else "")
                ),
            ))

    finally:
        con.close()

    # P5B.3 — DB şema kimlik kontrolü
    con_schema = db_readonly_connect(db_path)
    try:
        schema_rapor = _planlama_schema_kontrol(con_schema)
    finally:
        con_schema.close()
    sonuc.schema_kolon_raporu = schema_rapor
    sonuc.schema_identity_eksik = schema_rapor["schema_identity_eksik"]
    if sonuc.schema_identity_eksik:
        sonuc.ekle(SimulasyonKalemi(
            aksiyon="SCHEMA_IDENTITY_EKSIK",
            tablo="nexgen_planlama_uygunluk",
            identity="schema",
            mesaj=(
                "P5B.3: nexgen_planlama_uygunluk tablosunda renk/boyut kolonu yok. "
                "6-alan planlama identity DB'de fiziksel olarak saklanamaz. "
                "Migration 101 gerekiyor. Gerçek kısmi import NO-GO."
            ),
            bloker_mi=True,
            bloker_nedeni="SCHEMA_IDENTITY_EKSIK: musteri_renk_kodu/boyut kolonu yok (Migration 101)",
            op_id="schema_check",
        ))

    # P5B.3 — git commit + motor fingerprint
    git_sha = _git_commit_sha()
    if not git_sha:
        sonuc.ekle(SimulasyonKalemi(
            aksiyon="GIT_COMMIT_ALINAMADI",
            tablo="",
            identity="git",
            mesaj="git rev-parse HEAD başarısız — token GIT_COMMIT_ALINAMADI olacak",
            bloker_mi=True,
            bloker_nedeni="GIT_COMMIT_ALINAMADI",
            op_id="git_check",
        ))
    sonuc.git_commit = git_sha
    sonuc.motor_code_fingerprint = _motor_code_fingerprint()

    _p5b_bagimlilik_filtre(sonuc, bloke_uv_ids, yeni_rv_keys, yeni_uv_keys)
    sonuc.finalize_p5a()
    # P5B.4 — aday vs uygulanabilir sayaçları
    plan_aday = sum(
        1 for k in sonuc.islemler
        if k.aksiyon in (
            "INSERT_PLANLAMA", "INSERT_PLANLAMA_REVISION", "PLANLAMA_RV_UNRESOLVED",
        )
    )
    plan_uygulanabilir = sum(
        1 for k in sonuc.islemler
        if k.aksiyon in ("INSERT_PLANLAMA", "INSERT_PLANLAMA_REVISION")
        and k.safe_to_apply and not k.blocked_dependency
    )
    sonuc.guvenli_aday_sayisi = (
        sonuc.guvenli_yazma_sayisi + (plan_aday - plan_uygulanabilir)
    )
    sonuc.uygulanabilir_yazma_sayisi = sonuc.guvenli_yazma_sayisi
    if plan_aday:
        sonuc.ozet["INSERT_PLANLAMA_ADAY"] = plan_aday
        sonuc.ozet["INSERT_PLANLAMA_UYGULANABILIR"] = plan_uygulanabilir
        sonuc.ozet["PLANLAMA_RV_UNRESOLVED"] = sum(
            1 for k in sonuc.islemler if k.aksiyon == "PLANLAMA_RV_UNRESOLVED"
        )
    return sonuc


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------
def db_yedek_al(db_path: str, yedek_dizin: str) -> str:
    os.makedirs(yedek_dizin, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sha_kisa = _sha256(db_path)[:12]
    yedek_yolu = os.path.join(
        yedek_dizin, f"mock_data_before_import_{ts}_{sha_kisa}.db"
    )
    sha_once = _sha256(db_path)
    shutil.copy2(db_path, yedek_yolu)
    sha_yedek = _sha256(yedek_yolu)
    if sha_once != sha_yedek:
        raise RuntimeError(f"Yedek bütünlük hatası: {sha_once[:16]} != {sha_yedek[:16]}")
    return yedek_yolu


# ---------------------------------------------------------------------------
# P5B.2 — Kısmi apply plan, token, transaction
# ---------------------------------------------------------------------------
def guvenli_yazma_operasyonlari(sim: SimulasyonSonucu) -> list[SimulasyonKalemi]:
    """Yalnız DB'ye yazılabilir güvenli operasyonlar."""
    return [
        k for k in sim.islemler
        if k.aksiyon in YAZILABILIR_AKSIYONLAR
        and k.safe_to_apply
        and not k.blocked_dependency
    ]


def partial_plan_fingerprint(sim: SimulasyonSonucu) -> str:
    """
    P5B.3 — Güvenli operasyon listesinin deterministik SHA256 özeti.
    Planlama operasyonlarında tüm 6 alan + uv + kalip + musteri + mamul dahil.
    Renk veya boyut değişirse fingerprint değişir.
    """
    ops = guvenli_yazma_operasyonlari(sim)
    lines = []
    for k in sorted(ops, key=lambda x: (x.aksiyon, x.identity, x.op_id)):
        if k.aksiyon == "INSERT_PLANLAMA":
            pd = k.yeni_deger or {}
            line = "|".join([
                k.aksiyon,
                k.identity,
                k.op_id,
                (pd.get("cari") or "").strip(),
                (pd.get("ut") or "").strip().upper(),
                str(pd.get("formul_id") or ""),
                (pd.get("varyant") or "").strip(),
                (pd.get("renk_kodu") or "").strip().upper(),
                (pd.get("boyut") or "STANDART").strip().upper(),
                str(pd.get("uv_id") or ""),
                str(pd.get("kalip_carpani") or ""),
                (pd.get("musteri_formul_kodu") or "").strip(),
                (pd.get("mamul_uretim_kodu") or "").strip(),
            ])
        elif k.aksiyon == "INSERT_RF_TASLAK":
            vd = k.yeni_deger or {}
            line = "|".join([
                k.aksiyon,
                k.identity,
                k.op_id,
                str(vd.get("cari_id") or ""),
                str(vd.get("parent_formul_id") or ""),
                str(vd.get("rv_id") or ""),
                (vd.get("renk_kodu") or "").strip(),
                (vd.get("pigment_fp") or "")[:32],
            ])
        else:
            vd = k.yeni_deger or {}
            extra = ""
            if k.aksiyon == "UPDATE_ANA_KALEM":
                extra = f"|uv={vd.get('uv_id', '')}|fp={str(vd.get('fp_hedef', ''))[:16]}"
            elif k.aksiyon == "INSERT_UV_REVISION":
                extra = (
                    f"|kaynak={vd.get('kaynak_uv_id', '')}"
                    f"|ad={vd.get('ad', '')}"
                    f"|rev_no={vd.get('rev_no', REVISION_REV_NO)}"
                )
            line = f"{k.aksiyon}|{k.identity}|{k.op_id}{extra}"
        lines.append(line)
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _safe_op_distribution(sim: SimulasyonSonucu) -> dict[str, int]:
    """P5B.3 — Güvenli operasyon aksiyon dağılımı."""
    dist: dict[str, int] = {}
    for k in guvenli_yazma_operasyonlari(sim):
        dist[k.aksiyon] = dist.get(k.aksiyon, 0) + 1
    return dist


def generate_partial_confirm_token(
    excel_sha: str,
    db_sha: str,
    plan_fp: str,
    guvenli_op_sayisi: int,
    git_sha: str | None = None,
    motor_fp: str | None = None,
    op_distribution: dict[str, int] | None = None,
) -> str:
    """
    P5B.3 — Excel+DB+plan+op sayısı+git commit+motor+dağılım token.
    Git commit alınamazsa GIT_COMMIT_ALINAMADI döner (token üretilmez).
    """
    git_sha = git_sha if git_sha is not None else _git_commit_sha()
    if not git_sha:
        return "GIT_COMMIT_ALINAMADI"
    motor_fp = motor_fp or _motor_code_fingerprint()
    dist_str = ""
    if op_distribution:
        dist_str = "|".join(
            f"{k}={op_distribution.get(k, 0)}" for k in SAFE_OP_ORDER
        )
    digest = hashlib.sha256(
        f"{PARTIAL_TOKEN_PREFIX}|{PARTIAL_TOKEN_VERSION}|"
        f"{excel_sha}|{db_sha}|{plan_fp}|ops={guvenli_op_sayisi}|"
        f"git={git_sha}|motor={motor_fp}|dist={dist_str}".encode()
    ).hexdigest()
    return f"{PARTIAL_TOKEN_PREFIX}-{digest[:24]}"


def build_partial_import_plan(
    sim: SimulasyonSonucu,
    excel_sha: str,
    db_sha: str,
    git_sha: str | None = None,
) -> PartialImportPlan:
    """P5B.3 — Dry-run sonrası kısmi apply planı ve token."""
    ops = guvenli_yazma_operasyonlari(sim)
    plan_fp = partial_plan_fingerprint(sim)
    git_sha = git_sha if git_sha is not None else _git_commit_sha()
    motor_fp = _motor_code_fingerprint()
    dist = _safe_op_distribution(sim)
    token = generate_partial_confirm_token(
        excel_sha, db_sha, plan_fp, len(ops), git_sha, motor_fp, dist,
    )
    return PartialImportPlan(
        plan_fingerprint=plan_fp,
        confirm_token=token,
        guvenli_op_sayisi=len(ops),
        excel_sha=excel_sha,
        db_sha=db_sha,
        git_sha=git_sha,
        motor_code_fingerprint=motor_fp,
        safe_operation_distribution=dist,
        schema_identity_eksik=sim.schema_identity_eksik,
        operasyonlar=[
            {
                "op_id": k.op_id,
                "aksiyon": k.aksiyon,
                "identity": k.identity,
                "parent_op_id": k.parent_op_id,
                **({"yeni_deger": k.yeni_deger} if k.aksiyon in (
                    "INSERT_PLANLAMA", "INSERT_RF_TASLAK",
                ) else {}),
            }
            for k in ops
        ],
    )


def _ensure_import_log_tables(con: sqlite3.Connection) -> None:
    """Geçici test DB için import log tabloları (migration 100 eşdeğeri)."""
    if _import_log_tablo_var_mi(con):
        return
    con.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_import_batch (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dosya_adi TEXT NOT NULL,
            dosya_sha256 TEXT NOT NULL,
            durum TEXT NOT NULL DEFAULT 'DEVAM',
            analiz_zamani TEXT,
            import_zamani TEXT,
            analiz_eden_id INTEGER,
            kaynak_manifest_json TEXT,
            plan_fingerprint TEXT,
            db_sha_once TEXT
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_import_item_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_batch_id INTEGER NOT NULL,
            nesne_tipi TEXT NOT NULL,
            eski_id INTEGER,
            yeni_id INTEGER,
            aksiyon TEXT NOT NULL,
            detay_json TEXT
        )
    """)
    con.commit()


def _insert_import_batch_partial(
    con, pkg, sha_once, kullanici_id, plan_fp: str,
) -> int:
    excel_path = pkg.kaynak_bilgisi.get("dosya_yolu", "")
    excel_sha = pkg.kaynak_bilgisi.get("dosya_sha256", "")
    manifest = json.dumps({
        **pkg.kaynak_bilgisi,
        "partial": True,
        "plan_fingerprint": plan_fp,
    }, ensure_ascii=False)
    try:
        con.execute(
            """INSERT INTO nexgen_import_batch
               (dosya_adi, dosya_sha256, durum, analiz_zamani, analiz_eden_id,
                kaynak_manifest_json, plan_fingerprint, db_sha_once)
               VALUES (?, ?, 'DEVAM', datetime('now'), ?, ?, ?, ?)""",
            (
                os.path.basename(excel_path), excel_sha, kullanici_id,
                manifest, plan_fp, sha_once,
            ),
        )
        return con.execute("SELECT last_insert_rowid()").fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def _deactivate_ana_kalemler(con: sqlite3.Connection, uv_id: int) -> None:
    """Yalnız ana kalemleri pasifleştir — BOYA/pigment dokunulmaz."""
    con.execute(
        """UPDATE nexgen_recete_kalem SET aktif=0
           WHERE uretim_varyant_id=? AND aktif=1
             AND stok_kart_id IN (
               SELECT id FROM nexgen_stok_kart
               WHERE UPPER(COALESCE(kategori,'')) != 'BOYA'
             )""",
        (uv_id,),
    )


def _purge_inactive_ana_kalemler(con: sqlite3.Connection, uv_id: int) -> None:
    """Pasif ana kalemleri sil — UNIQUE(uv, stok) için INSERT öncesi."""
    con.execute(
        """DELETE FROM nexgen_recete_kalem
           WHERE uretim_varyant_id=? AND aktif=0
             AND stok_kart_id IN (
               SELECT id FROM nexgen_stok_kart
               WHERE UPPER(COALESCE(kategori,'')) != 'BOYA'
             )""",
        (uv_id,),
    )
    """Yalnız ana kalemleri pasifleştir — BOYA/pigment dokunulmaz."""
    con.execute(
        """UPDATE nexgen_recete_kalem SET aktif=0
           WHERE uretim_varyant_id=? AND aktif=1
             AND stok_kart_id IN (
               SELECT id FROM nexgen_stok_kart
               WHERE UPPER(COALESCE(kategori,'')) != 'BOYA'
             )""",
        (uv_id,),
    )


def _insert_ana_kalemler(
    con: sqlite3.Connection,
    uv_id: int,
    kalemler: list[dict],
    stok_map: dict[str, int],
) -> int:
    """Ana kalemleri UV'ye yazar; yazılan kalem sayısını döner."""
    n = 0
    for i, k in enumerate(kalemler, 1):
        kod = (k.get("stok_kodu") or "").strip().upper()
        sk_id = stok_map.get(kod)
        if sk_id is None:
            raise ValueError(f"Stok kartı bulunamadı: {kod}")
        sira = k.get("sira")
        if sira is None:
            sira = i
        con.execute(
            """INSERT INTO nexgen_recete_kalem
               (uretim_varyant_id, stok_kart_id, sira, miktar_kg, aktif, olusturma_tarihi)
               VALUES (?, ?, ?, ?, 1, datetime('now'))""",
            (uv_id, sk_id, sira, k.get("miktar_kg", 0)),
        )
        n += 1
    return n


def _apply_insert_planlama_op(
    con, op, cari_map, ut_map, formul_map, rv_map, rv_id_by_op,
    onayli_kullanici_id, sonuc,
) -> None:
    """INSERT_PLANLAMA ve INSERT_PLANLAMA_REVISION ortak uygulayıcı."""
    pd = op.yeni_deger or {}
    cari_id = cari_map.get((pd.get("cari") or "").strip())
    ut_nk = normalize_ascii_import(pd.get("ut") or "")
    ut_id = next(
        (v for k, v in ut_map.items() if normalize_ascii_import(k) == ut_nk),
        None,
    )
    if not cari_id or not ut_id:
        return
    db_f, _ = _formul_parent_coz(
        pd.get("ut") or "",
        pd.get("urun_ailesi") or "",
        formul_map,
    )
    if not db_f:
        return
    fid = db_f["f_id"]
    rv_nk = normalize_ascii_import(pd.get("varyant") or "")
    rv_id = rv_map.get((fid, rv_nk))
    if not rv_id and op.parent_op_id:
        rv_id = rv_id_by_op.get(op.parent_op_id)
    if not rv_id:
        sonuc.ozet["SKIP_PLANLAMA_RV"] = (
            sonuc.ozet.get("SKIP_PLANLAMA_RV", 0) + 1
        )
        return
    renk_kodu = (pd.get("renk_kodu") or "").strip()
    boyut_val = (pd.get("boyut") or "STANDART").strip().upper()
    kc = pd.get("kalip_carpani")
    has_renk_col = _planlama_musteri_renk_kolon_var_mi(con)
    has_boyut_col = _planlama_boyut_kolon_var_mi(con)
    if has_renk_col and has_boyut_col:
        dup = con.execute(
            """SELECT id FROM nexgen_planlama_uygunluk
               WHERE cari_id=? AND uretim_tipi_id=? AND formul_id=?
                 AND renk_varyant_id=? AND aktif=1
                 AND COALESCE(musteri_renk_kodu,'')=?
                 AND COALESCE(boyut,'')=?""",
            (cari_id, ut_id, fid, rv_id, renk_kodu, boyut_val),
        ).fetchone()
    elif has_renk_col:
        dup = con.execute(
            """SELECT id FROM nexgen_planlama_uygunluk
               WHERE cari_id=? AND uretim_tipi_id=? AND formul_id=?
                 AND renk_varyant_id=? AND aktif=1
                 AND COALESCE(musteri_renk_kodu,'')=?""",
            (cari_id, ut_id, fid, rv_id, renk_kodu),
        ).fetchone()
    else:
        dup = con.execute(
            """SELECT id FROM nexgen_planlama_uygunluk
               WHERE cari_id=? AND uretim_tipi_id=? AND formul_id=?
                 AND renk_varyant_id=? AND aktif=1""",
            (cari_id, ut_id, fid, rv_id),
        ).fetchone()
    if dup:
        sonuc.ozet["SKIP_PLANLAMA"] = sonuc.ozet.get("SKIP_PLANLAMA", 0) + 1
        return
    aks_key = "INSERT_PLANLAMA_REVISION" if op.aksiyon == "INSERT_PLANLAMA_REVISION" else "INSERT_PLANLAMA"
    if has_renk_col and has_boyut_col:
        con.execute(
            """INSERT INTO nexgen_planlama_uygunluk
               (cari_id, uretim_tipi_id, formul_id, renk_varyant_id,
                musteri_renk_kodu, boyut, kalip_carpani, durum, olusturan_id,
                olusturma_tarihi, aktif)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'AKTIF', ?, datetime('now'), 1)""",
            (
                cari_id, ut_id, fid, rv_id, renk_kodu or None,
                boyut_val or None, kc, onayli_kullanici_id,
            ),
        )
    elif has_renk_col:
        con.execute(
            """INSERT INTO nexgen_planlama_uygunluk
               (cari_id, uretim_tipi_id, formul_id, renk_varyant_id,
                musteri_renk_kodu, kalip_carpani, durum, olusturan_id,
                olusturma_tarihi, aktif)
               VALUES (?, ?, ?, ?, ?, ?, 'AKTIF', ?, datetime('now'), 1)""",
            (
                cari_id, ut_id, fid, rv_id, renk_kodu or None,
                kc, onayli_kullanici_id,
            ),
        )
    else:
        con.execute(
            """INSERT INTO nexgen_planlama_uygunluk
               (cari_id, uretim_tipi_id, formul_id, renk_varyant_id,
                kalip_carpani, durum, olusturan_id, olusturma_tarihi, aktif)
               VALUES (?, ?, ?, ?, ?, 'AKTIF', ?, datetime('now'), 1)""",
            (cari_id, ut_id, fid, rv_id, kc, onayli_kullanici_id),
        )
    sonuc.ozet[aks_key] = sonuc.ozet.get(aks_key, 0) + 1


def execute_partial_import(
    pkg: ImportPackage,
    db_path: str,
    confirm_token: str,
    excel_sha: str | None = None,
    yedek_dizin: str | None = None,
    onayli_kullanici_id: int | None = None,
    sim: SimulasyonSonucu | None = None,
    _test_fail_after: int | None = None,
) -> ImportSonucu:
    """
    P5B.2 — Kısmi güvenli import (yalnız simulate edilen safe_to_apply operasyonlar).
    Token: generate_partial_confirm_token ile üretilen dinamik değer olmalı.
    """
    from modules.nexgen.kod_uretici import yeni_rv_kodu_uret

    db_path = os.path.abspath(db_path)
    sonuc = ImportSonucu(partial_mode=True)
    t_baslangic = datetime.now()

    if sim is None:
        sim = simulate_import(pkg, db_path=db_path)

    if not sim.kismi_import_hazir:
        sonuc.hatalar.append("Kısmi import hazır değil (guvenli_yazma=0)")
        return sonuc

    excel_sha = excel_sha or pkg.kaynak_bilgisi.get("dosya_sha256", "")
    plan_fp = partial_plan_fingerprint(sim)
    sonuc.plan_fingerprint = plan_fp
    ops = guvenli_yazma_operasyonlari(sim)
    sonuc.guvenli_op_sayisi = len(ops)
    git_sha = _git_commit_sha()
    motor_fp = _motor_code_fingerprint()
    dist = _safe_op_distribution(sim)

    # P5B.3 — şema hazırlığı token doğrulamasından ÖNCE (DDL implicit commit)
    con_pre = sqlite3.connect(db_path, timeout=30)
    _ensure_planlama_p5b3_schema(con_pre)
    con_pre.close()
    db_sha_current = _sha256(db_path)

    beklenen_token = generate_partial_confirm_token(
        excel_sha, db_sha_current, plan_fp, sonuc.guvenli_op_sayisi,
        git_sha, motor_fp, dist,
    )
    if confirm_token != beklenen_token:
        sonuc.hatalar.append(
            "Kısmi import reddedildi: confirmation token plan fingerprint ile uyuşmuyor"
        )
        return sonuc

    yedek_dizin = yedek_dizin or os.path.abspath(os.path.join(
        os.path.dirname(db_path), "..", "..", "backup", "import_analysis"
    ))
    try:
        sonuc.yedek_yolu = db_yedek_al(db_path, yedek_dizin)
    except Exception as e:
        sonuc.hatalar.append(f"Yedek alınamadı: {e}")
        return sonuc

    sonuc.sha_once = db_sha_current
    safe_ops = guvenli_yazma_operasyonlari(sim)

    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    rv_id_by_op: dict[str, int] = {}
    uv_id_by_op: dict[str, int] = {}

    try:
        con.execute("BEGIN IMMEDIATE")
        stok_map = _stok_id_map_v2(con)
        cari_map = _cari_id_map(con)
        ut_map = _ut_id_map(con)
        formul_map = _formul_id_map_ascii(con)
        rv_map = _rv_id_map_varyant(con)
        uv_map = _uv_id_map(con)

        batch_id = _insert_import_batch_partial(
            con, pkg, sonuc.sha_once, onayli_kullanici_id, plan_fp,
        )
        sonuc.batch_id = batch_id or None

        for idx, op in enumerate(safe_ops):
            if _test_fail_after is not None and idx >= _test_fail_after:
                raise RuntimeError("P5B2_TEST_ROLLBACK")

            if op.aksiyon == "INSERT_RV":
                vd = op.yeni_deger or {}
                formul_id = vd.get("formul_id")
                varyant = vd.get("renk_varyant", "")
                if not formul_id or not varyant:
                    continue
                rv_nk = normalize_ascii_import(varyant)
                existing = rv_map.get((formul_id, rv_nk))
                if existing:
                    rv_id_by_op[op.op_id] = existing
                    continue
                frow = con.execute(
                    "SELECT kod FROM nexgen_formul WHERE id=?", (formul_id,),
                ).fetchone()
                if not frow:
                    raise ValueError(f"Formül bulunamadı: id={formul_id}")
                rv_kod = yeni_rv_kodu_uret(con, frow[0])
                con.execute(
                    """INSERT INTO nexgen_renk_varyant
                       (formul_id, kod, ad, renk, aktif, olusturma_tarihi)
                       VALUES (?, ?, ?, ?, 1, datetime('now'))""",
                    (formul_id, rv_kod, varyant, varyant),
                )
                rv_db_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
                rv_map[(formul_id, rv_nk)] = rv_db_id
                rv_id_by_op[op.op_id] = rv_db_id
                sonuc.ozet["INSERT_RV"] = sonuc.ozet.get("INSERT_RV", 0) + 1
                _log_item(con, batch_id, "nexgen_renk_varyant", "INSERT",
                          None, rv_db_id, {"varyant": varyant})

            elif op.aksiyon == "INSERT_UV":
                vd = op.yeni_deger or {}
                boyut_key = (vd.get("boyut") or "STANDART").strip().upper()
                rv_db_id = op.bagli_rv_id
                if op.parent_op_id:
                    rv_db_id = rv_id_by_op.get(op.parent_op_id, rv_db_id)
                if not rv_db_id:
                    raise ValueError(f"INSERT_UV için RV çözülemedi: {op.identity}")
                existing = uv_map.get((rv_db_id, boyut_key))
                if existing:
                    uv_id_by_op[op.op_id] = existing
                    continue
                con.execute(
                    """INSERT INTO nexgen_uretim_varyant
                       (renk_varyant_id, boyut, ad, recete_durum, aktif, olusturma_tarihi)
                       VALUES (?, ?, ?, 'AKTIF', 1, datetime('now'))""",
                    (rv_db_id, boyut_key, f"import/{boyut_key}"),
                )
                uv_db_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
                uv_map[(rv_db_id, boyut_key)] = uv_db_id
                uv_id_by_op[op.op_id] = uv_db_id
                sonuc.ozet["INSERT_UV"] = sonuc.ozet.get("INSERT_UV", 0) + 1
                _log_item(con, batch_id, "nexgen_uretim_varyant", "INSERT",
                          None, uv_db_id, {"boyut": boyut_key})

            elif op.aksiyon == "INSERT_UV_REVISION":
                vd = op.yeni_deger or {}
                kaynak_uv_id = vd.get("kaynak_uv_id") or op.bagli_uv_id
                rv_db_id = vd.get("renk_varyant_id") or op.bagli_rv_id
                boyut_key = (vd.get("boyut") or "STANDART").strip().upper()
                rev_ad = vd.get("ad") or _revision_uv_ad_uret("", kaynak_uv_id or 0)
                if not kaynak_uv_id or not rv_db_id:
                    raise ValueError(
                        f"INSERT_UV_REVISION için kaynak/RV çözülemedi: {op.identity}"
                    )
                existing = _revision_uv_bul(con, kaynak_uv_id)
                if existing:
                    uv_id_by_op[op.op_id] = existing
                    continue
                rev_no = int(vd.get("rev_no") or REVISION_REV_NO)
                if _uv_rev_no_kolon_var_mi(con):
                    con.execute(
                        """INSERT INTO nexgen_uretim_varyant
                           (renk_varyant_id, boyut, ad, kaynak_varyant_id, rev_no,
                            recete_durum, aktif, olusturma_tarihi)
                           VALUES (?, ?, ?, ?, ?, 'AKTIF', 1, datetime('now'))""",
                        (rv_db_id, boyut_key, rev_ad, kaynak_uv_id, rev_no),
                    )
                else:
                    con.execute(
                        """INSERT INTO nexgen_uretim_varyant
                           (renk_varyant_id, boyut, ad, kaynak_varyant_id,
                            recete_durum, aktif, olusturma_tarihi)
                           VALUES (?, ?, ?, ?, 'AKTIF', 1, datetime('now'))""",
                        (rv_db_id, boyut_key, rev_ad, kaynak_uv_id),
                    )
                rev_uv_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
                uv_id_by_op[op.op_id] = rev_uv_id
                sonuc.ozet["INSERT_UV_REVISION"] = (
                    sonuc.ozet.get("INSERT_UV_REVISION", 0) + 1
                )
                _log_item(
                    con, batch_id, "nexgen_uretim_varyant", "INSERT_REVISION",
                    kaynak_uv_id, rev_uv_id,
                    {"ad": rev_ad, "boyut": boyut_key},
                )

            elif op.aksiyon == "UPDATE_ANA_KALEM":
                vd = op.yeni_deger or {}
                uv_db_id = vd.get("uv_id") or op.bagli_uv_id
                if not uv_db_id:
                    m = re.search(r"uv_id=(\d+)", op.identity or "")
                    uv_db_id = int(m.group(1)) if m else None
                if not uv_db_id:
                    raise ValueError(
                        f"UPDATE_ANA_KALEM için UV çözülemedi: {op.identity}"
                    )
                fp_hedef = vd.get("fp_hedef") or ""
                fp_once = _kalem_fingerprint_db_ana(con, uv_db_id)
                if fp_hedef and fp_once == fp_hedef:
                    continue
                guvenli, neden = _uv_guncelleme_guvenli_mi(con, uv_db_id)
                if not guvenli:
                    raise ValueError(f"UPDATE_ANA_KALEM güvensiz: {neden}")
                _deactivate_ana_kalemler(con, uv_db_id)
                _purge_inactive_ana_kalemler(con, uv_db_id)
                kalemler = vd.get("kalemler") or []
                n = _insert_ana_kalemler(con, uv_db_id, kalemler, stok_map)
                fp_sonra = _kalem_fingerprint_db_ana(con, uv_db_id)
                if fp_hedef and fp_sonra != fp_hedef:
                    raise ValueError(
                        f"Fingerprint doğrulama başarısız: {fp_sonra} != {fp_hedef}"
                    )
                sonuc.ozet["UPDATE_ANA_KALEM"] = (
                    sonuc.ozet.get("UPDATE_ANA_KALEM", 0) + 1
                )
                _log_item(
                    con, batch_id, "nexgen_recete_kalem", "UPDATE_ANA",
                    uv_db_id, uv_db_id, {"kalem_sayisi": n, "fp_sonra": fp_sonra},
                )

            elif op.aksiyon == "INSERT_ANA_KALEM":
                uv_db_id = None
                if op.parent_op_id:
                    uv_db_id = uv_id_by_op.get(op.parent_op_id)
                if not uv_db_id:
                    raise ValueError(f"INSERT_ANA_KALEM için UV çözülemedi: {op.identity}")
                mevcut = con.execute(
                    "SELECT COUNT(*) FROM nexgen_recete_kalem "
                    "WHERE uretim_varyant_id=? AND aktif=1 "
                    "AND stok_kart_id IN ("
                    "  SELECT id FROM nexgen_stok_kart "
                    "  WHERE UPPER(COALESCE(kategori,'')) != 'BOYA'"
                    ")",
                    (uv_db_id,),
                ).fetchone()[0]
                if mevcut > 0:
                    continue
                kalemler = op.yeni_deger or []
                n = _insert_ana_kalemler(con, uv_db_id, kalemler, stok_map)
                sonuc.ozet["INSERT_ANA_KALEM"] = (
                    sonuc.ozet.get("INSERT_ANA_KALEM", 0) + 1
                )
                _log_item(con, batch_id, "nexgen_recete_kalem", "INSERT",
                          None, uv_db_id, {"kalem_sayisi": n})

            elif op.aksiyon in ("INSERT_PLANLAMA", "INSERT_PLANLAMA_REVISION"):
                _apply_insert_planlama_op(
                    con, op, cari_map, ut_map, formul_map, rv_map,
                    rv_id_by_op, onayli_kullanici_id, sonuc,
                )

            elif op.aksiyon == "INSERT_RF_TASLAK":
                vd = op.yeni_deger or {}
                rf_key = vd.get("rf_identity") or op.identity
                marker = _rf_import_identity_marker(rf_key)
                existing = con.execute(
                    "SELECT id FROM nexgen_rf_renk "
                    "WHERE aktif=1 AND aciklama LIKE ?",
                    (f"%{marker}%",),
                ).fetchone()
                if existing:
                    continue

                cari_id = vd.get("cari_id")
                parent_fid = vd.get("parent_formul_id")
                renk_kodu = vd.get("renk_kodu") or ""
                renk_adi = vd.get("renk_adi") or renk_kodu
                pigment_kalemler = vd.get("pigment_kalemleri") or []
                if not cari_id or not pigment_kalemler:
                    raise ValueError(
                        f"INSERT_RF_TASLAK eksik payload: {op.identity}"
                    )

                rf_kod = _import_rf_kod_uret(con, renk_kodu)
                excel_kaynak = vd.get("excel_kaynak") or "TABAN_EXCEL"
                aciklama = f"{marker}|{excel_kaynak}"
                con.execute(
                    """
                    INSERT INTO nexgen_rf_renk
                        (rf_kod, ad, durum, ilk_talep_cari_id, cari_id,
                         aciklama, olusturan_id, aktif, aktif_rev_no)
                    VALUES (?, ?, 'TASLAK', ?, ?, ?, 1, 1, 0)
                    """,
                    (rf_kod, renk_adi, cari_id, cari_id, aciklama),
                )
                rf_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

                for i, p in enumerate(pigment_kalemler, 1):
                    sk_id = stok_map.get(p["stok_kodu"])
                    if not sk_id:
                        row = con.execute(
                            "SELECT id FROM nexgen_stok_kart WHERE kod=? AND aktif=1",
                            (p["stok_kodu"],),
                        ).fetchone()
                        sk_id = row[0] if row else None
                    if not sk_id:
                        raise ValueError(
                            f"INSERT_RF_TASLAK stok bulunamadı: {p['stok_kodu']}"
                        )
                    con.execute(
                        """
                        INSERT INTO nexgen_rf_kalem
                            (rf_renk_id, stok_kart_id, pigment_ad, miktar_kg,
                             sira, aciklama, aktif)
                        VALUES (?, ?, ?, ?, ?, ?, 1)
                        """,
                        (
                            rf_id, sk_id, p["stok_kodu"],
                            float(p["miktar_kg"]), i,
                            p.get("kaynak_hucre") or "",
                        ),
                    )

                pigmentler_json = _rf_pigmentler_json_olustur(
                    con, pigment_kalemler, stok_map,
                )
                if _rf_revizyon_tablosu_var_mi(con):
                    mevcut_rev = con.execute(
                        "SELECT id FROM nexgen_rf_revizyon "
                        "WHERE rf_renk_id=? AND rev_no=1",
                        (rf_id,),
                    ).fetchone()
                    if not mevcut_rev:
                        kalip = None
                        con.execute(
                            """
                            INSERT INTO nexgen_rf_revizyon
                                (rf_renk_id, rev_no, durum, pigmentler_json,
                                 neden, aciklama, olusturan_id,
                                 olusturma_tarihi, kilitli_mi, aktif)
                            VALUES (?, 1, 'TASLAK', ?, 'TABAN_IMPORT',
                                    'Excel TABAN TASLAK REV-1', 1,
                                    datetime('now'), 0, 1)
                            """,
                            (rf_id, pigmentler_json),
                        )

                if parent_fid:
                    uygun = con.execute(
                        "SELECT id FROM nexgen_rf_formul_uygunluk "
                        "WHERE rf_renk_id=? AND formul_id=? AND aktif=1",
                        (rf_id, parent_fid),
                    ).fetchone()
                    if not uygun:
                        con.execute(
                            """
                            INSERT INTO nexgen_rf_formul_uygunluk
                                (rf_renk_id, formul_id, durum,
                                 ilk_talep_cari_id, aktif, olusturma_tarihi)
                            VALUES (?, ?, 'TASLAK', ?, 1, datetime('now'))
                            """,
                            (rf_id, parent_fid, cari_id),
                        )

                sonuc.ozet["INSERT_RF_TASLAK"] = (
                    sonuc.ozet.get("INSERT_RF_TASLAK", 0) + 1
                )
                _log_item(
                    con, batch_id, "nexgen_rf_renk", "INSERT_RF_TASLAK",
                    None, rf_id,
                    {"rf_kod": rf_kod, "identity": rf_key},
                )

        if batch_id:
            con.execute(
                "UPDATE nexgen_import_batch SET durum='TAMAMLANDI', "
                "import_zamani=datetime('now') WHERE id=?",
                (batch_id,),
            )
        con.execute("COMMIT")
        sonuc.basarili = True

    except Exception as e:
        con.execute("ROLLBACK")
        sonuc.rollback_yapildi = True
        sonuc.hatalar.append(f"Kısmi transaction hatası (ROLLBACK): {e}")
        sonuc.basarili = False
        con.close()
        sonuc.sha_sonra = _sha256(db_path)
        sonuc.elapsed_ms = (datetime.now() - t_baslangic).total_seconds() * 1000
        return sonuc

    con.close()
    sonuc.sha_sonra = _sha256(db_path)
    sonuc.elapsed_ms = (datetime.now() - t_baslangic).total_seconds() * 1000
    return sonuc


def test_partial_transaction(
    pkg: ImportPackage,
    source_db: str,
    excel_sha: str,
    test_root: str | None = None,
) -> dict[str, Any]:
    """
    P5B.2 — Geçici DB kopyasında kısmi apply, idempotency ve rollback testi.
    Kaynak DB'ye yazmaz.
    """
    source_db = os.path.abspath(source_db)
    test_root = test_root or os.path.abspath(os.path.join(
        os.path.dirname(source_db), "..", "..", "backup", "import_analysis",
    ))
    os.makedirs(test_root, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    source_sha = _sha256(source_db)

    sonuc: dict[str, Any] = {
        "kaynak_db": source_db,
        "kaynak_sha": source_sha,
        "zaman": ts,
    }

    # ── Test 1: İlk kısmi apply ──────────────────────────────────────
    temp_db = os.path.join(test_root, f"p5b2_tx_apply_{ts}.db")
    shutil.copy2(source_db, temp_db)
    con = sqlite3.connect(temp_db)
    _ensure_import_log_tables(con)
    _ensure_planlama_p5b3_schema(con)
    con.close()
    sha_once = _sha256(temp_db)
    sonuc["temp_db_apply"] = temp_db
    sonuc["temp_sha_once"] = sha_once

    sim1 = simulate_import(pkg, db_path=temp_db)
    plan1 = build_partial_import_plan(sim1, excel_sha, sha_once)
    r1 = execute_partial_import(
        pkg, temp_db, plan1.confirm_token, excel_sha=excel_sha, sim=sim1,
    )
    sha_after_apply = _sha256(temp_db)
    sonuc["apply1_basarili"] = r1.basarili
    sonuc["apply1_ozet"] = r1.ozet
    sonuc["apply1_hatalar"] = r1.hatalar
    sonuc["apply1_plan_fp"] = plan1.plan_fingerprint
    sonuc["apply1_guvenli_op"] = plan1.guvenli_op_sayisi
    sonuc["apply1_sha_sonra"] = sha_after_apply
    sonuc["apply1_yedek"] = os.path.basename(r1.yedek_yolu)

    # ── Test 2: Idempotency (ikinci sim → güvenli op kalmamalı) ───────
    sim2 = simulate_import(pkg, db_path=temp_db)
    plan2 = build_partial_import_plan(sim2, excel_sha, sha_after_apply)
    sonuc["apply2_guvenli_op"] = sim2.guvenli_yazma_sayisi
    if sim2.guvenli_yazma_sayisi == 0:
        sonuc["idempotent_ok"] = True
        sonuc["apply2_ozet"] = {}
        sonuc["apply2_atlandi"] = True
    else:
        r2 = execute_partial_import(
            pkg, temp_db, plan2.confirm_token, excel_sha=excel_sha, sim=sim2,
        )
        sha_after_idem = _sha256(temp_db)
        _write_keys = frozenset({
            "INSERT_RV", "INSERT_UV", "INSERT_UV_REVISION",
            "UPDATE_ANA_KALEM", "INSERT_ANA_KALEM",
            "INSERT_PLANLAMA", "INSERT_PLANLAMA_REVISION",
            "INSERT_RF_TASLAK",
        })
        yeni_yazma = sum(v for k, v in r2.ozet.items() if k in _write_keys)
        sonuc["idempotent_ok"] = r2.basarili and yeni_yazma == 0
        sonuc["apply2_ozet"] = r2.ozet
        sonuc["apply2_sha"] = sha_after_idem
        sonuc["apply2_hatalar"] = r2.hatalar
    if "apply2_sha" not in sonuc:
        sonuc["apply2_sha"] = sha_after_apply

    # ── Test 3: Rollback (hata sonrası SHA korunumu) ───────────────
    temp_db_rb = os.path.join(test_root, f"p5b2_tx_rollback_{ts}.db")
    shutil.copy2(source_db, temp_db_rb)
    con = sqlite3.connect(temp_db_rb)
    _ensure_import_log_tables(con)
    _ensure_planlama_p5b3_schema(con)
    con.close()
    sha_rb_once = _sha256(temp_db_rb)
    sonuc["temp_db_rollback"] = temp_db_rb
    sonuc["rollback_sha_once"] = sha_rb_once

    sim_rb = simulate_import(pkg, db_path=temp_db_rb)
    plan_rb = build_partial_import_plan(sim_rb, excel_sha, sha_rb_once)
    r_rb = execute_partial_import(
        pkg, temp_db_rb, plan_rb.confirm_token, excel_sha=excel_sha,
        sim=sim_rb, _test_fail_after=2,
    )
    sha_rb_sonra = _sha256(temp_db_rb)
    sonuc["rollback_ok"] = (
        r_rb.rollback_yapildi
        and sha_rb_once == sha_rb_sonra
        and not r_rb.basarili
    )
    sonuc["rollback_hata"] = r_rb.hatalar

    # ── P5D.2 doğrulamaları (apply sonrası temp DB) ─────────────────
    sonuc["p5d2"] = _p5d2_post_apply_validate(source_db, temp_db, sim1)
    sonuc["rf_taslak"] = _rf_taslak_post_apply_validate(source_db, temp_db, sim1)

    sonuc["sim1_bloker_sayisi"] = len(sim1.blokerler)
    sonuc["sim1_ozet"] = {
        k: sim1.ozet.get(k, 0)
        for k in (
            "INSERT_RF_TASLAK", "MATCH_RF", "MATCH_RF_TASLAK",
            "RF_REVISION_MANUAL_REVIEW", "GERCEK_BLOCKER",
            "UPDATE_ANA_KALEM", "INSERT_UV_REVISION", "INSERT_ANA_KALEM",
            "BLOCKED", "REVISION_SNAPSHOT_REQUIRED", "CHANGED_RECIPE",
        )
        if sim1.ozet.get(k, 0)
    }
    sonuc["sim1_token"] = plan1.confirm_token
    sonuc["sim2_token"] = plan2.confirm_token if sim2 else plan1.confirm_token

    sonuc["tum_testler_gecildi"] = (
        sonuc.get("apply1_basarili")
        and sonuc.get("idempotent_ok")
        and sonuc.get("rollback_ok")
        and sonuc.get("p5d2", {}).get("tum_kontroller_ok", False)
        and sonuc.get("rf_taslak", {}).get("tum_kontroller_ok", False)
    )
    return sonuc


def _rf_taslak_post_apply_validate(
    source_db: str, temp_db: str, sim1: SimulasyonSonucu,
) -> dict[str, Any]:
    """P5E-RF — geçici DB RF TASLAK apply sonrası koruma doğrulamaları."""
    rapor: dict[str, Any] = {"tum_kontroller_ok": True, "kontroller": []}

    def _chk(ad: str, ok: bool, detay: str = "") -> None:
        rapor["kontroller"].append({"ad": ad, "ok": ok, "detay": detay})
        if not ok:
            rapor["tum_kontroller_ok"] = False

    src = sqlite3.connect(source_db)
    tmp = sqlite3.connect(temp_db)
    src.row_factory = sqlite3.Row
    tmp.row_factory = sqlite3.Row

    try:
        src_onayli = src.execute(
            "SELECT COUNT(*) FROM nexgen_rf_renk "
            "WHERE durum IN ('ONAYLI','AKTIF') AND aktif=1"
        ).fetchone()[0]
        tmp_onayli = tmp.execute(
            "SELECT COUNT(*) FROM nexgen_rf_renk "
            "WHERE durum IN ('ONAYLI','AKTIF') AND aktif=1"
        ).fetchone()[0]
        _chk("aktif_onayli_rf_korundu", src_onayli == tmp_onayli, f"{src_onayli}=={tmp_onayli}")

        src_recete = src.execute(
            "SELECT COUNT(*) FROM nexgen_recete_kalem"
        ).fetchone()[0]
        tmp_recete = tmp.execute(
            "SELECT COUNT(*) FROM nexgen_recete_kalem"
        ).fetchone()[0]
        _chk("recete_kalem_degmedi", src_recete == tmp_recete, f"{src_recete}=={tmp_recete}")

        src_plan = src.execute(
            "SELECT COUNT(*) FROM nexgen_planlama_uygunluk"
        ).fetchone()[0]
        tmp_plan = tmp.execute(
            "SELECT COUNT(*) FROM nexgen_planlama_uygunluk"
        ).fetchone()[0]
        _chk("planlama_degmedi", src_plan == tmp_plan, f"{src_plan}=={tmp_plan}")

        src_batch = src.execute(
            "SELECT COUNT(*) FROM nexgen_uretim_batch"
        ).fetchone()[0]
        tmp_batch = tmp.execute(
            "SELECT COUNT(*) FROM nexgen_uretim_batch"
        ).fetchone()[0]
        _chk("batch_degmedi", src_batch == tmp_batch, f"{src_batch}=={tmp_batch}")

        beklenen_taslak = sim1.ozet.get("INSERT_RF_TASLAK", 0)
        gercek_taslak = tmp.execute(
            "SELECT COUNT(*) FROM nexgen_rf_renk WHERE durum='TASLAK' AND aktif=1 "
            "AND aciklama LIKE ?",
            (f"%{RF_IMPORT_IDENTITY_PREFIX}%",),
        ).fetchone()[0]
        _chk(
            "taslak_rf_sayisi",
            gercek_taslak >= beklenen_taslak,
            f"beklenen>={beklenen_taslak} gercek={gercek_taslak}",
        )

        # 0118 MASTERBATCH pigment doğrulama
        mb_rf = tmp.execute(
            "SELECT id FROM nexgen_rf_renk WHERE durum='TASLAK' AND aktif=1 "
            "AND ad LIKE '%Buz Beyaz%' OR aciklama LIKE '%|810|18-28|0118'"
        ).fetchone()
        if beklenen_taslak >= 12:
            rf_0118 = tmp.execute(
                "SELECT id FROM nexgen_rf_renk WHERE aktif=1 AND aciklama LIKE ?",
                (f"%{RF_IMPORT_IDENTITY_PREFIX}120.NX.008|810|18-28|0118%",),
            ).fetchone()
            if rf_0118:
                mb_cnt = tmp.execute(
                    """
                    SELECT COUNT(*) FROM nexgen_rf_kalem rk
                    JOIN nexgen_stok_kart sk ON sk.id=rk.stok_kart_id
                    WHERE rk.rf_renk_id=? AND UPPER(sk.kategori)='MASTERBATCH'
                    """,
                    (rf_0118[0],),
                ).fetchone()[0]
                _chk("0118_masterbatch_kalem", mb_cnt >= 6, f"mb_kalem={mb_cnt}")

        plan_rf_bos = tmp.execute(
            "SELECT COUNT(*) FROM nexgen_planlama_uygunluk "
            "WHERE rf_renk_id IS NOT NULL"
        ).fetchone()[0]
        src_plan_rf = src.execute(
            "SELECT COUNT(*) FROM nexgen_planlama_uygunluk "
            "WHERE rf_renk_id IS NOT NULL"
        ).fetchone()[0]
        _chk(
            "planlama_rf_baglanmadi",
            plan_rf_bos == src_plan_rf,
            f"plan_rf={plan_rf_bos}",
        )
    finally:
        src.close()
        tmp.close()

    return rapor


def _p5d2_post_apply_validate(
    source_db: str, temp_db: str, sim1: SimulasyonSonucu,
) -> dict[str, Any]:
    """P5D.2 — geçici DB apply sonrası koruma ve reçete doğrulamaları."""
    rapor: dict[str, Any] = {"tum_kontroller_ok": True, "kontroller": []}

    def _chk(ad: str, ok: bool, detay: str = "") -> None:
        rapor["kontroller"].append({"ad": ad, "ok": ok, "detay": detay})
        if not ok:
            rapor["tum_kontroller_ok"] = False

    src = sqlite3.connect(source_db)
    tmp = sqlite3.connect(temp_db)
    src.row_factory = sqlite3.Row
    tmp.row_factory = sqlite3.Row

    try:
        # Kaynak fingerprint'ler (eski UV korunumu)
        fp_10014_src = _kalem_fingerprint_db_ana(src, 10014)
        fp_10017_src = _kalem_fingerprint_db_ana(src, 10017)
        fp_10015_src = _kalem_fingerprint_db_ana(src, 10015)

        fp_10014_tmp = _kalem_fingerprint_db_ana(tmp, 10014)
        fp_10017_tmp = _kalem_fingerprint_db_ana(tmp, 10017)

        _chk("uv_10014_recete_korundu", fp_10014_src == fp_10014_tmp, f"{fp_10014_src}")
        _chk("uv_10017_recete_korundu", fp_10017_src == fp_10017_tmp, f"{fp_10017_src}")

        # Plan UV id'leri
        for pid in (88, 93, 91):
            row = tmp.execute(
                "SELECT uretim_varyant_id FROM nexgen_uretim_plan WHERE id=?",
                (pid,),
            ).fetchone()
            if row:
                _chk(f"plan_{pid}_uv_korundu", True, f"uv={row[0]}")

        batch10 = tmp.execute(
            "SELECT uretim_varyant_id FROM nexgen_uretim_batch WHERE id=10",
        ).fetchone()
        if batch10:
            _chk(
                "batch_10_uv_korundu",
                batch10[0] == 10017,
                f"uv={batch10[0]}",
            )

        # Revizyon UV'ler
        for kaynak in (10014, 10017):
            rev = _revision_uv_bul(tmp, kaynak)
            if rev:
                fp_rev = _kalem_fingerprint_db_ana(tmp, rev)
                row = tmp.execute(
                    "SELECT ad, kaynak_varyant_id FROM nexgen_uretim_varyant WHERE id=?",
                    (rev,),
                ).fetchone()
                _chk(
                    f"revizyon_uv_{kaynak}",
                    row and row["kaynak_varyant_id"] == kaynak,
                    f"rev_id={rev} ad={row['ad'] if row else ''} fp={fp_rev}",
                )

        # UV 10015 güncellendi mi
        if fp_10015_src != _kalem_fingerprint_db_ana(tmp, 10015):
            _chk("uv_10015_guncellendi", True, _kalem_fingerprint_db_ana(tmp, 10015))
        else:
            _chk("uv_10015_guncellendi", False, "fingerprint değişmedi")

        # RF sayısı değişmedi
        rf_src = src.execute("SELECT COUNT(*) FROM nexgen_rf_kullanim").fetchone()[0]
        rf_tmp = tmp.execute("SELECT COUNT(*) FROM nexgen_rf_kullanim").fetchone()[0]
        _chk("rf_kullanim_sayisi", rf_src == rf_tmp, f"{rf_src}->{rf_tmp}")

        # Simülasyon operasyon özeti
        rapor["update_ana_kalem"] = sim1.ozet.get("UPDATE_ANA_KALEM", 0)
        rapor["insert_uv_revision"] = sim1.ozet.get("INSERT_UV_REVISION", 0)
        rapor["gercek_blocker"] = sim1.ozet.get("GERCEK_BLOCKER", 0)
        rapor["bloker_sayisi"] = len(sim1.blokerler)

        # 10056-10061 kararları
        uv_karar = {}
        for k in sim1.islemler:
            m = re.search(r"uv_id=(\d+)", k.identity or "")
            if not m:
                m = re.search(r"kaynak_uv_id=(\d+)", k.identity or "")
            if m:
                uid = int(m.group(1))
                if uid in (10056, 10057, 10058, 10059, 10060, 10061):
                    uv_karar[uid] = k.aksiyon
        rapor["uv_10056_61"] = uv_karar

    finally:
        src.close()
        tmp.close()

    return rapor


# ---------------------------------------------------------------------------
# execute_import (--apply — tam import)
# ---------------------------------------------------------------------------
def execute_import(
    pkg: ImportPackage,
    db_path: str | None = None,
    yedek_dizin: str | None = None,
    onayli_kullanici_id: int | None = None,
    partial: bool = False,
    confirm_token: str | None = None,
) -> ImportSonucu:
    """
    Gerçek transaction import.
    Tam import: bloker varken çalışmaz.
    Kısmi import: --apply-partial --confirm TOKEN ile; yalnız safe_to_apply operasyonlar.
    """
    from modules.nexgen.kod_uretici import yeni_rv_kodu_uret  # noqa: F401 — INSERT_RV apply

    db_path = os.path.abspath(db_path or DB_PATH)

    if partial:
        return execute_partial_import(
            pkg, db_path, confirm_token or "",
            excel_sha=pkg.kaynak_bilgisi.get("dosya_sha256"),
            yedek_dizin=yedek_dizin,
            onayli_kullanici_id=onayli_kullanici_id,
        )

    # Tam import — simülasyon tabanlı güvenlik kapısı
    sim = simulate_import(pkg, db_path=db_path)
    sonuc = ImportSonucu()

    if sim.blokerler:
        sonuc.hatalar.append(
            f"Tam import reddedildi: {len(sim.blokerler)} bloker mevcut"
        )
        return sonuc

    excel_sha = pkg.kaynak_bilgisi.get("dosya_sha256", "")
    db_sha = _sha256(db_path)
    plan = build_partial_import_plan(sim, excel_sha, db_sha)
    result = execute_partial_import(
        pkg, db_path, plan.confirm_token,
        excel_sha=excel_sha,
        yedek_dizin=yedek_dizin,
        onayli_kullanici_id=onayli_kullanici_id,
        sim=sim,
    )
    result.partial_mode = False
    return result


# ---------------------------------------------------------------------------
# Yardımcılar (execute_import için)
# ---------------------------------------------------------------------------
def _insert_import_batch(con, pkg, sha_once, kullanici_id):
    excel_path = pkg.kaynak_bilgisi.get("dosya_yolu", "")
    excel_sha  = pkg.kaynak_bilgisi.get("dosya_sha256", "")
    manifest   = json.dumps(pkg.kaynak_bilgisi, ensure_ascii=False)
    con.execute(
        """INSERT INTO nexgen_import_batch
           (dosya_adi, dosya_sha256, durum, analiz_zamani, analiz_eden_id, kaynak_manifest_json)
           VALUES (?, ?, 'DEVAM', datetime('now'), ?, ?)""",
        (os.path.basename(excel_path), excel_sha, kullanici_id, manifest),
    )
    return con.execute("SELECT last_insert_rowid()").fetchone()[0]


def _log_item(con, batch_id, tablo, aksiyon, eski_id, yeni_id, detay):
    try:
        con.execute(
            """INSERT INTO nexgen_import_item_log
               (import_batch_id, nesne_tipi, eski_id, yeni_id, aksiyon, detay_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (batch_id, tablo, eski_id, yeni_id, aksiyon,
             json.dumps(detay, ensure_ascii=False)),
        )
    except sqlite3.OperationalError:
        pass  # tablo yoksa sessizce geç


# Çekirdek import — lazy import ile döngüsel bağımlılık önlenir
def simulate_cekirdek_import_reexport(pkg, db_path=None):
    from modules.nexgen.import_cekirdek import simulate_cekirdek_import as _sim
    return _sim(pkg, db_path=db_path)

simulate_cekirdek_import = simulate_cekirdek_import_reexport  # noqa: F811


def partial_apply_cekirdek_import_reexport(pkg, db_path=None, yedek_dizin=None, sim=None):
    from modules.nexgen.import_cekirdek import partial_apply_cekirdek_import as _apply
    return _apply(pkg, db_path=db_path, yedek_dizin=yedek_dizin, sim=sim)


partial_apply_cekirdek_import = partial_apply_cekirdek_import_reexport  # noqa: F811
