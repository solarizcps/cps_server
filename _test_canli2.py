# -*- coding: utf-8 -*-
"""FAZ-RENK-MERKEZI-CANLI-2 — KG/GR normalizasyon + regresyon testleri."""
import sys, io, os, json, sqlite3
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP  = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

DB = os.path.join(_APP, 'mock_data.db')

import app as flask_app
_app = flask_app.app
_app.config['TESTING'] = True

results = []
passed = 0; failed = 0

def ok(name, cond, detail=''):
    global passed, failed
    results.append((name, cond, detail))
    if cond: passed += 1
    else: failed += 1
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))

def admin_sess(c):
    with c.session_transaction() as sess:
        sess['kullanici'] = {'Id':1,'KullaniciAdi':'admin','Tip':'sistem','RolId':1,'RolAd':'Yönetici','Aktif':1}
        sess['kullanici_tip'] = 'sistem'

print("=" * 60)
print("  FAZ-RENK-MERKEZI-CANLI-2")
print("=" * 60)

# ─── DB birim doğrulama (doğrudan) ───────────────────────────
print("\n[DB] Birim analizi")
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# rf=10 → N330 (3.0 KG = 3000 GR)
row_n330 = con.execute(
    "SELECT sira, miktar_kg, pigment_ad, sk.ad FROM nexgen_rf_kalem rk "
    "LEFT JOIN nexgen_stok_kart sk ON sk.id=rk.stok_kart_id "
    "WHERE rk.rf_renk_id=10 AND rk.sira=1"
).fetchone()
ok('DB N330 miktar_kg=3.0', row_n330 and abs(float(row_n330['miktar_kg'])-3.0)<0.001,
   f"miktar_kg={row_n330['miktar_kg'] if row_n330 else 'YOK'}")

if row_n330:
    mkg = float(row_n330['miktar_kg'])
    mgr_beklenen = mkg * 1000
    ok('N330 normalize GR = 3000', abs(mgr_beklenen - 3000) < 0.01,
       f'miktar_kg={mkg} => GR={mgr_beklenen}')

# rf=11 → ATR-312 (2.0 KG = 2000 GR) + küçük pigmentler
kalemler11 = con.execute(
    "SELECT sira, miktar_kg, sk.ad FROM nexgen_rf_kalem rk "
    "LEFT JOIN nexgen_stok_kart sk ON sk.id=rk.stok_kart_id "
    "WHERE rk.rf_renk_id=11 ORDER BY rk.sira"
).fetchall()
ok('rf=11 kalemleri var', len(kalemler11) > 0, f'kalem={len(kalemler11)}')
if kalemler11:
    atr = kalemler11[0]
    ok('ATR-312 miktar_kg=2.0', abs(float(atr['miktar_kg'])-2.0)<0.01,
       f"miktar_kg={atr['miktar_kg']} ad={atr['ad']}")
    # Küçük pigmentler sıfır olmamalı
    kucuk = [k for k in kalemler11 if float(k['miktar_kg']) < 0.001]
    if kucuk:
        for k in kucuk:
            mkg = float(k['miktar_kg'])
            mgr = mkg * 1000
            ok(f'Küçük pigment sıfır değil: {k["ad"]}',
               mgr > 0, f'miktar_kg={mkg} => GR={mgr}')

# Toplam tutarlılık — rf=11
if kalemler11:
    toplam_kg = sum(float(k['miktar_kg']) for k in kalemler11)
    toplam_gr = toplam_kg * 1000
    ok('rf=11 toplam_gr > 0', toplam_gr > 0, f'toplam_gr={toplam_gr:.3f}')
    # Her kalemin oranı
    oranlar = [float(k['miktar_kg'])/toplam_kg*100 for k in kalemler11]
    oran_top = sum(oranlar)
    ok('rf=11 oranlar toplamı ~%100', abs(oran_top-100)<0.01, f'oran_top={oran_top:.4f}')

con.close()

