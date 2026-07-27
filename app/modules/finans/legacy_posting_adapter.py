# -*- coding: utf-8 -*-
"""Legacy finans modülü → FinancialPostingService adapter — P1."""
from __future__ import annotations

import sqlite3

from modules.nexgen.finans_core_config import idempotency_posting_event
from modules.nexgen.financial_posting_service import FinancialPostingError, FinancialPostingService, LegacyHareketRequest


def post_avans_hareket(
    con: sqlite3.Connection,
    *,
    ckod: str,
    avans_tarih: str,
    avans_id: int,
    proje_kod: str,
    tutar: float,
    kullanici: str = 'sistem',
) -> int:
    """Anlaşma avansı — alacak hareketi."""
    belge_no = f'AV{int(avans_id):04d}'
    req = LegacyHareketRequest(
        ckod=ckod,
        tarih=avans_tarih,
        belge_no=belge_no,
        belge_tip='AVANS',
        aciklama=f'{proje_kod} - Ön avans',
        borc=0.0,
        alacak=float(tutar or 0),
        kaynak_tur='finans_avans',
        kaynak_id=int(avans_id),
        olay_turu='AVANS_OLUSTUR',
        idempotency_key=idempotency_posting_event('LEGACY', 'finans_avans', int(avans_id), 'AVANS'),
        kullanici=kullanici,
        legacy_caller='anlasma_olustur.post_avans_hareket',
    )
    res = FinancialPostingService.post_legacy_hareket(con, req, legacy_compat_mode=True)
    return int(res['cari_har_id'])


def post_odeme_plan_tahsilat(
    con: sqlite3.Connection,
    *,
    ckod: str,
    plan_id: int,
    proje_kod: str,
    gerc_tarih: str,
    gerc_tutar: float,
    aciklama: str,
    kullanici: str = 'sistem',
) -> int:
    """Ödeme planı tahsilatı — alacak hareketi."""
    belge_no = f'OP{int(plan_id):04d}'
    req = LegacyHareketRequest(
        ckod=ckod,
        tarih=gerc_tarih,
        belge_no=belge_no,
        belge_tip='TAHSILAT',
        aciklama=aciklama or f'{proje_kod} - tahsilat',
        borc=0.0,
        alacak=float(gerc_tutar or 0),
        kaynak_tur='finans_odeme_plan',
        kaynak_id=int(plan_id),
        olay_turu='ODEME_GELDI',
        idempotency_key=idempotency_posting_event('LEGACY', 'finans_odeme_plan', int(plan_id), 'TAHSILAT'),
        kullanici=kullanici,
        legacy_caller='odeme_plan_gerceklesti',
    )
    res = FinancialPostingService.post_legacy_hareket(con, req, legacy_compat_mode=True)
    return int(res['cari_har_id'])


def geri_al_odeme_plan_hareket(con: sqlite3.Connection, cari_har_id: int) -> bool:
    """Legacy geri-al — teknik borç: fiziksel silme."""
    return FinancialPostingService.delete_legacy_hareket(
        con, int(cari_har_id), legacy_compat_mode=True,
    )


def validate_legacy_amounts(borc: float, alacak: float) -> None:
    """Adapter seviyesinde erken doğrulama."""
    from modules.nexgen.finans_ledger_standard import validate_hareket_tutarlari
    validate_hareket_tutarlari(borc, alacak)
