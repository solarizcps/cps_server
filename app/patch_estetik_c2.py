# -*- coding: utf-8 -*-
"""
CPS DEV — Patch C2: Tip Kart 3 Satirli Duzen (JS)
==================================================

KAPSAM:
  static/js/cps_ithalat_detay.js icindeki maliyetModul.tipOzetDoldur
  fonksiyonu yeniden duzenlenir. Tek buyuk sayi yerine 3 satirli
  yapi gelir:

  - Satir 1: "Plan:    XX,XX USD"     (tahmini)
  - Satir 2: "Gercek:  XX,XX USD"     (gerceklesen)
  - Ayrac (hafif dashed)
  - Satir 3: "Sapma:   ±X.X%"        (Var.B renkli: + kirmizi, - yesil)

KULLANICI ISTEKLERI:
  1. "Tahmini" -> "Plan", "Gerceklesen" -> "Gercek" (kisa)
  2. Ayraclar hafif/sade (acik gri border)

KORUNAN:
  - Kart class'lari (bekliyor, tahmini-yok, sapma-kritik, sapma-uyari)
  - Rozet sistemi (Patch B'den - aynen calisir)
  - Tip adi (TIP_ETIKET)
  - Mevcut layout, min-height, padding (Patch C1 v2 sonrasi)

DEGISTIRILEN:
  - Eski "buyuk tek sayi" + "tek alt metin" yapisi -> 3 satirli yapi
  - paraFmt cagrilari (tahmini, gerceklesen, sapma ayri ayri)

GUVENLIK:
  - Yedek alinir (tarih damgali)
  - Idempotent: yeni blok markeri "C2-3SATIR-V1" varsa tekrar uygulanmaz
  - Eski blok bulunamazsa HICBIR degisiklik yapilmaz (orijinal korunur)
  - Atomik yazma: .tmp -> os.replace
  - Boyut sanity (artis 800-3000 byte bekleniyor)
  - Brace/paren denge kontrolu (degismemeli)

NASIL CALISTIRILIR:
  cd C:\\cps_dev
  python patch_estetik_c2.py
"""

import os
import sys
import shutil
from datetime import datetime

# =============================================================
# HEDEF
# =============================================================
HEDEF = os.path.join('static', 'js', 'cps_ithalat_detay.js')

# =============================================================
# ESKI BLOK — Patch B sonrasi tipOzetDoldur'un TAM HALI
# =============================================================
BLOK_ESKI = '''    tipOzetDoldur: function (d) {
      var tipOzet = $('cps-ith-tip-ozet');
      if (!tipOzet || !d.tip_detay) return;
      tipOzet.innerHTML = '';
      d.tip_detay.forEach(function (t) {
        var kart = document.createElement('div');
        kart.className = 'cps-ith-tip-kart';
        // Eski 'bekliyor' flag'i hala calisir (backward compatible)
        if (t.bekliyor) kart.classList.add('bekliyor');
        // Patch B: yeni 'sinif' alani varsa TAHMINI_YOK icin mavi arka plan
        if (t.sinif === 'TAHMINI_YOK') kart.classList.add('tahmini-yok');
        if (t.sapma_yuzde != null) {
          var abs = Math.abs(t.sapma_yuzde);
          if (abs > 10)      kart.classList.add('sapma-kritik');
          else if (abs > 5)  kart.classList.add('sapma-uyari');
        }
        var ad = document.createElement('div');
        ad.className = 'cps-ith-tip-kart-ad';
        ad.textContent = TIP_ETIKET[t.tip] || t.tip;
        // Patch B: sinif'a gore rozet ekle (BEKLIYOR / TAHMINI_YOK)
        if (t.sinif === 'BEKLIYOR') {
          var _r = document.createElement('span');
          _r.className = 'cps-ith-tip-kart-rozet cps-ith-tip-kart-rozet-bekliyor';
          _r.textContent = '⏳ BEKLIYOR';
          ad.appendChild(_r);
        } else if (t.sinif === 'TAHMINI_YOK') {
          var _r2 = document.createElement('span');
          _r2.className = 'cps-ith-tip-kart-rozet cps-ith-tip-kart-rozet-yeni';
          _r2.textContent = '🆕 YENI';
          ad.appendChild(_r2);
        }
        kart.appendChild(ad);
        var deger = document.createElement('div');
        deger.className = 'cps-ith-tip-kart-deger';
        deger.textContent = paraFmt(t.etkin, d.para_birimi);
        kart.appendChild(deger);
        var alt = document.createElement('div');
        alt.className = 'cps-ith-tip-kart-alt';
        if (t.bekliyor)
          alt.textContent = 'Gerceklesen bekliyor · T: ' + paraFmt(t.tahmini);
        else if (t.sapma_yuzde != null && t.sapma_yuzde !== 0)
          alt.textContent = 'Sapma ' + yuzdeFmt(t.sapma_yuzde);
        else
          alt.textContent = 'T: ' + paraFmt(t.tahmini) + ' · G: ' + paraFmt(t.gerceklesen);
        kart.appendChild(alt);
        tipOzet.appendChild(kart);
      });
    },'''

