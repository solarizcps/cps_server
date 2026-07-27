# -*- coding: utf-8 -*-
"""Cari Hesap — Hesap çalışma alanı read modeli (FAZ-FINANS-CARI-HESAP-WORKSPACE-1)."""
from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal
from typing import Any

from modules.nexgen.finans_belgesi_repository import tablo_var
from modules.nexgen.finans_cari_identity_resolver import resolve_by_operasyonel
from modules.nexgen.finans_core_config import (
    OI_DURUM_ACIK,
    OI_DURUM_IPTAL,
    OI_DURUM_KAPALI,
    OI_DURUM_KISMI_KAPALI,
    OI_DURUM_TERS_ACILDI,
    OI_DURUM_UYUSMAZLIK,
    OI_YON_ALACAK,
    OI_YON_BORC,
)
from modules.nexgen.finans_core_schema import decimal_para
from modules.nexgen.finans_ledger_standard import hareket_kaynak_sinifi, load_hareket_metadata_maps

GORUNUM_BORCLAR = 'borclar'
GORUNUM_ALACAKLAR = 'alacaklar'
GORUNUM_ACIKLAR = 'aciklar'
GORUNUM_KAPANANLAR = 'kapananlar'
GORUNUMLER = (GORUNUM_BORCLAR, GORUNUM_ALACAKLAR, GORUNUM_ACIKLAR, GORUNUM_KAPANANLAR)

OI_DURUM_ETIKET = {
    OI_DURUM_ACIK: 'Açık',
    OI_DURUM_KISMI_KAPALI: 'Kısmi Kapalı',
    OI_DURUM_KAPALI: 'Kapalı',
    OI_DURUM_UYUSMAZLIK: 'Uyumsuzluk',
    OI_DURUM_IPTAL: 'İptal',
    OI_DURUM_TERS_ACILDI: 'Ters Açıldı',
}

BELGE_TIP_ETIKET = {
    'SATIS_SEVKIYAT': 'Satış Sevkiyat',
    'TAHSILAT': 'Tahsilat',
    'SATINALMA_MAL_KABUL': 'Satınalma Mal Kabul',
    'SATINALMA_FATURA': 'Satınalma Fatura',
    'TERS': 'Ters',
    'DUZELTME': 'Düzeltme',
    'MAHSUP': 'Mahsup',
}


def _today_iso() -> str:
    return date.today().isoformat()


def _float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _iso_tarih(v: Any) -> str | None:
    if v in (None, ''):
        return None
    s = str(v).strip()
    if ' ' in s:
        s = s.split(' ')[0]
    return s[:10] if len(s) >= 10 else s or None


def _belge_turu_etiket(belge_tipi: str | None) -> str | None:
    if not belge_tipi:
        return None
    return BELGE_TIP_ETIKET.get(belge_tipi.upper(), belge_tipi.replace('_', ' ').title())


def _open_item_satir(row: sqlite3.Row, *, today: str) -> dict[str, Any]:
    oi = dict(row)
    vade = _iso_tarih(oi.get('vade_tarihi'))
    fis_no = oi.get('cari_har_id')
    tarih = _iso_tarih(oi.get('islem_tarihi') or oi.get('olusturma_tarihi'))
    belge_tipi = oi.get('belge_tipi')
    durum = (oi.get('durum') or '').upper()
    return {
        'satir_tipi': 'OPEN_ITEM',
        'open_item_id': int(oi['id']),
        'fis_no': str(fis_no) if fis_no else None,
        'tarih': tarih,
        'evrak_belge_no': oi.get('belge_kodu') or oi.get('idempotency_key'),
        'belge_turu': belge_tipi,
        'belge_turu_etiket': _belge_turu_etiket(belge_tipi),
        'vade_tarihi': vade,
        'ilk_tutar': _float(oi.get('orijinal_tutar')),
        'kapanan_tutar': _float(oi.get('kapanan_tutar')),
        'kalan_tutar': _float(oi.get('acik_tutar')),
        'para_birimi': oi.get('para_birimi') or 'TRY',
        'durum': durum,
        'durum_etiket': OI_DURUM_ETIKET.get(durum, durum),
        'kaynak': 'finans_open_item',
        'kaynak_etiket': 'Open Item',
        'yon': oi.get('yon'),
        'finans_belgesi_id': int(oi['finans_belgesi_id']) if oi.get('finans_belgesi_id') else None,
        'vadesi_gecmis': bool(vade and vade < today and durum in (OI_DURUM_ACIK, OI_DURUM_KISMI_KAPALI)),
        'tiklanabilir': bool(oi.get('finans_belgesi_id')),
    }


