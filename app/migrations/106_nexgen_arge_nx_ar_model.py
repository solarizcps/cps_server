# -*- coding: utf-8 -*-
"""
Migration 106 — NX-AR tek çalışma kartı veri modeli
====================================================
FAZ-ARGE-2C / 2D1.

Ekler (idempotent):
  nexgen_arge_test     — NX-AR kart kolonları
  nexgen_arge_kaynak_uv
  nexgen_arge_deneme
  nexgen_arge_deneme_kalem
  nexgen_arge_boyut_sonuc
  nexgen_arge_olusan_uv
  nexgen_arge_revizyon — deneme_id (diğer istenen alanlar mevcut eşdeğerlerle karşılanır)

Kurallar:
  - Idempotent (ikinci çalıştırmada sıfır yeni değişiklik)
  - Mevcut veri silinmez / güncellenmez
  - onay_notu tekrar eklenmez
  - Gerçek DB'de kullanıcı onayı + dış backup olmadan çalıştırılmamalı

Çalıştırma:
  python app/migrations/106_nexgen_arge_nx_ar_model.py
  python app/migrations/106_nexgen_arge_nx_ar_model.py --db PATH
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.normpath(os.path.join(_HERE, '..', 'mock_data.db'))
VERSION = '106'

TEST_KOLONLAR = [
    ('calisma_tipi', "TEXT NOT NULL DEFAULT 'YENI_RF'"),
    ('guncelleme_tarihi', 'TEXT'),
    ('sorumlu_kullanici_id', 'INTEGER'),
    ('oncelik', "TEXT NOT NULL DEFAULT 'NORMAL'"),
    ('urun_ailesi', 'TEXT'),
    ('formul_grup_adi', 'TEXT'),
    ('ana_formul_grup_kodu', 'TEXT'),
    ('renk_kodu', 'TEXT'),
    ('yogunluk_hedef', 'REAL'),
    ('saha_testi_gerekli_mi', 'INTEGER NOT NULL DEFAULT 0'),
    ('saha_testi_nedeni', 'TEXT'),
    ('saha_testi_karar_veren_id', 'INTEGER'),
    ('saha_testi_karar_tarihi', 'TEXT'),
    ('ferhat_genel_karar', 'TEXT'),
    ('ferhat_genel_not', 'TEXT'),
    ('ferhat_kaydeden_id', 'INTEGER'),
    ('ferhat_kayit_tarihi', 'TEXT'),
]

# İstenen kavramsal alan → mevcut kolon (varsa ADD atlanır)
REVIZYON_ESDEGER = {
    'revizyon_no': 'rev_no',
    'degisiklik_nedeni': 'neden',
    'olusturan_kullanici_id': 'olusturan_id',
    'created_at': 'olusturma_tarihi',
    'snapshot_json': 'snapshot_json',
}


def _kolon_var(cur, tablo, kolon):
    return kolon in [c[1] for c in cur.execute(f'PRAGMA table_info({tablo})').fetchall()]


def _tablo_var(cur, tablo):
    return bool(cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
    ).fetchone())


def _index_var(cur, name):
    return bool(cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (name,)
    ).fetchone())


def run(db_path: str | None = None, take_internal_backup: bool = False) -> dict:
    """Migration uygular. Dönüş: değişiklik sayaçları."""
    db_path = os.path.abspath(db_path or DEFAULT_DB)
    stats = {
        'db': db_path,
        'kolon_eklendi': 0,
        'tablo_olusturuldu': 0,
        'index_olusturuldu': 0,
        'revizyon_kolon': 0,
        'skip': 0,
        'ok': False,
        'log': [],
    }

    def log(msg):
        stats['log'].append(msg)
        print(msg)

    if not os.path.exists(db_path):
        log(f'[106] HATA: DB bulunamadi: {db_path}')
        return stats

    if take_internal_backup:
        import shutil
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        bak = db_path.replace('.db', f'_backup_pre106_{ts}.db')
        try:
            shutil.copy2(db_path, bak)
            log(f'[106] YEDEK(internal): {bak}')
        except Exception as e:
            log(f'[106] UYARI internal yedek: {e}')

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    log('=' * 70)
    log('Migration 106 - NX-AR tek calisma karti veri modeli')
    log(f'DB: {db_path}')
    log('=' * 70)

    # ── 1) nexgen_arge_test kolonları ─────────────────────────────
    if not _tablo_var(cur, 'nexgen_arge_test'):
        log('[106] HATA: nexgen_arge_test yok — migration durdu')
        con.close()
        return stats

    if _kolon_var(cur, 'nexgen_arge_test', 'onay_notu'):
        log('[106] SKIP onay_notu (zaten var)')
        stats['skip'] += 1

    for kolon, tip in TEST_KOLONLAR:
        if _kolon_var(cur, 'nexgen_arge_test', kolon):
            log(f'[106] SKIP nexgen_arge_test.{kolon}')
            stats['skip'] += 1
        else:
            cur.execute(f'ALTER TABLE nexgen_arge_test ADD COLUMN {kolon} {tip}')
            con.commit()
            stats['kolon_eklendi'] += 1
            log(f'[106] OK   nexgen_arge_test.{kolon}')

    for idx_name, idx_sql in [
        ('idx_arge_test_calisma_tipi',
         'CREATE INDEX IF NOT EXISTS idx_arge_test_calisma_tipi ON nexgen_arge_test(calisma_tipi)'),
        ('idx_arge_test_oncelik',
         'CREATE INDEX IF NOT EXISTS idx_arge_test_oncelik ON nexgen_arge_test(oncelik)'),
        ('idx_arge_test_saha_gerekli',
         'CREATE INDEX IF NOT EXISTS idx_arge_test_saha_gerekli ON nexgen_arge_test(saha_testi_gerekli_mi)'),
        ('idx_arge_test_renk_kodu',
         'CREATE INDEX IF NOT EXISTS idx_arge_test_renk_kodu ON nexgen_arge_test(renk_kodu)'),
    ]:
        if _index_var(cur, idx_name):
            stats['skip'] += 1
        else:
            cur.execute(idx_sql)
            con.commit()
            stats['index_olusturuldu'] += 1
            log(f'[106] OK   index {idx_name}')

    # ── 2) nexgen_arge_kaynak_uv ──────────────────────────────────
    if _tablo_var(cur, 'nexgen_arge_kaynak_uv'):
        log('[106] SKIP nexgen_arge_kaynak_uv (tablo var)')
        stats['skip'] += 1
    else:
        cur.execute("""
            CREATE TABLE nexgen_arge_kaynak_uv (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                arge_test_id INTEGER NOT NULL,
                boyut TEXT NOT NULL CHECK (boyut IN ('LARGE','SMALL','MEDIUM')),
                kaynak_uretim_varyant_id INTEGER NOT NULL,
                sira_no INTEGER NOT NULL DEFAULT 1,
                aktif_mi INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                UNIQUE (arge_test_id, boyut),
                UNIQUE (arge_test_id, kaynak_uretim_varyant_id)
            )
        """)
        cur.execute(
            'CREATE INDEX IF NOT EXISTS idx_arge_kaynak_uv_test '
            'ON nexgen_arge_kaynak_uv(arge_test_id)'
        )
        con.commit()
        stats['tablo_olusturuldu'] += 1
        stats['index_olusturuldu'] += 1
        log('[106] OK   nexgen_arge_kaynak_uv')

    # ── 3) nexgen_arge_deneme ─────────────────────────────────────
    if _tablo_var(cur, 'nexgen_arge_deneme'):
        log('[106] SKIP nexgen_arge_deneme (tablo var)')
        stats['skip'] += 1
    else:
        cur.execute("""
            CREATE TABLE nexgen_arge_deneme (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                arge_test_id INTEGER NOT NULL,
                deneme_no INTEGER NOT NULL,
                durum TEXT NOT NULL DEFAULT 'HAZIR',
                aktif_mi INTEGER NOT NULL DEFAULT 1,
                deneme_tarihi TEXT,
                hazirlayan_kullanici_id INTEGER,
                numune_orani REAL,
                lot_no TEXT,
                genel_not TEXT,
                genel_sonuc TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at TEXT,
                UNIQUE (arge_test_id, deneme_no)
            )
        """)
        con.commit()
        stats['tablo_olusturuldu'] += 1
        log('[106] OK   nexgen_arge_deneme')

    if not _index_var(cur, 'uq_arge_deneme_tek_aktif'):
        cur.execute("""
            CREATE UNIQUE INDEX uq_arge_deneme_tek_aktif
            ON nexgen_arge_deneme(arge_test_id)
            WHERE aktif_mi = 1
        """)
        con.commit()
        stats['index_olusturuldu'] += 1
        log('[106] OK   uq_arge_deneme_tek_aktif')
    else:
        stats['skip'] += 1

    # ── 4) nexgen_arge_deneme_kalem ───────────────────────────────
    if _tablo_var(cur, 'nexgen_arge_deneme_kalem'):
        log('[106] SKIP nexgen_arge_deneme_kalem (tablo var)')
        stats['skip'] += 1
    else:
        cur.execute("""
            CREATE TABLE nexgen_arge_deneme_kalem (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deneme_id INTEGER NOT NULL,
                boyut TEXT NOT NULL CHECK (boyut IN ('LARGE','SMALL','MEDIUM')),
                kaynak_uv_id INTEGER,
                stok_kart_id INTEGER NOT NULL,
                sira INTEGER NOT NULL DEFAULT 1,
                orjinal_miktar_kg REAL,
                test_miktar_kg REAL,
                aciklama TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                UNIQUE (deneme_id, boyut, stok_kart_id, sira)
            )
        """)
        cur.execute(
            'CREATE INDEX IF NOT EXISTS idx_arge_deneme_kalem_deneme '
            'ON nexgen_arge_deneme_kalem(deneme_id)'
        )
        con.commit()
        stats['tablo_olusturuldu'] += 1
        stats['index_olusturuldu'] += 1
        log('[106] OK   nexgen_arge_deneme_kalem')

    # ── 5) nexgen_arge_boyut_sonuc ────────────────────────────────
    if _tablo_var(cur, 'nexgen_arge_boyut_sonuc'):
        log('[106] SKIP nexgen_arge_boyut_sonuc (tablo var)')
        stats['skip'] += 1
    else:
        cur.execute("""
            CREATE TABLE nexgen_arge_boyut_sonuc (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deneme_id INTEGER NOT NULL,
                arge_test_id INTEGER NOT NULL,
                boyut TEXT NOT NULL CHECK (boyut IN ('LARGE','SMALL','MEDIUM')),
                shore_sonuc REAL,
                pisme_suresi_dk REAL,
                yogunluk REAL,
                renk_sonucu TEXT,
                kalip_sonucu TEXT,
                basarili_mi INTEGER,
                saha_notu TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at TEXT,
                UNIQUE (deneme_id, boyut)
            )
        """)
        cur.execute(
            'CREATE INDEX IF NOT EXISTS idx_arge_boyut_sonuc_deneme '
            'ON nexgen_arge_boyut_sonuc(deneme_id)'
        )
        con.commit()
        stats['tablo_olusturuldu'] += 1
        stats['index_olusturuldu'] += 1
        log('[106] OK   nexgen_arge_boyut_sonuc')

    # ── 6) nexgen_arge_olusan_uv ──────────────────────────────────
    if _tablo_var(cur, 'nexgen_arge_olusan_uv'):
        log('[106] SKIP nexgen_arge_olusan_uv (tablo var)')
        stats['skip'] += 1
    else:
        cur.execute("""
            CREATE TABLE nexgen_arge_olusan_uv (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                arge_test_id INTEGER NOT NULL,
                boyut TEXT NOT NULL CHECK (boyut IN ('LARGE','SMALL','MEDIUM')),
                olusan_uv_id INTEGER,
                olusan_rv_id INTEGER,
                formul_id INTEGER,
                uygunluk_id INTEGER,
                uretim_kodu TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                UNIQUE (arge_test_id, boyut)
            )
        """)
        cur.execute(
            'CREATE INDEX IF NOT EXISTS idx_arge_olusan_uv_test '
            'ON nexgen_arge_olusan_uv(arge_test_id)'
        )
        con.commit()
        stats['tablo_olusturuldu'] += 1
        stats['index_olusturuldu'] += 1
        log('[106] OK   nexgen_arge_olusan_uv')

    # ── 7) nexgen_arge_revizyon genişletme ────────────────────────
    if _tablo_var(cur, 'nexgen_arge_revizyon'):
        for istenen, mevcut in REVIZYON_ESDEGER.items():
            if _kolon_var(cur, 'nexgen_arge_revizyon', mevcut):
                log(f'[106] SKIP revizyon.{istenen} — mevcut esdeger: {mevcut}')
                stats['skip'] += 1
            elif _kolon_var(cur, 'nexgen_arge_revizyon', istenen):
                log(f'[106] SKIP revizyon.{istenen} (zaten var)')
                stats['skip'] += 1
            else:
                # eşdeğer yoksa istenen adı ekle
                tip = 'INTEGER' if 'id' in istenen or istenen.endswith('_no') else 'TEXT'
                cur.execute(
                    f'ALTER TABLE nexgen_arge_revizyon ADD COLUMN {istenen} {tip}'
                )
                con.commit()
                stats['revizyon_kolon'] += 1
                log(f'[106] OK   revizyon.{istenen}')

        if _kolon_var(cur, 'nexgen_arge_revizyon', 'deneme_id'):
            log('[106] SKIP revizyon.deneme_id')
            stats['skip'] += 1
        else:
            cur.execute('ALTER TABLE nexgen_arge_revizyon ADD COLUMN deneme_id INTEGER')
            con.commit()
            stats['revizyon_kolon'] += 1
            log('[106] OK   revizyon.deneme_id')

        if not _index_var(cur, 'idx_arge_rev_deneme_id'):
            cur.execute(
                'CREATE INDEX IF NOT EXISTS idx_arge_rev_deneme_id '
                'ON nexgen_arge_revizyon(deneme_id)'
            )
            con.commit()
            stats['index_olusturuldu'] += 1
            log('[106] OK   idx_arge_rev_deneme_id')
        else:
            stats['skip'] += 1
    else:
        log('[106] WARN nexgen_arge_revizyon yok — deneme_id atlandi')

    # ── 8) schema_migrations ──────────────────────────────────────
    try:
        if _tablo_var(cur, 'schema_migrations'):
            cols = [c[1] for c in cur.execute('PRAGMA table_info(schema_migrations)').fetchall()]
            if 'aciklama' in cols:
                cur.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, aciklama) "
                    "VALUES(?, ?)",
                    (VERSION, 'NX-AR tek calisma karti veri modeli'),
                )
            else:
                cur.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)",
                    (VERSION,),
                )
            con.commit()
            log('[106] OK   schema_migrations version=106')
    except Exception as e:
        log(f'[106] WARN schema_migrations: {e}')

    yeni = (
        stats['kolon_eklendi']
        + stats['tablo_olusturuldu']
        + stats['index_olusturuldu']
        + stats['revizyon_kolon']
    )
    log(
        f'[106] OZET kolon={stats["kolon_eklendi"]} tablo={stats["tablo_olusturuldu"]} '
        f'index={stats["index_olusturuldu"]} rev_kolon={stats["revizyon_kolon"]} '
        f'skip={stats["skip"]} yeni_degisiklik={yeni}'
    )
    log('Migration 106 tamamlandi')
    stats['ok'] = True
    stats['yeni_degisiklik'] = yeni
    con.close()
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=None, help='SQLite DB yolu')
    ap.add_argument(
        '--internal-backup',
        action='store_true',
        help='DB yanina otomatik kopya al (dis backup tercih edilir)',
    )
    args = ap.parse_args()
    st = run(db_path=args.db, take_internal_backup=args.internal_backup)
    sys.exit(0 if st.get('ok') else 1)


if __name__ == '__main__':
    main()
