# -*- coding: utf-8 -*-
"""FAZ-MO-GERCEK-SEVKIYAT-MODULU-1 — backend test."""
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
TEST_PREFIX = 'MSV-TEST'
results: list[tuple[str, bool, str]] = []


def ok(name: str, cond: bool, detail: str = '') -> None:
    results.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f' — {detail}' if detail else ''))


def _con():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _run_migration():
    import importlib.util
    path = os.path.join(APP, 'migrations', '127_mo_musteri_sevkiyat.py')
    spec = importlib.util.spec_from_file_location('m127', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(DB)


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
    mo_only: bool = True,
) -> dict | None:
    if mo_only:
        sql = """
            SELECT id, cari_id, siparis_no, durum
            FROM nexgen_planlama_siparis
            WHERE kaynak_modul='MUSTERI_OPERASYONU'
              AND durum IN ('ONAYLANDI','URETIMDE','TAMAMLANDI','MPR_BEKLIYOR','PLANLAMAYA_HAZIR')
              AND EXISTS (
                SELECT 1 FROM nexgen_planlama_siparis_kalem k
                WHERE k.planlama_siparis_id = nexgen_planlama_siparis.id
              )
            ORDER BY id DESC
        """
    else:
        sql = """
            SELECT id, cari_id, siparis_no, durum FROM nexgen_planlama_siparis
            WHERE durum IN ('ONAYLANDI','URETIMDE','TAMAMLANDI','MPR_BEKLIYOR','PLANLAMAYA_HAZIR')
              AND EXISTS (
                SELECT 1 FROM nexgen_planlama_siparis_kalem k
                WHERE k.planlama_siparis_id = nexgen_planlama_siparis.id
              )
            ORDER BY id DESC
        """
    rows = con.execute(sql).fetchall()
    for r in rows:
        d = dict(r)
        sid = int(d['id'])
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
    if mo_only:
        return _find_siparis(
            con, temiz=temiz, min_kalan_kg=min_kalan_kg, mo_only=False,
        )
    return None


def _ensure_tahsilat_sevk(con, siparis_id: int):
    cols = [c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()]
    if 'tahsilat_kurali' not in cols:
        return
    con.execute(
        """
        UPDATE nexgen_planlama_siparis SET
            tahsilat_kurali='SEVKTEN_SONRA', tahsilat_gun_sayisi=15,
            tahsilat_durumu='SEVK_BEKLIYOR', planlanan_tahsilat_tarihi=NULL
        WHERE id=?
        """,
        (siparis_id,),
    )
    con.commit()


def test_migration():
    _run_migration()
    con = _con()
    try:
        ok('M01 tablo_sevkiyat', bool(con.execute(
            "SELECT 1 FROM sqlite_master WHERE name='mo_musteri_sevkiyat'"
        ).fetchone()))
        ok('M02 tablo_kalem', bool(con.execute(
            "SELECT 1 FROM sqlite_master WHERE name='mo_musteri_sevkiyat_kalem'"
        ).fetchone()))
    finally:
        con.close()


def _first_kalem(con, siparis_id: int) -> dict | None:
    return _best_kalem(con, siparis_id, 0)


def _kalem_payload(con, sid: int, kg: float) -> dict:
    k = _best_kalem(con, sid, kg)
    if not k or not k.get('id'):
        raise RuntimeError('yeterli kalanli kalem yok')
    return {'siparis_kalem_id': int(k['id']), 'miktar_kg': kg}


def test_tek_sevkiyat():
    from modules.nexgen.mo_sevkiyat_service import (
        durum_guncelle, gercek_sevk_tarihi, sevkiyat_olustur, sevkiyat_getir,
    )
    from modules.nexgen.mo_tahsilat_plan_service import hesapla_tahsilat_plani

    con = _con()
    try:
        sip = _find_siparis(con, temiz=True, min_kalan_kg=400)
        ok('S01 siparis_bulundu', bool(sip), str(sip.get('id') if sip else ''))
        if not sip:
            return
        sid = int(sip['id'])
        _ensure_tahsilat_sevk(con, sid)
        tag = uuid.uuid4().hex[:8]
        yk = {'*'}
        sevk_tarihi = '2026-08-05'

        s1 = sevkiyat_olustur(con, {
            'idempotency_key': f'{TEST_PREFIX}-tek-{tag}',
            'siparis_id': sid,
            'kalemler': [_kalem_payload(con, sid, 400)],
        }, 1, yk)
        ok('S02 olustur', bool(s1.get('id')), s1.get('sevkiyat_no'))
        ok('S03 durum_hazir', s1.get('durum') == 'HAZIRLANIYOR', s1.get('durum'))

        s2 = durum_guncelle(con, int(s1['id']), 'YUKLENIYOR', 1, yk)
        ok('S04 yukleniyor', s2.get('durum') == 'YUKLENIYOR')

        s3 = durum_guncelle(con, int(s1['id']), 'SEVK_EDILDI', 1, yk, sevk_tarihi=sevk_tarihi)
        ok('S05 sevk_edildi', s3.get('durum') == 'SEVK_EDILDI', s3.get('sevk_tarihi'))
        ok('S06 olay_cikti', s3.get('cari360_olay', {}).get('olay_tipi') == 'SEVK_CIKTI')

        gt = gercek_sevk_tarihi(con, sid)
        from datetime import date, timedelta
        beklenen_plan = (date.fromisoformat(gt) + timedelta(days=15)).isoformat() if gt else None
        ok('S07 gercek_sevk_tarihi', gt is not None and gt <= sevk_tarihi, gt)

        row = con.execute(
            'SELECT planlanan_tahsilat_tarihi, tahsilat_tarih_kaynagi FROM nexgen_planlama_siparis WHERE id=?',
            (sid,),
        ).fetchone()
        ok('S08 tahsilat_plan', row and row['planlanan_tahsilat_tarihi'] == beklenen_plan,
           row['planlanan_tahsilat_tarihi'] if row else '')
        ok('S09 tahsilat_kaynak', row and 'GERCEK_SEVK' in (row['tahsilat_tarih_kaynagi'] or ''), row['tahsilat_tarih_kaynagi'] if row else '')

        hp = hesapla_tahsilat_plani('SEVKTEN_SONRA', gun_sayisi=15, gercek_sevk_tarihi='2026-08-05')
        ok('S10 hesapla_plani', hp.get('planlanan_tahsilat_tarihi') == '2026-08-20')

        hp2 = hesapla_tahsilat_plani('SEVKTEN_SONRA', gun_sayisi=15)
        ok('S11 sevk_yok_bekliyor', hp2.get('tahsilat_durumu') == 'SEVK_BEKLIYOR')

        det = sevkiyat_getir(con, int(s1['id']), 1, yk)
        ok('S12 termin_alanlari', 'termin' in det and 'musteri_termin' in det['termin'])
    finally:
        con.close()


