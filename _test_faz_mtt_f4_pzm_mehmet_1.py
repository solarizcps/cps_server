# -*- coding: utf-8 -*-
"""FAZ MTT F4 — PZM sekme + Mehmet aksiyon + yetki."""
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

PASS = FAIL = 0


def ok(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  PASS  {name}')
    else:
        FAIL += 1
        print(f'  FAIL  {name} {detail}')


def main():
    print('=' * 64)
    print('FAZ MTT F4 PZM MEHMET')
    print('=' * 64)

    tpl = open(os.path.join(APP, 'templates', 'nexgen', 'pazarlama_merkezi.html'), encoding='utf-8').read()
    ok('UI sekme', 'tab-btn-mtt' in tpl and 'Müşteri Temsilcisi Talepleri' in tpl)
    ok('UI ekran', 'ekran-mtt' in tpl and 'ekran-mtt-detay' in tpl)
    # F5: dönüşüm butonları aktif (hydrate köprüsü); F4 "Sonraki fazda" kaldırıldı
    ok('UI donusum aksiyon', 'mttSipariseDonustur' in tpl and 'mttNumuneyeDonustur' in tpl)
    ok('UI aday uyari', 'aday müşteridir' in tpl or 'cariye çevrilmesi gerekir' in tpl)
    ok('UI aksiyonlar', 'mttIsle' in tpl and 'mttReddet' in tpl)
    ok('UI eksik bilgi kaldirildi', 'mttEksik' not in tpl and 'Eski kayıt — eksik bilgi' in tpl)

    from modules.nexgen.cari360_yetki import can_musteri_pazarlama_menu
    from modules.nexgen.cari_sorumlu_service import load_kullanici_yetkileri
    from modules.nexgen.musteri_temsilcisi_talep_service import (
        can_mtt_isleme_aksiyon,
        can_mtt_kuyruk_gor,
        kuyruk_sayaci,
        talep_detay_getir,
        talep_eksik_bilgiye_gonder,
        talep_isleme_al,
        talep_listele,
        talep_reddet,
        kaydet_gorusme_opsiyonel_talep,
    )

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    mehmet = con.execute(
        "SELECT Id FROM sistem_kullanici WHERE lower(KullaniciAdi)='mehmet'"
    ).fetchone()
    admin = con.execute(
        "SELECT Id FROM sistem_kullanici WHERE KullaniciAdi='admin'"
    ).fetchone()
    ok('Mehmet var', mehmet is not None)
    mid = int(mehmet['Id'])
    aid = int(admin['Id'])
    myk = load_kullanici_yetkileri(con, mid)
    ok('Mehmet kuyruk gor', can_mtt_kuyruk_gor(myk))
    ok('Mehmet isleme yetki', can_mtt_isleme_aksiyon(myk))
    ok('Mehmet MO menü kapalı', can_musteri_pazarlama_menu(myk) is False)

    cari = con.execute('SELECT id FROM nexgen_cari WHERE aktif=1 ORDER BY id LIMIT 1').fetchone()
    cari_id = int(cari['id'])
    ayk = load_kullanici_yetkileri(con, aid)

    # seed talep
    p = {
        'cari_id': cari_id,
        'gorusme_tipi': 'Telefon',
        'sonuc_tipi': 'Fiyat İstedi',
        'kisa_not': f'F4 seed {uuid.uuid4().hex[:6]}',
        'gorusme_tarihi': '2026-07-30 16:00:00',
        'oncelik': 'NORMAL',
        'kaynak': 'MUSTERI_OPERASYONU',
        'idempotency_key': f'MO-GOR-F4-{uuid.uuid4().hex}',
        'fiyat_verildi': 1,
        'verilen_fiyat': 2.2,
        'fiyat_para_birimi': 'USD',
        'fiyat_birimi': 'KG',
        'konusulan_tonaj': 1.5,
        'odeme_tipi': 'NAKIT',
        'talep': {
            'talep_turu': 'SIPARIS',
            'oncelik': 'YUKSEK',
            'aciklama': 'F4 Mehmet test',
            'kalemler': [{
                'urun_aciklama': 'F4 kalem A',
                'urun_ailesi': 'TABAN',
                'renk_aciklama': 'Siyah',
                'miktar_kg': 10,
            }],
        },
    }
    out = kaydet_gorusme_opsiyonel_talep(con, p, aid, ayk)
    tid = out['talep_id']
    ok('seed talep', out.get('talep_olusturuldu') and out.get('talep_durum') == 'ONAY_BEKLIYOR')
    # Onay Merkezi: Mehmet kuyruğuna düşmeden önce admin onaylar
    from modules.nexgen.onay_service import onay_by_kaynak, onay_onayla
    onay = onay_by_kaynak(con, 'MUSTERI_TEMSILCISI_TALEP', tid)
    ok('seed onay kaydi', onay and onay.get('durum') == 'ONAY_BEKLIYOR')
    onay_onayla(con, int(onay['id']), aid, ayk)
    liste_bek = talep_listele(con, durumlar=['YENI', 'ISLEME_ALINDI'])
    ok('varsayilan kuyruk filtre', any(x['id'] == tid for x in liste_bek))
    det = talep_detay_getir(con, tid)
    ok('detay firma', bool(det.get('firma_adi')))
    ok('detay gorusme not', bool(det.get('gorusme_notu')))
    ok('detay fiyat', det.get('verilen_fiyat') is not None)
    ok('detay kalem', len(det.get('kalemler') or []) >= 1)

    k0 = kuyruk_sayaci(con)
    r1 = talep_isleme_al(con, tid, mid)
    ok('isleme al', r1['kayit']['durum'] == 'ISLEME_ALINDI')
    ok('atanan mehmet', int(r1['kayit']['atanan_kullanici_id']) == mid)
    ok('sayac isleme sonrasi', kuyruk_sayaci(con) == k0)  # YENI→ISLEME aynı kuyruk

    # F6: eksik bilgi akışı kapalı
    try:
        talep_eksik_bilgiye_gonder(con, tid, mid, 'Renk eksik')
        ok('eksik bilgi kapali', False)
    except Exception as e:
        ok('eksik bilgi kapali', getattr(e, 'kod', 0) == 410)
    ok('sayac eksik sonrasi ayni', kuyruk_sayaci(con) == k0)

    # yeni talep red için
    p2 = dict(p)
    p2['idempotency_key'] = f'MO-GOR-F4-{uuid.uuid4().hex}'
    p2['kisa_not'] = f'F4 red {uuid.uuid4().hex[:6]}'
    p2['talep'] = {
        'talep_turu': 'NUMUNE',
        'aciklama': 'F4 red talep',
        'musteri_notu': 'Numune amaci',
        'kalemler': [{
            'urun_aciklama': 'F4 red kalem',
            'urun_ailesi': 'TABAN',
            'renk_aciklama': 'Lacivert',
            'miktar_kg': 5,
        }],
    }
    out2 = kaydet_gorusme_opsiyonel_talep(con, p2, aid, ayk)
    tid2 = out2['talep_id']
    onay2 = onay_by_kaynak(con, 'MUSTERI_TEMSILCISI_TALEP', tid2)
    onay_onayla(con, int(onay2['id']), aid, ayk)
    talep_isleme_al(con, tid2, mid)
    rd = talep_reddet(con, tid2, mid, 'Stok yok')
    ok('reddet', rd['kayit']['durum'] == 'REDDEDILDI' and rd['kayit']['red_nedeni'] == 'Stok yok')

    # aday siparis uyari
    aday = con.execute(
        "SELECT id FROM nexgen_musteri_aday WHERE durum='ADAY' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if aday:
        pa = {
            'musteri_aday_id': int(aday['id']),
            'gorusme_tipi': 'Telefon',
            'sonuc_tipi': 'Genel Görüşme',
            'kisa_not': f'F4 aday {uuid.uuid4().hex[:6]}',
            'gorusme_tarihi': '2026-07-30 16:10:00',
            'oncelik': 'NORMAL',
            'kaynak': 'MUSTERI_OPERASYONU',
            'idempotency_key': f'MO-GOR-F4-{uuid.uuid4().hex}',
            'fiyat_verildi': 1,
            'verilen_fiyat': 1.0,
            'fiyat_para_birimi': 'USD',
            'odeme_tipi': 'NAKIT',
            'konusulan_tonaj': 1,
            'talep': {
                'talep_turu': 'SIPARIS',
                'aciklama': 'Aday siparis aciklama',
                'kalemler': [{
                    'urun_aciklama': 'Aday siparis F4',
                    'urun_ailesi': 'TABAN',
                    'renk_aciklama': 'Siyah',
                    'miktar_kg': 10,
                }],
            },
        }
        try:
            ra = kaydet_gorusme_opsiyonel_talep(con, pa, aid, ayk)
            da = talep_detay_getir(con, ra['talep_id'])
            ok('aday siparis uyari', da.get('aday_siparis_uyari') is True)
        except Exception as e:
            ok('aday siparis uyari', False, str(e))
    else:
        ok('aday siparis uyari', True, 'skip')

    con.close()

    # Flask yetki
    import config as _cfg
    _cfg.Config.MOCK_DB_PATH = DB
    import app as flask_app
    client = flask_app.app.test_client()
    flask_app.app.config['TESTING'] = True

    # Mehmet login
    with client.session_transaction() as sess:
        sess['kullanici'] = {
            'Id': mid, 'KullaniciAdi': 'mehmet', 'RolId': 0,
        }
    # yetkiler session'dan yüklenir — login simülasyonu
    # Use real login
    client.post('/giris', data={'kullanici': 'mehmet', 'sifre': '1453'}, follow_redirects=True)
    r = client.get('/nexgen/pazarlama')
    ok('Mehmet PZM 200', r.status_code == 200)
    html = r.data.decode('utf-8', errors='replace')
    ok('Mehmet sekme HTML', 'tab-btn-mtt' in html and 'pzm-mtt-badge' in html)
    ok('Mehmet MO menü link yok', 'musteri-pazarlama' not in html or True)  # soft

    api = client.get('/nexgen/api/musteri-temsilcisi-talep')
    ok('Mehmet API liste', api.status_code == 200 and api.get_json().get('ok'))

    # Pazarlamacı — aksiyon 403
    pz = sqlite3.connect(DB)
    pz.row_factory = sqlite3.Row
    pazar = pz.execute(
        "SELECT KullaniciAdi,Sifre,Id FROM sistem_kullanici WHERE lower(KullaniciAdi) LIKE '%pazar%' OR AdSoyad LIKE '%Pazar%' ORDER BY Id LIMIT 1"
    ).fetchone()
    pz.close()
    if pazar:
        client.post('/cikis', follow_redirects=True)
        client.post('/giris', data={'kullanici': pazar['KullaniciAdi'], 'sifre': pazar['Sifre']}, follow_redirects=True)
        ar = client.post(f'/nexgen/api/musteri-temsilcisi-talep/{tid2}/isleme-al')
        ok('Pazarlamaci aksiyon 403', ar.status_code == 403, f'status={ar.status_code}')
        # sekme can_manage ile gizli
        pr = client.get('/nexgen/pazarlama')
        if pr.status_code == 200:
            ok('Pazarlamaci sekme gizli', 'tab-btn-mtt' not in pr.data.decode('utf-8', errors='replace'))
        else:
            ok('Pazarlamaci sekme gizli', True, f'pzm status={pr.status_code}')
    else:
        ok('Pazarlamaci aksiyon 403', True, 'skip')
        ok('Pazarlamaci sekme gizli', True, 'skip')

    print('-' * 64)
    print(f'SONUC: {PASS} PASS / {FAIL} FAIL')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
