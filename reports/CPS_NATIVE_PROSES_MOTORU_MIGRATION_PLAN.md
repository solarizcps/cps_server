# CPS NATIVE PROSES MOTORU MIGRATION PLANI

**Tarih:** 2026-05-16
**Hedef:** 5055 emir_proses + proses_sablon CPS'e taşıma + native şablon motoru kurulumu
**Kural:** Atomic migration, idempotent, davranış değişimi disipline.

---

## 1. AMAÇ

```
5055'ten CPS'e:
  - 18 proses_sablon kaydı → sablon_master + sablon_proses
  - 2127 emir_proses kaydı → emir_alt_proses
  - Veri kalitesi normalize (trailing comma, çift boşluk)
  - 5055 fallback hâlâ aktif (Faz B karakteri)
  
Sonra (Faz C):
  - Korgun emir gelince CPS otomatik proses üretsin
  - 5055 fallback kapatılsın
```

---

## 2. PATCH ADIMLARI (Sıralı)

### PATCH 1 — Tablo Kurulumu (`migrations/008_proses_motoru_tablolar.py`)

```python
# CREATE TABLE sablon_master, sablon_proses, emir_alt_proses, proses_import_log
# CREATE INDEX (4 adet)
# Sıfır veri INSERT
```

**Risk:** SIFIR (sadece tablo kurulumu)
**Süre:** 2 dk
**Rollback:** `DROP TABLE` x4

### PATCH 2 — 5055 → CPS sablon_master Import

```python
# 5055 snapshot'tan proses_sablon oku
# 18 kayıt için:
#   sablon_master INSERT (SablonAdi, LegacyId, Aktif kararı)
#   sablon_proses INSERT (her proses ad için 1 satır, normalize edilmiş)
# proses_import_log INSERT (audit)
```

**Risk:** DÜŞÜK
**Süre:** 5 dk
**Idempotent:** EVET (LegacyId duplicate kontrolü)
**Rollback:** `DELETE FROM sablon_master WHERE LegacyId IS NOT NULL`

### PATCH 3 — 5055 → CPS emir_alt_proses Import

```python
# 5055 snapshot'tan emir_proses oku (2127 kayıt)
# emir_alt_proses INSERT batch (200'lü gruplar)
# Veri kalitesi normalize:
#   ProsesAdi.strip()
#   re.sub(r'\s+', ' ', ad)
# Kaynak='LEGACY_5055', LegacyEmirProsesId=eski.id
# proses_import_log audit
```

**Risk:** DÜŞÜK
**Süre:** 15 dk (2127 kayıt + batch INSERT)
**Idempotent:** EVET (LegacyEmirProsesId duplicate kontrolü)
**Rollback:** `DELETE FROM emir_alt_proses WHERE Kaynak='LEGACY_5055'`

### PATCH 4 — sablon_proses ↔ emir_alt_proses Ad Eşleştirme

```python
# Her emir_alt_proses için SablonId tahmin et (ad eşleştirme)
# Eşleşme bulunca emir_alt_proses.SablonId UPDATE
# proses_import_log audit
```

