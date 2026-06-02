# MODULE_REGISTRY_PLAN

Belge tipi: Cekirdek mimari freeze
Tarih: 2026-05-15 (gece)
Snapshot referansi: STABLE_OP_RAPOR_V2_GECMIS_DONE_20260515_161612
Durum: FREEZE - patch yok, implementasyon yarin sonrasi

---

## 1. Amac ve Felsefe

module_registry, CPS'in TEK modul kayit yeridir.

Her modul (sayfa, blueprint, sekme, ozellik) burada kaydedilmelidir.
Burada kaydi olmayan modul:
- Sidebar'da gozukmez
- Yetki sisteminde gozukmez
- @yetki_gerek decorator'u calismaz
- Yonetim > Yetkiler ekraninda gozukmez
- Audit log'da modul olarak gozukmez

ANAYASA KURALI:
Yeni modul yazilmadan ONCE module_registry kaydi olusturulmalidir.
Kayit yoksa kod yazma engellenir.

---

## 2. Mevcut Sistemde Modul Kavrami (Recon Bulgu)

Mevcut durum:
- DB'de modul tablosu YOK
- Sidebar/menu tamamen base.html icinde hardcoded
- sistem_yetki.Modul + AltModul zaten dot-notation kullaniyor
- base.html'de active anahtarlari: home, tasks, finans, grafik, hedef, planlama, yonetim
- 14 Flask blueprint, 55 HTML sayfa, 240 endpoint
- Menu gruplari (gorsel baslik) tespit edilemedi - tek liste yapida

Mevcut sistem_yetki.Modul degerleri:
- finans (10 yetki)
- grafik (12 yetki)
- ithalat (3 yetki)
- yonetim (4 yetki)
- nakit (1 yetki)

Eksik (yetki kodu olmayan) blueprintler:
- enjeksiyon, hedef, planlama, tasks, personel_giris
- uretim_giris, uretim_yonetim, usta, canli_saha

Cikarim: V2'de sistem_yetki.Modul/AltModul standardini KORUYUYORUZ.
module_registry ile uyumlu olacak. Eski modul kodlari boyle kalir.
Yeni 9 modulun kodlari bu standart ile eklenecek.

---

## 3. Tablo Semasi - module_registry

CREATE TABLE module_registry (
    module_key       TEXT PRIMARY KEY,
    module_name      TEXT NOT NULL,
    module_desc      TEXT,
    parent_key       TEXT,
    menu_group       TEXT,
    icon             TEXT,
    url              TEXT,
    active_key       TEXT,
    sira             INTEGER DEFAULT 100,
    is_active        INTEGER DEFAULT 1,
    is_hidden        INTEGER DEFAULT 0,
    is_system        INTEGER DEFAULT 0,
    permission_key   TEXT,
    blueprint        TEXT,
    ozellikler       TEXT,
    olusturma_tarih  TEXT DEFAULT (datetime('now')),
    olusturan        TEXT,
    FOREIGN KEY (parent_key) REFERENCES module_registry(module_key)
);

CREATE INDEX idx_mreg_parent  ON module_registry(parent_key);
CREATE INDEX idx_mreg_group   ON module_registry(menu_group);
CREATE INDEX idx_mreg_active  ON module_registry(is_active, is_hidden);
CREATE INDEX idx_mreg_perm    ON module_registry(permission_key);

---

## 4. Alan Aciklamalari

| Alan | Tip | Zorunlu | Aciklama |
|------|-----|---------|----------|
| module_key | TEXT | EVET | Dot-notation unique anahtar. Ornek: enjeksiyon.saha |
| module_name | TEXT | EVET | Insan okur ad. Sidebar/UI'da gosterilir |
| module_desc | TEXT | HAYIR | Detayli aciklama (tooltip, yetki ekraninda) |
| parent_key | TEXT | HAYIR | Ust modul. NULL = root modul |
| menu_group | TEXT | EVET | Sidebar grup adi. Uretim/Finans/Yonetim |
| icon | TEXT | HAYIR | Lucide icon adi. Ornek: tool, target, shield |
| url | TEXT | HAYIR | Link adresi. NULL ise tiklanabilir degil |
| active_key | TEXT | HAYIR | base.html'deki active degiskeni esleyici |
| sira | INTEGER | HAYIR | Sidebar sirasi. Dusukten yuksek |
| is_active | INTEGER | EVET | 1 = aktif, 0 = pasif |
| is_hidden | INTEGER | HAYIR | 1 = admin'e bile gozukmez |
| is_system | INTEGER | HAYIR | 1 = cekirdek modul, silinemez |
| permission_key | TEXT | HAYIR | sistem_yetki.Kod ile baglar |
| blueprint | TEXT | HAYIR | Flask blueprint adi |
| ozellikler | TEXT | HAYIR | JSON ek alan. Esnek genisleme icin |