# =============================================================
# YENI BLOK — Patch C2: 3 satirli yapi
# =============================================================
BLOK_YENI = '''    tipOzetDoldur: function (d) {
      // C2-3SATIR-V1: Tip karti 3 satirli yeni duzen.
      // Plan / Gercek / Sapma satirlari + hafif ayraclar.
      // Var.B sapma rengi: pozitif (asim) kirmizi, negatif (tasarruf) yesil.
      var tipOzet = $('cps-ith-tip-ozet');
      if (!tipOzet || !d.tip_detay) return;
      tipOzet.innerHTML = '';

      // Yardimci: sayi yoksa em-dash, varsa formatli para
      function _paraVeyaTire(tutar, para) {
        if (tutar == null || tutar === 0) return '—';
        return paraFmt(tutar, para);
      }

      d.tip_detay.forEach(function (t) {
        var kart = document.createElement('div');
        kart.className = 'cps-ith-tip-kart';
        // Geriye uyumlu: eski 'bekliyor' flag'i
        if (t.bekliyor) kart.classList.add('bekliyor');
        // Patch B: TAHMINI_YOK mavi dashed
        if (t.sinif === 'TAHMINI_YOK') kart.classList.add('tahmini-yok');
        if (t.sapma_yuzde != null) {
          var abs = Math.abs(t.sapma_yuzde);
          if (abs > 10)      kart.classList.add('sapma-kritik');
          else if (abs > 5)  kart.classList.add('sapma-uyari');
        }

        // ---- AD + ROZET (Patch B davranisi aynen) ----
        var ad = document.createElement('div');
        ad.className = 'cps-ith-tip-kart-ad';
        ad.textContent = TIP_ETIKET[t.tip] || t.tip;
        if (t.sinif === 'BEKLIYOR') {
          var _r = document.createElement('span');
          _r.className = 'cps-ith-tip-kart-rozet cps-ith-tip-kart-rozet-bekliyor';
          _r.textContent = '⏳ BEKLIYOR';
          ad.appendChild(_r);
        } else if (t.sinif === 'TAHMINI_YOK') {
          var _r2 = document.createElement('span');
          _r2.className = 'cps-ith-tip-kart-rozet cps-ith-tip-kart-rozet-yeni';
          _r2.textContent = '🆕 YENI';
          ad.appendChild(_r2);
        }
        kart.appendChild(ad);

        // ---- USTTEKI HAFIF AYRAC ----
        var ayrac1 = document.createElement('div');
        ayrac1.className = 'cps-ith-tip-kart-ayrac';
        kart.appendChild(ayrac1);

        // ---- SATIR 1: PLAN (tahmini) ----
        var planSatir = document.createElement('div');
        planSatir.className = 'cps-ith-tip-kart-satir';
        var planLbl = document.createElement('span');
        planLbl.className = 'cps-ith-tip-kart-label';
        planLbl.textContent = 'Plan:';
        var planVal = document.createElement('span');
        planVal.className = 'cps-ith-tip-kart-deger-mini';
        planVal.textContent = _paraVeyaTire(t.tahmini, d.para_birimi);
        planSatir.appendChild(planLbl);
        planSatir.appendChild(planVal);
        kart.appendChild(planSatir);

        // ---- SATIR 2: GERCEK (gerceklesen) ----
        var gerSatir = document.createElement('div');
        gerSatir.className = 'cps-ith-tip-kart-satir';
        var gerLbl = document.createElement('span');
        gerLbl.className = 'cps-ith-tip-kart-label';
        gerLbl.textContent = 'Gercek:';
        var gerVal = document.createElement('span');
        gerVal.className = 'cps-ith-tip-kart-deger-mini';
        gerVal.textContent = _paraVeyaTire(t.gerceklesen, d.para_birimi);
        gerSatir.appendChild(gerLbl);
        gerSatir.appendChild(gerVal);
        kart.appendChild(gerSatir);

        // ---- ALTTAKI HAFIF AYRAC ----
        var ayrac2 = document.createElement('div');
        ayrac2.className = 'cps-ith-tip-kart-ayrac';
        kart.appendChild(ayrac2);

        // ---- SATIR 3: SAPMA (Var.B renkli) ----
        var sapSatir = document.createElement('div');
        sapSatir.className = 'cps-ith-tip-kart-satir';
        var sapLbl = document.createElement('span');
        sapLbl.className = 'cps-ith-tip-kart-label';
        sapLbl.textContent = 'Sapma:';
        var sapVal = document.createElement('span');
        sapVal.className = 'cps-ith-tip-kart-deger-mini';
        if (t.sapma_yuzde == null) {
          sapVal.textContent = '—';
        } else {
          sapVal.textContent = yuzdeFmt(t.sapma_yuzde);
          // Var.B: pozitif=asim=kirmizi, negatif=tasarruf=yesil
          if (t.sapma_yuzde > 0) {
            sapVal.classList.add('cps-ith-sapma-pozitif');
          } else if (t.sapma_yuzde < 0) {
            sapVal.classList.add('cps-ith-sapma-negatif');
          }
        }
        sapSatir.appendChild(sapLbl);
        sapSatir.appendChild(sapVal);
        kart.appendChild(sapSatir);

        tipOzet.appendChild(kart);
      });
    },'''


