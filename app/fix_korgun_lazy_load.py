# -*- coding: utf-8 -*-
"""
fix_korgun_lazy_load.py
-----------------------
Strateji: 
  1) Korgun helper get_siparis_emirleri'nden YAVAS batch SQL'i KALDIR
     -> ilk fetch tekrar HIZLI (sadece Siparis_Har)
  2) Yeni endpoint /hedef/siparis/emir-detay -> sadece Urt_Em_gch SUM+RKOD
     Bu sorgu DA yavas olabilir ama ekran zaten gosterildiginde calisir
  3) Frontend: ana fetch sonrasi arka planda detay endpoint'i cagir,
     emir satirlarinda EmirMiktari/RKOD'u guncelle
"""

import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
KORGUN_PY = os.path.join(CPS_ROOT, "modules", "common", "korgun.py")
HEDEF_ROUTES = os.path.join(CPS_ROOT, "modules", "hedef", "routes.py")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

KORGUN_MARKER_REVERT = "# === FAZ 4.6 B3 LAZY: batch kaldirildi ==="
ROUTES_MARKER = "# === FAZ 4.6 B3 emir-detay endpoint ==="
JS_MARKER = "[CPS LOCAL] FAZ 4.6 B3 lazy detay"


# =====================================================================
# 1) Korgun helper'dan yavas batch'i kaldir
# =====================================================================

# Onceki polish + nolock blogu (timeout veren):
ESKI_BATCH = '''            # === FAZ 4.6 B3 polish + NOLOCK ===
            # WITH(NOLOCK) ile lock beklemiyoruz, ayni planlama_server.py gibi
            # Read-only, guvenli.
            tum_emir_nos = [int(d['EmirNo']) for d in ana_dicts] + \\
                           [int(d['EmirNo']) for d in yari_dicts]
            emir_giren_map = {}
            emir_rkod_map = {}
            if tum_emir_nos:
                placeholders = ','.join(['%s'] * len(tum_emir_nos))
                cur.execute(f"""
                    SELECT EmirNo,
                           COALESCE(SUM(Giren), 0) AS toplam_giren,
                           MAX(CASE WHEN RKOD IS NOT NULL AND RKOD < 100
                                    THEN RKOD ELSE NULL END) AS rkod_temiz
                    FROM Urt_Em_gch WITH(NOLOCK)
                    WHERE EmirNo IN ({placeholders})
                    GROUP BY EmirNo
                """, tuple(tum_emir_nos))
                for r in cur.fetchall():
                    e_no = int(r[0])
                    emir_giren_map[e_no] = float(r[1] or 0)
                    emir_rkod_map[e_no] = r[2]

            # Ana emirlerin EmirMiktari'ni SUM(Giren) ile guncelle
            # Fallback: Siparis_Har.Miktar (zaten EmirMiktari=hm_f olarak set edilmisti)
            for em in emirler:
                if em.get('EmirTip') == 'ana':
                    giren = emir_giren_map.get(em['EmirNo'])
                    if giren and giren > 0:
                        em['EmirMiktari'] = giren  # gercek emir miktari
                    # else: ana emirde hareket yok -> SiparisMiktari fallback olarak EmirMiktari kalsin'''

YENI_BATCH = '''            # === FAZ 4.6 B3 LAZY: batch kaldirildi ===
            # Urt_Em_gch toplam SUM/MAX sorgusu yavas. Ayri endpoint /hedef/siparis/emir-detay
            # cagrilarak frontend'den lazy load yapilir.
            # Burada sadece Siparis_Har bilgisi var, hizli.
            emir_giren_map = {}
            emir_rkod_map = {}'''

# Alt emir blogundaki rkod/giren atamalarini da temizle (hala zinciri bozmayalim)
ESKI_ALT = '''            # Yari mamul (alt) emirler - EmirMiktari = SUM(Giren)
            for d in yari_dicts:
                emir_no_int = int(d['EmirNo'])
                parent_no = int(d.get('ParentEmirNo')) if d.get('ParentEmirNo') is not None else None
                ca_alt = parent_cari_map.get(parent_no) if parent_no else None
                miktar_alt = emir_giren_map.get(emir_no_int)
                if miktar_alt == 0:
                    miktar_alt = None
                rkod_alt = emir_rkod_map.get(emir_no_int)
                emirler.append({
                    'EmirNo': emir_no_int,
                    'ModelKod': d.get('ModelKod'),
                    'ModelAdi': d.get('ModelAdi'),
                    'EmirTip': 'alt',
                    'TipKod': (d.get('Tip') or '').strip(),
                    'Location': (d.get('Location') or '').strip() if d.get('Location') else None,
                    'Durum': d.get('Durum'),
                    'HedefMiktar': miktar_alt,
                    'EmirMiktari': miktar_alt,
                    'SipNo': sip_no_int,
                    'ParentEmirNo': parent_no,
                    'CariAdi': ca_alt,
                    'RKOD': rkod_alt,
                })
            # Ana emir RKOD'larini emir listesinde guncelle
            for em in emirler:
                if em.get('EmirTip') == 'ana':
                    em['RKOD'] = emir_rkod_map.get(em['EmirNo'])'''

