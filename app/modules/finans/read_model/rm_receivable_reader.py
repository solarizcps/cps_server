# -*- coding: utf-8 -*-
"""
Read-Model Okuyucu — RECEIVABLE (Müşteri Alacak).

TEMEL KURAL:
  - Korgün'e bağlanmaz (liste için).
  - Aktif RECEIVABLE snapshot yoksa güvenli boş durum döner.
  - PAYABLE verisiyle karışmaz (direction='RECEIVABLE' filtresi).
  - Tüm bakiye değerleri authoritative (kg_fn bazlı).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .rm_config import MAX_STALE_AGE_SECONDS, DIRECTION_RECEIVABLE
from .rm_db import open_readonly, get_active_snapshot_id, get_snapshot_header, get_refresh_control
from .rm_balance_resolver import resolve_finance_group as _resolve_finance_group  # re-export

# ─── Fiş tipi → ödeme yöntemi etiketi (refresh worker'dan bağımsız saf veri) ─
_FISTIP_TO_YONTEM: dict[str, str] = {
    "NT": "Nakit",
    "NO": "Nakit",
    "AD": "Dekont",
    "BG": "Banka/Havale",
    "CK": "Çek",
    "SN": "Senet",
    "BD": "Dekont",
    "DA": "Mahsup/Virman",
    "CV": "Mahsup/Virman",
    "DB": "Mahsup/Virman",
}

# ─── Decimal → güvenli string formatter ───────────────────────────────────────
def _ds(v) -> str:
    """Decimal veya sayısal değeri kayıpsız string'e çevirir. None güvenli."""
    from decimal import Decimal as _D
    if v is None or v == "":
        return "0"
    try:
        return str(_D(str(v)))
    except Exception:
        return "0"

# ─── Türkçe küçük harf dönüşümü (arama için) ─────────────────────────────────
_TR_LOWER_MAP = str.maketrans(
    "ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ",
    "abcçdefgğhıijklmnoöprsştuüvyz",
)

def _tr_lower(s: str) -> str:
    return s.translate(_TR_LOWER_MAP)


# ─── Snapshot durum ───────────────────────────────────────────────────────────

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


def _snapshot_status_label(published_at, refresh_state, last_error) -> str:
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


# ─── Filtre yardımcıları ─────────────────────────────────────────────────────

def _is_hareketli(r: Dict[str, Any]) -> bool:
    """Açık alacak, portföy çek veya aktif takip varsa hareketli."""
    net = Decimal(r.get("net") or "0")
    if net > 0:  # açık alacak (net = Borc - Alacak > 0)
        return True
    l2 = {}
    try:
        l2 = json.loads(r.get("enrichment_json") or "{}")
    except Exception:
        pass
    if l2.get("portfoy_cek_cnt", 0) > 0:
        return True
    if r.get("aktif_takip"):
        return True
    if r.get("son_odeme_tarih") or r.get("son_alim_tarih"):
        return True
    return False


