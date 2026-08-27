# -*- coding: utf-8 -*-
"""NEXGEN FAZ-5C-2 — depo HAZIR anında AKTIF rezerv oluşturma testi."""
from __future__ import annotations

import importlib.util
import io
import os
import sqlite3
import sys
import tempfile
import shutil

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
from tools.test_db_guard import bootstrap_adhoc_script_guards, run_guarded_subprocess  # noqa: E402


def _run_auth_version_migration(db_path: str) -> None:
    path = os.path.join(_APP_DIR, 'migrations', '150_sistem_kullanici_auth_version.py')
    spec = importlib.util.spec_from_file_location('150_sistem_kullanici_auth_version.py', path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    mod.run(db_path)


def _resolve_test_db():
    live = canonical_db_path()
    bootstrap_adhoc_script_guards()
    parent_tmp = os.environ.get('CPS_MOCK_DB_PATH', '').strip()
    if parent_tmp:
        db = os.path.abspath(parent_tmp)
        assert_resolved_db_is_tmp(db, live)
        os.environ['CPS_MOCK_DB_PATH'] = db
        return db, live, None, True

    tmp_dir = tempfile.mkdtemp(prefix='faz5c2_')
    db = os.path.join(tmp_dir, 'mock_data_test.db')
    shutil.copy2(live, db)
    assert_resolved_db_is_tmp(db, live)
    os.environ['CPS_MOCK_DB_PATH'] = db
    return db, live, tmp_dir, False


_LIVE_DB = canonical_db_path()
_SHA_BEFORE = sha256_file(_LIVE_DB)
DB, _CANONICAL, _TMP_DIR, _PARENT_OWNED = _resolve_test_db()
print(f'[ISO] tmp_db={DB}')
print(f'[ISO] parent_owned={_PARENT_OWNED}')
print(f'[ISO] main_sha_before={_SHA_BEFORE}')

for _mig in ('085_nexgen_depo_hazirlik.py', '086_nexgen_stok_rezerv.py'):
    _p = os.path.join(_APP_DIR, 'migrations', _mig)
    _spec = importlib.util.spec_from_file_location(_mig, _p)
    _mod = importlib.util.module_from_spec(_spec)
    assert _spec.loader is not None
    _spec.loader.exec_module(_mod)
    _mod.DB_PATH = DB
    _mod.run()
    if _mig.startswith('086'):
        _m086 = _mod

import config as _cfg
_cfg.Config.MOCK_DB_PATH = DB
import app as flask_app
import modules.nexgen.routes as nx_routes
from modules.nexgen.routes import (
    _depo_hazirlik_olustur, _depo_hazirlik_kalemleri,
    _kullanilabilir_stok, _aktif_rezerv_toplam, _mevcut_stok,
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


def hazirlik_hazir(c, hid):
    return c.post(f'/nexgen/api/depo/hazirlik/{hid}/hazir', json={})


def _cleanup_test_artifacts(db_path: str) -> None:
    con = sqlite3.connect(db_path)
    for _no in ('DH-TEST-5C2-OK', 'DH-TEST-YETERSIZ-5C2'):
        _old = con.execute(
            "SELECT id FROM nexgen_depo_hazirlik WHERE hazirlik_no=?", (_no,)
        ).fetchone()
        if _old:
            con.execute("DELETE FROM nexgen_stok_rezerv WHERE hazirlik_id=?", (_old['id'],))
            con.execute("DELETE FROM nexgen_depo_hazirlik_kalem WHERE hazirlik_id=?", (_old['id'],))
            con.execute("DELETE FROM nexgen_depo_hazirlik WHERE id=?", (_old['id'],))
    con.commit()
    con.close()


_cleanup_test_artifacts(DB)


def _restore_db_from_snapshot(snapshot: str, db_path: str) -> None:
    for suffix in ('-wal', '-shm'):
        sidecar = db_path + suffix
        if os.path.isfile(sidecar):
            try:
                os.remove(sidecar)
            except OSError:
                pass
    shutil.copy2(snapshot, db_path)
    for suffix in ('-wal', '-shm'):
        sidecar = db_path + suffix
        if os.path.isfile(sidecar):
            try:
                os.remove(sidecar)
            except OSError:
                pass


# Subprocess regresyon — reg_bak öncesi; her child için temiz temp snapshot
if not _PARENT_OWNED:
    _pre_sub_snapshot = DB + '.pre_subprocess_snapshot'
    shutil.copy2(DB, _pre_sub_snapshot)
    assert_resolved_db_is_tmp(_pre_sub_snapshot, _CANONICAL)
    try:
        for label, script in [
            ('7 faz4b', '_test_faz4b_stok_tuketim.py'),
            ('8 faz4d', '_test_faz4d_parca_geri_al.py'),
        ]:
            _restore_db_from_snapshot(_pre_sub_snapshot, DB)
            r = run_guarded_subprocess(
                [sys.executable, os.path.join(_ROOT, script)],
                cwd=_APP_DIR,
                tmp_db=DB,
            )
            tail = r.stdout.split('SONUC')[-1].strip() if 'SONUC' in r.stdout else ''
            err_tail = (r.stderr or '').strip()[-500:]
            detail = tail or err_tail or f'rc={r.returncode}'
            ok(label, r.returncode == 0, detail)
    finally:
        if os.path.exists(_pre_sub_snapshot):
            os.remove(_pre_sub_snapshot)

# Regresyon için temiz snapshot — yalnız standalone modda temp DB'ye kopyala
_reg_bak = os.path.join(_APP_DIR, 'mock_data.db.bak_faz5c2_20260624')
if not _PARENT_OWNED and os.path.exists(_reg_bak):
    for suffix in ('-wal', '-shm'):
        sidecar = DB + suffix
        if os.path.isfile(sidecar):
            try:
                os.remove(sidecar)
            except OSError:
                pass
    shutil.copy2(_reg_bak, DB)
    assert_resolved_db_is_tmp(DB, _CANONICAL)
    _run_auth_version_migration(DB)

# Regresyon snapshot geri yüklendiyse migration 086 tekrar
if not _PARENT_OWNED and os.path.exists(_reg_bak):
    _m086.run()

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row


def hazirlik_stok_yeterli(con, hazirlik_id):
    hdr = con.execute(
        "SELECT batch_kodu FROM nexgen_depo_hazirlik WHERE id=?", (hazirlik_id,)
    ).fetchone()
    if not hdr:
        return False
    kalemler = con.execute("""
        SELECT stok_kart_id, gerekli_kg, hazirlanan_kg
        FROM nexgen_depo_hazirlik_kalem WHERE hazirlik_id=?
    """, (hazirlik_id,)).fetchall()
    talep = {}
    for k in kalemler:
        hk = float(k['hazirlanan_kg'] or 0)
        gk = float(k['gerekli_kg'] or 0)
        miktar = round(hk if hk > 0 else gk, 3)
        if miktar <= 0:
            continue
        sid = k['stok_kart_id']
        talep[sid] = round(talep.get(sid, 0) + miktar, 3)
    for sid, miktar in talep.items():
        kul = _kullanilabilir_stok(con, sid, exclude_batch_kodu=hdr['batch_kodu'])
        if kul < miktar - 0.0005:
            return False
    return bool(talep)


def test_hazirlik_olustur(con):
    """Küçük miktarlı TABAN+RF kalemli test hazırlığı (stok hareketi yazmaz)."""
    batch_kodu = 'NG-TEST-5C2-OK'

    def _uygun_kart(kaynak=None):
        q = """
            SELECT k.stok_kart_id, k.kaynak
            FROM nexgen_depo_hazirlik_kalem k
            JOIN nexgen_depo_hazirlik h ON h.id = k.hazirlik_id
        """
        params = []
        if kaynak:
            q += " WHERE k.kaynak=?"
            params.append(kaynak)
        q += " ORDER BY h.id DESC, k.id"
        for row in con.execute(q, params).fetchall():
            sid = row['stok_kart_id']
            if _kullanilabilir_stok(con, sid, exclude_batch_kodu=batch_kodu) >= 0.01:
                return sid
        for row in con.execute(
            "SELECT id FROM nexgen_stok_kart WHERE aktif=1 ORDER BY id"
        ).fetchall():
            sid = row['id']
            if _kullanilabilir_stok(con, sid, exclude_batch_kodu=batch_kodu) >= 0.01:
                return sid
        return None

    taban_sid = _uygun_kart('TABAN')
    rf_sid = _uygun_kart('RF')
    ok_kart = taban_sid or rf_sid
    if not ok_kart:
        return None, batch_kodu

    con.execute("""
        INSERT INTO nexgen_depo_hazirlik
          (hazirlik_no, batch_kodu, durum, olusturan_id)
        VALUES ('DH-TEST-5C2-OK', ?, 'BEKLIYOR', 1)
    """, (batch_kodu,))
    hid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    if taban_sid:
        con.execute("""
            INSERT INTO nexgen_depo_hazirlik_kalem
              (hazirlik_id, stok_kart_id, kaynak, gerekli_kg, hazirlanan_kg)
            VALUES (?, ?, 'TABAN', 0.001, 0)
        """, (hid, taban_sid))
    if rf_sid and rf_sid != taban_sid:
        con.execute("""
            INSERT INTO nexgen_depo_hazirlik_kalem
              (hazirlik_id, stok_kart_id, kaynak, gerekli_kg, hazirlanan_kg)
            VALUES (?, ?, 'RF', 0.001, 0)
        """, (hid, rf_sid))
    elif not taban_sid and rf_sid:
        con.execute("""
            INSERT INTO nexgen_depo_hazirlik_kalem
              (hazirlik_id, stok_kart_id, kaynak, gerekli_kg, hazirlanan_kg)
            VALUES (?, ?, 'RF', 0.001, 0)
        """, (hid, rf_sid))
    con.commit()
    return hid, batch_kodu


# BEKLIYOR hazırlık — stok yeterli olanı seç
adaylar = con.execute("""
    SELECT h.id, h.batch_kodu, h.durum
    FROM nexgen_depo_hazirlik h
    WHERE h.durum IN ('BEKLIYOR', 'HAZIRLANIYOR')
      AND NOT EXISTS (
          SELECT 1 FROM nexgen_stok_rezerv r
          WHERE r.hazirlik_id = h.id AND r.durum = 'AKTIF'
      )
    ORDER BY h.id DESC
""").fetchall()

haz = None
test_hazirlik_id = None
for ad in adaylar:
    if hazirlik_stok_yeterli(con, ad['id']):
        haz = ad
        break

if not haz:
    test_hazirlik_id, test_batch = test_hazirlik_olustur(con)
    if test_hazirlik_id:
        haz = con.execute(
            "SELECT id, batch_kodu, durum FROM nexgen_depo_hazirlik WHERE id=?",
            (test_hazirlik_id,),
        ).fetchone()

ok('bekleyen hazirlik var', haz is not None, str(dict(haz) if haz else ''))
hazirlik_id = haz['id'] if haz else None
batch_kodu = haz['batch_kodu'] if haz else None

kalemler = _depo_hazirlik_kalemleri(con, hazirlik_id) if hazirlik_id else []
kalem_sayisi = len(kalemler)
taban_n = sum(1 for k in kalemler if k.get('kaynak') == 'TABAN')
rf_n = sum(1 for k in kalemler if k.get('kaynak') == 'RF')

# Test stok kartı — kullanılabilir ölçüm
ornek_sid = kalemler[0]['stok_kart_id'] if kalemler else None
kul_oncesi = _kullanilabilir_stok(con, ornek_sid, exclude_batch_kodu=batch_kodu) if ornek_sid else 0
rez_oncesi = _aktif_rezerv_toplam(con, ornek_sid) if ornek_sid else 0

h_stok_before = con.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]

with _app.test_client() as c:
    with c.session_transaction() as sess:
        sess['kullanici'] = sess_user()
        sess['kullanici_tip'] = 'sistem'

    if hazirlik_id:
        r1 = hazirlik_hazir(c, hazirlik_id)
        d1 = r1.get_json() or {}
        ok('1 depo hazir aktif rezerv', r1.status_code == 200 and d1.get('ok'),
           f"rezerv={d1.get('rezerv_sayisi')}")

        rez_cnt = con.execute("""
            SELECT COUNT(*) FROM nexgen_stok_rezerv
            WHERE hazirlik_id=? AND durum='AKTIF'
        """, (hazirlik_id,)).fetchone()[0]
        ok('2 kalem sayisi dogru', rez_cnt == kalem_sayisi, f'{rez_cnt}=={kalem_sayisi}')
        ok('3 taban rf rezerv', taban_n > 0 and rf_n >= 0, f'taban={taban_n} rf={rf_n}')

        kaynak = con.execute("""
            SELECT kaynak_tip FROM nexgen_stok_rezerv
            WHERE hazirlik_id=? AND durum='AKTIF' LIMIT 1
        """, (hazirlik_id,)).fetchone()
        ok('3 kaynak DEPO_HAZIRLIK', kaynak and kaynak[0] == 'DEPO_HAZIRLIK', kaynak[0] if kaynak else '')

        cnt_once = rez_cnt
        r2 = hazirlik_hazir(c, hazirlik_id)
        d2 = r2.get_json() or {}
        cnt_twice = con.execute("""
            SELECT COUNT(*) FROM nexgen_stok_rezerv
            WHERE hazirlik_id=? AND durum='AKTIF'
        """, (hazirlik_id,)).fetchone()[0]
        ok('4 tekrar hazir duplicate yok', cnt_twice == cnt_once,
           f'once={cnt_once} twice={cnt_twice} status={r2.status_code}')

        # Stok yetersiz senaryo
        con.execute("""
            INSERT INTO nexgen_depo_hazirlik
              (hazirlik_no, batch_kodu, durum, olusturan_id)
            VALUES ('DH-TEST-YETERSIZ-5C2', 'NG-TEST-YETERSIZ-5C2', 'BEKLIYOR', 1)
        """)
        yetersiz_hid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        sk = con.execute(
            "SELECT id FROM nexgen_stok_kart WHERE aktif=1 ORDER BY id LIMIT 1"
        ).fetchone()[0]
        con.execute("""
            INSERT INTO nexgen_depo_hazirlik_kalem
              (hazirlik_id, stok_kart_id, kaynak, gerekli_kg, hazirlanan_kg)
            VALUES (?, ?, 'TABAN', 999999999, 0)
        """, (yetersiz_hid, sk))
        con.commit()

        r5 = hazirlik_hazir(c, yetersiz_hid)
        d5 = r5.get_json() or {}
        y_rez = con.execute("""
            SELECT COUNT(*) FROM nexgen_stok_rezerv WHERE hazirlik_id=?
        """, (yetersiz_hid,)).fetchone()[0]
        y_durum = con.execute(
            "SELECT durum FROM nexgen_depo_hazirlik WHERE id=?", (yetersiz_hid,)
        ).fetchone()[0]
        ok('5 stok yetersiz rezerv yok', y_rez == 0 and y_durum != 'HAZIR',
           f'rez={y_rez} durum={y_durum}')
        ok('5 stok yetersiz 400', r5.status_code == 400 and 'yetersiz' in (d5.get('hata') or '').lower(),
           d5.get('hata'))
        ok('5 eksik liste', len(d5.get('eksik_kalemler') or []) > 0,
           str(d5.get('eksik_sayisi')))

        con.execute("DELETE FROM nexgen_depo_hazirlik_kalem WHERE hazirlik_id=?", (yetersiz_hid,))
        con.execute("DELETE FROM nexgen_depo_hazirlik WHERE id=?", (yetersiz_hid,))
        con.commit()

if ornek_sid and hazirlik_id:
    kul_sonra = _kullanilabilir_stok(con, ornek_sid)
    rez_sonra = _aktif_rezerv_toplam(con, ornek_sid)
    ornek_miktar = next(
        (float(k['gerekli_kg']) for k in kalemler if k['stok_kart_id'] == ornek_sid), 0.001
    )
    ok('6 kullanilabilir dusuyor',
       rez_sonra >= rez_oncesi + ornek_miktar - 0.01 or kul_sonra < kul_oncesi - 0.0005,
       f'kul {kul_oncesi}->{kul_sonra} rez {rez_oncesi}->{rez_sonra}')

h_stok_after = con.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
ok('stok hareket yazilmadi', h_stok_before == h_stok_after, f'{h_stok_before}=={h_stok_after}')

if test_hazirlik_id:
    con.execute("DELETE FROM nexgen_stok_rezerv WHERE hazirlik_id=?", (test_hazirlik_id,))
    con.execute("DELETE FROM nexgen_depo_hazirlik_kalem WHERE hazirlik_id=?", (test_hazirlik_id,))
    con.execute("DELETE FROM nexgen_depo_hazirlik WHERE id=?", (test_hazirlik_id,))
    con.commit()

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
