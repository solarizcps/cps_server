import io, sys, shutil, time

JS_PATH = r'C:\cps_dev\static\js\hedef.js'
MARKER = "/* ANA->MAMUL etiket */"

with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: ADIM 3 zaten uygulanmis')
    sys.exit(0)

OLD1 = """                '<span class=\"plan-detay-mini-kat\">ANA:</span>' +
                '<span class=\"plan-detay-mini-mesaj\">uretim yok</span>' +"""
NEW1 = """                '<span class=\"plan-detay-mini-kat\">MAMUL:</span>' + /* ANA->MAMUL etiket */
                '<span class=\"plan-detay-mini-mesaj\">uretim yok</span>' +"""

OLD2 = """        return '<span class=\"plan-detay-mini-line plan-detay-mini-ana\">' +
            '<span class=\"plan-detay-mini-arrow\">&rarr;</span>' +
            '<span class=\"plan-detay-mini-kat\">ANA:</span>' +
            parts.join(' \u00b7 ') +"""
NEW2 = """        return '<span class=\"plan-detay-mini-line plan-detay-mini-ana\">' +
            '<span class=\"plan-detay-mini-arrow\">&rarr;</span>' +
            '<span class=\"plan-detay-mini-kat\">MAMUL:</span>' +
            parts.join(' \u00b7 ') +"""

success = 0
new_src = src

if OLD1 in new_src:
    new_src = new_src.replace(OLD1, NEW1, 1)
    success += 1
else:
    print('UYARI: OLD1 (uretim yok) bulunamadi')

if OLD2 in new_src:
    new_src = new_src.replace(OLD2, NEW2, 1)
    success += 1
else:
    print('UYARI: OLD2 (parts.join ANA:) bulunamadi')

if success == 0:
    print('HATA: hicbir replace yapilamadi')
    sys.exit(1)

bak = JS_PATH + '.bak_pre_mamul_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(JS_PATH, bak)
print('Yedek: ' + bak)

with io.open(JS_PATH, 'w', encoding='utf-8') as f:
    f.write(new_src)

print('OK: ' + str(success) + ' yer degistirildi (ANA -> MAMUL)')