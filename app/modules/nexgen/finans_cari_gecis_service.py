# -*- coding: utf-8 -*-
"""Toplu cari kart geçiş orchestration — FAZ-GECIS Bölüm A."""
from __future__ import annotations

import sqlite3
from typing import Any

from modules.nexgen.finans_belgesi_repository import tablo_var
from modules.nexgen.finans_cari_identity_resolver import resolve_by_operasyonel
from modules.nexgen.finans_cari_kart_service import get_by_ckod_raw
from modules.nexgen.finans_cari_provision_service import (
    FinansCariProvisionError,
    is_test_kayit,
    provision_operasyonel,
)
from modules.nexgen.finans_core_config import CARI_TIP_MUSTERI, CARI_TIP_TEDARIKCI

SINIF_DOGRU = 'A'
SINIF_BAGLANTI_EKSIK = 'B'
SINIF_KART_YOK = 'C'
SINIF_KART_BOZUK = 'D'
SINIF_MUKERRER = 'E'
SINIF_TEST = 'F'


def _musteri_kayitlari(con: sqlite3.Connection) -> list[dict[str, Any]]:
    if not tablo_var(con, 'nexgen_cari'):
        return []
    return [dict(r) for r in con.execute(
        'SELECT id, cari_kod, unvan, aktif FROM nexgen_cari ORDER BY id',
    ).fetchall()]


def _tedarikci_kayitlari(con: sqlite3.Connection) -> list[dict[str, Any]]:
    if not tablo_var(con, 'nexgen_tedarikci'):
        return []
    return [dict(r) for r in con.execute(
        'SELECT id, kod, ad, aktif, para_birimi FROM nexgen_tedarikci ORDER BY id',
    ).fetchall()]


def siniflandir_kayit(
    con: sqlite3.Connection,
    tip: str,
    operasyonel_id: int,
    kod: str,
    unvan: str,
    aktif: bool,
) -> dict[str, Any]:
    base = {
        'cari_tipi': tip,
        'operasyonel_id': int(operasyonel_id),
        'kod': kod,
        'unvan': unvan,
        'aktif': bool(aktif),
    }
    if not aktif:
        return {**base, 'sinif': SINIF_TEST, 'neden': 'Pasif operasyonel cari'}
    if is_test_kayit(kod, unvan):
        return {**base, 'sinif': SINIF_TEST, 'neden': 'Test/deneme kaydı'}
    if not (kod or '').strip() or not (unvan or '').strip():
        return {**base, 'sinif': SINIF_MUKERRER, 'neden': 'Zorunlu bilgi eksik'}

    ckod = kod.strip()
    finans = get_by_ckod_raw(con, ckod)
    legacy = con.execute('SELECT CKod, Aktif FROM Cari_Kart WHERE CKod=?', (ckod,)).fetchone()

    try:
        res = resolve_by_operasyonel(con, tip, int(operasyonel_id), require_active=True)
        if res.finans_kart and not res.requires_manual_link and res.finance_card_code == ckod:
            return {**base, 'sinif': SINIF_DOGRU, 'neden': 'Finans kartı ve bağlantı tamam'}
    except Exception:
        pass

    if finans and not finans['aktif']:
        return {**base, 'sinif': SINIF_KART_BOZUK, 'neden': 'Finans kartı pasif'}

    if tip == CARI_TIP_MUSTERI and tablo_var(con, 'cari_eslestirme'):
        rows = con.execute(
            'SELECT cari_kart_ckod FROM cari_eslestirme WHERE nexgen_cari_id=? AND aktif=1',
            (int(operasyonel_id),),
        ).fetchall()
        kodlar = {r['cari_kart_ckod'] for r in rows if r['cari_kart_ckod']}
        if len(kodlar) > 1:
            return {**base, 'sinif': SINIF_MUKERRER, 'neden': 'Birden fazla eslestirme CKod'}

    if finans and legacy:
        return {**base, 'sinif': SINIF_BAGLANTI_EKSIK, 'neden': 'Finans kartı var — bağlantı eksik'}

    return {**base, 'sinif': SINIF_KART_YOK, 'neden': 'Finans kartı oluşturulabilir'}


