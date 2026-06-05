# -*- coding: utf-8 -*-
"""
fix_b3_three_issues.py
----------------------
Uc duzeltme:
  1) Frontend toplam hesabi: EmirMiktari'nin canli degeriyle, lazy update
     sonrasinda da yeniden hesapla
  2) Alt emirleri ATKI/GOVDE/DIGER olarak alt gruplara ayir (ModelKod'a gore)
  3) RENK fallback: lazy detay sirasinda RKOD bulunamazsa Urt_con_gch'tan dene,
     hala yoksa MIN(RKOD>0) kullan
"""

import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
HEDEF_ROUTES = os.path.join(CPS_ROOT, "modules", "hedef", "routes.py")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

ROUTES_MARKER = "# === FAZ 4.6 B3 emir-detay v2 ==="
JS_MARKER = "[CPS LOCAL] FAZ 4.6 B3 polish v2"


# =====================================================================
# 1) Backend: emir-detay endpoint'inde RENK fallback
# =====================================================================
ROUTES_OLD = '''        from modules.common import korgun as _kk
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
            con.close()'''

ROUTES_NEW = '''        from modules.common import korgun as _kk
        con = _kk._baglan()
        try:
            cur = con.cursor()
            placeholders = ','.join(['%s'] * len(emir_nos))
            # Once Urt_Em_gch
            cur.execute(f"""
                SELECT EmirNo,
                       COALESCE(SUM(Giren), 0) AS toplam_giren,
                       MAX(CASE WHEN RKOD IS NOT NULL AND RKOD > 0 AND RKOD < 100
                                THEN RKOD ELSE NULL END) AS rkod_max,
                       MIN(CASE WHEN RKOD IS NOT NULL AND RKOD > 0 AND RKOD < 100
                                THEN RKOD ELSE NULL END) AS rkod_min
                FROM Urt_Em_gch WITH(NOLOCK)
                WHERE EmirNo IN ({placeholders})
                GROUP BY EmirNo
            """, tuple(emir_nos))
            detay = {}
            eksik_rkod = []
            for r in cur.fetchall():
                e_no = int(r[0])
                # Once max'i, yoksa min'i kullan (her ikisi de < 100)
                rkod = r[2] if r[2] is not None else r[3]
                detay[str(e_no)] = {
                    'EmirMiktari': float(r[1] or 0) or None,
                    'RKOD': rkod,
                }
                if rkod is None:
                    eksik_rkod.append(e_no)

            # Fallback: RKOD bulunamayan emirler icin Urt_con_gch dene
            if eksik_rkod:
                ph2 = ','.join(['%s'] * len(eksik_rkod))
                try:
                    cur.execute(f"""
                        SELECT EmirNo,
                               MAX(CASE WHEN RKOD IS NOT NULL AND RKOD > 0 AND RKOD < 100
                                        THEN RKOD ELSE NULL END) AS rkod_temiz
                        FROM Urt_con_gch WITH(NOLOCK)
                        WHERE EmirNo IN ({ph2})
                        GROUP BY EmirNo
                    """, tuple(eksik_rkod))
                    for r in cur.fetchall():
                        e_no = int(r[0])
                        if r[1] is not None:
                            detay[str(e_no)]['RKOD'] = r[1]
                except Exception:
                    pass

            cur.close()
        finally:
            con.close()'''


# =====================================================================
# 2) Frontend: toplam hesap + alt grup ayrimi
# =====================================================================

# Toplam hesabi: hem ilk render hem lazy update sonrasi - bunu ayri func yap
# Mevcut sb3Info atama:
JS_OLD_INFO = """            // === FAZ 4.6 B3 polish ===
            var _toplamCift = 0;
            _state.emirler.forEach(function (e) {
                var m = (e.EmirMiktari != null ? e.EmirMiktari
                    : e.HedefMiktar != null ? e.HedefMiktar
                    : 0);
                _toplamCift += Number(m) || 0;
            });
            var _anaSayi = r.data.ana_sayisi || 0;
            var _altSayi = r.data.alt_sayisi || 0;
            var _emirSayi = r.data.emir_sayisi || _state.emirler.length;
            document.getElementById('sb3Info').innerHTML =
                '<strong>Sipariş ' + sipno + '</strong> &nbsp;•&nbsp; ' +
                '<span style=\"color:#16a34a;font-weight:600;\">' + _emirSayi + ' emir</span> ' +
                '(<span style=\"color:#15803d;\">' + _anaSayi + ' ana</span> / ' +
                '<span style=\"color:#1e40af;\">' + _altSayi + ' alt</span>) ' +
                '&nbsp;•&nbsp; ' +
                '<span style=\"color:#7c3aed;font-weight:600;\">Toplam: ' +
                _toplamCift.toLocaleString('tr-TR') + ' çift</span>';"""

