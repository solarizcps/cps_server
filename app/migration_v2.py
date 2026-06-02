# -*- coding: utf-8 -*-
"""
CPS DEV - Prod MSSQL Migration v2
=================================
Bu script Solariz22 MSSQL veritabanında Faz 1 için gerekli
sistem tablolarını ve yeni kolonları ekler.

GÜVENLİ: IF NOT EXISTS pattern — var olanı dokunmaz, sadece eksikleri ekler.

Çalıştırmadan önce:
  1. CPS_DB_MODE=prod ortam değişkeni set edilmeli (BASLA.bat bunu yapıyor)
  2. 192.168.1.16/Solariz22 erişilebilir olmalı
  3. DB'nin yedeği alınmış olmalı (güvence için)

Kullanım:
    set CPS_DB_MODE=prod
    python migration_v2.py
"""
import sys
from config import Config
from db import DB_MODE, tablo_var_mi, kolon_var_mi, qexec, q

if DB_MODE != 'prod':
    print("⚠ migration_v2 SADECE prod mode'da çalışır.")
    print("  Önce: set CPS_DB_MODE=prod")
    sys.exit(1)


def _println(mesaj, ok=True):
    ikon = "✓" if ok else "→"
    print(f"  {ikon} {mesaj}")


def tablo_olustur_sistem_rol():
    if tablo_var_mi('sistem_rol'):
        _println("sistem_rol zaten var", ok=False)
    else:
        qexec("""
            CREATE TABLE sistem_rol (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                Ad NVARCHAR(50) UNIQUE NOT NULL,
                Aciklama NVARCHAR(500),
                Renk NVARCHAR(20) DEFAULT '#64748b',
                Aktif BIT DEFAULT 1,
                SuperAdmin BIT DEFAULT 0,
                OlusturmaTarih DATETIME DEFAULT GETDATE(),
                OlusturanKullanici NVARCHAR(50)
            )
        """)
        _println("sistem_rol oluşturuldu")


def tablo_olustur_sistem_yetki():
    if tablo_var_mi('sistem_yetki'):
        _println("sistem_yetki zaten var", ok=False)
    else:
        qexec("""
            CREATE TABLE sistem_yetki (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                Kod NVARCHAR(100) UNIQUE NOT NULL,
                Ad NVARCHAR(200) NOT NULL,
                Aciklama NVARCHAR(500),
                Modul NVARCHAR(50) NOT NULL,
                AltModul NVARCHAR(50),
                Sira INT DEFAULT 0
            )
        """)
        _println("sistem_yetki oluşturuldu")


def tablo_olustur_sistem_rol_yetki():
    if tablo_var_mi('sistem_rol_yetki'):
        _println("sistem_rol_yetki zaten var", ok=False)
    else:
        qexec("""
            CREATE TABLE sistem_rol_yetki (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                RolId INT NOT NULL,
                YetkiId INT NOT NULL,
                Gorebilir BIT DEFAULT 0,
                Duzenleyebilir BIT DEFAULT 0,
                CONSTRAINT uq_rol_yetki UNIQUE (RolId, YetkiId)
            )
        """)
        _println("sistem_rol_yetki oluşturuldu")


