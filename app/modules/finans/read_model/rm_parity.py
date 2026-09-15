# -*- coding: utf-8 -*-
"""
Muhasebe Parity Gate — Kaynak bundle ile persisted snapshot karşılaştırması.

KURAL:
  - Tek kuruş veya kapsam farkı varsa snapshot reddedilir (publish edilmez).
  - Float kullanılmaz — tüm karşılaştırmalar Decimal üzerinden.
  - Satır içerikleri (cari, tutar) loglara basılmaz.

Karşılaştırılan boyutlar:
  1. Toplam satır sayısı
  2. Unique cari sayısı
  3. Şirket kümesi
  4. Para birimi kümesi
  5. Şirket + PB bazında SUM(borc)
  6. Şirket + PB bazında SUM(alacak)
  7. Şirket + PB bazında SUM(net)
  8. Genel KPI toplamları
  9. Deterministic canonical hash
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any, Dict, List, Optional, Tuple


# ─── Decimal yardımcıları ─────────────────────────────────────────────────────

_QUANT = Decimal("0.000001")   # 6 hane hassasiyet (muhasebe yuvarlama korunur)


def _d(v: Any) -> Decimal:
    """Güvenli Decimal dönüşüm — float→str→Decimal (IEEE 754 birikim hatası yok)."""
    if isinstance(v, Decimal):
        return v
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, str):
        return Decimal(v.strip() or "0")
    return Decimal("0")


def _q(v: Decimal) -> Decimal:
    """Canonical yuvarlama — 6 hane."""
    return v.quantize(_QUANT, rounding=ROUND_HALF_EVEN)


# ─── Source summary (kaynak bundle özeti) ────────────────────────────────────

@dataclass
class SourceSummary:
    """fetch_supplier_balances_bundle() çıktısından türetilmiş özet."""
    row_count: int = 0
    unique_cari: int = 0
    companies: frozenset = field(default_factory=frozenset)
    currencies: frozenset = field(default_factory=frozenset)
    # (location, para_birimi) → {borc, alacak, net}
    company_pb_agg: Dict[Tuple[str, str], Dict[str, Decimal]] = field(default_factory=dict)
    kpi_toplam_net: Decimal = Decimal("0")
    canonical_hash: str = ""


def build_source_summary(balances: List[Any]) -> SourceSummary:
    """
    KorgunFinanceAdapter'dan gelen SupplierBalanceDTO listesinden SourceSummary üretir.

    balances: List[SupplierBalanceDTO]  (location, cari_kod, para_birimi, bakiye alanları beklenir)
    bakiye: net = alacak - borc  (KorgunFinanceAdapter semantiği — pozitif = alacaklıyız)
    """
    agg: Dict[Tuple[str, str], Dict[str, Decimal]] = {}
    cari_set: set = set()
    comp_set: set = set()
    pb_set: set = set()
    hash_inputs: List[str] = []

    for b in balances:
        loc = b.location
        cari = b.cari_kod
        pb = b.para_birimi
        net = _d(b.bakiye)

        # borc / alacak: KorgunFinanceAdapter net semantiği
        # net > 0  → alacaklıyız (alacak > borc)
        # net < 0  → açık borç  (borc > alacak)
        if net >= Decimal("0"):
            borc_val = Decimal("0")
            alacak_val = net
        else:
            borc_val = abs(net)
            alacak_val = Decimal("0")

        key = (loc, pb)
        if key not in agg:
            agg[key] = {"borc": Decimal("0"), "alacak": Decimal("0"), "net": Decimal("0")}
        agg[key]["borc"] += borc_val
        agg[key]["alacak"] += alacak_val
        agg[key]["net"] += net

        cari_set.add(f"{loc}:{cari}:{pb}")
        comp_set.add(loc)
        pb_set.add(pb)

        # Deterministik hash girdisi (location+cari_kod+pb sıralamalı, tutar dahil)
        hash_inputs.append(f"{loc}|{cari}|{pb}|{_q(net)}")

    # Toplam net KPI
    total_net = sum((v["net"] for v in agg.values()), Decimal("0"))

    # Canonical hash — satır sırası bağımsız, her kombinasyon aynı hash'i üretmeli
    hash_inputs.sort()
    canonical_hash = hashlib.sha256(
        "\n".join(hash_inputs).encode("utf-8")
    ).hexdigest()

    return SourceSummary(
        row_count=len(balances),
        unique_cari=len(cari_set),
        companies=frozenset(comp_set),
        currencies=frozenset(pb_set),
        company_pb_agg=agg,
        kpi_toplam_net=_q(total_net),
        canonical_hash=canonical_hash,
    )


# ─── DB summary (persisted snapshot özeti) ────────────────────────────────────

@dataclass
class DBSummary:
    """rm_snapshot_row tablosundan yeniden okunan özet."""
    row_count: int = 0
    unique_cari: int = 0
    companies: frozenset = field(default_factory=frozenset)
    currencies: frozenset = field(default_factory=frozenset)
    company_pb_agg: Dict[Tuple[str, str], Dict[str, Decimal]] = field(default_factory=dict)
    kpi_toplam_net: Decimal = Decimal("0")
    canonical_hash: str = ""


def build_db_summary(conn: sqlite3.Connection, snapshot_id: str) -> DBSummary:
    """rm_snapshot_row'dan DBSummary üretir."""
    rows = conn.execute(
        """SELECT location, cari_kod, para_birimi, borc, alacak, net
           FROM rm_snapshot_row
           WHERE snapshot_id = ?""",
        (snapshot_id,),
    ).fetchall()

    agg: Dict[Tuple[str, str], Dict[str, Decimal]] = {}
    cari_set: set = set()
    comp_set: set = set()
    pb_set: set = set()
    hash_inputs: List[str] = []

    for r in rows:
        loc, cari, pb = r[0], r[1], r[2]
        borc = _d(r[3])
        alacak = _d(r[4])
        net = _d(r[5])

        key = (loc, pb)
        if key not in agg:
            agg[key] = {"borc": Decimal("0"), "alacak": Decimal("0"), "net": Decimal("0")}
        agg[key]["borc"] += borc
        agg[key]["alacak"] += alacak
        agg[key]["net"] += net

        cari_set.add(f"{loc}:{cari}:{pb}")
        comp_set.add(loc)
        pb_set.add(pb)

        hash_inputs.append(f"{loc}|{cari}|{pb}|{_q(net)}")

    total_net = sum((v["net"] for v in agg.values()), Decimal("0"))
    hash_inputs.sort()
    canonical_hash = hashlib.sha256(
        "\n".join(hash_inputs).encode("utf-8")
    ).hexdigest()

    return DBSummary(
        row_count=len(rows),
        unique_cari=len(cari_set),
        companies=frozenset(comp_set),
        currencies=frozenset(pb_set),
        company_pb_agg=agg,
        kpi_toplam_net=_q(total_net),
        canonical_hash=canonical_hash,
    )


