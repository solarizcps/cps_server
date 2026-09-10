# -*- coding: utf-8 -*-
"""Enjeksiyon kalıp/seri şema uyumluluk yardımcıları — salt okunur, DDL yok."""
from __future__ import annotations

import sqlite3

ALLOWLIST_TABLES = frozenset({
    'enj_kalip',
    'enj_kalip_seri',
    'enj_kalip_seri_uye',
})

SERI_TABLE = 'enj_kalip_seri'
UYE_TABLE = 'enj_kalip_seri_uye'
KALIP_TABLE = 'enj_kalip'

MIG191_KALIP_COLUMNS = frozenset({'aktif_goz_sayisi', 'kapasite_onayli'})


class SeriesSchemaUnavailableError(Exception):
    """Her iki seri tablosu da yok."""

    code = 'SERIES_SCHEMA_UNAVAILABLE'


class SeriesSchemaIncompleteError(Exception):
    """Yalnızca bir seri tablosu mevcut — kısmi migration."""

    code = 'SERIES_SCHEMA_INCOMPLETE'


def _assert_allowlisted_table(table_name: str) -> None:
    if table_name not in ALLOWLIST_TABLES:
        raise ValueError(f'allowlist dışı tablo: {table_name!r}')


def table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    _assert_allowlisted_table(table_name)
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return bool(row)


def column_names(con: sqlite3.Connection, table_name: str) -> set[str]:
    _assert_allowlisted_table(table_name)
    if not table_exists(con, table_name):
        return set()
    rows = con.execute(f'PRAGMA table_info({table_name})').fetchall()
    return {str(r[1]) for r in rows}


def has_column(con: sqlite3.Connection, table_name: str, column: str) -> bool:
    return column in column_names(con, table_name)


def series_schema_state(con: sqlite3.Connection) -> str:
    """'complete' | 'absent' | 'incomplete'."""
    seri = table_exists(con, SERI_TABLE)
    uye = table_exists(con, UYE_TABLE)
    if seri and uye:
        return 'complete'
    if not seri and not uye:
        return 'absent'
    return 'incomplete'


def kalip_column_projection(
    con: sqlite3.Connection,
    column: str,
    *,
    table_alias: str = 'k',
) -> str:
    """Migration-191 optional kolonlar için SELECT parçası."""
    if column not in MIG191_KALIP_COLUMNS:
        raise ValueError(f'desteklenmeyen optional kolon: {column!r}')
    prefix = f'{table_alias}.' if table_alias else ''
    if has_column(con, KALIP_TABLE, column):
        return f'{prefix}{column}'
    if column == 'aktif_goz_sayisi':
        return 'NULL AS aktif_goz_sayisi'
    return '0 AS kapasite_onayli'


def ky_kaliplar_select_sql(con: sqlite3.Connection) -> str:
    """Kalıp Master liste SELECT — legacy şemada NULL/0 alias."""
    ag = kalip_column_projection(con, 'aktif_goz_sayisi', table_alias='')
    ko = kalip_column_projection(con, 'kapasite_onayli', table_alias='')
    return f"""
            SELECT id, kalip_kod, kalip_tipi, model_kod, model_ad, asorti,
                   kalip_basi_cift, varsayilan_bagli_kalip, renk, gorsel_dosya, aktif,
                   kapasite_cift, kalip_durumu, aciklama,
                   cift_agirlik_gr, pisme_suresi_sn,
                   {ag}, {ko}
            FROM enj_kalip
            ORDER BY aktif DESC, kalip_kod, model_kod, asorti
        """


def uye_join_kalip_select_sql(con: sqlite3.Connection) -> str:
    """Seri üye JOIN — optional enj_kalip kolonları."""
    ag = kalip_column_projection(con, 'aktif_goz_sayisi')
    ko = kalip_column_projection(con, 'kapasite_onayli')
    return f"""
               k.kalip_kod, k.kalip_tipi, k.model_kod, k.model_ad, k.asorti,
               k.kalip_basi_cift, {ag}, k.kapasite_cift,
               {ko}, k.varsayilan_bagli_kalip, k.aktif AS kalip_aktif
        """


def reject_unavailable_kalip_patch_fields(
    con: sqlite3.Connection,
    guncel: dict,
) -> str | None:
    """Request'teki migration-191 alanı şemada yoksa alan adını döndür."""
    cols = column_names(con, KALIP_TABLE)
    for field in MIG191_KALIP_COLUMNS:
        if field in guncel and field not in cols:
            return field
    return None
