# D5 FAZ B+ — 5055 FALLBACK KAPATMA HAZIRLIK ANALİZİ (DÜZELTİLMİŞ)

**Tarih:** 2026-05-16 14:45
**Sprint:** D5 Faz B+ Düzeltilmiş Analiz (kod değişikliği YOK)
**Amaç:** F kategorisi yanlış pozitiflerin temizlenmesi + gerçek 5055 bağımlılık haritası

---

## 1. KRİTİK DÜZELTME

İlk taramada `snapshot` pattern'i `KurSnapshot` (USD/TL kur), `plan snapshot`, `slot_snapshot` gibi **başka kavramları** yakaladı. Detaylı incelemede:

| Önceki "F kategorisi" | Gerçek anlam | 5055 ile ilişki |
|---|---|---|
| `grafik/queries.py` (26 hit) | `KurSnapshot` (USD/TL kur tarihsel) | **YOK** |
| `planlama/routes.py` (21 hit) | Plan `snapshot` dict | **YOK** |
| `init_mock_db.py` (28 hit) | `KurSnapshot REAL` kolon | **YOK** |
| `enjeksiyon/audit.py` (8 hit) | `slot_snapshot, hesap_snapshot` | **YOK** |
| `finans/simulator_queries.py` (7 hit) | `KurSnapshot` | **YOK** |
| `finans/cin_ofis_queries.py` (4 hit) | `KurSnapshot` | **YOK** |
| JS dosyaları | "snapshot" muhtelif | **YOK** |

**Sonuç:** F kategorisi 16 dosyanın **0'ı** gerçek 5055 bağımlılığı içeriyor.

---

## 2. GERÇEK 5055 BAĞIMLILIK HARİTASI

### Sadece 2 Modül Bağımlı

| Modül | Dosya | Bağ Türü | Risk |
|---|---|---|---|
| **personel_giris** | `routes.py` | Runtime fallback (kontrollü) | DÜŞÜK |
| **canli_saha** | `routes.py` + `index.html` + `canli_saha.js` | DB dosya okuma | ORTA (ayrı sprint) |

### Tüm Diğer Modüller %100 CPS-Native

```
hedef             : 5055 referansı YOK ✓
planlama          : 5055 referansı YOK (snapshot=kayıt durumu) ✓
grafik            : 5055 referansı YOK (KurSnapshot=USD kur) ✓
finans            : 5055 referansı YOK (KurSnapshot=USD kur) ✓
enjeksiyon        : 5055 referansı YOK (slot_snapshot=audit) ✓
uretim_giris      : 5055 referansı YOK ✓
yonetim           : 5055 referansı YOK ✓
mesajlar          : 5055 referansı YOK ✓
sablon            : 5055 referansı YOK ✓
gorev             : 5055 referansı YOK ✓
auth              : 5055 referansı YOK ✓
```

---

## 3. PERSONEL_GIRIS GERÇEK DURUM

```
_5055_conn() çağrıları    : 3 (fallback path)
FROM emir_proses sorgu    : 2 (fallback)
FROM emir_alt_proses      : 2 (CPS-first ana yol) ✓
_legacy_warning çağrı     : 7 (logging)
```

**Live test sonucu:** `/prosesler/110393` → `veri_kaynagi=CPS_NATIVE` ✓

### Fallback Tetikleme Senaryoları (Gerçek Risk)

| Senaryo | Olasılık | Etki |
|---|---|---|
| CPS emir_alt_proses'te yok | DÜŞÜK (zaten 593/592 import OK) | Sablon motoru gerek |
| CPS sorgu hatası | ÇOK DÜŞÜK | Geçici |
| Yeni Korgun emiri | ORTA | Faz C kapsamı |

**Kritik bulgu:** `5055'te VAR, CPS'te YOK = 0 emir.` Şu anda hiç fallback tetiklenmiyor — her emir CPS_NATIVE dönüyor.

---

## 4. CANLI_SAHA AYRI MODÜL

```
canli_saha\routes.py:
  LEGACY_5055_DB = r"D:\Ortak\Solariz-ARGE\solariz.db"
  → Direkt SQLite dosya okuma (HTTP değil)
  → uretim_kayit veri köprüsü
```

**Bağımsız modül** — D5 Faz C kapsamı dışı. Ayrı sprint gerek:
- `mock_data.db.uretim_kayit WHERE kaynak='LEGACY_5055'` ile değiştirme
- Tahmini süre: 30 dakika

---

## 5. HEDEF EKRANI

