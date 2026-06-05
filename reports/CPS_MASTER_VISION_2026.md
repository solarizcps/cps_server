# CPS MASTER VİZYON 2026
## Solariz Central Process System — Yönetici Analiz Raporu

**Hazırlayan:** CPS Geliştirme Ekibi  
**Tarih:** Haziran 2026  
**Gizlilik:** Yönetim İçi  

---

## GİRİŞ

Bu rapor, Solariz'in dijital dönüşüm altyapısı olan CPS sisteminin bugünkü durumunu, tamamlanan çalışmaları, eksik kalan parçaları ve 2026–2027 yol haritasını özetlemektedir. Patron ve üst yönetim seviyesinde okunmak üzere hazırlanmıştır.

---

## BÖLÜM 1 — CPS NEDİR?

### Sıradan ERP Değil: Şirket İşletim Sistemi

CPS, **Central Process System** (Merkezi Süreç Sistemi) anlamına gelir.  
Solariz için bir muhasebe programı veya üretim takip yazılımı değildir.

CPS'in hedefi çok daha büyüktür:

> **"Şirketin tüm işleyişini — insan, üretim, finans, satın alma, kalite, görev ve zaman boyutlarıyla — tek bir dijital omurgada birleştirmek."**

---

### Geleneksel ERP vs CPS Farkı

| Geleneksel ERP | CPS |
|----------------|-----|
| Muhasebe merkezli | İnsan merkezli |
| Veri giriş formu | Anlık veri akışı |
| Raporlama odaklı | Karar destek odaklı |
| Departman silolar | Tek omurga |
| Aylık kapanış | Anlık durum |
| Pasif sistem | Aktif bildirim + uyarı |

---

### CPS'in Kapsamı

```
     İNSAN          ──►  Personel 360, PDKS, İzin, Maaş, Prim
     ÜRETİM         ──►  Enjeksiyon, Saha, Makine, Fire, Kalite
     PLANLAMA        ──►  Sipariş, Kapasite, Operasyon Raporu
     FİNANS         ──►  Kur, Gider, Maliyet, Prim Hesabı
     SATIN ALMA     ──►  Tedarikçi, Stok, Hammadde
     GÖREV          ──►  Atama, Takip, Eskalasyon, Bildirim
     YAPAY ZEKA     ──►  Anomali, Tahmin, Öneri (Gelecek)
```

Tüm bu katmanlar tek bir veritabanı omurgasında birbirine bağlıdır.

---

## BÖLÜM 2 — BUGÜN CPS NE DURUMDA?

### Genel Tamamlanma

| Katman | Durum | Tamamlanan % | Eksik % | Risk |
|--------|-------|-------------|---------|------|
| Kullanıcı & Yetki | ✅ Çalışıyor | 90% | 10% | Düşük |
| CORE Organizasyon | ✅ Çalışıyor | 75% | 25% | Düşük |
| Enjeksiyon Takip | ✅ **STABİL** | 95% | 5% | Çok Düşük |
| Kalıp Master | ✅ **STABİL** | 95% | 5% | Çok Düşük |
| Fire Analizi | ✅ **STABİL** | 85% | 15% | Düşük |
| Operasyon Raporu | ✅ **STABİL** | 80% | 20% | Düşük |
| Görev Sistemi | ✅ Çalışıyor | 70% | 30% | Orta |
| Bildirim Altyapısı | ⚠️ Kısmi | 50% | 50% | Orta |
| Personel Takip | ⚠️ Temel | 40% | 60% | Orta |
| Finans | ⚠️ Kısmi | 35% | 65% | Orta |
| İthalat Altyapısı | ⚠️ Temel | 30% | 70% | Orta |
| PDKS | ❌ Yok | 0% | 100% | Yüksek |
| İzin Yönetimi | ❌ Yok | 0% | 100% | Yüksek |
| Maaş/Prim | ❌ Yok | 0% | 100% | Orta |
| Kalite/Hata | ❌ Yok | 0% | 100% | Orta |
| Satın Alma | ❌ Yok | 0% | 100% | Orta |
| Mobil Uygulama | ❌ Yok | 0% | 100% | Düşük |
| Yapay Zeka | ❌ Yok | 0% | 100% | Düşük |

