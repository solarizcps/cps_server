# -*- coding: utf-8 -*-
"""
setup_faz46_b2_sablon_ui.py
---------------------------
FAZ 4.6 B2 - Sablon UI (basit liste).

Yapilan:
  - hedef.js'e tek bir IIFE: SABLON sekmesi acilinca /hedef/sablon/liste cek,
    pane'in icine tablo bas
  - Sutunlar: ID | AD | ACIKLAMA | PROSES SAYISI | PROSESLER (kisa) | TARIH | ISLEM
  - Bos durum: 'Sablon bulunamadi'
  - Hata durumu: 'Sablon yuklenemedi'
  - + YENI SABLON butonu: basit modal (ad + aciklama + proses listesi virgulle)
  - SIL butonu: confirm sonrasi soft delete

Idempotent (marker kontrolu).

DOKUNMAZ:
  - Backend (B1 endpoint'leri zaten var)
  - PLAN, RAPOR, ONAYLAR, GECMIS
  - mock_data.db semasi
  - Mevcut HTML pane'ler (id="pane-sablon" icine yaziyoruz)
"""

import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")
JS_MARKER = "[CPS LOCAL] FAZ 4.6 B2 sablon UI yuklendi"


JS_BLOCK = r'''


/* ====================================================================
   CPS LOCAL - FAZ 4.6 B2 - Sablon UI
   - SABLON sekmesi acildiginda /hedef/sablon/liste cek, render et
   - + YENI SABLON modal: sablon_adi, aciklama, prosesler (virgulle)
   - Eski 'UI.3 asamasinda' placeholder'i siler, yerine tablo koyar
   ==================================================================== */
(function () {
    'use strict';

    var _state = { sablonlar: [], yuklendi: false };

    // ---- CSS ----
    if (!document.getElementById('sb2Styles')) {
        var s = document.createElement('style');
        s.id = 'sb2Styles';
        s.textContent = [
            '#sb2Pane { padding:10px 4px; }',
            '#sb2Pane .sb2-bar { display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; gap:10px; }',
            '#sb2Pane .sb2-bar h3 { margin:0; font-size:14px; font-weight:700; color:var(--text); }',
            '#sb2Pane .sb2-ekle { background:var(--sol,#f97316); color:#fff; border:0; padding:8px 14px; border-radius:6px; font-size:12px; font-weight:700; cursor:pointer; letter-spacing:0.4px; }',
            '#sb2Pane .sb2-ekle:hover { filter:brightness(0.9); }',
            '#sb2Pane table.sb2-table { width:100%; border-collapse:collapse; background:#fff; border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.05); }',
            '#sb2Pane table.sb2-table th, #sb2Pane table.sb2-table td { padding:9px 12px; text-align:left; border-bottom:1px solid var(--border); font-size:13px; vertical-align:top; }',
            '#sb2Pane table.sb2-table th { font-size:10px; color:var(--text3); text-transform:uppercase; letter-spacing:0.5px; background:#fafafa; white-space:nowrap; }',
            '#sb2Pane table.sb2-table td.num { text-align:right; font-family:var(--mono); white-space:nowrap; }',
            '#sb2Pane table.sb2-table td.aks { text-align:right; white-space:nowrap; }',
            '#sb2Pane .sb2-prs { color:var(--text2); font-size:12px; }',
            '#sb2Pane .sb2-empty, #sb2Pane .sb2-loading, #sb2Pane .sb2-error { padding:32px; text-align:center; color:var(--text3); background:#fff; border-radius:8px; }',
            '#sb2Pane .sb2-error { color:#dc2626; }',
            '#sb2Pane .sb2-iconbtn { background:none; border:0; cursor:pointer; padding:4px 8px; font-size:14px; border-radius:4px; }',
            '#sb2Pane .sb2-iconbtn:hover { background:#f3f4f6; }',

            '#sb2Modal { position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:9999; display:none; align-items:center; justify-content:center; padding:20px; }',
            '#sb2Modal.acik { display:flex; }',
            '#sb2Modal .sb2-icerik { background:#fff; border-radius:12px; max-width:520px; width:100%; padding:22px 26px; }',
            '#sb2Modal h3 { margin:0 0 16px 0; font-size:16px; }',
            '#sb2Modal .fg { margin-bottom:14px; }',
            '#sb2Modal label { display:block; font-size:10px; font-weight:700; letter-spacing:0.6px; color:var(--text3); margin-bottom:5px; text-transform:uppercase; }',
            '#sb2Modal input, #sb2Modal textarea { width:100%; padding:9px 12px; border:1px solid var(--border); border-radius:6px; font-size:13px; box-sizing:border-box; font-family:inherit; outline:none; }',
            '#sb2Modal input:focus, #sb2Modal textarea:focus { border-color:var(--sol,#f97316); box-shadow:0 0 0 2px rgba(249,115,22,0.15); }',
            '#sb2Modal .ipucu { font-size:11px; color:var(--text3); margin-top:5px; }',
            '#sb2Modal .aksb { display:flex; gap:8px; justify-content:flex-end; margin-top:18px; }',
            '#sb2Modal button { padding:9px 18px; border-radius:6px; font-size:13px; font-weight:700; cursor:pointer; border:0; }',
            '#sb2Modal .iptal { background:#f3f4f6; color:var(--text2); }',
            '#sb2Modal .kaydet { background:var(--sol,#f97316); color:#fff; }',
            '#sb2Modal .hata { color:#dc2626; font-size:12px; margin-top:8px; display:none; }',
            '#sb2Modal .hata.gor { display:block; }'
        ].join('\n');
        document.head.appendChild(s);
    }

    // ---- Helpers ----
    function _esc(s) {
        if (s == null) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
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

    // ---- Pane'i bul (id="pane-sablon" garantisi) ----
    function _gercekPane() {
        var p = document.getElementById('pane-sablon');
        if (p) return p;
        // Fallback: data-pane="sablon" h-pane
        var alt = document.querySelectorAll('[data-pane="sablon"]');
        for (var i = 0; i < alt.length; i++) {
            if (alt[i].classList && alt[i].classList.contains('h-pane')) return alt[i];
        }
        return alt[0] || null;
    }

    // ---- Render: Pane kabugu ----
    function _renderKabuk() {
        var pane = _gercekPane();
        if (!pane) return null;

        // Eger zaten bizim sb2Pane var ise dokunmadan don
        if (pane.querySelector('#sb2Pane')) return pane.querySelector('#sb2Pane');

        // Eski icerigi tamamen sil
        while (pane.firstChild) pane.removeChild(pane.firstChild);

        // Yeni icerik
        var div = document.createElement('div');
        div.id = 'sb2Pane';
        div.innerHTML = [
            '<div class="sb2-bar">',
            '  <h3>📋 Şablon Yönetimi</h3>',
            '  <button class="sb2-ekle" id="sb2EkleBtn">+ YENİ ŞABLON</button>',
            '</div>',
            '<div id="sb2Liste"><div class="sb2-loading">Yükleniyor...</div></div>'
        ].join('\n');
        pane.appendChild(div);

        // Modal'i body'e ekle (z-index icin pane disinda)
        if (!document.getElementById('sb2Modal')) {
            var m = document.createElement('div');
            m.id = 'sb2Modal';
            m.innerHTML = '<div class="sb2-icerik" id="sb2ModalIcerik"></div>';
            document.body.appendChild(m);
            m.addEventListener('click', function (e) {
                if (e.target === m) _modalKapat();
            });
        }

        document.getElementById('sb2EkleBtn').addEventListener('click', function () {
            _modalAc(null);
        });

        return div;
    }

    // ---- Render: Liste ----
    function _renderListe() {
        var c = document.getElementById('sb2Liste');
        if (!c) return;
        var rows = _state.sablonlar || [];
        if (rows.length === 0) {
            c.innerHTML = '<div class="sb2-empty">Şablon bulunamadı.<br><br>Yukarıdan <strong>+ YENİ ŞABLON</strong> ile ekle.</div>';
            return;
        }

        var parts = ['<table class="sb2-table"><thead><tr>',
            '<th style="width:40px;">ID</th>',
            '<th>AD</th>',
            '<th>AÇIKLAMA</th>',
            '<th class="num" style="width:110px;">PROSES SAYISI</th>',
            '<th>PROSESLER</th>',
            '<th style="width:140px;">OLUŞTURMA</th>',
            '<th class="aks" style="width:90px;">İŞLEM</th>',
            '</tr></thead><tbody>'];

        rows.forEach(function (s) {
            var prsKisa = (s.prosesler || []).join(' → ');
            if (prsKisa.length > 80) prsKisa = prsKisa.substring(0, 80) + '...';
            parts.push('<tr>',
                '<td class="num">' + _esc(s.id) + '</td>',
                '<td><strong>' + _esc(s.sablon_adi) + '</strong></td>',
                '<td>' + _esc(s.aciklama || '-') + '</td>',
                '<td class="num"><strong>' + _esc(s.proses_sayisi) + '</strong></td>',
                '<td class="sb2-prs">' + _esc(prsKisa || '-') + '</td>',
                '<td style="font-family:var(--mono); font-size:11px; color:var(--text3);">' +
                  _esc(s.olusturma || '-') + '</td>',
                '<td class="aks">',
                '<button class="sb2-iconbtn" data-id="' + s.id + '" data-akt="duzenle" title="Düzenle">✏️</button>',
                '<button class="sb2-iconbtn" data-id="' + s.id + '" data-akt="sil" title="Sil">🗑️</button>',
                '</td></tr>');
        });
        parts.push('</tbody></table>');
        c.innerHTML = parts.join('');

        c.querySelectorAll('.sb2-iconbtn').forEach(function (b) {
            b.addEventListener('click', function () {
                var id = parseInt(b.dataset.id, 10);
                var rec = _state.sablonlar.find(function (x) { return x.id === id; });
                if (b.dataset.akt === 'duzenle') _modalAc(rec);
                else if (b.dataset.akt === 'sil') _sil(rec);
            });
        });
    }

    function _yukle() {
        var c = document.getElementById('sb2Liste');
        if (c) c.innerHTML = '<div class="sb2-loading">Yükleniyor...</div>';
        return _api('/hedef/sablon/liste').then(function (r) {
            if (r.status >= 400 || !r.data || r.data.ok === false) {
                if (c) c.innerHTML = '<div class="sb2-error">Şablon yüklenemedi.' +
                    (r.data && r.data.mesaj ? ' (' + _esc(r.data.mesaj) + ')' : '') + '</div>';
                return;
            }
            _state.sablonlar = (r.data && r.data.kayitlar) || [];
            _state.yuklendi = true;
            _renderListe();
            console.log('CPS/sablon/liste', r.status, _state.sablonlar.length);
        }).catch(function (e) {
            console.error('sablon liste fetch:', e);
            if (c) c.innerHTML = '<div class="sb2-error">Sunucuya ulaşılamadı.</div>';
        });
    }

    // ---- Modal ----
    function _modalKapat() {
        var m = document.getElementById('sb2Modal');
        if (m) m.classList.remove('acik');
    }
    function _modalAc(rec) {
        var rec0 = rec || { sablon_adi: '', aciklama: '', prosesler: [] };
        var prsStr = (rec0.prosesler || []).join(', ');
        var i = document.getElementById('sb2ModalIcerik');
        if (!i) return;
        i.innerHTML = [
            '<h3>' + (rec ? 'Şablon Düzenle' : 'Yeni Şablon') + '</h3>',
            '<div class="fg"><label>Şablon Adı</label>',
            '<input type="text" id="sb2Adi" value="' + _esc(rec0.sablon_adi) + '" placeholder="örn Atki LCW"></div>',
            '<div class="fg"><label>Açıklama (opsiyonel)</label>',
            '<textarea id="sb2Acik" rows="2">' + _esc(rec0.aciklama || '') + '</textarea></div>',
            '<div class="fg"><label>Prosesler (virgülle ayır, sıralı)</label>',
            '<textarea id="sb2Prs" rows="3" placeholder="Çapak, Rivet Takma, Tampon Baskı, Atkı Silme">' +
              _esc(prsStr) + '</textarea>',
            '<div class="ipucu">Sıra önemli — şablon uygulandığında bu sırayla emir_alt_proses\'e eklenir.</div></div>',
            '<div class="hata" id="sb2Hata"></div>',
            '<div class="aksb">',
            '<button class="iptal" id="sb2Iptal">İptal</button>',
            '<button class="kaydet" id="sb2Kaydet">Kaydet</button>',
            '</div>'
        ].join('\n');
        document.getElementById('sb2Modal').classList.add('acik');
        document.getElementById('sb2Iptal').addEventListener('click', _modalKapat);
        document.getElementById('sb2Kaydet').addEventListener('click', function () {
            _kaydet(rec);
        });
        setTimeout(function () { document.getElementById('sb2Adi').focus(); }, 50);
    }

    function _kaydet(rec) {
        var ad = (document.getElementById('sb2Adi').value || '').trim();
        var acik = (document.getElementById('sb2Acik').value || '').trim();
        var prsStr = (document.getElementById('sb2Prs').value || '').trim();
        var hata = document.getElementById('sb2Hata');
        hata.classList.remove('gor');

        if (!ad) {
            hata.textContent = 'Şablon adı zorunlu.';
            hata.classList.add('gor');
            return;
        }
        var prosesler = prsStr.split(',').map(function (x) { return x.trim(); })
            .filter(function (x) { return x; });
        if (prosesler.length === 0) {
            hata.textContent = 'En az 1 proses gerekli.';
            hata.classList.add('gor');
            return;
        }

        var url = rec ? '/hedef/sablon/guncelle/' + rec.id : '/hedef/sablon/ekle';
        _api(url, {
            method: 'POST',
            body: JSON.stringify({
                sablon_adi: ad,
                aciklama: acik || null,
                prosesler: prosesler
            })
        }).then(function (r) {
            if (r.status >= 400 || !r.data || r.data.ok === false) {
                hata.textContent = (r.data && r.data.mesaj) || ('HTTP ' + r.status);
                hata.classList.add('gor');
                return;
            }
            _modalKapat();
            _yukle();
        }).catch(function (e) {
            hata.textContent = 'Sunucuya ulaşılamadı: ' + e.message;
            hata.classList.add('gor');
        });
    }

    function _sil(rec) {
        if (!rec) return;
        if (!confirm('Bu şablonu silmek istiyor musun?\n"' + rec.sablon_adi + '"')) return;
        _api('/hedef/sablon/sil/' + rec.id, { method: 'POST' }).then(function (r) {
            if (r.data && r.data.ok) {
                _yukle();
            } else {
                alert((r.data && r.data.mesaj) || 'Silme başarısız');
            }
        });
    }

    // ---- Tetikleme ----
    function _hazirla() {
        _renderKabuk();
        if (!_state.yuklendi) _yukle();
    }

    var sablonTab = document.querySelector('.h-tab[data-tab="sablon"]');
    if (sablonTab) {
        sablonTab.addEventListener('click', function () {
            setTimeout(_hazirla, 80);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            // Sayfa acilinca eger sablon tab aktif ise hemen render
            var aktTab = document.querySelector('.h-tab.active[data-tab="sablon"]');
            if (aktTab) setTimeout(_hazirla, 200);
        });
    } else {
        var aktTab = document.querySelector('.h-tab.active[data-tab="sablon"]');
        if (aktTab) setTimeout(_hazirla, 100);
    }

    // Disardan tetiklemek icin
    window.sb2Yukle = _yukle;
    window.sb2Hazirla = _hazirla;

    console.log('[CPS LOCAL] FAZ 4.6 B2 sablon UI yuklendi.');
})();
'''


