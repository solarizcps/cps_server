# -*- coding: utf-8 -*-
"""FAZ-MI-MERKEZ-BE-1.1/1.2/1.3 — Çoklu plan MPR wrapper kapanış testi."""
import copy
import hashlib
import io
import json
import os
import sqlite3
import sys
from collections import defaultdict

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app')
sys.path.insert(0, _APP_DIR)
os.chdir(_APP_DIR)
DB = os.path.join(_APP_DIR, 'mock_data.db')

import modules.nexgen.routes as routes_mod  # noqa: E402
from modules.nexgen.routes import (  # noqa: E402
    _mpr_stok_ihtiyac_birlestir,
    _mpr_stok_ihtiyac_coklu_plan,
)

_REAL_TRACE = routes_mod._mpr_plan_detay_trace_uret
_REAL_REZERV = routes_mod._aktif_rezerv_toplam
HER_IKISI_CTX = {}
results = []
field_gaps = []
SKIP = 'SKIP'


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    mark = 'PASS' if cond is True else ('SKIP' if cond is SKIP else 'FAIL')
    print(f'  [{mark}] {name}' + (f' — {detail}' if detail else ''))


def skip(name, detail=''):
    ok(name, SKIP, detail)


def gap(layer, expected, actual_or_note):
    field_gaps.append({'layer': layer, 'expected': expected, 'note': actual_or_note})


def _sum_detay_gerekli(detay):
    return round(sum(float(d.get('gerekli_kg') or 0) for d in detay if d.get('stok_kart_id')), 6)


def _sum_toplu_gerekli(toplu):
    return round(sum(float(t.get('gerekli_kg') or t.get('toplam_gerekli_kg') or 0) for t in toplu), 6)


def _db_row_counts(con):
    tables = (
        'nexgen_uretim_plan',
        'nexgen_stok_hareket',
        'nexgen_stok_rezerv',
        'nexgen_satin_alma_siparis',
        'nexgen_satin_alma_siparis_kalem',
    )
    out = {}
    for t in tables:
        try:
            out[t] = con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
        except sqlite3.OperationalError:
            out[t] = None
    return out


