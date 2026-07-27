# -*- coding: utf-8 -*-
"""Cari Kart — Genel Durum (işlem türü özet tablosu, Korgün referanslı)."""
from __future__ import annotations

import sqlite3
from typing import Any

from modules.nexgen.finans_belgesi_repository import tablo_var
from modules.nexgen.finans_cari_identity_resolver import resolve_by_operasyonel

BELGE_TIP_ISLEM: dict[str, str] = {
    'ANLASMA': 'Fatura',
    'FATURA': 'Fatura',
    'SATIS': 'Fatura',
    'ALIS': 'Fatura',
    'ODEME': 'Banka',
    'TAHSILAT': 'Nakit',
    'NAKIT': 'Nakit',
    'CEK': 'Çek',
    'SENET': 'Senet',
    'BANKA': 'Banka',
    'DEKONT': 'Dekont',
    'VIRMAN': 'Virman',
    'GIDER': 'Gider',
    'STOK': 'Stok',
    'KUR_FARKI': 'Kur Farkı İşlemi',
    'KREDI_KARTI': 'Kredi Kartı İşlemi',
    'FIYAT_FARKI': 'Fiyat Farkı Faturası',
    'SMM': 'Serbest Meslek',
    'DEMIRBAS': 'Demirbaş',
    'AVANS': 'Devir',
    'DEVIR': 'Devir',
}

KORGEN_SIRA: tuple[str, ...] = (
    'Devir', 'Nakit', 'Çek', 'Senet', 'Fatura', 'Banka', 'Dekont', 'Virman',
    'Gider', 'Stok', 'Kur Farkı İşlemi', 'Kredi Kartı İşlemi',
    'Fiyat Farkı Faturası', 'Serbest Meslek', 'Demirbaş',
)


def _islem_turu(belge_tip: str | None, aciklama: str | None = None) -> str:
    bt = (belge_tip or '').strip().upper()
    if bt in BELGE_TIP_ISLEM:
        return BELGE_TIP_ISLEM[bt]
    if bt:
        return bt.replace('_', ' ').title()
    ac = (aciklama or '').casefold()
    for anahtar, ad in (('çek', 'Çek'), ('senet', 'Senet'), ('fatura', 'Fatura'), ('banka', 'Banka')):
        if anahtar in ac:
            return ad
    return 'Diğer'


def genel_durum_read(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
    *,
    para_birimi: str | None = None,
    tum_islem_turleri: bool = False,
) -> dict[str, Any]:
    resolution = resolve_by_operasyonel(con, cari_tipi, int(operasyonel_id))
    ckod = resolution.finance_card_code
    empty = {
        'cari_kart_ckod': ckod,
        'para_birimi': para_birimi or 'TRY',
        'satirlar': [],
        'toplam': {'islem_turu': 'Toplam', 'borc': 0.0, 'alacak': 0.0, 'borc_bakiye': 0.0, 'alacak_bakiye': 0.0, 'hareket_adedi': 0},
        'uyari': None,
        'tum_islem_turleri': tum_islem_turleri,
    }
    if not ckod or not tablo_var(con, 'Cari_Har'):
        empty['uyari'] = 'Cari kart bağlantısı veya hareket kaydı bulunamadı.'
        return empty

    rows = con.execute(
        """
        SELECT BelgeTip, Aciklama, Borc, Alacak
        FROM Cari_Har WHERE CKod=?
        ORDER BY Tarih, Id
        """,
        (ckod,),
    ).fetchall()

    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        tur = _islem_turu(r['BelgeTip'], r['Aciklama'])
        if tur not in agg:
            agg[tur] = {'islem_turu': tur, 'borc': 0.0, 'alacak': 0.0, 'hareket_adedi': 0}
        agg[tur]['borc'] += float(r['Borc'] or 0)
        agg[tur]['alacak'] += float(r['Alacak'] or 0)
        agg[tur]['hareket_adedi'] += 1

    satirlar: list[dict[str, Any]] = []
    borc_bak = alacak_bak = 0.0
    tb = ta = 0.0
    hareket_top = 0

    sirali = [t for t in KORGEN_SIRA if t in agg]
    diger = sorted(t for t in agg if t not in KORGEN_SIRA and t != 'Diğer')
    if 'Diğer' in agg:
        diger.append('Diğer')

    for tur in sirali + diger:
        a = agg[tur]
        if not tum_islem_turleri and a['borc'] <= 0.0001 and a['alacak'] <= 0.0001:
            continue
        tb += a['borc']
        ta += a['alacak']
        hareket_top += a['hareket_adedi']
        net = a['borc'] - a['alacak']
        if net > 0.0001:
            borc_bak += net
            alacak_bak_row = 0.0
            borc_bak_row = round(net, 2)
            alacak_bak_row_val = 0.0
        elif net < -0.0001:
            alacak_bak += abs(net)
            borc_bak_row = 0.0
            alacak_bak_row_val = round(abs(net), 2)
        else:
            borc_bak_row = alacak_bak_row_val = 0.0
        satirlar.append({
            'islem_turu': tur,
            'borc': round(a['borc'], 2),
            'alacak': round(a['alacak'], 2),
            'borc_bakiye': borc_bak_row,
            'alacak_bakiye': alacak_bak_row_val,
            'hareket_adedi': a['hareket_adedi'],
        })

    net_top = tb - ta
    toplam = {
        'islem_turu': 'Toplam',
        'borc': round(tb, 2),
        'alacak': round(ta, 2),
        'borc_bakiye': round(net_top, 2) if net_top > 0.0001 else 0.0,
        'alacak_bakiye': round(abs(net_top), 2) if net_top < -0.0001 else 0.0,
        'hareket_adedi': hareket_top,
    }
    return {
        'cari_kart_ckod': ckod,
        'para_birimi': para_birimi or 'TRY',
        'satirlar': satirlar,
        'toplam': toplam,
        'uyari': None if satirlar else 'Seçilen para birimi için hareket bulunmuyor.',
        'tum_islem_turleri': tum_islem_turleri,
    }
