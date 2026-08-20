# -*- coding: utf-8 -*-
"""
KorgunFinanceAdapter — READ-ONLY Korgün finans verisi.

Akış: Korgün → KorgunFinanceAdapter → Finance DTO → CPS API → Ödeme Planı UI

INSERT / UPDATE / DELETE YOK — yalnızca SELECT.

P3A.3: 45s TTL process-level in-memory cache (fetch_supplier_balances).
  Cache key: "balances:v2:{company}@{finance_scope}|..."  (P3A.8 consolidated scope)
  TTL: 45 saniye
  Explicit refresh: cache_invalidate_balances(locations) veya ?refresh=1 backend
  Multi-user safe: bakiye verisi kişisel değil.
  Ödeme Sözü / Aradı / CPS write verileri cache'lenmez.
"""
from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from modules.common.korgun import _baglan
except ImportError:
    from app.modules.common.korgun import _baglan


# ── Process-level balance cache ──────────────────────────────────────────────
_BALANCE_CACHE: Dict[str, tuple] = {}   # key → (fetched_at: float, data: list)
_CACHE_TTL: int = 45                     # saniye
_CACHE_LOCK = threading.Lock()


def _cache_key(locations: Optional[Sequence[str]], *, debt: bool = False) -> str:
    """P3A.9 — master vs açık borç cache anahtarları."""
    locs = sorted(locations) if locations else sorted(CANONICAL_LOCATION_CODES)
    parts = [f'{code}@{get_finance_location_scope(code)}' for code in locs]
    prefix = 'balances:v3:debt:' if debt else 'balances:v3:master:'
    return prefix + '|'.join(parts)


def cache_invalidate_balances(locations: Optional[Sequence[str]] = None) -> None:
    """İlgili balance cache entry'lerini sil (explicit refresh)."""
    with _CACHE_LOCK:
        _BALANCE_CACHE.pop(_cache_key(locations, debt=False), None)
        _BALANCE_CACHE.pop(_cache_key(locations, debt=True), None)


def cache_invalidate_all() -> None:
    """Tüm balance cache'i temizle."""
    with _CACHE_LOCK:
        _BALANCE_CACHE.clear()


def _cache_get(key: str):
    with _CACHE_LOCK:
        entry = _BALANCE_CACHE.get(key)
    if entry is None:
        return None, False
    fetched_at, data = entry
    if (time.time() - fetched_at) > _CACHE_TTL:
        with _CACHE_LOCK:
            _BALANCE_CACHE.pop(key, None)
        return None, False
    return data, True


def _cache_set(key: str, data) -> None:
    with _CACHE_LOCK:
        _BALANCE_CACHE[key] = (time.time(), data)


# Canonical şirket location mapping (Korgün dbo.Location)
COMPANY_LOCATIONS: Dict[str, Dict[str, str]] = {
    'YN001': {'code': 'YN001', 'label': 'NexGen', 'short': 'NexGen'},
    'SA001': {'code': 'SA001', 'label': 'Şahin Taban', 'short': 'Şahin Taban'},
    'YP001': {'code': 'YP001', 'label': 'Pera AŞ', 'short': 'Pera AŞ'},
}

CANONICAL_LOCATION_CODES: Tuple[str, ...] = tuple(COMPANY_LOCATIONS.keys())

# P3A.8 — consolidated muhasebe kapsamı (şirket UI kodu → kg_fn Location listesi)
# YN001 / YP001: kanıt yok — tek location (değişmedi)
COMPANY_FINANCE_LOCATION_MAP: Dict[str, Tuple[str, ...]] = {
    'SA001': ('SA001', 'SB001', 'SH001', 'SU001', 'SD002'),
}

# Tedarikçi filtresi — bkz. verify_supplier_rule()
SUPPLIER_CKOD_PREFIX = '320.'
DEBT_NET_TOLERANCE = 0.01

# TECH_DEBT (P1.1): Korgün'de 320PR.156 / 320PR.158 gibi noktasız prefix anomalileri
# mevcut; CKod LIKE '320.%' bunları kapsamaz. Business rule genişletme P3+ kararı.


@dataclass
class SupplierRuleVerification:
    """320.* tedarikçi kuralı doğrulama sonucu."""
    muhkod_rule_proven: bool
    muhkod_320_count: int
    muhkod_empty_count: int
    ckod_320_count: int
    purchase_invoice_320_share: float
    purchase_invoice_total: int
    recommended_filter: str
    notes: List[str] = field(default_factory=list)


