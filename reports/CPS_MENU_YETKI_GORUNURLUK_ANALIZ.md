# CPS MENÜ / YETKİ GÖRÜNÜRLÜk ANALİZİ
**Tarih:** 05.06.2026  
**Dosya:** `app/templates/base.html`  
**Durum:** Sadece Analiz — Kod Değiştirilmedi

---

## 1. MEVCUT MENÜ GÖRÜNÜRLÜK KURALLARI

### Genel Çerçeve

`base.html` içindeki sidebar üç katmanlı bir görünürlük mantığı kullanıyor:

```
Katman 1: kullanici_tip (session)
  'sistem'   → tam sidebar görünür
  'personel' → sadece Üretim Girişi
  'usta'     → Hedef + Üretim Girişi + Görevler

Katman 2: yetki() fonksiyonu
  Her menü grubu ayrı bir yetki kontrolüne bağlı
  yetki('yonetim'), yetki('planlama'), yetki('finans') vb.

Katman 3: g_user.RolAd karşılaştırması (satır 257)
  Üst menü tabları (dynNavTabs) için ROL BAZLI istisna
```

---

## 2. MENÜ GRUPLARINDAKİ YETKİ KONTROLLERI

| Menü Grubu | Yetki Koşulu | Satır |
|------------|-------------|-------|
| Genel (Özet, Görevler) | **Koşulsuz** — tüm sistem kullanıcıları | 376 |
| Finans | `yetki('finans')` | 429 |
| Ticaret | `yetki('finans') OR yetki('grafik.tedarikci')` | 586 |
| Üretim (Hedef, Enjeksiyon, Şablon) | `yetki('yonetim')` | 679 |
| Üretim 2. blok (ENJ_F4) | `yetki('planlama')` | 773 |
| Saha (Ferhat blok) | `yetki('enjeksiyon')` | 790 |
| Planlama | `yetki('planlama') OR yetki('yonetim')` | 809 |
| Kalıp Master | `yetki('planlama.enjeksiyon.kalip')` | 865 |
| Kalite / Tasarım | `yetki('grafik.urun') OR yetki('grafik.numune')` | 890 |
| Yönetim | `yetki('yonetim')` | 983 |

---

## 3. ROL BAZLI MENÜ DURUMU

### Sistem Yöneticisi (RolAd = 'Sistem Yöneticisi' veya benzeri)

`yetki()` fonksiyonu bu role genellikle tam yetki verir.  
Ancak **satır 256–259** kritik bir istisna içeriyor:

```html
{# FERHAT_TAB_GIZLE_V1 (15.05.2026) #}
{% if g_user.RolAd != 'Enjeksiyon' %}
<div id="dynNavTabs" class="nav-tabs"></div>
{% endif %}
```

Bu satır sadece **üst tab barını** etkiliyor, sidebar'ı değil.  
Yani Sistem Yöneticisi için üst tab bar **görünür**.

**Sidebar için durum:**

| Menü | Görünür mü? | Neden? |
|------|------------|--------|
| Genel (Özet, Görevler) | ✅ Evet | Koşulsuz |
| Finans | ✅ Evet (eğer yetki varsa) | `yetki('finans')` |
| Üretim grubu | ✅ Evet (eğer yetki varsa) | `yetki('yonetim')` |
| **Enjeksiyon Takip** (Üretim içinde) | ✅ Evet | `yetki('yonetim')` sağlanırsa |
| Planlama grubu | ✅ Evet (eğer yetki varsa) | `yetki('planlama') OR yetki('yonetim')` |
| **Operasyon Raporu** | ✅ Evet | Planlama grubu içinde, koşulsuz link |
| **Kalıp Master** | ⚠️ Sadece | `yetki('planlama.enjeksiyon.kalip')` varsa |
| Yönetim grubu | ✅ Evet | `yetki('yonetim')` |

---

### Enjeksiyon Rolü (RolAd = 'Enjeksiyon')

| Özellik | Durum |
|---------|-------|
| Üst tab bar (dynNavTabs) | ❌ **GİZLİ** — satır 257 açıkça gizliyor |
| Sidebar | `yetki()` sonucuna göre |
| Saha menüsü | ✅ `yetki('enjeksiyon')` varsa "Saha" grubu görünür |
| Üretim grubu | ⚠️ `yetki('yonetim')` gerektiriyor — Enjeksiyon rolünde yoksa görünmez |
| Planlama grubu ENJ linki | ⚠️ `yetki('planlama')` gerektiriyor |
| Yönetim, Finans | ❌ `yetki()` yoksa gizli |

**Sonuç:** Enjeksiyon rolü için özel olarak `FERHAT_SAHA_MENU_V3` bloğu yazılmış (satır 789–804). Bu blok `yetki('enjeksiyon')` varsa "Saha" başlığıyla sadece Enjeksiyon linkini gösteriyor. Temiz ve kasıtlı bir tasarım.

---

### Planlama / Yönetim Rolü

| Menü | Durum |
|------|-------|
| Planlama grubu | ✅ Görünür |
| Operasyon Raporu | ✅ Görünür (Planlama içinde) |
| Kalıp Master | ✅ `yetki('planlama.enjeksiyon.kalip')` varsa görünür |
| Enjeksiyon Takip | ✅ Planlama içinde ENJ_F4 bloğu var |
| Yönetim grubu | ✅ `yetki('yonetim')` varsa |
| Üretim grubu | ✅ `yetki('yonetim')` varsa |

---

## 4. ENJEKSİYON 200 OK AMA MENÜDE NEDEN GÖRÜNMEYEBİLİR?

### Sorunun Kökü

`/enjeksiyon` endpoint'i 200 döndürüyor çünkü route kaydı ve yetki middleware çalışıyor.  
Ancak menüde görünmemesinin **3 olası sebebi** var:

