# -*- coding: utf-8 -*-
"""
Korgun — Biten Prosesler (salt okunur home özet)

Kaynak: Solariz22 / Urt_con_gch UNION ALL Urtx_con_gch
        + Urt_Emir / Urtx_Emir.Location (COALESCE)
Kural: Cikan > 0 AND EndTarih IS NOT NULL AND Birim = 'CIFT'
       Excel "Biten" = SUM(Cikan) (SELECT kanit 33595)
Lokasyon: whitelist (yalniz uretim sahalari)
Yazma yok.

SELECT kanit (2026-07-28, Siparis 33595 / Emir 110362-110367):
- Urt_con_gch: 0 satir
- Urtx_con_gch: Emir+Proses SUM(Cikan)=480 = Excel Biten
- Urt_Emir: yok; Urtx_Emir.Location=SA001
Bu nedenle yalniz canli tablo okuyan sorgu Temmuz Monta/Temizleme=0 uretiyordu.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

VALID_PERIODS = ('bugun', 'dun', 'hafta', 'ay')

ALLOWED_PRODUCTION_LOCATIONS = (
    'YPM03',   # Pera - Yari Mamul Depo
    'SU002',   # Yari Mamul Depo
    'SU001',   # Uretim Saha
    'SARGE',   # Arge Urun
    'YP001',   # Monta CIFT (canli + arsiv)
    'SA001',   # Monta + Temizleme CIFT (Urtx_Emir kanit)
)

EXCLUDED_LOCATION_EXAMPLES = (
    'YP002 — Pera Hammadde (CIFT proses kapanış ana akış değil)',
    'SH001 — Hammadde Depo',
    'SD002 — Solariz Lojistik Depo',
    'SE001 — E-Ticaret',
    'YN001 — Nexgen Kimya',
)

# Ana sayfa kartında dönem 0 olsa bile erişilebilir kalsın (Proses_M kodları).
# Tüm master zorunlu değil; operasyonel önemli prosesler.
ALWAYS_VISIBLE_PROSES = (
    '28',  # Monta Baslayacak (Excel ayri satir; Monta ile birlestirilmez)
    '30',  # Monta
    '35',  # Temizleme
    '26',  # Enjeksiyon
    '02',  # Kesim
    '04',  # Silte
    '08',  # Digital
    '40',  # Planlama-Depo
    '12',  # Sayim-Kontrol
)

# Kararli grup anahtarlari — kodlar SELECT ile kanitlanmis.
# 28 ve 30 AYRI grup; otomatik Montaj toplami yok.
PROCESS_GROUPS = {
    'monta_baslayacak': {
        'codes': ('28',),
        'label_aliases': ('monta baslayacak', 'monta başlayacak', 'montabaslayacak'),
    },
    'montaj': {
        'codes': ('30',),
        'label_aliases': ('montaj',),
    },
    'temizleme': {
        'codes': ('35',),
        'label_aliases': ('temizleme',),
    },
    'enjeksiyon': {
        'codes': ('26',),
        'label_aliases': ('enjeksiyon',),
    },
    'kesim': {
        'codes': ('02', '2'),
        'label_aliases': ('kesim',),
    },
    'silte': {
        'codes': ('04', '4'),
        'label_aliases': ('şilte', 'silte'),
    },
    'digital': {
        'codes': ('08', '8'),
        'label_aliases': ('digital', 'serigraf'),
    },
    'lazer': {
        'codes': (),
        'label_aliases': ('lazer',),
    },
    'planlama_depo': {
        'codes': ('40',),
        'label_aliases': ('planlama-depo', 'planlama depo', 'planlama'),
    },
}


def resolve_proses_group(proses_kodu, proses_adi=None):
    """proses_kodu öncelikli; ad yalnız alias yedek. Bilinmeyen → None."""
    kod = str(proses_kodu or '').strip()
    ad = (proses_adi or '').strip().lower()
    for key, meta in PROCESS_GROUPS.items():
        codes = {str(c).strip() for c in meta.get('codes') or ()}
        if kod in codes:
            return key
        for alias in meta.get('label_aliases') or ():
            if ad and alias in ad:
                return key
    return None


class KorgunBitenBagError(Exception):
    def __init__(self, message='Korgun bağlantısı kurulamadı'):
        self.message = message
        super().__init__(message)


class KorgunBitenPeriodError(ValueError):
    pass


_BASE_WHERE_G = """
    g.Cikan > 0
    AND g.EndTarih IS NOT NULL
    AND UPPER(LTRIM(RTRIM(ISNULL(g.Birim, '')))) = 'CIFT'
