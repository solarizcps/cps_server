# -*- coding: utf-8 -*-
"""
141_backfill_apply_1c.py
========================
FAZ-CARI360-GORUSME-NUMUNE-ARGE-SERT-ILISKI-1C

Deterministik backfill APPLY (yalnız kopya DB).
- A: arge.numune_talep_id <- numune.id (via arge_test_id)
- B-only: exact talep_kodu=talep_referansi (A ile örtüşmeyen)
- C: numune.mo_gorusme_id <- gorusme.id (via reverse)

Yeni kayıt YOK. Fuzzy YOK. Production'a dokunma.
"""
from __future__ import annotations

import csv
import os
import sqlite3
from datetime import datetime
from typing import Any

MULTI_EXCLUDE_KOD = 'AT-M-2026-0147'


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _norm(v: Any) -> str:
    return (str(v) if v is not None else '').strip()


def _cari_ok(a: Any, b: Any) -> bool:
    """İkisi de doluysa eşit olmalı; biri boşsa engelleme yok."""
    if a in (None, 0, '') or b in (None, 0, ''):
        return True
    return int(a) == int(b)


def _cols(con: sqlite3.Connection, table: str) -> set[str]:
    return {c[1] for c in con.execute(f'PRAGMA table_info({table})').fetchall()}


