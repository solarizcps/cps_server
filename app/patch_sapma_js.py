# -*- coding: utf-8 -*-
"""
CPS DEV — Patch B (v2): Sapma UI JS fonksiyon degisiklikleri
=============================================================

v2 NOTLARI (v1'den fark):
  - Baseline paren/brace balance kontrolu UYARIYA dusuruldu.
  - Sebep: Naif karakter sayimi, JS string/regex/comment icindeki
    parantezleri de sayar -> false positive verir.
  - Patch guvenligi korundu: str.replace tam eslesme + atomik yazma
    + boyut sanity + idempotent kontrol -> kismi bozulma imkansiz.

KAPSAM (v1 ile ayni):
  static/js/cps_ithalat_detay.js dosyasinda IKI BLOGU degistirir:

  BLOK 1 — detayModul.doldur() icinde SAPMA KPI (line ~319-330)
    - sapma_yuzde null ise "Karsilastirilabilir tip yok" alt metin
    - sapma_guvenilir false ise ⚠ uyari ikonu + tooltip
    - sapma_kapsam_metni gri alt metin
    - para_birimi_karisik true ise turuncu "Karisik para birimi" metni

  BLOK 2 — maliyetModul.tipOzetDoldur() (line ~521-553)
    - sinif === 'BEKLIYOR' → ⏳ BEKLIYOR rozeti
    - sinif === 'TAHMINI_YOK' → 🆕 YENI rozeti + mavi dashed kart
    - sinif === 'ESLESEN' → degisiklik yok (sade)
    - ESKI 'bekliyor' flag'i hala calisiyor (backward compatible)

NASIL CALISTIRILIR:
  cd C:\\cps_dev
  python patch_sapma_js.py
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
# BLOK 1 — SAPMA KPI (dolur fonksiyonu icinde)
# =============================================================
BLOK1_ESKI = '''    var sapmaEl = $('cps-ith-k-sapma');
    if (sapmaEl) {
      sapmaEl.className = 'cps-ith-kpi-deger';
      if (d.sapma_yuzde != null) {
        sapmaEl.textContent = yuzdeFmt(d.sapma_yuzde);
        var abs = Math.abs(d.sapma_yuzde);
        if (abs > 10) sapmaEl.classList.add('cps-ith-sapma-kritik');
        else if (abs > 5) sapmaEl.classList.add('cps-ith-sapma-uyari');
      } else {
        sapmaEl.textContent = '—';
      }
    }'''

BLOK1_YENI = '''    var sapmaEl = $('cps-ith-k-sapma');
    if (sapmaEl) {
      // Degeri sifirla (re-render guvenli)
      sapmaEl.className = 'cps-ith-kpi-deger';
      sapmaEl.innerHTML = '';

      if (d.sapma_yuzde != null) {
        sapmaEl.textContent = yuzdeFmt(d.sapma_yuzde);
        var abs = Math.abs(d.sapma_yuzde);
        if (abs > 10) sapmaEl.classList.add('cps-ith-sapma-kritik');
        else if (abs > 5) sapmaEl.classList.add('cps-ith-sapma-uyari');

        // Patch B: sapma_guvenilir === false ise uyari ikonu ekle
        if (d.sapma_guvenilir === false) {
          var _ikon = document.createElement('span');
          _ikon.className = 'cps-ith-kpi-sapma-ikon';
          _ikon.textContent = '⚠';
          _ikon.title = 'Karisik para birimi veya kur eksikligi — dikkatli yorumlayin';
          sapmaEl.appendChild(_ikon);
        }
      } else {
        sapmaEl.textContent = '—';
      }

      // Patch B: SAPMA kartinin altina mini bilgi/uyari metni
      var _kart = sapmaEl.closest ? sapmaEl.closest('.cps-ith-kpi-kart') : null;
      if (_kart) {
        // Onceki patch alt metnini temizle (re-render guvenli)
        var _eski = _kart.querySelector('[data-sapma-patch="1"]');
        if (_eski) _eski.parentNode.removeChild(_eski);

        var _altMetin = null;
        var _altCls = null;
        if (d.sapma_yuzde == null) {
          _altMetin = 'Karsilastirilabilir tip yok';
          _altCls = 'cps-ith-kpi-alt-bilgi';
        } else if (d.para_birimi_karisik === true) {
          _altMetin = 'Karisik para birimi';
          _altCls = 'cps-ith-kpi-alt-uyari';
        } else if (d.sapma_kapsam_metni) {
          _altMetin = d.sapma_kapsam_metni;
          _altCls = 'cps-ith-kpi-alt-bilgi';
        }

        if (_altMetin) {
          var _altEl = document.createElement('div');
          _altEl.className = _altCls;
          _altEl.textContent = _altMetin;
          _altEl.setAttribute('data-sapma-patch', '1');
          _kart.appendChild(_altEl);
        }
      }
    }'''


# =============================================================
# BLOK 2 — tipOzetDoldur (maliyetModul icinde)
# =============================================================
BLOK2_ESKI = '''    tipOzetDoldur: function (d) {
      var tipOzet = $('cps-ith-tip-ozet');
      if (!tipOzet || !d.tip_detay) return;
      tipOzet.innerHTML = '';
      d.tip_detay.forEach(function (t) {
        var kart = document.createElement('div');
        kart.className = 'cps-ith-tip-kart';
        if (t.bekliyor) kart.classList.add('bekliyor');
        if (t.sapma_yuzde != null) {
          var abs = Math.abs(t.sapma_yuzde);
          if (abs > 10)      kart.classList.add('sapma-kritik');
          else if (abs > 5)  kart.classList.add('sapma-uyari');
        }
        var ad = document.createElement('div');
        ad.className = 'cps-ith-tip-kart-ad';
        ad.textContent = TIP_ETIKET[t.tip] || t.tip;
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

BLOK2_YENI = '''    tipOzetDoldur: function (d) {
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
# YARDIMCILAR
# =============================================================
def yaz(msg):
    sys.stdout.write(msg + '\n')
    sys.stdout.flush()


def cik(code, msg):
    yaz(msg)
    sys.exit(code)


def naive_balance(metin):
    """Kaba denge sayimi — string/regex/comment icindekileri de sayar.
       Sadece BILGI amacli, patch kararini etkilemez.
    """
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
    yaz('  CPS DEV — Patch B (v2): Sapma UI JS degisiklikleri')
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
    ilk_satir = mevcut.count('\n')
    yaz(f'Boyut  : {ilk_boyut} byte · {ilk_satir} satir')

    # v2: Balance bilgi amacli gosterilir, patch'i durdurmaz
    ilk_balance = naive_balance(mevcut)
    anomali = [f'{k}={v}' for k, v in ilk_balance.items() if v != 0]
    if anomali:
        yaz(f'Bilgi  : Kaba denge anomalisi (string/regex icinde olabilir): '
            f'{", ".join(anomali)}')
        yaz(f'         (Patch bu durumu TOLERE EDER — tam-eslesme replace kullaniliyor)')

    # --- 3) Her iki blok icin durum tespit ---
    blok1_eski_var = BLOK1_ESKI in mevcut
    blok1_yeni_var = BLOK1_YENI in mevcut
    blok2_eski_var = BLOK2_ESKI in mevcut
    blok2_yeni_var = BLOK2_YENI in mevcut

    blok1_eski_sayi = mevcut.count(BLOK1_ESKI)
    blok2_eski_sayi = mevcut.count(BLOK2_ESKI)

    yaz('')
    yaz('Durum tespit:')
    yaz(f'  Blok 1 (SAPMA KPI):    eski_var={blok1_eski_var} ({blok1_eski_sayi}x)  yeni_var={blok1_yeni_var}')
    yaz(f'  Blok 2 (tipOzet):      eski_var={blok2_eski_var} ({blok2_eski_sayi}x)  yeni_var={blok2_yeni_var}')

    # Idempotency: ikisi de zaten uygulanmis mi?
    if blok1_yeni_var and blok2_yeni_var and not blok1_eski_var and not blok2_eski_var:
        cik(0, '\nBILGI: Her iki blok da zaten uygulanmis.\n'
               '  Patch B daha once basariyla calismis — yeniden uygulama yapilmadi.')

    # Coklu eslesme varsa guvenlik icin dur
    if blok1_eski_sayi > 1:
        cik(3, f'HATA: Blok 1 eski versiyonu dosyada {blok1_eski_sayi} kez geciyor '
               '(beklenen 1).\n  Patch iptal, dosyayi manuel incele.')
    if blok2_eski_sayi > 1:
        cik(4, f'HATA: Blok 2 eski versiyonu dosyada {blok2_eski_sayi} kez geciyor '
               '(beklenen 1).\n  Patch iptal, dosyayi manuel incele.')

    # Hic blok bulunamadiysa → dosya farkli versiyon
    if not blok1_eski_var and not blok1_yeni_var:
        cik(5, 'HATA: Blok 1 (SAPMA KPI) dosyada bulunamadi — ne eski ne yeni hali.\n'
               '  Dosya farkli versiyonda olabilir, patch iptal.')
    if not blok2_eski_var and not blok2_yeni_var:
        cik(6, 'HATA: Blok 2 (tipOzetDoldur) dosyada bulunamadi — ne eski ne yeni hali.\n'
               '  Dosya farkli versiyonda olabilir, patch iptal.')

    # --- 4) Yedek al ---
    damga = datetime.now().strftime('%Y%m%d_%H%M%S')
    yedek_yol = f'{HEDEF}.yedek_{damga}'
    try:
        shutil.copy2(HEDEF, yedek_yol)
    except Exception as e:
        cik(7, f'HATA: Yedek alinamadi: {e}\n  Patch uygulanmadi.')

    yaz(f'\nYedek  : {yedek_yol}')

    # --- 5) Bloklari degistir ---
    yeni_icerik = mevcut
    blok1_uygulandi = False
    blok2_uygulandi = False

    if blok1_eski_var:
        yeni_icerik = yeni_icerik.replace(BLOK1_ESKI, BLOK1_YENI, 1)
        blok1_uygulandi = True
        yaz('  [+] Blok 1 degistirildi (SAPMA KPI)')
    else:
        yaz('  [=] Blok 1 atlandi (zaten yeni versiyon)')

    if blok2_eski_var:
        yeni_icerik = yeni_icerik.replace(BLOK2_ESKI, BLOK2_YENI, 1)
        blok2_uygulandi = True
        yaz('  [+] Blok 2 degistirildi (tipOzetDoldur)')
    else:
        yaz('  [=] Blok 2 atlandi (zaten yeni versiyon)')

    if not blok1_uygulandi and not blok2_uygulandi:
        try:
            os.remove(yedek_yol)
        except Exception:
            pass
        cik(0, '\nBILGI: Hicbir blok degistirilmedi (ikisi de zaten yeni hali).\n'
               '  Yedek dosyasi silindi.')

    # --- 6) Sanity: yeni bloklar icerikte var mi? ---
    if blok1_uygulandi and BLOK1_YENI not in yeni_icerik:
        cik(8, 'HATA: Blok 1 replace sonrasi yeni hali bulunamadi.\n'
               '  Patch iptal, orijinal dokunulmadi.')
    if blok2_uygulandi and BLOK2_YENI not in yeni_icerik:
        cik(9, 'HATA: Blok 2 replace sonrasi yeni hali bulunamadi.\n'
               '  Patch iptal, orijinal dokunulmadi.')

    # v2: Balance karsilastirma — patch oncesi ile sonrasi AYNI olmali
    yeni_balance = naive_balance(yeni_icerik)
    if yeni_balance != ilk_balance:
        # Bu ciddi bir iste gosterge — bloklar olculu olmadigi icin
        # balance degismemeli. Deger farkli ise bir sey ters gitmis demektir.
        try:
            os.remove(yedek_yol)
        except Exception:
            pass
        cik(10, f'HATA: Patch sonrasi denge DEGISTI (olmamali).\n'
                f'  Oncesi: {ilk_balance}\n'
                f'  Sonrasi: {yeni_balance}\n'
                f'  Bu bir degistirme hatasi isareti. Patch iptal.')

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
        cik(11, f'HATA: Gecici dosya yazilamadi: {e}\n'
                '  Orijinal dosya dokunulmadi.')

    yeni_boyut = os.path.getsize(tmp_yol)
    fark = yeni_boyut - ilk_boyut
    yaz(f'\nBoyut farki: +{fark} byte (yeni toplam: {yeni_boyut})')

    # Beklenen aralik: 500-6000 byte artis
    if fark < 100 or fark > 6000:
        try:
            os.remove(tmp_yol)
        except Exception:
            pass
        cik(12, f'HATA: Boyut farki beklenen araligin disinda: +{fark} byte.\n'
                '  Beklenen 100-6000 byte arasinda. Patch iptal.')

    # --- 8) Atomik rename ---
    try:
        os.replace(tmp_yol, HEDEF)
    except Exception as e:
        try:
            if os.path.isfile(tmp_yol):
                os.remove(tmp_yol)
        except Exception:
            pass
        cik(13, f'HATA: Dosya guncellenemedi (rename): {e}\n'
                '  Orijinal dosya dokunulmadi.')

    # --- BASARILI ---
    yaz('')
    yaz('=' * 60)
    yaz('  PATCH B BASARIYLA UYGULANDI')
    yaz('=' * 60)
    yaz(f'Dosya      : {HEDEF}')
    yaz(f'Yedek      : {yedek_yol}')
    yaz(f'Uygulanan  : '
        f'{"Blok 1 (SAPMA KPI) " if blok1_uygulandi else ""}'
        f'{"Blok 2 (tipOzet)" if blok2_uygulandi else ""}')
    yaz('')
    yaz('Test:')
    yaz('  1) Tarayicida Ctrl+Shift+Delete -> Onbellek temizle')
    yaz('  2) Ctrl+F5 hard refresh')
    yaz('  3) ITH-DEMO-001 detay sayfasini ac')
    yaz('  4) KONTROL:')
    yaz('     - Sapma yaninda ⚠ ikonu (karisik para)')
    yaz('     - Sapma altinda "Karisik para birimi" turuncu yazi')
    yaz('     - Tip kartlarinda ⏳ BEKLIYOR rozeti (GUMRUK, KOMISYON)')
    yaz('  5) ITH-2026-0004 detay sayfasini ac')
    yaz('     - Sapma "—" + "Karsilastirilabilir tip yok"')
    yaz('     - Tip kartlarinda 🆕 YENI rozeti (DEPOLAMA, DIGER, NAVLUN)')
    yaz('')
    yaz('Geri alma:')
    yaz(f'  copy "{yedek_yol}" "{HEDEF}"')
    yaz('')


if __name__ == '__main__':
    main()
