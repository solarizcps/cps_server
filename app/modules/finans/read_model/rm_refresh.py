# -*- coding: utf-8 -*-
"""
Read-Model Refresh Worker — PAYABLE snapshot üretimi.

GÖREV:
  1. Kira kilidi (SQLite lease + Windows named mutex) al.
  2. STAGING snapshot oluştur.
  3. fetch_supplier_balances_bundle() → satırları yaz.
  4. Parity gate — kaynak özeti ile DB özeti karşılaştır.
  5. Parity geçerse atomic pointer flip: staging → ACTIVE.
  6. Nesil rotasyonu: eski ACTIVE → SUPERSEDED; PREVIOUS'ı koru.
  7. Hata/fail olursa ACTIVE/LAST_SUCCESS dokunulmaz.

GÜVENLİK:
  - Production Korgün'e yazma YOK.
  - Canonical app/mock_data.db'ye dokunma YOK.
  - Loglarda cari finans detayları gösterilmez.
  - Windows named mutex ile tek-process garanti.
  - SQLite lease ile çökme sonrası recovery.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .rm_config import (
    DIRECTION_PAYABLE,
    LEASE_DURATION_SECONDS,
    SCHEMA_VERSION,
    SUCCESSFUL_GENERATIONS,
    sanitize_error,
)
from .rm_db import open_readwrite
from .rm_parity import build_db_summary, build_source_summary
from .rm_parity import run_parity_gate  # ayrı satır — test patch için
from .rm_schema import bootstrap_schema

logger = logging.getLogger("cps.finans.rm_refresh")


# ─── Enrichment facade'ları (test'te patch edilebilir) ───────────────────────

def _fetch_layer2(locations=None, force_refresh: bool = True) -> Dict[str, Any]:
    """Layer2 enrichment: son ödeme/çek/alış — Korgün batch (3 sorgu)."""
    try:
        from modules.finans.services.odeme_karar_read_service import fetch_layer2_maps
    except ImportError:
        from app.modules.finans.services.odeme_karar_read_service import fetch_layer2_maps
    return fetch_layer2_maps(locations=locations, force_refresh=force_refresh)


def _fetch_takip(locations=None) -> Dict[str, bool]:
    """CPS local: aktif takip map."""
    try:
        from modules.finans.services.odeme_takip_service import fetch_aktif_takip_map
    except ImportError:
        from app.modules.finans.services.odeme_takip_service import fetch_aktif_takip_map
    return fetch_aktif_takip_map(locations=locations)


def _fetch_enrichment(locations, cari_kods) -> tuple:
    """CPS local: contact/promise/term maps."""
    try:
        from modules.finans.services.odeme_plani_enrichment_service import fetch_enrichment_maps
    except ImportError:
        from app.modules.finans.services.odeme_plani_enrichment_service import fetch_enrichment_maps
    return fetch_enrichment_maps(locations, cari_kods)


# ─── Windows Named Mutex ──────────────────────────────────────────────────────

_MUTEX_NAME = "Global\\CPS_OdemePlaniPayableRefresh"

class _WindowsMutexLock:
    """
    Windows named mutex single-instance lock.
    Hata durumunda (non-Windows veya ctypes yoksa) no-op fallback.
    """
    def __init__(self):
        self._handle = None
        self._acquired = False

    def try_acquire(self, timeout_ms: int = 0) -> bool:
        """Mutex'i almayı dener. False → başka process zaten çalışıyor."""
        try:
            import ctypes
            import ctypes.wintypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
            if handle == 0:
                return False
            # Mutex'i almayı dene
            result = kernel32.WaitForSingleObject(handle, timeout_ms)
            # WAIT_OBJECT_0 = 0x00000000 (kazandı), WAIT_ABANDONED = 0x00000080 (önceki çakıldı)
            if result in (0x00000000, 0x00000080):
                self._handle = handle
                self._acquired = True
                return True
            # WAIT_TIMEOUT = 0x00000102
            kernel32.CloseHandle(handle)
            return False
        except Exception:
            # Non-Windows veya API erişimi yoksa — SQLite lease yeterli
            self._acquired = True
            return True

    def release(self):
        try:
            if self._acquired and self._handle is not None:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.ReleaseMutex(self._handle)
                kernel32.CloseHandle(self._handle)
                self._handle = None
                self._acquired = False
        except Exception:
            pass


