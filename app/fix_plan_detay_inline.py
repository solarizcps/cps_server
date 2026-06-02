# -*- coding: utf-8 -*-
"""
fix_plan_detay_inline.py
------------------------
PLAN detay paneli sagdan slide-in -> inline expand (accordion) cevir.

DEGISEN:
  - Sadece static/js/hedef.js
  - Onceki PLAN_DETAY_V1 IIFE'sini eski hale degil tamamen yeni
    PLAN_DETAY_INLINE_V2 IIFE'siyle override eder.
  - Eski sag panel DOM'da olusmaz (eski IIFE _ensureDom cagrilmadigi
    surece zararsiz, ama yine de eski class temizlenir).

DOKUNULMAZ:
  - Backend endpoint /hedef/plan-detay (aynen)
  - DB
  - PLAN tablosu HTML
  - Diger sekmeler
"""
import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

JS_MARKER = "[CPS LOCAL] PLAN detay inline v2 yuklendi"


# ====================================================================
# Yeni IIFE - eski sag paneli pasif eder, inline expand ekler
# ====================================================================
JS_BLOCK = r'''


/* ====================================================================
   CPS LOCAL - PLAN DETAY INLINE v2
   - Sag panel YOK
   - PLAN sat\u0131r\u0131na t\u0131klay\u0131nca alt\u0131nda yeni <tr> olarak detay a\u00e7\u0131l\u0131r
   - Ayn\u0131 sat\u0131ra tekrar t\u0131kla -> kapan\u0131r
   - Ba\u015fka sat\u0131ra t\u0131kla -> eski kapan\u0131r, yeni a\u00e7\u0131l\u0131r
   - ESC -> kapat\u0131r
   ==================================================================== */
(function () {
    'use strict';

    var STYLE_ID = 'plan-detay-inline-style';
    var aktifEmir = null;
    var loading = false;
    var TOPLAM_KOLON = 11;

    // Eski sag panel ve backdrop (varsa) gizle
    function _eskiPaneliGizle() {
        var p = document.getElementById('plan-detay-panel');
        var bk = document.getElementById('plan-detay-backdrop');
        if (p) { p.style.display = 'none'; p.classList.remove('acik'); }
        if (bk) { bk.style.display = 'none'; bk.classList.remove('acik'); }
    }

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

    function _ensureStyle() {
        if (document.getElementById(STYLE_ID)) return;
        var st = document.createElement('style');
        st.id = STYLE_ID;
        st.textContent = '' +
            '#planBody tr.plan-row {cursor:pointer;transition:background 0.12s;}' +
            '#planBody tr.plan-row:hover {background:rgba(249,115,22,0.04);}' +
            '#planBody tr.plan-row.acik {background:rgba(249,115,22,0.08);}' +
            '#planBody tr.plan-detay-row {background:#fafafa;}' +
            '#planBody tr.plan-detay-row > td {' +
                'padding:0;border-bottom:2px solid #f97316;' +
            '}' +
            '.plan-detay-icerik {' +
                'padding:18px 22px;animation:planDetayAc 0.18s ease-out;' +
            '}' +
            '@keyframes planDetayAc {' +
                'from {opacity:0;transform:translateY(-4px);}' +
                'to {opacity:1;transform:translateY(0);}' +
            '}' +
            '.pdi-meta {' +
                'display:grid;grid-template-columns:repeat(6,1fr);gap:14px;' +
                'padding:14px 16px;background:#fff;border-radius:8px;' +
                'border:1px solid #e5e7eb;margin-bottom:14px;' +
            '}' +
            '.pdi-meta-item {display:flex;flex-direction:column;}' +
            '.pdi-meta-item .label {' +
                'font-size:9px;color:#9ca3af;text-transform:uppercase;' +
                'letter-spacing:0.5px;font-weight:700;margin-bottom:3px;' +
            '}' +
            '.pdi-meta-item .val {font-size:13px;color:#111827;font-weight:600;}' +
            '.pdi-meta-item .val.mono {font-family:var(--mono,monospace);font-size:12px;}' +
            '.pdi-yuzde-pill {' +
                'display:inline-block;padding:1px 7px;border-radius:8px;' +
                'font-size:10px;font-weight:700;color:#fff;margin-left:4px;' +
            '}' +
            '.pdi-baslik {' +
                'font-size:10px;font-weight:700;color:#9ca3af;' +
                'text-transform:uppercase;letter-spacing:0.7px;' +
                'margin:6px 0 8px 0;' +
            '}' +
            '.pdi-proses-grid {' +
                'display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));' +
                'gap:8px;' +
            '}' +
            '.pdi-proses {' +
                'border:1px solid #e5e7eb;border-radius:8px;' +
                'padding:10px 12px;background:#fff;' +
            '}' +
            '.pdi-proses.aktif {border-color:#f97316;background:rgba(249,115,22,0.04);}' +
            '.pdi-proses.tamam {border-color:#10b981;background:rgba(16,185,129,0.04);}' +
            '.pdi-proses-head {' +
                'display:flex;align-items:center;gap:8px;margin-bottom:5px;' +
            '}' +
            '.pdi-ikon {' +
                'width:22px;height:22px;border-radius:6px;font-size:11px;' +
                'display:inline-flex;align-items:center;justify-content:center;' +
                'flex-shrink:0;font-weight:700;' +
            '}' +
            '.pdi-proses-adi {' +
                'flex:1;font-size:13px;font-weight:600;color:#111827;' +
            '}' +
            '.pdi-rozet {' +
                'font-size:9px;font-weight:700;text-transform:uppercase;' +
                'padding:1px 6px;border-radius:6px;color:#fff;' +
            '}' +
            '.pdi-bar-wrap {' +
                'height:4px;background:#f3f4f6;border-radius:2px;overflow:hidden;' +
                'margin:4px 0;' +
            '}' +
            '.pdi-bar {height:100%;border-radius:2px;transition:width 0.3s;}' +
            '.pdi-detay {' +
                'display:flex;justify-content:space-between;font-size:11px;' +
                'color:#6b7280;font-family:var(--mono,monospace);' +
            '}' +
            '.pdi-empty,.pdi-loading,.pdi-error {' +
                'text-align:center;padding:24px;font-size:13px;' +
            '}' +
            '.pdi-loading {color:#9ca3af;}' +
            '.pdi-empty {color:#9ca3af;}' +
            '.pdi-error {color:#dc2626;}' +
            '';
        document.head.appendChild(st);
    }

    function _terminGosterim(termIso) {
        if (!termIso) return '<span style="color:#9ca3af;">-</span>';
        var t = new Date(termIso);
        if (isNaN(t.getTime())) return '<span style="color:#9ca3af;">-</span>';
        var bugun = new Date(); bugun.setHours(0, 0, 0, 0);
        var hedef = new Date(t.getFullYear(), t.getMonth(), t.getDate());
        var fark = Math.round((hedef - bugun) / 86400000);
        var renk = '#10b981';
        var etiket = fark + ' gün';
        if (fark < 0) { renk = '#dc2626'; etiket = Math.abs(fark) + ' gün geçti'; }
        else if (fark === 0) { renk = '#dc2626'; etiket = 'Bugün'; }
        else if (fark <= 7) renk = '#dc2626';
        else if (fark <= 30) renk = '#f59e0b';
        var str = String(t.getFullYear()) + '-' +
            String(t.getMonth() + 1).padStart(2, '0') + '-' +
            String(t.getDate()).padStart(2, '0');
        return _esc(str) + ' <span class="pdi-yuzde-pill" style="background:' +
            renk + ';">' + etiket + '</span>';
    }

    function _detayHtml(d) {
        var hedef = Number(d.hedef || 0);
        var yapilan = Number(d.yapilan || 0);
        var yuzde = hedef > 0 ? Math.round((yapilan / hedef) * 1000) / 10 : 0;
        var yrenk = '#dc2626';
        if (yuzde >= 70) yrenk = '#10b981';
        else if (yuzde >= 30) yrenk = '#f59e0b';
        var sipsTxt = '-';
        if (Array.isArray(d.siparisler) && d.siparisler.length) {
            sipsTxt = d.siparisler.map(function (s) { return s.sip_no; }).join(', ');
        }

        var html = '<div class="plan-detay-icerik">';

        // META BLOCK
        html += '<div class="pdi-meta">' +
            '<div class="pdi-meta-item">' +
                '<span class="label">Sipariş</span>' +
                '<span class="val mono">' + _esc(sipsTxt) + '</span>' +
            '</div>' +
            '<div class="pdi-meta-item">' +
                '<span class="label">Müşteri</span>' +
                '<span class="val">' + _esc(d.musteri || '-') + '</span>' +
            '</div>' +
            '<div class="pdi-meta-item" style="grid-column:span 2;">' +
                '<span class="label">Model</span>' +
                '<span class="val" title="' + _esc(d.model_adi || '') + '" ' +
                'style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' +
                _esc(d.model_adi || d.model_kod || '-') + '</span>' +
            '</div>' +
            '<div class="pdi-meta-item">' +
                '<span class="label">Termin</span>' +
                '<span class="val">' + _terminGosterim(d.termin) + '</span>' +
            '</div>' +
            '<div class="pdi-meta-item">' +
                '<span class="label">Lokasyon</span>' +
                '<span class="val mono">' + _esc(d.location || '-') + '</span>' +
            '</div>' +
            '<div class="pdi-meta-item">' +
                '<span class="label">Hedef</span>' +
                '<span class="val">' + _fmt(hedef) + '</span>' +
            '</div>' +
            '<div class="pdi-meta-item">' +
                '<span class="label">Yapılan</span>' +
                '<span class="val">' + _fmt(yapilan) +
                ' <span class="pdi-yuzde-pill" style="background:' + yrenk +
                ';">' + yuzde + '%</span></span>' +
            '</div>' +
            '<div class="pdi-meta-item">' +
                '<span class="label">Kalan</span>' +
                '<span class="val">' + _fmt(d.kalan || 0) + '</span>' +
            '</div>' +
            '<div class="pdi-meta-item">' +
                '<span class="label">Tip</span>' +
                '<span class="val">' + _esc(d.tip_aciklama || d.tip || '-') +
                '</span>' +
            '</div>' +
        '</div>';

        // PROSES LISTE
        var lst = (d.proses_listesi || []).slice();
        // Frontend siralama: proses_kod numerik artan
        lst.sort(function (a, b) {
            var na = parseInt(a.proses_kod, 10);
            var nb = parseInt(b.proses_kod, 10);
            if (isNaN(na)) na = 9999;
            if (isNaN(nb)) nb = 9999;
            return na - nb;
        });

        html += '<div class="pdi-baslik">ÜRETİM AKIŞI ' +
            (lst.length ? '(' + lst.length + ' proses)' : '') + '</div>';

        if (lst.length === 0) {
            html += '<div class="pdi-empty">Henüz proses kaydı yok.</div>';
        } else {
            var aktifKod = d.aktif_proses_kod;
            html += '<div class="pdi-proses-grid">';
            for (var i = 0; i < lst.length; i++) {
                var p = lst[i];
                var aktif = (p.proses_kod === aktifKod);
                var cls = 'pdi-proses';
                if (aktif) cls += ' aktif';
                else if (p.durum === 'tamam') cls += ' tamam';

                var ikonRenk = '#9ca3af', ikonBg = '#f3f4f6', ikonText = '⏳';
                var rozetRenk = '#6b7280';
                if (p.durum === 'tamam') {
                    ikonRenk = '#fff'; ikonBg = '#10b981'; ikonText = '\u2713';
                    rozetRenk = '#10b981';
                } else if (p.durum === 'devam') {
                    ikonRenk = '#fff'; ikonBg = '#f97316'; ikonText = '\u25CF';
                    rozetRenk = '#f97316';
                }
                var bar = Math.min(100, p.yuzde || 0);
                var barRenk = (p.durum === 'tamam' ? '#10b981' : '#f97316');

                var sonTxt = '';
                if (p.son_tarih) {
                    var t = new Date(p.son_tarih);
                    if (!isNaN(t.getTime())) {
                        var fark = Math.round((Date.now() - t.getTime()) / 86400000);
                        if (fark === 0) sonTxt = 'bugün';
                        else if (fark === 1) sonTxt = 'dün';
                        else if (fark > 0) sonTxt = fark + ' gün önce';
                    }
                }

                html += '<div class="' + cls + '">' +
                    '<div class="pdi-proses-head">' +
                        '<span class="pdi-ikon" style="background:' + ikonBg +
                        ';color:' + ikonRenk + ';">' + ikonText + '</span>' +
                        '<span class="pdi-proses-adi">' +
                        _esc(p.proses_adi || p.proses_kod) +
                        ' <span style="font-size:10px;color:#9ca3af;font-weight:400;">[' +
                        _esc(p.proses_kod) + ']</span></span>' +
                        '<span class="pdi-rozet" style="background:' + rozetRenk +
                        ';">' + (aktif ? 'AKTİF' : (p.durum || '').toUpperCase()) +
                        '</span>' +
                    '</div>' +
                    '<div class="pdi-bar-wrap"><div class="pdi-bar" ' +
                        'style="width:' + bar + '%;background:' + barRenk + ';"></div></div>' +
                    '<div class="pdi-detay">' +
                        '<span>' + _fmt(p.yapilan) + ' / ' + _fmt(p.toplam_hedef) +
                        ' (' + p.yuzde + '%)</span>' +
                        '<span>' + (sonTxt ? 'Son: ' + sonTxt : '') + '</span>' +
                    '</div>' +
                '</div>';
            }
            html += '</div>';
        }

        html += '</div>';  // .plan-detay-icerik
        return html;
    }

    function _kapat() {
        var detayTr = document.querySelector('#planBody tr.plan-detay-row');
        if (detayTr) detayTr.parentNode.removeChild(detayTr);
        var aktifTr = document.querySelector('#planBody tr.plan-row.acik');
        if (aktifTr) aktifTr.classList.remove('acik');
        aktifEmir = null;
    }

    function _ac(emirNo, srcTr) {
        if (loading) return;
        // Aynı satıra tekrar tikla = kapat
        if (aktifEmir === String(emirNo)) {
            _kapat();
            return;
        }
        // Eski varsa kapat
        _kapat();

        loading = true;
        aktifEmir = String(emirNo);
        srcTr.classList.add('acik');

        // Loading row ekle
        var ld = document.createElement('tr');
        ld.className = 'plan-detay-row';
        ld.dataset.detayFor = emirNo;
        ld.innerHTML = '<td colspan="' + TOPLAM_KOLON + '">' +
            '<div class="plan-detay-icerik"><div class="pdi-loading">' +
            'Yükleniyor...</div></div></td>';
        srcTr.parentNode.insertBefore(ld, srcTr.nextSibling);

        fetch('/hedef/plan-detay/' + encodeURIComponent(emirNo), {
            credentials: 'include'
        })
            .then(function (r) {
                return r.json().then(function (d) {
                    return { status: r.status, data: d };
                });
            })
            .then(function (r) {
                loading = false;
                var td = ld.querySelector('td');
                if (!td) return;
                if (r.status >= 400 || !r.data || !r.data.ok) {
                    td.innerHTML = '<div class="plan-detay-icerik">' +
                        '<div class="pdi-error">' +
                        _esc((r.data && r.data.mesaj) || 'Veri alınamadı') +
                        '</div></div>';
                    return;
                }
                td.innerHTML = _detayHtml(r.data);
            })
            .catch(function (e) {
                loading = false;
                var td = ld.querySelector('td');
                if (td) {
                    td.innerHTML = '<div class="plan-detay-icerik">' +
                        '<div class="pdi-error">Sunucuya ulaşılamadı: ' +
                        _esc(e.message) + '</div></div>';
                }
            });
    }

    // Eski sag paneli pasif et
    _eskiPaneliGizle();
    _ensureStyle();

    // Click delegation
    document.addEventListener('click', function (ev) {
        if (ev.target.closest('button, a, input, select, .tab-x')) return;
        // Detay row icine tiklandiysa kapatma
        if (ev.target.closest('#planBody tr.plan-detay-row')) return;
        var tr = ev.target.closest('#planBody tr');
        if (!tr) return;
        if (tr.classList.contains('plan-detay-row')) return;
        var en = tr.dataset.emirNo;
        if (!en) {
            var ilkTd = tr.querySelector('td:nth-child(2)');
            if (ilkTd) {
                var m = (ilkTd.textContent || '').match(/(\d+)/);
                if (m) en = m[1];
            }
        }
        if (!en) return;
        _ac(en, tr);
    }, false);

    // ESC ile kapat
    document.addEventListener('keydown', function (ev) {
        if (ev.key === 'Escape') _kapat();
    });

    // Yeniden render olunca eski detay row'unu kaybeder; tekrar acmak ozel logic
    // gerek yok, kullanici tekrar tiklar.

    // renderPlanRows monkey-patch (data-emir-no varsa zaten v1'de eklendi,
    // burada double koruma)
    if (typeof window.renderPlanRows === 'function' && !window._origRenderRowsV2) {
        window._origRenderRowsV2 = window.renderPlanRows;
        window.renderPlanRows = function (emirler) {
            // Render once detay'i kapat
            _kapat();
            var ret = window._origRenderRowsV2.apply(this, arguments);
            // Render sonrasi dataset.emirNo + plan-row class
            var rows = document.querySelectorAll('#planBody tr');
            for (var i = 0; i < rows.length; i++) {
                var tr = rows[i];
                if (tr.classList.contains('plan-detay-row')) continue;
                if (tr.dataset.emirNo) {
                    tr.classList.add('plan-row');
                    continue;
                }
                var ilkTd = tr.querySelector('td:nth-child(2)');
                if (ilkTd) {
                    var m = (ilkTd.textContent || '').match(/(\d+)/);
                    if (m) {
                        tr.dataset.emirNo = m[1];
                        tr.classList.add('plan-row');
                    }
                }
            }
            return ret;
        };
    }

    console.log('[CPS LOCAL] PLAN detay inline v2 yuklendi');
})();
'''


def main():
    if not os.path.exists(JS_PATH):
        print(f"[HATA] {JS_PATH} yok.")
        return 1

    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if JS_MARKER in src:
        print("[BILGI] inline v2 zaten ekli.")
        return 0

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += JS_BLOCK

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = JS_PATH + f'.bak_{ts}'
    shutil.copy2(JS_PATH, bp)
    print(f"[OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("[OK] PLAN detay inline v2 IIFE eklendi.")
    print()
    print("YAPILACAK: Browser Ctrl+F5")
    print()
    print("BEKLENEN:")
    print("  - PLAN sat\u0131r\u0131na t\u0131kla -> alt\u0131nda detay a\u00e7\u0131l\u0131r")
    print("  - Sa\u011fdan slide-in panel art\u0131k a\u00e7\u0131lmaz (gizli)")
    print("  - Ayni satira tekrar t\u0131kla -> kapan\u0131r")
    print("  - Ba\u015fka satira t\u0131kla -> eski kapan\u0131r, yeni a\u00e7\u0131l\u0131r")
    print("  - ESC -> kapat\u0131r")
    print()
    print("ROLLBACK:")
    print(f'  copy "{bp}" "{JS_PATH}"')
    return 0


if __name__ == '__main__':
    sys.exit(main())
