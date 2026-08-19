# -*- coding: utf-8 -*-
"""Planlama — Enjeksiyon canli tahmin motoru (READ-ONLY ENJ verisi).

original_plan_bitis immutable kalir; yalniz guncel_tahmini_bitis guncellenir.
Plan↔setup otomatik binding YOK — pilot_scope explicit olmali.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from modules.planlama.enj_kapasite_motor import (
    HAFTA_SONU_KURAL,
    _format_tahmini_gosterim,
    _lookup_reference,
    _parse_dt,
    _ui_precision,
    _worst_confidence,
    hesapla_kapasite,
    simule_takvim,
)
from modules.planlama.enj_kapasite_read_service import _speed_references


def _format_sapma(sapma_dakika: int) -> dict:
    if sapma_dakika < 0:
        durum = 'ERKEN'
        m = abs(sapma_dakika)
        saat, dk = divmod(m, 60)
        if saat:
            gosterim = f'{saat} sa {dk} dk erken'
        else:
            gosterim = f'{dk} dk erken'
    elif sapma_dakika > 0:
        durum = 'GECIKIYOR'
        saat, dk = divmod(sapma_dakika, 60)
        if saat:
            gosterim = f'{saat} sa {dk} dk gecikme'
        else:
            gosterim = f'{dk} dk gecikme'
    else:
        durum = 'PLANLA UYUMLU'
        gosterim = 'Planla uyumlu'
    return {
        'sapma_dakika': sapma_dakika,
        'sapma_durum': durum,
        'sapma_gosterim': gosterim,
    }


def _load_plan_snapshot(con: sqlite3.Connection, payload: dict) -> dict:
    """Plan snapshot — DB'den READ veya payload'dan; UPDATE yok."""
    snap = dict(payload.get('plan_snapshot') or {})
    plan_id = payload.get('plan_id')
    if plan_id and not snap.get('plan_baslangic'):
        row = con.execute(
            """
            SELECT id, enj_makine_id, enj_slot, enj_aktif_goz, enj_kalip_basi_cift,
                   enj_tur_cift, enj_plan_baslangic, enj_plan_bitis, enj_planlanacak_cift
            FROM uretim_model_plan
            WHERE id = ? AND aktif = 1
            """,
            (int(plan_id),),
        ).fetchone()
        if row:
            snap.setdefault('plan_id', row['id'])
            snap.setdefault('makine_id', row['enj_makine_id'])
            snap.setdefault('taraf', row['enj_slot'])
            snap.setdefault('kalip_adedi', row['enj_aktif_goz'])
            snap.setdefault('kalip_basi_cift', row['enj_kalip_basi_cift'])
            snap.setdefault('tur_basi_cift', row['enj_tur_cift'])
            snap.setdefault('plan_baslangic', row['enj_plan_baslangic'])
            snap.setdefault('original_plan_bitis', row['enj_plan_bitis'])
            snap.setdefault('planlanan_toplam_cift', row['enj_planlanacak_cift'])
    return snap


def _read_pilot_gercek(
    con: sqlite3.Connection,
    pilot_scope: dict,
    slot: str,
    tur_basi_cift: int,
) -> dict | None:
    """Explicit pilot scope ile READ-ONLY gercek uretim."""
    slot = slot.upper()
    cevrim = 'cevrim_a' if slot == 'A' else 'cevrim_b'
    uretilen = 'uretilen_a' if slot == 'A' else 'uretilen_b'
    durum = 'durum_a' if slot == 'A' else 'durum_b'
    aksama = 'aksama_sebep_a_id' if slot == 'A' else 'aksama_sebep_b_id'
    setup_col = 'setup_id_a' if slot == 'A' else 'setup_id_b'

    if pilot_scope.get('explicit_gercek') is not None:
        eg = pilot_scope['explicit_gercek']
        gt = float(eg.get('gercek_tur') or eg.get('tur') or 0)
        gc = eg.get('gerceklesen_cift')
        if gc is None:
            gc = int(round(gt * tur_basi_cift))
        return {
            'kaynak': 'explicit_pilot',
            'gercek_tur': gt,
            'gerceklesen_net_cift': int(gc),
            'gerceklesen_net_cift_raw': int(gc),
            'tamamlanan_vardiyalar': eg.get('tamamlanan_vardiyalar') or [],
            'problemli_saat': int(eg.get('problemli_saat') or 0),
            'aksama_sebepleri': list(eg.get('aksama_sebepleri') or []),
            'binding': 'explicit',
        }

    rapor_id = pilot_scope.get('rapor_id')
    setup_id = pilot_scope.get('setup_id')
    makine_kod = pilot_scope.get('makine_kod')
    makine_id = pilot_scope.get('makine_id')
    tarih = pilot_scope.get('tarih')
    vardiya = pilot_scope.get('vardiya')

    if not rapor_id:
        if makine_kod:
            mk = con.execute(
                'SELECT id FROM enj_makine WHERE kod=? AND aktif=1', (makine_kod,),
            ).fetchone()
            makine_id = mk['id'] if mk else None
        if makine_id and tarih and vardiya:
            rr = con.execute(
                """
                SELECT id FROM enj_gunluk_rapor
                WHERE makine_id=? AND tarih=? AND vardiya=?
                """,
                (int(makine_id), tarih, vardiya),
            ).fetchone()
            rapor_id = rr['id'] if rr else None

    if not rapor_id:
        return None

    setup_filter = ''
    params: list[Any] = [rapor_id]
    if setup_id:
        setup_filter = ' AND s.id = ?'
        params.append(int(setup_id))
    else:
        setup_filter = " AND s.slot = ? AND s.durum IN ('AKTIF','KAPANDI')"
        params.append(slot)

    row = con.execute(
        f"""
        SELECT s.id AS setup_id, s.slot, s.aktif_goz_sayisi, s.kalip_basi_cift,
               SUM(COALESCE(h.{cevrim}, 0)) AS gercek_tur,
               SUM(COALESCE(h.{uretilen}, 0)) AS uretilen_cift,
               SUM(CASE WHEN h.{durum} IN ('AKSAMA','PROBLEM','DURUS') THEN 1 ELSE 0 END) AS problemli_saat
        FROM enj_ab_setup s
        JOIN enj_gunluk_rapor r ON r.id = s.rapor_id
        JOIN enj_saatlik_kayit h ON h.rapor_id = r.id
        WHERE r.id = ? {setup_filter}
        GROUP BY s.id
        ORDER BY s.baslangic_zamani DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    if not row or int(row['gercek_tur'] or 0) <= 0:
        return None

    gt = float(row['gercek_tur'])
    gc = int(row['uretilen_cift'] or 0)
    if gc <= 0:
        kbc = int(row['kalip_basi_cift'] or 0)
        ag = int(row['aktif_goz_sayisi'] or 0)
        tb = ag * kbc if ag and kbc else tur_basi_cift
        gc = int(round(gt * tb))

    aksama_rows = con.execute(
        f"""
        SELECT DISTINCT COALESCE(a.kod, a.ad, CAST(h.{aksama} AS TEXT)) AS sebep
        FROM enj_saatlik_kayit h
        LEFT JOIN enj_aksama_sebep a ON a.id = h.{aksama}
        WHERE h.rapor_id = ? AND h.{aksama} IS NOT NULL
        """,
        (rapor_id,),
    ).fetchall()
    sebepler = [r['sebep'] for r in aksama_rows if r['sebep']]

    return {
        'kaynak': 'enj_read',
        'rapor_id': rapor_id,
        'setup_id': row['setup_id'],
        'gercek_tur': gt,
        'gerceklesen_net_cift': gc,
        'gerceklesen_net_cift_raw': gc,
        'tamamlanan_vardiyalar': [{
            'tarih': tarih,
            'vardiya': vardiya,
            'tur': gt,
        }],
        'problemli_saat': int(row['problemli_saat'] or 0),
        'aksama_sebepleri': sebepler,
        'binding': 'explicit_pilot_scope',
    }


