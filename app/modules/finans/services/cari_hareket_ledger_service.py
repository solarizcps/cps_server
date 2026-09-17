# -*- coding: utf-8 -*-
"""
Cari hareket ledger — kg_fn_CariHesToplam @KC_Temp kurallarına uygun belge seviyesi rebuild.

READ-ONLY Korgün SELECT. kg_fn_CariHesDetail servis hesabında location güvenliği nedeniyle
0 satır döndürdüğünden manuel canonical kaynak rebuild kullanılır.

Resmî bakiye: kg_fn_CariHesToplam G satırı (Borc/Alacak/net).
Hareket ledger'ı açıklayıcıdır; parity sıfırlanmaz, fark dürüstçe gösterilir.
Sahte dengeleme / satış / tahsilat / ödeme / çek satırı üretilmez.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from modules.common.korgun import _baglan
    from modules.finans.services.korgun_finance_adapter import (
        COMPANY_FINANCE_LOCATION_MAP,
        DEBT_NET_TOLERANCE,
        _kg_fn_pc,
        _normalize_pb,
        get_finance_location_scope,
    )
except ImportError:
    from app.modules.common.korgun import _baglan
    from app.modules.finans.services.korgun_finance_adapter import (
        COMPANY_FINANCE_LOCATION_MAP,
        DEBT_NET_TOLERANCE,
        _kg_fn_pc,
        _normalize_pb,
        get_finance_location_scope,
    )


@dataclass
class LedgerRow:
    date: str
    movement_type: str
    document_no: str
    description: str
    due_date: str
    debit: Optional[float]
    credit: Optional[float]
    currency: str
    source_type: str
    source_id: str

    def to_hareket_dict(self) -> Dict[str, Any]:
        """Popup uyumlu legacy alan adları."""
        return {
            'tarih': self.date,
            'tur': self.movement_type,
            'belge_no': self.document_no,
            'aciklama': self.description,
            'vade': self.due_date,
            'borc': self.debit,
            'alacak': self.credit,
            'pb': self.currency,
            'kaynak': self.source_type,
            'source_id': self.source_id,
            'movement_type': self.movement_type,
            'source_type': self.source_type,
        }


def _scope_locs(finance_scope: str) -> Tuple[str, ...]:
    return tuple(x.strip() for x in (finance_scope or '').split(',') if x.strip())


def _in_clause(locs: Sequence[str]) -> Tuple[str, tuple]:
    ph = ','.join(['%s'] * len(locs))
    return f' IN ({ph}) ', tuple(locs)


def _row(
    date: str,
    movement_type: str,
    document_no: str,
    description: str,
    due_date: str,
    borc: float,
    alacak: float,
    pb_raw: str,
    source_type: str,
    source_id: str,
) -> Optional[LedgerRow]:
    b = round(float(borc or 0), 2)
    a = round(float(alacak or 0), 2)
    if abs(b) < 0.005 and abs(a) < 0.005:
        return None
    return LedgerRow(
        date=(date or '')[:10],
        movement_type=movement_type,
        document_no=str(document_no or ''),
        description=(description or '')[:500],
        due_date=(due_date or '')[:10],
        debit=b if b else None,
        credit=a if a else None,
        currency=_normalize_pb(pb_raw),
        source_type=source_type,
        source_id=str(source_id or document_no or ''),
    )


def _resolve_para_cinsi(cur, ck: str, loc: str) -> str:
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
        row = cur.fetchone()
        return _kg_fn_pc((row[0] if row else 'TL'))
    cur.execute("SELECT dbo.kg_fn_CariDefPc(%s)", (ck,))
    row = cur.fetchone()
    return _kg_fn_pc((row[0] if row else 'TL'))


def _cek_has_r1_single_lifecycle(cur, cekinx: int) -> bool:
    """Tek çek: ht3 B + ht0→320.* ht3 günü — kg_fn ht2 saymaz, multipc supplement de yok."""
    cur.execute(
        """
        SELECT 1 FROM Cek_Har b3 WITH (NOLOCK)
        WHERE b3.Cekinx = %s AND b3.HarTip = '3' AND b3.cmb = 'B'
          AND EXISTS (
            SELECT 1 FROM Cek_Har b0 WITH (NOLOCK)
            WHERE b0.Cekinx = %s AND b0.HarTip = '0' AND b0.cmb = 'C'
              AND LEFT(b0.cmb_Kod, 4) = '320.'
              AND CONVERT(date, b0.Tarih) = CONVERT(date, (
                SELECT MAX(x.Tarih) FROM Cek_Har x WITH (NOLOCK)
                WHERE x.Cekinx = %s AND x.HarTip = '3' AND x.cmb = 'B'
              ))
          )
        """,
        (cekinx, cekinx, cekinx),
    )
    return bool(cur.fetchone())


def _single_ht2_cekinx(cur, ck: str, locs: Sequence[str]) -> Optional[int]:
    inl, lp = _in_clause(locs)
    cur.execute(
        f"""
        SELECT DISTINCT a.cekinx
        FROM Cek_Har b WITH (NOLOCK)
        JOIN cek_Kart a WITH (NOLOCK) ON a.Cekinx = b.Cekinx
        WHERE a.CMKod = %s AND b.HarTip = '2' AND b.cmb = 'B'
          AND a.CekTip IN ('M', 'MX') AND a.Location {inl}
        """,
        (ck, *lp),
    )
    rows = [int(r[0]) for r in cur.fetchall() if r[0] is not None]
    return rows[0] if len(rows) == 1 else None


def _cekinx_is_ht0_only(cur, cekinx: int) -> bool:
    cur.execute(
        "SELECT DISTINCT b.HarTip FROM Cek_Har b WITH (NOLOCK) WHERE b.Cekinx = %s",
        (cekinx,),
    )
    hts = {str(r[0] or '').strip() for r in cur.fetchall()}
    return hts == {'0'}


def _fetch_ht0_only_multipc_supplement_rows(
    cur, ck: str, locs: Sequence[str], pc: str, canon_pb: str,
) -> List[LedgerRow]:
    """
    ht0-only cekinx çoklu PB: yalnız caride tek ht2-B varken ve bu ht2 R1 lifecycle değilken
    kg_fn ht0 ciro PB farkını sayar (019 kanıtı; 001/028 guard dışı).
    """
    if not (ck.startswith('120.') and not ck.startswith('120.NX.')):
        return []
    ht2_cx = _single_ht2_cekinx(cur, ck, locs)
    if ht2_cx is None or _cek_has_r1_single_lifecycle(cur, ht2_cx):
        return []
    inl, lp = _in_clause(locs)
    cur.execute(
        f"""
        SELECT
          a.cekinx,
          CONVERT(VARCHAR(10), MAX(b.Tarih), 120) AS dt,
          LTRIM(RTRIM(MAX(ISNULL(a.CekNo, CAST(a.cekinx AS VARCHAR(20)))))) AS belge,
          LTRIM(RTRIM(MAX(ISNULL(b.HarTip, '')))) AS aciklama,
          CONVERT(VARCHAR(10), MAX(a.vade), 120) AS vade,
          CAST(b.Harinx AS VARCHAR(20)) AS sid,
          CAST(SUM(CAST(t.Tutar AS FLOAT)) AS FLOAT) AS all_amt,
          CAST(SUM(
            CASE WHEN t.ParaCinsi = ISNULL(%s, a.ParaCinsi)
              THEN CAST(t.Tutar AS FLOAT) ELSE 0 END
          ) AS FLOAT) AS pc_amt
        FROM Cek_Har b WITH (NOLOCK)
        JOIN cek_Kart a WITH (NOLOCK) ON a.Cekinx = b.Cekinx
        JOIN CekHarTutar t WITH (NOLOCK)
          ON t.FisNo = b.Harinx AND t.FisHarinx = a.Cekinx AND t.LineType = 'S'
        WHERE b.HarTip = '0'
          AND a.CekTip IN ('M', 'MX')
          AND a.CMKod = %s AND a.CM = 'C'
          AND b.cmb = 'C' AND b.cmb_Kod <> %s
          AND a.Location {inl}
        GROUP BY a.cekinx, b.Harinx
        HAVING COUNT(DISTINCT t.ParaCinsi) > 1
          AND SUM(CAST(t.Tutar AS FLOAT)) >
              SUM(CASE WHEN t.ParaCinsi = ISNULL(%s, a.ParaCinsi)
                THEN CAST(t.Tutar AS FLOAT) ELSE 0 END) + 0.005
        """,
        (pc, ck, ck, *lp, pc),
    )
    cols = [d[0] for d in cur.description]
    out: List[LedgerRow] = []
    for raw in cur.fetchall():
        d = dict(zip(cols, raw))
        if not _cekinx_is_ht0_only(cur, int(d['cekinx'])):
            continue
        extra = round(float(d.get('all_amt') or 0) - float(d.get('pc_amt') or 0), 2)
        if extra < 0.005:
            continue
        r = _row(
            d.get('dt'), 'Çek', d.get('belge'),
            f"Çek ht0 PB farkı {d.get('aciklama')}",
            d.get('vade'), 0, extra, canon_pb, 'Cek_Har', f"{d.get('sid')}-ht0mpb",
        )
        if r:
            out.append(r)
    return out


def _count_distinct_ht2b_cekinx(cur, ck: str, locs: Sequence[str]) -> int:
    inl, lp = _in_clause(locs)
    cur.execute(
        f"""
        SELECT COUNT(DISTINCT a.cekinx)
        FROM Cek_Har b WITH (NOLOCK)
        JOIN cek_Kart a WITH (NOLOCK) ON a.Cekinx = b.Cekinx
        WHERE a.CMKod = %s AND b.HarTip = '2' AND b.cmb = 'B'
          AND a.CekTip IN ('M', 'MX') AND a.Location {inl}
        """,
        (ck, *lp),
    )
    row = cur.fetchone()
    return int(row[0] or 0)


def _fetch_classic_multipc_supplement_rows(
    cur, ck: str, locs: Sequence[str], pc: str, canon_pb: str,
) -> List[LedgerRow]:
    """
    Klasik müşteri (120.*, NX hariç): çoklu PB satırlarında kg_fn tam PB toplamı sayar.
    Yalnız canonical PC zaten ledger'da; fark (all_pb - canon) ek alacak satırı.
    Guard: tek ht2-B çek + R1 lifecycle → supplement yok (028 vb.).
    """
    if not (ck.startswith('120.') and not ck.startswith('120.NX.')):
        return []
    inl, lp = _in_clause(locs)
    multi_cek = _count_distinct_ht2b_cekinx(cur, ck, locs) > 1
    out: List[LedgerRow] = []
    blocks = [
        (
            "b.HarTip = '2' AND b.cmb = 'B' AND a.CekTip IN ('M', 'MX') "
            "AND a.CMKod = %s AND a.CM = 'C'",
            (ck,),
            True,
        ),
        (
            "b.HarTip = '3' AND b.cmb = 'B' AND a.CekTip IN ('M', 'MX') AND a.CMKod = %s",
            (ck,),
            True,
        ),
        (
            "b.HarTip IN ('3', 'MP') AND b.cmb = 'C' AND b.cmb_Kod <> %s "
            "AND a.CekTip IN ('M', 'MX') AND a.CMKod = %s AND a.CM = 'C' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM Cek_Har bci WITH (NOLOCK) "
            "  WHERE bci.Cekinx = a.Cekinx AND bci.HarTip = 'ci'"
            ")",
            (ck, ck),
            False,
        ),
    ]
    for where_sql, params, r1_guard in blocks:
        cur.execute(
            f"""
            SELECT
              a.cekinx,
              CONVERT(VARCHAR(10), MAX(b.Tarih), 120) AS dt,
              LTRIM(RTRIM(MAX(ISNULL(a.CekNo, CAST(a.cekinx AS VARCHAR(20)))))) AS belge,
              LTRIM(RTRIM(MAX(ISNULL(b.HarTip, '')))) AS aciklama,
              CONVERT(VARCHAR(10), MAX(a.vade), 120) AS vade,
              CAST(b.Harinx AS VARCHAR(20)) AS sid,
              CAST(SUM(CAST(t.Tutar AS FLOAT)) AS FLOAT) AS all_amt,
              CAST(SUM(
                CASE WHEN t.ParaCinsi = ISNULL(%s, a.ParaCinsi)
                  THEN CAST(t.Tutar AS FLOAT) ELSE 0 END
              ) AS FLOAT) AS pc_amt
            FROM Cek_Har b WITH (NOLOCK)
            JOIN cek_Kart a WITH (NOLOCK) ON a.Cekinx = b.Cekinx
            JOIN CekHarTutar t WITH (NOLOCK)
              ON t.FisNo = b.Harinx AND t.FisHarinx = a.Cekinx AND t.LineType = 'S'
            WHERE {where_sql} AND a.Location {inl}
            GROUP BY a.cekinx, b.Harinx
            HAVING COUNT(DISTINCT t.ParaCinsi) > 1
              AND SUM(CAST(t.Tutar AS FLOAT)) >
                  SUM(CASE WHEN t.ParaCinsi = ISNULL(%s, a.ParaCinsi)
                    THEN CAST(t.Tutar AS FLOAT) ELSE 0 END) + 0.005
            """,
            (pc, *params, *lp, pc),
        )
        cols = [d[0] for d in cur.description]
        for raw in cur.fetchall():
            d = dict(zip(cols, raw))
            if r1_guard and not multi_cek and _cek_has_r1_single_lifecycle(cur, int(d['cekinx'])):
                continue
            extra = round(float(d.get('all_amt') or 0) - float(d.get('pc_amt') or 0), 2)
            if extra < 0.005:
                continue
            r = _row(
                d.get('dt'), 'Çek', d.get('belge'),
                f"Çek PB farkı {d.get('aciklama')}",
                d.get('vade'), 0, extra, canon_pb, 'Cek_Har', f"{d.get('sid')}-mpb",
            )
            if r:
                out.append(r)
    return out


def _fetch_open_fatura_rows(cur, ck: str, locs: Sequence[str], pc: str, canon_pb: str) -> List[LedgerRow]:
    """FA — açık fatura (Fatura='*'), kg_ifn_FaturaTutar."""
    inl, lp = _in_clause(locs)
    cur.execute(
        f"""
        SELECT
          CONVERT(VARCHAR(10), CASE WHEN fk.Fatura='*' THEN fk.FatTar ELSE fk.irsaliyeTar END, 120) AS dt,
          LTRIM(RTRIM(ISNULL(fk.BelgeNo,''))) AS belge,
          LTRIM(RTRIM(ISNULL(fk.FaturaNo,''))) AS fno,
          LTRIM(RTRIM(ISNULL(fk.FaturaTip,''))) AS ftip,
          LTRIM(RTRIM(ISNULL(fk.notu,''))) AS aciklama,
          CONVERT(VARCHAR(10), fk.Vade, 120) AS vade,
          LTRIM(RTRIM(ISNULL(fk.FaturaPc, 'TL'))) AS pb,
          CAST(SUM(CASE WHEN SUBSTRING(fk.FaturaTip, 2, 2) IN ('sa','ai') THEN
            CASE WHEN SUBSTRING(fk.FaturaTip, 2, 2) = 'ai' AND ISNULL(t.TevkifatTutar, 0) > 0
              THEN ISNULL(t.KDVMatrah, 0) + ISNULL(t.TevkifatTutar, 0)
              ELSE t.NetTutar END
            ELSE 0 END) AS FLOAT) AS borc,
          CAST(SUM(CASE WHEN SUBSTRING(fk.FaturaTip, 2, 2) IN ('al','si') THEN t.NetTutar ELSE 0 END) AS FLOAT) AS alacak
        FROM Fatura_Kay fk WITH (NOLOCK)
        CROSS APPLY dbo.kg_ifn_FaturaTutar(fk.BelgeNo, NULL, ISNULL(%s, fk.FaturaPc), NULL) t
        WHERE fk.Fatura = '*'
          AND fk.CariKod = %s
          AND ISNULL(fk.iptal, '') NOT IN ('*','(')
          AND fk.Location {inl}
          AND SUBSTRING(ISNULL(fk.FaturaTip, ''), 1, 1) <> 't'
        GROUP BY fk.FatTar, fk.irsaliyeTar, fk.Fatura, fk.BelgeNo, fk.FaturaNo, fk.FaturaTip,
                 fk.notu, fk.Vade, fk.FaturaPc
        HAVING ABS(SUM(t.NetTutar)) > 0.001
        """,
        (pc, ck, *lp),
    )
    cols = [d[0] for d in cur.description]
    out: List[LedgerRow] = []
    tip_label = {
        'fal': 'Alış Fatura', 'hal': 'Alış Fatura', 'dal': 'Döviz Alış',
        'fsa': 'Satış Fatura', 'hsa': 'Serbest Alış', 'hai': 'İade Fatura',
    }
    for raw in cur.fetchall():
        d = dict(zip(cols, raw))
        ftip = (d.get('ftip') or '').lower()
        lbl = tip_label.get(ftip, 'Fatura')
        r = _row(
            d.get('dt'), lbl, d.get('fno') or d.get('belge'), d.get('aciklama') or lbl,
            d.get('vade'), d.get('borc'), d.get('alacak'), canon_pb, 'Fatura', d.get('belge'),
        )
        if r:
            out.append(r)
    return out


def _fetch_kapali_fatura_rows(cur, ck: str, locs: Sequence[str], pc: str, canon_pb: str) -> List[LedgerRow]:
    """K — kapalı fatura (KFatura='*')."""
    inl, lp = _in_clause(locs)
    cur.execute(
        f"""
        SELECT
          CONVERT(VARCHAR(10), fkk.FatTar, 120) AS dt,
          LTRIM(RTRIM(ISNULL(fkk.BelgeNo,''))) AS belge,
          LTRIM(RTRIM(ISNULL(fkk.FaturaNo,''))) AS fno,
          LTRIM(RTRIM(ISNULL(fkk.FaturaTip,''))) AS ftip,
          LTRIM(RTRIM(ISNULL(fkk.notu,''))) AS aciklama,
          CONVERT(VARCHAR(10), fkk.Vade, 120) AS vade,
          LTRIM(RTRIM(ISNULL(fh.ParaCinsi, 'TL'))) AS pb,
          CAST(SUM(CASE WHEN SUBSTRING(fkk.FaturaTip, 2, 2) IN ('al','si') THEN t.NetTutar ELSE 0 END) AS FLOAT) AS borc,
          CAST(SUM(CASE WHEN SUBSTRING(fkk.FaturaTip, 2, 2) IN ('sa','ai') THEN t.NetTutar ELSE 0 END) AS FLOAT) AS alacak
        FROM Fatura_Kay fkk WITH (NOLOCK)
        LEFT JOIN Fatura_Har fh WITH (NOLOCK) ON fh.BelgeNo = fkk.BelgeNo
        LEFT JOIN FaturaTutar t WITH (NOLOCK)
          ON t.FisNo = fh.BelgeNo AND t.FisHarinx = fh.FatHarinx
          AND t.ParaCinsi = CASE
            WHEN ISNULL(%s, '') <> '' THEN %s
            WHEN ISNULL((SELECT DefPC FROM Cari_Kart WHERE CKod = %s), '') <> '' THEN (SELECT DefPC FROM Cari_Kart WHERE CKod = %s)
            ELSE fh.ParaCinsi END
        WHERE ISNULL(fkk.iptal, '') NOT IN ('*','(')
          AND fkk.CariKod = %s
          AND ISNULL(fkk.KFatura, '') = '*'
          AND fkk.Location {inl}
          AND EXISTS (
            SELECT TOP 1 1 FROM Fatura_Kay fk WITH (NOLOCK)
            WHERE fk.BelgeNo = fkk.BelgeNo AND fk.Fatura = '*'
              AND CHARINDEX('K', ISNULL(fk.KFaturaTip, '')) > 0
          )
        GROUP BY fkk.FatTar, fkk.BelgeNo, fkk.FaturaNo, fkk.FaturaTip, fkk.notu, fkk.Vade, fh.ParaCinsi
        HAVING ABS(SUM(ISNULL(t.NetTutar, 0))) > 0.001
        """,
        (pc, pc, ck, ck, ck, *lp),
    )
    cols = [d[0] for d in cur.description]
    out: List[LedgerRow] = []
    for raw in cur.fetchall():
        d = dict(zip(cols, raw))
        r = _row(
            d.get('dt'), 'Kapalı Fatura', d.get('fno') or d.get('belge'),
            d.get('aciklama') or 'Kapalı fatura', d.get('vade'),
            d.get('borc'), d.get('alacak'), canon_pb, 'KapaliFatura', d.get('belge'),
        )
        if r:
            out.append(r)
    return out


def _fetch_cfis_rows(cur, ck: str, locs: Sequence[str], pc: str, canon_pb: str) -> List[LedgerRow]:
    """K — C_Fis (cbpg), NO/HF→borç NT→alacak."""
    inl, lp = _in_clause(locs)
    cur.execute(
        f"""
        SELECT
          CONVERT(VARCHAR(10), k.FisTar, 120) AS dt,
          LTRIM(RTRIM(ISNULL(k.BelgeNo, k.FisNo))) AS belge,
          LTRIM(RTRIM(ISNULL(k.FisTip,''))) AS ftip,
          LTRIM(RTRIM(ISNULL(h.tanim, ''))) AS aciklama,
          CONVERT(VARCHAR(10), h.Vade, 120) AS vade,
          LTRIM(RTRIM(ISNULL(h.ParaCinsi, 'TL'))) AS pb,
          CAST(SUM(CASE WHEN k.FisTip IN ('NO','HF') THEN t.NetTutar ELSE 0 END) AS FLOAT) AS borc,
          CAST(SUM(CASE WHEN k.FisTip = 'NT' THEN t.NetTutar ELSE 0 END) AS FLOAT) AS alacak
        FROM C_Fis_Kay k WITH (NOLOCK)
        JOIN C_Fis_Har h WITH (NOLOCK) ON h.FisNo = k.FisNo
        LEFT JOIN CFisTutar t WITH (NOLOCK)
          ON t.FisNo = h.FisNo AND t.FisHarinx = h.Fisinx
          AND t.ParaCinsi = CASE
            WHEN ISNULL(%s, '') <> '' THEN %s
            WHEN ISNULL((SELECT DefPC FROM Cari_Kart WHERE CKod = %s), '') <> '' THEN (SELECT DefPC FROM Cari_Kart WHERE CKod = %s)
            ELSE h.ParaCinsi END
        WHERE h.cbpg = %s
          AND ISNULL(k.iptal, '') NOT IN ('*','(')
          AND k.Bolum = 'K'
          AND k.FisTip IN ('NO', 'HF', 'NT')
          AND k.Location {inl}
        GROUP BY k.FisTar, k.BelgeNo, k.FisNo, k.FisTip, h.tanim, h.Vade, h.ParaCinsi
        HAVING ABS(SUM(ISNULL(t.NetTutar, 0))) > 0.001
        """,
        (pc, pc, ck, ck, ck, *lp),
    )
    cols = [d[0] for d in cur.description]
    out: List[LedgerRow] = []
    for raw in cur.fetchall():
        d = dict(zip(cols, raw))
        r = _row(
            d.get('dt'), 'Nakit/Cari Fiş', d.get('belge'), d.get('aciklama') or d.get('ftip'),
            d.get('vade'), d.get('borc'), d.get('alacak'), canon_pb, 'C_Fis', d.get('belge'),
        )
        if r:
            out.append(r)
    return out


def _fetch_banka_rows(cur, ck: str, locs: Sequence[str], pc: str, canon_pb: str) -> List[LedgerRow]:
    """B — Banka FisTip 1→borç, 0→alacak, BankaTutar LineType S."""
    inl, lp = _in_clause(locs)
    cur.execute(
        f"""
        SELECT
          CONVERT(VARCHAR(10), a.Tarih, 120) AS dt,
          LTRIM(RTRIM(ISNULL(a.EvrakNo, a.FisNo))) AS belge,
          LTRIM(RTRIM(ISNULL(a.FisNo,''))) AS fisno,
          LTRIM(RTRIM(ISNULL(a.FisTip,''))) AS ftip,
          LTRIM(RTRIM(ISNULL(b.Tanim, ''))) AS aciklama,
          LTRIM(RTRIM(ISNULL(b.ParaCinsi, 'TL'))) AS pb,
          CAST(SUM(CASE WHEN a.FisTip = '1' THEN ISNULL(t.Tutar, 0) ELSE 0 END) AS FLOAT) AS borc,
          CAST(SUM(CASE WHEN a.FisTip = '0' THEN ISNULL(t.Tutar, 0) ELSE 0 END) AS FLOAT) AS alacak
        FROM Banka_Kay a WITH (NOLOCK)
        JOIN Banka_Har b WITH (NOLOCK) ON b.FisNo = a.FisNo
        LEFT JOIN BankaTutar t WITH (NOLOCK)
          ON t.FisNo = a.FisNo AND t.FisHarinx = b.FisHarinx
          AND t.ParaCinsi = ISNULL(%s, b.ParaCinsi) AND t.LineType = 'S'
        WHERE a.cmb = 'C' AND a.cmbkod = %s
          AND a.FisTur IN ('1', '2')
          AND ISNULL(a.iptal, '') NOT IN ('*','(')
          AND a.Location {inl}
        GROUP BY a.Tarih, a.EvrakNo, a.FisNo, a.FisTip, b.Tanim, b.ParaCinsi
        HAVING ABS(SUM(ISNULL(t.Tutar, 0))) > 0.001
        """,
        (pc, ck, *lp),
    )
    cols = [d[0] for d in cur.description]
    out: List[LedgerRow] = []
    for raw in cur.fetchall():
        d = dict(zip(cols, raw))
        sid = d.get('fisno') or d.get('belge')
        r = _row(
            d.get('dt'), 'Banka/Havale', d.get('belge'), d.get('aciklama') or 'Banka işlemi',
            '', d.get('borc'), d.get('alacak'), canon_pb, 'Banka', sid,
        )
        if r:
            out.append(r)
    return out


def _fetch_cek_ledger_rows(cur, ck: str, locs: Sequence[str], pc: str, canon_pb: str) -> List[LedgerRow]:
    """C — çek kart + Cek_Har (kg_fn C bucket)."""
    inl, lp = _in_clause(locs)
    out: List[LedgerRow] = []

    # Verilen çek borç (CekTip F)
    cur.execute(
        f"""
        SELECT
          CONVERT(VARCHAR(10), a.Tarih, 120) AS dt,
          LTRIM(RTRIM(ISNULL(a.CekNo, CAST(a.cekinx AS VARCHAR(20))))) AS belge,
          LTRIM(RTRIM(ISNULL(a.Banka,''))) AS aciklama,
          CONVERT(VARCHAR(10), a.vade, 120) AS vade,
          LTRIM(RTRIM(ISNULL(a.ParaCinsi, 'TL'))) AS pb,
          CAST(ISNULL(t.Tutar, a.Tutar) AS FLOAT) AS borc,
          CAST(0 AS FLOAT) AS alacak,
          CAST(a.cekinx AS VARCHAR(20)) AS sid
        FROM cek_Kart a WITH (NOLOCK)
        LEFT JOIN CekTutar t WITH (NOLOCK)
          ON t.FisNo = a.cekinx AND t.FisHarinx = a.Cekinx
          AND t.ParaCinsi = ISNULL(%s, a.ParaCinsi) AND t.LineType = 'S'
        WHERE a.CekTip = 'F' AND a.CMKod = %s AND a.CM = 'C'
          AND (a.iptal IS NULL OR a.iptal = 0)
          AND a.Location {inl}
        """,
        (pc, ck, *lp),
    )
    cols = [d[0] for d in cur.description]
    for raw in cur.fetchall():
        d = dict(zip(cols, raw))
        r = _row(d.get('dt'), 'Çek', d.get('belge'), d.get('aciklama') or 'Verilen çek',
                 d.get('vade'), d.get('borc'), d.get('alacak'), canon_pb, 'Cek', d.get('sid'))
        if r:
            out.append(r)

    # Cek_Har alacak (tahsil / protesto)
    cur.execute(
        f"""
        SELECT
          CONVERT(VARCHAR(10), b.Tarih, 120) AS dt,
          LTRIM(RTRIM(ISNULL(a.CekNo, CAST(a.cekinx AS VARCHAR(20))))) AS belge,
          LTRIM(RTRIM(ISNULL(b.HarTip,''))) AS aciklama,
          CONVERT(VARCHAR(10), a.vade, 120) AS vade,
          LTRIM(RTRIM(ISNULL(a.ParaCinsi, 'TL'))) AS pb,
          CAST(0 AS FLOAT) AS borc,
          CAST(ISNULL(t.Tutar, 0) AS FLOAT) AS alacak,
          CAST(b.Harinx AS VARCHAR(20)) AS sid
        FROM Cek_Har b WITH (NOLOCK)
        JOIN cek_Kart a WITH (NOLOCK) ON a.Cekinx = b.Cekinx
        LEFT JOIN CekHarTutar t WITH (NOLOCK)
          ON t.FisNo = b.Harinx AND t.FisHarinx = a.Cekinx
          AND t.ParaCinsi = ISNULL(%s, a.ParaCinsi) AND t.LineType = 'S'
        WHERE b.cmb_Kod = %s AND b.cmb = 'C'
          AND (
            (b.HarTip IN ('4') AND a.CekTip IN ('F', 'FX'))
            OR (b.HarTip IN ('3', 'MP') AND a.CekTip IN ('M', 'MX'))
          )
          AND a.Location {inl}
        """,
        (pc, ck, *lp),
    )
    cols = [d[0] for d in cur.description]
    for raw in cur.fetchall():
        d = dict(zip(cols, raw))
        r = _row(d.get('dt'), 'Çek', d.get('belge'), f"Çek hareket {d.get('aciklama')}",
                 d.get('vade'), d.get('borc'), d.get('alacak'), canon_pb, 'Cek_Har', d.get('sid'))
        if r:
            out.append(r)

    # Cek_Har borç (alınan çek giriş)
    cur.execute(
        f"""
        SELECT
          CONVERT(VARCHAR(10), b.Tarih, 120) AS dt,
          LTRIM(RTRIM(ISNULL(a.CekNo, CAST(a.cekinx AS VARCHAR(20))))) AS belge,
          LTRIM(RTRIM(ISNULL(b.HarTip,''))) AS aciklama,
          CONVERT(VARCHAR(10), a.vade, 120) AS vade,
          LTRIM(RTRIM(ISNULL(a.ParaCinsi, 'TL'))) AS pb,
          CAST(ISNULL(t.Tutar, 0) AS FLOAT) AS borc,
          CAST(0 AS FLOAT) AS alacak,
          CAST(b.Harinx AS VARCHAR(20)) AS sid
        FROM Cek_Har b WITH (NOLOCK)
        JOIN cek_Kart a WITH (NOLOCK) ON a.Cekinx = b.Cekinx
        LEFT JOIN CekHarTutar t WITH (NOLOCK)
          ON t.FisNo = b.Harinx AND t.FisHarinx = a.Cekinx
          AND t.ParaCinsi = ISNULL(%s, a.ParaCinsi) AND t.LineType = 'S'
        WHERE b.HarTip IN ('0', 'ki', 'ci')
          AND a.CekTip IN ('M', 'MX')
          AND (
            (b.cmb_Kod = %s AND b.cmb = 'C' AND b.HarTip <> 'ci')
            OR (a.CMKod = %s AND b.HarTip = 'ci')
          )
          AND a.Location {inl}
        """,
        (pc, ck, ck, *lp),
    )
    cols = [d[0] for d in cur.description]
    for raw in cur.fetchall():
        d = dict(zip(cols, raw))
        r = _row(d.get('dt'), 'Çek', d.get('belge'), f"Çek hareket {d.get('aciklama')}",
                 d.get('vade'), d.get('borc'), d.get('alacak'), canon_pb, 'Cek_Har', d.get('sid'))
        if r:
            out.append(r)

    # Self ht0 alacak yansıması (120.*): HarTip=0, cmb=C, cmb_Kod=CMKod=ck
    # kg_fn G bucket self-ht0 hem borç (blok 3) hem alacak olarak yansır; yalnız müşteri.
    if ck.startswith('120.'):
        cur.execute(
            f"""
            SELECT
              CONVERT(VARCHAR(10), b.Tarih, 120) AS dt,
              LTRIM(RTRIM(ISNULL(a.CekNo, CAST(a.cekinx AS VARCHAR(20))))) AS belge,
              LTRIM(RTRIM(ISNULL(b.HarTip,''))) AS aciklama,
              CONVERT(VARCHAR(10), a.vade, 120) AS vade,
              LTRIM(RTRIM(ISNULL(a.ParaCinsi, 'TL'))) AS pb,
              CAST(ISNULL(t.Tutar, 0) AS FLOAT) AS alacak,
              CAST(b.Harinx AS VARCHAR(20)) AS sid
            FROM Cek_Har b WITH (NOLOCK)
            JOIN cek_Kart a WITH (NOLOCK) ON a.Cekinx = b.Cekinx
            LEFT JOIN CekHarTutar t WITH (NOLOCK)
              ON t.FisNo = b.Harinx AND t.FisHarinx = a.Cekinx
              AND t.ParaCinsi = ISNULL(%s, a.ParaCinsi) AND t.LineType = 'S'
            WHERE b.HarTip = '0'
              AND b.cmb = 'C'
              AND a.CMKod = %s
              AND b.cmb_Kod = %s
              AND a.CekTip IN ('M', 'MX')
              AND a.Location {inl}
            """,
            (pc, ck, ck, *lp),
        )
        cols = [d[0] for d in cur.description]
        for raw in cur.fetchall():
            d = dict(zip(cols, raw))
            r = _row(
                d.get('dt'), 'Çek', d.get('belge'),
                f"Çek self ht0 alacak {d.get('aciklama')}",
                d.get('vade'), 0, d.get('alacak'), canon_pb, 'Cek_Har', d.get('sid'),
            )
            if r:
                out.append(r)

    # Cek_Har alacak — portföy ciro çıkış (CMKod=ck, cmb başka cari)
    nx_ht0_guard = ''
    nx_ht0_params: list = []
    if ck.startswith('120.NX.'):
        # NX: ci+ht0 aynı cekinx çift sayım — belge kanıtı (7023671 vb.)
        nx_ht0_guard = """
          AND NOT EXISTS (
            SELECT 1 FROM Cek_Har bci WITH (NOLOCK)
            WHERE bci.Cekinx = a.Cekinx AND bci.HarTip = 'ci'
          )
        """
    cur.execute(
        f"""
        SELECT
          CONVERT(VARCHAR(10), b.Tarih, 120) AS dt,
          LTRIM(RTRIM(ISNULL(a.CekNo, CAST(a.cekinx AS VARCHAR(20))))) AS belge,
          LTRIM(RTRIM(ISNULL(b.HarTip,''))) AS aciklama,
          CONVERT(VARCHAR(10), a.vade, 120) AS vade,
          LTRIM(RTRIM(ISNULL(a.ParaCinsi, 'TL'))) AS pb,
          CAST(0 AS FLOAT) AS borc,
          CAST(ISNULL(t.Tutar, 0) AS FLOAT) AS alacak,
          CAST(b.Harinx AS VARCHAR(20)) AS sid
        FROM Cek_Har b WITH (NOLOCK)
        JOIN cek_Kart a WITH (NOLOCK) ON a.Cekinx = b.Cekinx
        LEFT JOIN CekHarTutar t WITH (NOLOCK)
          ON t.FisNo = b.Harinx AND t.FisHarinx = a.Cekinx
          AND t.ParaCinsi = ISNULL(%s, a.ParaCinsi) AND t.LineType = 'S'
        WHERE b.HarTip = '0'
          AND a.CekTip IN ('M', 'MX')
          AND a.CMKod = %s AND a.CM = 'C'
          AND b.cmb = 'C' AND b.cmb_Kod <> %s
          AND a.Location {inl}
          {nx_ht0_guard}
        """,
        (pc, ck, ck, *lp, *nx_ht0_params),
    )
    cols = [d[0] for d in cur.description]
    for raw in cur.fetchall():
        d = dict(zip(cols, raw))
        r = _row(
            d.get('dt'), 'Çek', d.get('belge'),
            f"Çek ciro çıkış {d.get('aciklama')}",
            d.get('vade'), d.get('borc'), d.get('alacak'), canon_pb, 'Cek_Har', d.get('sid'),
        )
        if r:
            out.append(r)

    # Cek_Har alacak — portföy çek banka hareketleri (HarTip 1/2, cmb=B, kg_fn C bucket)
    for _htip, _label in (('1', 'banka giriş'), ('2', 'bankaya verildi')):
        ht2_nx_guard = ''
        ht2_single_cek_guard = ''
        ht2_guard_params: list = []
        if ck.startswith('120.NX.') and _htip == '2':
            # NX: ht0 ciro (aynı veya aynı CekNo/yeniden basım cekinx) sonrası ht2 B çift sayım.
            ht2_nx_guard = f"""
              AND NOT EXISTS (
                SELECT 1 FROM Cek_Har b0 WITH (NOLOCK)
                WHERE b0.Cekinx = a.Cekinx
                  AND b0.HarTip = '0' AND b0.cmb = 'C' AND b0.cmb_Kod <> %s
              )
              AND NOT EXISTS (
                SELECT 1 FROM Cek_Har b0 WITH (NOLOCK)
                JOIN cek_Kart a0 WITH (NOLOCK) ON a0.Cekinx = b0.Cekinx
                WHERE a0.CMKod = %s AND a0.CekNo = a.CekNo AND a0.cekinx <> a.Cekinx
                  AND b0.HarTip = '0' AND b0.cmb = 'C' AND b0.cmb_Kod <> %s
              )
            """
            ht2_guard_params.extend((ck, ck, ck))
        elif ck.startswith('120.') and not ck.startswith('120.NX.') and _htip == '2':
            # Klasik müşteri: tek ht2-B çekinde ht3+ht0→320.* aynı gün → ht2 kg_fn'de sayılmaz.
            ht2_single_cek_guard = f"""
              AND NOT (
                EXISTS (
                  SELECT 1 FROM Cek_Har b3 WITH (NOLOCK)
                  WHERE b3.Cekinx = a.Cekinx AND b3.HarTip = '3' AND b3.cmb = 'B'
                )
                AND EXISTS (
                  SELECT 1 FROM Cek_Har b0 WITH (NOLOCK)
                  WHERE b0.Cekinx = a.Cekinx AND b0.HarTip = '0' AND b0.cmb = 'C'
                    AND LEFT(b0.cmb_Kod, 4) = '320.'
                    AND CONVERT(date, b0.Tarih) = CONVERT(date, (
                      SELECT MAX(b3b.Tarih) FROM Cek_Har b3b WITH (NOLOCK)
                      WHERE b3b.Cekinx = a.Cekinx AND b3b.HarTip = '3' AND b3b.cmb = 'B'
                    ))
                )
                AND (
                  SELECT COUNT(DISTINCT a2.cekinx) FROM Cek_Har b2 WITH (NOLOCK)
                  JOIN cek_Kart a2 WITH (NOLOCK) ON a2.Cekinx = b2.Cekinx
                  WHERE a2.CMKod = %s AND b2.HarTip = '2' AND b2.cmb = 'B'
                    AND a2.CekTip IN ('M', 'MX') AND a2.Location {inl}
                ) = 1
              )
            """
            ht2_guard_params.extend((ck, *lp))
        cur.execute(
            f"""
            SELECT
              CONVERT(VARCHAR(10), b.Tarih, 120) AS dt,
              LTRIM(RTRIM(ISNULL(a.CekNo, CAST(a.cekinx AS VARCHAR(20))))) AS belge,
              LTRIM(RTRIM(ISNULL(b.HarTip,''))) AS aciklama,
              CONVERT(VARCHAR(10), a.vade, 120) AS vade,
              LTRIM(RTRIM(ISNULL(a.ParaCinsi, 'TL'))) AS pb,
              CAST(0 AS FLOAT) AS borc,
              CAST(ISNULL(t.Tutar, 0) AS FLOAT) AS alacak,
              CAST(b.Harinx AS VARCHAR(20)) AS sid
            FROM Cek_Har b WITH (NOLOCK)
            JOIN cek_Kart a WITH (NOLOCK) ON a.Cekinx = b.Cekinx
            LEFT JOIN CekHarTutar t WITH (NOLOCK)
              ON t.FisNo = b.Harinx AND t.FisHarinx = a.Cekinx
              AND t.ParaCinsi = ISNULL(%s, a.ParaCinsi) AND t.LineType = 'S'
            WHERE b.HarTip = %s
              AND b.cmb = 'B'
              AND a.CekTip IN ('M', 'MX')
              AND a.CMKod = %s AND a.CM = 'C'
              AND a.Location {inl}
              {ht2_nx_guard}
              {ht2_single_cek_guard}
            """,
            (pc, _htip, ck, *lp, *ht2_guard_params),
        )
        cols = [d[0] for d in cur.description]
        for raw in cur.fetchall():
            d = dict(zip(cols, raw))
            r = _row(
                d.get('dt'), 'Çek', d.get('belge'),
                f"Çek {_label} {d.get('aciklama')}",
                d.get('vade'), d.get('borc'), d.get('alacak'), canon_pb, 'Cek_Har', d.get('sid'),
            )
            if r:
                out.append(r)

    # Cek_Har alacak — portföy protesto/tahsil cross-cari (HarTip 3/MP, cmb=C, cmb_Kod≠ck)
    # Yalnız klasik müşteri (120.*, NX hariç): tedarikçi + NX serisinde kg_fn farklı.
    # ci (ciro giriş) yaşam döngüsü olan çekte ht3 cross çift sayım yapılır → hariç.
    if ck.startswith('120.') and not ck.startswith('120.NX.'):
        cur.execute(
            f"""
            SELECT
              CONVERT(VARCHAR(10), b.Tarih, 120) AS dt,
              LTRIM(RTRIM(ISNULL(a.CekNo, CAST(a.cekinx AS VARCHAR(20))))) AS belge,
              LTRIM(RTRIM(ISNULL(b.HarTip,''))) AS aciklama,
              CONVERT(VARCHAR(10), a.vade, 120) AS vade,
              LTRIM(RTRIM(ISNULL(a.ParaCinsi, 'TL'))) AS pb,
              CAST(0 AS FLOAT) AS borc,
              CAST(ISNULL(t.Tutar, 0) AS FLOAT) AS alacak,
              CAST(b.Harinx AS VARCHAR(20)) AS sid
            FROM Cek_Har b WITH (NOLOCK)
            JOIN cek_Kart a WITH (NOLOCK) ON a.Cekinx = b.Cekinx
            LEFT JOIN CekHarTutar t WITH (NOLOCK)
              ON t.FisNo = b.Harinx AND t.FisHarinx = a.Cekinx
              AND t.ParaCinsi = ISNULL(%s, a.ParaCinsi) AND t.LineType = 'S'
            WHERE b.HarTip IN ('3', 'MP')
              AND b.cmb = 'C'
              AND b.cmb_Kod <> %s
              AND a.CekTip IN ('M', 'MX')
              AND a.CMKod = %s AND a.CM = 'C'
              AND a.Location {inl}
              AND NOT EXISTS (
                SELECT 1 FROM Cek_Har bci WITH (NOLOCK)
                WHERE bci.Cekinx = a.Cekinx AND bci.HarTip = 'ci'
              )
            """,
            (pc, ck, ck, *lp),
        )
        cols = [d[0] for d in cur.description]
        for raw in cur.fetchall():
            d = dict(zip(cols, raw))
            r = _row(
                d.get('dt'), 'Çek', d.get('belge'),
                f"Çek protesto/tahsil {d.get('aciklama')}",
                d.get('vade'), d.get('borc'), d.get('alacak'), canon_pb, 'Cek_Har', d.get('sid'),
            )
            if r:
                out.append(r)

        out.extend(_fetch_classic_multipc_supplement_rows(cur, ck, locs, pc, canon_pb))
        out.extend(_fetch_ht0_only_multipc_supplement_rows(cur, ck, locs, pc, canon_pb))

    # Tedarikçi: ht3/MP cross-cari — kg_fn çoklu PB tam tutarı sayar, canonical PC farkı ek alacak.
    if ck.startswith('320.'):
        cur.execute(
            f"""
            SELECT
              CONVERT(VARCHAR(10), MAX(b.Tarih), 120) AS dt,
              LTRIM(RTRIM(MAX(ISNULL(a.CekNo, CAST(a.cekinx AS VARCHAR(20)))))) AS belge,
              LTRIM(RTRIM(MAX(ISNULL(b.HarTip, '')))) AS aciklama,
              CONVERT(VARCHAR(10), MAX(a.vade), 120) AS vade,
              CAST(b.Harinx AS VARCHAR(20)) AS sid,
              CAST(SUM(CAST(t.Tutar AS FLOAT)) AS FLOAT) AS all_amt,
              CAST(SUM(
                CASE WHEN t.ParaCinsi = ISNULL(%s, a.ParaCinsi)
                  THEN CAST(t.Tutar AS FLOAT) ELSE 0 END
              ) AS FLOAT) AS pc_amt
            FROM Cek_Har b WITH (NOLOCK)
            JOIN cek_Kart a WITH (NOLOCK) ON a.Cekinx = b.Cekinx
            JOIN CekHarTutar t WITH (NOLOCK)
              ON t.FisNo = b.Harinx AND t.FisHarinx = a.Cekinx AND t.LineType = 'S'
            WHERE b.HarTip IN ('3', 'MP')
              AND b.cmb = 'C'
              AND b.cmb_Kod <> %s
              AND a.CekTip IN ('M', 'MX')
              AND a.CMKod = %s AND a.CM = 'C'
              AND a.Location {inl}
            GROUP BY b.Harinx
            HAVING COUNT(DISTINCT t.ParaCinsi) > 1
              AND SUM(CAST(t.Tutar AS FLOAT)) >
                  SUM(CASE WHEN t.ParaCinsi = ISNULL(%s, a.ParaCinsi)
                    THEN CAST(t.Tutar AS FLOAT) ELSE 0 END) + 0.005
            """,
            (pc, ck, ck, *lp, pc),
        )
        cols = [d[0] for d in cur.description]
        for raw in cur.fetchall():
            d = dict(zip(cols, raw))
            extra = round(float(d.get('all_amt') or 0) - float(d.get('pc_amt') or 0), 2)
            if extra < 0.005:
                continue
            r = _row(
                d.get('dt'), 'Çek', d.get('belge'),
                f"Çek protesto/tahsil PB farkı {d.get('aciklama')}",
                d.get('vade'), 0, extra, canon_pb, 'Cek_Har', f"{d.get('sid')}-mpb",
            )
            if r:
                out.append(r)

    return out


def _fetch_cfis_c_rows(cur, ck: str, locs: Sequence[str], pc: str, canon_pb: str) -> List[LedgerRow]:
    """CD/CE/CV/KF/Gi/SV/SA — C_Fis Bolum C hareketleri."""
    inl, lp = _in_clause(locs)
    fis_map = {
        'DB': ('Devir', 'Devir borç'),
        'DA': ('Devir', 'Devir alacak'),
        'BD': ('Dekont', 'Borç dekontu'),
        'AD': ('Dekont', 'Alacak dekontu'),
        'CV': ('Virman', 'Cari virman'),
        'KF': ('Kur Farkı', 'Kur farkı giren'),
        'KG': ('Kur Farkı', 'Kur farkı çıkan'),
        'AG': ('Gider', 'Borç gider'),
        'BG': ('Gider', 'Alacak gider'),
        'SV': ('Serbest Makbuz', 'Verilen SMM'),
        'SA': ('Serbest Makbuz', 'Alınan SMM'),
    }
    cur.execute(
        f"""
        SELECT
          CONVERT(VARCHAR(10), k.FisTar, 120) AS dt,
          LTRIM(RTRIM(ISNULL(k.BelgeNo, k.FisNo))) AS belge,
          LTRIM(RTRIM(ISNULL(k.FisNo,''))) AS fisno,
          LTRIM(RTRIM(ISNULL(k.FisTip,''))) AS ftip,
          LTRIM(RTRIM(ISNULL(h.tanim, ''))) AS aciklama,
          CONVERT(VARCHAR(10), h.Vade, 120) AS vade,
          LTRIM(RTRIM(ISNULL(h.ParaCinsi, 'TL'))) AS pb,
          CAST(SUM(ISNULL(t.NetTutar, 0)) AS FLOAT) AS tutar
        FROM C_Fis_Kay k WITH (NOLOCK)
        JOIN C_Fis_Har h WITH (NOLOCK) ON h.FisNo = k.FisNo
        LEFT JOIN CFisTutar t WITH (NOLOCK)
          ON t.FisNo = k.FisNo AND t.FisHarinx = h.Fisinx
          AND t.ParaCinsi = ISNULL(%s, h.ParaCinsi)
          AND (t.LineType = 'S' OR t.LineType IS NULL)
        WHERE k.Bolum = 'C'
          AND ISNULL(k.iptal, '') NOT IN ('*','(')
          AND h.cbpg = %s
          AND k.FisTip IN ('DB','DA','BD','AD','CV','KF','KG','AG','BG','SV','SA')
          AND k.Location {inl}
        GROUP BY k.FisTar, k.BelgeNo, k.FisNo, k.FisTip, h.tanim, h.Vade, h.ParaCinsi
        HAVING ABS(SUM(ISNULL(t.NetTutar, 0))) > 0.001
        """,
        (pc, ck, *lp),
    )
    cols = [d[0] for d in cur.description]
    out: List[LedgerRow] = []
    for raw in cur.fetchall():
        d = dict(zip(cols, raw))
        ftip = (d.get('ftip') or '').upper()
        mt, desc = fis_map.get(ftip, ('Cari Fiş', ftip))
        tutar = float(d.get('tutar') or 0)
        borc = alacak = 0.0
        if ftip in ('DB', 'BD', 'KF', 'AG', 'SV'):
            borc = tutar
        elif ftip in ('DA', 'AD', 'KG', 'BG', 'SA'):
            alacak = tutar
        elif ftip == 'CV':
            borc = tutar
        sid = f"{d.get('fisno')}-{ftip}"
        r = _row(d.get('dt'), mt, d.get('belge'), d.get('aciklama') or desc,
                 d.get('vade'), borc, alacak, canon_pb, 'C_Fis_C', sid)
        if r:
            out.append(r)
    return out


def _fetch_ff_fatura_rows(cur, ck: str, locs: Sequence[str], pc: str, canon_pb: str) -> List[LedgerRow]:
    inl, lp = _in_clause(locs)
    cur.execute(
        f"""
        SELECT
          CONVERT(VARCHAR(10), fk.FatTar, 120) AS dt,
          LTRIM(RTRIM(ISNULL(fk.BelgeNo,''))) AS belge,
          LTRIM(RTRIM(ISNULL(fk.FaturaNo,''))) AS fno,
          LTRIM(RTRIM(ISNULL(fk.Tip,''))) AS tip,
          LTRIM(RTRIM(ISNULL(fk.YansimaTip,''))) AS ytip,
          CAST(SUM(t.NetTutar) AS FLOAT) AS tutar
        FROM FFFatura_Kay fk WITH (NOLOCK)
        CROSS APPLY dbo.kg_ifn_FFFaturaTutar(fk.BelgeNo, NULL, %s, NULL) t
        WHERE fk.CariKod = %s
          AND ISNULL(fk.iptal, '') NOT IN ('*','(')
          AND fk.Location {inl}
        GROUP BY fk.FatTar, fk.BelgeNo, fk.FaturaNo, fk.Tip, fk.YansimaTip
        HAVING ABS(SUM(t.NetTutar)) > 0.001
        """,
        (pc, ck, *lp),
    )
    cols = [d[0] for d in cur.description]
    out: List[LedgerRow] = []
    for raw in cur.fetchall():
        d = dict(zip(cols, raw))
        tip, ytip = d.get('tip'), d.get('ytip')
        tutar = float(d.get('tutar') or 0)
        borc = alacak = 0.0
        if (tip == 'S' and ytip == '-') or (tip == 'A' and ytip == '+'):
            alacak = tutar
        elif (tip == 'S' and ytip == '+') or (tip == 'A' and ytip == '-'):
            borc = tutar
        r = _row(d.get('dt'), 'Fiyat Farkı Fatura', d.get('fno') or d.get('belge'),
                 'Fiyat farkı faturası', '', borc, alacak, canon_pb, 'FF_Fatura', d.get('belge'))
        if r:
            out.append(r)
    return out


def _fetch_verilen_cekler(cur, ck: str, locs: Sequence[str]) -> List[Dict[str, Any]]:
    """Bilgi paneli — mycek=K, net hesaba dahil edilmez."""
    inl, lp = _in_clause(locs)
    cur.execute(
        f"""
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
        WHERE c.CMKod = %s AND c.mycek = 'K'
          AND (c.iptal IS NULL OR c.iptal = 0)
          AND c.Location {inl}
        ORDER BY c.vade
        """,
        (ck, *lp),
    )
    cols = [d[0] for d in cur.description]
    sdurum_map = {
        'A': 'Aktif / Portföyde', 'BO': 'Bankaya verildi',
        '4': 'Tahsil edildi', '3': 'Protestolu', 'KO': 'Kısmi ödeme',
    }
    cekler = []
    for raw in cur.fetchall():
        d = dict(zip(cols, raw))
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
    return cekler


def _fetch_fx_g_mirror_rows(
    ck: str,
    canon_pb: str,
    rows: Sequence[LedgerRow],
    fn_borc: float,
    fn_alacak: float,
) -> List[LedgerRow]:
    """
    USD/EUR müşteri (120.*): kg_fn G bucket açık belge borcunu alacak olarak da yansıtır.
    Koşullar: çek alacak yok; fn_a-fn_b = banka alacak; delta_alacak ≈ açık belge borcu.
    """
    if not ck.startswith('120.') or canon_pb not in ('USD', 'EUR'):
        return []
    cek_a = round(sum(r.credit or 0 for r in rows if r.source_type in ('Cek', 'Cek_Har')), 2)
    if cek_a > 0.01:
        return []
    bank_a = round(sum(r.credit or 0 for r in rows if r.source_type == 'Banka'), 2)
    fn_open = round(fn_alacak - fn_borc, 2)
    if abs(fn_open - bank_a) > DEBT_NET_TOLERANCE:
        return []
    doc_b = round(
        sum(
            r.debit or 0
            for r in rows
            if r.source_type in ('Fatura', 'C_Fis', 'C_Fis_C', 'KapaliFatura')
        ),
        2,
    )
    if doc_b < 0.01:
        return []
    har_a = round(sum(r.credit or 0 for r in rows), 2)
    gap_a = round(fn_alacak - har_a, 2)
    if abs(gap_a - doc_b) > max(DEBT_NET_TOLERANCE, 0.02 * max(doc_b, 1.0)):
        return []
    out: List[LedgerRow] = []
    for r in rows:
        if r.source_type not in ('Fatura', 'C_Fis', 'C_Fis_C', 'KapaliFatura'):
            continue
        b = round(r.debit or 0, 2)
        if b < 0.01:
            continue
        mirror = _row(
            r.date, 'Kur/G bucket yansıma', r.document_no,
            f'FX G yansıma ({r.movement_type})',
            r.due_date, 0, b, r.currency, 'FX_G_Mirror',
            f'fx-{r.source_id}',
        )
        if mirror:
            out.append(mirror)
    return out


def _kg_fn_totals(cur, ck: str, location: str, pc: str) -> Tuple[float, float]:
    """Tek canonical location — consolidated scope ile ayna lokasyon netlenmez."""
    cur.execute(
        """
        SELECT CAST(ISNULL(Borc, 0) AS FLOAT), CAST(ISNULL(Alacak, 0) AS FLOAT)
        FROM dbo.kg_fn_CariHesToplam('G', %s, %s, NULL, NULL, NULL, %s, '0', NULL, '', '', '', '')
        """,
        (ck, location, pc),
    )
    row = cur.fetchone()
    if not row:
        return 0.0, 0.0
    return float(row[0] or 0), float(row[1] or 0)


def _resolve_ledger_balance_scope(
    loc: str,
    ck: str,
    canon_pb: str,
) -> Dict[str, Any]:
    """
    Resmî kg_fn: canonical location (mirror hariç).
    Hareket kapsamı: mirror çözümlendiyse yalnız canonical location.
    """
    if ck.startswith("120."):
        try:
            from modules.finans.read_model.rm_balance_resolver import (
                resolve_canonical_customer_balance,
            )
        except ImportError:
            from app.modules.finans.read_model.rm_balance_resolver import (
                resolve_canonical_customer_balance,
            )
        res = resolve_canonical_customer_balance(loc, ck, canon_pb)
    else:
        try:
            from modules.finans.read_model.rm_balance_resolver import (
                resolve_canonical_supplier_balance,
            )
        except ImportError:
            from app.modules.finans.read_model.rm_balance_resolver import (
                resolve_canonical_supplier_balance,
            )
        res = resolve_canonical_supplier_balance(loc, ck, canon_pb)

    canon_loc = (res.get("canonical_location") or loc).strip().upper()
    mirror_loc = res.get("mirror_location")
    if res.get("status") == "resolved" and mirror_loc:
        movement_locs: Tuple[str, ...] = (canon_loc,)
    else:
        movement_locs = _scope_locs(get_finance_location_scope(loc))

    fn_borc = float(res.get("borc") or 0)
    fn_alacak = float(res.get("alacak") or 0)
    fn_net = float(res.get("net") or 0)
    return {
        "balance_res": res,
        "canonical_location": canon_loc,
        "mirror_location": mirror_loc,
        "movement_locs": movement_locs,
        "fn_borc": fn_borc,
        "fn_alacak": fn_alacak,
        "fn_net": fn_net,
    }


def build_cari_hareket_ledger(
    location: str,
    cari_kod: str,
) -> Dict[str, Any]:
    """
    Tek cari için normalized ledger + parity + verilen çek bilgi paneli.
    """
    loc = (location or '').strip().upper()
    ck = (cari_kod or '').strip()
    finance_scope = get_finance_location_scope(loc)

    con = _baglan()
    try:
        cur = con.cursor()
        pc = _resolve_para_cinsi(cur, ck, loc)

        canon_pb = _normalize_pb(pc)
        bal_scope = _resolve_ledger_balance_scope(loc, ck, canon_pb)
        locs = bal_scope["movement_locs"]
        canon_loc = bal_scope["canonical_location"]
        mirror_loc = bal_scope["mirror_location"]

        rows: List[LedgerRow] = []
        rows.extend(_fetch_open_fatura_rows(cur, ck, locs, pc, canon_pb))
        rows.extend(_fetch_kapali_fatura_rows(cur, ck, locs, pc, canon_pb))
        rows.extend(_fetch_cfis_rows(cur, ck, locs, pc, canon_pb))
        rows.extend(_fetch_banka_rows(cur, ck, locs, pc, canon_pb))
        rows.extend(_fetch_cek_ledger_rows(cur, ck, locs, pc, canon_pb))
        rows.extend(_fetch_cfis_c_rows(cur, ck, locs, pc, canon_pb))
        rows.extend(_fetch_ff_fatura_rows(cur, ck, locs, pc, canon_pb))

        fn_borc = bal_scope["fn_borc"]
        fn_alacak = bal_scope["fn_alacak"]
        # Informational ledger: FX G mirror / sahte dengeleme satırı üretilmez.

        rows.sort(key=lambda x: (x.date or '', x.document_no), reverse=True)

        har_borc = round(sum(r.debit for r in rows if r.debit is not None), 2)
        har_alacak = round(sum(r.credit for r in rows if r.credit is not None), 2)
        har_net = round(har_borc - har_alacak, 2)
        fn_net = round(fn_borc - fn_alacak, 2)
        delta_borc = round(fn_borc - har_borc, 2)
        delta_alacak = round(fn_alacak - har_alacak, 2)
        delta_net = round(fn_net - har_net, 2)
        parity_ok = (
            abs(delta_net) <= DEBT_NET_TOLERANCE
            and abs(delta_borc) <= DEBT_NET_TOLERANCE
            and abs(delta_alacak) <= DEBT_NET_TOLERANCE
        )

        cekler = _fetch_verilen_cekler(cur, ck, locs)

        blocked: List[str] = []
        if not parity_ok:
            # Eksik bucket adayları — kg_fn'de var, ham hareket kapsamı karşılamıyor
            for label in ('DE', 'Si', 'Sf', 'KK', 'GV', 'Senet', 'PB-location'):
                blocked.append(label)

        return {
            'ok': True,
            'location': loc,
            'cari_kod': ck,
            'para_birimi': canon_pb,
            'finance_scope': finance_scope,
            'canonical_location': canon_loc,
            'mirror_location': mirror_loc,
            'canonical_balance_source': 'kg_fn',
            'movement_ledger_role': 'informational',
            'fn_borc': fn_borc,
            'fn_alacak': fn_alacak,
            'fn_net': fn_net,
            'har_borc': har_borc,
            'har_alacak': har_alacak,
            'har_net': har_net,
            'delta_borc': delta_borc,
            'delta_alacak': delta_alacak,
            'delta_net': delta_net,
            'parity_ok': parity_ok,
            'parity_delta': delta_net,
            'parity_note': (
                'Tam mutabık'
                if parity_ok else
                'Hareket kapsamı resmî bakiyeyi tam karşılamıyor'
            ),
            'parity_blocked_classes': blocked if not parity_ok else [],
            'hareketler': [r.to_hareket_dict() for r in rows],
            'cekler': cekler,
            'cari_hes_detail_rows': 0,
            'cari_hes_detail_note': (
                'kg_fn_CariHesDetail servis hesabında location güvenliği nedeniyle 0 satır; '
                'manuel @KC_Temp rebuild kullanıldı.'
            ),
        }
    finally:
        con.close()
