# YETKI_V2 — FAZ 2 Master Plan

> **Amac:** CPS Native runtime yetki cekirdegini kalici olarak standardize etmek. FAZ 1 stabilizasyon sonrasi mimari temizlik + tek core kurulumu.
>
> **Yazim tarihi:** 2026-05-20
> **Yazan:** Adem & Claude (Solariz CPS)
> **Hedef okuyucu:** Claude (gelecek oturumlar) + Adem (referans)
> **Statu:** PLAN — uygulama beklemede, F2.1'den baslayacak
> **On-kosul:** FAZ 1 apply edilmis (20.05.2026 16:52:09), CPS restart yapilmis (16:52:20)

---

## 0. Hizli Statu

| Madde | Durum |
|---|---|
| FAZ 1 — Stabilization | ✅ TAMAMLANDI (3 dosya apply, restart OK) |
| FAZ 2 — Core Standardization | ⏳ BU PLAN |
| Acil bug listesi | ✅ Cozuldu (Mehmet, Muhasebe) |
| Acik tekil tani | Samet/Numune dosya bug (ayri is, FAZ 2 paralel) |
| CPS runtime stabilitesi | ✅ Hash dogrulandi, regression yok |

---

## 1. VIZYON

CPS bugun **4 farkli yetki kontrol yontemi** kullaniyor:

```
1. @yetki_gerekli(kod, action)   — standart core (ithalat + proses_takip)
2. @yetki_gerek(kod)             — grafik modulu lokal helper, action yok
3. @admin_gerekli                — yonetim modulu, 16 yer
4. _yetki_var_mi() / _cof_yetkili() — ozel helper'lar, panel by-pass
```

Bu durum **panel ↔ runtime hizalamasini** kiriyor:

- Panelde yetki acik gosterilen kullanici 403 alabiliyor
- Panelde kapali olan kullanici (yanlislikla) erisebiliyor
- "Hangi yetkiyle hangi sayfa acilir" sorusu deterministtik degil
- Audit, debug, yeni modul ekleme — hepsi karisik

**FAZ 2 hedefi:** Bu 4 yontemi **TEK CORE'a** indirgemek.

### 1.1 Hedef mimari (FAZ 2 sonu)

```
                  ┌─────────────────────────┐
                  │   sistem_yetki (DB)     │
                  │   44 kod × 7 action     │
                  └────────────┬────────────┘
                               ↓
                  ┌─────────────────────────┐
                  │  sistem_rol_yetki (DB)  │
                  │   80 satir × 7 boyut    │
                  └────────────┬────────────┘
                               ↓
                  ┌─────────────────────────┐
                  │  kullanici_yetkileri()  │
                  │   set: kod:action       │
                  └────────────┬────────────┘
                               ↓
                  ┌─────────────────────────┐
                  │      yetki_var()        │
                  │   (kod, action)         │
                  │   tek dogruluk kaynagi  │
                  └────────────┬────────────┘
                               ↓
                  ┌─────────────────────────┐
                  │  @yetki_gerekli()       │
                  │   tek decorator         │
                  └────────────┬────────────┘
                               ↓
                  ┌─────────────────────────┐
                  │  TUM ROUTE'LAR          │
                  │  + sidebar yetki()      │
                  │  + JS API guard         │
                  └─────────────────────────┘
```

### 1.2 Tek Core ilkesi

| Madde | Eski | Yeni (FAZ 2 sonu) |
|---|---|---|
| Decorator | 4 farkli | TEK: `@yetki_gerekli(kod, action)` |
| Action modeli | Cogu yerde yok | 7 boyut zorunlu: `can_view/create/update/delete/approve/report/manage` |
| Admin shortcut | 2 yerde tekrar (`_admin_mi`, `kullanici_yetkileri`) | TEK: `auth.py` icinde `{'*'}` set |
| Panel by-pass | 5+ ozel helper | YOK |
| Sidebar koruma | Hardcoded `RolAd=='Yonetim'` (43 yer) | `{% if yetki(...) %}` (tek pattern) |

---

## 2. FAZ 1 TAMAMLANANLAR (Referans)

Apply tarihi: **2026-05-20 16:52:09**
Apply scripti: `D:\Firma_Ozel\adem\patch_yetki_isim_uyumsuzluk_20260520.py`
Yedek konumu: `D:\Firma_Ozel\adem\_BACKUPS\YETKI_V2\*_PRE_PATCH_20260520_165209.bak`

### 2.1 Yapilan degisiklikler

| # | Dosya | Hash Once | Hash Sonra | Degisim |
|---|---|---|---|---|
| F1.1 | `auth.py` | `777A3D04B9E2` | `DA44F2CC6FE3` | +27 byte |
| F1.2 | `ithalat/routes.py` | `7F40C7962062` | `20AF0F392954` | -4 byte |
| F1.3 | `planlama/proses_takip.py` | `A34734325C3A` | `27D26A1EF80F` | -649 byte |

### 2.2 Onceki YETKI_V2 patch'i (15:50:10)

