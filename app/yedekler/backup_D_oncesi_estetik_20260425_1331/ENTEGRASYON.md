# CPS Faz 1 — Entegrasyon ve Kurulum

## İçindekiler

1. Hızlı Başlangıç (Notebook / Mock)
2. Prod Deployment (192.168.1.16)
3. Klasör Yapısı
4. Yetki Sistemi Özet
5. Kur ve Belge Servisi Kullanımı
6. Audit Log
7. Sorun Giderme

---

## 1. Hızlı Başlangıç (Notebook / Mock)

```cmd
cd C:\cps_dev
python init_mock_db.py
python app.py
```

Tarayıcı: `http://127.0.0.1:5057/`

**Giriş:**
- `admin` / `admin123` (Yönetim — tam yetki)
- `halil` / `232323` (Yönetim)
- `hasan` / `323232` (Yönetim)
- `samet` / `434343` (Grafik)
- `cin.ofis` / `Cin2026!` (Çin Ofis — ilk girişte şifre değişir)
- `muhasebe` / `Muh2026!` (Muhasebe — ilk girişte şifre değişir)

`BASLA.bat` dosyasını çift tıklayarak da başlatabilirsiniz (mock mode default).

---

## 2. Prod Deployment (192.168.1.16)

### 2.1 Dosyaları kopyala

`C:\cps_dev\` klasörünü sunucuda `D:\Firma_Ozel\adem\cps\` altına kopyalayın (veya Task Scheduler'daki mevcut port 5057 dizinine).

### 2.2 MSSQL Migration

```cmd
set CPS_DB_MODE=prod
python migration_v2.py
```

Migration güvenlidir: `IF NOT EXISTS` pattern kullanılır, zaten var olan tabloları dokunmaz, sadece eksikleri ekler.

**Eklenen tablolar:**
- `sistem_rol`, `sistem_yetki`, `sistem_rol_yetki`
- `sistem_kullanici` (varsa eksik kolonlar eklenir: Email, RolId, ZorunluSifreDegistir, SonGirisTarih)
- `sistem_audit` (varsa Modul + AltModul + IpAdresi kolonları eklenir)
- `sistem_kur`, `sistem_belge`
- `finans_anlasma`, `finans_anlasma_model`, `finans_avans`, `finans_avans_mahsup`, `finans_odeme_plan`, `finans_odeme_cek`

### 2.3 İlk yönetici kullanıcı

Migration sonrası sistem_kullanici boşsa:

```sql
INSERT INTO sistem_kullanici
  (KullaniciAdi, Sifre, AdSoyad, RolId, Rol, Aktif, ZorunluSifreDegistir)
VALUES
  ('admin', 'Geçici123!', 'Sistem Yöneticisi',
   (SELECT Id FROM sistem_rol WHERE Ad='Yönetim'), 'Yönetim', 1, 1)
