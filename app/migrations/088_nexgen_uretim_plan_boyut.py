# -*- coding: utf-8 -*-
"""
Migration 088 — NexGen FAZ-BOYUT-1: Çok boyutlu MPR alt satır tablosu
======================================================================
[1] nexgen_uretim_plan_boyut tablosu + indexler
[2] Mevcut nexgen_uretim_plan kayıtları için backfill (tek boyut satırı)
[3] schema_migrations version=88

NOT:
- Header (nexgen_uretim_plan) değiştirilmez.
- Stok hareketi / MPR motoru / API davranışı değişmez.
- DB'de MEDIUM üretilmez; boyut uv.boyut değerinden gelir (STANDART dahil).
- İdempotent: Tekrar çalıştırılabilir.
"""

import math
import os
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def _tablo_var(cur, tablo):
    return cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (tablo,),
    ).fetchone() is not None


def _index_var(cur, index_adi):
    return cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (index_adi,),
    ).fetchone() is not None


def _formul_batch_kg_hesapla(con, uretim_varyant_id):
    """routes._formul_batch_kg_hesapla ile aynı mantık (BOYA hariç)."""
    row = con.execute("""
        SELECT COALESCE(SUM(rk.miktar_kg), 0) AS toplam
        FROM nexgen_recete_kalem rk
        JOIN nexgen_stok_kart sk ON sk.id = rk.stok_kart_id
        WHERE rk.uretim_varyant_id = ? AND rk.aktif = 1
          AND UPPER(COALESCE(sk.kategori, '')) != 'BOYA'
    """, (uretim_varyant_id,)).fetchone()
    return round(float(row[0]), 3) if row else 0.0


def _batch_hesapla(formul_batch_kg, planlanan_kg):
    """routes._batch_uretim_hesapla ile uyumlu cache alanları."""
    siparis_kg = round(float(planlanan_kg or 0), 3)
    if formul_batch_kg <= 0 or siparis_kg <= 0:
        return {
            'formul_batch_kg': round(float(formul_batch_kg or 0), 3),
            'batch_sayisi': 0,
            'uretilecek_kg': 0.0,
            'fazla_kg': 0.0,
        }
    batch_sayisi = int(math.ceil(siparis_kg / formul_batch_kg))
    uretilecek_kg = round(batch_sayisi * formul_batch_kg, 3)
    fazla_kg = round(uretilecek_kg - siparis_kg, 3)
    return {
        'formul_batch_kg': round(formul_batch_kg, 3),
        'batch_sayisi': batch_sayisi,
        'uretilecek_kg': uretilecek_kg,
        'fazla_kg': fazla_kg,
    }


def _boyut_sira(boyut):
    b = (boyut or '').upper()
    if b == 'LARGE':
        return 1
    if b == 'SMALL':
        return 2
    if b == 'STANDART':
        return 3
    return 9


def run():
    if not os.path.exists(DB_PATH):
        print(f'HATA: DB bulunamadi: {DB_PATH}')
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print('\n=== Migration 088: nexgen_uretim_plan_boyut ===')
    print(f'  DB: {os.path.abspath(DB_PATH)}')

    # [1] Tablo
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_uretim_plan_boyut (
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
            UNIQUE(plan_id, uretim_varyant_id)
        )
    """)
    con.commit()
    print('  OK    nexgen_uretim_plan_boyut')

    if not _index_var(cur, 'idx_nupb_plan_id'):
        cur.execute("""
            CREATE INDEX idx_nupb_plan_id
            ON nexgen_uretim_plan_boyut(plan_id)
        """)
        print('  OK    idx_nupb_plan_id')
    else:
        print('  SKIP  idx_nupb_plan_id')

    if not _index_var(cur, 'idx_nupb_uv_id'):
        cur.execute("""
            CREATE INDEX idx_nupb_uv_id
            ON nexgen_uretim_plan_boyut(uretim_varyant_id)
        """)
        print('  OK    idx_nupb_uv_id')
    else:
        print('  SKIP  idx_nupb_uv_id')

    con.commit()

    # [2] Backfill
    planlar = cur.execute("""
        SELECT np.id, np.uretim_varyant_id, np.planlanan_kg, uv.boyut
        FROM nexgen_uretim_plan np
        JOIN nexgen_uretim_varyant uv ON uv.id = np.uretim_varyant_id
        WHERE np.uretim_varyant_id IS NOT NULL
        ORDER BY np.id
    """).fetchall()

    eklendi = 0
    atlandi = 0
    hata = 0
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    for p in planlar:
        mevcut = cur.execute(
            "SELECT id FROM nexgen_uretim_plan_boyut WHERE plan_id=?",
            (p['id'],),
        ).fetchone()
        if mevcut:
            atlandi += 1
            continue

        uv_id = p['uretim_varyant_id']
        boyut = (p['boyut'] or 'STANDART').upper()
        if boyut == 'MEDIUM':
            boyut = 'STANDART'

        siparis_kg = round(float(p['planlanan_kg'] or 0), 3)
        fb = _formul_batch_kg_hesapla(con, uv_id)
        bh = _batch_hesapla(fb, siparis_kg)

        try:
            cur.execute("""
                INSERT INTO nexgen_uretim_plan_boyut (
                    plan_id, uretim_varyant_id, boyut, siparis_kg,
                    formul_batch_kg, batch_sayisi, uretilecek_kg, fazla_kg,
                    sira, aktif, olusturma_tarihi, guncelleme_tarihi
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """, (
                p['id'], uv_id, boyut, siparis_kg,
                bh['formul_batch_kg'], bh['batch_sayisi'],
                bh['uretilecek_kg'], bh['fazla_kg'],
                _boyut_sira(boyut), now, now,
            ))
            eklendi += 1
        except sqlite3.IntegrityError:
            atlandi += 1
        except Exception as ex:
            hata += 1
            print(f'  WARN  plan_id={p["id"]} backfill hata: {ex}')

    con.commit()

    toplam_plan = len(planlar)
    toplam_satir = cur.execute(
        "SELECT COUNT(*) FROM nexgen_uretim_plan_boyut"
    ).fetchone()[0]
    medium_cnt = cur.execute(
        "SELECT COUNT(*) FROM nexgen_uretim_plan_boyut WHERE UPPER(boyut)='MEDIUM'"
    ).fetchone()[0]

    print(f'  OK    backfill: plan={toplam_plan}, yeni_satir={eklendi}, '
          f'atlandi={atlandi}, hata={hata}')
    print(f'  CHECK boyut satiri toplam: {toplam_satir}')
    print(f'  CHECK MEDIUM satir: {medium_cnt} (0 olmali)')

    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(88)")
        con.commit()
        print('  OK    schema_migrations version=88')
    except Exception as e:
        print(f'  WARN  schema_migrations: {e}')

    con.close()
    print('=== Migration 088 tamamlandi ===\n')


if __name__ == '__main__':
    run()
