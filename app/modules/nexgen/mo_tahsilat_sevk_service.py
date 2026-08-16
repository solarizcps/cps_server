# -*- coding: utf-8 -*-
"""Tahsilat ↔ sevkiyat V1 — sevk adayları, kalan hesabı, write guard."""
from __future__ import annotations

import math
import sqlite3
from typing import Any

from modules.nexgen.mo_tahsilat_config import (
    KAYIT_ONAY_BEKLIYOR_DURUMLARI,
    SEVK_TAHSILAT_DURUMLARI,
    TAHSILAT_EDILEN_DURUMLARI,
)
from modules.nexgen.mo_tahsilat_kayit_service import MoTahsilatError

FX_KALAN_TOLERANS = 0.009


def _tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _kolon_var(con: sqlite3.Connection, tablo: str, kolon: str) -> bool:
    if not _tablo_var(con, tablo):
        return False
    return kolon in [c[1] for c in con.execute(f'PRAGMA table_info({tablo})').fetchall()]


def _sevk_snapshot_kolonlari_var(con: sqlite3.Connection) -> bool:
    if not _tablo_var(con, 'mo_musteri_sevkiyat_kalem'):
        return False
    cols = {c[1] for c in con.execute('PRAGMA table_info(mo_musteri_sevkiyat_kalem)').fetchall()}
    return 'birim_fiyat_snapshot' in cols and 'para_birimi_snapshot' in cols


def _valid_kur(kur: Any) -> float | None:
    if kur in (None, ''):
        return None
    try:
        k = float(kur)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(k) or k <= 0:
        return None
    return k


def _kayit_try_tutari(con: sqlite3.Connection, kayit_id: int, odeme_tipi: str | None) -> float:
    """Aktif çek toplamı (CEK) veya alinan_tutar — TRY cinsinden."""
    ot = (odeme_tipi or '').upper()
    if ot == 'CEK' and _tablo_var(con, 'mo_tahsilat_cek'):
        row = con.execute(
            """
            SELECT COALESCE(SUM(tutar), 0) AS toplam
            FROM mo_tahsilat_cek
            WHERE tahsilat_kayit_id=? AND aktif=1
            """,
            (int(kayit_id),),
        ).fetchone()
        cek_top = float(row['toplam'] or 0) if row else 0.0
        if cek_top > FX_KALAN_TOLERANS:
            return round(cek_top, 2)
    row = con.execute(
        'SELECT alinan_tutar FROM mo_tahsilat_kayit WHERE id=? AND aktif=1',
        (int(kayit_id),),
    ).fetchone()
    if not row or row['alinan_tutar'] in (None, ''):
        return 0.0
    try:
        return round(float(row['alinan_tutar']), 2)
    except (TypeError, ValueError):
        return 0.0


