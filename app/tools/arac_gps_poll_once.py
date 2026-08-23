# -*- coding: utf-8 -*-
"""
Araç GPS poll_once CLI — tek seferlik Filom snapshot persist.

Kullanım:
  set CPS_MOCK_DB_PATH=C:\\path\\to\\temp.db
  python app/tools/arac_gps_poll_once.py

Bu fazda scheduler'a bağlanmaz. Windows Task Scheduler worker ayrı faz.
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

CANONICAL = os.path.join(ROOT, 'mock_data.db')


def main() -> int:
    active = os.environ.get('CPS_MOCK_DB_PATH') or CANONICAL
    if os.path.normcase(os.path.normpath(active)) == os.path.normcase(os.path.normpath(CANONICAL)):
        print('STOP: CPS_MOCK_DB_PATH required — canonical DB write forbidden')
        return 2

    from modules.planlama.arac_gps_poll_service import poll_once
    result = poll_once()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
