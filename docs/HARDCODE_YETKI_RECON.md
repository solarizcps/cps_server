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