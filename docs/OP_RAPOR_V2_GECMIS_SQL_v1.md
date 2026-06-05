# OP_RAPOR_V2_GECMIS_SQL_v1

Belge tipi: SQL freeze referansi
Belge versiyonu: v1
Olusturma tarihi: 2026-05-15
Patch: OP_RAPOR_V2_GECMIS
Snapshot referansi: STABLE_OP_RAPOR_V2_GECMIS_PRE_PATCH_20260515_153601

---

## 1. Amac

Planlama / Operasyon Raporu sayfasi icindeki yeni GECMIS / EXCEL DETAY
sekmesini besleyen backend endpointinin SQL davranisini freeze etmek.

Bu doku CANLI ekrani DEGISTIRMEZ.
Bu doku yeni endpoint icindir.

---

## 2. Endpoint

GET /planlama/api/operasyon/gecmis

### 2.1 Query parametreleri

| Param        | Zorunlu | Tip        | Aciklama                          |
|--------------|---------|------------|-----------------------------------|
| tarih_bas    | EVET    | YYYY-MM-DD | Inclusive baslangic               |
| tarih_bit    | EVET    | YYYY-MM-DD | Inclusive bitis (>= tarih_bas)    |
| makine_id    | hayir   | INTEGER    | enj_makine.id                     |
| operator     | hayir   | TEXT       | kullanici_adi exact match         |
| kalip_tipi   | hayir   | enum       | GOVDE / ATKI                      |
| vardiya      | hayir   | enum       | gunduz / mesai / gece             |
| durum        | hayir   | enum       | CLS / KLP / ARZ / KPL             |
| arama        | hayir   | TEXT       | LIKE %arama% (5 alan)             |
| sayfa        | hayir   | INTEGER    | Varsayilan 1                      |
| boyut        | hayir   | INTEGER    | Varsayilan 50, max 250            |

### 2.2 Response sozlesmesi (sample)

JSON yapisi:
- ok: true/false
- filtreler: echo parametreler
- sayfalama: toplam_kayit, toplam_sayfa, sayfa, boyut
- tip_dagilimi: tur, ariza, setup adetleri
- kpi: toplam_tur, teorik_cift, net_cift, fire, ortalama_verim_yuzde,
       toplam_ariza_sn, toplam_ariza_hhmmss,
       toplam_kalip_degisim_sn, toplam_kalip_degisim_hhmmss
- satirlar: satir objesi dizisi

### 2.3 Satir objesi alanlari

- satir_tipi: TUR / ARIZA / SETUP
- satir_id: int
- tarih: YYYY-MM-DD
- saat_araligi: HH:MM-HH:MM
- makine: M1 / M2 / ...
- istasyon: M4-1A veya null
- operator: text
- vardiya: gunduz / mesai / gece
- kalip: { kod, kod_eski, tipi }
- tur, teorik_cift, net_cift, fire, verim_yuzde
- ariza_sn, ariza_hhmmss
- kalip_degisim_sn, kalip_degisim_hhmmss
- durum, durum_label
- sebep_ad, sebep_detay, not, gosterim_not
- foto_var
- anomali_seviye (0/1/2), anomali_label

### 2.4 Saha dili durum mapping

| DB durum_ham | Saha label | Renk    |
|--------------|------------|---------|
| CALISIYOR    | CLS        | yesil   |
| SETUP        | KLP        | amber   |
| ARIZA        | ARZ        | kirmizi |
| KAPALI       | KPL        | gri     |

### 2.5 Anomali esikleri

| Sure              | seviye | label              |
|-------------------|--------|--------------------|
| < 7200 sn         | 0      | null               |
| >= 7200 sn (2sa)  | 1      | Uzun sureli (2sa+) |
| >= 14400 sn (4sa) | 2      | ANOMALI (4sa+)     |

---

## 3. SQL - Ana liste sorgusu

SQL freeze edilmis hali asagidaki ayri SQL dosyasinda tutulacak:
docs/sql/operasyon_gecmis_main.sql

