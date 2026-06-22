# -*- coding: utf-8 -*-
"""
NexGen Test Verisi Temizleme Script'i
======================================

Kullanım:
  python app/scripts/nexgen_test_veri_temizle.py           <- sadece rapor
  python app/scripts/nexgen_test_veri_temizle.py --confirm <- rapor + sil

KURAL:
  --confirm olmadan HİÇBİR VERİ SİLİNMEZ.
  Önce rapor gösterilir, kullanıcı kontrol eder.
  Sonra --confirm ile çalıştırılır.

Temizlenecekler (FK sırasına göre):
  1. nexgen_stok_hareket   (hareket kayıtları — en bağımlı)
  2. nexgen_satin_siparis  (satın alma siparişleri)
  3. nexgen_tedarikci_stok (eşleşmeler)
  4. nexgen_stok_kart      (stok kartları)
  5. nexgen_tedarikci      (tedarikçiler)

Çalışma sırası (FAZ-2.5 geçişi için):
  python app/scripts/nexgen_test_veri_temizle.py
  python app/scripts/nexgen_test_veri_temizle.py --confirm
  python app/scripts/nexgen_gercek_veri_import.py
  python app/scripts/nexgen_gercek_veri_import.py --confirm
"""

import sqlite3
import os
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

TABLOLAR = [
    # (tablo_adi, aciklama, FK sırasına göre — önce bağımlı olanlar)
    ('nexgen_stok_hareket',    'Stok hareketleri'),
    ('nexgen_satin_siparis',   'Satın alma siparişleri'),
    ('nexgen_tedarikci_stok',  'Tedarikçi-stok eşleşmeleri'),
    ('nexgen_stok_kart',       'Stok kartları'),
    ('nexgen_tedarikci',       'Tedarikçiler'),
]


def rapor_ver(cur):
    """Mevcut kayıt sayılarını raporla."""
    print("\n" + "=" * 60)
    print("NexGen Test Verisi Raporu")
    print("=" * 60)
    toplam = 0
    sayilar = {}
    for tablo, acik in TABLOLAR:
        try:
            n = cur.execute(f"SELECT COUNT(*) FROM {tablo}").fetchone()[0]
        except Exception:
            n = 0
        sayilar[tablo] = n
        toplam += n
        durum = "silinecek" if n > 0 else "boş"
        print(f"  {tablo:30s}  {n:5d} kayıt  [{durum}]")
    print(f"\n  TOPLAM                          {toplam:5d} kayıt silinecek")
    return sayilar


def detay_ver(cur):
    """Silinecek verilerden örnek göster."""
    print("\n[Detay]")

    rows = cur.execute(
        "SELECT sk.kod, sk.ad, COUNT(sh.id) AS hrt "
        "FROM nexgen_stok_kart sk "
        "LEFT JOIN nexgen_stok_hareket sh ON sh.stok_kart_id = sk.id "
        "GROUP BY sk.id ORDER BY sk.id"
    ).fetchall()
    if rows:
        print("  Stok Kartları + Hareket Sayıları:")
        for r in rows:
            print(f"    {r[0]:20s}  {r[1]:30s}  {r[2]} hareket")

    rows2 = cur.execute("SELECT kod, ad FROM nexgen_tedarikci").fetchall()
    if rows2:
        print("  Tedarikçiler:")
        for r in rows2:
            print(f"    {r[0]:15s}  {r[1]}")

    rows3 = cur.execute("SELECT COUNT(*) FROM nexgen_satin_siparis").fetchone()[0]
    if rows3 > 0:
        siparisler = cur.execute("SELECT siparis_no, onay_durumu FROM nexgen_satin_siparis").fetchall()
        print("  Satın Alma Siparişleri:")
        for r in siparisler:
            print(f"    {r[0]}  durum={r[1]}")


def temizle(con, cur, sayilar):
    """FK sırasına göre verileri sil."""
    print("\n" + "=" * 60)
    print("SİLME İŞLEMİ BAŞLIYOR")
    print("=" * 60)
    toplam_silinen = 0
    for tablo, acik in TABLOLAR:
        n = sayilar.get(tablo, 0)
        if n == 0:
            print(f"  SKIP  {tablo:30s}  (boş)")
            continue
        cur.execute(f"DELETE FROM {tablo}")
        silinen = cur.rowcount
        toplam_silinen += silinen
        print(f"  SİLİNDİ  {tablo:30s}  {silinen} kayıt")
    con.commit()
    print(f"\n  TOPLAM {toplam_silinen} kayıt silindi.")
    print("  Sıradaki adım: python app/scripts/nexgen_gercek_veri_import.py --confirm")


def main():
    confirm = '--confirm' in sys.argv

    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadı: {DB_PATH}")
        sys.exit(1)

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("PRAGMA foreign_keys = OFF")  # FK OFF — sıralı silme yeterli

    sayilar = rapor_ver(cur)
    detay_ver(cur)

    if not confirm:
        print("\n" + "=" * 60)
        print("İŞLEM YAPILMADI.")
        print("Silmek için: python app/scripts/nexgen_test_veri_temizle.py --confirm")
        print("=" * 60)
    else:
        toplam = sum(sayilar.values())
        if toplam == 0:
            print("\n  Zaten temiz — silinecek kayıt yok.")
        else:
            print(f"\n  UYARI: {toplam} kayıt silinecek. Devam ediliyor...")
            temizle(con, cur, sayilar)

    con.close()


if __name__ == '__main__':
    main()
