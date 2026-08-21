# -*- coding: utf-8 -*-
"""
Cari hareket ledger — kg_fn_CariHesToplam @KC_Temp kurallarına uygun belge seviyesi rebuild.

READ-ONLY Korgün SELECT. kg_fn_CariHesDetail servis hesabında location güvenliği nedeniyle
0 satır döndürdüğünden manuel canonical kaynak rebuild kullanılır.

Parity hedefi: ledger borç/alacak toplamı = kg_fn_CariHesToplam G satırı (±0,01).
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


def _kg_fn_totals(cur, ck: str, finance_scope: str, pc: str) -> Tuple[float, float]:
    cur.execute(
        """
        SELECT CAST(ISNULL(Borc, 0) AS FLOAT), CAST(ISNULL(Alacak, 0) AS FLOAT)
        FROM dbo.kg_fn_CariHesToplam('G', %s, %s, NULL, NULL, NULL, %s, '0', NULL, '', '', '', '')
        """,
        (ck, finance_scope, pc),
    )
    row = cur.fetchone()
    if not row:
        return 0.0, 0.0
    return float(row[0] or 0), float(row[1] or 0)


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
    locs = _scope_locs(finance_scope)

    con = _baglan()
    try:
        cur = con.cursor()
        pc = _resolve_para_cinsi(cur, ck, loc)

        canon_pb = _normalize_pb(pc)

        rows: List[LedgerRow] = []
        rows.extend(_fetch_open_fatura_rows(cur, ck, locs, pc, canon_pb))
        rows.extend(_fetch_kapali_fatura_rows(cur, ck, locs, pc, canon_pb))
        rows.extend(_fetch_cfis_rows(cur, ck, locs, pc, canon_pb))
        rows.extend(_fetch_banka_rows(cur, ck, locs, pc, canon_pb))
        rows.extend(_fetch_cek_ledger_rows(cur, ck, locs, pc, canon_pb))
        rows.extend(_fetch_cfis_c_rows(cur, ck, locs, pc, canon_pb))
        rows.extend(_fetch_ff_fatura_rows(cur, ck, locs, pc, canon_pb))

        rows.sort(key=lambda x: (x.date or '', x.document_no), reverse=True)

        har_borc = round(sum(r.debit for r in rows if r.debit is not None), 2)
        har_alacak = round(sum(r.credit for r in rows if r.credit is not None), 2)
        har_net = round(har_borc - har_alacak, 2)

        fn_borc, fn_alacak = _kg_fn_totals(cur, ck, finance_scope, pc)
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
            # Eksik bucket adayları — kg_fn'de var, henüz belge rebuild yok
            for label in ('DE', 'Si', 'Sf', 'KK', 'GV', 'Senet'):
                blocked.append(label)

        return {
            'ok': True,
            'location': loc,
            'cari_kod': ck,
            'para_birimi': canon_pb,
            'finance_scope': finance_scope,
            'fn_borc': fn_borc,
            'fn_alacak': fn_alacak,
            'fn_net': fn_net,
            'har_borc': har_borc,
            'har_alacak': har_alacak,
            'har_net': har_net,
            'delta_borc': delta_borc,
            'delta_alacak': delta_alacak,
            'parity_ok': parity_ok,
            'parity_delta': delta_net,
            'parity_note': (
                'Canonical bakiye ile uyumlu.'
                if parity_ok else
                'Hareket dökümü canonical neti tam açıklamıyor.'
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
