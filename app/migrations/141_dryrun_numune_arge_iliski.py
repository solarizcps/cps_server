# -*- coding: utf-8 -*-
"""
141_dryrun_numune_arge_iliski.py
================================
FAZ-CARI360-GORUSME-NUMUNE-ARGE-SERT-ILISKI-1A

Read-only dry-run: deterministik backfill adayları (UPDATE YOK).

Kurallar:
  A — numune.arge_test_id = arge.id
  B — exact talep_kodu = talep_referansi, tekil, cari uyumlu (ikisi de NOT NULL)
  C — gorusme.numune_talep_id = numune.id reverse → mo_gorusme_id adayı

Hariç:
  - AT-M-2026-0147 çoklu AR-GE
  - orphan talep_referansi
  - belirsiz / çakışan eşleşmeler
  - cari_id düzeltmesi YOK
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
from typing import Any


MULTI_EXCLUDE_KOD = 'AT-M-2026-0147'


def _q(con: sqlite3.Connection, sql: str, p: tuple = ()) -> list[sqlite3.Row]:
    return list(con.execute(sql, p).fetchall())


def _write_csv(path: str, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)


def dump_schema(con: sqlite3.Connection, path: str) -> None:
    lines: list[str] = []
    for t in ('musteri_operasyon_gorusme', 'nexgen_numune_talep', 'nexgen_arge_test'):
        lines.append(f'=== {t} ===')
        for r in _q(con, f'PRAGMA table_info({t})'):
            lines.append(
                f"  {r['name']}: {r['type']} notnull={r['notnull']} "
                f"pk={r['pk']} dflt={r['dflt_value']}"
            )
        for r in _q(con, f'PRAGMA index_list({t})'):
            cols = [c['name'] for c in _q(con, f"PRAGMA index_info('{r['name']}')")]
            lines.append(f"  IDX {r['name']} unique={r['unique']} cols={cols}")
        for r in _q(con, f'PRAGMA foreign_key_list({t})'):
            lines.append(f"  FK {r['from']}->{r['table']}.{r['to']}")
        lines.append('')
    ver = _q(con, "SELECT MAX(version) AS v FROM schema_migrations")
    lines.append(f'schema_migrations.max_version={ver[0]["v"] if ver else None}')
    col_present = 'numune_talep_id' in {
        r['name'] for r in _q(con, 'PRAGMA table_info(nexgen_arge_test)')
    }
    lines.append(f'nexgen_arge_test.numune_talep_id_present={col_present}')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def run_dryrun(db_path: str, out_dir: str) -> dict[str, Any]:
    os.makedirs(out_dir, exist_ok=True)
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        arge_cols = {r['name'] for r in _q(con, 'PRAGMA table_info(nexgen_arge_test)')}
        has_ntp = 'numune_talep_id' in arge_cols
        ntp_expr = 'a.numune_talep_id' if has_ntp else 'NULL'

        fields = [
            'numune_id', 'arge_id', 'gorusme_id', 'numune_kodu', 'arge_test_no',
            'numune_cari_id', 'arge_cari_id', 'gorusme_cari_id',
            'kural', 'guven', 'apply_uygun', 'dislama_nedeni', 'notlar',
        ]

        rule_a: list[dict[str, Any]] = []
        rule_b: list[dict[str, Any]] = []
        rule_c: list[dict[str, Any]] = []
        manual: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []

        # --- Rule A ---
        for r in _q(con, f"""
            SELECT nt.id AS numune_id, nt.talep_kodu, nt.cari_id AS nc,
                   a.id AS arge_id, a.test_no, a.cari_id AS ac,
                   {ntp_expr} AS mevcut_ntp
            FROM nexgen_numune_talep nt
            JOIN nexgen_arge_test a ON a.id = nt.arge_test_id
            WHERE nt.arge_test_id IS NOT NULL AND nt.arge_test_id != 0
        """):
            row = {
                'numune_id': r['numune_id'],
                'arge_id': r['arge_id'],
                'gorusme_id': '',
                'numune_kodu': r['talep_kodu'],
                'arge_test_no': r['test_no'],
                'numune_cari_id': r['nc'],
                'arge_cari_id': r['ac'],
                'gorusme_cari_id': '',
                'kural': 'A',
                'guven': 'HIGH',
                'apply_uygun': 'EVET',
                'dislama_nedeni': '',
                'notlar': 'pointer arge_test_id reverse',
            }
            if r['mevcut_ntp'] not in (None, 0) and int(r['mevcut_ntp']) != int(r['numune_id']):
                row['apply_uygun'] = 'HAYIR'
                row['dislama_nedeni'] = 'arge.numune_talep_id farkli numune gosteriyor'
                row['guven'] = 'CONFLICT'
                excluded.append(row)
            elif (r['talep_kodu'] or '') == MULTI_EXCLUDE_KOD:
                row['apply_uygun'] = 'HAYIR'
                row['dislama_nedeni'] = 'AT-M-0147 coklu grup — bu fazda dokunulmaz'
                row['guven'] = 'MANUAL'
                excluded.append(row)
            else:
                if r['nc'] in (None, 0) or r['ac'] in (None, 0):
                    row['notlar'] += '; cari NULL (cari duzeltilmez, ID pointer OK)'
                if r['nc'] not in (None, 0) and r['ac'] not in (None, 0) and int(r['nc']) != int(r['ac']):
                    row['apply_uygun'] = 'HAYIR'
                    row['dislama_nedeni'] = 'cari_id uyusmazligi'
                    row['guven'] = 'CONFLICT'
                    excluded.append(row)
                else:
                    rule_a.append(row)

        # --- Rule B (tekil exact + cari NOT NULL eslesme) ---
        multi_ids = {
            int(r['numune_id']) for r in _q(con, """
                SELECT nt.id AS numune_id
                FROM nexgen_numune_talep nt
                JOIN nexgen_arge_test a ON a.talep_referansi = nt.talep_kodu
                GROUP BY nt.id
                HAVING COUNT(*) > 1
            """)
        }
        for r in _q(con, f"""
            SELECT nt.id AS numune_id, nt.talep_kodu, nt.cari_id AS nc,
                   nt.arge_test_id,
                   a.id AS arge_id, a.test_no, a.cari_id AS ac,
                   {ntp_expr} AS mevcut_ntp,
                   (SELECT COUNT(*) FROM nexgen_arge_test a2
                    WHERE a2.talep_referansi = nt.talep_kodu) AS ref_cnt
            FROM nexgen_numune_talep nt
            JOIN nexgen_arge_test a ON a.talep_referansi = nt.talep_kodu
        """):
            base = {
                'numune_id': r['numune_id'],
                'arge_id': r['arge_id'],
                'gorusme_id': '',
                'numune_kodu': r['talep_kodu'],
                'arge_test_no': r['test_no'],
                'numune_cari_id': r['nc'],
                'arge_cari_id': r['ac'],
                'gorusme_cari_id': '',
                'kural': 'B',
                'guven': '',
                'apply_uygun': '',
                'dislama_nedeni': '',
                'notlar': 'exact talep_kodu=talep_referansi',
            }
            if int(r['numune_id']) in multi_ids or (r['talep_kodu'] or '') == MULTI_EXCLUDE_KOD:
                base['guven'] = 'MANUAL'
                base['apply_uygun'] = 'HAYIR'
                base['dislama_nedeni'] = 'coklu AR-GE / AT-M-0147'
                excluded.append(base)
                continue
            if r['ref_cnt'] != 1:
                base['guven'] = 'LOW'
                base['apply_uygun'] = 'HAYIR'
                base['dislama_nedeni'] = 'tekil degil'
                excluded.append(base)
                continue
            if r['nc'] in (None, 0) or r['ac'] in (None, 0):
                base['guven'] = 'MANUAL'
                base['apply_uygun'] = 'HAYIR'
                base['dislama_nedeni'] = 'cari_id NULL — bu fazda duzeltilmez / B icin zorunlu'
                manual.append(base)
                continue
            if int(r['nc']) != int(r['ac']):
                base['guven'] = 'CONFLICT'
                base['apply_uygun'] = 'HAYIR'
                base['dislama_nedeni'] = 'cari_id uyusmazligi'
                excluded.append(base)
                continue
            if r['mevcut_ntp'] not in (None, 0) and int(r['mevcut_ntp']) != int(r['numune_id']):
                base['guven'] = 'CONFLICT'
                base['apply_uygun'] = 'HAYIR'
                base['dislama_nedeni'] = 'arge.numune_talep_id cakismasi'
                excluded.append(base)
                continue
            # Rule A zaten bu arge'yi kapsıyorsa B apply'da redundant ama raporlanır
            if r['arge_test_id'] and int(r['arge_test_id']) == int(r['arge_id']):
                base['guven'] = 'HIGH'
                base['apply_uygun'] = 'EVET'
                base['notlar'] += '; A ile ayni pointer (redundant OK)'
                rule_b.append(base)
                continue
            if r['arge_test_id'] and int(r['arge_test_id']) != int(r['arge_id']):
                base['guven'] = 'CONFLICT'
                base['apply_uygun'] = 'HAYIR'
                base['dislama_nedeni'] = 'numune.arge_test_id farkli AR-GE gosteriyor'
                excluded.append(base)
                continue
            base['guven'] = 'HIGH'
            base['apply_uygun'] = 'EVET'
            base['notlar'] += '; A pointer yok — B adayi'
            rule_b.append(base)

        # Orphan refs → excluded
        for r in _q(con, """
            SELECT a.id AS arge_id, a.test_no, a.talep_referansi, a.cari_id AS ac
            FROM nexgen_arge_test a
            WHERE IFNULL(TRIM(a.talep_referansi), '') != ''
              AND NOT EXISTS (
                SELECT 1 FROM nexgen_numune_talep nt
                WHERE nt.talep_kodu = a.talep_referansi
              )
        """):
            excluded.append({
                'numune_id': '',
                'arge_id': r['arge_id'],
                'gorusme_id': '',
                'numune_kodu': '',
                'arge_test_no': r['test_no'],
                'numune_cari_id': '',
                'arge_cari_id': r['ac'],
                'gorusme_cari_id': '',
                'kural': 'ORPHAN_REF',
                'guven': 'N/A',
                'apply_uygun': 'HAYIR',
                'dislama_nedeni': 'orphan talep_referansi — dokunulmaz',
                'notlar': r['talep_referansi'],
            })

        # --- Rule C ---
        for r in _q(con, """
            SELECT g.id AS gorusme_id, g.cari_id AS gc, g.numune_talep_id,
                   nt.id AS numune_id, nt.talep_kodu, nt.cari_id AS nc,
                   nt.mo_gorusme_id
            FROM musteri_operasyon_gorusme g
            JOIN nexgen_numune_talep nt ON nt.id = g.numune_talep_id
            WHERE g.numune_talep_id IS NOT NULL AND g.numune_talep_id != 0
        """):
            row = {
                'numune_id': r['numune_id'],
                'arge_id': '',
                'gorusme_id': r['gorusme_id'],
                'numune_kodu': r['talep_kodu'],
                'arge_test_no': '',
                'numune_cari_id': r['nc'],
                'arge_cari_id': '',
                'gorusme_cari_id': r['gc'],
                'kural': 'C',
                'guven': 'HIGH',
                'apply_uygun': 'EVET',
                'dislama_nedeni': '',
                'notlar': 'reverse gorusme.numune_talep_id → mo_gorusme_id',
            }
            if r['mo_gorusme_id'] not in (None, 0) and int(r['mo_gorusme_id']) != int(r['gorusme_id']):
                row['apply_uygun'] = 'HAYIR'
                row['guven'] = 'CONFLICT'
                row['dislama_nedeni'] = 'mo_gorusme_id farkli gorusme'
                excluded.append(row)
                continue
            if r['nc'] not in (None, 0) and r['gc'] not in (None, 0) and int(r['nc']) != int(r['gc']):
                row['apply_uygun'] = 'HAYIR'
                row['guven'] = 'CONFLICT'
                row['dislama_nedeni'] = 'cari_id uyusmazligi'
                excluded.append(row)
                continue
            if r['mo_gorusme_id'] and int(r['mo_gorusme_id']) == int(r['gorusme_id']):
                row['apply_uygun'] = 'HAYIR'
                row['dislama_nedeni'] = 'zaten bagli'
                row['notlar'] += '; no-op'
                rule_c.append(row)
            else:
                rule_c.append(row)

        # Manual: multi group summary + cari-null numune count note
        for nid in sorted(multi_ids):
            kod = _q(con, 'SELECT talep_kodu FROM nexgen_numune_talep WHERE id=?', (nid,))
            n_arge = _q(con, """
                SELECT COUNT(*) AS c FROM nexgen_arge_test a
                JOIN nexgen_numune_talep nt ON a.talep_referansi = nt.talep_kodu
                WHERE nt.id=?
            """, (nid,))[0]['c']
            manual.append({
                'numune_id': nid,
                'arge_id': '',
                'gorusme_id': '',
                'numune_kodu': kod[0]['talep_kodu'] if kod else '',
                'arge_test_no': '',
                'numune_cari_id': '',
                'arge_cari_id': '',
                'gorusme_cari_id': '',
                'kural': 'MULTI',
                'guven': 'MANUAL',
                'apply_uygun': 'HAYIR',
                'dislama_nedeni': f'coklu AR-GE n={n_arge}',
                'notlar': 'aktif AR-GE secimi 1C disi manuel',
            })

        _write_csv(os.path.join(out_dir, 'dryrun_rule_a.csv'), rule_a, fields)
        _write_csv(os.path.join(out_dir, 'dryrun_rule_b.csv'), rule_b, fields)
        _write_csv(os.path.join(out_dir, 'dryrun_rule_c.csv'), rule_c, fields)
        _write_csv(os.path.join(out_dir, 'manual_queue.csv'), manual, fields)
        _write_csv(os.path.join(out_dir, 'excluded_conflicts.csv'), excluded, fields)

        summary = {
            'rule_a_apply': len(rule_a),
            'rule_b_apply': len(rule_b),
            'rule_c_apply': len([r for r in rule_c if r['apply_uygun'] == 'EVET']),
            'rule_c_total_rows': len(rule_c),
            'manual_queue': len(manual),
            'excluded': len(excluded),
            'backfill_update_executed': False,
        }
        with open(os.path.join(out_dir, 'dryrun_summary.json'), 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        return summary
    finally:
        con.close()


if __name__ == '__main__':
    import sys
    # Read-only dry-run; yine de explicit path tercih edilir.
    if len(sys.argv) < 2:
        raise SystemExit(
            'HATA: kullanım: python 141_dryrun_numune_arge_iliski.py <db_path> [out_dir]'
        )
    db = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else '.'
    print(json.dumps(run_dryrun(db, out), ensure_ascii=False, indent=2))