def sevk_tahsil_kalan_hesapla(
    con: sqlite3.Connection,
    sevkiyat_id: int,
    sevk_hedef: float | None,
    sevk_pb: str | None,
    *,
    haric_kayit_id: int | None = None,
) -> dict[str, Any]:
    """
    Sevkiyat kalan — sevk PB cinsinden.
    FX sevkiyat: karsilanan_fx = try_tutar / tcmb_satis_kur_snapshot
    TRY sevkiyat: doğrudan TRY toplamı.
    """
    pb = (sevk_pb or 'TRY').upper()
    is_fx = pb in ('USD', 'EUR')
    out: dict[str, Any] = {
        'tahsil_edilen': 0.0,
        'tahsil_edilen_fx': 0.0,
        'kalan': None,
        'kalan_fx': None,
        'kalan_try': None,
        'kalan_negatif': False,
        'tahsil_tamamlandi': False,
        'onay_bekleyen_adet': 0,
        'onay_bekleyen_tahsilat': False,
        'onay_bekleyen_rezerve_try': 0.0,
        'kur_hesap_hatasi': None,
        'tcmb_satis_kur_snapshot': None,
    }
    if not _tablo_var(con, 'mo_tahsilat_kayit') or not _kolon_var(con, 'mo_tahsilat_kayit', 'sevkiyat_id'):
        return out

    ph = ','.join(['?'] * len(TAHSILAT_EDILEN_DURUMLARI))
    params: list[Any] = [int(sevkiyat_id), *sorted(TAHSILAT_EDILEN_DURUMLARI)]
    haric_sql = ''
    if haric_kayit_id:
        haric_sql = ' AND id != ?'
        params.append(int(haric_kayit_id))

    rows = con.execute(
        f"""
        SELECT id, kayit_kodu, durum, odeme_tipi, tcmb_satis_kur_snapshot
        FROM mo_tahsilat_kayit
        WHERE sevkiyat_id=? AND aktif=1
          AND durum IN ({ph}){haric_sql}
        ORDER BY id
        """,
        params,
    ).fetchall()

    tahsil_edilen_fx = 0.0
    ref_kur: float | None = None
    hedef_f = float(sevk_hedef) if sevk_hedef not in (None, '') else None

    for r in rows:
        try_t = _kayit_try_tutari(con, int(r['id']), r['odeme_tipi'])
        if (r['durum'] or '') in KAYIT_ONAY_BEKLIYOR_DURUMLARI:
            out['onay_bekleyen_adet'] += 1
            if try_t > FX_KALAN_TOLERANS:
                out['onay_bekleyen_rezerve_try'] = round(
                    float(out['onay_bekleyen_rezerve_try']) + try_t, 2,
                )
        if try_t <= FX_KALAN_TOLERANS:
            continue
        if is_fx:
            kur = _valid_kur(r['tcmb_satis_kur_snapshot'])
            if kur is None:
                kod = r['kayit_kodu'] or str(r['id'])
                out['kur_hesap_hatasi'] = (
                    f'{kod}: tcmb_satis_kur_snapshot geçersiz (FX kalan hesaplanamadı).'
                )
                return out
            payment_fx = try_t / kur
            ref_kur = kur
        else:
            payment_fx = try_t
        if hedef_f is not None:
            remaining = max(hedef_f - tahsil_edilen_fx, 0.0)
            allocated_fx = min(payment_fx, remaining)
        else:
            allocated_fx = payment_fx
        tahsil_edilen_fx += allocated_fx

    tahsil_edilen_fx = round(tahsil_edilen_fx, 6)
    out['tahsil_edilen_fx'] = tahsil_edilen_fx
    out['tahsil_edilen'] = round(tahsil_edilen_fx, 2)
    out['onay_bekleyen_tahsilat'] = out['onay_bekleyen_adet'] > 0
    out['tcmb_satis_kur_snapshot'] = ref_kur

    if sevk_hedef is None:
        return out

    kalan_fx = round(max(float(sevk_hedef) - tahsil_edilen_fx, 0.0), 6)
    out['kalan_fx'] = kalan_fx
    out['kalan'] = kalan_fx
    out['tahsil_tamamlandi'] = tahsil_edilen_fx >= float(sevk_hedef) - FX_KALAN_TOLERANS
    out['kalan_negatif'] = False

    if is_fx and ref_kur is not None:
        out['kalan_try'] = round(max(kalan_fx, 0.0) * ref_kur, 2)

    return out


