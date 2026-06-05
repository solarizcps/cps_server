# CPS MENÜ / YETKİ DB KONTROL RAPORU
**Tarih:** 05.06.2026  
**Kaynak:** `app/mock_data.db` — Sadece Okundu, Değiştirilmedi  
**auth.py:** `yetki_var(kod)` → `sistem_rol_yetki` tablosunu okur

---

## 1. ROLLER (sistem_rol)

| Id | RolAd | SuperAdmin | Aktif |
|----|-------|-----------|-------|
| 1 | **Yönetim** | ✅ 1 | ✅ |
| 2 | Muhasebe | 0 | ✅ |
| 3 | Çin Ofis | 0 | ✅ |
| 4 | Gümrük | 0 | ✅ |
| 5 | Grafik | 0 | ✅ |
| 6 | Personel | 0 | ✅ |
| 31 | Uretim | 0 | ✅ |
| 32 | **Planlama** | 0 | ✅ |
| 33 | Kalite | 0 | ✅ |
| 34 | İdari İşler | 0 | ✅ |
| 35 | **Enjeksiyon** | 0 | ✅ |

> **Not:** `Sistem Yöneticisi` adında ayrı bir rol yok. `admin` kullanıcısı RolId=1 (Yönetim) + SuperAdmin=1 üzerinden çalışıyor.

---

## 2. KRİTİK YETKİ KODLARI — DB VARLИК KONTROLÜ

| Yetki Kodu | DB'de Var mı? | Id |
|------------|-------------|-----|
| `yonetim` | ✅ Var | 150 |
| `planlama` | ✅ Var | 138 |
| `enjeksiyon` | ✅ Var | 135 |
| `planlama.enjeksiyon.kalip` | ✅ Var | 154 |

**Tüm yetki kodları DB'de mevcut. Eksik yetki kaydı yok.**

---

## 3. ROL BAZLI YETKİ ATAMALARl

### Yönetim Rolü (Id=1 — SuperAdmin=1)

`auth.py` satır 135–136:
```python
if is_superadmin(user_dict):
    return {'*'}   # TÜM yetkiler açık
```

`SuperAdmin=1` olduğu için `yetki()` fonksiyonu her kod için `True` döndürür.  
DB'de `planlama`, `enjeksiyon`, `yonetim` kayıtları **ayrıca atanmamış**.

| Yetki | DB'de Atanmış | SuperAdmin ile Geçer |
|-------|-------------|---------------------|
| `yonetim` | ✅ | ✅ |
| `planlama` | ❌ **YOK** | ✅ (SuperAdmin) |
| `enjeksiyon` | ❌ **YOK** | ✅ (SuperAdmin) |
| `planlama.enjeksiyon.kalip` | ✅ | ✅ |

> **SuperAdmin** olduğu için `planlama` ve `enjeksiyon` DB'de atanmamış olsa da `yetki()` fonksiyonu `True` döndürüyor. Bu rol için menü **tam görünür olmalı**.

---

### Planlama Rolü (Id=32)

| Yetki | Atanmış | can_view |
|-------|---------|---------|
| `planlama` | ✅ | ✅ |
| `enjeksiyon` | ✅ | ✅ |
| `planlama.enjeksiyon.kalip` | ✅ | ✅ |
| `planlama.operasyon_raporu` | ✅ | ✅ |
| `hedef` | ✅ | ✅ |
| `yonetim` | ❌ **YOK** | ❌ |

> Planlama rolü `yonetim` yetkisi **almamış**. Base.html'de "Üretim" ve "Yönetim" menü grupları `yetki('yonetim')` gerektirir. Enjeksiyon Takip linki ise hem `yetki('yonetim')` (blok A) hem `yetki('planlama')` (blok B) ile erişilebilir. Planlama için blok B aktif.

---

### Enjeksiyon Rolü (Id=35)

| Yetki | Atanmış | can_view |
|-------|---------|---------|
| `enjeksiyon` | ✅ | ✅ |
| `enjeksiyon.saha` | ✅ | ✅ |
| `planlama.enjeksiyon.kalip` | ✅ | ✅ |
| `planlama.operasyon_raporu` | ✅ | ✅ |
| `hedef` | ✅ | ✅ |
| `tasks` | ✅ | ✅ |
| `planlama` | ❌ **YOK** | ❌ |
| `yonetim` | ❌ **YOK** | ❌ |

> Enjeksiyon rolü kasıtlı olarak dar tutulmuş. `FERHAT_SAHA_MENU_V3` bloğu (base.html satır 790) bu role özel yazılmış. Tasarım doğru.

---

### Diğer Roller Özet

