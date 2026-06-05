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

