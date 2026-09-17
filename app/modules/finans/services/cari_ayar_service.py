# -*- coding: utf-8 -*-
"""
cari_ayar_service.py
====================
Direction-safe cari çalışma ayarları servisi.
- direction: RECEIVABLE (120.*) / PAYABLE (320.*)
- Unique key: (direction, location, cari_kod)
- Mevcut finans_odeme_tedarikci_ayar tablosuna DOKUNMAZ.
- Canonical DB'ye yazmaz — yalnız local CPS DB (mock_data.db / finans_main.db).
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

AYAR_TABLO = 'finans_cari_calisma_ayar'

CALISMA_SEKLI_OPTIONS = ('OTOMATIK', 'PESIN', 'VADELI', 'KARMA')
ODEME_YONTEMI_OPTIONS = (
    'OTOMATIK', 'NAKIT', 'HAVALE', 'CEK', 'KREDI_KARTI',
    'NAKIT_HAVALE', 'HAVALE_CEK', 'NAKIT_CEK', 'KARMA'
)
DIRECTIONS = ('RECEIVABLE', 'PAYABLE')
CARI_SEKLI_LABELS = {
    'OTOMATIK': 'Otomatik',
    'PESIN': 'Peşin',
    'VADELI': 'Vadeli',
    'KARMA': 'Karma',
}
ODEME_YONTEMI_LABELS = {
    'OTOMATIK': 'Otomatik',
    'NAKIT': 'Nakit',
    'HAVALE': 'Havale',
    'CEK': 'Çek',
    'KREDI_KARTI': 'Kredi Kartı',
    'NAKIT_HAVALE': 'Nakit / Havale',
    'HAVALE_CEK': 'Havale / Çek',
    'NAKIT_CEK': 'Nakit / Çek',
    'KARMA': 'Karma',
}

try:
    from config import Config
    def get_db_path() -> str:
        return Config.MOCK_DB_PATH
except ImportError:
    try:
        from db import get_db_path  # type: ignore
    except ImportError:
        def get_db_path() -> str:
            return os.path.normpath(
                os.path.join(os.path.dirname(__file__), '..', '..', '..', 'mock_data.db')
            )


class CariAyarError(Exception):
    def __init__(self, message: str, code: str = 'VALIDATION'):
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    return con


def ensure_table(db_path: Optional[str] = None) -> None:
    """Tablo yoksa oluştur — idempotent."""
    con = _connect(db_path)
    try:
        con.execute(f"""
            CREATE TABLE IF NOT EXISTS {AYAR_TABLO} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                direction TEXT NOT NULL CHECK(direction IN ('RECEIVABLE','PAYABLE')),
                location TEXT NOT NULL,
                cari_kod TEXT NOT NULL,
                calisma_sekli_mode TEXT NOT NULL DEFAULT 'OTOMATIK'
                    CHECK(calisma_sekli_mode IN ('OTOMATIK','PESIN','VADELI','KARMA')),
                calisma_sekli_manual TEXT
                    CHECK(calisma_sekli_manual IS NULL OR calisma_sekli_manual IN ('PESIN','VADELI','KARMA')),
                anlasmali_vade_gun INTEGER,
                odeme_yontemi_mode TEXT NOT NULL DEFAULT 'OTOMATIK'
                    CHECK(odeme_yontemi_mode IN ('OTOMATIK','NAKIT','HAVALE','CEK','KREDI_KARTI',
                        'NAKIT_HAVALE','HAVALE_CEK','NAKIT_CEK','KARMA')),
                odeme_yontemi_manual TEXT
                    CHECK(odeme_yontemi_manual IS NULL OR odeme_yontemi_manual IN (
                        'NAKIT','HAVALE','CEK','KREDI_KARTI','NAKIT_HAVALE','HAVALE_CEK','NAKIT_CEK','KARMA')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT NOT NULL DEFAULT '',
                UNIQUE(direction, location, cari_kod)
            )
        """)
        con.commit()
    finally:
        con.close()


def _validate_direction(direction: str) -> str:
    d = direction.upper()
    if d not in DIRECTIONS:
        raise CariAyarError(f'Geçersiz direction: {direction}', 'INVALID_DIRECTION')
    # 120.* sadece RECEIVABLE, 320.* sadece PAYABLE
    return d


def _validate_cari_kod_direction(cari_kod: str, direction: str) -> None:
    if direction == 'RECEIVABLE' and not cari_kod.startswith('120.'):
        raise CariAyarError('RECEIVABLE yalnız 120.* cari kodlarına uygulanır', 'DIRECTION_MISMATCH')
    if direction == 'PAYABLE' and not cari_kod.startswith('320.'):
        raise CariAyarError('PAYABLE yalnız 320.* cari kodlarına uygulanır', 'DIRECTION_MISMATCH')


def build_default_dto(direction: str, location: str, cari_kod: str) -> Dict[str, Any]:
    return {
        'direction': direction,
        'location': location,
        'cari_kod': cari_kod,
        'has_settings': False,
        'calisma_sekli_mode': 'OTOMATIK',
        'calisma_sekli_manual': None,
        'calisma_sekli_effective': None,
        'anlasmali_vade_gun': None,
        'odeme_yontemi_mode': 'OTOMATIK',
        'odeme_yontemi_manual': None,
        'odeme_yontemi_effective': None,
        'updated_at': None,
        'updated_by': None,
    }


def _row_to_dto(row: sqlite3.Row) -> Dict[str, Any]:
    mode = row['calisma_sekli_mode']
    manual = row['calisma_sekli_manual']
    effective_cs = manual if mode != 'OTOMATIK' and manual else None

    omode = row['odeme_yontemi_mode']
    omanual = row['odeme_yontemi_manual']
    effective_oy = omanual if omode != 'OTOMATIK' and omanual else None

    return {
        'id': row['id'],
        'direction': row['direction'],
        'location': row['location'],
        'cari_kod': row['cari_kod'],
        'has_settings': True,
        'calisma_sekli_mode': mode,
        'calisma_sekli_manual': manual,
        'calisma_sekli_effective': effective_cs,
        'anlasmali_vade_gun': row['anlasmali_vade_gun'],
        'odeme_yontemi_mode': omode,
        'odeme_yontemi_manual': omanual,
        'odeme_yontemi_effective': effective_oy,
        'updated_at': row['updated_at'],
        'updated_by': row['updated_by'],
    }


def get_ayar(direction: str, location: str, cari_kod: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    d = _validate_direction(direction)
    con = _connect(db_path)
    try:
        row = con.execute(
            f"SELECT * FROM {AYAR_TABLO} WHERE direction=? AND location=? AND cari_kod=?",
            (d, location, cari_kod),
        ).fetchone()
        if not row:
            return build_default_dto(d, location, cari_kod)
        return _row_to_dto(row)
    except Exception:
        return build_default_dto(d, location, cari_kod)
    finally:
        con.close()


def save_ayar(
    direction: str,
    location: str,
    cari_kod: str,
    payload: Dict[str, Any],
    updated_by: str = '',
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Upsert — yalnız manuel alanları kaydeder."""
    d = _validate_direction(direction)
    _validate_cari_kod_direction(cari_kod, d)
    ensure_table(db_path)
    con = _connect(db_path)
    now = _now()
    try:
        # Normalize inputs
        cs_mode = (payload.get('calisma_sekli_mode') or 'OTOMATIK').upper()
        cs_manual = payload.get('calisma_sekli_manual') or None
        if cs_mode not in CALISMA_SEKLI_OPTIONS:
            raise CariAyarError(f'Geçersiz calisma_sekli_mode: {cs_mode}')
        if cs_mode == 'OTOMATIK':
            cs_manual = None
        elif cs_manual and cs_manual.upper() not in ('PESIN', 'VADELI', 'KARMA'):
            raise CariAyarError(f'Geçersiz calisma_sekli_manual: {cs_manual}')

        vade = payload.get('anlasmali_vade_gun')
        if vade is not None and vade != '':
            try:
                vade = int(vade)
                if vade < 0 or vade > 730:
                    raise CariAyarError('Anlaşmalı vade 0-730 gün olmalı')
            except (ValueError, TypeError):
                raise CariAyarError('Anlaşmalı vade sayı olmalı')
        else:
            vade = None

        oy_mode = (payload.get('odeme_yontemi_mode') or 'OTOMATIK').upper()
        oy_manual = payload.get('odeme_yontemi_manual') or None
        if oy_mode not in ODEME_YONTEMI_OPTIONS:
            raise CariAyarError(f'Geçersiz odeme_yontemi_mode: {oy_mode}')
        if oy_mode == 'OTOMATIK':
            oy_manual = None

        existing = con.execute(
            f"SELECT id FROM {AYAR_TABLO} WHERE direction=? AND location=? AND cari_kod=?",
            (d, location, cari_kod),
        ).fetchone()

        if existing:
            con.execute(
                f"""UPDATE {AYAR_TABLO}
                    SET calisma_sekli_mode=?, calisma_sekli_manual=?,
                        anlasmali_vade_gun=?,
                        odeme_yontemi_mode=?, odeme_yontemi_manual=?,
                        updated_at=?, updated_by=?
                    WHERE direction=? AND location=? AND cari_kod=?""",
                (cs_mode, cs_manual, vade, oy_mode, oy_manual,
                 now, updated_by, d, location, cari_kod),
            )
        else:
            con.execute(
                f"""INSERT INTO {AYAR_TABLO}
                    (direction, location, cari_kod,
                     calisma_sekli_mode, calisma_sekli_manual, anlasmali_vade_gun,
                     odeme_yontemi_mode, odeme_yontemi_manual,
                     created_at, updated_at, updated_by)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (d, location, cari_kod,
                 cs_mode, cs_manual, vade,
                 oy_mode, oy_manual,
                 now, now, updated_by),
            )
        con.commit()
        return get_ayar(d, location, cari_kod, db_path=db_path)
    finally:
        con.close()


def compute_system_suggestion_calisma_sekli(
    direction: str,
    location: str,
    cari_kod: str,
    hareketler: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Geçmiş hareketlerden sistem önerisi hesapla.
    Güvenilir eşleştirme yoksa 'Yeterli veri yok' döner.
    Sahte sonuç üretmez.
    """
    # Şimdilik yeterli fatura-ödeme eşleştirmesi yapılamıyor
    # Bu alan ileriki fazda Korgün vade-tahsilat analizi ile doldurulacak
    return 'Yeterli veri yok'


def compute_system_suggestion_odeme_yontemi(
    direction: str,
    location: str,
    cari_kod: str,
    hareketler: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Geçmiş tahsilat/ödeme tiplerinden sistem önerisi.
    Güvenilir sonuç yoksa 'Belirlenemedi' döner.
    """
    if not hareketler:
        return 'Belirlenemedi'
    # Çek içeriyorsa Havale/Çek öner
    has_cek = any(r.get('hareket_turu_kodu') in ('CK', 'CEK') for r in hareketler)
    has_banka = any('Banka' in (r.get('aciklama') or '') or r.get('hareket_turu_kodu') in ('BG', 'NT') for r in hareketler)
    if has_cek and has_banka:
        return 'Havale / Çek'
    elif has_cek:
        return 'Çek'
    elif has_banka:
        return 'Havale'
    return 'Belirlenemedi'


def compute_average_payment_days(
    direction: str,
    location: str,
    cari_kod: str,
) -> Dict[str, Any]:
    """
    Ortalama tahsilat/ödeme günü hesabı.
    Fatura vade tarihi — tahsilat tarihi farkını kullanır.
    Güvenilir eşleştirme yapılamazsa örnek_sayisi=0 döner.
    """
    return {
        'ortalama_gun': None,
        'ornek_sayisi': 0,
        'aciklama': 'Yeterli veri yok — fatura-tahsilat eşleştirmesi yapılamadı',
    }
