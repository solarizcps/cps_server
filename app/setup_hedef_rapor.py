# -*- coding: utf-8 -*-
"""
setup_hedef_rapor.py
--------------------
FAZ 4.4 ADIM 2 - RAPOR ekrani.

1) Backend (modules/hedef/routes.py):
   - GET /hedef/rapor?baslangic=YYYY-MM-DD&bitis=YYYY-MM-DD
   - Sadece onay_durum='onaylandi' kayitlar
   - Tarih filtresi: COALESCE(onay_tarihi, olusturma) -> date()
   - Donus: { ok, baslangic, bitis, personel_bazli, proses_bazli, emir_bazli }
   - emir_bazli'da model adi Korgun get_emir_ozet ile zenginlestirilir

2) Frontend (static/js/hedef.js):
   - Yeni IIFE v5 (idempotent marker)
   - window.fetch monkey-patch: /api/v2/hedef/rapor URL'leri yutulur
     (MES v2 cagrilari tamamen kaldirilmis olur)
   - Eski <table>...<tbody id="raporBody">...</tbody> hide edilir
   - Yerine <div id="raporSonuc"> 3 blok HTML render edilir
   - Tarih input'lari default'lari otomatik dolar (son 7 gun)
   - Tarih change + tab click -> otomatik yenile

DOKUNMAZ:
  - PLAN endpoint ve render
  - ONAYLAR/GECMIS
  - /uretim/* hicbiri
  - mock_data.db schema
"""

import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
ROUTES_PATH = os.path.join(CPS_ROOT, "modules", "hedef", "routes.py")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

BACKEND_MARKER = "# === CPS LOCAL HEDEF RAPOR ENDPOINT ==="
JS_MARKER = "[CPS LOCAL] RAPOR v5 yuklendi"


