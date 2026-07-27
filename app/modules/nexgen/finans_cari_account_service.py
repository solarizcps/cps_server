# -*- coding: utf-8 -*-
"""Cari hesap read modeli — FAZ-FINANS-F2 (CariAccountService)."""
from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal
from typing import Any

from modules.nexgen.finans_belgesi_repository import tablo_var
from modules.nexgen.finans_cari_identity_resolver import (
    CariIdentityResolution,
    resolve_by_operasyonel,
)
from modules.nexgen.finans_cari_read_service import cari_hareket_liste
from modules.nexgen.finans_core_config import (
    OI_DURUM_ACIK,
    OI_DURUM_KISMI_KAPALI,
)
from modules.nexgen.finans_core_schema import decimal_para
from modules.nexgen.finans_ledger_standard import (
    bakiye_durumu_etiket,
    bakiye_durumu_kod,
    compute_bakiye,
    hareket_kaynak_say,
    hareket_kaynak_sinifi,
    load_hareket_metadata_maps,
)


def _today_iso() -> str:
    return date.today().isoformat()


def _float(v: Any) -> float:
    if v in (None, ''):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def open_item_ozet(con: sqlite3.Connection, ckod: str | None) -> dict[str, Any]:
    empty = {
        'mevcut': False,
        'acik_sayisi': 0,
        'kismi_kapali_sayisi': 0,
        'vadesi_gecmis_sayisi': 0,
        'acik_toplam': 0.0,
        'vadesi_gecmis_toplam': 0.0,
        'kalemler': [],
    }
    if not ckod or not tablo_var(con, 'finans_open_item'):
        return empty

    today = _today_iso()
    acik_durumlar = (OI_DURUM_ACIK, OI_DURUM_KISMI_KAPALI)
    rows = con.execute(
        """
        SELECT id, yon, acik_tutar, vade_tarihi, durum, para_birimi, finans_belgesi_id
        FROM finans_open_item
        WHERE ckod=? AND durum IN (?, ?)
        ORDER BY vade_tarihi ASC, id ASC
        """,
        (ckod, OI_DURUM_ACIK, OI_DURUM_KISMI_KAPALI),
    ).fetchall()
    if not rows:
        return empty

    acik_sayisi = kismi = vadesi_gecmis = 0
    acik_toplam = Decimal('0')
    vadesi_gecmis_toplam = Decimal('0')
    kalemler: list[dict[str, Any]] = []

    for r in rows:
        tutar = decimal_para(r['acik_tutar'])
        acik_toplam += tutar
        if r['durum'] == OI_DURUM_ACIK:
            acik_sayisi += 1
        else:
            kismi += 1
        vade = (r['vade_tarihi'] or '')[:10]
        gecmis = bool(vade and vade < today)
        if gecmis:
            vadesi_gecmis += 1
            vadesi_gecmis_toplam += tutar
        kalemler.append({
            'id': int(r['id']),
            'yon': r['yon'],
            'acik_tutar': float(tutar),
            'vade_tarihi': r['vade_tarihi'],
            'durum': r['durum'],
            'para_birimi': r['para_birimi'],
            'finans_belgesi_id': r['finans_belgesi_id'],
            'vadesi_gecmis': gecmis,
        })

    return {
        'mevcut': True,
        'acik_sayisi': acik_sayisi,
        'kismi_kapali_sayisi': kismi,
        'vadesi_gecmis_sayisi': vadesi_gecmis,
        'acik_toplam': float(acik_toplam),
        'vadesi_gecmis_toplam': float(vadesi_gecmis_toplam),
        'kalemler': kalemler,
    }


def son_hareketler(
    con: sqlite3.Connection,
    ckod: str | None,
    *,
    limit: int = 10,
    yalniz_nexgen: bool = True,
) -> list[dict[str, Any]]:
    if not ckod:
        return []
    ham = cari_hareket_liste(con, ckod, limit=limit * 3 if yalniz_nexgen else limit)
    if yalniz_nexgen:
        ham = [h for h in ham if not h.get('legacy_kaynak')]
    return ham[:limit]


