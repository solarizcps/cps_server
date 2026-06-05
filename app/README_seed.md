# CPS Seed Script'leri — Kullanım Rehberi

Bu dökümandaki araçlar **mock (geliştirme) ortamı** için veri üretir.
Prod ortamında çalışmazlar.

## 1. `init_mock_db.py` — Temel Seed

### Ne yapar?
Sıfırdan bir `mock_data.db` (SQLite) oluşturur ve **core demo verisiyle** doldurur.

### Oluşturduğu veri
- **Kullanıcılar:** admin, hasan, samet, muhasebe, cin.ofis (+ roller)
- **Müşteri/tedarikçi:** M001–M005 (Kaplan, LCW, Esem, DeFacto, Koton) + T001–T004 (Çin tedarikçileri) + **M099** (Parça 6 demo)
- **Çin Siparişler:** CIN-2026-0001 (tamamlandı, 2 sevkiyatlı), 0002 (onaylı), 0003 (taslak), 0005 (Parça 6 demo)
- **Sevkiyatlar:** SVK-0001 (teslim, konteyner), 0002 (hazırlık, uçak), 0003 (DHL numune), 0004 (parçalı sevkiyat demo — CIN-0001'e ikinci sevkiyat), 0005 (**Parça 6 / UAT Senaryo 9 — farklı tarihli 3 masraf**)
- **Fiyat Teklifleri:** 3 teklif (SIPARIS_OLDU, ALINDI, TR REDDEDILDI)
- **Finans:** 7 anlaşma, plan satırları, cari hareketler, Koton anlaşması 1. taksit GELDI
- **Kurlar:** USD 39.35 / EUR 43.00 / CNY 5.40 (bugün) + 4 geçmiş tarihli kur (demo için)

### Kullanım

```bash
python init_mock_db.py
```

Yeni bir DB oluşturur. Mevcut `mock_data.db` varsa üstüne yazar.

**Temiz başlangıç için:**
```bash
del mock_data.db && python init_mock_db.py
```
(Windows CMD) ya da:
```bash
rm mock_data.db && python init_mock_db.py
```

---

## 2. `seed_performans.py` — Performans/Yük Verisi (opsiyonel)

### Amaç
Yoğun veri altında liste/detay sayfalarının hızını test etmek. **`init_mock_db.py`'nin ürettiği core veri bozulmaz** — sadece ek olarak `[PERF-SEED]` marker'lı kayıt eklenir.

### Komutlar

```bash
python seed_performans.py small      # 20 sipariş + 40 sevkiyat + 200 masraf + 30 teklif
python seed_performans.py medium     # 50 sipariş + 80 sevkiyat + 400 masraf + 80 teklif  [DEFAULT]
python seed_performans.py large      # 150 sipariş + 240 sevkiyat + 1200 masraf + 200 teklif
python seed_performans.py clean      # Sadece [PERF-SEED] kayıtlarını sil
python seed_performans.py status     # Mevcut [PERF-SEED] sayılarını göster
```

### Kullanım örneği — performans testi

```bash
# 1. Temiz başlangıç
rm mock_data.db
python init_mock_db.py

# 2. Performans verisi ekle
python seed_performans.py medium

# 3. Uygulamayı aç, liste sayfalarını test et
python app.py
# → http://127.0.0.1:5057/grafik/siparis (55 sipariş)
# → http://127.0.0.1:5057/grafik/sevkiyat (85 sevkiyat)
# → http://127.0.0.1:5057/grafik/teklif (83 teklif)
# → http://127.0.0.1:5057/finans/cari (39 müşteri)

# 4. Bittiğinde temizle (core veri dokunulmaz)
python seed_performans.py clean
```

### `clean` ne siler?

Yalnızca şu şartları sağlayan kayıtlar:
- `grafik_cin_siparis.Notlar LIKE '[PERF-SEED]%'`
- `grafik_sevkiyat.Notlar LIKE '[PERF-SEED]%'`
- `grafik_fiyat_teklif.Notlar LIKE '[PERF-SEED]%'`
- `finans_anlasma.Notlar LIKE '[PERF-SEED]%'`
- `Cari_Kart.CName LIKE '[PERF]%'` (PM100, PM101, ...)
- `Cari_Har.Aciklama LIKE '[PERF-SEED]%'`
- Bunlara bağlı kalem, masraf, dağıtım, plan satırları da silinir

### `clean` **NE SİLMEZ?**
- `CIN-2026-0001..0005` (core siparişler)
- `SVK-2026-0001..0005` (core sevkiyatlar, 3 masraf satırı dahil)
- `M001–M005, M099, T001–T004` (core müşteri/tedarikçi)
- `T*/F*/K*` vs (core finans verileri)
- Parça 6 demo senaryosu (UAT Senaryo 9 verisi) — marker'sız olduğu için korunur

### `status` ne gösterir?

```
=== MEVCUT [PERF-SEED] KAYITLARI ===
  grafik_cin_siparis            :     50
  grafik_cin_siparis_kalem      :    110
  grafik_sevkiyat               :     80
  grafik_sevkiyat_masraf        :    411
  ...
  TOPLAM:    968 kayıt
```

---

## 3. Prod Koruması

Her iki script de iki koşuldan biri varsa exit eder:

1. `.production` dosyası proje kökünde bulunuyorsa
2. Environment değişkeni `CPS_ENV=production`

**Örnek:**
```bash
touch .production
python seed_performans.py medium
# ⛔ HATA: Bu script PROD ortamda çalışmaz!
```

Prod'a dağıtırken `.production` dosyasını bırakmak koruma sağlar.

---

## 4. Sık Sorulan

**Q: `seed_performans.py medium` iki kez çalıştırırsam ne olur?**
A: İlkinde 968 kayıt ekler, ikincisinde random seed aynı olduğu için aynı SiparisNo'lar çakışır ve hata verir. Önce `clean` çalıştırın.

**Q: PERF verisi ile core veri karışır mı?**
A: Hayır. Her PERF kaydı `[PERF-SEED]` veya `[PERF]` marker'lı. Filtreleme ve temizleme bu marker üzerinden yapılır.

**Q: Parça 6 demo (SVK-0005) PERF sayılır mı?**
A: Hayır. SVK-0005 core demo verisi olarak init_mock_db.py içinde oluşturulur, marker'ı yok. `clean` dokunmaz.

**Q: PERF verisi açıkken app çalıştırırsam performansı etkilenir mi?**
A: Evet — hedef bu. Liste sayfaları 50+ sipariş / 85+ sevkiyat ile yüklenir.

**Q: Production'a geçmeden tüm test verisini nasıl temizlerim?**
A:
```bash
rm mock_data.db
# ya da tüm tabloları truncate et + kendi prod seed'ini çalıştır
```
