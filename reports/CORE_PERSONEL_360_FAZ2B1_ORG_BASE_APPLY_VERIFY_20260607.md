# CORE_PERSONEL_360_FAZ2B1_ORG_BASE_APPLY_VERIFY

**Tarih:** 2026-06-07 09:20:59  
**Script:** `app/migrations/020_core_personel_360_faz2b1_org_base.py --apply`  
**Durum:** TAMAMLANDI — tüm doğrulamalar geçti

---

## Backup Bilgisi

| Tip | Konum | MD5 |
|-----|-------|-----|
| Apply öncesi DB backup | `C:\CPS_BACKUPS\mock_data_BEFORE_FAZ2B1_20260607_081655.db` | `ae850a9a970de2b6d8662fd8ab3eb9a6` |
| Apply sonrası DB | `app/mock_data.db` | `5ccf237517811a93040cc99f0f2511e8` |

Geri alma: backup dosyasını `app/mock_data.db` üzerine kopyala.

---

## Uygulanan 8 Değişiklik

| # | Tablo | id | Değişiklik | Sonuç |
|---|-------|----|------------|-------|
| 1 | `departman_master` | 19 | INSERT: regola / Regola / uretim | ✓ |
| 2 | `departman_master` | 20 | INSERT: monta / Monta / uretim | ✓ |
| 3 | `departman_master` | 21 | INSERT: temizleme / Temizleme / uretim | ✓ |
| 4 | `departman_master` | 22 | INSERT: kesim / Kesim / uretim | ✓ |
| 5 | `kullanici_profil` | 42 | INSERT: Alpay Dülger / profil_tipi=yonetim | ✓ |
| 6 | `kullanici_profil` | KP#2 | UPDATE: Halil departman_id 1→19 (Regola) | ✓ |
| 7 | `kullanici_profil` | KP#29 | UPDATE: Murat departman_id 4→20 (Monta) | ✓ |
| 8 | `kullanici_profil` | KP#30 | UPDATE: Deniz departman_id 4→21 (Temizleme) | ✓ |

Ferhat KP#14 skip: departman_id=4 Enjeksiyon zaten doğruydu.

---

## Readonly Doğrulama Sonuçları

### Yeni departmanlar

| Kontrol | Beklenen | Gerçekleşen | Durum |
|---------|----------|-------------|-------|
| departman_master regola | id=19, aktif=1 | id=19, aktif=1, tur=uretim | ✓ |
| departman_master monta | id=20, aktif=1 | id=20, aktif=1, tur=uretim | ✓ |
| departman_master temizleme | id=21, aktif=1 | id=21, aktif=1, tur=uretim | ✓ |
| departman_master kesim | id=22, aktif=1 | id=22, aktif=1, tur=uretim | ✓ |

### Alpay profili

| Kontrol | Beklenen | Gerçekleşen | Durum |
|---------|----------|-------------|-------|
| KP#42 gercek_ad | Alpay Dülger | Alpay Dülger | ✓ |
| KP#42 kullanici_adi | alpay | alpay | ✓ |
| KP#42 profil_tipi | yonetim | yonetim | ✓ |
| KP#42 departman_id | 1 (Yönetim) | 1 | ✓ |
| KP#42 kaynak / kaynak_id | sistem_kullanici / 39 | sistem_kullanici / 39 | ✓ |
| KP#42 aktif | 1 | 1 | ✓ |

### Usta ana departman güncellemeleri

| KP | Ad | Beklenen | Gerçekleşen | Durum |
|----|----|----------|-------------|-------|
| #2 | Halil | dept_id=19 Regola | dept_id=19 Regola | ✓ |
| #14 | Ferhat Usta | dept_id=4 Enjeksiyon (skip) | dept_id=4 Enjeksiyon | ✓ |
| #29 | Murat | dept_id=20 Monta | dept_id=20 Monta | ✓ |
| #30 | Deniz | dept_id=21 Temizleme | dept_id=21 Temizleme | ✓ |

---

## Kapsam Dışı Doğrulama

| Kontrol | Beklenen | Gerçekleşen | Durum |
|---------|----------|-------------|-------|
| kullanici_proses aktif kayıt sayısı | 18 (değişmemeli) | 18 | ✓ |
| usta_personel_iliskisi aktif sayısı | 4 (değişmemeli) | 4 | ✓ |
| sistem_kullanici aktif sayısı | 14 (değişmemeli) | 14 | ✓ |
| SAHA_PERSONEL aktif sayısı | 11 (değişmemeli) | 11 | ✓ |
| SAHA_PERSONEL departman_id=NULL sayısı | 11 (değişmemeli) | 11 | ✓ |
| KP#41 Halil Kıraç departman_id | NULL (dokunulmamış) | NULL | ✓ |
| ENJ_CORE tabloları | dokunulmadı | dokunulmadı | ✓ |
| Finans / Planlama | dokunulmadı | dokunulmadı | ✓ |
| Template / route dosyaları | dokunulmadı | dokunulmadı | ✓ |

---

## Git Durumu

```
 M app/mock_data.db          ← apply sonrası değişti, commit EDİLMEZ
?? app/migrations/020_core_personel_360_faz2b1_org_base.py    ← commit adayı
?? reports/CORE_PERSONEL_360_FAZ2B1_ORG_BASE_DRYRUN_20260607.md ← commit adayı
?? reports/CORE_PERSONEL_360_FAZ2B1_ORG_BASE_APPLY_VERIFY_20260607.md ← commit adayı
```

`app/mock_data.db` **commit edilmeyecek.**  
Migration script ve raporlar ayrıca onay verilirse commit edilebilir.

---

## Sonuç

`CORE_PERSONEL_360_FAZ2B1_ORG_BASE` tamamlandı.  
8 değişiklik uygulandı. Tüm kapsam dışı doğrulamalar geçti.  
DB yedekle izlenebilir (`kaynak='020_faz2b1'` veya backup MD5 ile).
