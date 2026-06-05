# CPS — DARBOĞAZ MERKEZLİ ÜRETİM YÖNETİMİ
## Mimari Tasarım Belgesi

**Hazırlayan:** CPS Geliştirme Ekibi  
**Tarih:** Haziran 2026  
**Durum:** Tasarım Aşaması — Kod Yazılmamış  
**Bağlı Belge:** CPS_MASTER_VISION_2026.md  

---

## 1. SORUN: Sipariş İlerlemesi Neden Yanıltır?

### Mevcut Durum

Bugün bir siparişin durumunu sormak için tek bir cevap yoktur:

> "Bu siparişin yüzde kaçı tamamlandı?"

Çünkü her proses farklı bir yüzde gösterir:

```
Sipariş: LCW-2026-047  (10.000 çift)

Atki bölümü      → %94 tamamlandı
Gövde bölümü     → %72 tamamlandı
Mamul bölümü     → %61 tamamlandı
```

Geleneksel yaklaşımda "ortalama" hesaplanır: **(94 + 72 + 61) / 3 = %75**

**Bu yanıltıcıdır.**

Çünkü mamul tamamlanmadan ürün sevk edilemez. Gerçek ilerleme **%61**'dir.

---

## 2. TEMEL KURAL: En Yavaş Proses = Siparişin Gerçek Durumu

### Kural

```
Sipariş İlerlemesi = MIN(Kategori Yüzdeleri)
```

Hangi kategorinin yüzdesi en düşükse, sipariş o kadar tamamlanmıştır.

### Örnek

```
Sipariş: LCW-2026-047  (10.000 çift)

Kategori     Tamamlanan    Yüzde
──────────   ──────────    ──────
ATKI         9.400 çift    %94
GÖVDE        7.200 çift    %72
MAMUL        6.100 çift    %61   ← EN DÜŞÜK

Siparişin gerçek ilerlemesi: %61
Ana darboğaz kategori:       MAMUL
```

---

## 3. KATEGORİ MANTIĞI

### Üç Ana Kategori

| Kategori | Anlamı | Örnek Prosesler |
|----------|--------|-----------------|
| **ATKI** | Hammadde / yarı mamul girdi | İplik, ham deri, malzeme kesimi |
| **GÖVDE** | Ara işlem / montaj öncesi | Enjeksiyon, taban, iç taban |
| **MAMUL** | Son ürün / sevke hazır | Dikme, montaj, kalite kontrol, paketleme |

### Kurallar

- Her proses mutlaka bir kategoriye aittir.
- Kategoriler hiyerarşiktir: ATKI → GÖVDE → MAMUL.
- Bir üst kategori tamamlanmadan alt kategori başlayamaz *(ileriki faz kısıtı)*.
- Sipariş ilerlemesi **her zaman en düşük kategori yüzdesi** üzerinden hesaplanır.

---

## 4. ANA DARBOĞAZ ve ALT DARBOĞAZ

### Tanımlar

```
Ana Darboğaz  = En düşük yüzdeye sahip KATEGORİ
Alt Darboğaz  = O kategorideki en yavaş PROSES
```

### Örnek (Detay)

```
MAMUL kategorisi (%61) = Ana Darboğaz

MAMUL içindeki prosesler:
  Dikme         → %81
  Montaj        → %61  ← Alt Darboğaz
  Paketleme     → %79

Alt Darboğaz:  Montaj prosesi
Sorumlu Usta:  [Montaj ustasının adı]
```

---

## 5. SORUMLU USTA BAĞLANTISI

### Proses → Usta → Personel 360

Her alt darboğaz tespitinde sistem otomatik olarak sorumlu ustayı bulur:

```
Alt Darboğaz (Proses)
        │
        ▼
  proses_master_ref  (proses kaydı)
        │
        ▼
  usta_personel_iliskisi  (usta ataması)
        │
        ▼
  kullanici_profil  (usta kimliği)
        │
        ▼
  Bildirim + Personel 360 kartı
```

### Sorumlu Usta Bildirimi (Gelecek)

Darboğaz tespit edildiğinde:

1. Sorumlu usta SMS/bildirim alır
2. Sebep seçimi yapması istenir (personel eksikliği / makine arızası / malzeme yok / diğer)
3. Sebep sisteme kaydedilir
4. Raporlama ve Personel 360 kartına yansır

---

## 6. SAPMA TESPİTİ VE RAPORLAMA

### Sapma Nedir?

Bir prosesin beklenen hızın altında kalması:

```
Beklenen tamamlanma: Sipariş tarihi - bugün  →  günlük hedef hesaplanır
Gerçekleşen:         Günlük fiili üretim
Sapma:               Hedef - Gerçek  (negatif = gecikme)
```

### Raporlama Akışı

```
Sistem her gün otomatik hesaplar:
  1. Her proses için tamamlanma %
  2. Ana ve alt darboğaz tespiti
  3. Sapma büyüklüğü (gün cinsinden gecikme riski)
  4. Sorumlu usta bilgisi

Raporlama katmanları:
  ① Operasyon Raporu → günlük özet
  ② Sipariş detay sayfası → anlık durum
  ③ Yönetim Kokpiti → kritik uyarılar
  ④ Personel 360 kartı → usta bazlı geçmiş
```

---

## 7. KİLİT SİSTEMİ — İLERİKİ FAZ

