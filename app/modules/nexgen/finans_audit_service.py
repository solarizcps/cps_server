# -*- coding: utf-8 -*-
"""Finans merkezi audit yazımı — finans_audit (FAZ-FINANS-F2)."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from modules.nexgen.finans_core_config import (
    AUDIT_ENTITY_CARI_KART,
    AUDIT_ISLEM_DURUM_DEGIS,
    AUDIT_ISLEM_GUNCELLE,
    AUDIT_ISLEM_OLUSTUR,
)
from modules.nexgen.finans_belgesi_repository import tablo_var


class FinansAuditError(Exception):
    def __init__(self, mesaj: str, kod: int = 500, hata_kodu: str = 'AUDIT_HATA'):
        self.mesaj = mesaj
        self.kod = kod
        self.hata_kodu = hata_kodu
        super().__init__(mesaj)


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _json_dumps(obj: Any) -> str:
    if obj is None:
        return '{}'
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def new_transaction_id() -> str:
    return f'fin-tx-{uuid.uuid4().hex}'


def audit_yaz(
    con: sqlite3.Connection,
    *,
    islem_turu: str,
    entity_tipi: str,
    entity_id: int | str,
    eski: dict[str, Any] | None = None,
    yeni: dict[str, Any] | None = None,
    onceki_durum: str | None = None,
    yeni_durum: str | None = None,
    kullanici_id: int | None = None,
    rol_kodu: str | None = None,
    gerekce: str | None = None,
    onaylayan_id: int | None = None,
    kaynak_belge_id: int | None = None,
    transaction_id: str | None = None,
    idempotency_key: str | None = None,
    istemci_bilgisi: str | None = None,
) -> int:
    if not tablo_var(con, 'finans_audit'):
        raise FinansAuditError('finans_audit tablosu yok.', 503, 'AUDIT_TABLO_YOK')
    cur = con.execute(
        """
        INSERT INTO finans_audit (
            islem_turu, entity_tipi, entity_id, kaynak_belge_id,
            onceki_durum, yeni_durum,
            eski_degerler_json, yeni_degerler_json,
            kullanici_id, rol_kodu, islem_zamani, gerekce, onaylayan_id,
            idempotency_key, transaction_id, istemci_bilgisi
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            islem_turu,
            entity_tipi,
            int(entity_id) if str(entity_id).isdigit() else entity_id,
            kaynak_belge_id,
            onceki_durum,
            yeni_durum,
            _json_dumps(eski),
            _json_dumps(yeni),
            kullanici_id,
            rol_kodu,
            _now(),
            gerekce,
            onaylayan_id,
            idempotency_key,
            transaction_id,
            istemci_bilgisi,
        ),
    )
    return int(cur.lastrowid)


def audit_cari_kart_olustur(
    con: sqlite3.Connection,
    ckod: str,
    kart: dict[str, Any],
    *,
    kullanici_id: int | None,
    transaction_id: str,
    rol_kodu: str | None = None,
) -> int:
    return audit_yaz(
        con,
        islem_turu=AUDIT_ISLEM_OLUSTUR,
        entity_tipi=AUDIT_ENTITY_CARI_KART,
        entity_id=ckod,
        yeni=kart,
        yeni_durum='AKTIF' if kart.get('aktif') else 'PASIF',
        kullanici_id=kullanici_id,
        rol_kodu=rol_kodu,
        transaction_id=transaction_id,
    )


def audit_cari_kart_guncelle(
    con: sqlite3.Connection,
    ckod: str,
    eski: dict[str, Any],
    yeni: dict[str, Any],
    *,
    kullanici_id: int | None,
    transaction_id: str,
    gerekce: str | None = None,
    rol_kodu: str | None = None,
) -> int:
    islem = AUDIT_ISLEM_DURUM_DEGIS if eski.get('aktif') != yeni.get('aktif') else AUDIT_ISLEM_GUNCELLE
    return audit_yaz(
        con,
        islem_turu=islem,
        entity_tipi=AUDIT_ENTITY_CARI_KART,
        entity_id=ckod,
        eski=eski,
        yeni=yeni,
        onceki_durum='AKTIF' if eski.get('aktif') else 'PASIF',
        yeni_durum='AKTIF' if yeni.get('aktif') else 'PASIF',
        kullanici_id=kullanici_id,
        rol_kodu=rol_kodu,
        gerekce=gerekce,
        transaction_id=transaction_id,
    )
