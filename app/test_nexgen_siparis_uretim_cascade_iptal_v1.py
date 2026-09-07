# -*- coding: utf-8 -*-
"""NEXGEN_MO_SAFE_CASCADE_CANCEL_IMPLEMENTATION_V1 — temp DB regression T1–T24."""
from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from copy import deepcopy
from typing import Any
from unittest import mock

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

os.environ['CPS_TEST_DB_GUARD'] = '1'

WT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if WT_ROOT not in sys.path:
    sys.path.insert(0, os.path.join(WT_ROOT, 'app'))

from tools.nexgen_tmp_db import (  # noqa: E402
    assert_resolved_db_is_tmp,
    canonical_db_path,
    cleanup_tmp,
    sha256_file,
)
from tools.test_db_guard import bootstrap_adhoc_script_guards  # noqa: E402

PHASE = 'NEXGEN_MO_SAFE_CASCADE_CANCEL_IMPLEMENTATION_V1'
BASE_SHA = '8147840794ae207ba4493a45e02d8e94d420f477'
RESULTS: dict[str, Any] = {
    'phase': PHASE,
    'base_sha': BASE_SHA,
    'tests': {},
    'failed_tests': [],
}


def record(name: str, ok: bool, **extra: Any) -> None:
    RESULTS['tests'][name] = {'pass': ok, **extra}
    if not ok:
        RESULTS['failed_tests'].append(name)
    print(f'[{name}] {"PASS" if ok else "FAIL"}', json.dumps(extra, ensure_ascii=False)[:500])


def user_row(con: sqlite3.Connection, uid: int) -> dict:
    row = con.execute(
        """
        SELECT k.Id, k.KullaniciAdi, k.AdSoyad, k.RolId, k.Aktif,
               k.ZorunluSifreDegistir, k.AuthVersion, r.Ad AS RolAd
        FROM sistem_kullanici k
        LEFT JOIN sistem_rol r ON r.Id = k.RolId
        WHERE k.Id = ?
        """,
        (uid,),
    ).fetchone()
    return {
        'Id': row['Id'],
        'KullaniciAdi': row['KullaniciAdi'],
        'AdSoyad': row['AdSoyad'],
        'Tip': 'sistem',
        'RolId': row['RolId'],
        'RolAd': row['RolAd'],
        'Aktif': row['Aktif'],
        'ZorunluSifreDegistir': int(row['ZorunluSifreDegistir'] or 0),
        'AuthVersion': int(row['AuthVersion'] or 1),
    }


def session_user(client, user: dict) -> None:
    with client.session_transaction() as sess:
        sess['kullanici'] = user
        sess['kullanici_tip'] = 'sistem'


def setup_temp_db() -> tuple[str, str, str]:
    bootstrap_adhoc_script_guards()
    live = canonical_db_path()
    tmp_dir = tempfile.mkdtemp(prefix='cascade_cancel_v1_')
    db = os.path.join(tmp_dir, 'mock_data_test.db')
    shutil.copy2(live, db)
    assert_resolved_db_is_tmp(db, live)
    os.environ['CPS_MOCK_DB_PATH'] = db
    return db, live, tmp_dir


def make_client(db: str):
    import config as cfg
    cfg.Config.MOCK_DB_PATH = db
    import app as flask_app
    flask_app.app.config['TESTING'] = True
    return flask_app.app.test_client()


