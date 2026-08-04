# -*- coding: utf-8 -*-
"""Ortak müşteri aday kimliği — nexgen_musteri_aday.

FAZ-NEXGEN-MUSTERI-ADAY-ORTAK-KIMLIK-VE-ILK-GORUSME-1
Cariye dönüştürme bu fazda yok.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from modules.nexgen.cari360_yetki import (
    can_cari360_crm_write,
    can_cari360_view_all,
    can_cari360_view_own,
    can_musteri_pazarlama_menu,
)
from modules.nexgen.cari_sorumlu_service import load_kullanici_yetkileri

TABLO = 'nexgen_musteri_aday'
DURUM_ADAY = 'ADAY'
DURUM_DONUSTURULDU = 'DONUSTURULDU'
DURUM_IPTAL = 'IPTAL'
DURUMLAR = frozenset({DURUM_ADAY, DURUM_DONUSTURULDU, DURUM_IPTAL})
GUNCELLENEBILIR = frozenset({'firma_adi', 'yetkili_adi', 'telefon', 'sehir', 'not_metni'})


class MusteriAdayError(Exception):
    def __init__(self, mesaj: str, kod: int = 400):
        self.mesaj = mesaj
        self.kod = kod
        super().__init__(mesaj)


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _row(r) -> dict[str, Any]:
    return dict(r) if r is not None else {}


def can_aday_yaz(
    con: sqlite3.Connection,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> bool:
    """Gerçek pazarlamacı (view_own+crm) veya admin. Mehmet (plan.manage) hayır."""
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if not can_musteri_pazarlama_menu(yk):
        return False
    if can_cari360_view_all(yk) or '*' in (yk or set()):
        return True
    return can_cari360_view_own(yk) and can_cari360_crm_write(yk)


def can_aday_gor(
    con: sqlite3.Connection,
    kullanici_id: int,
    aday: dict[str, Any] | int,
    yk: set[str] | None = None,
) -> bool:
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if not can_musteri_pazarlama_menu(yk):
        return False
    if can_cari360_view_all(yk) or '*' in (yk or set()):
        return True
    if isinstance(aday, int):
        row = aday_getir(con, aday, kullanici_id, yk, _skip_auth=True)
        if not row:
            return False
        aday = row
    return int(aday.get('olusturan_kullanici_id') or 0) == int(kullanici_id)


def aday_olustur(
    con: sqlite3.Connection,
    payload: dict,
    olusturan_kullanici_id: int,
    *,
    commit: bool = True,
) -> int:
    if not _tablo_var(con, TABLO):
        raise MusteriAdayError('Aday tablosu hazır değil (migration 142).', 503)
    if not olusturan_kullanici_id:
        raise MusteriAdayError('olusturan_kullanici_id zorunlu.', 400)

    firma = (payload.get('firma_adi') or '').strip()
    if not firma:
        raise MusteriAdayError('Firma adı zorunlu.', 400)

    yetkili = (payload.get('yetkili_adi') or '').strip() or None
    telefon = (payload.get('telefon') or '').strip() or None
    sehir = (payload.get('sehir') or '').strip() or None
    not_metni = (payload.get('not_metni') or payload.get('not') or '').strip() or None
    idem = (payload.get('idempotency_key') or '').strip() or None

    if idem:
        mevcut = con.execute(
            f'SELECT id FROM {TABLO} WHERE idempotency_key=?', (idem,),
        ).fetchone()
        if mevcut:
            return int(mevcut['id'] if hasattr(mevcut, 'keys') else mevcut[0])

    cur = con.execute(
        f"""
        INSERT INTO {TABLO} (
            firma_adi, yetkili_adi, telefon, sehir, not_metni, durum,
            olusturan_kullanici_id, nexgen_cari_id, idempotency_key, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            firma, yetkili, telefon, sehir, not_metni, DURUM_ADAY,
            int(olusturan_kullanici_id), None, idem, _now(),
        ),
    )
    aid = int(cur.lastrowid)
    if commit:
        con.commit()
    return aid


def aday_getir(
    con: sqlite3.Connection,
    aday_id: int,
    kullanici_id: int | None = None,
    yk: set[str] | None = None,
    *,
    _skip_auth: bool = False,
) -> dict[str, Any] | None:
    if not _tablo_var(con, TABLO):
        return None
    row = con.execute(f'SELECT * FROM {TABLO} WHERE id=?', (aday_id,)).fetchone()
    if not row:
        return None
    d = _row(row)
    if not _skip_auth and kullanici_id is not None:
        if not can_aday_gor(con, kullanici_id, d, yk):
            raise MusteriAdayError('Bu adaya erişim yetkiniz yok.', 403)
    return d


