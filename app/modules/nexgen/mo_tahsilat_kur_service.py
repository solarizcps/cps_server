# -*- coding: utf-8 -*-
"""Tahsilat TCMB Döviz Satış → TRY hedef canonical servisi."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

DESTEKLENEN_PB = frozenset({'TRY', 'USD', 'EUR'})
KUR_KAYNAGI = 'TCMB_SATIS'
KUR_KAYNAGI_ONCEKI_GECERLI_GUN = 'TCMB_SATIS_ONCEKI_GECERLI_GUN'
_TWOPL = Decimal('0.01')


class MoTahsilatKurError(Exception):
    def __init__(self, mesaj: str, kod: int = 400):
        self.mesaj = mesaj
        self.kod = kod
        super().__init__(mesaj)


def _tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _norm_pb(para_birimi: str | None) -> str:
    pb = (para_birimi or '').strip().upper()
    if pb not in DESTEKLENEN_PB:
        raise MoTahsilatKurError(
            f'Desteklenmeyen para birimi: {para_birimi!r}. (TRY, USD, EUR)',
            400,
        )
    return pb


def _norm_tarih(kur_tarihi: str | None) -> str:
    raw = (kur_tarihi or '').strip()
    if not raw:
        raise MoTahsilatKurError('Kur tarihi zorunlu.', 400)
    iso = raw[:10]
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', iso):
        raise MoTahsilatKurError(f'Geçersiz kur tarihi: {kur_tarihi!r}', 400)
    try:
        date.fromisoformat(iso)
    except ValueError as exc:
        raise MoTahsilatKurError(f'Geçersiz kur tarihi: {kur_tarihi!r}', 400) from exc
    return iso


def _norm_fx(fx_tutar: float | int | str | Decimal) -> Decimal:
    if fx_tutar in (None, ''):
        raise MoTahsilatKurError('FX tutar zorunlu.', 400)
    try:
        val = Decimal(str(fx_tutar))
    except Exception as exc:
        raise MoTahsilatKurError(f'Geçersiz FX tutar: {fx_tutar!r}', 400) from exc
    if val < 0:
        raise MoTahsilatKurError('FX tutar negatif olamaz.', 400)
    return val


def _round_try(amount: Decimal) -> Decimal:
    return amount.quantize(_TWOPL, rounding=ROUND_HALF_UP)


def _float2(val: Decimal) -> float:
    return float(_round_try(val))


def _satis_kur_satir_oku(row: sqlite3.Row | None) -> Decimal | None:
    if not row:
        return None
    satis = row['Satis']
    if satis in (None, ''):
        return None
    try:
        kur = Decimal(str(satis))
    except Exception:
        return None
    if kur <= 0:
        return None
    return kur


def _tcmb_satis_kur_satir(
    con: sqlite3.Connection,
    para_birimi: str,
    tarih: str,
) -> sqlite3.Row | None:
    return con.execute(
        """
        SELECT Satis, MerkezKur, Tarih
        FROM sistem_kur
        WHERE ParaBirimi=? AND Tarih=?
        ORDER BY Id DESC
        LIMIT 1
        """,
        (para_birimi, tarih),
    ).fetchone()


def tcmb_satis_kur_cozumle(
    con: sqlite3.Connection,
    para_birimi: str,
    istenen_sevk_tarihi: str,
) -> dict[str, Any]:
    """
    Sevk tarihi için TCMB Döviz Satış çözümü.
    Önce tam tarih; yoksa yalnız önceki geçerli gün (geleceğe kayma yok).
    """
    pb = _norm_pb(para_birimi)
    istenen = _norm_tarih(istenen_sevk_tarihi)
    if pb == 'TRY':
        return {
            'istenen_sevk_tarihi': istenen,
            'kur_tarihi': istenen,
            'tcmb_satis_kur': Decimal('1'),
            'kur_kaynagi': KUR_KAYNAGI,
        }

    if not _tablo_var(con, 'sistem_kur'):
        raise MoTahsilatKurError('sistem_kur tablosu bulunamadı.', 503)

    row = _tcmb_satis_kur_satir(con, pb, istenen)
    kur = _satis_kur_satir_oku(row)
    if kur is not None:
        return {
            'istenen_sevk_tarihi': istenen,
            'kur_tarihi': istenen,
            'tcmb_satis_kur': kur,
            'kur_kaynagi': KUR_KAYNAGI,
        }

    prev = con.execute(
        """
        SELECT Tarih, Satis, MerkezKur
        FROM sistem_kur
        WHERE ParaBirimi=? AND Tarih < ?
          AND Satis IS NOT NULL AND Satis > 0
        ORDER BY Tarih DESC
        LIMIT 1
        """,
        (pb, istenen),
    ).fetchone()
    prev_kur = _satis_kur_satir_oku(prev)
    if prev_kur is not None and prev:
        return {
            'istenen_sevk_tarihi': istenen,
            'kur_tarihi': str(prev['Tarih'])[:10],
            'tcmb_satis_kur': prev_kur,
            'kur_kaynagi': KUR_KAYNAGI_ONCEKI_GECERLI_GUN,
        }

    raise MoTahsilatKurError(
        f'{pb} için {istenen} tarihli TCMB Döviz Satış kuru bulunamadı.',
        404,
    )


def tcmb_satis_kur_oku(
    con: sqlite3.Connection,
    para_birimi: str,
    kur_tarihi: str,
) -> Decimal:
    """
    Verilen tarihte sistem_kur.Satis — tam eşleşme, fallback yok.
    TRY için 1 döner (tablo okunmaz).
    """
    pb = _norm_pb(para_birimi)
    tarih = _norm_tarih(kur_tarihi)
    if pb == 'TRY':
        return Decimal('1')

    if not _tablo_var(con, 'sistem_kur'):
        raise MoTahsilatKurError('sistem_kur tablosu bulunamadı.', 503)

    row = con.execute(
        """
        SELECT Satis, MerkezKur, Tarih
        FROM sistem_kur
        WHERE ParaBirimi=? AND Tarih=?
        ORDER BY Id DESC
        LIMIT 1
        """,
        (pb, tarih),
    ).fetchone()
    if not row:
        raise MoTahsilatKurError(
            f'{pb} için {tarih} tarihli TCMB Döviz Satış kuru bulunamadı.',
            404,
        )
    satis = row['Satis']
    if satis in (None, ''):
        raise MoTahsilatKurError(
            f'{pb} {tarih} TCMB Döviz Satış (Satis) değeri eksik.',
            409,
        )
    try:
        kur = Decimal(str(satis))
    except Exception as exc:
        raise MoTahsilatKurError(
            f'{pb} {tarih} TCMB Döviz Satış değeri geçersiz.',
            409,
        ) from exc
    if kur <= 0:
        raise MoTahsilatKurError(
            f'{pb} {tarih} TCMB Döviz Satış değeri sıfır veya negatif.',
            409,
        )
    return kur


def fx_try_hedef_hesapla(
    con: sqlite3.Connection,
    *,
    para_birimi: str,
    kur_tarihi: str,
    fx_tutar: float | int | str | Decimal,
) -> dict[str, Any]:
    """
    FX kalan → TCMB Döviz Satış → TRY tahsilat hedefi.
    JSON-serializable dict döner.
    """
    pb = _norm_pb(para_birimi)
    tarih = _norm_tarih(kur_tarihi)
    fx = _norm_fx(fx_tutar)
    cozum = tcmb_satis_kur_cozumle(con, pb, tarih)
    kur = cozum['tcmb_satis_kur']
    try_hedef = _round_try(fx * kur)

    out: dict[str, Any] = {
        'kaynak_pb': pb,
        'fx_tutar': _float2(fx),
        'istenen_sevk_tarihi': cozum['istenen_sevk_tarihi'],
        'kur_tarihi': cozum['kur_tarihi'],
        'tcmb_satis_kur': float(kur),
        'try_hedef_tutar': _float2(try_hedef),
        'kur_kaynagi': cozum['kur_kaynagi'],
    }
    return out


def fx_try_hedef_json(
    con: sqlite3.Connection,
    *,
    para_birimi: str,
    kur_tarihi: str,
    fx_tutar: float | int | str | Decimal,
) -> str:
    """fx_try_hedef_hesapla sonucunu JSON string olarak döner (doğrulama/test)."""
    return json.dumps(
        fx_try_hedef_hesapla(con, para_birimi=para_birimi, kur_tarihi=kur_tarihi, fx_tutar=fx_tutar),
        ensure_ascii=False,
    )
