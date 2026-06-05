# D6.0 - PROSES NORMALIZASYON MASTER PLAN

**Tarih:** 18.05.2026 10:44
**Tip:** RECON + ANALIZ + TASARIM - patch yok, DB degisikligi yok
**Amac:** Sahanin 47 proses_adi varyantini, AI/sinyal/darbogaz icin tek dile cevirmek

---

## 1. YONETICI OZETI

47 farklı proses_adi var (uretim_kayit + emir_alt_proses birlesim). proses_kategori
tablosu 11 satir Korgun standardi tutuyor (Kesim/Saya/Enjeksiyon/Monta vb) ama
**saha bunlari kullanmiyor**. Saha operasyonel detay yaziyor (silme/rivet/capak/baski).

Sorun: AI 'darbogaz' veya 'gec emir' diyebilmek icin **iki katmani birlestirmek** sart:
- Korgun proses_kod (02, 26, 30...) - emir akisi seviyesi
- Saha proses_adi (atki silme, govde basildi...) - operasyon seviyesi

Çözüm: **proses_alias tablosu** + mapping kurallari + admin UI ile manuel karar.

---

## 2. VERI ENVANTERI

### 2.1 Sahip oldugumuz veri katmanlari

| Katman | Veri | Yapi |
|--------|------|------|
| Korgun proses_M | ~10 standart kod | Sabit referans (Kesim=02, Enjeksiyon=26...) |
| proses_kategori | 11 satir | ATKI/GOVDE/MAMUL kategorilenmis, standart_saniye var |
| uretim_kayit | 1383 satir, 32 distinct | Saha kaydi (proses_kodu %99 NULL) |
| emir_alt_proses | 2282 satir, 39 distinct | Sablon/import/manuel kaynak (kod yok) |

### 2.2 47 varyantlik populasyon

**6 net typo grubu (auto-map ile cozulur):**
1. asagi is indirme: 'Aşağı iş indirme', 'aşagı iş indirme'
2. atki rivet takma: 4 varyant aksan/buyuk
3. atki silme: 3 varyant
4. capak: 'Capak', 'Çapak'
5. govde basildi: 2 varyant
6. tampon baski: 3 varyant

**12 saha gercek operasyon (gercekten farkli operasyonlar):**
- atkı silme/silindi (1166 kayit, 32% saha aktivitesi)
- gövde basıldı (266 kayit, 7%)
- atkı çapak alındı sayıldı (171 kayit, 5%)
- gövde sayıldı (124 kayit, 4%)
- gövde çapak alındı (115 kayit, 3%)
- gövde aşağıya indi (243 kayit)
- Aşağı iş indirme (140 kayit)
- Rivet Takma + atkı rivet takıldı (267 kayit)
- Tampon Baskı + tampon basıldı (218 kayit)
- atkı paketlemeye teslim edildi (96 kayit)
- atkı tampon basıldı (96 kayit)
- gövde toka takıldı (27 kayit)

**3 compound (kararsiz, manuel inceleme):**
- 'atkı basıldı capak alındı sayıldı' (44 kayit) - atki capak + sayım birlesik?
- 'atkı çapak alındı sayıldı' (171 kayit) - aynisi
- 'gövde basıldı.gövde çapak alındı.gövde sayım yapıldı. gövde montaya indirildi' (31 kayit) - 4 islem tek satirda