def aday_listele(
    con: sqlite3.Connection,
    kullanici_id: int,
    yk: set[str] | None = None,
    *,
    durum: str | None = DURUM_ADAY,
    limit: int = 60,
) -> list[dict[str, Any]]:
    if not _tablo_var(con, TABLO):
        return []
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if not can_musteri_pazarlama_menu(yk):
        return []

    params: list[Any] = []
    where = ['1=1']
    if durum:
        where.append('durum=?')
        params.append(durum)
    if not (can_cari360_view_all(yk) or '*' in yk):
        where.append('olusturan_kullanici_id=?')
        params.append(int(kullanici_id))

    params.append(int(limit))
    rows = con.execute(
        f"""
        SELECT a.*,
               COALESCE(NULLIF(TRIM(sk.AdSoyad), ''), sk.KullaniciAdi) AS olusturan_adi
        FROM {TABLO} a
        LEFT JOIN sistem_kullanici sk ON sk.Id = a.olusturan_kullanici_id
        WHERE {' AND '.join(where)}
        ORDER BY a.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_row(r) for r in rows]


def _gorusme_ozet_aday(con: sqlite3.Connection, aday_id: int) -> dict[str, Any]:
    from modules.nexgen.mo_gorusme_config import TABLO as GORUSME_TABLO
    from modules.nexgen.mo_gorusme_service import fiyat_ozet_metin

    out = {
        'gorusme_sayisi': 0,
        'son_gorusme_tarihi': None,
        'son_gorusme_metin': None,
        'son_sonuc': None,
        'son_kisa_not': None,
        'son_fiyat_ozet': None,
        'gorusmeler': [],
    }
    if not _tablo_var(con, GORUSME_TABLO):
        return out
    out['gorusme_sayisi'] = int(con.execute(
        f"SELECT COUNT(*) FROM {GORUSME_TABLO} WHERE musteri_aday_id=? AND aktif=1",
        (aday_id,),
    ).fetchone()[0] or 0)
    rows = con.execute(
        f"""
        SELECT g.*,
               COALESCE(NULLIF(TRIM(sk.AdSoyad), ''), sk.KullaniciAdi) AS pazarlamaci_adi
        FROM {GORUSME_TABLO} g
        LEFT JOIN sistem_kullanici sk ON sk.Id = g.kullanici_id
        WHERE g.musteri_aday_id=? AND g.aktif=1
        ORDER BY g.gorusme_tarihi DESC, g.id DESC
        LIMIT 20
        """,
        (aday_id,),
    ).fetchall()
    gecmis = []
    for r in rows:
        d = _row(r)
        d['fiyat_ozet'] = fiyat_ozet_metin(d)
        gecmis.append(d)
    out['gorusmeler'] = gecmis
    if gecmis:
        sg = gecmis[0]
        out['son_gorusme_tarihi'] = (sg.get('gorusme_tarihi') or '')[:10] or None
        out['son_sonuc'] = sg.get('sonuc_tipi')
        out['son_kisa_not'] = (sg.get('kisa_not') or '')[:80] or None
        out['son_fiyat_ozet'] = sg.get('fiyat_ozet')
        out['son_gorusme_metin'] = (
            f"{out['son_gorusme_tarihi'] or '—'} — "
            f"{sg.get('gorusme_tipi') or ''} ({sg.get('sonuc_tipi') or ''})"
        ).strip()
    return out


def aday_havuz_liste(
    con: sqlite3.Connection,
    kullanici_id: int,
    yk: set[str] | None = None,
    *,
    durum: str | None = DURUM_ADAY,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Yeni Müşteriler havuzu — entity_type=ADAY, cari_id yok."""
    from modules.nexgen.mo_gorusme_service import can_mo_gorusme_yaz_aday

    kartlar = []
    for a in aday_listele(con, kullanici_id, yk, durum=durum, limit=limit):
        aid = int(a['id'])
        oz = _gorusme_ozet_aday(con, aid)
        kartlar.append({
            'entity_type': 'ADAY',
            'aday_id': aid,
            'cari_id': None,
            'firma_adi': a.get('firma_adi') or '—',
            'unvan': a.get('firma_adi') or '—',
            'yetkili_adi': a.get('yetkili_adi'),
            'telefon': a.get('telefon'),
            'sehir': a.get('sehir'),
            'not_metni': a.get('not_metni'),
            'durum': a.get('durum') or DURUM_ADAY,
            'olusturan_kullanici_id': a.get('olusturan_kullanici_id'),
            'olusturan_adi': a.get('olusturan_adi') or '—',
            'created_at': a.get('created_at'),
            'son_gorusme': oz.get('son_gorusme_metin'),
            'son_gorusme_tarihi': oz.get('son_gorusme_tarihi'),
            'gorusme_sayisi': oz.get('gorusme_sayisi') or 0,
            'son_sonuc': oz.get('son_sonuc'),
            'son_kisa_not': oz.get('son_kisa_not'),
            'son_fiyat_ozet': oz.get('son_fiyat_ozet'),
            'gorusme_yazabilir': can_mo_gorusme_yaz_aday(con, kullanici_id, aid, yk),
            'can_edit': can_aday_yaz(con, kullanici_id, yk) and can_aday_gor(
                con, kullanici_id, a, yk,
            ),
            'donustur_hazir': False,  # bu fazda pasif
        })
    return kartlar


def aday_kart_detay(
    con: sqlite3.Connection,
    aday_id: int,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> dict[str, Any]:
    """Aday müşteri kartı — Cari360/Sipariş/Finans yok."""
    from modules.nexgen.mo_gorusme_service import can_mo_gorusme_yaz_aday

    a = aday_getir(con, aday_id, kullanici_id, yk)
    if not a:
        raise MusteriAdayError('Aday bulunamadı.', 404)
    oz = _gorusme_ozet_aday(con, int(aday_id))
    # olusturan adı
    olusturan_adi = None
    row = con.execute(
        """
        SELECT COALESCE(NULLIF(TRIM(AdSoyad), ''), KullaniciAdi) AS ad
        FROM sistem_kullanici WHERE Id=?
        """,
        (a.get('olusturan_kullanici_id'),),
    ).fetchone()
    if row:
        olusturan_adi = row['ad'] if hasattr(row, 'keys') else row[0]

    return {
        'entity_type': 'ADAY',
        'aday_id': int(aday_id),
        'cari_id': None,
        'firma_adi': a.get('firma_adi'),
        'yetkili_adi': a.get('yetkili_adi'),
        'telefon': a.get('telefon'),
        'sehir': a.get('sehir'),
        'not_metni': a.get('not_metni'),
        'durum': a.get('durum'),
        'olusturan_kullanici_id': a.get('olusturan_kullanici_id'),
        'olusturan_adi': olusturan_adi or '—',
        'created_at': a.get('created_at'),
        'updated_at': a.get('updated_at'),
        'nexgen_cari_id': a.get('nexgen_cari_id'),
        'donusturulme_tarihi': a.get('donusturulme_tarihi'),
        'son_gorusme': oz.get('son_gorusme_metin'),
        'gorusme_sayisi': oz.get('gorusme_sayisi') or 0,
        'gorusmeler': oz.get('gorusmeler') or [],
        'gorusme_yazabilir': can_mo_gorusme_yaz_aday(con, kullanici_id, int(aday_id), yk),
        'can_edit': can_aday_yaz(con, kullanici_id, yk),
        'aksiyonlar': {
            'cari360': False,
            'siparis': False,
            'finans': False,
            'sevkiyat': False,
            'tahsilat': False,
            'gorusme': True,
            'duzenle': True,
            'iptal': a.get('durum') == DURUM_ADAY,
            'cariye_donustur': False,  # bu fazda aktif değil
        },
        'donusum_hazirligi': {
            'hedef': 'nexgen_cari',
            'kimlik': 'nexgen_musteri_aday.id',
            'unvan_eslestirme': False,
            'telefon_eslestirme': False,
            'uygulandi': False,
        },
    }


def aday_guncelle(
    con: sqlite3.Connection,
    aday_id: int,
    payload: dict,
    kullanici_id: int,
    yk: set[str] | None = None,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    mevcut = aday_getir(con, aday_id, kullanici_id, yk)
    if not mevcut:
        raise MusteriAdayError('Aday bulunamadı.', 404)
    if mevcut.get('durum') != DURUM_ADAY:
        raise MusteriAdayError('Yalnız ADAY durumundaki kayıt güncellenir.', 400)
    if not can_aday_yaz(con, kullanici_id, yk):
        raise MusteriAdayError('Aday güncelleme yetkiniz yok.', 403)
    if not can_aday_gor(con, kullanici_id, mevcut, yk):
        raise MusteriAdayError('Bu adaya erişim yetkiniz yok.', 403)

    sets: list[str] = []
    vals: list[Any] = []
    for k in GUNCELLENEBILIR:
        if k not in payload:
            continue
        v = payload.get(k)
        if k == 'firma_adi':
            v = (v or '').strip()
            if not v:
                raise MusteriAdayError('Firma adı zorunlu.', 400)
        else:
            v = (v or '').strip() or None
        sets.append(f'{k}=?')
        vals.append(v)
    if not sets:
        return mevcut
    sets.append('updated_at=?')
    vals.append(_now())
    vals.append(aday_id)
    con.execute(
        f"UPDATE {TABLO} SET {', '.join(sets)} WHERE id=?",
        vals,
    )
    if commit:
        con.commit()
    return aday_getir(con, aday_id, kullanici_id, yk)


def aday_iptal_et(
    con: sqlite3.Connection,
    aday_id: int,
    kullanici_id: int,
    yk: set[str] | None = None,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    mevcut = aday_getir(con, aday_id, kullanici_id, yk)
    if not mevcut:
        raise MusteriAdayError('Aday bulunamadı.', 404)
    if mevcut.get('durum') == DURUM_DONUSTURULDU:
        raise MusteriAdayError('Dönüştürülmüş aday iptal edilemez.', 400)
    if not can_aday_yaz(con, kullanici_id, yk):
        raise MusteriAdayError('Aday iptal yetkiniz yok.', 403)
    if not can_aday_gor(con, kullanici_id, mevcut, yk):
        raise MusteriAdayError('Bu adaya erişim yetkiniz yok.', 403)
    con.execute(
        f"UPDATE {TABLO} SET durum=?, updated_at=? WHERE id=?",
        (DURUM_IPTAL, _now(), aday_id),
    )
    if commit:
        con.commit()
    return aday_getir(con, aday_id, kullanici_id, yk)


def aday_cariye_donustur(*_args, **_kwargs):
    """Bu fazda uygulanmaz."""
    raise NotImplementedError('Cariye dönüştürme bu fazda yok.')


def aday_ve_ilk_gorusme_kaydet(
    con: sqlite3.Connection,
    aday_payload: dict,
    gorusme_payload: dict,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> dict[str, Any]:
    """Tek transaction: aday + ilk görüşme. Yarım kayıt bırakılmaz."""
    from modules.nexgen.mo_gorusme_service import (
        MoGorusmeError,
        gorusme_detay,
        gorusme_kaydet,
    )

    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if not can_aday_yaz(con, kullanici_id, yk):
        raise MusteriAdayError('Aday oluşturma yetkiniz yok.', 403)

    idem = (gorusme_payload.get('idempotency_key') or aday_payload.get('idempotency_key') or '').strip()
    if not idem:
        raise MusteriAdayError('idempotency_key zorunlu.', 400)

    # Idempotency: mevcut görüşme
    if _tablo_var(con, 'musteri_operasyon_gorusme'):
        mevcut_g = con.execute(
            'SELECT id, musteri_aday_id FROM musteri_operasyon_gorusme '
            'WHERE idempotency_key=? AND aktif=1',
            (idem,),
        ).fetchone()
        if mevcut_g:
            gid = int(mevcut_g['id'])
            detay = gorusme_detay(con, gid, kullanici_id, yk)
            aid = mevcut_g['musteri_aday_id']
            aday = aday_getir(con, int(aid), kullanici_id, yk) if aid else None
            return {
                'aday': aday,
                'kayit': detay,
                'idempotent': True,
            }

    # Idempotency: aday oluşmuş görüşme yoksa — görüşmeyi tamamla (nadir)
    aday_payload = dict(aday_payload)
    aday_payload['idempotency_key'] = idem
    gorusme_payload = dict(gorusme_payload)
    gorusme_payload['idempotency_key'] = idem

    try:
        con.execute('BEGIN IMMEDIATE')
    except sqlite3.OperationalError:
        pass  # zaten transaction içindeyse devam

    try:
        aid = aday_olustur(con, aday_payload, kullanici_id, commit=False)
        gorusme_payload.pop('cari_id', None)
        gorusme_payload['musteri_aday_id'] = aid
        gorusme_payload['cari_id'] = None
        detay = gorusme_kaydet(con, gorusme_payload, kullanici_id, yk, commit=False)
        con.commit()
        aday = aday_getir(con, aid, kullanici_id, yk)
        return {'aday': aday, 'kayit': detay, 'idempotent': False}
    except (MusteriAdayError, MoGorusmeError):
        try:
            con.rollback()
        except Exception:
            pass
        raise
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass
        raise
