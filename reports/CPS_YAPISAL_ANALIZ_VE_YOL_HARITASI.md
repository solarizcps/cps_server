# CPS YAPISAL ANALİZ VE YOL HARİTASI

**Versiyon:** 1.0  
**Tarih:** 2026-06-05  
**Hazırlayan:** Claude / AI Geliştirme  
**Proje:** Solariz CPS Server — `C:\Solariz_CPS_SERVER`

---

## 1. CPS NEDİR?

**CPS (Central Production System)**, Solariz fabrikasının tüm operasyonel verilerini tek bir dijital omurgada toplayan, web tabanlı, Flask/Python ile geliştirilmiş bir yönetim sistemidir.

Teknik altyapı:
- **Backend:** Python 3 / Flask (blueprint mimarisi)
- **Veritabanı:** SQLite (`mock_data.db` + `solariz_dev.db`)
- **Frontend:** Jinja2 template + Vanilla JS (framework yok)
- **Erişim:** LAN üzerinden tarayıcı (`http://sunucu_ip:8080`)
- **Yetki sistemi:** RBAC (`sistem_rol` + `sistem_yetki` + `@yetki_gerekli` decorator)

---

## 2. SOLARİZ İÇİN AMACI NEDİR?

Solariz'in fabrika operasyonunu kağıt, Excel ve dağınık sistemlerden kurtararak **tek bir dijital merkeze** taşımak:

| Hedef | Açıklama |
|-------|----------|
| **Üretim takibi** | Günlük/saatlik üretim kayıtları, A/B slot |
| **Personel yönetimi** | Kimlik, ekip, görev, devam, izin |
| **Planlama** | Operasyon raporu, proses takip |
| **Kalıp yönetimi** | Enjeksiyon kalıp master data |
| **Fire analizi** | Üretim fire, gramaj, çift hesabı |
| **Görev sistemi** | Atama, takip, eskalasyon |
| **Finans** | Kur, alım, maliyet (kısmi) |
| **Bildirim** | Anlık uyarı, push (planlanan) |

---

## 3. ŞU AN ÇALIŞAN MODÜLLER

| Modül | URL | Durum |
|-------|-----|-------|
| **Enjeksiyon** | `/enjeksiyon` | ✅ STABIL — ENJ_CORE_SNAPSHOT_V1 |
| **Kalıp Master** | `/yonetim/kalip-yonetimi` | ✅ STABIL — FAZ2 tamamlandı |
| **Operasyon Raporu** | `/planlama/operasyon-raporu` | ✅ STABIL |
| **Fire V1** | (enjeksiyon içi) | ✅ STABIL |
| **Yönetim Paneli** | `/yonetim` | ✅ Aktif |
| **Core Organizasyon** | `/yonetim/core-organizasyon` | ✅ Aktif |
| **Görev Sistemi** | `/tasks` | ✅ Aktif |
| **Hedef/Plan** | `/hedef` | ✅ Aktif |
| **Personel Giriş** | `/personel-giris` | ✅ Aktif |
| **Usta Paneli** | `/usta` | ✅ Aktif |
| **Canlı Saha** | `/canli-saha` | ✅ Aktif |
| **Finans** | `/finans` | ⚠️ Kısmi |
| **İthalat** | `/ithalat` | ⚠️ Kısmi |
| **Grafik** | `/grafik` | ⚠️ Kısmi |
| **Üretim Yönetim** | `/uretim-yonetim` | ⚠️ Kısmi |
| PDKS | — | ❌ Yok |
| İzin | — | ❌ Yok |
| Maaş/Prim | — | ❌ Yok |
| Kalite/Hata Log | — | ❌ Yok |
| Push Bildirimi | — | ❌ Planlama |

---

## 4. CORE OMURGA NE İŞE YARAR?

CORE, CPS'in organizasyonel hafızasıdır. Kimin kim olduğunu, kimin nerede çalıştığını ve kimin neye yetkisi olduğunu tutar.

```
CORE Katmanları:

  YETKİ KATMANI
  sistem_kullanici → sistem_rol → sistem_rol_yetki
  (kim sisteme giriyor, ne görebiliyor)

  KİMLİK KATMANI
  kullanici_profil ← personel_kullanici (saha)
                   ← sistem_kullanici (ofis)
  (gerçek insanın tek profili)

  ORGANİZASYON KATMANI
  departman_master → ekip_master → kullanici_ekip
                                 → usta_personel_iliskisi
  (kim hangi ekipte, kim kimin ustası)

  YETKİNLİK KATMANI
  kullanici_proses → proses_master_ref
  (kim hangi prosesi yapabilir)
```

Bu omurga olmadan:
- Üretim kaydı kiminle eşleştirilemez
- Görev kime atanacağı bilinemez
- Prim kime ödenecek hesaplanamaz
- Bildirim kime gönderileceği bilinemez

