# -*- coding: utf-8 -*-
"""Finans cari kart write/read servisi — FAZ-FINANS-F2 (CariCardService)."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from modules.nexgen.finans_audit_service import (
    FinansAuditError,
    audit_cari_kart_guncelle,
    audit_cari_kart_olustur,
    new_transaction_id,
)
from modules.nexgen.finans_belgesi_repository import tablo_var
from modules.nexgen.finans_core_config import CARI_TIPLER

ODEME_SEKLLERI = ('NAKIT', 'EFT', 'HAVALE', 'CEK', 'KART', 'MAHSUP')


class FinansCariKartError(Exception):
    def __init__(self, mesaj: str, kod: int = 400, hata_kodu: str = 'CARI_KART_HATA'):
        self.mesaj = mesaj
        self.kod = kod
        self.hata_kodu = hata_kodu
        super().__init__(mesaj)


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def row_to_dict(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {}
    d = dict(row)
    d['aktif'] = bool(d.get('aktif'))
    return d


def _validate_tip(tip: str) -> str:
    t = (tip or '').strip().upper()
    if t not in CARI_TIPLER:
        raise FinansCariKartError(
            f'Geçersiz cari tipi: {tip}', 400, 'CARI_TIP_GECERSIZ',
        )
    return t


def _validate_odeme_sekli(v: str | None) -> str | None:
    if v is None or str(v).strip() == '':
        return None
    s = str(v).strip().upper()
    if s not in ODEME_SEKLLERI:
        raise FinansCariKartError(
            f'Geçersiz ödeme şekli: {v}', 400, 'ODEME_SEKLI_GECERSIZ',
        )
    return s


def get_by_ckod(con: sqlite3.Connection, ckod: str) -> sqlite3.Row:
    ckod = (ckod or '').strip()
    if not ckod:
        raise FinansCariKartError('CKod boş.', 400, 'CKOD_BOS')
    if not tablo_var(con, 'finans_cari_kart'):
        raise FinansCariKartError('finans_cari_kart tablosu yok.', 503, 'TABLO_YOK')
    row = con.execute('SELECT * FROM finans_cari_kart WHERE ckod=?', (ckod,)).fetchone()
    if not row:
        raise FinansCariKartError(f'Finans cari kart bulunamadı: {ckod}', 404, 'FINANS_KART_YOK')
    if not row['aktif']:
        raise FinansCariKartError(f'Finans cari kart pasif: {ckod}', 409, 'FINANS_KART_PASIF')
    return row


def get_by_ckod_raw(con: sqlite3.Connection, ckod: str) -> sqlite3.Row | None:
    ckod = (ckod or '').strip()
    if not ckod or not tablo_var(con, 'finans_cari_kart'):
        return None
    return con.execute('SELECT * FROM finans_cari_kart WHERE ckod=?', (ckod,)).fetchone()


def create(
    con: sqlite3.Connection,
    *,
    ckod: str,
    unvan: str,
    tip: str,
    para_birimi: str = 'TRY',
    aktif: bool = True,
    varsayilan_vade_gun: int | None = None,
    varsayilan_odeme_sekli: str | None = None,
    risk_limiti: float | None = None,
    kredi_limiti: float | None = None,
    vergi_no: str | None = None,
    vergi_dairesi: str | None = None,
    kullanici_id: int | None = None,
    rol_kodu: str | None = None,
    owns_transaction: bool = True,
) -> dict[str, Any]:
    ckod = (ckod or '').strip()
    if not ckod:
        raise FinansCariKartError('CKod zorunlu.', 400, 'CKOD_BOS')
    if not tablo_var(con, 'finans_cari_kart'):
        raise FinansCariKartError('finans_cari_kart tablosu yok.', 503, 'TABLO_YOK')
    if not tablo_var(con, 'Cari_Kart'):
        raise FinansCariKartError('Cari_Kart tablosu yok.', 503, 'CARI_KART_TABLO_YOK')
    legacy = con.execute('SELECT CKod FROM Cari_Kart WHERE CKod=?', (ckod,)).fetchone()
    if not legacy:
        raise FinansCariKartError(
            f'Legacy Cari_Kart kaydı yok — önce kart oluşturulmalı: {ckod}',
            409,
            'LEGACY_CARI_KART_YOK',
        )
    mevcut = con.execute('SELECT ckod FROM finans_cari_kart WHERE ckod=?', (ckod,)).fetchone()
    if mevcut:
        raise FinansCariKartError(
            f'Aynı CKod ile finans cari kart zaten var: {ckod}', 409, 'FINANS_KART_MEVCUT',
        )

    tip_v = _validate_tip(tip)
    odeme = _validate_odeme_sekli(varsayilan_odeme_sekli)
    unvan_s = (unvan or '').strip()
    if not unvan_s:
        raise FinansCariKartError('Unvan zorunlu.', 400, 'UNVAN_BOS')

    tx_id = new_transaction_id()
    if owns_transaction:
        con.execute('BEGIN IMMEDIATE')
    try:
        con.execute(
            """
            INSERT INTO finans_cari_kart (
                ckod, unvan, tip, para_birimi, aktif,
                varsayilan_vade_gun, varsayilan_odeme_sekli,
                risk_limiti, kredi_limiti, vergi_no, vergi_dairesi,
                versiyon, olusturma_tarihi, olusturan_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                ckod, unvan_s, tip_v, (para_birimi or 'TRY').strip().upper(),
                1 if aktif else 0,
                varsayilan_vade_gun, odeme,
                risk_limiti, kredi_limiti,
                vergi_no, vergi_dairesi,
                _now(), kullanici_id,
            ),
        )
        kart = row_to_dict(get_by_ckod_raw(con, ckod))
        audit_cari_kart_olustur(
            con, ckod, kart,
            kullanici_id=kullanici_id,
            transaction_id=tx_id,
            rol_kodu=rol_kodu,
        )
        if owns_transaction:
            con.commit()
        return kart
    except FinansAuditError:
        if owns_transaction:
            con.rollback()
        raise FinansCariKartError('Audit yazılamadı — işlem geri alındı.', 500, 'AUDIT_HATA') from None
    except sqlite3.IntegrityError as e:
        if owns_transaction:
            con.rollback()
        raise FinansCariKartError(
            f'Finans cari kart oluşturulamadı: {e}', 409, 'FINANS_KART_CAKISMA',
        ) from e
    except Exception:
        if owns_transaction:
            con.rollback()
        raise