---

### Tamamlanan Fazlar (Mayıs–Haziran 2026)

Aşağıdaki fazlar tamamlanmış ve stabil tag ile kilitlenmiştir:

| Faz | İçerik | Tag |
|-----|--------|-----|
| ENJ CORE | Enjeksiyon snapshot motoru | `STABLE_ENJ_CORE_SNAPSHOT_V1` |
| Kalıp Master FAZ1 | Temel CRUD | `STABLE_KALIP_MASTER_FAZ1_PASS` |
| Kalıp Master FAZ2 | Gramaj, pişme, durum, bağlı kalıp | `STABLE_KALIP_MASTER_FAZ2_FULL_PASS` |
| Fire V1 | KG görünürlük + çift hesabı | `STABLE_FIRE_4_1_UI_REFRESH_WARNING_PASS` |
| Genel V1 | ENJ + Kalıp + Fire tam test | `STABLE_ENJ_KALIP_FIRE_V1_FULL_PASS` |

**Bu fazlar kilitlidir. Üzerine inşa edilir, bozulmaz.**

---

### Mevcut Çalışan Modüller

| Modül | URL | Ne Yapıyor? |
|-------|-----|-------------|
| Enjeksiyon | `/enjeksiyon` | A/B slot üretim, saatlik tur, günlük özet |
| Kalıp Master | `/yonetim/kalip-yonetimi` | 69 kalıp, gramaj, pişme, durum yönetimi |
| Operasyon Raporu | `/planlama/operasyon-raporu` | Günlük KPI özeti |
| Yönetim Paneli | `/yonetim` | Kullanıcı, rol, ekip, org yönetimi |
| Görev Sistemi | `/tasks` | Görev atama, takip, log |
| Hedef/Plan | `/hedef` | Personel ekleme, hedef planlama |
| Personel Giriş | `/personel-giris` | Saha personeli girişi |
| Usta Paneli | `/usta` | Usta işlemleri |
| Canlı Saha | `/canli-saha` | Anlık saha durumu |
| Finans | `/finans` | Kur ve temel giderler |
| İthalat | `/ithalat` | Parti ve tedarikçi takibi |

---

## BÖLÜM 3 — CORE NEDEN YAPILDI?

### Eski Yöntem: Kişiye Bağlı Çalışmak

Eskiden şirket işleyişi insanların zihnindeydi:

> "Bu işi Halil biliyor."  
> "O makineyi Mehmet çalıştırıyor."  
> "Aylık rakamlar Ayşe'nin Excel'inde."

Bu yapının tehlikeleri:
- Halil izne çıkınca üretim bilgisi durur
- Mehmet ayrılınca makine geçmişi kaybolur
- Ayşe'nin Excel'i bozulunca ay kapanışı açılamaz

---

### Yeni Hedef: Şirketin Dijital İkizi

CPS ile her bilgi sisteme yazılır, kişiye değil:

```
Halil
 │
 ├── Ekibi          → Enjeksiyon A Ekibi
 ├── Makinesi       → İstasyon 3 / Slot A
 ├── Üretimi        → Bu ay 4.200 çift
 ├── Performansı    → Hedefin %94'ü
 ├── Fire oranı     → %2.1
 ├── Devam durumu   → 22/22 gün (PDKS)
 └── Maliyeti       → Prim hesabına dahil
```

Halil izne çıksa da, ayrılsa da, yerine yeni biri gelse de:  
**Sistem çalışmaya devam eder.**

---

### CORE Omurganın Yapısı

