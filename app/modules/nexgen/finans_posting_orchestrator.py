# -*- coding: utf-8 -*-
"""Posting transaction orchestrator — FAZ-GECIS Bölüm B."""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any

from modules.nexgen.finans_audit_service import FinansAuditError, audit_yaz, new_transaction_id
from modules.nexgen.finans_belgesi_repository import tablo_var
from modules.nexgen.finans_core_config import (
    AUDIT_ENTITY_BELGE,
    AUDIT_ENTITY_HAREKET,
    AUDIT_ENTITY_OPEN_ITEM,
    AUDIT_ISLEM_POST,
    OI_YON_BORC,
    idempotency_hareket_post,
    idempotency_posting_event,
)
from modules.nexgen.finans_ledger_service import FinansLedgerError, create_metadata
from modules.nexgen.finans_open_item_service import FinansOpenItemError, create_for_belge
from modules.nexgen.finans_posting_context import PostingContext
from modules.nexgen.finans_ledger_standard import compute_bakiye
from modules.nexgen.financial_posting_service import FinancialPostingService


class PostingOrchestratorError(Exception):
    def __init__(self, mesaj: str, kod: int = 409, hata_kodu: str = 'POSTING_ORCH_HATA'):
        self.mesaj = mesaj
        self.kod = kod
        self.hata_kodu = hata_kodu
        super().__init__(mesaj)


class PostingOrchestrator:
    """Transaction sahibi — yalnız izole test posting için."""

    _TEST_FAULT: str | None = None

    @classmethod
    def set_test_fault(cls, point: str | None) -> None:
        cls._TEST_FAULT = point

    @classmethod
    def _check_fault(cls, point: str) -> None:
        if cls._TEST_FAULT == point:
            raise PostingOrchestratorError(f'Test fault: {point}', 500, 'TEST_FAULT')

    @classmethod
    def _idempotency_kontrol(cls, con: sqlite3.Connection, idem_key: str) -> dict[str, Any] | None:
        if not tablo_var(con, 'finans_hareket'):
            return None
        row = con.execute(
            'SELECT cari_har_id FROM finans_hareket WHERE idempotency_key=?',
            (idem_key,),
        ).fetchone()
        if row:
            return {'idempotent': True, 'cari_har_id': int(row['cari_har_id'])}
        return None

    @classmethod
    def post_test_belge(
        cls,
        con: sqlite3.Connection,
        *,
        belge_id: int,
        ckod: str,
        ctx: PostingContext,
        kullanici_id: int,
        kullanici_ad: str | None = None,
        force_live: bool = True,
    ) -> dict[str, Any]:
        """İzole DB test posting zinciri — BEGIN IMMEDIATE sahibi."""
        if not ctx.transaction_id:
            ctx.transaction_id = new_transaction_id()
        if not ctx.idempotency_key:
            ctx.idempotency_key = idempotency_posting_event(
                ctx.kaynak_sistem,
                ctx.kaynak_tur or 'FINANS_BELGESI',
                int(ctx.kaynak_id or belge_id),
                ctx.olay_turu or 'POST',
                ctx.olay_versiyon,
            )
        idem_key = idempotency_hareket_post(ctx.idempotency_key)

        idem = cls._idempotency_kontrol(con, idem_key)
        if idem:
            return {'ok': True, 'idempotent': True, **idem}

        con.execute('BEGIN IMMEDIATE')
        pre_har = int(con.execute('SELECT COUNT(*) FROM Cari_Har').fetchone()[0])

        try:
            cls._check_fault('before_post')
            post = FinancialPostingService.post_borc(
                con, int(belge_id), kullanici_id, kullanici_ad, force_live=force_live,
            )
            cls._check_fault('after_cari_har')
            har_id = int(post.get('cari_har_id') or 0)
            if not har_id:
                raise PostingOrchestratorError('Cari_Har oluşmadı.', 500, 'CARI_HAR_YOK')

            meta = create_metadata(
                con,
                cari_har_id=har_id,
                ckod=ckod,
                ctx=ctx,
                islem_tipi='BORC',
                finans_belgesi_id=int(belge_id),
            )
            cls._check_fault('after_ledger')

            belge = con.execute(
                'SELECT toplam_tutar, para_birimi, islem_tarihi FROM finans_belgesi WHERE id=?',
                (int(belge_id),),
            ).fetchone()
            oi = create_for_belge(
                con,
                ckod=ckod,
                finans_belgesi_id=int(belge_id),
                yon=OI_YON_BORC,
                orijinal_tutar=Decimal(str(belge['toplam_tutar'] or 0)),
                vade_tarihi=ctx.vade_tarihi,
                para_birimi=(belge['para_birimi'] or 'TRY'),
            )
            cls._check_fault('after_open_item')

            audit_yaz(
                con,
                islem_turu=AUDIT_ISLEM_POST,
                entity_tipi=AUDIT_ENTITY_BELGE,
                entity_id=int(belge_id),
                yeni={'cari_har_id': har_id, 'open_item_id': oi.get('id')},
                kullanici_id=kullanici_id,
                transaction_id=ctx.transaction_id,
                idempotency_key=ctx.idempotency_key,
            )
            cls._check_fault('after_audit')

            con.commit()
            post_har = int(con.execute('SELECT COUNT(*) FROM Cari_Har').fetchone()[0])
            return {
                'ok': True,
                'idempotent': False,
                'cari_har_id': har_id,
                'finans_hareket': meta,
                'open_item': oi,
                'cari_har_count_before': pre_har,
                'cari_har_count_after': post_har,
                'bakiye': compute_bakiye(con, ckod),
                'transaction_id': ctx.transaction_id,
            }
        except (FinansAuditError, FinansLedgerError, FinansOpenItemError, PostingOrchestratorError):
            con.rollback()
            raise
        except Exception:
            con.rollback()
            raise
