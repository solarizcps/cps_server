# -*- coding: utf-8 -*-
"""
CPS DEV — Patch A: Sapma UI icin CSS eklentisi
===============================================

KAPSAM:
  static/css/cps_ithalat.css dosyasinin SONUNA yeni siniflar ekler.
  Mevcut hicbir sinif/kurala dokunulmaz.

EKLENEN SINIFLAR:
  .cps-ith-kpi-alt-bilgi          — "3 tip karsilastirildi" gri mini metin
  .cps-ith-kpi-alt-uyari          — "Karisik para" turuncu uyari
  .cps-ith-kpi-sapma-ikon         — uyari ikonu (inline, turuncu)
  .cps-ith-tip-kart-rozet         — emoji rozet konteyneri (base)
  .cps-ith-tip-kart-rozet-bekliyor → sari BEKLIYOR rozeti (palete uyumlu)
  .cps-ith-tip-kart-rozet-yeni     → mavi YENI/TAHMINI_YOK rozeti
  .cps-ith-tip-kart.tahmini-yok    → TAHMINI_YOK kart arka plan (mavi dashed)

KURALLAR:
  - Yedek alinir (tarih damgali)
  - Idempotent: basligi bulursa tekrar eklemez
  - Atomik yazma: .tmp -> os.replace
  - Minimum degisiklik
  - Backend / JS / DB / parser / UI layout'a dokunmaz

NASIL CALISTIRILIR:
  cd C:\\cps_dev
  python patch_sapma_css.py
"""

import os
import sys
import shutil
from datetime import datetime

# =============================================================
# HEDEF
# =============================================================
HEDEF = os.path.join('static', 'css', 'cps_ithalat.css')

# =============================================================
# BASLIK (idempotency icin esiz anahtar)
# =============================================================
BASLIK = '/* === SAPMA UI PATCH v1 — frontend genisletme (CSS) === */'
SON_ISARET = '/* === SAPMA UI PATCH v1 — son === */'

