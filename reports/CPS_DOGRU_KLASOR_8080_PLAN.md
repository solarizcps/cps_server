# CPS DOĞRU KLASÖR — 8080 BAŞLATMA PLANI
**Tarih:** 05.06.2026  
**Klasör:** `C:\Solariz_CPS_SERVER`  
**Durum:** Analiz tamamlandı — Onay bekleniyor

---

## 1. AKTİF KLASÖR

```
C:\Solariz_CPS_SERVER
```

✅ Doğru klasör. Git repo. Tüm stabil taglar burada.

---

## 2. DB DURUMU

| Alan | Değer |
|------|-------|
| Yol | `C:\Solariz_CPS_SERVER\app\mock_data.db` |
| Durum | ✅ Mevcut |
| Boyut | **4.572 KB** |
| Son Değişim | 05.06.2026 07:09 |
| Git Durumu | `M` — runtime değişimi (normal) |

---

## 3. GIT DURUMU

Temiz. Sadece `mock_data.db` modified (runtime yazımı, normal).

Son 3 commit:
```
6192e11  DOCS: add ENJ core architecture and AI development rules
14bfd13  ENJ: fix snapshot using live fallback when setup exists
6f85eec  KALIP: fix null event listener crash on master list load
```

---

## 4. PORT DURUMU

| Port | Durum |
|------|-------|
| **8080** | ✅ **BOŞ** — kullanılabilir |
| **5057** | ⚠️ LISTENING — PID 12584 (yanlış kopya) |

---

## 5. CONFIG AYARLARI

`app/config.py`:
```python
HOST  = '0.0.0.0'
PORT  = 8080
DEBUG = True
```

Güncel CPS zaten 8080 için yapılandırılmış. Sadece doğru klasörden başlatılması yeterli.

---

## 6. PLAN — CPS'İ 8080'DE BAŞLATMAK

### Adım 1 — Yanlış Instance'ı Kapat (ONAY GEREKİYOR)

5057'de çalışan process `C:\cps_dev` kaynaklı:

```powershell
Stop-Process -Id 12916 -Force   # debug reloader child
Stop-Process -Id 12584 -Force   # ana process (5057 LISTENING)
Stop-Process -Id 35556 -Force   # wrapper
```

> **Dokunulmayacak:** PID 19380, 2000 (`D:\finans` — ayrı uygulama)

---

### Adım 2 — Doğru Klasörden Başlat

```powershell
Set-Location C:\Solariz_CPS_SERVER\app
python app.py
```

`config.py → PORT = 8080` → otomatik 8080'de açılır.

---

### Adım 3 — Doğrula

```powershell
netstat -ano | findstr ":8080"
# Beklenen: 0.0.0.0:8080  LISTENING  <yeni PID>
```

HTTP testleri:
```
http://127.0.0.1:8080/
http://127.0.0.1:8080/enjeksiyon
http://127.0.0.1:8080/yonetim/kalip-yonetimi
http://127.0.0.1:8080/planlama/operasyon-raporu
http://192.168.110.186:8080/
```

---

### Adım 4 — Laptop Erişim Adresi

```
http://192.168.110.186:8080
```

---

## 7. ÖZET

| Adım | İçerik | Durum |
|------|--------|-------|
| DB | 4.572 KB, güncel, güvenli | ✅ Hazır |
| Git | Temiz, doğru branch | ✅ Hazır |
| Port 8080 | Boş, kullanılabilir | ✅ Hazır |
| Config | PORT=8080, HOST=0.0.0.0 | ✅ Doğru |
| Process kapatma | PID 35556+12584+12916 | ⏳ **Onay bekleniyor** |
| Başlatma | `cd app && python app.py` | ⏳ Onay sonrası |

---

*Onay verildiğinde: eski processleri kapat → doğru klasörden başlat → test et.*
