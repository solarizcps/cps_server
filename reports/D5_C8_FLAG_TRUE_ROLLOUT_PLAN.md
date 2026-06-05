# D5 C.8 - FLAG=True ROLLOUT PLAN (UYGULAMA YOK, SADECE TASARIM)

**Tarih:** 18.05.2026 09:58
**Durum:** PLAN (FLAG hala False, uygulama yapilmamis)
**Onay durumu:** Adem'in ozel onayi bekleniyor

---

## C.8 AMACI

USE_CPS_NATIVE_PROSES = False -> True. Lazy hook aktif olur. Sahaya emir geldikce
otomatik trigger calisir, CPS doldurulur. 5055 fallback hala calisir (hata sigortasi).

---

## 1. HANGI EMIRLE TEST EDILECEK?

### Onerilen test emirleri (RECON sonucu - yapilan_adet=0, sahaya etki minimal):

| Emir | tip | cari | Beklenen eslesme |
|------|-----|------|------------------|
| **111006** | M | Sahin Taban Solariz Fab Usd | Atki LCW (varsayilan) |
| 111011 | M | Capone - Pera | Atki LCW (varsayilan) |
| 111014 | M | Terteks (Twigy) | Atki LCW (varsayilan) |
| 111015 | Y | None | Asagi is indirme (tip=Y) |
| 111016 | Y | None | Asagi is indirme (tip=Y) |

### Yontem
1. FLAG False iken **dry-run** ile yukaridaki her emiri kontrol et (/sablon/trigger-test)
2. Beklenen sonuclari onayla
3. FLAG True flip
4. Saha **gercek emir** ile (mesai sirasinda emir gelirse) otomatik trigger gozle
5. Veya **manuel** olarak yukaridaki 5 emir icin /prosesler/<emir_no> cagir

### Tehlikeli alanlar
- yapilan_adet > 0 olan emirler (uretim baslamis, trigger karistirma riski)
- Korgun'da olmayan emirler (zaten trigger atlanir, sorun yok)
- 5055_IMPORT'tan gelen emirler (CPS dolu, hook devreye girmez)

---

## 2. HANGI SAAT PENCERESI UYGUN?

### Saha aktivite analizi (Memory'den)
- 08:00-12:00: Yogun (sabah mesai)
- 12:00-13:00: Ogle arasi (**ideal**)
- 13:00-17:00: Yogun
- 17:00 sonrasi: **Ideal**
- Akşam/gece: Cok dusuk (saha kapali)

### Onerim
- **C.8 flip zamani:** 12:30 ogle arasi VEYA 17:30 mesai sonu
- **Gozlem suresi:** 30-60 dakika
- **Yedek karari:** Sorun cikarsa 17:30+ saatinde rollback (saha minimum etkilenir)
- **Saha bilgilendirme:** Halil'e onceden haber (test penceresi sirasinda saha ne goruyorsa raporlamasi)

---

## 3. FLAG=True YAPILINCA BEKLENEN DAVRANIS

### Sahanin gozune ne degisir?
- **Hicbir sey gorunmez** (cunku CPS_NATIVE ve CPS_NATIVE_TRIGGERED ayni gosterimde)
- Beklenmeyen iyi yan etki: bos CPS olan emirler aniden 4-5 proses gosterir