```

İlk girişte şifre değiştirilecektir.

### 2.4 Task Scheduler

Mevcut `Planlama_CPS` task'ı port 5057 üzerinden çalışıyorsa, `app.py` bu portu zaten kullanır. Değişiklik yok.

**Başlatma komutu (elle):**
```cmd
set CPS_DB_MODE=prod
C:\Users\Administrator\AppData\Local\Programs\Python\Python315\python.exe D:\Firma_Ozel\adem\cps\app.py
```

### 2.5 Uploads klasörü

Prod'da `D:\Firma_Ozel\adem\cps\uploads\` oluşturulmalı ve Python sürecinin yazma hakkı olmalı. İç yapı kendi kendine oluşur: `uploads/<modul>/<alt_modul>/<yyyy>/<mm>/...`

---

## 3. Klasör Yapısı

```
cps_dev/
├── app.py                      # Ana Flask uygulaması — tüm blueprint'ler burada register
├── config.py                   # Ortam değişkenleri (DB_MODE, MSSQL creds, UPLOAD_ROOT vb.)
├── db.py                       # DB soyutlaması (SQLite/MSSQL dual mode)
├── init_mock_db.py             # Mock DB kurulum + seed
├── migration_v2.py             # Prod MSSQL Faz 1 migration
├── BASLA.bat                   # Başlatma batch
├── requirements.txt
├── mock_data.db                # SQLite veri (dev)
│
├── modules/
│   ├── audit.py                # Audit log API (log_ekle / log_duzenle_coklu / log_olay / son_loglar)
│   ├── auth.py                 # Login, yetki kontrolü (yetki_var + yetki_gerekli decorator)
│   ├── belge.py                # Dosya yükleme/indirme/silme servisi
│   │
│   ├── finans/                 # Finans v2 (anlaşma, plan, çek, avans, cari)
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   └── queries.py
│   │
│   ├── grafik/                 # Faz 2 için rezerv (numune, cin, maliyet, analiz, urun, tedarikci)
│   │   └── ...
│   │
│   └── yonetim/                # Faz 1 — yönetim paneli
│       ├── __init__.py         # yonetim_bp export
│       ├── routes.py           # /yonetim/* endpoint'leri
│       └── queries.py          # DB sorguları
│
├── templates/
│   ├── base.html               # Ana layout + menü
│   ├── giris.html
│   ├── index.html
│   ├── hata.html               # 403/404/500
│   ├── sifre_degistir.html
│   │
│   ├── finans/                 # Finans template'leri
│   │   └── ...
│   │
│   └── yonetim/                # Yönetim template'leri
│       ├── panel.html          # 5 KPI + son 20 log
│       ├── kullanici_liste.html
│       ├── rol_liste.html
│       ├── rol_detay.html      # Yetki matrisi (modül gruplamalı)
│       ├── kur_liste.html      # USD/EUR/CNY kartları + son 120 kur
│       └── log_liste.html      # Filtreli audit log
│
├── static/
│   └── css/
│       └── style.css           # Tüm CSS — Solariz orange + navy + Segoe UI
│
└── uploads/                    # Belge depolama (auto-created)
    └── <modul>/<alt_modul>/<yyyy>/<mm>/
```

---

## 4. Yetki Sistemi Özet

### 4.1 Modeller

- **Rol** (`sistem_rol`) — Yönetim, Muhasebe, Çin Ofis, Gümrük, Grafik, Personel
- **Yetki** (`sistem_yetki`) — `finans.anlasma`, `grafik.cin.fiyat`, `yonetim.kur` gibi kodlar (20 adet)
- **Rol-Yetki Matrisi** (`sistem_rol_yetki`) — Her rol için her yetkiye `Gorebilir` + `Duzenleyebilir` iki checkbox

### 4.2 Kontrol

Python kodunda:

```python
from modules.auth import yetki_var, yetki_gerekli

# Template'de veya view'da
if yetki_var('finans.anlasma.duzenle'):
    ...

# Route decorator
@yetki_gerekli('grafik.cin.goruntule')
def liste():
    ...
```

Template'de:

```jinja
{% if 'finans.anlasma.duzenle' in g.yetkiler %}
  <button>Düzenle</button>
{% endif %}
```

### 4.3 SuperAdmin

`sistem_rol.SuperAdmin = 1` olan roller (Yönetim) tüm yetkilere otomatik sahip olur — `yetki_var` her zaman `True` döner.

### 4.4 UI'dan Yönetim

`/yonetim/rol/<id>` ekranında modül bazlı gruplanmış yetki matrisi. Her satırda iki checkbox: Görebilir / Düzenleyebilir. Kaydet'e basınca:
- Eski yetkiler silinir (transaction içinde)
- Yeni seçimler yazılır
- Audit log'a tek satır: `"<Rol> rolünün yetkileri güncellendi (N değişiklik)"`

---

## 5. Kur ve Belge Servisi

### 5.1 Kur

```python
from modules.yonetim import queries as yqr

# Son kur
usd = yqr.kur_guncel('USD')         # → {Alis, Satis, MerkezKur, Tarih, ...}

# Yeni kur (aynı gün+PB varsa günceller)
yqr.kur_ekle('2026-04-25', 'USD', 39.40, 39.65, kullanici='admin')

# Tarihe göre
yqr.kur_tarihli('2026-04-20', 'EUR')
```

UI: `/yonetim/kur` — yeni kur formu + son 120 kayıt tablosu + bugünkü USD/EUR/CNY kartları.

### 5.2 Belge

```python
from modules import belge

