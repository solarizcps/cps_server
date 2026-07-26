# -*- coding: utf-8 -*-
"""Finans cari kimlik — domain servisi (FAZ-F1-2)."""
from __future__ import annotations

import sqlite3
import unicodedata
from datetime import datetime
from typing import Any

KIMLIK_TIPLERI = ('MUSTERI', 'TEDARIKCI')
KIMLIK_DURUMLARI = ('BEKLIYOR', 'DOGRULANDI', 'MANUEL', 'IPTAL', 'CAKISMA')
ESLESTIRME_DOGRULANMIS = ('DOGRULANDI', 'MANUEL')


class FinansCariKimlikError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = 'KIMLIK_HATA',
        http_status: int = 400,
        details: dict[str, Any] | None = None,
    ):
        self.message = message
        self.code = code
        self.http_status = http_status
        self.details = details or {}
        super().__init__(message)


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _ascii_upper(s: str) -> str:
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.upper().strip()


def normalize_ctip(value: Any) -> set[str]:
    """Cari_Kart.CTip → {'MUSTERI'}, {'TEDARIKCI'} veya her ikisi."""
    if value is None:
        return set()
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        raw = str(value)
    else:
        raw = str(value).strip()
    if not raw:
        return set()

    key = _ascii_upper(raw).replace(' ', '_')
    key_plain = key.replace('_', '')

    musteri_keys = {
        '1', 'MUSTERI', 'MÜŞTERİ', 'MUS', 'CUSTOMER', 'MST',
    }
    tedarikci_keys = {
        '2', 'TEDARIKCI', 'TEDARİKÇİ', 'TED', 'SUPPLIER', 'TDR',
    }
    her_ikisi_keys = {
        '3', 'HER_IKISI', 'HERİKİSİ', 'HERIKISI', 'BOTH', 'DUAL',
    }

    norm_key = _ascii_upper(raw)
    norm_plain = norm_key.replace(' ', '').replace('_', '')

    for k in (key, key_plain, norm_key, norm_plain):
        if k in musteri_keys or k == 'MUSTERI':
            return {'MUSTERI'}
        if k in tedarikci_keys or k == 'TEDARIKCI':
            return {'TEDARIKCI'}
        if k in her_ikisi_keys:
            return {'MUSTERI', 'TEDARIKCI'}

    if raw in ('1', 1):
        return {'MUSTERI'}
    if raw in ('2', 2):
        return {'TEDARIKCI'}
    if raw in ('3', 3):
        return {'MUSTERI', 'TEDARIKCI'}

    return set()


def validate_ctip_for_kimlik(
    cari_kart_row: dict[str, Any] | None,
    kimlik_tipi: str,
    *,
    manuel_override: bool = False,
    manuel_not: str | None = None,
) -> dict[str, Any]:
    """CTip uygunluk doğrulaması — bilinmeyen değer sessizce kabul edilmez."""
    ctip_raw = cari_kart_row.get('CTip') if cari_kart_row else None
    normalized = normalize_ctip(ctip_raw)
    uyari: str | None = None
    blok_kodu: str | None = None
    uygun = False

    if kimlik_tipi == 'MUSTERI':
        uygun = 'MUSTERI' in normalized
        if not normalized:
            uyari = 'CTip bilinmiyor'
            blok_kodu = 'CTIP_BILINMIYOR'
        elif not uygun:
            uyari = 'CTip yalnizca tedarikci'
            blok_kodu = 'CTIP_UYUMSUZ'
    elif kimlik_tipi == 'TEDARIKCI':
        uygun = 'TEDARIKCI' in normalized
        if not normalized:
            uyari = 'CTip bilinmiyor'
            blok_kodu = 'CTIP_BILINMIYOR'
        elif not uygun:
            uyari = 'CTip yalnizca musteri'
            blok_kodu = 'CTIP_UYUMSUZ'
    else:
        raise FinansCariKimlikError(
            'Gecersiz kimlik_tipi.',
            code='KIMLIK_TIP_GECERSIZ',
            http_status=400,
        )

    if not uygun and manuel_override:
        if not (manuel_not or '').strip():
            raise FinansCariKimlikError(
                'Manuel override icin aciklama zorunlu.',
                code='MANUEL_NOT_ZORUNLU',
                http_status=400,
            )
        uygun = True
        uyari = f'Manuel override: {(manuel_not or "").strip()}'
        blok_kodu = None

    return {
        'uygun': uygun,
        'ctip_raw': ctip_raw,
        'ctip_normalized': sorted(normalized),
        'manuel_override': bool(manuel_override and uygun),
        'uyari': uyari,
        'blok_kodu': blok_kodu if not uygun else None,
        'durum_onerisi': 'MANUEL' if manuel_override and uygun else ('DOGRULANDI' if uygun else None),
    }


