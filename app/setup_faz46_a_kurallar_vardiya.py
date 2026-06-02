# -*- coding: utf-8 -*-
"""
setup_faz46_a_kurallar_vardiya.py
---------------------------------
ADIM A:
  1) CPS_KURALLAR.txt -> Madde 5 genislet, Madde 10/11 ekle (FAZ 4.6)
  2) CPS_SISTEM_MANTIGI_FINAL.txt -> Yeniden yaz (FAZ 4.6 yansisi)
  3) modules/uretim_giris/routes.py -> uretim_kaydet vardiya hesabi
     1/2/3 (8 saat) -> 'gunduz'/'gece' (10/14 saat)

Idempotent. Tum dosyalar yedeklenir.
"""

import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
KURALLAR_PATH = os.path.join(CPS_ROOT, "CPS_KURALLAR.txt")
MANTIK_PATH = os.path.join(CPS_ROOT, "CPS_SISTEM_MANTIGI_FINAL.txt")
URETIM_ROUTES = os.path.join(CPS_ROOT, "modules", "uretim_giris", "routes.py")


# =====================================================================
# 1) CPS_KURALLAR.txt
# =====================================================================
KURALLAR_NEW = """CPS KURALLAR — DEGISMEZ
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

5) Usta ONAYLAR, KAPATIR ve SABLON tanimlar           [FAZ 4.6 genisletme]
   - /hedef/ ONAYLAR sekmesinden onay/red
   - Onayla -> onay_durum='onaylandi'
   - Reddet -> onay_durum='reddedildi' (>=5 karakter not zorunlu)
   - SABLON: proses + saat -> hedef tanimi (lookup tablosu)
     * Hibrit: genel temel sablon + emire ozel override
   - Ileride sablon yetkisi planlama roluna devredilebilir

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

10) MESAI SISTEMI                                     [FAZ 4.6 yeni]
    - Normal calisma gunu disinda is (hafta sonu, fazla mesai)
    - Onceden tanimlanir: tarih + bas/bit saat + katilan personel
    - Sadece RAPORLAMA amacli, kayit girisi engellenmez
    - Raporda kayit 'mesai mi normal mi' ayirt edilir

11) VARDIYA TANIMI                                    [FAZ 4.6 yeni]
    - Gunduz: 07:00 - 17:00 (10 saat)
    - Gece:   17:00 - 07:00 (ertesi gun) (14 saat)
    - String: "gunduz" / "gece" (sayisal degil)
    - Saatten otomatik hesaplanir, kayit response'unda doner
    - NOT: FAZ 4.5'teki 1/2/3 sayisal hesap iptal edildi.

==========================================
BU KURALLAR DEGISMEZ. CELISKI VARSA UYARI.
==========================================
"""


