# -*- coding: utf-8 -*-
"""BE-1: Pazarlama çok kalemli sipariş altyapısı — migration + read layer testleri."""
import importlib.util
import io
import os
import shutil
import sqlite3
import sys
from datetime import datetime

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP_DIR)
os.chdir(_APP_DIR)
DB = os.path.join(_APP_DIR, 'mock_data.db')
M107 = os.path.join(_APP_DIR, 'migrations', '107_nexgen_planlama_siparis_kalem.py')

results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def load_m107():
    spec = importlib.util.spec_from_file_location('m107', M107)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def snapshot(con):
    def cnt(sql):
        return con.execute(sql).fetchone()[0]
    return {
        'plan': cnt('SELECT COUNT(*) FROM nexgen_uretim_plan'),
        'batch': cnt('SELECT COUNT(*) FROM nexgen_uretim_batch'),
        'rf': cnt('SELECT COUNT(*) FROM nexgen_rf_renk'),
        'pzm': cnt("SELECT COUNT(*) FROM nexgen_planlama_siparis WHERE talep_referansi LIKE '__PZM_V1__%'"),
        'kalem': cnt('SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem') if _tablo_var(con, 'nexgen_planlama_siparis_kalem') else 0,
    }


def _tablo_var(con, tablo):
    return con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
    ).fetchone() is not None


print('=' * 65)
print('BE-1 TEST — nexgen_planlama_siparis_kalem')
print('=' * 65)

# ── Backup ───────────────────────────────────────────────────────
ts = datetime.now().strftime('%Y%m%d_%H%M%S')
bak = DB.replace('.db', f'_backup_be1_pre107_{ts}.db')
shutil.copy2(DB, bak)
ok('backup olusturuldu', os.path.exists(bak), bak)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
before = snapshot(con)
ok('once snapshot', before['plan'] >= 0, f'plan={before["plan"]} batch={before["batch"]} rf={before["rf"]} pzm={before["pzm"]}')

m107 = load_m107()

# ── Apply ────────────────────────────────────────────────────────
st1 = m107.run(db_path=DB)
ok('migration apply ok', st1.get('ok'), f'yeni={st1.get("yeni_degisiklik")}')
ok('kalem tablosu olustu', _tablo_var(con, 'nexgen_planlama_siparis_kalem'))

indexes = [r['name'] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='nexgen_planlama_siparis_kalem'"
).fetchall()]
for idx in ('idx_npsk_siparis', 'idx_npsk_formul', 'idx_npsk_renk', 'idx_npsk_plan', 'idx_npsk_durum'):
    ok(f'index {idx}', idx in indexes)

after1 = snapshot(con)
ok('plan sayisi degismedi', after1['plan'] == before['plan'], f'{before["plan"]} -> {after1["plan"]}')
ok('batch sayisi degismedi', after1['batch'] == before['batch'], f'{before["batch"]} -> {after1["batch"]}')
ok('rf sayisi degismedi', after1['rf'] == before['rf'], f'{before["rf"]} -> {after1["rf"]}')

if before['pzm'] > 0:
    ok('legacy backfill', after1['kalem'] >= before['pzm'], f'kalem={after1["kalem"]} pzm={before["pzm"]}')
else:
    ok('legacy backfill', True, 'pzm header yok — atlandi')

# ── Ikinci apply = 0 degisiklik ────────────────────────────────
st2 = m107.run(db_path=DB)
ok('ikinci apply yeni=0', st2.get('yeni_degisiklik') == 0, f'yeni={st2.get("yeni_degisiklik")}')
after2 = snapshot(con)
ok('ikinci apply sayim sabit', after2 == after1, str(after2))

# ── Read helper ──────────────────────────────────────────────────
from modules.nexgen.pzm_siparis_read import (
    pzm_kalem_tablosu_var,
    pzm_siparis_oku,
    pzm_siparis_kalemleri_getir,
)
from modules.nexgen.routes import _pzm_talep_satir_dict

ok('read helper tablo var', pzm_kalem_tablosu_var(con))

hdr = con.execute(
    "SELECT id, siparis_no, cari_id, cari_unvan, termin_tarihi, durum, notlar, talep_referansi, olusturma_tarihi "
    "FROM nexgen_planlama_siparis WHERE talep_referansi LIKE '__PZM_V1__%' ORDER BY id LIMIT 1"
).fetchone()

if hdr:
    okuma = pzm_siparis_oku(con, hdr['id'])
    ok('legacy siparis okunur', okuma is not None and okuma.get('legacy_json_korundu'), hdr['siparis_no'])
    ok('kalem listesi dolu', len(okuma.get('kalemler') or []) >= 1, f'n={len(okuma.get("kalemler") or [])}')
    k0 = (okuma.get('kalemler') or [{}])[0]
    ok('payload uyumlu', okuma.get('payload') is not None or k0.get('kaynak') == 'KALEM')
    satir = _pzm_talep_satir_dict(hdr, con)
    ok('talep_satir_dict kalemler', 'kalemler' in satir and len(satir['kalemler']) >= 1)
    ok('legacy JSON korundu', hdr['talep_referansi'].startswith('__PZM_V1__'))
else:
    ok('legacy siparis okunur', True, 'pzm kayit yok — atlandi')

# ── Integrity ────────────────────────────────────────────────────
orphan = con.execute("""
    SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem k
    LEFT JOIN nexgen_planlama_siparis h ON h.id = k.planlama_siparis_id
    WHERE h.id IS NULL
""").fetchone()[0]
ok('integrity orphan=0', orphan == 0, str(orphan))

ver107 = con.execute(
    "SELECT COUNT(*) FROM schema_migrations WHERE version='107'"
).fetchone()[0]
ok('schema_migrations 107', ver107 >= 1)

# ── Smoke: API import ────────────────────────────────────────────
import app as flask_app
_app = flask_app.app
_app.config['TESTING'] = True
with _app.test_client() as c:
    with c.session_transaction() as sess:
        sess['kullanici'] = {'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem', 'RolId': 1, 'RolAd': 'admin', 'Aktif': 1}
        sess['kullanici_tip'] = 'sistem'
    r = c.get('/nexgen/api/pazarlama/talepler')
    ok('smoke talepler api', r.status_code == 200, f'status={r.status_code}')
    if r.status_code == 200:
        js = r.get_json() or {}
        ok('smoke api ok', js.get('ok') is True)

con.close()

print('\n' + '=' * 65)
passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f'SONUC: {passed} PASS / {failed} FAIL')
print(f'Backup: {bak}')
print('Commit: EDILMEDI')
print('=' * 65)
sys.exit(0 if failed == 0 else 1)
