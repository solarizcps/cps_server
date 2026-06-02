# -*- coding: utf-8 -*-
"""
setup_plan_siparisler_kolonu.py
-------------------------------
PLAN ekrani: 6 -> 7 kolon (SIPARISLER eklendi)
Tum degisiklikler idempotent.

1) Backend (modules/hedef/routes.py):
   - get_emir_ozet'in donen 'siparisler' listesinden sip_no'lar alinir
   - virgulle birlestirilir: "33558, 33638"
   - sonuc dict'ine 'siparisler' alani eklenir

2) HTML (templates/hedef/index.html):
   - PLAN thead'ine SIPARISLER kolonu (EMIR'den sonra)
   - colspan 6 -> 7

3) JS (static/js/hedef.js):
   - Yeni IIFE eklenir (eskisini golger; eski override hala dosyada kalir)
   - _renderPlanV3: SIPARISLER hucresi eklenmis hali
   - "Aktif emir yok" colspan 6 -> 7

DOKUNMAZ:
  - mevcut hesaplama mantigi (hedef/yapilan/kalan/yuzde)
  - mock_data.db
  - /uretim/* endpointleri
  - /hedef/onaylar/*, /hedef/gecmis, /hedef/onayla, /hedef/reddet
"""

import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
ROUTES_PATH = os.path.join(CPS_ROOT, "modules", "hedef", "routes.py")
HTML_PATH = os.path.join(CPS_ROOT, "templates", "hedef", "index.html")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

JS_MARKER = "[CPS LOCAL] PLAN v3 - siparisler kolonu"


# ---------------------------------------------------------
# 1) BACKEND - iki str_replace
# ---------------------------------------------------------

BE_OLD_1 = '''        try:
            ozet = _kk_plan.get_emir_ozet(emir_no_int) or {}
            ok = bool(ozet.get('ok'))
            hedef = int(ozet.get('hedef_adet', 0) or 0) if ok else 0
            korgun_yapilan = int(ozet.get('yapilan_adet', 0) or 0) if ok else 0
            model = (ozet.get('model_kod') or ozet.get('model_adi') or model_local) if ok else model_local
            if not ok:
                hata_emirler.append({
                    'emir_no': str(emir_no_int),
                    'mesaj': ozet.get('mesaj', 'korgun_ozet_alinamadi')
                })
        except Exception as e:
            hedef = 0
            korgun_yapilan = 0
            model = model_local
            hata_emirler.append({'emir_no': str(emir_no_int), 'mesaj': str(e)[:120]})'''

BE_NEW_1 = '''        try:
            ozet = _kk_plan.get_emir_ozet(emir_no_int) or {}
            ok = bool(ozet.get('ok'))
            hedef = int(ozet.get('hedef_adet', 0) or 0) if ok else 0
            korgun_yapilan = int(ozet.get('yapilan_adet', 0) or 0) if ok else 0
            model = (ozet.get('model_kod') or ozet.get('model_adi') or model_local) if ok else model_local
            # FAZ 4.4 - SIPARIS listesi (get_emir_ozet'ten)
            _sip_list = ozet.get('siparisler', []) if (ok and isinstance(ozet, dict)) else []
            _sip_strs = [str(_s.get('sip_no')) for _s in _sip_list
                         if isinstance(_s, dict) and _s.get('sip_no')]
            siparisler_str = ', '.join(_sip_strs)
            if not ok:
                hata_emirler.append({
                    'emir_no': str(emir_no_int),
                    'mesaj': ozet.get('mesaj', 'korgun_ozet_alinamadi')
                })
        except Exception as e:
            hedef = 0
            korgun_yapilan = 0
            model = model_local
            siparisler_str = ''
            hata_emirler.append({'emir_no': str(emir_no_int), 'mesaj': str(e)[:120]})'''

BE_OLD_2 = '''        sonuc.append({
            'emir_no': str(emir_no_int),
            'model': model,
            'hedef': hedef,'''

BE_NEW_2 = '''        sonuc.append({
            'emir_no': str(emir_no_int),
            'model': model,
            'siparisler': siparisler_str,
            'hedef': hedef,'''

BE_MARKER = "'siparisler': siparisler_str,"


# ---------------------------------------------------------
# 2) HTML - thead 6 -> 7 kolon
# ---------------------------------------------------------

