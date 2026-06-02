# -*- coding: utf-8 -*-
"""
CPS DEV - Mock DB Initializer (Faz 1)
======================================
Sıfırdan SQLite veritabanı kurar:
  - Finans v2 tabloları
  - Sistem tabloları (kullanıcı, audit, rol, yetki, rol_yetki, kur, belge)
  - MSSQL uyumluluğu için Cari_Kart, Cari_Har, Banka_Kart, Kasa_Kart, Cek_Senet
  - 6 kullanıcı + 6 rol + 20 yetki
  - 5 Finans mock anlaşması
  - USD/EUR/CNY son 7 gün kurları

ÇALIŞTIR:
    python init_mock_db.py [--sil] [--sadece-yonetim]
"""
import os
import sys
import sqlite3
from datetime import datetime, date, timedelta
from config import Config


SCHEMA_SQL = """
-- ============= KULLANICI / ROL / YETKİ =============
CREATE TABLE IF NOT EXISTS sistem_rol (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Ad TEXT UNIQUE NOT NULL,
    Aciklama TEXT,
    Renk TEXT DEFAULT '#64748b',
    Aktif INTEGER DEFAULT 1,
    SuperAdmin INTEGER DEFAULT 0,
    OlusturmaTarih TEXT,
    OlusturanKullanici TEXT
);

CREATE TABLE IF NOT EXISTS sistem_yetki (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Kod TEXT UNIQUE NOT NULL,
    Ad TEXT NOT NULL,
    Aciklama TEXT,
    Modul TEXT NOT NULL,
    AltModul TEXT,
    Sira INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sistem_rol_yetki (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    RolId INTEGER NOT NULL,
    YetkiId INTEGER NOT NULL,
    Gorebilir INTEGER DEFAULT 0,
    Duzenleyebilir INTEGER DEFAULT 0,
    UNIQUE(RolId, YetkiId)
);

CREATE TABLE IF NOT EXISTS sistem_kullanici (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    KullaniciAdi TEXT UNIQUE NOT NULL,
    AdSoyad TEXT,
    Email TEXT,
    Sifre TEXT NOT NULL,
    RolId INTEGER,
    Rol TEXT,
    Aktif INTEGER DEFAULT 1,
    ZorunluSifreDegistir INTEGER DEFAULT 0,
    OlusturmaTarih TEXT,
    OlusturanKullanici TEXT,
    SonGirisTarih TEXT
);

-- ============= AUDIT =============
CREATE TABLE IF NOT EXISTS sistem_audit (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Tarih TEXT NOT NULL,
    KullaniciAdi TEXT NOT NULL,
    Islem TEXT NOT NULL,
    TabloAdi TEXT,
    KayitId INTEGER,
    Alan TEXT,
    EskiDeger TEXT,
    YeniDeger TEXT,
    AnlasmaId INTEGER,
    Aciklama TEXT,
    Modul TEXT,
    AltModul TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_tarih ON sistem_audit(Tarih);
CREATE INDEX IF NOT EXISTS idx_audit_kullanici ON sistem_audit(KullaniciAdi);
CREATE INDEX IF NOT EXISTS idx_audit_modul ON sistem_audit(Modul, AltModul);
CREATE INDEX IF NOT EXISTS idx_audit_kayit ON sistem_audit(TabloAdi, KayitId);
CREATE INDEX IF NOT EXISTS idx_audit_anlasma ON sistem_audit(AnlasmaId);

-- ============= KUR =============
CREATE TABLE IF NOT EXISTS sistem_kur (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Tarih TEXT NOT NULL,
    ParaBirimi TEXT NOT NULL,
    Alis REAL NOT NULL,
    Satis REAL NOT NULL,
    MerkezKur REAL NOT NULL,
    Kaynak TEXT DEFAULT 'MANUEL',
    OlusturmaTarih TEXT,
    OlusturanKullanici TEXT,
    UNIQUE(Tarih, ParaBirimi)
);

-- ============= BELGE =============
CREATE TABLE IF NOT EXISTS sistem_belge (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Modul TEXT NOT NULL,
    AltModul TEXT,
    KayitId INTEGER NOT NULL,
    BelgeTipi TEXT,
    OrijinalAd TEXT,
    DiskYol TEXT,
    DosyaBoyut INTEGER,
    MimeType TEXT,
    Yukleyen TEXT,
    YuklemeTarih TEXT,
    Aktif INTEGER DEFAULT 1,
    Aciklama TEXT
);
CREATE INDEX IF NOT EXISTS idx_belge_kayit ON sistem_belge(Modul, AltModul, KayitId);

-- ============= CARİ =============
CREATE TABLE IF NOT EXISTS Cari_Kart (
    CKod TEXT PRIMARY KEY,
    CName TEXT NOT NULL,
    CTip INTEGER DEFAULT 1,
    VergiNo TEXT,
    VergiDairesi TEXT,
    Telefon TEXT,
    Sehir TEXT,
    Ulke TEXT DEFAULT 'Türkiye',
    Email TEXT,
    Adres TEXT,
    Bakiye REAL DEFAULT 0,
    Aktif INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS Cari_Har (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    CKod TEXT NOT NULL,
    Tarih TEXT NOT NULL,
    BelgeNo TEXT,
    BelgeTip TEXT,
    Aciklama TEXT,
    Borc REAL DEFAULT 0,
    Alacak REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ch_ckod ON Cari_Har(CKod);
CREATE INDEX IF NOT EXISTS idx_ch_tarih ON Cari_Har(Tarih);

CREATE TABLE IF NOT EXISTS Banka_Kart (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    BankaAd TEXT, HesapNo TEXT, Iban TEXT,
    Doviz TEXT DEFAULT 'TL',
    Bakiye REAL DEFAULT 0,
    Aktif INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS Kasa_Kart (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    KasaAd TEXT, Doviz TEXT DEFAULT 'TL',
    Bakiye REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS Cek_Senet (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Tip TEXT DEFAULT 'CEK',
    CekNo TEXT, Banka TEXT,
    CKod TEXT,
    AlimTarih TEXT, VadeTarih TEXT,
    Tutar REAL DEFAULT 0,
    Durum TEXT DEFAULT 'PORTFOY'
);

-- ============= FİNANS V2 =============
CREATE TABLE IF NOT EXISTS finans_anlasma (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    ProjeKod TEXT NOT NULL,
    ProjeAdi TEXT NOT NULL,
    CKod TEXT NOT NULL,
    BaslangicTarih TEXT,
    BitisTarih TEXT,
    ToplamTutar REAL DEFAULT 0,
    KdvOrani REAL DEFAULT 10,
    ParaBirimi TEXT DEFAULT 'TRY',
    Durum TEXT DEFAULT 'AKTIF',
    Notlar TEXT,
    OlusturmaTarih TEXT,
    OlusturanKullanici TEXT,
    SonDuzenleyen TEXT,
    SonDuzenlemeTarih TEXT,
    KaynakModul TEXT,
    KaynakKayitId INTEGER
);

CREATE TABLE IF NOT EXISTS finans_anlasma_model (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    AnlasmaId INTEGER NOT NULL,
    Sira INTEGER DEFAULT 0,
    ModelKod TEXT,
    ModelAdi TEXT NOT NULL,
    Renk TEXT,
    Miktar INTEGER DEFAULT 0,
    BirimFiyat REAL DEFAULT 0,
    Notu TEXT
);
CREATE INDEX IF NOT EXISTS idx_am_anlasma ON finans_anlasma_model(AnlasmaId);

CREATE TABLE IF NOT EXISTS finans_avans (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    AnlasmaId INTEGER NOT NULL,
    AvansTarih TEXT,
    Tutar REAL DEFAULT 0,
    OdemeTipi TEXT DEFAULT 'HAVALE',
    TeminatMektup INTEGER DEFAULT 0,
    TeminatTutar REAL DEFAULT 0,
    TeminatNotu TEXT,
    Aciklama TEXT
);
CREATE INDEX IF NOT EXISTS idx_av_anlasma ON finans_avans(AnlasmaId);

CREATE TABLE IF NOT EXISTS finans_avans_mahsup (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    AvansId INTEGER NOT NULL,
    Sira INTEGER DEFAULT 0,
    MahsupTarih TEXT,
    Tutar REAL DEFAULT 0,
    Durum TEXT DEFAULT 'BEKLIYOR',
    GerceklesenTarih TEXT,
    GerceklesenTutar REAL DEFAULT 0,
    Aciklama TEXT
);
CREATE INDEX IF NOT EXISTS idx_mh_avans ON finans_avans_mahsup(AvansId);

CREATE TABLE IF NOT EXISTS finans_odeme_plan (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    AnlasmaId INTEGER NOT NULL,
    ModelId INTEGER,
    Sira INTEGER DEFAULT 0,
    PlanTarih TEXT,
    OdemeTipi TEXT,
    Tutar REAL DEFAULT 0,
    CekAdeti INTEGER DEFAULT 1,
    Durum TEXT DEFAULT 'BEKLIYOR',
    GerceklesenTarih TEXT,
    GerceklesenTutar REAL DEFAULT 0,
    Aciklama TEXT,
    CariHarId INTEGER
);
CREATE INDEX IF NOT EXISTS idx_op_anlasma ON finans_odeme_plan(AnlasmaId);

CREATE TABLE IF NOT EXISTS finans_odeme_cek (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    OdemePlanId INTEGER NOT NULL,
    CekSira INTEGER DEFAULT 0,
    CekNo TEXT,
    CekBanka TEXT,
    CekAlimTarih TEXT,
    CekVadeTarih TEXT,
    Tutar REAL DEFAULT 0,
    Durum TEXT DEFAULT 'BEKLIYOR',
    TahsilTarih TEXT,
    Notu TEXT
);
CREATE INDEX IF NOT EXISTS idx_ock_plan ON finans_odeme_cek(OdemePlanId);

-- ============= GRAFİK - ÜRÜN / VARYANT / TEDARİKÇİ =============
CREATE TABLE IF NOT EXISTS grafik_urun_kategori (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Ad TEXT UNIQUE NOT NULL,
    Aciklama TEXT,
    Sira INTEGER DEFAULT 0,
    Aktif INTEGER DEFAULT 1,
    OlusturmaTarih TEXT
);

CREATE TABLE IF NOT EXISTS grafik_urun (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Kod TEXT UNIQUE NOT NULL,
    Ad TEXT NOT NULL,
    KategoriId INTEGER,
    Aciklama TEXT,
    Aktif INTEGER DEFAULT 1,
    OlusturmaTarih TEXT,
    OlusturanKullanici TEXT,
    FOREIGN KEY (KategoriId) REFERENCES grafik_urun_kategori(Id)
);
CREATE INDEX IF NOT EXISTS idx_urun_kategori ON grafik_urun(KategoriId);

CREATE TABLE IF NOT EXISTS grafik_urun_varyant (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    UrunId INTEGER NOT NULL,
    Kod TEXT,
    RenkAd TEXT,
    RenkHex TEXT,
    Beden TEXT,
    StokKod TEXT,
    Aktif INTEGER DEFAULT 1,
    OlusturmaTarih TEXT,
    FOREIGN KEY (UrunId) REFERENCES grafik_urun(Id) ON DELETE CASCADE,
    UNIQUE(UrunId, RenkAd, Beden)
);
CREATE INDEX IF NOT EXISTS idx_varyant_urun ON grafik_urun_varyant(UrunId);

CREATE TABLE IF NOT EXISTS grafik_tedarikci (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Kod TEXT UNIQUE NOT NULL,
    Ad TEXT NOT NULL,
    Sehir TEXT,
    Ulke TEXT DEFAULT 'Çin',
    Iletisim TEXT,
    Email TEXT,
    WhatsApp TEXT,
    WeChat TEXT,
    NakliyeTipi TEXT DEFAULT 'FOB',
    VadeGun INTEGER DEFAULT 0,
    CariCKod TEXT,
    Notlar TEXT,
    Aktif INTEGER DEFAULT 1,
    OlusturmaTarih TEXT,
    OlusturanKullanici TEXT,
    FOREIGN KEY (CariCKod) REFERENCES Cari_Kart(CKod)
);

-- ============= GRAFİK - ÇİN SİPARİŞ =============
CREATE TABLE IF NOT EXISTS grafik_cin_siparis (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    SiparisNo TEXT UNIQUE NOT NULL,
    TedarikciId INTEGER NOT NULL,
    KaynakNumuneId INTEGER,
    KaynakTeklifId INTEGER,
    MusteriCKod TEXT,
    SiparisTarihi TEXT,
    BeklenenCikisTarihi TEXT,
    ParaBirimi TEXT DEFAULT 'USD',
    KurSnapshot REAL,
    ToplamTutar REAL DEFAULT 0,
    Durum TEXT DEFAULT 'TASLAK',
    Notlar TEXT,
    OlusturmaTarih TEXT,
    OlusturanKullanici TEXT,
    OnayTarihi TEXT,
    OnaylayanKullanici TEXT,
    FinansAnlasmaId INTEGER,
    FOREIGN KEY (TedarikciId) REFERENCES grafik_tedarikci(Id),
    FOREIGN KEY (KaynakNumuneId) REFERENCES grafik_numune(Id),
    FOREIGN KEY (MusteriCKod) REFERENCES Cari_Kart(CKod),
    FOREIGN KEY (FinansAnlasmaId) REFERENCES finans_anlasma(Id)
);
CREATE INDEX IF NOT EXISTS idx_cinsip_durum ON grafik_cin_siparis(Durum);
CREATE INDEX IF NOT EXISTS idx_cinsip_tedarikci ON grafik_cin_siparis(TedarikciId);
CREATE INDEX IF NOT EXISTS idx_cinsip_anlasma ON grafik_cin_siparis(FinansAnlasmaId);

CREATE TABLE IF NOT EXISTS grafik_cin_siparis_kalem (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    SiparisId INTEGER NOT NULL,
    VaryantId INTEGER,
    UrunId INTEGER,
    Aciklama TEXT,
    Miktar INTEGER DEFAULT 0,
    CiftSayi INTEGER DEFAULT 0,
    BirimFiyat REAL DEFAULT 0,
    Tutar REAL DEFAULT 0,
    AgirlikKg REAL DEFAULT 0,
    HacimM3 REAL DEFAULT 0,
    OlusturmaTarih TEXT,
    FOREIGN KEY (SiparisId) REFERENCES grafik_cin_siparis(Id) ON DELETE CASCADE,
    FOREIGN KEY (VaryantId) REFERENCES grafik_urun_varyant(Id),
    FOREIGN KEY (UrunId) REFERENCES grafik_urun(Id)
);
CREATE INDEX IF NOT EXISTS idx_cinsip_kalem_sip ON grafik_cin_siparis_kalem(SiparisId);

-- ============= GRAFİK - SEVKİYAT & MALİYET DAĞITIM =============
CREATE TABLE IF NOT EXISTS grafik_sevkiyat (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    SevkiyatNo TEXT UNIQUE NOT NULL,
    SiparisId INTEGER,
    NumuneId INTEGER,
    NakliyeTipi TEXT DEFAULT 'KONTEYNER',
    Forwarder TEXT,
    Konsimento TEXT,
    TakipNo TEXT,
    GonderimYonu TEXT DEFAULT 'CN_TR',
    UrunMaliyetineDahil INTEGER DEFAULT 1,
    AgirlikKg REAL DEFAULT 0,
    SevkTarihi TEXT,
    BeklenenVarisTarihi TEXT,
    GerceklesenVarisTarihi TEXT,
    ToplamMasrafTL REAL DEFAULT 0,
    DagitimYontemi TEXT DEFAULT 'FOB',
    DagitimHesaplandi INTEGER DEFAULT 0,
    Durum TEXT DEFAULT 'HAZIRLIK',
    Notlar TEXT,
    OlusturmaTarih TEXT,
    OlusturanKullanici TEXT,
    FOREIGN KEY (SiparisId) REFERENCES grafik_cin_siparis(Id),
    FOREIGN KEY (NumuneId) REFERENCES grafik_numune(Id)
);
CREATE INDEX IF NOT EXISTS idx_sevk_siparis ON grafik_sevkiyat(SiparisId);
CREATE INDEX IF NOT EXISTS idx_sevk_durum ON grafik_sevkiyat(Durum);

CREATE TABLE IF NOT EXISTS grafik_sevkiyat_masraf (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    SevkiyatId INTEGER NOT NULL,
    Tip TEXT NOT NULL,
    BirimSayi REAL DEFAULT 0,
    BirimFiyat REAL DEFAULT 0,
    Tutar REAL DEFAULT 0,
    ParaBirimi TEXT DEFAULT 'TRY',
    IslemTarih TEXT,
    KurSnapshot REAL DEFAULT 1,
    TutarTL REAL DEFAULT 0,
    BelgeNo TEXT,
    Aciklama TEXT,
    OlusturmaTarih TEXT,
    OlusturanKullanici TEXT,
    FOREIGN KEY (SevkiyatId) REFERENCES grafik_sevkiyat(Id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sevk_masraf_sevk ON grafik_sevkiyat_masraf(SevkiyatId);

CREATE TABLE IF NOT EXISTS grafik_sevkiyat_dagitim (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    SevkiyatId INTEGER NOT NULL,
    KalemId INTEGER NOT NULL,
    Yontem TEXT NOT NULL,
    DagitimAgirligi REAL DEFAULT 0,
    MasrafPayiTL REAL DEFAULT 0,
    FOBUSDTutar REAL DEFAULT 0,
    FOBTLTutar REAL DEFAULT 0,
    ToplamTLTutar REAL DEFAULT 0,
    BirimMaliyetTL REAL DEFAULT 0,
    IsTahmini INTEGER DEFAULT 1,
    OlusturmaTarih TEXT,
    UNIQUE(SevkiyatId, KalemId),
    FOREIGN KEY (SevkiyatId) REFERENCES grafik_sevkiyat(Id) ON DELETE CASCADE,
    FOREIGN KEY (KalemId) REFERENCES grafik_cin_siparis_kalem(Id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_dagitim_sevk ON grafik_sevkiyat_dagitim(SevkiyatId);

-- ============= GRAFİK - FİYAT TEKLİFİ =============
CREATE TABLE IF NOT EXISTS grafik_fiyat_teklif (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    TeklifNo TEXT UNIQUE NOT NULL,
    UlkeKodu TEXT DEFAULT 'CN',
    TedarikciId INTEGER,
    TedarikciAd TEXT,
    MusteriCKod TEXT,
    UrunAd TEXT,
    UrunKodu TEXT,
    Miktar REAL DEFAULT 0,
    BirimFiyat REAL DEFAULT 0,
    ParaBirimi TEXT DEFAULT 'USD',
    KurSnapshot REAL DEFAULT 1,
    ToplamTutar REAL DEFAULT 0,
    TeklifTarihi TEXT,
    GecerlilikTarihi TEXT,
    Durum TEXT DEFAULT 'ALINDI',
    SiparisId INTEGER,
    Notlar TEXT,
    OlusturmaTarih TEXT,
    OlusturanKullanici TEXT,
    FOREIGN KEY (TedarikciId) REFERENCES grafik_tedarikci(Id),
    FOREIGN KEY (MusteriCKod) REFERENCES Cari_Kart(CKod),
    FOREIGN KEY (SiparisId) REFERENCES grafik_cin_siparis(Id)
);
CREATE INDEX IF NOT EXISTS idx_teklif_durum ON grafik_fiyat_teklif(Durum);
CREATE INDEX IF NOT EXISTS idx_teklif_tedarikci ON grafik_fiyat_teklif(TedarikciId);

-- ============= GRAFİK - NUMUNE TAKİP =============
CREATE TABLE IF NOT EXISTS grafik_numune (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    NumuneNo TEXT UNIQUE NOT NULL,
    Baslik TEXT NOT NULL,
    MusteriCKod TEXT,
    TedarikciId INTEGER,
    UrunId INTEGER,
    Durum TEXT DEFAULT 'TALEP',
    TalepTarihi TEXT,
    BeklenenTarih TEXT,
    Notlar TEXT,
    OlusturmaTarih TEXT,
    OlusturanKullanici TEXT,
    FOREIGN KEY (MusteriCKod) REFERENCES Cari_Kart(CKod),
    FOREIGN KEY (TedarikciId) REFERENCES grafik_tedarikci(Id),
    FOREIGN KEY (UrunId) REFERENCES grafik_urun(Id)
);
CREATE INDEX IF NOT EXISTS idx_numune_durum ON grafik_numune(Durum);
CREATE INDEX IF NOT EXISTS idx_numune_musteri ON grafik_numune(MusteriCKod);
CREATE INDEX IF NOT EXISTS idx_numune_tedarikci ON grafik_numune(TedarikciId);

CREATE TABLE IF NOT EXISTS grafik_numune_iterasyon (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    NumuneId INTEGER NOT NULL,
    Sira INTEGER DEFAULT 1,
    Tarih TEXT NOT NULL,
    Durum TEXT NOT NULL,
    FeedbackNotu TEXT,
    OlusturanKullanici TEXT,
    OlusturmaTarih TEXT,
    FOREIGN KEY (NumuneId) REFERENCES grafik_numune(Id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_iter_numune ON grafik_numune_iterasyon(NumuneId);

-- ====================================================================
-- PARÇA 7a: Ön Maliyet ve Karar Simülatörü (Finans modülü)
-- ====================================================================
CREATE TABLE IF NOT EXISTS finans_simulasyon (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    SimulasyonNo TEXT NOT NULL UNIQUE,
    Baslik TEXT NOT NULL,
    UrunAdi TEXT,
    HedefMiktar INTEGER NOT NULL DEFAULT 0,
    HedefCiftSatis REAL,              -- opsiyonel: satış fiyatı TL/çift (marj için)
    HedefTeslimTarih TEXT,            -- opsiyonel
    Notlar TEXT,
    Durum TEXT DEFAULT 'TASLAK',      -- TASLAK / KARAR / ARSIVLENMIS
    SecilenSecenekId INTEGER,
    KararVerenKullanici TEXT,
    KararTarihi TEXT,
    OlusturmaTarih TEXT,
    OlusturanKullanici TEXT
);
CREATE INDEX IF NOT EXISTS idx_sim_durum ON finans_simulasyon(Durum);

CREATE TABLE IF NOT EXISTS finans_simulasyon_secenek (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    SimulasyonId INTEGER NOT NULL,
    Sira INTEGER DEFAULT 1,
    Etiket TEXT NOT NULL,
    -- Kaynak
    Ulke TEXT,                         -- CN / TR / EU
    TedarikciAd TEXT,
    TedarikciId INTEGER,               -- opsiyonel FK
    KaynakTeklifId INTEGER,            -- opsiyonel FK
    -- Birim fiyat
    BirimFiyat REAL NOT NULL DEFAULT 0,
    ParaBirimi TEXT DEFAULT 'USD',
    KurSnapshot REAL NOT NULL DEFAULT 1.0,
    -- Nakliye
    NakliyeTipi TEXT,                  -- UCAK / KONTEYNER / KARAYOLU / DHL
    NakliyeGunSuresi INTEGER DEFAULT 0,
    NakliyeSabitMaliyet REAL DEFAULT 0,
    NakliyeBirimMaliyet REAL DEFAULT 0,
    NakliyeParaBirimi TEXT DEFAULT 'USD',
    NakliyeKur REAL DEFAULT 1.0,
    NakliyeAgirlikKg REAL DEFAULT 0,
    -- Ek maliyetler
    GumrukVergisiYuzde REAL DEFAULT 18,
    SigortaYuzde REAL DEFAULT 0.5,
    MusavirMaliyeti REAL DEFAULT 0,
    DigerMaliyet REAL DEFAULT 0,
    DigerMaliyetAciklama TEXT,
    -- Hesaplanan (otomatik)
    ToplamFOB REAL DEFAULT 0,
    ToplamNakliye REAL DEFAULT 0,
    ToplamSigorta REAL DEFAULT 0,
    ToplamVergi REAL DEFAULT 0,
    ToplamExtras REAL DEFAULT 0,
    ToplamMaliyetTL REAL DEFAULT 0,
    BirimMaliyetTL REAL DEFAULT 0,
    KgMaliyetTL REAL DEFAULT 0,
    MarjYuzde REAL,
    Notlar TEXT,
    OlusturmaTarih TEXT,
    OlusturanKullanici TEXT,
    FOREIGN KEY (SimulasyonId) REFERENCES finans_simulasyon(Id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sim_sec_sim ON finans_simulasyon_secenek(SimulasyonId);

-- ====================================================================
-- PARÇA 8a: Çin Ofis Excel Import (Finans modülü)
-- ====================================================================
CREATE TABLE IF NOT EXISTS cin_ofis_import_log (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    OrderCode TEXT NOT NULL,
    DosyaAdi TEXT,
    SiparisId INTEGER,
    ParseOzet TEXT,
    Dil TEXT DEFAULT 'CN',
    TemplateSurum TEXT DEFAULT 'v1.0',
    Durum TEXT DEFAULT 'ON_IZLEME',  -- ON_IZLEME / BASARILI / HATA / REVIZE_EDILDI / IPTAL
    OncekiImportId INTEGER,
    HataListesi TEXT,
    -- Kur izlenebilirlik (finansal güvenlik)
    KurPB TEXT,
    KurDeger REAL,
    KurKaynagi TEXT,                  -- SISTEM_OTOMATIK / SISTEM_OVERRIDE / EXCEL_OVERRIDE / TRY_NATIVE
    KurTarihi TEXT,
    SistemKurDeger REAL,
    ExcelKurDeger REAL,
    KurFarkiYuzde REAL,
    KurOnayKullanici TEXT,
    KurOnayGerekce TEXT,
    OlusturmaTarih TEXT,
    OlusturanKullanici TEXT
);
CREATE INDEX IF NOT EXISTS idx_cof_log_order ON cin_ofis_import_log(OrderCode);
CREATE INDEX IF NOT EXISTS idx_cof_log_durum ON cin_ofis_import_log(Durum);

CREATE TABLE IF NOT EXISTS cin_ofis_odeme_taslak (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    ImportLogId INTEGER NOT NULL,
    Sira INTEGER DEFAULT 1,
    OdemeTipi TEXT,
    Oran REAL,
    Tutar REAL,
    ParaBirimi TEXT,
    PlanTarih TEXT,
    Tetikleyici TEXT,
    Notlar TEXT,
    FOREIGN KEY (ImportLogId) REFERENCES cin_ofis_import_log(Id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cin_ofis_dosya_referans (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    ImportLogId INTEGER NOT NULL,
    Sira INTEGER DEFAULT 1,
    DosyaAdi TEXT NOT NULL,
    DosyaTipi TEXT,
    Gerekli INTEGER DEFAULT 0,        -- 1 = Required=Yes
    Aciklama TEXT,
    BulundiMu INTEGER DEFAULT 0,
    FOREIGN KEY (ImportLogId) REFERENCES cin_ofis_import_log(Id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cin_ofis_kalem_ek (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    KalemId INTEGER NOT NULL,
    ContainerGroup TEXT,
    ContainerType TEXT,               -- 20GP / 40GP / 40HQ / LCL / Break Bulk
    ContainerQty INTEGER DEFAULT 1,
    Quality TEXT,                     -- Main / Sample / Other
    ProductName TEXT,
    Unit TEXT,                        -- kg / pair / pcs / box / ton
    FOREIGN KEY (KalemId) REFERENCES grafik_cin_siparis_kalem(Id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cof_kek_kalem ON cin_ofis_kalem_ek(KalemId);
"""


