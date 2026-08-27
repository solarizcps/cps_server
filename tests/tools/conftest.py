# -*- coding: utf-8 -*-
"""tests/tools — ensure app/ is on sys.path."""
from __future__ import annotations

import sys
from pathlib import Path

_APP = str(Path(__file__).resolve().parents[2] / 'app')
if _APP not in sys.path:
    sys.path.insert(0, _APP)