def tablo_olustur_sistem_kullanici():
    if tablo_var_mi('sistem_kullanici'):
        _println("sistem_kullanici zaten var — kolon kontrolleri yapılacak")
        # Eksik kolonları ekle
        for kolon, sql in [
            ('Email',                "ALTER TABLE sistem_kullanici ADD Email NVARCHAR(200)"),
            ('RolId',                "ALTER TABLE sistem_kullanici ADD RolId INT"),
            ('Rol',                  "ALTER TABLE sistem_kullanici ADD Rol NVARCHAR(50)"),
            ('ZorunluSifreDegistir', "ALTER TABLE sistem_kullanici ADD ZorunluSifreDegistir BIT DEFAULT 0"),
            ('SonGirisTarih',        "ALTER TABLE sistem_kullanici ADD SonGirisTarih DATETIME"),
            ('OlusturanKullanici',   "ALTER TABLE sistem_kullanici ADD OlusturanKullanici NVARCHAR(50)"),
        ]:
            if not kolon_var_mi('sistem_kullanici', kolon):
                qexec(sql)
                _println(f"sistem_kullanici.{kolon} eklendi")
    else:
        qexec("""
            CREATE TABLE sistem_kullanici (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                KullaniciAdi NVARCHAR(50) UNIQUE NOT NULL,
                AdSoyad NVARCHAR(200),
                Email NVARCHAR(200),
                Sifre NVARCHAR(200) NOT NULL,
                RolId INT,
                Rol NVARCHAR(50),
                Aktif BIT DEFAULT 1,
                ZorunluSifreDegistir BIT DEFAULT 0,
                OlusturmaTarih DATETIME DEFAULT GETDATE(),
                OlusturanKullanici NVARCHAR(50),
                SonGirisTarih DATETIME
            )
        """)
        _println("sistem_kullanici oluşturuldu")


def tablo_olustur_sistem_audit():
    if tablo_var_mi('sistem_audit'):
        _println("sistem_audit zaten var — kolon kontrolleri yapılacak")
        for kolon, sql in [
            ('Modul',    "ALTER TABLE sistem_audit ADD Modul NVARCHAR(50)"),
            ('AltModul', "ALTER TABLE sistem_audit ADD AltModul NVARCHAR(50)"),
            ('IpAdresi', "ALTER TABLE sistem_audit ADD IpAdresi NVARCHAR(50)"),
        ]:
            if not kolon_var_mi('sistem_audit', kolon):
                qexec(sql)
                _println(f"sistem_audit.{kolon} eklendi")
    else:
        qexec("""
            CREATE TABLE sistem_audit (
                Id BIGINT IDENTITY(1,1) PRIMARY KEY,
                Tarih DATETIME NOT NULL,
                KullaniciAdi NVARCHAR(50) NOT NULL,
                Islem NVARCHAR(50) NOT NULL,
                TabloAdi NVARCHAR(100),
                KayitId INT,
                Alan NVARCHAR(100),
                EskiDeger NVARCHAR(MAX),
                YeniDeger NVARCHAR(MAX),
                AnlasmaId INT,
                Aciklama NVARCHAR(1000),
                Modul NVARCHAR(50),
                AltModul NVARCHAR(50),
                IpAdresi NVARCHAR(50)
            )
        """)
        qexec("CREATE INDEX idx_audit_tarih ON sistem_audit(Tarih)")
        qexec("CREATE INDEX idx_audit_kullanici ON sistem_audit(KullaniciAdi)")
        qexec("CREATE INDEX idx_audit_modul ON sistem_audit(Modul, AltModul)")
        qexec("CREATE INDEX idx_audit_kayit ON sistem_audit(TabloAdi, KayitId)")
        qexec("CREATE INDEX idx_audit_anlasma ON sistem_audit(AnlasmaId)")
        _println("sistem_audit oluşturuldu")


def tablo_olustur_sistem_kur():
    if tablo_var_mi('sistem_kur'):
        _println("sistem_kur zaten var", ok=False)
    else:
        qexec("""
            CREATE TABLE sistem_kur (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                Tarih NVARCHAR(10) NOT NULL,
                ParaBirimi NVARCHAR(5) NOT NULL,
                Alis DECIMAL(18,6) NOT NULL,
                Satis DECIMAL(18,6) NOT NULL,
                MerkezKur DECIMAL(18,6) NOT NULL,
                Kaynak NVARCHAR(50) DEFAULT 'MANUEL',
                OlusturmaTarih DATETIME DEFAULT GETDATE(),
                OlusturanKullanici NVARCHAR(50),
                CONSTRAINT uq_kur_tarih_pb UNIQUE (Tarih, ParaBirimi)
            )
        """)
        _println("sistem_kur oluşturuldu")