def _siparis_miktar_kg(con: sqlite3.Connection, siparis_id: int) -> float | None:
    """Sipariş toplam miktarı — plan kalem / MO payload / sevk toplamı (canonical sıra)."""
    sid = int(siparis_id)
    if _tablo_var(con, 'nexgen_planlama_siparis_kalem'):
        cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis_kalem)').fetchall()}
        fk_col = None
        if 'planlama_siparis_id' in cols:
            fk_col = 'planlama_siparis_id'
        elif 'siparis_id' in cols:
            fk_col = 'siparis_id'
        if fk_col and {'miktar_l', 'miktar_s', 'miktar_m'}.issubset(cols):
            row = con.execute(
                f"""
                SELECT COALESCE(SUM(
                    COALESCE(miktar_l, 0) + COALESCE(miktar_s, 0) + COALESCE(miktar_m, 0)
                ), 0) AS t
                FROM nexgen_planlama_siparis_kalem
                WHERE {fk_col}=?
                """,
                (sid,),
            ).fetchone()
            if row and float(row['t'] or 0) > 0:
                return round(float(row['t']), 3)
    if _tablo_var(con, 'nexgen_planlama_siparis'):
        row = con.execute(
            'SELECT talep_referansi FROM nexgen_planlama_siparis WHERE id=?',
            (sid,),
        ).fetchone()
        if row and row['talep_referansi']:
            try:
                from modules.nexgen.mo_siparis_payload import mo_siparis_payload_unpack
                mo = mo_siparis_payload_unpack(row['talep_referansi']) or {}
                m = mo.get('miktar')
                if m not in (None, ''):
                    return round(float(m), 3)
            except (TypeError, ValueError):
                pass
    if _tablo_var(con, 'mo_musteri_sevkiyat') and _tablo_var(con, 'mo_musteri_sevkiyat_kalem'):
        row = con.execute(
            """
            SELECT COALESCE(SUM(k.miktar_kg), 0) AS t
            FROM mo_musteri_sevkiyat_kalem k
            JOIN mo_musteri_sevkiyat s ON s.id = k.sevkiyat_id AND s.aktif = 1
            WHERE s.siparis_id=?
            """,
            (sid,),
        ).fetchone()
        if row and float(row['t'] or 0) > 0:
            return round(float(row['t']), 3)
    return None


def _sevk_hesap_ozet(
    *,
    sevk_kg: float | None,
    birim_fiyat: float | None,
    para_birimi: str | None,
    sevk_tutar: float | None,
) -> str | None:
    if sevk_kg in (None, '') or birim_fiyat in (None, '') or sevk_tutar is None:
        return None
    pb = (para_birimi or 'TRY').upper()
    return f'{sevk_kg:g} kg × {birim_fiyat:g} {pb}/kg = {sevk_tutar:g} {pb}'


def sevk_hedef_hesapla(con: sqlite3.Connection, sevkiyat_id: int) -> dict[str, Any]:
    """
    Sevk hedef tutarı: SUM(miktar_kg × birim_fiyat_snapshot).
    Dönüş: sevk_hedef_tutar, para_birimi, eksik_fiyat (bool), toplam_kg
    """
    out: dict[str, Any] = {
        'sevk_hedef_tutar': None,
        'para_birimi': None,
        'eksik_fiyat': True,
        'toplam_kg': 0.0,
        'birim_fiyat_snapshot': None,
        'birim_fiyat_coklu': False,
        'sevk_hesap_ozet': None,
    }
    if not _tablo_var(con, 'mo_musteri_sevkiyat_kalem'):
        return out
    snap = _sevk_snapshot_kolonlari_var(con)
    snap_sel = ', birim_fiyat_snapshot, para_birimi_snapshot' if snap else ''
    rows = con.execute(
        f"""
        SELECT miktar_kg{snap_sel}
        FROM mo_musteri_sevkiyat_kalem
        WHERE sevkiyat_id=?
        ORDER BY id
        """,
        (int(sevkiyat_id),),
    ).fetchall()
    if not rows:
        return out

    toplam_kg = 0.0
    hedef = 0.0
    pb: str | None = None
    eksik = False
    fiyatlar: set[float] = set()

    for r in rows:
        kg = float(r['miktar_kg'] or 0)
        toplam_kg += kg
        if not snap:
            eksik = True
            continue
        bf = r['birim_fiyat_snapshot']
        row_pb = (r['para_birimi_snapshot'] or '').strip().upper() or None
        if bf in (None, '') or kg <= 0:
            if kg > 0:
                eksik = True
            continue
        try:
            fiyat = float(bf)
        except (TypeError, ValueError):
            eksik = True
            continue
        if row_pb:
            if pb and row_pb != pb:
                eksik = True
            pb = pb or row_pb
        fiyatlar.add(round(fiyat, 4))
        hedef += kg * fiyat

    out['toplam_kg'] = round(toplam_kg, 3)
    if eksik or toplam_kg <= 0:
        out['eksik_fiyat'] = True
        return out

    out['sevk_hedef_tutar'] = round(hedef, 2)
    out['para_birimi'] = pb or 'TRY'
    out['eksik_fiyat'] = False
    if len(fiyatlar) == 1:
        out['birim_fiyat_snapshot'] = float(next(iter(fiyatlar)))
    else:
        out['birim_fiyat_coklu'] = True
    out['sevk_hesap_ozet'] = _sevk_hesap_ozet(
        sevk_kg=out['toplam_kg'],
        birim_fiyat=out.get('birim_fiyat_snapshot'),
        para_birimi=out['para_birimi'],
        sevk_tutar=out['sevk_hedef_tutar'],
    )
    return out


