# -*- coding: utf-8 -*-
"""Musteri Operasyonu Ajanda V1 servisi."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from modules.nexgen.cari_sorumlu_service import can_mo_view_cari, load_kullanici_yetkileri
from modules.nexgen.mo_ajanda_config import (
    DURUM_GERCEKLESTI,
    DURUM_IPTAL,
    DURUM_PLANLANDI,
    DURUMLAR,
    TABLO,
)
from modules.nexgen.mo_gorusme_config import GORUSME_TIPLERI_ALL
from modules.nexgen.mo_gorusme_service import can_mo_gorusme_yaz


class MoAjandaError(Exception):
    def __init__(self, mesaj: str, kod: int = 400):
        self.mesaj = mesaj
        self.kod = kod
        super().__init__(mesaj)


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _today() -> str:
    return date.today().isoformat()


def _tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _parse_plan_tarihi(raw: str) -> str:
    s = (raw or '').strip()
    if not s:
        raise MoAjandaError('plan_tarihi zorunlu.', 400)
    if len(s) == 10:
        s = s + ' 09:00:00'
    elif len(s) == 16 and 'T' in s:
        s = s.replace('T', ' ') + ':00'
    elif len(s) == 19:
        pass
    else:
        raise MoAjandaError('plan_tarihi gecersiz format.', 400)
    try:
        datetime.strptime(s[:19], '%Y-%m-%d %H:%M:%S')
    except ValueError:
        raise MoAjandaError('plan_tarihi gecersiz.', 400)
    return s[:19]


def _gorunum_durumu(durum: str, plan_tarihi: str, gorusme_id=None) -> str:
    d = (durum or '').strip().upper()
    if d == DURUM_IPTAL:
        return DURUM_IPTAL
    if d == DURUM_GERCEKLESTI:
        return DURUM_GERCEKLESTI
    if d == DURUM_PLANLANDI:
        gid = gorusme_id not in (None, '', 0, '0')
        if plan_tarihi and not gid:
            plan_gun = plan_tarihi[:10]
            if plan_gun < _today():
                return 'ZORUNLU_SONUC_BEKLIYOR'
            if plan_tarihi <= _now():
                return 'SONUC_BEKLIYOR'
        return DURUM_PLANLANDI
    return d


def _durum_etiket(durum_gorunum: str) -> str:
    return {
        DURUM_PLANLANDI: 'Planlandı',
        'SONUC_BEKLIYOR': 'Sonuç Bekliyor',
        'ZORUNLU_SONUC_BEKLIYOR': 'Zorunlu Sonuç Bekliyor',
        DURUM_GERCEKLESTI: 'Gerçekleşti',
        DURUM_IPTAL: 'İptal',
    }.get(durum_gorunum, durum_gorunum)


def _gun_farki(eski_tarih: str, bugun: str | None = None) -> int:
    try:
        b = date.fromisoformat((bugun or _today())[:10])
        e = date.fromisoformat((eski_tarih or '')[:10])
        return max(0, (b - e).days)
    except ValueError:
        return 0


def _cari_map(con: sqlite3.Connection, cari_ids: list[int]) -> dict[int, dict]:
    if not cari_ids:
        return {}
    ph = ','.join('?' * len(cari_ids))
    rows = con.execute(
        f'SELECT id, unvan, cari_kod FROM nexgen_cari WHERE id IN ({ph})',
        cari_ids,
    ).fetchall()
    return {
        int(r['id']): {'unvan': r['unvan'], 'cari_kod': r['cari_kod']}
        for r in rows
    }


def _aday_map(con: sqlite3.Connection, aday_ids: list[int]) -> dict[int, dict]:
    if not aday_ids:
        return {}
    ph = ','.join('?' * len(aday_ids))
    rows = con.execute(
        f'SELECT id, firma_adi, yetkili_adi, telefon, sehir FROM nexgen_musteri_aday WHERE id IN ({ph})',
        aday_ids,
    ).fetchall()
    return {
        int(r['id']): {
            'firma_adi': r['firma_adi'] or '',
            'yetkili_adi': r['yetkili_adi'] or '',
            'telefon': r['telefon'] or '',
            'sehir': r['sehir'] or '',
        }
        for r in rows
    }


def _kolon_var(con: sqlite3.Connection, table: str, col: str) -> bool:
    return any(
        c[1] == col for c in con.execute(f'PRAGMA table_info({table})').fetchall()
    )


def _musteri_gorunum(
    d: dict[str, Any],
    cari_map: dict[int, dict] | None = None,
    aday_map: dict[int, dict] | None = None,
) -> str:
    snap = (d.get('firma_adi_gorunum') or '').strip()
    if snap:
        return snap
    cid = d.get('cari_id')
    if cid:
        info = (cari_map or {}).get(int(cid)) or {}
        return info.get('unvan') or d.get('cari_unvan') or '-'
    aid = d.get('musteri_aday_id')
    if aid:
        info = (aday_map or {}).get(int(aid)) or {}
        return info.get('firma_adi') or '-'
    return d.get('cari_unvan') or '-'


def _row_dict(
    r,
    cari_map: dict[int, dict] | None = None,
    aday_map: dict[int, dict] | None = None,
) -> dict[str, Any]:
    d = dict(r)
    cid = d.get('cari_id')
    info = (cari_map or {}).get(int(cid)) if cid else {}
    d['musteri'] = _musteri_gorunum(d, cari_map, aday_map)
    d['cari_kod'] = info.get('cari_kod') or '' if cid else ''
    d['saat'] = (d.get('plan_tarihi') or '')[11:16] or '-'
    d['tarih'] = (d.get('plan_tarihi') or '')[:10]
    # Snapshot öncelikli; boşsa bağlı aday tablosundan fallback (tarihsel snapshot ezilmez)
    _aid = d.get('musteri_aday_id')
    _aday_info = (aday_map or {}).get(int(_aid)) if _aid else {}
    d['plan_yetkili_metin'] = (d.get('plan_yetkili_metin') or '').strip() or _aday_info.get('yetkili_adi', '')
    d['plan_telefon']       = (d.get('plan_telefon')       or '').strip() or _aday_info.get('telefon', '')
    d['plan_sehir']         = (d.get('plan_sehir')         or '').strip() or _aday_info.get('sehir', '')
    d['plan_notu'] = (d.get('plan_notu') or '').strip()
    d['entity_type'] = 'ADAY' if d.get('musteri_aday_id') else 'CARI'
    d['musteri_tip_etiket'] = 'Yeni Müşteri' if d.get('musteri_aday_id') else 'Mevcut Müşteri'
    d['olusturan_adi'] = (d.get('olusturan_adi') or '').strip()
    dg = _gorunum_durumu(d.get('durum'), d.get('plan_tarihi'), d.get('gorusme_id'))
    d['durum_gorunum'] = dg
    d['durum_etiket'] = _durum_etiket(dg)
    if dg == 'ZORUNLU_SONUC_BEKLIYOR':
        d['bekleyen_gun'] = _gun_farki(d.get('tarih') or '')
    return d


_TICARI_OZET_KOLONLAR = (
    'fiyat_verildi', 'verilen_fiyat', 'fiyat_para_birimi', 'fiyat_birimi',
    'konusulan_tonaj', 'odeme_tipi', 'vade_gun', 'cek_vade_gun', 'cek_adedi',
    'ticari_not', 'cek_notu',
)


def gorusme_ozet_map(con: sqlite3.Connection, gorusme_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Ajanda GERCEKLESTI kartları için görüşme özeti (+ ticari snapshot)."""
    import json

    from modules.nexgen.mo_gorusme_config import TABLO as G_TABLO
    from modules.nexgen.mo_gorusme_service import _kolon_var, fiyat_ozet_metin

    ids = sorted({int(i) for i in gorusme_ids if i not in (None, '', 0, '0')})
    if not ids or not _tablo_var(con, G_TABLO):
        return {}
    has_ticari = _kolon_var(con, G_TABLO, 'fiyat_verildi')
    extra_cols: list[str] = []
    for col in ('yetkili_metin', 'sonuc_etiketler', 'konu', 'detay_not'):
        if _kolon_var(con, G_TABLO, col):
            extra_cols.append(col)
    ticari_sql = ''
    if has_ticari:
        ticari_sql = ', ' + ', '.join(_TICARI_OZET_KOLONLAR)
    extra_sql = (', ' + ', '.join(f'g.{c}' for c in extra_cols)) if extra_cols else ''
    ph = ','.join('?' * len(ids))
    rows = con.execute(
        f"""
        SELECT g.id, g.gorusme_tarihi, g.gorusme_tipi, g.sonuc_tipi, g.kisa_not,
               g.sonraki_aksiyon, g.sonraki_takip_tarihi,
               sk.AdSoyad AS olusturan_adi{ticari_sql}{extra_sql}
        FROM {G_TABLO} g
        LEFT JOIN sistem_kullanici sk ON sk.Id = g.olusturan_kullanici_id
        WHERE g.id IN ({ph}) AND COALESCE(g.aktif, 1)=1
        """,
        ids,
    ).fetchall()
    out: dict[int, dict[str, Any]] = {}
    for r in rows:
        d: dict[str, Any] = {
            'gorusme_id': int(r['id']),
            'gorusme_tarihi': r['gorusme_tarihi'] or '',
            'gorusme_tipi': r['gorusme_tipi'] or '',
            'sonuc_tipi': r['sonuc_tipi'] or '',
            'kisa_not': r['kisa_not'] or '',
            'sonraki_aksiyon': r['sonraki_aksiyon'] or '',
            'sonraki_takip_tarihi': r['sonraki_takip_tarihi'] or '',
            'olusturan_adi': (r['olusturan_adi'] if 'olusturan_adi' in r.keys() else '') or '',
        }
        if 'yetkili_metin' in r.keys():
            d['yetkili_metin'] = r['yetkili_metin'] or ''
        if 'konu' in r.keys():
            d['konu'] = r['konu'] or ''
        if 'detay_not' in r.keys():
            d['detay_not'] = r['detay_not'] or ''
        if 'sonuc_etiketler' in r.keys():
            raw = r['sonuc_etiketler'] or '[]'
            try:
                tags = json.loads(raw) if raw else []
            except (TypeError, ValueError, json.JSONDecodeError):
                tags = []
            if not isinstance(tags, list):
                tags = []
            d['sonuc_etiketler'] = tags
        if has_ticari:
            for col in _TICARI_OZET_KOLONLAR:
                d[col] = r[col] if col in r.keys() else None
            d['fiyat_ozet'] = fiyat_ozet_metin(d)
        else:
            d['fiyat_verildi'] = 0
            d['fiyat_ozet'] = None
        out[int(r['id'])] = d
    return out