def main():
    print("=" * 64)
    print("FAZ 4.6 B2 - Sablon UI (frontend)")
    print("=" * 64)
    print("Backend B1 zaten yazılı.")
    print("Bu adim sadece JS ekler.")

    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} bulunamadi.")
        return 1

    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if JS_MARKER in src:
        print("  [BILGI] B2 zaten ekli.")
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
    print("  [OK] B2 sablon UI IIFE eklendi.")
    print()
    print("YAPILACAK:")
    print("  1) Browser'da Ctrl+F5 (sunucu restart gerekmez, sadece JS)")
    print("  2) /hedef/ -> SABLON sekmesi")
    print()
    print("Beklenen:")
    print("  - 'UI.3 asamasinda' yazisi GITTI")
    print("  - 'Sablon Yonetimi' basligi + '+ YENI SABLON' butonu")
    print("  - Tablo: ID | AD | ACIKLAMA | PROSES SAYISI | PROSESLER | TARIH | ISLEM")
    print("  - Test 3'te ekledigin 'Atki LCW' satirin gozukmeli (id=1, 4 proses)")
    print()
    print("Test:")
    print("  - + YENI SABLON tikla")
    print("  - Ad: 'Govde Standart'")
    print("  - Prosesler: 'Capak, Govde Silme, Kalip Koyma'")
    print("  - Kaydet -> liste yenilenir, 2. satir gorunur")
    print()
    print("  - Sil butonuna tikla -> confirm -> siler")
    print()
    print("Console:")
    print("  [CPS LOCAL] FAZ 4.6 B2 sablon UI yuklendi.")
    print("  CPS/sablon/liste 200 N")
    return 0


if __name__ == '__main__':
    sys.exit(main())
