# -*- coding: utf-8 -*-
"""
Migration 079 — NexGen FAZ-3G + FAZ-3A-STOK:
  Bölüm A) nexgen_rf_kullanim ↔ tablet uretim baglantisi
  Bölüm B) nexgen_stok_kart kimlik alanları + seed

---
Bölüm A: nexgen_rf_kullanim genisletme
  - uretim_emir_id    (nexgen_uretim_parca.id, nullable)
  - tablet_session_id (batch_kodu, nullable)
  - durum             (MANUEL | URETIM | TAMAMLANDI)
  - miktar_kg         (REAL, default 0)
  - guncelleme_tarihi (TEXT)

Bölüm B: nexgen_stok_kart kimlik alanları
  - tanim            (TEXT)
  - yeni_tanim       (TEXT)
  - renk_bileseni_mi (INTEGER DEFAULT 0)
  Seed: 63 kayıt tanim/yeni_tanim, 26 kayıt renk_bileseni_mi=1
  Seed güvenli: sadece NULL veya boş olan satırlar güncellenir
                renk_bileseni_mi her zaman referans listesine göre set edilir

Idempotent. Rollback: yeni kolonlar SQLite'ta kalir (guvenli); index drop.
KURAL: RF/BOYA/ARGE/formul/recete_kalem DOKUNULMAZ.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def _kolon_var(cur, tablo, kolon):
    return kolon in [c[1] for c in cur.execute(f"PRAGMA table_info({tablo})").fetchall()]


# ── Ortak seed verisi — routes.py ve repair script ile tek kaynak ──────────
# (kod, tanim, yeni_tanim) — 63 kayıt
STOK_KIMLIK_SEED = [
    ('NEX-01-01','ANA MALZEME','N0A1'), ('NEX-01-02','ANA MALZEME','N0A1'),
    ('NEX-01-03','ANA MALZEME','N0A1'), ('NEX-01-04','ANA MALZEME','N0A1'),
    ('NEX-02-01','ANA MALZEME','N0A2'),
    ('NEX-03-01','ANA MALZEME','N0A4'), ('NEX-03-02','ANA MALZEME','N0A5'),
    ('NEX-03-03','ANA MALZEME','N0A7'), ('NEX-03-04','ANA MALZEME','N0A6'),
    ('NEX-07-01','ANA MALZEME','N0A3'), ('NEX-07-02','Yan malzeme','N0YN'),
    ('NEX-04-01','Katki','NK01'), ('NEX-04-02','Katki','NK03'),
    ('NEX-04-03','Katki','NK02'), ('NEX-04-04','Katki','NK10'),
    ('NEX-05-01','Katki','NK06'), ('NEX-05-02','Katki','NK07'),
    ('NEX-05-03','Katki','NK08'), ('NEX-05-04','Katki','NK09'),
    ('NEX-05-05','Katki','NK12'), ('NEX-05-06','Katki','NK13'),
    ('NEX-05-07','Katki','NK05'), ('NEX-05-08','Katki','NK11'),
    ('NEX-06-01','Katki','NK04'),
    ('NEX-08-01','Pigment boya','NB19'), ('NEX-08-02','Pigment boya','NB16'),
    ('NEX-08-03','Pigment boya','NB17'), ('NEX-08-04','Pigment boya','NB18'),
    ('NEX-08-05','Pigment boya','NB01'), ('NEX-08-06','Pigment boya','NB02'),
    ('NEX-08-07','Pigment boya','NB06'), ('NEX-08-08','Pigment boya','NB07'),
    ('NEX-08-09','Pigment boya','NB21'), ('NEX-08-10','Pigment boya','NB05'),
    ('NEX-08-11','Pigment boya','NB20'), ('NEX-08-12','Pigment boya','NB10'),
    ('NEX-08-13','Pigment boya','NB09'), ('NEX-08-14','Pigment boya','NB11'),
    ('NEX-08-15','Pigment boya','NB04'), ('NEX-08-16','Pigment boya','NB12'),
    ('NEX-08-17','Pigment boya','NB13'), ('NEX-08-18','Pigment boya','NB03'),
    ('NEX-08-19','Pigment boya','NB15'), ('NEX-08-20','Pigment boya','NB22'),
    ('NEX-08-21','Pigment boya','NB08'), ('NEX-08-22','Pigment boya','NB14'),
    ('NEX-09-01','MASTERBATCH BOYA','NBA2'), ('NEX-09-02','MASTERBATCH BOYA','NBA1'),
    ('NEX-MB-01','BOYA','NBA3'),
    ('NEX-10-01','BIOGREEN','NR33'), ('NEX-10-02','BIOGREEN','NR31'),
    ('NEX-10-03','BIOGREEN','NR32'), ('NEX-10-04','BIOGREEN','NR01'),
    ('NEX-10-05','BIOGREEN','NR02'), ('NEX-10-06','BIOGREEN','NR03'),
    ('NEX-10-07','BIOGREEN','NR04'), ('NEX-10-08','BIOGREEN','NR05'),
    ('NEX-10-09','BIOGREEN','NR06'), ('NEX-10-10','BIOGREEN','NR07'),
    ('NEX-10-11','BIOGREEN','NR08'), ('NEX-10-12','BIOGREEN','NR09'),
    ('NEX-10-13','BIOGREEN','NR10'), ('NEX-10-14','BIOGREEN','NR11'),
    ('NEX-10-15','BIOGREEN','NR12'), ('NEX-10-16','BIOGREEN','NR13'),
    ('NEX-10-17','BIOGREEN','NR14'), ('NEX-10-18','BIOGREEN','NR15'),
    ('NEX-10-19','BIOGREEN','NR16'), ('NEX-10-20','BIOGREEN','NR17'),
    ('NEX-10-21','BIOGREEN','NR18'), ('NEX-10-22','BIOGREEN','NR19'),
    ('NEX-10-23','BIOGREEN','NR20'), ('NEX-10-24','BIOGREEN','NR21'),
    ('NEX-10-25','BIOGREEN','NR22'), ('NEX-10-26','BIOGREEN','NR23'),
    ('NEX-10-27','BIOGREEN','NR24'), ('NEX-10-28','BIOGREEN','NR25'),
    ('NEX-10-29','BIOGREEN','NR26'), ('NEX-10-30','BIOGREEN','NR27'),
    ('NEX-10-31','BIOGREEN','NR28'), ('NEX-10-32','BIOGREEN','NR29'),
    ('NEX-10-33','BIOGREEN','NR30'),
]  # 63 kayıt

# renk_bileseni_mi=1 olacak stok kodları — 26 kayıt
RENK_BILESENI_KODLAR = (
    'NEX-08-01','NEX-08-02','NEX-08-03','NEX-08-04','NEX-08-05',
    'NEX-08-06','NEX-08-07','NEX-08-08','NEX-08-09','NEX-08-10',
    'NEX-08-11','NEX-08-12','NEX-08-13','NEX-08-14','NEX-08-15',
    'NEX-08-16','NEX-08-17','NEX-08-18','NEX-08-19','NEX-08-20',
    'NEX-08-21','NEX-08-22',
    'NEX-09-01','NEX-09-02','NEX-MB-01',
    'NEX-04-01',  # ATR-312: KATKI kalır, renk bileşeni olarak da seçilir
)


def _stok_kimlik_seed_uygula(cur, con):
    """
    Güvenli seed kuralları:
    - tanim/yeni_tanim: sadece NULL veya boş ise güncelle (kullanıcı değerleri korunur)
    - renk_bileseni_mi: referans listesine göre her zaman set edilir (master data)
    """
    tanim_guncellenen = 0
    for kod, tanim, yeni_tanim in STOK_KIMLIK_SEED:
        rc = cur.execute(
            """UPDATE nexgen_stok_kart
               SET tanim=?, yeni_tanim=?
               WHERE kod=?
                 AND (tanim IS NULL OR tanim=''
                      OR yeni_tanim IS NULL OR yeni_tanim='')""",
            (tanim, yeni_tanim, kod)
        ).rowcount
        tanim_guncellenen += rc

    # renk_bileseni_mi: tüm kartları sıfırla, sonra listedeki kodları 1 yap
    cur.execute("UPDATE nexgen_stok_kart SET renk_bileseni_mi = 0")
    renk_guncellenen = sum(
        cur.execute(
            "UPDATE nexgen_stok_kart SET renk_bileseni_mi = 1 WHERE kod = ?", (k,)
        ).rowcount for k in RENK_BILESENI_KODLAR
    )
    con.commit()
    return tanim_guncellenen, renk_guncellenen


def run():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    print("\n=== Migration 079: nexgen_rf_kullanim + nexgen_stok_kart kimlik ===")
    print(f"  DB: {os.path.abspath(DB_PATH)}")

    # ── Bölüm A: nexgen_rf_kullanim tablet bağlantı kolonları ──────────────
    print("\n[A] nexgen_rf_kullanim tablet baglantisi:")
    yeni_kolonlar = (
        ('uretim_emir_id',    'INTEGER'),
        ('tablet_session_id', 'TEXT'),
        ('durum',             "TEXT NOT NULL DEFAULT 'MANUEL'"),
        ('miktar_kg',         'REAL NOT NULL DEFAULT 0'),
        ('guncelleme_tarihi', 'TEXT'),
    )
    for kolon, tip in yeni_kolonlar:
        if not _kolon_var(cur, 'nexgen_rf_kullanim', kolon):
            cur.execute(f"ALTER TABLE nexgen_rf_kullanim ADD COLUMN {kolon} {tip}")
            con.commit()
            print(f"  OK    nexgen_rf_kullanim.{kolon}")
        else:
            print(f"  SKIP  {kolon} zaten var")

    indexler = [
        ("idx_nrfkull_emir",    "nexgen_rf_kullanim(uretim_emir_id)"),
        ("idx_nrfkull_session", "nexgen_rf_kullanim(tablet_session_id)"),
        ("idx_nrfkull_durum",   "nexgen_rf_kullanim(durum)"),
    ]
    for idx_ad, idx_hedef in indexler:
        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_ad} ON {idx_hedef}")
    con.commit()
    print(f"  OK    {len(indexler)} index")

    # ── Bölüm B: nexgen_stok_kart kimlik kolonları + seed ──────────────────
    print("\n[B] nexgen_stok_kart kimlik alanlari:")
    stok_kolonlar = [
        ('tanim',            'TEXT'),
        ('yeni_tanim',       'TEXT'),
        ('renk_bileseni_mi', 'INTEGER DEFAULT 0'),
    ]
    for kolon, tip in stok_kolonlar:
        if not _kolon_var(cur, 'nexgen_stok_kart', kolon):
            cur.execute(f"ALTER TABLE nexgen_stok_kart ADD COLUMN {kolon} {tip}")
            con.commit()
            print(f"  OK    nexgen_stok_kart.{kolon}")
        else:
            print(f"  SKIP  {kolon} zaten var")

    tanim_n, renk_n = _stok_kimlik_seed_uygula(cur, con)
    print(f"  SEED  tanim/yeni_tanim guncellenen: {tanim_n} kayit")
    print(f"  SEED  renk_bileseni_mi=1 set edilen: {renk_n} kayit")
    print(f"  INFO  Toplam seed tanimi: {len(STOK_KIMLIK_SEED)} kayit")
    print(f"  INFO  Renk bileseni referans liste: {len(RENK_BILESENI_KODLAR)} kod")

    # ── schema_migrations ──────────────────────────────────────────────────
    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(79)")
        con.commit()
        print("\n  OK    schema_migrations version=79")
    except Exception as e:
        print(f"\n  WARN  schema_migrations: {e}")

    # ── Doğrulama ──────────────────────────────────────────────────────────
    rf_cols = [c[1] for c in cur.execute("PRAGMA table_info(nexgen_rf_kullanim)").fetchall()]
    sk_cols = [c[1] for c in cur.execute("PRAGMA table_info(nexgen_stok_kart)").fetchall()]
    print(f"\n  CHECK nexgen_rf_kullanim kolonlar: {rf_cols}")
    print(f"  CHECK nexgen_stok_kart kimlik: tanim={'tanim' in sk_cols}, "
          f"yeni_tanim={'yeni_tanim' in sk_cols}, "
          f"renk_bileseni_mi={'renk_bileseni_mi' in sk_cols}")

    con.close()
    print("=== Migration 079 tamamlandi ===\n")


def rollback():
    """Indexleri kaldir; kolonlar SQLite ALTER DROP desteklemez."""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    print("\n=== Rollback 079: index drop ===")
    for idx in ('idx_nrfkull_emir', 'idx_nrfkull_session', 'idx_nrfkull_durum'):
        cur.execute(f"DROP INDEX IF EXISTS {idx}")
    try:
        cur.execute("DELETE FROM schema_migrations WHERE version=79")
    except Exception:
        pass
    con.commit()
    con.close()
    print("  OK    indexler kaldirildi (kolonlar kalir)")
    print("=== Rollback 079 tamamlandi ===\n")


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'rollback':
        rollback()
    else:
        run()
