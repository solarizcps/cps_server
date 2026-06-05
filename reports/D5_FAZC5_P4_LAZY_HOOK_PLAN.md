# D5 FAZ C.5 P4 - LAZY HOOK PLAN (SADECE TASARIM)

**Tarih:** 18.05.2026 09:35
**Durum:** RECON tamam, PATCH YAPILMADI
**Onay durumu:** Adem'in ozel onayi bekleniyor

---

## 1. MEVCUT AKIS (RECON sonucu)

\\\
GET /personel-giris/prosesler/<int:emir_no>
  |
  v
ADIM 1: CPS-NATIVE OKU
  ccps = _cps_conn()
  cps_rows = SELECT FROM emir_alt_proses WHERE emir_no=? AND aktif=1
  |
  +-- CPS_ROWS VAR mi?
       |
       +-- EVET: result = list(cps_rows) + uretim_kayit toplam
       |        veri_kaynagi = 'CPS_NATIVE'
       |        return jsonify(result)  [LINE 410]
       |
       +-- HAYIR (cps bos):
            |
            v
            ADIM 2: 5055 SNAPSHOT FALLBACK
              c5055 = _5055_conn()
              c5055 NULL mu?
                EVET: legacy_warning + return []
                HAYIR: SELECT FROM emir_proses (5055 db)
                      result + uretim_kayit toplam
                      veri_kaynagi = 'LEGACY_5055_SNAPSHOT'
                      return jsonify(result)
\\\

## 2. HOOK EKLEME NOKTASI

CPS bos durumunda, **5055 fallback'inden ONCE**, lazy trigger denenmeli.

**Tam yer: L411 (ccps.close() sonrasi) ve L413 (5055 fallback baslangici) ARASINA.**

\\\python
# MEVCUT L408-413 (Reference):
            ccps.close()
            return jsonify(result)
        ccps.close()  # <-- L411

        # ============ ADIM 2: 5055 SNAPSHOT FALLBACK ============  <-- L413
        c5055 = _5055_conn()
\\\

**Yeni hook L411 ile L413 arasina eklenir.**

## 3. YENI AKIS (PATCH SONRASI - FLAG=True ICIN)

\\\
ADIM 1: CPS-NATIVE OKU
  |
  cps_rows VAR mi?
    EVET: return CPS_NATIVE  [DEGISMEZ]
    HAYIR: ccps.close()
      |
      v
      [YENI] ADIM 1.5: LAZY TRIGGER (FLAG=True iken)
        try:
          if USE_CPS_NATIVE_PROSES is True:  # Modul-level flag oku
            trigger_sonucu = lazy_trigger(emir_no)
            if trigger_sonucu basariliysa:
              ccps2 = _cps_conn()
              cps_rows2 = SELECT FROM emir_alt_proses WHERE emir_no=? AND aktif=1
              if cps_rows2:
                result = list(cps_rows2) + ...
                veri_kaynagi = 'CPS_NATIVE_TRIGGERED'  # yeni tag (opsiyonel)
                ccps2.close()
                return jsonify(result)
              ccps2.close()
        except Exception:
          # trigger basarisiz, fallback'e gec
          pass
      |
      v
      ADIM 2: 5055 SNAPSHOT FALLBACK  [DEGISMEZ]
\\\

## 4. FLAG=False IKEN DAVRANIS

**Garanti edilen davranis:**
- Hook bolgesi sadece if USE_CPS_NATIVE_PROSES is True iceriyor
- False ise hicbir trigger cagrisi yapilmaz, hicbir DB write olmaz
- Akis: CPS oku -> bos -> dogrudan 5055 fallback (eski davranis)
- Response birebir ayni
- Performans etkisi: 1 boolean kontrol (~mikrosaniye)
- DB etkisi: SIFIR
- Korgun etkisi: SIFIR

**Sonuc: FLAG=False ile davranis %100 birebir korunur.**

## 5. KORGUN TIMEOUT SENARYOSU

Trigger icin Korgun cagrisi gerekir (_eslesme_meta_from_emir cagrir get_emir_ozet).

**Risk:** Korgun timeout 30+ saniye olabilir, mobil saha kullanicisi bekler.