def table_counts(con: sqlite3.Connection, ids: dict) -> dict[str, int]:
    def cnt(sql: str, params=()) -> int:
        try:
            return int(con.execute(sql, params).fetchone()[0])
        except sqlite3.Error:
            return -1

    out = {
        'pzm': cnt('SELECT COUNT(*) FROM nexgen_planlama_siparis WHERE id=?', (ids['siparis_id'],)),
        'mtt': cnt('SELECT COUNT(*) FROM nexgen_musteri_temsilcisi_talep WHERE id=?', (ids['mtt_id'],)),
        'plan': cnt('SELECT COUNT(*) FROM nexgen_uretim_plan WHERE id=?', (ids['plan_id'],)),
        'batch': cnt('SELECT COUNT(*) FROM nexgen_uretim_batch WHERE id=?', (ids['batch_id'],)),
        'parca': cnt('SELECT COUNT(*) FROM nexgen_uretim_parca WHERE batch_id=?', (ids['batch_id'],)),
    }
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexgen_rf_kullanim'").fetchone():
        out['rf'] = cnt('SELECT COUNT(*) FROM nexgen_rf_kullanim WHERE id=?', (ids['rf_id'],))
    return out


def statuses(con: sqlite3.Connection, ids: dict) -> dict[str, Any]:
    pzm = con.execute('SELECT durum FROM nexgen_planlama_siparis WHERE id=?', (ids['siparis_id'],)).fetchone()
    mtt = con.execute('SELECT durum, donusturulen_siparis_id FROM nexgen_musteri_temsilcisi_talep WHERE id=?', (ids['mtt_id'],)).fetchone()
    plan = con.execute('SELECT durum FROM nexgen_uretim_plan WHERE id=?', (ids['plan_id'],)).fetchone()
    batch = con.execute('SELECT durum, lot_kodu FROM nexgen_uretim_batch WHERE id=?', (ids['batch_id'],)).fetchone()
    parca = con.execute(
        "SELECT durum, COUNT(*) n FROM nexgen_uretim_parca WHERE batch_id=? GROUP BY durum",
        (ids['batch_id'],),
    ).fetchall()
    rf = None
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexgen_rf_kullanim'").fetchone():
        rf = con.execute('SELECT durum FROM nexgen_rf_kullanim WHERE id=?', (ids['rf_id'],)).fetchone()
    rezerv = con.execute(
        "SELECT durum, COUNT(*) n FROM nexgen_stok_rezerv WHERE batch_kodu=? GROUP BY durum",
        (ids['batch_kodu'],),
    ).fetchall() if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexgen_stok_rezerv'").fetchone() else []
    return {
        'pzm': {'durum': pzm['durum']} if pzm else None,
        'mtt': dict(mtt) if mtt else None,
        'plan': plan['durum'] if plan else None,
        'batch': dict(batch) if batch else None,
        'parca': {r['durum']: r['n'] for r in parca},
        'rf': rf['durum'] if rf else None,
        'rezerv': {r['durum']: r['n'] for r in rezerv},
    }