@dataclass
class SupplierBalanceDTO:
    location: str
    location_label: str
    cari_kod: str
    cari_adi: str
    para_birimi: str
    bakiye: float
    canonical_key: str
    # P3A.2: canlı muhasebe borç/alacak (kg_fn_CariHesToplam)
    borc: float = 0.0
    alacak: float = 0.0
    source: str = 'CariBakiye'  # 'kg_fn' | 'CariBakiye'


def get_finance_location_scope(company_code: str) -> str:
    """UI şirket kodu → kg_fn Location parametresi (consolidated veya tek loc)."""
    code = (company_code or '').strip().upper()
    mapped = COMPANY_FINANCE_LOCATION_MAP.get(code)
    if mapped:
        return ','.join(mapped)
    return code


def _kg_fn_pc(para_cinsi: Optional[str]) -> str:
    """kg_fn @ParaCinsi — TL / US / EU (DefPC yerine satır PB)."""
    raw = (para_cinsi or 'TL').strip().upper()
    if raw in ('TL', 'TRY', 'YTL'):
        return 'TL'
    if raw in ('US', 'USD'):
        return 'US'
    if raw in ('EU', 'EUR'):
        return 'EU'
    return raw


def _normalize_pb(para_cinsi: Optional[str]) -> str:
    raw = (para_cinsi or 'TL').strip().upper()
    if raw in ('TL', 'TRY', 'YTL'):
        return 'TRY'
    if raw in ('US', 'USD'):
        return 'USD'
    if raw in ('EU', 'EUR'):
        return 'EUR'
    return raw


def _canonical_key(location: str, ckod: str) -> str:
    return f'{location}|{ckod}'


def _location_filter_sql(locations: Optional[Sequence[str]]) -> Tuple[str, tuple]:
    locs = list(locations) if locations else list(CANONICAL_LOCATION_CODES)
    locs = [x for x in locs if x in COMPANY_LOCATIONS]
    if not locs:
        locs = list(CANONICAL_LOCATION_CODES)
    placeholders = ','.join(['%s'] * len(locs))
    return f' IN ({placeholders}) ', tuple(locs)


def _parse_location_filter_raw(raw: Optional[str]) -> Optional[List[str]]:
    """Route'dan gelen sirket= parametresini canonical location listesine çevirir."""
    if not raw or raw.strip().lower() in ('', 'all', 'tumu', 'tümü'):
        return None
    code = raw.strip().upper()
    if code in COMPANY_LOCATIONS:
        return [code]
    return None


