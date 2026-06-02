

===== docs\YETKI_V2_FAZ2_PLANI.md =====

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


===== docs\HARDCODE_YETKI_RECON.md =====

# HARDCODE_YETKI_RECON

Belge tipi: Teknik borc envanteri + migration plani
Tarih: 2026-05-15 (gece)
Snapshot referansi: STABLE_OP_RAPOR_V2_GECMIS_DONE_20260515_161612
Durum: RECON tamamlandi, patch yok
Veri kaynagi: PowerShell recon 15.05.2026 18:30

---

## 0. Yonetim Ozeti

Mevcut sistemde hardcoded yetki kontrolleri DAGILMIS durumda, ama beklenenden
DAHA AZ yogunlukta. Onceki tahmin "150+ yer" hatali idi.

GERCEK durum:

- base.html'de 20 hardcoded kontrol (RolAd + KullaniciAdi)
- Diger template'lerde ~10 kontrol (panel, index, siparis_detay)
- Toplam GERCEK refactor hedefi: ~30 satir
- setup_sidebar_*.py dosyalari sidebar generator script'leri (runtime degil)
- permissions.py'de yetki helper mantigi mevcut

SURPRIZ KESIF:

- @yetki_gerek decorator MEVCUTSU
- grafik modulu 60/55 (92% korumali)
- ithalat modulu 27/26 (96% korumali)
- Diger 11 modul sifir kullanim
- Yani decorator yazimi YOK, sadece yaygiNlastirma var

Bu durumda V2 migration:
- decorator yazma adimi atlanir
- mevcut grafik/ithalat decorator pattern'i kopyalanir
- 11 modul kademeli olarak decorator ekleme alir
- 30 hardcoded satir paralel olarak yetki() ile degistirilir

---

## 1. Tarama Sonuclari (Recon Veri)

### 1.1 RolAd == Kontrolleri Dosya Bazli

| Dosya | Sayi | Risk | Yorum |
|-------|------|------|-------|
| base.html | 13 | YUKSEK | Ana sidebar, herkes goruyor |
| setup_sidebar_kompakt.py | 11 | DUSUK | Sidebar generator script (runtime degil) |
| setup_sidebar_lucide_ikonlar.py | 11 | DUSUK | Sidebar generator (runtime degil) |
| setup_sidebar_yeniden.py | 11 | DUSUK | Sidebar generator (runtime degil) |
| panel.html | 5 | ORTA | Yonetim paneli |
| index.html | 3 | ORTA | Anasayfa |
| permissions.py | 2 | DUSUK | Yetki helper'i icindeki yorum/dock |
| apply_enjeksiyon_sidebar.py | 1 | DUSUK | Patch script |
| siparis_detay.html | 1 | ORTA | Grafik siparis detay |
| base_planlama_sidebar.py | 1 | DUSUK | Patch script |

Toplam: 59 satir
Gercek refactor hedefi: 22 satir (base.html + panel + index + siparis_detay)
Setup script'ler runtime'da calismaz, gozardi edilebilir.

### 1.2 KullaniciAdi == Bypass Kontrolleri

| Dosya | Sayi | Detay |
|-------|------|-------|
| base.html | 7 | Sidebar bypass'lari (admin, adem, altan, hasan) |
| setup_sidebar_*.py | 15 | Sidebar generator script'leri |
| index.html | 2 | Anasayfa bypass |
| permissions.py | 2 | Yorum/dock satirlari |
| siparis_detay.html | 1 | Tek if |
| base_planlama_sidebar.py | 1 | Patch script |

Toplam: 28 satir
Gercek refactor: ~10 satir (base.html + index + siparis_detay)

KULLANILAN BYPASS KULLANICI ADLARI:

- admin (cogu yerde)
- adem (base.html sat 503: ithalat.parti icin)
- altan (base.html sat 503: ithalat.parti icin)
- hasan (yer yer)

V2'de: Bu kullanicilar SuperAdmin rolune cekilir, bypass kaldirilir.

### 1.3 Admin Helper Fonksiyonlari

| Dosya | Sayi | Yorum |
|-------|------|-------|
| routes.py (genel) | 13 | Cesitli modullerde _admin_mi / is_admin cagrisi |
| apply_hedef_usta.py | 6 | Patch script, runtime degil |
| permissions.py | 6 | Helper modulu, ana referans |
| apply_step2_patch.py | 4 | Patch script |
| service.py | 4 | Servis katmani |

Toplam: 33 yer

permissions.py icinde yetki sistemi merkezi - bu V2 sonrasi da kalir, sadece
icine yeni 7-boyutlu mantik eklenir.

### 1.4 base.html Detayli Kategorize

base.html toplam 92 adet {% if %} blogu icerir:

| Tip | Sayi | Anlam |
|-----|------|-------|
| RolAd kontrolu | 15 | Refactor hedefi |
| KullaniciAdi kontrolu | 7 | Bypass kaldirma |
| yetki() helper | 11 | ZATEN YENI SISTEM (korunacak) |
| Tip kontrolu | 0 | Sorun yok |
| Diger | 59 | Cesitli iflere |

Cikarim: base.html'de zaten 11 yer yetki() kullaniyor. V2 standartina yakin
parca var. Sadece 22 satirin (15 + 7) refactor'u gerekli.

---

## 2. Detayli Satir Listesi - base.html

Refactor gerekli olan SPESIFIK satirlar (recon ciktisindan):

| Satir | Mevcut Kontrol | V2 Karsiligi |
|-------|----------------|--------------|
| 257 | g_user.RolAd != 'Enjeksiyon' | NOT yetki('enjeksiyon', 'can_view') |
| 429 | yetki('finans') or g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' | yetki('finans') |
| 503 | yetki('ithalat.parti') or admin/adem/altan bypass | yetki('ithalat.parti') |
| 529 | yetki('grafik.cin_siparis') or g_user.RolAd == 'Yönetim' | yetki('grafik.cin_siparis') |
| 550 | yetki('grafik.maliyet') or g_user.RolAd == 'Yönetim' | yetki('grafik.maliyet') |
| 580 | yetki('finans') or yetki('grafik.tedarikci') or RolAd/Kull | yetki('finans') or yetki('grafik.tedarikci') |
| 607 | yetki('finans') or g_user.RolAd == 'Yönetim' or KullaniciAdi == 'admin' | yetki('finans') |
| 643 | yetki('grafik.tedarikci') or g_user.RolAd == 'Yönetim' | yetki('grafik.tedarikci') |
| 673 | g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' | yetki('yonetim') |
| 767 | g_user.RolAd == 'Planlama' | yetki('planlama') |
| 784 | g_user.RolAd == 'Enjeksiyon' | yetki('enjeksiyon') |
| 803 | g_user.RolAd in ('Yönetim', 'Planlama') or KullaniciAdi == 'admin' | yetki('planlama') OR yetki('yonetim') |
| 876 | yetki('grafik.urun') or yetki('grafik.numune') or g_user.RolAd == 'Yönetim' | yetki('grafik.urun') or yetki('grafik.numune') |
| 918 | yetki('grafik.urun') or g_user.RolAd == 'Yönetim' | yetki('grafik.urun') |
| 939 | yetki('grafik.numune') or g_user.RolAd == 'Yönetim' | yetki('grafik.numune') |
| 969 | g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' | yetki('yonetim') |

Cikarim: 16 satir refactor. Cogu zaten yetki() ile baslyor, sadece OR bypass'lari
silinecek. Tam temizlik isi 1-2 saat alir.

ONEMLI: SuperAdmin shortcut yetki() fonksiyonu icine girer. Yani:
"yetki('finans')" cagirildiginda ve kullanici SuperAdmin ise zaten True doner.
Bu sayede "or RolAd == 'Yönetim'" eklemeye gerek kalmaz.

---

## 3. Modul Bazinda Migration Onceligi

Decorator durumuna gore migration sirasi:

| Sira | Modul | Endpoint | Korumasiz | Oncelik Sebebi |
|------|-------|----------|-----------|----------------|
| 1 | yonetim | 22 | 22 | Admin paneli, kritik |
| 2 | finans | 32 | 32 | Para konusu |
| 3 | hedef | 25 | 25 | Uretim onaylari |
| 4 | enjeksiyon | 18 | 18 | Saha aksiyon |
| 5 | personel_giris | 11 | 11 | Personel ekleme |
| 6 | tasks | 16 | 16 | Gorev yonetimi |
| 7 | planlama | 9 | 9 | Karar masasi |
| 8 | uretim_giris | 7 | 7 | Eski modul |
| 9 | uretim_yonetim | 6 | 6 | Eski modul |
| 10 | usta | 5 | 5 | Sade |
| 11 | canli_saha | 2 | 2 | Read-only viewer |

Zaten korumali (migration gerekmez):
- grafik (55/60, 92% korumali, kalan 5 incelenecek)
- ithalat (decorator YOK - duzeltildi 16.05.2026)

Migration sirasi onerisi:

ADIM 1: yonetim - en kritik, az endpoint
  Cunku: yonetim/rol, yonetim/kullanici bypass edilirse sistem ele gecirilir
  Sure: 1 gun

ADIM 2: finans - para konusu
  Cunku: anlasma, mahsup, sevkiyat para hareketleri
  Sure: 1 gun

ADIM 3: hedef - uretim
  Cunku: hedef.onayla yetkisiz herkes onaylayabilir
  Sure: 1 gun

ADIM 4: personel_giris - acik kapi
  Cunku: kayit endpoint'i tamamen acik, sahte uretim girilebilir
  Sure: 0.5 gun

ADIM 5: enjeksiyon - saha
  Cunku: ariza-start, setup-start gibi durumlar
  Sure: 0.5 gun

ADIM 6-11: kalan modulleri kademeli
  Sure: 2-3 gun

TOPLAM: 6-7 is gunu icin tam decorator migration.

---

## 4. setup_sidebar_*.py Dosyalari (Ozel Konu)

3 dosya: setup_sidebar_kompakt.py, setup_sidebar_lucide_ikonlar.py,
setup_sidebar_yeniden.py

Bunlarin her birinde ~11 RolAd ve ~5 KullaniciAdi var. Ama:

- Bunlar SIDEBAR GENERATOR SCRIPT'LERI (kod uretici)
- Runtime'da calismazlar
- Calistirildiklarinda base.html'i overwrite ederler
- V2'de bu generator'larin kendileri yeniden yazilmali

Strateji:

Onceligi: V2 base.html yazildiktan sonra bunlari archive klasorune tasi.
Veya: V2 module_registry'den otomatik sidebar uretecek tek yeni script:
  setup_sidebar_v2_from_registry.py

---

## 5. permissions.py Mevcut Durumu

modules/auth.py satir 56'da yetki_var fonksiyonu MEVCUT.

Yapisi (genel):

- yetki_var(user, kod) imzasi
- sistem_rol_yetki tablosundan SELECT
- Boolean doner

V2'de yapilacak guncelleme:

- Imza: yetki_var(user, kod, action='can_view')
- Action parametresi eklenir
- 7 boyut destegi (can_view, can_create, ...)
- user_permission_override kontrolu eklenir
- SuperAdmin shortcut on basta
- Effective permission hesabi (PERMISSION_MATRIX_PLAN.md Bolum 5)

Bu fonksiyon V2'de KULLANILMAYA DEVAM EDER. Yeniden yazilmaz, sadece genisletilir.

Yan ekleme:
- yetki(kod, action) jinja helper
- yetki_gerek(kod, action) decorator
- modul_listesi(user) sidebar render icin

---

## 6. service.py ve apply_*.py Dosyalari

| Dosya | Sayi | Mahiyet |
|-------|------|---------|
| service.py | 4 admin helper | Servis katmani, V2 ile uyumlu |
| apply_hedef_usta.py | 6 admin helper | PATCH SCRIPT, runtime degil |
| apply_step2_patch.py | 4 admin helper | PATCH SCRIPT, runtime degil |

Patch script'leri ZATEN bir kez calisip islerini bitirdi. Bunlara V2 migration
gerek yok. Archive klasorune tasinabilir.

service.py - henuz hangi servis oldugunu bilmiyoruz. Yarin recon ile incelemeli.

---

## 7. Migration Adimlari (Hardcoded Temizleme)

ADIM H1: Snapshot
- STABLE_HARDCODE_CLEANUP_PRE_<ts>

ADIM H2: setup_sidebar_*.py archive
- Eski generator script'leri move to /scripts/_archive/
- Bunlar runtime'da calismadigi icin sistem etkilenmez
- Kod kalir, kullanilmaz