def tablo_olustur_sistem_belge():
    if tablo_var_mi('sistem_belge'):
        _println("sistem_belge zaten var", ok=False)
    else:
        qexec("""
            CREATE TABLE sistem_belge (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                Modul NVARCHAR(50) NOT NULL,
                AltModul NVARCHAR(50),
                KayitId INT NOT NULL,
                BelgeTipi NVARCHAR(50),
                OrijinalAd NVARCHAR(400),
                DiskYol NVARCHAR(800),
                DosyaBoyut BIGINT,
                MimeType NVARCHAR(200),
                Yukleyen NVARCHAR(50),
                YuklemeTarih DATETIME,
                Aktif BIT DEFAULT 1,
                Aciklama NVARCHAR(1000)
            )
        """)
        qexec("CREATE INDEX idx_belge_kayit ON sistem_belge(Modul, AltModul, KayitId)")
        _println("sistem_belge oluşturuldu")


def tablo_olustur_finans_v2():
    """Finans v2 tabloları (anlaşma, avans, plan, mahsup, çek)."""
    tablolar = {
        'finans_anlasma': """
            CREATE TABLE finans_anlasma (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                ProjeKod NVARCHAR(50) UNIQUE NOT NULL,
                ProjeAdi NVARCHAR(500) NOT NULL,
                CKod NVARCHAR(50) NOT NULL,
                Durum NVARCHAR(20) DEFAULT 'AKTIF',
                ToplamTutar DECIMAL(18,2) DEFAULT 0,
                ParaBirimi NVARCHAR(5) DEFAULT 'TL',
                Notlar NVARCHAR(2000),
                KaynakModul NVARCHAR(50),
                KaynakKayitId INT,
                BaslangicTarih NVARCHAR(10),
                BitisTarih NVARCHAR(10),
                OlusturmaTarih DATETIME DEFAULT GETDATE(),
                OlusturanKullanici NVARCHAR(50),
                GuncellemeTarih DATETIME,
                GuncelleyenKullanici NVARCHAR(50)
            )""",
        'finans_anlasma_model': """
            CREATE TABLE finans_anlasma_model (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                AnlasmaId INT NOT NULL,
                Sira INT DEFAULT 0,
                ModelKod NVARCHAR(50),
                ModelAdi NVARCHAR(300),
                Miktar INT DEFAULT 0,
                BirimFiyat DECIMAL(18,4) DEFAULT 0,
                Tutar DECIMAL(18,2) DEFAULT 0,
                KdvOrani DECIMAL(5,2) DEFAULT 10
            )""",
        'finans_avans': """
            CREATE TABLE finans_avans (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                AnlasmaId INT NOT NULL,
                AvansTarih NVARCHAR(10),
                Tutar DECIMAL(18,2) DEFAULT 0,
                Aciklama NVARCHAR(500),
                TeminatMektupNo NVARCHAR(100),
                TeminatBanka NVARCHAR(100),
                Durum NVARCHAR(20) DEFAULT 'AKTIF'
            )""",
        'finans_avans_mahsup': """
            CREATE TABLE finans_avans_mahsup (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                AvansId INT NOT NULL,
                MahsupTarih NVARCHAR(10),
                Tutar DECIMAL(18,2) DEFAULT 0,
                Aciklama NVARCHAR(500),
                Gerceklesti BIT DEFAULT 0
            )""",
        'finans_odeme_plan': """
            CREATE TABLE finans_odeme_plan (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                AnlasmaId INT NOT NULL,
                Sira INT DEFAULT 0,
                VadeTarih NVARCHAR(10),
                OdemeTipi NVARCHAR(30),
                Tutar DECIMAL(18,2) DEFAULT 0,
                Aciklama NVARCHAR(500),
                Durum NVARCHAR(20) DEFAULT 'BEKLIYOR',
                GerceklesenTarih NVARCHAR(10)
            )""",
        'finans_odeme_cek': """
            CREATE TABLE finans_odeme_cek (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                OdemePlanId INT NOT NULL,
                CekNo NVARCHAR(50),
                BankaAdi NVARCHAR(100),
                DuzenlenmeTarih NVARCHAR(10),
                VadeTarih NVARCHAR(10),
                Tutar DECIMAL(18,2) DEFAULT 0,
                Durum NVARCHAR(20) DEFAULT 'VERILDI'
            )""",
    }

    for ad, sql in tablolar.items():
        if tablo_var_mi(ad):
            _println(f"{ad} zaten var", ok=False)
        else:
            qexec(sql)
            _println(f"{ad} oluşturuldu")