def tahsil_edilen_sevk(con: sqlite3.Connection, sevkiyat_id: int) -> float:
    """Sevkiyat PB cinsinden tahsil edilen / rezerve FX miktarı."""
    hedef_info = sevk_hedef_hesapla(con, sevkiyat_id)
    info = sevk_tahsil_kalan_hesapla(
        con,
        sevkiyat_id,
        hedef_info.get('sevk_hedef_tutar'),
        hedef_info.get('para_birimi'),
    )
    if info.get('kur_hesap_hatasi'):
        return 0.0
    return float(info.get('tahsil_edilen_fx') or 0.0)


def _kalan_hesapla(sevk_hedef: float | None, tahsil_edilen: float) -> dict[str, Any]:
    if sevk_hedef is None:
        return {'kalan': None, 'kalan_negatif': False}
    kalan = round(float(sevk_hedef) - float(tahsil_edilen), 6)
    return {
        'kalan': kalan,
        'kalan_negatif': kalan < -FX_KALAN_TOLERANS,
    }


def _secilebilir_mi(item: dict[str, Any]) -> bool:
    if not item.get('tahsilata_uygun'):
        return False
    if item.get('kur_hesap_hatasi'):
        return False
    kalan = item.get('kalan_fx')
    if kalan is None:
        return False
    return float(kalan) > FX_KALAN_TOLERANS


def tahsilat_sevk_adaylari(con: sqlite3.Connection, siparis_id: int) -> list[dict[str, Any]]:
    """Siparişe bağlı tahsilata uygun sevkiyat adayları + kalan hesabı."""
    if not _tablo_var(con, 'mo_musteri_sevkiyat'):
        return []
    sid = int(siparis_id)
    rows = con.execute(
        """
        SELECT id, sevkiyat_no, sevk_tarihi, durum
        FROM mo_musteri_sevkiyat
        WHERE siparis_id=? AND aktif=1
          AND durum IN ('SEVK_EDILDI','TESLIM_EDILDI','TAMAMLANDI')
        ORDER BY COALESCE(sevk_tarihi, olusturma_tarihi), id
        """,
        (sid,),
    ).fetchall()

    out: list[dict[str, Any]] = []
    siparis_miktar = _siparis_miktar_kg(con, sid)
    for r in rows:
        sevkiyat_id = int(r['id'])
        hedef_info = sevk_hedef_hesapla(con, sevkiyat_id)
        kalan_info = sevk_tahsil_kalan_hesapla(
            con,
            sevkiyat_id,
            hedef_info.get('sevk_hedef_tutar'),
            hedef_info.get('para_birimi'),
        )

        tahsilat_uygun = not hedef_info.get('eksik_fiyat')
        durum_etiket = (r['durum'] or '').upper()
        if hedef_info.get('eksik_fiyat'):
            durum_etiket = 'EKSIK_FIYAT'

        item: dict[str, Any] = {
            'sevkiyat_id': sevkiyat_id,
            'sevk_no': r['sevkiyat_no'],
            'sevk_tarihi': (r['sevk_tarihi'] or '')[:10] or None,
            'toplam_kg': hedef_info.get('toplam_kg'),
            'siparis_miktar_kg': siparis_miktar,
            'birim_fiyat_snapshot': hedef_info.get('birim_fiyat_snapshot'),
            'birim_fiyat_coklu': hedef_info.get('birim_fiyat_coklu', False),
            'sevk_hesap_ozet': hedef_info.get('sevk_hesap_ozet'),
            'sevk_hedef_tutar': hedef_info.get('sevk_hedef_tutar'),
            'para_birimi': hedef_info.get('para_birimi'),
            'tahsil_edilen': kalan_info.get('tahsil_edilen'),
            'tahsil_edilen_fx': kalan_info.get('tahsil_edilen_fx'),
            'kalan': kalan_info.get('kalan_fx'),
            'kalan_fx': kalan_info.get('kalan_fx'),
            'kalan_try': kalan_info.get('kalan_try'),
            'kalan_negatif': kalan_info.get('kalan_negatif', False),
            'tahsil_tamamlandi': kalan_info.get('tahsil_tamamlandi', False),
            'onay_bekleyen_adet': kalan_info.get('onay_bekleyen_adet', 0),
            'onay_bekleyen_tahsilat': kalan_info.get('onay_bekleyen_tahsilat', False),
            'onay_bekleyen_rezerve_try': kalan_info.get('onay_bekleyen_rezerve_try', 0.0),
            'kur_hesap_hatasi': kalan_info.get('kur_hesap_hatasi'),
            'tcmb_satis_kur_snapshot': kalan_info.get('tcmb_satis_kur_snapshot'),
            'durum': durum_etiket,
            'sevk_durum': (r['durum'] or '').upper(),
            'tahsilata_uygun': tahsilat_uygun,
        }
        item['secilebilir'] = _secilebilir_mi(item)
        out.append(item)
    return out


