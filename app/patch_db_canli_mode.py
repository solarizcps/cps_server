# -*- coding: utf-8 -*-
"""
CPS DEV — Patch: db.py get_conn() canli env okuma
====================================================

KAPSAM:
  db.py icindeki get_conn() fonksiyonu, modul-level DB_MODE sabitini
  kullaniyor. Bu sabit Python modulu import edildiginde okunup
  donduruluyor; runtime'da env degisirse fark etmiyor.

  Patch: get_conn() her cagrildiginda env degiskeninden taze okur,
  her cagri icin '[DB] get_conn mode = X' logu basar.

DEGISTIRILEN BLOK (sadece bu, baska yere dokunulmuyor):
  ESKI:
    def get_conn():
        return _sqlite_conn() if DB_MODE == 'mock' else _mssql_conn()

  YENI:
    def get_conn():
        import os as _os
        _mode = _os.environ.get('CPS_DB_MODE', DB_MODE) or 'mock'
        print(f'[DB] get_conn mode = {_mode}', flush=True)
        return _sqlite_conn() if _mode == 'mock' else _mssql_conn()

KORUNAN:
  - module-level DB_MODE = Config.DB_MODE (geriye uyum)
  - _sqlite_conn(), _mssql_conn() (degismiyor)
  - qone, q, qexec ve digerleri (degismiyor)
  - auth.py, app.py, herhangi bir route (dokunulmuyor)
  - mimari, login, UI (dokunulmuyor)

GUVENLIK:
  - Yedek alinir (tarih damgali)
  - Idempotent: yeni blok marker 'CPS_DB_MODE_LIVE_V1' varsa atlanir
  - Eski blok bulunamazsa hicbir degisiklik
  - Atomik yazma: .tmp -> os.replace
  - py_compile ile syntax dogrulama

NASIL CALISTIRILIR:
  cd C:\\cps_dev
  python patch_db_canli_mode.py
"""

import os
import sys
import shutil
import py_compile
from datetime import datetime

HEDEF = 'db.py'

# Eski blok — db.py icindeki tam metin (Get-Content cikti gore)
ESKI = """def get_conn():
    return _sqlite_conn() if DB_MODE == 'mock' else _mssql_conn()"""

# Yeni blok
YENI = """def get_conn():
    # CPS_DB_MODE_LIVE_V1: Her cagrida env'den taze oku (modul-level cache yok)
    import os as _os
    _mode = _os.environ.get('CPS_DB_MODE', DB_MODE) or 'mock'
    print(f'[DB] get_conn mode = {_mode}', flush=True)
    return _sqlite_conn() if _mode == 'mock' else _mssql_conn()"""


def yaz(msg):
    sys.stdout.write(msg + '\n')
    sys.stdout.flush()


def cik(code, msg):
    yaz(msg)
    sys.exit(code)


