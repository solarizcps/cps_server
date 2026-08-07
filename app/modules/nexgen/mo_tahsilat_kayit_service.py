# -*- coding: utf-8 -*-
"""MO tahsilat kaydı servisi — taslak, yönetim onayı, idempotency."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
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
        'beklenen_tahmini': tahmini,
        'para_birimi': d.get('anlasma_para_birimi') or 'TRY',
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
    kalan = payload.get('kalan_tutar')
    kalan_f = None
    if kalan not in (None, ''):
        try:
            kalan_f = round(float(kalan), 2)
        except (TypeError, ValueError):
            kalan_f = None
    elif beklenen_f is not None and alinan_f is not None:
        if alinan_f > beklenen_f + 0.009:
            raise MoTahsilatError('Alınan tutar beklenenden fazla olamaz.', 400)
        kalan_f = round(max(beklenen_f - alinan_f, 0), 2)
        kismi = kalan_f > 0.009
    return {
        'idempotency_key': idem,
        'cari_id': cari_id,
        'siparis_id': siparis_id,
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
        if norm['beklenen_tutar'] is None:
            norm['beklenen_tutar'] = plan.get('beklenen_tutar')
        if not norm['planlanan_tahsilat_tarihi']:
            norm['planlanan_tahsilat_tarihi'] = plan.get('planlanan_tahsilat_tarihi')

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
        con.execute(
            """
            UPDATE mo_tahsilat_kayit SET
                cari_id=?, siparis_id=?, beklenen_tutar=?, alinan_tutar=?, kalan_tutar=?,
                planlanan_tahsilat_tarihi=?, alinan_tarih=?, odeme_tipi=?, odeme_referansi=?,
                kismi_mi=?, aciklama=?, dosya_ref=?, onay_notu=?, guncelleme_tarihi=?
            WHERE id=?
            """,
            (
                norm['cari_id'], norm['siparis_id'], norm['beklenen_tutar'], norm['alinan_tutar'],
                norm['kalan_tutar'], norm['planlanan_tahsilat_tarihi'], norm['alinan_tarih'],
                norm['odeme_tipi'], norm['odeme_referansi'], norm['kismi_mi'], norm['aciklama'],
                norm['dosya_ref'], norm['onay_notu'], now, kayit_id,
            ),
        )
        kid = kayit_id
    else:
        cur = con.execute(
            """
            INSERT INTO mo_tahsilat_kayit
                (kayit_kodu, cari_id, siparis_id, kaynak_modul, beklenen_tutar, beklenen_tahmini,
                 alinan_tutar, kalan_tutar, planlanan_tahsilat_tarihi, alinan_tarih, odeme_tipi,
                 odeme_referansi, kismi_mi, aciklama, dosya_ref, onay_notu, durum,
                 cari_entegrasyon_durumu, idempotency_key, olusturan_id, olusturma_tarihi, guncelleme_tarihi)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                _kayit_kodu_uret(con), norm['cari_id'], norm['siparis_id'], KAYNAK_MUSTERI_OPERASYONU,
                norm['beklenen_tutar'], 1, norm['alinan_tutar'], norm['kalan_tutar'],
                norm['planlanan_tahsilat_tarihi'], norm['alinan_tarih'], norm['odeme_tipi'],
                norm['odeme_referansi'], norm['kismi_mi'], norm['aciklama'], norm['dosya_ref'],
                norm['onay_notu'], KAYIT_DURUM_TASLAK, 'BEKLIYOR', norm['idempotency_key'],
                kullanici_id, now, now,
            ),
        )
        kid = int(cur.lastrowid)

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
    if not cari_ids or not _tablo_var(con, 'nexgen_planlama_siparis'):
        return []
    if not _tablo_var(con, 'nexgen_planlama_siparis') or not any(
        c[1] == 'tahsilat_kurali'
        for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()
    ):
        return []
    ph = ','.join(['?'] * len(cari_ids))
    rows = con.execute(
        f"""
        SELECT id, siparis_no, cari_id, cari_unvan, tahsilat_kurali, tahsilat_gun_sayisi,
               planlanan_tahsilat_tarihi, tahsilat_durumu, anlasma_birim_fiyat,
               anlasma_para_birimi, talep_referansi, durum
        FROM nexgen_planlama_siparis
        WHERE kaynak_modul='MUSTERI_OPERASYONU'
          AND cari_id IN ({ph})
          AND tahsilat_kurali IS NOT NULL AND tahsilat_kurali != ''
          AND durum NOT IN ('REDDEDILDI','IPTAL','TASLAK')
          AND (tahsilat_durumu IS NULL OR tahsilat_durumu NOT IN ('TAMAMLANDI'))
        ORDER BY planlanan_tahsilat_tarihi, id DESC
        LIMIT 30
        """,
        cari_ids,
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        mo = mo_siparis_payload_unpack(d.get('talep_referansi')) or {}
        tutar, tahmini = beklenen_tutar_hesapla(d, mo)
        d['beklenen_tutar'] = tutar
        d['tahmini'] = tahmini
        out.append(d)
    return out
