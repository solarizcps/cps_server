# -*- coding: utf-8 -*-
"""Üretim Plan — CPS SQLite plan kayıtları."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from db import get_conn

PLAN_DONEMLERI = ('bu_hafta', 'gelecek_hafta', 'bu_ay', '3_ay', 'gecmis')
GEREKCE_SECENEKLERI = (
    'Müşteri Acil', 'Termin', 'Hammadde Hazır', 'Kalıp Boş',
    'Ödeme/Ticari Öncelik', 'Üretim Uygunluğu', 'Diğer',
)


def _ensure_table(con: sqlite3.Connection) -> None:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='uretim_model_plan'"
    ).fetchone()
    if row:
        return
    import importlib.util
    import os
    mig = os.path.join(
        os.path.dirname(__file__), '..', '..', 'migrations', '158_uretim_model_plan.py'
    )
    spec = importlib.util.spec_from_file_location('mig158', mig)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._ensure_table(con)


def canonical_key(sip_no, sip_harinx, mamul_skod, rkod) -> str:
    return f'{int(sip_no)}|{int(sip_harinx)}|{mamul_skod}|{int(rkod or 0)}'


def parse_canonical_key(key: str) -> dict:
    parts = (key or '').split('|')
    if len(parts) != 4:
        raise ValueError('Geçersiz canonical key')
    return {
        'sip_no': int(parts[0]),
        'sip_harinx': int(parts[1]),
        'mamul_skod': parts[2],
        'rkod': int(parts[3]),
    }


def _row_to_dict(row) -> dict:
    if row is None:
        return None
    d = dict(row)
    d['canonical_key'] = canonical_key(
        d['sip_no'], d['sip_harinx'], d['mamul_skod'], d['rkod']
    )
    return d


def _week_bounds(ref: date | None = None) -> tuple[date, date]:
    ref = ref or date.today()
    start = ref - timedelta(days=ref.weekday())
    end = start + timedelta(days=6)
    return start, end


def donem_aralik(donem: str, ref: date | None = None) -> tuple[date | None, date | None]:
    ref = ref or date.today()
    if donem == 'bu_hafta':
        return _week_bounds(ref)
    if donem == 'gelecek_hafta':
        s, _ = _week_bounds(ref)
        s = s + timedelta(days=7)
        return s, s + timedelta(days=6)
    if donem == 'bu_ay':
        start = ref.replace(day=1)
        if ref.month == 12:
            end = date(ref.year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(ref.year, ref.month + 1, 1) - timedelta(days=1)
        return start, end
    if donem == '3_ay':
        end = ref + timedelta(days=92)
        return ref, end
    if donem == 'gecmis':
        return None, ref - timedelta(days=1)
    return None, None


def _overlap(plan_bas, plan_bit, d_start, d_end) -> bool:
    if not plan_bas and not plan_bit:
        return True
    try:
        pb = datetime.strptime((plan_bas or plan_bit)[:10], '%Y-%m-%d').date() if (plan_bas or plan_bit) else None
        pe = datetime.strptime((plan_bit or plan_bas)[:10], '%Y-%m-%d').date() if (plan_bit or plan_bas) else pb
    except ValueError:
        return True
    if d_start is None and d_end is None:
        return True
    if d_start is None:
        return pe <= d_end if pe else False
    if d_end is None:
        return pb >= d_start if pb else False
    if not pb or not pe:
        return True
    return not (pe < d_start or pb > d_end)


def liste_aktif_planlar(donem: str = 'bu_hafta') -> list[dict]:
    con = get_conn()
    try:
        _ensure_table(con)
        rows = con.execute("""
            SELECT * FROM uretim_model_plan
             WHERE aktif = 1
             ORDER BY oncelik ASC, plan_baslangic ASC, id ASC
        """).fetchall()
        d_start, d_end = donem_aralik(donem)
        out = []
        for r in rows:
            d = _row_to_dict(r)
            if donem == 'gecmis':
                pb = d.get('plan_bitis') or d.get('plan_baslangic')
                if pb:
                    try:
                        if datetime.strptime(pb[:10], '%Y-%m-%d').date() >= date.today():
                            continue
                    except ValueError:
                        pass
            elif not _overlap(d.get('plan_baslangic'), d.get('plan_bitis'), d_start, d_end):
                continue
            out.append(d)
        return out
    finally:
        con.close()


def plan_get(plan_id: int) -> dict | None:
    con = get_conn()
    try:
        _ensure_table(con)
        row = con.execute(
            'SELECT * FROM uretim_model_plan WHERE id=?', (int(plan_id),)
        ).fetchone()
        return _row_to_dict(row)
    finally:
        con.close()


ENJ_ALANLARI = (
    'enj_makine_id', 'enj_istasyon_no', 'enj_slot', 'enj_kalip_id',
    'enj_kalip_kod', 'enj_aktif_goz', 'enj_kalip_basi_cift', 'enj_tur_cift',
    'enj_gunluk_tur_plan', 'enj_gunluk_kapasite',
    'enj_plan_baslangic', 'enj_plan_bitis',
    'enj_tahmini_gun', 'enj_planlanacak_cift',
)


def _enj_vals(payload: dict) -> dict:
    """Payload'dan enj_ alanlarını çek; tip dönüşümü yap."""
    out = {}
    int_fields = {'enj_makine_id', 'enj_istasyon_no', 'enj_kalip_id',
                  'enj_aktif_goz', 'enj_kalip_basi_cift', 'enj_tur_cift',
                  'enj_gunluk_tur_plan', 'enj_gunluk_kapasite'}
    real_fields = {'enj_tahmini_gun', 'enj_planlanacak_cift'}
    for k in ENJ_ALANLARI:
        v = payload.get(k)
        if v is not None and v != '':
            if k in int_fields:
                try:
                    v = int(v)
                except (ValueError, TypeError):
                    v = None
            elif k in real_fields:
                try:
                    v = float(v)
                except (ValueError, TypeError):
                    v = None
        else:
            v = None
        out[k] = v
    return out


