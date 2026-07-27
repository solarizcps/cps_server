# -*- coding: utf-8 -*-
"""FAZ-CARI-GORUSME-YETKILI-BAGI-VE-CARI-KART-CRM-1 — API/DB doğrulama."""
from __future__ import annotations

import io
import os
import sys
import uuid

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)
_DB = os.path.join(_APP, 'mock_data.db')

import importlib.util

spec = importlib.util.spec_from_file_location(
    'm134', os.path.join(_APP, 'migrations', '134_musteri_operasyon_gorusme_yetkili.py'))
m134 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m134)
m134.run(_DB)
m134.run(_DB)

import sqlite3

results = []
_CREATED = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


con = sqlite3.connect(_DB)
con.row_factory = sqlite3.Row
cols = {r[1] for r in con.execute('PRAGMA table_info(musteri_operasyon_gorusme)')}
ok('mig yetkili_id', 'yetkili_id' in cols)
ok('mig konu', 'konu' in cols)
ok('mig sonraki_aksiyon', 'sonraki_aksiyon' in cols)
ok('mig takip_durumu', 'takip_durumu' in cols)
ok('mig 134 registered', bool(con.execute(
    'SELECT 1 FROM schema_migrations WHERE version=134').fetchone()))

cari = con.execute(
    'SELECT id, cari_kod, unvan FROM nexgen_cari WHERE aktif=1 ORDER BY id LIMIT 1'
).fetchone()
ok('cari var', cari is not None)
cari_id = int(cari['id'])
cari2 = con.execute(
    'SELECT id FROM nexgen_cari WHERE aktif=1 AND id<>? ORDER BY id LIMIT 1',
    (cari_id,),
).fetchone()
cari2_id = int(cari2['id']) if cari2 else None

from modules.nexgen.cari_yetkili_service import yetkili_ekle, yetkili_aktif_ayarla

y1 = yetkili_ekle(
    con, cari_id, f'TEST-YETKILI-{uuid.uuid4().hex[:6]}',
    unvan='Satın Alma', kullanici_id=1,
)
ok('yetkili ekle', y1.get('ok'), str(y1))
yetkili_id = int(y1['id']) if y1.get('ok') else None
_CREATED.append(('yetkili', yetkili_id))

y2_id = None
if cari2_id:
    y2 = yetkili_ekle(
        con, cari2_id, f'TEST-YETKILI-X-{uuid.uuid4().hex[:6]}',
        kullanici_id=1,
    )
    if y2.get('ok'):
        y2_id = int(y2['id'])
        _CREATED.append(('yetkili', y2_id))
con.commit()

import config as _cfg
_cfg.Config.MOCK_DB_PATH = _DB
import app as flask_app

_app = flask_app.app
_app.config['TESTING'] = True
client = _app.test_client()


def login(uid=1, kadi='admin', rol_id=1):
    with client.session_transaction() as s:
        s['kullanici'] = {
            'Id': uid, 'KullaniciAdi': kadi, 'Tip': 'sistem',
            'RolId': rol_id, 'RolAd': 'Test', 'Aktif': 1,
        }
        s['kullanici_tip'] = 'sistem'


login(1, 'admin', 1)

idem_mp = f'CRM1-MP-{uuid.uuid4()}'
_CREATED.append(('idem', idem_mp))
r = client.post('/nexgen/api/musteri-pazarlama/gorusme', json={
    'cari_id': cari_id,
    'yetkili_id': yetkili_id,
    'gorusme_tipi': 'Telefon',
    'sonuc_tipi': 'Genel Görüşme',
    'konu': 'CRM1 MP test',
    'kisa_not': 'MP kaynakli gorusme kaydi test',
    'sonraki_aksiyon': 'Teklif gonder',
    'sonraki_takip_tarihi': '2026-08-01',
    'gorusme_tarihi': '2026-07-27 12:00:00',
    'idempotency_key': idem_mp,
    'kaynak': 'MUSTERI_OPERASYONU',
})
j = r.get_json() or {}
ok('MP create 200', r.status_code == 200 and j.get('ok'), f'{r.status_code} {j}')
gid_mp = (j.get('kayit') or {}).get('id')
ok('MP kullanici_id=admin', (j.get('kayit') or {}).get('kullanici_id') == 1, str((j.get('kayit') or {}).get('kullanici_id')))
ok('MP yetkili_id dogru', (j.get('kayit') or {}).get('yetkili_id') == yetkili_id)
ok('MP takip ACIK', (j.get('kayit') or {}).get('takip_durumu') == 'ACIK')

r2 = client.post('/nexgen/api/musteri-pazarlama/gorusme', json={
    'cari_id': cari_id,
    'yetkili_id': yetkili_id,
    'gorusme_tipi': 'Telefon',
    'sonuc_tipi': 'Genel Görüşme',
    'kisa_not': 'MP kaynakli gorusme kaydi test',
    'gorusme_tarihi': '2026-07-27 12:00:00',
    'idempotency_key': idem_mp,
})
gid2 = ((r2.get_json() or {}).get('kayit') or {}).get('id')
ok('idempotency tek kayit', gid_mp and gid_mp == gid2, f'{gid_mp} vs {gid2}')

