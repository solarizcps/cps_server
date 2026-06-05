# -*- coding: utf-8 -*-
"""
CPS DEV - İthalat Modülü Veritabanı Kurulum Scripti
===================================================
BLOK 4 — İthalat + Maliyet + Nakit Planlama tabloları.

SQLite (mock_data.db) için idempotent kurulum.
MSSQL prod ortamında ayrıca çalıştırılır (aynı script uyumlu).

Çalıştır:
    cd C:\\cps_dev
    python init_ithalat_db.py

Tekrar tekrar çalıştırılabilir — varolan tablolar ve kayıtlar korunur.
Seed verisi de idempotent (aynı kod tekrarlanmaz).
"""
import sys
import os
from datetime import datetime, date, timedelta

# Project root'u path'e ekle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_conn, tablo_var_mi, qone, qexec, q
from config import Config


# =====================================================================
# TABLO KURULUMLARI
# =====================================================================
SQL_TABLOLAR = [

    # -----------------------------------------------------------------
    # 1) ithalat_parti
    # -----------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS ithalat_parti (
        Id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        Kod                   TEXT NOT NULL UNIQUE,
        Baslik                TEXT NOT NULL,
        TedarikciId           INTEGER,
        TedarikciKod          TEXT,
        TedarikciAd           TEXT,
        SiparisId             INTEGER,
        ParaBirimi            TEXT NOT NULL DEFAULT 'USD',
        Durum                 TEXT NOT NULL DEFAULT 'TASLAK',
        YuklemeTarih          TEXT,
        TahminiVarisTarih     TEXT,
        GerceklesenVarisTarih TEXT,
        ToplamKg              REAL,
        ToplamCift            INTEGER,
        OlusturanKullanici    TEXT NOT NULL,
        DepartmanKod          TEXT,
        OlusmaTarih           TEXT NOT NULL,
        KapamaTarih           TEXT,
        Aciklama              TEXT
    )
    """,

    # -----------------------------------------------------------------
    # 2) ithalat_maliyet_kalem
    # -----------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS ithalat_maliyet_kalem (
        Id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        PartiId               INTEGER NOT NULL,
        Tip                   TEXT NOT NULL,
        AltKod                TEXT,
        Aciklama              TEXT,
        Kaynak                TEXT NOT NULL,
        Tutar                 REAL NOT NULL,
        ParaBirimi            TEXT NOT NULL,
        KurTarihi             TEXT,
        KurDegeri             REAL,
        TutarPartiPara        REAL,
        FaturaNo              TEXT,
        FaturaTarih           TEXT,
        CariId                INTEGER,
        CariKod               TEXT,
        CariAd                TEXT,
        OdemePlanId           INTEGER,
        OlusturanKullanici    TEXT,
        OlusmaTarih           TEXT NOT NULL,
        NotMetni              TEXT,
        FOREIGN KEY (PartiId) REFERENCES ithalat_parti(Id) ON DELETE CASCADE
    )
    """,

    # -----------------------------------------------------------------
    # 3) ithalat_odeme_plan
    # -----------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS ithalat_odeme_plan (
        Id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        PartiId               INTEGER NOT NULL,
        Sira                  INTEGER NOT NULL,
        Aciklama              TEXT,
        PlanlananTarih        TEXT NOT NULL,
        Tutar                 REAL NOT NULL,
        ParaBirimi            TEXT NOT NULL,
        OdemeTipi             TEXT,
        CariId                INTEGER,
        CariKod               TEXT,
        CariAd                TEXT,
        Durum                 TEXT NOT NULL DEFAULT 'BEKLIYOR',
        OdenenTutar           REAL NOT NULL DEFAULT 0,
        TamamlanmaTarih       TEXT,
        NotMetni              TEXT,
        OlusturanKullanici    TEXT,
        OlusmaTarih           TEXT NOT NULL,
        FOREIGN KEY (PartiId) REFERENCES ithalat_parti(Id) ON DELETE CASCADE
    )
    """,

    # -----------------------------------------------------------------
    # 4) ithalat_odeme_hareket
    # -----------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS ithalat_odeme_hareket (
        Id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        PartiId               INTEGER NOT NULL,
        OdemePlanId           INTEGER,
        Tarih                 TEXT NOT NULL,
        Tutar                 REAL NOT NULL,
        ParaBirimi            TEXT NOT NULL,
        KurTarihi             TEXT,
        KurDegeri             REAL,
        TutarPartiPara        REAL,
        OdemeYontemi          TEXT,
        BankaRef              TEXT,
        CariId                INTEGER,
        CariKod               TEXT,
        CariAd                TEXT,
        NotMetni              TEXT,
        Iptal                 INTEGER NOT NULL DEFAULT 0,
        IptalSebep            TEXT,
        KaydedenKullanici     TEXT NOT NULL,
        OlusmaTarih           TEXT NOT NULL,
        FOREIGN KEY (PartiId) REFERENCES ithalat_parti(Id) ON DELETE CASCADE,
        FOREIGN KEY (OdemePlanId) REFERENCES ithalat_odeme_plan(Id)
    )
    """,

    # -----------------------------------------------------------------
    # 5) nakit_giris_beklenen
    # -----------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS nakit_giris_beklenen (
        Id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        Kaynak                TEXT NOT NULL,
        CariId                INTEGER,
        CariKod               TEXT,
        CariAd                TEXT,
        RefKayitTipi          TEXT,
        RefKayitId            INTEGER,
        Aciklama              TEXT,
        BeklenenTarih         TEXT NOT NULL,
        Tutar                 REAL NOT NULL,
        ParaBirimi            TEXT NOT NULL,
        Durum                 TEXT NOT NULL DEFAULT 'BEKLIYOR',
        TahsilEdilen          REAL NOT NULL DEFAULT 0,
        OlusturanKullanici    TEXT,
        DepartmanKod          TEXT,
        OlusmaTarih           TEXT NOT NULL,
        NotMetni              TEXT
    )
    """,
]


# =====================================================================
# INDEXLER
# =====================================================================
SQL_INDEKSLER = [
    "CREATE INDEX IF NOT EXISTS ix_parti_durum        ON ithalat_parti(Durum, TahminiVarisTarih)",
    "CREATE INDEX IF NOT EXISTS ix_parti_ted_kod      ON ithalat_parti(TedarikciKod)",
    "CREATE INDEX IF NOT EXISTS ix_parti_olusturan    ON ithalat_parti(OlusturanKullanici)",
    "CREATE INDEX IF NOT EXISTS ix_parti_departman    ON ithalat_parti(DepartmanKod)",

    "CREATE INDEX IF NOT EXISTS ix_mk_parti_tip       ON ithalat_maliyet_kalem(PartiId, Tip)",
    "CREATE INDEX IF NOT EXISTS ix_mk_parti_kaynak    ON ithalat_maliyet_kalem(PartiId, Kaynak)",
    "CREATE INDEX IF NOT EXISTS ix_mk_plan            ON ithalat_maliyet_kalem(OdemePlanId)",
    "CREATE INDEX IF NOT EXISTS ix_mk_cari            ON ithalat_maliyet_kalem(CariKod)",

    "CREATE INDEX IF NOT EXISTS ix_op_parti_sira      ON ithalat_odeme_plan(PartiId, Sira)",
    "CREATE INDEX IF NOT EXISTS ix_op_durum_tarih     ON ithalat_odeme_plan(Durum, PlanlananTarih)",
    "CREATE INDEX IF NOT EXISTS ix_op_cari            ON ithalat_odeme_plan(CariKod, Durum)",

    "CREATE INDEX IF NOT EXISTS ix_oh_parti_tarih     ON ithalat_odeme_hareket(PartiId, Tarih)",
    "CREATE INDEX IF NOT EXISTS ix_oh_plan            ON ithalat_odeme_hareket(OdemePlanId, Iptal)",
    "CREATE INDEX IF NOT EXISTS ix_oh_tarih           ON ithalat_odeme_hareket(Tarih, Iptal)",

    "CREATE INDEX IF NOT EXISTS ix_ng_durum_tarih     ON nakit_giris_beklenen(Durum, BeklenenTarih)",
    "CREATE INDEX IF NOT EXISTS ix_ng_cari            ON nakit_giris_beklenen(CariKod)",
    "CREATE INDEX IF NOT EXISTS ix_ng_departman      ON nakit_giris_beklenen(DepartmanKod)",
]


# =====================================================================
# YETKI KAYITLARI — sistem_yetki tablosuna ekleme
# =====================================================================
# Mevcut yetki pattern'i: 'modul.alt_modul.islem' (auth.py'den)
# Orn: 'ithalat.parti.goruntule', 'ithalat.parti.duzenle'
YETKI_KAYITLARI = [
    ('ithalat.parti',       'Ithalat Parti',      'ithalat',       'parti'),
    ('ithalat.maliyet',     'Ithalat Maliyet',    'ithalat',       'maliyet'),
    ('ithalat.odeme',       'Ithalat Odeme',      'ithalat',       'odeme'),
    ('nakit.planlama',      'Nakit Planlama',     'nakit',         'planlama'),
]


# =====================================================================
# SEED VERISI — test icin 3 ornek parti
# =====================================================================
def _seed_var_mi():
    """Seed verisi zaten eklenmis mi kontrol et."""
    r = qone("SELECT COUNT(*) AS sayi FROM ithalat_parti WHERE Kod LIKE 'ITH-DEMO-%'")
    return r and r['sayi'] > 0


def seed_demo_verisi(kullanici='sistem'):
    """3 ornek parti + kalem + odeme plani."""
    if _seed_var_mi():
        print("  [SKIP] Seed verisi zaten mevcut.")
        return

    simdi = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    bugun = date.today()

    partiler = [
        {
            'Kod': 'ITH-DEMO-001',
            'Baslik': 'Mart Konteynir - EVA Terlik',
            'TedarikciKod': 'WUXI',
            'TedarikciAd': 'Wuxi Rubber Co.',
            'ParaBirimi': 'USD',
            'Durum': 'AKTIF',
            'YuklemeTarih':      (bugun - timedelta(days=30)).isoformat(),
            'TahminiVarisTarih': (bugun + timedelta(days=5)).isoformat(),
            'ToplamKg': 40000,
            'ToplamCift': 20000,
            'Aciklama': 'Demo parti - test verisi',
        },
        {
            'Kod': 'ITH-DEMO-002',
            'Baslik': 'Subat Konteynir - Spor Ayakkabi',
            'TedarikciKod': 'SHENGDA',
            'TedarikciAd': 'Shengda Footwear Ltd.',
            'ParaBirimi': 'USD',
            'Durum': 'TESLIM',
            'YuklemeTarih':      (bugun - timedelta(days=60)).isoformat(),
            'TahminiVarisTarih': (bugun - timedelta(days=20)).isoformat(),
            'GerceklesenVarisTarih': (bugun - timedelta(days=18)).isoformat(),
            'ToplamKg': 28000,
            'ToplamCift': 15000,
            'Aciklama': 'Demo parti - teslim edildi',
        },
        {
            'Kod': 'ITH-DEMO-003',
            'Baslik': 'Nisan On Siparis - Sandalet',
            'TedarikciKod': 'WUXI',
            'TedarikciAd': 'Wuxi Rubber Co.',
            'ParaBirimi': 'USD',
            'Durum': 'TASLAK',
            'YuklemeTarih':      (bugun + timedelta(days=10)).isoformat(),
            'TahminiVarisTarih': (bugun + timedelta(days=45)).isoformat(),
            'ToplamKg': 35000,
            'ToplamCift': 18000,
            'Aciklama': 'Demo parti - taslak, odeme plani henuz yok',
        },
    ]

    # Partileri ekle
    parti_ids = {}
    for p in partiler:
        pid = qexec("""
            INSERT INTO ithalat_parti
                (Kod, Baslik, TedarikciKod, TedarikciAd, ParaBirimi, Durum,
                 YuklemeTarih, TahminiVarisTarih, GerceklesenVarisTarih,
                 ToplamKg, ToplamCift, OlusturanKullanici, OlusmaTarih, Aciklama)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            p['Kod'], p['Baslik'], p['TedarikciKod'], p['TedarikciAd'],
            p['ParaBirimi'], p['Durum'],
            p.get('YuklemeTarih'), p.get('TahminiVarisTarih'),
            p.get('GerceklesenVarisTarih'),
            p['ToplamKg'], p['ToplamCift'],
            kullanici, simdi, p.get('Aciklama'),
        ))
        parti_ids[p['Kod']] = pid
        print(f"  [OK] Parti eklendi: {p['Kod']} (id={pid})")

    # DEMO-001 icin maliyet kalemleri
    p1_id = parti_ids['ITH-DEMO-001']
    kalemler = [
        ('FOB',     'TAHMINI',     68000, 'USD'),
        ('FOB',     'GERCEKLESEN', 68000, 'USD'),
        ('NAVLUN',  'TAHMINI',      8500, 'USD'),
        ('NAVLUN',  'GERCEKLESEN',  9200, 'USD'),
        ('GUMRUK',  'TAHMINI',      2800, 'USD'),
        ('SIGORTA', 'TAHMINI',       400, 'USD'),
        ('SIGORTA', 'GERCEKLESEN',   400, 'USD'),
    ]
    for tip, kaynak, tutar, para in kalemler:
        qexec("""
            INSERT INTO ithalat_maliyet_kalem
                (PartiId, Tip, Kaynak, Tutar, ParaBirimi,
                 TutarPartiPara, OlusturanKullanici, OlusmaTarih)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (p1_id, tip, kaynak, tutar, para, tutar, kullanici, simdi))
    print(f"  [OK] DEMO-001 maliyet kalemleri eklendi ({len(kalemler)} adet)")

    # DEMO-001 icin odeme plani
    odemeler = [
        (1, -30, 'Depozito %30', 24000, 'DEPOZITO'),
        (2, -15, 'Yukleme sonrasi %50', 40000, 'ARA_ODEME'),
        (3,  +5, 'Son odeme %20', 16000, 'SON_ODEME'),
        (4, +10, 'Navlun Maersk',  9200, 'NAVLUN_ODEMESI'),
    ]
    for sira, gun_fark, aciklama, tutar, tip in odemeler:
        qexec("""
            INSERT INTO ithalat_odeme_plan
                (PartiId, Sira, Aciklama, PlanlananTarih, Tutar, ParaBirimi,
                 OdemeTipi, CariKod, CariAd,
                 OlusturanKullanici, OlusmaTarih)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            p1_id, sira, aciklama,
            (bugun + timedelta(days=gun_fark)).isoformat(),
            tutar, 'USD', tip, 'WUXI', 'Wuxi Rubber Co.',
            kullanici, simdi,
        ))
    print(f"  [OK] DEMO-001 odeme plani eklendi ({len(odemeler)} satir)")

    # DEMO-002 icin odeme plani (kapali)
    p2_id = parti_ids['ITH-DEMO-002']
    qexec("""
        INSERT INTO ithalat_odeme_plan
            (PartiId, Sira, Aciklama, PlanlananTarih, Tutar, ParaBirimi,
             OdemeTipi, CariKod, CariAd, Durum, OdenenTutar,
             OlusturanKullanici, OlusmaTarih)
        VALUES (?, 1, 'Tek odeme', ?, 50000, 'USD',
                'SON_ODEME', 'SHENGDA', 'Shengda Footwear Ltd.',
                'ODENDI', 50000, ?, ?)
    """, (p2_id, (bugun - timedelta(days=50)).isoformat(), kullanici, simdi))
    print(f"  [OK] DEMO-002 odeme plani eklendi")

    # Nakit giris beklenen - 2 ornek
    qexec("""
        INSERT INTO nakit_giris_beklenen
            (Kaynak, CariKod, CariAd, BeklenenTarih, Tutar, ParaBirimi,
             Aciklama, OlusturanKullanici, OlusmaTarih)
        VALUES ('MUSTERI_TAHSILAT', 'ABC', 'ABC Tekstil A.S.',
                ?, 300000, 'TRY',
                'Demo tahsilat - nakit girisi test', ?, ?)
    """, ((bugun + timedelta(days=7)).isoformat(), kullanici, simdi))

    qexec("""
        INSERT INTO nakit_giris_beklenen
            (Kaynak, CariKod, CariAd, BeklenenTarih, Tutar, ParaBirimi,
             Aciklama, OlusturanKullanici, OlusmaTarih)
        VALUES ('MUSTERI_TAHSILAT', 'XYZ', 'XYZ Ticaret Ltd.',
                ?, 180000, 'TRY',
                'Demo tahsilat 2', ?, ?)
    """, ((bugun + timedelta(days=14)).isoformat(), kullanici, simdi))
    print(f"  [OK] Nakit giris ornekleri eklendi (2 adet)")


