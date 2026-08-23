# -*- coding: utf-8 -*-
"""
Araç GPS poll worker — browser-independent Filom snapshot + sapma engine.

Pilot interval: 60 seconds (temporary until Filom rate limit confirmed).
Single /mobiles call per cycle.

Usage:
  set CPS_MOCK_DB_PATH=C:\\path\\to\\temp.db
  python app/tools/arac_gps_poll_worker.py

One-shot smoke:
  python app/tools/arac_gps_poll_worker.py --once
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

CANONICAL = os.path.join(ROOT, 'mock_data.db')
DEFAULT_INTERVAL_SEC = int(os.environ.get('ARAC_GPS_POLL_INTERVAL_SEC', '60'))
BACKOFF_BASE_SEC = int(os.environ.get('ARAC_GPS_POLL_BACKOFF_SEC', '15'))
BACKOFF_MAX_SEC = int(os.environ.get('ARAC_GPS_POLL_BACKOFF_MAX_SEC', '300'))
LOCK_PATH = os.environ.get(
    'ARAC_GPS_POLL_LOCK_PATH',
    os.path.join(os.environ.get('TEMP', '.'), 'arac_gps_poll_worker.lock'),
)

log = logging.getLogger('arac_gps_poll_worker')
_stop = False


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [GPS-WORKER] %(levelname)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )


def _assert_temp_db() -> None:
    active = os.environ.get('CPS_MOCK_DB_PATH') or CANONICAL
    if os.path.normcase(os.path.normpath(active)) == os.path.normcase(os.path.normpath(CANONICAL)):
        log.error('STOP: CPS_MOCK_DB_PATH required — canonical DB write forbidden')
        raise SystemExit(2)


class _SingleInstanceLock:
    def __init__(self, path: str):
        self.path = path
        self._fh = None

    def acquire(self) -> bool:
        import msvcrt
        os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
        self._fh = open(self.path, 'a+b')
        try:
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            self._fh.seek(0)
            self._fh.truncate()
            self._fh.write(str(os.getpid()).encode('ascii'))
            self._fh.flush()
            return True
        except OSError:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None
            return False

    def release(self) -> None:
        if not self._fh:
            return
        import msvcrt
        try:
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            self._fh.close()
        except Exception:
            pass
        self._fh = None


def _handle_stop(signum, frame) -> None:
    global _stop
    _stop = True
    log.info('stop signal=%s', signum)


def run_cycle(backoff_sec: int) -> tuple[bool, int]:
    from modules.planlama.arac_gps_poll_service import poll_once
    result = poll_once()
    log.info(
        'poll ok=%s inserted=%s dedup=%s rejected=%s vehicles=%s',
        result.get('ok'), result.get('inserted'), result.get('skipped_dedup'),
        result.get('rejected'), result.get('vehicles_total'),
    )
    if not result.get('ok'):
        wait = min(backoff_sec, BACKOFF_MAX_SEC)
        log.warning('poll failed fetch_error=%s backoff=%ss', result.get('fetch_error'), wait)
        return False, wait
    dev = result.get('deviation') or {}
    log.info('deviation processed=%s last_id=%s', dev.get('processed'), dev.get('last_id'))
    return True, DEFAULT_INTERVAL_SEC


def main() -> int:
    _configure_logging()
    _assert_temp_db()
    once = '--once' in sys.argv
    log.info(
        'start interval=%ss pilot=TEMP until Filom rate limit confirmed lock=%s',
        DEFAULT_INTERVAL_SEC, LOCK_PATH,
    )

    lock = _SingleInstanceLock(LOCK_PATH)
    if not lock.acquire():
        log.warning('another worker instance is running — exiting')
        return 0

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    backoff = BACKOFF_BASE_SEC
    try:
        while not _stop:
            ok, wait_sec = run_cycle(backoff)
            backoff = BACKOFF_BASE_SEC if ok else min(backoff * 2, BACKOFF_MAX_SEC)
            if once:
                break
            log.info('sleep %ss', wait_sec)
            slept = 0
            while slept < wait_sec and not _stop:
                time.sleep(min(1, wait_sec - slept))
                slept += 1
    finally:
        lock.release()
        log.info('stopped')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
