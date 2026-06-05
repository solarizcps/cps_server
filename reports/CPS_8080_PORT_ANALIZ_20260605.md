# CPS 8080 PORT ANALİZİ
**Tarih:** 05.06.2026 17:30  
**Aktif CPS Klasörü:** `C:\Solariz_CPS_SERVER`  
**Durum:** Sadece Analiz — Hiçbir İşlem Yapılmadı

---

## 1. TÜM PYTHON PROCESSLERİ

| PID | CommandLine | Port | Başlangıç |
|-----|-------------|------|-----------|
| **35556** | `WindowsApps\python.exe app.py` | — | 16:29:03 |
| **12584** | `pythoncore-3.14\python.exe app.py` | **5057** | 16:29:03 |
| **12916** | `pythoncore-3.14\python.exe app.py` | — | 16:29:04 |
| 19380 | `WindowsApps\python.exe D:\finans\finans_server.py` | — | 15:28:46 |
| 2000 | `pythoncore-3.14\python.exe D:\finans\finans_server.py` | **5058** | 15:28:46 |

### Process Hiyerarşisi (app.py)

```
PID 21500  (terminal/PowerShell — artık kapalı)
  └── PID 35556  (WindowsApps python — reloader wrapper)
        └── PID 12584  (pythoncore-3.14 — ANA PROCESS, 5057 dinliyor)
              └── PID 12916  (debug reloader child)
```

Flask `debug=True` iken 3 process başlatır:
- **35556**: Başlatıcı (wrapper)
- **12584**: Ana Flask işlemi — port dinleyen
- **12916**: Hot-reload izleyici (child)

---

## 2. PORT DURUMLARI

| Port | Durum | PID | Ne? |
|------|-------|-----|-----|
| **8080** | ❌ **KAPALI** | — | Kimse dinlemiyor |
| **5057** | ✅ LISTENING | 12584 | Güncel CPS (`app.py`) |
| **5058** | ✅ LISTENING | 2000 | `D:\finans\finans_server.py` |
| 5040 | LISTENING | 9564 | Windows servisi (ilgisiz) |

---

## 3. SORUNUN KÖK NEDENİ — NET TANI

### config.py Karşılaştırması

| Klasör | config.py `PORT` |
|--------|----------------|
| `C:\Solariz_CPS_SERVER\app\config.py` | **PORT = 8080** ✅ |
| `C:\cps_dev\config.py` | **PORT = 5057** ⚠️ |

### Mevcut CPS 5057'de Çalışıyor — Neden?

**Cevap: `C:\cps_dev` klasöründen başlatılmış.**

Kanıt:
- `C:\cps_dev\config.py → PORT = 5057`
- PID 12584, PID 35556 ve PID 12916 aynı anda başlamış (16:29:03–04)
- Parent chain: terminal → 35556 (`WindowsApps\python.exe`) → 12584 → 12916
- `C:\cps_dev` bir git repo değil, ayrı bir kopya
- `C:\cps_dev\app.py` son değişim: **05.06.2026 17:26** (aktif olarak değiştiriliyor)

### Eski Ekranda "Finans/Grafik" Menüsü Neden Görünüyordu?

`C:\cps_dev` eski geliştirme kopyası. `config.py → PORT = 5057` olarak ayarlanmış.  
Bu kopya çalıştırıldığında ekrana "Solariz CPS v0.2 / Faz 1" arayüzü geliyordu.

---

## 4. C:\cps_dev DURUMU

- **Klasör mevcut:** ✅
- **Git repo:** ❌ Değil (`.git` yok)
- **app.py boyutu:** 9.5 KB (güncel CPS app.py = ~310 satır, cps_dev daha küçük = eski sürüm)
- **Son değişim:** 05.06.2026 17:26 (bugün, az önce)
- **İçinde apply_*.py scriptleri:** Eski geliştirme faz scriptleri

---

## 5. DİĞER AKTIF SERVİSLER

| PID | Servis | Port |
|-----|--------|------|
| 2000 | `D:\finans\finans_server.py` | **5058** |
| 19380 | `D:\finans\finans_server.py` (wrapper) | — |

`D:\finans` ayrı bir uygulama (CPS ile ilişkisiz).

---

## 6. WINDOWS BAŞLANGIÇ OTOMATİK BAŞLATMA

| Kontrol | Sonuç |
|---------|-------|
| Task Scheduler (python/cps/flask) | ❌ Kayıt yok |
| `%APPDATA%\Startup` klasörü | ❌ CPS kaydı yok |
| `%ProgramData%\Startup` klasörü | ❌ CPS kaydı yok |
| .bat / .cmd dosyaları (CPS kök) | ❌ Yok |

**CPS otomatik başlatma yok.** Her seferinde elle başlatılıyor.

---

## 7. ÖZET: KİM NEYİ KULLANIYOR?

| Port | Kullanan | Klasör | Durum |
|------|---------|--------|-------|
| **8080** | Kimse | — | Boş, kullanılabilir |
| **5057** | PID 12584 (app.py) | `C:\cps_dev` | ❌ Yanlış kopya çalışıyor |
| **5058** | PID 2000 | `D:\finans` | Ayrı uygulama |

---

## 8. GÜNCEL CPS'İ 8080 STANDARDINA ALMA PLANI

**Hedef:** `C:\Solariz_CPS_SERVER` → port 8080'de çalışsın

### Adım 1 — Yanlış Instance'ı Kapat

```
Kapatılacak: PID 35556, 12584, 12916 (C:\cps_dev kaynaklı)
Korunacak:   PID 19380, 2000 (D:\finans — dokunma)
```

Kapatma komutu (onay alındıktan sonra):
```powershell
Stop-Process -Id 12916 -Force
Stop-Process -Id 12584 -Force
Stop-Process -Id 35556 -Force
```

### Adım 2 — Doğru Klasörden Başlat

```powershell
Set-Location C:\Solariz_CPS_SERVER\app
python app.py
```

`config.py → PORT = 8080` olduğu için otomatik olarak 8080'de başlar.

### Adım 3 — Doğrula

```powershell
netstat -ano | findstr ":8080"
# Beklenen: 0.0.0.0:8080 LISTENING <yeni PID>
```

### Adım 4 — Erişim Adresi

```
Lokal:  http://127.0.0.1:8080
Ağ:     http://192.168.110.186:8080
```

---

## 9. RİSK NOTU

`C:\cps_dev` klasörü **farklı bir DB kullanıyor olabilir** veya **DB dosyasını paylaşıyor** olabilir.  
Eğer `mock_data.db` aynıysa geçişte veri kaybı olmaz.  
Eğer `cps_dev` kendi DB'sine yazıyorsa güncel kayıtlar farklı yerde olabilir.  
→ **Geçiş öncesi `cps_dev\app\mock_data.db` ile `Solariz_CPS_SERVER\app\mock_data.db` karşılaştırılmalı.**

---

*Bu belge analiz içermektedir. Process kapatma, port değişimi veya restart yapılmamıştır.*  
*Uygulama için açık onay gereklidir.*
