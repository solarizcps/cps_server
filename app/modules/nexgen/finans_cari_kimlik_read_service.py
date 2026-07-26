# -*- coding: utf-8 -*-
"""Finans cari kimlik — read-only servis (FAZ-F1-2)."""
from __future__ import annotations

import sqlite3
from typing import Any

from modules.nexgen.finans_cari_kimlik_service import (
    FinansCariKimlikError,
    _ckod_cakisma,
    _operasyonel_bilgi,
    _resolve_paket,
    normalize_ctip,
    tablo_var,
    validate_ctip_for_kimlik,
)


def _ensure(con: sqlite3.Connection) -> None:
    if not tablo_var(con, 'finans_cari_kimlik'):
        raise FinansCariKimlikError(
            'finans_cari_kimlik tablosu yok.',
            code='MIGRATION_131',
            http_status=503,
        )


def _liste_satir(con: sqlite3.Connection, kimlik: dict[str, Any]) -> dict[str, Any]:
    paket = _resolve_paket(con, kimlik)
    return {
        'id': paket['id'],
        'kimlik_tipi': paket['kimlik_tipi'],
        'operasyonel_id': paket['operasyonel_id'],
        'kod': paket['operasyonel_kod'],
        'unvan': paket.get('unvan_snapshot') or paket['operasyonel_unvan'],
        'operasyonel_aktif': paket['operasyonel_aktif'],
        'durum': paket['durum'],
        'cari_kart_ckod': paket['cari_kart_ckod'],
        'cari_kart_unvan': paket['cari_kart_unvan'],
        'ctip_raw': paket['ctip_raw'],
        'ctip_uygun': paket['ctip_uygun'],
        'posting_uygun': paket['posting_uygun'],
        'posting_engel_kodu': paket.get('posting_engel_kodu'),
        'updated_at': paket['updated_at'],
        'uyarilar': paket['uyarilar'],
        'aktif': paket['aktif'],
    }


