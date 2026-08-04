# -*- coding: utf-8 -*-
"""FAZ-MUSTERI-TEMSILCISI-TALEP-OMURGA-F1-F2 — local service/migration test."""
from __future__ import annotations

import os
import sqlite3
import sys
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'app')
sys.path.insert(0, APP)

import importlib

mig = importlib.import_module('migrations.146_nexgen_musteri_temsilcisi_talep')
from modules.nexgen.musteri_temsilcisi_talep_service import (  # noqa: E402
    MusteriTemsilcisiTalepError,
    talep_detay_getir,
    talep_eksik_bilgiye_gonder,
    talep_iptal_et,
    talep_isleme_al,
    talep_listele,
    talep_olustur,
    talep_reddet,
    talep_sayaclari,
    talep_tekrar_gonder,
)

DB = os.path.join(APP, 'mock_data.db')
PASS = 0
FAIL = 0


def ok(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  PASS  {name}')
    else:
        FAIL += 1
        print(f'  FAIL  {name} {detail}')


def con():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def seed_gorusme(c):
    """Mevcut bir cari görüşmesi bul veya minimal insert."""
    row = c.execute(
        """
        SELECT id, cari_id, musteri_aday_id, verilen_fiyat, fiyat_para_birimi,
               konusulan_tonaj, odeme_tipi, vade_gun, cek_vade_gun, kisa_not
        FROM musteri_operasyon_gorusme
        WHERE COALESCE(aktif,1)=1 AND cari_id IS NOT NULL
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    if row:
        return row
    cari = c.execute('SELECT id FROM nexgen_cari ORDER BY id LIMIT 1').fetchone()
    if not cari:
        raise RuntimeError('nexgen_cari yok')
    uid = c.execute('SELECT id FROM kullanicilar ORDER BY id LIMIT 1').fetchone()
    uid = int(uid['id']) if uid else 1
    now = '2026-07-30 12:00:00'
    cur = c.execute(
        """
        INSERT INTO musteri_operasyon_gorusme (
            cari_id, musteri_aday_id, kullanici_id, kaynak, gorusme_tipi, sonuc_tipi,
            kisa_not, gorusme_tarihi, oncelik, aktif,
            verilen_fiyat, fiyat_para_birimi, fiyat_birimi, konusulan_tonaj,
            odeme_tipi, vade_gun, created_at, updated_at, idempotency_key
        ) VALUES (
            ?, NULL, ?, 'MUSTERI_OPERASYONU', 'TELEFON', 'BILGI',
            'MTT test gorusme', ?, 'NORMAL', 1,
            12.5, 'USD', 'KG', 3.0,
            'PESIN', NULL, ?, ?, ?
        )
        """,
        (int(cari['id']), uid, now[:10], now, now, f'test-mtt-{uuid.uuid4().hex}'),
    )
    c.commit()
    return c.execute(
        'SELECT * FROM musteri_operasyon_gorusme WHERE id=?', (cur.lastrowid,),
    ).fetchone()


def main():
    print('=' * 60)
    print('FAZ MTT OMURGA F1-F2')
    print('DB:', DB)
    print('=' * 60)

    mig.run(DB)
    c = con()
    try:
        ok('tablo talep', bool(c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexgen_musteri_temsilcisi_talep'"
        ).fetchone()))
        ok('tablo kalem', bool(c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexgen_musteri_temsilcisi_talep_kalem'"
        ).fetchone()))

        g = seed_gorusme(c)
        gid = int(g['id'])
        cari_id = int(g['cari_id'])
        uid = 1
        idem = f'mtt-test-{uuid.uuid4().hex}'

        def full_kalem(urun, **extra):
            k = {
                'urun_aciklama': urun,
                'urun_ailesi': 'TABAN',
                'renk_aciklama': 'Siyah',
                'miktar_kg': 100,
                'para_birimi': 'USD',
                'odeme_tipi': 'NAKIT',
                'vade_gun': 0,
                'verilen_fiyat': 12.5,
            }
            k.update(extra)
            return k

        payload = {
            'gorusme_id': gid,
            'talep_turu': 'SIPARIS',
            'cari_id': cari_id,
            'musteri_aday_id': None,
            'oncelik': 'YUKSEK',
            'aciklama': 'MTT omurga talep aciklama',
            'musteri_notu': 'test not',
            'idempotency_key': idem,
            'kalemler': [full_kalem('Terlik hamur A')],
        }
        out = talep_olustur(c, payload, uid)
        kayit = out['kayit']
        # V1 Onay Merkezi: yeni MTT önce ONAY_BEKLIYOR
        ok('olustur', not out['idempotent'] and kayit['durum'] == 'ONAY_BEKLIYOR',
           str(kayit.get('durum')))
        ok('talep_no prefix', str(kayit['talep_no']).startswith('MTT-2026-'))
        ok('snapshot aciklama', bool(kayit.get('aciklama')))
        ok('kalem var', len(kayit['kalemler']) == 1)
        # gorusme fiyat fallback
        k0 = kayit['kalemler'][0]
        if g['verilen_fiyat'] is not None:
            ok('fiyat snapshot fallback', k0.get('verilen_fiyat') is not None)
        else:
            ok('fiyat snapshot fallback skip', True)

        out2 = talep_olustur(c, payload, uid)
        ok('idempotent ayni payload', out2['idempotent'] is True)
        ok('idempotent ayni id', out2['kayit']['id'] == kayit['id'])

        bad = dict(payload)
        bad['kalemler'] = [full_kalem('Baska urun')]
        try:
            talep_olustur(c, bad, uid)
            ok('idem conflict', False, 'exception beklenirdi')
        except MusteriTemsilcisiTalepError as e:
            ok('idem conflict', e.kod == 409)

        tid = int(kayit['id'])
        # Onay öncesi işleme alınamaz
        try:
            talep_isleme_al(c, tid, 99)
            ok('isleme onay oncesi engel', False)
        except MusteriTemsilcisiTalepError as e:
            ok('isleme onay oncesi engel', e.kod in (409, 400) or 'ONAY_BEKLIYOR' in (e.mesaj or ''))

        from modules.nexgen.onay_service import onay_by_kaynak, onay_onayla
        from modules.nexgen.cari_sorumlu_service import load_kullanici_yetkileri
        ayk = load_kullanici_yetkileri(c, 1)
        onay = onay_by_kaynak(c, 'MUSTERI_TEMSILCISI_TALEP', tid)
        ok('onay kaydi olustu', bool(onay and onay.get('id')))
        if onay:
            onay_onayla(c, int(onay['id']), 1, ayk)
            c.commit()
        durum_yeni = c.execute(
            'SELECT durum FROM nexgen_musteri_temsilcisi_talep WHERE id=?', (tid,)
        ).fetchone()['durum']
        ok('onay sonrasi YENI', durum_yeni == 'YENI', durum_yeni)

        r1 = talep_isleme_al(c, tid, 99)
        ok('isleme al', r1['kayit']['durum'] == 'ISLEME_ALINDI' and int(r1['kayit']['atanan_kullanici_id']) == 99)
        r1b = talep_isleme_al(c, tid, 99)
        ok('isleme al idempotent', r1b['idempotent'] is True)
        try:
            talep_isleme_al(c, tid, 100)
            ok('isleme conflict', False)
        except MusteriTemsilcisiTalepError as e:
            ok('isleme conflict', e.kod == 409)

        # F6: eksik bilgi / tekrar gönder devre dışı
        try:
            talep_eksik_bilgiye_gonder(c, tid, 99, 'Eksik renk')
            ok('eksik bilgi kapali', False)
        except MusteriTemsilcisiTalepError as e:
            ok('eksik bilgi kapali', e.kod == 410 and 'devre dışı' in e.mesaj.lower())
        try:
            talep_tekrar_gonder(c, tid, uid)
            ok('tekrar gonder kapali', False)
        except MusteriTemsilcisiTalepError as e:
            ok('tekrar gonder kapali', e.kod == 410)

        # ikinci talep — red / iptal akışı
        idem2 = f'mtt-test-{uuid.uuid4().hex}'
        p2 = dict(payload)
        p2['idempotency_key'] = idem2
        p2['talep_turu'] = 'NUMUNE'
        p2['aciklama'] = 'Numune talep aciklama'
        p2['musteri_notu'] = 'Numune amaci test'
        p2['kalemler'] = [full_kalem('Numune X', miktar_kg=5)]
        t2 = talep_olustur(c, p2, uid)['kayit']
        on2 = onay_by_kaynak(c, 'MUSTERI_TEMSILCISI_TALEP', int(t2['id']))
        if on2:
            onay_onayla(c, int(on2['id']), 1, ayk)
            c.commit()
        talep_isleme_al(c, int(t2['id']), 99)
        rd = talep_reddet(c, int(t2['id']), 99, 'Stok yok')
        ok('reddet', rd['kayit']['durum'] == 'REDDEDILDI')

        idem3 = f'mtt-test-{uuid.uuid4().hex}'
        p3 = dict(payload)
        p3['idempotency_key'] = idem3
        t3 = talep_olustur(c, p3, uid)['kayit']
        # ONAY_BEKLIYOR iken iptal (olusturan)
        ip = talep_iptal_et(c, int(t3['id']), uid)
        ok('iptal', ip['kayit']['durum'] == 'IPTAL')

        # yasak gecis
        try:
            from modules.nexgen.musteri_temsilcisi_talep_service import _assert_gecis
            _assert_gecis('YENI', 'SIPARISE_DONUSTU')
            ok('donusum elle yasak', False)
        except MusteriTemsilcisiTalepError as e:
            ok('donusum elle yasak', e.kod == 409)

        ok('liste', len(talep_listele(c, limit=10)) >= 1)
        ok('detay', talep_detay_getir(c, tid)['id'] == tid)
        sc = talep_sayaclari(c)
        ok('sayac', sc['TOPLAM'] >= 3)

        # XOR
        try:
            talep_olustur(c, {
                **payload,
                'idempotency_key': f'mtt-xor-{uuid.uuid4().hex}',
                'cari_id': cari_id,
                'musteri_aday_id': 1,
            }, uid)
            ok('xor', False)
        except MusteriTemsilcisiTalepError as e:
            ok('xor', e.kod == 400)

        # bos kalem
        try:
            talep_olustur(c, {
                **payload,
                'idempotency_key': f'mtt-empty-{uuid.uuid4().hex}',
                'kalemler': [],
            }, uid)
            ok('bos kalem', False)
        except MusteriTemsilcisiTalepError as e:
            ok('bos kalem', e.kod == 400)

    finally:
        c.close()

    print('-' * 60)
    print(f'SONUC: {PASS} PASS / {FAIL} FAIL')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
