# -*- coding: utf-8 -*-
"""Cari_Har borç/alacak/bakiye standardı — D1 debit-credit matrisi (read-only)."""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any

from modules.nexgen.finans_belgesi_repository import tablo_var
from modules.nexgen.finans_core_schema import decimal_para

BAKIYE_UYUM_TOLERANSI = Decimal('0.01')


def bakiye_durumu_kod(bakiye: Decimal | float) -> str:
    b = decimal_para(bakiye)
    if b > BAKIYE_UYUM_TOLERANSI:
        return 'BORCLU'
    if b < -BAKIYE_UYUM_TOLERANSI:
        return 'ALACAKLI'
    return 'SIFIR'


def bakiye_durumu_etiket(kod: str) -> str:
    return {'BORCLU': 'Borçlu', 'ALACAKLI': 'Alacaklı', 'SIFIR': 'Sıfır'}.get(kod, kod)


def compute_bakiye(con: sqlite3.Connection, ckod: str | None) -> dict[str, Any]:
    """Tek kaynak: SUM(Borc) - SUM(Alacak) = bakiye (müşteri borçlu = pozitif)."""
    empty = {
        'hareket_sayisi': 0,
        'toplam_borc': Decimal('0'),
        'toplam_alacak': Decimal('0'),
        'bakiye': Decimal('0'),
        'ilk_islem_tarihi': None,
        'son_islem_tarihi': None,
        'cari_har_bakiye': Decimal('0'),
        'cari_kart_bakiye': None,
        'bakiye_farki': None,
        'uyumlu': True,
        'kaynak': 'Cari_Har',
        'mevcut': False,
    }
    if not ckod or not tablo_var(con, 'Cari_Har'):
        return empty

    row = con.execute(
        """
        SELECT
            COUNT(*) AS hareket_sayisi,
            COALESCE(SUM(Borc), 0) AS toplam_borc,
            COALESCE(SUM(Alacak), 0) AS toplam_alacak,
            COALESCE(SUM(Borc - Alacak), 0) AS bakiye,
            MIN(Tarih) AS ilk_islem,
            MAX(Tarih) AS son_islem
        FROM Cari_Har WHERE CKod=?
        """,
        (ckod,),
    ).fetchone()
    d = dict(row) if row else {}
    har_bakiye = decimal_para(d.get('bakiye'))
    kart_bakiye = None
    if tablo_var(con, 'Cari_Kart'):
        kr = con.execute('SELECT Bakiye FROM Cari_Kart WHERE CKod=?', (ckod,)).fetchone()
        if kr:
            kart_bakiye = decimal_para(kr['Bakiye'])

    fark = None
    uyumlu = True
    if kart_bakiye is not None:
        fark = har_bakiye - kart_bakiye
        uyumlu = abs(fark) <= BAKIYE_UYUM_TOLERANSI

    hareket_sayisi = int(d.get('hareket_sayisi') or 0)
    return {
        'hareket_sayisi': hareket_sayisi,
        'toplam_borc': decimal_para(d.get('toplam_borc')),
        'toplam_alacak': decimal_para(d.get('toplam_alacak')),
        'bakiye': har_bakiye,
        'ilk_islem_tarihi': d.get('ilk_islem'),
        'son_islem_tarihi': d.get('son_islem'),
        'cari_har_bakiye': har_bakiye,
        'cari_kart_bakiye': kart_bakiye,
        'bakiye_farki': fark,
        'uyumlu': uyumlu,
        'kaynak': 'Cari_Har',
        'mevcut': hareket_sayisi > 0,
    }


def bakiye_float_dict(paket: dict[str, Any]) -> dict[str, Any]:
    """API uyumu — Decimal → float."""
    out = dict(paket)
    for k in ('toplam_borc', 'toplam_alacak', 'bakiye', 'cari_har_bakiye', 'cari_kart_bakiye', 'bakiye_farki'):
        if out.get(k) is not None and isinstance(out[k], Decimal):
            out[k] = float(out[k])
    if out.get('bakiye') is not None:
        bd = bakiye_durumu_kod(out['bakiye'])
        out['bakiye_durumu'] = bd
        out['bakiye_durumu_etiket'] = bakiye_durumu_etiket(bd)
    return out


