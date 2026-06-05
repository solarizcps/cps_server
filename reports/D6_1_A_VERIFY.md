# D6.1-A operasyon_sinyal Migration - VERIFY RAPORU

**Tarih:** 18.05.2026 12:51
**Sprint:** D6.1-A (Sinyal Motoru - Tablo Altyapisi)
**Sonuc:** TAMAMLANDI

## Yapilan

- Migration: app/migrations/011_operasyon_sinyal.py
- operasyon_sinyal tablosu olusturuldu (21 kolon dahil id + 5 index)
- SEED YOK (0 kayit)
- schema_migrations[011] kaydedildi

## Schema (21 kolon)

id, sinyal_tipi, seviye, emir_no, proses_adi, proses_kodu, personel_id,
personel_ad, mesaj, aksiyon_onerisi, kaynak, rule_id, durum (DEFAULT 'AKTIF'),
gorulen_kullanici_id, gorulen_zaman, cozulen_zaman, cozulen_aciklama,
tekrar_sayisi (DEFAULT 1), son_tetiklenme, meta_json, olusturma (DEFAULT CURRENT_TIMESTAMP)

CHECK/FK/UNIQUE constraints YOK (esneklik + idempotency kod tarafinda)

## Index (5)

- idx_os_tipi_durum (sinyal_tipi, durum)
- idx_os_emir (emir_no)
- idx_os_kaynak (kaynak)
- idx_os_olusturma (olusturma)
- idx_os_seviye (seviye)

## Hash gate (KORUNDU)

- hedef/routes.py: 7EAC892167AFEAD1 (P6)
- config.py: 6CD32DCB1E1B3EBE (C.8 FLAG=True)
- personel_giris/routes.py: F6D1953CC0243B0C (P4)
- yonetim/routes.py: 3A36699511E9CEC6 (D6.0.1 BCD+FIX)

## Etkilenmeyen tablolar

- uretim_kayit: degismedi
- emir_alt_proses: degismedi
- proses_alias: degismedi (15 kayit)

## Rollback

\\\powershell
Copy-Item "app\mock_data.db.YEDEK_D6_1_A_20260518_124558" "app\mock_data.db" -Force
\\\

## Sprint durumu

- [X] D6.1-A: Tablo + INIT (BU PATCH)
- [ ] D6.1-B: Rule engine (R001-R005)
- [ ] D6.1-C: Liste endpoint
- [ ] D6.1-D: Yonetim UI
- [ ] D6.1-E: Scheduler (opsiyonel)