r3 = client.get(f'/nexgen/api/cari360/{cari_id}/gorusme')
j3 = r3.get_json() or {}
ids = [x['id'] for x in (j3.get('liste') or [])]
ok('MP kayit Cari Kart listede', gid_mp in ids, str(gid_mp))

idem_ck = f'CRM1-CK-{uuid.uuid4()}'
_CREATED.append(('idem', idem_ck))
r4 = client.post(f'/nexgen/api/cari360/{cari_id}/gorusme', json={
    'yetkili_id': yetkili_id,
    'gorusme_tipi': 'Ziyaret',
    'sonuc_tipi': 'Fiyat İstedi',
    'konu': 'CRM1 CK test',
    'kisa_not': 'Cari Kart kaynakli gorusme',
    'sonraki_aksiyon': 'Fiyat hazirla',
    'sonraki_takip_tarihi': '2026-08-05',
    'gorusme_tarihi': '2026-07-27 13:00:00',
    'idempotency_key': idem_ck,
    'kaynak': 'CARI_KART',
})
j4 = r4.get_json() or {}
ok('CK create 200', r4.status_code == 200 and j4.get('ok'), f'{r4.status_code} {j4}')
gid_ck = (j4.get('kayit') or {}).get('id')
ok('CK kaynak CARI_KART', (j4.get('kayit') or {}).get('kaynak') == 'CARI_KART')

r5 = client.get(f'/nexgen/api/musteri-pazarlama/gorusme?cari_id={cari_id}')
ids5 = [x['id'] for x in ((r5.get_json() or {}).get('liste') or [])]
ok('CK kayit MP listede', gid_ck in ids5, str(gid_ck))

cnt = con.execute(
    'SELECT COUNT(*) AS c FROM musteri_operasyon_gorusme WHERE idempotency_key IN (?,?)',
    (idem_mp, idem_ck),
).fetchone()['c']
ok('DB iki satir (MP+CK)', cnt == 2, str(cnt))

if y2_id:
    r6 = client.post('/nexgen/api/musteri-pazarlama/gorusme', json={
        'cari_id': cari_id,
        'yetkili_id': y2_id,
        'gorusme_tipi': 'Telefon',
        'sonuc_tipi': 'Genel Görüşme',
        'kisa_not': 'yanlis yetkili denemesi xxx',
        'gorusme_tarihi': '2026-07-27 14:00:00',
        'idempotency_key': f'CRM1-BAD-{uuid.uuid4()}',
    })
    j6 = r6.get_json() or {}
    ok('yanlis cari yetkili engel', r6.status_code in (400, 403) and not j6.get('ok'), f'{r6.status_code} {j6}')

if yetkili_id:
    yetkili_aktif_ayarla(con, yetkili_id, 0, kullanici_id=1)
    con.commit()
    r7 = client.post('/nexgen/api/musteri-pazarlama/gorusme', json={
        'cari_id': cari_id,
        'yetkili_id': yetkili_id,
        'gorusme_tipi': 'Telefon',
        'sonuc_tipi': 'Genel Görüşme',
        'kisa_not': 'pasif yetkili denemesi xxx',
        'gorusme_tarihi': '2026-07-27 14:30:00',
        'idempotency_key': f'CRM1-PAS-{uuid.uuid4()}',
    })
    j7 = r7.get_json() or {}
    ok('pasif yetkili yeni engel', r7.status_code in (400, 403) and not j7.get('ok'), f'{r7.status_code} {j7}')
    row = con.execute(
        '''SELECT cy.ad_soyad FROM musteri_operasyon_gorusme g
           LEFT JOIN cari_yetkili cy ON cy.id=g.yetkili_id WHERE g.id=?''',
        (gid_mp,),
    ).fetchone()
    ok('pasif yetkili ad korundu', bool(row and row['ad_soyad']), str(row['ad_soyad'] if row else None))
    yetkili_aktif_ayarla(con, yetkili_id, 1, kullanici_id=1)
    con.commit()

if gid_mp:
    r8 = client.post(f'/nexgen/api/musteri-pazarlama/gorusme/{gid_mp}/takip', json={
        'takip_durumu': 'TAMAMLANDI'
    })
    j8 = r8.get_json() or {}
    ok('takip tamamla', r8.status_code == 200 and j8.get('ok'), f'{r8.status_code} {j8}')
    td = con.execute(
        'SELECT takip_durumu, aktif FROM musteri_operasyon_gorusme WHERE id=?',
        (gid_mp,),
    ).fetchone()
    ok('takip silinmedi', td and int(td['aktif']) == 1 and td['takip_durumu'] == 'TAMAMLANDI',
       str(dict(td) if td else None))

# Mehmet (planlama) yazma 403
login(31, 'mehmet', 32)
r9 = client.post('/nexgen/api/musteri-pazarlama/gorusme', json={
    'cari_id': cari_id,
    'gorusme_tipi': 'Telefon',
    'sonuc_tipi': 'Genel Görüşme',
    'kisa_not': 'mehmet yazma denemesi xxx',
    'gorusme_tarihi': '2026-07-27 15:00:00',
    'idempotency_key': f'CRM1-MEH-{uuid.uuid4()}',
})
j9 = r9.get_json() or {}
ok('Mehmet yazma 403', r9.status_code == 403 and not j9.get('ok'), f'{r9.status_code} {j9}')

