# -*- coding: utf-8 -*-
"""
SOLARIZ CPS - FAZ 1
Sapma Kontrolu

Mantik:
1. Her aktif siparis icin darbogaz hesapla
2. Darbogaz prosesinin sapmasini hesapla:
   - Olmasi gereken = (gecen_sure / vardiya_suresi) * gun_hedefi
   - Sapma % = (olmasi_gereken - gercek) / olmasi_gereken
3. %30+ ise:
   - sapma_olay tablosuna kayit ac (durum: SEBEP_BEKLENIYOR)
   - usta_kilit_durum: kilit_aktif=1
4. siparis_darbogaz tablosunda sapma_yuzde + seviye guncelle
"""
import sqlite3
from datetime import datetime, time
from config import Config
from modules.uretim_yonetim import darbogaz as db_motor


# =====================================================
# AYARLAR
# =====================================================
SAPMA_ESIGI_BUYUK = 30.0  # %30 ve uzeri = BUYUK_SAPMA
SAPMA_ESIGI_IZLE  = 15.0  # %15-30 arasi = IZLE
VARDIYA_BASLANGIC = time(7, 0)   # 07:00
VARDIYA_BITIS     = time(17, 0)  # 17:00
VARDIYA_SURE_SAAT = 10           # V1 toplam 10 saat


