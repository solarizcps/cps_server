# -*- coding: utf-8 -*-
"""UI-2 / BE-2 — Çok kalemli pazarlama sipariş testleri (temp DB)."""
import io
import os
import shutil
import sqlite3
import sys
from datetime import date, timedelta

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

SRC_DB = os.path.join(_APP, 'mock_data.db')
TEST_DB = os.path.join(_APP, 'mock_data_ui2_test_tmp.db')

results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def snap(con):
    return {
        'plan': con.execute('SELECT COUNT(*) FROM nexgen_uretim_plan').fetchone()[0],
        'batch': con.execute('SELECT COUNT(*) FROM nexgen_uretim_batch').fetchone()[0],
        'rf': con.execute('SELECT COUNT(*) FROM nexgen_rf_renk').fetchone()[0],
    }


def sess_user():
    return {'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem', 'RolId': 1, 'RolAd': 'admin', 'Aktif': 1}


def v2_payload(con, kalemler, cari_id=None):
    if cari_id is None:
        cari_id = con.execute('SELECT id FROM nexgen_cari WHERE aktif=1 LIMIT 1').fetchone()['id']
    termin = (date.today() + timedelta(days=21)).isoformat()
    return {
        'cari_id': cari_id,
        'siparis_tarihi': date.today().isoformat(),
        'genel_termin_tarihi': termin,
        'genel_not': 'UI2 test',
        'kalemler': kalemler,
    }


def _terlik_formul_id(con):
    row = con.execute(
        "SELECT MIN(f.id) FROM nexgen_formul f WHERE f.kod LIKE '1BA-FL01' AND f.aktif=1"
    ).fetchone()
    return row[0] if row else None


def _rf_kart(con, idx=0):
    rows = con.execute("""
        SELECT id, rf_kod, ad, durum, aktif, cari_id, ilk_talep_cari_id, kaynak_arge_test_id
        FROM nexgen_rf_renk
        WHERE aktif=1 AND durum='ONAYLI' ORDER BY rf_kod, id
    """).fetchall()
    from modules.nexgen.cekirdek_gorunum import yeni_secimde_renk_gosterilebilir_mi
    kartlar = [dict(r) for r in rows if yeni_secimde_renk_gosterilebilir_mi(dict(r))]
    if len(kartlar) <= idx:
        return None
    return kartlar[idx]


def terlik_kalem(con, renk_idx=0, ml=3000, ms=3000, rf_renk_id=None):
    fid = _terlik_formul_id(con)
    rf = _rf_kart(con, renk_idx) if rf_renk_id is None else {'id': rf_renk_id}
    if not fid or not rf:
        return None
    termin = (date.today() + timedelta(days=14)).isoformat()
    return {
        'urun_ailesi': 'TERLIK',
        'formul_id': fid,
        'rf_renk_id': rf['id'],
        'renk_varyant_id': rf['id'],
        'miktar_l': ml,
        'miktar_s': ms,
        'miktar_m': None,
        'termin_tarihi': termin,
    }


def taban_kalem(con):
    row = con.execute("""
        SELECT MIN(f.id) AS formul_id,
               SUM(CASE WHEN uv.boyut='LARGE' THEN 1 ELSE 0 END) AS has_l,
               SUM(CASE WHEN uv.boyut='SMALL' THEN 1 ELSE 0 END) AS has_s
        FROM nexgen_formul f
        JOIN nexgen_renk_varyant rv ON rv.formul_id=f.id AND rv.aktif=1
        JOIN nexgen_uretim_varyant uv ON uv.renk_varyant_id=rv.id AND uv.aktif=1
        WHERE f.aktif=1 AND f.kod LIKE '2BA-%' AND uv.recete_durum='URETIME_ACIK'
          AND uv.boyut IN ('LARGE','SMALL')
    """).fetchone()
    rf = _rf_kart(con, 0)
    if not row or not rf:
        return None
    ml = 2000 if row['has_l'] else 0
    ms = 1000 if row['has_s'] else 0
    if ml <= 0 and ms <= 0:
        ml, ms = 2000, 1000
    termin = (date.today() + timedelta(days=18)).isoformat()
    return {
        'urun_ailesi': 'TABAN',
        'formul_id': row['formul_id'],
        'rf_renk_id': rf['id'],
        'renk_varyant_id': rf['id'],
        'miktar_l': ml or None,
        'miktar_s': ms or None,
        'miktar_m': None,
        'termin_tarihi': termin,
    }


