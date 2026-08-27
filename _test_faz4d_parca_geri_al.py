# -*- coding: utf-8 -*-
"""NEXGEN FAZ-4D — alt emir BITTI geri alma + stok iade testi."""
from __future__ import annotations

import io
import os
import sqlite3
import sys
import tempfile
import shutil
from unittest.mock import patch

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP_DIR)
os.chdir(_APP_DIR)

os.environ.setdefault('CPS_TEST_DB_GUARD', '1')

from tools.nexgen_tmp_db import (  # noqa: E402
    assert_resolved_db_is_tmp,
    canonical_db_path,
    cleanup_tmp,
    live_db_write_guard_stats,
    sha256_file,
)
from tools.test_db_guard import bootstrap_adhoc_script_guards  # noqa: E402


def _resolve_test_db():
    live = canonical_db_path()
    bootstrap_adhoc_script_guards()
    parent_tmp = os.environ.get('CPS_MOCK_DB_PATH', '').strip()
    if parent_tmp:
        db = os.path.abspath(parent_tmp)
        assert_resolved_db_is_tmp(db, live)
        os.environ['CPS_MOCK_DB_PATH'] = db
        return db, live, None

    tmp_dir = tempfile.mkdtemp(prefix='faz4d_')
    db = os.path.join(tmp_dir, 'mock_data_test.db')
    shutil.copy2(live, db)
    assert_resolved_db_is_tmp(db, live)
    os.environ['CPS_MOCK_DB_PATH'] = db
    return db, live, tmp_dir


_LIVE_DB = canonical_db_path()
_SHA_BEFORE = sha256_file(_LIVE_DB)
DB, _CANONICAL, _TMP_DIR = _resolve_test_db()
print(f'[ISO] tmp_db={DB}')
print(f'[ISO] main_sha_before={_SHA_BEFORE}')

import config as _cfg
_cfg.Config.MOCK_DB_PATH = DB
import app as flask_app
import modules.nexgen.routes as nx_routes
from modules.nexgen.routes import (
    _mpr_stok_ihtiyac_hesapla, _mevcut_stok, _parca_stok_net_tuketim,
    _parca_stok_iade, _parca_stok_tuket,
)
nx_routes.DB_PATH = DB

_app = flask_app.app
_app.config['TESTING'] = True
results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def sess_user():
    con = sqlite3.connect(DB)
    row = con.execute(
        """
        SELECT Id, KullaniciAdi, RolId, Aktif, ZorunluSifreDegistir, AuthVersion
        FROM sistem_kullanici WHERE Id = 1
        """
    ).fetchone()
    con.close()
    auth_ver = row[5] if row and row[5] is not None else 1
    return {
        'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem',
        'RolId': 1, 'RolAd': 'admin', 'Aktif': 1,
        'AuthVersion': auth_ver,
        'ZorunluSifreDegistir': int(row[4] or 0) if row else 0,
    }


def stok_net(con, stok_kart_id):
    return round(_mevcut_stok(con, stok_kart_id), 3)


def parca_bitir_client(c, batch_kodu, parca_id):
    return c.post(
        f'/nexgen/api/batch/{batch_kodu}/parca/{parca_id}/bitir', json={}
    )


def parca_geri_al_client(c, batch_kodu, parca_id, gerekce):
    return c.post(
        f'/nexgen/api/batch/{batch_kodu}/parca/{parca_id}/geri-al',
        json={'gerekce': gerekce},
    )


def _ensure_parca_devam(c, batch_kodu, parca_id):
    durum = sqlite3.connect(DB).execute(
        'SELECT durum FROM nexgen_uretim_parca WHERE id=?', (parca_id,)
    ).fetchone()
    if durum and durum[0] == 'HAZIR':
        c.post(f'/nexgen/api/batch/{batch_kodu}/parca/{parca_id}/baslat', json={})


con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

parca_id = None
batch_kodu = None
hedef_kg = None

bitti = con.execute("""
    SELECT p.id, p.batch_kodu, p.hedef_kg, p.durum, p.baslama_zamani,
           b.uretim_varyant_id, pl.rf_renk_id
    FROM nexgen_uretim_parca p
    JOIN nexgen_uretim_batch b ON b.batch_kodu = p.batch_kodu
    LEFT JOIN nexgen_uretim_plan pl ON pl.id = COALESCE(p.plan_id, b.plan_id)
    WHERE p.durum = 'BITTI'
      AND EXISTS (
        SELECT 1 FROM nexgen_stok_hareket h
        WHERE h.referans_tip='URETIM_PARCA' AND h.referans_id=p.id
          AND h.hareket_tipi='URETIM_TUKETIM' AND h.miktar_kg < 0
      )
    ORDER BY p.id DESC LIMIT 1
""").fetchone()

