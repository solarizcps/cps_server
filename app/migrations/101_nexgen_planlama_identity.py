# -*- coding: utf-8 -*-
"""
Migration 101 — NexGen P5C-1: Planlama 6-Alan Identity Şema Desteği
====================================================================
Amaç:
  nexgen_planlama_uygunluk tablosuna import identity kolonları ekler:
    - musteri_renk_kodu  (müşteri renk kodu — Excel renk_kodu)
    - boyut              (LARGE / SMALL / MEDIUM / STANDART)

Business identity (DB fiziksel temsili):
  cari_id + uretim_tipi_id + formul_id + renk_varyant_id + musteri_renk_kodu + boyut
  NOT: normalize(varyant) metni DB'de renk_varyant_id (RV surrogate) ile temsil edilir.

Unique index: uq_npu_identity
  cari_id, uretim_tipi_id, formul_id, renk_varyant_id,
  COALESCE(musteri_renk_kodu,''), COALESCE(boyut,''),
  IFNULL(rf_renk_id,-1), IFNULL(rf_rev_no,-1)

Kurallar:
  - Idempotent
  - Mevcut satırlar silinmez / güncellenmez (sahte veri üretilmez)
  - NULL kolonlar korunur; COALESCE unique index'te '' olarak değerlendirilir
  - Tablo DROP edilmez
  - Gerçek DB yolu sabit kodlanmaz (run(db_path=...) ile geçici DB test edilebilir)

Yedek zorunluluğu:
  Gerçek DB uygulamasından ÖNCE mock_data.db yedeği alınmalıdır.

Rollback:
  python app/migrations/101_nexgen_planlama_identity.py rollback [db_path]
  - uq_npu_identity kaldırılır
  - uq_npu_kullanim (099) yeniden oluşturulur
  - musteri_renk_kodu ve boyut kolonları SQLite'da DROP COLUMN desteklenmediği
    için kalır (veri kaybı yok); üretim rollback için yedekten restore önerilir.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime

DEFAULT_DB = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "mock_data.db")
)


def _tablo_var(cur, tablo: str) -> bool:
    return cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
    ).fetchone() is not None


def _kolon_var(cur, tablo: str, kolon: str) -> bool:
    return kolon in [
        c[1] for c in cur.execute(f"PRAGMA table_info({tablo})").fetchall()
    ]


def _index_var(cur, ad: str) -> bool:
    return cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (ad,)
    ).fetchone() is not None


def _index_kolonlari(cur, ad: str) -> list[str]:
    return [r[2] for r in cur.execute(f"PRAGMA index_info({ad})").fetchall()]


def _legacy_dup_kontrol(cur) -> list[tuple]:
    """Yeni unique index öncesi mevcut satır çakışması."""
    return cur.execute("""
        SELECT cari_id, uretim_tipi_id, formul_id, renk_varyant_id,
               COALESCE(musteri_renk_kodu,''), COALESCE(boyut,''),
               COUNT(*) AS c
        FROM nexgen_planlama_uygunluk
        GROUP BY 1,2,3,4,5,6
        HAVING c > 1
    """).fetchall()


def run(db_path: str | None = None, backup: bool = True) -> dict:
    """
    Migration 101 uygula. db_path verilmezse DEFAULT_DB (gerçek DB).
    Geçici test için db_path=kopya_yolu kullanın.
    """
    db_path = os.path.abspath(db_path or DEFAULT_DB)
    sonuc: dict = {
        "db_path": db_path,
        "kolon_eklendi": [],
        "index_olusturuldu": False,
        "index_zaten_var": False,
        "satir_sayisi_once": 0,
        "satir_sayisi_sonra": 0,
        "legacy_dup": [],
        "hata": None,
    }

    if not os.path.exists(db_path):
        sonuc["hata"] = f"DB bulunamadı: {db_path}"
        return sonuc

    if backup:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = db_path.replace(".db", f"_backup_pre101_{ts}.db")
        try:
            shutil.copy2(db_path, bak)
            sonuc["yedek"] = bak
        except Exception as e:
            sonuc["hata"] = f"Yedek alınamadı: {e}"
            return sonuc

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    try:
        if not _tablo_var(cur, "nexgen_planlama_uygunluk"):
            sonuc["hata"] = "nexgen_planlama_uygunluk tablosu yok"
            return sonuc

        sonuc["satir_sayisi_once"] = cur.execute(
            "SELECT COUNT(*) FROM nexgen_planlama_uygunluk"
        ).fetchone()[0]

        # Kolonlar (idempotent)
        for kolon, tanim in [
            ("musteri_renk_kodu", "TEXT"),
            ("boyut", "TEXT"),
        ]:
            if not _kolon_var(cur, "nexgen_planlama_uygunluk", kolon):
                cur.execute(
                    f"ALTER TABLE nexgen_planlama_uygunluk ADD COLUMN {kolon} {tanim}"
                )
                con.commit()
                sonuc["kolon_eklendi"].append(kolon)

        # Mevcut kayıt çakışma kontrolü (NULL → '' COALESCE)
        sonuc["legacy_dup"] = [tuple(r) for r in _legacy_dup_kontrol(cur)]
        if sonuc["legacy_dup"]:
            sonuc["hata"] = (
                f"Legacy duplicate gruplar var ({len(sonuc['legacy_dup'])}); "
                "unique index oluşturulmadı"
            )
            return sonuc

        # Hedef index zaten doğruysa atla
        if _index_var(cur, "uq_npu_identity"):
            sonuc["index_zaten_var"] = True
            sonuc["index_kolonlari"] = _index_kolonlari(cur, "uq_npu_identity")
        else:
            cur.execute("DROP INDEX IF EXISTS uq_npu_kullanim")
            cur.execute("DROP INDEX IF EXISTS uq_npu_kullanim_v2")
            cur.execute("""
                CREATE UNIQUE INDEX uq_npu_identity
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
            sonuc["index_olusturuldu"] = True
            sonuc["index_kolonlari"] = _index_kolonlari(cur, "uq_npu_identity")

        sonuc["satir_sayisi_sonra"] = cur.execute(
            "SELECT COUNT(*) FROM nexgen_planlama_uygunluk"
        ).fetchone()[0]

    except Exception as e:
        con.rollback()
        sonuc["hata"] = str(e)
    finally:
        con.close()

    return sonuc


def rollback(db_path: str | None = None) -> dict:
    """Index geri al; kolonlar kalır (SQLite DROP COLUMN yok)."""
    db_path = os.path.abspath(db_path or DEFAULT_DB)
    sonuc: dict = {"db_path": db_path, "hata": None}
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    try:
        cur.execute("DROP INDEX IF EXISTS uq_npu_identity")
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_npu_kullanim
            ON nexgen_planlama_uygunluk (
                cari_id,
                uretim_tipi_id,
                formul_id,
                renk_varyant_id,
                IFNULL(rf_renk_id, -1),
                IFNULL(rf_rev_no,  -1)
            )
        """)
        con.commit()
        sonuc["rollback_ok"] = True
    except Exception as e:
        sonuc["hata"] = str(e)
    finally:
        con.close()
    return sonuc


if __name__ == "__main__":
    import sys
    target = sys.argv[2] if len(sys.argv) > 2 else None
    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        r = rollback(target)
        print(r)
    else:
        r = run(target, backup=target is None)
        print(r)
