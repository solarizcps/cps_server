# -*- coding: utf-8 -*-
"""Üretim Plan — Korgun read model (canonical: SipNo+SipHarinx+MamulSKOD+RKOD)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime


def _load_proses_adlari(cur, proses_kodlari):
    if not proses_kodlari:
        return {}
    codes = sorted({str(c).strip() for c in proses_kodlari if str(c or '').strip()})
    ph = ','.join(['%s'] * len(codes))
    cur.execute(f"SELECT Pro, Tanim FROM Proses_M WHERE Pro IN ({ph})", tuple(codes))
    return {str(r[0]).strip(): (r[1] or str(r[0])).strip() for r in cur.fetchall()}


def _emirler_proses_hareket(con_by_emir, wait_by_emir, query_emirs):
    """Scope içi emirlerde hareket gören proses → emir seti."""
    out = defaultdict(set)
    for en in query_emirs or []:
        for r in con_by_emir.get(en, []) + wait_by_emir.get(en, []):
            pk = str(r.get('Proses', '') or '').strip()
            if pk:
                out[pk].add(en)
    return out


def _load_getproses_map(cur, emir_nos):
    """Scope emirler için kg_fn_GetProses batch map (/hedef fallback parity).

    Returns:
        by_emir: {emir_no: {'proses_kod', 'proses_adi'}}
        by_proses: {proses_kod: set(emir_no)}
    """
    by_emir = {}
    by_proses = defaultdict(set)
    if not emir_nos:
        return by_emir, by_proses
    emir_list = sorted(set(int(e) for e in emir_nos))
    ph = ','.join(['%s'] * len(emir_list))
    for tbl in ('Urt_Emir', 'Urtx_Emir'):
        cur.execute(f"""
            SELECT e.EmirNo,
                   LTRIM(RTRIM(CAST(fn.Proses AS VARCHAR(20)))) AS proses_kod,
                   ISNULL(pm.Tanim, CAST(fn.Proses AS VARCHAR(20))) AS proses_adi
            FROM {tbl} e
            CROSS APPLY (SELECT dbo.kg_fn_GetProses(e.EmirNo, '', 'f') AS Proses) fn
            LEFT JOIN Proses_M pm ON pm.Pro = fn.Proses
            WHERE e.EmirNo IN ({ph})
        """, tuple(emir_list))
        for r in cur.fetchall():
            en = int(r[0])
            if en in by_emir:
                continue
            pk = str(r[1] or '').strip()
            if not pk:
                continue
            adi = (r[2] or pk).strip()
            by_emir[en] = {'proses_kod': pk, 'proses_adi': adi}
            by_proses[pk].add(en)
    return by_emir, by_proses


def _merge_proses_adlari(proses_adi_map, getproses_by_emir=None, model_p_adi_map=None):
    out = dict(proses_adi_map or {})
    for src in (model_p_adi_map or {},):
        for pk, ad in src.items():
            if pk and pk not in out:
                out[pk] = ad
    for gp in (getproses_by_emir or {}).values():
        pk = gp.get('proses_kod')
        if pk and pk not in out:
            out[pk] = gp.get('proses_adi') or pk
    return out


def _load_model_p_routes(cur, model_kods):
    """Model_P canonical rota — batch load (N+1 yok).

    Returns:
        routes: {model_kod: [{'proses_kod', 'proses_no', 'proses_adi'}, ...]}
        adi_map: {proses_kod: proses_adi}
    """
    routes = {}
    adi_map = {}
    if not model_kods:
        return routes, adi_map
    codes = sorted({str(m).strip() for m in model_kods if str(m or '').strip()})
    if not codes:
        return routes, adi_map
    ph = ','.join(['%s'] * len(codes))
    cur.execute(f"""
        SELECT mp.ModelKod,
               LTRIM(RTRIM(CAST(mp.Proses AS VARCHAR(20)))) AS proses_kod,
               mp.ProsesNo,
               ISNULL(pm.Tanim, CAST(mp.Proses AS VARCHAR(20))) AS proses_adi
        FROM Model_P mp
        LEFT JOIN Proses_M pm ON pm.Pro = mp.Proses
        WHERE mp.ModelKod IN ({ph})
        ORDER BY mp.ModelKod, mp.ProsesNo
    """, tuple(codes))
    tmp = defaultdict(list)
    for r in cur.fetchall():
        mk = (r[0] or '').strip()
        pk = str(r[1] or '').strip()
        if not pk:
            continue
        adi = (r[3] or pk).strip()
        tmp[mk].append({
            'proses_kod': pk,
            'proses_no': int(r[2] or 0),
            'proses_adi': adi,
        })
        adi_map[pk] = adi
    routes = dict(tmp)
    return routes, adi_map


def _distinct_model_kods(emir_nos, emir_meta, tip=None):
    seen, out = set(), []
    for en in emir_nos or []:
        meta = emir_meta.get(en) or {}
        if tip and (meta.get('tip') or '').upper() != tip.upper():
            continue
        mk = (meta.get('model_kod') or '').strip()
        if mk and mk not in seen:
            seen.add(mk)
            out.append(mk)
    return sorted(out)


def _canonical_proses_order(m_emirs, y_emirs, emir_meta, model_p_routes,
                            em2em_by_proses, move_by_proses):
    """Y Model_P zinciri (ProsesNo ASC) → M Model_P zinciri (ProsesNo ASC) → ekstralar."""
    y_models = _distinct_model_kods(y_emirs, emir_meta, 'Y') or _distinct_model_kods(y_emirs, emir_meta)
    m_models = _distinct_model_kods(m_emirs, emir_meta, 'M') or _distinct_model_kods(m_emirs, emir_meta)

    ordered = []
    seen_pk = set()

    def _add_chain(models, tier):
        for mk in sorted(models):
            for step in model_p_routes.get(mk, []):
                pk = step['proses_kod']
                if pk in seen_pk:
                    continue
                seen_pk.add(pk)
                ordered.append({
                    'proses_kod': pk,
                    'proses_no': step.get('proses_no', 0),
                    'tier': tier,
                    'model_kod': mk,
                })

    _add_chain(y_models, 0)
    _add_chain(m_models, 1)

    extras = sorted(
        (set(em2em_by_proses.keys()) | set(move_by_proses.keys())) - seen_pk,
        key=lambda pk: (9999, pk),
    )
    for pk in extras:
        ordered.append({
            'proses_kod': pk,
            'proses_no': 9999,
            'tier': 2,
            'model_kod': '',
        })
    return ordered


def _emirs_for_proses(pk, query_emirs, emir_meta, model_p_routes,
                      em2em_by_proses, move_by_proses):
    emirs = set()
    emirs |= em2em_by_proses.get(pk, set())
    emirs |= move_by_proses.get(pk, set())
    for en in query_emirs:
        mk = (emir_meta.get(en, {}).get('model_kod') or '').strip()
        chain = model_p_routes.get(mk, [])
        if any(str(s.get('proses_kod', '')).strip() == pk for s in chain):
            emirs.add(en)
    return sorted(e for e in emirs if e in query_emirs)


def _build_dynamic_prosesler(m_emirs, y_emirs, em2em_rows, con_by_emir, wait_by_emir,
                             giren_map, proses_adi_map, emir_meta=None,
                             model_p_routes=None):
    """Full route: Model_P ∪ Em2Em ∪ hareket (scope içi). Sıra: Y→M ProsesNo."""
    query_emirs = set(m_emirs or []) | set(y_emirs or [])
    emir_meta = emir_meta or {}
    model_p_routes = model_p_routes or {}

    em2em_by_proses = defaultdict(set)
    for row in em2em_rows or []:
        pk = str(row.get('proses') or '').strip()
        if not pk:
            continue
        men = int(row.get('m_emir') or 0)
        yen = int(row.get('y_emir') or 0)
        if men in query_emirs:
            em2em_by_proses[pk].add(men)
        if yen in query_emirs:
            em2em_by_proses[pk].add(yen)

    move_by_proses = _emirler_proses_hareket(con_by_emir, wait_by_emir, query_emirs)
    order = _canonical_proses_order(
        m_emirs, y_emirs, emir_meta, model_p_routes, em2em_by_proses, move_by_proses,
    )

    prosesler = []
    for entry in order:
        pk = entry['proses_kod']
        route_emirs = _emirs_for_proses(
            pk, query_emirs, emir_meta, model_p_routes, em2em_by_proses, move_by_proses,
        )
        if not route_emirs:
            continue
        calc_emirs = _emirs_for_proses_calc(
            pk, entry.get('tier'), m_emirs, y_emirs, emir_meta, model_p_routes,
            move_by_proses, em2em_by_proses,
        )
        if not calc_emirs:
            calc_emirs = route_emirs
        ozet = _proses_ozet(
            calc_emirs, con_by_emir, wait_by_emir, giren_map, pk, emir_meta,
        )
        prosesler.append({
            'proses_kod': pk,
            'proses_adi': proses_adi_map.get(pk, pk),
            'emir_nos': calc_emirs,
            'proses_no': entry.get('proses_no'),
            'route_tier': entry.get('tier'),
            **ozet,
        })
    return prosesler


def _proses_by_kod(prosesler, proses_kod):
    pk = str(proses_kod or '').strip()
    for p in prosesler or []:
        if str(p.get('proses_kod', '')).strip() == pk:
            return p
    return None


def _kategori(model_kod, model_adi=''):
    """hedef/korgun_v2._kategori_belirle ile parity (SAYA eklendi)."""
    mk = (model_kod or '').upper()
    # Türkçe normalizasyon — /hedef ile aynı
    ma = (model_adi or '').upper().replace('İ', 'I').replace('Ğ', 'G').replace('Ö', 'O')
    if 'ATKI' in mk or 'ATKI' in ma:
        return 'ATKI'
    if 'GOVDE' in mk or 'GOVDE' in ma or 'GÖVDE' in (model_adi or '').upper():
        return 'GOVDE'
    if 'TABAN' in mk or 'TABAN' in ma:
        return 'TABAN'
    if 'SAYA' in mk or 'SAYA' in ma or mk.startswith('SK-'):
        return 'SAYA'
    return 'MAMUL'


def _yuzde(biten, verilen):
    v = int(verilen or 0)
    b = int(biten or 0)
    if v <= 0:
        return 0.0
    return round(min(100.0, (b / v) * 100), 1)


def _durum_from_miktar(verilen, biten, devam=0):
    v = int(verilen or 0)
    b = int(biten or 0)
    d = int(devam or 0)
    if v <= 0:
        return 'BAŞLANMADI', 'gri'
    if d > 0 or (b > 0 and b < v):
        return 'DEVAM', 'sari'
    if b >= v:
        return 'BİTTİ', 'yesil'
    return 'BAŞLANMADI', 'gri'


def _emir_proses_miktar(en, proses_kod, con_by_emir, wait_by_emir, giren_map):
    """Tek emir + proses için miktar — con öncelikli (wait duplicate sayılmaz)."""
    pk = str(proses_kod or '').strip()
    con_rows = [
        r for r in con_by_emir.get(en, [])
        if str(r.get('Proses', '')).strip() == pk
    ]
    wait_rows = [
        r for r in wait_by_emir.get(en, [])
        if str(r.get('Proses', '')).strip() == pk
    ]
    if con_rows:
        verilen = sum(int(r.get('verilen') or 0) for r in con_rows)
        devam = sum(int(r.get('devam_eden') or 0) for r in con_rows)
        biten = sum(int(r.get('biten') or 0) for r in con_rows)
    elif wait_rows:
        verilen = sum(int(r.get('verilen') or 0) for r in wait_rows)
        devam = sum(int(r.get('devam_eden') or 0) for r in wait_rows)
        biten = sum(int(r.get('biten') or 0) for r in wait_rows)
    else:
        verilen = int(giren_map.get(en, 0) or 0)
        devam = biten = 0
    return verilen, devam, biten


def _emirs_for_proses_calc(pk, route_tier, m_emirs, y_emirs, emir_meta, model_p_routes,
                           move_by_proses, em2em_by_proses):
    """Proses yüzde paydası — yalnız canonical emir seviyesi (M/Y karıştırma yok)."""
    m_set = set(m_emirs or [])
    y_set = set(y_emirs or [])

    def _by_model_step(emirs, tip):
        out = []
        for en in emirs:
            meta = emir_meta.get(en) or {}
            if tip and (meta.get('tip') or 'M').upper() != tip.upper():
                continue
            mk = (meta.get('model_kod') or '').strip()
            if any(str(s.get('proses_kod', '')).strip() == pk for s in model_p_routes.get(mk, [])):
                out.append(en)
        return out

    m_mov = move_by_proses.get(pk, set()) & m_set
    y_mov = move_by_proses.get(pk, set()) & y_set

    if m_mov and not y_mov:
        pool, tip = m_set, 'M'
    elif y_mov and not m_mov:
        pool, tip = y_set, 'Y'
    elif route_tier == 0:
        pool, tip = y_set, 'Y'
    elif route_tier == 1:
        pool, tip = m_set, 'M'
    else:
        mov = m_mov | y_mov
        if mov:
            return sorted(mov)
        em2 = em2em_by_proses.get(pk, set()) & (m_set | y_set)
        return sorted(em2)

    mov_ok = m_mov if tip == 'M' else y_mov
    calc = sorted(set(_by_model_step(pool, tip)) | mov_ok)
    return calc


def _emir_seviyesi_label(emir_nos, emir_meta):
    tips = {
        (emir_meta.get(en) or {}).get('tip', '').upper()
        for en in (emir_nos or [])
    } - {''}
    if tips == {'M'}:
        return 'M'
    if tips == {'Y'}:
        return 'Y'
    if len(tips) > 1:
        return 'MIXED'
    return 'M'


def _proses_ozet(emir_nos, con_by_emir, wait_by_emir, giren_map, proses_kod=None,
                 emir_meta=None):
    pk = str(proses_kod or '').strip() if proses_kod is not None else None
    verilen = devam = biten = 0
    biten_emir_sayisi = 0
    emir_detay = []
    for en in emir_nos or []:
        if pk:
            v, d, b = _emir_proses_miktar(en, pk, con_by_emir, wait_by_emir, giren_map)
        else:
            rows = con_by_emir.get(en, []) + wait_by_emir.get(en, [])
            v = sum(int(r.get('verilen') or 0) for r in rows) or int(giren_map.get(en, 0) or 0)
            d = sum(int(r.get('devam_eden') or 0) for r in rows)
            b = sum(int(r.get('biten') or 0) for r in rows)
        verilen += v
        devam += d
        biten += b
        if v > 0 and b >= v:
            biten_emir_sayisi += 1
        meta = (emir_meta or {}).get(en) or {}
        emir_detay.append({
            'emir_no': en,
            'tip': (meta.get('tip') or '').upper(),
            'model_kod': meta.get('model_kod') or '',
            'model_adi': meta.get('model_adi') or meta.get('model_kod') or '',
            'giren': int(meta.get('giren') or giren_map.get(en, 0) or 0),
            'verilen': v,
            'devam': d,
            'biten': b,
            'kalan': max(0, v - b),
            'yuzde': _yuzde(b, v),
            'durum': _durum_from_miktar(v, b, d)[0],
        })
    durum, renk = _durum_from_miktar(verilen, biten, devam)
    pct = _yuzde(biten, verilen)
    seviye = _emir_seviyesi_label(emir_nos, emir_meta or {})
    return {
        'durum': durum, 'renk': renk, 'yuzde': pct,
        'verilen': verilen, 'devam': devam, 'biten': biten,
        'kalan': max(0, verilen - biten),
        'hedef_miktar': verilen,
        'emir_seviyesi': seviye,
        'emir_sayisi': len(emir_nos or []),
        'biten_emir_sayisi': biten_emir_sayisi,
        'emir_detay': emir_detay,
    }


def _genel_uretim_durum(prosesler, m_emirs, giren_map):
    if not prosesler:
        return 'BAŞLANMADI', 'gri', 0.0
    last = prosesler[-1]
    if last.get('durum') == 'BİTTİ' and int(last.get('verilen') or 0) > 0:
        return 'BİTTİ', 'yesil', float(last.get('yuzde') or 0)
    started = [p for p in prosesler if p.get('durum') != 'BAŞLANMADI']
    if started:
        avg = sum(float(p.get('yuzde') or 0) for p in started) / len(started)
        return 'DEVAM', 'sari', round(avg, 1)
    return 'BAŞLANMADI', 'gri', 0.0


def _genel_satir_durum(uretim_durum, uretim_renk, uretim_yuzde, plan_bas, plan_bit):
    today = date.today()
    pb = pe = None
    try:
        if plan_bas:
            pb = datetime.strptime(str(plan_bas)[:10], '%Y-%m-%d').date()
        if plan_bit:
            pe = datetime.strptime(str(plan_bit)[:10], '%Y-%m-%d').date()
    except ValueError:
        pass
    if uretim_durum == 'BİTTİ':
        return uretim_durum, uretim_renk, uretim_yuzde
    if uretim_durum == 'DEVAM':
        return uretim_durum, uretim_renk, uretim_yuzde
    if pb and pb <= today and uretim_durum == 'BAŞLANMADI':
        return 'GERİDE', 'kirmizi', uretim_yuzde
    if pe and pe < today and uretim_durum != 'BİTTİ':
        return 'GERİDE', 'kirmizi', uretim_yuzde
    return uretim_durum, uretim_renk, uretim_yuzde


def _emir_no_kompakt(emir_list):
    if not emir_list:
        return '-', 0
    nums = sorted([int(x) for x in emir_list], reverse=True)
    if len(nums) == 1:
        return str(nums[0]), 1
    return str(nums[0]) + ' +' + str(len(nums) - 1), len(nums)


def _load_emir_hareket(cur, query_emirs):
    """Aktif + archive hareket tabloları birlikte okunur (/hedef parity).

    con  : Urt_con_gch  UNION ALL Urtx_con_gch
    wait : Urt_Wait_gch UNION ALL Urtx_Wait_gch

    Aynı (EmirNo, Proses) çifti iki tabloda varsa toplamak doğrudur —
    arşiv kaydı aktife taşınmaz, gerçek hareketler ayrı satırlardır.
    /hedef korgun_v2 da aynı şekilde UNION ALL ile toplar.
    """
    if not query_emirs:
        return {}, {}, {}
    ph = ','.join(['%s'] * len(query_emirs))
    t = tuple(query_emirs)

    giren_map = {}
    # Urt_Em_gch + Urtx_Em_gch — archive Y emirlerin giren bilgisi Urtx'te olabilir
    cur.execute(f"""
        SELECT EmirNo, COALESCE(SUM(Giren), 0)
        FROM (
            SELECT EmirNo, Giren FROM Urt_Em_gch  WHERE EmirNo IN ({ph})
            UNION ALL
            SELECT EmirNo, Giren FROM Urtx_Em_gch WHERE EmirNo IN ({ph})
        ) g
        GROUP BY EmirNo
    """, t + t)
    for r in cur.fetchall():
        giren_map[int(r[0])] = int(float(r[1] or 0))

    # con_gch: aktif + archive UNION ALL
    cur.execute(f"""
        SELECT g.EmirNo, g.Proses,
               COALESCE(SUM(g.Giren), 0)                                   AS verilen,
               COALESCE(SUM(g.Giren - g.Cikan - ISNULL(g.Fire, 0)), 0)    AS devam_eden,
               COALESCE(SUM(g.Cikan), 0)                                   AS biten
        FROM (
            SELECT EmirNo, Proses, Giren, Cikan, Fire FROM Urt_con_gch  WHERE EmirNo IN ({ph})
            UNION ALL
            SELECT EmirNo, Proses, Giren, Cikan, Fire FROM Urtx_con_gch WHERE EmirNo IN ({ph})
        ) g
        GROUP BY g.EmirNo, g.Proses
    """, t + t)
    con_by_emir: defaultdict = defaultdict(list)
    for r in cur.fetchall():
        con_by_emir[int(r[0])].append({
            'Proses': r[1], 'verilen': r[2],
            'devam_eden': r[3], 'biten': r[4],
        })

    # wait_gch: aktif + archive UNION ALL
    cur.execute(f"""
        SELECT g.EmirNo, g.Proses,
               COALESCE(SUM(g.Giren), 0)              AS verilen,
               CAST(0 AS DECIMAL(18,4))               AS devam_eden,
               CAST(0 AS DECIMAL(18,4))               AS biten
        FROM (
            SELECT EmirNo, Proses, Giren, Cikan FROM Urt_Wait_gch  WHERE EmirNo IN ({ph})
            UNION ALL
            SELECT EmirNo, Proses, Giren, Cikan FROM Urtx_Wait_gch WHERE EmirNo IN ({ph})
        ) g
        GROUP BY g.EmirNo, g.Proses
    """, t + t)
    wait_by_emir: defaultdict = defaultdict(list)
    for r in cur.fetchall():
        wait_by_emir[int(r[0])].append({
            'Proses': r[1], 'verilen': r[2],
            'devam_eden': r[3], 'biten': r[4],
        })
    return giren_map, con_by_emir, wait_by_emir


def _build_satir(cur, sip_no, sip_harinx, mamul_skod, rkod, har_ctx, sip_meta,
                 include_lots=False, plan_fields=None):
    plan_fields = plan_fields or {}
    har_miktar, birim, termin, sresim, model_tanim = har_ctx

    cur.execute("""
        SELECT e.EmirNo,
               UPPER(LTRIM(RTRIM(ISNULL(e.Tip, '')))) AS tip,
               e.ModelKod,
               ISNULL(m.Tanim, e.ModelKod) AS model_adi,
               g.RKOD,
               MAX(rn.Tanim) AS renk_tanim,
               COALESCE(SUM(g.Giren), 0) AS giren
        FROM (
            SELECT EmirNo, RKOD, Giren FROM Urt_Em_gch
            WHERE FisNo = %s AND FisHarinx = %s
            UNION ALL
            SELECT EmirNo, RKOD, Giren FROM Urtx_Em_gch
            WHERE FisNo = %s AND FisHarinx = %s
        ) g
        INNER JOIN (
            SELECT EmirNo, Tip, ModelKod FROM Urt_Emir
            UNION ALL
            SELECT EmirNo, Tip, ModelKod FROM Urtx_Emir
        ) e ON e.EmirNo = g.EmirNo
        LEFT JOIN Model_M m ON m.ModelKod = e.ModelKod
        LEFT JOIN P_RNK_Tip rn ON rn.RENK_KOD = g.RKOD
        GROUP BY e.EmirNo, e.Tip, e.ModelKod, m.Tanim, g.RKOD
        ORDER BY e.EmirNo DESC
    """, (sip_no, sip_harinx, sip_no, sip_harinx))
    emir_raw = cur.fetchall()

    emir_meta = {}
    m_by_rkod = defaultdict(list)
    for r in emir_raw:
        en, tip, mk, ma, rk, renk_t, giren = r
        en = int(en)
        tip = (tip or 'M').upper()
        rk_i = int(rk) if rk else 0
        emir_meta[en] = {
            'emir_no': en, 'tip': tip, 'model_kod': mk or '',
            'model_adi': ma or mk or '', 'rkod': rk_i,
            'renk': (renk_t or '').strip() or (str(rk_i) if rk_i else '-'),
            'giren': int(float(giren or 0)),
        }
        if tip == 'M' and (mk or '') == (mamul_skod or ''):
            m_by_rkod[rk_i].append(en)

    if rkod not in m_by_rkod:
        m_by_rkod[rkod] = [
            en for en, m in emir_meta.items()
            if m['tip'] == 'M' and m['rkod'] == rkod
        ]
    m_emirs = m_by_rkod.get(rkod) or []
    if not m_emirs:
        return None

    sample = emir_meta[m_emirs[0]]
    renk_tanim = sample['renk']
    toplam_m = sum(emir_meta[e]['giren'] for e in m_emirs)

    ph = ','.join(['%s'] * len(m_emirs))
    cur.execute(f"""
        SELECT em2.EmirNo, em2.EmirNo_YM, LTRIM(RTRIM(ISNULL(em2.Proses, ''))) AS proses
        FROM Urt_Em2Em em2 WHERE em2.EmirNo IN ({ph})
    """, tuple(m_emirs))
    y_by_m = defaultdict(list)
    em2em_rows = []
    for r in cur.fetchall():
        men, yen, pk = int(r[0]), int(r[1]), str(r[2] or '').strip()
        y_by_m[men].append(yen)
        em2em_rows.append({'m_emir': men, 'y_emir': yen, 'proses': pk})
    y_emirs = list({y for ys in y_by_m.values() for y in ys})

    # Em2Em ile bulunan Y emirlerinin meta bilgisini Urt_Emir + Urtx_Emir'den çek.
    # Arşiv Y emirleri Urtx_Emir'e taşınır; FisHarinx filtresinin dışında kalabilirler.
    # parent M ilişkisinden scope edildiği için başka sipariş/renkin emirleri karışmaz.
    y_emirs_eksik = [y for y in y_emirs if y not in emir_meta]
    if y_emirs_eksik:
        ph_y = ','.join(['%s'] * len(y_emirs_eksik))
        cur.execute(f"""
            SELECT e.EmirNo, UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) AS tip,
                   e.ModelKod, ISNULL(m.Tanim, e.ModelKod) AS model_adi,
                   g.RKOD, COALESCE(SUM(g.Giren),0) AS giren
            FROM (
                SELECT EmirNo, Tip, ModelKod FROM Urt_Emir  WHERE EmirNo IN ({ph_y})
                UNION ALL
                SELECT EmirNo, Tip, ModelKod FROM Urtx_Emir WHERE EmirNo IN ({ph_y})
            ) e
            LEFT JOIN Model_M m ON m.ModelKod = e.ModelKod
            LEFT JOIN Urt_Em_gch g ON g.EmirNo = e.EmirNo
            GROUP BY e.EmirNo, e.Tip, e.ModelKod, m.Tanim, g.RKOD
        """, tuple(y_emirs_eksik) * 2)
        for r in cur.fetchall():
            en2 = int(r[0])
            if en2 not in emir_meta:
                emir_meta[en2] = {
                    'emir_no': en2,
                    'tip': (r[1] or 'Y').upper(),
                    'model_kod': r[2] or '',
                    'model_adi': r[3] or r[2] or '',
                    'rkod': int(r[4]) if r[4] else 0,
                    'giren': int(float(r[5] or 0)),
                }

    query_emirs = list(set(m_emirs + y_emirs))

    giren_map, con_by_emir, wait_by_emir = _load_emir_hareket(cur, query_emirs)
    for en, meta in emir_meta.items():
        giren_map.setdefault(en, meta['giren'])

    move_codes = set(_emirler_proses_hareket(con_by_emir, wait_by_emir, set(query_emirs)).keys())
    em2em_codes = {str(r.get('proses') or '').strip() for r in em2em_rows if r.get('proses')}
    scope_model_kods = _distinct_model_kods(query_emirs, emir_meta)
    model_p_routes, model_p_adi = _load_model_p_routes(cur, scope_model_kods)
    model_p_codes = {s['proses_kod'] for steps in model_p_routes.values() for s in steps}
    proses_adi_map = _merge_proses_adlari(
        _load_proses_adlari(cur, move_codes | em2em_codes | model_p_codes),
        model_p_adi_map=model_p_adi,
    )
    prosesler = _build_dynamic_prosesler(
        m_emirs, y_emirs, em2em_rows, con_by_emir, wait_by_emir, giren_map, proses_adi_map,
        emir_meta=emir_meta, model_p_routes=model_p_routes,
    )
    u_durum, u_renk, u_yuzde = _genel_uretim_durum(prosesler, m_emirs, giren_map)
    g_durum, g_renk, g_yuzde = _genel_satir_durum(
        u_durum, u_renk, u_yuzde,
        plan_fields.get('plan_baslangic'), plan_fields.get('plan_bitis'),
    )
    emir_disp, lot_count = _emir_no_kompakt(m_emirs)

    row = {
        'canonical_key': f'{sip_no}|{sip_harinx}|{mamul_skod}|{rkod}',
        'sip_no': str(sip_no),
        'sip_harinx': sip_harinx,
        'emir_no': emir_disp,
        'emir_lot_sayisi': lot_count,
        'emir_nos': m_emirs,
        'model_kod': mamul_skod,
        'model_tanim': model_tanim,
        'model_gorsel_skod': mamul_skod,
        'sresim': (sresim or '').strip(),
        'renk': renk_tanim,
        'rkod': rkod,
        'miktar': toplam_m or har_miktar,
        'birim': birim or 'CIFT',
        'termin': termin or sip_meta.get('teslim_tar') or '-',
        'musteri': sip_meta.get('musteri'),
        'm_emir_sayisi': len(m_emirs),
        'y_emir_sayisi': len(y_emirs),
        'prosesler': prosesler,
        'uretim_durum': u_durum,
        'durum': g_durum,
        'durum_renk': g_renk,
        'yuzde': g_yuzde,
    }
    if include_lots:
        row['m_lotlar'] = _m_lotlar_detay(
            m_emirs, y_by_m, em2em_rows, emir_meta, con_by_emir, wait_by_emir, giren_map, cur,
        )
    return row


def siparis_model_satirlari(con, sip_no, include_lots=False):
    cur = con.cursor()
    sip_no = int(sip_no)
    cur.execute("""
        SELECT CAST(sk.SipNo AS VARCHAR(20)) AS sip_no,
               CONVERT(VARCHAR(10), sk.SipTar, 120) AS siparis_tarihi,
               LTRIM(RTRIM(ISNULL(ck.CName, ''))) AS musteri,
               CONVERT(VARCHAR(10), sk.TeslimTar, 120) AS teslim_tar
        FROM Siparis_Kay sk
        LEFT JOIN Cari_Kart ck ON ck.CKod = sk.CariKod
        WHERE sk.SipNo = %s
    """, (sip_no,))
    kay = cur.fetchone()
    if not kay:
        return None
    sip_meta = {
        'sip_no': str(kay[0]), 'siparis_tarihi': kay[1] or '',
        'musteri': kay[2] or '-', 'teslim_tar': kay[3] or '',
    }

    cur.execute("""
        SELECT sh.SipHarinx, sh.SKOD, ISNULL(m.Tanim, sh.SKOD) AS model_tanim,
               COALESCE(sh.Miktar, 0) AS miktar, sh.Birim,
               CONVERT(VARCHAR(10), sh.TerminTarihi, 120) AS termin,
               LTRIM(RTRIM(ISNULL(sk2.SResim, ''))) AS sresim
        FROM Siparis_Har sh
        LEFT JOIN Model_M m ON m.ModelKod = sh.SKOD
        LEFT JOIN StokKart sk2 ON sk2.SKod = sh.SKOD
        WHERE sh.SipNo = %s
        ORDER BY sh.SipHarinx
    """, (sip_no,))
    har_rows = cur.fetchall()
    if not har_rows:
        return {'siparis': sip_meta, 'satirlar': [], 'onizleme': []}

    onizleme, satirlar = [], []
    seen_rkod = set()

    for har in har_rows:
        sip_harinx, mamul_skod, model_tanim, har_miktar, birim, termin, sresim = har
        sip_harinx = int(sip_harinx)
        har_miktar = int(float(har_miktar or 0))
        har_ctx = (har_miktar, birim, termin, sresim, model_tanim)

        cur.execute("""
            SELECT DISTINCT g.RKOD FROM (
                SELECT EmirNo, RKOD FROM Urt_Em_gch
                WHERE FisNo = %s AND FisHarinx = %s
                UNION ALL
                SELECT EmirNo, RKOD FROM Urtx_Em_gch
                WHERE FisNo = %s AND FisHarinx = %s
            ) g
            INNER JOIN (
                SELECT EmirNo, Tip, ModelKod FROM Urt_Emir
                UNION ALL
                SELECT EmirNo, Tip, ModelKod FROM Urtx_Emir
            ) e ON e.EmirNo = g.EmirNo
            WHERE UPPER(ISNULL(e.Tip,'M'))='M' AND e.ModelKod = %s
        """, (sip_no, sip_harinx, sip_no, sip_harinx, mamul_skod))
        rkods = [int(r[0] or 0) for r in cur.fetchall()]
        if not rkods:
            rkods = [0]

        for rkod in sorted(set(rkods)):
            key = (sip_no, sip_harinx, mamul_skod, rkod)
            if key in seen_rkod:
                continue
            seen_rkod.add(key)
            satir = _build_satir(cur, sip_no, sip_harinx, mamul_skod, rkod, har_ctx, sip_meta, include_lots)
            if not satir:
                continue
            satirlar.append(satir)
            onizleme.append({
                'canonical_key': satir['canonical_key'],
                'sip_no': sip_no,
                'sip_harinx': sip_harinx,
                'mamul_skod': mamul_skod,
                'model_kod': mamul_skod,
                'model_tanim': model_tanim,
                'renk': satir['renk'],
                'rkod': rkod,
                'miktar': satir['miktar'],
                'birim': satir['birim'],
                'termin': satir['termin'],
                'sresim': satir['sresim'],
                'm_emir_sayisi': satir['m_emir_sayisi'],
                'y_emir_sayisi': satir['y_emir_sayisi'],
            })

    cur.close()
    return {'siparis': sip_meta, 'satirlar': satirlar, 'onizleme': onizleme}


def model_satir_by_canonical(con, sip_no, sip_harinx, mamul_skod, rkod, plan_fields=None, include_lots=False):
    cur = con.cursor()
    sip_no = int(sip_no)
    cur.execute("""
        SELECT CAST(sk.SipNo AS VARCHAR(20)),
               LTRIM(RTRIM(ISNULL(ck.CName, ''))),
               CONVERT(VARCHAR(10), sk.TeslimTar, 120)
        FROM Siparis_Kay sk
        LEFT JOIN Cari_Kart ck ON ck.CKod = sk.CariKod
        WHERE sk.SipNo = %s
    """, (sip_no,))
    kay = cur.fetchone()
    sip_meta = {'musteri': kay[1] if kay else '-', 'teslim_tar': kay[2] if kay else ''}

    cur.execute("""
        SELECT COALESCE(sh.Miktar,0), sh.Birim,
               CONVERT(VARCHAR(10), sh.TerminTarihi, 120),
               LTRIM(RTRIM(ISNULL(sk2.SResim,''))),
               ISNULL(m.Tanim, sh.SKOD)
        FROM Siparis_Har sh
        LEFT JOIN Model_M m ON m.ModelKod = sh.SKOD
        LEFT JOIN StokKart sk2 ON sk2.SKod = sh.SKOD
        WHERE sh.SipNo = %s AND sh.SipHarinx = %s AND sh.SKOD = %s
    """, (sip_no, int(sip_harinx), mamul_skod))
    har = cur.fetchone()
    if not har:
        return None
    har_ctx = (int(float(har[0] or 0)), har[1], har[2], har[3], har[4])
    return _build_satir(
        cur, sip_no, int(sip_harinx), mamul_skod, int(rkod),
        har_ctx, sip_meta, include_lots, plan_fields or {},
    )


def merge_plan_korgun(plan_row: dict, korgun_row: dict | None) -> dict:
    out = dict(korgun_row or {})
    out['plan_id'] = plan_row.get('id')
    out['plan_donemi'] = plan_row.get('plan_donemi')
    out['plan_baslangic'] = plan_row.get('plan_baslangic')
    out['plan_bitis'] = plan_row.get('plan_bitis')
    out['oncelik'] = plan_row.get('oncelik')
    out['plan_gerekce'] = plan_row.get('plan_gerekce')
    out['plan_notu'] = plan_row.get('plan_notu')
    if korgun_row:
        g_d, g_r, g_y = _genel_satir_durum(
            korgun_row.get('uretim_durum') or korgun_row.get('durum'),
            korgun_row.get('durum_renk', 'gri'),
            korgun_row.get('yuzde', 0),
            plan_row.get('plan_baslangic'), plan_row.get('plan_bitis'),
        )
        out['durum'] = g_d
        out['durum_renk'] = g_r
        out['yuzde'] = g_y
        out['cari'] = (korgun_row.get('musteri') or '').strip() or '-'
    else:
        out.setdefault('durum', 'BAŞLANMADI')
        out.setdefault('durum_renk', 'gri')
        out['model_kod'] = plan_row.get('mamul_skod')
        out['renk'] = plan_row.get('renk_adi')
        out['miktar'] = plan_row.get('miktar')
        out['termin'] = plan_row.get('termin')
        out['sip_no'] = str(plan_row.get('sip_no'))
        out['canonical_key'] = plan_row.get('canonical_key')
    return out


def _m_lotlar_detay(m_emirs, y_by_m, em2em_rows, emir_meta, con_by_emir, wait_by_emir, giren_map, cur):
    out = []
    for men in sorted(m_emirs, reverse=True):
        mv = giren_map.get(men, 0)
        mb = sum(int(r.get('biten') or 0) for r in con_by_emir.get(men, []))
        md = sum(int(r.get('devam_eden') or 0) for r in con_by_emir.get(men, []))
        mdur, _ = _durum_from_miktar(mv, mb, md)
        ys = [y for y in y_by_m.get(men, []) if emir_meta.get(y)]
        lot_em2em = [r for r in em2em_rows if int(r.get('m_emir') or 0) == men]
        lot_emirs = [men] + ys
        move_codes = set(_emirler_proses_hareket(con_by_emir, wait_by_emir, set(lot_emirs)).keys())
        em2em_codes = {str(r.get('proses') or '').strip() for r in lot_em2em if r.get('proses')}
        lot_meta = {en: emir_meta[en] for en in lot_emirs if en in emir_meta}
        lot_model_kods = _distinct_model_kods(lot_emirs, lot_meta)
        lot_model_p, lot_mp_adi = _load_model_p_routes(cur, lot_model_kods)
        lot_mp_codes = {s['proses_kod'] for steps in lot_model_p.values() for s in steps}
        lot_adi_map = _merge_proses_adlari(
            _load_proses_adlari(cur, move_codes | em2em_codes | lot_mp_codes),
            model_p_adi_map=lot_mp_adi,
        )
        lot_prosesler = _build_dynamic_prosesler(
            [men], ys, lot_em2em, con_by_emir, wait_by_emir, giren_map, lot_adi_map,
            emir_meta=lot_meta, model_p_routes=lot_model_p,
        )
        out.append({
            'emir_no': men, 'miktar': mv, 'durum': mdur,
            'prosesler': lot_prosesler,
            'y_emir_sayisi': len(ys),
        })
    return out


def m_emirler_lazy(con, sip_no, sip_harinx, mamul_skod, rkod):
    row = model_satir_by_canonical(con, sip_no, sip_harinx, mamul_skod, rkod, include_lots=True)
    if not row:
        return []
    lots = []
    for m in row.get('m_lotlar') or []:
        lots.append({
            'emir_no': m['emir_no'], 'miktar': m['miktar'], 'durum': m['durum'],
            'prosesler': m.get('prosesler') or [],
            'y_emir_sayisi': m.get('y_emir_sayisi', 0),
        })
    return lots


def y_emirler_lazy(con, m_emir_no):
    cur = con.cursor()
    m_emir_no = int(m_emir_no)
    cur.execute("SELECT EmirNo_YM FROM Urt_Em2Em WHERE EmirNo = %s", (m_emir_no,))
    y_list = [int(r[0]) for r in cur.fetchall()]
    if not y_list:
        return []
    ph = ','.join(['%s'] * len(y_list))
    cur.execute(f"""
        SELECT e.EmirNo, e.ModelKod, ISNULL(m.Tanim, e.ModelKod)
        FROM Urt_Emir e LEFT JOIN Model_M m ON m.ModelKod = e.ModelKod
        WHERE e.EmirNo IN ({ph})
    """, tuple(y_list))
    emir_meta = {int(r[0]): {'model_kod': r[1], 'model_adi': r[2]} for r in cur.fetchall()}
    giren_map, con_by_emir, wait_by_emir = _load_emir_hareket(cur, y_list)
    return _y_emir_detay(y_list, emir_meta, con_by_emir, wait_by_emir, giren_map, cur)


def proses_detay_lazy(con, emir_no):
    cur = con.cursor()
    emir_no = int(emir_no)
    rows_out = []

    cur.execute("""
        SELECT g.Proses, ISNULL(pm.Tanim, CAST(g.Proses AS VARCHAR(20))),
               LTRIM(RTRIM(ISNULL(g.AltProses,''))),
               ISNULL(pd.Tanim, LTRIM(RTRIM(ISNULL(g.AltProses,'')))),
               g.WMakNum,
               COALESCE(SUM(g.Giren),0), COALESCE(SUM(g.Giren-g.Cikan-ISNULL(g.Fire,0)),0),
               COALESCE(SUM(g.Cikan),0)
        FROM (
            SELECT Proses, AltProses, WMakNum, Giren, Cikan, Fire FROM Urt_con_gch  WHERE EmirNo = %s
            UNION ALL
            SELECT Proses, AltProses, WMakNum, Giren, Cikan, Fire FROM Urtx_con_gch WHERE EmirNo = %s
        ) g
        LEFT JOIN Proses_M pm ON pm.Pro = g.Proses
        LEFT JOIN Proses_D pd ON pd.Pro = g.Proses AND pd.AltPro = g.AltProses
        GROUP BY g.Proses, pm.Tanim, g.AltProses, pd.Tanim, g.WMakNum
    """, (emir_no, emir_no))
    for r in cur.fetchall():
        v, d, b = int(float(r[5] or 0)), int(float(r[6] or 0)), int(float(r[7] or 0))
        durum, renk = _durum_from_miktar(v, b, d)
        rows_out.append({
            'kaynak': 'con', 'proses_kod': str(r[0]).strip(), 'proses_adi': r[1] or '-',
            'alt_proses_kod': r[2] or '', 'alt_proses_adi': r[3] or '-',
            'tezgah': r[4], 'verilen': v, 'devam': d, 'biten': b,
            'kalan': max(0, v - b), 'yuzde': _yuzde(b, v), 'durum': durum, 'renk': renk,
        })

    cur.execute("""
        SELECT g.Proses, ISNULL(pm.Tanim, CAST(g.Proses AS VARCHAR(20))),
               LTRIM(RTRIM(ISNULL(g.AltProses,''))),
               ISNULL(pd.Tanim, LTRIM(RTRIM(ISNULL(g.AltProses,'')))),
               g.WMakNum,
               COALESCE(SUM(g.Giren),0), COALESCE(SUM(g.Giren-g.Cikan),0), CAST(0 AS DECIMAL(18,4))
        FROM (
            SELECT Proses, AltProses, WMakNum, Giren, Cikan FROM Urt_Wait_gch  WHERE EmirNo = %s
            UNION ALL
            SELECT Proses, AltProses, WMakNum, Giren, Cikan FROM Urtx_Wait_gch WHERE EmirNo = %s
        ) g
        LEFT JOIN Proses_M pm ON pm.Pro = g.Proses
        LEFT JOIN Proses_D pd ON pd.Pro = g.Proses AND pd.AltPro = g.AltProses
        GROUP BY g.Proses, pm.Tanim, g.AltProses, pd.Tanim, g.WMakNum
    """, (emir_no, emir_no))
    for r in cur.fetchall():
        v = int(float(r[5] or 0))
        rows_out.append({
            'kaynak': 'wait', 'proses_kod': str(r[0]).strip(), 'proses_adi': r[1] or '-',
            'alt_proses_kod': r[2] or '', 'alt_proses_adi': r[3] or '-',
            'tezgah': r[4], 'verilen': v, 'devam': int(float(r[6] or 0)), 'biten': 0,
            'kalan': v, 'yuzde': 0.0, 'durum': 'BAŞLANMADI', 'renk': 'gri',
        })
    return rows_out


def _y_emir_detay(y_list, emir_meta, con_by_emir, wait_by_emir, giren_map, cur):
    out = []
    for yen in sorted(y_list or [], reverse=True):
        meta = emir_meta.get(yen)
        if not meta:
            continue
        if isinstance(meta, dict) and 'model_kod' in meta:
            mk, ma = meta['model_kod'], meta.get('model_adi', '')
        else:
            mk, ma = meta, meta
        kat = _kategori(mk, ma)
        kat_label = {'SAYA': 'Saya', 'ATKI': 'Atkı', 'GOVDE': 'Gövde'}.get(kat, kat)
        rows = con_by_emir.get(yen, []) + wait_by_emir.get(yen, [])
        if not rows:
            cur.execute("""
                SELECT fn.Proses, pm.Tanim
                FROM Urt_Emir e
                CROSS APPLY (SELECT dbo.kg_fn_GetProses(e.EmirNo, '', 'f') AS Proses) fn
                LEFT JOIN Proses_M pm ON pm.Pro = fn.Proses
                WHERE e.EmirNo = %s
            """, (yen,))
            fb = cur.fetchone()
            proses_adi = fb[1] if fb else '-'
            proses_kod = str(fb[0]).strip() if fb and fb[0] else ''
        else:
            r0 = rows[0]
            proses_kod = str(r0.get('Proses', '')).strip()
            proses_adi = proses_kod
        v = giren_map.get(yen, 0)
        b = sum(int(r.get('biten') or 0) for r in rows)
        d = sum(int(r.get('devam_eden') or 0) for r in rows)
        durum, renk = _durum_from_miktar(v, b, d)
        out.append({
            'emir_no': yen, 'kategori': kat_label, 'stok_kod': mk,
            'miktar': v, 'proses': proses_adi, 'proses_kod': proses_kod,
            'alt_proses': '-', 'verilen': v, 'devam': d, 'biten': b,
            'yuzde': _yuzde(b, v), 'durum': durum, 'renk': renk,
        })
    return out


def stok_gorsel_yolu(con, skod):
    cur = con.cursor()
    cur.execute("SELECT TOP 1 LTRIM(RTRIM(ISNULL(SResim, ''))) FROM StokKart WHERE SKod = %s", (skod,))
    row = cur.fetchone()
    cur.close()
    return (row[0] or '').strip() if row else ''
