# -*- coding: utf-8 -*-
"""finans_hareket metadata servisi — FAZ-GECIS Bölüm B (LedgerService)."""
from __future__ import annotations

import sqlite3
from typing import Any

from modules.nexgen.finans_belgesi_repository import tablo_var
from modules.nexgen.finans_core_config import (
    HAREKET_DURUM_AKTIF,
    KAYNAK_ENTITY_BELGE,
    KAYNAK_SISTEM_NEXGEN,
    idempotency_hareket_post,
)
from modules.nexgen.finans_posting_context import PostingContext


class FinansLedgerError(Exception):
    def __init__(self, mesaj: str, kod: int = 409, hata_kodu: str = 'LEDGER_HATA'):
        self.mesaj = mesaj
        self.kod = kod
        self.hata_kodu = hata_kodu
        super().__init__(mesaj)


def create_metadata(
    con: sqlite3.Connection,
    *,
    cari_har_id: int,
    ckod: str,
    ctx: PostingContext,
    islem_tipi: str,
    finans_belgesi_id: int | None = None,
    finans_belge_satir_id: int | None = None,
    finans_open_item_id: int | None = None,
    kaynak_entity: str = KAYNAK_ENTITY_BELGE,
    kaynak_entity_id: int | None = None,
    orijinal_cari_har_id: int | None = None,
    ters_cari_har_id: int | None = None,
) -> dict[str, Any]:
    if not tablo_var(con, 'finans_hareket'):
        raise FinansLedgerError('finans_hareket tablosu yok.', 503, 'TABLO_YOK')

    mevcut = con.execute(
        'SELECT cari_har_id FROM finans_hareket WHERE cari_har_id=?',
        (int(cari_har_id),),
    ).fetchone()
    if mevcut:
        return dict(con.execute(
            'SELECT * FROM finans_hareket WHERE cari_har_id=?', (int(cari_har_id),),
        ).fetchone())

    idem = idempotency_hareket_post(ctx.idempotency_key)
    ke_id = kaynak_entity_id or ctx.kaynak_id or finans_belgesi_id
    con.execute(
        """
        INSERT INTO finans_hareket (
            cari_har_id, ckod, finans_belgesi_id, finans_belge_satir_id,
            finans_open_item_id, kaynak_entity, kaynak_entity_id,
            kaynak_sistem, islem_tipi, durum,
            orijinal_cari_har_id, ters_cari_har_id,
            transaction_id, idempotency_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(cari_har_id), ckod, finans_belgesi_id, finans_belge_satir_id,
            finans_open_item_id, kaynak_entity, ke_id,
            ctx.kaynak_sistem or KAYNAK_SISTEM_NEXGEN, islem_tipi, HAREKET_DURUM_AKTIF,
            orijinal_cari_har_id, ters_cari_har_id,
            ctx.transaction_id, idem,
        ),
    )
    return dict(con.execute(
        'SELECT * FROM finans_hareket WHERE cari_har_id=?', (int(cari_har_id),),
    ).fetchone())
