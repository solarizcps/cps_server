# -*- coding: utf-8 -*-
"""Satın alma siparişi onay adapter — shadow + senkron."""
from __future__ import annotations

import json
from typing import Any

from modules.nexgen.onay_merkezi_service import (
    adapter_log,
    aktif_talep_var,
    karar_ver,
    shadow_olay,
    snapshot_hash,
    talep_olustur,
)

KAYNAK_MODUL = 'nexgen_satin_siparis'
TALEP_TIPI = 'SATIN_ALMA_SIPARISI'
ADAPTER = 'SATIN_ALMA_ADAPTER'


def _snapshot(con, siparis_id: int) -> dict:
    s = con.execute(
        """
        SELECT ss.*, t.ad AS tedarikci_ad
        FROM nexgen_satin_siparis ss
        LEFT JOIN nexgen_tedarikci t ON t.id = ss.tedarikci_id
        WHERE ss.id=?
        """,
        (siparis_id,),
    ).fetchone()
    if not s:
        return {}
    d = dict(s)
    return {
        'siparis_id': d['id'],
        'siparis_no': d['siparis_no'],
        'tedarikci_id': d['tedarikci_id'],
        'tedarikci_ad': d.get('tedarikci_ad'),
        'stok_kart_id': d['stok_kart_id'],
        'siparis_miktari_kg': d['siparis_miktari_kg'],
        'birim_fiyat': d['birim_fiyat'],
        'para_birimi': d['para_birimi'],
        'vade_gun': d['vade_gun'],
        'toplam_tutar_try': d['toplam_tutar_try'],
        'aciklama': d['aciklama'],
        'onay_durumu': d['onay_durumu'],
        'snapshot_hash': None,
    }


def satin_onaya_gonder_shadow(con, siparis_id: int, talep_eden_id: int) -> dict[str, Any]:
    if aktif_talep_var(con, KAYNAK_MODUL, siparis_id, TALEP_TIPI):
        return {'ok': True, 'shadow': True, 'skip': 'DUPLICATE'}

    s = con.execute(
        'SELECT siparis_no, onay_durumu FROM nexgen_satin_siparis WHERE id=?',
        (siparis_id,),
    ).fetchone()
    if not s:
        return {'ok': False, 'hata': 'Sipariş yok'}

    snap = _snapshot(con, siparis_id)
    snap['snapshot_hash'] = snapshot_hash(snap)
    idem = f'{TALEP_TIPI}:{siparis_id}:1'

    r = talep_olustur(
        con,
        talep_tipi=TALEP_TIPI,
        kaynak_modul=KAYNAK_MODUL,
        kaynak_id=siparis_id,
        kaynak_kod=s['siparis_no'],
        talep_eden_id=talep_eden_id,
        snapshot=snap,
        etki={'tip': 'SATIN_ALMA'},
        tutar=float(snap['toplam_tutar_try'] or 0) if snap.get('toplam_tutar_try') else None,
        para_birimi=snap.get('para_birimi'),
        vade_gun=int(snap['vade_gun']) if snap.get('vade_gun') not in (None, '') else None,
        idempotency_key=idem,
        adimlar=[
            {'sira': 1, 'adim_tipi': 'SATINALMA_ONAY', 'kademe': 'K2', 'rol_adi': 'Satın Alma', 'durum': 'BEKLIYOR'},
        ],
    )
    if not r.get('ok'):
        return r

    adapter_log(
        con, talep_id=r['talep_id'], adapter_kodu=ADAPTER,
        kaynak_modul=KAYNAK_MODUL, islem='ONAYA_GONDER_SHADOW', sonuc='OK',
        payload={'siparis_id': siparis_id},
    )
    return r


def satin_onay_senkron(con, siparis_id: int, yeni_onay_durumu: str, talep_id: int | None = None) -> None:
    if talep_id is None:
        row = con.execute(
            """
            SELECT id, durum FROM onay_talep
            WHERE kaynak_modul=? AND kaynak_id=? AND talep_tipi=?
            ORDER BY id DESC LIMIT 1
            """,
            (KAYNAK_MODUL, siparis_id, TALEP_TIPI),
        ).fetchone()
        if not row:
            return
        talep_id = int(row['id'])

    if yeni_onay_durumu == 'ONAYLANDI':
        con.execute(
            "UPDATE onay_talep SET durum='ONAYLANDI', updated_at=datetime('now','localtime') WHERE id=?",
            (talep_id,),
        )
        shadow_olay(con, 'SATIN_ALMA_ONAYLANDI', {'talep_id': talep_id, 'kaynak_id': siparis_id})
    elif yeni_onay_durumu == 'REDDEDILDI':
        con.execute(
            "UPDATE onay_talep SET durum='REDDEDILDI', aktif=0, updated_at=datetime('now','localtime') WHERE id=?",
            (talep_id,),
        )

    adapter_log(
        con, talep_id=talep_id, adapter_kodu=ADAPTER,
        kaynak_modul=KAYNAK_MODUL, islem='SENKRON', sonuc='OK',
        payload={'siparis_id': siparis_id, 'onay_durumu': yeni_onay_durumu},
    )
