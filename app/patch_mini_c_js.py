# ADIM C: V4 mini detay panel JS (idempotent, hedef.js sonuna eklenir)
import io, sys, shutil, time

PATH = r'C:\cps_dev\static\js\hedef.js'
MARKER = '[CPS LOCAL] PLAN detay v4 mini yuklendi'

with io.open(PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: ADIM C zaten uygulanmis')
    sys.exit(0)

JS = r'''

/* ============================================================
   FAZ 4.7 MINI DETAY (V4)
   - V3 buyuk panel inactive
   - Satira tiklayinca tek <tr class="plan-detay-mini">
   - 3 satir text: ATKI / GOVDE / ANA
   ============================================================ */
(function () {
    if (window._planDetayV4Yuklendi) return;
    window._planDetayV4Yuklendi = true;

    var DETAY_TR_CLASS = 'plan-detay-mini';
    var OLD_V3_CLASS = 'plan-detay-row';

    function _esc(s) {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function _fmt(n) {
        if (n === null || n === undefined || n === '') return '0';
        var x = Number(n);
        if (!isFinite(x)) return '0';
        return Math.round(x).toLocaleString('tr-TR');
    }

    function _kapatTumDetay() {
        var rows = document.querySelectorAll(
            '#planBody tr.' + DETAY_TR_CLASS + ', #planBody tr.' + OLD_V3_CLASS
        );
        for (var i = 0; i < rows.length; i++) rows[i].remove();
    }

    function _kolonSayisi() {
        var thead = document.querySelector('table thead tr');
        if (!thead) return 11;
        var ths = thead.querySelectorAll('th');
        return ths.length || 11;
    }

    function _prosesListesi(prosesler) {
        if (!prosesler || prosesler.length === 0) return '';
        var parts = [];
        for (var i = 0; i < prosesler.length; i++) {
            var p = prosesler[i];
            parts.push(_esc(p.proses_adi) + ' ' + _fmt(p.yapilan));
        }
        return parts.join(' / ');
    }

    function _katSatir(kat, ap) {
        var ad = _esc((kat || '').toUpperCase());
        if (!ap) {
            return '<span class="plan-detay-mini-line">' +
                '<span class="plan-detay-mini-arrow">&rarr;</span>' +
                '<span class="plan-detay-mini-kat">' + ad + ':</span>' +
                '<span class="plan-detay-mini-mesaj">parca emri yok</span>' +
                '</span>';
        }
        var prs = ap.prosesler || [];
        var emirEt = ap.emir_no ? ' <small style="color:#9ca3af;">E.' + _esc(ap.emir_no) + '</small>' : '';
        if (prs.length === 0) {
            var mesaj = ap.mesaj || 'henuz sablon uygulanmadi';
            return '<span class="plan-detay-mini-line">' +
                '<span class="plan-detay-mini-arrow">&rarr;</span>' +
                '<span class="plan-detay-mini-kat">' + ad + ':</span>' +
                '<span class="plan-detay-mini-mesaj">' + _esc(mesaj) + '</span>' +
                emirEt +
                '</span>';
        }
        return '<span class="plan-detay-mini-line">' +
            '<span class="plan-detay-mini-arrow">&rarr;</span>' +
            '<span class="plan-detay-mini-kat">' + ad + ':</span>' +
            _prosesListesi(prs) +
            emirEt +
            '</span>';
    }

    function _anaSatir(d) {
        var prs = d.ana_prosesleri || [];
        if (prs.length === 0) {
            return '<span class="plan-detay-mini-line">' +
                '<span class="plan-detay-mini-arrow">&rarr;</span>' +
                '<span class="plan-detay-mini-kat">ANA:</span>' +
                '<span class="plan-detay-mini-mesaj">henuz uretim yok</span>' +
                '</span>';
        }
        var parts = [];
        for (var i = 0; i < prs.length; i++) {
            var p = prs[i];
            parts.push(_esc(p.proses_adi) + ' ' + _fmt(p.yapilan));
        }
        return '<span class="plan-detay-mini-line">' +
            '<span class="plan-detay-mini-arrow">&rarr;</span>' +
            '<span class="plan-detay-mini-kat">ANA:</span>' +
            parts.join(' / ') +
            '</span>';
    }

    function _miniHtml(d) {
        var alt = d.alt_parcalar || [];
        var atki = null, govde = null;
        for (var i = 0; i < alt.length; i++) {
            var k = (alt[i].kategori || '').toLowerCase();
            if (k === 'atki' || k === 'atk\u0131') atki = alt[i];
            else if (k === 'govde' || k === 'g\u00f6vde') govde = alt[i];
        }
        var html = '';
        html += _katSatir('ATKI', atki);
        html += _katSatir('GOVDE', govde);
        html += _anaSatir(d);
        return html;
    }

    function _miniAc(tr, emirNo) {
        _kapatTumDetay();
        var kolon = _kolonSayisi();
        var ld = document.createElement('tr');
        ld.className = DETAY_TR_CLASS;
        ld.setAttribute('data-emir-detay', String(emirNo));
        ld.innerHTML = '<td colspan="' + kolon + '">' +
            '<span class="plan-detay-mini-loading">yukleniyor...</span></td>';
        tr.parentNode.insertBefore(ld, tr.nextSibling);

        fetch('/hedef/plan-detay/' + encodeURIComponent(emirNo), {
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' }
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        }).then(function (d) {
            if (!d || d.ok === false) {
                ld.querySelector('td').innerHTML =
                    '<span class="plan-detay-mini-error">' +
                    _esc((d && d.mesaj) || 'veri alinamadi') + '</span>';
                return;
            }
            ld.querySelector('td').innerHTML = _miniHtml(d);
        }).catch(function (err) {
            ld.querySelector('td').innerHTML =
                '<span class="plan-detay-mini-error">hata: ' +
                _esc(err && err.message ? err.message : err) + '</span>';
        });
    }

    function _onPlanClick(ev) {
        // Detay satirlarinin kendine tiklanirsa kapat
        if (ev.target.closest('#planBody tr.' + DETAY_TR_CLASS)) {
            _kapatTumDetay();
            return;
        }
        // Eski v3 satirina tiklanirsa kapat
        if (ev.target.closest('#planBody tr.' + OLD_V3_CLASS)) {
            _kapatTumDetay();
            return;
        }

        var tr = ev.target.closest('#planBody tr');
        if (!tr) return;
        if (tr.classList.contains(DETAY_TR_CLASS)) return;
        if (tr.classList.contains(OLD_V3_CLASS)) return;

        // Emir no'yu satirdan cek
        var emirNo = tr.getAttribute('data-emir-no') ||
                     tr.getAttribute('data-emir') ||
                     '';
        if (!emirNo) {
            // text icinden tahmin: 2. cell genelde emir
            var cells = tr.querySelectorAll('td');
            if (cells.length >= 2) {
                var t = (cells[1].textContent || '').replace(/\D/g, '');
                if (t) emirNo = t;
            }
        }
        if (!emirNo) return;

        // Eger ayni emir icin detay aciksa, kapat (toggle)
        var mevcut = document.querySelector(
            '#planBody tr.' + DETAY_TR_CLASS + '[data-emir-detay="' + emirNo + '"]'
        );
        if (mevcut) {
            _kapatTumDetay();
            return;
        }

        _miniAc(tr, emirNo);
    }

    // Mevcut click listener'lari ezmek icin capture phase'de baglan
    document.addEventListener('click', _onPlanClick, true);

    // V3'un MutationObserver'ini yumusatmak icin: DOM'a v4 satiri eklenmesini engelleme
    // (V3 click handler eski TR uretiyorsa, tiklandiginda hemen kaldir)
    var mo = new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
            for (var j = 0; j < muts[i].addedNodes.length; j++) {
                var n = muts[i].addedNodes[j];
                if (n.nodeType !== 1) continue;
                if (n.tagName === 'TR' && n.classList.contains(OLD_V3_CLASS)) {
                    n.remove();
                }
            }
        }
    });
    var planBody = document.getElementById('planBody');
    if (planBody) mo.observe(planBody, { childList: true, subtree: false });

    console.log('[CPS LOCAL] PLAN detay v4 mini yuklendi');
})();
'''

bak = PATH + '.bak_pre_mini_c_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(PATH, bak)
print('Yedek: ' + bak)

with io.open(PATH, 'w', encoding='utf-8') as f:
    f.write(src + JS)

print('OK: ADIM C V4 mini JS eklendi (' + str(len(JS)) + ' byte)')