# -*- coding: utf-8 -*-
"""BE-3E.1 — Atomik üretime gönderme: başarı + rollback kapanış testleri."""
import io
import os
import shutil
import sqlite3
import sys
from datetime import date, timedelta
from unittest.mock import patch

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

SRC_DB = os.path.join(_APP, 'mock_data.db')
TEST_DB_A = os.path.join(_APP, 'mock_data_be3e1_a_tmp.db')
TEST_DB_B = os.path.join(_APP, 'mock_data_be3e1_b_tmp.db')
TEST_DB_C = os.path.join(_APP, 'mock_data_be3e1_c_tmp.db')

results = []
_nx_routes = None
_app = None
_m107_mod = None


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def sess_user():
    return {'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem', 'RolId': 1, 'RolAd': 'admin', 'Aktif': 1}


def snap(con, talep_id=None, plan_ids=None):
    d = {
        'batch': con.execute('SELECT COUNT(*) FROM nexgen_uretim_batch').fetchone()[0],
        'parca': con.execute('SELECT COUNT(*) FROM nexgen_uretim_parca').fetchone()[0],
        'plan': con.execute('SELECT COUNT(*) FROM nexgen_uretim_plan').fetchone()[0],
    }
    if talep_id:
        row = con.execute(
            'SELECT durum FROM nexgen_planlama_siparis WHERE id=?', (talep_id,)
        ).fetchone()
        d['hdr_durum'] = row[0] if row else None
    if plan_ids:
        d['plan_durum'] = {
            pid: con.execute('SELECT durum FROM nexgen_uretim_plan WHERE id=?', (pid,)).fetchone()[0]
            for pid in plan_ids
        }
        d['plan_batch'] = {
            pid: con.execute(
                "SELECT COUNT(*) FROM nexgen_uretim_batch WHERE plan_id=? AND durum!='IPTAL'",
                (pid,),
            ).fetchone()[0]
            for pid in plan_ids
        }
    return d


def v2_payload(con, kalemler):
    cari_id = con.execute('SELECT id FROM nexgen_cari WHERE aktif=1 LIMIT 1').fetchone()['id']
    termin = (date.today() + timedelta(days=21)).isoformat()
    return {
        'cari_id': cari_id,
        'siparis_tarihi': date.today().isoformat(),
        'genel_termin_tarihi': termin,
        'genel_not': 'BE3E1 kapanis test',
        'kalemler': kalemler,
    }


def cok_plan_kalemler(con, ml1=1, ms1=1, ml2=2, ms2=2):
    rf_row = con.execute(
        "SELECT u.rf_renk_id FROM nexgen_rf_formul_uygunluk u "
        "JOIN nexgen_formul f ON f.id=u.formul_id "
        "WHERE u.aktif=1 AND f.kod LIKE '1BA-FL01' LIMIT 1"
    ).fetchone()
    if not rf_row:
        return None
    fid = con.execute(
        "SELECT MIN(f.id) FROM nexgen_formul f WHERE f.kod LIKE '1BA-FL01' AND f.aktif=1"
    ).fetchone()[0]
    rf_id = rf_row['rf_renk_id']
    termin = (date.today() + timedelta(days=14)).isoformat()
    base = {
        'urun_ailesi': 'TERLIK',
        'formul_id': fid,
        'rf_renk_id': rf_id,
        'renk_varyant_id': rf_id,
        'termin_tarihi': termin,
    }
    return [
        {**base, 'miktar_l': ml1, 'miktar_s': ms1, 'miktar_m': None},
        {**base, 'miktar_l': ml2, 'miktar_s': ms2, 'miktar_m': None},
    ]


def init_test_db(test_db_path):
    global _nx_routes, _app, _m107_mod
    shutil.copy2(SRC_DB, test_db_path)
    import app as flask_app
    import modules.nexgen.routes as nx_routes
    _nx_routes = nx_routes
    nx_routes.DB_PATH = test_db_path
    _app = flask_app.app
    _app.config['TESTING'] = True
    import importlib.util
    m107 = os.path.join(_APP, 'migrations', '107_nexgen_planlama_siparis_kalem.py')
    if os.path.exists(m107):
        spec = importlib.util.spec_from_file_location('m107', m107)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.run(db_path=test_db_path)
        _m107_mod = mod
    return sqlite3.connect(test_db_path)


def boost_stok_for_plan(con, plan_id, kg=500000):
    """Test DB: plan hammaddelerine yeterli GIRIS yazar."""
    st = _nx_routes._mpr_stok_ihtiyac_birlestir(con, plan_id)
    if not st.get('ok'):
        return False
    ids = set()
    for k in st.get('kalemler', []):
        sid = k.get('stok_kart_id')
        if sid:
            ids.add(int(sid))
    for sid in ids:
        _nx_routes._stok_hareket_yaz(
            con, sid, 'GIRIS', kg,
            aciklama='BE3E1 test stok boost',
            referans_tip='TEST',
        )
    con.commit()
    st2 = _nx_routes._mpr_stok_ihtiyac_birlestir(con, plan_id)
    return st2.get('yeterli_mi', False)


