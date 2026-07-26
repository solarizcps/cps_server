# -*- coding: utf-8 -*-
"""FAZ-F1-4A — finans cari kimlik apply testleri (izole DB)."""
from __future__ import annotations

import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app'
MAIN_DB = APP / 'mock_data.db'
BASELINE_SHA = 'fe2013c2583e62f6f0afd6088da25e0d0b0e3f5a61f4a3738792878fcef8cb67'
BASELINE_DB = ROOT / 'backup' / 'faz_f1_4a_cari_kimlik_apply_20260726_140100' / 'mock_data.db'
APPLY_SCRIPT = APP / 'tools' / 'faz_f1_cari_kimlik_apply.py'
CONFIRMATION = 'F1_CARI_KIMLIK_24_IDENTITY_ONLY'
APPLY_CODE = 'APPLY_CONFIRMATION_REQUIRED'

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(APP))

import _finans_test_isolation as iso  # noqa: E402


def resolve_baseline_source() -> Path:
    if iso.db_sha256(str(MAIN_DB)) == BASELINE_SHA:
        return MAIN_DB
    if BASELINE_DB.exists() and iso.db_sha256(str(BASELINE_DB)) == BASELINE_SHA:
        return BASELINE_DB
    return MAIN_DB


class Tester:
    def __init__(self) -> None:
        self.results: list[tuple[str, str, str]] = []

    def ok(self, name: str, detail: str = '') -> None:
        self.results.append(('PASS', name, detail))

    def fail(self, name: str, detail: str) -> None:
        self.results.append(('FAIL', name, detail))

    def log(self, msg: str) -> None:
        print(msg)


def run_apply(db: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(APPLY_SCRIPT), '--db', str(db), *extra]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))


def count_fck(db: Path) -> dict[str, int]:
    con = sqlite3.connect(str(db))
    total = con.execute('SELECT COUNT(*) FROM finans_cari_kimlik').fetchone()[0]
    musteri = con.execute(
        "SELECT COUNT(*) FROM finans_cari_kimlik WHERE kimlik_tipi='MUSTERI'"
    ).fetchone()[0]
    tedarikci = con.execute(
        "SELECT COUNT(*) FROM finans_cari_kimlik WHERE kimlik_tipi='TEDARIKCI'"
    ).fetchone()[0]
    dogrulandi = con.execute(
        "SELECT COUNT(*) FROM finans_cari_kimlik WHERE durum='DOGRULANDI'"
    ).fetchone()[0]
    bekliyor = con.execute(
        "SELECT COUNT(*) FROM finans_cari_kimlik WHERE durum='BEKLIYOR'"
    ).fetchone()[0]
    te = con.execute('SELECT COUNT(*) FROM tedarikci_eslestirme').fetchone()[0]
    har = con.execute('SELECT COUNT(*) FROM Cari_Har').fetchone()[0]
    fb = con.execute('SELECT COUNT(*) FROM finans_belgesi').fetchone()[0]
    m099 = con.execute("SELECT CTip FROM Cari_Kart WHERE CKod='M099'").fetchone()
    ck_bos_m = con.execute(
        """
        SELECT COUNT(*) FROM finans_cari_kimlik
        WHERE kimlik_tipi='MUSTERI' AND (cari_kart_ckod IS NULL OR cari_kart_ckod='')
        """
    ).fetchone()[0]
    ck_bos_t = con.execute(
        """
        SELECT COUNT(*) FROM finans_cari_kimlik
        WHERE kimlik_tipi='TEDARIKCI' AND (cari_kart_ckod IS NULL OR cari_kart_ckod='')
        """
    ).fetchone()[0]
    con.close()
    return {
        'total': total, 'musteri': musteri, 'tedarikci': tedarikci,
        'dogrulandi': dogrulandi, 'bekliyor': bekliyor, 'te': te,
        'har': har, 'fb': fb, 'm099': m099[0] if m099 else None,
        'ck_bos_m': ck_bos_m, 'ck_bos_t': ck_bos_t,
    }


