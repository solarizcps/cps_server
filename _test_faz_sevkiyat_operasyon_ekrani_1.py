# -*- coding: utf-8 -*-
"""FAZ-SEVKIYAT-OPERASYON-EKRANI-1 — operasyon ekranı test."""
from __future__ import annotations

import hashlib
import io
import os
import sqlite3
import sys
import uuid

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'app')
DB = os.path.join(APP, 'mock_data.db')
sys.path.insert(0, APP)
os.chdir(APP)

PRE_SHA = hashlib.sha256(open(DB, 'rb').read()).hexdigest()
results: list[tuple[str, bool, str]] = []


def ok(name: str, cond: bool, detail: str = '') -> None:
    results.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f' — {detail}' if detail else ''))


def _con():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


print('=' * 72)
print('FAZ-SEVKIYAT-OPERASYON-EKRANI-1 TEST')
print('=' * 72)
print(f'PRE_SHA={PRE_SHA}')

BASE = open(os.path.join(APP, 'templates', 'base.html'), encoding='utf-8').read()
LIST = open(os.path.join(APP, 'templates', 'nexgen', 'sevkiyat.html'), encoding='utf-8').read()
DET = open(os.path.join(APP, 'templates', 'nexgen', 'sevkiyat_detay.html'), encoding='utf-8').read()

ok('E01 menu sevkiyat', 'Müşteri Sevkiyat' in BASE and '/nexgen/sevkiyat' in BASE)
ok('E02 liste sekmeler', 'Sevkiyata Hazır' in LIST and 'Hazırlananlar' in LIST and 'Yolda' in LIST)
ok('E03 kompakt tablo', 'pzm-tablo' in LIST and 'svk-tab' in LIST)
ok('E04 modal olustur', 'Sevkiyat Oluştur' in LIST and 'svkKaydet' in LIST)
ok('E05 detay termin', 'Termin karşılaştırması' in DET and 'svkdDurumKaydet' in DET)
ok('E06 operasyon servis', os.path.exists(os.path.join(APP, 'modules', 'nexgen', 'mo_sevkiyat_operasyon_service.py')))

from modules.nexgen.mo_sevkiyat_operasyon_service import (
    liste_sevkiyat_tab,
    sevkiyata_hazir_siparisler,
    siparis_sevk_form_verisi,
    termin_durum_etiket,
)

ok('E07 termin erken', termin_durum_etiket('2026-08-10', '2026-08-05') == 'Erken')
ok('E08 termin gecikme', termin_durum_etiket('2026-08-05', '2026-08-10') == 'Gecikmiş')
ok('E09 termin henuz', termin_durum_etiket('2026-08-05', None) == 'Henüz sevk edilmedi')

con = _con()
try:
    hazir = sevkiyata_hazir_siparisler(con)
    ok('E10 hazir_liste_tip', isinstance(hazir, list))
    tumu = liste_sevkiyat_tab(con, 'tumu')
    ok('E11 tumu_liste', isinstance(tumu, list))
    haz = liste_sevkiyat_tab(con, 'hazirlananlar')
    ok('E12 hazirlananlar', isinstance(haz, list))
    if hazir:
        f = siparis_sevk_form_verisi(con, int(hazir[0]['siparis_id']))
        ok('E13 form_kalemler', 'kalemler' in f and 'tahsilat' in f)
    else:
        ok('E13 form_kalemler', True, 'hazir bos — atlandi')
finally:
    con.close()

from modules.nexgen.mo_sevkiyat_service import MoSevkiyatError, sevkiyat_olustur

con = _con()
try:
    row = con.execute(
        "SELECT id FROM nexgen_planlama_siparis WHERE durum='ONAY_BEKLIYOR' LIMIT 1"
    ).fetchone()
    if row:
        try:
            sevkiyat_olustur(con, {
                'idempotency_key': f'MSV-GUARD-{uuid.uuid4().hex[:8]}',
                'siparis_id': int(row['id']),
                'kalemler': [{'miktar_kg': 1}],
            }, 1, {'*'})
            ok('E14 onay_bekliyor_engel', False, 'olusturuldu')
        except MoSevkiyatError as e:
            ok('E14 onay_bekliyor_engel', e.kod == 409, e.mesaj)
    else:
        ok('E14 onay_bekliyor_engel', True, 'ornek yok')
finally:
    con.close()

import config as _cfg
_cfg.Config.MOCK_DB_PATH = DB
import app as flask_app

_app = flask_app.app
_app.config['TESTING'] = True
client = _app.test_client()


def login_sevkiyat():
    with client.session_transaction() as s:
        s['kullanici'] = {
            'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem',
            'RolId': 1, 'RolAd': 'Admin', 'Aktif': 1,
        }
        s['kullanici_tip'] = 'sistem'
        s['yetkiler'] = {
            'nexgen.sevkiyat.view': {'can_view': True},
            'nexgen.sevkiyat.write': {'can_create': True, 'can_update': True},
        }


login_sevkiyat()
r = client.get('/nexgen/sevkiyat')
ok('E15 sayfa 200', r.status_code == 200, str(r.status_code))
r2 = client.get('/nexgen/api/sevkiyat-operasyon/liste?tab=hazir')
ok('E16 api liste', r2.status_code == 200 and r2.get_json().get('ok'), str(r2.status_code))

with client.session_transaction() as s:
    s.clear()
r3 = client.get('/nexgen/sevkiyat')
ok('E17 yetkisiz', r3.status_code in (302, 401, 403), str(r3.status_code))

POST_SHA = hashlib.sha256(open(DB, 'rb').read()).hexdigest()
fail = [n for n, c, _ in results if not c]
print('=' * 72)
print(f'SONUC: {len(results) - len(fail)}/{len(results)} PASS')
print(f'POST_SHA={POST_SHA}')
print(f'DB_DEGISIM={PRE_SHA != POST_SHA}')
if fail:
    print('FAIL:', ', '.join(fail))
    sys.exit(1)
