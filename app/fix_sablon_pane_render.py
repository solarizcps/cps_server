# -*- coding: utf-8 -*-
"""
fix_sablon_pane_render.py
-------------------------
hedef.js dosyasinin sonuna kucuk bir "fix" IIFE ekler.
Mevcut SABLON pane'inde 'Sablonlar UI.3 asamasinda eklenecek' eski metni
varsa onu temizler ve bizim render'imiza dokunmaz.
"""

import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")
JS_MARKER = "[CPS LOCAL] FAZ 4.6 B fix-pane"

JS_BLOCK = r'''


/* ====================================================================
   CPS LOCAL - FAZ 4.6 B FIX: Eski 'UI.3 asamasinda' metnini temizle
   - Sablon pane'inde varsa o eski mesaji sil
   - Bizim #sablonPane DIV'imize dokunma
   ==================================================================== */
(function () {
    'use strict';

    function _temizle() {
        var pane = document.querySelector('[data-pane="sablon"]') ||
                   document.querySelector('.h-pane[data-pane="sablon"]') ||
                   document.getElementById('h-pane-sablon');
        if (!pane) return;

        // Pane içindeki child'lari incele:
        // - Bizim '#sablonPane' DIV'imiz kalsin
        // - '#sablonModal' DIV'imiz kalsin
        // - 'UI.3' metni iceren VEYA 'h-empty' class'li elemanlari KALDIR
        var children = Array.prototype.slice.call(pane.children);
        children.forEach(function (el) {
            if (el.id === 'sablonPane' || el.id === 'sablonModal') return;
            // h-empty class'li veya UI.3 metni iceren = eski placeholder
            if (el.classList && el.classList.contains('h-empty')) {
                el.remove();
                return;
            }
            if (el.textContent && el.textContent.indexOf('UI.3') !== -1) {
                el.remove();
                return;
            }
            // Bizim olmadigi belli olan diger eski elemanlar - guvenli bir sekilde kaldir
            // (sadece text-only veya placeholder gibi gorunenler)
            if (!el.id && el.children.length === 0) {
                // Bos veya text-only element, muhtemelen eski placeholder
                el.remove();
            }
        });
    }

    // Tab tiklamasiyla calistir
    var sablonTab = document.querySelector('.h-tab[data-tab="sablon"]');
    if (sablonTab) {
        sablonTab.addEventListener('click', function () {
            // Bizim render'dan sonra calissin
            setTimeout(_temizle, 100);
            setTimeout(_temizle, 300);
        });
    }

    // Sayfa yuklendigi anda da calistir (eger sablon tab acik ise)
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            setTimeout(_temizle, 250);
            setTimeout(_temizle, 600);
        });
    } else {
        setTimeout(_temizle, 250);
        setTimeout(_temizle, 600);
    }

    console.log('[CPS LOCAL] FAZ 4.6 B fix-pane yuklendi.');
})();
'''


def main():
    print("=" * 64)
    print("FAZ 4.6 B FIX - Pane temizleme")
    print("=" * 64)

    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} bulunamadi.")
        return 1

    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if JS_MARKER in src:
        print("  [BILGI] Fix zaten ekli.")
        return 0

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += JS_BLOCK

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = JS_PATH + f'.bak_{ts}'
    shutil.copy2(JS_PATH, bp)
    print(f"  [OK] Yedek: {bp}")

    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Pane temizleme IIFE eklendi.")
    print()
    print("YAPILACAK:")
    print("  1) CPS sunucusunu yeniden baslat (gerek yok ama temiz olsun)")
    print("  2) Browser'da Ctrl+F5")
    print("  3) /hedef/ -> SABLON sekmesi")
    print()
    print("Beklenen: 'UI.3 asamasinda' metni KAYBOLMUS olmali.")
    print("Genel Sablonlar / Emir Ozel Override sekmeleri gorunur.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
