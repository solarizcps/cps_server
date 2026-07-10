# -*- coding: utf-8 -*-
"""
MIG 092 SYNTAX DÜZELTME — İZOLE TEST
=====================================
Donanım gerektirmez. Gerçek DB kullanmaz.
In-memory SQLite üzerinde çalışır.

Senaryolar:
  A) Tablo hiç yok  → oluşturulur
  B) Tablo var, revizyon_id NOT NULL  → NULL-able yapılır
  C) Tablo var, revizyon_id zaten NULL-able  → dokunulmaz
  D) Eski barkod formatı var  → yeni formata güncellenir
  E) Barkodlar zaten yeni formatta  → değiştirilmez

Çalıştır:
  python app/migrations/test_092_fix.py
"""

import sys
import os
import sqlite3
import importlib.util

SEP  = "=" * 55
PASS = 0
FAIL = 0

_HERE = os.path.dirname(os.path.abspath(__file__))


def _yükle():
    spec = importlib.util.spec_from_file_location(
        "m092", os.path.join(_HERE, "092_nexgen_arge_etiket.py")
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _temel_db():
    """Boş in-memory DB, schema_migrations + bağımlı tablolar dahil."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""
        CREATE TABLE schema_migrations (
            version TEXT PRIMARY KEY,
            aciklama TEXT,
            applied_at TEXT DEFAULT (datetime('now'))
        )
    """)
    con.execute("""
        CREATE TABLE nexgen_arge_test (
            id INTEGER PRIMARY KEY,
            arge_kodu TEXT,
            aktif INTEGER DEFAULT 1
        )
    """)
    con.execute("""
        CREATE TABLE nexgen_cari (
            id INTEGER PRIMARY KEY,
            unvan TEXT
        )
    """)
    con.commit()
    return con


def test(isim, fn):
    global PASS, FAIL
    try:
        fn()
        print(f"  [PASS] {isim}")
        PASS += 1
    except AssertionError as e:
        print(f"  [FAIL] {isim}: {e}")
        FAIL += 1
    except Exception as e:
        import traceback
        print(f"  [FAIL] {isim}: {type(e).__name__}: {e}")
        traceback.print_exc()
        FAIL += 1


# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  A) Tablo hiç yok → oluşturulur")
print(SEP)


def t_a_tablo_yok():
    m = _yükle()
    con = _temel_db()
    cur = con.cursor()
    log = []
    m.mig092(cur, con, log)
    # Tablo var mı?
    r = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nexgen_arge_etiket'"
    ).fetchone()
    assert r, "nexgen_arge_etiket oluşturulmadı"
    # revizyon_id nullable mi?
    for satir in cur.execute("PRAGMA table_info(nexgen_arge_etiket)").fetchall():
        if satir[1] == 'revizyon_id':
            assert satir[3] == 0, f"revizyon_id NOT NULL olmamalı, notnull={satir[3]}"
            break
    # yazdirma tablosu
    r2 = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nexgen_arge_etiket_yazdirma'"
    ).fetchone()
    assert r2, "nexgen_arge_etiket_yazdirma oluşturulmadı"
    log_str = "\n".join(log)
    assert "olusturuldu" in log_str, f"Log'da 'olusturuldu' yok: {log_str}"


test("Tablo yok → taze oluşturma", t_a_tablo_yok)


# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  B) revizyon_id NOT NULL → NULL-able yapılır")
print(SEP)


