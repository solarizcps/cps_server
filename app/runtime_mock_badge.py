# -*- coding: utf-8 -*-
"""UI-only flag: when to show the header MOCK badge (not DB connection mode)."""
from __future__ import annotations

import os
from typing import Mapping


def compute_show_mock_badge(environ: Mapping[str, str] | None = None) -> bool:
    """True when running against an explicit temp DB or test guard is active.

    Production canonical (no CPS_MOCK_DB_PATH, CPS_TEST_DB_GUARD off) → False.
    """
    env = environ if environ is not None else os.environ
    if (env.get('CPS_MOCK_DB_PATH') or '').strip():
        return True
    return (env.get('CPS_TEST_DB_GUARD') or '').strip() == '1'
