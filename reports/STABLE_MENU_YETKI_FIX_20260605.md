# STABLE — MENÜ/YETKİ DÜZELTMESİ FAZ 1
**Tag:** `STABLE_MENU_YETKI_FIX_20260605`  
**Tarih:** 05.06.2026  
**Klasör:** `C:\Solariz_CPS_SERVER`  
**Durum:** ✅ STABLE

---

## YEDEK

| Alan | Değer |
|------|-------|
| Yol | `C:\CPS_BACKUPS\Solariz_CPS_SERVER_STABLE_MENU_YETKI_FIX_20260605` |
| Durum | ✅ Alındı |

---

## DEĞİŞEN DOSYA

**Tek dosya:** `app/templates/base.html`

### Ne Değişti?

| # | Değişiklik | Satır Bölgesi |
|---|-----------|--------------|
| 1 | `aktif_grup = 'uretim'` → `/enjeksiyon` sayfasında da çalışır | ~362 |
| 2 | Kalıp Master linki → Üretim grubuna da eklendi (`yetki('planlama.enjeksiyon.kalip')`) | ~721 |
| 3 | **Duplicate `data-grup="uretim"` bloğu kaldırıldı** (ENJ_F4_PLANLAMA bloğu) | ~772 |
| 4 | Enjeksiyon linki → Planlama grubuna eklendi (`yetki('enjeksiyon') and not yetki('yonetim')`) | ~845 |

---

## DOKUNULMAYAN DOSYALAR

| Dosya | Durum |
|-------|-------|
| `app/modules/enjeksiyon/routes.py` | ✅ Değişmedi |
| `app/modules/enjeksiyon/setup_db.py` | ✅ Değişmedi |
| `app/modules/planlama/routes.py` | ✅ Değişmedi |
| `app/modules/yonetim/routes.py` | ✅ Değişmedi |
| `app/mock_data.db` | ✅ Değişmedi (M = runtime, normal) |

---

## MENÜ GÖRÜNÜRLÜĞÜ (DÜZELTME SONRASI)

| Rol | Enjeksiyon | Kalıp Master | Operasyon Raporu | Yönetim |
|-----|-----------|-------------|-----------------|---------|
| **Yönetim / admin** | ✅ Üretim grubu | ✅ Üretim grubu | ✅ Planlama grubu | ✅ |
| **Planlama** | ✅ Planlama grubu | ✅ Planlama grubu | ✅ Planlama grubu | ❌ |
| **Enjeksiyon (ferhat)** | ✅ Saha (sade) | ❌ | ❌ | ❌ |

---

## TEST SONUÇLARI — 5/5 PASS

| Sayfa | HTTP |
|-------|------|
| `/` | ✅ 200 |
| `/giris` | ✅ 200 |
| `/enjeksiyon` | ✅ 200 |
| `/yonetim/kalip-yonetimi` | ✅ 200 |
| `/planlama/operasyon-raporu` | ✅ 200 |

---

## GIT STATUS

```
M  app/mock_data.db        ← runtime değişimi, normal
M  app/templates/base.html ← bu düzeltme
```

Son commit (değişmedi):
```
6192e11  DOCS: add ENJ core architecture and AI development rules
```

---

## AKTİF STABLE NOKTALAR (GÜNCELLEME)

| Tag | İçerik |
|-----|--------|
| `STABLE_ENJ_CORE_SNAPSHOT_V1` | Enjeksiyon motoru |
| `STABLE_ENJ_KALIP_FIRE_V1_FULL_PASS` | ENJ + Kalıp + Fire tam V1 |
| `STABLE_KALIP_MASTER_FAZ2_FULL_PASS` | Kalıp Master V2 |
| `STABLE_OPR_ENJ_SUMMARY_20260604_PASS` | Operasyon Raporu |
| `STABLE_CPS_CLEAN_REPO_20260604` | Repo temizliği |
| `STABLE_8080_CORRECT_INSTANCE_20260605` | Doğru instance / port |
| **`STABLE_MENU_YETKI_FIX_20260605`** | **Menü görünürlük düzeltmesi** |

---

## SUNUCU DURUMU

| Alan | Değer |
|------|-------|
| Klasör | `C:\Solariz_CPS_SERVER\app` |
| Port | `8080` |
| PID | `1432` |
| Lokal | `http://127.0.0.1:8080` |
| Ağ | `http://192.168.110.186:8080` |

---

*Bu stabil nokta sadece `base.html` menü görünürlük düzeltmesini içermektedir.*  
*ENJ Core, Kalıp, Fire, Planlama mantığına dokunulmamıştır.*