def setup_siparis_cok_plan(c, con, ml1=1, ms1=1, ml2=2, ms2=2):
    kalemler = cok_plan_kalemler(con, ml1=ml1, ms1=ms1, ml2=ml2, ms2=ms2)
    if not kalemler:
        return None, []
    d_t = (c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, kalemler)).get_json() or {})
    if not d_t.get('ok'):
        return None, []
    tid = d_t['talep_id']
    d_mpr = (c.post('/nexgen/api/pazarlama/mpr-olustur', json={'talep_id': tid}).get_json() or {})
    planlar = d_mpr.get('planlar') or []
    if not d_mpr.get('ok') or len(planlar) < 2:
        return tid, []
    plan_ids = [p['plan_id'] for p in planlar if p.get('plan_id')]
    return tid, plan_ids


def cleanup(con, tid, plan_ids):
    for pid in plan_ids:
        bks = con.execute(
            "SELECT batch_kodu FROM nexgen_uretim_batch WHERE plan_id=?", (pid,)
        ).fetchall()
        for b in bks:
            con.execute('DELETE FROM nexgen_uretim_parca WHERE batch_kodu=?', (b[0],))
            con.execute('DELETE FROM nexgen_uretim_batch WHERE batch_kodu=?', (b[0],))
        if con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='nexgen_depo_hazirlik'"
        ).fetchone():
            con.execute('DELETE FROM nexgen_depo_hazirlik WHERE plan_id=?', (pid,))
        con.execute('DELETE FROM nexgen_uretim_plan_boyut WHERE plan_id=?', (pid,))
        con.execute('DELETE FROM nexgen_uretim_plan WHERE id=?', (pid,))
    if tid:
        con.execute('DELETE FROM nexgen_planlama_siparis_kalem WHERE planlama_siparis_id=?', (tid,))
        con.execute('DELETE FROM nexgen_planlama_siparis WHERE id=?', (tid,))
    con.commit()


print('=' * 65)
print('BE-3E.1 TEST — atomik başarı + rollback kapanış')
print('=' * 65)

rf_probe = sqlite3.connect(SRC_DB)
rf_ok = rf_probe.execute(
    "SELECT 1 FROM nexgen_rf_formul_uygunluk u "
    "JOIN nexgen_formul f ON f.id=u.formul_id "
    "WHERE u.aktif=1 AND f.kod LIKE '1BA-FL01' LIMIT 1"
).fetchone()
rf_probe.close()

if not rf_ok:
    ok('setup RF', True, 'atlandi')
