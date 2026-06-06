# CORE_PERSONEL_360_FAZ1_APPLY_VERIFY
**Tarih:** 2026-06-06 17:21  
**Script:** `app/migrations/018_core_personel_usta_seed.py --apply`  
**Durum:** TAMAMLANDI — tüm doğrulamalar geçti

---

## Yedek Bilgisi

| Tip | Konum |
|-----|-------|
| Apply öncesi DB backup | `C:\CPS_BACKUPS\mock_data_BEFORE_FAZ1_APPLY_20260606_171926.db` |
| FAZ1 öncesi DB backup | `C:\CPS_BACKUPS\mock_data_BEFORE_CORE_PERSONEL_360_FAZ1_USTA_SEED_20260606.db` |

Geri alma: apply öncesi yedeği `app/mock_data.db` üzerine kopyala.

---

## Apply Kapsamı — Uygulanan 5 Değişiklik

| # | Tablo | Kayıt | Değişiklik | Sonuç |
|---|-------|-------|------------|-------|
| 1 | `kullanici_profil` | KP#29 Murat | `departman_id: NULL → 4` | ✓ |
| 2 | `kullanici_profil` | KP#30 Deniz | `departman_id: NULL → 4` | ✓ |
| 3 | `kullanici_proses` | id=33, Ferhat | `enjeksiyon / usta` eklendi | ✓ |
| 4 | `kullanici_proses` | id=34, Murat | `monta / usta` eklendi | ✓ |
| 5 | `kullanici_proses` | id=35, Deniz | `temizleme / usta` eklendi | ✓ |

Toplam: 2 UPDATE + 3 INSERT — silme yok, şema değişikliği yok.

---

## Readonly Doğrulama Sonuçları

| Kontrol | Beklenen | Gerçekleşen | Durum |
|---------|----------|-------------|-------|
| Murat `departman_id` | 4 | 4 | ✓ |
| Deniz `departman_id` | 4 | 4 | ✓ |
| Ferhat `enjeksiyon/usta` kaydı | var | var (KP#33) | ✓ |
| Ferhat `enjeksiyon/calisan` kaydı korundu | var | var (KP#23) | ✓ |
| Murat `monta/usta` kaydı | var | var (KP#34) | ✓ |
| Deniz `temizleme/usta` kaydı | var | var (KP#35) | ✓ |
| Halil `departman_id` | 1 (değişmemeli) | 1 | ✓ |
| `mehmet_kesim` profili | YOK (değişmemeli) | YOK | ✓ |
| `usta_personel_iliskisi` satır sayısı | 4 (değişmemeli) | 4 | ✓ |
| SAHA_PERSONEL `NULL departman_id` sayısı | 11 (değişmemeli) | 11 | ✓ |

---

## Apply Dışı Kalanlar (Manuel Karar Bekliyor — Faz2)

| Konu | Açıklama |
|------|----------|
| Halil `departman_id: 1 → 4` | Ayrı onay gerekli |
| `mehmet_kesim` profil oluşturma | Faz2'de ayrı onay ile |
| 11 SAHA_PERSONEL `departman_id` ataması | Faz2'de kişi bazlı onay ile |
| Adım 5 Personel → Usta bağlantıları | Ayrı onay gerekli |

---

## Kapsam Dışı Doğrulama

- ENJ_CORE tabloları: dokunulmadı
- `sistem_kullanici`, `sistem_rol_yetki`: dokunulmadı
- Finans / Planlama: dokunulmadı
- `routes.py`, template dosyaları, `base.html`: dokunulmadı
- `app/mock_data.db`: commit edilmedi

---

## Sonuç

`CORE_PERSONEL_360_FAZ1_APPLY_READONLY_VERIFY` tamamlandı.  
Tüm doğrulamalar geçti. Kapsam dışına çıkılmadı.  
DB commit edilmez — değişiklikler script kaydıyla izlenebilir (`kaynak='018_seed'`).
