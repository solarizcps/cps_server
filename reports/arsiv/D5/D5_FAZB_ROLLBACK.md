# D5 FAZ B — ROLLBACK PLANI

**Tarih:** 2026-05-16 13:42
**Amaç:** Acil durumda D5 Faz B değişikliklerini geri alma rehberi
**Geri dönüş hedefi:** D5 Faz A durumu (Warning Layer aktif, CPS-first değil)

---

## 1. ROLLBACK KAPSAMI

D5 Faz B 2 değişiklik yaptı:
1. **DB:** emir_alt_proses tablosuna 2127 kayıt + legacy_id kolonu
2. **Kod:** routes.py'da prosesler() fonksiyonu CPS-first oldu

**Mevcut yedekler:**
- DB: `mock_data.db.YEDEK_FAZB_20260516_133810`
- Kod: `routes.py.YEDEK_D5_FAZB_20260516_134126`
- Snapshot: `STABLE_D5_FAZB_ONCESI_CPS_NATIVE_MIGRATION_20260516_133210`

---

## 2. KISA ROLLBACK (Sadece Kod)

**Sadece davranış sorunu varsa, DB'ye dokunmadan:**

```powershell
# 1. routes.py'i D5 Faz A'ya geri al
$kaynak = "D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\modules\personel_giris\routes.py.YEDEK_D5_FAZB_20260516_134126"
$hedef = "D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\modules\personel_giris\routes.py"

Copy-Item $kaynak $hedef -Force

# 2. Servisi restart
Stop-ScheduledTask -TaskPath "\Solariz\" -TaskName "Solariz_CPS_8080"
Start-Sleep 2
Start-ScheduledTask -TaskPath "\Solariz\" -TaskName "Solariz_CPS_8080"

# 3. Dogrulama
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest "http://localhost:8080/giris" -Method POST -Body @{kullanici='admin';sifre='f7a6ua61'} -WebSession $session -UseBasicParsing -MaximumRedirection 0 -ErrorAction SilentlyContinue | Out-Null
$r = Invoke-WebRequest "http://localhost:8080/personel-giris/prosesler/110393" -WebSession $session -UseBasicParsing
$j = $r.Content | ConvertFrom-Json
Write-Host "veri_kaynagi: $($j[0].veri_kaynagi)"
# Beklenen: LEGACY_5055_SNAPSHOT (Faz A durumuna donus)
```

