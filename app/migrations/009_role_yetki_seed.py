# -*- coding: utf-8 -*-
"""
009_role_yetki_seed.py
=======================
C2.B PATCH - Bos rollere minimum V2 yetki seti

INSERT only, idempotent. Mevcut kayitlar dokunulmaz.

Roller:
  - Enjeksiyon (RolId=35, Ferhat) - 6 yetki
  - Kalite (RolId=33, nesrisamet) - 4 yetki
  - Idari Isler (RolId=34, ibrahim) - 2 yetki
  - Planlama (RolId=32, mehmet+mehmetemin) - 7 yetki

Toplam: 19 yeni INSERT.

KURAL:
  - INSERT OR IGNORE mantigi (UNIQUE RolId+YetkiId kontrolu)
  - Eski Gorebilir/Duzenleyebilir kolonu da set edilir (geriye uyum)
  - V2 7 boyut + 2 eski kolon = 9 kolon
  - can_delete / can_manage / can_approve: minimum principle, hepsi 0
"""
import os
import sys
import sqlite3
import shutil
import datetime

CPS_DB = r"D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\mock_data.db"

# ============================================================
# SEED: (RolId, YetkiId, view, create, update, delete, approve, report, manage)
# ============================================================
SEED = [
    # ====== ENJEKSIYON (RolId=35, Ferhat Usta) - 6 yetki ======
    (35, 135, 1, 0, 0, 0, 0, 1, 0),  # enjeksiyon - modul gorunurluk
    (35, 136, 1, 1, 1, 0, 0, 1, 0),  # enjeksiyon.saha - ASIL IS
    (35, 139, 1, 0, 0, 0, 0, 1, 0),  # planlama.operasyon_raporu - view/report
    (35, 142, 1, 0, 0, 0, 0, 1, 0),  # hedef - view only
    (35, 145, 1, 0, 1, 0, 0, 1, 0),  # tasks - kendine atanani guncelle
    (35, 147, 1, 0, 1, 0, 0, 1, 0),  # usta - usta paneli

    # ====== KALITE (RolId=33, nesrisamet) - 4 yetki ======
    (33, 139, 1, 0, 0, 0, 0, 1, 0),  # planlama.operasyon_raporu
    (33, 142, 1, 0, 0, 0, 0, 1, 0),  # hedef - view only
    (33, 144, 1, 0, 0, 0, 0, 1, 0),  # hedef.sapma - KALITE KRITIK
    (33, 145, 1, 0, 1, 0, 0, 1, 0),  # tasks - update

    # ====== IDARI ISLER (RolId=34, ibrahim) - 2 yetki ======
    (34, 139, 1, 0, 0, 0, 0, 1, 0),  # planlama.operasyon_raporu - genel bakis
    (34, 145, 1, 1, 1, 0, 0, 1, 0),  # tasks - olustur/takip

    # ====== PLANLAMA (RolId=32, mehmet+mehmetemin) - 7 yetki ======
    (32, 138, 1, 0, 0, 0, 0, 1, 0),  # planlama - modul gorunurluk
    (32, 139, 1, 0, 0, 0, 0, 1, 0),  # planlama.operasyon_raporu - view
    (32, 140, 1, 0, 0, 0, 0, 1, 0),  # planlama.proses_takip - view
    (32, 141, 1, 1, 1, 0, 0, 1, 0),  # planlama.karar_masasi - SINIRLI ISLEM
    (32, 142, 1, 0, 0, 0, 0, 1, 0),  # hedef - view only
    (32, 144, 1, 0, 0, 0, 0, 1, 0),  # hedef.sapma
    (32, 145, 1, 0, 1, 0, 0, 1, 0),  # tasks - update
]


def log(msg, level="INFO"):
    pfx = {"INFO":"[INFO]","OK":"[OK]","ERR":"[HATA]","WARN":"[UYARI]","SKIP":"[SKIP]"}.get(level,"[INFO]")
    print(pfx + " " + msg)