def hareket_dokumu(
    con: sqlite3.Connection,
    ckod: str,
    *,
    kaynak: str = 'NEXGEN',
    limit: int = 100,
    offset: int = 0,
    tarih_bas: str | None = None,
    tarih_bit: str | None = None,
    islem_turu: str | None = None,
    belge_no: str | None = None,
) -> dict[str, Any]:
    if not tablo_var(con, 'Cari_Har'):
        return {
            'toplam': 0, 'limit': limit, 'offset': offset,
            'bakiye_hesaplanabilir': False,
            'hareketler': [], 'legacy_sayisi': 0, 'nexgen_sayisi': 0,
            'kaynak_filtre': kaynak,
        }

    kaynak_norm = (kaynak or 'NEXGEN').strip().upper()
    if kaynak_norm not in ('NEXGEN', 'LEGACY', 'TUMU'):
        kaynak_norm = 'NEXGEN'

    rows = con.execute(
        """
        SELECT Id, Tarih, BelgeNo, BelgeTip, Aciklama, Borc, Alacak, kaynak_sistem
        FROM Cari_Har WHERE CKod=?
        ORDER BY Tarih ASC, Id ASC
        """,
        (ckod,),
    ).fetchall()
    ids = [int(r['Id']) for r in rows]
    fb_map, fh_map = load_hareket_metadata_maps(con, ids)

    seen: set[int] = set()
    bakiye = 0.0
    enriched: list[dict[str, Any]] = []
    legacy_count = nexgen_count = 0

    for r in rows:
        har_id = int(r['Id'])
        if har_id in seen:
            continue
        seen.add(har_id)

        sinif = hareket_kaynak_sinifi(
            finans_belgesi_var=har_id in fb_map,
            finans_hareket=fh_map.get(har_id),
            belge_tip=r['BelgeTip'],
        )
        ks_row = (r['kaynak_sistem'] or '').strip().upper()
        if ks_row in ('DEMO', 'MANUEL', 'MANUAL'):
            sinif = 'MANUAL'
        if sinif in ('NEXGEN', 'REVERSAL', 'MANUAL'):
            nexgen_count += 1
        else:
            legacy_count += 1

        tarih = (r['Tarih'] or '')[:10]
        if tarih_bas and tarih < tarih_bas:
            continue
        if tarih_bit and tarih > tarih_bit:
            continue
        if belge_no and belge_no.strip().casefold() not in (r['BelgeNo'] or '').casefold():
            continue
        if islem_turu and islem_turu.strip().casefold() not in (r['BelgeTip'] or '').casefold():
            continue

        if kaynak_norm == 'NEXGEN' and sinif == 'LEGACY':
            continue
        if kaynak_norm == 'LEGACY' and sinif != 'LEGACY':
            continue

        borc = round(_float(r['Borc']), 2)
        alacak = round(_float(r['Alacak']), 2)
        bakiye = round(bakiye + borc - alacak, 2)
        fb = fb_map.get(har_id)
        enriched.append({
            'id': har_id,
            'tarih': r['Tarih'],
            'belge_no': r['BelgeNo'],
            'islem_turu': r['BelgeTip'],
            'aciklama': r['Aciklama'],
            'kaynak': 'Finans Belgesi' if sinif != 'LEGACY' else 'Önceki Dönem',
            'kaynak_kodu': sinif,
            'legacy_kaynak': sinif == 'LEGACY',
            'onceki_donem': sinif == 'LEGACY',
            'reversal': sinif == 'REVERSAL',
            'borc': borc,
            'alacak': alacak,
            'bakiye': bakiye,
            'finans_belge_id': fb['id'] if fb else None,
            'finans_belge_kodu': fb['belge_kodu'] if fb else None,
        })

    total = len(enriched)
    page = enriched[offset:offset + limit]
    return {
        'toplam': total,
        'limit': limit,
        'offset': offset,
        'bakiye_hesaplanabilir': True,
        'hareketler': page,
        'legacy_sayisi': legacy_count,
        'nexgen_sayisi': nexgen_count,
        'kaynak_filtre': kaynak_norm,
    }


def read_account_model(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
) -> dict[str, Any]:
    """Finans kart merkezli cari hesap read modeli."""
    resolution: CariIdentityResolution = resolve_by_operasyonel(
        con, cari_tipi, int(operasyonel_id),
    )
    ckod = resolution.finance_card_code
    finans_kart = resolution.finans_kart

    bak_raw = compute_bakiye(con, ckod) if ckod else compute_bakiye(con, None)
    bakiye = float(bak_raw['bakiye']) if bak_raw.get('mevcut') or ckod else None
    bd = bakiye_durumu_kod(bak_raw['bakiye']) if ckod and bak_raw.get('mevcut') else None

    hsay = hareket_kaynak_say(con, ckod)
    oi = open_item_ozet(con, ckod if finans_kart else None)

    para_birimi = 'TRY'
    if finans_kart:
        para_birimi = finans_kart.get('para_birimi') or 'TRY'
    elif resolution.legacy_cari_kart:
        para_birimi = 'TRY'

    return {
        'cari_tipi': cari_tipi,
        'operasyonel_id': int(operasyonel_id),
        'finans_kart': finans_kart,
        'kimlik_cozumleme': resolution.to_dict(),
        'cari_kart_ckod': ckod,
        'kart_baglanti_eksik': resolution.requires_manual_link,
        'para_birimi': para_birimi,
        'toplam_borc': float(bak_raw['toplam_borc']) if bak_raw.get('mevcut') else None,
        'toplam_alacak': float(bak_raw['toplam_alacak']) if bak_raw.get('mevcut') else None,
        'bakiye': bakiye,
        'bakiye_durumu': bd,
        'bakiye_durumu_etiket': bakiye_durumu_etiket(bd) if bd else None,
        'bakiye_mevcut': bool(bak_raw.get('mevcut')),
        'hareket_sayisi': hsay,
        'nexgen_hareket_sayisi': hsay.get('nexgen', 0),
        'legacy_hareket_sayisi': hsay.get('legacy', 0),
        'reversal_hareket_sayisi': hsay.get('reversal', 0),
        'open_item': oi,
        'operasyonel_baglantilar': resolution.operasyonel_baglantilar,
        'is_legacy_fallback': resolution.is_legacy_fallback,
        'son_hareketler': son_hareketler(con, ckod, limit=10),
    }
