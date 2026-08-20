# -*- coding: utf-8 -*-
"""
KorgunFinanceAdapter — READ-ONLY Korgün finans verisi.

Akış: Korgün → KorgunFinanceAdapter → Finance DTO → CPS API → Ödeme Planı UI

INSERT / UPDATE / DELETE YOK — yalnızca SELECT.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from modules.common.korgun import _baglan
except ImportError:
    from app.modules.common.korgun import _baglan


# Canonical şirket location mapping (Korgün dbo.Location)
COMPANY_LOCATIONS: Dict[str, Dict[str, str]] = {
    'YN001': {'code': 'YN001', 'label': 'NexGen', 'short': 'NexGen'},
    'SA001': {'code': 'SA001', 'label': 'Şahin Taban', 'short': 'Şahin Taban'},
    'YP001': {'code': 'YP001', 'label': 'Pera AŞ', 'short': 'Pera AŞ'},
}

CANONICAL_LOCATION_CODES: Tuple[str, ...] = tuple(COMPANY_LOCATIONS.keys())

# Tedarikçi filtresi — bkz. verify_supplier_rule()
SUPPLIER_CKOD_PREFIX = '320.'

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

    def fetch_supplier_balances(
        self,
        locations: Optional[Sequence[str]] = None,
        positive_only: bool = True,
    ) -> List[SupplierBalanceDTO]:
        """
        Tedarikçi cari bakiyeleri — CariBakiye + Cari_Kart (CKod 320.*).

        Anahtar: Location + CKod + ParaCinsi
        """
        loc_sql, loc_params = _location_filter_sql(locations)
        con = _baglan()
        try:
            cur = con.cursor()
            sql = f"""
                SELECT
                  LTRIM(RTRIM(cb.Location)) AS Location,
                  LTRIM(RTRIM(cb.CKod)) AS CKod,
                  LTRIM(RTRIM(ISNULL(ck.CName, ''))) AS CName,
                  LTRIM(RTRIM(ISNULL(cb.ParaCinsi, 'TL'))) AS ParaCinsi,
                  CAST(cb.Tutar AS FLOAT) AS Tutar
                FROM CariBakiye cb WITH (NOLOCK)
                INNER JOIN Cari_Kart ck WITH (NOLOCK)
                  ON ck.CKod = cb.CKod
                 AND ck.CKod LIKE '320.%%'
                WHERE cb.Location {loc_sql}
            """
            if positive_only:
                sql += ' AND cb.Tutar > 0 '
            sql += ' ORDER BY cb.Location, ck.CName, cb.ParaCinsi '
            cur.execute(sql, loc_params)
            rows = cur.fetchall()
            out: List[SupplierBalanceDTO] = []
            for loc, ckod, cname, pb, tutar in rows:
                loc = (loc or '').strip()
                if loc not in COMPANY_LOCATIONS:
                    continue
                out.append(SupplierBalanceDTO(
                    location=loc,
                    location_label=COMPANY_LOCATIONS[loc]['label'],
                    cari_kod=(ckod or '').strip(),
                    cari_adi=(cname or '').strip() or (ckod or '').strip(),
                    para_birimi=_normalize_pb(pb),
                    bakiye=float(tutar or 0),
                    canonical_key=_canonical_key(loc, (ckod or '').strip()),
                ))
            return out
        finally:
            con.close()

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
    ) -> Dict[str, int]:
        """Pozitif bakiyeli benzersiz tedarikçi sayısı (Location + CKod)."""
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