def _ensure_tables(con: sqlite3.Connection) -> None:
    if not tablo_var(con, 'finans_cari_kimlik'):
        raise FinansCariKimlikError(
            'finans_cari_kimlik tablosu yok — migration 131 gerekli.',
            code='MIGRATION_131',
            http_status=503,
        )


def _kimlik_row(con: sqlite3.Connection, kimlik_id: int) -> dict[str, Any] | None:
    return _row(con.execute(
        'SELECT * FROM finans_cari_kimlik WHERE id=?', (int(kimlik_id),),
    ).fetchone())


def _kimlik_by_cari(con: sqlite3.Connection, nexgen_cari_id: int) -> dict[str, Any] | None:
    return _row(con.execute(
        'SELECT * FROM finans_cari_kimlik WHERE nexgen_cari_id=?',
        (int(nexgen_cari_id),),
    ).fetchone())


def _kimlik_by_tedarikci(con: sqlite3.Connection, nexgen_tedarikci_id: int) -> dict[str, Any] | None:
    return _row(con.execute(
        'SELECT * FROM finans_cari_kimlik WHERE nexgen_tedarikci_id=?',
        (int(nexgen_tedarikci_id),),
    ).fetchone())


def _touch(
    con: sqlite3.Connection,
    kimlik_id: int,
    *,
    user_id: int | None = None,
    notlar: str | None = None,
    **fields: Any,
) -> None:
    sets = ['updated_at=?']
    vals: list[Any] = [_now()]
    if user_id is not None:
        sets.append('updated_by=?')
        vals.append(int(user_id))
    if notlar is not None:
        sets.append('notlar=?')
        vals.append(notlar)
    for k, v in fields.items():
        sets.append(f'{k}=?')
        vals.append(v)
    vals.append(int(kimlik_id))
    con.execute(
        f"UPDATE finans_cari_kimlik SET {', '.join(sets)} WHERE id=?",
        vals,
    )


def _cari_kart(con: sqlite3.Connection, ckod: str | None) -> dict[str, Any] | None:
    if not ckod:
        return None
    return _row(con.execute(
        'SELECT CKod, CName, CTip FROM Cari_Kart WHERE CKod=?', (ckod,),
    ).fetchone())


def _ckod_cakisma(
    con: sqlite3.Connection,
    ckod: str,
    kimlik_tipi: str,
    exclude_id: int | None = None,
) -> dict[str, Any] | None:
    q = """
        SELECT id, kimlik_tipi FROM finans_cari_kimlik
        WHERE cari_kart_ckod=? AND aktif=1 AND kimlik_tipi=?
    """
    params: list[Any] = [ckod, kimlik_tipi]
    if exclude_id:
        q += ' AND id!=?'
        params.append(int(exclude_id))
    return _row(con.execute(q, params).fetchone())


