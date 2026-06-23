"""
Migration 064: nexgen_arge_test + nexgen_arge_test_kalem
FAZ-4C-3 — ARGE Renk Test Merkezi

Tablolar:
1) nexgen_arge_test       — Test seansı ana kaydı
2) nexgen_arge_test_kalem — Test başına ölçeklenmiş kalem miktarları

KURAL: nexgen_stok_hareket'e DOKUNULMAZ.
       Bu tablolar sadece AR-GE deneme kayıtlarıdır.
"""

import sqlite3, os


def run(db_path):
    con = sqlite3.connect(db_path)
    try:
        # ── 1) nexgen_arge_test
        con.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_arge_test (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                kaynak_uretim_varyant_id INTEGER NOT NULL,

                test_no                  TEXT    NOT NULL,
                test_tipi                TEXT    NOT NULL DEFAULT 'RENK_TEST',
                -- RENK_TEST | FORMUL_TEST

                makina                   TEXT    NOT NULL DEFAULT '7.5 LT',
                test_batch_kg            REAL    NOT NULL,
                kaynak_batch_kg          REAL    NOT NULL,
                -- ölçekleme çarpanı: test_batch_kg / kaynak_batch_kg

                yeni_renk_adi            TEXT,
                notlar                   TEXT,

                durum                    TEXT    NOT NULL DEFAULT 'TASLAK',
                -- TASLAK | TEST_EDILDI | BASARILI | BASARISIZ
                -- ONAYA_GONDERILDI | ONAYLANDI | REDDEDILDI

                sonuc_notu               TEXT,
                renk_tuttu               INTEGER,   -- 1/0/NULL
                shore_degeri             REAL,
                kopurme_notu             TEXT,
                cekme_problemi           INTEGER,   -- 1/0/NULL
                genel_aciklama           TEXT,

                olusturan_id             INTEGER,
                olusturma_tarihi         TEXT    NOT NULL DEFAULT (datetime('now')),

                onaylayan_id             INTEGER,
                onay_tarihi              TEXT,
                aktif                    INTEGER NOT NULL DEFAULT 1
            )
        """)
        print("[064] nexgen_arge_test tablosu hazir")

        # ── 2) nexgen_arge_test_kalem
        con.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_arge_test_kalem (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id             INTEGER NOT NULL,
                stok_kart_id        INTEGER NOT NULL,
                sira                INTEGER NOT NULL DEFAULT 1,
                orjinal_miktar_kg   REAL    NOT NULL,
                test_miktar_kg      REAL    NOT NULL,
                -- REAL: 0.001 hassasiyet korunur
                aciklama            TEXT,
                olusturma_tarihi    TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        print("[064] nexgen_arge_test_kalem tablosu hazir")

        # ── 3) test_no için sequence yardımcısı (basit)
        # test_no: AT-YYYY-NNNN formatında routes.py'de üretilecek

        con.commit()
        print("[064] Migration basarili")
    except Exception as e:
        con.rollback()
        print(f"[064] HATA: {e}")
        raise
    finally:
        con.close()


if __name__ == '__main__':
    db = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
    run(os.path.abspath(db))
