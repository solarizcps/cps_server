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