YENI_ALT = '''            # Yari mamul (alt) emirler - miktar/RKOD lazy load icin null
            for d in yari_dicts:
                emir_no_int = int(d['EmirNo'])
                parent_no = int(d.get('ParentEmirNo')) if d.get('ParentEmirNo') is not None else None
                ca_alt = parent_cari_map.get(parent_no) if parent_no else None
                emirler.append({
                    'EmirNo': emir_no_int,
                    'ModelKod': d.get('ModelKod'),
                    'ModelAdi': d.get('ModelAdi'),
                    'EmirTip': 'alt',
                    'TipKod': (d.get('Tip') or '').strip(),
                    'Location': (d.get('Location') or '').strip() if d.get('Location') else None,
                    'Durum': d.get('Durum'),
                    'HedefMiktar': None,
                    'EmirMiktari': None,         # lazy: /hedef/siparis/emir-detay
                    'SipNo': sip_no_int,
                    'ParentEmirNo': parent_no,
                    'CariAdi': ca_alt,
                    'RKOD': None,                # lazy
                })'''


# =====================================================================
# 2) Yeni endpoint /hedef/siparis/emir-detay
# =====================================================================
ROUTES_BLOCK = '''


# === FAZ 4.6 B3 emir-detay endpoint ===
# Lazy detay: belirli emir_no listesi icin Urt_Em_gch SUM(Giren) ve RKOD
# Sayfa acilinca arka planda cagrilir, ekrandaki satirlar update edilir.
@hedef_bp.route('/siparis/emir-detay', methods=['GET'])
def hedef_siparis_emir_detay():
    """GET /hedef/siparis/emir-detay?emirler=109772,109773,...
    Belirli emirler icin Urt_Em_gch'den SUM(Giren) ve RKOD donerir.
    """
    from flask import jsonify, request
    try:
        emirler_str = (request.args.get('emirler') or '').strip()
        if not emirler_str:
            return jsonify({'ok': False, 'mesaj': 'emirler param gerekli', 'detay': {}}), 400

        emir_nos = []
        for x in emirler_str.split(','):
            x = x.strip()
            if x.isdigit():
                emir_nos.append(int(x))
        if not emir_nos:
            return jsonify({'ok': False, 'mesaj': 'gecerli emir_no yok', 'detay': {}}), 400

        # Cok fazla emir limit
        emir_nos = emir_nos[:100]

        from modules.common import korgun as _kk
        con = _kk._baglan()
        try:
            cur = con.cursor()
            placeholders = ','.join(['%s'] * len(emir_nos))
            cur.execute(f"""
                SELECT EmirNo,
                       COALESCE(SUM(Giren), 0) AS toplam_giren,
                       MAX(CASE WHEN RKOD IS NOT NULL AND RKOD < 100
                                THEN RKOD ELSE NULL END) AS rkod_temiz
                FROM Urt_Em_gch WITH(NOLOCK)
                WHERE EmirNo IN ({placeholders})
                GROUP BY EmirNo
            """, tuple(emir_nos))
            detay = {}
            for r in cur.fetchall():
                e_no = int(r[0])
                detay[str(e_no)] = {
                    'EmirMiktari': float(r[1] or 0) or None,
                    'RKOD': r[2],
                }
            cur.close()
        finally:
            con.close()

        return jsonify({'ok': True, 'detay': detay, 'emir_sayisi': len(detay)})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200], 'detay': {}}), 500
'''


# =====================================================================
# 3) Frontend: ana fetch sonrasi detay endpoint'i cagir
# =====================================================================

# _yukleProsesSayilari fonksiyonundan once detay-load ekleyelim.
# Aslinda _renderTablolar() fonksiyonu cagrilmadan once ekrani goster, sonra
# detay'i arka planda fetch et.

