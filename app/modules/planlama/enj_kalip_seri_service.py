# -*- coding: utf-8 -*-
"""Kalıp seri/grup master — CRUD ve read-only sorgular."""
from __future__ import annotations

import sqlite3
from typing import Any

UYE_ROLLERI = frozenset({'GOVDE', 'ATKI', 'DIGER'})


class KalipSeriError(ValueError):
    """İş kuralı ihlali — transaction rollback beklenir."""


def _norm_kod(val: str | None) -> str:
    return (val or '').strip().upper()


def _norm_model(val: str | None) -> str:
    return (val or '').strip().upper()


def _row_dict(row) -> dict | None:
    if row is None:
        return None
    return dict(row)


def _kalip_public_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    d['kapasite_onayli'] = bool(d.get('kapasite_onayli'))
    return d


def list_seri(
    con: sqlite3.Connection,
    *,
    model_kod: str | None = None,
    aktif_only: bool = True,
) -> list[dict]:
    q = f"""
        SELECT s.*,
               (SELECT COUNT(*) FROM enj_kalip_seri_uye u
                 WHERE u.seri_id = s.id AND u.aktif = 1) AS uye_sayisi
        FROM enj_kalip_seri s
        WHERE 1=1
    """
    params: list[Any] = []
    if aktif_only:
        q += ' AND s.aktif = 1'
    if model_kod:
        q += ' AND TRIM(UPPER(s.model_kod)) = ?'
        params.append(_norm_model(model_kod))
    q += ' ORDER BY s.seri_kod'
    return [dict(r) for r in con.execute(q, params).fetchall()]


def get_seri_detail(con: sqlite3.Connection, seri_id: int, *, aktif_uyeler_only: bool = False) -> dict | None:
    seri = _row_dict(con.execute(
        'SELECT * FROM enj_kalip_seri WHERE id = ?', (int(seri_id),),
    ).fetchone())
    if not seri:
        return None
    uye_q = """
        SELECT u.*,
               k.kalip_kod, k.kalip_tipi, k.model_kod, k.model_ad, k.asorti,
               k.kalip_basi_cift, k.aktif_goz_sayisi, k.kapasite_cift,
               k.kapasite_onayli, k.varsayilan_bagli_kalip, k.aktif AS kalip_aktif
        FROM enj_kalip_seri_uye u
        JOIN enj_kalip k ON k.id = u.kalip_id
        WHERE u.seri_id = ?
    """
    params: list[Any] = [int(seri_id)]
    if aktif_uyeler_only:
        uye_q += ' AND u.aktif = 1 AND k.aktif = 1'
    uye_q += ' ORDER BY COALESCE(u.sira_no, 9999), u.id'
    uyeler = [_kalip_public_row(r) for r in con.execute(uye_q, params).fetchall()]
    seri['uyeler'] = uyeler
    return seri


def create_seri(
    con: sqlite3.Connection,
    payload: dict,
    *,
    user_id: int | None = None,
) -> dict:
    seri_kod = (payload.get('seri_kod') or '').strip()
    model_kod = (payload.get('model_kod') or '').strip()
    if not seri_kod:
        raise KalipSeriError('seri_kod zorunlu')
    if not model_kod:
        raise KalipSeriError('model_kod zorunlu')

    dup = con.execute(
        'SELECT id FROM enj_kalip_seri WHERE seri_kod = ? COLLATE NOCASE', (seri_kod,),
    ).fetchone()
    if dup:
        raise KalipSeriError(f'Seri kodu zaten mevcut: {seri_kod}')

    seri_ad = (payload.get('seri_ad') or '').strip() or None
    model_ad = (payload.get('model_ad') or '').strip() or None
    aciklama = (payload.get('aciklama') or '').strip() or None
    aktif = 0 if payload.get('aktif') in (0, '0', False) else 1

    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO enj_kalip_seri
        (seri_kod, seri_ad, model_kod, model_ad, aciklama, aktif, created_by, updated_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (seri_kod, seri_ad, model_kod, model_ad, aciklama, aktif, user_id, user_id),
    )
    seri_id = cur.lastrowid
    detail = get_seri_detail(con, int(seri_id))
    assert detail is not None
    return detail


