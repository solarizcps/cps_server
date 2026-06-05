# -*- coding: utf-8 -*-
"""
setup_plan_zenginlestir.py
--------------------------
PLAN tablosuna 5 yeni alan ekle:
  1) musteri    - get_emir_ozet().cari_adi (mevcut)
  2) termin     - 3 aday COALESCE: Siparis_Har -> Siparis_Kay -> Urt_Emir
  3) son_proses - Urt_con_gch'tan en son EndTarih'li proses
  4) durum      - kalan>0 'Devam', =0 'Tamam', hedef yok 'Plansiz'
  5) gorsel     - StokKart.SResim path (frontend kullanmaz, default ikon)

DOKUNULAN:
  - modules/hedef/routes.py   (/hedef/plan endpoint)
  - templates/hedef/index.html (PLAN thead)
  - static/js/hedef.js (PLAN render)

DOKUNULMAYAN:
  - DB schema
  - Yeni endpoint
  - Diger sekmeler (SABLON/SAPMA/OZET/RAPOR/ONAYLAR/GECMIS)
  - Mevcut alanlar (emir_no, model, hedef, yapilan, kalan, yuzde, siparisler)

GUVENLIK:
  - Tum 3 dosyaya yedek alinir
  - Korgun batch SQL try/except ile sarilir, hata durumunda eski alanlar doner
  - Frontend yeni alanlar yoksa "-" gosterir
"""

import os
import shutil
import datetime
import sys
import re
import ast

CPS_ROOT = r"C:\cps_dev"
HEDEF_ROUTES = os.path.join(CPS_ROOT, "modules", "hedef", "routes.py")
HEDEF_HTML = os.path.join(CPS_ROOT, "templates", "hedef", "index.html")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

ROUTES_MARKER = "# === PLAN_ZENGIN_V1 ==="
HTML_MARKER_BASLA = "<!-- PLAN_ZENGIN_V1_THEAD -->"
JS_MARKER = "[CPS LOCAL] PLAN zengin v1 yuklendi"


# =====================================================================
# 1) BACKEND - /hedef/plan endpoint'inin sonuna ek alanlar
# =====================================================================
# Mevcut routes.py'da hedef_plan() fonksiyonu var.
# 'sonuc' listesi olusturuluyor, sonra siralaniyor.
# Biz siralama'dan ONCE batch SQL ile zenginlestirip ekleyecegiz.
#
# Pattern: 'sonuc.sort(...)' satirindan ONCE ek SQL ve enrichment ekle.

ESKI_SORT = """    # En yeni emir ustte (emir_no buyukten kucuge)
    sonuc.sort(key=lambda x: int(x['emir_no']), reverse=True)"""

