# D6.1 SIGNAL ENGINE - RECON RAPORU

**Tarih:** 18.05.2026
**Sprint:** D6.1 - RECON + Mimari (Patch YOK)

---

## 1. YONETICI OZETI

CPS bugun kayit toplayan sistem. D6.1 ile dusunen sisteme donusum baslayacak.

Veri katmani (D5+D6.0.1 sonrasi) AI sinyalleri uretmek icin yeterli olgun:
- uretim_kayit: 1388 satir, 32 personel, 30+ proses varyanti
- emir_alt_proses: 2282 satir
- proses_alias: 15 varyant -> 6 standart kod
- proses_kategori: 11 standart (sadece 2 std_sn dolu)
- sablon: 5 sablon, 5 aktif kural, 1 varsayilan fallback

Yaklasim: batch + polling, realtime degil. 5dk gecikme yeterli.
Yanlis alarm risk dusuk, otomatik mudahale yok.

---

## 2. MEVCUT VERILERDEN CIKAN SINYALLER

### 2.1 DURGUN_EMIR - VERI HAZIR, EN GUVENLI

P1 recon kaniti:

| Esik | Emir sayisi |
|------|-------------|
| 4 saatte hareket yok | 585 |
| 24 saatte hareket yok | 585 |
| 72 saatte hareket yok | 558 |
| 168 saatte (1 hafta) hareket yok | 510 |

En durgun ornekler (33+ gun durgun): 110519, 110569, 109191, 109194, 109173

- Kaynak: uretim_kayit + emir_alt_proses LEFT JOIN
- Yanlis alarm: dusuk
- Karar: D6.1-B PoC adayi (esik 7 gun)

### 2.2 PERSONEL_BUGUN_0 - VERI HAZIR, RISKLI

P1 recon kaniti (son 30g vs son 1g):

| Personel | 30g ort | bugun | sapma |
|----------|---------|-------|-------|
| ilham jameshev | 4929 | 0 | -100% |
| bahtiyar baytarov | 4212 | 0 | -100% |
| najova tunus | 3784 | 560 | -85% |
| aman hudayberdiyev | 2668 | 1825 | -32% |
| sham koibich | 956 | 185 | -81% |

Risk: yanlis alarm. Tatil/hasta -100% olabilir.
Esik: 30g icinde >=5 gun aktif + bugun 0 + saat >12:00.

### 2.3 ONAY_GECIKMESI - VERI HAZIR

P1 recon kaniti:
- Bekleyen onay: 4 (en eski 11:53:08)
- Bugun gecikme: min=0.7 dk, ort=24.4 dk, max=88.1 dk

Esik: olusturma + 30 dk + bekliyor.
Karar: D6.1-B PoC dahil.

### 2.4 TRIGGER_VARSAYILAN - RISK BULUNDU

- 5 sablon: Atki LCW (aktif), Ilham (pasif), Asagi is indirme, Lcw atki, Esem
- Sablon 1 (Atki LCW) icinde varsayilan kural (oncelik=999)
- 'Hicbir eslesme yoksa -> Atki LCW'

Risk: Emir varsayilan tetiklenirse, yanlis sablon uygulanmis olabilir.
Esik: kaynak LIKE CPS_TRIGGER% + son sablon=Atki LCW + tip='varsayilan'.
Karar: D6.1-B PoC adayi.

### 2.5 HIZ_SAPMA - VERI EKSIK

- proses_kategori 11 satir, sadece 2 std_saniye dolu (Enjeksiyon=35, Capak=30)
- 9 proses NULL

Karar: D6.1 disi, D6.2 ye atildi.

### 2.6 CPS_BOS_KORGUN_AKTIF - RUNTIME

- CPS_TRIGGER kayitlari sadece 2 (111005, 111015 bizim testler)
- Lazy trigger bugun 1 kez otomatik calisti

Karar: Runtime Korgun query pahali. D6.1-E scheduler sonrasi.

### 2.7 5055_FALLBACK - TETIK YOK

- err.log son 5000 satir: 0 LEGACY_5055_WARNING
- C.9 analizinde only_5055=0 emir

Karar: Dusuk oncelik, PoC sonrasi.

### 2.8 EMIR_HEDEF_SAPIYOR - VERI EKSIK

Korgun + standart_saniye + kalan_kayit gerek.
proses_kategori std_saniye eksik -> tam hesap mumkun degil.
Karar: D6.2 ye atildi.

---

## 3. ONERILEN ILK 5 GUVENLI SINYAL