---

## 5. module_key Standardi (Naming Convention)

DURUM: sistem_yetki.Kod zaten dot-notation. AYNISINI kullaniriz.

Format: root.alt.altin_alti

Kurallar:
1. Kucuk harf, alt cizgi yerine kisa kelimeler tercih edilir
2. Maksimum 3 seviye. 4. seviye yasak.
3. ASCII karakter. Turkce karakter yasak.
4. Bosluk, tire, ozel karakter yasak.
5. Tekil olmali (singular). urunler degil urun.

Iyi ornek:
- enjeksiyon
- enjeksiyon.saha
- enjeksiyon.yonetim
- finans.anlasma
- finans.anlasma.sil
- yonetim.kullanici
- yonetim.rol

Kotu ornek:
- enjeksiyon-saha [tire kullanilamaz]
- enjeksiyon.saha.ekrani.aktif [4 seviye, yasak]
- Enjeksiyon.Saha [buyuk harf, yasak]
- urunler [cogul, yasak]

---

## 6. Group / Parent Hierarchy

Iki katmanli iliski:

### 6.1 menu_group (Yatay sidebar grubu)

Sidebar'da gorsel basliklara karsilik gelir.

| Grup | Iceren modul (ornek) |
|------|----------------------|
| Ozet | home, tasks |
| Uretim | hedef, enjeksiyon, personel_giris, usta |
| Planlama | planlama.proses_takip, planlama.karar_masasi, planlama.operasyon_raporu |
| Finans | finans.*, nakit.* |
| Grafik | grafik.* |
| Ithalat | ithalat.* |
| Yonetim | yonetim.* |

Mevcut base.html'de gorsel grup baslik yok ama mantiken bu gruplara
ayrilmis. V2'de eklenecek gorsel grup baslik (kucuk metin).

### 6.2 parent_key (Dikey modul agaci)

Dot-notation ile zaten implicit hiyerarsi var. parent_key explicit yapar.

| module_key | parent_key |
|------------|------------|
| finans | NULL |
| finans.anlasma | finans |
| finans.anlasma.sil | finans.anlasma |
| enjeksiyon | NULL |
| enjeksiyon.saha | enjeksiyon |
| enjeksiyon.yonetim | enjeksiyon |

Bu agac yapisi:
- Yetki kalitma kullanilabilir (root yetkisi varsa altlari da)
- Sidebar render'da accordion / collapse mantigi
- Audit log'da modul-bazli filtreleme

---

## 7. Hidden / System / Active State Mantigi

3 bayrak, 3 farkli kullanim.

### 7.1 is_active (1 / 0)

Modul tamamen kapatilabilir. 0 olunca:
- Sidebar'da gozukmez (admin'e dahi)
- @yetki_gerek decorator 404 doner (sanki yok)
- Yetki ekraninda gri/silik gosterilir

Kullanim ornegi: uretim_giris (eski modul) is_active=0 yapilabilir, kod kalir.

### 7.2 is_hidden (1 / 0)

Gelistirme asamasindaki modul. 1 olunca:
- Sadece SuperAdmin'lere gozukur
- Sidebar'da beta/gelistirme badge ile
- @yetki_gerek calisir ama yalniz SuperAdmin gecer

Kullanim ornegi:
- Yeni yazilan modul once is_hidden=1 ile baslar
- Test bitince is_hidden=0 yapilir

### 7.3 is_system (1 / 0)

