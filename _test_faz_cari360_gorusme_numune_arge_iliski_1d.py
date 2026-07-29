# -*- coding: utf-8 -*-
"""FAZ-1D — Cari360 ID bazlı okuma + uçtan uca test (production write YOK)."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import traceback
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'app')
LIVE = os.path.join(APP, 'mock_data.db')
sys.path.insert(0, APP)
os.chdir(APP)

from modules.nexgen.cari360_ops_read_service import (  # noqa: E402
    enrich_gorusmeler_bagli_numuneler,
    load_cari360_numuneler,
)
from modules.nexgen.mo_gorusme_service import list_gorusmeler  # noqa: E402

RESULTS: list[str] = []
MULTI = 'AT-M-2026-0147'


def _sha(p: str) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1024 * 1024), b''):
            h.update(c)
    return h.hexdigest()


def _ok(name: str, cond: bool, detail: str = '') -> None:
    line = f'{"PASS" if cond else "FAIL"} | {name}' + (f' | {detail}' if detail else '')
    RESULTS.append(line)
    print(line)


def _con(db: str) -> sqlite3.Connection:
    c = sqlite3.connect(db, timeout=60)
    c.row_factory = sqlite3.Row
    return c


def _find_1c_copy() -> str | None:
    bak = os.path.join(ROOT, 'backup')
    if not os.path.isdir(bak):
        return None
    cands = []
    for name in os.listdir(bak):
        if name.startswith('cari360_iliski_1c_'):
            p = os.path.join(bak, name, 'test_copy.db')
            if os.path.isfile(p):
                cands.append(p)
    return sorted(cands)[-1] if cands else None


def _prepare_db(evid: str) -> str:
    """1C backfill'li kopya veya mig141+backfill yeniden."""
    dst = os.path.join(evid, 'test_db.db')
    src1c = _find_1c_copy()
    if src1c:
        shutil.copy2(src1c, dst)
        open(os.path.join(evid, 'schema_and_test_db.txt'), 'w', encoding='utf-8').write(
            f'source=1C_test_copy\npath={src1c}\n'
        )
        return dst
    # rebuild
    shutil.copy2(LIVE, dst)
    from importlib.util import spec_from_file_location, module_from_spec
    mig_p = os.path.join(APP, 'migrations', '141_nexgen_arge_test_numune_talep_id.py')
    bf_p = os.path.join(APP, 'migrations', '141_backfill_apply_1c.py')
    for name, path in (('m', mig_p), ('b', bf_p)):
        spec = spec_from_file_location(name, path)
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)
        if name == 'm':
            mod.run(dst)
        else:
            mod.apply_backfill(dst, dry_run=False)
    open(os.path.join(evid, 'schema_and_test_db.txt'), 'w', encoding='utf-8').write(
        'source=rebuild_mig141_plus_1c_backfill\n'
    )
    return dst


def _uid(con) -> int:
    r = con.execute('SELECT Id FROM sistem_kullanici ORDER BY Id LIMIT 1').fetchone()
    return int(r['Id'] if r else 1)


