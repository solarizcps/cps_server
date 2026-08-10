# MO_AJANDA_LOCK_MANIFEST

## LOCK NAME

MO-GORUSME-AJANDA-CARI360-SYNC-LOCK

## Tarih

2026-08-10

## Gerçek E2E Kanıtı

Kullanıcı: Erhan  
Aksiyon: Ana sayfa → +Görüşme → bugün tarihli kayıt  
Cari: SEHA AYAKKABI VE TEKSTİL SAN. TİC. A.Ş.  
Görüşme tarihi: 2026-08-10 12:58

Sonuçlar:
- Ajanda: görüşme GERCEKLESTI olarak göründü, Tamamlanan sayısı arttı, duplicate oluşmadı
- Cari360: Son Görüşme 2026-08-10 12:58, Görüşmeler sekmesinde Erhan görüşmesi tek satır

## Canonical Kaynaklar

| Tablo | Anahtar Alan |
|---|---|
| `musteri_operasyon_gorusme` | `id`, `cari_id`, `kullanici_id`, `gorusme_tarihi` |
| `musteri_operasyon_ajanda` | `gorusme_id`, `durum`, `cari_id`, `kullanici_id`, `plan_tarihi` |

## İş Kuralları (Kilitli)

1. Gerçek görüşme kaydedildiğinde Ajanda geçmişinde görünmeli.
2. Aynı gün uygun PLANLANDI kayıt varsa: mevcut kayıt GERCEKLESTI olmalı, `gorusme_id` set edilmeli, yeni duplicate satır oluşmamalı.
3. Uygun plan yoksa: tek ADHOC GERCEKLESTI Ajanda kaydı oluşmalı.
4. Aynı görüşme Cari360'da tek kez görünmeli.
5. Geçmiş kayıt silinmemeli.
6. IPTAL plan yeniden kullanılmamalı.
7. Explicit `ajanda_id` mevcut flow korunmalı.
8. Erhan diğer aksiyonları ve Mehmet akışları bozulmamalı.

## Eşleştirme Kuralı

```
kullanici_id = gorusmeyi yapan kullanici
cari_id      = gorusulen cari
DATE(plan_tarihi) = DATE(gorusme_tarihi)
durum        = 'PLANLANDI'
aktif        = 1
ORDER BY plan_tarihi ASC LIMIT 1
```

DB kanıtı: `MULTI_PLAN_SAME_DAY = 0` (2026-08-10 itibarıyla)

## Değişen Dosyalar

| Dosya | Değişiklik |
|---|---|
| `app/modules/nexgen/mo_ajanda_service.py` | `gercek_gorusmeyi_ajandaya_bagla()` helper eklendi |
| `app/modules/nexgen/musteri_temsilcisi_talep_service.py` | `ajanda_id` yoksa canonical sync çağrısı eklendi |
| `app/modules/nexgen/mo_gorusme_service.py` | Gelecek tarihli görüşme write reject + read filter (önceki LOCK) |
| `app/modules/nexgen/cari360_timeline_service.py` | Gelecek tarihli görüşme timeline filtresi (önceki LOCK) |

## Regression Test Dosyaları

| Dosya | Test Sayısı | Kapsam |
|---|---|---|
| `tests/nexgen/test_ajanda_canonical_sync.py` | 9 | Sync LOCK (A-I) |
| `tests/nexgen/test_mo_gorusme_future_tarih_lock.py` | 7 | Future-date write/read LOCK |

## Son Test Sonucu

```
131 passed / 0 failed
Python 3.13.13, pytest 9.1.1
2026-08-10
```

## Park Edilen Sonraki Konu

Görüşme detayında ticari bilgi eksikliği (fiyat, miktar, ürün vb.)  
Bu LOCK kapsamı değildir. Ayrı görev olarak devam edilecek.
