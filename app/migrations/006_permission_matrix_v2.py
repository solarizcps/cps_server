# -*- coding: utf-8 -*-
"""
006_permission_matrix_v2.py
============================
Yetki Sistemi V2 - PATCH B

1. sistem_rol_yetki tablosuna 7 yeni kolon ekler (idempotent).
   - can_view, can_create, can_update, can_delete, can_approve, can_report, can_manage
2. user_permission_override tablosunu olusturur (idempotent).
3. Mevcut Gorebilir / Duzenleyebilir kolonlarini V2 boyutlarina map eder.

Mapping (veri migrasyonu - secim A):
   Gorebilir=1     -> can_view=1, can_report=1
   Duzenleyebilir=1 -> can_create=1, can_update=1
   can_delete, can_approve, can_manage -> 0 (default)

Riskler:
- ALTER TABLE: kolon varsa SKIP, yoksa ADD COLUMN. Idempotent.
- Eski Gorebilir / Duzenleyebilir kolonlari KORUNUR (geriye uyum).
- Mevcut endpointler / sidebar / decorator etkilenmez.
- Transaction: hata olursa ROLLBACK.

Rollback:
  Snapshot rollback (STABLE_YETKI_V2_PATCH_A_DONE_*).
  Veya manuel:
    DROP TABLE user_permission_override;
    (SQLite ALTER DROP COLUMN destegi 3.35+, yeni tablo yaratip kopyala yontemi)
"""
import os, sys, sqlite3, shutil, datetime

CPS_DB = r"D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\mock_data.db"

# Eklenecek yeni kolonlar (tum INTEGER DEFAULT 0)
NEW_COLUMNS = [
    "can_view",
    "can_create",
    "can_update",
    "can_delete",
    "can_approve",
    "can_report",
    "can_manage",
]

def log(msg, level="INFO"):
    pfx = {"INFO":"[INFO]","OK":"[OK]","ERR":"[HATA]","WARN":"[UYARI]","SKIP":"[SKIP]"}.get(level,"[INFO]")
    print(f"{pfx} {msg}")

def get_existing_columns(cur, table):
    """PRAGMA table_info ile mevcut kolon adlarini liste olarak don."""
    return [r[1] for r in cur.execute(f"PRAGMA table_info({table})")]