class KorgunFinanceAdapter:
    """Korgün finans verisi — salt okunur adapter."""

    def verify_supplier_rule(self) -> SupplierRuleVerification:
        """
        MuhKod 320.* kuralını READ-ONLY doğrular.

        Kanıt: MuhKod sütunu fiilen boş/vergi no; tedarikçi ayrımı CKod 320.* ile
        alış faturalarında (fal/hal/dal) %94+ uyum gösterir.
        """
        con = _baglan()
        try:
            cur = con.cursor()
            cur.execute("""
                SELECT
                  SUM(CASE WHEN MuhKod LIKE '320.%' THEN 1 ELSE 0 END) AS muh_320,
                  SUM(CASE WHEN MuhKod IS NULL OR LTRIM(RTRIM(MuhKod)) = '' THEN 1 ELSE 0 END) AS muh_empty,
                  SUM(CASE WHEN CKod LIKE '320.%' THEN 1 ELSE 0 END) AS ckod_320
                FROM Cari_Kart WITH (NOLOCK)
            """)
            row = cur.fetchone()
            muh_320 = int(row[0] or 0)
            muh_empty = int(row[1] or 0)
            ckod_320 = int(row[2] or 0)

            loc_in = ','.join(f"'{x}'" for x in CANONICAL_LOCATION_CODES)
            cur.execute(f"""
                SELECT
                  SUM(CASE WHEN ck.CKod LIKE '320.%' THEN 1 ELSE 0 END) AS n_320,
                  COUNT(*) AS n_total
                FROM Fatura_Kay fk WITH (NOLOCK)
                INNER JOIN Cari_Kart ck WITH (NOLOCK) ON ck.CKod = fk.CariKod
                WHERE fk.FaturaTip IN ('fal','hal','dal')
                  AND fk.Location IN ({loc_in})
                  AND ISNULL(fk.iptal,'') NOT IN ('*','(')
            """)
            prow = cur.fetchone()
            n_320 = int(prow[0] or 0)
            n_total = int(prow[1] or 0)
            share = (n_320 / n_total * 100.0) if n_total else 0.0

            notes = []
            if muh_320 == 0:
                notes.append(
                    'MuhKod 320.* kanıtlanamadı: Cari_Kart.MuhKod alanı boş veya vergi no; '
                    'muhasebe hesap kodu değil.'
                )
            notes.append(
                f'CKod 320.* alış faturalarında {share:.1f}% uyum ({n_320}/{n_total}).'
            )

            return SupplierRuleVerification(
                muhkod_rule_proven=muh_320 > 0,
                muhkod_320_count=muh_320,
                muhkod_empty_count=muh_empty,
                ckod_320_count=ckod_320,
                purchase_invoice_320_share=share,
                purchase_invoice_total=n_total,
                recommended_filter='CKod LIKE 320.%',
                notes=notes,
            )
        finally:
            con.close()

    def _fetch_company_balances(
        self,
        cur,
        company_code: str,
        *,
        debt_filter: bool = False,
    ) -> List[SupplierBalanceDTO]:
        """Tek şirket için kg_fn bakiye listesi.

        debt_filter=False → supplier master (net filtresi yok, Tutar>0 yok)
        debt_filter=True  → yalnız net > 0 (legacy; prefer master + Python filter)
        """
        company_code = company_code.strip().upper()
        if company_code not in COMPANY_LOCATIONS:
            return []

        finance_scope = get_finance_location_scope(company_code)
        is_consolidated = company_code in COMPANY_FINANCE_LOCATION_MAP
        cb_filter = 'AND Tutar > 0' if debt_filter else ''
        net_sql = (
            'AND CAST(ISNULL(ht.Borc, 0) - ISNULL(ht.Alacak, 0) AS FLOAT) > 0'
            if debt_filter else ''
        )

        if is_consolidated:
            cur.execute(f"""
                SELECT
                  %s AS Location,
                  LTRIM(RTRIM(cb.CKod)) AS CKod,
                  LTRIM(RTRIM(ISNULL(ck.CName, ''))) AS CName,
                  LTRIM(RTRIM(ISNULL(cb.ParaCinsi, 'TL'))) AS ParaCinsi,
                  CAST(ISNULL(ht.Borc, 0) AS FLOAT) AS Borc,
                  CAST(ISNULL(ht.Alacak, 0) AS FLOAT) AS Alacak,
                  CAST(ISNULL(ht.Borc, 0) - ISNULL(ht.Alacak, 0) AS FLOAT) AS Net
                FROM (
                  SELECT DISTINCT CKod, ParaCinsi
                  FROM CariBakiye WITH (NOLOCK)
                  WHERE Location = %s AND CKod LIKE '320.%%' {cb_filter}
                ) cb
                INNER JOIN Cari_Kart ck WITH (NOLOCK)
                  ON ck.CKod = cb.CKod AND ck.CKod LIKE '320.%%'
                CROSS APPLY (
                  SELECT Borc, Alacak
                  FROM dbo.kg_fn_CariHesToplam('G', cb.CKod, %s,
                       NULL, NULL, NULL, cb.ParaCinsi,
                       '0', NULL, '', '', '', '')
                ) ht
                WHERE 1=1 {net_sql}
                ORDER BY LTRIM(RTRIM(ISNULL(ck.CName, ''))), cb.ParaCinsi
            """, (company_code, company_code, finance_scope))
        else:
            cur.execute(f"""
                SELECT
                  LTRIM(RTRIM(cb.Location)) AS Location,
                  LTRIM(RTRIM(cb.CKod)) AS CKod,
                  LTRIM(RTRIM(ISNULL(ck.CName, ''))) AS CName,
                  dbo.kg_fn_CariDefPc(cb.CKod) AS DefPC,
                  CAST(ISNULL(ht.Borc, 0) AS FLOAT) AS Borc,
                  CAST(ISNULL(ht.Alacak, 0) AS FLOAT) AS Alacak,
                  CAST(ISNULL(ht.Borc, 0) - ISNULL(ht.Alacak, 0) AS FLOAT) AS Net
                FROM (
                  SELECT DISTINCT CKod, Location
                  FROM CariBakiye WITH (NOLOCK)
                  WHERE Location = %s AND CKod LIKE '320.%%' {cb_filter}
                ) cb
                INNER JOIN Cari_Kart ck WITH (NOLOCK)
                  ON ck.CKod = cb.CKod AND ck.CKod LIKE '320.%%'
                CROSS APPLY (
                  SELECT Borc, Alacak
                  FROM dbo.kg_fn_CariHesToplam('G', cb.CKod, cb.Location,
                       NULL, NULL, NULL, dbo.kg_fn_CariDefPc(cb.CKod),
                       '0', NULL, '', '', '', '')
                ) ht
                {('WHERE CAST(ISNULL(ht.Borc,0)-ISNULL(ht.Alacak,0) AS FLOAT) > 0' if debt_filter else '')}
                ORDER BY LTRIM(RTRIM(ISNULL(ck.CName, ''))), dbo.kg_fn_CariDefPc(cb.CKod)
            """, (company_code,))

        rows = cur.fetchall()
        out: List[SupplierBalanceDTO] = []
        for row in rows:
            if is_consolidated:
                loc, ckod, cname, pc_raw, borc, alacak, net = row
                pc_kg = _kg_fn_pc(pc_raw)
            else:
                loc, ckod, cname, defpc, borc, alacak, net = row
                pc_kg = _kg_fn_pc(defpc)

            loc = (loc or company_code).strip()
            if loc not in COMPANY_LOCATIONS:
                continue
            pb = _normalize_pb(pc_kg)
            out.append(SupplierBalanceDTO(
                location=loc,
                location_label=COMPANY_LOCATIONS[loc]['label'],
                cari_kod=(ckod or '').strip(),
                cari_adi=(cname or '').strip() or (ckod or '').strip(),
                para_birimi=pb,
                bakiye=float(net or 0),
                canonical_key=_canonical_key(loc, (ckod or '').strip()),
                borc=float(borc or 0),
                alacak=float(alacak or 0),
                source='kg_fn',
            ))
        return out

    def fetch_supplier_master_balances(
        self,
        locations: Optional[Sequence[str]] = None,
        force_refresh: bool = False,
    ) -> List[SupplierBalanceDTO]:
        """
        P3A.9 — Tedarikçi master evreni: 320.* cariler, consolidated canonical net.
        Net filtresi YOK — negatif/sıfır cariler dahil.
        Tek set-based kg_fn CROSS APPLY; 45s TTL cache.
        """
        _, loc_params = _location_filter_sql(locations)
        locs_validated = list(loc_params)
        cache_key = _cache_key(locs_validated, debt=False)

        if not force_refresh:
            cached, hit = _cache_get(cache_key)
            if hit:
                return cached

        con = _baglan()
        try:
            cur = con.cursor()
            out: List[SupplierBalanceDTO] = []
            for company_code in locs_validated:
                out.extend(self._fetch_company_balances(cur, company_code, debt_filter=False))
            _cache_set(cache_key, out)
            return out
        finally:
            con.close()

    def _fetch_debt_balances_sql(
        self,
        locations: Optional[Sequence[str]] = None,
        force_refresh: bool = False,
    ) -> List[SupplierBalanceDTO]:
        """P3A.8 açık borç evreni — CariBakiye Tutar>0 + kg_fn net>0 (KPI/Yükümlülükler)."""
        _, loc_params = _location_filter_sql(locations)
        locs_validated = list(loc_params)
        cache_key = _cache_key(locs_validated, debt=True)

        if not force_refresh:
            cached, hit = _cache_get(cache_key)
            if hit:
                return cached

        con = _baglan()
        try:
            cur = con.cursor()
            out: List[SupplierBalanceDTO] = []
            for company_code in locs_validated:
                out.extend(self._fetch_company_balances(cur, company_code, debt_filter=True))
            _cache_set(cache_key, out)
            return out
        finally:
            con.close()

    def fetch_supplier_balances(
        self,
        locations: Optional[Sequence[str]] = None,
        positive_only: bool = True,
        force_refresh: bool = False,
    ) -> List[SupplierBalanceDTO]:
        """
        Açık borç evreni — P3A.8 SQL (Tutar>0 + net>0). Master'dan türetilmez.

        P3A.9: Cariler sekmesi fetch_supplier_master_balances kullanmalı.
        KPI / Yükümlülükler bu metodu positive_only=True ile kullanır.
        """
        if positive_only:
            return self._fetch_debt_balances_sql(
                locations=locations,
                force_refresh=force_refresh,
            )
        return self.fetch_supplier_master_balances(
            locations=locations,
            force_refresh=force_refresh,
        )

    def fetch_open_checks(
        self,
        locations: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Açık çekler — vade bilgisi için P1 read-only (mycek=K)."""
        loc_sql, loc_params = _location_filter_sql(locations)
        con = _baglan()
        try:
            cur = con.cursor()
            sql = f"""
                SELECT
                  LTRIM(RTRIM(c.Location)) AS Location,
                  LTRIM(RTRIM(c.CMKod)) AS CKod,
                  LTRIM(RTRIM(ISNULL(ck.CName, ISNULL(c.Borclu, '')))) AS CName,
                  CONVERT(VARCHAR(10), c.vade, 120) AS Vade,
                  LTRIM(RTRIM(ISNULL(c.ParaCinsi, 'TL'))) AS ParaCinsi,
                  CAST(c.Tutar AS FLOAT) AS Tutar,
                  LTRIM(RTRIM(ISNULL(c.SDurum, ''))) AS SDurum,
                  LTRIM(RTRIM(ISNULL(c.CekNo, ''))) AS CekNo
                FROM cek_Kart c WITH (NOLOCK)
                LEFT JOIN Cari_Kart ck WITH (NOLOCK) ON ck.CKod = c.CMKod
                WHERE c.mycek = 'K'
                  AND c.Location {loc_sql}
                  AND c.CMKod LIKE '320.%%'
                  AND (c.iptal IS NULL OR c.iptal = 0)
                ORDER BY c.vade, c.Tutar DESC
            """
            cur.execute(sql, loc_params)
            cols = [d[0] for d in cur.description]
            result = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                loc = (d.get('Location') or '').strip()
                d['location_label'] = COMPANY_LOCATIONS.get(loc, {}).get('label', loc)
                d['para_birimi'] = _normalize_pb(d.get('ParaCinsi'))
                d['tutar'] = float(d.get('Tutar') or 0)
                result.append(d)
            return result
        finally:
            con.close()

    def count_suppliers_by_location(
        self,
        locations: Optional[Sequence[str]] = None,
        balances: Optional[List[SupplierBalanceDTO]] = None,
    ) -> Dict[str, int]:
        """
        Pozitif bakiyeli benzersiz tedarikçi sayısı (Location + CKod).

        P3A.3: balances parametresi verilirse tekrar fetch yapılmaz (duplicate CROSS APPLY önlenir).
        """
        if balances is None:
            balances = self.fetch_supplier_balances(locations=locations, positive_only=True)
        counts: Dict[str, set] = {code: set() for code in CANONICAL_LOCATION_CODES}
        for b in balances:
            counts.setdefault(b.location, set()).add(b.cari_kod)
        return {loc: len(s) for loc, s in counts.items()}

    def supplier_canonical_exists(self, location: str, cari_kod: str) -> bool:
        """Location + CKod tedarikçi Korgün'de var mı (320.*, READ-ONLY)."""
        loc = (location or '').strip().upper()
        ck = (cari_kod or '').strip()
        if loc not in COMPANY_LOCATIONS or not ck:
            return False
        con = _baglan()
        try:
            cur = con.cursor()
            cur.execute(
                """
                SELECT TOP 1 1
                FROM CariBakiye cb WITH (NOLOCK)
                INNER JOIN Cari_Kart ck WITH (NOLOCK)
                  ON ck.CKod = cb.CKod AND ck.CKod LIKE '320.%%'
                WHERE cb.Location = %s AND cb.CKod = %s
                """,
                (loc, ck),
            )
            return cur.fetchone() is not None
        finally:
            con.close()

    def get_supplier_info(self, location: str, cari_kod: str) -> Optional[Dict[str, Any]]:
        """Tek tedarikçi adı — canonical doğrulama sonrası snapshot için."""
        loc = (location or '').strip().upper()
        ck = (cari_kod or '').strip()
        con = _baglan()
        try:
            cur = con.cursor()
            cur.execute(
                """
                SELECT TOP 1
                  LTRIM(RTRIM(cb.Location)) AS Location,
                  LTRIM(RTRIM(cb.CKod)) AS CKod,
                  LTRIM(RTRIM(ISNULL(ck.CName, ''))) AS CName
                FROM CariBakiye cb WITH (NOLOCK)
                INNER JOIN Cari_Kart ck WITH (NOLOCK)
                  ON ck.CKod = cb.CKod AND ck.CKod LIKE '320.%%'
                WHERE cb.Location = %s AND cb.CKod = %s
                """,
                (loc, ck),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                'location': (row[0] or '').strip(),
                'cari_kod': (row[1] or '').strip(),
                'cari_adi': (row[2] or '').strip() or ck,
            }
        finally:
            con.close()

    def fetch_cari_live_balance(self, location: str, cari_kod: str) -> Dict[str, Any]:
        """
        Tek cari için canlı muhasebe bakiyesi — kg_fn_CariHesToplam.
        P3A.8: SA001 consolidated scope + CariBakiye ParaCinsi.
        INSERT/UPDATE/DELETE YOK.
        """
        loc = (location or '').strip().upper()
        ck = (cari_kod or '').strip()
        finance_scope = get_finance_location_scope(loc)
        con = _baglan()
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT TOP 1 LTRIM(RTRIM(ISNULL(CName,''))) FROM Cari_Kart WHERE CKod=%s",
                (ck,),
            )
            row = cur.fetchone()
            cname = (row[0] or ck) if row else ck

            if loc in COMPANY_FINANCE_LOCATION_MAP:
                cur.execute(
                    """
                    SELECT TOP 1 LTRIM(RTRIM(ISNULL(ParaCinsi, 'TL')))
                    FROM CariBakiye WITH (NOLOCK)
                    WHERE CKod = %s AND Location = %s
                    ORDER BY CASE WHEN Tutar > 0 THEN 0 ELSE 1 END, ABS(Tutar) DESC
                    """,
                    (ck, loc),
                )
                pc_row = cur.fetchone()
                pc = _kg_fn_pc((pc_row[0] if pc_row else 'TL'))
            else:
                cur.execute("SELECT dbo.kg_fn_CariDefPc(%s)", (ck,))
                row2 = cur.fetchone()
                pc = _kg_fn_pc((row2[0] if row2 else 'TL'))

            cur.execute(
                """
                SELECT CAST(ISNULL(Borc,0) AS FLOAT), CAST(ISNULL(Alacak,0) AS FLOAT)
                FROM dbo.kg_fn_CariHesToplam('G', %s, %s,
                     NULL, NULL, NULL, %s, '0', NULL, '', '', '', '')
                """,
                (ck, finance_scope, pc),
            )
            hrow = cur.fetchone()
            borc = float(hrow[0] or 0) if hrow else 0.0
            alacak = float(hrow[1] or 0) if hrow else 0.0
            net = borc - alacak
            pb = _normalize_pb(pc)
            return {
                'location': loc,
                'location_label': COMPANY_LOCATIONS.get(loc, {}).get('label', loc),
                'cari_kod': ck,
                'cari_adi': cname,
                'para_birimi': pb,
                'borc': borc,
                'alacak': alacak,
                'net': net,
                'finance_scope': finance_scope,
                'source': 'kg_fn',
            }
        finally:
            con.close()

    def fetch_cari_hareketleri(self, location: str, cari_kod: str) -> Dict[str, Any]:
        """
        Cari hareketleri — READ-ONLY, kronolojik liste.

        Kaynaklar (P3A.1 forensic):
          - Fatura_Kay / Fatura_Har  (hal/fal/dal alış)
          - C_Fis_Kay / C_Fis_Har   (kasa/nakit/dekont)
          - Banka_Kay / Banka_Har   (havale/banka)
          - cek_Kart (mycek=K)      — verilen çekler ayrı bölüm

        Hareket parity: toplam borç − alacak vs kg_fn net raporlanır.
        INSERT/UPDATE/DELETE YOK.
        """
        loc = (location or '').strip().upper()
        ck = (cari_kod or '').strip()
        if loc not in COMPANY_LOCATIONS or not ck:
            return {'ok': False, 'error': 'Geçersiz lokasyon veya cari kodu.', 'hareketler': [], 'cekler': []}

        con = _baglan()
        try:
            cur = con.cursor()
            hareketler: List[Dict[str, Any]] = []

            # 1) Fatura_Kay — alış faturaları
            cur.execute("""
                SELECT
                  CONVERT(VARCHAR(10), fk.FatTar, 120) AS tarih,
                  fk.FaturaTip AS tip,
                  fk.FaturaNo AS belge_no,
                  ISNULL(fk.notu, '') AS aciklama,
                  CONVERT(VARCHAR(10), fk.Vade, 120) AS vade,
                  fk.ParaCinsi AS pb
                FROM Fatura_Kay fk WITH (NOLOCK)
                WHERE fk.CariKod = %s AND fk.Location = %s
                  AND fk.FaturaTip IN ('fal','hal','dal','hai','hsa')
                  AND ISNULL(fk.iptal,'') NOT IN ('*','(')
                ORDER BY fk.FatTar DESC
            """, (ck, loc))
            cols = [d[0] for d in cur.description]
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                tip_map = {
                    'hal': 'Alış Fat.', 'fal': 'Alış Fat.',
                    'dal': 'Döviz Alış', 'hai': 'İade Fat.',
                    'hsa': 'Serbest Alış',
                }
                pb = _normalize_pb(d.get('pb'))
                hareketler.append({
                    'tarih': d.get('tarih') or '',
                    'tur': tip_map.get(d.get('tip', ''), d.get('tip', 'Fatura')),
                    'belge_no': str(d.get('belge_no') or ''),
                    'aciklama': d.get('aciklama') or '',
                    'vade': d.get('vade') or '',
                    'borc': None,   # fatura tutarı FaturaTutar'dan; burada gösterim için None
                    'alacak': None,
                    'pb': pb,
                    'kaynak': 'Fatura_Kay',
                })

            # 2) C_Fis_Kay / C_Fis_Har — kasa/nakit/dekont
            cur.execute("""
                SELECT
                  CONVERT(VARCHAR(10), k.FisTar, 120) AS tarih,
                  k.FisTip AS tip,
                  k.BelgeNo AS belge_no,
                  ISNULL(h.tanim, '') AS aciklama,
                  CONVERT(VARCHAR(10), h.Vade, 120) AS vade,
                  CAST(h.Tutar AS FLOAT) AS tutar,
                  h.ParaCinsi AS pb,
                  h.MM AS mm
                FROM C_Fis_Kay k WITH (NOLOCK)
                JOIN C_Fis_Har h WITH (NOLOCK) ON h.FisNo = k.FisNo
                WHERE k.CariKod = %s AND k.Location = %s
                  AND ISNULL(k.iptal,'') NOT IN ('*','(')
                ORDER BY k.FisTar DESC
            """, (ck, loc))
            cols2 = [d[0] for d in cur.description]
            for row in cur.fetchall():
                d = dict(zip(cols2, row))
                tip = d.get('tip', '')
                mm = (d.get('mm') or '').strip()
                tutar = float(d.get('tutar') or 0)
                pb = _normalize_pb(d.get('pb'))
                # MM: B=borç, A=alacak göstergesi
                borc_v = tutar if mm == 'B' else None
                alacak_v = tutar if mm == 'A' else None
                hareketler.append({
                    'tarih': d.get('tarih') or '',
                    'tur': f"Fiş/{tip}",
                    'belge_no': str(d.get('belge_no') or ''),
                    'aciklama': d.get('aciklama') or '',
                    'vade': d.get('vade') or '',
                    'borc': borc_v,
                    'alacak': alacak_v,
                    'pb': pb,
                    'kaynak': 'C_Fis',
                })

            # 3) Banka_Kay / Banka_Har
            cur.execute("""
                SELECT
                  CONVERT(VARCHAR(10), a.Tarih, 120) AS tarih,
                  a.FisTip AS tip,
                  a.EvrakNo AS belge_no,
                  ISNULL(b.Tanim, '') AS aciklama,
                  CAST(b.Tutar AS FLOAT) AS tutar,
                  b.ParaCinsi AS pb,
                  b.MM AS mm
                FROM Banka_Kay a WITH (NOLOCK)
                JOIN Banka_Har b WITH (NOLOCK) ON b.FisNo = a.FisNo
                WHERE a.cmbkod = %s AND a.Location = %s AND a.cmb = 'C'
                  AND ISNULL(a.iptal,'') NOT IN ('*','(')
                ORDER BY a.Tarih DESC
            """, (ck, loc))
            cols3 = [d[0] for d in cur.description]
            for row in cur.fetchall():
                d = dict(zip(cols3, row))
                tip = d.get('tip', '')
                mm = (d.get('mm') or '').strip()
                tutar = float(d.get('tutar') or 0)
                pb = _normalize_pb(d.get('pb'))
                # MM: B=borç tarafı, A=alacak tarafı
                borc_v = tutar if mm == 'B' else None
                alacak_v = tutar if mm == 'A' else None
                hareketler.append({
                    'tarih': d.get('tarih') or '',
                    'tur': 'Havale/Banka',
                    'belge_no': str(d.get('belge_no') or ''),
                    'aciklama': d.get('aciklama') or '',
                    'vade': '',
                    'borc': borc_v,
                    'alacak': alacak_v,
                    'pb': pb,
                    'kaynak': 'Banka',
                })

            # Kronolojik sırala (tarih desc)
            hareketler.sort(key=lambda x: x.get('tarih') or '', reverse=True)

            # 4) Verilen çekler — ayrı liste
            cur.execute("""
                SELECT
                  c.cekinx,
                  CONVERT(VARCHAR(10), c.Tarih, 120) AS cektar,
                  CONVERT(VARCHAR(10), c.vade, 120) AS vade,
                  CAST(c.Tutar AS FLOAT) AS tutar,
                  c.ParaCinsi AS pb,
                  ISNULL(c.SDurum,'') AS sdurum,
                  ISNULL(c.CekNo,'') AS cekno,
                  ISNULL(c.CekTip,'') AS cektip,
                  ISNULL(c.Banka,'') AS banka
                FROM cek_Kart c WITH (NOLOCK)
                WHERE c.CMKod = %s AND c.Location = %s
                  AND c.mycek = 'K'
                  AND (c.iptal IS NULL OR c.iptal = 0)
                ORDER BY c.vade
            """, (ck, loc))
            cols4 = [d[0] for d in cur.description]
            cekler = []
            for row in cur.fetchall():
                d = dict(zip(cols4, row))
                sdurum_map = {
                    'A': 'Aktif / Portföyde', 'BO': 'Bankaya verildi',
                    '4': 'Tahsil edildi', '3': 'Protestolu', 'KO': 'Kısmi ödeme',
                }
                pb = _normalize_pb(d.get('pb'))
                cekler.append({
                    'cekinx': d.get('cekinx'),
                    'cektar': d.get('cektar') or '',
                    'vade': d.get('vade') or '',
                    'tutar': float(d.get('tutar') or 0),
                    'pb': pb,
                    'sdurum': d.get('sdurum'),
                    'sdurum_label': sdurum_map.get(d.get('sdurum', ''), d.get('sdurum', '')),
                    'cekno': d.get('cekno') or '',
                    'cektip': d.get('cektip') or '',
                    'banka': d.get('banka') or '',
                })

            # Parity: hareketler toplamı vs kg_fn
            har_borc = sum(r['borc'] for r in hareketler if r.get('borc') is not None)
            har_alacak = sum(r['alacak'] for r in hareketler if r.get('alacak') is not None)
            har_net = har_borc - har_alacak

            # kg_fn canlı — P3A.8 consolidated scope + satır ParaCinsi
            finance_scope = get_finance_location_scope(loc)
            if loc in COMPANY_FINANCE_LOCATION_MAP:
                cur.execute(
                    """
                    SELECT TOP 1 LTRIM(RTRIM(ISNULL(ParaCinsi, 'TL')))
                    FROM CariBakiye WITH (NOLOCK)
                    WHERE CKod = %s AND Location = %s
                    ORDER BY CASE WHEN Tutar > 0 THEN 0 ELSE 1 END, ABS(Tutar) DESC
                    """,
                    (ck, loc),
                )
                pc_row = cur.fetchone()
                fn_pc = _kg_fn_pc((pc_row[0] if pc_row else 'TL'))
            else:
                cur.execute("SELECT dbo.kg_fn_CariDefPc(%s)", (ck,))
                defpc_row = cur.fetchone()
                fn_pc = _kg_fn_pc((defpc_row[0] if defpc_row else 'TL'))
            cur.execute("""
                SELECT CAST(ISNULL(Borc,0) AS FLOAT), CAST(ISNULL(Alacak,0) AS FLOAT)
                FROM dbo.kg_fn_CariHesToplam('G', %s, %s, NULL, NULL, NULL, %s, '0', NULL, '', '', '', '')
            """, (ck, finance_scope, fn_pc))
            fn_row = cur.fetchone()
            fn_borc = float(fn_row[0] or 0) if fn_row else 0.0
            fn_alacak = float(fn_row[1] or 0) if fn_row else 0.0
            fn_net = fn_borc - fn_alacak

            parity_delta = round(fn_net - har_net, 2)
            parity_ok = abs(parity_delta) < 1.0

            return {
                'ok': True,
                'location': loc,
                'location_label': COMPANY_LOCATIONS.get(loc, {}).get('label', loc),
                'cari_kod': ck,
                'cari_adi': '',  # doldurulacak üstte
                'para_birimi': _normalize_pb(fn_pc),
                'finance_scope': finance_scope,
                'fn_borc': fn_borc,
                'fn_alacak': fn_alacak,
                'fn_net': fn_net,
                'har_borc': har_borc,
                'har_alacak': har_alacak,
                'har_net': har_net,
                'parity_ok': parity_ok,
                'parity_delta': parity_delta,
                'parity_note': (
                    'Hareket dökümü canonical neti tam açıklamıyor.'
                    if not parity_ok else 'Hareket parity OK.'
                ),
                'hareketler': hareketler,
                'cekler': cekler,
            }
        finally:
            con.close()