YETKI_TANIMLARI = [
    # Finans
    ('finans',                    'Finans Modülü Genel',          'finans', None,           1),
    ('finans.anlasma',            'Anlaşma / Proje',              'finans', 'anlasma',      2),
    ('finans.anlasma.sil',        'Anlaşma Sil',                  'finans', 'anlasma',      3),
    ('finans.cari',               'Cari Hesaplar',                'finans', 'cari',         4),
    ('finans.odeme',              'Ödeme / Mahsup İşlemleri',     'finans', 'odeme',        5),
    ('finans.maliyet_goster',     'Maliyet Alanlarını Görme',     'finans', 'maliyet',      6),
    ('finans.simulator',          'Maliyet Simülatörü',           'finans', 'simulator',    7),
    ('finans.simulator.karar',    'Simülasyon Karar Verme',       'finans', 'simulator',    8),
    ('finans.cin_ofis_import',    'Çin Ofis Excel Import',        'finans', 'cin_ofis',     9),
    ('finans.cin_ofis_import.override_kur', 'Excel Kur Override',  'finans', 'cin_ofis',     10),
    ('grafik.cin_siparis.onayla', 'Çin Sipariş Kontrolünü Onay',   'grafik', 'cin_siparis',  20),
    ('grafik.cin_siparis.kur_override', 'Sipariş Kur Kilidini Aç', 'grafik', 'cin_siparis',  21),

    # Grafik
    ('grafik.numune',             'Numune Takip',                 'grafik', 'numune',       10),
    ('grafik.numune.sil',         'Numune Sil',                   'grafik', 'numune',       11),
    ('grafik.cin_siparis',        'Çin Sipariş Takip',            'grafik', 'cin_siparis',  12),
    ('grafik.cin_siparis.sil',    'Çin Sipariş Sil',              'grafik', 'cin_siparis',  13),
    ('grafik.cin_siparis.maliyet','Sipariş Maliyet Görme',        'grafik', 'cin_siparis',  14),
    ('grafik.maliyet',            'Maliyet / Sevkiyat Takibi',    'grafik', 'maliyet',      15),
    ('grafik.maliyet.beyanname',  'Beyanname / Fatura İşleme',    'grafik', 'maliyet',      16),
    ('grafik.analiz',             'Analiz / Karşılaştırma',       'grafik', 'analiz',       17),
    ('grafik.urun',               'Ürün / Varyant Yönetimi',      'grafik', 'urun',         18),
    ('grafik.tedarikci',          'Tedarikçi Yönetimi',           'grafik', 'tedarikci',    19),

    # Yönetim
    ('yonetim.kullanici',         'Kullanıcı Yönetimi',           'yonetim','kullanici',    90),
    ('yonetim.rol',               'Rol ve Yetki Yönetimi',        'yonetim','rol',          91),
    ('yonetim.kur',               'Kur Yönetimi',                 'yonetim','kur',          92),
    ('yonetim.log',               'Audit Log',                    'yonetim','log',          93),
]


