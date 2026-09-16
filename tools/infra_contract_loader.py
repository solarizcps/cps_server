# -*- coding: utf-8 -*-
"""Load module schema contracts (TOML) — read-only metadata."""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


def load_contract(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f'Contract not found: {p}')
    with p.open('rb') as f:
        return tomllib.load(f)


def contract_tables(contract: dict[str, Any]) -> list[dict[str, Any]]:
    return contract.get('tables') or []


def table_spec(contract: dict[str, Any], name: str) -> dict[str, Any] | None:
    for t in contract_tables(contract):
        if t.get('name') == name:
            return t
    return None
