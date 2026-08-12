# -*- coding: utf-8 -*-
"""CARI-MO-RESPONSIBILITY-FIX-01 regression — temp DB only."""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app'
CANONICAL = APP / 'mock_data.db'
sys.path.insert(0, str(APP))
os.chdir(str(APP))

import tools.test_db_guard  # noqa: F401  TEST-DB-GUARD

results: list[tuple[str, bool, str]] = []


def ok(name: str, cond: bool, note: str = '') -> None:
    results.append((name, bool(cond), note))
    print(('PASS' if cond else 'FAIL'), name, note)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _find_mo_aday(con: sqlite3.Connection) -> int | None:
    from modules.nexgen.cari_sorumlu_service import list_mo_sorumlu_adaylari

    aday = list_mo_sorumlu_adaylari(con)
    ok('A01 aday list not empty', len(aday) > 0, f'n={len(aday)}')
    if not aday:
        return None
    return int(aday[0]['Id'])


def _erhan_scope_count(con: sqlite3.Connection, uid: int) -> int:
    from modules.nexgen.cari_sorumlu_service import get_kullanici_cari_kapsami

    yk = {'cari360.view_own:can_view'}
    kap = get_kullanici_cari_kapsami(con, uid, yk)
    return len(kap.get('cari_id_listesi') or [])


def test_create_requires_sorumlu(tmp_db: str) -> None:
    from modules.nexgen.cari_genel_bilgi_service import CariGenelError, insert_cari_with_genel
    from modules.nexgen.cari_sorumlu_service import ensure_ana_sorumlu_atama, validate_mo_sorumlu_aday
    from modules.nexgen.finans_cari_provision_service import provision_yeni_musteri

    con = sqlite3.connect(tmp_db)
    con.row_factory = sqlite3.Row
    yk = {'*'}
    aday_uid = _find_mo_aday(con)
    if aday_uid is None:
        return

    kod = '120.NX.RESP01'
    con.execute('DELETE FROM cari_sorumlu WHERE cari_id IN (SELECT id FROM nexgen_cari WHERE cari_kod=?)', (kod,))
    con.execute('DELETE FROM nexgen_cari WHERE cari_kod=?', (kod,))
    con.commit()

    # simulate api_cari_ekle without sorumlu — validation layer
    ok('B01 validate rejects 0', not validate_mo_sorumlu_aday(con, 0))

    con.execute('BEGIN IMMEDIATE')
    try:
        yeni_id = insert_cari_with_genel(
            con, kod, 'RESP TEST CARI 01', {'cari_tipi': 'MUSTERI'}, 1, yk,
        )
        provision_yeni_musteri(con, yeni_id, kullanici_id=1, owns_transaction=False)
        sr = ensure_ana_sorumlu_atama(con, yeni_id, aday_uid, atayan_kullanici_id=1)
        ok('B02 create+provision+sorumlu ok', sr.get('ok'), str(sr))
        con.commit()
    except Exception as e:
        con.rollback()
        ok('B02 create+provision+sorumlu ok', False, str(e))

    row = con.execute(
        """
        SELECT cs.id FROM cari_sorumlu cs
        WHERE cs.cari_id=(SELECT id FROM nexgen_cari WHERE cari_kod=?)
          AND cs.sorumluluk_rolu='ANA' AND cs.aktif=1
        """,
        (kod,),
    ).fetchone()
    ok('B03 ANA mapping exists', row is not None)
    con.close()


def test_update_does_not_clear_sorumlu(tmp_db: str) -> None:
    from modules.nexgen.cari_genel_bilgi_service import update_cari_genel

    con = sqlite3.connect(tmp_db)
    con.row_factory = sqlite3.Row
    row = con.execute(
        """
        SELECT c.id, COUNT(cs.id) AS n
        FROM nexgen_cari c
        JOIN cari_sorumlu cs ON cs.cari_id=c.id AND cs.aktif=1
        WHERE c.aktif=1
        GROUP BY c.id
        HAVING n > 0
        LIMIT 1
        """
    ).fetchone()
    if not row:
        ok('E01 update sorumlu preserved', True, 'SKIP no assigned cari')
        con.close()
        return
    cid = int(row['id'])
    before = con.execute(
        'SELECT COUNT(*) FROM cari_sorumlu WHERE cari_id=? AND aktif=1', (cid,),
    ).fetchone()[0]
    update_cari_genel(con, cid, {'telefon': '555-RESP-TEST'}, 1, {'*'})
    con.commit()
    after = con.execute(
        'SELECT COUNT(*) FROM cari_sorumlu WHERE cari_id=? AND aktif=1', (cid,),
    ).fetchone()[0]
    ok('E01 update sorumlu preserved', before == after, f'{before}->{after}')
    con.close()


