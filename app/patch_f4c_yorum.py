# F4c: Mini detayda yorum satiri (hibrit Korgun oncelikli mesaj)
import io, sys, shutil, time

JS_PATH = r'C:\cps_dev\static\js\hedef.js'
CSS_PATH = r'C:\cps_dev\static\css\hedef.css'
JS_MARKER = '_yorumSatir'
CSS_MARKER = '/* === FAZ 4.10 F4c YORUM ==='

# === 1) JS ===
with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    js_src = f.read()

if JS_MARKER in js_src:
    print('SKIP-JS: F4c zaten uygulanmis')
else:
    OLD_CALL = """        var html = '';
        // F1: DURUM satiri (darbogaz ozeti) - en uste
        html += _durumSatir(d);
        // F3: PARCALAR satiri - DURUM altina
        html += _parcalarSatir(d);"""

    NEW_CALL = """        var html = '';
        // F1: DURUM satiri (darbogaz ozeti) - en uste
        html += _durumSatir(d);
        // F4c: YORUM satiri - DURUM hemen altinda
        html += _yorumSatir(d);
        // F3: PARCALAR satiri
        html += _parcalarSatir(d);"""

    if OLD_CALL not in js_src:
        print('HATA: _miniHtml call anchor bulunamadi')
        sys.exit(1)

    OLD_HELPER_ANCHOR = """    function _parcalarSatir(d) {"""

    NEW_HELPER = """    function _yorumSatir(d) {
        if (!d) return '';
        var hedef = parseInt(d.hedef || 0);
        var yapilan = parseInt(d.yapilan_darbogaz || 0);

        // MAMUL Korgun oncelikli: numerik proses_kod MAX
        var mamul = 0;
        if (d.ana_prosesleri && d.ana_prosesleri.length) {
            var maxKod = -1;
            for (var i = 0; i < d.ana_prosesleri.length; i++) {
                var p = d.ana_prosesleri[i];
                var kod = parseInt(p.proses_kod);
                if (!isNaN(kod) && kod > maxKod) {
                    maxKod = kod;
                    mamul = parseInt(p.yapilan || 0);
                }
            }
        }

        var db = (d.darbogaz_kategori || '').toUpperCase();
        var dbLabel = db;
        if (db === 'GOVDE') dbLabel = 'G\\u00d6VDE';

        var mesaj = '';
        if (mamul > 0 && yapilan === 0) {
            mesaj = 'Kesim var ama devam yok \\u2014 ' + dbLabel + '\\u2019da t\\u0131kal\\u0131';
        } else if (yapilan > 0 && yapilan < hedef) {
            mesaj = '\\u00dcretim devam ediyor';
        } else if (yapilan > 0 && yapilan >= hedef && hedef > 0) {
            mesaj = '\\u00dcretim tamamland\\u0131';
        }
        if (!mesaj) return '';

        return '<span class="plan-detay-mini-line plan-detay-mini-yorum">' +
            '<span class="plan-detay-mini-arrow">&rarr;</span>' +
            '<span class="plan-detay-mini-yorum-text">' + mesaj + '</span>' +
            '</span>';
    }

    function _parcalarSatir(d) {"""

    if OLD_HELPER_ANCHOR not in js_src:
        print('HATA: _parcalarSatir anchor bulunamadi')
        sys.exit(1)

    js_new = js_src.replace(OLD_CALL, NEW_CALL, 1)
    js_new = js_new.replace(OLD_HELPER_ANCHOR, NEW_HELPER, 1)

    if js_new == js_src:
        print('HATA: JS replace yapilmadi')
        sys.exit(1)

    bak_js = JS_PATH + '.bak_pre_f4c_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(JS_PATH, bak_js)
    print('JS Yedek: ' + bak_js)

    with io.open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(js_new)
    print('OK-JS: F4c yorum satiri eklendi (' + str(len(js_new) - len(js_src)) + ' byte)')

# === 2) CSS ===
with io.open(CSS_PATH, 'r', encoding='utf-8') as f:
    css_src = f.read()

if CSS_MARKER in css_src:
    print('SKIP-CSS: F4c zaten uygulanmis')
else:
    CSS_ADD = '''

/* === FAZ 4.10 F4c YORUM === */
.plan-detay-mini-line.plan-detay-mini-yorum {
    font-size: 11px;
    color: #b91c1c;
    font-weight: 500;
    margin-bottom: 4px;
}
.plan-detay-mini-line.plan-detay-mini-yorum .plan-detay-mini-arrow {
    color: #b91c1c;
}
.plan-detay-mini-yorum-text {
    margin-left: 4px;
}
/* === /FAZ 4.10 F4c YORUM === */
'''

    bak_css = CSS_PATH + '.bak_pre_f4c_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(CSS_PATH, bak_css)
    print('CSS Yedek: ' + bak_css)

    with io.open(CSS_PATH, 'w', encoding='utf-8') as f:
        f.write(css_src + CSS_ADD)
    print('OK-CSS: F4c stili eklendi (' + str(len(CSS_ADD)) + ' byte)')

print('TAMAM: F4c uygulandi')