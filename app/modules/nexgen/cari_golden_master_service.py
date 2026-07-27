# -*- coding: utf-8 -*-
"""
Golden Master read-only servis — nexgen_cari merkezli cari eşleştirme görünümü.

FAZ-CARI-GOLDEN-MASTER-ESLESTIRME-F1B
- Otomatik eşleştirme YOK
- Yeni Cari_Kart / crm_firma oluşturma YOK
- Mevcut FK taşıma YOK
"""
from __future__ import annotations

import sqlite3
from typing import Any, Optional

ESLESTIRME_DURUMLARI = ('BEKLIYOR', 'DOGRULANDI', 'MANUEL', 'IPTAL')
ESLESTIRME_YONTEMLERI = ('CARI_KODU', 'ERP_KODU', 'VERGI_NO', 'MANUEL')

_BAGLANTI_KEYS = ('cari_kart', 'crm_firma')


def _row_dict(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return dict(row)


def _eksik_baglantilar(es: Optional[dict[str, Any]]) -> list[str]:
    if not es:
        return list(_BAGLANTI_KEYS)
    eksik = []
    if not es.get('cari_kart_ckod'):
        eksik.append('cari_kart')
    if not es.get('crm_firma_id'):
        eksik.append('crm_firma')
    return eksik


def get_golden_master_snapshot(
    con: sqlite3.Connection,
    nexgen_cari_id: int,
) -> dict[str, Any]:
    """
    Bir nexgen_cari_id için Golden Master read-only snapshot.

    Eşleşme yoksa hata vermez; eslestirme_durumu='eslesmemis' döner.
    """
    nc = con.execute(
        'SELECT id, cari_kod, unvan, aktif FROM nexgen_cari WHERE id=?',
        (nexgen_cari_id,),
    ).fetchone()
    if not nc:
        return {
            'ok': False,
            'hata': 'nexgen_cari_bulunamadi',
            'nexgen_cari_id': nexgen_cari_id,
        }

    es_row = con.execute(
        """
        SELECT id, nexgen_cari_id, cari_kart_ckod, crm_firma_id,
               eslestirme_durumu, eslestirme_yontemi, guven_puani,
               eslestiren_id, eslestirme_tarihi, aktif,
               created_at, updated_at
        FROM cari_eslestirme
        WHERE nexgen_cari_id=? AND aktif=1
        ORDER BY id DESC
        LIMIT 1
        """,
        (nexgen_cari_id,),
    ).fetchone()
    es = _row_dict(es_row)

    finans_ref = None
    crm_ref = None
    durum = 'eslesmemis'

    if es:
        durum = es.get('eslestirme_durumu') or 'BEKLIYOR'
        ckod = es.get('cari_kart_ckod')
        if ckod:
            ck = con.execute(
                'SELECT CKod, CName, CTip, VergiNo, Sehir FROM Cari_Kart WHERE CKod=?',
                (ckod,),
            ).fetchone()
            if ck:
                finans_ref = {
                    'cari_kart_ckod': ck['CKod'],
                    'unvan': ck['CName'],
                    'tip': ck['CTip'],
                    'vergi_no': ck['VergiNo'],
                    'sehir': ck['Sehir'],
                }
        crm_id = es.get('crm_firma_id')
        if crm_id:
            cf = con.execute(
                """
                SELECT id, firma_adi, yetkili, telefon, email, erp_cari_kodu, aktif
                FROM crm_firma WHERE id=?
                """,
                (crm_id,),
            ).fetchone()
            if cf:
                gorusme_cnt = 0
                if con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='crm_gorusme'"
                ).fetchone():
                    gorusme_cnt = con.execute(
                        'SELECT COUNT(*) FROM crm_gorusme WHERE firma_id=?',
                        (crm_id,),
                    ).fetchone()[0]
                crm_ref = {
                    'crm_firma_id': cf['id'],
                    'firma_adi': cf['firma_adi'],
                    'yetkili': cf['yetkili'],
                    'telefon': cf['telefon'],
                    'email': cf['email'],
                    'erp_cari_kodu': cf['erp_cari_kodu'],
                    'gorusme_sayisi': int(gorusme_cnt or 0),
                }

    return {
        'ok': True,
        'golden_cari': {
            'nexgen_cari_id': nc['id'],
            'cari_kod': nc['cari_kod'],
            'unvan': nc['unvan'],
            'aktif': bool(nc['aktif']),
        },
        'eslestirme_durumu': durum,
        'eslestirme': es,
        'finans_referans': finans_ref,
        'crm_referans': crm_ref,
        'eksik_baglantilar': _eksik_baglantilar(es),
        'otomatik_eslestirme': False,
    }


def count_eslestirme(con: sqlite3.Connection) -> int:
    """Toplam aktif eşleştirme satırı."""
    if not con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cari_eslestirme'"
    ).fetchone():
        return 0
    return int(con.execute('SELECT COUNT(*) FROM cari_eslestirme').fetchone()[0])
