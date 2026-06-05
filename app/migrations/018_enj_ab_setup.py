# -*- coding: utf-8 -*-
"""
018_enj_ab_setup.py — ENJ_SETUP_V1 FAZ 1

enj_ab_setup: slot bazli kilitli uretim setup kaydi.
Idempotent CREATE + backfill (mevcut enj_istasyon_durumu).

Calistirma:
  py 018_enj_ab_setup.py
  py 018_enj_ab_setup.py --no-backfill
"""
import os
import sys
import shutil
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(os.path.dirname(BASE_DIR), "mock_data.db")

SETUP_DURUM = ("TASLAK", "AKTIF", "KAPANDI", "IPTAL")


def yedek_al():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    yedek = DB_PATH + ".YEDEK_ENJ_SETUP_V1_" + ts
    shutil.copy2(DB_PATH, yedek)
    print("[YEDEK] " + os.path.basename(yedek))
    return yedek


def tablo_var_mi(con, ad):
    cur = con.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (ad,),
    )
    return cur.fetchone() is not None


def create_schema(con):
    cur = con.cursor()
    if tablo_var_mi(con, "enj_ab_setup"):
        print("[SKIP] enj_ab_setup zaten var")
        return False

    print("[1/3] enj_ab_setup CREATE...")
    cur.execute("""
    CREATE TABLE enj_ab_setup (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        rapor_id            INTEGER NOT NULL
                            REFERENCES enj_gunluk_rapor(id) ON DELETE CASCADE,
        makine_id           INTEGER NOT NULL
                            REFERENCES enj_makine(id),
        slot                TEXT NOT NULL CHECK (slot IN ('A', 'B')),
        kalip_id            INTEGER REFERENCES enj_kalip(id),
        kalip_kod_snapshot  TEXT,
        model_kod_snapshot  TEXT,
        renk                TEXT,
        pisme_suresi_sn     INTEGER,
        personel_sayisi     INTEGER,
        aktif_goz_sayisi    INTEGER NOT NULL DEFAULT 0,
        kalip_basi_cift     INTEGER,
        durum               TEXT NOT NULL DEFAULT 'TASLAK'
                            CHECK (durum IN ('TASLAK', 'AKTIF', 'KAPANDI', 'IPTAL')),
        baslangic_zamani    TEXT,
        bitis_zamani        TEXT,
        degisim_sebebi      TEXT,
        notlar              TEXT,
        created_by          INTEGER,
        created_at          TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_enj_ab_setup_rapor "
        "ON enj_ab_setup(rapor_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_enj_ab_setup_rapor_slot "
        "ON enj_ab_setup(rapor_id, slot)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_enj_ab_setup_durum "
        "ON enj_ab_setup(rapor_id, slot, durum)"
    )
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_enj_ab_setup_aktif_slot
        ON enj_ab_setup(rapor_id, slot)
        WHERE durum = 'AKTIF'
    """)
    con.commit()
    print("[OK] Tablo ve indeksler olusturuldu")
    return True


def _slot_kaynak(cur, rapor_id, slot):
    """Ilk aktif istasyon; yoksa ilk kalip_id dolu satir (ab-ozet ile uyumlu)."""
    cur.execute(
        """
        SELECT i.kalip_id, i.renk, i.pisme_suresi_sn, i.kalip_basi_cift,
               i.son_durum_zamani
        FROM enj_istasyon_durumu i
        WHERE i.rapor_id=? AND i.slot=? AND i.aktif=1
        ORDER BY i.istasyon_no
        LIMIT 1
        """,
        (rapor_id, slot),
    )
    row = cur.fetchone()
    if not row:
        cur.execute(
            """
            SELECT i.kalip_id, i.renk, i.pisme_suresi_sn, i.kalip_basi_cift,
                   i.son_durum_zamani
            FROM enj_istasyon_durumu i
            WHERE i.rapor_id=? AND i.slot=? AND i.kalip_id IS NOT NULL
            ORDER BY i.istasyon_no
            LIMIT 1
            """,
            (rapor_id, slot),
        )
        row = cur.fetchone()
    if not row or not row[0]:
        return None

    cur.execute(
        "SELECT COUNT(*) FROM enj_istasyon_durumu "
        "WHERE rapor_id=? AND slot=? AND aktif=1",
        (rapor_id, slot),
    )
    aktif_goz = int(cur.fetchone()[0] or 0)

    kalip_id = row[0]
    kalip_kod = model_kod = None
    kbc_master = None
    cur.execute(
        "SELECT kalip_kod, model_kod, kalip_basi_cift FROM enj_kalip WHERE id=?",
        (kalip_id,),
    )
    kr = cur.fetchone()
    if kr:
        kalip_kod, model_kod, kbc_master = kr[0], kr[1], kr[2]

    kbc = row[3] if row[3] is not None else kbc_master

    return {
        "kalip_id": kalip_id,
        "kalip_kod_snapshot": kalip_kod,
        "model_kod_snapshot": model_kod,
        "renk": row[1],
        "pisme_suresi_sn": row[2],
        "kalip_basi_cift": kbc,
        "aktif_goz_sayisi": aktif_goz,
        "son_durum_zamani": row[4],
    }