def siniflandir_tumu(con: sqlite3.Connection) -> dict[str, Any]:
    siniflar: dict[str, list[dict[str, Any]]] = {
        SINIF_DOGRU: [], SINIF_BAGLANTI_EKSIK: [], SINIF_KART_YOK: [],
        SINIF_KART_BOZUK: [], SINIF_MUKERRER: [], SINIF_TEST: [],
    }
    for r in _musteri_kayitlari(con):
        s = siniflandir_kayit(
            con, CARI_TIP_MUSTERI, int(r['id']),
            r['cari_kod'], r['unvan'], bool(r['aktif']),
        )
        siniflar[s['sinif']].append(s)
    for r in _tedarikci_kayitlari(con):
        s = siniflandir_kayit(
            con, CARI_TIP_TEDARIKCI, int(r['id']),
            r['kod'], r['ad'], bool(r['aktif']),
        )
        siniflar[s['sinif']].append(s)
    ozet = {k: len(v) for k, v in siniflar.items()}
    return {'ozet': ozet, 'siniflar': siniflar}


def apply_gecis(
    con: sqlite3.Connection,
    *,
    kullanici_id: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Cari bazlı transaction ile güvenli geçiş apply."""
    sinif = siniflandir_tumu(con)
    uygulanacak = (
        sinif['siniflar'][SINIF_KART_YOK]
        + sinif['siniflar'][SINIF_BAGLANTI_EKSIK]
    )
    sonuclar: list[dict[str, Any]] = []
    olusturulan_kart = 0
    olusturulan_baglanti = 0
    noop = 0
    hatalar: list[dict[str, Any]] = []

    for kayit in uygulanacak:
        if dry_run:
            sonuclar.append({**kayit, 'dry_run': True, 'sonuc': 'PLANLANDI'})
            continue
        try:
            paket = provision_operasyonel(
                con,
                kayit['cari_tipi'],
                kayit['operasyonel_id'],
                kullanici_id=kullanici_id,
                owns_transaction=True,
                skip_test=True,
            )
            sonuclar.append(paket)
            if paket.get('sonuc') == 'NOOP':
                noop += 1
            else:
                o = paket.get('olusturulan') or {}
                if o.get('finans_cari_kart'):
                    olusturulan_kart += 1
                if o.get('kimlik') or o.get('eslestirme'):
                    olusturulan_baglanti += 1
        except FinansCariProvisionError as e:
            hatalar.append({
                **kayit,
                'hata_kodu': e.hata_kodu,
                'mesaj': e.mesaj,
            })

    return {
        'dry_run': dry_run,
        'siniflandirma': sinif,
        'uygulanan_sayisi': len(uygulanacak),
        'olusturulan_kart': olusturulan_kart,
        'olusturulan_baglanti': olusturulan_baglanti,
        'noop': noop,
        'hatalar': hatalar,
        'sonuclar': sonuclar,
    }


def reconciliation_ozet(con: sqlite3.Connection) -> dict[str, Any]:
    aktif_m = int(con.execute('SELECT COUNT(*) FROM nexgen_cari WHERE aktif=1').fetchone()[0])
    aktif_t = 0
    if tablo_var(con, 'nexgen_tedarikci'):
        aktif_t = int(con.execute('SELECT COUNT(*) FROM nexgen_tedarikci WHERE aktif=1').fetchone()[0])
    aktif_toplam = aktif_m + aktif_t

    finans_kart_eksik = 0
    baglanti_eksik = 0
    resolver_hata = 0
    teknik_istisna = 0

    for tip, rows_fn, kod_fn, unvan_fn in (
        (CARI_TIP_MUSTERI, _musteri_kayitlari, lambda r: r['cari_kod'], lambda r: r['unvan']),
        (CARI_TIP_TEDARIKCI, _tedarikci_kayitlari, lambda r: r['kod'], lambda r: r['ad']),
    ):
        for r in rows_fn(con):
            if not r.get('aktif'):
                continue
            if is_test_kayit(kod_fn(r), unvan_fn(r)):
                teknik_istisna += 1
                continue
            s = siniflandir_kayit(
                con, tip, int(r['id']), kod_fn(r), unvan_fn(r), True,
            )
            if s['sinif'] == SINIF_DOGRU:
                continue
            if s['sinif'] == SINIF_KART_YOK:
                finans_kart_eksik += 1
            elif s['sinif'] == SINIF_BAGLANTI_EKSIK:
                baglanti_eksik += 1
            elif s['sinif'] in (SINIF_MUKERRER, SINIF_KART_BOZUK):
                resolver_hata += 1
                teknik_istisna += 1

    return {
        'aktif_gercek_cari': aktif_toplam - teknik_istisna,
        'finans_kart_eksik_aktif': finans_kart_eksik,
        'baglanti_eksik_aktif': baglanti_eksik,
        'resolver_hatasi': resolver_hata,
        'teknik_istisna': teknik_istisna,
        'finans_cari_kart_sayisi': int(con.execute(
            'SELECT COUNT(*) FROM finans_cari_kart',
        ).fetchone()[0]) if tablo_var(con, 'finans_cari_kart') else 0,
    }
