# -*- coding: utf-8 -*-
"""
P1.2 — Ödeme Karar Masası read-model (Korgün READ-ONLY).

Layer 2 batch enrichment:
  - last_payment_map  → Banka FisTip=1 + C_Fis NO/HF (borç tarafı, çek DEĞİL)
  - last_cek_map      → P0-aligned verilen çek (CekTip=F + Cek_Har HarTip=0)
  - last_purchase_map → Fatura_Kay + kg_ifn_FaturaTutar (alış yönü)

890 cari × query YASAK — en fazla 3 set-based Korgün sorgusu + Python join.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

try:
    from modules.common.korgun import _baglan
except ImportError:
    from app.modules.common.korgun import _baglan

try:
    from modules.finans.services.korgun_finance_adapter import (
        CANONICAL_LOCATION_CODES,
        COMPANY_FINANCE_LOCATION_MAP,
        COMPANY_LOCATIONS,
        DEBT_NET_TOLERANCE,
        SupplierBalanceDTO,
        _normalize_pb,
    )
except ImportError:
    from app.modules.finans.services.korgun_finance_adapter import (
        CANONICAL_LOCATION_CODES,
        COMPANY_FINANCE_LOCATION_MAP,
        COMPANY_LOCATIONS,
        DEBT_NET_TOLERANCE,
        SupplierBalanceDTO,
        _normalize_pb,
    )

try:
    from modules.finans.services.odeme_plani_ops_service import (
        format_son_gorusme,
        format_son_odeme_sozu,
    )
except ImportError:
    from app.modules.finans.services.odeme_plani_ops_service import (
        format_son_gorusme,
        format_son_odeme_sozu,
    )

try:
    from modules.finans.services.odeme_plani_enrichment_service import build_row_enrichment
except ImportError:
    from app.modules.finans.services.odeme_plani_enrichment_service import build_row_enrichment

# Tüm kg_fn fiziksel location'lar (batch IN listesi)
ALL_PHYSICAL_LOCATIONS: Tuple[str, ...] = tuple(
    sorted({
        loc
        for scope in (
            tuple(COMPANY_FINANCE_LOCATION_MAP.values())
            + tuple((code,) for code in CANONICAL_LOCATION_CODES)
        )
        for loc in scope
    })
)

_ENRICH_CACHE: Dict[str, tuple] = {}
_ENRICH_TTL = 60
_ENRICH_LOCK = threading.Lock()

CariViewMode = Literal['daily', 'active', 'zero']


@dataclass
class LastPaymentDTO:
    cari_kod: str
    tutar: float
    tarih: str
    kaynak: str
    pb: str


@dataclass
class LastCekDTO:
    cari_kod: str
    tutar: float
    verilis: str
    vade: str
    cek_no: str
    pb: str


@dataclass
class LastPurchaseDTO:
    cari_kod: str
    tutar: float
    tarih: str
    belge: str
    tip: str
    pb: str


def company_physical_locations(locations: Optional[Sequence[str]] = None) -> Tuple[str, ...]:
    """Seçili şirket(ler)in fiziksel location scope'u — ALL_PHYSICAL_LOCATIONS yerine."""
    ui_locs = list(locations) if locations else list(CANONICAL_LOCATION_CODES)
    physical: set = set()
    for code in ui_locs:
        if code not in COMPANY_LOCATIONS:
            continue
        mapped = COMPANY_FINANCE_LOCATION_MAP.get(code)
        if mapped:
            for loc in mapped:
                physical.add(loc)
        else:
            physical.add(code)
    return tuple(sorted(physical))


def _in_clause_locs(locations: Optional[Sequence[str]] = None) -> Tuple[str, tuple]:
    locs = company_physical_locations(locations)
    ph = ','.join(['%s'] * len(locs))
    return ph, locs


def _enrich_cache_key(
    locations: Optional[Sequence[str]] = None,
    cari_kods: Optional[Sequence[str]] = None,
) -> str:
    loc_part = ','.join(company_physical_locations(locations))
    if cari_kods:
        ck = ','.join(sorted(set(cari_kods)))
        return f'enrich:v2:{loc_part}:{hash(ck) & 0xFFFFFFFF:x}:{len(cari_kods)}'
    return f'enrich:v2:{loc_part}:all'


