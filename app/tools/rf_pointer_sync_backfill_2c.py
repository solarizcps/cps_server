# -*- coding: utf-8 -*-
"""
FAZ-2C — HIGH RF pointer sync backfill (schema migration DEĞİL).

Kurallar:
  H1: arge.rf dolu, numune.rf boş → numune.rf_renk_id = arge.rf_renk_id
  H2: arge.rf=rf.id, rf.kaynak boş → rf.kaynak_arge_test_id = arge.id
  H3: rf.kaynak=arge.id, arge.rf boş → arge.rf_renk_id = rf.id (+ H1 sync)

Güvenlik:
  - explicit --db zorunlu
  - varsayılan --dry-run
  - --apply + --confirm HIGH_RF_SYNC
  - mock_data.db apply için --allow-live
  - BEGIN IMMEDIATE + audit + rollback helper
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
from datetime import datetime
from typing import Any

CONFIRM_TOKEN = 'HIGH_RF_SYNC'
ARGE_OK_DURUM = frozenset({'ONAYLANDI'})
RF_OK_DURUM = frozenset({'ONAYLI', 'ONAYLANDI', 'AKTIF', ''})


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _cols(con: sqlite3.Connection, table: str) -> set[str]:
    return {c[1] for c in con.execute(f'PRAGMA table_info({table})').fetchall()}


def _iint(v: Any) -> int | None:
    if v in (None, '', 0, '0'):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def preflight(con: sqlite3.Connection) -> dict[str, Any]:
    need_tables = (
        'nexgen_numune_talep', 'nexgen_arge_test', 'nexgen_rf_renk',
    )
    for t in need_tables:
        if not con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,),
        ).fetchone():
            raise RuntimeError(f'PREFLIGHT: tablo yok: {t}')
    nt = _cols(con, 'nexgen_numune_talep')
    ar = _cols(con, 'nexgen_arge_test')
    rf = _cols(con, 'nexgen_rf_renk')
    for col, tbl, cset in (
        ('rf_renk_id', 'nexgen_numune_talep', nt),
        ('rf_renk_id', 'nexgen_arge_test', ar),
        ('kaynak_arge_test_id', 'nexgen_rf_renk', rf),
    ):
        if col not in cset:
            raise RuntimeError(f'PREFLIGHT: {tbl}.{col} yok')
    return {
        'ok': True,
        'mig141_numune_talep_id': 'numune_talep_id' in ar,
        'schema_max': con.execute(
            'SELECT MAX(version) FROM schema_migrations'
        ).fetchone()[0] if con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone() else None,
    }


def baseline_counts(con: sqlite3.Connection) -> dict[str, Any]:
    def q(sql: str, *a):
        return con.execute(sql, a).fetchone()[0]

    out: dict[str, Any] = {
        'numune_aktif': q('SELECT COUNT(*) FROM nexgen_numune_talep WHERE aktif=1'),
        'arge_aktif': q('SELECT COUNT(*) FROM nexgen_arge_test WHERE aktif=1'),
        'rf_aktif': q('SELECT COUNT(*) FROM nexgen_rf_renk WHERE aktif=1'),
        'numune_rf_dolu': q(
            'SELECT COUNT(*) FROM nexgen_numune_talep WHERE aktif=1 '
            'AND rf_renk_id IS NOT NULL AND rf_renk_id!=0'
        ),
        'numune_rf_bos': q(
            'SELECT COUNT(*) FROM nexgen_numune_talep WHERE aktif=1 '
            'AND (rf_renk_id IS NULL OR rf_renk_id=0)'
        ),
        'arge_rf_dolu': q(
            'SELECT COUNT(*) FROM nexgen_arge_test WHERE aktif=1 '
            'AND rf_renk_id IS NOT NULL AND rf_renk_id!=0'
        ),
        'arge_rf_bos': q(
            'SELECT COUNT(*) FROM nexgen_arge_test WHERE aktif=1 '
            'AND (rf_renk_id IS NULL OR rf_renk_id=0)'
        ),
        'rf_kaynak_dolu': q(
            'SELECT COUNT(*) FROM nexgen_rf_renk WHERE aktif=1 '
            'AND kaynak_arge_test_id IS NOT NULL AND kaynak_arge_test_id!=0'
        ),
        'rf_kaynak_bos': q(
            'SELECT COUNT(*) FROM nexgen_rf_renk WHERE aktif=1 '
            'AND (kaynak_arge_test_id IS NULL OR kaynak_arge_test_id=0)'
        ),
        'mismatch': q(
            """
            SELECT COUNT(*) FROM nexgen_numune_talep nt
            JOIN nexgen_arge_test a ON a.id = nt.arge_test_id
            WHERE nt.aktif=1 AND a.aktif=1
              AND nt.rf_renk_id IS NOT NULL AND nt.rf_renk_id!=0
              AND a.rf_renk_id IS NOT NULL AND a.rf_renk_id!=0
              AND nt.rf_renk_id != a.rf_renk_id
            """
        ),
        'dup_kaynak_arge': q(
            """
            SELECT COUNT(*) FROM (
              SELECT kaynak_arge_test_id FROM nexgen_rf_renk
              WHERE aktif=1 AND kaynak_arge_test_id IS NOT NULL
              GROUP BY kaynak_arge_test_id HAVING COUNT(*)>1
            )
            """
        ),
        'orphan_arge_rf': q(
            """
            SELECT COUNT(*) FROM nexgen_arge_test a
            WHERE a.rf_renk_id IS NOT NULL AND a.rf_renk_id!=0
              AND NOT EXISTS (SELECT 1 FROM nexgen_rf_renk rf WHERE rf.id=a.rf_renk_id)
            """
        ),
        'orphan_numune_rf': q(
            """
            SELECT COUNT(*) FROM nexgen_numune_talep nt
            WHERE nt.rf_renk_id IS NOT NULL AND nt.rf_renk_id!=0
              AND NOT EXISTS (SELECT 1 FROM nexgen_rf_renk rf WHERE rf.id=nt.rf_renk_id)
            """
        ),
    }
    if con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexgen_planlama_siparis_kalem'"
    ).fetchone():
        out['siparis_kalem_rf'] = q(
            'SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem '
            'WHERE rf_renk_id IS NOT NULL AND rf_renk_id!=0'
        )
    if con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexgen_uretim_plan'"
    ).fetchone():
        out['plan_rf'] = q(
            'SELECT COUNT(*) FROM nexgen_uretim_plan '
            'WHERE rf_renk_id IS NOT NULL AND rf_renk_id!=0'
        )
    if con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexgen_uretim_batch'"
    ).fetchone():
        out['batch_rf'] = q(
            'SELECT COUNT(*) FROM nexgen_uretim_batch '
            'WHERE rf_renk_id IS NOT NULL AND rf_renk_id!=0'
        )
    out['arge_rf_by_durum'] = [
        dict(r) for r in con.execute(
            """
            SELECT IFNULL(durum,'') AS durum, COUNT(*) n
            FROM nexgen_arge_test
            WHERE aktif=1 AND rf_renk_id IS NOT NULL AND rf_renk_id!=0
            GROUP BY IFNULL(durum,'')
            """
        )
    ]
    if 'numune_talep_id' in _cols(con, 'nexgen_arge_test'):
        out['faz1_arge_ntp_dolu'] = q(
            'SELECT COUNT(*) FROM nexgen_arge_test '
            'WHERE numune_talep_id IS NOT NULL AND numune_talep_id!=0'
        )
    return out


def _rf_ok(rf: sqlite3.Row) -> tuple[bool, str]:
    if not int(rf['aktif'] or 0):
        return False, 'pasif_rf'
    d = (rf['durum'] or '').strip().upper()
    if d and d not in RF_OK_DURUM and d in ('IPTAL', 'İPTAL', 'REDDEDILDI', 'PASIF', 'TASLAK'):
        return False, f'rf_durum_{d}'
    return True, ''


def _cari_strict(a: Any, b: Any) -> tuple[bool, str]:
    """İkisi de dolu ve eşit olmalı; NULL → dışla."""
    ai, bi = _iint(a), _iint(b)
    if ai is None or bi is None:
        return False, 'cari_null'
    if ai != bi:
        return False, 'cari_mismatch'
    return True, ''


def _rf_cari_ok(rf_cari: Any, arge_cari: Any) -> tuple[bool, str]:
    rc, ac = _iint(rf_cari), _iint(arge_cari)
    if rc is None:
        return True, ''  # global RF
    if ac is None:
        return False, 'cari_null'
    if rc != ac:
        return False, 'rf_cari_mismatch'
    return True, ''


def find_numune_for_arge(con: sqlite3.Connection, arge_id: int) -> sqlite3.Row | None:
    ar_cols = _cols(con, 'nexgen_arge_test')
    if 'numune_talep_id' in ar_cols:
        r = con.execute(
            'SELECT numune_talep_id FROM nexgen_arge_test WHERE id=?', (arge_id,),
        ).fetchone()
        nid = _iint(r['numune_talep_id'] if r else None)
        if nid is not None:
            nt = con.execute(
                """
                SELECT id, rf_renk_id, cari_id, durum, aktif, arge_test_id, talep_kodu
                FROM nexgen_numune_talep WHERE id=?
                """,
                (nid,),
            ).fetchone()
            if nt and int(nt['aktif'] or 0):
                return nt
    rows = con.execute(
        """
        SELECT id, rf_renk_id, cari_id, durum, aktif, arge_test_id, talep_kodu
        FROM nexgen_numune_talep
        WHERE aktif=1 AND arge_test_id=?
        ORDER BY id
        """,
        (arge_id,),
    ).fetchall()
    if len(rows) == 1:
        return rows[0]
    return None


def select_h1(con: sqlite3.Connection) -> tuple[list[dict], list[dict]]:
    eligible: list[dict] = []
    excluded: list[dict] = []
    for a in con.execute(
        """
        SELECT id, rf_renk_id, cari_id, durum, aktif, test_no
        FROM nexgen_arge_test
        WHERE aktif=1 AND rf_renk_id IS NOT NULL AND rf_renk_id!=0
        """
    ):
        base = {
            'rule': 'H1', 'arge_id': int(a['id']), 'rf_id': int(a['rf_renk_id']),
            'numune_id': '', 'arge_durum': a['durum'], 'arge_cari': a['cari_id'],
            'test_no': a['test_no'], 'confidence': 'HIGH',
        }
        durum = (a['durum'] or '').strip().upper()
        if durum in ('REDDEDILDI', 'RED', 'IPTAL', 'İPTAL'):
            excluded.append({**base, 'eligible': False, 'skip_reason': f'arge_{durum}'})
            continue
        if durum not in ARGE_OK_DURUM:
            excluded.append({**base, 'eligible': False, 'skip_reason': f'arge_durum_{durum}'})
            continue
        rf = con.execute(
            'SELECT id, aktif, durum, cari_id, kaynak_arge_test_id, rf_kod FROM nexgen_rf_renk WHERE id=?',
            (int(a['rf_renk_id']),),
        ).fetchone()
        if not rf:
            excluded.append({**base, 'eligible': False, 'skip_reason': 'orphan_rf'})
            continue
        ok, reason = _rf_ok(rf)
        if not ok:
            excluded.append({**base, 'eligible': False, 'skip_reason': reason, 'rf_kod': rf['rf_kod']})
            continue
        ok, reason = _rf_cari_ok(rf['cari_id'], a['cari_id'])
        if not ok:
            excluded.append({**base, 'eligible': False, 'skip_reason': reason})
            continue
        nt = find_numune_for_arge(con, int(a['id']))
        if not nt:
            excluded.append({**base, 'eligible': False, 'skip_reason': 'numune_yok_veya_multi'})
            continue
        base['numune_id'] = int(nt['id'])
        base['numune_kodu'] = nt['talep_kodu']
        base['numune_cari'] = nt['cari_id']
        base['eski_deger'] = nt['rf_renk_id']
        base['yeni_deger'] = int(a['rf_renk_id'])
        base['hedef_kolon'] = 'nexgen_numune_talep.rf_renk_id'
        base['rf_kod'] = rf['rf_kod']
        ok, reason = _cari_strict(nt['cari_id'], a['cari_id'])
        if not ok:
            excluded.append({**base, 'eligible': False, 'skip_reason': reason})
            continue
        nt_rf = _iint(nt['rf_renk_id'])
        if nt_rf is not None and nt_rf != int(a['rf_renk_id']):
            excluded.append({**base, 'eligible': False, 'skip_reason': 'mismatch_pointer'})
            continue
        if nt_rf == int(a['rf_renk_id']):
            excluded.append({**base, 'eligible': False, 'skip_reason': 'already_linked'})
            continue
        # nt_rf is None
        eligible.append({**base, 'eligible': True, 'skip_reason': '', 'reason': 'H1_numune_rf_from_arge'})
    return eligible, excluded


def select_h2(con: sqlite3.Connection) -> tuple[list[dict], list[dict]]:
    eligible: list[dict] = []
    excluded: list[dict] = []
    for a in con.execute(
        """
        SELECT id, rf_renk_id, cari_id, durum, aktif, test_no
        FROM nexgen_arge_test
        WHERE aktif=1 AND rf_renk_id IS NOT NULL AND rf_renk_id!=0
        """
    ):
        rid = int(a['rf_renk_id'])
        base = {
            'rule': 'H2', 'arge_id': int(a['id']), 'rf_id': rid,
            'numune_id': '', 'arge_durum': a['durum'], 'arge_cari': a['cari_id'],
            'test_no': a['test_no'], 'confidence': 'HIGH',
            'hedef_kolon': 'nexgen_rf_renk.kaynak_arge_test_id',
        }
        durum = (a['durum'] or '').strip().upper()
        if durum in ('REDDEDILDI', 'RED', 'IPTAL', 'İPTAL'):
            excluded.append({**base, 'eligible': False, 'skip_reason': f'arge_{durum}'})
            continue
        if durum not in ARGE_OK_DURUM:
            excluded.append({**base, 'eligible': False, 'skip_reason': f'arge_durum_{durum}'})
            continue
        rf = con.execute(
            """
            SELECT id, aktif, durum, cari_id, kaynak_arge_test_id, rf_kod
            FROM nexgen_rf_renk WHERE id=?
            """,
            (rid,),
        ).fetchone()
        if not rf:
            excluded.append({**base, 'eligible': False, 'skip_reason': 'orphan_rf'})
            continue
        ok, reason = _rf_ok(rf)
        if not ok:
            excluded.append({**base, 'eligible': False, 'skip_reason': reason})
            continue
        ok, reason = _rf_cari_ok(rf['cari_id'], a['cari_id'])
        if not ok:
            excluded.append({**base, 'eligible': False, 'skip_reason': reason})
            continue
        if _iint(a['cari_id']) is None:
            excluded.append({**base, 'eligible': False, 'skip_reason': 'cari_null'})
            continue
        kaynak = _iint(rf['kaynak_arge_test_id'])
        base['eski_deger'] = rf['kaynak_arge_test_id']
        base['yeni_deger'] = int(a['id'])
        base['rf_kod'] = rf['rf_kod']
        if kaynak is not None:
            if kaynak == int(a['id']):
                excluded.append({**base, 'eligible': False, 'skip_reason': 'already_linked'})
            else:
                excluded.append({**base, 'eligible': False, 'skip_reason': 'kaynak_other_arge'})
            continue
        # başka AR-GE aynı RF pointer?
        others = con.execute(
            """
            SELECT id FROM nexgen_arge_test
            WHERE aktif=1 AND rf_renk_id=? AND id!=?
            """,
            (rid, int(a['id'])),
        ).fetchall()
        if others:
            excluded.append({
                **base, 'eligible': False, 'skip_reason': 'multi_arge_same_rf',
                'other_arge_ids': ','.join(str(int(x['id'])) for x in others),
            })
            continue
        eligible.append({**base, 'eligible': True, 'skip_reason': '', 'reason': 'H2_rf_kaynak_from_arge'})
    return eligible, excluded


def select_h3(con: sqlite3.Connection) -> tuple[list[dict], list[dict]]:
    eligible: list[dict] = []
    excluded: list[dict] = []
    for rf in con.execute(
        """
        SELECT id, aktif, durum, cari_id, kaynak_arge_test_id, rf_kod
        FROM nexgen_rf_renk
        WHERE aktif=1 AND kaynak_arge_test_id IS NOT NULL AND kaynak_arge_test_id!=0
        """
    ):
        aid = int(rf['kaynak_arge_test_id'])
        base = {
            'rule': 'H3', 'arge_id': aid, 'rf_id': int(rf['id']),
            'numune_id': '', 'rf_kod': rf['rf_kod'], 'confidence': 'HIGH',
            'hedef_kolon': 'nexgen_arge_test.rf_renk_id',
            'eski_deger': None, 'yeni_deger': int(rf['id']),
        }
        ok, reason = _rf_ok(rf)
        if not ok:
            excluded.append({**base, 'eligible': False, 'skip_reason': reason})
            continue
        # multi RF same kaynak (defensive; UNIQUE may exist)
        multi = con.execute(
            """
            SELECT id FROM nexgen_rf_renk
            WHERE aktif=1 AND kaynak_arge_test_id=? AND id!=?
            """,
            (aid, int(rf['id'])),
        ).fetchall()
        if multi:
            excluded.append({
                **base, 'eligible': False, 'skip_reason': 'multi_rf_same_kaynak',
                'other_rf_ids': ','.join(str(int(x['id'])) for x in multi),
            })
            continue
        a = con.execute(
            'SELECT id, rf_renk_id, cari_id, durum, aktif, test_no FROM nexgen_arge_test WHERE id=?',
            (aid,),
        ).fetchone()
        if not a or not int(a['aktif'] or 0):
            excluded.append({**base, 'eligible': False, 'skip_reason': 'arge_yok_pasif'})
            continue
        base['arge_durum'] = a['durum']
        base['arge_cari'] = a['cari_id']
        base['test_no'] = a['test_no']
        base['eski_deger'] = a['rf_renk_id']
        durum = (a['durum'] or '').strip().upper()
        if durum in ('REDDEDILDI', 'RED', 'IPTAL', 'İPTAL'):
            excluded.append({**base, 'eligible': False, 'skip_reason': f'arge_{durum}'})
            continue
        if durum not in ARGE_OK_DURUM:
            excluded.append({**base, 'eligible': False, 'skip_reason': f'arge_durum_{durum}'})
            continue
        ok, reason = _rf_cari_ok(rf['cari_id'], a['cari_id'])
        if not ok:
            excluded.append({**base, 'eligible': False, 'skip_reason': reason})
            continue
        if _iint(a['cari_id']) is None:
            excluded.append({**base, 'eligible': False, 'skip_reason': 'cari_null'})
            continue
        arf = _iint(a['rf_renk_id'])
        if arf is not None:
            if arf == int(rf['id']):
                excluded.append({**base, 'eligible': False, 'skip_reason': 'already_linked'})
            else:
                excluded.append({**base, 'eligible': False, 'skip_reason': 'mismatch_pointer'})
            continue
        # numune cari check if present (for post H1)
        nt = find_numune_for_arge(con, aid)
        if nt:
            base['numune_id'] = int(nt['id'])
            ok, reason = _cari_strict(nt['cari_id'], a['cari_id'])
            if not ok:
                excluded.append({**base, 'eligible': False, 'skip_reason': reason})
                continue
            nt_rf = _iint(nt['rf_renk_id'])
            if nt_rf is not None and nt_rf != int(rf['id']):
                excluded.append({**base, 'eligible': False, 'skip_reason': 'numune_mismatch'})
                continue
        eligible.append({**base, 'eligible': True, 'skip_reason': '', 'reason': 'H3_arge_rf_from_kaynak'})
    return eligible, excluded


def build_manual_queue(con: sqlite3.Connection) -> list[dict]:
    rows: list[dict] = []
    # mismatches
    for r in con.execute(
        """
        SELECT nt.id AS numune_id, nt.talep_kodu, nt.rf_renk_id AS nt_rf, nt.cari_id AS nc,
               a.id AS arge_id, a.test_no, a.rf_renk_id AS arge_rf, a.cari_id AS ac, a.durum
        FROM nexgen_numune_talep nt
        JOIN nexgen_arge_test a ON a.id = nt.arge_test_id
        WHERE nt.aktif=1 AND a.aktif=1
          AND nt.rf_renk_id IS NOT NULL AND a.rf_renk_id IS NOT NULL
          AND nt.rf_renk_id != a.rf_renk_id
        """
    ):
        rows.append({
            'queue': 'mismatch', 'numune_id': r['numune_id'], 'arge_id': r['arge_id'],
            'rf_id': f"{r['nt_rf']}|{r['arge_rf']}", 'kod': r['talep_kodu'],
            'durum': r['durum'], 'skip_reason': 'mismatch_pointer',
            'oneri': 'Manuel karar — overwrite yok', 'oncelik': 'P1',
        })
    # text-only
    for r in con.execute(
        """
        SELECT id, test_no, cari_id, durum, yeni_renk_adi, formul_grup_adi
        FROM nexgen_arge_test
        WHERE aktif=1 AND (rf_renk_id IS NULL OR rf_renk_id=0)
          AND (
            IFNULL(TRIM(yeni_renk_adi),'')!=''
            OR IFNULL(TRIM(formul_grup_adi),'')!=''
            OR IFNULL(TRIM(renk_kodu),'')!=''
          )
        """
    ):
        rows.append({
            'queue': 'text_only', 'numune_id': '', 'arge_id': r['id'],
            'rf_id': '', 'kod': r['test_no'], 'durum': r['durum'],
            'skip_reason': 'text_only_no_id', 'oneri': 'Manuel RF oluştur/bağla',
            'oncelik': 'P2',
        })
    # multi formul
    if con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexgen_rf_formul_uygunluk'"
    ).fetchone():
        for r in con.execute(
            """
            SELECT rf_renk_id, COUNT(*) n FROM nexgen_rf_formul_uygunluk
            WHERE aktif=1 GROUP BY rf_renk_id HAVING COUNT(*)>1
            """
        ):
            rows.append({
                'queue': 'multi_formul', 'numune_id': '', 'arge_id': '',
                'rf_id': r['rf_renk_id'], 'kod': '', 'durum': '',
                'skip_reason': f'multi_formul_n={r["n"]}', 'oneri': 'Dokunma',
                'oncelik': 'P3',
            })
    return rows


AUDIT_FIELDS = [
    'rule', 'entity_table', 'row_id', 'eski_deger', 'yeni_deger',
    'numune_id', 'arge_id', 'rf_id', 'numune_cari', 'arge_cari',
    'status', 'aktif', 'timestamp', 'reason', 'confidence',
    'apply_sonucu', 'skip_reason',
]


def apply_backfill(
    db_path: str,
    *,
    dry_run: bool = True,
    allow_live: bool = False,
) -> dict[str, Any]:
    base = os.path.basename(os.path.normpath(db_path)).lower()
    if base == 'mock_data.db' and not allow_live and not dry_run:
        raise RuntimeError(
            'REFUSED: mock_data.db apply için --allow-live gerekir.'
        )
    if not os.path.isfile(db_path):
        raise RuntimeError(f'DB yok: {db_path}')

    con = sqlite3.connect(db_path, timeout=60)
    con.row_factory = sqlite3.Row
    audit: list[dict] = []
    ts = _now()
    result: dict[str, Any] = {
        'ok': False, 'dry_run': dry_run,
        'applied_h1': 0, 'applied_h2': 0, 'applied_h3': 0,
        'applied_h3_h1': 0,
        'skipped_h1': 0, 'skipped_h2': 0, 'skipped_h3': 0,
        'audit': audit, 'error': None,
    }
    try:
        pf = preflight(con)
        result['preflight'] = pf
        before = baseline_counts(con)
        result['baseline_before'] = before

        h1e, h1x = select_h1(con)
        h2e, h2x = select_h2(con)
        h3e, h3x = select_h3(con)
        result['candidates_h1'] = len(h1e)
        result['candidates_h2'] = len(h2e)
        result['candidates_h3'] = len(h3e)
        result['excluded_h1'] = len(h1x)
        result['excluded_h2'] = len(h2x)
        result['excluded_h3'] = len(h3x)
        result['all_h1'] = h1e + h1x
        result['all_h2'] = h2e + h2x
        result['all_h3'] = h3e + h3x
        result['manual_queue'] = build_manual_queue(con)

        if dry_run:
            for x in h1e + h2e + h3e:
                audit.append({
                    **x, 'entity_table': x.get('hedef_kolon', ''),
                    'row_id': x.get('numune_id') or x.get('rf_id') or x.get('arge_id'),
                    'timestamp': ts, 'apply_sonucu': 'DRY_RUN',
                    'status': x.get('arge_durum'), 'aktif': 1,
                    'numune_cari': x.get('numune_cari'), 'arge_cari': x.get('arge_cari'),
                })
            for x in h1x + h2x + h3x:
                audit.append({
                    **x, 'entity_table': x.get('hedef_kolon', ''),
                    'row_id': x.get('numune_id') or x.get('rf_id') or x.get('arge_id'),
                    'timestamp': ts, 'apply_sonucu': 'SKIP',
                    'status': x.get('arge_durum'), 'aktif': 1,
                    'numune_cari': x.get('numune_cari'), 'arge_cari': x.get('arge_cari'),
                })
            result['ok'] = True
            return result

        con.execute('BEGIN IMMEDIATE')
        # H1
        for x in h1e:
            con.execute(
                'UPDATE nexgen_numune_talep SET rf_renk_id=? WHERE id=? '
                'AND (rf_renk_id IS NULL OR rf_renk_id=0)',
                (int(x['yeni_deger']), int(x['numune_id'])),
            )
            if con.total_changes < 0:
                pass
            chk = con.execute(
                'SELECT rf_renk_id FROM nexgen_numune_talep WHERE id=?',
                (int(x['numune_id']),),
            ).fetchone()
            if _iint(chk['rf_renk_id']) != int(x['yeni_deger']):
                raise RuntimeError(f'H1 verify fail numune={x["numune_id"]}')
            audit.append({
                **x, 'entity_table': 'nexgen_numune_talep', 'row_id': x['numune_id'],
                'timestamp': ts, 'apply_sonucu': 'APPLIED',
                'status': x.get('arge_durum'), 'aktif': 1,
                'numune_cari': x.get('numune_cari'), 'arge_cari': x.get('arge_cari'),
            })
            result['applied_h1'] += 1
        for x in h1x:
            audit.append({
                **x, 'entity_table': 'nexgen_numune_talep',
                'row_id': x.get('numune_id') or '',
                'timestamp': ts, 'apply_sonucu': 'SKIP',
                'status': x.get('arge_durum'), 'aktif': 1,
                'numune_cari': x.get('numune_cari'), 'arge_cari': x.get('arge_cari'),
            })
            result['skipped_h1'] += 1

        # H2
        for x in h2e:
            con.execute(
                """
                UPDATE nexgen_rf_renk SET kaynak_arge_test_id=?
                WHERE id=? AND (kaynak_arge_test_id IS NULL OR kaynak_arge_test_id=0)
                """,
                (int(x['yeni_deger']), int(x['rf_id'])),
            )
            chk = con.execute(
                'SELECT kaynak_arge_test_id FROM nexgen_rf_renk WHERE id=?',
                (int(x['rf_id']),),
            ).fetchone()
            if _iint(chk['kaynak_arge_test_id']) != int(x['yeni_deger']):
                raise RuntimeError(f'H2 verify fail rf={x["rf_id"]}')
            audit.append({
                **x, 'entity_table': 'nexgen_rf_renk', 'row_id': x['rf_id'],
                'timestamp': ts, 'apply_sonucu': 'APPLIED',
                'status': x.get('arge_durum'), 'aktif': 1,
                'numune_cari': x.get('numune_cari'), 'arge_cari': x.get('arge_cari'),
            })
            result['applied_h2'] += 1
        for x in h2x:
            audit.append({
                **x, 'entity_table': 'nexgen_rf_renk', 'row_id': x.get('rf_id'),
                'timestamp': ts, 'apply_sonucu': 'SKIP',
                'status': x.get('arge_durum'), 'aktif': 1,
                'numune_cari': '', 'arge_cari': x.get('arge_cari'),
            })
            result['skipped_h2'] += 1

        # H3
        for x in h3e:
            con.execute(
                """
                UPDATE nexgen_arge_test SET rf_renk_id=?
                WHERE id=? AND (rf_renk_id IS NULL OR rf_renk_id=0)
                """,
                (int(x['yeni_deger']), int(x['arge_id'])),
            )
            chk = con.execute(
                'SELECT rf_renk_id FROM nexgen_arge_test WHERE id=?',
                (int(x['arge_id']),),
            ).fetchone()
            if _iint(chk['rf_renk_id']) != int(x['yeni_deger']):
                raise RuntimeError(f'H3 verify fail arge={x["arge_id"]}')
            audit.append({
                **x, 'entity_table': 'nexgen_arge_test', 'row_id': x['arge_id'],
                'timestamp': ts, 'apply_sonucu': 'APPLIED',
                'status': x.get('arge_durum'), 'aktif': 1,
                'numune_cari': x.get('numune_cari') if x.get('numune_id') else '',
                'arge_cari': x.get('arge_cari'),
            })
            result['applied_h3'] += 1
            # H3 sonrası H1 sync
            nt = find_numune_for_arge(con, int(x['arge_id']))
            if nt and _iint(nt['rf_renk_id']) is None:
                ok, reason = _cari_strict(nt['cari_id'], x.get('arge_cari'))
                if not ok:
                    raise RuntimeError(
                        f'H3→H1 conflict arge={x["arge_id"]} reason={reason}'
                    )
                con.execute(
                    'UPDATE nexgen_numune_talep SET rf_renk_id=? WHERE id=? '
                    'AND (rf_renk_id IS NULL OR rf_renk_id=0)',
                    (int(x['yeni_deger']), int(nt['id'])),
                )
                audit.append({
                    'rule': 'H3_H1', 'entity_table': 'nexgen_numune_talep',
                    'row_id': int(nt['id']), 'eski_deger': None,
                    'yeni_deger': int(x['yeni_deger']),
                    'numune_id': int(nt['id']), 'arge_id': x['arge_id'],
                    'rf_id': x['rf_id'], 'numune_cari': nt['cari_id'],
                    'arge_cari': x.get('arge_cari'),
                    'status': x.get('arge_durum'), 'aktif': 1,
                    'timestamp': ts, 'reason': 'H3_follow_H1',
                    'confidence': 'HIGH', 'apply_sonucu': 'APPLIED',
                    'skip_reason': '',
                })
                result['applied_h3_h1'] += 1
            elif nt and _iint(nt['rf_renk_id']) not in (None, int(x['yeni_deger'])):
                raise RuntimeError(
                    f'H3→H1 mismatch numune={nt["id"]} '
                    f'nt_rf={nt["rf_renk_id"]} rf={x["yeni_deger"]}'
                )
        for x in h3x:
            audit.append({
                **x, 'entity_table': 'nexgen_arge_test', 'row_id': x.get('arge_id'),
                'timestamp': ts, 'apply_sonucu': 'SKIP',
                'status': x.get('arge_durum'), 'aktif': 1,
                'numune_cari': '', 'arge_cari': x.get('arge_cari'),
            })
            result['skipped_h3'] += 1

        # global validation
        after = baseline_counts(con)
        result['baseline_after'] = after
        if after['mismatch'] > before['mismatch']:
            raise RuntimeError(
                f'mismatch arttı {before["mismatch"]}→{after["mismatch"]}'
            )
        if after['dup_kaynak_arge'] > before['dup_kaynak_arge']:
            raise RuntimeError('dup kaynak arttı')
        # snapshot regression
        for key in ('siparis_kalem_rf', 'plan_rf', 'batch_rf'):
            if key in before and before[key] != after.get(key):
                raise RuntimeError(f'{key} değişti {before[key]}→{after.get(key)}')

        con.commit()
        result['ok'] = True
        result['total_pointer_changes'] = (
            result['applied_h1'] + result['applied_h2']
            + result['applied_h3'] + result['applied_h3_h1']
        )
    except Exception as e:
        con.rollback()
        result['error'] = str(e)
        result['ok'] = False
        raise
    finally:
        con.close()
    return result


def rollback_from_audit(db_path: str, audit_rows: list[dict]) -> dict[str, Any]:
    con = sqlite3.connect(db_path, timeout=60)
    con.row_factory = sqlite3.Row
    restored = 0
    try:
        con.execute('BEGIN IMMEDIATE')
        for row in audit_rows:
            if row.get('apply_sonucu') != 'APPLIED':
                continue
            rule = row.get('rule')
            eski = row.get('eski_deger')
            if eski in ('', None):
                eski_sql = None
            else:
                try:
                    eski_sql = int(eski)
                except (TypeError, ValueError):
                    eski_sql = None
            if rule in ('H1', 'H3_H1'):
                con.execute(
                    'UPDATE nexgen_numune_talep SET rf_renk_id=? WHERE id=?',
                    (eski_sql, int(row['numune_id'] or row['row_id'])),
                )
                restored += 1
            elif rule == 'H2':
                con.execute(
                    'UPDATE nexgen_rf_renk SET kaynak_arge_test_id=? WHERE id=?',
                    (eski_sql, int(row['rf_id'] or row['row_id'])),
                )
                restored += 1
            elif rule == 'H3':
                con.execute(
                    'UPDATE nexgen_arge_test SET rf_renk_id=? WHERE id=?',
                    (eski_sql, int(row['arge_id'] or row['row_id'])),
                )
                restored += 1
        con.commit()
        return {'ok': True, 'restored': restored}
    except Exception as e:
        con.rollback()
        return {'ok': False, 'error': str(e), 'restored': restored}
    finally:
        con.close()


def write_csv(path: str, rows: list[dict], fields: list[str] | None = None) -> None:
    if not rows:
        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            f.write('')
        return
    fields = fields or sorted({k for r in rows for k in r.keys()})
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='FAZ-2C HIGH RF pointer sync backfill')
    p.add_argument('--db', required=True, help='Explicit DB path (zorunlu)')
    p.add_argument('--dry-run', action='store_true', default=None)
    p.add_argument('--apply', action='store_true', help='Gerçek UPDATE')
    p.add_argument('--confirm', default='', help=f'Apply için {CONFIRM_TOKEN}')
    p.add_argument('--allow-live', action='store_true')
    p.add_argument('--out', default='.', help='Kanıt çıktı klasörü')
    args = p.parse_args(argv)

    dry_run = True
    if args.apply:
        if args.confirm != CONFIRM_TOKEN:
            print(f'HATA: --apply için --confirm {CONFIRM_TOKEN} zorunlu', file=sys.stderr)
            return 2
        dry_run = False
    elif args.dry_run is False:
        dry_run = True
    else:
        dry_run = True

    os.makedirs(args.out, exist_ok=True)
    res = apply_backfill(args.db, dry_run=dry_run, allow_live=args.allow_live)

    write_csv(os.path.join(args.out, 'dryrun_h1.csv'), res.get('all_h1') or [])
    write_csv(os.path.join(args.out, 'dryrun_h2.csv'), res.get('all_h2') or [])
    write_csv(os.path.join(args.out, 'dryrun_h3.csv'), res.get('all_h3') or [])
    write_csv(os.path.join(args.out, 'manual_queue.csv'), res.get('manual_queue') or [])
    excl = [
        x for x in (res.get('all_h1') or []) + (res.get('all_h2') or []) + (res.get('all_h3') or [])
        if not x.get('eligible')
    ]
    write_csv(os.path.join(args.out, 'excluded_conflicts.csv'), excl)
    applied = [a for a in res.get('audit') or [] if a.get('apply_sonucu') == 'APPLIED']
    write_csv(
        os.path.join(args.out, 'apply_h1.csv'),
        [a for a in applied if a.get('rule') == 'H1'],
        AUDIT_FIELDS,
    )
    write_csv(
        os.path.join(args.out, 'apply_h2.csv'),
        [a for a in applied if a.get('rule') == 'H2'],
        AUDIT_FIELDS,
    )
    write_csv(
        os.path.join(args.out, 'apply_h3.csv'),
        [a for a in applied if a.get('rule') in ('H3', 'H3_H1')],
        AUDIT_FIELDS,
    )
    write_csv(os.path.join(args.out, 'audit_all.csv'), res.get('audit') or [], AUDIT_FIELDS)
    with open(os.path.join(args.out, 'result_summary.json'), 'w', encoding='utf-8') as f:
        dump = {k: v for k, v in res.items() if k not in (
            'audit', 'all_h1', 'all_h2', 'all_h3', 'manual_queue',
        )}
        json.dump(dump, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({
        'ok': res.get('ok'), 'dry_run': dry_run,
        'h1': res.get('candidates_h1'), 'h2': res.get('candidates_h2'),
        'h3': res.get('candidates_h3'),
        'applied_h1': res.get('applied_h1'), 'applied_h2': res.get('applied_h2'),
        'applied_h3': res.get('applied_h3'), 'applied_h3_h1': res.get('applied_h3_h1'),
    }, ensure_ascii=False, indent=2))
    return 0 if res.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
