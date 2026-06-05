# -*- coding: utf-8 -*-
"""
CPS DEV — durum_gecmisi fonksiyonu guvenli patch scripti
=========================================================

KAPSAM:
  Sadece modules/ithalat/queries.py icindeki durum_gecmisi fonksiyonunun
  SQL cumlesini duzeltir. Baska hicbir yere dokunmaz.

KURALLAR:
  - Once zaman damgali yedek alir
  - Eski bloku bulamazsa HICBIR degisiklik yapmaz
  - Degisiklikten once/sonra py_compile ile syntax dogrular
  - Atomik yazma: once .tmp, basarili olursa rename
  - Hersey OK ise hangi dosyaya yedek aldigini yazar

NASIL CALISTIRILIR:
  cd C:\\cps_dev
  python patch_durum_gecmisi.py
"""

import os
import sys
import shutil
import py_compile
from datetime import datetime

# =============================================================
# HEDEF
# =============================================================
HEDEF = os.path.join('modules', 'ithalat', 'queries.py')

# =============================================================
# ESKI BLOK — tam olarak dosyada gecen metin
# =============================================================
ESKI_BLOK = '''def durum_gecmisi(parti_id, limit=50):
    try:
        return q("""
            SELECT Id, IslemTarih AS Tarih, KayiciKullanici AS Kullanici,
                   Aciklama, Islem
            FROM sistem_audit
            WHERE KayitTipi = 'ithalat_parti'
              AND KayitId = ?
              AND Islem IN ('DURUM_DEGISIM', 'EKLE')
            ORDER BY IslemTarih DESC, Id DESC
            LIMIT ?
        """, (parti_id, int(limit)))
    except Exception as e:
        log.exception("durum_gecmisi hata: %s", e)
        return []'''

# =============================================================
# YENI BLOK — DB semasiyla uyumlu
# =============================================================
YENI_BLOK = '''def durum_gecmisi(parti_id, limit=50):
    try:
        return q("""
            SELECT Id, Tarih, KullaniciAdi AS Kullanici,
                   Aciklama, Islem
            FROM sistem_audit
            WHERE TabloAdi = 'ithalat_parti'
              AND KayitId = ?
              AND Islem IN ('DURUM_DEGISIM', 'EKLE')
            ORDER BY Tarih DESC, Id DESC
            LIMIT ?
        """, (parti_id, int(limit)))
    except Exception as e:
        log.exception("durum_gecmisi hata: %s", e)
        return []'''


def yaz(msg):
    sys.stdout.write(msg + '\n')
    sys.stdout.flush()


def cik(code, msg):
    yaz(msg)
    sys.exit(code)