def test_backfill_idempotent(tmp_db: str) -> None:
    from modules.nexgen.cari_sorumlu_service import ensure_ana_sorumlu_atama, get_kullanici_cari_kapsami

    con = sqlite3.connect(tmp_db)
    con.row_factory = sqlite3.Row

    aday = con.execute(
        """
        SELECT sk.Id FROM sistem_kullanici sk
        JOIN sistem_rol_yetki ry ON ry.RolId=sk.RolId
        JOIN sistem_yetki y ON y.Id=ry.YetkiId
        WHERE sk.Aktif=1 AND y.Kod='cari360.view_own' AND ry.can_view=1
        LIMIT 1
        """
    ).fetchone()
    if not aday:
        ok('G01 backfill setup', False, 'no view_own user')
        con.close()
        return
    uid = int(aday['Id'])
    yk = {'cari360.view_own:can_view'}

    # 3 temp cari — sorumlusuz (backfill simülasyonu)
    targets: list[int] = []
    for i, kod in enumerate(('120.NX.RB01', '120.NX.RB02', '120.NX.RB03'), start=1):
        con.execute('DELETE FROM cari_sorumlu WHERE cari_id IN (SELECT id FROM nexgen_cari WHERE cari_kod=?)', (kod,))
        con.execute('DELETE FROM nexgen_cari WHERE cari_kod=?', (kod,))
        con.execute(
            'INSERT INTO nexgen_cari (cari_kod, unvan, aktif) VALUES (?,?,1)',
            (kod, f'BACKFILL TEST {i}'),
        )
        targets.append(int(con.execute('SELECT last_insert_rowid()').fetchone()[0]))
    con.commit()
    ok('G01 backfill setup', len(targets) == 3, f'n={len(targets)}')

    pre = len(get_kullanici_cari_kapsami(con, uid, yk).get('cari_id_listesi') or [])
    other_before = con.execute(
        'SELECT COUNT(*) FROM cari_sorumlu WHERE aktif=1 AND kullanici_id<>?',
        (uid,),
    ).fetchone()[0]

    con.execute('BEGIN IMMEDIATE')
    for cid in targets:
        r = ensure_ana_sorumlu_atama(con, cid, uid, atama_notu='test backfill')
        ok(f'G02 apply cari {cid}', r.get('ok'), r.get('hata', ''))
    con.commit()

    post = len(get_kullanici_cari_kapsami(con, uid, yk).get('cari_id_listesi') or [])
    ok('G03 scope increased', post == pre + 3, f'{pre}->{post}')

    other_after = con.execute(
        'SELECT COUNT(*) FROM cari_sorumlu WHERE aktif=1 AND kullanici_id<>?',
        (uid,),
    ).fetchone()[0]
    ok('G04 other mappings unchanged', other_before == other_after)

    # second apply idempotent
    con.execute('BEGIN IMMEDIATE')
    noop = 0
    for cid in targets:
        r = ensure_ana_sorumlu_atama(con, cid, uid)
        if r.get('noop'):
            noop += 1
    con.commit()
    ok('G05 second apply noop x3', noop == 3, f'noop={noop}')

    ic = con.execute('PRAGMA integrity_check').fetchone()[0]
    ok('G06 integrity ok', ic == 'ok', ic)
    con.close()


def test_no_duplicate_ana(tmp_db: str) -> None:
    from modules.nexgen.cari_sorumlu_service import atama_ekle, ensure_ana_sorumlu_atama

    con = sqlite3.connect(tmp_db)
    con.row_factory = sqlite3.Row
    cid = con.execute(
        'SELECT id FROM nexgen_cari WHERE aktif=1 LIMIT 1'
    ).fetchone()[0]
    uid = con.execute(
        'SELECT Id FROM sistem_kullanici WHERE Aktif=1 LIMIT 1'
    ).fetchone()[0]
    uid2 = con.execute(
        'SELECT Id FROM sistem_kullanici WHERE Aktif=1 LIMIT 1 OFFSET 1'
    ).fetchone()[0]

    # clean ANA for test cari
    con.execute(
        "UPDATE cari_sorumlu SET aktif=0, bitis_tarihi=date('now') "
        "WHERE cari_id=? AND sorumluluk_rolu='ANA' AND aktif=1",
        (cid,),
    )
    con.commit()

    r1 = ensure_ana_sorumlu_atama(con, int(cid), int(uid))
    con.commit()
    ok('F01 first ANA ok', r1.get('ok'))
    r2 = atama_ekle(con, int(cid), int(uid2), 'ANA')
    ok('F02 duplicate ANA blocked', not r2.get('ok'))
    r3 = ensure_ana_sorumlu_atama(con, int(cid), int(uid))
    ok('F03 same user idempotent', r3.get('ok') and r3.get('noop'))
    con.close()


def test_yonetim_dom() -> None:
    tpl = ROOT / 'app' / 'templates' / 'nexgen' / 'yonetim.html'
    src = tpl.read_text(encoding='utf-8')
    ok('H01 cari-modal-sorumlu field', 'id="cari-modal-sorumlu"' in src)
    ok('H02 create sorumlu wrap', 'id="cari-create-sorumlu-wrap"' in src)
    ok('H03 sorumlu required validation', 'Müşteri temsilcisi (sorumlu) zorunlu' in src)
    ok('H04 sorumlu_kullanici_id payload', 'sorumlu_kullanici_id' in src)


def main() -> int:
    sha_before = sha256(CANONICAL)
    print('CANONICAL SHA BEFORE:', sha_before)

    tmpdir = tempfile.mkdtemp(prefix='cari_mo_resp_')
    tmp_db = os.path.join(tmpdir, 'test.db')
    shutil.copy2(CANONICAL, tmp_db)

    test_create_requires_sorumlu(tmp_db)
    test_update_does_not_clear_sorumlu(tmp_db)
    test_backfill_idempotent(tmp_db)
    test_no_duplicate_ana(tmp_db)
    test_yonetim_dom()

    sha_after = sha256(CANONICAL)
    ok('SHA canonical unchanged', sha_before == sha_after)

    shutil.rmtree(tmpdir, ignore_errors=True)

    fails = [r for r in results if not r[1]]
    print('\n=== SUMMARY ===')
    print(f'PASS {sum(1 for r in results if r[1])} / {len(results)}')
    if fails:
        for n, _, note in fails:
            print(' FAIL', n, note)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
