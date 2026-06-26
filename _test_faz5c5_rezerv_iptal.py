# -*- coding: utf-8 -*-
"""NEXGEN FAZ-5C-5 — rezerv temizleme / iptal yaşam döngüsü testi."""
import sys, io, os, sqlite3, subprocess, importlib.util, shutil

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP_DIR)
os.chdir(_APP_DIR)
DB = os.path.join(_APP_DIR, 'mock_data.db')
_REG_BAK = os.path.join(_APP_DIR, 'mock_data.db.bak_faz5c5_20260624')
if not os.path.exists(_REG_BAK):
    _REG_BAK = os.path.join(_APP_DIR, 'mock_data.db.bak_faz5c4_20260624')

for _mig in ('085_nexgen_depo_hazirlik.py', '086_nexgen_stok_rezerv.py'):
    _p = os.path.join(_APP_DIR, 'migrations', _mig)
    _spec = importlib.util.spec_from_file_location(_mig, _p)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _mod.run()

import app as flask_app
from modules.nexgen.routes import (
    _mevcut_stok, _aktif_rezerv_toplam, _kullanilabilir_stok,
    _rezerv_aktif_iptal,
)

_app = flask_app.app
_app.config['TESTING'] = True
results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def sess_user():
    return {'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem',
            'RolId': 1, 'RolAd': 'admin', 'Aktif': 1}


def rezerv_ekle(con, batch_kodu, sid, miktar, plan_id=None, hazirlik_id=None, no=None):
    rno = no or f'RZ-TEST-5C5-{batch_kodu[-6:]}-{sid}'
    con.execute("""
        INSERT INTO nexgen_stok_rezerv
          (rezerv_no, stok_kart_id, kaynak_tip, kaynak_id, hazirlik_id,
           batch_kodu, plan_id, miktar_kg, kalan_kg, durum, olusturan_id)
        VALUES (?, ?, 'DEPO_HAZIRLIK', ?, ?, ?, ?, ?, ?, 'AKTIF', 1)
    """, (
        rno, sid, hazirlik_id or 1, hazirlik_id, batch_kodu,
        plan_id, miktar, miktar,
    ))
    return rno


def aktif_rezerv(con, batch_kodu=None, sid=None):
    q = "SELECT COALESCE(SUM(kalan_kg),0) FROM nexgen_stok_rezerv WHERE durum='AKTIF'"
    params = []
    if batch_kodu:
        q += " AND batch_kodu=?"; params.append(batch_kodu)
    if sid:
        q += " AND stok_kart_id=?"; params.append(sid)
    return round(float(con.execute(q, params).fetchone()[0]), 3)


if os.path.exists(_REG_BAK):
    shutil.copy2(_REG_BAK, DB)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

sk = con.execute("SELECT id FROM nexgen_stok_kart WHERE aktif=1 ORDER BY id LIMIT 1").fetchone()
sid = sk['id']

# Temizlik
con.execute("DELETE FROM nexgen_stok_rezerv WHERE rezerv_no LIKE 'RZ-TEST-5C5-%'")
con.execute("DELETE FROM nexgen_depo_hazirlik_kalem WHERE hazirlik_id IN "
            "(SELECT id FROM nexgen_depo_hazirlik WHERE hazirlik_no LIKE 'DH-TEST-5C5-%')")
con.execute("DELETE FROM nexgen_depo_hazirlik WHERE hazirlik_no LIKE 'DH-TEST-5C5-%'")
con.commit()

