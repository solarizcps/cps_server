# FINANS_NATIVE_FAZ1 — RECON + Taşıma Planı

> **Tarih:** 2026-05-18, ~14:50
> **Sprint adı:** FINANS_NATIVE_FAZ1
> **Karar:** Eski 5058 bağımsız sistem **kalıcı çözüm DEĞİL**. Finans CPS içine **native blueprint** olarak alınacak. 5058 sadece **referans** kalır (aktif kullanım YOK).
> **Hedef:** Altan tek CPS login ile, **CPS sidebar → Finans** altında çalışacak. Saha kesinti YOK, mevcut canlı CPS tasarımı/sidebar/topbar/altın renk korunacak.
> **Kapsam:** Sadece RECON + taşıma planı. Kod YOK, migration YOK, canlıya dokunma YOK.

---

## 0. Yönetici Özeti — 5 Net Karar

| # | Karar |
|---|-------|
| 1 | **Eski finans.db CANLIYA ALINMAZ.** Sadece `_arsiv/` referans olarak kalır. |
| 2 | **Eski HTML kopyalanmaz**, sadece **mantık/ekran referansı**. CPS native template'ler yeniden yazılır. |
| 3 | **CPS'in mevcut 14 finans tablosuna dokunulmaz.** Eksik kalan parçalar yeni tablolarla eklenir. |
| 4 | **Sidebar/topbar/altın brand/yetki sistemi** olduğu gibi korunur. Tek değişiklik: sidebar'a 1 koşullu menü item. |
| 5 | **Saha üretimi etkilenmez.** Tüm değişiklikler `app/modules/finans/` ve `app/services/finans/` altında. |

---

## 1. Mevcut Durum

### 1.1 Eski sistem aktif

