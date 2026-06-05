# D5 FAZ B+ — 5055 FALLBACK KAPATMA HAZIRLIK ANALIZI

**Tarih:** 2026-05-16 14:46:29
**Sprint:** D5 Faz B+ Analiz (kod degisikligi YOK)
**Amac:** 5055 fallback'i tamamen kapatabilmek icin kalan bagimliliklari belgelemek

---

## 1. OZET

D5 Faz A + Faz B sonrasi 5055 dependency genel olarak azaldi. /prosesler endpoint'i CPS_NATIVE veri doniyor. Faz C oncesi son durumu netlestirmek icin tam analiz yapildi.

## 2. PATTERN BAZLI MATCH SAYILARI

| Pattern | Sebep | Match |
|---|---|---|
| 5055 | Genel mention | 139 |
| DB_5055 | DB path constant | aktif |
| _5055_conn | Connection fonksiyonu | aktif (fallback) |
| LEGACY_5055 | Warning string | aktif |
| LEGACY_5055_SNAPSHOT | Veri kaynagi tag | aktif |
| snapshot | Snapshot mantigi | aktif |
| emir_proses | 5055 tablo adi | sadece fallback sorgu |

**Etkilenen dosya:** 66

## 3. DOSYA SINIFLANDIRMASI

### A. RUNTIME FALLBACK (canli fallback yapan)
- app\modules\canli_saha\routes.py (27 hit)
 - app\modules\personel_giris\routes.py (106 hit)


### D. MIGRATION SCRIPT (bir kerelik)
- app\migrations\001_legacy_5055_kolonlari.py (6 hit)
 - app\migrations\002_personel_kullanici.py (16 hit)
 - app\migrations\005_module_registry.py (2 hit)
 - app\migrations\006_permission_matrix_v2.py (1 hit)
 - app\migrations\007_sistem_yetki_seed.py (1 hit)
 - app\scripts\import_5055_bugun.py (29 hit)
 - app\scripts\import_5055_full.py (35 hit)


### C. RAPOR/DOKUMAN
18 dosya - silinmesine gerek yok

### E. GUVENLI KALABILIR
12 dosya - kucuk referanslar, runtime etkisi yok

## 4. PERSONEL-GIRIS DURUMU

- _5055_conn() cagrilari       : 3 (fallback path)
- FROM emir_proses sorgu       : 2 (fallback)
- FROM emir_alt_proses sorgu   : 2 (CPS-first)
- _legacy_warning cagri        : 7 (logging)

**Sonuc:** CPS_NATIVE aktif. Fallback sadece **CPS'te olmayan emir** icin tetiklenir.

**Tetikleme senaryolari:**
1. CPS emir_alt_proses'te bu emir_no YOK → 5055 fallback
2. CPS sorgu hatasi (DB locked vb) → 5055 fallback
3. /emir/<no> EmirMiktar bulunamadi → 5055 fallback

## 5. HEDEF EKRANI DURUMU

**GUVENLI:** hedef/ klasorunde 5055 referansi YOK. Hedef ekrani CPS DB + Korgun ile calisiyor.

5055 kapansa hedef ekrani **etkilenmez**.

## 6. CANLI_SAHA AYRI MODUL

canli_saha modulu hala 5055 solariz.db dosyasini okuyor. Bu **ayri bir sprint** gerektirir. D5 Faz C kapsaminda degil.

## 7. MIGRATION/SCRIPT

65 match - hepsi bir kerelik calistirilmis. 5055 portu kapansa **etkilenmez**.

## 8. KATEGORI SONUCLARI

| Kategori | Sonuc |
|---|---|
| personel_giris | GUVENLI |
| hedef | GUVENLI |
| runtime_dep | VAR (sadece personel-giris fallback) |
| fallback_oneri | SONRA (Faz C sonrasi) |
| faz_c_hazirlik | HAZIR |

## 9. SON KARAR

**5055 FALLBACK KAPATMA HAZIRLIK:**

- personel_giris       : GUVENLI
- hedef                : GUVENLI
- runtime dependency   : VAR (sadece personel-giris fallback)
- fallback kapatma     : SONRA (Faz C sonrasi)
- Faz C hazirlik       : HAZIR

## 10. ONERILEN FAZ C PLANI

1. **Sablon motoru kurulumu** (1 hafta)
   - sablon_master + sablon_proses tablolari (zaten mevcut)
   - Korgun emir trigger
   - Yeni emir geldiginde otomatik proses uretimi
   
2. **Yonetim UI** (3-4 gun)
   - Sablon yonetim ekrani
   - Manuel proses ekleme/duzenleme
   
3. **USE_CPS_NATIVE_PROSES = True aktivasyonu**
   - Sablon motoru calismaya basladiktan sonra
   - Test + dogrulama
   
4. **5055 fallback tamamen kapatma**
   - _5055_conn() return None doner gibi
   - Mevcut snapshot mantigi kalir (acil durum icin)

5. **canli_saha modulu CPS-native gecisi** (ayri sprint)

## SONUC

D5 Faz C ic in **hazir**. Sablon motoru + Yonetim UI olusturulduktan sonra 5055 fallback guvenle kapatilabilir.

**Tahmini Faz C suresi:** 1-2 hafta

---

**Olusturan:** D5 Faz B+ Analiz
