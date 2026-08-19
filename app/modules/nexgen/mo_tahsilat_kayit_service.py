# -*- coding: utf-8 -*-
"""MO tahsilat kaydı servisi — taslak, yönetim onayı, idempotency."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from modules.nexgen.mo_gorusme_service import can_mo_gorusme_yaz
from modules.nexgen.mo_siparis_talep_service import can_mo_siparis_yaz, mo_siparis_payload_unpack
from modules.nexgen.mo_tahsilat_config import (
    CARI_ENTEGRASYON_AKTIF,
    KAYIT_DURUM_ETIKET,
    KAYNAK_MUSTERI_OPERASYONU,
    KAYIT_DURUM_MUHASEBE_BEKLIYOR,   # alias → YONETIM_ONAY_BEKLIYOR
    KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR,
    KAYIT_DURUM_ISTISNA_ONAY_BEKLIYOR,
    KAYIT_DURUM_YONETIM_ONAYLANDI,
    KAYIT_DURUM_ONAYLANDI,
    KAYIT_DURUM_REDDEDILDI,
    KAYIT_DURUM_REVIZYON,
    KAYIT_DURUM_TASLAK,
    KAYIT_DUZENLENEBILIR,
    ODEME_SEKILLERI,
    PLAN_DURUM_KAYIT_GIRILDI,
    PLAN_DURUM_MUHASEBE_BEKLIYOR,
    PLAN_DURUM_TAMAMLANDI,
    TAHSILAT_EDILEN_DURUMLARI,
    TAHSILAT_TIPI_NORMAL,
    TAHSILAT_TIPI_AVANS,
    TAHSILAT_TIPLERI,
)
from modules.nexgen.mo_tahsilat_plan_service import beklenen_tutar_hesapla


class MoTahsilatError(Exception):
    def __init__(self, mesaj: str, kod: int = 400):
        self.mesaj = mesaj
        self.kod = kod
        super().__init__(mesaj)


_MSG_MANUEL_KUR_ZORUNLU = 'Manuel kur girilmeden devam edilemez.'
_MSG_MANUEL_KUR_GECERSIZ = 'Geçerli bir manuel kur girin.'


def _parse_manuel_kur_raw(raw, *, zorunlu: bool = False) -> float | None:
    """Manuel kur parse — virgül/nokta kabul; 0/negatif/geçersiz reddedilir."""
    if raw in (None, ''):
        if zorunlu:
            raise MoTahsilatError(_MSG_MANUEL_KUR_ZORUNLU, 400)
        return None
    if raw == 0:
        raise MoTahsilatError(_MSG_MANUEL_KUR_GECERSIZ, 400)
    try:
        val = float(str(raw).replace(',', '.'))
    except (TypeError, ValueError):
        raise MoTahsilatError(_MSG_MANUEL_KUR_GECERSIZ, 400)
    import math
    if not math.isfinite(val) or val <= 0:
        raise MoTahsilatError(_MSG_MANUEL_KUR_GECERSIZ, 400)
    return val


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _tablo_var(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _kolon_var(con: sqlite3.Connection, tablo: str, kolon: str) -> bool:
    if not _tablo_var(con, tablo):
        return False
    return kolon in [c[1] for c in con.execute(f'PRAGMA table_info({tablo})').fetchall()]


def _sevk_tahsilat_kolonlari_var(con: sqlite3.Connection) -> bool:
    return _kolon_var(con, 'mo_tahsilat_kayit', 'sevkiyat_id')


def _tahsilat_tipi_kolon_var(con: sqlite3.Connection) -> bool:
    return _kolon_var(con, 'mo_tahsilat_kayit', 'tahsilat_tipi')


def _is_avans_norm(norm: dict[str, Any]) -> bool:
    """norm dict'inde AVANS tipi seçilmiş mi?"""
    return (norm.get('tahsilat_tipi') or '').upper() == TAHSILAT_TIPI_AVANS


def _tcmb_snapshot_kolonlari_var(con: sqlite3.Connection) -> bool:
    return _kolon_var(con, 'mo_tahsilat_kayit', 'sevk_kalan_fx_snapshot')


def _kur_tarihi_sevk_belirle(
    con: sqlite3.Connection,
    sevkiyat_id: int,
    *,
    aday: dict[str, Any] | None = None,
) -> str:
    """Kur tarihi = seçili sevkiyatın gerçek sevk tarihi (tahsilat/çek tarihi değil)."""
    tarih = ''
    if aday and aday.get('sevk_tarihi'):
        tarih = str(aday['sevk_tarihi'])[:10]
    if not tarih:
        row = con.execute(
            'SELECT sevk_tarihi FROM mo_musteri_sevkiyat WHERE id=? AND aktif=1',
            (int(sevkiyat_id),),
        ).fetchone()
        if row:
            tarih = (row['sevk_tarihi'] or '')[:10]
    if not tarih:
        raise MoTahsilatError('Gerçek sevk tarihi zorunludur (kur tarihi).', 400)
    return tarih


def _recalc_try_kalan(norm: dict[str, Any]) -> None:
    odeme = (norm.get('odeme_tipi') or '').upper()
    hedef = norm.get('paket_hedef_tutar') if odeme == 'CEK' else norm.get('beklenen_tutar')
    alinan = norm.get('alinan_tutar')
    if hedef is None or alinan is None:
        return
    kalan = round(max(float(hedef) - float(alinan), 0), 2)
    norm['kalan_tutar'] = kalan
    norm['kismi_mi'] = 1 if kalan > 0.009 else 0


def _fill_missing_cek_paket_hedef(norm: dict[str, Any]) -> None:
    """CEK taslağında paket_hedef_tutar boşsa frozen snapshot'tan deterministik olarak tamamla.

    Koşulların tamamı sağlanmalı:
    - odeme_tipi == 'CEK'
    - paket_hedef_tutar is None
    - tcmb_satis_kur_snapshot sayısal ve pozitif
    - sevk_kalan_fx_snapshot sayısal ve negatif değil

    Diğer hiçbir alan değiştirilmez; sistem_kur lookup yapılmaz.
    """
    if (norm.get('odeme_tipi') or '').upper() != 'CEK':
        return
    if norm.get('paket_hedef_tutar') is not None:
        return
    kur = norm.get('tcmb_satis_kur_snapshot')
    fx = norm.get('sevk_kalan_fx_snapshot')
    if kur is None or fx is None:
        return
    try:
        kur_f = float(kur)
        fx_f = float(fx)
    except (TypeError, ValueError):
        return
    import math
    if not math.isfinite(kur_f) or not math.isfinite(fx_f):
        return
    if kur_f < 0 or fx_f < 0:
        return
    norm['paket_hedef_tutar'] = round(fx_f * kur_f, 2)


def _load_frozen_tcmb_snapshots(
    con: sqlite3.Connection,
    norm: dict[str, Any],
    kayit_id: int,
) -> bool:
    """Mevcut TCMB snapshot doluysa norm'a yükle; True = freeze korundu."""
    if not _tcmb_snapshot_kolonlari_var(con):
        return False
    row = con.execute(
        """
        SELECT sevk_kalan_fx_snapshot, sevk_para_birimi_snapshot,
               tcmb_satis_kur_snapshot, kur_tarihi_snapshot,
               sevk_hedef_tutar_snapshot, para_birimi,
               beklenen_tutar, paket_hedef_tutar
        FROM mo_tahsilat_kayit WHERE id=? AND aktif=1
        """,
        (int(kayit_id),),
    ).fetchone()
    if not row or row['tcmb_satis_kur_snapshot'] in (None, ''):
        return False
    norm['sevk_kalan_fx_snapshot'] = row['sevk_kalan_fx_snapshot']
    norm['sevk_para_birimi_snapshot'] = row['sevk_para_birimi_snapshot']
    norm['tcmb_satis_kur_snapshot'] = row['tcmb_satis_kur_snapshot']
    norm['kur_tarihi_snapshot'] = row['kur_tarihi_snapshot']
    norm['sevk_hedef_tutar_snapshot'] = row['sevk_hedef_tutar_snapshot']
    norm['para_birimi'] = row['para_birimi'] or 'TRY'
    norm['beklenen_tutar'] = row['beklenen_tutar']
    norm['paket_hedef_tutar'] = row['paket_hedef_tutar']
    norm['beklenen_tahmini'] = 0
    _fill_missing_cek_paket_hedef(norm)
    _recalc_try_kalan(norm)
    return True


