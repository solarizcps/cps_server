# -*- coding: utf-8 -*-
"""
CPS DEV — Patch C2.1B: Tip kart border renkleri (CSS)
======================================================

KAPSAM:
  static/css/cps_ithalat.css dosyasinin SONUNA tip kart border
  renk tanimlari eklenir.

EKLENEN SINIFLAR:
  .cps-ith-tip-kart.kart-pozitif → kirmizi solid border (asim)
  .cps-ith-tip-kart.kart-negatif → yesil solid border (tasarruf)

ONCELIK MANTIGI (CSS specificity ayni - sira onemli):
  1) .cps-ith-tip-kart.bekliyor    → sari dashed (mevcut)
  2) .cps-ith-tip-kart.tahmini-yok → mavi dashed (mevcut)
  3) .cps-ith-tip-kart.kart-pozitif → KIRMIZI SOLID (yeni)
  4) .cps-ith-tip-kart.kart-negatif → YESIL SOLID  (yeni)
  5) Default                       → gri solid (mevcut)

  CSS cascade: bekliyor/tahmini-yok onceden tanimli, kart-pozitif/negatif
  sonra eklendigi icin, eger bir kart hem 'bekliyor' hem 'kart-pozitif'
  alirsa son tanimlanan (pozitif/negatif) kazanir. Bu istemediğimiz durum.

  COZUM: kart-pozitif / kart-negatif siniflarini :not() ile kosulla.
  Boylece BEKLIYOR ya da TAHMINI_YOK varsa bu siniflarin border'i
  override etmez.

GUVENLIK:
  - Yedek alinir (tarih damgali, ayri yedek)
  - Idempotent: marker "C2.1B-KART-BORDER" varsa tekrar uygulanmaz
  - Atomik yazma: .tmp -> os.replace
  - Boyut sanity (artis 400-2000 byte)

NASIL CALISTIRILIR:
  cd C:\\cps_dev
  python patch_estetik_c2_1b_css.py
"""

import os
import sys
import shutil
from datetime import datetime

HEDEF = os.path.join('static', 'css', 'cps_ithalat.css')

BASLIK = '/* === PATCH C2.1B-KART-BORDER — sapma yonune gore kart border === */'
SON_ISARET = '/* === PATCH C2.1B-KART-BORDER — son === */'

EKLENECEK_BLOK = '''

''' + BASLIK + '''
/* Amac: Tip kart border'i sapma yonune gore renkli olsun.
   Var.B mantigi:
     - sapma > 0 (asim)     -> KIRMIZI border
     - sapma < 0 (tasarruf) -> YESIL border
     - null/0               -> Gri default (mevcut)
     - bekliyor             -> Sari dashed (degismez)
     - tahmini-yok          -> Mavi dashed (degismez)

   Oncelik :not() ile saglanir: BEKLIYOR/TAHMINI_YOK kartlar icin
   pozitif/negatif border uygulanmaz, mevcut sari/mavi dashed kalir.
   ----------------------------------------------------------------- */

/* Pozitif sapma (asim) - kirmizi solid border */
.cps-ith-tip-kart.kart-pozitif:not(.bekliyor):not(.tahmini-yok) {
  border-color: #fca5a5;
  background: #fef2f2;
}

/* Negatif sapma (tasarruf) - yesil solid border */
.cps-ith-tip-kart.kart-negatif:not(.bekliyor):not(.tahmini-yok) {
  border-color: #86efac;
  background: #f0fdf4;
}

/* Mevcut .sapma-kritik ve .sapma-uyari border'larini etkisizlestir
   (artik isaret bazli renk ana belirleyici - magnitude'e gore degil)
   NOT: Bu siniflar JS C2.1A sonrasi kart icin EKLENMIYOR zaten,
   ama eski kayitlar icin guvenlik amacli override yapiyoruz.
*/
.cps-ith-tip-kart.sapma-kritik.kart-pozitif {
  border-color: #fca5a5;
  background: #fef2f2;
}
.cps-ith-tip-kart.sapma-kritik.kart-negatif {
  border-color: #86efac;
  background: #f0fdf4;
}
.cps-ith-tip-kart.sapma-uyari.kart-pozitif {
  border-color: #fca5a5;
  background: #fef2f2;
}
.cps-ith-tip-kart.sapma-uyari.kart-negatif {
  border-color: #86efac;
  background: #f0fdf4;
}

''' + SON_ISARET + '''
'''


def yaz(msg):
    sys.stdout.write(msg + '\n')
    sys.stdout.flush()