```
     CORE
      │
      ├── kullanici_profil     (her insanın tek kartı)
      │       ├── sistem_kullanici     (ofis/yetki girişi)
      │       └── personel_kullanici  (saha girişi)
      │
      ├── departman_master     (Üretim / İdari / Bakım...)
      │
      ├── ekip_master          (Enjeksiyon A, Enjeksiyon B...)
      │       └── kullanici_ekip      (kim hangi ekipte)
      │
      ├── proses_master_ref    (hangi iş prosesleri var)
      │       └── kullanici_proses    (kim hangi prosesi biliyor)
      │
      └── usta_personel_iliskisi  (kim kimin sorumlusu)
```

Bu yapı olmadan: görev kime gidecek bilinmez, prim kime ödenecek hesaplanamaz, bildirim kime gönderilecek kaybolur.

---

## BÖLÜM 4 — CPS 1 YIL SONRA NEREYE GİDECEK?

### 2027 Hedef Ekran: Yönetim Kokpiti

Fabrika müdürü sabah bilgisayarını açtığında şunları görecek:

```
┌─────────────────────────────────────────────────────────┐
│  SOLARİZ CPS — YÖNETİM KOKPİTİ          5 Haziran 2026  │
├────────────┬───────────────┬──────────────┬─────────────┤
│ ÜRETİM     │ PERSONEL      │ FİNANS       │ GÖREVLER    │
│ Bugün:     │ Çalışan: 148  │ Bu ay ciro:  │ Açık: 23    │
│ 18.400 çft │ İzinli: 3     │ ₺ 2.840.000  │ Geciken: 4  │
│ Hedef: 94% │ Devamsız: 1   │ Hedef: %88   │ Kritik: 1   │
├────────────┴───────────────┴──────────────┴─────────────┤
│  ⚠️  AI UYARISI                                           │
│  LCW Siparişi 5 gün gecikme riski:                       │
│  → Enjeksiyon kapasitesi %78 dolu                        │
│  → Malzeme deposunda 3 gün kaldı                         │
│  → Önerilen aksiyon: Fazla mesai aut. + sipariş ver      │
└─────────────────────────────────────────────────────────┘
```

---

### 1 Yıl Sonraki Hedef Özellikler

| Özellik | Açıklama |
|---------|----------|
| **Canlı Fabrika Takip** | Her makinenin anlık durumu, üretim sayacı |
| **Personel 360** | Her çalışanın tam profil kartı |
| **Makine Performansı** | OEE (genel ekipman etkinliği) takibi |
| **Fire Analizi** | KG → çift dönüşümü, kalıp bazlı fire oranı |
| **AI Öneri Sistemi** | Gecikme tahmini, kapasite uyarısı |
| **Otomatik Görev Üretme** | AI anomali tespiti → görev oluştur → kişiye at |
| **Mobil Uygulama** | PDKS girişi, görev listesi, bildirim alımı |
| **Yönetim Kokpiti** | Üst yönetim için anlık özet ekran |

---

### AI Sistemi Nasıl Çalışacak?

```
Veri Kaynakları:
  Enjeksiyon üretim    →  saatlik/günlük gerçek rakamlar
  Personel devam       →  PDKS giriş/çıkış saatleri
  Sipariş durumu       →  teslim tarihi, miktar
  Stok durumu          →  hammadde kalan gün
  Makine durumu        →  bakım takvimi, arıza geçmişi
          │
          ▼
    AI Tahmin Motoru
          │
          ▼
  "Sipariş X, 5 gün gecikme riski"
  "Makine 3 önümüzdeki hafta bakıma girecek"
  "Halil bu ay prim hak ediyor"
  "Hammadde A için bugün sipariş ver"
          │
          ▼
  Yöneticiye bildirim + Görev otomatik oluşturulur
```

---

## BÖLÜM 5 — EKSİK KALAN BÜYÜK PARÇALAR

### Kritik Eksikler (Şirketi Doğrudan Etkiliyor)