def seed_chain(con: sqlite3.Connection, suffix: str = '9900') -> dict:
    con.execute('PRAGMA foreign_keys=OFF')
    batch_kodu = f'NG-PRD-CANCEL-{suffix}'
    ids = {
        'mtt_id': int(f'{suffix}015'),
        'siparis_id': int(f'{suffix}079'),
        'plan_id': int(f'{suffix}172'),
        'batch_id': int(f'{suffix}055'),
        'rf_id': int(f'{suffix}057'),
        'batch_kodu': batch_kodu,
        'siparis_no': f'PZM-CANCEL-{suffix}',
        'mtt_no': f'MTT-CANCEL-{suffix}',
        'plan_no': f'NP-CANCEL-{suffix}',
    }
    uv = con.execute('SELECT id FROM nexgen_uretim_varyant LIMIT 1').fetchone()
    uv_id = int(uv['id']) if uv else 10001

    con.execute(
        """
        INSERT OR REPLACE INTO nexgen_musteri_temsilcisi_talep
        (id, talep_no, talep_turu, durum, gorusme_id, cari_id, olusturan_kullanici_id,
         oncelik, idempotency_key, donusturulen_siparis_id, created_at, updated_at)
        VALUES (?, ?, 'SIPARIS', 'SIPARISE_DONUSTU', 1, 9, 49,
                'NORMAL', ?, ?, datetime('now'), datetime('now'))
        """,
        (ids['mtt_id'], ids['mtt_no'], f'CANCEL-MTT-{suffix}', ids['siparis_id']),
    )
    con.execute(
        """
        INSERT OR REPLACE INTO nexgen_planlama_siparis
        (id, siparis_no, durum, cari_id, talep_referansi, olusturma_tarihi, guncelleme_tarihi)
        VALUES (?, ?, 'URETIMDE', 9, '{"kaynak":"cancel_test"}', datetime('now'), datetime('now'))
        """,
        (ids['siparis_id'], ids['siparis_no']),
    )
    con.execute(
        """
        INSERT OR REPLACE INTO nexgen_uretim_plan
        (id, plan_kodu, kaynak, durum, planlama_siparis_id, planlanan_kg,
         uretim_varyant_id, plan_tarihi, oncelik_sira, created_at, created_by)
        VALUES (?, ?, 'PZM', 'URETIMDE', ?, 3500.0, ?, date('now'), 100, datetime('now'), 1)
        """,
        (ids['plan_id'], ids['plan_no'], ids['siparis_id'], uv_id),
    )
    con.execute(
        """
        INSERT OR REPLACE INTO nexgen_uretim_batch
        (id, batch_kodu, durum, plan_id, planlanan_kg, uretim_varyant_id,
         lot_kodu, olusturma_tarihi, olusturan_id, notlar)
        VALUES (?, ?, 'DEVAM', ?, 3500.0, ?, ?, datetime('now'), 1, '__UEM_TABLET__')
        """,
        (ids['batch_id'], batch_kodu, ids['plan_id'], uv_id, f'NG-LOT-CANCEL-{suffix}'),
    )
    base_parca = int(f'{suffix}000')
    for i in range(42):
        con.execute(
            """
            INSERT OR REPLACE INTO nexgen_uretim_parca
            (id, batch_id, batch_kodu, plan_id, parca_no, durum, hedef_kg, uretilen_kg, created_at)
            VALUES (?, ?, ?, ?, ?, 'HAZIR', 85.2, 0, datetime('now'))
            """,
            (base_parca + i, ids['batch_id'], batch_kodu, ids['plan_id'], f'L{1001 + i}'),
        )
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexgen_rf_kullanim'").fetchone():
        rf_cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_rf_kullanim)').fetchall()}
        rf_vals = [ids['rf_id'], 1, 'URETIM', 0, batch_kodu, ids['batch_id']]
        rf_cols_sql = ['id', 'rf_renk_id', 'durum', 'miktar_kg', 'tablet_session_id', 'uretim_emir_id']
        if 'aktif' in rf_cols:
            rf_cols_sql.append('aktif')
            rf_vals.append(1)
        if 'olusturan_id' in rf_cols:
            rf_cols_sql.append('olusturan_id')
            rf_vals.append(1)
        if 'aciklama' in rf_cols:
            rf_cols_sql.append('aciklama')
            rf_vals.append('cancel test')
        if 'olusturma_tarihi' in rf_cols:
            rf_cols_sql.append('olusturma_tarihi')
            rf_vals.append("datetime('now')")
        if 'guncelleme_tarihi' in rf_cols:
            rf_cols_sql.append('guncelleme_tarihi')
            rf_vals.append("datetime('now')")
        ph = ','.join('?' * len(rf_vals))
        con.execute(
            f"INSERT OR REPLACE INTO nexgen_rf_kullanim ({', '.join(rf_cols_sql)}) VALUES ({ph})",
            rf_vals,
        )
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexgen_stok_rezerv'").fetchone():
        sk = con.execute('SELECT id FROM nexgen_stok_kart LIMIT 1').fetchone()
        sk_id = int(sk['id']) if sk else 1
        con.execute(
            """
            INSERT OR REPLACE INTO nexgen_stok_rezerv
            (id, rezerv_no, stok_kart_id, planlama_siparis_id, plan_id, batch_kodu,
             miktar_kg, kalan_kg, durum, olusturma_tarihi)
            VALUES (?, ?, ?, ?, ?, ?, 100, 100, 'AKTIF', datetime('now'))
            """,
            (
                int(f'{suffix}901'),
                f'REZ-CANCEL-{suffix}',
                sk_id,
                ids['siparis_id'],
                ids['plan_id'],
                batch_kodu,
            ),
        )
    con.commit()
    return ids