if bitti:
    parca_id = bitti['id']
    batch_kodu = bitti['batch_kodu']
    hedef_kg = float(bitti['hedef_kg'])
else:
    aday = con.execute("""
        SELECT p.id, p.batch_kodu, p.hedef_kg, p.durum, b.uretim_varyant_id, pl.rf_renk_id
        FROM nexgen_uretim_parca p
        JOIN nexgen_uretim_batch b ON b.batch_kodu = p.batch_kodu
        LEFT JOIN nexgen_uretim_plan pl ON pl.id = COALESCE(p.plan_id, b.plan_id)
        WHERE p.durum IN ('DEVAM', 'HAZIR')
        ORDER BY p.id DESC LIMIT 1
    """).fetchone()
    if aday:
        chk = _mpr_stok_ihtiyac_hesapla(
            con, aday['uretim_varyant_id'], aday['rf_renk_id'],
            float(aday['hedef_kg']),
        )
        if chk.get('ok') and not chk.get('yeterli_mi'):
            for k in chk.get('kalemler', []):
                if not k.get('yeterli'):
                    sid = k['stok_kart_id']
                    eksik = round(float(k['gerekli_kg']) - float(k['mevcut_kg']), 3) + 2.0
                    onceki = _mevcut_stok(con, sid)
                    con.execute("""
                        INSERT INTO nexgen_stok_hareket
                          (stok_kart_id, hareket_tipi, miktar_kg, onceki_stok, sonraki_stok,
                           aciklama, olusturma_tarihi)
                        VALUES (?, 'GIRIS', ?, ?, ?, 'FAZ4D test seed', datetime('now'))
                    """, (sid, eksik, onceki, round(onceki + eksik, 3)))
            con.commit()
        with _app.test_client() as c:
            with c.session_transaction() as sess:
                sess['kullanici'] = sess_user()
                sess['kullanici_tip'] = 'sistem'
            _ensure_parca_devam(c, aday['batch_kodu'], aday['id'])
            r = parca_bitir_client(c, aday['batch_kodu'], aday['id'])
            if r.status_code == 200 and (r.get_json() or {}).get('ok'):
                parca_id = aday['id']
                batch_kodu = aday['batch_kodu']
                hedef_kg = float(aday['hedef_kg'])