> **Bu bölüm şu an uygulanmayacaktır. Gelecek faz tasarımıdır.**

### Konsept

Darboğaz aşılmadan bir sonraki kategori kilitlenir:

```
ATKI %100 tamamlanmadan → GÖVDE başlatılamaz
GÖVDE %100 tamamlanmadan → MAMUL başlatılamaz
```

### Neden Şimdi Değil?

- Mevcut veri kalitesi bu kısıtı kaldırmaya hazır değil
- Saha alışkanlıkları değişmeli, eğitim gerekli
- Önce raporlama; sonra kısıt
- FAZ 3 (Üretim Dijital İkizi) kapsamında değerlendirilecek

---

## 8. PERSONEL 360 BAĞLANTISI

### Kişi Kartında Darboğaz Geçmişi

Bir ustanın Personel 360 kartı şunları gösterecektir:

```
┌─────────────────────────────────────────────────────┐
│  USTA KARTI — Mehmet Yılmaz                          │
│  Departman: Üretim   Ekip: Montaj A                  │
├─────────────────────────────────────────────────────┤
│  SORUMLU OLDUĞU PROSESLER                            │
│  • Montaj (Ana)                                      │
│  • Kalite Kontrol (Yedek)                            │
├─────────────────────────────────────────────────────┤
│  DARBOĞAZ GEÇMİŞİ (Son 90 Gün)                      │
│  Toplam darboğaz: 4 kez                              │
│  Ortalama gecikme: 1.8 gün                           │
│  En sık sebep: Personel eksikliği (%50)              │
├─────────────────────────────────────────────────────┤
│  SEBEP DOĞRULUĞU                                     │
│  Bildirilen sebep: "Makine arızası"                  │
│  Gerçekleşen: Arıza kaydı yok → Şüpheli             │
├─────────────────────────────────────────────────────┤
│  PERFORMANS                                          │
│  Bu ay hedef: %95                                    │
│  Gerçekleşen: %91  → Prim eşiğinin altında           │
└─────────────────────────────────────────────────────┘
```

### Bağlantı Akışı

```
Darboğaz Tespiti
      │
      ├──► proses_master_ref.sorumlu_usta_id
      │           │
      │           ▼
      │    kullanici_profil
      │           │
      ├──► Darboğaz kaydı: [proses, tarih, gecikme_gun, sebep]
      │
      └──► Personel 360 kartı güncellenir:
               - darboğaz_sayisi artar
               - sebep_dagılimi güncellenir
               - performans skoru etkilenir
               - prim hesabına girdi sağlar
```

---

## 9. VERİ AKIŞI (Gelecek Mimari)

```
Sipariş Sistemi
      │  (sipariş, miktar, teslim tarihi)
      ▼
Proses Planlama
      │  (hangi proses, kaç adet, hedef tarih)
      ▼
Günlük Üretim Girişi (Enjeksiyon + Saha)
      │  (fiili üretim miktarı)
      ▼
Darboğaz Hesap Motoru
      │  ┌─ kategori yüzdeleri
      │  ├─ ana/alt darboğaz tespiti
      │  └─ sorumlu usta bulma
      ▼
Raporlama Katmanı
      │  ┌─ Operasyon Raporu
      │  ├─ Yönetim Kokpiti
      │  └─ Personel 360 Kartı
      ▼
Aksiyon
      │  ├─ Usta bildirimi
      │  ├─ Sebep kaydı
      │  └─ Otomatik görev oluşturma (AI Faz)
```

---

## 10. UYGULAMA YOL HARİTASI

| Faz | Kapsam | Ön Koşul | Tahmini Süre |
|-----|--------|----------|-------------|
| **Faz A** | Proses bazlı üretim girişi | Sipariş sistemi hazır | 2–3 hafta |
| **Faz B** | Kategori hesabı + darboğaz raporu | Faz A | 1–2 hafta |
| **Faz C** | Sorumlu usta bildirimi | CORE ilişkileri tam | 1 hafta |
| **Faz D** | Personel 360 darboğaz kartı | Personel 360 UI | 1–2 hafta |
| **Faz E** | Sebep doğrulama motoru | Faz C + D | 2–3 hafta |
| **Faz F** | Kilit sistemi | Faz E + saha hazırlığı | 3–4 hafta |
| **Faz G** | AI darboğaz tahmini | Faz F + 6 ay veri | 2–4 ay |

**Toplam (Faz A–E, temel sistem):** ~8–11 hafta

---

## 11. ÖZET

| Konu | Karar |
|------|-------|
| Sipariş ilerlemesi | En düşük kategori yüzdesi |
| Kategori yapısı | ATKI → GÖVDE → MAMUL |
| Ana darboğaz | En düşük yüzdeli kategori |
| Alt darboğaz | O kategorideki en yavaş proses |
| Sorumlu | Proses ustası (CORE'dan) |
| Önce ne yapılır? | Raporlama, kısıt değil |
| Kilit sistemi | İleriki faz |
| Personel 360 bağlantısı | Darboğaz geçmişi + sebep doğruluğu + prim |

---

*Bu belge mimari tasarım kararlarını içermektedir. Kod yazılmamıştır.*  
*Uygulama başlamadan önce saha verisinin proses bazlı girilmesi sağlanmalıdır.*
