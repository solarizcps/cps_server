# CPS TEK DB STANDARDI — 2026-06-03

## Canlı Ortam

| Alan | Değer |
|------|-------|
| Canlı klasör | `D:\Firma_Ozel\adem\CPS_GIT_TEST` |
| Canlı uygulama | `D:\Firma_Ozel\adem\CPS_GIT_TEST\app` |
| Tek canlı DB | `D:\Firma_Ozel\adem\CPS_GIT_TEST\app\mock_data.db` |
| Server başlatma | `cd D:\Firma_Ozel\adem\CPS_GIT_TEST\app && python app.py` |
| Erişim portu | `8080` (http://127.0.0.1:8080) |

## Kurallar

1. **Server her zaman canlı klasörden çalışır.**
   `D:\Firma_Ozel\adem\CPS_GIT_TEST\app\app.py`

2. **Tüm testler canlı DB ile yapılır.**
   `D:\Firma_Ozel\adem\CPS_GIT_TEST\app\mock_data.db`

3. **`C:\Solariz_CPS_SERVER\app\mock_data.db` test DB'si olarak kullanılmaz.**
   Bu klasör yalnızca geliştirme ve syntax kontrolü içindir.
   Bu DB ile yapılan PASS/FAIL sonuçları geçersiz sayılır.

4. **Başka bir DB ile yapılan test geçersizdir.**
   Canlı doğrulama = canlı DB.

5. **Port 8080 cevap vermiyorsa sırayla:**
   - `netstat -ano | findstr :8080` ile port kontrol
   - `Get-Process python` ile Python process kontrol
   - Çoklu process varsa stale olanları `Stop-Process` ile kapat
   - Tek process ile server yeniden başlat

6. **DB migration sadece server kapalıyken ve DB yedeği alındıktan sonra yapılır.**

## Son Doğrulanmış Durum (2026-06-03)

- Commit: `3430275`
- Rapor 61 — Makine 3: A TUR=54, A ÜRET=54, B TUR=10, B ÜRET=20
- Migrations 018 ve 019 canlı DB'ye uygulandı
- Server port 8080 aktif