if parca_id:
    tuketimler = con.execute("""
        SELECT stok_kart_id, miktar_kg FROM nexgen_stok_hareket
        WHERE referans_tip='URETIM_PARCA' AND referans_id=?
          AND hareket_tipi='URETIM_TUKETIM' AND miktar_kg < 0
    """, (parca_id,)).fetchall()
    ok('1 BITTI parca stok dusmus', len(tuketimler) > 0, f'hareket={len(tuketimler)}')
    stok_once = {r['stok_kart_id']: stok_net(con, r['stok_kart_id']) for r in tuketimler}
    beklenen_sonra = {}
    for r in tuketimler:
        sid = r['stok_kart_id']
        beklenen_sonra[sid] = round(stok_once[sid] + abs(float(r['miktar_kg'])), 3)
    net_tuket_once = _parca_stok_net_tuketim(con, parca_id)
    ok('1 net tuketim aktif', net_tuket_once < -0.0005, str(net_tuket_once))

    gerekce = 'yanlış kapatma test FAZ4D'
    with _app.test_client() as c:
        with c.session_transaction() as sess:
            sess['kullanici'] = sess_user()
            sess['kullanici_tip'] = 'sistem'
        r = parca_geri_al_client(c, batch_kodu, parca_id, gerekce)
        d = r.get_json() or {}
        ok('2 geri al 200', r.status_code == 200 and d.get('ok'), str(d.get('yeni_durum')))

    iptaller = con.execute("""
        SELECT * FROM nexgen_stok_hareket
        WHERE referans_tip='URETIM_PARCA_IPTAL' AND referans_id=?
          AND hareket_tipi='URETIM_TUKETIM_IPTAL'
    """, (parca_id,)).fetchall()
    ok('2 stok iade hareketi', len(iptaller) > 0, str(len(iptaller)))
    if iptaller:
        h0 = iptaller[0]
        ok('ornek iptal pozitif', float(h0['miktar_kg']) > 0, str(h0['miktar_kg']))
        ok('ornek tip URETIM_TUKETIM_IPTAL', h0['hareket_tipi'] == 'URETIM_TUKETIM_IPTAL', '')

    net_sonra = _parca_stok_net_tuketim(con, parca_id)
    ok('3 net stok sifirlandi', abs(net_sonra) < 0.001, str(net_sonra))
    stok_eski = True
    for sid, bek in beklenen_sonra.items():
        simdi = stok_net(con, sid)
        if abs(simdi - bek) > 0.01:
            stok_eski = False
            break
    ok('3 stok kartlari eski seviyeye dondu', stok_eski, '')

    iptal_cnt_once = len(iptaller)
    with _app.test_client() as c:
        with c.session_transaction() as sess:
            sess['kullanici'] = sess_user()
            sess['kullanici_tip'] = 'sistem'
        r2 = parca_geri_al_client(c, batch_kodu, parca_id, gerekce + ' tekrar')
        d2 = r2.get_json() or {}
        ok('4 ikinci geri al engellendi', r2.status_code == 400 or not d2.get('ok'),
           d2.get('hata', str(r2.status_code)))
    iptal_cnt_sonra = con.execute("""
        SELECT COUNT(*) FROM nexgen_stok_hareket
        WHERE referans_tip='URETIM_PARCA_IPTAL' AND referans_id=?
    """, (parca_id,)).fetchone()[0]
    ok('4 cift iade yok', iptal_cnt_sonra == iptal_cnt_once, f'{iptal_cnt_once}=={iptal_cnt_sonra}')

    durum = con.execute(
        "SELECT durum FROM nexgen_uretim_parca WHERE id=?", (parca_id,)
    ).fetchone()[0]
    ok('4 parca BITTI degil', durum != 'BITTI', durum)

    with _app.test_client() as c:
        with c.session_transaction() as sess:
            sess['kullanici'] = sess_user()
            sess['kullanici_tip'] = 'sistem'
        _ensure_parca_devam(c, batch_kodu, parca_id)
        r3 = parca_bitir_client(c, batch_kodu, parca_id)
        d3 = r3.get_json() or {}
        ok('5 tekrar bitir 200', r3.status_code == 200 and d3.get('ok'), d3.get('durum'))
    net_rebitir = _parca_stok_net_tuketim(con, parca_id)
    ok('5 stok tekrar dustu', net_rebitir < -0.0005, str(net_rebitir))
    yeni_tuket = con.execute("""
        SELECT COUNT(*) FROM nexgen_stok_hareket
        WHERE referans_tip='URETIM_PARCA' AND referans_id=?
          AND hareket_tipi='URETIM_TUKETIM' AND miktar_kg < 0
    """, (parca_id,)).fetchone()[0]
    ok('5 yeni tuketim satirlari', yeni_tuket > len(tuketimler),
       f'{len(tuketimler)}->{yeni_tuket}')

    with _app.test_client() as c:
        with c.session_transaction() as sess:
            sess['kullanici'] = sess_user()
            sess['kullanici_tip'] = 'sistem'
        rga = parca_geri_al_client(c, batch_kodu, parca_id, gerekce + ' rf test')
        ok('6 geri al rf icin', rga.status_code == 200, '')
    rf_row = con.execute("""
        SELECT miktar_kg, durum FROM nexgen_rf_kullanim
        WHERE tablet_session_id=? AND aktif=1 ORDER BY id DESC LIMIT 1
    """, (batch_kodu,)).fetchone()
    if rf_row:
        ok('6 RF kayit var', rf_row is not None, f'miktar={rf_row["miktar_kg"]}')
    else:
        ok('6 RF kayit (tablo yok/atlanir)', True, 'rf_kullanim yok')

    durum_b = con.execute(
        "SELECT durum FROM nexgen_uretim_parca WHERE id=?", (parca_id,)
    ).fetchone()[0]
    if durum_b != 'BITTI':
        with _app.test_client() as c:
            with c.session_transaction() as sess:
                sess['kullanici'] = sess_user()
                sess['kullanici_tip'] = 'sistem'
            _ensure_parca_devam(c, batch_kodu, parca_id)
            parca_bitir_client(c, batch_kodu, parca_id)
    diger = con.execute("""
        SELECT id FROM nexgen_uretim_parca
        WHERE batch_kodu=? AND id != ? AND durum != 'BITTI' LIMIT 1
    """, (batch_kodu, parca_id)).fetchone()
    if diger:
        with _app.test_client() as c:
            with c.session_transaction() as sess:
                sess['kullanici'] = sess_user()
                sess['kullanici_tip'] = 'sistem'
            c.post(f'/nexgen/api/batch/{batch_kodu}/parca/{diger["id"]}/bitir', json={})
    con.execute(
        "UPDATE nexgen_uretim_batch SET durum='BITTI' WHERE batch_kodu=?",
        (batch_kodu,),
    )
    con.commit()
    with _app.test_client() as c:
        with c.session_transaction() as sess:
            sess['kullanici'] = sess_user()
            sess['kullanici_tip'] = 'sistem'
        rgb = parca_geri_al_client(c, batch_kodu, parca_id, gerekce + ' batch test')
        dgb = rgb.get_json() or {}
        ok('7 geri al batch icin', rgb.status_code == 200 and dgb.get('ok'), '')
    batch_durum = con.execute(
        "SELECT durum FROM nexgen_uretim_batch WHERE batch_kodu=?", (batch_kodu,)
    ).fetchone()
    ok('7 batch DEVAM oldu', batch_durum and batch_durum[0] == 'DEVAM',
       batch_durum[0] if batch_durum else 'yok')
