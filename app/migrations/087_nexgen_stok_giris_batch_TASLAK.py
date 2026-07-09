# -*- coding: utf-8 -*-
"""
Migration 087 — TASLAK (UYGULANMAZ)
====================================
NexGen FAZ-STOK-GIRIS — Excel toplu stok giriş batch tabloları.

DURUM: Taslak only — Adem onayı olmadan çalıştırılmaz.
Referans: FAZ-STOK-GIRIS-2A RECON, nexgen_fiyat_batch (056) modeli.

Bu migration:
  - nexgen_stok_giris_batch
  - nexgen_stok_giris_batch_detay
  - opsiyonel: nexgen_stok_hareket.hareket_kaynagi (087b ayrı dosyada olabilir)

KURAL: nexgen_stok_hareket mevcut kayıtları değiştirmez.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    raise RuntimeError(
        'TASLAK migration — uygulanmaz. '
        'Onay sonrası RuntimeError kaldırılıp çalıştırılır.'
    )

    if not os.path.exists(DB_PATH):
        print(f'HATA: DB bulunamadı: {DB_PATH}')
        return

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    hrt_say = cur.execute('SELECT COUNT(*) FROM nexgen_stok_hareket').fetchone()[0]
    print(f'[KONTROL] nexgen_stok_hareket başlangıç: {hrt_say}')

    # ── 1) nexgen_stok_giris_batch ───────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_stok_giris_batch (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_no        TEXT    NOT NULL UNIQUE,
            belge_no        TEXT    NOT NULL,
            kaynak          TEXT    NOT NULL DEFAULT 'EXCEL',
            dosya_adi       TEXT,
            toplam_satir    INTEGER NOT NULL DEFAULT 0,
            gecerli_satir   INTEGER NOT NULL DEFAULT 0,
            hatali_satir    INTEGER NOT NULL DEFAULT 0,
            toplam_kg       REAL    NOT NULL DEFAULT 0,
            durum           TEXT    NOT NULL DEFAULT 'ONAY_BEKLIYOR',
            notlar          TEXT,
            yukleyen_id     INTEGER NOT NULL,
            yukleme_tarihi  TEXT    NOT NULL DEFAULT (datetime('now')),
            onaylayan_id    INTEGER,
            onay_tarihi     TEXT,
            CHECK (durum IN ('ONAY_BEKLIYOR','ONAYLANDI','IPTAL')),
            CHECK (kaynak IN ('EXCEL','MANUEL'))
        )
    """)

    # ── 2) nexgen_stok_giris_batch_detay ─────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_stok_giris_batch_detay (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id            INTEGER NOT NULL
                                    REFERENCES nexgen_stok_giris_batch(id) ON DELETE CASCADE,
            satir_no            INTEGER NOT NULL,
            stok_kodu           TEXT    NOT NULL,
            stok_kart_id        INTEGER REFERENCES nexgen_stok_kart(id),
            miktar_kg           REAL,
            lot_no              TEXT,
            tedarikci_id        INTEGER REFERENCES nexgen_tedarikci(id),
            giris_tarihi        TEXT,
            aciklama            TEXT,
            gecerli_mi          INTEGER NOT NULL DEFAULT 1,
            hata_mesaji         TEXT,
            isleme_alindi_mi    INTEGER NOT NULL DEFAULT 0,
            mal_kabul_id        INTEGER REFERENCES nexgen_mal_kabul(id),
            stok_hareket_id     INTEGER REFERENCES nexgen_stok_hareket(id)
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nsgbd_batch
        ON nexgen_stok_giris_batch_detay(batch_id)
    """)

    con.commit()

    hrt_son = cur.execute('SELECT COUNT(*) FROM nexgen_stok_hareket').fetchone()[0]
    assert hrt_son == hrt_say, 'nexgen_stok_hareket değişmemeli'

    sm_kol = [r[1] for r in cur.execute('PRAGMA table_info(schema_migrations)').fetchall()]
    if 'aciklama' in sm_kol:
        cur.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, aciklama) "
            "VALUES (87, 'nexgen stok giris batch TASLAK FAZ-STOK-GIRIS')"
        )
    else:
        cur.execute('INSERT OR IGNORE INTO schema_migrations (version) VALUES (87)')
    con.commit()
    con.close()
    print('Migration 087 taslak tamamlandı.')


if __name__ == '__main__':
    run()
