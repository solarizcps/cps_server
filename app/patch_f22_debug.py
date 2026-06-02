# F2.2 DEBUG: Header logging + contains match + fetch data log
import io, sys, shutil, time

JS_PATH = r'C:\cps_dev\static\js\hedef.js'
MARKER = '[F2.2 headers]'

with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: Debug zaten uygulanmis')
    sys.exit(0)

# 1) _f22SutunIndeksleri fonksiyonunu contains mantigiyla ezelim
OLD_FUNC = '''    /* Header text ile sutun indeksini bul */
    function _f22SutunIndeksleri(table) {
        var thead = table.querySelector("thead tr");
        if (!thead) return null;
        var ths = thead.querySelectorAll("th");
        var idx = { yapilan: -1, kalan: -1, yuzde: -1, emir: -1 };
        for (var i = 0; i < ths.length; i++) {
            var t = (ths[i].textContent || "").trim().toUpperCase();
            if (t === "YAPILAN") idx.yapilan = i;
            else if (t === "KALAN") idx.kalan = i;
            else if (t === "%") idx.yuzde = i;
            else if (t === "EMIR" || t === "EM\u0130R") idx.emir = i;
        }
        return idx;
    }'''

NEW_FUNC = '''    /* Header text ile sutun indeksini bul (DEBUG + contains) */
    function _f22Norm(s) {
        return (s || "")
            .toString()
            .toUpperCase()
            .replace(/\u0130/g, "I")
            .replace(/\u0131/g, "I")
            .replace(/\u00DC/g, "U").replace(/\u00FC/g, "U")
            .replace(/\u015E/g, "S").replace(/\u015F/g, "S")
            .replace(/\u00D6/g, "O").replace(/\u00F6/g, "O")
            .replace(/\u00C7/g, "C").replace(/\u00E7/g, "C")
            .replace(/\u011E/g, "G").replace(/\u011F/g, "G")
            .trim();
    }

    function _f22SutunIndeksleri(table) {
        var thead = table.querySelector("thead tr");
        if (!thead) return null;
        var ths = thead.querySelectorAll("th");
        var headerRaw = [];
        var headerNorm = [];
        for (var j = 0; j < ths.length; j++) {
            headerRaw.push((ths[j].textContent || "").trim());
            headerNorm.push(_f22Norm(ths[j].textContent));
        }
        try {
            console.log("[F2.2 headers]", headerRaw);
            console.log("[F2.2 headers norm]", headerNorm);
        } catch (e) {}

        var idx = { yapilan: -1, kalan: -1, yuzde: -1, emir: -1 };
        for (var i = 0; i < headerNorm.length; i++) {
            var t = headerNorm[i];
            if (idx.yapilan < 0 && t.indexOf("YAPIL") >= 0) idx.yapilan = i;
            if (idx.kalan < 0 && t.indexOf("KALAN") >= 0) idx.kalan = i;
            if (idx.yuzde < 0 && (t.indexOf("%") >= 0 || t.indexOf("YUZDE") >= 0)) idx.yuzde = i;
            if (idx.emir < 0 && t.indexOf("EMIR") >= 0) idx.emir = i;
        }
        try {
            console.log("[F2.2 index]", idx);
        } catch (e) {}
        return idx;
    }'''

if OLD_FUNC not in src:
    print('HATA: _f22SutunIndeksleri eski fonksiyon bulunamadi')
    sys.exit(1)

new_src = src.replace(OLD_FUNC, NEW_FUNC, 1)

# 2) fetch then(data) blogundan ONCE log ekle
OLD_THEN = '''        }).then(function (data) {
            if (!data || !data.ok || !data.darbogaz) return; /* sessiz fallback */'''

NEW_THEN = '''        }).then(function (data) {
            try { console.log("[F2.2 data]", data); } catch (e) {}
            try { console.log("[F2.2 emirler gonderilen]", emirler); } catch (e) {}
            if (!data || !data.ok || !data.darbogaz) return; /* sessiz fallback */'''

if OLD_THEN not in new_src:
    print('HATA: fetch then anchor bulunamadi')
    sys.exit(1)

new_src2 = new_src.replace(OLD_THEN, NEW_THEN, 1)

# 3) emirToTr ve emirler dump - calistir baslangici
OLD_RUN = '''        if (emirler.length === 0) return;
        if (emirler.length > 100) emirler = emirler.slice(0, 100);'''

NEW_RUN = '''        try {
            console.log("[F2.2 toplam tr]", rows.length, "emir bulundu", emirler.length);
            console.log("[F2.2 emirler]", emirler);
        } catch (e) {}
        if (emirler.length === 0) return;
        if (emirler.length > 100) emirler = emirler.slice(0, 100);'''

if OLD_RUN not in new_src2:
    print('HATA: calistir anchor bulunamadi')
    sys.exit(1)

new_src3 = new_src2.replace(OLD_RUN, NEW_RUN, 1)

bak = JS_PATH + '.bak_pre_f22_debug_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(JS_PATH, bak)
print('Yedek: ' + bak)

with io.open(JS_PATH, 'w', encoding='utf-8') as f:
    f.write(new_src3)

print('OK: F2.2 debug modu eklendi (' + str(len(new_src3) - len(src)) + ' byte)')
print('Test: Ctrl+F5 -> F12 Console -> [F2.2 ...] mesajlarini incele')