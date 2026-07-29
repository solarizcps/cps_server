# -*- coding: utf-8 -*-
"""
Satış siparişi onay adapter + Mehmet köprüsü.

Kural: Aynı nexgen_planlama_siparis kaydı; ONAYLANDI sonrası Mehmet ekranına düşer.
Siparişi Al yok — mevcut Üretime Gönder akışı.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from modules.nexgen.onay_merkezi_service import (
    adapter_log,
    aktif_talep_var,
    karar_ver,
    shadow_olay,
    snapshot_hash,
    talep_olustur,
)
from modules.nexgen.planlama_kopru_sozlesmesi import PLANLAMA_KOPRU_SNAPSHOT_ALANLARI

KAYNAK_MODUL = 'nexgen_planlama_siparis'
TALEP_TIPI = 'SATIS_SIPARISI'
ADAPTER = 'SATIS_SIPARISI_ADAPTER'

# Legacy: onay_talep yoksa eski akış (TASLAK→MPR) korunur
ONAY_GEREKLI_DURUMLAR = frozenset({
    'ONAY_BEKLIYOR', 'ONAYLANDI', 'REVIZYON', 'REDDEDILDI',
})


def _tablo_var(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def siparis_onay_kayitli_mi(con, siparis_id: int) -> bool:
    if not _tablo_var(con, 'onay_talep'):
        return False
    return bool(con.execute(
        """
        SELECT 1 FROM onay_talep
        WHERE kaynak_modul=? AND kaynak_id=? AND talep_tipi=?
        """,
        (KAYNAK_MODUL, siparis_id, TALEP_TIPI),
    ).fetchone())


def pzm_mpr_uretim_izinli(con, siparis_id: int) -> tuple[bool, str | None]:
    """
    MPR analiz / Üretime Gönder öncesi onay kontrolü.
    Legacy siparişler (onay kaydı yok): mevcut davranış.
    """
    row = con.execute(
        'SELECT id, durum FROM nexgen_planlama_siparis WHERE id=?', (siparis_id,)
    ).fetchone()
    if not row:
        return False, 'Sipariş bulunamadı.'
    durum = (row['durum'] or '').upper()
    if durum in ('IPTAL', 'URETIMDE'):
        return False, f'Sipariş durumu uygun değil: {durum}'
    if not siparis_onay_kayitli_mi(con, siparis_id):
        return True, None
    if durum == 'ONAY_BEKLIYOR':
        return False, 'Onay tamamlanmadan MPR/üretim başlatılamaz.'
    if durum in ('TASLAK', 'REVIZYON', 'REDDEDILDI'):
        return False, 'Sipariş onay sürecinde veya taslak; önce onaya gönderin/onaylayın.'
    if durum in ('ONAYLANDI', 'MPR_BEKLIYOR', 'PLANLAMAYA_HAZIR'):
        return True, None
    return False, f'Onaylı sipariş bekleniyor; mevcut durum: {durum}'


def _kalemler(con, siparis_id: int) -> list[dict]:
    from modules.nexgen.pzm_siparis_read import pzm_siparis_kalemleri_getir
    try:
        return pzm_siparis_kalemleri_getir(con, siparis_id)
    except Exception:
        return []


def satis_snapshot_olustur(con, siparis_id: int) -> dict[str, Any]:
    """planlama_kopru_sozlesmesi alanları — NULL/eksik uydurma yok."""
    hdr = con.execute(
        """
        SELECT ps.*, nc.cari_kod, sk.KullaniciAdi AS olusturan_ad
        FROM nexgen_planlama_siparis ps
        LEFT JOIN nexgen_cari nc ON nc.id = ps.cari_id
        LEFT JOIN sistem_kullanici sk ON sk.Id = ps.olusturan_id
        WHERE ps.id=?
        """,
        (siparis_id,),
    ).fetchone()
    if not hdr:
        return {}

    from modules.nexgen.pzm_siparis_read import pzm_payload_unpack, pzm_siparis_finans_alanlari
    from modules.nexgen.mo_siparis_talep_service import mo_siparis_payload_unpack
    from modules.nexgen.mo_tahsilat_config import ODEME_SEKLI_ETIKET
    from modules.nexgen.mo_tahsilat_plan_service import tahsilat_kural_etiket, hesapla_tahsilat_plani

    payload = pzm_payload_unpack(hdr['talep_referansi'])
    mo_payload = mo_siparis_payload_unpack(hdr['talep_referansi'])
    fin = pzm_siparis_finans_alanlari(dict(hdr), payload)
    kalemler = _kalemler(con, siparis_id)

    snap: dict[str, Any] = {
        'siparis_id': hdr['id'],
        'siparis_no': hdr['siparis_no'],
        'cari_id': hdr['cari_id'],
        'cari_kod_snapshot': hdr['cari_kod'],
        'cari_unvan_snapshot': hdr['cari_unvan'],
        'pazarlamaci_id': hdr['olusturan_id'],
        'pazarlamaci_adi': hdr['olusturan_ad'],
        'kalemler': kalemler,
        'termin_tarihi': hdr['termin_tarihi'],
        'fiyat': fin.get('anlasma_birim_fiyat'),  # tek kalem geçiş; çok kalemde kalem snapshot
        'para_birimi': fin.get('anlasma_para_birimi'),
        'vade_gun': fin.get('vade_gun'),
        'odeme_tipi': fin.get('odeme_tipi'),  # NAKIT|VADELI — tahsilat_odeme_sekli değil
        'odeme_notu': fin.get('odeme_notu'),
        'kur': fin.get('kur'),
        'kur_tarihi': fin.get('kur_tarihi'),
        'kur_kaynagi': fin.get('kur_kaynagi'),
        'odeme_sekli': (payload or {}).get('odeme_sekli'),
        'cek_sayisi': (payload or {}).get('cek_sayisi'),
        'cek_tarihleri': (payload or {}).get('cek_tarihleri'),
        'risk_sonucu': (payload or {}).get('risk_sonucu'),
        'siparis_notlari': hdr['notlar'],
        'teslim_plani': (payload or {}).get('teslim_plani'),
        'numune_baglanti_id': (payload or {}).get('numune_baglanti_id'),
        'onayli_renk_baglanti_id': (payload or {}).get('onayli_renk_baglanti_id'),
        'onay_talep_id': None,
    }
    if kalemler:
        k0 = kalemler[0]
        snap['urun_ozet'] = k0.get('formul_ad') or k0.get('urun_ailesi')
        snap['miktar'] = k0.get('toplam_kg')
        snap['formul_id'] = k0.get('formul_id')
        snap['renk_kodu'] = k0.get('renk_kodu') or k0.get('renk_ad')
        snap['rf_renk_id'] = k0.get('rf_renk_id')
        # T2: tutar kalem satir_tutari toplamından (yanıltıcı başlık ortalaması yok)
        satir_toplam = 0.0
        satir_var = False
        for k in kalemler:
            st = k.get('satir_tutari')
            if st not in (None, ''):
                try:
                    satir_toplam += float(st)
                    satir_var = True
                except (TypeError, ValueError):
                    pass
        if satir_var:
            snap['toplam_tutar'] = round(satir_toplam, 4)
            if len(kalemler) == 1:
                snap['fiyat'] = k0.get('birim_fiyat') or snap.get('fiyat')
            else:
                snap['fiyat'] = None  # çok kalem: birim fiyat başlıktan okunmaz
        snap['kalem_fiyatlar'] = [
            {
                'sira_no': k.get('sira_no'),
                'birim_fiyat': k.get('birim_fiyat'),
                'iskonto_orani': k.get('iskonto_orani'),
                'net_birim_fiyat': k.get('net_birim_fiyat'),
                'satir_tutari': k.get('satir_tutari'),
                'net_birim_fiyat_try': k.get('net_birim_fiyat_try'),
                'satir_tutari_try': k.get('satir_tutari_try'),
                'fiyat_kaynagi': k.get('fiyat_kaynagi'),
            }
            for k in kalemler
        ]
        try_toplam = 0.0
        try_var = False
        for k in kalemler:
            stt = k.get('satir_tutari_try')
            if stt not in (None, ''):
                try:
                    try_toplam += float(stt)
                    try_var = True
                except (TypeError, ValueError):
                    pass
        if try_var:
            snap['toplam_tutar_try'] = round(try_toplam, 4)
    else:
        snap['urun_ozet'] = None
        snap['miktar'] = None
        snap['formul_id'] = None
        snap['renk_kodu'] = None
        snap['rf_renk_id'] = None

    if mo_payload:
        snap['kaynak_mo'] = True
        snap['urun_grubu'] = mo_payload.get('urun_grubu')
        snap['urun_adi'] = mo_payload.get('urun_adi')
        snap['miktar'] = mo_payload.get('miktar')
        snap['birim'] = mo_payload.get('birim')
        snap['teslim_sekli'] = hdr['teslim_sekli'] if 'teslim_sekli' in hdr.keys() else mo_payload.get('teslim_sekli')
        snap['musteri_termin'] = hdr['musteri_termin'] if 'musteri_termin' in hdr.keys() else mo_payload.get('musteri_termin')
        snap['onerilen_termin'] = hdr['onerilen_termin'] if 'onerilen_termin' in hdr.keys() else mo_payload.get('onerilen_termin')
        snap['musteri_urun_kodu'] = hdr['musteri_urun_kodu'] if 'musteri_urun_kodu' in hdr.keys() else mo_payload.get('musteri_urun_kodu')
        snap['musteri_notu'] = hdr['notlar']
        snap['onay_notu'] = hdr['onay_notu'] if 'onay_notu' in hdr.keys() else None
        snap['mo_gorusme_id'] = hdr['mo_gorusme_id'] if 'mo_gorusme_id' in hdr.keys() else mo_payload.get('mo_gorusme_id')
        snap['urun_ozet'] = mo_payload.get('urun_adi') or mo_payload.get('urun_grubu')
        if not snap.get('miktar') and mo_payload.get('miktar'):
            snap['miktar'] = mo_payload.get('miktar')
        tah_kural = hdr['tahsilat_kurali'] if 'tahsilat_kurali' in hdr.keys() else None
        if tah_kural:
            snap['tahsilat_odeme_sekli'] = hdr['tahsilat_odeme_sekli'] if 'tahsilat_odeme_sekli' in hdr.keys() else None
            snap['tahsilat_odeme_sekli_etiket'] = ODEME_SEKLI_ETIKET.get(snap.get('tahsilat_odeme_sekli') or '', snap.get('tahsilat_odeme_sekli'))
            snap['tahsilat_kurali'] = tah_kural
            snap['tahsilat_kural_etiket'] = tahsilat_kural_etiket(tah_kural)
            snap['tahsilat_gun_sayisi'] = hdr['tahsilat_gun_sayisi'] if 'tahsilat_gun_sayisi' in hdr.keys() else None
            snap['tahsilat_sabit_tarih'] = hdr['tahsilat_sabit_tarih'] if 'tahsilat_sabit_tarih' in hdr.keys() else None
            snap['planlanan_tahsilat_tarihi'] = hdr['planlanan_tahsilat_tarihi'] if 'planlanan_tahsilat_tarihi' in hdr.keys() else None
            snap['tahsilat_sozu'] = hdr['tahsilat_sozu'] if 'tahsilat_sozu' in hdr.keys() else None
            snap['tahsilat_notu'] = hdr['tahsilat_notu'] if 'tahsilat_notu' in hdr.keys() else None
            snap['cek_teslim_tarihi'] = hdr['cek_teslim_tarihi'] if 'cek_teslim_tarihi' in hdr.keys() else None
            snap['cek_vadesi'] = hdr['cek_vadesi'] if 'cek_vadesi' in hdr.keys() else None
            hesap = hesapla_tahsilat_plani(
                tah_kural,
                gun_sayisi=snap.get('tahsilat_gun_sayisi'),
                sabit_tarih=snap.get('tahsilat_sabit_tarih'),
                referans_tarih=(hdr['olusturma_tarihi'] or '')[:10] if 'olusturma_tarihi' in hdr.keys() else None,
            )
            snap['tahsilat_durum_metin'] = hesap.get('durum_metin')

    for key in PLANLAMA_KOPRU_SNAPSHOT_ALANLARI:
        snap.setdefault(key, None)
    snap['snapshot_hash'] = snapshot_hash(snap)
    return snap


def _etki_onizleme(con, snap: dict) -> dict:
    vade = snap.get('vade_gun')
    risk = snap.get('risk_sonucu')
    etki = {'vade_gun': vade, 'risk_sonucu': risk or 'henuz_yok'}
    std_vade = 60
    try:
        v = int(vade) if vade not in (None, '') else std_vade
    except (TypeError, ValueError):
        v = std_vade
        etki['vade_eksik'] = True
    if v > std_vade or (risk and str(risk).upper() not in ('', 'NORMAL', 'NONE')):
        etki['yonetim_adimi_gerekli'] = True
    else:
        etki['yonetim_adimi_gerekli'] = False
    return etki


def _adimlar_olustur(etki: dict) -> list[dict]:
    adimlar = [
        {'sira': 1, 'adim_tipi': 'FINANS_INCELEME', 'kademe': 'K2', 'rol_adi': 'Muhasebe', 'durum': 'BEKLIYOR'},
    ]
    if etki.get('yonetim_adimi_gerekli'):
        adimlar.append(
            {'sira': 2, 'adim_tipi': 'YONETIM_ONAY', 'kademe': 'K3', 'rol_adi': 'Yönetim', 'durum': 'BEKLIYOR'},
        )
    return adimlar


def satis_onaya_gonder(con, siparis_id: int, talep_eden_id: int, revizyon_no: int = 1) -> dict[str, Any]:
    hdr = con.execute(
        'SELECT id, siparis_no, durum, olusturan_id FROM nexgen_planlama_siparis WHERE id=?',
        (siparis_id,),
    ).fetchone()
    if not hdr:
        return {'ok': False, 'hata': 'Sipariş bulunamadı.'}
    durum = (hdr['durum'] or '').upper()
    if durum not in ('TASLAK', 'REVIZYON', 'REDDEDILDI'):
        return {'ok': False, 'hata': f'Onaya gönderilemez: {durum}'}

    # T1: Gönder öncesi cari + ticari şart zorunlu (JSON 400/403/404)
    try:
        from modules.nexgen.pzm_siparis_write import (
            PzmWriteError,
            pzm_cari_dogrula,
            pzm_gonder_ticari_hazir_mi,
        )
        pzm_gonder_ticari_hazir_mi(con, siparis_id)
        row_c = con.execute(
            'SELECT cari_id FROM nexgen_planlama_siparis WHERE id=?', (siparis_id,),
        ).fetchone()
        if row_c and row_c['cari_id'] is not None:
            pzm_cari_dogrula(con, row_c['cari_id'], uid=talep_eden_id)
    except PzmWriteError as e:
        return {'ok': False, 'hata': e.message, 'status': e.status}

    if aktif_talep_var(con, KAYNAK_MODUL, siparis_id, TALEP_TIPI):
        return {'ok': False, 'hata': 'Aktif onay talebi zaten var.', 'code': 'DUPLICATE'}

    snap = satis_snapshot_olustur(con, siparis_id)
    etki = _etki_onizleme(con, snap)
    idem = f'{TALEP_TIPI}:{siparis_id}:rev{revizyon_no}'

    r = talep_olustur(
        con,
        talep_tipi=TALEP_TIPI,
        kaynak_modul=KAYNAK_MODUL,
        kaynak_id=siparis_id,
        kaynak_kod=hdr['siparis_no'],
        talep_eden_id=talep_eden_id,
        snapshot=snap,
        etki=etki,
        cari_id=snap.get('cari_id'),
        cari_unvan=snap.get('cari_unvan_snapshot'),
        tutar=(
            float(snap['toplam_tutar'])
            if snap.get('toplam_tutar') not in (None, '')
            else (float(snap['fiyat']) if snap.get('fiyat') not in (None, '') else None)
        ),
        para_birimi=snap.get('para_birimi'),
        vade_gun=int(snap['vade_gun']) if snap.get('vade_gun') not in (None, '') else None,
        idempotency_key=idem,
        adimlar=_adimlar_olustur(etki),
        revizyon_no=revizyon_no,
    )
    if not r.get('ok'):
        return r

    snap['onay_talep_id'] = r['talep_id']
    snap['snapshot_hash'] = snapshot_hash(snap)
    snap_json = json.dumps(snap, ensure_ascii=False)

    con.execute(
        """
        UPDATE nexgen_planlama_siparis
        SET durum='ONAY_BEKLIYOR',
            guncelleme_tarihi=datetime('now','localtime')
        WHERE id=?
        """,
        (siparis_id,),
    )
    con.execute(
        'UPDATE onay_talep SET snapshot_json=? WHERE id=?',
        (snap_json, r['talep_id']),
    )
    adapter_log(
        con, talep_id=r['talep_id'], adapter_kodu=ADAPTER,
        kaynak_modul=KAYNAK_MODUL, islem='ONAYA_GONDER', sonuc='OK',
        payload={'siparis_id': siparis_id, 'siparis_no': hdr['siparis_no']},
    )
    return {
        'ok': True,
        'talep_id': r['talep_id'],
        'talep_kod': r['talep_kod'],
        'siparis_id': siparis_id,
        'siparis_no': hdr['siparis_no'],
        'durum': 'ONAY_BEKLIYOR',
    }


def satis_onay_sonrasi_uygula(con, talep_id: int) -> dict[str, Any]:
    """Tüm adımlar ONAYLANDI — aynı sipariş ONAYLANDI; Pazarlama ekranına (idempotent)."""
    talep = con.execute('SELECT * FROM onay_talep WHERE id=?', (talep_id,)).fetchone()
    if not talep or talep['durum'] != 'ONAYLANDI':
        return {'ok': False, 'hata': 'Talep onaylı değil.'}

    siparis_id = int(talep['kaynak_id'])
    dup = con.execute(
        """
        SELECT 1 FROM onay_adapter_log
        WHERE talep_id=? AND adapter_kodu=? AND islem='PAZARLAMA_ONAY_KOPRU' AND sonuc='OK'
        """,
        (talep_id, ADAPTER),
    ).fetchone()
    if dup:
        return {'ok': True, 'skip': True, 'siparis_id': siparis_id}

    snap = json.loads(talep['snapshot_json'] or '{}')
    snap['onay_talep_id'] = talep_id
    snap_json = json.dumps(snap, ensure_ascii=False)

    con.execute(
        """
        UPDATE nexgen_planlama_siparis
        SET durum='ONAYLANDI',
            onay_snapshot_json=?,
            guncelleme_tarihi=datetime('now','localtime')
        WHERE id=?
        """,
        (snap_json, siparis_id),
    )
    adapter_log(
        con, talep_id=talep_id, adapter_kodu=ADAPTER,
        kaynak_modul=KAYNAK_MODUL, islem='PAZARLAMA_ONAY_KOPRU', sonuc='OK',
        payload={'siparis_id': siparis_id, 'siparis_no': talep['kaynak_kod']},
    )
    shadow_olay(con, 'SATIS_SIPARISI_ONAYLANDI', {
        'talep_id': talep_id,
        'kaynak_modul': KAYNAK_MODUL,
        'kaynak_id': siparis_id,
        'siparis_no': talep['kaynak_kod'],
    })
    return {'ok': True, 'siparis_id': siparis_id, 'durum': 'ONAYLANDI'}


def satis_revizyon_uygula(con, talep_id: int, notu: str) -> None:
    talep = con.execute('SELECT kaynak_id FROM onay_talep WHERE id=?', (talep_id,)).fetchone()
    if not talep:
        return
    sid = int(talep['kaynak_id'])
    row = con.execute(
        'SELECT kaynak_modul FROM nexgen_planlama_siparis WHERE id=?', (sid,),
    ).fetchone()
    if row and (row['kaynak_modul'] or '') == 'MUSTERI_OPERASYONU':
        from modules.nexgen.mo_siparis_talep_service import revizyon_uygula as mo_rev
        mo_rev(con, sid, notu)
        return
    con.execute(
        """
        UPDATE nexgen_planlama_siparis
        SET durum='REVIZYON', notlar=COALESCE(notlar,'') || ?, guncelleme_tarihi=datetime('now','localtime')
        WHERE id=?
        """,
        (f'\n[ONAY REVIZYON] {notu}', sid),
    )


def satis_red_uygula(con, talep_id: int, notu: str) -> None:
    talep = con.execute('SELECT kaynak_id FROM onay_talep WHERE id=?', (talep_id,)).fetchone()
    if not talep:
        return
    sid = int(talep['kaynak_id'])
    row = con.execute(
        'SELECT kaynak_modul FROM nexgen_planlama_siparis WHERE id=?', (sid,),
    ).fetchone()
    if row and (row['kaynak_modul'] or '') == 'MUSTERI_OPERASYONU':
        from modules.nexgen.mo_siparis_talep_service import red_uygula as mo_red
        mo_red(con, sid, notu)
        return
    con.execute(
        """
        UPDATE nexgen_planlama_siparis
        SET durum='REDDEDILDI', notlar=COALESCE(notlar,'') || ?, guncelleme_tarihi=datetime('now','localtime')
        WHERE id=?
        """,
        (f'\n[ONAY RED] {notu}', sid),
    )


def karar_sonrasi_adapter(con, talep_id: int, karar_sonuc: dict) -> None:
    if not karar_sonuc.get('ok'):
        return
    durum = karar_sonuc.get('durum')
    if durum == 'ONAYLANDI' and karar_sonuc.get('tamamlandi'):
        satis_onay_sonrasi_uygula(con, talep_id)
    elif durum == 'REVIZYON':
        adim = con.execute(
            "SELECT karar_notu FROM onay_talep_adim WHERE talep_id=? AND durum='REVIZYON' ORDER BY id DESC LIMIT 1",
            (talep_id,),
        ).fetchone()
        satis_revizyon_uygula(con, talep_id, (adim['karar_notu'] if adim else '') or '')
    elif durum == 'REDDEDILDI':
        adim = con.execute(
            "SELECT karar_notu FROM onay_talep_adim WHERE talep_id=? AND durum='REDDEDILDI' ORDER BY id DESC LIMIT 1",
            (talep_id,),
        ).fetchone()
        satis_red_uygula(con, talep_id, (adim['karar_notu'] if adim else '') or '')


def siparis_detay_snapshot(con, siparis_id: int) -> dict | None:
    """Mehmet detay ekranı — onaylı snapshot kaynağı."""
    row = con.execute(
        'SELECT onay_snapshot_json, durum FROM nexgen_planlama_siparis WHERE id=?',
        (siparis_id,),
    ).fetchone()
    if not row or not row['onay_snapshot_json']:
        return None
    try:
        return json.loads(row['onay_snapshot_json'])
    except Exception:
        return None