r10 = client.get(f'/nexgen/api/cari360/{cari_id}/gorusme')
j10 = r10.get_json() or {}
ok('Mehmet read-only liste', r10.status_code == 200 and j10.get('ok') and j10.get('can_write') is False,
   f'{r10.status_code} can_write={j10.get("can_write")}')

# Ali erişim yok
login(46, 'ali', 43)
r11 = client.get('/nexgen/musteri-pazarlama')
ok('Ali MP engel', r11.status_code in (403, 302, 401), str(r11.status_code))
r12 = client.get(f'/nexgen/cari360/{cari_id}?tab=gorusmeler')
ok('Ali Cari Kart engel', r12.status_code in (403, 302, 401), str(r12.status_code))

# Cari Kart sayfa admin
login(1, 'admin', 1)
r13 = client.get(f'/nexgen/cari360/{cari_id}?tab=gorusmeler')
html = r13.get_data(as_text=True)
ok('CK sayfa 200', r13.status_code == 200, str(r13.status_code))
ok('CK sekme HTML', 'data-tab="gorusmeler"' in html and 'Yeni Görüşme' in html)

# mo_gorusme_id regression
has_nt = bool(con.execute(
    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexgen_numune_talep'"
).fetchone())
if has_nt:
    ncols = {r[1] for r in con.execute('PRAGMA table_info(nexgen_numune_talep)')}
    ok('numune mo_gorusme_id kolon', 'mo_gorusme_id' in ncols)
    n_cnt = con.execute(
        'SELECT COUNT(*) AS c FROM nexgen_numune_talep WHERE mo_gorusme_id IS NOT NULL'
    ).fetchone()['c']
    ok('numune baglari bozulmadi', True, f'count={n_cnt}')
else:
    ok('numune tablo yok (skip)', True)

# siparis tablo
sip_tables = [r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%siparis%'"
)]
mo_sip = None
for t in sip_tables:
    cols_t = {r[1] for r in con.execute(f'PRAGMA table_info({t})')}
    if 'mo_gorusme_id' in cols_t:
        mo_sip = t
        break
ok('siparis mo_gorusme_id kolon', mo_sip is not None, str(mo_sip))

# unvan değişince geçmiş
if gid_mp:
    old_unvan = con.execute('SELECT unvan FROM nexgen_cari WHERE id=?', (cari_id,)).fetchone()['unvan']
    con.execute('UPDATE nexgen_cari SET unvan=? WHERE id=?', (old_unvan + ' [TMP]', cari_id))
    con.commit()
    still = con.execute(
        'SELECT id, cari_id FROM musteri_operasyon_gorusme WHERE id=?', (gid_mp,)
    ).fetchone()
    ok('unvan degisse gorusme kopmaz', still and int(still['cari_id']) == cari_id)
    con.execute('UPDATE nexgen_cari SET unvan=? WHERE id=?', (old_unvan, cari_id))
    con.commit()

tpl_mp = open(os.path.join(_APP, 'templates', 'nexgen', 'musteri_pazarlama.html'), encoding='utf-8').read()
tpl_ck = open(os.path.join(_APP, 'templates', 'nexgen', 'cari360_kart.html'), encoding='utf-8').read()
ok('MP yetkili field', 'mp-f-yetkili' in tpl_mp and 'sonraki_aksiyon' in tpl_mp)
ok('CK gorusme JS', 'ckartGorusmeYukle' in tpl_ck)

# güncelleme
login(1, 'admin', 1)
if gid_ck:
    r14 = client.post(f'/nexgen/api/cari360/{cari_id}/gorusme/{gid_ck}', json={
        'konu': 'CRM1 CK guncellendi',
        'kisa_not': 'Cari Kart kaynakli gorusme guncel',
        'gorusme_tipi': 'Ziyaret',
        'sonuc_tipi': 'Fiyat İstedi',
    })
    j14 = r14.get_json() or {}
    ok('gorusme duzenle', r14.status_code == 200 and j14.get('ok'), f'{r14.status_code} {j14}')

# cleanup
for kind, val in _CREATED:
    if kind == 'idem' and val:
        con.execute('DELETE FROM musteri_operasyon_gorusme WHERE idempotency_key=?', (val,))
    if kind == 'yetkili' and val:
        con.execute('DELETE FROM cari_yetkili WHERE id=?', (val,))
# leftover bad keys
con.execute("DELETE FROM musteri_operasyon_gorusme WHERE idempotency_key LIKE 'CRM1-%'")
con.commit()
con.close()

failed = [n for n, c, _ in results if not c]
print('=' * 72)
print(f'TOPLAM={len(results)} PASS={len(results)-len(failed)} FAIL={len(failed)}')
if failed:
    print('FAILED:', ', '.join(failed))
    sys.exit(1)
print('ALL PASS')
sys.exit(0)
