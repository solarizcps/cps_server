# -*- coding: utf-8 -*-
"""Finans / Muhasebe Merkezi yetki anayasası — route seviyesi."""
from __future__ import annotations

from typing import Any

from modules.nexgen.finans_belgesi_config import (
    DURUM_BEKLIYOR,
    DURUM_DUZELTME_BEKLIYOR,
    DURUM_EKSIK_BILGI,
    DURUM_INCELEMEDE,
    DURUM_ONAYLANDI,
    DURUM_POST_EDILDI,
    POSTING_DURUM_HAZIR,
)
from modules.nexgen.mo_tahsilat_config import CARI_ENTEGRASYON_AKTIF

YETKI_FINANS_VIEW = 'nexgen.finans.view'
YETKI_FINANS_REVIEW = 'nexgen.finans.review'
YETKI_FINANS_APPROVE = 'nexgen.finans.approve'
YETKI_FINANS_POST = 'nexgen.finans.post'
YETKI_FINANS_REJECT = 'nexgen.finans.reject'

FINANS_YETKI_KODLARI: tuple[str, ...] = (
    YETKI_FINANS_VIEW,
    YETKI_FINANS_REVIEW,
    YETKI_FINANS_APPROVE,
    YETKI_FINANS_POST,
    YETKI_FINANS_REJECT,
)


def _yk_has(yk: set[str] | frozenset[str], kod: str, action: str = 'can_view') -> bool:
    if '*' in yk:
        return True
    if f'{kod}:{action}' in yk:
        return True
    return kod in yk


def can_finans_manage(yk: set[str] | frozenset[str]) -> bool:
    return (
        _yk_has(yk, YETKI_FINANS_VIEW, 'can_manage')
        or _yk_has(yk, 'nexgen.yonetim.manage', 'can_manage')
    )


def can_finans_view(yk: set[str] | frozenset[str]) -> bool:
    return _yk_has(yk, YETKI_FINANS_VIEW, 'can_view') or can_finans_manage(yk)


def can_finans_review(yk: set[str] | frozenset[str]) -> bool:
    return (
        _yk_has(yk, YETKI_FINANS_REVIEW, 'can_update')
        or _yk_has(yk, YETKI_FINANS_REVIEW, 'can_create')
        or can_finans_manage(yk)
    )


def can_finans_approve(yk: set[str] | frozenset[str]) -> bool:
    return _yk_has(yk, YETKI_FINANS_APPROVE, 'can_approve') or can_finans_manage(yk)


def can_finans_reject(yk: set[str] | frozenset[str]) -> bool:
    return _yk_has(yk, YETKI_FINANS_REJECT, 'can_approve') or can_finans_manage(yk)


def can_finans_post(yk: set[str] | frozenset[str]) -> bool:
    return (
        _yk_has(yk, YETKI_FINANS_POST, 'can_create')
        or _yk_has(yk, YETKI_FINANS_POST, 'can_update')
        or can_finans_manage(yk)
    )


def can_finans_menu(user_dict: dict | None, yk: set[str] | frozenset[str]) -> bool:
    """Finans Merkezi menü/sayfa görünürlüğü."""
    if finans_erisim_engelli(user_dict, yk):
        return False
    return can_finans_view(yk)


def finans_erisim_engelli(user_dict: dict | None, yk: set[str] | frozenset[str]) -> bool:
    """Depo (Oktay) ve üretim operatörü (Ali) finans route'larına erişemez."""
    if not user_dict:
        return True
    from modules.auth import is_nexgen_uretim_operator
    from modules.nexgen.mo_depo_yetki import is_nexgen_depo_sade_kullanici

    if is_nexgen_depo_sade_kullanici(user_dict, yk):
        return True
    if is_nexgen_uretim_operator(user_dict):
        return True
    return False


def is_pazarlamaci_finans_kisitli(yk: set[str] | frozenset[str]) -> bool:
    """Pazarlamacı — finans onay/posting yapamaz."""
    from modules.nexgen.cari360_yetki import can_cari360_view_own, can_cari360_view_all

    if can_finans_manage(yk) or can_finans_approve(yk) or can_finans_post(yk):
        return False
    if can_cari360_view_all(yk):
        return False
    return can_cari360_view_own(yk)


def finans_aksiyonlar(belge: dict[str, Any], yk: set[str] | frozenset[str]) -> dict[str, bool]:
    durum = (belge.get('durum') or '').upper()
    pd = (belge.get('posting_durumu') or '').upper()
    review = can_finans_review(yk) and not is_pazarlamaci_finans_kisitli(yk)
    approve = can_finans_approve(yk) and not is_pazarlamaci_finans_kisitli(yk)
    reject = can_finans_reject(yk) and not is_pazarlamaci_finans_kisitli(yk)
    post = can_finans_post(yk) and not is_pazarlamaci_finans_kisitli(yk)
    live_ready = (
        post and durum == DURUM_ONAYLANDI and pd == POSTING_DURUM_HAZIR
        and not belge.get('cari_har_id') and CARI_ENTEGRASYON_AKTIF
    )
    return {
        'can_review': review and durum in (
            DURUM_BEKLIYOR, DURUM_DUZELTME_BEKLIYOR,
        ),
        'can_approve': approve and durum == DURUM_INCELEMEDE,
        'can_reject': reject and durum == DURUM_INCELEMEDE,
        'can_duzeltme': review and durum == DURUM_INCELEMEDE,
        'can_post': post and durum == DURUM_ONAYLANDI,
        'can_live_post': live_ready,
        'can_close': (can_finans_manage(yk) or can_finans_approve(yk)) and durum == DURUM_POST_EDILDI,
    }