Apply tarihi: **2026-05-20 15:50:10**
Apply scripti: `D:\Firma_Ozel\adem\patch_auth_yetki_v2_20260520.py`
Yedek: `auth_py_PRE_PATCH_20260520_155010.bak`

- auth.py mojibake fix (`'YÃ¶netim'` → `'Yonetim'`)
- SuperAdmin bypass marker (`YETKI_V2_SUPERADMIN_BYPASS_20260520`)
- 10 UTF-8 string temizligi (`KullanÄ±cÄ±`, `Åifre` vs.)
- `_tip_guard` hibrit kullanici uyumu

### 2.3 Cozulen acil bug'lar

| Kullanici | Onceki durum | Sonraki durum |
|---|---|---|
| Mehmet (Planlama) → `/proses-takip` | 403 | ✅ Acilir |
| Muhasebe → `/ithalat/parti/liste` | 403 | ✅ Acilir |
| Muhasebe → `/ithalat/parti/.../guncelle` | 403 | ✅ Calisir (can_update) |
| Halil (RolId=1, Tip='usta') → Yonetim ekranlari | engellenmis | ✅ Calisir |
| Admin → her yer | calisirdi | ✅ Aynisi |

### 2.4 FAZ 1 ile kazanilan altyapi

| Yetenek | Kullanim |
|---|---|
| `yetki_gerekli(kod, action='can_view')` | Geriye uyumlu, mevcut 200+ cagri bozulmaz |
| `yetki_var(kod, action)` | Default 'can_view', V2 7 action destegi |
| SuperAdmin bypass (TipGuard) | `RolAd='Yonetim'` veya `KullaniciAdi='admin'` |

---

## 3. MEVCUT PROBLEM HARITASI

Recon (2026-05-20) sonucu tespit edilen aktif sorunlar:

### 3.1 Helper Cesitliligi

| Helper | Dosya | Endpoint Sayisi | Davranis | Risk |
|---|---|---|---|---|
| `_yetki_var_mi()` | `planlama/routes.py:L45` | 7 cagri | RolAd in ('Yonetim','Planlama') or kad=='admin' | Panel by-pass |
| `_cof_yetkili()` | `finans/routes.py:L548 etrafi` | 3+ cagri | Bilinmiyor, ic helper | Panel by-pass |
| `_admin_mi()` | `grafik/routes.py:L18` | 1+ kullanim | RolAd=='Yonetim' or kad=='admin' | Auth.py shortcut'iyla tekrar |
| `yetki_gerek` (lokal) | `grafik/routes.py:L27` | 54 endpoint | yetki_var(kod) — action yok | Default 'can_view' |

### 3.2 Hardcoded RolAd Kontrolleri

- **43 satir** `RolAd == 'Yonetim'` veya `KullaniciAdi == 'admin'` sidebar/template'lerde
- **Cogu zaten gereksiz** (auth.py SuperAdmin shortcut bu kontrolu sagliyor)
- Riski dusuk ama sistem temizligi acisindan kaldirilmali

### 3.3 Upload/Download Action Eksikleri

| Endpoint | Mevcut decorator | Mevcut action | Olmasi gereken |
|---|---|---|---|
| `/grafik/numune/<id>/belge/yukle` POST | `@yetki_gerek('grafik.numune')` | `can_view` (default) | `can_create` |
| `/grafik/urun/<id>/belge/yukle` POST | `@yetki_gerek('grafik.urun')` | `can_view` | `can_create` |
| `/grafik/tedarikci/<id>/belge/yukle` POST | `@yetki_gerek('grafik.tedarikci')` | `can_view` | `can_create` |
| `/grafik/siparis/<id>/belge/yukle` POST | `@yetki_gerek('grafik.cin_siparis')` | `can_view` | `can_create` |
| `/grafik/sevkiyat/<id>/belge/yukle` POST | `@yetki_gerek('grafik.maliyet')` | `can_view` | `can_create` |
| `/grafik/belge/<id>/sil` POST | YOK | — | `can_delete` |
| `/finans/cin-ofis/upload` POST | `_cof_yetkili()` | manuel | `can_create` |
| `/yonetim/belge/<id>` GET | YOK (sadece login) | — | `can_view` |
| `/yonetim/belge/<id>/sil` POST | `@admin_gerekli` | admin sınırlı | `can_delete` |

### 3.4 Orphan Permission Kodlari

DB'de 44 yetki kodu tanimli, runtime'da SADECE 4'u kullaniliyor (FAZ 1 sonrasi):

```
KULLANILIYOR (4): ithalat.parti, ithalat.maliyet, ithalat.odeme, planlama.proses_takip
KULLANILMIYOR (40): canli_saha, enjeksiyon.*, finans.*, grafik.*, hedef.*, nakit.*,
                    personel_giris, planlama.karar_masasi, planlama.operasyon_raporu,
                    tasks, usta, yonetim.kullanici, yonetim.kur, yonetim.log, yonetim.rol
```

**Sebep:** Grafik (54 yer), planlama (7 yer), finans (?) ozel helper kullaniyor → runtime DB'yi sormuyor.

