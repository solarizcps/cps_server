# -*- coding: utf-8 -*-
"""
005_module_registry.py
=======================
Yetki Sistemi V2 - PATCH A

1. module_registry tablosunu olusturur (idempotent).
2. 4 index olusturur.
3. 30 temel modul kaydini seed olarak ekler (INSERT OR IGNORE).

Riskler:
- Yeni tablo, mevcut sistem dokunulmaz.
- Sidebar henuz buradan beslenmez.
- Decorator henuz buradan okumaz.
- Servis davranisi tamamen ayni kalir.

Rollback:
  DROP TABLE module_registry; (veya snapshot rollback)
"""
import os, sys, sqlite3, shutil, datetime

CPS_DB = r"D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\mock_data.db"

def log(msg, level="INFO"):
    pfx = {"INFO":"[INFO]","OK":"[OK]","ERR":"[HATA]","WARN":"[UYARI]","SKIP":"[SKIP]"}.get(level,"[INFO]")
    print(f"{pfx} {msg}")

# ============================================================
# 30 SEED KAYDI
# ============================================================
# Tuple: (module_key, module_name, module_desc, parent_key, menu_group,
#         icon, url, active_key, sira, is_active, is_hidden, is_system,
#         permission_key, blueprint)

SEED = [
    # === OZET ===
    ("home",                    "Ana Sayfa",            "Anasayfa - tum kullanicilara acik",    None,            "Ozet",     "home",            "/",                            "home",       10, 1, 0, 1, None,                          "home"),
    ("tasks",                   "Gorevler",             "Atanmis gorevler listesi",             None,            "Ozet",     "check-square",    "/tasks",                       "tasks",      20, 1, 0, 0, "tasks",                       "tasks"),

    # === URETIM ===
    ("hedef",                   "Hedef Yonetimi",       "Uretim hedefleri ve onaylar",          None,            "Uretim",   "target",          "/hedef/",                      "hedef",      30, 1, 0, 0, "hedef",                       "hedef"),
    ("hedef.sablon",            "Sablon / Proses",      "Hedef sablonlari",                     "hedef",         "Uretim",   "layout",          "/hedef/sablon",                "hedef",      31, 1, 0, 0, "hedef.sablon",                "hedef"),
    ("hedef.sapma",             "Sapma Analizi",        "Hedef-gerceklesen sapma raporu",       "hedef",         "Uretim",   "trending-up",     "/hedef/sapma",                 "hedef",      32, 1, 0, 0, "hedef.sapma",                 "hedef"),
    ("enjeksiyon",              "Enjeksiyon Takip",     "Saha enjeksiyon paneli",               None,            "Uretim",   "tool",            "/enjeksiyon/",                 "enjeksiyon", 40, 1, 0, 0, "enjeksiyon",                  "enjeksiyon"),
    ("enjeksiyon.saha",         "Saha Ekrani",          "Tablet/mobil saha ekrani",             "enjeksiyon",    "Uretim",   "smartphone",      "/enjeksiyon/saha",             "enjeksiyon", 41, 1, 0, 0, "enjeksiyon.saha",             "enjeksiyon"),
    ("enjeksiyon.yonetim",      "Enjeksiyon Yonetim",   "Makine ve istasyon yonetim paneli",    "enjeksiyon",    "Uretim",   "settings",        "/enjeksiyon/",                 "enjeksiyon", 42, 1, 0, 0, "enjeksiyon.yonetim",          "enjeksiyon"),
    ("personel_giris",          "Uretim Girisi",        "Personel uretim girisi",               None,            "Uretim",   "user-check",      "/personel-giris/",             "personel",   50, 1, 0, 0, "personel_giris",              "personel_giris"),
    ("usta",                    "Usta Paneli",          "Usta onay paneli",                     None,            "Uretim",   "hard-hat",        "/usta/",                       "usta",       60, 1, 0, 0, "usta",                        "usta"),
    ("canli_saha",              "Canli Saha (5055)",    "5055 canli saha viewer",               None,            "Uretim",   "radio",           "/canli-saha/",                 "canli_saha", 70, 1, 0, 0, "canli_saha",                  "canli_saha"),

    # === PLANLAMA ===
    ("planlama",                "Planlama",             "Planlama modulu",                      None,            "Planlama", "clipboard",       "/planlama/",                   "planlama",   80, 1, 0, 0, "planlama",                    "planlama"),
    ("planlama.proses_takip",   "Proses Takip",         "Proses rota takip",                    "planlama",      "Planlama", "activity",        "/planlama/proses-takip",       "planlama",   81, 1, 0, 0, "planlama.proses_takip",       "planlama"),
    ("planlama.karar_masasi",   "Karar Masasi",         "Sevkiyat karar masasi",                "planlama",      "Planlama", "clipboard",       "/planlama/karar-masasi",       "planlama",   82, 1, 0, 0, "planlama.karar_masasi",       "planlama"),
    ("planlama.operasyon_raporu","Operasyon Raporu",    "Saha operasyon raporu (canli+gecmis)", "planlama",      "Planlama", "bar-chart",       "/planlama/operasyon-raporu",   "planlama",   83, 1, 0, 0, "planlama.operasyon_raporu",   "planlama"),

    # === FINANS ===
    ("finans",                  "Finans",               "Finans modulu",                        None,            "Finans",   "dollar-sign",     "/finans/",                     "finans",     90, 1, 0, 0, "finans",                      "finans"),
    ("finans.anlasma",          "Anlasmalar",           "Musteri anlasma yonetimi",             "finans",        "Finans",   "file-text",       "/finans/anlasma",              "finans",     91, 1, 0, 0, "finans.anlasma",              "finans"),
    ("finans.cari",             "Cari Hesaplar",        "Cari hesap ekstreleri",                "finans",        "Finans",   "users",           "/finans/cari",                 "finans",     92, 1, 0, 0, "finans.cari",                 "finans"),
    ("finans.simulator",        "Maliyet Simulator",    "Maliyet hesaplama araci",              "finans",        "Finans",   "calculator",      "/finans/simulator",            "finans",     93, 1, 0, 0, "finans.simulator",            "finans"),
    ("finans.cin_ofis",         "Cin Ofis Import",      "Cin ofis veri aktarimi",               "finans",        "Finans",   "upload",          "/finans/cin-ofis",             "finans",     94, 1, 0, 0, "finans.cin_ofis",             "finans"),

    # === GRAFIK ===
    ("grafik",                  "Grafik Paneli",        "Grafik modulu (urun/numune/tedarikci)",None,            "Grafik",   "layers",          "/grafik/",                     "grafik",     100,1, 0, 0, "grafik",                      "grafik"),
    ("grafik.urun",             "Urun Yonetimi",        "Urun kayitlari",                       "grafik",        "Grafik",   "box",             "/grafik/urun",                 "grafik",     101,1, 0, 0, "grafik.urun",                 "grafik"),
    ("grafik.numune",           "Numune Takip",         "Numune onay ve takip",                 "grafik",        "Grafik",   "flask",           "/grafik/numune",               "grafik",     102,1, 0, 0, "grafik.numune",               "grafik"),
    ("grafik.tedarikci",        "Tedarikciler",         "Tedarikci karti",                      "grafik",        "Grafik",   "truck",           "/grafik/tedarikci",            "grafik",     103,1, 0, 0, "grafik.tedarikci",            "grafik"),
    ("grafik.siparis",          "Cin Siparis",          "Cin siparis takip",                    "grafik",        "Grafik",   "shopping-cart",   "/grafik/siparis",              "grafik",     104,1, 0, 0, "grafik.cin_siparis",          "grafik"),
    ("grafik.sevkiyat",         "Sevkiyat ve Maliyet",  "Sevkiyat maliyet hesabi",              "grafik",        "Grafik",   "ship",            "/grafik/sevkiyat",             "grafik",     105,1, 0, 0, "grafik.maliyet",              "grafik"),

    # === ITHALAT ===
    ("ithalat.parti",           "Ithalat Parti",        "Ithalat parti takibi",                 None,            "Ithalat",  "package",         "/ithalat/parti/liste",         "ithalat",    110,1, 0, 0, "ithalat.parti",               "ithalat"),

    # === YONETIM ===
    ("yonetim",                 "Yonetim Paneli",       "Yonetim ana paneli",                   None,            "Yonetim",  "shield",          "/yonetim/",                    "yonetim",    120,1, 0, 1, "yonetim",                     "yonetim"),
    ("yonetim.kullanici",       "Kullanicilar",         "Kullanici yonetimi",                   "yonetim",       "Yonetim",  "user",            "/yonetim/kullanici",           "yonetim",    121,1, 0, 1, "yonetim.kullanici",           "yonetim"),
    ("yonetim.rol",             "Roller ve Yetkiler",   "Rol ve yetki yonetimi",                "yonetim",       "Yonetim",  "lock",            "/yonetim/rol",                 "yonetim",    122,1, 0, 1, "yonetim.rol",                 "yonetim"),
    ("yonetim.kur",             "Kur Tanimlari",        "Doviz kuru tanimlari",                 "yonetim",       "Yonetim",  "trending-up",     "/yonetim/kur",                 "yonetim",    123,1, 0, 0, "yonetim.kur",                 "yonetim"),
    ("yonetim.log",             "Audit Log",            "Sistem aktivite gecmisi",              "yonetim",       "Yonetim",  "activity",        "/yonetim/log",                 "yonetim",    124,1, 0, 1, "yonetim.log",                 "yonetim"),
]