ADIM H3: base.html refactor (en kritik)
- 16 satirlik RolAd/KullaniciAdi yapilarini yetki() ile degistir
- Her satir markel'lanir, geri alinabilir
- 1-2 saat surer
- Test: sidebar tum kullanicilarda dogru gozukmeli

ADIM H4: panel.html, index.html, siparis_detay.html
- Toplam ~10 satir
- 1 saat

ADIM H5: Module migration (kademeli)
- yonetim -> finans -> hedef -> personel_giris -> ... (Bolum 3)
- Her modul: snapshot + decorator ekle + test
- Toplam 6-7 is gunu

ADIM H6: KullaniciAdi bypass'lar kaldirilir
- adem, altan SuperAdmin rolune cekilir
- admin zaten Yonetim rolunde
- Code'dan KullaniciAdi == 'X' temizlenir

ADIM H7: Final test
- 14 kullanici icin sidebar dogru mu?
- 240 endpoint icin yetki kontrolu dogru mu?
- Audit log calisiyor mu?

ADIM H8: Snapshot
- STABLE_HARDCODE_CLEANUP_DONE_<ts>

---

## 8. Continuation - Yarin Nereden Devam

Bu doku RECON tamamlandi. Patch yok.

Yarin Ferhat saha testi bittikten sonra:
1. Bu doku tekrar okunur
2. PERSONEL_IK_OMURGA_PLAN.md icin recon yapilir (henuz yok)
3. Hepsi tamam ise patch baslar

Patch onceliği:
- ONCE: module_registry tablosu (yeni)
- SONRA: sistem_rol_yetki 7 boyut (ALTER TABLE)
- SONRA: user_permission_override (yeni)
- SONRA: yetki_gerek decorator yayginlastirma
- SONRA: base.html hardcoded temizleme
- SONRA: KullaniciAdi bypass temizleme

Yarinki tek sart:
- Mevcut grafik ve ithalat modulu calismaya devam etmeli
- (zaten korumalilar, ama testte dokunulmamali)

---

## 9. Diger Belgelerle Iliski

| Belge | Konu |
|-------|------|
| YETKI_SISTEMI_V2_ANALIZ.md | 6 tablolu envanter, 11 adimli migration |
| MODULE_REGISTRY_PLAN.md | Modul kayit standardi |
| PERMISSION_MATRIX_PLAN.md | 7 boyutlu yetki + override |
| HARDCODE_YETKI_RECON.md | BU DOKU - teknik borc haritasi |
| PERSONEL_IK_OMURGA_PLAN.md | (recon bekliyor) |

---

## 9.5 Duzeltme Notu (16.05.2026)

Onceki versiyonda "grafik 60/55 (92%) ve ithalat 27/26 (96%) korumali" denmisti.
Gercek recon (16.05.2026 sabah) sonucu:

- grafik modulu kendi icinde lokal bir `@yetki_gerek` decorator tanimlamis (routes.py satir 27)
- 55 endpoint bu lokal decorator ile korunmus
- ithalat modulunde `@yetki_gerek` HIC YOK, 0 endpoint korumali

Bu yuzden V2 migration sirasinda:
- grafik'in lokal decorator'unu auth.py'ye tasimak gerekecek (genellestirme)
- ithalat sifirdan korumaya alinacak
- Diger 11 modul de yine sifirdan korumaya alinacak

---

## 10. Belge Surumu

| Surum | Tarih | Aciklama |
|-------|-------|----------|
| v1 | 2026-05-15 | Recon tamamlandi (patch yok) |

Recon sonucu yeni satir bulunursa v2 olarak guncellenir.


===== docs\YETKI_SISTEMI_V2_ANALIZ.md =====

# YETKI SISTEMI V2 - ANALIZ RAPORU

Tarih: 2026-05-15 (gece analizi)
Hazirlayan: Recon A + B + C cikti analizi
Snapshot referansi: STABLE_OP_RAPOR_V2_GECMIS_DONE_20260515_161612
Durum: ANALIZ - patch YOK

---

## 0. Yonetim Ozeti

Iyi haber: CPS'te yetki altyapisi ZATEN VAR. 8 yetki tablosu, 30 yetki
kodu, 11 rol, 61 rol-yetki bagi mevcut. Sifirdan kurmuyoruz.

Kotu haber: Sistem sadece 4 modulu kapsiyor (finans, grafik, yonetim,
ithalat). Geriye kalan 10 modul (enjeksiyon, planlama, hedef, tasks,
personel_giris, uretim_giris, uretim_yonetim, usta, canli_saha) icin
hicbir yetki kodu yok.

Kritik bulgu: 240 endpoint'in 122'si POST (mutasyon). Bunlardan sadece
planlama modulu (8 endpoint) yetki kontrolu yapiyor. Geriye kalan 114
POST endpoint'i yetkisiz erisilebilir.

Yarinki Ferhat saha testi: Ferhat 'Enjeksiyon' rolunde, ama Enjeksiyon
rolunun sistem_rol_yetki'de hicbir bagi yok. Bu nedenle yarinki test
yetkisiz veya hardcoded fallback'lerle yurutulecek.

Onerilen: Mevcut sistemin uzerine yetki kodlari eklenecek + 2 boyut
(Gorebilir, Duzenleyebilir) 7 boyuta genisletilecek (Adem'in istegi).
Bu MIGRATION ile yapilir, mevcut bag'lar bozulmaz.

---

## TABLO 1 - Modul / Sayfa Envanteri

| # | Modul | URL Prefix | HTML | Routes KB | Endpoint Sayisi | Yetki Var? | Risk |
|---|-------|------------|------|-----------|-----------------|------------|------|
| 1 | canli_saha | /canli-saha | 1 | 5.6 | 2 | YOK | DUSUK (read-only) |
| 2 | common | - | - | - | - | N/A | - |
| 3 | enjeksiyon | /enjeksiyon | 2 | 51.8 | 18 | YOK | YUKSEK |
| 4 | finans | /finans | 13 | 30.7 | 32 | KISMI | YUKSEK (para) |
| 5 | grafik | /grafik | 17 | 41.8 | 60 | KISMI | YUKSEK |
| 6 | hedef | /hedef | 3 | 91.3 | 25 | YOK | YUKSEK |
| 7 | ithalat | /ithalat | ? | 51.2 | 27 | KISMI | YUKSEK (para) |
| 8 | personel_giris | /personel-giris | 1 | 17.8 | 11 | YOK | KRITIK |
| 9 | planlama | /planlama | 3 | 55.5 | 9 | VAR | ORTA |
| 10 | tasks | /tasks | 1 | 20.4 | 16 | YOK | ORTA |
| 11 | uretim_giris | (yok) | 1 | 15 | 7 | YOK | YUKSEK |
| 12 | uretim_yonetim | (yok) | 2 | 8.6 | 6 | YOK | YUKSEK |
| 13 | usta | /usta | 1 | 3.6 | 5 | YOK | ORTA |
| 14 | yonetim | /yonetim | 7 | 19 | 22 | KISMI | KRITIK (admin) |

TOPLAM: 14 blueprint + 55 HTML sayfa + 240 endpoint

---

## TABLO 2 - Endpoint Envanteri (Kritik POST'lar)

240 endpoint'in dagilimi:

| Method | Sayi | Anlami |
|--------|------|--------|
| GET | 112 | Goruntuleme (zarar verme riski dusuk) |
| POST | 122 | Veri olusturma/degistirme |
| PUT | 2 | Tam guncelleme |
| PATCH | 4 | Kismi guncelleme |

EN RISKLI 10 POST ENDPOINT (yetki yok, kritik aksiyon):

| # | Endpoint | Modul | Risk Sebebi |
|---|----------|-------|-------------|
| 1 | POST /yonetim/kullanici/yeni | yonetim | Kim isterse kullanici olusturabilir |
| 2 | POST /yonetim/kullanici/<id>/sifre-sifirla | yonetim | Sifre sifirlama korumasiz |
| 3 | POST /yonetim/rol/<id>/kaydet | yonetim | Rol yetkileri degistirilebilir |
| 4 | POST /personel-giris/kaydet | personel_giris | Kayit korumasiz |
| 5 | POST /finans/anlasma/yeni | finans | Anlasma para kaydi |
| 6 | POST /finans/anlasma/<id>/duzenle | finans | Anlasma duzenleme |
| 7 | POST /hedef/onayla | hedef | Uretim onayi |
| 8 | POST /hedef/reddet | hedef | Uretim reddi |
| 9 | POST /enjeksiyon/api/istasyon/<id>/ariza-start | enjeksiyon | Saha aksiyon |
| 10 | POST /grafik/siparis/<id>/onayla | grafik | Siparis onayi |

Modul bazli yetki kontrolu (Recon B6):

| Modul | login_req | session check | yetki cagrisi | abort 403 |
|-------|-----------|---------------|---------------|-----------|
| planlama | 0 | 2 | 8 | 5 | < TEK SAGLAM MODUL
| ithalat | 0 | 0 | 0 | 0 | < HIC KORUMA YOK
| personel_giris | 0 | 0 | 0 | 0 | < HIC KORUMA YOK
| canli_saha | 0 | 1 | 0 | 0 | < salt-okunur |
| enjeksiyon | 0 | 10 | 0 | 1 | manuel session check |
| finans | 0 | 12 | 0 | 11 | manuel + abort |
| grafik | 0 | 7 | 0 | 6 | manuel + abort |
| hedef | 0 | 16 | 0 | 3 | manuel + abort |
| yonetim | 0 | 7 | 0 | 6 | manuel + abort |
| tasks | 0 | 2 | 0 | 2 | zayif |
| usta | 0 | 2 | 0 | 1 | zayif |

Sonuc: TUM modullerde @login_required decorator YOK. Yetki kontrolu
manuel ve dagisik. Sadece planlama modulu yeni yetki() fonksiyonunu
aktif kullaniyor.

---

## TABLO 3 - Kullanici / Rol Envanteri

14 aktif kullanici:

| Id | Kullanici | Ad Soyad | Rol | Tip | Yetki Sayisi |
|----|-----------|----------|-----|-----|---------------|
| 1 | admin | Sistem Yoneticisi | Yonetim | - | 28 (SuperAdmin) |
| 2 | halil | Halil | Yonetim | usta | 28 (Yonetim) |
| 3 | hasan | Hasan | Yonetim | - | 28 |
| 4 | samet | Samet (Grafik) | Grafik | - | 7 |
| 5 | cin.ofis | Cin Ofisi | Cin Ofis | - | 4 |
| 6 | muhasebe | Muhasebe | Muhasebe | - | 14 |
| 31 | mehmet | Mehmet CORABCI | Planlama | - | 2 |
| 32 | altan | Altan TERZI | Yonetim | - | 28 |
| 33 | dervis | Dervis Resul Seven | Muhasebe | - | 14 |
| 34 | mehmetakif | Mehmet Akif Cil | Muhasebe | - | 14 |
| 35 | mehmetemin | Mehmet Emin Bakirci | Planlama | - | 2 |
| 36 | ibrahim | Ibrahim Kilic | Idari Isler | - | 0 (!) |
| 37 | nesrisamet | Nesri Samet Kirac | Kalite | - | 0 (!) |
| 38 | ferhat | Ferhat Usta | Enjeksiyon | sistem | 0 (!) |

KRITIK: Ferhat (yarinki test) 'Enjeksiyon' rolunde ama bu rolun
sistem_rol_yetki tablosunda HICBIR yetkisi yok. Demek ki:
- Ferhat su an yetki sistemiyle hicbir yere giremez
- Mevcut hardcoded fallback'ler (g_user.RolAd == 'Enjeksiyon')
  Ferhat'in enjeksiyon ekranina erismesini sagliyor

11 rol:

| Id | Rol Ad | Aciklama | SuperAdmin | Yetki Sayisi |
|----|--------|----------|------------|---------------|
| 1 | Yonetim | Tum modullere tam erisim | EVET | 28 |
| 2 | Muhasebe | Finans tam, maliyet giris | HAYIR | 14 |
| 3 | Cin Ofis | Numune + Cin siparis | HAYIR | 4 |
| 4 | Gumruk | Sevkiyat / beyanname | HAYIR | 3 |
| 5 | Grafik | Numune + urun tanimi | HAYIR | 7 |
| 6 | Personel | Sinirli goruntuleme | HAYIR | 0 (!) |
| 31 | Uretim | - | HAYIR | 0 (!) |
| 32 | Planlama | Uretim Planlama | HAYIR | 2 |
| 33 | Kalite | Kalite kontrol + numune onay | HAYIR | 0 (!) |
| 34 | Idari Isler | Idari/IK operasyon | HAYIR | 0 (!) |
| 35 | Enjeksiyon | Enjeksiyon Eva | HAYIR | 0 (!) |

4 rol yetkisiz: Personel, Uretim, Kalite, Idari Isler, Enjeksiyon.
Bu rollerdeki kullanicilar (Ferhat, Nesri, Ibrahim) su an hardcoded
fallback'lerle calisiyor.

---

## TABLO 4 - Onerilen Module Registry

Yeni tablo: module_registry

```sql
CREATE TABLE module_registry (
  module_key   TEXT PRIMARY KEY,
  module_name  TEXT NOT NULL,
  module_group TEXT NOT NULL,
  url          TEXT,
  icon         TEXT,
  sira         INTEGER DEFAULT 100,
  active       INTEGER DEFAULT 1,
  ozellikler   TEXT
);
```

Ilk veri (14 modul):

| module_key | module_name | group | url | icon | active |
|------------|-------------|-------|-----|------|--------|
| home | Ana Sayfa | Ozet | / | home | 1 |
| tasks | Gorevler | Ozet | /tasks | check-square | 1 |
| finans | Finans | Finans | /finans/ | dollar-sign | 1 |
| finans.anlasma | Anlasmalar | Finans | /finans/anlasma | file-text | 1 |
| finans.cari | Cari Hesaplar | Finans | /finans/cari | users | 1 |
| finans.simulator | Maliyet Simulator | Finans | /finans/simulator | calculator | 1 |
| finans.cin_ofis | Cin Ofis Import | Finans | /finans/cin-ofis | upload | 1 |
| grafik | Grafik Paneli | Grafik | /grafik/ | layers | 1 |
| grafik.urun | Urun Yonetimi | Grafik | /grafik/urun | box | 1 |
| grafik.numune | Numune Takip | Grafik | /grafik/numune | flask | 1 |
| grafik.tedarikci | Tedarikciler | Grafik | /grafik/tedarikci | truck | 1 |
| grafik.siparis | Cin Siparis | Grafik | /grafik/siparis | shopping-cart | 1 |
| grafik.sevkiyat | Sevkiyat & Maliyet | Grafik | /grafik/sevkiyat | ship | 1 |
| ithalat.parti | Ithalat Parti | Ithalat | /ithalat/parti/liste | package | 1 |
| hedef | Hedef Yonetimi | Uretim | /hedef/ | target | 1 |
| hedef.sablon | Sablon / Proses | Uretim | /hedef/sablon | layout | 1 |
| hedef.sapma | Sapma Analizi | Uretim | /hedef/sapma | trending-up | 1 |
| enjeksiyon | Enjeksiyon Takip | Uretim | /enjeksiyon/ | tool | 1 |
| enjeksiyon.saha | Saha Ekrani | Uretim | /enjeksiyon/saha | smartphone | 1 |
| planlama.proses_takip | Proses Takip | Planlama | /planlama/proses-takip | activity | 1 |
| planlama.karar_masasi | Karar Masasi | Planlama | /planlama/karar-masasi | clipboard | 1 |
| planlama.operasyon_raporu | Operasyon Raporu | Planlama | /planlama/operasyon-raporu | bar-chart | 1 |
| personel_giris | Uretim Girisi | Uretim | /personel-giris/ | user-check | 1 |
| usta | Usta Paneli | Uretim | /usta/ | hard-hat | 1 |
| canli_saha | Canli Saha (5055) | Uretim | /canli-saha/ | radio | 1 |
| uretim_giris | Uretim Girisi (Eski) | Uretim | /uretim-giris | edit | 0 |
| uretim_yonetim | Uretim Yonetim | Yonetim | /uretim-yonetim | settings | 0 |
| yonetim | Yonetim Paneli | Yonetim | /yonetim/ | shield | 1 |
| yonetim.kullanici | Kullanicilar | Yonetim | /yonetim/kullanici | user | 1 |
| yonetim.rol | Roller & Yetkiler | Yonetim | /yonetim/rol | lock | 1 |
| yonetim.kur | Kur Tanimlari | Yonetim | /yonetim/kur | trending-up | 1 |
| yonetim.log | Audit Log | Yonetim | /yonetim/log | activity | 1 |
| yonetim.proses_kategori | Proses Tanimlari | Yonetim | /yonetim/proses-kategori | grid | 1 |

---

## TABLO 5 - Onerilen Permission Matrix

Mevcut: sistem_rol_yetki 2 boyutlu (Gorebilir + Duzenleyebilir)
Hedef: Adem'in istegi - 7 boyutlu (can_view, can_create, can_update,
       can_delete, can_approve, can_report, can_manage)