**Süre:** ~10 saniye
**Etki:** 
- DB değişmez (emir_alt_proses 2250 kayıt kalır, sadece routes.py 5055 fallback'e döner)
- Saha personeli etkilenmez
- Davranış D5 Faz A ile aynı olur

**Doğrulama:** `/prosesler/110393` artık `LEGACY_5055_SNAPSHOT` döndürmeli.

---

## 3. ORTA ROLLBACK (Kod + DB Veri)

**emir_alt_proses verisinde sorun varsa:**

```powershell
# 1. Önce kod rollback (üstteki adım 1-2)
$kaynak = "D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\modules\personel_giris\routes.py.YEDEK_D5_FAZB_20260516_134126"
$hedef = "D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\modules\personel_giris\routes.py"
Copy-Item $kaynak $hedef -Force

# 2. DB'den 5055_IMPORT kayıtlarını sil (legacy_id kolonu kalsın, ama veri silinsin)
$pyClean = @'
import sqlite3
DB = r"D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\mock_data.db"
conn = sqlite3.connect(DB)
conn.execute("BEGIN")
try:
    cur = conn.execute("DELETE FROM emir_alt_proses WHERE kaynak = '5055_IMPORT'")
    silinen = cur.rowcount
    conn.commit()
    print(f"[OK] Silinen: {silinen} kayit")
    
    # Manuel ve sablon kayıtlar dokunulmamış olmali
    manuel = conn.execute("SELECT COUNT(*) FROM emir_alt_proses WHERE kaynak='manuel'").fetchone()[0]
    sablonlu = conn.execute("SELECT COUNT(*) FROM emir_alt_proses WHERE kaynak LIKE 'sablon:%'").fetchone()[0]
    print(f"  Manuel kayit: {manuel}")
    print(f"  Sablonlu kayit: {sablonlu}")
except Exception as e:
    conn.execute("ROLLBACK")
    print(f"[HATA] {e}")
finally:
    conn.close()
'@
$pyClean | Out-File "$env:TEMP\fazb_rollback.py" -Encoding utf8
& "C:\Users\Administrator\AppData\Local\Programs\Python\Python315\python.exe" "$env:TEMP\fazb_rollback.py"

# 3. Servisi restart
Stop-ScheduledTask -TaskPath "\Solariz\" -TaskName "Solariz_CPS_8080"
Start-Sleep 2
Start-ScheduledTask -TaskPath "\Solariz\" -TaskName "Solariz_CPS_8080"
```

**Süre:** ~15 saniye
**Etki:**
- 2127 import kaydı silinir
- 123 manuel/sablon kayıt dokunulmaz
- legacy_id kolonu DB'de kalır (zararsız)
- Davranış D5 Faz A öncesi durumuna döner

---

## 4. TAM ROLLBACK (Full DB Restore)

**Tüm DB durumunu geri istersek:**

```powershell
# 1. Önce kod rollback (Section 2)
$kaynak_kod = "D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\modules\personel_giris\routes.py.YEDEK_D5_FAZB_20260516_134126"
$hedef_kod = "D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\modules\personel_giris\routes.py"
Copy-Item $kaynak_kod $hedef_kod -Force

# 2. Servisi DURDUR (DB'ye yazma kesinti)
Stop-ScheduledTask -TaskPath "\Solariz\" -TaskName "Solariz_CPS_8080"
Start-Sleep 3

# 3. DB'yi yedek'ten geri yukle
$kaynak_db = "D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\mock_data.db.YEDEK_FAZB_20260516_133810"
$hedef_db = "D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\mock_data.db"

Copy-Item $hedef_db "$hedef_db.ROLLBACK_BACKUP_$(Get-Date -Format yyyyMMdd_HHmmss)" -Force
Copy-Item $kaynak_db $hedef_db -Force

# 4. Servis restart
Start-ScheduledTask -TaskPath "\Solariz\" -TaskName "Solariz_CPS_8080"

Write-Host "[OK] Full rollback tamam"
Write-Host "DB durumu D5 Faz B oncesi (123 manuel kayit)"
```

**Süre:** ~30 saniye
**Etki:**
- Migration tamamen geri alınır
- emir_alt_proses 123 kayıta düşer
- Migration sırasında yapılan **tüm üretim kayıtları KAYBOLUR** (1348→1347)

⚠️ **DİKKAT:** Migration sırasında saha personeli 1 yeni üretim girdi (1347→1348). Tam rollback yaparsanız **bu kayıt kaybolur**. Bu yüzden:
- Section 2 (kod rollback) → güvenli
- Section 3 (orta rollback) → güvenli
- Section 4 (tam rollback) → **veri kaybı riski var**

---

## 5. ROLLBACK NE ZAMAN GEREKİR?

| Sorun | Rollback Türü |
|---|---|
| /prosesler endpoint 5xx döndürüyor | **Section 2** (kod) |
| veri_kaynagi yanlış field içeriği | **Section 2** (kod) |
| CPS_NATIVE veri bozuk geliyor | **Section 3** (orta) |
| Frontend tamamen çöktü | **Section 2** (kod) + DEBUG |
| DB corruption şüphesi | **Section 4** (tam, dikkatli) |
| Saha personeli yetkisi etkilendi | Yetki problemi, bu rollback yardımcı olmaz |

---

## 6. ROLLBACK SONRASI DOĞRULAMA

Her rollback sonrası test edin:

```powershell
# 1. Port
netstat -ano | Select-String ":8080.*LISTENING"

# 2. Health
Invoke-WebRequest "http://localhost:8080/personel-giris/health" -UseBasicParsing | Select-Object -ExpandProperty Content

# 3. /prosesler/110393
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest "http://localhost:8080/giris" -Method POST -Body @{kullanici='admin';sifre='f7a6ua61'} -WebSession $session -UseBasicParsing -MaximumRedirection 0 -ErrorAction SilentlyContinue | Out-Null
$r = Invoke-WebRequest "http://localhost:8080/personel-giris/prosesler/110393" -WebSession $session -UseBasicParsing
$j = $r.Content | ConvertFrom-Json
Write-Host "Proses sayisi: $($j.Count)"
Write-Host "veri_kaynagi : $($j[0].veri_kaynagi)"

# 4. emir 110393
$r2 = Invoke-WebRequest "http://localhost:8080/personel-giris/emir/110393" -WebSession $session -UseBasicParsing
Write-Host "EmirMiktar   : $(($r2.Content | ConvertFrom-Json).EmirMiktar)"
```

Beklenen durumlar:
- **Section 2 sonrası:** veri_kaynagi=LEGACY_5055_SNAPSHOT (Faz A)
- **Section 3 sonrası:** veri_kaynagi=LEGACY_5055_SNAPSHOT (Faz A)
- **Section 4 sonrası:** veri_kaynagi=LEGACY_5055_SNAPSHOT (Faz A)

---

## 7. ROLLBACK SONRASı SONRAKİ ADIM

Rollback yapıldıktan sonra:
1. **Sorunu belgele** — neden rollback gerekti, hangi log/error?
2. **Snapshot al** — rollback sonrası durum için
3. **Plan revize et** — sorun nasıl çözülür?
4. **Faz B'yi tekrar dene** — düzeltilmiş plan ile

---

## 8. ÖNEMLI

- ⚠ Rollback **mevcut DB değişikliklerini** geri alır
- ⚠ **Saha personeli üretim kayıtları kaybolabilir** (Section 4)
- ⚠ Rollback sırasında **kısa servis kesintisi** olur
- ✓ Yedekler **kalıcı** (silinmemeli)
- ✓ Faz A yedekleri **korundu** (`routes.py.YEDEK_D5_FAZA_*`)

---

**Oluşturan:** D5 Faz B Rollback Planı
**Yedek Tag:** STABLE_D5_FAZB_ONCESI_CPS_NATIVE_MIGRATION_20260516_133210
**Yedek konum:** D:\Firma_Ozel\adem\yedeklemeler\