def hesapla_posting_uygunluk(
    kimlik: dict[str, Any],
    *,
    operasyonel_aktif: bool,
    cari_kart: dict[str, Any] | None,
    ctip_dogrulama: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bilgi amaçlı posting uygunluk — FinancialPostingService değiştirilmez."""
    if not kimlik:
        return {'posting_uygun': False, 'posting_engel_kodu': 'KIMLIK_BULUNAMADI'}
    if not int(kimlik.get('aktif') or 0):
        return {'posting_uygun': False, 'posting_engel_kodu': 'KIMLIK_PASIF'}
    if kimlik.get('durum') == 'CAKISMA':
        return {'posting_uygun': False, 'posting_engel_kodu': 'KIMLIK_CAKISMA'}
    if kimlik.get('durum') == 'IPTAL':
        return {'posting_uygun': False, 'posting_engel_kodu': 'KIMLIK_PASIF'}
    if not operasyonel_aktif:
        return {'posting_uygun': False, 'posting_engel_kodu': 'OPERASYONEL_PASIF'}
    if kimlik.get('durum') not in ('DOGRULANDI', 'MANUEL'):
        return {'posting_uygun': False, 'posting_engel_kodu': 'ESLESME_BEKLIYOR'}
    ckod = kimlik.get('cari_kart_ckod')
    if not ckod:
        return {'posting_uygun': False, 'posting_engel_kodu': 'CKOD_YOK'}
    if not cari_kart:
        return {'posting_uygun': False, 'posting_engel_kodu': 'CARI_KART_YOK'}
    if kimlik.get('durum') == 'MANUEL':
        return {'posting_uygun': True, 'posting_engel_kodu': None}
    ctip = ctip_dogrulama or validate_ctip_for_kimlik(
        cari_kart, str(kimlik.get('kimlik_tipi')),
    )
    if not ctip.get('uygun'):
        kod = ctip.get('blok_kodu') or 'CTIP_UYUMSUZ'
        return {'posting_uygun': False, 'posting_engel_kodu': kod}
    return {'posting_uygun': True, 'posting_engel_kodu': None}


def _operasyonel_bilgi(con: sqlite3.Connection, kimlik: dict[str, Any]) -> dict[str, Any]:
    if kimlik['kimlik_tipi'] == 'MUSTERI':
        nc = _row(con.execute(
            'SELECT id, cari_kod, unvan, aktif FROM nexgen_cari WHERE id=?',
            (kimlik['nexgen_cari_id'],),
        ).fetchone())
        return {
            'operasyonel_id': kimlik['nexgen_cari_id'],
            'operasyonel_kod': nc['cari_kod'] if nc else None,
            'operasyonel_unvan': nc['unvan'] if nc else None,
            'operasyonel_aktif': bool(nc and int(nc.get('aktif') or 0)),
        }
    nt = _row(con.execute(
        'SELECT id, kod, ad, aktif FROM nexgen_tedarikci WHERE id=?',
        (kimlik['nexgen_tedarikci_id'],),
    ).fetchone())
    return {
        'operasyonel_id': kimlik['nexgen_tedarikci_id'],
        'operasyonel_kod': nt['kod'] if nt else None,
        'operasyonel_unvan': nt['ad'] if nt else None,
        'operasyonel_aktif': bool(nt and int(nt.get('aktif') or 0)),
    }


def _resolve_paket(con: sqlite3.Connection, kimlik: dict[str, Any]) -> dict[str, Any]:
    op = _operasyonel_bilgi(con, kimlik)
    ck = _cari_kart(con, kimlik.get('cari_kart_ckod'))
    ctip = validate_ctip_for_kimlik(ck, kimlik['kimlik_tipi']) if ck else {
        'uygun': False,
        'ctip_raw': None,
        'ctip_normalized': [],
        'manuel_override': False,
        'uyari': None,
        'blok_kodu': 'CARI_KART_YOK' if kimlik.get('cari_kart_ckod') else None,
        'durum_onerisi': None,
    }
    if kimlik.get('durum') == 'MANUEL':
        ctip = {**ctip, 'uygun': True, 'manuel_override': True}
    posting = hesapla_posting_uygunluk(
        kimlik,
        operasyonel_aktif=op['operasyonel_aktif'],
        cari_kart=ck,
        ctip_dogrulama=ctip,
    )
    uyarilar = []
    if ctip.get('uyari'):
        uyarilar.append(ctip['uyari'])
    if kimlik.get('durum') == 'CAKISMA':
        uyarilar.append('Kimlik cakisma durumunda')
    return {
        'id': kimlik['id'],
        'kimlik_tipi': kimlik['kimlik_tipi'],
        **op,
        'cari_kart_ckod': kimlik.get('cari_kart_ckod'),
        'cari_kart_unvan': ck['CName'] if ck else None,
        'ctip_raw': ctip.get('ctip_raw'),
        'ctip_normalized': ctip.get('ctip_normalized', []),
        'ctip_uygun': bool(ctip.get('uygun')),
        'aktif': bool(int(kimlik.get('aktif') or 0)),
        'durum': kimlik.get('durum'),
        'notlar': kimlik.get('notlar'),
        'unvan_snapshot': kimlik.get('unvan_snapshot'),
        'manuel_override_kayitli': kimlik.get('durum') == 'MANUEL',
        **posting,
        'uyarilar': uyarilar,
        'created_at': kimlik.get('created_at'),
        'updated_at': kimlik.get('updated_at'),
        'created_by': kimlik.get('created_by'),
        'updated_by': kimlik.get('updated_by'),
    }


def create_kimlik_musteri(
    con: sqlite3.Connection,
    nexgen_cari_id: int,
    *,
    user_id: int | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    _ensure_tables(con)
    nc = _row(con.execute(
        'SELECT id, unvan, aktif FROM nexgen_cari WHERE id=?',
        (int(nexgen_cari_id),),
    ).fetchone())
    if not nc:
        raise FinansCariKimlikError(
            'nexgen_cari bulunamadi.',
            code='NEXGEN_CARI_YOK',
            http_status=404,
        )
    if not int(nc.get('aktif') or 0):
        raise FinansCariKimlikError(
            'nexgen_cari pasif.',
            code='OPERASYONEL_PASIF',
            http_status=409,
        )

    mevcut = _kimlik_by_cari(con, nexgen_cari_id)
    if mevcut:
        paket = _resolve_paket(con, mevcut)
        paket['idempotent'] = True
        return paket

    now = _now()
    cur = con.execute(
        """
        INSERT INTO finans_cari_kimlik
            (kimlik_tipi, nexgen_cari_id, unvan_snapshot, durum, aktif,
             created_at, updated_at, created_by, updated_by)
        VALUES ('MUSTERI', ?, ?, 'BEKLIYOR', 1, ?, ?, ?, ?)
        """,
        (int(nexgen_cari_id), nc.get('unvan'), now, now, user_id, user_id),
    )
    kid = int(cur.lastrowid)
    if commit:
        con.commit()
    kimlik = _kimlik_row(con, kid)
    assert kimlik
    paket = _resolve_paket(con, kimlik)
    paket['idempotent'] = False
    return paket


def create_kimlik_tedarikci(
    con: sqlite3.Connection,
    nexgen_tedarikci_id: int,
    *,
    user_id: int | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    _ensure_tables(con)
    nt = _row(con.execute(
        'SELECT id, ad, aktif FROM nexgen_tedarikci WHERE id=?',
        (int(nexgen_tedarikci_id),),
    ).fetchone())
    if not nt:
        raise FinansCariKimlikError(
            'nexgen_tedarikci bulunamadi.',
            code='NEXGEN_TEDARIKCI_YOK',
            http_status=404,
        )
    if not int(nt.get('aktif') or 0):
        raise FinansCariKimlikError(
            'nexgen_tedarikci pasif.',
            code='OPERASYONEL_PASIF',
            http_status=409,
        )

    mevcut = _kimlik_by_tedarikci(con, nexgen_tedarikci_id)
    if mevcut:
        paket = _resolve_paket(con, mevcut)
        paket['idempotent'] = True
        return paket

    now = _now()
    cur = con.execute(
        """
        INSERT INTO finans_cari_kimlik
            (kimlik_tipi, nexgen_tedarikci_id, unvan_snapshot, durum, aktif,
             created_at, updated_at, created_by, updated_by)
        VALUES ('TEDARIKCI', ?, ?, 'BEKLIYOR', 1, ?, ?, ?, ?)
        """,
        (int(nexgen_tedarikci_id), nt.get('ad'), now, now, user_id, user_id),
    )
    kid = int(cur.lastrowid)
    if commit:
        con.commit()
    kimlik = _kimlik_row(con, kid)
    assert kimlik
    paket = _resolve_paket(con, kimlik)
    paket['idempotent'] = False
    return paket


def resolve_kimlik(
    con: sqlite3.Connection,
    *,
    kimlik_id: int | None = None,
    nexgen_cari_id: int | None = None,
    nexgen_tedarikci_id: int | None = None,
) -> dict[str, Any]:
    _ensure_tables(con)
    params = [kimlik_id, nexgen_cari_id, nexgen_tedarikci_id]
    dolu = [p for p in params if p is not None]
    if len(dolu) != 1:
        raise FinansCariKimlikError(
            'Tam olarak bir kimlik parametresi verilmeli.',
            code='PARAMETRE_HATASI',
            http_status=400,
            details={'verilen': len(dolu)},
        )

    if kimlik_id is not None:
        kimlik = _kimlik_row(con, kimlik_id)
    elif nexgen_cari_id is not None:
        kimlik = _kimlik_by_cari(con, nexgen_cari_id)
    else:
        kimlik = _kimlik_by_tedarikci(con, nexgen_tedarikci_id)  # type: ignore[arg-type]

    if not kimlik:
        raise FinansCariKimlikError(
            'Kimlik bulunamadi.',
            code='KIMLIK_BULUNAMADI',
            http_status=404,
        )
    return _resolve_paket(con, kimlik)


def sync_musteri_ckod_from_eslestirme(
    con: sqlite3.Connection,
    kimlik_id: int,
    *,
    user_id: int | None = None,
    manuel_override: bool = False,
    manuel_not: str | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    _ensure_tables(con)
    kimlik = _kimlik_row(con, kimlik_id)
    if not kimlik:
        raise FinansCariKimlikError('Kimlik bulunamadi.', code='KIMLIK_BULUNAMADI', http_status=404)
    if kimlik['kimlik_tipi'] != 'MUSTERI':
        raise FinansCariKimlikError(
            'Yalnizca MUSTERI kimligi sync edilebilir.',
            code='KIMLIK_TIP_UYUMSUZ',
            http_status=409,
        )

    es_rows = con.execute(
        """
        SELECT id, cari_kart_ckod, eslestirme_durumu, aktif
        FROM cari_eslestirme
        WHERE nexgen_cari_id=? AND aktif=1
        ORDER BY id
        """,
        (kimlik['nexgen_cari_id'],),
    ).fetchall()
    if not es_rows:
        raise FinansCariKimlikError(
            'Aktif cari_eslestirme bulunamadi.',
            code='ESLESME_BEKLIYOR',
            http_status=409,
        )

    ckodlar = {r['cari_kart_ckod'] for r in es_rows if r['cari_kart_ckod']}
    if len(es_rows) > 1 and len(ckodlar) > 1:
        _touch(con, kimlik_id, user_id=user_id, durum='CAKISMA',
               notlar='Coklu aktif eslestirme — farkli CKod')
        if commit:
            con.commit()
        raise FinansCariKimlikError(
            'Coklu aktif eslestirme cakismasi.',
            code='KIMLIK_CAKISMA',
            http_status=409,
        )

    es = dict(es_rows[0])
    if es.get('eslestirme_durumu') not in ESLESTIRME_DOGRULANMIS:
        raise FinansCariKimlikError(
            'Eslestirme durumu DOGRULANDI veya MANUEL olmali.',
            code='ESLESME_BEKLIYOR',
            http_status=409,
        )

    ckod = es.get('cari_kart_ckod')
    if not ckod:
        raise FinansCariKimlikError('Eslestirmede CKod yok.', code='CKOD_YOK', http_status=409)

    ck = _cari_kart(con, ckod)
    if not ck:
        raise FinansCariKimlikError('Cari_Kart bulunamadi.', code='CARI_KART_YOK', http_status=404)

    ctip = validate_ctip_for_kimlik(
        ck, 'MUSTERI',
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

    cakisma = _ckod_cakisma(con, ckod, 'MUSTERI', exclude_id=kimlik_id)
    if cakisma:
        raise FinansCariKimlikError(
            'CKod baska aktif MUSTERI kimliginde.',
            code='CKOD_CAKISMA',
            http_status=409,
            details={'diger_kimlik_id': cakisma['id']},
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


def deactivate_kimlik(
    con: sqlite3.Connection,
    kimlik_id: int,
    reason: str,
    *,
    user_id: int | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    _ensure_tables(con)
    if not (reason or '').strip():
        raise FinansCariKimlikError(
            'Deaktivasyon nedeni zorunlu.',
            code='NEDEN_ZORUNLU',
            http_status=400,
        )
    kimlik = _kimlik_row(con, kimlik_id)
    if not kimlik:
        raise FinansCariKimlikError('Kimlik bulunamadi.', code='KIMLIK_BULUNAMADI', http_status=404)

    prev = kimlik.get('durum')
    notlar = kimlik.get('notlar') or ''
    ek = f'[deactivate:{reason.strip()}] onceki_durum={prev}'
    notlar = f'{notlar}\n{ek}'.strip()

    _touch(con, kimlik_id, user_id=user_id, aktif=0, durum='IPTAL', notlar=notlar)
    if commit:
        con.commit()
    updated = _kimlik_row(con, kimlik_id)
    assert updated
    paket = _resolve_paket(con, updated)
    paket['onceki_durum'] = prev
    return paket


def reactivate_kimlik(
    con: sqlite3.Connection,
    kimlik_id: int,
    *,
    user_id: int | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    _ensure_tables(con)
    kimlik = _kimlik_row(con, kimlik_id)
    if not kimlik:
        raise FinansCariKimlikError('Kimlik bulunamadi.', code='KIMLIK_BULUNAMADI', http_status=404)

    op = _operasyonel_bilgi(con, kimlik)
    if not op['operasyonel_aktif']:
        raise FinansCariKimlikError(
            'Operasyonel master pasif.',
            code='OPERASYONEL_PASIF',
            http_status=409,
        )

    ckod = kimlik.get('cari_kart_ckod')
    yeni_durum = 'BEKLIYOR'
    if ckod:
        cakisma = _ckod_cakisma(con, ckod, kimlik['kimlik_tipi'], exclude_id=kimlik_id)
        if cakisma:
            raise FinansCariKimlikError(
                'CKod baska aktif kimlikte kullaniliyor.',
                code='CKOD_CAKISMA',
                http_status=409,
            )
        ck = _cari_kart(con, ckod)
        if ck:
            manuel = '[MANUEL_OVERRIDE' in (kimlik.get('notlar') or '')
            ctip = validate_ctip_for_kimlik(
                ck, kimlik['kimlik_tipi'],
                manuel_override=manuel,
                manuel_not='reactivate' if manuel else None,
            )
            if ctip['uygun']:
                yeni_durum = 'MANUEL' if manuel else 'DOGRULANDI'
            elif manuel:
                yeni_durum = 'MANUEL'
        else:
            yeni_durum = 'BEKLIYOR'

    _touch(con, kimlik_id, user_id=user_id, aktif=1, durum=yeni_durum)
    if commit:
        con.commit()
    return _resolve_paket(con, _kimlik_row(con, kimlik_id) or kimlik)


def _eslestirme_celiski_musteri(
    con: sqlite3.Connection,
    nexgen_cari_id: int,
    ckod: str,
) -> None:
    rows = con.execute(
        """
        SELECT cari_kart_ckod FROM cari_eslestirme
        WHERE nexgen_cari_id=? AND aktif=1 AND cari_kart_ckod IS NOT NULL
        """,
        (int(nexgen_cari_id),),
    ).fetchall()
    ckodlar = {r['cari_kart_ckod'] for r in rows if r['cari_kart_ckod']}
    if ckodlar and ckod not in ckodlar:
        raise FinansCariKimlikError(
            'cari_eslestirme ile CKod celiskisi.',
            code='ESLESME_CELISKISI',
            http_status=409,
            details={'mevcut_ckodlar': sorted(ckodlar)},
        )


def _eslestirme_celiski_tedarikci(
    con: sqlite3.Connection,
    nexgen_tedarikci_id: int,
    ckod: str,
) -> None:
    row = con.execute(
        """
        SELECT cari_kart_ckod FROM tedarikci_eslestirme
        WHERE nexgen_tedarikci_id=? AND aktif=1 AND cari_kart_ckod IS NOT NULL
        """,
        (int(nexgen_tedarikci_id),),
    ).fetchone()
    if row and row['cari_kart_ckod'] and row['cari_kart_ckod'] != ckod:
        raise FinansCariKimlikError(
            'tedarikci_eslestirme ile CKod celiskisi.',
            code='ESLESME_CELISKISI',
            http_status=409,
            details={'mevcut_ckod': row['cari_kart_ckod']},
        )


def apply_manuel_kimlik_override(
    con: sqlite3.Connection,
    kimlik_id: int,
    cari_kart_ckod: str,
    override_reason: str,
    *,
    user_id: int | None = None,
    notlar: str | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    """CTip uyumsuzlugunda kontrollu manuel CKod atama — durum MANUEL."""
    _ensure_tables(con)
    if not (override_reason or '').strip():
        raise FinansCariKimlikError(
            'override_reason zorunlu.',
            code='OVERRIDE_REASON_ZORUNLU',
            http_status=400,
        )
    ckod = (cari_kart_ckod or '').strip()
    if not ckod:
        raise FinansCariKimlikError('cari_kart_ckod zorunlu.', code='CKOD_ZORUNLU', http_status=400)

    kimlik = _kimlik_row(con, kimlik_id)
    if not kimlik:
        raise FinansCariKimlikError('Kimlik bulunamadi.', code='KIMLIK_BULUNAMADI', http_status=404)

    ck = _cari_kart(con, ckod)
    if not ck:
        raise FinansCariKimlikError('Cari_Kart bulunamadi.', code='CARI_KART_YOK', http_status=404)

    validate_ctip_for_kimlik(
        ck, kimlik['kimlik_tipi'],
        manuel_override=True,
        manuel_not=override_reason.strip(),
    )

    cakisma = _ckod_cakisma(con, ckod, kimlik['kimlik_tipi'], exclude_id=kimlik_id)
    if cakisma:
        raise FinansCariKimlikError(
            'CKod baska aktif kimlikte.',
            code='CKOD_CAKISMA',
            http_status=409,
        )

    if kimlik['kimlik_tipi'] == 'MUSTERI':
        _eslestirme_celiski_musteri(con, kimlik['nexgen_cari_id'], ckod)
    else:
        _eslestirme_celiski_tedarikci(con, kimlik['nexgen_tedarikci_id'], ckod)

    ek_not = f'[MANUEL_OVERRIDE api] {override_reason.strip()}'
    birlesik = notlar or kimlik.get('notlar') or ''
    birlesik = f'{birlesik}\n{ek_not}'.strip() if birlesik else ek_not

    _touch(
        con, kimlik_id,
        user_id=user_id,
        cari_kart_ckod=ckod,
        durum='MANUEL',
        notlar=birlesik,
    )
    if commit:
        con.commit()
    paket = _resolve_paket(con, _kimlik_row(con, kimlik_id) or kimlik)
    paket['manuel_override'] = True
    paket['override_reason'] = override_reason.strip()
    return paket
