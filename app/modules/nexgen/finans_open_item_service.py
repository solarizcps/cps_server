# -*- coding: utf-8 -*-
"""Open item yaşam döngüsü write servisi — FAZ-GECIS Bölüm B."""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any

from modules.nexgen.finans_belgesi_repository import tablo_var
from modules.nexgen.finans_core_config import (
    OI_DURUM_ACIK,
    OI_DURUM_IPTAL,
    OI_DURUM_KAPALI,
    OI_DURUM_KISMI_KAPALI,
    OI_DURUM_TERS_ACILDI,
    OI_DURUM_UYUSMAZLIK,
    OI_YON_ALACAK,
    OI_YON_BORC,
    idempotency_open_item,
)
from modules.nexgen.finans_core_schema import decimal_para, open_item_tutar_gecerli


class FinansOpenItemError(Exception):
    def __init__(self, mesaj: str, kod: int = 409, hata_kodu: str = 'OPEN_ITEM_HATA'):
        self.mesaj = mesaj
        self.kod = kod
        self.hata_kodu = hata_kodu
        super().__init__(mesaj)


def _durum_hesapla(orijinal: Decimal, acik: Decimal, kapanan: Decimal) -> str:
    if acik <= Decimal('0'):
        return OI_DURUM_KAPALI
    if kapanan > Decimal('0') and acik < orijinal:
        return OI_DURUM_KISMI_KAPALI
    return OI_DURUM_ACIK


def create_for_belge(
    con: sqlite3.Connection,
    *,
    ckod: str,
    finans_belgesi_id: int,
    yon: str,
    orijinal_tutar: Decimal | float,
    vade_tarihi: str | None = None,
    finans_belge_satir_id: int | None = None,
    taksit_no: int | None = None,
    para_birimi: str = 'TRY',
) -> dict[str, Any]:
    if not tablo_var(con, 'finans_open_item'):
        raise FinansOpenItemError('finans_open_item tablosu yok.', 503, 'TABLO_YOK')
    yon_u = (yon or '').strip().upper()
    if yon_u not in (OI_YON_BORC, OI_YON_ALACAK):
        raise FinansOpenItemError('Geçersiz open item yönü.', 400, 'OI_YON_GECERSIZ')
    orig = decimal_para(orijinal_tutar)
    if orig < 0:
        raise FinansOpenItemError('Orijinal tutar negatif olamaz.', 409, 'OI_TUTAR_NEGATIF')

    idem = idempotency_open_item(int(finans_belgesi_id), satir_no=finans_belge_satir_id, taksit_no=taksit_no)
    mevcut = con.execute(
        'SELECT id FROM finans_open_item WHERE idempotency_key=?', (idem,),
    ).fetchone()
    if mevcut:
        row = con.execute('SELECT * FROM finans_open_item WHERE id=?', (int(mevcut['id']),)).fetchone()
        return dict(row)

    cur = con.execute(
        """
        INSERT INTO finans_open_item (
            ckod, finans_belgesi_id, finans_belge_satir_id, yon,
            orijinal_tutar, acik_tutar, kapanan_tutar, para_birimi,
            vade_tarihi, durum, idempotency_key
        ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, 'ACIK', ?)
        """,
        (ckod, int(finans_belgesi_id), finans_belge_satir_id, yon_u,
         float(orig), float(orig), para_birimi, vade_tarihi, idem),
    )
    oid = int(cur.lastrowid)
    return dict(con.execute('SELECT * FROM finans_open_item WHERE id=?', (oid,)).fetchone())


def apply_kapanis(
    con: sqlite3.Connection,
    open_item_id: int,
    *,
    tutar: Decimal | float,
    beklenen_versiyon: int,
) -> dict[str, Any]:
    row = con.execute('SELECT * FROM finans_open_item WHERE id=?', (int(open_item_id),)).fetchone()
    if not row:
        raise FinansOpenItemError('Open item bulunamadı.', 404, 'OI_YOK')
    if int(row['versiyon']) != int(beklenen_versiyon):
        raise FinansOpenItemError('Versiyon uyuşmazlığı.', 409, 'OI_VERSIYON_CAKISMA')
    durum = (row['durum'] or '').upper()
    if durum in (OI_DURUM_KAPALI, OI_DURUM_IPTAL, OI_DURUM_UYUSMAZLIK):
        raise FinansOpenItemError('Kapalı/iptal item kapatılamaz.', 409, 'OI_KAPALI')

    dagitim = decimal_para(tutar)
    if dagitim <= Decimal('0'):
        raise FinansOpenItemError('Sıfır veya negatif dağıtım reddedildi.', 409, 'OI_DAGITIM_GECERSIZ')

    orig = decimal_para(row['orijinal_tutar'])
    acik = decimal_para(row['acik_tutar'])
    kapanan = decimal_para(row['kapanan_tutar'])
    if dagitim > acik + Decimal('0.001'):
        raise FinansOpenItemError('Dağıtım açık tutarı aşıyor.', 409, 'OI_DAGITIM_ASIM')

    yeni_acik = acik - dagitim
    yeni_kapanan = kapanan + dagitim
    if not open_item_tutar_gecerli(orig, yeni_acik, yeni_kapanan):
        raise FinansOpenItemError('Open item tutar uyumsuzluğu.', 409, 'OI_TUTAR_UYUMSUZ')

    yeni_durum = _durum_hesapla(orig, yeni_acik, yeni_kapanan)
    con.execute(
        """
        UPDATE finans_open_item SET
            acik_tutar=?, kapanan_tutar=?, durum=?,
            versiyon=versiyon+1, guncelleme_tarihi=datetime('now','localtime'),
            kapanis_tarihi=CASE WHEN ?=0 THEN datetime('now','localtime') ELSE kapanis_tarihi END
        WHERE id=? AND versiyon=?
        """,
        (float(yeni_acik), float(yeni_kapanan), yeni_durum, float(yeni_acik),
         int(open_item_id), int(beklenen_versiyon)),
    )
    if con.total_changes == 0:
        raise FinansOpenItemError('Versiyon uyuşmazlığı.', 409, 'OI_VERSIYON_CAKISMA')
    return dict(con.execute('SELECT * FROM finans_open_item WHERE id=?', (int(open_item_id),)).fetchone())


def apply_coklu_kapanis(
    con: sqlite3.Connection,
    dagitimlar: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """ID ASC sıralı çoklu kapama — tek transaction içinde çağrılmalı."""
    sirali = sorted(dagitimlar, key=lambda x: int(x['open_item_id']))
    sonuc: list[dict[str, Any]] = []
    for d in sirali:
        sonuc.append(apply_kapanis(
            con,
            int(d['open_item_id']),
            tutar=d['tutar'],
            beklenen_versiyon=int(d['versiyon']),
        ))
    return sonuc