# ─── SQLite Lease ─────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _is_lease_stale(expires_at: Optional[str]) -> bool:
    """Kira süresi dolmuş mu? Dolmuşsa stale sayılır, yeni refresh başlayabilir."""
    dt = _parse_iso(expires_at)
    if dt is None:
        return True
    return datetime.now(timezone.utc) >= dt


def _acquire_sqlite_lease(conn, lock_owner: str) -> bool:
    """
    SQLite lease almayı dener.
    RUNNING + lease_expires_at ileride → başka worker var → False döner.
    RUNNING + lease_expires_at geçmişte → stale/çökmüş → lease'i yeniden al.
    """
    row = conn.execute(
        "SELECT state, lease_expires_at FROM rm_refresh_control WHERE direction=?",
        (DIRECTION_PAYABLE,),
    ).fetchone()

    if row is None:
        return False

    state = row[0]
    expires_at = row[1]

    if state == "RUNNING" and not _is_lease_stale(expires_at):
        logger.info("Refresh zaten çalışıyor, lease geçerli — bu run atlanıyor.")
        return False

    # IDLE, QUEUED_MANUAL veya stale RUNNING → al
    now = _now_iso()
    from datetime import timedelta
    expires = datetime.now(timezone.utc) + timedelta(seconds=LEASE_DURATION_SECONDS)
    expires_iso = expires.isoformat(timespec="milliseconds")

    conn.execute(
        """UPDATE rm_refresh_control
           SET state='RUNNING', lock_owner=?, heartbeat_at=?,
               lease_expires_at=?, last_attempt_at=?, updated_at=?
           WHERE direction=?""",
        (lock_owner, now, expires_iso, now, now, DIRECTION_PAYABLE),
    )
    return True


def _release_sqlite_lease(conn, success: bool, error_msg: Optional[str] = None) -> None:
    """Lease'i serbest bırak — state IDLE'a döner."""
    now = _now_iso()
    conn.execute(
        """UPDATE rm_refresh_control
           SET state='IDLE', lock_owner=NULL, heartbeat_at=NULL,
               lease_expires_at=NULL, last_error=?, updated_at=?
           WHERE direction=?""",
        (error_msg, now, DIRECTION_PAYABLE),
    )


def _heartbeat(conn, lock_owner: str) -> None:
    """Uzun süren refresh'lerde lease'i yenile."""
    from datetime import timedelta
    now = _now_iso()
    expires = datetime.now(timezone.utc) + timedelta(seconds=LEASE_DURATION_SECONDS)
    conn.execute(
        """UPDATE rm_refresh_control
           SET heartbeat_at=?, lease_expires_at=?, updated_at=?
           WHERE direction=? AND lock_owner=?""",
        (now, expires.isoformat(timespec="milliseconds"), now, DIRECTION_PAYABLE, lock_owner),
    )


# ─── Decimal JSON serializer ──────────────────────────────────────────────────

class _DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


# ─── Snapshot yazma ───────────────────────────────────────────────────────────

def _ds(v) -> str:
    """Decimal/float/int/str → güvenli Decimal string (float yasak)."""
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