| Konu | Detay |
|------|-------|
| Sunucu | `D:\Firma_Ozel\adem\solariz finans\` |
| Port | **5058** (host='0.0.0.0' — dışarıdan erişilebilir) |
| DB | `finans.db` (250 KB, 6 tablo, 1207 kayıt) |
| UI | `finans_yonetim.html` (3895 satır, 8 tab) — **çalışıyor**, Altan login olabildi |
| Login | `altan/104099`, `adem/f7a6ua61` (plaintext) |
| Veri | 715 ödeme + 27 kredi + 454 planlama + 0 kasa |
| Veri tarihi | Şubat 2026 snapshot (3 ay eski) |

### 1.2 CPS canlı durum (D6.1 sonrası)

| Konu | Detay |
|------|-------|
| Port | **8080** (sahanın ana sistemi) |
| Sahip | admin login: `admin/f7a6ua61` |
| Sidebar | 6 grup (Genel/Finans/Ticaret/Üretim/Kalite/Yönetim) |
| Yetki sistemi | `sistem_rol` (11) + `sistem_yetki` (44) + `sistem_rol_yetki` (80) |
| Finans tabloları | 14 adet (anlasma, odeme_plan, Banka_Kart, Cek_Senet, Kasa_Kart, Cari_*, vb) |
| Hash zinciri | yonetim hash `4C486F3CD7D84A55` (D6.1-D) |

### 1.3 Çakışma noktası

CPS'te `Finans` sidebar grubu **zaten var** ama içerik eski. Native taşıma bu grubu yeniden kuracak. Mevcut finans tabloları **bozulmadan** yeni şema **yan yana** eklenecek.

---

## 2. Geçiş Stratejisi — Native Modül

### 2.1 Genel prensip

```
KESINLIKLE OLMAYACAKLAR:
  - Eski finans.db import (CPS mock_data.db'ye veri çekme YOK)
  - Eski HTML kopyala-yapıştır (3895 satır SPA YOK)
  - Eski API endpoint pattern (auth'suz public API YOK)
  - 5058 port aktif tutulması (modul bitince kapatılır)

OLACAKLAR:
  - CPS native blueprint (modules/finans/)
  - CPS auth + yetki (sistem_rol_yetki üzerinden)
  - CPS template (base.html extend, modüler 8 ekran)
  - CPS audit (sistem_audit + finans_audit)
  - Temiz veri girişi (Altan elle, ilk hafta)
```

### 2.2 Veri stratejisi

| Veri | Strateji | Süre |
|------|----------|------|
| **Eski finans.db** | `_arsiv/` klasörüne taşı, **import yok** | 5 dk |
| **715 ödeme** | Altan elle girer — sadece **aktif/bekleyen** olanlar (~50-80 kayıt) | 3-4 saat |
| **27 kredi** | Altan elle girer — sadece **aktif krediler** (~10-15 kayıt) + taksitler otomatik | 2-3 saat |
| **Çekler** | Sadece bekleyen çekler (~10-20 kayıt) | 1-2 saat |
| **Kasa** | Sıfırdan (eski boştu) | 15 dk |
| **Planlama** | Altan elle — sadece **gelecek aylar** (~30-50 kayıt) | 2-3 saat |

**Toplam Altan veri girişi: ~10-12 saat** (bir hafta yarım gün).

### 2.3 5058'in akıbeti

```
FAZ 1-5 sürerken: 5058 paralel açık (Altan referans olarak bakabilir)
FAZ 6 sonrası:    5058 read-only mode
FAZ 7'de:         5058 durdur + Task Scheduler kaldır + finans.db arşive taşı
```

---

## 3. Mimari — CPS Native Yapı

### 3.1 Klasör yapısı

```
D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\
├── modules\
│   └── finans\                          [YENI blueprint]
│       ├── __init__.py                  blueprint tanımı
│       ├── routes.py                    tüm endpointler
│       └── yetki_dekorator.py           @finans_yetki_gerekli
│
├── services\
│   └── finans\                          [YENI service paketi]
│       ├── __init__.py
│       ├── odeme_service.py
│       ├── kredi_service.py
│       ├── kasa_service.py
│       ├── cek_service.py
│       ├── takvim_service.py
│       ├── nakit_akisi_service.py
│       ├── planlama_service.py
│       ├── kur_service.py               (sistem_kur'dan okur)
│       └── audit_helper.py
│
├── templates\
│   └── finans\                          [YENI template paketi]
│       ├── _layout.html                 base.html extend
│       ├── ozet.html                    Dashboard
│       ├── odemeler.html                Ödeme liste + modal
│       ├── krediler.html                Kredi liste + kart
│       ├── kredi_detay.html             Tek kredi + taksit timeline
│       ├── cekler.html                  Çek listesi (Cek_Senet)
│       ├── kasa.html                    Kasa hareketleri + bakiye
│       ├── takvim.html                  Aylık grid
│       ├── nakit_akisi.html             6 ay strip + günlük
│       └── planlama_12ay.html           Yıllık matris
│
└── migrations\
    └── 020_finans_native_yetki.py       [YENI]
    └── 021_finans_native_schema.py      [YENI]
```

### 3.2 Route haritası

```
/finans                                  → Dashboard (Özet)
/finans/odemeler                         → Ödemeler liste
/finans/odemeler/yeni                    → Yeni ödeme
/finans/odemeler/<id>                    → Detay/PUT/DELETE
/finans/odemeler/<id>/odendi             → POST durum geçiş

/finans/krediler                         → Krediler liste
/finans/krediler/yeni                    → Yeni kredi + taksit otomatik
/finans/krediler/<id>                    → Detay + taksit timeline
/finans/kredi-taksitleri/<id>/odendi     → POST taksit ödendi

/finans/cekler                           → Çekler liste (Cek_Senet)
/finans/cekler/yeni                      → Yeni çek
/finans/cekler/<id>                      → Detay

/finans/kasa                             → Kasa hareketleri + bakiye
/finans/kasa/giris                       → POST hareket ekle (giriş)
/finans/kasa/cikis                       → POST hareket ekle (çıkış)

/finans/takvim                           → Aylık takvim
/finans/nakit-akisi                      → Nakit akışı (6 ay)
/finans/planlama                         → 12 ay planlama matrisi

/finans/api/ozet                         → KPI JSON
/finans/api/kurlar                       → CPS sistem_kur okur
/finans/api/export-xlsx                  → Excel rapor

/finans/hatirlatmalar                    → D6.1 pattern (vade yakın uyarı)
/finans/hatirlatmalar/<id>/dismiss
/finans/hatirlatmalar/<id>/resolved
```

### 3.3 Service-layer pattern (D6.1'den proven)

```
Routes minimal (auth + validation + service çağrısı)
        ↓
Service business logic (KPI hesaplama, taksit oluşturma, durum geçiş)
        ↓
DB layer (mock_data.db, finans_* tabloları)
        ↓
Audit_helper (her INSERT/UPDATE/DELETE'te log)
```

---

## 4. DB Şeması — Yeni Tablolar

### 4.1 CPS'te zaten kullanılacak (DOKUNULMAZ)

```
finans_anlasma (36)            Mevcut — koru
finans_anlasma_model (98)       Mevcut — koru
finans_odeme_plan (212)         KULLANILACAK — ana ödeme tablosu
finans_avans (6)                Mevcut — koru
finans_simulasyon (7)           Mevcut — koru
Banka_Kart (2)                  KULLANILACAK — banka tanımları
Kasa_Kart (1)                   KULLANILACAK — kasa hesap tanımları
Cek_Senet (0)                   KULLANILACAK — çek modülü
Cari_Kart (10)                  Mevcut — koru
Cari_Har (82)                   Mevcut — koru
nakit_giris_beklenen (2)        KULLANILACAK — beklenen gelir
sistem_kur (24)                 KULLANILACAK — TCMB (finans çekmeyecek)
```

### 4.2 Yeni eklenecek (6 tablo)

**finans_kredi** — Kredi ana (eski 'krediler' yerine düzgün şema)
```
id, entity, ad, tip, banka_kart_id (FK), toplam_tutar, para,
taksit_sayisi, taksit_tutari, faiz_orani, baslangic_tarihi, bitis_tarihi,
not_metin, olusturan_id, olusturma, durum (AKTIF/KAPALI/IPTAL)
```

**finans_kredi_taksit** — Düzgün FK ilişki (eski 'odemeler tip=taksit' yerine)
```
id, kredi_id (FK finans_kredi), taksit_no, vade_tarihi, tutar,
odenen_tutar, odeme_tarihi, durum (BEKLIYOR/ODENDI/GECIKTI), not_metin
```

**finans_kasa_hareket** — Kasa_Kart bağlantılı
```
id, kasa_kart_id (FK), entity, tip (GIRIS/CIKIS), tutar, para,
aciklama, tarih, olusturan_id, olusturma
```

**finans_planlama** — 12 ay planlama
```
id, entity, kategori (gelir/maas/kredi/vergi/...), aciklama, tutar, para,
tarih, durum (PLANLI/ODENDI/GECIKTI/IPTAL), olusturan_id, olusturma
```

**finans_audit** — Audit log (kritik, eski sistemde yoktu)
```
id, tablo, kayit_id, islem (INSERT/UPDATE/DELETE/ODENDI),
eski_deger (JSON), yeni_deger (JSON), kullanici_id, kullanici_ad,
ip_adres, zaman
```

**finans_hatirlatma** — Finansal sinyal (D6.1 pattern)
```
id, tip, rule_id, hedef_tablo, hedef_id, entity, mesaj, seviye,
durum (AKTIF/GORULDU/DISMISS/RESOLVED), tekrar_sayisi, son_tetiklenme,
gorulen_kullanici_id, gorulen_zaman, cozulen_zaman, cozulen_aciklama, olusturma
```

### 4.3 Migration numarası

```
Mevcut schema_migrations: 002, 003, 004_overlay, 010, 011
Yeni:
  020_finans_native_yetki.py        — Rol + yetki ekle
  021_finans_native_schema.py       — 6 yeni tablo + 12 index
```

### 4.4 Veri akışı örneği

```
Yeni ödeme ekle:
  Route → odeme_service.create()
       → finans_odeme_plan INSERT (CPS'in mevcut tablosuna)
       → audit_helper.log('INSERT', kullanici_id)
       → finans_audit INSERT

Yeni kredi ekle:
  Route → kredi_service.create_with_taksitler()
       → finans_kredi INSERT
       → finans_kredi_taksit x N INSERT (taksit_sayisi kadar)
       → finans_audit log
```

---

## 5. Yetki Mimarisi

### 5.1 Hedef yetki matrisi

| Rol | FINANS_GORME | FINANS_ODEME | FINANS_KREDI | FINANS_KASA | FINANS_PLANLAMA | FINANS_RAPOR |
|-----|:---:|:---:|:---:|:---:|:---:|:---:|
| **sistem** (admin) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **finans_yonetici** (Altan) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **finans_okur** (gelecek) | ✓ | (sadece okuma) | (sadece okuma) | (sadece okuma) | (sadece okuma) | ✓ |
| **yonetim** | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **usta** (Halil) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **personel** | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |

### 5.2 Migration 020 detayı

```
Yeni rol:
  sistem_rol: RolAd='finans_yonetici', Aciklama='Finans Konsolu Yöneticisi'

6 yeni yetki:
  sistem_yetki: FINANS_GORME, FINANS_ODEME_CRUD, FINANS_KREDI_CRUD,
                FINANS_KASA_CRUD, FINANS_PLANLAMA_CRUD, FINANS_RAPOR

Rol-yetki mapping:
  sistem_rol_yetki:
    sistem (admin) → 6 yetkinin hepsi
    finans_yonetici → 6 yetkinin hepsi
    finans_okur → FINANS_GORME + FINANS_RAPOR (gelecek için altyapı)

Altan kullanıcı:
  sistem_kullanici: KullaniciAdi='altan', Sifre=<hash>, RolAd='finans_yonetici',
                    Ad='Altan', Soyad='', AktifMi=1
```

### 5.3 Sidebar render kontrolü

```
{# base.html veya _sidebar.html içinde mevcut Finans grubunda #}
{# Sadece 1 koşul eklenir: #}
{% if 'FINANS_GORME' in session.get('yetkiler', []) %}
  <div class="sidebar-item">
    <a href="/finans">
      <i class="icon-finans">💰</i>
      Finans Konsolu
    </a>
  </div>
{% endif %}
```

### 5.4 Route dekoratör

```
@finans_bp.route('/finans/odemeler')
@finans_yetki_gerekli('FINANS_ODEME_CRUD')
def odemeler_liste():
    ...
```

---

## 6. UI Tasarım Dili — Eski vs CPS

### 6.1 Karşılaştırma

| Konu | Eski (5058) | CPS (8080) | Karar |
|------|-------------|------------|-------|
| Brand renk | Mavi `#2563eb` | **Altın `#d4a52f`** | CPS altın kullanılacak |
| Font | Inter | Inter | Aynı |
| Layout | Tek HTML, kendi header/nav | base.html + sidebar/topbar | CPS layout |
| Modal sistem | Kendi modal'ı | CPS standardı (varsa) | CPS standardı |
| Card stil | Sol border 4px accent | CPS card stili | CPS standardı |
| KPI kart | Emoji + renk + sayı | (incele, CPS varsa o) | Hibrit |
| Tablo | Custom .data-table | CPS tablo stili | CPS standardı |
| Entity tab | Header'da 4 tab | Sidebar veya filter | İncelenecek |

### 6.2 Render hedefi

```
Header (CPS topbar — DOKUNULMUYOR):
  Solariz logo | Tab'lar | MOCK badge | Sistem Yoneticisi | Cikis

Sidebar (CPS — DOKUNULMUYOR):
  Ana Sayfa
  Yönetim
  Üretim
  ...
  💰 Finans Konsolu  ← YENI koşullu
     ├── Özet
     ├── Ödemeler
     ├── Krediler
     ├── Çekler
     ├── Kasa
     ├── Takvim
     ├── Nakit Akışı
     └── 12 Ay Planlama

Main content:
  CPS card stili, altın accent, mevcut grid sistemi
```

### 6.3 Entity seçimi

Eski sistemde header'da 4 entity tab vardı (Solariz/NexGen/Pera/Şahsi). CPS native'de:

- **Seçenek A:** Sidebar sub-menü (her entity için ayrı /finans/solariz, /finans/nexgen vb)
- **Seçenek B:** Topbar yanında dropdown (CPS standardına uygun)
- **Seçenek C:** İlk ekranda kart seçimi, sonra session'da tut

**Önerim:** Seçenek B (dropdown) — minimum CPS bozma, kullanım kolay.

---

## 7. Eski Sistemin Akıbeti

### 7.1 Geçiş aşamaları

```
FAZ 0  Şimdi              5058 açık, 8080 CPS açık (D6.1 sonrası)
       Eski sistem        Altan kullanmıyor, sadece RECON için gördük

FAZ 1-2 Yetki + Şema      5058 paralel açık (referans)
                          Altan eski sistemi açabilir bakabilir

FAZ 3-5 CRUD + UI         5058 paralel açık (referans)
                          Altan yeni native UI ile veri girmeye başlıyor
                          Eski veriye sadece eski sistemden bakıyor

FAZ 6  Test               5058 ŞIMDILIK AÇIK
                          Altan native sistemde tüm işlemlerini yapıyor
                          1 hafta paralel kullanım

FAZ 7  Kapatma            5058 durdurulur
                          Task Scheduler kaydı kaldırılır
                          finans.db → \\solarizdb\arsiv\finans_referans_20260601\
                          Tek finans sistemi: CPS native
```

### 7.2 Güvenlik notu

**5058 şu an `host='0.0.0.0'`** — dışarıdan erişilebilir. FAZ 0 sonunda en azından `host='127.0.0.1'` yapılması önerilir (1 satır değişiklik, restart). Veya Windows Firewall'dan dış IP engellenir.

**Ama:** Karar "kalıcı çözüm değil" olduğu için **bu da gerekli değil**. 1-2 hafta içinde tamamen kapanacak. Acil değil.

---

## 8. Hatırlatma Motoru — Finansal Sinyaller (D6.1 Pattern)

D6.1 sinyal motoru başarılı olduğu için aynı pattern finansa uygulanır.

### 8.1 Önerilen rule'lar

| Rule | Tip | Mantık | Çıktı |
|------|-----|--------|-------|
| **R010** | `ODEME_VADESI_3GUN` | vade <= bugün+3 gün, durum=bekliyor | "Hasan Haykır ödemesi 3 gün içinde — ₺3.5M" |
| **R011** | `ODEME_GECIKTI` | vade < bugün, durum != odendi | "Esra Orhan — 47 gün gecikme" |
| **R012** | `KREDI_TAKSITI_YAKIN` | vade <= bugün+7 gün, durum=BEKLIYOR | "Kuveytturk taksit 7 gün içinde — ₺266K" |
| **R013** | `KASA_DUSUK` | TL bakiye < threshold (örn 1M) | "Solariz kasa bakiye düşük — ₺X" |
| **R014** | `CEK_VADESI_YAKIN` | Cek_Senet vade <= bugün+5 gün | "Demirel Oluklu çek vadesi yakın" |

### 8.2 Engine yapısı (D6.1 ile aynı)

```
app/services/finans/hatirlatma_engine.py
  - FEATURE_FLAGS = {R010: True, R011: True, R012: True, R013: False, R014: True}
  - Her rule sınıfı (Rule_R010_..., Rule_R011_...)
  - save_signal idempotent
  - run_rule + run_all_rules

Endpoint:
  POST /yonetim/finans-engine/test     (manuel tetik, dry_run default true)
  GET  /finans/hatirlatmalar           (D6.1 sinyaller-ui gibi)
  POST /finans/hatirlatmalar/<id>/dismiss
  POST /finans/hatirlatmalar/<id>/resolved
```

### 8.3 Sidebar badge

```
{# Sidebar'da Finans Konsolu yanında badge #}
💰 Finans Konsolu  [3]  ← bekleyen sinyal sayısı
```

### 8.4 Scheduler

Manuel tetik yeterli. İleride Windows Task Scheduler ile dakikalık otomatik (D6.1-E gibi).

---

## 9. Hızlı + Güvenli Faz Planı

### FAZ 0 — RECON + Onay (1-2 saat)

- ✅ Bu doküman
- Adem onayı (FAZ planı + mimari + DB şeması)
- Karar: 6 soru (bölüm 11)

**Çıktı:** Plan onaylı, ilk faz hazır.

---

### FAZ 1 — Yetki Altyapısı (2-3 saat)

**Hedef:** Sidebar'da Altan + admin "Finans Konsolu" görür, başkaları görmez.

**Adımlar:**
1. Migration `020_finans_native_yetki.py`:
   - Yeni rol: `finans_yonetici`
   - 6 yeni yetki: FINANS_*
   - Rol-yetki mapping (admin + finans_yonetici tüm yetkiler)
2. Altan kullanıcı: `sistem_kullanici` INSERT
3. Auth flow'da yetkiler session'a koyulsun (eğer şu an yoksa)
4. `base.html` veya `_sidebar.html`'de 1 koşullu menü item
5. TEST: 3 farklı rol kullanıcısı ile login → sidebar görünüm
6. Mini snapshot: `STABLE_FINANS_NATIVE_F1_YETKI_OK_*`

**Risk:** Düşük. CPS auth zaten çalışıyor.
**Hash etkilenen:** `base.html`, `auth.py` (yetki session — gerekirse)

---

### FAZ 2 — DB Şeması + Boş Modül (3-4 saat)

**Hedef:** `/finans` boş ama yetkilendirilmiş sayfa, placeholder render.

**Adımlar:**
1. Migration `021_finans_native_schema.py`:
   - 6 yeni tablo + 12 index
   - SEED YOK
2. Blueprint `app/modules/finans/`:
   - `__init__.py` (blueprint register)
   - `routes.py` (placeholder `/finans` ve 8 sub-route)
   - `yetki_dekorator.py`
3. Service paketi `app/services/finans/` (boş iskelet)
4. Template `app/templates/finans/`:
   - `_layout.html` (base.html extend + finans alt-nav)
   - `ozet.html` (placeholder)
5. `app.py`'de blueprint register
6. TEST: Altan login → `/finans` 200 + placeholder
7. Mini snapshot: `STABLE_FINANS_NATIVE_F2_BOSH_OK_*`

**Risk:** Düşük. Sadece yeni dosyalar, app.py 1 satır blueprint register.
**Hash etkilenen:** `app.py`

---

### FAZ 3 — CRUD'lar (8-10 saat, 3 alt-faz)

**FAZ 3A — Ödemeler (3-4 saat)**
- `odeme_service.py`: list, get, create, update, delete (soft), odendi
- `finans/odemeler.html` + modal
- `routes.py` ödeme endpointleri
- Audit log her CRUD'da
- TEST: Altan 5 ödeme ekle/sil/güncelle/odendi
- Mini snapshot: `STABLE_FINANS_F3A_ODEME_OK_*`

**FAZ 3B — Krediler + Taksit otomatik (3 saat)**
- `kredi_service.py`: create_kredi → taksitleri otomatik oluştur (taksit_sayisi kadar)
- `finans/krediler.html` (liste) + `kredi_detay.html` (timeline)
- Taksit ödendi endpoint
- TEST: Yeni kredi 12 taksit oluşsun, taksit ödendiğinde kredi kalan güncellensin
- Mini snapshot: `STABLE_FINANS_F3B_KREDI_OK_*`

**FAZ 3C — Kasa + Çekler (2-3 saat)**
- `kasa_service.py`: hareket ekle, bakiye hesap
- `cek_service.py`: Cek_Senet üzerinden CRUD
- Template'ler
- TEST: Kasa giriş/çıkış, bakiye, çek ekle/durum
- Mini snapshot: `STABLE_FINANS_F3C_KASA_CEK_OK_*`

**Çıktı:** Altan elle veri girişi yapabilir, eski sistemden bakıp aktarabilir.

---

### FAZ 4 — Görsel Ekranlar (6-8 saat, 4 alt-faz)

**FAZ 4A — Özet Dashboard (2 saat)**
- KPI kartları (4 tane)
- Borç özet tablosu
- Yaklaşan ödemeler (30 gün)
- Aktif krediler özeti
- Aylık ödeme trendi chart

**FAZ 4B — Takvim (2 saat)**
- Aylık grid (CPS card stili)
- Gün tıklanınca o günün ödemeleri panel

**FAZ 4C — Nakit Akışı (3-4 saat)**
- 6 ay strip (üst)
- Günlük akış (sol panel)
- 6 ay bakiye grafik (sağ)
- Kritik günler liste
- Gider kategorisi dağılım
- Beklenen gelir formu (nakit_giris_beklenen tablosu)

**FAZ 4D — 12 Ay Planlama (1-2 saat)**
- Yıl x ay matris (firma renk-kod)
- Aylık/haftalık görünüm toggle
- Hücre tıklanınca detay panel
- Mini snapshot: `STABLE_FINANS_F4_UI_OK_*`

**Çıktı:** Eski sistemdeki 8 tab fonksiyonel olarak CPS içinde.

---

### FAZ 5 — Hatırlatma Motoru (3-4 saat)

D6.1 sinyal motoru pattern'i finans için:
- `app/services/finans/hatirlatma_engine.py`
- 5 rule (R010-R014, R013 pasif başlangıçta)
- FEATURE_FLAGS dict
- `save_signal` idempotent (D6.1 copy-pattern)
- 5 CRUD endpoint (D6.1-C pattern)
- UI template `hatirlatmalar.html` (D6.1-D sinyaller.html benzer)
- Sidebar badge
- TEST: R010 tetikle, vadesi yakın ödemeler sinyal üretsin
- Mini snapshot: `STABLE_FINANS_F5_HATIRLATMA_OK_*`

**Çıktı:** Altan'a otomatik vade uyarısı.

---

### FAZ 6 — Export + Hızlı Giriş + Cilalama (2-3 saat)

- `/finans/api/export-xlsx` (openpyxl ile)
- Quick Add modal (eski sistemdeki gibi tek tıkla)
- Klavye kısayolları (Ctrl+N yeni ödeme vb)
- Mobil responsive kontrol
- Performans (1000+ ödeme listesi yavaş mı?)
- Mini snapshot: `STABLE_FINANS_F6_EXPORT_OK_*`

**Çıktı:** Aylık Excel raporu, hızlı kullanım.

---

### FAZ 7 — 5058 Migrasyonu + Kapanış (1 saat)

- 5058 sunucusunu durdur (`Stop-Process`)
- Task Scheduler kaydı kaldır
- `D:\Firma_Ozel\adem\solariz finans\finans.db` → `\\solarizdb\arsiv\finans_referans_20260601\`
- `solariz finans/` klasörü `_arsiv_5058_eski/` adıyla yeniden adlandır
- Final snapshot: `STABLE_FINANS_NATIVE_FULL_OK_*`
- Final rapor: `FINANS_NATIVE_FAZ7_KAPANIS.md`

**Çıktı:** Tek finans sistemi (CPS native), eski sistem arşivde.

---

### TOPLAM SÜRE

| Faz | Süre | Kümülatif |
|-----|------|-----------|
| FAZ 0 RECON | 1-2 saat | 2 |
| FAZ 1 Yetki | 2-3 saat | 5 |
| FAZ 2 Şema + Boş Modül | 3-4 saat | 9 |
| FAZ 3 CRUD (A+B+C) | 8-10 saat | 19 |
| FAZ 4 UI (A+B+C+D) | 6-8 saat | 27 |
| FAZ 5 Hatırlatma | 3-4 saat | 31 |
| FAZ 6 Export | 2-3 saat | 34 |
| FAZ 7 Migrasyon | 1 saat | 35 |
| **TOPLAM** | **26-35 saat** | |

**Tahmini takvim:** Günde 4-5 saat çalışmayla **6-9 gün**. Veya 2 hafta rahat çalışmayla.

---

## 10. Risk Yönetimi

### 10.1 Risk matrisi

| Risk | Olasılık | Etki | Mitigasyon |
|------|----------|------|-----------|
| Saha kesinti | Çok düşük | Yüksek | Tüm değişiklik `finans/` altında, hash gate |
| Yetki yanlış kurulup Halil görür | Düşük | Orta | Her FAZ sonu farklı rolde test (3 user) |
| Audit eksik kalıp DELETE veri kaybı | Düşük | Yüksek | FAZ 2'de audit_helper ilk kurulsun, FAZ 3'ten itibaren zorunlu |
| Altan veri girişine adapt olamaz | Orta | Düşük | İlk hafta Adem destek, Quick Add modali, kısayollar |
| Eski sistem yanlışlıkla import edilir | Düşük | Yüksek | "Import endpoint" hiç eklenmeyecek, sadece elle giriş |
| TCMB sistem_kur ile çakışma | Düşük | Düşük | Tek kaynak `sistem_kur`, finans READ only |
| Cek_Senet (0 kayıt) şeması yetmez | Orta | Orta | FAZ 3C başında kolon kontrol, eksikse ALTER TABLE |
| finans_odeme_plan mevcut veri tutarsız | Orta | Orta | FAZ 3A başında veri kalitesi kontrolü |

### 10.2 Geri alma stratejisi

Her FAZ'da:
- Migration `down()` fonksiyonu yazılır (idempotent)
- Yedek alınır (`mock_data.db.YEDEK_FINANS_F<N>_<timestamp>`)
- Snapshot alınır (`STABLE_FINANS_F<N>_OK_<timestamp>`)
- Rollback komutu rapora yazılır

**Tam geri:**
```
DROP TABLE finans_kredi, finans_kredi_taksit, finans_kasa_hareket,
           finans_planlama, finans_audit, finans_hatirlatma;
DELETE FROM sistem_kullanici WHERE KullaniciAdi='altan';
DELETE FROM sistem_rol WHERE RolAd='finans_yonetici';
DELETE FROM sistem_yetki WHERE YetkiAd LIKE 'FINANS_%';
sidebar 1 satır geri al
blueprint app.py register satırı geri al
modules/finans/ services/finans/ templates/finans/ klasörlerini sil
```

**~10 dakika.**

---

## 11. Adem'in Vermesi Gereken 6 Karar

| # | Karar | Önerim |
|---|-------|--------|
| 1 | Altan CPS hesabı `sistem_kullanici` mı `personel_kullanici` mı? | `sistem_kullanici` (admin haklarına yakın) |
| 2 | Şifre hash yöntemi (mevcut CPS'te ne kullanıyor?) | Mevcut sistem ile aynı (bcrypt/scrypt/MD5?) |
| 3 | Entity seçimi UI'da nasıl? (Solariz/NexGen/Pera/Şahsi) | Topbar dropdown |
| 4 | Mevcut `finans_odeme_plan` (212 kayıt) korunsun mu yoksa temizlensin mi? | Adem incelesin sonra karar |
| 5 | Snapshot adlandırma `STABLE_D8_*` veya `STABLE_FINANS_NATIVE_*`? | `STABLE_FINANS_NATIVE_*` (D6.1 ile çakışmasın) |
| 6 | Veri girişi başlama zamanı (FAZ 3 sonu mu yoksa FAZ 6 sonu mu?) | FAZ 3 sonu (CRUD tamamlanır tamamlanmaz Altan girmeye başlasın) |

---

## 12. Yeni Claude Oturumu için Hızlı Devir

```
Durum (2026-05-18 14:50):
  - Eski 5058 sistem AÇIK, Altan login olmuş, UI çalışıyor (referans)
  - Karar: 5058 KALICI DEĞİL. CPS native modül yapılacak.
  - FAZ 0 RECON tamamlandı (bu dosya)
  - Eski finans.db CANLIYA ALINMAYACAK, temiz veri girişi

Mimari özet:
  Blueprint:   app/modules/finans/
  Service:     app/services/finans/ (8 service)
  Template:    app/templates/finans/ (10 template)
  Migration:   020_finans_native_yetki.py + 021_finans_native_schema.py
  6 yeni tablo: finans_kredi, finans_kredi_taksit, finans_kasa_hareket,
                finans_planlama, finans_audit, finans_hatirlatma
  Yetki:       finans_yonetici rol + 6 FINANS_* yetki + Altan user

Süreç:
  FAZ 1 Yetki (2-3h) → FAZ 2 Şema (3-4h) → FAZ 3 CRUD (8-10h) →
  FAZ 4 UI (6-8h) → FAZ 5 Hatırlatma (3-4h) → FAZ 6 Export (2-3h) →
  FAZ 7 5058 Kapat (1h)
  TOPLAM: 26-35 saat / 6-9 gün

Korumalar:
  base.html sadece sidebar'a 1 koşullu menü item ekler
  CPS auth/yetki sistemi DOKUNULMAZ
  CPS finans tabloları (anlasma, odeme_plan, Banka_Kart, Cek_Senet vb) DOKUNULMAZ
  Saha üretimi (uretim_kayit, emir_alt_proses, operasyon_sinyal) DOKUNULMAZ

İlk adım (Adem onayı sonrası):
  FAZ 1 yetki migration staging hazırla → AST + DRY-RUN → atomic move → smoke
```

---

## SONUÇ

5058'den CPS native'e geçiş **mimari olarak hazır**, faz planı **detaylı**, riskler **belirlenmiş**, geri alma **mümkün**.

**26-35 saatlik bir sprint serisi.** Adem'in günlük çalışma temposuna göre **6-9 gün**.

Eski sistem **geçiş süresince paralel açık** (referans), FAZ 7'de kapanır.

**Saha üretimine sıfır risk** — tüm değişiklikler izole modül altında.

İlk gerçek adım: **Adem'in 6 karar onayı** + FAZ 1 başlangıcı.

---

*Doküman sonu: 2026-05-18 ~14:50*
*Yazan: Claude — FINANS_NATIVE_FAZ1 RECON sprintı*
*Sonraki: 6 karar + FAZ 1 yetki staging*