def _apply_customer_filters(
    rows: List[Dict[str, Any]],
    bakiye_f: Optional[str],
    musteri_q: Optional[str],
    pb_filter: Optional[str],
    # ── Kolon header filtreleri (mf_ prefix) ──────────────────────
    mf_bakiye: Optional[str] = None,      # acik_alacak | fazla_odeme | sifir
    mf_durum: Optional[str] = None,       # acik_alacak | fazla_odeme | aktif_takip | sifir
    mf_tahsilat: Optional[str] = None,    # bu_ay | son_30 | son_90 | var | yok
    mf_satis: Optional[str] = None,       # bu_ay | son_30 | son_90 | var | yok
    mf_cek: Optional[str] = None,         # var | yok
    mf_takip: Optional[str] = None,       # aktif | pasif
    mf_sort: Optional[str] = None,        # adi_az | adi_za | bakiye_desc | bakiye_asc
) -> List[Dict[str, Any]]:
    """
    Filtreler:
    - bakiye_f: 'acik_alacak', 'fazla_odeme', 'hareketli', 'hareketsiz', 'aktif_takip', None=tümü
    - musteri_q: cari_adi / cari_kod / location_label arama
    - pb_filter: 'TRY', 'USD', 'EUR', None=tümü
    """
    result = rows

    if pb_filter:
        result = [r for r in result if r.get("para_birimi") == pb_filter]

    if bakiye_f == "acik_alacak":
        result = [r for r in result if Decimal(r.get("net") or "0") > 0]
    elif bakiye_f == "fazla_odeme":
        result = [r for r in result if Decimal(r.get("net") or "0") < 0]
    elif bakiye_f == "hareketli":
        result = [r for r in result if _is_hareketli(r)]
    elif bakiye_f == "hareketsiz":
        result = [r for r in result if not _is_hareketli(r)]
    elif bakiye_f == "aktif_takip":
        result = [r for r in result if r.get("aktif_takip")]
    elif bakiye_f == "sifir_bakiye":
        result = [r for r in result if Decimal(r.get("net") or "0") == 0]
    elif bakiye_f == "mudahale_gereken":
        # Açık alacak VEYA portföy çek var (muhasebeleşmemiş) VEYA aktif takip
        result = [r for r in result if (
            Decimal(r.get("net") or "0") > 0
            or int(json.loads(r.get("enrichment_json") or "{}").get("portfoy_cek_cnt") or 0) > 0
            or r.get("aktif_takip")
        )]

    if musteri_q:
        q_low = _tr_lower(musteri_q.strip())
        filtered = []
        for r in result:
            haystack = _tr_lower(" ".join(filter(None, [
                r.get("cari_adi") or "",
                r.get("cari_kod") or "",
                r.get("location_label") or "",
                r.get("location") or "",
            ])))
            if q_low in haystack:
                filtered.append(r)
        result = filtered

    # ── Kolon header filtreleri ──────────────────────────────────
    if mf_bakiye == "acik_alacak":
        result = [r for r in result if Decimal(r.get("net") or "0") > 0]
    elif mf_bakiye == "fazla_odeme":
        result = [r for r in result if Decimal(r.get("net") or "0") < 0]
    elif mf_bakiye == "sifir":
        result = [r for r in result if Decimal(r.get("net") or "0") == 0]

    if mf_durum == "acik_alacak":
        result = [r for r in result if Decimal(r.get("net") or "0") > 0]
    elif mf_durum == "fazla_odeme":
        result = [r for r in result if Decimal(r.get("net") or "0") < 0]
    elif mf_durum == "aktif_takip":
        result = [r for r in result if r.get("aktif_takip")]
    elif mf_durum == "sifir":
        result = [r for r in result if Decimal(r.get("net") or "0") == 0]

    from datetime import date, timedelta
    _today = date.today()

    def _date_in_range(date_str: Optional[str], days: int) -> bool:
        if not date_str:
            return False
        try:
            d = date.fromisoformat(str(date_str)[:10])
            return (_today - timedelta(days=days)) <= d <= _today
        except Exception:
            return False

    if mf_tahsilat == "bu_ay":
        result = [r for r in result if _date_in_range(r.get("son_odeme_tarih"), 31)]
    elif mf_tahsilat == "son_30":
        result = [r for r in result if _date_in_range(r.get("son_odeme_tarih"), 30)]
    elif mf_tahsilat == "son_90":
        result = [r for r in result if _date_in_range(r.get("son_odeme_tarih"), 90)]
    elif mf_tahsilat == "var":
        result = [r for r in result if r.get("son_odeme_tarih")]
    elif mf_tahsilat == "yok":
        result = [r for r in result if not r.get("son_odeme_tarih")]

    if mf_satis == "bu_ay":
        result = [r for r in result if _date_in_range(r.get("son_alim_tarih"), 31)]
    elif mf_satis == "son_30":
        result = [r for r in result if _date_in_range(r.get("son_alim_tarih"), 30)]
    elif mf_satis == "son_90":
        result = [r for r in result if _date_in_range(r.get("son_alim_tarih"), 90)]
    elif mf_satis == "var":
        result = [r for r in result if r.get("son_alim_tarih")]
    elif mf_satis == "yok":
        result = [r for r in result if not r.get("son_alim_tarih")]

    if mf_cek == "var":
        result = [r for r in result if int(r.get("portfoy_cek_cnt") or 0) > 0]
    elif mf_cek == "yok":
        result = [r for r in result if int(r.get("portfoy_cek_cnt") or 0) == 0]

    if mf_takip == "aktif":
        result = [r for r in result if r.get("aktif_takip")]
    elif mf_takip == "pasif":
        result = [r for r in result if not r.get("aktif_takip")]

    # ── Sıralama ────────────────────────────────────────────────
    if mf_sort == "adi_az":
        result = sorted(result, key=lambda r: (r.get("cari_adi") or "").lower())
    elif mf_sort == "adi_za":
        result = sorted(result, key=lambda r: (r.get("cari_adi") or "").lower(), reverse=True)
    elif mf_sort == "bakiye_desc":
        result = sorted(result, key=lambda r: abs(Decimal(r.get("net") or "0")), reverse=True)
    elif mf_sort == "bakiye_asc":
        result = sorted(result, key=lambda r: abs(Decimal(r.get("net") or "0")))

    return result


