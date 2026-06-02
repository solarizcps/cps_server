# -*- coding: utf-8 -*-
"""
CPS DEV — Patch v2: app.py debug parametresi env-aware
=======================================================

v2 NOTLARI (v1'den fark):
  - BOM (U+FEFF) toleransi eklendi.
  - app.py'nin basinda BOM olabilir (Windows editorlerden).
  - Python interpreter BOM'u kabul eder ama compile() hata verir.
  - Patch BOM varsa once siyirir, sonra syntax kontrol eder.

KAPSAM (v1 ile ayni):
  app.run(host=..., port=..., debug=Config.DEBUG) -> env-aware
"""

import os
import sys
import shutil
import py_compile
from datetime import datetime

HEDEF = 'app.py'

ESKI = """    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)"""

YENI = """    # CPS_DEBUG_ENV_AWARE_V1: FLASK_DEBUG env varsa onu kullan
    import os as _os
    _dbg_env = _os.environ.get('FLASK_DEBUG')
    if _dbg_env is not None:
        _dbg = _dbg_env not in ('0', 'false', 'False', '')
    else:
        _dbg = Config.DEBUG
    app.run(host=Config.HOST, port=Config.PORT, debug=_dbg)"""


def yaz(msg):
    sys.stdout.write(msg + '\n')
    sys.stdout.flush()


def cik(code, msg):
    yaz(msg)
    sys.exit(code)


def main():
    yaz('')
    yaz('=' * 60)
    yaz('  CPS DEV — Patch v2: app.py debug env-aware (BOM toleransli)')
    yaz('=' * 60)

    if not os.path.isfile(HEDEF):
        cik(1, f'HATA: Hedef dosya bulunamadi: {HEDEF}')

    yaz(f'Hedef  : {HEDEF}')

    try:
        with open(HEDEF, 'r', encoding='utf-8-sig') as f:  # utf-8-sig: BOM otomatik siyrilir
            mevcut = f.read()
    except Exception as e:
        cik(2, f'HATA: Dosya okunamadi: {e}')

    ilk_boyut = len(mevcut)
    yaz(f'Boyut  : {ilk_boyut} byte (BOM siyrildi)')

    # Baseline syntax kontrolu (BOM olmadan)
    try:
        compile(mevcut, HEDEF, 'exec')
        yaz('Baseline syntax: OK')
    except SyntaxError as e:
        cik(3, f'HATA: Mevcut dosyada gercekten syntax hatasi: {e}')

    # Idempotency
    if 'CPS_DEBUG_ENV_AWARE_V1' in mevcut:
        cik(0, '\nBILGI: Patch marker zaten mevcut.\n  Yeniden uygulanmadi.')

    eski_sayi = mevcut.count(ESKI)
    yaz(f'Eski blok eslesmesi: {eski_sayi}x  (beklenen: 1)')
    if eski_sayi == 0:
        cik(4, 'HATA: Beklenen app.run() satiri bulunamadi.')
    if eski_sayi > 1:
        cik(5, f'HATA: Eski blok {eski_sayi} kez geciyor.')

    # Yedek (orijinal BOM'lu hali ile)
    damga = datetime.now().strftime('%Y%m%d_%H%M%S')
    yedek_yol = f'{HEDEF}.yedek_debugenv_{damga}'
    try:
        shutil.copy2(HEDEF, yedek_yol)
    except Exception as e:
        cik(6, f'HATA: Yedek alinamadi: {e}')

    yaz(f'Yedek  : {yedek_yol}')

    # Replace
    yeni = mevcut.replace(ESKI, YENI, 1)
    if yeni == mevcut:
        cik(7, 'HATA: Replace sonrasi icerik aynen kaldi.')
    if 'CPS_DEBUG_ENV_AWARE_V1' not in yeni:
        cik(8, 'HATA: Yeni marker yeni icerikte yok.')

    # Tmp yaz (BOM YOK — utf-8 yazıyoruz, eski BOM kaybolur ama Python sorunsuz okur)
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

    # Syntax dogrula (yeni dosya, BOM yok)
    try:
        py_compile.compile(tmp_yol, doraise=True)
        yaz('Yeni icerik syntax: OK')
    except py_compile.PyCompileError as e:
        try:
            os.remove(tmp_yol)
        except Exception:
            pass
        cik(10, f'HATA: Yeni icerik syntax hatasi: {e}')

    # Boyut sanity
    yeni_boyut = os.path.getsize(tmp_yol)
    fark = yeni_boyut - os.path.getsize(yedek_yol)
    yaz(f'Boyut farki: {fark:+d} byte')

    # BOM siyirilirsa 3 byte azalir, patch ekleyince ~250 byte artar -> net +200-300
    if fark < 100 or fark > 600:
        try:
            os.remove(tmp_yol)
        except Exception:
            pass
        cik(11, f'HATA: Boyut farki beklenen disinda: {fark:+d}')

    # Atomik rename
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
    yaz('  - FLASK_DEBUG=0 -> debug OFF')
    yaz('  - FLASK_DEBUG=1 -> debug ON')
    yaz('  - FLASK_DEBUG yok -> Config.DEBUG (eski davranis)')
    yaz('')
    yaz('Test:')
    yaz('  1) Flask\'i Ctrl+C ile durdur (gerekirse 2 kere)')
    yaz('  2) PowerShell:')
    yaz('       cd C:\\cps_dev')
    yaz('       $env:CPS_DB_MODE = "mock"')
    yaz('       $env:FLASK_DEBUG = "0"')
    yaz('       python app.py')
    yaz('  3) Cikti BEKLENEN:')
    yaz('       Debug mode: off')
    yaz('       (Restarting with stat YOK)')
    yaz('       (Debugger is active YOK)')
    yaz('  4) Login dene + log akisini izle')
    yaz('       Loglar: [DB] get_conn mode = mock')
    yaz('')
    yaz('Geri alma:')
    yaz(f'  copy "{yedek_yol}" "{HEDEF}"')
    yaz('')


if __name__ == '__main__':
    main()