(SQL dosyasinin tam icerigi patch fazinda routes.py icinde string olarak
gomulu olacak. Bu doku sadece referans.)

Ana sorgu yapisi:
- 3 CTE: saatlik_olaylar, ariza_olaylar, setup_olaylar
- 1 foto_haritasi CTE
- UNION ALL ile birlestirme
- LEFT JOIN foto_haritasi
- WHERE tarih + opsiyonel filtreler
- ORDER BY tarih DESC, sirala_zaman DESC
- LIMIT + OFFSET

Sure hesabi:
- julianday(end_zaman) - julianday(start_zaman)) * 86400
- meta_json icindeki sure alanlari KULLANILMAZ

START-END eslesmesi:
- Ayni rapor_id + istasyon_id
- start.zaman < end.zaman
- En son START -> END (MAX(start.id) altsorgu)

---

## 4. SQL - Yan sorgular

Yan sorgularin tam SQL'i routes.py icinde olacak:

- KPI ozet: SUM(tur), SUM(teorik), SUM(ariza_sn), SUM(kalip_dgs_sn)
  + SELECT FROM enj_gunluk_rapor (net_cift, fire)
- Tip dagilim: GROUP BY satir_tipi, COUNT(*)
- Toplam kayit: COUNT(*) (pagination)

Verim yuzde Python tarafi:
ortalama_verim_yuzde = 100.0 - (toplam_fire / max(toplam_teorik, 1) * 100)

---

## 5. Python tarafi minimal mantik

Her satir icin Python tarafinda hesaplanacak:

- gosterim_not: sebep_ad + " . " + not (her ikisi varsa)
- anomali_label: seviyeye gore string
- ariza_hhmmss / kalip_degisim_hhmmss: divmod(sn, 3600)
- verim_yuzde: yukaridaki formul

Frontend (.js) HICBIR hesap yapmaz. Backend bitmis veri doner.

---

## 6. Patch invariantlari

- Bu endpoint YENI route. Mevcut endpoint'ler dokunulmaz.
- Mevcut CANLI sekme dokunulmaz.
- enj_ tablolarinin schema'si dokunulmaz.
- uretim_kayit schema'si dokunulmaz.
- Korgun veritabani okunmaz, yazilmaz.
- 30 saniye query timeout uygulanir.
- Sidebar'a yeni sayfa eklenmez.

---

## 7. Test plani

| Test                  | Beklenen                                          |
|-----------------------|---------------------------------------------------|
| Bos tarih             | 400 hata, "tarih_bas zorunlu"                     |
| tarih_bit < tarih_bas | 400 hata, "tarih_bit, tarih_bas'tan kucuk olamaz" |
| Bos sonuc             | ok:true, satirlar [], KPI hepsi 0                 |
| Tek gun (15.05)       | Sample veri ile uyumlu sonuc                      |
| boyut=500             | 250'ye clamp edilir                               |
| Durum=ARZ filtre      | Sadece ARIZA satirlari                            |
| Anomali 2sa+          | anomali_seviye=1 dogru isaretlenir                |
| Anomali 4sa+          | anomali_seviye=2 dogru isaretlenir                |

---

## 8. Bilinen kisitlamalar (V1)

1. Foto rapor bazli - bir gunun raporunda foto varsa o gundeki TUM
   satirlarda foto_var=true. Olay bazli ayrim V2'de.
2. Operator JOIN yok - kullanici_adi text alanindan direkt. Ferhat saha
   testinde gercek isim akisini dogrulayacagiz.
3. Saatlik tur icin net/fire/verim NULL - Bu degerler sadece gunluk
   rapor seviyesinde tutuluyor. Saatlik dagitim V2'de.
4. Anomali sadece sure bazli - Diger anomali tipleri (cok fire, dusuk
   verim, vb) V2+.

---

## 9. Surum

| Surum | Tarih      | Aciklama   |
|-------|------------|------------|
| v1    | 2026-05-15 | Ilk freeze |

Freeze sonrasi degisiklik v2 olarak ayri belge.