HTML_OLD = '''      <thead>
        <tr>
          <th>EM&#304;R</th>
          <th>MODEL</th>
          <th>HEDEF</th>
          <th>YAPILAN</th>
          <th>KALAN</th>
          <th>%</th>
        </tr>
      </thead>
      <tbody id="planBody">
        <tr class="h-row-loading"><td colspan="6">Yükleniyor...</td></tr>
      </tbody>'''

HTML_NEW = '''      <thead>
        <tr>
          <th>EM&#304;R</th>
          <th>S&#304;PAR&#304;&#350;LER</th>
          <th>MODEL</th>
          <th>HEDEF</th>
          <th>YAPILAN</th>
          <th>KALAN</th>
          <th>%</th>
        </tr>
      </thead>
      <tbody id="planBody">
        <tr class="h-row-loading"><td colspan="7">Yükleniyor...</td></tr>
      </tbody>'''


# ---------------------------------------------------------
# 3) JS - yeni IIFE (v3) ile mevcut override'i gölger
# ---------------------------------------------------------

JS_BLOCK = r'''


/* ====================================================================
   CPS LOCAL OVERRIDE v3 - PLAN + SIPARISLER kolonu
   v2'yi window override ile gölger (eski IIFE dosyada kalir, calisir
   ama window.planlariYukle/renderPlanRows artik bunlar olur).
   Kolonlar: EMIR | SIPARISLER | MODEL | HEDEF | YAPILAN | KALAN | %
   ==================================================================== */
(function () {
    'use strict';

    function _planEscV3(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function _planFmtV3(n) {
        var x = Number(n);
        if (!isFinite(x)) return _planEscV3(n);
        return x.toLocaleString('tr-TR');
    }

    function _planYuzdeRenkV3(yuzde) {
        var y = Number(yuzde) || 0;
        if (y < 30) return '#dc2626';
        if (y < 70) return '#f59e0b';
        return '#10b981';
    }

    function _renderPlanV3(emirler) {
        var body = document.getElementById('planBody');
        if (!body) return;
        body.innerHTML = '';
        if (!emirler || emirler.length === 0) {
            body.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:32px; color:var(--text3);">Aktif emir yok.</td></tr>';
            return;
        }
        for (var i = 0; i < emirler.length; i++) {
            var e = emirler[i];
            var renk = _planYuzdeRenkV3(e.yuzde);
            var modelTxt = e.model || '-';
            var sipTxt = e.siparisler || '-';
            var tr = document.createElement('tr');
            tr.innerHTML =
                '<td><strong>E.' + _planEscV3(e.emir_no) + '</strong></td>' +
                '<td style="font-family:var(--mono); font-size:12px; color:var(--text2);">' + _planEscV3(sipTxt) + '</td>' +
                '<td style="font-size:13px;">' + _planEscV3(modelTxt) + '</td>' +
                '<td style="font-family:var(--mono); text-align:right;">' + _planFmtV3(e.hedef) + '</td>' +
                '<td style="font-family:var(--mono); text-align:right;">' + _planFmtV3(e.yapilan) + '</td>' +
                '<td style="font-family:var(--mono); text-align:right;">' + _planFmtV3(e.kalan) + '</td>' +
                '<td style="text-align:center;"><span style="display:inline-block; background:' + renk + '; color:#fff; padding:4px 10px; border-radius:12px; font-weight:700; font-size:12px; min-width:64px;">' + _planEscV3(e.yuzde) + '%</span></td>';
            body.appendChild(tr);
        }
    }

    function _planlariYukleV3() {
        var body = document.getElementById('planBody');
        var errBox = document.getElementById('planError');
        if (errBox) errBox.innerHTML = '';
        if (body) {
            body.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:24px; color:var(--text3);">Yükleniyor...</td></tr>';
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
                        body.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:24px; color:var(--red);">PLAN yüklenemedi.</td></tr>';
                    }
                    return;
                }
                var emirler = (r.data && r.data.emirler) || [];
                _renderPlanV3(emirler);
                console.log('CPS/hedef/plan v3', r.status, emirler.length);
            })
            .catch(function (e) {
                console.error('plan v3 fetch:', e);
                if (body) {
                    body.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:24px; color:var(--red);">Sunucuya ulaşılamadı.</td></tr>';
                }
            });
    }

    // v2'nin uzerine yaz
    window.planlariYukle = _planlariYukleV3;
    window.renderPlanRows = _renderPlanV3;

    console.log('[CPS LOCAL] PLAN v3 - siparisler kolonu yuklendi.');
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


def patch_backend():
    print()
    print("=" * 64)
    print("1/3 BACKEND: modules/hedef/routes.py")
    print("=" * 64)
    if not os.path.exists(ROUTES_PATH):
        print(f"  [HATA] {ROUTES_PATH} bulunamadi.")
        return False
    with open(ROUTES_PATH, 'r', encoding='utf-8') as f:
        src = f.read()
    if BE_MARKER in src:
        print("  [BILGI] Backend zaten patchli (siparisler_str marker var).")
        return True

    if BE_OLD_1 not in src:
        print("  [HATA] BE_OLD_1 bloku bulunamadi.")
        return False
    if src.count(BE_OLD_1) > 1:
        print("  [HATA] BE_OLD_1 birden fazla.")
        return False
    if BE_OLD_2 not in src:
        print("  [HATA] BE_OLD_2 bloku bulunamadi.")
        return False
    if src.count(BE_OLD_2) > 1:
        print("  [HATA] BE_OLD_2 birden fazla.")
        return False

    new_src = src.replace(BE_OLD_1, BE_NEW_1, 1).replace(BE_OLD_2, BE_NEW_2, 1)

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] Yeni icerik parse edilemiyor: {e}")
        return False

    bp = backup(ROUTES_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(ROUTES_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] siparisler_str hesaplandi + sonuc dict'ine eklendi.")
    return True


def patch_html():
    print()
    print("=" * 64)
    print("2/3 HTML: templates/hedef/index.html")
    print("=" * 64)
    if not os.path.exists(HTML_PATH):
        print(f"  [HATA] {HTML_PATH} bulunamadi.")
        return False
    with open(HTML_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if HTML_NEW in src:
        print("  [BILGI] Yeni 7-kolon thead zaten mevcut.")
        return True
    if HTML_OLD not in src:
        print("  [HATA] Eski 6-kolon thead bulunamadi.")
        print("         (Onceki PLAN patch'i uygulanmamis olabilir.)")
        return False
    if src.count(HTML_OLD) > 1:
        print("  [HATA] Eski thead birden fazla.")
        return False

    new_src = src.replace(HTML_OLD, HTML_NEW, 1)

    bp = backup(HTML_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(HTML_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] PLAN thead 6 -> 7 kolon (SIPARISLER eklendi).")
    return True


def patch_js():
    print()
    print("=" * 64)
    print("3/3 JS: static/js/hedef.js")
    print("=" * 64)
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} bulunamadi.")
        return False
    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()
    if JS_MARKER in src:
        print("  [BILGI] JS v3 zaten ekli.")
        return True

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += JS_BLOCK

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] PLAN v3 IIFE eklendi (mevcut v2'yi window override ile golger).")
    return True


def main():
    ok1 = patch_backend()
    ok2 = patch_html()
    ok3 = patch_js()

    print()
    print("=" * 64)
    if ok1 and ok2 and ok3:
        print("HEPSI TAMAM.")
        print("=" * 64)
        print()
        print("YAPILACAK:")
        print("  1) CPS sunucusunu yeniden baslat")
        print("  2) Browser'da Ctrl+F5")
        print("  3) /hedef/ -> PLAN sekmesi")
        print()
        print("Beklenen E.110626 satiri:")
        print("  EMIR        : E.110626")
        print("  SIPARISLER  : 33558, 33638")
        print("  MODEL       : CRX-71033-LCW")
        print("  HEDEF       : 14.000")
        print("  YAPILAN     : 1.970 (Korgun 480 + CPS 1490)")
        print("  KALAN       : 12.030")
        print("  %           : 14.1% (kirmizi)")
        print()
        print("Console'da:")
        print("  [CPS LOCAL] PLAN v3 - siparisler kolonu yuklendi.")
        print("  CPS/hedef/plan v3 200 1")
        print()
        print("JSON dogrulama:")
        print("  http://127.0.0.1:5057/hedef/plan")
        print("  emir nesnesinde 'siparisler': '33558, 33638' alani olmali")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