| Rol | yonetim | planlama | enjeksiyon | planlama.enjeksiyon.kalip |
|-----|---------|---------|-----------|--------------------------|
| Yönetim (Id=1) | ✅ (SA) | ✅ (SA) | ✅ (SA) | ✅ |
| Planlama (Id=32) | ❌ | ✅ | ✅ | ✅ |
| Enjeksiyon (Id=35) | ❌ | ❌ | ✅ | ✅ |
| Muhasebe (Id=2) | ❌ | ❌ | ❌ | ❌ |
| Kalite (Id=33) | ❌ | ❌ | ❌ | ❌ |
| Uretim (Id=31) | ❌ | ❌ | ❌ | ❌ |

*(SA = SuperAdmin bypass, DB'de kayıt olmasa da True döner)*

---

## 4. KULLANICILAR VE ROLLERİ

| Kullanıcı Adı | Ad | Rol |
|-------------|-----|-----|
| `admin` | Sistem Yöneticisi | **Yönetim** (SuperAdmin) |
| `halil` | Halil | **Yönetim** (SuperAdmin) |
| `altan` | Altan TERZİ | **Yönetim** (SuperAdmin) |
| `mehmet` | Mehmet ÇORABCI | Planlama |
| `mehmetemin` | Mehmet Emin Bakırcı | Planlama |
| `ferhat` | Ferhat Usta | **Enjeksiyon** |
| `alpay` | Alpay Dülger | ❌ RolId=None |

> **Kritik:** `alpay` kullanıcısının RolId=None. Bu kullanıcı giriş yapsa `kullanici_yetkileri()` boş set döndürür (`is_superadmin` False, `rol_id` yok). Hiçbir menü görünmez.

---

## 5. SORUNUN KÖK ANAL İZİ

### Yönetim/admin ile giriş yapıldığında menüde ne görünmeli?

```
auth.py satır 135: is_superadmin → True → yetki seti = {'*'}
yetki('yonetim')   → '*' in yk → True  ✅
yetki('planlama')  → '*' in yk → True  ✅
yetki('enjeksiyon')→ '*' in yk → True  ✅
```

**Yönetim rolü ile TÜM menüler görünür olmalı.**

---

### O zaman neden görünmüyor olabilir?

**Cevap: Duplicate `data-grup="uretim"` sorunu (base.html)**

base.html satır 679 ve 773'te iki ayrı "Üretim" başlıklı blok var:

```
Blok 1 (satır 679): {% if yetki('yonetim') %}
  → data-grup="uretim"
  → İçinde: Hedef, Enjeksiyon Takip, Üretim Girişi, Şablon, Sapma

Blok 2 (satır 773): {% if yetki('planlama') %}
  → data-grup="uretim"   ← AYNI ID!
  → İçinde: sadece Enjeksiyon Takip
```

**DOM'da aynı anda iki `data-grup="uretim"` elementi var.**

Accordion JS kodu:
```javascript
var body = sb.querySelector('.sn-grup[data-grup="' + grup + '"]');
```

`querySelector` **ilk eşleşeni** alır. İkinci blok toggle edilmek istendiğinde JS yanlış elementi açıp kapatıyor. Görsel olarak "Üretim" grubunu tıklamak yanlış davranış sergiliyor.

---

### `alpay` kullanıcısı için sorun

`RolId = None` → `kullanici_yetkileri()` boş set → hiçbir koşullu menü görünmez.  
Bu ayrı bir kullanıcı veri sorunu.

---

## 6. NET SONUÇ

| Soru | Cevap |
|------|-------|
| Yetki kodları DB'de var mı? | ✅ Hepsi var |
| Yönetim rolü yetkisi var mı? | ✅ SuperAdmin, hepsi True |
| Planlama rolü yetkisi var mı? | ✅ planlama + enjeksiyon + kalip var |
| Enjeksiyon rolü doğru mu? | ✅ Kasıtlı dar, FERHAT_SAHA mantığı doğru |
| DB'de eksik kayıt var mı? | ⚠️ alpay kullanıcısının RolId=None |
| Sorunun kökü nerede? | **base.html'de duplicate `data-grup="uretim"`** |

---

## 7. GEREKLİ DÜZELTMELER (Onay Bekliyor)

### Düzeltme 1 — base.html duplicate grup (KRİTİK)

**Dosya:** `app/templates/base.html` satır 772–787

```
Mevcut: data-grup="uretim"  (Planlama bloğu)
Öneri:  Bu bloğu SİL.
        Enjeksiyon Takip linki zaten Blok 1 içinde var (satır 717).
        Planlama bloğu gereksiz duplicate.
```

### Düzeltme 2 — alpay kullanıcısı RolId=None (ORTA)

`alpay` kullanıcısına bir rol atanmalı veya Aktif=0 yapılmalı.  
Onaysız dokunulmadı.

---

*Bu belge sadece okuma ve analiz içermektedir. DB ve kod değiştirilmemiştir.*  
*Düzeltme için açık onay beklenmektedir.*
