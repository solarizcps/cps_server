# D5 FAZ B — MIGRATION RAPORU

**Tarih:** 2026-05-16 13:38
**Sprint:** D5 Faz B — emir_alt_proses CPS-Native Migration
**Süre:** Migration + patch + test = ~50 dk
**Sonuç:** ✅ BAŞARILI

---

## 1. ÖZET

5055 emir_proses tablosundaki **2127 kayıt** başarıyla CPS `emir_alt_proses` tablosuna import edildi. routes.py'a **CPS-first patch** uygulandı. Artık `/prosesler/<no>` endpoint'i öncelikli olarak CPS DB'den okuyor; emir CPS'te yoksa 5055 snapshot fallback'i devreye giriyor.

---

## 2. DEĞİŞENLER

### 2.1 DB

| Tablo | Önceki | Sonraki | Notlar |
|---|---|---|---|
| `emir_alt_proses` | 123 | 2250 | +2127 import (kaynak='5055_IMPORT') |
| `emir_alt_proses.legacy_id` | YOK | INTEGER kolon eklendi | ALTER TABLE |
| Index `idx_eap_legacy` | YOK | OLUŞTURULDU | (legacy_id, kaynak) |
| `uretim_kayit` | 1347 | 1347 | DOKUNULMADI ✓ |
| Manuel kayıtlar | 123 | 123 | DOKUNULMADI ✓ |

### 2.2 Dosyalar

| Dosya | Önceki | Sonraki | Hash |
|---|---|---|---|
| `routes.py` | 19965 byte | 21187 byte (+1222) | `41b220d201b0e1f8` |
| `mock_data.db` | 2228 KB | ~2400 KB | Migration sonrası büyüdü |
| Yedek (D5 Faz A) | korunur | korunur | `routes.py.YEDEK_D5_FAZA_20260516_131922` |
| Yedek (D5 Faz B) | yeni | OLUŞTU | `routes.py.YEDEK_D5_FAZB_20260516_134126` |
| DB Yedek | yeni | OLUŞTU | `mock_data.db.YEDEK_FAZB_20260516_133810` |

---

## 3. MIGRATION SONUÇ JSON

```json
{
  "zaman": "2026-05-16 13:38:11",
  "dry_run": false,
  "kaynak_5055": 2127,
  "cps_onceki_toplam": 123,
  "cps_sonraki_toplam": 2250,
  "insert": 2127,
  "skip": 0,
  "error": 0,
  "hata_orani_pct": 0.0,
  "manuel_korundu": true,
  "uretim_kayit_korundu": true,
  "unique_emir_no_cps": 592
}
```

---

## 4. ALAN EŞLEŞTİRME (UYGULANAN)

| 5055 `emir_proses` | CPS `emir_alt_proses` | Dönüşüm |
|---|---|---|
| `id` (INT) | `legacy_id` (INT) | Direkt |
| `emir_no` (INT) | `emir_no` (TEXT) | `str()` cast |
| `proses_adi` (TEXT) | `proses_adi` (TEXT) | `.strip()` + çift boşluk temizle |
| `limit_miktar` (INT) | `hedef_adet` (INT) | `or 0` (NULL → 0) |
| `olusturma` (TEXT) | `created_at` (TEXT) | Direkt |
| — | `aktif` | **1** (aktif görünür) |
| — | `siralama` | 1, 2, 3... her emir için |
| — | `kaynak` | **'5055_IMPORT'** |
| — | `olusturan_id` | 'system_migration' |
| — | `olusturan_ad` | '5055 Import' |
| — | `updated_at` | datetime.now() |

---

## 5. IDEMPOTENT GÜVENLİK

Migration tekrar çalıştırılırsa:
- `legacy_id + kaynak='5055_IMPORT'` ile **duplicate skip**
- INSERT atılmaz, sadece SKIP sayacı artar
- Manuel 123 kayıt **dokunulmaz**
- uretim_kayit **dokunulmaz**

```python
# Duplicate kontrol:
SELECT id FROM emir_alt_proses
 WHERE legacy_id = ? AND kaynak = '5055_IMPORT'
```

---

## 6. ROUTES.PY CPS-FIRST PATCH

### Mantık

```
prosesler(emir_no):
  1. CPS emir_alt_proses oku (WHERE emir_no=? AND aktif=1)
     Veri varsa → veri_kaynagi='CPS_NATIVE', dön
  2. CPS boş → 5055 fallback (Faz A kodu)
     Veri varsa → veri_kaynagi='LEGACY_5055_SNAPSHOT', dön
  3. İkisi de yok → [] + WARNING
```

### Korunan

- 5055 fallback **silinmedi** (sadece 2. sıraya düştü)
- `_legacy_warning` çağrıları korundu
- `_5055_conn()` None kontrolü korundu
- `_cps_conn()` çağrıları korundu
- Frontend JSON yapısı **birebir aynı** (`veri_kaynagi` field değeri değişti)

---

## 7. DAVRANIŞ DEĞİŞİMİ ÖZETİ

| Senaryo | Önceki | Sonraki |
|---|---|---|
| Emir 110393 (5055'te var, import edildi) | LEGACY_5055_SNAPSHOT | **CPS_NATIVE** ✓ |
| Emir 110391 | LEGACY_5055_SNAPSHOT | **CPS_NATIVE** ✓ |
| Yeni emir (henüz CPS'te yok) | LEGACY_5055_SNAPSHOT | LEGACY_5055_SNAPSHOT (fallback) |
| Var olmayan emir | `[]` + WARNING | `[]` + WARNING |
| Manuel sablon emiri (aktif=1) | LEGACY_5055_SNAPSHOT | CPS_NATIVE |
| Saha personeli /kaydet | OK | OK (dokunulmadı) |
| /emir/<no> | OK | OK (dokunulmadı) |
| Login akışı | OK | OK (dokunulmadı) |

---

## 8. SİSTEM KAZANIMLARI

1. **5055 dependency azaldı** — `/prosesler` için artık 5055 öncelik değil
2. **Daha hızlı yanıt** — CPS lokal DB, 5055 snapshot okumak gerekmiyor
3. **Tutarlı veri kaynağı** — CPS-native veri kullanılıyor
4. **5055 kapanış için ZEMİN HAZIR** — sadece yeni emir geldiğinde 5055 fallback
5. **Sablon motoru Faz C için kurulu** — `emir_alt_proses` aktif veri katmanı

---

## 9. KALANGIDIKLAR (FAZ B'DE YAPILMADı)

- ❌ Şablon motoru (Korgun'dan otomatik proses üretimi) → Faz C
- ❌ Yönetim UI'de şablon düzenleme → Faz C
- ❌ canli_saha modülü 5055 → CPS geçişi → Ayrı sprint
- ❌ 5055 fallback tamamen kapatma → Faz C son adım

---

## 10. SONRAKİ ADIM

D5 Faz C için bekleyen işler:
1. Korgun emir gelince **otomatik şablon uygulama motoru**
2. Yönetim UI'de **sablon yönetim ekranı**
3. **5055 fallback'i kapama** (`USE_CPS_NATIVE_PROSES = True`)
4. `canli_saha` modülü CPS-native geçiş

Süre tahmini: 1-2 hafta.

---

**Oluşturan:** D5 Faz B Migration Sprint
**İlgili belgeler:**
- `D5_FAZB_TEST_RAPORU.md`
- `D5_FAZB_ROLLBACK.md`
- `CPS_NATIVE_PROSES_MOTORU_MIGRATION_PLAN.md`
- `D5_FAZA_WARNING_LAYER_RAPORU.md`
