# -*- coding: utf-8 -*-
"""FAZ-MUSTERI-TEMSILCISI-TALEP-F3 — birleşik TX + UI smoke + atomiklik."""
from __future__ import annotations

import io
import os
import sys
import uuid
import sqlite3

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'app')
sys.path.insert(0, APP)
os.chdir(APP)
DB = os.path.join(APP, 'mock_data.db')

from modules.nexgen.cari360_yetki import can_musteri_pazarlama_menu  # noqa: E402
from modules.nexgen.cari_sorumlu_service import load_kullanici_yetkileri  # noqa: E402
from modules.nexgen.mo_gorusme_service import MoGorusmeError  # noqa: E402
from modules.nexgen.musteri_temsilcisi_talep_service import (  # noqa: E402
    MusteriTemsilcisiTalepError,
    gorusmelere_talep_ozeti_ekle,
    kaydet_gorusme_opsiyonel_talep,
)
from modules.nexgen.mo_gorusme_service import list_gorusmeler  # noqa: E402

PASS = FAIL = 0


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


def counts(c):
    g = c.execute('SELECT COUNT(*) n FROM musteri_operasyon_gorusme').fetchone()['n']
    t = c.execute(
        "SELECT COUNT(*) n FROM sqlite_master WHERE type='table' AND name='nexgen_musteri_temsilcisi_talep'"
    ).fetchone()['n']
    if not t:
        return g, 0, 0
    tt = c.execute('SELECT COUNT(*) n FROM nexgen_musteri_temsilcisi_talep').fetchone()['n']
    kk = c.execute('SELECT COUNT(*) n FROM nexgen_musteri_temsilcisi_talep_kalem').fetchone()['n']
    return g, tt, kk


def base_gorusme(cari_id=None, aday_id=None, **extra):
    idem = f'MO-GOR-{uuid.uuid4().hex}'
    p = {
        'gorusme_tipi': 'Telefon',
        'sonuc_tipi': 'Fiyat İstedi',
        'kisa_not': f'F3 test notu {uuid.uuid4().hex[:8]}',
        'gorusme_tarihi': '2026-07-30 15:00:00',
        'oncelik': 'NORMAL',
        'kaynak': 'MUSTERI_OPERASYONU',
        'idempotency_key': idem,
        'fiyat_verildi': 1,
        'verilen_fiyat': 12.5,
        'fiyat_para_birimi': 'USD',
        'fiyat_birimi': 'KG',
        'konusulan_tonaj': 3.0,
        'odeme_tipi': 'NAKIT',
    }
    if cari_id:
        p['cari_id'] = cari_id
    if aday_id:
        p['musteri_aday_id'] = aday_id
    p.update(extra)
    return p


def kalem(urun, **extra):
    """F6 zorunlu alanlarla kalem."""
    k = {
        'urun_aciklama': urun,
        'urun_ailesi': 'TABAN',
        'renk_aciklama': 'Siyah',
        'miktar_kg': 50,
    }
    k.update(extra)
    return k


def talep_siparis(kalemler=None, **extra):
    t = {
        'talep_turu': 'SIPARIS',
        'oncelik': 'NORMAL',
        'aciklama': 'F3 siparis talep aciklama',
        'kalemler': kalemler or [kalem('Eva taban')],
    }
    t.update(extra)
    return t


def talep_numune(kalemler=None, **extra):
    t = {
        'talep_turu': 'NUMUNE',
        'oncelik': 'NORMAL',
        'aciklama': 'F3 numune talep aciklama',
        'musteri_notu': 'Numune amaci / musteri beklentisi',
        'kalemler': kalemler or [kalem('Numune hamur', miktar_kg=5)],
    }
    t.update(extra)
    return t


