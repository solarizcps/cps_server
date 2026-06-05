# D6.0.1 PATCH-B+C+D - VERIFY RAPORU

**Tarih:** 18.05.2026 12:09
**Sprint:** D6.0.1 PATCH-B+C+D (admin gorunurluk)
**Sonuc:** TAMAMLANDI - sprint kapandi

## Yapilan

### PATCH-B: GET /yonetim/proses-alias/liste (JSON)
- read-only endpoint
- Response: { ok, toplam, onayli, bekleyen, aliaslar[] }
- ORDER BY standart_kod, saha_adi
- _faz7_admin_kontrol yetki

### PATCH-D: GET /yonetim/proses-alias (UI render)
- render_template('yonetim/proses_alias.html')
- _faz7_admin_kontrol yetki

### PATCH-C: templates/yonetim/proses_alias.html
- 3 KPI kart (toplam/onayli/bekleyen)
- Tablo (saha_adi, kod, standart_adi, kategori, guven, kaynak, durum)
- Onayli=yesil, Bekleyen=sari
- Filter input + refresh button
- CRUD YOK - sadece gorunurluk

## Hash karsilastirmasi

| Dosya | Onceki | Yeni |
|-------|--------|------|
| hedef/routes.py | 7EAC892167AFEAD1 | 7EAC892167AFEAD1 (KORUNDU) |
| config.py | 6CD32DCB1E1B3EBE | 6CD32DCB1E1B3EBE (KORUNDU) |
| personel_giris/routes.py | F6D1953CC0243B0C | F6D1953CC0243B0C (KORUNDU) |
| yonetim/routes.py | 1790EF07602730A3 | **C1DBC21D98CA7ED8** (BCD) |

YENI dosya: app/templates/yonetim/proses_alias.html (6810 byte)

## Verify sonuclari

- /health: 200
- /prosesler/110393: BIREBIR (B9B1C8CC6C646AD5)
- /prosesler/111015: CPS_NATIVE (duplicate guard)
- /yonetim/proses-alias/liste: 200, 15 alias
- /yonetim/proses-alias: HTML render (markerlar var)
- proses_alias: 15 kayit
- uretim_kayit: dokunulmadi
- emir_alt_proses: dokunulmadi

## D6.0.1 SPRINT TAM TAMAM

- PATCH-A: migration + 15 seed
- PATCH-B: read-only JSON endpoint
- PATCH-C: yonetim UI template
- PATCH-D: UI render route

Tum altyapi hazir. AI sinyalleri icin proses normalize sozlugu hazir.
Runtime davranis %100 korundu.

## Rollback (gerekirse)

\\\powershell
# Routes geri al
Copy-Item "app\modules\yonetim\routes.py.YEDEK_D6_0_1_BCD_20260518_120953" "app\modules\yonetim\routes.py" -Force
# Template kaldir
Remove-Item "app\templates\yonetim\proses_alias.html" -Force
\\\

DB rollback gerekirse (PATCH-A da geri al):
\\\powershell
Copy-Item app\mock_data.db.YEDEK_D6_0_1_PATCH_A_20260518_105653 app\mock_data.db -Force
\\\

## NEXT

D6.0.1 sprint kapali. Sonraki adim:
- D6.0.2 (admin onay UI - manuel saha varyant ekleme)
- D6.1 (sinyaller motoru iskelet)
- Veya P7 (created_at audit fix)