# =====================================================================
# 2) CPS_SISTEM_MANTIGI_FINAL.txt
# =====================================================================
MANTIK_NEW = """CPS — SISTEM MANTIGI (FINAL)
=============================
Tarih: {tarih}
Durum: STABIL — Bu doküman kilitlenmistir.
Son güncelleme: FAZ 4.6 (madde 5 genisletme + madde 10/11 ekleme)


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
       |    Tablolar: uretim_kayit, emir_alt_proses,
       |              sablon, mesai, mesai_personel  [FAZ 4.6 yeni]
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
  - SABLON tanimlar: /hedef/ SABLON sekmesi              [FAZ 4.6+]
  - MESAI tanimlar: /hedef/ MESAI sekmesi (planlanan)    [FAZ 4.6+]
  - GECMIS sekmesinde tum islem gormus kayitlari gorur

ADMIN / YONETIM
  - PLAN ekranindan emir bazli ilerleme
  - RAPOR ekranindan tarih bazli analiz
  - Yonetim, kullanici, rol, log


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

VARDIYA HESABI (uretim_kaydet'te, kayit zamaninda):     [FAZ 4.6]
  saat = simdi.hour
  if 7 <= saat < 17:  vardiya = 'gunduz'  (10 saat)
  else:               vardiya = 'gece'    (14 saat)
  Response'a 'vardiya' alani eklenir.

RAPOR ekrani:
  - Sadece onay_durum='onaylandi' kayitlar
  - Tarih: COALESCE(onay_tarihi, olusturma)
  - 3 blok: personel/proses/emir bazli SUM(miktar) + COUNT(*)
  - Mesai isareti (FAZ 4.6+): mesai tablosunda eslesen tarih+saat+personel


6. AKTIF ENDPOINT'LER
---------------------

URETIM (modules/uretim_giris/routes.py)
  GET  /uretim/                       Panel
  GET  /uretim/emir/<no>              Emir ozeti (Korgun get_emir_ozet)
  GET  /uretim/emir/<no>/prosesler    Alt prosesler (mock_data.db)
  GET  /uretim/gecmisim?limit=N       Login personelin kayitlari
  POST /uretim/kaydet                 Yeni kayit (validasyonlar)
                                       - emir geçerli, hedef >0, proses_id valid
                                       - duplicate kontrol (60sn)
                                       - vardiya hesaplanir (gunduz/gece)
  GET  /uretim/proxy/<path>           (Eski MES v2 proxy — kullanim YOK)

HEDEF (modules/hedef/routes.py)
  GET  /hedef/                        Panel
  GET  /hedef/plan                    PLAN ekrani verisi (KORGUN+CPS)
  GET  /hedef/rapor?baslangic=&bitis= RAPOR ekrani verisi (sadece CPS)
  GET  /hedef/dogrulama               Veri kalitesi 4 blok + legacy
  GET  /hedef/onaylar/bekleyen        Bekleyen onaylar
  GET  /hedef/gecmis?limit=N          Onay/red gecmisi
  POST /hedef/onayla                  Usta onay (uretim_kayit_id, not?)
  POST /hedef/reddet                  Usta red (uretim_kayit_id, not >=5)

  PLANLANAN (FAZ 4.6 B+C):
  GET  /hedef/sablon                  Sablon listesi
  POST /hedef/sablon/ekle             Yeni sablon
  POST /hedef/sablon/guncelle/<id>
  POST /hedef/sablon/sil/<id>
  GET  /hedef/sablon/ara              Lookup (proses+saat -> hedef)
  GET  /hedef/mesai/liste             Mesai tanimlari
  POST /hedef/mesai/ekle              Yeni mesai
  POST /hedef/mesai/sil/<id>


7. KRITIK KURALLAR (DEGISMEZ)
-----------------------------

* Korgun'a YAZMA yok. Hicbir endpoint INSERT/UPDATE/DELETE atmaz.
* MES v2 kullanilmayacak. Yeni gelistirmeler CPS local'a baglanir.
* Ana emir miktari asilmaz; backend uretim_kaydet'te kontrol var.
* Personel onay veremez; sadece bekliyor durumunda kayit ekler.
* RAPOR Korgun verisi gostermez; CPS onayli kayitlardan hesaplar.
* PLAN hesabinda hem Korgun hem CPS toplanir; CPS bekleyenler dahil DEGIL.
* mock_data.db semasi degistirilmez; YENI TABLO eklenir, mevcut tutulur.
* Onayli/reddedilmis kayit silinmez; gecmiste gorunmeye devam eder.
* MESAI sistemi sadece raporlama amaclidir; kayit girisini engellemez.
* SABLON sistemi hibrit: genel temel + emire ozel override.
* VARDIYA sayisal DEGIL, string ('gunduz'/'gece'); saatten otomatik.
* Eski string proses_kodu kayitlari LEGACY say (FAZ 4.5b);
  yeni kontroller sadece numeric proses_kodu icin uygulanir.


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
  - "Personel onaylasin" -> RED, kural 4 (rol)
  - "RAPOR'a Korgun verisi ekle" -> RED, kural 7 (rapor cps-only)
  - "MES v2 endpoint'ini geri ac" -> RED, kural 9


10. TAMAMLANAN FAZLAR
---------------------

FAZ 4.3 STABLE (yedek: cps_dev_backup_FAZ4_3_STABLE_*)
  - Uretim kayit sistemi (mock_data.db.uretim_kayit)
  - Alt proses sistemi (mock_data.db.emir_alt_proses)
  - Usta onay/red
  - GECMIS (/hedef/) ve GECMISIM (/uretim/)

FAZ 4.4
  - PLAN ekrani: Korgun + CPS canli ilerleme
  - PLAN: SIPARISLER kolonu, renk yok (ERP'de yok)
  - RAPOR endpoint: 3 blok ozet (personel/proses/emir)
  - RAPOR v6 frontend: KPI + arama + sira + limit + katlama
  - MES v2 izi tamamen kaldirildi (fetch monkey-patch)

FAZ 4.5
  - HEDEF_YOK / DUPLICATE / VARDIYA kontroller (uretim_kaydet)
  - /hedef/dogrulama endpoint (4 blok suspheli kayit)
  - UI: sari uyari banner + modal

FAZ 4.5b
  - Legacy mode: eski string proses_kodu kayitlari korumali
  - Modal'a 5. blok 'Legacy Kayitlar'
  - toplam_uyari sayisi yalnizca yeni format kayitlari kapsar

FAZ 4.6 ADIM A (su an)
  - CPS_KURALLAR madde 5 genisletme + madde 10/11 ekleme
  - VARDIYA: 1/2/3 (8 saat) -> 'gunduz'/'gece' (10/14 saat)

FAZ 4.6 PLANLANAN
  - ADIM B: Sablon sistemi (hibrit: genel + emir override)
  - ADIM C: Mesai sistemi (raporlama amacli)


11. NOT
-------
Bu doküman kilitlidir. Sistem mantigi degistirilmez.
Yeni gelistirmeler bu temel uzerine yapilir.

Adem'in talimati:
  > Bu mantik degistirilmez.
  > Yeni ozellik yazarken bu kurallara uyulacak.
  > Eger bir gelistirme bu kurallarla celisirse: kod yazma, uyari ver.
""".format(tarih=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))


