# -*- coding: utf-8 -*-
"""
fix_alt_grup_v2.py
------------------
Onceki patch JS_OLD_GRUP'u bulamadi cunku pattern degismis.
Direkt regex ile alt grup HTML.push satirini bul ve degistir.
"""

import os
import re
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

JS_MARKER = "[CPS LOCAL] FAZ 4.6 B3 alt-grup v2"


def main():
    if not os.path.exists(JS_PATH):
        print(f"[HATA] {JS_PATH} yok.")
        return 1

    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if JS_MARKER in src:
        print("[BILGI] Alt grup v2 zaten ekli.")
        return 0

    # Onceki patch _altKategori ve altGruplari'ni eklemis durumda (JS_OLD_RENDER calisti).
    # Sadece grupHTML cagrisi eski sekilde duruyor:
    #   html.push(_grupHTML('🔧 Alt Emirler (Yarı Mamul)', 'alt', altHepsi, 'alt'));
    # Bunu cesitlendirmemiz lazim.

    # Regex ile bul: html.push(_grupHTML(... 'alt', ALT_DEGISKEN, 'alt'));
    # ALT_DEGISKEN: 'alt' veya 'altHepsi' olabilir.
    pattern1 = re.compile(
        r"html\.push\(_grupHTML\([^)]*Alt Emirler[^)]*'alt'[^)]*\)\);",
        re.UNICODE
    )
    m1 = pattern1.search(src)

    if not m1:
        # alt grup pattern'ini farkli sekilde dene
        pattern2 = re.compile(
            r"html\.push\(_grupHTML\([^)]*alt[^)]*\)\);[^h]*",
            re.IGNORECASE
        )
        # Daha basit: '_grupHTML' satirinin tum cagrilarini bul
        all_calls = list(re.finditer(r"html\.push\(_grupHTML\([^;]*\);", src))
        print(f"[BILGI] Bulunan _grupHTML cagrilari: {len(all_calls)}")
        for i, c in enumerate(all_calls):
            print(f"  [{i+1}] {c.group()[:120]}...")

        if len(all_calls) < 2:
            print("[HATA] _grupHTML cagrilari bulunamadi.")
            return 1

        # Son cagriyi (alt emirler icin olan) replace et
        ALT_NEW = """html.push(_grupHTML('📦 Ana Emirler (Mamul)', 'ana', ana, 'ana'));
        if (altGruplari && altGruplari.atki && altGruplari.atki.length > 0)
            html.push(_grupHTML('🪡 Atkı Emirleri (Yarı Mamul)', 'alt', altGruplari.atki, 'alt_atki'));
        if (altGruplari && altGruplari.govde && altGruplari.govde.length > 0)
            html.push(_grupHTML('🦶 Gövde Emirleri (Yarı Mamul)', 'alt', altGruplari.govde, 'alt_govde'));
        if (altGruplari && altGruplari.taban && altGruplari.taban.length > 0)
            html.push(_grupHTML('👟 Taban Emirleri (Yarı Mamul)', 'alt', altGruplari.taban, 'alt_taban'));
        if (altGruplari && altGruplari.saya && altGruplari.saya.length > 0)
            html.push(_grupHTML('🧵 Saya Emirleri (Yarı Mamul)', 'alt', altGruplari.saya, 'alt_saya'));
        if (altGruplari && altGruplari.diger && altGruplari.diger.length > 0)
            html.push(_grupHTML('🔧 Diğer Alt Emirler (Yarı Mamul)', 'alt', altGruplari.diger, 'alt_diger'));"""

        # Iki ardisik _grupHTML cagrisi: 'ana' ve 'alt' (ya da 'altHepsi')
        # 1. ana, 2. alt - bunlari toplu replace et
        if len(all_calls) >= 2:
            first = all_calls[0]
            second = all_calls[-1]  # son cagri
            # ana ve alt cagrilarini birlikte degistir
            start = first.start()
            end = second.end()
            # araya gelen kucuk text de var (whitespace)
            new_src = src[:start] + ALT_NEW + src[end:]
        else:
            print("[HATA] Beklenen sayida cagri yok.")
            return 1
    else:
        # Tek alt cagrisi bulundu, sadece o
        ALT_NEW_SINGLE = """if (altGruplari && altGruplari.atki && altGruplari.atki.length > 0)
            html.push(_grupHTML('🪡 Atkı Emirleri (Yarı Mamul)', 'alt', altGruplari.atki, 'alt_atki'));
        if (altGruplari && altGruplari.govde && altGruplari.govde.length > 0)
            html.push(_grupHTML('🦶 Gövde Emirleri (Yarı Mamul)', 'alt', altGruplari.govde, 'alt_govde'));
        if (altGruplari && altGruplari.taban && altGruplari.taban.length > 0)
            html.push(_grupHTML('👟 Taban Emirleri (Yarı Mamul)', 'alt', altGruplari.taban, 'alt_taban'));
        if (altGruplari && altGruplari.saya && altGruplari.saya.length > 0)
            html.push(_grupHTML('🧵 Saya Emirleri (Yarı Mamul)', 'alt', altGruplari.saya, 'alt_saya'));
        if (altGruplari && altGruplari.diger && altGruplari.diger.length > 0)
            html.push(_grupHTML('🔧 Diğer Alt Emirler (Yarı Mamul)', 'alt', altGruplari.diger, 'alt_diger'));"""
        new_src = src[:m1.start()] + ALT_NEW_SINGLE + src[m1.end():]

    new_src += "\n/* " + JS_MARKER + " */\n"

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = JS_PATH + f'.bak_{ts}'
    shutil.copy2(JS_PATH, bp)
    print(f"[OK] Yedek: {bp}")

    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("[OK] Alt emir gruplari (Atki/Govde/Taban/Saya/Diger) ayri.")
    print()
    print("YAPILACAK: Ctrl+F5 (sunucu restart gerekmez)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