JS_OLD = """            _state.emirler = r.data.emirler || [];
            if (_state.emirler.length === 0) {
                sonuc.innerHTML = '<div class="sb3-empty">Bu siparişte emir bulunamadı.</div>';
                return;
            }

            // Proses sayilari arkadan yuklensin
            var emirNos = _state.emirler.map(function (e) { return e.EmirNo; });
            _yukleProsesSayilari(emirNos).then(function () { _renderTablolar(); });"""

JS_NEW = """            _state.emirler = r.data.emirler || [];
            if (_state.emirler.length === 0) {
                sonuc.innerHTML = '<div class="sb3-empty">Bu siparişte emir bulunamadı.</div>';
                return;
            }

            // === FAZ 4.6 B3 lazy detay ===
            // Proses sayilari arkadan yuklensin
            var emirNos = _state.emirler.map(function (e) { return e.EmirNo; });
            _yukleProsesSayilari(emirNos).then(function () { _renderTablolar(); });

            // Emir detay (Korgun SUM/RKOD) arkadan yuklensin - sayfa zaten render olur
            _yukleEmirDetay(emirNos);"""


# Yeni fonksiyon: _yukleEmirDetay
JS_FUNC_BLOCK = r'''


/* ====================================================================
   CPS LOCAL - FAZ 4.6 B3 lazy detay
   Korgun SUM(Giren) ve RKOD ayri endpointten arka planda cekilir.
   ==================================================================== */
(function () {
    'use strict';

    var BATCH = 30;  // Korgun timeout'undan kacin: 30'ar emir batch

    function _yukleEmirDetay(emirNos) {
        if (!emirNos || emirNos.length === 0) return;
        // Batch'lere bol
        for (var i = 0; i < emirNos.length; i += BATCH) {
            var chunk = emirNos.slice(i, i + BATCH);
            (function (c) {
                var qs = c.join(',');
                fetch('/hedef/siparis/emir-detay?emirler=' + encodeURIComponent(qs), {
                    credentials: 'include'
                }).then(function (r) { return r.json(); })
                  .then(function (d) {
                      if (!d || !d.ok) return;
                      var detay = d.detay || {};
                      var st = window._sb3State;
                      if (!st || !st.emirler) return;
                      var degisti = false;
                      st.emirler.forEach(function (e) {
                          var k = String(e.EmirNo);
                          if (detay[k]) {
                              if (detay[k].EmirMiktari != null) {
                                  e.EmirMiktari = detay[k].EmirMiktari;
                                  degisti = true;
                              }
                              if (detay[k].RKOD != null) {
                                  e.RKOD = detay[k].RKOD;
                                  degisti = true;
                              }
                          }
                      });
                      if (degisti && typeof window._sb3RenderTablolar === 'function') {
                          window._sb3RenderTablolar();
                      }
                  }).catch(function (e) {
                      console.warn('emir-detay batch hata:', e);
                  });
            })(chunk);
        }
    }

    window._yukleEmirDetayBatch = _yukleEmirDetay;

    console.log('[CPS LOCAL] FAZ 4.6 B3 lazy detay yuklendi.');
})();
'''


# Ana B3 IIFE icindeki _yukleEmirDetay'i kullanmak icin window'a expose etmek gerek
# _renderTablolar ve _state'i de window'a expose ederek erisim
JS_OLD_STATE_EXPOSE = """    window.sb3Hazirla = _hazirla;
    window.sb3Getir = _emirleriGetir;

    console.log('[CPS LOCAL] FAZ 4.6 B3 siparis-uygula yuklendi.');"""

JS_NEW_STATE_EXPOSE = """    window.sb3Hazirla = _hazirla;
    window.sb3Getir = _emirleriGetir;
    // FAZ 4.6 B3 lazy detay icin
    window._sb3State = _state;
    window._sb3RenderTablolar = _renderTablolar;

    console.log('[CPS LOCAL] FAZ 4.6 B3 siparis-uygula yuklendi.');"""


# JS_NEW icinde _yukleEmirDetay cagrisi var ama tanim disarda IIFE'de.
# IIFE icinden window._yukleEmirDetayBatch'i cagir.
JS_NEW_FIX = """            _state.emirler = r.data.emirler || [];
            if (_state.emirler.length === 0) {
                sonuc.innerHTML = '<div class="sb3-empty">Bu siparişte emir bulunamadı.</div>';
                return;
            }

            // === FAZ 4.6 B3 lazy detay ===
            // Proses sayilari arkadan yuklensin
            var emirNos = _state.emirler.map(function (e) { return e.EmirNo; });
            _yukleProsesSayilari(emirNos).then(function () { _renderTablolar(); });

            // Emir detay (Korgun SUM/RKOD) arkadan yuklensin - sayfa zaten render olur
            if (typeof window._yukleEmirDetayBatch === 'function') {
                window._yukleEmirDetayBatch(emirNos);
            }"""


