# -*- coding: utf-8 -*-
"""
apply_enjeksiyon_register.py
============================
F3 - app.py'ye enjeksiyon_bp import + register satirlarini ekler.

Garantiler:
  - Idempotent: marker bazli, ayni patch ikinci kez calistirildiginda skip.
  - Atomic: .tmp dosyaya yazar, AST syntax test eder, sonra os.replace.
  - Yedek: app.py.YEDEK_FAZ_ENJ_F3_<ts> alir (Adem'in YEDEK deseni).
  - CRLF/UTF-8 korur (BOM eklenmez).
  - Mevcut dosyalara dokunmaz disinda app.py'ye 2 satir ekler.

Markerlar:
  ENJ_F3_IMPORT    - line 31'den sonra (import satirinda yorum olarak)
  ENJ_F3_REGISTER  - line 57'den sonra (register satirinda yorum olarak)

Kullanim:
  py apply_enjeksiyon_register.py            # patch uygula
  py apply_enjeksiyon_register.py --rollback # en son yedekten geri yukle
  py apply_enjeksiyon_register.py --dry-run  # patch hazirla ama uygulama
"""
import os
import sys
import shutil
import ast
import glob
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PY = os.path.join(BASE_DIR, 'app.py')

IMPORT_MARKER   = '# ENJ_F3_IMPORT'
REGISTER_MARKER = '# ENJ_F3_REGISTER'

IMPORT_ANCHOR   = 'from modules.tasks import tasks_bp'
REGISTER_ANCHOR = 'app.register_blueprint(personel_giris_bp)  # PERSONEL_GIRIS_BRIDGE'

IMPORT_LINE   = 'from modules.enjeksiyon import enjeksiyon_bp  ' + IMPORT_MARKER
REGISTER_LINE = 'app.register_blueprint(enjeksiyon_bp)  ' + REGISTER_MARKER


def yedek_al():
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    yedek = APP_PY + '.YEDEK_FAZ_ENJ_F3_' + ts
    shutil.copy2(APP_PY, yedek)
    return yedek


def en_son_yedek():
    yedekler = sorted(glob.glob(APP_PY + '.YEDEK_FAZ_ENJ_F3_*'))
    return yedekler[-1] if yedekler else None


def syntax_test(path):
    with open(path, 'rb') as f:
        src = f.read()
    ast.parse(src, filename=path)


def patch_uygula(dry_run=False):
    print('[1/6] Mevcut app.py okunuyor...')
    with open(APP_PY, 'rb') as f:
        raw = f.read()

    if b'\r\n' in raw:
        nl = '\r\n'
        nl_label = 'CRLF'
    else:
        nl = '\n'
        nl_label = 'LF'
    print('       Line ending: ' + nl_label)
    print('       Boyut       : {} byte'.format(len(raw)))

    content = raw.decode('utf-8')

    print('[2/6] Idempotency kontrol...')
    has_imp = IMPORT_MARKER in content
    has_reg = REGISTER_MARKER in content
    if has_imp and has_reg:
        print('  [SKIP] Patch zaten uygulanmis (her iki marker da var)')
        return False
    if has_imp or has_reg:
        print('  [HATA] Kismi patch tespit edildi:')
        print('         IMPORT marker  : ' + ('VAR' if has_imp else 'YOK'))
        print('         REGISTER marker: ' + ('VAR' if has_reg else 'YOK'))
        print('  Manuel mudahale gerekli.')
        sys.exit(2)
    print('  [OK] Temiz dosya - patch uygulanabilir')

    print('[3/6] Anchor satirlari araniyor...')
    lines = content.split(nl)

    import_idx = -1
    register_idx = -1
    for i, ln in enumerate(lines):
        s = ln.rstrip()
        if import_idx == -1 and s == IMPORT_ANCHOR:
            import_idx = i
        if register_idx == -1 and s == REGISTER_ANCHOR:
            register_idx = i

    if import_idx == -1:
        print('  [HATA] Import anchor bulunamadi:')
        print('         ' + IMPORT_ANCHOR)
        sys.exit(3)
    if register_idx == -1:
        print('  [HATA] Register anchor bulunamadi:')
        print('         ' + REGISTER_ANCHOR)
        sys.exit(4)

    print('  [OK] Import   anchor   : line {}'.format(import_idx + 1))
    print('  [OK] Register anchor   : line {}'.format(register_idx + 1))
    print('  [PLAN] Yeni IMPORT     : line {}'.format(import_idx + 2))
    print('  [PLAN] Yeni REGISTER   : line {}'.format(register_idx + 2 + 1))

    if dry_run:
        print('\n[DRY-RUN] Patch uygulanmadi. Cikiliyor.')
        return False

    print('[4/6] Yedek aliniyor...')
    yedek = yedek_al()
    print('       ' + os.path.basename(yedek))

    print('[5/6] Patch uygulaniyor (.tmp + syntax test + os.replace)...')
    yeni = list(lines)
    yeni.insert(register_idx + 1, REGISTER_LINE)
    yeni.insert(import_idx + 1, IMPORT_LINE)

    yeni_content = nl.join(yeni)
    yeni_bytes = yeni_content.encode('utf-8')

    tmp = APP_PY + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(yeni_bytes)
    print('       .tmp yazildi: {} byte'.format(len(yeni_bytes)))

    try:
        syntax_test(tmp)
        print('       [OK] AST syntax test gecti')
    except SyntaxError as e:
        print('       [HATA] Syntax error: ' + str(e))
        os.remove(tmp)
        print('       .tmp silindi, app.py degismedi.')
        sys.exit(5)

    os.replace(tmp, APP_PY)
    print('       [OK] os.replace tamamlandi')

    print('[6/6] Son dogrulama...')
    with open(APP_PY, 'r', encoding='utf-8', newline='') as f:
        son = f.read()
    if IMPORT_MARKER in son and REGISTER_MARKER in son:
        print('  [OK] Iki marker da mevcut, patch tamamlandi.')
    else:
        print('  [HATA] Marker dogrulama basarisiz!')
        sys.exit(6)

    print('       Yedek dosyasi: ' + os.path.basename(yedek))
    return True


def rollback():
    yedek = en_son_yedek()
    if not yedek:
        print('[HATA] FAZ_ENJ_F3 yedegi bulunamadi.')
        sys.exit(1)
    print('[ROLLBACK] Geri yukleniyor: ' + os.path.basename(yedek))
    shutil.copy2(yedek, APP_PY)
    with open(APP_PY, 'r', encoding='utf-8') as f:
        content = f.read()
    if IMPORT_MARKER in content or REGISTER_MARKER in content:
        print('[HATA] Marker hala mevcut - rollback basarisiz!')
        sys.exit(2)
    print('[OK] Rollback tamamlandi. app.py temiz.')


def main():
    if not os.path.exists(APP_PY):
        print('[HATA] app.py bulunamadi: ' + APP_PY)
        sys.exit(1)

    print('=' * 60)
    print('apply_enjeksiyon_register.py - F3')
    print('=' * 60)

    if '--rollback' in sys.argv:
        rollback()
    elif '--dry-run' in sys.argv:
        patch_uygula(dry_run=True)
    else:
        sonuc = patch_uygula()
        if sonuc:
            print('\n' + '=' * 60)
            print('[TAMAM] F3 patch basarili.')
            print('  Sonraki adim: Task Scheduler restart + /enjeksiyon/api/saglik test')
            print('=' * 60)


if __name__ == '__main__':
    main()
