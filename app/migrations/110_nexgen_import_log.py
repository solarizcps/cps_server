# -*- coding: utf-8 -*-
"""
Migration 110 — NexGen P4F: Import Log Altyapısı
=================================================
[1] nexgen_import_batch     — import oturumu log tablosu
[2] nexgen_import_item_log  — kalem bazlı before/after log

Kurallar:
  - Idempotent: tekrar çalıştırılabilir
  - Mevcut veriler silinmez, değiştirilmez
  - nexgen_stok_hareket DOKUNULMAZ
  - nexgen_recete_kalem DOKUNULMAZ
  - nexgen_uretim_plan DOKUNULMAZ
"""

import sqlite3
import os
import shutil
from datetime import datetime

DB_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'mock_data.db'))


def _tablo_var(cur, tablo):
    return cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
    ).fetchone() is not None


def _kolon_var(cur, tablo, kolon):
    return kolon in [c[1] for c in cur.execute(f"PRAGMA table_info({tablo})").fetchall()]


def run():
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadı: {DB_PATH}")
        return

    # Yedek
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = DB_PATH.replace('.db', f'_backup_pre110_{ts}.db')
    try:
        shutil.copy2(DB_PATH, bak)
        print(f"[YEDEK] {os.path.basename(bak)}")
    except Exception as e:
        print(f"[UYARI] Yedek alınamadı: {e}")

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("=" * 70)
    print("Migration 110 — nexgen_import_batch + nexgen_import_item_log")
    print(f"DB: {os.path.abspath(DB_PATH)}")
    print("=" * 70)

    # Güvenlik sayımı
    sh_onceki  = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    frm_onceki = cur.execute("SELECT COUNT(*) FROM nexgen_formul").fetchone()[0]
    rk_onceki  = cur.execute("SELECT COUNT(*) FROM nexgen_recete_kalem").fetchone()[0]
    print(f"\n[ÖNCESİ] stok_hareket={sh_onceki}  formul={frm_onceki}  recete_kalem={rk_onceki}")

    # ═══════════════════════════════════════════════════════════════════
    # [1] nexgen_import_batch
    # ═══════════════════════════════════════════════════════════════════
    print("\n[1] nexgen_import_batch tablosu:")
    if not _tablo_var(cur, 'nexgen_import_batch'):
        cur.execute("""
            CREATE TABLE nexgen_import_batch (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,

                dosya_adi             TEXT    NOT NULL,
                dosya_sha256          TEXT    NOT NULL,

                -- Yaşam döngüsü
                -- DEVAM     : transaction başladı, henüz commit olmadı
                -- TAMAMLANDI: commit başarılı
                -- HATA      : rollback yapıldı
                durum                 TEXT    NOT NULL DEFAULT 'DEVAM',

                -- Zaman damgaları
                analiz_zamani         TEXT,
                onay_zamani           TEXT,
                import_zamani         TEXT,
                olusturma_tarihi      TEXT    NOT NULL DEFAULT (datetime('now')),

                -- Kullanıcılar
                analiz_eden_id        INTEGER,
                onaylayan_id          INTEGER,
                import_eden_id        INTEGER,

                -- Sayımlar (import tamamlandığında doldurulur)
                yeni_formul_sayisi    INTEGER DEFAULT 0,
                degisen_formul_sayisi INTEGER DEFAULT 0,
                hata_sayisi           INTEGER DEFAULT 0,
                uyari_sayisi          INTEGER DEFAULT 0,

                -- Kaynak bilgisi
                kaynak_manifest_json  TEXT,
                rollback_yedek_yolu   TEXT,

                -- SHA kontrolü
                db_sha_once           TEXT,
                db_sha_sonra          TEXT
            )
        """)
        con.commit()
        print("  OK    nexgen_import_batch oluşturuldu")
    else:
        print("  SKIP  nexgen_import_batch zaten var")
        # Eksik kolon kontrolü (sonradan eklenebilir)
        for kolon, tanim in [
            ('db_sha_once',   'TEXT'),
            ('db_sha_sonra',  'TEXT'),
            ('rollback_yedek_yolu', 'TEXT'),
        ]:
            if not _kolon_var(cur, 'nexgen_import_batch', kolon):
                cur.execute(f"ALTER TABLE nexgen_import_batch ADD COLUMN {kolon} {tanim}")
                con.commit()
                print(f"  OK    nexgen_import_batch.{kolon} eklendi")

    # İndeksler
    for idx_ad, idx_hedef in [
        ("idx_nib_sha",    "nexgen_import_batch(dosya_sha256)"),
        ("idx_nib_durum",  "nexgen_import_batch(durum)"),
        ("idx_nib_tarih",  "nexgen_import_batch(olusturma_tarihi)"),
    ]:
        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_ad} ON {idx_hedef}")
    con.commit()
    print("  OK    3 index")

    # ═══════════════════════════════════════════════════════════════════
    # [2] nexgen_import_item_log
    # ═══════════════════════════════════════════════════════════════════
    print("\n[2] nexgen_import_item_log tablosu:")
    if not _tablo_var(cur, 'nexgen_import_item_log'):
        cur.execute("""
            CREATE TABLE nexgen_import_item_log (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                import_batch_id  INTEGER NOT NULL,

                -- Kaynak
                kaynak_sayfa     TEXT,
                kaynak_hucre     TEXT,

                -- Nesne
                nesne_tipi       TEXT    NOT NULL,  -- nexgen_formul, nexgen_recete_kalem vb.
                eski_id          INTEGER,
                yeni_id          INTEGER,
                aksiyon          TEXT    NOT NULL,  -- INSERT, UPDATE, REPLACE, PASIFLES

                -- Fingerprint
                eski_fingerprint TEXT,
                yeni_fingerprint TEXT,

                -- JSON detay (before/after)
                detay_json       TEXT,

                olusturma_tarihi TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        con.commit()
        print("  OK    nexgen_import_item_log oluşturuldu")
    else:
        print("  SKIP  nexgen_import_item_log zaten var")

    # İndeksler
    for idx_ad, idx_hedef in [
        ("idx_niil_batch",   "nexgen_import_item_log(import_batch_id)"),
        ("idx_niil_tip",     "nexgen_import_item_log(nesne_tipi)"),
        ("idx_niil_aksiyon", "nexgen_import_item_log(aksiyon)"),
    ]:
        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_ad} ON {idx_hedef}")
    con.commit()
    print("  OK    3 index")

    # Güvenlik doğrulama
    sh_sonraki  = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    frm_sonraki = cur.execute("SELECT COUNT(*) FROM nexgen_formul").fetchone()[0]
    rk_sonraki  = cur.execute("SELECT COUNT(*) FROM nexgen_recete_kalem").fetchone()[0]
    print(f"\n[SONRASI] stok_hareket={sh_sonraki}  formul={frm_sonraki}  recete_kalem={rk_sonraki}")
    assert sh_sonraki  == sh_onceki,  "HATA: stok_hareket sayısı değişti!"
    assert frm_sonraki == frm_onceki, "HATA: formul sayısı değişti!"
    assert rk_sonraki  == rk_onceki,  "HATA: recete_kalem sayısı değişti!"

    # schema_migrations
    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(110)")
        con.commit()
        print("\n  OK    schema_migrations version=110")
    except Exception as e:
        print(f"\n  WARN  schema_migrations: {e}")

    nib_say  = cur.execute("SELECT COUNT(*) FROM nexgen_import_batch").fetchone()[0]
    niil_say = cur.execute("SELECT COUNT(*) FROM nexgen_import_item_log").fetchone()[0]

    print("\n" + "=" * 70)
    print("ÖZET")
    print("=" * 70)
    print(f"  nexgen_import_batch    : {nib_say} kayıt (yeni tablo)")
    print(f"  nexgen_import_item_log : {niil_say} kayıt (yeni tablo)")
    print(f"  stok_hareket delta     : {sh_sonraki - sh_onceki} (0 olmalı)")
    print("=" * 70)
    print("Migration 110 tamamlandı\n")

    con.close()


def rollback():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    print("\n=== Rollback 110 ===")
    cur.execute("DROP TABLE IF EXISTS nexgen_import_item_log")
    cur.execute("DROP TABLE IF EXISTS nexgen_import_batch")
    for idx in ('idx_nib_sha', 'idx_nib_durum', 'idx_nib_tarih',
                'idx_niil_batch', 'idx_niil_tip', 'idx_niil_aksiyon'):
        cur.execute(f"DROP INDEX IF EXISTS {idx}")
    try:
        cur.execute("DELETE FROM schema_migrations WHERE version=110")
    except Exception:
        pass
    con.commit()
    con.close()
    print("  OK    nexgen_import_batch + nexgen_import_item_log kaldırıldı")
    print("=== Rollback 110 tamamlandı ===\n")


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'rollback':
        rollback()
    else:
        run()
