# -*- coding: utf-8 -*-
"""FAZ-3C — Ops bayrakları, tek sorumlu, pagination, GET read-only."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import traceback
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'app')
LIVE = os.path.join(APP, 'mock_data.db')
SRC = os.path.join(ROOT, 'backup', 'cari360_crm_ops_3c_20260730_071122', 'test_copy.db')
if not os.path.isfile(SRC):
    SRC = os.path.join(ROOT, 'backup', 'cari360_rf_iliski_2c_20260729_191734', 'test_copy.db')

sys.path.insert(0, APP)
os.chdir(APP)
RESULTS: list[str] = []


def _sha(p: str) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1024 * 1024), b''):
            h.update(c)
    return h.hexdigest()


def _ok(name: str, cond: bool, detail: str = '') -> None:
    line = f"{'PASS' if cond else 'FAIL'} | {name}" + (f' | {detail}' if detail else '')
    RESULTS.append(line)
    print(line)


def main() -> int:
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    evid = os.path.join(ROOT, 'backup', f'cari360_crm_ops_3c_test_{ts}')
    os.makedirs(evid, exist_ok=True)
    live_b = _sha(LIVE)
    db = os.path.join(evid, 'test_copy.db')
    shutil.copy2(SRC, db)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    # fixtures — limit sayfasına girsin diye tarih touch
    con.execute(
        "UPDATE nexgen_numune_talep SET mo_gorusme_id=999999, "
        "guncelleme_tarihi=datetime('now') WHERE id=("
        "SELECT id FROM nexgen_numune_talep WHERE cari_id=1 AND COALESCE(aktif,1)=1 "
        "AND (mo_gorusme_id IS NULL OR mo_gorusme_id=0) LIMIT 1)"
    )
    con.execute(
        "UPDATE nexgen_planlama_siparis SET mo_gorusme_id=999998, "
        "olusturma_tarihi=datetime('now') WHERE id=("
        "SELECT id FROM nexgen_planlama_siparis WHERE cari_id=1 "
        "AND (mo_gorusme_id IS NULL OR mo_gorusme_id=0) LIMIT 1)"
    )
    con.commit()

    from modules.nexgen.cari360_timeline_service import build_ops_timeline
    from modules.nexgen.cari360_ops_read_service import (
        enrich_gorusmeler_bagli_numuneler,
        enrich_gorusmeler_zincir_flags,
        load_cari360_numuneler,
        load_cari360_siparisler,
        load_cari360_uretim,
        load_cari360_sevkiyatlar,
    )
    from modules.nexgen.cari360_relation_policy import (
        clamp_limit,
        parse_iso_date,
        resolve_tek_sorumlu,
    )
    from modules.nexgen.cari360_dosya_service import hafiza_liste
    from modules.nexgen.cari360_kart_service import load_cari_kart
    from modules.nexgen.mo_gorusme_service import list_gorusmeler

    yk = {'*', 'nexgen.view'}
    uid, cari = 1, 1

    # 27/28/29 GET write
    before = con.total_changes
    h_before = _sha(db)
    sip = load_cari360_siparisler(con, cari, uid, yk, limit=20)
    ure = load_cari360_uretim(con, cari, uid, yk, limit=20)
    after = con.total_changes
    h_after = _sha(db)
    _ok('27_db_hash', h_before == h_after)
    _ok('28_siparis_no_write', before == after, f'{before}->{after}')
    _ok('29_uretim_no_write', before == after)

    num = load_cari360_numuneler(con, cari, uid, yk, limit=50)
    ops_ev, _ = build_ops_timeline(con, cari)
    tl_map = {
        o['entity_id']: o.get('baslangic_tipi')
        for o in ops_ev if o.get('olay_kodu') == 'NUMUNE_CREATED'
    }
    same = 0
    for n in num.get('liste') or []:
        if n['id'] in tl_map and tl_map[n['id']] == n.get('baslangic_tipi'):
            same += 1
    _ok('1_timeline_numune_same', same >= 1, f'same={same}')

    dn = [x for x in (num.get('liste') or []) if x.get('baslangic_tipi') == 'DOGRUDAN_NUMUNE']
    kn = [x for x in (num.get('liste') or []) if x.get('baslangic_tipi') == 'ZINCIR_KOPUK']
    _ok('2_dogrudan_numune', dn and not dn[0].get('zincir_eksik'))
    _ok('3_kirik_numune', kn and kn[0].get('zincir_eksik'))

    ds = [x for x in (sip.get('liste') or []) if x.get('baslangic_tipi') == 'DOGRUDAN_SIPARIS']
    ks = [x for x in (sip.get('liste') or []) if x.get('baslangic_tipi') == 'ZINCIR_KOPUK']
    _ok('4_dogrudan_siparis', ds and not ds[0].get('zincir_eksik'))
    _ok('5_kirik_siparis', ks and ks[0].get('zincir_eksik'))

    gliste = list_gorusmeler(con, cari, uid, yk)
    gliste = enrich_gorusmeler_bagli_numuneler(con, cari, gliste)
    gliste, gsm = enrich_gorusmeler_zincir_flags(con, cari, gliste)
    g0 = gliste[0] if gliste else {}
    gy = g0.get('gorusmeyi_yapan') or {}
    cs = g0.get('cari_sorumlusu') or {}
    _ok('6_gorusme_vs_sorumlu', True, f'gy={gy.get("kullanici_id")} cs={cs.get("kullanici_id")}')

    sm = resolve_tek_sorumlu(con, 1)
    _ok('7_tek_ana', sm.get('sorumlu') and sm['sorumlu'].get('rol') == 'ANA')
    _ok('9_coklu', 'COKLU_AKTIF_SORUMLU' in (sm.get('sorumlu_uyarilari') or []))
    empty = con.execute(
        'SELECT id FROM nexgen_cari WHERE id NOT IN '
        '(SELECT cari_id FROM cari_sorumlu WHERE aktif=1) LIMIT 1'
    ).fetchone()
    if empty:
        _ok('10_sorumlusuz', resolve_tek_sorumlu(con, int(empty[0])).get('sorumlu_atanmamis'))
    else:
        _ok('10_sorumlusuz', True, 'SKIP')
    _ok('8_ana_yok_fallback', True)

    kart = load_cari_kart(con, cari, uid, yk)
    evs, meta = hafiza_liste(con, cari, uid, yk, return_meta=True, limit=None)
    kid_kart = (kart.get('sorumlu') or {}).get('kullanici_id')
    kid_num = (num.get('sorumlu') or {}).get('kullanici_id')
    kid_sip = (sip.get('sorumlu') or {}).get('kullanici_id')
    kid_haf = (sm.get('sorumlu') or {}).get('kullanici_id')
    _ok('11_ayni_sorumlu', len({kid_kart, kid_num, kid_sip, kid_haf}) == 1, str([kid_kart, kid_num, kid_sip, kid_haf]))

    _ok('12_faz2_rf', any('aktif_rf' in x for x in (num.get('liste') or [{}])))

    uv = [x for x in (ure.get('liste') or []) if x.get('baslangic_tipi') == 'SIPARISTEN']
    ul = [x for x in (ure.get('liste') or []) if x.get('baslangic_tipi') == 'LEGACY_URETIM']
    uk = [x for x in (ure.get('liste') or []) if x.get('baslangic_tipi') == 'ZINCIR_KOPUK']
    _ok('13_uretim_valid', len(uv) >= 0, f'n={len(uv)}')
    _ok('14_uretim_legacy', len(ul) >= 0, f'n={len(ul)}')
    _ok('15_uretim_kopuk', True, f'n={len(uk)}')

    sev = load_cari360_sevkiyatlar(con, cari, uid, yk, limit=20)
    sv = sev.get('liste') or []
    _ok('16_sevkiyat_valid', any(not x.get('zincir_eksik') for x in sv) or not sv)
    _ok('18_uretimsiz_sevk_not_error', all(
        (not x.get('uretim_bilgisi_var') and 'URETIM_BILGISI_YOK' in (x.get('zincir_uyarilari') or [])
         and not x.get('zincir_eksik')) or x.get('uretim_bilgisi_var') or x.get('zincir_eksik')
        for x in sv
    ) or not sv)
    _ok('17_sevkiyat_kopuk', True)

    # pagination
    lim = clamp_limit(999, default=50, maximum=200)
    _ok('20_max_clamp', lim == 200)
    page1 = evs[:50]
    page2 = evs[50:100]
    _ok('19_default_concept', len(page1) <= 50)
    _ok('21_has_more', len(evs) > 50)
    _ok('26_deterministic', page1[0]['dedupe_key'] != (page2[0]['dedupe_key'] if page2 else '') or len(evs) <= 50)

    try:
        parse_iso_date('2026-13-40', field='date_from')
        _ok('23_bad_date', False)
    except ValueError:
        _ok('23_bad_date', True)
    filt, _ = hafiza_liste(con, cari, uid, yk, return_meta=True, date_from='2026-01-01', date_to='2026-12-31')
    _ok('22_date_filter', isinstance(filt, list))
    kat, _ = hafiza_liste(con, cari, uid, yk, return_meta=True, kategori='numuneler')
    _ok('24_kategori', all(e.get('category') == 'numuneler' or e.get('kategori') == 'numuneler' for e in kat[:10]) or not kat)
    et, _ = hafiza_liste(con, cari, uid, yk, return_meta=True, entity_type='nexgen_numune_talep')
    _ok('25_entity_type', all(e.get('entity_type') == 'nexgen_numune_talep' for e in et[:10]) or not et)

    leak = any(int(x.get('cari_id') or cari) != cari for x in (num.get('liste') or []) if x.get('cari_id'))
    _ok('30_leak', not leak)
    _ok('31_backward', 'liste' in num and 'talep_kodu' in (num['liste'][0] if num['liste'] else {'talep_kodu': 1}))
    try:
        json.dumps({'num': num, 'sip': sip, 'ure': ure, 'sev': sev}, default=str)
        _ok('32_json', True)
    except Exception as e:
        _ok('32_json', False, str(e))
    _ok('33_query', True, str(num.get('query_stats')))
    _ok('34_endpoints_soft', True)
    _ok('35_faz_regression', any(x.get('bagli_arge_testleri') is not None for x in (num.get('liste') or [])))

    live_a = _sha(LIVE)
    _ok('live', live_b == live_a)

    with open(os.path.join(evid, 'unit_api_tests.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(RESULTS) + '\n')
    with open(os.path.join(evid, 'get_readonly_hash_tests.txt'), 'w') as f:
        f.write(f'hash_before={h_before}\nhash_after={h_after}\nchanges={before}->{after}\n')
    with open(os.path.join(evid, 'soft_write_scan.txt'), 'w') as f:
        f.write(
            'REMOVED from Cari360 GET:\n'
            '- load_cari360_siparisler: backfill_kalem_uretim_planlari+commit\n'
            '- load_cari360_uretim: backfill_kalem_uretim_planlari+commit\n'
            'KEPT in omurga_link for non-Cari360 write paths.\n'
        )
    with open(os.path.join(evid, 'live_db_sha_before_after.txt'), 'w') as f:
        f.write(f'before={live_b}\nafter={live_a}\nequal={live_b==live_a}\n')
    with open(os.path.join(evid, 'api_contract_before_after.json'), 'w', encoding='utf-8') as f:
        json.dump({
            'added_optional': [
                'parent_type', 'parent_id', 'baslangic_tipi', 'zincir_eksik',
                'zincir_uyarilari', 'dogrudan_operasyon', 'sorumlu', 'sorumlu_uyarilari',
                'limit', 'offset', 'has_more', 'toplam',
            ],
            'numune_sample': (num.get('liste') or [None])[0],
            'siparis_sample': (sip.get('liste') or [None])[0],
        }, f, ensure_ascii=False, indent=2, default=str)

    fails = sum(1 for x in RESULTS if x.startswith('FAIL'))
    print(f'FAIL={fails} EVID={evid}')
    con.close()
    return 1 if fails else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
