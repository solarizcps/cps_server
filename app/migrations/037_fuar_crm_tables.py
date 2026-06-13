# -*- coding: utf-8 -*-
"""
037_fuar_crm_tables.py
=======================
Fuar CRM Faz 1 — DB Şeması

Tablolar:
  crm_firma       — Firma / cari kartı
  crm_gorusme     — Görüşme notları
  crm_dosya       — Kartvizit / ek dosyalar

Idempotent. Mevcut tablolar varsa SKIP geçer.
Rollback: DROP TABLE crm_firma, crm_gorusme, crm_dosya;
"""
import os, sys, sqlite3, shutil, datetime

CPS_DB_DEFAULT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..', 'mock_data.db'
)
CPS_DB = os.environ.get('CPS_DB', CPS_DB_DEFAULT)


def log(msg, level="INFO"):
    pfx = {"INFO": "[INFO]", "OK": "[OK]", "ERR": "[HATA]",
           "WARN": "[UYARI]", "SKIP": "[SKIP]"}.get(level, "[INFO]")
    print(f"{pfx} {msg}")


def main():
    log("=" * 70)
    log("MIGRATION 037 - Fuar CRM Tablolari")
    log("=" * 70)

    db_path = os.path.normpath(CPS_DB)
    if not os.path.exists(db_path):
        log(f"DB bulunamadı: {db_path}", "ERR")
        return 1

    log(f"DB: {db_path}")
    log(f"DB boyut: {os.path.getsize(db_path)} byte")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = db_path + f".YEDEK_CRM_FAZ1_{ts}"
    shutil.copy2(db_path, bak)
    log(f"Backup: {os.path.basename(bak)}", "OK")

    conn = sqlite3.connect(db_path, timeout=10)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN TRANSACTION")

        # ── crm_firma ──────────────────────────────────────────────────────
        ex = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='crm_firma'"
        ).fetchone()
        if ex:
            log("crm_firma zaten var", "SKIP")
        else:
            cur.execute("""
                CREATE TABLE crm_firma (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    firma_adi     TEXT NOT NULL,
                    yetkili       TEXT,
                    telefon       TEXT,
                    whatsapp      TEXT,
                    email         TEXT,
                    ulke          TEXT,
                    sehir         TEXT,
                    firma_tipi    TEXT,
                    marka_ilgisi  TEXT,
                    erp_cari_kodu TEXT,
                    kaynak        TEXT,
                    aktif         INTEGER NOT NULL DEFAULT 1,
                    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                    created_by    TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_firma_ulke   ON crm_firma(ulke)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_firma_aktif  ON crm_firma(aktif)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_firma_kaynak ON crm_firma(kaynak)")
            log("crm_firma olusturuldu (3 index)", "OK")

        # ── crm_gorusme ────────────────────────────────────────────────────
        ex = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='crm_gorusme'"
        ).fetchone()
        if ex:
            log("crm_gorusme zaten var", "SKIP")
        else:
            cur.execute("""
                CREATE TABLE crm_gorusme (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    firma_id       INTEGER NOT NULL REFERENCES crm_firma(id),
                    fuar_adi       TEXT,
                    gorusen        TEXT,
                    not_text       TEXT,
                    urun_ilgisi    TEXT,
                    numune         INTEGER NOT NULL DEFAULT 0,
                    fiyat_verildi  INTEGER NOT NULL DEFAULT 0,
                    takip_tarihi   TEXT,
                    durum          TEXT NOT NULL DEFAULT 'beklemede',
                    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
                    created_by     TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_gor_firma  ON crm_gorusme(firma_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_gor_durum  ON crm_gorusme(durum)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_gor_takip  ON crm_gorusme(takip_tarihi)")
            log("crm_gorusme olusturuldu (3 index)", "OK")

        # ── crm_dosya ──────────────────────────────────────────────────────
        ex = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='crm_dosya'"
        ).fetchone()
        if ex:
            log("crm_dosya zaten var", "SKIP")
        else:
            cur.execute("""
                CREATE TABLE crm_dosya (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    firma_id    INTEGER NOT NULL REFERENCES crm_firma(id),
                    dosya_yolu  TEXT NOT NULL,
                    tip         TEXT NOT NULL DEFAULT 'kartvizit',
                    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                    created_by  TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_dosya_firma ON crm_dosya(firma_id)")
            log("crm_dosya olusturuldu (1 index)", "OK")

        conn.commit()
        log("COMMIT OK", "OK")

        # Dogrulama
        log("")
        log("--- Post-migration tablolari ---")
        for tbl in ("crm_firma", "crm_gorusme", "crm_dosya"):
            cnt = cur.execute(
                f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (tbl,)
            ).fetchone()[0]
            log(f"  {tbl}: {'VAR' if cnt else 'YOK'}", "OK" if cnt else "ERR")

        log("")
        log("=" * 70)
        log("MIGRATION 037 BASARILI", "OK")
        log("=" * 70)
        log(f"Backup: {os.path.basename(bak)}")
        return 0

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        log(f"HATA: {e}", "ERR")
        log("Rollback yapildi", "WARN")
        import traceback
        traceback.print_exc()
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
