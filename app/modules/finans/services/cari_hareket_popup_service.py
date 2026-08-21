# -*- coding: utf-8 -*-
"""
Cari Hareketleri popup — P1.2C sekme read-model (READ-ONLY).

P0 ledger rebuild'e dokunmaz; build_cari_hareket_ledger REUSE.
P1.2B business semantic korunur.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from modules.common.korgun import _baglan
    from modules.finans.services.cari_hareket_ledger_service import build_cari_hareket_ledger
    from modules.finans.services.korgun_finance_adapter import (
        DEBT_NET_TOLERANCE,
        _normalize_pb,
        get_finance_location_scope,
    )
    from modules.finans.services.odeme_karar_read_service import (
        company_physical_locations,
        _banka_tutar_join_clause,
    )
except ImportError:
    from app.modules.common.korgun import _baglan
    from app.modules.finans.services.cari_hareket_ledger_service import build_cari_hareket_ledger
    from app.modules.finans.services.korgun_finance_adapter import (
        DEBT_NET_TOLERANCE,
        _normalize_pb,
        get_finance_location_scope,
    )
    from app.modules.finans.services.odeme_karar_read_service import (
        company_physical_locations,
        _banka_tutar_join_clause,
    )


_SDURUM_MAP = {
    'A': 'Aktif / Portföyde',
    'BO': 'Bankaya verildi',
    '4': 'Tahsil edildi',
    '3': 'Protestolu',
    'KO': 'Kısmi ödeme',
}


def _company_locs(location: str) -> Tuple[str, ...]:
    """P1.3 FAZ2 — popup enrichment = ledger/layer2 company finance scope."""
    loc = (location or '').strip().upper()
    return company_physical_locations([loc] if loc else None)


def _in_clause(locs: Sequence[str]) -> Tuple[str, tuple]:
    ph = ','.join(['%s'] * len(locs))
    return f' IN ({ph}) ', tuple(locs)


def _net_is_zero(net: float) -> bool:
    return Decimal(str(net)) == Decimal('0')


def business_semantic(net: float) -> Dict[str, str]:
    """P1.2B — raw signed net korunur, görsel yorum."""
    if net > DEBT_NET_TOLERANCE:
        return {'status': 'ALACAKLIYIZ', 'label': 'Alacaklıyız', 'class': 'op-har-net-credit'}
    if net < -DEBT_NET_TOLERANCE:
        return {'status': 'ACIK_BORC', 'label': 'Açık Borç', 'class': 'op-har-net-debt'}
    return {'status': 'BAKIYE_YOK', 'label': 'Bakiye Yok', 'class': 'op-har-net-zero'}


def _days_until(iso_date: Optional[str], today: date) -> Optional[int]:
    if not iso_date:
        return None
    try:
        d = datetime.strptime(iso_date[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None
    return (d - today).days


def _days_ago(iso_date: Optional[str], today: date) -> Optional[int]:
    if not iso_date:
        return None
    try:
        d = datetime.strptime(iso_date[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None
    return (today - d).days


def _fetch_last_payment(cur, ck: str, locs: Sequence[str]) -> Optional[Dict[str, Any]]:
    inl, lp = _in_clause(locs)
    banka_join = _banka_tutar_join_clause('a.cmbkod', 'a.Location')
    cur.execute(
        f"""
        WITH payments AS (
          SELECT a.Tarih AS dt, CAST(ISNULL(t.Tutar, 0) AS FLOAT) AS amt,
            LTRIM(RTRIM(ISNULL(t.ParaCinsi, b.ParaCinsi))) AS pb, 'Banka' AS kaynak,
            LTRIM(RTRIM(ISNULL(a.FisNo, ''))) AS belge
          FROM Banka_Kay a WITH (NOLOCK)
          JOIN Banka_Har b WITH (NOLOCK) ON b.FisNo = a.FisNo
          LEFT JOIN BankaTutar t WITH (NOLOCK)
            {banka_join}
          WHERE a.cmb = 'C' AND a.cmbkod = %s AND a.FisTip = '1'
            AND a.FisTur IN ('1', '2') AND ISNULL(a.iptal, '') NOT IN ('*', '(')
            AND a.Location {inl} AND ISNULL(t.Tutar, 0) > 0.001
          UNION ALL
          SELECT k.FisTar AS dt, CAST(ISNULL(t.NetTutar, 0) AS FLOAT) AS amt,
            LTRIM(RTRIM(ISNULL(t.ParaCinsi, h.ParaCinsi))) AS pb, 'C_Fis' AS kaynak,
            LTRIM(RTRIM(ISNULL(k.BelgeNo, k.FisNo))) AS belge
          FROM C_Fis_Kay k WITH (NOLOCK)
          JOIN C_Fis_Har h WITH (NOLOCK) ON h.FisNo = k.FisNo
          LEFT JOIN CFisTutar t WITH (NOLOCK)
            ON t.FisNo = h.FisNo AND t.FisHarinx = h.Fisinx AND t.ParaCinsi = h.ParaCinsi
          WHERE h.cbpg = %s AND k.Bolum = 'K' AND k.FisTip IN ('NO', 'HF')
            AND ISNULL(k.iptal, '') NOT IN ('*', '(') AND k.Location {inl}
            AND ISNULL(t.NetTutar, 0) > 0.001
          UNION ALL
          SELECT k.FisTar AS dt, CAST(ISNULL(t.NetTutar, 0) AS FLOAT) AS amt,
            LTRIM(RTRIM(ISNULL(t.ParaCinsi, h.ParaCinsi))) AS pb, 'Dekont' AS kaynak,
            LTRIM(RTRIM(ISNULL(k.BelgeNo, k.FisNo))) AS belge
          FROM C_Fis_Kay k WITH (NOLOCK)
          JOIN C_Fis_Har h WITH (NOLOCK) ON h.FisNo = k.FisNo
          LEFT JOIN CFisTutar t WITH (NOLOCK)
            ON t.FisNo = h.FisNo AND t.FisHarinx = h.Fisinx AND t.ParaCinsi = h.ParaCinsi
          WHERE h.cbpg = %s AND k.Bolum = 'C' AND k.FisTip = 'BD'
            AND ISNULL(k.iptal, '') NOT IN ('*', '(') AND k.Location {inl}
            AND ISNULL(t.NetTutar, 0) > 0.001
        )
        SELECT TOP 1
          CONVERT(VARCHAR(10), dt, 120) AS tarih, amt, pb, kaynak, belge
        FROM payments ORDER BY dt DESC, amt DESC
        """,
        (ck, *lp, ck, *lp, ck, *lp),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        'tarih': row[0], 'tutar': float(row[1] or 0),
        'pb': _normalize_pb(row[2]), 'kaynak': row[3], 'belge_no': row[4],
    }


def _fetch_last_cek(cur, ck: str, locs: Sequence[str]) -> Optional[Dict[str, Any]]:
    """P0-aligned — CekTip=F + Cek_Har HarTip=0 (cmb_Kod=tedarikçi)."""
    inl, lp = _in_clause(locs)
    cur.execute(
        f"""
        WITH verilen AS (
          SELECT a.Tarih AS verilis, a.vade AS vade,
            CAST(a.Tutar AS FLOAT) AS tutar,
            LTRIM(RTRIM(ISNULL(a.CekNo, ''))) AS cekno,
            LTRIM(RTRIM(ISNULL(a.ParaCinsi, 'TL'))) AS pb
          FROM cek_Kart a WITH (NOLOCK)
          WHERE a.CekTip = 'F' AND a.CMKod = %s AND a.CM = 'C'
            AND (a.iptal IS NULL OR a.iptal = 0) AND a.Location {inl}
          UNION ALL
          SELECT b.Tarih AS verilis, a.vade AS vade,
            CAST(a.Tutar AS FLOAT) AS tutar,
            LTRIM(RTRIM(ISNULL(a.CekNo, ''))) AS cekno,
            LTRIM(RTRIM(ISNULL(a.ParaCinsi, 'TL'))) AS pb
          FROM Cek_Har b WITH (NOLOCK)
          JOIN cek_Kart a WITH (NOLOCK) ON a.Cekinx = b.Cekinx
          WHERE b.HarTip = '0' AND b.cmb = 'C' AND b.cmb_Kod = %s
            AND a.CekTip IN ('M', 'MX') AND a.mycek = 'K'
            AND (a.iptal IS NULL OR a.iptal = 0) AND a.Location {inl}
        )
        SELECT TOP 1
          CONVERT(VARCHAR(10), verilis, 120) AS verilis,
          CONVERT(VARCHAR(10), vade, 120) AS vade,
          tutar, cekno, pb
        FROM verilen ORDER BY verilis DESC, tutar DESC
        """,
        (ck, *lp, ck, *lp),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        'verilis': row[0], 'vade': row[1], 'tutar': float(row[2] or 0),
        'cekno': row[3], 'pb': _normalize_pb(row[4]),
    }


def _fetch_last_purchase(cur, ck: str, locs: Sequence[str]) -> Optional[Dict[str, Any]]:
    inl, lp = _in_clause(locs)
    cur.execute(
        f"""
        SELECT TOP 1
          CONVERT(VARCHAR(10), CASE WHEN fk.Fatura='*' THEN fk.FatTar ELSE fk.irsaliyeTar END, 120) AS dt,
          LTRIM(RTRIM(ISNULL(fk.FaturaNo, ''))) AS fno,
          LTRIM(RTRIM(ISNULL(fk.BelgeNo, ''))) AS belge,
          CAST(SUM(t.NetTutar) AS FLOAT) AS tutar,
          LTRIM(RTRIM(ISNULL(fk.FaturaPc, 'TL'))) AS pb
        FROM Fatura_Kay fk WITH (NOLOCK)
        CROSS APPLY dbo.kg_ifn_FaturaTutar(fk.BelgeNo, NULL, fk.FaturaPc, NULL) t
        WHERE fk.CariKod = %s
          AND ISNULL(fk.iptal, '') NOT IN ('*', '(') AND fk.Location {inl}
          AND SUBSTRING(ISNULL(fk.FaturaTip, ''), 2, 2) IN ('al', 'si')
        GROUP BY fk.FatTar, fk.irsaliyeTar, fk.Fatura, fk.FaturaNo, fk.BelgeNo, fk.FaturaPc
        HAVING ABS(SUM(t.NetTutar)) > 0.001
        ORDER BY dt DESC
        """,
        (ck, *lp),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        'tarih': row[0], 'fatura_no': row[1], 'belge_no': row[2],
        'tutar': float(row[3] or 0), 'pb': _normalize_pb(row[4]),
    }


def _fetch_verilen_cekler_detay(cur, ck: str, locs: Sequence[str]) -> List[Dict[str, Any]]:
    """P0-aligned verilen çek bilgi paneli — CekTip=F + Cek_Har HarTip=0."""
    inl, lp = _in_clause(locs)
    cur.execute(
        f"""
        SELECT
          c.cekinx,
          LTRIM(RTRIM(ISNULL(c.CekNo, ''))) AS cekno,
          CONVERT(VARCHAR(10), src.verilis, 120) AS duzenleme,
          CONVERT(VARCHAR(10), c.vade, 120) AS vade,
          CAST(c.Tutar AS FLOAT) AS tutar,
          LTRIM(RTRIM(ISNULL(c.ParaCinsi, 'TL'))) AS pb,
          LTRIM(RTRIM(ISNULL(c.SDurum, ''))) AS sdurum,
          LTRIM(RTRIM(ISNULL(c.CekTip, ''))) AS cektip,
          LTRIM(RTRIM(ISNULL(c.Banka, ''))) AS banka,
          LTRIM(RTRIM(ISNULL(c.Sube, ''))) AS sube,
          LTRIM(RTRIM(ISNULL(c.HesapNo, ''))) AS hesap_no,
          LTRIM(RTRIM(ISNULL(c.IBAN, ''))) AS iban,
          LTRIM(RTRIM(ISNULL(c.PortfoyNo, ''))) AS portfoy_no,
          LTRIM(RTRIM(ISNULL(c.Borclu, ''))) AS borclu,
          LTRIM(RTRIM(ISNULL(c.Borclu_CKod, ''))) AS borclu_ckod,
          LTRIM(RTRIM(ISNULL(c.CekAck, ''))) AS cek_ack
        FROM (
          SELECT a.cekinx, a.Tarih AS verilis
          FROM cek_Kart a WITH (NOLOCK)
          WHERE a.CekTip = 'F' AND a.CMKod = %s AND a.CM = 'C'
            AND (a.iptal IS NULL OR a.iptal = 0) AND a.Location {inl}
          UNION ALL
          SELECT a.cekinx, b.Tarih AS verilis
          FROM Cek_Har b WITH (NOLOCK)
          JOIN cek_Kart a WITH (NOLOCK) ON a.Cekinx = b.Cekinx
          WHERE b.HarTip = '0' AND b.cmb = 'C' AND b.cmb_Kod = %s
            AND a.CekTip IN ('M', 'MX') AND a.mycek = 'K'
            AND (a.iptal IS NULL OR a.iptal = 0) AND a.Location {inl}
        ) src
        JOIN cek_Kart c WITH (NOLOCK) ON c.cekinx = src.cekinx
        ORDER BY c.vade, c.CekNo
        """,
        (ck, *lp, ck, *lp),
    )
    cols = [d[0] for d in cur.description]
    out: List[Dict[str, Any]] = []
    for raw in cur.fetchall():
        d = dict(zip(cols, raw))
        sd = d.get('sdurum') or ''
        borclu = (d.get('borclu') or '').strip()
        borclu_ckod = (d.get('borclu_ckod') or '').strip()
        kesideci_label = borclu or borclu_ckod or '—'
        out.append({
            'cekinx': d.get('cekinx'),
            'cekno': d.get('cekno') or '',
            'duzenleme': d.get('duzenleme') or '',
            'vade': d.get('vade') or '',
            'tutar': float(d.get('tutar') or 0),
            'pb': _normalize_pb(d.get('pb')),
            'sdurum': sd,
            'sdurum_label': _SDURUM_MAP.get(sd, sd or '—'),
            'cektip': d.get('cektip') or '',
            'banka': d.get('banka') or '',
            'sube': d.get('sube') or '',
            'hesap_no': d.get('hesap_no') or '',
            'iban': d.get('iban') or '',
            'portfoy_no': d.get('portfoy_no') or '',
            'borclu': borclu,
            'borclu_ckod': borclu_ckod,
            'kesideci_label': kesideci_label,
            'cek_ack': d.get('cek_ack') or '',
            'sahis_firma_note': (
                'Korgün Borclu/Borclu_CKod alanı — tahmin etiketi yok'
                if not borclu and not borclu_ckod else
                f'Keşideci: {kesideci_label}'
            ),
        })
    return out


def _cek_ozet(cekler: List[Dict[str, Any]], today: date) -> Dict[str, Any]:
    aktif = [c for c in cekler if (c.get('sdurum') or '') in ('A', 'BO', '')]
    if not aktif:
        aktif = cekler
    by_pb: Dict[str, float] = {}
    for c in aktif:
        pb = c.get('pb') or 'TRY'
        by_pb[pb] = by_pb.get(pb, 0.0) + float(c.get('tutar') or 0)
    vadeler = [c.get('vade') for c in aktif if c.get('vade')]
    en_yakin = min(vadeler) if vadeler else None
    en_uzak = max(vadeler) if vadeler else None
    return {
        'toplam_aktif': by_pb,
        'adet': len(aktif),
        'en_yakin_vade': en_yakin,
        'en_yakin_gun': _days_until(en_yakin, today),
        'en_uzak_vade': en_uzak,
        'informational_only': True,
        'double_count_note': 'Verilen çek toplamı Net Bakiye hesabına tekrar uygulanmaz.',
    }


def _fetch_nakit_odemeler(cur, ck: str, locs: Sequence[str], today: date) -> Dict[str, Any]:
    inl, lp = _in_clause(locs)
    banka_join = _banka_tutar_join_clause('a.cmbkod', 'a.Location')
    cur.execute(
        f"""
        SELECT dt, kaynak, belge, aciklama, tutar, pb, fis_no FROM (
          SELECT
            CONVERT(VARCHAR(10), a.Tarih, 120) AS dt,
            'Banka' AS kaynak,
            LTRIM(RTRIM(ISNULL(a.EvrakNo, a.FisNo))) AS belge,
            LTRIM(RTRIM(ISNULL(b.Tanim, ''))) AS aciklama,
            CAST(ISNULL(t.Tutar, 0) AS FLOAT) AS tutar,
            LTRIM(RTRIM(ISNULL(t.ParaCinsi, b.ParaCinsi))) AS pb,
            LTRIM(RTRIM(ISNULL(a.FisNo, ''))) AS fis_no
          FROM Banka_Kay a WITH (NOLOCK)
          JOIN Banka_Har b WITH (NOLOCK) ON b.FisNo = a.FisNo
          LEFT JOIN BankaTutar t WITH (NOLOCK)
            {banka_join}
          WHERE a.cmb = 'C' AND a.cmbkod = %s AND a.FisTip = '1'
            AND a.FisTur IN ('1', '2') AND ISNULL(a.iptal, '') NOT IN ('*', '(')
            AND a.Location {inl} AND ISNULL(t.Tutar, 0) > 0.001
          UNION ALL
          SELECT
            CONVERT(VARCHAR(10), k.FisTar, 120) AS dt,
            'C_Fis' AS kaynak,
            LTRIM(RTRIM(ISNULL(k.BelgeNo, k.FisNo))) AS belge,
            LTRIM(RTRIM(ISNULL(h.tanim, ''))) AS aciklama,
            CAST(ISNULL(t.NetTutar, 0) AS FLOAT) AS tutar,
            LTRIM(RTRIM(ISNULL(t.ParaCinsi, h.ParaCinsi))) AS pb,
            LTRIM(RTRIM(ISNULL(k.FisNo, ''))) AS fis_no
          FROM C_Fis_Kay k WITH (NOLOCK)
          JOIN C_Fis_Har h WITH (NOLOCK) ON h.FisNo = k.FisNo
          LEFT JOIN CFisTutar t WITH (NOLOCK)
            ON t.FisNo = h.FisNo AND t.FisHarinx = h.Fisinx AND t.ParaCinsi = h.ParaCinsi
          WHERE h.cbpg = %s AND k.Bolum = 'K' AND k.FisTip IN ('NO', 'HF')
            AND ISNULL(k.iptal, '') NOT IN ('*', '(') AND k.Location {inl}
            AND ISNULL(t.NetTutar, 0) > 0.001
          UNION ALL
          SELECT
            CONVERT(VARCHAR(10), k.FisTar, 120) AS dt,
            'Dekont' AS kaynak,
            LTRIM(RTRIM(ISNULL(k.BelgeNo, k.FisNo))) AS belge,
            LTRIM(RTRIM(ISNULL(h.tanim, ''))) AS aciklama,
            CAST(ISNULL(t.NetTutar, 0) AS FLOAT) AS tutar,
            LTRIM(RTRIM(ISNULL(t.ParaCinsi, h.ParaCinsi))) AS pb,
            LTRIM(RTRIM(ISNULL(k.FisNo, ''))) AS fis_no
          FROM C_Fis_Kay k WITH (NOLOCK)
          JOIN C_Fis_Har h WITH (NOLOCK) ON h.FisNo = k.FisNo
          LEFT JOIN CFisTutar t WITH (NOLOCK)
            ON t.FisNo = h.FisNo AND t.FisHarinx = h.Fisinx AND t.ParaCinsi = h.ParaCinsi
          WHERE h.cbpg = %s AND k.Bolum = 'C' AND k.FisTip = 'BD'
            AND ISNULL(k.iptal, '') NOT IN ('*', '(') AND k.Location {inl}
            AND ISNULL(t.NetTutar, 0) > 0.001
        ) x ORDER BY dt DESC, tutar DESC
        """,
        (ck, *lp, ck, *lp, ck, *lp),
    )
    cols = [d[0] for d in cur.description]
    rows = []
    for raw in cur.fetchall():
        d = dict(zip(cols, raw))
        rows.append({
            'tarih': d.get('dt'),
            'odeme_tipi': d.get('kaynak'),
            'belge_no': d.get('belge'),
            'aciklama': d.get('aciklama') or '',
            'tutar': float(d.get('tutar') or 0),
            'pb': _normalize_pb(d.get('pb')),
            'fis_no': d.get('fis_no') or '',
            'banka_kasa': 'Banka' if d.get('kaynak') == 'Banka' else 'Cari Fiş',
        })

    d30 = today - timedelta(days=30)
    d90 = today - timedelta(days=90)
    tot_all: Dict[str, float] = {}
    tot_30: Dict[str, float] = {}
    tot_90: Dict[str, float] = {}
    for r in rows:
        pb = r['pb']
        try:
            dt = datetime.strptime(r['tarih'][:10], '%Y-%m-%d').date()
        except (ValueError, TypeError):
            continue
        tot_all[pb] = tot_all.get(pb, 0.0) + r['tutar']
        if dt >= d90:
            tot_90[pb] = tot_90.get(pb, 0.0) + r['tutar']
        if dt >= d30:
            tot_30[pb] = tot_30.get(pb, 0.0) + r['tutar']

    son = rows[0] if rows else None
    return {
        'rows': rows,
        'ozet': {
            'son_odeme': son,
            'toplam': tot_all,
            'son_30_gun': tot_30,
            'son_90_gun': tot_90,
            'kalem': len(rows),
        },
        'source': 'Banka FisTip=1 + C_Fis NO/HF',
    }


def _fetch_alis_faturalari(cur, ck: str, locs: Sequence[str]) -> Dict[str, Any]:
    inl, lp = _in_clause(locs)
    cur.execute(
        f"""
        SELECT
          CONVERT(VARCHAR(10), CASE WHEN fk.Fatura='*' THEN fk.FatTar ELSE fk.irsaliyeTar END, 120) AS dt,
          LTRIM(RTRIM(ISNULL(fk.FaturaNo, ''))) AS fatura_no,
          LTRIM(RTRIM(ISNULL(fk.BelgeNo, ''))) AS belge_no,
          CONVERT(VARCHAR(10), fk.Vade, 120) AS vade,
          LTRIM(RTRIM(ISNULL(fk.FaturaTip, ''))) AS ftip,
          CAST(SUM(t.NetTutar) AS FLOAT) AS tutar,
          LTRIM(RTRIM(ISNULL(fk.FaturaPc, 'TL'))) AS pb,
          CASE WHEN fk.Fatura='*' THEN 'Açık' ELSE 'Kapalı' END AS durum
        FROM Fatura_Kay fk WITH (NOLOCK)
        CROSS APPLY dbo.kg_ifn_FaturaTutar(fk.BelgeNo, NULL, fk.FaturaPc, NULL) t
        WHERE fk.CariKod = %s AND ISNULL(fk.iptal, '') NOT IN ('*', '(')
          AND fk.Location {inl}
          AND SUBSTRING(ISNULL(fk.FaturaTip, ''), 2, 2) IN ('al', 'si')
        GROUP BY fk.FatTar, fk.irsaliyeTar, fk.Fatura, fk.FaturaNo, fk.BelgeNo,
                 fk.Vade, fk.FaturaTip, fk.FaturaPc
        HAVING ABS(SUM(t.NetTutar)) > 0.001
        ORDER BY dt DESC
        """,
        (ck, *lp),
    )
    cols = [d[0] for d in cur.description]
    rows = []
    for raw in cur.fetchall():
        d = dict(zip(cols, raw))
        rows.append({
            'tarih': d.get('dt'),
            'fatura_no': d.get('fatura_no') or '',
            'belge_no': d.get('belge_no') or '',
            'vade': d.get('vade') or '',
            'tutar': float(d.get('tutar') or 0),
            'pb': _normalize_pb(d.get('pb')),
            'durum': d.get('durum') or '',
            'fatura_tip': d.get('ftip') or '',
        })
    return {'rows': rows, 'kalem': len(rows), 'source': 'Fatura_Kay + kg_ifn_FaturaTutar'}


def build_popup_summary(ledger: Dict[str, Any], today: Optional[date] = None) -> Dict[str, Any]:
    """Özet sekmesi — ledger + tek cari read-model.

    P1.3 FAZ2: Enrichment scope = company_physical_locations(location).
    Ledger ile aynı company finance scope → list ↔ popup parity + cross-company izolasyon.
    """
    today = today or date.today()
    loc = ledger.get('location', '')
    ck = ledger.get('cari_kod', '')
    locs = _company_locs(loc)
    fn_net = float(ledger.get('fn_net') or 0)

    con = _baglan()
    try:
        cur = con.cursor()
        last_pay = _fetch_last_payment(cur, ck, locs)
        last_cek = _fetch_last_cek(cur, ck, locs)
        last_pur = _fetch_last_purchase(cur, ck, locs)
        cekler = _fetch_verilen_cekler_detay(cur, ck, locs)
    finally:
        con.close()

    cek_oz = _cek_ozet(cekler, today)
    sem = business_semantic(fn_net)

    # Son Finansal Aksiyon — liste ile aynı semantik (max nakit/dekont vs çek)
    cash_date = last_pay.get('tarih') if last_pay else None
    cek_date = last_cek.get('verilis') if last_cek else None
    if cash_date and cek_date:
        fa_is_cek = cek_date >= cash_date
    elif cek_date:
        fa_is_cek = True
    else:
        fa_is_cek = False
    if fa_is_cek and last_cek:
        son_finansal = {
            'tarih': last_cek.get('verilis'),
            'tutar': last_cek.get('tutar'),
            'pb': last_cek.get('pb'),
            'tur': 'Çek',
            'kaynak': 'Cek',
            'is_cek': True,
        }
    elif last_pay:
        son_finansal = {
            'tarih': last_pay.get('tarih'),
            'tutar': last_pay.get('tutar'),
            'pb': last_pay.get('pb'),
            'tur': last_pay.get('kaynak') or 'Ödeme',
            'kaynak': last_pay.get('kaynak'),
            'is_cek': False,
        }
    else:
        son_finansal = None

    return {
        'canli_borc': ledger.get('fn_borc'),
        'canli_alacak': ledger.get('fn_alacak'),
        'net_bakiye': fn_net,
        'para_birimi': ledger.get('para_birimi'),
        'business': sem,
        'son_odeme': last_pay,
        'son_cek': last_cek,
        'son_finansal_aksiyon': son_finansal,
        'son_alim': last_pur,
        'verilen_cek_toplami': cek_oz.get('toplam_aktif'),
        'verilen_cek_adet': cek_oz.get('adet'),
        'en_yakin_cek_vade': cek_oz.get('en_yakin_vade'),
        'en_yakin_cek_gun': cek_oz.get('en_yakin_gun'),
        'cek_ozet': cek_oz,
    }


def build_cari_hareket_popup(location: str, cari_kod: str) -> Dict[str, Any]:
    """İlk açılış — ledger + özet (ağır sekmeler lazy)."""
    ledger = build_cari_hareket_ledger(location, cari_kod)
    if not ledger.get('ok'):
        return ledger
    summary = build_popup_summary(ledger)
    try:
        from modules.finans.services.odeme_plani_enrichment_service import fetch_row_enrichment
    except ImportError:
        from app.modules.finans.services.odeme_plani_enrichment_service import fetch_row_enrichment
    enrich = fetch_row_enrichment(location, cari_kod)
    summary['enrichment'] = enrich
    summary['son_temas'] = enrich['contact']
    summary['odeme_sozu'] = enrich['promise']
    summary['anlasma_vade'] = enrich['term']
    ledger['summary'] = summary
    ledger['business_semantic'] = summary.get('business')
    ledger['tabs_available'] = ['ozet', 'tum', 'nakit', 'cekler', 'alis']
    ledger['lazy_tabs'] = ['nakit', 'cekler', 'alis']
    return ledger


def fetch_popup_tab(location: str, cari_kod: str, tab: str) -> Dict[str, Any]:
    """Lazy tab yükleme — modal cache için.

    P1.3 FAZ2: company_physical_locations — build_popup_summary ile aynı scope.
    """
    loc = (location or '').strip().upper()
    ck = (cari_kod or '').strip()
    locs = _company_locs(loc)
    today = date.today()

    con = _baglan()
    try:
        cur = con.cursor()
        if tab == 'nakit':
            data = _fetch_nakit_odemeler(cur, ck, locs, today)
        elif tab == 'cekler':
            cekler = _fetch_verilen_cekler_detay(cur, ck, locs)
            data = {'rows': cekler, 'ozet': _cek_ozet(cekler, today), 'source': 'P0-aligned verilen cek'}
        elif tab == 'alis':
            data = _fetch_alis_faturalari(cur, ck, locs)
        else:
            return {'ok': False, 'error': f'Geçersiz tab: {tab}'}
    finally:
        con.close()

    return {'ok': True, 'tab': tab, 'location': loc, 'cari_kod': ck, **data}