### Backend ne degisir?
\\\
GET /personel-giris/prosesler/110626 (CPS bos, Korgun'da yok, 5055'te var)
  -> CPS oku bos
  -> ADIM 1.5: FLAG=True, Korgun cagir
    -> meta=None (Korgun'da yok)
    -> hook'tan cikilir
  -> ADIM 2: 5055 fallback -> LEGACY_5055_SNAPSHOT
\\\

\\\
GET /personel-giris/prosesler/111006 (CPS bos, Korgun'da var)
  -> CPS oku bos
  -> ADIM 1.5: FLAG=True, Korgun cagir
    -> meta={cari: Sahin Taban, tip: M, ...}
    -> _eslesme_bul -> varsayilan -> sablon Atki LCW
    -> _sablon_uygula_internal -> INSERT 4 satir
    -> CPS tekrar oku -> 4 satir
    -> veri_kaynagi='CPS_NATIVE_TRIGGERED'
    -> return jsonify(result)
\\\

### DB etkisi
- emir_alt_proses'a yeni satirlar (kaynak='CPS_TRIGGER_C5:...')
- uretim_kayit DOKUNULMAZ (trigger sadece INSERT, saha personeli kayit girince artar)

---

## 4. YANLIS ESLESME OLURSA GERI DONUS

### Senaryolar

**A) Yanlis sablon eklendi (orn: M emire atki sablonu)**
\\\powershell
# /sablon/geri-al P6 sonrasi CPS_TRIGGER kapsiyor
# Session'li POST:
POST /hedef/sablon/geri-al
Body: {"emir_no_listesi": ["111006"]}
\\\
4 kayit aktif=0 olur. Saha tekrar bos goruyor. Onayli mevcut akisi devam.

**B) Cok fazla emir yanlis eslesti (toplu rollback)**
\\\powershell
# C.8 FLAG flip'i geri al
Copy-Item "app\config.py.YEDEK_C8_<ts>" "app\config.py" -Force
# Flask reload bekle
# Sonra son 1 saatin trigger kayitlarini topla
\\\

\\\sql
-- Tum FLAG=True suresinde olusan trigger kayitlarini gor
SELECT emir_no, COUNT(*), MIN(created_at), MAX(created_at)
  FROM emir_alt_proses
 WHERE kaynak LIKE 'CPS_TRIGGER_C5%'
   AND aktif = 1
   AND created_at >= '<FLAG_TRUE_BASLAMA_TIME>'
 GROUP BY emir_no
 ORDER BY emir_no;
\\\

**C) Lazy hook hata veriyor (saha 500 aliyor)**
\\\powershell
# P4 once durumuna don
Copy-Item "app\modules\personel_giris\routes.py.YEDEK_D5_FAZC5_P4_<ts>" "app\modules\personel_giris\routes.py" -Force
\\\

---

## 5. PERSONEL EKRANINDA NE DEGISIR?

### Onceden (FLAG=False)
- Boş CPS + 5055'te var: LEGACY_5055_SNAPSHOT
- Boş CPS + 5055'te yok: BOS LISTE
- Dolu CPS: CPS_NATIVE

### Sonra (FLAG=True)
- Boş CPS + Korgun'da var: **trigger CALISIR -> CPS doldurulur -> CPS_NATIVE_TRIGGERED**
- Boş CPS + Korgun'da yok + 5055'te var: LEGACY_5055_SNAPSHOT (degismez)
- Boş CPS + her ikisinde de yok: BOS LISTE (degismez)
- Dolu CPS: CPS_NATIVE (degismez)

**Saha tarafindan gozle gorunur tek fark:** Daha az "bos liste" ekrani. CPS otomatik dolar.

---

## 6. KAC DAKIKA GOZLEM?

### Faz 1: FLAG flip + ilk 5 dakika
- Tum kritik endpoint'leri kontrol
- /health, /prosesler, /kaydet hala 200
- Hata logu temiz mi
- Hicbir 500 yok

### Faz 2: 5-30 dakika
- Ilk trigger INSERT'lerini gozle
- CPS_TRIGGER_C5 kayitlar artiyor mu
- Saha aktivite normal mi
- Korgun cagrilari 5sn altinda kaliyor mu

### Faz 3: 30-60 dakika
- Belirgin pattern gozlem
- Hatali eslesme var mi (varsayilan kuralin urettigi soru isaretleri)
- DB size patlamiyor mu

**Toplam onerim:** 60 dakika gozlem, sorun yoksa **C.8 onayli**.

---

## 7. ROLLBACK KOMUTU

### Hizli rollback (sadece FLAG flip)
\\\powershell
# config.py yedek al
20260518_095857 = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item "app\config.py" "app\config.py.YEDEK_C8_20260518_095857" -Force

# FLAG False yap (manuel duzenleme)
# Veya yedek dosyadan don:
Copy-Item "D:\Firma_Ozel\adem\yedeklemeler\STABLE_D5_FAZC5_P4_LAZY_HOOK_OK_20260518_095857\config.py" "app\config.py" -Force

