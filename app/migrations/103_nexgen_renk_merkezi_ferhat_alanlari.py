# -*- coding: utf-8 -*-
"""
Migration 103 — NexGen Renk Merkezi: Ferhat Saha Sonucu Alanları
=================================================================
Amaç:
  Renk Merkezi V1 onay akışında Ferhat'ın saha sonucunu kaydetmek için
  nexgen_arge_test tablosuna 3 yeni kolon eklenir.

Eklenen kolonlar:
  - pisme_suresi_dk  REAL   — pişme süresi (dakika)
  - ferhat_adi       TEXT   — saha testini yapan kişi adı
  - ferhat_tarihi    TEXT   — saha test tarihi (ISO string)

Kurallar:
  - İdempotent: kolon varsa ALTER atlanır, işlem devam eder.
  - Başka tablo değiştirilmez.
  - Mevcut veri değiştirilmez.
  - CHECK constraint veya tablo rebuild yapılmaz.
  - Durum enumları bu migration'da değiştirilmez.

Kullanım:
  Geçici DB testi (zorunlu):
    python app/migrations/103_nexgen_renk_merkezi_ferhat_alanlari.py test <db_kopya_yolu>

  Gerçek DB (yalnız SHA onayı sonrası):
    python app/migrations/103_nexgen_renk_merkezi_ferhat_alanlari.py gercek
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
from datetime import datetime

MIGRATION_NO = 103
TABLO = "nexgen_arge_test"
YENI_KOLONLAR = [
    ("pisme_suresi_dk", "REAL"),
    ("ferhat_adi",      "TEXT"),
    ("ferhat_tarihi",   "TEXT"),
]

DEFAULT_DB = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "mock_data.db")
)


# ── yardımcılar ────────────────────────────────────────────────────────

def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def _kolon_var(cur, tablo: str, kolon: str) -> bool:
    cols = [c[1] for c in cur.execute(f"PRAGMA table_info({tablo})").fetchall()]
    return kolon in cols


def _tablo_var(cur, tablo: str) -> bool:
    return cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
    ).fetchone() is not None


# ── çekirdek ──────────────────────────────────────────────────────────

def calistir(db_path: str, kuru_calisma: bool = False) -> dict:
    """
    Migration'ı çalıştırır.

    Returns:
        {
            "eklenen": ["pisme_suresi_dk", ...],
            "atlanan": ["ferhat_adi", ...],   # zaten vardı
            "degisiklik_sayisi": int,
        }
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DB bulunamadi: {db_path}")

    con = sqlite3.connect(db_path)
    cur = con.cursor()

    if not _tablo_var(cur, TABLO):
        con.close()
        raise RuntimeError(f"Tablo bulunamadi: {TABLO}")

    eklenen: list[str] = []
    atlanan: list[str] = []

    for kolon_adi, kolon_tip in YENI_KOLONLAR:
        if _kolon_var(cur, TABLO, kolon_adi):
            atlanan.append(kolon_adi)
        else:
            if not kuru_calisma:
                cur.execute(
                    f"ALTER TABLE {TABLO} ADD COLUMN {kolon_adi} {kolon_tip}"
                )
            eklenen.append(kolon_adi)

    if not kuru_calisma and eklenen:
        con.commit()

    con.close()

    return {
        "eklenen": eklenen,
        "atlanan": atlanan,
        "degisiklik_sayisi": len(eklenen),
    }


# ── doğrulama ────────────────────────────────────────────────────────

def dogrula(db_path: str) -> bool:
    """Migration sonrası kolonların varlığını doğrular."""
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    eksik = [ad for ad, _ in YENI_KOLONLAR if not _kolon_var(cur, TABLO, ad)]
    con.close()
    return len(eksik) == 0


# ── CLI ──────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _cli_test(db_path: str) -> None:
    """Geçici DB kopyası üzerinde 2 kez çalıştırır, idempotency kontrolü."""
    _log(f"TEST MODU — DB: {db_path}")
    sha_once = _sha256(db_path)
    _log(f"SHA oncesi: {sha_once}")

    # 1. çalışma
    r1 = calistir(db_path)
    _log(f"1. calisma — eklenen: {r1['eklenen']}, atlanan: {r1['atlanan']}")
    assert r1["degisiklik_sayisi"] == len(YENI_KOLONLAR) or r1["atlanan"], \
        "1. calisma: beklenmedik sonuc"

    # 2. çalışma — idempotency
    r2 = calistir(db_path)
    _log(f"2. calisma — eklenen: {r2['eklenen']}, atlanan: {r2['atlanan']}")
    assert r2["degisiklik_sayisi"] == 0, \
        f"2. calisma idempotent olmali! eklenen: {r2['eklenen']}"

    # doğrulama
    assert dogrula(db_path), "Dogrulama basarisiz — kolon eksik!"
    _log("Dogrulama OK — tum kolonlar mevcut")

    sha_sonra = _sha256(db_path)
    _log(f"SHA sonrasi: {sha_sonra}")
    if sha_once != sha_sonra:
        _log("SHA degisti (beklenen — kolon eklendi)")
    _log("TEST GECTI")


def _cli_gercek(db_path: str) -> None:
    """Gerçek DB'ye uygular. SHA öncesi/sonrası yazdırır."""
    _log(f"GERCEK MOD — DB: {db_path}")
    sha_once = _sha256(db_path)
    _log(f"SHA oncesi: {sha_once}")

    r = calistir(db_path)
    _log(f"Sonuc — eklenen: {r['eklenen']}, atlanan: {r['atlanan']}")

    assert dogrula(db_path), "Dogrulama basarisiz — DUR!"
    _log("Dogrulama OK")

    sha_sonra = _sha256(db_path)
    _log(f"SHA sonrasi: {sha_sonra}")
    _log(f"Migration {MIGRATION_NO} tamamlandi.")


if __name__ == "__main__":
    # stdout Türkçe
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    mod = sys.argv[1] if len(sys.argv) > 1 else ""
    if mod == "test":
        db_arg = sys.argv[2] if len(sys.argv) > 2 else None
        if not db_arg:
            print("Kullanim: python 103_... test <db_kopya_yolu>")
            sys.exit(1)
        _cli_test(db_arg)
    elif mod == "gercek":
        db_arg = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_DB
        _cli_gercek(db_arg)
    else:
        print(f"Kullanim: python 103_... test <db_kopya_yolu>")
        print(f"          python 103_... gercek [<db_yolu>]")
        sys.exit(1)
