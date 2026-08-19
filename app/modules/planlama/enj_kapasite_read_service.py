# -*- coding: utf-8 -*-
"""Planlama — Enjeksiyon kapasite READ-ONLY servisi.

Ferhat /enjeksiyon modülüne DOKUNMAZ. Yalnızca SELECT.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from statistics import median
from typing import Any

_SLOTS = ('A', 'B')
_VARDIYALAR = ('gunduz', 'gece', 'mesai')

# Canonical vardiya süreleri (enjeksiyon routes.SAATLER ile uyumlu)
VARDIYA_CANONICAL_SAAT = {'gunduz': 10, 'gece': 14}
# PRIMARY referans: aktif üretim saati eşiği (gündüz ≥8h, gece ~%80)
PRIMARY_MIN_ACTIVE_SAAT = {'gunduz': 8, 'gece': 11}
# Median'a dahil minimum: anlamlı kısmi vardiya (3h gibi gürültü hariç)
ELIGIBLE_MIN_ACTIVE_SAAT = {'gunduz': 6, 'gece': 8}


def vardiya_otomatik(now: datetime | None = None) -> str:
    h = (now or datetime.now()).hour
    return 'gunduz' if 7 <= h < 17 else 'gece'


def _row_dict(row) -> dict | None:
    if row is None:
        return None
    return dict(row)


def _slot_label(aktif: int | None) -> str:
    return 'DOLU' if int(aktif or 0) else 'BOS'


def _resolve_rapor(
    con: sqlite3.Connection,
    makine_id: int,
    tarih: str | None = None,
    vardiya: str | None = None,
) -> dict | None:
    """Makine için snapshot raporu bul (CREATE yok)."""
    if tarih and vardiya:
        row = con.execute(
            """
            SELECT id, tarih, vardiya, makine_id
            FROM enj_gunluk_rapor
            WHERE makine_id = ? AND tarih = ? AND vardiya = ?
            """,
            (makine_id, tarih, vardiya),
        ).fetchone()
        if row:
            return _row_dict(row)

    if tarih and not vardiya:
        row = con.execute(
            """
            SELECT id, tarih, vardiya, makine_id
            FROM enj_gunluk_rapor
            WHERE makine_id = ? AND tarih = ?
            ORDER BY CASE vardiya WHEN 'gunduz' THEN 1 WHEN 'gece' THEN 2 ELSE 3 END
            LIMIT 1
            """,
            (makine_id, tarih),
        ).fetchone()
        if row:
            return _row_dict(row)

    bugun = (tarih or datetime.now().strftime('%Y-%m-%d'))
    vd = vardiya or vardiya_otomatik()
    row = con.execute(
        """
        SELECT id, tarih, vardiya, makine_id
        FROM enj_gunluk_rapor
        WHERE makine_id = ? AND tarih = ? AND vardiya = ?
        """,
        (makine_id, bugun, vd),
    ).fetchone()
    if row:
        return _row_dict(row)

    row = con.execute(
        """
        SELECT id, tarih, vardiya, makine_id
        FROM enj_gunluk_rapor
        WHERE makine_id = ?
        ORDER BY tarih DESC,
                 CASE vardiya WHEN 'gece' THEN 2 WHEN 'gunduz' THEN 1 ELSE 3 END DESC
        LIMIT 1
        """,
        (makine_id,),
    ).fetchone()
    return _row_dict(row)


def _kalip_kod(con: sqlite3.Connection, kalip_id: int | None) -> str | None:
    if not kalip_id:
        return None
    row = con.execute(
        'SELECT kalip_kod FROM enj_kalip WHERE id = ?',
        (kalip_id,),
    ).fetchone()
    return row['kalip_kod'] if row else None


def _istasyon_grid(
    con: sqlite3.Connection,
    rapor_id: int | None,
    istasyon_sayisi: int,
) -> list[dict]:
    rows_by_no: dict[int, dict[str, dict]] = {
        n: {'istasyon_no': n, 'A': _empty_cell(), 'B': _empty_cell()}
        for n in range(1, istasyon_sayisi + 1)
    }
    if not rapor_id:
        return [rows_by_no[n] for n in range(1, istasyon_sayisi + 1)]

    rows = con.execute(
        """
        SELECT istasyon_no, slot, aktif, durum, kalip_id, renk, pisme_suresi_sn
        FROM enj_istasyon_durumu
        WHERE rapor_id = ?
        ORDER BY istasyon_no, slot
        """,
        (rapor_id,),
    ).fetchall()

    for r in rows:
        no = int(r['istasyon_no'])
        slot = (r['slot'] or '').upper()
        if no not in rows_by_no or slot not in _SLOTS:
            continue
        kk = _kalip_kod(con, r['kalip_id'])
        rows_by_no[no][slot] = {
            'durum': r['durum'] or ('AKTIF' if r['aktif'] else 'KAPALI'),
            'aktif': int(r['aktif'] or 0),
            'kalip_id': r['kalip_id'],
            'kalip': kk,
            'kalip_kod': kk,
            'renk': r['renk'],
            'pisme_suresi_sn': r['pisme_suresi_sn'],
            'slot_label': _slot_label(r['aktif']),
        }
    return [rows_by_no[n] for n in range(1, istasyon_sayisi + 1)]


def _empty_cell() -> dict:
    return {
        'durum': 'KAPALI',
        'aktif': 0,
        'kalip_id': None,
        'kalip': None,
        'kalip_kod': None,
        'renk': None,
        'pisme_suresi_sn': None,
        'slot_label': 'BOS',
    }


def _slot_counts(grid: list[dict], slot: str, istasyon_sayisi: int) -> dict:
    dolu = sum(1 for g in grid if int(g[slot].get('aktif') or 0))
    bos = max(0, istasyon_sayisi - dolu)
    return {
        'dolu': dolu,
        'bos': bos,
        'used': dolu,
        'free': bos,
        'aktif_adet': dolu,
        'bos_adet': bos,
        'available_now': dolu == 0,
        'has_free_capacity': bos > 0,
        'tahmini_bosalma': None,
    }


def _active_setup(
    con: sqlite3.Connection,
    rapor_id: int | None,
    slot: str,
) -> dict | None:
    if not rapor_id:
        return None
    row = con.execute(
        """
        SELECT id, kalip_id, kalip_kod_snapshot, renk,
               aktif_goz_sayisi, kalip_basi_cift, pisme_suresi_sn,
               baslangic_zamani, personel_sayisi, durum
        FROM enj_ab_setup
        WHERE rapor_id = ? AND slot = ? AND durum = 'AKTIF'
        ORDER BY baslangic_zamani DESC
        LIMIT 1
        """,
        (rapor_id, slot),
    ).fetchone()
    if not row:
        return None
    ag = int(row['aktif_goz_sayisi'] or 0)
    kbc = int(row['kalip_basi_cift'] or 0)
    return {
        'setup_id': row['id'],
        'kalip_id': row['kalip_id'],
        'kalip_kod': row['kalip_kod_snapshot'] or _kalip_kod(con, row['kalip_id']),
        'renk': row['renk'],
        'aktif_goz_sayisi': ag,
        'kalip_basi_cift': kbc,
        'tur_basi_cift': ag * kbc if ag > 0 and kbc > 0 else 0,
        'pisme_suresi_sn': row['pisme_suresi_sn'],
        'setup_baslangic': row['baslangic_zamani'],
        'personel_sayisi': row['personel_sayisi'],
        'durum': row['durum'],
        'tahmini_bosalma': None,
    }


def _hourly_rapor_metrics(
    con: sqlite3.Connection,
    makine_id: int,
    ref_days: int,
) -> dict[int, dict]:
    """Rapor bazlı slot tur + aktif üretim saati (cevrim>0)."""
    days = max(1, min(int(ref_days or 90), 365))
    rows = con.execute(
        """
        SELECT r.id AS rapor_id, r.vardiya, r.tarih,
               SUM(COALESCE(h.cevrim_a, 0)) AS tur_a,
               SUM(CASE WHEN COALESCE(h.cevrim_a, 0) > 0 THEN 1 ELSE 0 END) AS ah_a,
               SUM(COALESCE(h.cevrim_b, 0)) AS tur_b,
               SUM(CASE WHEN COALESCE(h.cevrim_b, 0) > 0 THEN 1 ELSE 0 END) AS ah_b
        FROM enj_gunluk_rapor r
        JOIN enj_saatlik_kayit h ON h.rapor_id = r.id
        WHERE r.makine_id = ?
          AND r.tarih >= date('now', ?)
          AND r.vardiya IN ('gunduz', 'gece')
        GROUP BY r.id
        """,
        (makine_id, f'-{days} day'),
    ).fetchall()
    out: dict[int, dict] = {}
    for r in rows:
        out[int(r['rapor_id'])] = dict(r)
    return out


def _speed_references(
    con: sqlite3.Connection,
    makine_id: int,
    makine_kod: str,
    ref_days: int = 90,
) -> list[dict]:
    """Geçmiş referans — tam vardiya eşdeğeri normalize tur (READ-ONLY)."""
    days = max(1, min(int(ref_days or 90), 365))
    hourly_by_rapor = _hourly_rapor_metrics(con, makine_id, days)

    setup_keys = con.execute(
        """
        SELECT DISTINCT r.id AS rapor_id, r.vardiya, UPPER(s.slot) AS slot,
               s.aktif_goz_sayisi AS ag
        FROM enj_ab_setup s
        JOIN enj_gunluk_rapor r ON r.id = s.rapor_id
        WHERE r.makine_id = ?
          AND r.tarih >= date('now', ?)
          AND s.durum IN ('AKTIF', 'KAPANDI')
          AND COALESCE(s.aktif_goz_sayisi, 0) > 0
          AND r.vardiya IN ('gunduz', 'gece')
        ORDER BY r.id, slot, ag
        """,
        (makine_id, f'-{days} day'),
    ).fetchall()

    seen_dedup: set[tuple[int, str, int]] = set()
    buckets: dict[tuple[str, str, int], list[dict]] = {}

    for sk in setup_keys:
        rapor_id = int(sk['rapor_id'])
        slot = (sk['slot'] or '').upper()
        ag = int(sk['ag'] or 0)
        vd = sk['vardiya'] or ''
        if slot not in _SLOTS or vd not in VARDIYA_CANONICAL_SAAT or ag <= 0:
            continue

        dedup_key = (rapor_id, slot, ag)
        if dedup_key in seen_dedup:
            continue
        seen_dedup.add(dedup_key)

        hr = hourly_by_rapor.get(rapor_id)
        if not hr:
            continue

        shift_tur = int(hr['tur_a'] if slot == 'A' else hr['tur_b'] or 0)
        active_saat = int(hr['ah_a'] if slot == 'A' else hr['ah_b'] or 0)
        if shift_tur <= 0 or active_saat <= 0:
            continue

        eligible_min = ELIGIBLE_MIN_ACTIVE_SAAT[vd]
        if active_saat < eligible_min:
            continue

        canon_h = VARDIYA_CANONICAL_SAAT[vd]
        norm_tur = round(shift_tur / active_saat * canon_h, 2)
        min_primary = PRIMARY_MIN_ACTIVE_SAAT[vd]
        quality = 'PRIMARY' if active_saat >= min_primary else 'LOW'

        bucket_key = (slot, vd, ag)
        buckets.setdefault(bucket_key, []).append({
            'rapor_id': rapor_id,
            'tarih': hr['tarih'],
            'shift_tur': shift_tur,
            'active_saat': active_saat,
            'normalize_tur': norm_tur,
            'quality': quality,
            'tur_saat': round(shift_tur / active_saat, 4),
        })

    out: list[dict] = []
    for (slot, vd, ag), samples in sorted(buckets.items()):
        primary = [s for s in samples if s['quality'] == 'PRIMARY']
        low = [s for s in samples if s['quality'] == 'LOW']
        used = samples
        if primary:
            used_quality = 'PRIMARY' if not low else 'PRIMARY_MIXED'
        else:
            used_quality = 'LOW'

        norm_vals = [s['normalize_tur'] for s in used]
        raw_vals = [s['shift_tur'] for s in used]
        tur_saat_vals = [s['tur_saat'] for s in used]
        med_norm = float(median(norm_vals))
        ref_type = (
            'median_normalize_tur_10h' if vd == 'gunduz'
            else 'median_normalize_tur_14h'
        )

        entry: dict[str, Any] = {
            'makine_kod': makine_kod,
            'slot': slot,
            'vardiya': vd,
            'aktif_goz_sayisi': ag,
            'sample_count': len(used),
            'primary_sample_count': len(primary),
            'low_quality_sample_count': len(low),
            'excluded_low_quality_count': len(low) if primary else 0,
            'used_quality_tier': used_quality,
            'reference_type': ref_type,
            'median_normalize_tur': med_norm,
            'median_tur_vardiya': med_norm,
            'avg_tur_vardiya': round(sum(norm_vals) / len(norm_vals), 2),
            'min_tur': min(norm_vals),
            'max_tur': max(norm_vals),
            'median_raw_tur_vardiya': float(median(raw_vals)),
            'avg_raw_tur_vardiya': round(sum(raw_vals) / len(raw_vals), 2),
            'etiket': 'Gecmis Referans',
            'samples': used,
        }
        if tur_saat_vals:
            entry['avg_tur_saat'] = round(sum(tur_saat_vals) / len(tur_saat_vals), 4)
            entry['median_tur_saat'] = float(median(tur_saat_vals))
        else:
            entry['avg_tur_saat'] = None
            entry['median_tur_saat'] = None
        out.append(entry)
    return out


def _refs_for_slot(references: list[dict], slot: str) -> list[dict]:
    return [r for r in references if r.get('slot') == slot]


def build_kapasite_snapshot(
    con: sqlite3.Connection,
    makine_id: int | None = None,
    tarih: str | None = None,
    vardiya: str | None = None,
    ref_days: int = 90,
) -> dict:
    """Plan Oluştur tek çağrı read-model."""
    if makine_id:
        params_sql = ' AND id = ?'
        args = [makine_id]
    else:
        params_sql = ''
        args = []

    makineler = con.execute(
        f"""
        SELECT id, kod, ad, istasyon_sayisi
        FROM enj_makine
        WHERE aktif = 1 {params_sql}
        ORDER BY sira, kod
        """,
        args,
    ).fetchall()

    snapshot_tarih = tarih or datetime.now().strftime('%Y-%m-%d')
    snapshot_vardiya = vardiya or vardiya_otomatik()
    machines_out: list[dict] = []

    for mk in makineler:
        mid = int(mk['id'])
        ist = int(mk['istasyon_sayisi'])
        rapor = _resolve_rapor(con, mid, tarih=tarih, vardiya=vardiya)
        rapor_id = rapor['id'] if rapor else None
        if rapor:
            snapshot_tarih = rapor['tarih']
            snapshot_vardiya = rapor['vardiya']

        grid = _istasyon_grid(con, rapor_id, ist)
        references = _speed_references(con, mid, mk['kod'], ref_days=ref_days)

        sides: dict[str, dict] = {}
        for slot in _SLOTS:
            counts = _slot_counts(grid, slot, ist)
            setup = _active_setup(con, rapor_id, slot)
            counts['active_setup'] = setup
            counts['references'] = _refs_for_slot(references, slot)
            sides[slot] = counts

        machines_out.append({
            'makine_id': mid,
            'makine_kod': mk['kod'],
            'makine_ad': mk['ad'],
            'code': mk['kod'],
            'istasyon_sayisi': ist,
            'stations': ist,
            'toplam_yuva': ist * 2,
            'rapor_id': rapor_id,
            'snapshot_tarih': rapor['tarih'] if rapor else None,
            'snapshot_vardiya': rapor['vardiya'] if rapor else None,
            'A': sides['A'],
            'B': sides['B'],
            'grid': grid,
            'references': references,
        })

    return {
        'snapshot_tarih': snapshot_tarih,
        'snapshot_vardiya': snapshot_vardiya,
        'ref_days': max(1, min(int(ref_days or 90), 365)),
        'machines': machines_out,
    }


def get_machine_snapshot(
    con: sqlite3.Connection,
    makine_kod: str,
    tarih: str | None = None,
    vardiya: str | None = None,
    ref_days: int = 90,
) -> dict | None:
    row = con.execute(
        'SELECT id FROM enj_makine WHERE kod = ? AND aktif = 1',
        (makine_kod,),
    ).fetchone()
    if not row:
        return None
    payload = build_kapasite_snapshot(
        con, makine_id=int(row['id']), tarih=tarih, vardiya=vardiya, ref_days=ref_days,
    )
    return payload['machines'][0] if payload['machines'] else None
