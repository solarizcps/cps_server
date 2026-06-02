# -*- coding: utf-8 -*-
"""
fix_eski_sag_panel_kapat.py
---------------------------
Sorun: Eski PLAN_DETAY_V1 IIFE'i hala click handler'a sahip,
       sag panel'i acmaya calisiyor.

Cozum: Inline v2 IIFE'inin global bayrak (window._planInlineAktif=true)
       eski v1'i devre dis birakir.

Yontem 1 (basit): Inline v2 IIFE basina bir flag set et, click handler'da
                  flag varsa eski panel acmasin.

Ama eski v1 IIFE zaten yazildi, JS'i tekrar yazip override etmek zor.
Daha kolay: Eski PLAN_DETAY_V1 IIFE'in olusturdugu DOM elemanlarini
            sayfada YOK et + eski click handler'inin ic isleyisini bozma.

En basit cozum: window.dispatchEvent eski v1 click handler'larini engellemek
               icin event capture phase'de stopPropagation.

DAHA TEMIZ COZUM: Eski v1 IIFE'inin _yukle/_ac fonksiyonlarini override
                 edip no-op yap.

Eski IIFE'in icindeki _yukle ve _ac fonksiyonlari local scope'ta kapali.
Disardan erismeden override edilemez.

EN BASIT COZUM: capture phase event listener ile #planBody tr tiklamalari
               daha once yakalanir, eski v1 click handler'inin daha sonra
               calismasini engelle (stopImmediatePropagation).

Bunu yapamayiz cunki bizim v2 IIFE'i de event delegation kullaniyor.

GERCEK COZUM: Eski sag panel DOM olustugunda kaldir.
              MutationObserver ile #plan-detay-panel olusunca an\u0131nda sil.
"""
import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

JS_MARKER = "[CPS LOCAL] eski sag panel kesin kapat v3"


# Eski sag paneli kesin kapatan kod
JS_BLOCK = r'''


/* ====================================================================
   CPS LOCAL - eski sag panel KESIN kapat v3
   - MutationObserver ile #plan-detay-panel olusur olusmaz silinir
   - Boylece eski v1 IIFE'in fetch'i bossa bile DOM gozukmez
   ==================================================================== */
(function () {
    'use strict';

    function _eskiPaneliSil() {
        var p = document.getElementById('plan-detay-panel');
        var bk = document.getElementById('plan-detay-backdrop');
        if (p && p.parentNode) p.parentNode.removeChild(p);
        if (bk && bk.parentNode) bk.parentNode.removeChild(bk);
    }

    // Hemen sil (varsa)
    _eskiPaneliSil();

    // Sayfa boyunca olusursa hemen sil
    var obs = new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
            var m = muts[i];
            if (m.type === 'childList' && m.addedNodes.length) {
                for (var j = 0; j < m.addedNodes.length; j++) {
                    var n = m.addedNodes[j];
                    if (!n || n.nodeType !== 1) continue;
                    if (n.id === 'plan-detay-panel' || n.id === 'plan-detay-backdrop') {
                        if (n.parentNode) n.parentNode.removeChild(n);
                    }
                }
            }
        }
    });
    obs.observe(document.body, { childList: true });

    console.log('[CPS LOCAL] eski sag panel kesin kapat v3');
})();
'''


def main():
    if not os.path.exists(JS_PATH):
        print(f"[HATA] {JS_PATH} yok.")
        return 1

    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if JS_MARKER in src:
        print("[BILGI] v3 zaten ekli.")
        return 0

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += JS_BLOCK

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = JS_PATH + f'.bak_{ts}'
    shutil.copy2(JS_PATH, bp)
    print(f"[OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("[OK] Eski sag panel MutationObserver ile kesin kapatildi.")
    print()
    print("YAPILACAK: Browser Ctrl+F5")
    print()
    print("BEKLENEN:")
    print("  - Sag panel artik gorunmez")
    print("  - Sadece inline expand (alt detay) calisir")
    return 0


if __name__ == '__main__':
    sys.exit(main())
