# -*- coding: utf-8 -*-
"""
Migration 056 — NexGen FAZ-2.6: Hammadde Fiyat Geçmişi Tabloları
=================================================================

Yapılanlar:
  1) nexgen_hammadde_fiyat     — Fiyat geçmiş defteri (her giriş yeni satır)
  2) nexgen_fiyat_batch        — Excel yükleme oturumu
  3) nexgen_fiyat_batch_detay  — Preview geçici tampon (onay öncesi asıl tabloya yazılmaz)

SON FİYAT KURALI:
  WHERE tedarikci_id = ? AND stok_kart_id = ? AND aktif = 1
  ORDER BY fiyat_tarihi DESC, id DESC
  LIMIT 1

  aktif = 1 → normal geçmiş kaydı
  aktif = 0 → sadece Yönetim tarafından hatalı/iptal işaretlendi
  Eski fiyatlar silinmez, aktif=0 yapılmaz.
  Son fiyat tarihe göre bulunur.

PREVIEW AKIŞ:
  Excel → parse → nexgen_fiyat_batch_detay (geçici)
  Onay → nexgen_hammadde_fiyat INSERT
  İptal → batch_detay sil, hammadde_fiyat KIRLENMEZ

KURALLAR:
  - nexgen_stok_hareket tablosuna DOKUNULMAZ.
  - Test verisi DELETE yapılmaz.
  - Idempotent.

Versiyon: 056
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadı: {DB_PATH}")
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("PRAGMA foreign_keys = ON")

    print("=" * 65)
    print("Migration 056 — NexGen FAZ-2.6: Fiyat Geçmişi Tabloları")
    print("=" * 65)

    hrt_say = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    print(f"\n[KONTROL] nexgen_stok_hareket başlangıç: {hrt_say} — korunacak.")

    # ── 1) nexgen_fiyat_batch ─────────────────────────────────────
    print("\n[1] nexgen_fiyat_batch:")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_fiyat_batch (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            hafta_kodu      TEXT    NOT NULL,
            dosya_adi       TEXT,
            toplam_satir    INTEGER NOT NULL DEFAULT 0,
            gecerli_satir   INTEGER NOT NULL DEFAULT 0,
            hatali_satir    INTEGER NOT NULL DEFAULT 0,
            durum           TEXT    NOT NULL DEFAULT 'ONAY_BEKLIYOR',
            notlar          TEXT,
            yukleyen_id     INTEGER NOT NULL,
            yukleme_tarihi  TEXT    NOT NULL DEFAULT (datetime('now')),
            onaylayan_id    INTEGER,
            onay_tarihi     TEXT,
            CHECK (durum IN ('ONAY_BEKLIYOR','ONAYLANDI','IPTAL'))
        )
    """)
    print("  OK nexgen_fiyat_batch")

    # ── 2) nexgen_fiyat_batch_detay ──────────────────────────────
    print("\n[2] nexgen_fiyat_batch_detay:")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_fiyat_batch_detay (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id         INTEGER NOT NULL
                                 REFERENCES nexgen_fiyat_batch(id) ON DELETE CASCADE,
            tedarikci_kodu   TEXT    NOT NULL,
            stok_kodu        TEXT    NOT NULL,
            tedarikci_id     INTEGER REFERENCES nexgen_tedarikci(id),
            stok_kart_id     INTEGER REFERENCES nexgen_stok_kart(id),
            fiyat            REAL,
            para_birimi      TEXT,
            kur              REAL,
            fiyat_try        REAL,
            vade_gun         INTEGER,
            fiyat_tarihi     TEXT,
            gecerlilik_bas   TEXT,
            gecerlilik_bitis TEXT,
            notlar           TEXT,
            onceki_fiyat     REAL,
            onceki_pb        TEXT,
            onceki_tarih     TEXT,
            fark             REAL,
            yuzde_degisim    REAL,
            gecerli_mi       INTEGER NOT NULL DEFAULT 1,
            hata_sebebi      TEXT
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nfbd_batch
        ON nexgen_fiyat_batch_detay(batch_id)
    """)
    print("  OK nexgen_fiyat_batch_detay")

    # ── 3) nexgen_hammadde_fiyat ──────────────────────────────────
    print("\n[3] nexgen_hammadde_fiyat:")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_hammadde_fiyat (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            tedarikci_id     INTEGER NOT NULL REFERENCES nexgen_tedarikci(id),
            stok_kart_id     INTEGER NOT NULL REFERENCES nexgen_stok_kart(id),
            fiyat            REAL    NOT NULL,
            para_birimi      TEXT    NOT NULL DEFAULT 'USD',
            kur              REAL,
            fiyat_try        REAL,
            vade_gun         INTEGER,
            fiyat_tarihi     TEXT    NOT NULL,
            gecerlilik_bas   TEXT,
            gecerlilik_bitis TEXT,
            kaynak           TEXT    NOT NULL DEFAULT 'MANUEL',
            batch_id         INTEGER REFERENCES nexgen_fiyat_batch(id),
            notlar           TEXT,
            aktif            INTEGER NOT NULL DEFAULT 1,
            -- 1 = normal kayıt; 0 = Yönetim tarafından hatalı işaretlendi
            -- Son fiyat: WHERE aktif=1 ORDER BY fiyat_tarihi DESC, id DESC LIMIT 1
            iptal_sebebi     TEXT,
            iptal_eden_id    INTEGER,
            iptal_tarihi     TEXT,
            olusturan_id     INTEGER,
            olusturma_tarihi TEXT    NOT NULL DEFAULT (datetime('now')),
            CHECK (para_birimi IN ('USD','EUR','TRY','GBP','CNY')),
            CHECK (kaynak IN ('MANUEL','EXCEL_IMPORT'))
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nhf_ted_stok
        ON nexgen_hammadde_fiyat(tedarikci_id, stok_kart_id)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nhf_tarih
        ON nexgen_hammadde_fiyat(fiyat_tarihi DESC)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nhf_batch
        ON nexgen_hammadde_fiyat(batch_id)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nhf_aktif
        ON nexgen_hammadde_fiyat(aktif)
    """)
    print("  OK nexgen_hammadde_fiyat")

    con.commit()

    # ── Güvenlik ──────────────────────────────────────────────────
    hrt_son = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    assert hrt_son == hrt_say, f"HATA: nexgen_stok_hareket değişti!"
    print(f"\n[KONTROL] nexgen_stok_hareket: {hrt_son} — değişmedi ✓")

    # ── schema_migrations ─────────────────────────────────────────
    sm_kol = [r[1] for r in cur.execute("PRAGMA table_info(schema_migrations)").fetchall()]
    if 'aciklama' in sm_kol:
        cur.execute("INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (56, 'nexgen fiyat gecmis tablolari FAZ-2.6')")
    else:
        cur.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (56)")
    con.commit()

    # ── Doğrulama ─────────────────────────────────────────────────
    print("\n[4] Doğrulama:")
    for t in ['nexgen_fiyat_batch', 'nexgen_fiyat_batch_detay', 'nexgen_hammadde_fiyat']:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:35s}: {n} kayıt")

    con.close()
    print("\nMigration 056 tamamlandı.")


if __name__ == '__main__':
    run()