### 3.5 Panel/Runtime Action Uyumsuzlugu

Mevcut decorator'lar action belirtmiyor → tum POST/UPDATE/DELETE islemleri `can_view` ile koruyor. Ornek:

- Panel: Samet'e `grafik.numune can_create=1, can_view=1` verilmis
- Runtime: `@yetki_gerek('grafik.numune')` → can_view kontrolu → Samet gecer
- **Sorun:** Eger Samet'e sadece `can_view=1, can_create=0` verilse de gecer (yanlislikla)
- **Cozum:** POST endpoint'leri `can_create` veya `can_update` ile koruyacak

### 3.6 Sidebar Bagimsiz Kontrolleri

- `base.html` ve setup script'lerinde 43 satir `g_user.RolAd == 'Yonetim'` veya `g_user.KullaniciAdi == 'admin'`
- Bunlar `{% if yetki('xxx') %}` ile **OR** baglaniyor → SuperAdmin shortcut auth.py'de zaten var
- Cift kontrol gereksiz ama zararsiz
- Temizlik gorevi (F2.5)

---

## 4. TEK CORE KURALI

FAZ 2 sonrasi yeni kod yazarken **kati kurallar**:

### 4.1 ❌ YASAK

| # | Yasak | Sebep |
|---|---|---|
| 1 | Ozel `_yetki_var_mi`, `_admin_mi`, `_cof_yetkili` benzeri helper | Panel by-pass |
| 2 | Hardcoded `RolAd == 'Yonetim'`, `KullaniciAdi == 'admin'` | Auth.py shortcut'ini tekrarliyor |
| 3 | Standalone decorator (`@yetki_gerek` gibi lokal kopya) | Tek core yerine fragman |
| 4 | Action belirtmeden POST endpoint korumak | Yetki seviyesi bilinmez olur |
| 5 | Decorator olmadan `session.get('kullanici')` ile manuel check | Auth.py disinda kalir |

### 4.2 ✅ ZORUNLU

| # | Zorunlu | Ornek |
|---|---|---|
| 1 | Tek decorator | `@yetki_gerekli('modul.kod', 'can_xxx')` |
| 2 | Action belirtilecek | GET=can_view, POST upload=can_create, POST guncelle=can_update, POST sil=can_delete |
| 3 | Yetki kodu DB'de tanimli | `sistem_yetki` tablosunda kayit olmali |
| 4 | Yetki rolu atanmis | `sistem_rol_yetki` tablosunda satir olmali |
| 5 | Sidebar koruma | `{% if yetki('modul.kod') %}` (RolAd hardcoded YOK) |

---

## 5. ACTION MODELI

### 5.1 7 Standart Action

| Action | Kullanim | Ornek |
|---|---|---|
| `can_view` | Sayfa goruntule, liste oku, JSON GET | `/x/liste`, `/x/<id>` |
| `can_create` | Yeni kayit, dosya yukle, INSERT POST | `/x/olustur`, `/x/<id>/belge/yukle` |
| `can_update` | Mevcut kayit guncelle, alan degistir | `/x/<id>/guncelle`, `/x/<id>/durum` |
| `can_delete` | Silme, kayit kaldirma | `/x/<id>/sil`, `/belge/<id>/sil` |
| `can_approve` | Onay, durum gecisi (yonetimsel) | `/x/<id>/onayla`, `/x/<id>/reddet` |
| `can_report` | Rapor cikti, Excel export, KPI detay | `/x/rapor`, `/x/excel` |
| `can_manage` | Modul yonetimi, ayar, super-kullanici aksiyonlari | `/x/ayar`, `/x/yetki/duzenle` |

### 5.2 Action Atama Kurali

Yeni endpoint yazarken `HTTP method` + `is mantigi` → action eslesir:

```
GET sayfa/liste           → can_view
GET belge/dosya indir     → can_view
POST yeni kayit           → can_create
POST belge yukle          → can_create
POST var olan guncelle    → can_update
POST durum degistir       → can_update
POST sil                  → can_delete
POST onayla/reddet        → can_approve
GET rapor/excel/pdf       → can_report
POST ayar/yetki/sistem    → can_manage
```

### 5.3 Geriye Uyumluluk

- `kullanici_yetkileri()` zaten 7 action set'i uretiyor
- `yetki_gerekli(kod, action='can_view')` default ile mevcut tek-arg cagrilari bozulmaz
- `yetki_var` action fallback'li (`.goruntule` → can_view, `.duzenle` → can_update)

---

## 6. FAZ 2 GOREV SIRASI

Toplam **7 alt-faz**. Risk artisina gore siralandi. Her birinin tahmini, etkilenen dosya, test gereksinimi belli.

### F2.1 — planlama/routes.py helper standardizasyonu