def main():
    yaz('')
    yaz('=' * 60)
    yaz('  CPS DEV — durum_gecmisi patch scripti')
    yaz('=' * 60)

    # --- 1) Dosya var mi? ---
    if not os.path.isfile(HEDEF):
        cik(1, f'HATA: Hedef dosya bulunamadi: {HEDEF}\n'
               '  Bu scripti C:\\cps_dev\\ dizininde calistirdigindan emin ol.')

    yaz(f'Hedef  : {HEDEF}')

    # --- 2) Mevcut icerigi oku ---
    try:
        with open(HEDEF, 'r', encoding='utf-8') as f:
            mevcut = f.read()
    except Exception as e:
        cik(2, f'HATA: Dosya okunamadi: {e}')

    # --- 3) Once syntax dogru mu? (patch'ten ONCE baseline) ---
    try:
        compile(mevcut, HEDEF, 'exec')
    except SyntaxError as e:
        cik(3, f'HATA: Mevcut dosyada zaten syntax hatasi var: {e}\n'
               '  Patch uygulanmadi. Dosyayi once manuel duzelt.')

    # --- 4) Eski blok var mi? ---
    sayac = mevcut.count(ESKI_BLOK)
    if sayac == 0:
        # Zaten patch uygulanmis mi?
        if YENI_BLOK in mevcut:
            cik(0, '\nBILGI: Yeni blok zaten dosyada mevcut.\n'
                   '  Patch daha once uygulanmis - yeniden uygulama yapilmadi.\n'
                   '  (Hic dosya degisikligi yapilmadi, yedek de alinmadi.)')
        cik(4,
            'HATA: Eski blok dosyada bulunamadi.\n'
            '  Dosya manuel olarak degistirilmis olabilir ya da farkli bir\n'
            '  versiyondasin. HICBIR degisiklik yapilmadi.\n'
            '  Eski blok "def durum_gecmisi(parti_id, limit=50):" ile baslar.')
    if sayac > 1:
        cik(5,
            f'HATA: Eski blok dosyada {sayac} kez geciyor - beklenen 1.\n'
            '  Guvenlik icin hicbir degisiklik yapilmadi.\n'
            '  Dosyayi manuel incele.')

    yaz('Eski blok bulundu (1 eslesme).')

    # --- 5) Yedek al ---
    damga = datetime.now().strftime('%Y%m%d_%H%M%S')
    yedek_yol = f'{HEDEF}.yedek_{damga}'
    try:
        shutil.copy2(HEDEF, yedek_yol)
    except Exception as e:
        cik(6, f'HATA: Yedek alinamadi: {e}\n'
               '  Patch uygulanmadi (yedek zorunlu).')

    yaz(f'Yedek  : {yedek_yol}')

    # --- 6) Yeni icerigi hazirla ---
    yeni_icerik = mevcut.replace(ESKI_BLOK, YENI_BLOK, 1)

    if yeni_icerik == mevcut:
        cik(7, 'HATA: Replace sonrasi icerik aynen kaldi (beklenmedik).\n'
               '  Patch uygulanmadi.')

    # --- 7) Gecici dosyaya yaz ---
    tmp_yol = HEDEF + '.tmp_patch'
    try:
        with open(tmp_yol, 'w', encoding='utf-8', newline='') as f:
            f.write(yeni_icerik)
    except Exception as e:
        # tmp bozuksa temizle
        try:
            if os.path.isfile(tmp_yol):
                os.remove(tmp_yol)
        except Exception:
            pass
        cik(8, f'HATA: Gecici dosya yazilamadi: {e}\n'
               '  Orijinal dosya dokunulmadi.')

    # --- 8) Gecici dosya syntax dogrula ---
    try:
        py_compile.compile(tmp_yol, doraise=True)
    except py_compile.PyCompileError as e:
        try:
            os.remove(tmp_yol)
        except Exception:
            pass
        cik(9, f'HATA: Yeni icerik syntax hatasi veriyor, patch iptal.\n'
               f'  Detay: {e}\n'
               '  Orijinal dosya dokunulmadi.')

    # --- 9) Atomik rename: tmp -> gercek dosya ---
    try:
        os.replace(tmp_yol, HEDEF)
    except Exception as e:
        try:
            if os.path.isfile(tmp_yol):
                os.remove(tmp_yol)
        except Exception:
            pass
        cik(10, f'HATA: Dosya guncellenemedi (rename): {e}\n'
                '  Orijinal dosya dokunulmadi, yedek duruyor.')

    # --- 10) Son dogrulama: disktaki dosya gercekten yeni blogu iceriyor mu? ---
    try:
        with open(HEDEF, 'r', encoding='utf-8') as f:
            son_icerik = f.read()
    except Exception as e:
        cik(11, f'UYARI: Patch uygulandi ama dogrulama icin dosya okunamadi.\n'
                f'  {e}\n'
                f'  Yedek: {yedek_yol}')

    if YENI_BLOK not in son_icerik:
        cik(12, 'UYARI: Patch yazildi gibi gorundu ama yeni blok dosyada bulunamadi.\n'
                f'  Yedegi kontrol et: {yedek_yol}')

    # --- BASARILI ---
    yaz('')
    yaz('=' * 60)
    yaz('  PATCH BASARIYLA UYGULANDI')
    yaz('=' * 60)
    yaz(f'Dosya  : {HEDEF}')
    yaz(f'Yedek  : {yedek_yol}')
    yaz('')
    yaz('Degisiklik: durum_gecmisi fonksiyonu SQL cumlesi DB semasiyla uyumlu.')
    yaz('  IslemTarih      -> Tarih')
    yaz('  KayiciKullanici -> KullaniciAdi AS Kullanici')
    yaz('  KayitTipi       -> TabloAdi')
    yaz('')
    yaz('Geri alma: yedek dosyasini orijinal ismiyle kopyala:')
    yaz(f'  copy "{yedek_yol}" "{HEDEF}"')
    yaz('')


if __name__ == '__main__':
    main()
