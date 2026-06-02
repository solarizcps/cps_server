# -*- coding: utf-8 -*-
"""
CPS DEV — Patch C1 v2 AGRESIF: Estetik iyilestirme CSS
=======================================================

KAPSAM:
  static/css/cps_ithalat.css dosyasinin SONUNA daha agresif gorsel
  iyilestirme blogu eklenir. Mevcut hicbir sinif silinmez; sonradan
  tanimlanan ayni sinif CSS cascade ile mevcut degeri override eder.

KULLANICININ ONAYLADIGI 3 OZEL NOT:
  1) Tip kart minimum-height: 120px  → KALIYOR (esit yukseklik)
  2) SAPMA kart sol border (renkli accent) → KALIYOR (vurgu)
  3) Tip kart border: 2px yerine 1.5px → DAHA YUMUSAK

DEGISIKLIKLER (ozet):
  KPI BAR:
    - Detay KPI kart padding: 14/16 -> 22/24
    - Detay KPI deger font: 20px -> 28px (700)
    - Etiket: 12px -> 11px, letter-spacing 0.06em (havadar)

  SAPMA KARTI (5. KPI):
    - Sayi font: 28px -> 32px (800, letter-spacing -0.02em)
    - Sol accent: 4px solid renkli ceperin sol kenarinda
      (negatif=yesil, pozitif/uyari=kirmizi/turuncu — mevcut sinif kombu)

  TIP KARTLARI:
    - Padding: 10/12 -> 18/22
    - Border: 1.5px solid (yumusak)
    - Border-radius: 6px -> 10px
    - min-height: 120px (esit yukseklik)
    - Baslik margin-bottom: 6 -> 14, font 11 -> 12 bold
    - Deger font 15 -> 18 bold
    - TAHMINI_YOK: 1.5px dashed daha doygun mavi
    - BEKLIYOR: 1.5px dashed daha doygun sari

  ROZETLER (tip kart icindeki):
    - padding: 1/6 -> 4/12
    - font: 10px -> 11px (700)
    - text-transform: uppercase + letter-spacing 0.05em
    - border: 1px solid renkli
    - border-radius: 12px (pill)

  TABLO ROZETLERI (.durum-pill ailesi):
    - padding: 5/14
    - font 11px (700) uppercase
    - border 1px solid + min-width 90px (tutarli genislik)

  SAPMA RENGI (Var.B):
    - .cps-ith-sapma-pozitif (asim)   = #b91c1c kirmizi
    - .cps-ith-sapma-negatif (tasarruf) = #047857 yesil
    - Tip kart deger-mini icindeki bu siniflar 700 font

  TABLO:
    - td padding 12/16
    - thead th font 11px bold uppercase
    - alt cizgi 2px border-bottom

  YARDIMCI (JS C2'de kullanilacak):
    - .cps-ith-tip-kart-satir / -label / -deger-mini / -ayrac
    - .cps-ith-tablo-info-ikon

GUVENLIK:
  - Yedek alinir (tarih damgali)
  - Idempotent: v2 basligi varsa tekrar uygulanmaz
  - Atomik yazma: .tmp -> os.replace
  - Boyut sanity (5000-15000 byte ekleme bekleniyor)

NASIL CALISTIRILIR:
  cd C:\\cps_dev
  python patch_estetik_c1_agresif.py
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
# BASLIKLAR
# =============================================================
BASLIK_V2 = '/* === ESTETIK PATCH C1 v2 AGRESIF — KPI/tip kart belirgin + sapma rengi === */'
SON_ISARET_V2 = '/* === ESTETIK PATCH C1 v2 AGRESIF — son === */'

# Eski v1 basligi (varsa not amacli)
BASLIK_V1 = '/* === ESTETIK PATCH C1 v1 — KPI/tip kart ferahlik + sapma rengi === */'

# =============================================================
# EKLENECEK BLOK
# =============================================================
EKLENECEK_BLOK = '''

''' + BASLIK_V2 + '''
/* Amac:
     1) Tip kartlari ve KPI bar'da net gorsel ferahlik
     2) SAPMA kartinda sol renkli accent + buyuk bold sayi
     3) Rozet ve pill standartlasmasi (uppercase, weight 700, letter-spacing)
     4) Tip kart 3 satirli yeni duzen icin yardimci siniflar (JS C2)
     5) Sapma rengi Var.B: pozitif=asim=KIRMIZI, negatif=tasarruf=YESIL

   Kullanicinin 3 ozel istegi:
     - min-height 120px tip kartlarda (esit yukseklik)
     - SAPMA sol accent korunuyor
     - Tip kart border 1.5px (yumusak)

   Renk paleti mevcutla uyumlu (daha doygun tonlar tercih edildi):
     - Yesil:  #d1fae5 / #10b981 / #047857 / #065f46 / #86efac
     - Kirmizi: #fee2e2 / #ef4444 / #b91c1c / #991b1b / #fca5a5
     - Mavi:   #dbeafe / #60a5fa / #1e40af / #93c5fd
     - Sari:   #fef3c7 / #f59e0b / #92400e / #fcd34d / #fbbf24
     - Gri:    #f3f4f6 / #6b7280 / #4b5563 / #d1d5db
   ----------------------------------------------------------------- */


/* =====================================================================
   KPI BAR — agresif ferahlik
   ===================================================================== */
.cps-ith-detay-kpi .cps-ith-kpi-kart {
  padding: 22px 24px;            /* eski: 14/16 */
}
.cps-ith-detay-kpi .cps-ith-kpi-deger {
  font-size: 28px;               /* eski: 20px */
  font-weight: 700;
  letter-spacing: -0.01em;
  line-height: 1.1;
}
.cps-ith-detay-kpi .cps-ith-kpi-etiket {
  font-size: 11px;               /* eski: 12px - daha mini, daha hava */
  letter-spacing: 0.06em;        /* eski: 0.02em - daha airy */
  margin-bottom: 10px;           /* eski: 6px - nefes */
  color: #6b7280;
  font-weight: 500;
}


/* =====================================================================
   SAPMA KARTI (5. KPI - son kart) — vurgu icin sol accent + buyuk sayi
   ===================================================================== */
/* Default: notr accent (gri) */
.cps-ith-detay-kpi .cps-ith-kpi-kart:last-child {
  border-left: 4px solid #d1d5db;
  padding-left: 20px;            /* sol border icin */
}

/* Sapma sayisi BUYUK */
.cps-ith-detay-kpi .cps-ith-kpi-kart:last-child .cps-ith-kpi-deger {
  font-size: 32px;               /* eski C1 v1: 24px */
  font-weight: 800;
  letter-spacing: -0.02em;
  line-height: 1.05;
}

/* Mevcut .cps-ith-sapma-kritik / .cps-ith-sapma-uyari class'lari
   sapma sayisinin uzerinde — bunlar accent rengi de etkiler */
.cps-ith-detay-kpi .cps-ith-kpi-kart:last-child:has(.cps-ith-sapma-kritik) {
  border-left-color: #b91c1c;
  background: linear-gradient(to right, #fef2f2 0, #fff 80px);
}
.cps-ith-detay-kpi .cps-ith-kpi-kart:last-child:has(.cps-ith-sapma-uyari) {
  border-left-color: #d97706;
  background: linear-gradient(to right, #fffbeb 0, #fff 80px);
}
/* :has() destegi olmayan eski tarayicilar icin geri donus: sade kart */


/* =====================================================================
   TIP KART — agresif ferahlik (kullanici onayli 3 nota uygun)
   ===================================================================== */
.cps-ith-tip-kart {
  padding: 18px 22px;            /* eski: 10/12 */
  border-width: 1.5px;           /* kullanici istegi: 2px yerine 1.5px (yumusak) */
  border-style: solid;
  border-color: #e5e7eb;
  border-radius: 10px;           /* eski: 6px */
  min-height: 120px;             /* kullanici istegi: kartlar esit yukseklik */
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  background: #fff;              /* eski: #f9fafb -> beyaza cikti, daha temiz */
}
.cps-ith-tip-kart-ad {
  margin-bottom: 14px;           /* eski: 6px */
  font-size: 12px;               /* eski: 11px */
  font-weight: 700;              /* eski: 600 */
  color: #374151;                /* eski: #6b7280 - daha kontrast */
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.cps-ith-tip-kart-deger {
  font-size: 18px;               /* eski: 15px */
  font-weight: 700;
  color: #111827;
  font-variant-numeric: tabular-nums;
  margin-bottom: 6px;
  line-height: 1.2;
}
.cps-ith-tip-kart-alt {
  font-size: 12px;               /* eski: 11px */
  color: #6b7280;                /* eski: #9ca3af - daha okunur */
  font-variant-numeric: tabular-nums;
  margin-top: 8px;
  line-height: 1.4;
}

/* TAHMINI_YOK — daha doygun mavi dashed */
.cps-ith-tip-kart.tahmini-yok {
  border-style: dashed;
  border-width: 1.5px;
  border-color: #60a5fa;         /* eski: #93c5fd */
  background: #dbeafe;           /* eski: #eff6ff */
}

/* BEKLIYOR — daha doygun sari dashed */
.cps-ith-tip-kart.bekliyor {
  border-style: dashed;
  border-width: 1.5px;
  border-color: #fbbf24;         /* eski: #fde68a */
  background: #fef3c7;           /* eski: #fffbeb */
}


/* =====================================================================
   TIP KART — yeni 3 satirli duzen icin yardimci siniflar (JS C2)
   ===================================================================== */
.cps-ith-tip-kart-ayrac {
  height: 1px;
  background: transparent;
  border-top: 1px dashed #e5e7eb;
  margin: 12px 0;
}
.cps-ith-tip-kart-satir {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 10px;
  margin-top: 5px;
  margin-bottom: 5px;
  line-height: 1.5;
}
.cps-ith-tip-kart-label {
  font-size: 12px;
  color: #6b7280;
  font-weight: 500;
  white-space: nowrap;
}
.cps-ith-tip-kart-deger-mini {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
  font-variant-numeric: tabular-nums;
  text-align: right;
}


/* =====================================================================
   SAPMA RENGI — Var.B (pozitif=asim=KIRMIZI, negatif=tasarruf=YESIL)
   ===================================================================== */
.cps-ith-sapma-pozitif {
  color: #b91c1c;
}
.cps-ith-sapma-negatif {
  color: #047857;
}
/* Tip kart icinde guclu vurgu */
.cps-ith-tip-kart .cps-ith-tip-kart-deger-mini.cps-ith-sapma-pozitif {
  color: #b91c1c;
  font-weight: 700;
}
.cps-ith-tip-kart .cps-ith-tip-kart-deger-mini.cps-ith-sapma-negatif {
  color: #047857;
  font-weight: 700;
}


/* =====================================================================
   ROZETLER — tip kart icindeki (Patch B base sinifi tuning)
   ===================================================================== */
.cps-ith-tip-kart-rozet {
  padding: 4px 12px;             /* eski: 1/6 */
  font-size: 11px;               /* eski: 10px */
  font-weight: 700;              /* eski: 500 */
  letter-spacing: 0.05em;
  text-transform: uppercase;
  border-radius: 12px;
  line-height: 1.4;
  border: 1px solid transparent;
  margin-left: 8px;
  vertical-align: middle;
  white-space: nowrap;
}
.cps-ith-tip-kart-rozet-bekliyor {
  background: #fef3c7;
  color: #92400e;
  border-color: #fcd34d;         /* eski: #fde68a - daha belirgin */
}
.cps-ith-tip-kart-rozet-yeni {
  background: #dbeafe;
  color: #1e40af;
  border-color: #93c5fd;         /* eski: #bfdbfe - daha belirgin */
}


/* =====================================================================
   KPI ALT METNI — netlik tuning (Patch A overrides)
   ===================================================================== */
.cps-ith-kpi-alt-bilgi {
  font-size: 11px;
  color: #6b7280;
  margin-top: 6px;
  font-weight: 500;
}
.cps-ith-kpi-alt-uyari {
  font-size: 11px;
  color: #b45309;                /* eski: #d97706 - daha kontrast */
  margin-top: 6px;
  font-weight: 600;
}
.cps-ith-kpi-sapma-ikon {
  font-size: 16px;               /* eski: 14px - daha gorulebilir */
  margin-left: 6px;
}


/* =====================================================================
   TABLO — Tip Bazli Sapma Ozeti (.cps-ith-sapma-tablo)
   ===================================================================== */
.cps-ith-sapma-tablo th {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #4b5563;
  padding: 12px 16px;
  border-bottom: 2px solid #e5e7eb;
}
.cps-ith-sapma-tablo td {
  padding: 12px 16px;            /* eski: muhtemelen 8/12 */
  border-bottom: 1px solid #f3f4f6;
  font-variant-numeric: tabular-nums;
}
.cps-ith-sapma-tablo tbody tr:last-child td {
  border-bottom: none;
}

/* Sapma yuzde hucresi - bold + tabular */
.cps-ith-sapma-tablo td.sapma-yuzde-cell {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}


/* =====================================================================
   TABLO — DURUM kolonu pill standardi (.durum-pill ailesi - JS C3'te)
   ===================================================================== */
.cps-ith-sapma-tablo .durum-pill {
  display: inline-block;
  padding: 5px 14px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  border-radius: 12px;
  white-space: nowrap;
  line-height: 1.4;
  border: 1px solid transparent;
  min-width: 90px;
  text-align: center;
}
.cps-ith-sapma-tablo .durum-pill-kritik {
  background: #fee2e2;
  color: #991b1b;
  border-color: #fca5a5;
}
.cps-ith-sapma-tablo .durum-pill-uyari {
  background: #fef3c7;
  color: #92400e;
  border-color: #fcd34d;
}
.cps-ith-sapma-tablo .durum-pill-bekliyor {
  background: #f3f4f6;
  color: #4b5563;
  border-color: #d1d5db;
}
.cps-ith-sapma-tablo .durum-pill-yeni {
  background: #dbeafe;
  color: #1e40af;
  border-color: #93c5fd;
}
.cps-ith-sapma-tablo .durum-pill-mix {
  background: #fef3c7;
  color: #92400e;
  border-color: #fcd34d;
}
.cps-ith-sapma-tablo .durum-pill-tasarruf {
  background: #d1fae5;
  color: #065f46;
  border-color: #86efac;
}


/* =====================================================================
   TABLO — info ikonu (karisik para birimi tooltip'i icin)
   ===================================================================== */
.cps-ith-tablo-info-ikon {
  display: inline-block;
  margin-left: 4px;
  color: #d97706;
  font-size: 12px;
  cursor: help;
  vertical-align: baseline;
}


/* =====================================================================
   GENEL SPACING — bolumler arasi nefes
   ===================================================================== */
.cps-ith-sapma-bolum {
  margin-bottom: 28px;            /* eski: 20px */
}

''' + SON_ISARET_V2 + '''
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
    yaz('  CPS DEV — Patch C1 v2 AGRESIF: Estetik CSS')
    yaz('=' * 60)

    # --- 1) Dosya var mi? ---
    if not os.path.isfile(HEDEF):
        cik(1, f'HATA: Hedef dosya bulunamadi: {HEDEF}\n'
               '  Bu scripti C:\\cps_dev\\ dizininde calistir.')

    yaz(f'Hedef  : {HEDEF}')

    # --- 2) Mevcut icerigi oku ---
    try:
        with open(HEDEF, 'r', encoding='utf-8') as f:
            mevcut = f.read()
    except Exception as e:
        cik(2, f'HATA: Dosya okunamadi: {e}')

    ilk_boyut = len(mevcut)
    yaz(f'Boyut  : {ilk_boyut} byte (mevcut)')

    # --- 3) v2 zaten uygulanmis mi? (idempotency) ---
    if BASLIK_V2 in mevcut:
        cik(0, '\nBILGI: C1 v2 AGRESIF basligi dosyada zaten mevcut.\n'
               '  Patch daha once uygulanmis - yeniden uygulama yapilmadi.')

    # --- 4) Eski v1 izi var mi? (uyari amacli, uygulamaya engel degil) ---
    if BASLIK_V1 in mevcut:
        yaz('UYARI: Eski v1 patch izi dosyada bulundu — v2 onun uzerine eklenecek.')
        yaz('       (CSS cascade nedeniyle v2 degerleri override eder)')

    # --- 5) Yedek al ---
    damga = datetime.now().strftime('%Y%m%d_%H%M%S')
    yedek_yol = f'{HEDEF}.yedek_C1agr_{damga}'
    try:
        shutil.copy2(HEDEF, yedek_yol)
    except Exception as e:
        cik(3, f'HATA: Yedek alinamadi: {e}\n  Patch uygulanmadi.')

    yaz(f'Yedek  : {yedek_yol}')

    # --- 6) Yeni icerigi hazirla ---
    yeni_icerik = mevcut + EKLENECEK_BLOK

    if not yeni_icerik.startswith(mevcut):
        cik(4, 'HATA: Yeni icerik eski icerigi icermiyor.\n  Patch iptal.')

    if BASLIK_V2 not in yeni_icerik or SON_ISARET_V2 not in yeni_icerik:
        cik(5, 'HATA: v2 baslik/son isareti yeni icerikte yok.\n  Patch iptal.')

    # --- 7) Gecici dosyaya yaz ---
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
        cik(6, f'HATA: Gecici dosya yazilamadi: {e}')

    # --- 8) Boyut sanity ---
    yeni_boyut = os.path.getsize(tmp_yol)
    fark = yeni_boyut - ilk_boyut
    yaz(f'Eklenen: {fark} byte (yeni toplam: {yeni_boyut})')

    if fark < 4000 or fark > 15000:
        try:
            os.remove(tmp_yol)
        except Exception:
            pass
        cik(7, f'HATA: Boyut farki beklenen disinda: +{fark} byte.\n'
               '  Beklenen 4000-15000 byte. Patch iptal.')

    # --- 9) Atomik rename ---
    try:
        os.replace(tmp_yol, HEDEF)
    except Exception as e:
        try:
            if os.path.isfile(tmp_yol):
                os.remove(tmp_yol)
        except Exception:
            pass
        cik(8, f'HATA: Dosya guncellenemedi: {e}\n  Yedek duruyor.')

    # --- 10) Son dogrulama ---
    try:
        with open(HEDEF, 'r', encoding='utf-8') as f:
            son = f.read()
    except Exception as e:
        cik(9, f'UYARI: Patch yazildi ama dogrulama icin okunamadi: {e}\n'
               f'  Yedek: {yedek_yol}')

    if BASLIK_V2 not in son or SON_ISARET_V2 not in son:
        cik(10, 'UYARI: Dosya yazildi ama baslik/son isareti yok.\n'
                f'  Yedegi kontrol et: {yedek_yol}')

    # --- BASARILI ---
    yaz('')
    yaz('=' * 60)
    yaz('  PATCH C1 v2 AGRESIF BASARIYLA UYGULANDI')
    yaz('=' * 60)
    yaz(f'Dosya  : {HEDEF}')
    yaz(f'Yedek  : {yedek_yol}')
    yaz('')
    yaz('Etkin degisiklikler:')
    yaz('  KPI BAR:')
    yaz('    - Kart padding 14/16 -> 22/24 (ferah)')
    yaz('    - Deger font 20px -> 28px (700)')
    yaz('  SAPMA KARTI:')
    yaz('    - Sol 4px renkli accent (kritik=kirmizi, uyari=turuncu)')
    yaz('    - Sayi 32px (800, sikistirilmis)')
    yaz('  TIP KARTLARI:')
    yaz('    - Padding 10/12 -> 18/22')
    yaz('    - Border 1.5px (yumusak), radius 10px')
    yaz('    - min-height 120px (esit yukseklik)')
    yaz('    - TAHMINI_YOK / BEKLIYOR daha doygun renkler')
    yaz('  ROZETLER:')
    yaz('    - 4/12 padding, 11px 700 uppercase, 12px radius')
    yaz('    - Belirgin border')
    yaz('  TABLO:')
    yaz('    - Td padding 12/16, thead 2px alt cizgi')
    yaz('    - .durum-pill standardi (90px min-width)')
    yaz('  SAPMA RENGI (Var.B):')
    yaz('    - .cps-ith-sapma-pozitif #b91c1c (kirmizi)')
    yaz('    - .cps-ith-sapma-negatif #047857 (yesil)')
    yaz('')
    yaz('JS henuz yeni siniflari kullanmiyor (C2/C3 ile gelecek):')
    yaz('  - .cps-ith-tip-kart-satir, -label, -deger-mini, -ayrac')
    yaz('  - .durum-pill-* (tablo)')
    yaz('  - .cps-ith-tablo-info-ikon')
    yaz('')
    yaz('Test:')
    yaz('  1) Ctrl+Shift+Delete -> Onbellek temizle')
    yaz('  2) Ctrl+F5 hard refresh')
    yaz('  3) ITH-DEMO-001 ac:')
    yaz('     - SAPMA kartinda sol kirmizi border accent gorulebilir')
    yaz('     - SAPMA sayisi cok daha buyuk ve kalin')
    yaz('     - Tip kartlari belirgin daha ferah')
    yaz('     - Rozetler daha buyuk, uppercase, kalin')
    yaz('  4) Layout BOZULDU mu? OLMAMALI')
    yaz('  5) Konsol kirmizi hata? OLMAMALI')
    yaz('')
    yaz('Geri alma:')
    yaz(f'  copy "{yedek_yol}" "{HEDEF}"')
    yaz('')


if __name__ == '__main__':
    main()
