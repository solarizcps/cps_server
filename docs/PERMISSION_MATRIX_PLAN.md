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
   - Sonuc NULL ise veya kayit yoksa: Adim C'ye geç

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

## 16. Geliþtirici Standardi Vurgu

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