import io, shutil, time, sys

PP = r'C:\cps_dev\modules\hedef\plan_v2.py'

with io.open(PP, 'r', encoding='utf-8') as f:
    src = f.read()

if 'PAGINATION_V1' in src:
    print('SKIP: zaten var')
    sys.exit(0)

OLD = """    response = {
        'ok': True,
        'siparis_sayisi': len(sonuc),
        'siparisler': sonuc,
    }"""

NEW = """    # PAGINATION_V1
    try:
        sayfa = int(request.args.get('page', 1))
    except:
        sayfa = 1
    if sayfa < 1: sayfa = 1
    limit = 10
    toplam = len(sonuc)
    toplam_sayfa = max(1, (toplam + limit - 1) // limit)
    if sayfa > toplam_sayfa: sayfa = toplam_sayfa
    bas = (sayfa - 1) * limit
    response = {
        'ok': True,
        'siparis_sayisi': toplam,
        'mevcut_sayfa': sayfa,
        'toplam_sayfa': toplam_sayfa,
        'limit': limit,
        'siparisler': sonuc[bas:bas+limit],
    }"""

if OLD not in src:
    print('HATA: anchor yok')
    sys.exit(1)

new_src = src.replace(OLD, NEW, 1)

if 'from flask import' in new_src and ', request' not in new_src.split('from flask import')[1].split('\n')[0]:
    new_src = new_src.replace(
        'from flask import Blueprint, jsonify, render_template',
        'from flask import Blueprint, jsonify, render_template, request',
        1
    )

shutil.copy2(PP, PP + '.bak_pagi_' + time.strftime('%Y%m%d_%H%M%S'))
with io.open(PP, 'w', encoding='utf-8') as f:
    f.write(new_src)
print('OK: backend pagination eklendi')