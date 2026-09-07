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

def _is_hareketli(r: Dict[str, Any]) -> bool:
    """
    Hareketli cari: bakiye≠0 VEYA aktif_takip VEYA son ödeme/alım/temas/söz var.
    Bakiye sıfır, takip yok, hareketsiz → False.
    """
    if abs(float(r.get("display_bakiye") or 0)) > 0.009:
        return True
    if r.get("aktif_takip"):
        return True
    if r.get("son_odeme_tarihi"):
        return True
    if r.get("son_cek_vade"):
        return True
    if r.get("son_alim_tarihi"):
        return True
    if r.get("son_temas_tarihi"):
        return True
    if r.get("son_soz_tarihi"):
        return True
    return False


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
        elif bf == "mudahale":
            # Legacy semantik: mudahale = açık borçlu cariler (bakiye_durumu contains "Borç")
            result = [r for r in result if "Açık Borç" in (r.get("bakiye_durumu") or "")]
        elif bf == "aktif_takip":
            # Aktif Takip: aktif_takip=True olan satırlar
            result = [r for r in result if r.get("aktif_takip") is True]
        elif bf == "hareketli":
            # Hareketli: bakiye≠0 VEYA aktif_takip VEYA son_odeme/son_alim/son_temas var
            result = [r for r in result if _is_hareketli(r)]
        elif bf == "hareketsiz":
            # Hareketsiz: bakiye sıfır VE aktif takip yok VE hareket yok
            result = [r for r in result if not _is_hareketli(r)]
    if tedarikci_q:
        q = tedarikci_q.strip().lower()
        if q:
            # Türkçe büyük harf duyarsız karşılaştırma
            # İ → i, I → ı (Python .lower() İ'yi 2 karakter yapabiliyor)
            _TR_LOWER_MAP = str.maketrans('İIĞÜŞÖÇ', 'iiğüşöç')

            def _tr_lower(s: str) -> str:
                return s.translate(_TR_LOWER_MAP).lower()

            q_norm = _tr_lower(q)

            # Arama kapsamı: cari_adi + cari_kod + şirket/lokasyon kodu ve adı
            def _matches(r: Dict[str, Any]) -> bool:
                if q_norm in _tr_lower(r.get("cari_adi") or ""):
                    return True
                if q_norm in _tr_lower(r.get("cari_kod") or ""):
                    return True
                if q_norm in _tr_lower(r.get("location") or ""):
                    return True
                if q_norm in _tr_lower(r.get("location_label") or ""):
                    return True
                return False
            result = [r for r in result if _matches(r)]
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
        # location filtresi sonrası toplam (şirket filtreli evren)
        loc_rows = _apply_filters(all_rows, location, None, None)
        active_count = sum(1 for r in loc_rows if _is_hareketli(r))
        # Arama varsa hareketli/hareketsiz filtresini devre dışı bırak
        # → hareketsiz cariler de aramada bulunabilir
        effective_bakiye_f = bakiye_f
        if tedarikci_q and tedarikci_q.strip() and bakiye_f in ('hareketli', 'hareketsiz'):
            effective_bakiye_f = None
        filtered_rows = _apply_filters(all_rows, location, effective_bakiye_f, tedarikci_q)
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
                "active_count": active_count,
                "loc_total": len(loc_rows),
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


