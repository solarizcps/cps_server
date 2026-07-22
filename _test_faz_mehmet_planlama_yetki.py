# -*- coding: utf-8 -*-
"""FAZ-MEHMET-OVERRIDE-YETKI — test suite."""
import importlib.util
import io
import os
import shutil
import sqlite3
import sys
import tempfile

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

from tools.nexgen_tmp_db import sha256_file

_LIVE_DB = os.path.join(_APP, 'mock_data.db')
_SHA_BEFORE = sha256_file(_LIVE_DB)

_TMP_DIR = tempfile.mkdtemp(prefix='faz_mehmet_ov_')
DB = os.path.join(_TMP_DIR, 'mock_data_test.db')
shutil.copy2(_LIVE_DB, DB)

_MIG = os.path.join(_APP, 'migrations', '112_nexgen_planlama_mehmet_yetki.py')
_AUTH = os.path.join(_APP, 'modules', 'auth.py')

results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    s = 'PASS' if cond else 'FAIL'
    print(f'  [{s}] {name}' + (f' — {detail}' if detail else ''))


def _run_migration(path, db_path):
    spec = importlib.util.spec_from_file_location('mig112', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path=db_path)


print('=' * 70)
print('FAZ-MEHMET-OVERRIDE-YETKI TEST')
print('=' * 70)

# T1: auth.py override bloğu var
with open(_AUTH, encoding='utf-8') as f:
    auth_src = f.read()
ok('T1 auth.py override bloğu eklendi', 'user_permission_override' in auth_src and 'KullaniciId' in auth_src)

# T2: Migration dosyası var
ok('T2 migration 112 dosyası var', os.path.exists(_MIG))

# T3: Migration ilk çalışma
try:
    _run_migration(_MIG, DB)
    ok('T3 migration ilk çalışma', True)
except Exception as e:
    ok('T3 migration ilk çalışma', False, str(e))

# T4: İdempotent
try:
    _run_migration(_MIG, DB)
    ok('T4 migration idempotent', True)
except Exception as e:
    ok('T4 migration idempotent', False, str(e))

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# T5: Mehmet RolId=32 korundu
mehmet = con.execute("SELECT Id, RolId, Aktif FROM sistem_kullanici WHERE KullaniciAdi='mehmet'").fetchone()
ok('T5 mehmet RolId=32 korundu', mehmet and mehmet['RolId'] == 32, f'RolId={mehmet["RolId"] if mehmet else "?"}')
ok('T6 mehmet aktif', mehmet and mehmet['Aktif'] == 1)

# T6: mehmetemin etkilenmedi
mte = con.execute("SELECT RolId FROM sistem_kullanici WHERE KullaniciAdi='mehmetemin'").fetchone()
ok('T7 mehmetemin RolId=32 korundu', mte and mte['RolId'] == 32, f'RolId={mte["RolId"] if mte else "?"}')

# T7: 3 override kaydı var (mehmet — Kod üzerinden)
mehmet_id = mehmet['Id'] if mehmet else None
yetki_map = {}
if mehmet_id is not None:
    for kod in ('nexgen.view', 'nexgen.plan.view', 'nexgen.plan.manage'):
        yrow = con.execute('SELECT Id FROM sistem_yetki WHERE Kod=?', (kod,)).fetchone()
        yetki_map[kod] = yrow['Id'] if yrow else None
ovs = con.execute(
    """
    SELECT y.Kod
    FROM user_permission_override upo
    JOIN sistem_yetki y ON y.Id = upo.YetkiId
    WHERE upo.KullaniciId=? AND y.Kod IN ('nexgen.view','nexgen.plan.view','nexgen.plan.manage')
    """,
    (mehmet_id,),
).fetchall() if mehmet_id else []
kodlar = {r['Kod'] for r in ovs}
ok('T8 nexgen.view override', 'nexgen.view' in kodlar)
ok('T9 nexgen.plan.view override', 'nexgen.plan.view' in kodlar)
ok('T10 nexgen.plan.manage override', 'nexgen.plan.manage' in kodlar)