# =====================================================================
# 3) uretim_kaydet vardiya hesabi - str_replace
# =====================================================================
VARDIYA_OLD = """        # === FAZ 4.5: VARDIYA hesabi (07-15=1, 15-23=2, 23-07=3) ===
        try:
            _hh = simdi.hour
            if 7 <= _hh < 15:
                _vardiya = 1
            elif 15 <= _hh < 23:
                _vardiya = 2
            else:
                _vardiya = 3
        except Exception:
            _vardiya = None"""

VARDIYA_NEW = """        # === FAZ 4.6: VARDIYA hesabi (07-17=gunduz, 17-07=gece) ===
        try:
            _hh = simdi.hour
            if 7 <= _hh < 17:
                _vardiya = 'gunduz'
            else:
                _vardiya = 'gece'
        except Exception:
            _vardiya = None"""


# =====================================================================
# Helpers
# =====================================================================

def backup(path):
    if not os.path.exists(path):
        return None
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = path + f'.bak_{ts}'
    shutil.copy2(path, bp)
    return bp


def yaz(path, content):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def patch_kurallar():
    print()
    print("=" * 64)
    print("1/3 CPS_KURALLAR.txt")
    print("=" * 64)
    bp = backup(KURALLAR_PATH)
    if bp:
        print(f"  [OK] Yedek: {bp}")
    yaz(KURALLAR_PATH, KURALLAR_NEW)
    print(f"  [OK] {len(KURALLAR_NEW)} bayt yazildi (madde 5/10/11 guncel).")
    return True


def patch_mantik():
    print()
    print("=" * 64)
    print("2/3 CPS_SISTEM_MANTIGI_FINAL.txt")
    print("=" * 64)
    bp = backup(MANTIK_PATH)
    if bp:
        print(f"  [OK] Yedek: {bp}")
    yaz(MANTIK_PATH, MANTIK_NEW)
    print(f"  [OK] {len(MANTIK_NEW)} bayt yazildi (FAZ 4.6 yansisi).")
    return True


def patch_vardiya():
    print()
    print("=" * 64)
    print("3/3 modules/uretim_giris/routes.py - vardiya")
    print("=" * 64)
    if not os.path.exists(URETIM_ROUTES):
        print(f"  [HATA] {URETIM_ROUTES} bulunamadi.")
        return False
    with open(URETIM_ROUTES, 'r', encoding='utf-8') as f:
        src = f.read()

    if VARDIYA_NEW in src:
        print("  [BILGI] Vardiya hesabi zaten yeni format ('gunduz'/'gece').")
        return True

    if VARDIYA_OLD not in src:
        print("  [HATA] Eski vardiya bloku bulunamadi.")
        print("         (FAZ 4.5 patch'i uygulanmadi mi?)")
        return False
    if src.count(VARDIYA_OLD) > 1:
        print("  [HATA] Eski blok birden fazla.")
        return False

    new_src = src.replace(VARDIYA_OLD, VARDIYA_NEW, 1)

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False

    bp = backup(URETIM_ROUTES)
    print(f"  [OK] Yedek: {bp}")
    with open(URETIM_ROUTES, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] vardiya: 1/2/3 (8 saat) -> 'gunduz'/'gece' (10/14 saat)")
    return True


def main():
    print("=" * 64)
    print("FAZ 4.6 ADIM A - Kurallar guncelleme + Vardiya duzeltme")
    print("=" * 64)

    if not os.path.exists(CPS_ROOT):
        print(f"  [HATA] {CPS_ROOT} bulunamadi.")
        return 1

    ok1 = patch_kurallar()
    ok2 = patch_mantik()
    ok3 = patch_vardiya()

    print()
    print("=" * 64)
    if ok1 and ok2 and ok3:
        print("ADIM A TAMAM.")
        print("=" * 64)
        print()
        print("YAPILACAK:")
        print("  1) CPS sunucusunu yeniden baslat (vardiya icin)")
        print("  2) Test:")
        print("     /uretim/ -> 110626 -> kayit gir")
        print("     Response'da 'vardiya': 'gunduz' veya 'gece' (sayi degil)")
        print()
        print("Saat 09:55 (su an) -> vardiya='gunduz' beklenir.")
        print()
        print("Yeni kurallar:")
        print(f"  type {KURALLAR_PATH}")
        print()
        print("Hazir olunca: 'devam ADIM B' de, sablon sistemi yazayim.")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
