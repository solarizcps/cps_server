# -*- coding: utf-8 -*-
"""
fix_altgruplari_tanim.py
------------------------
JS satir 2913'te 'var alt = ...' var ama 'altGruplari' tanimi YOK.
Onceki patch (fix_b3_three_issues) sadece kismen uygulanmis, RENDER replace
calisti gibi gozukse de altGruplari atamasi kayboldu.

Cozum: 'var alt = ...' satirini bul, oraya altGruplari atamasi ekle.
"""

import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

JS_MARKER = "[CPS LOCAL] FAZ 4.6 B3 altGruplari fix"

# Mevcut satir (2913):
ESKI = """        var ana = _state.emirler.filter(function (e) { return e.EmirTip === 'ana'; });
        var alt = _state.emirler.filter(function (e) { return e.EmirTip === 'alt'; });"""

# Yeni: altGruplari tanimini da ekle
YENI = """        var ana = _state.emirler.filter(function (e) { return e.EmirTip === 'ana'; });
        var altHepsi = _state.emirler.filter(function (e) { return e.EmirTip === 'alt'; });

        // === FAZ 4.6 B3 altGruplari fix ===
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
        });"""


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
        print("[HATA] Eski pattern bulunamadi.")
        # Belki sadece ana satiri var
        return 1
    if src.count(ESKI) > 1:
        print("[HATA] Pattern cogul.")
        return 1

    new_src = src.replace(ESKI, YENI, 1)
    new_src += "\n/* " + JS_MARKER + " */\n"

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = JS_PATH + f'.bak_{ts}'
    shutil.copy2(JS_PATH, bp)
    print(f"[OK] Yedek: {bp}")

    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("[OK] altGruplari tanimi eklendi (atki/govde/taban/saya/diger).")
    print()
    print("YAPILACAK: Ctrl+F5 (sunucu restart gerekmez)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