---

## 5. PERSONEL 360 HEDEFİ NEDİR?

Her çalışanın tüm geçmişinin, performansının ve durumunun **tek bir ekranda** görünmesi:

```
Personel 360 Kart
│
├── KİMLİK      — ad, sicil, tip, departman, ekip, üst kişi
├── GÖREV       — açık, tamamlanan, geciken görevler
├── ÜRETİM      — aylık üretim, proses bazlı, vardiya bazlı
├── KALİTE      — fire, hata, düzeltici aksiyon geçmişi
├── PDKS        — devam, gecikme, mesai
├── İZİN        — bakiye, bekleyen talepler, geçmiş
├── MAAŞ/PRİM   — baz maaş, dönemlik prim
├── UYARI       — aktif bildirimler, uyarı geçmişi
└── NOT         — yönetici notları, başarı rozetleri
```

Detaylı plan: `reports/CORE_PERSONEL_360_MASTER_PLAN.md`

---

## 6. GÖREV SİSTEMİ NEREYE BAĞLANIYOR?

```
tasks (görev)
    │
    ├── tasks_users          → atanan kişi (kullanici_profil köprüsü)
    ├── task_logs            → geçmiş olaylar
    ├── task_files           → ek dosyalar
    │
    ├── bildirim_log         → atama/gecikme bildirimi
    │       └── push_service → telefona bildirim (planlanan)
    │
    ├── personel_kullanici   → saha personeli görevi
    ├── sistem_kullanici     → ofis personeli görevi
    │
    └── Personel 360         → görev geçmişi bloğuna beslenir
```

Mevcut durum: Görev sistemi çalışıyor ancak `tasks_users` ile `kullanici_profil` arasındaki otomatik senkronizasyon (`linked_source` / `linked_id`) henüz doldurulmamış.

---

## 7. ÜRETİM / ENJEKSİYON / PLANLAMA BAĞLANTISI

```
enj_gunluk_rapor (günlük vardiya)
    │
    ├── enj_ab_setup         → kalıp, aktif göz, KBÇ (A/B slot)
    │       └── enj_kalip    → Kalıp Master (gramaj, pişme, durum)
    │
    ├── enj_saatlik_kayit    → saatlik tur + SNAPSHOT (freeze)
    │       ├── uretilen_a, uretilen_b
    │       └── tur_kapasitesi_*_snapshot (ag × kbc — değişmez)
    │
    └── enj_gunluk_ozet → operasyon_raporu
            ├── toplam_tur, toplam_uretim
            ├── fire_kg, toplam_fire_cift
            └── KPI hesapları

uretim_kayit (saha personeli üretimi)
    ├── personel_id → personel_kullanici
    ├── usta_id     → usta bağlantısı
    └── proses      → proses_master_ref
```

**Kritik kural (ENJ_CORE_SNAPSHOT_V1):**
- Setup varsa → sadece `setup.ag × setup.kbc` kullanılır
- Geçmiş kayıt hiçbir zaman değişmez
- A ve B slot tamamen bağımsız

---

## 8. FİNANS / İTHALAT / SATIN ALMA HEDEFİ

### Mevcut Durum

| Modül | Durum | Notlar |
|-------|-------|--------|
| Finans | Kısmi | Kur takibi, temel gider kayıtları |
| İthalat | Kısmi | Parti takibi, gümrük/tedarikçi |
| Satın Alma | Yok | Planlama aşamasında |

### Hedef Bağlantılar

```
Satın Alma Siparişi
    │
    ├── Tedarikçi Master     → firma, kur, teslim süresi
    ├── Hammadde Stok        → giriş/çıkış takibi
    ├── Kalıp Master         → kalıp bazlı hammadde ihtiyacı
    └── Üretim Planlama      → stok → üretim → fire dengesi
```

Finans → İthalat → Stok → Üretim → Fire döngüsü kurulduğunda maliyet analizi mümkün olacak.

---

## 9. ŞU AN EKSİK KALAN ALANLAR

| Alan | Öncelik | Not |
|------|---------|-----|
| PDKS (devam takibi) | YÜK | Personel 360'ın temeli |
| İzin yönetimi | YÜK | PDKS'e bağımlı |
| Maaş/Prim | ORTA | İzin + PDKS + üretim bağlantısı |
| Kalite/Hata log | ORTA | Enjeksiyonla entegre olacak |
| Push bildirim altyapısı | ORTA | `personel_iletisim` + FCM |
| Satın alma modülü | DÜŞÜK | Finans modülüne bağımlı |
| Personel 360 UI | YÜK | Mevcut data var, UI yok |
| `kullanici_profil` ↔ `personel_kullanici` köprü temizliği | YÜK | Veri temizliği |
| Org tablo migration'ları | ORTA | DB'de var, repoda CREATE yok |
| Mobil uygulama | GELECEK | Push + 360 hazır olunca |
| YZ karar sistemi | GELECEK | Tüm veri hazır olunca |

