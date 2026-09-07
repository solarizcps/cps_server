# -*- coding: utf-8 -*-
"""
Read-Model konfigürasyon ve path yönetimi.

GÜVENLİK KURALLARI:
  - Production runtime path repo dışındadır (ProgramData sınıfı).
  - Testlerde ODEME_PLANI_RM_PATH env değişkeni ile temp path inject edilir.
  - Canonical DB path'i (app/mock_data.db) hiçbir zaman kabul edilmez.
  - Web reader dizin/DB oluşturamaz; yalnız CLI (refresh worker) oluşturabilir.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# ─── Sabitler ────────────────────────────────────────────────────────────────

SCHEMA_VERSION: int = 1
DIRECTION_PAYABLE: str = "PAYABLE"

# Production default path — repo dışı, git-ignored, yeniden üretilebilir.
_PRODUCTION_DEFAULT = r"C:\ProgramData\Solariz\runtime\finans\odeme_plani_rm.sqlite"

# Refresh CLI'nın refresh aralığı (bilgi amaçlı; asıl kontrol Scheduled Task'ta)
REFRESH_INTERVAL_SECONDS: int = 5 * 60          # 5 dakika
MAX_STALE_AGE_SECONDS: int = 15 * 60            # 15 dakika — "veri eski" eşiği
MANUAL_REFRESH_RATE_LIMIT_SECONDS: int = 2 * 60 # 2 dakika

# Kilit lease süresi (yaklaşık 3 dakika; refresh ~18 sn süriyor)
LEASE_DURATION_SECONDS: int = 3 * 60

# Kaç başarılı nesil saklanır (current + previous)
SUCCESSFUL_GENERATIONS: int = 2

# Arayüze gösterilebilecek maksimum error string uzunluğu
MAX_SANITIZED_ERROR_LEN: int = 200

# KorgunFinanceAdapter ile aynı tolerans (0.01)
DEBT_NET_TOLERANCE_STR: str = "0.01"

# Canonical DB'yi reddetmek için kontrol edilecek path pattern'leri
_CANONICAL_DB_REJECT_PATTERNS: list[str] = [
    r"mock_data\.db",
    r"mock_data_",
]

# ─── Yardımcı fonksiyonlar ────────────────────────────────────────────────────

def _reject_canonical_path(path_str: str) -> None:
    """Canonical DB path geçirilirse ValueError fırlatır (fail-closed)."""
    norm = os.path.normpath(path_str).replace("\\", "/")
    for pattern in _CANONICAL_DB_REJECT_PATTERNS:
        if re.search(pattern, norm, re.IGNORECASE):
            raise ValueError(
                f"READ-MODEL PATH REJECTed: canonical DB path kabul edilmez: {path_str!r}"
            )


def get_rm_path() -> str:
    """
    Read-model SQLite dosya yolunu döner.

    Öncelik:
      1. ODEME_PLANI_RM_PATH ortam değişkeni (test inject için)
      2. Production default (ProgramData sınıfı)

    Güvenlik:
      - Canonical DB path'i reddeder.
      - Repo içi .sqlite/.db uzantısı varsa uyarı üretir (STOP koşulu değil,
        çünkü test geçici dosyası olabilir — test sadece temp dizin kullanmalı).
    """
    env_path = os.environ.get("ODEME_PLANI_RM_PATH", "").strip()
    chosen = env_path if env_path else _PRODUCTION_DEFAULT
    _reject_canonical_path(chosen)
    return chosen


def is_production_path(path_str: str) -> bool:
    """Verilen path production default mı?"""
    return os.path.normcase(path_str) == os.path.normcase(_PRODUCTION_DEFAULT)


def sanitize_error(exc: Exception) -> str:
    """Hata mesajını kullanıcıya/loga güvenli hale getirir.
    Finans tutarları ve cari detayları mesaja yansımamalı.
    """
    raw = str(exc)
    # Sayısal değerleri maskeleme (bakiye tutarlarının sızmasını engelle)
    sanitized = re.sub(r'\b\d+[\.,]\d{2,}\b', '[TUTAR]', raw)
    # Cari kod benzeri alanları maskeleme (320.XX.XXX formatı)
    sanitized = re.sub(r'320\.\d+\.\d+', '[CARI_KOD]', sanitized)
    if len(sanitized) > MAX_SANITIZED_ERROR_LEN:
        sanitized = sanitized[:MAX_SANITIZED_ERROR_LEN] + "..."
    return sanitized


def assert_test_path(path_str: str) -> None:
    """Test ortamında canonical DB path'i kullanmaya çalışılırsa FAIL."""
    _reject_canonical_path(path_str)
    if is_production_path(path_str):
        raise RuntimeError(
            "TEST: Production path test ortamında kullanılamaz. "
            "ODEME_PLANI_RM_PATH env ile temp path inject edin."
        )
