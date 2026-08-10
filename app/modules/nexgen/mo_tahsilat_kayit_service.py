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
    KAYIT_DURUM_MUHASEBE_BEKLIYOR,
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
)
from modules.nexgen.mo_tahsilat_plan_service import beklenen_tutar_hesapla


class MoTahsilatError(Exception):
    def __init__(self, mesaj: str, kod: int = 400):
        self.mesaj = mesaj
        self.kod = kod
        super().__init__(mesaj)


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
    if float(alinan) > float(hedef) + 0.009:
        raise MoTahsilatError('Alınan tutar TRY hedefini aşıyor.', 400)
    kalan = round(max(float(hedef) - float(alinan), 0), 2)
    norm['kalan_tutar'] = kalan
    norm['kismi_mi'] = 1 if kalan > 0.009 else 0


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
        if norm['alinan_tutar'] is not None and float(norm['alinan_tutar']) > sevk_kalan + 0.009:
            raise MoTahsilatError(
                f'Alınan tutar sevk kalanını aşıyor (kalan={sevk_kalan}).', 409,
            )
    else:
        if norm['beklenen_tutar'] is None:
            norm['beklenen_tutar'] = sevk_kalan
        elif float(norm['beklenen_tutar']) > sevk_kalan + 0.009:
            raise MoTahsilatError(
                f'Beklenen tutar sevk kalanını aşıyor (kalan={sevk_kalan}).', 409,
            )
        if norm['alinan_tutar'] is not None and float(norm['alinan_tutar']) > sevk_kalan + 0.009:
            raise MoTahsilatError(
                f'Alınan tutar sevk kalanını aşıyor (kalan={sevk_kalan}).', 409,
            )


def _tahsil_edilen_sevk(
    con: sqlite3.Connection,
    sevkiyat_id: int,
    *,
    haric_kayit_id: int | None = None,
) -> float:
    """ONAYLANDI + MUHASEBE_ONAY_BEKLIYOR alinan_tutar toplamı."""
    if not _tablo_var(con, 'mo_tahsilat_kayit') or not _sevk_tahsilat_kolonlari_var(con):
        return 0.0
    ph = ','.join(['?'] * len(TAHSILAT_EDILEN_DURUMLARI))
    haric_sql = ''
    params: list[Any] = [int(sevkiyat_id), *sorted(TAHSILAT_EDILEN_DURUMLARI)]
    if haric_kayit_id:
        haric_sql = ' AND id != ?'
        params.append(int(haric_kayit_id))
    row = con.execute(
        f"""
        SELECT COALESCE(SUM(alinan_tutar), 0) AS toplam
        FROM mo_tahsilat_kayit
        WHERE sevkiyat_id=? AND aktif=1
          AND durum IN ({ph}){haric_sql}
        """,
        params,
    ).fetchone()
    return round(float(row['toplam'] or 0), 2) if row else 0.0


