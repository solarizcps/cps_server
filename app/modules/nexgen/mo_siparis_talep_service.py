# -*- coding: utf-8 -*-
"""Müşteri Operasyonu sipariş talebi — taslak + merkezi onay köprüsü."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from modules.nexgen.mo_gorusme_config import KAYNAK_MUSTERI_OPERASYONU
from modules.nexgen.mo_gorusme_service import can_mo_gorusme_yaz
from modules.nexgen.mo_tahsilat_config import (
    ODEME_SEKILLERI,
    ODEME_SEKLI_ETIKET,
    TAHSILAT_KURALLARI,
)
from modules.nexgen.mo_tahsilat_plan_service import (
    hesapla_tahsilat_plani,
    tahsilat_kural_etiket,
)

KAYNAK_MODUL = KAYNAK_MUSTERI_OPERASYONU
MO_SIP_PREFIX = '__MO_SIP__'
URUN_GRUPLARI = frozenset({'TERLIK', 'TABAN', 'DOKME'})
PARA_BIRIMLERI = frozenset({'TRY', 'USD', 'EUR'})
BIRIMLER = frozenset({'kg', 'adet', 'ton', 'metre', 'm2', 'koli'})
DUZENLENEBILIR_MO = frozenset({'TASLAK', 'REVIZYON'})
ONAYA_GONDERILEBILIR = frozenset({'TASLAK', 'REVIZYON'})
READONLY_MO = frozenset({'ONAY_BEKLIYOR', 'ONAYLANDI', 'REDDEDILDI'})
YASAK_ALANLAR = frozenset({
    'formul_id', 'rf_renk_id', 'renk_varyant_id', 'kalemler', 'uretim_plan_id',
    'batch', 'uv', 'malzeme_ihtiyac', 'stok', 'plan', 'mpr',
})

OLAY_MOTORU_AKTIF = False


class MoSiparisError(Exception):
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


def _kolon_var(con, tablo: str, kolon: str) -> bool:
    if not _tablo_var(con, tablo):
        return False
    return kolon in [c[1] for c in con.execute(f'PRAGMA table_info({tablo})').fetchall()]


def _shadow_olay(con, olay_tipi: str, payload: dict) -> None:
    if OLAY_MOTORU_AKTIF or not _tablo_var(con, 'cari360_olay_shadow'):
        return
    try:
        con.execute(
            """
            INSERT INTO cari360_olay_shadow (olay_tipi, payload_json, created_at)
            VALUES (?, ?, datetime('now','localtime'))
            """,
            (olay_tipi, json.dumps(payload, ensure_ascii=False)),
        )
    except sqlite3.OperationalError:
        pass


def mo_siparis_payload_pack(meta: dict) -> str:
    return MO_SIP_PREFIX + json.dumps(meta, ensure_ascii=False, separators=(',', ':'))


def mo_siparis_payload_unpack(ref) -> dict | None:
    if not ref:
        return None
    s = str(ref)
    if not s.startswith(MO_SIP_PREFIX):
        return None
    try:
        return json.loads(s[len(MO_SIP_PREFIX):])
    except Exception:
        return None


def _siparis_no_uret(con) -> str:
    yil = datetime.now().year
    prefix = f'MO-S-{yil}-'
    row = con.execute(
        "SELECT siparis_no FROM nexgen_planlama_siparis WHERE siparis_no LIKE ? ORDER BY id DESC LIMIT 1",
        (prefix + '%',),
    ).fetchone()
    son = 0
    if row and row['siparis_no']:
        try:
            son = int(str(row['siparis_no']).split('-')[-1])
        except Exception:
            son = 0
    return f'{prefix}{son + 1:04d}'


def _mo_row_guard(row) -> None:
    if not row:
        raise MoSiparisError('Sipariş bulunamadı.', 404)
    if (row['kaynak_modul'] or '') != KAYNAK_MODUL:
        raise MoSiparisError('Bu kayıt Müşteri Operasyonu sipariş talebi değil.', 403)


def can_mo_siparis_yaz(con, kullanici_id: int, cari_id: int, yk: set[str] | None = None) -> bool:
    return can_mo_gorusme_yaz(con, kullanici_id, cari_id, yk)


def _reject_technical(payload: dict) -> None:
    for k in payload:
        if k in YASAK_ALANLAR:
            raise MoSiparisError(f'Teknik alan gönderilemez: {k}', 403)


def _norm_para(raw) -> str:
    s = (raw or 'TRY').strip().upper()
    if s == 'TL':
        s = 'TRY'
    if s not in PARA_BIRIMLERI:
        raise MoSiparisError('Geçersiz para birimi.', 400)
    return s


def _norm_fiyat(raw) -> str | None:
    if raw in (None, ''):
        return None
    s = str(raw).strip().replace(',', '.')
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise MoSiparisError('Geçersiz fiyat.', 400)
    if d <= 0:
        raise MoSiparisError('Fiyat sıfırdan büyük olmalı.', 400)
    return format(d.quantize(Decimal('0.0001')), 'f')


def _norm_vade(raw) -> int | None:
    if raw in (None, ''):
        return None
    try:
        v = int(raw)
    except (TypeError, ValueError):
        raise MoSiparisError('Vade günü tam sayı olmalı.', 400)
    if v < 0:
        raise MoSiparisError('Vade günü negatif olamaz.', 400)
    return v


def _norm_gun(raw) -> int | None:
    if raw in (None, ''):
        return None
    try:
        g = int(raw)
    except (TypeError, ValueError):
        raise MoSiparisError('Gün sayısı tam sayı olmalı.', 400)
    if g < 0:
        raise MoSiparisError('Gün sayısı negatif olamaz.', 400)
    return g


def _extract_tahsilat_plani(payload: dict, *, zorunlu_onay: bool, referans_tarih: str | None = None) -> dict[str, Any]:
    odeme = (payload.get('tahsilat_odeme_sekli') or payload.get('odeme_sekli') or '').strip().upper()
    kural = (payload.get('tahsilat_kurali') or '').strip().upper()
    if zorunlu_onay:
        if odeme not in ODEME_SEKILLERI:
            raise MoSiparisError('Tahsilat ödeme şekli zorunlu.', 400)
        if kural not in TAHSILAT_KURALLARI:
            raise MoSiparisError('Tahsilat kuralı zorunlu.', 400)
    elif not odeme and not kural:
        return {}
    if odeme and odeme not in ODEME_SEKILLERI:
        raise MoSiparisError('Geçersiz tahsilat ödeme şekli.', 400)
    if kural and kural not in TAHSILAT_KURALLARI:
        raise MoSiparisError('Geçersiz tahsilat kuralı.', 400)

    gun = _norm_gun(payload.get('tahsilat_gun_sayisi'))
    sabit = (payload.get('tahsilat_sabit_tarih') or '')[:10] or None
    if zorunlu_onay and kural == 'SEVKTEN_SONRA' and gun is None:
        raise MoSiparisError('Sevkten sonra için gün sayısı zorunlu.', 400)
    if zorunlu_onay and kural == 'SABIT_TARIH' and not sabit:
        raise MoSiparisError('Sabit tahsilat tarihi zorunlu.', 400)

    hesap = {}
    if kural:
        hesap = hesapla_tahsilat_plani(
            kural,
            gun_sayisi=gun,
            sabit_tarih=sabit,
            referans_tarih=referans_tarih,
        )

    return {
        'tahsilat_odeme_sekli': odeme or None,
        'tahsilat_kurali': kural or None,
        'tahsilat_gun_sayisi': gun,
        'tahsilat_sabit_tarih': sabit,
        'planlanan_tahsilat_tarihi': hesap.get('planlanan_tahsilat_tarihi'),
        'tahsilat_sozu': (payload.get('tahsilat_sozu') or '').strip() or None,
        'tahsilat_notu': (payload.get('tahsilat_notu') or '').strip() or None,
        'tahsilat_durumu': hesap.get('tahsilat_durumu'),
        'tahsilat_tarih_kaynagi': hesap.get('tahsilat_tarih_kaynagi'),
        'tahsilat_hesaplanan_sevk_ref': None,
        'cek_teslim_tarihi': (payload.get('cek_teslim_tarihi') or '')[:10] or None,
        'cek_vadesi': (payload.get('cek_vadesi') or '')[:10] or None,
        'tahsilat_durum_metin': hesap.get('durum_metin'),
    }


def _tahsilat_kolonlari_var(con) -> bool:
    return _kolon_var(con, 'nexgen_planlama_siparis', 'tahsilat_kurali')


def _validate_mo_payload(payload: dict, *, zorunlu_onay: bool = False, require_idempotency: bool = True) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise MoSiparisError('JSON gövde gerekli.', 400)
    _reject_technical(payload)

    idem = (payload.get('idempotency_key') or '').strip()
    if require_idempotency and not idem:
        raise MoSiparisError('idempotency_key zorunlu.', 400)

    try:
        cari_id = int(payload.get('cari_id') or 0)
    except (TypeError, ValueError):
        cari_id = 0
    if not cari_id:
        raise MoSiparisError('Müşteri seçimi zorunlu.', 400)

    urun_grubu = (payload.get('urun_grubu') or payload.get('urun_tipi') or '').strip().upper()
    if zorunlu_onay and urun_grubu not in URUN_GRUPLARI:
        raise MoSiparisError('Ürün / ürün grubu zorunlu.', 400)

    urun_adi = (payload.get('urun_adi') or payload.get('urun') or '').strip()
    if zorunlu_onay and not urun_adi:
        raise MoSiparisError('Ürün adı / açıklama zorunlu.', 400)

    miktar = payload.get('miktar')
    if zorunlu_onay and miktar in (None, ''):
        raise MoSiparisError('Miktar zorunlu.', 400)
    if miktar not in (None, ''):
        try:
            miktar_f = round(float(miktar), 3)
        except (TypeError, ValueError):
            raise MoSiparisError('Geçersiz miktar.', 400)
        if miktar_f <= 0:
            raise MoSiparisError('Miktar sıfırdan büyük olmalı.', 400)
    else:
        miktar_f = None

    birim = (payload.get('birim') or 'kg').strip().lower()
    if zorunlu_onay and birim not in BIRIMLER:
        raise MoSiparisError('Geçersiz birim.', 400)

    musteri_termin = (payload.get('musteri_termin') or payload.get('istenen_termin') or '').strip() or None
    if zorunlu_onay and not musteri_termin:
        raise MoSiparisError('Müşterinin istediği termin zorunlu.', 400)

    onerilen_termin = (payload.get('onerilen_termin') or payload.get('verilen_termin') or '').strip() or None
    fiyat = _norm_fiyat(payload.get('fiyat')) if payload.get('fiyat') not in (None, '') else None
    if zorunlu_onay and not fiyat:
        raise MoSiparisError('Fiyat zorunlu.', 400)

    para_birimi = _norm_para(payload.get('para_birimi'))
    vade_gun = _norm_vade(payload.get('vade_gun') or payload.get('vade_talebi'))
    if zorunlu_onay and vade_gun is None:
        raise MoSiparisError('Vade talebi zorunlu.', 400)

    musteri_notu = (payload.get('musteri_notu') or payload.get('musteri_siparis_notu') or '').strip() or None
    if zorunlu_onay and not musteri_notu:
        raise MoSiparisError('Müşteri sipariş notu zorunlu.', 400)

    mo_gorusme_id = payload.get('mo_gorusme_id')
    if mo_gorusme_id not in (None, ''):
        try:
            mo_gorusme_id = int(mo_gorusme_id)
        except (TypeError, ValueError):
            raise MoSiparisError('Geçersiz görüşme bağlantısı.', 400)
    else:
        mo_gorusme_id = None

    meta = {
        'mo_siparis': True,
        'urun_grubu': urun_grubu or None,
        'urun_adi': urun_adi or None,
        'miktar': miktar_f,
        'birim': birim,
        'teslim_sekli': (payload.get('teslim_sekli') or '').strip() or None,
        'musteri_termin': musteri_termin,
        'onerilen_termin': onerilen_termin,
        'musteri_urun_kodu': (payload.get('musteri_urun_kodu') or '').strip() or None,
        'musteri_notu': musteri_notu,
        'ozel_talep': (payload.get('ozel_talep') or '').strip() or None,
        'mo_gorusme_id': mo_gorusme_id,
        'dosya_ref': (payload.get('dosya_ref') or '').strip() or None,
    }

    base = {
        'cari_id': cari_id,
        'kaynak_modul': KAYNAK_MODUL,
        'idempotency_key': idem,
        'mo_gorusme_id': mo_gorusme_id,
        'onay_notu': (payload.get('onay_notu') or '').strip() or None,
        'musteri_urun_kodu': meta['musteri_urun_kodu'],
        'teslim_sekli': meta['teslim_sekli'],
        'musteri_termin': musteri_termin,
        'onerilen_termin': onerilen_termin,
        'termin_tarihi': onerilen_termin,
        'anlasma_birim_fiyat': fiyat,
        'anlasma_para_birimi': para_birimi,
        'vade_gun': vade_gun,
        'notlar': musteri_notu,
        'talep_referansi': mo_siparis_payload_pack(meta),
    }
    ref_tarih = datetime.now().strftime('%Y-%m-%d')
    base.update(_extract_tahsilat_plani(payload, zorunlu_onay=zorunlu_onay, referans_tarih=ref_tarih))
    return base


def _persist_tahsilat_plani(con, siparis_id: int, norm: dict) -> None:
    if not _tahsilat_kolonlari_var(con):
        return
    if not norm.get('tahsilat_kurali') and not norm.get('tahsilat_odeme_sekli'):
        return
    kolonlar = (
        'tahsilat_odeme_sekli', 'tahsilat_kurali', 'tahsilat_gun_sayisi',
        'tahsilat_sabit_tarih', 'planlanan_tahsilat_tarihi', 'tahsilat_sozu',
        'tahsilat_notu', 'tahsilat_durumu', 'tahsilat_tarih_kaynagi',
        'tahsilat_hesaplanan_sevk_ref', 'cek_teslim_tarihi', 'cek_vadesi',
    )
    upd = {k: norm.get(k) for k in kolonlar if k in norm}
    if not upd:
        return
    sets = ','.join(f'{k}=?' for k in upd)
    con.execute(
        f'UPDATE nexgen_planlama_siparis SET {sets} WHERE id=?',
        [*upd.values(), siparis_id],
    )


def taslak_kaydet(
    con: sqlite3.Connection,
    payload: dict,
    kullanici_id: int,
    yk: set[str] | None = None,
    siparis_id: int | None = None,
) -> dict[str, Any]:
    if not _kolon_var(con, 'nexgen_planlama_siparis', 'kaynak_modul'):
        raise MoSiparisError('Migration 125 uygulanmamış.', 503)

    norm = _validate_mo_payload(payload, zorunlu_onay=False)
    if not can_mo_siparis_yaz(con, kullanici_id, int(norm['cari_id']), yk):
        raise MoSiparisError('Bu cari için sipariş talebi açma yetkiniz yok.', 403)

    mevcut_idem = con.execute(
        """
        SELECT id FROM nexgen_planlama_siparis
        WHERE idempotency_key=? AND kaynak_modul=?
        """,
        (norm['idempotency_key'], KAYNAK_MODUL),
    ).fetchone()
    if mevcut_idem and not siparis_id:
        return mo_siparis_detay(con, int(mevcut_idem['id']), kullanici_id, yk)

    cari = con.execute(
        'SELECT id, unvan FROM nexgen_cari WHERE id=? AND aktif=1', (norm['cari_id'],),
    ).fetchone()
    if not cari:
        raise MoSiparisError('Cari bulunamadı.', 404)

    now = _now()
    if siparis_id:
        row = con.execute(
            """
            SELECT id, durum, kaynak_modul, olusturan_id
            FROM nexgen_planlama_siparis WHERE id=?
            """,
            (siparis_id,),
        ).fetchone()
        _mo_row_guard(row)
        if row['durum'] not in DUZENLENEBILIR_MO:
            raise MoSiparisError('Bu durumda düzenleme yapılamaz.', 409)
        if int(row['olusturan_id'] or 0) != kullanici_id:
            raise MoSiparisError('Yalnız kendi taslağınızı düzenleyebilirsiniz.', 403)

        upd = {k: norm[k] for k in (
            'talep_referansi', 'termin_tarihi', 'notlar', 'anlasma_birim_fiyat',
            'anlasma_para_birimi', 'vade_gun', 'onay_notu', 'musteri_urun_kodu',
            'teslim_sekli', 'musteri_termin', 'onerilen_termin', 'mo_gorusme_id',
        )}
        upd['guncelleme_tarihi'] = now
        upd['cari_id'] = norm['cari_id']
        upd['cari_unvan'] = cari['unvan']
        sets = ','.join(f'{k}=?' for k in upd)
        con.execute(f'UPDATE nexgen_planlama_siparis SET {sets} WHERE id=?', [*upd.values(), siparis_id])
        sid = siparis_id
    else:
        cur = con.execute(
            """
            INSERT INTO nexgen_planlama_siparis
                (siparis_no, cari_id, cari_unvan, termin_tarihi, talep_referansi,
                 durum, notlar, olusturan_id, olusturma_tarihi, guncelleme_tarihi,
                 anlasma_para_birimi, vade_gun, anlasma_birim_fiyat,
                 kaynak_modul, mo_gorusme_id, idempotency_key, onay_notu,
                 musteri_urun_kodu, teslim_sekli, musteri_termin, onerilen_termin)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                _siparis_no_uret(con), norm['cari_id'], cari['unvan'],
                norm.get('termin_tarihi'), norm['talep_referansi'], 'TASLAK',
                norm['notlar'], kullanici_id, now, now,
                norm['anlasma_para_birimi'], norm['vade_gun'], norm['anlasma_birim_fiyat'],
                KAYNAK_MODUL, norm['mo_gorusme_id'], norm['idempotency_key'],
                norm['onay_notu'], norm['musteri_urun_kodu'], norm['teslim_sekli'],
                norm['musteri_termin'], norm['onerilen_termin'],
            ),
        )
        sid = int(cur.lastrowid)
        _shadow_olay(con, 'MUSTERI_SIPARIS_TASLAK_OLUSTU', {'id': sid, 'cari_id': norm['cari_id']})

    _persist_tahsilat_plani(con, sid, norm)
    con.commit()
    return mo_siparis_detay(con, sid, kullanici_id, yk)


