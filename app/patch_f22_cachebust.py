# F2.2 CACHE BUST: fetch URL'e timestamp ekle (eski cache kullanma)
import io, sys, shutil, time

JS_PATH = r'C:\cps_dev\static\js\hedef.js'
MARKER = '_f22cb='

with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: cache bust zaten uygulanmis')
    sys.exit(0)

OLD = 'var url = "/hedef/plan-darbogaz?emirler=" + encodeURIComponent(emirler.join(","));'
NEW = 'var url = "/hedef/plan-darbogaz?emirler=" + encodeURIComponent(emirler.join(",")) + "&_f22cb=" + Date.now();'

if OLD not in src:
    print('HATA: URL anchor bulunamadi')
    sys.exit(1)

new_src = src.replace(OLD, NEW, 1)

bak = JS_PATH + '.bak_pre_cb_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(JS_PATH, bak)
print('Yedek: ' + bak)

with io.open(JS_PATH, 'w', encoding='utf-8') as f:
    f.write(new_src)

print('OK: cache bust eklendi (' + str(len(new_src) - len(src)) + ' byte)')