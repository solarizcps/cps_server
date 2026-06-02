# -*- coding: utf-8 -*-
"""
CPS DEV — Patch C2.1A: Tip kart border renk dinamigi (JS)
==========================================================

KAPSAM:
  static/js/cps_ithalat_detay.js icindeki tipOzetDoldur (C2 sonrasi
  hali) icine, kart container'ina sapma yonune gore class ekleme:
    - sapma_yuzde > 0  -> kart.classList.add('kart-pozitif')   (asim)
    - sapma_yuzde < 0  -> kart.classList.add('kart-negatif')   (tasarruf)
    - null/0           -> ek class yok (gri default)

  Ayrica MEVCUT magnitude bazli siniflari (sapma-kritik / sapma-uyari)
  kart icin TEMIZLIYORUZ — yeni mantik isaret bazli oldugu icin
  bunlar artik border'i bozmasin diye.

ONCELIK SIRASI (CSS specificity):
  1) BEKLIYOR     → sari dashed   (Patch B/C1)
  2) TAHMINI_YOK  → mavi dashed   (Patch B/C1)
  3) kart-pozitif → kirmizi solid (yeni)
  4) kart-negatif → yesil solid   (yeni)
  5) Sapma yok    → gri default

GUVENLIK:
  - Yedek alinir (tarih damgali, ayri yedek)
  - Idempotent: marker "C2.1A-KART-RENK" varsa tekrar uygulanmaz
  - Eski blok (Patch C2 sonrasi hali) bulunamazsa hicbir degisiklik
  - Atomik yazma: .tmp -> os.replace
  - Boyut sanity (artis 200-1500 byte bekleniyor)
  - Brace/paren denge degismemeli

NASIL CALISTIRILIR:
  cd C:\\cps_dev
  python patch_estetik_c2_1a_js.py
"""

import os
import sys
import shutil
from datetime import datetime

HEDEF = os.path.join('static', 'js', 'cps_ithalat_detay.js')

# =============================================================
# ESKI BLOK — Patch C2 sonrasi hali (kart class block bolumu)
# Sadece bu kucuk parcayi degistirecegiz, tum fonksiyonu degil
# =============================================================
ESKI = """        var kart = document.createElement('div');
        kart.className = 'cps-ith-tip-kart';
        // Geriye uyumlu: eski 'bekliyor' flag'i
        if (t.bekliyor) kart.classList.add('bekliyor');
        // Patch B: TAHMINI_YOK mavi dashed
        if (t.sinif === 'TAHMINI_YOK') kart.classList.add('tahmini-yok');
        if (t.sapma_yuzde != null) {
          var abs = Math.abs(t.sapma_yuzde);
          if (abs > 10)      kart.classList.add('sapma-kritik');
          else if (abs > 5)  kart.classList.add('sapma-uyari');
        }"""

YENI = """        var kart = document.createElement('div');
        kart.className = 'cps-ith-tip-kart';
        // C2.1A-KART-RENK: Sapma yonune gore border rengi
        // Geriye uyumlu: eski 'bekliyor' flag'i (sari dashed - en yuksek oncelik)
        if (t.bekliyor) kart.classList.add('bekliyor');
        // Patch B: TAHMINI_YOK mavi dashed (BEKLIYOR yoksa)
        if (t.sinif === 'TAHMINI_YOK') kart.classList.add('tahmini-yok');
        // C2.1A: Sapma isaretine gore border (BEKLIYOR/TAHMINI_YOK degilse)
        // - sapma > 0 -> kart-pozitif (kirmizi - asim)
        // - sapma < 0 -> kart-negatif (yesil - tasarruf)
        // - null/0    -> default gri
        if (t.sapma_yuzde != null) {
          if (t.sapma_yuzde > 0)      kart.classList.add('kart-pozitif');
          else if (t.sapma_yuzde < 0) kart.classList.add('kart-negatif');
        }"""


def yaz(msg):
    sys.stdout.write(msg + '\n')
    sys.stdout.flush()


def cik(code, msg):
    yaz(msg)
    sys.exit(code)


def naive_balance(metin):
    return {
        'brace':   metin.count('{') - metin.count('}'),
        'paren':   metin.count('(') - metin.count(')'),
        'bracket': metin.count('[') - metin.count(']'),
    }


