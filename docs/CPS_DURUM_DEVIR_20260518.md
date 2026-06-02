# CPS Durum Devir Dokumani — 18 Mayis 2026

> **Amac:** Yeni faza (finans modulu) gecmeden once D5 + C.8 + D6.0.1 + D6.1 sprintlerinin eksiksiz teknik/mimari devir notu. Yarim kalma ve context kaybi olmamasi icin.
>
> **Yazim tarihi:** 2026-05-18, ~14:00
> **Yazan:** Adem & Claude (Solariz CPS)
> **Hedef okuyucu:** Claude (gelecek oturum) + Adem (referans)

---

## 1. CPS Genel Mimari

CPS ("Solariz CPS") — Solariz Terlik Sanayi'nin kendi gelistirdigi MES platformu. Korgun ERP (MSSQL) okunan, kendi SQLite veri tabaninda calisan, Flask tabanli Python uygulamasi.

### Veri akisi (yukaridan asagi)

```
[Korgun ERP — MSSQL @ 25.7.184.221]
     ↓  (read-only, pytds)
[CPS Native Runtime — Flask @ 8080, app/mock_data.db]
     ↓  (saha kayit toplama, onay akisi)
[uretim_kayit] ←→ [emir_alt_proses] ←→ [proses_kategori]
     ↓
[proses_alias] ← (D6.0.1: saha varyantlari → standart kod)
     ↓
[sinyal_engine.py] ← (D6.1-B: rule motor, R001/R004)
     ↓
[operasyon_sinyal] ← (D6.1-A: tablo, 258 ilk sinyal)
     ↓
[/yonetim/sinyaller-ui] ← (D6.1-D: Halil'in gordugu ekran)
```

### Calisma cevresi

- **Server:** SOLARIZDB (192.168.1.16) — Windows Server
- **Path:** `D:\Firma_Ozel\adem\Solariz_CPS_SERVER`
- **Port:** 8080 (CPS Native, primary)
- **Yan port:** 5055 (legacy personel terminal, read-only)
- **Python:** `C:\Users\Administrator\AppData\Local\Programs\Python\Python315\python.exe`
- **Task Scheduler:** `\Solariz\Solariz_CPS_8080` (SYSTEM, AtStartup)
- **DB:** `app/mock_data.db` (~2.9 MB)
- **Admin:** `admin / f7a6ua61`
- **Login endpoint:** `POST /giris` (kullanici+sifre+next)

### Onemli mimari kararlar

1. **Korgun read-only.** CPS hicbir zaman Korgun'a yazmaz. Sadece SELECT.
2. **`app/` klasoru paket DEGIL.** `app/__init__.py` yok. Flask CWD = `app/`, root paketler `modules` ve `services`. Import: `from services import sinyal_engine` (NOT `app.services`).
3. **DB path mantigi.** `os.path.dirname(__file__)` dirname x3 zaten `app/`'a kadar ciker. `os.path.join(_root, 'mock_data.db')` dogru (`app/` tekrar koymadan).
4. **Service-layer.** D6.1-C'den itibaren: business logic engine'de, routes minimal.
5. **routes.py format CRLF.** Tum patch'ler CRLF-aware.

---

## 2. Tamamlanan Sprintler

### D5 — CPS-Native MES (sablon_eslesme + engine)

**Sprint suresi:** C.4 + C.5 P1-P6 + P4 (~3 saat)
**Tamamlanma:** 2026-05-18 09:55

