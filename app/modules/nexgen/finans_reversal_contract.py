# -*- coding: utf-8 -*-
"""Reversal veri kontratı — FAZ-GECIS Bölüm B (tam ReversalService sonraki faz)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReversalLinkBundle:
    """Orijinal ↔ ters kayıt ilişki paketi — posted satır silinmez."""

    orijinal_belge_id: int | None = None
    ters_belge_id: int | None = None
    orijinal_cari_har_id: int | None = None
    ters_cari_har_id: int | None = None
    orijinal_hareket_cari_har_id: int | None = None
    ters_hareket_cari_har_id: int | None = None
    orijinal_open_item_id: int | None = None
    yeniden_acilan_open_item_id: int | None = None
    reversal_transaction_id: str | None = None
    reversal_reason: str | None = None
    kullanici_id: int | None = None
    onaylayan_id: int | None = None
    donem_kilidi_atlandi: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'orijinal_belge_id': self.orijinal_belge_id,
            'ters_belge_id': self.ters_belge_id,
            'orijinal_cari_har_id': self.orijinal_cari_har_id,
            'ters_cari_har_id': self.ters_cari_har_id,
            'orijinal_hareket_cari_har_id': self.orijinal_hareket_cari_har_id,
            'ters_hareket_cari_har_id': self.ters_hareket_cari_har_id,
            'orijinal_open_item_id': self.orijinal_open_item_id,
            'yeniden_acilan_open_item_id': self.yeniden_acilan_open_item_id,
            'reversal_transaction_id': self.reversal_transaction_id,
            'reversal_reason': self.reversal_reason,
            'kullanici_id': self.kullanici_id,
            'onaylayan_id': self.onaylayan_id,
            'donem_kilidi_atlandi': self.donem_kilidi_atlandi,
            'metadata': dict(self.metadata),
        }

    def validate(self) -> None:
        if not self.reversal_transaction_id:
            raise ValueError('reversal_transaction_id zorunlu')
        if not self.reversal_reason:
            raise ValueError('reversal_reason zorunlu')
        if not self.orijinal_cari_har_id and not self.orijinal_belge_id:
            raise ValueError('Orijinal Cari_Har veya belge referansı gerekli')


def reversal_idempotency_key(
    kaynak_sistem: str,
    kaynak_tur: str,
    kaynak_id: int,
    olay_versiyon: int | None = None,
) -> str:
    base = f'REVERSAL:{kaynak_sistem}:{kaynak_tur}:{int(kaynak_id)}'
    if olay_versiyon is not None:
        return f'{base}:v{int(olay_versiyon)}'
    return base
