# F1: Mini detayda DURUM satiri (darbogaz ozeti)
# - hedef.js: _durumSatir() helper + _miniHtml() icine cagri
# - hedef.css: DURUM satir stili (kalin siyah, kirmizi darbogaz vurgusu)
import io, sys, shutil, time

JS_PATH = r'C:\cps_dev\static\js\hedef.js'
CSS_PATH = r'C:\cps_dev\static\css\hedef.css'
JS_MARKER = 'plan-detay-mini-durum'  # idempotent kontrol icin
CSS_MARKER = '/* === FAZ 4.7 F1 DURUM SATIR ==='

# === 1) JS DEGISIKLIGI ===
with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    js_src = f.read()

if JS_MARKER in js_src:
    print('SKIP-JS: F1 zaten uygulanmis')
else:
    # Anchor: _miniHtml fonksiyonun basi
    OLD_MINIHTML = """    function _miniHtml(d) {
        var alt = d.alt_parcalar || [];
        var atki = null, govde = null;
        for (var i = 0; i < alt.length; i++) {
            var k = (alt[i].kategori || '').toLowerCase();
            if (k === 'atki' || k === 'atk\\u0131') atki = alt[i];
            else if (k === 'govde' || k === 'g\\u00f6vde') govde = alt[i];
        }
        var html = '';
        html += _katSatir('ATKI', atki);
        html += _katSatir('GOVDE', govde);
        html += _anaSatir(d);
        return html;
    }"""

    NEW_MINIHTML = """    function _durumSatir(d) {
        if (d.yapilan_darbogaz === undefined || d.yapilan_darbogaz === null) {
            return '';
        }
        var yp = Number(d.yapilan_darbogaz || 0);
        var hf = Number(d.hedef || 0);
        var yz = (d.yuzde_darbogaz !== undefined && d.yuzde_darbogaz !== null)
            ? Number(d.yuzde_darbogaz) : 0;
        var kat = d.darbogaz_kategori || '';
        var darbogazHtml = '';
        if (kat) {
            darbogazHtml = ' <span class="plan-detay-mini-darbogaz">' +
                '\\u00b7 DARBO\\u011eAZ: ' + _esc(kat) + '</span>';
        }
        return '<span class="plan-detay-mini-line plan-detay-mini-durum">' +
            '<span class="plan-detay-mini-arrow">&rarr;</span>' +
            '<span class="plan-detay-mini-kat">DURUM:</span>' +
            _fmt(yp) + ' / ' + _fmt(hf) + ' (%' + _fmt(yz) + ')' +
            darbogazHtml +
            '</span>';
    }

    function _miniHtml(d) {
        var alt = d.alt_parcalar || [];
        var atki = null, govde = null;
        for (var i = 0; i < alt.length; i++) {
            var k = (alt[i].kategori || '').toLowerCase();
            if (k === 'atki' || k === 'atk\\u0131') atki = alt[i];
            else if (k === 'govde' || k === 'g\\u00f6vde') govde = alt[i];
        }
        var html = '';
        // F1: DURUM satiri (darbogaz ozeti) - en uste
        html += _durumSatir(d);
        html += _katSatir('ATKI', atki);
        html += _katSatir('GOVDE', govde);
        html += _anaSatir(d);
        return html;
    }"""

    if OLD_MINIHTML not in js_src:
        print('HATA: _miniHtml anchor bulunamadi')
        print('Belki JS daha once degistirildi - manuel kontrol gerek')
        sys.exit(1)

    js_new = js_src.replace(OLD_MINIHTML, NEW_MINIHTML, 1)

    bak_js = JS_PATH + '.bak_pre_f1_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(JS_PATH, bak_js)
    print('JS Yedek: ' + bak_js)

    with io.open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(js_new)
    print('OK-JS: _durumSatir eklendi (' + str(len(js_new) - len(js_src)) + ' byte)')

# === 2) CSS DEGISIKLIGI ===
with io.open(CSS_PATH, 'r', encoding='utf-8') as f:
    css_src = f.read()

if CSS_MARKER in css_src:
    print('SKIP-CSS: F1 zaten uygulanmis')
else:
    CSS_ADD = '''

/* === FAZ 4.7 F1 DURUM SATIR === */
/* DURUM satiri - kalin siyah, dikkat cekici */
.plan-detay-mini-line.plan-detay-mini-durum {
  color: #111827 !important;
  font-weight: 600 !important;
  margin-bottom: 4px;
  display: block;
}
.plan-detay-mini-line.plan-detay-mini-durum .plan-detay-mini-kat {
  color: #111827 !important;
  font-weight: 700 !important;
}
.plan-detay-mini-line.plan-detay-mini-durum .plan-detay-mini-arrow {
  color: #111827;
}
/* DARBOGAZ vurgusu - kirmizi, hangi parca takildi */
.plan-detay-mini-darbogaz {
  color: #dc2626;
  font-weight: 600;
  margin-left: 4px;
}
/* === /FAZ 4.7 F1 DURUM SATIR === */
'''

    bak_css = CSS_PATH + '.bak_pre_f1_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(CSS_PATH, bak_css)
    print('CSS Yedek: ' + bak_css)

    with io.open(CSS_PATH, 'w', encoding='utf-8') as f:
        f.write(css_src + CSS_ADD)
    print('OK-CSS: DURUM satir stili eklendi (' + str(len(CSS_ADD)) + ' byte)')

print('TAMAM: F1 uygulandi')