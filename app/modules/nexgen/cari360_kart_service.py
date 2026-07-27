# -*- coding: utf-8 -*-
"""
Cari Kart shell — FAZ-CARI-KART-SHELL-VE-YETKILILER-UI-1

Hafif okuma: nexgen_cari + iç sorumlu + eşleşme durumu.
Finans/CRM/numune/sipariş/tahsilat sorgusu YOK.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from modules.nexgen.cari_sorumlu_service import can_view_cari, list_aktif_cari_sorumlulari
from modules.nexgen.cari_yetkili_service import can_write_yetkili
from modules.nexgen.finans_cari_provision_service import is_test_kayit


class Cari360KartError(Exception):
    def __init__(self, mesaj: str, kod: int = 400):
        self.mesaj = mesaj
        self.kod = kod
        super().__init__(mesaj)


def _tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def assert_cari_yetkili_schema(con: sqlite3.Connection) -> None:
    if not _tablo_var(con, 'cari_yetkili'):
        raise Cari360KartError(
            'cari_yetkili tablosu yok. Migration 133 uygulanmalı.',
            503,
        )


def _eslestirme_durumu(con: sqlite3.Connection, cari_id: int, cari_kod: str, unvan: str) -> str:
    """Tek satır cari_eslestirme — Cari_Kart / CRM / hareket yok."""
    test = is_test_kayit(cari_kod, unvan)
    durum = None
    if _tablo_var(con, 'cari_eslestirme'):
        row = con.execute(
            """
            SELECT eslestirme_durumu FROM cari_eslestirme
            WHERE nexgen_cari_id=? AND aktif=1
            ORDER BY id DESC LIMIT 1
            """,
            (cari_id,),
        ).fetchone()
        if row:
            durum = (row['eslestirme_durumu'] or '').strip().upper() or None

    if test and durum not in ('DOGRULANDI', 'MANUEL'):
        return 'TEST_NO_LINK'
    if durum in ('DOGRULANDI', 'MANUEL', 'BEKLIYOR', 'TEST_NO_LINK'):
        return durum
    if durum:
        return durum
    return 'BEKLIYOR'


def _sorumlu_ozet(con: sqlite3.Connection, cari_id: int) -> dict[str, Any]:
    if not _tablo_var(con, 'cari_sorumlu'):
        return {'ana_adi': None, 'liste': []}
    aktif = list_aktif_cari_sorumlulari(con, cari_id)
    ana_adi = None
    for s in aktif:
        if (s.get('sorumluluk_rolu') or '').upper() == 'ANA':
            ana_adi = s.get('kullanici_adi')
            break
    if ana_adi is None and aktif:
        ana_adi = aktif[0].get('kullanici_adi')
    return {
        'ana_adi': ana_adi,
        'liste': [
            {
                'kullanici_adi': s.get('kullanici_adi'),
                'rol': s.get('sorumluluk_rolu'),
            }
            for s in aktif
        ],
    }


def load_cari_kart(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None,
) -> dict[str, Any]:
    """Cari Kart shell verisi — ağır modül sorgusu yok."""
    if not can_view_cari(con, kullanici_id, cari_id, yk):
        raise Cari360KartError('Bu cari için görüntüleme yetkiniz yok.', 403)

    assert_cari_yetkili_schema(con)

    row = con.execute(
        'SELECT id, cari_kod, unvan, aktif, created_at, updated_at '
        'FROM nexgen_cari WHERE id=?',
        (cari_id,),
    ).fetchone()
    if not row:
        raise Cari360KartError('Cari bulunamadı.', 404)

    cari_kod = row['cari_kod'] or ''
    unvan = row['unvan'] or ''
    es_durum = _eslestirme_durumu(con, cari_id, cari_kod, unvan)
    test_cari = is_test_kayit(cari_kod, unvan)
    sorumlu = _sorumlu_ozet(con, cari_id)

    return {
        'cari': {
            'id': int(row['id']),
            'cari_kod': cari_kod,
            'unvan': unvan,
            'aktif': int(row['aktif'] or 0),
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
        },
        'sorumlu_adi': sorumlu['ana_adi'],
        'sorumlular': sorumlu['liste'],
        'eslestirme_durumu': es_durum,
        'test_cari': test_cari,
        'test_banner': bool(test_cari and es_durum == 'TEST_NO_LINK'),
        'can_write_yetkili': can_write_yetkili(con, kullanici_id, cari_id, yk),
    }