def update(
    con: sqlite3.Connection,
    ckod: str,
    *,
    beklenen_versiyon: int,
    unvan: str | None = None,
    tip: str | None = None,
    para_birimi: str | None = None,
    varsayilan_vade_gun: int | None = None,
    varsayilan_odeme_sekli: str | None = None,
    risk_limiti: float | None = None,
    kredi_limiti: float | None = None,
    vergi_no: str | None = None,
    vergi_dairesi: str | None = None,
    kullanici_id: int | None = None,
    rol_kodu: str | None = None,
    gerekce: str | None = None,
    owns_transaction: bool = True,
) -> dict[str, Any]:
    ckod = (ckod or '').strip()
    row = get_by_ckod_raw(con, ckod)
    if not row:
        raise FinansCariKartError(f'Finans cari kart bulunamadı: {ckod}', 404, 'FINANS_KART_YOK')
    eski = row_to_dict(row)
    if int(eski.get('versiyon') or 0) != int(beklenen_versiyon):
        raise FinansCariKartError(
            'Versiyon uyuşmazlığı — kayıt başka kullanıcı tarafından güncellenmiş.',
            409,
            'VERSIYON_CAKISMA',
        )

    yeni = dict(eski)
    if unvan is not None:
        yeni['unvan'] = (unvan or '').strip()
    if tip is not None:
        yeni['tip'] = _validate_tip(tip)
    if para_birimi is not None:
        yeni['para_birimi'] = (para_birimi or 'TRY').strip().upper()
    if varsayilan_vade_gun is not None:
        yeni['varsayilan_vade_gun'] = varsayilan_vade_gun
    if varsayilan_odeme_sekli is not None:
        yeni['varsayilan_odeme_sekli'] = _validate_odeme_sekli(varsayilan_odeme_sekli)
    if risk_limiti is not None:
        yeni['risk_limiti'] = risk_limiti
    if kredi_limiti is not None:
        yeni['kredi_limiti'] = kredi_limiti
    if vergi_no is not None:
        yeni['vergi_no'] = vergi_no
    if vergi_dairesi is not None:
        yeni['vergi_dairesi'] = vergi_dairesi

    tx_id = new_transaction_id()
    if owns_transaction:
        con.execute('BEGIN IMMEDIATE')
    try:
        con.execute(
            """
            UPDATE finans_cari_kart SET
                unvan=?, tip=?, para_birimi=?,
                varsayilan_vade_gun=?, varsayilan_odeme_sekli=?,
                risk_limiti=?, kredi_limiti=?, vergi_no=?, vergi_dairesi=?,
                versiyon=versiyon+1, guncelleme_tarihi=?, guncelleyen_id=?
            WHERE ckod=? AND versiyon=?
            """,
            (
                yeni['unvan'], yeni['tip'], yeni['para_birimi'],
                yeni.get('varsayilan_vade_gun'), yeni.get('varsayilan_odeme_sekli'),
                yeni.get('risk_limiti'), yeni.get('kredi_limiti'),
                yeni.get('vergi_no'), yeni.get('vergi_dairesi'),
                _now(), kullanici_id,
                ckod, beklenen_versiyon,
            ),
        )
        if con.total_changes == 0:
            raise FinansCariKartError('Versiyon uyuşmazlığı.', 409, 'VERSIYON_CAKISMA')
        guncel = row_to_dict(get_by_ckod_raw(con, ckod))
        audit_cari_kart_guncelle(
            con, ckod, eski, guncel,
            kullanici_id=kullanici_id,
            transaction_id=tx_id,
            gerekce=gerekce,
            rol_kodu=rol_kodu,
        )
        if owns_transaction:
            con.commit()
        return guncel
    except FinansAuditError:
        if owns_transaction:
            con.rollback()
        raise FinansCariKartError('Audit yazılamadı — işlem geri alındı.', 500, 'AUDIT_HATA') from None
    except FinansCariKartError:
        if owns_transaction:
            con.rollback()
        raise
    except Exception:
        if owns_transaction:
            con.rollback()
        raise


