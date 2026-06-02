# ENJ_FOTO_V1_PLAN

Belge tipi: Patch plani (V1 hazirlik)
Olusturma tarihi: 2026-05-15
Snapshot referansi: STABLE_OP_RAPOR_V2_GECMIS_DONE_20260515_161612
Durum: PLANLAMA - Henuz patch uygulanmadi

---

## 1. Amac

Enjeksiyon saha ekraninda Ferhat (veya diger operator) fotograf cekip
sisteme yukleyebilsin. Foto kayitlari enj_foto tablosuna dussun.
Operasyon Raporu / Gecmis ekraninda Foto kolonu var/yok gostersin.

V1 odagi: minimum calisir foto akisi.

V2'ye birakilanlar: galeri sistemi, foto duzenleme, OCR, AI analiz,
olay bazli foto iliskisi (saatlik_kayit_id, event_log_id).

---

## 2. Recon bulgulari (15.05.2026)

### 2.1 Mevcut hazir parcalar

| Parca | Durum | Yorum |
|-------|-------|-------|
| enj_foto SQLite tablosu | VAR | 9 kolon, NN'ler dogru |
| Index (rapor_id, tip) | VAR | Migration 003 |
| uploads/ klasoru | VAR | cin_ofis, grafik, ithalat altlari var |
| uploads/enj_foto/ | VAR | H1'de olusturuldu |
| request.files.get('dosya') pattern | VAR | finans/grafik/ithalat'ta ornek |
| GECMIS sekmesinde foto_var | VAR | SQL hazir, JS render hazir |

### 2.2 enj_foto sema (mock_data.db)

```
id              INTEGER PK
rapor_id        INTEGER NN
tip             TEXT    NN
dosya_yolu      TEXT    NN
dosya_ad        TEXT
dosya_boyut     INTEGER
yukleyen_id     INTEGER
aciklama        TEXT
yuklenme_tarih  TEXT    DFLT=datetime('now')
```

Satir sayisi: 0 (hic foto yok).

### 2.3 Eksik parcalar (V1'de yazilacak)

| # | Eksik | Cozum |
|---|-------|-------|
| 1 | db.foto_ekle() helper | enjeksiyon/db.py'ye yeni fonksiyon |
| 2 | POST /enjeksiyon/api/foto/upload endpoint | enjeksiyon/routes.py'ye marker'li blok |
| 3 | saha.html foto UI | Buton + tip select + file input |
| 4 | Foto JS upload akisi | saha.html inline script veya yeni .js |
| 5 | Foto tip mantigi (ARIZA/KALIP/GENEL) | UI seciminden veya event'ten |
| 6 | Boyut/format validasyonu | Backend tarafinda |

### 2.4 saha.html durumu

Suanki saha.html (55 satir) sadece iskelet placeholder.
Banner: 'FAZ 5 iskelet aktif. Tablet icin sade saha ekrani.
R4 mockup birebir HTML F6'da gelecek.'

Bu demek: Saha kabugu henuz yapilmadi. Foto V1'i bu kabuk
olgunlasmadan eklemek anlamsiz. Foto patch'i saha kabugu V1
ile birlikte ele alinacak.

### 2.5 HTTPS / Kamera notu

CPS 8080 portu HTTP uzerinden calisiyor (HTTPS YOK).
Modern tarayicilar getUserMedia API'sini sadece HTTPS'de calistirir.

V1 cozumu: <input type='file' accept='image/*' capture='environment'>
Bu yontem HTTP'de de calisir, kamera acar.
HTTPS gereksinimi YOK.

---

## 3. Endpoint contract (V1)

```
POST /enjeksiyon/api/foto/upload
Content-Type: multipart/form-data

FormData:
  dosya          (file)   zorunlu - image/*
  rapor_id       (int)    zorunlu
  tip            (text)   zorunlu - ARIZA | KALIP | GENEL
  aciklama       (text)   opsiyonel
```

Backend davranisi:
1. Yetki kontrolu (operator/usta/yonetim)
2. rapor_id var mi kontrol (enj_gunluk_rapor)
3. tip dogrula (ARIZA / KALIP / GENEL)
4. Dosya validasyonu:
   - MIME image/jpeg, image/png, image/webp
   - Max boyut: 8 MB
5. Dosya adi olustur: enj_<rapor_id>_<tip>_<ts>_<rnd>.<uzanti>
6. Disk yaz: uploads/enj_foto/<dosya_adi>
7. DB INSERT: enj_foto tablosu
8. JSON donus:

```json
{
  "ok": true,
  "foto_id": 123,
  "dosya_yolu": "uploads/enj_foto/enj_15_ARIZA_20260516_103045_a3f.jpg",
  "dosya_boyut": 1245678
}
```