def mo_siparis_detay(con, siparis_id: int, kullanici_id: int, yk: set[str] | None = None) -> dict[str, Any]:
    row = con.execute(
        """
        SELECT ps.*, sk.KullaniciAdi AS olusturan_ad
        FROM nexgen_planlama_siparis ps
        LEFT JOIN sistem_kullanici sk ON sk.Id = ps.olusturan_id
        WHERE ps.id=?
        """,
        (siparis_id,),
    ).fetchone()
    _mo_row_guard(row)
    cid = int(row['cari_id'] or 0)
    if cid and not can_mo_siparis_yaz(con, kullanici_id, cid, yk):
        raise MoSiparisError('Bu siparişi görüntüleme yetkiniz yok.', 403)

    d = dict(row)
    d['mo_payload'] = mo_siparis_payload_unpack(d.get('talep_referansi')) or {}
    d['duzenlenebilir'] = d['durum'] in DUZENLENEBILIR_MO
    d['read_only'] = d['durum'] in READONLY_MO
    if d.get('mo_gorusme_id') and _tablo_var(con, 'musteri_operasyon_gorusme'):
        g = con.execute(
            'SELECT id, gorusme_tipi, kisa_not, gorusme_tarihi FROM musteri_operasyon_gorusme WHERE id=?',
            (d['mo_gorusme_id'],),
        ).fetchone()
        d['bagli_gorusme'] = dict(g) if g else None
    else:
        d['bagli_gorusme'] = None
    ot = con.execute(
        """
        SELECT id, talep_kod, durum FROM onay_talep
        WHERE kaynak_modul='nexgen_planlama_siparis' AND kaynak_id=?
        ORDER BY id DESC LIMIT 1
        """,
        (siparis_id,),
    ).fetchone()
    d['son_onay'] = dict(ot) if ot else None
    return d


