/* ================================================================
   CPS DEV - Hedef Operasyon KPI Bandi (FAZ 6.3)
   ----------------------------------------------------------------
   Bagimsiz IIFE - mevcut hedef.js'e dokunmaz.
   
   Veri kaynagi: GET /hedef/operasyon-ozet
   Render hedef: <div id="kpi-band-faz63">
   Refresh:      30 saniye
   ================================================================ */
(function() {
    "use strict";

    // Idempotent guard
    if (window.__faz63_operasyon_kpi) return;
    window.__faz63_operasyon_kpi = true;

    // === KONFIGURASYON ===
    var CFG = {
        endpoint: '/hedef/operasyon-ozet',
        refreshMs: 30000,         // 30 saniye
        targetId: 'kpi-band-faz63',
        timeoutMs: 8000           // 8 saniye fetch timeout
    };

    var state = {
        loading: false,
        lastFetch: 0,
        lastData: null,
        timerId: null,
        consecutiveErrors: 0
    };

    // === HELPERLAR ===
    function fmtNum(n) {
        if (n === null || n === undefined || isNaN(n)) return '0';
        n = Number(n);
        if (n >= 1000) return n.toLocaleString('tr-TR');
        return String(Math.round(n));
    }

    function escHtml(s) {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // === RENK KOSULLARI ===
    function renkBekleyen(n) {
        if (n > 15) return { color: '#c62828', bg: '#ffebee', etiket: 'YUKSEK' };
        if (n > 5)  return { color: '#ef6c00', bg: '#fff3e0', etiket: 'ARTIYOR' };
        return { color: '#1a1a1a', bg: 'transparent', etiket: 'kayit' };
    }

    function renkAktifPersonel(n) {
        if (n === 0) return { color: '#c62828', bg: '#ffebee', etiket: 'BOS' };
        if (n < 2)   return { color: '#ef6c00', bg: '#fff3e0', etiket: 'AZ' };
        return { color: '#1a1a1a', bg: 'transparent', etiket: 'kisi' };
    }

    function renkKritik(n) {
        if (n > 0) return { color: '#c62828', bg: '#ffebee', etiket: 'KRITIK!' };
        return { color: '#2e7d32', bg: '#e8f5e9', etiket: 'IYI' };
    }

    // === KART HTML ===
    function kartHtml(baslik, sayi, etiket, renk) {
        var bg = renk && renk.bg ? renk.bg : 'transparent';
        var color = renk && renk.color ? renk.color : '#1a1a1a';
        var textColor = renk && renk.color !== '#1a1a1a' ? renk.color : '#888';
        return ''
            + '<div class="faz63-kpi-card" style="'
            +   'flex: 1 1 0; min-width: 130px; padding: 10px 14px; '
            +   'background: ' + bg + '; '
            +   'border: 1px solid #e8e8e8; border-radius: 6px; '
            +   'box-shadow: 0 1px 2px rgba(0,0,0,.03);'
            + '">'
            +   '<div style="font-size: 10.5px; color: #888; font-weight: 600; '
            +     'text-transform: uppercase; letter-spacing: .6px; margin-bottom: 4px;">'
            +     escHtml(baslik)
            +   '</div>'
            +   '<div style="font-size: 26px; font-weight: 700; line-height: 1.1; '
            +     'color: ' + color + ';">' + escHtml(sayi) + '</div>'
            +   '<div style="font-size: 10px; color: ' + textColor + '; '
            +     'margin-top: 2px; font-weight: 500;">' + escHtml(etiket) + '</div>'
            + '</div>';
    }

    // === RENDER ===
    function render(data) {
        var target = document.getElementById(CFG.targetId);
        if (!target) return;

        if (!data || !data.kpi) {
            target.innerHTML = '';
            return;
        }

        var k = data.kpi;
        var rB = renkBekleyen(Number(k.bekleyen_onay) || 0);
        var rA = renkAktifPersonel(Number(k.aktif_personel) || 0);
        var rK = renkKritik(Number(k.kritik_darbogaz) || 0);

        var html = ''
            + '<div class="faz63-kpi-band" data-faz63="kpi-band" style="'
            +   'display: flex; gap: 8px; margin: 12px 0 16px 0; '
            +   'flex-wrap: nowrap; overflow-x: auto;'
            + '">'
            + kartHtml('Acik Is', fmtNum(k.acik_is), 'aktif emir', null)
            + kartHtml('Bekleyen Onay', fmtNum(k.bekleyen_onay), rB.etiket, rB)
            + kartHtml('Bugun Uretim', fmtNum(k.bugun_uretim), 'adet', null)
            + kartHtml('Aktif Personel', fmtNum(k.aktif_personel), rA.etiket, rA)
            + kartHtml('Kritik Darbogaz', fmtNum(k.kritik_darbogaz), rK.etiket, rK)
            + '</div>';

        target.innerHTML = html;
        state.lastData = data;
    }

    function renderHata() {
        // Hatada ekrani BOZMA - sadece sessiz duruyor
        // Eger hic veri yoksa kucuk bir "yukleme bekleniyor" mesaji
        var target = document.getElementById(CFG.targetId);
        if (target && !state.lastData) {
            target.innerHTML = ''
                + '<div style="margin: 8px 0; padding: 8px 12px; '
                +   'background: #fafafa; border: 1px dashed #ddd; '
                +   'border-radius: 6px; color: #999; font-size: 11.5px;">'
                +   'KPI bandi yukleniyor...'
                + '</div>';
        }
        // Eger lastData var ise, ekranda eski deger duruyor - dokunma
    }

    // === FETCH ===
    function fetchKpi() {
        if (state.loading) return;
        state.loading = true;

        // Timeout icin AbortController (modern browser)
        var ctrl = null;
        var timeoutId = null;
        try {
            if (window.AbortController) {
                ctrl = new AbortController();
                timeoutId = setTimeout(function() { ctrl.abort(); }, CFG.timeoutMs);
            }
        } catch (e) {}

        var fetchOpts = { credentials: 'same-origin' };
        if (ctrl) fetchOpts.signal = ctrl.signal;

        fetch(CFG.endpoint, fetchOpts)
            .then(function(r) {
                if (timeoutId) clearTimeout(timeoutId);
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function(data) {
                state.consecutiveErrors = 0;
                state.lastFetch = Date.now();
                render(data);
            })
            .catch(function(err) {
                state.consecutiveErrors++;
                // Sessiz hata - sadece ilk hata icin minimal log
                if (state.consecutiveErrors === 1) {
                    try { console.warn('[FAZ 6.3] KPI yuklenemedi:', err.message || err); } catch (e) {}
                }
                renderHata();
            })
            .finally(function() {
                state.loading = false;
            });
    }

    // === AUTO REFRESH ===
    function startAutoRefresh() {
        if (state.timerId) return;
        state.timerId = setInterval(fetchKpi, CFG.refreshMs);
    }

    function stopAutoRefresh() {
        if (state.timerId) {
            clearInterval(state.timerId);
            state.timerId = null;
        }
    }

    // === BASLAT ===
    function init() {
        var target = document.getElementById(CFG.targetId);
        if (!target) {
            // Hedef div yok - sessiz cik
            return;
        }
        // Ilk fetch
        fetchKpi();
        // Auto-refresh basla
        startAutoRefresh();

        // Sayfa gizli iken refresh yapma (pil tasarrufu)
        if (typeof document.hidden !== 'undefined') {
            document.addEventListener('visibilitychange', function() {
                if (document.hidden) {
                    stopAutoRefresh();
                } else {
                    fetchKpi();           // Geri donunce hemen yenile
                    startAutoRefresh();
                }
            });
        }
    }

    // DOM hazir olunca baslat
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Diagnostik
    try { console.info('[FAZ 6.3] Hedef Operasyon KPI bandi aktif (refresh:', CFG.refreshMs/1000, 'sn)'); } catch (e) {}
})();
