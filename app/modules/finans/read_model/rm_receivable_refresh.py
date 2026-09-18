# -*- coding: utf-8 -*-
"""
Read-Model Refresh Worker — RECEIVABLE (Müşteri Alacak) snapshot üretimi.

GÖREV:
  1. Kira kilidi (SQLite lease) al.
  2. STAGING snapshot oluştur (direction='RECEIVABLE').
  3. Korgün CariBakiye (120.*) → aday evreni oluştur.
  4. kg_fn_CariHesToplam ile authoritative bakiye doğrula (batch, lokasyon bazlı).
  5. Parity gate: CariBakiye vs kg_fn delta > eşik → satırı STALE işaretle veya publish'i engelle.
  6. Layer2 enrichment: son satış, son tahsilat, portföy çek.
  7. Parity geçerse ACTIVE pointer flip.
  8. Hata/fail olursa önceki ACTIVE korunur.

GÜVENLİK:
  - Korgün'e yazma YOK.
  - Canonical mock_data.db'ye dokunma YOK.
  - PAYABLE snapshot'a dokunma YOK.
  - Web request sırasında çağrılmaz.

AŞAMA 0 JOİN GÜVENLİĞİ BULGULARI (uygulandı):
  - Fatura_Kay.BelgeNo GLOBAL UNIQUE → BelgeNo tek başına JOIN anahtarı olarak yeterli.
  - Fatura_Har.Location YOK → Fatura_Kay.Location ile filtrele (BelgeNo güvenli).
  - C_Fis_Kay.FisNo GLOBAL UNIQUE → FisNo tek başına JOIN anahtarı olarak yeterli.
  - C_Fis_Har: 1 FisNo'da birden fazla 120.* cari olabilir (95 durum) →
    cbpg filtresi zorunlu.
  - kg_fn_CariHesDetail 0 satır döndürüyor → KULLANMA; direkt tablo sorgula.
  - Fatura_Har.Fiyat=0 → tutar=0 üretmez; amount_status alanı eklendi.
  - Running balance sıfırdan başlatılmaz → DB fişinden devir tespit edilir.
  - 120.02.451 / 320.08.016 çift rol tespit edildi → CKod prefix filtresi yeterli.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from .rm_config import (
    DIRECTION_RECEIVABLE,
    DIRECTION_PAYABLE,
    LEASE_DURATION_SECONDS,
    SCHEMA_VERSION,
    sanitize_error,
)
from .rm_db import open_readwrite
from .rm_schema import bootstrap_schema

logger = logging.getLogger("cps.finans.rm_receivable_refresh")

# ─── Parity delta eşikleri (yapılandırılabilir) ───────────────────────────────
# Test ortamında env ile override edilebilir
PARITY_WARN_PCT_DEFAULT = float(os.environ.get("RECEIVABLE_PARITY_WARN_PCT", "2.0"))
PARITY_REJECT_PCT_DEFAULT = float(os.environ.get("RECEIVABLE_PARITY_REJECT_PCT", "10.0"))


def _ds(v) -> str:
    """Decimal/float/int/str → güvenli Decimal string."""
    from decimal import Decimal as D
    if v is None or v == "" or v == "None":
        return "0"
    if isinstance(v, D):
        return str(v)
    if isinstance(v, float):
        return str(D(str(v)))
    if isinstance(v, (int, str)):
        try:
            return str(D(str(v)))
        except Exception:
            return "0"
    return "0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


# ─── Korgün bağlantısı ───────────────────────────────────────────────────────

def _kg_connect():
    try:
        from modules.common.korgun import _baglan
    except ImportError:
        from app.modules.common.korgun import _baglan
    return _baglan()


# ─── Lokasyon haritası ───────────────────────────────────────────────────────

_LOCATION_LABELS = {
    "SA001": "Solariz",
    "SA002": "Solariz 2",
    "SH001": "Solariz Hor.",
    "SU002": "Solariz Uçak",
    "YN001": "YN",
    "YP001": "YP",
    "YP002": "YP 2",
    "SD002": "SD",
}

_ACTIVE_LOCATIONS = ["SA001", "SA002", "SH001", "SU002", "YN001", "YP001", "YP002"]

# Son tahsilat FisTip → görüntü etiketi
_FISTIP_TO_YONTEM = {
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

_TAHSILAT_FISTIPLERI = ("NT", "NO", "AD", "BG")


from .rm_balance_resolver import (
    BALANCE_FAIL_CLOSED_STATUS,
    ZERO_EPS,
    customer_bakiye_durumu,
    fetch_authoritative_balance_detail,
    resolve_canonical_customer_balance,
    resolve_finance_group as _resolve_finance_group,
    _pb_kg,
)


def _fatura_line_total_sql() -> str:
    return (
        "CASE WHEN fh.Fiyat IS NOT NULL AND fh.Fiyat <> 0 "
        "THEN fh.Miktar * fh.Fiyat "
        "*(1 - ISNULL(fh.iskonto, 0) / 100.0) "
        "*(1 + ISNULL(fh.KDVORAN, 0) / 100.0) ELSE 0 END"
    )


# ─── Adım 1: CariBakiye aday evreni ──────────────────────────────────────────

def fetch_customer_candidate_universe(
    locations: List[str],
) -> List[Dict[str, Any]]:
    """
    CariBakiye'den 120.* carileri çeker → hızlı aday evreni.
    Bakiye negatif = açık alacak (müşteri bize borçlu).
    Bakiye pozitif = fazla ödeme/avans.
    Bakiye sıfır = bu snapshot'a alınmaz (filtre: != 0).

    Returns list of dicts:
      location, cari_kod, cari_adi, para_birimi,
      source_balance (str), last_update
    """
    rows = []
    con = _kg_connect()
    cur = con.cursor()
    try:
        for loc in locations:
            cur.execute("""
                SELECT
                    cb.CKod,
                    LTRIM(RTRIM(ISNULL(ck.CName, ISNULL(ck.Unvan, cb.CKod)))) AS cari_adi,
                    CAST(cb.Tutar AS FLOAT) AS Tutar,
                    cb.ParaCinsi,
                    cb.LastUpdate
                FROM CariBakiye cb WITH (NOLOCK)
                LEFT JOIN Cari_Kart ck WITH (NOLOCK)
                    ON ck.CKod = cb.CKod AND ck.CKod LIKE '120.%%'
                WHERE cb.Location = %s
                  AND cb.CKod LIKE '120.%%'
                  AND CAST(cb.Tutar AS FLOAT) <> 0
                ORDER BY ABS(CAST(cb.Tutar AS FLOAT)) DESC
            """, (loc,))
            for r in cur.fetchall():
                ckod, cari_adi, tutar, para_birimi, last_update = r
                # Normalize para birimi
                pb_norm = (para_birimi or "TL").strip().upper()
                if pb_norm == "TL":
                    pb_norm = "TRY"
                elif pb_norm == "US":
                    pb_norm = "USD"
                elif pb_norm == "EU":
                    pb_norm = "EUR"
                rows.append({
                    "location": loc,
                    "cari_kod": ckod,
                    "cari_adi": (cari_adi or ckod).strip() or ckod,
                    "para_birimi": pb_norm,
                    "source_balance": _ds(tutar),
                    "last_update": str(last_update) if last_update else None,
                })
    finally:
        try:
            con.close()
        except Exception:
            pass
    return rows


def fetch_authoritative_balance(
    location: str,
    cari_kod: str,
    para_birimi: str,
) -> Optional[str]:
    """Geriye dönük uyumluluk — yalnızca signed net döner."""
    detail = fetch_authoritative_balance_detail(location, cari_kod, para_birimi)
    return detail["net"] if detail else None


# ─── Adım 3: Layer2 enrichment (son satış, son tahsilat, portföy çek) ────────

def fetch_customer_layer2(
    row_location: str,
    cari_kod: str,
    para_birimi: str = "TRY",
) -> Dict[str, Any]:
    """
    Layer2 enrichment — ana bakiye satır lokasyonunda kalır;
    son satış/tahsilat COMPANY_FINANCE_LOCATION_MAP group'unda aranır.
    Portföy çek satır lokasyonunda (ayna riskini önlemek için).
    """
    result: Dict[str, Any] = {
        "son_satis_tarih": None,
        "son_satis_tutar": None,
        "son_satis_pb": None,
        "son_satis_belge_no": None,
        "son_satis_location": None,
        "son_tahsilat_tarih": None,
        "son_tahsilat_tutar": None,
        "son_tahsilat_pb": None,
        "son_tahsilat_tur": None,
        "son_tahsilat_belge_no": None,
        "son_tahsilat_location": None,
        "portfoy_cek_tutar": None,
        "portfoy_cek_cnt": 0,
        "portfoy_cek_muhafsiz_cnt": 0,
        "portfoy_cek_muhasebeli_cnt": 0,
        "en_yakin_cek_vade": None,
        "vadesi_gecmis_cek_adet": 0,
        "vadesi_gecmis_cek_tutar": None,
    }
    group_locs = _resolve_finance_group(row_location)
    loc_ph = ",".join(["%s"] * len(group_locs))
    line_sql = _fatura_line_total_sql()
    tahsilat_in = ",".join(["'%s'" % t for t in _TAHSILAT_FISTIPLERI])
    try:
        con = _kg_connect()
        cur = con.cursor()
        try:
            # Son satış — group lokasyon; sıfır tutarlı son belge atlanır (Eba vb.)
            line_sql = _fatura_line_total_sql()
            cur.execute(f"""
                SELECT TOP 1 sub.FatTar, sub.Location, sub.BelgeNo, sub.ParaCinsi, sub.tutar
                FROM (
                    SELECT fk.FatTar, fk.Location, fk.BelgeNo, fk.FaturaPc AS ParaCinsi,
                           CAST(
                             CASE
                               WHEN ABS(ISNULL((
                                 SELECT SUM(t.NetTutar)
                                 FROM dbo.kg_ifn_FaturaTutar(fk.BelgeNo, NULL, fk.FaturaPc, NULL) t
                               ), 0)) > 0.001 THEN (
                                 SELECT SUM(t.NetTutar)
                                 FROM dbo.kg_ifn_FaturaTutar(fk.BelgeNo, NULL, fk.FaturaPc, NULL) t
                               )
                               ELSE SUM({line_sql})
                             END
                           AS FLOAT) AS tutar
                    FROM Fatura_Kay fk WITH (NOLOCK)
                    JOIN Fatura_Har fh WITH (NOLOCK) ON fh.BelgeNo = fk.BelgeNo
                    WHERE fk.CariKod = %s
                      AND fk.Location IN ({loc_ph})
                      AND fk.FaturaTip IN ('fsa', 'hsa')
                      AND ISNULL(fk.iptal, '') NOT IN ('E', '*', '(')
                    GROUP BY fk.FatTar, fk.Location, fk.BelgeNo, fk.FaturaPc
                ) sub
                ORDER BY CASE WHEN ABS(ISNULL(sub.tutar, 0)) > 0.001 THEN 0 ELSE 1 END,
                         sub.FatTar DESC,
                         sub.BelgeNo DESC
            """, (cari_kod, *group_locs))
            r = cur.fetchone()
            if r:
                result["son_satis_tarih"] = str(r[0])[:10] if r[0] else None
                result["son_satis_location"] = r[1]
                result["son_satis_belge_no"] = str(r[2]) if r[2] is not None else None
                result["son_satis_pb"] = r[3]
                amt = r[4]
                result["son_satis_tutar"] = _ds(amt) if amt is not None and abs(float(amt or 0)) > 0.001 else None

            # Son tahsilat — group lokasyon
            cur.execute(f"""
                SELECT TOP 1 cfk.FisTar, cfk.Location, cfk.FisTip, cfk.FisNo,
                       cfh.Tutar, cfh.ParaCinsi
                FROM C_Fis_Har cfh WITH (NOLOCK)
                JOIN C_Fis_Kay cfk WITH (NOLOCK) ON cfk.FisNo = cfh.FisNo
                WHERE cfh.cbpg = %s
                  AND cfk.Location IN ({loc_ph})
                  AND cfk.FisTip IN ({tahsilat_in})
                  AND ISNULL(cfk.iptal, '') <> 'E'
                ORDER BY cfk.FisTar DESC
            """, (cari_kod, *group_locs))
            r = cur.fetchone()
            if r:
                result["son_tahsilat_tarih"] = str(r[0])[:10] if r[0] else None
                result["son_tahsilat_location"] = r[1]
                fis_tip = (r[2] or "").strip().upper()
                result["son_tahsilat_tur"] = _FISTIP_TO_YONTEM.get(fis_tip, fis_tip or None)
                result["son_tahsilat_belge_no"] = str(r[3]) if r[3] is not None else None
                result["son_tahsilat_tutar"] = _ds(r[4])
                result["son_tahsilat_pb"] = r[5]

            if not result["son_tahsilat_tarih"]:
                cur.execute(f"""
                    SELECT TOP 1 cfk.FisTar, cfk.Location, cfk.FisTip, cfk.FisNo,
                           cfh.Tutar, cfh.ParaCinsi
                    FROM C_Fis_Har cfh WITH (NOLOCK)
                    JOIN C_Fis_Kay cfk WITH (NOLOCK) ON cfk.FisNo = cfh.FisNo
                    WHERE cfh.cbpg = %s
                      AND cfk.Location IN ({loc_ph})
                      AND ISNULL(cfk.iptal, '') <> 'E'
                    ORDER BY cfk.FisTar DESC
                """, (cari_kod, *group_locs))
                r = cur.fetchone()
                if r:
                    result["son_tahsilat_tarih"] = str(r[0])[:10] if r[0] else None
                    result["son_tahsilat_location"] = r[1]
                    fis_tip = (r[2] or "").strip().upper()
                    result["son_tahsilat_tur"] = _FISTIP_TO_YONTEM.get(fis_tip, fis_tip or None)
                    result["son_tahsilat_belge_no"] = str(r[3]) if r[3] is not None else None
                    result["son_tahsilat_tutar"] = _ds(r[4])
                    result["son_tahsilat_pb"] = r[5]

            # Portföy çek — satır lokasyonu (group toplama yok)
            cur.execute("""
                SELECT
                    COUNT(*) AS cnt,
                    CAST(SUM(ISNULL(Tutar, 0)) AS FLOAT) AS toplam,
                    SUM(CASE WHEN MuhFisNo IS NULL OR MuhFisNo = 0 THEN 1 ELSE 0 END) AS muhafsiz,
                    SUM(CASE WHEN MuhFisNo IS NOT NULL AND MuhFisNo > 0 THEN 1 ELSE 0 END) AS muhasebeli,
                    MIN(CONVERT(VARCHAR(10), vade, 120)) AS en_yakin_vade,
                    SUM(CASE WHEN vade < GETDATE() THEN 1 ELSE 0 END) AS vadesi_gecmis_cnt,
                    CAST(SUM(CASE WHEN vade < GETDATE() THEN ISNULL(Tutar, 0) ELSE 0 END) AS FLOAT) AS vadesi_gecmis_tutar
                FROM cek_Kart WITH (NOLOCK)
                WHERE CMKod = %s
                  AND Location = %s
                  AND CekTip = 'M'
                  AND LTRIM(RTRIM(SDurum)) IN ('0', '1')
            """, (cari_kod, row_location))
            r = cur.fetchone()
            if r and r[0]:
                result["portfoy_cek_tutar"] = _ds(r[1])
                result["portfoy_cek_cnt"] = int(r[0])
                result["portfoy_cek_muhafsiz_cnt"] = int(r[2] or 0)
                result["portfoy_cek_muhasebeli_cnt"] = int(r[3] or 0)
                result["en_yakin_cek_vade"] = r[4]
                result["vadesi_gecmis_cek_adet"] = int(r[5] or 0)
                result["vadesi_gecmis_cek_tutar"] = _ds(r[6]) if r[6] else "0"
        finally:
            try:
                con.close()
            except Exception:
                pass
    except Exception as e:
        logger.warning("layer2 error for %s/%s: %s", cari_kod, row_location, e)
    return result


# ─── Adım 4: Parity delta kontrolü ───────────────────────────────────────────

def compute_parity_delta(
    source_balance: str,
    authoritative_balance: str,
) -> Tuple[float, str]:
    """
    delta_abs = source - auth
    delta_pct = abs(delta_abs) / max(abs(source), 1) * 100

    Returns (delta_pct_float, delta_pct_str)
    """
    try:
        src = Decimal(source_balance)
        auth = Decimal(authoritative_balance)
        delta = src - auth
        denom = max(abs(src), Decimal("1"))
        pct = float(abs(delta) / denom * 100)
        return pct, f"{pct:.2f}"
    except (InvalidOperation, ZeroDivisionError):
        return 0.0, "0.00"


# ─── SQLite lease (RECEIVABLE) ────────────────────────────────────────────────

def _acquire_receivable_lease(conn, lock_owner: str) -> bool:
    row = conn.execute(
        "SELECT state, lease_expires_at FROM rm_refresh_control WHERE direction=?",
        (DIRECTION_RECEIVABLE,),
    ).fetchone()
    if row is None:
        return False
    state, expires_at = row[0], row[1]
    if state == "RUNNING":
        if expires_at:
            try:
                exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) < exp:
                    logger.info("RECEIVABLE refresh zaten çalışıyor.")
                    return False
            except (ValueError, TypeError):
                pass
    now = _now_iso()
    expires = (datetime.now(timezone.utc) + timedelta(seconds=LEASE_DURATION_SECONDS)).isoformat(timespec="milliseconds")
    conn.execute(
        """UPDATE rm_refresh_control
           SET state='RUNNING', lock_owner=?, heartbeat_at=?,
               lease_expires_at=?, last_attempt_at=?, updated_at=?
           WHERE direction=?""",
        (lock_owner, now, expires, now, now, DIRECTION_RECEIVABLE),
    )
    return True


def _release_receivable_lease(conn, success: bool, error_msg: Optional[str] = None) -> None:
    now = _now_iso()
    conn.execute(
        """UPDATE rm_refresh_control
           SET state='IDLE', lock_owner=NULL, heartbeat_at=NULL,
               lease_expires_at=NULL, last_error=?, updated_at=?
           WHERE direction=?""",
        (error_msg, now, DIRECTION_RECEIVABLE),
    )


# ─── Ana refresh orkestrasyonu ────────────────────────────────────────────────

def run_receivable_refresh(
    rm_path: str,
    locations: Optional[List[str]] = None,
    parity_warn_pct: float = PARITY_WARN_PCT_DEFAULT,
    parity_reject_pct: float = PARITY_REJECT_PCT_DEFAULT,
) -> Dict[str, Any]:
    """
    RECEIVABLE snapshot'ını tamamen yeniler.
    PAYABLE snapshot'a dokunmaz.

    Returns dict with keys:
      success, snapshot_id, row_count, warnings, errors
    """
    if locations is None:
        locations = _ACTIVE_LOCATIONS

    lock_owner = f"receivable_refresh_{os.getpid()}"
    snapshot_id = str(uuid.uuid4())
    result: Dict[str, Any] = {
        "success": False,
        "snapshot_id": snapshot_id,
        "row_count": 0,
        "warn_count": 0,
        "reject_count": 0,
        "warnings": [],
        "errors": [],
    }

    conn = None
    try:
        with open_readwrite(rm_path) as _conn:
            conn = _conn
            bootstrap_schema(conn)

            # Lease al
            conn.execute("BEGIN IMMEDIATE")
            if not _acquire_receivable_lease(conn, lock_owner):
                conn.execute("ROLLBACK")
                result["errors"].append("Lease alınamadı — başka process çalışıyor.")
                return result
            conn.execute("COMMIT")

            # STAGING snapshot oluştur
            now = _now_iso()
            conn.execute("BEGIN")
            conn.execute("""
                INSERT INTO rm_snapshot(
                    snapshot_id, direction, status, schema_version,
                    refresh_started_at, created_at
                ) VALUES(?, ?, 'STAGING', ?, ?, ?)
            """, (snapshot_id, DIRECTION_RECEIVABLE, SCHEMA_VERSION, now, now))
            conn.execute(
                "UPDATE rm_refresh_control SET last_attempt_id=?, updated_at=? WHERE direction=?",
                (snapshot_id, now, DIRECTION_RECEIVABLE),
            )
            conn.execute("COMMIT")

            logger.info("RECEIVABLE refresh başlıyor. snapshot_id=%s", snapshot_id)

            # Korgün'den aday evreni çek
            t0 = time.time()
            candidates = fetch_customer_candidate_universe(locations)
            candidate_ms = int((time.time() - t0) * 1000)
            logger.info("Aday evreni: %d satır, %d ms", len(candidates), candidate_ms)

            if not candidates:
                result["errors"].append("Korgün'den aday cari verisi gelmedi.")
                conn.execute("BEGIN")
                _fail_snapshot(conn, snapshot_id, "NO_CANDIDATES")
                _release_receivable_lease(conn, False, "NO_CANDIDATES")
                conn.execute("COMMIT")
                return result

            # Her aday için authoritative bakiye + layer2 + parity
            rows_to_insert = []
            warn_count = 0
            reject_count = 0

            for cand in candidates:
                loc = cand["location"]
                ckod = cand["cari_kod"]
                pb = cand["para_birimi"]
                src_bal = cand["source_balance"]

                # Canonical bakiye — finance group ayna lokasyon çözümlemesi
                balance_res = resolve_canonical_customer_balance(loc, ckod, pb)
                kg_borc = balance_res.get("borc") or "0"
                kg_alacak = balance_res.get("alacak") or "0"
                auth_bal = balance_res.get("net")
                canon_loc = balance_res.get("canonical_location") or loc

                # Parity: CariBakiye (satır lokasyonu) vs canonical kg_fn
                parity_delta_pct = None
                parity_status = "ok"
                if balance_res.get("status") == "fail_closed":
                    parity_status = "mirror_unresolved"
                elif auth_bal is not None:
                    delta_pct, delta_str = compute_parity_delta(src_bal, auth_bal)
                    parity_delta_pct = delta_str
                    if delta_pct > parity_reject_pct:
                        reject_count += 1
                        parity_status = "rejected"
                        result["warnings"].append(
                            f"PARITY_REJECT {ckod}/{loc}/{pb}: delta={delta_str}% "
                            f"(src={src_bal}, auth={auth_bal}, canon={canon_loc})"
                        )
                    elif delta_pct > parity_warn_pct:
                        warn_count += 1
                        parity_status = "warn"
                        result["warnings"].append(
                            f"PARITY_WARN {ckod}/{loc}/{pb}: delta={delta_str}% "
                            f"(src={src_bal}, auth={auth_bal}, canon={canon_loc})"
                        )
                else:
                    parity_status = "kg_fn_error"

                final_balance = auth_bal if auth_bal is not None else src_bal
                net_d = Decimal(final_balance or "0")
                if net_d > 0:
                    bakiye_durumu = "Açık Alacak"
                elif net_d < 0:
                    bakiye_durumu = "Müşteri Avansı"
                else:
                    bakiye_durumu = "Bakiye Yok"
                display_bakiye = _ds(abs(net_d)) if net_d != 0 else "0"

                # Layer2 enrichment (group lokasyon — yalnız enrichment)
                l2 = fetch_customer_layer2(loc, ckod, pb)

                # Bilgi amaçlı: brüt açık alacaktan portföy çeki düşülmez
                cek_haric = "0"
                if net_d > 0 and l2.get("portfoy_cek_tutar"):
                    cek_t = Decimal(l2.get("portfoy_cek_tutar") or "0")
                    cek_haric = _ds(max(net_d - cek_t, Decimal("0")))

                canonical_key = f"{loc}:{ckod}:{pb}"

                info_ledger: Dict[str, Any] = {}
                try:
                    from modules.finans.services.cari_hareket_ledger_service import (
                        build_cari_hareket_ledger,
                    )
                except ImportError:
                    from app.modules.finans.services.cari_hareket_ledger_service import (
                        build_cari_hareket_ledger,
                    )
                try:
                    led = build_cari_hareket_ledger(canon_loc or loc, ckod)
                    if led.get("ok"):
                        info_ledger = {
                            "info_har_borc": led.get("har_borc"),
                            "info_har_alacak": led.get("har_alacak"),
                            "info_har_net": led.get("har_net"),
                            "info_delta_borc": led.get("delta_borc"),
                            "info_delta_alacak": led.get("delta_alacak"),
                            "info_delta_net": led.get("delta_net", led.get("parity_delta")),
                            "info_parity_ok": led.get("parity_ok"),
                            "info_parity_note": led.get("parity_note"),
                            "info_parity_blocked_classes": led.get("parity_blocked_classes") or [],
                        }
                except Exception:
                    pass

                rows_to_insert.append((
                    snapshot_id,
                    loc,
                    _LOCATION_LABELS.get(loc, loc),
                    ckod,
                    cand["cari_adi"],
                    pb,
                    kg_borc,
                    kg_alacak,
                    _ds(net_d),
                    canonical_key,
                    bakiye_durumu,
                    display_bakiye,
                    # fa_* = son tahsilat meta
                    l2.get("son_tahsilat_tarih"),
                    l2.get("son_tahsilat_tur") or "",
                    l2.get("son_tahsilat_tutar"),
                    l2.get("son_tahsilat_pb"),
                    None,
                    0,
                    l2.get("son_tahsilat_belge_no"),
                    l2.get("son_tahsilat_belge_no"),
                    # son_odeme = son tahsilat
                    l2.get("son_tahsilat_tarih"),
                    l2.get("son_tahsilat_tutar"),
                    l2.get("son_tahsilat_pb"),
                    # son_alim = son satış
                    l2.get("son_satis_tarih"),
                    l2.get("son_satis_tutar"),
                    l2.get("son_satis_pb"),
                    "SATIS",
                    # portföy çek bilgileri (satır lokasyonu)
                    l2.get("en_yakin_cek_vade"),
                    l2.get("portfoy_cek_tutar"),
                    pb,
                    None,
                    0,
                    None,
                    None,
                    None,
                    None,
                    0,
                    None,
                    0,
                    0,
                    None,
                    json.dumps({
                        "source_balance": src_bal,
                        "authoritative_balance": auth_bal,
                        "authoritative_borc": kg_borc,
                        "authoritative_alacak": kg_alacak,
                        "parity_delta_pct": parity_delta_pct,
                        "parity_status": parity_status,
                        "portfoy_cek_cnt": l2.get("portfoy_cek_cnt", 0),
                        "portfoy_cek_muhafsiz_cnt": l2.get("portfoy_cek_muhafsiz_cnt", 0),
                        "portfoy_cek_muhasebeli_cnt": l2.get("portfoy_cek_muhasebeli_cnt", 0),
                        "portfoy_cek_tutar": l2.get("portfoy_cek_tutar"),
                        "en_yakin_cek_vade": l2.get("en_yakin_cek_vade"),
                        "vadesi_gecmis_cek_adet": l2.get("vadesi_gecmis_cek_adet", 0),
                        "vadesi_gecmis_cek_tutar": l2.get("vadesi_gecmis_cek_tutar"),
                        "son_satis_belge_no": l2.get("son_satis_belge_no"),
                        "son_satis_location": l2.get("son_satis_location"),
                        "son_tahsilat_tur": l2.get("son_tahsilat_tur"),
                        "son_tahsilat_belge_no": l2.get("son_tahsilat_belge_no"),
                        "son_tahsilat_location": l2.get("son_tahsilat_location"),
                        "cek_haric_teminatsiz_tutar": cek_haric,
                        "direction": DIRECTION_RECEIVABLE,
                        "canonical_balance_location": balance_res.get("canonical_location"),
                        "mirror_location": balance_res.get("mirror_location"),
                        "mirror_mechanism": balance_res.get("mirror_mechanism"),
                        "balance_resolution": balance_res.get("status"),
                        "row_location": loc,
                        **info_ledger,
                    }, ensure_ascii=False),
                ))

            # Batch insert
            conn.execute("BEGIN")
            conn.executemany("""
                INSERT INTO rm_snapshot_row(
                    snapshot_id, location, location_label,
                    cari_kod, cari_adi, para_birimi,
                    borc, alacak, net,
                    canonical_key, bakiye_durumu, display_bakiye,
                    fa_tarih, fa_turu, fa_tutar, fa_pb, fa_vade, fa_is_cek,
                    fa_vade_short, fa_cek_no,
                    son_odeme_tarih, son_odeme_tutar, son_odeme_pb,
                    son_alim_tarih, son_alim_tutar, son_alim_pb, son_alim_tip,
                    son_cek_vade, son_cek_tutar, son_cek_pb, son_cek_no,
                    aktif_takip, karar_badge, karar_class, karar_aksiyon,
                    anlasma_durumu, vade_has_term, vade_gun,
                    soz_has_active, soz_is_overdue, temas_tarih_iso,
                    enrichment_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?
                )
            """, rows_to_insert)

            # KPI özeti
            total_rows = len(rows_to_insert)
            unique_caris = len({(r[1], r[3], r[5]) for r in rows_to_insert})
            unique_locs = len({r[1] for r in rows_to_insert})
            unique_pbs = len({r[5] for r in rows_to_insert})

            kpi: Dict[str, Any] = {
                "total_receivable_by_pb": {},
                "total_overpayment_by_pb": {},
                "row_count": total_rows,
                "warn_count": warn_count,
                "reject_count": reject_count,
            }
            for row in rows_to_insert:
                pb_key = row[5]
                net_val = Decimal(row[8])
                if net_val > 0:
                    kpi["total_receivable_by_pb"][pb_key] = str(
                        Decimal(kpi["total_receivable_by_pb"].get(pb_key, "0")) + net_val
                    )
                elif net_val < 0:
                    kpi["total_overpayment_by_pb"][pb_key] = str(
                        Decimal(kpi["total_overpayment_by_pb"].get(pb_key, "0")) + abs(net_val)
                    )

            completed_at = _now_iso()
            conn.execute("""
                UPDATE rm_snapshot
                SET status='ACTIVE',
                    refresh_completed_at=?,
                    published_at=?,
                    row_count=?,
                    unique_cari_count=?,
                    company_count=?,
                    currency_count=?,
                    kpi_json=?
                WHERE snapshot_id=?
            """, (
                completed_at, completed_at,
                total_rows, unique_caris, unique_locs, unique_pbs,
                json.dumps(kpi, ensure_ascii=False),
                snapshot_id,
            ))

            # Pointer flip
            conn.execute("""
                UPDATE rm_pointer
                SET active_snapshot_id=?, last_success_id=?, updated_at=?
                WHERE direction=?
            """, (snapshot_id, snapshot_id, completed_at, DIRECTION_RECEIVABLE))

            # refresh_control güncelle
            conn.execute("""
                UPDATE rm_refresh_control
                SET active_snapshot_id=?, last_success_id=?, last_success_at=?,
                    state='IDLE', lock_owner=NULL, heartbeat_at=NULL,
                    lease_expires_at=NULL, last_error=NULL, updated_at=?
                WHERE direction=?
            """, (snapshot_id, snapshot_id, completed_at, completed_at, DIRECTION_RECEIVABLE))

            conn.execute("COMMIT")

            result["success"] = True
            result["row_count"] = total_rows
            result["warn_count"] = warn_count
            result["reject_count"] = reject_count

            logger.info(
                "RECEIVABLE snapshot başarılı. id=%s rows=%d warns=%d rejects=%d",
                snapshot_id, total_rows, warn_count, reject_count
            )

    except Exception as exc:
        err_msg = sanitize_error(exc)
        logger.exception("RECEIVABLE refresh FAILED: %s", err_msg)
        result["errors"].append(err_msg)

    return result


def _fail_snapshot(conn, snapshot_id: str, error_msg: str) -> None:
    conn.execute(
        "UPDATE rm_snapshot SET status='FAILED', error_message=? WHERE snapshot_id=?",
        (error_msg[:500], snapshot_id),
    )