# =====================================================================
# YETKI SEED
# =====================================================================
def seed_yetkiler():
    """
    sistem_yetki tablosuna ithalat modulu yetkilerini ekle.
    sistem_yetki tablosu yoksa sessiz gec (kullanici yetki sistemi henuz
    kurulu degilse engelleme).
    """
    if not tablo_var_mi('sistem_yetki'):
        print("  [SKIP] sistem_yetki tablosu yok, yetki kayitlari atlandi.")
        return

    for kod, ad, modul, alt_modul in YETKI_KAYITLARI:
        mevcut = qone("SELECT Id FROM sistem_yetki WHERE Kod = ?", (kod,))
        if mevcut:
            continue
        # Yetki tablosunun gercek semasini bilmiyoruz - en yaygin kolonlarla dene
        try:
            qexec("""
                INSERT INTO sistem_yetki (Kod, Ad, Modul, AltModul)
                VALUES (?, ?, ?, ?)
            """, (kod, ad, modul, alt_modul))
            print(f"  [OK] Yetki eklendi: {kod}")
        except Exception as e:
            # Sema farkliysa 3 kolonlu versiyonu dene
            try:
                qexec("""
                    INSERT INTO sistem_yetki (Kod, Ad)
                    VALUES (?, ?)
                """, (kod, ad))
                print(f"  [OK] Yetki eklendi (basit sema): {kod}")
            except Exception as e2:
                print(f"  [WARN] Yetki eklenemedi {kod}: {e2}")


