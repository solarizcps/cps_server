# CORE_PERSONEL_360_FAZ1_USTA_SEED — DRY-RUN RAPORU (v2)
**Tarih:** 2026-06-06  
**Script:** `app/migrations/018_core_personel_usta_seed.py`  
**Mod:** DRY-RUN — veritabanına hiçbir yazma yapılmadı  
**Review:** Fix uygulandı — v2 (GPT review + 8 madde)

---

## YEDEK BİLGİSİ

| Tip | Konum |
|-----|-------|
| Proje yedeği | `C:\CPS_BACKUPS\Solariz_CPS_SERVER_BEFORE_CORE_PERSONEL_360_FAZ1_USTA_SEED_20260606` |
| DB yedeği | `C:\CPS_BACKUPS\mock_data_BEFORE_CORE_PERSONEL_360_FAZ1_USTA_SEED_20260606.db` (4.584 KB) |

Geri alma: DB yedeğini `app/mock_data.db` üzerine kopyala → eski haline döner.

**DB durumu:** `--apply` henüz çalıştırılmadı. `mock_data.db` yedekle birebir aynı (MD5 eşleşiyor).

---

## MEVCUT DURUM (Recon Sonuçları)

### kullanici_profil — Usta Durumu

| KP# | Ad | kullanici_adi | profil_tipi | departman_id | Sorun |
|-----|-----|---------------|-------------|--------------|-------|
| 2 | Halil | halil | SAHA_USTASI ✓ | **1 (Yönetim)** | dept yanlış → 4 olmalı — **MANUEL KARAR, bu fazda değişmez** |
| 14 | Ferhat Usta | ferhat | SAHA_USTASI ✓ | 4 (Enjeksiyon) ✓ | OK |
| 29 | Murat | murat | SAHA_USTASI ✓ | **None** | → 4 atanacak ✓ |
| 30 | Deniz | deniz | SAHA_USTASI ✓ | **None** | → 4 atanacak ✓ |
| — | Mehmet (Kesim) | mehmet_kesim | **YOK** | — | **MANUEL KARAR, Faz2'de oluşturulacak** |

> NOT: `mehmet` (KP#7, Mehmet ÇORABCI) planlama sorumlusudur. Dokunulmaz.

### kullanici_proses — Mevcut Usta Bağlantıları

| Profil | Mevcut Bağlantı | Eklenecek |
|--------|-----------------|-----------|
| Halil | kesim/monta/saya/temizleme/... usta tipi ✓ | Değişmez |
| Ferhat | enjeksiyon/**calisan** (mevcut) | + enjeksiyon/**usta** kaydı eklenecek |
| Murat | YOK | + monta/usta eklenecek |
| Deniz | YOK | + temizleme/usta eklenecek |
| Mehmet Kesim | Profil yok | Faz2'de |

> NOT: Ferhat'ın mevcut `enjeksiyon/calisan` kaydı **silinmez**. Sadece ayrı `usta` tipi kayıt eklenir.

---

## --apply İLE UYGULANACAK DEĞİŞİKLİKLER

```
UPDATE kullanici_profil:
  KP#29 Murat   departman_id: None → 4 (Enjeksiyon)
  KP#30 Deniz   departman_id: None → 4 (Enjeksiyon)

INSERT kullanici_proses (iliski_tipi='usta', sadece 'usta' tipi yoksa):
  Ferhat (KP#14) → enjeksiyon / usta
  Murat  (KP#29) → monta      / usta
  Deniz  (KP#30) → temizleme  / usta

Silme          : 0
Şema değişikliği: YOK
```

---

## MANUEL KARAR BEKLIYOR (Bu Fazda Uygulanmıyor)

| Konu | Açıklama |
|------|----------|
| Halil `departman_id` 1→4 | Ayrı onay gerekli — `--apply` ile değişmez |
| `mehmet_kesim` profil oluşturma | Faz2'de ayrı onay ile |
| 11 SAHA_PERSONEL `departman_id` ataması | Faz2'de kişi bazlı onay ile |
| Adım 5 Personel → Usta bağlantıları | Ayrı onay gerekli |

---

## ADIM 5 — USTA-PERSONEL BAĞLANTISI ÖNERİLERİ (OTOMATİK UYGULANMAZ)

Bu bağlantılar ne dry-run ne apply modunda uygulanmaz. Manuel karar gereklidir.

| # | Usta | Personel | Proses | Not |
|---|------|----------|--------|-----|
| 1 | Ferhat (KP#14) | Mustafa Enes Öztürk (KP#31) | enjeksiyon | Onay? |
| 2 | Ferhat (KP#14) | Moustafa Kordy (KP#32) | enjeksiyon | Onay? |
| 3 | Ferhat (KP#14) | Badr Safa (KP#33) | enjeksiyon | Onay? |
| 4 | Murat (KP#29) | Merdan Hojamkulov (KP#35) | monta | Onay? |
| 5 | Murat (KP#29) | Aman Hudayberdiyev (KP#37) | monta | Onay? |
| 6 | Murat (KP#29) | Mahmoud Alkhatib (KP#38) | monta | Onay? |
| 7 | Murat (KP#29) | Alisher Gaibov (KP#39) | monta | Onay? |
| 8 | Mehmet Kesim | — | kesim | Kesim personeli bilinmiyor |

**Mevcut (dokunulmaz) bağlantılar:**

| Usta | Personel |
|------|----------|
| Halil | Adem Özkan (KP#34) |
| Ferhat | Adem Özkan (KP#34) |
| Ferhat | Lanchyn Kurbanova (KP#36) |
| Deniz | Recep Arabacı (KP#40) |

---

## SONRAKI ADIM

Onay geldikten sonra:
```powershell
cd "C:\Solariz_CPS_SERVER\app\migrations"
python 018_core_personel_usta_seed.py --apply
```

`--apply` sonrası commit edilecek dosyalar:
- `app/migrations/018_core_personel_usta_seed.py`
- `reports/CORE_PERSONEL_360_FAZ1_USTA_SEED_DRYRUN_20260606.md`

`app/mock_data.db` commit edilmez.
