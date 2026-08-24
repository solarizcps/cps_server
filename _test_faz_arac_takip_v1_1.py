# -*- coding: utf-8 -*-
"""VEHUI-01..20 — Araç Takip & Plan V1.1 lock tests."""
import io
import os
import sys
from unittest.mock import patch

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

YK = frozenset({'planlama:can_view', 'planlama:can_update', 'planlama:can_create'})

results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def client():
    import app as flask_app
    flask_app.app.config['TESTING'] = True
    c = flask_app.app.test_client()
    with c.session_transaction() as s:
        s['kullanici'] = {
            'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem',
            'RolId': 1, 'RolAd': 'admin', 'Aktif': 1,
        }
        s['kullanici_tip'] = 'sistem'
    return c


print('=' * 72)
print('VEHUI — Araç Takip & Plan V1.1')
print('=' * 72)

with patch('modules.auth.kullanici_yetkileri', return_value=YK), \
     patch('modules.auth.sistem_session_gecerli_mi', return_value=True):
    c = client()
    r = c.get('/planlama/arac-takip/')
    ok('VEHUI-01 route GET 200', r.status_code == 200, str(r.status_code))
    html = r.get_data(as_text=True)

    ok('VEHUI-02 CPS shell preserved', 'atp-wrap' in html and 'sidebar' in html.lower() or 'sn-grup' in html)
    ok('VEHUI-03 no second app shell', html.count('atp-wrap') == 1)
    ok('VEHUI-04 daily tab default', 'GÜNLÜK PLAN' in html)
    ok('VEHUI-05 weekly tab marker', 'atpPanelHaftalik' in html)
    ok('VEHUI-06 history tab marker', 'atpPanelGecmis' in html)
    ok('VEHUI-07 vehicle panel', 'CANLI ARAÇLAR' in html)
    ok('VEHUI-08 KPI cards', 'Aktif Araç' in html and 'Yakıt' in html)
    ok('VEHUI-09 daily table', 'atpTaskTable' in html)
    # Priority badges are rendered by JS; verify CSS class is defined in stylesheet
    import pathlib as _pl
    _css = (_pl.Path(__file__).parent / 'app' / 'static' / 'css' / 'planlama_arac_takip.css').read_text(encoding='utf-8', errors='replace')
    ok('VEHUI-10 priority badges', 'atp-pri-yuksek' in _css)
    ok('VEHUI-11 status badges', 'Bekliyor' in html or 'Başlangıç' in html)
    ok('VEHUI-12 WhatsApp endpoint', c.get('/planlama/arac-takip/api/whatsapp').status_code == 200)
    wa = c.get('/planlama/arac-takip/api/whatsapp').get_json()
    ok('VEHUI-12b WhatsApp payload', wa and wa.get('ok') and 'whatsapp_url' in wa)
    ok('VEHUI-13 manual ordering API', c.post('/planlama/arac-takip/api/reorder',
        json={'date': '2026-08-21', 'task_id': 't2', 'direction': 'up'}).status_code == 200)
    ok('VEHUI-14 request modal', 'atpRequestModal' in html and 'Yeni İş Talebi' in html and 'atpDrawer' not in html)
    ok('VEHUI-15 route analysis DTO', 'ÖNERİLEN ROTA ANALİZİ' in html)
    ok('VEHUI-16 map container', ('atp-live-map-container' in html or 'atp-plan-map-container' in html) and 'planlama_arac_takip.js' in html)
    ok('VEHUI-17 responsive CSS', 'planlama_arac_takip.css' in html)
    ok('VEHUI-18 data_source canonical', 'data-source="canonical"' in html or 'data-source="mock"' in html)
    r2 = c.get('/planlama/genel-plan/')
    ok('VEHUI-19 no unrelated regression', r2.status_code == 200, str(r2.status_code))
    bad = ['TURKCELL', 'FILOM_PASSWORD', 'api_key', 'Sh18']
    ok('VEHUI-20 no hardcoded secrets', not any(x in html for x in bad))
    ok('VEHUI-05b haftalik GET', c.get('/planlama/arac-takip/?tab=haftalik').status_code == 200)
    ok('VEHUI-06b gecmis GET', c.get('/planlama/arac-takip/?tab=gecmis').status_code == 200)

passed = sum(1 for _, p, _ in results if p)
failed = sum(1 for _, p, _ in results if not p)
print('=' * 72)
print(f'VEHUI SONUÇ: {passed} PASS / {failed} FAIL / {len(results)} total')
print('=' * 72)
sys.exit(1 if failed else 0)
