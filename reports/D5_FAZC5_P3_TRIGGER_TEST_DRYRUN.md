# D5 FAZ C.5 P3 - TRIGGER-TEST DRY-RUN ENDPOINT RAPORU

**Tarih:** 18.05.2026 08:51
**Sprint:** D5 Faz C.5 / P3: Trigger Test Dry-Run Endpoint
**Sonuc:** BASARILI - sifir saha kesintisi, sifir DB yazimi

## Yapilan

### Yeni endpoint
GET /hedef/sablon/trigger-test/<emir_no>
- INSERT/UPDATE/DELETE YOK
- Korgun get_emir_ozet -> _eslesme_bul -> sablon_proses -> mevcut_emir_alt_proses karsilastir
- 'dry_run: true' yanit
- Saha test penceresi olarak hizmet eder
- Auth wall korundu (mevcut /hedef/* gibi)

### Yardimci
_meta_jsonable(meta) - set -> list (JSON serialize icin)

## Hash karsilastirmasi

| Dosya | Onceki (P2) | Yeni (P3) |
|-------|-------------|-----------|
| hedef/routes.py | 3557C2EA6C4F054C | **C534DCEC9D1FAB0F** |
| personel_giris | 41B220D201B0E1F8 | 41B220D201B0E1F8 (DOKUNULMAZ) |

## Kod metrigi
- ~130 satir yeni kod, dosya sonuna append
- Mevcut endpoint'ler dokunulmadi

## Atomic move
- 0.25 ms
- Flask auto-reload tetiklendi
- Saha kesintisi: 0

## Tarayicidan test sonuclari (gercek emirler)

### Emir 110393 (Korgun'da var, tip=Y, cari=null)
- eslesme.sablon_adi: Asagi is indirme (oncelik 100, tip kurali)
- routing_sebep: ana:sablon_belirsiz (sablon ATKI/GOVDE icermiyor)
- mevcut_proses_sayisi: 4 (5055_IMPORT)
- tahmini_eklenecek: 1 ('Asagi is indirme')

### Emir 110626, 111007, 999999 (Korgun'da YOK - 5055_IMPORT veya bilinmeyen)
- mesaj: 'Korgun veri yok veya emir bulunamadi'
- HTTP 404
- Saha icin dogru davranis: trigger calismaz, fallback'e gec

## Bulgular

### 110393 senaryo analizi
- Eslesme motoru DOGRU calisti (tip=Y -> sablon 3 'Asagi is indirme')
- Karsilastirma DOGRU calisti (4 mevcut proses, 1 yeni)
- INSERT yapilmadi (dry_run garantisi)

### 5055_IMPORT emirleri Korgun'da yok
- mock_data.db'deki 5055_IMPORT kayitlari Korgun MSSQL'de bulunmuyor
- Trigger bu emirler icin calismayacak
- P4 lazy hook'ta emir_alt_proses'te kayit varsa zaten trigger atlanir

## Regression (5/5 PASS)
- /personel-giris/health: 200
- /personel-giris/prosesler/110393: CPS_NATIVE
- /hedef/sablon/liste: 200
- /hedef/sablon-eslesme/liste: 200
- /hedef/sablon/trigger-test/110393 (YENI): 200 + dry_run JSON

## Saha etkisi

- Patch oncesi uretim_kayit: 1380
- Patch sirasinda yeni kayit: 0
- DB integrity: ok
- Saha kesintisi: 0

## Tasarim notu

P3 sadece BILGI amacli, henuz aktif degil. P4'te (lazy hook) trigger DOGRU yerden cagrilacak:
- Sadece emir_alt_proses BOSSA cagri
- USE_CPS_NATIVE_PROSES=True olmali (FLAG)
- Yani 110393 gibi 4 prosesli emirde trigger zaten devreye girmez

## Sonraki adim

**P5** - /hedef/sablon/trigger/<emir_no> manuel admin endpoint (gercek INSERT yapan)
veya
**P4** - personel_giris lazy hook (YUKSEK risk, DOKUNULMAZ kirma)

Onerim: P5 once (dusuk risk, admin manuel), sonra P6 (config), sonra P4 (en sonda).

## Rollback yedek
routes.py.YEDEK_D5_FAZC5_P3_20260518_085111 (kullanilmadi)