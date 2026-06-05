# -*- coding: utf-8 -*-
"""
007_sistem_yetki_seed.py
=========================
Yetki Sistemi V2 - PATCH C2.A

1. sistem_yetki tablosuna 14 yeni yetki kodu ekler (idempotent).
2. module_registry.permission_key ile birebir eslesir.

Mevcut: 30 yetki kodu
Eklenen: 14 yeni kod
Toplam beklenen: 44
"""
import os, sys, sqlite3, shutil, datetime

CPS_DB = r"D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\mock_data.db"

SEED = [
    # ENJEKSIYON (3 kod)
    ("enjeksiyon",                "Enjeksiyon Modulu",       "Enjeksiyon ana modulu",         "enjeksiyon", None,              100),
    ("enjeksiyon.saha",           "Enjeksiyon Saha Ekrani",  "Tablet/mobil saha ekrani",      "enjeksiyon", "saha",            101),
    ("enjeksiyon.yonetim",        "Enjeksiyon Yonetim",      "Makine/istasyon yonetim",       "enjeksiyon", "yonetim",         102),

    # PLANLAMA (4 kod)
    ("planlama",                  "Planlama Modulu",         "Planlama ana modulu",           "planlama",   None,              110),
    ("planlama.operasyon_raporu", "Operasyon Raporu",        "Saha operasyon raporu",         "planlama",   "operasyon_raporu",111),
    ("planlama.proses_takip",     "Proses Takip",            "Proses rota takip",             "planlama",   "proses_takip",    112),
    ("planlama.karar_masasi",     "Karar Masasi",            "Sevkiyat karar masasi",         "planlama",   "karar_masasi",    113),

    # HEDEF (3 kod)
    ("hedef",                     "Hedef Yonetimi",          "Uretim hedefleri",              "hedef",      None,              120),
    ("hedef.sablon",              "Hedef Sablon",            "Sablon yonetimi",               "hedef",      "sablon",          121),
    ("hedef.sapma",               "Hedef Sapma",             "Hedef-gerceklesen sapma",       "hedef",      "sapma",           122),

    # TASKS (1 kod)
    ("tasks",                     "Gorevler",                "Gorev listesi ve yonetimi",     "tasks",      None,              130),

    # DIGER (3 kod)
    ("personel_giris",            "Uretim Girisi",           "Personel uretim girisi",        "personel_giris", None,          140),
    ("usta",                      "Usta Paneli",             "Usta onay paneli",              "usta",       None,              141),
    ("canli_saha",                "Canli Saha (5055)",       "5055 canli saha viewer",        "canli_saha", None,              142),
]

def log(msg, level="INFO"):
    pfx = {"INFO":"[INFO]","OK":"[OK]","ERR":"[HATA]","WARN":"[UYARI]","SKIP":"[SKIP]"}.get(level,"[INFO]")
    print(f"{pfx} {msg}")

def main():
    log("=" * 70)
    log("PATCH C2.A - sistem_yetki seed (14 yeni yetki kodu)")
    log("=" * 70)

    if not os.path.exists(CPS_DB):
        log("CPS DB yok: " + CPS_DB, "ERR")
        return 1

    log(f"DB: {CPS_DB}")
    log(f"DB boyut: {os.path.getsize(CPS_DB)} byte")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = CPS_DB + ".YEDEK_SISTEM_YETKI_" + ts
    shutil.copy2(CPS_DB, bak)
    log(f"Backup: {os.path.basename(bak)}", "OK")

    conn = sqlite3.connect(CPS_DB, timeout=10)
    try:
        cur = conn.cursor()

        on = cur.execute("SELECT COUNT(*) FROM sistem_yetki").fetchone()[0]
        log(f"On-durum: sistem_yetki kayit = {on}")
        log("")

        cur.execute("BEGIN TRANSACTION")
        log("Transaction baslatildi", "OK")

        log("")
        log("--- 14 yetki kodu ekleniyor ---")

        eklenen = 0
        atlanan = 0
        eklenen_kodlar = []
        atlanan_kodlar = []

        for row in SEED:
            kod = row[0]
            mevcut = cur.execute("SELECT Id FROM sistem_yetki WHERE Kod = ?", (kod,)).fetchone()
            if mevcut:
                atlanan += 1
                atlanan_kodlar.append(kod)
                log(f"  {kod:30s}: zaten var (Id={mevcut[0]})", "SKIP")
            else:
                cur.execute("""
                    INSERT INTO sistem_yetki (Kod, Ad, Aciklama, Modul, AltModul, Sira)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, row)
                eklenen += 1
                eklenen_kodlar.append(kod)
                log(f"  {kod:30s}: eklendi", "OK")

        log("")
        log(f"  Eklenen: {eklenen}/14  Atlanan: {atlanan}/14")

        conn.commit()
        log("")
        log("Transaction COMMIT", "OK")

        log("")
        log("--- DOGRULAMA ---")

        son = cur.execute("SELECT COUNT(*) FROM sistem_yetki").fetchone()[0]
        log(f"  sistem_yetki kayit: {son} (on-durum {on}, beklenen {on + eklenen})")

        kayip = []
        for kod in eklenen_kodlar:
            mev = cur.execute("SELECT Id FROM sistem_yetki WHERE Kod = ?", (kod,)).fetchone()
            if not mev:
                kayip.append(kod)
        if kayip:
            log("  EKSIK KODLAR: " + str(kayip), "ERR")
            return 2
        log("  Tum 14 kod erisilebilir", "OK")

        log("")
        log("  module_registry sistem_yetki esleme kontrolu:")
        sql_check = """
            SELECT mr.module_key, mr.permission_key
            FROM module_registry mr
            WHERE mr.permission_key IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM sistem_yetki sy WHERE sy.Kod = mr.permission_key
              )
            ORDER BY mr.module_key
        """
        eslesmeyen = list(cur.execute(sql_check))
        if eslesmeyen:
            log("  module_registry de var ama sistem_yetki de YOK: " + str(len(eslesmeyen)) + " kayit", "WARN")
            for r in eslesmeyen:
                log(f"    module_key={r[0]:30s} permission_key={r[1]}")
        else:
            log("  Tum module_registry permission_key degerleri sistem_yetki de var", "OK")

        mreg = cur.execute("SELECT COUNT(*) FROM module_registry").fetchone()[0]
        log(f"  module_registry kayit: {mreg} (beklenen 32)")

        sry = cur.execute("SELECT COUNT(*) FROM sistem_rol_yetki").fetchone()[0]
        log(f"  sistem_rol_yetki kayit: {sry} (beklenen 61, dokunulmamis)")

        log("")
        log("  Yeni eklenen kodlardan ornekler:")
        for kod in eklenen_kodlar[:5]:
            r = cur.execute("SELECT Id, Kod, Modul, AltModul, Ad FROM sistem_yetki WHERE Kod = ?", (kod,)).fetchone()
            if r:
                am = r[3] if r[3] else "-"
                log(f"    Id={r[0]:3d}  Kod={r[1]:30s} Modul={r[2]:12s} AltModul={am:18s} Ad={r[4]}")

        log("")
        log("=" * 70)
        log("PATCH C2.A BASARILI", "OK")
        log("=" * 70)
        log(f"Backup: {os.path.basename(bak)}")
        log("Sonraki adim: regression test")
        return 0

    except Exception as e:
        try:
            conn.rollback()
        except: pass
        log("HATA: " + str(e), "ERR")
        log("Rollback yapildi", "WARN")
        log("Backup: " + os.path.basename(bak), "INFO")
        import traceback
        traceback.print_exc()
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
