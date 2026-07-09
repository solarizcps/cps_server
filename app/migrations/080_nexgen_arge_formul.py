# -*- coding: utf-8 -*-
"""
Migration 080 — NexGen FAZ-3F-9: AR-GE Formül Tabloları
=========================================================

Yeni tablolar:
  [1] nexgen_arge_formul       — AR-GE formül geliştirme ana kaydı (MODÜL-03)
  [2] nexgen_arge_formul_kalem — Her formülün bileşen kalemleri

Tasarım kararları:
  - nexgen_formul (üretim formülü) ASLA değişmez/karışmaz.
  - nexgen_arge_formul = taslak/AR-GE çalışması.
  - Onaylandığında ileride nexgen_formul'a aktarılabilir (ayrı FAZ).
  - NX-ARF-NNNN kod formatı burada üretilir.
  - kaynak_formul_id = "Taslak Al" yönteminde kaynak üretim formülü.
  - arge_kodu (NX-ARF-NNNN) alanı merkezi geçişe hazır olacak şekilde
    ayrı tutulmaktadır.

İdempotent: Tekrar çalıştırılabilir.
KURAL: nexgen_formul, nexgen_stok_hareket dokunulmaz.
"""

import sqlite3
import os
import shutil
from datetime import datetime


DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    if not os.path.exists(DB_PATH):
        print(f"[080] HATA: DB bulunamadı: {DB_PATH}")
        return

    # ── Yedek al ──────────────────────────────────────────────────
    ts  = datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = DB_PATH.replace('.db', f'_backup_pre080_{ts}.db')
    shutil.copy2(DB_PATH, bak)
    print(f"[080] Yedek: {os.path.basename(bak)}")

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("=" * 65)
    print("Migration 080 — NexGen AR-GE Formül Tabloları")
    print("=" * 65)

    # ── Güvenlik kontrolü ─────────────────────────────────────────
    formul_say = cur.execute("SELECT COUNT(*) FROM nexgen_formul").fetchone()[0]
    print(f"[KONTROL] nexgen_formul={formul_say} kayıt — migration bunları değiştirmez")

    # ── 1) nexgen_arge_formul ──────────────────────────────────────
    print("\n[1] nexgen_arge_formul tablosu:")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_arge_formul (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,

            -- Kod (NX-ARF-NNNN formatı)
            arge_kodu            TEXT    UNIQUE,

            -- Temel bilgi
            formul_adi           TEXT    NOT NULL,
            aciklama             TEXT,

            -- İş akışı: yöntem
            yontem               TEXT    NOT NULL DEFAULT 'SIFIRDAN',
            -- SIFIRDAN | TASLAK
            -- TASLAK: mevcut nexgen_formul'dan kopyalandı

            -- Kaynak formül (yöntem=TASLAK ise dolu)
            kaynak_formul_id     INTEGER REFERENCES nexgen_formul(id),

            -- Cari / müşteri bağlantısı
            cari_id              INTEGER REFERENCES nexgen_cari(id),

            -- Renk seçimi
            renk_secim           TEXT    NOT NULL DEFAULT 'YOK',
            -- YOK | MEVCUT | YENI

            -- AR-GE notu (zorunlu, UI seviyesinde zorunlu)
            arge_notu            TEXT,

            -- Durum
            durum                TEXT    NOT NULL DEFAULT 'TASLAK',
            -- TASLAK | ONAY_BEKLIYOR | ONAYLANDI | REDDEDILDI | ARSIV

            -- Bağlantılar (ileride kullanım)
            olusan_formul_id     INTEGER REFERENCES nexgen_formul(id),

            -- Sistem alanları
            olusturan_id         INTEGER,
            olusturma_tarihi     TEXT    NOT NULL DEFAULT (datetime('now')),
            guncelleme_tarihi    TEXT,
            aktif                INTEGER NOT NULL DEFAULT 1
        )
    """)
    con.commit()
    print("  OK nexgen_arge_formul")

    # ── 2) nexgen_arge_formul_kalem ────────────────────────────────
    print("\n[2] nexgen_arge_formul_kalem tablosu:")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_arge_formul_kalem (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,

            arge_formul_id      INTEGER NOT NULL
                                    REFERENCES nexgen_arge_formul(id)
                                    ON DELETE CASCADE,
            stok_kart_id        INTEGER NOT NULL
                                    REFERENCES nexgen_stok_kart(id),

            -- Sıra (görüntüleme)
            sira                INTEGER NOT NULL DEFAULT 1,

            -- Miktar (kg)
            miktar_kg           REAL    NOT NULL DEFAULT 0,

            -- Renk bileşeni mi?
            renk_bileseni_mi    INTEGER NOT NULL DEFAULT 0,
            -- 1 = renk bileşeni (gram ile girildi, kg'a çevrildi)

            -- Gram karşılığı (renk bileşeni için görüntüleme)
            miktar_gr           REAL,

            aciklama            TEXT,
            aktif               INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi    TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    con.commit()
    print("  OK nexgen_arge_formul_kalem")

    # ── 3) Index'ler ──────────────────────────────────────────────
    print("\n[3] Index'ler:")
    indexler = [
        ("idx_naf_arge_kodu",  "nexgen_arge_formul(arge_kodu)"),
        ("idx_naf_cari",       "nexgen_arge_formul(cari_id)"),
        ("idx_naf_kaynak",     "nexgen_arge_formul(kaynak_formul_id)"),
        ("idx_naf_durum",      "nexgen_arge_formul(durum)"),
        ("idx_nafk_formul",    "nexgen_arge_formul_kalem(arge_formul_id)"),
        ("idx_nafk_stok",      "nexgen_arge_formul_kalem(stok_kart_id)"),
    ]
    for idx_ad, idx_hedef in indexler:
        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_ad} ON {idx_hedef}")
        print(f"  {idx_ad}")
    con.commit()

    # ── 4) schema_migrations ──────────────────────────────────────
    try:
        cur.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, aciklama) "
            "VALUES (80, 'nexgen_arge_formul + kalem tablosu FAZ-3F-9')"
        )
        con.commit()
        print("\n[4] schema_migrations version=80 OK")
    except Exception as e:
        print(f"\n[4] schema_migrations WARN: {e}")

    # ── Doğrulama ─────────────────────────────────────────────────
    formul_say2 = cur.execute("SELECT COUNT(*) FROM nexgen_formul").fetchone()[0]
    naf_cols = [r[1] for r in cur.execute(
        "PRAGMA table_info(nexgen_arge_formul)"
    ).fetchall()]
    nafk_cols = [r[1] for r in cur.execute(
        "PRAGMA table_info(nexgen_arge_formul_kalem)"
    ).fetchall()]

    print("\n" + "=" * 65)
    print("ÖZET:")
    print(f"  nexgen_arge_formul      : {len(naf_cols)} kolon, 0 satır")
    print(f"  nexgen_arge_formul_kalem: {len(nafk_cols)} kolon, 0 satır")
    print(f"  nexgen_formul ÖNCE={formul_say} SONRA={formul_say2}",
          "OK" if formul_say == formul_say2 else "!!! DEGISTI !!!")
    print(f"  Yedek: {os.path.basename(bak)}")
    print("=" * 65)

    con.close()
    print("Migration 080 tamamlandı.\n")


if __name__ == '__main__':
    run()