| Eksik | Etki | Süre Tahmini |
|-------|------|-------------|
| **PDKS Entegrasyonu** | Devam takibi elle yapılıyor, hata riski yüksek | 2–3 hafta |
| **İzin Yönetimi** | Kağıt/sözel talep, kayıt yok | 1–2 hafta |
| **Maaş/Prim Sistemi** | Excel'de, şeffaflık yok, hata riski | 3–4 hafta |
| **Kalite/Hata Modülü** | Fire nedenleri kayıt altında değil | 2–3 hafta |

### Orta Vadeli Eksikler

| Eksik | Etki | Süre Tahmini |
|-------|------|-------------|
| **Depo/Stok Takibi** | Hammadde ne zaman biter bilinmiyor | 3–4 hafta |
| **Satın Alma Karar Sistemi** | Manuel süreç, gecikmeli sipariş | 4–6 hafta |
| **Personel 360 UI** | Veri var ama tek ekranda görünmüyor | 1–2 hafta |
| **Push Bildirim** | Telefona bildirim gitmiyor | 2–3 hafta |

### Uzun Vadeli Eksikler

| Eksik | Etki | Süre Tahmini |
|-------|------|-------------|
| **AI Tahmin Motoru** | Reaktif yönetim → proaktif yönetim | 2–4 ay |
| **Mobil Uygulama** | Saha personeli sisteme bağlanamıyor | 2–3 ay |
| **Çoklu Fabrika** | Büyüme planına hazırlık | 6–12 ay |

---

## BÖLÜM 6 — RİSK ANALİZİ

### CPS İçin En Büyük Riskler

#### Risk 1: Modül Adalara Ayrışması ⚠️

**Yanlış yol:**
```
Muhasebe modülü → ayrı DB
Üretim modülü   → ayrı DB
İK modülü       → ayrı Excel
```

**Doğru yol:**
```
Tek CORE omurga
    │
    ├── Muhasebe  → kullanici_profil.maliyet
    ├── Üretim    → uretim_kayit.personel_id
    └── İK        → pdks_kayit.kullanici_profil_id
```

Her modül CORE'a bağlanır, CORE'dan ayrılmaz.

---

#### Risk 2: Kişiye Bağlı Geliştirme ⚠️

Bir modülü tek kişi bilirse, o kişi ayrılınca sistem durur.  
**Çözüm:** Her modül dokümante edilir, her geliştirme commit'lenir, her stabil nokta taglanır.

---

#### Risk 3: ENJ Core Bozulması 🔴

Enjeksiyon modülü 2 aylık stabilizasyon çalışmasıyla olgunlaştırılmıştır.  
**Bu modüle dokunulmaz.** Gelecek eklemeler ayrı katman olarak yapılır.

---

#### Risk 4: Veritabanı Büyümesi ⚠️

SQLite tek dosya yapısı prod ortamında büyük veri için yavaşlar.  
**Plan:** 6–12 ay içinde PostgreSQL geçişi planlanmalıdır.

---

## BÖLÜM 7 — YOL HARİTASI

### Faz Sıralaması (Önerilen)