| # | Sinyal | Esik | Ses | Risk |
|---|--------|------|-----|------|
| 1 | DURGUN_EMIR_7G | 168 saat hareket yok | 510/gun | Dusuk |
| 2 | ONAY_GECIKMESI_30DK | olusturma + 30dk + bekliyor | 4-10/gun | Cok dusuk |
| 3 | TRIGGER_VARSAYILAN | CPS_TRIGGER + varsayilan sablon | 0-2/gun | Dusuk |
| 4 | PERSONEL_BUGUN_0 | 30g aktif + bugun 0 + saat>12 | 5-10/gun | Orta |
| 5 | EMIR_AKTIF_DUSURME | aktif=1 -> 0 sebep yok | 0-3/gun | Dusuk |

Tasarim:
- 5 sinyal ayri tip
- Hepsi UI'da goster, kullanici dismiss edebilir
- Hicbiri otomatik mudahale yok
- In-app notification (push degil simdilik)

---

## 4. operasyon_sinyal TABLO ONERISI

    CREATE TABLE IF NOT EXISTS operasyon_sinyal (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        -- Sinyal kimligi
        sinyal_tipi TEXT NOT NULL,
        seviye TEXT NOT NULL,
        -- Konu
        emir_no TEXT,
        proses_adi TEXT,
        proses_kodu TEXT,
        personel_id INTEGER,
        personel_ad TEXT,
        -- Mesaj
        mesaj TEXT NOT NULL,
        aksiyon_onerisi TEXT,
        -- Kaynak
        kaynak TEXT NOT NULL,
        rule_id TEXT,
        -- Durum
        durum TEXT DEFAULT 'AKTIF',
        gorulen_kullanici_id INTEGER,
        gorulen_zaman TEXT,
        cozulen_zaman TEXT,
        cozulen_aciklama TEXT,
        -- Tekrar
        tekrar_sayisi INTEGER DEFAULT 1,
        son_gorulme TEXT,
        -- Meta
        meta_json TEXT,
        olusturma TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX idx_os_tipi_durum ON operasyon_sinyal(sinyal_tipi, durum);
    CREATE INDEX idx_os_emir ON operasyon_sinyal(emir_no);
    CREATE INDEX idx_os_kaynak ON operasyon_sinyal(kaynak);
    CREATE INDEX idx_os_olusturma ON operasyon_sinyal(olusturma);
    CREATE INDEX idx_os_seviye ON operasyon_sinyal(seviye);

Tasarim notlari:
- UNIQUE constraint YOK. Ayni sinyal yeniden tetiklenebilir (tekrar_sayisi++).
- Durum akisi: AKTIF -> GORULDU -> DISMISS (yanlis alarm) veya RESOLVED (cozuldu)
- Seviye: INFO / WARN / CRITIC
- meta_json: tipine ozgu (DURGUN icin son_hareket+gun_durgun)

---

## 5. SCHEDULER ONERISI

### 5.1 Yontem karari

| Yontem | Arti | Eksi |
|--------|------|------|
| Cron | YOK | Windows |
| Windows Task Scheduler | Sistem cap, restart guvenli | Ayri process |
| Flask icinde (APScheduler) | App context | Crash riski |

Karar: Windows Task Scheduler + script
- Script: app/scripts/sinyal_motor.py
- Task: \Solariz\Solariz_Sinyal_Motor (SYSTEM, AtStartup + dakikalik)

### 5.2 Periyot

| Sinyal | Periyot |
|--------|---------|
| DURGUN_EMIR_7G | 30 dk |
| ONAY_GECIKMESI_30DK | 5 dk |
| TRIGGER_VARSAYILAN | 5 dk |
| PERSONEL_BUGUN_0 | 1 saat (saat 12 sonra) |
| EMIR_AKTIF_DUSURME | 5 dk |

### 5.3 Baslangic: MANUEL

D6.1-A/B/C/D yeterli. Halil butonuna basinca calisir.
D6.1-E (scheduler) son patch, opsiyonel.

---

## 6. ILK PoC: DURGUN_EMIR_7G

### 6.1 Neden?
- 510 emir veri hazir
- Veri kalitesi: son_hareket_tarihi guvenilir
- Yanlis alarm dusuk (33 gun durgun emir tartismasiz problem)
- Sahaya etki yok
- AI degil, sade rule

### 6.2 PoC kural

SQL: emir_alt_proses + uretim_kayit JOIN
WHERE aktif=1 AND son_hareket < datetime('now', '-7 days')

### 6.3 PoC akis
1. Halil butonu basar: 'Sinyalleri uret'
2. Rule calisir, 510 emir doner
3. operasyon_sinyal INSERT (idempotent, tekrar_sayisi++)
4. Halil /yonetim/sinyaller acar, listeyi gorur
5. Yanlis alarm icin dismiss eder

### 6.4 Beklenen veri
- 510 sinyal (1 hafta+ durgun)
- Halil bunlardan kac taneni cozer - olcum metrigi

---

## 7. RULE ENGINE - AI ONCESI

### 7.1 Yontem karari

| Yontem | Arti | Eksi |
|--------|------|------|
| JSON dosya | Kolay deploy, version control | Karmasik kural zor |
| DB rule (tablo) | Dinamik, Admin UI | Schema gerek |
| Python hardcoded MVP | Hizli, tip safe | Patch gerek |

Karar: Python hardcoded MVP ile basla, D6.5+ ile DB rule'a gec.

Sebep: Dogru kurallari kesfetme asamasindayiz. Code-as-config en hizli iteration.

### 7.2 MVP yapisi (D6.1-B icin)

app/sinyal/rules.py:
- class Rule (base) - id, sinyal_tipi, seviye, hesapla(conn)
- class R001_DurgunEmir7G(Rule)
- class R002_OnayGecikmesi30(Rule)
- class R003_TriggerVarsayilan(Rule)
- class R004_PersonelBugun0(Rule) [opsiyonel, Adem onayi gerek]
- class R005_EmirAktifDusurme(Rule)

RULES = {'R001': R001_DurgunEmir7G(), ...}

app/sinyal/engine.py:
- run_all_rules(conn) -> liste
- run_rule(rule_id, conn) -> liste
- save_signals(signals, conn) -> insert (idempotent, tekrar_sayisi++)

### 7.3 D6.5+ DB rule plani (gelecek)

CREATE TABLE sinyal_kural (
  id INTEGER PK, rule_id TEXT UNIQUE, sinyal_tipi, seviye, aktif,
  sql_query TEXT, mesaj_template TEXT, aksiyon_template TEXT,
  aciklama, yaratici, olusturma
);

Ama bu D6.5+. Simdi DEGIL.

---

## 8. PUSH ENTEGRASYON (D7 ile baglanti)

### 8.1 Mevcut altyapi
- bildirim_log tablosu var (13 kolon, D3.0 doneminden)
- Push gonderici YOK
- VAPID keys YOK
- Service worker YOK

### 8.2 D6.1 in-app only

Sinyal akisi:
  Sinyal -> operasyon_sinyal INSERT -> bildirim_log INSERT -> Halil UI badge

UI tarafinda:
- /api/sinyal/ozet (badge sayisi: AKTIF sinyal toplam)
- Header'da kirmizi badge '5'
- Halil tikar -> /yonetim/sinyaller acilir

### 8.3 D7 push baglantisi (gelecek)

D7 push sistemi gelince:
- operasyon_sinyal INSERT trigger
- bildirim_log -> push gonderici queue
- VAPID + service worker
- Telefon notification

Bu D7 sprint'i. D6.1 SADECE in-app.

---

## 9. RISKLER

### 9.1 Yanlis alarm

| Sinyal | Yanlis alarm sebebi | Azaltici tedbir |
|--------|---------------------|------------------|
| DURGUN_EMIR_7G | Emir iptal/bekleme ama acik | Iptal listesi karsilastir |
| PERSONEL_BUGUN_0 | Tatil/hasta | PDKS giris/cikis kontrol |
| ONAY_GECIKMESI | Halil yok | Mesai saat filtreleme |
| TRIGGER_VARSAYILAN | Gercek varsayilan kabul edilebilir | Halil dismiss edebilir |

### 9.2 Veri eksikligi
- proses_kategori.standart_saniye 9/11 NULL -> hiz sinyalleri yok
- proses_kodu uretim_kayit'ta %99 NULL (D6.0 ile cozuluyor)
- bildirim_log gonderici yok -> sadece DB INSERT

### 9.3 Saat/tarih guvenilirligi
- datetime now localtime SQLite - server saat bagimli
- Timezone karisikligi - sunucu UTC mi yerel mi
- Test gerek: server saat dogru mu

### 9.4 Korgun gecikme
D6.1-E Korgun query atacaksa 2-5 saniye gecikme normal. Kabul edilebilir.

### 9.5 Personel psikolojisi - EN KRITIK RISK

- PERSONEL_BUGUN_0 sinyali yanlis kullanildiginda 'izlendigi' hissi yaratir
- Sinyal Halil'e gider, personel gormez
- UI'da personel adi gosterilse de 'sayisal degerlendirme yapma' kurali
- Dismiss buton zorunlu (Halil 'tatil' diye not edebilmeli)
- ADEM ONAYI: PERSONEL_BUGUN_0 sinyali aktif olmali mi?

### 9.6 Performans
- DURGUN_EMIR_7G query: 1388 + 2282 satir JOIN
- Hesaplama maliyeti: 30-50ms tahmin
- 5 sinyal x dakikada 1 = saatte 300 query - normal

---

## 10. D6.1 PATCH PLANI

### D6.1-A: TABLO + INIT

- Migration: app/migrations/011_operasyon_sinyal.py
- CREATE TABLE operasyon_sinyal + 5 INDEX
- schema_migrations[011] kaydet
- Idempotent (CREATE TABLE IF NOT EXISTS)

Risk: 1/10 (yeni tablo, INSERT only)
Sure: 30 dk

### D6.1-B: MANUEL SINYAL URETICI

- app/sinyal/__init__.py
- app/sinyal/rules.py (Rule base + R001-R005)
- app/sinyal/engine.py (run_all_rules)
- POST /yonetim/sinyal/uret - manuel tetik
- Cikti: operasyon_sinyal INSERT (idempotent)

Risk: 2/10 (yeni endpoint, INSERT only)
Sure: 1.5 saat

### D6.1-C: LISTE ENDPOINTLERI

- GET /yonetim/sinyal/liste - JSON (filter: tip, durum, seviye)
- GET /yonetim/sinyal/<id> - detail
- POST /yonetim/sinyal/<id>/gor (GORULDU)
- POST /yonetim/sinyal/<id>/dismiss (DISMISS)
- POST /yonetim/sinyal/<id>/cozuldu (RESOLVED)
- GET /api/sinyal/ozet (badge sayisi)

Risk: 2/10 (yonetim modulu append)
Sure: 1 saat

### D6.1-D: YONETIM UI

- templates/yonetim/sinyaller.html
- Tab/filter (Tum / Aktif / Goruldu / Dismiss / Resolved)
- 5 sinyal tipi filtresi
- Tablo: tipi, seviye, emir_no, mesaj, durum, tarih
- Aksiyon butonlari (gor/dismiss/cozuldu)
- KPI: aktif sinyal sayisi (badge)
- GET /yonetim/sinyaller (render)

Risk: 2/10 (yeni template + UI)
Sure: 2 saat

### D6.1-E: SCHEDULER (opsiyonel ilk asamada)

- Windows Task Scheduler: \Solariz\Solariz_Sinyal_Motor
- Script: app/scripts/sinyal_motor.py
- Periyot: dakikalik (kuralin kendi periyodunu kontrol)
- SYSTEM auth, AtStartup + dakikalik

Risk: 3/10 (windows task ekleme)
Sure: 1 saat

### Tahmini toplam: 6 saat

Sprint sirasi: A -> B -> C -> D (manuel testle) -> E

Adem'in karari ile D6.1-E ilk asamada SKIP edilebilir.
Halil manuel butonla PoC test eder.

---

## 11. SONRAKI ADIM

D6.1-A migration plan + onay -> D6.1-B rule engine -> D6.1-C/D admin UI.

D6.1 bittiginde CPS kayit toplayan sistemden dusunen sisteme donusur.
Halil gunde 5-10 sinyal gorur, yanlis alarm 1-2, gercek sorun 5-8 cozulur.

### D6.1 sonra yol haritasi
- D6.2 HIZ_SAPMA - standart_saniye doldur, hiz benchmark
- D6.3 CPS_BOS_KORGUN_AKTIF runtime scheduler
- D6.4 PDKS entegrasyon - tatil yanlis alarm dusur
- D6.5 DB rule engine - hardcoded kuraldan dinamige
- D6.6 5055_FALLBACK + log monitoring
- D6.7 D7 push hazirligi

### Bekleyen kararlar
- PERSONEL_BUGUN_0 sinyali aktif mi olsun? (Adem)
- DURGUN_EMIR_7G esigi 7 gun mu 10 gun mu? (Adem/Halil)
- D6.1-E scheduler ilk asamada mi sonra mi? (Adem)

---

**Rapor sonu.** D6.1 RECON tamam. Patch yok, sadece tasarim.