def main():
    yaz('')
    yaz('=' * 60)
    yaz('  CPS DEV — Patch: db.py canli env okuma')
    yaz('=' * 60)

    if not os.path.isfile(HEDEF):
        cik(1, f'HATA: Hedef dosya bulunamadi: {HEDEF}\n'
               '  Bu scripti C:\\cps_dev\\ dizininde calistir.')

    yaz(f'Hedef  : {HEDEF}')

    try:
        with open(HEDEF, 'r', encoding='utf-8') as f:
            mevcut = f.read()
    except Exception as e:
        cik(2, f'HATA: Dosya okunamadi: {e}')

    ilk_boyut = len(mevcut)
    yaz(f'Boyut  : {ilk_boyut} byte')

    # 1) Baseline syntax kontrol
    try:
        compile(mevcut, HEDEF, 'exec')
    except SyntaxError as e:
        cik(3, f'HATA: Mevcut dosyada zaten syntax hatasi: {e}\n'
               '  Patch uygulanmadi.')

    # 2) Idempotency — yeni marker var mi?
    if 'CPS_DB_MODE_LIVE_V1' in mevcut:
        cik(0, '\nBILGI: Patch marker dosyada zaten mevcut.\n'
               '  Patch daha once uygulanmis - yeniden uygulama yapilmadi.')

    # 3) Eski blok bulunmali
    eski_sayi = mevcut.count(ESKI)
    yaz(f'Eski blok eslesmesi: {eski_sayi}x  (beklenen: 1)')
    if eski_sayi == 0:
        cik(4, 'HATA: Beklenen get_conn() blogu bulunamadi.\n'
               '  db.py manuel duzenlenmis veya farkli bir versiyonda olabilir.\n'
               '  Hicbir degisiklik yapilmadi.')
    if eski_sayi > 1:
        cik(5, f'HATA: Eski blok {eski_sayi} kez geciyor (beklenen 1).\n'
               '  Patch iptal.')

    # 4) Yedek
    damga = datetime.now().strftime('%Y%m%d_%H%M%S')
    yedek_yol = f'{HEDEF}.yedek_canlimode_{damga}'
    try:
        shutil.copy2(HEDEF, yedek_yol)
    except Exception as e:
        cik(6, f'HATA: Yedek alinamadi: {e}\n  Patch uygulanmadi.')

    yaz(f'Yedek  : {yedek_yol}')

    # 5) Replace
    yeni = mevcut.replace(ESKI, YENI, 1)
    if yeni == mevcut:
        cik(7, 'HATA: Replace sonrasi icerik aynen kaldi.')
    if 'CPS_DB_MODE_LIVE_V1' not in yeni:
        cik(8, 'HATA: Yeni marker yeni icerikte yok.')

    # 6) Gecici dosyaya yaz
    tmp_yol = HEDEF + '.tmp_patch'
    try:
        with open(tmp_yol, 'w', encoding='utf-8', newline='') as f:
            f.write(yeni)
    except Exception as e:
        try:
            if os.path.isfile(tmp_yol):
                os.remove(tmp_yol)
        except Exception:
            pass
        cik(9, f'HATA: Gecici dosya yazilamadi: {e}')

    # 7) Syntax dogrula
    try:
        py_compile.compile(tmp_yol, doraise=True)
    except py_compile.PyCompileError as e:
        try:
            os.remove(tmp_yol)
        except Exception:
            pass
        cik(10, f'HATA: Yeni icerik syntax hatasi: {e}\n'
                '  Orijinal dokunulmadi.')

    # 8) Boyut sanity
    yeni_boyut = os.path.getsize(tmp_yol)
    fark = yeni_boyut - ilk_boyut
    yaz(f'Boyut farki: +{fark} byte (yeni toplam: {yeni_boyut})')

    if fark < 50 or fark > 500:
        try:
            os.remove(tmp_yol)
        except Exception:
            pass
        cik(11, f'HATA: Boyut farki beklenen disinda: +{fark}.\n'
                '  Beklenen 50-500 byte. Patch iptal.')

    # 9) Atomik rename
    try:
        os.replace(tmp_yol, HEDEF)
    except Exception as e:
        try:
            if os.path.isfile(tmp_yol):
                os.remove(tmp_yol)
        except Exception:
            pass
        cik(12, f'HATA: Dosya guncellenemedi: {e}\n  Yedek duruyor.')

    yaz('')
    yaz('=' * 60)
    yaz('  PATCH BASARIYLA UYGULANDI')
    yaz('=' * 60)
    yaz(f'Dosya  : {HEDEF}')
    yaz(f'Yedek  : {yedek_yol}')
    yaz('')
    yaz('Yeni davranis:')
    yaz('  - get_conn() her cagrida CPS_DB_MODE env\'ini taze okur')
    yaz('  - CPS_DB_MODE yoksa Config.DB_MODE kullanilir, o da yoksa mock')
    yaz('  - Her cagri terminalde su logu basar:')
    yaz('      [DB] get_conn mode = mock')
    yaz('')
    yaz('Test:')
    yaz('  1) Flask\'i Ctrl+C ile durdur')
    yaz('  2) CMD\'de:')
    yaz('       cd C:\\cps_dev')
    yaz('       set CPS_DB_MODE=mock')
    yaz('       python app.py')
    yaz('  3) Tarayicida login dene:')
    yaz('       http://127.0.0.1:5057/giris?next=/ithalat/parti/liste')
    yaz('       admin / admin123')
    yaz('  4) Terminalde "[DB] get_conn mode = mock" loglari akmali')
    yaz('  5) TimeoutError YOK olmali, parti listesi gelmeli')
    yaz('')
    yaz('Geri alma:')
    yaz(f'  copy "{yedek_yol}" "{HEDEF}"')
    yaz('')


if __name__ == '__main__':
    main()
