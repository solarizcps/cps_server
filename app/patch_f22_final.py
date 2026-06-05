# F2.2 FINAL: Dedupe + loading guard + bos koruma + debug log temizle
import io, sys, shutil, time

JS_PATH = r'C:\cps_dev\static\js\hedef.js'
MARKER_DONE = '_f22Loading'

with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER_DONE in src:
    print('SKIP: F2.2 final zaten uygulanmis')
    sys.exit(0)

# === DEGISIKLIK 1: Debug loglarini KALDIR ===
DBG_REPLACES = [
    # _f22EmirNoBul icindeki [F2.2 TR] ve [F2.2 emir_no] loglari
    (
        '''        try {
            var preview = (tr.textContent || "").substring(0, 80).replace(/\\s+/g, " ").trim();
            console.log("[F2.2 TR]", preview);
            console.log("[F2.2 emir_no]", en);
        } catch (e) {}

        if (en && /^\\d+$/.test(en)) return en;''',
        '''        if (en && /^\\d+$/.test(en)) return en;'''
    ),
    # _f22SutunIndeksleri icindeki [F2.2 headers] loglari
    (
        '''        try {
            console.log("[F2.2 headers]", headerRaw);
            console.log("[F2.2 headers norm]", headerNorm);
        } catch (e) {}

        var idx = { yapilan: -1, kalan: -1, yuzde: -1, emir: -1 };''',
        '''        var idx = { yapilan: -1, kalan: -1, yuzde: -1, emir: -1 };'''
    ),
    # _f22SutunIndeksleri icindeki [F2.2 index] log
    (
        '''        try {
            console.log("[F2.2 index]", idx);
        } catch (e) {}
        return idx;
    }''',
        '''        return idx;
    }'''
    ),
    # _f22Calistir icindeki [F2.2 toplam tr] ve [F2.2 emirler] loglari
    (
        '''        try {
            console.log("[F2.2 toplam tr]", rows.length, "emir bulundu", emirler.length);
            console.log("[F2.2 emirler]", emirler);
        } catch (e) {}
        if (emirler.length === 0) return;
        if (emirler.length > 100) emirler = emirler.slice(0, 100);''',
        '''        // Dedupe
        emirler = Array.from(new Set(emirler));
        if (!emirler.length) return;
        if (emirler.length > 100) emirler = emirler.slice(0, 100);'''
    ),
    # fetch then icindeki [F2.2 data] loglari
    (
        '''        }).then(function (data) {
            try { console.log("[F2.2 data]", data); } catch (e) {}
            try { console.log("[F2.2 emirler gonderilen]", emirler); } catch (e) {}
            if (!data || !data.ok || !data.darbogaz) return;''',
        '''        }).then(function (data) {
            if (!data || !data.ok || !data.darbogaz) return;'''
    ),
]

new_src = src
removed_count = 0
for old, new in DBG_REPLACES:
    if old in new_src:
        new_src = new_src.replace(old, new, 1)
        removed_count += 1

# === DEGISIKLIK 2: Loading guard ekle ===
# Anchor: 'var url = "/hedef/plan-darbogaz?...'
GUARD_OLD = '''        var url = "/hedef/plan-darbogaz?emirler=" + encodeURIComponent(emirler.join(","));
        fetch(url, {
            credentials: "same-origin",
            headers: { "Accept": "application/json" }
        }).then(function (r) {'''

GUARD_NEW = '''        // Loading guard - cift fetch engelle
        if (window._f22Loading) return;
        window._f22Loading = true;

        var url = "/hedef/plan-darbogaz?emirler=" + encodeURIComponent(emirler.join(","));
        fetch(url, {
            credentials: "same-origin",
            headers: { "Accept": "application/json" }
        }).then(function (r) {'''

if GUARD_OLD in new_src:
    new_src = new_src.replace(GUARD_OLD, GUARD_NEW, 1)

# === DEGISIKLIK 3: catch sonrasina .finally ekle ===
FINALLY_OLD = '''        }).catch(function (err) {
            /* Sessiz fallback - eski degerler kalir */
            try { console.warn("[F2.2] darbogaz fetch hata:", err); } catch (e) {}
        });
    }'''

FINALLY_NEW = '''        }).catch(function (err) {
            /* Sessiz fallback - eski degerler kalir */
        }).finally(function () {
            window._f22Loading = false;
        });
    }'''

if FINALLY_OLD in new_src:
    new_src = new_src.replace(FINALLY_OLD, FINALLY_NEW, 1)

if new_src == src:
    print('HATA: hicbir degisiklik yapilamadi')
    sys.exit(1)

bak = JS_PATH + '.bak_pre_f22_final_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(JS_PATH, bak)
print('Yedek: ' + bak)

with io.open(JS_PATH, 'w', encoding='utf-8') as f:
    f.write(new_src)

artis = len(new_src) - len(src)
print('OK: F2.2 final uygulandi (' + str(artis) + ' byte)')
print('  Debug log kaldirildi: ' + str(removed_count) + ' yer')
print('  Loading guard + dedupe + bos koruma eklendi')