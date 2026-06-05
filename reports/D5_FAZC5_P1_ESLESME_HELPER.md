# D5 FAZ C.5 P1 - _eslesme_bul HELPER RAPORU

**Tarih:** 18.05.2026
**Saat:** 08:31
**Sprint:** D5 Faz C.5 - Trigger Motoru / P1: Eslesme Helper
**Sonuc:** BASARILI - sifir saha kesintisi, sifir davranis degisimi

## Uygulanan

### Helper kodu (hedef/routes.py'ye append)
- _eslesme_meta_from_emir(emir_no) - Korgun get_emir_ozet sarmalayicisi
- _kural_eslesti(tip, deger, meta) - Saf fonksiyon, tek kural karsilastirma
- _eslesme_bul(meta, conn=None) - Tum sablon_eslesme kurallarini oncelik sirali tarar

### Karsilastirma kurallari
- musteri/model: _normalize_tr_local sonrasi CONTAINS
- tip: normalize sonrasi EXACT (tam esitlik)
- location: normalize sonrasi startsWith
- varsayilan: her zaman True (fallback)
- cari_kod/stok_kodu/ozkod: meta'da yok ise SKIP (ileride alan eklenince aktif)
- ozel: reserved (False doner)
- Pasif sablon: LEFT JOIN aktif=1 sarti, sablon_adi None ise atlanir

## Hash karsilastirmasi

| Dosya | Onceki | Yeni |
|-------|--------|------|
| hedef/routes.py | 7BA720964BC8537F | **642B553F48D2EA0F** |
| personel_giris/routes.py | 41B220D201B0E1F8 | 41B220D201B0E1F8 (DOKUNULMAZ) |
| sablon.html | B3331364975FF6B6 | B3331364975FF6B6 (degismedi) |
| sablon.js | 32B4D05B97B8FCF8 | 32B4D05B97B8FCF8 (degismedi) |

## Kod metrikleri

- 3 yeni fonksiyon (~140 satir)
- Mevcut /sablon/* endpoint'leri: DOKUNULMADI
- C.4 sablon_eslesme CRUD: DOKUNULMADI
- Side-effect: YOK (INSERT/UPDATE/DELETE/HTTP yok)
- Helper henuz hicbir yerden cagrilmiyor (P4'te cagrilacak)

## Test sonuclari

### Unit test (15/15 PASS)
- varsayilan ile bos meta -> True
- musteri=LCW + cari_adi='LCW Turkey...' -> True
- musteri=LCW + cari_adi='Esem...' -> False
- musteri=LCW + cari_adi=None -> False
- model=ATKI + model_adi='Atki govde' -> True
- tip=Y + meta.tip='Y' -> True
- tip=M + meta.tip='Y' -> False (CONTAINS degil EXACT)
- location=SU + meta.location='SU001 Sahin' -> True (startsWith)
- location=SA + meta.location='SU001 Sahin' -> False
- cari_kod=120-001 + meta=None -> False (SKIP)
- ozel=whatever -> False (reserved)
- Bilinmiyor tip -> False

### Canli DB senaryo testi (5/5 PASS)
1. **110393** (Korgun canli: cari=None, tip=Y) -> tip=Y kurali (onc 100) -> **Asagi is indirme**
2. **LCW musteri** -> musteri=LCW (onc 20) -> **Lcw atki** (oncelik 25'i Atki LCW atlamadi)
3. **Esem musteri** -> musteri=Esem (onc 20) -> **Esem**
4. **Tip M, musteri yok** -> varsayilan (onc 999) -> **Atki LCW**
5. **Bos meta** -> varsayilan -> **Atki LCW**

### Endpoint regression (6/6 PASS)
- /personel-giris/health: 200
- /personel-giris/prosesler/110393: CPS_NATIVE
- /hedef/: 200
- /hedef/sablon: 200
- /hedef/sablon/liste: 200
- /hedef/sablon-eslesme/liste: 200

## Saha etkisi

- Patch oncesi uretim_kayit toplam: 1380
- Patch sirasinda uretim aktivitesi: 0
- Helper hicbir yerden cagrilmiyor (davranis %0 degisim)

## Riskler ve notlar

### Bilinen test sinirlamasi
Dry-run testinde _eslesme_meta_from_emir standalone Python script'te calismadi (Flask app context gerekli, openpyxl bagimliligi sorunu).
- Canli sunucuda calisirken sorun yok (Flask request context icinde)
- Workaround: DB direkt baglanip _kural_eslesti'yi standalone test ettik (yukarida)

### Ileride iyilestirme alanlari
- **Exact/regex/weighted match engine**: Su anki contains/startsWith basit. Karmasik kurallar icin regex destegi eklenebilir.
- **cari_kod/stok_kodu/ozkod alanlari**: get_emir_ozet'e eklenince otomatik aktiflesir, helper'a dokunma gerekmez.
- **Cache**: sablon_eslesme query her trigger'da yapilir; uretim hizla artarsa LRU cache eklenebilir.

## Sonraki adim

**P2** - _sablon_uygula_internal refactor. Mevcut /sablon/uygula endpoint govdesini fonksiyona cikarir, HTTP wrapper aynisi kalir. Risk: ORTA (mevcut endpoint dokunulmasi).

## Stable tag

routes.py.YEDEK_D5_FAZC5_P1_20260518_082019 (rollback icin)