# CORE_PERSONEL_360_FAZ2B1_ORG_BASE_DRYRUN

**Tarih:** 2026-06-07  
**Script:** `app/migrations/020_core_personel_360_faz2b1_org_base.py`  
**Mod:** DRY-RUN (apply yapılmadı)  
**DB MD5 (önce/sonra):** `ae850a9a970de2b6d8662fd8ab3eb9a6` / `ae850a9a970de2b6d8662fd8ab3eb9a6` — EŞİT  
**Backup:** `C:\CPS_BACKUPS\mock_data_BEFORE_FAZ2B1_20260607_081655.db`  
**Önceki faz:** CORE_PERSONEL_360_FAZ1 (commit `486865d`)

---

## Mimari Kural

Bu faz yalnızca **organizasyon omurgası** düzenler.  
Personeli tek prosese kilitlemez.

Ayrı tutulan 3 kavram:
- **Organizasyon ilişkisi** → Bu faz kapsamı
- **Yetkinlik / Gelişim** → FAZ2C kapsamı
- **Günlük görev / Geçici görevlendirme** → İleri faz kapsamı

---

## ADIM 1 — departman_master: Yeni Üretim Departmanları

| Kod | Ad | Tür | Sıra | Durum |
|-----|----|-----|------|-------|
| regola | Regola | uretim | 10 | EKLENECEK |
| monta | Monta | uretim | 11 | EKLENECEK |
| temizleme | Temizleme | uretim | 12 | EKLENECEK |
| kesim | Kesim | uretim | 13 | EKLENECEK |

Tüm 4 departman şu an DB'de yok; `--apply` ile idempotent olarak eklenecek.

---

## ADIM 2 — kullanici_profil: Alpay Profili

| Alan | Değer |
|------|-------|
| gercek_ad | Alpay Dülger |
| kullanici_adi | alpay |
| profil_tipi | yonetim |
| departman | Yönetim |
| departman_id | 1 |
| aktif | 1 |
| kaynak | sistem_kullanici |
| kaynak_id | 39 |

`sistem_kullanici.Id=39` doğrulandı. Alpay profili şu an DB'de yok; `--apply` ile eklenecek.

---

## ADIM 3 — kullanici_profil: Usta Ana Departman Güncellemesi

| KP | Ad | Mevcut dept_id | Mevcut dept_ad | Hedef departman | Durum |
|----|----|----------------|----------------|-----------------|-------|
| #2 | Halil | 1 | Yönetim | regola (ADIM 1'den) | GÜNCELLENECEK |
| #14 | Ferhat Usta | 4 | Enjeksiyon | enjeksiyon | ATLANACAK (zaten doğru) |
| #29 | Murat | 4 | Enjeksiyon | monta (ADIM 1'den) | GÜNCELLENECEK |
| #30 | Deniz | 4 | Enjeksiyon | temizleme (ADIM 1'den) | GÜNCELLENECEK |

Önemli: Halil, Murat, Deniz için hedef departmanlar ADIM 1'de oluşturulduktan sonra geçerli id'ler alınır; `--apply` bu sırayı doğru işler.

---

## Apply Özeti

| İşlem | Tablo | Kayıt | Durum |
|-------|-------|-------|-------|
| INSERT | departman_master | regola / Regola | EKLENECEK |
| INSERT | departman_master | monta / Monta | EKLENECEK |
| INSERT | departman_master | temizleme / Temizleme | EKLENECEK |
| INSERT | departman_master | kesim / Kesim | EKLENECEK |
| INSERT | kullanici_profil | Alpay Dülger | EKLENECEK |
| UPDATE | kullanici_profil | KP#2 Halil — dept_id → regola | GÜNCELLENECEK |
| SKIP | kullanici_profil | KP#14 Ferhat — zaten Enjeksiyon | ATLANACAK |
| UPDATE | kullanici_profil | KP#29 Murat — dept_id → monta | GÜNCELLENECEK |
| UPDATE | kullanici_profil | KP#30 Deniz — dept_id → temizleme | GÜNCELLENECEK |

Toplam apply işlemi: **4 INSERT + 1 INSERT + 3 UPDATE = 8 değişiklik**

---

## Kesinlikle Dokunulmayacaklar

| Alan | Durum |
|------|-------|
| kullanici_proses | DOKUNULMAZ |
| usta_personel_iliskisi | DOKUNULMAZ |
| sistem_kullanici / sistem_rol / sistem_rol_yetki | DOKUNULMAZ |
| 11 SAHA_PERSONEL departman/usta ataması | DOKUNULMAZ — panelden yönetilecek |
| Halil / Halil Kıraç merge | DOKUNULMAZ |
| Mehmet Kesim profili | DOKUNULMAZ |
| kullanici_proses proses atamaları | DOKUNULMAZ |
| ENJ_CORE tabloları | DOKUNULMAZ |
| Finans / Planlama | DOKUNULMAZ |
| Template / route dosyaları | DOKUNULMAZ |

---

## Rollback

Backup: `C:\CPS_BACKUPS\mock_data_BEFORE_FAZ2B1_20260607_081655.db`  
Geri alma: bu dosyayı `app/mock_data.db` üzerine kopyala.

---

## Apply İçin Hazırlık Kontrol

- [x] DB backup alındı
- [x] Dry-run çalıştırıldı
- [x] Beklenen değişiklikler listelendi
- [x] DB değişmedi doğrulandı
- [ ] Kullanıcı onayı bekleniyor
- [ ] `--apply` henüz çalıştırılmadı

---

## Onay Sonrası Komut

```text
cd C:\Solariz_CPS_SERVER\app\migrations
python 020_core_personel_360_faz2b1_org_base.py --apply
```