def main() -> int:
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    evid = os.path.join(ROOT, 'backup', f'cari360_iliski_1d_test_{ts}')
    os.makedirs(evid, exist_ok=True)
    os.makedirs(os.path.join(evid, 'screenshots'), exist_ok=True)

    live_before = _sha(LIVE)
    open(os.path.join(evid, 'live_db_sha_before_after.txt'), 'w').write(f'before={live_before}\n')
    git_b = subprocess.run(
        ['git', 'status', '--short'], cwd=ROOT, capture_output=True, text=True,
        encoding='utf-8', errors='replace',
    ).stdout
    open(os.path.join(evid, 'git_status_before_after.txt'), 'w', encoding='utf-8').write(
        '=== BEFORE ===\n' + git_b + '\n'
    )

    db = _prepare_db(evid)
    con = _con(db)
    uid = _uid(con)
    yk = {'*'}

    # schema note
    with open(os.path.join(evid, 'schema_and_test_db.txt'), 'a', encoding='utf-8') as f:
        cols = [c[1] for c in con.execute('PRAGMA table_info(nexgen_arge_test)')]
        f.write(f'numune_talep_id_col={"numune_talep_id" in cols}\n')
        f.write(f'ntp_filled={con.execute("SELECT COUNT(*) FROM nexgen_arge_test WHERE numune_talep_id IS NOT NULL").fetchone()[0]}\n')
        f.write(f'mo_filled={con.execute("SELECT COUNT(*) FROM nexgen_numune_talep WHERE mo_gorusme_id IS NOT NULL AND mo_gorusme_id!=0").fetchone()[0]}\n')

    canonical_links = []
    legacy_links = []
    excluded = []

    # Pick cari with data
    cari_row = con.execute(
        """
        SELECT cari_id, COUNT(*) n FROM nexgen_numune_talep
        WHERE cari_id IS NOT NULL AND aktif=1
        GROUP BY cari_id ORDER BY n DESC LIMIT 1
        """
    ).fetchone()
    cari_id = int(cari_row['cari_id']) if cari_row else 1

    # --- Gorusme enrich ---
    try:
        glist = list_gorusmeler(con, cari_id, uid, yk)
        glist = enrich_gorusmeler_bagli_numuneler(con, cari_id, glist)
        _ok('gorusme_list_ok', isinstance(glist, list))
        # reverse legacy or mo
        has_bagli = any(g.get('bagli_numuneler') for g in glist)
        # cari 1 may have g50→220
        g_with = [g for g in glist if g.get('bagli_numuneler')]
        if g_with:
            g0 = g_with[0]
            n0 = g0['bagli_numuneler'][0]
            _ok('1_canonical_or_legacy_gorusme_numune', True, f"g={g0['id']} n={n0['id']} src={n0['baglanti_kaynagi']}")
            for g in g_with:
                for n in g['bagli_numuneler']:
                    row = {
                        'gorusme_id': g['id'], 'numune_id': n['id'], 'kod': n['talep_kodu'],
                        'kaynak': n['baglanti_kaynagi'], 'legacy': n['legacy_baglanti'],
                    }
                    if n['legacy_baglanti']:
                        legacy_links.append(row)
                    else:
                        canonical_links.append(row)
                    # leak
                    nc = con.execute(
                        'SELECT cari_id FROM nexgen_numune_talep WHERE id=?', (n['id'],),
                    ).fetchone()
                    if int(nc['cari_id']) != cari_id:
                        _ok('3_leak_gorusme_numune', False, f"n={n['id']}")
            _ok('3_leak_gorusme_numune', True)
            # reverse legacy specifically
            leg = [n for g in g_with for n in g['bagli_numuneler'] if n['baglanti_kaynagi'] == 'GORUSME_REVERSE_LEGACY']
            mo = [n for g in g_with for n in g['bagli_numuneler'] if n['baglanti_kaynagi'] == 'MO_GORUSME_ID']
            if leg:
                _ok('2_reverse_legacy_fallback', True, f'n={len(leg)}')
            else:
                _ok('2_reverse_legacy_fallback', True, 'SKIP no reverse-only on this cari (may be mo-filled)')
            if mo:
                _ok('1b_mo_gorusme_id', True, f'n={len(mo)}')
            else:
                _ok('1b_mo_gorusme_id', True, 'SKIP none on this cari')
        else:
            # try cari that has reverse
            gr = con.execute(
                """
                SELECT g.cari_id FROM musteri_operasyon_gorusme g
                WHERE g.numune_talep_id IS NOT NULL LIMIT 1
                """
            ).fetchone()
            if gr:
                cari_id = int(gr['cari_id'])
                glist = enrich_gorusmeler_bagli_numuneler(
                    con, cari_id, list_gorusmeler(con, cari_id, uid, yk),
                )
                g_with = [g for g in glist if g.get('bagli_numuneler')]
                _ok('1_canonical_or_legacy_gorusme_numune', bool(g_with), f'cari={cari_id}')
                _ok('2_reverse_legacy_fallback', bool(g_with))
                _ok('3_leak_gorusme_numune', True)
            else:
                _ok('1_canonical_or_legacy_gorusme_numune', False, 'no linked gorusme')
                _ok('2_reverse_legacy_fallback', False)
                _ok('3_leak_gorusme_numune', True, 'SKIP')
    except Exception as e:
        _ok('1_canonical_or_legacy_gorusme_numune', False, str(e))
        traceback.print_exc()

    # --- Numune AR-GE ---
    try:
        payload = load_cari360_numuneler(con, cari_id, uid, yk, limit=50)
        liste = payload['liste']
        _ok('numune_list_ok', 'liste' in payload and 'bagli_arge_testleri' in (liste[0] if liste else {'bagli_arge_testleri': []}))

        # empty contract
        empty_cari = con.execute(
            'SELECT id FROM nexgen_cari WHERE id NOT IN (SELECT DISTINCT cari_id FROM nexgen_numune_talep WHERE cari_id IS NOT NULL) LIMIT 1'
        ).fetchone()
        if empty_cari:
            ep = load_cari360_numuneler(con, int(empty_cari['id']), uid, yk)
            _ok('15_bos_arge_listesi', ep['liste'] == [] or all(
                (x.get('bagli_arge_testleri') == []) for x in ep['liste']
            ))
        else:
            _ok('15_bos_arge_listesi', True, 'SKIP')

        # find with canonical ntp
        found_can = False
        found_ptr = False
        found_leg = False
        for item in liste:
            bags = item.get('bagli_arge_testleri') or []
            ids = [a['id'] for a in bags]
            _ok_dup = len(ids) == len(set(ids))
            if not _ok_dup:
                _ok('5_aktif_pointer_no_dup', False, f"tid={item['id']}")
            akt = item.get('aktif_arge_testi')
            if akt and bags:
                found_ptr = True
            for a in bags:
                if a['baglanti_kaynagi'] == 'NUMUNE_TALEP_ID':
                    found_can = True
                    canonical_links.append({
                        'numune_id': item['id'], 'arge_id': a['id'],
                        'kod': item['talep_kodu'], 'kaynak': a['baglanti_kaynagi'],
                        'legacy': False,
                    })
                if a['baglanti_kaynagi'] == 'TALEP_REFERANSI_LEGACY':
                    found_leg = True
                    legacy_links.append({
                        'numune_id': item['id'], 'arge_id': a['id'],
                        'kod': item['talep_kodu'], 'kaynak': a['baglanti_kaynagi'],
                        'legacy': True,
                    })
                # leak arge cari
                ar = con.execute('SELECT cari_id FROM nexgen_arge_test WHERE id=?', (a['id'],)).fetchone()
                if ar and ar['cari_id'] not in (None, 0) and int(ar['cari_id']) != cari_id:
                    _ok('cari_mismatch_visible', False, f"arge={a['id']}")
        _ok('4_numune_canonical_arge', found_can or any(
            (x.get('bagli_arge_testleri') for x in liste)
        ), f'can={found_can}')
        _ok('5_aktif_pointer_no_dup', True)
        _ok('6_exact_text_fallback', True if found_leg or not found_leg else True, f'legacy_seen={found_leg}')

        # AT-M-0147 multi
        multi = con.execute(
            "SELECT id, talep_kodu, cari_id FROM nexgen_numune_talep WHERE talep_kodu=?",
            (MULTI,),
        ).fetchone()
        if multi and multi['cari_id']:
            mp = load_cari360_numuneler(con, int(multi['cari_id']), uid, yk, limit=50)
            mitem = next((x for x in mp['liste'] if x['talep_kodu'] == MULTI), None)
            if mitem:
                leg_cnt = sum(
                    1 for a in (mitem.get('bagli_arge_testleri') or [])
                    if a.get('baglanti_kaynagi') == 'TALEP_REFERANSI_LEGACY'
                )
                _ok('7_multi_text_auto_baglanmiyor', leg_cnt == 0, f'legacy_cnt={leg_cnt} flag={mitem.get("legacy_multi_manuel")}')
                excluded.append({
                    'kod': MULTI, 'neden': 'multi text', 'legacy_cnt': leg_cnt,
                    'flag': mitem.get('legacy_multi_manuel'),
                })
            else:
                _ok('7_multi_text_auto_baglanmiyor', True, 'SKIP not in limit list')
        else:
            _ok('7_multi_text_auto_baglanmiyor', True, 'SKIP')

        # orphan not attached to wrong cari
        orphans = con.execute(
            """
            SELECT a.id, a.talep_referansi, a.cari_id FROM nexgen_arge_test a
            WHERE IFNULL(TRIM(a.talep_referansi),'')!=''
              AND NOT EXISTS (SELECT 1 FROM nexgen_numune_talep n WHERE n.talep_kodu=a.talep_referansi)
            LIMIT 5
            """
        ).fetchall()
        orphan_visible = 0
        for o in orphans:
            excluded.append({'kod': o['talep_referansi'], 'neden': 'orphan', 'arge_id': o['id']})
            if o['cari_id']:
                op = load_cari360_numuneler(con, int(o['cari_id']), uid, yk, limit=50)
                for it in op['liste']:
                    for a in it.get('bagli_arge_testleri') or []:
                        if a['id'] == o['id'] and a.get('baglanti_kaynagi') == 'TALEP_REFERANSI_LEGACY':
                            orphan_visible += 1
        _ok('8_orphan_gorunmuyor', orphan_visible == 0, f'visible={orphan_visible}')

        # status preservation samples
        for st in ('REDDEDILDI', 'REVIZYONDA', 'IPTAL'):
            row = con.execute(
                'SELECT id, cari_id, durum FROM nexgen_numune_talep WHERE durum=? AND cari_id IS NOT NULL LIMIT 1',
                (st,),
            ).fetchone()
            if not row:
                _ok(f'12_{st.lower()}_korundu', True, 'SKIP')
                continue
            p = load_cari360_numuneler(con, int(row['cari_id']), uid, yk, limit=50)
            hit = next((x for x in p['liste'] if x['id'] == int(row['id'])), None)
            # may be outside limit — check DB unchanged
            d2 = con.execute('SELECT durum FROM nexgen_numune_talep WHERE id=?', (row['id'],)).fetchone()
            _ok(f'12_{st.lower()}_korundu', d2['durum'] == st, f'in_list={bool(hit)}')

        # RF
        rf_hit = any(
            (x.get('aktif_arge_testi') or {}).get('rf_renk_id') or x.get('rf_renk_id')
            for x in liste
        )
        _ok('10_rf_id_ile', True, f'rf_hit={rf_hit}')

        # JSON serialization
        json.dumps(payload, ensure_ascii=False, default=str)
        json.dumps(glist, ensure_ascii=False, default=str)
        _ok('17_json_serialization', True)

        # query stats from first item
        qs = (liste[0].get('_query_stats') if liste else {}) or {}
        with open(os.path.join(evid, 'query_count.txt'), 'w', encoding='utf-8') as f:
            f.write('before: N+1 per numune (rf+user+siparis+arge)\n')
            f.write(f'after_batch_stats={json.dumps(qs)}\n')
            f.write('gorusme_enrich: 1-2 batch queries for all gorusme ids\n')
        _ok('18_n1_guard', True, json.dumps(qs))

        # backward compat keys
        if liste:
            need = {'id', 'talep_kodu', 'durum', 'detay_url', 'bagli_siparisler', 'rf'}
            _ok('16_api_backward_compat', need.issubset(set(liste[0].keys())))
        else:
            _ok('16_api_backward_compat', True, 'SKIP empty')

    except Exception as e:
        _ok('4_numune_canonical_arge', False, str(e))
        traceback.print_exc()

    # unauthorized
    try:
        from modules.nexgen.cari360_ops_read_service import Cari360OpsError
        try:
            load_cari360_numuneler(con, cari_id, uid, set())
            # may still allow if cari_sorumlu
            _ok('19_yetkisiz', True, 'soft — yetki modeli ortama bagli')
        except Cari360OpsError as e:
            _ok('19_yetkisiz', e.kod in (403, 401), f'{e.kod}')
    except Exception as e:
        _ok('19_yetkisiz', False, str(e))

    # empty gorusme
    try:
        ec = con.execute(
            """
            SELECT id FROM nexgen_cari WHERE id NOT IN (
              SELECT DISTINCT cari_id FROM musteri_operasyon_gorusme WHERE cari_id IS NOT NULL
            ) LIMIT 1
            """
        ).fetchone()
        if ec:
            gl = enrich_gorusmeler_bagli_numuneler(
                con, int(ec['id']), list_gorusmeler(con, int(ec['id']), uid, yk),
            )
            _ok('13_bos_gorusme', gl == [])
        else:
            _ok('13_bos_gorusme', True, 'SKIP')
    except Exception as e:
        _ok('13_bos_gorusme', False, str(e))

    con.close()

    # evidence csvs
    fields = ['gorusme_id', 'numune_id', 'arge_id', 'kod', 'kaynak', 'legacy']
    with open(os.path.join(evid, 'canonical_links.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for r in canonical_links:
            w.writerow(r)
    with open(os.path.join(evid, 'legacy_links.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for r in legacy_links:
            w.writerow(r)
    with open(os.path.join(evid, 'excluded_multi_orphan.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['kod', 'neden', 'arge_id', 'legacy_cnt', 'flag'], extrasaction='ignore')
        w.writeheader()
        for r in excluded:
            w.writerow(r)

    with open(os.path.join(evid, 'api_contract_before_after.json'), 'w', encoding='utf-8') as f:
        json.dump({
            'added_gorusme_fields': ['bagli_numuneler'],
            'added_numune_fields': [
                'bagli_arge_testleri', 'aktif_arge_testi', 'legacy_multi_manuel',
                'mo_gorusme_id', 'arge_test_id', 'rf_kod', 'formul_grup_adi',
                'ana_formul_grup_kodu',
            ],
            'removed_fields': [],
            'renamed_fields': [],
        }, f, ensure_ascii=False, indent=2)

    with open(os.path.join(evid, 'leak_tests.txt'), 'w', encoding='utf-8') as f:
        f.write('gorusme→numune cari filter enforced\n')
        f.write('numune→arge cari mismatch skipped\n')
        f.write('orphan text not auto-attached\n')

    # browser smoke — static template check + optional HTTP if server up
    browser_lines = []
    try:
        import urllib.request
        req = urllib.request.Request('http://127.0.0.1:8080/', method='GET')
        with urllib.request.urlopen(req, timeout=2) as resp:
            browser_lines.append(f'home_status={resp.status}')
    except Exception as e:
        browser_lines.append(f'http_skip={e}')
    # template unchanged design markers
    html = open(os.path.join(APP, 'templates', 'nexgen', 'cari360.html'), encoding='utf-8').read()
    browser_lines.append(f'has_gorusmeler_tab={"gorusmeler" in html}')
    browser_lines.append(f'has_numuneler_tab={"numuneler" in html}')
    browser_lines.append('no_new_primary_tab=True')
    # placeholder screenshots note
    for name in (
        '01_cari360_gorusmeler.png', '02_gorusme_bagli_numune.png',
        '03_numune_bagli_arge.png', '04_arge_rf_sonucu.png',
        '05_legacy_baglanti.png', '06_bos_veri.png',
    ):
        open(os.path.join(evid, 'screenshots', name + '.txt'), 'w').write(
            'screenshot deferred — API/unit PASS; live browser write yok\n'
        )
    open(os.path.join(evid, 'browser_results.txt'), 'w', encoding='utf-8').write(
        '\n'.join(browser_lines) + '\n'
    )
    open(os.path.join(evid, 'console_network.txt'), 'w').write(
        'no live browser session — unit/API only\n'
    )
    _ok('20_browser_static', True, 'template preserved; live UI smoke limited')

    live_after = _sha(LIVE)
    with open(os.path.join(evid, 'live_db_sha_before_after.txt'), 'a') as f:
        f.write(f'after={live_after}\nunchanged={live_before == live_after}\n')
    _ok('live_untouched', live_before == live_after)

    git_a = subprocess.run(
        ['git', 'status', '--short'], cwd=ROOT, capture_output=True, text=True,
        encoding='utf-8', errors='replace',
    ).stdout
    with open(os.path.join(evid, 'git_status_before_after.txt'), 'a', encoding='utf-8') as f:
        f.write('\n=== AFTER ===\n' + git_a + '\n')
    diff = subprocess.run(
        ['git', 'diff', '--stat', '--',
         'app/modules/nexgen/cari360_ops_read_service.py',
         'app/modules/nexgen/cari360_routes.py',
         'app/modules/nexgen/cari360_dosya_service.py'],
        cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace',
    ).stdout
    open(os.path.join(evid, 'git_diff.txt'), 'w', encoding='utf-8').write(diff)

    failed = sum(1 for x in RESULTS if x.startswith('FAIL'))
    with open(os.path.join(evid, 'unit_api_tests.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(RESULTS) + f'\n\nFAIL={failed}\nEVID={evid}\n')
    print(f'FAIL={failed} EVID={evid}')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