| Madde | Detay |
|---|---|
| **Risk** | 🟢 Dusuk |
| **Sure** | 30 dk |
| **Dosya** | `app/modules/planlama/routes.py` |
| **Etkilenen endpoint** | 7 (`_yetki_var_mi()` cagrilari L539, 911, 1096, 1108, 1191, 1253, 1581) |
| **Yapilacak** | `def _yetki_var_mi()` sil, 7 cagriyi `@yetki_gerekli('planlama.X')` ile degistir |
| **Bagimlilik** | DB'de `planlama.karar_masasi`, `planlama.operasyon_raporu` zaten var; her endpoint icin uygun kod secilecek |
| **Onceki helper davranis** | Sadece `RolAd in ('Yonetim','Planlama') or kad=='admin'` → Mehmet (RolId=32) zaten geciyordu |
| **Apply sonrasi** | Mehmet'in tum planlama endpoint'leri panel uyumlu olur; baska rolu olan (orn. Halil tip='usta') gecemez (bu istenilen) |
| **Rollback** | Tek dosya yedek + 1 satir restore |
| **Test** | Mehmet × 7 endpoint, Halil regression, Admin regression |

### F2.2 — finans `_cof_yetkili` standardizasyonu

| Madde | Detay |
|---|---|
| **Risk** | 🟢 Dusuk |
| **Sure** | 20 dk |
| **Dosya** | `app/modules/finans/routes.py` |
| **Etkilenen endpoint** | 3+ (cin-ofis upload, onizleme, template) |
| **Yapilacak** | `_cof_yetkili()` helper'i sil, `@yetki_gerekli('finans.cin_ofis_import', action)` |
| **On-recon** | `_cof_yetkili()` icerigini incele (henuz tam okumadik) |
| **Bagimlilik** | DB'de `finans.cin_ofis_import` kodu zaten var |
| **Apply sonrasi** | Cin-ofis upload paneldeki yetkiye dayanir, manuel helper yok |
| **Rollback** | Tek dosya |
| **Test** | Muhasebe + bu modulu kullanan kullanici tespiti |

### F2.3 — Upload/Download/Read Action Modeli

| Madde | Detay |
|---|---|
| **Risk** | 🟡 Orta |
| **Sure** | 1-1.5 saat |
| **Dosya** | `grafik/routes.py` (54+ yer), `finans/routes.py`, `yonetim/routes.py` |
| **Etkilenen endpoint** | 5+ upload, 1+ sil, 1+ download |
| **Yapilacak** | Grafik lokal `yetki_gerek` helper'i alias yap VEYA tum cagrilari `@yetki_gerekli`'ya cevir + action ekle |
| **Onerilen yaklasim** | Yaklasim A (alias) — Grafik 54 satira dokunmadan tek satir alias. Sonra action gerekiyorsa adim adim eklenir. |
| **Alternatif** | Yaklasim B — 54 satiri tek tek action atayarak duzelt (uzun, riskli) |
| **Apply sonrasi** | POST upload → can_create kontrolu, GET liste → can_view, sil → can_delete |
| **Rollback** | Bir dosya tek-yedek; cross-file rollback gerekmez |
| **Test** | Samet × numune upload, Muhasebe × ithalat upload (regression), admin (regression) |

### F2.4 — yonetim @admin_gerekli standardizasyonu

