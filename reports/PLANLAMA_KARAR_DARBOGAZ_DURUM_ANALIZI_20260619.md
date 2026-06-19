# CPS Planlama / Karar Masası / Darboğaz Durum Analizi
Tarih: 19.06.2026
Yazar: AI Analiz (Cursor Sonnet 4.6)
Amaç: İK geliştirmesine ara verilirken Planlama/Hedef/Darboğaz durumu net belgelenmesi.

---

## 1. Genel Sonuç

### Çalışan Parçalar
- Korgun SQL bağlantısı canlı (mssql → `korgun_v2.py`)
- Sipariş Takip ekranı: sipariş no ile arama, emir/proses ağaç görünümü
- Hedef paneli: Korgun'dan emir listesi, hafızaya alma, proses bazlı görünüm
- Şablon sistemi: proses şablonu tanımlama, emirlere eşleştirme, tetikleme
- Üretim girişi (personel_giris + uretim_giris): usta/personel veri girişi
- Onay akışı: personelin girdiği üretimi planlama onaylıyor
- Operasyon raporu: kalıp/makine bazlı rapor ekranı
- Plan-Darboğaz API endpoint'i (hesaplıyor ama UI bağlı değil)

### Yarım Kalan Parçalar
- Darboğaz uyarı bandı: JS kodu yazılmış, `return;` ile kapatılmış (FAZ 2B kararı)
- Karar Masası: ekran var, route var, **veri kaynağı MOCK** (`_km_mock_satirlar()`)
- `hedef_plan_darbogaz` endpoint'i: çalışır durumda ama Karar Masası ekranına bağlı değil
- `siparis_darbogaz` tablosu: `darbogaz.py` motoru bunu güncelliyor ama ekranda gösterilmiyor
- Korgun miktar doğrulama: `hedef_dogrulama` endpoint'i var, `eski_bekleyen` + `duplicate` + `gecersiz_proses` kontrolü yapıyor ama Hedef Paneli içinde entegre değil
- `FINAL_PROSES_MAP` boş → bitmiş mamul hesabı her zaman 0 döner
- `plan_v2.html` sadece 2134 byte — iskelet halinde

### Hiç Bağlanmamış Parçalar
- Personel performansı ← Hedef üretim verisi olmadan geliştirme yasak
- Karar Masası → Usta otomatik iş atama (endpoint var: `/karar-masasi/ustaya-gonder`, UI yok)
- Darboğaz → SMS/bildirim tetikleme
- Planlama → Excel toplantı planı yerine geçme

---

## 2. Menü ve Ekran Haritası

| Ekran | URL | Dosya | Durum | Not |
|---|---|---|---|---|
| Hedef Paneli | `/hedef/` | `hedef/index.html` (20 KB) + `hedef.js` (329 KB) | **Aktif** | Menü: Üretim grubu |
| Şablon / Proses | `/hedef/sablon` | `hedef/sablon.html` (16 KB) | **Aktif** | Menü: Üretim grubu |
| Sipariş Takip | `/hedef/siparis-takip` | `hedef/index.html` içinde | **Aktif** | Korgun canlı veri |
| Plan Detay | `/hedef/plan-detay/<emir_no>` | — | **Aktif** | Emir bazlı görünüm |
| Sapma Analizi | `/hedef/sapma` | — | **Aktif** | Menü: Üretim grubu |
| Proses Takip | `/planlama/proses-takip` | `planlama/proses_takip.html` (8 KB) | **Aktif** | Menü: Planlama grubu |
| Karar Masası | `/planlama/karar-masasi` | `planlama/karar_masasi.html` (13 KB) | **MOCK** | Gerçek veri yok |
| Operasyon Raporu | `/planlama/operasyon-raporu` | `planlama/operasyon_raporu.html` (10 KB) | **Aktif** | Menü: Planlama grubu |
| Kalıp Görünüm | `/planlama/kalip-gorunum` | — | **Belirsiz** | Menüde yok |
| Hedef (Planlama menüsünde) | `/hedef/` | — | **Aktif** | Planlama grubuna da eklendi |
| Plan Ekranı | `/uretim-yonetim/plan` | `uretim_yonetim/plan_ekrani.html` (9 KB) | **Belirsiz** | Menüde görünmüyor |
| Kilit Ekranı | `/uretim-yonetim/kilit` | `uretim_yonetim/kilit_ekrani.html` (10 KB) | **Belirsiz** | Menüde görünmüyor |
| Üretim Girişi | `/uretim-giris/` | `uretim_giris/index.html` (6 KB) | **Aktif** | Personel veri girişi |
| Usta Ekranı | `/usta/` | `usta/index.html` (5 KB) | **Aktif** | Usta menüsü |
| Darboğaz Bandı | (tüm sayfalarda) | `hedef/_darbogaz_band.html` (573 B) | **KAPALI** | JS `return;` ile devre dışı |
| Plan v2 | `/hedef/plan` | `hedef/plan_v2.html` (2 KB) | **İSKELET** | İçerik yok |

