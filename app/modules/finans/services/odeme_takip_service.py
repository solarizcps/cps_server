# -*- coding: utf-8 -*-
"""
odeme_takip_service.py
======================
P3A.5 — Aktif Takip Master service.

Finansal tutar TUTULMAZ — CPS yalnız aktif_takip flag'ini yönetir.
Borç her zaman Korgün kg_fn_CariHesToplam'dan gelir.

Canonical key: location + cari_kod
N+1 query YASAK: fetch_aktif_takip_map tek query döndürür.
Korgün write: KESİNLİKLE 0.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from db import get_db_path
except ImportError:
    def get_db_path() -> str:
        return os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', '..', '..', 'mock_data.db')
        )


class TakipError(Exception):
    pass


def _connect() -> sqlite3.Connection:
    db_path = get_db_path()
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def fetch_aktif_takip_map(
    locations: Optional[List[str]] = None,
) -> Dict[str, bool]:
    """
    Tek query — canonical_key → aktif_takip (bool) map.

    Döner: {'SA001|320.01.056': True, 'SA001|320.02.065': True, ...}
    aktif_takip=0 olanlar da dahil (False olarak) — Tümü görünümünde kullanılmaz
    ama Aktif Takip filtresinde kullanılır.
    N+1 YASAK: tüm lokasyonlar tek sorguda yüklenir.
    """
    con = _connect()
    try:
        if locations:
            placeholders = ','.join('?' * len(locations))
            rows = con.execute(
                f"SELECT location, cari_kod, aktif_takip FROM finans_odeme_tedarikci_takip "
                f"WHERE location IN ({placeholders})",
                locations,
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT location, cari_kod, aktif_takip FROM finans_odeme_tedarikci_takip"
            ).fetchall()
        return {
            f"{r['location']}|{r['cari_kod']}": bool(r['aktif_takip'])
            for r in rows
        }
    finally:
        con.close()


def get_takip_row(location: str, cari_kod: str) -> Optional[Dict[str, Any]]:
    """Tek cari için takip kaydını getir."""
    con = _connect()
    try:
        r = con.execute(
            "SELECT * FROM finans_odeme_tedarikci_takip WHERE location=? AND cari_kod=?",
            (location, cari_kod),
        ).fetchone()
        return dict(r) if r else None
    finally:
        con.close()


def set_aktif_takip(
    location: str,
    cari_kod: str,
    aktif: bool,
    kullanici: str,
    cari_adi_snapshot: str = '',
) -> Dict[str, Any]:
    """
    Admin: aktif_takip=True/False yap.
    Fiziksel DELETE yok — soft toggle.
    Korgün write: 0.
    Audit: updated_by, updated_at kaydedilir.
    """
    if location not in ('YN001', 'SA001', 'YP001'):
        raise TakipError(f'Gecersiz lokasyon: {location}')
    if not cari_kod or not cari_kod.strip():
        raise TakipError('Cari kod bos olamaz.')
    if not kullanici:
        raise TakipError('Kullanici adi gerekli.')

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    con = _connect()
    try:
        existing = con.execute(
            "SELECT id FROM finans_odeme_tedarikci_takip WHERE location=? AND cari_kod=?",
            (location, cari_kod),
        ).fetchone()

        if existing:
            con.execute(
                """UPDATE finans_odeme_tedarikci_takip
                   SET aktif_takip=?, updated_by=?, updated_at=?
                   WHERE location=? AND cari_kod=?""",
                (1 if aktif else 0, kullanici, now, location, cari_kod),
            )
            action = 'update'
        else:
            # Yeni kayıt — sadece admin WRITE
            con.execute(
                """INSERT INTO finans_odeme_tedarikci_takip
                   (location, cari_kod, aktif_takip, kaynak, cari_adi_snapshot,
                    created_by, created_at, updated_by, updated_at)
                   VALUES (?, ?, ?, 'MANUEL', ?, ?, ?, ?, ?)""",
                (location, cari_kod, 1 if aktif else 0, cari_adi_snapshot,
                 kullanici, now, kullanici, now),
            )
            action = 'insert'

        con.commit()
        return {
            'ok': True,
            'action': action,
            'location': location,
            'cari_kod': cari_kod,
            'aktif_takip': aktif,
            'updated_by': kullanici,
            'updated_at': now,
        }
    finally:
        con.close()


def seed_from_excel(
    excel_rows: List[Dict[str, Any]],
    location: str,
    kg_ckods: set,
    import_batch: str = '',
    kullanici: str = 'sistem',
) -> Dict[str, Any]:
    """
    Excel exact match seed — idempotent.
    YALNIZ: Excel CKod == Korgün CKod (exact match).
    320M.* seed edilmez.
    Name match seed edilmez.
    Finansal tutar OKUNMAZ.
    """
    if location not in ('YN001', 'SA001', 'YP001'):
        raise TakipError(f'Gecersiz lokasyon: {location}')

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    inserted = 0; skipped = 0; m320_skipped = 0

    con = _connect()
    try:
        for r in excel_rows:
            ckod = str(r.get('ckod', '') or '').strip()
            cname = str(r.get('cname', '') or '').strip()

            # 320M kesinlikle skip
            if ckod.startswith('320M'):
                m320_skipped += 1
                continue

            # Korgün'de exact CKod yoksa skip
            if ckod not in kg_ckods:
                continue

            try:
                con.execute(
                    """INSERT OR IGNORE INTO finans_odeme_tedarikci_takip
                       (location, cari_kod, aktif_takip, kaynak, cari_adi_snapshot,
                        import_batch, created_by, created_at)
                       VALUES (?, ?, 1, 'EXCEL_SEED', ?, ?, ?, ?)""",
                    (location, ckod, cname, import_batch, kullanici, now),
                )
                if con.execute("SELECT changes()").fetchone()[0] > 0:
                    inserted += 1
                else:
                    skipped += 1
            except sqlite3.IntegrityError:
                skipped += 1

        con.commit()
        return {
            'ok': True,
            'inserted': inserted,
            'skipped_duplicate': skipped,
            'm320_skipped': m320_skipped,
            'total': con.execute(
                "SELECT COUNT(*) FROM finans_odeme_tedarikci_takip WHERE location=?",
                (location,)
            ).fetchone()[0],
        }
    finally:
        con.close()
