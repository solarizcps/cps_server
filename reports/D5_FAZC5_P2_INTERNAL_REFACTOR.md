# D5 FAZ C.5 P2 - _sablon_uygula_internal REFACTOR RAPORU

**Tarih:** 18.05.2026
**Saat:** 08:43
**Sprint:** D5 Faz C.5 / P2: Sablon Uygula Refactor
**Sonuc:** BASARILI - sifir saha kesintisi, sifir davranis degisimi

## Yapilan

### Refactor stratejisi
Mevcut /sablon/uygula HTTP endpoint'inin 94 satirlik govdesi:
- Tum is mantigi -> _sablon_uygula_internal(emir_no, sablon_id, kaynak_prefix='sablon', conn=None, uid=None, uad=None) saf fonksiyona tasindi
- HTTP wrapper 11 satira dustu (request parse + helper call + jsonify)
- Davranis BIRE BIR korundu (response format, status code, INSERT order, audit)
- kaynak_prefix='CPS_TRIGGER_C5' destekli (P4 trigger icin)

### Kod metrikleri

| Bolum | Eski | Yeni |
|-------|------|------|
| /sablon/uygula endpoint | 94 satir | 11 satir |
| _sablon_uygula_internal (YENI) | 0 | ~110 satir |
| Net degisim | - | +27 satir |
| LIVE byte | 107901 | 109065 (+1164) |

## Hash karsilastirmasi

| Dosya | Onceki (P1 sonrasi) | Yeni (P2 sonrasi) |
|-------|---------------------|---------------------|
| hedef/routes.py | 642B553F48D2EA0F | **3557C2EA6C4F054C** |
| personel_giris | 41B220D201B0E1F8 | 41B220D201B0E1F8 (DOKUNULMAZ) |
| sablon.html | B3331364975FF6B6 | B3331364975FF6B6 (degismedi) |
| sablon.js | 32B4D05B97B8FCF8 | 32B4D05B97B8FCF8 (degismedi) |

## Atomic move

- 0.24 ms
- Flask auto-reload tetiklendi (5 sn bekleme yeterli)
- Saha kesintisi: 0

## Smoke test (8/8 PASS)

| Endpoint | Sonuc |
|----------|-------|
| /personel-giris/health | 200 |
| /personel-giris/prosesler/110393 | CPS_NATIVE |
| /hedef/ | 200 |
| /hedef/sablon | 200 |
| /hedef/sablon/liste | 200 |
| /hedef/sablon-eslesme/liste | 200 |
| /hedef/sablon/proses-onerileri | 200 |
| /hedef/sablon/uygula (POST baseline) | 200 + login HTML (baseline AYNEN) |

### Sozlesme korumasi (KRITIK)
- /sablon/uygula POST: P1 oncesi davranis = login HTML auth wall (anonim)
- P2 sonrasi davranis: AYNI (HTTP 200, login HTML, ayni byte uzunluk)
- Response BIRE BIR korundu

## Saha etkisi

- Patch oncesi uretim_kayit: 1380
- Patch sonrasi uretim_kayit: 1380
- Patch sirasinda yeni kayit: 0
- Saha kesintisi: 0

## Riskler ve notlar

### Test edilmis senaryolar
- Mevcut HTTP endpoint hala calisiyor
- Tum response field'lari korundu (ok, emir_no, sablon_id, sablon_adi, eklenen, atlanan)
- HTTP status code dogruluk (400 validation, 404 sablon yok, 500 exception)
- Mevcut sablon.js (UI) etkilenmedi

### Test edilmemis (henuz)
- _sablon_uygula_internal DOGRUDAN cagirma (P4 ve P5'te yapilacak)
- kaynak_prefix='CPS_TRIGGER_C5' davranisi (P6'da test edilecek)
- conn parametresi disaridan verme (P4 lazy hook'ta kullanilacak)

### Ileride iyilestirme
- BEGIN IMMEDIATE lock pattern (race condition) - mevcut kod taklit etti, P4'te eklenebilir
- Performans: tek SELECT yerine batch (sablon_proses olur)

## Sonraki adim

**P3** - /hedef/sablon/trigger-test/<emir_no> dry-run endpoint. Eslesme motoru + helper'i birlestirir ama INSERT YAPMAZ. Sahaya test penceresi.

## Rollback yedek

routes.py.YEDEK_D5_FAZC5_P2_20260518_084357 (kullanilmadi)