YENI_SORT = """    # === PLAN_ZENGIN_V1 ===
    # 5 yeni alan icin batch Korgun sorgusu (try/except - hata olursa eski alanlar doner)
    try:
        if sonuc:
            from modules.common import korgun as _kk_zen
            _emir_listesi = [int(x['emir_no']) for x in sonuc if x.get('emir_no')]
            if _emir_listesi:
                _con = _kk_zen._baglan()
                try:
                    _cur = _con.cursor()
                    _ph = ','.join(['%s'] * len(_emir_listesi))
                    _cur.execute(f\"\"\"
                        SELECT
                            e.EmirNo,
                            e.ModelKod,
                            (SELECT TOP 1 pm.Tanim
                               FROM Urt_con_gch g WITH(NOLOCK)
                               LEFT JOIN Proses_M pm ON pm.Pro = g.Proses
                              WHERE g.EmirNo = e.EmirNo AND g.Cikan > 0
                              ORDER BY g.EndTarih DESC) AS SonProses,
                            (SELECT TOP 1 g.EndTarih
                               FROM Urt_con_gch g WITH(NOLOCK)
                              WHERE g.EmirNo = e.EmirNo AND g.Cikan > 0
                              ORDER BY g.EndTarih DESC) AS SonTarih,
                            COALESCE(
                                (SELECT MIN(sh.TerminTarihi)
                                   FROM Siparis_Har sh WITH(NOLOCK)
                                  WHERE sh.SKOD = e.ModelKod
                                    AND sh.TerminTarihi IS NOT NULL
                                    AND LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''),
                                (SELECT MIN(sk.TerminTarihi)
                                   FROM Siparis_Kay sk WITH(NOLOCK)
                                   INNER JOIN Siparis_Har sh2 ON sh2.SipNo = sk.SipNo
                                  WHERE sh2.SKOD = e.ModelKod
                                    AND sk.TerminTarihi IS NOT NULL),
                                e.TerTarih
                            ) AS Termin,
                            (SELECT TOP 1 sk.SResim
                               FROM StokKart sk WITH(NOLOCK)
                              WHERE sk.SKOD = e.ModelKod) AS Gorsel,
                            (SELECT TOP 1 ck.CName
                               FROM Siparis_Har sh3 WITH(NOLOCK)
                               LEFT JOIN Siparis_Kay sk3 ON sk3.SipNo = sh3.SipNo
                               LEFT JOIN Cari_Kart ck ON ck.CKod = sk3.CariKod
                              WHERE sh3.SKOD = e.ModelKod
                                AND LTRIM(RTRIM(ISNULL(sh3.Durum,''))) = '') AS MusteriAdi
                          FROM Urt_Emir e WITH(NOLOCK)
                         WHERE e.EmirNo IN ({_ph})
                    \"\"\", tuple(_emir_listesi))
                    _zen_map = {}
                    for _r in _cur.fetchall():
                        _zen_map[str(int(_r[0]))] = {
                            'son_proses': _r[2],
                            'son_proses_tarih': _r[3].isoformat() if _r[3] else None,
                            'termin': _r[4].isoformat() if _r[4] else None,
                            'gorsel': _r[5],
                            'musteri': _r[6],
                        }
                    _cur.close()
                finally:
                    _con.close()
                # Sonuca enrichment uygula
                for x in sonuc:
                    _ek = _zen_map.get(str(x.get('emir_no')), {})
                    x['musteri'] = _ek.get('musteri')
                    x['termin'] = _ek.get('termin')
                    x['son_proses'] = _ek.get('son_proses')
                    x['son_proses_tarih'] = _ek.get('son_proses_tarih')
                    x['gorsel'] = _ek.get('gorsel')
                    # durum hesaplama
                    _kalan = x.get('kalan', 0)
                    _hedef = x.get('hedef', 0)
                    if _hedef <= 0:
                        x['durum'] = 'Plansiz'
                    elif _kalan <= 0:
                        x['durum'] = 'Tamam'
                    else:
                        x['durum'] = 'Devam'
    except Exception as _e:
        # Zenginlestirme hatasinda eski alanlar zaten doner, bilgi log
        try:
            print(f'[PLAN_ZENGIN_V1 hata, eski yanit doner]: {_e}')
        except Exception:
            pass

    # En yeni emir ustte (emir_no buyukten kucuge)
    sonuc.sort(key=lambda x: int(x['emir_no']), reverse=True)"""


# =====================================================================
# 2) HTML - PLAN thead'i 7 -> 11 kolon
# =====================================================================
HTML_OLD = """      <thead>
        <tr>
          <th class="text">EM&#304;R</th>
          <th class="text">S&#304;PAR&#304;&#350;LER</th>
          <th class="text">MODEL</th>
          <th class="num">HEDEF</th>
          <th class="num">YAPILAN</th>
          <th class="num">KALAN</th>
          <th class="num">%</th>
        </tr>
      </thead>
      <tbody id="planBody">
        <tr class="h-row-loading"><td colspan="7">Yükleniyor...</td></tr>
      </tbody>"""

HTML_NEW = """      <!-- PLAN_ZENGIN_V1_THEAD -->
      <thead>
        <tr>
          <th class="text" style="width:54px;">G&#214;RSEL</th>
          <th class="text">EM&#304;R</th>
          <th class="text">S&#304;PAR&#304;&#350;</th>
          <th class="text">M&#220;&#350;TER&#304;</th>
          <th class="text">MODEL</th>
          <th class="num">HEDEF</th>
          <th class="num">YAPILAN</th>
          <th class="num">KALAN</th>
          <th class="text">TERM&#304;N</th>
          <th class="text">SON PROSES</th>
          <th class="num">%</th>
        </tr>
      </thead>
      <tbody id="planBody">
        <tr class="h-row-loading"><td colspan="11">Yükleniyor...</td></tr>
      </tbody>"""