def cik(code, msg):
    yaz(msg)
    sys.exit(code)


def main():
    yaz('')
    yaz('=' * 60)
    yaz('  CPS DEV — Patch C2.1B: Tip kart border renkleri (CSS)')
    yaz('=' * 60)

    if not os.path.isfile(HEDEF):
        cik(1, f'HATA: Hedef dosya bulunamadi: {HEDEF}\n'
               '  Bu scripti C:\\cps_dev\\ dizininde calistir.')

    yaz(f'Hedef  : {HEDEF}')

    try:
        with open(HEDEF, 'r', encoding='utf-8') as f:
            mevcut = f.read()
    except Exception as e:
        cik(2, f'HATA: Dosya okunamadi: {e}')

    ilk_boyut = len(mevcut)
    yaz(f'Boyut  : {ilk_boyut} byte')

    if BASLIK in mevcut:
        cik(0, '\nBILGI: C2.1B patch basligi dosyada zaten mevcut.\n'
               '  Patch daha once uygulanmis - yeniden uygulama yapilmadi.')

    damga = datetime.now().strftime('%Y%m%d_%H%M%S')
    yedek_yol = f'{HEDEF}.yedek_C2_1B_{damga}'
    try:
        shutil.copy2(HEDEF, yedek_yol)
    except Exception as e:
        cik(3, f'HATA: Yedek alinamadi: {e}')

    yaz(f'Yedek  : {yedek_yol}')

    yeni = mevcut + EKLENECEK_BLOK

    if not yeni.startswith(mevcut):
        cik(4, 'HATA: Yeni icerik eski icerigi icermiyor.')
    if BASLIK not in yeni or SON_ISARET not in yeni:
        cik(5, 'HATA: Baslik/son isareti yeni icerikte yok.')

    tmp_yol = HEDEF + '.tmp_patch'
    try:
        with open(tmp_yol, 'w', encoding='utf-8', newline='') as f:
            f.write(yeni)
    except Exception as e:
        try:
            if os.path.isfile(tmp_yol): os.remove(tmp_yol)
        except Exception:
            pass
        cik(6, f'HATA: Gecici dosya yazilamadi: {e}')

    yeni_boyut = os.path.getsize(tmp_yol)
    fark = yeni_boyut - ilk_boyut
    yaz(f'Eklenen: {fark} byte (yeni toplam: {yeni_boyut})')

    if fark < 300 or fark > 3000:
        try:
            os.remove(tmp_yol)
        except Exception:
            pass
        cik(7, f'HATA: Boyut farki beklenen disinda: +{fark} byte.\n'
               '  Beklenen 300-3000 byte. Patch iptal.')

    try:
        os.replace(tmp_yol, HEDEF)
    except Exception as e:
        try:
            if os.path.isfile(tmp_yol): os.remove(tmp_yol)
        except Exception:
            pass
        cik(8, f'HATA: Dosya guncellenemedi: {e}\n  Yedek duruyor.')

    yaz('')
    yaz('=' * 60)
    yaz('  PATCH C2.1B BASARIYLA UYGULANDI (CSS)')
    yaz('=' * 60)
    yaz(f'Dosya  : {HEDEF}')
    yaz(f'Yedek  : {yedek_yol}')
    yaz('')
    yaz('Eklenen border kurallari:')
    yaz('  .kart-pozitif (BEKLIYOR/TAHMINI_YOK degilse) -> kirmizi border')
    yaz('  .kart-negatif (BEKLIYOR/TAHMINI_YOK degilse) -> yesil border')
    yaz('')
    yaz('Beklenen sonuc (ITH-DEMO-001):')
    yaz('  - FOB (-23.5%) -> YESIL border (tasarruf)')
    yaz('  - NAVLUN (+118.6%) -> KIRMIZI border (asim)')
    yaz('  - SIGORTA (%0) -> Gri default')
    yaz('  - GUMRUK / KOMISYON (BEKLIYOR) -> Sari dashed (degismez)')
    yaz('')
    yaz('Test:')
    yaz('  1) Ctrl+Shift+Delete -> Onbellek temizle')
    yaz('  2) Ctrl+F5 hard refresh')
    yaz('  3) ITH-DEMO-001 -> Maliyet sekmesi')
    yaz('  4) FOB karti yesil border, NAVLUN kirmizi olmali')
    yaz('')
    yaz('Geri alma:')
    yaz(f'  copy "{yedek_yol}" "{HEDEF}"')
    yaz('')


if __name__ == '__main__':
    main()
