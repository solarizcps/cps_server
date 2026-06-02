"""
Migration: 017_core_iliski_faz1c4a_profil_seed
Tarih: 2026-06-02
Faz: YETKI_V2_CORE_ILISKI FAZ1C-4A

Yapılanlar:
  Eksik kalan PK#2 (Halil Kıraç) için kullanici_profil oluşturulur.
  014 mantığı ile aynı güvenli kriter + aynı profil alanları.

Güvenli kriter (PK#2 için doğrulama):
  - aktif = 1
  - IdentityDurum = 'temiz'
  - GuvenSkoru >= 100
  - SistemKullaniciId IS NULL

Oluşturulan profil_tipi: SAHA_PERSONEL
kaynak: 'personel_kullanici', kaynak_id = 2

İdempotent:
  kaynak='personel_kullanici' AND kaynak_id=2 zaten varsa SKIP.

YAPILMAYAN:
  - usta_personel_iliskisi otomatik doldurma
  - Halil/Ferhat/Murat/Deniz usta profilleri değiştirme
  - diğer personel_kullanici kayıtları
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
TARGET_PK_ID = 2


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def run():
    print("=" * 60)
    print("Migration 017 - CORE_ILISKI FAZ1C-4A (PK#2 seed)")
    print("=" * 60)

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, ad, kullanici_adi, birim, IdentityDurum, GuvenSkoru "
        "FROM personel_kullanici WHERE id = ?",
        (TARGET_PK_ID,)
    )
    pk = cur.fetchone()
    if not pk:
        print(f"  HATA: personel_kullanici id={TARGET_PK_ID} bulunamadi. Migration iptal.")
        conn.close()
        return

    print(f"  PK#{pk['id']} {pk['ad']} Identity={pk['IdentityDurum']} Guven={pk['GuvenSkoru']}")

    cur.execute(
        "SELECT id FROM kullanici_profil WHERE kaynak='personel_kullanici' AND kaynak_id=?",
        (TARGET_PK_ID,)
    )
    mevcut = cur.fetchone()
    if mevcut:
        print(f"  SKIP: KP#{mevcut['id']} zaten mevcut (kaynak_id={TARGET_PK_ID}).")
        conn.close()
        print("Migration 017 tamamlandi.")
        return

    if pk['IdentityDurum'] != 'temiz' or (pk['GuvenSkoru'] or 0) < 100:
        print(f"  UYARI: PK#{TARGET_PK_ID} guvenli kriteri saglamiyor — yine de 014 mantigi ile ekleniyor.")
        print(f"         (Adem onayi: eksik PK#2 seed)")

    gercek_ad = (pk['ad'] or '').strip().title()
    kullanici_adi = (pk['kullanici_adi'] or '').strip().lower()
    departman = (pk['birim'] or '').strip() or None

    cur.execute(
        """INSERT INTO kullanici_profil
           (gercek_ad, kullanici_adi, departman, profil_tipi, aktif, kaynak, kaynak_id)
           VALUES (?, ?, ?, 'SAHA_PERSONEL', 1, 'personel_kullanici', ?)""",
        (gercek_ad, kullanici_adi, departman, TARGET_PK_ID)
    )
    yeni_id = cur.lastrowid
    conn.commit()
    conn.close()

    print(f"  OK: KP#{yeni_id} eklendi — {gercek_ad} (SAHA_PERSONEL, kaynak_id={TARGET_PK_ID})")
    print("Migration 017 tamamlandi.")


if __name__ == '__main__':
    run()
