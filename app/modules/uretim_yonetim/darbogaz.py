# -*- coding: utf-8 -*-
"""
SOLARIZ CPS - FAZ 1
Darbogaz Hesap Motoru

Mantik:
1. Siparisin tum proseslerini al
2. Her proses icin yuzde hesapla (yapilan / hedef)
3. Kategoriye grupla (ATKI / GOVDE / MAMUL)
4. Her kategori icin MIN al
5. ANA DARBOGAZ = MIN(ATKI%, GOVDE%, MAMUL%)
6. ALT DARBOGAZ = ana kategorinin en yavas alt-prosesi
7. siparis_darbogaz tablosuna yaz
"""
import sqlite3
from datetime import datetime
from config import Config


def _conn():
    conn = sqlite3.connect(Config.MOCK_DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def proses_yuzde_hesapla(siparis_no):
    """
    Siparisin her prosesi icin yuzde hesaplar.
    Returns: [{'proses_kod', 'proses_adi', 'kategori', 'hedef', 'yapilan', 'yuzde', 'usta'}, ...]
    """
    c = _conn()
    try:
        cur = c.cursor()
        cur.execute("""
            SELECT 
                spd.proses_kod,
                pk.proses_adi,
                pk.kategori,
                spd.hedef,
                spd.yapilan_korgun,
                spd.yapilan_cps,
                CASE 
                    WHEN spd.hedef > 0 
                    THEN (CAST(spd.yapilan_korgun AS REAL) / spd.hedef) * 100
                    ELSE 0
                END AS yuzde,
                COALESCE(pua.usta_kullanici, pua.fallback_usta, 'halil') AS usta
            FROM siparis_proses_durum spd
            JOIN proses_kategori pk ON pk.proses_kod = spd.proses_kod
            LEFT JOIN proses_usta_atama pua ON pua.proses_kod = spd.proses_kod AND pua.aktif = 1
            WHERE spd.siparis_no = ?
            ORDER BY pk.kategori, pk.sira
        """, (siparis_no,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        c.close()


def kategori_yuzdeleri(prosesler):
    """
    Proses listesinden kategori yuzdelerini hesaplar.
    Her kategori icin MIN aliyoruz (en yavas proses).
    Returns: {'ATKI': {...}, 'GOVDE': {...}, 'MAMUL': {...}}
    """
    sonuc = {'ATKI': None, 'GOVDE': None, 'MAMUL': None}
    
    for kategori in ('ATKI', 'GOVDE', 'MAMUL'):
        kategori_prosesleri = [p for p in prosesler if p['kategori'] == kategori]
        if not kategori_prosesleri:
            continue
        
        # MIN yuzde
        en_yavas = min(kategori_prosesleri, key=lambda x: x['yuzde'])
        
        sonuc[kategori] = {
            'yuzde': round(en_yavas['yuzde'], 2),
            'alt_proses': en_yavas['proses_kod'],
            'alt_proses_adi': en_yavas['proses_adi'],
            'yapilan': en_yavas['yapilan_korgun'],
            'hedef': en_yavas['hedef'],
            'usta': en_yavas['usta'],
        }
    
    return sonuc


def darbogaz_tespit(kategori_data):
    """
    Kategori yuzdelerinden ana darbogaz + alt darbogaz tespit.
    Returns: {'ana_darbogaz', 'alt_darbogaz_proses', 'kilitlenecek_usta', 'darbogaz_yuzde'}
    """
    # Sadece dolu kategorileri al
    dolu_kategoriler = {k: v for k, v in kategori_data.items() if v is not None}
    
    if not dolu_kategoriler:
        return None
    
    # Ana darbogaz = en dusuk yuzdeli kategori
    ana_kategori = min(dolu_kategoriler.keys(), key=lambda k: dolu_kategoriler[k]['yuzde'])
    ana_data = dolu_kategoriler[ana_kategori]
    
    return {
        'ana_darbogaz': ana_kategori,
        'alt_darbogaz_proses': ana_data['alt_proses'],
        'alt_darbogaz_proses_adi': ana_data['alt_proses_adi'],
        'kilitlenecek_usta': ana_data['usta'],
        'darbogaz_yuzde': ana_data['yuzde'],
        'darbogaz_yapilan': ana_data['yapilan'],
        'darbogaz_hedef': ana_data['hedef'],
    }


def siparis_hesapla(siparis_no, model_kod=None, musteri=None, hedef_toplam=None):
    """
    Tek siparis icin tam darbogaz hesabi yapar ve siparis_darbogaz'a yazar.
    Returns: dict (darbogaz ozeti)
    """
    prosesler = proses_yuzde_hesapla(siparis_no)
    
    if not prosesler:
        return {'hata': f'Siparis {siparis_no} icin proses verisi yok'}
    
    kategoriler = kategori_yuzdeleri(prosesler)
    db = darbogaz_tespit(kategoriler)
    
    if not db:
        return {'hata': 'Darbogaz tespit edilemedi'}
    
    # siparis_darbogaz'a yaz/guncelle
    c = _conn()
    try:
        cur = c.cursor()
        cur.execute("""
            INSERT INTO siparis_darbogaz (
                siparis_no, model_kod, musteri, hedef_toplam,
                atki_yuzde, govde_yuzde, mamul_yuzde,
                ana_darbogaz, alt_darbogaz_proses, kilitlenecek_usta,
                guncelleme
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(siparis_no) DO UPDATE SET
                model_kod = excluded.model_kod,
                musteri = excluded.musteri,
                hedef_toplam = excluded.hedef_toplam,
                atki_yuzde = excluded.atki_yuzde,
                govde_yuzde = excluded.govde_yuzde,
                mamul_yuzde = excluded.mamul_yuzde,
                ana_darbogaz = excluded.ana_darbogaz,
                alt_darbogaz_proses = excluded.alt_darbogaz_proses,
                kilitlenecek_usta = excluded.kilitlenecek_usta,
                guncelleme = CURRENT_TIMESTAMP
        """, (
            siparis_no, model_kod, musteri, hedef_toplam,
            kategoriler['ATKI']['yuzde'] if kategoriler['ATKI'] else 0,
            kategoriler['GOVDE']['yuzde'] if kategoriler['GOVDE'] else 0,
            kategoriler['MAMUL']['yuzde'] if kategoriler['MAMUL'] else 0,
            db['ana_darbogaz'],
            db['alt_darbogaz_proses'],
            db['kilitlenecek_usta'],
        ))
        c.commit()
    finally:
        c.close()
    
    return {
        'siparis_no': siparis_no,
        'kategoriler': kategoriler,
        'darbogaz': db,
        'tum_prosesler': prosesler,
    }


def darbogaz_ozet(siparis_no):
    """
    siparis_darbogaz tablosundan ozet okur (cache mantigi).
    """
    c = _conn()
    try:
        cur = c.cursor()
        cur.execute("SELECT * FROM siparis_darbogaz WHERE siparis_no = ?", (siparis_no,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        c.close()


# =====================================================
# TEST FONKSIYONU (komut satirindan calistirilabilir)
# =====================================================
if __name__ == '__main__':
    # TEST: Mock siparis 33680 icin proses verisi gir, hesapla
    import sys
    
    test_siparis = '33680'
    
    print(f"\n=== TEST: Siparis {test_siparis} ===\n")
    
    # Test verisi: siparis_proses_durum'a mock data
    c = _conn()
    try:
        cur = c.cursor()
        # Once temizle
        cur.execute("DELETE FROM siparis_proses_durum WHERE siparis_no = ?", (test_siparis,))
        
        # Test verisi: 600 cift hedef, kategorilere dagit
        test_veri = [
            ('26', 600, 480),  # Enjeksiyon - ATKI
            ('50', 600, 470),  # Eva Hazir - ATKI
            ('02', 600, 350),  # Kesim - GOVDE
            ('15', 600, 200),  # Saya - GOVDE
            ('18', 600, 180),  # Saya Kontrol - GOVDE (en yavas govde)
            ('42', 600, 250),  # Saya Hazir - GOVDE
            ('28', 600, 150),  # Monta Baslayacak - MAMUL
            ('30', 600, 120),  # Monta - MAMUL
            ('32', 600, 100),  # Mekval - MAMUL
            ('35', 600, 80),   # Temizleme - MAMUL (en yavas mamul)
        ]
        for proses_kod, hedef, yapilan in test_veri:
            cur.execute("""
                INSERT INTO siparis_proses_durum (siparis_no, proses_kod, hedef, yapilan_korgun)
                VALUES (?, ?, ?, ?)
            """, (test_siparis, proses_kod, hedef, yapilan))
        c.commit()
        print("Test verisi yazildi.\n")
    finally:
        c.close()
    
    # Hesapla
    sonuc = siparis_hesapla(
        test_siparis,
        model_kod='BRP-9000',
        musteri='Solariz Magza Beyazit',
        hedef_toplam=600
    )
    
    if 'hata' in sonuc:
        print(f"HATA: {sonuc['hata']}")
        sys.exit(1)
    
    # Sonuclari yazdir
    print("--- KATEGORI YUZDELERI ---")
    for kat, data in sonuc['kategoriler'].items():
        if data:
            print(f"  {kat:6}: %{data['yuzde']:5.1f}  ({data['yapilan']}/{data['hedef']})  alt: {data['alt_proses_adi']}")
    
    print("\n--- DARBOGAZ ---")
    db = sonuc['darbogaz']
    print(f"  Ana Darbogaz       : {db['ana_darbogaz']} (%{db['darbogaz_yuzde']})")
    print(f"  Alt Darbogaz Proses: {db['alt_darbogaz_proses_adi']}")
    print(f"  Kilitlenecek Usta  : {db['kilitlenecek_usta']}")
    print(f"  Yapilan/Hedef      : {db['darbogaz_yapilan']}/{db['darbogaz_hedef']}")
    
    print("\n--- TUM PROSESLER ---")
    for p in sonuc['tum_prosesler']:
        print(f"  [{p['kategori']:5}] {p['proses_adi']:20} {p['yapilan_korgun']:4}/{p['hedef']:4} = %{p['yuzde']:5.1f}  (usta: {p['usta']})")
    
    print("\nTest tamamlandi.")