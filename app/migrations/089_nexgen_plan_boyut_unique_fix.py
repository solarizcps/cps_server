# -*- coding: utf-8 -*-
"""
Migration 089 — NexGen FAZ-1 Stabilizasyon: nexgen_uretim_plan_boyut UNIQUE kısıt düzeltmesi
==============================================================================================
Sorun (YÜKSEK #9 / FAZ-1):
  Migration 088'de UNIQUE(plan_id, uretim_varyant_id) tanımlandı.
  Aynı plan içinde farklı boyutlar (LARGE, SMALL) farklı uretim_varyant_id kullanır,
  bu yüzden kısıt yanlış değil — ancak aynı boyut birden fazla kez eklenmesini
  engellemek gerekir. Doğru kısıt: UNIQUE(plan_id, boyut).

  SQLite ALTER TABLE ile kısıt değiştirilemez. Bu migration:
  1. Yeni tabloyu UNIQUE(plan_id, boyut) ile oluşturur.
  2. Mevcut veriyi taşır.
  3. Eski tabloyu siler, yeni tabloyu yeniden adlandırır.
  4. Index'leri yeniden oluşturur.

İdempotent: Tekrar çalıştırılabilir.
"""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def _tablo_var(cur, tablo):
    return cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (tablo,),
    ).fetchone() is not None


def _unique_kontrol(cur):
    """Mevcut tablodaki UNIQUE kısıtlarını sorgular."""
    row = cur.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='nexgen_uretim_plan_boyut'"
    ).fetchone()
    if not row:
        return None
    return row[0] or ''


def run():
    if not os.path.exists(DB_PATH):
        print(f'HATA: DB bulunamadi: {DB_PATH}')
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print('\n=== Migration 089: nexgen_uretim_plan_boyut UNIQUE(plan_id, boyut) ===')
    print(f'  DB: {os.path.abspath(DB_PATH)}')

    if not _tablo_var(cur, 'nexgen_uretim_plan_boyut'):
        print('  SKIP  nexgen_uretim_plan_boyut tablosu yok (088 çalışmamış?)')
        con.close()
        return

    mevcut_sql = _unique_kontrol(cur) or ''
    if 'UNIQUE(plan_id, boyut)' in mevcut_sql or 'unique(plan_id, boyut)' in mevcut_sql.lower():
        print('  SKIP  UNIQUE(plan_id, boyut) zaten mevcut')
        try:
            cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(89)")
            con.commit()
        except Exception:
            pass
        con.close()
        return

    print('  Mevcut kısıt: UNIQUE(plan_id, uretim_varyant_id) → değiştiriliyor...')

    # [1] Yeni tablo: UNIQUE(plan_id, boyut)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_uretim_plan_boyut_new (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id             INTEGER NOT NULL,
            uretim_varyant_id   INTEGER NOT NULL,
            boyut               TEXT NOT NULL,
            siparis_kg          REAL NOT NULL DEFAULT 0,
            formul_batch_kg     REAL DEFAULT 0,
            batch_sayisi        INTEGER DEFAULT 0,
            uretilecek_kg       REAL DEFAULT 0,
            fazla_kg            REAL DEFAULT 0,
            sira                INTEGER DEFAULT 0,
            aktif               INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi    TEXT DEFAULT (datetime('now','localtime')),
            guncelleme_tarihi   TEXT,
            UNIQUE(plan_id, boyut)
        )
    """)
    con.commit()

    # [2] Veri taşıma
    cur.execute("""
        INSERT OR IGNORE INTO nexgen_uretim_plan_boyut_new
            (id, plan_id, uretim_varyant_id, boyut, siparis_kg,
             formul_batch_kg, batch_sayisi, uretilecek_kg, fazla_kg,
             sira, aktif, olusturma_tarihi, guncelleme_tarihi)
        SELECT id, plan_id, uretim_varyant_id, boyut, siparis_kg,
               formul_batch_kg, batch_sayisi, uretilecek_kg, fazla_kg,
               sira, aktif, olusturma_tarihi, guncelleme_tarihi
        FROM nexgen_uretim_plan_boyut
    """)
    tasinan = cur.rowcount
    con.commit()
    print(f'  OK    {tasinan} satır taşındı')

    # [3] Eski tablo silinir, yeni tablo yeniden adlandırılır
    cur.execute("DROP TABLE nexgen_uretim_plan_boyut")
    cur.execute("ALTER TABLE nexgen_uretim_plan_boyut_new RENAME TO nexgen_uretim_plan_boyut")
    con.commit()
    print('  OK    Tablo yeniden adlandırıldı')

    # [4] Index'ler
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nupb_plan_id
        ON nexgen_uretim_plan_boyut(plan_id)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nupb_uv_id
        ON nexgen_uretim_plan_boyut(uretim_varyant_id)
    """)
    con.commit()
    print('  OK    Index\'ler yeniden oluşturuldu')

    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(89)")
        con.commit()
        print('  OK    schema_migrations version=89')
    except Exception as e:
        print(f'  WARN  schema_migrations: {e}')

    toplam = cur.execute("SELECT COUNT(*) FROM nexgen_uretim_plan_boyut").fetchone()[0]
    print(f'  CHECK toplam boyut satırı: {toplam}')
    print('=== Migration 089 tamamlandı ===\n')

    con.close()


if __name__ == '__main__':
    run()
