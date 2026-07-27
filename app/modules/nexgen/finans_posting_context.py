# -*- coding: utf-8 -*-
"""Posting işlem context — FAZ-GECIS Bölüm B."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PostingContext:
    transaction_id: str = ''
    idempotency_key: str = ''
    kullanici_id: int | None = None
    rol_kodu: str | None = None
    kaynak_sistem: str = 'NEXGEN'
    kaynak_tur: str | None = None
    kaynak_id: int | None = None
    olay_turu: str | None = None
    olay_versiyon: int | None = None
    finans_cari_kart_kod: str | None = None
    finans_belgesi_id: int | None = None
    belge_tarihi: str | None = None
    vade_tarihi: str | None = None
    para_birimi: str = 'TRY'
    kur: float | None = None
    aciklama: str | None = None
    audit_gerekce: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'transaction_id': self.transaction_id,
            'idempotency_key': self.idempotency_key,
            'kullanici_id': self.kullanici_id,
            'rol_kodu': self.rol_kodu,
            'kaynak_sistem': self.kaynak_sistem,
            'kaynak_tur': self.kaynak_tur,
            'kaynak_id': self.kaynak_id,
            'olay_turu': self.olay_turu,
            'olay_versiyon': self.olay_versiyon,
            'finans_cari_kart_kod': self.finans_cari_kart_kod,
            'finans_belgesi_id': self.finans_belgesi_id,
            'belge_tarihi': self.belge_tarihi,
            'vade_tarihi': self.vade_tarihi,
            'para_birimi': self.para_birimi,
            'kur': self.kur,
            'aciklama': self.aciklama,
            'audit_gerekce': self.audit_gerekce,
            'meta': dict(self.meta),
        }