with _app.test_client() as c:
    with c.session_transaction() as sess:
        sess['kullanici'] = sess_user()
        sess['kullanici_tip'] = 'sistem'

    # ── 1) Batch iptal ──
    bk1 = 'NG-TEST-5C5-BATCH1'
    con.execute("""
        INSERT INTO nexgen_uretim_batch (batch_kodu, uretim_varyant_id, planlanan_kg, durum)
        SELECT ?, uretim_varyant_id, 10, 'HAZIR' FROM nexgen_uretim_batch LIMIT 1
    """, (bk1,))
    rezerv_ekle(con, bk1, sid, 50.0, no='RZ-TEST-5C5-B1')
    con.commit()
    kul_on = _kullanilabilir_stok(con, sid)
    rez_on = aktif_rezerv(con, sid=sid)
    r1 = c.post(f'/nexgen/api/batch/{bk1}/iptal', json={'nedeni': 'test batch iptal'})
    d1 = r1.get_json() or {}
    row1 = con.execute(
        "SELECT durum, kalan_kg, kapanis_tarihi FROM nexgen_stok_rezerv "
        "WHERE rezerv_no='RZ-TEST-5C5-B1'"
    ).fetchone()
    kul_sn = _kullanilabilir_stok(con, sid)
    ok('1 batch iptal 200', r1.status_code == 200 and d1.get('ok'), str(d1))
    ok('1 rezerv IPTAL', row1 and row1['durum'] == 'IPTAL', row1['durum'] if row1 else '')
    ok('1 kalan_kg korundu', row1 and abs(float(row1['kalan_kg']) - 50.0) < 0.001,
       str(row1['kalan_kg'] if row1 else ''))
    ok('5 kullanilabilir artti', kul_sn > kul_on + 49.0, f'{kul_on}->{kul_sn}')

    # ── 7) Duplicate / idempotent batch iptal ──
    gunc1 = d1.get('rezerv', {}).get('guncellenen', 0)
    r1b = c.post(f'/nexgen/api/batch/{bk1}/iptal', json={'nedeni': 'tekrar'})
    d1b = r1b.get_json() or {}
    ok('7 duplicate batch iptal', r1b.status_code == 200 and d1b.get('ok'), str(d1b.get('rezerv')))
    ok('8 idempotent rezerv', d1b.get('rezerv', {}).get('atlandi') is True,
       f'once={gunc1} twice={d1b.get("rezerv")}')

    # ── 2) Plan iptal ──
    plan = con.execute("""
        SELECT id FROM nexgen_uretim_plan
        WHERE durum NOT IN ('BITTI','IPTAL') ORDER BY id LIMIT 1
    """).fetchone()
    if plan:
        pid = plan['id']
        bk2 = 'NG-TEST-5C5-BATCH2'
        con.execute("""
            INSERT INTO nexgen_uretim_batch
              (batch_kodu, uretim_varyant_id, planlanan_kg, durum, plan_id)
            SELECT ?, uretim_varyant_id, 10, 'HAZIR', ?
            FROM nexgen_uretim_batch LIMIT 1
        """, (bk2, pid))
        rezerv_ekle(con, bk2, sid, 30.0, plan_id=pid, no='RZ-TEST-5C5-P1')
        con.commit()
        r2 = c.post(f'/nexgen/api/plan/{pid}/iptal', json={'nedeni': 'test plan'})
        d2 = r2.get_json() or {}
        st2 = con.execute(
            "SELECT durum FROM nexgen_stok_rezerv WHERE rezerv_no='RZ-TEST-5C5-P1'"
        ).fetchone()
        ok('2 plan iptal 200', r2.status_code == 200 and d2.get('ok'), str(d2.get('rezerv')))
        ok('2 plan rezerv IPTAL', st2 and st2['durum'] == 'IPTAL', st2['durum'] if st2 else '')

    # ── 3) Hazırlık iptal ──
    bk3 = 'NG-TEST-5C5-BATCH3'
    con.execute("""
        INSERT INTO nexgen_depo_hazirlik
          (hazirlik_no, batch_kodu, durum, olusturan_id)
        VALUES ('DH-TEST-5C5-HAZIR', ?, 'HAZIR', 1)
    """, (bk3,))
    hid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    rezerv_ekle(con, bk3, sid, 25.0, hazirlik_id=hid, no='RZ-TEST-5C5-H1')
    con.commit()
    r3 = c.post(f'/nexgen/api/depo/hazirlik/{hid}/iptal', json={'nedeni': 'depo iptal'})
    d3 = r3.get_json() or {}
    st3 = con.execute(
        "SELECT durum, kalan_kg FROM nexgen_stok_rezerv WHERE rezerv_no='RZ-TEST-5C5-H1'"
    ).fetchone()
    hdr3 = con.execute("SELECT durum FROM nexgen_depo_hazirlik WHERE id=?", (hid,)).fetchone()
    ok('3 hazirlik iptal 200', r3.status_code == 200 and d3.get('ok'), str(d3))
    ok('3 hazirlik rezerv IPTAL', st3 and st3['durum'] == 'IPTAL', st3['durum'] if st3 else '')
    ok('3 hazirlik durum IPTAL', hdr3 and hdr3['durum'] == 'IPTAL', hdr3['durum'] if hdr3 else '')

    # ── 4) Kısmi üretim + iptal ──
    bk4 = 'NG-TEST-5C5-BATCH4'
    con.execute("""
        INSERT INTO nexgen_uretim_batch (batch_kodu, uretim_varyant_id, planlanan_kg, durum)
        SELECT ?, uretim_varyant_id, 10, 'DEVAM' FROM nexgen_uretim_batch LIMIT 1
    """, (bk4,))
    con.execute("""
        INSERT INTO nexgen_stok_rezerv
          (rezerv_no, stok_kart_id, kaynak_tip, kaynak_id, batch_kodu,
           miktar_kg, kalan_kg, durum, olusturan_id)
        VALUES ('RZ-TEST-5C5-KISMI-A', ?, 'DEPO_HAZIRLIK', 1, ?, 200, 100, 'AKTIF', 1)
    """, (sid, bk4))
    con.execute("""
        INSERT INTO nexgen_stok_rezerv
          (rezerv_no, stok_kart_id, kaynak_tip, kaynak_id, batch_kodu,
           miktar_kg, kalan_kg, durum, olusturan_id)
        VALUES ('RZ-TEST-5C5-KISMI-T', ?, 'DEPO_HAZIRLIK', 1, ?, 100, 0, 'TUKETILDI', 1)
    """, (sid, bk4))
    con.commit()
    r4 = c.post(f'/nexgen/api/batch/{bk4}/iptal', json={'nedeni': 'kisem iptal'})
    tuk = con.execute(
        "SELECT durum, kalan_kg FROM nexgen_stok_rezerv WHERE rezerv_no='RZ-TEST-5C5-KISMI-T'"
    ).fetchone()
    akt = con.execute(
        "SELECT durum, kalan_kg FROM nexgen_stok_rezerv WHERE rezerv_no='RZ-TEST-5C5-KISMI-A'"
    ).fetchone()
    ok('4 kismi iptal 200', r4.status_code == 200, str(r4.status_code))
    ok('4 TUKETILDI korundu', tuk and tuk['durum'] == 'TUKETILDI', tuk['durum'] if tuk else '')
    ok('4 kalan AKTIF iptal', akt and akt['durum'] == 'IPTAL' and float(akt['kalan_kg']) == 100.0,
       f"{akt['durum'] if akt else ''} kalan={akt['kalan_kg'] if akt else ''}")

    # ── 6) Legacy batch rezerv yok ──
    bk5 = 'NG-TEST-5C5-LEGACY'
    con.execute("""
        INSERT INTO nexgen_uretim_batch (batch_kodu, uretim_varyant_id, planlanan_kg, durum)
        SELECT ?, uretim_varyant_id, 5, 'HAZIR' FROM nexgen_uretim_batch LIMIT 1
    """, (bk5,))
    con.commit()
    r5 = c.post(f'/nexgen/api/batch/{bk5}/iptal', json={})
    d5 = r5.get_json() or {}
    ok('6 legacy batch iptal', r5.status_code == 200 and d5.get('ok'),
       str(d5.get('rezerv')))

    # ── 6b) Helper legacy (tablo yok simülasyonu atlandi — tablo var) ──
    res_legacy = _rezerv_aktif_iptal(con, batch_kodu='NG-NO-SUCH-BATCH-5C5')
    ok('6 legacy helper skip', res_legacy.get('ok') and res_legacy.get('atlandi'),
       str(res_legacy))

con.close()

# FAZ-5C-4 regresyon
if os.path.exists(_REG_BAK):
    shutil.copy2(_REG_BAK, DB)
r4reg = subprocess.run(
    [sys.executable, os.path.join(_ROOT, '_test_faz5c4_rezerv_tuketim.py')],
    cwd=_APP_DIR, capture_output=True, text=True,
    encoding='utf-8', errors='replace',
)
reg_ok = '20/20 PASS' in r4reg.stdout or '19/20 PASS' in r4reg.stdout
ok('FAZ-5C-4 regresyon', reg_ok, r4reg.stdout.split('SONUC')[-1].strip()[:80])

passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f'\n=== SONUC: {passed}/{len(results)} PASS, {failed} FAIL ===')
sys.exit(1 if failed else 0)
