# -*- coding: utf-8 -*-
"""FAZ-SEVKIYAT-B26-B19-DUZELTME-1 — tahsilat idempotency + kalem validasyon."""
from __future__ import annotations

import hashlib
import io
import os
import sqlite3
import sys
import uuid

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'app')
DB = os.path.join(APP, 'mock_data.db')
sys.path.insert(0, APP)
os.chdir(APP)

PRE_SHA = hashlib.sha256(open(DB, 'rb').read()).hexdigest()
TEST_PREFIX = 'MSV-B26B19'
results: list[tuple[str, bool, str]] = []


def ok(name: str, cond: bool, detail: str = '') -> None:
    results.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f' — {detail}' if detail else ''))


def _con():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _best_kalem(con, siparis_id: int, min_kg: float = 0) -> dict | None:
    from modules.nexgen.pzm_siparis_read import pzm_siparis_kalemleri_getir
    from modules.nexgen.mo_sevkiyat_service import (
        _uretilen_kg_siparis,
        kalan_miktarlar,
        sevk_edilmis_kg,
    )
    kalan_map = {k['siparis_kalem_id']: float(k.get('kalan_kg') or 0) for k in kalan_miktarlar(con, siparis_id)}
    uret = _uretilen_kg_siparis(con, siparis_id)
    sevk = sevk_edilmis_kg(con, siparis_id)
    cap = max(0.0, uret - sevk) if uret > 0.001 else None
    for k in pzm_siparis_kalemleri_getir(con, siparis_id):
        kid = k.get('id')
        if not kid:
            continue
        kalan = kalan_map.get(kid, 0.0)
        edilebilir = min(kalan, cap) if cap is not None else kalan
        if edilebilir + 0.001 >= float(min_kg):
            return k
    return None


def _max_sevk_edilebilir(con, siparis_id: int) -> float:
    k = _best_kalem(con, siparis_id, 0)
    if not k:
        return 0.0
    from modules.nexgen.mo_sevkiyat_service import kalan_miktarlar, _uretilen_kg_siparis, sevk_edilmis_kg
    kid = k['id']
    kalan = next((x['kalan_kg'] for x in kalan_miktarlar(con, siparis_id) if x.get('siparis_kalem_id') == kid), 0)
    uret = _uretilen_kg_siparis(con, siparis_id)
    if uret > 0.001:
        sevk = sevk_edilmis_kg(con, siparis_id)
        return min(float(kalan or 0), max(0.0, uret - sevk))
    return float(kalan or 0)


def _find_siparis(
    con,
    *,
    temiz: bool = False,
    min_kalan_kg: float = 1.0,
    exclude_ids: set[int] | None = None,
) -> dict | None:
    rows = con.execute(
        """
        SELECT id, cari_id, siparis_no, durum FROM nexgen_planlama_siparis
        WHERE durum IN ('ONAYLANDI','URETIMDE','TAMAMLANDI','MPR_BEKLIYOR','PLANLAMAYA_HAZIR')
          AND EXISTS (
            SELECT 1 FROM nexgen_planlama_siparis_kalem k
            WHERE k.planlama_siparis_id = nexgen_planlama_siparis.id
          )
        ORDER BY id DESC
        """
    ).fetchall()
    for r in rows:
        d = dict(r)
        sid = int(d['id'])
        if exclude_ids and sid in exclude_ids:
            continue
        if temiz:
            n = con.execute(
                """
                SELECT COUNT(*) FROM mo_musteri_sevkiyat
                WHERE siparis_id=? AND aktif=1
                  AND durum IN ('SEVK_EDILDI','TESLIM_EDILDI','TAMAMLANDI')
                """,
                (sid,),
            ).fetchone()[0]
            if int(n or 0) > 0:
                continue
        if _max_sevk_edilebilir(con, sid) + 0.001 < float(min_kalan_kg):
            continue
        return d
    return None


def _first_kalem(con, siparis_id: int) -> dict | None:
    return _best_kalem(con, siparis_id, 0) or None