# ─── API testleri ─────────────────────────────────────────────
print("\n[API] Detay endpoint testleri")
with _app.test_client() as c:
    admin_sess(c)

    # rf=10 detay
    r10 = c.get('/nexgen/api/renk-merkezi/detay?rf_id=10')
    ok('detay rf=10 HTTP 200', r10.status_code==200, f'status={r10.status_code}')
    d10 = json.loads(r10.data) if r10.status_code==200 else {}
    pigs10 = d10.get('pigmentler', [])
    ok('rf=10 pigment var', len(pigs10) > 0, f'kalem={len(pigs10)}')
    if pigs10:
        p0 = pigs10[0]
        ok('rf=10 N330 miktar_gr=3000', abs(float(p0.get('miktar_gr',0))-3000)<0.01,
           f"miktar_gr={p0.get('miktar_gr')} miktar_kg={p0.get('miktar_kg')}")
        ok('rf=10 ozet rf_id mevcut', d10.get('ozet',{}).get('rf_id') is not None,
           f"rf_id={d10.get('ozet',{}).get('rf_id')}")

    # rf=11 detay — çok kalemli
    r11 = c.get('/nexgen/api/renk-merkezi/detay?rf_id=11')
    ok('detay rf=11 HTTP 200', r11.status_code==200, f'status={r11.status_code}')
    d11 = json.loads(r11.data) if r11.status_code==200 else {}
    pigs11 = d11.get('pigmentler', [])
    ok('rf=11 çok kalem var', len(pigs11) >= 2, f'kalem={len(pigs11)}')
    if pigs11:
        toplam = sum(float(p.get('miktar_gr',0)) for p in pigs11)
        ok('rf=11 toplam_gr hesaplandı', toplam > 0, f'toplam={toplam:.3f} GR')
        kucuk0 = [p for p in pigs11 if float(p.get('miktar_gr',0))==0]
        ok('rf=11 küçük pigment sıfır değil', len(kucuk0)==0,
           f'{len(kucuk0)} adet sıfır' if kucuk0 else 'Temiz')

    # rf=67 detay — 8 kalem
    r67 = c.get('/nexgen/api/renk-merkezi/detay?rf_id=67')
    d67 = json.loads(r67.data) if r67.status_code==200 else {}
    pigs67 = d67.get('pigmentler', [])
    ok('rf=67 8 kalem', len(pigs67)==8, f'kalem={len(pigs67)}')
    if pigs67:
        toplam67 = sum(float(p.get('miktar_gr',0)) for p in pigs67)
        oranlar67 = [float(p.get('oran_yuzde',0)) for p in pigs67]
        ok('rf=67 toplam > 0', toplam67 > 0, f'toplam={toplam67:.3f}')
        ok('rf=67 oranlar ~%100', abs(sum(oranlar67)-100)<0.1,
           f'oran_top={sum(oranlar67):.4f}')

    # Bekleyen kart ozet rf_id
    r_liste = c.get('/nexgen/api/renk-merkezi/liste?filtre=AKT%C4%B0F')
    d_liste = json.loads(r_liste.data) if r_liste.status_code==200 else {}
    aktif_k = d_liste.get('kartlar',[])
    if aktif_k:
        ak = aktif_k[0]
        r_det = c.get(f'/nexgen/api/renk-merkezi/detay?rf_id={ak["rf_id"]}')
        d_det = json.loads(r_det.data) if r_det.status_code==200 else {}
        ok('aktif kart ozet.rf_id var',
           d_det.get('ozet',{}).get('rf_id') is not None,
           f"rf_id={d_det.get('ozet',{}).get('rf_id')}")

    # ─── Buton testi — revizyon-ac endpoint (tmp DB; live'a geri yazma YOK) ─
    print("\n[BTN] Yeni Revizyon endpoint testi (temp DB)")
    import shutil, tempfile, hashlib
    import config as _cfg
    import modules.nexgen.routes as nx_routes
    _live = os.path.join(_APP, 'mock_data.db')
    def _sha(p):
        h = hashlib.sha256()
        with open(p, 'rb') as f:
            for ch in iter(lambda: f.read(1024 * 1024), b''):
                h.update(ch)
        return h.hexdigest()
    sha_before = _sha(_live)
    tmp_dir = tempfile.mkdtemp(prefix='canli2_')
    TEMP_DB = os.path.join(tmp_dir, 'mock_data_test.db')
    shutil.copy2(_live, TEMP_DB)
    old_path = nx_routes.DB_PATH
    old_cfg = _cfg.Config.MOCK_DB_PATH
    nx_routes.DB_PATH = TEMP_DB
    _cfg.Config.MOCK_DB_PATH = TEMP_DB
    print(f'[ISO] tmp_db={TEMP_DB}')
    print(f'[ISO] main_sha_before={sha_before}')
    try:
        with _app.test_client() as ct:
            admin_sess(ct)
            rv = ct.post('/nexgen/api/boya-recetesi/1/revizyon-ac',
                         json={'neden':'TEST'},
                         content_type='application/json')
            ok('revizyon-ac rf=1 HTTP 200', rv.status_code==200,
               f'status={rv.status_code}')
            dv = json.loads(rv.data)
            ok('revizyon-ac ok=True', dv.get('ok') is True, str(dv)[:120])

            rv2 = ct.post('/nexgen/api/boya-recetesi/1/revizyon-ac',
                          json={'neden':'TEST2'},
                          content_type='application/json')
            ok('revizyon-ac tekrar 409', rv2.status_code==409,
               f'status={rv2.status_code}')

            with _app.test_client() as cu:
                r_yz = cu.post('/nexgen/api/boya-recetesi/10/revizyon-ac',
                               json={'neden':'X'},
                               content_type='application/json')
                ok('yetkisiz revizyon-ac 302/403', r_yz.status_code in (302,403),
                   f'status={r_yz.status_code}')
    finally:
        nx_routes.DB_PATH = old_path
        _cfg.Config.MOCK_DB_PATH = old_cfg
        sha_after = _sha(_live)
        ok('ISO main DB SHA unchanged', sha_before == sha_after, sha_before[:12])
        print(f'[ISO] main_sha_after={sha_after}')
        print(f'[ISO] main_db_changed={sha_before != sha_after}')
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # ─── Regresyon ─────────────────────────────────────────────
    print("\n[REG] Regresyon testleri")
    ok('renk-merkezi HTTP 200', c.get('/nexgen/renk-merkezi').status_code==200)
    ok('Reçete Merkezi 200', c.get('/nexgen/recete/').status_code==200)
    ok('Pazarlama 200', c.get('/nexgen/pazarlama').status_code==200)
    ok('ÜEM 200', c.get('/nexgen/uretim-emirleri').status_code==200)
    ok('Tablet 200', c.get('/nexgen/tablet').status_code in (200,302))

print()
print("=" * 60)
print(f"  {passed} PASS / {failed} FAIL / {passed+failed} toplam")
print("=" * 60)
if failed:
    print("  BAŞARISIZ:")
    for n,c2,d in results:
        if not c2: print(f"    ✗ {n} — {d}")
else:
    print("  GO ✓")
