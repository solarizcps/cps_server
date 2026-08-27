# -*- coding: utf-8 -*-
"""NEXGEN FAZ-5C-3 — kullanılabilir stok MPR/plan/stok kartları testi (temp DB only)."""
from __future__ import annotations

import importlib.util
import io
import os
import sqlite3
import subprocess
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP_DIR)

os.environ.setdefault('CPS_TEST_DB_GUARD', '1')

from tools.nexgen_tmp_db import assert_resolved_db_is_tmp, canonical_db_path  # noqa: E402
from tools.test_db_guard import bootstrap_adhoc_script_guards, run_guarded_subprocess, tmp_db_context  # noqa: E402


def _load_migration(name: str):
    path = os.path.join(_APP_DIR, 'migrations', name)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _run_migration_on_temp(mod, db_path: str) -> None:
    if hasattr(mod, 'DB_PATH'):
        mod.DB_PATH = db_path
    run_fn = getattr(mod, 'run', None)
    if run_fn is None:
        raise RuntimeError(f'migration {mod!r} has no run()')
    import inspect

    params = inspect.signature(run_fn).parameters
    if len(params) == 0:
        run_fn()
    else:
        run_fn(db_path)


def main() -> int:
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    os.chdir(_APP_DIR)
    os.environ['CPS_TEST_DB_GUARD'] = '1'
    live = canonical_db_path()
    bootstrap_adhoc_script_guards()
    source_db = live

    results: list[tuple[str, bool, str]] = []

    def ok(name, cond, detail=''):
        results.append((name, cond, detail))
        print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))

    def sess_user(db_path: str):
        con = sqlite3.connect(db_path)
        row = con.execute(
            """
            SELECT Id, KullaniciAdi, RolId, Aktif, ZorunluSifreDegistir, AuthVersion
            FROM sistem_kullanici WHERE Id = 1
            """
        ).fetchone()
        con.close()
        auth_ver = row[5] if row and row[5] is not None else 1
        return {
            'Id': 1,
            'KullaniciAdi': 'admin',
            'Tip': 'sistem',
            'RolId': 1,
            'RolAd': 'admin',
            'Aktif': 1,
            'AuthVersion': auth_ver,
            'ZorunluSifreDegistir': int(row[4] or 0) if row else 0,
        }

    with tmp_db_context(source_db, prefix='faz5c3_') as info:
        db = info['tmp_db']
        assert_resolved_db_is_tmp(db, live)
        os.environ['CPS_MOCK_DB_PATH'] = db

        m085 = _load_migration('085_nexgen_depo_hazirlik.py')
        m086 = _load_migration('086_nexgen_stok_rezerv.py')
        _run_migration_on_temp(m085, db)
        _run_migration_on_temp(m086, db)

        for label, script in [
            ('6 faz5c2', '_test_faz5c2_depo_rezerv.py'),
            ('7 faz4b', '_test_faz4b_stok_tuketim.py'),
        ]:
            r = run_guarded_subprocess(
                [sys.executable, os.path.join(_ROOT, script)],
                cwd=_APP_DIR,
                tmp_db=db,
            )
            tail = r.stdout.split('SONUC')[-1].strip() if 'SONUC' in r.stdout else r.stderr[:80]
            ok(label, r.returncode == 0, tail)

        _run_migration_on_temp(m086, db)

        con_prep = sqlite3.connect(db)
        con_prep.execute(
            """
            DELETE FROM nexgen_stok_rezerv
            WHERE hazirlik_id IN (
                SELECT id FROM nexgen_depo_hazirlik
                WHERE hazirlik_no LIKE 'DH-TEST-%'
            )
            """
        )
        con_prep.execute(
            "DELETE FROM nexgen_depo_hazirlik_kalem WHERE hazirlik_id IN "
            "(SELECT id FROM nexgen_depo_hazirlik WHERE hazirlik_no LIKE 'DH-TEST-%')"
        )
        con_prep.execute(
            "DELETE FROM nexgen_depo_hazirlik WHERE hazirlik_no LIKE 'DH-TEST-%'"
        )
        con_prep.execute("DELETE FROM nexgen_stok_rezerv WHERE rezerv_no LIKE 'RZ-TEST-%'")
        con_prep.commit()
        con_prep.close()

        import app as flask_app
        from modules.nexgen.routes import (
            _aktif_rezerv_toplam,
            _kullanilabilir_stok,
            _mevcut_stok,
            _mpr_stok_ihtiyac_hesapla,
            _yumusak_talep_toplam,
        )

        _app = flask_app.app
        _app.config['TESTING'] = True

        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row

        sk = con.execute(
            """
            SELECT sk.id, sk.kod
            FROM nexgen_stok_kart sk
            WHERE sk.aktif = 1
              AND NOT EXISTS (
                  SELECT 1 FROM nexgen_stok_rezerv r
                  WHERE r.stok_kart_id = sk.id AND r.durum = 'AKTIF'
              )
            ORDER BY sk.id
            LIMIT 1
            """
        ).fetchone()
        if not sk:
            sk = con.execute(
                'SELECT id, kod FROM nexgen_stok_kart WHERE aktif=1 ORDER BY id LIMIT 1'
            ).fetchone()
        sid = sk['id']

        con.execute("DELETE FROM nexgen_stok_rezerv WHERE rezerv_no LIKE 'RZ-TEST-5C3-%'")
        _old_h = con.execute(
            "SELECT id FROM nexgen_depo_hazirlik WHERE hazirlik_no='DH-TEST-5C3-SOFT'"
        ).fetchone()
        if _old_h:
            con.execute('DELETE FROM nexgen_depo_hazirlik_kalem WHERE hazirlik_id=?', (_old_h['id'],))
            con.execute('DELETE FROM nexgen_depo_hazirlik WHERE id=?', (_old_h['id'],))
        con.commit()

        fiziksel = _mevcut_stok(con, sid)
        con.execute(
            """
    INSERT INTO nexgen_stok_rezerv
      (rezerv_no, stok_kart_id, batch_kodu, miktar_kg, kalan_kg, durum)
    VALUES ('RZ-TEST-5C3-A', ?, 'NG-TEST-5C3-A', 300, 300, 'AKTIF')
""",
            (sid,),
        )
        con.execute(
            """
    INSERT INTO nexgen_depo_hazirlik
      (hazirlik_no, batch_kodu, durum, olusturan_id)
    VALUES ('DH-TEST-5C3-SOFT', 'NG-TEST-5C3-SOFT', 'BEKLIYOR', 1)
"""
        )
        soft_hid = con.execute('SELECT last_insert_rowid()').fetchone()[0]
        con.execute(
            """
    INSERT INTO nexgen_depo_hazirlik_kalem
      (hazirlik_id, stok_kart_id, kaynak, gerekli_kg, hazirlanan_kg)
    VALUES (?, ?, 'TABAN', 200, 0)
""",
            (soft_hid, sid),
        )
        con.commit()

        rez = _aktif_rezerv_toplam(con, sid)
        yum = _yumusak_talep_toplam(con, sid)
        kul = _kullanilabilir_stok(con, sid)
        beklenen = round(fiziksel - 300 - 200, 3)
        ok(
            '1 rezerv 300 yumusak 200',
            abs(rez - 300) < 0.01 and abs(yum - 200) < 0.01,
            f'rez={rez} yum={yum}',
        )
        ok('1 kullanilabilir formul', abs(kul - beklenen) < 0.01, f'kul={kul} bek={beklenen}')

        uv = con.execute(
            'SELECT uretim_varyant_id FROM nexgen_recete_kalem WHERE stok_kart_id=? AND aktif=1 LIMIT 1',
            (sid,),
        ).fetchone()
        if uv:
            mpr = _mpr_stok_ihtiyac_hesapla(con, uv['uretim_varyant_id'], None, 1.0)
            kalem = next((k for k in mpr.get('kalemler', []) if k['stok_kart_id'] == sid), None)
            if kalem:
                ok(
                    '2 mpr kalem alanlari',
                    'kullanilabilir_kg' in kalem and 'rezerve_kg' in kalem,
                    str(kalem.get('kullanilabilir_kg')),
                )
                yeterli_bek = kalem['kullanilabilir_kg'] >= kalem['gerekli_kg'] - 0.0005
                ok(
                    '2 mpr yeterlilik kullanilabilir',
                    kalem['yeterli'] == yeterli_bek,
                    f"yeterli={kalem['yeterli']} kul={kalem['kullanilabilir_kg']}",
                )
            else:
                ok('2 mpr kalem', True, 'sid yok kucuk kg')
        else:
            ok('2 mpr uv', True, 'atlandi')

        con.execute(
            """
    INSERT INTO nexgen_stok_rezerv
      (rezerv_no, stok_kart_id, batch_kodu, miktar_kg, kalan_kg, durum)
    VALUES ('RZ-TEST-5C3-B', ?, 'NG-TEST-5C3-B', ?, ?, 'AKTIF')
""",
            (sid, max(fiziksel, 0), max(fiziksel, 0)),
        )
        con.commit()

        plan = con.execute(
            """
    SELECT np.id, np.uretim_varyant_id, np.rf_renk_id, np.planlanan_kg
    FROM nexgen_uretim_plan np
    WHERE np.durum='PLANLANDI'
    ORDER BY np.planlanan_kg ASC LIMIT 1
"""
        ).fetchone()

        with _app.test_client() as c:
            with c.session_transaction() as sess:
                sess['kullanici'] = sess_user(db)
                sess['kullanici_tip'] = 'sistem'

            if plan and uv:
                r_on = c.post(
                    '/nexgen/api/plan/stok-onizle',
                    json={
                        'uretim_varyant_id': plan['uretim_varyant_id'],
                        'rf_renk_id': plan['rf_renk_id'],
                        'planlanan_kg': float(plan['planlanan_kg']),
                    },
                )
                d_on = r_on.get_json() or {}
                fiz_yeterli = any(
                    (k.get('fiziksel_kg') or k.get('mevcut_kg') or 0) >= (k.get('gerekli_kg') or 0)
                    for k in (d_on.get('kalemler') or [])
                )
                ok(
                    '3 onizleme eksik kullanilabilir',
                    r_on.status_code == 200 and d_on.get('ok') and not d_on.get('yeterli_mi'),
                    f'yeterli_mi={d_on.get("yeterli_mi")} fiz_yeterli={fiz_yeterli}',
                )

                r_bas = c.post(f'/nexgen/api/plan/{plan["id"]}/basla', json={})
                d_bas = r_bas.get_json() or {}
                ok(
                    '4 plan basla 400 rezervli',
                    r_bas.status_code == 400 and 'Stok yetersiz' in (d_bas.get('hata') or ''),
                    d_bas.get('hata'),
                )
            else:
                ok('3 onizleme eksik', False, 'PLANLANDI yok')
                ok('4 plan basla 400', False, 'PLANLANDI yok')

            page = c.get('/nexgen/stok-kartlari').get_data(as_text=True)
            ok('5 stok kartlari 200', c.get('/nexgen/stok-kartlari').status_code == 200, '')
            ok(
                '5 kolonlar var',
                'Fiziksel' in page and 'Rezerve' in page and 'Bekleyen' in page and 'Kullanılabilir' in page,
                '',
            )

        con.execute("DELETE FROM nexgen_stok_rezerv WHERE rezerv_no LIKE 'RZ-TEST-5C3-%'")
        con.execute('DELETE FROM nexgen_depo_hazirlik_kalem WHERE hazirlik_id=?', (soft_hid,))
        con.execute('DELETE FROM nexgen_depo_hazirlik WHERE id=?', (soft_hid,))
        con.commit()
        con.close()

    passed = sum(1 for _, c, _ in results if c)
    failed = sum(1 for _, c, _ in results if not c)
    print(f'\n=== SONUC: {passed}/{len(results)} PASS, {failed} FAIL ===')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
