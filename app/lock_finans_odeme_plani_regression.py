# -*- coding: utf-8 -*-
"""
LOCK-FIN-ODEME — Ödeme Planı P1 + P2 + P3A kalıcı regression.

Write testleri yalnız TEMP DB kopyasında çalışır.
Canonical app/mock_data.db SHA before == after zorunlu.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CANONICAL_DB = os.path.join(APP_DIR, 'mock_data.db')
ADAPTER_PATH = os.path.join(APP_DIR, 'modules', 'finans', 'services', 'korgun_finance_adapter.py')
IBRAHIM_ID = 36

os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)

results: list[tuple[str, bool, str]] = []


def record(lock_id: str, ok: bool, detail: str = '') -> None:
    results.append((lock_id, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {lock_id}: {detail}")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def get_app():
    try:
        from app import create_app
        return create_app()
    except ImportError:
        import app as app_mod
        return app_mod.app


def login_as(client, username: str, db_path: str):
    with client.session_transaction() as sess:
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        row = con.execute(
            """
            SELECT k.Id, k.KullaniciAdi, k.AdSoyad, k.RolId, k.Aktif,
                   k.ZorunluSifreDegistir, k.AuthVersion, r.Ad AS RolAd
            FROM sistem_kullanici k
            LEFT JOIN sistem_rol r ON r.Id = k.RolId
            WHERE k.KullaniciAdi=? AND k.Aktif=1
            """,
            (username,),
        ).fetchone()
        con.close()
        if not row:
            raise RuntimeError(f'user not found: {username}')
        sess['kullanici'] = {
            'Id': row['Id'], 'KullaniciAdi': row['KullaniciAdi'],
            'AdSoyad': row['AdSoyad'], 'RolId': row['RolId'], 'RolAd': row['RolAd'],
            'Aktif': row['Aktif'], 'ZorunluSifreDegistir': row['ZorunluSifreDegistir'],
            'AuthVersion': row['AuthVersion'], 'Tip': 'sistem',
        }


def pick_pilot_cari(db_path: str) -> tuple[str, str, str]:
    os.environ['CPS_MOCK_DB_PATH'] = db_path
    import config
    config.Config.MOCK_DB_PATH = db_path
    from modules.finans.services.korgun_finance_adapter import KorgunFinanceAdapter
    rows = KorgunFinanceAdapter().fetch_supplier_balances(locations=['YP001'], positive_only=True)
    if not rows:
        raise RuntimeError('Pilot cari bulunamadi')
    r = rows[0]
    return r.location, r.cari_kod, r.cari_adi


def main() -> int:
    sha_before = sha256(CANONICAL_DB)
    record('CANONICAL_SHA_BEFORE', True, sha_before)

    temp_dir = tempfile.mkdtemp(prefix='lock_odeme_')
    temp_db = os.path.join(temp_dir, 'mock_data.lock.db')
    shutil.copy2(CANONICAL_DB, temp_db)
    os.environ['CPS_MOCK_DB_PATH'] = temp_db
    import config
    config.Config.MOCK_DB_PATH = temp_db

    from modules.finans.services.korgun_finance_adapter import (
        CANONICAL_LOCATION_CODES,
        KorgunFinanceAdapter,
    )
    from modules.finans.services.odeme_plani_service import odeme_plani_sayfa_verisi_safe
    from modules.finans.services import odeme_plani_ops_service as ops
    from modules.finans.services.odeme_plani_yetki import (
        can_odeme_plani_view, can_odeme_plani_write,
    )

    application = get_app()
    adapter = KorgunFinanceAdapter()

    # LOCK-FIN-ODEME-01 — company isolation
    record('LOCK-FIN-ODEME-01a', CANONICAL_LOCATION_CODES == ('YN001', 'SA001', 'YP001'), str(CANONICAL_LOCATION_CODES))
    all_data = odeme_plani_sayfa_verisi_safe()
    for code, label in (('YN001', 'NexGen'), ('SA001', 'Sahin Taban'), ('YP001', 'Pera')):
        d = odeme_plani_sayfa_verisi_safe(location_filter=code, active_tab='cariler')
        rows = d.get('cari_rows', [])
        locs = {r.get('location') for r in rows if r.get('location')}
        ok = len(locs) <= 1 and (not locs or locs == {code})
        record(f'LOCK-FIN-ODEME-01-{code}', ok, f'{label} rows={len(rows)} locs={sorted(locs)}')

    loc, ckod, cadi = pick_pilot_cari(temp_db)
    record('LOCK-FIN-ODEME-02-pilot', True, f'{loc}|{ckod}')

    # LOCK-FIN-ODEME-03 — Korgun READ-ONLY
    src = open(ADAPTER_PATH, encoding='utf-8').read()
    src_no_doc = re.sub(r'"""[\s\S]*?"""', '', src)
    writes = len(re.findall(r'\b(INSERT|UPDATE|DELETE)\b', src_no_doc, re.I))
    record('LOCK-FIN-ODEME-03', writes == 0, f'adapter_writes={writes}')

    # LOCK-FIN-ODEME-04 / 05 — KPI semantics
    kpi = all_data.get('kpi', {})
    record('LOCK-FIN-ODEME-04', kpi.get('toplam_acik_borc', {}).get('source') == 'CariBakiye',
           kpi.get('toplam_acik_borc', {}).get('source', ''))
    record('LOCK-FIN-ODEME-05', kpi.get('vadesi_gecmis', {}).get('source') == 'cek_Kart',
           kpi.get('vadesi_gecmis', {}).get('source', ''))

    # LOCK-FIN-ODEME-06 — Odeme Sozu (temp DB writes)
    con = sqlite3.connect(temp_db)
    soz_before = con.execute('SELECT COUNT(*) FROM finans_odeme_plani_sozu').fetchone()[0]
    r_soz = ops.create_soz({
        'location': loc, 'cari_kod': ckod, 'cari_adi_snapshot': cadi,
        'promise_date': '2026-08-28', 'amount': 500000, 'currency': 'TRY',
        'note': 'LOCK regression',
    }, 'admin')
    soz_after = con.execute('SELECT COUNT(*) FROM finans_odeme_plani_sozu').fetchone()[0]
    row = con.execute(
        'SELECT location, cari_kod FROM finans_odeme_plani_sozu WHERE Id=?', (r_soz['id'],),
    ).fetchone()
    record('LOCK-FIN-ODEME-06-create', r_soz.get('ok') and soz_after == soz_before + 1, f"id={r_soz.get('id')}")
    record('LOCK-FIN-ODEME-06-canonical', row and row[0] == loc and row[1] == ckod, str(row))
    ng = odeme_plani_sayfa_verisi_safe(location_filter='YN001', active_tab='odeme_sozleri')
    iso = not any(x['cari_kod'] == ckod for x in ng.get('soz_rows', []))
    record('LOCK-FIN-ODEME-06-isolation', iso, f'yn001_soz={len(ng.get("soz_rows", []))}')
    cari = odeme_plani_sayfa_verisi_safe(location_filter=loc, active_tab='cariler')
    match = next((x for x in cari['cari_rows'] if x['cari_kod'] == ckod), None)
    t_parity = match and '28.08.2026' in match['son_odeme_sozu'] and '500' in match['son_odeme_sozu']
    record('LOCK-FIN-ODEME-06-parity', bool(t_parity), match['son_odeme_sozu'] if match else 'no row')
    with application.test_client() as client:
        login_as(client, 'admin', temp_db)
        html = client.get(f'/finans/odeme-plani?sekme=odeme_sozleri&sirket={loc}').get_data(as_text=True)
        record('LOCK-FIN-ODEME-06-persist', ckod in html and '500' in html, 'reload ok')

    # LOCK-FIN-ODEME-07 — Aradi / Odeme Sordu
    ilet_before = con.execute('SELECT COUNT(*) FROM finans_odeme_plani_iletisim').fetchone()[0]
    r_ilet = ops.create_iletisim({
        'location': loc, 'cari_kod': ckod, 'cari_adi_snapshot': cadi,
        'contact_at': '2026-08-20', 'contact_person': 'LOCK', 'note': 'Odeme tarihini sordu',
    }, 'admin')
    ilet_after = con.execute('SELECT COUNT(*) FROM finans_odeme_plani_iletisim').fetchone()[0]
    irow = con.execute(
        'SELECT location, cari_kod, note FROM finans_odeme_plani_iletisim WHERE Id=?', (r_ilet['id'],),
    ).fetchone()
    record('LOCK-FIN-ODEME-07-create', r_ilet.get('ok') and ilet_after == ilet_before + 1, f"id={r_ilet.get('id')}")
    record('LOCK-FIN-ODEME-07-canonical', irow and irow[0] == loc and irow[1] == ckod, str(irow))
    ng2 = odeme_plani_sayfa_verisi_safe(location_filter='YN001', active_tab='arama')
    iso2 = not any(x['cari_kod'] == ckod for x in ng2.get('arama_rows', []))
    record('LOCK-FIN-ODEME-07-isolation', iso2, f'yn001_ilet={len(ng2.get("arama_rows", []))}')
    cari2 = odeme_plani_sayfa_verisi_safe(location_filter=loc, active_tab='cariler')
    match2 = next((x for x in cari2['cari_rows'] if x['cari_kod'] == ckod), None)
    g_ok = match2 and '20.08.2026' in match2['son_gorusme'] and 'Odeme' in match2['son_gorusme']
    record('LOCK-FIN-ODEME-07-parity', bool(g_ok), match2['son_gorusme'] if match2 else 'no row')
    with application.test_client() as client:
        login_as(client, 'admin', temp_db)
        html2 = client.get(f'/finans/odeme-plani?sekme=arama&sirket={loc}').get_data(as_text=True)
        record('LOCK-FIN-ODEME-07-persist', ckod in html2, 'reload ok')

    # LOCK-FIN-ODEME-08 — permissions
    with application.test_client() as client:
        login_as(client, 'admin', temp_db)
        record('LOCK-FIN-ODEME-08-admin-view', client.get('/finans/odeme-plani').status_code == 200, 'admin view')
        rw = client.post('/finans/odeme-plani/api/soz', json={
            'location': loc, 'cari_kod': ckod, 'promise_date': '2026-09-01', 'amount': 1000, 'currency': 'TRY',
        })
        record('LOCK-FIN-ODEME-08-admin-write', rw.status_code == 200, f'status={rw.status_code}')
    with application.test_client() as client:
        login_as(client, 'ibrahim', temp_db)
        record('LOCK-FIN-ODEME-08-ibrahim-view', client.get('/finans/odeme-plani').status_code == 200, 'ibrahim view')
        rw2 = client.post('/finans/odeme-plani/api/soz', json={
            'location': loc, 'cari_kod': ckod, 'promise_date': '2026-08-28', 'amount': 100,
        })
        record('LOCK-FIN-ODEME-08-ibrahim-write-block', rw2.status_code == 403, f'status={rw2.status_code}')
    ov = con.execute(
        """
        SELECT o.can_view FROM user_permission_override o
        JOIN sistem_yetki y ON y.Id = o.YetkiId
        WHERE o.KullaniciId=? AND y.Kod='finans.odeme_plani.write'
        """,
        (IBRAHIM_ID,),
    ).fetchone()
    record('LOCK-FIN-ODEME-08-migration170', bool(ov and int(ov[0]) == 1), f'override={ov}')

    # LOCK-FIN-ODEME-09 — status soft (no physical delete)
    soz_id = r_soz['id']
    st = ops.update_soz_status(soz_id, 'ERTELENDI', 'admin')
    status_row = con.execute('SELECT status FROM finans_odeme_plani_sozu WHERE Id=?', (soz_id,)).fetchone()
    count_after = con.execute('SELECT COUNT(*) FROM finans_odeme_plani_sozu WHERE Id=?', (soz_id,)).fetchone()[0]
    record('LOCK-FIN-ODEME-09-ertelendi', st.get('ok') and status_row[0] == 'ERTELENDI', status_row[0] if status_row else '')
    record('LOCK-FIN-ODEME-09-no-delete', count_after == 1, f'row_count={count_after}')
    for status in ('GERCEKLESTI', 'IPTAL', 'ACIK'):
        ok_st = ops.update_soz_status(soz_id, status, 'admin').get('ok')
        cur = con.execute('SELECT status FROM finans_odeme_plani_sozu WHERE Id=?', (soz_id,)).fetchone()
        record(f'LOCK-FIN-ODEME-09-{status}', ok_st and cur[0] == status, cur[0] if cur else '')

    # Negative blocks on temp DB
    try:
        ops.create_soz({'location': 'XX999', 'cari_kod': ckod, 'promise_date': '2026-08-28', 'amount': 1}, 'admin')
        record('LOCK-FIN-ODEME-neg-location', False, 'should block')
    except ops.OdemePlaniOpsError as e:
        record('LOCK-FIN-ODEME-neg-location', e.code == 'INVALID_LOCATION', str(e))
    try:
        ops.create_soz({'location': loc, 'cari_kod': '999.XX.YYY', 'promise_date': '2026-08-28', 'amount': 1}, 'admin')
        record('LOCK-FIN-ODEME-neg-cari', False, 'should block')
    except ops.OdemePlaniOpsError as e:
        record('LOCK-FIN-ODEME-neg-cari', e.code == 'INVALID_CARI', str(e))
    try:
        ops.create_soz({'location': loc, 'cari_kod': ckod, 'promise_date': '2026-08-28', 'amount': 0}, 'admin')
        record('LOCK-FIN-ODEME-neg-amount', False, 'should block')
    except ops.OdemePlaniOpsError as e:
        record('LOCK-FIN-ODEME-neg-amount', e.code == 'INVALID_AMOUNT', str(e))

    con.close()
    shutil.rmtree(temp_dir, ignore_errors=True)

    sha_after = sha256(CANONICAL_DB)
    record('CANONICAL_SHA_AFTER', sha_before == sha_after,
           f'before={sha_before} after={sha_after}')

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print('\n=== LOCK SUMMARY ===')
    print(json.dumps({'passed': passed, 'total': total, 'all_pass': passed == total}, indent=2))
    return 0 if passed == total else 1


if __name__ == '__main__':
    raise SystemExit(main())