---

**Sebep 1 — Yetki eksikliği (En Olası)**

Enjeksiyon menüsü iki farklı blokta yer alıyor:

```
Blok A (satır 717): Üretim grubu içinde
  Koşul: {% if yetki('yonetim') %}

Blok B (satır 773-786): ENJ_F4_PLANLAMA bloğu
  Koşul: {% if yetki('planlama') %}

Blok C (satır 790-803): FERHAT_SAHA_MENU_V3
  Koşul: {% if yetki('enjeksiyon') %}
```

Eğer aktif kullanıcının `yetki('yonetim')`, `yetki('planlama')` ve `yetki('enjeksiyon')` fonksiyonlarından **hiçbiri** `True` dönmüyorsa, menüde görünmez.

---

**Sebep 2 — Duplicate Üretim Grubu**

Satır 679'da `yetki('yonetim')` ile bir "Üretim" grubu var.  
Satır 773'te `yetki('planlama')` ile AYNI BAŞLIĞI taşıyan ("Üretim") başka bir blok daha var.  
Her ikisi de `data-grup="uretim"` kullanıyor → **DOM'da iki aynı grup ID'si** oluşuyor.  
Bu accordion toggle'ı karıştırabilir, yanlış grubun açılıp kapanmasına yol açabilir.

---

**Sebep 3 — DB'deki yetki kayıtları**

`yetki()` fonksiyonu `sistem_yetki` veya `rol_yetki` tablosundan okuyor.  
Eğer Sistem Yöneticisi rolü DB'de `planlama` veya `yonetim` yetkisine sahip değilse  
template koşulları `False` döner ve menüler render edilmez.

---

## 5. SORUNUN NET AÇIKLAMASI

```
Endpoint çalışıyor          → routes.py blueprint kayıtlı, Flask route aktif
Menüde görünmüyor olabilir  → yetki() False dönüyor veya duplicate grup sorunu

Kontrol edilmesi gereken:
  1) DB'de Sistem Yöneticisi rolüne hangi yetkiler atanmış?
     Tablo: sistem_yetki veya rol_yetki_matrisi
  2) yetki('yonetim') ve yetki('planlama') True mu dönüyor?
  3) Duplicate 'uretim' grup ID sorunu menü açılışını etkiliyor mu?
```

---

## 6. HEDEF DURUM — YETKİ MATRİSİ

Kullanıcı isteğine göre hedef görünürlük:

| Rol | Enjeksiyon Takip | Operasyon Raporu | Kalıp Master | Personel Ekranı (sade) |
|-----|-----------------|-----------------|--------------|----------------------|
| **Sistem Yöneticisi** | ✅ Görünsün | ✅ Görünsün | ✅ Görünsün | — |
| **Yönetim / Admin** | ✅ Görünsün | ✅ Görünsün | ✅ Görünsün | — |
| **Enjeksiyon** | ✅ Sadece bu | ❌ Gizli | ❌ Gizli | ✅ Sade |
| **Planlama** | ✅ Görünsün | ✅ Görünsün | ✅ Görünsün | — |

---

## 7. MİNİMUM DÜZELTME ÖNERİSİ

**Onay gerektirir. Şimdi yapılmadı.**

### Öneri 1 — DB Yetki Kaydı Kontrolü (Öncelikli)

```sql
-- Sistem Yöneticisi rolüne hangi yetkiler atanmış?
SELECT r.RolAd, y.yetki_kodu
FROM sistem_rol r
JOIN rol_yetki y ON r.id = y.rol_id
WHERE r.RolAd = 'Sistem Yöneticisi';
```

Eğer `yonetim` veya `planlama` yoksa → DB'ye ekle.

---

### Öneri 2 — Duplicate Grup Sorunu (Temizlik)

Satır 772–787 (`ENJ_F4_PLANLAMA_START` bloğu):

```html
<!-- Mevcut: data-grup="uretim" kullanıyor, 679. satırla çakışıyor -->
{% if yetki('planlama') %}
  <div class="sn-sec" data-grup="uretim">   ← SORUN
```

**Öneri:** Bu bloğun `data-grup`'unu `"enjeksiyon-planlama"` gibi benzersiz bir değere çek  
veya bu bloğu tamamen kaldırıp Planlama grubunun (satır 809) içine taşı.

---

### Öneri 3 — Kalıp Master Yetki Kaydı

Kalıp Master linki `yetki('planlama.enjeksiyon.kalip')` koşuluna bağlı.  
Bu yetki kodu DB'de yoksa menüde hiçbir zaman görünmez.  
Kontrol: `sistem_yetki` tablosunda `planlama.enjeksiyon.kalip` kaydı var mı?

---

## 8. ÖZET BULGU TABLOSU

| Bulgu | Açıklama | Kritiklik |
|-------|----------|-----------|
| Enjeksiyon endpoint'i çalışıyor | `/enjeksiyon` 200 OK | — |
| Menü görünürlüğü yetki bağımlı | `yetki('yonetim')` veya `yetki('planlama')` gerekiyor | YÜKSEK |
| Duplicate "Üretim" grubu | İki blok aynı data-grup="uretim" kullanıyor | ORTA |
| FERHAT_TAB_GIZLE_V1 | Sadece üst tab barı etkiliyor, sidebar değil | DÜŞÜK |
| Kalıp Master ayrı yetki | `planlama.enjeksiyon.kalip` özel kodu gerekiyor | ORTA |
| Enjeksiyon rolü tasarımı | FERHAT_SAHA bloğu kasıtlı, doğru çalışıyor | — |

---

*Bu belge sadece analiz içermektedir. Kod, DB veya template değiştirilmemiştir.*  
*Düzeltme için onay alınması gerekir.*
