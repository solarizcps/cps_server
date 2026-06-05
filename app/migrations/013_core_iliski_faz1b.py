"""
Migration: 013_core_iliski_faz1b
Tarih: 2026-06-02
Faz: YETKI_V2_CORE_ILISKI FAZ1B

Yapılanlar:
1. usta_personel_iliskisi tablosu oluşturulur (idempotent)
2. Halil ve Ferhat'ın profil_tipi = SAHA_USTASI güncellenir
3. Murat ve Deniz yoksa SAHA_USTASI olarak oluşturulur

Yapılmayanlar (Faz1C):
- personel_kullanici otomatik profil oluşturma
- otomatik usta-personel bağlama
- eski ekip ilişkilerini değiştirme
"""

import sqlite3
import os
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def run():
    print("=" * 60)
    print("Migration 013 - CORE_ILISKI FAZ1B")
    print("=" * 60)

    conn = get_conn()
    cur = conn.cursor()

    # ------------------------------------------------------------------
    # ADIM 1: usta_personel_iliskisi tablosunu oluştur (idempotent)
    # ------------------------------------------------------------------
    print("\n[1/3] usta_personel_iliskisi tablosu kontrol ediliyor...")

    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='usta_personel_iliskisi'"
    )
    tablo_var = cur.fetchone()

    if tablo_var:
        print("  -> Tablo zaten mevcut, atlanıyor.")
    else:
        cur.executescript("""
            CREATE TABLE usta_personel_iliskisi (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,

                -- İlişki tarafları
                usta_profil_id      INTEGER NOT NULL
                                        REFERENCES kullanici_profil(id) ON DELETE RESTRICT,
                personel_profil_id  INTEGER NOT NULL
                                        REFERENCES kullanici_profil(id) ON DELETE RESTRICT,

                -- Organizasyonel bağlam (tarihçe için)
                proses_id           INTEGER REFERENCES kullanici_proses(id) ON DELETE SET NULL,
                departman_id        INTEGER REFERENCES departman_master(id) ON DELETE SET NULL,

                -- Tarihçe alanları
                baslangic_tarihi    TEXT NOT NULL DEFAULT (date('now')),
                bitis_tarihi        TEXT,

                -- Durum ve kaynak
                aktif               INTEGER NOT NULL DEFAULT 1,
                kaynak              TEXT NOT NULL DEFAULT 'manuel',

                -- Audit alanları
                olusturan_id        INTEGER,
                guncelleme_notu     TEXT,
                created_at          TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at          TEXT NOT NULL DEFAULT (datetime('now')),

                -- Aynı usta-personel-proses kombinasyonu tekrarlanmasın (aktif kayıtlar için)
                UNIQUE (usta_profil_id, personel_profil_id, proses_id, bitis_tarihi)
            );

            CREATE INDEX IF NOT EXISTS idx_upi_usta
                ON usta_personel_iliskisi (usta_profil_id, aktif);
            CREATE INDEX IF NOT EXISTS idx_upi_personel
                ON usta_personel_iliskisi (personel_profil_id, aktif);
            CREATE INDEX IF NOT EXISTS idx_upi_proses
                ON usta_personel_iliskisi (proses_id);
        """)
        print("  -> Tablo oluşturuldu: usta_personel_iliskisi")
        print("     Kolonlar: usta_profil_id, personel_profil_id, proses_id,")
        print("               departman_id, baslangic_tarihi, bitis_tarihi,")
        print("               aktif, kaynak, olusturan_id, guncelleme_notu,")
        print("               created_at, updated_at")

    # ------------------------------------------------------------------
    # ADIM 2: Halil ve Ferhat → profil_tipi = SAHA_USTASI
    # ------------------------------------------------------------------
    print("\n[2/3] Halil ve Ferhat profil_tipi güncelleniyor...")

    for ad in ['Halil', 'Ferhat Usta']:
        cur.execute(
            "SELECT id, gercek_ad, profil_tipi FROM kullanici_profil WHERE gercek_ad = ?",
            (ad,)
        )
        kayit = cur.fetchone()

        if kayit is None:
            # Kısmi isim araması
            cur.execute(
                "SELECT id, gercek_ad, profil_tipi FROM kullanici_profil WHERE gercek_ad LIKE ?",
                (f'%{ad.split()[0]}%',)
            )
            kayit = cur.fetchone()

        if kayit is None:
            print(f"  -> UYARI: '{ad}' bulunamadı, atlanıyor.")
            continue

        pid, gercek_ad, mevcut_tip = kayit['id'], kayit['gercek_ad'], kayit['profil_tipi']

        if mevcut_tip == 'SAHA_USTASI':
            print(f"  -> {gercek_ad} (id:{pid}) zaten SAHA_USTASI, atlanıyor.")
        else:
            cur.execute(
                "UPDATE kullanici_profil SET profil_tipi='SAHA_USTASI', updated_at=datetime('now') WHERE id=?",
                (pid,)
            )
            print(f"  -> {gercek_ad} (id:{pid}): '{mevcut_tip}' → 'SAHA_USTASI' GÜNCELLENDI")

    # ------------------------------------------------------------------
    # ADIM 3: Murat ve Deniz yoksa SAHA_USTASI olarak oluştur
    # ------------------------------------------------------------------
    print("\n[3/3] Murat ve Deniz kontrol ediliyor...")

    yeni_ustalar = [
        {'gercek_ad': 'Murat', 'kullanici_adi': 'murat', 'departman': 'Üretim'},
        {'gercek_ad': 'Deniz', 'kullanici_adi': 'deniz', 'departman': 'Üretim'},
    ]

    for usta in yeni_ustalar:
        cur.execute(
            "SELECT id FROM kullanici_profil WHERE gercek_ad = ? OR kullanici_adi = ?",
            (usta['gercek_ad'], usta['kullanici_adi'])
        )
        mevcut = cur.fetchone()

        if mevcut:
            row = mevcut
            cur.execute(
                "SELECT gercek_ad, profil_tipi FROM kullanici_profil WHERE id=?", (row['id'],)
            )
            detay = cur.fetchone()
            if detay['profil_tipi'] == 'SAHA_USTASI':
                print(f"  -> {usta['gercek_ad']} (id:{row['id']}) zaten mevcut ve SAHA_USTASI, atlanıyor.")
            else:
                cur.execute(
                    "UPDATE kullanici_profil SET profil_tipi='SAHA_USTASI', updated_at=datetime('now') WHERE id=?",
                    (row['id'],)
                )
                print(f"  -> {usta['gercek_ad']} (id:{row['id']}) mevcut, profil_tipi SAHA_USTASI yapıldı.")
        else:
            cur.execute(
                """INSERT INTO kullanici_profil
                   (gercek_ad, kullanici_adi, departman, profil_tipi, aktif, kaynak)
                   VALUES (?, ?, ?, 'SAHA_USTASI', 1, 'faz1b_migration')""",
                (usta['gercek_ad'], usta['kullanici_adi'], usta['departman'])
            )
            yeni_id = cur.lastrowid
            print(f"  -> {usta['gercek_ad']} OLUŞTURULDU (id:{yeni_id}, profil_tipi: SAHA_USTASI)")

    # ------------------------------------------------------------------
    # Commit
    # ------------------------------------------------------------------
    conn.commit()
    conn.close()

    print("\n" + "=" * 60)
    print("Migration 013 TAMAMLANDI.")
    print("=" * 60)


if __name__ == '__main__':
    run()