# ======================================================================
# BACKEND
# ======================================================================
BACKEND_BLOCK = '''


# === CPS LOCAL HEDEF RAPOR ENDPOINT ===
# Tarih araligina gore onaylanmis CPS uretim kayitlari (3 blok ozet)

@hedef_bp.route('/rapor', methods=['GET'])
def hedef_rapor():
    """GET /hedef/rapor?baslangic=YYYY-MM-DD&bitis=YYYY-MM-DD"""
    import sqlite3
    from datetime import date, timedelta
    from flask import jsonify, request

    # Parametreler
    bas = (request.args.get('baslangic') or '').strip()
    bit = (request.args.get('bitis') or '').strip()
    today = date.today()
    if not bit:
        bit = today.isoformat()
    if not bas:
        bas = (today - timedelta(days=7)).isoformat()

    # Tarih formati dogrulama (basit)
    import re as _re
    if not _re.match(r'^\\d{4}-\\d{2}-\\d{2}$', bas):
        return jsonify({'ok': False, 'success': False,
                        'mesaj': 'gecersiz baslangic',
                        'personel_bazli': [], 'proses_bazli': [], 'emir_bazli': []}), 400
    if not _re.match(r'^\\d{4}-\\d{2}-\\d{2}$', bit):
        return jsonify({'ok': False, 'success': False,
                        'mesaj': 'gecersiz bitis',
                        'personel_bazli': [], 'proses_bazli': [], 'emir_bazli': []}), 400

    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # --- PERSONEL BAZLI ---
        cur.execute("""
            SELECT
                COALESCE(NULLIF(personel_ad,''), 'Bilinmeyen') AS personel_ad,
                personel_id,
                SUM(miktar) AS toplam_miktar,
                COUNT(*) AS kayit_sayisi
              FROM uretim_kayit
             WHERE onay_durum = 'onaylandi'
               AND date(COALESCE(NULLIF(onay_tarihi,''), olusturma)) BETWEEN ? AND ?
             GROUP BY personel_id, personel_ad
             ORDER BY toplam_miktar DESC, personel_ad ASC
        """, (bas, bit))
        personel_bazli = []
        for r in cur.fetchall():
            d = dict(r)
            personel_bazli.append({
                'personel_id': d.get('personel_id'),
                'personel_ad': d.get('personel_ad') or 'Bilinmeyen',
                'toplam_miktar': int(d.get('toplam_miktar') or 0),
                'kayit_sayisi': int(d.get('kayit_sayisi') or 0),
            })

        # --- PROSES BAZLI ---
        cur.execute("""
            SELECT
                COALESCE(NULLIF(proses_adi,''), 'Bilinmeyen') AS proses_adi,
                SUM(miktar) AS toplam_miktar,
                COUNT(*) AS kayit_sayisi
              FROM uretim_kayit
             WHERE onay_durum = 'onaylandi'
               AND date(COALESCE(NULLIF(onay_tarihi,''), olusturma)) BETWEEN ? AND ?
             GROUP BY proses_adi
             ORDER BY toplam_miktar DESC, proses_adi ASC
        """, (bas, bit))
        proses_bazli = []
        for r in cur.fetchall():
            d = dict(r)
            proses_bazli.append({
                'proses_adi': d.get('proses_adi') or 'Bilinmeyen',
                'toplam_miktar': int(d.get('toplam_miktar') or 0),
                'kayit_sayisi': int(d.get('kayit_sayisi') or 0),
            })

        # --- EMIR BAZLI (raw) ---
        cur.execute("""
            SELECT
                emir_no,
                MAX(model_kod) AS model_kod,
                MAX(model_adi) AS model_adi,
                SUM(miktar) AS toplam_miktar,
                COUNT(*) AS kayit_sayisi
              FROM uretim_kayit
             WHERE onay_durum = 'onaylandi'
               AND date(COALESCE(NULLIF(onay_tarihi,''), olusturma)) BETWEEN ? AND ?
             GROUP BY emir_no
             ORDER BY toplam_miktar DESC, emir_no DESC
        """, (bas, bit))
        emir_raw = [dict(r) for r in cur.fetchall()]
        conn.close()

        # Korgun'dan model adi zenginlestir (her emir icin 1 cagri)
        try:
            from modules.common import korgun as _kk_rapor
        except Exception:
            _kk_rapor = None

        emir_bazli = []
        for e in emir_raw:
            emir_no_str = str(e.get('emir_no'))
            model = e.get('model_kod') or e.get('model_adi') or ''
            if _kk_rapor is not None:
                try:
                    ozet = _kk_rapor.get_emir_ozet(int(e.get('emir_no'))) or {}
                    if ozet.get('ok'):
                        model = ozet.get('model_kod') or model
                except Exception:
                    pass
            emir_bazli.append({
                'emir_no': emir_no_str,
                'model': model,
                'toplam_miktar': int(e.get('toplam_miktar') or 0),
                'kayit_sayisi': int(e.get('kayit_sayisi') or 0),
            })

        return jsonify({
            'ok': True, 'success': True,
            'baslangic': bas, 'bitis': bit,
            'personel_bazli': personel_bazli,
            'proses_bazli': proses_bazli,
            'emir_bazli': emir_bazli,
        })
    except Exception as e:
        return jsonify({
            'ok': False, 'success': False,
            'mesaj': f'{type(e).__name__}: {str(e)[:200]}',
            'personel_bazli': [], 'proses_bazli': [], 'emir_bazli': [],
        }), 500
'''


