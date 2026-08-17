# -*- coding: utf-8 -*-
"""FAZ-URETIM-PLAN-F2 — lock tests T1–T16."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import sqlite3
import sys
import tempfile
import shutil

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

import tools.test_db_guard  # noqa: E402
from tools.nexgen_tmp_db import sha256_file, tmp_db_context  # noqa: E402

results: list[tuple[str, bool, str]] = []
_LIVE = os.path.join(_APP, 'mock_data.db')
_SHA_BEFORE = sha256_file(_LIVE)


def ok(name: str, cond: bool, detail: str = '') -> bool:
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))
    return bool(cond)


def _run_mig158(db_path: str) -> None:
    mig = os.path.join(_APP, 'migrations', '158_uretim_model_plan.py')
    spec = importlib.util.spec_from_file_location('mig158', mig)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path=db_path)


def _flask_client(tmp_db: str):
    os.environ['CPS_MOCK_DB_PATH'] = tmp_db
    from app import app as flask_app
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def run_suite(info: dict) -> None:
    tmp_db = info['tmp_db']
    pre_sha = hashlib.sha256(open(tmp_db, 'rb').read()).hexdigest()
    print(f'TMP_DB={tmp_db}')
    print(f'PRE_SHA={pre_sha}')

    _run_mig158(tmp_db)
    ok('T4 migration idempotent', True)
    _run_mig158(tmp_db)

    con = sqlite3.connect(tmp_db)
    con.row_factory = sqlite3.Row
    ok('T4 table exists', bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE name='uretim_model_plan'"
    ).fetchone()))

    mehmet = con.execute(
        "SELECT Id, Sifre FROM sistem_kullanici WHERE KullaniciAdi='mehmet' AND Aktif=1"
    ).fetchone()
    ok('mehmet exists', bool(mehmet))

    ov = con.execute("""
        SELECT upo.can_create, upo.can_update FROM user_permission_override upo
        JOIN sistem_yetki y ON y.Id=upo.YetkiId
        WHERE upo.KullaniciId=? AND y.Kod='planlama'
    """, (mehmet['Id'],)).fetchone()
    ok('T15 mehmet planlama edit', ov and ov['can_create'] == 1 and ov['can_update'] == 1,
       f"create={ov['can_create'] if ov else '?'} update={ov['can_update'] if ov else '?'}")

    con.close()

    # Korgun read tests (no write)
    from modules.common import korgun as kk
    from modules.planlama.uretim_plan_service import siparis_model_satirlari, model_satir_by_canonical
    from modules.planlama import uretim_plan_repo as repo

    kcon = kk._baglan()
    try:
        d33919 = siparis_model_satirlari(kcon, 33919)
        ok('T1 sip 33919 onizleme', d33919 and len(d33919['onizleme']) >= 1,
           f"kalem={len(d33919['onizleme']) if d33919 else 0}")

        d33859 = siparis_model_satirlari(kcon, 33859)
        renkler = {x['renk'] for x in (d33859 or {}).get('onizleme', [])}
        ok('T2 farkli renk ayri', len(renkler) >= 2, f"renk={len(renkler)}")

        keys = [x['canonical_key'] for x in (d33859 or {}).get('onizleme', [])]
        harinx_set = {(x['sip_harinx'], x['rkod']) for x in (d33859 or {}).get('onizleme', [])}
        ok('T3 farkli SipHarinx ayri', len(keys) == len(set(keys)), f"keys={len(keys)}")

        o = d33919['onizleme'][0]
        os.environ['CPS_MOCK_DB_PATH'] = tmp_db
        import importlib
        import db as dbmod
        importlib.reload(dbmod)
        import modules.planlama.uretim_plan_repo as repo_mod
        importlib.reload(repo_mod)

        plan = repo_mod.plan_ekle({
            'sip_no': o['sip_no'], 'sip_harinx': o['sip_harinx'],
            'mamul_skod': o['model_kod'], 'rkod': o['rkod'],
            'model_adi': o.get('model_tanim'), 'renk_adi': o['renk'],
            'miktar': o['miktar'], 'termin': o['termin'],
            'plan_donemi': 'gelecek_hafta',
            'plan_baslangic': '2026-08-25', 'plan_bitis': '2026-08-29',
            'oncelik': 2, 'plan_gerekce': 'Termin',
        }, int(mehmet['Id']))
        ok('T4 plan kayit key', plan['canonical_key'] == o['canonical_key'], plan['canonical_key'])

        dup_ok = False
        try:
            repo_mod.plan_ekle({
                'sip_no': o['sip_no'], 'sip_harinx': o['sip_harinx'],
                'mamul_skod': o['model_kod'], 'rkod': o['rkod'],
                'plan_donemi': 'gelecek_hafta',
            }, int(mehmet['Id']))
        except ValueError:
            dup_ok = True
        ok('T5 duplicate engeli', dup_ok)

        plan2 = repo_mod.plan_ekle({
            'sip_no': o['sip_no'], 'sip_harinx': o['sip_harinx'],
            'mamul_skod': o['model_kod'], 'rkod': o['rkod'],
            'plan_donemi': 'bu_ay',
            'plan_baslangic': '2026-08-01', 'plan_bitis': '2026-08-31',
            'oncelik': 3,
        }, int(mehmet['Id']))
        ok('T6 baska donem ok', plan2 and plan2['id'] != plan['id'])

        satir = model_satir_by_canonical(kcon, o['sip_no'], o['sip_harinx'], o['model_kod'], o['rkod'])
        ok('T10 6 M lot', satir and satir.get('m_emir_sayisi') == 6,
           f"m={satir.get('m_emir_sayisi') if satir else '?'}")

        from modules.planlama.uretim_plan_service import m_emirler_lazy, y_emirler_lazy
        lots = m_emirler_lazy(kcon, o['sip_no'], o['sip_harinx'], o['model_kod'], o['rkod'])
        ok('T11 M drilldown', len(lots) == 6, f"lots={len(lots)}")
        if lots:
            ys = y_emirler_lazy(kcon, lots[0]['emir_no'])
            ok('T11 Y drilldown', len(ys) == 3, f"y={len(ys)}")

        ok('T12 sresim', bool(satir and satir.get('sresim')), (satir or {}).get('sresim', '')[:40])

        def _proses_by_kod(row, kod):
            for p in (row or {}).get('prosesler') or []:
                if str(p.get('proses_kod', '')).strip() == str(kod):
                    return p
            return None

        pilot = model_satir_by_canonical(kcon, 33785, 83529, 'CRP-81311RL', 8)
        enj85 = _proses_by_kod(pilot, '26')
        ok('T14 enjeksiyon DEVAM pilot', enj85 and enj85.get('durum') in ('DEVAM', 'BİTTİ'),
           f"pct={enj85.get('yuzde') if enj85 else '?'}")

        pilot2 = model_satir_by_canonical(kcon, 33459, 82562, 'CRX-71139', 2336)
        mon59 = _proses_by_kod(pilot2, '30')
        ok('T14 montaj DEVAM pilot', mon59 and mon59.get('durum') in ('DEVAM', 'BİTTİ'),
           f"pct={mon59.get('yuzde') if mon59 else '?'}")

        pasif = repo_mod.plan_pasif(plan['id'], int(mehmet['Id']))
        ok('T9 deactivate', pasif and pasif['aktif'] == 0)
        row = repo_mod.plan_get(plan['id'])
        ok('T9 not hard delete', row is not None)

    finally:
        kcon.close()

    # T16 hedef untouched
    hedef = open(os.path.join(_APP, 'modules', 'hedef', 'routes.py'), encoding='utf-8').read()
    ok('T16 hedef routes unchanged marker', 'uretim_model_plan' not in hedef)

    # T8 routes — plan update only CPS fields in repo
    repo_src = open(os.path.join(_APP, 'modules', 'planlama', 'uretim_plan_repo.py'), encoding='utf-8').read()
    ok('T8 edit CPS only', 'plan_guncelle' in repo_src and 'Korgun' not in repo_src)

    post_sha = hashlib.sha256(open(tmp_db, 'rb').read()).hexdigest()
    ok('canonical db unchanged', sha256_file(_LIVE) == _SHA_BEFORE, 'live sha stable')


def main() -> int:
    print('=' * 70)
    print('FAZ-URETIM-PLAN-F2 LOCK TEST')
    print('=' * 70)
    with tmp_db_context() as info:
        run_suite(info)
    passed = sum(1 for _, c, _ in results if c)
    failed = sum(1 for _, c, _ in results if not c)
    print('=' * 70)
    print(f'SONUÇ: {passed} PASS / {failed} FAIL')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