def set_aktif(
    con: sqlite3.Connection,
    ckod: str,
    *,
    aktif: bool,
    beklenen_versiyon: int,
    kullanici_id: int | None = None,
    rol_kodu: str | None = None,
    gerekce: str | None = None,
    owns_transaction: bool = True,
) -> dict[str, Any]:
    ckod = (ckod or '').strip()
    row = get_by_ckod_raw(con, ckod)
    if not row:
        raise FinansCariKartError(f'Finans cari kart bulunamadı: {ckod}', 404, 'FINANS_KART_YOK')
    eski = row_to_dict(row)
    if int(eski.get('versiyon') or 0) != int(beklenen_versiyon):
        raise FinansCariKartError('Versiyon uyuşmazlığı.', 409, 'VERSIYON_CAKISMA')

    tx_id = new_transaction_id()
    if owns_transaction:
        con.execute('BEGIN IMMEDIATE')
    try:
        con.execute(
            """
            UPDATE finans_cari_kart SET
                aktif=?, versiyon=versiyon+1, guncelleme_tarihi=?, guncelleyen_id=?
            WHERE ckod=? AND versiyon=?
            """,
            (1 if aktif else 0, _now(), kullanici_id, ckod, beklenen_versiyon),
        )
        if con.total_changes == 0:
            raise FinansCariKartError('Versiyon uyuşmazlığı.', 409, 'VERSIYON_CAKISMA')
        yeni = row_to_dict(get_by_ckod_raw(con, ckod))
        audit_cari_kart_guncelle(
            con, ckod, eski, yeni,
            kullanici_id=kullanici_id,
            transaction_id=tx_id,
            gerekce=gerekce or ('Pasifleştirme' if not aktif else 'Aktifleştirme'),
            rol_kodu=rol_kodu,
        )
        if owns_transaction:
            con.commit()
        return yeni
    except FinansAuditError:
        if owns_transaction:
            con.rollback()
        raise FinansCariKartError('Audit yazılamadı — işlem geri alındı.', 500, 'AUDIT_HATA') from None
    except FinansCariKartError:
        if owns_transaction:
            con.rollback()
        raise
    except Exception:
        if owns_transaction:
            con.rollback()
        raise