# ======================================================================
# FRONTEND
# ======================================================================
JS_BLOCK = r'''


/* ====================================================================
   CPS LOCAL - RAPOR v5
   - GET /hedef/rapor backend'i kullanir
   - 3 blok render: PERSONEL, PROSES, EMIR
   - Eski raporBody table HIDE edilir, yerine #raporSonuc gelir
   - window.fetch monkey-patch: /api/v2/hedef/rapor URL'leri yutulur
     (eski raporYukle hala calissa bile MES v2'ye gitmez)
   - Tarih default: bitis=bugun, baslangic=7 gun once (input bossa)
   - Tarih change + RAPOR tab click -> otomatik yenile
   ==================================================================== */
(function () {
    'use strict';

    // ---- 1) MES v2 RAPOR fetch'lerini yutan monkey-patch ---------------
    if (!window.__cpsRaporFetchPatched) {
        var _origFetch = window.fetch;
        window.fetch = function (url, opts) {
            try {
                if (typeof url === 'string' && url.indexOf('/api/v2/hedef/rapor') !== -1) {
                    console.log('[CPS LOCAL] eski MES v2 rapor fetch iptal:', url);
                    return Promise.resolve(new Response('{"ok":false,"veriler":[],"rows":[]}',
                        { status: 200, headers: { 'Content-Type': 'application/json' } }));
                }
            } catch (_) {}
            return _origFetch.apply(this, arguments);
        };
        window.__cpsRaporFetchPatched = true;
    }

    // ---- 2) Style injection ---------------------------------------------
    if (!document.getElementById('raporStyles')) {
        var s = document.createElement('style');
        s.id = 'raporStyles';
        s.textContent = [
            '#raporSonuc { margin-top:12px; }',
            '#raporSonuc .rb-blok { margin-bottom:18px; background:#fff; border-radius:10px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.05); }',
            '#raporSonuc .rb-blok h4 { margin:0 0 10px 0; font-size:11px; font-weight:700; letter-spacing:1.2px; color:var(--text2); text-transform:uppercase; border-bottom:2px solid var(--border); padding-bottom:8px; }',
            '#raporSonuc table.rb-table { width:100%; border-collapse:collapse; }',
            '#raporSonuc table.rb-table th, #raporSonuc table.rb-table td { padding:8px 12px; white-space:nowrap; border-bottom:1px solid var(--border); font-size:13px; }',
            '#raporSonuc table.rb-table th { font-weight:700; color:var(--text3); font-size:10px; letter-spacing:0.6px; text-transform:uppercase; }',
            '#raporSonuc table.rb-table th.num, #raporSonuc table.rb-table td.num { text-align:right; font-family:var(--mono); }',
            '#raporSonuc table.rb-table th.text, #raporSonuc table.rb-table td.text { text-align:left; }',
            '#raporSonuc .rb-empty { padding:20px; text-align:center; color:var(--text3); font-size:13px; }',
            '#raporSonuc .rb-empty-all { padding:48px; text-align:center; color:var(--text3); background:#fff; border-radius:10px; box-shadow:0 1px 3px rgba(0,0,0,0.05); }',
            '#raporSonuc .rb-loading { padding:32px; text-align:center; color:var(--text3); }'
        ].join('\n');
        document.head.appendChild(s);
    }

    // ---- 3) Helpers -----------------------------------------------------
    function _rEsc(s) {
        if (s == null) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    function _rFmt(n) {
        var x = Number(n);
        if (!isFinite(x)) return _rEsc(n);
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

    function _ensureContainer() {
        var raporBody = document.getElementById('raporBody');
        if (raporBody) {
            var tbl = raporBody.closest('table');
            if (tbl) tbl.style.display = 'none';
        }
        var sonuc = document.getElementById('raporSonuc');
        if (!sonuc) {
            sonuc = document.createElement('div');
            sonuc.id = 'raporSonuc';
            // Eski tablonun yanina (varsa) ya da rapor pane'ine ekle
            var pane = document.querySelector('[data-pane="rapor"]') ||
                       document.getElementById('h-pane-rapor') ||
                       document.querySelector('.h-pane[data-pane="rapor"]');
            if (raporBody && raporBody.parentNode && raporBody.parentNode.parentNode) {
                var tblNode = raporBody.closest('table');
                var parent = tblNode ? tblNode.parentNode : raporBody.parentNode.parentNode;
                if (tblNode && tblNode.parentNode) {
                    tblNode.parentNode.insertBefore(sonuc, tblNode.nextSibling);
                } else {
                    parent.appendChild(sonuc);
                }
            } else if (pane) {
                pane.appendChild(sonuc);
            } else {
                document.body.appendChild(sonuc);
            }
        }
        return sonuc;
    }

    function _renderBlok(baslik, kolonlar, rows, bosMesaj) {
        var html = '<div class="rb-blok"><h4>' + _rEsc(baslik) + '</h4>';
        if (!rows || rows.length === 0) {
            html += '<div class="rb-empty">' + _rEsc(bosMesaj || 'Veri yok.') + '</div></div>';
            return html;
        }
        html += '<table class="rb-table"><thead><tr>';
        for (var i = 0; i < kolonlar.length; i++) {
            var k = kolonlar[i];
            html += '<th class="' + (k.num ? 'num' : 'text') + '">' + _rEsc(k.label) + '</th>';
        }
        html += '</tr></thead><tbody>';
        for (var j = 0; j < rows.length; j++) {
            var r = rows[j];
            html += '<tr>';
            for (var c = 0; c < kolonlar.length; c++) {
                var kk = kolonlar[c];
                var v = r[kk.key];
                if (kk.num) {
                    html += '<td class="num">' + _rFmt(v) + '</td>';
                } else {
                    html += '<td class="text">' + _rEsc(v == null || v === '' ? '-' : v) + '</td>';
                }
            }
            html += '</tr>';
        }
        html += '</tbody></table></div>';
        return html;
    }

    function _renderRapor(data) {
        var sonuc = _ensureContainer();
        if (!sonuc) return;

        var personel = (data && data.personel_bazli) || [];
        var proses = (data && data.proses_bazli) || [];
        var emir = (data && data.emir_bazli) || [];

        if (personel.length === 0 && proses.length === 0 && emir.length === 0) {
            sonuc.innerHTML = '<div class="rb-empty-all">Bu tarih aralığında onaylı üretim kaydı yok.</div>';
            return;
        }

        var html = '';
        html += _renderBlok('Personel Bazlı', [
            { label: 'PERSONEL', key: 'personel_ad', num: false },
            { label: 'TOPLAM',   key: 'toplam_miktar', num: true },
            { label: 'KAYIT',    key: 'kayit_sayisi',  num: true }
        ], personel, 'Personel kaydı yok.');

        html += _renderBlok('Proses Bazlı', [
            { label: 'PROSES', key: 'proses_adi', num: false },
            { label: 'TOPLAM', key: 'toplam_miktar', num: true },
            { label: 'KAYIT',  key: 'kayit_sayisi',  num: true }
        ], proses, 'Proses kaydı yok.');

        html += _renderBlok('Emir Bazlı', [
            { label: 'EMİR',   key: 'emir_no', num: false },
            { label: 'MODEL',  key: 'model',   num: false },
            { label: 'TOPLAM', key: 'toplam_miktar', num: true },
            { label: 'KAYIT',  key: 'kayit_sayisi',  num: true }
        ], emir, 'Emir kaydı yok.');

        sonuc.innerHTML = html;
    }

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

        // Direkt _origFetch kullan (kendi monkey-patch'imize yakalanmasin)
        var fetchFn = window.fetch;  // patch /hedef/rapor'u yutmuyor (sadece /api/v2/...)
        fetchFn(url, {
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
                            (r.data && r.data.mesaj ? ' (' + _rEsc(r.data.mesaj) + ')' : '') + '</div>';
                    }
                    return;
                }
                _renderRapor(r.data);
                console.log('CPS/hedef/rapor', r.status,
                    (r.data.personel_bazli || []).length + ' personel, ' +
                    (r.data.proses_bazli || []).length + ' proses, ' +
                    (r.data.emir_bazli || []).length + ' emir');
            })
            .catch(function (e) {
                console.error('rapor fetch:', e);
                if (sonuc) sonuc.innerHTML = '<div class="rb-empty-all">Sunucuya ulaşılamadı.</div>';
            });
    }

    // Override
    window.raporYukle = _yukleRapor;
    window.raporlariYukle = _yukleRapor; // eski adi varsa

    // ---- Kurulum (idempotent) -------------------------------------------
    var _kurulduMu = false;
    function _kurulum() {
        if (_kurulduMu) return;
        _kurulduMu = true;

        var inpBas = document.getElementById('raporTarihBas');
        var inpBit = document.getElementById('raporTarihBit');
        if (inpBit && !inpBit.value) inpBit.value = _bugunISO();
        if (inpBas && !inpBas.value) inpBas.value = _gunOnceISO(7);

        if (inpBas) inpBas.addEventListener('change', _yukleRapor);
        if (inpBit) inpBit.addEventListener('change', _yukleRapor);

        // RAPOR tab click -> yukle
        var rt = document.querySelector('.h-tab[data-tab="rapor"]');
        if (rt) {
            rt.addEventListener('click', function () {
                setTimeout(_yukleRapor, 60);
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _kurulum);
    } else {
        setTimeout(_kurulum, 0);
    }

    console.log('[CPS LOCAL] RAPOR v5 yuklendi.');
})();
'''