# Yükle (Flask request.files['dosya'] ile)
belge_id = belge.belge_yukle(
    modul='grafik', alt_modul='numune',
    kayit_id=123,
    dosya_storage=request.files['dosya'],
    belge_tipi='TEKNIK_CIZIM',
    kullanici='samet',
)

# Listele
dosyalar = belge.belge_liste('grafik', 'numune', 123)

# İndir (route)
# GET /yonetim/belge/<belge_id>
```

**Güvenlik:**
- İzinli uzantılar: `pdf, jpg, jpeg, png, webp, gif` (`config.py` > `ALLOWED_EXT`)
- Max boyut: 20 MB (`MAX_UPLOAD_MB`)
- Dosya adı `werkzeug.secure_filename` ile temizlenir
- Disk yolu: `uploads/<modul>/<alt_modul>/<yyyy>/<mm>/<kayit_id>_<dosyaad>.ext`
- İndirme yetkisi: `belge.indir.goruntule` VEYA kaynak modülün `<modul>.<alt_modul>.goruntule` yetkisi

---

## 6. Audit Log

Her yazma işlemi audit log'a düşer. `modules/audit.py`:

```python
from modules import audit

# Basit log
audit.log(kullanici='admin', islem='EKLE', tablo='finans_anlasma',
          kayit_id=5, modul='finans', alt_modul='anlasma',
          aciklama='Yeni anlaşma: LCW-2026-OKUL')

# Ekleme için kısayol
audit.log_ekle('admin', 'sistem_kullanici', 7, aciklama='Kullanıcı eklendi: test.user',
               modul='yonetim', alt_modul='kullanici')

# Alan bazlı değişiklik logu (her alan için ayrı satır)
audit.log_duzenle_coklu('admin', 'finans_anlasma', 5,
                        eski_dict, yeni_dict,
                        modul='finans', alt_modul='anlasma')

# Sorgulama
audit.son_loglar(limit=50, modul='finans')
audit.log_kayit_detay('finans_anlasma', 5)
```

UI: `/yonetim/log` — filtre (modül/alt-modül/kullanıcı/işlem/tarih aralığı).

---

## 7. Sorun Giderme

### Port 5057 başka bir process'te

```cmd
netstat -ano | findstr :5057
taskkill /PID <pid> /F
```

Server sık sık eski PID bırakıyorsa, `BASLA.bat` içine `taskkill /FI "WINDOWTITLE eq CPS Dev Server" /F` eklenebilir.

### MSSQL bağlantı hatası

- `Config.MSSQL_HOST = '192.168.1.16'` — notebook'tan çalışırken `'SOLARIZDB'` veya `'192.168.1.16'` ping atılabilir mi?
- `pytds` paketi kurulu mu? `pip install python-tds`
- Kullanıcı `claude` / `104099` hâlâ geçerli mi? `SELECT @@VERSION` ile test.

### "no such column" hatası (mock)

Schema'da yeni bir kolon eklendi ama DB eski versiyonda kaldı:

```cmd
del mock_data.db
python init_mock_db.py
```

### Import hatası

`__pycache__` önbelleği bozulmuş olabilir:

```cmd
rmdir /s /q __pycache__ modules\__pycache__ modules\yonetim\__pycache__
```

### Yetki ekranında değişiklik yapamıyorum

- Kendi rolünüz `Yönetim` (SuperAdmin) mı? Başka rolde iseniz `yonetim.rol.duzenle` yetkiniz var mı?
- Mock mode'da `admin/admin123` ile giriş yapın.

---

## Değişiklik Kayıtları

### v2.0 — Faz 1 (Nisan 2026)

- Yetki sistemi (Rol + Yetki + Matris) + SuperAdmin bayrağı
- Kur yönetimi (USD/EUR/CNY + dinamik ekleme)
- Belge servisi (polymorphic: modül + kayıt_id + alt_modül)
- Audit log genişletildi: Modul + AltModul + IpAdresi kolonları
- Zorunlu şifre değiştirme akışı (ilk girişte)
- Yönetim paneli (`/yonetim/*`)

### v1.0 — Finans v2 (Nisan 2026)

- Anlaşma + model + ödeme planı + çek batch
- Avans + teminat mektubu + mahsup
- Cari hareket entegrasyonu