def ozet_olustur(con, siparis_id: int, kullanici_id: int, yk: set[str] | None = None) -> dict[str, Any]:
    s = mo_siparis_detay(con, siparis_id, kullanici_id, yk)
    p = s.get('mo_payload') or {}
    return {
        'siparis_id': s['id'],
        'siparis_no': s['siparis_no'],
        'cari_unvan': s.get('cari_unvan'),
        'urun_grubu': p.get('urun_grubu'),
        'urun_adi': p.get('urun_adi'),
        'miktar': p.get('miktar'),
        'birim': p.get('birim'),
        'fiyat': s.get('anlasma_birim_fiyat'),
        'para_birimi': s.get('anlasma_para_birimi'),
        'vade_gun': s.get('vade_gun'),
        'musteri_termin': s.get('musteri_termin') or p.get('musteri_termin'),
        'onerilen_termin': s.get('onerilen_termin') or p.get('onerilen_termin'),
        'teslim_sekli': s.get('teslim_sekli') or p.get('teslim_sekli'),
        'musteri_notu': s.get('notlar'),
        'musteri_urun_kodu': s.get('musteri_urun_kodu'),
        'bagli_gorusme': s.get('bagli_gorusme'),
        'onay_notu': s.get('onay_notu'),
        'revizyon_gerekce': s.get('revizyon_gerekce'),
        'dosya_ref': s.get('dosya_ref') or p.get('dosya_ref'),
        'durum': s['durum'],
        'tahsilat_odeme_sekli': s.get('tahsilat_odeme_sekli'),
        'tahsilat_odeme_sekli_etiket': ODEME_SEKLI_ETIKET.get(s.get('tahsilat_odeme_sekli') or '', s.get('tahsilat_odeme_sekli')),
        'tahsilat_kurali': s.get('tahsilat_kurali'),
        'tahsilat_kural_etiket': tahsilat_kural_etiket(s.get('tahsilat_kurali')),
        'tahsilat_gun_sayisi': s.get('tahsilat_gun_sayisi'),
        'tahsilat_sabit_tarih': s.get('tahsilat_sabit_tarih'),
        'planlanan_tahsilat_tarihi': s.get('planlanan_tahsilat_tarihi'),
        'tahsilat_sozu': s.get('tahsilat_sozu'),
        'tahsilat_notu': s.get('tahsilat_notu'),
        'tahsilat_durumu': s.get('tahsilat_durumu'),
        'tahsilat_durum_metin': _extract_tahsilat_plani(
            {'tahsilat_kurali': s.get('tahsilat_kurali'), 'tahsilat_gun_sayisi': s.get('tahsilat_gun_sayisi'),
             'tahsilat_sabit_tarih': s.get('tahsilat_sabit_tarih')},
            zorunlu_onay=False,
            referans_tarih=(s.get('olusturma_tarihi') or '')[:10] or None,
        ).get('tahsilat_durum_metin'),
        'cek_teslim_tarihi': s.get('cek_teslim_tarihi'),
        'cek_vadesi': s.get('cek_vadesi'),
    }


