# -*- coding: utf-8 -*-
"""
setup_plan_detay_panel.py
-------------------------
PLAN ekraninda satira tiklayinca SAGDAN slide-in panel acar.

ENDPOINT:
  GET /hedef/plan-detay/<int:emir_no> (read-only)
    - get_emir_ozet ile temel bilgiler
    - Urt_con_gch + Proses_M batch SQL ile proses_listesi
    - aktif_proses = ORDER BY EndTarih DESC ilk kayit
    - proses_listesi siralamasi backend: EndTarih DESC
    - frontend: proses_kod numerik artan siralayacak

FRONTEND:
  hedef.js sonuna IIFE - click delegation + slide-in panel
  inline CSS, mevcut HTML dokunulmaz

CPS_KURALLAR:
  - Korgun read-only
  - Yeni write yok
  - DB dokunulmaz
  - PLAN/SABLON/SAPMA/ONAYLAR/GECMIS bozulmaz
"""
import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
HEDEF_ROUTES = os.path.join(CPS_ROOT, "modules", "hedef", "routes.py")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

ROUTES_MARKER = "# === PLAN_DETAY_V1 endpoint ==="
JS_MARKER = "[CPS LOCAL] PLAN detay panel v1 yuklendi"


# ====================================================================
# 1) BACKEND - yeni endpoint (mevcut routes.py sonuna eklenir)
# ====================================================================
ROUTES_BLOCK = '''


# === PLAN_DETAY_V1 endpoint ===
# GET /hedef/plan-detay/<emir_no> - Read-only emir detay paneli
# Veri kaynaklari: get_emir_ozet + Urt_con_gch + Proses_M
@hedef_bp.route('/plan-detay/<int:emir_no>', methods=['GET'])
@hedef_yetkili
def hedef_plan_detay(emir_no):
    """Read-only emir detay - PLAN ekraninda slide-in panel icin."""
    from flask import jsonify
    from modules.common import korgun as _kk_pd

    try:
        ozet = _kk_pd.get_emir_ozet(emir_no)
    except Exception as e:
        return jsonify({
            'ok': False,
            'mesaj': 'Korgun erisilemiyor: ' + str(e)[:120]
        }), 500

    if not ozet or not ozet.get('ok'):
        return jsonify({
            'ok': False,
            'mesaj': 'Emir bulunamadi',
            'kod': 'EMIR_YOK'
        }), 404

    # Proses listesi - tek SQL
    proses_listesi = []
    aktif_proses_kod = None
    aktif_proses_adi = None
    hedef_toplam = int(ozet.get('hedef_adet', 0) or 0)

    try:
        con = _kk_pd._baglan()
        try:
            cur = con.cursor()
            cur.execute("""
                SELECT
                    g.Proses,
                    pm.Tanim,
                    SUM(g.Cikan) AS yapilan,
                    MAX(g.EndTarih) AS son_tarih,
                    COUNT(*) AS kayit
                  FROM Urt_con_gch g WITH(NOLOCK)
                  LEFT JOIN Proses_M pm WITH(NOLOCK) ON pm.Pro = g.Proses
                 WHERE g.EmirNo = %s
                   AND g.Cikan > 0
                 GROUP BY g.Proses, pm.Tanim
                 ORDER BY MAX(g.EndTarih) DESC
            """, (emir_no,))
            rows = cur.fetchall()
            for i, r in enumerate(rows):
                kod = r[0]
                adi = r[1] or kod
                yapilan = float(r[2] or 0)
                son_tarih = r[3]
                kayit = int(r[4] or 0)
                if hedef_toplam > 0:
                    yuzde = round((yapilan / hedef_toplam) * 100, 1)
                else:
                    yuzde = 0.0
                if yuzde >= 100:
                    durum = 'tamam'
                elif yuzde > 0:
                    durum = 'devam'
                else:
                    durum = 'bekliyor'
                proses_listesi.append({
                    'proses_kod': kod,
                    'proses_adi': adi,
                    'yapilan': int(yapilan),
                    'toplam_hedef': hedef_toplam,
                    'yuzde': yuzde,
                    'durum': durum,
                    'son_tarih': son_tarih.isoformat() if son_tarih else None,
                    'kayit_sayisi': kayit,
                })
                # Aktif proses = ilk kayit (ORDER BY EndTarih DESC)
                if i == 0:
                    aktif_proses_kod = kod
                    aktif_proses_adi = adi
            cur.close()
        finally:
            con.close()
    except Exception as e:
        try:
            print(f'[PLAN_DETAY_V1 hata, proses_listesi bos]: {e}')
        except Exception:
            pass
        proses_listesi = []

    return jsonify({
        'ok': True,
        'emir_no': emir_no,
        'model_kod': ozet.get('model_kod'),
        'model_adi': ozet.get('model_adi'),
        'musteri': ozet.get('cari_adi'),
        'termin': ozet.get('termin_tarihi'),
        'tip': ozet.get('tip'),
        'tip_aciklama': ozet.get('tip_aciklama'),
        'location': ozet.get('location'),
        'hedef': hedef_toplam,
        'yapilan': int(ozet.get('yapilan_adet', 0) or 0),
        'kalan': int(ozet.get('kalan_adet', 0) or 0),
        'siparisler': ozet.get('siparisler', []),
        'proses_listesi': proses_listesi,
        'aktif_proses_kod': aktif_proses_kod,
        'aktif_proses': aktif_proses_adi,
    })
'''


