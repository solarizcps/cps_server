# STABLE — CPS 8080 DOĞRU INSTANCE
**Tarih:** 05.06.2026 17:26  
**Klasör:** `C:\Solariz_CPS_SERVER`  
**Durum:** ✅ STABLE — 8080 doğru instance çalışıyor

---

## OLAY ÖZETİ

### Ne Oldu?

Bugün yapılan kontrollerde CPS'in `C:\cps_dev` adlı eski bir kopya klasöründen çalıştığı tespit edildi. Bu kopya `config.py → PORT = 5057` ile yapılandırılmış, git repo değil ve enjeksiyon/kalıp/fire modüllerini içermiyordu. Ekranda "Solariz CPS v0.2 / Faz 1" arayüzü görünüyordu.

### Neden Oldu?

`C:\cps_dev` önceki geliştirme oturumlarından kalan eski bir kopya. Birisi (muhtemelen farklı bir terminal penceresi) bu klasörden `python app.py` çalıştırmış ve port 5057'de açılmıştı.

---

## YAPILAN İŞLEMLER

### 1. Yanlış Processler Kapatıldı

| PID | Kaynak | İşlem |
|-----|--------|-------|
| 12916 | `C:\cps_dev` (reloader child) | ✅ Kapatıldı |
| 12584 | `C:\cps_dev` (ana process, port 5057) | ✅ Kapatıldı |
| 35556 | `C:\cps_dev` (wrapper) | ✅ Kapatıldı |

### 2. Korunan Processler

| PID | Kaynak | İşlem |
|-----|--------|-------|
| 19380 | `D:\finans\finans_server.py` | 🔒 Dokunulmadı |
| 2000 | `D:\finans\finans_server.py` | 🔒 Dokunulmadı |

### 3. Doğru CPS Başlatıldı

```powershell
Set-Location C:\Solariz_CPS_SERVER\app
python app.py
```

**Sonuç:**
- PID: **1432**
- Port: **8080**
- Host: `0.0.0.0`

---

## TEST SONUÇLARI — 10/10 PASS

| Sayfa | Lokal (127.0.0.1:8080) | Ağ (192.168.110.186:8080) |
|-------|----------------------|--------------------------|
| `/` | ✅ 200 | ✅ 200 |
| `/giris` | ✅ 200 | ✅ 200 |
| `/enjeksiyon` | ✅ 200 | ✅ 200 |
| `/yonetim/kalip-yonetimi` | ✅ 200 | ✅ 200 |
| `/planlama/operasyon-raporu` | ✅ 200 | ✅ 200 |

---

## GIT DURUMU

```
M app/mock_data.db   ← runtime değişimi, normal
```

**mock_data.db dışında kod değişikliği yok.** Temiz.

---

## YEDEK

| Alan | Değer |
|------|-------|
| Yol | `C:\CPS_BACKUPS\Solariz_CPS_SERVER_STABLE_8080_CORRECT_INSTANCE_20260605` |
| Boyut | 2.505 MB |
| Tarih | 05.06.2026 17:26 |

---

## BUNDAN SONRA — KURAL

### CPS Başlatma Standardı

```powershell
cd C:\Solariz_CPS_SERVER\app
python app.py
```

### Erişim Adresleri

```
Lokal:   http://127.0.0.1:8080
Ağ:      http://192.168.110.186:8080
```

### Yasaklı

```
❌ C:\cps_dev klasöründen başlatma
❌ Port 5057 üzerinden CPS erişimi (cps_dev imzası)
❌ cps_dev'in app.py veya config.py dosyalarına müdahale
```

---

## AKTİF STABLE NOKTALAR

| Tag | İçerik |
|-----|--------|
| `STABLE_ENJ_CORE_SNAPSHOT_V1` | Enjeksiyon motoru |
| `STABLE_ENJ_KALIP_FIRE_V1_FULL_PASS` | ENJ + Kalıp + Fire tam V1 |
| `STABLE_KALIP_MASTER_FAZ2_FULL_PASS` | Kalıp Master V2 |
| `STABLE_OPR_ENJ_SUMMARY_20260604_PASS` | Operasyon Raporu |
| `STABLE_CPS_CLEAN_REPO_20260604` | Repo temizliği |

---

*Bu stabil nokta koda müdahale içermemektedir.*  
*Sadece instance yönetimi (yanlış process kapatma + doğru klasörden başlatma) yapılmıştır.*
