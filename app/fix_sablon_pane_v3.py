# -*- coding: utf-8 -*-
"""
fix_sablon_pane_v3.py
---------------------
TESHIS: Tab sistemi 'id="pane-sablon"' pattern'i kullaniyor (data-pane degil).
Bizim onceki render duplikat pane olusturdu, gercek pane'e dokunmadi.

CARE:
  1) Onceki bizim duplikat pane'i sil
  2) Gercek pane (#pane-sablon) icini temizle
  3) Bizim '#sablonPane' ve '#sablonModal' DIV'lerimizi #pane-sablon icine yerlestir
  4) #sablonPane'in tab tiklamasinda render'i tetiklesin
"""

import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")
JS_MARKER = "[CPS LOCAL] FAZ 4.6 B fix-pane v3"

JS_BLOCK = r'''


/* ====================================================================
   CPS LOCAL - FAZ 4.6 B FIX v3
   - Gercek pane: id="pane-sablon" (tire ile)
   - data-pane="sablon" sadece bizim olusturdugumuz fazlalikti
   ==================================================================== */
(function () {
    'use strict';

    function _migrate() {
        // 1) Gercek pane'i bul: id="pane-sablon"
        var gercek = document.getElementById('pane-sablon');
        if (!gercek) {
            // Fallback: data-pane=sablon olan ilk h-pane class'ina sahip element
            var fallbacks = document.querySelectorAll('[data-pane="sablon"], [id*="sablon"]');
            for (var i = 0; i < fallbacks.length; i++) {
                if (fallbacks[i].classList && fallbacks[i].classList.contains('h-pane')) {
                    gercek = fallbacks[i];
                    break;
                }
            }
        }
        if (!gercek) {
            console.warn('[FIX v3] Gercek pane bulunamadi.');
            return;
        }

        // 2) Bizim DIV'lerimizi tum DOM'da bul (nerede olursa olsun)
        var sablonPane = document.getElementById('sablonPane');
        var sablonModal = document.getElementById('sablonModal');

        // 3) Gercek pane icinde zaten bizim DIV'imiz var mi kontrol et
        var icindeMi = gercek.contains(sablonPane);
        if (icindeMi && !gercek.querySelector('.h-empty') && !gercek.textContent.match(/UI\.3/)) {
            // Zaten dogru yerdeyiz, eski metin yok, idempotent done
            return;
        }

        // 4) Gercek pane'in tum icerigini sil
        while (gercek.firstChild) {
            gercek.removeChild(gercek.firstChild);
        }

        // 5) Bizim DIV'lerimizi gercek pane'e tasi
        if (sablonPane) {
            gercek.appendChild(sablonPane);
        }
        if (sablonModal) {
            gercek.appendChild(sablonModal);
        }

        // 6) Bizim eski olusturdugumuz duplikat pane'leri (data-pane=sablon, h-pane class)
        //    eger gercek pane DEGIL'se ve icinde bizim DIV'imiz YOK'sa = duplikat = sil
        var hepsi = document.querySelectorAll('[data-pane="sablon"]');
        for (var j = 0; j < hepsi.length; j++) {
            var el = hepsi[j];
            if (el !== gercek && (!el.children.length || el.id !== 'pane-sablon')) {
                if (el.parentNode) el.parentNode.removeChild(el);
            }
        }

        console.log('[CPS LOCAL] FIX v3: gercek pane (id=pane-sablon) icine tasindi.');
    }

    function _trigger() {
        // Onceki render fonksiyonunu da tekrar tetikle (tab click gibi)
        // Onceki IIFE'lerin pane bulma fonksiyonu vardi, ama erisemiyoruz.
        // Onun yerine: eger #sablonPane DOM'da yoksa, eski IIFE _renderPane'i
        // tetiklemek icin kapali bir mekanizma yok. Bu yuzden:
        //   a) Eger #sablonPane yoksa, hicbir sey yapma; bizim onceki IIFE
        //      muhtemelen daha sonra olusturacak (ya tab click ile ya kurulum'da).
        //   b) Eger #sablonPane varsa, _migrate() onu dogru yere koyar.
        _migrate();
    }

    // Tab tiklamalarinda
    var sablonTab = document.querySelector('.h-tab[data-tab="sablon"]');
    if (sablonTab) {
        sablonTab.addEventListener('click', function () {
            // Bizim render gecip pane'i taşıdıktan sonra
            setTimeout(_trigger, 200);
            setTimeout(_trigger, 500);
        });
    }

    // Sayfa yuklenince
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            setTimeout(_trigger, 400);
            setTimeout(_trigger, 900);
        });
    } else {
        setTimeout(_trigger, 400);
        setTimeout(_trigger, 900);
    }

    console.log('[CPS LOCAL] FAZ 4.6 B fix-pane v3 yuklendi.');
})();
'''


def main():
    print("=" * 64)
    print("FAZ 4.6 B FIX v3 - id=pane-sablon hedef")
    print("=" * 64)

    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} bulunamadi.")
        return 1

    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if JS_MARKER in src:
        print("  [BILGI] Fix v3 zaten ekli.")
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
    print("  [OK] Fix v3 IIFE eklendi.")
    print()
    print("YAPILACAK: Ctrl+F5 -> /hedef/ -> SABLON")
    print()
    print("Beklenen log:")
    print("  [CPS LOCAL] FAZ 4.6 B fix-pane v3 yuklendi.")
    print("  [CPS LOCAL] FIX v3: gercek pane (id=pane-sablon) icine tasindi.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