def hareket_kaynak_sinifi(
    *,
    finans_belgesi_var: bool,
    finans_hareket: dict[str, Any] | None,
    belge_tip: str | None = None,
) -> str:
    """NEXGEN | LEGACY | REVERSAL | MANUAL"""
    if finans_hareket:
        durum = (finans_hareket.get('durum') or '').upper()
        islem = (finans_hareket.get('islem_tipi') or '').upper()
        if durum == 'TERS' or islem == 'TERS':
            return 'REVERSAL'
        ks = (finans_hareket.get('kaynak_sistem') or 'NEXGEN').upper()
        if ks == 'LEGACY':
            return 'LEGACY'
        ke = (finans_hareket.get('kaynak_entity') or '').upper()
        if ke == 'LEGACY':
            return 'LEGACY'
        if ke == 'MANUEL':
            return 'MANUAL'
        return 'NEXGEN'
    if finans_belgesi_var:
        return 'NEXGEN'
    if (belge_tip or '').upper() == 'TERS':
        return 'REVERSAL'
    return 'LEGACY'


def load_hareket_metadata_maps(
    con: sqlite3.Connection,
    cari_har_ids: list[int],
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    """finans_belgesi + finans_hareket lookup — çift döndürme engeli."""
    fb_map: dict[int, dict[str, Any]] = {}
    fh_map: dict[int, dict[str, Any]] = {}
    if not cari_har_ids:
        return fb_map, fh_map
    ph = ','.join('?' * len(cari_har_ids))
    if tablo_var(con, 'finans_belgesi'):
        for r in con.execute(
            f"""
            SELECT id, belge_kodu, cari_har_id, posting_durumu, belge_tipi
            FROM finans_belgesi
            WHERE cari_har_id IN ({ph}) AND aktif=1
            """,
            cari_har_ids,
        ).fetchall():
            if r['cari_har_id']:
                fb_map[int(r['cari_har_id'])] = dict(r)
    if tablo_var(con, 'finans_hareket'):
        for r in con.execute(
            f"""
            SELECT cari_har_id, kaynak_entity, kaynak_sistem, islem_tipi, durum,
                   finans_belgesi_id, iptal_edildi
            FROM finans_hareket
            WHERE cari_har_id IN ({ph})
            """,
            cari_har_ids,
        ).fetchall():
            fh_map[int(r['cari_har_id'])] = dict(r)
    return fb_map, fh_map


def hareket_kaynak_say(con: sqlite3.Connection, ckod: str | None) -> dict[str, int]:
    if not ckod or not tablo_var(con, 'Cari_Har'):
        return {'toplam': 0, 'nexgen': 0, 'legacy': 0, 'reversal': 0}
    rows = con.execute('SELECT Id, BelgeTip FROM Cari_Har WHERE CKod=?', (ckod,)).fetchall()
    if not rows:
        return {'toplam': 0, 'nexgen': 0, 'legacy': 0, 'reversal': 0}
    ids = [int(r['Id']) for r in rows]
    fb_map, fh_map = load_hareket_metadata_maps(con, ids)
    nexgen = legacy = reversal = 0
    for r in rows:
        hid = int(r['Id'])
        sinif = hareket_kaynak_sinifi(
            finans_belgesi_var=hid in fb_map,
            finans_hareket=fh_map.get(hid),
            belge_tip=r['BelgeTip'],
        )
        if sinif == 'NEXGEN':
            nexgen += 1
        elif sinif == 'REVERSAL':
            reversal += 1
        else:
            legacy += 1
    return {
        'toplam': len(ids),
        'nexgen': nexgen,
        'legacy': legacy,
        'reversal': reversal,
    }


def validate_hareket_tutarlari(borc: Decimal | float, alacak: Decimal | float) -> None:
    """Borç/alacak işaret standardı — aynı anda pozitif veya ikisi sıfır olamaz."""
    b = decimal_para(borc)
    a = decimal_para(alacak)
    if b < 0 or a < 0:
        raise ValueError('Negatif borç veya alacak kullanılamaz.')
    if b > Decimal('0') and a > Decimal('0'):
        raise ValueError('Borç ve alacak aynı anda pozitif olamaz.')
    if b <= Decimal('0') and a <= Decimal('0'):
        raise ValueError('Borç ve alacak ikisi de sıfır olamaz.')
