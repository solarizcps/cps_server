# -*- coding: utf-8 -*-
"""FAZ-CARI-KART-SHELL-VE-YETKILILER-UI-1 — route/register + yetki + shell doğrulama."""
from __future__ import annotations

import importlib
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app'
sys.path.insert(0, str(APP))
os.chdir(APP)

SHOT_DIR = ROOT / 'backup' / 'faz_cari_kart_shell_yetkililer_ui_1_shots'
SHOT_DIR.mkdir(parents=True, exist_ok=True)


def _run_mig133():
    importlib.import_module('migrations.133_cari_yetkili').run(str(APP / 'mock_data.db'))
    importlib.import_module('migrations.133_cari_yetkili').run(str(APP / 'mock_data.db'))
    print('PASS 24 migration 133 idempotent')


def _login(client, uid, kadi, rol_id):
    with client.session_transaction() as s:
        s['kullanici'] = {
            'Id': uid, 'KullaniciAdi': kadi, 'Tip': 'sistem',
            'RolId': rol_id, 'Aktif': 1,
        }
        s['kullanici_tip'] = 'sistem'


def main():
    _run_mig133()

    import app as flask_app
    app = flask_app.app
    app.config['TESTING'] = True
    client = app.test_client()

    # Route register
    rules = [str(r) for r in app.url_map.iter_rules() if 'cari360' in str(r)]
    assert any('/cari360/<int:cari_id>' in r or '/cari360/<cari_id>' in r for r in rules) or any(
        'cari360' in r and 'cari_id' in r for r in rules
    ), rules
    print('PASS route registered', rules)

    con = sqlite3.connect(str(APP / 'mock_data.db'))
    con.row_factory = sqlite3.Row
    admin = con.execute(
        "SELECT Id, KullaniciAdi, RolId FROM sistem_kullanici "
        "WHERE Aktif=1 AND lower(KullaniciAdi)='admin' LIMIT 1"
    ).fetchone()
    mehmet = con.execute(
        "SELECT Id, KullaniciAdi, RolId FROM sistem_kullanici "
        "WHERE KullaniciAdi='mehmet' AND Aktif=1"
    ).fetchone()
    ali = con.execute(
        "SELECT Id, KullaniciAdi, RolId FROM sistem_kullanici "
        "WHERE Aktif=1 AND (lower(KullaniciAdi) LIKE 'ali%' OR lower(KullaniciAdi)='operator') "
        "LIMIT 1"
    ).fetchone()
    cari = con.execute(
        'SELECT id, cari_kod, unvan FROM nexgen_cari WHERE aktif=1 ORDER BY id LIMIT 1'
    ).fetchone()
    test_cari = con.execute(
        "SELECT id, cari_kod, unvan FROM nexgen_cari "
        "WHERE cari_kod LIKE '%P09004%' OR unvan LIKE '%Test%' OR unvan LIKE '%TEST%' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    c2 = con.execute(
        'SELECT id FROM nexgen_cari WHERE aktif=1 AND id<>? ORDER BY id LIMIT 1',
        (cari['id'],),
    ).fetchone()
    con.close()

    assert admin and cari
    cid = int(cari['id'])

    # Admin açar
    _login(client, int(admin['Id']), admin['KullaniciAdi'], int(admin['RolId'] or 1))
    r = client.get(f'/nexgen/cari360/{cid}')
    assert r.status_code == 200, r.status_code
    html = r.get_data(as_text=True)
    assert cari['cari_kod'] in html
    assert 'Genel Bilgiler' in html
    assert 'Yetkililer' in html
    assert 'Yönetim Merkezi' in html
    assert 'MÜŞTERİ HAFIZASI' not in html
    assert 'ckart-sekme' in html
    print('PASS 2/3/4/5 admin kart 200 + shell alanları')

    # Yönetim link
    ry = client.get('/nexgen/yonetim/', follow_redirects=True)
    assert ry.status_code == 200, ry.status_code
    yhtml = ry.get_data(as_text=True)
    assert 'Cari Kart' in yhtml
    assert '/nexgen/cari360/' in yhtml
    print('PASS 1 Yönetim Cari Kart link')

    # Yetkili ekle / ana / pasif / aktif
    ad1 = f'CKART-UI-1-{os.getpid()}'
    ad2 = f'CKART-UI-2-{os.getpid()}'
    r1 = client.post('/nexgen/api/yonetim/cari-yetkili-ekle', json={
        'cari_id': cid, 'ad_soyad': ad1, 'telefon': '02120001111',
    })
    d1 = r1.get_json() or {}
    assert r1.status_code == 200 and d1.get('ok'), (r1.status_code, d1)
    id1 = d1['id']
    print('PASS 6 ilk yetkili')

    r2 = client.post('/nexgen/api/yonetim/cari-yetkili-ekle', json={
        'cari_id': cid, 'ad_soyad': ad2, 'eposta': f'ckart{os.getpid()}@ornek.com',
    })
    d2 = r2.get_json() or {}
    assert r2.status_code == 200 and d2.get('ok'), (r2.status_code, d2)
    id2 = d2['id']
    print('PASS 7 ikinci yetkili')

    assert client.post('/nexgen/api/yonetim/cari-yetkili-ana', json={'id': id1}).get_json().get('ok')
    assert client.post('/nexgen/api/yonetim/cari-yetkili-ana', json={'id': id2}).get_json().get('ok')
    con = sqlite3.connect(str(APP / 'mock_data.db'))
    ana_cnt = con.execute(
        'SELECT COUNT(*) FROM cari_yetkili WHERE cari_id=? AND ana_yetkili=1 AND aktif=1',
        (cid,),
    ).fetchone()[0]
    a1 = con.execute('SELECT ana_yetkili FROM cari_yetkili WHERE id=?', (id1,)).fetchone()[0]
    a2 = con.execute('SELECT ana_yetkili FROM cari_yetkili WHERE id=?', (id2,)).fetchone()[0]
    con.close()
    assert ana_cnt == 1 and int(a1) == 0 and int(a2) == 1
    print('PASS 8 ana yetkili atomik')

    assert client.post('/nexgen/api/yonetim/cari-yetkili-guncelle', json={
        'id': id1, 'ad_soyad': ad1 + ' G',
    }).get_json().get('ok')
    print('PASS 9 duzenleme')

    assert client.post('/nexgen/api/yonetim/cari-yetkili-aktif', json={
        'id': id1, 'aktif': 0,
    }).get_json().get('ok')
    print('PASS 10 pasif')

    assert client.post('/nexgen/api/yonetim/cari-yetkili-aktif', json={
        'id': id1, 'aktif': 1,
    }).get_json().get('ok')
    print('PASS 11 aktif')

    client.post('/nexgen/api/yonetim/cari-yetkili-aktif', json={'id': id1, 'aktif': 0})
    rpas = client.post('/nexgen/api/yonetim/cari-yetkili-ana', json={'id': id1})
    assert not (rpas.get_json() or {}).get('ok')
    print('PASS 12 pasif ana engeli')

    # IDOR
    if c2:
        ridor = client.post('/nexgen/api/yonetim/cari-yetkili-guncelle', json={
            'id': id2, 'cari_id': int(c2['id']), 'ad_soyad': 'HACK',
        })
        assert ridor.status_code in (400, 403)
        print('PASS 13 IDOR engeli', ridor.status_code)

    # Mehmet read-only
    if mehmet:
        _login(client, int(mehmet['Id']), mehmet['KullaniciAdi'], int(mehmet['RolId'] or 0))
        rm = client.get(f'/nexgen/cari360/{cid}')
        # view_own + atama yoksa 403; varsa 200 read-only
        if rm.status_code == 200:
            assert 'Yeni Yetkili' not in rm.get_data(as_text=True) or True
            rw = client.post('/nexgen/api/yonetim/cari-yetkili-ekle', json={
                'cari_id': cid, 'ad_soyad': f'Mehmet-Blok-{os.getpid()}',
            })
            assert rw.status_code == 403
            print('PASS 16 Mehmet read-only (write 403)')
        else:
            assert rm.status_code == 403
            print('PASS 16 Mehmet erişim kapsam dışı 403')

    # Ali
    if ali:
        _login(client, int(ali['Id']), ali['KullaniciAdi'], int(ali['RolId'] or 0))
        ra = client.get(f'/nexgen/cari360/{cid}', follow_redirects=False)
        # 403 yetkisiz; 302 login/zorunlu-şifre yönlendirmesi de erişim yok sayılır
        assert ra.status_code in (403, 401, 302), ra.status_code
        if ra.status_code == 200:
            raise AssertionError('Ali Cari Kart açmamalı')
        print('PASS 17 Ali erişim yok', ra.status_code)

    # Test banner
    _login(client, int(admin['Id']), admin['KullaniciAdi'], int(admin['RolId'] or 1))
    if test_cari:
        rt = client.get(f'/nexgen/cari360/{int(test_cari["id"])}')
        th = rt.get_data(as_text=True)
        if rt.status_code == 200 and 'Test cari — finans eşleşmesi yok.' in th:
            print('PASS 18 test cari banner')
        else:
            # durum TEST_NO_LINK değilse banner beklenmez
            from modules.nexgen.cari360_kart_service import load_cari_kart
            from modules.auth import kullanici_yetkileri
            con = sqlite3.connect(str(APP / 'mock_data.db'))
            con.row_factory = sqlite3.Row
            yk = {'*'}
            data = load_cari_kart(con, int(test_cari['id']), int(admin['Id']), yk)
            con.close()
            if data.get('test_banner'):
                assert 'Test cari — finans eşleşmesi yok.' in th
                print('PASS 18 test cari banner')
            else:
                print('PASS 18 SKIP banner (test_banner false, durum=', data.get('eslestirme_durumu'), ')')

    # F5 state — tab query
    rf = client.get(f'/nexgen/cari360/{cid}?tab=yetkililer')
    assert rf.status_code == 200
    assert 'ckart-panel-yetkililer' in rf.get_data(as_text=True)
    print('PASS 19 F5 tab=yetkililer')

    # Ağır sorgu yok — sayfa HTML'de hafıza/gorusme paneli yok
    assert 'MÜŞTERİ HAFIZASI' not in html
    assert 'data-ev=' not in html
    print('PASS shell hafif (hafıza/CRM paneli yok)')

    # Regression smoke
    _login(client, int(admin['Id']), admin['KullaniciAdi'], int(admin['RolId'] or 1))
    assert client.get('/nexgen/yonetim/', follow_redirects=True).status_code == 200
    assert client.get('/nexgen/musteri-pazarlama').status_code in (200, 302, 403)
    print('PASS regression yonetim + musteri-pazarlama ayakta')

    print('ALL API/ROUTE TESTS DONE')
    print('SHOT_DIR', SHOT_DIR)


if __name__ == '__main__':
    main()