# ─── KPI hesaplama ────────────────────────────────────────────────────────────

def _build_customer_kpis(rows: List[Dict[str, Any]], snapshot_kpi_json: Optional[str]) -> Dict[str, Any]:
    """
    Snapshot satırlarından müşteri KPI kartlarını hesaplar.
    Çek toplamı açık alacağa EKLENMİYOR.
    """
    kpis: Dict[str, Any] = {
        "toplam_acik_alacak": {},     # pb → toplam
        "toplam_fazla_odeme": {},     # pb → toplam
        "portfoy_cek_toplam": {},     # pb → toplam (ayrı)
        "vadesi_gecmis_cek": {},      # gelecek: şimdilik 0
        "7gun_beklenen_cek": {},      # gelecek: şimdilik 0
        "30gun_beklenen_cek": {},     # gelecek: şimdilik 0
    }
    for r in rows:
        pb = r.get("para_birimi", "TRY")
        net = Decimal(r.get("net") or "0")
        if net > 0:
            kpis["toplam_acik_alacak"][pb] = str(
                Decimal(kpis["toplam_acik_alacak"].get(pb, "0")) + net
            )
        elif net < 0:
            kpis["toplam_fazla_odeme"][pb] = str(
                Decimal(kpis["toplam_fazla_odeme"].get(pb, "0")) + abs(net)
            )
        # Portföy çek (enrichment_json'dan)
        try:
            l2 = json.loads(r.get("enrichment_json") or "{}")
            cek_t = l2.get("portfoy_cek_cnt", 0)
            if cek_t:
                cek_tutar = Decimal(r.get("son_cek_tutar") or "0")
                kpis["portfoy_cek_toplam"][pb] = str(
                    Decimal(kpis["portfoy_cek_toplam"].get(pb, "0")) + cek_tutar
                )
        except Exception:
            pass
    return kpis


# ─── Ana okuyucu ─────────────────────────────────────────────────────────────

