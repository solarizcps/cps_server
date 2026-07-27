# -*- coding: utf-8 -*-
"""FAZ-CARI-GORUSME browser smoke — screenshots + HTTP matrix."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app'
BASE = os.environ.get('CPS_BASE_URL', 'http://127.0.0.1:8080')
OUT = ROOT / 'backup' / f'faz_cari_gorusme_crm1_shots_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
OUT.mkdir(parents=True, exist_ok=True)


def pwd(user: str) -> str:
    con = sqlite3.connect(str(APP / 'mock_data.db'))
    row = con.execute(
        'SELECT Sifre FROM sistem_kullanici WHERE KullaniciAdi=? AND Aktif=1', (user,)
    ).fetchone()
    con.close()
    return row[0]


def login(user: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f'{BASE}/giris', data={'kullanici': user, 'sifre': pwd(user)}, timeout=20)
    r.raise_for_status()
    return s


def main():
    results = []
    con = sqlite3.connect(str(APP / 'mock_data.db'))
    cari_id = con.execute('SELECT id FROM nexgen_cari WHERE aktif=1 ORDER BY id LIMIT 1').fetchone()[0]
    yet = con.execute(
        'SELECT id FROM cari_yetkili WHERE cari_id=? AND aktif=1 ORDER BY id LIMIT 1', (cari_id,)
    ).fetchone()
    yetkili_id = yet[0] if yet else None
    con.close()

    admin = login('admin')
    r = admin.get(f'{BASE}/nexgen/musteri-pazarlama', timeout=20)
    results.append({'t': '1 Admin MP', 'ok': r.status_code == 200, 'code': r.status_code})
    (OUT / '01_admin_mp.html').write_text(r.text, encoding='utf-8')

    if yetkili_id:
        yl = admin.get(
            f'{BASE}/nexgen/api/yonetim/cari-yetkili?cari_id={cari_id}&aktif=1', timeout=15
        ).json()
        ids = [y['id'] for y in yl.get('yetkililer') or []]
        results.append({'t': '2 aktif yetkililer', 'ok': yl.get('ok') and yetkili_id in ids})

    import uuid
    idem = f'CRM1-BR-{uuid.uuid4()}'
    payload = {
        'cari_id': cari_id,
        'yetkili_id': yetkili_id,
        'gorusme_tipi': 'Telefon',
        'sonuc_tipi': 'Genel Görüşme',
        'konu': 'Browser CRM1',
        'kisa_not': 'Browser smoke gorusme kaydi',
        'sonraki_aksiyon': 'Kontrol et',
        'sonraki_takip_tarihi': '2026-08-10',
        'gorusme_tarihi': '2026-07-27 16:00:00',
        'idempotency_key': idem,
    }
    cr = admin.post(f'{BASE}/nexgen/api/musteri-pazarlama/gorusme', json=payload, timeout=20)
    cj = cr.json()
    gid = (cj.get('kayit') or {}).get('id')
    results.append({'t': '4 yeni gorusme', 'ok': cr.status_code == 200 and cj.get('ok'), 'gid': gid})

    lst_ck = admin.get(f'{BASE}/nexgen/api/cari360/{cari_id}/gorusme', timeout=15).json()
    ids = [x['id'] for x in lst_ck.get('liste') or []]
    results.append({'t': '5 CK listede', 'ok': gid in ids})

    page = admin.get(f'{BASE}/nexgen/cari360/{cari_id}?tab=gorusmeler', timeout=20)
    results.append({'t': 'CK sayfa', 'ok': page.status_code == 200 and 'Görüşmeler' in page.text})
    (OUT / '05_cari_kart_gorusmeler.html').write_text(page.text, encoding='utf-8')

    idem2 = f'CRM1-BRCK-{uuid.uuid4()}'
    cr2 = admin.post(f'{BASE}/nexgen/api/cari360/{cari_id}/gorusme', json={
        **payload, 'idempotency_key': idem2, 'kisa_not': 'CK browser kayit',
        'kaynak': 'CARI_KART',
    }, timeout=20)
    j2 = cr2.json()
    gid2 = (j2.get('kayit') or {}).get('id')
    results.append({'t': '6 CK create', 'ok': cr2.status_code == 200 and j2.get('ok')})

    lst_mp = admin.get(
        f'{BASE}/nexgen/api/musteri-pazarlama/gorusme?cari_id={cari_id}', timeout=15
    ).json()
    ids_mp = [x['id'] for x in lst_mp.get('liste') or []]
    results.append({'t': '7 MP listede', 'ok': gid2 in ids_mp})

    con = sqlite3.connect(str(APP / 'mock_data.db'))
    cnt = con.execute(
        'SELECT COUNT(*) FROM musteri_operasyon_gorusme WHERE idempotency_key IN (?,?)',
        (idem, idem2),
    ).fetchone()[0]
    results.append({'t': '8 tek DB satir x2', 'ok': cnt == 2, 'cnt': cnt})

    mehmet = login('mehmet')
    mw = mehmet.post(f'{BASE}/nexgen/api/musteri-pazarlama/gorusme', json={
        **payload, 'idempotency_key': f'CRM1-BRMEH-{uuid.uuid4()}',
        'kisa_not': 'mehmet browser yazma',
    }, timeout=20)
    results.append({'t': '15 Mehmet 403', 'ok': mw.status_code == 403})
    mr = mehmet.get(f'{BASE}/nexgen/api/cari360/{cari_id}/gorusme', timeout=15)
    mj = mr.json()
    results.append({'t': '14 Mehmet RO', 'ok': mr.status_code == 200 and mj.get('can_write') is False})

    ali = login('ali')
    ar = ali.get(f'{BASE}/nexgen/musteri-pazarlama', timeout=15, allow_redirects=False)
    results.append({'t': '16 Ali engel', 'ok': ar.status_code in (302, 403, 401)})

    # cleanup
    con.execute(
        "DELETE FROM musteri_operasyon_gorusme WHERE idempotency_key LIKE 'CRM1-BR%'"
    )
    con.commit()
    con.close()

    passed = sum(1 for x in results if x.get('ok'))
    summary = {'passed': passed, 'total': len(results), 'results': results, 'out': str(OUT)}
    (OUT / 'results.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    raise SystemExit(0 if passed == len(results) else 1)


if __name__ == '__main__':
    main()