# =============================================================
# EKLENECEK BLOK
# =============================================================
EKLENECEK_BLOK = '''

''' + BASLIK + '''
/* Amac:
     1) Sapma KPI kartinin altinda mini bilgi/uyari metni
     2) Tip kartlarinda BEKLIYOR (⏳) ve TAHMINI_YOK (🆕) rozetleri
     3) Sapma yaninda uyari ikonu (sapma_guvenilir=false durumu)
   Renk paleti MEVCUT cps_ithalat.css ile uyumlu:
     - Turuncu uyari:   #fef3c7 / #f59e0b / #d97706 / #92400e
     - Mavi bilgi:      #dbeafe / #60a5fa / #1e40af / #eff6ff / #bfdbfe
     - Gri nötr:        #e5e7eb / #6b7280 / #4b5563
   ----------------------------------------------------------------- */

/* --- KPI alt metin varyantlari (sapma KPI kartinin altinda) --- */
.cps-ith-kpi-alt-bilgi {
  font-size: 11px;
  color: #6b7280;
  line-height: 1.3;
  margin-top: 2px;
}
.cps-ith-kpi-alt-uyari {
  font-size: 11px;
  color: #d97706;
  line-height: 1.3;
  margin-top: 2px;
  font-weight: 500;
}

/* --- Sapma yaninda kucuk uyari ikonu (inline) --- */
.cps-ith-kpi-sapma-ikon {
  display: inline-block;
  margin-left: 4px;
  color: #d97706;
  font-size: 14px;
  cursor: help;
  vertical-align: baseline;
}

/* --- Tip kart rozet (adin yaninda kucuk pill) --- */
.cps-ith-tip-kart-rozet {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 500;
  border-radius: 10px;
  background: #e5e7eb;
  color: #4b5563;
  vertical-align: middle;
  white-space: nowrap;
  line-height: 1.4;
}
.cps-ith-tip-kart-rozet-bekliyor {
  background: #fef3c7;
  color: #92400e;
}
.cps-ith-tip-kart-rozet-yeni {
  background: #dbeafe;
  color: #1e40af;
}

/* --- Tip kart: TAHMINI_YOK durumu (planda olmayan kalem) --- */
.cps-ith-tip-kart.tahmini-yok {
  border-style: dashed;
  background: #eff6ff;
  border-color: #bfdbfe;
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
    yaz('  CPS DEV — Patch A: Sapma UI CSS eklentisi')
    yaz('=' * 60)

    # --- 1) Dosya var mi? ---
    if not os.path.isfile(HEDEF):
        cik(1, f'HATA: Hedef dosya bulunamadi: {HEDEF}\n'
               '  Bu scripti C:\\cps_dev\\ dizininde calistirdigindan emin ol.')

    yaz(f'Hedef  : {HEDEF}')

    # --- 2) Mevcut icerigi oku ---
    try:
        with open(HEDEF, 'r', encoding='utf-8') as f:
            mevcut = f.read()
    except Exception as e:
        cik(2, f'HATA: Dosya okunamadi: {e}')

    ilk_boyut = len(mevcut)
    yaz(f'Boyut  : {ilk_boyut} byte (mevcut)')

    # --- 3) Idempotency kontrolu ---
    if BASLIK in mevcut:
        cik(0, '\nBILGI: Patch basligi dosyada zaten mevcut.\n'
               '  Patch daha once uygulanmis — yeniden uygulama yapilmadi.\n'
               '  (Hic dosya degisikligi yok, yedek de alinmadi.)')

    # --- 4) Yedek al ---
    damga = datetime.now().strftime('%Y%m%d_%H%M%S')
    yedek_yol = f'{HEDEF}.yedek_{damga}'
    try:
        shutil.copy2(HEDEF, yedek_yol)
    except Exception as e:
        cik(3, f'HATA: Yedek alinamadi: {e}\n'
               '  Patch uygulanmadi (yedek zorunlu).')

    yaz(f'Yedek  : {yedek_yol}')

    # --- 5) Yeni icerigi hazirla ---
    yeni_icerik = mevcut + EKLENECEK_BLOK

    # Bos satirda bitiyorsa okudugumuz mevcut, yeni blok basinda ekstra \n
    # zaten var. Fazla bos satir kozmetik, sorun degil.

    # Sanity: yeni icerik eski icerigi icermeli
    if not yeni_icerik.startswith(mevcut):
        cik(4, 'HATA: Yeni icerik eski icerigi icermiyor (beklenmedik).\n'
               '  Patch iptal, yedek duruyor.')

    # Sanity: baslik yeni icerige gercekten girmis mi?
    if BASLIK not in yeni_icerik or SON_ISARET not in yeni_icerik:
        cik(5, 'HATA: Eklenecek baslik/son isareti yeni icerikte yok.\n'
               '  Patch iptal.')

    # --- 6) Gecici dosyaya yaz ---
    tmp_yol = HEDEF + '.tmp_patch'
    try:
        with open(tmp_yol, 'w', encoding='utf-8', newline='') as f:
            f.write(yeni_icerik)
    except Exception as e:
        try:
            if os.path.isfile(tmp_yol):
                os.remove(tmp_yol)
        except Exception:
            pass
        cik(6, f'HATA: Gecici dosya yazilamadi: {e}\n'
               '  Orijinal dosya dokunulmadi.')

    # --- 7) Gecici dosya boyut kontrolu ---
    try:
        yeni_boyut = os.path.getsize(tmp_yol)
    except Exception as e:
        cik(7, f'HATA: Gecici dosya stat alinamadi: {e}')

    if yeni_boyut <= ilk_boyut:
        try:
            os.remove(tmp_yol)
        except Exception:
            pass
        cik(8, f'HATA: Yeni dosya boyutu ({yeni_boyut}) mevcuttan ({ilk_boyut}) '
               f'kucuk/esit - beklenmedik.\n  Patch iptal.')

    eklenen_byte = yeni_boyut - ilk_boyut
    yaz(f'Eklenen: {eklenen_byte} byte (yeni toplam: {yeni_boyut} byte)')

    # --- 8) Atomik rename ---
    try:
        os.replace(tmp_yol, HEDEF)
    except Exception as e:
        try:
            if os.path.isfile(tmp_yol):
                os.remove(tmp_yol)
        except Exception:
            pass
        cik(9, f'HATA: Dosya guncellenemedi (rename): {e}\n'
               '  Orijinal dosya dokunulmadi, yedek duruyor.')

    # --- 9) Son dogrulama ---
    try:
        with open(HEDEF, 'r', encoding='utf-8') as f:
            son_icerik = f.read()
    except Exception as e:
        cik(10, f'UYARI: Patch uygulandi ama dogrulama icin dosya okunamadi.\n'
                f'  {e}\n'
                f'  Yedek: {yedek_yol}')

    if BASLIK not in son_icerik or SON_ISARET not in son_icerik:
        cik(11, 'UYARI: Dosya yazildi ama patch basligi/son isareti bulunamadi.\n'
                f'  Yedegi kontrol et: {yedek_yol}')

    # --- BASARILI ---
    yaz('')
    yaz('=' * 60)
    yaz('  PATCH A BASARIYLA UYGULANDI')
    yaz('=' * 60)
    yaz(f'Dosya  : {HEDEF}')
    yaz(f'Yedek  : {yedek_yol}')
    yaz('')
    yaz('Eklenen siniflar:')
    yaz('  .cps-ith-kpi-alt-bilgi')
    yaz('  .cps-ith-kpi-alt-uyari')
    yaz('  .cps-ith-kpi-sapma-ikon')
    yaz('  .cps-ith-tip-kart-rozet (+ -bekliyor / -yeni)')
    yaz('  .cps-ith-tip-kart.tahmini-yok')
    yaz('')
    yaz('ETKI: Bu patch sadece yeni siniflar ekler. JS henuz bu siniflari')
    yaz('       kullanmadigi icin sayfada GORSEL DEGISIKLIK BEKLEMIYORUZ.')
    yaz('       Patch B (JS) uygulaninca rozetler ve mini metinler gorunecek.')
    yaz('')
    yaz('Test:')
    yaz('  - Tarayicida Ctrl+F5 hard refresh')
    yaz('  - Sayfalarda gorsel bozulma VAR MI? (Olmamali)')
    yaz('  - Konsolda CSS parse hatasi VAR MI? (Olmamali)')
    yaz('')
    yaz('Geri alma:')
    yaz(f'  copy "{yedek_yol}" "{HEDEF}"')
    yaz('')


if __name__ == '__main__':
    main()