---

## 3. Backend Endpoint Haritası

### Hedef Modülü (`/hedef/`)

| Endpoint | Fonksiyon | Veri Kaynağı | Durum | Menüde? |
|---|---|---|---|---|
| `GET /hedef/` | `panel` | Korgun SQL | **Aktif** | Evet |
| `GET /hedef/plan` | `hedef_plan` | Korgun SQL | Aktif | Hayır |
| `GET /hedef/plan-proses` | `hedef_plan_proses` | Korgun SQL | Aktif | Hayır |
| `GET /hedef/korgun-plan` | `hedef_korgun_plan` | Korgun SQL | Aktif | Hayır |
| `GET /hedef/siparis-takip` | `hedef_siparis_takip` | Korgun SQL | **Aktif** | Evet |
| `GET /hedef/dogrulama` | `hedef_dogrulama` | CPS SQLite | Aktif | Hayır |
| `GET /hedef/plan-darbogaz` | `hedef_plan_darbogaz` | Korgun SQL | **Aktif (bağlantısız)** | Hayır |
| `GET /hedef/darbogaz-ozet` | `darbogaz_ozet` | Korgun SQL | Aktif | Hayır |
| `GET /hedef/sablon` | `sablon` | CPS SQLite | **Aktif** | Evet |
| `GET /hedef/sapma` | `sapma` | CPS SQLite | **Aktif** | Evet |
| `GET /hedef/rapor` | `hedef_rapor` | CPS SQLite | Aktif | Hayır |
| `POST /hedef/sablon/uygula` | `hedef_sablon_uygula` | CPS SQLite | **Aktif** | Hayır |
| `GET /hedef/sablon/trigger/<emir_no>` | `hedef_sablon_trigger_manuel` | CPS SQLite | Aktif | Hayır |

### Planlama Modülü (`/planlama/`)

| Endpoint | Fonksiyon | Veri Kaynağı | Durum | Menüde? |
|---|---|---|---|---|
| `GET /planlama/` | `kok` | — | Yönlendirme | Hayır |
| `GET /planlama/karar-masasi` | `km_gorunum` | — | Ekran var | Evet |
| `GET /planlama/karar-masasi/data` | `karar_masasi_data` | **MOCK** | ⚠️ Mock veri | Hayır |
| `POST /planlama/api/karar-masasi/gorev-olustur` | `km_gorev_olustur` | CPS SQLite (tasks) | Aktif | Hayır |
| `POST /planlama/karar-masasi/ustaya-gonder` | — | CPS SQLite | Aktif | Hayır |
| `GET /planlama/operasyon-raporu` | — | CPS SQLite | **Aktif** | Evet |
| `GET /planlama/proses-takip` | — | CPS SQLite | **Aktif** | Evet |
| `GET /planlama/api/operasyon/genel` | — | CPS SQLite | Aktif | Hayır |