def main():
    log("=" * 70)
    log("PATCH C2.B - Bos rollere V2 yetki seed (19 INSERT)")
    log("=" * 70)
    log("")

    if not os.path.exists(CPS_DB):
        log("CPS DB yok: " + CPS_DB, "ERR")
        return 1

    log("DB: " + CPS_DB)
    log("DB boyut: " + str(os.path.getsize(CPS_DB)) + " byte")

    # Backup
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = CPS_DB + ".YEDEK_ROLE_YETKI_" + ts
    shutil.copy2(CPS_DB, bak)
    log("Backup: " + os.path.basename(bak), "OK")
    log("")

    conn = sqlite3.connect(CPS_DB, timeout=10)
    try:
        cur = conn.cursor()

        # On-durum
        on = cur.execute("SELECT COUNT(*) FROM sistem_rol_yetki").fetchone()[0]
        log("On-durum: sistem_rol_yetki kayit = " + str(on))

        # Yetki kodu dogrulamasi - tum YetkiId'ler sistem_yetki'de var mi?
        all_yetki_ids = set(r[1] for r in SEED)
        for yid in all_yetki_ids:
            mev = cur.execute("SELECT Kod FROM sistem_yetki WHERE Id = ?", (yid,)).fetchone()
            if not mev:
                log("YetkiId " + str(yid) + " sistem_yetki'de YOK! Iptal.", "ERR")
                return 2

        # Rol dogrulamasi
        all_rol_ids = set(r[0] for r in SEED)
        for rid in all_rol_ids:
            mev = cur.execute("SELECT Ad FROM sistem_rol WHERE Id = ?", (rid,)).fetchone()
            if not mev:
                log("RolId " + str(rid) + " sistem_rol'de YOK! Iptal.", "ERR")
                return 3

        log("Tum YetkiId ve RolId dogrulamalari OK", "OK")
        log("")

        cur.execute("BEGIN TRANSACTION")
        log("Transaction baslatildi", "OK")
        log("")

        log("--- 19 yetki bagi INSERT ediliyor ---")
        eklenen = 0
        atlanan = 0
        eklenen_detay = []

        for row in SEED:
            (rol_id, yetki_id, view, create, update, delete, approve, report, manage) = row

            # Idempotent kontrol
            mevcut = cur.execute("""
                SELECT Id FROM sistem_rol_yetki 
                WHERE RolId = ? AND YetkiId = ?
            """, (rol_id, yetki_id)).fetchone()

            # Rol ve yetki adlari (log icin)
            rol_ad = cur.execute("SELECT Ad FROM sistem_rol WHERE Id = ?", (rol_id,)).fetchone()[0]
            yetki_kod = cur.execute("SELECT Kod FROM sistem_yetki WHERE Id = ?", (yetki_id,)).fetchone()[0]

            if mevcut:
                atlanan += 1
                log("  [SKIP] " + rol_ad + " <-> " + yetki_kod + " zaten var (Id=" + str(mevcut[0]) + ")", "SKIP")
                continue

            # Eski kolon mapping (geriye uyum)
            gorebilir = 1 if view else 0
            duzenleyebilir = 1 if (create or update) else 0

            cur.execute("""
                INSERT INTO sistem_rol_yetki 
                (RolId, YetkiId, Gorebilir, Duzenleyebilir,
                 can_view, can_create, can_update, can_delete,
                 can_approve, can_report, can_manage)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (rol_id, yetki_id, gorebilir, duzenleyebilir,
                  view, create, update, delete, approve, report, manage))

            eklenen += 1
            eklenen_detay.append((rol_ad, yetki_kod, view, create, update, delete, approve, report, manage))
            actions = []
            if view: actions.append("V")
            if create: actions.append("C")
            if update: actions.append("U")
            if delete: actions.append("D")
            if approve: actions.append("A")
            if report: actions.append("R")
            if manage: actions.append("M")
            action_str = "/".join(actions)
            log("  [OK]   " + rol_ad + " <-> " + yetki_kod + " (" + action_str + ")", "OK")

        log("")
        log("Eklenen: " + str(eklenen) + "/19  Atlanan: " + str(atlanan) + "/19")

        conn.commit()
        log("")
        log("Transaction COMMIT", "OK")
        log("")

        # ============================================
        # DOGRULAMA
        # ============================================
        log("--- DOGRULAMA ---")
        log("")

        son = cur.execute("SELECT COUNT(*) FROM sistem_rol_yetki").fetchone()[0]
        log("sistem_rol_yetki kayit: " + str(son) + " (on-durum " + str(on) + ", beklenen " + str(on + eklenen) + ")")

        # Her rol icin yetki sayisi (dogrulama)
        log("")
        log("Rol bazinda guncel yetki sayisi:")
        for rid in (32, 33, 34, 35):
            cnt = cur.execute("SELECT COUNT(*) FROM sistem_rol_yetki WHERE RolId = ?", (rid,)).fetchone()[0]
            rad = cur.execute("SELECT Ad FROM sistem_rol WHERE Id = ?", (rid,)).fetchone()[0]
            log("  RolId=" + str(rid) + "  " + rad + ":  " + str(cnt) + " yetki")

        # Ferhat'in (RolId=35) yetkilerini detayli goster
        log("")
        log("FERHAT (RolId=35) yeni yetki listesi:")
        rows = cur.execute("""
            SELECT y.Kod, ry.can_view, ry.can_create, ry.can_update,
                   ry.can_delete, ry.can_approve, ry.can_report, ry.can_manage,
                   ry.Gorebilir, ry.Duzenleyebilir
            FROM sistem_rol_yetki ry
            JOIN sistem_yetki y ON y.Id = ry.YetkiId
            WHERE ry.RolId = 35
            ORDER BY y.Kod
        """).fetchall()
        for r in rows:
            actions = []
            if r[1]: actions.append("can_view")
            if r[2]: actions.append("can_create")
            if r[3]: actions.append("can_update")
            if r[4]: actions.append("can_delete")
            if r[5]: actions.append("can_approve")
            if r[6]: actions.append("can_report")
            if r[7]: actions.append("can_manage")
            log("  " + r[0].ljust(35) + " | " + ", ".join(actions))
            log("    (eski: Gorebilir=" + str(r[8]) + " Duzenleyebilir=" + str(r[9]) + ")")

        log("")
        log("=" * 70)
        log("PATCH C2.B BASARILI", "OK")
        log("=" * 70)
        log("Backup: " + os.path.basename(bak))
        log("Sonraki: servis restart + regression + Ferhat yetki dump")
        return 0

    except Exception as e:
        try:
            conn.rollback()
        except: pass
        log("HATA: " + str(e), "ERR")
        log("Rollback yapildi", "WARN")
        log("DB Backup: " + os.path.basename(bak))
        import traceback
        traceback.print_exc()
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())