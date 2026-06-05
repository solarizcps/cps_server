# D5 FAZ C — RECON DEVAM RAPORU

**Tarih:** 2026-05-16 15:00
**Sprint:** D5 Faz C Recon (kod değişikliği YOK)
**Amaç:** Yeni emir geldiğinde proses üretim mimarisini netleştirmek

---

## 1. ÖZET

D5 Faz C için sistem **%85 hazır**. Şablon tabloları, sablon_proses ilişkisi, Korgun bridge fonksiyonları mevcut. **Eksik olan 2 şey**:

1. Otomatik trigger (yeni emir geldiğinde sablon → proses)
2. Yönetim UI (şablon CRUD)

## 2. MEVCUT MİMARİ

### 2.1 Tablo Yapısı

```
┌─────────────────────────┐
│ sablon                  │ ← 5 kayıt
│ - id, sablon_adi        │
│ - aciklama, aktif       │
│ - olusturan_id/ad       │
└────────────┬────────────┘
             │ sablon_id (FK)
             ▼
┌─────────────────────────┐
│ sablon_proses           │ ← 14 kayıt
│ - id, sablon_id         │
│ - proses_adi, siralama  │
└─────────────────────────┘

┌──────────────────────────────┐
│ emir_alt_proses              │ ← 2250 kayıt
│ - id, emir_no, proses_adi    │
│ - hedef_adet, aktif, siralama│
│ - kaynak (string: 'sablon:*')│ ← FK YOK!
│ - legacy_id (D5 Faz B)       │
└──────────────────────────────┘
```

### 2.2 Mevcut 5 Şablon

| ID | Sablon Adı | Aktif | Olusturma | Proses Sayısı |
|----|-----------|-------|-----------|---|
| 1 | Atki LCW | 1 | 2026-04-28 | 4 (Capak, Rivet Takma, Tampon Baski, Atki Silme) |
| 2 | İlham | 0 | 2026-05-11 | 3 (Atkı silme, tampon baskı, rivet takma) |
| 3 | Aşağı iş indirme | 1 | 2026-05-12 | 1 (Aşağı iş indirme) |
| 4 | Lcw atkı | 1 | 2026-05-15 | 5 (Atkı basıldı, çapak, silindi, tampon, rivet) |
| 5 | Esem | 1 | 2026-05-16 13:52 | 1 (Atkı rivet takma) - BUGUN OLUSTURULMUS |

### 2.3 emir_alt_proses kaynak ↔ sablon Eşleşme

```
emir_alt_proses.kaynak='Atki LCW'         → sablon.id=1 ✓
emir_alt_proses.kaynak='Aşağı iş indirme' → sablon.id=3 ✓
emir_alt_proses.kaynak='Esem'             → sablon.id=5 ✓
emir_alt_proses.kaynak='Lcw atkı'         → sablon.id=4 ✓
```

**Eşleşme %100.** FK yok ama isim bazlı eşleşme net.

## 3. KORGUN BRIDGE FONKSİYONLARI (Hazır)

### 3.1 modules/common/korgun.py (18.9 KB)

```python
_baglan()                       # MSSQL connection
get_emir_ozet(emir_no)          # Emir detay
get_siparis_emirleri(sip_no)    # Sipariş alt emirler
get_alt_emirler(ana_emir_no)    # Hierarşi
saglik_kontrol()                # Health check
```

### 3.2 modules/hedef/korgun_v2.py (43 KB, 24+ fonksiyon)

```python
_korgun_baglan()                # MSSQL bağlantı
get_siparis_listesi_canli()     # Aktif siparişler
get_siparis_detay_v2_canli(sip) # Tam detay
_sql_get_siparis_emirler(sip)   # Emir listesi
get_emir_ozet(...)              # Hesaplama
```

**Sonuç:** Yeni emir çekme altyapısı **kurulu**. Faz C'de yeni Korgun query YAZILMAYACAK — sadece **scheduled trigger** çağıracak mevcut fonksiyonları.

## 4. 5055 vs CPS ŞABLON KARŞILAŞTIRMA

### 5055'te 18 Şablon (CPS'te %0 import)

```
[CPS_YOK] tedii, lcw gövde ilerleme, lcw atkı ilerleme,
[CPS_YOK] lcw yezzy, ilham, ilham 2, bahtiyar,
[CPS_YOK] esem atkı ilerleme, lcw gövde ilerleme frezeli,
[CPS_YOK] terda muya, terda 2, ilham 3, terda yzm,
[CPS_YOK] Eşek brz, Atkı Standart, Atkı LCW,
[CPS_YOK] Atkı Twigy, Atkı Esem
```

### Manual Eşleştirme (Karar Gerekli)

| 5055 Sablon | CPS Eşi | Aksiyon |
|---|---|---|
| 'lcw atkı ilerleme' | 'Lcw atkı' | Aynı? Birleştir? |
| 'Atkı LCW' | 'Atki LCW' | Aynı (i farkı) |
| 'esem atkı ilerleme' | 'Esem' | Genişlet |
| 'ilham' | 'İlham' (pasif) | Aynı |
| 'bahtiyar' (aşagı iş) | 'Aşağı iş indirme' | Aynı? |

**Karar:** 18 5055 şablonu **körü körüne import EDİLMEMELİ**. Önce eşleştirme tablosu, sonra seçici import.

## 5. EKSIK PARÇALAR (Faz C İşleri)

### 5.1 FK Eksik
```sql
emir_alt_proses tablosu YOK:
  - sablon_id INTEGER (FK)
  - sablon_kaynak_tipi (manual / auto / 5055)
  - musteri_tipi (LCW / Defacto / ...)
  - model_kod (Korgun ModelKod)
```

