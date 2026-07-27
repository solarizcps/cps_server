# -*- coding: utf-8 -*-
"""Finans Belgesi okuma — liste, detay, posting önizleme."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from modules.nexgen.finans_belgesi_config import (
    BELGE_TIP_SATIS_SEVKIYAT,
    BELGE_TIP_TAHSILAT,
    DURUM_BEKLIYOR,
    DURUM_DUZELTME_BEKLIYOR,
    DURUM_EKSIK_BILGI,
    DURUM_INCELEMEDE,
    DURUM_ONAYLANDI,
    DURUM_GECIS,
    KAYNAK_TIP_SEVKIYAT,
    KAYNAK_TIP_TAHSILAT_KAYIT,
    POSTING_DURUM_HAZIR,
    POSTING_DURUM_POST_EDILDI,
)
from modules.nexgen.finans_belgesi_repository import (
    FinansBelgesiError,
    get_by_id,
    resolve_golden_cari_kart,
    tablo_var,
)
from modules.nexgen.finans_yetki import finans_aksiyonlar
from modules.nexgen.mo_tahsilat_config import CARI_ENTEGRASYON_AKTIF

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25


def _audit_list(belge: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        data = json.loads(belge.get('audit_json') or '[]')
        return data if isinstance(data, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _kaynak_ozet(con: sqlite3.Connection, belge: dict[str, Any]) -> dict[str, Any]:
    tip = belge.get('belge_tipi')
    if tip == BELGE_TIP_SATIS_SEVKIYAT and belge.get('sevkiyat_id'):
        row = con.execute(
            """
            SELECT id, sevkiyat_no, durum, sevk_tarihi, irsaliye_no, siparis_id
            FROM mo_musteri_sevkiyat WHERE id=?
            """,
            (int(belge['sevkiyat_id']),),
        ).fetchone()
        if row:
            d = dict(row)
            kg = con.execute(
                'SELECT COALESCE(SUM(miktar_kg),0) FROM mo_musteri_sevkiyat_kalem WHERE sevkiyat_id=?',
                (d['id'],),
            ).fetchone()[0]
            d['toplam_kg'] = float(kg or 0)
            return {'tip': KAYNAK_TIP_SEVKIYAT, 'sevkiyat': d}
    if tip == BELGE_TIP_TAHSILAT and belge.get('tahsilat_kayit_id'):
        row = con.execute(
            """
            SELECT id, kayit_kodu, durum, alinan_tutar, alinan_tarih, odeme_tipi, odeme_referansi
            FROM mo_tahsilat_kayit WHERE id=?
            """,
            (int(belge['tahsilat_kayit_id']),),
        ).fetchone()
        if row:
            return {'tip': KAYNAK_TIP_TAHSILAT_KAYIT, 'tahsilat': dict(row)}
    return {}


def _siparis_ozet(con: sqlite3.Connection, siparis_id: int | None) -> dict[str, Any] | None:
    if not siparis_id or not tablo_var(con, 'nexgen_planlama_siparis'):
        return None
    try:
        row = con.execute(
            """
            SELECT id, siparis_no, cari_id, cari_unvan, termin_tarihi, musteri_termin,
                   durum, olusturma_tarihi
            FROM nexgen_planlama_siparis WHERE id=?
            """,
            (int(siparis_id),),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        if tablo_var(con, 'nexgen_planlama_siparis_kalem'):
            cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis_kalem)').fetchall()}
            if 'miktar_kg' in cols:
                tr = con.execute(
                    'SELECT COALESCE(SUM(miktar_kg),0) FROM nexgen_planlama_siparis_kalem WHERE siparis_id=?',
                    (int(siparis_id),),
                ).fetchone()
                d['talep_kg'] = float(tr[0] or 0) if tr else None
        if tablo_var(con, 'nexgen_uretim_plan'):
            ucols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_uretim_plan)').fetchall()}
            if 'planlanan_kg' in ucols:
                ur = con.execute(
                    'SELECT COALESCE(SUM(planlanan_kg),0) FROM nexgen_uretim_plan WHERE siparis_id=? AND aktif=1',
                    (int(siparis_id),),
                ).fetchone()
                d['fiili_uretim_kg'] = float(ur[0] or 0) if ur else None
        return d
    except Exception:
        return None


def _belge_kalemleri(con: sqlite3.Connection, belge: dict[str, Any]) -> list[dict[str, Any]]:
    """Finans belgesi satır grid — yalnız gerçek kaynak kalemleri."""
    tip = belge.get('belge_tipi')
    pb = belge.get('para_birimi') or 'TRY'
    bf = belge.get('birim_fiyat')
    sevkiyat_id = belge.get('sevkiyat_id')
    if tip == BELGE_TIP_SATIS_SEVKIYAT and sevkiyat_id and tablo_var(con, 'mo_musteri_sevkiyat_kalem'):
        rows = con.execute(
            """
            SELECT id, urun_adi, renk_ad, formul_ad, miktar_kg, miktar_adet, notlar
            FROM mo_musteri_sevkiyat_kalem WHERE sevkiyat_id=? ORDER BY id
            """,
            (int(sevkiyat_id),),
        ).fetchall()
        kalemler: list[dict[str, Any]] = []
        for i, row in enumerate(rows, start=1):
            r = dict(row)
            aciklama = ' · '.join(
                x for x in (r.get('urun_adi'), r.get('renk_ad'), r.get('formul_ad')) if x
            ) or (r.get('notlar') or '—')
            miktar = float(r.get('miktar_kg') or 0)
            birim_fiyat = float(bf) if bf not in (None, '') else None
            tutar = round(miktar * birim_fiyat, 2) if birim_fiyat is not None and miktar else None
            kalemler.append({
                'satir': i,
                'aciklama': aciklama,
                'kaynak': 'Sevkiyat',
                'miktar': miktar,
                'birim': 'KG',
                'birim_fiyat': birim_fiyat,
                'para_birimi': pb,
                'tutar': tutar,
                'durum': None,
            })
        return kalemler
    return []


def _liste_where(
    *,
    belge_tipi: str | None = None,
    durum: str | None = None,
    posting_durumu: str | None = None,
    cari_id: int | None = None,
    siparis_id: int | None = None,
    sevkiyat_id: int | None = None,
    tahsilat_id: int | None = None,
    tarih_bas: str | None = None,
    tarih_bit: str | None = None,
    arama: str | None = None,
) -> tuple[str, list]:
    where = ['fb.aktif=1']
    params: list = []

    if belge_tipi:
        where.append('fb.belge_tipi=?')
        params.append(belge_tipi.strip().upper())
    if durum:
        where.append('fb.durum=?')
        params.append(durum.strip().upper())
    if posting_durumu:
        where.append('fb.posting_durumu=?')
        params.append(posting_durumu.strip().upper())
    if cari_id:
        where.append('fb.cari_id=?')
        params.append(int(cari_id))
    if siparis_id:
        where.append('fb.siparis_id=?')
        params.append(int(siparis_id))
    if sevkiyat_id:
        where.append('fb.sevkiyat_id=?')
        params.append(int(sevkiyat_id))
    if tahsilat_id:
        where.append('fb.tahsilat_kayit_id=?')
        params.append(int(tahsilat_id))
    if tarih_bas:
        where.append('fb.islem_tarihi>=?')
        params.append(tarih_bas[:10])
    if tarih_bit:
        where.append('fb.islem_tarihi<=?')
        params.append(tarih_bit[:10])
    if arama:
        q = f'%{arama.strip()}%'
        where.append(
            '(fb.belge_kodu LIKE ? OR fb.cari_unvan LIKE ? OR fb.siparis_no LIKE ? OR fb.kaynak_no LIKE ?)'
        )
        params.extend([q, q, q, q])

    return ' AND '.join(where), params


def liste_ozet(
    con: sqlite3.Connection,
    **filtreler,
) -> dict[str, int]:
    """Aktif filtre sonucuna göre KPI sayıları."""
    wsql, params = _liste_where(**filtreler)
    total = int(con.execute(
        f'SELECT COUNT(*) FROM finans_belgesi fb WHERE {wsql}', params,
    ).fetchone()[0])

    durum_rows = con.execute(
        f'SELECT fb.durum, COUNT(*) AS n FROM finans_belgesi fb WHERE {wsql} GROUP BY fb.durum',
        params,
    ).fetchall()
    durum_map = {str(r['durum']): int(r['n']) for r in durum_rows}

    bekleyen_durumlar = (
        DURUM_BEKLIYOR, DURUM_INCELEMEDE, DURUM_DUZELTME_BEKLIYOR,
    )
    bekleyen = sum(durum_map.get(d, 0) for d in bekleyen_durumlar)

    posting_hazir = int(con.execute(
        f"""
        SELECT COUNT(*) FROM finans_belgesi fb
        WHERE {wsql} AND fb.posting_durumu=?
        """,
        [*params, POSTING_DURUM_HAZIR],
    ).fetchone()[0])

    return {
        'toplam': total,
        'bekleyen': bekleyen,
        'eksik_bilgi': durum_map.get(DURUM_EKSIK_BILGI, 0),
        'onaylandi': durum_map.get(DURUM_ONAYLANDI, 0),
        'posting_hazir': posting_hazir,
    }


def liste_belgeler(
    con: sqlite3.Connection,
    *,
    belge_tipi: str | None = None,
    durum: str | None = None,
    posting_durumu: str | None = None,
    cari_id: int | None = None,
    siparis_id: int | None = None,
    sevkiyat_id: int | None = None,
    tahsilat_id: int | None = None,
    tarih_bas: str | None = None,
    tarih_bit: str | None = None,
    arama: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    if not tablo_var(con, 'finans_belgesi'):
        raise FinansBelgesiError('Migration 128 uygulanmamış.', 503, 'MIGRATION_128')

    page = max(1, int(page or 1))
    page_size = min(MAX_PAGE_SIZE, max(1, int(page_size or DEFAULT_PAGE_SIZE)))
    offset = (page - 1) * page_size

    wsql, params = _liste_where(
        belge_tipi=belge_tipi,
        durum=durum,
        posting_durumu=posting_durumu,
        cari_id=cari_id,
        siparis_id=siparis_id,
        sevkiyat_id=sevkiyat_id,
        tahsilat_id=tahsilat_id,
        tarih_bas=tarih_bas,
        tarih_bit=tarih_bit,
        arama=arama,
    )

    total = int(con.execute(
        f'SELECT COUNT(*) FROM finans_belgesi fb WHERE {wsql}', params,
    ).fetchone()[0])

    rows = con.execute(
        f"""
        SELECT fb.*, nc.cari_kod AS nexgen_cari_kod
        FROM finans_belgesi fb
        LEFT JOIN nexgen_cari nc ON nc.id = fb.cari_id
        WHERE {wsql}
        ORDER BY fb.id DESC
        LIMIT ? OFFSET ?
        """,
        [*params, page_size, offset],
    ).fetchall()

    return {
        'liste': [dict(r) for r in rows],
        'sayfalama': {
            'page': page,
            'page_size': page_size,
            'total': total,
            'total_pages': max(1, (total + page_size - 1) // page_size),
        },
        'ozet': liste_ozet(
            con,
            belge_tipi=belge_tipi,
            durum=durum,
            posting_durumu=posting_durumu,
            cari_id=cari_id,
            siparis_id=siparis_id,
            sevkiyat_id=sevkiyat_id,
            tahsilat_id=tahsilat_id,
            tarih_bas=tarih_bas,
            tarih_bit=tarih_bit,
            arama=arama,
        ),
    }


def detay_paket(
    con: sqlite3.Connection,
    belge_id: int,
    yk: set[str] | frozenset[str],
    user_dict: dict | None = None,
) -> dict[str, Any]:
    from modules.nexgen.finans_cari_read_service import (
        FinansCariReadError,
        cari_hesap_paket,
    )

    belge = get_by_id(con, belge_id)
    durum = (belge.get('durum') or '').upper()
    gecisler = sorted(DURUM_GECIS.get(durum, frozenset()))
    cari_hesap = None
    cari_id = belge.get('cari_id')
    if cari_id:
        try:
            cari_hesap = cari_hesap_paket(
                con, int(cari_id), yk=yk, user_dict=user_dict,
            )
        except FinansCariReadError:
            cari_hesap = None
    siparis_id = belge.get('siparis_id')
    return {
        'belge': belge,
        'kaynak_ozet': _kaynak_ozet(con, belge),
        'siparis_ozet': _siparis_ozet(con, int(siparis_id) if siparis_id else None),
        'kalemler': _belge_kalemleri(con, belge),
        'audit': _audit_list(belge),
        'durum_gecisleri': gecisler,
        'aksiyonlar': finans_aksiyonlar(belge, yk),
        'posting_onizleme': posting_onizleme(con, belge),
        'cari_hesap': cari_hesap,
    }


def posting_onizleme(con: sqlite3.Connection, belge: dict[str, Any]) -> dict[str, Any]:
    """Yan etkisiz posting validasyon ve muhasebe önizleme özeti."""
    hatalar: list[dict[str, str]] = []
    durum = (belge.get('durum') or '').upper()
    pd = (belge.get('posting_durumu') or '').upper()
    tip = (belge.get('belge_tipi') or '').upper()
    cari_id = int(belge.get('cari_id') or 0)

    if durum == DURUM_EKSIK_BILGI:
        hatalar.append({'kod': 'EKSIK_BILGI', 'mesaj': 'Belgede eksik bilgi var — önce tamamlanmalı.'})
    if durum != DURUM_ONAYLANDI:
        hatalar.append({'kod': 'POST_ONAY_GEREKLI', 'mesaj': 'Belge onaylı değil.'})
    if pd == POSTING_DURUM_POST_EDILDI or belge.get('cari_har_id'):
        hatalar.append({'kod': 'POST_DUPLICATE', 'mesaj': 'Belge zaten post edilmiş.'})
    if float(belge.get('toplam_tutar') or 0) <= 0:
        hatalar.append({'kod': 'POST_TUTAR_SIFIR', 'mesaj': 'Tutar sıfır.'})
    if not (belge.get('para_birimi') or '').strip():
        hatalar.append({'kod': 'PARA_BIRIMI_EKSIK', 'mesaj': 'Para birimi eksik.'})
    if tip == BELGE_TIP_SATIS_SEVKIYAT:
        if not belge.get('birim_fiyat') or float(belge.get('birim_fiyat') or 0) <= 0:
            hatalar.append({'kod': 'FIYAT_EKSIK', 'mesaj': 'Birim fiyat eksik.'})
    if not belge.get('vade_tarihi') and belge.get('vade_gun') in (None, ''):
        hatalar.append({'kod': 'VADE_EKSIK', 'mesaj': 'Vade bilgisi eksik.'})

    cari_bulundu = False
    cari_unvan = belge.get('cari_unvan') or ''
    if cari_id:
        row = con.execute('SELECT id, unvan FROM nexgen_cari WHERE id=?', (cari_id,)).fetchone()
        if row:
            cari_bulundu = True
            cari_unvan = row['unvan'] or cari_unvan

    ckod = belge.get('cari_kart_ckod')
    golden_bulundu = False
    golden_sebep = None
    try:
        ckod = resolve_golden_cari_kart(con, cari_id)
        golden_bulundu = bool(ckod)
    except FinansBelgesiError as e:
        hatalar.append({'kod': e.hata_kodu or 'CARI_ESLESME', 'mesaj': e.mesaj})
        golden_sebep = e.mesaj

    islem = 'BORC' if tip == BELGE_TIP_SATIS_SEVKIYAT else (
        'ALACAK' if tip == BELGE_TIP_TAHSILAT else '—'
    )
    tutar = float(belge.get('toplam_tutar') or 0)
    belge_no = belge.get('cari_har_belge_no') or belge.get('belge_kodu') or ''
    if tip == BELGE_TIP_SATIS_SEVKIYAT:
        aciklama = (
            f"Sevkiyat {belge.get('kaynak_no') or ''} / Sipariş {belge.get('siparis_no') or ''} "
            f"/ İrsaliye {belge.get('irsaliye_no') or '—'}"
        ).strip()
    else:
        aciklama = f"Tahsilat {belge.get('kaynak_no') or ''}".strip()

    hazir = len(hatalar) == 0
    cari_har_yazilabilir = hazir and durum == DURUM_ONAYLANDI and not belge.get('cari_har_id')

    if hazir:
        durum_panel = 'HAZIR'
        durum_panel_etiket = 'Hazır'
    elif durum != DURUM_ONAYLANDI or durum == DURUM_EKSIK_BILGI:
        durum_panel = 'INCELEME_GEREKLI'
        durum_panel_etiket = 'İnceleme Gerekli'
    else:
        durum_panel = 'MUHASEBELESTIRILEMEZ'
        durum_panel_etiket = 'Muhasebeleştirilemez'

    return {
        'hazir': hazir,
        'durum_panel': durum_panel,
        'durum_panel_etiket': durum_panel_etiket,
        'cari_entegrasyon_aktif': CARI_ENTEGRASYON_AKTIF,
        'gercek_posting_kapali': not CARI_ENTEGRASYON_AKTIF,
        'can_live_post': (
            hazir and pd == POSTING_DURUM_HAZIR and durum == DURUM_ONAYLANDI
            and not belge.get('cari_har_id') and CARI_ENTEGRASYON_AKTIF
        ),
        'golden_cari_kart_ckod': ckod,
        'posting_durumu': belge.get('posting_durumu'),
        'cari_har_id': belge.get('cari_har_id'),
        'hatalar': hatalar,
        'hata_sayisi': len(hatalar),
        'golden_analiz': {
            'cari_bulundu': cari_bulundu,
            'cari_id': cari_id,
            'cari_unvan': cari_unvan,
            'golden_mapping_bulundu': golden_bulundu,
            'cari_har_yazilabilir': cari_har_yazilabilir,
            'sebep': golden_sebep,
        },
        'muhasebe_ozet': {
            'islem': islem,
            'belge_tipi': tip,
            'belge_no': belge_no,
            'cari_unvan': cari_unvan,
            'cari_kart_ckod': ckod,
            'kaynak_no': belge.get('kaynak_no'),
            'sevkiyat_id': belge.get('sevkiyat_id'),
            'siparis_no': belge.get('siparis_no'),
            'tutar': format(tutar, '.2f') if tutar else '0.00',
            'para_birimi': belge.get('para_birimi') or 'TRY',
            'vade_tarihi': belge.get('vade_tarihi'),
            'aciklama': aciklama,
            'muhasebe_kaydi_olusturulacak': cari_har_yazilabilir and not CARI_ENTEGRASYON_AKTIF,
            'cari_har_olusturulacak': cari_har_yazilabilir,
        },
    }