Cekirdek modul koruma bayragi. 1 olunca:
- DELETE yasak (yonetim/UI'dan silinemez)
- module_key degisikligi yasak
- is_active=0 yapilamaz

Sistem modulleri:
- home
- auth
- yonetim
- yonetim.kullanici
- yonetim.rol
- yonetim.log

### 7.4 State Matrisi - Hangi durumda kim gorur?

| is_active | is_hidden | Normal user | Admin | SuperAdmin |
|-----------|-----------|-------------|-------|------------|
| 1 | 0 | Yetki varsa gorur | Gorur | Gorur |
| 1 | 1 | GIZLI | GIZLI | Gorur |
| 0 | 0 | GIZLI | GIZLI | GIZLI |
| 0 | 1 | GIZLI | GIZLI | GIZLI |

---

## 8. Sidebar Mapping (Registry -> Menu)

Yeni mantik:

base.html cagrir:
  sidebar_render(user)

sidebar_render() yapar:
1. module_registry SELECT (is_active=1 AND is_hidden=0)
2. permission_key NULL veya yetki(permission_key) True olanlari al
3. menu_group bazinda grupla
4. parent_key/sira'ya gore sirala
5. Render: grup baslik + tek tek modul linkleri

ESKI hardcoded sidebar tamamen kaldirilacak.
base.html'deki 150+ "if RolAd == X" bloklari silinir.
Sadece 1 cagri kalir.

---

## 9. Route Relation (Registry -> URL)

module_registry.url 4 farkli sekilde kullanilabilir:

| Tip | Ornek | Anlami |
|-----|-------|--------|
| Tam URL | /enjeksiyon/saha | Statik link |
| Endpoint name | enjeksiyon.saha_index | Flask url_for |
| NULL | (bos) | Tiklanmaz modul (sadece grup basligi) |
| Disabled | javascript:void(0) | Placeholder |

blueprint kolonuyla Flask blueprint'ine bagli:
- Audit log'da modul tespiti icin
- Endpoint -> module_key reverse lookup icin
- @yetki_gerek decorator otomatik module_key cikartmak icin

---

## 10. Permission Dependency (Registry -> Permission)

module_registry.permission_key sistem_yetki.Kod ile birebir eslesir.

Pattern:
- module_registry.module_key = enjeksiyon.saha
- sistem_yetki.Kod = enjeksiyon.saha
- Ayni string, iki tabloda

Avantaj:
- Modul yaratirken auto-create permission
- @yetki_gerek('enjeksiyon.saha') hem registry hem permission'da arar
- Yetki ekraninda modul tablosu = permission tablosu uyumlu

Trigger yazilabilir (opsiyonel, V2 sprint 2'de):
- INSERT INTO module_registry -> ayni Kod ile INSERT INTO sistem_yetki

---

## 11. Ilk Seed Verisi (32 modul)

Patch sirasinda yapilacak INSERT'ler:

| module_key | module_name | menu_group | url | parent_key | is_system |
|------------|-------------|------------|-----|------------|-----------|
| home | Ana Sayfa | Ozet | / | NULL | 1 |
| tasks | Gorevler | Ozet | /tasks | NULL | 0 |
| hedef | Hedef Yonetimi | Uretim | /hedef/ | NULL | 0 |
| hedef.sablon | Sablon / Proses | Uretim | /hedef/sablon | hedef | 0 |
| hedef.sapma | Sapma Analizi | Uretim | /hedef/sapma | hedef | 0 |
| enjeksiyon | Enjeksiyon Takip | Uretim | /enjeksiyon/ | NULL | 0 |
| enjeksiyon.saha | Saha Ekrani | Uretim | /enjeksiyon/saha | enjeksiyon | 0 |
| enjeksiyon.yonetim | Yonetim Paneli | Uretim | /enjeksiyon/ | enjeksiyon | 0 |
| personel_giris | Uretim Girisi | Uretim | /personel-giris/ | NULL | 0 |
| usta | Usta Paneli | Uretim | /usta/ | NULL | 0 |
| canli_saha | Canli Saha (5055) | Uretim | /canli-saha/ | NULL | 0 |
| planlama | Planlama | Planlama | /planlama/ | NULL | 0 |
| planlama.proses_takip | Proses Takip | Planlama | /planlama/proses-takip | planlama | 0 |
| planlama.karar_masasi | Karar Masasi | Planlama | /planlama/karar-masasi | planlama | 0 |
| planlama.operasyon_raporu | Operasyon Raporu | Planlama | /planlama/operasyon-raporu | planlama | 0 |
| finans | Finans | Finans | /finans/ | NULL | 0 |
| finans.anlasma | Anlasmalar | Finans | /finans/anlasma | finans | 0 |
| finans.cari | Cari Hesaplar | Finans | /finans/cari | finans | 0 |
| finans.simulator | Maliyet Simulator | Finans | /finans/simulator | finans | 0 |
| finans.cin_ofis | Cin Ofis Import | Finans | /finans/cin-ofis | finans | 0 |
| grafik | Grafik Paneli | Grafik | /grafik/ | NULL | 0 |
| grafik.urun | Urun Yonetimi | Grafik | /grafik/urun | grafik | 0 |
| grafik.numune | Numune Takip | Grafik | /grafik/numune | grafik | 0 |
| grafik.tedarikci | Tedarikciler | Grafik | /grafik/tedarikci | grafik | 0 |
| grafik.siparis | Cin Siparis | Grafik | /grafik/siparis | grafik | 0 |
| grafik.sevkiyat | Sevkiyat & Maliyet | Grafik | /grafik/sevkiyat | grafik | 0 |
| ithalat.parti | Ithalat Parti | Ithalat | /ithalat/parti/liste | NULL | 0 |
| yonetim | Yonetim Paneli | Yonetim | /yonetim/ | NULL | 1 |
| yonetim.kullanici | Kullanicilar | Yonetim | /yonetim/kullanici | yonetim | 1 |
| yonetim.rol | Roller & Yetkiler | Yonetim | /yonetim/rol | yonetim | 1 |
| yonetim.kur | Kur Tanimlari | Yonetim | /yonetim/kur | yonetim | 0 |
| yonetim.log | Audit Log | Yonetim | /yonetim/log | yonetim | 1 |
| yonetim.proses_kategori | Proses Tanimlari | Yonetim | /yonetim/proses-kategori | yonetim | 0 |

Toplam: 32 modul ilk seed'de.

---

## 12. Migration Sirasi (Patch Adimlari)

Bu plani uygulamak icin sira:

| Adim | Yapilacak | Aciklama |
|------|-----------|----------|
| M1 | Snapshot | STABLE_YETKI_V2_PRE_PATCH_<ts> |
| M2 | Migration script | app/migrations/003_module_registry.py - CREATE TABLE + index |
| M3 | Seed verisi | app/migrations/004_module_registry_seed.py - 30 INSERT |
| M4 | sistem_yetki uyumlu | Eski yetki kayitlarini permission_key ile baglat |
| M5 | Helper fonksiyonlar | modules/auth.py icine modul_listesi, sidebar_render |
| M6 | Test (yarin sonrasi) | USE_V2_SIDEBAR flag ile paralel, eski sistem bozulmasin |
| M7 | Production switch | USE_V2_SIDEBAR=True, eski sidebar kodu 1-2 hafta sonra silinir |
| M8 | Snapshot | STABLE_YETKI_V2_REGISTRY_DONE_<ts> |

---

## 13. Continuation - Yarin Nereden Devam

Bu doku FREEZE durumda. Patch baslamadi.

Yarin Ferhat saha testi bittikten sonra:
1. Bu doku tekrar okunur (15 dakika)
2. Adem onayi alinir (degisiklik var mi?)
3. PERMISSION_MATRIX_PLAN.md de okunur (yazilirsa)
4. PERSONEL_IK_OMURGA_PLAN.md de okunur (yazilirsa)
5. Hepsi tamam ise patch baslar (M1-M8)

Eger bu doku yarin degisecekse:
- Once degisiklik nedeni docs/MODULE_REGISTRY_PLAN_CHANGELOG.md'ye yazilir
- Sonra bu doku v2 olarak yenilenir
- Eski versiyon yedek kalir

---

## 14. Diger Belgelerle Iliski

Bu doku ana referans. Yan dokulerle bagi:

| Belge | Durum | Konu |
|-------|-------|------|
| YETKI_SISTEMI_V2_ANALIZ.md | YAZILDI | 6 tablolu envanter, 11 adimli migration, 12 acik |
| MODULE_REGISTRY_PLAN.md | BU DOKU | Modul kayit standardi (freeze) |
| PERMISSION_MATRIX_PLAN.md | SIRADA | 7 boyutlu yetki, override, decorator, 403 fallback |
| PERSONEL_IK_OMURGA_PLAN.md | RECON BEKLIYOR | Kisi karti, hiyerarsi, aktivite, yildiz, maas |
| HARDCODE_YETKI_RECON.md | SIRADA | 150+ hardcoded RolAd kontrolu liste |

---

## 15. Anayasa Tekrar Vurgusu

YENI MODUL YAZMA KURALI (degismez):

| Adim | Aksiyon | Atlanirsa |
|------|---------|-----------|
| 1 | module_registry'e INSERT (is_hidden=1) | HER SEY DURACAK |
| 2 | sistem_yetki'ye INSERT | Yetki kontrolu calismayacak |
| 3 | sistem_rol_yetki'ye INSERT | Hicbir kullanici giremez |
| 4 | Blueprint yazilir (@yetki_gerek zorunlu) | REJECT |
| 5 | Sidebar otomatik gosterilir (sidebar_render) | Manuel HTML eklendi ise SIL |
| 6 | Test (is_hidden=1 ile sadece superadmin gorur) | Test atlanamaz |
| 7 | is_hidden=0 yapilir | Onay sonrasi |

---

## 16. Belge Surumu

| Surum | Tarih | Aciklama |
|-------|-------|----------|
| v1 | 2026-05-15 | Cekirdek mimari freeze (patch yok) |

Sonraki surumde patch sonucu eklenir (M1-M8 tamamlandiginda).