def dokme_kalem(con):
    row = con.execute("""
        SELECT MIN(f.id) AS formul_id
        FROM nexgen_formul f
        JOIN nexgen_renk_varyant rv ON rv.formul_id=f.id AND rv.aktif=1
        JOIN nexgen_uretim_varyant uv ON uv.renk_varyant_id=rv.id AND uv.aktif=1
        WHERE f.aktif=1 AND f.kod LIKE '3BA-%'
          AND uv.recete_durum='URETIME_ACIK'
          AND uv.boyut IN ('MEDIUM','STANDART')
    """).fetchone()
    rf = _rf_kart(con, 0)
    if not row or not rf:
        return None
    termin = (date.today() + timedelta(days=20)).isoformat()
    return {
        'urun_ailesi': 'DOKME',
        'formul_id': row['formul_id'],
        'rf_renk_id': rf['id'],
        'renk_varyant_id': rf['id'],
        'miktar_l': None,
        'miktar_s': None,
        'miktar_m': 5000,
        'termin_tarihi': termin,
    }


print('=' * 65)
print('UI-2 TEST — temp DB')
print('=' * 65)

shutil.copy2(SRC_DB, TEST_DB)
ok('test db kopyalandi', os.path.exists(TEST_DB), TEST_DB)

import app as flask_app
import modules.nexgen.routes as nx_routes
from modules.nexgen.pzm_siparis_write import pzm_v2_taslak_kaydet, PzmWriteError
from modules.nexgen.pzm_siparis_read import pzm_siparis_oku

nx_routes.DB_PATH = TEST_DB
_app = flask_app.app
_app.config['TESTING'] = True

con = sqlite3.connect(TEST_DB)
con.row_factory = sqlite3.Row
before = snap(con)

# migration 107 if needed
import importlib.util
m107 = os.path.join(_APP, 'migrations', '107_nexgen_planlama_siparis_kalem.py')
if os.path.exists(m107):
    spec = importlib.util.spec_from_file_location('m107', m107)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path=TEST_DB)

t1 = terlik_kalem(con)
ok('setup terlik kalem', t1 is not None)

created_ids = []

