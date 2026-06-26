# -*- coding: utf-8 -*-
"""FAZ-STOK-GIRIS-2C — core tamamlama + recycle dogrulama."""
import sys, io, os, sqlite3

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'app'))
os.chdir(os.path.join(ROOT, 'app'))
DB = os.path.join(ROOT, 'app', 'mock_data.db')

from modules.nexgen.routes import _stok_hareket_yaz, _mevcut_stok

results = []
def chk(name, cond, detail=''):
    results.append({'name': name, 'pass': bool(cond), 'detail': detail})
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))

print('=== 2C: Recycle helper (rollback) ===')
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
rk = con.execute("SELECT id FROM nexgen_stok_kart WHERE kategori='RECYCLE' AND aktif=1 LIMIT 1").fetchone()
if rk:
    kid = rk['id']
    before = _mevcut_stok(con, kid)
    con.execute('BEGIN')
    try:
        wr = _stok_hareket_yaz(
            con, kid, 'GERI_DONUSUM_DEVIR', 0.001,
            aciklama='2C recycle test rollback',
            referans_tip='RECYCLE_GUNLUK',
            referans_id=None,
            olusturan_id=1,
            olusturma_tarihi='2026-06-24 12:00:00',
        )
        row = con.execute('SELECT * FROM nexgen_stok_hareket WHERE id=?', (wr['hareket_id'],)).fetchone()
        chk('recycle INSERT ok', row is not None)
        chk('referans_tip RECYCLE_GUNLUK', row['referans_tip'] == 'RECYCLE_GUNLUK')
        chk('onceki_sonraki dolu', row['onceki_stok'] is not None and row['sonraki_stok'] is not None)
    finally:
        con.execute('ROLLBACK')
    after = _mevcut_stok(con, kid)
    chk('rollback stok ayni', abs(before - after) < 0.0001, f'{before} vs {after}')
else:
    chk('recycle kart var', False, 'RECYCLE kart yok')
con.close()

print('\n=== 2C: INSERT noktasi taramasi ===')
routes_path = os.path.join(ROOT, 'app', 'modules', 'nexgen', 'routes.py')
with open(routes_path, encoding='utf-8') as f:
    content = f.read()
direct = content.count('INSERT INTO nexgen_stok_hareket')
helper_refs = content.count('_stok_hareket_yaz(')
chk('routes.py tek INSERT yeri (helper icinde)', direct == 2, f'direct={direct}')
chk('helper cagri sayisi >= 6', helper_refs >= 6, f'calls={helper_refs}')

passed = sum(1 for r in results if r['pass'])
print(f'\n=== SONUC: {passed}/{len(results)} PASS ===')
sys.exit(0 if passed == len(results) else 1)