def update_seri(
    con: sqlite3.Connection,
    seri_id: int,
    payload: dict,
    *,
    user_id: int | None = None,
) -> dict:
    seri = _row_dict(con.execute(
        'SELECT * FROM enj_kalip_seri WHERE id = ?', (int(seri_id),),
    ).fetchone())
    if not seri:
        raise KalipSeriError('Seri bulunamadı')

    guncel: dict[str, Any] = {}
    if 'seri_kod' in payload:
        yeni_kod = (payload.get('seri_kod') or '').strip()
        if not yeni_kod:
            raise KalipSeriError('seri_kod boş olamaz')
        if yeni_kod.lower() != (seri['seri_kod'] or '').lower():
            dup = con.execute(
                'SELECT id FROM enj_kalip_seri WHERE seri_kod = ? COLLATE NOCASE AND id <> ?',
                (yeni_kod, seri_id),
            ).fetchone()
            if dup:
                raise KalipSeriError(f'Seri kodu zaten mevcut: {yeni_kod}')
        guncel['seri_kod'] = yeni_kod

    if 'seri_ad' in payload:
        guncel['seri_ad'] = (payload.get('seri_ad') or '').strip() or None
    if 'model_ad' in payload:
        guncel['model_ad'] = (payload.get('model_ad') or '').strip() or None
    if 'aciklama' in payload:
        guncel['aciklama'] = (payload.get('aciklama') or '').strip() or None
    if 'aktif' in payload:
        guncel['aktif'] = 0 if payload.get('aktif') in (0, '0', False) else 1

    if 'model_kod' in payload:
        yeni_model = (payload.get('model_kod') or '').strip()
        if not yeni_model:
            raise KalipSeriError('model_kod boş olamaz')
        if _norm_model(yeni_model) != _norm_model(seri['model_kod']):
            uyumsuz = con.execute(
                """
                SELECT u.id FROM enj_kalip_seri_uye u
                JOIN enj_kalip k ON k.id = u.kalip_id
                WHERE u.seri_id = ? AND u.aktif = 1
                  AND TRIM(UPPER(k.model_kod)) <> TRIM(UPPER(?))
                LIMIT 1
                """,
                (seri_id, yeni_model),
            ).fetchone()
            if uyumsuz:
                raise KalipSeriError(
                    'Model kodu değiştirilemez: mevcut aktif üyeler yeni model ile uyumsuz'
                )
        guncel['model_kod'] = yeni_model

    if not guncel:
        raise KalipSeriError('Güncellenecek alan yok')

    guncel['updated_by'] = user_id
    set_parts = [f'{k} = ?' for k in guncel]
    set_parts.append("updated_at = datetime('now', 'localtime')")
    params = list(guncel.values()) + [seri_id]
    con.execute(
        f'UPDATE enj_kalip_seri SET {", ".join(set_parts)} WHERE id = ?',
        params,
    )
    detail = get_seri_detail(con, int(seri_id))
    assert detail is not None
    return detail


def _validate_kalip_for_seri(con: sqlite3.Connection, seri: dict, kalip_id: int) -> sqlite3.Row:
    kalip = con.execute(
        'SELECT * FROM enj_kalip WHERE id = ?', (int(kalip_id),),
    ).fetchone()
    if not kalip:
        raise KalipSeriError('Kalıp bulunamadı')
    if not int(kalip['aktif'] or 0):
        raise KalipSeriError('Pasif kalıp seriye eklenemez')
    if _norm_model(kalip['model_kod']) != _norm_model(seri['model_kod']):
        raise KalipSeriError(
            f'Kalıp modeli ({kalip["model_kod"]}) seri modeli ({seri["model_kod"]}) ile uyuşmuyor'
        )
    return kalip


def add_uye(
    con: sqlite3.Connection,
    seri_id: int,
    payload: dict,
    *,
    user_id: int | None = None,
) -> dict:
    seri = _row_dict(con.execute(
        'SELECT * FROM enj_kalip_seri WHERE id = ?', (int(seri_id),),
    ).fetchone())
    if not seri:
        raise KalipSeriError('Seri bulunamadı')

    kalip_id = payload.get('kalip_id')
    if not kalip_id:
        raise KalipSeriError('kalip_id zorunlu')
    _validate_kalip_for_seri(con, seri, int(kalip_id))

    dup = con.execute(
        'SELECT id, aktif FROM enj_kalip_seri_uye WHERE seri_id = ? AND kalip_id = ?',
        (seri_id, int(kalip_id)),
    ).fetchone()
    if dup:
        raise KalipSeriError('Bu kalıp zaten seriye ekli')

    uye_rolu = (payload.get('uye_rolu') or 'DIGER').strip().upper()
    if uye_rolu not in UYE_ROLLERI:
        raise KalipSeriError('uye_rolu GOVDE, ATKI veya DIGER olmalı')

    beden_numara = (payload.get('beden_numara') or '').strip() or None
    sira_no = payload.get('sira_no')
    if sira_no is not None and sira_no != '':
        sira_no = int(sira_no)
        if sira_no <= 0:
            raise KalipSeriError('sira_no pozitif olmalı')
    else:
        sira_no = None

    vfa = payload.get('varsayilan_fiziksel_adet')
    if vfa is not None and vfa != '':
        vfa = int(vfa)
        if vfa <= 0:
            raise KalipSeriError('varsayilan_fiziksel_adet pozitif olmalı')
    else:
        vfa = None

    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO enj_kalip_seri_uye
        (seri_id, kalip_id, uye_rolu, beden_numara, sira_no,
         varsayilan_fiziksel_adet, aktif, created_by, updated_by)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (seri_id, int(kalip_id), uye_rolu, beden_numara, sira_no, vfa, user_id, user_id),
    )
    uye_id = cur.lastrowid
    row = con.execute(
        """
        SELECT u.*,
               k.kalip_kod, k.kalip_tipi, k.model_kod, k.model_ad, k.asorti,
               k.kalip_basi_cift, k.aktif_goz_sayisi, k.kapasite_cift,
               k.kapasite_onayli, k.varsayilan_bagli_kalip, k.aktif AS kalip_aktif
        FROM enj_kalip_seri_uye u
        JOIN enj_kalip k ON k.id = u.kalip_id
        WHERE u.id = ?
        """,
        (uye_id,),
    ).fetchone()
    return _kalip_public_row(row)


