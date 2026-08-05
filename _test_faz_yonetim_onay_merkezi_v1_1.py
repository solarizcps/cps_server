# -*- coding: utf-8 -*-
"""FAZ-YONETIM-ONAY-MERKEZI-V1-OMURGA — servis + yetki + Mehmet kuyruk."""
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
LIVE_DB = os.path.join(APP, 'mock_data.db')
DB = os.environ.get('CPS_ONAY_TEST_DB', '').strip()
if not DB or os.path.normcase(os.path.abspath(DB)) == os.path.normcase(os.path.abspath(LIVE_DB)):
    raise RuntimeError('CPS_ONAY_TEST_DB zorunlu ve ana mock_data.db disinda olmalidir')

from modules.nexgen.cari_sorumlu_service import load_kullanici_yetkileri  # noqa: E402
from modules.nexgen.musteri_temsilcisi_talep_service import (  # noqa: E402
    kaydet_gorusme_opsiyonel_talep,
    talep_listele,
)
from modules.nexgen.onay_service import (  # noqa: E402
    OnayError,
    can_onay_karar,
    can_onay_liste_gor,
    onay_by_kaynak,
    onay_listele,
    onay_olustur_mtt,
    onay_onayla,
    onay_reddet,
)

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


def base_payload(cari_id, **extra):
    p = {
        'cari_id': int(cari_id),
        'gorusme_tipi': 'Telefon',
        'sonuc_tipi': 'Fiyat İstedi',
        'kisa_not': f'OnayMerkezi {uuid.uuid4().hex[:8]}',
        'gorusme_tarihi': '2026-07-30 17:00:00',
        'oncelik': 'NORMAL',
        'kaynak': 'MUSTERI_OPERASYONU',
        'idempotency_key': f'MO-GOR-ONY-{uuid.uuid4().hex}',
        'fiyat_verildi': 1,
        'verilen_fiyat': 5.5,
        'fiyat_para_birimi': 'USD',
        'fiyat_birimi': 'KG',
        'konusulan_tonaj': 2.0,
        'odeme_tipi': 'NAKIT',
        'talep': {
            'talep_turu': 'SIPARIS',
            'oncelik': 'NORMAL',
            'aciklama': 'Onay merkezi test aciklama',
            'kalemler': [{
                'urun_aciklama': 'Onay kalem Eva',
                'urun_ailesi': 'TABAN',
                'renk_aciklama': 'Siyah',
                'miktar_kg': 25,
            }],
        },
    }
    p.update(extra)
    return p


