# -*- coding: utf-8 -*-
"""
fix_lazy_ana_override.py
------------------------
Lazy detay endpoint ana emir SUM(Giren)'i de donderiyor ama frontend
sadece alt emirler icin override ediyor.

Sorun: ana emirde EmirMiktari = 7000 (Siparis_Har) kaliyor, lazy detay
gelince guncellenmiyor.

Cozum: Frontend lazy callback'inde TUM emirleri (ana+alt) override et,
SUM(Giren) > 0 ise EmirMiktari'yi yenile.
"""

import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

JS_MARKER = "[CPS LOCAL] FAZ 4.6 lazy ana override"

ESKI = """                      var degisti = false;
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
                      });"""

YENI = """                      // === FAZ 4.6 lazy ana override ===
                      // Hem ana hem alt emirleri override et (SUM(Giren) > 0 ise)
                      var degisti = false;
                      st.emirler.forEach(function (e) {
                          var k = String(e.EmirNo);
                          if (detay[k]) {
                              // EmirMiktari = SUM(Giren) - alt'ta her zaman, ana'da SUM>0 ise
                              if (detay[k].EmirMiktari != null && detay[k].EmirMiktari > 0) {
                                  // Ana emir: SiparisMiktari'yi koru ama EmirMiktari override
                                  e.EmirMiktari = detay[k].EmirMiktari;
                                  degisti = true;
                              } else if (e.EmirTip === 'alt' && detay[k].EmirMiktari != null) {
                                  // Alt emir: SUM(Giren) 0 olsa bile null yerine al
                                  e.EmirMiktari = detay[k].EmirMiktari;
                                  degisti = true;
                              }
                              if (detay[k].RKOD != null) {
                                  e.RKOD = detay[k].RKOD;
                                  degisti = true;
                              }
                          }
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
    print("[OK] Lazy ana emir override eklendi.")
    print()
    print("YAPILACAK: Ctrl+F5 (sunucu restart gerekmez)")
    print()
    print("Beklenen:")
    print("  - Lazy load tamamlandiginda toplam: 26.400 cift (210.000 degil)")
    print("  - Ana emirlerde de EMIR CIFT ADET = 480 (7000 degil)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