else:
    # ── A) Başarı yolu ─────────────────────────────────────────────
    con = init_test_db(TEST_DB_A)
    con.row_factory = sqlite3.Row
    with _app.test_client() as c:
        with c.session_transaction() as sess:
            sess['kullanici'] = sess_user()
            sess['kullanici_tip'] = 'sistem'

        tid_ok, plan_ids_ok = setup_siparis_cok_plan(c, con)
        ok('A setup 2 plan', tid_ok and len(plan_ids_ok) >= 2, f'plans={len(plan_ids_ok)}')

        if tid_ok and len(plan_ids_ok) >= 2:
            for pid in plan_ids_ok:
                boosted = boost_stok_for_plan(con, pid)
                ok(f'A stok boost plan {pid}', boosted)

            for pid in plan_ids_ok:
                st = _nx_routes._mpr_stok_ihtiyac_birlestir(con, pid)
                ok(f'A on-kontrol stok plan {pid}', st.get('yeterli_mi'), f"eksik={st.get('eksik_sayisi')}")

            before = snap(con, tid_ok, plan_ids_ok)
            ok('A once ON_CALISMA', all(d == 'ON_CALISMA' for d in before['plan_durum'].values()))

            d_send = (c.post(
                f'/nexgen/api/pazarlama/siparis/{tid_ok}/uretime-gonder',
                json={'confirm': True},
            ).get_json() or {})

            after = snap(con, tid_ok, plan_ids_ok)

            if d_send.get('ok'):
                ok('A atomik gonder ok', True, f"{d_send.get('plan_sayisi')} plan")
                ok('A hdr URETIMDE', after['hdr_durum'] == 'URETIMDE', after['hdr_durum'])
                ok('A tum plan URETIMDE', all(d == 'URETIMDE' for d in after['plan_durum'].values()))
                ok('A her plan batch', all(after['plan_batch'][p] == 1 for p in plan_ids_ok))
                ok('A batch artti', after['batch'] == before['batch'] + len(plan_ids_ok),
                   f"{before['batch']}->{after['batch']}")
                ok('A parca artti', after['parca'] > before['parca'],
                   f"{before['parca']}->{after['parca']}")
            else:
                ok('A atomik gonder ok', False, d_send.get('hata', '?')[:80])

            cleanup(con, tid_ok, plan_ids_ok)
    con.close()

    # ── B) Ön-kontrol rollback (stok eksik) ───────────────────────
    con = init_test_db(TEST_DB_B)
    con.row_factory = sqlite3.Row
    with _app.test_client() as c:
        with c.session_transaction() as sess:
            sess['kullanici'] = sess_user()
            sess['kullanici_tip'] = 'sistem'

        tid_rb, plan_ids_rb = setup_siparis_cok_plan(c, con, ml1=5000, ms1=5000, ml2=4000, ms2=4000)
        ok('B setup 2 plan buyuk KG', tid_rb and len(plan_ids_rb) >= 2)

        if tid_rb and len(plan_ids_rb) >= 2:
            for pid in plan_ids_rb:
                stb = _nx_routes._mpr_stok_ihtiyac_birlestir(con, pid)
                ok(f'B on-kontrol stok plan {pid}', not stb.get('yeterli_mi'),
                   f"yeterli={stb.get('yeterli_mi')} eksik={stb.get('eksik_sayisi')}")
            before_b = snap(con, tid_rb, plan_ids_rb)
            d_rb = (c.post(
                f'/nexgen/api/pazarlama/siparis/{tid_rb}/uretime-gonder',
                json={'confirm': True},
            ).get_json() or {})
            after_b = snap(con, tid_rb, plan_ids_rb)

            blok = bool(d_rb.get('stok_eksik') or not d_rb.get('ok'))
            ok('B stok eksik blok', blok,
               f"ok={d_rb.get('ok')} stok_eksik={d_rb.get('stok_eksik')} hata={(d_rb.get('hata') or '')[:50]}")
            ok('B batch degismedi', after_b['batch'] == before_b['batch'])
            ok('B parca degismedi', after_b['parca'] == before_b['parca'])
            ok('B hdr degismedi', after_b['hdr_durum'] == before_b['hdr_durum'])
            ok('B plan ON_CALISMA', all(d == 'ON_CALISMA' for d in after_b['plan_durum'].values()))
            ok('B plan batch yok', all(after_b['plan_batch'][p] == 0 for p in plan_ids_rb))

            cleanup(con, tid_rb, plan_ids_rb)
    con.close()

    # ── C) Transaction rollback (2. planda simule hata) ───────────
    con = init_test_db(TEST_DB_C)
    con.row_factory = sqlite3.Row
    with _app.test_client() as c:
        with c.session_transaction() as sess:
            sess['kullanici'] = sess_user()
            sess['kullanici_tip'] = 'sistem'

        tid_tx, plan_ids_tx = setup_siparis_cok_plan(c, con)
        ok('C setup 2 plan', tid_tx and len(plan_ids_tx) >= 2)

        if tid_tx and len(plan_ids_tx) >= 2:
            for pid in plan_ids_tx:
                boost_stok_for_plan(con, pid)
            before_c = snap(con, tid_tx, plan_ids_tx)
            _orig_tx = _nx_routes._mpr_plan_uretime_gonder_tx
            _calls = {'n': 0}

            def _fail_second(con_, plan_id, uid, plan=None, uv=None):
                _calls['n'] += 1
                if _calls['n'] >= 2:
                    raise RuntimeError('BE3E1 simulated plan-2 failure')
                return _orig_tx(con_, plan_id, uid, plan=plan, uv=uv)

            with patch.object(_nx_routes, '_mpr_plan_uretime_gonder_tx', side_effect=_fail_second):
                d_tx = (c.post(
                    f'/nexgen/api/pazarlama/siparis/{tid_tx}/uretime-gonder',
                    json={'confirm': True},
                ).get_json() or {})

            after_c = snap(con, tid_tx, plan_ids_tx)

            ok('C gonder basarisiz', not d_tx.get('ok'))
            ok('C batch rollback', after_c['batch'] == before_c['batch'],
               f"{before_c['batch']}->{after_c['batch']}")
            ok('C parca rollback', after_c['parca'] == before_c['parca'])
            ok('C hdr rollback', after_c['hdr_durum'] == before_c['hdr_durum'])
            ok('C plan ON_CALISMA', all(d == 'ON_CALISMA' for d in after_c['plan_durum'].values()))
            ok('C plan batch yok', all(after_c['plan_batch'][p] == 0 for p in plan_ids_tx))

            cleanup(con, tid_tx, plan_ids_tx)
    con.close()

for _tmp in (TEST_DB_A, TEST_DB_B, TEST_DB_C):
    try:
        os.remove(_tmp)
    except OSError:
        pass

print('\n' + '=' * 65)
passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f'SONUC: {passed} PASS / {failed} FAIL')
print('Commit: EDILMEDI')
print('=' * 65)
sys.exit(0 if failed == 0 else 1)