def select_rule_a(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if 'numune_talep_id' not in _cols(con, 'nexgen_arge_test'):
        return rows
    for r in con.execute(
        """
        SELECT nt.id AS numune_id, nt.talep_kodu, nt.cari_id AS nc, nt.durum AS ndurum,
               a.id AS arge_id, a.test_no, a.cari_id AS ac, a.numune_talep_id AS mevcut_ntp,
               a.durum AS adurum
        FROM nexgen_numune_talep nt
        JOIN nexgen_arge_test a ON a.id = nt.arge_test_id
        WHERE nt.arge_test_id IS NOT NULL AND nt.arge_test_id != 0
          AND nt.aktif = 1 AND a.aktif = 1
        """
    ):
        item = {
            'rule': 'A',
            'numune_talep_id': int(r['numune_id']),
            'arge_test_id': int(r['arge_id']),
            'gorusme_id': '',
            'numune_kodu': r['talep_kodu'],
            'arge_test_no': r['test_no'],
            'numune_cari_id': r['nc'],
            'arge_cari_id': r['ac'],
            'eski_deger': r['mevcut_ntp'],
            'yeni_deger': int(r['numune_id']),
            'hedef_kolon': 'nexgen_arge_test.numune_talep_id',
            'numune_durum': r['ndurum'],
            'arge_durum': r['adurum'],
            'eligible': True,
            'skip_reason': '',
        }
        if (r['talep_kodu'] or '') == MULTI_EXCLUDE_KOD:
            item['eligible'] = False
            item['skip_reason'] = 'AT-M-0147 excluded'
        elif r['mevcut_ntp'] not in (None, 0):
            if int(r['mevcut_ntp']) == int(r['numune_id']):
                item['eligible'] = False
                item['skip_reason'] = 'already_linked'
            else:
                item['eligible'] = False
                item['skip_reason'] = 'conflict_other_numune_on_arge'
        elif not _cari_ok(r['nc'], r['ac']):
            item['eligible'] = False
            item['skip_reason'] = 'cari_mismatch'
        else:
            # aynı AR-GE'ye başka numune.arge_test_id pointer?
            other = con.execute(
                """
                SELECT id FROM nexgen_numune_talep
                WHERE aktif=1 AND arge_test_id=? AND id!=?
                LIMIT 1
                """,
                (int(r['arge_id']), int(r['numune_id'])),
            ).fetchone()
            if other:
                item['eligible'] = False
                item['skip_reason'] = 'duplicate_numune_pointer_to_same_arge'
        rows.append(item)
    return rows


def select_rule_b_only(con: sqlite3.Connection) -> list[dict[str, Any]]:
    """Exact normalize match; A sonrası hâlâ numune_talep_id NULL olanlar."""
    rows: list[dict[str, Any]] = []
    if 'numune_talep_id' not in _cols(con, 'nexgen_arge_test'):
        return rows

    # kod -> numune ids / arge ids (normalize = strip)
    numune_by_kod: dict[str, list[sqlite3.Row]] = {}
    for r in con.execute(
        """
        SELECT id, talep_kodu, cari_id, arge_test_id, durum, aktif
        FROM nexgen_numune_talep WHERE aktif=1
        """
    ):
        k = _norm(r['talep_kodu'])
        if not k:
            continue
        numune_by_kod.setdefault(k, []).append(r)

    arge_by_ref: dict[str, list[sqlite3.Row]] = {}
    for r in con.execute(
        """
        SELECT id, test_no, talep_referansi, cari_id, numune_talep_id, durum, aktif
        FROM nexgen_arge_test WHERE aktif=1
        """
    ):
        k = _norm(r['talep_referansi'])
        if not k:
            continue
        arge_by_ref.setdefault(k, []).append(r)

    for kod, nlist in numune_by_kod.items():
        alist = arge_by_ref.get(kod, [])
        if not alist:
            continue
        base_meta = {
            'rule': 'B',
            'numune_kodu': kod,
        }
        if kod == MULTI_EXCLUDE_KOD or len(nlist) != 1 or len(alist) != 1:
            continue  # multi/orphan-like handled in manual/excluded separately

        nt = nlist[0]
        ar = alist[0]
        item = {
            'rule': 'B',
            'numune_talep_id': int(nt['id']),
            'arge_test_id': int(ar['id']),
            'gorusme_id': '',
            'numune_kodu': nt['talep_kodu'],
            'arge_test_no': ar['test_no'],
            'numune_cari_id': nt['cari_id'],
            'arge_cari_id': ar['cari_id'],
            'eski_deger': ar['numune_talep_id'],
            'yeni_deger': int(nt['id']),
            'hedef_kolon': 'nexgen_arge_test.numune_talep_id',
            'numune_durum': nt['durum'],
            'arge_durum': ar['durum'],
            'eligible': True,
            'skip_reason': '',
        }
        if ar['numune_talep_id'] not in (None, 0):
            item['eligible'] = False
            if int(ar['numune_talep_id']) == int(nt['id']):
                item['skip_reason'] = 'already_linked_or_A'
            else:
                item['skip_reason'] = 'conflict_other_numune_on_arge'
        elif nt['arge_test_id'] not in (None, 0) and int(nt['arge_test_id']) == int(ar['id']):
            # A adayı / A uygulanmış olmalı — B-only değil
            item['eligible'] = False
            item['skip_reason'] = 'covered_by_A_pointer'
        elif nt['arge_test_id'] not in (None, 0) and int(nt['arge_test_id']) != int(ar['id']):
            item['eligible'] = False
            item['skip_reason'] = 'numune.arge_test_id_points_elsewhere'
        elif not _cari_ok(nt['cari_id'], ar['cari_id']):
            item['eligible'] = False
            item['skip_reason'] = 'cari_mismatch'
        elif nt['cari_id'] in (None, 0) or ar['cari_id'] in (None, 0):
            # B için 1A dry-run: ikisi de NOT NULL zorunlu
            item['eligible'] = False
            item['skip_reason'] = 'cari_null_B_requires_both'
        rows.append(item)
    return rows


def select_rule_c(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if 'numune_talep_id' not in _cols(con, 'musteri_operasyon_gorusme'):
        return rows
    for r in con.execute(
        """
        SELECT g.id AS gorusme_id, g.cari_id AS gc, g.numune_talep_id,
               nt.id AS numune_id, nt.talep_kodu, nt.cari_id AS nc,
               nt.mo_gorusme_id, nt.durum AS ndurum
        FROM musteri_operasyon_gorusme g
        JOIN nexgen_numune_talep nt ON nt.id = g.numune_talep_id
        WHERE g.aktif=1 AND nt.aktif=1
          AND g.numune_talep_id IS NOT NULL AND g.numune_talep_id != 0
        """
    ):
        item = {
            'rule': 'C',
            'numune_talep_id': int(r['numune_id']),
            'arge_test_id': '',
            'gorusme_id': int(r['gorusme_id']),
            'numune_kodu': r['talep_kodu'],
            'arge_test_no': '',
            'numune_cari_id': r['nc'],
            'arge_cari_id': '',
            'gorusme_cari_id': r['gc'],
            'eski_deger': r['mo_gorusme_id'],
            'yeni_deger': int(r['gorusme_id']),
            'hedef_kolon': 'nexgen_numune_talep.mo_gorusme_id',
            'numune_durum': r['ndurum'],
            'arge_durum': '',
            'eligible': True,
            'skip_reason': '',
        }
        if r['mo_gorusme_id'] not in (None, 0):
            if int(r['mo_gorusme_id']) == int(r['gorusme_id']):
                item['eligible'] = False
                item['skip_reason'] = 'already_linked'
            else:
                item['eligible'] = False
                item['skip_reason'] = 'mo_gorusme_id_conflict'
        elif not _cari_ok(r['nc'], r['gc']):
            item['eligible'] = False
            item['skip_reason'] = 'cari_mismatch'
        else:
            # başka görüşme aynı numuneye reverse mi?
            other_g = con.execute(
                """
                SELECT id FROM musteri_operasyon_gorusme
                WHERE aktif=1 AND numune_talep_id=? AND id!=?
                LIMIT 1
                """,
                (int(r['numune_id']), int(r['gorusme_id'])),
            ).fetchone()
            if other_g:
                item['eligible'] = False
                item['skip_reason'] = 'multi_gorusme_reverse'
        rows.append(item)
    return rows


def build_manual_and_excluded(con: sqlite3.Connection) -> tuple[list[dict], list[dict]]:
    manual: list[dict] = []
    excluded: list[dict] = []

    # multi AT-M-0147
    for r in con.execute(
        """
        SELECT nt.id, nt.talep_kodu, nt.cari_id, nt.durum, COUNT(a.id) AS n
        FROM nexgen_numune_talep nt
        JOIN nexgen_arge_test a ON a.talep_referansi = nt.talep_kodu
        GROUP BY nt.id
        HAVING COUNT(a.id) > 1
        """
    ):
        manual.append({
            'numune_talep_id': r['id'],
            'arge_test_id': '',
            'gorusme_id': '',
            'kod': r['talep_kodu'],
            'durum': r['durum'],
            'cari_id': r['cari_id'],
            'neden': f'coklu AR-GE n={r["n"]}',
            'onerilen_manuel_karar': 'aktif AR-GE sec; reverse tekil bagla',
            'oncelik': 'YUKSEK' if (r['talep_kodu'] or '') == MULTI_EXCLUDE_KOD else 'ORTA',
        })

    # orphans
    for r in con.execute(
        """
        SELECT a.id, a.test_no, a.talep_referansi, a.cari_id, a.durum
        FROM nexgen_arge_test a
        WHERE IFNULL(TRIM(a.talep_referansi),'') != ''
          AND NOT EXISTS (
            SELECT 1 FROM nexgen_numune_talep nt
            WHERE nt.talep_kodu = a.talep_referansi
          )
        """
    ):
        excluded.append({
            'numune_talep_id': '',
            'arge_test_id': r['id'],
            'gorusme_id': '',
            'kod': r['talep_referansi'],
            'durum': r['durum'],
            'cari_id': r['cari_id'],
            'neden': 'orphan talep_referansi',
            'onerilen_manuel_karar': 'dokunma veya manuel numune eslestir',
            'oncelik': 'DUSUK',
        })

    # cari null numuneler (bilgi)
    for r in con.execute(
        """
        SELECT id, talep_kodu, durum, cari_id FROM nexgen_numune_talep
        WHERE aktif=1 AND (cari_id IS NULL OR cari_id=0)
        """
    ):
        manual.append({
            'numune_talep_id': r['id'],
            'arge_test_id': '',
            'gorusme_id': '',
            'kod': r['talep_kodu'],
            'durum': r['durum'],
            'cari_id': r['cari_id'],
            'neden': 'cari_id NULL — bu fazda duzeltilmez',
            'onerilen_manuel_karar': 'cari backfill ayri faz',
            'oncelik': 'ORTA',
        })

    # görüşmeye bağlanamayan (mo boş) — özet satır
    n_unlinked = con.execute(
        """
        SELECT COUNT(*) FROM nexgen_numune_talep
        WHERE aktif=1 AND (mo_gorusme_id IS NULL OR mo_gorusme_id=0)
        """
    ).fetchone()[0]
    manual.append({
        'numune_talep_id': '',
        'arge_test_id': '',
        'gorusme_id': '',
        'kod': '',
        'durum': '',
        'cari_id': '',
        'neden': f'gorusmeye baglanamayan numune adet={n_unlinked} (otomatik aday yok)',
        'onerilen_manuel_karar': '1B yeni yazmalar + manuel eslestirme',
        'oncelik': 'DUSUK',
    })

    # exact text eşleşmesi yalnız pasif AR-GE ile (B-only uygulanamaz)
    for r in con.execute(
        """
        SELECT nt.id, nt.talep_kodu, nt.cari_id, nt.durum, a.id AS arge_id
        FROM nexgen_numune_talep nt
        JOIN nexgen_arge_test a ON a.talep_referansi = nt.talep_kodu AND IFNULL(a.aktif,0)=0
        WHERE nt.aktif=1
          AND (nt.arge_test_id IS NULL OR nt.arge_test_id=0)
          AND NOT EXISTS (
            SELECT 1 FROM nexgen_arge_test a2
            WHERE a2.talep_referansi = nt.talep_kodu AND a2.aktif=1
          )
        """
    ):
        excluded.append({
            'numune_talep_id': r['id'],
            'arge_test_id': r['arge_id'],
            'gorusme_id': '',
            'kod': r['talep_kodu'],
            'durum': r['durum'],
            'cari_id': r['cari_id'],
            'neden': 'exact match yalniz pasif AR-GE (aktif=0) — B-only yok',
            'onerilen_manuel_karar': 'pasif AR-GE canlandir veya yeni aktif bagla',
            'oncelik': 'ORTA',
        })

    # pre-existing duplicate pointer (arge ← birden fazla numune)
    for r in con.execute(
        """
        SELECT a.id AS arge_id, GROUP_CONCAT(nt.id) AS nids, COUNT(DISTINCT nt.id) AS n
        FROM nexgen_arge_test a
        JOIN nexgen_numune_talep nt ON nt.arge_test_id = a.id AND nt.aktif=1
        WHERE a.aktif=1
        GROUP BY a.id
        HAVING COUNT(DISTINCT nt.id) > 1
        """
    ):
        excluded.append({
            'numune_talep_id': r['nids'],
            'arge_test_id': r['arge_id'],
            'gorusme_id': '',
            'kod': '',
            'durum': '',
            'cari_id': '',
            'neden': f'preexisting duplicate arge_test_id pointer n={r["n"]}',
            'onerilen_manuel_karar': 'tek aktif pointer sec; digeri temizle',
            'oncelik': 'YUKSEK',
        })
    return manual, excluded


AUDIT_FIELDS = [
    'rule', 'numune_talep_id', 'arge_test_id', 'gorusme_id',
    'numune_kodu', 'arge_test_no',
    'numune_cari_id', 'arge_cari_id', 'gorusme_cari_id',
    'hedef_kolon', 'eski_deger', 'yeni_deger',
    'timestamp', 'apply_sonucu', 'skip_reason',
]


def apply_backfill(
    db_path: str,
    *,
    dry_run: bool = False,
    allow_live: bool = False,
) -> dict[str, Any]:
    """Tek BEGIN IMMEDIATE: A → B-only → C → doğrulama → COMMIT/ROLLBACK.

    Güvenlik: basename mock_data.db ise allow_live=True zorunlu
    (yanlışlıkla canlı DB'ye yazmayı engeller).
    """
    base = os.path.basename(os.path.normpath(db_path)).lower()
    if base == 'mock_data.db' and not allow_live and not dry_run:
        raise RuntimeError(
            'REFUSED: mock_data.db backfill apply için allow_live=True gerekir. '
            'Önce kopya DB + dry_run kullanın.'
        )
    con = sqlite3.connect(db_path, timeout=60)
    con.row_factory = sqlite3.Row
    audit: list[dict[str, Any]] = []
    ts = _now()
    result: dict[str, Any] = {
        'ok': False,
        'dry_run': dry_run,
        'applied_a': 0,
        'applied_b_only': 0,
        'applied_c': 0,
        'skipped_a': 0,
        'skipped_b': 0,
        'skipped_c': 0,
        'audit': audit,
        'error': None,
    }
    try:
        if 'numune_talep_id' not in _cols(con, 'nexgen_arge_test'):
            raise RuntimeError('Migration 141 gerekli (arge.numune_talep_id yok)')

        cand_a = select_rule_a(con)
        cand_b = select_rule_b_only(con)
        cand_c = select_rule_c(con)

        elig_a = [x for x in cand_a if x['eligible']]
        elig_b = [x for x in cand_b if x['eligible']]
        elig_c = [x for x in cand_c if x['eligible']]
        result['candidates_a'] = len(elig_a)
        result['candidates_b_only'] = len(elig_b)
        result['candidates_c'] = len(elig_c)
        result['all_a'] = cand_a
        result['all_b'] = cand_b
        result['all_c'] = cand_c

        if dry_run:
            for x in elig_a + elig_b + elig_c:
                audit.append({**x, 'timestamp': ts, 'apply_sonucu': 'DRY_RUN'})
            for x in cand_a + cand_b + cand_c:
                if not x['eligible']:
                    audit.append({**x, 'timestamp': ts, 'apply_sonucu': 'SKIP'})
            result['ok'] = True
            return result

        con.execute('BEGIN IMMEDIATE')
        try:
            for x in elig_a:
                cur = con.execute(
                    """
                    UPDATE nexgen_arge_test
                    SET numune_talep_id=?
                    WHERE id=? AND aktif=1
                      AND (numune_talep_id IS NULL OR numune_talep_id=0)
                    """,
                    (x['yeni_deger'], x['arge_test_id']),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(
                        f"A guard fail arge={x['arge_test_id']} numune={x['numune_talep_id']}"
                    )
                audit.append({**x, 'timestamp': ts, 'apply_sonucu': 'APPLIED'})
                result['applied_a'] += 1

            # B-only: A sonrası yeniden seç (A ile doldurulanlar elensin)
            cand_b2 = select_rule_b_only(con)
            elig_b2 = [x for x in cand_b2 if x['eligible']]
            for x in elig_b2:
                cur = con.execute(
                    """
                    UPDATE nexgen_arge_test
                    SET numune_talep_id=?
                    WHERE id=? AND aktif=1
                      AND (numune_talep_id IS NULL OR numune_talep_id=0)
                    """,
                    (x['yeni_deger'], x['arge_test_id']),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(
                        f"B guard fail arge={x['arge_test_id']} numune={x['numune_talep_id']}"
                    )
                audit.append({**x, 'timestamp': ts, 'apply_sonucu': 'APPLIED'})
                result['applied_b_only'] += 1

            for x in elig_c:
                cur = con.execute(
                    """
                    UPDATE nexgen_numune_talep
                    SET mo_gorusme_id=?
                    WHERE id=? AND aktif=1
                      AND (mo_gorusme_id IS NULL OR mo_gorusme_id=0)
                    """,
                    (x['yeni_deger'], x['numune_talep_id']),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(
                        f"C guard fail numune={x['numune_talep_id']} gorusme={x['gorusme_id']}"
                    )
                audit.append({**x, 'timestamp': ts, 'apply_sonucu': 'APPLIED'})
                result['applied_c'] += 1

            # in-tx validation — yalnız bu apply'ın dokunduğu satırlar
            applied_arge_ids = [
                int(x['arge_test_id']) for x in elig_a + elig_b2 if x.get('arge_test_id')
            ]
            applied_numune_ids_c = [int(x['numune_talep_id']) for x in elig_c]

            if applied_arge_ids:
                ph = ','.join('?' * len(applied_arge_ids))
                mm = con.execute(
                    f"""
                    SELECT COUNT(*) FROM nexgen_arge_test a
                    JOIN nexgen_numune_talep nt ON nt.id = a.numune_talep_id
                    WHERE a.id IN ({ph})
                      AND nt.cari_id IS NOT NULL AND nt.cari_id != 0
                      AND a.cari_id IS NOT NULL AND a.cari_id != 0
                      AND nt.cari_id != a.cari_id
                    """,
                    applied_arge_ids,
                ).fetchone()[0]
                if mm:
                    raise RuntimeError(f'cari mismatch on applied rows: {mm}')

                # uygulanan AR-GE reverse'i kendi numune pointer'ı ile çelişmesin
                bad = con.execute(
                    f"""
                    SELECT COUNT(*) FROM nexgen_arge_test a
                    JOIN nexgen_numune_talep nt ON nt.id = a.numune_talep_id
                    WHERE a.id IN ({ph})
                      AND nt.arge_test_id IS NOT NULL AND nt.arge_test_id != 0
                      AND nt.arge_test_id != a.id
                    """,
                    applied_arge_ids,
                ).fetchone()[0]
                if bad:
                    raise RuntimeError(f'pointer/reverse mismatch on applied: {bad}')

                # uygulanan AR-GE'ye birden fazla numune.arge_test_id olmamalı
                dup = con.execute(
                    f"""
                    SELECT a.id FROM nexgen_arge_test a
                    JOIN nexgen_numune_talep nt ON nt.arge_test_id=a.id AND nt.aktif=1
                    WHERE a.id IN ({ph})
                    GROUP BY a.id HAVING COUNT(DISTINCT nt.id) > 1
                    """,
                    applied_arge_ids,
                ).fetchall()
                if dup:
                    raise RuntimeError(f'duplicate pointer on applied arge: {len(dup)}')

            for nid in applied_numune_ids_c:
                g = con.execute(
                    'SELECT mo_gorusme_id FROM nexgen_numune_talep WHERE id=?',
                    (nid,),
                ).fetchone()
                if not g or g['mo_gorusme_id'] in (None, 0):
                    raise RuntimeError(f'C apply missing mo_gorusme_id numune={nid}')

            con.commit()
            result['ok'] = True
            result['applied_b_candidates_reselect'] = len(elig_b2)
        except Exception as e:
            con.rollback()
            result['error'] = str(e)
            result['ok'] = False
            raise
    finally:
        con.close()
    return result


def rollback_from_audit(db_path: str, audit_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Audit APPLIED satırlarını tersine çevir."""
    con = sqlite3.connect(db_path, timeout=60)
    con.row_factory = sqlite3.Row
    restored = 0
    try:
        con.execute('BEGIN IMMEDIATE')
        for row in audit_rows:
            if row.get('apply_sonucu') != 'APPLIED':
                continue
            rule = row['rule']
            eski = row.get('eski_deger')
            if eski in ('', None):
                eski_sql = None
            else:
                try:
                    eski_sql = int(eski)
                except (TypeError, ValueError):
                    eski_sql = None
            if rule in ('A', 'B'):
                con.execute(
                    """
                    UPDATE nexgen_arge_test
                    SET numune_talep_id=?
                    WHERE id=?
                    """,
                    (eski_sql, int(row['arge_test_id'])),
                )
                restored += 1
            elif rule == 'C':
                con.execute(
                    """
                    UPDATE nexgen_numune_talep
                    SET mo_gorusme_id=?
                    WHERE id=?
                    """,
                    (eski_sql, int(row['numune_talep_id'])),
                )
                restored += 1
        con.commit()
        return {'ok': True, 'restored': restored}
    except Exception as e:
        con.rollback()
        return {'ok': False, 'error': str(e), 'restored': restored}
    finally:
        con.close()


def write_audit_csv(path: str, rows: list[dict[str, Any]]) -> None:
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=AUDIT_FIELDS, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)


def read_audit_csv(path: str) -> list[dict[str, Any]]:
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))
