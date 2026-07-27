# -*- coding: utf-8 -*-
"""Finans cari kart kimlik çözümleme — FAZ-FINANS-F2."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from modules.nexgen.finans_belgesi_repository import tablo_var
from modules.nexgen.finans_cari_kart_service import (
    FinansCariKartError,
    get_by_ckod,
    row_to_dict,
)
from modules.nexgen.finans_cari_read_service import cari_golden_durum_paket
from modules.nexgen.finans_core_config import CARI_TIP_MUSTERI, CARI_TIP_TEDARIKCI

RESOLUTION_FINANS_KART = 'FINANS_CARI_KART'
RESOLUTION_CKOD_DIRECT = 'CKOD_DIRECT'
RESOLUTION_OPERASYONEL_ESLESME = 'OPERASYONEL_ESLESME'
RESOLUTION_LEGACY_CARI_KART = 'LEGACY_CARI_KART'
RESOLUTION_BULUNAMADI = 'BULUNAMADI'


class FinansCariIdentityError(Exception):
    def __init__(self, mesaj: str, kod: int = 409, hata_kodu: str = 'CARI_KIMLIK_HATA'):
        self.mesaj = mesaj
        self.kod = kod
        self.hata_kodu = hata_kodu
        super().__init__(mesaj)


@dataclass
class CariIdentityResolution:
    finance_card_id: str | None
    finance_card_code: str | None
    resolution_source: str
    is_legacy_fallback: bool = False
    requires_manual_link: bool = False
    warnings: list[str] = field(default_factory=list)
    finans_kart: dict[str, Any] | None = None
    operasyonel_baglantilar: list[dict[str, Any]] = field(default_factory=list)
    legacy_cari_kart: dict[str, Any] | None = None
    aktif: bool | None = None
    hata_kodu: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'finance_card_id': self.finance_card_id,
            'finance_card_code': self.finance_card_code,
            'resolution_source': self.resolution_source,
            'is_legacy_fallback': self.is_legacy_fallback,
            'requires_manual_link': self.requires_manual_link,
            'warnings': list(self.warnings),
            'finans_kart': self.finans_kart,
            'operasyonel_baglantilar': self.operasyonel_baglantilar,
            'legacy_cari_kart': self.legacy_cari_kart,
            'aktif': self.aktif,
            'hata_kodu': self.hata_kodu,
        }


def _legacy_cari_kart(con: sqlite3.Connection, ckod: str) -> dict[str, Any] | None:
    if not tablo_var(con, 'Cari_Kart'):
        return None
    row = con.execute(
        'SELECT CKod, CName, CTip, Bakiye, Aktif FROM Cari_Kart WHERE CKod=?',
        (ckod,),
    ).fetchone()
    return dict(row) if row else None


def operasyonel_baglantilar(con: sqlite3.Connection, ckod: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if tablo_var(con, 'cari_eslestirme'):
        for r in con.execute(
            """
            SELECT nexgen_cari_id, eslestirme_durumu, eslestirme_yontemi, aktif
            FROM cari_eslestirme
            WHERE cari_kart_ckod=? AND aktif=1
            """,
            (ckod,),
        ).fetchall():
            out.append({
                'tip': CARI_TIP_MUSTERI,
                'operasyonel_id': int(r['nexgen_cari_id']),
                'durum': r['eslestirme_durumu'],
                'yontem': r['eslestirme_yontemi'],
            })
    if tablo_var(con, 'tedarikci_eslestirme'):
        for r in con.execute(
            """
            SELECT nexgen_tedarikci_id, eslestirme_durumu, aktif
            FROM tedarikci_eslestirme
            WHERE cari_kart_ckod=? AND aktif=1
            """,
            (ckod,),
        ).fetchall():
            out.append({
                'tip': CARI_TIP_TEDARIKCI,
                'operasyonel_id': int(r['nexgen_tedarikci_id']),
                'durum': r['eslestirme_durumu'],
                'yontem': None,
            })
    if tablo_var(con, 'finans_cari_kimlik'):
        for r in con.execute(
            """
            SELECT kimlik_tipi, nexgen_cari_id, nexgen_tedarikci_id, durum, aktif
            FROM finans_cari_kimlik
            WHERE cari_kart_ckod=? AND aktif=1
            """,
            (ckod,),
        ).fetchall():
            tip = (r['kimlik_tipi'] or '').upper()
            oid = r['nexgen_cari_id'] if tip == CARI_TIP_MUSTERI else r['nexgen_tedarikci_id']
            if oid:
                out.append({
                    'tip': tip,
                    'operasyonel_id': int(oid),
                    'durum': r['durum'],
                    'yontem': 'finans_cari_kimlik',
                })
    return out


def resolve_by_ckod(
    con: sqlite3.Connection,
    ckod: str,
    *,
    allow_legacy_fallback: bool = True,
    require_active: bool = True,
) -> CariIdentityResolution:
    ckod = (ckod or '').strip()
    if not ckod:
        return CariIdentityResolution(
            finance_card_id=None,
            finance_card_code=None,
            resolution_source=RESOLUTION_BULUNAMADI,
            requires_manual_link=True,
            hata_kodu='CKOD_BOS',
        )

    legacy = _legacy_cari_kart(con, ckod)
    baglantilar = operasyonel_baglantilar(con, ckod)

    try:
        kart = get_by_ckod(con, ckod)
        fd = row_to_dict(kart)
        if require_active and not fd.get('aktif'):
            raise FinansCariIdentityError(
                f'Finans cari kart pasif: {ckod}', 409, 'FINANS_KART_PASIF',
            )
        return CariIdentityResolution(
            finance_card_id=ckod,
            finance_card_code=ckod,
            resolution_source=RESOLUTION_FINANS_KART,
            finans_kart=fd,
            operasyonel_baglantilar=baglantilar,
            legacy_cari_kart=legacy,
            aktif=bool(fd.get('aktif')),
        )
    except FinansCariKartError as e:
        if e.hata_kodu == 'FINANS_KART_PASIF':
            raise FinansCariIdentityError(e.mesaj, e.kod, e.hata_kodu) from e
        if e.hata_kodu != 'FINANS_KART_YOK':
            raise FinansCariIdentityError(e.mesaj, e.kod, e.hata_kodu) from e

    if legacy and allow_legacy_fallback:
        return CariIdentityResolution(
            finance_card_id=None,
            finance_card_code=ckod,
            resolution_source=RESOLUTION_LEGACY_CARI_KART,
            is_legacy_fallback=True,
            requires_manual_link=True,
            warnings=['Finans cari kart overlay yok — legacy Cari_Kart fallback.'],
            legacy_cari_kart=legacy,
            operasyonel_baglantilar=baglantilar,
            aktif=True,
            hata_kodu='FINANS_KART_YOK',
        )

    return CariIdentityResolution(
        finance_card_id=None,
        finance_card_code=ckod if legacy else None,
        resolution_source=RESOLUTION_BULUNAMADI,
        requires_manual_link=True,
        warnings=['Cari kart kaydı bulunamadı.'],
        legacy_cari_kart=legacy,
        operasyonel_baglantilar=baglantilar,
        hata_kodu='CARI_KART_YOK' if not legacy else 'FINANS_KART_YOK',
    )


def resolve_by_operasyonel(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
    *,
    allow_legacy_fallback: bool = True,
    require_active: bool = True,
) -> CariIdentityResolution:
    tip = (cari_tipi or '').strip().upper()
    oid = int(operasyonel_id)
    aday_ckodlar: set[str] = set()

    if tip == CARI_TIP_MUSTERI:
        g = cari_golden_durum_paket(con, oid)
        if g.get('cari_kart_ckod'):
            aday_ckodlar.add(g['cari_kart_ckod'])
        if tablo_var(con, 'cari_eslestirme'):
            for r in con.execute(
                """
                SELECT cari_kart_ckod FROM cari_eslestirme
                WHERE nexgen_cari_id=? AND aktif=1
                  AND cari_kart_ckod IS NOT NULL AND cari_kart_ckod != ''
                """,
                (oid,),
            ).fetchall():
                aday_ckodlar.add(r['cari_kart_ckod'])
        if tablo_var(con, 'finans_cari_kimlik'):
            for r in con.execute(
                """
                SELECT cari_kart_ckod FROM finans_cari_kimlik
                WHERE nexgen_cari_id=? AND aktif=1
                  AND cari_kart_ckod IS NOT NULL AND cari_kart_ckod != ''
                """,
                (oid,),
            ).fetchall():
                aday_ckodlar.add(r['cari_kart_ckod'])
    elif tip == CARI_TIP_TEDARIKCI:
        if tablo_var(con, 'tedarikci_eslestirme'):
            for r in con.execute(
                """
                SELECT cari_kart_ckod FROM tedarikci_eslestirme
                WHERE nexgen_tedarikci_id=? AND aktif=1
                  AND cari_kart_ckod IS NOT NULL AND cari_kart_ckod != ''
                """,
                (oid,),
            ).fetchall():
                aday_ckodlar.add(r['cari_kart_ckod'])
        if tablo_var(con, 'finans_cari_kimlik'):
            for r in con.execute(
                """
                SELECT cari_kart_ckod FROM finans_cari_kimlik
                WHERE nexgen_tedarikci_id=? AND aktif=1
                  AND cari_kart_ckod IS NOT NULL AND cari_kart_ckod != ''
                """,
                (oid,),
            ).fetchall():
                aday_ckodlar.add(r['cari_kart_ckod'])
    else:
        raise FinansCariIdentityError('Geçersiz cari tipi.', 400, 'CARI_TIP_GECERSIZ')

    if not aday_ckodlar:
        return CariIdentityResolution(
            finance_card_id=None,
            finance_card_code=None,
            resolution_source=RESOLUTION_BULUNAMADI,
            requires_manual_link=True,
            warnings=['Operasyonel cari için kart bağlantısı yok.'],
            hata_kodu='KART_BAGLANTISI_EKSIK',
        )

    if len(aday_ckodlar) > 1:
        raise FinansCariIdentityError(
            'Birden fazla aktif cari kart bağlantısı — manuel çözüm gerekli.',
            409,
            'CARI_ESLESME_CAKISMA',
        )

    ckod = next(iter(aday_ckodlar))
    res = resolve_by_ckod(
        con, ckod,
        allow_legacy_fallback=allow_legacy_fallback,
        require_active=require_active,
    )
    if res.resolution_source in (RESOLUTION_FINANS_KART, RESOLUTION_LEGACY_CARI_KART, RESOLUTION_BULUNAMADI):
        res.resolution_source = RESOLUTION_OPERASYONEL_ESLESME
    return res
