# -*- coding: utf-8 -*-
"""MO tahsilat kaydı Merkezi Onay adapter."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from modules.nexgen.mo_tahsilat_config import CARI_ENTEGRASYON_AKTIF, KAYNAK_MUSTERI_OPERASYONU
from modules.nexgen.mo_tahsilat_kayit_service import karar_sonrasi
from modules.nexgen.onay_merkezi_service import (
    adapter_log,
    shadow_olay,
    snapshot_hash,
    talep_olustur,
)

KAYNAK_MODUL = 'mo_tahsilat_kayit'
TALEP_TIPI = 'TAHSILAT_KAYDI'
ADAPTER = 'TAHSILAT_KAYDI_ADAPTER'


def _tablo_var(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def tahsilat_snapshot_olustur(con, kayit_id: int) -> dict[str, Any]:
    row = con.execute(
        """
        SELECT tk.*, c.unvan AS cari_unvan, c.cari_kod,
               ps.siparis_no, sk.KullaniciAdi AS pazarlamaci_adi
        FROM mo_tahsilat_kayit tk
        LEFT JOIN nexgen_cari c ON c.id = tk.cari_id
        LEFT JOIN nexgen_planlama_siparis ps ON ps.id = tk.siparis_id
        LEFT JOIN sistem_kullanici sk ON sk.Id = tk.olusturan_id
        WHERE tk.id=? AND tk.aktif=1
        """,
        (kayit_id,),
    ).fetchone()
    if not row:
        return {}
    d = dict(row)
    snap: dict[str, Any] = {
        'tahsilat_kayit_id': d['id'],
        'kayit_kodu': d.get('kayit_kodu'),
        'cari_id': d.get('cari_id'),
        'cari_unvan_snapshot': d.get('cari_unvan'),
        'cari_kod_snapshot': d.get('cari_kod'),
        'siparis_id': d.get('siparis_id'),
        'siparis_no': d.get('siparis_no'),
        'pazarlamaci_id': d.get('olusturan_id'),
        'pazarlamaci_adi': d.get('pazarlamaci_adi'),
        'beklenen_tutar': d.get('beklenen_tutar'),
        'alinan_tutar': d.get('alinan_tutar'),
        'kalan_tutar': d.get('kalan_tutar'),
        'planlanan_tahsilat_tarihi': d.get('planlanan_tahsilat_tarihi'),
        'alinan_tarih': d.get('alinan_tarih'),
        'odeme_tipi': d.get('odeme_tipi'),
        'odeme_referansi': d.get('odeme_referansi'),
        'kismi_mi': bool(d.get('kismi_mi')),
        'aciklama': d.get('aciklama'),
        'dosya_ref': d.get('dosya_ref'),
        'onay_notu': d.get('onay_notu'),
        'kaynak_modul': KAYNAK_MUSTERI_OPERASYONU,
        'cari_entegrasyon_aktif': CARI_ENTEGRASYON_AKTIF,
    }
    snap['snapshot_hash'] = snapshot_hash(snap)
    return snap


def tahsilat_onaya_gonder(con, kayit_id: int, talep_eden_id: int) -> dict[str, Any]:
    snap = tahsilat_snapshot_olustur(con, kayit_id)
    if not snap:
        return {'ok': False, 'hata': 'Kayıt bulunamadı.'}

    idem = f'mo-tahsilat-onay-{kayit_id}-{snap.get("snapshot_hash", "")[:16]}'
    adimlar = [
        {'sira': 1, 'adim_tipi': 'MUHASEBE_ONAY', 'kademe': 'K2', 'rol_adi': 'Muhasebe', 'durum': 'BEKLIYOR'},
    ]
    r = talep_olustur(
        con,
        talep_tipi=TALEP_TIPI,
        kaynak_modul=KAYNAK_MODUL,
        kaynak_id=kayit_id,
        kaynak_kod=snap.get('kayit_kodu') or f'MTK-{kayit_id}',
        talep_eden_id=talep_eden_id,
        snapshot=snap,
        cari_id=snap.get('cari_id'),
        cari_unvan=snap.get('cari_unvan_snapshot'),
        tutar=snap.get('alinan_tutar') or snap.get('beklenen_tutar'),
        para_birimi='TRY',
        idempotency_key=idem,
        adimlar=adimlar,
    )
    if r.get('ok'):
        adapter_log(
            con, talep_id=r.get('talep_id'), adapter_kodu=ADAPTER,
            kaynak_modul=KAYNAK_MODUL, islem='ONAYA_GONDER', sonuc='OK',
            payload={'kayit_id': kayit_id},
        )
        shadow_olay(con, 'TAHSILAT_KAYDI_GIRILDI', {
            'kayit_id': kayit_id, 'talep_id': r.get('talep_id'),
        })
    return r


def karar_sonrasi_adapter(con, talep_id: int, sonuc: dict) -> None:
    if not sonuc.get('ok'):
        return
    talep = con.execute(
        'SELECT kaynak_id, kaynak_modul FROM onay_talep WHERE id=?', (talep_id,)
    ).fetchone()
    if not talep or talep['kaynak_modul'] != KAYNAK_MODUL:
        return
    kid = int(talep['kaynak_id'])
    notu = ''
    if sonuc.get('durum') in ('REVIZYON', 'REDDEDILDI'):
        adim = con.execute(
            "SELECT karar_notu FROM onay_talep_adim WHERE talep_id=? AND durum=? ORDER BY id DESC LIMIT 1",
            (talep_id, sonuc.get('durum')),
        ).fetchone()
        notu = (adim['karar_notu'] if adim else '') or ''
    karar_sonrasi(con, kid, {**sonuc, 'not': notu})
    adapter_log(
        con, talep_id=talep_id, adapter_kodu=ADAPTER,
        kaynak_modul=KAYNAK_MODUL, islem=f"KARAR_{sonuc.get('durum')}", sonuc='OK',
        payload={'kayit_id': kid},
    )
