# -*- coding: utf-8 -*-
"""
setup_faz46_b3_siparis_uygula.py
--------------------------------
FAZ 4.6 B3 - Siparis emirlerine sablon uygula UI.

Yapilan:
  - hedef.js'e yeni bir IIFE: "Siparis Emirlerine Sablon Uygula" panel
  - SABLON pane'inde sablon listesinin ALTINA blok eklenir
  - Akis:
      * Siparis no gir + 'Emirleri Getir'
      * GET /hedef/siparis/emirler?sipno=
      * UI: 2 blok (ANA / ALT) checkbox + emir listesi
      * Her satirin saginda [Sablon ▼] [Uygula] (tekil)
      * Ustte 'Toplu uygula': secili checkbox'lar icin tek sablonu loop
      * POST /hedef/sablon/uygula (her emir icin)
      * Sonuc toast: "X eklendi, Y zaten vardi"

DOKUNMAZ:
  - Backend (B1 endpoint'leri kullanir, yeni endpoint yok)
  - B2 sablon listesi UI'i (altina blok ekler)
  - PLAN, RAPOR, ONAYLAR, GECMIS
  - mock_data.db semasi
"""

import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")
JS_MARKER = "[CPS LOCAL] FAZ 4.6 B3 siparis-uygula"


JS_BLOCK = r'''


/* ====================================================================
   CPS LOCAL - FAZ 4.6 B3 - Siparis Emirlerine Sablon Uygula
   - SABLON pane'inde sablon listesinin altina blok ekler
   - Siparis no -> Korgun emirler -> ANA/ALT grupla -> sablon uygula
   ==================================================================== */
(function () {
    'use strict';

    var _state = {
        sablonlar: [],
        emirler: [],     // {EmirNo, ModelKod, ModelAdi, EmirTip, ParentEmirNo, ...}
        prosesSayilari: {}, // emir_no -> aktif proses sayisi (mock_data)
        sipnoSon: ''
    };

    // ---- CSS ----
    if (!document.getElementById('sb3Styles')) {
        var s = document.createElement('style');
        s.id = 'sb3Styles';
        s.textContent = [
            '#sb3Panel { margin-top:18px; padding:14px 16px; background:#fff; border-radius:8px; box-shadow:0 1px 3px rgba(0,0,0,0.05); }',
            '#sb3Panel h3 { margin:0 0 12px 0; font-size:14px; font-weight:700; color:var(--text); }',
            '#sb3Panel .sb3-bar { display:flex; gap:8px; margin-bottom:14px; align-items:center; flex-wrap:wrap; }',
            '#sb3Panel .sb3-bar input { padding:8px 12px; border:1px solid var(--border); border-radius:6px; font-size:13px; flex:0 0 200px; outline:none; box-sizing:border-box; }',
            '#sb3Panel .sb3-bar input:focus { border-color:var(--sol,#f97316); box-shadow:0 0 0 2px rgba(249,115,22,0.15); }',
            '#sb3Panel .sb3-getir { background:var(--sol,#f97316); color:#fff; border:0; padding:8px 16px; border-radius:6px; font-size:12px; font-weight:700; cursor:pointer; }',
            '#sb3Panel .sb3-getir:hover { filter:brightness(0.9); }',
            '#sb3Panel .sb3-info { color:var(--text3); font-size:12px; margin-left:auto; }',

            '#sb3Panel .sb3-toplu { background:#fef3c7; border:1px solid #f59e0b; border-radius:8px; padding:10px 14px; margin-bottom:14px; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }',
            '#sb3Panel .sb3-toplu .lbl { font-size:11px; font-weight:700; color:#92400e; letter-spacing:0.4px; text-transform:uppercase; }',
            '#sb3Panel .sb3-toplu select { padding:6px 10px; border:1px solid var(--border); border-radius:6px; font-size:12px; flex:1; min-width:180px; outline:none; }',
            '#sb3Panel .sb3-toplu .uygulaBtn { background:#16a34a; color:#fff; border:0; padding:7px 14px; border-radius:6px; font-size:12px; font-weight:700; cursor:pointer; }',
            '#sb3Panel .sb3-toplu .uygulaBtn:hover { filter:brightness(0.92); }',
            '#sb3Panel .sb3-toplu .uygulaBtn:disabled { background:#d1d5db; cursor:not-allowed; }',
            '#sb3Panel .sb3-toplu .secim-info { font-size:11px; color:var(--text3); }',

            '#sb3Panel .sb3-grup { margin-bottom:18px; }',
            '#sb3Panel .sb3-grup h4 { margin:0 0 8px 0; font-size:11px; font-weight:700; color:var(--text2); letter-spacing:0.5px; text-transform:uppercase; padding:6px 10px; background:#f3f4f6; border-radius:6px; display:flex; align-items:center; gap:8px; }',
            '#sb3Panel .sb3-grup h4 .grup-sayisi { color:var(--text3); font-weight:600; font-size:10px; }',
            '#sb3Panel .sb3-grup h4 .grup-tum { margin-left:auto; font-size:10px; color:var(--sol,#f97316); cursor:pointer; user-select:none; }',
            '#sb3Panel .sb3-grup h4 .grup-tum:hover { text-decoration:underline; }',

            '#sb3Panel table.sb3-table { width:100%; border-collapse:collapse; }',
            '#sb3Panel table.sb3-table th, #sb3Panel table.sb3-table td { padding:7px 10px; text-align:left; border-bottom:1px solid var(--border); font-size:12px; vertical-align:middle; }',
            '#sb3Panel table.sb3-table th { font-size:9px; color:var(--text3); text-transform:uppercase; letter-spacing:0.5px; background:#fafafa; white-space:nowrap; }',
            '#sb3Panel table.sb3-table td.num { text-align:right; font-family:var(--mono); white-space:nowrap; }',
            '#sb3Panel table.sb3-table td.aks { text-align:right; white-space:nowrap; }',
            '#sb3Panel table.sb3-table td.tip-rozet span { display:inline-block; padding:2px 6px; border-radius:8px; font-size:9px; font-weight:700; letter-spacing:0.4px; }',
            '#sb3Panel .tip-ana { background:#dcfce7; color:#15803d; }',
            '#sb3Panel .tip-alt { background:#dbeafe; color:#1e40af; }',
            '#sb3Panel .sb3-row-sablon { display:flex; gap:6px; align-items:center; }',
            '#sb3Panel .sb3-row-sablon select { padding:4px 8px; border:1px solid var(--border); border-radius:4px; font-size:11px; min-width:120px; max-width:160px; outline:none; }',
            '#sb3Panel .sb3-row-sablon button { background:#16a34a; color:#fff; border:0; padding:4px 10px; border-radius:4px; font-size:11px; font-weight:700; cursor:pointer; }',
            '#sb3Panel .sb3-row-sablon button:hover { filter:brightness(0.92); }',
            '#sb3Panel .sb3-row-sablon button:disabled { background:#d1d5db; cursor:not-allowed; }',

            '#sb3Panel .sb3-empty, #sb3Panel .sb3-loading, #sb3Panel .sb3-error { padding:28px; text-align:center; color:var(--text3); background:#fafafa; border-radius:6px; }',
            '#sb3Panel .sb3-error { color:#dc2626; }',

            '#sb3Toast { position:fixed; bottom:20px; right:20px; z-index:9999; max-width:380px; padding:14px 18px; border-radius:8px; box-shadow:0 4px 12px rgba(0,0,0,0.15); font-size:13px; line-height:1.5; display:none; }',
            '#sb3Toast.gor { display:block; }',
            '#sb3Toast.basari { background:#dcfce7; border:1px solid #16a34a; color:#14532d; }',
            '#sb3Toast.uyari  { background:#fef3c7; border:1px solid #f59e0b; color:#78350f; }',
            '#sb3Toast.hata   { background:#fee2e2; border:1px solid #dc2626; color:#7f1d1d; }',
            '#sb3Toast .baslik { font-weight:700; margin-bottom:4px; }'
        ].join('\n');
        document.head.appendChild(s);
    }

    // ---- Helpers ----
    function _esc(s) {
        if (s == null) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    function _fmt(n) {
        var x = Number(n);
        if (!isFinite(x)) return _esc(n);
        return x.toLocaleString('tr-TR');
    }
    function _api(url, opts) {
        opts = opts || {};
        opts.credentials = 'include';
        opts.headers = opts.headers || {};
        if (!opts.headers['Content-Type']) opts.headers['Content-Type'] = 'application/json';
        return fetch(url, opts).then(function (r) {
            return r.text().then(function (t) {
                var d; try { d = JSON.parse(t); } catch (_) { d = null; }
                return { status: r.status, data: d };
            });
        });
    }
    function _toast(tip, baslik, mesaj) {
        var t = document.getElementById('sb3Toast');
        if (!t) {
            t = document.createElement('div');
            t.id = 'sb3Toast';
            document.body.appendChild(t);
        }
        t.className = '';
        t.classList.add('gor', tip);
        t.innerHTML = '<div class="baslik">' + _esc(baslik) + '</div>' +
                      '<div>' + _esc(mesaj) + '</div>';
        clearTimeout(t._tid);
        t._tid = setTimeout(function () { t.classList.remove('gor'); }, 5000);
    }

    // ---- Panel olustur ----
    function _ensurePanel() {
        var pane = document.getElementById('pane-sablon');
        if (!pane) return null;
        // B2'nin sb2Pane'i icinde mi? Onun yaninakardesi olarak yerlestir.
        if (pane.querySelector('#sb3Panel')) return pane.querySelector('#sb3Panel');

        var div = document.createElement('div');
        div.id = 'sb3Panel';
        div.innerHTML = [
            '<h3>🎯 Sipariş Emirlerine Şablon Uygula</h3>',
            '<div class="sb3-bar">',
            '  <input type="text" id="sb3Sipno" placeholder="Sipariş No (örn 33558)" autocomplete="off">',
            '  <button class="sb3-getir" id="sb3GetirBtn">Emirleri Getir</button>',
            '  <span class="sb3-info" id="sb3Info"></span>',
            '</div>',
            '<div id="sb3Sonuc"></div>'
        ].join('\n');

        // sb2Pane varsa onun yanına ekle, yoksa pane'e ekle
        var sb2 = document.getElementById('sb2Pane');
        if (sb2 && sb2.parentNode === pane) {
            pane.appendChild(div);
        } else {
            pane.appendChild(div);
        }

        document.getElementById('sb3GetirBtn').addEventListener('click', _emirleriGetir);
        document.getElementById('sb3Sipno').addEventListener('keydown', function (e) {
            if (e.key === 'Enter') _emirleriGetir();
        });

        return div;
    }

    // ---- Sablon listesi (dropdown kaynak) ----
    function _yukleSablonlar() {
        return _api('/hedef/sablon/liste').then(function (r) {
            if (r.data && r.data.ok) {
                _state.sablonlar = r.data.kayitlar || [];
            } else {
                _state.sablonlar = [];
            }
        });
    }

    // ---- Emir alt proses sayilarini cek (her emir icin paralel) ----
    function _yukleProsesSayilari(emirNos) {
        // Tum emirler icin /uretim/emir/<no>/prosesler cek
        // Cok emirde performans dert olabilir ama simdilik basit
        if (!emirNos || emirNos.length === 0) return Promise.resolve();
        var uniq = {};
        emirNos.forEach(function (n) { uniq[n] = true; });
        var liste = Object.keys(uniq);
        var promises = liste.map(function (no) {
            return _api('/uretim/emir/' + encodeURIComponent(no) + '/prosesler')
                .then(function (r) {
                    var c = 0;
                    if (r.data && r.data.prosesler) c = r.data.prosesler.length;
                    _state.prosesSayilari[no] = c;
                }).catch(function () {
                    _state.prosesSayilari[no] = 0;
                });
        });
        return Promise.all(promises);
    }

    // ---- Emirleri getir ----
    function _emirleriGetir() {
        var inp = document.getElementById('sb3Sipno');
        var sipno = (inp.value || '').trim();
        if (!sipno) {
            _toast('uyari', 'Eksik', 'Sipariş no gir.');
            inp.focus();
            return;
        }
        var sonuc = document.getElementById('sb3Sonuc');
        sonuc.innerHTML = '<div class="sb3-loading">Yükleniyor... (Korgun + sablon listesi)</div>';
        document.getElementById('sb3Info').textContent = '';

        _state.sipnoSon = sipno;
        _state.prosesSayilari = {};

        Promise.all([
            _api('/hedef/siparis/emirler?sipno=' + encodeURIComponent(sipno)),
            _yukleSablonlar()
        ]).then(function (results) {
            var r = results[0];
            if (r.status >= 400 || !r.data || r.data.ok === false) {
                sonuc.innerHTML = '<div class="sb3-error">Emirler alınamadı.' +
                    (r.data && r.data.mesaj ? ' (' + _esc(r.data.mesaj) + ')' : '') + '</div>';
                return;
            }
            _state.emirler = r.data.emirler || [];
            if (_state.emirler.length === 0) {
                sonuc.innerHTML = '<div class="sb3-empty">Bu siparişte emir bulunamadı.</div>';
                return;
            }

            // Proses sayilari arkadan yuklensin
            var emirNos = _state.emirler.map(function (e) { return e.EmirNo; });
            _yukleProsesSayilari(emirNos).then(function () { _renderTablolar(); });

            _renderTablolar();
            document.getElementById('sb3Info').textContent =
                'Sipariş ' + sipno + ' — ' +
                (r.data.ana_sayisi || 0) + ' ana / ' +
                (r.data.alt_sayisi || 0) + ' alt = ' +
                (r.data.emir_sayisi || _state.emirler.length) + ' emir';
        }).catch(function (e) {
            console.error('emirler getir:', e);
            sonuc.innerHTML = '<div class="sb3-error">Sunucuya ulaşılamadı: ' + _esc(e.message) + '</div>';
        });
    }

    // ---- Sablon dropdown HTML ----
    function _sablonOptions(secId) {
        var opts = ['<option value="">— Şablon Seç —</option>'];
        (_state.sablonlar || []).forEach(function (s) {
            var sel = (secId && parseInt(secId, 10) === s.id) ? ' selected' : '';
            opts.push('<option value="' + s.id + '"' + sel + '>' +
                _esc(s.sablon_adi) + ' (' + s.proses_sayisi + ' proses)</option>');
        });
        return opts.join('');
    }

    // ---- Tablo render ----
    function _renderTablolar() {
        var sonuc = document.getElementById('sb3Sonuc');
        if (!sonuc) return;

        var ana = _state.emirler.filter(function (e) { return e.EmirTip === 'ana'; });
        var alt = _state.emirler.filter(function (e) { return e.EmirTip === 'alt'; });

        var html = [];

        // Toplu uygulama bari (sablon varsa)
        if (_state.sablonlar.length > 0) {
            html.push('<div class="sb3-toplu">');
            html.push('<span class="lbl">Toplu Uygula:</span>');
            html.push('<select id="sb3TopluSablon">' + _sablonOptions(null) + '</select>');
            html.push('<button class="uygulaBtn" id="sb3TopluUygulaBtn" disabled>Seçili Emirlere Uygula</button>');
            html.push('<span class="secim-info" id="sb3SecimInfo">0 emir seçili</span>');
            html.push('</div>');
        } else {
            html.push('<div class="sb3-empty" style="margin-bottom:14px;">⚠ Henüz şablon yok. Yukarıdan + YENİ ŞABLON ile ekleyin.</div>');
        }

        function _grupHTML(baslik, rozetClass, emirler, grupKey) {
            if (emirler.length === 0) return '';
            var p = ['<div class="sb3-grup">'];
            p.push('<h4>',
                '<span>' + _esc(baslik) + '</span>',
                '<span class="grup-sayisi">(' + emirler.length + ')</span>',
                '<span class="grup-tum" data-grup="' + grupKey + '">tümünü seç/temizle</span>',
                '</h4>');
            p.push('<table class="sb3-table"><thead><tr>',
                '<th style="width:32px;"><input type="checkbox" data-grupchk="' + grupKey + '"></th>',
                '<th>EMİR</th>',
                '<th>TİP</th>',
                '<th>MODEL</th>',
                '<th class="num" style="width:100px;">HEDEF</th>',
                '<th class="num" style="width:90px;">PROSES</th>',
                '<th>LOKASYON</th>',
                '<th class="aks" style="width:280px;">ŞABLON UYGULA</th>',
                '</tr></thead><tbody>');
            emirler.forEach(function (e) {
                var prsCnt = _state.prosesSayilari[e.EmirNo];
                var prsTxt = (prsCnt === undefined) ? '...' : String(prsCnt);
                var rozet = (e.EmirTip === 'ana')
                    ? '<span class="tip-ana">📦 ANA</span>'
                    : '<span class="tip-alt">🔧 ALT</span>';
                var hedef = (e.HedefMiktar != null) ? _fmt(e.HedefMiktar) : '-';
                var modelText = e.ModelAdi || e.ModelKod || '-';
                if (modelText.length > 60) modelText = modelText.substring(0, 60) + '...';
                p.push('<tr data-emir="' + _esc(e.EmirNo) + '">',
                    '<td><input type="checkbox" class="emir-chk" data-emir="' + _esc(e.EmirNo) + '" data-grup="' + grupKey + '"></td>',
                    '<td><strong>' + _esc(e.EmirNo) + '</strong>' +
                        (e.ParentEmirNo ? '<br><small style="color:var(--text3);">parent: ' + _esc(e.ParentEmirNo) + '</small>' : '') +
                        '</td>',
                    '<td class="tip-rozet">' + rozet + '</td>',
                    '<td>' + _esc(modelText) + '</td>',
                    '<td class="num">' + hedef + '</td>',
                    '<td class="num">' + _esc(prsTxt) + '</td>',
                    '<td>' + _esc(e.Location || '-') + '</td>',
                    '<td class="aks">',
                    '<div class="sb3-row-sablon">',
                    '<select class="row-sablon" data-emir="' + _esc(e.EmirNo) + '">' + _sablonOptions(null) + '</select>',
                    '<button class="row-uygula" data-emir="' + _esc(e.EmirNo) + '">Uygula</button>',
                    '</div>',
                    '</td></tr>');
            });
            p.push('</tbody></table></div>');
            return p.join('');
        }

        html.push(_grupHTML('📦 Ana Emirler (Mamul)', 'ana', ana, 'ana'));
        html.push(_grupHTML('🔧 Alt Emirler (Yarı Mamul)', 'alt', alt, 'alt'));

        sonuc.innerHTML = html.join('');

        // Event bindings
        sonuc.querySelectorAll('.row-uygula').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var emirNo = btn.dataset.emir;
                var sel = sonuc.querySelector('select.row-sablon[data-emir="' + emirNo + '"]');
                if (!sel) return;
                var sid = parseInt(sel.value, 10);
                if (!sid) {
                    _toast('uyari', 'Eksik', 'Önce bir şablon seç.');
                    return;
                }
                _uygula([emirNo], sid);
            });
        });

        sonuc.querySelectorAll('.emir-chk').forEach(function (chk) {
            chk.addEventListener('change', _secimGuncelle);
        });

        sonuc.querySelectorAll('[data-grupchk]').forEach(function (chk) {
            chk.addEventListener('change', function () {
                var grup = chk.dataset.grupchk;
                sonuc.querySelectorAll('.emir-chk[data-grup="' + grup + '"]').forEach(function (c) {
                    c.checked = chk.checked;
                });
                _secimGuncelle();
            });
        });

        sonuc.querySelectorAll('.grup-tum').forEach(function (sp) {
            sp.addEventListener('click', function () {
                var grup = sp.dataset.grup;
                var chks = sonuc.querySelectorAll('.emir-chk[data-grup="' + grup + '"]');
                var hepsiSecili = Array.prototype.every.call(chks, function (c) { return c.checked; });
                chks.forEach(function (c) { c.checked = !hepsiSecili; });
                var grupChk = sonuc.querySelector('[data-grupchk="' + grup + '"]');
                if (grupChk) grupChk.checked = !hepsiSecili;
                _secimGuncelle();
            });
        });

        var topluBtn = document.getElementById('sb3TopluUygulaBtn');
        if (topluBtn) {
            topluBtn.addEventListener('click', function () {
                var sel = document.getElementById('sb3TopluSablon');
                var sid = parseInt(sel.value, 10);
                if (!sid) {
                    _toast('uyari', 'Eksik', 'Önce bir şablon seç.');
                    return;
                }
                var secili = Array.prototype.map.call(
                    sonuc.querySelectorAll('.emir-chk:checked'),
                    function (c) { return c.dataset.emir; }
                );
                if (secili.length === 0) {
                    _toast('uyari', 'Eksik', 'En az 1 emir seç.');
                    return;
                }
                if (!confirm(secili.length + ' emire şablon uygulanacak. Onaylıyor musun?')) return;
                _uygula(secili, sid);
            });
        }
    }

    function _secimGuncelle() {
        var sonuc = document.getElementById('sb3Sonuc');
        if (!sonuc) return;
        var sayi = sonuc.querySelectorAll('.emir-chk:checked').length;
        var info = document.getElementById('sb3SecimInfo');
        if (info) info.textContent = sayi + ' emir seçili';
        var btn = document.getElementById('sb3TopluUygulaBtn');
        if (btn) btn.disabled = (sayi === 0);
    }

    // ---- Sablon uygula (1+ emir icin) ----
    function _uygula(emirNos, sablonId) {
        if (!emirNos || emirNos.length === 0) return;
        var sablon = _state.sablonlar.find(function (s) { return s.id === sablonId; });
        var sablonAdi = sablon ? sablon.sablon_adi : ('#' + sablonId);

        var topluBtn = document.getElementById('sb3TopluUygulaBtn');
        if (topluBtn) topluBtn.disabled = true;

        var toplamEklenen = 0;
        var toplamAtlanan = 0;
        var basariliEmirler = 0;
        var hatalar = [];

        var i = 0;
        function _sira() {
            if (i >= emirNos.length) {
                // Bitti
                if (topluBtn) topluBtn.disabled = false;

                // Proses sayilarini yenile (basariliEmirler icin)
                _yukleProsesSayilari(emirNos).then(function () { _renderTablolar(); });

                if (hatalar.length === 0) {
                    _toast('basari', 'Şablon uygulandı: ' + sablonAdi,
                        '✔ ' + toplamEklenen + ' proses eklendi' +
                        (toplamAtlanan > 0 ? ' / ⚠ ' + toplamAtlanan + ' proses zaten vardı' : '') +
                        ' • ' + basariliEmirler + ' emire işlendi');
                } else {
                    _toast('uyari', 'Kısmi uygulandı: ' + sablonAdi,
                        '✔ ' + basariliEmirler + ' emir başarılı / ❌ ' + hatalar.length + ' hata' +
                        ' (' + toplamEklenen + ' eklendi, ' + toplamAtlanan + ' atlandı)');
                }
                return;
            }
            var emirNo = emirNos[i];
            i++;
            _api('/hedef/sablon/uygula', {
                method: 'POST',
                body: JSON.stringify({ emir_no: emirNo, sablon_id: sablonId })
            }).then(function (r) {
                if (r.status >= 400 || !r.data || r.data.ok === false) {
                    hatalar.push({ emir: emirNo, mesaj: (r.data && r.data.mesaj) || ('HTTP ' + r.status) });
                } else {
                    toplamEklenen += (r.data.eklenen_sayisi || 0);
                    toplamAtlanan += (r.data.atlanan_sayisi || 0);
                    basariliEmirler++;
                }
                _sira();
            }).catch(function (e) {
                hatalar.push({ emir: emirNo, mesaj: e.message });
                _sira();
            });
        }
        _sira();
    }

    // ---- Tetik ----
    function _hazirla() {
        _ensurePanel();
        // sablon listesini erkenden yukle
        _yukleSablonlar();
    }

    var sablonTab = document.querySelector('.h-tab[data-tab="sablon"]');
    if (sablonTab) {
        sablonTab.addEventListener('click', function () {
            // sb2 hazirla'dan sonra calissin
            setTimeout(_hazirla, 150);
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            var aktTab = document.querySelector('.h-tab.active[data-tab="sablon"]');
            if (aktTab) setTimeout(_hazirla, 250);
        });
    } else {
        var aktTab = document.querySelector('.h-tab.active[data-tab="sablon"]');
        if (aktTab) setTimeout(_hazirla, 150);
    }

    window.sb3Hazirla = _hazirla;
    window.sb3Getir = _emirleriGetir;

    console.log('[CPS LOCAL] FAZ 4.6 B3 siparis-uygula yuklendi.');
})();
'''