def tablo_olustur_grafik_v2a():
    """Grafik Faz 2a tabloları (kategori + ürün + varyant + tedarikçi)."""
    tablolar = {
        'grafik_urun_kategori': """
            CREATE TABLE grafik_urun_kategori (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                Ad NVARCHAR(100) UNIQUE NOT NULL,
                Aciklama NVARCHAR(500),
                Sira INT DEFAULT 0,
                Aktif BIT DEFAULT 1,
                OlusturmaTarih DATETIME DEFAULT GETDATE()
            )""",
        'grafik_urun': """
            CREATE TABLE grafik_urun (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                Kod NVARCHAR(50) UNIQUE NOT NULL,
                Ad NVARCHAR(300) NOT NULL,
                KategoriId INT,
                Aciklama NVARCHAR(1000),
                Aktif BIT DEFAULT 1,
                OlusturmaTarih DATETIME DEFAULT GETDATE(),
                OlusturanKullanici NVARCHAR(50)
            )""",
        'grafik_urun_varyant': """
            CREATE TABLE grafik_urun_varyant (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                UrunId INT NOT NULL,
                Kod NVARCHAR(50),
                RenkAd NVARCHAR(100),
                RenkHex NVARCHAR(10),
                Beden NVARCHAR(20),
                StokKod NVARCHAR(50),
                Aktif BIT DEFAULT 1,
                OlusturmaTarih DATETIME DEFAULT GETDATE()
            )""",
        'grafik_tedarikci': """
            CREATE TABLE grafik_tedarikci (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                Kod NVARCHAR(50) UNIQUE NOT NULL,
                Ad NVARCHAR(300) NOT NULL,
                Sehir NVARCHAR(100),
                Ulke NVARCHAR(50) DEFAULT 'Çin',
                Iletisim NVARCHAR(200),
                Email NVARCHAR(200),
                WhatsApp NVARCHAR(50),
                WeChat NVARCHAR(100),
                NakliyeTipi NVARCHAR(10) DEFAULT 'FOB',
                VadeGun INT DEFAULT 0,
                Notlar NVARCHAR(2000),
                Aktif BIT DEFAULT 1,
                OlusturmaTarih DATETIME DEFAULT GETDATE(),
                OlusturanKullanici NVARCHAR(50)
            )""",
    }

    for ad, sql in tablolar.items():
        if tablo_var_mi(ad):
            _println(f"{ad} zaten var", ok=False)
        else:
            qexec(sql)
            _println(f"{ad} oluşturuldu")

    # Indexler
    if tablo_var_mi('grafik_urun') and not kolon_var_mi('grafik_urun', 'KategoriId'):
        pass  # zaten var
    # SQL Server üzerinde index var mı kontrolü basit değil, try/except ile geç
    for idx_sql in [
        "CREATE INDEX idx_grafik_urun_kategori ON grafik_urun(KategoriId)",
        "CREATE INDEX idx_grafik_varyant_urun ON grafik_urun_varyant(UrunId)",
    ]:
        try:
            qexec(idx_sql)
        except Exception:
            pass  # index zaten var


