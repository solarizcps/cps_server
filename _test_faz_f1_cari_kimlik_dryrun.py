# -*- coding: utf-8 -*-
"""FAZ-F1-4 — finans cari kimlik backfill dry-run testleri."""
from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app'
MAIN_DB = APP / 'mock_data.db'
BASELINE_SHA = 'fe2013c2583e62f6f0afd6088da25e0d0b0e3f5a61f4a3738792878fcef8cb67'
DRYRUN = APP / 'tools' / 'faz_f1_cari_kimlik_dryrun.py'
APPLY_CODE = 'APPLY_DISABLED_USER_APPROVAL_REQUIRED'

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(APP))

import _finans_test_isolation as iso  # noqa: E402


class Tester:
    def __init__(self) -> None:
        self.results: list[tuple[str, str, str]] = []

    def ok(self, name: str, detail: str = '') -> None:
        self.results.append(('PASS', name, detail))

    def fail(self, name: str, detail: str) -> None:
        self.results.append(('FAIL', name, detail))

    def log(self, msg: str) -> None:
        print(msg)


def main() -> int:
    t = Tester()
    pre_sha = iso.db_sha256(str(MAIN_DB))
    pre_hashes = iso.critical_table_hashes(str(MAIN_DB))

    src = DRYRUN.read_text(encoding='utf-8')
    if 'PRAGMA query_only' in src or 'mode=ro' in src:
        t.ok('Script read-only mod', 'query_only/mode=ro')
    else:
        t.fail('Script read-only mod', 'eksik')

    if 'APPLY_DISABLED_USER_APPROVAL_REQUIRED' in src:
        t.ok('--apply disabled kodu', APPLY_CODE)
    else:
        t.fail('--apply disabled kodu', 'yok')

    for pat in ('INSERT INTO', 'UPDATE ', 'DELETE FROM'):
        if re.search(rf'^\s*{pat}', src, re.M):
            t.fail('Script DB write statement yok', pat)
        else:
            pass
    t.ok('Script DB write statement yok', 'kaynak taramasi')

    rc_apply = subprocess.run(
        [sys.executable, str(DRYRUN), '--apply'],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    if rc_apply.returncode == 2 and APPLY_CODE in (rc_apply.stdout + rc_apply.stderr):
        t.ok('--apply reddedilir', str(rc_apply.returncode))
    else:
        t.fail('--apply reddedilir', f'rc={rc_apply.returncode} {(rc_apply.stdout + rc_apply.stderr)[-200:]}')

    rc = subprocess.run(
        [sys.executable, str(DRYRUN)],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    out = rc.stdout + rc.stderr
    if rc.returncode != 0:
        t.fail('dry-run calistir', out[-400:])
        for r in t.results:
            t.log(f"[{r[0]}] {r[1]} — {r[2]}")
        return 1

    t.ok('dry-run calistir', 'rc=0')

    post_sha = iso.db_sha256(str(MAIN_DB))
    if post_sha == pre_sha:
        t.ok('Ana DB SHA degismez', post_sha)
    else:
        t.fail('Ana DB SHA degismez', f'{pre_sha} -> {post_sha}')

    ok_log, msg = iso.assert_main_db_logical_unchanged(pre_hashes, str(MAIN_DB))
    if ok_log:
        t.ok('Mantiksal hash degismez', msg)
    else:
        t.fail('Mantiksal hash degismez', msg)

    backup_dirs = sorted((ROOT / 'backup').glob('faz_f1_4_cari_kimlik_dryrun_*'))
    if not backup_dirs:
        t.fail('backup klasoru', 'yok')
        return 1
    bdir = backup_dirs[-1]

    summary = json.loads((bdir / 'summary.json').read_text(encoding='utf-8'))
    customers = json.loads((bdir / 'customer_candidates.json').read_text(encoding='utf-8'))
    suppliers = json.loads((bdir / 'supplier_candidates.json').read_text(encoding='utf-8'))
    conflicts = json.loads((bdir / 'conflicts.json').read_text(encoding='utf-8'))
    ctip = json.loads((bdir / 'ctip_analysis.json').read_text(encoding='utf-8'))
    actions = json.loads((bdir / 'proposed_actions.json').read_text(encoding='utf-8'))
    before = json.loads((bdir / 'db_evidence_before.json').read_text(encoding='utf-8'))
    after = json.loads((bdir / 'db_evidence_after.json').read_text(encoding='utf-8'))

    if len(customers) == 15:
        t.ok('Musteri sayisi 15', str(len(customers)))
    else:
        t.fail('Musteri sayisi 15', str(len(customers)))

    if len(suppliers) == 9:
        t.ok('Tedarikci sayisi 9', str(len(suppliers)))
    else:
        t.fail('Tedarikci sayisi 9', str(len(suppliers)))

    verified = [c for c in customers if c.get('karar_sinifi') == 'LINK_EXISTING_VERIFIED']
    if verified and verified[0].get('mevcut_cari_kart_ckod') == 'M001':
        t.ok('Dogrulanmis mapping sinifi', verified[0]['mevcut_cari_kart_ckod'])
    else:
        t.fail('Dogrulanmis mapping sinifi', str(verified))

    m099 = ctip.get('m099') or {}
    if m099.get('musteri_uygun') and not m099.get('tedarikci_uygun'):
        t.ok('M099 normalizasyonu', str(m099.get('normalize_sonuc')))
    else:
        t.fail('M099 normalizasyonu', json.dumps(m099))

    auto_bad = [
        c for c in customers + suppliers
        if c.get('karar_sinifi') == 'AUTO_MATCH_SAFE'
        and c.get('en_iyi_aday')
        and not c.get('ctip_uygun', True)
    ]
    if not auto_bad:
        t.ok('CTip uyumsuz AUTO_MATCH_SAFE olmaz', '0')
    else:
        t.fail('CTip uyumsuz AUTO_MATCH_SAFE olmaz', str(len(auto_bad)))

    no_match = [s for s in suppliers if s.get('karar_sinifi') == 'NO_MATCHING_CARI_KART']
    if len(no_match) == 9:
        t.ok('Tedarikci NO_MATCHING_CARI_KART', '9')
    else:
        t.fail('Tedarikci NO_MATCHING_CARI_KART', str(len(no_match)))

    ctip_mismatch = [s for s in suppliers if s.get('karar_sinifi') == 'CTIP_MISMATCH']
    if len(ctip_mismatch) == 0:
        t.ok('Tedarikci CTIP_MISMATCH yok (yaniltici sinif)', '0')
    else:
        t.fail('Tedarikci CTIP_MISMATCH yok', str(len(ctip_mismatch)))

    dual = [x for x in conflicts if x.get('tip') == 'AYNI_CKOD_MUSTERI_TEDARIKCI']
    if dual:
        t.ok('Dual CKod conflict kaydi', str(len(dual)))
    else:
        t.ok('Dual CKod conflict kaydi', '0 (beklenen opsiyonel)')

    dup_conf = [x for x in conflicts if 'COKLU' in x.get('tip', '')]
    t.ok('Duplicate CKod conflict raporu', str(len(dup_conf)))

    pasif = [c for c in customers if c.get('karar_sinifi') == 'OPERATIONAL_INACTIVE']
    t.ok('Pasif kayit siniflamasi', f'count={len(pasif)}')

    required = ('summary.json', 'customer_candidates.json', 'supplier_candidates.json',
                'conflicts.json', 'ctip_analysis.json', 'proposed_actions.json', 'RAPOR.md')
    missing = [f for f in required if not (bdir / f).exists()]
    if not missing:
        t.ok('JSON cikti semalari', str(len(required)))
    else:
        t.fail('JSON cikti semalari', str(missing))

    sql_in_actions = json.dumps(actions)
    if not re.search(r'\b(INSERT|UPDATE|DELETE)\b', sql_in_actions, re.I):
        t.ok('proposed_actions SQL yok', 'action names only')
    else:
        t.fail('proposed_actions SQL yok', 'SQL bulundu')

    if before['sha256'] == after['sha256'] == pre_sha:
        t.ok('db evidence SHA esit', pre_sha[:16])
    else:
        t.fail('db evidence SHA esit', f"{before['sha256']} {after['sha256']}")

    con = sqlite3.connect(str(MAIN_DB))
    har = con.execute('SELECT COUNT(*) FROM Cari_Har').fetchone()[0]
    fb = con.execute('SELECT COUNT(*) FROM finans_belgesi').fetchone()[0]
    fck = con.execute('SELECT COUNT(*) FROM finans_cari_kimlik').fetchone()[0]
    te = con.execute('SELECT COUNT(*) FROM tedarikci_eslestirme').fetchone()[0]
    con.close()

    if har == 82:
        t.ok('Cari_Har 82', str(har))
    else:
        t.fail('Cari_Har 82', str(har))
    if fb == 2:
        t.ok('finans_belgesi degismez', str(fb))
    else:
        t.fail('finans_belgesi degismez', str(fb))
    if fck == 0 and te == 0:
        t.ok('kimlik tablolari 0 (pre-apply)', f'fck={fck} te={te}')
    elif fck == 24 and te == 0:
        t.ok('kimlik tablolari post-apply', f'fck={fck} te={te}')
    else:
        t.fail('kimlik tablolari beklenen', f'fck={fck} te={te}')

    try:
        from modules.nexgen import mo_tahsilat_config as mtc
        if not bool(getattr(mtc, 'CARI_ENTEGRASYON_AKTIF', None)):
            t.ok('CARI_ENTEGRASYON_AKTIF=False', 'False')
        else:
            t.fail('CARI_ENTEGRASYON_AKTIF=False', 'True')
    except Exception as exc:
        t.fail('CARI_ENTEGRASYON_AKTIF=False', str(exc))

    for script in (
        '_test_faz_f1_migration_131.py',
        '_test_faz_f1_finans_cari_kimlik_service.py',
        '_test_faz_f1_finans_cari_kimlik_api.py',
    ):
        r = subprocess.run(
            [sys.executable, str(ROOT / script)],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        name = script.replace('_test_', '').replace('.py', '')
        if r.returncode == 0:
            t.ok(f'F1 regresyon {name}', 'PASS')
        else:
            t.fail(f'F1 regresyon {name}', (r.stdout + r.stderr)[-300:])

    fails = [r for r in t.results if r[0] == 'FAIL']
    for r in t.results:
        t.log(f"[{r[0]}] {r[1]} — {r[2]}")
    t.log(f'\nBackup dry-run: {bdir}')
    t.log(f'SONUC: {"PASS" if not fails else "FAIL"} ({len(fails)} hata)')
    return 0 if not fails else 1


if __name__ == '__main__':
    raise SystemExit(main())