# Flask auto-reload 5 sn
# Yeni trigger calismaz
\\\

### Deep rollback (P4 hook'unu da geri al)
\\\powershell
# personel_giris da geri al
Copy-Item "D:\Firma_Ozel\adem\yedeklemeler\STABLE_D5_FAZC5_P4_LAZY_HOOK_OK_20260518_095857\personel_giris_routes.py" "app\modules\personel_giris\routes.py" -Force
\\\

### Komple rollback (P1-P6 hepsi)
\\\powershell
# Tum app/ geri al (en tehlikeli)
Copy-Item "D:\Firma_Ozel\adem\yedeklemeler\STABLE_D5_FAZC5_ONCESI_P4_FULL_20260518_093937\app" "app" -Recurse -Force
\\\

---

## 8. 5055 FALLBACK KALACAK MI?

**EVET. 5055 fallback kalacak (kapatma YOK).**

### Sebepleri
- Korgun'da olmayan ama 5055'te var olan emirler icin sigorta
- 5055 hala canli sistem (port 5055)
- Lazy hook hata verirse fallback'e dusulur
- Saha mobil cihazlarda zaten 5055 ve 8080 yan yana

### C.8 sonrasi 5055 fallback akisi
\\\
CPS bos:
  - Korgun'da var -> trigger -> CPS doldur (YENI)
  - Korgun'da yok + 5055'te var -> LEGACY_5055_SNAPSHOT (DEVAM)
  - Her ikisinde de yok -> [] (DEVAM)
\\\

5055'i kapatma plani sirasiyla **C.9 sonrasi** veya **D6** sprint'inde olabilir.

---

## 9. C.8 SONRASI C.9 FINAL VERIFY LISTESI

### Sistem health
- [ ] /personel-giris/health 200 (1 saat boyunca her dakika kontrol)
- [ ] /personel-giris/kaydet POST 200 (saha kayit girisi)
- [ ] /personel-giris/login POST 200 (saha login)
- [ ] /hedef/sablon 200 (admin yonetim)
- [ ] Tum mevcut endpoint'ler ayni cevap

### Veri butunlugu
- [ ] uretim_kayit bozulmadi (sadece artiyor, eski kayitlar korunuyor)
- [ ] emir_alt_proses'ta CPS_TRIGGER_C5 sayisi makul (asiri patlama yok)
- [ ] sablon_id INSERT'lerde dolu (P6 audit kanitli)
- [ ] DB integrity ok

### Trigger metrigi (FLAG=True suresinde)
- [ ] Korgun call success rate > %95
- [ ] Trigger latency < 3 saniye (saha mobil bekleme suresi)
- [ ] Hatali eslesme orani < %5 (saha geri bildirim)
- [ ] /sablon/trigger-test ve /sablon/trigger arasi tutarlilik

### Audit ve gozlem
- [ ] CPS_TRIGGER_C5 kayitlari Korgun_Anomali raporlarinda gozukmuyor
- [ ] Saha personeli "yeni gelen prosesler" sikayetinde yok
- [ ] Halil'in test onayi (Yonetim rolu)
- [ ] 24 saatlik canli izleme + raporlama

### Performance
- [ ] /prosesler/<emir_no> response time < 2 sn
- [ ] Korgun query rate makul (Korgun loglarinda spike yok)
- [ ] CPS DB locking veya wait yok

### Yedekleme
- [ ] C.8 sonrasi STABLE snapshot al
- [ ] C.9 verify rapor yazilir
- [ ] memory update

---

## OZET

| Konu | Karar |
|------|-------|
| C.8 uygulama | Henuz YOK |
| FLAG | False (degismedi) |
| 5055 | Kapatma YOK |
| Scheduler | Baslatma YOK |
| Test emri | 111006 (yapilan=0, Sahin Taban) |
| Saat | 12:30 ogle arasi VEYA 17:30 sonrasi |
| Gozlem | 60 dakika |
| Rollback | 3 seviyeli (flag-only / hook+flag / full) |
| Sonraki sprint | C.8 - ozel onay sonrasi |