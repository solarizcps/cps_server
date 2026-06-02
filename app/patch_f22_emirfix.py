# F2.2 FIX v2: Emir_no bulma - 3 fallback + debug log
import io, sys, shutil, time

JS_PATH = r'C:\cps_dev\static\js\hedef.js'
MARKER = '[F2.2 TR]'

with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: F2.2 emirfix zaten uygulanmis')
    sys.exit(0)

OLD_FUNC = """    /* Bir TR icindeki emir_no'yu cikart */
    function _f22EmirNoBul(tr, emirIdx) {
        var v = tr.getAttribute("data-emir-no") || tr.getAttribute("data-emir");
        if (v) {
            var d = String(v).replace(/\\D/g, "");
            if (d) return d;
        }
        if (emirIdx >= 0) {
            var cells = tr.querySelectorAll("td");
            if (cells.length > emirIdx) {
                var t = (cells[emirIdx].textContent || "").replace(/\\D/g, "");
                if (t) return t;
            }
        }
        return null;
    }"""

NEW_FUNC = """    /* Bir TR icindeki emir_no'yu cikart - 3 fallback + debug */
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

        try {
            var preview = (tr.textContent || "").substring(0, 80).replace(/\\s+/g, " ").trim();
            console.log("[F2.2 TR]", preview);
            console.log("[F2.2 emir_no]", en);
        } catch (e) {}

        if (en && /^\\d+$/.test(en)) return en;
        return null;
    }"""

if OLD_FUNC not in src:
    print('HATA: anchor hala bulunamadi')
    print('---')
    print('Aranan ilk 200 karakter:')
    print(repr(OLD_FUNC[:200]))
    sys.exit(1)

new_src = src.replace(OLD_FUNC, NEW_FUNC, 1)

bak = JS_PATH + '.bak_pre_f22_emirfix_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(JS_PATH, bak)
print('Yedek: ' + bak)

with io.open(JS_PATH, 'w', encoding='utf-8') as f:
    f.write(new_src)

artis = len(new_src) - len(src)
print('OK: F2.2 emirfix uygulandi (' + str(artis) + ' byte)')
print('Test: Ctrl+F5 -> F12 Console -> [F2.2 TR] mesajlari')