def backup(path):
    if not os.path.exists(path):
        return None
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = path + f'.bak_{ts}'
    shutil.copy2(path, bp)
    return bp


def patch_korgun():
    print()
    print("=" * 64)
    print("1/3 KORGUN: yavas batch'i kaldir")
    print("=" * 64)
    if not os.path.exists(KORGUN_PY):
        print(f"  [HATA] {KORGUN_PY} yok.")
        return False

    with open(KORGUN_PY, 'r', encoding='utf-8') as f:
        src = f.read()

    if KORGUN_MARKER_REVERT in src:
        print("  [BILGI] Lazy revert zaten ekli.")
        return True

    if ESKI_BATCH not in src:
        print("  [HATA] ESKI_BATCH bulunamadi.")
        return False
    if ESKI_ALT not in src:
        print("  [HATA] ESKI_ALT bulunamadi.")
        return False

    new_src = src.replace(ESKI_BATCH, YENI_BATCH, 1).replace(ESKI_ALT, YENI_ALT, 1)
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False

    bp = backup(KORGUN_PY)
    print(f"  [OK] Yedek: {bp}")
    with open(KORGUN_PY, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Yavas batch kaldirildi. Hizli ilk fetch.")
    return True


def patch_routes():
    print()
    print("=" * 64)
    print("2/3 ROUTES: emir-detay lazy endpoint")
    print("=" * 64)
    if not os.path.exists(HEDEF_ROUTES):
        print(f"  [HATA] {HEDEF_ROUTES} yok.")
        return False
    with open(HEDEF_ROUTES, 'r', encoding='utf-8') as f:
        src = f.read()
    if ROUTES_MARKER in src:
        print("  [BILGI] emir-detay endpoint zaten ekli.")
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
    print("  [OK] /hedef/siparis/emir-detay endpoint eklendi.")
    return True


def patch_js():
    print()
    print("=" * 64)
    print("3/3 JS: lazy detay caller + state expose")
    print("=" * 64)
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} yok.")
        return False
    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()
    if JS_MARKER in src:
        print("  [BILGI] JS lazy detay zaten ekli.")
        return True

    if JS_OLD not in src:
        print("  [HATA] JS_OLD bulunamadi.")
        return False
    if src.count(JS_OLD) > 1:
        print("  [HATA] JS_OLD cogul.")
        return False
    if JS_OLD_STATE_EXPOSE not in src:
        print("  [HATA] JS_OLD_STATE_EXPOSE bulunamadi.")
        return False
    if src.count(JS_OLD_STATE_EXPOSE) > 1:
        print("  [HATA] JS_OLD_STATE_EXPOSE cogul.")
        return False

    new_src = src.replace(JS_OLD, JS_NEW_FIX, 1)
    new_src = new_src.replace(JS_OLD_STATE_EXPOSE, JS_NEW_STATE_EXPOSE, 1)
    new_src += JS_FUNC_BLOCK

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Lazy detay caller + state expose eklendi.")
    return True


def main():
    print("=" * 64)
    print("FAZ 4.6 B3 - LAZY LOAD STRATEJISI")
    print("=" * 64)
    print("Strateji:")
    print("  - Ana fetch artik Urt_Em_gch'a girmiyor (HIZLI)")
    print("  - Sayfa acilinca emir-detay endpoint 30'lik batch'lerle cagrilir")
    print("  - Emir miktari/RKOD doldukca tablo otomatik update")

    ok1 = patch_korgun()
    ok2 = patch_routes()
    ok3 = patch_js()

    print()
    print("=" * 64)
    if ok1 and ok2 and ok3:
        print("TAMAM.")
        print("=" * 64)
        print()
        print("YAPILACAK:")
        print("  1) CPS sunucusunu yeniden baslat")
        print("  2) Browser'da Ctrl+F5")
        print("  3) /hedef/ -> SABLON -> 33558 -> Emirleri Getir")
        print()
        print("Beklenen:")
        print("  - HIZLI sayfa: tablo 1-2 sn icinde gelir")
        print("  - Ilk an: ANA emirler dolu (Siparis_Har), ALT emirlerde miktar ve RKOD '-'")
        print("  - 5-15 sn sonra: ALT emirlerde de gercek miktar/RKOD doldukca update")
        print("  - Bu surede sayfada calismaya devam edebilirsin")
        print()
        print("Console:")
        print("  [CPS LOCAL] FAZ 4.6 B3 lazy detay yuklendi.")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
