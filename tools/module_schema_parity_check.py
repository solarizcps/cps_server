"""
tools/module_schema_parity_check.py
====================================
Salt-okunur modül bazlı şema parity kontrolü.
Her modül TOML sözleşmesini canonical DB ile karşılaştırır.

Kullanım:
    python tools/module_schema_parity_check.py --db <path> [--module <name>]

Çıktı:
    Her modül için PASS / BLOCKED / PARTIAL satırı.
    Eğer herhangi bir modül BLOCKED ise çıkış kodu 1.

YASAK: Bu script canonical DB'ye HİÇBİR YAZI yapmaz.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import tomllib
from pathlib import Path

CONTRACTS_DIR = Path(__file__).parent / "module_schema_contracts"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_contract(path: Path) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def _db_tables(con: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _db_columns(con: sqlite3.Connection, table: str) -> dict[str, dict]:
    """name → {type, not_null, dflt_value}"""
    result = {}
    for row in con.execute(f"PRAGMA table_info({table})").fetchall():
        _, name, typ, notnull, dflt, _ = row
        result[name] = {"type": (typ or "").upper(), "not_null": bool(notnull), "dflt_value": dflt}
    return result


def _db_indexes(con: sqlite3.Connection, table: str) -> set[str]:
    return {
        r[1]
        for r in con.execute(
            f"SELECT * FROM sqlite_master WHERE type='index' AND tbl_name='{table}'"
        ).fetchall()
    }


def _applied_migrations(con: sqlite3.Connection) -> set[str]:
    try:
        return {
            r[0]
            for r in con.execute(
                "SELECT version FROM schema_migrations"
            ).fetchall()
        }
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Core parity logic
# ---------------------------------------------------------------------------

def check_module(contract: dict, con: sqlite3.Connection) -> dict:
    """
    Returns:
        {
            "module": str,
            "status": "PASS" | "BLOCKED" | "PARTIAL",
            "errors": [...],
            "warnings": [...],
        }
    """
    module_name = contract.get("module", "unknown")
    errors: list[str] = []
    warnings: list[str] = []

    # Known blockers declared in the contract
    for b in contract.get("known_blockers", []):
        errors.append(f"KNOWN_BLOCKER: {b}")

    existing_tables = _db_tables(con)
    applied = _applied_migrations(con)

    # Check required migrations
    for mig in contract.get("required_migrations", []):
        if mig not in applied:
            errors.append(f"MISSING_MIGRATION: {mig}")

    # Check tables
    for tbl_spec in contract.get("tables", []):
        tbl_name = tbl_spec["name"]
        if tbl_name not in existing_tables:
            errors.append(f"MISSING_TABLE: {tbl_name}")
            continue

        db_cols = _db_columns(con, tbl_name)
        db_idxs = _db_indexes(con, tbl_name)

        for col_spec in tbl_spec.get("columns", []):
            col_name = col_spec["name"]
            if col_name not in db_cols:
                errors.append(f"MISSING_COLUMN: {tbl_name}.{col_name}")
                continue
            # Type check (loose — SQLite is type-affinity)
            spec_type = col_spec.get("type", "").upper()
            db_type = db_cols[col_name]["type"]
            if spec_type and spec_type not in db_type and db_type not in spec_type:
                warnings.append(
                    f"TYPE_MISMATCH: {tbl_name}.{col_name} "
                    f"contract={spec_type} db={db_type}"
                )
            # not_null check
            if col_spec.get("not_null", False) and not db_cols[col_name]["not_null"]:
                warnings.append(
                    f"NULLABLE_MISMATCH: {tbl_name}.{col_name} "
                    "contract=not_null db=nullable"
                )

        for idx_spec in tbl_spec.get("indexes", []):
            idx_name = idx_spec["name"]
            if idx_name not in db_idxs:
                errors.append(f"MISSING_INDEX: {tbl_name}.{idx_name}")

    # Determine status
    parity_declared = contract.get("parity_status")
    if parity_declared == "PARTIAL":
        status = "PARTIAL"
        warnings.append(contract.get("parity_note", "parity_status=PARTIAL declared in contract"))
    elif errors:
        status = "BLOCKED"
    else:
        status = "PASS"

    return {
        "module": module_name,
        "status": status,
        "errors": errors,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def check_contract_file(
    contract_path: str | Path,
    db_path: str | Path,
    *,
    manifest_module: str | None = None,
) -> dict:
    """
    Orchestrator entry: compare one contract file against a DB (read-only).

    Returns dict with PARITY_RESULT in PASS / BLOCKED / PARTIAL and MODULE name.
    """
    contract_path = Path(contract_path)
    db_path = Path(db_path)
    result: dict = {
        'PARITY_RESULT': 'BLOCKED',
        'MODULE': '',
        'ERRORS': [],
        'WARNINGS': [],
        'error': '',
    }

    if not contract_path.is_file():
        result['error'] = f'contract not found: {contract_path}'
        return result
    if not db_path.is_file():
        result['error'] = f'db not found: {db_path}'
        return result
    if db_path.stat().st_size == 0:
        result['error'] = 'db is zero bytes'
        return result

    contract = _load_contract(contract_path)
    contract_module = contract.get('module', contract_path.stem)
    result['MODULE'] = contract_module

    if manifest_module and contract_module != manifest_module:
        result['error'] = (
            f'module mismatch: manifest={manifest_module!r} contract={contract_module!r}'
        )
        result['ERRORS'] = [result['error']]
        return result

    con = sqlite3.connect(f'file:{db_path.as_posix()}?mode=ro', uri=True)
    try:
        ic = con.execute('PRAGMA integrity_check').fetchone()[0]
        if ic != 'ok':
            result['error'] = f'integrity_check={ic}'
            return result
        mod_result = check_module(contract, con)
    finally:
        con.close()

    result['ERRORS'] = mod_result['errors']
    result['WARNINGS'] = mod_result['warnings']
    status = mod_result['status']
    if status == 'PASS':
        result['PARITY_RESULT'] = 'PASS'
    elif status == 'PARTIAL':
        result['PARITY_RESULT'] = 'PARTIAL'
    else:
        result['PARITY_RESULT'] = 'BLOCKED'
    return result


def run_module_parity(
    db_path: Path,
    module_filter: str | None = None,
) -> list[dict]:
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")

    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        contract_files = sorted(CONTRACTS_DIR.glob("*.toml"))
        if not contract_files:
            raise RuntimeError(f"No contract files found in {CONTRACTS_DIR}")

        results = []
        for cf in contract_files:
            contract = _load_contract(cf)
            mod = contract.get("module", cf.stem)
            if module_filter and module_filter not in (mod, cf.stem):
                continue
            result = check_module(contract, con)
            results.append(result)
        return results
    finally:
        con.close()


def _print_results(results: list[dict]) -> int:
    any_blocked = False
    for r in results:
        status = r["status"]
        print(f"MODULE={r['module']} STATUS={status}")
        for e in r["errors"]:
            print(f"  ERROR: {e}")
        for w in r["warnings"]:
            print(f"  WARN:  {w}")
        if status == "BLOCKED":
            any_blocked = True
    return 1 if any_blocked else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Module schema parity check")
    parser.add_argument("--db", required=True, help="Path to SQLite DB (read-only)")
    parser.add_argument("--module", default=None, help="Filter to single module name")
    args = parser.parse_args(argv)

    results = run_module_parity(Path(args.db), args.module)
    return _print_results(results)


if __name__ == "__main__":
    sys.exit(main())