def _db_revizyonid_notnull():
    """revizyon_id NOT NULL olan eski şema."""
    con = _temel_db()
    con.execute("""
        CREATE TABLE nexgen_arge_etiket (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            arge_kayit_id            INTEGER NOT NULL,
            revizyon_id              INTEGER NOT NULL,
            arge_kodu                TEXT,
            rev_no                   INTEGER NOT NULL DEFAULT 0,
            numune_no                INTEGER NOT NULL,
            barkod_kodu              TEXT    NOT NULL,
            cari_id                  INTEGER,
            cari_adi_snapshot        TEXT,
            talep_tarihi             TEXT,
            numune_tarihi            TEXT,
            olusturan_kullanici_id   INTEGER,
            olusturan_kullanici_adi  TEXT,
            yazdirma_sayisi          INTEGER NOT NULL DEFAULT 0,
            ilk_yazdirma_tarihi      TEXT,
            son_yazdirma_tarihi      TEXT,
            durum                    TEXT    NOT NULL DEFAULT 'AKTIF',
            created_at               TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at               TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(barkod_kodu),
            UNIQUE(arge_kayit_id, rev_no, numune_no)
        )
    """)
    con.execute("""
        CREATE TABLE nexgen_arge_etiket_yazdirma (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            etiket_id   INTEGER NOT NULL,
            barkod_kodu TEXT    NOT NULL,
            kullanici_id INTEGER,
            kullanici_adi TEXT,
            kopya_sayisi INTEGER NOT NULL DEFAULT 1,
            ilk_basim_mi INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    con.commit()
    return con


def t_b_revizyonid_not_null_kaldirilir():
    m = _yükle()
    con = _db_revizyonid_notnull()
    cur = con.cursor()
    log = []
    m.mig092(cur, con, log)
    # revizyon_id artık nullable olmalı
    for satir in cur.execute("PRAGMA table_info(nexgen_arge_etiket)").fetchall():
        if satir[1] == 'revizyon_id':
            assert satir[3] == 0, f"NOT NULL kaldırılmadı, notnull={satir[3]}"
            break
    log_str = "\n".join(log)
    assert "kaldirildi" in log_str or "NULL-able" in log_str, f"Log: {log_str}"


def t_b_veri_korunur():
    """Tablo yeniden oluşturulurken mevcut veri korunmalı."""
    m = _yükle()
    con = _db_revizyonid_notnull()
    cur = con.cursor()
    # Önceden veri ekle (revizyon_id dolu olduğu için NOT NULL şimdilik sorun yok)
    cur.execute("""
        INSERT INTO nexgen_arge_etiket
            (arge_kayit_id, revizyon_id, arge_kodu, rev_no, numune_no, barkod_kodu, numune_tarihi)
        VALUES (1, 99, 'NX-AR-0001', 0, 1, 'NX-ARGE-AR0001-R00-N01', '2026-07-10')
    """)
    con.commit()
    log = []
    m.mig092(cur, con, log)
    # Veri hâlâ var mı?
    row = cur.execute(
        "SELECT barkod_kodu FROM nexgen_arge_etiket WHERE arge_kodu='NX-AR-0001'"
    ).fetchone()
    assert row, "Veri migration sonrası kayboldu!"
    assert row[0] == 'NX-ARGE-AR0001-R00-N01', f"Barkod değişti: {row[0]}"


test("revizyon_id NOT NULL → NULL-able dönüştürme", t_b_revizyonid_not_null_kaldirilir)
test("Veri korunuyor (NOT NULL kaldırma sırasında)", t_b_veri_korunur)


# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  C) revizyon_id zaten NULL-able → dokunulmaz")
print(SEP)


def _db_revizyonid_nullable():
    """revizyon_id nullable olan güncel şema."""
    con = _temel_db()
    con.execute("""
        CREATE TABLE nexgen_arge_etiket (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            arge_kayit_id            INTEGER NOT NULL,
            revizyon_id              INTEGER,
            arge_kodu                TEXT,
            rev_no                   INTEGER NOT NULL DEFAULT 0,
            numune_no                INTEGER NOT NULL,
            barkod_kodu              TEXT    NOT NULL,
            cari_id                  INTEGER,
            cari_adi_snapshot        TEXT,
            talep_tarihi             TEXT,
            numune_tarihi            TEXT,
            olusturan_kullanici_id   INTEGER,
            olusturan_kullanici_adi  TEXT,
            yazdirma_sayisi          INTEGER NOT NULL DEFAULT 0,
            ilk_yazdirma_tarihi      TEXT,
            son_yazdirma_tarihi      TEXT,
            durum                    TEXT    NOT NULL DEFAULT 'AKTIF',
            created_at               TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at               TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(barkod_kodu),
            UNIQUE(arge_kayit_id, rev_no, numune_no)
        )
    """)
    con.execute("""
        CREATE TABLE nexgen_arge_etiket_yazdirma (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            etiket_id   INTEGER NOT NULL,
            barkod_kodu TEXT    NOT NULL,
            kullanici_id INTEGER,
            kullanici_adi TEXT,
            kopya_sayisi INTEGER NOT NULL DEFAULT 1,
            ilk_basim_mi INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    con.commit()
    return con


def t_c_zaten_nullable():
    m = _yükle()
    con = _db_revizyonid_nullable()
    cur = con.cursor()
    log = []
    m.mig092(cur, con, log)
    log_str = "\n".join(log)
    assert "atlandi" in log_str or "zaten" in log_str, \
        f"NULL-able kolonun atlandığı log'da yok: {log_str}"


def t_c_idempotent_ikinci():
    """İkinci çalıştırmada da hata yok, değişiklik yok."""
    m = _yükle()
    con = _db_revizyonid_nullable()
    cur = con.cursor()
    # İki kez çalıştır
    log1 = []
    m.mig092(cur, con, log1)
    log2 = []
    m.mig092(cur, con, log2)
    # İkinci çalıştırmada tablo yeniden oluşturulmamalı
    log2_str = "\n".join(log2)
    assert "olusturuldu" not in log2_str or "mevcut" in log2_str, \
        f"İkinci çalıştırma tablo oluşturdu: {log2_str}"
    assert "atlandi" in log2_str or "zaten" in log2_str or "gerekmedi" in log2_str, \
        f"İkinci çalıştırma idempotent değil: {log2_str}"


test("revizyon_id zaten nullable → atlanır", t_c_zaten_nullable)
test("İkinci çalıştırma idempotent", t_c_idempotent_ikinci)


# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  D) Eski barkod formatı → yeni formata güncellenir")
print(SEP)


def _db_eski_barkod():
    """v1 barkod formatı olan DB."""
    con = _temel_db()
    con.execute("""
        CREATE TABLE nexgen_arge_etiket (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            arge_kayit_id INTEGER NOT NULL,
            revizyon_id INTEGER,
            arge_kodu TEXT,
            rev_no INTEGER NOT NULL DEFAULT 0,
            numune_no INTEGER NOT NULL,
            barkod_kodu TEXT NOT NULL,
            cari_id INTEGER,
            cari_adi_snapshot TEXT,
            talep_tarihi TEXT,
            numune_tarihi TEXT,
            olusturan_kullanici_id INTEGER,
            olusturan_kullanici_adi TEXT,
            yazdirma_sayisi INTEGER NOT NULL DEFAULT 0,
            ilk_yazdirma_tarihi TEXT,
            son_yazdirma_tarihi TEXT,
            durum TEXT NOT NULL DEFAULT 'AKTIF',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(barkod_kodu),
            UNIQUE(arge_kayit_id, rev_no, numune_no)
        )
    """)
    con.execute("""
        CREATE TABLE nexgen_arge_etiket_yazdirma (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            etiket_id INTEGER NOT NULL,
            barkod_kodu TEXT NOT NULL,
            kullanici_id INTEGER,
            kullanici_adi TEXT,
            kopya_sayisi INTEGER NOT NULL DEFAULT 1,
            ilk_basim_mi INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    # Eski formatta kayıtlar: NX-ARGE-0005-R00-N01 (prefix eksik)
    con.execute("""
        INSERT INTO nexgen_arge_etiket
            (arge_kayit_id, revizyon_id, arge_kodu, rev_no, numune_no, barkod_kodu, numune_tarihi)
        VALUES (1, NULL, 'NX-AR-0005', 0, 1, 'NX-ARGE-0005-R00-N01', '2026-07-10')
    """)
    con.execute("""
        INSERT INTO nexgen_arge_etiket
            (arge_kayit_id, revizyon_id, arge_kodu, rev_no, numune_no, barkod_kodu, numune_tarihi)
        VALUES (2, NULL, 'NX-RT-0004', 0, 1, 'NX-ARGE-0004-R00-N01', '2026-07-10')
    """)
    con.commit()
    return con


def t_d_eski_barkod_guncellenir():
    m = _yükle()
    con = _db_eski_barkod()
    cur = con.cursor()
    log = []
    m.mig092(cur, con, log)
    # NX-AR-0005 → NX-ARGE-AR0005-R00-N01 olmalı
    r1 = cur.execute(
        "SELECT barkod_kodu FROM nexgen_arge_etiket WHERE arge_kodu='NX-AR-0005'"
    ).fetchone()
    assert r1[0] == 'NX-ARGE-AR0005-R00-N01', f"AR barkod yanlış: {r1[0]}"
    # NX-RT-0004 → NX-ARGE-RT0004-R00-N01 olmalı
    r2 = cur.execute(
        "SELECT barkod_kodu FROM nexgen_arge_etiket WHERE arge_kodu='NX-RT-0004'"
    ).fetchone()
    assert r2[0] == 'NX-ARGE-RT0004-R00-N01', f"RT barkod yanlış: {r2[0]}"
    log_str = "\n".join(log)
    assert "guncellendi" in log_str, f"Güncelleme logu yok: {log_str}"


test("Eski barkod formatı → yeni formata güncellendi", t_d_eski_barkod_guncellenir)


# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  E) Barkodlar zaten yeni formatta → değiştirilmez")
print(SEP)


def _db_yeni_barkod():
    """v2 barkod formatı olan DB (zaten doğru)."""
    con = _temel_db()
    con.execute("""
        CREATE TABLE nexgen_arge_etiket (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            arge_kayit_id INTEGER NOT NULL,
            revizyon_id INTEGER,
            arge_kodu TEXT,
            rev_no INTEGER NOT NULL DEFAULT 0,
            numune_no INTEGER NOT NULL,
            barkod_kodu TEXT NOT NULL,
            cari_id INTEGER,
            cari_adi_snapshot TEXT,
            talep_tarihi TEXT,
            numune_tarihi TEXT,
            olusturan_kullanici_id INTEGER,
            olusturan_kullanici_adi TEXT,
            yazdirma_sayisi INTEGER NOT NULL DEFAULT 0,
            ilk_yazdirma_tarihi TEXT,
            son_yazdirma_tarihi TEXT,
            durum TEXT NOT NULL DEFAULT 'AKTIF',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(barkod_kodu),
            UNIQUE(arge_kayit_id, rev_no, numune_no)
        )
    """)
    con.execute("""
        CREATE TABLE nexgen_arge_etiket_yazdirma (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            etiket_id INTEGER NOT NULL,
            barkod_kodu TEXT NOT NULL,
            kullanici_id INTEGER,
            kullanici_adi TEXT,
            kopya_sayisi INTEGER NOT NULL DEFAULT 1,
            ilk_basim_mi INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    # Zaten yeni formatta
    con.execute("""
        INSERT INTO nexgen_arge_etiket
            (arge_kayit_id, revizyon_id, arge_kodu, rev_no, numune_no, barkod_kodu, numune_tarihi)
        VALUES (1, NULL, 'NX-RT-0004', 0, 1, 'NX-ARGE-RT0004-R00-N01', '2026-07-10')
    """)
    con.execute("""
        INSERT INTO nexgen_arge_etiket
            (arge_kayit_id, revizyon_id, arge_kodu, rev_no, numune_no, barkod_kodu, numune_tarihi)
        VALUES (2, NULL, 'NX-AR-0005', 0, 1, 'NX-ARGE-AR0005-R00-N01', '2026-07-10')
    """)
    con.execute("""
        INSERT INTO nexgen_arge_etiket
            (arge_kayit_id, revizyon_id, arge_kodu, rev_no, numune_no, barkod_kodu, numune_tarihi)
        VALUES (3, NULL, 'NX-ARF-0001', 0, 1, 'NX-ARGE-ARF0001-R00-N01', '2026-07-10')
    """)
    con.commit()
    return con


def t_e_yeni_barkod_degismez():
    m = _yükle()
    con = _db_yeni_barkod()
    cur = con.cursor()
    log = []
    m.mig092(cur, con, log)
    log_str = "\n".join(log)
    assert "gerekmedi" in log_str or "0 kayit" in log_str, \
        f"Barkod değişiklik logu beklenmedik: {log_str}"
    # Değerler korunmuş olmalı
    rows = cur.execute("SELECT barkod_kodu FROM nexgen_arge_etiket ORDER BY id").fetchall()
    assert rows[0][0] == 'NX-ARGE-RT0004-R00-N01'
    assert rows[1][0] == 'NX-ARGE-AR0005-R00-N01'
    assert rows[2][0] == 'NX-ARGE-ARF0001-R00-N01'


def t_e_idempotent_yeni_barkodla():
    """Yeni format barkodlar varken de ikinci çalıştırma 0 değişiklik."""
    m = _yükle()
    con = _db_yeni_barkod()
    cur = con.cursor()
    log1 = []
    m.mig092(cur, con, log1)
    log2 = []
    m.mig092(cur, con, log2)
    log2_str = "\n".join(log2)
    assert "gerekmedi" in log2_str or "0 kayit" in log2_str, \
        f"İkinci çalıştırma idempotent değil: {log2_str}"


test("Yeni formatlı barkodlar değiştirilmedi", t_e_yeni_barkod_degismez)
test("İkinci çalıştırma — yeni barkodlarla 0 değişiklik", t_e_idempotent_yeni_barkodla)


# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  F) pragma_table_info() KULLANILMADI kontrolü")
print(SEP)


def t_f_pragma_table_info_yok():
    """Düzeltilen dosyada pragma_table_info() SQL fonksiyonu kullanılmamalı."""
    dosya = os.path.join(_HERE, "092_nexgen_arge_etiket.py")
    with open(dosya, 'r', encoding='utf-8') as f:
        kaynak = f.read()
    # Eski hatalı sorgu yok mu?
    assert "pragma_table_info(" not in kaynak, \
        "pragma_table_info() SQL fonksiyonu hâlâ var!"
    # Doğru PRAGMA kullanımı var mı?
    assert "PRAGMA table_info(nexgen_arge_etiket)" in kaynak, \
        "PRAGMA table_info() bulunamadı"
    # Python tarafında işleniyor mu?
    assert "_satir[1] == 'revizyon_id'" in kaynak or "satir[1]" in kaynak, \
        "Python'da kolon adı karşılaştırması yok"


def t_f_notnull_sql_keyword_yok():
    """'notnull' SQLite keyword'ü SELECT sorgusunda kullanılmamalı."""
    dosya = os.path.join(_HERE, "092_nexgen_arge_etiket.py")
    with open(dosya, 'r', encoding='utf-8') as f:
        kaynak = f.read()
    import re
    # SELECT notnull FROM ... gibi bir kullanım varsa hata
    sql_notnull = re.findall(r'SELECT\s+notnull\s+FROM', kaynak, re.IGNORECASE)
    assert not sql_notnull, f"'SELECT notnull FROM' ifadesi hâlâ var: {sql_notnull}"


test("pragma_table_info() SQL fonksiyonu kaldırıldı", t_f_pragma_table_info_yok)
test("'SELECT notnull FROM' SQL ifadesi kaldırıldı", t_f_notnull_sql_keyword_yok)


# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  SONUÇ")
print(SEP)
TOPLAM = PASS + FAIL
print(f"  Toplam : {TOPLAM}")
print(f"  PASS   : {PASS}")
print(f"  FAIL   : {FAIL}")
print()

if FAIL > 0:
    print("  [!] Bazı testler başarısız.")
    sys.exit(1)
else:
    print("  [OK] Tüm testler geçti — commit güvenli.")
    sys.exit(0)