def _stable_payload_hash(payload):
    slim = {
        'plan_ids': payload.get('plan_ids'),
        'ozet': payload.get('ozet'),
        'detay_len': len(payload.get('detay') or []),
        'toplu': [
            {
                'stok_kart_id': t.get('stok_kart_id'),
                'gerekli_kg': t.get('gerekli_kg'),
                'net_eksik_kg': t.get('net_eksik_kg'),
            }
            for t in (payload.get('toplu') or [])
        ],
    }
    raw = json.dumps(slim, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _find_calculable_plans(con, limit=20):
    rows = con.execute("""
        SELECT id, plan_kodu, planlanan_kg, siparis_no, musteri_adi, cari_id
        FROM nexgen_uretim_plan
        WHERE durum != 'IPTAL' AND COALESCE(planlanan_kg, 0) > 0
        ORDER BY id DESC
        LIMIT ?
    """, (limit * 3,)).fetchall()
    ok_ids = []
    for r in rows:
        s = _mpr_stok_ihtiyac_birlestir(con, r['id'])
        if s.get('ok'):
            ok_ids.append(dict(r))
        if len(ok_ids) >= limit:
            break
    return ok_ids


def _kaynak_setleri(detay):
    mp = defaultdict(set)
    for d in detay:
        sid = d.get('stok_kart_id')
        if sid:
            mp[sid].add(d.get('kaynak') or '')
    return mp


def _trace_her_ikisi_fixture(con, plan_id, exclude_batch_kodu=None):
    """Gerçek trace sonucuna aynı stok için RF satırı enjekte eder (DB yazmaz)."""
    result = _REAL_TRACE(con, plan_id, exclude_batch_kodu=exclude_batch_kodu)
    if not result.get('ok') or plan_id != HER_IKISI_CTX.get('plan_id'):
        return result
    satirlar = list(result.get('satirlar') or [])
    sid_hedef = HER_IKISI_CTX.get('stok_kart_id')
    taban = next(
        (s for s in satirlar if s.get('stok_kart_id') == sid_hedef and s.get('kaynak') == 'TABAN'),
        None,
    )
    if taban is None:
        taban = next((s for s in satirlar if s.get('kaynak') == 'TABAN' and s.get('stok_kart_id')), None)
    if taban is None:
        return result
    sid = taban['stok_kart_id']
    HER_IKISI_CTX['stok_kart_id'] = sid
    HER_IKISI_CTX['taban_kg'] = float(taban.get('gerekli_kg') or 0)
    rf_kg = float(HER_IKISI_CTX.get('rf_kg') or 3.141)
    batch = int(taban.get('batch_sayisi') or taban.get('formul_adedi') or 1)
    rf_row = copy.deepcopy(taban)
    rf_row.update({
        'kaynak': 'RF',
        'kaynak_turu': 'BOYA_RECETESI',
        'gerekli_kg': rf_kg,
        'bir_formulde_kg': round(rf_kg / batch, 6) if batch > 0 else rf_kg,
        'pigment_ad': rf_row.get('pigment_ad') or 'FIXTURE-RF-PIGMENT',
    })
    satirlar.append(rf_row)
    HER_IKISI_CTX['rf_kg'] = rf_kg
    return {'ok': True, 'satirlar': satirlar}


def _rezerv_her_ikisi_fixture(con, stok_kart_id, exclude_batch_kodu=None):
    if stok_kart_id == HER_IKISI_CTX.get('stok_kart_id'):
        return float(HER_IKISI_CTX.get('rezerve_kg') or 12.5)
    return _REAL_REZERV(con, stok_kart_id, exclude_batch_kodu=exclude_batch_kodu)


def _run_her_ikisi_fixture(con, plan_id):
    """Monkeypatch ile HER_IKISI senaryosunu gerçek wrapper üzerinde çalıştır."""
    HER_IKISI_CTX.clear()
    HER_IKISI_CTX.update({'plan_id': plan_id, 'rf_kg': 3.141, 'rezerve_kg': 12.5})
    before = _db_row_counts(con)
    routes_mod._mpr_plan_detay_trace_uret = _trace_her_ikisi_fixture
    routes_mod._aktif_rezerv_toplam = _rezerv_her_ikisi_fixture
    try:
        payload = _mpr_stok_ihtiyac_coklu_plan(con, [plan_id])
    finally:
        routes_mod._mpr_plan_detay_trace_uret = _REAL_TRACE
        routes_mod._aktif_rezerv_toplam = _REAL_REZERV
    after = _db_row_counts(con)
    HER_IKISI_CTX['db_unchanged'] = before == after
    return payload

def _field_present(obj, key):
    if key not in obj:
        return False, 'missing'
    val = obj.get(key)
    if val is None:
        return False, 'None'
    if val == '' and key not in ('siparis_no', 'musteri_adi'):
        return False, 'empty'
    return True, val


def _audit_response_fields(ozet, detay_row, toplu_row):
    """BE-1.2 response alan denetimi."""
    ozet_expected = {
        'plan_sayisi': 'plan_sayisi',
        'basarili_plan_sayisi': 'basarili_plan_sayisi',
        'siparis_sayisi': 'siparis_sayisi',
        'cari_sayisi': 'cari_sayisi',
        'toplam_talep_kg': 'toplam_talep_kg',
        'toplam_uretilecek_kg': 'toplam_uretilecek_kg',
        'toplam_faturalanacak_kg': 'toplam_faturalanacak_kg',
        'toplam_hammadde_kg': 'toplam_hammadde_kg',
        'toplam_net_eksik_kg': 'toplam_net_eksik_kg',
        'yeterli_kalem_sayisi': 'yeterli_kalem_sayisi',
        'eksik_kalem_sayisi': 'eksik_kalem_sayisi',
        'yeterli_mi': 'yeterli_mi',
    }
    for exp, actual_key in ozet_expected.items():
        present, note = _field_present(ozet, actual_key)
        if not present:
            gap('ozet', exp, f'beklenen={actual_key} → {note}')

    detay_map = {
        'plan_id': 'plan_id',
        'plan_kodu': 'plan_kodu',
        'siparis_id': 'siparis_id',
        'siparis_kodu': 'siparis_no',
        'cari': 'musteri_adi',
        'formul': 'formul_kod',
        'renk': 'rv_ad',
        'boyut': 'boyut',
        'stok_kart_id': 'stok_kart_id',
        'stok_kodu': 'stok_kod',
        'kaynak_turu': 'kaynak_turu',
        'bir_formulde_kg': 'bir_formulde_kg',
        'gerekli_kg': 'gerekli_kg',
        'birim': 'birim',
    }
    for exp, actual_key in detay_map.items():
        if actual_key in ('siparis_id', 'musteri_adi', 'siparis_no') and detay_row.get(actual_key) is None:
            continue
        present, note = _field_present(detay_row, actual_key)
        if not present:
            gap('detay', exp, f'beklenen={actual_key} → {note}')

    toplu_map = {
        'stok_kart_id': 'stok_kart_id',
        'toplam_gerekli_kg': 'toplam_gerekli_kg',
        'fiziksel_kg': 'fiziksel_kg',
        'rezerve_kg': 'rezerve_kg',
        'yumusak_talep_kg': 'yumusak_talep_kg',
        'kullanilabilir_kg': 'kullanilabilir_kg',
        'yolda_kg': 'yolda_kg',
        'net_eksik_kg': 'net_eksik_kg',
        'durum': 'durum',
        'kaynak_turu': 'kaynak_turu',
        'plan_sayisi': 'plan_sayisi',
        'siparis_sayisi': 'siparis_sayisi',
        'cari_sayisi': 'cari_sayisi',
        'formul_sayisi': 'formul_sayisi',
    }
    for exp, actual_key in toplu_map.items():
        present, note = _field_present(toplu_row, actual_key)
        if not present:
            gap('toplu', exp, f'beklenen={actual_key} → {note}')


print('=' * 72)
print('FAZ-MI-MERKEZ-BE-1.1 + BE-1.2 + BE-1.3 — ÇOKLU PLAN WRAPPER KAPANIŞ TESTİ')
print('=' * 72)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

calculable = _find_calculable_plans(con, limit=15)
ok('setup hesaplanabilir plan var', len(calculable) >= 2, f'adet={len(calculable)}')

plan_a = calculable[0]['id'] if calculable else None
plan_b = calculable[1]['id'] if len(calculable) > 1 else None

# ── 1) Boş plan listesi ──
r_empty = _mpr_stok_ihtiyac_coklu_plan(con, [])
ok('01 bos plan listesi hata', not r_empty.get('ok') and 'plan_id' in (r_empty.get('hata') or '').lower())

r_none = _mpr_stok_ihtiyac_coklu_plan(con, None)
ok('01b plan_ids None hata', not r_none.get('ok'))

# ── 2) Duplicate plan ID ──
if plan_a and plan_b:
    r_dup = _mpr_stok_ihtiyac_coklu_plan(con, [plan_a, plan_a, plan_b])
    ok('02 duplicate temizleme', r_dup.get('plan_ids') == [plan_a, plan_b])
    ok('02 plan_sayisi', r_dup.get('ozet', {}).get('plan_sayisi') == 2)

# ── 3) Geçersiz plan ID ──
r_bad = _mpr_stok_ihtiyac_coklu_plan(con, [999999991])
ok('03 gecersiz plan', not r_bad.get('ok') or len(r_bad.get('hesaplanamayan_planlar') or []) == 1)
if plan_a:
    r_mix = _mpr_stok_ihtiyac_coklu_plan(con, [plan_a, 999999992])
    ok('03 karisik gecersiz devam', r_mix.get('ok') is True)
    ok('03 karisik hesaplanamayan', len(r_mix.get('hesaplanamayan_planlar') or []) == 1)
    ok('03 karisik basarili', r_mix.get('ozet', {}).get('basarili_plan_sayisi') == 1)

# ── 4) Tek plan ──
if plan_a:
    r_one = _mpr_stok_ihtiyac_coklu_plan(con, [plan_a])
    ok('04 tek plan ok', r_one.get('ok'))
    ok('04 tek plan_sayisi', r_one.get('ozet', {}).get('plan_sayisi') == 1)

# ── 5–7) İki plan + mutabakat ──
r_two = None
if plan_a and plan_b:
    r_two = _mpr_stok_ihtiyac_coklu_plan(con, [plan_a, plan_b])
    ok('05 iki plan ok', r_two.get('ok'))
    detay_sum = _sum_detay_gerekli(r_two.get('detay') or [])
    toplu_sum = _sum_toplu_gerekli(r_two.get('toplu') or [])
    ok('07 detay-toplu gerekli mutabakat', abs(detay_sum - toplu_sum) < 0.02,
       f'detay={detay_sum} toplu={toplu_sum}')

    shared = set()
    mp_a = defaultdict(float)
    mp_b = defaultdict(float)
    for d in r_two.get('detay') or []:
        sid = d.get('stok_kart_id')
        if not sid:
            continue
        if d.get('plan_id') == plan_a:
            mp_a[sid] += float(d.get('gerekli_kg') or 0)
        elif d.get('plan_id') == plan_b:
            mp_b[sid] += float(d.get('gerekli_kg') or 0)
    shared = set(mp_a.keys()) & set(mp_b.keys())
    ok('05 ortak stok karti var', len(shared) > 0, f'adet={len(shared)}')

    # ── 6) Stok tek sefer düşümü ──
    if shared:
        sid = next(iter(shared))
        toplu_row = next(t for t in r_two['toplu'] if t['stok_kart_id'] == sid)
        merged_gerekli = float(toplu_row['gerekli_kg'])
        expected_gerekli = round(mp_a[sid] + mp_b[sid], 6)
        ok('06 toplu gerekli birlesik', abs(merged_gerekli - expected_gerekli) < 0.02)
        kull = float(toplu_row['kullanilabilir_kg'])
        fiz_eksik = float(toplu_row['fiziksel_eksik_kg'])
        ok('06 fiziksel eksik tek stok', abs(fiz_eksik - max(merged_gerekli - kull, 0.0)) < 0.02)
        wrong_double = max(mp_a[sid] - kull, 0) + max(mp_b[sid] - kull, 0)
        ok('06 cift dusum yok', abs(float(toplu_row['net_eksik_kg']) - wrong_double) > 0.01 or merged_gerekli <= kull,
           f"net={toplu_row['net_eksik_kg']} yanlis_cift={wrong_double}")

# ── 8–9) TABAN + RF aynı stok / HER_IKISI (BE-1.3 fixture) ──
r_her = None
if plan_a:
    r_her = _run_her_ikisi_fixture(con, plan_a)
    ok('08 fixture ok', r_her.get('ok'), r_her.get('hata', ''))
    sid = HER_IKISI_CTX.get('stok_kart_id')
    if r_her.get('ok') and sid:
        detay_sid = [d for d in r_her['detay'] if d.get('stok_kart_id') == sid]
        ks = _kaynak_setleri(detay_sid)
        ok('08 ayni stok TABAN+RF', 'TABAN' in ks.get(sid, set()) and 'RF' in ks.get(sid, set()),
           f'stok={sid} kaynaklar={ks.get(sid)}')
        turler = {d.get('kaynak_turu') for d in detay_sid}
        ok('08 detay kaynak_turu ANA+BOYA', 'ANA_RECETE' in turler and 'BOYA_RECETESI' in turler,
           f'turler={turler}')
        ok('08 detay iki trace satiri', len(detay_sid) >= 2, f'adet={len(detay_sid)}')

        toplu_row = next((t for t in r_her['toplu'] if t['stok_kart_id'] == sid), None)
        ok('09 toplu tek satir', toplu_row is not None)
        if toplu_row:
            ok('09 kaynak_turu HER_IKISI', toplu_row.get('kaynak_turu') == 'HER_IKISI',
               f'mevcut={toplu_row.get("kaynak_turu")!r}')
            taban_kg = float(HER_IKISI_CTX.get('taban_kg') or 0)
            rf_kg = float(HER_IKISI_CTX.get('rf_kg') or 0)
            merged = round(taban_kg + rf_kg, 6)
            ok('09 toplu gerekli birlesik', abs(float(toplu_row['gerekli_kg']) - merged) < 0.02,
               f'toplu={toplu_row["gerekli_kg"]} beklenen={merged}')
            kull = float(toplu_row['kullanilabilir_kg'])
            yolda = float(toplu_row.get('yolda_kg') or 0)
            net = float(toplu_row['net_eksik_kg'])
            bek_net = round(max(max(merged - kull, 0.0) - yolda, 0.0), 3)
            ok('09 stok tek dusum net', abs(net - bek_net) < 0.02, f'net={net} bek={bek_net}')
            wrong = round(max(max(taban_kg - kull, 0.0) - yolda, 0.0) + max(max(rf_kg - kull, 0.0) - yolda, 0.0), 3)
            ok('09 cift dusum yok', abs(net - wrong) > 0.01 or merged <= kull,
               f'net={net} yanlis_cift={wrong}')
            ok('09 plan_sayisi sismez', int(toplu_row.get('plan_sayisi') or 0) == 1)
            ok('09 formul_sayisi sismez',
               int(toplu_row.get('formul_sayisi') or 0) <= len({d.get('formul_kod') for d in detay_sid if d.get('formul_kod')}))
            ds = round(sum(float(d.get('gerekli_kg') or 0) for d in r_her['detay'] if d.get('stok_kart_id')), 6)
            ts = _sum_toplu_gerekli(r_her['toplu'])
            ok('09 detay-toplu mutabakat', abs(ds - ts) < 0.02, f'd={ds} t={ts}')
            ok('09 net eksik negatif degil', net >= -0.0005)
            for d in detay_sid:
                if d.get('batch_sayisi'):
                    bek = round(float(d['bir_formulde_kg']) * int(d['batch_sayisi']), 3)
                    ok(f'09 bir_formulde stok={sid} kaynak={d.get("kaynak")}',
                       abs(bek - float(d['gerekli_kg'])) < 0.02)
            ok('09 tek plan motor', _mpr_stok_ihtiyac_birlestir(con, plan_a).get('ok'))
            ok('09 fixture db yazmadi', HER_IKISI_CTX.get('db_unchanged') is True)
    else:
        ok('08 fixture sid', False, 'trace enjekte edilemedi')
else:
    ok('08 fixture plan', False, 'plan_a yok')
# ── 10–14) Stok durumları ──
if r_two and r_two.get('ok'):
    toplu = r_two['toplu']
    yeterli_rows = [t for t in toplu if t.get('yeterli')]
    eksik_rows = [t for t in toplu if not t.get('yeterli')]
    ok('10 yeterli stok satiri', len(yeterli_rows) > 0, f'adet={len(yeterli_rows)}')
    ok('11 eksik stok satiri', len(eksik_rows) > 0, f'adet={len(eksik_rows)}')

    yolda_rows = [t for t in toplu if float(t.get('yolda_kg') or 0) > 0.001]
    if yolda_rows:
        t = yolda_rows[0]
        fiz_eksik = float(t['fiziksel_eksik_kg'])
        net = float(t['net_eksik_kg'])
        yolda = float(t['yolda_kg'])
        ok('12 yolda stok formul', abs(net - max(fiz_eksik - yolda, 0.0)) < 0.02,
           f'stok={t["stok_kart_id"]}')
    else:
        skip('12 yolda stok', 'mock DB acik SA yok')

    rez_rows = [t for t in toplu if float(t.get('rezerve_kg') or 0) > 0.001]
    if not rez_rows and r_her and r_her.get('ok'):
        sid = HER_IKISI_CTX.get('stok_kart_id')
        rez_rows = [t for t in r_her['toplu'] if t.get('stok_kart_id') == sid]
    if not rez_rows and len(calculable) >= 3:
        wide = _mpr_stok_ihtiyac_coklu_plan(con, [p['id'] for p in calculable[:5]])
        if wide.get('ok'):
            rez_rows = [t for t in wide['toplu'] if float(t.get('rezerve_kg') or 0) > 0.001]
    if rez_rows:
        t = rez_rows[0]
        kull = round(float(t['fiziksel_kg']) - float(t['rezerve_kg']) - float(t['yumusak_talep_kg']), 3)
        ok('13 rezerve stok formul', abs(float(t['kullanilabilir_kg']) - kull) < 0.02,
           f'stok={t["stok_kart_id"]}')
    else:
        skip('13 rezerve stok', 'secili stoklarda rezerv yok')

    neg_net = [t for t in toplu if float(t.get('net_eksik_kg') or 0) < -0.0005]
    ok('14 net eksik negatif degil', len(neg_net) == 0, f'negatif_adet={len(neg_net)}')

    bad_net_fiz = [
        t for t in toplu
        if float(t.get('net_eksik_kg') or 0) > float(t.get('fiziksel_eksik_kg') or 0) + 0.001
    ]
    ok('14b net<=fiziksel tum satirlar', len(bad_net_fiz) == 0,
       f'ihlal={len(bad_net_fiz)}')

# ── 15) Plan/sipariş/cari sayıları ──
if r_two and r_two.get('ok'):
    oz = r_two['ozet']
    ok('15 plan_sayisi', oz.get('plan_sayisi') == 2)
    ok('15 basarili_plan_sayisi', oz.get('basarili_plan_sayisi') == 2)
    sip_ids = {p.get('siparis_id') for p in r_two['plan_ozetleri'] if p.get('siparis_id') not in (None, '')}
    cari_ids = {p.get('cari_id') for p in r_two['plan_ozetleri'] if p.get('cari_id') not in (None, '')}
    ok('15 siparis_sayisi ozet', oz.get('siparis_sayisi') == len(sip_ids), f'ozet={oz.get("siparis_sayisi")} beklenen={len(sip_ids)}')
    ok('15 cari_sayisi ozet', oz.get('cari_sayisi') == len(cari_ids), f'ozet={oz.get("cari_sayisi")} beklenen={len(cari_ids)}')

# ── 16) Hesaplanamayan plan ──
if plan_a:
    r_fail = _mpr_stok_ihtiyac_coklu_plan(con, [plan_a, 999999993])
    ok('16 hesaplanamayan listede', any(h.get('plan_id') == 999999993
        for h in (r_fail.get('hesaplanamayan_planlar') or [])))

# ── 17) Detay net_eksik_toplanabilir ──
if r_two and r_two.get('ok'):
    bad_flags = [d for d in r_two['detay'] if d.get('net_eksik_toplanabilir') is not False]
    ok('17 detay net_eksik_toplanabilir false', len(bad_flags) == 0, f'yanlis={len(bad_flags)}')
    ok('17 detay net_eksik null', all(d.get('net_eksik_kg') is None for d in r_two['detay']))

# ── 18) Tek plan motor bozulmuyor ──
if plan_a:
    bir = _mpr_stok_ihtiyac_birlestir(con, plan_a)
    tek = _mpr_stok_ihtiyac_coklu_plan(con, [plan_a])
    if bir.get('ok') and tek.get('ok'):
        b_map = {k['stok_kart_id']: float(k['gerekli_kg']) for k in bir['kalemler'] if k.get('stok_kart_id')}
        t_map = {k['stok_kart_id']: float(k['gerekli_kg']) for k in tek['toplu'] if k.get('stok_kart_id')}
        ok('18 tek plan gerekli eslesir', b_map == t_map)
        ok('18 tek plan yeterli eslesir', bir.get('yeterli_mi') == tek.get('yeterli_mi'))
        ok('18 birlestir hala ok', bir.get('ok'))

# ── 19) DB yazmıyor ──
if plan_a and plan_b:
    before = _db_row_counts(con)
    _mpr_stok_ihtiyac_coklu_plan(con, [plan_a, plan_b])
    after = _db_row_counts(con)
    ok('19 wrapper db yazmiyor', before == after, f'before={before} after={after}')

# ── 20) Idempotent ──
if plan_a and plan_b:
    r1 = _mpr_stok_ihtiyac_coklu_plan(con, [plan_a, plan_b])
    r2 = _mpr_stok_ihtiyac_coklu_plan(con, [plan_a, plan_b])
    h1 = _stable_payload_hash(r1)
    h2 = _stable_payload_hash(r2)
    ok('20 idempotent hash', h1 == h2, h1[:16])

# ── BE-1.2) Response model tamamlama ──
if r_two and r_two.get('ok'):
    oz = r_two['ozet']
    toplu_n = len(r_two['toplu'])
    ok('BE12 yeterli+eksik kalem',
       int(oz.get('yeterli_kalem_sayisi') or 0) + int(oz.get('eksik_kalem_sayisi') or 0) == toplu_n,
       f"y={oz.get('yeterli_kalem_sayisi')} e={oz.get('eksik_kalem_sayisi')} t={toplu_n}")
    ok('BE12 faturalanacak=uretilecek',
       abs(float(oz.get('toplam_faturalanacak_kg') or 0) - float(oz.get('toplam_uretilecek_kg') or 0)) < 0.02)
    ok('BE12 detay kaynak_turu enum',
       all(d.get('kaynak_turu') in ('ANA_RECETE', 'BOYA_RECETESI', 'HER_IKISI')
           for d in r_two['detay'] if d.get('stok_kart_id')))
    ok('BE12 toplu kaynak_turu enum',
       all(t.get('kaynak_turu') in ('ANA_RECETE', 'BOYA_RECETESI', 'HER_IKISI') for t in r_two['toplu']))
    ok('BE12 toplu trace sayilari >=1',
       all(int(t.get('plan_sayisi') or 0) >= 1 for t in r_two['toplu']))
    sample = next((d for d in r_two['detay'] if d.get('stok_kart_id') and d.get('batch_sayisi')), None)
    if sample:
        bek = round(float(sample['bir_formulde_kg']) * int(sample['batch_sayisi']), 3)
        ok('BE12 bir_formulde_kg', abs(bek - float(sample['gerekli_kg'])) < 0.02,
           f"stok={sample['stok_kart_id']}")
    her_rows = [t for t in r_two['toplu'] if t.get('kaynak_turu') == 'HER_IKISI']
    if her_rows:
        ok('BE12 HER_IKISI satir (canli)', True, f'adet={len(her_rows)}')
    elif r_her and r_her.get('ok'):
        her_fix = [t for t in r_her['toplu'] if t.get('kaynak_turu') == 'HER_IKISI']
        ok('BE12 HER_IKISI satir (fixture)', len(her_fix) >= 1, f'adet={len(her_fix)}')
    else:
        ok('BE12 HER_IKISI satir', False, 'fixture calismadi')
# ── Response alan denetimi ──
if r_two and r_two.get('ok') and r_two.get('detay') and r_two.get('toplu'):
    _audit_response_fields(r_two['ozet'], r_two['detay'][0], r_two['toplu'][0])
    ok('alan denetimi calisti', True, f'gap={len(field_gaps)}')

con.close()

# ── Rapor ──
print()
print('=' * 72)
print('HESAP MUTABAKATI')
print('=' * 72)
if r_two and r_two.get('ok'):
    ds = _sum_detay_gerekli(r_two['detay'])
    ts = _sum_toplu_gerekli(r_two['toplu'])
    print(f'  sum(detay.gerekli_kg)     = {ds}')
    print(f'  sum(toplu.gerekli_kg)     = {ts}')
    print(f'  fark                      = {round(ds - ts, 6)}')
    print(f'  mutabakat                 = {"OK" if abs(ds - ts) < 0.02 else "FAIL"}')
else:
    print('  (iki plan senaryosu calismadi)')

print()
print('=' * 72)
print('EKSİK / FARKLI ALAN RAPORU')
print('=' * 72)
if not field_gaps:
    print('  (otomatik gap kaydı yok)')
else:
    seen = set()
    for g in field_gaps:
        key = (g['layer'], g['expected'])
        if key in seen:
            continue
        seen.add(key)
        print(f"  [{g['layer']}] {g['expected']}: {g['note']}")

print()
print('=' * 72)
print('ÖZET')
print('=' * 72)
passed = sum(1 for _, c, _ in results if c is True)
failed = sum(1 for _, c, _ in results if c is False)
skipped = sum(1 for _, c, _ in results if c is SKIP)
print(f'  PASS={passed}  FAIL={failed}  SKIP={skipped}  TOPLAM={len(results)}')
if failed:
    print('  BASARISIZ:')
    for name, c, detail in results:
        if c is False:
            print(f'    - {name}: {detail}')

sys.exit(1 if failed else 0)