### Üretim Yönetim Modülü (`/uretim-yonetim/`)

| Endpoint | Fonksiyon | Durum |
|---|---|---|
| `GET /uretim-yonetim/plan` | plan ekranı | Belirsiz — menüde yok |
| `GET /uretim-yonetim/kilit` | kilit ekranı | Belirsiz — menüde yok |

---

## 4. Korgun Veri Akışı

```
Korgun MSSQL (sahintaban)
│
├── Urt_Emir       → Ana emirler (sipariş bazlı)
├── Urt_Em2Em      → Alt emir ağacı (MAMUL/ATKI/GOVDE/AMBALAJ hiyerarşisi)
├── Urt_Em_gch     → Emir geçmişi (proses bazlı gerçekleşen üretim)
├── Urt_con_gch    → Tamamlanan (biten) üretim hareketi
└── Urt_wait_gch   → Bekleyen üretim hareketi
         │
         ▼
app/modules/hedef/korgun_v2.py   (43 KB — ana veri katmanı)
         │
         ├── get_siparis_emirleri()     → Sipariş altındaki tüm emirler
         ├── get_emir_prosesleri()      → Emir bazlı proses hareketleri
         ├── hesapla_bitmis_mamul()     → FINAL_PROSES_MAP üzerinden (şu an 0)
         ├── hesapla_uretim_asamasi()   → En ileri proses kodu
         └── (canlı SQL modu: MOCK_MODE = False)
         │
         ▼
app/modules/hedef/routes.py      (165 KB — 35 endpoint)
         │
         ├── /siparis-takip    → Har ağacı + emir/proses detay
         ├── /korgun-plan      → Planlama tablosu satırları
         ├── /plan-darbogaz    → Çok emirli darboğaz hesabı
         └── /dogrulama        → CPS veri tutarlılık kontrolü
```

**Kritik not:** Korgun sadece okunuyor (NOLOCK). Korgun'a hiçbir yazma yapılmıyor. Gerçekleşen üretim `uretim_kayit` tablosuna (CPS SQLite) yazılıyor.

---

## 5. Hedef / Sipariş Takip Durumu

### Ne Çalışıyor
- Sipariş numarası veya emir numarasıyla arama: **çalışıyor**
- Har ağacı görünümü (ana emir → alt emirler): **çalışıyor**
- Her emirde proses listesi + yapılan/hedef: **çalışıyor**
- Şablon sistemi: proses şablonu tanımlama, emirlere eşleştirme: **çalışıyor**
- Şablon tetikleme (manuel + otomatik): **çalışıyor**
- CPS'te üretim kaydı (uretim_kayit): **çalışıyor**
- Onay akışı (bekliyor → onaylandı): **çalışıyor**

### Ne Eksik
- **Bitmiş mamul hesabı:** `FINAL_PROSES_MAP = {}` → her sipariş için 0 döner. Hangi proses kodunun "bitmiş mamul" sayılacağı tanımlanmamış.
- **Miktar doğrulama son adımı:** `hedef_dogrulama` endpoint'i var ama Hedef Paneli'ne entegre değil. Veri tutarsızlıkları görünmüyor.
- **Korgun → CPS miktar karşılaştırması:** Korgun'da Urt_con_gch'de yazan miktar ile CPS'te uretim_kayit arasındaki fark hesabı yok.
- **Sipariş teslim tarihi:** Korgun'dan alınıyor ama gecikme uyarısı yok.
- **Operasyon özeti ekranı:** `/hedef/operasyon-ozet` endpoint'i var ama bağlı ekran yok.

---

## 6. Karar Masası Durumu

### Ne Çalışıyor
- Ekran açılıyor: `GET /planlama/karar-masasi`
- Görev oluşturma: `POST /planlama/api/karar-masasi/gorev-olustur` → tasks tablosuna yazıyor
- Ustaya gönderme endpoint'i var: `POST /planlama/karar-masasi/ustaya-gonder`