Migration plani:

```sql
-- Adim 1: Yeni kolonlari ekle (eskileri silmiyoruz, geriye uyumlu)
ALTER TABLE sistem_rol_yetki ADD COLUMN can_view     INTEGER DEFAULT 0;
ALTER TABLE sistem_rol_yetki ADD COLUMN can_create   INTEGER DEFAULT 0;
ALTER TABLE sistem_rol_yetki ADD COLUMN can_update   INTEGER DEFAULT 0;
ALTER TABLE sistem_rol_yetki ADD COLUMN can_delete   INTEGER DEFAULT 0;
ALTER TABLE sistem_rol_yetki ADD COLUMN can_approve  INTEGER DEFAULT 0;
ALTER TABLE sistem_rol_yetki ADD COLUMN can_report   INTEGER DEFAULT 0;
ALTER TABLE sistem_rol_yetki ADD COLUMN can_manage   INTEGER DEFAULT 0;

-- Adim 2: Mevcut Gorebilir -> can_view, Duzenleyebilir -> can_update
UPDATE sistem_rol_yetki SET can_view = Gorebilir;
UPDATE sistem_rol_yetki SET can_update = Duzenleyebilir;
-- can_create varsayilan: Duzenleyebilir ile aynidir (mantik geregi)
UPDATE sistem_rol_yetki SET can_create = Duzenleyebilir;

-- Adim 3: Eski kolonlari koru (geriye uyumluluk icin)
-- Gorebilir + Duzenleyebilir kalir, yeni kod can_* kullanir
```

Matrix gosterimi (Yonetim > Yetkiler ekrani):

```
Kullanici: ferhat (Enjeksiyon)

Modul                     | View | Create | Update | Delete | Approve | Report | Manage |
--------------------------|------|--------|--------|--------|---------|--------|--------|
enjeksiyon                |  X   |   .    |   X    |   .    |    .    |   .    |   .    |
enjeksiyon.saha           |  X   |   X    |   X    |   .    |    .    |   .    |   .    |
hedef                     |  X   |   .    |   .    |   .    |    .    |   .    |   .    |
planlama.operasyon_raporu |  X   |   .    |   .    |   .    |    .    |   X    |   .    |
tasks                     |  X   |   X    |   X    |   .    |    .    |   .    |   .    |
```

---

## TABLO 6 - Oncelikli Guvenlik Aciklari

| # | Acik | Etki | Kim Etkilenir | Oncelik | Cozum |
|---|------|------|---------------|---------|-------|
| 1 | 114 POST endpoint korumasiz | Veri degisikligi | Tum kullanicilar | KRITIK | @login_required + yetki_gerek decorator |
| 2 | Enjeksiyon rolu 0 yetki | Ferhat hicbir seye giremez | Ferhat | YUKSEK | enj.* yetki kodlarini ekle |
| 3 | personel_giris/kaydet korumasiz | Sahte uretim kaydi | Tum personel | KRITIK | Yetki + session check |
| 4 | yonetim/kullanici/yeni korumasiz | Yetkisiz admin yaratimi | Sistem | KRITIK | yonetim.kullanici yetkisi sart |
| 5 | Hardcoded RolAd kontrolleri (150+ yer) | Esnek olmayan yetki | Bakim | YUKSEK | yetki() helper'a migrate |
| 6 | KullaniciAdi=='adem' bypass | Tek noktada acik | adem | ORTA | SuperAdmin flag kullan |
| 7 | Sidebar yetki = guvenlik yanilgisi | UI kandirma | Adminler | ORTA | Backend 403 sart |
| 8 | Sifre plaintext | Sifre calinabilir | Tum kullanicilar | YUKSEK | bcrypt hash migration |
| 9 | 0 yetkili rolde 3 kullanici | Calismaz veya bypass | Ibrahim, Nesri, Ferhat | YUKSEK | Rol yetkilerini doldur |
| 10 | proses_usta_atama hep halil | Test verisi prod'da | Saha | DUSUK | Gercek atama yap |
| 11 | sistem_audit 858 kayit ama erisim yok | Audit kor | Yoneticiler | DUSUK | Audit ekrani aktif et |
| 12 | finans.maliyet_goster yetki ayri | Cifte mantik | Muhasebe | DUSUK | Sadelestir |

---

## Mevcut Sistem Degerlendirmesi

Mevcut sistemin GUCLU yanlari:

1. Dot-notation yetki kodlari (finans.anlasma.sil) - sektor standardi
2. sistem_yetki.Modul ve AltModul gruplandirma hazir
3. sistem_rol.SuperAdmin flag - admin tespiti standart
4. sistem_rol_yetki.Gorebilir + Duzenleyebilir - 2 boyutlu baslangic
5. modules/auth.py - yetki_var fonksiyonu mevcut
6. sistem_audit tablosu - 858 kayit, denetim hazir
7. proses_usta_atama - KATMAN 2 izin sistemi (usta-proses bag)
8. /yonetim/rol ekrani calisiyor - genisletilebilir

Mevcut sistemin ZAYIF yanlari:

1. yetki() Sadece sidebar render'da kullaniliyor, backend'de yok
2. @login_required decorator hicbir endpoint'te yok
3. 10 modul (enjeksiyon, hedef, tasks vs) sisteme dahil degil
4. 4 rol (Enjeksiyon, Kalite, Idari Isler, Uretim) BOSTA
5. Hardcoded fallback'ler her yerde (RolAd == 'X' or KullaniciAdi == 'admin')
6. Sifre plaintext (kritik guvenlik)
7. module_registry tablo YOK (UI sayfa listesi mevcut, ama yapilandirilmamis)
8. permission matrix UI sade (sadece liste, switch yok)

---

## Migration Plani (2 boyut -> 7 boyut)

Adim 1: Snapshot al
Adim 2: ALTER TABLE sistem_rol_yetki - 7 kolon ekle
Adim 3: UPDATE - eski 2 kolon -> yeni 7 kolona map
Adim 4: Yeni yetki kodlari ekle (enjeksiyon.*, planlama.*, hedef.*, tasks.* vs)
Adim 5: 4 bos rolun yetkilerini doldur (Enjeksiyon, Kalite, Uretim, Idari Isler)
Adim 6: module_registry tablo olustur + 30 modul seed
Adim 7: @yetki_gerek decorator yaz - modules/auth.py icine ekle
Adim 8: yonetim/rol ekrani -> 7 boyutlu switch matrix
Adim 9: Sidebar -> hardcoded RolAd kontrollerini yetki() ile degistir
Adim 10: Modul bazli endpoint'lere decorator ekle (tek modul, test, snapshot, sonraki)
Adim 11: Sifre hash migration (bcrypt) - en son ve ayri patch

Toplam tahmini sure: 3-4 gun yogun calisma (modul bazli kademeli)

---

## Anayasa Kurallari

Adem'in karar verdigi sistem anayasasi:

1. Yeni modul yazilmadan ONCE module_registry kaydi olacak.
2. Yeni modul icin yetki kodu sistem_yetki'ye eklenecek.
3. Backend endpoint'lere @yetki_gerek decorator zorunlu.
4. Sidebar yetki() ile beslenecek, hardcoded RolAd yok.
5. Buton/islem yetkisi UI'da kontrol edilecek (data-yetki attribute).
6. Yonetim > Yetkiler ekrani 7 kolon (View/Create/Update/Delete/Approve/Report/Manage)
7. Yetki yoksa modul yok. (Yeni modul yazma engellenir.)
8. Menu gizleme guvenlik degildir. Backend 403 zorunlu.

BUNDAN SONRAKI HER YENI MODUL ICIN CHECK LIST:
- [ ] module_registry'de kayit var mi?
- [ ] sistem_yetki'de yetki kodu tanimli mi?
- [ ] Sidebar yetki() ile mi besleniyor?
- [ ] Backend endpoint @yetki_gerek decorator'lu mu?
- [ ] Buton/islem yetkileri kontrol ediliyor mu?
- [ ] sistem_audit'e logleniyor mu?

