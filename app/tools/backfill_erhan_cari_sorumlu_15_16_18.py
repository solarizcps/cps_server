# -*- coding: utf-8 -*-
"""
Erhan (uid=49) ANA sorumlu backfill — cari_id 15, 16, 18.

Server RDP:
  python app/tools/backfill_erhan_cari_sorumlu_15_16_18.py --db C:\\Solariz_CPS_SERVER\\app\\mock_data.db --check
  python app/tools/backfill_erhan_cari_sorumlu_15_16_18.py --db C:\\Solariz_CPS_SERVER\\app\\mock_data.db --apply
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'
sys.path.insert(0, str(APP))

ALLOWLIST_CARI_IDS = (15, 16, 18)
TARGET_KULLANICI_ID = 49
TARGET_ROL = 'ANA'

_AKTIF_WHERE = (
    "aktif=1 AND (bitis_tarihi IS NULL OR bitis_tarihi='' "
    "OR bitis_tarihi > datetime('now','localtime'))"
)


def _connect(db: str) -> sqlite3.Connection:
    con = sqlite3.connect(db, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _erhan_visible_count(con: sqlite3.Connection) -> int:
    rows = con.execute(
        f"""
        SELECT COUNT(DISTINCT cs.cari_id)
        FROM cari_sorumlu cs
        JOIN nexgen_cari c ON c.id = cs.cari_id AND c.aktif = 1
        WHERE cs.kullanici_id = ? AND cs.sorumluluk_rolu = 'ANA'
          AND cs.aktif = 1
          AND (cs.bitis_tarihi IS NULL OR cs.bitis_tarihi = ''
               OR cs.bitis_tarihi > datetime('now', 'localtime'))
        """,
        (TARGET_KULLANICI_ID,),
    ).fetchone()
    return int(rows[0] or 0)


def _target_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    ph = ','.join(['?'] * len(ALLOWLIST_CARI_IDS))
    return con.execute(
        f"""
        SELECT c.id, c.cari_kod, c.unvan, c.aktif,
               cs.id AS atama_id, cs.kullanici_id AS mevcut_uid, cs.sorumluluk_rolu
        FROM nexgen_cari c
        LEFT JOIN cari_sorumlu cs ON cs.cari_id = c.id
            AND cs.sorumluluk_rolu = 'ANA'
            AND cs.aktif = 1
            AND (cs.bitis_tarihi IS NULL OR cs.bitis_tarihi = ''
                 OR cs.bitis_tarihi > datetime('now', 'localtime'))
        WHERE c.id IN ({ph})
        ORDER BY c.id
        """,
        ALLOWLIST_CARI_IDS,
    ).fetchall()


def run_check(db: str) -> int:
    con = _connect(db)
    try:
        print('DB:', os.path.abspath(db))
        print('SHA256:', _sha256(db))
        print('Erhan visible (aktif ANA):', _erhan_visible_count(con))
        needs = 0
        blocked = 0
        for r in _target_rows(con):
            cid = int(r['id'])
            if not int(r['aktif'] or 0):
                print(f'  cari {cid} PASIF — atlanır')
                continue
            mevcut = r['mevcut_uid']
            if mevcut is None:
                print(f'  NEED  id={cid} {r["cari_kod"]} {r["unvan"]}')
                needs += 1
            elif int(mevcut) == TARGET_KULLANICI_ID:
                print(f'  OK    id={cid} Erhan ANA mevcut (atama_id={r["atama_id"]})')
            else:
                print(
                    f'  BLOCK id={cid} farkli ANA uid={mevcut} — manuel inceleme gerekir'
                )
                blocked += 1
        ku = con.execute(
            'SELECT Id, KullaniciAdi FROM sistem_kullanici WHERE Id=? AND Aktif=1',
            (TARGET_KULLANICI_ID,),
        ).fetchone()
        print('Erhan kullanici:', dict(ku) if ku else 'BULUNAMADI')
        print('needs_apply:', needs, 'blocked:', blocked)
        return 1 if blocked else 0
    finally:
        con.close()


def run_apply(db: str) -> int:
    from modules.nexgen.cari_sorumlu_service import ensure_ana_sorumlu_atama

    con = _connect(db)
    try:
        pre = _erhan_visible_count(con)
        print('PRE Erhan visible:', pre)
        applied = 0
        noop = 0
        con.execute('BEGIN IMMEDIATE')
        for r in _target_rows(con):
            cid = int(r['id'])
            if not int(r['aktif'] or 0):
                continue
            mevcut = r['mevcut_uid']
            if mevcut is not None and int(mevcut) != TARGET_KULLANICI_ID:
                con.rollback()
                print(f'ABORT: cari {cid} farkli ANA uid={mevcut}')
                return 2
            if mevcut is not None and int(mevcut) == TARGET_KULLANICI_ID:
                noop += 1
                continue
            res = ensure_ana_sorumlu_atama(
                con, cid, TARGET_KULLANICI_ID,
                atayan_kullanici_id=None,
                atama_notu='Backfill Erhan ANA — CARI-MO-RESPONSIBILITY-FIX-01',
            )
            if not res.get('ok'):
                con.rollback()
                print(f'ABORT cari {cid}:', res.get('hata'))
                return 3
            applied += 1
        post = _erhan_visible_count(con)
        ic = con.execute('PRAGMA integrity_check').fetchone()[0]
        if ic != 'ok':
            con.rollback()
            print('ABORT integrity_check:', ic)
            return 4
        con.commit()
        print('POST Erhan visible:', post)
        print('applied:', applied, 'noop:', noop, 'integrity:', ic)
        if post != pre + applied:
            print('WARN: post count beklenenden farkli')
            return 5
        return 0
    except Exception as e:
        con.rollback()
        print('ABORT exception:', e)
        return 6
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description='Erhan ANA backfill cari 15,16,18')
    ap.add_argument('--db', required=True, help='Absolute path to mock_data.db')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--check', action='store_true')
    g.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    db = os.path.abspath(args.db)
    if not os.path.isfile(db):
        print('DB bulunamadi:', db)
        return 10
    if args.check:
        return run_check(db)
    return run_apply(db)


if __name__ == '__main__':
    raise SystemExit(main())
