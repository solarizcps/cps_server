# STABLE — MENU + ALPAY ADMIN
**Tag:** `STABLE_MENU_ALPAY_ADMIN_20260605`  
**Tarih:** 05.06.2026  
**Durum:** ✅ STABLE — Testler geçti, commit hazır

---

## YEDEK

| Alan | Değer |
|------|-------|
| Yol | `C:\CPS_BACKUPS\Solariz_CPS_SERVER_STABLE_MENU_ALPAY_ADMIN_20260605` |
| Dosya sayısı | 23.509 |
| Toplam boyut | ~2505 MB |
| Durum | ✅ Alındı |

---

## DEĞİŞİKLİKLER

### 1) `app/templates/base.html` — MENU_FIX_V1

Menü/yetki görünürlüğü düzeltildi:

| Değişiklik | Açıklama |
|------------|----------|
| `aktif_grup = 'uretim'` | `/enjeksiyon` sayfasında Üretim grubu otomatik açık |
| Duplicate `data-grup="uretim"` kaldırıldı | ENJ_F4_PLANLAMA bloğu silindi (DOM çakışması giderildi) |
| Kalıp Master — Üretim grubu | Yönetim rolünde `yetki('planlama.enjeksiyon.kalip')` ile görünür |
| Enjeksiyon — Planlama grubu | Planlama rolünde `yetki('enjeksiyon') and not yetki('yonetim')` ile görünür |

**Dokunulmayan:** ENJ Core, kalıp hesapları, fire, operasyon raporu route'ları.

### 2) `app/mock_data.db` — ALPAY ADMIN

Tek SQL ile `alpay` kullanıcısı yönetim admin yapıldı:

```sql
UPDATE sistem_kullanici
SET RolId=1, Rol='Yönetim', Tip='sistem'
WHERE KullaniciAdi='alpay';
```

**DB yedeği (işlem öncesi):** `C:\CPS_BACKUPS\mock_data_BEFORE_ALPAY_ADMIN_20260605.db`

| Alan | Değer |
|------|-------|
| KullaniciAdi | alpay |
| AdSoyad | Alpay Dülger |
| RolId | 1 |
| Rol | Yönetim |
| Tip | sistem |
| Aktif | 1 |
| ZorunluSifreDegistir | 1 |

---

## TEST SONUÇLARI

**Ortam:** `http://127.0.0.1:8080` — `C:\Solariz_CPS_SERVER\app`

| Test | Sonuç |
|------|-------|
| admin giriş | ✅ HTTP 200 → `/` |
| alpay giriş | ✅ HTTP 200 → `/sifre-degistir` (beklenen) |
| `/enjeksiyon/` | ✅ admin=200, alpay=200 |
| `/yonetim/kalip-yonetimi` | ✅ admin=200, alpay=200 |
| `/planlama/operasyon-raporu` | ✅ admin=200, alpay=200 |

---

## GIT

**Commit mesajı:**
```
AUTH: fix menu visibility and grant Alpay admin role
```

**Stage edilen dosyalar:**
- `app/templates/base.html`
- `app/mock_data.db`
- `reports/STABLE_MENU_ALPAY_ADMIN_20260605.md`

---

## CANLI STANDARD

| Alan | Değer |
|------|-------|
| Klasör | `C:\Solariz_CPS_SERVER` |
| Çalıştırma | `cd C:\Solariz_CPS_SERVER\app && python app.py` |
| Port | 8080 |
| Adres | `http://192.168.110.186:8080` |

---

## NOTLAR

- `alpay` ilk girişte şifre değiştirmeli (`ZorunluSifreDegistir=1`).
- `alpay` artık `Tip='sistem'` + `RolId=1` (Yönetim, SuperAdmin=1) → tüm menüler görünür.
- ENJ Core / Kalıp / Fire modüllerine dokunulmadı.