def _onceki_donem_satir(row: sqlite3.Row, para_birimi: str) -> dict[str, Any]:
    borc = round(float(row['Borc'] or 0), 2)
    alacak = round(float(row['Alacak'] or 0), 2)
    yon = OI_YON_BORC if borc > 0 else OI_YON_ALACAK
    ilk = borc if borc > 0 else alacak
    return {
        'satir_tipi': 'ONCEKI_DONEM',
        'cari_har_id': int(row['Id']),
        'fis_no': str(row['Id']),
        'tarih': _iso_tarih(row['Tarih']),
        'evrak_belge_no': row['BelgeNo'],
        'belge_turu': row['BelgeTip'],
        'belge_turu_etiket': row['BelgeTip'] or '—',
        'vade_tarihi': None,
        'ilk_tutar': ilk if ilk > 0 else None,
        'kapanan_tutar': None,
        'kapanan_tutar_guvenilir': False,
        'kalan_tutar': None,
        'kalan_tutar_guvenilir': False,
        'para_birimi': para_birimi,
        'durum': 'ONCEKI_DONEM',
        'durum_etiket': 'Önceki Dönem',
        'kaynak': 'Cari_Har',
        'kaynak_etiket': 'Önceki Dönem',
        'yon': yon,
        'finans_belgesi_id': None,
        'vadesi_gecmis': False,
        'tiklanabilir': False,
        'aciklama': row['Aciklama'],
    }


def _open_item_filtre(gorunum: str, yon: str, durum: str) -> bool:
    g = (gorunum or GORUNUM_ACIKLAR).strip().lower()
    d = (durum or '').upper()
    y = (yon or '').upper()
    if g == GORUNUM_KAPANANLAR:
        return d == OI_DURUM_KAPALI
    if d not in (OI_DURUM_ACIK, OI_DURUM_KISMI_KAPALI):
        return False
    if g == GORUNUM_BORCLAR:
        return y == OI_YON_BORC
    if g == GORUNUM_ALACAKLAR:
        return y == OI_YON_ALACAK
    return True


def _load_open_items(con: sqlite3.Connection, ckod: str) -> list[dict[str, Any]]:
    if not tablo_var(con, 'finans_open_item'):
        return []
    rows = con.execute(
        """
        SELECT oi.*, fb.belge_kodu, fb.belge_tipi, fb.cari_har_id,
               fb.islem_tarihi, fb.olusturma_tarihi, fb.durum AS belge_durum
        FROM finans_open_item oi
        LEFT JOIN finans_belgesi fb ON fb.id = oi.finans_belgesi_id AND fb.aktif = 1
        WHERE oi.ckod = ?
        ORDER BY COALESCE(oi.vade_tarihi, fb.islem_tarihi, oi.olusturma_tarihi) ASC, oi.id ASC
        """,
        (ckod,),
    ).fetchall()
    today = _today_iso()
    return [_open_item_satir(r, today=today) for r in rows]


def _nexgen_har_id_set(con: sqlite3.Connection, ckod: str) -> set[int]:
    """Open item / NexGen belge ile temsil edilen Cari_Har Id'leri — mükerrer engeli."""
    covered: set[int] = set()
    if tablo_var(con, 'finans_belgesi'):
        for r in con.execute(
            """
            SELECT cari_har_id FROM finans_belgesi
            WHERE cari_har_id IS NOT NULL AND aktif = 1
            """,
        ).fetchall():
            if r['cari_har_id']:
                covered.add(int(r['cari_har_id']))
    if not tablo_var(con, 'Cari_Har'):
        return covered
    rows = con.execute('SELECT Id, BelgeTip FROM Cari_Har WHERE CKod=?', (ckod,)).fetchall()
    if not rows:
        return covered
    ids = [int(r['Id']) for r in rows]
    fb_map, fh_map = load_hareket_metadata_maps(con, ids)
    for r in rows:
        hid = int(r['Id'])
        sinif = hareket_kaynak_sinifi(
            finans_belgesi_var=hid in fb_map,
            finans_hareket=fh_map.get(hid),
            belge_tip=r['BelgeTip'],
        )
        if sinif != 'LEGACY':
            covered.add(hid)
    return covered