Hata durumlari:
- 400: rapor_id eksik / tip gecersiz / dosya yok
- 404: rapor bulunamadi
- 413: dosya cok buyuk
- 415: desteklenmeyen format
- 403: yetkisiz

---

## 4. UI davranisi (saha.html'de)

V1'de minimum UI. Saha kabugu V1 ile birlikte design edilecek.

Soyle bir bilesen olabilir:

```
[Foto cek butonu]  -->  modal/inline acilir
  |
  +-- Tip secimi: ARIZA / KALIP / GENEL (radio veya icon)
  +-- Aciklama: opsiyonel text input
  +-- <input type='file' accept='image/*' capture='environment'>
  +-- Yukle butonu  -->  POST endpoint
  +-- Sonuc: 'Foto yuklendi' toast
```

### 4.1 Tip otomatik atama (V2)

V1'de manuel. V2'de:
- ARIZA modunda foto cekilirse otomatik tip='ARIZA'
- Kalip degisim modunda foto cekilirse otomatik tip='KALIP'
- Genel modda manuel veya GENEL

---

## 5. Mobil/tablet davranisi

capture='environment' ozelligi:
- Android Chrome: Kamera dogrudan acar (arka kamera)
- iOS Safari: 'Foto cek / Galeri / Dosya sec' menusu acar
- Tablet (Android): Android Chrome ile ayni davranis

HTTPS olmadan da calisir (file input fallback davranisi).

### 5.1 Bilinen kisitlar

- Live preview yok (kamera direkt aktif, sonra foto)
- Tek seferde tek foto (cogul upload V2)
- Galeri secimi de mumkun (kamera zorlanamaz)

---

## 6. V1 invariantlari

- enj_foto tablo schema'si dokunulmaz
- enj_* diger tablolar dokunulmaz
- Mevcut CANLI ekran ve F9.5.1 endpoint'leri dokunulmaz
- Mevcut operasyon raporu davranisi degismez
- DB'ye BLOB yazilmaz. Dosyalar diske. DB sadece path tutar.
- enj_gunluk_rapor rapor_id'siz foto yazilmaz (FK gibi davran)
- uploads/enj_foto/ disinda dosya yazilmaz

---

## 7. V2 yol haritasi

### 7.1 Olay bazli foto iliskisi

Su an enj_foto sadece rapor_id ile bagli. Bu V1 sadelestirmesi.

V2'de eklenecek:
- enj_foto.saatlik_kayit_id (nullable) - tur bazli foto
- enj_foto.event_log_id (nullable) - ariza/setup bazli foto

Migration ile ALTER TABLE: 2 yeni nullable kolon.
Eski kayitlar (V1 donemi) bu kolonlar NULL kalir.

### 7.2 Galeri ve yonetim

- Foto onizleme grid'i (Operasyon Raporu detay panelinde)
- Foto silme (sadece yukleyen veya yonetim)
- Foto degisikligi audit log

### 7.3 OCR / AI

Cok ilerde:
- PLC ekran fotografindan tartim okuma (OCR)
- Kalip hasari tespiti (CNN)

---

## 8. Patch akisi (gelecekte)

V1 foto patch'i icin sira:

1. Snapshot (Foto patch oncesi): STABLE_FOTO_V1_PRE_PATCH_<ts>
2. uploads/enj_foto/ klasoru (zaten H1'de olusturuldu)
3. db.foto_ekle() helper - enjeksiyon/db.py (BEGIN/END marker)
4. POST endpoint - enjeksiyon/routes.py (BEGIN/END marker)
5. UI degisikligi - saha.html (saha kabugu V1 ile birlikte)
6. JS upload akisi - inline veya static/js/enjeksiyon_saha.js
7. Test:
   - Boyut limit testi
   - Format limit testi
   - Yetki testi
   - rapor_id validasyon testi
   - DB INSERT testi
   - Operasyon Raporu Gecmis foto_var dogru gosteriyor mu
8. Snapshot (sonrasi): STABLE_FOTO_V1_DONE_<ts>

---

## 9. Yarinki Ferhat saha testi iliskisi

Yarinki 10 adimli test foto fonksiyonu icermez:
1. Giris  2. Makine secimi  3. Kalip degisim baslat
4. Kalip sec  5. Kalip degisim bitir  6. Tur gir
7. Operasyon raporu okuma  8. Ariza bildir  9. Ariza kapat
10. Operasyon raporu son kontrol

Foto V1 patch'i Ferhat testi sonrasina birakildi.

Yarinki test sonucu saha kabugu UX'i hakkinda gercek geri bildirim
verecek. Foto bileseni bu geri bildirimle uyumlu tasarlanacak.

---

## 10. Surum

| Surum | Tarih      | Aciklama        |
|-------|------------|-----------------|
| v1    | 2026-05-15 | Plan olusturuldu (kod yok) |

Patch uygulandiginda v2 olarak ayri belge: ENJ_FOTO_V1_RESULT.md