def _other_kalem(con, siparis_id: int) -> int | None:
    row = con.execute(
        """
        SELECT k.id FROM nexgen_planlama_siparis_kalem k
        WHERE k.planlama_siparis_id != ?
        LIMIT 1
        """,
        (siparis_id,),
    ).fetchone()
    return int(row['id']) if row else None


def _ensure_tahsilat(con, sid: int):
    cols = [c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()]
    if 'tahsilat_kurali' not in cols:
        return
    con.execute(
        """
        UPDATE nexgen_planlama_siparis SET
            tahsilat_kurali='SEVKTEN_SONRA', tahsilat_gun_sayisi=15,
            tahsilat_durumu='SEVK_BEKLIYOR', planlanan_tahsilat_tarihi=NULL,
            tahsilat_tarih_kaynagi=NULL, tahsilat_hesaplanan_sevk_ref=NULL
        WHERE id=?
        """,
        (sid,),
    )
    con.commit()


def _kalem_payload(con, sid: int, kg: float) -> dict:
    k = _best_kalem(con, sid, kg)
    if not k or not k.get('id'):
        raise RuntimeError('yeterli kalanli kalem yok')
    return {'siparis_kalem_id': int(k['id']), 'miktar_kg': kg}


def test_b26_tahsilat_idempotent():
    from modules.nexgen.mo_sevkiyat_service import (
        _tahsilat_sevk_sonrasi_guncelle,
        durum_guncelle,
        gercek_sevk_tarihi,
        sevkiyat_olustur,
    )

    con = _con()
    try:
        sip = _find_siparis(con, temiz=True, min_kalan_kg=200)
        ok('T01 siparis', bool(sip), str(sip.get('id') if sip else ''))
        if not sip:
            return
        sid = int(sip['id'])
        _ensure_tahsilat(con, sid)
        tag = uuid.uuid4().hex[:8]
        yk = {'*'}
        k1 = _kalem_payload(con, sid, 100)

        a = sevkiyat_olustur(con, {
            'idempotency_key': f'{TEST_PREFIX}-a-{tag}',
            'siparis_id': sid, 'kalemler': [k1],
        }, 1, yk)
        durum_guncelle(con, int(a['id']), 'YUKLENIYOR', 1, yk)
        durum_guncelle(con, int(a['id']), 'SEVK_EDILDI', 1, yk, sevk_tarihi='2026-09-10')

        row = con.execute(
            'SELECT planlanan_tahsilat_tarihi FROM nexgen_planlama_siparis WHERE id=?', (sid,),
        ).fetchone()
        ok('T02 ilk_plan', row and row['planlanan_tahsilat_tarihi'] == '2026-09-25',
           row['planlanan_tahsilat_tarihi'] if row else '')

        b = sevkiyat_olustur(con, {
            'idempotency_key': f'{TEST_PREFIX}-b-{tag}',
            'siparis_id': sid, 'kalemler': [_kalem_payload(con, sid, 50)],
        }, 1, yk)
        durum_guncelle(con, int(b['id']), 'YUKLENIYOR', 1, yk)
        durum_guncelle(con, int(b['id']), 'SEVK_EDILDI', 1, yk, sevk_tarihi='2026-10-01')

        row2 = con.execute(
            'SELECT planlanan_tahsilat_tarihi FROM nexgen_planlama_siparis WHERE id=?', (sid,),
        ).fetchone()
        ok('T03 ikinci_sevk_plan_degmez', row2 and row2['planlanan_tahsilat_tarihi'] == '2026-09-25',
           row2['planlanan_tahsilat_tarihi'] if row2 else '')

        c = sevkiyat_olustur(con, {
            'idempotency_key': f'{TEST_PREFIX}-c-{tag}',
            'siparis_id': sid, 'kalemler': [_kalem_payload(con, sid, 50)],
        }, 1, yk)
        durum_guncelle(con, int(c['id']), 'YUKLENIYOR', 1, yk)
        durum_guncelle(con, int(c['id']), 'SEVK_EDILDI', 1, yk, sevk_tarihi='2026-11-15')
        row3 = con.execute(
            'SELECT planlanan_tahsilat_tarihi FROM nexgen_planlama_siparis WHERE id=?', (sid,),
        ).fetchone()
        ok('T04 ucuncu_sevk_plan_degmez', row3 and row3['planlanan_tahsilat_tarihi'] == '2026-09-25',
           row3['planlanan_tahsilat_tarihi'] if row3 else '')

        _tahsilat_sevk_sonrasi_guncelle(con, sid, int(a['id']))
        con.commit()
        row4 = con.execute(
            'SELECT planlanan_tahsilat_tarihi FROM nexgen_planlama_siparis WHERE id=?', (sid,),
        ).fetchone()
        ok('T05 tekrar_cagri_idempotent', row4 and row4['planlanan_tahsilat_tarihi'] == '2026-09-25',
           row4['planlanan_tahsilat_tarihi'] if row4 else '')

        gt = gercek_sevk_tarihi(con, sid)
        ok('T06 en_eski_sevk', gt == '2026-09-10', gt)
    finally:
        con.close()


