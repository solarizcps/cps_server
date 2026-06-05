# -*- coding: utf-8 -*-
"""
import_5055_full.py
===================
5055 solariz.db -> CPS mock_data.db
TUM kayitlari import eder (tarih filtresi yok).

Idempotent (INSERT OR IGNORE).
5055 DB'sine YAZMAZ.
"""
import os
import sys
import sqlite3
import shutil
import datetime

DB_5055 = r"D:\Ortak\Solariz-ARGE\solariz.db"
DB_CPS  = r"D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\mock_data.db"

LEGACY_DB_LABEL = "solariz.db"
KAYNAK_LABEL    = "LEGACY_5055"
BATCH_SIZE      = 500


def log(msg, level="INFO"):
    pfx = {"INFO":"[INFO]","OK":"[OK]","ERR":"[HATA]","WARN":"[UYARI]","SKIP":"[SKIP]"}.get(level,"[INFO]")
    print(f"{pfx} {msg}")


def main():
    log("=" * 70)
    log("FAZ 2C - 5055 FULL IMPORT")
    log("=" * 70)

    if not os.path.exists(DB_5055):
        log(f"5055 DB yok: {DB_5055}", "ERR")
        return 1
    if not os.path.exists(DB_CPS):
        log(f"CPS DB yok: {DB_CPS}", "ERR")
        return 1

    # Backup
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = DB_CPS + ".YEDEK_FULL_IMPORT_" + ts
    shutil.copy2(DB_CPS, bak)
    log(f"Backup: {os.path.basename(bak)}", "OK")
    log(f"Boyut : {os.path.getsize(bak)} byte")

    # 5055 READ-ONLY
    uri_5055 = "file:" + DB_5055.replace("\\", "/") + "?mode=ro&nolock=1"
    c5055 = sqlite3.connect(uri_5055, uri=True, timeout=10)
    c5055.row_factory = sqlite3.Row
    log("5055 baglanti (READ ONLY)", "OK")

    # CPS write
    ccps = sqlite3.connect(DB_CPS, timeout=15)
    log("CPS baglanti (WRITE)", "OK")

    try:
        cur = ccps.cursor()

        # Pre-import
        once_toplam = cur.execute("SELECT COUNT(*) FROM uretim_kayit").fetchone()[0]
        once_legacy = cur.execute("SELECT COUNT(*) FROM uretim_kayit WHERE kaynak=?", (KAYNAK_LABEL,)).fetchone()[0]
        log("")
        log("--- Pre-import CPS durumu ---")
        log(f"  Toplam kayit       : {once_toplam}")
        log(f"  LEGACY_5055 kayit  : {once_legacy}")

        # 5055'ten TUM kayitlari oku
        log("")
        log("--- 5055'ten TUM kayitlari okuma ---")
        rows = c5055.execute("""
            SELECT id, emir_no, model_kod, model_adi, miktar,
                   personel_id, personel_ad, proses_adi,
                   tarih, saat, onay_durum, usta_ad, usta_not, onay_tarihi, olusturma
              FROM uretim_kayit
             ORDER BY id ASC
        """).fetchall()
        log(f"  Okunan: {len(rows)} kayit")

        if not rows:
            log("Kayit yok - import atlandi", "WARN")
            return 0

        # INSERT OR IGNORE batch'li
        log("")
        log("--- CPS'e INSERT OR IGNORE (batch=500) ---")
        import_dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        eklenen = 0
        atlanan = 0
        hatali  = 0
        batch_no = 0

        cur.execute("BEGIN TRANSACTION")

        for idx, r in enumerate(rows, start=1):
            ih = f"{LEGACY_DB_LABEL}:{r['id']}"
            try:
                cur.execute("""
                    INSERT INTO uretim_kayit
                        (emir_no, model_kod, model_adi, miktar,
                         proses_kodu, proses_adi,
                         personel_id, personel_ad,
                         tarih, saat,
                         not_metin, onay_durum,
                         usta_id, usta_ad, usta_not,
                         onay_tarihi, olusturma,
                         kaynak, legacy_id, legacy_db, import_tarihi, import_hash)
                    VALUES (?, ?, ?, ?,
                            NULL, ?,
                            ?, ?,
                            ?, ?,
                            NULL, ?,
                            NULL, ?, ?,
                            ?, ?,
                            ?, ?, ?, ?, ?)
                """, (
                    r["emir_no"], r["model_kod"], r["model_adi"], r["miktar"],
                    r["proses_adi"],
                    r["personel_id"], r["personel_ad"],
                    r["tarih"], r["saat"],
                    r["onay_durum"],
                    r["usta_ad"], r["usta_not"],
                    r["onay_tarihi"], r["olusturma"],
                    KAYNAK_LABEL, r["id"], LEGACY_DB_LABEL, import_dt, ih
                ))
                eklenen += 1
            except sqlite3.IntegrityError as e:
                if "UNIQUE" in str(e).upper():
                    atlanan += 1
                else:
                    hatali += 1
                    if hatali <= 3:
                        log(f"  Integrity hata id={r['id']}: {e}", "WARN")
            except Exception as e:
                hatali += 1
                if hatali <= 3:
                    log(f"  Genel hata id={r['id']}: {e}", "WARN")

            # Her 500 kayitta progress + commit
            if idx % BATCH_SIZE == 0:
                ccps.commit()
                batch_no += 1
                log(f"  Batch {batch_no} commit: {idx}/{len(rows)} (eklenen={eklenen} atlanan={atlanan} hatali={hatali})")
                cur.execute("BEGIN TRANSACTION")

        ccps.commit()
        log(f"  TAMAMLANDI: eklenen={eklenen} atlanan={atlanan} hatali={hatali}", "OK")

        # Post-import
        log("")
        log("--- Post-import CPS durumu ---")
        sonra_toplam = cur.execute("SELECT COUNT(*) FROM uretim_kayit").fetchone()[0]
        sonra_legacy = cur.execute("SELECT COUNT(*) FROM uretim_kayit WHERE kaynak=?", (KAYNAK_LABEL,)).fetchone()[0]
        log(f"  Toplam kayit       : {sonra_toplam} (+{sonra_toplam-once_toplam})")
        log(f"  LEGACY_5055 kayit  : {sonra_legacy} (+{sonra_legacy-once_legacy})")

        # Kaynak dagilimi
        log("")
        log("--- Kaynak dagilimi ---")
        for r in cur.execute("SELECT kaynak, COUNT(*) FROM uretim_kayit GROUP BY kaynak").fetchall():
            log(f"  kaynak='{r[0]}': {r[1]} kayit")

        # LEGACY onay dagilimi
        log("")
        log("--- LEGACY_5055 onay dagilimi ---")
        for r in cur.execute("""
            SELECT onay_durum, COUNT(*) say, SUM(miktar) cift
              FROM uretim_kayit
             WHERE kaynak='LEGACY_5055'
             GROUP BY onay_durum
        """).fetchall():
            log(f"  {r[0]:<15}: {r[1]} kayit, {r[2]} cift")

        # Min/Max legacy_id check
        log("")
        log("--- legacy_id araligi ---")
        r = cur.execute("""
            SELECT MIN(legacy_id), MAX(legacy_id), COUNT(*)
              FROM uretim_kayit WHERE kaynak='LEGACY_5055'
        """).fetchone()
        log(f"  Min: {r[0]}  Max: {r[1]}  Toplam: {r[2]}")

        # 5055 ile karsilastir
        r55 = c5055.execute("SELECT MIN(id), MAX(id), COUNT(*) FROM uretim_kayit").fetchone()
        log(f"  5055 Min: {r55[0]}  Max: {r55[1]}  Toplam: {r55[2]}")

        if r[2] == r55[2]:
            log("  ESLESME TAM ✓", "OK")
        else:
            fark = r55[2] - r[2]
            log(f"  EKSIK: {fark} kayit", "WARN")

        log("")
        log("=" * 70)
        log("FULL IMPORT BASARILI", "OK")
        log("=" * 70)
        log(f"Backup       : {os.path.basename(bak)}")
        log(f"Yeni eklenen : {eklenen}")
        log(f"Atlanan      : {atlanan}")
        log(f"Hatali       : {hatali}")
        return 0

    except Exception as e:
        try:
            ccps.rollback()
        except Exception:
            pass
        log(f"HATA: {e}", "ERR")
        log("Transaction ROLLBACK", "WARN")
        log(f"DB bozulmadi - backup: {os.path.basename(bak)}", "INFO")
        return 5
    finally:
        c5055.close()
        ccps.close()


if __name__ == "__main__":
    sys.exit(main())