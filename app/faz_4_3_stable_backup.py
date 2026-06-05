# -*- coding: utf-8 -*-
"""
faz_4_3_stable_backup.py
------------------------
FAZ 4.3 STABLE snapshot:
  1) C:\\cps_dev klasorunu komple kopyala
     -> C:\\cps_dev_backup_FAZ4_3_STABLE_YYYYMMDD_HHMM
  2) mock_data.db'yi ayrica kopyala
     -> C:\\cps_dev_db_backups\\mock_data_backup_FAZ4_3_YYYYMMDD_HHMM.db
  3) C:\\cps_dev\\FAZ4_3_STATUS.txt olustur
  4) .git varsa commit komutlarini yazdir (otomatik commit YAPMAZ)
"""

import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"


def klasor_boyutu(path):
    total = 0
    files = 0
    for dp, dns, fns in os.walk(path):
        for fn in fns:
            try:
                total += os.path.getsize(os.path.join(dp, fn))
                files += 1
            except Exception:
                pass
    return total, files


def main():
    if not os.path.exists(CPS_ROOT):
        print(f"[HATA] {CPS_ROOT} bulunamadi.")
        return 1

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M')

    backup_dir = rf"C:\cps_dev_backup_FAZ4_3_STABLE_{ts}"
    db_backup_dir = r"C:\cps_dev_db_backups"
    db_backup = os.path.join(db_backup_dir, f"mock_data_backup_FAZ4_3_{ts}.db")
    status_path = os.path.join(CPS_ROOT, "FAZ4_3_STATUS.txt")

    print("=" * 68)
    print(f"FAZ 4.3 STABLE SNAPSHOT  ({ts})")
    print("=" * 68)

    # --- 1) KLASOR YEDEK ---
    print()
    print(f"[1/3] Komple klasor yedegi:")
    print(f"      kaynak: {CPS_ROOT}")
    print(f"      hedef:  {backup_dir}")
    if os.path.exists(backup_dir):
        print(f"      [HATA] Hedef zaten var. Manuel sil ve tekrar dene.")
        return 2

    shutil.copytree(
        CPS_ROOT, backup_dir,
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo')
    )

    total, files = klasor_boyutu(backup_dir)
    print(f"      [OK] {files} dosya, {total/1024/1024:.1f} MB.")

    # --- 2) DB AYRI YEDEK ---
    print()
    print(f"[2/3] mock_data.db ayri kopya:")
    src_db = os.path.join(CPS_ROOT, "mock_data.db")
    if not os.path.exists(src_db):
        print(f"      [UYARI] {src_db} bulunamadi, atlandi.")
    else:
        os.makedirs(db_backup_dir, exist_ok=True)
        shutil.copy2(src_db, db_backup)
        size_mb = os.path.getsize(db_backup) / 1024 / 1024
        print(f"      [OK] {db_backup}")
        print(f"           {size_mb:.2f} MB.")

    # --- 3) STATUS TXT ---
    print()
    print(f"[3/3] Status dosyasi:")
    print(f"      {status_path}")

    status_content = f"""FAZ 4.3 - STABLE SNAPSHOT
=========================
Tamamlanma:  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
Klasor yedek: {backup_dir}
DB ayri yedek: {db_backup}


DURUM
-----
- Uretim kayit sistemi aktif (mock_data.db.uretim_kayit)
- Alt proses sistemi aktif (mock_data.db.emir_alt_proses)
- Usta onay sistemi aktif (ONAYLA / REDDET)
- Gecmis (/hedef/) ve gecmisim (/uretim/) aktif
- Durumlar: bekliyor / onaylandi / reddedildi tam calisiyor
- Sistem LOCAL DB ile calisiyor
- MES v2 devre disi (PLAN/RAPOR sekmeleri haric - henuz local'e cekilmedi)
- Korgun sadece veri kaynagi (read-only, pytds 25.7.184.221:1433)


AKTIF ENDPOINT'LER
------------------
URETIM:
  GET  /uretim/                       panel
  GET  /uretim/emir/<no>              emir ozeti (Korgun)
  GET  /uretim/emir/<no>/prosesler    alt prosesler (mock_data.db)
  GET  /uretim/gecmisim?limit=N       personel kayitlari
  POST /uretim/kaydet                 yeni kayit (proses_id + hedef asimi validasyon)

HEDEF:
  GET  /hedef/                        panel
  GET  /hedef/onaylar/bekleyen        bekleyen onaylar
  GET  /hedef/gecmis?limit=N          onay/red gecmisi
  POST /hedef/onayla                  usta onay
  POST /hedef/reddet                  usta red (not >=5 karakter zorunlu)


VERI AKISI
----------
Frontend (port 5057)
   |
   | HTTP + session cookie
   v
Flask routes (modules/uretim_giris/routes.py, modules/hedef/routes.py)
   |
   +--> mock_data.db                                     READ + WRITE
   |    (uretim_kayit, emir_alt_proses)
   |
   +--> Korgun MSSQL Solariz22 (pytds)                   READ only
        25.7.184.221:1433


ANAHTAR DOSYALAR
----------------
modules/uretim_giris/routes.py    /uretim/* handler'lar (uretim_kaydet validasyon dahil)
modules/hedef/routes.py           /hedef/* handler'lar (onay/red endpoint'leri)
static/js/uretim_giris.js         uretim ekrani + GECMISIM lazy-load (sona IIFE)
static/js/hedef.js                hedef ekrani + ONAYLAR/GECMIS override IIFE
mock_data.db                      SQLite, 2 tablo


YARIN - FAZ 4.4
---------------
Konu: /hedef/ PLAN ve RAPOR ekranlari

Yapilacaklar:
  - MES v2 baglantisini tamamen kaldir
  - PLAN ekrani: emir bazli hedef / yapilan / kalan
      kaynak: mock_data.db (yapilan) + Korgun (hedef/sip bilgisi)
  - RAPOR ekrani: tarih araligina gore
      * personel bazli toplam adet
      * proses bazli toplam adet
      * emir bazli toplam
  - Hedef hesabinda sadece ONAYLANAN kayitlar (onay_durum='onaylandi') dahil
  - Personel bazli gunluk cikti -> performans altyapisi

Dikkat:
  - /uretim/ akisini bozma
  - /hedef/onaylar ve /hedef/gecmis bozma
  - mock_data.db yapisini degistirme (yeni tablo eklenebilir, mevcut tablolar dokunulmaz)
  - Korgun DB'ye yazma YOK


GIT KOMUTLARI (opsiyonel)
-------------------------
cd C:\\cps_dev
git add -A
git commit -m "FAZ 4.3 STABLE - uretim + onay + gecmisim tam calisiyor"


GERI DONUS PLANI (acil durumda)
-------------------------------
Eger yarin bir sey bozulursa:
  1) CPS sunucusunu durdur
  2) C:\\cps_dev'i sil
  3) {backup_dir} icindekileri C:\\cps_dev'e kopyala
  4) Sunucuyu tekrar baslat
Veya sadece DB'yi geri yuklemek icin:
  copy {db_backup} C:\\cps_dev\\mock_data.db


PATCH GECMISI (BU SEANSTA EKLENENLER)
-------------------------------------
- patch_uretim_prosesler_v2.py        /emir/<no>/prosesler eklendi
- fix_double_prefix.py                cift /uretim prefix'i duzeltildi
- add_proses_aliases.py               ad/adi/name/label/proses alias
- add_kod_hedef_aliases.py            kod/hedef alias
- setup_hedef_onaylar.py              4 hedef endpoint + override IIFE
- setup_uretim_validation_ve_gecmisim.py  proses_id validasyon + gecmisim

Tum yedekler routes.py.bak_* / hedef.js.bak_* / uretim_giris.js.bak_* olarak
ilgili dosyalarin yaninda mevcut.
"""

    with open(status_path, 'w', encoding='utf-8') as f:
        f.write(status_content)
    print(f"      [OK] {len(status_content)} bayt.")

    # --- GIT KONTROL ---
    print()
    git_dir = os.path.join(CPS_ROOT, ".git")
    if os.path.exists(git_dir):
        print("[GIT] .git klasoru bulundu. Manuel commit icin:")
        print(f"      cd {CPS_ROOT}")
        print(f"      git add -A")
        print(f'      git commit -m "FAZ 4.3 STABLE - uretim + onay + gecmisim tam calisiyor"')
    else:
        print("[GIT] .git yok, atlandi.")

    print()
    print("=" * 68)
    print("FAZ 4.3 STABLE - KAYDEDILDI.")
    print("=" * 68)
    print(f"  Klasor yedek:  {backup_dir}")
    print(f"  DB ayri yedek: {db_backup}")
    print(f"  Status txt:    {status_path}")
    print()
    print("Yarin FAZ 4.4 (PLAN + RAPOR + performans) ile devam.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