def test_b19_kalem_validasyon():
    from modules.nexgen.mo_sevkiyat_service import MoSevkiyatError, sevkiyat_olustur

    con = _con()
    try:
        sip = _find_siparis(con, min_kalan_kg=1)
        ok('K01 siparis', bool(sip), str(sip.get('id') if sip else ''))
        if not sip:
            return
        sid = int(sip['id'])
        tag = uuid.uuid4().hex[:8]
        yk = {'*'}
        base = {'idempotency_key': f'{TEST_PREFIX}-k-{tag}', 'siparis_id': sid}

        def expect_err(payload, kod_min=400):
            try:
                sevkiyat_olustur(con, payload, 1, yk)
                return False, 'exception yok'
            except MoSevkiyatError as e:
                return e.kod >= kod_min, f'{e.kod}:{e.mesaj[:60]}'

        p = dict(base, idempotency_key=f'{TEST_PREFIX}-k0-{tag}',
                 kalemler=[{'miktar_kg': 10}])
        c, d = expect_err(p)
        ok('K02 kalem_id_yok', c, d)

        p = dict(base, idempotency_key=f'{TEST_PREFIX}-k1-{tag}',
                 kalemler=[{'siparis_kalem_id': 999999999, 'miktar_kg': 10}])
        c, d = expect_err(p)
        ok('K03 gecersiz_id', c, d)

        other = _other_kalem(con, sid)
        if other:
            p = dict(base, idempotency_key=f'{TEST_PREFIX}-k2-{tag}',
                     kalemler=[{'siparis_kalem_id': other, 'miktar_kg': 10}])
            c, d = expect_err(p)
            ok('K04 baska_siparis_kalem', c, d)
        else:
            ok('K04 baska_siparis_kalem', True, 'ornek yok')

        p = dict(base, idempotency_key=f'{TEST_PREFIX}-k3-{tag}',
                 kalemler=[{'siparis_kalem_id': _first_kalem(con, sid)['id'], 'miktar_kg': 0}])
        c, d = expect_err(p)
        ok('K05 sifir_miktar', c, d)

        p = dict(base, idempotency_key=f'{TEST_PREFIX}-k4-{tag}',
                 kalemler=[{'siparis_kalem_id': _first_kalem(con, sid)['id'], 'miktar_kg': -5}])
        c, d = expect_err(p)
        ok('K06 negatif', c, d)

        p = dict(base, idempotency_key=f'{TEST_PREFIX}-k5-{tag}',
                 kalemler=[{'siparis_kalem_id': _first_kalem(con, sid)['id'], 'miktar_kg': 99999}])
        c, d = expect_err(p, 409)
        ok('K07 kalan_asim', c, d)

        from modules.nexgen.mo_sevkiyat_service import _uretilen_kg_siparis, sevk_edilmis_kg
        uret = _uretilen_kg_siparis(con, sid)
        sevk = sevk_edilmis_kg(con, sid)
        if uret > 0:
            asiri = uret - sevk + 1000
            p = dict(base, idempotency_key=f'{TEST_PREFIX}-k6-{tag}',
                     kalemler=[{'siparis_kalem_id': _first_kalem(con, sid)['id'], 'miktar_kg': asiri}])
            c, d = expect_err(p, 409)
            ok('K08 uretim_asim', c, d)
        else:
            ok('K08 uretim_asim', True, 'uretilen=0 atlandi')

        ok_payload = dict(base, idempotency_key=f'{TEST_PREFIX}-k7-{tag}',
                          kalemler=[_kalem_payload(con, sid, 1)])
        r = sevkiyat_olustur(con, ok_payload, 1, yk)
        ok('K09 gecerli_kalem', bool(r.get('id')), r.get('sevkiyat_no'))
    finally:
        con.close()


