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

def _write_snapshot_rows(
    conn,
    snapshot_id: str,
    balances: List[Any],
) -> None:
    """
    Cari satırlarını rm_snapshot_row'a yazar.
    BATCH insert — N+1 yok.
    Tutar değerleri Decimal string olarak saklanır.
    """
    from decimal import Decimal as D

    def _d(v) -> str:
        if isinstance(v, D):
            return str(v)
        if isinstance(v, float):
            return str(D(str(v)))
        if isinstance(v, (int, str)):
            return str(D(str(v) if isinstance(v, str) else v))
        return "0"

    def _net_is_zero(net_d) -> bool:
        return D(str(net_d)) == D("0")

    def _bakiye_durumu(net_d) -> str:
        from .rm_config import DEBT_NET_TOLERANCE_STR
        tol = D(DEBT_NET_TOLERANCE_STR)
        if net_d > tol:
            return "Alacaklıyız"
        if net_d < -tol:
            return "Açık Borç"
        return "Bakiye Yok"

    rows = []
    for b in balances:
        net_d = D(str(b.bakiye)) if not isinstance(b.bakiye, D) else b.bakiye
        # borc / alacak ayrımı
        if net_d >= D("0"):
            borc_str = "0"
            alacak_str = _d(net_d)
        else:
            borc_str = _d(abs(net_d))
            alacak_str = "0"

        net_str = _d(net_d)
        disp = _d(abs(net_d)) if not _net_is_zero(net_d) else "0"
        durum = _bakiye_durumu(net_d)
        canonical_key = f"{b.location}:{b.cari_kod}:{b.para_birimi}"

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
        ))

    conn.executemany(
        """INSERT INTO rm_snapshot_row
           (snapshot_id, location, location_label, cari_kod, cari_adi, para_birimi,
            borc, alacak, net, canonical_key, bakiye_durumu, display_bakiye)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
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

    # Satırları STAGING snapshot'a yaz
    conn.execute("BEGIN IMMEDIATE")
    _write_snapshot_rows(conn, snapshot_id, supplier_master)
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