def _conn():
    conn = sqlite3.connect(Config.MOCK_DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def gecen_sure_orani(simdi=None):
    """
    Vardiya icinde gecen sure oranini hesaplar (0.0 - 1.0).
    Vardiya disinda ise 0 doner.
    """
    if simdi is None:
        simdi = datetime.now().time()
    
    if simdi < VARDIYA_BASLANGIC:
        return 0.0
    if simdi >= VARDIYA_BITIS:
        return 1.0
    
    # Saat farki
    baslangic_dakika = VARDIYA_BASLANGIC.hour * 60 + VARDIYA_BASLANGIC.minute
    simdi_dakika = simdi.hour * 60 + simdi.minute
    toplam_dakika = VARDIYA_SURE_SAAT * 60
    
    return (simdi_dakika - baslangic_dakika) / toplam_dakika


def sapma_hesapla(gun_hedef, gercek_yapilan, simdi=None):
    """
    Tek darbogaz prosesi icin sapma hesabi.
    Returns: dict {olmasi_gereken, gercek, sapma_yuzde, seviye}
    """
    oran = gecen_sure_orani(simdi)
    
    if oran <= 0:
        # Vardiya baslamadi
        return {
            'olmasi_gereken': 0,
            'gercek': gercek_yapilan,
            'sapma_yuzde': 0.0,
            'seviye': 'NORMAL',
            'gecen_sure_orani': 0.0,
        }
    
    olmasi_gereken = round(gun_hedef * oran)
    
    if olmasi_gereken == 0:
        sapma_yuzde = 0.0
    else:
        sapma_yuzde = ((olmasi_gereken - gercek_yapilan) / olmasi_gereken) * 100
    
    # Seviye tespiti
    if sapma_yuzde >= SAPMA_ESIGI_BUYUK:
        seviye = 'BUYUK_SAPMA'
    elif sapma_yuzde >= SAPMA_ESIGI_IZLE:
        seviye = 'IZLE'
    else:
        seviye = 'NORMAL'
    
    return {
        'olmasi_gereken': olmasi_gereken,
        'gercek': gercek_yapilan,
        'sapma_yuzde': round(sapma_yuzde, 2),
        'seviye': seviye,
        'gecen_sure_orani': round(oran, 2),
    }


def sapma_olay_ac(siparis_no, proses_kod, usta, sapma_data):
    """
    sapma_olay tablosuna yeni kayit acar.
    Ayni siparis+proses icin acik kayit varsa, yenisini acmaz.
    """
    c = _conn()
    try:
        cur = c.cursor()
        
        # Acik sapma var mi kontrol et
        cur.execute("""
            SELECT id FROM sapma_olay 
            WHERE siparis_no = ? AND proses_kod = ? AND durum = 'SEBEP_BEKLENIYOR'
            ORDER BY id DESC LIMIT 1
        """, (siparis_no, proses_kod))
        mevcut = cur.fetchone()
        
        if mevcut:
            return mevcut['id']  # Zaten acik kayit var
        
        # Yeni kayit ac
        cur.execute("""
            INSERT INTO sapma_olay (
                siparis_no, proses_kod, usta,
                olmasi_gereken, gercek, sapma_yuzde, seviye, durum
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'SEBEP_BEKLENIYOR')
        """, (
            siparis_no, proses_kod, usta,
            sapma_data['olmasi_gereken'],
            sapma_data['gercek'],
            sapma_data['sapma_yuzde'],
            sapma_data['seviye'],
        ))
        sapma_olay_id = cur.lastrowid
        c.commit()
        return sapma_olay_id
    finally:
        c.close()


def kilit_ac(usta, sapma_olay_id):
    """
    Ustanin kilit_aktif=1 yapar.
    """
    c = _conn()
    try:
        cur = c.cursor()
        cur.execute("""
            INSERT INTO usta_kilit_durum (kullanici, kilit_aktif, sapma_olay_id, baslangic)
            VALUES (?, 1, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(kullanici) DO UPDATE SET
                kilit_aktif = 1,
                sapma_olay_id = excluded.sapma_olay_id,
                baslangic = CURRENT_TIMESTAMP
        """, (usta, sapma_olay_id))
        c.commit()
    finally:
        c.close()


def siparis_kontrol(siparis_no):
    """
    Tek siparis icin tam akis:
    1. Darbogaz hesapla
    2. Darbogaz prosesinin sapmasini hesapla
    3. %30+ ise sapma_olay ac + kilit aktif et
    4. siparis_darbogaz'da sapma_yuzde + seviye guncelle
    
    Returns: dict (sonuc ozeti)
    """
    # Siparis darbogaz ozeti al
    db_ozet = db_motor.darbogaz_ozet(siparis_no)
    
    if not db_ozet:
        return {'hata': f'{siparis_no} icin darbogaz bilgisi yok'}
    
    # Darbogaz prosesinin yapilanini bul
    c = _conn()
    try:
        cur = c.cursor()
        cur.execute("""
            SELECT yapilan_korgun, hedef 
            FROM siparis_proses_durum 
            WHERE siparis_no = ? AND proses_kod = ?
        """, (siparis_no, db_ozet['alt_darbogaz_proses']))
        row = cur.fetchone()
        
        if not row:
            return {'hata': 'Darbogaz proses verisi yok'}
        
        gercek_yapilan = row['yapilan_korgun']
        gun_hedef = db_ozet['hedef_toplam']
        
        # Sapma hesapla
        sapma = sapma_hesapla(gun_hedef, gercek_yapilan)
        
        # siparis_darbogaz tablosunda sapma_yuzde + seviye guncelle
        cur.execute("""
            UPDATE siparis_darbogaz 
            SET sapma_yuzde = ?, seviye = ?, guncelleme = CURRENT_TIMESTAMP
            WHERE siparis_no = ?
        """, (sapma['sapma_yuzde'], sapma['seviye'], siparis_no))
        c.commit()
    finally:
        c.close()
    
    # BUYUK_SAPMA ise kilit ac
    sapma_olay_id = None
    if sapma['seviye'] == 'BUYUK_SAPMA':
        sapma_olay_id = sapma_olay_ac(
            siparis_no=siparis_no,
            proses_kod=db_ozet['alt_darbogaz_proses'],
            usta=db_ozet['kilitlenecek_usta'],
            sapma_data=sapma,
        )
        kilit_ac(db_ozet['kilitlenecek_usta'], sapma_olay_id)
    
    return {
        'siparis_no': siparis_no,
        'darbogaz_proses': db_ozet['alt_darbogaz_proses'],
        'usta': db_ozet['kilitlenecek_usta'],
        'sapma': sapma,
        'sapma_olay_id': sapma_olay_id,
        'kilit_aktif': sapma['seviye'] == 'BUYUK_SAPMA',
    }


def tum_aktif_siparisler_kontrol():
    """
    siparis_darbogaz'daki tum siparisleri kontrol et.
    Returns: list of sonuc dict
    """
    c = _conn()
    try:
        cur = c.cursor()
        cur.execute("SELECT siparis_no FROM siparis_darbogaz")
        siparisler = [r['siparis_no'] for r in cur.fetchall()]
    finally:
        c.close()
    
    sonuclar = []
    for sno in siparisler:
        sonuc = siparis_kontrol(sno)
        sonuclar.append(sonuc)
    
    return sonuclar


# =====================================================
# TEST
# =====================================================
if __name__ == '__main__':
    print("\n=== SAPMA KONTROL TESTI ===\n")
    
    # Once darbogaz hesabini taze yap (Adim 2'deki test verisi varsayiliyor)
    test_siparis = '33680'
    
    print(f"Siparis: {test_siparis}")
    print(f"Su anki saat: {datetime.now().strftime('%H:%M')}")
    print(f"Vardiya: {VARDIYA_BASLANGIC} - {VARDIYA_BITIS}\n")
    
    # Vardiya icinde miyiz?
    oran = gecen_sure_orani()
    print(f"Vardiya gecen sure orani: %{oran*100:.1f}\n")
    
    # Darbogaz hesabi
    sonuc = db_motor.siparis_hesapla(
        test_siparis,
        model_kod='BRP-9000',
        musteri='Solariz Magza Beyazit',
        hedef_toplam=600
    )
    
    print(f"Darbogaz: {sonuc['darbogaz']['alt_darbogaz_proses_adi']}")
    print(f"Yapilan: {sonuc['darbogaz']['darbogaz_yapilan']}/{sonuc['darbogaz']['darbogaz_hedef']}\n")
    
    # Sapma kontrolu
    kontrol_sonuc = siparis_kontrol(test_siparis)
    
    print("--- SAPMA SONUCU ---")
    s = kontrol_sonuc['sapma']
    print(f"  Olmasi gereken : {s['olmasi_gereken']}")
    print(f"  Gercek         : {s['gercek']}")
    print(f"  Sapma          : %{s['sapma_yuzde']}")
    print(f"  Seviye         : {s['seviye']}")
    print(f"  Kilit aktif mi : {kontrol_sonuc['kilit_aktif']}")
    
    if kontrol_sonuc['kilit_aktif']:
        print(f"  Sapma olay ID  : {kontrol_sonuc['sapma_olay_id']}")
        print(f"  Kilitlenen usta: {kontrol_sonuc['usta']}")
    
    # Halil'in kilit durumunu kontrol et
    print("\n--- HALIL KILIT DURUMU ---")
    c = _conn()
    try:
        cur = c.cursor()
        cur.execute("SELECT * FROM usta_kilit_durum WHERE kullanici = 'halil'")
        row = cur.fetchone()
        if row:
            print(f"  kilit_aktif    : {row['kilit_aktif']}")
            print(f"  sapma_olay_id  : {row['sapma_olay_id']}")
            print(f"  baslangic      : {row['baslangic']}")
        else:
            print("  Kayit yok")
    finally:
        c.close()
    
    print("\nTest tamamlandi.")