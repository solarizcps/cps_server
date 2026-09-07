# -*- coding: utf-8 -*-
"""
Ödeme Planı PAYABLE Read-Model — CLI Entrypoint.

Kullanım (Windows Scheduled Task veya manuel):
    python -m app.modules.finans.read_model.rm_cli [--db-path PATH] [--dry-run]

Exit codes:
    0  — başarılı refresh ve publish
    1  — refresh hata (parity fail, Korgün erişilemez vb.)
    2  — lease meşgul (başka refresh zaten çalışıyor)
    3  — konfigürasyon hatası (canonical DB path vb.)

Scheduled Task örneği (her 5 dakika):
    schtasks /Create /TN "CPS_OdemePlaniRefresh"
             /TR "python C:\\Solariz_CPS_SERVER\\app\\modules\\finans\\read_model\\rm_cli.py"
             /SC MINUTE /MO 5 /RU "SOLARIZ_SVC"

GÜVENLİK:
    - Loglarda cari finans detayları YOKTUR.
    - Canonical app/mock_data.db'ye dokunmaz.
    - Production runtime path dışında çalışmak için ODEME_PLANI_RM_PATH set edin.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

# Logging yapılandırması
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("cps.finans.rm_cli")


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="CPS Ödeme Planı PAYABLE Read-Model Refresh CLI",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Read-model SQLite dosya yolu (default: ODEME_PLANI_RM_PATH env veya production default)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parity doğrulama yapar ama publish etmez (test amaçlı).",
    )
    parser.add_argument(
        "--locations",
        default=None,
        help="Virgülle ayrılmış şirket kodları (default: tümü). Örnek: SA001,YN001",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    """CLI ana fonksiyon. Exit code döner."""
    args = _parse_args(argv)

    # Konfigürasyon kontrolü
    try:
        from .rm_config import get_rm_path, _reject_canonical_path
        db_path = args.db_path or get_rm_path()
        _reject_canonical_path(db_path)
    except ValueError as exc:
        logger.critical("Konfigürasyon hatası: %s", exc)
        return 3
    except Exception as exc:
        logger.critical("Başlatma hatası: %s", exc)
        return 3

    locations = None
    if args.locations:
        locations = [s.strip().upper() for s in args.locations.split(",") if s.strip()]

    logger.info(
        "Refresh başlıyor. db_path=%s dry_run=%s locations=%s",
        db_path if not _is_production(db_path) else "[PRODUCTION]",
        args.dry_run,
        locations or "all",
    )

    start = time.time()

    try:
        from .rm_refresh import run_refresh
        result = run_refresh(
            db_path=db_path,
            locations=locations,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        from .rm_config import sanitize_error
        logger.critical("Beklenmeyen hata: %s", sanitize_error(exc))
        return 1

    elapsed = int((time.time() - start) * 1000)
    ok = result.get("ok", False)
    reason = result.get("reason", "")

    if reason in ("MUTEX_BUSY", "LEASE_BUSY"):
        logger.info("Refresh atlandı (zaten çalışıyor): reason=%s", reason)
        return 2

    if ok:
        logger.info(
            "Refresh başarılı: snapshot_id=%s rows=%d parity=%s elapsed=%dms dry_run=%s",
            result.get("snapshot_id"),
            result.get("row_count", 0),
            result.get("parity_passed"),
            elapsed,
            result.get("dry_run", False),
        )
        return 0
    else:
        logger.error(
            "Refresh başarısız: reason=%s snapshot_id=%s elapsed=%dms",
            reason,
            result.get("snapshot_id"),
            elapsed,
        )
        return 1


def _is_production(path: str) -> bool:
    """Production path'i log'da maskele."""
    try:
        from .rm_config import is_production_path
        return is_production_path(path)
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
