# -*- coding: utf-8 -*-
"""
CARI360-SEVKIYAT-REGRESSION — canonical read + pagination + expand contract.
READ-ONLY — mock_data.db SHA korunur.
"""
import hashlib
import os
import sqlite3
import sys
import unittest.mock as mock

CANONICAL_DB = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app', 'mock_data.db')
)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app'))

from modules.nexgen.cari360_ops_read_service import load_cari360_sevkiyatlar  # noqa: E402

_STUB_YK = {'NEXGEN_ADMIN'}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def get_con():
    db_uri = f'file:{os.path.abspath(CANONICAL_DB)}?mode=ro'
    con = sqlite3.connect(db_uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _load(cari_id, **kwargs):
    con = get_con()
    try:
        with mock.patch(
            'modules.nexgen.cari360_ops_read_service._assert_cari',
            return_value={'id': cari_id},
        ), mock.patch(
            'modules.nexgen.cari360_ops_read_service.can_view_cari',
            return_value=True,
        ):
            return load_cari360_sevkiyatlar(con, cari_id, kullanici_id=1, yk=_STUB_YK, **kwargs)
    finally:
        con.close()


SHA_BEFORE = sha256_file(CANONICAL_DB)
results = []


def check(name, cond, detail=''):
    status = 'PASS' if cond else 'FAIL'
    results.append((name, status, detail))
    print(f'  [{status}] {name}' + (f' — {detail}' if detail else ''))
    return cond


# ---------------------------------------------------------------------------
print('\n=== CASE A: cari 5 — gerçek sevkiyat var ===')
d5 = _load(cari_id=5, page=1, page_size=10)
check('A1 — count > 0', d5.get('total_count', 0) > 0, str(d5.get('total_count')))
check('A2 — 2 sevkiyat', d5.get('total_count') == 2, str(d5.get('total_count')))
liste5 = d5.get('liste') or []
check('A3 — liste dolu', len(liste5) == 2, str(len(liste5)))
if liste5:
    s = next((x for x in liste5 if x.get('sevkiyat_no') == 'MSV-2026-0165'), liste5[0])
    check('A4 — sevkiyat_no business code', s.get('sevkiyat_no', '').startswith('MSV-'),
          s.get('sevkiyat_no'))
    check('A5 — internal id gösterilmez (no == sevkiyat_no)',
          s.get('sevkiyat_no') != f"#{s.get('id')}", s.get('sevkiyat_no'))
    check('A6 — urun TERLIK', s.get('urun') == 'TERLIK', s.get('urun'))
    check('A7 — renk canonical', 'TURUNCU' in (s.get('renk') or ''), s.get('renk'))
    check('A8 — sevk_kg 3000', float(s.get('sevk_kg') or 0) == 3000, str(s.get('sevk_kg')))
    check('A9 — durum SEVK_EDILDI veya HAZIRLANIYOR',
          s.get('durum') in ('SEVK_EDILDI', 'HAZIRLANIYOR'), s.get('durum'))
    check('A10 — batch_kodu canonical', bool(s.get('batch_kodu')),
          s.get('batch_kodu'))
    check('A11 — batch NG-PRD prefix', (s.get('batch_kodu') or '').startswith('NG-PRD'),
          s.get('batch_kodu'))
    check('A12 — siparis_no PZM-2026-0221', s.get('siparis_no') == 'PZM-2026-0221',
          s.get('siparis_no'))
    check('A13 — sevkiyat_url canonical route',
          s.get('sevkiyat_url') == f"/nexgen/sevkiyat/{s.get('id')}", s.get('sevkiyat_url'))
    check('A14 — siparis → cari pointer', s.get('siparis_id') == 759, str(s.get('siparis_id')))

# ---------------------------------------------------------------------------
print('\n=== CASE B: cari 11 — tek sevkiyat ===')
d11 = _load(cari_id=11, page=1, page_size=10)
check('B1 — total_count=1', d11.get('total_count') == 1, str(d11.get('total_count')))
s11 = (d11.get('liste') or [{}])[0]
check('B2 — MSV-2026-0166', s11.get('sevkiyat_no') == 'MSV-2026-0166', s11.get('sevkiyat_no'))
check('B3 — siparis PZM-2026-0222', s11.get('siparis_no') == 'PZM-2026-0222', s11.get('siparis_no'))
check('B4 — sevk_kg 2000', float(s11.get('sevk_kg') or 0) == 2000, str(s11.get('sevk_kg')))

# ---------------------------------------------------------------------------
print('\n=== CASE C: cari 16 — gerçekten boş ===')
d16 = _load(cari_id=16, page=1, page_size=10)
check('C1 — total_count=0', d16.get('total_count') == 0, str(d16.get('total_count')))
check('C2 — liste boş', len(d16.get('liste') or []) == 0)

# ---------------------------------------------------------------------------
print('\n=== SIZMA: cari 16 sevkiyat cari 5\'e karışmaz ===')
ids16 = {x.get('id') for x in (d16.get('liste') or [])}
ids5 = {x.get('id') for x in (d5.get('liste') or [])}
check('D1 — cari16 boş küme', len(ids16) == 0)
check('D2 — overlap yok', len(ids16 & ids5) == 0)

# ---------------------------------------------------------------------------
print('\n=== PAGINATION: page_size=10 ===')
check('E1 — page_size response', d5.get('page_size') == 10, str(d5.get('page_size')))
check('E2 — total_pages >= 1', (d5.get('total_pages') or 0) >= 1, str(d5.get('total_pages')))

# ---------------------------------------------------------------------------
print('\n=== EXPAND CONTRACT — 4 blok alanları ===')
if liste5:
    s = liste5[0]
    req = [
        'sevkiyat_no', 'gercek_sevk_tarihi', 'durum', 'durum_etiket',
        'kalemler', 'siparis_no', 'siparis_tarihi', 'siparis_url',
        'sevkiyat_url', 'plan_url', 'batch_kodlari', 'batch_kodu',
        'hazirlik_tarihi', 'kargo_firmasi',
    ]
    missing = [k for k in req if k not in s]
    check('F1 — expand alanları mevcut', len(missing) == 0, str(missing))
    k0 = (s.get('kalemler') or [{}])[0]
    check('F2 — kalem formul_ad alanı', 'formul_ad' in k0)
    check('F3 — fake URL yok (plan_url null veya uretim-emirleri)',
          s.get('plan_url') is None or '/nexgen/uretim-emirleri' in (s.get('plan_url') or ''))
    check('F4 — siparis_url pazarlama', '/nexgen/pazarlama?siparis=' in (s.get('siparis_url') or ''))

# ---------------------------------------------------------------------------
print('\n=== GERÇEK SEVK TARIHI ===')
sevk_edildi = next((x for x in liste5 if x.get('durum') == 'SEVK_EDILDI'), None)
if sevk_edildi:
    check('G1 — SEVK_EDILDI gercek_sevk_tarihi dolu',
          bool(sevk_edildi.get('gercek_sevk_tarihi')), sevk_edildi.get('gercek_sevk_tarihi'))
hazir = next((x for x in liste5 if x.get('durum') == 'HAZIRLANIYOR'), None)
if hazir:
    check('G2 — HAZIRLANIYOR gercek_sevk_tarihi null',
          hazir.get('gercek_sevk_tarihi') is None, str(hazir.get('gercek_sevk_tarihi')))

# ---------------------------------------------------------------------------
print('\n=== MULTI-KALEM — ONE HEADER = ONE ROW (in-memory) ===')
_mem = sqlite3.connect(':memory:')
_mem.row_factory = sqlite3.Row
_mem.executescript("""
CREATE TABLE nexgen_cari (id INTEGER PRIMARY KEY, cari_kod TEXT, unvan TEXT, aktif INTEGER DEFAULT 1);
CREATE TABLE mo_musteri_sevkiyat (
    id INTEGER PRIMARY KEY, sevkiyat_no TEXT, siparis_id INTEGER, cari_id INTEGER,
    durum TEXT, sevk_tarihi TEXT, olusturma_tarihi TEXT, aktif INTEGER DEFAULT 1,
    irsaliye_no TEXT, hazirlik_tarihi TEXT, teslim_tarihi TEXT,
    arac_plaka TEXT, sofor TEXT, kargo_firmasi TEXT, kargo_takip_no TEXT,
    teslim_alan TEXT, teslim_durumu TEXT, notlar TEXT
);
CREATE TABLE mo_musteri_sevkiyat_kalem (
    id INTEGER PRIMARY KEY, sevkiyat_id INTEGER, siparis_kalem_id INTEGER,
    urun_adi TEXT, renk_ad TEXT, formul_ad TEXT, miktar_kg REAL, miktar_adet REAL, notlar TEXT
);
CREATE TABLE nexgen_planlama_siparis (
    id INTEGER PRIMARY KEY, siparis_no TEXT, cari_id INTEGER, olusturma_tarihi TEXT, durum TEXT
);
INSERT INTO nexgen_cari VALUES (99,'T.99','Test',1);
INSERT INTO nexgen_planlama_siparis VALUES (900,'PZM-T-900',99,'2026-01-01','ONAY');
INSERT INTO mo_musteri_sevkiyat VALUES
  (9001,'MSV-T-9001',900,99,'SEVK_EDILDI','2026-08-01','2026-08-01',1,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO mo_musteri_sevkiyat_kalem VALUES
  (1,9001,1,'URUN-A','RENK-A','',1000,NULL,''),
  (2,9001,2,'URUN-B','RENK-B','',500,NULL,'');
""")
with mock.patch(
    'modules.nexgen.cari360_ops_read_service._assert_cari', return_value={'id': 99}
), mock.patch('modules.nexgen.cari360_ops_read_service.can_view_cari', return_value=True):
    r_mk = load_cari360_sevkiyatlar(_mem, 99, 1, _STUB_YK, page=1, page_size=10)
_mem.close()
check('H1 — 2 kalem → 1 header row', len(r_mk.get('liste') or []) == 1)
check('H2 — total_count kalem sayısıyla şişmez', r_mk.get('total_count') == 1)
mk_row = (r_mk.get('liste') or [{}])[0]
check('H3 — sevk_kg = SUM(kalem.miktar_kg)', float(mk_row.get('sevk_kg') or 0) == 1500,
      str(mk_row.get('sevk_kg')))
check('H4 — kalemler expand içinde', mk_row.get('kalem_sayisi') == 2)

# ---------------------------------------------------------------------------
print('\n=== ROUTE CONTRACT — fake shipment URL absent when no record ===')
check('I1 — sevkiyat_url only when id set', all(
    (not x.get('sevkiyat_url')) or x.get('sevkiyat_url', '').startswith('/nexgen/sevkiyat/')
    for x in (d5.get('liste') or [])
))

# ---------------------------------------------------------------------------
print('\n=== LOCK: MSV-2026-0165 — canonical pin (SEVK_EDILDI) ===')
msv165 = next((x for x in liste5 if x.get('sevkiyat_no') == 'MSV-2026-0165'), None)
check('J1 — MSV-2026-0165 mevcut', msv165 is not None)
if msv165:
    check('J2 — siparis PZM-2026-0221', msv165.get('siparis_no') == 'PZM-2026-0221',
          msv165.get('siparis_no'))
    check('J3 — batch NG-PRD-2026-00029', msv165.get('batch_kodu') == 'NG-PRD-2026-00029',
          msv165.get('batch_kodu'))
    check('J4 — urun TERLIK', msv165.get('urun') == 'TERLIK', msv165.get('urun'))
    check('J5 — renk 0250 TURUNCU', '0250' in (msv165.get('renk') or '') and 'TURUNCU' in (msv165.get('renk') or ''),
          msv165.get('renk'))
    check('J6 — sevk_kg 3000', float(msv165.get('sevk_kg') or 0) == 3000, str(msv165.get('sevk_kg')))
    check('J7 — durum SEVK_EDILDI', msv165.get('durum') == 'SEVK_EDILDI', msv165.get('durum'))
    check('J8 — gercek_sevk_tarihi 2026-08-10', msv165.get('gercek_sevk_tarihi') == '2026-08-10',
          str(msv165.get('gercek_sevk_tarihi')))
    check('J9 — sevkiyat_url /nexgen/sevkiyat/227',
          msv165.get('sevkiyat_url') == '/nexgen/sevkiyat/227', msv165.get('sevkiyat_url'))
    check('J10 — siparis_url /nexgen/pazarlama?siparis=759',
          msv165.get('siparis_url') == '/nexgen/pazarlama?siparis=759', msv165.get('siparis_url'))
    check('J11 — plan_url /nexgen/uretim-emirleri?vurgu=193',
          msv165.get('plan_url') == '/nexgen/uretim-emirleri?vurgu=193', msv165.get('plan_url'))

# ---------------------------------------------------------------------------
print('\n=== LOCK: MSV-2026-0164 — HAZIRLANIYOR pin ===')
msv164 = next((x for x in liste5 if x.get('sevkiyat_no') == 'MSV-2026-0164'), None)
check('K1 — MSV-2026-0164 mevcut', msv164 is not None)
if msv164:
    check('K2 — durum HAZIRLANIYOR', msv164.get('durum') == 'HAZIRLANIYOR', msv164.get('durum'))
    check('K3 — gercek_sevk_tarihi null', msv164.get('gercek_sevk_tarihi') is None,
          str(msv164.get('gercek_sevk_tarihi')))
    check('K4 — sevkiyat_url /nexgen/sevkiyat/226',
          msv164.get('sevkiyat_url') == '/nexgen/sevkiyat/226', msv164.get('sevkiyat_url'))

# ---------------------------------------------------------------------------
print('\n=== LOCK: BEOSS cari_id=1 — empty state canonical ===')
d1 = _load(cari_id=1, page=1, page_size=10)
check('L1 — Beoss total_count=0', d1.get('total_count') == 0, str(d1.get('total_count')))
check('L2 — Beoss liste=[]', len(d1.get('liste') or []) == 0)
check('L3 — Beoss liste key mevcut', 'liste' in d1)
check('L4 — Beoss sizmaz: cari5 listesine karışmaz',
      len({x.get('id') for x in (d1.get('liste') or [])} & {x.get('id') for x in liste5}) == 0)

# ---------------------------------------------------------------------------
print('\n=== LOCK: 3E SUMMARY — total 2, toplam_kg 6000 (db doğrudan) ===')
import sqlite3 as _s3
_con_sum = _s3.connect(f'file:{os.path.abspath(CANONICAL_DB)}?mode=ro', uri=True)
_con_sum.row_factory = _s3.Row
_r_cnt = _con_sum.execute(
    "SELECT COUNT(*) n FROM mo_musteri_sevkiyat WHERE cari_id=5 AND COALESCE(aktif,1)=1"
).fetchone()
_r_kg = _con_sum.execute(
    """SELECT COALESCE(SUM(k.miktar_kg),0) kg
       FROM mo_musteri_sevkiyat_kalem k
       JOIN mo_musteri_sevkiyat s ON s.id=k.sevkiyat_id
       WHERE s.cari_id=5 AND COALESCE(s.aktif,1)=1"""
).fetchone()
_con_sum.close()
check('M1 — DB toplam_sevkiyat=2', _r_cnt['n'] == 2, str(_r_cnt['n']))
check('M2 — DB toplam_sevk_kg=6000', float(_r_kg['kg']) == 6000.0, str(_r_kg['kg']))

# ---------------------------------------------------------------------------
print('\n=== LOCK: HEADER DUPLICATION — hiçbir sevk_no birden fazla görünmez ===')
sevk_nolar = [x.get('sevkiyat_no') for x in liste5]
check('N1 — header duplication yok', len(sevk_nolar) == len(set(sevk_nolar)),
      str(sevk_nolar))

# ---------------------------------------------------------------------------
SHA_AFTER = sha256_file(CANONICAL_DB)
print('\n=== SONUÇ ===')
pass_count = sum(1 for _, s, _ in results if s == 'PASS')
fail_count = sum(1 for _, s, _ in results if s == 'FAIL')
print(f'PASS: {pass_count}  FAIL: {fail_count}  TOPLAM: {len(results)}')
print(f'SHA BEFORE: {SHA_BEFORE}')
print(f'SHA AFTER : {SHA_AFTER}')
sha_ok = SHA_BEFORE == SHA_AFTER
print(f'SHA AYNI  : {"EVET" if sha_ok else "HAYIR"}')

if fail_count > 0 or not sha_ok:
    sys.exit(1)
sys.exit(0)
