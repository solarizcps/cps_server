# -*- coding: utf-8 -*-
"""Finans çekirdek schema read-only doğrulama yardımcıları — FAZ-FINANS-F1."""
from __future__ import annotations

import sqlite3
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from modules.nexgen.finans_core_config import OI_DURUMLAR, OI_YONLAR

F1_CORE_TABLES: tuple[str, ...] = (
    'finans_cari_kart',
    'finans_belge_satir',
    'finans_hareket',
    'finans_open_item',
    'finans_audit',
)

FB_F1_KOLONLAR: tuple[str, ...] = (
    'kaynak_sistem', 'olay_turu', 'olay_versiyonu', 'kur', 'yerel_para_tutari',
    'ters_belge_id', 'orijinal_belge_id', 'onaylayan_2_id', 'dort_goz_bypass',
    'mal_kabul_id', 'versiyon',
)


def tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def kolon_var(con: sqlite3.Connection, tablo: str, kolon: str) -> bool:
    if not tablo_var(con, tablo):
        return False
    return kolon in [c[1] for c in con.execute(f'PRAGMA table_info({tablo})').fetchall()]


def f1_core_schema_ok(con: sqlite3.Connection) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for t in F1_CORE_TABLES:
        if not tablo_var(con, t):
            errors.append(f'missing_table:{t}')
    if tablo_var(con, 'finans_belgesi'):
        for k in FB_F1_KOLONLAR:
            if not kolon_var(con, 'finans_belgesi', k):
                errors.append(f'missing_column:finans_belgesi.{k}')
    return (len(errors) == 0, errors)


def decimal_para(value: object, *, scale: int = 2) -> Decimal:
    """Para alanı — float yerine Decimal (DB NUMERIC ile uyumlu)."""
    if value is None:
        return Decimal('0')
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f'Geçersiz para değeri: {value!r}') from exc
    q = Decimal('1').scaleb(-scale)
    return d.quantize(q, rounding=ROUND_HALF_UP)


def open_item_tutar_gecerli(orijinal: Decimal, acik: Decimal, kapanan: Decimal) -> bool:
    if orijinal < 0 or acik < 0 or kapanan < 0:
        return False
    if kapanan > orijinal:
        return False
    if acik + kapanan > orijinal + Decimal('0.001'):
        return False
    return True


def open_item_durum_gecerli(durum: str) -> bool:
    return durum in OI_DURUMLAR


def open_item_yon_gecerli(yon: str) -> bool:
    return yon in OI_YONLAR