def _actual_reference_tur(
    plan_ref: float,
    gercek_data: dict,
    pilot_scope: dict,
) -> tuple[float, str, int]:
    """Tamamlanmis gercek vardiya performansina gore guncel hiz."""
    override = pilot_scope.get('actual_reference_tur')
    if override is not None:
        return float(override), 'explicit_override', 1

    vards = gercek_data.get('tamamlanan_vardiyalar') or []
    tur_vals = [float(v['tur']) for v in vards if v.get('tur')]
    if tur_vals:
        if len(tur_vals) >= 2:
            return float(median(tur_vals)), 'median_tamamlanan_vardiya', len(tur_vals)
        return tur_vals[0], 'son_tamamlanan_vardiya', 1

    gt = float(gercek_data.get('gercek_tur') or 0)
    if gt > 0:
        return gt, 'gercek_toplam_tur', 1
    return plan_ref, 'plan_reference', 0


def hesapla_canli_tahmin(
    con: sqlite3.Connection,
    payload: dict,
    ref_days: int = 90,
) -> dict:
    snap = _load_plan_snapshot(con, payload)
    pilot_scope = dict(payload.get('pilot_scope') or {})

    makine_kod = payload.get('makine_kod') or snap.get('makine_kod')
    makine_id = payload.get('makine_id') or snap.get('makine_id')
    taraf = (payload.get('slot') or payload.get('taraf') or snap.get('taraf') or '').upper()
    if taraf not in ('A', 'B'):
        return {'ok': False, 'hata': 'slot/taraf A veya B zorunlu'}

    if makine_id:
        mk = con.execute(
            'SELECT id, kod FROM enj_makine WHERE id=? AND aktif=1', (int(makine_id),),
        ).fetchone()
    elif makine_kod:
        mk = con.execute(
            'SELECT id, kod FROM enj_makine WHERE kod=? AND aktif=1', (makine_kod,),
        ).fetchone()
    else:
        return {'ok': False, 'hata': 'makine_kod veya makine_id zorunlu'}
    if not mk:
        return {'ok': False, 'hata': 'Makine bulunamadi'}
    makine_id = int(mk['id'])
    makine_kod = mk['kod']

    kalip_adedi = int(snap.get('kalip_adedi') or payload.get('kalip_adedi') or 0)
    kbc = int(snap.get('kalip_basi_cift') or payload.get('kalip_basi_cift') or 2)
    goz_per_kalip = max(1, int(snap.get('goz_per_kalip') or payload.get('goz_per_kalip') or 1))
    aktif_goz_toplam = int(
        snap.get('aktif_goz_sayisi') or payload.get('aktif_goz_sayisi') or payload.get('aktif_goz') or 0
    )
    if aktif_goz_toplam <= 0:
        aktif_goz_toplam = kalip_adedi * goz_per_kalip
    tur_basi = int(snap.get('tur_basi_cift') or payload.get('tur_basi_cift') or kalip_adedi * kbc)
    if kalip_adedi <= 0:
        kalip_adedi = len(payload.get('istasyonlar') or [1, 2, 3, 4])

    planlanan_cift = float(
        snap.get('planlanan_toplam_cift')
        or payload.get('planlanan_toplam_cift')
        or payload.get('uretilecek_cift')
        or 0,
    )
    plan_tur_ref = float(
        snap.get('plan_tur_referansi')
        or payload.get('plan_tur_referansi')
        or payload.get('plan_reference_tur')
        or 60,
    )
    plan_tur_toplam = float(
        snap.get('plan_tur_toplam')
        or payload.get('plan_tur_toplam')
        or math.ceil(planlanan_cift / tur_basi) if tur_basi else 0,
    )

    calisma_modu = (snap.get('plan_calisma_modu') or payload.get('calisma_modu') or 'GUNDUZ_GECE').upper()
    hafta_sonu = (snap.get('plan_hafta_sonu_kurali') or payload.get('hafta_sonu_calisma') or 'HAYIR').upper()
    hs_vardiya = payload.get('hafta_sonu_vardiya')
    if hs_vardiya:
        hs_vardiya = hs_vardiya.upper()

    try:
        plan_bas = _parse_dt(snap.get('plan_baslangic') or payload.get('plan_baslangic'))
    except ValueError as e:
        return {'ok': False, 'hata': str(e)}

    original_bitis_raw = snap.get('original_plan_bitis') or payload.get('original_plan_bitis')
    if not original_bitis_raw:
        orig_calc = hesapla_kapasite(con, {
            'makine_kod': makine_kod,
            'taraf': taraf,
            'istasyonlar': payload.get('istasyonlar') or list(range(1, kalip_adedi + 1)),
            'kalip_adedi': kalip_adedi,
            'kalip_basi_cift': kbc,
            'uretilecek_cift': planlanan_cift,
            'plan_baslangic': plan_bas.strftime('%Y-%m-%d %H:%M:%S'),
            'calisma_modu': calisma_modu,
            'hafta_sonu_calisma': hafta_sonu,
            'hafta_sonu_vardiya': hs_vardiya,
        }, ref_days=ref_days)
        if not orig_calc.get('ok'):
            return {'ok': False, 'hata': 'original_plan_bitis hesaplanamadi', 'detay': orig_calc}
        original_bitis_raw = orig_calc['tahmini_bitis']

    try:
        original_plan_bitis = _parse_dt(original_bitis_raw)
    except ValueError:
        return {'ok': False, 'hata': 'Gecersiz original_plan_bitis'}

    simdi_raw = payload.get('simdi') or pilot_scope.get('simdi')
    try:
        simdi = _parse_dt(simdi_raw) if simdi_raw else datetime.now().replace(second=0, microsecond=0)
    except ValueError:
        simdi = datetime.now().replace(second=0, microsecond=0)

    gercek = _read_pilot_gercek(con, pilot_scope, taraf, tur_basi)
    if gercek is None and not pilot_scope.get('allow_empty_gercek'):
        return {
            'ok': False,
            'hata': 'Gercek uretim okunamadi — explicit pilot_scope veya explicit_gercek gerekli',
            'binding_gerekli': True,
        }

    if gercek is None:
        gercek = {
            'gercek_tur': 0.0,
            'gerceklesen_net_cift': 0,
            'gerceklesen_net_cift_raw': 0,
            'tamamlanan_vardiyalar': [],
            'problemli_saat': 0,
            'aksama_sebepleri': [],
            'kaynak': 'empty',
        }

    gercek_tur = float(gercek.get('gercek_tur') or 0)
    gercek_cift = int(gercek.get('gerceklesen_net_cift') or 0)
    gercek_cift_raw = int(gercek.get('gerceklesen_net_cift_raw') or gercek_cift)
    kalan_cift_raw = planlanan_cift - gercek_cift_raw
    kalan_cift = max(0, kalan_cift_raw)
    kalan_tur = max(0.0, plan_tur_toplam - gercek_tur)

    actual_ref, ref_type, ref_n = _actual_reference_tur(plan_tur_ref, gercek, pilot_scope)
    live_confidence = 'DUSUK' if ref_n < 2 else ('ORTA' if ref_n < 4 else 'YUKSEK')

    refs_all = _speed_references(con, makine_id, makine_kod, ref_days=ref_days)
    refs_slot = [r for r in refs_all if r.get('slot') == taraf]
    ref_gunduz = _lookup_reference(refs_slot, taraf, 'gunduz', aktif_goz_toplam)
    ref_gece = _lookup_reference(refs_slot, taraf, 'gece', aktif_goz_toplam)

    ref_override = {'gunduz': actual_ref, 'gece': actual_ref}

    warnings: list[dict] = []
    sapma_nedenleri: list[str] = []

    if gercek.get('aksama_sebepleri'):
        for s in gercek['aksama_sebepleri']:
            sapma_nedenleri.append(str(s))
    if int(gercek.get('problemli_saat') or 0) > 0:
        sapma_nedenleri.append(f"{gercek['problemli_saat']} problemli saat")

    if ref_n < 2:
        warnings.append({
            'kod': 'DUSUK_CANLI_CONFIDENCE',
            'seviye': 'UYARI',
            'mesaj': f'Canli hiz referansi dusuk guven (n={ref_n}, tip={ref_type})',
        })

    gercek_bitis = None
    if kalan_cift <= 0 and gercek.get('binding') == 'explicit_pilot_scope' and pilot_scope.get('rapor_id'):
        warnings.append({
            'kod': 'BINDING_GEREKLI',
            'seviye': 'BILGI',
            'mesaj': 'Canonical plan-setup binding yok — gercek_bitis null',
        })
    elif kalan_cift <= 0 and gercek.get('kaynak') == 'explicit_pilot':
        if pilot_scope.get('explicit_gercek', {}).get('is_tamamlandi'):
            gercek_bitis = pilot_scope['explicit_gercek'].get('gercek_bitis') or simdi.strftime('%Y-%m-%d %H:%M:%S')

    calendar_breakdown: list[dict] = []
    guncel_tahmini_bitis = original_plan_bitis

    if kalan_tur > 0 or kalan_cift > 0:
        rem_tur = kalan_tur if kalan_tur > 0 else math.ceil(kalan_cift / tur_basi)
        sim = simule_takvim(
            simdi, float(rem_tur),
            calisma_modu=calisma_modu,
            hafta_sonu=hafta_sonu,
            hs_vardiya=hs_vardiya,
            ref_gunduz=ref_gunduz,
            ref_gece=ref_gece,
            tur_basi_cift=tur_basi,
            ref_override=ref_override,
        )
        if not sim.get('ok'):
            return {'ok': False, 'hata': sim.get('hata'), 'detay': sim}
        guncel_tahmini_bitis = sim['tahmini_bitis']
        calendar_breakdown = [{
            'asama': 'KALAN_TAHMIN',
            **b,
        } for b in sim.get('vardiya_breakdown', [])]
    else:
        guncel_tahmini_bitis = simdi
        calendar_breakdown = [{'asama': 'TAMAMLANDI', 'not': 'Kalan uretim yok'}]

    sapma = _format_sapma(int((guncel_tahmini_bitis - original_plan_bitis).total_seconds() / 60))
    overall = _worst_confidence(live_confidence, ref_gunduz.get('confidence', 'YETERSIZ'))

    return {
        'ok': True,
        'original_plan_bitis': original_plan_bitis.strftime('%Y-%m-%d %H:%M:%S'),
        'guncel_tahmini_bitis': guncel_tahmini_bitis.strftime('%Y-%m-%d %H:%M:%S'),
        'gercek_bitis': gercek_bitis,
        'planlanan_cift': int(planlanan_cift) if planlanan_cift == int(planlanan_cift) else planlanan_cift,
        'gerceklesen_cift': gercek_cift,
        'gerceklesen_cift_raw': gercek_cift_raw,
        'kalan_cift': kalan_cift,
        'kalan_cift_raw': kalan_cift_raw,
        'plan_tur': plan_tur_toplam,
        'plan_reference_tur': plan_tur_ref,
        'gercek_tur': gercek_tur,
        'actual_reference_tur': actual_ref,
        'actual_reference_type': ref_type,
        'actual_reference_sample_count': ref_n,
        'plan_baslangic': plan_bas.strftime('%Y-%m-%d %H:%M:%S'),
        'simdi': simdi.strftime('%Y-%m-%d %H:%M:%S'),
        'makine_kod': makine_kod,
        'slot': taraf,
        'tur_basi_cift': tur_basi,
        'confidence': overall,
        'live_confidence': live_confidence,
        'tahmini_bitis_precision': _ui_precision(overall),
        'guncel_tahmini_gosterim': _format_tahmini_gosterim(
            guncel_tahmini_bitis, overall, calendar_breakdown,
        ),
        'warnings': warnings,
        'sapma_nedenleri': sapma_nedenleri,
        'calendar_breakdown': calendar_breakdown,
        'hafta_sonu_kural': HAFTA_SONU_KURAL,
        'pilot_kaynak': gercek.get('kaynak'),
        'pilot_binding': gercek.get('binding'),
        'plan_immutable': True,
        'plan_bitis_degistirildi': False,
        **sapma,
    }
