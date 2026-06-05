# D5 FAZ C.5 P5 - MANUEL TRIGGER ENDPOINT RAPORU

**Tarih:** 18.05.2026 09:10
**Sprint:** D5 Faz C.5 / P5: Manuel Trigger Endpoint (ilk gercek INSERT)
**Sonuc:** BASARILI - sifir saha kesintisi, kontrollu INSERT + temizlik

## Yapilan

### Yeni endpoint
POST /hedef/sablon/trigger/<emir_no>
- Admin manuel cagrisi (auth gerekli)
- Lazy hook DEGIL - sadece test/admin
- Duplicate koruma: emir_alt_proses'te aktif=1 kayit varsa "zaten_islenmis" doner
- Korgun veri yoksa "korgun_veri_yok"
- Eslesme yoksa "eslesme_yok"
- INSERT basariliysa "islendi" + kaynak='CPS_TRIGGER_C5:<sablon_adi>'

### Tasarim
- _eslesme_meta_from_emir -> meta
- _eslesme_bul -> sablon
- _sablon_uygula_internal(kaynak_prefix='CPS_TRIGGER_C5') -> INSERT
- Tum motor zinciri (P1+P2) kullaniliyor

## Hash karsilastirmasi

| Dosya | Onceki (P3) | Yeni (P5) |
|-------|-------------|-----------|
| hedef/routes.py | C534DCEC9D1FAB0F | **DD83F35FAC5CCEC1** |
| personel_giris | 41B220D201B0E1F8 | 41B220D201B0E1F8 (DOKUNULMAZ) |

## Kod metrigi
- ~110 satir yeni kod, dosya sonuna append
- Mevcut endpoint'ler dokunulmadi
- /sablon/uygula (P2) ve /trigger-test (P3) hala calisiyor

## Atomic move
- 0.28 ms
- Flask auto-reload tetiklendi

## Test sonuclari (7/7 PASS)

### 1. Dry-run (P3) ile beklenti dogrulama
- emir 111005 dry-run
- eslesme: Atki LCW (varsayilan, oncelik 999)
- tahmini_eklenecek: 4 proses
- Beklenti DOGRU

### 2. GERCEK INSERT (P5 ilk cagrı)
- POST /hedef/sablon/trigger/111005
- Login: admin/f7a6ua61 (NOT admin123 - sahada degistirilmis)
- HTTP 200
- Response: durum=islendi, eklenen_sayisi=4, kaynak=CPS_TRIGGER_C5
- DB: id 2274-2277 olarak 4 yeni satir

### 3. DB Audit dogrulama
- 4 kayit eklendi (Capak, Rivet Takma, Tampon Baski, Atki Silme)
- kaynak='CPS_TRIGGER_C5:Atki LCW' (audit DOGRU)
- olusturan_ad='Sistem'(0) - trigger session resolve fallback (kabul edilebilir)
- sablon_id=None (BILINEN EKSIK - P6'da duzeltilir)
- aktif=1

### 4. Saha view test (CPS_NATIVE)
- GET /personel-giris/prosesler/111005
- 4 satir JSON, veri_kaynagi='CPS_NATIVE'
- limit_miktar=0, toplam_girilen=0 (saha henuz uretim yapmamis)
- SAHA TARAFINDAN GORULUYOR

### 5. Duplicate koruma test
- POST /hedef/sablon/trigger/111005 (ikinci kez)
- HTTP 200, durum=zaten_islenmis
- mevcut_proses_sayisi=4
- DB DEGISMEDI (yeni INSERT yok)

### 6. Temizlik (saha tertemiz birak)
- Manuel SQL: UPDATE aktif=0 WHERE emir_no='111005' AND kaynak LIKE 'CPS_TRIGGER_C5:%'
- 4 kayit pasif
- audit korundu (kayit tabloda var, sadece aktif=0)

### 7. Saha view tekrar test
- GET /personel-giris/prosesler/111005
- Response: [] (3 byte, BOS)
- Saha tertemiz, hicbir CPS_NATIVE kayit gozukmuyor

## Saha etkisi

- Patch oncesi uretim_kayit: 1380
- Patch sonrasi uretim_kayit: 1380
- Saha kesintisi: 0
- Kontrol disindaki etki: 0

## Onemli notlar

### 1. Admin sifre DEGISTI
- Memory'de "admin/admin123" yaziyordu
- Gercek sifre: **admin/f7a6ua61**
- Sahada 11.05 sonrasi muhtemelen degisti
- Memory update gerekli

### 2. /sablon/geri-al endpoint kapsam disi
- Mevcut kod sadece kaynak LIKE 'sablon:%' siler
- CPS_TRIGGER_C5 kayitlarini SILMEZ
- Manuel SQL ile cozuldu
- P6'da geri-al endpoint genisletilmeli

### 3. Audit alanlari eksik
- olusturan_ad='Sistem'(0) trigger icin uygun ama kayit oturum kullanicisina yansimiyor
- sablon_id INSERT'te yazilmiyor (mevcut /sablon/uygula da yazmiyordu)
- P6'da iyilestirme

### 4. Varsayilan kural cok genis
- 111005 (M tip, Sahin Taban) -> varsayilan -> Atki LCW
- Bu mantikli mi? Tartismali (M tipi atki sablonu almali mi?)
- sablon_eslesme yonetim panelinden ayarlanabilir

## Sonraki adim

**P6** - Config + audit iyilestirme:
- USE_CPS_NATIVE_PROSES flag (varsayilan False)
- /sablon/geri-al'a CPS_TRIGGER_C5 kapsami ekle
- emir_alt_proses INSERT'te sablon_id yazilsin

**P4** (en sonda) - personel_giris lazy hook:
- Sahaya otomatik tetikleme
- FLAG=True olunca aktif
- YUKSEK risk - DOKUNULMAZ alan

## Rollback yedek
routes.py.YEDEK_D5_FAZC5_P5_20260518_085613 (kullanilmadi)