def _write_snapshot_rows(
    conn,
    snapshot_id: str,
    balances: List[Any],
    layer2: Optional[Dict[str, Any]] = None,
    takip_map: Optional[Dict[str, bool]] = None,
    enrichment_maps: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Cari satırlarını rm_snapshot_row'a yazar — V2 tam UI contract.
    BATCH insert, N+1 yok.
    Layer2 (son ödeme/çek/alış) ve CPS-local enrichment (soz/temas/takip/vade)
    refresh sırasında snapshot'a gömülür; web request Korgün çağırmaz.
    """
    from decimal import Decimal as D
    from datetime import date as _date

    def _net_is_zero(net_d: D) -> bool:
        return net_d == D("0")

    def _bakiye_durumu(net_d: D) -> str:
        from .rm_config import DEBT_NET_TOLERANCE_STR
        tol = D(DEBT_NET_TOLERANCE_STR)
        if net_d > tol:
            return "Alacaklıyız"
        if net_d < -tol:
            return "Açık Borç"
        return "Bakiye Yok"

    def _karar(net_d: D) -> tuple:
        """(badge, class, aksiyon)"""
        from .rm_config import DEBT_NET_TOLERANCE_STR
        tol = D(DEBT_NET_TOLERANCE_STR)
        if net_d < -tol:
            return "Açık Borç", "op-st-open", "Ödeme planla"
        if net_d > tol:
            return "Alacaklıyız", "op-st-credit", "—"
        return "Bakiye Yok", "op-st-neutral", "—"

    def _fmt_money(v, pb: str) -> str:
        if v is None:
            return ""
        sym = {"TRY": "₺", "USD": "$", "EUR": "€"}.get(str(pb), str(pb) + " ")
        try:
            return f"{sym}{float(v):,.0f}".replace(",", ".")
        except (TypeError, ValueError):
            return ""

    # Layer2 maps
    pay_map = (layer2 or {}).get("last_payment_map", {})
    cek_map = (layer2 or {}).get("last_cek_map", {})
    pur_map = (layer2 or {}).get("last_purchase_map", {})

    # CPS local maps (contact, promise, term)
    contact_map = (enrichment_maps or {}).get("contact_map", {})
    promise_map = (enrichment_maps or {}).get("promise_map", {})
    term_map = (enrichment_maps or {}).get("term_map", {})
    takip_map = takip_map or {}

    today = _date.today()

    rows = []
    for b in balances:
        net_d = D(str(b.bakiye)) if not isinstance(b.bakiye, D) else b.bakiye
        # borc / alacak ayrımı
        if net_d >= D("0"):
            borc_str = "0"
            alacak_str = _ds(net_d)
        else:
            borc_str = _ds(abs(net_d))
            alacak_str = "0"

        net_str = _ds(net_d)
        disp = _ds(abs(net_d)) if not _net_is_zero(net_d) else "0"
        durum = _bakiye_durumu(net_d)
        karar_badge, karar_class, karar_aksiyon = _karar(net_d)
        canonical_key = f"{b.location}:{b.cari_kod}:{b.para_birimi}"
        canonical_key_pipe = f"{b.location}|{b.cari_kod}"

        # Layer2: son ödeme/çek/alış
        pay = pay_map.get(b.cari_kod)
        cek = cek_map.get(b.cari_kod)
        pur = pur_map.get(b.cari_kod)

        # Son Finansal Aksiyon (FA = max(nakit, çek tarihi))
        cash_date = getattr(pay, "tarih", None)
        cek_date = getattr(cek, "verilis", None)
        if cash_date and cek_date:
            fa_is_cek = cek_date >= cash_date
        elif cek_date:
            fa_is_cek = True
        else:
            fa_is_cek = False

        if fa_is_cek and cek:
            fa_tarih = getattr(cek, "verilis", None)
            fa_turu = "Çek"
            fa_tutar = _ds(getattr(cek, "tutar", None))
            fa_pb = getattr(cek, "pb", None) or b.para_birimi
            fa_vade = getattr(cek, "vade", None)
            fa_cek_no = getattr(cek, "cek_no", None)
            # Vade süresi kısası — çek veriliş → vade gün farkı
            try:
                from datetime import datetime as _dt
                _v = _dt.strptime(str(fa_vade)[:10], "%Y-%m-%d").date() if fa_vade else None
                _s = _dt.strptime(str(fa_tarih)[:10], "%Y-%m-%d").date() if fa_tarih else None
                fa_vade_short = f"{(_v - _s).days}g" if (_v and _s) else ""
            except Exception:
                fa_vade_short = ""
        elif pay:
            fa_tarih = getattr(pay, "tarih", None)
            fa_turu = str(getattr(pay, "kaynak", "") or "")
            fa_tutar = _ds(getattr(pay, "tutar", None))
            fa_pb = getattr(pay, "pb", None) or b.para_birimi
            fa_vade = None
            fa_cek_no = None
            fa_vade_short = ""
        else:
            fa_tarih = fa_turu = fa_vade = fa_cek_no = fa_vade_short = None
            fa_tutar = "0"
            fa_pb = b.para_birimi
            fa_is_cek = False

        # CPS local: aktif takip
        aktif_takip = 1 if takip_map.get(canonical_key_pipe, False) else 0

        # CPS local: enrichment (soz/temas/vade)
        soz_has_active = 0
        soz_is_overdue = 0
        temas_tarih_iso = None
        anlasma_durumu = None
        vade_has_term = 0
        vade_gun = None

        if contact_map or promise_map or term_map:
            _bre = None
            try:
                from modules.finans.services.odeme_plani_enrichment_service import build_row_enrichment as _bre
            except ImportError:
                try:
                    from app.modules.finans.services.odeme_plani_enrichment_service import build_row_enrichment as _bre
                except ImportError:
                    _bre = None
            if _bre is not None:
                try:
                    enrich = _bre(
                        b.location, b.cari_kod,
                        contact_map=contact_map,
                        promise_map=promise_map,
                        term_map=term_map,
                        today=today,
                    )
                    soz_has_active = 1 if enrich.get("soz_has_active") else 0
                    soz_is_overdue = 1 if enrich.get("soz_is_overdue") else 0
                    temas_tarih_iso = enrich.get("temas_tarih_iso")
                    anlasma_durumu = enrich.get("anlasma_durumu")
                    vade_has_term = 1 if enrich.get("vade_has_term") else 0
                    vade_gun = enrich.get("vade_gun")
                except Exception:
                    pass

        rows.append((
            snapshot_id,
            b.location,
            getattr(b, "location_label", b.location),
            b.cari_kod,
            b.cari_adi,
            b.para_birimi,
            borc_str,
            alacak_str,
            net_str,
            canonical_key,
            durum,
            disp,
            # V2 enrichment
            fa_tarih,
            fa_turu,
            fa_tutar,
            fa_pb,
            fa_vade,
            1 if fa_is_cek else 0,
            fa_vade_short,
            fa_cek_no,
            str(getattr(pay, "tarih", None) or "") or None,
            _ds(getattr(pay, "tutar", None)),
            getattr(pay, "pb", None) or b.para_birimi,
            str(getattr(pur, "tarih", None) or "") or None,
            _ds(getattr(pur, "tutar", None)),
            getattr(pur, "pb", None) or b.para_birimi,
            str(getattr(pur, "tip", None) or "") or None,
            str(getattr(cek, "vade", None) or "") or None,
            _ds(getattr(cek, "tutar", None)),
            getattr(cek, "pb", None) or b.para_birimi,
            str(getattr(cek, "cek_no", None) or "") or None,
            aktif_takip,
            karar_badge,
            karar_class,
            karar_aksiyon,
            anlasma_durumu,
            vade_has_term,
            vade_gun,
            soz_has_active,
            soz_is_overdue,
            temas_tarih_iso,
        ))

    conn.executemany(
        """INSERT INTO rm_snapshot_row
           (snapshot_id, location, location_label, cari_kod, cari_adi, para_birimi,
            borc, alacak, net, canonical_key, bakiye_durumu, display_bakiye,
            fa_tarih, fa_turu, fa_tutar, fa_pb, fa_vade, fa_is_cek, fa_vade_short, fa_cek_no,
            son_odeme_tarih, son_odeme_tutar, son_odeme_pb,
            son_alim_tarih, son_alim_tutar, son_alim_pb, son_alim_tip,
            son_cek_vade, son_cek_tutar, son_cek_pb, son_cek_no,
            aktif_takip, karar_badge, karar_class, karar_aksiyon,
            anlasma_durumu, vade_has_term, vade_gun,
            soz_has_active, soz_is_overdue, temas_tarih_iso)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )


