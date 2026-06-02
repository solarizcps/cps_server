# -*- coding: utf-8 -*-
"""
setup_plan_hizalama_v4.py
-------------------------
PLAN tablo hizalama sorunu cozumu (kolon sayisi/sirasi/text-align).

1) HTML (templates/hedef/index.html):
   a) <table> -> <table id="planTable">
   b) thead'e class="text" / class="num" eklendi
   c) Subtitle: "MES v2 API uzerinden..." -> "Korgun ve CPS onayli..."

2) JS (static/js/hedef.js):
   - Yeni IIFE v4 ekle (v3'u window override ile golger)
   - <style id="planTableStyles"> head'e dinamik enjekte
   - _renderPlanV4: class-based td render

DOKUNMAZ:
  - Backend (mevcut /hedef/plan endpoint'i, hesaplama)
  - mock_data.db
  - Diger sekmeler (ONAYLAR/GECMIS/...)
  - /uretim/* hicbiri
"""

import os
import re
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
HTML_PATH = os.path.join(CPS_ROOT, "templates", "hedef", "index.html")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

JS_MARKER_V4 = "[CPS LOCAL] PLAN v4 - hizalama"


# ---------------------------------------------------------
# 1) HTML - thead + table id
# ---------------------------------------------------------

HTML_TABLE_OLD = '''    <table>
      <thead>
        <tr>
          <th>EM&#304;R</th>
          <th>S&#304;PAR&#304;&#350;LER</th>
          <th>MODEL</th>
          <th>HEDEF</th>
          <th>YAPILAN</th>
          <th>KALAN</th>
          <th>%</th>
        </tr>
      </thead>'''

HTML_TABLE_NEW = '''    <table id="planTable">
      <thead>
        <tr>
          <th class="text">EM&#304;R</th>
          <th class="text">S&#304;PAR&#304;&#350;LER</th>
          <th class="text">MODEL</th>
          <th class="num">HEDEF</th>
          <th class="num">YAPILAN</th>
          <th class="num">KALAN</th>
          <th class="num">%</th>
        </tr>
      </thead>'''

NEW_SUBTITLE = "Korgun ve CPS onaylı üretim kayıtları üzerinden canlı hedef takibi."


# ---------------------------------------------------------
# 2) JS v4 IIFE (style injection + class-based render)
# ---------------------------------------------------------

JS_BLOCK_V4 = r'''


/* ====================================================================
   CPS LOCAL OVERRIDE v4 - PLAN tablo HIZALAMA (class-based)
   - <style id="planTableStyles"> head'e dinamik enjekte
   - thead/tbody class .text / .num
   - .txt-strong, .badge-percent
   - v3'u window override ile golger
   ==================================================================== */
(function () {
    'use strict';

    // Style injection (idempotent — bir kere)
    if (!document.getElementById('planTableStyles')) {
        var styleEl = document.createElement('style');
        styleEl.id = 'planTableStyles';
        styleEl.textContent = [
            '#planTable { width:100%; border-collapse:collapse; }',
            '#planTable th, #planTable td { white-space:nowrap; padding:10px 14px; }',
            '#planTable th { font-weight:700; font-size:11px; letter-spacing:0.6px; text-transform:uppercase; color:var(--text3); border-bottom:1px solid var(--border); }',
            '#planTable td { border-bottom:1px solid var(--border); font-size:14px; }',
            '#planTable th.num, #planTable td.num { text-align:right; }',
            '#planTable th.text, #planTable td.text { text-align:left; }',
            '#planTable td.txt-strong { font-weight:700; color:var(--text); }',
            '#planTable td .badge-percent { display:inline-block; color:#fff; padding:4px 10px; border-radius:12px; font-weight:700; font-size:12px; min-width:64px; text-align:center; }'
        ].join('\n');
        document.head.appendChild(styleEl);
    }

    function _planEscV4(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function _planFmtV4(n) {
        var x = Number(n);
        if (!isFinite(x)) return _planEscV4(n);
        return x.toLocaleString('tr-TR');
    }

    function _planYuzdeRenkV4(yuzde) {
        var y = Number(yuzde) || 0;
        if (y < 30) return '#dc2626';   // kirmizi
        if (y < 70) return '#f59e0b';   // sari
        return '#10b981';                // yesil
    }

    function _renderPlanV4(emirler) {
        var body = document.getElementById('planBody');
        if (!body) return;
        body.innerHTML = '';
        if (!emirler || emirler.length === 0) {
            body.innerHTML = '<tr><td colspan="7" class="text" style="text-align:center; padding:32px; color:var(--text3);">Aktif emir yok.</td></tr>';
            return;
        }
        for (var i = 0; i < emirler.length; i++) {
            var e = emirler[i];
            var renk = _planYuzdeRenkV4(e.yuzde);
            var modelTxt = e.model || '-';
            var sipTxt = e.siparisler || '-';
            var tr = document.createElement('tr');
            tr.innerHTML =
                '<td class="text txt-strong">E.' + _planEscV4(e.emir_no) + '</td>' +
                '<td class="text" style="font-family:var(--mono); font-size:12px; color:var(--text2);">' + _planEscV4(sipTxt) + '</td>' +
                '<td class="text" style="font-size:13px;">' + _planEscV4(modelTxt) + '</td>' +
                '<td class="num" style="font-family:var(--mono);">' + _planFmtV4(e.hedef) + '</td>' +
                '<td class="num" style="font-family:var(--mono);">' + _planFmtV4(e.yapilan) + '</td>' +
                '<td class="num" style="font-family:var(--mono);">' + _planFmtV4(e.kalan) + '</td>' +
                '<td class="num"><span class="badge-percent" style="background:' + renk + ';">' + _planEscV4(e.yuzde) + '%</span></td>';
            body.appendChild(tr);
        }
    }

    function _planlariYukleV4() {
        var body = document.getElementById('planBody');
        var errBox = document.getElementById('planError');
        if (errBox) errBox.innerHTML = '';
        if (body) {
            body.innerHTML = '<tr><td colspan="7" class="text" style="text-align:center; padding:24px; color:var(--text3);">Yükleniyor...</td></tr>';
        }
        fetch('/hedef/plan', {
            method: 'GET',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' }
        })
            .then(function (resp) {
                return resp.text().then(function (t) {
                    var data;
                    try { data = JSON.parse(t); } catch (_) { data = null; }
                    return { status: resp.status, data: data };
                });
            })
            .then(function (r) {
                if (r.status >= 400 || !r.data || r.data.ok === false) {
                    if (body) {
                        body.innerHTML = '<tr><td colspan="7" class="text" style="text-align:center; padding:24px; color:var(--red);">PLAN yüklenemedi.</td></tr>';
                    }
                    return;
                }
                var emirler = (r.data && r.data.emirler) || [];
                _renderPlanV4(emirler);
                console.log('CPS/hedef/plan v4', r.status, emirler.length);
            })
            .catch(function (e) {
                console.error('plan v4 fetch:', e);
                if (body) {
                    body.innerHTML = '<tr><td colspan="7" class="text" style="text-align:center; padding:24px; color:var(--red);">Sunucuya ulaşılamadı.</td></tr>';
                }
            });
    }

    window.planlariYukle = _planlariYukleV4;
    window.renderPlanRows = _renderPlanV4;

    console.log('[CPS LOCAL] PLAN v4 - hizalama (class-based) yuklendi.');
})();
'''


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def backup(path):
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = path + f'.bak_{ts}'
    shutil.copy2(path, bp)
    return bp