def _bind_sevkiyat_taslak_fx_legacy(
    norm: dict[str, Any],
    sevk_kalan: float,
    sevk_hedef: float,
    sevk_pb: str,
) -> None:
    """Migration 155 öncesi / TCMB kolonları yok — döviz hedef (legacy)."""
    norm['sevk_para_birimi_snapshot'] = sevk_pb
    norm['para_birimi'] = sevk_pb
    norm['beklenen_tahmini'] = 0
    if norm['odeme_tipi'] == 'CEK':
        if norm['paket_hedef_tutar'] is None:
            norm['paket_hedef_tutar'] = sevk_kalan
        elif float(norm['paket_hedef_tutar']) > sevk_kalan + 0.009:
            raise MoTahsilatError(
                f'Paket hedef tutarı sevk kalanını aşıyor (kalan={sevk_kalan}).', 409,
            )
    else:
        if norm['beklenen_tutar'] is None:
            norm['beklenen_tutar'] = sevk_kalan
        elif float(norm['beklenen_tutar']) > sevk_kalan + 0.009:
            raise MoTahsilatError(
                f'Beklenen tutar sevk kalanını aşıyor (kalan={sevk_kalan}).', 409,
            )


def _tahsil_edilen_sevk(
    con: sqlite3.Connection,
    sevkiyat_id: int,
    *,
    haric_kayit_id: int | None = None,
) -> float:
    """Sevkiyat PB cinsinden tahsil edilen / rezerve miktar (FX-aware)."""
    if not _tablo_var(con, 'mo_tahsilat_kayit') or not _sevk_tahsilat_kolonlari_var(con):
        return 0.0
    from modules.nexgen.mo_tahsilat_sevk_service import sevk_hedef_hesapla, sevk_tahsil_kalan_hesapla

    hedef_info = sevk_hedef_hesapla(con, sevkiyat_id)
    info = sevk_tahsil_kalan_hesapla(
        con,
        sevkiyat_id,
        hedef_info.get('sevk_hedef_tutar'),
        hedef_info.get('para_birimi'),
        haric_kayit_id=haric_kayit_id,
    )
    if info.get('kur_hesap_hatasi'):
        return 0.0
    return float(info.get('tahsil_edilen_fx') or 0.0)


def _bind_sevkiyat_taslak(
    con: sqlite3.Connection,
    norm: dict[str, Any],
    sevkiyat_id: int,
    *,
    kayit_id: int | None = None,
    preserve_tcmb_snapshot: bool = False,
) -> None:
    """Sevkiyat bağlantısı + manuel kur → TRY hedef snapshot freeze."""
    from modules.nexgen.mo_tahsilat_sevk_service import tahsilat_sevk_write_guard

    if not norm.get('siparis_id'):
        raise MoTahsilatError('Sevkiyat bağlantısı için siparis_id zorunlu.', 400)
    aday = tahsilat_sevk_write_guard(
        con,
        cari_id=int(norm['cari_id']),
        siparis_id=int(norm['siparis_id']),
        sevkiyat_id=int(sevkiyat_id),
    )
    sevk_kalan_fx = float(aday['kalan'])
    sevk_hedef = float(aday['sevk_hedef_tutar'])
    sevk_pb = (aday.get('para_birimi') or 'TRY').upper()

    norm['sevkiyat_id'] = int(sevkiyat_id)
    norm['sevk_hedef_tutar_snapshot'] = sevk_hedef

    if preserve_tcmb_snapshot and kayit_id and _load_frozen_tcmb_snapshots(con, norm, int(kayit_id)):
        return

    if not _tcmb_snapshot_kolonlari_var(con):
        _bind_sevkiyat_taslak_fx_legacy(norm, sevk_kalan_fx, sevk_hedef, sevk_pb)
        return

    kur_tarihi = _kur_tarihi_sevk_belirle(con, int(sevkiyat_id), aday=aday)

    # Manuel kur: frontend'den gelen tcmb_satis_kur_snapshot veya manuel_fx_kur
    manuel_kur_raw = norm.get('tcmb_satis_kur_snapshot') if not preserve_tcmb_snapshot else None
    if manuel_kur_raw is None:
        manuel_kur_raw = norm.get('manuel_fx_kur')

    if sevk_pb in ('USD', 'EUR'):
        manuel_kur_f = _parse_manuel_kur_raw(manuel_kur_raw, zorunlu=True)
        try_hedef = round(sevk_kalan_fx * float(manuel_kur_f), 2)
        norm['sevk_kalan_fx_snapshot'] = round(sevk_kalan_fx, 6)
        norm['sevk_para_birimi_snapshot'] = sevk_pb
        norm['tcmb_satis_kur_snapshot'] = manuel_kur_f
        norm['kur_tarihi_snapshot'] = kur_tarihi
        if aday.get('sevk_tarihi'):
            norm['gercek_sevk_tarihi_snapshot'] = str(aday['sevk_tarihi'])[:10]
        norm['para_birimi'] = 'TRY'
        norm['beklenen_tahmini'] = 0
        if norm['odeme_tipi'] == 'CEK':
            norm['paket_hedef_tutar'] = try_hedef
        else:
            norm['beklenen_tutar'] = try_hedef
        _recalc_try_kalan(norm)
        return

    if sevk_pb == 'TRY':
        # TRY: manuel kur gerekmez; TCMB lookup yok
        try_hedef = sevk_kalan_fx
        norm['sevk_kalan_fx_snapshot'] = round(sevk_kalan_fx, 6)
        norm['sevk_para_birimi_snapshot'] = sevk_pb
        norm['tcmb_satis_kur_snapshot'] = 1.0
        norm['kur_tarihi_snapshot'] = kur_tarihi
        if aday.get('sevk_tarihi'):
            norm['gercek_sevk_tarihi_snapshot'] = str(aday['sevk_tarihi'])[:10]
        norm['para_birimi'] = 'TRY'
        norm['beklenen_tahmini'] = 0
        if norm['odeme_tipi'] == 'CEK':
            norm['paket_hedef_tutar'] = try_hedef
        else:
            norm['beklenen_tutar'] = try_hedef
        _recalc_try_kalan(norm)
        return

    raise MoTahsilatError(_MSG_MANUEL_KUR_ZORUNLU, 400)


def _sevk_onay_kontrol(con: sqlite3.Connection, kayit_id: int) -> None:
    """Onaya gönder öncesi sevk kalan + double-count kontrolü."""
    if not _sevk_tahsilat_kolonlari_var(con):
        return
    row = con.execute(
        """
        SELECT sevkiyat_id, siparis_id, cari_id, odeme_tipi, alinan_tutar,
               paket_hedef_tutar, beklenen_tutar, sevk_hedef_tutar_snapshot,
               tcmb_satis_kur_snapshot, durum
        FROM mo_tahsilat_kayit WHERE id=? AND aktif=1
        """,
        (kayit_id,),
    ).fetchone()
    if not row or not row['sevkiyat_id']:
        return

    from modules.nexgen.mo_tahsilat_sevk_service import tahsilat_sevk_write_guard

    sevkiyat_id = int(row['sevkiyat_id'])
    siparis_id = int(row['siparis_id'] or 0)
    cari_id = int(row['cari_id'] or 0)
    if not siparis_id:
        raise MoTahsilatError('Sevkiyat bağlı kayıtta siparis_id zorunlu.', 400)

    tahsilat_sevk_write_guard(
        con, cari_id=cari_id, siparis_id=siparis_id, sevkiyat_id=sevkiyat_id,
    )

    odeme = (row['odeme_tipi'] or '').upper()
    tutar = float(row['alinan_tutar'] or 0)

    if row['tcmb_satis_kur_snapshot'] not in (None, ''):
        hedef_try = float(
            row['paket_hedef_tutar'] if odeme == 'CEK' else (row['beklenen_tutar'] or 0),
        )
        if tutar <= 0 and odeme == 'CEK' and row['paket_hedef_tutar'] not in (None, ''):
            tutar = float(row['paket_hedef_tutar'] or 0)
        if tutar <= 0:
            raise MoTahsilatError('Onaya göndermek için alınan tutar zorunlu.', 400)
        return

    from modules.nexgen.mo_tahsilat_sevk_service import sevk_hedef_hesapla, sevk_tahsil_kalan_hesapla

    hedef = row['sevk_hedef_tutar_snapshot']
    if hedef in (None, ''):
        hi = sevk_hedef_hesapla(con, sevkiyat_id)
        hedef = hi.get('sevk_hedef_tutar')
    if hedef in (None, ''):
        raise MoTahsilatError('Sevk hedef tutarı hesaplanamadı.', 409)

    hi = sevk_hedef_hesapla(con, sevkiyat_id)
    kalan_info = sevk_tahsil_kalan_hesapla(
        con, sevkiyat_id, hedef, hi.get('para_birimi'), haric_kayit_id=kayit_id,
    )
    kalan_fx = kalan_info.get('kalan_fx')
    if kalan_fx is None:
        raise MoTahsilatError('Sevk kalan tutarı hesaplanamadı.', 409)
    sevk_pb = (hi.get('para_birimi') or 'TRY').upper()
    kur = None
    if row['tcmb_satis_kur_snapshot'] not in (None, ''):
        try:
            kur = float(row['tcmb_satis_kur_snapshot'])
        except (TypeError, ValueError):
            kur = None
    if sevk_pb in ('USD', 'EUR') and kur and kur > 0:
        kalan_karsilastir = round(float(kalan_fx) * kur, 2)
    else:
        kalan_karsilastir = round(float(kalan_fx), 2)

    if odeme == 'CEK':
        if tutar <= 0 and row['paket_hedef_tutar'] not in (None, ''):
            tutar = float(row['paket_hedef_tutar'] or 0)
    if tutar <= 0:
        raise MoTahsilatError('Onaya göndermek için alınan tutar zorunlu.', 400)


