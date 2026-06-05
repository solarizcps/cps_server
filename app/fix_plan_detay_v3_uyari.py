# -*- coding: utf-8 -*-
"""
fix_plan_detay_v3_uyari.py
--------------------------
PLAN detay paneli yanilticidan duzelt:
  1) Alt emirde proses YOKSA takildi bandi GOSTERME
  2) Yerine uyari: "Uretim alt parcalara baglanmamis"
  3) Bos alt blok mesaji: "HENUZ PROSES YOK (uretim ana emirde gorunuyor)"
  4) Takildi sadece alt emirlerde proses varsa hesaplansin

DEGISEN:
  - Backend: takildi algoritmasi (sadece alt prosesler varsa)
  - Frontend: bant render mantigi (uyari modu)

DOKUNULMAYAN:
  - Endpoint URL
  - Diger sekmeler
  - DB
"""
import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
HEDEF_ROUTES = os.path.join(CPS_ROOT, "modules", "hedef", "routes.py")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

ROUTES_MARKER = "# === V3 takildi-uyari ==="
JS_MARKER = "[CPS LOCAL] PLAN detay v3.1 takildi-uyari"


# ====================================================================
# 1) BACKEND - Takildi algoritmasini degistir
# ====================================================================

# Mevcut takildi blogu (V3 endpoint icinde)
ROUTES_ESKI = '''    takildi = None  # {kategori, proses_adi, proses_kod, durum, son_tarih}
    for ap in alt_parcalar:
        p = _ilk_tamam_olmayan(ap.get('prosesler') or [])
        if p:
            takildi = {
                'kategori': ap['kategori'],
                'proses_adi': p['proses_adi'],
                'proses_kod': p['proses_kod'],
                'durum': p['durum'],
                'son_tarih': p['son_tarih'],
                'yapilan': p['yapilan'],
                'toplam_hedef': p['toplam_hedef'],
            }
            break
    if not takildi:
        # Alt yoksa veya hepsi tamam ise ana emir prosesleri
        p = _ilk_tamam_olmayan(ana_prosesleri)
        if p:
            takildi = {
                'kategori': 'Ana',
                'proses_adi': p['proses_adi'],
                'proses_kod': p['proses_kod'],
                'durum': p['durum'],
                'son_tarih': p['son_tarih'],
                'yapilan': p['yapilan'],
                'toplam_hedef': p['toplam_hedef'],
            }'''

ROUTES_YENI = '''    # === V3 takildi-uyari ===
    # Takildi sadece alt emirlerde proses varsa hesaplanir.
    # Aksi halde "uretim alt parcalara baglanmamis" uyarisi gosterilir.
    takildi = None  # {kategori, proses_adi, ...}
    uyari = None    # 'alt_baglanmamis' | 'hic_uretim_yok'

    alt_proses_var_mi = any(len(ap.get('prosesler') or []) > 0 for ap in alt_parcalar)
    ana_proses_var_mi = len(ana_prosesleri) > 0

    if alt_proses_var_mi:
        # Alt emirlerde proses var: takildi hesabi yap
        for ap in alt_parcalar:
            p = _ilk_tamam_olmayan(ap.get('prosesler') or [])
            if p:
                takildi = {
                    'kategori': ap['kategori'],
                    'proses_adi': p['proses_adi'],
                    'proses_kod': p['proses_kod'],
                    'durum': p['durum'],
                    'son_tarih': p['son_tarih'],
                    'yapilan': p['yapilan'],
                    'toplam_hedef': p['toplam_hedef'],
                }
                break
        # Hepsi tamam ise takildi None kalir, frontend "tamam" gosterir
    elif alt_parcalar and ana_proses_var_mi:
        # Alt emir VAR ama proses YOK + ana emirde uretim VAR
        # = Yanlis baglama (uretim ana emire yazilmis, alt parcaya degil)
        uyari = 'alt_baglanmamis'
    elif not alt_parcalar and ana_proses_var_mi:
        # Hic alt emir yok, sadece ana emirde uretim
        # Ana emir prosesinden takildi hesapla (eski mantik)
        p = _ilk_tamam_olmayan(ana_prosesleri)
        if p:
            takildi = {
                'kategori': 'Ana',
                'proses_adi': p['proses_adi'],
                'proses_kod': p['proses_kod'],
                'durum': p['durum'],
                'son_tarih': p['son_tarih'],
                'yapilan': p['yapilan'],
                'toplam_hedef': p['toplam_hedef'],
            }
    else:
        # Ne alt ne ana proseste uretim
        uyari = 'hic_uretim_yok' '''


# Return jsonify icine uyari alanini eklemek
ROUTES_RETURN_ESKI = '''        'ana_prosesleri': ana_prosesleri,
        'alt_parcalar': alt_parcalar,
        'takildi': takildi,
    })'''

ROUTES_RETURN_YENI = '''        'ana_prosesleri': ana_prosesleri,
        'alt_parcalar': alt_parcalar,
        'takildi': takildi,
        'uyari': uyari,
    })'''


