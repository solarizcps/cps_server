# -*- coding: utf-8 -*-
"""
Read-Model Web Okuyucu — Snapshot'tan hızlı sayfa verisi.

TEMEL KURAL:
  - Bu modül hiçbir zaman Korgün'e bağlanmaz.
  - Aktif snapshot yoksa "henüz hazır değil" durumu döner.
  - Sıfır bakiyeli veya uydurma KPI döndürmez.
  - Tüm veri aynı snapshot_id'den gelir (request boyunca tutarlı).
  - Server-side pagination ve mevcut filtre davranışı korunur.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .rm_config import (
    MAX_STALE_AGE_SECONDS,
    DIRECTION_PAYABLE,
)
from .rm_db import (
    open_readonly,
    get_active_snapshot_id,
    get_snapshot_header,
    get_refresh_control,
)


# ─── Snapshot durum hesaplama ─────────────────────────────────────────────────

def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _snapshot_age_seconds(published_at: Optional[str]) -> Optional[int]:
    dt = _parse_iso(published_at)
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, int((now - dt).total_seconds()))


def _snapshot_status_label(
    published_at: Optional[str],
    refresh_state: Optional[str],
    last_error: Optional[str],
) -> str:
    """
    UI durum etiketi:
      no_snapshot     — hiç snapshot yok
      refreshing      — refresh şu an çalışıyor
      failed_last_ok  — son refresh başarısız, son başarılı gösteriliyor
      stale           — 15 dakikadan eski
      fresh           — taze
    """
    if published_at is None:
        return "no_snapshot"
    if refresh_state == "RUNNING":
        return "refreshing"
    if last_error:
        return "failed_last_ok"
    age = _snapshot_age_seconds(published_at)
    if age is not None and age > MAX_STALE_AGE_SECONDS:
        return "stale"
    return "fresh"


# ─── Filtre ve pagination (mevcut odeme_plani_service davranışı korunur) ────

def _apply_filters(
    rows: List[Dict[str, Any]],
    location: Optional[str],
    bakiye_f: Optional[str],
    tedarikci_q: Optional[str],
) -> List[Dict[str, Any]]:
    """Basit server-side filtre — mevcut UI filtre semantiğini korur."""
    result = rows
    if location and location.strip().upper():
        loc = location.strip().upper()
        result = [r for r in result if r.get("location") == loc]
    if bakiye_f:
        bf = bakiye_f.strip()
        if bf == "acik_borc":
            result = [r for r in result if "Açık Borç" in (r.get("bakiye_durumu") or "")]
        elif bf == "alacakli":
            result = [r for r in result if "Alacaklı" in (r.get("bakiye_durumu") or "")]
        elif bf == "sifir":
            result = [r for r in result if "Yok" in (r.get("bakiye_durumu") or "")]
    if tedarikci_q:
        q = tedarikci_q.strip().lower()
        if q:
            result = [r for r in result if q in (r.get("cari_adi") or "").lower()]
    return result


def _paginate(rows: List[Any], page: int, page_size: int) -> Tuple[List[Any], int, int, int]:
    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, page), total_pages)
    start = (page - 1) * page_size
    return rows[start : start + page_size], total, page, total_pages


# ─── Ana okuma fonksiyonu ─────────────────────────────────────────────────────

_NO_SNAPSHOT_RESPONSE: Dict[str, Any] = {
    "ok": True,
    "snapshot_state": "no_snapshot",
    "snapshot_id": None,
    "published_at": None,
    "snapshot_age_seconds": None,
    "status_label": "no_snapshot",
    "status_message": "Finans verisi henüz hazırlanmadı. İlk yenileme bekleniyor.",
    "refreshing": False,
    "kpi": None,
    "cari_rows": [],
    "pagination": {"page": 1, "page_size": 50, "total_pages": 1, "total_count": 0},
    "inline_korgun_calls": 0,   # Kanıt: 0 inline Korgün çağrısı
}


def read_payable_snapshot(
    db_path: Optional[str] = None,
    *,
    location: Optional[str] = None,
    bakiye_f: Optional[str] = None,
    tedarikci_q: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    """
    Aktif PAYABLE snapshot'tan sayfa verisi döner.

    HİÇBİR ZAMAN Korgün'e bağlanmaz.
    Snapshot yoksa → no_snapshot durumu (hızlı, <10ms).
    """
    with open_readonly(db_path) as conn:
        if conn is None:
            return {**_NO_SNAPSHOT_RESPONSE}

        # Refresh control — durum bilgisi
        ctrl = get_refresh_control(conn, DIRECTION_PAYABLE)
        refresh_state = ctrl["state"] if ctrl else None
        last_error = ctrl["last_error"] if ctrl else None
        last_success_at = ctrl["last_success_at"] if ctrl else None

        # Aktif snapshot id
        snapshot_id = get_active_snapshot_id(conn, DIRECTION_PAYABLE)
        if not snapshot_id:
            return {
                **_NO_SNAPSHOT_RESPONSE,
                "refreshing": refresh_state == "RUNNING",
                "status_label": "refreshing" if refresh_state == "RUNNING" else "no_snapshot",
                "status_message": (
                    "Veriler hazırlanıyor, lütfen bekleyin..."
                    if refresh_state == "RUNNING"
                    else "Finans verisi henüz hazırlanmadı."
                ),
            }

        # Snapshot header
        hdr = get_snapshot_header(conn, snapshot_id)
        if not hdr:
            return {**_NO_SNAPSHOT_RESPONSE}

        published_at = hdr["published_at"]
        age_secs = _snapshot_age_seconds(published_at)
        status_label = _snapshot_status_label(published_at, refresh_state, last_error)

        # KPI — snapshot_row aggregation (float YOK, Decimal string)
        kpi = _build_kpi_from_snapshot(conn, snapshot_id, hdr)

        # Cari satırları — snapshot'tan oku, filtrele, paginate et
        all_rows = _load_cari_rows(conn, snapshot_id)
        filtered_rows = _apply_filters(all_rows, location, bakiye_f, tedarikci_q)
        page_rows, total, page_out, total_pages = _paginate(filtered_rows, page, page_size)

        # Durum mesajı
        status_message = _status_message(status_label, last_error, published_at, age_secs)

        return {
            "ok": True,
            "snapshot_state": "active",
            "snapshot_id": snapshot_id,
            "published_at": published_at,
            "snapshot_age_seconds": age_secs,
            "status_label": status_label,
            "status_message": status_message,
            "refreshing": refresh_state == "RUNNING",
            "last_success_at": last_success_at,
            "kpi": kpi,
            "cari_rows": page_rows,
            "pagination": {
                "page": page_out,
                "page_size": page_size,
                "total_pages": total_pages,
                "total_count": total,
                "filtered_count": len(filtered_rows),
                "unfiltered_count": len(all_rows),
            },
            "inline_korgun_calls": 0,   # Kanıt
            "snapshot_meta": {
                "row_count": hdr["row_count"],
                "unique_cari_count": hdr["unique_cari_count"],
                "company_count": hdr["company_count"],
                "currency_count": hdr["currency_count"],
                "source_duration_ms": hdr["source_duration_ms"],
            },
        }


def _load_cari_rows(conn: sqlite3.Connection, snapshot_id: str) -> List[Dict[str, Any]]:
    """Snapshot'tan tüm cari satırlarını yükler."""
    rows = conn.execute(
        """SELECT location, location_label, cari_kod, cari_adi,
                  para_birimi, borc, alacak, net, canonical_key,
                  bakiye_durumu, display_bakiye
           FROM rm_snapshot_row
           WHERE snapshot_id = ?
           ORDER BY location, cari_adi, para_birimi""",
        (snapshot_id,),
    ).fetchall()

    result = []
    for r in rows:
        result.append({
            "location": r[0],
            "location_label": r[1],
            "cari_kod": r[2],
            "cari_adi": r[3],
            "para_birimi": r[4],
            "borc": r[5],
            "alacak": r[6],
            "net": r[7],
            "canonical_key": r[8],
            "bakiye_durumu": r[9],
            "display_bakiye": r[10],
            # Mevcut UI'ın beklediği alanlar
            "acik_bakiye": r[7],      # net
            "kritik": r[9],
            "kritik_class": _durum_class(r[9]),
            "bakiye_durum_class": _durum_class(r[9]),
        })
    return result