def _cache_get_enrich(key: str) -> Optional[Dict[str, Any]]:
    with _ENRICH_LOCK:
        entry = _ENRICH_CACHE.get(key)
    if not entry:
        return None
    fetched_at, data = entry
    if (time.time() - fetched_at) > _ENRICH_TTL:
        with _ENRICH_LOCK:
            _ENRICH_CACHE.pop(key, None)
        return None
    return data


def _cache_set_enrich(key: str, data: Dict[str, Any]) -> None:
    with _ENRICH_LOCK:
        _ENRICH_CACHE[key] = (time.time(), data)


def _cari_pb_subquery(ck_expr: str, loc_expr: str) -> str:
    """P0-aligned cari transaction PB — BankaTutar tek satır filtresi."""
    return f"""(
      SELECT TOP 1 LTRIM(RTRIM(ISNULL(ParaCinsi, 'TL')))
      FROM CariBakiye cb WITH (NOLOCK)
      WHERE cb.CKod = {ck_expr} AND cb.Location = {loc_expr}
      ORDER BY CASE WHEN Tutar > 0 THEN 0 ELSE 1 END, ABS(Tutar) DESC
    )"""


def _banka_tutar_join_clause(ck_expr: str, loc_expr: str, har_pb: str = 'b.ParaCinsi') -> str:
    """BankaTutar JOIN — yalnız işlem PB satırı (kur karşılığı satırları hariç)."""
    pb = _cari_pb_subquery(ck_expr, loc_expr)
    return (
        f"ON t.FisNo = a.FisNo AND t.FisHarinx = b.FisHarinx "
        f"AND t.ParaCinsi = ISNULL({pb}, {har_pb}) AND t.LineType = 'S'"
    )


def _verilen_cek_union_sql(
    ck_param: str,
    loc_in_clause: str,
    *,
    select_extra: str = '',
    date_field_verilis: str = 'verilis',
) -> str:
    """P0 ledger ile aynı verilen çek kaynakları — tek cari UNION ALL."""
    return f"""
    SELECT
      {date_field_verilis} AS verilis,
      vade,
      amt AS tutar,
      cekno,
      pb
      {select_extra}
    FROM (
      SELECT
        a.Tarih AS verilis,
        a.vade AS vade,
        CAST(a.Tutar AS FLOAT) AS amt,
        LTRIM(RTRIM(ISNULL(a.CekNo, ''))) AS cekno,
        LTRIM(RTRIM(ISNULL(a.ParaCinsi, 'TL'))) AS pb
      FROM cek_Kart a WITH (NOLOCK)
      WHERE a.CekTip = 'F' AND a.CMKod = {ck_param} AND a.CM = 'C'
        AND (a.iptal IS NULL OR a.iptal = 0)
        AND a.Location {loc_in_clause}

      UNION ALL

      SELECT
        b.Tarih AS verilis,
        a.vade AS vade,
        CAST(a.Tutar AS FLOAT) AS amt,
        LTRIM(RTRIM(ISNULL(a.CekNo, ''))) AS cekno,
        LTRIM(RTRIM(ISNULL(a.ParaCinsi, 'TL'))) AS pb
      FROM Cek_Har b WITH (NOLOCK)
      JOIN cek_Kart a WITH (NOLOCK) ON a.Cekinx = b.Cekinx
      WHERE b.HarTip = '0' AND b.cmb = 'C' AND b.cmb_Kod = {ck_param}
        AND a.CekTip IN ('M', 'MX') AND a.mycek = 'K'
        AND (a.iptal IS NULL OR a.iptal = 0)
        AND a.Location {loc_in_clause}
    ) vc
    """


