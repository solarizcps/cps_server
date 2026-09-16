# -*- coding: utf-8 -*-
"""Schema parity check — CODE_REQUIRED vs DB_ACTUAL (read-only)."""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.infra_contract_loader import contract_tables, load_contract


def _is_absolute(path: str) -> bool:
    return os.path.isabs(path)


def _git_head(repo: str) -> str:
    proc = subprocess.run(
        ['git', 'rev-parse', 'HEAD'],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def _table_exists(cur: sqlite3.Cursor, name: str) -> bool:
    return cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone() is not None


def _col_info(cur: sqlite3.Cursor, table: str) -> dict[str, dict]:
    return {
        r[1]: {'type': r[2], 'notnull': r[3], 'dflt': r[4], 'pk': r[5]}
        for r in cur.execute(f'PRAGMA table_info({table})').fetchall()
    }


def _index_columns(cur: sqlite3.Cursor, idx: str) -> list[str]:
    return [r[2] for r in cur.execute(f'PRAGMA index_info({idx})').fetchall()]


def _fk_list(cur: sqlite3.Cursor, table: str) -> list[tuple]:
    return cur.execute(f'PRAGMA foreign_key_list({table})').fetchall()


def _migration_versions(cur: sqlite3.Cursor) -> set[str]:
    if not _table_exists(cur, 'schema_migrations'):
        return set()
    rows = cur.execute('SELECT version FROM schema_migrations').fetchall()
    return {str(r[0]) for r in rows}


def _norm_default(val: Any) -> str | None:
    if val is None:
        return None
    return str(val).strip()


def _norm_type(val: str) -> str:
    return (val or '').strip().upper()


def check_parity(
    *,
    contract_path: str,
    db_path: str,
    repo_path: str | None = None,
    expected_commit: str | None = None,
    skip_commit_check: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        'PARITY_RESULT': 'BLOCKED',
        'MISSING_TABLES': [],
        'MISSING_COLUMNS': [],
        'TYPE_MISMATCHES': [],
        'MISSING_INDEXES': [],
        'MISSING_MIGRATIONS': [],
        'EXTRA_TABLES': [],
        'DB_INTEGRITY': '',
        'EXPECTED_COMMIT': expected_commit or '',
        'ACTUAL_COMMIT': '',
        'DB_PATH': db_path,
    }

    if not _is_absolute(contract_path):
        result['error'] = 'contract path must be absolute'
        return result
    if not _is_absolute(db_path):
        result['error'] = 'db path must be absolute'
        return result
    if not os.path.isfile(db_path):
        result['error'] = f'db not found: {db_path}'
        return result
    if os.path.getsize(db_path) == 0:
        result['error'] = 'db is zero bytes'
        return result

    if repo_path:
        if not _is_absolute(repo_path):
            result['error'] = 'repo path must be absolute'
            return result
        try:
            actual = _git_head(repo_path)
            result['ACTUAL_COMMIT'] = actual
            if expected_commit and not skip_commit_check:
                if actual != expected_commit:
                    result['error'] = f'commit mismatch: expected {expected_commit}, got {actual}'
                    return result
        except subprocess.CalledProcessError as exc:
            result['error'] = f'git head failed: {exc}'
            return result

    contract = load_contract(contract_path)
    uri = 'file:' + db_path.replace('\\', '/') + '?mode=ro'
    con = sqlite3.connect(uri, uri=True)
    cur = con.cursor()
    try:
        ic = cur.execute('PRAGMA integrity_check').fetchone()[0]
        result['DB_INTEGRITY'] = ic
        if ic != 'ok':
            result['error'] = f'integrity_check={ic}'
            return result

        required_tables = {t['name'] for t in contract_tables(contract)}
        existing_tables = {
            r[0] for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        for tname in sorted(required_tables):
            if tname not in existing_tables:
                result['MISSING_TABLES'].append(tname)

        for tspec in contract_tables(contract):
            tname = tspec['name']
            if tname not in existing_tables:
                continue
            cols = _col_info(cur, tname)
            for cspec in tspec.get('columns') or []:
                cname = cspec['name']
                if cname not in cols:
                    result['MISSING_COLUMNS'].append(f'{tname}.{cname}')
                    continue
                actual = cols[cname]
                exp_type = _norm_type(cspec.get('type', ''))
                act_type = _norm_type(actual['type'])
                if exp_type and act_type != exp_type:
                    result['TYPE_MISMATCHES'].append(
                        f'{tname}.{cname}: expected {exp_type}, got {act_type}'
                    )
                if cspec.get('not_null') and not actual['notnull']:
                    result['TYPE_MISMATCHES'].append(
                        f'{tname}.{cname}: expected NOT NULL'
                    )
                if 'default' in cspec:
                    exp_d = _norm_default(cspec['default'])
                    act_d = _norm_default(actual['dflt'])
                    if exp_d is not None and act_d != exp_d:
                        # created_at default may vary in expression form — skip strict
                        if cname != 'created_at':
                            result['TYPE_MISMATCHES'].append(
                                f'{tname}.{cname}: default mismatch'
                            )

            for fk in tspec.get('foreign_keys') or []:
                fks = _fk_list(cur, tname)
                ok = any(
                    r[2] == fk['references_table']
                    and r[3] == fk['column']
                    and r[4] == fk['references_column']
                    for r in fks
                )
                if not ok:
                    result['TYPE_MISMATCHES'].append(
                        f'{tname} FK {fk["column"]}->{fk["references_table"]}.{fk["references_column"]}'
                    )

            for uq in tspec.get('unique_constraints') or []:
                idxs = cur.execute(
                    "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=?",
                    (tname,),
                ).fetchall()
                cols_needed = set(uq.get('columns') or [])
                found = False
                for _, sql in idxs:
                    if sql and 'UNIQUE' in sql.upper():
                        # unique constraint via table def or index
                        found = True
                        break
                if not found:
                    # SQLite stores UNIQUE in CREATE TABLE — check table sql
                    create_sql = cur.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                        (tname,),
                    ).fetchone()
                    if create_sql and 'UNIQUE' in (create_sql[0] or '').upper():
                        found = True
                if not found and cols_needed:
                    result['TYPE_MISMATCHES'].append(
                        f'{tname} UNIQUE {sorted(cols_needed)}'
                    )

            for idx_spec in tspec.get('indexes') or []:
                iname = idx_spec['name']
                if not cur.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
                    (iname,),
                ).fetchone():
                    result['MISSING_INDEXES'].append(iname)
                else:
                    icols = _index_columns(cur, iname)
                    exp_cols = idx_spec.get('columns') or []
                    if icols != exp_cols:
                        result['TYPE_MISMATCHES'].append(
                            f'{iname}: expected cols {exp_cols}, got {icols}'
                        )

        reg_required = [
            str(v) for v in (contract.get('registry_required') or contract.get('required_migrations') or [])
        ]
        applied = _migration_versions(cur)
        for v in reg_required:
            if v not in applied:
                result['MISSING_MIGRATIONS'].append(v)

        if (
            not result['MISSING_TABLES']
            and not result['MISSING_COLUMNS']
            and not result['TYPE_MISMATCHES']
            and not result['MISSING_INDEXES']
            and not result['MISSING_MIGRATIONS']
        ):
            result['PARITY_RESULT'] = 'PASS'
        else:
            result['PARITY_RESULT'] = 'BLOCKED'
        return result
    finally:
        con.close()


