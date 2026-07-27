# -*- coding: utf-8 -*-
"""Müşteri Operasyonu numune talebi — taslak + merkezi onay köprüsü."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from modules.nexgen.mo_gorusme_config import KAYNAK_MUSTERI_OPERASYONU, ONCELIKLER
from modules.nexgen.mo_gorusme_service import can_mo_gorusme_yaz
from modules.nexgen.numune_talep_service import (
    NumuneTalepError,
    _apply_karsilama_isolation,
    _insert_fields,
    _norm_karsilama_yolu,
    _norm_oncelik,
    _norm_urun_tipi,
    get_talep,
    uret_talep_kodu,
)

KAYNAK_MODUL = KAYNAK_MUSTERI_OPERASYONU
DUZENLENEBILIR_MO = frozenset({'TASLAK', 'REVIZYON_ISTENDI'})
ONAYA_GONDERILEBILIR = frozenset({'TASLAK', 'REVIZYON_ISTENDI'})
READONLY_MO = frozenset({'ONAY_BEKLIYOR', 'REDDEDILDI'})

OLAY_MOTORU_AKTIF = False


class MoNumuneError(Exception):
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
    if OLAY_MOTORU_AKTIF:
        return
    if not _tablo_var(con, 'cari360_olay_shadow'):
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


def numune_olay_sozlesmesi(olay_tipi: str, kayit: dict[str, Any]) -> dict[str, Any]:
    return {
        'olay_tipi': olay_tipi,
        'kaynak_modul': KAYNAK_MODUL,
        'kaynak_id': kayit.get('id'),
        'cari_id': kayit.get('cari_id'),
        'talep_kodu': kayit.get('talep_kodu'),
        'durum': kayit.get('durum'),
        'olay_motoru_aktif': OLAY_MOTORU_AKTIF,
    }


def _mo_row_guard(row) -> None:
    if not row:
        raise MoNumuneError('Talep bulunamadı.', 404)
    if (row['kaynak_modul'] or '') != KAYNAK_MODUL:
        raise MoNumuneError('Bu kayıt Müşteri Operasyonu numune talebi değil.', 403)


def can_mo_numune_yaz(
    con: sqlite3.Connection,
    kullanici_id: int,
    cari_id: int,
    yk: set[str] | None = None,
) -> bool:
    return can_mo_gorusme_yaz(con, kullanici_id, cari_id, yk)


def _validate_mo_payload(
    payload: dict,
    *,
    zorunlu_onay: bool = False,
    require_idempotency: bool = True,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise MoNumuneError('JSON gövde gerekli.', 400)

    idem = (payload.get('idempotency_key') or '').strip()
    if require_idempotency and not idem:
        raise MoNumuneError('idempotency_key zorunlu.', 400)

    try:
        cari_id = int(payload.get('cari_id') or 0)
    except (TypeError, ValueError):
        cari_id = 0
    if not cari_id:
        raise MoNumuneError('Müşteri seçimi zorunlu.', 400)

    urun_tipi = _norm_urun_tipi(payload.get('urun_tipi'))
    if zorunlu_onay and not urun_tipi:
        raise MoNumuneError('Ürün tipi zorunlu.', 400)

    urun_adi = (payload.get('urun_adi') or '').strip()
    if zorunlu_onay and not urun_adi:
        raise MoNumuneError('Ürün adı / model zorunlu.', 400)

    karsilama = _norm_karsilama_yolu(payload.get('karsilama_yolu') or payload.get('talep_turu'))
    if zorunlu_onay and not karsilama:
        raise MoNumuneError('Talep türü zorunlu.', 400)
    if karsilama and karsilama not in ('HAZIR_RENK', 'YENI_RENK', 'YENI_FORMUL'):
        raise MoNumuneError('Geçersiz talep türü.', 400)

    musteri_talebi = (payload.get('musteri_talebi') or payload.get('aciklama') or '').strip()
    if zorunlu_onay and len(musteri_talebi) < 3:
        raise MoNumuneError('Müşteri talebi zorunlu (en az 3 karakter).', 400)

    hedef = (payload.get('hedef_tarih') or payload.get('istenen_termin') or '').strip() or None
    if zorunlu_onay and not hedef:
        raise MoNumuneError('İstenen termin zorunlu.', 400)

    oncelik = _norm_oncelik(payload.get('oncelik'))
    if oncelik not in ONCELIKLER:
        oncelik = 'NORMAL'

    mo_gorusme_id = payload.get('mo_gorusme_id')
    if mo_gorusme_id not in (None, ''):
        try:
            mo_gorusme_id = int(mo_gorusme_id)
        except (TypeError, ValueError):
            raise MoNumuneError('Geçersiz görüşme bağlantısı.', 400)
    else:
        mo_gorusme_id = None

    data = {
        'musteri_tipi': 'MEVCUT',
        'cari_id': cari_id,
        'talep_eden_kullanici_id': payload.get('talep_eden_kullanici_id'),
        'oncelik': oncelik,
        'hedef_tarih': hedef,
        'aciklama': musteri_talebi or None,
        'talep_nedeni': musteri_talebi or None,
        'ek_not': (payload.get('ek_not') or payload.get('not') or '').strip() or None,
        'urun_tipi': urun_tipi,
        'urun_adi': urun_adi or None,
        'karsilama_yolu': karsilama,
        'ref_renk_kodu': (payload.get('ref_renk_kodu') or payload.get('referans_renk') or '').strip() or None,
        'yeni_renk_aciklama': (payload.get('yeni_renk_aciklama') or '').strip() or None,
        'musteri_urun_kodu': (payload.get('musteri_urun_kodu') or '').strip() or None,
        'onay_notu': (payload.get('onay_notu') or '').strip() or None,
        'dosya_ref': (payload.get('dosya_ref') or '').strip() or None,
        'mo_gorusme_id': mo_gorusme_id,
        'kaynak_modul': KAYNAK_MODUL,
        'idempotency_key': idem,
        'diger_beklentiler_json': json.dumps([], ensure_ascii=False),
        'renk_tipi': None,
        'rf_renk_id': None,
    }
    if karsilama:
        data = _apply_karsilama_isolation(data)
    return data


def _audit_json(islem: str, kullanici_id: int, extra: dict | None = None) -> str:
    body = {'islem': islem, 'kullanici_id': kullanici_id, 'tarih': _now()}
    if extra:
        body.update(extra)
    return json.dumps(body, ensure_ascii=False)


def taslak_kaydet(
    con: sqlite3.Connection,
    payload: dict,
    kullanici_id: int,
    yk: set[str] | None = None,
    talep_id: int | None = None,
) -> dict[str, Any]:
    if not _kolon_var(con, 'nexgen_numune_talep', 'kaynak_modul'):
        raise MoNumuneError('Migration 124 uygulanmamış.', 503)

    norm = _validate_mo_payload(payload, zorunlu_onay=False)
    if not can_mo_numune_yaz(con, kullanici_id, int(norm['cari_id']), yk):
        raise MoNumuneError('Bu cari için numune talebi açma yetkiniz yok.', 403)

    if not norm.get('talep_eden_kullanici_id'):
        norm['talep_eden_kullanici_id'] = kullanici_id

    mevcut_idem = con.execute(
        """
        SELECT id FROM nexgen_numune_talep
        WHERE idempotency_key=? AND aktif=1 AND kaynak_modul=?
        """,
        (norm['idempotency_key'], KAYNAK_MODUL),
    ).fetchone()
    if mevcut_idem and not talep_id:
        return mo_talep_detay(con, int(mevcut_idem['id']), kullanici_id, yk)

    now = _now()
    if talep_id:
        row = con.execute(
            """
            SELECT id, durum, arge_test_id, kaynak_modul, talep_eden_kullanici_id
            FROM nexgen_numune_talep WHERE id=? AND aktif=1
            """,
            (talep_id,),
        ).fetchone()
        _mo_row_guard(row)
        if row['durum'] not in DUZENLENEBILIR_MO:
            raise MoNumuneError('Bu durumda düzenleme yapılamaz.', 409)
        if row['arge_test_id']:
            raise MoNumuneError('Bağlı AR-GE kartı var — düzenlenemez.', 409)
        if int(row['talep_eden_kullanici_id'] or 0) != kullanici_id and not can_mo_numune_yaz(
            con, kullanici_id, int(norm['cari_id']), yk
        ):
            raise MoNumuneError('Yalnız kendi taslağınızı düzenleyebilirsiniz.', 403)

        norm['guncelleme_tarihi'] = now
        norm['durum'] = 'TASLAK' if row['durum'] == 'TASLAK' else row['durum']
        norm.pop('idempotency_key', None)
        sets = ','.join(f'{k}=?' for k in norm)
        con.execute(
            f'UPDATE nexgen_numune_talep SET {sets} WHERE id=?',
            [*norm.values(), talep_id],
        )
        tid = talep_id
    else:
        cari = con.execute(
            'SELECT id, unvan FROM nexgen_cari WHERE id=? AND aktif=1',
            (norm['cari_id'],),
        ).fetchone()
        if not cari:
            raise MoNumuneError('Cari bulunamadı.', 404)

        norm.update({
            'talep_kodu': uret_talep_kodu(con),
            'durum': 'TASLAK',
            'olusturan_kullanici_id': kullanici_id,
            'olusturma_tarihi': now,
            'guncelleme_tarihi': now,
            'aktif': 1,
        })
        cols, vals = _insert_fields(norm)
        cur = con.execute(
            f'INSERT INTO nexgen_numune_talep ({cols}) VALUES ({",".join(["?"] * len(vals))})',
            vals,
        )
        tid = int(cur.lastrowid)
        _shadow_olay(con, 'MUSTERI_NUMUNE_TASLAK_OLUSTU', numune_olay_sozlesmesi(
            'MUSTERI_NUMUNE_TASLAK_OLUSTU', {'id': tid, 'cari_id': norm['cari_id'], 'talep_kodu': norm['talep_kodu'], 'durum': 'TASLAK'},
        ))

    con.commit()
    return mo_talep_detay(con, tid, kullanici_id, yk)


def mo_talep_detay(
    con: sqlite3.Connection,
    talep_id: int,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> dict[str, Any]:
    row = con.execute(
        """
        SELECT nt.*, c.unvan AS cari_unvan, c.cari_kod,
               sk.KullaniciAdi AS talep_eden_ad
        FROM nexgen_numune_talep nt
        LEFT JOIN nexgen_cari c ON c.id = nt.cari_id
        LEFT JOIN sistem_kullanici sk ON sk.Id = nt.talep_eden_kullanici_id
        WHERE nt.id=? AND nt.aktif=1
        """,
        (talep_id,),
    ).fetchone()
    _mo_row_guard(row)
    cid = int(row['cari_id'] or 0)
    if cid and not can_mo_numune_yaz(con, kullanici_id, cid, yk):
        raise MoNumuneError('Bu talebi görüntüleme yetkiniz yok.', 403)

    d = dict(row)
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
    return d


def ozet_olustur(con: sqlite3.Connection, talep_id: int, kullanici_id: int, yk: set[str] | None = None) -> dict[str, Any]:
    t = mo_talep_detay(con, talep_id, kullanici_id, yk)
    return {
        'talep_id': t['id'],
        'talep_kodu': t['talep_kodu'],
        'cari_unvan': t.get('cari_unvan'),
        'urun_tipi': t.get('urun_tipi'),
        'urun_adi': t.get('urun_adi'),
        'talep_turu': t.get('karsilama_yolu'),
        'hedef_tarih': t.get('hedef_tarih'),
        'oncelik': t.get('oncelik'),
        'musteri_talebi': t.get('aciklama') or t.get('talep_nedeni'),
        'musteri_urun_kodu': t.get('musteri_urun_kodu'),
        'ref_renk_kodu': t.get('ref_renk_kodu'),
        'dosya_ref': t.get('dosya_ref'),
        'urun_gorsel_belge_id': t.get('urun_gorsel_belge_id'),
        'bagli_gorusme': t.get('bagli_gorusme'),
        'onay_notu': t.get('onay_notu'),
        'revizyon_gerekce': t.get('revizyon_gerekce'),
        'durum': t['durum'],
    }


def onaya_gonder(
    con: sqlite3.Connection,
    talep_id: int,
    kullanici_id: int,
    yk: set[str] | None = None,
    payload: dict | None = None,
) -> dict[str, Any]:
    from modules.nexgen.onay_numune_adapter import numune_onaya_gonder

    row = con.execute(
        """
        SELECT id, durum, cari_id, kaynak_modul, arge_test_id, talep_eden_kullanici_id
        FROM nexgen_numune_talep WHERE id=? AND aktif=1
        """,
        (talep_id,),
    ).fetchone()
    _mo_row_guard(row)
    if row['durum'] not in ONAYA_GONDERILEBILIR:
        raise MoNumuneError('Bu durumda onaya gönderilemez.', 409)
    if row['arge_test_id']:
        raise MoNumuneError('AR-GE köprüsü mevcut — onay akışı kullanılamaz.', 409)
    if int(row['talep_eden_kullanici_id'] or 0) != kullanici_id:
        raise MoNumuneError('Yalnız kendi talebinizi onaya gönderebilirsiniz.', 403)
    if not can_mo_numune_yaz(con, kullanici_id, int(row['cari_id']), yk):
        raise MoNumuneError('Yetki yok.', 403)

    if payload:
        norm = _validate_mo_payload(
            {**payload, 'cari_id': row['cari_id']},
            zorunlu_onay=True,
            require_idempotency=False,
        )
        norm['guncelleme_tarihi'] = _now()
        norm.pop('idempotency_key', None)
        if not norm.get('talep_eden_kullanici_id'):
            norm.pop('talep_eden_kullanici_id', None)
        sets = ','.join(f'{k}=?' for k in norm)
        con.execute(
            f'UPDATE nexgen_numune_talep SET {sets} WHERE id=?',
            [*norm.values(), talep_id],
        )

    rev = con.execute(
        """
        SELECT COALESCE(MAX(revizyon_no),0)+1 FROM onay_talep
        WHERE kaynak_modul='nexgen_numune_talep' AND kaynak_id=?
        """,
        (talep_id,),
    ).fetchone()[0]

    r = numune_onaya_gonder(con, talep_id, kullanici_id, int(rev or 1))
    if not r.get('ok'):
        raise MoNumuneError(r.get('hata') or 'Onaya gönderilemedi.', 409 if r.get('code') == 'DUPLICATE' else 400)

    con.execute(
        """
        UPDATE nexgen_numune_talep
        SET durum='ONAY_BEKLIYOR', revizyon_gerekce=NULL, guncelleme_tarihi=?
        WHERE id=?
        """,
        (_now(), talep_id),
    )
    _shadow_olay(con, 'MUSTERI_NUMUNE_ONAYA_GONDERILDI', numune_olay_sozlesmesi(
        'MUSTERI_NUMUNE_ONAYA_GONDERILDI',
        {'id': talep_id, 'cari_id': row['cari_id'], 'onay_talep_id': r.get('talep_id'), 'durum': 'ONAY_BEKLIYOR'},
    ))
    con.commit()
    return {'ok': True, 'talep_id': talep_id, 'onay_talep_id': r.get('talep_id'), 'talep_kod': r.get('talep_kod')}


def list_mo_numune_talepleri(
    con: sqlite3.Connection,
    kullanici_id: int,
    yk: set[str] | None = None,
    cari_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    if not _kolon_var(con, 'nexgen_numune_talep', 'kaynak_modul'):
        return []
    sql = """
        SELECT nt.id, nt.talep_kodu, nt.durum, nt.cari_id, nt.karsilama_yolu,
               nt.urun_adi, nt.hedef_tarih, nt.oncelik, nt.olusturma_tarihi,
               nt.arge_test_id, c.unvan AS cari_unvan
        FROM nexgen_numune_talep nt
        LEFT JOIN nexgen_cari c ON c.id = nt.cari_id
        WHERE nt.aktif=1 AND nt.kaynak_modul=? AND nt.talep_eden_kullanici_id=?
    """
    params: list[Any] = [KAYNAK_MODUL, kullanici_id]
    if cari_ids:
        ph = ','.join(['?'] * len(cari_ids))
        sql += f' AND nt.cari_id IN ({ph})'
        params.extend(cari_ids)
    sql += ' ORDER BY nt.guncelleme_tarihi DESC, nt.id DESC LIMIT 50'
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def revizyon_uygula(con, talep_id: int, notu: str) -> None:
    con.execute(
        """
        UPDATE nexgen_numune_talep
        SET durum='REVIZYON_ISTENDI', revizyon_gerekce=?, guncelleme_tarihi=?
        WHERE id=? AND kaynak_modul=?
        """,
        (notu, _now(), talep_id, KAYNAK_MODUL),
    )
    _shadow_olay(con, 'MUSTERI_NUMUNE_REVIZYON_ISTENDI', numune_olay_sozlesmesi(
        'MUSTERI_NUMUNE_REVIZYON_ISTENDI', {'id': talep_id, 'durum': 'REVIZYON_ISTENDI'},
    ))


def red_uygula(con, talep_id: int, notu: str) -> None:
    con.execute(
        """
        UPDATE nexgen_numune_talep
        SET durum='REDDEDILDI', revizyon_gerekce=?, guncelleme_tarihi=?
        WHERE id=? AND kaynak_modul=?
        """,
        (notu, _now(), talep_id, KAYNAK_MODUL),
    )
    _shadow_olay(con, 'MUSTERI_NUMUNE_REDDEDILDI', numune_olay_sozlesmesi(
        'MUSTERI_NUMUNE_REDDEDILDI', {'id': talep_id, 'durum': 'REDDEDILDI'},
    ))


def onay_sonrasi_uygula(con, talep_id: int, onay_talep_id: int) -> dict[str, Any]:
    row = con.execute(
        'SELECT id, durum, arge_test_id FROM nexgen_numune_talep WHERE id=? AND kaynak_modul=?',
        (talep_id, KAYNAK_MODUL),
    ).fetchone()
    if not row:
        return {'ok': False, 'hata': 'Talep yok'}
    if row['arge_test_id']:
        return {'ok': True, 'skip': True, 'talep_id': talep_id}
    if row['durum'] == 'ONAYLANDI':
        return {'ok': True, 'skip': True, 'talep_id': talep_id}

    con.execute(
        """
        UPDATE nexgen_numune_talep
        SET durum='ONAYLANDI', guncelleme_tarihi=?
        WHERE id=?
        """,
        (_now(), talep_id),
    )
    _shadow_olay(con, 'MUSTERI_NUMUNE_ONAYLANDI', numune_olay_sozlesmesi(
        'MUSTERI_NUMUNE_ONAYLANDI', {'id': talep_id, 'onay_talep_id': onay_talep_id, 'durum': 'ONAYLANDI'},
    ))
    return {'ok': True, 'talep_id': talep_id, 'durum': 'ONAYLANDI'}