with _app.test_client() as c:
    with c.session_transaction() as sess:
        sess['kullanici'] = sess_user()
        sess['kullanici_tip'] = 'sistem'

    # 1 tek kalem TERLIK
    r1 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [t1]))
    d1 = r1.get_json() or {}
    ok('1 tek kalem TERLIK', r1.status_code == 200 and d1.get('ok'), d1.get('siparis_no'))
    created_ids.append(d1.get('talep_id'))

    # 2 iki renk TERLIK
    t1b = terlik_kalem(con, renk_idx=1, ml=4000, ms=2000)
    if t1b:
        r2 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [t1, t1b]))
        d2 = r2.get_json() or {}
        ok('2 iki renk TERLIK', d2.get('ok') and d2.get('kalem_sayisi') == 2)
        created_ids.append(d2.get('talep_id'))
    else:
        ok('2 iki renk TERLIK', True, 'atlandi')

    # 3 TERLIK + TABAN
    tb = taban_kalem(con)
    if tb:
        r3 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [t1, tb]))
        d3 = r3.get_json() or {}
        ok('3 TERLIK+TABAN', d3.get('ok') and d3.get('kalem_sayisi') == 2)
        created_ids.append(d3.get('talep_id'))
    else:
        ok('3 TERLIK+TABAN', True, 'taban yok-atlandi')

    # 4 TERLIK + DOKME
    dk = dokme_kalem(con)
    if dk:
        r4 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [t1, dk]))
        d4 = r4.get_json() or {}
        ok('4 TERLIK+DOKME', d4.get('ok') and d4.get('kalem_sayisi') == 2)
        created_ids.append(d4.get('talep_id'))
    else:
        ok('4 TERLIK+DOKME', True, 'dokme yok-atlandi')

    # 5 L/S esit
    r5 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [terlik_kalem(con, ml=3000, ms=3000)]))
    ok('5 L/S esit', (r5.get_json() or {}).get('ok'))

    # 6 L/S farkli
    r6 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [terlik_kalem(con, ml=4000, ms=2000)]))
    ok('6 L/S farkli', (r6.get_json() or {}).get('ok'))

    # 7 yalniz L
    r7 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [terlik_kalem(con, ml=5000, ms=0)]))
    ok('7 yalniz L', (r7.get_json() or {}).get('ok'))

    # 8 yalniz S
    r8 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [terlik_kalem(con, ml=0, ms=5000)]))
    ok('8 yalniz S', (r8.get_json() or {}).get('ok'))

    # 9 DOKME yalniz M
    if dk:
        r9 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [dk]))
        ok('9 DOKME yalniz M', (r9.get_json() or {}).get('ok'))
    else:
        ok('9 DOKME yalniz M', True, 'atlandi')

    # 10 DOKME + L/S reddedilir
    if dk:
        bad = dict(dk)
        bad['miktar_l'] = 100
        r10 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [bad]))
        ok('10 DOKME+L reddedilir', r10.status_code == 400)
    else:
        ok('10 DOKME+L reddedilir', True, 'atlandi')

    # 11 negatif
    neg = terlik_kalem(con, ml=1000, ms=0)
    if neg:
        neg['miktar_l'] = -1
        r11 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [neg]))
        ok('11 negatif reddedilir', r11.status_code == 400)
    else:
        ok('11 negatif reddedilir', True, 'atlandi')

    # 12 sifir kalem
    r12 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, []))
    ok('12 sifir kalem reddedilir', r12.status_code == 400)

    # 13 gecersiz formul
    badf = terlik_kalem(con, ml=1000, ms=0)
    if badf:
        badf['formul_id'] = 999999
        r13 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [badf]))
        ok('13 gecersiz formul reddedilir', r13.status_code == 400)
    else:
        ok('13 gecersiz formul reddedilir', True, 'atlandi')

    # 14 legacy formul
    leg = con.execute("SELECT id FROM nexgen_formul WHERE kod='810' AND aktif=1 LIMIT 1").fetchone()
    if leg and terlik_kalem(con, ml=1000, ms=0):
        badl = terlik_kalem(con, ml=1000, ms=0)
        badl['formul_id'] = leg['id']
        r14 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [badl]))
        ok('14 legacy formul reddedilir', r14.status_code == 400)
    else:
        ok('14 legacy formul reddedilir', True, '810 yok')

    # 15 gecersiz renk
    badr = terlik_kalem(con, ml=1000, ms=0)
    if badr:
        badr['rf_renk_id'] = 999999
        badr['renk_varyant_id'] = 999999
        r15 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [badr]))
        ok('15 gecersiz renk reddedilir', r15.status_code == 400)
    else:
        ok('15 gecersiz renk reddedilir', True, 'atlandi')

    # 16 rollback — ikinci kalem hatali
    hdr_cnt_before = con.execute('SELECT COUNT(*) FROM nexgen_planlama_siparis').fetchone()[0]
    kalem_cnt_before = con.execute('SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem').fetchone()[0]
    bad2 = [t1, terlik_kalem(con, ml=500, ms=0)]
    if bad2[0] and bad2[1]:
        bad2[1]['formul_id'] = 999999
        try:
            pzm_v2_taslak_kaydet(con, v2_payload(con, bad2), 1)
            ok('16 rollback', False, 'exception bekleniyordu')
        except PzmWriteError:
            ok('16 rollback', True)
    else:
        ok('16 rollback', True, 'atlandi')
    hdr_cnt_after = con.execute('SELECT COUNT(*) FROM nexgen_planlama_siparis').fetchone()[0]
    kalem_cnt_after = con.execute('SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem').fetchone()[0]
    ok('16 header artmadi', hdr_cnt_after == hdr_cnt_before, f'{hdr_cnt_before}->{hdr_cnt_after}')
    ok('16 kalem artmadi', kalem_cnt_after == kalem_cnt_before)

    # 17-20 liste/detay
    r17 = c.get('/nexgen/api/pazarlama/talepler')
    liste = (r17.get_json() or {}).get('liste') or []
    ok('17 liste dolu', len(liste) > 0, f'n={len(liste)}')
    son = liste[0] if liste else {}
    ok('18 toplam_kg', float(son.get('toplam_kg') or 0) > 0, str(son.get('toplam_kg')))
    ok('19 en_yakin_termin', bool(son.get('en_yakin_termin')), son.get('en_yakin_termin'))
    if son.get('id'):
        okuma = pzm_siparis_oku(con, son['id'])
        ok('20 detay kalemler', len(okuma.get('kalemler') or []) >= 1)

    # 21 legacy V1 — sanal kalem
    import json
    from modules.nexgen.pzm_siparis_read import pzm_siparis_kalemleri_getir
    prefix = '__PZM_V1__'
    payload = {'v':1,'urun_ailesi':'TERLIK','formul_id':1,'formul_ad':'T','renk_varyant_id':1,
               'renk_ad':'R','boyut_miktar':{'LARGE':100},'termin_tarihi':date.today().isoformat()}
    ref = prefix + json.dumps(payload, separators=(',',':'))
    con.execute("INSERT INTO nexgen_planlama_siparis (siparis_no,cari_id,cari_unvan,termin_tarihi,talep_referansi,durum) VALUES ('PZM-LEG-UI2',1,'T',?,?,'TASLAK')", (date.today().isoformat(), ref))
    leg_id = con.execute('SELECT last_insert_rowid()').fetchone()[0]
    con.commit()
    leg_k = pzm_siparis_kalemleri_getir(con, leg_id)
    ok('21 legacy V1 acilir', len(leg_k) == 1)
    con.execute('DELETE FROM nexgen_planlama_siparis WHERE id=?', (leg_id,))
    con.commit()

    # 22 sayfa 200
    r22 = c.get('/nexgen/pazarlama')
    ok('22 sayfa HTTP 200', r22.status_code == 200)

    # 26-30 Faz-2: renk kartı / RF ayrımı
    tb = taban_kalem(con)
    if tb:
        r26 = c.get(
            f'/nexgen/api/pazarlama/renk-boyut?formul_id={tb["formul_id"]}&urun_ailesi=TABAN'
        )
        j26 = r26.get_json() or {}
        renkler = j26.get('renkler') or []
        ok('26 TABAN renk dropdown dolu', r26.status_code == 200 and len(renkler) > 0, f'n={len(renkler)}')
        etiket = (renkler[0].get('renk_ad') or '') if renkler else ''
        rf_kod = (renkler[0].get('rf_kod') or '') if renkler else ''
        parts = etiket.split(' — ', 1)
        ok('27 renk etiket format', len(parts) == 2 and parts[0] in rf_kod, etiket[:40])
        ok('27b rf_uygunluk bilgi', (not renkler[0].get('rf_uygunluk_var')) if renkler else True)

        r28 = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [tb]))
        d28 = r28.get_json() or {}
        taban_tid = d28.get('talep_id')
        ok('28 TABAN taslak RF olmadan', d28.get('ok'), d28.get('siparis_no'))
        created_ids.append(taban_tid)

        plan_before_taban = con.execute('SELECT COUNT(*) FROM nexgen_uretim_plan').fetchone()[0]
        durum_before = con.execute(
            'SELECT durum FROM nexgen_planlama_siparis WHERE id=?', (taban_tid,)
        ).fetchone()[0] if taban_tid else None
        if taban_tid:
            r29 = c.post('/nexgen/api/pazarlama/mpr-olustur', json={'talep_id': taban_tid})
            d29 = r29.get_json() or {}
            plan_after_taban = con.execute('SELECT COUNT(*) FROM nexgen_uretim_plan').fetchone()[0]
            durum_after = con.execute(
                'SELECT durum FROM nexgen_planlama_siparis WHERE id=?', (taban_tid,)
            ).fetchone()[0]
            ok('29 TABAN MRP rf_eksik', r29.status_code == 400 and d29.get('rf_eksik'), d29.get('hata', '')[:80])
            ok('29 durum korundu', durum_after == durum_before == 'TASLAK')
            ok('29 plan artmadi', plan_after_taban == plan_before_taban)
        else:
            ok('29 TABAN MRP rf_eksik', False, 'taslak yok')
            ok('29 durum korundu', False)
            ok('29 plan artmadi', False)
    else:
        ok('26 TABAN renk dropdown dolu', True, 'taban yok-atlandi')
        ok('27 renk etiket format', True, 'atlandi')
        ok('27b rf_uygunluk bilgi', True, 'atlandi')
        ok('28 TABAN taslak RF olmadan', True, 'atlandi')
        ok('29 TABAN MRP rf_eksik', True, 'atlandi')
        ok('29 durum korundu', True, 'atlandi')
        ok('29 plan artmadi', True, 'atlandi')

    rf28 = con.execute(
        "SELECT u.rf_renk_id FROM nexgen_rf_formul_uygunluk u "
        "JOIN nexgen_formul f ON f.id=u.formul_id "
        "WHERE u.aktif=1 AND f.kod LIKE '1BA-FL01' LIMIT 1"
    ).fetchone()
    if rf28:
        trf = terlik_kalem(con, rf_renk_id=rf28['rf_renk_id'], ml=2000, ms=2000)
        r30a = c.post('/nexgen/api/pazarlama/taslak-kaydet', json=v2_payload(con, [trf]))
        d30a = r30a.get_json() or {}
        terlik_tid = d30a.get('talep_id')
        created_ids.append(terlik_tid)
        plan_before_t = con.execute('SELECT COUNT(*) FROM nexgen_uretim_plan').fetchone()[0]
        if terlik_tid:
            r30 = c.post('/nexgen/api/pazarlama/mpr-olustur', json={'talep_id': terlik_tid})
            d30 = r30.get_json() or {}
            plan_after_t = con.execute('SELECT COUNT(*) FROM nexgen_uretim_plan').fetchone()[0]
            ok('30 TERLIK MRP basarili', d30.get('ok') and d30.get('plan_sayisi', 0) >= 1, d30.get('siparis_no'))
            ok('30 plan artti', plan_after_t > plan_before_t, f'{plan_before_t}->{plan_after_t}')
            # MRP planlarini temizle (test DB)
            if d30.get('ok'):
                for p in d30.get('planlar') or []:
                    pid = p.get('plan_id')
                    if pid:
                        con.execute('DELETE FROM nexgen_uretim_plan_boyut WHERE plan_id=?', (pid,))
                        con.execute('DELETE FROM nexgen_uretim_plan WHERE id=?', (pid,))
                con.execute(
                    "UPDATE nexgen_planlama_siparis SET durum='TASLAK' WHERE id=?",
                    (terlik_tid,),
                )
                con.commit()
        else:
            ok('30 TERLIK MRP basarili', False, 'taslak yok')
            ok('30 plan artti', False)
    else:
        ok('30 TERLIK MRP basarili', True, 'RF uygunluk yok-atlandi')
        ok('30 plan artti', True, 'atlandi')

after = snap(con)
ok('23 plan degismedi', after['plan'] == before['plan'])
ok('24 batch degismedi', after['batch'] == before['batch'])
ok('25 rf degismedi', after['rf'] == before['rf'])

# temizlik — test siparisleri sil
for tid in created_ids:
    if tid:
        con.execute('DELETE FROM nexgen_planlama_siparis_kalem WHERE planlama_siparis_id=?', (tid,))
        con.execute('DELETE FROM nexgen_planlama_siparis WHERE id=?', (tid,))
con.execute("DELETE FROM nexgen_planlama_siparis WHERE siparis_no LIKE 'PZM-%' AND talep_referansi LIKE '__PZM_V2__%'")
con.commit()
con.close()
try:
    os.remove(TEST_DB)
except OSError:
    pass

print('\n' + '=' * 65)
passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f'SONUC: {passed} PASS / {failed} FAIL')
print('Test DB silindi — gercek DB korundu')
print('Commit: EDILMEDI')
print('=' * 65)
sys.exit(0 if failed == 0 else 1)