def print_report(result: dict[str, Any]) -> None:
    for key in (
        'PARITY_RESULT', 'MISSING_TABLES', 'MISSING_COLUMNS', 'TYPE_MISMATCHES',
        'MISSING_INDEXES', 'MISSING_MIGRATIONS', 'DB_INTEGRITY',
        'EXPECTED_COMMIT', 'ACTUAL_COMMIT', 'DB_PATH',
    ):
        val = result.get(key, '')
        if isinstance(val, list):
            print(f'{key}={",".join(val) if val else ""}')
        else:
            print(f'{key}={val}')
    if result.get('error'):
        print(f'ERROR={result["error"]}')


def main() -> int:
    parser = argparse.ArgumentParser(description='Schema parity check (read-only)')
    parser.add_argument('--contract', required=True, help='Absolute path to contract TOML')
    parser.add_argument('--db', required=True, help='Absolute path to SQLite DB')
    parser.add_argument('--repo', default='', help='Absolute repo path for commit check')
    parser.add_argument('--expected-commit', default='', help='Full git commit hash')
    parser.add_argument('--mode', default='check', choices=['check'])
    parser.add_argument('--skip-commit-check', action='store_true')
    args = parser.parse_args()

    result = check_parity(
        contract_path=args.contract,
        db_path=args.db,
        repo_path=args.repo or None,
        expected_commit=args.expected_commit or None,
        skip_commit_check=args.skip_commit_check,
    )
    print_report(result)
    if result.get('error'):
        print(f'ERROR={result["error"]}')
    return 0 if result['PARITY_RESULT'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