def plan_ekle(payload: dict, user_id: int) -> dict:
    con = get_conn()
    try:
        _ensure_table(con)
        dup = con.execute("""
            SELECT id FROM uretim_model_plan
             WHERE aktif=1 AND sip_no=? AND sip_harinx=? AND mamul_skod=? AND rkod=? AND plan_donemi=?
        """, (
            int(payload['sip_no']), int(payload['sip_harinx']),
            payload['mamul_skod'], int(payload.get('rkod') or 0),
            payload['plan_donemi'],
        )).fetchone()
        if dup:
            raise ValueError('Bu model+renk bu plan döneminde zaten planlı')

        enj = _enj_vals(payload)
        enj_cols = ', '.join(enj.keys())
        enj_ph = ', '.join(['?'] * len(enj))

        cur = con.execute(f"""
            INSERT INTO uretim_model_plan (
                sip_no, sip_harinx, mamul_skod, rkod,
                model_adi, renk_adi, miktar, termin,
                plan_donemi, plan_baslangic, plan_bitis,
                oncelik, plan_gerekce, plan_notu,
                aktif, created_by,
                {enj_cols}
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,{enj_ph})
        """, (
            int(payload['sip_no']), int(payload['sip_harinx']),
            payload['mamul_skod'], int(payload.get('rkod') or 0),
            payload.get('model_adi'), payload.get('renk_adi'),
            payload.get('miktar'), payload.get('termin'),
            payload['plan_donemi'],
            payload.get('plan_baslangic'), payload.get('plan_bitis'),
            int(payload.get('oncelik') or 3),
            payload.get('plan_gerekce'), payload.get('plan_notu'),
            int(user_id),
            *enj.values(),
        ))
        con.commit()
        return plan_get(cur.lastrowid)
    finally:
        con.close()


def plan_guncelle(plan_id: int, payload: dict, user_id: int) -> dict:
    con = get_conn()
    try:
        _ensure_table(con)
        mevcut = plan_get(plan_id)
        if not mevcut or not mevcut.get('aktif'):
            raise ValueError('Plan bulunamadı')

        donem = payload.get('plan_donemi', mevcut['plan_donemi'])
        dup = con.execute("""
            SELECT id FROM uretim_model_plan
             WHERE aktif=1 AND id<>? AND sip_no=? AND sip_harinx=? AND mamul_skod=? AND rkod=? AND plan_donemi=?
        """, (
            int(plan_id), mevcut['sip_no'], mevcut['sip_harinx'],
            mevcut['mamul_skod'], mevcut['rkod'], donem,
        )).fetchone()
        if dup:
            raise ValueError('Bu model+renk bu plan döneminde zaten planlı')

        enj = _enj_vals(payload)
        enj_set = ', '.join(f'{k}=?' for k in enj)

        con.execute(f"""
            UPDATE uretim_model_plan SET
                plan_donemi=?, plan_baslangic=?, plan_bitis=?,
                oncelik=?, plan_gerekce=?, plan_notu=?,
                {enj_set},
                updated_at=datetime('now','localtime'), updated_by=?
             WHERE id=?
        """, (
            donem,
            payload.get('plan_baslangic', mevcut.get('plan_baslangic')),
            payload.get('plan_bitis', mevcut.get('plan_bitis')),
            int(payload.get('oncelik', mevcut.get('oncelik') or 3)),
            payload.get('plan_gerekce', mevcut.get('plan_gerekce')),
            payload.get('plan_notu', mevcut.get('plan_notu')),
            *enj.values(),
            int(user_id), int(plan_id),
        ))
        con.commit()
        return plan_get(plan_id)
    finally:
        con.close()


def plan_pasif(plan_id: int, user_id: int) -> dict:
    con = get_conn()
    try:
        _ensure_table(con)
        con.execute("""
            UPDATE uretim_model_plan SET aktif=0,
                updated_at=datetime('now','localtime'), updated_by=?
             WHERE id=? AND aktif=1
        """, (int(user_id), int(plan_id)))
        con.commit()
        return plan_get(plan_id)
    finally:
        con.close()
