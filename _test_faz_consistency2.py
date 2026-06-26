# -*- coding: utf-8 -*-
"""FAZ-CONSISTENCY-2 — snapshot, tablet tutarlılık, BOYA hariç kazan."""
import sys, io, os, sqlite3, math

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)
DB = os.path.join(_APP, 'mock_data.db')

import app as flask_app
from modules.nexgen.routes import (
    _batch_uretim_hesapla,
    _formul_batch_kg_hesapla,
    _nexgen_batch_snapshot,
    _tablet_ana_veri,
)

_app = flask_app.app
_app.config['TESTING'] = True
results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def sess_user():
    return {'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem', 'RolId': 1, 'RolAd': 'admin', 'Aktif': 1}


con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

uv = con.execute("""
    SELECT uv.id FROM nexgen_uretim_varyant uv
    JOIN nexgen_renk_varyant rv ON rv.id=uv.renk_varyant_id
    JOIN nexgen_formul f ON f.id=rv.formul_id
    WHERE f.ad='AYM TABAN' AND rv.ad='RECON RENK 65919' AND uv.boyut='SMALL'
      AND uv.recete_durum='URETIME_ACIK'
""").fetchone()
fb = _formul_batch_kg_hesapla(con, uv['id'])

# A) 200 KG ceil
b200 = _batch_uretim_hesapla(con, uv['id'], 200)
ok('A batch_sayisi=3', b200.get('batch_sayisi') == 3, str(b200.get('batch_sayisi')))
ok('A uretilecek~249.447', abs(b200.get('uretilecek_kg', 0) - 249.447) < 0.01,
   str(b200.get('uretilecek_kg')))
ok('A fazla~49.447', abs(b200.get('fazla_kg', 0) - 49.447) < 0.01, str(b200.get('fazla_kg')))

# F) BOYA çift sayım yok — taban batch BOYA hariç
boya_row = con.execute("""
    SELECT COALESCE(SUM(rk.miktar_kg),0) s
    FROM nexgen_recete_kalem rk
    JOIN nexgen_stok_kart sk ON sk.id=rk.stok_kart_id
    WHERE rk.uretim_varyant_id=? AND rk.aktif=1
      AND UPPER(COALESCE(sk.kategori,''))='BOYA'
""", (uv['id'],)).fetchone()
boya_kg = float(boya_row['s'] or 0)
tum_row = con.execute("""
    SELECT COALESCE(SUM(miktar_kg),0) s FROM nexgen_recete_kalem
    WHERE uretim_varyant_id=? AND aktif=1
""", (uv['id'],)).fetchone()
ok('F formul_batch BOYA haric', fb < float(tum_row['s'] or 0) or boya_kg <= 0,
   f'taban={fb} tum={tum_row["s"]} boya={boya_kg}')

PILOT_BATCH = 'NG-PRD-2026-00008'
snap_pilot = _nexgen_batch_snapshot(con, PILOT_BATCH)
ok('pilot snapshot', snap_pilot is not None, PILOT_BATCH)

if snap_pilot:
    ok('pilot batch_sayisi=3', snap_pilot['batch_sayisi'] == 3,
       str(snap_pilot['batch_sayisi']))
    ok('E stale_depo_var_mi', snap_pilot.get('stale_depo_var_mi') is True,
       f"depo={snap_pilot.get('depo_toplam_kg')} canli={snap_pilot.get('canli_ihtiyac_toplam_kg')} fark={snap_pilot.get('stale_depo_fark_kg')}")
    ok('E stale fark pozitif', (snap_pilot.get('stale_depo_fark_kg') or 0) > 40,
       str(snap_pilot.get('stale_depo_fark_kg')))
    ok('snapshot kalan alanlari',
       'kalan_siparis_kg' in snap_pilot and 'kalan_uretim_kg' in snap_pilot,
       f"sip={snap_pilot['kalan_siparis_kg']} ur={snap_pilot['kalan_uretim_kg']}")

# B/C — tablet ana veri vs snapshot parca sayaclari
devam, _plans = _tablet_ana_veri(con)
pilot_row = next((x for x in devam if x.get('batch_kodu') == PILOT_BATCH), None)
if pilot_row and snap_pilot:
    ok('B parca_toplam esit', pilot_row.get('parca_toplam') == snap_pilot['parca_toplam'],
       f"ana={pilot_row.get('parca_toplam')} snap={snap_pilot['parca_toplam']}")
    ok('B parca_biten esit', pilot_row.get('parca_biten') == snap_pilot['parca_biten'])
    ok('B parca_devam esit', pilot_row.get('parca_devam') == snap_pilot['parca_devam'])
    ok('B parca_kalan esit', pilot_row.get('parca_kalan') == snap_pilot['parca_kalan'])
    ok('B uretilecek_kg esit', pilot_row.get('uretilecek_kg') == snap_pilot['uretilecek_kg'],
       f"{pilot_row.get('uretilecek_kg')}")
    ok('D ana liste uretilecek> siparis',
       float(pilot_row.get('uretilecek_kg') or 0) >= float(pilot_row.get('siparis_kg') or 0))
else:
    ok('B pilot batch ana listede', False, 'batch bulunamadi')

# API ilerleme
with _app.test_client() as c:
    with c.session_transaction() as sess:
        sess['kullanici'] = sess_user()
    r = c.get(f'/nexgen/api/batch/{PILOT_BATCH}/ilerleme')
    j = r.get_json() if r.status_code == 200 else {}
    ok('API ilerleme 200', r.status_code == 200, str(r.status_code))
    if j.get('ok') and snap_pilot:
        ok('API kalan_uretim_kg', 'kalan_uretim_kg' in j, str(j.get('kalan_uretim_kg')))
        ok('API kalan_siparis_kg', 'kalan_siparis_kg' in j, str(j.get('kalan_siparis_kg')))
        ok('API uretilecek=snapshot', j.get('uretilecek_kg') == snap_pilot['uretilecek_kg'])

# G) FAZ-M1 regresyon
import subprocess
proc = subprocess.run(
    [sys.executable, os.path.join(ROOT, '_test_fazm1_mpr_on_calisma.py')],
    capture_output=True, text=True, encoding='utf-8', errors='replace',
)
m1_pass = proc.returncode == 0 and '0 FAIL' in proc.stdout
ok('G FAZ-M1 regresyon', m1_pass, f'rc={proc.returncode}')

con.close()
passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f'\n=== SONUC: {passed}/{len(results)} PASS, {failed} FAIL ===')
sys.exit(1 if failed else 0)