### Kritik Sorun: Veri MOCK
`GET /planlama/karar-masasi/data` fonksiyonunda:
```python
satirlar = _km_mock_satirlar()
return jsonify({"ok": True, "kaynak": "MOCK", ...})
```
Karar Masası **gerçek Korgun verisi ile çalışmıyor.** Mock veriden gösteriyor.

### Ne Eksik
- `_km_mock_satirlar()` → gerçek Korgun sorgusuyla değiştirilmeli
- Plan-Darboğaz hesabı (`hedef_plan_darbogaz`) Karar Masası'na bağlanmalı
- Darboğaz renk kodlaması (yeşil/sarı/kırmızı) mock veriden geliyor, gerçek hesapla değil
- Ustaya gönderme → gerçek tasks entegrasyonu eksik mi kontrol edilmeli

---

## 7. Darboğaz Durumu

### Kod Altyapısı
| Bileşen | Dosya | Durum |
|---|---|---|
| Darboğaz hesap motoru | `uretim_yonetim/darbogaz.py` (9 KB) | Yazılmış, **CPS SQLite bağımlı** |
| Darboğaz band HTML | `hedef/_darbogaz_band.html` (573 B) | Var, include edilmiş |
| Darboğaz CSS | `static/css/darbogaz_uyari.css` | Var |
| Darboğaz JS | `static/js/darbogaz_uyari.js` (7 KB) | **Satır 12: `return;` → KAPALI** |
| Plan-Darboğaz API | `hedef/routes.py` → `/plan-darbogaz` | **Çalışıyor, UI bağlı değil** |
| Darboğaz özet API | `hedef/routes.py` → `/darbogaz-ozet` | Çalışıyor |

### Neden Kapatıldı
`darbogaz_uyari.js` başında yorum: *"FAZ 2B: Darboğaz bandı + PLAN kolonu geçici kapalı — sonraki faz"*

`uretim_yonetim/darbogaz.py` hesap motoru:
- `siparis_proses_durum` tablosunu okuyor (CPS SQLite)
- `proses_kategori` tablosuna göre ATKI/GOVDE/MAMUL kategorize ediyor
- MIN% hesabıyla darboğaz buluyor
- **Sorun:** `siparis_proses_durum` tablosu Korgun gerçek verisini yansıtıyor mu yoksa manuel mi güncelleniyor? Bu bağlantı doğrulanmamış.

### Hedef Plan-Darboğaz API (Daha Güçlü)
`hedef/routes.py` → `hedef_plan_darbogaz()`:
- Korgun'dan doğrudan `Urt_con_gch` + `Urt_wait_gch` okuyor
- Birden fazla emir için tek API çağrısıyla hesaplıyor
- **Bu endpoint daha güncel ve doğru** — ama hiçbir ekrana bağlı değil

---

## 8. Ana Eksik Halka

Excel toplantı planını CPS'e taşımak için eksik olan ana yapı:

```
MEVCUT DURUM:
Excel toplantıda planlama sorular sorar:
  "33784 no'lu sipariş ne durumda?"
  "Enjeksiyonda darboğaz var mı?"
  "Yarın Halil'in ekibi neyle meşgul?"

CPS'TE OLAN:
✅ Sipariş sorgulama (Korgun'dan)
✅ Emir/proses ağacı
✅ Üretim girişi (usta/personel)
✅ Karar Masası ekranı (MOCK)

CPS'TE OLMAYAN:
❌ Gerçek zamanlı darboğaz hesabı → ekranda
❌ Karar Masası gerçek veri
❌ Usta bugün ne yapıyor? → planlanan iş listesi
❌ Makine/ekipman durumu
❌ Sipariş teslim tarihi gecikme uyarısı
❌ "Bu siparişi bitirmek için kaç gün?" hesabı
```

