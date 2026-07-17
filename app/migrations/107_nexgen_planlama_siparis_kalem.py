# -*- coding: utf-8 -*-
"""
Migration 107 — Pazarlama Merkezi BE-1: Çok kalemli sipariş kalem tablosu
============================================================================
[1] nexgen_planlama_siparis_kalem tablosu
[2] Indexler
[3] Legacy backfill: talep_referansi JSON → 1 kalem satırı (header JSON korunur)
[4] schema_migrations version=107

NOT: MRP / batch / plan mantığı değişmez. İdempotent.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime

VERSION = '107'
PZM_JSON_PREFIX = '__PZM_V1__'
DEFAULT_DB = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

KALEM_DDL = """
CREATE TABLE IF NOT EXISTS nexgen_planlama_siparis_kalem (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    planlama_siparis_id     INTEGER NOT NULL
                            REFERENCES nexgen_planlama_siparis(id),
    sira_no                 INTEGER NOT NULL DEFAULT 1,
    urun_ailesi             TEXT NOT NULL,
    formul_id               INTEGER,
    formul_ad               TEXT,
    renk_varyant_id         INTEGER,
    renk_ad                 TEXT,
    rf_renk_id              INTEGER,
    miktar_l                REAL NOT NULL DEFAULT 0,
    miktar_s                REAL NOT NULL DEFAULT 0,
    miktar_m                REAL NOT NULL DEFAULT 0,
    termin_tarihi           TEXT,
    notlar                  TEXT,
    uretim_plan_id          INTEGER REFERENCES nexgen_uretim_plan(id),
    durum                   TEXT NOT NULL DEFAULT 'AKTIF',
    legacy_kaynak           INTEGER NOT NULL DEFAULT 0,
    olusturma_tarihi        TEXT DEFAULT (datetime('now','localtime')),
    guncelleme_tarihi       TEXT,
    UNIQUE (planlama_siparis_id, sira_no)
)
"""

KALEM_INDEXES = [
    ('idx_npsk_siparis', 'nexgen_planlama_siparis_kalem(planlama_siparis_id)'),
    ('idx_npsk_formul', 'nexgen_planlama_siparis_kalem(formul_id)'),
    ('idx_npsk_renk', 'nexgen_planlama_siparis_kalem(renk_varyant_id)'),
    ('idx_npsk_plan', 'nexgen_planlama_siparis_kalem(uretim_plan_id)'),
    ('idx_npsk_durum', 'nexgen_planlama_siparis_kalem(durum)'),
]


def _tablo_var(cur, tablo: str) -> bool:
    return bool(cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (tablo,),
    ).fetchone())


def _index_var(cur, name: str) -> bool:
    return bool(cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (name,),
    ).fetchone())


def _payload_unpack(ref):
    if not ref or not str(ref).startswith(PZM_JSON_PREFIX):
        return None
    try:
        return json.loads(str(ref)[len(PZM_JSON_PREFIX):])
    except Exception:
        return None


def _boyut_to_miktar(boyut_miktar: dict) -> tuple[float, float, float]:
    ml = ms = mm = 0.0
    if not isinstance(boyut_miktar, dict):
        return ml, ms, mm
    for b, v in boyut_miktar.items():
        key = (b or '').upper()
        if key == 'MEDIUM':
            key = 'STANDART'
        try:
            kg = round(float(v), 3)
        except (TypeError, ValueError):
            continue
        if kg <= 0:
            continue
        if key == 'LARGE':
            ml = kg
        elif key == 'SMALL':
            ms = kg
        elif key == 'STANDART':
            mm = kg
    return ml, ms, mm


def _sayim(cur, sql: str) -> int:
    row = cur.execute(sql).fetchone()
    return int(row[0] if row else 0)


def _integrity_check(cur, log) -> bool:
    ok = True
    if not _tablo_var(cur, 'nexgen_planlama_siparis_kalem'):
        log('[107] INTEGRITY FAIL: kalem tablosu yok')
        return False

    orphan = _sayim(cur, """
        SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem k
        LEFT JOIN nexgen_planlama_siparis h ON h.id = k.planlama_siparis_id
        WHERE h.id IS NULL
    """)
    if orphan:
        log(f'[107] INTEGRITY FAIL: yetim kalem={orphan}')
        ok = False

    bad_plan = _sayim(cur, """
        SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem k
        WHERE k.uretim_plan_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM nexgen_uretim_plan p WHERE p.id = k.uretim_plan_id
          )
    """)
    if bad_plan:
        log(f'[107] INTEGRITY FAIL: gecersiz uretim_plan_id={bad_plan}')
        ok = False

    dup_sira = _sayim(cur, """
        SELECT COUNT(*) FROM (
            SELECT planlama_siparis_id, sira_no, COUNT(*) c
            FROM nexgen_planlama_siparis_kalem
            GROUP BY planlama_siparis_id, sira_no
            HAVING c > 1
        )
    """)
    if dup_sira:
        log(f'[107] INTEGRITY FAIL: cift sira_no={dup_sira}')
        ok = False

    if ok:
        log('[107] INTEGRITY OK')
    return ok


def run(db_path: str | None = None, take_internal_backup: bool = False) -> dict:
    db_path = os.path.abspath(db_path or DEFAULT_DB)
    stats = {
        'db': db_path,
        'tablo_olusturuldu': 0,
        'index_olusturuldu': 0,
        'kalem_backfill': 0,
        'skip': 0,
        'ok': False,
        'log': [],
        'before': {},
        'after': {},
    }

    def log(msg):
        stats['log'].append(msg)
        print(msg)

    if not os.path.exists(db_path):
        log(f'[107] HATA: DB bulunamadi: {db_path}')
        return stats

    if not _tablo_var(sqlite3.connect(db_path).cursor(), 'nexgen_planlama_siparis'):
        log('[107] HATA: nexgen_planlama_siparis yok — migration durdu')
        return stats

    if take_internal_backup:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        bak = db_path.replace('.db', f'_backup_pre107_{ts}.db')
        try:
            shutil.copy2(db_path, bak)
            log(f'[107] YEDEK(internal): {bak}')
            stats['backup_path'] = bak
        except Exception as e:
            log(f'[107] UYARI internal yedek: {e}')

    con = sqlite3.connect(db_path)
    cur = con.cursor()

    log('=' * 70)
    log('Migration 107 - nexgen_planlama_siparis_kalem')
    log(f'DB: {db_path}')
    log('=' * 70)

    stats['before'] = {
        'plan': _sayim(cur, 'SELECT COUNT(*) FROM nexgen_uretim_plan'),
        'batch': _sayim(cur, 'SELECT COUNT(*) FROM nexgen_uretim_batch'),
        'rf': _sayim(cur, 'SELECT COUNT(*) FROM nexgen_rf_renk'),
        'pzm_header': _sayim(cur, f"""
            SELECT COUNT(*) FROM nexgen_planlama_siparis
            WHERE talep_referansi LIKE '{PZM_JSON_PREFIX}%'
        """),
        'kalem': _sayim(cur, """
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name='nexgen_planlama_siparis_kalem'
        """) and _sayim(cur, 'SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem') or 0,
    }
    log(
        f'[107] ONCE plan={stats["before"]["plan"]} batch={stats["before"]["batch"]} '
        f'rf={stats["before"]["rf"]} pzm_header={stats["before"]["pzm_header"]} '
        f'kalem={stats["before"]["kalem"]}'
    )

    # ── 1) Tablo ─────────────────────────────────────────────────
    if _tablo_var(cur, 'nexgen_planlama_siparis_kalem'):
        log('[107] SKIP tablo (zaten var)')
        stats['skip'] += 1
    else:
        cur.execute(KALEM_DDL)
        con.commit()
        stats['tablo_olusturuldu'] += 1
        log('[107] OK   nexgen_planlama_siparis_kalem')

    # ── 2) Indexler ──────────────────────────────────────────────
    for idx_name, idx_cols in KALEM_INDEXES:
        if _index_var(cur, idx_name):
            stats['skip'] += 1
        else:
            cur.execute(f'CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_cols}')
            con.commit()
            stats['index_olusturuldu'] += 1
            log(f'[107] OK   index {idx_name}')

    # ── 3) Legacy backfill ───────────────────────────────────────
    headers = cur.execute(f"""
        SELECT id, termin_tarihi, notlar, talep_referansi, durum
        FROM nexgen_planlama_siparis
        WHERE talep_referansi LIKE ?
        ORDER BY id
    """, (PZM_JSON_PREFIX + '%',)).fetchall()

    for hdr in headers:
        ps_id = hdr[0]
        mevcut = cur.execute(
            'SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem WHERE planlama_siparis_id=?',
            (ps_id,),
        ).fetchone()[0]
        if mevcut:
            stats['skip'] += 1
            continue

        payload = _payload_unpack(hdr[3])
        if not payload:
            log(f'[107] WARN header={ps_id} payload parse edilemedi — atlandi')
            continue

        ml, ms, mm = _boyut_to_miktar(payload.get('boyut_miktar') or {})
        plan_row = cur.execute(
            'SELECT id FROM nexgen_uretim_plan WHERE planlama_siparis_id=? ORDER BY id LIMIT 1',
            (ps_id,),
        ).fetchone()
        plan_id = plan_row[0] if plan_row else None

        cur.execute("""
            INSERT INTO nexgen_planlama_siparis_kalem
                (planlama_siparis_id, sira_no, urun_ailesi, formul_id, formul_ad,
                 renk_varyant_id, renk_ad, rf_renk_id,
                 miktar_l, miktar_s, miktar_m,
                 termin_tarihi, notlar, uretim_plan_id, durum, legacy_kaynak)
            VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            ps_id,
            (payload.get('urun_ailesi') or '').strip().upper() or 'TERLIK',
            payload.get('formul_id'),
            payload.get('formul_ad'),
            payload.get('renk_varyant_id'),
            payload.get('renk_ad'),
            payload.get('rf_renk_id'),
            ml, ms, mm,
            payload.get('termin_tarihi') or hdr[1],
            payload.get('notlar') or hdr[2],
            plan_id,
            'AKTIF',
        ))
        stats['kalem_backfill'] += 1

    if stats['kalem_backfill']:
        con.commit()
        log(f'[107] OK   legacy backfill kalem={stats["kalem_backfill"]}')

    # ── 4) schema_migrations ─────────────────────────────────────
    try:
        if _tablo_var(cur, 'schema_migrations'):
            cols = [c[1] for c in cur.execute('PRAGMA table_info(schema_migrations)').fetchall()]
            if 'aciklama' in cols:
                cur.execute(
                    'INSERT OR IGNORE INTO schema_migrations(version, aciklama) VALUES(?, ?)',
                    (VERSION, 'Pazarlama cok kalemli siparis kalem tablosu'),
                )
            else:
                cur.execute(
                    'INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)',
                    (VERSION,),
                )
            con.commit()
            log('[107] OK   schema_migrations version=107')
    except Exception as e:
        log(f'[107] WARN schema_migrations: {e}')

    stats['after'] = {
        'plan': _sayim(cur, 'SELECT COUNT(*) FROM nexgen_uretim_plan'),
        'batch': _sayim(cur, 'SELECT COUNT(*) FROM nexgen_uretim_batch'),
        'rf': _sayim(cur, 'SELECT COUNT(*) FROM nexgen_rf_renk'),
        'kalem': _sayim(cur, 'SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem'),
    }
    log(
        f'[107] SONRA plan={stats["after"]["plan"]} batch={stats["after"]["batch"]} '
        f'rf={stats["after"]["rf"]} kalem={stats["after"]["kalem"]}'
    )

    unchanged = (
        stats['before']['plan'] == stats['after']['plan']
        and stats['before']['batch'] == stats['after']['batch']
        and stats['before']['rf'] == stats['after']['rf']
    )
    if unchanged:
        log('[107] CHECK plan/batch/rf degismedi')
    else:
        log('[107] UYARI plan/batch/rf sayisi degisti!')

    stats['integrity_ok'] = _integrity_check(cur, log)

    yeni = stats['tablo_olusturuldu'] + stats['index_olusturuldu'] + stats['kalem_backfill']
    log(
        f'[107] OZET tablo={stats["tablo_olusturuldu"]} index={stats["index_olusturuldu"]} '
        f'backfill={stats["kalem_backfill"]} skip={stats["skip"]} yeni_degisiklik={yeni}'
    )
    log('Migration 107 tamamlandi')
    stats['ok'] = unchanged and stats['integrity_ok']
    stats['yeni_degisiklik'] = yeni
    con.close()
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=None, help='SQLite DB yolu')
    ap.add_argument(
        '--internal-backup',
        action='store_true',
        help='DB yanina otomatik kopya al',
    )
    args = ap.parse_args()
    st = run(db_path=args.db, take_internal_backup=args.internal_backup)
    sys.exit(0 if st.get('ok') else 1)


if __name__ == '__main__':
    main()