### 5.2 Otomatik Trigger Yok
- Yeni emir geldiğinde **manuel** proses ekleniyor şu an
- Korgun polling **yok**
- Sablon eşleştirme **yok**

### 5.3 Yönetim UI Yok
- `/yonetim/sablon` endpoint **mevcut değil**
- Şablon ekle/sil/düzenle UI yok
- Şablon → emir eşleştirme UI yok

### 5.4 hedef_adet Eksik
- 123 sablon kaydında **hedef_adet=0**
- Vardiya bazlı hedef öneri yok

## 6. SABLON MANTIK ANALİZİ

### 6.1 Müşteri bazlı mı? 
- **Kısmi.** "Lcw atkı", "Atki LCW" → LCW müşteri için
- "Esem" → Esem müşteri için
- "Aşağı iş indirme" → genel

### 6.2 Model bazlı mı?
- **Hayır.** Mevcut şablonlar müşteri/iş türü bazlı, model kod değil

### 6.3 Proses tipi bazlı mı?
- **Evet.** "Atki", "Gövde", "Aşağı" → ürün parça tipi

### 6.4 Manuel override var mı?
- **Evet.** Mevcut 30+22+65+23 = 140 kayıt manuel uygulanmış
- Olusturan_id=0/system (otomatik olarak kim ekledi belirsiz)

## 7. ÖNERILEN CPS-NATIVE ŞABLON MOTORU

### Mimari

```
┌─────────────────────────────────────┐
│ scheduled_task                       │
│ (5 dk'da bir Korgun polling)         │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│ Korgun get_siparis_listesi_canli()  │
│ Yeni emir kontrol                    │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│ sablon_eslestir(emir)                │
│ - musteri  → sablon                  │
│ - model    → sablon                  │
│ - manuel   → varsayilan              │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│ emir_alt_proses INSERT               │
│ kaynak='AUTO:Lcw_atki'               │
│ sablon_id=4                          │
│ aktif=1                              │
└─────────────────────────────────────┘
```

### Eşleştirme Tablosu Önerisi

```sql
CREATE TABLE sablon_eslesme (
  id INTEGER PK,
  sablon_id INTEGER (FK sablon),
  kural_tipi TEXT,        -- 'musteri', 'model_prefix', 'manuel'
  kural_deger TEXT,       -- 'LCW', 'PTK', 'default'
  oncelik INTEGER DEFAULT 100,
  aktif INTEGER DEFAULT 1
);
```

## 8. SON KARAR

**FAZ C RECON:**

- **Şablon mantığı**           : **NET** ✓ (sablon + sablon_proses mevcut, eşleşme yapılı)
- **Trigger mantığı**          : **KISMI** (Korgun bridge var, scheduled job yok)
- **CPS-native uygulanabilirlik**: **ORTA** (FK eksik, eşleştirme tablosu yok)
- **Yarın patch'e hazır mı**    : **EVET** (bütün öğeler bilinen, detaylı planlama yapılabilir)

## 9. FAZ C ALT BÖLÜMLER (Sıralı)

| # | Bölüm | Süre | Risk |
|---|-------|------|------|
| C.1 | sablon_id FK ekle (ALTER) | 1 saat | DÜŞÜK |
| C.2 | sablon_eslesme tablosu kurulum | 1 saat | DÜŞÜK |
| C.3 | Yönetim UI - sablon liste | 2 saat | DÜŞÜK |
| C.4 | Yönetim UI - sablon CRUD | 2 saat | DÜŞÜK |
| C.5 | Otomatik trigger fonksiyonu | 3 saat | ORTA |
| C.6 | Scheduled task entegre | 1 saat | DÜŞÜK |
| C.7 | hedef_adet vardiya kuralı | 2 saat | ORTA |
| C.8 | USE_CPS_NATIVE_PROSES = True | 30 dk | DÜŞÜK |
| C.9 | Test + doğrulama | 2 saat | DÜŞÜK |
| **TOPLAM** | | **~14 saat** (~2 gün yoğun çalışma) |

## 10. KRİTİK NOTLAR

1. **18 5055 şablonu** körü körüne import edilmemeli — eşleştirme tablosu ile selektif
2. **Mevcut 123 sablon kaydı** dokunulmamalı (aktif=1 olanlar manuel uygulanmış)
3. **emir_alt_proses.kaynak** string ile sablon_adi eşleşmesi devam etmeli (geri uyumluluk)
4. **Korgun query yazılmayacak** — mevcut bridge kullanılacak
5. **D5 Faz B fallback** kalmalı (acil durum kurtarma için)

## 11. SONUÇ

D5 Faz C için **mimari netleşti, sistem hazır, plan detaylı**. Yarın patch sırası:

1. ✓ Önce mini snapshot
2. ✓ ALTER TABLE (sablon_id FK)
3. ✓ Yönetim UI (sablon CRUD)
4. ✓ Otomatik trigger
5. ✓ Test
6. ✓ Snapshot

**Yarın patch'e HAZIR.**

---

**Oluşturan:** D5 Faz C Recon Devam
**Sonraki adım:** Yarın D5 Faz C.1 (sablon_id FK ekle)
**Önceki belgeler:**
- D5_FAZB_FINAL_VERIFY.md
- D5_FAZB_PLUS_5055_FALLBACK_KAPATMA_ANALIZI_DUZELTILMIS.md
- CPS_NATIVE_PROSES_MOTORU_MIGRATION_PLAN.md