Cevaplar HAYIR ise: modul gelistirme DURDURULUR.

---

## Yarinki Oncelikler

1. ONCELIK: Ferhat saha testi (10 adim, foto yok)
   - Mevcut hardcoded fallback'lerle calisacak
   - Bu test sirasinda yetki kirildigi yer not edilecek

2. Test sonrasi: Bu doku ile beraber Yetki Sistemi V2 patch'i baslar
   - Snapshot
   - 11 adimli migration plani sirasiyla

3. Patch sirasi onerisi (en az riskten en cok riske):
   - Snapshot
   - module_registry tablosu (yeni, etkisi yok)
   - 7 yeni kolon ekle (eski 2 kolon kalir)
   - Yeni yetki kodlari ekle (Ferhat'in Enjeksiyon rolu icin oncelikle)
   - @yetki_gerek decorator yaz
   - Modul bazli decorator ekleme (en az kullanilan modulden basla)
   - Sidebar refactor (hardcoded -> yetki() helper)
   - Sifre hash migration (en son, ayri sprint)

---

## Belge Surumu

| Surum | Tarih | Aciklama |
|-------|-------|----------|
| v1 | 2026-05-15 | Analiz raporu olusturuldu (kod yok) |

Patch baslayinca: YETKI_SISTEMI_V2_PATCH_LOG.md ayri belge.



===== docs\PERMISSION_MATRIX_PLAN.md =====

# PERMISSION_MATRIX_PLAN

Belge tipi: Cekirdek mimari freeze
Tarih: 2026-05-15 (gece)
Snapshot referansi: STABLE_OP_RAPOR_V2_GECMIS_DONE_20260515_161612
Durum: FREEZE - patch yok, implementasyon yarin sonrasi
Ilgili belgeler: YETKI_SISTEMI_V2_ANALIZ.md, MODULE_REGISTRY_PLAN.md

---

## 1. Amac ve Mevcut Durum

permission_matrix, CPS'te bir kullanicinin bir modul uzerinde NE YAPABILECEGINI
tanimlayan tek kaynaktir. Mevcut sistem yetersiz, V2'de genisletilecek.

Mevcut durum (15.05.2026 itibariyle):

- sistem_rol_yetki tablosu 2 boyutlu: Gorebilir (1/0) + Duzenleyebilir (1/0)
- 61 rol-yetki bag kaydi mevcut
- 11 rol, 30 yetki kodu, 14 kullanici
- 4 rol (Enjeksiyon, Kalite, Idari Isler, Uretim, Personel) hicbir yetkiye bagli degil
- Yetki kontrolu sadece sidebar render'da kullaniliyor (Jinja yetki(...))
- 240 endpoint'in sadece planlama modulundeki 8 tanesi yetki cagrisi yapiyor
- 122 POST endpoint'inin 114'u korumasiz
- Hardcoded RolAd == kontrolleri sistemde 150+ yerde var

Hedef durum (V2):

- sistem_rol_yetki 7 boyutlu: can_view, can_create, can_update, can_delete,
  can_approve, can_report, can_manage
- user_permission_override tablosu - kullanici bazli ozel izin/kisitlama
- @yetki_gerek decorator backend'de tum endpoint'lere uygulanir
- yetki(kod, action) jinja helper sidebar/template'lerde kullanilir
- 403 fallback standardize davranis
- Hardcoded RolAd kontrolleri tamamen kaldirilir

---

## 2. Yedi Yetki Boyutunun Anlami

Adem'in talebi ile 7 boyut. Her boyut bir endpoint method tipiyle veya
UI aksiyonuyla esleserir.

| Boyut | Karsiligi | Endpoint Method | UI Karsiligi |
|-------|-----------|-----------------|--------------|
| can_view | Goruntuleme | GET (listing, detay) | Sayfa acabilir, listeyi gorur |
| can_create | Yeni olusturma | POST (.../yeni) | "Yeni Ekle" butonu |
| can_update | Duzenleme | POST/PUT (.../guncelle) | "Duzenle" butonu |
| can_delete | Silme | POST/DELETE (.../sil) | "Sil" butonu |
| can_approve | Onaylama | POST (.../onayla, .../reddet) | "Onayla" / "Reddet" butonlari |
| can_report | Rapor alma | GET (.../rapor, .../export) | "Rapor", "Excel Indir" butonlari |
| can_manage | Yonetsel kontrol | Hassas islemler | Rol degisikligi, masraf onayi, kritik aksiyonlar |

can_manage notu:
- Bu en yuksek yetki seviyesidir
- Genelde SuperAdmin'lere verilir
- Module ozel cok kritik aksiyonlar icin: kullanici sifre sifirlama, rol degistirme,
  master data temizleme, bulk delete, vs.

can_approve notu:
- Onay/red aksiyonlari bu boyuta dusur
- Hedef modulundeki uretim onayi, finans modulundeki anlasma onayi, vs.

can_report notu:
- Sadece ozet/agregasyon/export tipi okuma
- can_view'den farkli: detayli rapor ya da yetkili olmasan goremedigin agregasyon

---

## 3. Tablo Semasi

ALTER TABLE ile mevcut sistem_rol_yetki tablosuna 7 kolon eklenecek.
Eski Gorebilir/Duzenleyebilir kolonlari KORUNACAK (geriye uyumluluk).

SQL (Migration script icerigi):

ALTER TABLE sistem_rol_yetki ADD COLUMN can_view     INTEGER DEFAULT 0;
ALTER TABLE sistem_rol_yetki ADD COLUMN can_create   INTEGER DEFAULT 0;
ALTER TABLE sistem_rol_yetki ADD COLUMN can_update   INTEGER DEFAULT 0;
ALTER TABLE sistem_rol_yetki ADD COLUMN can_delete   INTEGER DEFAULT 0;
ALTER TABLE sistem_rol_yetki ADD COLUMN can_approve  INTEGER DEFAULT 0;
ALTER TABLE sistem_rol_yetki ADD COLUMN can_report   INTEGER DEFAULT 0;
ALTER TABLE sistem_rol_yetki ADD COLUMN can_manage   INTEGER DEFAULT 0;

CREATE INDEX idx_sry_rol_yetki ON sistem_rol_yetki(RolId, YetkiId);

Migration ilk verisi - mevcut 2 boyut yeni 7 boyuta map edilir:

UPDATE sistem_rol_yetki SET can_view = Gorebilir WHERE Gorebilir IS NOT NULL;
UPDATE sistem_rol_yetki SET can_create = Duzenleyebilir WHERE Duzenleyebilir IS NOT NULL;
UPDATE sistem_rol_yetki SET can_update = Duzenleyebilir WHERE Duzenleyebilir IS NOT NULL;
UPDATE sistem_rol_yetki SET can_delete = 0;
UPDATE sistem_rol_yetki SET can_approve = 0;
UPDATE sistem_rol_yetki SET can_report = Gorebilir WHERE Gorebilir IS NOT NULL;
UPDATE sistem_rol_yetki SET can_manage = 0;

Mantik: Eski Duzenleyebilir hem create hem update'i kapsiyordu - ikisine de map.
Delete, approve, manage ekstra yetkiler - default 0, manuel ayarlanir.
Report eski gorebilir ile ayni - default ekleme.

---

## 4. user_permission_override Tablosu (Yeni)

Kullanici bazli ozel izin/kisitlama icin yeni tablo.

CREATE TABLE user_permission_override (
    Id              INTEGER PRIMARY KEY AUTOINCREMENT,
    KullaniciId     INTEGER NOT NULL,
    YetkiId         INTEGER NOT NULL,
    can_view        INTEGER,
    can_create      INTEGER,
    can_update      INTEGER,
    can_delete      INTEGER,
    can_approve     INTEGER,
    can_report      INTEGER,
    can_manage      INTEGER,
    aciklama        TEXT,
    olusturma_tarih TEXT DEFAULT (datetime('now')),
    olusturan       TEXT,
    FOREIGN KEY (KullaniciId) REFERENCES sistem_kullanici(Id),
    FOREIGN KEY (YetkiId) REFERENCES sistem_yetki(Id),
    UNIQUE (KullaniciId, YetkiId)
);

CREATE INDEX idx_upo_kullanici ON user_permission_override(KullaniciId);
CREATE INDEX idx_upo_yetki ON user_permission_override(YetkiId);

NULL onemli:
- NULL = "override yok, rol yetkisini kullan"
- 0 = "override var, AKTIF KAPALI" (rolde acik bile olsa)
- 1 = "override var, AKTIF ACIK" (rolde kapali bile olsa)

UNIQUE constraint: Bir kullanicinin bir yetki uzerinde tek override'i olur.

---

## 5. Effective Permission Hesap Sirasi (KRITIK)

Bu en cok karistirilabilen bolum. Sirayla:

1. Kullanici giris yapar, session kullanici bilgileri yuklenir
2. Bir yetki kontrolu yapilir, ornek: yetki_var(user, 'finans.anlasma', 'can_update')
3. Hesap motoru su sirayla bakar:

   ADIM A - SuperAdmin shortcut:
   - sistem_rol.SuperAdmin = 1 olan rol kullanicinin rolu ise: True don.
   - Bu ENG ONCE bakilir, hicbir override veya rol yetkisi kontrol edilmez.
   - SuperAdmin tum yetkilere sahiptir.

   ADIM B - user_permission_override:
   - SELECT can_update FROM user_permission_override
     WHERE KullaniciId = user.Id AND YetkiId = yetki_id
   - Sonuc NULL degilse (override var):
     - 1 ise True don
     - 0 ise False don
   - Sonuc NULL ise veya kayit yoksa: Adim C'ye ge�

   ADIM C - sistem_rol_yetki:
   - SELECT can_update FROM sistem_rol_yetki
     WHERE RolId = user.RolId AND YetkiId = yetki_id
   - 1 ise True don
   - 0 veya kayit yok ise False don

Ozel durumlar:

- module_registry.is_active = 0 ise: Once 404 don, yetki kontrol edilmez
- module_registry.is_hidden = 1 ise: Sadece SuperAdmin gecer
- user.Aktif = 0 ise: Tum yetki kontrolleri False (login engellenir aslinda)

Bu sira KESINDIR. Once SuperAdmin, sonra override, sonra rol. Hicbir zaman tersi degil.

---

## 6. Rol + Kullanici Override Modeli (Detayli)

Mantigi anlamak icin ornek senaryolar:

ORNEK 1: Ferhat Usta
- Rol: Enjeksiyon
- sistem_rol_yetki: Enjeksiyon rolune sadece enjeksiyon.* yetkilerin can_view=1
- user_permission_override: BOS (override yok)
- Sonuc: Ferhat sadece enjeksiyon ekranini gorur

ORNEK 2: Ferhat Usta + Operasyon Raporu istegi
- Rol: Enjeksiyon (degismeden)
- sistem_rol_yetki: Degismez (rol-bazli)
- user_permission_override:
  INSERT (KullaniciId=38, YetkiId=<planlama.operasyon_raporu_id>, can_view=1, can_report=1)
- Sonuc: Ferhat'a OZEL olarak operasyon raporu acildi.
  Diger Enjeksiyon rolundeki kullanicilar bunu goremez. Sadece Ferhat.

ORNEK 3: Mehmet Planlama'dan finans goruntuleme kisitlama
- Rol: Planlama (default grafik.numune yetkisi var)
- user_permission_override:
  INSERT (KullaniciId=31, YetkiId=<grafik.numune_id>, can_view=0)
- Sonuc: Planlama rolunde grafik.numune var ama Mehmet'e OZEL olarak kapatildi.
  Diger Planlama rolundeki kullanicilar (Mehmet Emin) hala gorur.

Override felsefesi:
- Rol = genel kurali
- Override = istisnayi
- Yonetim ekraninda her kullanici icin "rol yetkileri" + "ozel istisnalar" gosterilir

---

## 7. Backend Decorator API (@yetki_gerek)

modules/auth.py icinde yeni decorator tanimlanacak.

Imza:

def yetki_gerek(module_key, action='can_view'):
    """
    Endpoint koruyucu decorator.
    Kullanim:
        @yetki_gerek('finans.anlasma')
        @yetki_gerek('finans.anlasma', 'can_create')
        @yetki_gerek('finans.anlasma', 'can_update')
    """

Davranis:

1. Session'dan kullaniciyi al (yoksa /giris'e yonlendir)
2. module_registry.is_active kontrol et (0 ise 404)
3. module_registry.is_hidden kontrol et (1 ise SuperAdmin disindakilere 403)
4. Effective permission hesapla (Section 5)
5. False ise: 403 don + audit log + flash mesaj