# T8: can_delete=0 hepsinde
del_rows = con.execute(
    """
    SELECT upo.can_delete
    FROM user_permission_override upo
    JOIN sistem_yetki y ON y.Id = upo.YetkiId
    WHERE upo.KullaniciId=? AND y.Kod IN ('nexgen.view','nexgen.plan.view','nexgen.plan.manage')
    """,
    (mehmet_id,),
).fetchall() if mehmet_id else []
ok('T11 can_delete=0 (minimum)', all(r['can_delete'] == 0 for r in del_rows))

# T9: mehmetemin'de NexGen override yok
mte_row = con.execute(
    "SELECT Id FROM sistem_kullanici WHERE KullaniciAdi='mehmetemin'"
).fetchone()
mte_ov = con.execute(
    """
    SELECT COUNT(*) c FROM user_permission_override upo
    JOIN sistem_yetki y ON y.Id = upo.YetkiId
    WHERE upo.KullaniciId=? AND y.Kod IN ('nexgen.view','nexgen.plan.view','nexgen.plan.manage')
    """,
    (mte_row['Id'],),
).fetchone()['c'] if mte_row else 0
ok('T12 mehmetemin override yok', mte_ov == 0, f'sayı={mte_ov}')

# T10: RolId=32 yetkiler değişmedi (11 kayıt)
planlama_yetki = con.execute(
    'SELECT COUNT(*) c FROM sistem_rol_yetki WHERE RolId=32'
).fetchone()['c']
ok('T13 RolId=32 yetkileri değişmedi', planlama_yetki == 11, f'sayı={planlama_yetki}')

# T11: NexGen Planlama rolü (Id=44) kalmadı — rollback temizledi
rol44 = con.execute("SELECT Id FROM sistem_rol WHERE Id=44").fetchone()
ok('T14 eski NexGen Planlama rolü (44) yok', rol44 is None)

con.close()

# T12: kullanici_yetkileri() override'ı dahil ediyor mu?
try:
    import config as cfg
    cfg.Config.MOCK_DB_PATH = DB
    # auth modülünü fresh yükle
    import importlib
    import modules.auth as auth_mod
    importlib.reload(auth_mod)

    user_dict = {'Id': mehmet_id, 'KullaniciAdi': 'mehmet', 'RolId': 32, 'Tip': None}
    import app as flask_app
    flask_app.app.config['TESTING'] = True
    with flask_app.app.test_request_context('/'):
        import flask
        flask.g.user = user_dict
        yks = auth_mod.kullanici_yetkileri(user_dict)
        ok('T15 nexgen.view:can_view override aktif', 'nexgen.view:can_view' in yks,
           f'yks içeriği (ilgili): {[y for y in yks if "nexgen" in y]}')
        ok('T16 nexgen.plan.manage:can_manage override aktif',
           'nexgen.plan.manage:can_manage' in yks)
        # Eski planlama yetkiler korundu mu?
        ok('T17 planlama:can_view korundu', 'planlama:can_view' in yks)
except Exception as e:
    ok('T15 override aktif', False, str(e))
    ok('T16 plan.manage override', False, '')
    ok('T17 eski yetki korundu', False, '')

# T15: Ana DB SHA değişmedi
ok('T18 ana DB SHA korundu', sha256_file(_LIVE_DB) == _SHA_BEFORE, _SHA_BEFORE[:12] + '..')

print('=' * 70)
passed = sum(1 for _, c, _ in results if c)
total = len(results)
print(f'SONUÇ: {passed}/{total} PASS')
if passed < total:
    print('BAŞARISIZ:')
    for name, cond, detail in results:
        if not cond:
            print(f'  [FAIL] {name}' + (f' — {detail}' if detail else ''))
