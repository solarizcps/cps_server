# -*- coding: utf-8 -*-
"""
import_5055_bugun.py
====================
5055 solariz.db -> CPS mock_data.db
BUGUNKU kayitlari import eder. Idempotent (INSERT OR IGNORE).

5055 DB'sine YAZMAZ - sadece READ ONLY okuma.
CPS DB'sine YAZAR - INSERT only (UPDATE/DELETE yok).
"""
import os
import sys
import sqlite3
import shutil
import datetime
import hashlib

DB_5055 = r"D:\Ortak\Solariz-ARGE\solariz.db"
DB_CPS  = r"D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\mock_data.db"

LEGACY_DB_LABEL = "solariz.db"
KAYNAK_LABEL    = "LEGACY_5055"


def log(msg, level="INFO"):
    pfx = {"INFO":"[INFO]","OK":"[OK]","ERR":"[HATA]","WARN":"[UYARI]","SKIP":"[SKIP]"}.get(level,"[INFO]")
    print(f"{pfx} {msg}")


def import_hash_gen(legacy_db, legacy_id):
    return f"{legacy_db}:{legacy_id}"


def main():
    log("=" * 70)
    log("FAZ 2A - 5055 BUGUNKU KAYIT IMPORT")
    log("=" * 70)

    # 1) Var mi kontrolu
    if not os.path.exists(DB_5055):
        log(f"5055 DB yok: {DB_5055}", "ERR")
        return 1
    if not os.path.exists(DB_CPS):
        log(f"CPS DB yok: {DB_CPS}", "ERR")
        return 1

    # 2) CPS Backup
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = DB_CPS + ".YEDEK_IMPORT_2A_" + ts
    try:
        shutil.copy2(DB_CPS, bak)
        log(f"CPS Backup: {os.path.basename(bak)}", "OK")
    except Exception as e:
        log(f"Backup hatasi: {e}", "ERR")
        return 2

    # 3) 5055 READ-ONLY baglan
    uri_5055 = "file:" + DB_5055.replace("\\", "/") + "?mode=ro&nolock=1"
    try:
        c5055 = sqlite3.connect(uri_5055, uri=True, timeout=5)
        c5055.row_factory = sqlite3.Row
        log("5055 baglanti (READ ONLY)", "OK")
    except Exception as e:
        log(f"5055 baglanti hatasi: {e}", "ERR")
        return 3

    # 4) CPS write modda baglan
    try:
        ccps = sqlite3.connect(DB_CPS, timeout=10)
        log("CPS baglanti (WRITE)", "OK")
    except Exception as e:
        log(f"CPS baglanti hatasi: {e}", "ERR")
        c5055.close()
        return 4

    try:
        # 5) Pre-import CPS durumu
        cur = ccps.cursor()
        once_toplam = cur.execute("SELECT COUNT(*) FROM uretim_kayit").fetchone()[0]
        once_legacy = cur.execute("SELECT COUNT(*) FROM uretim_kayit WHERE kaynak=?", (KAYNAK_LABEL,)).fetchone()[0]
        log("")
        log("--- Pre-import CPS durumu ---")
        log(f"  Toplam kayit       : {once_toplam}")
        log(f"  LEGACY_5055 kayit  : {once_legacy}")

        # 6) 5055'ten bugunku kayitlari oku
        log("")
        log("--- 5055'ten BUGUN kayitlari okuma ---")
        rows = c5055.execute("""
            SELECT id, emir_no, model_kod, model_adi, miktar,
                   personel_id, personel_ad, proses_adi,
                   tarih, saat, onay_durum, usta_ad, usta_not, onay_tarihi, olusturma
              FROM uretim_kayit
             WHERE date(tarih) = date('now', 'localtime')
             ORDER BY id ASC
        """).fetchall()
        log(f"  Okunan: {len(rows)} kayit")

        if not rows:
            log("Bugunku kayit yok - import atlandi", "WARN")
            c5055.close()
            ccps.close()
            return 0

        # Ilk birkac orneği goster
        log("  Ornek ilk 3:")
        for r in rows[:3]:
            log(f"    id={r['id']} emir={r['emir_no']} miktar={r['miktar']} pers={r['personel_ad']} proses={(r['proses_adi'] or '')[:30]}")

        # 7) Batch INSERT OR IGNORE
        log("")
        log("--- CPS'e INSERT OR IGNORE ---")
        cur.execute("BEGIN TRANSACTION")

        import_dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        eklenen = 0
        atlanan = 0

        for r in rows:
            ih = import_hash_gen(LEGACY_DB_LABEL, r["id"])

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
                # unique index ihlali -> zaten import edilmis
                if "UNIQUE" in str(e).upper():
                    atlanan += 1
                else:
                    raise

        ccps.commit()
        log(f"  Eklenen: {eklenen}", "OK")
        log(f"  Atlanan (zaten var): {atlanan}", "INFO")

        # 8) Post-import durum
        log("")
        log("--- Post-import CPS durumu ---")
        sonra_toplam = cur.execute("SELECT COUNT(*) FROM uretim_kayit").fetchone()[0]
        sonra_legacy = cur.execute("SELECT COUNT(*) FROM uretim_kayit WHERE kaynak=?", (KAYNAK_LABEL,)).fetchone()[0]
        log(f"  Toplam kayit       : {sonra_toplam} (+{sonra_toplam-once_toplam})")
        log(f"  LEGACY_5055 kayit  : {sonra_legacy} (+{sonra_legacy-once_legacy})")

        # Dagilim
        log("")
        log("--- Kaynak dagilimi ---")
        for r in cur.execute("SELECT kaynak, COUNT(*) FROM uretim_kayit GROUP BY kaynak").fetchall():
            log(f"  kaynak='{r[0]}': {r[1]} kayit")

        # 9) Import edilen kayitlardan birkac orneği goster
        log("")
        log("--- Import edilen ornek (son 3) ---")
        for r in cur.execute("""
            SELECT id, emir_no, miktar, personel_ad, proses_adi, onay_durum, legacy_id, import_hash
              FROM uretim_kayit
             WHERE kaynak=?
             ORDER BY id DESC LIMIT 3
        """, (KAYNAK_LABEL,)).fetchall():
            log(f"  cps_id={r[0]} legacy_id={r[6]} hash={r[7]} emir={r[1]} miktar={r[2]} pers={r[3]} proses={(r[4] or '')[:25]} onay={r[5]}")

        log("")
        log("=" * 70)
        log("IMPORT BASARILI", "OK")
        log("=" * 70)
        log(f"Backup       : {os.path.basename(bak)}")
        log(f"Yeni eklenen : {eklenen}")
        log(f"Atlanan      : {atlanan}")
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