Kullanim ornekleri:

@finans_bp.route('/anlasma')
@yetki_gerek('finans.anlasma')
def anlasma_liste():
    ...

@finans_bp.route('/anlasma/yeni', methods=['POST'])
@yetki_gerek('finans.anlasma', 'can_create')
def anlasma_yeni():
    ...

@finans_bp.route('/anlasma/<int:id>/sil', methods=['POST'])
@yetki_gerek('finans.anlasma', 'can_delete')
def anlasma_sil(id):
    ...

@finans_bp.route('/anlasma/<int:id>/onayla', methods=['POST'])
@yetki_gerek('finans.anlasma', 'can_approve')
def anlasma_onayla(id):
    ...

Kural: Method ile action otomatik eslesmez. Action her zaman EXPLICIT yazilir.
Cunku ayni endpoint birden fazla action gerektirebilir (POST ile hem create
hem delete olabilir, sadece method bakilamaz).

---

## 8. Frontend Visibility Helper

Mevcut yetki(kod) jinja fonksiyonu V2'de yetki(kod, action) olarak genisleyecek.

Imza:

def yetki(module_key, action='can_view'):
    """
    Jinja template'lerde kullanilan helper.
    Effective permission hesabini yapar ve True/False doner.
    """

Kullanim ornekleri (template icinde):

{% if yetki('finans.anlasma') %}
    <a href="/finans/anlasma">Anlasmalar</a>
{% endif %}

{% if yetki('finans.anlasma', 'can_create') %}
    <button>Yeni Anlasma Ekle</button>
{% endif %}

{% if yetki('finans.anlasma', 'can_delete') %}
    <button class="kirmizi">Sil</button>
{% endif %}

{% if yetki('finans.anlasma', 'can_approve') %}
    <button>Onayla</button>
{% endif %}

KRITIK KURAL:
Frontend gizleme guvenlik DEGILDIR. Asil guvenlik backend 403 ile saglanir.

Frontend yetki() sadece UX icindir:
- Yetkisi olmayan butonu gostermez
- Yetkisi olmayan menu satirini gizler
- Ama API'ye kullanici direkt request gonderebilirse: backend reddetmeli

DOGRU:
Backend @yetki_gerek var + Frontend yetki() gosterir/gizler = Tam guvenlik

YANLIS:
Sadece frontend yetki() kontrolu = Backend acik = Postman ile by-pass

---

## 9. 403 Fallback Davranis Standardi

Bir kullanici yetkisi olmayan endpoint'e erismeye calistiginda:

| Erisim tipi | Davranis |
|-------------|----------|
| HTML sayfa istegi (GET) | 403 render template/403.html, "Bu sayfaya erisim yetkiniz yok" |
| AJAX/fetch (Accept: json) | 403 JSON: {"ok": false, "hata": "Yetki yok", "kod": 403} |
| POST form submit | 403 + flash mesaj + redirect URL yonlendirme |
| API tipi endpoint (/api/...) | 403 JSON her zaman |

Audit log:

Her 403 olayi sistem_audit'e yazilir:
- action_type: ACCESS_DENIED
- kullanici_id, module_key, action, ip, user_agent, timestamp

Bu sayede Yonetim > Audit Log ekraninda "Kim neye erismeye calisti ama olmadi"
gorunur. Guvenlik analiz icin kritik.

403 sayfasi mesajlari:

- Genel: "Bu sayfaya erisim yetkiniz yok."
- Detayli (admin gorur): "module_key=finans.anlasma action=can_delete reddedildi"
- Loglu: "Bu olay kayit edildi. Yetki istegi icin yoneticinize basvurun."

Kullanicinin yetki istemesi:

- 403 sayfasinda "Yetki Iste" butonu
- Tiklandiginda yoneticiye notification
- (V2 sprint 2'de eklenebilir, V1'de sadece statik mesaj)

---

## 10. Sidebar'in Registry'den Beslenme Mantigi

Mevcut base.html durumu:
- Hardcoded 150+ HTML satir
- Her menu satiri icin {% if yetki(...) or RolAd == 'X' or KullaniciAdi == 'admin' %}
- Bakim cehennemi: yeni modul eklemek icin base.html'i duzenlemek gerek

V2 hedef:

base.html sadece SU satiri icerir (sidebar bolumunde):

{{ sidebar_render(g_user) | safe }}

sidebar_render() Python fonksiyonu:

def sidebar_render(user):
    """
    Kullanicinin yetkilerine gore tam sidebar HTML doner.
    module_registry + sistem_rol_yetki + user_permission_override'dan beslenir.
    """
    # 1. Aktif modulleri al
    moduller = SELECT * FROM module_registry
               WHERE is_active = 1
               AND (is_hidden = 0 OR user.SuperAdmin = 1)
               ORDER BY menu_group, sira

    # 2. Her modul icin yetki kontrol
    gosterilecek = []
    for m in moduller:
        if m.permission_key is None:
            gosterilecek.append(m)  # Yetki gerekmeyenler herkese acik
        elif yetki(m.permission_key, 'can_view'):
            gosterilecek.append(m)

    # 3. menu_group'a gore grupla
    gruplar = group_by(gosterilecek, key='menu_group')

    # 4. HTML render et
    return render_template('sidebar_v2.html', gruplar=gruplar)

sidebar_v2.html template'i:
- Her grup baslik altinda kendi modulleri
- parent_key olanlar collapse/accordion icinde
- Active sayfa highlight (request.path uyumlu)
- Icon Lucide (module_registry.icon)

Avantajlar:
- Yeni modul = SADECE module_registry INSERT (base.html dokunulmaz)
- Yetki degisikligi = SADECE DB UPDATE (kod restart gerek yok)
- Test edilebilir (sidebar_render fonksiyon birim test edilir)

---

## 11. Migration Plani: Eski Sistem -> Yeni Sistem

Toplam 11 adim. Sirasiyla:

ADIM 1 - Snapshot
- STABLE_YETKI_V2_PRE_MIGRATION_<ts>
- mock_data.db yedeklenir
- Rollback komutu hazirda durur

ADIM 2 - Migration scripts olusturma
- app/migrations/003_module_registry.py (Bolum 3, MODULE_REGISTRY_PLAN.md)
- app/migrations/004_permission_matrix_v2.py (Bolum 3, bu doku)
- app/migrations/005_user_permission_override.py (Bolum 4, bu doku)

ADIM 3 - Migration calistir
- 003, 004, 005 sirayla calistir
- Her birinden sonra dogrulama: tablo var mi, kolon eklendi mi?

ADIM 4 - Seed verisi (yeni yetki kodlari)
- sistem_yetki'ye eksik 9 modul icin yetki kodlari ekle:
  - enjeksiyon.* (3 yetki: saha, yonetim, ariza-bildirim)
  - hedef.* (3 yetki: liste, onayla, reddet)
  - planlama.* (3 yetki: proses_takip, karar_masasi, operasyon_raporu)
  - tasks.* (2 yetki: liste, yonet)
  - personel_giris.* (1 yetki)
  - usta.* (1 yetki)
  - uretim_giris.* (1 yetki)
  - uretim_yonetim.* (1 yetki)
  - canli_saha.* (1 yetki)
- Toplam yeni 16+ yetki kaydi

ADIM 5 - Bos rollerin yetkilerini doldur
- Enjeksiyon rolu: enjeksiyon.saha can_view + can_create, hedef can_view
- Kalite rolu: grafik.numune can_view + can_approve
- Idari Isler rolu: yonetim.log can_view, finans.cari can_view
- Uretim rolu: hedef can_view + can_create
- Personel rolu: hedef can_view, personel_giris can_view + can_create

ADIM 6 - modules/auth.py guncelleme
- yetki_var() fonksiyonu yetki_var(user, kod, action) imzasiyla
- yetki_gerek() decorator yazimi
- yetki() jinja helper register

ADIM 7 - Tek modul pilot decorator ekleme
- Once SADECE yonetim modulu enjeksiyon decorator'leri al
- Test et: admin gecer, ferhat gecemez
- Test bittikten sonra digerleri kademeli

ADIM 8 - Kademeli modul decorator ekleme
- Sira: yonetim, finans, ithalat, hedef, grafik, planlama, enjeksiyon, tasks, others
- Her modul icin: snapshot + decorator ekle + test + audit
- 1 gun 1 modul tempolu