def _kur_sema(conn):
    cur = conn.cursor()
    cur.executescript(SCHEMA_SQL)
    for kod, ad, modul, alt, sira in YETKI_TANIMLARI:
        cur.execute("""INSERT OR IGNORE INTO sistem_yetki
                       (Kod, Ad, Aciklama, Modul, AltModul, Sira)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (kod, ad, ad, modul, alt, sira))
    conn.commit()


def _seed_roller_kullanicilar(conn):
    cur = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    roller = [
        ('Yönetim',  'Tüm modüllere tam erişim.',         '#F97316', 1),
        ('Muhasebe', 'Finans tam, maliyet + beyanname giriş.', '#059669', 0),
        ('Çin Ofis', 'Numune + Çin sipariş. Maliyet görünmez.', '#0891b2', 0),
        ('Gümrük',   'Sevkiyat / beyanname / fatura.',    '#b45309', 0),
        ('Grafik',   'Numune + ürün tanımı.',             '#7c3aed', 0),
        ('Personel', 'Sınırlı görüntüleme.',              '#64748b', 0),
    ]
    rol_id = {}
    for ad, ac, renk, sa in roller:
        cur.execute("""INSERT OR IGNORE INTO sistem_rol
                       (Ad, Aciklama, Renk, Aktif, SuperAdmin, OlusturmaTarih, OlusturanKullanici)
                       VALUES (?, ?, ?, 1, ?, ?, 'sistem')""",
                    (ad, ac, renk, sa, now))
        cur.execute("SELECT Id FROM sistem_rol WHERE Ad = ?", (ad,))
        rol_id[ad] = cur.fetchone()[0]

    # YÖNETİM — tüm yetkiler (gor + duz)
    cur.execute("SELECT Id FROM sistem_yetki")
    tum = [r[0] for r in cur.fetchall()]
    for yid in tum:
        cur.execute("""INSERT OR IGNORE INTO sistem_rol_yetki
                       (RolId, YetkiId, Gorebilir, Duzenleyebilir)
                       VALUES (?, ?, 1, 1)""", (rol_id['Yönetim'], yid))

    cur.execute("SELECT Id, Kod FROM sistem_yetki")
    kod_id = {k: i for i, k in cur.fetchall()}

    def _atama(rolad, gor_kodlar, duz_kodlar):
        rid = rol_id[rolad]
        for k in gor_kodlar:
            yid = kod_id.get(k)
            if yid:
                duz = 1 if k in duz_kodlar else 0
                cur.execute("""INSERT OR REPLACE INTO sistem_rol_yetki
                               (RolId, YetkiId, Gorebilir, Duzenleyebilir)
                               VALUES (?, ?, 1, ?)""", (rid, yid, duz))

    # Muhasebe
    _atama('Muhasebe',
           ['finans','finans.anlasma','finans.cari','finans.odeme',
            'finans.maliyet_goster','grafik.maliyet','grafik.maliyet.beyanname',
            'grafik.cin_siparis','grafik.cin_siparis.maliyet','grafik.analiz'],
           ['finans.anlasma','finans.cari','finans.odeme',
            'grafik.maliyet','grafik.maliyet.beyanname'])
    # Çin Ofis
    _atama('Çin Ofis',
           ['grafik.numune','grafik.cin_siparis','grafik.urun','grafik.tedarikci'],
           ['grafik.numune','grafik.cin_siparis'])
    # Gümrük
    _atama('Gümrük',
           ['grafik.maliyet','grafik.maliyet.beyanname','grafik.cin_siparis'],
           ['grafik.maliyet','grafik.maliyet.beyanname'])
    # Grafik
    _atama('Grafik',
           ['grafik.numune','grafik.urun','grafik.tedarikci','grafik.cin_siparis'],
           ['grafik.numune','grafik.urun'])

    # KULLANICILAR
    kullanicilar = [
        ('admin',    'Sistem Yöneticisi', 'admin@solariz.com.tr', 'admin123', 'Yönetim', 0),
        ('halil',    'Halil',              'halil@solariz.com.tr', '232323',  'Yönetim', 0),
        ('hasan',    'Hasan',              'hasan@solariz.com.tr', '323232',  'Yönetim', 0),
        ('samet',    'Samet (Grafik)',     'samet@solariz.com.tr', '434343',  'Grafik',  0),
        ('cin.ofis', 'Çin Ofisi',          None,                   'Cin2026!', 'Çin Ofis',1),
        ('muhasebe', 'Muhasebe',           None,                   'Muh2026!', 'Muhasebe',1),
    ]
    for kadi, adsoyad, mail, sifre, rol_ad, zorunlu in kullanicilar:
        rid = rol_id.get(rol_ad)
        cur.execute("""INSERT OR IGNORE INTO sistem_kullanici
                       (KullaniciAdi, AdSoyad, Email, Sifre, RolId, Rol, Aktif,
                        ZorunluSifreDegistir, OlusturmaTarih, OlusturanKullanici)
                       VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, 'sistem')""",
                    (kadi, adsoyad, mail, sifre, rid, rol_ad, zorunlu, now))

    conn.commit()


def _seed_kur(conn):
    cur = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    bugun = date.today()
    bas = {'USD': (39.20, 39.50),
           'EUR': (42.80, 43.20),
           'CNY': (5.35,  5.45)}
    for i in range(7):
        t = (bugun - timedelta(days=i)).strftime('%Y-%m-%d')
        for pb, (a, s) in bas.items():
            # Ufak dalgalanma
            delta = (i * 0.05) * (-1 if i % 2 else 1)
            alis  = round(a + delta, 4)
            satis = round(s + delta, 4)
            merkez = round((alis + satis) / 2, 4)
            cur.execute("""INSERT OR IGNORE INTO sistem_kur
                           (Tarih, ParaBirimi, Alis, Satis, MerkezKur, Kaynak,
                            OlusturmaTarih, OlusturanKullanici)
                           VALUES (?, ?, ?, ?, ?, 'MANUEL', ?, 'sistem')""",
                        (t, pb, alis, satis, merkez, now))
    conn.commit()


def _seed_finans(conn):
    cur = conn.cursor()

    # CARİ
    cariler = [
        ('M001', 'Kaplan Tekstil A.Ş.',    1, 'İstanbul', '0212-555-1001'),
        ('M002', 'LC Waikiki Mağazacılık', 1, 'İstanbul', '0216-555-1002'),
        ('M003', 'Esem Ayakkabı San.',     1, 'İzmir',    '0232-555-1003'),
        ('M004', 'DeFacto Perakende',      1, 'İstanbul', '0212-555-1004'),
        ('M005', 'Koton Mağazacılık',      1, 'İstanbul', '0212-555-1005'),
        ('T001', 'EVA Kimya Tedarik',      2, 'Kocaeli',  '0262-555-2001'),
        ('T002', 'Logistics China LTD',    2, 'Shenzhen', None),
    ]
    for ck, cn, ct, sh, tel in cariler:
        cur.execute("""INSERT OR IGNORE INTO Cari_Kart
                       (CKod, CName, CTip, Sehir, Telefon)
                       VALUES (?, ?, ?, ?, ?)""", (ck, cn, ct, sh, tel))

    # ANLAŞMALAR
    anlasmalar = [
        ('KAPLAN-2026-01',  'Kaplan Yaz Koleksiyonu', 'M001', '2026-02-01', '2026-05-15',  4_000_000, 10, 'halil', 'AKTIF'),
        ('LCW-2026-OKUL',   'LCW Okul Sezonu',        'M002', '2026-01-20', '2026-08-01', 28_000_000, 10, 'admin', 'AKTIF'),
        ('ESEM-2026-YAZ',   'Esem Yaz Kampanya',      'M003', '2026-03-01', '2026-07-01', 30_000_000, 10, 'admin', 'AKTIF'),
        ('DEFACTO-2026-IB', 'DeFacto İlkbahar',       'M004', '2026-02-10', '2026-06-10', 35_000_000, 10, 'hasan', 'AKTIF'),
        ('KOTON-2025-KIS',  'Koton Kış Ref.',         'M005', '2025-08-01', '2025-12-15', 12_000_000, 10, 'halil', 'TAMAMLANDI'),
    ]
    for pk, pa, ck, bt, bit, tt, kdv, olu, dr in anlasmalar:
        cur.execute("""INSERT OR IGNORE INTO finans_anlasma
                       (ProjeKod, ProjeAdi, CKod, BaslangicTarih, BitisTarih,
                        ToplamTutar, KdvOrani, Durum, OlusturmaTarih, OlusturanKullanici)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (pk, pa, ck, bt, bit, tt, kdv, dr, bt, olu))

    # Her anlaşmaya 1 model + 2 plan satırı
    cur.execute("SELECT Id, ProjeKod, ToplamTutar, BaslangicTarih FROM finans_anlasma")
    for row in cur.fetchall():
        aid, pk, tt, bt = row
        cur.execute("""INSERT INTO finans_anlasma_model
                       (AnlasmaId, Sira, ModelKod, ModelAdi, Renk, Miktar, BirimFiyat)
                       VALUES (?, 1, ?, ?, 'Karma', ?, ?)""",
                    (aid, f"M-{pk}", f"{pk} Model A", int(tt/200) if tt else 0, 200))
        try:
            bt_date = datetime.strptime(bt, '%Y-%m-%d')
            tarih2 = (bt_date + timedelta(days=60)).strftime('%Y-%m-%d')
        except Exception:
            tarih2 = bt
        cur.execute("""INSERT INTO finans_odeme_plan
                       (AnlasmaId, Sira, PlanTarih, OdemeTipi, Tutar, CekAdeti, Durum, Aciklama)
                       VALUES (?, 1, ?, 'HAVALE', ?, 1, 'BEKLIYOR', 'Peşinat')""",
                    (aid, bt, tt*0.3))
        cur.execute("""INSERT INTO finans_odeme_plan
                       (AnlasmaId, Sira, PlanTarih, OdemeTipi, Tutar, CekAdeti, Durum, Aciklama)
                       VALUES (?, 2, ?, 'CEK', ?, 1, 'BEKLIYOR', 'Sevk sonrası')""",
                    (aid, tarih2, tt*0.7))

    # Kasa + Banka
    cur.execute("INSERT OR IGNORE INTO Kasa_Kart (Id, KasaAd, Doviz, Bakiye) VALUES (1, 'Merkez Kasa', 'TL', 850000)")
    cur.execute("INSERT OR IGNORE INTO Banka_Kart (Id, BankaAd, HesapNo, Doviz, Bakiye) VALUES (1, 'Garanti', '****1234', 'TL', 3250000)")
    cur.execute("INSERT OR IGNORE INTO Banka_Kart (Id, BankaAd, HesapNo, Doviz, Bakiye) VALUES (2, 'İş Bankası', '****5678', 'TL', 1840000)")

    conn.commit()