# =============================================================
# YARDIMCILAR
# =============================================================
def yaz(msg):
    sys.stdout.write(msg + '\n')
    sys.stdout.flush()


def cik(code, msg):
    yaz(msg)
    sys.exit(code)


def naive_balance(metin):
    """Kaba denge: string/regex/comment icindekileri de sayar.
       Sadece bilgi amacli + degisiklik sonrasi degismemesi kontrolu."""
    return {
        'brace':   metin.count('{') - metin.count('}'),
        'paren':   metin.count('(') - metin.count(')'),
        'bracket': metin.count('[') - metin.count(']'),
    }


# =============================================================
# ANA
# =============================================================
def main():
    yaz('')
    yaz('=' * 60)
    yaz('  CPS DEV — Patch C2: Tip kart 3 satirli duzen (JS)')
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
    ilk_satir = mevcut.count('\n')
    yaz(f'Boyut  : {ilk_boyut} byte · {ilk_satir} satir')

    # Bilgi: kaba denge
    ilk_balance = naive_balance(mevcut)
    anomali = [f'{k}={v}' for k, v in ilk_balance.items() if v != 0]
    if anomali:
        yaz(f'Bilgi  : Kaba denge anomalisi (string/regex icinde olabilir): '
            f'{", ".join(anomali)}')
        yaz('         (Tam-eslesme replace kullaniliyor — tolere edilir)')

    # --- 3) Idempotency: yeni blok marker'i var mi? ---
    if 'C2-3SATIR-V1' in mevcut:
        cik(0, '\nBILGI: C2 patch marker dosyada zaten mevcut.\n'
               '  Patch daha once uygulanmis - yeniden uygulama yapilmadi.')

    # --- 4) Eski blok var mi? ---
    eski_sayi = mevcut.count(BLOK_ESKI)
    yaz(f'\nEski blok eslesmesi: {eski_sayi}x  (beklenen: 1)')

    if eski_sayi == 0:
        cik(3, 'HATA: Patch B sonrasi tipOzetDoldur fonksiyonu bulunamadi.\n'
               '  Olasi sebepler:\n'
               '    a) Patch B uygulanmamis (önce onu uygula)\n'
               '    b) Dosya manuel duzenlenmis\n'
               '    c) Farkli bir versiyondasin\n'
               '  Hicbir degisiklik yapilmadi.')
    if eski_sayi > 1:
        cik(4, f'HATA: Eski blok {eski_sayi} kez geciyor (beklenen 1).\n'
               '  Guvenlik icin patch iptal.')

    # --- 5) Yedek al ---
    damga = datetime.now().strftime('%Y%m%d_%H%M%S')
    yedek_yol = f'{HEDEF}.yedek_C2_{damga}'
    try:
        shutil.copy2(HEDEF, yedek_yol)
    except Exception as e:
        cik(5, f'HATA: Yedek alinamadi: {e}\n  Patch uygulanmadi.')

    yaz(f'Yedek  : {yedek_yol}')

    # --- 6) Replace ---
    yeni_icerik = mevcut.replace(BLOK_ESKI, BLOK_YENI, 1)

    if yeni_icerik == mevcut:
        cik(6, 'HATA: Replace sonrasi icerik aynen kaldi (beklenmedik).\n'
               '  Patch iptal.')

    # --- 7) Sanity: yeni blok icerikte var mi? ---
    if 'C2-3SATIR-V1' not in yeni_icerik:
        cik(7, 'HATA: Yeni blok marker yeni icerikte bulunamadi.\n'
               '  Patch iptal.')

    # --- 8) Balance degismedi mi? ---
    yeni_balance = naive_balance(yeni_icerik)
    if yeni_balance != ilk_balance:
        cik(8, f'HATA: Patch sonrasi denge DEGISTI (olmamali).\n'
               f'  Oncesi : {ilk_balance}\n'
               f'  Sonrasi: {yeni_balance}\n'
               '  Patch iptal.')

    # --- 9) Gecici dosyaya yaz ---
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
        cik(9, f'HATA: Gecici dosya yazilamadi: {e}')

    # --- 10) Boyut sanity ---
    yeni_boyut = os.path.getsize(tmp_yol)
    fark = yeni_boyut - ilk_boyut
    yaz(f'Boyut farki: +{fark} byte (yeni toplam: {yeni_boyut})')

    if fark < 500 or fark > 5000:
        try:
            os.remove(tmp_yol)
        except Exception:
            pass
        cik(10, f'HATA: Boyut farki beklenen disinda: +{fark} byte.\n'
                '  Beklenen 500-5000 byte. Patch iptal.')

    # --- 11) Atomik rename ---
    try:
        os.replace(tmp_yol, HEDEF)
    except Exception as e:
        try:
            if os.path.isfile(tmp_yol):
                os.remove(tmp_yol)
        except Exception:
            pass
        cik(11, f'HATA: Dosya guncellenemedi: {e}\n  Yedek duruyor.')

    # --- BASARILI ---
    yaz('')
    yaz('=' * 60)
    yaz('  PATCH C2 BASARIYLA UYGULANDI')
    yaz('=' * 60)
    yaz(f'Dosya  : {HEDEF}')
    yaz(f'Yedek  : {yedek_yol}')
    yaz('')
    yaz('Yeni davranis (tip kartlari):')
    yaz('  Eski: [TIP] [rozet] / Buyuk sayi / Tek alt metin')
    yaz('  Yeni: [TIP] [rozet]')
    yaz('        ----- (hafif ayrac)')
    yaz('        Plan:    XX,XX USD')
    yaz('        Gercek:  XX,XX USD')
    yaz('        ----- (hafif ayrac)')
    yaz('        Sapma:   ±X.X%   (Var.B: + kirmizi, - yesil)')
    yaz('')
    yaz('Korunan:')
    yaz('  - Rozetler (⏳ BEKLIYOR / 🆕 YENI)')
    yaz('  - Kart class\'lari (bekliyor, tahmini-yok, sapma-kritik/uyari)')
    yaz('  - Layout, min-height 120px, padding')
    yaz('')
    yaz('Test:')
    yaz('  1) Ctrl+Shift+Delete -> Onbellek temizle')
    yaz('  2) Ctrl+F5 hard refresh')
    yaz('  3) ITH-DEMO-001 -> Maliyet sekmesi:')
    yaz('     - 5 tip karti (FOB/GUMRUK/KOMISYON/NAVLUN/SIGORTA) 3 satirli')
    yaz('     - FOB sapmasi -23.5% YESIL (tasarruf)')
    yaz('     - NAVLUN sapmasi +118.6% KIRMIZI (asim)')
    yaz('     - GUMRUK/KOMISYON: Plan dolu, Gercek "—", Sapma "—"')
    yaz('  4) Layout BOZULDU mu? OLMAMALI')
    yaz('  5) Konsol kirmizi hata? OLMAMALI')
    yaz('')
    yaz('Geri alma:')
    yaz(f'  copy "{yedek_yol}" "{HEDEF}"')
    yaz('')


if __name__ == '__main__':
    main()
