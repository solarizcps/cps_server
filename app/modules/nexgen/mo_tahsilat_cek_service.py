# -*- coding: utf-8 -*-
"""
mo_tahsilat_cek_service.py
===========================
mo_tahsilat_cek CRUD — çek satırı ekle/güncelle/sil/listele.

Kurallar:
  - Parent mevcut ve TASLAK/REVIZYON_ISTENDI olmalı.
  - Parent odeme_tipi = CEK olmalı.
  - Child PB = parent PB.
  - tutar > 0.
  - Tarihler ISO YYYY-MM-DD.
  - idempotency_key UNIQUE.
  - Soft delete (aktif=0).
  - ONAYLANDI parent readonly.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from modules.nexgen.mo_tahsilat_config import (
    KAYIT_DUZENLENEBILIR,
)

# CEK odeme_tipi sabiti — config döngüsünü önlemek için burada literal
_CEK = "CEK"


class MoCekError(Exception):
    def __init__(self, mesaj: str, kod: int = 400):
        self.mesaj = mesaj
        self.kod = kod
        super().__init__(mesaj)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
    )


def _parent_row(con: sqlite3.Connection, tahsilat_kayit_id: int) -> sqlite3.Row:
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT id, durum, odeme_tipi, para_birimi, siparis_id, olusturan_id "
        "FROM mo_tahsilat_kayit WHERE id=? AND aktif=1",
        (tahsilat_kayit_id,),
    ).fetchone()
    if not row:
        raise MoCekError("Tahsilat kaydı bulunamadı.", 404)
    return row


def _assert_duzenlenebilir(row: sqlite3.Row) -> None:
    if row["durum"] not in KAYIT_DUZENLENEBILIR:
        raise MoCekError(
            f"Bu tahsilat kaydı düzenlenemez (durum: {row['durum']}).", 409
        )
    if (row["odeme_tipi"] or "").upper() != _CEK:
        raise MoCekError("Çek satırı yalnız CEK tipli tahsilat paketine eklenebilir.", 400)


def _validate_cek(payload: dict, parent_pb: str) -> dict:
    """Bir çek satırı payload'ını validate et ve normalize et."""
    try:
        tutar = Decimal(str(payload.get("tutar") or "0"))
    except InvalidOperation:
        raise MoCekError("Geçersiz tutar.", 400)
    if tutar <= Decimal("0"):
        raise MoCekError("Tutar sıfırdan büyük olmalı.", 400)

    vade = (payload.get("gercek_cek_vade_tarihi") or "").strip()[:10]
    if not vade or len(vade) < 10:
        raise MoCekError("Çek vade tarihi zorunlu (YYYY-MM-DD).", 400)
    try:
        from datetime import date
        date.fromisoformat(vade)
    except ValueError:
        raise MoCekError(f"Geçersiz vade tarihi: {vade!r}", 400)

    alim = (payload.get("cek_alim_tarihi") or "").strip()[:10] or None
    if alim:
        try:
            from datetime import date
            date.fromisoformat(alim)
        except ValueError:
            raise MoCekError(f"Geçersiz alım tarihi: {alim!r}", 400)

    pb = (payload.get("para_birimi") or parent_pb or "TRY").strip().upper()
    if pb != (parent_pb or "TRY").strip().upper():
        raise MoCekError(
            f"Para birimi uyumsuzluğu: paket={parent_pb}, çek={pb}", 400
        )

    sira = int(payload.get("sira_no") or 1)

    return {
        "tutar": float(tutar),
        "para_birimi": pb,
        "gercek_cek_vade_tarihi": vade,
        "cek_alim_tarihi": alim,
        "odeme_referansi": (payload.get("odeme_referansi") or "").strip() or None,
        "banka_adi": (payload.get("banka_adi") or "").strip() or None,
        "sira_no": sira,
    }


def _idem_key(tahsilat_kayit_id: int, extra: str) -> str:
    raw = f"cek-{tahsilat_kayit_id}-{extra}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def cek_listele(
    con: sqlite3.Connection,
    tahsilat_kayit_id: int,
    sadece_aktif: bool = True,
) -> list[dict[str, Any]]:
    """Aktif (veya tüm) çek satırlarını döner."""
    if not _tablo_var(con, "mo_tahsilat_cek"):
        return []
    con.row_factory = sqlite3.Row
    q = (
        "SELECT * FROM mo_tahsilat_cek WHERE tahsilat_kayit_id=?"
        + (" AND aktif=1" if sadece_aktif else "")
        + " ORDER BY sira_no, id"
    )
    rows = con.execute(q, (tahsilat_kayit_id,)).fetchall()
    return [dict(r) for r in rows]