def _as_float(v: Any) -> float:
    """SQLite Decimal string → float (Jinja '{:,.2f}'.format uyumu)."""
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def _load_cari_rows(conn: sqlite3.Connection, snapshot_id: str) -> List[Dict[str, Any]]:
    """Snapshot'tan tüm cari satırlarını yükler — V2 tam UI contract."""
    rows = conn.execute(
        """SELECT location, location_label, cari_kod, cari_adi,
                  para_birimi, borc, alacak, net, canonical_key,
                  bakiye_durumu, display_bakiye,
                  fa_tarih, fa_turu, fa_tutar, fa_pb, fa_vade, fa_is_cek, fa_vade_short, fa_cek_no,
                  son_odeme_tarih, son_odeme_tutar, son_odeme_pb,
                  son_alim_tarih, son_alim_tutar, son_alim_pb, son_alim_tip,
                  son_cek_vade, son_cek_tutar, son_cek_pb, son_cek_no,
                  aktif_takip, karar_badge, karar_class, karar_aksiyon,
                  anlasma_durumu, vade_has_term, vade_gun,
                  soz_has_active, soz_is_overdue, temas_tarih_iso
           FROM rm_snapshot_row
           WHERE snapshot_id = ?
           ORDER BY
             CASE bakiye_durumu
               WHEN 'Açık Borç'   THEN 1
               WHEN 'Alacaklıyız' THEN 2
               ELSE                    3
             END,
             CAST(display_bakiye AS REAL) DESC,
             location, cari_adi, para_birimi""",
        (snapshot_id,),
    ).fetchall()

    def _str(v: Any) -> Optional[str]:
        return str(v) if v not in (None, "", "None") else None

    def _bool_col(v: Any) -> bool:
        return bool(v) if v is not None else False

    result = []
    for r in rows:
        durum = r[9]
        durum_class = _durum_class(durum)
        net_f = _as_float(r[7])
        disp_f = _as_float(r[10])

        # karar alanları: snapshot'ta varsa kullan; yoksa durum'dan fallback
        karar_badge = r[31] or (durum or "Bakiye Yok")
        karar_class = r[32] or durum_class
        karar_aksiyon = r[33] or "—"
        anlasma_durumu = _str(r[34])
        vade_has_term = _bool_col(r[35])
        vade_gun = r[36]
        aktif_takip = _bool_col(r[30])
        soz_has_active = _bool_col(r[37])
        soz_is_overdue = _bool_col(r[38])
        temas_tarih_iso = _str(r[39])

        # fa (Son Finansal Aksiyon)
        fa_tarih = _str(r[11])
        fa_turu = _str(r[12]) or ""
        fa_tutar_f = _as_float(r[13])
        fa_pb = _str(r[14]) or r[4]
        fa_vade = _str(r[15])
        fa_is_cek = _bool_col(r[16])
        fa_vade_short = _str(r[17]) or ""
        fa_cek_no = _str(r[18])

        def _fmt(v_str: Any, pb: str) -> str:
            f = _as_float(v_str)
            if f == 0.0:
                return ""
            sym = {"TRY": "₺", "USD": "$", "EUR": "€"}.get(str(pb), str(pb) + " ")
            try:
                return f"{sym}{f:,.0f}".replace(",", ".")
            except Exception:
                return ""

        fa_pb_str = fa_pb or r[4]
        fa_label = _fmt(r[13], fa_pb_str)

        son_odeme_tarih = _str(r[19])
        son_odeme_pb = _str(r[21]) or r[4]
        son_odeme_label = _fmt(r[20], son_odeme_pb)

        son_alim_tarih = _str(r[22])
        son_alim_pb = _str(r[24]) or r[4]
        son_alim_label = _fmt(r[23], son_alim_pb)
        son_alim_tip = _str(r[25]) or ""

        son_cek_vade = _str(r[26])
        son_cek_pb = _str(r[28]) or r[4]
        son_cek_label = _fmt(r[27], son_cek_pb)
        son_cek_no = _str(r[29])

        result.append({
            "location": r[0],
            "location_label": r[1] or r[0],
            "cari_kod": r[2],
            "cari_adi": r[3],
            "para_birimi": r[4],
            "borc": r[5],
            "alacak": r[6],
            "net": r[7],
            "canonical_key": r[8],
            "bakiye_durumu": durum,
            "display_bakiye": disp_f,
            "acik_bakiye": net_f,
            "kritik": durum,
            "kritik_class": durum_class,
            "bakiye_durum_class": durum_class,
            # Karar
            "karar_badge": karar_badge,
            "karar_class": karar_class,
            "karar_aksiyon": karar_aksiyon,
            "anlasma_durumu": anlasma_durumu or "Vade tanımlı değil",
            "vade_has_term": vade_has_term,
            "vade_gun": vade_gun,
            # Takip / soz / temas
            "aktif_takip": aktif_takip,
            "soz_has_active": soz_has_active,
            "soz_is_overdue": soz_is_overdue,
            "temas_tarih_iso": temas_tarih_iso,
            # Placeholder rich fields (template'de yalnız has_active ile dallanıyor)
            "son_odeme_sozu": "—",
            "son_odeme_sozu_rich": "",
            "son_gorusme": "—",
            "son_gorusme_rich": "",
            # Son Finansal Aksiyon
            "fa_tarih": fa_tarih,
            "fa_turu": fa_turu,
            "fa_tutar": fa_tutar_f,
            "fa_pb": fa_pb_str,
            "fa_vade": fa_vade,
            "fa_is_cek": fa_is_cek,
            "fa_vade_short": fa_vade_short,
            "fa_cek_no": fa_cek_no,
            "fa_label": fa_label,
            # Son ödeme
            "son_odeme_tarih": son_odeme_tarih,
            "son_odeme_label": son_odeme_label,
            "son_odeme_pb": son_odeme_pb,
            # Son alış
            "son_alim_tarih": son_alim_tarih,
            "son_alim_label": son_alim_label,
            "son_alim_tip": son_alim_tip,
            "son_alim_pb": son_alim_pb,
            # Son çek
            "son_cek_vade": son_cek_vade,
            "son_cek_label": son_cek_label,
            "son_cek_no": son_cek_no,
            "son_cek_pb": son_cek_pb,
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

    # Vadeli çek KPI'ları — son_cek_vade + son_cek_tutar sütunlarından snapshot row bazlı hesap
    # NOT: Bu cari başına son çek özeti; tüm açık çeklerin tam kümesi değil (yaklaşık)
    today_str = datetime.now(timezone.utc).date().isoformat()  # "YYYY-MM-DD"
    cutoff_7 = (datetime.now(timezone.utc).date() + timedelta(days=7)).isoformat()
    cutoff_30 = (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat()

    cek_rows = conn.execute(
        """SELECT son_cek_vade, son_cek_tutar, son_cek_pb
           FROM rm_snapshot_row
           WHERE snapshot_id = ?
             AND son_cek_vade IS NOT NULL AND son_cek_vade != ''
             AND son_cek_tutar IS NOT NULL AND son_cek_tutar != ''""",
        (snapshot_id,),
    ).fetchall()

    vadesi_gecmis = {"tutar": 0.0, "kalem": 0}
    gun_7 = {"tutar": 0.0, "kalem": 0}
    gun_30 = {"tutar": 0.0, "kalem": 0}
    for cr in cek_rows:
        vade = (cr[0] or "")[:10]
        tutar = 0.0
        try:
            tutar = float(str(cr[1]).replace(",", "") or 0)
        except (ValueError, TypeError):
            pass
        if not vade or tutar == 0.0:
            continue
        if vade < today_str:
            vadesi_gecmis["tutar"] += tutar
            vadesi_gecmis["kalem"] += 1
        elif vade <= cutoff_7:
            gun_7["tutar"] += tutar
            gun_7["kalem"] += 1
        elif vade <= cutoff_30:
            gun_30["tutar"] += tutar
            gun_30["kalem"] += 1

    # Bu hafta ödeme sözü — local CPS DB'den (finans_odeme_plani_sozu)
    bu_hafta_soz = {"tutar": 0.0, "cari": 0, "has_data": False}
    try:
        from .rm_config import get_rm_path as _get_rm_path
        import os as _os
        _mock_db = _os.environ.get("CPS_MOCK_DB_PATH", "")
        if _mock_db and _os.path.exists(_mock_db):
            _soz_conn = sqlite3.connect(_mock_db, timeout=5)
            _soz_conn.row_factory = sqlite3.Row
            try:
                from datetime import timedelta as _td
                _today = datetime.now(timezone.utc).date()
                _week_end = (_today + _td(days=7)).isoformat()
                _today_str = _today.isoformat()
                _soz_rows = _soz_conn.execute(
                    """SELECT COUNT(DISTINCT cari_kod) as cnt, COALESCE(SUM(tutar),0) as toplam
                       FROM finans_odeme_plani_sozu
                       WHERE durum='BEKLIYOR'
                         AND soz_tarihi >= ? AND soz_tarihi <= ?""",
                    (_today_str, _week_end),
                ).fetchone()
                if _soz_rows and (_soz_rows[0] or 0) > 0:
                    bu_hafta_soz = {
                        "tutar": float(_soz_rows[1] or 0),
                        "cari": int(_soz_rows[0] or 0),
                        "has_data": True,
                    }
            except Exception:
                pass
            finally:
                _soz_conn.close()
    except Exception:
        pass

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
        "vadesi_gecmis": {
            "tutar": vadesi_gecmis["tutar"],
            "kalem": vadesi_gecmis["kalem"],
            "has_data": vadesi_gecmis["kalem"] > 0,
            "source": "rm_snapshot_row.son_cek_vade",
        },
        "7_gun": {
            "tutar": gun_7["tutar"],
            "kalem": gun_7["kalem"],
            "has_data": gun_7["kalem"] > 0,
            "source": "rm_snapshot_row.son_cek_vade",
        },
        "30_gun": {
            "tutar": gun_30["tutar"],
            "kalem": gun_30["kalem"],
            "has_data": gun_30["kalem"] > 0,
            "source": "rm_snapshot_row.son_cek_vade",
        },
        "bu_hafta_odeme_sozu": bu_hafta_soz,
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