```
┌─────────────────────────────────────────────────────────┐
│                    CPS YOL HARİTASI                      │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  FAZ 0 — Temel Veri Temizliği          [1–2 gün]         │
│  Personel profil köprülerini tamamla                     │
│  profil_tipi standartlaştır                              │
│                                                          │
│  FAZ 1 — CORE Tamamla                  [2–3 hafta]       │
│  Personel 360 UI                                         │
│  PDKS devam takibi                                       │
│  İzin yönetimi                                           │
│                                                          │
│  FAZ 2 — Personel Ekonomisi            [3–4 hafta]       │
│  Maaş/Prim hesabı                                        │
│  Push bildirim altyapısı                                 │
│                                                          │
│  FAZ 3 — Üretim Dijital İkizi          [4–6 hafta]       │
│  Makine performans takibi                                │
│  Kalite/Hata modülü                                      │
│  Fire analizi derinleştirme                              │
│                                                          │
│  FAZ 4 — Finans + Satın Alma + Stok    [6–8 hafta]       │
│  Hammadde stok takibi                                    │
│  Satın alma karar sistemi                                │
│  Maliyet analizi                                         │
│                                                          │
│  FAZ 5 — AI Yönetici Asistanı          [2–4 ay]          │
│  Tahmin motoru                                           │
│  Otomatik görev üretme                                   │
│  Yönetim kokpiti                                         │
│                                                          │
│  FAZ 6 — Mobil Uygulama                [2–3 ay]          │
│  PDKS QR giriş                                           │
│  Saha personeli görev listesi                            │
│  Yönetici bildirimleri                                   │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### Takvim Önerisi

| Dönem | Hedef |
|-------|-------|
| Haziran 2026 | FAZ 0 + FAZ 1 başlangıç |
| Temmuz 2026 | FAZ 1 tamamla, FAZ 2 başla |
| Ağustos 2026 | FAZ 2 tamamla |
| Ekim 2026 | FAZ 3 tamamla |
| Aralık 2026 | FAZ 4 tamamla |
| Mart 2027 | FAZ 5 beta |
| Haziran 2027 | FAZ 6 — Mobil uygulama canlıya al |

---

## BÖLÜM 8 — VİZYON: ADEM TERZİ

### 150 Kişilik Fabrikayı Veri ile Yönetmek

> **"Solariz'i kişilere bağlı çalışan yapıdan çıkarıp, veriye dayalı, ölçülebilir, kendi kendini takip eden şirkete çevirmek."**

---

### Dönüşüm Tablosu

| Bugün (Kişiye Bağlı) | Hedef (Sisteme Bağlı) |
|---------------------|----------------------|
| "Halil biliyor" | Sistem biliyor |
| Devam kağıtla tutuluyor | PDKS otomatik |
| Prim Excel'de hesaplanıyor | Sistem hesaplıyor |
| Sipariş gecikmesi sürpriz | AI 5 gün önceden uyarıyor |
| Stok bitince fark ediliyor | Sistem 3 gün kala haber veriyor |
| Makine arızası beklenmiyor | Bakım takvimi otomatik |
| Yönetici her şeyi bilmeli | Kokpit her şeyi gösteriyor |

---

### Büyüme Senaryosu

**Bugün:** 150 kişi, 1 fabrika, manuel süreçler  
**2027:** 150+ kişi, 1–2 fabrika, dijital süreçler  
**2030:** Çoklu fabrika, CPS omurgası ortak, AI destekli yönetim

Solariz'in büyümesi artık kişi kapasitesine değil, **sistem kapasitesine** bağlı olacak.

---

### Son Söz

CPS bir yazılım projesi değildir.

CPS, Solariz'in kurumsal hafızasıdır.  
Her üretilen çiftin, her çalışılan günün, her verilen kararın kaydı burada tutulur.

**Bugün yapılan her doğru veri girişi, yarın alınacak doğru karara dönüşür.**

---

## BÖLÜM 9 — DARBOĞAZ MERKEZLİ ÜRETİM YÖNETİMİ

### Temel Fikir

Bir siparişin yüzde kaçının tamamlandığını sormak için tek bir doğru cevap vardır:

> **Siparişin gerçek ilerlemesi = En düşük kategori yüzdesi**

Ortalama almak yanıltır. Mamul kategorisi %61'deyse, sipariş %61 tamamdır — diğer kategoriler ne kadar yüksek olursa olsun.

---

### Kategori Yapısı

Tüm prosesler üç ana kategoriye ayrılır:

| Kategori | Anlamı |
|----------|--------|
| **ATKI** | Hammadde / yarı mamul girdi |
| **GÖVDE** | Ara işlem / montaj öncesi |
| **MAMUL** | Son ürün / sevke hazır |

Hiyerarşi: **ATKI → GÖVDE → MAMUL**

---

### Darboğaz Mantığı

```
Ana Darboğaz  = En düşük yüzdeye sahip KATEGORİ
Alt Darboğaz  = O kategorideki en yavaş PROSES
Sorumlu Usta  = O prosese atanmış usta (CORE'dan otomatik)
```

**Örnek:**

```
Sipariş: LCW-2026-047  (10.000 çift)

ATKI   → %94
GÖVDE  → %72
MAMUL  → %61  ← Ana Darboğaz

MAMUL içindeki prosesler:
  Dikme     → %81
  Montaj    → %61  ← Alt Darboğaz
  Paketleme → %79
```

---

### Sapma ve Raporlama

- Sistem her gün her proses için tamamlanma % hesaplar
- Ana ve alt darboğaz otomatik tespit edilir
- Sapma büyüklüğü gün cinsinden gecikme riski olarak raporlanır
- Sorumlu usta bildirim alır, sebep girer, kayıt sisteme yazılır

---

### Personel 360 Bağlantısı

Her ustanın kişi kartında şunlar görünecek:

- Sorumlu olduğu prosesler
- Darboğaz geçmişi (son 90 gün, kaç kez, ortalama gecikme)
- En sık bildirilen sebep
- Sebep doğruluğu (bildirim ile gerçek arıza kaydı karşılaştırması)
- Performans skoru ve prim etkisi

---

### Kilit Sistemi — İleriki Faz

Bir kategorideki proses tamamlanmadan bir sonraki kategorinin başlatılmasını engelleyen kilit sistemi **şu an uygulanmayacaktır**. Önce raporlama kurulur, saha alışkanlıkları olgunlaşır, sonra kısıt gelir.

---

### Uygulama Sırası

| Faz | Kapsam |
|-----|--------|
| Faz A | Proses bazlı üretim girişi |
| Faz B | Kategori hesabı + darboğaz raporu |
| Faz C | Sorumlu usta bildirimi |
| Faz D | Personel 360 darboğaz kartı |
| Faz E | Sebep doğrulama |
| Faz F | Kilit sistemi |

Detaylı mimari: `reports/CPS_DARBOGAZ_MIMARISI.md`

---

## EKLER

### A. Teknik Altyapı

| Bileşen | Teknoloji |
|---------|-----------|
| Backend | Python 3 / Flask |
| Veritabanı | SQLite (prod: PostgreSQL hedefi) |
| Frontend | Jinja2 + Vanilla JS |
| Erişim | LAN (tarayıcı, port 8080) |
| Versiyon Kontrol | Git / GitHub |
| Yedekleme | C:\CPS_BACKUPS (manuel + otomatik) |

### B. Mevcut Stabil Noktalar

| Tag | Tarih | İçerik |
|-----|-------|--------|
| `STABLE_ENJ_CORE_SNAPSHOT_V1` | 04.06.2026 | Enjeksiyon motoru |
| `STABLE_KALIP_MASTER_FAZ2_FULL_PASS` | 04.06.2026 | Kalıp Master V2 |
| `STABLE_FIRE_4_1_UI_REFRESH_WARNING_PASS` | 04.06.2026 | Fire V1 |
| `STABLE_ENJ_KALIP_FIRE_V1_FULL_PASS` | 04.06.2026 | Genel V1 |

### C. Ekip & İletişim

| Rol | Sorumluluk |
|-----|-----------|
| Adem Terzi | Vizyon sahibi, ürün onayı |
| CPS Geliştirme | Backend + Frontend geliştirme |
| Saha Kullanıcıları | Veri girişi + geri bildirim |

---

*Bu rapor CPS sisteminin 2026 Haziran ayı itibarıyla anlık fotoğrafıdır.*  
*Yol haritası güncellenebilir; stabil noktalar değiştirilemez.*
