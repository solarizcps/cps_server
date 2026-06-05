# -*- coding: utf-8 -*-
"""
CPS DEV — Patch C1: Estetik iyilestirme CSS
============================================

KAPSAM:
  static/css/cps_ithalat.css dosyasinin SONUNA ek blok yazilir.
  Mevcut hicbir sinif silinmez; sonradan tanimlanan ayni sinif
  CSS cascade ile mevcut degeri override eder (specificity esit).

EKLENEN / OVERRIDE EDILEN ALANLAR:
  1) Detay KPI kartlari padding ve hover ferahligi
  2) Detay KPI sapma karti (5. kart) icin font-size buyutme + bold
  3) Tip kartlarinda yeni 3 satirli icerik icin sinif tanimlari
     - .cps-ith-tip-kart-satir   → label + deger (flex)
     - .cps-ith-tip-kart-label   → gri label
     - .cps-ith-tip-kart-deger-mini → koyu deger
     - .cps-ith-tip-kart-ayrac   → dashed ayrac
  4) Tip kart genel padding: 10/12px → 16/18px (ferah)
  5) Yeni renk siniflari: sapma-pozitif (kirmizi=asim), sapma-negatif (yesil=tasarruf)
     - Var. B: pozitif = asim = kirmizi, negatif = tasarruf = yesil
  6) Patch B'de eklenen rozet siniflarinin gorsel tuningi (pill standardi)
     - uppercase, letter-spacing, padding, weight 600
  7) Tablo durum rozetleri tutarlilik (zaten var olan satir siniflarina
     ek olarak rozet element'inin standart pill gorunumu)

DOKUNULMAYAN:
  - Mevcut sinif tanimlari (silinmiyor)
  - HTML layout
  - JS / backend / DB

KURALLAR:
  - Yedek alinir (tarih damgali)
  - Idempotent: basligi bulursa tekrar eklemez
  - Atomik yazma: .tmp -> os.replace
  - Boyut sanity (300-6000 byte)

NASIL CALISTIRILIR:
  cd C:\\cps_dev
  python patch_estetik_c1.py
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
# BASLIK (idempotency anahtari)
# =============================================================
BASLIK = '/* === ESTETIK PATCH C1 v1 — KPI/tip kart ferahlik + sapma rengi === */'
SON_ISARET = '/* === ESTETIK PATCH C1 v1 — son === */'

# =============================================================
# EKLENECEK BLOK
# =============================================================
EKLENECEK_BLOK = '''

''' + BASLIK + '''
/* Amac:
     1) Tip kartlarinda 3 satirli yeni duzen icin yardimci siniflar
     2) Padding/boslukta ferahlik
     3) Sapma rengi semantigi (Var.B): + asim KIRMIZI, - tasarruf YESIL
     4) Patch B'de eklenen rozetlere modern pill gorunumu
     5) KPI sapma karti font buyutme

   Renk paleti mevcut paletle uyumlu:
     - Yesil (tasarruf):   #d1fae5 / #10b981 / #065f46
     - Kirmizi (asim):     #fee2e2 / #ef4444 / #991b1b
     - Mavi (yeni):        #dbeafe / #60a5fa / #1e40af
     - Sari (bekliyor):    #fef3c7 / #f59e0b / #92400e
     - Gri:                #f3f4f6 / #6b7280 / #374151
   ----------------------------------------------------------------- */


/* ===== DETAY KPI — sapma karti font buyutme ===== */
/* 5 KPI kartinin sonuncusu (SAPMA) — gorsel agirlik vermek icin */
.cps-ith-detay-kpi .cps-ith-kpi-kart:last-child .cps-ith-kpi-deger {
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.01em;
}


/* ===== TIP KART — ferah padding ===== */
.cps-ith-tip-kart {
  padding: 16px 18px;        /* eski: 10px 12px */
  border-radius: 8px;        /* eski: 6px */
}
.cps-ith-tip-kart-ad {
  margin-bottom: 12px;       /* eski: 6px — rozet sonrasi nefes */
  font-size: 12px;           /* eski: 11px */
}


/* ===== TIP KART — yeni 3 satirli duzen icin yardimci siniflar ===== */
.cps-ith-tip-kart-ayrac {
  height: 1px;
  background: transparent;
  border-top: 1px dashed #e5e7eb;
  margin: 10px 0;
}
.cps-ith-tip-kart-satir {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 10px;
  margin-top: 4px;
  margin-bottom: 4px;
  line-height: 1.4;
}
.cps-ith-tip-kart-label {
  font-size: 12px;
  color: #6b7280;
  font-weight: 500;
  white-space: nowrap;
}
.cps-ith-tip-kart-deger-mini {
  font-size: 13px;
  font-weight: 600;
  color: #111827;
  font-variant-numeric: tabular-nums;
  text-align: right;
}


/* ===== SAPMA RENGI — Var.B (negatif=tasarruf=YESIL, pozitif=asim=KIRMIZI) ===== */
/*
   Bu siniflar mevcut .cps-ith-sapma-uyari ve .cps-ith-sapma-kritik
   ile birlikte calisir. Mevcut siniflar magnitude'e gore renk verir
   (>5% turuncu, >10% kirmizi). Bu yeni siniflar isarete (sign) gore
   net renk verir.
   JS'te ekleniyor: t.sapma_yuzde > 0 -> sapma-pozitif, < 0 -> sapma-negatif
*/
.cps-ith-sapma-pozitif {
  color: #991b1b;            /* asim - kirmizi */
}
.cps-ith-sapma-negatif {
  color: #065f46;            /* tasarruf - yesil */
}
/* Tip kart icindeki sapma satiri kontekstinde daha guclu vurgu */
.cps-ith-tip-kart .cps-ith-tip-kart-deger-mini.cps-ith-sapma-pozitif {
  color: #b91c1c;
  font-weight: 700;
}
.cps-ith-tip-kart .cps-ith-tip-kart-deger-mini.cps-ith-sapma-negatif {
  color: #047857;
  font-weight: 700;
}


/* ===== TIP KART — TAHMINI_YOK gorunumu (Patch B'de tanimliydi, tuning) ===== */
.cps-ith-tip-kart.tahmini-yok {
  border-style: dashed;
  background: #eff6ff;
  border-color: #93c5fd;     /* Patch B: #bfdbfe -> biraz daha doygun */
}


/* ===== ROZET — modern pill standardi ===== */
/* Patch B'de eklenen .cps-ith-tip-kart-rozet base'ine ek tuning */
.cps-ith-tip-kart-rozet {
  padding: 3px 9px;          /* eski: 1px 6px - daha rahat */
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border-radius: 12px;       /* eski: 10px */
  line-height: 1.4;
  border: 1px solid transparent;
}
.cps-ith-tip-kart-rozet-bekliyor {
  background: #fef3c7;
  color: #92400e;
  border-color: #fde68a;
}
.cps-ith-tip-kart-rozet-yeni {
  background: #dbeafe;
  color: #1e40af;
  border-color: #bfdbfe;
}


/* ===== KPI alt metni — font netlik ===== */
.cps-ith-kpi-alt-bilgi {
  font-size: 11px;
  color: #6b7280;
  margin-top: 4px;            /* Patch A: 2px -> 4px nefes */
}
.cps-ith-kpi-alt-uyari {
  font-size: 11px;
  color: #b45309;             /* Patch A: #d97706 -> daha kontrasli */
  margin-top: 4px;
  font-weight: 600;           /* Patch A: 500 -> 600 */
}


/* ===== TABLO — sapma renk hucresi (Var.B) ===== */
/* Sapma yuzde kolonu — isarete gore renk (sapma_yuzde JS tarafindan
   sapma-pozitif/negatif class'i ile geliyor) */
.cps-ith-sapma-tablo td.sapma-yuzde-cell {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}


/* ===== TABLO — durum kolonu pill standartlasmasi ===== */
/* Sapma tablosunda DURUM kolonundaki rozetler icin tutarli pill gorunumu.
   JS halihazirda span class verecek; bu CSS ona modern gorunum saglar. */
.cps-ith-sapma-tablo .durum-pill {
  display: inline-block;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border-radius: 12px;
  white-space: nowrap;
  line-height: 1.4;
  border: 1px solid transparent;
}
.cps-ith-sapma-tablo .durum-pill-kritik {
  background: #fee2e2; color: #991b1b; border-color: #fecaca;
}
.cps-ith-sapma-tablo .durum-pill-uyari {
  background: #fef3c7; color: #92400e; border-color: #fde68a;
}
.cps-ith-sapma-tablo .durum-pill-bekliyor {
  background: #f3f4f6; color: #4b5563; border-color: #e5e7eb;
}
.cps-ith-sapma-tablo .durum-pill-yeni {
  background: #dbeafe; color: #1e40af; border-color: #bfdbfe;
}
.cps-ith-sapma-tablo .durum-pill-mix {
  background: #fef3c7; color: #92400e; border-color: #fde68a;
}


/* ===== TABLO — hucre yaninda kucuk info ikonu (karisik para) ===== */
.cps-ith-tablo-info-ikon {
  display: inline-block;
  margin-left: 4px;
  color: #d97706;
  font-size: 11px;
  cursor: help;
  vertical-align: baseline;
}


/* ===== KART GAP — KPI ve tip kartlari arasi nefes ===== */
.cps-ith-kpi-grid {
  /* Eger varsa - mevcut grid gap'i artir */
  gap: 14px;                 /* eski: muhtemelen 10-12px */
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
    yaz('  CPS DEV — Patch C1: Estetik iyilestirme CSS')
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

    # --- 3) Idempotency kontrolu ---
    if BASLIK in mevcut:
        cik(0, '\nBILGI: C1 patch basligi dosyada zaten mevcut.\n'
               '  Patch daha once uygulanmis — yeniden uygulama yapilmadi.')

    # --- 4) Yedek al ---
    damga = datetime.now().strftime('%Y%m%d_%H%M%S')
    yedek_yol = f'{HEDEF}.yedek_{damga}'
    try:
        shutil.copy2(HEDEF, yedek_yol)
    except Exception as e:
        cik(3, f'HATA: Yedek alinamadi: {e}\n  Patch uygulanmadi.')

    yaz(f'Yedek  : {yedek_yol}')

    # --- 5) Yeni icerigi hazirla ---
    yeni_icerik = mevcut + EKLENECEK_BLOK

    if not yeni_icerik.startswith(mevcut):
        cik(4, 'HATA: Yeni icerik eski icerigi icermiyor.\n  Patch iptal.')

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
        cik(6, f'HATA: Gecici dosya yazilamadi: {e}')

    # --- 7) Boyut sanity ---
    yeni_boyut = os.path.getsize(tmp_yol)
    fark = yeni_boyut - ilk_boyut
    yaz(f'Eklenen: {fark} byte (yeni toplam: {yeni_boyut})')

    if fark < 300 or fark > 8000:
        try:
            os.remove(tmp_yol)
        except Exception:
            pass
        cik(7, f'HATA: Boyut farki beklenen araligin disinda: +{fark} byte.\n'
               '  Beklenen 300-8000 byte. Patch iptal.')

    # --- 8) Atomik rename ---
    try:
        os.replace(tmp_yol, HEDEF)
    except Exception as e:
        try:
            if os.path.isfile(tmp_yol):
                os.remove(tmp_yol)
        except Exception:
            pass
        cik(8, f'HATA: Dosya guncellenemedi: {e}\n  Yedek duruyor.')

    # --- 9) Son dogrulama ---
    try:
        with open(HEDEF, 'r', encoding='utf-8') as f:
            son = f.read()
    except Exception as e:
        cik(9, f'UYARI: Patch yazildi ama dogrulama icin okunamadi: {e}\n'
               f'  Yedek: {yedek_yol}')

    if BASLIK not in son or SON_ISARET not in son:
        cik(10, 'UYARI: Dosya yazildi ama baslik/son isareti bulunamadi.\n'
                f'  Yedegi kontrol et: {yedek_yol}')

    # --- BASARILI ---
    yaz('')
    yaz('=' * 60)
    yaz('  PATCH C1 BASARIYLA UYGULANDI')
    yaz('=' * 60)
    yaz(f'Dosya  : {HEDEF}')
    yaz(f'Yedek  : {yedek_yol}')
    yaz('')
    yaz('Eklenen alanlar:')
    yaz('  - Tip kart padding: 10/12px -> 16/18px (ferah)')
    yaz('  - Tip kart 3 satirli duzen icin yardimci siniflar')
    yaz('  - Sapma rengi (Var.B): pozitif KIRMIZI / negatif YESIL')
    yaz('  - Rozet pill standartlasmasi (uppercase, letter-spacing)')
    yaz('  - KPI alt metin renk netlik')
    yaz('  - Tablo durum pill siniflari (.durum-pill-*)')
    yaz('  - Tablo info ikon stili')
    yaz('  - Detay KPI sapma karti font 24px bold')
    yaz('')
    yaz('GORSEL ETKI BU PATCH SONRASI:')
    yaz('  - Tip kartlari biraz daha ferah (padding artisi)')
    yaz('  - Rozetler biraz daha buyuk/okunur')
    yaz('  - SAPMA KPI degeri 24px bold (eskiden 20px)')
    yaz('  - Diger seyler aynen kalir (JS henuz yeni siniflari kullanmiyor)')
    yaz('')
    yaz('Test:')
    yaz('  - Ctrl+Shift+Delete -> Onbellek temizle')
    yaz('  - Ctrl+F5 hard refresh')
    yaz('  - ITH-DEMO-001 sayfasi: layout bozuldu mu? (BOZULMAMALI)')
    yaz('  - Sapma KPI biraz buyumus, tip kartlari ferah olmali')
    yaz('  - Konsol: kirmizi hata? (OLMAMALI)')
    yaz('')
    yaz('Geri alma:')
    yaz(f'  copy "{yedek_yol}" "{HEDEF}"')
    yaz('')


if __name__ == '__main__':
    main()