def cek_ekle(
    con: sqlite3.Connection,
    tahsilat_kayit_id: int,
    payload: dict,
    kullanici_id: int,
    idempotency_key: Optional[str] = None,
) -> dict[str, Any]:
    """Tek çek satırı ekle. Parent TASLAK/REVIZYON_ISTENDI + CEK olmalı."""
    if not _tablo_var(con, "mo_tahsilat_cek"):
        raise MoCekError("Migration 152 uygulanmamış.", 503)
    parent = _parent_row(con, tahsilat_kayit_id)
    _assert_duzenlenebilir(parent)

    norm = _validate_cek(payload, parent["para_birimi"])
    idem = (idempotency_key or payload.get("idempotency_key") or "").strip()
    if not idem:
        idem = _idem_key(tahsilat_kayit_id, f"{norm['gercek_cek_vade_tarihi']}-{norm['tutar']}-{_now()}")

    # idempotency: varsa o kaydı döndür
    con.row_factory = sqlite3.Row
    dup = con.execute(
        "SELECT id FROM mo_tahsilat_cek WHERE idempotency_key=?", (idem,)
    ).fetchone()
    if dup:
        row = con.execute("SELECT * FROM mo_tahsilat_cek WHERE id=?", (dup["id"],)).fetchone()
        return dict(row)

    now = _now()
    cur = con.execute(
        """
        INSERT INTO mo_tahsilat_cek
            (tahsilat_kayit_id, sira_no, tutar, para_birimi,
             cek_alim_tarihi, gercek_cek_vade_tarihi,
             odeme_referansi, banka_adi,
             durum, aktif, idempotency_key,
             olusturan_id, olusturma_tarihi, guncelleme_tarihi)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            tahsilat_kayit_id, norm["sira_no"], norm["tutar"], norm["para_birimi"],
            norm["cek_alim_tarihi"], norm["gercek_cek_vade_tarihi"],
            norm["odeme_referansi"], norm["banka_adi"],
            "AKTIF", 1, idem,
            kullanici_id, now, now,
        ),
    )
    cek_id = int(cur.lastrowid)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM mo_tahsilat_cek WHERE id=?", (cek_id,)).fetchone()
    return dict(row)


def cek_guncelle(
    con: sqlite3.Connection,
    tahsilat_kayit_id: int,
    cek_id: int,
    payload: dict,
    kullanici_id: int,
) -> dict[str, Any]:
    """Bir çek satırını güncelle. Parent düzenlenebilir olmalı."""
    if not _tablo_var(con, "mo_tahsilat_cek"):
        raise MoCekError("Migration 152 uygulanmamış.", 503)
    parent = _parent_row(con, tahsilat_kayit_id)
    _assert_duzenlenebilir(parent)

    con.row_factory = sqlite3.Row
    cek = con.execute(
        "SELECT * FROM mo_tahsilat_cek WHERE id=? AND tahsilat_kayit_id=? AND aktif=1",
        (cek_id, tahsilat_kayit_id),
    ).fetchone()
    if not cek:
        raise MoCekError("Çek satırı bulunamadı.", 404)

    norm = _validate_cek(payload, parent["para_birimi"])
    now = _now()
    con.execute(
        """
        UPDATE mo_tahsilat_cek SET
            sira_no=?, tutar=?, para_birimi=?,
            cek_alim_tarihi=?, gercek_cek_vade_tarihi=?,
            odeme_referansi=?, banka_adi=?, guncelleme_tarihi=?
        WHERE id=?
        """,
        (
            norm["sira_no"], norm["tutar"], norm["para_birimi"],
            norm["cek_alim_tarihi"], norm["gercek_cek_vade_tarihi"],
            norm["odeme_referansi"], norm["banka_adi"], now, cek_id,
        ),
    )
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM mo_tahsilat_cek WHERE id=?", (cek_id,)).fetchone()
    return dict(row)


def cek_soft_delete(
    con: sqlite3.Connection,
    tahsilat_kayit_id: int,
    cek_id: int,
    kullanici_id: int,
) -> dict[str, Any]:
    """Çek satırını soft-delete (aktif=0, durum=IPTAL)."""
    if not _tablo_var(con, "mo_tahsilat_cek"):
        raise MoCekError("Migration 152 uygulanmamış.", 503)
    parent = _parent_row(con, tahsilat_kayit_id)
    _assert_duzenlenebilir(parent)

    con.row_factory = sqlite3.Row
    cek = con.execute(
        "SELECT id FROM mo_tahsilat_cek WHERE id=? AND tahsilat_kayit_id=? AND aktif=1",
        (cek_id, tahsilat_kayit_id),
    ).fetchone()
    if not cek:
        raise MoCekError("Çek satırı bulunamadı veya zaten iptal.", 404)

    con.execute(
        "UPDATE mo_tahsilat_cek SET aktif=0, durum='IPTAL', guncelleme_tarihi=? WHERE id=?",
        (_now(), cek_id),
    )
    return {"ok": True, "cek_id": cek_id, "durum": "IPTAL"}


def cek_batch_replace(
    con: sqlite3.Connection,
    tahsilat_kayit_id: int,
    satirlar: list[dict],
    kullanici_id: int,
) -> list[dict[str, Any]]:
    """
    Tüm aktif çekleri input ile değiştir (batch save).
    Mevcut aktif çekleri soft-delete, yeni satirlari insert.
    Transaction dışarıdan sarılmalı.
    """
    if not _tablo_var(con, "mo_tahsilat_cek"):
        raise MoCekError("Migration 152 uygulanmamış.", 503)
    parent = _parent_row(con, tahsilat_kayit_id)
    _assert_duzenlenebilir(parent)

    now = _now()
    # mevcut aktif çekleri iptal et
    con.execute(
        "UPDATE mo_tahsilat_cek SET aktif=0, durum='IPTAL', guncelleme_tarihi=? "
        "WHERE tahsilat_kayit_id=? AND aktif=1",
        (now, tahsilat_kayit_id),
    )
    # yeni satırları insert
    result = []
    for i, s in enumerate(satirlar, start=1):
        s2 = dict(s)
        s2["sira_no"] = i
        idem = (s.get("idempotency_key") or "").strip()
        if not idem:
            idem = _idem_key(tahsilat_kayit_id, f"batch-{i}-{s2.get('gercek_cek_vade_tarihi','')}-{s2.get('tutar','')}-{now}")
        s2["idempotency_key"] = idem
        row = cek_ekle(con, tahsilat_kayit_id, s2, kullanici_id, idempotency_key=idem)
        result.append(row)
    return result
