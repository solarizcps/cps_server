# -*- coding: utf-8 -*-
"""Tedarikci Cari Koprusu — eslestirme servisi (FAZ-F1-2)."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from modules.nexgen.finans_cari_kimlik_service import (
    FinansCariKimlikError,
    ESLESTIRME_DOGRULANMIS,
    _cari_kart,
    _ckod_cakisma,
    _kimlik_by_tedarikci,
    _kimlik_row,
    _resolve_paket,
    _touch,
    tablo_var,
    validate_ctip_for_kimlik,
)

ESLESTIRME_DURUMLARI = ('BEKLIYOR', 'DOGRULANDI', 'MANUEL', 'IPTAL')
ESLESTIRME_YONTEMLERI = ('CARI_KODU', 'ERP_KODU', 'VERGI_NO', 'MANUEL')


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def _ensure_table(con: sqlite3.Connection) -> None:
    if not tablo_var(con, 'tedarikci_eslestirme'):
        raise FinansCariKimlikError(
            'tedarikci_eslestirme tablosu yok — migration 131 gerekli.',
            code='MIGRATION_131',
            http_status=503,
        )


def get_tedarikci_eslestirme(
    con: sqlite3.Connection,
    nexgen_tedarikci_id: int,
) -> dict[str, Any] | None:
    _ensure_table(con)
    es = _row(con.execute(
        """
        SELECT * FROM tedarikci_eslestirme
        WHERE nexgen_tedarikci_id=?
        ORDER BY id DESC LIMIT 1
        """,
        (int(nexgen_tedarikci_id),),
    ).fetchone())
    if not es:
        return None
    ck = _cari_kart(con, es.get('cari_kart_ckod'))
    ctip = validate_ctip_for_kimlik(ck, 'TEDARIKCI') if ck else None
    return {
        **es,
        'cari_kart_unvan': ck['CName'] if ck else None,
        'ctip_raw': ctip['ctip_raw'] if ctip else None,
        'ctip_normalized': ctip['ctip_normalized'] if ctip else [],
        'ctip_uygun': bool(ctip and ctip.get('uygun')),
    }


def validate_tedarikci_eslestirme(
    con: sqlite3.Connection,
    nexgen_tedarikci_id: int,
    cari_kart_ckod: str,
    *,
    manuel_override: bool = False,
    manuel_not: str | None = None,
) -> dict[str, Any]:
    _ensure_table(con)
    nt = _row(con.execute(
        'SELECT id, aktif FROM nexgen_tedarikci WHERE id=?',
        (int(nexgen_tedarikci_id),),
    ).fetchone())
    if not nt:
        raise FinansCariKimlikError('nexgen_tedarikci bulunamadi.', code='NEXGEN_TEDARIKCI_YOK', http_status=404)
    if not int(nt.get('aktif') or 0):
        raise FinansCariKimlikError('nexgen_tedarikci pasif.', code='OPERASYONEL_PASIF', http_status=409)

    ck = _cari_kart(con, cari_kart_ckod)
    if not ck:
        raise FinansCariKimlikError('Cari_Kart bulunamadi.', code='CARI_KART_YOK', http_status=404)

    ctip = validate_ctip_for_kimlik(
        ck, 'TEDARIKCI',
        manuel_override=manuel_override,
        manuel_not=manuel_not,
    )
    if not ctip['uygun']:
        raise FinansCariKimlikError(
            ctip.get('uyari') or 'CTip uyumsuz.',
            code=ctip.get('blok_kodu') or 'CTIP_UYUMSUZ',
            http_status=409,
            details=ctip,
        )

    mevcut_ted = con.execute(
        """
        SELECT id, nexgen_tedarikci_id FROM tedarikci_eslestirme
        WHERE cari_kart_ckod=? AND aktif=1 AND nexgen_tedarikci_id!=?
        """,
        (cari_kart_ckod, int(nexgen_tedarikci_id)),
    ).fetchone()
    if mevcut_ted:
        raise FinansCariKimlikError(
            'CKod baska aktif tedarikci eslestirmesinde.',
            code='CKOD_CAKISMA',
            http_status=409,
            details={'diger_eslestirme_id': mevcut_ted['id']},
        )

    cakisma = _ckod_cakisma(con, cari_kart_ckod, 'TEDARIKCI')
    if cakisma:
        raise FinansCariKimlikError(
            'CKod baska aktif TEDARIKCI kimliginde.',
            code='CKOD_CAKISMA',
            http_status=409,
            details={'kimlik_id': cakisma['id']},
        )

    return {
        'uygun': True,
        'ctip': ctip,
        'durum_onerisi': ctip.get('durum_onerisi') or 'DOGRULANDI',
    }


def create_or_update_tedarikci_eslestirme(
    con: sqlite3.Connection,
    nexgen_tedarikci_id: int,
    cari_kart_ckod: str,
    *,
    eslestirme_yontemi: str = 'MANUEL',
    eslestirme_durumu: str | None = None,
    user_id: int | None = None,
    manuel_override: bool = False,
    manuel_not: str | None = None,
    notlar: str | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    _ensure_table(con)
    dogrulama = validate_tedarikci_eslestirme(
        con, nexgen_tedarikci_id, cari_kart_ckod,
        manuel_override=manuel_override,
        manuel_not=manuel_not,
    )
    durum = eslestirme_durumu or dogrulama['durum_onerisi']
    if durum not in ESLESTIRME_DURUMLARI:
        durum = 'DOGRULANDI'

    mevcut = _row(con.execute(
        'SELECT * FROM tedarikci_eslestirme WHERE nexgen_tedarikci_id=?',
        (int(nexgen_tedarikci_id),),
    ).fetchone())

    now = _now()
    if mevcut:
        con.execute(
            """
            UPDATE tedarikci_eslestirme
            SET cari_kart_ckod=?, eslestirme_durumu=?, eslestirme_yontemi=?,
                aktif=1, notlar=?, eslestiren_id=?, eslestirme_tarihi=?,
                updated_at=?
            WHERE id=?
            """,
            (
                cari_kart_ckod, durum, eslestirme_yontemi,
                notlar, user_id, now, now, mevcut['id'],
            ),
        )
        es_id = int(mevcut['id'])
        idempotent = (
            mevcut.get('cari_kart_ckod') == cari_kart_ckod
            and mevcut.get('eslestirme_durumu') == durum
        )
    else:
        cur = con.execute(
            """
            INSERT INTO tedarikci_eslestirme
                (nexgen_tedarikci_id, cari_kart_ckod, eslestirme_durumu,
                 eslestirme_yontemi, aktif, notlar, eslestiren_id,
                 eslestirme_tarihi, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (
                int(nexgen_tedarikci_id), cari_kart_ckod, durum,
                eslestirme_yontemi, notlar, user_id, now, now, now,
            ),
        )
        es_id = int(cur.lastrowid)
        idempotent = False

    if commit:
        con.commit()
    paket = get_tedarikci_eslestirme(con, nexgen_tedarikci_id)
    assert paket
    paket['idempotent'] = idempotent
    paket['eslestirme_id'] = es_id
    return paket