# ====================================================================
# 2) FRONTEND - takildi bandi + bos blok mesaji
# ====================================================================

# Mevcut takildi bandi blogu
JS_ESKI = '''        // 2. TAKILDI BANDI
        var t = d.takildi;
        if (t) {
            var bantCls = 'pdv3-takildi';
            var bantIkon = '\u25CF';  // dolu daire
            var rozetEt = (t.durum || 'bekliyor').toUpperCase();
            var rozetBg = '#f97316';
            if (t.durum === 'tamam') {
                bantCls += ' tamam';
                bantIkon = '\u2713';
                rozetEt = 'TAMAM';
                rozetBg = '#10b981';
            } else if (t.durum === 'bekliyor') {
                rozetEt = 'TAKILDI';
            } else {
                rozetEt = 'TAKILDI';
            }
            var sonStr = _zamanRel(t.son_tarih);
            html += '<div class="' + bantCls + '">' +
                '<span class="pdv3-takildi-ikon">' + bantIkon + '</span>' +
                '<span class="pdv3-takildi-etiket" style="background:' + rozetBg +
                ';">' + rozetEt + '</span>' +
                '<span class="pdv3-takildi-yer">' +
                '<strong>' + _esc(t.kategori || '-') + '</strong> &rarr; ' +
                '<strong>' + _esc(t.proses_adi || '-') + '</strong></span>' +
                '<span class="pdv3-takildi-zaman">' + (sonStr || '-') + '</span>' +
            '</div>';
        } else {
            // Hiç bekleyen yok = hepsi tamam, ya da hiç hareket yok
            html += '<div class="pdv3-takildi tamam">' +
                '<span class="pdv3-takildi-ikon">\u2713</span>' +
                '<span class="pdv3-takildi-etiket" style="background:#10b981;">TAMAM</span>' +
                '<span class="pdv3-takildi-yer">Tüm prosesler tamamlandı veya henüz başlamadı</span>' +
            '</div>';
        }'''

JS_YENI = '''        // 2. TAKILDI BANDI veya UYARI (v3.1)
        var t = d.takildi;
        var uyari = d.uyari;
        if (uyari === 'alt_baglanmamis') {
            // Alt emir var ama proses ana emirde - yanlis baglama
            html += '<div class="pdv3-takildi uyari-alt">' +
                '<span class="pdv3-takildi-ikon">\u26A0\uFE0F</span>' +
                '<span class="pdv3-takildi-etiket" style="background:#f59e0b;">UYARI</span>' +
                '<span class="pdv3-takildi-yer">' +
                '<strong>Üretim alt parçalara bağlanmamış</strong>' +
                ' &middot; Kayıtlar ana emirde görünüyor</span>' +
            '</div>';
        } else if (uyari === 'hic_uretim_yok') {
            html += '<div class="pdv3-takildi bos">' +
                '<span class="pdv3-takildi-ikon">\u23F3</span>' +
                '<span class="pdv3-takildi-etiket" style="background:#9ca3af;">BEKLİYOR</span>' +
                '<span class="pdv3-takildi-yer">Üretim henüz başlamadı</span>' +
            '</div>';
        } else if (t) {
            var bantCls = 'pdv3-takildi';
            var bantIkon = '\u25CF';
            var rozetEt = (t.durum || 'bekliyor').toUpperCase();
            var rozetBg = '#f97316';
            if (t.durum === 'tamam') {
                bantCls += ' tamam';
                bantIkon = '\u2713';
                rozetEt = 'TAMAM';
                rozetBg = '#10b981';
            } else if (t.durum === 'bekliyor') {
                rozetEt = 'TAKILDI';
            } else {
                rozetEt = 'TAKILDI';
            }
            var sonStr = _zamanRel(t.son_tarih);
            html += '<div class="' + bantCls + '">' +
                '<span class="pdv3-takildi-ikon">' + bantIkon + '</span>' +
                '<span class="pdv3-takildi-etiket" style="background:' + rozetBg +
                ';">' + rozetEt + '</span>' +
                '<span class="pdv3-takildi-yer">' +
                '<strong>' + _esc(t.kategori || '-') + '</strong> &rarr; ' +
                '<strong>' + _esc(t.proses_adi || '-') + '</strong></span>' +
                '<span class="pdv3-takildi-zaman">' + (sonStr || '-') + '</span>' +
            '</div>';
        } else {
            // Hicbir veri yok ama uyari da yok (alt emir VAR + alt prosesler hep tamam)
            html += '<div class="pdv3-takildi tamam">' +
                '<span class="pdv3-takildi-ikon">\u2713</span>' +
                '<span class="pdv3-takildi-etiket" style="background:#10b981;">TAMAM</span>' +
                '<span class="pdv3-takildi-yer">Tüm prosesler tamamlandı</span>' +
            '</div>';
        }'''


