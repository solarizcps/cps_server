# -*- coding: utf-8 -*-
"""
kaydet_cps_kurallar.py
----------------------
CPS sistem mantigini iki dosya olarak proje icine kaydeder:
  1) C:\\cps_dev\\CPS_SISTEM_MANTIGI_FINAL.txt   (uzun, kapsamli)
  2) C:\\cps_dev\\CPS_KURALLAR.txt                (kisa, 9 madde)

Idempotent:
  - Dosya yoksa: yeni yaz
  - Dosya varsa: eskisini .bak_TS olarak yedekler, sonra yenisini yaz
"""

import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
LONG_PATH = os.path.join(CPS_ROOT, "CPS_SISTEM_MANTIGI_FINAL.txt")
SHORT_PATH = os.path.join(CPS_ROOT, "CPS_KURALLAR.txt")


SHORT_CONTENT = """CPS KURALLAR — DEGISMEZ
========================

1) Korgun = SADECE VERI KAYNAGI
   - Read-only erisim
   - Hicbir sekilde yazilmaz

2) CPS = URETIM + PERSONEL + ANALIZ
   - Tum yeni veri burada tutulur (mock_data.db)
   - Personel kayitlari, onaylar, gecmis hepsi CPS

3) Ana emir miktari ASILMAZ
   - Korgun hedef + CPS bekleyen + CPS onayli = max hedef
   - Backend validasyonu var (uretim_kaydet)

4) Personel sadece KAYIT GIRER
   - Onay yetkisi yok
   - Kayitlari onay_durum='bekliyor' ile baslar

5) Usta ONAYLAR ve KAPATIR
   - /hedef/ ONAYLAR sekmesinden
   - Onayla -> onay_durum='onaylandi'
   - Reddet -> onay_durum='reddedildi' (>=5 karakter not zorunlu)

6) PLAN = Korgun + CPS toplam ilerleme
   - get_emir_ozet (Korgun hedef + Korgun yapilan)
   - + CPS onayli (mock_data.db)
   - = Toplam yapilan, kalan, %

7) RAPOR = SADECE CPS analiz
   - mock_data.db.uretim_kayit (onaylandi)
   - Tarih araligi, personel/proses/emir bazli ozet
   - Korgun verisi rapora KARISMAZ

8) Korgun'a YAZMA YOK
   - Hicbir endpoint Korgun'a INSERT/UPDATE/DELETE atmaz
   - Sadece SELECT

9) MES v2 KULLANILMAYACAK
   - Eski /api/v2/... endpoint'leri devre disi
   - Yeni gelistirmeler CPS local + Korgun read

==========================================
BU KURALLAR DEGISMEZ. CELISKI VARSA UYARI.
==========================================
"""