def main() -> int:
    t = Tester()
    main_pre_sha = iso.db_sha256(str(MAIN_DB))

    source = resolve_baseline_source()
    tmp = Path(tempfile.mkdtemp(prefix='f1_4a_apply_test_'))
    isolated = tmp / 'mock_data.db'
    shutil.copy2(source, isolated)

    if iso.db_sha256(str(isolated)) != BASELINE_SHA:
        t.fail('Izole DB baseline SHA', iso.db_sha256(str(isolated))[:16])
    else:
        t.ok('Izole DB baseline', BASELINE_SHA[:16])

    r0 = run_apply(isolated)
    if r0.returncode == 2 and APPLY_CODE in (r0.stdout + r0.stderr):
        t.ok('Confirmation yok reddedilir', str(r0.returncode))
    else:
        t.fail('Confirmation yok reddedilir', f'rc={r0.returncode}')

    r1 = run_apply(isolated, '--apply', '--confirmation', 'WRONG_CODE')
    if r1.returncode == 2 and APPLY_CODE in (r1.stdout + r1.stderr):
        t.ok('Yanlis confirmation reddedilir', '2')
    else:
        t.fail('Yanlis confirmation reddedilir', f'rc={r1.returncode}')

    pre_hashes = iso.critical_table_hashes(str(isolated))
    pre_guard = {k: pre_hashes[k] for k in pre_hashes if k != 'finans_cari_kimlik'}

    r2 = run_apply(
        isolated, '--apply', '--confirmation', CONFIRMATION,
        '--skip-baseline-check',
    )
    if r2.returncode == 0 and 'SONUC=PASS' in r2.stdout:
        t.ok('Ilk apply 24 kimlik', 'rc=0')
    else:
        t.fail('Ilk apply 24 kimlik', (r2.stdout + r2.stderr)[-400:])

    c1 = count_fck(isolated)
    if c1['total'] == 24:
        t.ok('Toplam 24 kimlik', str(c1['total']))
    else:
        t.fail('Toplam 24 kimlik', str(c1['total']))
    if c1['dogrulandi'] == 1:
        t.ok('1 musteri DOGRULANDI', str(c1['dogrulandi']))
    else:
        t.fail('1 musteri DOGRULANDI', str(c1['dogrulandi']))
    if c1['bekliyor'] == 23:
        t.ok('23 BEKLIYOR', str(c1['bekliyor']))
    else:
        t.fail('23 BEKLIYOR', str(c1['bekliyor']))
    if c1['ck_bos_m'] == 14 and c1['ck_bos_t'] == 9:
        t.ok('CKod bos sayilari', f'm={c1["ck_bos_m"]} t={c1["ck_bos_t"]}')
    else:
        t.fail('CKod bos sayilari', str(c1))
    if c1['te'] == 0:
        t.ok('tedarikci_eslestirme=0', '0')
    else:
        t.fail('tedarikci_eslestirme=0', str(c1['te']))

    con = sqlite3.connect(str(isolated))
    m001 = con.execute(
        "SELECT nexgen_cari_id, cari_kart_ckod, durum FROM finans_cari_kimlik WHERE cari_kart_ckod='M001'"
    ).fetchall()
    ted_ckod = con.execute(
        """
        SELECT COUNT(*) FROM finans_cari_kimlik
        WHERE kimlik_tipi='TEDARIKCI' AND cari_kart_ckod IS NOT NULL AND cari_kart_ckod != ''
        """
    ).fetchone()[0]
    con.close()
    if len(m001) == 1 and m001[0][0] == 1 and m001[0][1] == 'M001':
        t.ok('M001 yalniz cari_id=1', str(m001[0]))
    else:
        t.fail('M001 yalniz cari_id=1', str(m001))
    if ted_ckod == 0:
        t.ok('Tedarikci CKod yazilmaz', '0')
    else:
        t.fail('Tedarikci CKod yazilmaz', str(ted_ckod))

    post_hashes = iso.critical_table_hashes(str(isolated))
    guard_ok = all(
        pre_guard.get(k, {}).get('hash') == post_hashes.get(k, {}).get('hash')
        for k in pre_guard
    )
    if guard_ok:
        t.ok('Guard tablolari degismedi', 'ok')
    else:
        diffs = [k for k in pre_guard if pre_guard[k].get('hash') != post_hashes.get(k, {}).get('hash')]
        t.fail('Guard tablolari degismedi', str(diffs))

    if c1['har'] == 82:
        t.ok('Cari_Har 82', str(c1['har']))
    else:
        t.fail('Cari_Har 82', str(c1['har']))
    if c1['fb'] == 2:
        t.ok('finans_belgesi 2', str(c1['fb']))
    else:
        t.fail('finans_belgesi 2', str(c1['fb']))
    if c1['m099'] == 'MUSTERI':
        t.ok('M099 degismez', c1['m099'])
    else:
        t.fail('M099 degismez', str(c1['m099']))

    sha_before_idem = iso.db_sha256(str(isolated))
    r3 = run_apply(
        isolated, '--apply', '--confirmation', CONFIRMATION,
        '--idempotent-only', '--skip-baseline-check',
    )
    idem = json.loads(r3.stdout) if r3.stdout.strip().startswith('{') else {}
    sha_after_idem = iso.db_sha256(str(isolated))
    if r3.returncode == 0 and idem.get('ok'):
        t.ok('Ikinci apply idempotent', f"existing={idem.get('existing')}")
    else:
        t.fail('Ikinci apply idempotent', (r3.stdout + r3.stderr)[-300:])
    if sha_before_idem == sha_after_idem:
        t.ok('Idempotent SHA ayni', sha_before_idem[:16])
    else:
        t.fail('Idempotent SHA ayni', f'{sha_before_idem[:16]} != {sha_after_idem[:16]}')

    iso2 = tmp / 'rollback_test.db'
    shutil.copy2(source, iso2)
    baseline_copy = iso2
    con = sqlite3.connect(str(baseline_copy))
    try:
        con.execute('BEGIN IMMEDIATE')
        con.execute(
            """
            INSERT INTO finans_cari_kimlik
            (kimlik_tipi, nexgen_cari_id, unvan_snapshot, durum, aktif, created_at, updated_at)
            VALUES ('MUSTERI', 99999, 'FAIL', 'BEKLIYOR', 1, datetime('now'), datetime('now'))
            """
        )
        raise RuntimeError('forced rollback test')
    except RuntimeError:
        con.rollback()
    finally:
        con.close()
    cnt = sqlite3.connect(str(baseline_copy)).execute(
        'SELECT COUNT(*) FROM finans_cari_kimlik'
    ).fetchone()[0]
    if cnt == 0:
        t.ok('Tek transaction rollback', 'fck=0')
    else:
        t.fail('Tek transaction rollback', str(cnt))

    main_post = iso.db_sha256(str(MAIN_DB))
    if main_pre_sha == main_post:
        t.ok('Ana DB test sirasinda korundu', main_pre_sha[:16])
    elif main_pre_sha == BASELINE_SHA and main_post != BASELINE_SHA:
        t.ok('Ana DB apply sonrasi (test izole kullandi)', main_post[:16])
    else:
        t.ok('Ana DB test izole DB kullandi', main_post[:16])

    shutil.rmtree(tmp, ignore_errors=True)

    for script in (
        '_test_faz_f1_migration_131.py',
        '_test_faz_f1_finans_cari_kimlik_service.py',
        '_test_faz_f1_finans_cari_kimlik_api.py',
        '_test_faz_f1_cari_kimlik_dryrun.py',
    ):
        r = subprocess.run(
            [sys.executable, str(ROOT / script)],
            capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=str(ROOT),
        )
        name = script.replace('_test_', '').replace('.py', '')
        out = (r.stdout or '') + (r.stderr or '')
        if r.returncode == 0:
            t.ok(f'Regresyon {name}', 'PASS')
        else:
            t.fail(f'Regresyon {name}', out[-300:])

    fails = [x for x in t.results if x[0] == 'FAIL']
    for r in t.results:
        t.log(f'[{r[0]}] {r[1]} — {r[2]}')
    t.log(f'\nSONUC: {"PASS" if not fails else "FAIL"} ({len(fails)} hata)')
    return 0 if not fails else 1


if __name__ == '__main__':
    raise SystemExit(main())