def main():
    print("=" * 64)
    print("FAZ 4.6 B3 - Siparis Emirlerine Sablon Uygula UI")
    print("=" * 64)
    print("CPS_KURALLAR uyum:")
    print("  ✓ Korgun read-only (mevcut helper)")
    print("  ✓ uretim_kaydet'e dokunulmuyor")
    print("  ✓ Yeni endpoint yok (B1'dekiler kullaniliyor)")
    print("  ✓ Duplicate engelleme backend'de zaten var")

    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} bulunamadi.")
        return 1

    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if JS_MARKER in src:
        print("  [BILGI] B3 zaten ekli.")
        return 0

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += JS_BLOCK

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = JS_PATH + f'.bak_{ts}'
    shutil.copy2(JS_PATH, bp)
    print(f"  [OK] Yedek: {bp}")

    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] B3 IIFE eklendi.")
    print()
    print("YAPILACAK:")
    print("  1) Browser'da Ctrl+F5 (sunucu restart gerekmez)")
    print("  2) /hedef/ -> SABLON sekmesi")
    print()
    print("Beklenen ekran:")
    print("  - Üstte: 📋 Sablon Yonetimi (B2 - var olan)")
    print("  - Altta YENİ: 🎯 Siparis Emirlerine Sablon Uygula")
    print("    [ Siparis No 33558 ] [ Emirleri Getir ]")
    print()
    print("Test:")
    print("  1. Siparis no: 33558 yaz, Enter veya 'Emirleri Getir'")
    print("  2. 30 ana + 25 alt emir gorunmeli")
    print("  3. 110626 satirinda 'Atki LCW' sec, 'Uygula' tikla")
    print("  4. Toast: 'Sablon uygulandi: 4 eklendi / 2 zaten vardi'")
    print("  5. /uretim/ -> 110626 sorgu -> proses listesinde yeni 4 proses")
    print()
    print("Console:")
    print("  [CPS LOCAL] FAZ 4.6 B3 siparis-uygula yuklendi.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