def main():
    yaz('')
    yaz('=' * 60)
    yaz('  CPS DEV — Patch C2.1A: Tip kart border renk dinamigi (JS)')
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
    ilk_balance = naive_balance(mevcut)
    yaz(f'Boyut  : {ilk_boyut} byte')

    # Idempotency
    if 'C2.1A-KART-RENK' in mevcut:
        cik(0, '\nBILGI: C2.1A patch marker dosyada zaten mevcut.\n'
               '  Patch daha once uygulanmis - yeniden uygulama yapilmadi.')

    # On kosul: C2 patch uygulanmis olmali
    if 'C2-3SATIR-V1' not in mevcut:
        cik(3, 'HATA: C2 patch (3 satirli duzen) bu dosyada bulunamadi.\n'
               '  C2.1A C2 sonrasi calisir. Once C2 uygulanmali.\n'
               '  Hicbir degisiklik yapilmadi.')

    eski_sayi = mevcut.count(ESKI)
    yaz(f'Eski blok eslesmesi: {eski_sayi}x  (beklenen: 1)')
    if eski_sayi == 0:
        cik(4, 'HATA: C2 sonrasi kart class blogu bulunamadi.\n'
               '  Dosya beklenen halde degil.\n'
               '  Hicbir degisiklik yapilmadi.')
    if eski_sayi > 1:
        cik(5, f'HATA: Eski blok {eski_sayi} kez geciyor (beklenen 1).\n'
               '  Patch iptal.')

    # Yedek
    damga = datetime.now().strftime('%Y%m%d_%H%M%S')
    yedek_yol = f'{HEDEF}.yedek_C2_1A_{damga}'
    try:
        shutil.copy2(HEDEF, yedek_yol)
    except Exception as e:
        cik(6, f'HATA: Yedek alinamadi: {e}')

    yaz(f'Yedek  : {yedek_yol}')

    # Replace
    yeni = mevcut.replace(ESKI, YENI, 1)
    if yeni == mevcut:
        cik(7, 'HATA: Replace sonrasi icerik aynen kaldi.')
    if 'C2.1A-KART-RENK' not in yeni:
        cik(8, 'HATA: Yeni marker yeni icerikte yok.')

    # Balance check
    yeni_balance = naive_balance(yeni)
    if yeni_balance != ilk_balance:
        cik(9, f'HATA: Patch sonrasi denge degisti.\n'
               f'  Oncesi : {ilk_balance}\n'
               f'  Sonrasi: {yeni_balance}')

    # Atomik yaz
    tmp_yol = HEDEF + '.tmp_patch'
    try:
        with open(tmp_yol, 'w', encoding='utf-8', newline='') as f:
            f.write(yeni)
    except Exception as e:
        try:
            if os.path.isfile(tmp_yol): os.remove(tmp_yol)
        except Exception:
            pass
        cik(10, f'HATA: Gecici dosya yazilamadi: {e}')

    yeni_boyut = os.path.getsize(tmp_yol)
    fark = yeni_boyut - ilk_boyut
    yaz(f'Boyut farki: +{fark} byte (yeni toplam: {yeni_boyut})')

    if fark < 100 or fark > 2000:
        try:
            os.remove(tmp_yol)
        except Exception:
            pass
        cik(11, f'HATA: Boyut farki beklenen disinda: +{fark} byte.\n'
                '  Beklenen 100-2000 byte. Patch iptal.')

    try:
        os.replace(tmp_yol, HEDEF)
    except Exception as e:
        try:
            if os.path.isfile(tmp_yol): os.remove(tmp_yol)
        except Exception:
            pass
        cik(12, f'HATA: Dosya guncellenemedi: {e}\n  Yedek duruyor.')

    yaz('')
    yaz('=' * 60)
    yaz('  PATCH C2.1A BASARIYLA UYGULANDI (JS)')
    yaz('=' * 60)
    yaz(f'Dosya  : {HEDEF}')
    yaz(f'Yedek  : {yedek_yol}')
    yaz('')
    yaz('Yeni davranis:')
    yaz('  Tip kartlarinda artik:')
    yaz('  - sapma > 0 -> .kart-pozitif class (kirmizi border)')
    yaz('  - sapma < 0 -> .kart-negatif class (yesil border)')
    yaz('  - null/0    -> ek class yok (gri default)')
    yaz('  - .sapma-kritik / .sapma-uyari ARTIK eklenmiyor (kart icin)')
    yaz('')
    yaz('SIRADAKI: Patch C2.1B (CSS) — bu siniflar icin renk tanimi')
    yaz('  (Henuz CSS yoksa kartlar gri kalir, sorun degil)')
    yaz('')
    yaz('Geri alma:')
    yaz(f'  copy "{yedek_yol}" "{HEDEF}"')
    yaz('')


if __name__ == '__main__':
    main()
