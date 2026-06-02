# -*- coding: utf-8 -*-
"""
002_personel_kullanici.py
=========================
1. CPS mock_data.db'ye personel_kullanici tablosu ekle (idempotent)
2. 5055'ten aktif=1 personelleri import et (INSERT OR IGNORE)

5055 DB'ye DOKUNMAZ - READ ONLY.
"""
import os, sys, sqlite3, shutil, datetime

CPS_DB  = r"D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\mock_data.db"
DB_5055 = r"D:\Ortak\Solariz-ARGE\solariz.db"
LEGACY_DB_LABEL = "solariz.db"
KAYNAK_LEGACY = "LEGACY_5055"

def log(msg, level="INFO"):
    pfx = {"INFO":"[INFO]","OK":"[OK]","ERR":"[HATA]","WARN":"[UYARI]","SKIP":"[SKIP]"}.get(level,"[INFO]")
    print(f"{pfx} {msg}")

def main():
    log("=" * 70)
    log("FAZ 1 - PERSONEL MIGRATION + IMPORT")
    log("=" * 70)

    if not os.path.exists(CPS_DB):
        log("CPS DB yok", "ERR")
        return 1

    # Backup
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = CPS_DB + ".YEDEK_PERSONEL_MIG_" + ts
    shutil.copy2(CPS_DB, bak)
    log(f"Backup: {os.path.basename(bak)}", "OK")

    conn = sqlite3.connect(CPS_DB, timeout=10)
    try:
        cur = conn.cursor()

        # 1) Tablo var mi?
        existing = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='personel_kullanici'"
        ).fetchone()

        cur.execute("BEGIN TRANSACTION")
        log("Transaction baslatildi", "OK")

        if existing:
            log("personel_kullanici tablosu zaten var", "SKIP")
        else:
            log("")
            log("--- Tablo olusturuluyor ---")
            cur.execute("""
                CREATE TABLE personel_kullanici (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    ad              TEXT NOT NULL,
                    kullanici_adi   TEXT NOT NULL,
                    sifre           TEXT NOT NULL,
                    sicil           TEXT,
                    birim           TEXT,
                    aktif           INTEGER DEFAULT 1,
                    olusturma       TEXT DEFAULT CURRENT_TIMESTAMP,
                    kaynak          TEXT DEFAULT 'CPS_CANLI',
                    legacy_id       INTEGER,
                    legacy_db       TEXT,
                    import_tarihi   TEXT
                )
            """)
            log("Tablo OK", "OK")

            # Index'ler
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pk_legacy_unique "
                        "ON personel_kullanici(kaynak, legacy_db, legacy_id) "
                        "WHERE kaynak = 'LEGACY_5055'")
            log("Unique index (legacy) OK", "OK")

            cur.execute("CREATE INDEX IF NOT EXISTS idx_pk_kullanici "
                        "ON personel_kullanici(kullanici_adi)")
            log("Index (kullanici_adi) OK", "OK")

            cur.execute("CREATE INDEX IF NOT EXISTS idx_pk_aktif "
                        "ON personel_kullanici(aktif)")
            log("Index (aktif) OK", "OK")

        # 2) 5055'ten READ-ONLY import
        log("")
        log("--- 5055'ten aktif=1 personeller okuma ---")
        uri = "file:" + DB_5055.replace("\\", "/") + "?mode=ro&nolock=1"
        c5055 = sqlite3.connect(uri, uri=True, timeout=5)
        c5055.row_factory = sqlite3.Row

        rows = c5055.execute("""
            SELECT id, ad, kullanici_adi, sifre, sicil, birim, aktif, olusturma
              FROM pers_kullanici
             WHERE aktif = 1
             ORDER BY id ASC
        """).fetchall()
        log(f"  Okunan: {len(rows)} aktif personel")

        import_dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        eklenen = 0
        atlanan = 0

        for r in rows:
            try:
                cur.execute("""
                    INSERT INTO personel_kullanici
                        (ad, kullanici_adi, sifre, sicil, birim, aktif, olusturma,
                         kaynak, legacy_id, legacy_db, import_tarihi)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    r["ad"], r["kullanici_adi"], r["sifre"],
                    r["sicil"], r["birim"], r["aktif"], r["olusturma"],
                    KAYNAK_LEGACY, r["id"], LEGACY_DB_LABEL, import_dt
                ))
                eklenen += 1
            except sqlite3.IntegrityError as e:
                if "UNIQUE" in str(e).upper():
                    atlanan += 1
                else:
                    raise

        conn.commit()
        c5055.close()

        log(f"  Eklenen: {eklenen}", "OK")
        log(f"  Atlanan: {atlanan}", "INFO")

        # 3) Dogrulama
        log("")
        log("--- Post-import durum ---")
        total = cur.execute("SELECT COUNT(*) FROM personel_kullanici").fetchone()[0]
        aktif = cur.execute("SELECT COUNT(*) FROM personel_kullanici WHERE aktif=1").fetchone()[0]
        log(f"  Toplam personel_kullanici: {total}")
        log(f"  Aktif personel           : {aktif}")

        # Kaynak dagilimi
        for r in cur.execute("SELECT kaynak, COUNT(*) FROM personel_kullanici GROUP BY kaynak"):
            log(f"  kaynak='{r[0]}': {r[1]} kayit")

        # Ilk 5 ornek
        log("")
        log("  Ilk 5 ornek:")
        for r in cur.execute(
            "SELECT id, ad, kullanici_adi, aktif, kaynak, legacy_id "
            "FROM personel_kullanici ORDER BY id LIMIT 5"
        ):
            ad = (r[1] or "")[:20]
            ku = (r[2] or "")[:20]
            print(f"    id={r[0]} ad='{ad}' ku='{ku}' aktif={r[3]} kaynak={r[4]} legacy={r[5]}")

        # Duplicate check
        dup = cur.execute("""
            SELECT kullanici_adi, COUNT(*) say FROM personel_kullanici
             WHERE aktif=1 GROUP BY kullanici_adi HAVING COUNT(*) > 1
        """).fetchall()
        log("")
        if dup:
            log(f"  UYARI: {len(dup)} duplicate kullanici_adi var", "WARN")
            for d in dup:
                log(f"    '{d[0]}' -> {d[1]} kayit")
        else:
            log("  Duplicate kullanici_adi: yok", "OK")

        log("")
        log("=" * 70)
        log("FAZ 1 MIGRATION + IMPORT BASARILI", "OK")
        log("=" * 70)
        log(f"Backup: {os.path.basename(bak)}")
        return 0

    except Exception as e:
        try:
            conn.rollback()
        except: pass
        log(f"HATA: {e}", "ERR")
        log("Rollback yapildi", "WARN")
        log(f"Backup: {os.path.basename(bak)}", "INFO")
        return 5
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())