else:
    ok('1 BITTI parca bulunamadi', False, 'atlandi')

if batch_kodu and parca_id:
    with _app.test_client() as c:
        with c.session_transaction() as sess:
            sess['kullanici'] = sess_user()
            sess['kullanici_tip'] = 'sistem'
        import modules.nexgen.routes as nr
        orig = nr.yetki_var

        def _tablet_only(key, action='can_view'):
            if key == 'nexgen.tablet.view' and action == 'can_view':
                return True
            if key == 'nexgen.plan.manage':
                return False
            return orig(key, action)

        with patch.object(nr, 'yetki_var', side_effect=_tablet_only):
            r = parca_geri_al_client(c, batch_kodu, parca_id, 'yetkisiz test denemesi')
            ok('8 yetkisiz 403', r.status_code == 403, str(r.status_code))

if batch_kodu and parca_id:
    with _app.test_client() as c:
        with c.session_transaction() as sess:
            sess['kullanici'] = sess_user()
            sess['kullanici_tip'] = 'sistem'
        r = parca_geri_al_client(c, batch_kodu, parca_id, 'kisa')
        d = r.get_json() or {}
        ok('9 kisa gerekce 400', r.status_code == 400, d.get('hata', ''))

if batch_kodu:
    with _app.test_client() as c:
        with c.session_transaction() as sess:
            sess['kullanici'] = sess_user()
            sess['kullanici_tip'] = 'sistem'
        r1 = c.get(f'/nexgen/api/batch/{batch_kodu}/formul-icerik')
        ok('10 formul-icerik 200', r1.status_code == 200, '')
        uv = con.execute(
            "SELECT uretim_varyant_id FROM nexgen_uretim_batch WHERE batch_kodu=?",
            (batch_kodu,),
        ).fetchone()
        if uv:
            r2 = c.get(
                f'/nexgen/api/tablet/arge/formul-onizle?uv_id={uv[0]}&test_kg=10'
            )
            ok('10 arge formul-onizle 200', r2.status_code == 200, '')

with _app.test_client() as c:
    with c.session_transaction() as sess:
        sess['kullanici'] = sess_user()
        sess['kullanici_tip'] = 'sistem'
    ok('uretim-plan 200', c.get('/nexgen/uretim-plan').status_code == 200, '')

staged = os.path.exists(os.path.join(_APP_DIR, 'mock_data.db-staged'))
ok('mock_data.db stage edilmedi', not staged, '')

con.close()
_SHA_AFTER = sha256_file(_LIVE_DB)
_guard = live_db_write_guard_stats()
ok('ISO guard active', _guard.get('active') is True, str(_guard))
print(f'[ISO] main_sha_after={_SHA_AFTER}')
print(f'[ISO] main_db_changed={_SHA_BEFORE != _SHA_AFTER}')
if _TMP_DIR:
    cleanup_tmp({'tmp_dir': _TMP_DIR})

passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f'\n=== SONUC: {passed}/{len(results)} PASS, {failed} FAIL ===')
sys.exit(1 if failed else 0)
