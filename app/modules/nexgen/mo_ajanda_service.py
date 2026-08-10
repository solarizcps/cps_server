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


def _row_dict(r, cari_map: dict[int, dict] | None = None) -> dict[str, Any]:
    d = dict(r)
    cid = d.get('cari_id')
    info = (cari_map or {}).get(int(cid)) if cid else {}
    d['musteri'] = info.get('unvan') or d.get('cari_unvan') or '-'
    d['cari_kod'] = info.get('cari_kod') or ''
    d['saat'] = (d.get('plan_tarihi') or '')[11:16] or '-'
    d['tarih'] = (d.get('plan_tarihi') or '')[:10]
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
    from modules.nexgen.mo_gorusme_config import TABLO as G_TABLO
    from modules.nexgen.mo_gorusme_service import _kolon_var, fiyat_ozet_metin

    ids = sorted({int(i) for i in gorusme_ids if i not in (None, '', 0, '0')})
    if not ids or not _tablo_var(con, G_TABLO):
        return {}
    has_ticari = _kolon_var(con, G_TABLO, 'fiyat_verildi')
    ticari_sql = ''
    if has_ticari:
        ticari_sql = ', ' + ', '.join(_TICARI_OZET_KOLONLAR)
    ph = ','.join('?' * len(ids))
    rows = con.execute(
        f"""
        SELECT id, gorusme_tarihi, gorusme_tipi, sonuc_tipi, kisa_not,
               sonraki_aksiyon, sonraki_takip_tarihi{ticari_sql}
        FROM {G_TABLO}
        WHERE id IN ({ph}) AND COALESCE(aktif, 1)=1
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
        }
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
    cari_id: int,
    yk: set[str] | None = None,
) -> None:
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if not can_mo_view_cari(con, kullanici_id, cari_id, yk):
        raise MoAjandaError('Bu cari icin yetkiniz yok.', 403)
    if not can_mo_gorusme_yaz(con, kullanici_id, cari_id, yk):
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

    cari_id = int(payload.get('cari_id') or 0)
    if not cari_id:
        raise MoAjandaError('cari_id zorunlu.', 400)

    idem = (payload.get('idempotency_key') or '').strip()
    if not idem:
        raise MoAjandaError('idempotency_key zorunlu.', 400)

    gorusme_tipi = (payload.get('gorusme_tipi') or '').strip()
    if gorusme_tipi not in GORUSME_TIPLERI_ALL:
        raise MoAjandaError('gorusme_tipi gecersiz.', 400)

    plan_tarihi = _parse_plan_tarihi(payload.get('plan_tarihi') or '')
    plan_notu = (payload.get('plan_notu') or '').strip() or None

    _scope_kontrol(con, kullanici_id, cari_id, yk)

    mevcut = con.execute(
        f'SELECT * FROM {TABLO} WHERE idempotency_key=? AND aktif=1',
        (idem,),
    ).fetchone()
    if mevcut:
        cm = _cari_map(con, [int(mevcut['cari_id'])])
        return {
            'ok': True,
            'kayit': _row_dict(mevcut, cm),
            'idempotent': True,
            'mesaj': 'Plan zaten kayitli.',
        }

    try:
        con.execute('BEGIN IMMEDIATE')
    except sqlite3.OperationalError:
        pass

    try:
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
        cm = _cari_map(con, [cari_id])
        return {
            'ok': True,
            'kayit': _row_dict(row, cm),
            'idempotent': False,
            'mesaj': 'Plan olusturuldu.',
        }
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass
        raise


def ajanda_listele(
    con: sqlite3.Connection,
    kullanici_id: int,
    yk: set[str] | None = None,
    *,
    filtre: str = 'bugun',
) -> list[dict[str, Any]]:
    if not _tablo_var(con, TABLO):
        return []

    f = (filtre or 'bugun').strip().lower()
    today = _today()
    hafta_bas, hafta_bit = _hafta_araligi()

    sql = f"""
        SELECT a.*, c.unvan AS cari_unvan
        FROM {TABLO} a
        LEFT JOIN nexgen_cari c ON c.id = a.cari_id
        WHERE a.aktif=1 AND a.kullanici_id=?
    """
    params: list[Any] = [kullanici_id]

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
    cm = _cari_map(con, cari_ids)

    out: list[dict[str, Any]] = []
    for r in rows:
        item = _row_dict(r, cm)
        if not can_mo_view_cari(con, kullanici_id, int(r['cari_id']), yk):
            continue
        out.append(item)
    return ajanda_enrich_gorusme_ozet(con, out)


def ajanda_zorunlu_sonuc_listele(
    con: sqlite3.Connection,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Önceki gün(ler)den kalan sonuçsuz PLANLANDI kayıtları — blocking gate."""
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
    _scope_kontrol(con, kullanici_id, int(row['cari_id']), yk)
    cm = _cari_map(con, [int(row['cari_id'])])
    return _row_dict(row, cm)


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
    cari_id: int,
    yk: set[str] | None = None,
    *,
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
    if int(row['cari_id']) != int(cari_id):
        raise MoAjandaError('Ajanda cari eslesmiyor.', 400)
    if row['gorusme_id']:
        raise MoAjandaError('Ajanda kaydi zaten tamamlanmis.', 409)

    _scope_kontrol(con, kullanici_id, int(cari_id), yk)

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
    cari_id: int,
    gorusme_tarihi: str,
    gorusme_tipi: str = '',
    *,
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

    gun = (gorusme_tarihi or '')[:10]
    if not gun:
        return {'durum': 'skip', 'sebep': 'tarih_eksik'}

    # A) Aynı gün+cari+kullanıcı için tek PLANLANDI kayıt ara
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