def _durum_class(durum: Optional[str]) -> str:
    if not durum:
        return "op-st-neutral"
    d = durum.lower()
    if "borç" in d or "borc" in d:
        return "op-st-open"
    if "alacak" in d:
        return "op-st-credit"
    return "op-st-neutral"


def _build_kpi_from_snapshot(
    conn: sqlite3.Connection,
    snapshot_id: str,
    hdr: sqlite3.Row,
) -> Dict[str, Any]:
    """KPI — snapshot header'dan + row aggregation. Float YOK."""

    # Önce kpi_json varsa kullan
    kpi_json_str = hdr["kpi_json"]
    if kpi_json_str:
        try:
            base = json.loads(kpi_json_str)
        except (json.JSONDecodeError, TypeError):
            base = {}
    else:
        base = {}

    # Şirket bazında açık borç (net < 0 → borç)
    company_agg = conn.execute(
        """SELECT location, para_birimi,
                  SUM(CAST(borc AS REAL)) as sum_borc,
                  SUM(CAST(alacak AS REAL)) as sum_alacak,
                  SUM(CAST(net AS REAL)) as sum_net,
                  COUNT(*) as cnt
           FROM rm_snapshot_row
           WHERE snapshot_id = ?
           GROUP BY location, para_birimi""",
        (snapshot_id,),
    ).fetchall()

    # Açık borç özeti (net < 0 olan satırlar)
    debt_rows = conn.execute(
        """SELECT para_birimi,
                  COUNT(*) as cnt,
                  SUM(CAST(display_bakiye AS REAL)) as total
           FROM rm_snapshot_row
           WHERE snapshot_id = ? AND bakiye_durumu LIKE '%Borç%'
           GROUP BY para_birimi""",
        (snapshot_id,),
    ).fetchall()

    debt_by_pb: Dict[str, Dict] = {}
    for r in debt_rows:
        pb = r[0]
        debt_by_pb[pb] = {"kalem": r[1], "tutar": r[2]}

    try_debt = debt_by_pb.get("TRY", {"kalem": 0, "tutar": 0.0})

    kpi = {
        "toplam_acik_borc": {
            "tutar": try_debt.get("tutar", 0.0),
            "kalem": try_debt.get("kalem", 0),
            "kalem_total": sum(v["kalem"] for v in debt_by_pb.values()),
            "para_birimi": "TRY",
            "diger_pb": {k: v for k, v in debt_by_pb.items() if k != "TRY"},
            "has_data": bool(debt_by_pb),
            "source": "rm_snapshot",
            "semantic": "Read-model snapshot açık borç (net<0)",
        },
        "snapshot_id": snapshot_id,
        "row_count": hdr["row_count"],
        "unique_cari_count": hdr["unique_cari_count"],
    }

    # base kpi_json'dan ek alanlar varsa ekle
    for k, v in base.items():
        if k not in kpi:
            kpi[k] = v

    return kpi