def update_uye(
    con: sqlite3.Connection,
    uye_id: int,
    payload: dict,
    *,
    user_id: int | None = None,
) -> dict:
    uye = _row_dict(con.execute(
        'SELECT * FROM enj_kalip_seri_uye WHERE id = ?', (int(uye_id),),
    ).fetchone())
    if not uye:
        raise KalipSeriError('Seri üyesi bulunamadı')

    guncel: dict[str, Any] = {}
    if 'uye_rolu' in payload:
        rol = (payload.get('uye_rolu') or '').strip().upper()
        if rol not in UYE_ROLLERI:
            raise KalipSeriError('uye_rolu GOVDE, ATKI veya DIGER olmalı')
        guncel['uye_rolu'] = rol
    if 'beden_numara' in payload:
        guncel['beden_numara'] = (payload.get('beden_numara') or '').strip() or None
    if 'sira_no' in payload:
        sn = payload.get('sira_no')
        if sn is None or sn == '':
            guncel['sira_no'] = None
        else:
            sn = int(sn)
            if sn <= 0:
                raise KalipSeriError('sira_no pozitif olmalı')
            guncel['sira_no'] = sn
    if 'varsayilan_fiziksel_adet' in payload:
        vfa = payload.get('varsayilan_fiziksel_adet')
        if vfa is None or vfa == '':
            guncel['varsayilan_fiziksel_adet'] = None
        else:
            vfa = int(vfa)
            if vfa <= 0:
                raise KalipSeriError('varsayilan_fiziksel_adet pozitif olmalı')
            guncel['varsayilan_fiziksel_adet'] = vfa
    if 'aktif' in payload:
        guncel['aktif'] = 0 if payload.get('aktif') in (0, '0', False) else 1

    if not guncel:
        raise KalipSeriError('Güncellenecek alan yok')

    guncel['updated_by'] = user_id
    set_parts = [f'{k} = ?' for k in guncel]
    set_parts.append("updated_at = datetime('now', 'localtime')")
    params = list(guncel.values()) + [uye_id]
    con.execute(
        f'UPDATE enj_kalip_seri_uye SET {", ".join(set_parts)} WHERE id = ?',
        params,
    )
    row = con.execute(
        """
        SELECT u.*,
               k.kalip_kod, k.kalip_tipi, k.model_kod, k.model_ad, k.asorti,
               k.kalip_basi_cift, k.aktif_goz_sayisi, k.kapasite_cift,
               k.kapasite_onayli, k.varsayilan_bagli_kalip, k.aktif AS kalip_aktif
        FROM enj_kalip_seri_uye u
        JOIN enj_kalip k ON k.id = u.kalip_id
        WHERE u.id = ?
        """,
        (uye_id,),
    ).fetchone()
    return _kalip_public_row(row)


def read_series_for_model(con: sqlite3.Connection, model_kod: str) -> list[dict]:
    """Planlama read-only — aktif seriler + aktif üyeler."""
    norm = _norm_model(model_kod)
    if not norm:
        return []
    seriler = list_seri(con, model_kod=norm, aktif_only=True)
    out: list[dict] = []
    for s in seriler:
        detail = get_seri_detail(con, int(s['id']), aktif_uyeler_only=True)
        if not detail:
            continue
        uyeler = []
        for u in detail.get('uyeler') or []:
            uyeler.append({
                'kalip_id': u['kalip_id'],
                'kalip_kod': u['kalip_kod'],
                'uye_rolu': u['uye_rolu'],
                'beden_numara': u.get('beden_numara'),
                'sira_no': u.get('sira_no'),
                'kalip_basi_cift': u.get('kalip_basi_cift'),
                'aktif_goz_sayisi': u.get('aktif_goz_sayisi'),
                'varsayilan_fiziksel_adet': u.get('varsayilan_fiziksel_adet'),
                'kapasite_onayli': bool(u.get('kapasite_onayli')),
                'kalip_tipi': u.get('kalip_tipi'),
                'asorti': u.get('asorti'),
            })
        out.append({
            'seri': {
                'id': detail['id'],
                'seri_kod': detail['seri_kod'],
                'seri_ad': detail.get('seri_ad'),
                'model_kod': detail['model_kod'],
                'model_ad': detail.get('model_ad'),
                'aktif': bool(detail.get('aktif')),
            },
            'uyeler': uyeler,
        })
    return out
