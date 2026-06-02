# -*- coding: utf-8 -*-
"""
FAZ 4.3 - USTA GOREVLERI Migration Scripti
============================================
Karar Masasi -> Usta Paneli pilot baglantisi icin
yeni tablo: usta_gorevleri

Idempotent: Birden fazla calistirilabilir.
Rollback: rollback_faz43_usta_gorevleri.py

Calistirma:
    python setup_faz43_usta_gorevleri.py
"""
import sqlite3
import os
import shutil
import sys
from datetime import datetime

DB_PATH = r"C:\cps_dev\solariz_dev.db"

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS usta_gorevleri (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    karar_masasi_satir_id TEXT,
    siparis_no TEXT NOT NULL,
    emir_no TEXT,
    musteri TEXT NOT NULL,
    model TEXT NOT NULL,
    bant TEXT,
    hedef_adet INTEGER NOT NULL DEFAULT 0,
    kalan_adet INTEGER,
    uretilebilirlik TEXT,
    darbogaz TEXT,
    talimat TEXT,
    oncelik INTEGER DEFAULT 50,
    musteri_etiketi TEXT,
    atanan_usta TEXT,
    olusturan TEXT NOT NULL,
    olusturan_notu TEXT,
    durum TEXT NOT NULL DEFAULT 'ATANDI',
    olusturma_tarih DATETIME DEFAULT (datetime('now', 'localtime')),
    okuma_tarih DATETIME,
    baslama_tarih DATETIME,
    tamamlanma_tarih DATETIME,
    termin TEXT,
    termin_durumu TEXT,
    usta_notu TEXT
);
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_ug_durum ON usta_gorevleri(durum);",
    "CREATE INDEX IF NOT EXISTS idx_ug_atanan ON usta_gorevleri(atanan_usta);",
    "CREATE INDEX IF NOT EXISTS idx_ug_tarih ON usta_gorevleri(olusturma_tarih);",
    "CREATE INDEX IF NOT EXISTS idx_ug_siparis ON usta_gorevleri(siparis_no);",
]

BEKLENEN_KOLONLAR = [
    "id", "karar_masasi_satir_id", "siparis_no", "emir_no", "musteri",
    "model", "bant", "hedef_adet", "kalan_adet", "uretilebilirlik",
    "darbogaz", "talimat", "oncelik", "musteri_etiketi", "atanan_usta",
    "olusturan", "olusturan_notu", "durum", "olusturma_tarih",
    "okuma_tarih", "baslama_tarih", "tamamlanma_tarih", "termin",
    "termin_durumu", "usta_notu"
]


def yedek_al():
    if not os.path.exists(DB_PATH):
        print(f"[HATA] DB bulunamadi: {DB_PATH}")
        sys.exit(1)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    yedek = f"{DB_PATH}.YEDEK_FAZ43_{ts}"
    shutil.copy2(DB_PATH, yedek)
    boyut = os.path.getsize(yedek)
    print(f"[OK] Yedek alindi: {os.path.basename(yedek)} ({boyut:,} byte)")
    return yedek


def tablo_var_mi(conn):
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='usta_gorevleri'"
    )
    return cur.fetchone() is not None


def kayit_sayisi(conn):
    try:
        cur = conn.execute("SELECT COUNT(*) FROM usta_gorevleri")
        return cur.fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def kolon_listesi(conn):
    cur = conn.execute("PRAGMA table_info(usta_gorevleri)")
    return [r[1] for r in cur.fetchall()]


def main():
    print("=" * 60)
    print("FAZ 4.3 - USTA GOREVLERI Migration")
    print("=" * 60)
    print(f"DB Path: {DB_PATH}")
    print()

    yedek = yedek_al()
    conn = sqlite3.connect(DB_PATH, timeout=10)

    try:
        var_onceden = tablo_var_mi(conn)
        kayit_onceden = kayit_sayisi(conn) if var_onceden else 0

        if var_onceden:
            print(f"[BILGI] Tablo zaten var. Mevcut kayit: {kayit_onceden}")
        else:
            print("[BILGI] Tablo yok, olusturuluyor...")

        conn.execute(CREATE_SQL)
        print("[OK] CREATE TABLE basarili")

        for idx_sql in INDEXES:
            conn.execute(idx_sql)
        print(f"[OK] {len(INDEXES)} index olusturuldu")

        conn.commit()

        kolonlar = kolon_listesi(conn)
        eksik = [k for k in BEKLENEN_KOLONLAR if k not in kolonlar]
        fazla = [k for k in kolonlar if k not in BEKLENEN_KOLONLAR]

        print()
        print("=" * 60)
        print("DOGRULAMA")
        print("=" * 60)
        print(f"Toplam kolon: {len(kolonlar)} (beklenen: {len(BEKLENEN_KOLONLAR)})")

        if eksik:
            print(f"[!!] EKSIK kolonlar: {eksik}")
        if fazla:
            print(f"[!!] FAZLA kolonlar (eski tablo?): {fazla}")
        if not eksik and not fazla:
            print("[OK] Tum kolonlar dogru")

        kayit_sonra = kayit_sayisi(conn)
        print(f"Kayit sayisi: {kayit_sonra}")

        cur = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name='usta_gorevleri' "
            "ORDER BY name"
        )
        indexler = [r[0] for r in cur.fetchall()]
        print(f"Index'ler ({len(indexler)}):")
        for idx in indexler:
            print(f"  - {idx}")

        print()
        print("=" * 60)
        print(f"[TAMAM] FAZ 4.3 migration basarili")
        print(f"        Yedek: {os.path.basename(yedek)}")
        print("=" * 60)

    except Exception as e:
        print(f"[HATA] Migration basarisiz: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()