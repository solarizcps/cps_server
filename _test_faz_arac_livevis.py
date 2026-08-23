# -*- coding: utf-8 -*-
"""LIVEVIS-01..07 — Live map loading + roundtrip."""
from __future__ import annotations

import io
import os
import sys

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

results: list[tuple[str, bool, str]] = []


def ok(name: str, cond: bool, detail: str = '') -> None:
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))

js = open(os.path.join(_APP, 'static', 'js', 'planlama_arac_takip.js'), encoding='utf-8').read()
ok('LIVEVIS-01 loading resolves helper', 'liveFetchState' in js and 'LIVE_FETCH_TIMEOUT_MS' in js)
ok('LIVEVIS-02 renderLiveVehicles no tab guard', 'if (currentTab !== \'canli\') return;' not in js.split('function renderLiveVehicles')[1].split('function bindVehiclePanelClicks')[0])
ok('LIVEVIS-03 canli tab reload', 'atp-live-loading' in js and 'loadLiveVehicles(false)' in js)
ok('LIVEVIS-05 failure exits loading', 'atp-live-error' in js and 'showLiveError' in js)
ok('LIVEVIS-06 live map isolated', 'atpLeafletMap' in open(os.path.join(_APP, 'static', 'js', 'planlama_arac_takip_map.js'), encoding='utf-8').read())
ok('LIVEVIS-07 plan map isolated', 'atpPlanLeafletMap' in open(os.path.join(_APP, 'static', 'js', 'planlama_arac_takip_plan_map.js'), encoding='utf-8').read())

passed = sum(1 for _, c, _ in results if c)
print(f'LIVEVIS static: {passed}/{len(results)} PASS')
if passed != len(results):
    sys.exit(1)