def _load_onceki_donem(
    con: sqlite3.Connection,
    ckod: str,
    para_birimi: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if not tablo_var(con, 'Cari_Har'):
        return []
    covered = _nexgen_har_id_set(con, ckod)
    rows = con.execute(
        """
        SELECT Id, Tarih, BelgeNo, BelgeTip, Aciklama, Borc, Alacak
        FROM Cari_Har WHERE CKod=?
        ORDER BY Tarih DESC, Id DESC
        LIMIT ?
        """,
        (ckod, max(limit * 3, 100)),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        hid = int(r['Id'])
        if hid in covered:
            continue
        out.append(_onceki_donem_satir(r, para_birimi))
        if len(out) >= limit:
            break
    return out


def hesap_workspace_read(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
    *,
    gorunum: str = GORUNUM_ACIKLAR,
    limit: int = 200,
    offset: int = 0,
    onceki_donem_limit: int = 30,
) -> dict[str, Any]:
    """Cari kart merkezli Hesap çalışma alanı — read-only."""
    g = (gorunum or GORUNUM_ACIKLAR).strip().lower()
    if g not in GORUNUMLER:
        g = GORUNUM_ACIKLAR

    resolution = resolve_by_operasyonel(con, cari_tipi, int(operasyonel_id))
    ckod = resolution.finance_card_code
    para_birimi = 'TRY'
    if resolution.finans_kart:
        para_birimi = resolution.finans_kart.get('para_birimi') or 'TRY'

    empty = {
        'gorunum': g,
        'cari_tipi': cari_tipi,
        'operasyonel_id': int(operasyonel_id),
        'cari_kart_ckod': ckod,
        'kart_baglanti_eksik': resolution.requires_manual_link,
        'para_birimi': para_birimi,
        'open_item_mevcut': False,
        'open_item_toplam': 0,
        'kalemler': [],
        'ozet': {
            'borc_acik_sayisi': 0,
            'alacak_acik_sayisi': 0,
            'kapanan_sayisi': 0,
            'acik_toplam_borc': 0.0,
            'acik_toplam_alacak': 0.0,
        },
        'onceki_donem': {'mevcut': False, 'sayisi': 0, 'kalemler': []},
        'uyari': None,
        'toplam': 0,
        'limit': int(limit),
        'offset': int(offset),
    }

    if not ckod:
        empty['uyari'] = 'Cari Kart bağlantısı olmadan hesap kalemleri gösterilemez.'
        return empty

    all_oi = _load_open_items(con, ckod)
    empty['open_item_mevcut'] = tablo_var(con, 'finans_open_item')
    empty['open_item_toplam'] = len(all_oi)

    borc_acik = alacak_acik = kapanan = 0
    acik_borc = acik_alacak = Decimal('0')
    for k in all_oi:
        d = (k.get('durum') or '').upper()
        if d == OI_DURUM_KAPALI:
            kapanan += 1
        elif d in (OI_DURUM_ACIK, OI_DURUM_KISMI_KAPALI):
            kalan = decimal_para(k.get('kalan_tutar'))
            if k.get('yon') == OI_YON_BORC:
                borc_acik += 1
                acik_borc += kalan
            elif k.get('yon') == OI_YON_ALACAK:
                alacak_acik += 1
                acik_alacak += kalan

    empty['ozet'] = {
        'borc_acik_sayisi': borc_acik,
        'alacak_acik_sayisi': alacak_acik,
        'kapanan_sayisi': kapanan,
        'acik_toplam_borc': float(acik_borc),
        'acik_toplam_alacak': float(acik_alacak),
    }

    filtered = [
        k for k in all_oi
        if _open_item_filtre(g, k.get('yon') or '', k.get('durum') or '')
    ]
    total = len(filtered)
    page = filtered[int(offset): int(offset) + int(limit)]

    uyari = None
    if not all_oi and tablo_var(con, 'finans_open_item'):
        uyari = (
            'Bu caride henüz open item kaydı yok. NexGen posting sonrası kalemler burada görünecek. '
            'Önceki dönem hareketleri aşağıda ayrı gösterilir; kapanan/kalan tutar uydurulmaz.'
        )
    elif not filtered and all_oi:
        uyari = f'Seçilen görünüme ({g}) uygun open item bulunmuyor.'

    onceki = _load_onceki_donem(con, ckod, para_birimi, limit=onceki_donem_limit)
    onceki_toplam = 0
    if tablo_var(con, 'Cari_Har'):
        covered = _nexgen_har_id_set(con, ckod)
        har_rows = con.execute('SELECT Id FROM Cari_Har WHERE CKod=?', (ckod,)).fetchall()
        onceki_toplam = sum(1 for r in har_rows if int(r['Id']) not in covered)

    empty.update({
        'kalemler': page,
        'toplam': total,
        'uyari': uyari,
        'onceki_donem': {
            'mevcut': onceki_toplam > 0,
            'sayisi': onceki_toplam,
            'kalemler': onceki,
        },
    })
    return empty
