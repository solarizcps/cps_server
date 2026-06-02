# F3: Mini detayda PARCALAR satiri (DURUM altina)
import io, sys, shutil, time

JS_PATH = r'C:\cps_dev\static\js\hedef.js'
CSS_PATH = r'C:\cps_dev\static\css\hedef.css'
JS_MARKER = '_parcalarSatir'
CSS_MARKER = '/* === FAZ 4.9 F3 PARCALAR ==='

# === 1) JS DEGISIKLIGI ===
with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    js_src = f.read()

if JS_MARKER in js_src:
    print('SKIP-JS: F3 zaten uygulanmis')
else:
    # 1a) _miniHtml icine cagri ekle (DURUM satirinin altina)
    OLD_CALL = """        var html = '';
        // F1: DURUM satiri (darbogaz ozeti) - en uste
        html += _durumSatir(d);
        html += _katSatir('ATKI', atki);"""

    NEW_CALL = """        var html = '';
        // F1: DURUM satiri (darbogaz ozeti) - en uste
        html += _durumSatir(d);
        // F3: PARCALAR satiri - DURUM altina
        html += _parcalarSatir(d);
        html += _katSatir('ATKI', atki);"""

    if OLD_CALL not in js_src:
        print('HATA: _miniHtml call anchor bulunamadi')
        sys.exit(1)

    # 1b) Yeni helper fonksiyonu - _katSatir fonksiyonundan ONCE ekle
    OLD_KATSATIR = """    function _katSatir(kat, ap) {"""

    NEW_HELPER = """    function _parcalarSatir(d) {
        var alt = d.alt_parcalar || [];
        if (!alt.length) return '';
        var atki = null;
        var govde = null;
        for (var i = 0; i < alt.length; i++) {
            var k = (alt[i].kategori || '').toLowerCase();
            if (k === 'atki' || k === 'atk\\u0131') {
                atki = alt[i];
            } else if (k === 'govde' || k === 'g\\u00f6vde') {
                govde = alt[i];
            }
        }
        var parts = [];
        if (atki && atki.emir_no) {
            parts.push('ATKI E.' + atki.emir_no);
        }
        if (govde && govde.emir_no) {
            parts.push('G\\u00d6VDE E.' + govde.emir_no);
        }
        if (!parts.length) return '';
        return '<span class="plan-detay-mini-line plan-detay-mini-parcalar">' +
            '<span class="plan-detay-mini-arrow">&rarr;</span>' +
            '<span class="plan-detay-mini-kat">PAR\\u00c7ALAR:</span>' +
            parts.join(' \\u00b7 ') +
            '</span>';
    }

    function _katSatir(kat, ap) {"""

    if OLD_KATSATIR not in js_src:
        print('HATA: _katSatir anchor bulunamadi')
        sys.exit(1)

    js_new = js_src.replace(OLD_CALL, NEW_CALL, 1)
    js_new = js_new.replace(OLD_KATSATIR, NEW_HELPER, 1)

    if js_new == js_src:
        print('HATA: JS replace yapilmadi')
        sys.exit(1)

    bak_js = JS_PATH + '.bak_pre_f3_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(JS_PATH, bak_js)
    print('JS Yedek: ' + bak_js)

    with io.open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(js_new)
    print('OK-JS: F3 helper + cagri eklendi (' + str(len(js_new) - len(js_src)) + ' byte)')

# === 2) CSS DEGISIKLIGI ===
with io.open(CSS_PATH, 'r', encoding='utf-8') as f:
    css_src = f.read()

if CSS_MARKER in css_src:
    print('SKIP-CSS: F3 zaten uygulanmis')
else:
    CSS_ADD = '''

/* === FAZ 4.9 F3 PARCALAR === */
.plan-detay-mini-line.plan-detay-mini-parcalar {
    font-size: 11px;
    color: #4b5563;
    margin-bottom: 4px;
}
.plan-detay-mini-line.plan-detay-mini-parcalar .plan-detay-mini-kat {
    color: #4b5563;
    font-weight: 600;
}
/* === /FAZ 4.9 F3 PARCALAR === */
'''

    bak_css = CSS_PATH + '.bak_pre_f3_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(CSS_PATH, bak_css)
    print('CSS Yedek: ' + bak_css)

    with io.open(CSS_PATH, 'w', encoding='utf-8') as f:
        f.write(css_src + CSS_ADD)
    print('OK-CSS: F3 stili eklendi (' + str(len(CSS_ADD)) + ' byte)')

print('TAMAM: F3 uygulandi')