def main():
    print('=' * 60)
    print('FAZ-YONETIM-ONAY-MERKEZI-V1')
    print('=' * 60)
    c = con()
    ok('tablo nexgen_onay', bool(c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexgen_onay'"
    ).fetchone()))
    sql = c.execute(
        "SELECT sql FROM sqlite_master WHERE name='nexgen_musteri_temsilcisi_talep'"
    ).fetchone()[0]
    ok('MTT CHECK ONAY_BEKLIYOR', 'ONAY_BEKLIYOR' in sql)

    admin = c.execute("SELECT Id FROM sistem_kullanici WHERE KullaniciAdi='admin'").fetchone()
    mehmet = c.execute(
        "SELECT Id FROM sistem_kullanici WHERE lower(KullaniciAdi)='mehmet' LIMIT 1"
    ).fetchone()
    pazar = c.execute(
        "SELECT Id FROM sistem_kullanici WHERE lower(KullaniciAdi) LIKE '%pazar%' "
        "OR AdSoyad LIKE '%Pazar%' ORDER BY Id LIMIT 1"
    ).fetchone()
    cari = c.execute('SELECT id FROM nexgen_cari WHERE COALESCE(aktif,1)=1 ORDER BY id LIMIT 1').fetchone()
    ok('kullanicilar', bool(admin and mehmet and cari))
    aid = int(admin['Id'])
    mid = int(mehmet['Id'])
    ayk = load_kullanici_yetkileri(c, aid)
    myk = load_kullanici_yetkileri(c, mid)
    pyk = load_kullanici_yetkileri(c, int(pazar['Id'])) if pazar else set()

    ok('admin onay karar', can_onay_karar(ayk))
    ok('admin onay liste', can_onay_liste_gor(ayk))
    ok('mehmet onay karar YOK', not can_onay_karar(myk))
    ok('pazarlamaci onay karar YOK', not can_onay_karar(pyk) if pazar else True)

    # Yeni MTT → görüşme + MTT + onay aynı TX
    g0 = c.execute('SELECT COUNT(*) n FROM musteri_operasyon_gorusme').fetchone()['n']
    t0 = c.execute('SELECT COUNT(*) n FROM nexgen_musteri_temsilcisi_talep').fetchone()['n']
    o0 = c.execute('SELECT COUNT(*) n FROM nexgen_onay').fetchone()['n']
    out = kaydet_gorusme_opsiyonel_talep(c, base_payload(cari['id']), aid, ayk)
    tid = out['talep_id']
    ok('create talep', out.get('talep_olusturuldu') and out.get('talep_durum') == 'ONAY_BEKLIYOR')
    g1 = c.execute('SELECT COUNT(*) n FROM musteri_operasyon_gorusme').fetchone()['n']
    t1 = c.execute('SELECT COUNT(*) n FROM nexgen_musteri_temsilcisi_talep').fetchone()['n']
    o1 = c.execute('SELECT COUNT(*) n FROM nexgen_onay').fetchone()['n']
    ok('tx counts +1', g1 == g0 + 1 and t1 == t0 + 1 and o1 == o0 + 1)
    onay = onay_by_kaynak(c, 'MUSTERI_TEMSILCISI_TALEP', tid)
    ok('onay kaydi', onay and onay['durum'] == 'ONAY_BEKLIYOR' and str(onay['onay_no']).startswith('ONY-'))

    # Mehmet ONAY_BEKLIYOR görmez
    mehmet_liste = talep_listele(c, durumlar=['YENI', 'ISLEME_ALINDI', 'KISMEN_NUMUNEYE_DONUSTU'])
    ok('mehmet bekleyen gormez', not any(x['id'] == tid for x in mehmet_liste))

    # Duplicate: aynı kaynak için ikinci çağrı mevcut kaydı döner (UNIQUE)
    dup = onay_olustur_mtt(c, tid, aid, f'DUP-{uuid.uuid4().hex}', commit=True)
    ok('duplicate engeli', dup.get('idempotent') is True and int(dup['kayit']['id']) == int(onay['id']))
    o_after_dup = c.execute('SELECT COUNT(*) n FROM nexgen_onay').fetchone()['n']
    ok('duplicate yeni satir yok', o_after_dup == o1)

    # Mehmet onaylayamaz
    try:
        onay_onayla(c, int(onay['id']), mid, myk)
        ok('mehmet onay 403', False)
    except OnayError as e:
        ok('mehmet onay 403', e.kod == 403)

    # Admin onay → YENI → Mehmet görür
    r_ok = onay_onayla(c, int(onay['id']), aid, ayk)
    ok('admin onay', r_ok['kayit']['durum'] == 'ONAYLANDI')
    mtt = c.execute('SELECT durum FROM nexgen_musteri_temsilcisi_talep WHERE id=?', (tid,)).fetchone()
    ok('mtt YENI', mtt['durum'] == 'YENI')
    mehmet_liste2 = talep_listele(c, durumlar=['YENI', 'ISLEME_ALINDI', 'KISMEN_NUMUNEYE_DONUSTU'])
    ok('mehmet onay sonrasi gorur', any(x['id'] == tid for x in mehmet_liste2))

    # Red senaryosu
    out2 = kaydet_gorusme_opsiyonel_talep(c, base_payload(cari['id']), aid, ayk)
    tid2 = out2['talep_id']
    onay2 = onay_by_kaynak(c, 'MUSTERI_TEMSILCISI_TALEP', tid2)
    try:
        onay_reddet(c, int(onay2['id']), aid, '', ayk)
        ok('red neden zorunlu', False)
    except OnayError as e:
        ok('red neden zorunlu', e.kod == 400)
    r_red = onay_reddet(c, int(onay2['id']), aid, 'Fiyat uygun degil', ayk)
    ok('admin red', r_red['kayit']['durum'] == 'REDDEDILDI')
    mtt2 = c.execute(
        'SELECT durum, red_nedeni FROM nexgen_musteri_temsilcisi_talep WHERE id=?', (tid2,)
    ).fetchone()
    ok('mtt REDDEDILDI', mtt2['durum'] == 'REDDEDILDI' and mtt2['red_nedeni'] == 'Fiyat uygun degil')
    mehmet_liste3 = talep_listele(c, durumlar=['YENI', 'ISLEME_ALINDI', 'KISMEN_NUMUNEYE_DONUSTU'])
    ok('mehmet red gormez', not any(x['id'] == tid2 for x in mehmet_liste3))

    # Rollback: onay tablosu geçici kaldırılınca görüşme+MTT de yazılmaz
    g_b = c.execute('SELECT COUNT(*) n FROM musteri_operasyon_gorusme').fetchone()['n']
    t_b = c.execute('SELECT COUNT(*) n FROM nexgen_musteri_temsilcisi_talep').fetchone()['n']
    o_b = c.execute('SELECT COUNT(*) n FROM nexgen_onay').fetchone()['n']
    c.execute('ALTER TABLE nexgen_onay RENAME TO nexgen_onay__rb_bak')
    try:
        kaydet_gorusme_opsiyonel_talep(c, base_payload(cari['id']), aid, ayk)
        ok('rollback onay hatasi', False)
    except Exception:
        ok('rollback onay hatasi', True)
    finally:
        c.execute('ALTER TABLE nexgen_onay__rb_bak RENAME TO nexgen_onay')
    ok('rollback counts ayni', (
        c.execute('SELECT COUNT(*) n FROM musteri_operasyon_gorusme').fetchone()['n'] == g_b
        and c.execute('SELECT COUNT(*) n FROM nexgen_musteri_temsilcisi_talep').fetchone()['n'] == t_b
        and c.execute('SELECT COUNT(*) n FROM nexgen_onay').fetchone()['n'] == o_b
    ))

    # Liste API enrich
    liste = onay_listele(c, durum='ONAYLANDI', kaynak_turu='MUSTERI_TEMSILCISI_TALEP', limit=20)
    ok('liste onaylandi', any(x.get('kaynak_id') == tid for x in liste))

    # HTTP yetki
    admin_row = c.execute(
        "SELECT KullaniciAdi, Sifre FROM sistem_kullanici WHERE KullaniciAdi='admin'"
    ).fetchone()
    from config import Config
    Config.MOCK_DB_PATH = DB
    import modules.nexgen.routes as nexgen_routes
    nexgen_routes.DB_PATH = DB
    from app import app
    client = app.test_client()
    client.post('/giris', data={'kullanici': 'mehmet', 'sifre': '1453'}, follow_redirects=True)
    r = client.get('/nexgen/api/yonetim/onaylar')
    ok('mehmet API 403', r.status_code == 403)
    client.post(
        '/giris',
        data={'kullanici': admin_row['KullaniciAdi'], 'sifre': admin_row['Sifre'] or '1453'},
        follow_redirects=True,
    )
    r = client.get('/nexgen/api/yonetim/onaylar?durum=ONAY_BEKLIYOR')
    d = r.get_json() or {}
    ok('admin API liste', r.status_code == 200 and d.get('ok'), str(r.status_code))
    r = client.get('/nexgen/yonetim', follow_redirects=True)
    html = r.get_data(as_text=True)
    ok('yonetim sekme HTML', 'Onay Merkezi' in html and 'ngsd-sekme-onay' in html, str(r.status_code))
    ok('yonetim JS onayla', 'onayOnayla' in html and 'onayReddet' in html)

    c.close()
    print('-' * 60)
    print(f'SONUC: {PASS} PASS / {FAIL} FAIL')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