---

## 10. RİSKLER

| Risk | Seviye | Açıklama | Çözüm |
|------|--------|----------|-------|
| ENJ_CORE bozulması | KRİTİK | Snapshot mantığına müdahale | Dokunulmaz kural — tag'li |
| DB büyümesi | ORTA | SQLite tek dosya, prod için sınır | Zamanında PostgreSQL geçişi planla |
| Parçalı kimlik veri | ORTA | 3 ayrı tabloda kullanıcı | Profil köprü temizliği (P0) |
| Firewall erişim sorunu | ORTA | IP değişince laptop bağlanamıyor | Statik IP veya firewall kuralı |
| Maaş veri güvenliği | ORTA | Şifrelenmemişse risk | Kolon şifreli + rol kısıtı |
| Legacy DB (solariz_dev.db) | DÜŞÜK | Ayrı dosya, bcrypt şifreler | Zamanında mock_data'ya migrasyon |
| Commit'siz migration'lar | DÜŞÜK | Org tabloları repoda CREATE yok | Migration script'lerini repoya ekle |

---

## 11. BUNDAN SONRAKI DOĞRU GELİŞTİRME SIRASI

### Kısa Vadeli (1–4 hafta)

```
1. Firewall / ağ erişim kararlı hale getir
2. Personel 360 Sprint P1-MINI (mevcut veriyi göster, yeni tablo yok)
3. kullanici_profil ↔ personel_kullanici köprü temizliği
4. PDKS Sprint P2 (devam takibi)
5. İzin Sprint P3
```

### Orta Vadeli (1–3 ay)

```
6. Maaş/Prim Sprint P4
7. Push bildirim altyapısı Sprint P5
8. Kalite/Hata log modülü
9. Finans → Satın Alma köprüsü
10. Stok takip modülü
```

### Uzun Vadeli (3–12 ay)

```
11. Mobil uygulama (React Native / Flutter)
    → PDKS QR giriş
    → Görev listesi
    → Bildirim alımı
12. YZ karar destek sistemi
    → Üretim anomali tespiti
    → Prim önerisi
    → Personel performans tahmini
13. PostgreSQL geçişi (ölçeklenme)
14. Çoklu fabrika desteği
```

---

## 12. ADEM'İN NİHAİ HEDEFİ

**CPS'in Solariz'in merkezi işletim sistemi olması.**

```
BUGÜN:
  Kağıt + Excel + dağınık sistemler
  ↓
CPS V1 (şu an):
  Enjeksiyon + Kalıp + Fire + Operasyon Raporu + Görev + Org
  ↓
CPS V2 (hedef):
  + Personel 360
  + PDKS + İzin + Maaş/Prim
  + Kalite/Hata
  + Stok + Satın Alma
  ↓
CPS V3 (gelecek):
  + Mobil uygulama
  + Push bildirim
  + YZ karar desteği
  + Çoklu fabrika
```

### Tek Omurga Vizyonu

```
KİŞİ ─────────────────────────────────────────┐
  kullanici_profil                              │
  departman_master / ekip_master                │
                                                ▼
GÖREV ──────────► tasks ──────────► bildirim_log ──► push
                                                ▲
ÜRETİM ─────────► uretim_kayit                 │
  enj_saatlik_kayit                             │
  enj_gunluk_rapor ──────────────► Operasyon Raporu
                                                │
FİNANS ─────────► finans_kayit                 │
  ithalat / stok / satın alma                   │
                                                │
KALİTE ─────────► kalite_hata_log ─────────────┘

         TÜMÜ → Personel 360 Kart
         TÜMÜ → YZ Karar Sistemi (gelecek)
```

**Sonuç:** Her çalışanın performansı, her makinenin üretimi, her siparişin durumu ve her kararın geçmişi tek bir sistemden okunabilir olacak. Bu sistem Solariz'in kurumsal hafızası ve yönetim beyni olacak.

---

## EK: STABIL NOKTALAR

| Tag | İçerik |
|-----|--------|
| `STABLE_ENJ_CORE_SNAPSHOT_V1` | Enjeksiyon motoru — DOKUNULMAZ |
| `STABLE_KALIP_MASTER_FAZ2_FULL_PASS` | Kalıp Master — STABIL |
| `STABLE_FIRE_4_1_UI_REFRESH_WARNING_PASS` | Fire V1 — STABIL |
| `STABLE_ENJ_KALIP_FIRE_V1_FULL_PASS` | Genel V1 — STABIL |

**Bu stabil noktalar üzerine inşa edilir. Hiçbiri bozulmaz.**
