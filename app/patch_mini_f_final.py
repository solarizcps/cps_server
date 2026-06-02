# ADIM F: Alt emir numarasini (E.110649) detay satirindan gizle
import io, sys, shutil, time

JS_PATH = r'C:\cps_dev\static\js\hedef.js'
MARKER = '/* FAZ 4.7 MINI: emir numarasi gizli */'

with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: ADIM F zaten uygulanmis')
    sys.exit(0)

# emirEt'i bos string'e cevir - emir numarasi gosterilmeyecek
OLD = "        var emirEt = ap.emir_no ? ' <small style=\"color:#9ca3af;\">E.' + _esc(ap.emir_no) + '</small>' : '';"
NEW = "        var emirEt = ''; /* FAZ 4.7 MINI: emir numarasi gizli */"

if OLD not in src:
    print('HATA: emirEt satiri bulunamadi')
    sys.exit(1)

new_src = src.replace(OLD, NEW, 1)

bak = JS_PATH + '.bak_pre_mini_f_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(JS_PATH, bak)
print('Yedek: ' + bak)

with io.open(JS_PATH, 'w', encoding='utf-8') as f:
    f.write(new_src)

print('OK: ADIM F emir numarasi gizlendi')