def onaya_gonder(
    con: sqlite3.Connection,
    siparis_id: int,
    kullanici_id: int,
    yk: set[str] | None = None,
    payload: dict | None = None,
) -> dict[str, Any]:
    from modules.nexgen.onay_satis_adapter import satis_onaya_gonder

    row = con.execute(
        """
        SELECT id, durum, cari_id, kaynak_modul, olusturan_id
        FROM nexgen_planlama_siparis WHERE id=?
        """,
        (siparis_id,),
    ).fetchone()
    _mo_row_guard(row)
    if row['durum'] not in ONAYA_GONDERILEBILIR:
        raise MoSiparisError('Bu durumda onaya gönderilemez.', 409)
    if int(row['olusturan_id'] or 0) != kullanici_id:
        raise MoSiparisError('Yalnız kendi talebinizi onaya gönderebilirsiniz.', 403)
    if not can_mo_siparis_yaz(con, kullanici_id, int(row['cari_id']), yk):
        raise MoSiparisError('Yetki yok.', 403)

    if payload:
        norm = _validate_mo_payload(
            {**payload, 'cari_id': row['cari_id']},
            zorunlu_onay=True,
            require_idempotency=False,
        )
        norm['guncelleme_tarihi'] = _now()
        cari = con.execute('SELECT unvan FROM nexgen_cari WHERE id=?', (norm['cari_id'],)).fetchone()
        upd = {k: norm[k] for k in (
            'talep_referansi', 'termin_tarihi', 'notlar', 'anlasma_birim_fiyat',
            'anlasma_para_birimi', 'vade_gun', 'onay_notu', 'musteri_urun_kodu',
            'teslim_sekli', 'musteri_termin', 'onerilen_termin', 'mo_gorusme_id',
        )}
        upd['guncelleme_tarihi'] = norm['guncelleme_tarihi']
        upd['cari_unvan'] = cari['unvan'] if cari else None
        sets = ','.join(f'{k}=?' for k in upd)
        con.execute(f'UPDATE nexgen_planlama_siparis SET {sets} WHERE id=?', [*upd.values(), siparis_id])
        _persist_tahsilat_plani(con, siparis_id, norm)
    elif _tahsilat_kolonlari_var(con):
        existing = con.execute(
            """
            SELECT tahsilat_kurali, tahsilat_odeme_sekli, olusturma_tarihi
            FROM nexgen_planlama_siparis WHERE id=?
            """,
            (siparis_id,),
        ).fetchone()
        if not existing or not existing['tahsilat_kurali'] or not existing['tahsilat_odeme_sekli']:
            raise MoSiparisError('Tahsilat planı zorunlu.', 400)

    rev = con.execute(
        """
        SELECT COALESCE(MAX(revizyon_no),0)+1 FROM onay_talep
        WHERE kaynak_modul='nexgen_planlama_siparis' AND kaynak_id=?
        """,
        (siparis_id,),
    ).fetchone()[0]

    r = satis_onaya_gonder(con, siparis_id, kullanici_id, int(rev or 1))
    if not r.get('ok'):
        raise MoSiparisError(r.get('hata') or 'Onaya gönderilemedi.', 409 if r.get('code') == 'DUPLICATE' else 400)

    con.execute(
        """
        UPDATE nexgen_planlama_siparis
        SET durum='ONAY_BEKLIYOR', revizyon_gerekce=NULL, guncelleme_tarihi=?
        WHERE id=?
        """,
        (_now(), siparis_id),
    )
    _shadow_olay(con, 'MUSTERI_SIPARIS_ONAYA_GONDERILDI', {'id': siparis_id, 'onay_talep_id': r.get('talep_id')})
    con.commit()
    return {'ok': True, 'siparis_id': siparis_id, 'onay_talep_id': r.get('talep_id'), 'talep_kod': r.get('talep_kod')}