# ─── Parity Gate ─────────────────────────────────────────────────────────────

@dataclass
class ParityResult:
    passed: bool
    checks: List[Dict[str, Any]] = field(default_factory=list)
    failure_reasons: List[str] = field(default_factory=list)
    source_hash: str = ""
    db_hash: str = ""


def run_parity_gate(source: SourceSummary, db: DBSummary) -> ParityResult:
    """
    Kaynak özeti ile DB özeti arasında parity kontrol eder.

    Her kontrol başarısız olursa result.passed = False.
    Satır içerikleri (tutar, cari kod) failure mesajlarına yansımaz.
    """
    failures: List[str] = []
    checks: List[Dict[str, Any]] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            failures.append(name + (f": {detail}" if detail else ""))

    # 1. Satır sayısı
    _check(
        "row_count",
        source.row_count == db.row_count,
        f"kaynak={source.row_count} db={db.row_count}" if source.row_count != db.row_count else "",
    )

    # 2. Unique cari
    _check(
        "unique_cari_count",
        source.unique_cari == db.unique_cari,
        f"kaynak={source.unique_cari} db={db.unique_cari}" if source.unique_cari != db.unique_cari else "",
    )

    # 3. Şirket kümesi
    _check(
        "company_set",
        source.companies == db.companies,
        f"eksik={source.companies - db.companies} fazla={db.companies - source.companies}"
        if source.companies != db.companies else "",
    )

    # 4. Para birimi kümesi
    _check(
        "currency_set",
        source.currencies == db.currencies,
        f"eksik={source.currencies - db.currencies} fazla={db.currencies - source.currencies}"
        if source.currencies != db.currencies else "",
    )

    # 5-7. Şirket + PB bazında borc/alacak/net
    all_keys = source.company_pb_agg.keys() | db.company_pb_agg.keys()
    for key in sorted(all_keys):
        loc, pb = key
        s_vals = source.company_pb_agg.get(key, {"borc": Decimal("0"), "alacak": Decimal("0"), "net": Decimal("0")})
        d_vals = db.company_pb_agg.get(key, {"borc": Decimal("0"), "alacak": Decimal("0"), "net": Decimal("0")})

        for field_name in ("borc", "alacak", "net"):
            s_v = _q(s_vals[field_name])
            d_v = _q(d_vals[field_name])
            _check(
                f"agg_{field_name}_{loc}_{pb}",
                s_v == d_v,
                # Tutarları loga basma — sadece eşit olup olmadığı
                f"FARK VAR" if s_v != d_v else "",
            )

    # 8. Genel net KPI
    _check(
        "kpi_toplam_net",
        _q(source.kpi_toplam_net) == _q(db.kpi_toplam_net),
        "FARK VAR" if _q(source.kpi_toplam_net) != _q(db.kpi_toplam_net) else "",
    )

    # 9. Canonical hash
    _check(
        "canonical_hash",
        source.canonical_hash == db.canonical_hash,
        "HASH_MISMATCH" if source.canonical_hash != db.canonical_hash else "",
    )

    return ParityResult(
        passed=len(failures) == 0,
        checks=checks,
        failure_reasons=failures,
        source_hash=source.canonical_hash,
        db_hash=db.canonical_hash,
    )