def _kayit_kodu_uret(con) -> str:
    yil = datetime.now().year
    prefix = f'MO-T-{yil}-'
    row = con.execute(
        "SELECT kayit_kodu FROM mo_tahsilat_kayit WHERE kayit_kodu LIKE ? ORDER BY id DESC LIMIT 1",
        (prefix + '%',),
    ).fetchone()
    son = 0
    if row and row['kayit_kodu']:
        try:
            son = int(str(row['kayit_kodu']).split('-')[-1])
        except ValueError:
            son = 0
    return f'{prefix}{son + 1:04d}'


def can_muhasebe_onay(yk: set[str] | None) -> bool:
    """Yönetim/onay kararı verebilen kullanıcılar tahsilat kaydı açamaz."""
    if not yk:
        return False
    if '*' in yk:
        return True
    return (
        'onay.merkez.karar:can_approve' in yk
        or 'onay.finans.karar:can_approve' in yk
        or 'onay.yonetim.karar:can_approve' in yk
        or 'finans.tahsilat.write:can_approve' in yk
    )


def _siparis_plan_ozet(con, siparis_id: int) -> dict | None:
    row = con.execute(
        """
        SELECT ps.*, c.unvan AS cari_unvan
        FROM nexgen_planlama_siparis ps
        LEFT JOIN nexgen_cari c ON c.id = ps.cari_id
        WHERE ps.id=?
        """,
        (siparis_id,),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    mo = mo_siparis_payload_unpack(d.get('talep_referansi')) or {}
    tutar, tahmini = beklenen_tutar_hesapla(d, mo)
    return {
        'siparis_id': d['id'],
        'siparis_no': d.get('siparis_no'),
        'cari_id': d.get('cari_id'),
        'cari_unvan': d.get('cari_unvan'),
        'planlanan_tahsilat_tarihi': d.get('planlanan_tahsilat_tarihi'),
        'tahsilat_durumu': d.get('tahsilat_durumu'),
        'beklenen_tutar': tutar,
        'beklened_tahmini': tahmini,
        'para_birimi': d.get('anlasma_para_birimi') or 'TRY',
        'siparis_kur': d.get('kur'),
        'siparis_kur_tarihi': (d.get('kur_tarihi') or '')[:10] or None,
    }


def _validate_payload(payload: dict, *, zorunlu_gonder: bool = False) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise MoTahsilatError('JSON gövde gerekli.', 400)
    idem = (payload.get('idempotency_key') or '').strip()
    if not idem:
        raise MoTahsilatError('idempotency_key zorunlu.', 400)
    try:
        cari_id = int(payload.get('cari_id') or 0)
    except (TypeError, ValueError):
        cari_id = 0
    if not cari_id:
        raise MoTahsilatError('Müşteri zorunlu.', 400)
    siparis_id = payload.get('siparis_id')
    if siparis_id not in (None, ''):
        try:
            siparis_id = int(siparis_id)
        except (TypeError, ValueError):
            raise MoTahsilatError('Geçersiz sipariş.', 400)
    else:
        siparis_id = None
    sevkiyat_id = payload.get('sevkiyat_id')
    if sevkiyat_id not in (None, ''):
        try:
            sevkiyat_id = int(sevkiyat_id)
        except (TypeError, ValueError):
            raise MoTahsilatError('Geçersiz sevkiyat.', 400)
    else:
        sevkiyat_id = None
    alinan = payload.get('alinan_tutar')
    if zorunlu_gonder and alinan in (None, ''):
        raise MoTahsilatError('Alınan tutar zorunlu.', 400)
    alinan_f = None
    if alinan not in (None, ''):
        try:
            alinan_f = round(float(alinan), 2)
        except (TypeError, ValueError):
            raise MoTahsilatError('Geçersiz alınan tutar.', 400)
        if alinan_f <= 0:
            raise MoTahsilatError('Alınan tutar sıfırdan büyük olmalı.', 400)
    odeme = (payload.get('odeme_tipi') or payload.get('tahsilat_turu') or 'NAKIT').strip().upper()
    if odeme == 'NAKIT':
        pass
    elif odeme in ('CEK', 'HAVALE', 'SENET', 'DIGER'):
        pass
    else:
        odeme_map = {'nakit': 'NAKIT', 'cek': 'CEK', 'havale': 'HAVALE', 'senet': 'SENET', 'diger': 'DIGER'}
        odeme = odeme_map.get(odeme.lower(), odeme)
    if odeme not in ODEME_SEKILLERI:
        raise MoTahsilatError('Geçersiz ödeme tipi.', 400)
    kismi = bool(payload.get('kismi_mi'))
    beklenen = payload.get('beklenen_tutar')
    beklenen_f = None
    if beklenen not in (None, ''):
        try:
            beklenen_f = round(float(beklenen), 2)
        except (TypeError, ValueError):
            beklenen_f = None
    paket_hedef = payload.get('paket_hedef_tutar')
    paket_hedef_f = None
    if paket_hedef not in (None, ''):
        try:
            paket_hedef_f = round(float(paket_hedef), 2)
        except (TypeError, ValueError):
            raise MoTahsilatError('Geçersiz paket hedef tutarı.', 400)
        if paket_hedef_f <= 0:
            raise MoTahsilatError('Paket hedef tutarı sıfırdan büyük olmalı.', 400)

    kalan = payload.get('kalan_tutar')
    kalan_f = None
    if kalan not in (None, ''):
        try:
            kalan_f = round(float(kalan), 2)
        except (TypeError, ValueError):
            kalan_f = None
    elif odeme == 'CEK' and paket_hedef_f is not None and alinan_f is not None:
        kalan_f = round(max(paket_hedef_f - alinan_f, 0), 2)
        kismi = kalan_f > 0.009
    elif beklenen_f is not None and alinan_f is not None:
        kalan_f = round(max(beklenen_f - alinan_f, 0), 2)
        kismi = kalan_f > 0.009

    # tahsilat_tipi: NORMAL veya AVANS discriminator (Migration 164) — CEK validation'dan önce okunur
    raw_tip = (payload.get('tahsilat_tipi') or '').strip().upper()
    if raw_tip not in TAHSILAT_TIPLERI:
        raw_tip = TAHSILAT_TIPI_NORMAL

    if odeme == 'CEK':
        if not siparis_id:
            raise MoTahsilatError('Çek tahsilatında bağlı sipariş zorunludur.', 400)
        # AVANS modunda paket hedef tutarı zorunlu değil (gerçek sevkiyat yok, hedef belirsiz)
        if zorunlu_gonder and paket_hedef_f is None and raw_tip != TAHSILAT_TIPI_AVANS:
            raise MoTahsilatError('Çek paketi için hedef tutar zorunludur.', 400)

    manuel_kur_raw = payload.get('tcmb_satis_kur_snapshot')
    if manuel_kur_raw is None:
        manuel_kur_raw = payload.get('manuel_fx_kur')
    manuel_kur_f = _parse_manuel_kur_raw(manuel_kur_raw, zorunlu=False)

    return {
        'idempotency_key': idem,
        'cari_id': cari_id,
        'siparis_id': siparis_id,
        'sevkiyat_id': sevkiyat_id,
        'alinan_tutar': alinan_f,
        'alinan_tarih': (payload.get('alinan_tarih') or '')[:10] or None,
        'odeme_tipi': odeme,
        'odeme_referansi': (payload.get('odeme_referansi') or payload.get('referans') or '').strip() or None,
        'kismi_mi': 1 if kismi else 0,
        'kalan_tutar': kalan_f,
        'aciklama': (payload.get('aciklama') or '').strip() or None,
        'dosya_ref': (payload.get('dosya_ref') or '').strip() or None,
        'onay_notu': (payload.get('onay_notu') or '').strip() or None,
        'beklenen_tutar': beklenen_f,
        'paket_hedef_tutar': paket_hedef_f,
        'planlanan_tahsilat_tarihi': (payload.get('planlanan_tahsilat_tarihi') or '')[:10] or None,
        'tcmb_satis_kur_snapshot': manuel_kur_f,
        'manuel_fx_kur': manuel_kur_f,
        'tahsilat_tipi': raw_tip,
    }


def kayit_detay(con, kayit_id: int, kullanici_id: int, yk: set[str] | None = None) -> dict[str, Any]:
    if not _tablo_var(con, 'mo_tahsilat_kayit'):
        raise MoTahsilatError('Migration 126 uygulanmamış.', 503)
    row = con.execute('SELECT * FROM mo_tahsilat_kayit WHERE id=? AND aktif=1', (kayit_id,)).fetchone()
    if not row:
        raise MoTahsilatError('Kayıt bulunamadı.', 404)
    cid = int(row['cari_id'] or 0)
    if cid and not can_mo_gorusme_yaz(con, kullanici_id, cid, yk) and not can_muhasebe_onay(yk):
        raise MoTahsilatError('Bu kaydı görüntüleme yetkiniz yok.', 403)
    d = dict(row)
    d['durum_etiket'] = KAYIT_DURUM_ETIKET.get(d.get('durum'), (d.get('durum') or '').replace('_', ' '))
    d['cari_entegrasyon_mesaj'] = (
        'Cari entegrasyonu bekliyor'
        if d.get('durum') == KAYIT_DURUM_ONAYLANDI and d.get('cari_entegrasyon_durumu') != 'YAZILDI'
        else None
    )
    # CEK çek satırları
    if d.get('odeme_tipi') == 'CEK' and _tablo_var(con, 'mo_tahsilat_cek'):
        from modules.nexgen.mo_tahsilat_cek_service import cek_listele
        d['cek_satirlari'] = cek_listele(con, d['id'])
    else:
        d['cek_satirlari'] = []
    return d


def taslak_kaydet(
    con: sqlite3.Connection,
    payload: dict,
    kullanici_id: int,
    yk: set[str] | None = None,
    kayit_id: int | None = None,
) -> dict[str, Any]:
    if not _tablo_var(con, 'mo_tahsilat_kayit'):
        raise MoTahsilatError('Migration 126 uygulanmamış.', 503)
    norm = _validate_payload(payload)
    if not can_mo_gorusme_yaz(con, kullanici_id, int(norm['cari_id']), yk):
        raise MoTahsilatError('Bu cari için tahsilat kaydı yetkiniz yok.', 403)

    dup = con.execute(
        'SELECT id FROM mo_tahsilat_kayit WHERE idempotency_key=?', (norm['idempotency_key'],)
    ).fetchone()
    if dup and not kayit_id:
        return kayit_detay(con, int(dup['id']), kullanici_id, yk)

    if norm['siparis_id']:
        if not can_mo_siparis_yaz(con, kullanici_id, int(norm['cari_id']), yk):
            raise MoTahsilatError('Sipariş erişim yetkisi yok.', 403)
        plan = _siparis_plan_ozet(con, int(norm['siparis_id']))
        if not plan:
            raise MoTahsilatError('Bağlı sipariş bulunamadı.', 404)
        if int(plan['cari_id'] or 0) != int(norm['cari_id']):
            raise MoTahsilatError('Sipariş müşteri uyuşmuyor.', 400)
        if norm['odeme_tipi'] != 'CEK' and not norm.get('sevkiyat_id'):
            if norm['beklenen_tutar'] is None:
                norm['beklenen_tutar'] = plan.get('beklenen_tutar')
        if not norm['planlanan_tahsilat_tarihi']:
            norm['planlanan_tahsilat_tarihi'] = plan.get('planlanan_tahsilat_tarihi')

    sevk_kolon = _sevk_tahsilat_kolonlari_var(con)
    bind_sevkiyat_id = norm.get('sevkiyat_id')
    if kayit_id and not bind_sevkiyat_id:
        ex = con.execute(
            'SELECT sevkiyat_id FROM mo_tahsilat_kayit WHERE id=? AND aktif=1', (kayit_id,),
        ).fetchone()
        if ex and ex['sevkiyat_id']:
            bind_sevkiyat_id = int(ex['sevkiyat_id'])

    if bind_sevkiyat_id and sevk_kolon:
        preserve_tcmb = False
        if kayit_id and _tcmb_snapshot_kolonlari_var(con):
            ex_snap = con.execute(
                'SELECT tcmb_satis_kur_snapshot FROM mo_tahsilat_kayit WHERE id=? AND aktif=1',
                (kayit_id,),
            ).fetchone()
            preserve_tcmb = bool(ex_snap and ex_snap['tcmb_satis_kur_snapshot'] not in (None, ''))
        _bind_sevkiyat_taslak(
            con, norm, int(bind_sevkiyat_id),
            kayit_id=kayit_id, preserve_tcmb_snapshot=preserve_tcmb,
        )
    elif bind_sevkiyat_id and not sevk_kolon:
        raise MoTahsilatError('Migration 154 uygulanmamış.', 503)

    norm.setdefault('beklenen_tahmini', 1)
    if not norm.get('sevkiyat_id'):
        norm.pop('sevk_hedef_tutar_snapshot', None)
        norm.pop('sevk_para_birimi_snapshot', None)
        norm.pop('sevk_kalan_fx_snapshot', None)
        # AVANS modunda manuel kur kullanıcı tarafından girilmişse koru;
        # normal kayıtta sevkiyat yokken bu alan zaten boştur.
        if not _is_avans_norm(norm):
            norm.pop('tcmb_satis_kur_snapshot', None)
        norm.pop('kur_tarihi_snapshot', None)

    now = _now()
    if kayit_id:
        row = con.execute(
            'SELECT id, durum, olusturan_id FROM mo_tahsilat_kayit WHERE id=? AND aktif=1',
            (kayit_id,),
        ).fetchone()
        if not row:
            raise MoTahsilatError('Kayıt bulunamadı.', 404)
        if row['durum'] not in KAYIT_DUZENLENEBILIR:
            raise MoTahsilatError('Bu durumda düzenleme yapılamaz.', 409)
        if int(row['olusturan_id'] or 0) != kullanici_id:
            raise MoTahsilatError('Yalnız kendi kaydınızı düzenleyebilirsiniz.', 403)
        tahsilat_tipi_kolon = _tahsilat_tipi_kolon_var(con)
        if sevk_kolon:
            tcmb_kolon = _tcmb_snapshot_kolonlari_var(con)
            if tcmb_kolon:
                _tt_set = ", tahsilat_tipi=?" if tahsilat_tipi_kolon else ""
                _tt_val = (norm.get('tahsilat_tipi'),) if tahsilat_tipi_kolon else ()
                con.execute(
                    f"""
                    UPDATE mo_tahsilat_kayit SET
                        cari_id=?, siparis_id=?, sevkiyat_id=?, beklenen_tutar=?, beklenen_tahmini=?,
                        paket_hedef_tutar=?, alinan_tutar=?, kalan_tutar=?,
                        sevk_hedef_tutar_snapshot=?, sevk_para_birimi_snapshot=?,
                        sevk_kalan_fx_snapshot=?, tcmb_satis_kur_snapshot=?, kur_tarihi_snapshot=?,
                        para_birimi=?,
                        planlanan_tahsilat_tarihi=?, alinan_tarih=?, odeme_tipi=?, odeme_referansi=?,
                        kismi_mi=?, aciklama=?, dosya_ref=?, onay_notu=?, guncelleme_tarihi=?{_tt_set}
                    WHERE id=?
                    """,
                    (
                        norm['cari_id'], norm['siparis_id'], norm.get('sevkiyat_id'),
                        norm['beklenen_tutar'], norm.get('beklenen_tahmini', 1),
                        norm['paket_hedef_tutar'], norm['alinan_tutar'], norm['kalan_tutar'],
                        norm.get('sevk_hedef_tutar_snapshot'), norm.get('sevk_para_birimi_snapshot'),
                        norm.get('sevk_kalan_fx_snapshot'), norm.get('tcmb_satis_kur_snapshot'),
                        norm.get('kur_tarihi_snapshot'), norm.get('para_birimi'),
                        norm['planlanan_tahsilat_tarihi'], norm['alinan_tarih'], norm['odeme_tipi'],
                        norm['odeme_referansi'], norm['kismi_mi'], norm['aciklama'], norm['dosya_ref'],
                        norm['onay_notu'], now, *_tt_val, kayit_id,
                    ),
                )
            else:
                _tt_set = ", tahsilat_tipi=?" if tahsilat_tipi_kolon else ""
                _tt_val = (norm.get('tahsilat_tipi'),) if tahsilat_tipi_kolon else ()
                con.execute(
                    f"""
                    UPDATE mo_tahsilat_kayit SET
                        cari_id=?, siparis_id=?, sevkiyat_id=?, beklenen_tutar=?, beklenen_tahmini=?,
                        paket_hedef_tutar=?, alinan_tutar=?, kalan_tutar=?,
                        sevk_hedef_tutar_snapshot=?, sevk_para_birimi_snapshot=?, para_birimi=?,
                        planlanan_tahsilat_tarihi=?, alinan_tarih=?, odeme_tipi=?, odeme_referansi=?,
                        kismi_mi=?, aciklama=?, dosya_ref=?, onay_notu=?, guncelleme_tarihi=?{_tt_set}
                    WHERE id=?
                    """,
                    (
                        norm['cari_id'], norm['siparis_id'], norm.get('sevkiyat_id'),
                        norm['beklenen_tutar'], norm.get('beklenen_tahmini', 1),
                        norm['paket_hedef_tutar'], norm['alinan_tutar'], norm['kalan_tutar'],
                        norm.get('sevk_hedef_tutar_snapshot'), norm.get('sevk_para_birimi_snapshot'),
                        norm.get('para_birimi'),
                        norm['planlanan_tahsilat_tarihi'], norm['alinan_tarih'], norm['odeme_tipi'],
                        norm['odeme_referansi'], norm['kismi_mi'], norm['aciklama'], norm['dosya_ref'],
                        norm['onay_notu'], now, *_tt_val, kayit_id,
                    ),
                )
        else:
            _tt_set = ", tahsilat_tipi=?" if tahsilat_tipi_kolon else ""
            _tt_val = (norm.get('tahsilat_tipi'),) if tahsilat_tipi_kolon else ()
            con.execute(
                f"""
                UPDATE mo_tahsilat_kayit SET
                    cari_id=?, siparis_id=?, beklenen_tutar=?, paket_hedef_tutar=?, alinan_tutar=?, kalan_tutar=?,
                    planlanan_tahsilat_tarihi=?, alinan_tarih=?, odeme_tipi=?, odeme_referansi=?,
                    kismi_mi=?, aciklama=?, dosya_ref=?, onay_notu=?, guncelleme_tarihi=?{_tt_set}
                WHERE id=?
                """,
                (
                    norm['cari_id'], norm['siparis_id'], norm['beklenen_tutar'], norm['paket_hedef_tutar'],
                    norm['alinan_tutar'], norm['kalan_tutar'], norm['planlanan_tahsilat_tarihi'],
                    norm['alinan_tarih'], norm['odeme_tipi'], norm['odeme_referansi'], norm['kismi_mi'],
                    norm['aciklama'], norm['dosya_ref'], norm['onay_notu'], now, *_tt_val, kayit_id,
                ),
            )
        kid = kayit_id
    else:
        tahsilat_tipi_kolon = _tahsilat_tipi_kolon_var(con)
        _tt_col = ", tahsilat_tipi" if tahsilat_tipi_kolon else ""
        _tt_ph = ", ?" if tahsilat_tipi_kolon else ""
        _tt_val_ins = (norm.get('tahsilat_tipi'),) if tahsilat_tipi_kolon else ()
        if sevk_kolon:
            tcmb_kolon = _tcmb_snapshot_kolonlari_var(con)
            if tcmb_kolon:
                cur = con.execute(
                    f"""
                    INSERT INTO mo_tahsilat_kayit
                        (kayit_kodu, cari_id, siparis_id, sevkiyat_id, kaynak_modul, beklenen_tutar, beklenen_tahmini,
                         paket_hedef_tutar, alinan_tutar, kalan_tutar,
                         sevk_hedef_tutar_snapshot, sevk_para_birimi_snapshot,
                         sevk_kalan_fx_snapshot, tcmb_satis_kur_snapshot, kur_tarihi_snapshot,
                         para_birimi,
                         planlanan_tahsilat_tarihi, alinan_tarih, odeme_tipi, odeme_referansi, kismi_mi,
                         aciklama, dosya_ref, onay_notu, durum, cari_entegrasyon_durumu,
                         idempotency_key, olusturan_id, olusturma_tarihi, guncelleme_tarihi{_tt_col})
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?{_tt_ph})
                    """,
                    (
                        _kayit_kodu_uret(con), norm['cari_id'], norm['siparis_id'], norm.get('sevkiyat_id'),
                        KAYNAK_MUSTERI_OPERASYONU, norm['beklenen_tutar'], norm.get('beklenen_tahmini', 1),
                        norm['paket_hedef_tutar'], norm['alinan_tutar'], norm['kalan_tutar'],
                        norm.get('sevk_hedef_tutar_snapshot'), norm.get('sevk_para_birimi_snapshot'),
                        norm.get('sevk_kalan_fx_snapshot'), norm.get('tcmb_satis_kur_snapshot'),
                        norm.get('kur_tarihi_snapshot'), norm.get('para_birimi'),
                        norm['planlanan_tahsilat_tarihi'], norm['alinan_tarih'], norm['odeme_tipi'],
                        norm['odeme_referansi'], norm['kismi_mi'], norm['aciklama'], norm['dosya_ref'],
                        norm['onay_notu'], KAYIT_DURUM_TASLAK, 'BEKLIYOR', norm['idempotency_key'],
                        kullanici_id, now, now, *_tt_val_ins,
                    ),
                )
            else:
                cur = con.execute(
                    f"""
                    INSERT INTO mo_tahsilat_kayit
                        (kayit_kodu, cari_id, siparis_id, sevkiyat_id, kaynak_modul, beklenen_tutar, beklenen_tahmini,
                         paket_hedef_tutar, alinan_tutar, kalan_tutar,
                         sevk_hedef_tutar_snapshot, sevk_para_birimi_snapshot, para_birimi,
                         planlanan_tahsilat_tarihi, alinan_tarih, odeme_tipi, odeme_referansi, kismi_mi,
                         aciklama, dosya_ref, onay_notu, durum, cari_entegrasyon_durumu,
                         idempotency_key, olusturan_id, olusturma_tarihi, guncelleme_tarihi{_tt_col})
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?{_tt_ph})
                    """,
                    (
                        _kayit_kodu_uret(con), norm['cari_id'], norm['siparis_id'], norm.get('sevkiyat_id'),
                        KAYNAK_MUSTERI_OPERASYONU, norm['beklenen_tutar'], norm.get('beklenen_tahmini', 1),
                        norm['paket_hedef_tutar'], norm['alinan_tutar'], norm['kalan_tutar'],
                        norm.get('sevk_hedef_tutar_snapshot'), norm.get('sevk_para_birimi_snapshot'),
                        norm.get('para_birimi'),
                        norm['planlanan_tahsilat_tarihi'], norm['alinan_tarih'], norm['odeme_tipi'],
                        norm['odeme_referansi'], norm['kismi_mi'], norm['aciklama'], norm['dosya_ref'],
                        norm['onay_notu'], KAYIT_DURUM_TASLAK, 'BEKLIYOR', norm['idempotency_key'],
                        kullanici_id, now, now, *_tt_val_ins,
                    ),
                )
        else:
            cur = con.execute(
                f"""
                INSERT INTO mo_tahsilat_kayit
                    (kayit_kodu, cari_id, siparis_id, kaynak_modul, beklenen_tutar, beklenen_tahmini,
                     paket_hedef_tutar, alinan_tutar, kalan_tutar, planlanan_tahsilat_tarihi, alinan_tarih,
                     odeme_tipi, odeme_referansi, kismi_mi, aciklama, dosya_ref, onay_notu, durum,
                     cari_entegrasyon_durumu, idempotency_key, olusturan_id, olusturma_tarihi, guncelleme_tarihi{_tt_col})
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?{_tt_ph})
                """,
                (
                    _kayit_kodu_uret(con), norm['cari_id'], norm['siparis_id'], KAYNAK_MUSTERI_OPERASYONU,
                    norm['beklenen_tutar'], norm.get('beklenen_tahmini', 1), norm['paket_hedef_tutar'],
                    norm['alinan_tutar'], norm['kalan_tutar'], norm['planlanan_tahsilat_tarihi'],
                    norm['alinan_tarih'], norm['odeme_tipi'], norm['odeme_referansi'], norm['kismi_mi'],
                    norm['aciklama'], norm['dosya_ref'], norm['onay_notu'], KAYIT_DURUM_TASLAK, 'BEKLIYOR',
                    norm['idempotency_key'], kullanici_id, now, now, *_tt_val_ins,
                ),
            )
        kid = int(cur.lastrowid)

    # CEK: snapshot kolonları freeze
    if norm.get('odeme_tipi') == 'CEK' and norm['siparis_id']:
        _freeze_cek_snapshots(con, kid, norm['siparis_id'])

    if norm['siparis_id']:
        con.execute(
            """
            UPDATE nexgen_planlama_siparis
            SET tahsilat_durumu=?, guncelleme_tarihi=?
            WHERE id=? AND kaynak_modul=?
            """,
            (PLAN_DURUM_KAYIT_GIRILDI, now, norm['siparis_id'], KAYNAK_MUSTERI_OPERASYONU),
        )
    con.commit()
    return kayit_detay(con, kid, kullanici_id, yk)


def _freeze_cek_snapshots(con: sqlite3.Connection, kayit_id: int, siparis_id: int) -> None:
    """
    CEK paketi için parent snapshot kolonlarını doldur.
    Öncelik: mevcut snapshot dolu ise değiştirme (idempotent).
    AVANS: gercek_sevk_tarihi ve hedef_vade_tarihi hesaplanmaz (sevkiyat yok).
    """
    from modules.nexgen.mo_sevkiyat_service import gercek_sevk_tarihi
    from datetime import date, timedelta

    tt_col = _tahsilat_tipi_kolon_var(con)
    tt_select = ', tahsilat_tipi' if tt_col else ''
    row = con.execute(
        f'SELECT para_birimi, onaylanan_vade_gun_snapshot, gercek_sevk_tarihi_snapshot, '
        f'       hedef_vade_tarihi, paket_hedef_tutar, beklenen_tutar{tt_select} '
        'FROM mo_tahsilat_kayit WHERE id=?', (kayit_id,)
    ).fetchone()
    if not row:
        return

    # AVANS kaydında sevk tarihine dayalı hesaplar yapılmaz
    is_avans = tt_col and (row['tahsilat_tipi'] or '').upper() == TAHSILAT_TIPI_AVANS

    sip = con.execute(
        'SELECT vade_gun, anlasma_para_birimi FROM nexgen_planlama_siparis WHERE id=?',
        (siparis_id,)
    ).fetchone()
    if not sip:
        return

    now = _now()
    updates: list = []
    vals: list = []

    # para_birimi (parent kolonuna freeze)
    pb = (row['para_birimi'] if row['para_birimi'] else None) or (sip['anlasma_para_birimi'] or 'TRY')
    if not row['para_birimi']:
        updates.append('para_birimi=?')
        vals.append(pb)

    # onaylanan_vade_gun_snapshot
    if row['onaylanan_vade_gun_snapshot'] is None and sip['vade_gun'] is not None:
        updates.append('onaylanan_vade_gun_snapshot=?')
        vals.append(int(sip['vade_gun']))

    # gercek_sevk_tarihi_snapshot — AVANS'ta atla (sevkiyat henüz yok)
    sevk = row['gercek_sevk_tarihi_snapshot']
    if not sevk and not is_avans:
        sevk = gercek_sevk_tarihi(con, siparis_id)
        if sevk:
            updates.append('gercek_sevk_tarihi_snapshot=?')
            vals.append(sevk)

    # hedef_vade_tarihi — AVANS'ta hesaplanamaz (sevk tarihi bilinmiyor)
    if not row['hedef_vade_tarihi'] and sevk and not is_avans:
        vade_gun = row['onaylanan_vade_gun_snapshot'] or (sip['vade_gun'] if sip['vade_gun'] else None)
        if vade_gun:
            try:
                sevk_d = date.fromisoformat(sevk[:10])
                hedef = (sevk_d + timedelta(days=int(vade_gun))).isoformat()
                updates.append('hedef_vade_tarihi=?')
                vals.append(hedef)
            except (ValueError, TypeError):
                pass

    # paket_hedef_tutar — yalnız explicit parent değeri (beklenen_tutar otomatik kopyalanmaz)
    if updates:
        updates.append('guncelleme_tarihi=?')
        vals.append(now)
        vals.append(kayit_id)
        con.execute(
            'UPDATE mo_tahsilat_kayit SET ' + ', '.join(updates) + ' WHERE id=?',
            vals,
        )


def sync_cek_parent_tutarlar(con: sqlite3.Connection, kayit_id: int) -> None:
    """CEK parent alinan/kalan tutarlarını aktif çek toplamına göre güncelle."""
    if not _tablo_var(con, 'mo_tahsilat_cek'):
        return
    parent = con.execute(
        'SELECT odeme_tipi, paket_hedef_tutar FROM mo_tahsilat_kayit WHERE id=? AND aktif=1',
        (kayit_id,),
    ).fetchone()
    if not parent or (parent['odeme_tipi'] or '').upper() != 'CEK':
        return
    row = con.execute(
        'SELECT COALESCE(SUM(tutar), 0) AS toplam FROM mo_tahsilat_cek WHERE tahsilat_kayit_id=? AND aktif=1',
        (kayit_id,),
    ).fetchone()
    toplam = round(float(row['toplam'] or 0), 2)
    hedef = parent['paket_hedef_tutar']
    kalan = None
    kismi = 0
    if hedef is not None:
        kalan = round(max(float(hedef) - toplam, 0), 2)
        kismi = 1 if kalan > 0.009 else 0
    con.execute(
        """
        UPDATE mo_tahsilat_kayit
        SET alinan_tutar=?, kalan_tutar=?, kismi_mi=?, guncelleme_tarihi=?
        WHERE id=?
        """,
        (toplam, kalan, kismi, _now(), kayit_id),
    )


def _cek_onay_validate(
    con: sqlite3.Connection,
    kayit_id: int,
    tahsilat_tipi_override: Optional[str] = None,
) -> None:
    """CEK paketini onaya göndermeden önce: sipariş, hedef, en az 1 aktif çek.

    tahsilat_tipi_override: DB'de kolon yoksa (migration 164 uygulanmamış) payload'dan gelen
    değeri parametre olarak al. DB'de kolon varsa DB değeri tercih edilir.
    """
    from modules.nexgen.mo_tahsilat_cek_service import cek_listele
    # tahsilat_tipi kolonunu backward-compat okuma: kolon yoksa NORMAL varsay
    tt_kolon = _tahsilat_tipi_kolon_var(con)
    select_cols = 'odeme_tipi, siparis_id, paket_hedef_tutar'
    if tt_kolon:
        select_cols += ', tahsilat_tipi'
    row = con.execute(
        f'SELECT {select_cols} FROM mo_tahsilat_kayit WHERE id=?',
        (kayit_id,),
    ).fetchone()
    if not row or (row['odeme_tipi'] or '').upper() != 'CEK':
        return
    if not row['siparis_id']:
        raise MoTahsilatError('Çek tahsilatında bağlı sipariş zorunludur.', 400)
    # AVANS modunda paket_hedef_tutar zorunlu değil — gerçek sevkiyat henüz yok
    # DB'de kolon varsa DB'yi tercih et; yoksa override (payload) değerini al
    _db_tipi = (row['tahsilat_tipi'] if tt_kolon else None)
    kayit_tipi = (_db_tipi or tahsilat_tipi_override or TAHSILAT_TIPI_NORMAL).upper()
    is_avans = kayit_tipi == TAHSILAT_TIPI_AVANS
    if not is_avans:
        if row['paket_hedef_tutar'] is None or float(row['paket_hedef_tutar'] or 0) <= 0:
            raise MoTahsilatError('Çek paketi için hedef tutar zorunludur.', 400)
    cekler = cek_listele(con, kayit_id)
    if not cekler:
        raise MoTahsilatError('CEK paketi onaylanabilir için en az 1 aktif çek satırı gerekli.', 400)


def onaya_gonder(
    con: sqlite3.Connection,
    kayit_id: int,
    kullanici_id: int,
    yk: set[str] | None = None,
    payload: dict | None = None,
    vade_asim_aciklamasi: str | None = None,
) -> dict[str, Any]:
    """
    Tahsilat kaydını yönetim onayına gönder.

    Normal vade → YONETIM_ONAY_BEKLIYOR
    Fazla vade  → vade_asim_aciklamasi zorunlu → YONETIM_ISTISNA_ONAY_BEKLIYOR

    Backend, vade_kontrol sonucunu bağımsız hesaplar;
    frontend'den gelen durum_kodu'na güvenmez.
    """
    from modules.nexgen.onay_tahsilat_adapter import tahsilat_onaya_gonder
    from modules.nexgen.mo_vade_kontrol_service import hesapla as vade_hesapla, DURUM_FAZLA_VADE

    # payload artık yalnızca tahsilat_tipi ve vade_asim_aciklamasi taşır;
    # tam _validate_payload / taslak_kaydet çağrısı yapılmaz —
    # kayıt zaten önceki adımda taslak olarak DB'ye yazıldı.

    row = con.execute(
        'SELECT id, durum, olusturan_id, cari_id FROM mo_tahsilat_kayit WHERE id=? AND aktif=1',
        (kayit_id,),
    ).fetchone()
    if not row:
        raise MoTahsilatError('Kayıt bulunamadı.', 404)
    if row['durum'] not in KAYIT_DUZENLENEBILIR:
        raise MoTahsilatError('Bu durumda onaya gönderilemez.', 409)
    if int(row['olusturan_id'] or 0) != kullanici_id:
        raise MoTahsilatError('Yalnız kendi kaydınızı gönderebilirsiniz.', 403)
    if can_muhasebe_onay(yk):
        raise MoTahsilatError('Onay yetkisi olan kullanıcı tahsilat kaydı açamaz.', 403)

    tt_kolon_ok = _tahsilat_tipi_kolon_var(con)
    _sip_cols = 'odeme_tipi, siparis_id'
    if tt_kolon_ok:
        _sip_cols += ', tahsilat_tipi'
    sip_row = con.execute(
        f'SELECT {_sip_cols} FROM mo_tahsilat_kayit WHERE id=?', (kayit_id,),
    ).fetchone()
    is_cek = sip_row and (sip_row['odeme_tipi'] or '').upper() == 'CEK'
    # tahsilat_tipi: DB'den oku (migration varsa), yoksa payload'dan al, yoksa NORMAL
    _db_tipi = (sip_row['tahsilat_tipi'] if (sip_row and tt_kolon_ok) else None)
    _payload_tipi = ((payload or {}).get('tahsilat_tipi') or '').strip().upper() if payload else ''
    kayit_tahsilat_tipi = (_db_tipi or _payload_tipi or TAHSILAT_TIPI_NORMAL).upper()
    is_avans_kayit = kayit_tahsilat_tipi == TAHSILAT_TIPI_AVANS

    _cek_onay_validate(con, kayit_id, tahsilat_tipi_override=kayit_tahsilat_tipi)

    if is_cek and sip_row['siparis_id']:
        sync_cek_parent_tutarlar(con, kayit_id)
        if not is_avans_kayit:
            _freeze_cek_snapshots(con, kayit_id, int(sip_row['siparis_id']))

    _sevk_onay_kontrol(con, kayit_id)

    # --- Vade kontrol: backend bağımsız hesap ---
    vade_sonuc = None
    istisna_path = False
    if is_cek and not is_avans_kayit:
        try:
            old_rf = con.row_factory
            con.row_factory = __import__('sqlite3').Row
            vade_sonuc = vade_hesapla(
                tahsilat_kayit_id=kayit_id,
                con=con,
                tahsilat_tipi=kayit_tahsilat_tipi,
            )
            con.row_factory = old_rf
            if vade_sonuc and vade_sonuc.durum_kodu == DURUM_FAZLA_VADE:
                istisna_path = True
        except Exception:
            pass  # vade kontrol hatası onayı bloklamasın (uyarı yeterli)

    if istisna_path:
        aciklama = (vade_asim_aciklamasi or '').strip()
        if not aciklama:
            raise MoTahsilatError(
                'Vade aşımı var. Yönetime göndermek için açıklama zorunludur.', 400
            )
        hedef_durum = KAYIT_DURUM_ISTISNA_ONAY_BEKLIYOR
    else:
        hedef_durum = KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR

    r = tahsilat_onaya_gonder(con, kayit_id, kullanici_id)
    if not r.get('ok'):
        raise MoTahsilatError(r.get('hata') or 'Onaya gönderilemedi.', 409)

    now = _now()

    # İstisna açıklaması varsa onay_notu'na yaz
    extra_fields = ''
    extra_params: list[Any] = []
    if istisna_path and aciklama:
        extra_fields = ', onay_notu=?'
        extra_params = [aciklama]

    # Vade kontrol snapshot → audit_json'a ekle
    vk_snap: dict[str, Any] = {}
    if vade_sonuc is not None:
        from modules.nexgen.mo_vade_kontrol_service import onay_snapshot_blogu
        vk_snap = onay_snapshot_blogu(vade_sonuc)

    con.execute(
        f"""
        UPDATE mo_tahsilat_kayit SET durum=?, guncelleme_tarihi=?{extra_fields} WHERE id=?
        """,
        (hedef_durum, now, *extra_params, kayit_id),
    )
    sip = con.execute('SELECT siparis_id FROM mo_tahsilat_kayit WHERE id=?', (kayit_id,)).fetchone()
    if sip and sip['siparis_id']:
        con.execute(
            """
            UPDATE nexgen_planlama_siparis SET tahsilat_durumu=?, guncelleme_tarihi=?
            WHERE id=?
            """,
            (PLAN_DURUM_MUHASEBE_BEKLIYOR, now, sip['siparis_id']),
        )
    con.commit()
    return {
        'ok': True,
        'kayit_id': kayit_id,
        'onay_talep_id': r.get('talep_id'),
        'talep_kod': r.get('talep_kod'),
        'hedef_durum': hedef_durum,
        'istisna_path': istisna_path,
        'vade_snapshot': vk_snap,
    }


def karar_sonrasi(con, kayit_id: int, sonuc: dict) -> None:
    """Yönetim onay sonrası — cari hareket YAZILMAZ (entegrasyon kapalı).

    Legacy ONAYLANDI DB kaydı varsa korunur; yeni onaylar YONETIM_ONAYLANDI yazar.
    """
    durum = sonuc.get('durum')
    now = _now()
    if durum == 'ONAYLANDI' and sonuc.get('tamamlandi'):
        ent = 'YAZILDI' if CARI_ENTEGRASYON_AKTIF else 'BEKLIYOR'
        _onaylayan_id = sonuc.get('kullanici_id') or None
        _karar_tarihi = sonuc.get('karar_tarihi') or now
        _karar_notu = sonuc.get('not') or None
        # Yeni onaylar YONETIM_ONAYLANDI yazar; legacy ONAYLANDI kayıtlar okunmaya devam eder
        con.execute(
            """
            UPDATE mo_tahsilat_kayit
            SET durum=?, cari_entegrasyon_durumu=?,
                onaylayan_id=?, onay_notu=?, guncelleme_tarihi=?
            WHERE id=?
            """,
            (KAYIT_DURUM_YONETIM_ONAYLANDI, ent, _onaylayan_id, _karar_notu, _karar_tarihi, kayit_id),
        )
        row = con.execute('SELECT siparis_id, kalan_tutar FROM mo_tahsilat_kayit WHERE id=?', (kayit_id,)).fetchone()
        if row and row['siparis_id']:
            plan_durum = PLAN_DURUM_TAMAMLANDI
            if row['kalan_tutar'] and float(row['kalan_tutar']) > 0.009:
                plan_durum = PLAN_DURUM_KAYIT_GIRILDI
            con.execute(
                'UPDATE nexgen_planlama_siparis SET tahsilat_durumu=?, guncelleme_tarihi=? WHERE id=?',
                (plan_durum, now, row['siparis_id']),
            )
    elif durum == 'REVIZYON':
        con.execute(
            'UPDATE mo_tahsilat_kayit SET durum=?, revizyon_gerekce=?, guncelleme_tarihi=? WHERE id=?',
            (KAYIT_DURUM_REVIZYON, sonuc.get('not') or '', now, kayit_id),
        )
    elif durum == 'REDDEDILDI':
        con.execute(
            'UPDATE mo_tahsilat_kayit SET durum=?, revizyon_gerekce=?, guncelleme_tarihi=? WHERE id=?',
            (KAYIT_DURUM_REDDEDILDI, sonuc.get('not') or '', now, kayit_id),
        )


def _pzm_siparis_payload_unpack(ref: Any) -> dict | None:
    if not ref:
        return None
    s = str(ref)
    for prefix in ('__PZM_V3__', '__PZM_V2__', '__PZM_V1__'):
        if s.startswith(prefix):
            try:
                return json.loads(s[len(prefix):])
            except Exception:
                return None
    return None


def canonical_siparis_odeme_tipi(plan_row: dict, mo: dict | None = None) -> str | None:
    """Sipariş canonical ödeme tipi — kolon, MO payload, PZM payload sırası."""
    mo = mo or {}
    pzm = _pzm_siparis_payload_unpack(plan_row.get('talep_referansi')) or {}
    for raw in (
        plan_row.get('odeme_tipi'),
        plan_row.get('tahsilat_odeme_sekli'),
        mo.get('tahsilat_odeme_sekli'),
        mo.get('odeme_sekli'),
        mo.get('odeme_tipi'),
        pzm.get('odeme_tipi'),
        pzm.get('tahsilat_odeme_sekli'),
        pzm.get('odeme_sekli'),
    ):
        ot = (raw or '').strip().upper()
        if ot in ODEME_SEKILLERI:
            return ot
    return None


def acik_planlar(con, cari_ids: list[int]) -> list[dict[str, Any]]:
    """Tahsilata uygun siparişler — MO açık siparişler (dashboard_v2) ile aynı cari_id/durum mantığı."""
    if not cari_ids or not _tablo_var(con, 'nexgen_planlama_siparis'):
        return []
    ps_cols = [c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()]
    if 'tahsilat_kurali' not in ps_cols:
        return []
    ph = ','.join(['?'] * len(cari_ids))
    has_kur = 'kur' in ps_cols
    kur_fields = ', ps.kur, ps.kur_tarihi' if has_kur else ''
    odeme_fields = ''
    if 'odeme_tipi' in ps_cols:
        odeme_fields += ', ps.odeme_tipi'
    if 'tahsilat_odeme_sekli' in ps_cols:
        odeme_fields += ', ps.tahsilat_odeme_sekli'
    tahsilat_durum_sql = ''
    if 'tahsilat_durumu' in ps_cols:
        tahsilat_durum_sql = (
            " AND (ps.tahsilat_durumu IS NULL OR ps.tahsilat_durumu NOT IN ('TAMAMLANDI'))"
        )
    sevk_sub = ''
    if _tablo_var(con, 'mo_musteri_sevkiyat'):
        sevk_sub = """
            , (SELECT MIN(ms.sevk_tarihi) FROM mo_musteri_sevkiyat ms
               WHERE ms.siparis_id = ps.id AND ms.aktif = 1
                 AND ms.sevk_tarihi IS NOT NULL AND ms.sevk_tarihi != ''
                 AND ms.durum IN ('SEVK_EDILDI','TESLIM_EDILDI','TAMAMLANDI')
              ) AS gercek_sevk_tarihi
        """
    kalem_tbl = _tablo_var(con, 'nexgen_planlama_siparis_kalem')
    kalem_cols: set[str] = set()
    if kalem_tbl:
        kalem_cols = {c[1] for c in con.execute(
            'PRAGMA table_info(nexgen_planlama_siparis_kalem)'
        ).fetchall()}
    sql = f"""
        SELECT ps.id, ps.siparis_no, ps.cari_id, ps.cari_unvan, ps.tahsilat_kurali, ps.tahsilat_gun_sayisi,
               ps.planlanan_tahsilat_tarihi, ps.tahsilat_durumu, ps.anlasma_birim_fiyat,
               ps.anlasma_para_birimi, ps.talep_referansi, ps.durum, ps.vade_gun{odeme_fields}{kur_fields}
               {sevk_sub}
        FROM nexgen_planlama_siparis ps
        WHERE ps.cari_id IN ({ph})
          AND ps.durum NOT IN ('REDDEDILDI','IPTAL','TASLAK')
          {tahsilat_durum_sql}
        ORDER BY ps.id DESC
        LIMIT 200
    """
    out: list[dict[str, Any]] = []
    for r in con.execute(sql, cari_ids).fetchall():
        d = dict(r)
        sevk_tarihi = d.get('gercek_sevk_tarihi')
        mo = mo_siparis_payload_unpack(d.get('talep_referansi')) or {}
        tutar, tahmini = beklenen_tutar_hesapla(d, mo)
        d['beklenen_tutar'] = tutar
        d['tahmini'] = tahmini
        # CEK: vade_gun NULL ise talep_referansi.cek_vade_gun fallback
        _raw_vg = d.get('vade_gun')
        _odeme = (d.get('odeme_tipi') or '').upper()
        if _raw_vg is None and _odeme == 'CEK':
            _ref = d.get('talep_referansi') or ''
            _marker = '__PZM_V2__'
            _idx = str(_ref).find(_marker)
            if _idx >= 0:
                try:
                    import json as _json
                    _pzm = _json.loads(str(_ref)[_idx + len(_marker):])
                    _cv = _pzm.get('cek_vade_gun')
                    if _cv is not None:
                        _v = int(str(_cv).strip())
                        _raw_vg = _v if _v > 0 else None
                except Exception:
                    pass
        d['onaylanan_vade_gun'] = _raw_vg
        d['gercek_sevk_tarihi'] = sevk_tarihi
        d['tahsilat_uygunluk'] = 'sevk_yapildi' if sevk_tarihi else 'plan'
        d['siparis_kur'] = d.get('kur')
        d['siparis_kur_tarihi'] = (d.get('kur_tarihi') or '')[:10] or None

        # hedef_vade_tarihi = gerçek sevk tarihi + canonical vade_gun
        _vg = _raw_vg
        if sevk_tarihi and _vg is not None:
            try:
                d['hedef_vade_tarihi'] = (
                    date.fromisoformat(str(sevk_tarihi)[:10]) + timedelta(days=int(_vg))
                ).isoformat()
            except (ValueError, TypeError):
                d['hedef_vade_tarihi'] = None
        else:
            d['hedef_vade_tarihi'] = None

        # Sipariş toplam miktarı ve canonical toplam FX
        siparis_miktar: float | None = None
        fk_col = None
        if kalem_tbl:
            if 'planlama_siparis_id' in kalem_cols:
                fk_col = 'planlama_siparis_id'
            elif 'siparis_id' in kalem_cols:
                fk_col = 'siparis_id'
        if fk_col and {'miktar_l', 'miktar_s', 'miktar_m'}.issubset(kalem_cols):
            km = con.execute(
                f"""
                SELECT COALESCE(SUM(COALESCE(miktar_l,0)+COALESCE(miktar_s,0)+COALESCE(miktar_m,0)),0) AS t
                FROM nexgen_planlama_siparis_kalem WHERE {fk_col}=?
                """,
                (int(d['id']),),
            ).fetchone()
            if km and float(km['t'] or 0) > 0:
                siparis_miktar = round(float(km['t']), 3)
        if siparis_miktar is None:
            mo_m = mo.get('miktar')
            if mo_m not in (None, ''):
                try:
                    siparis_miktar = round(float(mo_m), 3)
                except (TypeError, ValueError):
                    pass
        d['siparis_miktar_kg'] = siparis_miktar
        birim = d.get('anlasma_birim_fiyat')
        pb = (d.get('anlasma_para_birimi') or 'TRY').upper()
        if siparis_miktar is not None and birim not in (None, ''):
            try:
                d['siparis_toplam_fx'] = round(float(siparis_miktar) * float(birim), 2)
            except (TypeError, ValueError):
                d['siparis_toplam_fx'] = None
        else:
            d['siparis_toplam_fx'] = None
        d['siparis_para_birimi'] = pb
        d['odeme_tipi'] = canonical_siparis_odeme_tipi(d, mo)
        out.append(d)
    return out


def cari_tahsilat_listele(
    con,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Cari bazlı tahsilat kayıt listesi (read-only).

    Yalnız kullanıcının erişim yetkisi olan cari döner; başka cari için 403.
    Canonical write=0.
    """
    from modules.nexgen.mo_tahsilat_config import KAYIT_DUZENLENEBILIR, KAYIT_DURUM_ETIKET
    from modules.nexgen.mo_gorusme_service import can_mo_gorusme_yaz

    if not _tablo_var(con, 'mo_tahsilat_kayit'):
        return []
    if not can_mo_gorusme_yaz(con, kullanici_id, cari_id, yk) and not can_muhasebe_onay(yk):
        raise MoTahsilatError('Bu müşteri için erişim yetkiniz yok.', 403)

    rows = con.execute(
        """
        SELECT
            tk.id,
            tk.kayit_kodu,
            tk.siparis_id,
            tk.sevkiyat_id,
            tk.odeme_tipi,
            tk.para_birimi,
            tk.paket_hedef_tutar,
            tk.beklenen_tutar,
            tk.alinan_tutar,
            tk.kalan_tutar,
            tk.durum,
            tk.olusturma_tarihi,
            COALESCE(ps.siparis_no, '') AS siparis_no,
            COALESCE(sv.sevkiyat_no, '') AS sevkiyat_no
        FROM mo_tahsilat_kayit tk
        LEFT JOIN nexgen_planlama_siparis ps ON ps.id = tk.siparis_id
        LEFT JOIN mo_musteri_sevkiyat sv ON sv.id = tk.sevkiyat_id
        WHERE tk.cari_id = ? AND tk.aktif = 1
        ORDER BY tk.olusturma_tarihi DESC, tk.id DESC
        """,
        (cari_id,),
    ).fetchall()

    out = []
    for r in rows:
        d = dict(r)
        durum = d.get('durum') or ''
        d['durum_etiket'] = KAYIT_DURUM_ETIKET.get(durum, durum.replace('_', ' '))
        d['duzenlenebilir'] = durum in KAYIT_DUZENLENEBILIR
        # Canonical hedef: CEK için paket_hedef_tutar, diğerleri beklenen_tutar
        if (d.get('odeme_tipi') or '').upper() == 'CEK':
            d['hedef_tutar'] = d.get('paket_hedef_tutar')
        else:
            d['hedef_tutar'] = d.get('beklenen_tutar')
        out.append(d)
    return out