def test_durum_zincir():
    from modules.nexgen.mo_sevkiyat_service import MoSevkiyatError, durum_guncelle, sevkiyat_olustur

    con = _con()
    try:
        sip = _find_siparis(con, min_kalan_kg=1)
        ok('D01 siparis', bool(sip), str(sip.get('id') if sip else ''))
        if not sip:
            return
        sid = int(sip['id'])
        tag = uuid.uuid4().hex[:8]
        yk = {'*'}
        s = sevkiyat_olustur(con, {
            'idempotency_key': f'{TEST_PREFIX}-d-{tag}',
            'siparis_id': sid,
            'kalemler': [_kalem_payload(con, sid, 1)],
        }, 1, yk)
        vid = int(s['id'])
        try:
            durum_guncelle(con, vid, 'SEVK_EDILDI', 1, yk)
            ok('D02 atlama_engel', False, 'izin verildi')
        except MoSevkiyatError as e:
            ok('D02 atlama_engel', e.kod == 409, e.mesaj[:50])
    finally:
        con.close()


def test_api_http():
    import config as _cfg
    _cfg.Config.MOCK_DB_PATH = DB
    import app as flask_app

    app = flask_app.app
    app.config['TESTING'] = True
    client = app.test_client()
    con = _con()
    sip = _find_siparis(con, min_kalan_kg=0)
    ok('H01 siparis', bool(sip), str(sip.get('id') if sip else ''))
    if not sip:
        con.close()
        return
    sid = int(sip['id'])
    kid = _first_kalem(con, sid)['id']
    con.close()

    with client.session_transaction() as s:
        s['kullanici'] = {'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem', 'RolId': 1, 'Aktif': 1}
        s['kullanici_tip'] = 'sistem'
        s['yetkiler'] = {
            'nexgen.sevkiyat.write': {'can_create': True, 'can_update': True},
        }

    r1 = client.post('/nexgen/api/mo-sevkiyat', json={
        'idempotency_key': f'{TEST_PREFIX}-http-{uuid.uuid4().hex[:6]}',
        'siparis_id': sid,
        'kalemler': [{'miktar_kg': 10}],
    })
    ok('H02 http_kalem_yok', r1.status_code == 400, str(r1.status_code))

    r2 = client.post('/nexgen/api/mo-sevkiyat', json={
        'idempotency_key': f'{TEST_PREFIX}-http2-{uuid.uuid4().hex[:6]}',
        'siparis_id': sid,
        'kalemler': [{'siparis_kalem_id': kid, 'miktar_kg': 99999}],
    })
    ok('H03 http_asiri', r2.status_code == 409, str(r2.status_code))


if __name__ == '__main__':
    print('=' * 72)
    print('FAZ-SEVKIYAT-B26-B19-DUZELTME-1')
    print(f'PRE SHA: {PRE_SHA}')
    print('=' * 72)
    test_b26_tahsilat_idempotent()
    test_b19_kalem_validasyon()
    test_durum_zincir()
    test_api_http()
    POST_SHA = hashlib.sha256(open(DB, 'rb').read()).hexdigest()
    fail = [n for n, c, _ in results if not c]
    print('=' * 72)
    print(f'SONUC: {len(results) - len(fail)}/{len(results)} PASS')
    print(f'POST SHA: {POST_SHA}')
    if fail:
        print('FAIL:', ', '.join(fail))
        sys.exit(1)