def ajanda_enrich_gorusme_ozet(
    con: sqlite3.Connection,
    planlar: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gids = [
        int(p['gorusme_id'])
        for p in planlar
        if p.get('gorusme_id') not in (None, '', 0, '0')
    ]
    gm = gorusme_ozet_map(con, gids)
    for p in planlar:
        gid = p.get('gorusme_id')
        if gid not in (None, '', 0, '0'):
            p['gorusme_ozet'] = gm.get(int(gid))
        else:
            p['gorusme_ozet'] = None
    return planlar


def _hafta_araligi(ref: date | None = None) -> tuple[str, str]:
    d = ref or date.today()
    bas = d - timedelta(days=d.weekday())
    bit = bas + timedelta(days=6)
    return bas.isoformat(), bit.isoformat()


def _scope_kontrol(
    con: sqlite3.Connection,
    kullanici_id: int,
    cari_id: int | None,
    yk: set[str] | None = None,
    *,
    musteri_aday_id: int | None = None,
) -> None:
    if musteri_aday_id:
        from modules.nexgen.mo_gorusme_service import can_mo_gorusme_yaz_aday
        if not can_mo_gorusme_yaz_aday(con, kullanici_id, int(musteri_aday_id), yk):
            raise MoAjandaError('Bu aday icin yetkiniz yok.', 403)
        return
    if not cari_id:
        raise MoAjandaError('cari_id veya musteri_aday_id zorunlu.', 400)
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if not can_mo_view_cari(con, kullanici_id, int(cari_id), yk):
        raise MoAjandaError('Bu cari icin yetkiniz yok.', 403)
    if not can_mo_gorusme_yaz(con, kullanici_id, int(cari_id), yk):
        raise MoAjandaError('Bu cari icin plan olusturma yetkiniz yok.', 403)


def ajanda_olustur(
    con: sqlite3.Connection,
    payload: dict,
    kullanici_id: int,
    yk: set[str] | None = None,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    if not _tablo_var(con, TABLO):
        raise MoAjandaError('Ajanda tablosu bulunamadi.', 500)

    def _opt_int(v):
        if v in (None, '', 0, '0'):
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    cari_id = _opt_int(payload.get('cari_id'))
    musteri_aday_id = _opt_int(payload.get('musteri_aday_id'))
    if cari_id and musteri_aday_id:
        raise MoAjandaError('cari_id ve musteri_aday_id birlikte gonderilemez.', 400)
    if not cari_id and not musteri_aday_id:
        raise MoAjandaError('cari_id veya musteri_aday_id zorunlu.', 400)
    if cari_id == 0:
        raise MoAjandaError('Gecersiz cari_id.', 400)

    idem = (payload.get('idempotency_key') or '').strip()
    if not idem:
        raise MoAjandaError('idempotency_key zorunlu.', 400)

    gorusme_tipi = (payload.get('gorusme_tipi') or '').strip()
    if gorusme_tipi not in GORUSME_TIPLERI_ALL:
        raise MoAjandaError('gorusme_tipi gecersiz.', 400)

    plan_tarihi = _parse_plan_tarihi(payload.get('plan_tarihi') or '')
    plan_notu = (payload.get('plan_notu') or '').strip() or None

    firma_adi_gorunum = (payload.get('firma_adi_gorunum') or '').strip() or None
    if cari_id and not firma_adi_gorunum:
        u = con.execute(
            'SELECT unvan FROM nexgen_cari WHERE id=?', (cari_id,),
        ).fetchone()
        firma_adi_gorunum = (u['unvan'] if u else None) or None
    elif musteri_aday_id and not firma_adi_gorunum:
        u = con.execute(
            'SELECT firma_adi FROM nexgen_musteri_aday WHERE id=?', (musteri_aday_id,),
        ).fetchone()
        firma_adi_gorunum = (u['firma_adi'] if u else None) or None

    _scope_kontrol(
        con, kullanici_id, cari_id, yk, musteri_aday_id=musteri_aday_id,
    )

    mevcut = con.execute(
        f'SELECT * FROM {TABLO} WHERE idempotency_key=? AND aktif=1',
        (idem,),
    ).fetchone()
    if mevcut:
        cm = _cari_map(con, [int(mevcut['cari_id'])] if mevcut['cari_id'] else [])
        am = _aday_map(con, [int(mevcut['musteri_aday_id'])] if (
            'musteri_aday_id' in mevcut.keys() and mevcut['musteri_aday_id']
        ) else [])
        return {
            'ok': True,
            'kayit': _row_dict(mevcut, cm, am),
            'idempotent': True,
            'mesaj': 'Plan zaten kayitli.',
        }

    has_aday_cols = _kolon_var(con, TABLO, 'musteri_aday_id')
    has_plan_snap = _kolon_var(con, TABLO, 'plan_yetkili_metin')
    plan_yetkili = (payload.get('plan_yetkili_metin') or '').strip() or None
    plan_telefon = (payload.get('plan_telefon') or '').strip() or None
    plan_sehir = (payload.get('plan_sehir') or '').strip() or None

    try:
        con.execute('BEGIN IMMEDIATE')
    except sqlite3.OperationalError:
        pass

    try:
        if has_aday_cols:
            if has_plan_snap:
                cur = con.execute(
                    f"""
                    INSERT INTO {TABLO} (
                        cari_id, musteri_aday_id, firma_adi_gorunum,
                        plan_yetkili_metin, plan_telefon, plan_sehir,
                        kullanici_id, plan_tarihi, gorusme_tipi, plan_notu,
                        durum, gorusme_id, idempotency_key, aktif,
                        olusturan_kullanici_id, olusturma_tarihi
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 1, ?, ?)
                    """,
                    (
                        cari_id, musteri_aday_id, firma_adi_gorunum,
                        plan_yetkili, plan_telefon, plan_sehir,
                        kullanici_id, plan_tarihi, gorusme_tipi, plan_notu,
                        DURUM_PLANLANDI, idem, kullanici_id, _now(),
                    ),
                )
            else:
                cur = con.execute(
                    f"""
                    INSERT INTO {TABLO} (
                        cari_id, musteri_aday_id, firma_adi_gorunum,
                        kullanici_id, plan_tarihi, gorusme_tipi, plan_notu,
                        durum, gorusme_id, idempotency_key, aktif,
                        olusturan_kullanici_id, olusturma_tarihi
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 1, ?, ?)
                    """,
                    (
                        cari_id, musteri_aday_id, firma_adi_gorunum,
                        kullanici_id, plan_tarihi, gorusme_tipi, plan_notu,
                        DURUM_PLANLANDI, idem, kullanici_id, _now(),
                    ),
                )
        else:
            if musteri_aday_id:
                raise MoAjandaError('Aday ajanda icin migration 156 gerekli.', 503)
            cur = con.execute(
                f"""
                INSERT INTO {TABLO} (
                    cari_id, kullanici_id, plan_tarihi, gorusme_tipi, plan_notu,
                    durum, gorusme_id, idempotency_key, aktif,
                    olusturan_kullanici_id, olusturma_tarihi
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 1, ?, ?)
                """,
                (
                    cari_id, kullanici_id, plan_tarihi, gorusme_tipi, plan_notu,
                    DURUM_PLANLANDI, idem, kullanici_id, _now(),
                ),
            )
        aid = int(cur.lastrowid)
        row = con.execute(f'SELECT * FROM {TABLO} WHERE id=?', (aid,)).fetchone()
        if commit:
            con.commit()
        cm = _cari_map(con, [cari_id] if cari_id else [])
        am = _aday_map(con, [musteri_aday_id] if musteri_aday_id else [])
        return {
            'ok': True,
            'kayit': _row_dict(row, cm, am),
            'idempotent': False,
            'mesaj': 'Plan olusturuldu.',
        }
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass
        raise


def ajanda_gorunen_kullanici(
    oturum_kullanici_id: int,
    yk: set[str] | None,
    hedef_kullanici_id: int | None = None,
) -> tuple[int, bool]:
    """Oturum + hedef → görünen pazarlamacı uid ve admin cross-view bayrağı."""
    from modules.nexgen.cari360_yetki import can_cari360_view_all

    oturum_uid = int(oturum_kullanici_id)
    if hedef_kullanici_id and int(hedef_kullanici_id) != oturum_uid:
        if not can_cari360_view_all(yk or set()):
            raise MoAjandaError('Başka pazarlamacının ajandası için yetki yok.', 403)
        return int(hedef_kullanici_id), True
    return oturum_uid, False


def ajanda_listele(
    con: sqlite3.Connection,
    kullanici_id: int,
    yk: set[str] | None = None,
    *,
    filtre: str = 'bugun',
    hedef_kullanici_id: int | None = None,
) -> list[dict[str, Any]]:
    if not _tablo_var(con, TABLO):
        return []

    gorunen_uid, baska_pazarlamaci = ajanda_gorunen_kullanici(
        kullanici_id, yk, hedef_kullanici_id,
    )

    f = (filtre or 'bugun').strip().lower()
    today = _today()
    hafta_bas, hafta_bit = _hafta_araligi()

    sql = f"""
        SELECT a.*, c.unvan AS cari_unvan,
               ma.firma_adi AS aday_firma_adi,
               sk.AdSoyad AS olusturan_adi
        FROM {TABLO} a
        LEFT JOIN nexgen_cari c ON c.id = a.cari_id
        LEFT JOIN nexgen_musteri_aday ma ON ma.id = a.musteri_aday_id
        LEFT JOIN sistem_kullanici sk ON sk.Id = a.olusturan_kullanici_id
        WHERE a.aktif=1 AND a.kullanici_id=?
    """
    params: list[Any] = [gorunen_uid]

    if f == 'bugun':
        sql += " AND substr(a.plan_tarihi, 1, 10) = ?"
        params.append(today)
    elif f == 'hafta':
        sql += " AND substr(a.plan_tarihi, 1, 10) BETWEEN ? AND ?"
        params.extend([hafta_bas, hafta_bit])
    elif f == 'planli':
        sql += " AND a.durum = ?"
        params.append(DURUM_PLANLANDI)

    sql += ' ORDER BY a.plan_tarihi ASC, a.id ASC'

    rows = con.execute(sql, params).fetchall()
    cari_ids = sorted({int(r['cari_id']) for r in rows if r['cari_id']})
    aday_ids = sorted({
        int(r['musteri_aday_id']) for r in rows
        if 'musteri_aday_id' in r.keys() and r['musteri_aday_id']
    })
    cm = _cari_map(con, cari_ids)
    am = _aday_map(con, aday_ids)

    out: list[dict[str, Any]] = []
    for r in rows:
        item = _row_dict(r, cm, am)
        if baska_pazarlamaci:
            out.append(item)
        elif r['cari_id']:
            if not can_mo_view_cari(con, kullanici_id, int(r['cari_id']), yk):
                continue
            out.append(item)
        elif 'musteri_aday_id' in r.keys() and r['musteri_aday_id']:
            from modules.nexgen.musteri_aday_service import can_aday_gor
            if not can_aday_gor(con, kullanici_id, int(r['musteri_aday_id']), yk):
                continue
            out.append(item)
        else:
            continue
    return ajanda_enrich_gorusme_ozet(con, out)


def ajanda_zorunlu_sonuc_listele(
    con: sqlite3.Connection,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> list[dict[str, Any]]:
    today = _today()
    planli = ajanda_listele(con, kullanici_id, yk, filtre='planli')
    out: list[dict[str, Any]] = []
    for x in planli:
        if x.get('gorusme_id'):
            continue
        if (x.get('durum') or '').upper() != DURUM_PLANLANDI:
            continue
        plan_gun = (x.get('plan_tarihi') or x.get('tarih') or '')[:10]
        if plan_gun and plan_gun < today:
            item = dict(x)
            item['bekleyen_gun'] = _gun_farki(plan_gun, today)
            out.append(item)
    out.sort(key=lambda x: (x.get('plan_tarihi') or '', x.get('id') or 0))
    return out


def ajanda_ozet_bugun(
    con: sqlite3.Connection,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> dict[str, Any]:
    now = _now()
    today = _today()
    planli = ajanda_listele(con, kullanici_id, yk, filtre='planli')
    sonuc_bekleyen = [
        x for x in planli
        if not x.get('gorusme_id')
        and (x.get('plan_tarihi') or '') <= now
        and (x.get('plan_tarihi') or '')[:10] >= today
    ]
    if sonuc_bekleyen:
        sonuc_bekleyen.sort(key=lambda x: (x.get('plan_tarihi') or '', x.get('id') or 0))
        return {
            'mod': 'sonuc_bekliyor',
            'kayitlar': sonuc_bekleyen[:12],
            'bos_mesaj': None,
        }

    bugun = ajanda_listele(con, kullanici_id, yk, filtre='bugun')
    planli_bugun = [
        x for x in bugun
        if x.get('durum') == DURUM_PLANLANDI
        and (x.get('plan_tarihi') or '') > now
    ]
    if planli_bugun:
        return {
            'mod': 'bugun',
            'kayitlar': planli_bugun,
            'bos_mesaj': None,
        }

    hafta = ajanda_listele(con, kullanici_id, yk, filtre='hafta')
    planli_hafta = [
        x for x in hafta
        if x.get('durum') == DURUM_PLANLANDI
        and (x.get('plan_tarihi') or '') > now
    ]
    if planli_hafta:
        return {
            'mod': 'hafta',
            'kayitlar': planli_hafta[:8],
            'bos_mesaj': None,
        }

    return {
        'mod': 'bos',
        'kayitlar': [],
        'bos_mesaj': (
            'Bu hafta planlanmış görüşmeniz yok. '
            'Bu hafta görüşeceğiniz firmaları planlayın.'
        ),
    }


def ajanda_getir(
    con: sqlite3.Connection,
    ajanda_id: int,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> dict[str, Any]:
    if not _tablo_var(con, TABLO):
        raise MoAjandaError('Ajanda kaydi bulunamadi.', 404)
    row = con.execute(
        f'SELECT * FROM {TABLO} WHERE id=? AND aktif=1',
        (ajanda_id,),
    ).fetchone()
    if not row:
        raise MoAjandaError('Ajanda kaydi bulunamadi.', 404)
    if int(row['kullanici_id']) != int(kullanici_id):
        raise MoAjandaError('Bu plan size ait degil.', 403)
    aid = row['musteri_aday_id'] if 'musteri_aday_id' in row.keys() else None
    _scope_kontrol(
        con, kullanici_id,
        int(row['cari_id']) if row['cari_id'] else None,
        yk,
        musteri_aday_id=int(aid) if aid else None,
    )
    cm = _cari_map(con, [int(row['cari_id'])] if row['cari_id'] else [])
    am = _aday_map(con, [int(aid)] if aid else [])
    return _row_dict(row, cm, am)


def ajanda_iptal(
    con: sqlite3.Connection,
    ajanda_id: int,
    kullanici_id: int,
    yk: set[str] | None = None,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    kayit = ajanda_getir(con, ajanda_id, kullanici_id, yk)
    if kayit.get('durum') != DURUM_PLANLANDI:
        raise MoAjandaError('Yalniz planlanmis kayitlar iptal edilebilir.', 400)

    try:
        con.execute('BEGIN IMMEDIATE')
    except sqlite3.OperationalError:
        pass

    try:
        con.execute(
            f"""
            UPDATE {TABLO}
            SET durum=?, guncelleme_tarihi=?
            WHERE id=? AND kullanici_id=? AND aktif=1 AND durum=?
            """,
            (DURUM_IPTAL, _now(), ajanda_id, kullanici_id, DURUM_PLANLANDI),
        )
        if commit:
            con.commit()
        kayit['durum'] = DURUM_IPTAL
        kayit['durum_gorunum'] = DURUM_IPTAL
        kayit['durum_etiket'] = _durum_etiket(DURUM_IPTAL)
        return {'ok': True, 'kayit': kayit, 'mesaj': 'Plan iptal edildi.'}
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass
        raise


def ajanda_tamamla(
    con: sqlite3.Connection,
    ajanda_id: int,
    gorusme_id: int,
    kullanici_id: int,
    cari_id: int | None = None,
    yk: set[str] | None = None,
    *,
    musteri_aday_id: int | None = None,
    commit: bool = True,
) -> None:
    if not _tablo_var(con, TABLO):
        raise MoAjandaError('Ajanda tablosu bulunamadi.', 500)

    row = con.execute(
        f"""
        SELECT * FROM {TABLO}
        WHERE id=? AND aktif=1 AND kullanici_id=? AND durum=?
        """,
        (ajanda_id, kullanici_id, DURUM_PLANLANDI),
    ).fetchone()
    if not row:
        raise MoAjandaError('Ajanda kaydi bulunamadi veya tamamlanamaz.', 404)
    row_aid = row['musteri_aday_id'] if 'musteri_aday_id' in row.keys() else None
    if cari_id and row['cari_id'] and int(row['cari_id']) != int(cari_id):
        raise MoAjandaError('Ajanda cari eslesmiyor.', 400)
    if musteri_aday_id and row_aid and int(row_aid) != int(musteri_aday_id):
        raise MoAjandaError('Ajanda aday eslesmiyor.', 400)
    if row['gorusme_id']:
        raise MoAjandaError('Ajanda kaydi zaten tamamlanmis.', 409)

    _scope_kontrol(
        con, kullanici_id,
        int(row['cari_id']) if row['cari_id'] else None,
        yk,
        musteri_aday_id=int(row_aid) if row_aid else None,
    )

    con.execute(
        f"""
        UPDATE {TABLO}
        SET durum=?, gorusme_id=?, guncelleme_tarihi=?
        WHERE id=? AND kullanici_id=? AND durum=? AND gorusme_id IS NULL
        """,
        (DURUM_GERCEKLESTI, int(gorusme_id), _now(), ajanda_id, kullanici_id, DURUM_PLANLANDI),
    )


def gercek_gorusmeyi_ajandaya_bagla(
    con: sqlite3.Connection,
    gorusme_id: int,
    kullanici_id: int,
    gorusme_tarihi: str,
    gorusme_tipi: str = '',
    *,
    cari_id: int | None = None,
    musteri_aday_id: int | None = None,
    firma_adi_gorunum: str | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    """Gerçek görüşme kaydını Ajanda ile senkronize eder.

    A) Aynı kullanici+cari+gün için PLANLANDI kayıt varsa: o kaydı tamamlar.
    B) Yoksa: yeni GERCEKLESTI geçmiş kaydı oluşturur.
    C) Aynı gorusme_id zaten bağlıysa: idempotent dönüş.
    D) IPTAL kayıt eşleşmez; ad-hoc satır oluşturulur.
    """
    if not _tablo_var(con, TABLO):
        return {'durum': 'skip', 'sebep': 'tablo_yok'}

    # Idempotency: bu görüşme zaten bir ajanda kaydına bağlı mı?
    existing = con.execute(
        f'SELECT id, durum FROM {TABLO} WHERE gorusme_id=? AND aktif=1',
        (int(gorusme_id),),
    ).fetchone()
    if existing:
        return {'durum': 'idempotent', 'ajanda_id': int(existing['id'])}

    if not cari_id and not musteri_aday_id:
        return {'durum': 'skip', 'sebep': 'kimlik_eksik'}

    gun = (gorusme_tarihi or '')[:10]
    if not gun:
        return {'durum': 'skip', 'sebep': 'tarih_eksik'}

    has_aday_cols = _kolon_var(con, TABLO, 'musteri_aday_id')

    if cari_id:
        plan_row = con.execute(
            f"""
            SELECT id, gorusme_id FROM {TABLO}
            WHERE kullanici_id=? AND cari_id=? AND aktif=1 AND durum=?
              AND DATE(plan_tarihi)=?
            ORDER BY plan_tarihi ASC
            LIMIT 1
            """,
            (int(kullanici_id), int(cari_id), DURUM_PLANLANDI, gun),
        ).fetchone()
    else:
        plan_row = con.execute(
            f"""
            SELECT id, gorusme_id FROM {TABLO}
            WHERE kullanici_id=? AND musteri_aday_id=? AND aktif=1 AND durum=?
              AND DATE(plan_tarihi)=?
            ORDER BY plan_tarihi ASC
            LIMIT 1
            """,
            (int(kullanici_id), int(musteri_aday_id), DURUM_PLANLANDI, gun),
        ).fetchone() if has_aday_cols else None

    if plan_row:
        # Mevcut plan tamamla
        con.execute(
            f"""
            UPDATE {TABLO}
            SET durum=?, gorusme_id=?, guncelleme_tarihi=?
            WHERE id=? AND kullanici_id=? AND durum=? AND gorusme_id IS NULL
            """,
            (DURUM_GERCEKLESTI, int(gorusme_id), _now(),
             int(plan_row['id']), int(kullanici_id), DURUM_PLANLANDI),
        )
        if commit:
            con.commit()
        return {'durum': 'plan_tamamlandi', 'ajanda_id': int(plan_row['id'])}

    # B) Plan yok — ad-hoc GERCEKLESTI kaydı
    idem = f'ADHOC-GOR-{int(gorusme_id)}'
    mevcut_adhoc = con.execute(
        f'SELECT id FROM {TABLO} WHERE idempotency_key=? AND aktif=1',
        (idem,),
    ).fetchone()
    if mevcut_adhoc:
        return {'durum': 'idempotent', 'ajanda_id': int(mevcut_adhoc['id'])}

    tip = (gorusme_tipi or '').strip()
    if not tip or tip not in GORUSME_TIPLERI_ALL:
        tip = GORUSME_TIPLERI_ALL[0]

    plan_tarihi = (gorusme_tarihi or _now())[:19]
    if has_aday_cols:
        con.execute(
            f"""
            INSERT INTO {TABLO} (
                cari_id, musteri_aday_id, firma_adi_gorunum,
                kullanici_id, plan_tarihi, gorusme_tipi, plan_notu,
                durum, gorusme_id, idempotency_key, aktif,
                olusturan_kullanici_id, olusturma_tarihi
            ) VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)
            """,
            (
                cari_id, musteri_aday_id, firma_adi_gorunum,
                int(kullanici_id), plan_tarihi,
                tip, None,
                DURUM_GERCEKLESTI, int(gorusme_id),
                idem, int(kullanici_id), _now(),
            ),
        )
    else:
        if not cari_id:
            return {'durum': 'skip', 'sebep': 'aday_migration_eksik'}
        con.execute(
            f"""
            INSERT INTO {TABLO} (
                cari_id, kullanici_id, plan_tarihi, gorusme_tipi, plan_notu,
                durum, gorusme_id, idempotency_key, aktif,
                olusturan_kullanici_id, olusturma_tarihi
            ) VALUES (?,?,?,?,?,?,?,?,1,?,?)
            """,
            (
                int(cari_id), int(kullanici_id), plan_tarihi,
                tip, None,
                DURUM_GERCEKLESTI, int(gorusme_id),
                idem, int(kullanici_id), _now(),
            ),
        )
    new_id = con.execute('SELECT last_insert_rowid()').fetchone()[0]
    if commit:
        con.commit()
    return {'durum': 'adhoc_olusturuldu', 'ajanda_id': int(new_id)}


# ---------------------------------------------------------------------------
# Cari360 — Planlı Görüşmeler read-only helper
# ---------------------------------------------------------------------------

def _c360_planli_durum_gorunum(dg: str) -> str:
    """Ajanda durum_gorunum → Cari360 kullanıcı etiketi."""
    if dg == 'ZORUNLU_SONUC_BEKLIYOR':
        return 'GECİKTİ'
    if dg == 'SONUC_BEKLIYOR':
        return 'BUGÜN'
    return 'PLANLANDI'



def list_planli_by_cari(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Cari360 Planlı Görüşmeler bölümü için read-only liste.

    Yalnız:
    - cari_id eşleşen
    - aktif=1
    - durum=PLANLANDI
    - gorusme_id IS NULL
    Sıralama: plan_tarihi ASC, id ASC (en yakın üstte).
    """
    if not _tablo_var(con, TABLO):
        return []
    if not can_mo_view_cari(con, kullanici_id, int(cari_id), yk):
        return []

    has_aday_col = _kolon_var(con, TABLO, 'musteri_aday_id')
    has_snap_col = _kolon_var(con, TABLO, 'plan_yetkili_metin')

    extra_sel = ''
    if has_aday_col:
        extra_sel += ', a.musteri_aday_id'
    if has_snap_col:
        extra_sel += ', a.plan_yetkili_metin, a.plan_telefon, a.plan_sehir'

    rows = con.execute(
        f"""
        SELECT a.id, a.cari_id, a.plan_tarihi, a.kullanici_id,
               a.gorusme_tipi, a.plan_notu, a.durum, a.gorusme_id{extra_sel},
               sk.AdSoyad AS pazarlamaci_adi,
               c.unvan AS cari_unvan
        FROM {TABLO} a
        LEFT JOIN sistem_kullanici sk ON sk.Id = a.kullanici_id
        LEFT JOIN nexgen_cari c ON c.id = a.cari_id
        WHERE a.cari_id = ? AND a.aktif = 1
          AND a.durum = ? AND (a.gorusme_id IS NULL OR a.gorusme_id = 0)
        ORDER BY a.plan_tarihi ASC, a.id ASC
        """,
        (int(cari_id), DURUM_PLANLANDI),
    ).fetchall()

    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        dg = _gorunum_durumu(d.get('durum'), d.get('plan_tarihi'), d.get('gorusme_id'))
        row_out: dict[str, Any] = {
            'id': d['id'],
            'cari_id': d['cari_id'],
            'plan_tarihi': d['plan_tarihi'],
            'pazarlamaci_id': d['kullanici_id'],
            'pazarlamaci': (d.get('pazarlamaci_adi') or '').strip() or str(d['kullanici_id']),
            'yetkili': (d.get('plan_yetkili_metin') or '').strip(),
            'gorusme_turu': d.get('gorusme_tipi') or '',
            'plan_notu': (d.get('plan_notu') or '').strip(),
            'durum': d.get('durum') or DURUM_PLANLANDI,
            'durum_gorunum': _c360_planli_durum_gorunum(dg),
            'mo_gorusme_id': None,
            'sonuclandi': False,
        }
        row_out['ajanda_url'] = (
            '/nexgen/musteri-pazarlama/ajanda'
            + '?hedef_kullanici_id=' + str(d['kullanici_id'])
        )
        out.append(row_out)
    return out