def main():
    log("=" * 70)
    log("PATCH A - module_registry MIGRATION + SEED")
    log("=" * 70)

    if not os.path.exists(CPS_DB):
        log("CPS DB yok: " + CPS_DB, "ERR")
        return 1

    log(f"DB: {CPS_DB}")
    log(f"DB boyut: {os.path.getsize(CPS_DB)} byte")

    # Backup
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = CPS_DB + ".YEDEK_MODULE_REG_" + ts
    shutil.copy2(CPS_DB, bak)
    log(f"Backup: {os.path.basename(bak)}", "OK")

    conn = sqlite3.connect(CPS_DB, timeout=10)
    try:
        cur = conn.cursor()

        # 1) Tablo var mi?
        existing = cur.execute(
            "SELECT name FROM sqlite_master WHERE type=\u0027table\u0027 AND name=\u0027module_registry\u0027"
        ).fetchone()

        cur.execute("BEGIN TRANSACTION")
        log("Transaction baslatildi", "OK")

        if existing:
            log("module_registry tablosu zaten var", "SKIP")
        else:
            log("")
            log("--- Tablo olusturuluyor ---")
            cur.execute("""
                CREATE TABLE module_registry (
                    module_key       TEXT PRIMARY KEY,
                    module_name      TEXT NOT NULL,
                    module_desc      TEXT,
                    parent_key       TEXT,
                    menu_group       TEXT,
                    icon             TEXT,
                    url              TEXT,
                    active_key       TEXT,
                    sira             INTEGER DEFAULT 100,
                    is_active        INTEGER DEFAULT 1,
                    is_hidden        INTEGER DEFAULT 0,
                    is_system        INTEGER DEFAULT 0,
                    permission_key   TEXT,
                    blueprint        TEXT,
                    ozellikler       TEXT,
                    olusturma_tarih  TEXT DEFAULT (datetime(\u0027now\u0027)),
                    olusturan        TEXT,
                    FOREIGN KEY (parent_key) REFERENCES module_registry(module_key)
                )
            """)
            log("Tablo OK", "OK")

            cur.execute("CREATE INDEX IF NOT EXISTS idx_mreg_parent ON module_registry(parent_key)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_mreg_group  ON module_registry(menu_group)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_mreg_active ON module_registry(is_active, is_hidden)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_mreg_perm   ON module_registry(permission_key)")
            log("4 index OK", "OK")

        # 2) Seed verisi
        log("")
        log("--- Seed verisi yukleniyor ---")
        eklenen = 0
        atlanan = 0

        for row in SEED:
            try:
                cur.execute("""
                    INSERT INTO module_registry
                        (module_key, module_name, module_desc, parent_key, menu_group,
                         icon, url, active_key, sira, is_active, is_hidden, is_system,
                         permission_key, blueprint, olusturan)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, row + ("MIGRATION_005",))
                eklenen += 1
            except sqlite3.IntegrityError as e:
                if "UNIQUE" in str(e).upper() or "PRIMARY KEY" in str(e).upper():
                    atlanan += 1
                else:
                    raise

        conn.commit()
        log(f"  Eklenen: {eklenen}", "OK")
        log(f"  Atlanan: {atlanan}", "INFO")

        # 3) Dogrulama
        log("")
        log("--- Post-migration durum ---")
        total = cur.execute("SELECT COUNT(*) FROM module_registry").fetchone()[0]
        log(f"  Toplam module_registry: {total}")

        # Grup dagilimi
        log("")
        log("  Grup dagilimi:")
        for r in cur.execute(
            "SELECT menu_group, COUNT(*) FROM module_registry GROUP BY menu_group ORDER BY menu_group"
        ):
            log(f"    {r[0]:12s}: {r[1]} modul")

        # Is_system kayitlar
        log("")
        log("  Sistem modulleri (is_system=1):")
        for r in cur.execute(
            "SELECT module_key, module_name FROM module_registry WHERE is_system=1 ORDER BY module_key"
        ):
            log(f"    {r[0]:25s} {r[1]}")

        # Ilk 5 ornek
        log("")
        log("  Ilk 5 ornek:")
        for r in cur.execute(
            "SELECT module_key, module_name, menu_group, url FROM module_registry ORDER BY sira LIMIT 5"
        ):
            log(f"    {r[0]:20s} | {r[1]:20s} | {r[2]:10s} | {r[3]}")

        log("")
        log("=" * 70)
        log("PATCH A MIGRATION BASARILI", "OK")
        log("=" * 70)
        log(f"Backup: {os.path.basename(bak)}")
        log("Sonraki adim: servis restart + regression test")
        return 0

    except Exception as e:
        try:
            conn.rollback()
        except: pass
        log(f"HATA: {e}", "ERR")
        log("Rollback yapildi", "WARN")
        log(f"Backup: {os.path.basename(bak)}", "INFO")
        import traceback
        traceback.print_exc()
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