def _seed_grafik(conn):
    """Grafik modülü altyapı verileri: kategoriler, ürünler, varyantlar, tedarikçiler."""
    cur = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # KATEGORİLER
    kategoriler = [
        ('EVA Terlik',      'Enjeksiyon EVA terliği',     1),
        ('Pach (Süsleme)',  'Üst yüzey baskı/nakış/pach', 2),
        ('Bant Malzemesi',  'Kayış, bant aksesuar',       3),
        ('Ambalaj',         'Kutu, poşet, etiket',        4),
    ]
    kat_id = {}
    for ad, ac, sira in kategoriler:
        cur.execute("""INSERT OR IGNORE INTO grafik_urun_kategori
                       (Ad, Aciklama, Sira, Aktif, OlusturmaTarih)
                       VALUES (?, ?, ?, 1, ?)""", (ad, ac, sira, now))
        cur.execute("SELECT Id FROM grafik_urun_kategori WHERE Ad = ?", (ad,))
        kat_id[ad] = cur.fetchone()[0]

    # ÜRÜNLER + VARYANTLAR
    urunler = [
        # (Kod, Ad, Kategori, [varyant: (renk_ad, renk_hex, beden)...])
        ('TRL-CLSK-01', 'Klasik Düz EVA Terlik', 'EVA Terlik', [
            ('Siyah',  '#000000', '38'), ('Siyah',  '#000000', '40'), ('Siyah',  '#000000', '42'),
            ('Beyaz',  '#FFFFFF', '38'), ('Beyaz',  '#FFFFFF', '40'), ('Beyaz',  '#FFFFFF', '42'),
            ('Lacivert','#1E293B', '40'), ('Lacivert','#1E293B', '42'),
        ]),
        ('TRL-BANT-02', 'Çift Bantlı EVA Terlik', 'EVA Terlik', [
            ('Siyah',  '#000000', '39'), ('Siyah',  '#000000', '41'),
            ('Kırmızı','#DC2626', '39'), ('Kırmızı','#DC2626', '41'),
        ]),
        ('TRL-PRMM-03', 'Premium Yumuşak EVA',  'EVA Terlik', [
            ('Beyaz',  '#FFFFFF', '37'), ('Beyaz',  '#FFFFFF', '39'), ('Beyaz',  '#FFFFFF', '41'),
            ('Gri',    '#6B7280', '39'), ('Gri',    '#6B7280', '41'),
        ]),
        ('PCH-FLWR-01', 'Çiçek Desenli Pach',   'Pach (Süsleme)', [
            ('Karışık','#F27A1A', None),
        ]),
        ('PCH-GEOM-02', 'Geometrik Pach',       'Pach (Süsleme)', [
            ('Mavi',   '#2563EB', None), ('Turuncu','#F27A1A', None),
        ]),
        ('BNT-KLSK-01', 'Klasik PVC Bant',      'Bant Malzemesi', [
            ('Siyah',  '#000000', None), ('Beyaz',  '#FFFFFF', None),
        ]),
        ('AMB-KTKS-01', 'Karton Kutu 40x30x20', 'Ambalaj', [
            ('Kraft',  '#A8A29E', None),
        ]),
    ]
    for kod, ad, kat_ad, varyantlar in urunler:
        cur.execute("""INSERT OR IGNORE INTO grafik_urun
                       (Kod, Ad, KategoriId, Aktif, OlusturmaTarih, OlusturanKullanici)
                       VALUES (?, ?, ?, 1, ?, 'sistem')""",
                    (kod, ad, kat_id[kat_ad], now))
        cur.execute("SELECT Id FROM grafik_urun WHERE Kod = ?", (kod,))
        uid = cur.fetchone()[0]
        for i, (renk_ad, renk_hex, beden) in enumerate(varyantlar, 1):
            v_kod = f"{kod}-{i:02d}"
            cur.execute("""INSERT OR IGNORE INTO grafik_urun_varyant
                           (UrunId, Kod, RenkAd, RenkHex, Beden, Aktif, OlusturmaTarih)
                           VALUES (?, ?, ?, ?, ?, 1, ?)""",
                        (uid, v_kod, renk_ad, renk_hex, beden, now))

    # TEDARİKÇİLER (Çin ağırlıklı)
    tedarikciler = [
        ('DG-LIGHT',  'Dongguan Light Pach Co., Ltd.',    'Dongguan',  'Çin',     'Jack Liu',    'jack@lightpach.cn', '+86 138 2666 1111', 'jack_lightpach', 'FOB', 45,  'Pach/baskı uzmanı, küçük miktar kabul'),
        ('GZ-PVC',    'Guangzhou PVC Accessories Ltd.',   'Guangzhou', 'Çin',     'Mrs. Wu',     'wu@gzpvc.cn',       '+86 136 2888 2222', 'gzpvc_wu',       'FOB', 60,  'Büyük miktar PVC bant tedariki'),
        ('YW-TRIM',   'Yiwu Fashion Trim Co.',            'Yiwu',      'Çin',     'Tony Zhang',  'tony@ywtrim.cn',    '+86 139 8888 3333', 'ywtrim_tony',    'CIF', 30,  'Aksesuar + hızlı numune'),
        ('EVA-KOC',   'EVA Kimya Tedarik A.Ş.',           'Kocaeli',   'Türkiye', 'Mehmet Bey',  'mehmet@evakimya.com','0262 555 2001',    '',               'EXW', 90,  'Yerli EVA hammadde'),
    ]

    # Çin tedarikçileri için Cari_Kart'ta kayıt yoksa oluştur + eşle
    # (INSERT OR REPLACE ile finans mock'daki yanlış isimleri üzerine yaz)
    tedarikci_cari_map = {
        'DG-LIGHT':  ('T001', 'Dongguan Light Pach Co., Ltd.'),
        'GZ-PVC':    ('T002', 'Guangzhou PVC Accessories Ltd.'),
        'YW-TRIM':   ('T003', 'Yiwu Fashion Trim Co.'),
        'EVA-KOC':   ('T004', 'EVA Kimya Tedarik A.Ş.'),
    }
    for ted_kod, (ckod, cname) in tedarikci_cari_map.items():
        cur.execute("""INSERT OR REPLACE INTO Cari_Kart
                       (CKod, CName, CTip, Sehir, Aktif)
                       VALUES (?, ?, 2, NULL, 1)""", (ckod, cname))

    for kod, ad, sh, ul, il, em, wa, wc, nt, vg, notu in tedarikciler:
        cari_ckod = tedarikci_cari_map.get(kod, (None, None))[0]
        cur.execute("""INSERT OR IGNORE INTO grafik_tedarikci
                       (Kod, Ad, Sehir, Ulke, Iletisim, Email, WhatsApp, WeChat,
                        NakliyeTipi, VadeGun, CariCKod, Notlar, Aktif, OlusturmaTarih, OlusturanKullanici)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'sistem')""",
                    (kod, ad, sh, ul, il, em, wa, wc, nt, vg, cari_ckod, notu, now))

    # NUMUNELER (4 farklı durumda)
    # Önce id'leri bulalım
    cur.execute("SELECT Id FROM grafik_tedarikci WHERE Kod='DG-LIGHT'");  ted_dg = cur.fetchone()[0]
    cur.execute("SELECT Id FROM grafik_tedarikci WHERE Kod='GZ-PVC'");    ted_gz = cur.fetchone()[0]
    cur.execute("SELECT Id FROM grafik_tedarikci WHERE Kod='YW-TRIM'");   ted_yw = cur.fetchone()[0]
    cur.execute("SELECT Id FROM grafik_urun WHERE Kod='PCH-FLWR-01'");    urn_pach = cur.fetchone()[0]
    cur.execute("SELECT Id FROM grafik_urun WHERE Kod='BNT-KLSK-01'");    urn_bant = cur.fetchone()[0]
    cur.execute("SELECT Id FROM grafik_urun WHERE Kod='PCH-GEOM-02'");    urn_geom = cur.fetchone()[0]
    cur.execute("SELECT Id FROM grafik_urun WHERE Kod='TRL-BANT-02'");    urn_terl = cur.fetchone()[0]

    numuneler = [
        # (NumuneNo, Baslik, MusteriCKod, TedarikciId, UrunId, Durum, TalepTarihi, BeklenenTarih, Notlar)
        ('NUM-2026-0001', 'Kaplan için çiçek desen pach',    'M001', ted_dg, urn_pach,
         'ONAY',        '2026-03-15', '2026-04-05',
         'İlk iterasyon onaylandı, küçük renk tonlama değişikliği istendi'),
        ('NUM-2026-0002', 'LCW okul serisi PVC bant',        'M002', ted_gz, urn_bant,
         'GONDERILDI',  '2026-04-01', '2026-04-25',
         'Siyah ve beyaz iki renk numune istendi, nakliye Dongguan üzerinden'),
        ('NUM-2026-0003', 'Esem spor geometrik pach',        'M003', ted_yw, urn_geom,
         'RED',         '2026-03-20', '2026-04-10',
         'İlk iterasyonda renkler çok soluk çıktı, revize istendi'),
        ('NUM-2026-0004', 'DeFacto çift bantlı terlik',      'M004', ted_gz, urn_terl,
         'TAMAMLANDI',  '2026-02-10', '2026-03-01',
         'Onaylandı ve sipariş açıldı (CIN-2026-0001 ile bağlı)'),
    ]
    for no, bas, mck, tid, uid_, dr, tt, bt, no_ in numuneler:
        cur.execute("""INSERT OR IGNORE INTO grafik_numune
                       (NumuneNo, Baslik, MusteriCKod, TedarikciId, UrunId, Durum,
                        TalepTarihi, BeklenenTarih, Notlar, OlusturmaTarih, OlusturanKullanici)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'samet')""",
                    (no, bas, mck, tid, uid_, dr, tt, bt, no_, tt))

    # İTERASYONLAR
    cur.execute("SELECT Id, NumuneNo FROM grafik_numune")
    numune_id = {r[1]: r[0] for r in cur.fetchall()}

    iterasyonlar = [
        # NUM-2026-0001 (Kaplan, ONAY): 2 iterasyon
        ('NUM-2026-0001', 1, '2026-03-15', 'GONDERIM',  'Proforma + teknik çizim gönderildi'),
        ('NUM-2026-0001', 2, '2026-03-28', 'ALINDI',    'Numune geldi, Adem ve Kaplan ekibi inceledi'),
        ('NUM-2026-0001', 3, '2026-04-02', 'ONAY',      'Onay verildi, renk tonlaması netleştirildi (Pantone 137C)'),

        # NUM-2026-0002 (LCW, GONDERILDI): 1 iterasyon
        ('NUM-2026-0002', 1, '2026-04-01', 'GONDERIM',  'Teknik dosya + renk örnekleri WeChat ile iletildi'),

        # NUM-2026-0003 (Esem, RED): 2 iterasyon
        ('NUM-2026-0003', 1, '2026-03-20', 'GONDERIM',  'İlk numune talebi — parlak renk istendi'),
        ('NUM-2026-0003', 2, '2026-04-05', 'RED',       'Renkler soluk çıktı, revize istendi. Tedarikçi boyama makinesi değiştirecek'),

        # NUM-2026-0004 (DeFacto, TAMAMLANDI): 3 iterasyon
        ('NUM-2026-0004', 1, '2026-02-10', 'GONDERIM',  'Numune talebi, 2 renk'),
        ('NUM-2026-0004', 2, '2026-02-18', 'ALINDI',    'Numune DHL ile geldi'),
        ('NUM-2026-0004', 3, '2026-02-25', 'ONAY',      'Küçük revizyonla onaylandı'),
        ('NUM-2026-0004', 4, '2026-03-01', 'REVIZYON',  'Kayış genişliği 1mm artırıldı, son numune bu hafta'),
    ]
    for nno, sira, tar, dr, fb in iterasyonlar:
        if nno in numune_id:
            cur.execute("""INSERT INTO grafik_numune_iterasyon
                           (NumuneId, Sira, Tarih, Durum, FeedbackNotu, OlusturanKullanici, OlusturmaTarih)
                           VALUES (?, ?, ?, ?, ?, 'samet', ?)""",
                        (numune_id[nno], sira, tar, dr, fb, tar))

    # ÇİN SİPARİŞLERİ
    # Varyant id'leri
    cur.execute("SELECT Id FROM grafik_urun_varyant WHERE UrunId=? LIMIT 1", (urn_pach,)); v_pach = cur.fetchone()[0]
    cur.execute("SELECT Id FROM grafik_urun_varyant WHERE UrunId=? LIMIT 1", (urn_bant,)); v_bant = cur.fetchone()[0]
    cur.execute("SELECT Id FROM grafik_urun_varyant WHERE UrunId=? LIMIT 1", (urn_terl,)); v_terl = cur.fetchone()[0]

    # CIN-2026-0001: TAMAMLANDI (DeFacto numunesinden, GZ-PVC, finans anlaşması bağlı)
    # Önce finans anlaşması oluştur, sonra ID'yi siparişe bağla
    cur.execute("""INSERT OR IGNORE INTO finans_anlasma
                   (ProjeKod, ProjeAdi, CKod, ToplamTutar, ParaBirimi, Durum,
                    BaslangicTarih, KaynakModul, KaynakKayitId, OlusturmaTarih, OlusturanKullanici, Notlar)
                   VALUES ('CIN-2026-0001', 'Çin Sipariş: DeFacto bant (GZ-PVC)', 'T002', 245280, 'TRY',
                           'AKTIF', '2026-03-05', 'grafik_cin_siparis', 1, ?, 'admin',
                           'Otomatik — Çin sipariş onayı. USD kuru: 30.66 anlık snapshot.')""", (now,))
    cur.execute("SELECT Id FROM finans_anlasma WHERE ProjeKod='CIN-2026-0001'")
    an1 = cur.fetchone()[0]

    siparisler = [
        # (SiparisNo, TedKod, NumuneNo, MusteriCKod, SiparisTarihi, BeklenenCikis, Durum, Toplam, Notlar, Kur, OnayTarihi, OnayUser, AnlasmaId)
        ('CIN-2026-0001', 'GZ-PVC',   'NUM-2026-0004', 'M004', '2026-03-05', '2026-05-15', 'TAMAMLANDI',
         8000.00, 'DeFacto kış sezonu ilk parti', 30.66, '2026-03-05 10:00:00', 'admin', an1),
        ('CIN-2026-0002', 'DG-LIGHT', 'NUM-2026-0001', 'M001', '2026-04-10', '2026-06-01', 'ONAYLANDI',
         6500.00, 'Kaplan için çiçek pach üretim sipariş', 39.32, '2026-04-10 14:30:00', 'admin', None),
        ('CIN-2026-0003', 'YW-TRIM',  None,             'M003', '2026-04-22', '2026-06-30', 'TASLAK',
         0.00, 'Esem için yeni geometrik pach — kalemler hazırlanıyor', None, None, None, None),
    ]
    for sno, tkod, nno, mck, st, bc, dr, tt, no_, kur, onay_tr, onay_u, aid in siparisler:
        cur.execute("SELECT Id FROM grafik_tedarikci WHERE Kod=?", (tkod,))
        tid = cur.fetchone()[0]
        nid = numune_id.get(nno) if nno else None
        cur.execute("""INSERT OR IGNORE INTO grafik_cin_siparis
                       (SiparisNo, TedarikciId, KaynakNumuneId, MusteriCKod,
                        SiparisTarihi, BeklenenCikisTarihi, ParaBirimi, KurSnapshot,
                        ToplamTutar, Durum, Notlar, OlusturmaTarih, OlusturanKullanici,
                        OnayTarihi, OnaylayanKullanici, FinansAnlasmaId)
                       VALUES (?, ?, ?, ?, ?, ?, 'USD', ?, ?, ?, ?, ?, 'admin', ?, ?, ?)""",
                    (sno, tid, nid, mck, st, bc, kur, tt, dr, no_, st, onay_tr, onay_u, aid))

    # KALEMLER (sadece ilk 2 sipariş için - 3.sü TASLAK, boş)
    cur.execute("SELECT Id FROM grafik_cin_siparis WHERE SiparisNo='CIN-2026-0001'"); s1 = cur.fetchone()[0]
    cur.execute("SELECT Id FROM grafik_cin_siparis WHERE SiparisNo='CIN-2026-0002'"); s2 = cur.fetchone()[0]
    kalemler = [
        # (SiparisId, VaryantId, UrunId, Aciklama, Miktar, BirimFiyat, Tutar, AgirlikKg, HacimM3)
        (s1, v_terl, urn_terl, 'Siyah 39',   4000, 1.20, 4800.00, 800.0, 8.5),
        (s1, v_terl, urn_terl, 'Kirmizi 39', 2000, 1.20, 2400.00, 400.0, 4.2),
        (s1, v_terl, urn_terl, 'Siyah 41',    667, 1.20,  800.00, 140.0, 1.5),
        (s2, v_pach, urn_pach, 'Cicek pach A4 kesim', 5000, 0.80, 4000.00, 120.0, 0.8),
        (s2, v_pach, urn_pach, 'Cicek pach kucuk',    5000, 0.50, 2500.00,  80.0, 0.5),
    ]
    for sid, vid, uid_, ac, mk, bf, tut, agr, hac in kalemler:
        cur.execute("""INSERT INTO grafik_cin_siparis_kalem
                       (SiparisId, VaryantId, UrunId, Aciklama, Miktar, BirimFiyat, Tutar,
                        AgirlikKg, HacimM3, OlusturmaTarih)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (sid, vid, uid_, ac, mk, bf, tut, agr, hac, now))

    # SEVKIYAT: CIN-2026-0001 icin TESLIM, masraflar girilmis, dagitim henuz hesaplanmamis
    cur.execute("""INSERT OR IGNORE INTO grafik_sevkiyat
                   (SevkiyatNo, SiparisId, NakliyeTipi, Forwarder, Konsimento,
                    SevkTarihi, BeklenenVarisTarihi, GerceklesenVarisTarihi,
                    ToplamMasrafTL, DagitimYontemi, DagitimHesaplandi, Durum, Notlar,
                    OlusturmaTarih, OlusturanKullanici)
                   VALUES ('SVK-2026-0001', ?, 'KONTEYNER', 'Hacizade Denizcilik', 'MSCU-5551234',
                           '2026-04-20', '2026-05-12', '2026-05-10',
                           0, 'FOB', 0, 'TESLIM',
                           'Shenzhen -> Istanbul 20ft konteyner. Demo: Dagitimi Hesapla butonuna basip kalem basi maliyete bak.',
                           ?, 'admin')""", (s1, now))
    cur.execute("SELECT Id FROM grafik_sevkiyat WHERE SevkiyatNo='SVK-2026-0001'")
    sevk1 = cur.fetchone()[0]

    # Masraflar (Gercekci konteyner - 8 kalem)
    # Tip, BirimSayi, BirimFiyat, Tutar, PB, Kur, TutarTL, BelgeNo, Aciklama
    masraflar = [
        ('NAVLUN_DENIZ', 1,    1850.00,  1850.00, 'USD', 30.66, 56721.00, 'INV-MSC-991',   '20ft konteyner x 1 adet - Shenzhen->Istanbul'),
        ('YUKLEME',      0,       0.00,   120.00, 'USD', 30.66,  3679.20, 'SZX-LOAD-12',   'Shenzhen limani yukleme'),
        ('THC',          0,       0.00,    80.00, 'USD', 30.66,  2452.80, 'MSC-THC-551',   'Terminal Handling Charge'),
        ('SIGORTA',      0,       0.00,   120.00, 'USD', 30.66,  3679.20, 'AXA-2026-551',  'Yuk sigortasi (%0.3)'),
        ('GUMRUK',       0,       0.00, 28500.00, 'TRY',  1.00, 28500.00, 'GTB-880123',    'Gumruk beyanname + vergi'),
        ('MUSAVIR',      0,       0.00,  3500.00, 'TRY',  1.00,  3500.00, 'ARZ-2026-12',   'Gumruk musaviri'),
        ('EVRAK',        0,       0.00,   850.00, 'TRY',  1.00,   850.00, None,            'Evrak + dosyalama'),
        ('IC_NAKLIYE',   0,       0.00,  6800.00, 'TRY',  1.00,  6800.00, None,            'Liman-depo ic tasima'),
    ]
    toplam = 0
    for tip, bs, bf, tu, pb, kur, ttl, bn, ac in masraflar:
        cur.execute("""INSERT INTO grafik_sevkiyat_masraf
                       (SevkiyatId, Tip, BirimSayi, BirimFiyat, Tutar, ParaBirimi, IslemTarih, KurSnapshot, TutarTL,
                        BelgeNo, Aciklama, OlusturmaTarih, OlusturanKullanici)
                       VALUES (?, ?, ?, ?, ?, ?, '2026-04-18', ?, ?, ?, ?, ?, 'hasan')""",
                    (sevk1, tip, bs, bf, tu, pb, kur, ttl, bn, ac, now))
        toplam += ttl
    cur.execute("UPDATE grafik_sevkiyat SET ToplamMasrafTL=? WHERE Id=?", (toplam, sevk1))

    # SEVKIYAT 2: CIN-2026-0002 icin UCAK (HAZIRLIK, tahmini)
    cur.execute("""INSERT OR IGNORE INTO grafik_sevkiyat
                   (SevkiyatNo, SiparisId, NakliyeTipi, Forwarder, Konsimento,
                    AgirlikKg, SevkTarihi, BeklenenVarisTarihi,
                    ToplamMasrafTL, DagitimYontemi, DagitimHesaplandi, Durum, Notlar,
                    OlusturmaTarih, OlusturanKullanici)
                   VALUES ('SVK-2026-0002', ?, 'UCAK', 'Turkish Cargo', 'TK-8821-2026',
                           280.0, '2026-05-10', '2026-05-15',
                           0, 'AGIRLIK', 0, 'HAZIRLIK',
                           'Kaplan siparisi - hizli teslim icin ucak. Navlun kg bazli. Tahmini.',
                           ?, 'admin')""", (s2, now))
    cur.execute("SELECT Id FROM grafik_sevkiyat WHERE SevkiyatNo='SVK-2026-0002'")
    sevk2 = cur.fetchone()[0]

    masraflar2 = [
        ('NAVLUN', 280.0, 4.50,  1260.00, 'USD', 39.35, 49581.00, None, 'Ucak navlun 280 kg x $4.50/kg'),
        ('GUMRUK',   0,   0.00,  8500.00, 'TRY',  1.00,  8500.00, None, 'Tahmini gumruk'),
    ]
    toplam2 = 0
    for tip, bs, bf, tu, pb, kur, ttl, bn, ac in masraflar2:
        cur.execute("""INSERT INTO grafik_sevkiyat_masraf
                       (SevkiyatId, Tip, BirimSayi, BirimFiyat, Tutar, ParaBirimi, IslemTarih, KurSnapshot, TutarTL,
                        BelgeNo, Aciklama, OlusturmaTarih, OlusturanKullanici)
                       VALUES (?, ?, ?, ?, ?, ?, '2026-05-05', ?, ?, ?, ?, ?, 'admin')""",
                    (sevk2, tip, bs, bf, tu, pb, kur, ttl, bn, ac, now))
        toplam2 += ttl
    cur.execute("UPDATE grafik_sevkiyat SET ToplamMasrafTL=? WHERE Id=?", (toplam2, sevk2))

    # SEVKIYAT 3: DHL numune - Kaplan (CN->TR, operasyonel gider)
    n_kaplan_id = numune_id.get('NUM-2026-0001')
    if n_kaplan_id:
        cur.execute("""INSERT OR IGNORE INTO grafik_sevkiyat
                       (SevkiyatNo, NumuneId, NakliyeTipi, Forwarder,
                        TakipNo, GonderimYonu, UrunMaliyetineDahil, AgirlikKg,
                        SevkTarihi, BeklenenVarisTarihi, GerceklesenVarisTarihi,
                        ToplamMasrafTL, DagitimYontemi, DagitimHesaplandi, Durum, Notlar,
                        OlusturmaTarih, OlusturanKullanici)
                       VALUES ('SVK-2026-0003', ?, 'DHL', 'DHL',
                               'JD014600112233CN', 'CN_TR', 0, 2.5,
                               '2026-03-25', '2026-03-28', '2026-03-28',
                               0, 'FOB', 0, 'TESLIM',
                               'Kaplan cicek pach numunesi. Operasyonel gider - urune yansimaz.',
                               ?, 'samet')""", (n_kaplan_id, now))
        cur.execute("SELECT Id FROM grafik_sevkiyat WHERE SevkiyatNo='SVK-2026-0003'")
        sevk3 = cur.fetchone()[0]
        cur.execute("""INSERT INTO grafik_sevkiyat_masraf
                       (SevkiyatId, Tip, BirimSayi, BirimFiyat, Tutar, ParaBirimi, IslemTarih, KurSnapshot, TutarTL,
                        BelgeNo, Aciklama, OlusturmaTarih, OlusturanKullanici)
                       VALUES (?, 'DHL', 2.5, 72.00, 180.00, 'USD', '2026-03-25', 30.66, 5519,
                               'JD014600112233CN', 'DHL numune kargo 2.5 kg Cin->TR',
                               ?, 'samet')""", (sevk3, now))
        cur.execute("UPDATE grafik_sevkiyat SET ToplamMasrafTL=5519 WHERE Id=?", (sevk3,))

    # SEVKIYAT 4: CIN-2026-0001'e IKINCI sevkiyat (Parça 4 - parçalı sevkiyat demo)
    # NOT: SVK-0001 (TESLIM, 106K TL) zaten var. Bu ikinci sevkiyat kalan kısım için.
    # Kritik: sipariş toplam tutarını, finans anlaşmasını ve cari bakiyeyi DEĞİŞTİRMİYOR.
    # Sadece yeni bir sevkiyat kaydı + tahmini gümrük masrafı.
    cur.execute("""INSERT OR IGNORE INTO grafik_sevkiyat
                   (SevkiyatNo, SiparisId, NakliyeTipi, Forwarder, Konsimento,
                    SevkTarihi, BeklenenVarisTarihi,
                    ToplamMasrafTL, DagitimYontemi, DagitimHesaplandi, Durum, Notlar,
                    OlusturmaTarih, OlusturanKullanici)
                   VALUES ('SVK-2026-0004', ?, 'KONTEYNER', 'MSC', 'MSC-PARCALI-882',
                           '2026-05-02', '2026-06-10',
                           0, 'AGIRLIK', 0, 'YOLDA',
                           'CIN-0001 siparisinin ikinci partisi - parçali sevkiyat demo. Kalan kalemler konteynerle. Masraflar tahmini.',
                           ?, 'admin')""", (s1, now))
    cur.execute("SELECT Id FROM grafik_sevkiyat WHERE SevkiyatNo='SVK-2026-0004'")
    sevk4 = cur.fetchone()[0]

    # Tahmini gümrük masrafı (sadece 1 satır - sevkiyat daha yolda)
    cur.execute("""INSERT INTO grafik_sevkiyat_masraf
                   (SevkiyatId, Tip, BirimSayi, BirimFiyat, Tutar, ParaBirimi, IslemTarih, KurSnapshot, TutarTL,
                    BelgeNo, Aciklama, OlusturmaTarih, OlusturanKullanici)
                   VALUES (?, 'GUMRUK', 0, 0, 15000, 'TRY', '2026-05-02', 1.00, 15000,
                           NULL, 'Tahmini gumruk (konteyner henuz gumrukte degil)',
                           ?, 'admin')""", (sevk4, now))
    cur.execute("UPDATE grafik_sevkiyat SET ToplamMasrafTL=15000 WHERE Id=?", (sevk4,))

    # ===================================================================
    # PARÇA 6 / UAT SENARYO 9: Farklı tarihli masraf / kur snapshot demo
    # CIN-2026-0005 + SVK-2026-0005 + 3 farklı kur masraf + M099 demo müşteri
    # ===================================================================

    # --- Geçmiş tarihli kurlar (demo: o günlerde bu kur vardı) ---
    gecmis_kurlar = [
        ('2026-02-10', 'USD', 28.45, 28.55, 28.50),
        ('2026-03-20', 'USD', 32.05, 32.15, 32.10),
        ('2026-04-05', 'EUR', 40.75, 40.85, 40.80),
        ('2026-04-05', 'CNY', 4.82,  4.88,  4.85),
    ]
    for tarih, pb, alis, satis, merkez in gecmis_kurlar:
        cur.execute("""INSERT OR IGNORE INTO sistem_kur
                       (Tarih, ParaBirimi, Alis, Satis, MerkezKur, Kaynak, OlusturmaTarih, OlusturanKullanici)
                       VALUES (?, ?, ?, ?, ?, 'MANUEL', ?, 'sistem')""",
                    (tarih, pb, alis, satis, merkez, now))

    # --- M099 Demo Yaz Buyer müşterisi ---
    cur.execute("""INSERT OR IGNORE INTO Cari_Kart
                   (CKod, CName, CTip, Ulke, Bakiye, Aktif)
                   VALUES ('M099', 'Demo Yaz Buyer (Senaryo 9)', 'MUSTERI', 'TR', 0, 1)""")

    # --- CIN-2026-0005 sipariş ---
    cur.execute("""INSERT OR IGNORE INTO grafik_cin_siparis
                   (SiparisNo, TedarikciId, MusteriCKod, Durum, ParaBirimi, KurSnapshot,
                    ToplamTutar, BeklenenCikisTarihi, Notlar, OlusturmaTarih, OlusturanKullanici)
                   VALUES ('CIN-2026-0005', 1, 'M099', 'SEVKEDILDI', 'USD', 32.10,
                           12500, '2026-02-05',
                           'DEMO: Farkli tarihli masraf senaryosu (UAT Senaryo 9). Her masraf kendi kur snapshot ini korur.',
                           '2026-01-20 10:00:00', 'admin')""")
    cur.execute("SELECT Id FROM grafik_cin_siparis WHERE SiparisNo='CIN-2026-0005'")
    s5 = cur.fetchone()[0]

    # --- 2 kalem ---
    cur.execute("""INSERT OR IGNORE INTO grafik_cin_siparis_kalem
                   (SiparisId, VaryantId, UrunId, Aciklama, Miktar, BirimFiyat, Tutar,
                    AgirlikKg, HacimM3, CiftSayi, OlusturmaTarih)
                   VALUES (?, NULL, NULL, 'Yaz 2026 Slim PVC Aplik (DEM-SLM-01)', 4000, 1.50, 6000, 130, 0.9, 4000, ?)""",
                (s5, now))
    cur.execute("""INSERT OR IGNORE INTO grafik_cin_siparis_kalem
                   (SiparisId, VaryantId, UrunId, Aciklama, Miktar, BirimFiyat, Tutar,
                    AgirlikKg, HacimM3, CiftSayi, OlusturmaTarih)
                   VALUES (?, NULL, NULL, 'Yaz 2026 Genis Bant (DEM-BNT-02)', 2500, 2.60, 6500, 90, 0.6, 2500, ?)""",
                (s5, now))

    # --- SVK-2026-0005 ---
    cur.execute("""INSERT OR IGNORE INTO grafik_sevkiyat
                   (SevkiyatNo, SiparisId, NakliyeTipi, Forwarder, Konsimento,
                    SevkTarihi, BeklenenVarisTarihi, GerceklesenVarisTarihi,
                    ToplamMasrafTL, DagitimYontemi, DagitimHesaplandi, Durum, Notlar,
                    OlusturmaTarih, OlusturanKullanici)
                   VALUES ('SVK-2026-0005', ?, 'KONTEYNER', 'Maersk', 'MSC-DEMO-905',
                           '2026-02-05', '2026-04-10', '2026-04-08',
                           0, 'AGIRLIK', 0, 'TESLIM',
                           'DEMO (UAT Senaryo 9): 3 farkli tarihli masraf. Her satir kendi kurunu korur, bugunku kur uygulanmaz.',
                           '2026-01-20 10:00:00', 'admin')""", (s5,))
    cur.execute("SELECT Id FROM grafik_sevkiyat WHERE SevkiyatNo='SVK-2026-0005'")
    sevk5 = cur.fetchone()[0]

    # --- 3 masraf (3 farklı tarih, 3 farklı kur, 3 farklı PB) ---
    parca6_masraflar = [
        # (Tip,       IslemTarih,    PB,    Tutar,  KurSnapshot, TutarTL,  BelgeNo,       Aciklama)
        ('NAVLUN',    '2026-02-10', 'USD', 2000,   28.50,       57000,    'MSC-INV-88',  'Deniz navlunu (Subat kuru)'),
        ('GUMRUK',    '2026-03-20', 'TRY', 28500,  1.0000,      28500,    'GB-2026-334', 'Gumruk vergisi (Mart odeme)'),
        ('ARDIYE',    '2026-04-05', 'EUR', 500,    40.80,       20400,    'ARD-405',     'Limanda ardiye (Nisan Euro kuru)'),
    ]
    for tip, tarih, pb, tutar, kur, tl, belge, aciklama in parca6_masraflar:
        cur.execute("""INSERT INTO grafik_sevkiyat_masraf
                       (SevkiyatId, Tip, BirimSayi, BirimFiyat, Tutar, ParaBirimi,
                        IslemTarih, KurSnapshot, TutarTL, BelgeNo, Aciklama,
                        OlusturmaTarih, OlusturanKullanici)
                       VALUES (?, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, 'admin')""",
                    (sevk5, tip, tutar, pb, tarih, kur, tl, belge, aciklama, now))

    toplam_masraf_tl = sum(m[5] for m in parca6_masraflar)  # 105900
    cur.execute("UPDATE grafik_sevkiyat SET ToplamMasrafTL=? WHERE Id=?",
                (toplam_masraf_tl, sevk5))

    # --- Finans anlaşması (M099 üzerinde, mevcut cari bakiyeleri etkilemez) ---
    an5_tutar = 12500 * 32.10  # 401.250 TRY
    cur.execute("""INSERT OR IGNORE INTO finans_anlasma
                   (ProjeKod, ProjeAdi, CKod, ToplamTutar, ParaBirimi,
                    BaslangicTarih, Durum, Notlar,
                    OlusturmaTarih, OlusturanKullanici)
                   VALUES ('CIN-2026-0005', 'Cin Siparis 0005 (Demo)', 'M099', ?, 'TRY',
                           '2026-02-05', 'AKTIF',
                           'DEMO: Senaryo 9 icin Parca 6 demo anlasmasi',
                           ?, 'admin')""",
                (an5_tutar, now))
    cur.execute("SELECT Id FROM finans_anlasma WHERE ProjeKod='CIN-2026-0005'")
    _r = cur.fetchone()
    if not _r:
        raise RuntimeError("CIN-2026-0005 anlaşması eklenememiş!")
    an5 = _r[0]

    # Ödeme planı — basit tek taksit (peşinat) + bekleyen kalan
    cur.execute("""INSERT INTO finans_odeme_plan
                   (AnlasmaId, Sira, PlanTarih, OdemeTipi, Tutar, CekAdeti, Durum, Aciklama)
                   VALUES (?, 1, '2026-02-10', 'HAVALE', ?, 1, 'GELDI', 'Pesinat %30')""",
                (an5, round(an5_tutar * 0.3, 2)))
    cur.execute("""INSERT INTO finans_odeme_plan
                   (AnlasmaId, Sira, PlanTarih, OdemeTipi, Tutar, CekAdeti, Durum, Aciklama)
                   VALUES (?, 2, '2026-04-15', 'HAVALE', ?, 1, 'BEKLIYOR', 'Kalan %70')""",
                (an5, round(an5_tutar * 0.7, 2)))

    # Cari_Har — sadece M099 için (mevcut M001-M005 dokunulmadan)
    cur.execute("""INSERT INTO Cari_Har
                   (CKod, Tarih, BelgeTip, BelgeNo, Aciklama, Borc, Alacak)
                   VALUES ('M099', '2026-02-05', 'ANLASMA', 'CIN-2026-0005',
                           'CIN-2026-0005 anlasmasi', ?, 0)""",
                (an5_tutar,))
    cur.execute("""INSERT INTO Cari_Har
                   (CKod, Tarih, BelgeTip, BelgeNo, Aciklama, Borc, Alacak)
                   VALUES ('M099', '2026-02-10', 'ODEME', 'TAHSILAT-0005',
                           'Pesinat tahsilat', 0, ?)""",
                (round(an5_tutar * 0.3, 2),))

    # M099 bakiye güncelleme (sadece M099)
    cur.execute("""UPDATE Cari_Kart
                   SET Bakiye = COALESCE((SELECT SUM(Borc) - SUM(Alacak)
                                          FROM Cari_Har WHERE CKod = 'M099'), 0)
                   WHERE CKod = 'M099'""")

    # -------- CIN-2026-0001 için ÖDEME PLANI + AVANS (demo verileri) --------
    # %30 peşin TT (ödendi) + %70 yükleme öncesi TT (bekliyor)
    cur.execute("SELECT Id FROM finans_anlasma WHERE ProjeKod='CIN-2026-0001'")
    r_an = cur.fetchone()
    if r_an:
        an_id = r_an[0]
        toplam_tl = 245280.00
        pes_tl = round(toplam_tl * 0.30, 2)   # 73.584 TL
        bal_tl = round(toplam_tl * 0.70, 2)   # 171.696 TL

        # Ödeme planı satırları
        cur.execute("""INSERT INTO finans_odeme_plan
                       (AnlasmaId, Sira, PlanTarih, OdemeTipi, Tutar, CekAdeti,
                        Durum, GerceklesenTarih, GerceklesenTutar, Aciklama)
                       VALUES (?, 1, '2026-03-08', 'HAVALE', ?, 1,
                               'GELDI', '2026-03-08', ?,
                               '%30 peşin TT (sipariş onayı ile birlikte)')""",
                    (an_id, pes_tl, pes_tl))
        cur.execute("""INSERT INTO finans_odeme_plan
                       (AnlasmaId, Sira, PlanTarih, OdemeTipi, Tutar, CekAdeti,
                        Durum, Aciklama)
                       VALUES (?, 2, '2026-05-01', 'HAVALE', ?, 1,
                               'BEKLIYOR', '%70 yükleme öncesi TT (B/L sonrası)')""",
                    (an_id, bal_tl))

        # Avans (ödenmiş): aynı %30
        cur.execute("""INSERT INTO finans_avans
                       (AnlasmaId, AvansTarih, Tutar, OdemeTipi, Aciklama)
                       VALUES (?, '2026-03-08', ?, 'HAVALE',
                               'Guangzhou PVC %30 peşin ödeme')""",
                    (an_id, pes_tl))

    # ==================== FİYAT TEKLİFLERİ (MOCK) ====================
    # 3 örnek teklif: ALINDI, REDDEDILDI, SIPARIS_OLDU (CIN-0001'e bağlı)
    cur.execute("""INSERT OR IGNORE INTO grafik_fiyat_teklif
                   (TeklifNo, UlkeKodu, TedarikciId, TedarikciAd, MusteriCKod,
                    UrunAd, UrunKodu, Miktar, BirimFiyat, ParaBirimi,
                    KurSnapshot, ToplamTutar, TeklifTarihi, GecerlilikTarihi,
                    Durum, Notlar, OlusturmaTarih, OlusturanKullanici)
                   VALUES ('TKF-2026-0001', 'CN', 1, 'Guangzhou PVC Accessories Ltd.',
                           'M001', 'PVC Kaplan Cicek Pach', 'PVC-KPL-01',
                           5000, 0.35, 'USD', 30.12, 1750.0,
                           '2026-02-15', '2026-03-15',
                           'SIPARIS_OLDU',
                           'Kaplan cicek pach numunesi onaylandi. Fiyat sabitlendi. MOQ: 3000.',
                           ?, 'hasan')""", (now,))
    # CIN-0001'in SiparisId'sine baglayalim - ama CIN-0001 id'si numune_id yapisi gibi degil
    # Direct sorgu ile bulalim
    cur.execute("SELECT Id FROM grafik_cin_siparis WHERE SiparisNo='CIN-2026-0001'")
    cin1_id = cur.fetchone()
    if cin1_id:
        cur.execute("""UPDATE grafik_fiyat_teklif SET SiparisId=?
                       WHERE TeklifNo='TKF-2026-0001'""", (cin1_id[0],))
        cur.execute("""UPDATE grafik_cin_siparis SET KaynakTeklifId=(
                           SELECT Id FROM grafik_fiyat_teklif WHERE TeklifNo='TKF-2026-0001'
                       ) WHERE Id=?""", (cin1_id[0],))

    # ALINDI durumunda aktif teklif (Çin'den yeni numune)
    cur.execute("""INSERT OR IGNORE INTO grafik_fiyat_teklif
                   (TeklifNo, UlkeKodu, TedarikciId, TedarikciAd, MusteriCKod,
                    UrunAd, UrunKodu, Miktar, BirimFiyat, ParaBirimi,
                    KurSnapshot, ToplamTutar, TeklifTarihi, GecerlilikTarihi,
                    Durum, Notlar, OlusturmaTarih, OlusturanKullanici)
                   VALUES ('TKF-2026-0002', 'CN', 2, 'Dongguan Light Pach Co., Ltd.',
                           'M002', 'LED Light Panel Patch', 'LED-LP-02',
                           3000, 1.20, 'USD', 39.15, 3600.0,
                           '2026-04-10', '2026-05-10',
                           'ALINDI',
                           'DeFacto yaz sezonu icin. Siparise cevrilmeyi bekliyor. Ornek var.',
                           ?, 'admin')""", (now,))

    # Türkiye'den teklif (yerli tedarikçi için)
    cur.execute("""INSERT OR IGNORE INTO grafik_fiyat_teklif
                   (TeklifNo, UlkeKodu, TedarikciId, TedarikciAd, MusteriCKod,
                    UrunAd, UrunKodu, Miktar, BirimFiyat, ParaBirimi,
                    KurSnapshot, ToplamTutar, TeklifTarihi, GecerlilikTarihi,
                    Durum, Notlar, OlusturmaTarih, OlusturanKullanici)
                   VALUES ('TKF-2026-0003', 'TR', NULL, 'Istanbul Kauçuk Sanayi',
                           NULL, 'EVA Taban Malzemesi (45 shore)', 'EVA-45SH',
                           2000, 85.00, 'TRY', 1.00, 170000.0,
                           '2026-04-18', '2026-04-28',
                           'REDDEDILDI',
                           'Fiyat yuksek geldi. Alternatif tedarikci arastiriliyor.',
                           ?, 'admin')""", (now,))

    # ==================== CARİ HAREKET SEED (türetilmiş) ====================
    # Önce: bazı ödeme planlarını GELDI olarak işaretle (demo zenginliği)
    # Kaplan #1 taksidi, LCW #1 taksidi, Esem #1 taksidi, DeFacto #1 taksidi gerçekleşmiş olsun
    cur.execute("""UPDATE finans_odeme_plan SET Durum='GELDI',
                   GerceklesenTarih=PlanTarih, GerceklesenTutar=Tutar
                   WHERE Id IN (1, 3, 5, 7)""")
    # Koton 2025 anlaşması tamamen gerçekleşmiş
    cur.execute("""UPDATE finans_odeme_plan SET Durum='GELDI',
                   GerceklesenTarih=PlanTarih, GerceklesenTutar=Tutar
                   WHERE AnlasmaId = 5""")

    # Cari detay ekranı Cari_Har tablosunu okuyor — mock'ta bu tablo boş olduğu için
    # hareket/borç/alacak 0 görünüyordu. finans_anlasma + finans_avans + odeme_plan
    # kayıtlarından hareket satırları üretiyoruz.
    # Idempotent: önce Cari_Har'ı temizleyip yeniden dolduruyoruz (sadece türetilmiş
    # kayıtlar etkilenir, manuel girilen başka hareket yoksa risk yok).
    cur.execute("DELETE FROM Cari_Har WHERE BelgeTip IN ('ANLASMA','AVANS','ODEME','CEK')")

    # 1) Anlaşmalar → BORÇ (müşteri bize borçlandı)
    #    Tedarikçi anlaşması ise → ALACAK (biz tedarikçiye borçluyuz)
    for r in cur.execute("""SELECT a.Id, a.ProjeKod, a.ProjeAdi, a.CKod, a.BaslangicTarih,
                                   a.ToplamTutar, a.ParaBirimi, c.CTip
                            FROM finans_anlasma a
                            LEFT JOIN Cari_Kart c ON c.CKod = a.CKod
                            WHERE a.CKod IS NOT NULL""").fetchall():
        anl_id, proje, proje_ad, ckod, tarih, tutar, pb, ctip = r
        if not tarih:
            tarih = '2026-01-01'
        # CTip: 1=müşteri (borç), 2=tedarikçi (alacak)
        if ctip == 2:
            borc, alacak = 0, tutar
            acikl = f"Tedarikçi anlaşması - {proje_ad or proje}"
        else:
            borc, alacak = tutar, 0
            acikl = f"Müşteri anlaşması - {proje_ad or proje}"
        cur.execute("""INSERT INTO Cari_Har (CKod, Tarih, BelgeNo, BelgeTip, Aciklama, Borc, Alacak)
                       VALUES (?, ?, ?, 'ANLASMA', ?, ?, ?)""",
                    (ckod, tarih, proje, acikl, borc, alacak))

    # 2) Avanslar → Tedarikçiye ödeme (BORÇ azaltıcı = tedarikçi tarafında BORÇ)
    #                Müşteriden gelen avans (ALACAK azaltıcı = müşteri tarafında ALACAK)
    for r in cur.execute("""SELECT av.Id, av.AnlasmaId, av.AvansTarih, av.Tutar, av.OdemeTipi, av.Aciklama,
                                   a.CKod, a.ProjeKod, c.CTip
                            FROM finans_avans av
                            JOIN finans_anlasma a ON a.Id = av.AnlasmaId
                            LEFT JOIN Cari_Kart c ON c.CKod = a.CKod
                            WHERE a.CKod IS NOT NULL""").fetchall():
        av_id, anl_id, tarih, tutar, tip, aciklama, ckod, proje, ctip = r
        if not tarih:
            continue
        if ctip == 2:
            # Tedarikçi: avans verdik → bizim borç azalır → cari tarafında BORÇ
            borc, alacak = tutar, 0
            acikl = f"Avans ödeme - {proje} ({tip or 'HAVALE'})"
        else:
            # Müşteri: avans aldık → alacağımız azalır → cari tarafında ALACAK
            borc, alacak = 0, tutar
            acikl = f"Avans tahsil - {proje} ({tip or 'HAVALE'})"
        if aciklama:
            acikl = f"{acikl} · {aciklama}"
        cur.execute("""INSERT INTO Cari_Har (CKod, Tarih, BelgeNo, BelgeTip, Aciklama, Borc, Alacak)
                       VALUES (?, ?, ?, 'AVANS', ?, ?, ?)""",
                    (ckod, tarih, f"AVN-{av_id}", acikl, borc, alacak))

    # 3) Ödeme planı satırları (sadece GELDI durumundakiler hareket olur)
    for r in cur.execute("""SELECT op.Id, op.AnlasmaId, op.PlanTarih, op.OdemeTipi, op.Tutar,
                                   op.Durum, op.GerceklesenTarih, op.GerceklesenTutar, op.Sira,
                                   a.CKod, a.ProjeKod, c.CTip
                            FROM finans_odeme_plan op
                            JOIN finans_anlasma a ON a.Id = op.AnlasmaId
                            LEFT JOIN Cari_Kart c ON c.CKod = a.CKod
                            WHERE a.CKod IS NOT NULL AND op.Durum = 'GELDI'""").fetchall():
        pl_id, anl_id, plan_tarih, tip, tutar, durum, grc_tarih, grc_tutar, sira, ckod, proje, ctip = r
        tarih = grc_tarih or plan_tarih
        gerc = grc_tutar or tutar
        if ctip == 2:
            borc, alacak = gerc, 0
            acikl = f"Ödeme - {proje} Taksit {sira} ({tip})"
        else:
            borc, alacak = 0, gerc
            acikl = f"Tahsilat - {proje} Taksit {sira} ({tip})"
        cur.execute("""INSERT INTO Cari_Har (CKod, Tarih, BelgeNo, BelgeTip, Aciklama, Borc, Alacak)
                       VALUES (?, ?, ?, 'ODEME', ?, ?, ?)""",
                    (ckod, tarih, f"ODM-{pl_id}", acikl, borc, alacak))

    # Cari_Kart.Bakiye'yi de güncelle (Borç - Alacak)
    cur.execute("""UPDATE Cari_Kart
                   SET Bakiye = COALESCE((SELECT SUM(Borc) - SUM(Alacak)
                                          FROM Cari_Har WHERE CKod = Cari_Kart.CKod), 0)""")

    # Migration: TESLIM sevkiyatların mevcut dağıtım satırlarını kesinleşmiş olarak işaretle (K1/H1)
    cur.execute("""UPDATE grafik_sevkiyat_dagitim SET IsTahmini=0
                   WHERE SevkiyatId IN (SELECT Id FROM grafik_sevkiyat WHERE Durum='TESLIM')""")

    conn.commit()

    # SVK-0001 (TESLIM) için dağıtım otomatik hesapla → akış çubuğu "Gerçek ₺" adımı yeşil olsun
    try:
        import sys as _sys
        _sys.path.insert(0, '.')
        from modules.grafik import queries as _gq
        _gq.dagitim_hesapla(1, 'admin')
        conn.commit()
    except Exception:
        pass

    # SVK-0005 (TESLIM, Parça 6 demo) dağıtımını hesapla
    try:
        from modules.grafik import queries as _gq
        _gq.dagitim_hesapla(5, 'admin')
        conn.commit()
    except Exception:
        pass

    # ===================================================================
    # PARÇA 7a: Ön Maliyet ve Karar Simülatörü — 3 demo simülasyon
    # ===================================================================
    cur = conn.cursor()

    def _hesap_ve_ekle(sim_id, sira, etiket, veri, hedef_miktar, hedef_satis):
        """Seçeneği hesaplayıp ekle."""
        def f(x, d=0.0):
            try: return float(x or d)
            except: return d
        bf = f(veri.get('BirimFiyat'))
        kur = f(veri.get('KurSnapshot'), 1.0)
        nsab = f(veri.get('NakliyeSabitMaliyet'))
        nbir = f(veri.get('NakliyeBirimMaliyet'))
        nkg = f(veri.get('NakliyeAgirlikKg'))
        nkur = f(veri.get('NakliyeKur'), 1.0)
        vy = f(veri.get('GumrukVergisiYuzde'), 18)
        sy = f(veri.get('SigortaYuzde'), 0.5)
        mus = f(veri.get('MusavirMaliyeti'))
        dig = f(veri.get('DigerMaliyet'))

        fob = bf * hedef_miktar * kur
        nak = nsab * nkur + nbir * nkg * nkur
        sig = fob * sy / 100
        ver = (fob + nak + sig) * vy / 100
        ext = mus + dig
        toplam = fob + nak + sig + ver + ext
        birim = toplam / hedef_miktar if hedef_miktar > 0 else 0
        kg_birim = toplam / nkg if nkg > 0 else 0
        marj = (hedef_satis - birim) / hedef_satis * 100 if hedef_satis else None

        cur.execute("""INSERT INTO finans_simulasyon_secenek
                       (SimulasyonId, Sira, Etiket, Ulke, TedarikciAd, TedarikciId,
                        BirimFiyat, ParaBirimi, KurSnapshot,
                        NakliyeTipi, NakliyeGunSuresi, NakliyeSabitMaliyet, NakliyeBirimMaliyet,
                        NakliyeParaBirimi, NakliyeKur, NakliyeAgirlikKg,
                        GumrukVergisiYuzde, SigortaYuzde, MusavirMaliyeti, DigerMaliyet,
                        ToplamFOB, ToplamNakliye, ToplamSigorta, ToplamVergi, ToplamExtras,
                        ToplamMaliyetTL, BirimMaliyetTL, KgMaliyetTL, MarjYuzde,
                        OlusturmaTarih, OlusturanKullanici)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                               ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'admin')""",
                    (sim_id, sira, etiket,
                     veri.get('Ulke'), veri.get('TedarikciAd'), veri.get('TedarikciId'),
                     bf, veri.get('ParaBirimi', 'USD'), kur,
                     veri.get('NakliyeTipi'), int(veri.get('NakliyeGunSuresi') or 0),
                     nsab, nbir, veri.get('NakliyeParaBirimi', 'USD'), nkur, nkg,
                     vy, sy, mus, dig,
                     round(fob, 2), round(nak, 2), round(sig, 2), round(ver, 2), round(ext, 2),
                     round(toplam, 2), round(birim, 4), round(kg_birim, 4),
                     round(marj, 2) if marj is not None else None,
                     now))
        return cur.lastrowid

    # ========== SIM-2026-0001 — Yaz 2026 PVC Pach (KARAR verilmiş, satış fiyatlı) ==========
    # Not: 10000 adet × $2.50 = $25.000 FOB → ~800K TL → birim ~100 TL
    # Satış fiyatı 130 TL (Bursa ~26 TL/çift toplamın altında, gerçekçi marj senaryosu)
    cur.execute("""INSERT INTO finans_simulasyon
                   (SimulasyonNo, Baslik, UrunAdi, HedefMiktar, HedefCiftSatis,
                    HedefTeslimTarih, Notlar, Durum, KararVerenKullanici, KararTarihi,
                    OlusturmaTarih, OlusturanKullanici)
                   VALUES ('SIM-2026-0001', 'Yaz 2026 PVC Pach Tedarikci Karsilastirma',
                           'Yaz 2026 PVC Pach', 10000, 130.00,
                           '2026-05-30',
                           'DEMO: 3 tedarikci karsilastirmasi — Dongguan konteyner/ucak vs Bursa yerli',
                           'KARAR', 'admin', '2026-04-12 10:30:00',
                           '2026-04-08 09:00:00', 'admin')""")
    sim1 = cur.lastrowid

    # Tedarikçi 1 = Dongguan Light Industry, Tedarikçi 2 = Yiwu Trim
    s1a = _hesap_ve_ekle(sim1, 1, 'Dongguan / Konteyner / 30 gun',
                         {'Ulke': 'CN', 'TedarikciAd': 'Dongguan Light Industry', 'TedarikciId': 1,
                          'BirimFiyat': 2.50, 'ParaBirimi': 'USD', 'KurSnapshot': 32.10,
                          'NakliyeTipi': 'KONTEYNER', 'NakliyeGunSuresi': 30,
                          'NakliyeSabitMaliyet': 1850, 'NakliyeParaBirimi': 'USD', 'NakliyeKur': 32.10,
                          'NakliyeAgirlikKg': 3200,
                          'GumrukVergisiYuzde': 18, 'SigortaYuzde': 0.5,
                          'MusavirMaliyeti': 3500, 'DigerMaliyet': 1000}, 10000, 130.00)

    s1b = _hesap_ve_ekle(sim1, 2, 'Dongguan / Ucak / 7 gun',
                         {'Ulke': 'CN', 'TedarikciAd': 'Dongguan Light Industry', 'TedarikciId': 1,
                          'BirimFiyat': 2.50, 'ParaBirimi': 'USD', 'KurSnapshot': 32.10,
                          'NakliyeTipi': 'UCAK', 'NakliyeGunSuresi': 7,
                          'NakliyeBirimMaliyet': 4.50, 'NakliyeParaBirimi': 'USD', 'NakliyeKur': 32.10,
                          'NakliyeAgirlikKg': 3200,
                          'GumrukVergisiYuzde': 18, 'SigortaYuzde': 0.5,
                          'MusavirMaliyeti': 3500, 'DigerMaliyet': 1000}, 10000, 130.00)

    s1c = _hesap_ve_ekle(sim1, 3, 'Bursa Yerli / Karayolu / 3 gun',
                         {'Ulke': 'TR', 'TedarikciAd': 'Bursa Aksesuar San. A.S.',
                          'BirimFiyat': 22.00, 'ParaBirimi': 'TRY', 'KurSnapshot': 1.0,
                          'NakliyeTipi': 'KARAYOLU', 'NakliyeGunSuresi': 3,
                          'NakliyeSabitMaliyet': 4500, 'NakliyeParaBirimi': 'TRY', 'NakliyeKur': 1.0,
                          'NakliyeAgirlikKg': 3200,
                          'GumrukVergisiYuzde': 0, 'SigortaYuzde': 0,
                          'MusavirMaliyeti': 0, 'DigerMaliyet': 500}, 10000, 130.00)

    # Karar: Seçenek 3 (Bursa — en ucuz + en hızlı + en iyi marj)
    cur.execute("UPDATE finans_simulasyon SET SecilenSecenekId=? WHERE Id=?", (s1c, sim1))

    # ========== SIM-2026-0002 — LCW Bant (TASLAK, satış fiyatlı) ==========
    # Birim maliyet ~80 TL, satış 95 TL → marj ~15%
    cur.execute("""INSERT INTO finans_simulasyon
                   (SimulasyonNo, Baslik, UrunAdi, HedefMiktar, HedefCiftSatis,
                    HedefTeslimTarih, Notlar, Durum, OlusturmaTarih, OlusturanKullanici)
                   VALUES ('SIM-2026-0002', 'LCW Bant Siparisi Karar',
                           'Beyaz Bant', 5000, 95.00,
                           '2026-06-15',
                           'DEMO: 2 tedarikci, karar henuz verilmedi',
                           'TASLAK', '2026-04-14 11:00:00', 'samet')""")
    sim2 = cur.lastrowid

    _hesap_ve_ekle(sim2, 1, 'Yiwu / Konteyner',
                   {'Ulke': 'CN', 'TedarikciAd': 'Yiwu Trim Co.', 'TedarikciId': 2,
                    'BirimFiyat': 1.80, 'ParaBirimi': 'USD', 'KurSnapshot': 32.50,
                    'NakliyeTipi': 'KONTEYNER', 'NakliyeGunSuresi': 32,
                    'NakliyeSabitMaliyet': 1850, 'NakliyeParaBirimi': 'USD', 'NakliyeKur': 32.50,
                    'NakliyeAgirlikKg': 1800,
                    'GumrukVergisiYuzde': 18, 'SigortaYuzde': 0.5,
                    'MusavirMaliyeti': 3500}, 5000, 95.00)

    _hesap_ve_ekle(sim2, 2, 'Dongguan / Konteyner',
                   {'Ulke': 'CN', 'TedarikciAd': 'Dongguan Light Industry', 'TedarikciId': 1,
                    'BirimFiyat': 1.95, 'ParaBirimi': 'USD', 'KurSnapshot': 32.50,
                    'NakliyeTipi': 'KONTEYNER', 'NakliyeGunSuresi': 28,
                    'NakliyeSabitMaliyet': 1850, 'NakliyeParaBirimi': 'USD', 'NakliyeKur': 32.50,
                    'NakliyeAgirlikKg': 1800,
                    'GumrukVergisiYuzde': 18, 'SigortaYuzde': 0.5,
                    'MusavirMaliyeti': 3500}, 5000, 95.00)

    # ========== SIM-2026-0003 — Numune Paket (TASLAK, satış fiyatsız) ==========
    cur.execute("""INSERT INTO finans_simulasyon
                   (SimulasyonNo, Baslik, UrunAdi, HedefMiktar,
                    Notlar, Durum, OlusturmaTarih, OlusturanKullanici)
                   VALUES ('SIM-2026-0003', 'Numune Paket Maliyet Karsilastirma',
                           'Prototip Paket (numune)', 50,
                           'DEMO: Sadece maliyet karsilastirma. Satis fiyati girilmedi — marj hesaplanmaz.',
                           'TASLAK', '2026-04-18 14:00:00', 'samet')""")
    sim3 = cur.lastrowid

    _hesap_ve_ekle(sim3, 1, 'DHL Express',
                   {'Ulke': 'CN', 'TedarikciAd': 'Dongguan Light Industry', 'TedarikciId': 1,
                    'BirimFiyat': 12.00, 'ParaBirimi': 'USD', 'KurSnapshot': 32.50,
                    'NakliyeTipi': 'DHL', 'NakliyeGunSuresi': 5,
                    'NakliyeSabitMaliyet': 650, 'NakliyeParaBirimi': 'USD', 'NakliyeKur': 32.50,
                    'NakliyeAgirlikKg': 15,
                    'GumrukVergisiYuzde': 18, 'SigortaYuzde': 0.5,
                    'MusavirMaliyeti': 500}, 50, None)

    conn.commit()

    # ===================================================================
    # PARÇA 8a: Çin Ofis Excel Import — 1 demo import log
    # ===================================================================
    # DEMO: Kullanılmış bir Excel, BASARILI durumda, sipariş oluşmuş (CIN_IMPORT_KONTROL)
    # Kur: SISTEM_OTOMATIK (USD 32.10 — demo senaryo için mock tarih)
    demo_parse = {
        'INFO': {
            'Order Code': 'CN-OF-2026-DEMO',
            'Supplier Name': 'Dongguan Light Industry',
            'Supplier Contact': 'Mr. Wang +86 139-5555-5555',
            'Total Container Count': 3,
            'Currency': 'USD',
            'Currency Rate': None,
            'Shipment Type': 'SEA',
            'Expected ETD': '2026-05-15',
            'Expected ETA': '2026-06-20',
            'Loading Port': 'Shenzhen',
            'Discharge Port': 'Istanbul',
            'Notes': '2 ana + 1 numune konteyner. Navlun $1850 konteyner basi. Tahmini vergi %18. Musavir 3500 TL.',
        },
        'ITEMS': [
            {'Line #': 1, 'Container Group': 'Main-A', 'Container Type': '40HQ',
             'Container Qty': 2, 'Quality': 'Main', 'Product Name': 'EVA Grade A Compound',
             'Description': 'White, shore 55', 'Qty': 40000, 'Unit': 'kg',
             'Unit Price': 2.10, 'Weight (kg)': 40000},
            {'Line #': 2, 'Container Group': 'Sample-B', 'Container Type': '20GP',
             'Container Qty': 1, 'Quality': 'Sample', 'Product Name': 'EVA Grade B Compound',
             'Description': 'Trial run, black', 'Qty': 18000, 'Unit': 'kg',
             'Unit Price': 2.35, 'Weight (kg)': 18000},
        ],
        'PAYMENT': [
            {'Type': 'Advance TT', 'Ratio': 30, 'Amount': 37890,
             'Due Date': '2026-04-25', 'Trigger': 'Order Confirmation', 'Notes': 'PO sonrasi'},
            {'Type': 'Pre-shipment TT', 'Ratio': 40, 'Amount': 50520,
             'Due Date': '2026-05-12', 'Trigger': 'Before Loading', 'Notes': ''},
            {'Type': 'Post-shipment', 'Ratio': 30, 'Amount': 37890,
             'Due Date': '2026-06-15', 'Trigger': 'After B/L Copy', 'Notes': ''},
        ],
        'FILES': [
            {'File Name': 'proforma_demo.pdf', 'Type': 'Proforma', 'Required': 'Yes',
             'Description': 'Ana proforma'},
            {'File Name': 'eva_photo_demo.jpg', 'Type': 'Image', 'Required': 'No',
             'Description': 'Urun gorseli'},
        ],
        '_lang': 'CN',
        '_template_version': 'v1.0',
    }
    import json as _json
    cur.execute("""INSERT INTO cin_ofis_import_log
                   (OrderCode, DosyaAdi, ParseOzet, Dil, TemplateSurum, Durum,
                    KurPB, KurDeger, KurKaynagi, KurTarihi,
                    SistemKurDeger, ExcelKurDeger, KurFarkiYuzde,
                    OlusturmaTarih, OlusturanKullanici)
                   VALUES ('CN-OF-2026-DEMO', 'demo_cin_ofis_eva.xlsx', ?,
                           'CN', 'v1.0', 'BASARILI',
                           'USD', 32.10, 'SISTEM_OTOMATIK', '2026-05-15',
                           32.10, NULL, 0.0,
                           '2026-04-20 10:30:00', 'admin')""",
                (_json.dumps(demo_parse, ensure_ascii=False),))
    demo_log_id = cur.lastrowid

    # Demo sipariş (CIN_IMPORT_KONTROL durumunda)
    cur.execute("""INSERT INTO grafik_cin_siparis
                   (SiparisNo, TedarikciId, Durum, ParaBirimi, KurSnapshot,
                    ToplamTutar, BeklenenCikisTarihi, Notlar,
                    OlusturmaTarih, OlusturanKullanici)
                   VALUES ('CIN-2026-DEMO', 1, 'CIN_IMPORT_KONTROL', 'USD', 32.10,
                           126300, '2026-05-15',
                           ?,
                           '2026-04-20 10:30:00', 'admin')""",
                ('[ÇİN İÇE AKTARMA] Sipariş Kodu: CN-OF-2026-DEMO\n'
                 'Urun (genel): EVA Grade A Compound\n'
                 'Toplam konteyner: 3\n'
                 'Nakliye: SEA\n'
                 'Limanlar: Shenzhen → Istanbul\n'
                 'Tahmini navlun $1850/konteyner, vergi %18, musavir 3500 TL.',))
    demo_siparis_id = cur.lastrowid

    # Log'a sipariş ID'si yaz
    cur.execute("UPDATE cin_ofis_import_log SET SiparisId=? WHERE Id=?",
                (demo_siparis_id, demo_log_id))

    # Kalemler
    for idx, it in enumerate(demo_parse['ITEMS'], 1):
        cur.execute("""INSERT INTO grafik_cin_siparis_kalem
                       (SiparisId, VaryantId, UrunId, Aciklama, Miktar, CiftSayi,
                        BirimFiyat, Tutar, AgirlikKg, HacimM3, OlusturmaTarih)
                       VALUES (?, NULL, NULL, ?, ?, ?, ?, ?, ?, 0, ?)""",
                    (demo_siparis_id,
                     f'{it["Product Name"]} — {it["Description"]} [{it["Container Group"]} × {it["Container Qty"]}× {it["Container Type"]}]',
                     it['Qty'], it['Qty'], it['Unit Price'],
                     it['Qty'] * it['Unit Price'], it['Weight (kg)'], now))
        kalem_id = cur.lastrowid
        cur.execute("""INSERT INTO cin_ofis_kalem_ek
                       (KalemId, ContainerGroup, ContainerType, ContainerQty,
                        Quality, ProductName, Unit)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (kalem_id, it['Container Group'], it['Container Type'],
                     it['Container Qty'], it['Quality'], it['Product Name'], it['Unit']))

    # Ödeme taslakları
    for i, p in enumerate(demo_parse['PAYMENT'], 1):
        cur.execute("""INSERT INTO cin_ofis_odeme_taslak
                       (ImportLogId, Sira, OdemeTipi, Oran, Tutar, ParaBirimi,
                        PlanTarih, Tetikleyici, Notlar)
                       VALUES (?, ?, ?, ?, ?, 'USD', ?, ?, ?)""",
                    (demo_log_id, i, p['Type'], p['Ratio'], p['Amount'],
                     p['Due Date'], p['Trigger'], p.get('Notes', '')))

    # Dosya referansları
    for i, f in enumerate(demo_parse['FILES'], 1):
        cur.execute("""INSERT INTO cin_ofis_dosya_referans
                       (ImportLogId, Sira, DosyaAdi, DosyaTipi, Gerekli, Aciklama)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (demo_log_id, i, f['File Name'], f['Type'],
                     1 if f['Required'].lower() in ('yes', 'y') else 0,
                     f['Description']))

    conn.commit()


def _seed_cin_ofis_import(conn):
    """
    Parça 8a demo: 1 başarılı Çin Ofis import + kontrol bekleyen sipariş.
    Amaç: UAT sırasında "gerçek gibi" bir örnek göstermek.
    """
    cur = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # EVA senaryosu — başarılı import demo
    order_code = 'CN-OF-2026-DEMO01'

    # Sipariş oluştur — CIN_IMPORT_KONTROL durumunda (henüz müşteri yok)
    cur.execute("""INSERT INTO grafik_cin_siparis
                   (SiparisNo, TedarikciId, Durum, ParaBirimi, KurSnapshot,
                    ToplamTutar, BeklenenCikisTarihi, Notlar, OlusturmaTarih, OlusturanKullanici)
                   VALUES ('CIN-2026-0099', 1, 'CIN_IMPORT_KONTROL', 'USD', 39.3500,
                           126300, '2026-05-15',
                           ?, ?, 'cin.ofis')""",
                (('[ÇİN İÇE AKTARMA DEMO] Sipariş Kodu: CN-OF-2026-DEMO01\n'
                  'Ürün (genel): EVA Grade A Compound\n'
                  'Toplam konteyner: 3 (2 ana + 1 numune)\n'
                  'Nakliye: SEA (Shenzhen → Istanbul)\n'
                  'Limanlar: Shenzhen → Istanbul\n'
                  'Navlun tahmini: $1850 × 3 konteyner = $5550\n'
                  'Vergi tahmini: %18 (KDV dahil)\n'
                  'Not: 2 ana + 1 numune konteyner. Numune için ayrı kalite raporu gönderildi.'),
                 now))
    sid = cur.lastrowid

    # Kalemler
    kalemler = [
        # (Aciklama, Miktar, CiftSayi, BirimFiyat, Tutar, AgirlikKg)
        ('EVA Grade A Compound — White, shore 55 [Main-A × 2× 40HQ]',
         40000, 40000, 2.10, 84000, 40000),
        ('EVA Grade B Compound — Trial run, black [Sample-B × 1× 20GP]',
         18000, 18000, 2.35, 42300, 18000),
    ]
    kalem_ids = []
    for ac, mk, cs, bf, tut, agr in kalemler:
        cur.execute("""INSERT INTO grafik_cin_siparis_kalem
                       (SiparisId, VaryantId, UrunId, Aciklama, Miktar, CiftSayi,
                        BirimFiyat, Tutar, AgirlikKg, HacimM3, OlusturmaTarih)
                       VALUES (?, NULL, NULL, ?, ?, ?, ?, ?, ?, 0, ?)""",
                    (sid, ac, mk, cs, bf, tut, agr, now))
        kalem_ids.append(cur.lastrowid)

    # Kalem ek bilgileri (cin_ofis_kalem_ek)
    ek_bilgi = [
        ('Main-A', '40HQ', 2, 'Main', 'EVA Grade A Compound', 'kg'),
        ('Sample-B', '20GP', 1, 'Sample', 'EVA Grade B Compound', 'kg'),
    ]
    for i, (cg, ct, cq, q, pn, u) in enumerate(ek_bilgi):
        cur.execute("""INSERT INTO cin_ofis_kalem_ek
                       (KalemId, ContainerGroup, ContainerType, ContainerQty,
                        Quality, ProductName, Unit)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (kalem_ids[i], cg, ct, cq, q, pn, u))

    # Import log
    import json as _json
    parse_ozet = {
        'INFO': {
            'Order Code': order_code,
            'Supplier Name': 'Dongguan Light Industry',
            'Supplier Contact': 'Mr. Wang +86 139-5555-5555',
            'Currency': 'USD',
            'Currency Rate': 32.10,
            'Expected ETD': '2026-05-15',
            'Expected ETA': '2026-06-20',
            'Total Container Count': 3,
            'Shipment Type': 'SEA',
            'Loading Port': 'Shenzhen',
            'Discharge Port': 'Istanbul',
            'Notes': '2 ana + 1 numune konteyner. Numune için ayrı kalite raporu.',
        },
        'ITEMS': [
            {'Line #': 1, 'Container Group': 'Main-A', 'Container Type': '40HQ',
             'Container Qty': 2, 'Quality': 'Main', 'Product Name': 'EVA Grade A Compound',
             'Description': 'White, shore 55', 'Qty': 40000, 'Unit': 'kg',
             'Unit Price': 2.10, 'Weight (kg)': 40000},
            {'Line #': 2, 'Container Group': 'Sample-B', 'Container Type': '20GP',
             'Container Qty': 1, 'Quality': 'Sample', 'Product Name': 'EVA Grade B Compound',
             'Description': 'Trial run, black', 'Qty': 18000, 'Unit': 'kg',
             'Unit Price': 2.35, 'Weight (kg)': 18000},
        ],
        'PAYMENT': [
            {'#': 1, 'Type': 'Advance TT', 'Ratio': 30, 'Amount': 37890,
             'Due Date': '2026-04-25', 'Trigger': 'Order Confirmation', 'Notes': 'PO sonrası 5 gün'},
            {'#': 2, 'Type': 'Pre-shipment TT', 'Ratio': 40, 'Amount': 50520,
             'Due Date': '2026-05-12', 'Trigger': 'Before Loading', 'Notes': 'B/L kopyası öncesi'},
            {'#': 3, 'Type': 'Post-shipment', 'Ratio': 30, 'Amount': 37890,
             'Due Date': '2026-06-15', 'Trigger': 'After B/L Copy', 'Notes': 'Sevk sonrası'},
        ],
        'FILES': [
            {'#': 1, 'File Name': 'proforma_2026_demo01.pdf', 'Type': 'Proforma',
             'Required': 'Yes', 'Description': 'Ana proforma fatura'},
            {'#': 2, 'File Name': 'eva_grade_a_photo.jpg', 'Type': 'Image',
             'Required': 'No', 'Description': 'Ana ürün görseli'},
            {'#': 3, 'File Name': 'sample_lab_report.pdf', 'Type': 'Test Report',
             'Required': 'Yes', 'Description': 'Sample lab raporu'},
        ],
        '_lang': 'CN',
        '_template_version': 'v1.0',
        '_hatalar': [],
    }
    cur.execute("""INSERT INTO cin_ofis_import_log
                   (OrderCode, DosyaAdi, SiparisId, ParseOzet, Dil, TemplateSurum, Durum,
                    KurPB, KurDeger, KurKaynagi, KurTarihi,
                    SistemKurDeger, ExcelKurDeger, KurFarkiYuzde,
                    OlusturmaTarih, OlusturanKullanici)
                   VALUES (?, 'cin_ofis_eva_ornek_v1.0.xlsx', ?, ?, 'CN', 'v1.0', 'BASARILI',
                           'USD', 39.3500, 'SISTEM_OTOMATIK', '2026-05-15',
                           39.3500, 32.1000, 18.42,
                           ?, 'cin.ofis')""",
                (order_code, sid, _json.dumps(parse_ozet), now))
    log_id = cur.lastrowid

    # Ödeme plan taslağı — %30/%40/%30
    odeme_taslaklari = [
        (1, 'Advance TT', 30, 37890, 'USD', '2026-04-25', 'Order Confirmation', 'PO sonrası 5 gün'),
        (2, 'Pre-shipment TT', 40, 50520, 'USD', '2026-05-12', 'Before Loading', 'B/L kopyası öncesi'),
        (3, 'Post-shipment', 30, 37890, 'USD', '2026-06-15', 'After B/L Copy', 'Sevk sonrası'),
    ]
    for sira, tip, oran, tutar, pb, tarih, tetik, notlar in odeme_taslaklari:
        cur.execute("""INSERT INTO cin_ofis_odeme_taslak
                       (ImportLogId, Sira, OdemeTipi, Oran, Tutar, ParaBirimi,
                        PlanTarih, Tetikleyici, Notlar)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (log_id, sira, tip, oran, tutar, pb, tarih, tetik, notlar))

    # Dosya referansları — 2 Required, 1 Optional
    dosyalar = [
        ('proforma_2026_demo01.pdf', 'Proforma', 1, 'Ana proforma fatura'),
        ('eva_grade_a_photo.jpg', 'Image', 0, 'Ana ürün görseli'),
        ('sample_lab_report.pdf', 'Test Report', 1, 'Sample lab raporu'),
    ]
    for i, (ad, tip, gerekli, aciklama) in enumerate(dosyalar, 1):
        cur.execute("""INSERT INTO cin_ofis_dosya_referans
                       (ImportLogId, Sira, DosyaAdi, DosyaTipi, Gerekli, Aciklama)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (log_id, i, ad, tip, gerekli, aciklama))

    conn.commit()