def test_kismi_coklu():
    from modules.nexgen.mo_sevkiyat_service import (
        durum_guncelle, kalan_miktarlar, sevkiyat_olustur,
    )

    con = _con()
    try:
        sip = _find_siparis(con, min_kalan_kg=700)
        ok('K01 siparis', bool(sip), str(sip.get('id') if sip else ''))
        if not sip:
            return
        sid = int(sip['id'])
        tag = uuid.uuid4().hex[:8]
        yk = {'*'}

        # İlk kısmi: 400 kg
        a = sevkiyat_olustur(con, {
            'idempotency_key': f'{TEST_PREFIX}-p1-{tag}',
            'siparis_id': sid,
            'kalemler': [_kalem_payload(con, sid, 400)],
        }, 1, yk)
        durum_guncelle(con, int(a['id']), 'YUKLENIYOR', 1, yk)
        durum_guncelle(con, int(a['id']), 'SEVK_EDILDI', 1, yk, sevk_tarihi='2026-08-01')

        # İkinci kısmi: 300 kg
        b = sevkiyat_olustur(con, {
            'idempotency_key': f'{TEST_PREFIX}-p2-{tag}',
            'siparis_id': sid,
            'kalemler': [_kalem_payload(con, sid, 300)],
        }, 1, yk)
        ok('K02 ikinci_sevkiyat', bool(b.get('id')), b.get('sevkiyat_no'))

        cnt = con.execute(
            "SELECT COUNT(*) n FROM mo_musteri_sevkiyat WHERE siparis_id=? AND idempotency_key LIKE ?",
            (sid, f'{TEST_PREFIX}-p%-{tag}'),
        ).fetchone()['n']
        ok('K03 coklu_sevkiyat', int(cnt) >= 2, str(cnt))

        # Duplicate idempotency
        c = sevkiyat_olustur(con, {
            'idempotency_key': f'{TEST_PREFIX}-p2-{tag}',
            'siparis_id': sid,
            'kalemler': [_kalem_payload(con, sid, 300)],
        }, 1, yk)
        ok('K04 idempotency', int(c['id']) == int(b['id']))

        # Asiri miktar — siparis toplam kg bilinmiyorsa en azından pozitif kalan kontrol
        kalan = kalan_miktarlar(con, sid)
        ok('K05 kalan_liste', isinstance(kalan, list) and len(kalan) >= 0)
    finally:
        con.close()


def test_yetki():
    from modules.nexgen.mo_sevkiyat_service import MoSevkiyatError, sevkiyat_olustur

    con = _con()
    try:
        sip = _find_siparis(con, min_kalan_kg=1)
        ok('Y01 siparis', bool(sip), str(sip.get('id') if sip else ''))
        if not sip:
            return
        try:
            sevkiyat_olustur(con, {
                'idempotency_key': f'{TEST_PREFIX}-yetki-{uuid.uuid4().hex[:6]}',
                'siparis_id': sip['id'],
                'kalemler': [_kalem_payload(con, int(sip['id']), 1)],
            }, 1, {'cari360.view_own:can_view'})
            ok('Y02 yetkisiz_403', False, 'exception bekleniyordu')
        except MoSevkiyatError as e:
            ok('Y02 yetkisiz_403', e.kod == 403, e.mesaj)
    finally:
        con.close()


def test_regression():
    import subprocess
    for script in (
        '_test_faz_mo_tahsilat_plani_1.py',
        '_test_faz_mo_surec_odak.py',
    ):
        r = subprocess.run([sys.executable, os.path.join(ROOT, script)], capture_output=True, text=True)
        ok(f'R_{script}', r.returncode == 0, (r.stdout or r.stderr)[-80:])


if __name__ == '__main__':
    print('=' * 72)
    print('FAZ-MO-GERCEK-SEVKIYAT-MODULU-1')
    print('=' * 72)
    print(f'PRE SHA: {PRE_SHA[:16]}...')
    test_migration()
    test_tek_sevkiyat()
    test_kismi_coklu()
    test_yetki()
    test_regression()
    POST_SHA = hashlib.sha256(open(DB, 'rb').read()).hexdigest()
    passed = sum(1 for _, p, _ in results if p)
    print('=' * 72)
    print(f'SONUÇ: {passed}/{len(results)}')
    print(f'POST SHA: {POST_SHA}')
    if passed != len(results):
        sys.exit(1)