**Cozum:**
- Trigger cagrisi **try/except**'le sariliacak
- Timeout veya exception olursa **sessizce gecilir** (5055 fallback'e geciler)
- Trigger asla ana akisi bloke etmez
- Saha kullanicisi sadece "bos liste" gorur (sonra refresh ile cozulur)

**Daha agresif cozum (opsiyonel):**
- Trigger cagrisini ayri thread'de yap (fire-and-forget)
- Ana akis 5055'e dusup hemen response don
- Bir sonraki cagrida CPS dolu olur
- DEZAVANTAJ: Implementation karmasik, race riski

**Onerim:** Basit try/except + sync trigger. Korgun normalde 1-2sn yanit verir.

## 6. TRIGGER HATA SENARYOSU

Trigger icindeki olasi hatalar:
- Korgun veri yok (emir Korgun'da yok) -> meta=None -> hook'tan cikilir, 5055 fallback
- Eslesme yok (sablon_eslesme kuraltarila eslesmeyen emir) -> hook'tan cikilir
- _sablon_uygula_internal exception -> try/except'le yakalanir
- INSERT race condition (paralel iki cagri) -> 2. cagri zaten_islenmis donerse hook'tan cikilir

**Garanti:** Trigger hata verirse fallback DEVAM EDER. 5055 fallback hala calisir. Saha kullanicisi sonucu gorur.

## 7. RACE / DUPLICATE RISKI

**Senaryo:** Iki saha personeli ayni emir icin ayni anda /prosesler/<emir_no> cagrir. Ikisi de CPS bos gorur, ikisi de trigger calistirmaya baslar.

**Korunma:** _sablon_uygula_internal icindeki SELECT/INSERT pattern.
- 1. trigger INSERT yapar (uniq emir+proses_adi+aktif=1 kontrolu)
- 2. trigger ayni emire icin tekrar SELECT yapar, kayitlari gorur, atlanan listesine ekler
- Sonuc: 2. trigger duplicate insert YAPMAZ
- AMA: SELECT/INSERT arasinda race window var (~milisaniye)

**Daha guvenli:** BEGIN IMMEDIATE TRANSACTION ekle. Su an mevcut /sablon/uygula bunu yapmiyor (mevcut davranis).

**Onerim:** Su an yeterli. Race window cok kucuk, saha pratik olarak bunu tetiklemez. Gerekirse ileride iyilestirilebilir.

## 8. IMPORT GEREKSINIMI

personel_giris/routes.py icine eklenmeli:

\\\python
# Lazy hook icin (P4)
# Modul-level flag zaten var (L78): USE_CPS_NATIVE_PROSES = False
# Trigger fonksiyonu hedef modulden import edilecek
from modules.hedef.routes import (
    _eslesme_meta_from_emir,
    _eslesme_bul,
    _sablon_uygula_internal,
)
\\\

**Risk:** Circular import? hedef modulu personel_giris'i import etmiyor, sadece tek yonlu. Guvenli.

**Alternatif:** Import lazy yapilir (fonksiyon icinde). Daha az risk ama her cagride kucuk overhead.

## 9. CONFIG FLAG OKUMA STRATEJISI

**Iki secenek:**

**A) Modul-level constant (L78 mevcut):**
\\\python
USE_CPS_NATIVE_PROSES = False  # Mevcut
\\\
- Avantaj: Hizli, basit
- Dezavantaj: Degisiklik icin kod degisikligi gerekir, restart sart

**B) Flask config (P6 eklendi):**
\\\python
from flask import current_app
flag = current_app.config.get('USE_CPS_NATIVE_PROSES', False)
\\\
- Avantaj: Runtime degistirilebilir (env var, dashboard, vb)
- Dezavantaj: Her cagride config lookup

**Onerim:** **B (Flask config)** secelim. Onceden eklemistik P6'da. Modul L78 yorum olarak kalir, kodu (B) ile sarilir. Adem kontrolu daha kolay.

## 10. PATCH GEREKSINIMI

**Patch yeri:** app/modules/personel_giris/routes.py
**Patch tipi:** L411-413 arasina ~30 satir insert
**Etki:** 
- Tek dosya (DOKUNULMAZ alanin DOKUNULMASI - 6 patch sonrasi ilk kez)
- Hash degisecek: 41B220D201B0E1F8 -> yeni hash

**Hash degisimi sonrasi:**
- 6 patch'lik DOKUNULMAZ rekoru kirilir
- ANCAK bu bilincli ve onayli bir adim
- FLAG=False oldukca davranis degismez

## 11. RISK SEVIYESI

**Risk: ORTA-YUKSEK (4-6/10)**

