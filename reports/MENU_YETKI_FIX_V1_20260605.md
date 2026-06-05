# MENÜ/YETKİ DÜZELTMESİ — FAZ 1
**Tag:** `MENU_FIX_V1`  
**Tarih:** 05.06.2026  
**Durum:** ✅ TAMAMLANDI — Testler geçti

---

## YEDEK

| Alan | Değer |
|------|-------|
| Yol | `C:\CPS_BACKUPS\Solariz_CPS_SERVER_BEFORE_MENU_YETKI_FIX_20260605` |
| Durum | ✅ Alındı |

---

## YAPILAN DEĞİŞİKLİK

**Tek dosya:** `app/templates/base.html`

### Değişiklik 1 — aktif_grup: enjeksiyon sayfasında Üretim grubu açık

**Satır ~362 — Eklendi:**
```jinja
{% if active == 'enjeksiyon' %}{% set aktif_grup = 'uretim' %}{% endif %}
```

**Neden:** `/enjeksiyon` sayfasında sidebar'da "Üretim" grubu otomatik açık gelmiyordu.

---

### Değişiklik 2 — Yönetim rolünde Kalıp Master Üretim grubunda da görünsün

**Satır ~721 — Eklendi (Üretim grubu içine):**
```jinja
{% if yetki('planlama.enjeksiyon.kalip') %}
  <a href="/yonetim/kalip-yonetimi">Kalıp Master</a>
{% endif %}
```

**Neden:** Yönetim rolü `yetki('yonetim')` ile Üretim grubuna giriyor. Kalıp Master linki sadece Planlama grubunda vardı. Yönetim rolü Planlama grubuna da girebiliyor ama `yetki('planlama.enjeksiyon.kalip')` SuperAdmin bypass ile zaten True olduğu için burada da görünür.

---

### Değişiklik 3 — Duplicate `data-grup="uretim"` bloğu kaldırıldı

**Satır ~772-787 — Silindi (`ENJ_F4_PLANLAMA_START` bloğu):**

```html
<!-- KALDIRILDI -->
{% if yetki('planlama') %}
  <div data-grup="uretim">...</div>   ← DUPLICATE
  <div data-grup="uretim">...</div>   ← DUPLICATE
{% endif %}
```

**Neden:** DOM'da iki `data-grup="uretim"` elementi accordion JavaScript'ini bozuyordu. `querySelector` ilk eşleşeni alıyor, ikinci blok toggle edilemiyor.

**Yerine:** Açıklayıcı yorum satırı bırakıldı.

---

### Değişiklik 4 — Planlama grubuna Enjeksiyon linki eklendi

**Satır ~845 — Eklendi (Planlama grubu içine):**
```jinja
{% if yetki('enjeksiyon') and not yetki('yonetim') %}
  <a href="/enjeksiyon/">Enjeksiyon Takip</a>
{% endif %}
```

**Neden:** Planlama rolü `yetki('enjeksiyon')` atanmış ama Planlama menüsünde enjeksiyon linki yoktu. `not yetki('yonetim')` koşulu ile Yönetim rolünde duplicate olmasını önlüyoruz (Yönetim zaten Üretim grubundan görüyor).

---

## ROL BAZLI MENÜ DURUMU (DÜZELTME SONRASI)

| Rol | Enjeksiyon | Kalıp Master | Operasyon Raporu |
|-----|-----------|-------------|-----------------|
| **Yönetim / admin** | ✅ Üretim grubu | ✅ Üretim grubu | ✅ Planlama grubu |
| **Planlama** | ✅ Planlama grubu | ✅ Planlama grubu | ✅ Planlama grubu |
| **Enjeksiyon (ferhat)** | ✅ Saha grubu (sade) | ❌ | ❌ |

---

## TEST SONUÇLARI — 5/5 PASS

| Sayfa | Sonuç |
|-------|-------|
| `/` | ✅ 200 |
| `/giris` | ✅ 200 |
| `/enjeksiyon` | ✅ 200 |
| `/yonetim/kalip-yonetimi` | ✅ 200 |
| `/planlama/operasyon-raporu` | ✅ 200 |

---

## GIT STATUS

```
M  app/mock_data.db        ← runtime, normal
M  app/templates/base.html ← bu düzeltme
```

**ENJ, Kalıp, Fire, Planlama routes — dokunulmadı.**

---

## DEĞIŞMEYEN KURALLAR

- ENJ Core sabitlendi → routes.py değiştirilmedi
- DB değiştirilmedi
- `alpay` kullanıcısı dokunulmadı (ayrı karar gerekiyor)
- Enjeksiyon rolü sade kaldı (FERHAT_SAHA_MENU_V3 korundu)