def main():
    sil = '--sil' in sys.argv
    sadece_y = '--sadece-yonetim' in sys.argv

    path = Config.MOCK_DB_PATH
    if sil and os.path.exists(path):
        os.remove(path)
        print(f"✓ Eski DB silindi: {path}")
        for ek in ('-wal', '-shm'):
            if os.path.exists(path + ek):
                os.remove(path + ek)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    print("→ Şema oluşturuluyor...")
    _kur_sema(conn)

    print("→ Roller ve kullanıcılar...")
    _seed_roller_kullanicilar(conn)

    print("→ Kur (son 7 gün USD/EUR/CNY)...")
    _seed_kur(conn)

    if not sadece_y:
        print("→ Finans mock verileri (5 anlaşma)...")
        _seed_finans(conn)

        print("→ Grafik altyapı (kategori, ürün, varyant, tedarikçi)...")
        _seed_grafik(conn)

        print("→ Parça 8a: Çin Ofis Import demo...")
        _seed_cin_ofis_import(conn)

    conn.close()
    print()
    print("=" * 60)
    print("  ✓ DB kuruldu:", path)
    print("=" * 60)
    print()
    print("  Kullanıcılar:")
    print("    admin     / admin123   (Yönetim)")
    print("    halil     / 232323     (Yönetim)")
    print("    hasan     / 323232     (Yönetim)")
    print("    samet     / 434343     (Grafik)")
    print("    cin.ofis  / Cin2026!   (Çin Ofis)  ← ilk girişte şifre zorunlu değişir")
    print("    muhasebe  / Muh2026!   (Muhasebe)  ← ilk girişte şifre zorunlu değişir")
    print()


if __name__ == '__main__':
    main()