def _days_ago(iso_date: Optional[str], today: date) -> Optional[int]:
    if not iso_date:
        return None
    try:
        d = datetime.strptime(iso_date[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None
    return (today - d).days


def _days_until(iso_date: Optional[str], today: date) -> Optional[int]:
    if not iso_date:
        return None
    try:
        d = datetime.strptime(iso_date[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None
    return (d - today).days


def _vade_suresi_label(verilis: Optional[str], vade: Optional[str]) -> str:
    """Vade süresi label: '5 ay 11 gün'. Hardcode yok, date arithmetic."""
    if not verilis or not vade:
        return ''
    try:
        d0 = datetime.strptime(verilis[:10], '%Y-%m-%d').date()
        d1 = datetime.strptime(vade[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return ''
    delta = d1 - d0
    if delta.days <= 0:
        return ''
    months = delta.days // 30
    remaining_days = delta.days % 30
    if months > 0 and remaining_days > 0:
        return f'{months} ay {remaining_days} gün'
    if months > 0:
        return f'{months} ay'
    return f'{delta.days} gün'


def _vade_suresi_short(verilis: Optional[str], vade: Optional[str]) -> str:
    """~N ay compact format for main list cell."""
    if not verilis or not vade:
        return ''
    try:
        d0 = datetime.strptime(verilis[:10], '%Y-%m-%d').date()
        d1 = datetime.strptime(vade[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return ''
    delta = d1 - d0
    if delta.days <= 0:
        return ''
    months = round(delta.days / 30.44)
    if months >= 1:
        return f'~{months} ay'
    return f'~{delta.days} gün'


def _kaynak_type_label(kaynak: str) -> str:
    """Canonical kaynak → display type: BANKA, NAKİT, DEKONT, ÇEK."""
    k = (kaynak or '').upper()
    if 'BANKA' in k:
        return 'Banka'
    if 'DEKONT' in k or 'C_FIS' in k or 'CFIS' in k or 'NO' in k or 'HF' in k or k == 'BD':
        return 'Dekont'
    return kaynak or ''


# P1.3 FAZ5 — Son ödeme evreni: Banka + C_Fis NO/HF (Bolum K) + BD borç dekontu (Bolum C)
_PAYMENT_DEKONT_UNION = """
              UNION ALL

              SELECT
                LTRIM(RTRIM(h.cbpg)) AS ck,
                k.FisTar AS dt,
                CAST(ISNULL(t.NetTutar, 0) AS FLOAT) AS amt,
                LTRIM(RTRIM(ISNULL(t.ParaCinsi, h.ParaCinsi))) AS pb,
                'Dekont' AS kaynak
              FROM C_Fis_Kay k WITH (NOLOCK)
              JOIN C_Fis_Har h WITH (NOLOCK) ON h.FisNo = k.FisNo
              LEFT JOIN CFisTutar t WITH (NOLOCK)
                ON t.FisNo = h.FisNo AND t.FisHarinx = h.Fisinx AND t.ParaCinsi = h.ParaCinsi
              WHERE h.cbpg LIKE '320.%%'
                AND k.Bolum = 'C'
                AND k.FisTip = 'BD'
                AND ISNULL(k.iptal, '') NOT IN ('*', '(')
                AND k.Location IN ({ph})
                AND ISNULL(t.NetTutar, 0) > 0.001
"""


_PRESERVE_CARI_TOKENS = frozenset({
    'A.Ş.', 'A.S.', 'LTD.', 'LTD', 'ŞTİ.', 'ŞTI.', 'TİC.', 'TIC.', 'SAN.',
    'PVC', 'EVA', 'DBS', 'NX', 'AŞ', 'AS',
})


def _tr_lower_char(c: str) -> str:
    return {'İ': 'i', 'I': 'ı', 'Ş': 'ş', 'Ğ': 'ğ', 'Ü': 'ü', 'Ö': 'ö', 'Ç': 'ç'}.get(c, c.lower())


def _tr_title_word(word: str) -> str:
    if not word:
        return word
    if len(word) == 1:
        return word.upper()
    out = [word[0].upper() if word[0].islower() else word[0]]
    for ch in word[1:]:
        out.append(_tr_lower_char(ch) if ch.isupper() else ch)
    return ''.join(out)


def normalize_cari_display_name(raw: str) -> str:
    """Presentation-only: ALL CAPS Korgün adını okunabilir başlığa çevirir."""
    s = (raw or '').strip()
    if not s:
        return s
    letters = [c for c in s if c.isalpha()]
    if not letters or not all(c.isupper() or c in 'İI' for c in letters):
        return s
    out: List[str] = []
    for part in s.split():
        up = part.upper().replace('İ', 'I')
        preserved = None
        for tok in _PRESERVE_CARI_TOKENS:
            if up == tok.upper().replace('İ', 'I'):
                preserved = tok
                break
        if preserved:
            out.append(preserved)
        elif len(part) <= 3 and part.isupper():
            out.append(part)
        else:
            out.append(_tr_title_word(part))
    return ' '.join(out)


def _fmt_money(amount: Optional[float], pb: str = 'TRY') -> str:
    if amount is None:
        return '—'
    sym = {'TRY': '₺', 'USD': '$', 'EUR': '€'}.get(pb, pb + ' ')
    txt = f'{amount:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return f'{sym}{txt}'


def _net_is_zero(net: float) -> bool:
    return Decimal(str(net)) == Decimal('0')


def _bakiye_durumu(net: float) -> Tuple[str, str]:
    """P1.2B — 320 tedarikçi: net>0 alacaklıyız, net<0 açık borç."""
    if net > DEBT_NET_TOLERANCE:
        return 'Alacaklıyız', 'op-st-credit'
    if net < -DEBT_NET_TOLERANCE:
        return 'Açık Borç', 'op-st-open'
    return 'Bakiye Yok', 'op-st-neutral'


def _karar_from_net(net: float) -> Tuple[str, str, str, str]:
    """Güvenli karar badge — gecikme/vade tahmini YOK (P1.2B canonical)."""
    if net > DEBT_NET_TOLERANCE:
        return 'Alacaklıyız', 'op-st-credit', 'Alacaklıyız', 'Ödeme yapma'
    if net < -DEBT_NET_TOLERANCE:
        return 'Açık Borç', 'op-st-open', 'Açık Borç', 'Vade tanımlı değil'
    return 'Bakiye Yok', 'op-st-neutral', 'Bakiye Yok', 'Ödeme gerekmez'


def _display_bakiye(net: float) -> float:
    """UI tutarı — işaret çözümü kullanıcıya bırakılmaz."""
    if _net_is_zero(net):
        return 0.0
    return abs(net)


def fetch_last_payment_map(
    locations: Optional[Sequence[str]] = None,
    force_refresh: bool = False,
) -> Dict[str, LastPaymentDTO]:
    """Batch — son gerçek ödeme (Banka FisTip=1 + C_Fis NO/HF, tutar>0).

    P1.2E: BankaTutar yalnız cari işlem PB satırı — kur karşılığı duplicate yok.
    """
    ph, locs = _in_clause_locs(locations)
    banka_join = _banka_tutar_join_clause('a.cmbkod', 'a.Location')
    con = _baglan()
    try:
        cur = con.cursor()
        cur.execute(
            f"""
            WITH payments AS (
              SELECT
                LTRIM(RTRIM(a.cmbkod)) AS ck,
                a.Tarih AS dt,
                CAST(ISNULL(t.Tutar, 0) AS FLOAT) AS amt,
                LTRIM(RTRIM(ISNULL(t.ParaCinsi, b.ParaCinsi))) AS pb,
                'Banka' AS kaynak
              FROM Banka_Kay a WITH (NOLOCK)
              JOIN Banka_Har b WITH (NOLOCK) ON b.FisNo = a.FisNo
              LEFT JOIN BankaTutar t WITH (NOLOCK)
                {banka_join}
              WHERE a.cmb = 'C'
                AND a.cmbkod LIKE '320.%%'
                AND a.FisTip = '1'
                AND a.FisTur IN ('1', '2')
                AND ISNULL(a.iptal, '') NOT IN ('*', '(')
                AND a.Location IN ({ph})
                AND ISNULL(t.Tutar, 0) > 0.001

              UNION ALL

              SELECT
                LTRIM(RTRIM(h.cbpg)) AS ck,
                k.FisTar AS dt,
                CAST(ISNULL(t.NetTutar, 0) AS FLOAT) AS amt,
                LTRIM(RTRIM(ISNULL(t.ParaCinsi, h.ParaCinsi))) AS pb,
                'C_Fis' AS kaynak
              FROM C_Fis_Kay k WITH (NOLOCK)
              JOIN C_Fis_Har h WITH (NOLOCK) ON h.FisNo = k.FisNo
              LEFT JOIN CFisTutar t WITH (NOLOCK)
                ON t.FisNo = h.FisNo AND t.FisHarinx = h.Fisinx AND t.ParaCinsi = h.ParaCinsi
              WHERE h.cbpg LIKE '320.%%'
                AND k.Bolum = 'K'
                AND k.FisTip IN ('NO', 'HF')
                AND ISNULL(k.iptal, '') NOT IN ('*', '(')
                AND k.Location IN ({ph})
                AND ISNULL(t.NetTutar, 0) > 0.001
            {_PAYMENT_DEKONT_UNION.format(ph=ph)}
            ),
            ranked AS (
              SELECT ck, dt, amt, pb, kaynak,
                ROW_NUMBER() OVER (PARTITION BY ck ORDER BY dt DESC, amt DESC) AS rn
              FROM payments
            )
            SELECT
              ck,
              CONVERT(VARCHAR(10), dt, 120) AS odeme_tarihi,
              amt,
              pb,
              kaynak
            FROM ranked
            WHERE rn = 1
            """,
            (*locs, *locs, *locs),
        )
        cols = [d[0] for d in cur.description]
        out: Dict[str, LastPaymentDTO] = {}
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            ck = (d.get('ck') or '').strip()
            if not ck:
                continue
            pb = _normalize_pb(d.get('pb'))
            out[ck] = LastPaymentDTO(
                cari_kod=ck,
                tutar=float(d.get('amt') or 0),
                tarih=d.get('odeme_tarihi') or '',
                kaynak=d.get('kaynak') or '',
                pb=pb,
            )
        return out
    finally:
        con.close()


def fetch_last_cek_map(
    locations: Optional[Sequence[str]] = None,
    force_refresh: bool = False,
) -> Dict[str, LastCekDTO]:
    """Batch — son verilen çek (P0-aligned: CekTip=F + Cek_Har HarTip=0).

    P1.2E: cek_Kart CMKod=mycek=K yetersiz — tedarikçiye verilen çek Cek_Har üzerinden
    cmb_Kod ile bağlanır (P0 ledger ile aynı kaynak).
    """
    ph, locs = _in_clause_locs(locations)
    con = _baglan()
    try:
        cur = con.cursor()
        cur.execute(
            f"""
            WITH verilen AS (
              SELECT
                LTRIM(RTRIM(a.CMKod)) AS ck,
                a.Tarih AS verilis,
                a.vade AS vade,
                CAST(a.Tutar AS FLOAT) AS amt,
                LTRIM(RTRIM(ISNULL(a.CekNo, ''))) AS cekno,
                LTRIM(RTRIM(ISNULL(a.ParaCinsi, 'TL'))) AS pb
              FROM cek_Kart a WITH (NOLOCK)
              WHERE a.CekTip = 'F' AND a.CM = 'C'
                AND a.CMKod LIKE '320.%%'
                AND (a.iptal IS NULL OR a.iptal = 0)
                AND a.Location IN ({ph})

              UNION ALL

              SELECT
                LTRIM(RTRIM(b.cmb_Kod)) AS ck,
                b.Tarih AS verilis,
                a.vade AS vade,
                CAST(a.Tutar AS FLOAT) AS amt,
                LTRIM(RTRIM(ISNULL(a.CekNo, ''))) AS cekno,
                LTRIM(RTRIM(ISNULL(a.ParaCinsi, 'TL'))) AS pb
              FROM Cek_Har b WITH (NOLOCK)
              JOIN cek_Kart a WITH (NOLOCK) ON a.Cekinx = b.Cekinx
              WHERE b.HarTip = '0' AND b.cmb = 'C'
                AND b.cmb_Kod LIKE '320.%%'
                AND a.CekTip IN ('M', 'MX') AND a.mycek = 'K'
                AND (a.iptal IS NULL OR a.iptal = 0)
                AND a.Location IN ({ph})
            ),
            ranked AS (
              SELECT ck, verilis, vade, amt, cekno, pb,
                ROW_NUMBER() OVER (
                  PARTITION BY ck
                  ORDER BY verilis DESC, amt DESC
                ) AS rn
              FROM verilen
            )
            SELECT
              ck,
              CONVERT(VARCHAR(10), verilis, 120) AS verilis,
              CONVERT(VARCHAR(10), vade, 120) AS vade,
              amt,
              cekno,
              pb
            FROM ranked
            WHERE rn = 1
            """,
            (*locs, *locs),
        )
        cols = [d[0] for d in cur.description]
        out: Dict[str, LastCekDTO] = {}
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            ck = (d.get('ck') or '').strip()
            if not ck:
                continue
            out[ck] = LastCekDTO(
                cari_kod=ck,
                tutar=float(d.get('amt') or 0),
                verilis=d.get('verilis') or '',
                vade=d.get('vade') or '',
                cek_no=d.get('cekno') or '',
                pb=_normalize_pb(d.get('pb')),
            )
        return out
    finally:
        con.close()


def fetch_last_purchase_map(
    locations: Optional[Sequence[str]] = None,
    force_refresh: bool = False,
) -> Dict[str, LastPurchaseDTO]:
    """Batch — son alış faturası (Fatura='*', al/si yönü, kg_ifn tutar)."""
    ph, locs = _in_clause_locs(locations)
    con = _baglan()
    try:
        cur = con.cursor()
        cur.execute(
            f"""
            WITH ranked AS (
              SELECT
                LTRIM(RTRIM(fk.CariKod)) AS ck,
                CASE WHEN fk.Fatura='*' THEN fk.FatTar ELSE fk.irsaliyeTar END AS dt,
                fk.BelgeNo AS belge,
                LTRIM(RTRIM(ISNULL(fk.FaturaNo, ''))) AS fno,
                LTRIM(RTRIM(ISNULL(fk.FaturaTip, ''))) AS tip,
                fk.Location AS loc,
                ROW_NUMBER() OVER (
                  PARTITION BY LTRIM(RTRIM(fk.CariKod))
                  ORDER BY CASE WHEN fk.Fatura='*' THEN fk.FatTar ELSE fk.irsaliyeTar END DESC,
                           fk.BelgeNo DESC
                ) AS rn
              FROM Fatura_Kay fk WITH (NOLOCK)
              WHERE fk.CariKod LIKE '320.%%'
                AND SUBSTRING(ISNULL(fk.FaturaTip, ''), 2, 2) IN ('al', 'si')
                AND ISNULL(fk.iptal, '') NOT IN ('*', '(')
                AND fk.Location IN ({ph})
            )
            SELECT
              r.ck,
              CONVERT(VARCHAR(10), r.dt, 120) AS fatura_tarihi,
              r.belge,
              r.fno,
              r.tip,
              CAST(SUM(t.NetTutar) AS FLOAT) AS tutar
            FROM ranked r
            CROSS APPLY dbo.kg_ifn_FaturaTutar(r.belge, NULL, 'TL', NULL) t
            WHERE r.rn = 1
            GROUP BY r.ck, r.dt, r.belge, r.fno, r.tip
            """,
            locs,
        )
        cols = [d[0] for d in cur.description]
        out: Dict[str, LastPurchaseDTO] = {}
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            ck = (d.get('ck') or '').strip()
            if not ck:
                continue
            belge = str(d.get('belge') or d.get('fno') or '')
            out[ck] = LastPurchaseDTO(
                cari_kod=ck,
                tutar=float(d.get('tutar') or 0),
                tarih=d.get('fatura_tarihi') or '',
                belge=belge,
                tip=(d.get('tip') or '').lower(),
                pb='TRY',
            )
        return out
    finally:
        con.close()


def fetch_layer2_maps(
    cari_kods: Optional[Sequence[str]] = None,
    locations: Optional[Sequence[str]] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """3 batch sorgu — payment, cek, purchase map (PERF-02 company scope)."""
    ck_list = list(cari_kods) if cari_kods else []
    cache_key = _enrich_cache_key(locations, ck_list if ck_list else None)

    if not force_refresh:
        cached = _cache_get_enrich(cache_key)
        if cached is not None:
            return cached

    t0 = time.time()
    pay = fetch_last_payment_map(locations=locations, force_refresh=force_refresh)
    cek = fetch_last_cek_map(locations=locations, force_refresh=force_refresh)
    pur = fetch_last_purchase_map(locations=locations, force_refresh=force_refresh)
    elapsed_ms = round((time.time() - t0) * 1000)

    data = {
        'last_payment_map': pay,
        'last_cek_map': cek,
        'last_purchase_map': pur,
        'query_count': 3,
        'elapsed_ms': elapsed_ms,
        'queried_locations': list(company_physical_locations(locations)),
    }
    _cache_set_enrich(cache_key, data)
    return data


def build_karar_cari_rows(
    balances: List[SupplierBalanceDTO],
    *,
    soz_map: Optional[Dict[str, Dict[str, Any]]] = None,
    iletisim_map: Optional[Dict[str, Dict[str, Any]]] = None,
    promise_map: Optional[Dict[str, Dict[str, Any]]] = None,
    contact_map: Optional[Dict[str, Dict[str, Any]]] = None,
    term_map: Optional[Dict[str, Dict[str, Any]]] = None,
    takip_map: Optional[Dict[str, bool]] = None,
    cari_view: CariViewMode = 'daily',
    layer2: Optional[Dict[str, Any]] = None,
    today: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Karar masası cari satırları — Layer 1 + Layer 2 join."""
    promise_map = promise_map if promise_map is not None else (soz_map or {})
    contact_map = contact_map if contact_map is not None else (iletisim_map or {})
    term_map = term_map or {}
    takip_map = takip_map or {}
    today = today or date.today()

    if layer2 is None:
        ckods = [b.cari_kod for b in balances]
        layer2 = fetch_layer2_maps(ckods)

    pay_map: Dict[str, LastPaymentDTO] = layer2.get('last_payment_map', {})
    cek_map: Dict[str, LastCekDTO] = layer2.get('last_cek_map', {})
    pur_map: Dict[str, LastPurchaseDTO] = layer2.get('last_purchase_map', {})

    rows: List[Dict[str, Any]] = []
    for b in balances:
        key = b.canonical_key
        aktif_takip = takip_map.get(key, False)
        is_zero = _net_is_zero(b.bakiye)

        if cari_view == 'zero':
            if not is_zero:
                continue
        elif cari_view == 'active':
            if not aktif_takip:
                continue
        else:
            if is_zero:
                continue

        durum_label, durum_class = _bakiye_durumu(b.bakiye)
        karar_badge, karar_class, kritik, karar_aksiyon = _karar_from_net(b.bakiye)

        pay = pay_map.get(b.cari_kod)
        cek = cek_map.get(b.cari_kod)
        pur = pur_map.get(b.cari_kod)

        son_odeme_gun = _days_ago(pay.tarih if pay else None, today)
        son_cek_vade_gun = _days_until(cek.vade if cek else None, today)

        # P1.2D: Son Finansal Aksiyon = max(son nakit/banka, son verilen çek)
        # No new SQL — map seviyesinde date comparison
        cash_date = pay.tarih if pay else None
        cek_date = cek.verilis if cek else None
        if cash_date and cek_date:
            _fa_is_cek = cek_date >= cash_date
        elif cek_date:
            _fa_is_cek = True
        else:
            _fa_is_cek = False

        if _fa_is_cek and cek:
            fa_tutar = cek.tutar
            fa_tarih = cek.verilis
            fa_turu = 'Çek'
            fa_pb = cek.pb or b.para_birimi
            fa_vade = cek.vade
            fa_cek_no = cek.cek_no
            fa_vade_short = _vade_suresi_short(cek.verilis, cek.vade)
        elif pay:
            fa_tutar = pay.tutar
            fa_tarih = pay.tarih
            fa_turu = _kaynak_type_label(pay.kaynak)
            fa_pb = pay.pb or b.para_birimi
            fa_vade = None
            fa_cek_no = None
            fa_vade_short = ''
        else:
            fa_tutar = None
            fa_tarih = None
            fa_turu = ''
            fa_pb = b.para_birimi
            fa_vade = None
            fa_cek_no = None
            fa_vade_short = ''

        son_cek_vade_sure = _vade_suresi_label(cek.verilis if cek else None, cek.vade if cek else None)
        son_cek_vade_short = _vade_suresi_short(cek.verilis if cek else None, cek.vade if cek else None)

        soz_raw = promise_map.get(key)
        ilet_raw = contact_map.get(key)
        enrich = build_row_enrichment(
            b.location, b.cari_kod,
            contact_map=contact_map,
            promise_map=promise_map,
            term_map=term_map,
            today=today,
        )

        rows.append({
            'location': b.location,
            'location_label': b.location_label,
            'cari_kod': b.cari_kod,
            'cari_adi': normalize_cari_display_name(b.cari_adi),
            'cari_adi_raw': b.cari_adi,
            'para_birimi': b.para_birimi,
            'acik_bakiye': b.bakiye,
            'display_bakiye': _display_bakiye(b.bakiye),
            'bakiye_durumu': durum_label,
            'bakiye_durum_class': durum_class,
            'karar_badge': karar_badge,
            'karar_class': karar_class,
            'karar_aksiyon': karar_aksiyon,
            'kritik': kritik,
            'kritik_class': karar_class,
            'anlasma_durumu': enrich['anlasma_durumu'],
            'anlasma_durumu_rich': enrich['term']['display'],
            'vade_has_term': enrich['vade_has_term'],
            'vade_gun': enrich.get('vade_gun'),
            'vade_source': enrich.get('vade_source'),
            'canonical_key': key,
            'aktif_takip': aktif_takip,
            # Son ödeme
            'son_odeme_tutar': pay.tutar if pay else None,
            'son_odeme_tarih': pay.tarih if pay else None,
            'son_odeme_gun_once': son_odeme_gun,
            'son_odeme_kaynak': pay.kaynak if pay else None,
            'son_odeme_pb': pay.pb if pay else None,
            'son_odeme_label': _fmt_money(pay.tutar if pay else None, pay.pb if pay else b.para_birimi),
            # Son çek
            'son_cek_tutar': cek.tutar if cek else None,
            'son_cek_verilis': cek.verilis if cek else None,
            'son_cek_vade': cek.vade if cek else None,
            'son_cek_vade_gun': son_cek_vade_gun,
            'son_cek_no': cek.cek_no if cek else None,
            'son_cek_pb': cek.pb if cek else None,
            'son_cek_label': _fmt_money(cek.tutar if cek else None, cek.pb if cek else b.para_birimi),
            'son_cek_vade_sure': son_cek_vade_sure,
            'son_cek_vade_short': son_cek_vade_short,
            # Son alım
            'son_alim_tutar': pur.tutar if pur else None,
            'son_alim_tarih': pur.tarih if pur else None,
            'son_alim_belge': pur.belge if pur else None,
            'son_alim_tip': pur.tip if pur else None,
            'son_alim_label': _fmt_money(pur.tutar if pur else None, pur.pb if pur else b.para_birimi),
            # P1.2D: Son Finansal Aksiyon (max cash vs check)
            'fa_tutar': fa_tutar,
            'fa_tarih': fa_tarih,
            'fa_turu': fa_turu,
            'fa_pb': fa_pb,
            'fa_vade': fa_vade,
            'fa_cek_no': fa_cek_no,
            'fa_vade_short': fa_vade_short,
            'fa_label': _fmt_money(fa_tutar, fa_pb),
            'fa_is_cek': _fa_is_cek,
            # P1.2D: Son nakit/banka (renamed from son_odeme to be explicit)
            'last_cash_type': _kaynak_type_label(pay.kaynak if pay else ''),
            # P1.3 FAZ4 — CPS ops + Korgün vade enrichment
            'son_odeme_sozu': enrich['son_odeme_sozu'] if enrich['soz_has_active'] else '—',
            'son_odeme_sozu_rich': enrich['promise']['display'],
            'son_gorusme': enrich['son_gorusme'] if enrich['contact']['has_contact'] else '—',
            'son_gorusme_rich': enrich['contact']['display'],
            'temas_tarih_iso': enrich.get('temas_tarih_iso'),
            'soz_has_active': enrich['soz_has_active'],
            'soz_promise_date': enrich.get('soz_promise_date'),
            'soz_is_overdue': enrich.get('soz_is_overdue', False),
            'enrichment': enrich,
        })

    rows.sort(key=lambda r: (r['location'], r['cari_adi'], r['para_birimi']))
    return rows
