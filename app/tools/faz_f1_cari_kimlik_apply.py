# -*- coding: utf-8 -*-
"""FAZ-F1-4A — Finans cari kimlik kontrollü backfill apply.

Kullanım (yalnız onaylı):
    python app/tools/faz_f1_cari_kimlik_apply.py --apply --confirmation F1_CARI_KIMLIK_24_IDENTITY_ONLY

Varsayılan mod yazma yapmaz.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'
DEFAULT_DB = APP / 'mock_data.db'
BASELINE_SHA = 'fe2013c2583e62f6f0afd6088da25e0d0b0e3f5a61f4a3738792878fcef8cb67'
CONFIRMATION_CODE = 'F1_CARI_KIMLIK_24_IDENTITY_ONLY'
APPLY_CONFIRMATION_REQUIRED = 'APPLY_CONFIRMATION_REQUIRED'
SYNC_CARI_ID = 1
USER_ID = 1

DRYRUN_BACKUP = ROOT / 'backup' / 'faz_f1_4_cari_kimlik_dryrun_20260726_135358'

if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.nexgen.finans_cari_kimlik_service import (  # noqa: E402
    FinansCariKimlikError,
    create_kimlik_musteri,
    create_kimlik_tedarikci,
    sync_musteri_ckod_from_eslestirme,
)

CRITICAL_TABLES = (
    'Cari_Har',
    'finans_belgesi',
    'finans_cari_kimlik',
    'tedarikci_eslestirme',
    'cari_eslestirme',
    'Cari_Kart',
    'sistem_yetki',
    'sistem_rol_yetki',
    'schema_migrations',
)

GUARD_TABLES = (
    'Cari_Har',
    'finans_belgesi',
    'tedarikci_eslestirme',
    'cari_eslestirme',
    'Cari_Kart',
    'sistem_yetki',
    'sistem_rol_yetki',
    'schema_migrations',
)


def db_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def table_hashes(db_path: Path) -> dict[str, dict[str, Any]]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    out: dict[str, dict[str, Any]] = {}
    for t in CRITICAL_TABLES:
        rows = con.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall()
        cols = [d[0] for d in con.execute(f'SELECT * FROM "{t}" LIMIT 0').description]
        payload = [dict(zip(cols, row)) for row in rows]
        h = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        out[t] = {'count': len(rows), 'hash': h}
    con.close()
    return out


def collect_evidence(db_path: Path) -> dict[str, Any]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    fb = [dict(r) for r in con.execute(
        'SELECT id, belge_kodu, durum, posting_durumu FROM finans_belgesi ORDER BY id'
    ).fetchall()]
    m099 = dict(con.execute(
        "SELECT CKod, CTip, CName FROM Cari_Kart WHERE CKod='M099'"
    ).fetchone() or {})
    ce = [dict(r) for r in con.execute('SELECT * FROM cari_eslestirme ORDER BY id').fetchall()]
    fck_stats = con.execute(
        """
        SELECT kimlik_tipi, durum, COUNT(*) AS n,
               SUM(CASE WHEN cari_kart_ckod IS NULL OR cari_kart_ckod='' THEN 1 ELSE 0 END) AS ckod_bos
        FROM finans_cari_kimlik WHERE aktif=1
        GROUP BY kimlik_tipi, durum
        """
    ).fetchall()
    evidence = {
        'db_path': str(db_path),
        'sha256': db_sha256(db_path),
        'size_bytes': db_path.stat().st_size,
        'integrity_check': con.execute('PRAGMA integrity_check').fetchone()[0],
        'max_migration': con.execute(
            'SELECT MAX(CAST(version AS INTEGER)) FROM schema_migrations'
        ).fetchone()[0],
        'cari_har': con.execute('SELECT COUNT(*) FROM Cari_Har').fetchone()[0],
        'finans_belgesi': fb,
        'finans_cari_kimlik': con.execute('SELECT COUNT(*) FROM finans_cari_kimlik').fetchone()[0],
        'tedarikci_eslestirme': con.execute('SELECT COUNT(*) FROM tedarikci_eslestirme').fetchone()[0],
        'cari_eslestirme': ce,
        'nexgen_cari': con.execute('SELECT COUNT(*) FROM nexgen_cari').fetchone()[0],
        'nexgen_tedarikci': con.execute('SELECT COUNT(*) FROM nexgen_tedarikci').fetchone()[0],
        'cari_kart': con.execute('SELECT COUNT(*) FROM Cari_Kart').fetchone()[0],
        'm099': m099,
        'fck_breakdown': [dict(r) for r in fck_stats],
        'table_hashes': table_hashes(db_path),
    }
    con.close()
    try:
        from modules.nexgen import mo_tahsilat_config as mtc
        evidence['cari_entegrasyon_aktif'] = bool(getattr(mtc, 'CARI_ENTEGRASYON_AKTIF', False))
    except Exception:
        evidence['cari_entegrasyon_aktif'] = None
    return evidence


def validate_pre_apply(evidence: dict[str, Any], *, require_baseline: bool = True) -> None:
    if require_baseline and evidence['sha256'] != BASELINE_SHA:
        raise RuntimeError(f"Baseline SHA uyusmaz: {evidence['sha256']}")
    if evidence['integrity_check'] != 'ok':
        raise RuntimeError(f"integrity_check={evidence['integrity_check']}")
    if evidence['max_migration'] != 131:
        raise RuntimeError(f"migration={evidence['max_migration']}")
    if evidence['finans_cari_kimlik'] != 0:
        raise RuntimeError(f"finans_cari_kimlik={evidence['finans_cari_kimlik']} (beklenen 0)")
    if evidence['tedarikci_eslestirme'] != 0:
        raise RuntimeError('tedarikci_eslestirme != 0')
    if evidence['cari_har'] != 82:
        raise RuntimeError(f"Cari_Har={evidence['cari_har']}")
    if evidence['nexgen_cari'] != 15 or evidence['nexgen_tedarikci'] != 9:
        raise RuntimeError('nexgen sayilari uyusmaz')


def validate_post_apply(
    evidence: dict[str, Any],
    pre_guard_hashes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    con = sqlite3.connect(str(evidence['db_path']))
    con.row_factory = sqlite3.Row

    fck = evidence['finans_cari_kimlik']
    checks['finans_cari_kimlik_24'] = fck == 24

    musteri = con.execute(
        "SELECT COUNT(*) FROM finans_cari_kimlik WHERE kimlik_tipi='MUSTERI' AND aktif=1"
    ).fetchone()[0]
    tedarikci = con.execute(
        "SELECT COUNT(*) FROM finans_cari_kimlik WHERE kimlik_tipi='TEDARIKCI' AND aktif=1"
    ).fetchone()[0]
    checks['musteri_15'] = musteri == 15
    checks['tedarikci_9'] = tedarikci == 9

    dogrulandi = con.execute(
        "SELECT COUNT(*) FROM finans_cari_kimlik WHERE durum='DOGRULANDI' AND aktif=1"
    ).fetchone()[0]
    bekliyor = con.execute(
        "SELECT COUNT(*) FROM finans_cari_kimlik WHERE durum='BEKLIYOR' AND aktif=1"
    ).fetchone()[0]
    checks['dogrulandi_1'] = dogrulandi == 1
    checks['bekliyor_23'] = bekliyor == 23

    m001 = con.execute(
        """
        SELECT id, nexgen_cari_id, cari_kart_ckod, durum
        FROM finans_cari_kimlik
        WHERE cari_kart_ckod='M001' AND aktif=1
        """
    ).fetchall()
    checks['m001_yalniz_cari_1'] = (
        len(m001) == 1 and int(m001[0]['nexgen_cari_id']) == SYNC_CARI_ID
        and m001[0]['durum'] == 'DOGRULANDI'
    )

    ck_bos_m = con.execute(
        """
        SELECT COUNT(*) FROM finans_cari_kimlik
        WHERE kimlik_tipi='MUSTERI' AND aktif=1
          AND (cari_kart_ckod IS NULL OR cari_kart_ckod='')
        """
    ).fetchone()[0]
    ck_bos_t = con.execute(
        """
        SELECT COUNT(*) FROM finans_cari_kimlik
        WHERE kimlik_tipi='TEDARIKCI' AND aktif=1
          AND (cari_kart_ckod IS NULL OR cari_kart_ckod='')
        """
    ).fetchone()[0]
    checks['ckod_bos_musteri_14'] = ck_bos_m == 14
    checks['ckod_bos_tedarikci_9'] = ck_bos_t == 9
    checks['tedarikci_eslestirme_0'] = evidence['tedarikci_eslestirme'] == 0

    post_hashes = table_hashes(Path(evidence['db_path']))
    guard_ok = []
    guard_fail = []
    for t in GUARD_TABLES:
        if pre_guard_hashes.get(t) == post_hashes.get(t):
            guard_ok.append(t)
        else:
            guard_fail.append(t)
    checks['guard_tables_unchanged'] = guard_fail == []
    checks['guard_fail'] = guard_fail

    m099 = dict(con.execute("SELECT CTip FROM Cari_Kart WHERE CKod='M099'").fetchone() or {})
    checks['m099_musterti'] = m099.get('CTip') == 'MUSTERI'
    checks['integrity_ok'] = evidence['integrity_check'] == 'ok'
    checks['cari_har_82'] = evidence['cari_har'] == 82
    checks['finans_belgesi_2'] = len(evidence['finans_belgesi']) == 2

    con.close()
    failed = [k for k, v in checks.items() if v is False]
    checks['all_pass'] = not failed
    checks['failed'] = failed
    return checks


def run_apply_transaction(con: sqlite3.Connection) -> dict[str, Any]:
    stats = {
        'created_musteri': 0,
        'existing_musteri': 0,
        'created_tedarikci': 0,
        'existing_tedarikci': 0,
        'synced': 0,
        'sync_unchanged': 0,
        'sync_cari_id': SYNC_CARI_ID,
        'sync_ckod': 'M001',
    }

    cari_ids = [
        int(r[0]) for r in con.execute(
            'SELECT id FROM nexgen_cari WHERE aktif=1 ORDER BY id'
        ).fetchall()
    ]
    ted_ids = [
        int(r[0]) for r in con.execute(
            'SELECT id FROM nexgen_tedarikci WHERE aktif=1 ORDER BY id'
        ).fetchall()
    ]

    if len(cari_ids) != 15:
        raise RuntimeError(f'Beklenen 15 musteri, bulunan {len(cari_ids)}')
    if len(ted_ids) != 9:
        raise RuntimeError(f'Beklenen 9 tedarikci, bulunan {len(ted_ids)}')

    kimlik_before_sync: dict[int, str | None] = {}

    for cid in cari_ids:
        paket = create_kimlik_musteri(con, cid, user_id=USER_ID, commit=False)
        if paket.get('idempotent'):
            stats['existing_musteri'] += 1
        else:
            stats['created_musteri'] += 1
        kid = int(paket['id'])
        kimlik_before_sync[cid] = paket.get('updated_at')

    for tid in ted_ids:
        paket = create_kimlik_tedarikci(con, tid, user_id=USER_ID, commit=False)
        if paket.get('idempotent'):
            stats['existing_tedarikci'] += 1
        else:
            stats['created_tedarikci'] += 1

    sync_row = con.execute(
        """
        SELECT id, cari_kart_ckod, durum, updated_at
        FROM finans_cari_kimlik
        WHERE nexgen_cari_id=? AND kimlik_tipi=? AND aktif=1
        """,
        (SYNC_CARI_ID, 'MUSTERI'),
    ).fetchone()
    if not sync_row:
        raise RuntimeError(f'nexgen_cari_id={SYNC_CARI_ID} kimligi bulunamadi')
    kid = int(sync_row['id'])

    es = con.execute(
        """
        SELECT cari_kart_ckod FROM cari_eslestirme
        WHERE nexgen_cari_id=? AND aktif=1
          AND eslestirme_durumu IN ('DOGRULANDI', 'MANUEL')
        ORDER BY id LIMIT 1
        """,
        (SYNC_CARI_ID,),
    ).fetchone()
    expected_ckod = es['cari_kart_ckod'] if es else None

    if (
        expected_ckod
        and sync_row['cari_kart_ckod'] == expected_ckod
        and sync_row['durum'] == 'DOGRULANDI'
    ):
        stats['sync_unchanged'] += 1
        post = {
            'cari_kart_ckod': sync_row['cari_kart_ckod'],
            'durum': sync_row['durum'],
            'updated_at': sync_row['updated_at'],
        }
    else:
        sync_paket = sync_musteri_ckod_from_eslestirme(con, kid, user_id=USER_ID, commit=False)
        post = sync_paket
        stats['synced'] += 1

    if post.get('cari_kart_ckod') != 'M001' or post.get('durum') != 'DOGRULANDI':
        raise RuntimeError(f'M001 sync basarisiz: {post}')

    te_count = con.execute('SELECT COUNT(*) FROM tedarikci_eslestirme').fetchone()[0]
    if te_count != 0:
        raise RuntimeError(f'tedarikci_eslestirme yazildi: {te_count}')

    stats['total_kimlik'] = con.execute('SELECT COUNT(*) FROM finans_cari_kimlik').fetchone()[0]
    return stats


def create_backup(db_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(db_path, output_dir / 'mock_data.db')
    if DRYRUN_BACKUP.exists():
        src = DRYRUN_BACKUP / 'proposed_actions.json'
        if src.exists():
            shutil.copy2(src, output_dir / 'proposed_actions.json')
    shutil.copy2(Path(__file__), output_dir / 'faz_f1_cari_kimlik_apply.py')


def run_apply(
    db_path: Path,
    *,
    backup_dir: Path | None = None,
    require_baseline: bool = True,
    skip_backup: bool = False,
) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(str(db_path))

    pre = collect_evidence(db_path)
    validate_pre_apply(pre, require_baseline=require_baseline)
    pre_guard = {t: pre['table_hashes'][t] for t in GUARD_TABLES}

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    bdir = backup_dir or (ROOT / 'backup' / f'faz_f1_4a_cari_kimlik_apply_{ts}')

    if not skip_backup:
        create_backup(db_path, bdir)
        backup_sha = db_sha256(bdir / 'mock_data.db')
        if backup_sha != pre['sha256']:
            raise RuntimeError('Backup SHA dogrulanamadi')

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    stats: dict[str, Any] = {}
    try:
        con.execute('BEGIN IMMEDIATE')
        stats = run_apply_transaction(con)
        post_inline = {
            'fck': con.execute('SELECT COUNT(*) FROM finans_cari_kimlik').fetchone()[0],
            'te': con.execute('SELECT COUNT(*) FROM tedarikci_eslestirme').fetchone()[0],
            'har': con.execute('SELECT COUNT(*) FROM Cari_Har').fetchone()[0],
        }
        if post_inline['fck'] != 24 or post_inline['te'] != 0 or post_inline['har'] != 82:
            raise RuntimeError(f'Son kontrol basarisiz: {post_inline}')
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    post = collect_evidence(db_path)
    checks = validate_post_apply(post, pre_guard)

    result = {
        'ok': checks['all_pass'],
        'backup_dir': str(bdir),
        'pre_apply': pre,
        'post_apply': post,
        'stats': stats,
        'checks': checks,
        'pre_sha': pre['sha256'],
        'post_sha': post['sha256'],
    }

    if not skip_backup:
        (bdir / 'pre_apply_evidence.json').write_text(
            json.dumps(pre, ensure_ascii=False, indent=2, default=str), encoding='utf-8',
        )
        (bdir / 'post_apply_evidence.json').write_text(
            json.dumps(post, ensure_ascii=False, indent=2, default=str), encoding='utf-8',
        )
        (bdir / 'apply_result.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8',
        )

    if not checks['all_pass']:
        raise RuntimeError(f"Post-apply dogrulama basarisiz: {checks['failed']}")

    return result


def run_idempotent(db_path: Path) -> dict[str, Any]:
    pre = collect_evidence(db_path)
    pre_sha = pre['sha256']
    pre_guard = {t: pre['table_hashes'][t] for t in GUARD_TABLES}
    pre_fck_hash = pre['table_hashes']['finans_cari_kimlik']

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        con.execute('BEGIN IMMEDIATE')
        stats = run_apply_transaction(con)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    post = collect_evidence(db_path)
    post_sha = post['sha256']
    post_fck_hash = post['table_hashes']['finans_cari_kimlik']

    guard_same = all(
        pre_guard[t] == post['table_hashes'][t] for t in GUARD_TABLES
    )
    fck_same = pre_fck_hash == post_fck_hash

    expected = (
        stats['created_musteri'] == 0
        and stats['created_tedarikci'] == 0
        and stats['existing_musteri'] == 15
        and stats['existing_tedarikci'] == 9
        and stats['synced'] == 0
        and post['finans_cari_kimlik'] == 24
        and post['tedarikci_eslestirme'] == 0
    )

    return {
        'ok': expected and guard_same and fck_same and pre_sha == post_sha,
        'pre_sha': pre_sha,
        'post_sha': post_sha,
        'stats': stats,
        'guard_same': guard_same,
        'fck_hash_same': fck_same,
        'created': stats['created_musteri'] + stats['created_tedarikci'],
        'existing': stats['existing_musteri'] + stats['existing_tedarikci'],
        'synced_changed': stats['synced'],
    }


def build_report(
    *,
    backup_dir: Path,
    pre: dict[str, Any],
    post_first: dict[str, Any],
    post_idem: dict[str, Any],
    stats_first: dict[str, Any],
    stats_idem: dict[str, Any],
    checks: dict[str, Any],
) -> str:
    lines = [
        '# FAZ-F1-4A Finans Cari Kimlik Kontrollü Backfill Apply Raporu',
        '',
        f'**Backup:** `{backup_dir}`',
        f'**Confirmation:** `{CONFIRMATION_CODE}`',
        '',
        '## 1. Apply onayı ve confirmation',
        f'- Onay kodu: `{CONFIRMATION_CODE}`',
        '- Kapsam: 24 kimlik (15 MUSTERI + 9 TEDARIKCI), M001 sync, tedarikci_eslestirme yok',
        '',
        '## 2. Backup yolu',
        f'`{backup_dir}` — byte-level DB kopyası + pre_apply_evidence.json',
        '',
        '## 3. Apply öncesi kanıt',
        f"- SHA: `{pre['sha256']}`",
        f"- finans_cari_kimlik: {pre['finans_cari_kimlik']}",
        f"- Cari_Har: {pre['cari_har']}",
        '',
        '## 4. İlk apply sonucu',
        f"- created müşteri: {stats_first.get('created_musteri')}",
        f"- created tedarikçi: {stats_first.get('created_tedarikci')}",
        f"- M001 sync: {stats_first.get('synced')}",
        f"- post SHA: `{post_first['sha256']}`",
        '',
        '## 5. İkinci apply/idempotency sonucu',
        f"- created: {stats_idem.get('created', 0)}",
        f"- existing: {stats_idem.get('existing', 0)}",
        f"- synced_changed: {stats_idem.get('synced_changed', 0)}",
        f"- SHA önce=sonra: {stats_idem.get('pre_sha') == stats_idem.get('post_sha')}",
        '',
        '## 6–9. Kimlik durumları',
        f"- Toplam finans_cari_kimlik: {post_first['finans_cari_kimlik']}",
        f"- DOGRULANDI: 1 (nexgen_cari_id=1 → M001)",
        f"- BEKLIYOR: 23 (14 müşteri + 9 tedarikçi, CKod boş)",
        '',
        '## 10. tedarikci_eslestirme kanıtı',
        f"- Kayıt sayısı: {post_first['tedarikci_eslestirme']} (değişmedi)",
        '',
        '## 11. Güncellenmiş dry-run sınıflandırması',
        '- 9 tedarikçi: NO_MATCHING_CARI_KART (CTIP_MISMATCH yerine)',
        '',
        '## 12. Transaction/rollback kanıtı',
        '- Tek BEGIN IMMEDIATE → commit; hata durumunda rollback',
        '',
        '## 13. Test sonuçları',
        '- `_test_faz_f1_cari_kimlik_apply.py` + F1 regresyon',
        '',
        '## 14–17. Korunan tablolar',
        f"- Cari_Har: {pre['cari_har']} → {post_first['cari_har']}",
        f"- finans_belgesi: {len(pre['finans_belgesi'])} → {len(post_first['finans_belgesi'])}",
        f"- cari_eslestirme hash: korundu",
        f"- M099 CTip: `{post_first.get('m099', {}).get('CTip')}`",
        '',
        '## 18. DB SHA zaman çizelgesi',
        f"| Aşama | SHA |",
        f"|-------|-----|",
        f"| Pre-apply | `{pre['sha256'][:16]}...` |",
        f"| Post-apply | `{post_first['sha256'][:16]}...` |",
        f"| Post-idempotent | `{post_idem.get('post_sha', '')[:16]}...` |",
        '',
        '## 19. integrity_check',
        f"- {post_first['integrity_check']}",
        '',
        '## 20. Rollback planı',
        f"- Restore: `{backup_dir / 'mock_data.db'}`",
        '',
        '## 21. Bilinen riskler',
        '- 14 müşteri CKod boş — F1-5 UI/manuel eşleştirme gerekir',
        '- 9 tedarikçi CKod boş — manuel onay şart',
        '',
        '## 22. F1-5 UI öncesi kullanıcı onayı',
        '- Apply tamamlandı; F1-5 UI için ayrı onay bekleniyor',
        '',
        f'**Post-apply checks:** {json.dumps(checks.get("failed") or "ALL PASS")}',
    ]
    return '\n'.join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='FAZ-F1-4A finans cari kimlik apply')
    parser.add_argument('--db', default=str(DEFAULT_DB))
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--confirmation', default='')
    parser.add_argument('--idempotent-only', action='store_true',
                        help='Yalniz idempotent tekrar kosusu (backup yok)')
    parser.add_argument('--output-dir', default='')
    parser.add_argument('--skip-baseline-check', action='store_true',
                        help='Test izole DB icin baseline SHA kontrolunu atla')
    args = parser.parse_args(argv)

    if not args.apply:
        print(json.dumps({
            'ok': False,
            'error': {'code': APPLY_CONFIRMATION_REQUIRED, 'message': '--apply ve confirmation gerekli'},
        }, ensure_ascii=False))
        return 2

    if args.confirmation != CONFIRMATION_CODE:
        print(json.dumps({
            'ok': False,
            'error': {'code': APPLY_CONFIRMATION_REQUIRED, 'message': f'Beklenen: {CONFIRMATION_CODE}'},
        }, ensure_ascii=False))
        return 2

    db_path = Path(args.db)

    try:
        if args.idempotent_only:
            result = run_idempotent(db_path)
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0 if result['ok'] else 1

        backup_dir = Path(args.output_dir) if args.output_dir else None
        result = run_apply(
            db_path,
            backup_dir=backup_dir,
            require_baseline=not args.skip_baseline_check,
        )
        print(f"pre_sha={result['pre_sha']}")
        print(f"post_sha={result['post_sha']}")
        print(f"backup_dir={result['backup_dir']}")
        print(f"created={result['stats']['created_musteri']}+{result['stats']['created_tedarikci']}")
        print('SONUC=PASS')
        return 0
    except FinansCariKimlikError as exc:
        print(f'FAIL: {exc.code}: {exc}')
        return 1
    except Exception as exc:
        print(f'FAIL: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
