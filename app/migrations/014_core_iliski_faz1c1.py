"""
Migration: 014_core_iliski_faz1c1
Tarih: 2026-06-02
Faz: YETKI_V2_CORE_ILISKI FAZ1C-1

Yapılanlar:
  10 güvenli personel_kullanici kaydı için kullanici_profil oluşturulur.

Güvenli kriter (hepsi AND):
  - aktif = 1
  - IdentityDurum = 'temiz'
  - GuvenSkoru >= 100
  - SistemKullaniciId IS NULL  (mevcut profil bağlantısı yok)

Oluşturulan profil_tipi: SAHA_PERSONEL
kaynak: 'personel_kullanici', kaynak_id = personel_kullanici.id

İdempotent:
  Aynı (kaynak, kaynak_id) çifti zaten varsa ekleme yapılmaz.

YAPILMAYAN (FAZ1C-2 ve sonrası):
  - usta_personel_iliskisi doldurma
  - usta-personel bağlama
  - Halil/Ferhat/Murat/Deniz değiştirme
  - GuvenSkoru < 100 veya IdentityDurum != 'temiz' kayıtları
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

GUVENLI_KRITERI = """
    SELECT id, ad, kullanici_adi, birim
    FROM personel_kullanici
    WHERE COALESCE(aktif, 1) = 1
      AND IdentityDurum = 'temiz'
      AND COALESCE(GuvenSkoru, 0) >= 100
      AND SistemKullaniciId IS NULL
    ORDER BY id
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def run():
    print("=" * 60)
    print("Migration 014 - CORE_ILISKI FAZ1C-1")
    print("=" * 60)

    conn = get_conn()
    cur = conn.cursor()

    # Güvenli aday listesi
    cur.execute(GUVENLI_KRITERI)
    adaylar = [dict(r) for r in cur.fetchall()]

    print(f"\nGüvenli aday sayısı (IdentityDurum=temiz, GuvenSkoru>=100, SistemKullaniciId=NULL): {len(adaylar)}")
    print()

    eklendi = 0
    atlandi = 0

    for p in adaylar:
        # İdempotent kontrol: kaynak='personel_kullanici' AND kaynak_id=p['id']
        cur.execute(
            "SELECT id FROM kullanici_profil WHERE kaynak='personel_kullanici' AND kaynak_id=?",
            (p['id'],)
        )
        mevcut = cur.fetchone()

        if mevcut:
            print(f"  ATLA  PK#{p['id']:02d} {p['ad']} -> KP#{mevcut['id']} zaten mevcut")
            atlandi += 1
            continue

        # Profil oluştur
        gercek_ad = (p['ad'] or '').strip().title()
        kullanici_adi = (p['kullanici_adi'] or '').strip().lower()
        departman = (p['birim'] or '').strip() or None

        cur.execute(
            """INSERT INTO kullanici_profil
               (gercek_ad, kullanici_adi, departman, profil_tipi, aktif, kaynak, kaynak_id)
               VALUES (?, ?, ?, 'SAHA_PERSONEL', 1, 'personel_kullanici', ?)""",
            (gercek_ad, kullanici_adi, departman, p['id'])
        )
        yeni_id = cur.lastrowid
        print(f"  EKLE  PK#{p['id']:02d} {gercek_ad} -> KP#{yeni_id} (SAHA_PERSONEL)")
        eklendi += 1

    conn.commit()
    conn.close()

    print()
    print(f"  Eklendi : {eklendi}")
    print(f"  Atlandı : {atlandi}")
    print()
    print("=" * 60)
    print("Migration 014 TAMAMLANDI.")
    print("=" * 60)


if __name__ == '__main__':
    run()