"""

# Canli + arsiv hareket (Excel/Hedef ile ayni kaynak modeli)
_GCH_UNION = """(
    SELECT EmirNo, Proses, AltProses, Birim, Cikan, Giren, Fire,
           EndTarih, StartTarih, FisNo, SKOD, Personel, WMakNum
    FROM Urt_con_gch WITH (NOLOCK)
    UNION ALL
    SELECT EmirNo, Proses, AltProses, Birim, Cikan, Giren, Fire,
           EndTarih, StartTarih, FisNo, SKOD, Personel, WMakNum
    FROM Urtx_con_gch WITH (NOLOCK)
) g"""

_EMIR_JOINS = """
    LEFT JOIN Urt_Emir ue WITH (NOLOCK) ON ue.EmirNo = g.EmirNo
    LEFT JOIN Urtx_Emir uxe WITH (NOLOCK) ON uxe.EmirNo = g.EmirNo
"""

_LOC_EXPR = "LTRIM(RTRIM(COALESCE(ue.Location, uxe.Location, '')))"

_PROSES_JOIN = """
    LEFT JOIN Proses_M pm WITH (NOLOCK)
      ON LTRIM(RTRIM(CAST(pm.Pro AS VARCHAR(20))))
       = LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20))))
"""


def _ymd(d):
    return d.isoformat()


def _num(v):
    try:
        f = float(v or 0)
        return int(f) if f == int(f) else f
    except Exception:
        return 0


def _baglan():
    try:
        from modules.common.korgun import _baglan as _k_baglan
        return _k_baglan()
    except Exception as e:
        raise KorgunBitenBagError('Korgun bağlantısı kurulamadı') from e


def location_scope_meta():
    return {
        'mode': 'whitelist',
        'source': 'COALESCE(Urt_Emir.Location, Urtx_Emir.Location)',
        'movement_source': 'Urt_con_gch UNION ALL Urtx_con_gch',
        'quantity_field': 'Cikan',
        'excel_biten_equiv': 'SUM(Cikan)',
        'included': list(ALLOWED_PRODUCTION_LOCATIONS),
        'excluded_examples': list(EXCLUDED_LOCATION_EXAMPLES),
    }


def _loc_in_sql():
    """Parametreli IN listesi için (%s,%s,...) ve tuple."""
    locs = list(ALLOWED_PRODUCTION_LOCATIONS)
    if not locs:
        raise KorgunBitenBagError('Üretim lokasyonu whitelist boş')
    ph = ','.join(['%s'] * len(locs))
    return ph, tuple(locs)


def period_date_range(period, today=None):
    today = today or date.today()
    p = (period or 'bugun').strip().lower()
    if p not in VALID_PERIODS:
        raise KorgunBitenPeriodError('gecersiz_period')
    if p == 'bugun':
        return today, today
    if p == 'dun':
        d = today - timedelta(days=1)
        return d, d
    if p == 'hafta':
        return today - timedelta(days=6), today
    return today.replace(day=1), today


def _count_emir_proses(cur, bas, bit):
    ph, locs = _loc_in_sql()
    cur.execute(
        f"""
        SELECT COUNT(*) FROM (
            SELECT g.EmirNo, LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20)))) AS Proses
            FROM {_GCH_UNION}
            {_EMIR_JOINS}
            WHERE {_BASE_WHERE_G}
              AND CAST(g.EndTarih AS DATE) >= CAST(%s AS DATE)
              AND CAST(g.EndTarih AS DATE) <= CAST(%s AS DATE)
              AND {_LOC_EXPR} IN ({ph})
            GROUP BY g.EmirNo, LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20))))
        ) t
        """,
        (_ymd(bas), _ymd(bit)) + locs,
    )
    row = cur.fetchone()
    return int(row[0] or 0) if row else 0


def _period_summary_counts(cur, bas, bit):
    ph, locs = _loc_in_sql()
    cur.execute(
        f"""
        SELECT
            COALESCE(SUM(ISNULL(g.Cikan, 0)), 0) AS toplam_cift,
            COUNT(DISTINCT g.EmirNo) AS biten_emir_sayisi,
            COUNT(DISTINCT LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20))))) AS proses_turu_sayisi
        FROM {_GCH_UNION}
        {_EMIR_JOINS}
        WHERE {_BASE_WHERE_G}
          AND CAST(g.EndTarih AS DATE) >= CAST(%s AS DATE)
          AND CAST(g.EndTarih AS DATE) <= CAST(%s AS DATE)
          AND {_LOC_EXPR} IN ({ph})
        """,
        (_ymd(bas), _ymd(bit)) + locs,
    )
    row = cur.fetchone()
    cols = [d[0] for d in cur.description]
    d = dict(zip(cols, row)) if row else {}
    return {
        'toplam_cift': _num(d.get('toplam_cift')),
        'biten_emir_sayisi': int(d.get('biten_emir_sayisi') or 0),
        'proses_turu_sayisi': int(d.get('proses_turu_sayisi') or 0),
        'biten_proses_sayisi': _count_emir_proses(cur, bas, bit),
    }


def _proses_toplamlari(cur, bas, bit):
    ph, locs = _loc_in_sql()
    cur.execute(
        f"""
        SELECT
            LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20)))) AS proses_kodu,
            ISNULL(MAX(pm.Tanim), LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20))))) AS proses_adi,
            SUM(ISNULL(g.Cikan, 0)) AS toplam_cift,
            COUNT(DISTINCT g.EmirNo) AS emir_sayisi,
            COUNT(DISTINCT CAST(g.EmirNo AS VARCHAR(20)) + '|' + LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20))))) AS biten_proses_sayisi
        FROM {_GCH_UNION}
        {_EMIR_JOINS}
        {_PROSES_JOIN}
        WHERE {_BASE_WHERE_G}
          AND CAST(g.EndTarih AS DATE) >= CAST(%s AS DATE)
          AND CAST(g.EndTarih AS DATE) <= CAST(%s AS DATE)
          AND {_LOC_EXPR} IN ({ph})
        GROUP BY LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20))))
        ORDER BY SUM(ISNULL(g.Cikan, 0)) DESC
        """,
        (_ymd(bas), _ymd(bit)) + locs,
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    toplam = sum(float(r.get('toplam_cift') or 0) for r in rows)
    out = []
    for r in rows:
        cift = _num(r.get('toplam_cift'))
        pay = round((float(cift) / toplam) * 100, 1) if toplam > 0 else 0.0
        kod = str(r.get('proses_kodu') or '')
        adi = (r.get('proses_adi') or '').strip() or kod
        out.append({
            'proses_kodu': kod,
            'proses_adi': adi,
            'group_key': resolve_proses_group(kod, adi),
            'toplam_cift': cift,
            'emir_sayisi': int(r.get('emir_sayisi') or 0),
            'biten_proses_sayisi': int(r.get('biten_proses_sayisi') or 0),
            'pay_yuzde': pay,
            'birim': 'CIFT',
        })
    return out, _num(toplam)


def _proses_kodlari_lookback(cur, bas, bit):
    """Whitelist lokasyonlarda aralıkta CIFT bitişi olan proses kodları."""
    ph, locs = _loc_in_sql()
    cur.execute(
        f"""
        SELECT DISTINCT LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20)))) AS proses_kodu
        FROM {_GCH_UNION}
        {_EMIR_JOINS}
        WHERE {_BASE_WHERE_G}
          AND CAST(g.EndTarih AS DATE) >= CAST(%s AS DATE)
          AND CAST(g.EndTarih AS DATE) <= CAST(%s AS DATE)
          AND {_LOC_EXPR} IN ({ph})
        """,
        (_ymd(bas), _ymd(bit)) + locs,
    )
    return [str(r[0]).strip() for r in cur.fetchall() if r and r[0] is not None]


def _build_proses_kartlari(cur, bas, bit, today):
    """
    Seçili dönem miktarları + lookback/önemli prosesler (0 olabilir).
    Sıra: dönem çift DESC, sonra ad.
    """
    period_list, period_toplam = _proses_toplamlari(cur, bas, bit)
    by_kod = {p['proses_kodu']: dict(p) for p in period_list}

    look_bas = min(bas, today - timedelta(days=90), today.replace(day=1))
    for kod in _proses_kodlari_lookback(cur, look_bas, today):
        if kod not in by_kod:
            adi = _proses_adi(cur, kod)
            by_kod[kod] = {
                'proses_kodu': kod,
                'proses_adi': adi,
                'group_key': resolve_proses_group(kod, adi),
                'toplam_cift': 0,
                'emir_sayisi': 0,
                'biten_proses_sayisi': 0,
                'pay_yuzde': 0.0,
                'birim': 'CIFT',
            }

    for kod in ALWAYS_VISIBLE_PROSES:
        kod = str(kod).strip()
        if kod not in by_kod:
            adi = _proses_adi(cur, kod)
            by_kod[kod] = {
                'proses_kodu': kod,
                'proses_adi': adi,
                'group_key': resolve_proses_group(kod, adi),
                'toplam_cift': 0,
                'emir_sayisi': 0,
                'biten_proses_sayisi': 0,
                'pay_yuzde': 0.0,
                'birim': 'CIFT',
            }
        else:
            # ad güncelle (pin isimleri Proses_M)
            adi = _proses_adi(cur, kod) or by_kod[kod]['proses_adi']
            by_kod[kod]['proses_adi'] = adi
            by_kod[kod]['group_key'] = resolve_proses_group(kod, adi)

    toplam = float(period_toplam or 0)
    out = list(by_kod.values())
    for p in out:
        cift = float(p.get('toplam_cift') or 0)
        p['pay_yuzde'] = round((cift / toplam) * 100, 1) if toplam > 0 else 0.0
        if not p.get('group_key'):
            p['group_key'] = resolve_proses_group(p.get('proses_kodu'), p.get('proses_adi'))
    out.sort(key=lambda p: (-float(p.get('toplam_cift') or 0), (p.get('proses_adi') or '').lower()))
    return out, _num(toplam)


def _chart_from_proses(proses_list, top_n=6):
    if not proses_list:
        return []
    top = proses_list[:top_n]
    rest = proses_list[top_n:]
    chart = [{
        'proses_kodu': p['proses_kodu'],
        'proses_adi': p['proses_adi'],
        'toplam_cift': p['toplam_cift'],
        'emir_sayisi': p['emir_sayisi'],
        'pay_yuzde': p['pay_yuzde'],
    } for p in top]
    if rest:
        diger = sum(float(p.get('toplam_cift') or 0) for p in rest)
        if diger > 0:
            chart.append({
                'proses_kodu': '_DIGER',
                'proses_adi': 'Diğer',
                'toplam_cift': _num(diger),
                'emir_sayisi': sum(int(p.get('emir_sayisi') or 0) for p in rest),
                'pay_yuzde': round((float(diger) / max(sum(float(x.get('toplam_cift') or 0) for x in proses_list), 1)) * 100, 1),
            })
    return chart


def _son_bitenler(cur, bas, bit, limit=5, proses_kodu=None):
    n = max(1, min(int(limit or 5), 20))
    ph, locs = _loc_in_sql()
    params = [_ymd(bas), _ymd(bit)]
    proses_sql = ''
    if proses_kodu:
        proses_sql = " AND LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20)))) = %s "
        params.append(str(proses_kodu).strip())
    params.extend(locs)
    sql = (
        "SELECT TOP " + str(n) + f"""
            CAST(g.EmirNo AS VARCHAR(20)) AS emir_no,
            CAST(MAX(g.FisNo) AS VARCHAR(20)) AS siparis_no,
            LTRIM(RTRIM(ISNULL(MAX(ck.CName), ''))) AS cari,
            LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20)))) AS proses_kodu,
            ISNULL(MAX(pm.Tanim), LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20))))) AS proses_adi,
            SUM(ISNULL(g.Cikan, 0)) AS miktar,
            'CIFT' AS birim,
            MAX(g.EndTarih) AS bitis_zamani
        FROM {_GCH_UNION}
        {_EMIR_JOINS}
        {_PROSES_JOIN}
        LEFT JOIN Siparis_Kay sk WITH (NOLOCK) ON sk.SipNo = g.FisNo
        LEFT JOIN Cari_Kart ck WITH (NOLOCK) ON ck.CKod = sk.CariKod
        WHERE {_BASE_WHERE_G}
          AND CAST(g.EndTarih AS DATE) >= CAST(%s AS DATE)
          AND CAST(g.EndTarih AS DATE) <= CAST(%s AS DATE)
          {proses_sql}
          AND {_LOC_EXPR} IN ({ph})
        GROUP BY g.EmirNo, LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20))))
        ORDER BY MAX(g.EndTarih) DESC
        """
    )
    cur.execute(sql, tuple(params))
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        bt = d.get('bitis_zamani')
        if isinstance(bt, datetime):
            bitis = bt.strftime('%Y-%m-%dT%H:%M:%S')
        elif bt:
            bitis = str(bt)[:19].replace(' ', 'T')
        else:
            bitis = None
        out.append({
            'emir_no': str(d.get('emir_no') or ''),
            'siparis_no': str(d.get('siparis_no') or '') if d.get('siparis_no') is not None else '',
            'cari': (d.get('cari') or '').strip() or '-',
            'proses_kodu': str(d.get('proses_kodu') or ''),
            'proses_adi': (d.get('proses_adi') or '').strip() or str(d.get('proses_kodu') or ''),
            'miktar': _num(d.get('miktar')),
            'birim': 'CIFT',
            'bitis_zamani': bitis,
        })
    return out


def _proses_kpi_window(cur, proses_kodu, bas, bit):
    ph, locs = _loc_in_sql()
    cur.execute(
        f"""
        SELECT
            COALESCE(SUM(ISNULL(g.Cikan, 0)), 0) AS cift,
            COUNT(DISTINCT g.EmirNo) AS emir
        FROM {_GCH_UNION}
        {_EMIR_JOINS}
        WHERE {_BASE_WHERE_G}
          AND CAST(g.EndTarih AS DATE) >= CAST(%s AS DATE)
          AND CAST(g.EndTarih AS DATE) <= CAST(%s AS DATE)
          AND LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20)))) = %s
          AND {_LOC_EXPR} IN ({ph})
        """,
        (_ymd(bas), _ymd(bit), str(proses_kodu).strip()) + locs,
    )
    row = cur.fetchone()
    return _num(row[0] if row else 0), int(row[1] or 0) if row else 0


def _gunluk_seri(cur, proses_kodu, bas, bit):
    ph, locs = _loc_in_sql()
    cur.execute(
        f"""
        SELECT
            CONVERT(date, g.EndTarih) AS tarih,
            COALESCE(SUM(ISNULL(g.Cikan, 0)), 0) AS toplam_cift,
            COUNT(DISTINCT g.EmirNo) AS emir_sayisi
        FROM {_GCH_UNION}
        {_EMIR_JOINS}
        WHERE {_BASE_WHERE_G}
          AND CAST(g.EndTarih AS DATE) >= CAST(%s AS DATE)
          AND CAST(g.EndTarih AS DATE) <= CAST(%s AS DATE)
          AND LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20)))) = %s
          AND {_LOC_EXPR} IN ({ph})
        GROUP BY CONVERT(date, g.EndTarih)
        """,
        (_ymd(bas), _ymd(bit), str(proses_kodu).strip()) + locs,
    )
    cols = [d[0] for d in cur.description]
    by_day = {}
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        key = d['tarih']
        if hasattr(key, 'isoformat'):
            key = key.isoformat()
        else:
            key = str(key)[:10]
        by_day[key] = {
            'tarih': key,
            'toplam_cift': _num(d.get('toplam_cift')),
            'emir_sayisi': int(d.get('emir_sayisi') or 0),
        }
    # eksik günleri 0 ile doldur
    out = []
    d = bas
    while d <= bit:
        k = _ymd(d)
        out.append(by_day.get(k, {'tarih': k, 'toplam_cift': 0, 'emir_sayisi': 0}))
        d += timedelta(days=1)
    return out


def _proses_adi(cur, proses_kodu):
    cur.execute(
        """
        SELECT TOP 1 ISNULL(Tanim, %s) FROM Proses_M WITH (NOLOCK)
        WHERE LTRIM(RTRIM(CAST(Pro AS VARCHAR(20)))) = %s
        """,
        (str(proses_kodu).strip(), str(proses_kodu).strip()),
    )
    row = cur.fetchone()
    if row and row[0]:
        return str(row[0]).strip()
    return str(proses_kodu).strip()


def get_home_biten_prosesler(period='bugun', today=None):
    today = today or date.today()
    period = (period or 'bugun').strip().lower()
    bas, bit = period_date_range(period, today)

    con = None
    try:
        con = _baglan()
        cur = con.cursor()
        try:
            counts = _period_summary_counts(cur, bas, bit)
            proses_list, _ = _build_proses_kartlari(cur, bas, bit, today)
            # KPI "en yoğun" yalnız seçili dönemde miktarı > 0 olanlardan
            period_only = [p for p in proses_list if float(p.get('toplam_cift') or 0) > 0]
            toplam_cift = counts['toplam_cift']
            en = None
            if period_only:
                top = period_only[0]
                en = {
                    'proses_kodu': top['proses_kodu'],
                    'proses_adi': top['proses_adi'],
                    'toplam_cift': top['toplam_cift'],
                }
            chart = _chart_from_proses(period_only or proses_list, 8)
            son = _son_bitenler(cur, bas, bit, 5)

            dun = today - timedelta(days=1)
            hafta_bas = today - timedelta(days=6)
            ay_bas = today.replace(day=1)
            period_counts = {
                'bugun': _count_emir_proses(cur, today, today),
                'dun': _count_emir_proses(cur, dun, dun),
                'hafta': _count_emir_proses(cur, hafta_bas, today),
                'ay': _count_emir_proses(cur, ay_bas, today),
            }
            # Ana sayfa üst KPI (çift) — seçili dönemden bağımsız
            qty_bugun = _period_summary_counts(cur, today, today)['toplam_cift']
            qty_hafta = _period_summary_counts(cur, hafta_bas, today)['toplam_cift']
            qty_ay = _period_summary_counts(cur, ay_bas, today)['toplam_cift']
            qty_by_period = {
                'bugun_cift': qty_bugun,
                'hafta_cift': qty_hafta,
                'ay_cift': qty_ay,
            }
        finally:
            try:
                cur.close()
            except Exception:
                pass
    except KorgunBitenPeriodError:
        raise
    except KorgunBitenBagError:
        raise
    except Exception as e:
        raise KorgunBitenBagError('Korgun bağlantısı kurulamadı') from e
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass

    return {
        'ok': True,
        'generated_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'source': 'Korgun Solariz22 / Urt_con_gch UNION ALL Urtx_con_gch',
        'period': period,
        'period_range': {'bas': _ymd(bas), 'bit': _ymd(bit)},
        'location_scope': location_scope_meta(),
        'count_unit': 'emir_proses',
        'quantity_unit': 'cift',
        'summary': {
            'toplam_cift': toplam_cift,
            'proses_turu_sayisi': counts['proses_turu_sayisi'],
            'biten_emir_sayisi': counts['biten_emir_sayisi'],
            'biten_proses_sayisi': counts['biten_proses_sayisi'],
            'en_yogun_proses': en,
            'bugun': period_counts['bugun'],
            'dun': period_counts['dun'],
            'hafta': period_counts['hafta'],
            'ay': period_counts['ay'],
        },
        'qty_by_period': qty_by_period,
        'proses_toplamlari': proses_list,
        'proses_kartlari': proses_list,
        'chart': chart,
        'son_bitenler': son,
        'proses_dagilimi': [
            {
                'proses_kodu': p['proses_kodu'],
                'proses_adi': p['proses_adi'],
                'adet': p['biten_proses_sayisi'],
                'toplam_cift': p['toplam_cift'],
            }
            for p in proses_list[:12]
        ],
    }


def get_proses_detay(proses_kodu, period='hafta', chart_mode='hafta', today=None):
    """Seçilen proses için bugün/dün/hafta/ay KPI + günlük seri + son emirler."""
    today = today or date.today()
    period = (period or 'hafta').strip().lower()
    if period not in VALID_PERIODS:
        raise KorgunBitenPeriodError('gecersiz_period')
    chart_mode = (chart_mode or 'hafta').strip().lower()
    if chart_mode not in ('hafta', 'ay'):
        chart_mode = 'hafta'
    kod = str(proses_kodu or '').strip()
    if not kod or kod == '_DIGER':
        raise KorgunBitenPeriodError('gecersiz_proses')

    bas_list, bit_list = period_date_range(period, today)
    dun = today - timedelta(days=1)
    hafta_bas = today - timedelta(days=6)
    ay_bas = today.replace(day=1)
    if chart_mode == 'ay':
        chart_bas, chart_bit = ay_bas, today
    else:
        chart_bas, chart_bit = hafta_bas, today

    con = None
    try:
        con = _baglan()
        cur = con.cursor()
        try:
            adi = _proses_adi(cur, kod)
            b_cift, b_emir = _proses_kpi_window(cur, kod, today, today)
            d_cift, d_emir = _proses_kpi_window(cur, kod, dun, dun)
            h_cift, h_emir = _proses_kpi_window(cur, kod, hafta_bas, today)
            a_cift, a_emir = _proses_kpi_window(cur, kod, ay_bas, today)
            seri = _gunluk_seri(cur, kod, chart_bas, chart_bit)
            son = _son_bitenler(cur, bas_list, bit_list, 5, proses_kodu=kod)
        finally:
            try:
                cur.close()
            except Exception:
                pass
    except KorgunBitenPeriodError:
        raise
    except KorgunBitenBagError:
        raise
    except Exception as e:
        raise KorgunBitenBagError('Korgun bağlantısı kurulamadı') from e
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass

    return {
        'ok': True,
        'generated_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'source': 'Korgun Solariz22 / Urt_con_gch UNION ALL Urtx_con_gch',
        'location_scope': location_scope_meta(),
        'period': period,
        'period_range': {'bas': _ymd(bas_list), 'bit': _ymd(bit_list)},
        'chart_mode': chart_mode,
        'chart_range': {'bas': _ymd(chart_bas), 'bit': _ymd(chart_bit)},
        'proses': {'kod': kod, 'ad': adi},
        'kpi': {
            'bugun_cift': b_cift,
            'bugun_emir': b_emir,
            'dun_cift': d_cift,
            'dun_emir': d_emir,
            'hafta_cift': h_cift,
            'hafta_emir': h_emir,
            'ay_cift': a_cift,
            'ay_emir': a_emir,
        },
        'gunluk_seri': seri,
        'son_biten_emirler': son,
    }