def liste(
    con: sqlite3.Connection,
    *,
    kimlik_tipi: str | None = None,
    durum: str | None = None,
    arama: str | None = None,
    yalniz_eksik: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    _ensure(con)
    q = 'SELECT * FROM finans_cari_kimlik WHERE 1=1'
    params: list[Any] = []
    if kimlik_tipi:
        q += ' AND kimlik_tipi=?'
        params.append(kimlik_tipi)
    if durum:
        q += ' AND durum=?'
        params.append(durum)
    if yalniz_eksik:
        q += " AND (cari_kart_ckod IS NULL OR cari_kart_ckod='')"
    q += ' ORDER BY updated_at DESC, id DESC'
    rows = [dict(r) for r in con.execute(q, params).fetchall()]

    if arama:
        a = arama.strip().casefold()
        filtreli = []
        for r in rows:
            op = _operasyonel_bilgi(con, r)
            metin = ' '.join(filter(None, [
                str(r.get('unvan_snapshot') or ''),
                str(op.get('operasyonel_kod') or ''),
                str(op.get('operasyonel_unvan') or ''),
                str(r.get('cari_kart_ckod') or ''),
            ])).casefold()
            if a in metin:
                filtreli.append(r)
        rows = filtreli

    total = len(rows)
    page = rows[int(offset): int(offset) + int(limit)]
    return {
        'toplam': total,
        'limit': limit,
        'offset': offset,
        'kayitlar': [_liste_satir(con, r) for r in page],
    }


def detay(con: sqlite3.Connection, kimlik_id: int) -> dict[str, Any]:
    _ensure(con)
    row = con.execute(
        'SELECT * FROM finans_cari_kimlik WHERE id=?', (int(kimlik_id),),
    ).fetchone()
    if not row:
        raise FinansCariKimlikError(
            'Kimlik bulunamadi.',
            code='KIMLIK_BULUNAMADI',
            http_status=404,
        )
    return _resolve_paket(con, dict(row))


def kpi(con: sqlite3.Connection) -> dict[str, int]:
    _ensure(con)
    all_rows = [dict(r) for r in con.execute('SELECT * FROM finans_cari_kimlik')]
    out = {
        'toplam': len(all_rows),
        'dogrulanmis': 0,
        'manuel': 0,
        'bekleyen': 0,
        'iptal': 0,
        'cakisma': 0,
        'posting_engelli': 0,
        'musteri': 0,
        'tedarikci': 0,
    }
    for kimlik in all_rows:
        if kimlik['kimlik_tipi'] == 'MUSTERI':
            out['musteri'] += 1
        else:
            out['tedarikci'] += 1
        durum = kimlik.get('durum')
        if durum == 'DOGRULANDI':
            out['dogrulanmis'] += 1
        elif durum == 'MANUEL':
            out['manuel'] += 1
        elif durum == 'BEKLIYOR':
            out['bekleyen'] += 1
        elif durum == 'IPTAL':
            out['iptal'] += 1
        elif durum == 'CAKISMA':
            out['cakisma'] += 1
        paket = _resolve_paket(con, kimlik)
        if not paket.get('posting_uygun'):
            out['posting_engelli'] += 1
    return out


def eslestirme_adaylari(
    con: sqlite3.Connection,
    kimlik_tipi: str,
    operasyonel_id: int,
    *,
    arama: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    _ensure(con)
    if kimlik_tipi not in ('MUSTERI', 'TEDARIKCI'):
        raise FinansCariKimlikError('Gecersiz kimlik_tipi.', code='KIMLIK_TIP_GECERSIZ', http_status=400)

    q = 'SELECT CKod, CName, CTip FROM Cari_Kart WHERE 1=1'
    params: list[Any] = []
    if arama:
        q += ' AND (CKod LIKE ? OR CName LIKE ?)'
        p = f'%{arama.strip()}%'
        params.extend([p, p])
    q += ' ORDER BY CKod LIMIT ?'
    params.append(int(limit) * 3)

    adaylar: list[dict[str, Any]] = []
    for row in con.execute(q, params).fetchall():
        ck = dict(row)
        normalized = sorted(normalize_ctip(ck.get('CTip')))
        ctip_val = validate_ctip_for_kimlik(ck, kimlik_tipi)
        uyumlu = bool(ctip_val.get('uygun'))

        kullanim = _ckod_cakisma(con, ck['CKod'], 'MUSTERI')
        kullanim_ted = _ckod_cakisma(con, ck['CKod'], 'TEDARIKCI')
        kullanan_tip: str | None = None
        kullanan_id: int | None = None
        if kullanim and kullanim['kimlik_tipi'] != kimlik_tipi:
            kullanan_tip = kullanim['kimlik_tipi']
            kullanan_id = kullanim['id']
        elif kullanim and kullanim['kimlik_tipi'] == kimlik_tipi:
            kullanan_tip = 'MUSTERI'
            kullanan_id = kullanim['id']
        if kullanim_ted and kullanim_ted['kimlik_tipi'] != kimlik_tipi:
            kullanan_tip = kullanim_ted['kimlik_tipi']
            kullanan_id = kullanim_ted['id']
        elif kullanim_ted and kullanim_ted['kimlik_tipi'] == kimlik_tipi:
            kullanan_tip = 'TEDARIKCI'
            kullanan_id = kullanim_ted['id']

        # Ayni CKod farkli tipte kullanim izinli
        ayni_tip_kullanim = _ckod_cakisma(con, ck['CKod'], kimlik_tipi)
        secilebilir = uyumlu and not ayni_tip_kullanim
        engel: str | None = None
        if ayni_tip_kullanim:
            engel = f"Ayni CKod aktif {kimlik_tipi} kimliginde (id={ayni_tip_kullanim['id']})"
        elif not uyumlu:
            engel = ctip_val.get('uyari') or 'CTip uyumsuz'
        elif not normalized:
            engel = 'CTip bilinmiyor'

        adaylar.append({
            'cari_kart_ckod': ck['CKod'],
            'cari_kart_unvan': ck['CName'],
            'ctip_raw': ck.get('CTip'),
            'ctip_normalized': normalized,
            'uyumlu': uyumlu,
            'baska_aktif_kimlikte': bool(ayni_tip_kullanim),
            'kullanan_kimlik_tipi': kullanan_tip,
            'kullanan_kimlik_id': kullanan_id,
            'secilebilir': secilebilir,
            'engel_aciklama': engel,
        })
        if len(adaylar) >= limit:
            break
    return adaylar