# ====================================================================
# 2) FRONTEND - hedef.js sonuna IIFE
# ====================================================================
JS_BLOCK = r'''


/* ====================================================================
   CPS LOCAL - PLAN DETAY PANEL v1
   - PLAN tablosu satirina tiklayinca sagdan slide-in panel
   - Read-only, hicbir buton/write yok
   - ESC, X, dis tikla, ayni satira tekrar tikla = kapat
   - Proses listesi: backend EndTarih DESC veriyor, frontend
     proses_kod numerik artan siraliyor (02, 15, 30...)
   ==================================================================== */
(function () {
    'use strict';

    var PANEL_ID = 'plan-detay-panel';
    var BACKDROP_ID = 'plan-detay-backdrop';
    var STYLE_ID = 'plan-detay-style';
    var loading = false;
    var aktifEmirNo = null;

    var DEFAULT_IKON =
        'data:image/svg+xml;utf8,' +
        encodeURIComponent(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" ' +
            'fill="none" stroke="#9ca3af" stroke-width="1.5" stroke-linecap="round" ' +
            'stroke-linejoin="round">' +
            '<rect x="3" y="3" width="18" height="18" rx="2"/>' +
            '<circle cx="9" cy="9" r="2"/>' +
            '<path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>' +
            '</svg>'
        );

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
            '#' + BACKDROP_ID + ' {' +
                'position:fixed;top:0;left:0;right:0;bottom:0;' +
                'background:rgba(0,0,0,0.18);z-index:9000;' +
                'opacity:0;pointer-events:none;transition:opacity 0.18s;' +
            '}' +
            '#' + BACKDROP_ID + '.acik {opacity:1;pointer-events:auto;}' +
            '#' + PANEL_ID + ' {' +
                'position:fixed;top:0;right:0;bottom:0;width:520px;max-width:92vw;' +
                'background:#fff;box-shadow:-8px 0 32px rgba(0,0,0,0.12);' +
                'z-index:9100;transform:translateX(100%);' +
                'transition:transform 0.22s ease-out;display:flex;flex-direction:column;' +
                'font-family:var(--font,system-ui);' +
            '}' +
            '#' + PANEL_ID + '.acik {transform:translateX(0);}' +
            '#' + PANEL_ID + ' .pdp-head {' +
                'padding:16px 18px;border-bottom:1px solid #e5e7eb;' +
                'display:flex;align-items:flex-start;gap:14px;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-head img {' +
                'width:54px;height:54px;border-radius:8px;' +
                'object-fit:cover;background:#f3f4f6;flex-shrink:0;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-head .pdp-info {flex:1;min-width:0;}' +
            '#' + PANEL_ID + ' .pdp-emir {' +
                'font-size:14px;font-weight:700;color:#111827;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-model {' +
                'font-size:12px;color:#6b7280;margin-top:2px;' +
                'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-musteri {' +
                'font-size:13px;color:#3b82f6;font-weight:600;margin-top:4px;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-close {' +
                'background:#f3f4f6;border:none;width:32px;height:32px;' +
                'border-radius:8px;cursor:pointer;font-size:18px;' +
                'display:flex;align-items:center;justify-content:center;' +
                'color:#6b7280;flex-shrink:0;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-close:hover {background:#fee2e2;color:#dc2626;}' +
            '#' + PANEL_ID + ' .pdp-meta {' +
                'padding:14px 18px;border-bottom:1px solid #e5e7eb;' +
                'display:grid;grid-template-columns:1fr 1fr;gap:10px;font-size:12px;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-meta-item {display:flex;flex-direction:column;}' +
            '#' + PANEL_ID + ' .pdp-meta-item .label {' +
                'font-size:10px;color:#9ca3af;text-transform:uppercase;' +
                'letter-spacing:0.5px;font-weight:600;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-meta-item .val {' +
                'font-size:13px;color:#111827;font-weight:600;margin-top:2px;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-yuzde {' +
                'display:inline-block;padding:2px 10px;border-radius:12px;' +
                'font-size:11px;font-weight:700;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-body {' +
                'flex:1;overflow-y:auto;padding:16px 18px;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-body h4 {' +
                'font-size:11px;color:#9ca3af;text-transform:uppercase;' +
                'letter-spacing:0.6px;font-weight:700;margin:0 0 12px 0;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-proses {' +
                'border:1px solid #e5e7eb;border-radius:8px;' +
                'padding:10px 12px;margin-bottom:8px;' +
                'transition:background 0.12s;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-proses.aktif {' +
                'border-color:#f97316;background:rgba(249,115,22,0.06);' +
            '}' +
            '#' + PANEL_ID + ' .pdp-proses.tamam {' +
                'border-color:#10b981;background:rgba(16,185,129,0.04);' +
            '}' +
            '#' + PANEL_ID + ' .pdp-proses-head {' +
                'display:flex;align-items:center;gap:8px;margin-bottom:6px;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-proses-ikon {' +
                'width:22px;height:22px;border-radius:6px;font-size:11px;' +
                'display:inline-flex;align-items:center;justify-content:center;' +
                'flex-shrink:0;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-proses-adi {' +
                'flex:1;font-size:13px;font-weight:600;color:#111827;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-proses-rozet {' +
                'font-size:9px;font-weight:700;text-transform:uppercase;' +
                'padding:1px 6px;border-radius:6px;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-proses-bar-wrap {' +
                'height:4px;background:#f3f4f6;border-radius:2px;overflow:hidden;' +
                'margin:4px 0;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-proses-bar {' +
                'height:100%;border-radius:2px;transition:width 0.3s;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-proses-detay {' +
                'display:flex;justify-content:space-between;font-size:11px;' +
                'color:#6b7280;margin-top:4px;font-family:var(--mono,monospace);' +
            '}' +
            '#' + PANEL_ID + ' .pdp-loading,#' + PANEL_ID + ' .pdp-empty {' +
                'text-align:center;padding:40px;color:#9ca3af;font-size:13px;' +
            '}' +
            '#' + PANEL_ID + ' .pdp-error {' +
                'text-align:center;padding:40px;color:#dc2626;font-size:13px;' +
            '}' +
            '#planBody tr.plan-row {cursor:pointer;}' +
            '#planBody tr.plan-row:hover {background:rgba(249,115,22,0.04);}' +
            '';
        document.head.appendChild(st);
    }

    function _ensureDom() {
        _ensureStyle();
        if (document.getElementById(PANEL_ID)) return;
        var bk = document.createElement('div');
        bk.id = BACKDROP_ID;
        document.body.appendChild(bk);
        var p = document.createElement('div');
        p.id = PANEL_ID;
        p.innerHTML = '<div class="pdp-head"></div>' +
                      '<div class="pdp-meta"></div>' +
                      '<div class="pdp-body"></div>';
        document.body.appendChild(p);

        bk.addEventListener('click', _kapat);
        document.addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape') _kapat();
        });
    }

    function _kapat() {
        var p = document.getElementById(PANEL_ID);
        var bk = document.getElementById(BACKDROP_ID);
        if (p) p.classList.remove('acik');
        if (bk) bk.classList.remove('acik');
        aktifEmirNo = null;
    }

    function _ac() {
        _ensureDom();
        document.getElementById(PANEL_ID).classList.add('acik');
        document.getElementById(BACKDROP_ID).classList.add('acik');
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
        return _esc(str) +
            '<br><span style="display:inline-block;background:' + renk +
            ';color:#fff;padding:1px 6px;border-radius:8px;' +
            'font-size:9px;font-weight:700;margin-top:2px;">' + etiket + '</span>';
    }

    function _renderHead(d) {
        var head = document.querySelector('#' + PANEL_ID + ' .pdp-head');
        if (!head) return;
        head.innerHTML = '<img src="' + DEFAULT_IKON + '" alt="">' +
            '<div class="pdp-info">' +
                '<div class="pdp-emir">E.' + _esc(d.emir_no) + '</div>' +
                '<div class="pdp-model" title="' + _esc(d.model_adi || d.model_kod || '') + '">' +
                    _esc(d.model_adi || d.model_kod || '-') + '</div>' +
                '<div class="pdp-musteri">' + _esc(d.musteri || '-') + '</div>' +
            '</div>' +
            '<button class="pdp-close" type="button" title="Kapat">×</button>';
        var btn = head.querySelector('.pdp-close');
        if (btn) btn.addEventListener('click', _kapat);
    }

    function _renderMeta(d) {
        var meta = document.querySelector('#' + PANEL_ID + ' .pdp-meta');
        if (!meta) return;
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
        meta.innerHTML =
            '<div class="pdp-meta-item"><span class="label">Sipariş</span>' +
                '<span class="val" style="font-family:var(--mono,monospace);font-size:12px;">' +
                _esc(sipsTxt) + '</span></div>' +
            '<div class="pdp-meta-item"><span class="label">Termin</span>' +
                '<span class="val">' + _terminGosterim(d.termin) + '</span></div>' +
            '<div class="pdp-meta-item"><span class="label">Hedef</span>' +
                '<span class="val">' + _fmt(hedef) + ' çift</span></div>' +
            '<div class="pdp-meta-item"><span class="label">Yapılan</span>' +
                '<span class="val">' + _fmt(yapilan) +
                ' <span class="pdp-yuzde" style="background:' + yrenk +
                ';color:#fff;">' + yuzde + '%</span></span></div>' +
            '<div class="pdp-meta-item"><span class="label">Kalan</span>' +
                '<span class="val">' + _fmt(d.kalan || 0) + ' çift</span></div>' +
            '<div class="pdp-meta-item"><span class="label">Lokasyon</span>' +
                '<span class="val" style="font-family:var(--mono,monospace);font-size:12px;">' +
                _esc(d.location || '-') + '</span></div>';
    }

    function _renderBody(d) {
        var body = document.querySelector('#' + PANEL_ID + ' .pdp-body');
        if (!body) return;
        var lst = (d.proses_listesi || []).slice();
        // Frontend siralama: proses_kod numerik artan
        lst.sort(function (a, b) {
            var na = parseInt(a.proses_kod, 10);
            var nb = parseInt(b.proses_kod, 10);
            if (isNaN(na)) na = 9999;
            if (isNaN(nb)) nb = 9999;
            return na - nb;
        });
        if (lst.length === 0) {
            body.innerHTML = '<h4>ÜRETİM AKIŞI</h4>' +
                '<div class="pdp-empty">Henüz proses kaydı yok.</div>';
            return;
        }
        var aktifKod = d.aktif_proses_kod;
        var html = '<h4>ÜRETİM AKIŞI (' + lst.length + ' proses)</h4>';
        for (var i = 0; i < lst.length; i++) {
            var p = lst[i];
            var aktif = (p.proses_kod === aktifKod);
            var cls = 'pdp-proses';
            if (aktif) cls += ' aktif';
            else if (p.durum === 'tamam') cls += ' tamam';
            var ikonRenk = '#9ca3af', ikonBg = '#f3f4f6', ikonText = '⏳';
            var rozetRenk = '#6b7280';
            if (p.durum === 'tamam') {
                ikonRenk = '#fff'; ikonBg = '#10b981'; ikonText = '✓';
                rozetRenk = '#10b981';
            } else if (p.durum === 'devam') {
                ikonRenk = '#fff'; ikonBg = '#f97316'; ikonText = '●';
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
                '<div class="pdp-proses-head">' +
                    '<span class="pdp-proses-ikon" style="background:' + ikonBg +
                    ';color:' + ikonRenk + ';">' + ikonText + '</span>' +
                    '<span class="pdp-proses-adi">' +
                    _esc(p.proses_adi || p.proses_kod) +
                    ' <span style="font-size:10px;color:#9ca3af;font-weight:400;">[' +
                    _esc(p.proses_kod) + ']</span></span>' +
                    '<span class="pdp-proses-rozet" style="background:' + rozetRenk +
                    ';color:#fff;">' + (aktif ? 'AKTİF' : p.durum.toUpperCase()) + '</span>' +
                '</div>' +
                '<div class="pdp-proses-bar-wrap"><div class="pdp-proses-bar" ' +
                    'style="width:' + bar + '%;background:' + barRenk + ';"></div></div>' +
                '<div class="pdp-proses-detay">' +
                    '<span>' + _fmt(p.yapilan) + ' / ' + _fmt(p.toplam_hedef) +
                    ' (' + p.yuzde + '%)</span>' +
                    '<span>' + (sonTxt ? 'Son: ' + sonTxt : '') + '</span>' +
                '</div>' +
            '</div>';
        }
        body.innerHTML = html;
    }

    function _yukle(emirNo) {
        if (loading) return;
        if (aktifEmirNo === String(emirNo)) {
            // ayni satira tekrar tikla = kapat (toggle)
            _kapat();
            return;
        }
        loading = true;
        aktifEmirNo = String(emirNo);
        _ensureDom();
        document.querySelector('#' + PANEL_ID + ' .pdp-head').innerHTML =
            '<div class="pdp-info"><div class="pdp-emir">E.' + _esc(emirNo) + '</div>' +
            '<div class="pdp-model">Yükleniyor...</div></div>' +
            '<button class="pdp-close" type="button" title="Kapat">×</button>';
        document.querySelector('#' + PANEL_ID + ' .pdp-meta').innerHTML = '';
        document.querySelector('#' + PANEL_ID + ' .pdp-body').innerHTML =
            '<div class="pdp-loading">Yükleniyor...</div>';
        var btn = document.querySelector('#' + PANEL_ID + ' .pdp-close');
        if (btn) btn.addEventListener('click', _kapat);
        _ac();

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
                if (r.status >= 400 || !r.data || !r.data.ok) {
                    document.querySelector('#' + PANEL_ID + ' .pdp-body').innerHTML =
                        '<div class="pdp-error">' +
                        _esc((r.data && r.data.mesaj) || 'Veri alınamadı') +
                        '</div>';
                    return;
                }
                _renderHead(r.data);
                _renderMeta(r.data);
                _renderBody(r.data);
            })
            .catch(function (e) {
                loading = false;
                document.querySelector('#' + PANEL_ID + ' .pdp-body').innerHTML =
                    '<div class="pdp-error">Sunucuya ulaşılamadı: ' +
                    _esc(e.message) + '</div>';
            });
    }

    // Click delegation - PLAN tablosu satirlarina (data-emir-no veya tr)
    document.addEventListener('click', function (ev) {
        // Etkilesim icindeki elementlere izin verme
        if (ev.target.closest('button, a, input, select, .tab-x')) return;
        var tr = ev.target.closest('#planBody tr');
        if (!tr) return;
        // data-emir-no varsa kullan
        var en = tr.dataset.emirNo;
        if (!en) {
            // Fallback: ilk td'deki "E.110626" -> 110626
            var ilkTd = tr.querySelector('td:nth-child(2)');
            if (ilkTd) {
                var t = (ilkTd.textContent || '').trim();
                var m = t.match(/(\d+)/);
                if (m) en = m[1];
            }
        }
        if (!en) return;
        _yukle(en);
    }, false);

    // Mevcut _renderPlanV5 satir olusturulurken data-emir-no ekleyelim (monkey-patch)
    if (typeof window.renderPlanRows === 'function' && !window._origRenderPlanRows) {
        window._origRenderPlanRows = window.renderPlanRows;
        window.renderPlanRows = function (emirler) {
            var ret = window._origRenderPlanRows.apply(this, arguments);
            // Render sonrasi tum satirlara data-emir-no + plan-row class ekle
            var rows = document.querySelectorAll('#planBody tr');
            for (var i = 0; i < rows.length; i++) {
                var tr = rows[i];
                if (tr.dataset.emirNo) continue;
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

    console.log('[CPS LOCAL] PLAN detay panel v1 yuklendi');
})();
'''


