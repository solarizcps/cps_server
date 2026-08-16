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
               ps.siparis_no, ps.anlasma_para_birimi AS siparis_para_birimi,
               ps.anlasma_birim_fiyat AS siparis_birim_fiyat, ps.kur AS siparis_kur,
               ps.kur_tarihi AS siparis_kur_tarihi,
               sk.KullaniciAdi AS pazarlamaci_adi
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
        'siparis_para_birimi': d.get('siparis_para_birimi'),
        'siparis_kur': float(d['siparis_kur']) if d.get('siparis_kur') else None,
        'siparis_kur_tarihi': (d.get('siparis_kur_tarihi') or '')[:10] or None,
        'siparis_toplami': float(d['siparis_birim_fiyat']) if d.get('siparis_birim_fiyat') else None,
        'pazarlamaci_id': d.get('olusturan_id'),
        'pazarlamaci_adi': d.get('pazarlamaci_adi'),
        'beklenen_tutar': d.get('beklenen_tutar'),
        'paket_hedef_tutar': d.get('paket_hedef_tutar'),
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

    # CEK: vade_kontrol snapshot freeze
    if (d.get('odeme_tipi') or '').upper() == 'CEK':
        snap['vade_kontrol'] = _vade_kontrol_snapshot(con, kayit_id, d)

    snap['snapshot_hash'] = snapshot_hash(snap)
    return snap


def _vade_kontrol_snapshot(con, kayit_id: int, parent: dict) -> dict[str, Any]:
    """CEK paket için canonical vade kontrolü hesapla ve dondur."""
    try:
        from decimal import Decimal
        from modules.nexgen.mo_tahsilat_cek_service import cek_listele
        from modules.nexgen.mo_vade_kontrol_service import CekSatiriInput, hesapla

        cekler = cek_listele(con, kayit_id)
        satirlar = [
            CekSatiriInput(
                tutar=Decimal(str(c['tutar'])),
                gercek_cek_vade_tarihi=c['gercek_cek_vade_tarihi'],
                para_birimi=c['para_birimi'],
                cek_alim_tarihi=c.get('cek_alim_tarihi'),
                odeme_referansi=c.get('odeme_referansi'),
                banka_adi=c.get('banka_adi'),
            )
            for c in cekler
        ]
        pb = (parent.get('para_birimi') or 'TRY').strip().upper()
        hedef = parent.get('paket_hedef_tutar')
        hedef_d = Decimal(str(hedef)) if hedef is not None else None
        onaylanan = parent.get('onaylanan_vade_gun_snapshot')
        sevk = parent.get('gercek_sevk_tarihi_snapshot')

        sonuc = hesapla(
            tahsilat_kayit_id=kayit_id,
            odeme_tipi='CEK',
            cek_satirlari=satirlar,
            paket_hedef_tutar=hedef_d,
            para_birimi=pb,
            onaylanan_vade_gun=onaylanan,
            sevk_tarihi=sevk,
            con=con,
        )
        return sonuc.to_dict()
    except Exception as e:
        # snapshot freeze hatası onay akışını engellememeli
        return {'hata': str(e), 'cek_adedi': 0}


def tahsilat_onaya_gonder(con, kayit_id: int, talep_eden_id: int) -> dict[str, Any]:
    snap = tahsilat_snapshot_olustur(con, kayit_id)
    if not snap:
        return {'ok': False, 'hata': 'Kayıt bulunamadı.'}

    # Revizyon sayacı: mevcut geçmiş taleplerin max revizyon_no + 1
    mevcut = con.execute(
        "SELECT COALESCE(MAX(revizyon_no),0) FROM onay_talep WHERE kaynak_modul=? AND kaynak_id=?",
        (KAYNAK_MODUL, kayit_id),
    ).fetchone()
    rev_no = (mevcut[0] or 0) + 1

    idem = f'mo-tahsilat-onay-{kayit_id}-r{rev_no}-{snap.get("snapshot_hash", "")[:12]}'
    adimlar = [
        {'sira': 1, 'adim_tipi': 'YONETIM_ONAY', 'kademe': 'K3', 'rol_adi': 'Yönetim', 'durum': 'BEKLIYOR'},
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
        revizyon_no=rev_no,
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
    # Gerçek karar adımını oku: kullanici_id, tarih, karar_notu
    _durum_ara = sonuc.get('durum')
    _adim_durum = {
        'ONAYLANDI': 'TAMAMLANDI', 'REVIZYON': 'REVIZYON', 'REDDEDILDI': 'REDDEDILDI',
    }.get(_durum_ara, _durum_ara)
    adim = con.execute(
        "SELECT kullanici_id, tarih, karar_notu FROM onay_talep_adim "
        "WHERE talep_id=? AND durum=? ORDER BY id DESC LIMIT 1",
        (talep_id, _adim_durum),
    ).fetchone()
    notu = (adim['karar_notu'] if adim else '') or ''
    uid = int(adim['kullanici_id']) if adim and adim['kullanici_id'] else None
    ktarih = str(adim['tarih']) if adim and adim['tarih'] else None
    karar_sonrasi(con, kid, {**sonuc, 'not': notu, 'kullanici_id': uid, 'karar_tarihi': ktarih})
    adapter_log(
        con, talep_id=talep_id, adapter_kodu=ADAPTER,
        kaynak_modul=KAYNAK_MODUL, islem=f"KARAR_{sonuc.get('durum')}", sonuc='OK',
        payload={'kayit_id': kid},
    )