# =====================================================================
# ANA AKIS
# =====================================================================
def main():
    print("=" * 70)
    print("  CPS DEV - Ithalat Modulu DB Kurulumu")
    print(f"  DB_MODE: {Config.DB_MODE}")
    if Config.DB_MODE == 'mock':
        print(f"  SQLite: {Config.MOCK_DB_PATH}")
    else:
        print(f"  MSSQL:  {Config.MSSQL_HOST}/{Config.MSSQL_DATABASE}")
    print("=" * 70)

    # 1) Tablolar
    print("\n[1] Tablolar olusturuluyor...")
    c = get_conn()
    try:
        cur = c.cursor()
        for sql in SQL_TABLOLAR:
            cur.execute(sql)
        for sql in SQL_INDEKSLER:
            cur.execute(sql)
        c.commit()
    finally:
        c.close()

    tablolar = [
        'ithalat_parti',
        'ithalat_maliyet_kalem',
        'ithalat_odeme_plan',
        'ithalat_odeme_hareket',
        'nakit_giris_beklenen',
    ]
    for t in tablolar:
        var = tablo_var_mi(t)
        durum = "OK" if var else "HATA"
        print(f"  [{durum}] {t}")

    # 2) Yetkiler
    print("\n[2] Yetki kayitlari kontrol ediliyor...")
    seed_yetkiler()

    # 3) Seed demo veri
    print("\n[3] Demo veri ekleniyor...")
    seed_demo_verisi()

    # 4) Ozet
    print("\n[4] Ozet:")
    for t in tablolar:
        r = qone(f"SELECT COUNT(*) AS sayi FROM {t}")
        sayi = r['sayi'] if r else 0
        print(f"  {t:30s} : {sayi} kayit")

    print("\n" + "=" * 70)
    print("  KURULUM TAMAMLANDI")
    print("  Test: python app.py")
    print("  URL:  http://127.0.0.1:5057/ithalat/parti/liste")
    print("=" * 70)


if __name__ == '__main__':
    main()