def backfill(con, bugun_iso):
    cur = con.cursor()
    if cur.execute("SELECT COUNT(*) FROM enj_ab_setup").fetchone()[0] > 0:
        print("[SKIP] backfill — tablo dolu")
        return 0

    print("[2/3] backfill enj_istasyon_durumu -> enj_ab_setup ...")
    cur.execute(
        """
        SELECT id, makine_id, tarih, personel_sayisi, kullanici_id,
               son_guncelleme, kapanis_tarih
        FROM enj_gunluk_rapor
        ORDER BY id
        """
    )
    raporlar = cur.fetchall()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n = 0

    for rid, makine_id, tarih, personel, kullanici_id, son_gunc, kapanis in raporlar:
        eski = (tarih or "") < bugun_iso
        for slot in ("A", "B"):
            src = _slot_kaynak(cur, rid, slot)
            if not src:
                continue

            aktif_goz = src["aktif_goz_sayisi"]
            if eski:
                durum = "KAPANDI"
                baslangic = src["son_durum_zamani"] or son_gunc or now
                bitis = kapanis or son_gunc or now
                notlar = "BACKFILL_ESKI_RAPOR"
            elif aktif_goz > 0:
                durum = "AKTIF"
                baslangic = src["son_durum_zamani"] or son_gunc or now
                bitis = None
                notlar = "BACKFILL_AKTIF"
            else:
                durum = "TASLAK"
                baslangic = None
                bitis = None
                notlar = "BACKFILL_TASLAK"

            cur.execute(
                """
                INSERT INTO enj_ab_setup (
                    rapor_id, makine_id, slot,
                    kalip_id, kalip_kod_snapshot, model_kod_snapshot,
                    renk, pisme_suresi_sn, personel_sayisi,
                    aktif_goz_sayisi, kalip_basi_cift,
                    durum, baslangic_zamani, bitis_zamani,
                    notlar, created_by, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    rid, makine_id, slot,
                    src["kalip_id"], src["kalip_kod_snapshot"],
                    src["model_kod_snapshot"],
                    src["renk"], src["pisme_suresi_sn"], personel,
                    aktif_goz, src["kalip_basi_cift"],
                    durum, baslangic, bitis,
                    notlar, kullanici_id, now, now,
                ),
            )
            n += 1

    con.commit()
    print("[OK] backfill: %d setup kaydi" % n)
    return n


def dogrula(con):
    cur = con.cursor()
    print("\n[DOGRULAMA]")
    cols = cur.execute("PRAGMA table_info(enj_ab_setup)").fetchall()
    print("  Kolon sayisi: %d" % len(cols))
    total = cur.execute("SELECT COUNT(*) FROM enj_ab_setup").fetchone()[0]
    print("  Toplam kayit: %d" % total)
    for d in SETUP_DURUM:
        c = cur.execute(
            "SELECT COUNT(*) FROM enj_ab_setup WHERE durum=?", (d,)
        ).fetchone()[0]
        print("    %s: %d" % (d, c))
    dup = cur.execute("""
        SELECT rapor_id, slot, COUNT(*) c FROM enj_ab_setup
        WHERE durum='AKTIF' GROUP BY rapor_id, slot HAVING c > 1
    """).fetchall()
    if dup:
        print("  [HATA] Coklu AKTIF:", dup)
    else:
        print("  [OK] Slot basina tek AKTIF")


def main():
    if not os.path.exists(DB_PATH):
        print("[HATA] DB yok: " + DB_PATH)
        sys.exit(1)

    no_backfill = "--no-backfill" in sys.argv
    bugun = datetime.now().strftime("%Y-%m-%d")

    print("=" * 60)
    print("018_enj_ab_setup.py — ENJ_SETUP_V1 FAZ 1")
    print("=" * 60)
    yedek_al()
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        create_schema(con)
        if not no_backfill:
            backfill(con, bugun)
        dogrula(con)
        print("\n[TAMAM]")
    except Exception as e:
        con.rollback()
        print("[HATA] " + str(e))
        sys.exit(1)
    finally:
        con.close()


if __name__ == "__main__":
    main()
