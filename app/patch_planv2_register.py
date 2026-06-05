"""ADIM 6: PLAN v2 blueprint kayit + sidebar link.

Iki dosyaya dokunur:
1. modules/hedef/__init__.py  → plan_v2_bp expose
2. app.py                     → blueprint kayit

Sidebar linki opsiyonel - simdilik atlandi (test sonrasi eklenir).
"""
import io, sys, shutil, time

# === 1) modules/hedef/__init__.py - plan_v2_bp expose ===
INIT_PATH = r'C:\cps_dev\modules\hedef\__init__.py'
INIT_MARKER = 'plan_v2_bp'

with io.open(INIT_PATH, 'r', encoding='utf-8') as f:
    init_src = f.read()

if INIT_MARKER in init_src:
    print('SKIP-INIT: plan_v2_bp zaten kayitli')
else:
    new_init = init_src.rstrip() + '\n\nfrom modules.hedef.plan_v2 import plan_v2_bp\n'

    bak_init = INIT_PATH + '.bak_pre_planv2_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(INIT_PATH, bak_init)
    print('INIT Yedek: ' + bak_init)

    with io.open(INIT_PATH, 'w', encoding='utf-8') as f:
        f.write(new_init)
    print('OK-INIT: plan_v2_bp expose edildi')


# === 2) app.py - blueprint kayit ===
APP_PATH = r'C:\cps_dev\app.py'
APP_MARKER = 'plan_v2_bp'

with io.open(APP_PATH, 'r', encoding='utf-8') as f:
    app_src = f.read()

if APP_MARKER in app_src:
    print('SKIP-APP: plan_v2_bp zaten register edilmis')
else:
    # Anchor: hedef_bp register satirinin BIRINCISI'ni bul
    OLD_REG = "from modules.hedef import hedef_bp"
    NEW_REG = "from modules.hedef import hedef_bp\nfrom modules.hedef import plan_v2_bp"

    if OLD_REG not in app_src:
        print('UYARI: hedef_bp import anchor bulunamadi - manuel ekle')
        sys.exit(1)

    app_new = app_src.replace(OLD_REG, NEW_REG, 1)

    # register_blueprint anchor
    REG_OLD = "app.register_blueprint(hedef_bp)"
    REG_NEW = "app.register_blueprint(hedef_bp)\napp.register_blueprint(plan_v2_bp)"

    if REG_OLD not in app_new:
        # Belki farkli format - 2. dene
        print('UYARI: register_blueprint(hedef_bp) anchor bulunamadi')
        print('Manuel ekle: app.register_blueprint(plan_v2_bp)')
        # Yine de import'u kaydet
        bak_app = APP_PATH + '.bak_pre_planv2_' + time.strftime('%Y%m%d_%H%M%S')
        shutil.copy2(APP_PATH, bak_app)
        print('APP Yedek: ' + bak_app)
        with io.open(APP_PATH, 'w', encoding='utf-8') as f:
            f.write(app_new)
        print('OK-APP-PARTIAL: import eklendi, register manuel yapilmali')
        sys.exit(0)

    app_new2 = app_new.replace(REG_OLD, REG_NEW, 1)

    bak_app = APP_PATH + '.bak_pre_planv2_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(APP_PATH, bak_app)
    print('APP Yedek: ' + bak_app)

    with io.open(APP_PATH, 'w', encoding='utf-8') as f:
        f.write(app_new2)
    print('OK-APP: plan_v2_bp import + register edildi')

print('TAMAM: ADIM 6 uygulandi')
print('Test: http://localhost:5057/hedef/v2/')