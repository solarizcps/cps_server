# D6.1-B Sinyal Engine - VERIFY RAPORU

**Tarih:** 18.05.2026 13:01
**Sprint:** D6.1-B (Rule Engine + Manuel Tetik)
**Sonuc:** TAMAMLANDI

## Yapilan

- Yeni dosya: app/services/__init__.py (23 byte)
- Yeni dosya: app/services/sinyal_engine.py (7394 byte)
- Endpoint append: yonetim/routes.py + POST /yonetim/sinyal-engine/test

## Engine yapisi

- 2 Rule sinifi tanimli (R001 aktif, R004 pasif)
- FEATURE_FLAGS dict:
  - R001_DURGUN_EMIR_7G: True (aktif)
  - R004_PERSONEL_BUGUN_0: False (pasif, Adem karari)
- save_signal: idempotent (AKTIF + ayni rule+emir varsa UPDATE tekrar_sayisi++, yoksa INSERT)
- run_rule + run_all_rules + rule_filter destegi
- Body: dry_run=true (default) veya dry_run=false

## R001_DURGUN_EMIR_7G

SQL: emir_alt_proses + uretim_kayit LEFT JOIN, HAVING gun_durgun >= 7.0
Sonuc: 257 emir (P1 recon 510 - hic hareket yok olan 253 emir HARIC)
seviye: WARN
mesaj: 'Emir XXXX son X.X gundur durgun'

## R004_PERSONEL_BUGUN_0

PASIF. FEATURE_FLAGS[R004_PERSONEL_BUGUN_0]=False olduğu surece engine skip eder.

## Hash karsilastirmasi

- hedef/routes.py: 7EAC892167AFEAD1 (KORUNDU)
- config.py: 6CD32DCB1E1B3EBE (KORUNDU)
- personel_giris: F6D1953CC0243B0C (KORUNDU)
- yonetim/routes.py: 3A36699511E9CEC6 -> **ED2EFB7186C5C757** (D6.1-B)

## Verify

- /health: 200
- /yonetim/sinyal-engine/test dry_run=true: 0 INSERT, 257 listelendi
- 1. APPLY dry_run=false: 257 INSERT
- 2. APPLY dry_run=false: 0 INSERT + 257 UPDATE (tekrar_sayisi=2)
- operasyon_sinyal: 257 kayit (sabit)
- uretim_kayit: dokunulmadi
- emir_alt_proses: dokunulmadi
- proses_alias: dokunulmadi

## Rollback

\\\powershell
Copy-Item "app\mock_data.db.YEDEK_D6_1_B_20260518_125429" "app\mock_data.db" -Force
Copy-Item "app\modules\yonetim\routes.py.YEDEK_D6_1_B_20260518_125429" "app\modules\yonetim\routes.py" -Force
Remove-Item "app\services\sinyal_engine.py" -Force
Remove-Item "app\services\__init__.py" -Force
Remove-Item "app\services" -Force
\\\

## NEXT

- D6.1-C: 5 yonetim endpoint (liste/gor/dismiss/cozuldu/ozet)
- D6.1-D: UI template (sinyaller.html)
- D6.1-E: Scheduler (opsiyonel)