ADIM 9 - Sidebar V2 (paralel calisma)
- USE_V2_SIDEBAR feature flag (config'de False default)
- Admin test ederken True yapip dener
- Sorun yoksa True kalir

ADIM 10 - Hardcoded RolAd temizleme
- 150+ if RolAd == X satirlari yetki(...) ile degisir
- HARDCODE_YETKI_RECON.md belgesindeki listeden gidilir

ADIM 11 - Snapshot final
- STABLE_YETKI_V2_FULL_DONE_<ts>
- Belgeler guncellenir

Beklenen sure: 5-7 is gunu. Tempo: 1 gun 1 modul.

---

## 12. Hardcoded Role Kontrolunden Cikis Plani

Mevcut sistemde su kalipdaki kontroller var:

{% if g_user.RolAd == 'Yonetim' %}
{% if g_user.RolAd in ('Yonetim', 'Planlama') %}
{% if g_user.KullaniciAdi == 'admin' %}
if user.get('RolAd') == 'Yonetim':

Her birinin V2 karsiligi var. Donusum tablosu:

Eski:                                          | Yeni:
{% if g_user.RolAd == 'Yonetim' %}             | {% if yetki('yonetim') %}
{% if g_user.RolAd == 'Planlama' %}            | {% if yetki('planlama') %}
{% if g_user.KullaniciAdi == 'admin' %}        | {% if g_user.SuperAdmin %}
{% if RolAd in ('A','B','C') %}                | {% if yetki('module_kodu') %}
if user.get('RolAd') == 'X':                   | if yetki_var(user, 'module_kodu'):

KullaniciAdi == 'adem' ve KullaniciAdi == 'altan' gibi ozel kullanici bypass'lari:
- Bunlar tamamen kaldirilir
- Onlara SuperAdmin flag = 1 ile rol verilir
- Sonra her yerde g_user.SuperAdmin kullanilir

HARDCODE_YETKI_RECON.md belgesi tum bu kontrollerin listesini yapacak.
Patch sirasinda satir-satir gidilip degistirilecek.

---

## 13. Yonetim > Yetkiler Ekrani (UX Tasarimi)

Sol panel - Kullanici kartlari:

[kullanici karti tasarimi]
- Avatar (ad bas harfi)
- Ad Soyad
- @KullaniciAdi
- Rol etiket (renkli pill)
- Aktif/Pasif badge
- Yildiz seviye (1-5)
- "Detay" butonu

Sag panel - Yetki matrisi:

Secilen kullaniciya gore:
- Ust baslik: "Ferhat Usta - Yetki Matrisi"
- Alt baslik: "Rol: Enjeksiyon | Override: 2 ozel izin"

Tablo:
- Satirlar: module_registry'den modul listesi
- Kolonlar: 7 boyut (View, Create, Update, Delete, Approve, Report, Manage)
- Her hucre: toggle switch (on/off)
- Hucre rengi:
  - Yesil: Rolden gelen yetki var, override yok
  - Mavi: Override ile acilmis (rolde olmasa bile)
  - Kirmizi/cizik: Override ile kapatilmis (rolde olsa bile)
  - Gri: Yetki yok (rolde de yok)

Alt aksiyon:
- "Tum override'lari sifirla" butonu
- "Rol degistir" dropdown
- "Kullaniciyi pasifle" butonu

Audit:
- Sag ust kose: "Son degisiklik: 15.05.2026 14:32 - admin tarafindan"

---

## 14. Continuation - Yarin Nereden Devam

Bu doku FREEZE durumda. Patch baslamadi.

Yarin Ferhat saha testi bittikten sonra:

1. Bu doku tekrar okunur (15 dakika)
2. MODULE_REGISTRY_PLAN.md ile karsilastirilir (uyumlu mu?)
3. Adem onayi alinir
4. PERSONEL_IK_OMURGA_PLAN.md de okunur (yazilirsa)
5. HARDCODE_YETKI_RECON.md tamamlanir
6. Hepsi tamam ise patch baslar (Adim 1: Snapshot)

Eger bu doku yarin degisecekse:
- docs/PERMISSION_MATRIX_PLAN_CHANGELOG.md'ye not yazilir
- Bu doku v2 olarak yenilenir
- Eski versiyon yedek kalir

Patch sirasinda:
- Her adim sonrasi browser test
- Her adim sonrasi audit log kontrol
- Her adim sonrasi snapshot disiplini

---

## 15. Diger Belgelerle Iliski

| Belge | Durum | Konu |
|-------|-------|------|
| YETKI_SISTEMI_V2_ANALIZ.md | YAZILDI | 6 tablolu envanter, 11 adimli migration, 12 acik |
| MODULE_REGISTRY_PLAN.md | YAZILDI | Modul kayit standardi (freeze) |
| PERMISSION_MATRIX_PLAN.md | BU DOKU | 7 boyutlu yetki + override (freeze) |
| PERSONEL_IK_OMURGA_PLAN.md | RECON BEKLIYOR | Kisi karti, hiyerarsi, aktivite |
| HARDCODE_YETKI_RECON.md | SIRADA | 150+ hardcoded kontrol liste |

Bu doku 3 belge ile ic ice:

- MODULE_REGISTRY_PLAN: Yetki anahtarinin nereden geldigi (module_key)
- PERMISSION_MATRIX_PLAN: Yetkinin 7 boyutu ve hesaplanmasi
- HARDCODE_YETKI_RECON: Eski sistemden temizlenecek yerler

---

## 16. Geli�tirici Standardi Vurgu

YENI ENDPOINT YAZARKEN DEGISMEZ KURALLAR:

1. Endpoint mutlaka @yetki_gerek('module_key', 'action') ile baslar
2. module_key module_registry'de kayitli olmalidir
3. action 7 boyuttan biri olmalidir
4. Yetki kontrolu KOD ICINDE yapilmaz (decorator yapar)
5. Hardcoded RolAd kontrolu YASAK
6. KullaniciAdi == 'admin' YASAK
7. 403 sayfasi standart - manuel donulmez

YENI TEMPLATE YAZARKEN DEGISMEZ KURALLAR:

1. {% if yetki(kod, action) %} kullan
2. Hardcoded {% if RolAd %} YASAK
3. Buton/menu/aksiyon yetki kontrollu olmali
4. Yetki yoksa element tamamen gizlenir (visibility: hidden DEGIL, render edilmez)

YENI MODUL YAZARKEN DEGISMEZ KURALLAR:

1. module_registry'e INSERT (is_hidden=1 ile basla)
2. sistem_yetki'ye INSERT (en az can_view)
3. sistem_rol_yetki'ye INSERT (en az 1 role acik)
4. Blueprint @yetki_gerek decorator'lu
5. Sidebar otomatik gosterilir (sidebar_render kullanir)
6. Test (is_hidden=1 ile sadece superadmin gorur)
7. Onay sonrasi is_hidden=0

Bu kurallar anayasadir. Istisna YOK.

---

## 17. Belge Surumu

| Surum | Tarih | Aciklama |
|-------|-------|----------|
| v1 | 2026-05-15 | Cekirdek mimari freeze (patch yok) |

Sonraki surumde patch sonucu eklenir (Adim 11 - Final snapshot sonrasi).


===== docs\CPS_MODUL_YETKI_STANDARDI_v1.md =====

# CPS MODÜL GELİŞTİRME STANDARDI v1

> **⚡ KULLANIM TALİMATI**
>
> Bu doküman CPS geliştirmelerinde ana referans dosyasıdır. Yeni bir oturumda,
> yeni modül geliştirmede veya patch öncesinde **önce bu dosya okunmalı**;
> sonra analiz ve patch planı çıkarılmalıdır.

**Tarih:** 13.05.2026
**Onay:** Adem TERZİ
**Statü:** RESMÎ STANDART (köprü dönem)
**Geçerlilik:** Yetki Sistemi V2 hayata geçene kadar
**Dosya:** `docs/CPS_MODUL_YETKI_STANDARDI_v1.md`

Bu doküman 13.05.2026 oturumunda yaşanan çoklu yetki/menü/route/upload karmaşası
sonrası resmî karar olarak yayınlanmıştır. CPS sistemine eklenecek **her yeni
modül** bu standarda uymak zorundadır.

---

## İÇİNDEKİLER

1. CPS Modül Yetki Standardı
2. Korgun Veri Çekme Standardı
3. CPS Analiz Standardı
4. Patch Standardı
5. Upload / Belge Standardı
6. Güvenlik Standardı
7. Bilinen Bug Dersleri
8. V2 Hedefi
9. Changelog

---

# 1. CPS MODÜL YETKİ STANDARDI

CPS, **operasyon sistemi**dir. Korgun ERP'den **okur**, kendi kayıtlarını
**yazar**. Her modül kendi yetki kapısına sahip olmak zorundadır.

## 1.1 Temel İlkeler

1. **"Sidebar'da gizlemek güvenlik değildir."**
   Kullanıcı linki görmüyor olsa bile URL'i bilirse erişebiliyorsa, modül
   **güvensiz** sayılır. Backend guard her zaman zorunlu.

2. **"Yetki ekranı işaretli ama menüde yok" durumu olmamalı.**
   DB'de yetki atanan kullanıcı menüde linki görmeli, link backend route'u
   gerçekten açabilmeli.

3. **"Menüde link var ama URL 404" durumu olmamalı.**
   Modülün kök URL'i çalışmalı, yönlendirme zinciri kapalı olmalı.

4. **Audit log varsayılan olarak açık.**
   Kritik işlemler (oluştur/güncelle/sil/onay/red) `sistem_audit` tablosuna
   yazılır.

## 1.2 Zorunlu Modül Checklist'i

Her yeni modül **canlıya alınmadan önce** aşağıdaki 10 madde tamamlanmalı:

```
[ ] 1. Blueprint tanımı  (blueprint adı + url_prefix + dosya konumu)
[ ] 2. URL prefix standardı  (/<modul>) — hardcode URL yasak
[ ] 3. Kök route  (@bp.route('/') -> redirect ana sayfa)
[ ] 4. sistem_yetki kayıtları  (Açıklama dolu)
[ ] 5. Sidebar link  (yetki() veya rol koşulu ile)
[ ] 6. Backend guard  (@yetki_gerekli veya @before_request)
[ ] 7. Audit log  (kritik işlemler)
[ ] 8. Upload/config kontrolü  (varsa)
[ ] 9. Rollback noktası  (.YEDEK_<açıklama>_<timestamp>)
[ ] 10. STABLE backup  (modül canlıya alındıktan sonra)
```

## 1.3 Yetki Katmanları

| Katman | Kontrol Yeri | Yetersiz olursa |
|---|---|---|
| **Sidebar görünürlüğü** | base.html `{% if yetki(...) %}` | Link görünmez (URL bilen erişebilir) |
| **Route erişimi** | Backend dekoratör veya `@before_request` | 403 döner |
| **İşlem yetkisi** | `<kod>.duzenle` yetkisi | POST/UPDATE/DELETE engellenir |
| **Upload yetkisi** | `<kod>.duzenle` + Config.UPLOAD_ROOT | Dosya yüklenemez |
| **Yönetim bypass** | `RolAd == 'Yönetim'` veya `'*' in yk` | Tüm kontroller geçilir |
| **Admin bypass** | `KullaniciAdi == 'admin'` veya hardcode | Tüm kontroller geçilir |

**Köprü dönemde** sidebar görünürlüğü ile route erişimi paralel yazılır
(`base.html` ve `routes.py` aynı koşulu kullanır). V2'de ikisi de
`sistem_yetki` tablosundan beslenecek.

## 1.4 Standart Yetki Kod Yapısı

```
<modul>                          # genel görüntüleme
<modul>.<alt>                    # alt modül detayı
<modul>.<alt>.<aksiyon>          # belirli aksiyon
```

### Örnekler

```
grafik.urun.goruntule
grafik.urun.duzenle
grafik.numune.onayla
finans.odeme.goruntule
finans.cari.sil
planlama.karar_masasi.goruntule
ithalat.parti.onayla
```

### Kurallar

- Tümü küçük harf
- Türkçe karakter yasak (`gümrük` -> `gumruk`)
- Boşluk yasak (`.` ve `_` ayraç)
- Maksimum 3 seviye
- Ortak aksiyonlar: `goruntule`, `duzenle`, `sil`, `onayla`, `reddet`,
  `indir`, `export`

### Suffix Esneme

`auth.py` `yetki_var()` fonksiyonu suffix esneme yapar:
`yetki('grafik.urun')` çağrısı `grafik.urun.goruntule` yetkisini de kabul eder.
Yani sidebar'da kısa yazılabilir.

## 1.5 Köprü Dönem Rol Whitelist'i (Geçici)

Hardcode rol whitelist Yetki Sistemi V2 hayata geçene kadar geçerli.

| Rol | Modül erişimi |
|---|---|
| Yönetim | Hepsi (wildcard) |
| Muhasebe | Finans + Grafik (kısmi) + İthalat |
| Planlama | Hedef + Üretim + Planlama |
| Kalite | Hedef + Üretim (görüntüleme) |
| İdari İşler | Hedef (sınırlı) + Görevler |
| Grafik | Grafik modülü |
| Usta | Hedef + Üretim girişi |
| Personel | Sınırlı görüntüleme |
| Çin Ofis | Grafik.numune + Grafik.cin_siparis |

**Önemli:** Halil gibi `RolAd='Yönetim'` ama `Tip='usta'` olan kullanıcılar için
ek filtre gerekli — sadece RolAd yeterli değil. Bu özel durumlar modülün
`_modul_guard()` fonksiyonunda ele alınır (örn Finans guard).

---

# 2. KORGUN VERİ ÇEKME STANDARDI

Korgun ERP, **veri kaynağı**dır. CPS, **operasyon sistemi**dir.
Bu iki sistem **birbirinden bağımsız** çalışır ve **birbirine karışmaz**.

## 2.1 Temel Kural

```
Korgun  =  veri kaynağı  (sipariş, üretim emri, stok, müşteri)
CPS     =  operasyon     (planlama, onay, görev, kalite, prim)
```

**Yön:**
```
Korgun  -->  CPS  (READ ONLY)
CPS     -->  Korgun  YASAK
```

Korgun veritabanına **HİÇBİR koşulda** CPS'ten yazma yapılmaz. Korgun'da olan
ne varsa, Korgun yazar. CPS yalnızca okur.

## 2.2 Bağlantı Detayları

| Alan | Değer |
|---|---|
| Host | 25.7.184.221 (Hamachi) veya 192.168.1.16 (LAN) |
| Database | Solariz22 (MSSQL) |
| Kullanıcı | claude |
| Şifre | (config.py'da) |
| Port | 1433 |
| Driver | pytds |
| Timeout | 30 saniye (zorunlu) |
| Read Hint | `WITH(NOLOCK)` (zorunlu) |

## 2.3 Sorgu Standardı

### Zorunlu kurallar

1. **Yalnızca SELECT.** INSERT/UPDATE/DELETE Korgun'da YASAK.
2. **WITH(NOLOCK) zorunlu.** Tüm tablo isimlerinden sonra eklenecek.
3. **Timeout 30 saniye.** Daha uzun sürebilecek sorgular reddedilir.
4. **Parametre 500'lük chunk.** MSSQL'in 2100 parametre limiti için.
5. **`Urt_con_gch` ve `Urtx_con_gch` UNION ALL.** İkisi de aranmadıysa
   eksik veri olur.

### Veri çekme kuralları

| Tablo | Kullanım | Önemli Not |
|---|---|---|
| `Siparis_Kay` | Sipariş başlık | SipNo birincil anahtar |
| `Siparis_Har` | Sipariş detayı | SipNo + SKOD |
| `Urt_Emir` | Üretim emri | EmirNo ≠ SipNo |
| `Urt_Em_gch` | Emir miktar | Giren = hedef adet |
| `Urt_con_gch` | Operasyon | UNION ALL Urtx ile |
| `Urtx_con_gch` | Eski operasyon | UNION ALL Urt ile |
| `Cari_Kart` | Müşteri | CKod + CName (Cari_M DEĞİL) |
| `StokKart` | Ürün | OzKod4/5/6/11/1 attribute |
| `Proses_M` | Proses tanımı | Pro + Tanim |

## 2.4 CPS Snapshot Standardı

Korgun'dan çekilen veri **CPS DB'de snapshot** olarak tutulur:

- `uretim_kayit` tablosunda `kaynak` alanı zorunlu: `LEGACY_5055`, `CPS_CANLI`,
  `KORGUN_SNAPSHOT`, `CPS_TEST`
- `legacy_id`, `legacy_db`, `import_tarihi`, `import_hash` alanları doldurulur
- Snapshot **kopyadır**, "canlı" değildir
- CPS operasyonu (onay, atama, prim) snapshot üzerinde **kendi alanlarına** yazar
- Korgun verisi değişirse snapshot bayatlamış sayılır, yeniden çekilir

## 2.5 Hata ve Fallback

Korgun bağlantısı kopabilir (VPN, ağ, MSSQL). Modüller bu duruma hazırlıklı
olmak zorunda:

```python
try:
    veri = korgun_helper.veri_cek(...)  # 30s timeout
except (TimeoutError, pytds.Error) as e:
    log.warning(f"Korgun erisilemez: {e}")
    veri = cps_snapshot.veri_cek(...)   # CPS lokal kopya
    flash("Korgun erisilemez, kayitli snapshot gosteriliyor", "uyari")
```

**Log zorunlu.** Her Korgun bağlantı hatası `logs/cps_8080.err.log`'a yazılır.

## 2.6 Performans Sınırı

| Sorgu tipi | Maksimum | Açıklama |
|---|---|---|
| Tek sipariş detay | 100ms | Anlık sayfa açma |
| Liste (50 satır) | 500ms | KPI dashboard |
| Plan (500 sipariş) | 2 sn | Karar masası |
| Raporu (1000+) | 5 sn | Geçmiş analiz |

Bu sınırı aşan sorgular **batch işleme** veya **arka plan job**'a taşınır.

---

# 3. CPS ANALİZ STANDARDI

Her yeni işten önce **mevcut durum** mutlaka analiz edilir. "Doğrudan kod
yazma" yasak — önce kanıt toplanır.

## 3.1 Analiz Sırası (Zorunlu)

```
1. Mevcut route       ->  routes.py'da @bp.route(...) listesi
2. Mevcut DB tablo    ->  PRAGMA table_info veya sqlite3 .schema
3. Mevcut yetki       ->  sistem_yetki + sistem_rol_yetki
4. Mevcut sidebar     ->  base.html'de yetki() çağrıları
5. Mevcut log         ->  audit_log + dosya log
6. Kullanıcı etkisi   ->  hangi rol etkilenir, kaç kullanıcı
```

## 3.2 Analiz Çıktısı Formatı

Her analiz sonunda aşağıdaki tablolar üretilir:

```
A) Gerçek route listesi
B) Hangi yetki kodları kullanılıyor
C) Hangi roller geçer / geçmez
D) Bilinen sorun / açık varsa
E) Minimum güvenli müdahale önerisi
F) Patch gerekiyorsa hangi dosyalar değişecek
G) Rollback komutu
```

## 3.3 Patch Öncesi Soru Listesi

Patch yapmadan önce mutlaka cevaplanır:

1. Bu değişiklik **hangi kullanıcıları** etkiler?
2. Bu değişiklik **hangi modülleri** etkiler? (yan etki var mı?)
3. **Geri alınabilir mi?** (rollback komutu nedir?)
4. **Stable backup** alındı mı?
5. **Syntax check** + **template render check** geçti mi?
6. **Yetkili + yetkisiz** kullanıcı testi yapıldı mı?
7. **F12 Network + Console** temiz mi?

7 sorudan biri **HAYIR** ise patch yapılmaz.

## 3.4 Karışık Line-Ending Tespiti

`base.html`, `planlama/routes.py` gibi eski dosyalar **karışık line-ending**
içerebilir (CRLF + LF + CR). Bu dosyalarda patch öncesi:

```powershell
$bytes = [System.IO.File]::ReadAllBytes($src)
$cr = 0; $lf = 0
foreach ($b in $bytes) { if ($b -eq 13) {$cr++}; if ($b -eq 10) {$lf++} }
# CR == LF      -> CRLF (Windows)
# CR == 0       -> LF (Unix)
# Aksi          -> KARISIK (byte-precise patch zorunlu)
```

Karışık ise enriched anchor ile atomik str_replace kullanılır (önceki satır +
hedef satır). Tüm dosya line-ending'ini normalize etmek **YASAK** (büyük risk).

---

# 4. PATCH STANDARDI

Her kod değişikliği aşağıdaki **9 adımı** sırayla uygular. Adım atlanmaz.

## 4.1 Zorunlu Sıra

```
1. Analiz       — mevcut durum tespiti (Bölüm 3)
2. Yedek        — .YEDEK_<açıklama>_<timestamp> dosyası
3. Hash/Boyut   — patch öncesi metrik
4. Atomik patch — tek str_replace, eşsiz anchor
5. Syntax check — py_compile (Python) veya Jinja Environment (HTML)
6. Restart      — 8080 (15 saniye bekleme, debug mode çift restart)
7. Test         — yetkili + yetkisiz + admin
8. Rollback     — başarısızsa otomatik yedekten geri al
9. STABLE backup— başarı durumunda app/ + DB tam yedek
```

## 4.2 Patch Komutu Şablonu

```powershell
$ts  = Get-Date -Format "yyyyMMdd_HHmmss"
$src = "<dosya yolu>"
$bak = "$src.YEDEK_<aciklama>_$ts"

# 1) YEDEK
Copy-Item $src $bak -Force

# 2) METRIK
$hashOnce  = (Get-FileHash $src -Algorithm SHA256).Hash.Substring(0,16)
$boyutOnce = (Get-Item $src).Length

# 3) READ + REPLACE
$icerik = [System.IO.File]::ReadAllText($src, [System.Text.Encoding]::UTF8)
$eski   = "<ESSIZ ANCHOR>"
$yeni   = "<YENI ICERIK>"
$sayi   = ([regex]::Matches($icerik, [regex]::Escape($eski))).Count
if ($sayi -ne 1) { Write-Host "ESSIZ DEGIL: $sayi"; return }
$yeniIcerik = $icerik.Replace($eski, $yeni)
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($src, $yeniIcerik, $utf8)

# 4) SYNTAX
$pyc = & $PY -m py_compile $src 2>&1
if ($LASTEXITCODE -ne 0) {
    Copy-Item $bak $src -Force   # AUTO ROLLBACK
    return
}

# 5) DOGRULAMA
$icerik2 = [System.IO.File]::ReadAllText($src, [System.Text.Encoding]::UTF8)
$yeniVar = $icerik2.Contains("<yeni string parçası>")
if (-not $yeniVar) {
    Copy-Item $bak $src -Force
    return
}

# 6) RESTART
Stop-ScheduledTask -TaskName 'Solariz_CPS_8080' -TaskPath '\Solariz\'
Start-Sleep -Seconds 3
Start-ScheduledTask -TaskName 'Solariz_CPS_8080' -TaskPath '\Solariz\'
Start-Sleep -Seconds 15   # Flask debug mode çift restart

# 7) HEALTH CHECK
$r = Invoke-WebRequest -Uri "http://192.168.1.16:8080/giris" -UseBasicParsing -TimeoutSec 10
# Status 200 değilse ROLLBACK
```

## 4.3 Eşsizlik Kontrolü

Anchor pattern dosyada **birden fazla** geçiyorsa atomik patch güvensizdir.
Çözüm: enriched anchor (önceki satır + hedef satır).

```powershell
$p = "<HEDEF PATTERN>"
$sayi = ([regex]::Matches($icerik, [regex]::Escape($p))).Count
if ($sayi -ne 1) {
    # Enriched anchor dene: önceki satır + hedef
    $p_enriched = "<ONCEKI_KISIM>" + $p
    $sayi_e = ([regex]::Matches($icerik, [regex]::Escape($p_enriched))).Count
    if ($sayi_e -ne 1) {
        Write-Host "ATOMIK PATCH MUMKUN DEGIL"
        return
    }
}
```

## 4.4 Otomatik Rollback Tetikleri

Aşağıdaki durumlarda **otomatik rollback** uygulanır:

- Syntax check fail
- Doğrulama: yeni string dosyada yok
- Restart sonrası 8080 200 dönmüyor
- Jinja template render hatası (HTML patch için)
- CR/LF delta beklenenden farklı (line-ending bozulma riski)

---

# 5. UPLOAD / BELGE STANDARDI

13.05.2026'daki Samet bug'ı sonrası belge yükleme **standardize edilmiştir**.

## 5.1 Config Zorunlulukları

`config.py` içinde aşağıdaki 3 attribute **zorunlu**:

```python
class Config:
    MAX_UPLOAD_MB = 50
    ALLOWED_EXT = {
        'jpg', 'jpeg', 'png', 'webp', 'gif',
        'pdf', 'docx', 'xlsx', 'doc', 'xls'
    }
    UPLOAD_ROOT = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'uploads'
    )
```

**Eksikse:** `belge.py` AttributeError fırlatır, **tüm modüllerde** upload broken
olur. Bu hata sessiz çalışır — kullanıcıya flash mesajı görünür ama log
düşmez. Bu yüzden zorunlu.

## 5.2 Klasör Yapısı

```
app/uploads/
├── grafik/
│   ├── numune/2026/04/000003_*.jpg
│   ├── urun/2026/05/000001_*.png
│   └── tedarikci/...
├── ithalat/
│   └── parti/2026/05/...
├── cin_ofis/
│   └── _temp/*.xlsx
└── _parse_onay/
```

Klasör yapısı `belge_yukle()` tarafından **otomatik** oluşturulur:
`<modul>/<alt_modul>/<yıl>/<ay>/<kayit_id>_<dosya_ad>`

## 5.3 Yetki Kontrolü

Upload endpoint'i mutlaka yetki dekoratörü ile korunur:

```python
@grafik_bp.route('/urun/<int:urun_id>/belge/yukle', methods=['POST'])
@yetki_gerek('grafik.urun')   # <kod>.duzenle değil <kod> yeter
                              # (auth.py suffix esnemesi sayesinde)
def urun_belge_yukle(urun_id):
    return _belge_yukle_helper('grafik', 'urun', urun_id,
                                url_for('grafik.urun_detay', urun_id=urun_id))
```

## 5.4 Belge Tipleri

```python
BELGE_TIPLERI = [
    ('PROFORMA',     'Proforma Fatura'),
    ('TEKNIK_CIZIM', 'Teknik Çizim'),
    ('GORSEL',       'Görsel'),
    ('BEYANNAME',    'Gümrük Beyannamesi'),
    ('FATURA',       'Fatura'),
    ('SERTIFIKA',    'Sertifika'),
    ('DIGER',        'Diğer'),
]
```

## 5.5 Audit Log

Her başarılı upload audit'e yazılır:

```python
audit.log_ekle(
    kullanici=kullanici,
    tablo='sistem_belge',
    kayit_id=belge_id,
    aciklama=f"Belge yuklendi: {orijinal} ({belge_tipi}) - {boyut//1024} KB",
    modul=modul,
    alt_modul=alt_modul
)
```

## 5.6 Sınırlar

| Sınır | Değer |
|---|---|
| Maksimum dosya boyutu | 50 MB (Config.MAX_UPLOAD_MB) |
| İzinli uzantılar | jpg/jpeg/png/webp/gif/pdf/docx/xlsx/doc/xls |
| Klasör yazma izni | SYSTEM kullanıcısı (Task Scheduler) |
| Eşzamanlı upload | Sınırsız (Flask debug mode) |

---

# 6. GÜVENLİK STANDARDI

## 6.1 Temel İlkeler

1. **"Sidebar gizlemek güvenlik değildir."**
   Link gizleme UX'tir. Güvenlik backend'tedir.

2. **"Yetki ekranı işaretli ama menüde yok" hatası**
   Bu hata güvenlik açığı değil ama tutarsızlıktır. V2 öncesi her modülde
   bu durum düzeltilir.

3. **Backend guard zorunlu.**
   Her HTML route + kritik API'de yetki kontrolü olmalı.

4. **Hassas modüllerde çift katman.**
   Finans gibi modüllerde `@before_request` guard (modül girişi) +
   route içi yetki kontrolü.

5. **Yetkisiz URL testi zorunlu.**
   Modül canlıya alınmadan önce yetkisiz kullanıcı ile **doğrudan URL** denemesi
   yapılır. 403 dönmesi gerekir.

## 6.2 Hassas Modül Listesi

Aşağıdaki modüller **hassas** kabul edilir, `@before_request` modül guard
zorunlu:

| Modül | Sebep | Guard durumu |
|---|---|---|
| **finans** | Mali veri, alacak/borç, banka | ✅ guard mevcut (13.05) |
| **yonetim.kullanici** | Şifre yönetimi, rol atama | ⚠ V2'de eklenecek |
| **yonetim.rol** | Yetki dağıtımı | ⚠ V2'de eklenecek |
| **yonetim.log** | Audit log okuma | ⚠ V2'de eklenecek |
| **finans.cin_ofis** | Banka maliyet hesaplama | ✅ finans guard kapsamı |
| **ithalat.maliyet** | Gümrük maliyet | ⚠ V2'de eklenecek |
| **planlama.karar_masasi** | İşçi atama | Köprü guard yeterli |

## 6.3 Yetkisiz URL Testi (Penetrasyon)

Her modül canlıya alındıktan sonra **en az 3 yetkisiz rol** ile test edilir:

```
1. Yetkisiz kullanıcı sidebar'da link görüyor mu?    -> HAYIR olmalı
2. Yetkisiz kullanıcı doğrudan URL yazarsa ne olur?  -> 403 olmalı
3. Yetkisiz kullanıcı API endpoint'i çağırırsa?      -> 403 olmalı
4. Yetkisiz kullanıcı POST request gönderirse?       -> 403 olmalı
```

`/finans/`, `/yonetim/`, `/ithalat/parti/liste` gibi URL'ler **en az**
şu rollerle test edilir: samet (Grafik), mehmet (Planlama), halil (Yönetim+usta).

## 6.4 Bilgi Sızıntısı Önleme

- **Şifre/kredi kartı/banka hesabı** asla log'a yazılmaz
- **TRY tutarları >10.000.000** parser seviyesinde bloklanır
- **Yetkisiz kullanıcıya 403** verilirken **detay verilmez** ("Bu sayfaya
  erişiminiz yok" yeterli, "Bu sayfa Muhasebe rolüne özel" YOK)
- **Audit log** kritik işlemlerde **kullanıcı + zaman + IP** kaydeder

## 6.5 Şifre Politikası

| Politika | Kural |
|---|---|
| Minimum uzunluk | 6 karakter |
| Karmaşıklık | Henüz zorunlu değil |
| Zorunlu değişim | İlk girişte zorunlu (yeni kullanıcı) |
| Şifre saklama | bcrypt hash |
| Şifre logging | YASAK |

---

# 7. BİLİNEN BUG DERSLERİ (13.05.2026)

## 7.1 Finans Sızıntısı

**Durum:** Mehmet (Planlama rolü) `/finans/` URL'ini doğrudan açabiliyordu,
sidebar'da link olmamasına rağmen tüm finansal verileri görüyordu.

**Sebep:** finans/routes.py'da 32 route var, **0 tanesinde** yetki dekoratörü
yoktu. "Daha önce sadece admin/Yönetim vardı" varsayımıyla yazılmış.

**Çözüm:** `@finans_bp.before_request def _finans_modul_guard():` ile tek
guard, 32 route. Admin/Adem/Altan/Muhasebe/Finans rolü dışında 403.

**Ders:** "Sidebar'da link yok" güvenlik değildir. Backend guard zorunludur.

## 7.2 Planlama 404

**Durum:** Mehmet (Planlama rolü) `/planlama/` URL'inde 404 alıyordu.

**Sebep:** İki katman problem:
1. `base.html` L758'de Planlama menüsü `RolAd == 'Yönetim'` hardcode kilidinde
2. `planlama_bp` blueprint'inde kök route (`/`) tanımlı değildi

**Çözüm:**
1. `base.html` L758: `RolAd in ('Yönetim', 'Planlama')` atomik patch
2. `planlama/routes.py`: `@planlama_bp.route('/') def kok(): return redirect(...)`

**Ders:** Modül URL'i 404 dönüyorsa "yarın bakarız" değil — kök route standart.
Sidebar görünürlüğü ve route erişimi paralel kontrol gerektirir.

## 7.3 İthalat Sidebar Eksikliği

**Durum:** Muhasebe rolünde `ithalat.parti`, `ithalat.maliyet`, `ithalat.odeme`
yetkileri DB'de işaretli, ama sidebar'da link yoktu. Kullanıcı URL ezberlemek
zorunda kalıyordu.

**Sebep:** `base.html` L498'de "İthalat" alt başlığı vardı, altında **sadece
Çin Ofis ve Çin Sipariş** linkleri vardı. Gerçek `/ithalat/parti/liste` için
sidebar'da link yoktu.

**Ek bug:** `ithalat/routes.py`'da `url_prefix` yok, 27 route hardcode
`/ithalat/...` ile yazılmış. Bu CPS standart dışı tek modül.

**Çözüm:** `base.html` L498 sonrasına atomik str_replace ile İthalat Parti
linki eklendi. `url_prefix` refactor V2'ye bırakıldı.

**Ders:** "Yetki ekranı işaretli ama menüde yok" tutarsızlığı kullanıcı için
ezbere URL anlamına gelir, kabul edilemez.

## 7.4 Samet Upload Bug

**Durum:** Samet (Grafik rolü) numune/ürün görselini yükleyemiyordu.
Flash mesajı: `"type object 'Config' has no attribute 'ALLOWED_EXT'"`

**Sebep:** `config.py`'da `ALLOWED_EXT` ve `UPLOAD_ROOT` attribute'leri tanımlı
değildi. `belge.py` bunları `Config.ALLOWED_EXT` ile çağırınca AttributeError
fırlatıyordu. Mevcut numune dosyaları **23-26 Nisan**'da yüklenmişti — yani
yaklaşık 2-3 hafta önce config silinmişti, **herkesin** upload'ı broken'mıştı.

**Çözüm:** `config.py`'ya 2 satır:
```python
ALLOWED_EXT = {'jpg','jpeg','png','webp','gif','pdf','docx','xlsx','doc','xls'}
UPLOAD_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
```

**Ders:** Tek kullanıcı şikayeti gelse bile, problem **herkesi** etkileyen
sistem seviyesinde olabilir. Yetkili kullanıcı (admin) test etmeyince fark
edilmedi. Modül bazlı düzenli **smoke test** lazım.

## 7.5 base.html Line-Ending Riski

**Durum:** `base.html` karışık line-ending kullanıyor: CR=2503, LF=2910.
Bazı bölgeler CRLF, bazıları LF, bazıları sadece CR.

**Sebep:** Dosya yıllar içinde birden fazla editörde kaydedilmiş, line-ending
karışmış. Sabah erken patch'te (sidebar yorumu) bu yüzden Jinja parse hatası
yaşandı.

**Çözüm:** Her base.html patch'inde:
1. Hedef satırın **bayt seviyesinde** byte hex dump alınır
2. CRLF/LF varyantları **ayrı ayrı** denenir
3. Enriched anchor kullanılır (eşsizlik)
4. Patch sonrası CR/LF delta kontrol edilir, dengesizlik rollback tetikler

**Ders:** Karışık line-ending dosyalar **bilinçli olarak** korunur. Bütün
dosyayı LF veya CRLF'e normalize etmeye çalışmak büyük risk.

## 7.6 Jinja yetki() / auth.py Ayrımı

**Durum:** Sidebar'da `{% if yetki('finans') %}` çağrısı bekleniyor şekilde
çalışmıyordu. Yetki DB'de işaretli ama Jinja False döndürüyordu.

**Sebep:** İki katman problem:
1. `auth.py` `kullanici_yetkileri()` set'e `.goruntule` suffix ekliyordu
   (`finans.goruntule`), ama `yetki_var()` sadece tam eşleme yapıyordu.
2. `app.py` context_processor Jinja'ya **kendi lambda'sını** geçiriyordu,
   `yetki_var()` bypass ediliyordu.

**Çözüm:**
1. `auth.py` `yetki_var()`: `kod` yoksa `kod + '.goruntule'` da kontrol et
2. `app.py` L109: lambda yerine `'yetki': yetki_var` referansı

**Ders:** Aynı fonksiyon ismi farklı yerlerde farklı tanımlanmış olabilir.
"Yetki çalışmıyor" diyorsa **tüm yetki katmanları** sırayla incelenmeli:
DB -> auth.py -> app.py context_processor -> Jinja kullanımı.

---

# 8. V2 HEDEFİ — YETKİ SİSTEMİ V2

Yetki Sistemi V2'nin başlama tarihi henüz belirlenmedi. Köprü dönem
patch'leri stabil çalıştığı sürece V2 acele edilmeyecek.

## 8.1 V2'nin Temel Farkları

| Özellik | Köprü (v1) | V2 |
|---|---|---|
| Yetki kaynağı | Hardcode rol whitelist + sistem_yetki | Sadece sistem_yetki |
| Sidebar üretimi | Manuel HTML | Otomatik (yetki tablosundan) |
| Modül guard | Karışık (dekoratör/before_request/hardcode) | Tek format: `@yetki_gerekli` |
| Rol matrisi | Statik (8 rol) | Dinamik (kullanıcı tanımlı) |
| Yetki kodu sayısı | ~30 | ~200+ (sekme/işlem/proses bazlı) |
| Audit zorunluluk | Tavsiye | Tüm CRUD'de zorunlu |

## 8.2 V2 Yetki Türleri

### Sekme bazlı yetki

```
hedef.tab.plan.goruntule
hedef.tab.sapma.goruntule
hedef.tab.onaylar.goruntule
hedef.tab.gecmis.goruntule
```

Her sekme ayrı yetki. Kullanıcı sekmeleri tek tek görür/görmez.

### İşlem bazlı yetki

```
hedef.plan.olustur
hedef.plan.duzenle
hedef.plan.sil
hedef.plan.export
hedef.plan.import
```

Aksiyonlar ayrı ayrı işaretlenir. "Sil" yetkisi olmadan görüntüleyen rol.

### Proses bazlı yetki

```
uretim.proses.26.giris    # Enjeksiyon proses girişi
uretim.proses.30.giris    # Monta proses girişi
uretim.proses.35.giris    # Temizleme proses girişi
```

Halil sadece Regola için, Ferhat sadece Enjeksiyon için. Saha personeli kendi
prosesine giriş yapar.

### Personel/Usta/Alt proses yetkisi

```
personel.kendi_kayit.goruntule    # Kendi üretimini görür
personel.kendi_prim.goruntule     # Kendi primini görür
usta.atadigi.goruntule            # Atadığı personelin işini görür
usta.atadigi.onayla               # Atadığı personelin işini onaylar
```

### Modül x Lokasyon kombinasyonu

```
uretim.lokasyon.SA001.goruntule   # SA001 monta hattı
uretim.lokasyon.SU001.goruntule   # SU001 enjeksiyon
```

## 8.3 V2 Geçiş Adımları

1. **Tüm sistem_yetki kodları seed**: ~200 kod tanımlanır, Açıklama dolu
2. **Rol matrisi seed**: 8 köprü rolün her yetki için Görebilir/Düzenleyebilir
3. **Tüm modüllerde `@yetki_gerekli` ekleme**: Hardcode dekoratörler kaldırılır
4. **Sidebar dinamik üretim**: `base.html` Jinja loop ile yetki tablosundan
5. **UI panel**: Yetki Yönetimi ekranında 200 yetki kodu görünür hale gelir
6. **Audit zorunluluk**: Tüm INSERT/UPDATE/DELETE audit'e yazar
7. **Köprü kod temizliği**: hardcode `RolAd == 'X'` kontrolleri kaldırılır

## 8.4 V2 Audit Zorunluluğu

V2'de tüm aşağıdaki işlemler audit_log'a yazılır:

- Kullanıcı login/logout
- Şifre değişikliği
- Rol/yetki atama-kaldırma
- Tüm CRUD işlemleri (INSERT/UPDATE/DELETE)
- Belge yükleme/silme
- Onay/red işlemleri
- Export işlemleri
- Yetkisiz erişim denemesi (403)

Audit log retention süresi: **2 yıl** (Korgun standartına uyumlu).

---

# 9. CHANGELOG

| Sürüm | Tarih | Değişiklik | Yapan |
|---|---|---|---|
| **v1** | 13.05.2026 | İlk sürüm. Bugünkü 14 patch sonrası resmî karar. Bölüm 1-8 oluşturuldu. | Adem TERZİ |

---

**Doküman sahibi:** Adem TERZİ (Solariz Terlik)
**Geliştirme ortağı:** AI asistan (Claude)
**Bu sürüm köprü dönem için geçerlidir.**
**Yetki Sistemi V2 yayınında v2 dokümanı çıkacak ve bu sürüm**
**`docs/archive/`'e taşınacak.**
