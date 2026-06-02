# F2.2 MUTATION: planBody'ye satir eklendiginde otomatik tetikle
import io, sys, shutil, time

JS_PATH = r'C:\cps_dev\static\js\hedef.js'
MARKER = '_f22MutationGozlemci'

with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: F2.2 mutation zaten uygulanmis')
    sys.exit(0)

# Anchor: console.log("[CPS LOCAL] PLAN darbogaz F2.2 yuklendi"); ifadesinin ONCESINE ekle
ANCHOR = '    console.log("[CPS LOCAL] PLAN darbogaz F2.2 yuklendi");'

if ANCHOR not in src:
    print('HATA: anchor (yuklendi log) bulunamadi')
    sys.exit(1)

INSERT = '''    /* MUTATION: planBody'ye satir eklendiginde otomatik tetikle */
    var _f22MutationGozlemci = null;
    var _f22LastRunTs = 0;
    function _f22DebouncedCalistir() {
        var now = Date.now();
        // Son 800ms icinde calistirildiysa atla (debounce)
        if (now - _f22LastRunTs < 800) return;
        _f22LastRunTs = now;
        setTimeout(_f22Calistir, 50);
    }
    function _f22BaslatGozlem() {
        var planBody = document.getElementById("planBody");
        if (!planBody) return false;
        if (_f22MutationGozlemci) return true;
        _f22MutationGozlemci = new MutationObserver(function (muts) {
            for (var i = 0; i < muts.length; i++) {
                var m = muts[i];
                if (m.addedNodes && m.addedNodes.length > 0) {
                    /* Eklenen TR'ler arasinda data-emir-no veya E.XXXXX olan var mi? */
                    for (var j = 0; j < m.addedNodes.length; j++) {
                        var n = m.addedNodes[j];
                        if (n.nodeType !== 1) continue;
                        if (n.tagName !== "TR") continue;
                        if (n.classList.contains("plan-detay-mini")) continue;
                        if (n.classList.contains("plan-detay-row")) continue;
                        _f22DebouncedCalistir();
                        return;
                    }
                }
            }
        });
        _f22MutationGozlemci.observe(planBody, { childList: true, subtree: false });
        return true;
    }

    /* Sayfa yuklendigi anda planBody hazir mi? Hazirsa hemen calistir + gozlem baslat */
    function _f22Init() {
        if (_f22BaslatGozlem()) {
            /* Tablo zate