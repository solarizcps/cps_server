# F2.2 EX FIX: Fallback 3 (5+ haneli) bozuk - ilk hucre ile sinirlandir
import io, sys, shutil, time

JS_PATH = r'C:\cps_dev\static\js\hedef.js'
MARKER = '/* F2.2 EX FIX */'

with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: ex fix zaten uygulanmis')
    sys.exit(0)

OLD_FUNC = """    /* Bir TR icindeki emir_no'yu cikart - 3 fallback + debug */
    function _f22EmirNoBul(tr, emirIdx) {
        var en = null;

        // Fallback 1: data-emir-no veya data-emir
        var v = tr.getAttribute("data-emir-no") || tr.getAttribute("data-emir");
        if (v) {
            var d = String(v).replace(/\\D/g, "");
            if (d && /^\\d+$/.test(d)) en = d;
        }

        // Fallback 2: TR icinde "E.XXXXX" pattern
        if (!en) {
            var txt = tr.textContent || "";
            var m = txt.match(/E\\.(\\d+)/);
            if (m && m[1]) en = m[1];
        }

        // Fallback 3: TR icinde 5+ basamakli sayi
        if (!en) {
            var txt2 = tr.textContent || "";
            var m2 = txt2.match(/\\b(\\d{5,})\\b/);
            if (m2 && m2[1]) en = m2[1];
        }

        if (en && /^\\d+$/.test(en)) return en;
        return null;
    }"""

NEW_FUNC = """    /* F2.2 EX FIX */
    /* Bir TR icindeki emir_no'yu cikart - SADECE ilk hucreden, EMIR sutunu */
    function _f22EmirNoBul(tr, emirIdx) {
        var en = null;

        // Fallback 1: data-emir-no veya data-emir
        var v = tr.getAttribute("data-emir-no") || tr.getAttribute("data-emir");
        if (v) {
            var d = String(v).replace(/\\D/g, "");
            if (d && /^\\d{4,8}$/.test(d)) en = d;
        }

        // Fallback 2: EMIR sutunundan "E.XXXXX" pattern (sadece o hucre)
        if (!en && emirIdx >= 0) {
            var cells = tr.querySelectorAll("td");
            if (cells.length > emirIdx) {
                var celTxt = cells[emirIdx].textContent || "";
                var m = celTxt.match(/E\\.?(\\d+)/);
                if (m && m[1]) en = m[1];
                else {
                    var d2 = celTxt.replace(/\\D/g, "");
                    if (d2 && /^\\d{4,8}$/.test(d2)) en = d2;
                }
            }
        }

        // Fallback 3: Tum TR icinde "E.XXXXX" pattern (sadece bir tane)
        if (!en) {
            var txt = tr.textContent || "";
            var m3 = txt.match(/E\\.?(\\d{4,8})/);
            if (m3 && m3[1]) en = m3[1];
        }

        // Sadece 4-8 hane kabul (emir no genelde 6 hane)
        if (en && /^\\d{4,8}$/.test(en)) return en;
        return null;
    }"""

if OLD_FUNC not in src:
    print('HATA: anchor bulunamadi')
    sys.exit(1)

new_src = src.replace(OLD_FUNC, NEW_FUNC, 1)

bak = JS_PATH + '.bak_pre_exfix_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(JS_PATH, bak)
print('Yedek: ' + bak)

with io.open(JS_PATH, 'w', encoding='utf-8') as f:
    f.write(new_src)

print('OK: F2.2 ex fix uygulandi (' + str(len(new_src) - len(src)) + ' byte)')