def seed_yetkiler_ve_yonetim():
    """Yetki tanımları + Yönetim rolünü kur."""
    sayi = q("SELECT COUNT(*) AS c FROM sistem_yetki")[0]['c']
    if sayi > 0:
        _println(f"sistem_yetki zaten dolu ({sayi} kayıt) — seed atlanıyor", ok=False)
        return

    print("\n  Yetkiler ekleniyor...")
    yetkiler = [
        ('finans.dashboard',    'Finans Dashboard',        None, 'finans', None, 10),
        ('finans.anlasma',      'Anlaşma Listesi',         None, 'finans', 'anlasma', 20),
        ('finans.anlasma.yaz',  'Anlaşma Oluştur/Düzenle', None, 'finans', 'anlasma', 21),
        ('finans.cari',         'Cari Liste',              None, 'finans', 'cari', 30),
        ('grafik.numune',       'Numune Listesi',          None, 'grafik', 'numune', 40),
        ('grafik.cin',          'Çin Sipariş',             None, 'grafik', 'cin', 50),
        ('grafik.cin.fiyat',    'Çin Fiyat Görüntüle',     None, 'grafik', 'cin', 51),
        ('grafik.maliyet',      'Maliyet & Sevkiyat',      None, 'grafik', 'maliyet', 60),
        ('grafik.analiz',       'Analiz Dashboard',        None, 'grafik', 'analiz', 70),
        ('grafik.urun',         'Ürün Kataloğu',           None, 'grafik', 'urun', 80),
        ('grafik.tedarikci',    'Tedarikçi Listesi',       None, 'grafik', 'tedarikci', 90),
        ('belge.indir',         'Belge İndirme',           None, 'belge',  None, 100),
        ('belge.yukle',         'Belge Yükleme',           None, 'belge',  None, 101),
        ('yonetim.kullanici',   'Kullanıcı Yönetimi',      None, 'yonetim','kullanici', 200),
        ('yonetim.rol',         'Rol Yönetimi',            None, 'yonetim','rol', 201),
        ('yonetim.kur',         'Kur Yönetimi',            None, 'yonetim','kur', 202),
        ('yonetim.log',         'Audit Log',               None, 'yonetim','log', 203),
    ]
    for kod, ad, ac, md, alt, sira in yetkiler:
        qexec("""INSERT INTO sistem_yetki (Kod, Ad, Aciklama, Modul, AltModul, Sira)
                 VALUES (?, ?, ?, ?, ?, ?)""",
              (kod, ad, ac, md, alt, sira))
    _println(f"{len(yetkiler)} yetki eklendi")

    # Yönetim rolü
    r = q("SELECT Id FROM sistem_rol WHERE Ad = ?", ('Yönetim',))
    if not r:
        qexec("""INSERT INTO sistem_rol (Ad, Aciklama, Renk, SuperAdmin, OlusturanKullanici)
                 VALUES ('Yönetim', 'Tüm modüllere tam erişim.', '#F97316', 1, 'sistem')""")
        _println("Yönetim rolü oluşturuldu")


def main():
    print("=" * 60)
    print(f"CPS Migration v2 — DB_MODE={DB_MODE}")
    print(f"Hedef: {Config.MSSQL_HOST}/{Config.MSSQL_DATABASE}")
    print("=" * 60)

    try:
        print("\n[1/7] Rol / Yetki / Kullanıcı tabloları...")
        tablo_olustur_sistem_rol()
        tablo_olustur_sistem_yetki()
        tablo_olustur_sistem_rol_yetki()
        tablo_olustur_sistem_kullanici()

        print("\n[2/7] Audit log...")
        tablo_olustur_sistem_audit()

        print("\n[3/7] Kur tablosu...")
        tablo_olustur_sistem_kur()

        print("\n[4/7] Belge tablosu...")
        tablo_olustur_sistem_belge()

        print("\n[5/7] Finans v2 tabloları...")
        tablo_olustur_finans_v2()

        print("\n[6/7] Grafik Faz 2a tabloları (ürün + varyant + tedarikçi)...")
        tablo_olustur_grafik_v2a()

        print("\n[7/7] Yetki + Yönetim rolü seed...")
        seed_yetkiler_ve_yonetim()

        print("\n" + "=" * 60)
        print("✅ MIGRATION TAMAMLANDI")
        print("=" * 60)
        print("\nSonraki adımlar:")
        print("  1. sistem_kullanici tablosuna en az 1 Yönetim rolünde kullanıcı ekleyin")
        print("  2. python app.py ile çalıştırın")
        print("  3. /yonetim/rol/1 ekranından diğer rollere yetki verin")
    except Exception as e:
        print(f"\n❌ HATA: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)


if __name__ == '__main__':
    main()