def read_receivable_snapshot(
    rm_path: str,
    location: Optional[str] = None,
    para_birimi: Optional[str] = None,
    bakiye_f: Optional[str] = None,
    musteri_q: Optional[str] = None,
    page: int = 1,
    per_page: int = 25,
    # ── Kolon header filtreleri ──────────────────────────────────
    mf_bakiye: Optional[str] = None,
    mf_durum: Optional[str] = None,
    mf_tahsilat: Optional[str] = None,
    mf_satis: Optional[str] = None,
    mf_cek: Optional[str] = None,
    mf_takip: Optional[str] = None,
    mf_sort: Optional[str] = None,
) -> Dict[str, Any]:
    """
    RECEIVABLE snapshot'tan müşteri listesini döner.
    - Korgün çağırmaz.
    - PAYABLE verisiyle karışmaz.

    Returns dict:
      rows, pagination, kpis, snapshot_status, snapshot_meta
    """
    # Arama varsa bakiye_f filtresi kaldırılır (tüm carilerde arama)
    effective_bakiye_f = bakiye_f
    if musteri_q and bakiye_f in ("hareketli", "hareketsiz", "acik_alacak", "mudahale_gereken", "aktif_takip", "sifir_bakiye"):
        effective_bakiye_f = None

    empty = {
        "rows": [],
        "pagination": {"page": 1, "per_page": per_page, "total": 0, "total_pages": 1,
                       "active_count": 0, "loc_total": 0},
        "kpis": {},
        "snapshot_status": "no_snapshot",
        "snapshot_meta": {},
        "customer_scope_implemented": True,
    }

    try:
        with open_readonly(rm_path) as conn:
            if conn is None:
                empty["snapshot_status"] = "no_snapshot"
                return empty

            # Aktif snapshot bul
            snap_id = get_active_snapshot_id(conn, DIRECTION_RECEIVABLE)
            if not snap_id:
                ctrl = get_refresh_control(conn, DIRECTION_RECEIVABLE)
                refresh_state = ctrl["state"] if ctrl else None
                last_error = ctrl["last_error"] if ctrl else None
                empty["snapshot_status"] = _snapshot_status_label(None, refresh_state, last_error)
                return empty

            snap_header = get_snapshot_header(conn, snap_id)
            ctrl = get_refresh_control(conn, DIRECTION_RECEIVABLE)
            refresh_state = ctrl["state"] if ctrl else None
            last_error = ctrl["last_error"] if ctrl else None

            published_at = snap_header["published_at"] if snap_header else None
            status_label = _snapshot_status_label(published_at, refresh_state, last_error)

            # Satırları çek
            query_parts = ["SELECT * FROM rm_snapshot_row WHERE snapshot_id=?"]
            params: List[Any] = [snap_id]

            if location:
                # Mantıksal şirket grubu genişletmesi
                try:
                    from modules.finans.services.korgun_finance_adapter import COMPANY_FINANCE_LOCATION_MAP
                except ImportError:
                    try:
                        from app.modules.finans.services.korgun_finance_adapter import COMPANY_FINANCE_LOCATION_MAP
                    except ImportError:
                        COMPANY_FINANCE_LOCATION_MAP = {}
                _loc_upper = location.strip().upper()
                _loc_group = COMPANY_FINANCE_LOCATION_MAP.get(_loc_upper)
                if _loc_group:
                    _locs = list(_loc_group)
                else:
                    _locs = [_loc_upper]
                placeholders = ",".join("?" * len(_locs))
                query_parts.append(f"AND location IN ({placeholders})")
                params.extend(_locs)

            if para_birimi:
                query_parts.append("AND para_birimi=?")
                params.append(para_birimi)

            query_parts.append("ORDER BY ABS(CAST(net AS FLOAT)) DESC, cari_kod")
            sql = " ".join(query_parts)

            cursor = conn.execute(sql, params)
            col_names = [d[0] for d in cursor.description]
            raw_rows = [dict(zip(col_names, r)) for r in cursor.fetchall()]

            # Güvenlik: direction=RECEIVABLE olanları filtrele
            safe_rows = []
            for r in raw_rows:
                try:
                    l2 = json.loads(r.get("enrichment_json") or "{}")
                    if l2.get("direction", DIRECTION_RECEIVABLE) == DIRECTION_RECEIVABLE:
                        safe_rows.append(r)
                except Exception:
                    safe_rows.append(r)

            # Filtrele
            filtered = _apply_customer_filters(
                safe_rows, effective_bakiye_f, musteri_q, None,
                mf_bakiye=mf_bakiye,
                mf_durum=mf_durum,
                mf_tahsilat=mf_tahsilat,
                mf_satis=mf_satis,
                mf_cek=mf_cek,
                mf_takip=mf_takip,
                mf_sort=mf_sort,
            )

            # KPI
            kpis = _build_customer_kpis(safe_rows, snap_header["kpi_json"] if snap_header else None)

            # Sayfalama
            loc_total = len(filtered)
            active_count = len([r for r in filtered if _is_hareketli(r)])
            open_count = len([r for r in filtered if float(r.get("net") or 0) > 0])
            overpay_count = len([r for r in filtered if float(r.get("net") or 0) < 0])
            total_pages = max(1, (loc_total + per_page - 1) // per_page)
            page = max(1, min(page, total_pages))
            start = (page - 1) * per_page
            page_rows = filtered[start: start + per_page]

            # Satır formatlama
            display_rows = []
            for r in page_rows:
                try:
                    l2 = json.loads(r.get("enrichment_json") or "{}")
                except Exception:
                    l2 = {}
                display_rows.append({
                    "cari_kod": r.get("cari_kod"),
                    "cari_adi": r.get("cari_adi") or r.get("cari_kod"),
                    "location": r.get("location"),
                    "location_label": r.get("location_label") or r.get("location"),
                    "para_birimi": r.get("para_birimi"),
                    "open_receivable": r.get("display_bakiye") or "0",
                    "net": r.get("net") or "0",
                    "borc": r.get("borc") or "0",
                    "alacak": r.get("alacak") or "0",
                    "bakiye_durumu": r.get("bakiye_durumu") or "—",
                    "son_satis_tarih": r.get("son_alim_tarih"),
                    "son_satis_tutar": r.get("son_alim_tutar"),
                    "son_satis_location": l2.get("son_satis_location"),
                    "son_tahsilat_tarih": r.get("son_odeme_tarih"),
                    "son_tahsilat_tutar": r.get("son_odeme_tutar"),
                    "son_tahsilat_yontem": l2.get("son_tahsilat_tur") or r.get("fa_turu") or "",
                    "portfoy_cek_cnt": l2.get("portfoy_cek_cnt", 0),
                    "portfoy_cek_adet": l2.get("portfoy_cek_cnt", 0),
                    "portfoy_cek_tutar": l2.get("portfoy_cek_tutar") or r.get("son_cek_tutar"),
                    "portfoy_cek_muhafsiz_cnt": l2.get("portfoy_cek_muhafsiz_cnt", 0),
                    "portfoy_cek_muhasebeli_cnt": l2.get("portfoy_cek_muhasebeli_cnt", 0),
                    "en_yakin_cek_vade": l2.get("en_yakin_cek_vade") or r.get("son_cek_vade"),
                    "vadesi_gecmis_cek_adet": l2.get("vadesi_gecmis_cek_adet", 0),
                    "vadesi_gecmis_cek_tutar": l2.get("vadesi_gecmis_cek_tutar"),
                    "cek_haric_teminatsiz_tutar": l2.get("cek_haric_teminatsiz_tutar"),
                    "parity_status": l2.get("parity_status", "ok"),
                    "parity_delta_pct": l2.get("parity_delta_pct"),
                    "balance_resolution": l2.get("balance_resolution"),
                    "location_warning": (l2.get("balance_resolution") == "fail_closed"),
                    "aktif_takip": bool(r.get("aktif_takip")),
                    "source_updated_at": r.get("fa_tarih"),
                })

            snap_meta = {
                "snapshot_id": snap_id,
                "published_at": published_at,
                "row_count": snap_header["row_count"] if snap_header else 0,
                "status": status_label,
            }

            return {
                "rows": display_rows,
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": loc_total,
                    "total_pages": total_pages,
                    "active_count": active_count,
                    "loc_total": loc_total,
                    "open_count": open_count,
                    "overpay_count": overpay_count,
                },
                "kpis": kpis,
                "snapshot_status": status_label,
                "snapshot_meta": snap_meta,
                "customer_scope_implemented": True,
            }
    except Exception as exc:
        empty["snapshot_status"] = "error"
        empty["error"] = str(exc)[:200]
        return empty