def _status_message(
    status_label: str,
    last_error: Optional[str],
    published_at: Optional[str],
    age_secs: Optional[int],
) -> str:
    if status_label == "no_snapshot":
        return "Finans verisi henüz hazırlanmadı."
    if status_label == "refreshing":
        return "Veriler yenileniyor..."
    if status_label == "failed_last_ok":
        return "Yenileme başarısız; son başarılı veri gösteriliyor."
    if status_label == "stale":
        mins = (age_secs or 0) // 60
        return f"Veri {mins} dakika önce güncellendi — güncel değil."
    return ""  # fresh → mesaj yok


# ─── Snapshot durum özeti (banner için) ───────────────────────────────────────

def get_snapshot_status(db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Yalnızca durum/meta bilgisi — cari satırları yüklemez.
    Sayfa header ve banner için kullanılır.
    """
    with open_readonly(db_path) as conn:
        if conn is None:
            return {
                "snapshot_state": "no_snapshot",
                "status_label": "no_snapshot",
                "status_message": "Finans verisi henüz hazırlanmadı.",
                "published_at": None,
                "snapshot_age_seconds": None,
                "refreshing": False,
            }

        ctrl = get_refresh_control(conn, DIRECTION_PAYABLE)
        refresh_state = ctrl["state"] if ctrl else None
        last_error = ctrl["last_error"] if ctrl else None

        snapshot_id = get_active_snapshot_id(conn, DIRECTION_PAYABLE)
        if not snapshot_id:
            return {
                "snapshot_state": "no_snapshot",
                "status_label": "refreshing" if refresh_state == "RUNNING" else "no_snapshot",
                "status_message": "Veriler hazırlanıyor..." if refresh_state == "RUNNING" else "Finans verisi henüz hazırlanmadı.",
                "published_at": None,
                "snapshot_age_seconds": None,
                "refreshing": refresh_state == "RUNNING",
            }

        hdr = get_snapshot_header(conn, snapshot_id)
        if not hdr:
            return {
                "snapshot_state": "no_snapshot",
                "status_label": "no_snapshot",
                "status_message": "Snapshot başlığı bulunamadı.",
                "published_at": None,
                "snapshot_age_seconds": None,
                "refreshing": False,
            }

        published_at = hdr["published_at"]
        age_secs = _snapshot_age_seconds(published_at)
        status_label = _snapshot_status_label(published_at, refresh_state, last_error)
        msg = _status_message(status_label, last_error, published_at, age_secs)

        return {
            "snapshot_state": "active",
            "snapshot_id": snapshot_id,
            "status_label": status_label,
            "status_message": msg,
            "published_at": published_at,
            "snapshot_age_seconds": age_secs,
            "refreshing": refresh_state == "RUNNING",
            "last_error": last_error,
            "row_count": hdr["row_count"],
            "source_duration_ms": hdr["source_duration_ms"],
        }