**Risk:** DÜŞÜK (sadece UPDATE, veri eklenmez)
**Süre:** 5 dk
**Idempotent:** EVET (zaten dolu olan SablonId'leri atla)
**Rollback:** `UPDATE emir_alt_proses SET SablonId=NULL WHERE Kaynak='LEGACY_5055'`

### PATCH 5 — personel_giris\routes.py Kod Patch

```python
# _5055_conn() → _cps_proses_conn() yeni fonksiyon
# /prosesler/<no> davranışı:
#   1. CPS emir_alt_proses oku
#   2. Bulamazsa _5055_conn() fallback (mevcut kod KORU)
# /emir/<no> aynı şekilde fallback chain
```

**Risk:** ORTA (kod davranışı değişir)
**Süre:** 30 dk
**Davranış değişimi:** SIFIR (CPS varsa CPS, yoksa eski)
**Idempotent:** Hayır (kod değişimi tek seferlik)
**Rollback:** Backup'tan geri yükle

### PATCH 6 — Servis Restart + Doğrulama

```powershell
# Stop-ScheduledTask Solariz_CPS_8080
# Start-ScheduledTask
# 6 sayfa regression test
# personel-giris/prosesler/110393 → CPS'ten gelmeli (Kaynak='CPS')
# Saha personeli üretim yapabiliyor olmalı (test kayıt)
```

**Risk:** ORTA (canlı sistem restart)
**Süre:** 5 dk
**Rollback:** Önceki snapshot geri yükle

### PATCH 7 — Mini Snapshot

```powershell
# STABLE_D5_PROSES_MOTORU_CPS_NATIVE_<ts>
# Sadece app/, docs/, migrations/, reports/
# 5055_snapshot DB de dahil
```

**Risk:** SIFIR
**Süre:** 30 sn

---

## 3. KOD DEĞİŞİKLİĞİ DETAYı (PATCH 5)

### 3.1 Yeni Fonksiyon

```python
# personel_giris\routes.py - ust kisma ekle

def _cps_proses_conn():
    """CPS native emir_alt_proses icin baglanti"""
    return sqlite3.connect(_db_path(), timeout=10)


def _emir_prosesler(emir_no):
    """
    Emir prosesleri al.
    Once CPS emir_alt_proses, sonra 5055 fallback.
    """
    result = []
    
    # 1) CPS-native
    try:
        conn = _cps_proses_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT Id, EmirNo as emir_no, ProsesAdi as proses_adi,
                   HedefMiktar as limit_miktar, OlusturmaTarih as olusturma,
                   'CPS' as veri_kaynagi
              FROM emir_alt_proses
             WHERE EmirNo = ? AND Durum = 'aktif'
             ORDER BY ProsesSira NULLS LAST, Id
        """, (emir_no,)).fetchall()
        conn.close()
        if rows:
            return [dict(r) for r in rows]
    except Exception as e:
        # CPS sorgu hatasi - fallback'e dus
        pass
    
    # 2) 5055 snapshot fallback (mevcut kod)
    try:
        c5055 = _5055_conn()
        rows = c5055.execute("""
            SELECT id, emir_no, proses_adi, limit_miktar, olusturma,
                   'LEGACY_5055' as veri_kaynagi
              FROM emir_proses
             WHERE emir_no = ? AND proses_adi NOT LIKE '%.%'
             ORDER BY id
        """, (emir_no,)).fetchall()
        c5055.close()
        return [dict(r) for r in rows]
    except:
        return []
```

### 3.2 Mevcut Endpoint Güncelleme

```python
# Mevcut prosesler() fonksiyonunu degistir

@personel_giris_bp.route('/prosesler/<int:emir_no>', methods=['GET'])
def prosesler(emir_no):
    """Once CPS, sonra 5055 fallback ile emir prosesleri."""
    try:
        rows = _emir_prosesler(emir_no)
        
        # Her proses icin toplam_girilen hesabi (CPS uretim_kayit)
        ccps = _cps_conn()
        result = []
        for r in rows:
            d = dict(r)
            total = ccps.execute("""
                SELECT COALESCE(SUM(miktar), 0)
                  FROM uretim_kayit
                 WHERE emir_no = ? AND proses_adi = ?
                   AND onay_durum IN ('onaylandi', 'bekliyor')
            """, (emir_no, d['proses_adi'])).fetchone()[0]
            d['toplam_girilen'] = total
            result.append(d)
        ccps.close()
        return jsonify(result)
    except Exception as e:
        return jsonify([])
```

**Davranış değişimi:** Hiç. CPS'te kayıt varsa CPS'ten, yoksa 5055'ten. Frontend'e gönderilen JSON yapısı **birebir aynı** (veri_kaynagi ekstrası eklenir ama frontend ignore edebilir).

---

## 4. UYGULAMA ÖNCESİ KONTROL LİSTESİ

- [ ] Snapshot alınmış mı? (`STABLE_5055_KAPANIS_ONCESI_CPS_NATIVE_PROSES_*`)
- [ ] `D49_OZET.md`, `D4.8_SOIS_MIMARI.md` mevcut mu?
- [ ] mock_data.db boyutu beklenen aralıkta mı? (~2.2 MB)
- [ ] 5055 snapshot DB mevcut mu? (`app\5055_snapshot\solariz.db`)
- [ ] Saha personeli aktif kullanıyor mu? (`netstat 8080` LISTENING)
- [ ] Yedeklemeler klasörü erişilebilir mi?
- [ ] PowerShell admin olarak çalışıyor mu? (Task scheduler için)

---

## 5. UYGULAMA SONRASı DOĞRULAMA

### 5.1 DB Doğrulama

```sql
-- Tablo varlığı
SELECT name FROM sqlite_master WHERE type='table' 
  AND name IN ('sablon_master','sablon_proses','emir_alt_proses','proses_import_log');
-- Beklenen: 4 satır

-- Veri sayıları
SELECT COUNT(*) FROM sablon_master;       -- 18
SELECT COUNT(*) FROM sablon_proses;       -- 64 (18 sablon × ortalama 3.5 proses)
SELECT COUNT(*) FROM emir_alt_proses;     -- 2127
SELECT COUNT(*) FROM proses_import_log;   -- 2145+ (audit)

-- Sablon eşleştirme
SELECT COUNT(*) FROM emir_alt_proses WHERE SablonId IS NOT NULL;
-- Beklenen: ~80%+ (büyük çoğunluk)
```

### 5.2 Endpoint Doğrulama

```powershell
# Login
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest "http://localhost:8080/giris" -Method POST -Body @{kullanici='admin';sifre='f7a6ua61'} -WebSession $session

# /prosesler test
$r = Invoke-WebRequest "http://localhost:8080/personel-giris/prosesler/110393" -WebSession $session
$data = $r.Content | ConvertFrom-Json
$data | Format-Table

# Beklenen:
#   id  emir_no  proses_adi              limit_miktar  veri_kaynagi  toplam_girilen
#   1   110393   gövde basıldı           200           CPS           XX
#   2   110393   gövde çapak alındı      200           CPS           XX
#   ...
```

### 5.3 Davranış Değişimi Kontrolü

| Test | Beklenen |
|---|---|
| Saha personeli login | OK |
| Emir 110393 prosesleri görüntüle | 4 proses (CPS'ten) |
| Üretim kaydı gir (POST /kaydet) | OK, mock_data.db'ye yazılır |
| /gecmis/<pid> | OK, mock_data.db'den |
| canli_saha modülü | OK (etkilenmez) |
| Hedef ekranı | OK (etkilenmez) |

---

## 6. RİSK MATRİSİ

| Risk | Olasılık | Etki | Önlem |
|---|---|---|---|
| Migration sırasında duplicate INSERT | DÜŞÜK | DÜŞÜK | LegacyId UNIQUE check + SKIP |
| Şablon ad eşleştirme yanlış | ORTA | DÜŞÜK | Manuel onay UI ile düzeltilir |
| `/prosesler` endpoint 5xx | DÜŞÜK | ORTA | Try/except mevcut, [] döner |
| 5055 fallback bozulur | DÜŞÜK | DÜŞÜK | Sadece kod görmezse fallback iptal |
| Saha personeli sırasında kesinti | DÜŞÜK | YÜKSEK | Restart 5 sn |
| uretim_kayit korunmaz | YOK | YÜKSEK | uretim_kayit'a HİÇ DOKUNULMUYOR |
| Korgun bağlantısı bozulur | YOK | YÜKSEK | Korgun bağlantısı yok |

---

## 7. UYGULAMA SIRASI (FINAL)

```
ADIM 1: Mini snapshot al (5055_KAPANIS_ONCESI_PROSES_MOTORU)
ADIM 2: PATCH 1 — 4 yeni tablo (migration script)
ADIM 3: PATCH 2 — sablon_master + sablon_proses import (18+64 kayıt)
ADIM 4: PATCH 3 — emir_alt_proses import (2127 kayıt)
ADIM 5: PATCH 4 — SablonId eşleştirme (UPDATE)
ADIM 6: DB doğrulama (4 SQL kontrolü)
ADIM 7: PATCH 5 — personel_giris\routes.py kod patch
ADIM 8: PATCH 6 — Servis restart + endpoint test
ADIM 9: PATCH 7 — Sonuç snapshot
```

**Toplam süre:** ~2-3 saat
**Riskli adım:** PATCH 5 (kod patch)
**Geri dönüş noktası:** PATCH 7 sonrası snapshot

---

## 8. SONUÇ — UYGULAMA İÇİN GEREKLİ

Bu plan **kabul edildiğinde** ihtiyacımız olanlar:

1. **Adem onayı:** "Bu plan ile devam et"
2. **Snapshot teyit:** Yedek alındı mı?
3. **Saha personeli kullanım zamanı:** Yoğun saatlerde mi yoksa mola saatlerinde mi?
4. **PATCH sıralı uygulama:** Her PATCH sonrası kontrol noktası ister miyiz?

---

## 9. EK NOTLAR

### 9.1 canli_saha Modülü Ayrı

Bu plan **sadece personel_giris** için. `canli_saha` modülü ayrı bir geçiş gerektirir:
- `LEGACY_5055_DB` → `mock_data.db.uretim_kayit WHERE kaynak='LEGACY_5055'`
- Bu modül zaten **read-only bridge**, kritik değil
- Ayrı sprint'te ele alınır

### 9.2 emir Tablosu Eksikliği

5055'te `emir` tablosu yok. `/emir/<no>` endpoint'i muhtemelen **Korgun'dan** çekiyor olabilir veya zaten mock_data.db'de tutuluyor. **PATCH 5 öncesi** /emir/<no> kodunu detaylı inceleyeceğiz.

### 9.3 Faz C Hazırlığı

Bu plan **Faz B**'yi gerçekleştiriyor. Faz C (CPS-native şablon motoru, Korgun'dan otomatik proses üretimi) ayrı bir sprint planı gerektirir.

---

**Olusturan:** D5.1 CPS Native Proses Motoru Migration Planı
**İlgili belgeler:**
- `EMIR_PROSES_KAYNAK_RECON.md`
- `5055_KAPANIS_VE_PROSES_MOTORU_PLAN.md`
- `D4.8_SOIS_MIMARI.md`
