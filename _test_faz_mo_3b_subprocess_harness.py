# -*- coding: utf-8 -*-
"""MO 3B test paketlerini ayrı süreçlerde ve izole SQLite kopyalarında çalıştırır."""
from __future__ import annotations

import argparse
import ast
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys


REPO = Path(__file__).resolve().parent
MAIN_DB = REPO / "app" / "mock_data.db"
EXPECTED_MAIN_SHA256 = "AF3262FBA5E04A2B98FC12E3F990F5A481E9F6E9E68250056C7AEFA7C4C7AB60"
DB_ASSIGNMENT = "DB = os.path.join(APP, 'mock_data.db')"
SAFE_ORDER_MESSAGE = "Sipari\u015f d\u00f6n\u00fc\u015f\u00fcm\u00fc tamamlanamad\u0131."
SAFE_SAMPLE_MESSAGE = "Numune d\u00f6n\u00fc\u015f\u00fcm\u00fc tamamlanamad\u0131."


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _main_facts() -> tuple[str, int, int]:
    stat = MAIN_DB.stat()
    return _sha256(MAIN_DB), stat.st_size, stat.st_mtime_ns


def _backup(source: Path, target: Path) -> None:
    source_con = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
    try:
        target_con = sqlite3.connect(str(target))
        try:
            source_con.backup(target_con)
        finally:
            target_con.close()
    finally:
        source_con.close()


def _assert_safe_error_contract() -> None:
    service = REPO / "app" / "modules" / "nexgen" / "mtt_donusum_service.py"
    source = service.read_text(encoding="utf-8")
    tree = ast.parse(source)
    messages = {
        node.exc.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and getattr(node.exc.func, "id", None) == "MusteriTemsilcisiTalepError"
        and node.exc.args
        and isinstance(node.exc.args[0], ast.Constant)
        and isinstance(node.exc.args[0].value, str)
    }
    if SAFE_ORDER_MESSAGE not in messages or SAFE_SAMPLE_MESSAGE not in messages:
        raise RuntimeError("Güvenli dönüşüm hata mesajı sözleşmesi değişti")
    if "MusteriTemsilcisiTalepError(str(e), 500)" in source:
        raise RuntimeError("Ham exception mesajı dış sözleşmeye sızıyor")
    if source.count("logger.exception(") != 2:
        raise RuntimeError("Beklenen iki logger.exception çağrısı bulunamadı")


def _run_case(test_file: Path, case_db: Path) -> int:
    source = test_file.read_text(encoding="utf-8")
    if source.count(DB_ASSIGNMENT) != 1:
        raise RuntimeError(f"Beklenen tek DB sabiti bulunamadı: {test_file}")
    source = source.replace(DB_ASSIGNMENT, "DB = os.environ['MO3B_CASE_DB']")
    if DB_ASSIGNMENT in source:
        raise RuntimeError(f"Ana DB sabiti kaynakta kaldı: {test_file}")
    if Path(os.environ["MO3B_CASE_DB"]).resolve() != case_db.resolve():
        raise RuntimeError("İzole DB environment doğrulaması başarısız")

    namespace = {"__name__": "__main__", "__file__": str(test_file)}
    try:
        exec(compile(source, str(test_file), "exec"), namespace, namespace)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _run_one(python_exe: Path, test_file: Path, base_db: Path, work_dir: Path) -> tuple[int, str, str]:
    case_db = work_dir / f"case_{test_file.stem}.db"
    if case_db.exists():
        case_db.unlink()
    _backup(base_db, case_db)

    before = _main_facts()
    if before[0] != EXPECTED_MAIN_SHA256:
        raise RuntimeError(f"Ana DB başlangıç SHA-256 farklı: {before[0]}")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "app")
    env["PYTHONIOENCODING"] = "utf-8"
    env["MO3B_CASE_DB"] = str(case_db)
    command = [
        str(python_exe), str(Path(__file__).resolve()), "--case",
        str(test_file), "--case-db", str(case_db),
    ]
    completed = subprocess.run(
        command,
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    after = _main_facts()
    if after != before:
        raise RuntimeError(f"Ana DB değişti: önce={before}, sonra={after}")
    return completed.returncode, completed.stdout, completed.stderr


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case")
    parser.add_argument("--case-db")
    parser.add_argument("--python")
    parser.add_argument("--base-db")
    parser.add_argument("--work-dir")
    parser.add_argument("tests", nargs="*")
    args = parser.parse_args()

    if args.case:
        return _run_case(Path(args.case).resolve(), Path(args.case_db).resolve())

    python_exe = Path(args.python).resolve()
    base_db = Path(args.base_db).resolve()
    work_dir = Path(args.work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    _assert_safe_error_contract()
    total_pass = total_fail = total_error = 0

    for name in args.tests:
        test_file = (REPO / name).resolve()
        code, stdout, stderr = _run_one(python_exe, test_file, base_db, work_dir)
        print(f"\n===== {test_file.name} | exit={code} =====")
        print(stdout, end="")
        if stderr:
            print("--- stderr ---")
            print(stderr, end="")
        matches = re.findall(r"SONU(?:C|Ç):\s*(\d+)\s*(?:PASS|pass)\s*/\s*(\d+)\s*(?:FAIL|fail)", stdout)
        if matches:
            passed, failed = map(int, matches[-1])
            total_pass += passed
            total_fail += failed
        elif code:
            total_error += 1
        if code or total_fail or total_error:
            print(f"HARNESS_STOP pass={total_pass} fail={total_fail} error={total_error or 1}")
            return code or 1

    print(f"HARNESS_TOTAL pass={total_pass} fail={total_fail} error={total_error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
