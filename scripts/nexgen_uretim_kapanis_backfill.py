# -*- coding: utf-8 -*-
"""Launcher — asıl araç: app/tools/nexgen_uretim_kapanis_backfill.py"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "app" / "tools" / "nexgen_uretim_kapanis_backfill.py"
sys.argv[0] = str(TARGET)
runpy.run_path(str(TARGET), run_name="__main__")