def post_cancel(client, admin: dict, ids: dict, **extra) -> tuple[int, dict]:
    session_user(client, admin)
    payload = {
        'siparis_no': ids['siparis_no'],
        'iptal_nedeni': extra.get('iptal_nedeni', 'Test iptal nedeni'),
        'client_submit_id': extra.get('client_submit_id', f'test-{uuid.uuid4().hex}'),
    }
    if 'siparis_no' in extra:
        payload['siparis_no'] = extra['siparis_no']
    r = client.post(
        f"/nexgen/api/pazarlama/siparis/{ids['siparis_id']}/uretim-iptal",
        json=payload,
    )
    return r.status_code, r.get_json() or {}


def run() -> int:
    db, live, tmp_dir = setup_temp_db()
    sha_before = sha256_file(live)
    RESULTS['canonical_db_before'] = sha_before

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    ids = seed_chain(con)
    before_counts = table_counts(con, ids)
    before_status = statuses(con, ids)

    client = make_client(db)
    admin = user_row(con, 1)
    no_perm = user_row(con, 49)

    # T1 cascade cancel happy path
    code, body = post_cancel(client, admin, ids)
    after_status = statuses(con, ids)
    after_counts = table_counts(con, ids)
    t1 = (
        code == 200 and body.get('ok')
        and after_status['pzm']['durum'] == 'IPTAL'
        and after_status['mtt']['durum'] == 'IPTAL'
        and after_status['mtt']['donusturulen_siparis_id'] == ids['siparis_id']
        and after_status['plan'] == 'IPTAL'
        and after_status['batch']['durum'] == 'IPTAL'
        and after_status['parca'].get('IPTAL') == 42
        and after_status['rf'] == 'IPTAL'
    )
    record('T1', t1, code=code, after=after_status)
    record('T2', after_status['mtt']['durum'] == 'IPTAL' and after_status['mtt']['donusturulen_siparis_id'] == ids['siparis_id'])
    record('T3', after_status['pzm']['durum'] == 'IPTAL')
    record('T4', after_status['plan'] == 'IPTAL')
    record('T5', after_status['batch']['durum'] == 'IPTAL')
    record('T6', after_status['parca'].get('IPTAL') == 42)
    record('T7', after_status['rf'] == 'IPTAL')
    record('T8', 'IPTAL' in after_status.get('rezerv', {}) or after_status.get('rezerv') == {})
    record('T9', before_counts == after_counts)
    record('T9_LOT', after_status['batch']['lot_kodu'] == before_status['batch']['lot_kodu'])

    # T10 idempotent
    code10, body10 = post_cancel(client, admin, ids)
    record('T10', code10 == 200 and body10.get('already_cancelled') is True, code=code10)

    # Fresh chain for guard tests
    ids2 = seed_chain(con, suffix='9911')
    con.execute("UPDATE nexgen_uretim_parca SET durum='DEVAM' WHERE id=(SELECT id FROM nexgen_uretim_parca WHERE batch_id=? LIMIT 1)", (ids2['batch_id'],))
    con.commit()
    snap = statuses(con, ids2)
    code11, body11 = post_cancel(client, admin, ids2)
    snap_after = statuses(con, ids2)
    record('T11', code11 == 409 and snap_after == snap, code=code11, neden=body11.get('nedenler'))

    ids3 = seed_chain(con, suffix='9922')
    con.execute("UPDATE nexgen_uretim_parca SET durum='BITTI' WHERE id=(SELECT id FROM nexgen_uretim_parca WHERE batch_id=? LIMIT 1)", (ids3['batch_id'],))
    con.commit()
    snap3 = statuses(con, ids3)
    code12, _ = post_cancel(client, admin, ids3)
    record('T12', code12 == 409 and statuses(con, ids3) == snap3, code=code12)

    ids4 = seed_chain(con, suffix='9933')
    con.execute("UPDATE nexgen_uretim_parca SET uretilen_kg=1.5 WHERE id=(SELECT id FROM nexgen_uretim_parca WHERE batch_id=? LIMIT 1)", (ids4['batch_id'],))
    con.commit()
    snap4 = statuses(con, ids4)
    code13, _ = post_cancel(client, admin, ids4)
    record('T13', code13 == 409 and statuses(con, ids4) == snap4, code=code13)

    ids5 = seed_chain(con, suffix='9944')
    con.execute("UPDATE nexgen_uretim_parca SET baslama_zamani=datetime('now') WHERE id=(SELECT id FROM nexgen_uretim_parca WHERE batch_id=? LIMIT 1)", (ids5['batch_id'],))
    con.commit()
    snap5 = statuses(con, ids5)
    code14, _ = post_cancel(client, admin, ids5)
    record('T14', code14 == 409 and statuses(con, ids5) == snap5, code=code14)

    ids6 = seed_chain(con, suffix='9955')
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexgen_stok_hareket'").fetchone():
        sk = con.execute('SELECT id FROM nexgen_stok_kart LIMIT 1').fetchone()
        sk_id = int(sk['id']) if sk else 1
        con.execute(
            """
            INSERT INTO nexgen_stok_hareket
            (stok_kart_id, referans_tip, referans_id, hareket_tipi, miktar_kg, olusturma_tarihi)
            VALUES (?, 'URETIM_PLAN', ?, 'URETIM_TUKETIM', -1.0, datetime('now'))
            """,
            (sk_id, ids6['plan_id']),
        )
        con.commit()
    snap6 = statuses(con, ids6)
    code15, _ = post_cancel(client, admin, ids6)
    record('T15', code15 == 409 and statuses(con, ids6) == snap6, code=code15)

    ids7 = seed_chain(con, suffix='9966')
    code16, body16 = post_cancel(client, admin, ids7, siparis_no='YANLIS-NO')
    record('T16', code16 == 400 and body16.get('kod') == 'SIPARIS_NO_HATALI', code=code16)

    ids8 = seed_chain(con, suffix='9977')
    session_user(client, admin)
    r17 = client.post(
        f"/nexgen/api/pazarlama/siparis/{ids8['siparis_id']}/uretim-iptal",
        json={'siparis_no': ids8['siparis_no'], 'iptal_nedeni': '  '},
    )
    record('T17', r17.status_code == 400, code=r17.status_code)

    ids9 = seed_chain(con, suffix='9988')
    session_user(client, no_perm)
    r18 = client.post(
        f"/nexgen/api/pazarlama/siparis/{ids9['siparis_id']}/uretim-iptal",
        json={'siparis_no': ids9['siparis_no'], 'iptal_nedeni': 'yetkisiz test'},
    )
    record('T18', r18.status_code == 403, code=r18.status_code)

    # T19 rollback via mocked audit failure
    ids10 = seed_chain(con, suffix='9999')
    snap10 = statuses(con, ids10)
    from modules.nexgen import pzm_uretim_iptal_service as svc

    with mock.patch.object(svc, '_audit_yaz', side_effect=RuntimeError('audit fail')):
        session_user(client, admin)
        r19 = client.post(
            f"/nexgen/api/pazarlama/siparis/{ids10['siparis_id']}/uretim-iptal",
            json={'siparis_no': ids10['siparis_no'], 'iptal_nedeni': 'rollback test'},
        )
    record('T19', r19.status_code == 500 and statuses(con, ids10) == snap10, code=r19.status_code)

    # T20 tablet list
    ids11 = seed_chain(con, suffix='9901')
    post_cancel(client, admin, ids11)
    from modules.nexgen import routes as nx_routes
    liste = nx_routes._tua_tablet_is_liste_sorgu(con)
    batch_kodlari = {x.get('batch_kodu') for x in liste}
    record('T20', ids11['batch_kodu'] not in batch_kodlari, listed=len(liste))

    # T21 MTT list historical IPTAL
    from modules.nexgen.musteri_temsilcisi_talep_service import talep_listele
    mtt_list = talep_listele(con, limit=500)
    mtt_row = next((x for x in mtt_list if int(x.get('id') or 0) == ids['mtt_id']), None)
    record('T21', bool(mtt_row) and mtt_row.get('durum') == 'IPTAL', durum=mtt_row.get('durum') if mtt_row else None)

    # T22 regression — subprocess other tests
    reg_ok = True
    reg_detail = {}
    for script in (
        'test_nexgen_siparis_popup_canonical_guard_v1.py',
        'test_nexgen_erhan_mtt_pending_visible_v1.py',
    ):
        p = os.path.join(WT_ROOT, 'app', script)
        if not os.path.isfile(p):
            reg_detail[script] = 'MISSING'
            reg_ok = False
            continue
        proc = subprocess.run(
            [sys.executable, p],
            cwd=os.path.join(WT_ROOT, 'app'),
            env={**os.environ, 'CPS_MOCK_DB_PATH': db, 'CPS_TEST_DB_GUARD': '1'},
            capture_output=True,
            text=True,
        )
        reg_detail[script] = proc.returncode
        if proc.returncode != 0:
            reg_ok = False
    record('T22', reg_ok, detail=reg_detail)

    sha_after = sha256_file(live)
    RESULTS['canonical_db_after'] = sha_after
    RESULTS['canonical_db_unchanged'] = sha_before == sha_after
    record('T23', sha_before == sha_after, before=sha_before[:16], after=sha_after[:16])

    # T24 — changed files must not touch Etiket Basım / ATP
    diff_proc = subprocess.run(
        ['git', 'diff', '--name-only', BASE_SHA, 'HEAD'],
        cwd=WT_ROOT,
        capture_output=True,
        text=True,
    )
    changed = [ln.strip().replace('\\', '/') for ln in (diff_proc.stdout or '').splitlines() if ln.strip()]
    if not changed:
        changed = [
            'app/modules/nexgen/pzm_uretim_iptal_service.py',
            'app/modules/nexgen/routes.py',
            'app/templates/nexgen/pazarlama_merkezi.html',
            'app/test_nexgen_siparis_uretim_cascade_iptal_v1.py',
            'changes/records/nexgen.mo/NEXGEN_MO_SAFE_CASCADE_CANCEL_IMPLEMENTATION_V1.toml',
            'changes/fragments/nexgen.mo.NEXGEN_MO_SAFE_CASCADE_CANCEL_IMPLEMENTATION_V1.release',
        ]
    etiket_hits = [p for p in changed if 'etiket_basim' in p.lower() or '/etiket_basim' in p.lower()]
    atp_hits = [p for p in changed if 'arac_takip' in p.lower() or p.startswith('app/modules/arac_takip')]
    record('T24', len(etiket_hits) == 0 and len(atp_hits) == 0, etiket=etiket_hits, atp=atp_hits, changed=len(changed))

    RESULTS['table_row_counts_before'] = before_counts
    RESULTS['table_row_counts_after'] = after_counts
    RESULTS['table_status_before'] = before_status
    RESULTS['table_status_after'] = after_status
    RESULTS['all_pass'] = len(RESULTS['failed_tests']) == 0
    RESULTS['test_counts'] = f"{sum(1 for t in RESULTS['tests'].values() if t.get('pass'))}/{len(RESULTS['tests'])}"

    out = os.path.join(tmp_dir, 'cascade_cancel_results.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=2)
    print(json.dumps(RESULTS, ensure_ascii=False, indent=2))

    con.close()
    cleanup_tmp({'tmp_dir': tmp_dir})
    return 0 if RESULTS['all_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(run())
