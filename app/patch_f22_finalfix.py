# F2.2 FINAL FIX v2: anchor escape duzeltildi
import io, sys, shutil, time

JS_PATH = r'C:\cps_dev\static\js\hedef.js'
MARKER = 'data-f22-done'

with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: F2.2 finalfix zaten uygulanmis')
    sys.exit(0)

OLD_FUNC_BAS = """    /* PLAN tablosunu bul ve darbogaz cek */
    function _f22Calistir() {
        var planBody = document.getElementById("planBody");
        if (!planBody) return;"""

NEW_FUNC_BAS = """    /* PLAN tablosunu bul ve darbogaz cek (single-run garantili) */
    function _f22Calistir() {
        if (window._f22RanOnce) return;
        var planBody = document.getElementById("planBody");
        if (!planBody) return;"""

OLD_WRITE = """            for (var k in d) {
                if (!Object.prototype.hasOwnProperty.call(d, k)) continue;
                var tr2 = emirToTr[k];
                if (!tr2) continue;
                var v = d[k];
                if (!v) continue;
                if (v.yapilan_darbogaz === null || v.yapilan_darbogaz === undefined) continue;
                var cells = tr2.querySelectorAll("td");
                if (idx.yapilan >= 0 && cells.length > idx.yapilan) {
                    cells[idx.yapilan].textContent = _f22Fmt(v.yapilan_darbogaz);
                }
                if (idx.kalan >= 0 && cells.length > idx.kalan) {
                    cells[idx.kalan].textContent = _f22Fmt(v.kalan_darbogaz);
                }
                if (idx.yuzde >= 0 && cells.length > idx.yuzde) {
                    /* Yuzde hucresi pill icerebilir, varsa onun textContent'ini guncelle */
                    var yc = cells[idx.yuzde];
                    var pill = yc.querySelector(".pill, .badge, span");
                    if (pill) {
                        pill.textContent = _f22FmtPct(v.yuzde_darbogaz);
                    } else {
                        yc.textContent = _f22FmtPct(v.yuzde_darbogaz);
                    }
                }
            }"""

NEW_WRITE = """            window._f22RanOnce = true;
            for (var k in d) {
                if (!Object.prototype.hasOwnProperty.call(d, k)) continue;
                var tr2 = emirToTr[k];
                if (!tr2) continue;
                if (tr2.getAttribute("data-f22-done")) continue;
                var v = d[k];
                if (!v) continue;
                if (v.yapilan_darbogaz === null || v.yapilan_darbogaz === undefined) continue;
                var cells = tr2.querySelectorAll("td");
                if (!cells || cells.length < 8) continue;
                if (idx.yapilan >= 0 && cells.length > idx.yapilan) {
                    cells[idx.yapilan].textContent = _f22Fmt(v.yapilan_darbogaz);
                }
                if (idx.kalan >= 0 && cells.length > idx.kalan) {
                    cells[idx.kalan].textContent = _f22Fmt(v.kalan_darbogaz);
                }
                if (idx.yuzde >= 0 && cells.length > idx.yuzde) {
                    var yc = cells[idx.yuzde];
                    var pill = yc.querySelector(".pill, .badge, span");
                    if (pill) {
                        pill.textContent = _f22FmtPct(v.yuzde_darbogaz);
                    } else {
                        yc.textContent = _f22FmtPct(v.yuzde_darbogaz);
                    }
                }
                tr2.setAttribute("data-f22-done", "1");
                try { console.log("[F2.2 write]", k, "yapilan=" + v.yapilan_darbogaz, "kalan=" + v.kalan_darbogaz); } catch (e) {}
            }"""

OLD_GECIKME = """    setTimeout(_f22ZorlaCalistir, 500);"""
NEW_GECIKME = """    setTimeout(_f22ZorlaCalistir, 1500);"""

success = 0
new_src = src

if OLD_FUNC_BAS in new_src:
    new_src = new_src.replace(OLD_FUNC_BAS, NEW_FUNC_BAS, 1)
    success += 1
else:
    print('UYARI: _f22Calistir bas anchor bulunamadi')

if OLD_WRITE in new_src:
    new_src = new_src.replace(OLD_WRITE, NEW_WRITE, 1)
    success += 1
else:
    print('UYARI: yazma loop anchor bulunamadi')

if OLD_GECIKME in new_src:
    new_src = new_src.replace(OLD_GECIKME, NEW_GECIKME, 1)
    success += 1
else:
    print('UYARI: gecikme anchor bulunamadi')

if success < 3:
    print('HATA: tum anchor bulunamadi (' + str(success) + '/3)')
    sys.exit(1)

bak = JS_PATH + '.bak_pre_f22_finalfix_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(JS_PATH, bak)
print('Yedek: ' + bak)

with io.open(JS_PATH, 'w', encoding='utf-8') as f:
    f.write(new_src)

artis = len(new_src) - len(src)
print('OK: F2.2 finalfix uygulandi (' + str(artis) + ' byte)')
print('  - Single-run guard: window._f22RanOnce')
print('  - Per-row guard: data-f22-done')
print('  - Gecikme 500ms -> 1500ms')