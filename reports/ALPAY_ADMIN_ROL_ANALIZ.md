# ALPAY KULLANICI ROL ANALİZİ — TAM RAPOR
**Tarih:** 05.06.2026  
**Durum:** Sadece Analiz — Değişiklik Yapılmadı  
**Sonuç:** Panelden düzeltme ÇALIŞIR — sadece yapılmadı

---

## 1. ALPAY — HANGİ TABLOLARDA VAR?

| Tablo | Durum | Not |
|-------|-------|-----|
| `sistem_kullanici` | ✅ Var (Id=39) | Asıl giriş hesabı |
| `personel_kullanici` | ❌ Yok | Saha personeli tablosu — ilgisiz |
| `kullanici_profil` | ❌ Yok | CORE profil tablosu — bağlantı kurulmamış |

---

## 2. ALPAY — MEVCUT BİLGİLER

| Alan | Değer | Durum |
|------|-------|-------|
| Id | **39** | — |
| KullaniciAdi | `alpay` | — |
| AdSoyad | `Alpay Dülger` | — |
| Email | `alpay@solariz.com.tr` | — |
| Sifre | `solariz2026` | — |
| **RolId** | **None** | ❌ Sorun |
| Rol | None | ❌ |
| Aktif | 1 | ✅ |
| **Tip** | **None** | ⚠️ `'sistem'` olmalı |
| ZorunluSifreDegistir | 1 | ✅ kasıtlı — ilk girişte şifre değiştirmeli |
| OlusturmaTarih | 2026-06-05 07:09:21 | Bugün oluşturulmuş |
| **SonGirisTarih** | **None** | ⚠️ Hiç giriş yapmamış |

---

## 3. ADMIN HESAP ÖRNEĞİ (Referans)

Çalışan Yönetim hesapları:

| KullaniciAdi | RolId | Tip | Aktif |
|-------------|-------|-----|-------|
| `admin` | **1** | None | ✅ |
| `halil` | **1** | usta | ✅ |
| `altan` | **1** | None | ✅ |

**Hedef:** alpay → `RolId=1`, `Tip='sistem'`

---

## 4. ROLLER

| Id | RolAd | SuperAdmin | Not |
|----|-------|-----------|-----|
| **1** | **Yönetim** | **1** | ← alpay için bu |
| 32 | Planlama | 0 | |
| 35 | Enjeksiyon | 0 | |
| 2 | Muhasebe | 0 | |

**SuperAdmin nasıl çalışır:**  
`auth.py → is_superadmin()`:
```python
if user_dict.get('KullaniciAdi') == 'admin':   # hardcoded
    return True
if user_dict.get('Tip') == 'sistem':
    flag = qone("SELECT SuperAdmin FROM sistem_rol WHERE Id=? AND Aktif=1", (rol_id,))
    if flag and flag.get('SuperAdmin') == 1:
        return True
```

Yani: `Tip='sistem'` + `RolId=1` (SuperAdmin=1) → tüm yetkiler açık.

---

## 5. PANELDEN DEĞİŞİKLİK NEDEN İŞLEMEDİ — KÖK NEDEN

### Audit Log Kanıtı

`sistem_audit` tablosunda alpay için **tek kayıt**:
```
Id=1439 | 2026-06-05 07:09:21 | admin | EKLE | sistem_kullanici | KayitId=39
Aciklama: Kullanıcı eklendi: alpay (Alpay Dülger)
```

**Güncelleme denemesi hiç yapılmamış.** Sadece oluşturma var.

### Oluşturmada Ne Oldu?

`kullanici_yeni` (routes.py satır 44–60):
```python
'RolId': request.form.get('RolId') or None,
```

Form'da `RolId` boş gönderilirse:
```python
int('' or 0) = 0  →  0 or None = None
```

`admin` kullanıcısı alpay'ı oluştururken Rol seçmeden kaydetmiş → `RolId=None`.

### Backend ve Frontend Durumu

| Katman | Durum | Not |
|--------|-------|-----|
| `kullanici_guncelle` endpoint | ✅ Çalışıyor | `UPDATE SET RolId=?` doğru |
| Frontend `<select name="RolId">` | ✅ Var | Form gönderimi doğru |
| `duzenleAc(k)` JS | ✅ Var | `k.RolId || ''` set ediliyor |
| `yetki_secimlik_liste()` | ✅ Var | Tüm roller listeniyor |
| **Güncelleme denemesi** | ❌ **Hiç yapılmamış** | Audit kayıt yok |

---

## 6. SONUÇ

**Panel çalışıyor. Güncelleme denenmedi.**  

`/yonetim/kullanici` sayfasından alpay satırının "Düzenle" butonuna tıklanıp "Yönetim" seçilip kaydedilirse `RolId=1` yazılır.

---

## 7. MİNİMUM ÇÖZÜM SEÇENEKLERİ

### Seçenek A — Panel Üzerinden (Önerilen — Kod/DB Değişikliği Yok)

```
http://192.168.110.186:8080/yonetim/kullanici
→ alpay satırı → Düzenle
→ Rol: "Yönetim" seç
→ Kaydet
```

**Sonuç:** `RolId=1` yazılır, audit log oluşur, temiz.

---

### Seçenek B — DB Doğrudan Update (Panel Çalışmazsa)

```sql
UPDATE sistem_kullanici
SET RolId = 1,
    Rol   = 'Yönetim',
    Tip   = 'sistem'
WHERE KullaniciAdi = 'alpay';
```

**2 alan güncellenir:**
- `RolId = 1` → Yönetim rolü
- `Tip = 'sistem'` → `is_superadmin()` için gerekli

**Etki:** alpay giriş yaptığında:
- `Tip='sistem'` → `_tip_guard` bypass
- `RolId=1` → `SuperAdmin=1` → `yetki()` hepsi True
- Tüm menüler görünür

---

### Seçenek C — CORE Profil Bağlantısı (Uzun Vadeli)

`kullanici_profil` tablosuna alpay kaydı ekle, `kaynak='sistem_kullanici'`, `kaynak_id=39`.  
Şu an zorunlu değil — login için `sistem_kullanici` yeterli.

---

## 8. ÖNERİ

```
Adım 1: Seçenek A — panel üzerinden dene
Adım 2: Eğer olmazsa Seçenek B onayı ver
Adım 3: Tip='sistem' mutlaka set edilmeli (A veya B ile birlikte)
```

---

*Bu belge analiz içermektedir. alpay'a, sistem_kullanici tablosuna dokunulmamıştır.*
