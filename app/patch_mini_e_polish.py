# ADIM E: Mini detay polish - mesaj sadeleştir, separator, vurgu, hiyerarşi
import io, sys, shutil, time

# 1) JS değişiklikleri (V4 mini IIFE içinde)
JS_PATH = r'C:\cps_dev\static\js\hedef.js'
CSS_PATH = r'C:\cps_dev\static\css\hedef.css'

JS_REPLACES = [
    # Separator: ' / ' → ' · ' (orta nokta)
    # ATKI/GOVDE listesinde
    (
        "        return parts.join(' / ');\n    }\n\n    function _katSatir",
        "        return parts.join(' \u00b7 ');\n    }\n\n    function _katSatir",
    ),
    # ANA listesinde
    (
        "            parts.join(' / ') +",
        "            parts.join(' \u00b7 ') +",
    ),
    # Mesaj 1: alt parca emir_no boş ise (varsayılan)
    (
        "                '<span class=\"plan-detay-mini-mesaj\">parca emri yok</span>' +",
        "                '<span class=\"plan-detay-mini-mesaj\">parca yok</span>' +",
    ),
    # Mesaj 2: prosesler boş + mesaj yoksa default
    (
        "            var mesaj = ap.mesaj || 'henuz sablon uygulanmadi';\n",
        "            var mesaj = (ap.mesaj && ap.mesaj.trim()) ? 'sablon yok' : 'sablon yok';\n",
    ),
    # Mesaj 3: ANA boş ise
    (
        "                '<span class=\"plan-detay-mini-mesaj\">henuz uretim yok</span>' +",
        "                '<span class=\"plan-detay-mini-mesaj\">uretim yok</span>' +",
    ),
    # ANA satırına vurgu (ilk proses öncesi)
    # Mevcut: parts.push(_esc(p.proses_adi) + ' ' + _fmt(p.yapilan));
    # Bu döngü _anaSatir içinde - ilk öğeye işaret koy
    (
        "    function _anaSatir(d) {\n        var prs = d.ana_prosesleri || [];\n        if (prs.length === 0) {",
        "    function _anaSatir(d) {\n        var prs = d.ana_prosesleri || [];\n        var ANA_VURGU = '\\ud83d\\udd38 ';\n        if (prs.length === 0) {",
    ),
    (
        "        var parts = [];\n        for (var i = 0; i < prs.length; i++) {\n            var p = prs[i];\n            parts.push(_esc(p.proses_adi) + ' ' + _fmt(p.yapilan));\n        }\n        return '<span class=\"plan-detay-mini-line\">' +\n            '<span class=\"plan-detay-mini-arrow\">&rarr;</span>' +\n            '<span class=\"plan-detay-mini-kat\">ANA:</span>' +\n            parts.join(' \u00b7 ') +",
        "        var parts = [];\n        for (var i = 0; i < prs.length; i++) {\n            var p = prs[i];\n            var pre = (i === 0) ? ANA_VURGU : '';\n            parts.push(pre + _esc(p.proses_adi) + ' ' + _fmt(p.yapilan));\n        }\n        return '<span class=\"plan-detay-mini-line plan-detay-mini-ana\">' +\n            '<span class=\"plan-detay-mini-arrow\">&rarr;</span>' +\n            '<span class=\"plan-detay-mini-kat\">ANA:</span>' +\n            parts.join(' \u00b7 ') +",
    ),
]

with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    js_src = f.read()

# Idempotent kontrol
if 'plan-detay-mini-ana' in js_src:
    print('SKIP-JS: ADIM E zaten uygulanmis (JS)')
else:
    js_new = js_src
    success = 0
    fail = []
    for old, new in JS_REPLACES:
        if old in js_new:
            js_new = js_new.replace(old, new, 1)
            success += 1
        else:
            fail.append(old[:60].replace('\n', '\\n'))

    if fail:
        print('UYARI: bazi JS replace edilmedi:')
        for fa in fail:
            print('  - ' + fa)
        print('Devam edilmeyecek, JS bozulmasin.')
        sys.exit(1)

    bak_js = JS_PATH + '.bak_pre_mini_e_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(JS_PATH, bak_js)
    print('JS Yedek: ' + bak_js)

    with io.open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(js_new)
    print('OK-JS: ' + str(success) + ' replace yapildi')


# 2) CSS - hiyerarsi ve vurgu
CSS_MARKER = '/* === FAZ 4.7 MINI POLISH ==='
CSS_ADD = '''

/* === FAZ 4.7 MINI POLISH === */
/* ATKI/GOVDE secondary (gri, hafif) */
.plan-detay-mini-line { color: #6b7280; }
.plan-detay-mini-line .plan-detay-mini-kat {
  color: #6b7280;
  font-weight: 500;
}
/* ANA primary (koyu, kalin) */
.plan-detay-mini-line.plan-detay-mini-ana { color: #111827; font-weight: 500; }
.plan-detay-mini-line.plan-detay-mini-ana .plan-detay-mini-kat {
  color: #111827;
  font-weight: 700;
}
/* === /FAZ 4.7 MINI POLISH === */
'''

with io.open(CSS_PATH, 'r', encoding='utf-8') as f:
    css_src = f.read()

if CSS_MARKER in css_src:
    print('SKIP-CSS: ADIM E zaten uygulanmis (CSS)')
else:
    bak_css = CSS_PATH + '.bak_pre_mini_e_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(CSS_PATH, bak_css)
    print('CSS Yedek: ' + bak_css)

    with io.open(CSS_PATH, 'w', encoding='utf-8') as f:
        f.write(css_src + CSS_ADD)
    print('OK-CSS: polish CSS eklendi (' + str(len(CSS_ADD)) + ' byte)')

print('TAMAM: ADIM E uygulandi')