JS_NEW_INFO = """            // === FAZ 4.6 B3 polish v2 ===
            // Toplam canli hesap - lazy update'lerden sonra da yeniden cagrilacak
            _state.sipnoSon = sipno;
            _state.anaSayi = r.data.ana_sayisi || 0;
            _state.altSayi = r.data.alt_sayisi || 0;
            _state.emirSayi = r.data.emir_sayisi || _state.emirler.length;
            _ozetGuncelle();"""


# Yeni helper fonksiyon: _ozetGuncelle (ayrı tanım eklenecek)
# Bunu _renderTablolar'dan ÖNCE tanımlamamız gerek. _yukleProsesSayilari'nın
# tanımının yanına eklemek en temizi.

JS_OLD_PROSES_FN = """    function _yukleProsesSayilari(emirNos) {"""

JS_NEW_PROSES_FN = """    function _ozetGuncelle() {
        var box = document.getElementById('sb3Info');
        if (!box) return;
        var toplam = 0;
        (_state.emirler || []).forEach(function (e) {
            var m = (e.EmirMiktari != null ? e.EmirMiktari
                : e.HedefMiktar != null ? e.HedefMiktar
                : 0);
            toplam += Number(m) || 0;
        });
        box.innerHTML =
            '<strong>Sipariş ' + (_state.sipnoSon || '') + '</strong> &nbsp;•&nbsp; ' +
            '<span style=\"color:#16a34a;font-weight:600;\">' + (_state.emirSayi || 0) + ' emir</span> ' +
            '(<span style=\"color:#15803d;\">' + (_state.anaSayi || 0) + ' ana</span> / ' +
            '<span style=\"color:#1e40af;\">' + (_state.altSayi || 0) + ' alt</span>) ' +
            '&nbsp;•&nbsp; ' +
            '<span style=\"color:#7c3aed;font-weight:600;\">Toplam: ' +
            toplam.toLocaleString('tr-TR') + ' çift</span>';
    }
    window._sb3OzetGuncelle = _ozetGuncelle;

    function _yukleProsesSayilari(emirNos) {"""


# Alt grup ayrimi: _renderTablolar fonksiyonu icinde alt'i ATKI/GOVDE/DIGER olarak ayır
JS_OLD_RENDER = """        var ana = _state.emirler.filter(function (e) { return e.EmirTip === 'ana'; });
        var alt = _state.emirler.filter(function (e) { return e.EmirTip === 'alt'; });

        var html = [];

        // Toplu uygulama bari (sablon varsa)"""

JS_NEW_RENDER = """        var ana = _state.emirler.filter(function (e) { return e.EmirTip === 'ana'; });
        var altHepsi = _state.emirler.filter(function (e) { return e.EmirTip === 'alt'; });

        // === FAZ 4.6 B3 polish v2: alt emirleri ATKI/GOVDE/DIGER ayir ===
        function _altKategori(e) {
            var t = ((e.ModelKod || '') + ' ' + (e.ModelAdi || '')).toUpperCase();
            if (t.indexOf('ATKI') !== -1 || t.indexOf('ATKİ') !== -1) return 'atki';
            if (t.indexOf('GOVDE') !== -1 || t.indexOf('GÖVDE') !== -1) return 'govde';
            if (t.indexOf('TABAN') !== -1) return 'taban';
            if (t.indexOf('SAYA') !== -1) return 'saya';
            return 'diger';
        }
        var altGruplari = { atki: [], govde: [], taban: [], saya: [], diger: [] };
        altHepsi.forEach(function (e) {
            var k = _altKategori(e);
            altGruplari[k].push(e);
        });

        var html = [];

        // Toplu uygulama bari (sablon varsa)"""


# Alt emir tek grup yerine 4-5 ayrı grup olarak render edilsin
JS_OLD_GRUP = """        html.push(_grupHTML('📦 Ana Emirler (Mamul)', 'ana', ana, 'ana'));
        html.push(_grupHTML('🔧 Alt Emirler (Yarı Mamul)', 'alt', altHepsi, 'alt'));"""

