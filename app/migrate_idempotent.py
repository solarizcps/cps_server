# -*- coding: utf-8 -*-
"""
CPS DEV - BLOK 4.6 Idempotent Parse Migration
==============================================
Upload'tan parse edilen kalemlerin izlenebilirligi + idempotency icin
gerekli semayi ekler.

Degisiklikler:
  1) ithalat_maliyet_kalem'e 5 yeni sutun:
     - Iptal, IptalSebep, IptalTarih (soft delete)
     - KaynakBelgeId, KaynakBelgeRef (izlenebilirlik + idempotency)

  2) Yeni tablo: ithalat_belge_parse
     - Her belge icin parse durum kaydi
     - Unique index: BelgeId (bir belge icin tek kayit)

Calistir:
    cd C:\\cps_dev
    python migrate_idempotent.py

Idempotent: Tekrar tekrar calistirilabilir.
  - Mevcut sutun varsa atlar
  - Mevcut tablo/index varsa atlar
  - Mevcut kayitlara dokunmaz
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_conn, tablo_var_mi, kolon_var_mi
from config import Config


# =====================================================================
# YENI SUTUNLAR - ithalat_maliyet_kalem
# =====================================================================
MALIYET_KALEM_YENI_KOLONLAR = [
    # (kolon_adi, SQL tipi, default)
    ('Iptal',          'INTEGER NOT NULL DEFAULT 0'),
    ('IptalSebep',     'TEXT'),
    ('IptalTarih',     'TEXT'),
    ('KaynakBelgeId',  'INTEGER'),
    ('KaynakBelgeRef', 'TEXT'),
]


# =====================================================================
# YENI TABLO - ithalat_belge_parse
# =====================================================================
SQL_BELGE_PARSE_TABLO = """
CREATE TABLE IF NOT EXISTS ithalat_belge_parse (
    Id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    BelgeId            INTEGER NOT NULL,
    PartiId            INTEGER NOT NULL,
    BelgeTipi          TEXT NOT NULL,
    ParseDurum         TEXT NOT NULL DEFAULT 'BEKLIYOR',
    ParseMesaj         TEXT,
    KaynakBelgeRef     TEXT,
    DosyaHash          TEXT,
    UygulananKalemSayisi INTEGER DEFAULT 0,
    KaynakBelgeIdList  TEXT,
    Parseden           TEXT,
    ParseTarih         TEXT NOT NULL,
    GuncellemeTarih    TEXT,
    NotMetni           TEXT,
    FOREIGN KEY (BelgeId) REFERENCES sistem_belge(Id) ON DELETE CASCADE,
    FOREIGN KEY (PartiId) REFERENCES ithalat_parti(Id) ON DELETE CASCADE
)
"""


# =====================================================================
# INDEXLER
# =====================================================================
INDEXLER = [
    # ithalat_maliyet_kalem uzerinde
    ("ix_mk_kaynak_ref",
     "CREATE INDEX IF NOT EXISTS ix_mk_kaynak_ref "
     "ON ithalat_maliyet_kalem(PartiId, KaynakBelgeRef)"),

    ("ix_mk_iptal",
     "CREATE INDEX IF NOT EXISTS ix_mk_iptal "
     "ON ithalat_maliyet_kalem(PartiId, Iptal)"),

    ("ix_mk_kaynak_belge",
     "CREATE INDEX IF NOT EXISTS ix_mk_kaynak_belge "
     "ON ithalat_maliyet_kalem(KaynakBelgeId)"),

    # ithalat_belge_parse uzerinde
    ("ix_bp_belge",
     "CREATE UNIQUE INDEX IF NOT EXISTS ix_bp_belge "
     "ON ithalat_belge_parse(BelgeId)"),

    ("ix_bp_parti_ref",
     "CREATE INDEX IF NOT EXISTS ix_bp_parti_ref "
     "ON ithalat_belge_parse(PartiId, KaynakBelgeRef)"),

    ("ix_bp_hash",
     "CREATE INDEX IF NOT EXISTS ix_bp_hash "
     "ON ithalat_belge_parse(DosyaHash)"),

    ("ix_bp_durum",
     "CREATE INDEX IF NOT EXISTS ix_bp_durum "
     "ON ithalat_belge_parse(ParseDurum, ParseTarih)"),
]


# =====================================================================
# ANA AKIS
# =====================================================================
def main():
    print("=" * 70)
    print("  CPS DEV - BLOK 4.6 Idempotent Parse Migration")
    print(f"  DB_MODE: {Config.DB_MODE}")
    if Config.DB_MODE == 'mock':
        print(f"  SQLite:  {Config.MOCK_DB_PATH}")
    else:
        print(f"  MSSQL:   {Config.MSSQL_HOST}/{Config.MSSQL_DATABASE}")
    print("=" * 70)

    degisiklikler = []
    atlananlar = []

    # -----------------------------------------------------------------
    # 1) ithalat_maliyet_kalem var mi?
    # -----------------------------------------------------------------
    print("\n[1] ithalat_maliyet_kalem tablo kontrol...")
    if not tablo_var_mi('ithalat_maliyet_kalem'):
        print("  [HATA] Tablo yok! Once init_ithalat_db.py calistir.")
        sys.exit(1)
    print("  [OK] Tablo mevcut")

    # -----------------------------------------------------------------
    # 2) Yeni sutunlar
    # -----------------------------------------------------------------
    print("\n[2] ithalat_maliyet_kalem yeni sutunlar...")
    c = get_conn()
    try:
        cur = c.cursor()
        for kolon_ad, kolon_tip in MALIYET_KALEM_YENI_KOLONLAR:
            if kolon_var_mi('ithalat_maliyet_kalem', kolon_ad):
                atlananlar.append(f"sutun {kolon_ad} (zaten var)")
                print(f"  [SKIP] {kolon_ad} zaten var")
                continue
            try:
                sql = f"ALTER TABLE ithalat_maliyet_kalem ADD COLUMN {kolon_ad} {kolon_tip}"
                cur.execute(sql)
                degisiklikler.append(f"sutun eklendi: {kolon_ad}")
                print(f"  [OK]   {kolon_ad} eklendi")
            except Exception as e:
                print(f"  [HATA] {kolon_ad} eklenemedi: {e}")
        c.commit()
    finally:
        c.close()

    # -----------------------------------------------------------------
    # 3) Yeni tablo: ithalat_belge_parse
    # -----------------------------------------------------------------
    print("\n[3] ithalat_belge_parse tablosu...")
    zaten_var = tablo_var_mi('ithalat_belge_parse')
    c = get_conn()
    try:
        cur = c.cursor()
        cur.execute(SQL_BELGE_PARSE_TABLO)
        c.commit()
        if zaten_var:
            atlananlar.append("tablo ithalat_belge_parse (zaten var)")
            print("  [SKIP] Tablo zaten var")
        else:
            degisiklikler.append("yeni tablo: ithalat_belge_parse")
            print("  [OK]   Tablo olusturuldu")
    finally:
        c.close()

    # -----------------------------------------------------------------
    # 4) Indexler
    # -----------------------------------------------------------------
    print("\n[4] Indexler...")
    c = get_conn()
    try:
        cur = c.cursor()
        for index_ad, sql in INDEXLER:
            try:
                cur.execute(sql)
                print(f"  [OK]   {index_ad}")
            except Exception as e:
                print(f"  [WARN] {index_ad}: {e}")
        c.commit()
    finally:
        c.close()

    # -----------------------------------------------------------------
    # 5) Dogrulama
    # -----------------------------------------------------------------
    print("\n[5] Dogrulama...")
    tum_sutunlar_ok = all(
        kolon_var_mi('ithalat_maliyet_kalem', kol)
        for kol, _ in MALIYET_KALEM_YENI_KOLONLAR
    )
    tablo_ok = tablo_var_mi('ithalat_belge_parse')

    if tum_sutunlar_ok:
        print("  [OK] ithalat_maliyet_kalem yeni sutunlar hazir")
    else:
        print("  [HATA] Bazi sutunlar eksik!")

    if tablo_ok:
        print("  [OK] ithalat_belge_parse tablosu hazir")
    else:
        print("  [HATA] Tablo olusturulamadi!")

    # -----------------------------------------------------------------
    # 6) Ozet
    # -----------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  MIGRATION OZETI")
    print("=" * 70)
    print(f"  Yapilan degisiklik  : {len(degisiklikler)}")
    for d in degisiklikler:
        print(f"    + {d}")
    print(f"  Atlanan (zaten var) : {len(atlananlar)}")
    for a in atlananlar:
        print(f"    . {a}")
    print("")
    print("  BILGI: Eski manuel kalemlerde KaynakBelgeRef = NULL")
    print("         Sistem bu kalemleri 'manuel giris' kabul edecek,")
    print("         idempotency kontrollerine dahil etmeyecek.")
    print("")
    print("  Sonraki adim: Flask restart (veya 'python app.py')")
    print("=" * 70)


if __name__ == '__main__':
    main()
