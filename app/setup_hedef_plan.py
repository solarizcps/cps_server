# -*- coding: utf-8 -*-
"""
setup_hedef_plan.py
-------------------
FAZ 4.4 - PLAN ekrani:
  1) modules/hedef/routes.py'a GET /hedef/plan endpoint ekle
     - mock_data.db'den distinct emir_no listesi (CPS'de is goren emirler)
     - her biri icin get_emir_ozet(emir_no) -> hedef + korgun_yapilan
     - mock_data.db'den o emirin SUM(miktar WHERE onay_durum='onaylandi')
     - JSON: [{emir_no, model, hedef, yapilan, kalan, yuzde}]
  2) templates/hedef/index.html PLAN thead'ini guncelle
     ESKI: ID | Emir No | Siparis No | Proses | Hedef Adet | Tarih | Durum (7)
     YENI: EMIR | MODEL | HEDEF | YAPILAN | KALAN | %        (6)
  3) static/js/hedef.js sonuna override IIFE ekle
     - planlariYukle ve renderPlanRows yeni endpoint'i kullansin
     - Yuzde renkleri: <30 kirmizi, 30-70 sari, >70 yesil

DOKUNMAZ:
  - /uretim/* hicbiri
  - /hedef/onaylar/*, /hedef/gecmis, /hedef/onayla, /hedef/reddet
  - mock_data.db semasi
  - Korgun DB
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

BACKEND_MARKER = "# === CPS LOCAL HEDEF PLAN ENDPOINT ==="
JS_MARKER = "[CPS LOCAL] /hedef/ PLAN endpoint override yuklendi"


# ----------------------------------------------------------------------
# 1) BACKEND - /hedef/plan
# ----------------------------------------------------------------------
BACKEND_BLOCK = '''


# === CPS LOCAL HEDEF PLAN ENDPOINT ===
# Aktif emirler: mock_data.db'de en az 1 uretim kaydi olan emirler
# Her biri icin Korgun (get_emir_ozet) + CPS (onayli SUM) birlestirilir.

@hedef_bp.route('/plan', methods=['GET'])
def hedef_plan():
    """GET /hedef/plan - Aktif emirler hedef/yapilan/kalan/yuzde."""
    import sqlite3
    from flask import jsonify
    db_path = _hedef_db_path()

    # 1) CPS local'den distinct emir_no'lar + onayli + bekleyen toplamlari
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cps_rows = conn.execute("""
            SELECT
                emir_no,
                MAX(model_kod) AS model_kod,
                MAX(model_adi) AS model_adi,
                SUM(CASE WHEN onay_durum='onaylandi' THEN miktar ELSE 0 END) AS cps_onayli,
                SUM(CASE WHEN onay_durum='bekliyor'  THEN miktar ELSE 0 END) AS cps_bekleyen,
                COUNT(*) AS kayit_sayisi
              FROM uretim_kayit
             GROUP BY emir_no
        """).fetchall()
        conn.close()
        cps_list = [dict(r) for r in cps_rows]
    except Exception as e:
        return jsonify({
            'success': False, 'ok': False,
            'mesaj': 'CPS DB hatasi: ' + str(e), 'emirler': []
        }), 500

    # 2) Korgun helper
    try:
        from modules.common import korgun as _kk_plan
    except Exception as e:
        return jsonify({
            'success': False, 'ok': False,
            'mesaj': 'Korgun helper yuklenemedi: ' + str(e), 'emirler': []
        }), 500

    # 3) Her emir icin Korgun ozeti + birlesik hesap
    sonuc = []
    hata_emirler = []
    for em in cps_list:
        try:
            emir_no_int = int(em['emir_no'])
        except Exception:
            continue

        cps_onayli = int(em['cps_onayli'] or 0)
        cps_bekleyen = int(em['cps_bekleyen'] or 0)
        model_local = em.get('model_kod') or em.get('model_adi') or ''

        try:
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
            hata_emirler.append({'emir_no': str(emir_no_int), 'mesaj': str(e)[:120]})

        toplam_yapilan = korgun_yapilan + cps_onayli
        kalan = max(0, hedef - toplam_yapilan)
        if hedef > 0:
            yuzde = round((toplam_yapilan / hedef) * 100, 1)
        else:
            yuzde = 0.0

        sonuc.append({
            'emir_no': str(emir_no_int),
            'model': model,
            'hedef': hedef,
            'korgun_yapilan': korgun_yapilan,
            'cps_yapilan': cps_onayli,
            'cps_bekleyen': cps_bekleyen,
            'yapilan': toplam_yapilan,
            'kalan': kalan,
            'yuzde': yuzde,
        })

    # En yeni emir ustte (emir_no buyukten kucuge)
    sonuc.sort(key=lambda x: int(x['emir_no']), reverse=True)

    return jsonify({
        'success': True, 'ok': True,
        'emirler': sonuc,
        'emir_sayisi': len(sonuc),
        'hata_emirler': hata_emirler,
    })
'''


# ----------------------------------------------------------------------
# 2) HTML - thead degistir
# ----------------------------------------------------------------------
HTML_OLD = '''      <thead>
        <tr>
          <th>ID</th>
          <th>Emir No</th>
          <th>Sipari&#351; No</th>
          <th>Proses</th>
          <th>Hedef Adet</th>
          <th>Tarih</th>
          <th>Durum</th>
        </tr>
      </thead>
      <tbody id="planBody">
        <tr class="h-row-loading"><td colspan="7">Yükleniyor...</td></tr>
      </tbody>'''

HTML_NEW = '''      <thead>
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


# ----------------------------------------------------------------------
# 3) JS override IIFE
# ----------------------------------------------------------------------
JS_BLOCK = r'''


/* ====================================================================
   CPS LOCAL OVERRIDE - /hedef/ PLAN
   - planlariYukle / renderPlanRows yenisi
   - Endpoint: GET /hedef/plan
   - Kolonlar: EMIR | MODEL | HEDEF | YAPILAN | KALAN | %
   - Renkler: <30 kirmizi, 30-70 sari, >=70 yesil
   ==================================================================== */
(function () {
    'use strict';

    function _planEsc(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function _planFmt(n) {
        var x = Number(n);
        if (!isFinite(x)) return _planEsc(n);
        return x.toLocaleString('tr-TR');
    }

    function _planYuzdeRenk(yuzde) {
        var y = Number(yuzde) || 0;
        if (y < 30) return '#dc2626';   // kirmizi
        if (y < 70) return '#f59e0b';   // sari
        return '#10b981';                // yesil
    }

    function _renderPlanV2(emirler) {
        var body = document.getElementById('planBody');
        if (!body) return;
        body.innerHTML = '';
        if (!emirler || emirler.length === 0) {
            body.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:32px; color:var(--text3);">Aktif emir yok.</td></tr>';
            return;
        }
        for (var i = 0; i < emirler.length; i++) {
            var e = emirler[i];
            var renk = _planYuzdeRenk(e.yuzde);
            var modelTxt = e.model || '-';
            var tr = document.createElement('tr');
            tr.innerHTML =
                '<td><strong>E.' + _planEsc(e.emir_no) + '</strong></td>' +
                '<td style="font-size:13px;">' + _planEsc(modelTxt) + '</td>' +
                '<td style="font-family:var(--mono); text-align:right;">' + _planFmt(e.hedef) + '</td>' +
                '<td style="font-family:var(--mono); text-align:right;">' + _planFmt(e.yapilan) + '</td>' +
                '<td style="font-family:var(--mono); text-align:right;">' + _planFmt(e.kalan) + '</td>' +
                '<td style="text-align:center;"><span style="display:inline-block; background:' + renk + '; color:#fff; padding:4px 10px; border-radius:12px; font-weight:700; font-size:12px; min-width:64px;">' + _planEsc(e.yuzde) + '%</span></td>';
            body.appendChild(tr);
        }
    }

    function _planlariYukleV2() {
        var body = document.getElementById('planBody');
        var errBox = document.getElementById('planError');
        if (errBox) errBox.innerHTML = '';
        if (body) {
            body.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:24px; color:var(--text3);">Yükleniyor...</td></tr>';
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
                        body.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:24px; color:var(--red);">PLAN yüklenemedi.</td></tr>';
                    }
                    return;
                }
                var emirler = (r.data && r.data.emirler) || [];
                _renderPlanV2(emirler);
                console.log('CPS/hedef/plan', r.status, emirler.length,
                    r.data.hata_emirler && r.data.hata_emirler.length
                        ? '(uyari: ' + r.data.hata_emirler.length + ' emirde Korgun ozet alinamadi)'
                        : ''
                );
            })
            .catch(function (e) {
                console.error('plan fetch:', e);
                if (body) {
                    body.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:24px; color:var(--red);">Sunucuya ulaşılamadı.</td></tr>';
                }
            });
    }

    // Override globals
    window.planlariYukle = _planlariYukleV2;
    window.renderPlanRows = _renderPlanV2;

    console.log('[CPS LOCAL] /hedef/ PLAN endpoint override yuklendi.');
})();
'''


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

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
    if BACKEND_MARKER in src:
        print("  [BILGI] Endpoint zaten ekli (marker var).")
        return True

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += BACKEND_BLOCK

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] Yeni icerik parse edilemiyor: {e}")
        return False

    bp = backup(ROUTES_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(ROUTES_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] /hedef/plan endpoint'i eklendi.")
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
        print("  [BILGI] Yeni thead zaten mevcut.")
        return True
    if HTML_OLD not in src:
        print("  [HATA] Eski thead bloku bulunamadi.")
        print("         (Belki manuel degistirildi veya format farkli.)")
        return False
    if src.count(HTML_OLD) > 1:
        print("  [HATA] Eski blok birden fazla, belirsiz.")
        return False

    new_src = src.replace(HTML_OLD, HTML_NEW, 1)

    bp = backup(HTML_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(HTML_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] PLAN thead'i 6 kolona guncellendi (EMIR/MODEL/HEDEF/YAPILAN/KALAN/%).")
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
        print("  [BILGI] JS override zaten ekli.")
        return True

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += JS_BLOCK

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] PLAN render override IIFE eklendi.")
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
        print("     Beklenen: 1 satir (E.110626)")
        print("       MODEL  : CRX-71033 - ISIKSIZ SARGILI...")
        print("       HEDEF  : 14000")
        print("       YAPILAN: korgun_yapilan + cps_yapilan(1490)")
        print("       KALAN  : hedef - yapilan")
        print("       %      : renkli badge (~30-70 sari muhtemelen)")
        print()
        print("DevTools Console'da:")
        print("  [CPS LOCAL] /hedef/ PLAN endpoint override yuklendi.")
        print("  CPS/hedef/plan 200 1")
        print()
        print("Direkt JSON test:")
        print("  Browser -> http://127.0.0.1:5057/hedef/plan")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