# ─── Nesil rotasyonu ──────────────────────────────────────────────────────────

def _rotate_generations(conn, new_active_id: str) -> None:
    """
    Staging snapshot'ı ACTIVE yapar, eski nesilleri döndürür.
    SUCCESSFUL_GENERATIONS = 2 → current + previous.
    """
    now = _now_iso()

    # Mevcut aktif snapshot id
    ctrl = conn.execute(
        "SELECT active_snapshot_id, last_success_id, prev_success_id FROM rm_refresh_control WHERE direction=?",
        (DIRECTION_PAYABLE,),
    ).fetchone()

    current_active = ctrl[0] if ctrl else None
    current_last_success = ctrl[1] if ctrl else None

    # Eski ACTIVE → SUPERSEDED
    if current_active:
        conn.execute(
            "UPDATE rm_snapshot SET status='SUPERSEDED' WHERE snapshot_id=? AND status='ACTIVE'",
            (current_active,),
        )

    # Yeni staging → ACTIVE
    conn.execute(
        """UPDATE rm_snapshot
           SET status='ACTIVE', published_at=?
           WHERE snapshot_id=? AND status='STAGING'""",
        (now, new_active_id),
    )

    # rm_refresh_control güncelle
    # prev_success = eski last_success
    # last_success = yeni active
    prev = current_active  # yeni "previous" nesil

    conn.execute(
        """UPDATE rm_refresh_control
           SET active_snapshot_id=?, last_success_id=?, prev_success_id=?,
               last_success_at=?, updated_at=?
           WHERE direction=?""",
        (new_active_id, new_active_id, prev, now, now, DIRECTION_PAYABLE),
    )

    # rm_pointer güncelle
    conn.execute(
        """UPDATE rm_pointer
           SET active_snapshot_id=?, last_success_id=?, updated_at=?
           WHERE direction=?""",
        (new_active_id, new_active_id, now, DIRECTION_PAYABLE),
    )

    # GENERATIONS'tan fazla SUPERSEDED'ı temizle (2 nesil → 1 adet superseded tutulabilir)
    # Basit strateji: en eski SUPERSEDED'ı soft-delete et (satırları sil)
    old_snapshots = conn.execute(
        """SELECT snapshot_id FROM rm_snapshot
           WHERE direction=? AND status='SUPERSEDED'
           ORDER BY published_at ASC""",
        (DIRECTION_PAYABLE,),
    ).fetchall()

    # current + previous = 2; bunun ötesindeki superseded'lar temizlenir
    keep_ids = {new_active_id, prev} if prev else {new_active_id}

    for row in old_snapshots:
        sid = row[0]
        if sid in keep_ids:
            continue
        # Satırları sil, snapshot header'ı koru (audit trail)
        conn.execute("DELETE FROM rm_snapshot_row WHERE snapshot_id=?", (sid,))
        conn.execute(
            "UPDATE rm_snapshot SET status='SUPERSEDED' WHERE snapshot_id=?",
            (sid,),
        )