# Bos alt blok mesaji
JS_ESKI_BOS = '''            if (prosesler.length === 0) {
                html += '<div class="pdv3-empty">Henüz proses kaydı yok.</div>';
            } else {'''

JS_YENI_BOS = '''            if (prosesler.length === 0) {
                var anaUretimVar = (d.ana_prosesleri || []).length > 0;
                if (anaUretimVar) {
                    html += '<div class="pdv3-empty">' +
                        '<strong>HENÜZ PROSES YOK</strong>' +
                        '<div style="font-size:11px;margin-top:4px;color:#f59e0b;">' +
                        '(üretim ana emirde görünüyor)</div></div>';
                } else {
                    html += '<div class="pdv3-empty">Henüz proses kaydı yok.</div>';
                }
            } else {'''


# CSS: yeni bant tipleri (uyari, bos)
JS_CSS_ESKI = '''            '.pdv3-takildi.tamam {border-left-color:#10b981;background:rgba(16,185,129,0.06);}' +
            '.pdv3-takildi.bos {border-left-color:#9ca3af;background:#f9fafb;}' +'''

JS_CSS_YENI = '''            '.pdv3-takildi.tamam {border-left-color:#10b981;background:rgba(16,185,129,0.06);}' +
            '.pdv3-takildi.bos {border-left-color:#9ca3af;background:#f9fafb;}' +
            '.pdv3-takildi.uyari-alt {' +
                'border-left-color:#f59e0b;background:rgba(245,158,11,0.08);' +
            '}' +'''


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
    print("1/2 BACKEND: takildi-uyari mantigi")
    print("=" * 64)
    if not os.path.exists(HEDEF_ROUTES):
        print(f"  [HATA] {HEDEF_ROUTES} yok.")
        return False
    with open(HEDEF_ROUTES, 'r', encoding='utf-8') as f:
        src = f.read()
    if ROUTES_MARKER in src:
        print("  [BILGI] V3 uyari zaten ekli.")
        return True

    if ROUTES_ESKI not in src:
        print("  [HATA] Eski takildi blogu bulunamadi.")
        return False
    if src.count(ROUTES_ESKI) > 1:
        print("  [HATA] Cogul.")
        return False
    if ROUTES_RETURN_ESKI not in src:
        print("  [HATA] return blogu bulunamadi.")
        return False

    new_src = src.replace(ROUTES_ESKI, ROUTES_YENI, 1)
    new_src = new_src.replace(ROUTES_RETURN_ESKI, ROUTES_RETURN_YENI, 1)

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False

    bp = backup(HEDEF_ROUTES)
    print(f"  [OK] Yedek: {bp}")
    with open(HEDEF_ROUTES, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Backend uyari mantigi eklendi.")
    return True


def patch_js():
    print()
    print("=" * 64)
    print("2/2 FRONTEND: bant + bos blok mesaj")
    print("=" * 64)
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} yok.")
        return False
    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()
    if JS_MARKER in src:
        print("  [BILGI] JS uyari zaten ekli.")
        return True

    if JS_ESKI not in src:
        print("  [HATA] Eski bant blogu bulunamadi.")
        return False
    if JS_ESKI_BOS not in src:
        print("  [HATA] Eski bos blok blogu bulunamadi.")
        return False
    if JS_CSS_ESKI not in src:
        print("  [HATA] Eski CSS blogu bulunamadi.")
        return False

    new_src = src.replace(JS_ESKI, JS_YENI, 1)
    new_src = new_src.replace(JS_ESKI_BOS, JS_YENI_BOS, 1)
    new_src = new_src.replace(JS_CSS_ESKI, JS_CSS_YENI, 1)
    new_src += "\n/* " + JS_MARKER + " */\n"

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Frontend uyari mesajlari eklendi.")
    return True


def main():
    print("=" * 64)
    print("PLAN DETAY v3.1 - TAKILDI UYARI")
    print("=" * 64)

    ok1 = patch_routes()
    ok2 = patch_js()

    print()
    if ok1 and ok2:
        print("TAMAM.")
        print()
        print("Senaryolar:")
        print("  A) Alt emir VAR + alt proses VAR")
        print("     -> TAKILDI/DEVAM/TAMAM bandi (eski davranis)")
        print()
        print("  B) Alt emir VAR + alt proses YOK + ana emirde uretim VAR")
        print("     -> 'Uretim alt parcalara baglanmamis' UYARI bandi (sari)")
        print("     -> Alt blokta 'HENUZ PROSES YOK (ana emirde gorunuyor)'")
        print()
        print("  C) Alt emir YOK + ana emirde uretim VAR")
        print("     -> Eski mantik (takildi ana emirden hesaplanir)")
        print()
        print("  D) Hic uretim yok")
        print("     -> 'Uretim henuz baslamadi' (gri)")
        print()
        print("YAPILACAK: Browser Ctrl+F5 (Flask otomatik restart yapacak)")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