**Ana eksik halka:** Karar Masası'nın gerçek Korgun verisi + Plan-Darboğaz API'ıyla bağlanması.

---

## 9. Önerilen Yeni Yol

### FAZ-P0 — Temel Doğrulama (1-2 gün)
- `FINAL_PROSES_MAP`'i doldur: hangi proses kodu bitmiş mamul?
- `siparis_proses_durum` → Korgun canlı veriye nasıl bağlı, doğrula
- Karar Masası'nın MOCK durumunu belgele, gerçek veri geçişi hazırla

### FAZ-P1 — Karar Masası Gerçek Veri (3-5 gün)
- `_km_mock_satirlar()` → `hedef_plan_darbogaz()` çıktısıyla değiştir
- Plan-Darboğaz API çıktısını Karar Masası tablosuna bağla
- Renk kodlaması: gerçek % hesaplamasına göre (kırmızı < 30%, sarı 30-70%, yeşil > 70%)

### FAZ-P2 — Darboğaz Bandı (1-2 gün)
- `darbogaz_uyari.js` → `return;` satırını kaldır
- API: `/hedef/darbogaz-ozet` veya `/hedef/plan-darbogaz?emirler=...` bağla
- En kritik darboğazı üst banda yaz

### FAZ-P3 — Sipariş Teslim Takibi (3-5 gün)
- Korgun'dan teslim tarihi çek
- Gecikme hesabı: kalan gün × günlük üretim kapasitesi
- Geciken siparişler için uyarı listesi

---

## 10. Riskler

| Risk | Açıklama | Etki |
|---|---|---|
| **FINAL_PROSES_MAP boş** | Bitmiş mamul sayısı 0 — tüm siparişler tamamlanmamış görünüyor | Yüksek |
| **Karar Masası MOCK** | Gerçek karar alınamaz, ekranda görünen veri yapay | Yüksek |
| **Darboğaz bandı kapalı** | Geciken siparişler sessizce bekliyor, uyarı yok | Orta |
| **siparis_proses_durum senkronizasyonu** | Bu tablonun Korgun ile ne zaman / nasıl güncellendiği belirsiz | Orta-Yüksek |
| **hedef.js 329 KB** | Tek büyük JS dosyası — bakımı zor, hata ayıklama karmaşık | Orta |
| **uretim_yonetim/plan + kilit ekranları** | Menüde yok, hangi koşulda açılıyor bilinmiyor | Düşük |
| **Planlama routes.py çift satır aralığı** | Dosya içinde çift boş satır formatı — okunabilirlik düşük | Düşük |

---

## Sonuç: Mevcut Sistem Planlama Merkezi Olmaya Ne Kadar Yakın?

| Alan | Mevcut Durum | Tamamlanma % |
|---|---|---|
| **Veri altyapısı** | Korgun bağlantısı canlı, SQL sorguları yazılı, veri geliyor | **%70** |
| **Ekran** | Hedef Paneli aktif, Karar Masası MOCK, Darboğaz bandı kapalı | **%45** |
| **Karar / Darboğaz** | Hesap motoru var ama hiçbir ekrana bağlı değil | **%25** |
| **Usta iş akışı** | Üretim girişi çalışıyor, ama planlanan iş listesi yok | **%40** |
| **Excel yerine geçme** | Sipariş sorgulama var, toplantı kararı almak için henüz yetersiz | **%20** |

**Genel değerlendirme:**
Sistem veri altyapısı bakımından iyi bir noktada. Korgun bağlantısı canlı, sipariş/emir/proses hiyerarşisi okunabiliyor. Ancak bu verinin **karar ekranına taşınması** henüz yapılmamış. Karar Masası mock, Darboğaz kapalı. Bir planlama toplantısında "şu an sisteme bakarak karar alalım" denilemez.

En kritik tek adım: **Karar Masası'nı gerçek Plan-Darboğaz verisine bağlamak.**
Bu tek adım sistemi %20'den %60'a çıkarır.