def tahsilat_sevk_write_guard(
    con: sqlite3.Connection,
    *,
    cari_id: int,
    siparis_id: int,
    sevkiyat_id: int,
) -> dict[str, Any]:
    """
    Sevkiyat tahsilat yazım ön kontrolü — V1 Faz 1 helper.
    taslak_kaydet / onaya_gonder henüz bağlanmadı.
    """
    if not _tablo_var(con, 'mo_musteri_sevkiyat'):
        raise MoTahsilatError('Sevkiyat tablosu yok.', 503)
    row = con.execute(
        """
        SELECT id, cari_id, siparis_id, durum, aktif
        FROM mo_musteri_sevkiyat WHERE id=?
        """,
        (int(sevkiyat_id),),
    ).fetchone()
    if not row or not int(row['aktif'] or 0):
        raise MoTahsilatError('Sevkiyat bulunamadı.', 404)
    if int(row['cari_id'] or 0) != int(cari_id):
        raise MoTahsilatError('Sevkiyat müşteri uyuşmuyor.', 400)
    if int(row['siparis_id'] or 0) != int(siparis_id):
        raise MoTahsilatError('Sevkiyat sipariş uyuşmuyor.', 400)
    durum = (row['durum'] or '').upper()
    if durum not in SEVK_TAHSILAT_DURUMLARI:
        raise MoTahsilatError(f'Sevkiyat tahsilata uygun durumda değil ({durum}).', 409)

    adaylar = {a['sevkiyat_id']: a for a in tahsilat_sevk_adaylari(con, siparis_id)}
    aday = adaylar.get(int(sevkiyat_id))
    if not aday:
        raise MoTahsilatError('Sevkiyat tahsilat aday listesinde yok.', 404)
    if aday.get('kur_hesap_hatasi'):
        raise MoTahsilatError(str(aday['kur_hesap_hatasi']), 409)
    if not aday.get('tahsilata_uygun'):
        raise MoTahsilatError('Sevkiyat fiyat snapshot eksik (EKSIK_FIYAT).', 409)
    _raw_kalan = aday.get('kalan_fx')
    if _raw_kalan is None:
        _raw_kalan = aday.get('kalan')
    try:
        kalan = float(_raw_kalan) if _raw_kalan is not None else 0.0
    except (TypeError, ValueError):
        raise MoTahsilatError('Sevkiyat tahsilat kalan tutarı hesaplanamadı.', 409)
    tamamlandi = bool(aday.get('tahsil_tamamlandi'))
    if tamamlandi or kalan <= FX_KALAN_TOLERANS:
        raise MoTahsilatError(
            'Bu sevkiyat için tahsilat tamamlanmış; yeni kayıt oluşturulamaz.',
            409,
        )
    return aday
