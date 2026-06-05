# -*- coding: utf-8 -*-
"""
setup_rapor_v6_filtre_kpi.py
----------------------------
RAPOR ekrani esneklestirme (frontend-only, backend dokunulmaz):

1) Ust KPI kartlari: Toplam Uretim / Personel / Proses / Kayit
2) Her blok ustunde arama input'u
3) Tablo basliklarina tiklayinca siralama (default: toplam DESC)
4) Personel listesi: ilk 50 + 'Daha fazla goster' butonu
5) Frontend filtreleme (backend endpoint aynen)
6) Bloklar katlanabilir (Personel/Proses acik, Emir kapali default)
7) Tek innerHTML render (DOM append yok)
8) Bos durumda "Filtreye uygun kayit bulunamadi"

DOKUNMAZ:
  - Backend (/hedef/rapor endpoint aynen kalir)
  - PLAN, ONAYLAR, GECMIS
  - mock_data.db
"""

import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

JS_MARKER = "[CPS LOCAL] RAPOR v6 yuklendi"


JS_BLOCK = r'''


/* ====================================================================
   CPS LOCAL - RAPOR v6 (filtre + KPI + siralama + limit + katlama)
   - Backend /hedef/rapor aynen kullanilir
   - State: arama, sirala, kapali, personelLimit
   - Tek innerHTML render (300 kisi icin performansli)
   ==================================================================== */
(function () {
    'use strict';

    // ---- State ----
    var _state = {
        raw: null,
        personelLimit: 50,
        sirala: {
            personel: { col: 'toplam_miktar', dir: 'desc' },
            proses:   { col: 'toplam_miktar', dir: 'desc' },
            emir:     { col: 'toplam_miktar', dir: 'desc' }
        },
        arama: { personel: '', proses: '', emir: '' },
        kapali: { personel: false, proses: false, emir: true }
    };

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
    function _bugunISO() {
        var d = new Date();
        return d.getFullYear() + '-' +
            String(d.getMonth() + 1).padStart(2, '0') + '-' +
            String(d.getDate()).padStart(2, '0');
    }
    function _gunOnceISO(n) {
        var d = new Date();
        d.setDate(d.getDate() - n);
        return d.getFullYear() + '-' +
            String(d.getMonth() + 1).padStart(2, '0') + '-' +
            String(d.getDate()).padStart(2, '0');
    }

    // ---- Container ----
    function _ensureContainer() {
        var raporBody = document.getElementById('raporBody');
        if (raporBody) {
            var t = raporBody.closest('table');
            if (t) t.style.display = 'none';
        }
        var sonuc = document.getElementById('raporSonuc');
        if (!sonuc) {
            sonuc = document.createElement('div');
            sonuc.id = 'raporSonuc';
            var tblNode = raporBody && raporBody.closest('table');
            if (tblNode && tblNode.parentNode) {
                tblNode.parentNode.insertBefore(sonuc, tblNode.nextSibling);
            } else if (raporBody && raporBody.parentNode && raporBody.parentNode.parentNode) {
                raporBody.parentNode.parentNode.appendChild(sonuc);
            } else {
                var pane = document.querySelector('[data-pane="rapor"]') ||
                           document.querySelector('.h-pane[data-pane="rapor"]');
                (pane || document.body).appendChild(sonuc);
            }
        }
        return sonuc;
    }

    // ---- Filtre + sirala ----
    function _filtrele(arr, key) {
        var q = (_state.arama[key] || '').toLowerCase().trim();
        if (!q) return arr.slice();
        return arr.filter(function (r) {
            // Tum string kolonlarda ara
            for (var k in r) {
                if (Object.prototype.hasOwnProperty.call(r, k)) {
                    var v = r[k];
                    if (v != null && String(v).toLowerCase().indexOf(q) !== -1) return true;
                }
            }
            return false;
        });
    }
    function _sirala(arr, sira) {
        var col = sira.col, dir = sira.dir;
        return arr.slice().sort(function (a, b) {
            var av = a[col], bv = b[col];
            if (av == null) av = '';
            if (bv == null) bv = '';
            if (typeof av === 'number' && typeof bv === 'number') {
                return dir === 'asc' ? av - bv : bv - av;
            }
            // numerik mi parse et
            var an = Number(av), bn = Number(bv);
            if (!isNaN(an) && !isNaN(bn) && av !== '' && bv !== '') {
                return dir === 'asc' ? an - bn : bn - an;
            }
            // string
            var as = String(av).toLocaleLowerCase('tr-TR');
            var bs = String(bv).toLocaleLowerCase('tr-TR');
            return dir === 'asc' ? as.localeCompare(bs) : bs.localeCompare(as);
        });
    }

    // ---- KPI ----
    function _renderKPI(raw) {
        var personel = (raw && raw.personel_bazli) || [];
        var proses = (raw && raw.proses_bazli) || [];
        var toplam = 0, kayit = 0;
        for (var i = 0; i < personel.length; i++) {
            toplam += Number(personel[i].toplam_miktar || 0);
            kayit += Number(personel[i].kayit_sayisi || 0);
        }
        return [
            '<div class="rb-kpi-grid">',
            '<div class="rb-kpi-card"><div class="rb-kpi-label">Toplam Üretim</div><div class="rb-kpi-value">', _fmt(toplam), '</div></div>',
            '<div class="rb-kpi-card"><div class="rb-kpi-label">Personel</div><div class="rb-kpi-value">', _fmt(personel.length), '</div></div>',
            '<div class="rb-kpi-card"><div class="rb-kpi-label">Proses</div><div class="rb-kpi-value">', _fmt(proses.length), '</div></div>',
            '<div class="rb-kpi-card"><div class="rb-kpi-label">Kayıt</div><div class="rb-kpi-value">', _fmt(kayit), '</div></div>',
            '</div>'
        ].join('');
    }

    // ---- Tablo ----
    function _tabloHTML(rows, kolonlar, sira, blokKey, limit) {
        if (rows.length === 0) {
            return '<div class="rb-empty">Filtreye uygun kayıt bulunamadı.</div>';
        }
        var goster = (limit && limit > 0) ? rows.slice(0, limit) : rows;
        var parts = ['<table class="rb-table"><thead><tr>'];
        for (var i = 0; i < kolonlar.length; i++) {
            var k = kolonlar[i];
            var ok = (sira.col === k.key);
            var arrow = ok ? (sira.dir === 'asc' ? ' ▲' : ' ▼') : '';
            parts.push('<th class="' + (k.num ? 'num' : 'text') +
                ' rb-sort" data-blok="' + blokKey + '" data-col="' + k.key + '">' +
                _esc(k.label) + arrow + '</th>');
        }
        parts.push('</tr></thead><tbody>');
        for (var j = 0; j < goster.length; j++) {
            var r = goster[j];
            parts.push('<tr>');
            for (var c = 0; c < kolonlar.length; c++) {
                var kk = kolonlar[c];
                var v = r[kk.key];
                if (kk.num) {
                    parts.push('<td class="num">', _fmt(v), '</td>');
                } else {
                    parts.push('<td class="text">', _esc(v == null || v === '' ? '-' : v), '</td>');
                }
            }
            parts.push('</tr>');
        }
        parts.push('</tbody></table>');
        if (limit && limit > 0 && rows.length > limit) {
            var kalan = rows.length - limit;
            parts.push('<button class="rb-loadmore" data-blok="', blokKey,
                '">Daha fazla göster (+50, kalan ', String(kalan), ')</button>');
        }
        return parts.join('');
    }

    // ---- Blok ----
    function _blokHTML(key, baslik, kolonlar, rows, sira, limit, totalRaw) {
        var kapali = !!_state.kapali[key];
        var aramaVal = _state.arama[key] || '';
        var matchInfo = (aramaVal && rows.length !== totalRaw)
            ? ' (' + rows.length + '/' + totalRaw + ')'
            : ' (' + totalRaw + ')';
        var parts = ['<div class="rb-blok" data-blok="', key, '">'];
        parts.push('<div class="rb-blok-header" data-blok="', key, '">');
        parts.push('<span class="rb-toggle">', kapali ? '+' : '−', '</span>');
        parts.push('<span class="rb-baslik">', _esc(baslik), '</span>');
        parts.push('<span class="rb-count">', matchInfo, '</span>');
        parts.push('</div>');
        if (!kapali) {
            parts.push('<div class="rb-blok-body">');
            parts.push('<input type="search" class="rb-search" data-blok="', key,
                '" placeholder="', _esc(baslik), ' ara..." value="', _esc(aramaVal),
                '" autocomplete="off">');
            parts.push(_tabloHTML(rows, kolonlar, sira, key, limit));
            parts.push('</div>');
        }
        parts.push('</div>');
        return parts.join('');
    }

    // ---- Render ----
    function _render() {
        var sonuc = _ensureContainer();
        if (!sonuc) return;
        if (!_state.raw) return;

        var raw = _state.raw;
        var rawPersonel = raw.personel_bazli || [];
        var rawProses = raw.proses_bazli || [];
        var rawEmir = raw.emir_bazli || [];

        if (rawPersonel.length === 0 && rawProses.length === 0 && rawEmir.length === 0) {
            sonuc.innerHTML = _renderKPI(raw) +
                '<div class="rb-empty-all">Bu tarih aralığında onaylı üretim kaydı yok.</div>';
            _bindEvents();
            return;
        }

        var personel = _sirala(_filtrele(rawPersonel, 'personel'), _state.sirala.personel);
        var proses = _sirala(_filtrele(rawProses, 'proses'), _state.sirala.proses);
        var emir = _sirala(_filtrele(rawEmir, 'emir'), _state.sirala.emir);

        var html = _renderKPI(raw);
        html += _blokHTML('personel', 'Personel Bazlı', [
            { label: 'PERSONEL', key: 'personel_ad', num: false },
            { label: 'TOPLAM',   key: 'toplam_miktar', num: true },
            { label: 'KAYIT',    key: 'kayit_sayisi',  num: true }
        ], personel, _state.sirala.personel, _state.personelLimit, rawPersonel.length);

        html += _blokHTML('proses', 'Proses Bazlı', [
            { label: 'PROSES', key: 'proses_adi', num: false },
            { label: 'TOPLAM', key: 'toplam_miktar', num: true },
            { label: 'KAYIT',  key: 'kayit_sayisi',  num: true }
        ], proses, _state.sirala.proses, 0, rawProses.length);

        html += _blokHTML('emir', 'Emir Bazlı', [
            { label: 'EMİR',   key: 'emir_no', num: false },
            { label: 'MODEL',  key: 'model',   num: false },
            { label: 'TOPLAM', key: 'toplam_miktar', num: true },
            { label: 'KAYIT',  key: 'kayit_sayisi',  num: true }
        ], emir, _state.sirala.emir, 0, rawEmir.length);

        sonuc.innerHTML = html;
        _bindEvents();
    }

    // ---- Event binding ----
    function _bindEvents() {
        var sonuc = document.getElementById('raporSonuc');
        if (!sonuc) return;

        // Header click -> toggle
        sonuc.querySelectorAll('.rb-blok-header').forEach(function (h) {
            h.addEventListener('click', function () {
                var key = h.dataset.blok;
                _state.kapali[key] = !_state.kapali[key];
                _render();
            });
        });

        // Sort click
        sonuc.querySelectorAll('.rb-sort').forEach(function (th) {
            th.addEventListener('click', function (e) {
                e.stopPropagation();
                var blok = th.dataset.blok;
                var col = th.dataset.col;
                var s = _state.sirala[blok];
                if (s.col === col) {
                    s.dir = (s.dir === 'asc') ? 'desc' : 'asc';
                } else {
                    s.col = col;
                    s.dir = 'desc';
                }
                _render();
            });
        });

        // Search input
        sonuc.querySelectorAll('.rb-search').forEach(function (inp) {
            inp.addEventListener('click', function (e) { e.stopPropagation(); });
            inp.addEventListener('input', function () {
                var blok = inp.dataset.blok;
                _state.arama[blok] = inp.value || '';
                if (blok === 'personel') {
                    _state.personelLimit = 50;
                }
                var oldVal = inp.value;
                _render();
                // Focus restore
                var newInp = document.querySelector('.rb-search[data-blok="' + blok + '"]');
                if (newInp) {
                    newInp.focus();
                    try {
                        newInp.setSelectionRange(oldVal.length, oldVal.length);
                    } catch (_) {}
                }
            });
        });

        // Daha fazla goster
        sonuc.querySelectorAll('.rb-loadmore').forEach(function (btn) {
            btn.addEventListener('click', function () {
                _state.personelLimit += 50;
                _render();
            });
        });
    }

    // ---- Yukle ----
    function _yukleRapor() {
        var inpBas = document.getElementById('raporTarihBas');
        var inpBit = document.getElementById('raporTarihBit');
        var bas = (inpBas && inpBas.value) || '';
        var bit = (inpBit && inpBit.value) || '';

        var url = '/hedef/rapor';
        var params = [];
        if (bas) params.push('baslangic=' + encodeURIComponent(bas));
        if (bit) params.push('bitis=' + encodeURIComponent(bit));
        if (params.length) url += '?' + params.join('&');

        var sonuc = _ensureContainer();
        if (sonuc) sonuc.innerHTML = '<div class="rb-loading">Yükleniyor...</div>';

        fetch(url, {
            method: 'GET',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' }
        })
            .then(function (resp) {
                return resp.text().then(function (t) {
                    var d; try { d = JSON.parse(t); } catch (_) { d = null; }
                    return { status: resp.status, data: d };
                });
            })
            .then(function (r) {
                if (r.status >= 400 || !r.data || r.data.ok === false) {
                    if (sonuc) {
                        sonuc.innerHTML = '<div class="rb-empty-all">Rapor yüklenemedi.' +
                            (r.data && r.data.mesaj ? ' (' + _esc(r.data.mesaj) + ')' : '') + '</div>';
                    }
                    return;
                }
                _state.raw = r.data;
                _state.personelLimit = 50;
                _render();
                console.log('CPS/hedef/rapor v6', r.status,
                    (r.data.personel_bazli || []).length + ' personel, ' +
                    (r.data.proses_bazli || []).length + ' proses, ' +
                    (r.data.emir_bazli || []).length + ' emir');
            })
            .catch(function (e) {
                console.error('rapor v6 fetch:', e);
                if (sonuc) sonuc.innerHTML = '<div class="rb-empty-all">Sunucuya ulaşılamadı.</div>';
            });
    }

    // Override (v5'in uzerine)
    window.raporYukle = _yukleRapor;
    window.raporlariYukle = _yukleRapor;

    // ---- CSS ----
    if (!document.getElementById('raporStylesV6')) {
        var s = document.createElement('style');
        s.id = 'raporStylesV6';
        s.textContent = [
            '#raporSonuc .rb-kpi-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-bottom:14px; }',
            '#raporSonuc .rb-kpi-card { background:#fff; border-radius:10px; padding:12px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.05); }',
            '#raporSonuc .rb-kpi-label { font-size:10px; font-weight:700; letter-spacing:1px; color:var(--text3); text-transform:uppercase; }',
            '#raporSonuc .rb-kpi-value { font-family:var(--mono); font-size:22px; font-weight:700; color:var(--text); margin-top:4px; line-height:1.1; }',
            '#raporSonuc .rb-blok { margin-bottom:10px; background:#fff; border-radius:10px; box-shadow:0 1px 3px rgba(0,0,0,0.05); overflow:hidden; }',
            '#raporSonuc .rb-blok-header { padding:12px 16px; font-size:12px; font-weight:700; letter-spacing:0.7px; color:var(--text2); text-transform:uppercase; cursor:pointer; user-select:none; display:flex; align-items:center; gap:10px; }',
            '#raporSonuc .rb-blok-header:hover { background:rgba(0,0,0,0.02); }',
            '#raporSonuc .rb-toggle { display:inline-flex; width:20px; height:20px; align-items:center; justify-content:center; background:var(--bg3,#f3f4f6); border-radius:4px; font-size:14px; line-height:1; flex-shrink:0; }',
            '#raporSonuc .rb-baslik { flex-shrink:0; }',
            '#raporSonuc .rb-count { color:var(--text3); font-weight:600; font-size:11px; margin-left:auto; }',
            '#raporSonuc .rb-blok-body { padding:0 16px 14px; }',
            '#raporSonuc .rb-search { width:100%; padding:8px 12px; border:1px solid var(--border); border-radius:6px; margin-bottom:10px; font-size:13px; outline:none; box-sizing:border-box; }',
            '#raporSonuc .rb-search:focus { border-color:var(--sol,#f97316); box-shadow:0 0 0 2px rgba(249,115,22,0.15); }',
            '#raporSonuc table.rb-table { width:100%; border-collapse:collapse; }',
            '#raporSonuc table.rb-table th, #raporSonuc table.rb-table td { padding:8px 12px; white-space:nowrap; border-bottom:1px solid var(--border); font-size:13px; }',
            '#raporSonuc table.rb-table th { font-weight:700; color:var(--text3); font-size:10px; letter-spacing:0.5px; text-transform:uppercase; cursor:pointer; user-select:none; }',
            '#raporSonuc table.rb-table th:hover { color:var(--text); background:rgba(0,0,0,0.02); }',
            '#raporSonuc table.rb-table th.num, #raporSonuc table.rb-table td.num { text-align:right; font-family:var(--mono); }',
            '#raporSonuc table.rb-table th.text, #raporSonuc table.rb-table td.text { text-align:left; }',
            '#raporSonuc .rb-loadmore { display:block; width:100%; margin-top:10px; padding:10px; background:var(--bg3,#f3f4f6); border:1px dashed var(--border); border-radius:6px; font-size:12px; color:var(--text2); cursor:pointer; }',
            '#raporSonuc .rb-loadmore:hover { background:var(--bg4,#e5e7eb); }',
            '#raporSonuc .rb-empty { padding:18px; text-align:center; color:var(--text3); font-size:13px; }',
            '#raporSonuc .rb-empty-all { padding:48px; text-align:center; color:var(--text3); background:#fff; border-radius:10px; box-shadow:0 1px 3px rgba(0,0,0,0.05); }',
            '#raporSonuc .rb-loading { padding:32px; text-align:center; color:var(--text3); }',
            '@media (max-width:720px) { #raporSonuc .rb-kpi-grid { grid-template-columns:repeat(2,1fr); } }'
        ].join('\n');
        document.head.appendChild(s);
    }

    console.log('[CPS LOCAL] RAPOR v6 yuklendi.');
})();
'''