JS_NEW_GRUP = """        html.push(_grupHTML('📦 Ana Emirler (Mamul)', 'ana', ana, 'ana'));
        if (altGruplari.atki.length > 0)
            html.push(_grupHTML('🪡 Atkı Emirleri (Yarı Mamul)', 'alt', altGruplari.atki, 'alt_atki'));
        if (altGruplari.govde.length > 0)
            html.push(_grupHTML('🦶 Gövde Emirleri (Yarı Mamul)', 'alt', altGruplari.govde, 'alt_govde'));
        if (altGruplari.taban.length > 0)
            html.push(_grupHTML('👟 Taban Emirleri (Yarı Mamul)', 'alt', altGruplari.taban, 'alt_taban'));
        if (altGruplari.saya.length > 0)
            html.push(_grupHTML('🧵 Saya Emirleri (Yarı Mamul)', 'alt', altGruplari.saya, 'alt_saya'));
        if (altGruplari.diger.length > 0)
            html.push(_grupHTML('🔧 Diğer Alt Emirler (Yarı Mamul)', 'alt', altGruplari.diger, 'alt_diger'));"""


# JS_FUNC_BLOCK lazy detay sonrası _ozetGuncelle de çağırsın
JS_OLD_LAZY = """                      if (degisti && typeof window._sb3RenderTablolar === 'function') {
                          window._sb3RenderTablolar();
                      }"""

JS_NEW_LAZY = """                      if (degisti) {
                          if (typeof window._sb3RenderTablolar === 'function')
                              window._sb3RenderTablolar();
                          if (typeof window._sb3OzetGuncelle === 'function')
                              window._sb3OzetGuncelle();
                      }"""


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
    print("1/2 ROUTES: emir-detay RENK fallback")
    print("=" * 64)
    if not os.path.exists(HEDEF_ROUTES):
        print(f"  [HATA] {HEDEF_ROUTES} yok.")
        return False
    with open(HEDEF_ROUTES, 'r', encoding='utf-8') as f:
        src = f.read()
    if ROUTES_MARKER in src:
        print("  [BILGI] v2 zaten ekli.")
        return True
    if ROUTES_OLD not in src:
        print("  [HATA] ROUTES_OLD bulunamadi.")
        return False
    if src.count(ROUTES_OLD) > 1:
        print("  [HATA] ROUTES_OLD cogul.")
        return False

    new_src = src.replace(ROUTES_OLD, ROUTES_NEW, 1)
    new_src = new_src.replace("# === FAZ 4.6 B3 emir-detay endpoint ===",
                              "# === FAZ 4.6 B3 emir-detay endpoint ===\n# === FAZ 4.6 B3 emir-detay v2 ===", 1)

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False

    bp = backup(HEDEF_ROUTES)
    print(f"  [OK] Yedek: {bp}")
    with open(HEDEF_ROUTES, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] RKOD fallback eklendi (Urt_con_gch).")
    return True


def patch_js():
    print()
    print("=" * 64)
    print("2/2 FRONTEND: toplam canli + alt grup ayrimi")
    print("=" * 64)
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} yok.")
        return False
    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()
    if JS_MARKER in src:
        print("  [BILGI] JS v2 zaten ekli.")
        return True

    repls = [
        ("JS_OLD_INFO", JS_OLD_INFO, JS_NEW_INFO),
        ("JS_OLD_PROSES_FN", JS_OLD_PROSES_FN, JS_NEW_PROSES_FN),
        ("JS_OLD_RENDER", JS_OLD_RENDER, JS_NEW_RENDER),
        ("JS_OLD_GRUP", JS_OLD_GRUP, JS_NEW_GRUP),
        ("JS_OLD_LAZY", JS_OLD_LAZY, JS_NEW_LAZY),
    ]

    new_src = src
    for ad, old, new in repls:
        if old not in new_src:
            print(f"  [HATA] {ad} bulunamadi.")
            return False
        if new_src.count(old) > 1:
            print(f"  [HATA] {ad} cogul ({new_src.count(old)}).")
            return False
        new_src = new_src.replace(old, new, 1)
        print(f"  [OK] {ad}")

    new_src += "\n/* " + JS_MARKER + " */\n"

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Toplam canli + alt grup ayrimi eklendi.")
    return True


def main():
    print("=" * 64)
    print("FAZ 4.6 B3 - Uc duzeltme")
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
        print("  1) CPS sunucusunu yeniden baslat (routes degisti)")
        print("  2) Browser'da Ctrl+F5")
        print("  3) /hedef/ -> SABLON -> 33558 -> Emirleri Getir")
        print()
        print("Beklenen:")
        print("  - Toplam: 26.400 cift gibi gercek rakam (210.000 degil)")
        print("  - Lazy update sonrasinda toplam yeniden hesaplanir")
        print()
        print("  Alt emir gruplari:")
        print("    🪡 Atki Emirleri (X)")
        print("    🦶 Govde Emirleri (Y)")
        print("    Diger gruplar varsa (Taban, Saya, Diger)")
        print()
        print("  RENK:")
        print("    109774, 109810 gibi '-' satirlarinda artik renk dolar")
        print("    (Urt_con_gch fallback ile)")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
