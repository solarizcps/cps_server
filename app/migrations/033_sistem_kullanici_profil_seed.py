# -*- coding: utf-8 -*-
"""
Migration 033: sistem_kullanici → kullanici_profil seed (idempotent)

Hedef: Mevcut sistem_kullanici kayıtlarından kullanici_profil'i eksik olanlar
için otomatik profil oluştur. Personel 360 merkezi kullanici_profil olduğundan
tüm kullanıcıların profili olmalı.

Köprü pattern: kaynak='sistem_kullanici', kaynak_id=sistem_kullanici.Id
Profil tipi: 'sistem' (yönetim/ofis kullanıcıları)

Kurallar:
- Mevcut profil varsa DOKUNMA (INSERT OR IGNORE + WHERE NOT EXISTS çift kontrol)
- Pasif (Aktif=0) sistem_kullanici için profil_aktif=0 oluştur
- Idempotent: tekrar çalışınca sorun çıkarmaz
"""

import sqlite3
import os
import sys
sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")

    try:
        # Tüm sistem_kullanici kayıtlarını çek
        sk_rows = con.execute("""
            SELECT Id, KullaniciAdi, AdSoyad, Aktif
            FROM sistem_kullanici
            ORDER BY Id
        """).fetchall()

        eklenen = 0
        atlanan = 0
        hatali  = 0

        for sk in sk_rows:
            sk_id   = sk['Id']
            kadi    = (sk['KullaniciAdi'] or '').strip().lower()
            ad_soyad = (sk['AdSoyad'] or kadi or '').strip()
            aktif   = 1 if sk['Aktif'] else 0

            if not kadi:
                hatali += 1
                continue

            # Mevcut profil kontrolü — kaynak bazlı VE kullanici_adi bazlı
            mevcut = con.execute("""
                SELECT id FROM kullanici_profil
                WHERE (kaynak = 'sistem_kullanici' AND kaynak_id = ?)
                   OR kullanici_adi = ?
                LIMIT 1
            """, (sk_id, kadi)).fetchone()

            if mevcut:
                atlanan += 1
                continue

            # Profil oluştur
            try:
                con.execute("""
                    INSERT INTO kullanici_profil
                      (gercek_ad, kullanici_adi, profil_tipi, aktif, kaynak, kaynak_id)
                    VALUES (?, ?, 'sistem', ?, 'sistem_kullanici', ?)
                """, (ad_soyad, kadi, aktif, sk_id))
                eklenen += 1
            except Exception as e:
                print(f"  HATA: sistem_kullanici.Id={sk_id} kadi={kadi}: {e}")
                hatali += 1

        con.commit()

        print(f"Migration 033 tamamlandı:")
        print(f"  Eklenen profil : {eklenen}")
        print(f"  Atlanan (mevcut): {atlanan}")
        print(f"  Hatalı         : {hatali}")
        print(f"  Toplam işlenen : {len(sk_rows)}")

    except Exception as e:
        con.rollback()
        print(f"Migration 033 HATA: {e}")
        raise
    finally:
        con.close()


if __name__ == '__main__':
    run()