def _bind_sevkiyat_taslak(
    con: sqlite3.Connection,
    norm: dict[str, Any],
    sevkiyat_id: int,
    *,
    kayit_id: int | None = None,
    preserve_tcmb_snapshot: bool = False,
) -> None:
    """Sevkiyat bağlantısı + FX kalan → TCMB Satış → TRY hedef freeze."""
    from modules.nexgen.mo_tahsilat_kur_service import MoTahsilatKurError, fx_try_hedef_hesapla
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
    try:
        kur_out = fx_try_hedef_hesapla(
            con,
            para_birimi=sevk_pb,
            kur_tarihi=kur_tarihi,
            fx_tutar=sevk_kalan_fx,
        )
    except MoTahsilatKurError as exc:
        raise MoTahsilatError(exc.mesaj, exc.kod) from exc

    try_hedef = float(kur_out['try_hedef_tutar'])
    norm['sevk_kalan_fx_snapshot'] = float(kur_out['fx_tutar'])
    norm['sevk_para_birimi_snapshot'] = sevk_pb
    norm['tcmb_satis_kur_snapshot'] = float(kur_out['tcmb_satis_kur'])
    norm['kur_tarihi_snapshot'] = kur_out['kur_tarihi']
    if aday.get('sevk_tarihi'):
        norm['gercek_sevk_tarihi_snapshot'] = str(aday['sevk_tarihi'])[:10]
    norm['para_birimi'] = 'TRY'
    norm['beklenen_tahmini'] = 0

    if norm['odeme_tipi'] == 'CEK':
        norm['paket_hedef_tutar'] = try_hedef
    else:
        norm['beklenen_tutar'] = try_hedef
    _recalc_try_kalan(norm)


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
        if tutar > hedef_try + 0.009:
            raise MoTahsilatError(
                f'TRY tahsilat hedefi aşıldı (hedef={hedef_try}, talep={tutar}).', 409,
            )
        return

    from modules.nexgen.mo_tahsilat_sevk_service import sevk_hedef_hesapla

    hedef = row['sevk_hedef_tutar_snapshot']
    if hedef in (None, ''):
        hi = sevk_hedef_hesapla(con, sevkiyat_id)
        hedef = hi.get('sevk_hedef_tutar')
    if hedef in (None, ''):
        raise MoTahsilatError('Sevk hedef tutarı hesaplanamadı.', 409)

    edilen = _tahsil_edilen_sevk(con, sevkiyat_id, haric_kayit_id=kayit_id)
    kalan = round(float(hedef) - edilen, 2)

    if odeme == 'CEK':
        if tutar <= 0 and row['paket_hedef_tutar'] not in (None, ''):
            tutar = float(row['paket_hedef_tutar'] or 0)
    if tutar <= 0:
        raise MoTahsilatError('Onaya göndermek için alınan tutar zorunlu.', 400)
    if tutar > kalan + 0.009:
        raise MoTahsilatError(
            f'Sevkiyat tahsilat kalanı aşıldı (kalan={kalan}, talep={tutar}).', 409,
        )


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
        if alinan_f > paket_hedef_f + 0.009:
            raise MoTahsilatError('Alınan tutar paket hedefinden fazla olamaz.', 400)
        kalan_f = round(max(paket_hedef_f - alinan_f, 0), 2)
        kismi = kalan_f > 0.009
    elif beklenen_f is not None and alinan_f is not None:
        if alinan_f > beklenen_f + 0.009:
            raise MoTahsilatError('Alınan tutar beklenenden fazla olamaz.', 400)
        kalan_f = round(max(beklenen_f - alinan_f, 0), 2)
        kismi = kalan_f > 0.009

    if odeme == 'CEK':
        if not siparis_id:
            raise MoTahsilatError('Çek tahsilatında bağlı sipariş zorunludur.', 400)
        if zorunlu_gonder and paket_hedef_f is None:
            raise MoTahsilatError('Çek paketi için hedef tutar zorunludur.', 400)

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
        if sevk_kolon:
            tcmb_kolon = _tcmb_snapshot_kolonlari_var(con)
            if tcmb_kolon:
                con.execute(
                    """
                    UPDATE mo_tahsilat_kayit SET
                        cari_id=?, siparis_id=?, sevkiyat_id=?, beklenen_tutar=?, beklenen_tahmini=?,
                        paket_hedef_tutar=?, alinan_tutar=?, kalan_tutar=?,
                        sevk_hedef_tutar_snapshot=?, sevk_para_birimi_snapshot=?,
                        sevk_kalan_fx_snapshot=?, tcmb_satis_kur_snapshot=?, kur_tarihi_snapshot=?,
                        para_birimi=?,
                        planlanan_tahsilat_tarihi=?, alinan_tarih=?, odeme_tipi=?, odeme_referansi=?,
                        kismi_mi=?, aciklama=?, dosya_ref=?, onay_notu=?, guncelleme_tarihi=?
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
                        norm['onay_notu'], now, kayit_id,
                    ),
                )
            else:
                con.execute(
                    """
                    UPDATE mo_tahsilat_kayit SET
                        cari_id=?, siparis_id=?, sevkiyat_id=?, beklenen_tutar=?, beklenen_tahmini=?,
                        paket_hedef_tutar=?, alinan_tutar=?, kalan_tutar=?,
                        sevk_hedef_tutar_snapshot=?, sevk_para_birimi_snapshot=?, para_birimi=?,
                        planlanan_tahsilat_tarihi=?, alinan_tarih=?, odeme_tipi=?, odeme_referansi=?,
                        kismi_mi=?, aciklama=?, dosya_ref=?, onay_notu=?, guncelleme_tarihi=?
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
                        norm['onay_notu'], now, kayit_id,
                    ),
                )
        else:
            con.execute(
                """
                UPDATE mo_tahsilat_kayit SET
                    cari_id=?, siparis_id=?, beklenen_tutar=?, paket_hedef_tutar=?, alinan_tutar=?, kalan_tutar=?,
                    planlanan_tahsilat_tarihi=?, alinan_tarih=?, odeme_tipi=?, odeme_referansi=?,
                    kismi_mi=?, aciklama=?, dosya_ref=?, onay_notu=?, guncelleme_tarihi=?
                WHERE id=?
                """,
                (
                    norm['cari_id'], norm['siparis_id'], norm['beklenen_tutar'], norm['paket_hedef_tutar'],
                    norm['alinan_tutar'], norm['kalan_tutar'], norm['planlanan_tahsilat_tarihi'],
                    norm['alinan_tarih'], norm['odeme_tipi'], norm['odeme_referansi'], norm['kismi_mi'],
                    norm['aciklama'], norm['dosya_ref'], norm['onay_notu'], now, kayit_id,
                ),
            )
        kid = kayit_id
    else:
        if sevk_kolon:
            tcmb_kolon = _tcmb_snapshot_kolonlari_var(con)
            if tcmb_kolon:
                cur = con.execute(
                    """
                    INSERT INTO mo_tahsilat_kayit
                        (kayit_kodu, cari_id, siparis_id, sevkiyat_id, kaynak_modul, beklenen_tutar, beklenen_tahmini,
                         paket_hedef_tutar, alinan_tutar, kalan_tutar,
                         sevk_hedef_tutar_snapshot, sevk_para_birimi_snapshot,
                         sevk_kalan_fx_snapshot, tcmb_satis_kur_snapshot, kur_tarihi_snapshot,
                         para_birimi,
                         planlanan_tahsilat_tarihi, alinan_tarih, odeme_tipi, odeme_referansi, kismi_mi,
                         aciklama, dosya_ref, onay_notu, durum, cari_entegrasyon_durumu,
                         idempotency_key, olusturan_id, olusturma_tarihi, guncelleme_tarihi)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                        kullanici_id, now, now,
                    ),
                )
            else:
                cur = con.execute(
                    """
                    INSERT INTO mo_tahsilat_kayit
                        (kayit_kodu, cari_id, siparis_id, sevkiyat_id, kaynak_modul, beklenen_tutar, beklenen_tahmini,
                         paket_hedef_tutar, alinan_tutar, kalan_tutar,
                         sevk_hedef_tutar_snapshot, sevk_para_birimi_snapshot, para_birimi,
                         planlanan_tahsilat_tarihi, alinan_tarih, odeme_tipi, odeme_referansi, kismi_mi,
                         aciklama, dosya_ref, onay_notu, durum, cari_entegrasyon_durumu,
                         idempotency_key, olusturan_id, olusturma_tarihi, guncelleme_tarihi)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                        kullanici_id, now, now,
                    ),
                )
        else:
            cur = con.execute(
                """
                INSERT INTO mo_tahsilat_kayit
                    (kayit_kodu, cari_id, siparis_id, kaynak_modul, beklenen_tutar, beklenen_tahmini,
                     paket_hedef_tutar, alinan_tutar, kalan_tutar, planlanan_tahsilat_tarihi, alinan_tarih,
                     odeme_tipi, odeme_referansi, kismi_mi, aciklama, dosya_ref, onay_notu, durum,
                     cari_entegrasyon_durumu, idempotency_key, olusturan_id, olusturma_tarihi, guncelleme_tarihi)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    _kayit_kodu_uret(con), norm['cari_id'], norm['siparis_id'], KAYNAK_MUSTERI_OPERASYONU,
                    norm['beklenen_tutar'], norm.get('beklenen_tahmini', 1), norm['paket_hedef_tutar'],
                    norm['alinan_tutar'], norm['kalan_tutar'], norm['planlanan_tahsilat_tarihi'],
                    norm['alinan_tarih'], norm['odeme_tipi'], norm['odeme_referansi'], norm['kismi_mi'],
                    norm['aciklama'], norm['dosya_ref'], norm['onay_notu'], KAYIT_DURUM_TASLAK, 'BEKLIYOR',
                    norm['idempotency_key'], kullanici_id, now, now,
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
    """
    from modules.nexgen.mo_sevkiyat_service import gercek_sevk_tarihi
    from datetime import date, timedelta

    row = con.execute(
        'SELECT para_birimi, onaylanan_vade_gun_snapshot, gercek_sevk_tarihi_snapshot, '
        '       hedef_vade_tarihi, paket_hedef_tutar, beklenen_tutar '
        'FROM mo_tahsilat_kayit WHERE id=?', (kayit_id,)
    ).fetchone()
    if not row:
        return

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

    # gercek_sevk_tarihi_snapshot
    sevk = row['gercek_sevk_tarihi_snapshot']
    if not sevk:
        sevk = gercek_sevk_tarihi(con, siparis_id)
        if sevk:
            updates.append('gercek_sevk_tarihi_snapshot=?')
            vals.append(sevk)

    # hedef_vade_tarihi
    if not row['hedef_vade_tarihi'] and sevk:
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


def _cek_onay_validate(con: sqlite3.Connection, kayit_id: int) -> None:
    """CEK paketini onaya göndermeden önce: sipariş, hedef, en az 1 aktif çek."""
    from modules.nexgen.mo_tahsilat_cek_service import cek_listele
    row = con.execute(
        'SELECT odeme_tipi, siparis_id, paket_hedef_tutar FROM mo_tahsilat_kayit WHERE id=?',
        (kayit_id,),
    ).fetchone()
    if not row or (row['odeme_tipi'] or '').upper() != 'CEK':
        return
    if not row['siparis_id']:
        raise MoTahsilatError('Çek tahsilatında bağlı sipariş zorunludur.', 400)
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
) -> dict[str, Any]:
    from modules.nexgen.onay_tahsilat_adapter import tahsilat_onaya_gonder

    if payload:
        _validate_payload({**payload, 'idempotency_key': payload.get('idempotency_key') or f'tahsilat-send-{kayit_id}'}, zorunlu_gonder=True)
        taslak_kaydet(con, {**payload, 'idempotency_key': payload.get('idempotency_key') or f'tahsilat-{kayit_id}-send'}, kullanici_id, yk, kayit_id=kayit_id)

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

    _cek_onay_validate(con, kayit_id)

    sip_row = con.execute(
        'SELECT odeme_tipi, siparis_id FROM mo_tahsilat_kayit WHERE id=?', (kayit_id,),
    ).fetchone()
    if sip_row and (sip_row['odeme_tipi'] or '').upper() == 'CEK' and sip_row['siparis_id']:
        sync_cek_parent_tutarlar(con, kayit_id)
        _freeze_cek_snapshots(con, kayit_id, int(sip_row['siparis_id']))

    _sevk_onay_kontrol(con, kayit_id)

    r = tahsilat_onaya_gonder(con, kayit_id, kullanici_id)
    if not r.get('ok'):
        raise MoTahsilatError(r.get('hata') or 'Onaya gönderilemedi.', 409)

    now = _now()
    con.execute(
        """
        UPDATE mo_tahsilat_kayit SET durum=?, guncelleme_tarihi=? WHERE id=?
        """,
        (KAYIT_DURUM_MUHASEBE_BEKLIYOR, now, kayit_id),
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
    return {'ok': True, 'kayit_id': kayit_id, 'onay_talep_id': r.get('talep_id'), 'talep_kod': r.get('talep_kod')}


def karar_sonrasi(con, kayit_id: int, sonuc: dict) -> None:
    """Yönetim onay sonrası — cari hareket YAZILMAZ (entegrasyon kapalı)."""
    durum = sonuc.get('durum')
    now = _now()
    if durum == 'ONAYLANDI' and sonuc.get('tamamlandi'):
        ent = 'YAZILDI' if CARI_ENTEGRASYON_AKTIF else 'BEKLIYOR'
        # Gerçek karar bilgisini onay_talep_adim'den oku (karar veren + tarihi)
        _onaylayan_id = sonuc.get('kullanici_id') or None
        _karar_tarihi = sonuc.get('karar_tarihi') or now
        _karar_notu = sonuc.get('not') or None
        con.execute(
            """
            UPDATE mo_tahsilat_kayit
            SET durum=?, cari_entegrasyon_durumu=?,
                onaylayan_id=?, onay_notu=?, guncelleme_tarihi=?
            WHERE id=?
            """,
            (KAYIT_DURUM_ONAYLANDI, ent, _onaylayan_id, _karar_notu, _karar_tarihi, kayit_id),
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
               ps.anlasma_para_birimi, ps.talep_referansi, ps.durum, ps.vade_gun{kur_fields}
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
        d['onaylanan_vade_gun'] = d.get('vade_gun')
        d['gercek_sevk_tarihi'] = sevk_tarihi
        d['tahsilat_uygunluk'] = 'sevk_yapildi' if sevk_tarihi else 'plan'
        d['siparis_kur'] = d.get('kur')
        d['siparis_kur_tarihi'] = (d.get('kur_tarihi') or '')[:10] or None

        # hedef_vade_tarihi = gerçek sevk tarihi + canonical vade_gun
        _vg = d.get('vade_gun')
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
        out.append(d)
    return out
