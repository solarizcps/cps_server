# -*- coding: utf-8 -*-
"""
001_legacy_5055_kolonlari.py
============================
CPS uretim_kayit tablosuna 5055 import altyapisi.

Idempotent, atomic, auto-backup, auto-rollback.
5055 DB'sine ASLA dokunmaz.
"""
import os
import sys
import sqlite3
import shutil
import datetime

CPS_DB = r"D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\mock_data.db"

YENI_KOLONLAR = [
    ("kaynak",        "TEXT DEFAULT 'CPS_CANLI'"),
    ("legacy_id",     "INTEGER"),
    ("legacy_db",     "TEXT"),
    ("import_tarihi", "TEXT"),
    ("import_hash",   "TEXT"),
]

YENI_INDEXLER = [
    ("idx_uk_kaynak",
     "CREATE INDEX IF NOT EXISTS idx_uk_kaynak ON uretim_kayit(kaynak)"),
    ("idx_uk_legacy_unique",
     "CREATE UNIQUE INDEX IF NOT EXISTS idx_uk_legacy_unique "
     "ON uretim_kayit(kaynak, legacy_db, legacy_id) "
     "WHERE kaynak = 'LEGACY_5055'"),
]


def log(msg, level="INFO"):
    pfx = {"INFO":"[INFO]","OK":"[OK]","ERR":"[HATA]","WARN":"[UYARI]","SKIP":"[SKIP]"}.get(level,"[INFO]")
    print(f"{pfx} {msg}")


def main():
    log("=" * 70)
    log("FAZ 1 MIGRATION - CPS uretim_kayit altyapi")
    log("=" * 70)

    if not os.path.exists(CPS_DB):
        log("CPS DB bulunamadi: " + CPS_DB, "ERR")
        return 1

    # 1) Backup
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = CPS_DB + ".YEDEK_MIGRATION_" + ts
    shutil.copy2(CPS_DB, bak)
    log("Backup: " + os.path.basename(bak), "OK")
    log("Boyut : " + str(os.path.getsize(bak)) + " byte")

    # 2) Baglan
    conn = sqlite3.connect(CPS_DB, timeout=10)

    try:
        cur = conn.cursor()

        # Mevcut kolonlar
        cur.execute("PRAGMA table_info(uretim_kayit)")
        mevcut_kolonlar = [r[1] for r in cur.fetchall()]
        log("Mevcut kolon sayisi: " + str(len(mevcut_kolonlar)))

        cur.execute("BEGIN TRANSACTION")
        log("Transaction baslatildi", "OK")

        # 3) Kolonlar
        log("")
        log("--- Kolon ekleme ---")
        eklenen = 0
        for kol_ad, kol_tip in YENI_KOLONLAR:
            if kol_ad in mevcut_kolonlar:
                log("  '" + kol_ad + "' zaten var", "SKIP")
            else:
                cur.execute("ALTER TABLE uretim_kayit ADD COLUMN " + kol_ad + " " + kol_tip)
                log("  Eklendi: " + kol_ad + " (" + kol_tip + ")", "OK")
                eklenen += 1

        # 4) Index
        log("")
        log("--- Index ekleme ---")
        for idx_ad, idx_sql in YENI_INDEXLER:
            cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name=?", (idx_ad,))
            if cur.fetchone():
                log("  '" + idx_ad + "' zaten var", "SKIP")
            else:
                cur.execute(idx_sql)
                log("  Eklendi: " + idx_ad, "OK")

        # 5) Etiketleme - mevcut etiketsiz kayitlar
        log("")
        log("--- Mevcut kayitlari CPS_TEST etiketle ---")
        cur.execute("""
            UPDATE uretim_kayit
               SET kaynak = 'CPS_TEST'
             WHERE legacy_id IS NULL
               AND (kaynak IS NULL OR kaynak = 'CPS_CANLI')
        """)
        etiketlenen = cur.rowcount
        log("  Etiketlenen: " + str(etiketlenen) + " kayit", "OK")

        # 6) Commit
        conn.commit()
        log("")
        log("Transaction COMMIT", "OK")

        # 7) Dogrulama
        log("")
        log("--- Dogrulama ---")
        cur.execute("PRAGMA table_info(uretim_kayit)")
        son_kolonlar = [r[1] for r in cur.fetchall()]
        log("Yeni kolon sayisi: " + str(len(son_kolonlar)))

        beklenen = [k[0] for k in YENI_KOLONLAR]
        eksik = [k for k in beklenen if k not in son_kolonlar]
        if eksik:
            log("EKSIK: " + str(eksik), "ERR")
            return 4

        cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='uretim_kayit' ORDER BY name")
        indexler = [r[0] for r in cur.fetchall()]
        log("Index'ler: " + str(indexler))

        cur.execute("SELECT kaynak, COUNT(*) FROM uretim_kayit GROUP BY kaynak")
        for r in cur.fetchall():
            log("  kaynak='" + str(r[0]) + "': " + str(r[1]) + " kayit")

        log("")
        log("=" * 70)
        log("MIGRATION BASARILI", "OK")
        log("=" * 70)
        log("Backup       : " + os.path.basename(bak))
        log("Eklenen kolon: " + str(eklenen) + "/" + str(len(YENI_KOLONLAR)))
        log("Etiketlenen  : " + str(etiketlenen) + " kayit")
        return 0

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        log("HATA: " + str(e), "ERR")
        log("Transaction ROLLBACK", "WARN")
        log("DB bozulmadi - backup: " + os.path.basename(bak), "INFO")
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())