def main():
    log("=" * 70)
    log("PATCH B - permission_matrix V2 (sistem_rol_yetki + user_permission_override)")
    log("=" * 70)

    if not os.path.exists(CPS_DB):
        log("CPS DB yok: " + CPS_DB, "ERR")
        return 1

    log(f"DB: {CPS_DB}")
    log(f"DB boyut: {os.path.getsize(CPS_DB)} byte")

    # Backup
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = CPS_DB + ".YEDEK_PERMISSION_V2_" + ts
    shutil.copy2(CPS_DB, bak)
    log(f"Backup: {os.path.basename(bak)}", "OK")

    conn = sqlite3.connect(CPS_DB, timeout=10)
    try:
        cur = conn.cursor()

        cur.execute("BEGIN TRANSACTION")
        log("Transaction baslatildi", "OK")

        # =============================================
        # 1) sistem_rol_yetki tablosuna 7 yeni kolon
        # =============================================
        log("")
        log("--- ADIM 1: sistem_rol_yetki kolonlari ---")

        existing_cols = get_existing_columns(cur, "sistem_rol_yetki")
        log(f"  Mevcut kolonlar: {existing_cols}")

        eklenen_kolon = 0
        atlanan_kolon = 0

        for col in NEW_COLUMNS:
            if col in existing_cols:
                log(f"  {col:15s}: zaten var", "SKIP")
                atlanan_kolon += 1
            else:
                cur.execute(f"ALTER TABLE sistem_rol_yetki ADD COLUMN {col} INTEGER DEFAULT 0")
                log(f"  {col:15s}: eklendi", "OK")
                eklenen_kolon += 1

        log("")
        log(f"  Eklenen: {eklenen_kolon}/7  Atlanan: {atlanan_kolon}/7")

        # Index for V2 kolonlari (performans icin)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sry_rol_yetki ON sistem_rol_yetki(RolId, YetkiId)")
        log("  Index idx_sry_rol_yetki OK", "OK")

        # =============================================
        # 2) Veri migrasyonu (mapping)
        # =============================================
        log("")
        log("--- ADIM 2: Veri migrasyonu (Gorebilir/Duzenleyebilir -> 7 boyut) ---")

        # Sadece yeni eklenen kolonlari guncelle. Zaten varsa dokunma (idempotent).
        if "can_view" not in existing_cols:
            cur.execute("UPDATE sistem_rol_yetki SET can_view = Gorebilir")
            log("  can_view = Gorebilir", "OK")
        if "can_report" not in existing_cols:
            cur.execute("UPDATE sistem_rol_yetki SET can_report = Gorebilir")
            log("  can_report = Gorebilir", "OK")
        if "can_create" not in existing_cols:
            cur.execute("UPDATE sistem_rol_yetki SET can_create = Duzenleyebilir")
            log("  can_create = Duzenleyebilir", "OK")
        if "can_update" not in existing_cols:
            cur.execute("UPDATE sistem_rol_yetki SET can_update = Duzenleyebilir")
            log("  can_update = Duzenleyebilir", "OK")
        # can_delete, can_approve, can_manage -> 0 (default)
        log("  can_delete/can_approve/can_manage: 0 (default)", "OK")

        # =============================================
        # 3) user_permission_override tablosu
        # =============================================
        log("")
        log("--- ADIM 3: user_permission_override tablosu ---")

        upo_exists = cur.execute(
            "SELECT name FROM sqlite_master WHERE type=\u0027table\u0027 AND name=\u0027user_permission_override\u0027"
        ).fetchone()

        if upo_exists:
            log("user_permission_override zaten var", "SKIP")
        else:
            cur.execute("""
                CREATE TABLE user_permission_override (
                    Id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    KullaniciId     INTEGER NOT NULL,
                    YetkiId         INTEGER NOT NULL,
                    can_view        INTEGER,
                    can_create      INTEGER,
                    can_update      INTEGER,
                    can_delete      INTEGER,
                    can_approve     INTEGER,
                    can_report      INTEGER,
                    can_manage      INTEGER,
                    aciklama        TEXT,
                    olusturma_tarih TEXT DEFAULT (datetime(\u0027now\u0027)),
                    olusturan       TEXT,
                    UNIQUE (KullaniciId, YetkiId)
                )
            """)
            log("Tablo OK", "OK")

            cur.execute("CREATE INDEX IF NOT EXISTS idx_upo_kullanici ON user_permission_override(KullaniciId)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_upo_yetki     ON user_permission_override(YetkiId)")
            log("2 index OK", "OK")

        # =============================================
        # 4) COMMIT
        # =============================================
        conn.commit()
        log("")
        log("Transaction COMMIT", "OK")

        # =============================================
        # 5) Dogrulama
        # =============================================
        log("")
        log("--- DOGRULAMA ---")

        # 5a) sistem_rol_yetki kolonlari
        final_cols = get_existing_columns(cur, "sistem_rol_yetki")
        log(f"  sistem_rol_yetki kolonlari ({len(final_cols)}): {final_cols}")
        missing = [c for c in NEW_COLUMNS if c not in final_cols]
        if missing:
            log(f"  EKSIK KOLONLAR: {missing}", "ERR")
            return 2
        log(f"  Tum 7 kolon mevcut", "OK")

        # 5b) Kayit sayisi degisti mi?
        toplam = cur.execute("SELECT COUNT(*) FROM sistem_rol_yetki").fetchone()[0]
        log(f"  Toplam kayit: {toplam} (PATCH oncesi 61 idi)")

        # 5c) Mapping dogru mu?
        log("")
        log("  Mapping dogrulamasi:")
        gor = cur.execute("SELECT COUNT(*) FROM sistem_rol_yetki WHERE Gorebilir=1").fetchone()[0]
        duz = cur.execute("SELECT COUNT(*) FROM sistem_rol_yetki WHERE Duzenleyebilir=1").fetchone()[0]
        cv  = cur.execute("SELECT COUNT(*) FROM sistem_rol_yetki WHERE can_view=1").fetchone()[0]
        cr  = cur.execute("SELECT COUNT(*) FROM sistem_rol_yetki WHERE can_report=1").fetchone()[0]
        cc  = cur.execute("SELECT COUNT(*) FROM sistem_rol_yetki WHERE can_create=1").fetchone()[0]
        cu  = cur.execute("SELECT COUNT(*) FROM sistem_rol_yetki WHERE can_update=1").fetchone()[0]
        cd  = cur.execute("SELECT COUNT(*) FROM sistem_rol_yetki WHERE can_delete=1").fetchone()[0]
        ca  = cur.execute("SELECT COUNT(*) FROM sistem_rol_yetki WHERE can_approve=1").fetchone()[0]
        cm  = cur.execute("SELECT COUNT(*) FROM sistem_rol_yetki WHERE can_manage=1").fetchone()[0]
        log(f"    Gorebilir=1      : {gor}")
        log(f"    can_view=1       : {cv}  (esit: {gor==cv})")
        log(f"    can_report=1     : {cr}  (esit: {gor==cr})")
        log(f"    Duzenleyebilir=1 : {duz}")
        log(f"    can_create=1     : {cc}  (esit: {duz==cc})")
        log(f"    can_update=1     : {cu}  (esit: {duz==cu})")
        log(f"    can_delete=1     : {cd}  (beklenen: 0)")
        log(f"    can_approve=1    : {ca}  (beklenen: 0)")
        log(f"    can_manage=1     : {cm}  (beklenen: 0)")

        if gor != cv or gor != cr or duz != cc or duz != cu or cd != 0 or ca != 0 or cm != 0:
            log("  MAPPING SAPMASI!", "WARN")
        else:
            log("  Mapping dogru", "OK")

        # 5d) user_permission_override
        upo_check = cur.execute(
            "SELECT name FROM sqlite_master WHERE type=\u0027table\u0027 AND name=\u0027user_permission_override\u0027"
        ).fetchone()
        log("  user_permission_override tablosu: " + ("VAR" if upo_check else "YOK"))
        if not upo_check:
            log("user_permission_override OLUSMAMIS!", "ERR")
            return 3

        upo_count = cur.execute("SELECT COUNT(*) FROM user_permission_override").fetchone()[0]
        log(f"  user_permission_override kayit: {upo_count} (beklenen: 0)")

        # 5e) module_registry hala 32 mi?
        mreg = cur.execute("SELECT COUNT(*) FROM module_registry").fetchone()[0]
        log(f"  module_registry kayit: {mreg} (beklenen: 32)")

        log("")
        log("=" * 70)
        log("PATCH B MIGRATION BASARILI", "OK")
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