# ─── Ana refresh fonksiyonu ───────────────────────────────────────────────────

class RefreshError(Exception):
    """Refresh başarısız — detay sanitize edilmiş."""
    def __init__(self, msg: str, parity_failure: bool = False):
        super().__init__(msg)
        self.parity_failure = parity_failure


def _import_adapter():
    """KorgunFinanceAdapter'ı import et — dual import desteği."""
    try:
        from modules.finans.services.korgun_finance_adapter import KorgunFinanceAdapter
    except ImportError:
        from app.modules.finans.services.korgun_finance_adapter import KorgunFinanceAdapter
    return KorgunFinanceAdapter


def run_refresh(
    db_path: Optional[str] = None,
    *,
    locations: Optional[List[str]] = None,
    force: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Tam PAYABLE refresh çalıştırır.

    Returns: {"ok": bool, "snapshot_id": str|None, "parity": {...}, "elapsed_ms": int, ...}
    Loglarda cari finans detayları YOKTUR.
    """
    lock_owner = f"pid={os.getpid()}_ts={int(time.time())}"
    mutex = _WindowsMutexLock()
    start_ts = time.time()
    snapshot_id = str(uuid.uuid4())

    # 1. Windows Named Mutex
    if not mutex.try_acquire(timeout_ms=0):
        logger.warning("Named mutex alınamadı — başka refresh çalışıyor olabilir.")
        return {
            "ok": False,
            "snapshot_id": None,
            "reason": "MUTEX_BUSY",
            "elapsed_ms": int((time.time() - start_ts) * 1000),
        }

    try:
        with open_readwrite(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")

            # 2. SQLite lease
            if not _acquire_sqlite_lease(conn, lock_owner):
                conn.execute("ROLLBACK")
                mutex.release()
                return {
                    "ok": False,
                    "snapshot_id": None,
                    "reason": "LEASE_BUSY",
                    "elapsed_ms": int((time.time() - start_ts) * 1000),
                }
            conn.execute("COMMIT")

            try:
                result = _do_refresh(
                    conn=conn,
                    snapshot_id=snapshot_id,
                    lock_owner=lock_owner,
                    locations=locations,
                    dry_run=dry_run,
                )
                conn.execute("BEGIN IMMEDIATE")
                _release_sqlite_lease(conn, success=True)
                conn.execute("COMMIT")
                return result

            except RefreshError as exc:
                logger.error("Refresh başarısız: %s", str(exc))
                # ACTIVE snapshot korunur — yalnız staging FAILED olarak işaretlenir
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE rm_snapshot SET status='FAILED', error_message=? WHERE snapshot_id=?",
                    (str(exc)[:200], snapshot_id),
                )
                conn.execute(
                    """UPDATE rm_refresh_control
                       SET last_attempt_id=?, last_error=?
                       WHERE direction=?""",
                    (snapshot_id, str(exc)[:200], DIRECTION_PAYABLE),
                )
                _release_sqlite_lease(conn, success=False, error_msg=str(exc)[:200])
                conn.execute("COMMIT")
                elapsed = int((time.time() - start_ts) * 1000)
                return {
                    "ok": False,
                    "snapshot_id": snapshot_id,
                    "reason": "PARITY_FAILURE" if exc.parity_failure else "REFRESH_ERROR",
                    "elapsed_ms": elapsed,
                }

            except Exception as exc:
                sanitized = sanitize_error(exc)
                logger.error("Beklenmeyen refresh hatası: %s", sanitized)
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        "UPDATE rm_snapshot SET status='FAILED', error_message=? WHERE snapshot_id=?",
                        (sanitized, snapshot_id),
                    )
                    _release_sqlite_lease(conn, success=False, error_msg=sanitized)
                    conn.execute("COMMIT")
                except Exception:
                    pass
                elapsed = int((time.time() - start_ts) * 1000)
                return {"ok": False, "snapshot_id": snapshot_id, "reason": "UNEXPECTED_ERROR", "elapsed_ms": elapsed}

    finally:
        mutex.release()


def _do_refresh(
    conn,
    snapshot_id: str,
    lock_owner: str,
    locations: Optional[List[str]],
    dry_run: bool,
) -> Dict[str, Any]:
    """İç refresh işlemi — lease alındıktan sonra çalışır."""
    now = _now_iso()
    start_ts = time.time()

    # STAGING snapshot oluştur
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        """INSERT INTO rm_snapshot
           (snapshot_id, direction, status, schema_version, refresh_started_at)
           VALUES (?, ?, 'STAGING', ?, ?)""",
        (snapshot_id, DIRECTION_PAYABLE, SCHEMA_VERSION, now),
    )
    conn.execute(
        "UPDATE rm_refresh_control SET last_attempt_id=? WHERE direction=?",
        (snapshot_id, DIRECTION_PAYABLE),
    )
    conn.execute("COMMIT")

    # Korgün'den veri çek (fetch_supplier_balances_bundle — kapsam daraltılmaz)
    logger.info("Korgün balance bundle fetch başlıyor. snapshot_id=%s", snapshot_id)
    fetch_start = time.time()

    KorgunFinanceAdapter = _import_adapter()
    adapter = KorgunFinanceAdapter()
    supplier_master, debt_balances = adapter.fetch_supplier_balances_bundle(
        locations=locations,
        force_refresh=True,  # Her refresh'te fresh Korgün verisi
    )
    fetch_elapsed_ms = int((time.time() - fetch_start) * 1000)

    logger.info(
        "Korgün fetch tamamlandı: toplam=%d borç=%d elapsed=%dms",
        len(supplier_master), len(debt_balances), fetch_elapsed_ms,
    )

    # Heartbeat — uzun fetch sonrası lease yenile
    _heartbeat(conn, lock_owner)

    # KPI özeti (float KULLANMA)
    from .rm_parity import build_source_summary, _d, _q
    source_summary = build_source_summary(supplier_master)

    kpi_data = {
        "toplam_net": str(source_summary.kpi_toplam_net),
        "row_count": source_summary.row_count,
        "unique_cari": source_summary.unique_cari,
        "companies": sorted(source_summary.companies),
        "currencies": sorted(source_summary.currencies),
    }

    # Layer2 enrichment — son ödeme/çek/alış (Korgün batch, 3 sorgu)
    layer2: Dict[str, Any] = {}
    try:
        layer2 = _fetch_layer2(locations=locations)
        logger.info("Layer2 fetch tamamlandı: elapsed=%dms", layer2.get("elapsed_ms", 0))
    except Exception as _l2_exc:
        logger.warning("Layer2 fetch başarısız (enrichment boş olacak): %s", sanitize_error(_l2_exc))

    # CPS-local enrichment — soz/temas/vade/takip (SQLite, Korgün yok)
    takip_map: Dict[str, bool] = {}
    enrichment_maps: Dict[str, Any] = {}
    try:
        takip_map = _fetch_takip(locations=locations)
        _enrich_ckods = [b.cari_kod for b in supplier_master]
        contact_map, promise_map, term_map = _fetch_enrichment(locations, _enrich_ckods)
        enrichment_maps = {
            "contact_map": contact_map,
            "promise_map": promise_map,
            "term_map": term_map,
        }
        logger.info("CPS local enrichment tamamlandı: takip=%d contact=%d promise=%d term=%d",
                    len(takip_map), len(contact_map), len(promise_map), len(term_map))
    except Exception as _enr_exc:
        logger.warning("CPS enrichment fetch başarısız (default olacak): %s", sanitize_error(_enr_exc))

    # Heartbeat
    _heartbeat(conn, lock_owner)

    # Satırları STAGING snapshot'a yaz (V2 tam UI contract)
    conn.execute("BEGIN IMMEDIATE")
    _write_snapshot_rows(conn, snapshot_id, supplier_master,
                         layer2=layer2, takip_map=takip_map,
                         enrichment_maps=enrichment_maps)
    conn.execute("COMMIT")

    fetch_completed = _now_iso()
    logger.info("Snapshot satırları yazıldı: row_count=%d", len(supplier_master))

    # Heartbeat
    _heartbeat(conn, lock_owner)

    # Parity gate — DB'den yeniden oku ve karşılaştır
    db_summary = build_db_summary(conn, snapshot_id)
    parity = run_parity_gate(source_summary, db_summary)

    if not parity.passed:
        logger.error(
            "Parity FAIL: %s — snapshot reddediliyor.",
            parity.failure_reasons,
        )
        raise RefreshError(
            f"Parity gate başarısız: {len(parity.failure_reasons)} kontrol geçemedi",
            parity_failure=True,
        )

    logger.info("Parity PASS: %s kontrol geçti.", len(parity.checks))

    if dry_run:
        # Dry-run: staging FAILED olarak işaretle (yayınlama)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE rm_snapshot SET status='FAILED', error_message='dry_run' WHERE snapshot_id=?",
            (snapshot_id,),
        )
        conn.execute("COMMIT")
        elapsed = int((time.time() - start_ts) * 1000)
        return {
            "ok": True,
            "dry_run": True,
            "snapshot_id": snapshot_id,
            "parity_passed": True,
            "parity_checks": len(parity.checks),
            "row_count": len(supplier_master),
            "source_hash": source_summary.canonical_hash,
            "elapsed_ms": elapsed,
            "fetch_ms": fetch_elapsed_ms,
        }

    # Atomic pointer flip: staging → ACTIVE, eski nesiller döndürülür
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        """UPDATE rm_snapshot
           SET refresh_completed_at=?, source_duration_ms=?,
               source_hash=?, row_count=?, unique_cari_count=?,
               company_count=?, currency_count=?, kpi_json=?
           WHERE snapshot_id=?""",
        (
            fetch_completed,
            fetch_elapsed_ms,
            source_summary.canonical_hash,
            source_summary.row_count,
            source_summary.unique_cari,
            len(source_summary.companies),
            len(source_summary.currencies),
            json.dumps(kpi_data, cls=_DecimalEncoder),
            snapshot_id,
        ),
    )
    _rotate_generations(conn, snapshot_id)
    conn.execute("COMMIT")

    elapsed = int((time.time() - start_ts) * 1000)
    logger.info(
        "Refresh TAMAMLANDI: snapshot_id=%s rows=%d elapsed=%dms",
        snapshot_id, len(supplier_master), elapsed,
    )

    return {
        "ok": True,
        "snapshot_id": snapshot_id,
        "parity_passed": True,
        "parity_checks": len(parity.checks),
        "row_count": len(supplier_master),
        "source_hash": source_summary.canonical_hash,
        "elapsed_ms": elapsed,
        "fetch_ms": fetch_elapsed_ms,
    }