# =====================================================================
# 3) JS - PLAN render IIFE override (yeni v5)
# =====================================================================
JS_BLOCK = r'''


/* ====================================================================
   CPS LOCAL - PLAN ZENGIN v1
   - 11 kolon: GORSEL | EMIR | SIPARIS | MUSTERI | MODEL | HEDEF |
                YAPILAN | KALAN | TERMIN | SON PROSES | %
   - Default ikon (UNC path tarayicida acilmaz, gelecek icin path geliyor)
   - Termin renkli pill: <=7 gun kirmizi, <=30 sari, >30 yesil
   - Eski tabloyu BOZMAZ (window override; mevcut v4 dosyada kalir)
   ==================================================================== */
(function () {
    'use strict';

    // Inline default urun ikonu (SVG, base64-free)
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

    function _planEscV5(s) {
        if (s == null) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function _planFmtV5(n) {
        var x = Number(n);
        if (!isFinite(x)) return _planEscV5(n);
        return x.toLocaleString('tr-TR');
    }

    function _planYuzdeRenkV5(yuzde) {
        var y = Number(yuzde) || 0;
        if (y < 30) return '#dc2626';
        if (y < 70) return '#f59e0b';
        return '#10b981';
    }

    // Termin gosterim: tarih + 'X gun kaldi' renkli pill
    function _planTerminHtml(terminIso) {
        if (!terminIso) return '<span style="color:#9ca3af;">-</span>';
        var t = new Date(terminIso);
        if (isNaN(t.getTime())) return '<span style="color:#9ca3af;">-</span>';
        var bugun = new Date();
        bugun.setHours(0, 0, 0, 0);
        var hedef = new Date(t.getFullYear(), t.getMonth(), t.getDate());
        var fark = Math.round((hedef - bugun) / (1000 * 60 * 60 * 24));
        var renk = '#10b981';
        var etiket = '';
        if (fark < 0) {
            renk = '#dc2626';
            etiket = Math.abs(fark) + ' gün geçti';
        } else if (fark === 0) {
            renk = '#dc2626';
            etiket = 'Bugün';
        } else if (fark <= 7) {
            renk = '#dc2626';
            etiket = fark + ' gün';
        } else if (fark <= 30) {
            renk = '#f59e0b';
            etiket = fark + ' gün';
        } else {
            renk = '#10b981';
            etiket = fark + ' gün';
        }
        var tarihStr = String(t.getFullYear()) + '-' +
            String(t.getMonth() + 1).padStart(2, '0') + '-' +
            String(t.getDate()).padStart(2, '0');
        return '<div style="font-family:var(--mono); font-size:11px;">' +
            _planEscV5(tarihStr) + '</div>' +
            '<span style="display:inline-block; background:' + renk +
            '; color:#fff; padding:1px 7px; border-radius:8px; ' +
            'font-size:10px; font-weight:700; margin-top:2px;">' +
            etiket + '</span>';
    }

    function _planSonProsesHtml(adi, tarihIso) {
        if (!adi) return '<span style="color:#9ca3af;">-</span>';
        var ek = '';
        if (tarihIso) {
            var t = new Date(tarihIso);
            if (!isNaN(t.getTime())) {
                var bugun = new Date();
                var fark = Math.round((bugun - t) / (1000 * 60 * 60 * 24));
                if (fark === 0) ek = '(bugün)';
                else if (fark === 1) ek = '(dün)';
                else if (fark > 0) ek = '(' + fark + ' gün önce)';
            }
        }
        return '<div style="font-size:12px;">' + _planEscV5(adi) + '</div>' +
            (ek ? '<div style="font-size:10px; color:var(--text3);">' + ek + '</div>' : '');
    }

    function _planDurumHtml(durum) {
        if (!durum) return '';
        var renk = '#6b7280';
        if (durum === 'Tamam') renk = '#10b981';
        else if (durum === 'Devam') renk = '#3b82f6';
        else if (durum === 'Plansiz') renk = '#9ca3af';
        return '<span style="background:' + renk + '; color:#fff; ' +
            'padding:1px 6px; border-radius:6px; font-size:10px; font-weight:600;">' +
            _planEscV5(durum) + '</span>';
    }

    function _renderPlanV5(emirler) {
        var body = document.getElementById('planBody');
        if (!body) return;
        body.innerHTML = '';
        if (!emirler || emirler.length === 0) {
            body.innerHTML = '<tr><td colspan="11" class="text" ' +
                'style="text-align:center; padding:32px; color:var(--text3);">' +
                'Aktif emir yok.</td></tr>';
            return;
        }
        for (var i = 0; i < emirler.length; i++) {
            var e = emirler[i];
            var renk = _planYuzdeRenkV5(e.yuzde);
            var modelTxt = e.model || '-';
            var sipTxt = e.siparisler || '-';
            var musTxt = e.musteri || '-';
            var tr = document.createElement('tr');
            // GORSEL kolonu: backend path donduruyor ama UNC tarayicida acilmaz
            // Default ikon kullanilacak. Path data attribute olarak tutulur (gelecek icin).
            tr.innerHTML =
                '<td class="text" style="text-align:center; width:54px;">' +
                  '<img src="' + DEFAULT_IKON + '" alt="" data-gorsel="' +
                  _planEscV5(e.gorsel || '') + '" ' +
                  'style="width:36px; height:36px; border-radius:6px; ' +
                  'object-fit:cover; background:#f3f4f6;">' +
                '</td>' +
                '<td class="text txt-strong">E.' + _planEscV5(e.emir_no) + '</td>' +
                '<td class="text" style="font-family:var(--mono); font-size:11px; ' +
                  'color:var(--text2);">' + _planEscV5(sipTxt) + '</td>' +
                '<td class="text" style="font-size:12px;" title="' +
                  _planEscV5(musTxt) + '">' + _planEscV5(musTxt) + '</td>' +
                '<td class="text" style="font-size:13px;" title="' +
                  _planEscV5(modelTxt) + '">' + _planEscV5(modelTxt) + '</td>' +
                '<td class="num" style="font-family:var(--mono);">' +
                  _planFmtV5(e.hedef) + '</td>' +
                '<td class="num" style="font-family:var(--mono);">' +
                  _planFmtV5(e.yapilan) + '</td>' +
                '<td class="num" style="font-family:var(--mono);">' +
                  _planFmtV5(e.kalan) + '</td>' +
                '<td class="text" style="text-align:center;">' +
                  _planTerminHtml(e.termin) + '</td>' +
                '<td class="text">' +
                  _planSonProsesHtml(e.son_proses, e.son_proses_tarih) + '</td>' +
                '<td class="num"><span style="display:inline-block; background:' +
                  renk + '; color:#fff; padding:4px 10px; border-radius:12px; ' +
                  'font-weight:700; font-size:12px; min-width:64px; text-align:center;">' +
                  _planEscV5(e.yuzde) + '%</span></td>';
            body.appendChild(tr);
        }
    }

    function _planlariYukleV5() {
        var body = document.getElementById('planBody');
        var errBox = document.getElementById('planError');
        if (errBox) errBox.innerHTML = '';
        if (body) {
            body.innerHTML = '<tr><td colspan="11" class="text" ' +
                'style="text-align:center; padding:24px; color:var(--text3);">' +
                'Yükleniyor...</td></tr>';
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
                        body.innerHTML = '<tr><td colspan="11" class="text" ' +
                            'style="text-align:center; padding:24px; color:var(--red);">' +
                            'PLAN yüklenemedi.</td></tr>';
                    }
                    return;
                }
                var emirler = (r.data && r.data.emirler) || [];
                _renderPlanV5(emirler);
                console.log('CPS/hedef/plan zengin v1', r.status, emirler.length);
            })
            .catch(function (e) {
                console.error('plan v5 fetch:', e);
                if (body) {
                    body.innerHTML = '<tr><td colspan="11" class="text" ' +
                        'style="text-align:center; padding:24px; color:var(--red);">' +
                        'Sunucuya ulaşılamadı.</td></tr>';
                }
            });
    }

    // v4 uzerine yaz
    window.planlariYukle = _planlariYukleV5;
    window.renderPlanRows = _renderPlanV5;

    console.log('[CPS LOCAL] PLAN zengin v1 yuklendi');
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
    print("1/3 BACKEND: modules/hedef/routes.py")
    print("=" * 64)
    if not os.path.exists(HEDEF_ROUTES):
        print(f"  [HATA] {HEDEF_ROUTES} yok.")
        return False
    with open(HEDEF_ROUTES, 'r', encoding='utf-8') as f:
        src = f.read()
    if ROUTES_MARKER in src:
        print("  [BILGI] Backend zengin v1 zaten ekli.")
        return True

    if ESKI_SORT not in src:
        print("  [HATA] Eski sort satiri bulunamadi.")
        return False
    if src.count(ESKI_SORT) > 1:
        print("  [HATA] Sort cogul.")
        return False

    new_src = src.replace(ESKI_SORT, YENI_SORT, 1)
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False
    bp = backup(HEDEF_ROUTES)
    print(f"  [OK] Yedek: {bp}")
    with open(HEDEF_ROUTES, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] /hedef/plan endpoint'i 5 yeni alan donderir.")
    return True


def patch_html():
    print()
    print("=" * 64)
    print("2/3 HTML: templates/hedef/index.html")
    print("=" * 64)
    if not os.path.exists(HEDEF_HTML):
        print(f"  [HATA] {HEDEF_HTML} yok.")
        return False
    with open(HEDEF_HTML, 'r', encoding='utf-8') as f:
        src = f.read()
    if HTML_MARKER_BASLA in src:
        print("  [BILGI] HTML zengin v1 zaten ekli.")
        return True
    if HTML_OLD not in src:
        print("  [HATA] Eski thead bulunamadi.")
        return False
    if src.count(HTML_OLD) > 1:
        print("  [HATA] Eski thead cogul.")
        return False

    new_src = src.replace(HTML_OLD, HTML_NEW, 1)
    bp = backup(HEDEF_HTML)
    print(f"  [OK] Yedek: {bp}")
    with open(HEDEF_HTML, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] PLAN thead 7 -> 11 kolon.")
    return True


def patch_js():
    print()
    print("=" * 64)
    print("3/3 JS: static/js/hedef.js")
    print("=" * 64)
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} yok.")
        return False
    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()
    if JS_MARKER in src:
        print("  [BILGI] JS zengin v1 zaten ekli.")
        return True

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += JS_BLOCK

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] PLAN render v5 IIFE eklendi (v4'u override eder).")
    return True


def main():
    print("=" * 64)
    print("PLAN ZENGIN v1 - 5 yeni alan")
    print("=" * 64)
    print("Kapsamda:")
    print("  - Backend: musteri, termin, son_proses, durum, gorsel")
    print("  - HTML: 7 -> 11 kolon thead")
    print("  - JS: yeni render (default ikon, renkli termin)")
    print()
    print("CPS_KURALLAR uyum:")
    print("  ✓ Korgun read-only (yalnizca SELECT)")
    print("  ✓ Yeni endpoint yok")
    print("  ✓ DB schema dokunulmadi")
    print("  ✓ Diger sekmeler etkilenmedi")
    print("  ✓ Hata olursa eski alanlar doner (try/except)")

    ok1 = patch_routes()
    ok2 = patch_html()
    ok3 = patch_js()

    print()
    print("=" * 64)
    if ok1 and ok2 and ok3:
        print("TAMAM.")
        print("=" * 64)
        print()
        print("YAPILACAK:")
        print("  1) CPS sunucusunu yeniden baslat (Korgun SQL eklendi)")
        print("  2) Browser Ctrl+F5")
        print("  3) /hedef/ -> PLAN sekmesi")
        print()
        print("BEKLENEN:")
        print("  - 11 kolon: Gorsel | Emir | Siparis | Musteri | Model |")
        print("              Hedef | Yapilan | Kalan | Termin | Son Proses | %")
        print("  - Gorsel: default kucuk ikon")
        print("  - Termin: tarih + renkli 'X gun' pill")
        print("  - Son Proses: ad + 'X gun once'")
        print("  - Musteri: cari adi (ornek: Lc Waikiki)")
        print()
        print("TEST:")
        print("  fetch('/hedef/plan',{credentials:'include'})")
        print("    .then(r=>r.json())")
        print("    .then(d=>console.log(d.emirler[0]))")
        print("  Donen alanlar (yeniler dahil):")
        print("    emir_no, model, hedef, yapilan, kalan, yuzde,")
        print("    musteri, termin, son_proses, son_proses_tarih, gorsel, durum")
        print()
        print("Hata olursa eski alanlar yine doner, tablo bozulmaz.")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