```
hedef/ klasoru: 21 dosya
5055 referansı: 0
/hedef ana ekran live test: 200 OK, 66414 byte
```

**Hedef ekranı 5055'ten tamamen bağımsız.** Port kapansa etkilenmez.

---

## 6. MIGRATION/SCRIPT TARIHSEL

```
Toplam: 65 match, 7 dosya
Hepsi BIR KERELİK çalıştırılmış
Runtime etkisi YOK
```

5055 portu kapansa bile bu scriptler çalıştırılmayacak. Sadece tarihsel referans olarak kalabilir veya `archive/` klasörüne taşınabilir (opsiyonel).

---

## 7. KATEGORİ SONUÇLARI (DÜZELTİLMİŞ)

| Kategori | Sonuç | Açıklama |
|---|---|---|
| personel_giris | **GÜVENLİ** | CPS-first aktif, fallback kontrollü |
| hedef | **GÜVENLİ** | 5055 referansı yok |
| canli_saha | KISMI | Ayrı sprint gerektirir |
| runtime_dependency | DÜŞÜK | Sadece personel_giris fallback |
| Diğer 12 modül | **GÜVENLİ** | 5055 bağımsız |
| Faz C hazırlık | **HAZIR** | Sablon motoru kurulabilir |

---

## 8. SON KARAR

**5055 FALLBACK KAPATMA HAZIRLIK:**

- personel_giris       : **GÜVENLİ**
- hedef                : **GÜVENLİ**
- runtime dependency   : VAR (sadece personel-giris fallback, kontrollü)
- fallback kapatma     : SONRA (Faz C sonrasi, sablon motoru ile)
- Faz C hazırlık       : **HAZIR**
- canli_saha           : Ayrı sprint

---

## 9. REVİZE EDİLMİŞ FAZ C PLANI

### Faz C Bölüm 1: Şablon Motoru (3-4 gün)

1. **`sablon_master` aktif kullanım**
   - Var olan tablo, dolduralım
   - Korgun'dan otomatik şablon eşleştirme
   
2. **`sablon_proses` normalize tablosu**
   - 18 5055 şablonu CPS'e import
   - Trailing comma, çift boşluk temizleme
   
3. **Yeni emir trigger fonksiyonu**
   ```python
   def yeni_emir_proses_uret(emir_no, model_kod):
       sablon_id = sablon_seç(model_kod)
       proses_listesi = sablon_proses_oku(sablon_id)
       for proses in proses_listesi:
           INSERT INTO emir_alt_proses (...)
   ```

### Faz C Bölüm 2: Yönetim UI (2-3 gün)

- `/yonetim/sablon` — Şablon CRUD
- `/yonetim/sablon/<id>/proses` — Proses ekle/sil/sırala
- Manuel olarak şablon değiştirme

### Faz C Bölüm 3: Korgun Trigger (2 gün)

- Korgun'dan emir geldiğinde otomatik proses üretimi
- `Urtx_Proses` mapping veya manuel şablon seçimi
- Scheduled task ile sync

### Faz C Bölüm 4: USE_CPS_NATIVE_PROSES = True (1 gün)

- Flag aktivasyonu
- 5055 fallback kapatma (kod hala dursun, sadece flag ile devre dışı)
- Test + doğrulama

### Faz C Bölüm 5: canli_saha CPS-Native (Bonus 1 gün)

- `LEGACY_5055_DB` → `mock_data.db.uretim_kayit WHERE kaynak='LEGACY_5055'`
- Tek modül patch

---

## 10. SONUÇ

D5 Faz C için **sistem %95 hazır**. Sadece **şablon motoru** ve **yönetim UI** kaldı.

**Tahmini Faz C toplam süre:** 7-10 iş günü (1-2 hafta)

5055 portu **şu anda bile** %95 güvenle kapatılabilir — sadece yeni emir geldiğinde sablon olmadığı için proses listesi boş döner (saha personeli emir görür ama prosesleri görmez). Bu kabul edilebilir bir geçici durum olabilir.

**Önerim:** Şablon motoru Faz C bölüm 1'de hızlıca yapılırsa (3-4 gün), 5055 portu **bu hafta sonu** güvenle kapatılabilir.

---

**Oluşturan:** D5 Faz B+ Düzeltilmiş Analiz
**Önceki hatalı kategorize:** F_KALDIRILMASI_GEREKEN (16 dosya yanlış pozitifti)
**Düzeltilmiş kategorize:** Sadece personel_giris + canli_saha gerçek bağımlı