- `sablon_eslesme` tablosu (5 kayit canlida; sprint sirasinda max 126'ya cikti, sonra arsiv/temizlik)
- `_eslesme_bul` helper, `_sablon_uygula_internal` refactor
- `/sablon/trigger-test` (dry-run)
- `/sablon/trigger` manuel — **111005 ILK GERCEK INSERT** (7/7 PASS)
- Config + audit (8 kolon, sablon_id eklendi)
- Lazy hook `personel_giris/routes.py` (DOKUNULMAZ ILK)
- `hedef/routes.py` hash zinciri: 7BA → 642 → 3557 → C534 → DD83 → **7EAC892167AFEAD1** (P6, FINAL)

### C.8 — FLAG=True Canli Rollout

**Sprint suresi:** ~30 dk
**Tamamlanma:** 2026-05-18 10:10

- `config.py` L50: `USE_CPS_NATIVE_PROSES = False → True` atomic
- **111015 ILK OTOMATIK TRIGGER** (tip=Y, model=CRZ 8650 GOVDE, sablon_id=3, id=2282, kaynak=CPS_TRIGGER_C5: Asagi is indirme)
- 5/5 PASS test: 110393 BIREBIR, 111015 CPS_NATIVE_TRIGGERED, duplicate guard, DB temiz, hash korunmus
- C.9 derin analiz: 5055 kapatma RISKSIZ, only_5055=0
- D6 master analiz: 513 emir 7g+ durgun, Halil tek usta darbogaz, push altyapi 0
- `config.py` hash: **6CD32DCB1E1B3EBE** (FINAL)

### D6.0.1 — Proses Alias Altyapisi

**Sprint suresi:** ~1.25 saat (10:57 → 12:17)
**Tamamlanma:** 2026-05-18 12:17

- Migration `010_proses_alias.py` — tablo (9 kolon + 3 index) + 15 seed (6 typo grup, guven=100, onayli=1)
- 6 standart kod canlida:
  - 60 Capak (ATKI): 2 varyant
  - 70 Atki Silme (ATKI): 3 varyant
  - 71 Atki Rivet Takma (ATKI): 3 varyant
  - 72 Atki Tampon Baski (ATKI): 3 varyant
  - 80 Govde Baski (GOVDE): 2 varyant
  - 90 Asagi Is Indirme (TRANSFER): 2 varyant
- PATCH-B: `GET /yonetim/proses-alias/liste` (read-only JSON)
- PATCH-C: `app/templates/yonetim/proses_alias.html` (3 KPI kart, tablo, filter, CRUD YOK)
- PATCH-D: `GET /yonetim/proses-alias` (HTML render)
- HOTFIX: `_pa_db_path` dirname x3 duzelt
- **Stable:** `STABLE_D6_0_1_FINAL_OK_20260518_121759`

### D6.1 — Operasyon Sinyal Motoru (A+B+C+D, E SKIP)

**Sprint suresi:** ~1 saat 20 dk (12:30 → 13:50)
**Tamamlanma:** 2026-05-18 13:50

#### D6.1-A — operasyon_sinyal Tablo

- Migration `011_operasyon_sinyal.py` (3780 byte)
- **21 kolon** (id dahil) + 5 INDEX
- CHECK/FK/UNIQUE YOK (esneklik, idempotency kodda)
- SEED YOK
- Yedek: `mock_data.db.YEDEK_D6_1_A_20260518_124558`
- Stable: `STABLE_D6_1_A_OK_20260518_125158`

#### D6.1-B — sinyal_engine.py + R001 + manuel tetik

- YENI dosya: `app/services/__init__.py` (23 byte)
- YENI dosya: `app/services/sinyal_engine.py` (7394 byte ilk surum)
- 2 Rule sinifi:
  - `Rule_R001_DurgunEmir7G` (aktif)
  - `Rule_R004_PersonelBugun0` (PASIF, FEATURE_FLAGS = False)
- `FEATURE_FLAGS = {'R001_DURGUN_EMIR_7G': True, 'R004_PERSONEL_BUGUN_0': False}`
- `save_signal` idempotent: ayni `rule_id + emir_no + durum=AKTIF` varsa UPDATE `tekrar_sayisi++` ve `son_tetiklenme`, yoksa INSERT
- `run_rule` + `run_all_rules` + `rule_filter`
- Endpoint: `POST /yonetim/sinyal-engine/test`
  - Body: `{"dry_run": true/false, "rule_id": "R001"}` (rule_id opsiyonel)
  - Default `dry_run=true` (guvenli)
- **2 hotfix yasandi:**
  1. `from app.services import sinyal_engine` → `from services import sinyal_engine`
  2. `os.path.join(_root, 'app', 'mock_data.db')` → `os.path.join(_root, 'mock_data.db')`
- Canli test: **258 INSERT** 1. cagri, 258 UPDATE 2. cagri (`tekrar_sayisi=2`), idempotent kanitlandi
- Stable: `STABLE_D6_1_B_FINAL_OK_20260518_130625`

#### D6.1-C — 5 CRUD Endpoint (Service-Layer)

- 5 yeni service fonksiyon (`sinyal_engine.py` 7394 → 14585 byte):
  - `list_signals(conn, durum, seviye, rule_id, limit, offset)` — filtreli liste max 500
  - `get_signal(conn, id)` — detay, None varsa
  - `dismiss_signal(conn, id, kid, kadi, aciklama)` — DISMISS + audit, idempotent no_op
  - `resolve_signal(conn, id, kid, kadi, aciklama)` — RESOLVED + audit, idempotent no_op
  - `get_ozet(conn)` — durum/seviye/tip dagilim
- 5 yeni endpoint (`yonetim/routes.py`):
  - `GET /yonetim/sinyaller` (filter: durum, seviye, rule_id, limit max 500)
  - `GET /yonetim/sinyaller/<id>` (404 yoksa)
  - `POST /yonetim/sinyaller/<id>/dismiss` (aciklama >=3 char)
  - `POST /yonetim/sinyaller/<id>/resolved` (aciklama >=3 char)
  - `GET /yonetim/sinyaller/ozet` (KPI badge)
- Audit pattern: `full_aciklama = f'[{kullanici_adi}] {aciklama}'`, `gorulen_kullanici_id` NULL olabilir
- DELETE yok, INSERT yok, AKTIF'e geri donus yok
- DISMISS → RESOLVED gecisi serbest (Halil hatasini duzeltebilir)
- DRY-RUN 10/10 PASS, canli verify 9/9 PASS
- Stable: `STABLE_D6_1_C_OK_20260518_131824`

#### D6.1-D — UI Template

- YENI dosya: `app/templates/yonetim/sinyaller.html` (13697 byte)
- Endpoint: `GET /yonetim/sinyaller-ui` (render only, business logic YOK)
- 6 KPI kart: Toplam, Aktif, Warn, Critic, Resolved, Dismiss
- 5 filtre: Durum, Seviye, Rule, Limit, Arama
- 9 kolon tablo: ID, Seviye, Tip, Emir, Mesaj, Tekrar, Durum, Olusturma, Aksiyon
- 3 aksiyon: Detay modal, Dismiss prompt (>=3 char), Resolved prompt
- Renk pill: WARN sari, CRITIC kirmizi, RESOLVED yesil, DISMISS gri, AKTIF altin
- Sayfa ici arama (mesaj/emir/tip)
- Auto-refresh YOK (sadece manuel Yenile)
- `base.html` / sidebar / topbar **DOKUNULMADI**
- Template Halil tarayicidan canli gorebilir: `http://192.168.1.16:8080/yonetim/sinyaller-ui` (admin login)
- Render 66334 byte (full page: base + content)
- Stable: `STABLE_D6_1_D_OK_20260518_135047`
- **Full stable:** `STABLE_D6_1_FULL_OK_20260518_135706` (2.9 MB, 13 dosya)

#### D6.1-E — SKIP (Scheduler)

- Bugun yapilmadi
- Manuel tetik yeterli (`POST /sinyal-engine/test`)
- Karar: Halil saha geri bildirimi sonrasi (yarin / sonra)

---

## 3. Canli Tablolar ve Kayit Sayilari

### CPS Native (uretim & sinyal)

| Tablo | Kayit | Aciklama |
|-------|-------|----------|
| `uretim_kayit` | 1393 | Saha kayit, 35 distinct proses, 28 personel, 25 gun (en eski 2026-04-14, en yeni 2026-05-18) |
| `emir_alt_proses` | 2282 | 594 aktif emir, 4 pasif emir |
| `proses_kategori` | 11 | Standart sure: SADECE 2 dolu (kod 26=35sn, 60=30sn), 9 EKSIK |
| `proses_alias` | 15 | D6.0.1 typo grup seed |
| `sablon_eslesme` | 5 | D5 (sprint sirasinda 126'ya cikti, sonra temizlik) |
| `sablon` | 5 | D5 sablon ana tablo |
| `sablon_proses` | 14 | D5 sablon proses detay |
| `operasyon_sinyal` | **258** | D6.1-A/B/C/D: 256 AKTIF + 1 DISMISS + 1 RESOLVED |
| `proses_usta_atama` | 10 | FAZ 4.3 PARÇA 3 |
| `usta_aksiyon` | 1 | usta islem audit |
| `usta_kilit_durum` | 1 | usta lock |
| `personel_kullanici` | 22 | D4.7 EXTEND personel + login |
| `sistem_kullanici` | 14 | admin/sistem rolleri |
| `sistem_rol` | 11 | |
| `sistem_rol_yetki` | 80 | |
| `sistem_yetki` | 44 | |
| `sistem_audit` | 915 | tum islem log |
| `sistem_belge` | 180 | belge yonetimi |
| `sistem_kur` | 24 | TCMB kur cache |
| `schema_migrations` | 5 | 002, 003, 004_overlay, 010, 011 |

### Enjeksiyon modulu (ZATEN VAR — surpriz keşif)

| Tablo | Kayit | Aciklama |
|-------|-------|----------|
| `enj_makine` | 4 | EVA makine listesi |
| `enj_kalip` | 67 | Kalip kataloğu |
| `enj_istasyon_durumu` | 380 | Canli durum kayit |
| `enj_saatlik_kayit` | 300 | Saatlik uretim |
| `enj_event_log` | 415 | Olay log |
| `enj_gunluk_rapor` | 27 | Vardiya raporlari |
| `enj_aksama_sebep` | 11 | Sebep kataloğu |
| `enj_foto` | 0 | Henuz kullanilmiyor |

**Sonuc:** Enjeksiyon veri akiyor, UI yok. D7 onceligi #2.

### Finans modulu

| Tablo | Kayit | Aciklama |
|-------|-------|----------|
| `finans_anlasma` | 36 | Anlasma ana |
| `finans_anlasma_model` | 98 | Anlasma model detay |
| `finans_avans` | 6 | |
| `finans_avans_mahsup` | 0 | |
| `finans_odeme_cek` | 0 | |
| `finans_odeme_plan` | 212 | Odeme plani |
| `finans_simulasyon` | 7 | Simulasyon |
| `finans_simulasyon_secenek` | 8 | |
| `Banka_Kart` | 2 | |
| `Kasa_Kart` | 1 | |
| `Cek_Senet` | 0 | |
| `Cari_Har` | 82 | Cari hareket |
| `Cari_Kart` | 10 | Cari liste |
| `nakit_giris_beklenen` | 2 | |

### Grafik / urun / sevkiyat

| Tablo | Kayit |
|-------|-------|
| `grafik_urun` | 45 |
| `grafik_urun_kategori` | 10 |
| `grafik_urun_varyant` | 48 |
| `grafik_numune` | 16 |
| `grafik_numune_iterasyon` | 52 |
| `grafik_tedarikci` | 5 |
| `grafik_cin_siparis` | 6 |
| `grafik_cin_siparis_kalem` | 39 |
| `grafik_fiyat_teklif` | 3 |
| `grafik_sevkiyat` | 5 |
| `grafik_sevkiyat_dagitim` | 25 |
| `grafik_sevkiyat_masraf` | 75 |

### Ithalat

| Tablo | Kayit |
|-------|-------|
| `ithalat_parti` | 11 |
| `ithalat_maliyet_kalem` | 84 |
| `ithalat_belge_parse` | 125 |
| `ithalat_odeme_plan` | 6 |
| `ithalat_odeme_hareket` | 3 |

### Cin ofis (ozel)

| Tablo | Kayit |
|-------|-------|
| `cin_ofis_dosya_referans` | 5 |
| `cin_ofis_import_log` | 6 |
| `cin_ofis_kalem_ek` | 4 |
| `cin_ofis_odeme_taslak` | 6 |

### Gorev / iş akisi

| Tablo | Kayit |
|-------|-------|
| `tasks` | 13 |
| `task_logs` | 29 |
| `task_settings` | 7 |
| `tasks_users` | 6 |
| `task_files` | 0 |
| `is_akisi` | 3 |

### Yonetim / planlama / sapma

| Tablo | Kayit |
|-------|-------|
| `module_registry` | 32 |
| `planlama_karar` | 0 (BOS — D4.3 alt yapi var, kullanim yok) |
| `siparis_darbogaz` | 1 |
| `siparis_proses_durum` | 10 |
| `sapma_olay` | 1 |
| `bildirim_log` | 24 |
| `user_permission_override` | 0 |
| `vardiya_devir_log` | 0 |

---

## 4. Final Hashler (18 Mayis 2026, 14:00)

| Dosya | Hash | Sprint kaynak |
|-------|------|---------------|
| `app/modules/hedef/routes.py` | **7EAC892167AFEAD1** | D5 P6 |
| `app/config.py` | **6CD32DCB1E1B3EBE** | C.8 |
| `app/modules/personel_giris/routes.py` | **F6D1953CC0243B0C** | D5 C.5 P4 |
| `app/modules/yonetim/routes.py` | **4C486F3CD7D84A55** | D6.1-D |
| `app/services/sinyal_engine.py` | **3C7BD523E5C37CAF** | D6.1-C |
| `app/templates/yonetim/sinyaller.html` | **C4994F8BE7E15A9D** | D6.1-D |

### yonetim/routes.py hash zinciri (D6.0.1 → D6.1-D)

```
3A36699511E9CEC6  (D6.0.1 BCD + HOTFIX)
       ↓ + D6.1-B endpoint append
ED2EFB7186C5C757  (D6.1-B atomic)
       ↓ + import fix (app.services → services)
B39BFC301CEB87D5
       ↓ + path fix (app/mock_data.db → mock_data.db)
DA11A90E41A381CF  (D6.1-B FINAL)
       ↓ + D6.1-C 5 endpoint
3DF38F3974835D89  (D6.1-C)
       ↓ + D6.1-D /sinyaller-ui
4C486F3CD7D84A55  (D6.1-D FINAL)
```

---

## 5. Aktif Endpoint'ler (D5 sonrasi yeni)

### Sinyal sistemi (D6.1)

| Endpoint | Metod | Yetki | Aciklama |
|----------|-------|-------|----------|
| `/yonetim/sinyal-engine/test` | POST | admin | Rule motoru manuel tetik (`dry_run=true/false`) |
| `/yonetim/sinyaller` | GET | admin | Liste + filtre (durum, seviye, rule_id, limit, offset) |
| `/yonetim/sinyaller/<id>` | GET | admin | Tek sinyal detay |
| `/yonetim/sinyaller/<id>/dismiss` | POST | admin | Durum geçişi (aciklama >=3 zorunlu) |
| `/yonetim/sinyaller/<id>/resolved` | POST | admin | Durum geçişi (aciklama >=3 zorunlu) |
| `/yonetim/sinyaller/ozet` | GET | admin | KPI dağılım (badge için) |
| `/yonetim/sinyaller-ui` | GET | admin | UI ekran (render only) |

### Proses alias (D6.0.1)

| Endpoint | Metod | Aciklama |
|----------|-------|----------|
| `/yonetim/proses-alias/liste` | GET | JSON liste |
| `/yonetim/proses-alias` | GET | HTML render |

### Sablon engine (D5)

- `/sablon/trigger-test` (dry-run)
- `/sablon/trigger` (manuel uygula)
- D5 C.8 sonrasi otomatik: `personel_giris/routes.py` lazy hook çağırıyor

### Saha / personel (legacy + native)

- `/personel-giris/prosesler/<emir_no>` — saha lazy trigger akışı
- `/personel-giris/health` — health check (200)

---

## 6. Operasyon Sinyal Mantigi

### Tablo şeması (`operasyon_sinyal`, 21 kolon)

```
id INTEGER PRIMARY KEY
sinyal_tipi TEXT          -- ornek: 'DURGUN_EMIR_7G', 'PERSONEL_BUGUN_0'
seviye TEXT               -- 'INFO' / 'WARN' / 'CRITIC'
emir_no TEXT              -- TEXT! (uretim_kayit.emir_no INTEGER ile CAST)
proses_adi TEXT
proses_kodu TEXT
personel_id INTEGER
personel_ad TEXT
mesaj TEXT                -- Halil'in göreceği metin
aksiyon_onerisi TEXT
kaynak TEXT               -- 'RULE_ENGINE'
rule_id TEXT              -- 'R001' / 'R004'
durum TEXT DEFAULT 'AKTIF' -- AKTIF / GORULDU / DISMISS / RESOLVED
gorulen_kullanici_id INTEGER
gorulen_zaman TEXT
cozulen_zaman TEXT
cozulen_aciklama TEXT     -- '[admin] ...' prefix audit
tekrar_sayisi INTEGER DEFAULT 1
son_tetiklenme TEXT
meta_json TEXT            -- {gun_durgun, son_hareket}
olusturma TEXT DEFAULT CURRENT_TIMESTAMP
```

### İdempotency

- `rule_id + emir_no + durum=AKTIF` UNIQUE değil ama kod tarafında garantili
- save_signal: AKTIF kayit varsa UPDATE tekrar_sayisi++, son_tetiklenme=now
- save_signal: yoksa INSERT (tekrar_sayisi=1)

### Durum akışı

```
INSERT → AKTIF
  ↓
  ├──→ dismiss → DISMISS (cozulen_zaman, cozulen_aciklama)
  │       ↓
  │     resolved → RESOLVED (geçiş serbest)
  ↓
  └──→ resolved → RESOLVED (cozulen_zaman, cozulen_aciklama)

AKTIF'e geri dönüş YOK
DELETE YOK
```

### Audit pattern

```
gorulen_kullanici_id = session['kullanici'].get('Id')  # admin için NULL olabilir
cozulen_aciklama = f'[{kullanici_adi}] {aciklama}'      # audit trail
cozulen_zaman = datetime('now', 'localtime')            # YYYY-MM-DD HH:MM:SS
```

---

## 7. Rule Sistemi

### Mevcut

| Rule | Tip | Status | Mantık | Üretilen |
|------|-----|--------|--------|----------|
| **R001** | `DURGUN_EMIR_7G` | **AKTIF** (FLAG=True) | `emir_alt_proses.aktif=1` + son hareket 7+ gün önce | **258 sinyal** |
| **R004** | `PERSONEL_BUGUN_0` | **PASIF** (FLAG=False) | 30g aktif personel + bugün 0 kayıt + saat>12 | 0 (skipped) |

### `FEATURE_FLAGS` dict

```python
FEATURE_FLAGS = {
    'R001_DURGUN_EMIR_7G': True,
    'R004_PERSONEL_BUGUN_0': False,  # Adem psikolojik risk endişesi
}
```

### R001 SQL (özet)

```sql
SELECT eap.emir_no,
       MAX(u.olusturma) son_hareket,
       julianday('now') - julianday(MAX(u.olusturma)) gun_durgun
  FROM emir_alt_proses eap
  LEFT JOIN uretim_kayit u
       ON CAST(u.emir_no AS TEXT) = eap.emir_no
      AND u.onay_durum = 'onaylandi'
 WHERE eap.aktif = 1
 GROUP BY eap.emir_no
HAVING son_hareket IS NOT NULL
   AND gun_durgun >= 7.0
```

### Önemli not: `HAVING son_hareket IS NOT NULL` filtresi

- 510 emir 7g+ durgun (RECON'da görüldü)
- 258 emir hareket görmüş ama 7g+ önce (R001 yakaladı)
- 253 emir HİÇ hareket görmemiş (LEGACY_5055 import sonrası) — **bu farklı bir sinyal** (gelecek R006 EMIR_HIC_HAREKET_YOK)

---

## 8. Rollback Stratejisi

### Genel disiplin

- Her atomic move öncesi yedek (mock_data.db + ilgili .py dosyaları)
- Yedek formatı: `<dosya>.YEDEK_<SPRINT>_<TIMESTAMP>`
- Her sprint sonrasi mini snapshot: `STABLE_<SPRINT>_OK_<TIMESTAMP>` (D:\...\yedeklemeler)
- Sprint kapanışında full stable: `STABLE_<SPRINT>_FULL_OK_<TIMESTAMP>`

### Bugünkü yedekler (D5+C8+D6.0.1+D6.1)

```powershell
# D6.1-A
Copy-Item "app\mock_data.db.YEDEK_D6_1_A_20260518_124558" "app\mock_data.db" -Force

# D6.1-B
Copy-Item "app\mock_data.db.YEDEK_D6_1_B_20260518_125429" "app\mock_data.db" -Force
Copy-Item "app\modules\yonetim\routes.py.YEDEK_D6_1_B_20260518_125429" "app\modules\yonetim\routes.py" -Force
Remove-Item "app\services" -Recurse -Force

# D6.1-C
Copy-Item "app\mock_data.db.YEDEK_D6_1_C_20260518_131010" "app\mock_data.db" -Force
Copy-Item "app\modules\yonetim\routes.py.YEDEK_D6_1_C_20260518_131010" "app\modules\yonetim\routes.py" -Force
Copy-Item "app\services\sinyal_engine.py.YEDEK_D6_1_C_20260518_131010" "app\services\sinyal_engine.py" -Force

# D6.1-D
Copy-Item "app\modules\yonetim\routes.py.YEDEK_D6_1_D_20260518_132732" "app\modules\yonetim\routes.py" -Force
Remove-Item "app\templates\yonetim\sinyaller.html" -Force

# Hızlı tam geri (D6.1 öncesi noktasına)
Copy-Item "app\mock_data.db.YEDEK_D6_1_A_20260518_124558" "app\mock_data.db" -Force
Copy-Item "app\modules\yonetim\routes.py.YEDEK_D6_1_B_20260518_125429" "app\modules\yonetim\routes.py" -Force
Remove-Item "app\services" -Recurse -Force
Remove-Item "app\templates\yonetim\sinyaller.html" -Force
```

### Patch disiplini (her sprintte uygulanmış)

1. RECON (sadece okuma, sıfır risk)
2. Yedek al (gerçek timestamp + rollback komutu)
3. Staging kod yaz (Python file build, here-string sorunları bypass)
4. AST + py_compile + marker check + regression check
5. SIMULATE merge + LF/CR format
6. DRY-RUN kopya DB'de
7. PRE-ATOMIC GATE + Adem onayı
8. Atomic move (os.replace)
9. Flask reload 5 sn
10. Verify (canlı smoke test, login + endpoint)
11. Hash teyit + DB durum
12. Rapor + Mini snapshot

---

## 9. Snapshot / Yedek Yolları

### Tam stable snapshot'lar (`D:\Firma_Ozel\adem\yedeklemeler\`)

- `STABLE_SERVER_8080_AUTH_FIX_20260511_123850` — eski baseline
- `STABLE_UI_FINAL_v2_20260508_222016` — UI cleanup sonrasi
- `STABLE_D5_FAZ_C5_FULL_*` — D5 C.5 kapanış
- `STABLE_D6_0_1_FINAL_OK_20260518_121759` — D6.0.1 kapanış (2.87 MB)
- `STABLE_D6_1_A_OK_20260518_125158` — D6.1-A (2.73 MB)
- `STABLE_D6_1_B_FINAL_OK_20260518_130625` — D6.1-B (2.85 MB)
- `STABLE_D6_1_C_OK_20260518_131824` — D6.1-C (2.86 MB)
- `STABLE_D6_1_D_OK_20260518_135047` — D6.1-D (2.87 MB)
- **`STABLE_D6_1_FULL_OK_20260518_135706`** — D6.1 sprint kapanış (2.9 MB, 13 dosya) ⭐

### Raporlar (`D:\...\Solariz_CPS_SERVER\reports\`)

- `D5_FAZC5_P1-P6.md` + `D5_FAZC5_FINAL.md`
- `D5_C8_FLAG_TRUE_BASARI.md` + `SONUC.json`
- `D5_C9_CANLI_GOZLEM_DERIN_ANALIZ.md` (8116 byte)
- `D6_OPERASYON_ZEKASI_MASTER_ANALIZ.md` (9753 byte)
- `D6_0_PROSES_NORMALIZASYON_MASTER_PLAN.md` (13593 byte)
- `D6_0_1_PROSES_ALIAS_MIGRATION.md` + verify + final (4160 byte)
- `D6_1_SIGNAL_ENGINE_RECON.md` (12248 byte) — 5 sinyal önerisi
- `D6_1_A_VERIFY.md` (1552 byte)
- `D6_1_B_FINAL.md` (2361 byte)
- `D6_1_C_FINAL.md` (2513 byte)
- `D6_1_D_FINAL.md` (1935 byte)
- **`D6_1_FINAL_KAPANIS.md`** (6875 byte) ⭐ sprint genel kapanış

---

## 10. Ertelenen Kararlar

### Pazartesi (yarın) bekleyen 3 küçük karar

1. **PERSONEL_BUGUN_0 FLAG** (R004)
   - Şu an pasif (`FEATURE_FLAGS = False`)
   - Sebep: Adem psikolojik risk endişesi (personel "performans takip" hissetmesin)
   - Karar: aktif / pasif / kaldır
   - Tahmini etki: aktif olursa ~5-15 sinyal/gün

2. **DURGUN_EMIR_7G eşik**
   - Şu an 7 gün → 258 sinyal
   - Alternatifler: 10 gün (~150 sinyal), 14 gün (~70 sinyal)
   - Karar Halil ile (yüksek/orta/düşük "ses" tercihi)

3. **D6.1-E Scheduler**
   - Şu an manuel tetik (`POST /sinyal-engine/test`)
   - Alternatif: Windows Task Scheduler dakikalık otomatik
   - Karar: bu hafta / sonra / hiç

### UI iyileştirme (yarın, ~30 dk)

- `WARN` → "Uyarı"
- `CRITIC` → "Kritik"
- `DISMISS` → "Reddedildi"
- `RESOLVED` → "Çözüldü"
- `AKTIF` → "Aktif"
- `GORULDU` → "Görüldü"
- Kolon başlıkları: `OLUSTURMA` → `OLUŞTURMA`, vb.
- DISMISS kolonu kenardan kesiliyor (responsive iyileştirme)

### Standart süre atölye oturumu (yarın, 15 dk)

- `proses_kategori`: 11 proses, 2 dolu, **9 EKSİK**
- Adem + Halil + 9 prosese saniye girilsin:
  - 70 Atki Silme, 71 Atki Rivet, 72 Atki Tampon
  - 80 Gövde Baski, gövde sayma, gövde çapak
  - Rivet Takma, Aşağı iş indirme
- Bu olmadan D7.3+ sprintleri yapılamaz (performans/kapasite/sapma)

---

## 11. Sonraki Büyük Faz Önerileri (D7 analiz)

D6.1 RECON sonucu CPS'in çok daha geniş ekosisteme sahip olduğu görüldü. Öncelik analizi:

### 🥇 D7.1 — Darboğaz Tahmini (R002) — Değer 9/10

- **Veri:** HAZIR (594 aktif emir, 35 proses, 250 son-7g kayıt)
- **Mantık:** Bir prosesteki bekleyen yığılma X gündür artıyor
- **Standart süre eksik olsa bile çalışır** (göreceli hız analizi)
- **Yapılacak:** sinyal_engine'e R002 rule ekle, mevcut mimari hazır
- **Süre:** 2-3 saat
- **Risk:** Düşük (yeni rule, mevcut sisteme dokunmaz)
- **Halil değeri:** Çok yüksek — sabah "bugün nereye odaklan?" cevabı

### 🥈 D7.2 — Enjeksiyon Canlı Makine Ekranı — Değer 8.5/10

- **Sürpriz keşif:** Veri zaten akıyor!
  - 4 makine, 67 kalıp, 380 istasyon kaydı, 415 olay, 300 saatlik kayıt
- **Yapılacak:** `/yonetim/enjeksiyon-canli` route + template
  - 4 makine kart (kalıp + durum + son saatlik üretim)
  - Aksama sebep dağılımı
  - Vardiya istatistik
- **Süre:** 2-3 saat
- **Risk:** Düşük (sadece UI, veri zaten var)
- **Vardiya sorumlusu değeri:** Çok yüksek

### 🥉 D7.3 — Kritik Sipariş Erken Uyarı (R003) — Değer 8/10

- **Veri:** Var ama emir-sipariş bağlantısı belirsiz
- **Mantık:** `eap.hedef_adet - cumul üretim` / `son 7g hız` = tahmini bitiş
- **Bağımlılık:** Sipariş teslim tarihi nerede?
- **Süre:** 2-3 saat (eğer veri bağlantısı kurulursa)
- **Risk:** Orta (veri keşfi gerekli)

### Diğer alanlar (orta öncelik)

| Alan | Değer | Süre | Engel |
|------|-------|------|-------|
| Personel Performans Anomali | 5/10 | 4-6 saat | Standart süre eksik + psikolojik risk |
| Kapasite Tahmini | 6/10 | 4 saat | Standart süre eksik |
| Maliyet/Sapma Zekası | 7/10 | 5-6 saat | İş kuralları karmaşık |
| Görev/İş Akışı | 4/10 | 3 saat | `tasks` az kullanım |
| Satın Alma Gecikme Etkisi | 5/10 | 4-5 saat | İthalat-emir bağlantısı yok |
| Planlama Önerisi | 5/10 | 6-8 saat | `planlama_karar` boş |

---

## 12. Finans Modülüne Geçiş Notu

### Mevcut finans altyapısı (KAPSAMLI)

Finans modülü CPS içinde **ZATEN VAR ve aktif**. 14 tablo, 462 kayıt:

```
finans_anlasma: 36           ← Anlaşma ana
finans_anlasma_model: 98     ← Model bazlı detay
finans_odeme_plan: 212       ← Ödeme planı (en yoğun)
finans_avans: 6
finans_simulasyon: 7 + 8
nakit_giris_beklenen: 2
Banka_Kart: 2, Kasa_Kart: 1, Cek_Senet: 0
Cari_Har: 82, Cari_Kart: 10
ithalat_*: 5 tablo + 229 kayıt
cin_ofis_*: 4 tablo + 21 kayıt
```

### Mevcut finans Flask uygulaması

- Path: `D:\Firma_Ozel\adem\solariz finans\`
- Port: ayrı (CPS'ten bağımsız)
- Dosyalar: `finans_yonetim.html`, `finans_server.py`, `finans.db` (kendi DB!)
- TCMB rates via HTTP (HTTPS bloklu serverda)
- 6 tablo schema, multi-user, field-level audit
- Nakit Akışı Yönetim Sistemi (6-ay strip)
- Kasa tab (TL/FX tracking)

### Geçiş notu (yeni faza)

Eğer "yeni finans modülüne geçiş" demek:
- **Mevcut finans Flask** ile çalışmaya devam (ayrı sistem)
- VEYA CPS içine **operasyon zekası entegrasyonu** (D6.1 pattern'i finans tablolarına uygula)

### Önerilen ilk finans-sinyal kuralları (D8 olabilir)

| Rule | Mantık | Veri kaynağı |
|------|--------|--------------|
| **R010 ODEME_GECIKME** | finans_odeme_plan tarihi geçmiş, ödenmemiş | finans_odeme_plan |
| **R011 NAKIT_RISKI** | Önümüzdeki 7 gün ödeme > kasa+banka | finans_odeme_plan + Kasa_Kart + Banka_Kart |
| **R012 CEK_VADESI_YAKIN** | Çek vadesi <= 3 gün | Cek_Senet |
| **R013 CARI_BAKIYE_BOZULDU** | Cari_Har bakiye sınır aşımı | Cari_Har |
| **R014 ITHALAT_GECIKME** | ithalat_parti tahmini varış geçti | ithalat_parti |

**Finans-sinyal mimarisi:** D6.1 sinyal motoru aynı şekilde çalışır. Sadece yeni `Rule_Rxxx` sınıfları + `FEATURE_FLAGS` entry. **Mevcut altyapı 1:1 uyumlu.**

### Geçiş öncesi kritik notlar (gelecek Claude için)

1. **CPS `mock_data.db` vs Finans `finans.db`** — iki ayrı DB. Eğer entegrasyon istiyorsa cross-DB query veya finans tablolarını CPS'e kopyalamak gerekir.
2. **TCMB kur sistemi** CPS'te (`sistem_kur`, 24 kayıt) ve finans'ta ayrı. Birleştirme gerekebilir.
3. **Audit pattern** her iki sistemde benzer ama tablolar farklı (`sistem_audit` vs finans audit log).
4. **Login akışı** CPS'te `session.get('kullanici')` — finans'taki user-id ile eşleştirme gerekecek.

---

## 🚨 Yeni Claude Oturumu için Acil Kontrol Listesi

Yeni oturum başladığında Claude'un yapması gereken:

```powershell
Set-Location D:\Firma_Ozel\adem\Solariz_CPS_SERVER

# 1. Sağlık + Hash
Invoke-WebRequest "http://127.0.0.1:8080/personel-giris/health"  # 200 olmalı
Get-FileHash "app\modules\hedef\routes.py"          # 7EAC892167AFEAD1
Get-FileHash "app\config.py"                        # 6CD32DCB1E1B3EBE
Get-FileHash "app\modules\personel_giris\routes.py" # F6D1953CC0243B0C
Get-FileHash "app\modules\yonetim\routes.py"        # 4C486F3CD7D84A55
Get-FileHash "app\services\sinyal_engine.py"        # 3C7BD523E5C37CAF
Get-FileHash "app\templates\yonetim\sinyaller.html" # C4994F8BE7E15A9D

# 2. DB durum
# operasyon_sinyal: 258 (256/1/1)
# uretim_kayit: 1393+
# emir_alt_proses: 2282
# proses_alias: 15

# 3. Halil ekranı
# http://192.168.1.16:8080/yonetim/sinyaller-ui  (admin/f7a6ua61)
```

---

## SONUÇ

D5 + C.8 + D6.0.1 + D6.1 sprintleri **18 patch + 2 hotfix** ile tamamlandı. **0 saha kesintisi, 0 gerçek rollback.**

CPS bugün **"kayıt toplayan"dan "düşünen ve problem çözen"e** geçti:

- **258 ilk gerçek operasyon sinyali** canlıda
- Halil tarayıcıdan görüyor, etiketliyor (dismiss/resolved)
- Audit trail eksiksiz
- Sahaya tamamen şeffaf (görmüyor)

**Yarın için açık:** UI Türkçeleştirme (30 dk) + D7 sprint kararı.

**Finans modülüne geçiş:** Mevcut finans Flask sistemi ayrı çalışıyor. Eğer CPS-finans entegrasyonu hedefse, D6.1 sinyal motoru pattern'i finans tablolarına 1:1 uygulanabilir (D8 olarak).

---

*Yazım sonu: 2026-05-18 ~14:00. Tahmini okuma süresi: 15-20 dk.*
*Gelecek Claude oturumu için: bu dosyayı ilk önce oku, sonra hash kontrol et, sonra Adem'in yeni isteğine geç.*