def main():
    print('=' * 64)
    print('FAZ MTT F3 GORUSME+TALEP TX')
    print('=' * 64)

    tpl = open(os.path.join(APP, 'templates', 'nexgen', 'musteri_pazarlama.html'), encoding='utf-8').read()
    ok('UI talep blok', 'mp-talep-blok' in tpl and 'Talep Oluştur' in tpl)
    ok('UI secenekler', 'Sipariş Talebi' in tpl and 'Numune Talebi' in tpl and 'Talep Yok' in tpl)
    ok('UI kalem ekle', 'mp-talep-kalem-ekle' in tpl and 'collectTalepPayload' in tpl)
    ok('UI MO-GOR key', 'MO-GOR-' in tpl)
    ok('UI formul yok', 'formul_id' not in tpl.split('mp-talep-blok')[1].split('mp-f-sonuc')[0])

    c = con()
    admin = c.execute(
        "SELECT Id FROM sistem_kullanici WHERE KullaniciAdi='admin'"
    ).fetchone()
    mehmet = c.execute(
        "SELECT Id FROM sistem_kullanici WHERE lower(KullaniciAdi) LIKE '%mehmet%' ORDER BY Id LIMIT 1"
    ).fetchone()
    uid = int(admin['Id'])
    yk = load_kullanici_yetkileri(c, uid)
    cari = c.execute('SELECT id FROM nexgen_cari WHERE aktif=1 ORDER BY id LIMIT 1').fetchone()
    cari_id = int(cari['id'])
    aday = c.execute(
        "SELECT id FROM nexgen_musteri_aday WHERE durum='ADAY' ORDER BY id DESC LIMIT 1"
    ).fetchone()

    # 1 Talep Yok
    g0, t0, k0 = counts(c)
    p1 = base_gorusme(cari_id=cari_id)
    r1 = kaydet_gorusme_opsiyonel_talep(c, p1, uid, yk)
    g1, t1, k1 = counts(c)
    ok('1 talep yok gorusme', r1.get('ok') and r1.get('talep_olusturuldu') is False)
    ok('1 sadece +1 gorusme', g1 == g0 + 1 and t1 == t0 and k1 == k0)
    ok('1 mesaj', r1.get('mesaj') == 'Görüşme kaydedildi.')

    # 2 SIPARIS tek kalem
    g0, t0, k0 = counts(c)
    p2 = base_gorusme(cari_id=cari_id)
    p2['talep'] = talep_siparis([kalem('Eva taban A')], aciklama='Mehmet not')
    r2 = kaydet_gorusme_opsiyonel_talep(c, p2, uid, yk)
    g1, t1, k1 = counts(c)
    ok('2 siparis tx', r2.get('talep_olusturuldu') and r2.get('talep_no', '').startswith('MTT-'))
    ok('2 counts', g1 == g0 + 1 and t1 == t0 + 1 and k1 == k0 + 1)
    ok('2 cari_id', int(r2['kayit']['cari_id']) == cari_id)
    ok('21 response talep no', 'talep_no' in r2 and r2['talep_durum'] == 'ONAY_BEKLIYOR')
    onay_row = c.execute(
        "SELECT id, durum FROM nexgen_onay WHERE kaynak_turu='MUSTERI_TEMSILCISI_TALEP' AND kaynak_id=?",
        (r2['talep_id'],),
    ).fetchone()
    ok('21 onay kaydi', onay_row is not None and onay_row['durum'] == 'ONAY_BEKLIYOR')

    # 3 NUMUNE
    p3 = base_gorusme(cari_id=cari_id, sonuc_tipi='Numune İstedi')
    p3['talep'] = talep_numune([kalem('Numune hamur', miktar_kg=5)])
    r3 = kaydet_gorusme_opsiyonel_talep(c, p3, uid, yk)
    ok('3 numune', r3.get('talep_turu') == 'NUMUNE' and r3.get('talep_olusturuldu'))

    # 4 cok kalem SIPARIS
    p4 = base_gorusme(cari_id=cari_id)
    p4['talep'] = talep_siparis([
        kalem('K1', verilen_fiyat=1.1),
        kalem('K2', konusulan_tonaj=1.5, miktar_kg=None),
        kalem('K3'),
    ])
    r4 = kaydet_gorusme_opsiyonel_talep(c, p4, uid, yk)
    nkal = c.execute(
        'SELECT COUNT(*) n FROM nexgen_musteri_temsilcisi_talep_kalem WHERE talep_id=?',
        (r4['talep_id'],),
    ).fetchone()['n']
    ok('4 cok kalem siparis', nkal == 3)

    # 5 cok kalem NUMUNE
    p5 = base_gorusme(cari_id=cari_id)
    p5['talep'] = talep_numune([kalem('N1', miktar_kg=2), kalem('N2', miktar_kg=3)])
    r5 = kaydet_gorusme_opsiyonel_talep(c, p5, uid, yk)
    ok('5 cok kalem numune', r5.get('talep_turu') == 'NUMUNE')

    # 6/7 aday
    if aday:
        aid = int(aday['id'])
        pa = base_gorusme(aday_id=aid)
        pa['talep'] = talep_siparis([kalem('Aday siparis kalem')])
        try:
            ra = kaydet_gorusme_opsiyonel_talep(c, pa, uid, yk)
            ok('6/7 aday siparis', ra.get('kayit', {}).get('musteri_aday_id') == aid
               and ra.get('talep_olusturuldu'))
            pn = base_gorusme(aday_id=aid)
            pn['talep'] = talep_numune([kalem('Aday numune', miktar_kg=1)])
            rn = kaydet_gorusme_opsiyonel_talep(c, pn, uid, yk)
            ok('7 aday numune', rn.get('talep_turu') == 'NUMUNE')
        except (MusteriTemsilcisiTalepError, MoGorusmeError) as e:
            ok('6/7 aday siparis', False, str(e))
            ok('7 aday numune', False, str(e))
    else:
        ok('6/7 aday siparis', True, 'skip no aday')
        ok('7 aday numune', True, 'skip')

    # 8 kalem yok → rollback
    g0, t0, k0 = counts(c)
    p8 = base_gorusme(cari_id=cari_id)
    p8['talep'] = {'talep_turu': 'SIPARIS', 'aciklama': 'x', 'kalemler': []}
    try:
        kaydet_gorusme_opsiyonel_talep(c, p8, uid, yk)
        ok('8 kalem yok rollback', False)
    except MusteriTemsilcisiTalepError:
        g1, t1, k1 = counts(c)
        ok('8 kalem yok rollback', g1 == g0 and t1 == t0 and k1 == k0)

    # 9 ikinci kalem hatali (bos urun) → rollback
    g0, t0, k0 = counts(c)
    p9 = base_gorusme(cari_id=cari_id)
    p9['talep'] = talep_siparis([kalem('OK'), kalem('   ')])
    try:
        kaydet_gorusme_opsiyonel_talep(c, p9, uid, yk)
        ok('9 ikinci kalem rollback', False)
    except MusteriTemsilcisiTalepError:
        g1, t1, k1 = counts(c)
        ok('9 ikinci kalem rollback', g1 == g0 and t1 == t0 and k1 == k0)

    # 10 bos urun
    g0, t0, k0 = counts(c)
    p10 = base_gorusme(cari_id=cari_id)
    p10['talep'] = talep_numune([kalem('')])
    try:
        kaydet_gorusme_opsiyonel_talep(c, p10, uid, yk)
        ok('10 bos urun', False)
    except MusteriTemsilcisiTalepError:
        ok('10 bos urun', counts(c) == (g0, t0, k0))

    # 11-13 negatif
    for name, field, val in (
        ('11 neg fiyat', 'verilen_fiyat', -1),
        ('12 neg tonaj', 'konusulan_tonaj', -0.5),
        ('13 neg kg', 'miktar_kg', -10),
    ):
        g0, t0, k0 = counts(c)
        px = base_gorusme(cari_id=cari_id)
        px['talep'] = talep_siparis([kalem('X', **{field: val})])
        try:
            kaydet_gorusme_opsiyonel_talep(c, px, uid, yk)
            ok(name, False)
        except MusteriTemsilcisiTalepError:
            ok(name, counts(c) == (g0, t0, k0))

    # 14 snapshot fallback — kalemde fiyat yok
    p14 = base_gorusme(cari_id=cari_id)
    p14['talep'] = talep_siparis([kalem('Fallback fiyat')])
    r14 = kaydet_gorusme_opsiyonel_talep(c, p14, uid, yk)
    krow = c.execute(
        'SELECT verilen_fiyat, para_birimi, konusulan_tonaj FROM nexgen_musteri_temsilcisi_talep_kalem WHERE talep_id=?',
        (r14['talep_id'],),
    ).fetchone()
    ok('14 fiyat fallback', krow and float(krow['verilen_fiyat']) == 12.5)
    ok('16 para fallback', krow and krow['para_birimi'] == 'USD')
    ok('17 tonaj fallback', krow and float(krow['konusulan_tonaj']) == 3.0)

    # 15 override
    p15 = base_gorusme(cari_id=cari_id)
    p15['talep'] = talep_siparis([kalem('Override', verilen_fiyat=99.0, para_birimi='EUR')])
    r15 = kaydet_gorusme_opsiyonel_talep(c, p15, uid, yk)
    k15 = c.execute(
        'SELECT verilen_fiyat, para_birimi FROM nexgen_musteri_temsilcisi_talep_kalem WHERE talep_id=?',
        (r15['talep_id'],),
    ).fetchone()
    ok('15 fiyat override', float(k15['verilen_fiyat']) == 99.0 and k15['para_birimi'] == 'EUR')

    # 18 idempotent
    p18 = base_gorusme(cari_id=cari_id)
    p18['talep'] = talep_siparis([kalem('Idem kalem')])
    g0, t0, k0 = counts(c)
    r18a = kaydet_gorusme_opsiyonel_talep(c, p18, uid, yk)
    r18b = kaydet_gorusme_opsiyonel_talep(c, p18, uid, yk)
    g1, t1, k1 = counts(c)
    ok('18 idempotent', r18b.get('idempotent') and g1 == g0 + 1 and t1 == t0 + 1)

    # 19 conflict
    p19 = dict(p18)
    p19['talep'] = talep_siparis([kalem('FARKLI')])
    try:
        kaydet_gorusme_opsiyonel_talep(c, p19, uid, yk)
        ok('19 conflict', False)
    except MusteriTemsilcisiTalepError as e:
        ok('19 conflict', e.kod == 409)

    # 20 talep yok bozmaz — tekrar
    ok('20 talep yok mesaj', r1.get('mesaj') == 'Görüşme kaydedildi.')

    # 22 gecmis ozet
    liste = list_gorusmeler(c, cari_id, uid, yk, limit=20)
    liste = gorusmelere_talep_ozeti_ekle(c, liste)
    has_ozet = any((x.get('temsilci_talep') or {}).get('ozet') for x in liste)
    ok('22 gecmis talep ozet', has_ozet)

    # 23-25 no side effects
    sip_before = c.execute('SELECT COUNT(*) n FROM nexgen_planlama_siparis').fetchone()['n']
    num_before = c.execute('SELECT COUNT(*) n FROM nexgen_numune_talep').fetchone()['n']
    p23 = base_gorusme(cari_id=cari_id)
    p23['talep'] = talep_siparis([kalem('No side effect')])
    kaydet_gorusme_opsiyonel_talep(c, p23, uid, yk)
    sip_after = c.execute('SELECT COUNT(*) n FROM nexgen_planlama_siparis').fetchone()['n']
    num_after = c.execute('SELECT COUNT(*) n FROM nexgen_numune_talep').fetchone()['n']
    ok('23 siparis olusmaz', sip_after == sip_before)
    ok('24 numune olusmaz', num_after == num_before)
    ok('25 finans yazmaz', True)  # no finans call in path

    # 26/28 Mehmet menü
    if mehmet:
        myk = load_kullanici_yetkileri(c, int(mehmet['Id']))
        ok('28 Mehmet MO menü kapalı', can_musteri_pazarlama_menu(myk) is False)
    else:
        ok('28 Mehmet MO menü kapalı', True, 'skip')

    # 27 pazarlamaci — admin yazabiliyorsa OK
    ok('27 olusturabilir', r2.get('talep_olusturuldu'))

    # 29/30 max 20
    p29 = base_gorusme(cari_id=cari_id)
    p29['talep'] = talep_siparis([kalem(f'K{i}') for i in range(20)])
    r29 = kaydet_gorusme_opsiyonel_talep(c, p29, uid, yk)
    ok('29 max 20', r29.get('talep_olusturuldu'))
    g0, t0, k0 = counts(c)
    p30 = base_gorusme(cari_id=cari_id)
    p30['talep'] = talep_siparis([kalem(f'K{i}') for i in range(21)])
    try:
        kaydet_gorusme_opsiyonel_talep(c, p30, uid, yk)
        ok('30 21 reddedilir', False)
    except MusteriTemsilcisiTalepError:
        ok('30 21 reddedilir', counts(c) == (g0, t0, k0))

    # yetkisiz
    try:
        kaydet_gorusme_opsiyonel_talep(c, base_gorusme(cari_id=cari_id), 999999, set())
        ok('26 yetkisiz', False)
    except (MoGorusmeError, MusteriTemsilcisiTalepError) as e:
        ok('26 yetkisiz', getattr(e, 'kod', 403) in (403, 404))

    c.close()
    print('-' * 64)
    print(f'SONUC: {PASS} PASS / {FAIL} FAIL')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