def sync_tedarikci_kimlik_ckod(
    con: sqlite3.Connection,
    kimlik_id: int,
    *,
    user_id: int | None = None,
    manuel_override: bool = False,
    manuel_not: str | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    from modules.nexgen.finans_cari_kimlik_service import tablo_var as kimlik_tablo

    if not kimlik_tablo(con, 'finans_cari_kimlik'):
        raise FinansCariKimlikError('finans_cari_kimlik yok.', code='MIGRATION_131', http_status=503)

    kimlik = _kimlik_row(con, kimlik_id)
    if not kimlik:
        raise FinansCariKimlikError('Kimlik bulunamadi.', code='KIMLIK_BULUNAMADI', http_status=404)
    if kimlik['kimlik_tipi'] != 'TEDARIKCI':
        raise FinansCariKimlikError(
            'Yalnizca TEDARIKCI kimligi sync edilebilir.',
            code='KIMLIK_TIP_UYUMSUZ',
            http_status=409,
        )

    es = get_tedarikci_eslestirme(con, kimlik['nexgen_tedarikci_id'])
    if not es or not int(es.get('aktif') or 0):
        raise FinansCariKimlikError(
            'Aktif tedarikci eslestirme bulunamadi.',
            code='ESLESME_BEKLIYOR',
            http_status=409,
        )
    if es.get('eslestirme_durumu') not in ESLESTIRME_DOGRULANMIS:
        raise FinansCariKimlikError(
            'Eslestirme DOGRULANDI veya MANUEL olmali.',
            code='ESLESME_BEKLIYOR',
            http_status=409,
        )

    ckod = es.get('cari_kart_ckod')
    if not ckod:
        raise FinansCariKimlikError('Eslestirmede CKod yok.', code='CKOD_YOK', http_status=409)

    validate_tedarikci_eslestirme(
        con, kimlik['nexgen_tedarikci_id'], ckod,
        manuel_override=manuel_override,
        manuel_not=manuel_not,
    )

    cakisma = _ckod_cakisma(con, ckod, 'TEDARIKCI', exclude_id=kimlik_id)
    if cakisma:
        raise FinansCariKimlikError(
            'CKod baska aktif TEDARIKCI kimliginde.',
            code='CKOD_CAKISMA',
            http_status=409,
        )

    ck = _cari_kart(con, ckod)
    ctip = validate_ctip_for_kimlik(
        ck, 'TEDARIKCI',
        manuel_override=manuel_override,
        manuel_not=manuel_not,
    )
    yeni_durum = ctip.get('durum_onerisi') or 'DOGRULANDI'
    notlar = kimlik.get('notlar')
    if manuel_override and manuel_not:
        ek = f'[MANUEL_OVERRIDE sync] {manuel_not.strip()}'
        notlar = f'{notlar}\n{ek}'.strip() if notlar else ek

    _touch(
        con, kimlik_id,
        user_id=user_id,
        cari_kart_ckod=ckod,
        durum=yeni_durum,
        notlar=notlar,
    )
    if commit:
        con.commit()
    return _resolve_paket(con, _kimlik_row(con, kimlik_id) or kimlik)


def dogrula_tedarikci_eslestirme(
    con: sqlite3.Connection,
    nexgen_tedarikci_id: int,
    *,
    user_id: int | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    _ensure_table(con)
    es = get_tedarikci_eslestirme(con, nexgen_tedarikci_id)
    if not es or not int(es.get('aktif') or 0):
        raise FinansCariKimlikError(
            'Aktif tedarikci eslestirme yok.',
            code='ESLESME_BEKLIYOR',
            http_status=404,
        )
    ckod = es.get('cari_kart_ckod')
    if not ckod:
        raise FinansCariKimlikError('CKod yok.', code='CKOD_YOK', http_status=409)
    validate_tedarikci_eslestirme(con, nexgen_tedarikci_id, ckod)
    now = _now()
    con.execute(
        """
        UPDATE tedarikci_eslestirme
        SET eslestirme_durumu='DOGRULANDI', eslestiren_id=?, eslestirme_tarihi=?, updated_at=?
        WHERE nexgen_tedarikci_id=? AND aktif=1
        """,
        (user_id, now, now, int(nexgen_tedarikci_id)),
    )
    if commit:
        con.commit()
    paket = get_tedarikci_eslestirme(con, nexgen_tedarikci_id)
    assert paket
    paket['dogrulandi'] = True
    return paket


def iptal_tedarikci_eslestirme(
    con: sqlite3.Connection,
    nexgen_tedarikci_id: int,
    reason: str,
    *,
    user_id: int | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    _ensure_table(con)
    if not (reason or '').strip():
        raise FinansCariKimlikError('reason zorunlu.', code='NEDEN_ZORUNLU', http_status=400)
    es = get_tedarikci_eslestirme(con, nexgen_tedarikci_id)
    if not es:
        raise FinansCariKimlikError(
            'Tedarikci eslestirme bulunamadi.',
            code='ESLESME_BEKLIYOR',
            http_status=404,
        )
    now = _now()
    notlar = es.get('notlar') or ''
    ek = f'[iptal:{reason.strip()}]'
    notlar = f'{notlar}\n{ek}'.strip()
    con.execute(
        """
        UPDATE tedarikci_eslestirme
        SET aktif=0, eslestirme_durumu='IPTAL', notlar=?, updated_at=?
        WHERE nexgen_tedarikci_id=?
        """,
        (notlar, now, int(nexgen_tedarikci_id)),
    )
    if commit:
        con.commit()
    out = get_tedarikci_eslestirme(con, nexgen_tedarikci_id)
    return out or {'nexgen_tedarikci_id': nexgen_tedarikci_id, 'iptal': True, 'aktif': 0}


def dogrula_tedarikci_eslestirme(
    con: sqlite3.Connection,
    nexgen_tedarikci_id: int,
    *,
    user_id: int | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    _ensure_table(con)
    es = get_tedarikci_eslestirme(con, nexgen_tedarikci_id)
    if not es or not int(es.get('aktif') or 0):
        raise FinansCariKimlikError(
            'Aktif tedarikci eslestirme yok.',
            code='ESLESME_BEKLIYOR',
            http_status=404,
        )
    ckod = es.get('cari_kart_ckod')
    if not ckod:
        raise FinansCariKimlikError('CKod yok.', code='CKOD_YOK', http_status=409)
    validate_tedarikci_eslestirme(con, nexgen_tedarikci_id, ckod)
    now = _now()
    con.execute(
        """
        UPDATE tedarikci_eslestirme
        SET eslestirme_durumu='DOGRULANDI', eslestiren_id=?, eslestirme_tarihi=?, updated_at=?
        WHERE nexgen_tedarikci_id=? AND aktif=1
        """,
        (user_id, now, now, int(nexgen_tedarikci_id)),
    )
    if commit:
        con.commit()
    paket = get_tedarikci_eslestirme(con, nexgen_tedarikci_id)
    assert paket
    paket['dogrulandi'] = True
    return paket


def iptal_tedarikci_eslestirme(
    con: sqlite3.Connection,
    nexgen_tedarikci_id: int,
    reason: str,
    *,
    user_id: int | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    _ensure_table(con)
    if not (reason or '').strip():
        raise FinansCariKimlikError('reason zorunlu.', code='NEDEN_ZORUNLU', http_status=400)
    es = get_tedarikci_eslestirme(con, nexgen_tedarikci_id)
    if not es:
        raise FinansCariKimlikError(
            'Tedarikci eslestirme bulunamadi.',
            code='ESLESME_BEKLIYOR',
            http_status=404,
        )
    now = _now()
    notlar = es.get('notlar') or ''
    ek = f'[iptal:{reason.strip()}]'
    notlar = f'{notlar}\n{ek}'.strip()
    con.execute(
        """
        UPDATE tedarikci_eslestirme
        SET aktif=0, eslestirme_durumu='IPTAL', notlar=?, updated_at=?
        WHERE nexgen_tedarikci_id=?
        """,
        (notlar, now, int(nexgen_tedarikci_id)),
    )
    if commit:
        con.commit()
    out = get_tedarikci_eslestirme(con, nexgen_tedarikci_id)
    return out or {'nexgen_tedarikci_id': nexgen_tedarikci_id, 'iptal': True, 'aktif': 0}
