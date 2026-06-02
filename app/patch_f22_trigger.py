# F2.2 TRIGGER FIX v2: Init zorla baslat + retry (triple-quote'suz)
import io, sys, shutil, time

JS_PATH = r'C:\cps_dev\static\js\hedef.js'
MARKER = '_f22ZorlaTetik'

with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: F2.2 trigger zaten uygulanmis')
    sys.exit(0)

ANCHOR_LOG = '    console.log("[CPS LOCAL] PLAN darbogaz F2.2 yuklendi");\n})();'

if ANCHOR_LOG not in src:
    print('HATA: anchor bulunamadi')
    sys.exit(1)

LINES = [
    '    /* F2.2 ZORLA TETIK: 6 kez 1 sn arayla dene, sonra durdur */',
    '    var _f22ZorlaTetik = 0;',
    '    function _f22ZorlaCalistir() {',
    '        try {',
    '            var pb = document.getElementById("planBody");',
    '            if (pb) {',
    '                var rows = pb.querySelectorAll("tr");',
    '                var dolu = 0;',
    '                for (var i = 0; i < rows.length; i++) {',
    '                    var tr = rows[i];',
    '                    if (tr.classList.contains("plan-detay-mini")) continue;',
    '                    if (tr.classList.contains("plan-detay-row")) continue;',
    '                    if ((tr.textContent || "").match(/E\\.\\d+/)) dolu++;',
    '                }',
    '                if (dolu > 0) {',
    '                    if (typeof _f22BaslatGozlem === "function") _f22BaslatGozlem();',
    '                    _f22Calistir();',
    '                    _f22ZorlaTetik = 99;',
    '                    return;',
    '                }',
    '            }',
    '        } catch (e) {}',
    '        _f22ZorlaTetik++;',
    '        if (_f22ZorlaTetik < 6) {',
    '            setTimeout(_f22ZorlaCalistir, 1000);',
    '        }',
    '    }',
    '    setTimeout(_f22ZorlaCalistir, 500);',
    '',
    '    console.log("[CPS LOCAL] PLAN darbogaz F2.2 yuklendi");',
    '})();',
]
NEW_BLOCK = '\n'.join(LINES)

new_src = src.replace(ANCHOR_LOG, NEW_BLOCK, 1)

if new_src == src:
    print('HATA: anchor eslenmedi')
    sys.exit(1)

bak = JS_PATH + '.bak_pre_f22_trigger_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(JS_PATH, bak)
print('Yedek: ' + bak)

with io.open(JS_PATH, 'w', encoding='utf-8') as f:
    f.write(new_src)

artis = len(new_src) - len(src)
print('OK: F2.2 zorla tetik eklendi (' + str(artis) + ' byte)')