def main():
    print()
    print("=" * 64)
    print("RAPOR v6 - filtre + KPI + siralama + limit + katlama")
    print("=" * 64)

    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} bulunamadi.")
        return 1

    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if JS_MARKER in src:
        print("  [BILGI] RAPOR v6 zaten ekli.")
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
    print("  [OK] RAPOR v6 IIFE eklendi.")
    print()
    print("YAPILACAK:")
    print("  1) CPS sunucusunu yeniden baslat")
    print("  2) Browser'da Ctrl+F5")
    print("  3) /hedef/ -> RAPOR sekmesi")
    print()
    print("Beklenen ekran:")
    print("  [4 KPI kart] Toplam 1.490 | Personel 1 | Proses 4 | Kayit 4")
    print("  [Personel Bazli (1)]   ACIK")
    print("    [arama input]")
    print("    PERSONEL  TOPLAM  KAYIT (kolon basliklari TIKLANARAK siralanir)")
    print("    Sistem Yöneticisi  1.490   4")
    print("  [Proses Bazli (4)]     ACIK")
    print("    [arama input]")
    print("    PROSES   TOPLAM  KAYIT")
    print("    Monta    1.000   1")
    print("    Enjeksiyon 250   1")
    print("    Kesim    120     1")
    print("    Temizleme 120    1")
    print("  [Emir Bazli (1)]       KAPALI (basliga tikla -> acilir)")
    print()
    print("Test:")
    print("  - Personel arama: 'sistem' yaz -> sadece eslesen kalmali")
    print("  - Tablo basligi tikla: siralama degisir, ok yon belli (▲/▼)")
    print("  - Emir blok basligini tikla: + -> − degisir, body acilir")
    print()
    print("Console:")
    print("  [CPS LOCAL] RAPOR v6 yuklendi.")
    print("  CPS/hedef/rapor v6 200 1 personel, 4 proses, 1 emir")
    return 0


if __name__ == '__main__':
    sys.exit(main())