| Madde | Detay |
|---|---|
| **Risk** | 🟡 Orta |
| **Sure** | 1 saat |
| **Dosya** | `app/modules/yonetim/routes.py` |
| **Etkilenen endpoint** | 16 (`@admin_gerekli` decorator'lari) |
| **Yapilacak** | `@admin_gerekli` → `@yetki_gerekli('yonetim.kullanici', 'can_manage')` veya benzeri |
| **On-recon** | Her endpoint hangi alt-modul (kullanici/rol/kur/log) — uygun yetki kodu secimi |
| **Bagimlilik** | DB'de `yonetim.kullanici, yonetim.rol, yonetim.kur, yonetim.log` zaten var |
| **Yan etki** | Admin shortcut (auth.py'deki `{'*'}`) zaten admin'i geciriyor — fonksiyonel degisim yok |
| **Apply sonrasi** | Yonetim ekranlari kullaniciya gore filtrelenir (admin disindaki Yonetim rolundekiler de yetkiye gore gorur) |
| **Rollback** | Tek dosya |
| **Test** | Admin (regression), Halil (Yonetim rol) — kullanici/rol/kur/log ekranlari |

### F2.5 — Sidebar RolAd Temizligi

| Madde | Detay |
|---|---|
| **Risk** | 🟢 Dusuk (gorsel/template degisikligi) |
| **Sure** | 30 dk |
| **Dosya** | `app/templates/base.html` + `setup_sidebar_*.py` script'leri (yedekler arsivlenir) |
| **Etkilenen satir** | 43 (`RolAd == 'Yonetim'` veya `KullaniciAdi == 'admin'`) |
| **Yapilacak** | Hardcoded `or g_user.RolAd == 'Yonetim'` kismini SIL — sidebar yalnizca `{% if yetki('xxx') %}` ile kosul yapacak |
| **Bagimlilik** | Auth.py SuperAdmin shortcut `{'*'}` set'i Yonetim'i her yetkiye geciriyor → davranis aynı kalır |
| **Yan etki** | YOK; sadece cift kontrol kalkar |
| **Rollback** | Tek dosya (base.html) — setup script'leri arsiv, dokunulmaz |
| **Test** | Halil (Yonetim rolu) sidebar tam gorur mu, Samet sadece grafik gorur mu |

### F2.6 — Orphan Permission Cleanup

| Madde | Detay |
|---|---|
| **Risk** | 🟡 Orta (DB migration) |
| **Sure** | 1-2 saat |
| **Dosya** | Yeni migration `app/migrations/004_orphan_yetki_cleanup.py` |
| **Etkilenen** | 40 orphan kod (`canli_saha`, `enjeksiyon.*`, `hedef.*`, `nakit.*`, `personel_giris`, `tasks`, `usta`, vb.) |
| **Karar** | Her orphan icin: (a) Route ekle (kullanim ihtiyaci varsa), (b) DB'den sil (kullanim yok), (c) Sakla (gelecekte kullanim) |
| **Strateji** | F2.1-F2.4 sonrasi cikan tabloya gore karar. Hicbir kodu silmeden once panele bakilir. |
| **Apply sonrasi** | DB tertibli, panelde "ataniyor ama hicbir sey acmiyor" kodlari kalmaz |
| **Rollback** | DB yedek (mock_data.db) tam restore |
| **Test** | Panel goruntusu, audit log temiz mi |

### F2.7 — Gorev/Idari/Personel Ayrimi Standardi

| Madde | Detay |
|---|---|
| **Risk** | ⚠️ Belirsiz (tanim eksik) |
| **Sure** | Belirsiz (once tanim oturumu, sonra patch) |
| **Tanim eksigi** | Adem'in soruda "Gorev modulu sadece kayitli idari kadro/ofis/usta/yonetim kullanicilarina cikmali" demis — `Tip` kullanim modeli net olmali |
| **On-tanim** | `Tip` enum: `sistem | personel | usta`. `is_akisi` tablosu var (3 kayit). `idari/ofis` Tip degeri yok. |
| **Olasi yaklasim** | Yeni `Tip` degerleri eklemek YERINE `sistem_rol`'de "Ofis/Idari" rolu olusturup yetkilendirmek |
| **Karar gerekli** | Adem ile tanim oturumu — bu altfaz simdi PATCH degil RECON |
| **Yapilacak** | Tip kullanim haritasini cikar, role-based tanima gec, gorev modulu icin yetki kodlari (`tasks.idari`, `tasks.usta` vs.) |

---

## 7. HER FAZ ICIN — Risk, Sure, Rollback, Test Matrisi, Etkilenen Dosyalar

### F2.1 — planlama helper

| Risk | Sure | Etkilenen Dosya | Yedek | Test Sayisi |
|---|---|---|---|---|
| 🟢 Dusuk | 30 dk | planlama/routes.py | 1 | 7 endpoint × 3 kullanici = 21 |

**Test matrisi:**

| Kullanici | Endpoint | Action | Beklenen |
|---|---|---|---|
| Mehmet (RolId=32) | `/planlama/karar-masasi` GET | can_view | ✅ Acilir |
| Mehmet | `/planlama/operasyon-raporu` GET | can_view | ✅ Acilir |
| Halil (RolId=1) | Tum planlama endpoint'leri | can_view | ✅ Acilir |
| Admin | Hepsi | can_view | ✅ Acilir |
| Samet (RolId=5) | Planlama endpoint'leri | yok | ❌ 403 (beklenen) |

**Rollback:**
```powershell
Copy-Item "_BACKUPS\YETKI_V2\planlama_routes_PRE_PATCH_<ts>.bak" `
          "app\modules\planlama\routes.py" -Force
schtasks /End /TN "\Solariz\Solariz_CPS_8080"
schtasks /Run /TN "\Solariz\Solariz_CPS_8080"
```

### F2.2 — finans _cof_yetkili

| Risk | Sure | Etkilenen Dosya | Yedek | Test Sayisi |
|---|---|---|---|---|
| 🟢 Dusuk | 20 dk | finans/routes.py | 1 | 3 endpoint × 2 kullanici |

**Test matrisi:**

| Kullanici | Endpoint | Action | Beklenen |
|---|---|---|---|
| Muhasebe (RolId=2) | `/finans/cin-ofis/upload` | can_create | DB'de yetki yoksa 403, varsa ✅ |
| Admin | Hepsi | – | ✅ Calisir |

### F2.3 — Upload Action Modeli

| Risk | Sure | Etkilenen Dosya | Yedek | Test Sayisi |
|---|---|---|---|---|
| 🟡 Orta | 1-1.5 saat | grafik/routes.py + finans + yonetim | 3 | 5 endpoint × 3 kullanici = 15 |

**Yaklasim A (alias):**
- `grafik/routes.py` L27-38 `def yetki_gerek` sil
- L8 altina `from modules.auth import yetki_gerekli as yetki_gerek` ekle
- 54 cagri OLDUGU GIBI kalir
- Lokal admin shortcut `_admin_mi` kullanan kismi sil (cunku auth.py'de var)

**Test matrisi:**

| Kullanici | Endpoint | Action | Beklenen |
|---|---|---|---|
| Samet | `/grafik/numune/<id>/belge/yukle` POST | can_create | ✅ (panel'de can_create=1) |
| Samet | `/grafik/tedarikci/<id>/belge/yukle` POST | can_create | ❌ 403 (panel'de can_create=0, sadece view) |
| Samet | `/grafik/numune` GET | can_view | ✅ Acilir |
| Admin | Hepsi | – | ✅ Hepsi calisir |

### F2.4 — yonetim @admin_gerekli

| Risk | Sure | Etkilenen Dosya | Yedek | Test Sayisi |
|---|---|---|---|---|
| 🟡 Orta | 1 saat | yonetim/routes.py | 1 | 16 endpoint × 2-3 kullanici |

**Test matrisi:**

| Kullanici | Endpoint | Beklenen |
|---|---|---|
| Admin | `/yonetim/kullanici`, `/rol`, `/kur`, `/log` | ✅ Acilir |
| Halil (RolAd=Yonetim) | Hepsi | ✅ Acilir (SuperAdmin shortcut) |
| Mehmet | Yonetim ekranlari | ❌ 403 |
| Samet | Yonetim ekranlari | ❌ 403 |

### F2.5 — Sidebar Temizligi

| Risk | Sure | Etkilenen Dosya | Yedek | Test Sayisi |
|---|---|---|---|---|
| 🟢 Dusuk | 30 dk | templates/base.html | 1 | Sidebar tam goruntuleme |

**Test:**
- Admin sidebar her seyi gorur
- Halil (Yonetim) sidebar her seyi gorur
- Mehmet (Planlama) sadece planlama+karar masasi+proses takip
- Samet (Grafik) sadece grafik alt menusu
- Hicbir cift kontrol kalmaz

### F2.6 — Orphan Cleanup

| Risk | Sure | Etkilenen | Yedek | Test |
|---|---|---|---|---|
| 🟡 Orta | 1-2 saat | mock_data.db | 1 (DB yedek) | Panel goruntusu, audit |

### F2.7 — Tip Standardi

| Risk | Sure | Etkilenen | Yedek | Test |
|---|---|---|---|---|
| ⚠️ Belirsiz | Tanim sonrasi | DB + auth.py + birden cok modul | 2+ | Kapsam belirsiz |

---

## 8. DISIPLIN

Her alt-faz **kati pipeline** ile yapilir:

```
1. RECON (sadece okuma, sifir risk)
   ↓
2. MOCKUP (degisecek satirlar, etki, risk, geri donulebilirlik)
   ↓
3. ONAY (Adem mockup'i okuyup "MOCKUP ONAY" der)
   ↓
4. SCRIPT YAZIM (sandbox'ta + Linux simulasyon)
   ↓
5. DRY-RUN (sandbox + Adem'in sunucusunda)
   ↓
6. ONAY (Adem dry-run cikti uyumlu mu kontrol eder, "APPLY" der)
   ↓
7. APPLY (yedek + atomik yaz + hash dogrula + auto-rollback)
   ↓
8. CPS RESTART
   ↓
9. TEST (test matrisi sirasi)
   ↓
10. RAPOR + Stable Snapshot
```

### 8.1 Yedek Konvansiyonu

```
D:\Firma_Ozel\adem\_BACKUPS\YETKI_V2\
  <dosya>_PRE_F2.X_<ts>.bak
```

### 8.2 Idempotency Garantisi

- Patch script idempotent: zaten dogru ise skip, yanlissa duzelt, miss ise dur
- Cross-file rollback: 3 dosya icin TEK transaction
- Hash dogrulama: yazimdan sonra mutlaka

### 8.3 Stable Snapshot Konvansiyonu

Her alt-faz kapaninca:
```
D:\Firma_Ozel\adem\yedeklemeler\
  STABLE_YETKI_V2_F2.X_OK_<ts>
```

Tam YETKI_V2 sprint kapaninca:
```
STABLE_YETKI_V2_FULL_OK_<ts>
```

---

## 9. TEST MATRISI — Kullanici × URL × Action × Beklenen

FAZ 2 boyunca kullanilacak baz test matrisi:

### 9.1 Test Kullanicilari

| Kullanici | RolId | Tip | Kontrol amaci |
|---|---|---|---|
| `admin` | 1 | NULL | SuperAdmin shortcut (her zaman gecer) |
| `halil` | 1 | usta | SuperAdmin + Tip='usta' hibrit (bypass) |
| `hasan` | 1 | NULL | Yonetim rol, ana kullanici |
| `mehmet` | 32 | NULL | Planlama rolu — F2.1 odak |
| `muhasebe` | 2 | sistem | Muhasebe rolu — F2.2 + F2.3 odak |
| `samet` | 5 | NULL | Grafik rolu — F2.3 odak |
| `ferhat` | 35 | usta | Enjeksiyon rolu — regression |
| `ibrahim` | 34 | sistem | Idari/Ofis — F2.7 belirleyici |
| `nesrisamet` | 33 | sistem | Kalite |

### 9.2 Test URL Listesi (modul bazli)

| Modul | URL Ornekleri |
|---|---|
| Planlama | `/planlama/karar-masasi`, `/planlama/operasyon-raporu`, `/planlama/proses-takip` |
| Ithalat | `/ithalat/parti/liste`, `/ithalat/maliyet/...`, `/ithalat/odeme/...` |
| Finans | `/finans/anlasma`, `/finans/cin-ofis/upload`, `/finans/odeme` |
| Grafik | `/grafik/numune`, `/grafik/urun`, `/grafik/tedarikci`, `/grafik/numune/<id>/belge/yukle` |
| Yonetim | `/yonetim/kullanici`, `/yonetim/rol`, `/yonetim/kur`, `/yonetim/log` |
| Hedef | `/hedef/`, `/hedef/sablon`, `/hedef/sapma` |
| Tasks | `/tasks` |
| Enjeksiyon | `/enjeksiyon/` |
| Personel | `/personel-giris/` |
| Uretim | `/uretim/` |

### 9.3 Action Senaryosu

Her endpoint icin:
```
GET sayfa  → can_view bekleyecek
POST yeni  → can_create bekleyecek
POST guncelle → can_update bekleyecek
POST sil   → can_delete bekleyecek
GET rapor  → can_report bekleyecek
```

---

## 10. KAPATMA HEDEFI

### 10.1 KPI'lar (FAZ 2 sonu kontrol listesi)

| KPI | Onceki (FAZ 1 sonu) | Hedef (FAZ 2 sonu) |
|---|---|---|
| Standart decorator kullanim orani | %15 (4/26+) | %100 |
| Action belirten decorator orani | %50 | %100 (her POST/GET tipi) |
| Ozel helper sayisi | 4 (`_yetki_var_mi×2, _cof_yetkili, _admin_mi`) | 0 |
| Hardcoded RolAd kontrolu | 43 satir | 0 |
| Runtime'da kullanilan DB yetki kodu | 4/44 (%9) | 35+/44 (%80+) |
| Orphan kod | 40 | 0-5 |
| Sidebar standart koruma | %30 | %100 |

### 10.2 Mimari Hedef

```
TEK CORE      = auth.py (yetki_gerekli + yetki_var + kullanici_yetkileri)
TEK DECORATOR = @yetki_gerekli(kod, action)
TEK ACTION    = 7 standart (view/create/update/delete/approve/report/manage)
TEK ADMIN     = auth.py SuperAdmin shortcut {'*'}
TEK SIDEBAR   = {% if yetki(kod) %}
TEK PANEL     = Yonetim/Rol/Yetki ekrani
```

### 10.3 Yeni Modul Yazim Klavuzu (FAZ 2 sonrasi)

Yeni modul eklerken:

1. **DB:** `sistem_yetki` tablosuna kod ekle (`modul.alt_modul`)
2. **DB:** `sistem_rol_yetki` tablosuna her rol icin 7 action satiri (panel uzerinden veya migration)
3. **Route:** Her endpoint `@yetki_gerekli('modul.alt_modul', 'can_xxx')` ile koru
4. **Sidebar:** `{% if yetki('modul.alt_modul') %}` ile koruyu
5. **JS API:** Frontend'de yetki kontrolu yapma (server tarafi yeterli)
6. **Audit:** Her POST/PUT/DELETE icin `audit.log(...)` cagrisi

❌ Yasak: yerel helper, hardcoded RolAd, manuel session check
✅ Zorunlu: tek decorator + 7 action + DB'de tanimli kod

---

## 11. ROLLBACK YOLLARI

### 11.1 Tek alt-faz rollback

```powershell
$BAK = "D:\Firma_Ozel\adem\_BACKUPS\YETKI_V2"
$TS  = "<gercek_timestamp>"

# F2.X icin dosya rollback
Copy-Item "$BAK\<dosya>_PRE_F2.X_$TS.bak" "<canli_yol>" -Force

# CPS restart
schtasks /End /TN "\Solariz\Solariz_CPS_8080"
Start-Sleep 3
schtasks /Run /TN "\Solariz\Solariz_CPS_8080"
```

### 11.2 Tum FAZ 2 rollback (felaket senaryosu)

```powershell
# YETKI_V2 FAZ 1 + FAZ 2 oncesi noktasina don
$BAK = "D:\Firma_Ozel\adem\_BACKUPS\YETKI_V2"

# FAZ 1'in PRE-PATCH yedekleri (20.05.2026 16:52:09 ONCESI)
Copy-Item "$BAK\auth_PRE_PATCH_20260520_165209.bak" `
          "D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\modules\auth.py" -Force
Copy-Item "$BAK\routes_PRE_PATCH_20260520_165209.bak" `
          "D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\modules\ithalat\routes.py" -Force
Copy-Item "$BAK\proses_takip_PRE_PATCH_20260520_165209.bak" `
          "D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\modules\planlama\proses_takip.py" -Force

# YETKI_V2 mojibake fix oncesi noktasina don (15:50:10 ONCESI)
Copy-Item "$BAK\auth_py_PRE_PATCH_20260520_155010.bak" `
          "D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\modules\auth.py" -Force

# CPS restart
schtasks /End /TN "\Solariz\Solariz_CPS_8080"
schtasks /Run /TN "\Solariz\Solariz_CPS_8080"
```

### 11.3 Felaket stable backup

```
D:\Firma_Ozel\adem\_BACKUPS\YETKI_V2\BACKUP_YETKI_V2_CRITICAL_20260520_151815\
  ├── auth.py + tum cevre
  ├── mock_data.db
  ├── routes.py 60+ history backup
  └── 730 dosya, SHA1 dogrulu
```

---

## 12. ACIL OLMAYAN AMA HATIRLANMASI GEREKEN

### 12.1 Samet/Numune Dosya Bug (ayri tani)

FAZ 2'de cozulmeyecek. Ayri sprint:
- F12 Network testi (Adem yapacak)
- Storage yolu kontrolu
- JS endpoint cagri kontrolu

Bu **tekil bug** olarak ele alinir, runtime standardizasyonundan bagimsiz.

### 12.2 Devir Dosyasinin Acik Isleri

CPS_DURUM_DEVIR_20260518.md'de yer alan:
- R004 PERSONEL_BUGUN_0 FLAG kararı
- DURGUN_EMIR_7G eşik kararı
- D6.1-E Scheduler kararı
- UI Türkçeleştirme
- Standart süre 9 eksik proses
- D7.1 Darboğaz Tahmini (R002)
- D7.2 Enjeksiyon Canlı Makine Ekranı
- D7.3 Kritik Sipariş Erken Uyarı (R003)
- Finans modülü entegrasyonu (D8)

Bunlar **YETKI_V2 disinda**, paralel sprintler. FAZ 2 bittikten sonra veya bir alt-fazin arasinda yapilabilir.

### 12.3 Hash Zinciri Kayit

Her alt-faz kapaninca:
```markdown
F2.1 sonrasi:
  planlama/routes.py: <ESKI> → <YENI>

F2.2 sonrasi:
  finans/routes.py: <ESKI> → <YENI>
...
```

---

## 13. YENI CLAUDE OTURUMU ICIN ACIL KONTROL LISTESI

Yeni oturumda Claude'un yapmasi gereken:

```powershell
Set-Location D:\Firma_Ozel\adem\Solariz_CPS_SERVER

# 1. FAZ 1 hashleri (apply edildi mi kontrol)
Get-FileHash "app\modules\auth.py"                  # DA44F2CC6FE3
Get-FileHash "app\modules\ithalat\routes.py"        # 20AF0F392954
Get-FileHash "app\modules\planlama\proses_takip.py" # 27D26A1EF80F

# 2. CPS canli mi
Invoke-WebRequest "http://127.0.0.1:8080/personel-giris/health"  # 200 olmali

# 3. DB durum (test kullanicilari, roller, yetkiler)
& "C:\Users\Administrator\AppData\Local\Programs\Python\Python315\python.exe" -c "
import sqlite3
con = sqlite3.connect(r'D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\mock_data.db')
print('Roller     :', con.execute('SELECT COUNT(*) FROM sistem_rol').fetchone()[0])
print('Kullanicilar:', con.execute('SELECT COUNT(*) FROM sistem_kullanici').fetchone()[0])
print('Yetki kodu :', con.execute('SELECT COUNT(*) FROM sistem_yetki').fetchone()[0])
print('Rol-Yetki  :', con.execute('SELECT COUNT(*) FROM sistem_rol_yetki').fetchone()[0])
"

# 4. Plan dosyasi: D:\Firma_Ozel\adem\Solariz_CPS_SERVER\docs\YETKI_V2_FAZ2_PLANI.md
# 5. F2.X hangi alt-faz acik / kapali ogren
```

---

## 14. SONUC

YETKI_V2 FAZ 2:

- **Tek core sistem** kurulacak (yeni decorator/helper yasak)
- **7 alt-faz** (F2.1 → F2.7) kademeli uygulanacak
- **Her alt-faz** kendi recon + mockup + dry-run + 3 onay + apply disiplini
- **Her alt-faz** rollback'li, test matrisli
- **FAZ 2 sonu** %100 panel ↔ runtime hizalama hedefi

**Ilk adim:** F2.1 — `planlama/routes.py` `_yetki_var_mi` standardizasyonu.

**Onceki Claude oturumunun hash imzasi:**
- auth.py: `DA44F2CC6FE3` (FAZ 1 sonu)
- ithalat/routes.py: `20AF0F392954`
- planlama/proses_takip.py: `27D26A1EF80F`

---

*Yazim sonu: 2026-05-20. Tahmini okuma suresi: 15 dk.*
*Bir sonraki adim icin Adem'in "F2.1 BASLA" komutu beklenecek.*