def backup(path):
    if not os.path.exists(path):
        return None
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = path + f'.bak_{ts}'
    shutil.copy2(path, bp)
    return bp


def patch_routes():
    print()
    print("=" * 64)
    print("1/2 BACKEND: yeni endpoint /hedef/plan-detay/<emir_no>")
    print("=" * 64)
    if not os.path.exists(HEDEF_ROUTES):
        print(f"  [HATA] {HEDEF_ROUTES} yok.")
        return False
    with open(HEDEF_ROUTES, 'r', encoding='utf-8') as f:
        src = f.read()
    if ROUTES_MARKER in src:
        print("  [BILGI] Endpoint zaten ekli.")
        return True
    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += ROUTES_BLOCK

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False

    bp = backup(HEDEF_ROUTES)
    print(f"  [OK] Yedek: {bp}")
    with open(HEDEF_ROUTES, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Endpoint eklendi.")
    return True


def patch_js():
    print()
    print("=" * 64)
    print("2/2 FRONTEND: detay panel IIFE")
    print("=" * 64)
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} yok.")
        return False
    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()
    if JS_MARKER in src:
        print("  [BILGI] JS zaten ekli.")
        return True
    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += JS_BLOCK

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Detay panel IIFE eklendi.")
    return True


def main():
    print("=" * 64)
    print("PLAN DETAY PANEL v1")
    print("=" * 64)

    ok1 = patch_routes()
    ok2 = patch_js()

    print()
    print("=" * 64)
    if ok1 and ok2:
        print("TAMAM.")
        print("=" * 64)
        print()
        print("YAPILACAK:")
        print("  Flask debug mode otomatik restart yapar.")
        print("  Tarayicida Ctrl+F5.")
        print()
        print("TEST:")
        print("  1) /hedef/ -> PLAN sekmesi")
        print("  2) E.110626 satirina tikla")
        print("  3) Sagdan slide-in panel acilmali")
        print()
        print("Beklenen panel:")
        print("  - Header: E.110626 / model / Lc Waikiki")
        print("  - Meta: Siparis, Termin, Hedef, Yapilan, Kalan, Lokasyon")
        print("  - URETIM AKISI: 1 proses (Kesim) - AKTIF rozet")
        print()
        print("Console:")
        print("  [CPS LOCAL] PLAN detay panel v1 yuklendi")
        print()
        print("Kapatma: ESC, X, dis tikla, ayni satira tekrar tikla")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
