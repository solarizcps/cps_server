# -*- coding: utf-8 -*-
"""
sablon_b3_stable_backup.py
--------------------------
Sablon B3 STABLE snapshot:
  1) C:\\cps_dev tam klasor yedek -> C:\\cps_dev_backup_SABLON_B3_STABLE_YYYYMMDD_HHMM
  2) mock_data.db ayri kopya -> C:\\cps_dev_db_backups\\mock_data_sablon_b3_stable_YYYYMMDD_HHMM.db
  3) Status txt -> C:\\cps_dev\\SABLON_B3_STATUS.txt
"""

import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"


def klasor_boyutu(path):
    total, files = 0, 0
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
    backup_dir = rf"C:\cps_dev_backup_SABLON_B3_STABLE_{ts}"
    db_backup_dir = r"C:\cps_dev_db_backups"
    db_backup = os.path.join(db_backup_dir, f"mock_data_sablon_b3_stable_{ts}.db")
    status_path = os.path.join(CPS_ROOT, "SABLON_B3_STATUS.txt")

    print("=" * 68)
    print(f"SABLON B3 STABLE SNAPSHOT  ({ts})")
    print("=" * 68)

    # 1) KLASOR YEDEK
    print()
    print(f"[1/3] Komple klasor yedegi:")
    print(f"      kaynak: {CPS_ROOT}")
    print(f"      hedef:  {backup_dir}")
    if os.path.exists(backup_dir):
        print(f"      [HATA] Hedef zaten var. Silmek icin:")
        print(f"      rmdir /s /q \"{backup_dir}\"")
        return 2

    shutil.copytree(
        CPS_ROOT, backup_dir,
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo',
                                       'cps_dev_backup_*', 'cps_dev_db_backups')
    )
    total, files = klasor_boyutu(backup_dir)
    print(f"      [OK] {files} dosya, {total/1024/1024:.1f} MB.")

    # 2) DB AYRI YEDEK
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

    # 3) STATUS TXT
    print()
    print(f"[3/3] Status dosyasi:")
    print(f"      {status_path}")

    status_content = f"""SABLON B3 - STABLE SNAPSHOT
============================
Tarih:           {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
Klasor yedek:    {backup_dir}
DB ayri yedek:   {db_backup}


DURUM
-----
- Sablon B3 sistemi tamamlandi.
- Siparis emirlerine sablon uygulama AKTIF.
- Toplu sablon uygulama AKTIF.
- Sablon Geri Al AKTIF.
- Korgun = read-only (INSERT/UPDATE/DELETE yok).
- CPS = mock_data.db'ye yazar (emir_alt_proses, sablon, sablon_proses).
- Renk mapping bekliyor (RKOD -> renk adi, Adem tarafindan verilecek).


SAGLIK KONTROL SONUCU (saglik.txt)
-----------------------------------
- 11 endpoint: hepsi tanimli
- emir_alt_proses: 16 kayit (12 aktif + 4 pasif)
  - kaynak dagilimi: 10 sablon + 6 manuel + 0 bos
- sablon: 1 aktif (Atki LCW, 4 proses)
- yetim sablon_proses: yok
- duplicate aktif: yok
- aktif/pasif karisikligi: yok
- Korgun INSERT/UPDATE/DELETE: yok (read-only OK)
- uretim_kaydet sablon kullanmiyor (kural OK)
- syntax 3 dosya temiz
- 21 OK, 0 RISK, 0 HATA


AKTIF SABLON ENDPOINT'LERI
---------------------------
GET    /hedef/sablon/liste
GET    /hedef/sablon/proses-onerileri
POST   /hedef/sablon/ekle
POST   /hedef/sablon/guncelle/<id>
POST   /hedef/sablon/sil/<id>
GET    /hedef/siparis/emirler?sipno=
GET    /hedef/siparis/emir-detay?emirler=...
POST   /hedef/sablon/uygula
POST   /hedef/sablon/geri-al


VERI AKISI
----------
Frontend SABLON sekmesi
   |
   +--> Sablon Yonetimi (CRUD)
   |    POST /hedef/sablon/ekle/guncelle/sil
   |    -> mock_data.db.sablon + sablon_proses
   |
   +--> Siparis Emirlerine Sablon Uygula
        GET /hedef/siparis/emirler?sipno=33558
        -> Korgun helper get_siparis_emirleri (read-only)
           1) Siparis_Har -> ana emirler (Tip='M')
           2) Urt_Em2Em -> alt emirler (Tip='Y')
           3) Cari_Kart JOIN -> CariAdi
           4) siparis_kalemleri (siparis toplam adedi)

        Lazy: GET /hedef/siparis/emir-detay?emirler=1,2,3,...
        -> Urt_Em_gch SUM(Giren) + RKOD (lot bazli emir miktari)

        Toplu uygula: POST /hedef/sablon/uygula
        -> mock_data.db.emir_alt_proses INSERT (kaynak='sablon:Atki LCW')

        Geri al: POST /hedef/sablon/geri-al
        -> emir_alt_proses UPDATE aktif=0
           (kaynak LIKE 'sablon:%' filtre, manuel kayitlar korunur)


GERI DONUS PLANI
----------------
Acil durumda:
  1) CPS sunucusunu durdur
  2) C:\\cps_dev'i sil (yedek var)
  3) Bu klasoru kopyala:
     {backup_dir}
  4) Sunucuyu tekrar baslat
Veya sadece DB:
  copy "{db_backup}" C:\\cps_dev\\mock_data.db


BEKLEYEN ISLER
--------------
1) Renk (RKOD) mapping
   - Korgun'da renk katalogu yok
   - Mock_data.db'de manuel mapping tablosu olusturulabilir
   - Adem RKOD listesini verecek (ornek: 1=Siyah, 4=Beyaz)

2) Duplicate emir gorunumu (110852 ornegi)
   - Sql JOIN bazi emirleri tekrar uretiyor
   - get_siparis_emirleri'da DISTINCT EmirNo veya GROUP BY duzeltmesi


CPS_KURALLAR UYUMU
-------------------
- Korgun read-only:                              OK
- MES v2 yok:                                    OK
- Sablon hedef uretmez (sadece proses listesi):  OK
- uretim_kaydet sablon dokunmuyor:               OK
- mock_data.db schema: yeni tablo (eski bozulmuyor): OK
- Manuel kayitlar geri-al'da korunuyor:          OK
"""

    with open(status_path, 'w', encoding='utf-8') as f:
        f.write(status_content)
    print(f"      [OK] {len(status_content)} bayt.")

    print()
    print("=" * 68)
    print("SABLON B3 STABLE - KAYDEDILDI.")
    print("=" * 68)
    print(f"  Klasor yedek:  {backup_dir}")
    print(f"  DB ayri yedek: {db_backup}")
    print(f"  Status txt:    {status_path}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
