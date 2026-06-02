# -*- coding: utf-8 -*-
"""
fix_toplam_inline.py
--------------------
Satir 2871-2889'daki inline toplam hesabini siparis_toplam ile degistir.
Backend zaten siparis_toplam donduruyor (fix_toplam_siparis.py 1/2 basarili).
"""

import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

JS_MARKER = "[CPS LOCAL] FAZ 4.6 toplam siparis inline fix"


# Tam mevcut blok (satir 2871-2889):
ESKI = """            // === FAZ 4.6 B3 polish ===
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

# Yeni: backend siparis_toplam'i kullan
YENI = """            // === FAZ 4.6 toplam siparis inline fix ===
            // Toplam = backend'den gelen siparis_toplam (distinct Siparis_Har.Miktar)
            // Eski 30 ana x 7000 = 210.000 yanlisi yerine: 33558(7000)+33638(7000)=14000
            var _siparisToplam = Number(r.data.siparis_toplam || 0);
            var _anaSayi = r.data.ana_sayisi || 0;
            var _altSayi = r.data.alt_sayisi || 0;
            var _emirSayi = r.data.emir_sayisi || _state.emirler.length;
            document.getElementById('sb3Info').innerHTML =
                '<strong>Sipariş ' + sipno + '</strong> &nbsp;•&nbsp; ' +
                '<span style=\"color:#16a34a;font-weight:600;\">' + _emirSayi + ' emir</span> ' +
                '(<span style=\"color:#15803d;\">' + _anaSayi + ' ana</span> / ' +
                '<span style=\"color:#1e40af;\">' + _altSayi + ' alt</span>) ' +
                '&nbsp;•&nbsp; ' +
                '<span style=\"color:#7c3aed;font-weight:600;\">Sipariş: ' +
                _siparisToplam.toLocaleString('tr-TR') + ' çift</span>';"""


def main():
    if not os.path.exists(JS_PATH):
        print(f"[HATA] {JS_PATH} yok.")
        return 1

    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if JS_MARKER in src:
        print("[BILGI] Fix zaten ekli.")
        return 0

    if ESKI not in src:
        print("[HATA] Eski blok bulunamadi.")
        return 1
    if src.count(ESKI) > 1:
        print("[HATA] Blok cogul.")
        return 1

    new_src = src.replace(ESKI, YENI, 1)
    new_src += "\n/* " + JS_MARKER + " */\n"

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = JS_PATH + f'.bak_{ts}'
    shutil.copy2(JS_PATH, bp)
    print(f"[OK] Yedek: {bp}")

    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("[OK] Toplam = siparis_toplam (backend'den).")
    print()
    print("YAPILACAK: Ctrl+F5 (sunucu restart gerekmez)")
    print()
    print("Beklenen:")
    print("  Sipariş 33558 • 55 emir (30 ana / 25 alt) • Sipariş: 14.000 çift")
    return 0


if __name__ == '__main__':
    sys.exit(main())