LONG_CONTENT = """CPS — SISTEM MANTIGI (FINAL)
=============================
Tarih: {tarih}
Durum: STABIL — Bu doküman kilitlenmistir.


1. AMAC
-------
Solariz Terlik fabrikasinin uretim sureclerini Korgun ERP'yi bozmadan,
yeni veriyi yerel CPS sistemine yazarak yonetmek.

  Korgun = saglam, mevcut, kullanilan ERP (dokunulmaz)
  CPS    = uretim girisi + personel takip + onay + analiz katmani


2. UC KATMANLI MIMARI
---------------------

  Frontend (browser, port 5057)
       |
       | HTTP + session cookie
       v
  Flask routes (modules/uretim_giris/, modules/hedef/, ...)
       |
       +--> mock_data.db (SQLite)            READ + WRITE
       |    Tablolar: uretim_kayit, emir_alt_proses
       |
       +--> Korgun MSSQL Solariz22 (pytds)   READ ONLY
            25.7.184.221:1433
            Tablolar: Urt_Emir, Siparis_Har, Urt_Em_gch,
                      Urt_con_gch, Urtx_con_gch, Cari_Kart, ...


3. ROLLER
---------

PERSONEL
  - /uretim/ ekranindan kayit girer
  - Emir secer, proses secer, miktar girer
  - onay_durum = 'bekliyor' olarak baslar
  - GECMISIM sekmesinde kendi kayitlarini gorur
  - ONAY YETKISI YOK

USTA
  - /hedef/ ONAYLAR sekmesinden bekleyen kayitlari gorur
  - ONAYLA -> onay_durum = 'onaylandi'
  - REDDET -> onay_durum = 'reddedildi' (>=5 karakter not zorunlu)
  - GECMIS sekmesinde tum islem gormus kayitlari gorur

ADMIN / YONETIM
  - PLAN ekranindan emir bazli ilerleme
  - RAPOR ekranindan tarih bazli analiz


4. VERI AKISI (ONAY HATTI)
--------------------------

  Personel kayit girer
       |
       v
  mock_data.db.uretim_kayit  (onay_durum='bekliyor')
       |
       v
  Usta onaylar/reddeder
       |
       v
  mock_data.db.uretim_kayit  (onay_durum='onaylandi' veya 'reddedildi')
       |
       v
  PLAN'da toplam_yapilan'a katilir (sadece 'onaylandi')
  RAPOR'da tarih analizine girer (sadece 'onaylandi')

NOT: Korgun'a yazim YOK. Onayli kayitlar mock_data.db'de kalir.
     Ileride Korgun'a aktarim yapilirsa, ayri bir sync surecidir,
     ana sistemi etkilemez.


5. HESAPLAMA KURALLARI
-----------------------

PLAN ekrani (her aktif emir icin):
  hedef            = Siparis_Har toplam        (Korgun)
  korgun_yapilan   = Urt_Em_gch SUM(Cikan)     (Korgun)
  cps_yapilan      = mock_data SUM(miktar) WHERE onay_durum='onaylandi'
  toplam_yapilan   = korgun_yapilan + cps_yapilan
  kalan            = max(0, hedef - toplam_yapilan)
  yuzde            = (toplam_yapilan / hedef) * 100

ASIM KONTROLU (uretim_kaydet endpoint'inde):
  bekleyen_local = mock_data SUM(miktar) WHERE onay_durum='bekliyor'
  acik_kalan     = max(0, hedef - korgun_yapilan - bekleyen_local)
  if (yeni_miktar > acik_kalan) -> 400 hedef_asimi

RAPOR ekrani:
  - Sadece onay_durum='onaylandi' kayitlar
  - Tarih: COALESCE(onay_tarihi, olusturma)
  - 3 blok: personel/proses/emir bazli SUM(miktar) + COUNT(*)


6. AKTIF ENDPOINT'LER
---------------------

URETIM (modules/uretim_giris/routes.py)
  GET  /uretim/                       Panel
  GET  /uretim/emir/<no>              Emir ozeti (Korgun get_emir_ozet)
  GET  /uretim/emir/<no>/prosesler    Alt prosesler (mock_data.db)
  GET  /uretim/gecmisim?limit=N       Login personelin kayitlari
  POST /uretim/kaydet                 Yeni kayit (proses_id + asim valid.)
  GET  /uretim/proxy/<path>           (Eski MES v2 proxy — kullanim YOK)

HEDEF (modules/hedef/routes.py)
  GET  /hedef/                        Panel
  GET  /hedef/plan                    PLAN ekrani verisi (KORGUN+CPS)
  GET  /hedef/rapor?baslangic=&bitis= RAPOR ekrani verisi (sadece CPS)
  GET  /hedef/onaylar/bekleyen        Bekleyen onaylar
  GET  /hedef/gecmis?limit=N          Onay/red gecmisi
  POST /hedef/onayla                  Usta onay (uretim_kayit_id, not?)
  POST /hedef/reddet                  Usta red (uretim_kayit_id, not >=5)


7. KRITIK KURALLAR (DEGISMEZ)
-----------------------------

* Korgun'a YAZMA yok. Hicbir endpoint INSERT/UPDATE/DELETE atmaz.
* MES v2 kullanilmayacak. Yeni gelistirmeler CPS local'a baglanir.
* Ana emir miktari asilmaz; backend uretim_kaydet'te kontrol var.
* Personel onay veremez; sadece bekliyor durumunda kayit ekler.
* RAPOR Korgun verisi gostermez; CPS onayli kayitlardan hesaplar.
* PLAN hesabinda hem Korgun hem CPS toplanir; CPS bekleyenler dahil DEGIL.
* mock_data.db semasi degistirilmez; yeni tablo eklenir, mevcut tutulur.
* Onayli/reddedilmis kayit silinmez; gecmiste gorunmeye devam eder.


8. GELISTIRME PRENSIPLERI
-------------------------

* Yeni endpoint backend dosyasi sonuna eklenir, mevcut bozulmaz
* Frontend override IIFE pattern'i: window.X = yenisi
* Eski IIFE'ler dosyada kalir (geri donus icin)
* Her yazimdan once .bak_YYYYMMDD_HHMMSS yedek
* AST dogrulama, JS node --check
* Idempotent marker'larla cift uygulama engellenir
* Adem'in zamanini bos diagnose ile harcama; hedefli ol


9. CELISKI DURUMU
------------------
Yeni bir gelistirme bu kurallarla celisirse:
  - Kod YAZILMAZ
  - Once UYARI verilir
  - Adem onaylarsa kural revize edilir, sonra kod yazilir

Ornekler:
  - "Korgun'a tarih yaz" -> RED, kural 7
  - "Personel onaylasin" -> RED, kural 3 (rol)
  - "RAPOR'a Korgun verisi ekle" -> RED, kural 5 (rapor cps-only)
  - "MES v2 endpoint'ini geri ac" -> RED, kural 7


10. TAMAMLANAN FAZLAR
---------------------

FAZ 4.3 STABLE (yedek: cps_dev_backup_FAZ4_3_STABLE_*)
  - Uretim kayit sistemi (mock_data.db.uretim_kayit)
  - Alt proses sistemi (mock_data.db.emir_alt_proses)
  - Usta onay/red
  - GECMIS (/hedef/) ve GECMISIM (/uretim/)
  - Status dosyasi: FAZ4_3_STATUS.txt

FAZ 4.4 (devam ediyor)
  - PLAN ekrani: Korgun + CPS canli ilerleme (v4 hizalama)
  - PLAN: SIPARISLER kolonu, renk yok (ERP'de yok)
  - RAPOR endpoint: 3 blok ozet (personel/proses/emir)
  - RAPOR v6 frontend: KPI + arama + sira + limit + katlama
  - MES v2 izi tamamen kaldirildi (fetch monkey-patch)


11. NOT
-------
Bu doküman kilitlidir. Sistem mantigi degistirilmez.
Yeni gelistirmeler bu temel uzerine yapilir.

Adem'in talimati:
  > Bu mantik degistirilmez.
  > Yeni ozellik yazarken bu kurallara uyulacak.
  > Eger bir gelistirme bu kurallarla celisirse: kod yazma, uyari ver.
""".format(tarih=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))