def patch_html():
    print()
    print("=" * 64)
    print("1/2 HTML: templates/hedef/index.html")
    print("=" * 64)
    if not os.path.exists(HTML_PATH):
        print(f"  [HATA] {HTML_PATH} bulunamadi.")
        return False

    with open(HTML_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    changed = False

    # --- 1.a) thead + table id ---
    if HTML_TABLE_NEW in src:
        print("  [BILGI] thead/table id zaten guncel.")
    elif HTML_TABLE_OLD in src and src.count(HTML_TABLE_OLD) == 1:
        src = src.replace(HTML_TABLE_OLD, HTML_TABLE_NEW, 1)
        changed = True
        print("  [OK] <table id='planTable'> + thead class'lari uygulandi.")
    else:
        print("  [HATA] Eski thead bloku bulunamadi (ya da birden fazla).")
        return False

    # --- 1.b) Subtitle ---
    if NEW_SUBTITLE in src:
        print("  [BILGI] Subtitle zaten guncel.")
    else:
        m = re.search(r'MES v2[^<]*', src)
        if m:
            src = src[:m.start()] + NEW_SUBTITLE + src[m.end():]
            changed = True
            print(f"  [OK] Subtitle guncellendi (eski: '{m.group()[:50]}...')")
        else:
            print("  [UYARI] 'MES v2' metni bulunamadi, subtitle atlandi.")

    if changed:
        bp = backup(HTML_PATH)
        print(f"  [OK] Yedek: {bp}")
        with open(HTML_PATH, 'w', encoding='utf-8') as f:
            f.write(src)
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

    if JS_MARKER_V4 in src:
        print("  [BILGI] JS v4 zaten ekli.")
        return True

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += JS_BLOCK_V4

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] PLAN v4 IIFE eklendi (style injection + class-based render).")
    return True


def main():
    ok1 = patch_html()
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
        print("  3) /hedef/ -> PLAN sekmesi")
        print()
        print("Beklenen E.110626 satiri (HIZALI):")
        print("  EMIR        SIPARISLER     MODEL          HEDEF   YAPILAN  KALAN     %")
        print("  E.110626    33558, 33638   CRX-71033-LCW  14.000  1.970    12.030  14.1%")
        print()
        print("  - Sayisal kolonlar saga hizali (KALAN basligin altinda)")
        print("  - Metin kolonlari sola hizali")
        print("  - Subtitle: 'Korgun ve CPS onayli...'")
        print()
        print("Console:")
        print("  [CPS LOCAL] PLAN v4 - hizalama (class-based) yuklendi.")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