**14 dusuk frekansli (5'ten az emir):**
- boylama, gövde freze yapıldı, gövde toka takıldı, gövde tampon baskı yapıldı, vb.

### 2.3 NULL/eksik

- proses_kodu NULL: %99 (1375/1383) - kritik eksik
- proses_adi NULL: 0, bos: 25 (%1.8)
- CPS_CANLI sahasi 14 distinct varyant kullanır (sınırlı dropdown var sanki)

---

## 3. STANDART EVREN ONERISI

### 3.1 Mevcut proses_kategori (11)

Korgun standardi, ATKI/GOVDE/MAMUL ile etiketli:
- 02 Kesim (GOVDE)
- 15 Saya (GOVDE)
- 18 Saya Kontrol (GOVDE)
- 26 Enjeksiyon (ATKI, std=35sn)
- 28 Monta Baslayacak (MAMUL)
- 30 Monta (MAMUL)
- 32 Mekval (MAMUL)
- 35 Temizleme (MAMUL)
- 42 Saya Hazir (GOVDE)
- 50 Eva Hazir (ATKI)
- 60 capak (ATKI, std=30sn)

### 3.2 ONERILEN GENISLETME (saha gercegine uygun)

Mevcut 11'e ek ~10 saha-spesifik kod onerilir:

| Onerilen kod | Standart ad | Kategori | std_saniye |
|--------------|-------------|----------|------------|
| 70 | Atki Silme | ATKI | TBD |
| 71 | Atki Rivet Takma | ATKI | TBD |
| 72 | Atki Tampon Baski | ATKI | TBD |
| 73 | Atki Capak/Sayim | ATKI | TBD (compound) |
| 74 | Atki Paketleme | ATKI | TBD |
| 80 | Govde Baski | GOVDE | TBD |
| 81 | Govde Sayim | GOVDE | TBD |
| 82 | Govde Capak | GOVDE | TBD |
| 83 | Govde Silme | GOVDE | TBD |
| 84 | Govde Indirme | GOVDE | TBD |
| 85 | Govde Toka/Boy/Freze | GOVDE | TBD |
| 90 | Asagi Is Indirme | TRANSFER | TBD |
| 91 | Paketleme | MAMUL | TBD |
| 92 | Boylama | GOVDE | TBD |

Toplam: **11 mevcut + 13 yeni = ~24 standart proses_kod**.

NOT: Bu kodlar Korgun'da olmayabilir. Sadece **CPS sahasi icin local standardi** olusturulur. Korgun bagi gerekirse Korgun.proses_kod ile JOIN edilir.

---

## 4. MAPPING ONERISI (47 -> 24 standart)

### 4.1 KESIN AUTO-MAP (6 typo grubu)

| Saha varyantlari | Standart |
|------------------|----------|
| 'Aşağı iş indirme', 'aşagı iş indirme' | 90 Asagi Is Indirme |
| 'Atkı rivet takma', 'atkı Rivet Takma', 'atkı rivet takma' | 71 Atki Rivet Takma |
| 'Atki Silme', 'Atkı Silme', 'atkı silme' | 70 Atki Silme |
| 'Capak', 'Çapak' (alone) | 60 capak |
| 'Gövde basıldı', 'gövde basıldı' | 80 Govde Baski |
| 'Tampon Baski', 'Tampon Baskı', 'tampon baskı' | 72 Atki Tampon Baski |

### 4.2 GUVENLI MAP (12 saha gercek operasyon)

| Saha | Standart |
|------|----------|
| 'atkı silindi' | 70 Atki Silme |
| 'gövde sayıldı' | 81 Govde Sayim |
| 'gövde çapak alındı' | 82 Govde Capak |
| 'gövde aşagıya indi' | 84 Govde Indirme |
| 'atkı rivet takıldı' | 71 Atki Rivet Takma |
| 'atkı tampon basıldı' | 72 Atki Tampon Baski |
| 'tampon basıldı' | 72 Atki Tampon Baski (varsayim ATKI) |
| 'atkı paketlemeye teslim edildi' | 74 Atki Paketleme |
| 'Rivet Takma' (kaynak ATKI tahmin) | 71 Atki Rivet Takma |
| 'silme' (alone, ATKI tahmin) | 70 Atki Silme |
| 'gövde silindi' | 83 Govde Silme |
| 'gövde freze yapıldı' | 85 Govde Toka/Boy/Freze |

### 4.3 RISKLI - MANUEL KARAR (5 compound)

| Saha | Sorun | Onerim |
|------|-------|--------|
| 'atkı basıldı capak alındı sayıldı' | 3 islem birlesik | 73 Atki Capak/Sayim (compound olarak ayri kod) |
| 'atkı çapak alındı sayıldı' | 2 islem birlesik | 73 Atki Capak/Sayim |
| 'gövde basıldı.gövde çapak alındı.gövde sayım yapıldı. gövde montaya indirildi' | 4 islem | **MANUEL INCELE** - kayit boluneblir |
| 'gövde tampon baskı yapıldı' / 'gövde tambon basıldı' | govde + tampon | Yeni kod gerek (86 Govde Tampon)? |
| 'Atki Takma', 'Capak Alma' | manuel emir_alt_proses | Manuel kullanim, ozel sablon? |

### 4.4 DUSUK FREKANSLI (1-5 emir, dusuk oncelik)

- boylama, gövde toka takıldı, gövde boy kontrolü, gövde freze, paketleme yapılı (typo)
- Bunlar tek tek karar verilir veya 'DIGER (99)' altinda toplanir

---

## 5. RISKLI ESLESMELER (manuel karar bekleyen)

### Risk 1: "Tampon basıldı" alone (43 kayit)
- ATKI mı GOVDE mı? Hangi parcaya?
- **Karar onerim:** model_kod veya emir bagina bakilmali. Default ATKI kabul edilebilir cunku 'gövde tampon...' ayri.

### Risk 2: "Rivet Takma" alone (75 kayit, manuel + sablon)
- Atki rivet midir, govde rivet midir?
- **Karar:** Solariz EVA terlik uretiminde rivet hep ATKI'ya. Atki tampon ile baglandi.

### Risk 3: "silme" alone (5 kayit)
- atki mi govde mi?
- **Karar:** Atki tahmin (atkı silindi 1166 vs gövde silindi 19).

### Risk 4: Compound 'gövde basıldı.gövde çapak alındı.gövde sayım yapıldı. gövde montaya indirildi'
- 31 kayit, tek satirda 4 islem
- **Karar:** Kayitlari **bolme YOK** (audit korunur). Bunlar **'COMPOUND_MULTI' flag**li kalsin, AI tek kayit gibi gormesin.

### Risk 5: '' bos proses_adi (25 kayit)
- Sahanin proses yazmadigi durum
- **Karar:** Eski LEGACY_5055 import'ta olabilir. AI hesabina dahil etme.

---

## 6. BACKFILL STRATEJISI

### Onerilen yaklasim: KARMA (lazy + admin UI)

**Adim 1: proses_alias tablosu olustur (yeni tablo)**
\\\sql
CREATE TABLE proses_alias (
  id INTEGER PRIMARY KEY,
  saha_adi TEXT UNIQUE NOT NULL,     -- 'atkı silindi'
  standart_kod TEXT NOT NULL,         -- '70'
  standart_adi TEXT NOT NULL,         -- 'Atki Silme'
  kategori TEXT,                       -- 'ATKI'
  guven_skoru INTEGER,                 -- 0-100 (100=kesin, 50=tahmin)
  karar_kaynak TEXT,                   -- 'auto_typo' | 'auto_keyword' | 'manuel'
  olusturma TEXT DEFAULT CURRENT_TIMESTAMP,
  onayli_mi INTEGER DEFAULT 0          -- admin onayi
);
\\\

**Adim 2: 6 typo grubu otomatik fill (guven=100, onayli=1)**

**Adim 3: 12 saha operasyon (guven=80, onayli=0 - admin onayi bekler)**

**Adim 4: Admin UI - 5 riskli + bos kalan icin manuel karar**

**Adim 5: Backfill yontemi:**
- **Yeni kayit:** uretim_kayit/emir_alt_proses INSERT'inde trigger -> proses_alias join -> proses_kodu otomatik doldurulur
- **Eski kayit:** TEK BATCH, gecmis 1383 kayit icin UPDATE...JOIN (idempotent script)
- **Lazy hook degil:** Veri buyumemis (1383 satir), batch hizli

### Onerilen sira

1. proses_alias migration
2. Auto-mapping seed (6 typo grup)
3. Admin UI - 12 saha operasyon onay
4. Batch backfill (UPDATE uretim_kayit SET proses_kodu)
5. Yeni kayit hook'u (INSERT trigger veya app-level)

---

## 7. AI ETKISI - BU MAPPING SONRASI MUMKUN OLAN ANALIZLER

### Yeni analizler

**A. Darbogaz tespiti (proses_kodu bazli)**
- "Atki silme bu hafta 30% sapmalı geri kaldı"
- "Govde basildi 4 gun durdu"
- proses_kategori.standart_saniye ile bencmark

**B. Personel hizi (gerçek karsilastirma)**
- "Najova atki silmede ort 451 cift, bu hafta 280 = %38 dusus"
- proses_kod sabit -> kisi/proses/hafta tablosu cikar

**C. Termin riski (proses bazli)**
- "Bu emir Govde Baski adiminda kaldi, termine 2 gun var"
- Korgun TerTarih + CPS proses_kod cross check

**D. Sablon onerisi (otomatik)**
- "Yeni acilan 111020 (M, Sahin Taban) icin standart Atki LCW + Govde Standart sablonu"
- sablon_proses'i proses_kod bazli yeniden yaz

**E. Hatali eslesme tespiti**
- "Bu emir M tipi ama govde basildi kaydi yok, mantik hatasi"
- AI flag at

**F. Vardiya analizi (saatlik)**
- "Gece vardiya gövde sayım %20 az"
- saat alani + proses_kod ile

**G. Operasyon dagilimi**
- "Bu hafta zamanin %40i atki silme, %30u rivet, %20si capak..."
- Frequency analysis

**H. Halil iş yuku (onay)**
- "Halil bugun atki silme'de 50 kayit onayladi"
- usta_ad x proses_kod

---

## 8. TEKNIK MIMARI ONERISI

### 8.1 Onerilen yapi

**proses_alias tablosu** (yeni)
- saha varyantlarini standart_kod'a baglar
- guven skoru + onayli flag ile audit
- Admin UI ile yonetilir

**proses_kategori tablosu** (mevcut, genisletilir)
- ~24 standart proses_kod tutar
- standart_saniye, kategori, sira gibi metric

**Runtime davranis:**
\\\
INSERT uretim_kayit / emir_alt_proses:
  IF proses_kodu EMPTY:
    SELECT standart_kod FROM proses_alias WHERE saha_adi=NEW.proses_adi
    IF found: NEW.proses_kodu = standart_kod
    IF not found: log warning + insert anyway (manuel onay icin)
\\\

### 8.2 JSON konfig mi tablo mu?

| Yontem | Arti | Eksi |
|--------|------|------|
| JSON konfig dosyasi | Kolay deploy, version control | Adminin git pull yapması gerek, dinamik degisiklik zor |
| Veritabani tablosu | Admin UI ile dinamik, hot reload | Schema migration + UI gerek |
| Runtime cache | Hizli | Senkron problemi |

**Onerim:** **Tablo + Runtime cache (in-memory dict)**. Admin UI ile değisim -> cache invalidate.

### 8.3 Admin UI gerekli mi?

**EVET.** Sebepler:
- Yeni saha varyantlari her gun gelebilir (yeni personel yeni typo)
- Risk 1-5 manuel karar bekleyen alanlar var
- Halil/admin "evet bu Atki Silme'dir" diyebilmeli
- Audit kaydi (kim ne zaman onayladi)

**MVP UI:**
- Listele: tum proses_alias kayitlari (guven < 100 olanlar uyari)
- Yeni saha_adi geldiginde: dropdown ile standart_kod sec, onayla
- Toplu onay: 'tum auto_typo onayli yap' butonu

---

## 9. D6.0 HIZLI KAZANIM PLANI

### MVP - 1 gun (8 saat)
- proses_alias migration + 6 typo seed (auto_typo, onayli=1)
- 12 saha operasyon seed (auto_keyword, onayli=0)
- Hizli backfill script (1383 satir UPDATE)
- **Cikti:** AI temel sorgulara cevap verir (auto_typo kapsamiyla)

### TAM SISTEM - 2-3 gun
- Admin UI (yonetim/proses_normalize)
- 5 riskli alan manuel onay
- INSERT hook (yeni kayitlar otomatik)
- Saha test - Halil onayi
- **Cikti:** %95+ kayit dogru proses_kodu ile, AI tam analizler

### TAHMINI SURE: 3 gun (sprint olarak D6.0.1 ve D6.0.2)

---

## 10. OPERASYON AI ICIN KAZANIM

### Bu is bitince CPS hangi seviyeye cikar

**ESKI seviye (su an, 18.05.2026 10:50):**
- Saha 47 varyant yaziyor, AI bunlari ayni gormez
- "Atki Silme yavasladi" diyemez cunku Atki Silme'nin ne oldugu belirsiz
- proses_kategori 11 standart var ama saha kullanmiyor
- Korgun bagi koparmis (proses_kodu %99 NULL)

**YENI seviye (D6.0 sonrasi, 21.05.2026 hedef):**
- Tum saha kayitlari proses_kodu dolu (%99+)
- 24 standart proses_kod evreni
- AI 'Govde Baski darbogazi var' diyebilir
- AI 'Najova ortalamasinin %38 altinda' diyebilir
- Termin riski hesaplanabilir (Korgun TerTarih + standart_saniye + kalan_kayit)
- Vardiya/saat karsilastirmasi mumkun
- Halil onerileri kanit ile gosterir
- Otomatik sablon onerisi (gecmis sablon eslesmeleri analiz edilir)

### Sonraki adimlar (D6.0 -> D6.1)

- D6.0 mapping bitince -> D6.1 sinyal motoru (durgun emir tespiti) calisir
- D6.2 hiz sapmasi (benchmark + standart_saniye)
- D6.3 rule_engine (auto oneri uretmeye baslar)

### Operasyon AI'nin "Halil burada yavas" diyebilmesi icin

Su an: HAYIR diyemez (proses adi karisik)
D6.0 bittiginde: KISMEN diyebilir (kategori + kayit sayisi bazli)
D6.0 + D6.2 bittiginde: TAM diyebilir (standart_saniye benchmark ile)

---

## 11. SONUC

### Hazirsiz adimlar (D6.0 baslayabilmek icin)

- proses_kategori'ye 13 yeni satir eklenmeli (saha standartlari)
- proses_alias tablosu yaratilmali
- Adem'in onayi: mapping kararlari (4.1, 4.2 onaylayalim mi)
- 4.3 ve 5'teki riskli alanlar icin Adem ve Halil tartismalı

### Tahmini cikti
- 3 gun calisma sonunda %95+ kayit dogru proses_kodu
- AI temel sinyalleri verebilir
- D6.1 (sinyaller) hemen baslayabilir

### Kritik karar
**Compound'lar (atkı çapak alındı sayıldı tipi 175 kayit)** - bolmek mi tek kod mu? Bu cevap sonrasi mapping kararlari hizlanir.