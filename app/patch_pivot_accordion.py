import io, shutil, time, sys

JS_PATH = r'C:\cps_dev\static\js\plan_v2.js'
MARKER = '/* ACCORDION MODU */'

with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP')
    sys.exit(0)

OLD = """    window.planv2PivotToggle = function (rowId) {
        var detay = document.getElementById('detay-' + rowId);
        var icon = document.getElementById('icon-' + rowId);
        if (!detay) return;
        if (detay.style.display === 'none') {
            detay.style.display = '';
            if (icon) icon.textContent = '−';
        } else {
            detay.style.display = 'none';
            if (icon) icon.textContent = '+';
        }
    };"""

NEW = """    window.planv2PivotToggle = function (rowId) {
        /* ACCORDION MODU */
        var detay = document.getElementById('detay-' + rowId);
        var icon = document.getElementById('icon-' + rowId);
        if (!detay) return;
        var acilacak = (detay.style.display === 'none');
        var tumDetaylar = document.querySelectorAll('.planv2-pivot-detay');
        for (var i = 0; i < tumDetaylar.length; i++) {
            tumDetaylar[i].style.display = 'none';
        }
        var tumIkonlar = document.querySelectorAll('.planv2-expand-icon');
        for (var j = 0; j < tumIkonlar.length; j++) {
            tumIkonlar[j].textContent = '+';
        }
        if (acilacak) {
            detay.style.display = '';
            if (icon) icon.textContent = '−';
        }
    };"""

if OLD not in src:
    print('HATA: anchor yok')
    sys.exit(1)

shutil.copy2(JS_PATH, JS_PATH + '.bak_acc_' + time.strftime('%Y%m%d_%H%M%S'))
with io.open(JS_PATH, 'w', encoding='utf-8') as f:
    f.write(src.replace(OLD, NEW, 1))
print('OK: accordion eklendi')