def yedek_al(path):
    if not os.path.exists(path):
        return None
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = path + f'.bak_{ts}'
    shutil.copy2(path, bp)
    return bp


def yaz(path, content):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def main():
    print()
    print("=" * 64)
    print("CPS SISTEM MANTIGI - DOSYA OLUSTURMA")
    print("=" * 64)

    if not os.path.exists(CPS_ROOT):
        print(f"  [HATA] {CPS_ROOT} bulunamadi.")
        return 1

    # 1) Uzun
    print()
    print(f"1) UZUN: {LONG_PATH}")
    bp1 = yedek_al(LONG_PATH)
    if bp1:
        print(f"   [OK] Yedek: {bp1}")
    yaz(LONG_PATH, LONG_CONTENT)
    print(f"   [OK] {len(LONG_CONTENT)} bayt yazildi.")

    # 2) Kisa
    print()
    print(f"2) KISA: {SHORT_PATH}")
    bp2 = yedek_al(SHORT_PATH)
    if bp2:
        print(f"   [OK] Yedek: {bp2}")
    yaz(SHORT_PATH, SHORT_CONTENT)
    print(f"   [OK] {len(SHORT_CONTENT)} bayt yazildi.")

    print()
    print("=" * 64)
    print("KAYDEDILDI VE KILITLENDI.")
    print("=" * 64)
    print()
    print("Bundan sonra:")
    print("  - Bu kurallar DEGISMEZ")
    print("  - Yeni Claude'a context icin: type CPS_KURALLAR.txt")
    print("  - Detayli baglam icin: type CPS_SISTEM_MANTIGI_FINAL.txt")
    print()
    print("Anlasildi: Yeni gelistirme bu kurallarla celisirse:")
    print("  - Kod yazmayacagim")
    print("  - Once uyaracagim")
    print("  - Adem onaylarsa kural revize edilir, sonra kod yazilir")
    return 0


if __name__ == '__main__':
    sys.exit(main())