def revizyon_uygula(con, siparis_id: int, notu: str) -> None:
    if not _kolon_var(con, 'nexgen_planlama_siparis', 'revizyon_gerekce'):
        return
    con.execute(
        """
        UPDATE nexgen_planlama_siparis
        SET durum='REVIZYON', revizyon_gerekce=?, guncelleme_tarihi=?
        WHERE id=? AND kaynak_modul=?
        """,
        (notu, _now(), siparis_id, KAYNAK_MODUL),
    )
    _shadow_olay(con, 'MUSTERI_SIPARIS_REVIZYON_ISTENDI', {'id': siparis_id})


def red_uygula(con, siparis_id: int, notu: str) -> None:
    con.execute(
        """
        UPDATE nexgen_planlama_siparis
        SET durum='REDDEDILDI', revizyon_gerekce=?, guncelleme_tarihi=?
        WHERE id=? AND kaynak_modul=?
        """,
        (notu, _now(), siparis_id, KAYNAK_MODUL),
    )
    _shadow_olay(con, 'MUSTERI_SIPARIS_REDDEDILDI', {'id': siparis_id})


def list_mo_siparis_talepleri(
    con: sqlite3.Connection,
    kullanici_id: int,
    yk: set[str] | None = None,
    cari_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    if not _kolon_var(con, 'nexgen_planlama_siparis', 'kaynak_modul'):
        return []
    sql = """
        SELECT ps.id, ps.siparis_no, ps.durum, ps.cari_id, ps.cari_unvan,
               ps.musteri_termin, ps.olusturma_tarihi, ps.anlasma_birim_fiyat,
               ps.anlasma_para_birimi, ps.vade_gun
        FROM nexgen_planlama_siparis ps
        WHERE ps.kaynak_modul=? AND ps.olusturan_id=?
    """
    params: list[Any] = [KAYNAK_MODUL, kullanici_id]
    if cari_ids:
        ph = ','.join(['?'] * len(cari_ids))
        sql += f' AND ps.cari_id IN ({ph})'
        params.extend(cari_ids)
    sql += ' ORDER BY ps.guncelleme_tarihi DESC, ps.id DESC LIMIT 50'
    return [dict(r) for r in con.execute(sql, params).fetchall()]
