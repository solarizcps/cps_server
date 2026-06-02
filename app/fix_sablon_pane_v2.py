# -*- coding: utf-8 -*-
"""
fix_sablon_pane_v2.py
---------------------
Onceki fix yanlis pane olusturmus. Simdi:
  - Sayfadaki TUM 'data-pane=sablon' section'larini bul
  - Bizim olmayan (orijinal) pane'i tespit et: 'h-empty' icindeki 'UI.3' metni
  - Orijinal pane'in icini tamamen temizle
  - Bizim '#sablonPane' DIV'imizi orijinal pane'in icine TASI
  - Bizim olusturdugumuz fazlalik pane'i sil
"""

import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")
JS_MARKER = "[CPS LOCAL] FAZ 4.6 B fix-pane v2"

JS_BLOCK = r'''


/* ====================================================================
   CPS LOCAL - FAZ 4.6 B FIX v2
   - Orijinal pane'i bul, icini temizle
   - Bizim #sablonPane / #sablonModal'i ona tasi
   - Duplikat pane'leri sil
   ==================================================================== */
(function () {
    'use strict';

    function _gercekPaneBul() {
        // Tum data-pane="sablon" elementleri
        var hepsi = document.querySelectorAll('[data-pane="sablon"]');
        if (hepsi.length === 0) return null;

        // Tek pane varsa o
        if (hepsi.length === 1) return hepsi[0];

        // Birden fazla varsa: 'h-pane' class'ina sahip ve text icinde 'UI.3' olan = orijinal
        // Ya da: BIZIM ekledigimiz olmayan = h-pane class'ina sahip orijinal
        var orijinal = null;
        var bizim = null;
        for (var i = 0; i < hepsi.length; i++) {
            var el = hepsi[i];
            // Bizim eklediklerimizi tespit et: tek child #sablonPane ve #sablonModal
            var sablonPane = el.querySelector('#sablonPane');
            var sablonModal = el.querySelector('#sablonModal');
            var ui3 = el.textContent && el.textContent.indexOf('UI.3') !== -1;
            var hasEmpty = el.querySelector('.h-empty');

            if (ui3 || hasEmpty) {
                orijinal = el;
            } else if (sablonPane || sablonModal) {
                if (!orijinal) bizim = el;
            }
        }
        // Orijinal yoksa, hangisi h-pane class'i ile gerçekse onu seç
        if (!orijinal) {
            for (var j = 0; j < hepsi.length; j++) {
                if (hepsi[j].classList.contains('h-pane')) {
                    orijinal = hepsi[j];
                    break;
                }
            }
        }
        return orijinal || hepsi[0];
    }

    function _tasi() {
        var hepsi = document.querySelectorAll('[data-pane="sablon"]');
        if (hepsi.length === 0) return;

        var orijinal = _gercekPaneBul();
        if (!orijinal) return;

        // Bizim DIV'lerimizi bul (her yerde olabilirler)
        var sablonPane = document.getElementById('sablonPane');
        var sablonModal = document.getElementById('sablonModal');

        if (!sablonPane && !sablonModal) {
            // Bizim render hic calismamis demek - hicbir sey yapma
            return;
        }

        // Orijinal pane'in TUM icerigini sil
        while (orijinal.firstChild) {
            orijinal.removeChild(orijinal.firstChild);
        }

        // Bizim DIV'lerimizi orijinale TASI (yeniden ekle)
        if (sablonPane) {
            orijinal.appendChild(sablonPane);
        }
        if (sablonModal) {
            // Modal'i body'e tasimak daha iyi (z-index/overflow icin)
            // Ama sablonPane'i tasidigimiz icin tutarli kalsin diye orijinale ekle
            orijinal.appendChild(sablonModal);
        }

        // Duplikat data-pane="sablon" section'lari sil (orijinal HARIC)
        for (var i = 0; i < hepsi.length; i++) {
            var el = hepsi[i];
            if (el !== orijinal && el.parentNode) {
                el.parentNode.removeChild(el);
            }
        }

        console.log('[CPS LOCAL] Sablon pane orijinale tasindi.');
    }

    // Tab tiklamasiyla
    var sablonTab = document.querySelector('.h-tab[data-tab="sablon"]');
    if (sablonTab) {
        sablonTab.addEventListener('click', function () {
            // Bizim render bittikten sonra
            setTimeout(_tasi, 150);
            setTimeout(_tasi, 400);
        });
    }

    // Sayfa acildiginda
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            setTimeout(_tasi, 300);
            setTimeout(_tasi, 700);
        });
    } else {
        setTimeout(_tasi, 300);
        setTimeout(_tasi, 700);
    }

    console.log('[CPS LOCAL] FAZ 4.6 B fix-pane v2 yuklendi.');
})();
'''


def main():
    print("=" * 64)
    print("FAZ 4.6 B FIX v2 - Pane tasima")
    print("=" * 64)

    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} bulunamadi.")
        return 1

    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if JS_MARKER in src:
        print("  [BILGI] Fix v2 zaten ekli.")
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
    print("  [OK] Pane tasima IIFE eklendi.")
    print()
    print("YAPILACAK:")
    print("  1) Browser'da Ctrl+F5")
    print("  2) /hedef/ -> SABLON")
    print()
    print("Beklenen: 'UI.3' kayboldu, bizim alt sekmeler GORUNUR.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