**Sebepler:**
- DOKUNULMAZ alan dokunuyor (ilk kez 18.05'te)
- personel_giris saha tarafindan SUREKLI kullaniliyor (~200 personel)
- /prosesler endpoint cok kullanilan, en kritik
- Sahanin canli aktivitesi sirasinda patch yapamayiz (~mesai saati)
- Test penceresi siniri

**Azaltma:**
- FLAG=False default, davranis degismez
- Patch SADECE 1 yeri degistirir (hook insert)
- Try/except ile guvence
- Rollback 30 saniyede yapilabilir
- C.4 ve C.5 paterni proven (6 patch hatasiz)
- Test plani genisletilmis

## 12. FLAG=False IKEN DAVRANIS DEGISIMI

**Var mi: HAYIR**

Patch sonrasi (FLAG=False):
- CPS oku -> if cps_rows -> CPS_NATIVE return  [DEGISMEZ]
- CPS bos -> if USE_CPS_NATIVE_PROSES is True: SKIP (False)  [YENI ASA ATLAR]
- 5055 fallback -> LEGACY_5055_SNAPSHOT return  [DEGISMEZ]

**Tek fark:** Bir if check eklenir, False oldugu icin atlanir. Davranis %100 ayni.

## 13. FLAG=True IKEN BEKLENEN DAVRANIS

- CPS bos
- Korgun'da emir varsa: trigger calisir, INSERT yapar, CPS dolar, response CPS_NATIVE doner
- Korgun'da emir yoksa: trigger meta=None doner, hook'tan cikilir, 5055 fallback
- Eslesme yoksa: hook'tan cikilir, 5055 fallback
- Trigger hata verirse: try/except yakalar, 5055 fallback

## 14. ROLLBACK PLANI

**Tetik:** Eger atomic move sonrasi:
- /personel-giris/health 200 degil
- /prosesler/<emir_no> herhangi bir emir icin 500
- saha mobil cihazlardan sikayet (Halil veya saha personeli)

**Komut:**
\\\powershell
Copy-Item app\modules\personel_giris\routes.py.YEDEK_D5_FAZC5_P4_<ts> app\modules\personel_giris\routes.py -Force
\\\

**Sure:** <30 saniye
**Saha etkisi:** Mobil refresh sonrasi normal calisir

## 15. TEST LISTESI

### Pre-patch (FLAG=False ile yapilacak)
- T1: FLAG=False iken /prosesler/110393 -> CPS_NATIVE (mevcut davranis)
- T2: FLAG=False iken /prosesler/111005 -> [] (5055 yok, CPS bos)
- T3: FLAG=False iken /prosesler/110626 -> LEGACY_5055_SNAPSHOT (5055 fallback)
- T4: FLAG=False iken response birebir P6 oncesi ile ayni mi
- T5: personel_giris/health hala 200

### Post-patch tek-test (FLAG=True iken - lokal test)
- T6: Gecici FLAG=True yap, /prosesler/111006 -> trigger calisir, CPS_NATIVE_TRIGGERED veya CPS_NATIVE doner
- T7: T6 sonrasi DB'de emir_alt_proses[111006] var
- T8: Tekrar /prosesler/111006 -> CPS_NATIVE (duplicate check sonra)
- T9: FLAG=False'a geri don, /prosesler/yeni_emir -> 5055 fallback'e duser (trigger atlandi)
- T10: Korgun timeout simulasyonu (sahte) -> sessizce 5055 fallback'e geciler

### Saha simulasyonu
- T11: 200ms response time hedefli (FLAG=True iken)
- T12: 5 paralel cagri -> hicbiri 500 vermez

## 16. PATCH'E HAZIR MI?

**Bilesenler hazir mi:**
- [x] _eslesme_meta_from_emir (P1)
- [x] _eslesme_bul (P1)
- [x] _sablon_uygula_internal (P2, kaynak_prefix destekli)
- [x] /sablon/trigger manuel (P5, duplicate koruma)
- [x] config.USE_CPS_NATIVE_PROSES (P6)
- [x] /sablon/geri-al CPS_TRIGGER kapsami (P6)
- [x] Audit (sablon_id) (P6)

**Patch hazirligi:**
- [x] Hook tam yeri belli (L411 sonrasi)
- [x] Akis tasarimi netlesti
- [x] Risk azaltma stratejileri belirli
- [x] Test plani var
- [x] Rollback plani var
- [ ] **ADEM ONAYI BEKLENIYOR**

**Tahmin edilen patch suresi:** ~40 dakika (recon + staging + sim + verify + atomic move + 12 test)

**Onerim:** Saha aktivitesi DUSUK olan bir zaman dilimi sec (ogle arasi 12:00-13:00, aksam 18:00 sonrasi).