# ======================================================================
# Helpers
# ======================================================================
def backup(path):
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = path + f'.bak_{ts}'
    shutil.copy2(path, bp)
    return bp


def patch_backend():
    print()
    print("=" * 64)
    print("1/2 BACKEND: modules/hedef/routes.py")
    print("=" * 64)
    if not os.path.exists(ROUTES_PATH):
        print(f"  [HATA] {ROUTES_PATH} bulunamadi.")
        return False
    with open(ROUTES_PATH, 'r', encoding='utf-8') as f:
        src = f.read()
    if BACKEND_MARKER in src:
        print("  [BILGI] /hedef/rapor zaten ekli.")
        return True

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += BACKEND_BLOCK

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False

    bp = backup(ROUTES_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(ROUTES_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] /hedef/rapor endpoint'i eklendi.")
    return True


def patch_js():
    print()
    print("=" * 64)
    print("2/2 JS: static/js/hedef.js")
    print("=" * 64)
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} bulunamadi.")
        return False
    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()
    if JS_MARKER in src:
        print("  [BILGI] RAPOR v5 zaten ekli.")
        return True

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += JS_BLOCK

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] RAPOR v5 IIFE eklendi (fetch monkey-patch + 3 blok render).")
    return True


def main():
    ok1 = patch_backend()
    ok2 = patch_js()

    print()
    print("=" * 64)
    if ok1 and ok2:
        print("HEPSI TAMAM.")
        print("=" * 64)
        print()
        print("YAPILACAK:")
        print("  1) CPS sunucusunu yeniden baslat")
        print("  2) Browser'da Ctrl+F5")
        print("  3) /hedef/ -> RAPOR sekmesi")
        print()
        print("Beklenen (110626 emrinde 4 onayli kayit, hepsi bugun):")
        print("  PERSONEL BAZLI:")
        print("    Sistem Yöneticisi  1.490   4")
        print("  PROSES BAZLI:")
        print("    Temizleme   120   1")
        print("    Monta     1.000   1")
        print("    Enjeksiyon  250   1")
        print("    Kesim       120   1")
        print("  EMIR BAZLI:")
        print("    110626   CRX-71033-LCW   1.490   4")
        print()
        print("Tarih: bugun ile 7 gun once arasi (input default)")
        print("Tarih degisirse otomatik yeniden yukler.")
        print()
        print("Console:")
        print("  [CPS LOCAL] RAPOR v5 yuklendi.")
        print("  CPS/hedef/rapor 200 1 personel, 4 proses, 1 emir")
        print("  (eski MES v2 rapor fetch iptal: ...)  -- monkey-patch calistiysa")
        print()
        print("Direkt JSON test:")
        print("  http://127.0.0.1:5057/hedef/rapor?baslangic=2026-04-20&bitis=2026-04-28")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
