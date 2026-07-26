# -*- coding: utf-8 -*-
"""
FAZ-F1-1 — Migration 131 izole test paketi.

Ana DB'ye yazmaz. Temp DB kopyası üzerinde migration + constraint doğrulaması.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sqlite3
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app'
sys.path.insert(0, str(APP))

from migrations import nexgen_manifest as nm  # noqa: E402

import _finans_test_isolation as iso  # noqa: E402

MAIN_DB = str(APP / 'mock_data.db')
BASELINE_SHA = 'fe2013c2583e62f6f0afd6088da25e0d0b0e3f5a61f4a3738792878fcef8cb67'
BASELINE_CARI_HAR = 82
MIGRATION_VERSION = 131

YENI_YETKILER = (
    'nexgen.finans.cari_kimlik.view',
    'nexgen.finans.cari_kimlik.manage',
    'nexgen.finans.tedarikci_kimlik.manage',
)

PROTECTED_TABLES = ('cari_eslestirme', 'finans_belgesi', 'Cari_Har', 'Cari_Kart')


def _ts() -> str:
    return datetime.now().strftime('%Y%m%d_%H%M%S')


def _connect(db: str) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    return con


def _schema_snapshot(db: str) -> dict:
    con = _connect(db)
    out: dict = {'tables': {}, 'indexes': {}}
    for tbl in ('finans_cari_kimlik', 'tedarikci_eslestirme'):
        if not nm.tablo_var(con, tbl):
            out['tables'][tbl] = None
            continue
        cols = con.execute(f'PRAGMA table_info({tbl})').fetchall()
        out['tables'][tbl] = [
            {'cid': r['cid'], 'name': r['name'], 'type': r['type'],
             'notnull': r['notnull'], 'dflt_value': r['dflt_value'], 'pk': r['pk']}
            for r in cols
        ]
    for idx_row in con.execute(
        """
        SELECT name, tbl_name, sql FROM sqlite_master
        WHERE type='index' AND tbl_name IN ('finans_cari_kimlik','tedarikci_eslestirme')
        ORDER BY name
        """
    ):
        out['indexes'][idx_row['name']] = {
            'table': idx_row['tbl_name'],
            'sql': idx_row['sql'],
        }
    con.close()
    return out


def _finans_belgesi_summary(db: str) -> dict:
    con = _connect(db)
    rows = con.execute(
        'SELECT id, durum FROM finans_belgesi ORDER BY id'
    ).fetchall()
    by_durum: dict[str, int] = {}
    for r in rows:
        d = str(r['durum'])
        by_durum[d] = by_durum.get(d, 0) + 1
    con.close()
    return {'total': len(rows), 'by_durum': by_durum}


def _ctip_anomaly(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        "SELECT CKod, CTip FROM Cari_Kart WHERE typeof(CTip)='text' OR CTip='MUSTERI'"
    ).fetchall()
    return [dict(r) for r in rows]


def _pick_ids(con: sqlite3.Connection) -> dict:
    cari_ids = [int(r[0]) for r in con.execute('SELECT id FROM nexgen_cari ORDER BY id').fetchall()]
    tedarikci_ids = [int(r[0]) for r in con.execute(
        'SELECT id FROM nexgen_tedarikci ORDER BY id'
    ).fetchall()]
    ckods = [str(r[0]) for r in con.execute('SELECT CKod FROM Cari_Kart ORDER BY CKod').fetchall()]
    if len(cari_ids) < 2 or len(tedarikci_ids) < 2 or not ckods:
        raise RuntimeError('Test verisi yetersiz (nexgen_cari/tedarikci/Cari_Kart)')
    return {
        'cari1': cari_ids[0],
        'cari2': cari_ids[1],
        'ted1': tedarikci_ids[0],
        'ted2': tedarikci_ids[1],
        'ckod': ckods[0],
    }


def _expect_integrity(fn, label: str, results: list) -> None:
    try:
        fn()
        results.append(('FAIL', label, 'IntegrityError bekleniyordu'))
    except sqlite3.IntegrityError as exc:
        results.append(('PASS', label, str(exc)))


def _run_constraint_tests(db: str, results: list) -> None:
    con = _connect(db)
    con.execute('DELETE FROM finans_cari_kimlik')
    con.execute('DELETE FROM tedarikci_eslestirme')
    con.commit()
    ids = _pick_ids(con)

    con.execute(
        """
        INSERT INTO finans_cari_kimlik
            (kimlik_tipi, nexgen_cari_id, cari_kart_ckod, durum)
        VALUES ('MUSTERI', ?, ?, 'BEKLIYOR')
        """,
        (ids['cari1'], ids['ckod']),
    )
    con.execute(
        """
        INSERT INTO finans_cari_kimlik
            (kimlik_tipi, nexgen_tedarikci_id, cari_kart_ckod, durum)
        VALUES ('TEDARIKCI', ?, ?, 'BEKLIYOR')
        """,
        (ids['ted1'], ids['ckod']),
    )
    con.commit()
    results.append(('PASS', 'CTip=3 benzeri: ayni CKod MUSTERI+TEDARIKCI', ids['ckod']))

    _expect_integrity(
        lambda: (
            con.execute(
                """
                INSERT INTO finans_cari_kimlik
                    (kimlik_tipi, nexgen_cari_id, durum)
                VALUES ('MUSTERI', ?, 'BEKLIYOR')
                """,
                (ids['cari1'],),
            ),
            con.commit(),
        ),
        'Ayni nexgen_cari_id ikinci MUSTERI reddedilir',
        results,
    )
    con.rollback()

    _expect_integrity(
        lambda: (
            con.execute(
                """
                INSERT INTO finans_cari_kimlik
                    (kimlik_tipi, nexgen_tedarikci_id, durum)
                VALUES ('TEDARIKCI', ?, 'BEKLIYOR')
                """,
                (ids['ted1'],),
            ),
            con.commit(),
        ),
        'Ayni nexgen_tedarikci_id ikinci TEDARIKCI reddedilir',
        results,
    )
    con.rollback()

    _expect_integrity(
        lambda: (
            con.execute(
                """
                INSERT INTO finans_cari_kimlik
                    (kimlik_tipi, nexgen_cari_id, cari_kart_ckod, durum)
                VALUES ('MUSTERI', ?, ?, 'BEKLIYOR')
                """,
                (ids['cari2'], ids['ckod']),
            ),
            con.commit(),
        ),
        'Ayni CKod iki MUSTERI reddedilir',
        results,
    )
    con.rollback()

    _expect_integrity(
        lambda: (
            con.execute(
                """
                INSERT INTO finans_cari_kimlik
                    (kimlik_tipi, nexgen_tedarikci_id, cari_kart_ckod, durum)
                VALUES ('TEDARIKCI', ?, ?, 'BEKLIYOR')
                """,
                (ids['ted2'], ids['ckod']),
            ),
            con.commit(),
        ),
        'Ayni CKod iki TEDARIKCI reddedilir',
        results,
    )
    con.rollback()

    _expect_integrity(
        lambda: (
            con.execute(
                """
                INSERT INTO finans_cari_kimlik
                    (kimlik_tipi, nexgen_cari_id, nexgen_tedarikci_id, durum)
                VALUES ('MUSTERI', ?, ?, 'BEKLIYOR')
                """,
                (ids['cari2'], ids['ted2']),
            ),
            con.commit(),
        ),
        'MUSTERI + nexgen_tedarikci_id dolu reddedilir (CHECK)',
        results,
    )
    con.rollback()

    _expect_integrity(
        lambda: (
            con.execute(
                """
                INSERT INTO finans_cari_kimlik
                    (kimlik_tipi, nexgen_cari_id, durum)
                VALUES ('TEDARIKCI', ?, 'BEKLIYOR')
                """,
                (ids['cari2'],),
            ),
            con.commit(),
        ),
        'TEDARIKCI + nexgen_cari_id dolu reddedilir (CHECK)',
        results,
    )
    con.rollback()

    con.execute(
        """
        INSERT INTO tedarikci_eslestirme
            (nexgen_tedarikci_id, cari_kart_ckod, eslestirme_durumu, eslestirme_yontemi)
        VALUES (?, ?, 'DOGRULANDI', 'MANUEL')
        """,
        (ids['ted2'], ids['ckod']),
    )
    con.commit()

    _expect_integrity(
        lambda: (
            con.execute(
                """
                INSERT INTO tedarikci_eslestirme
                    (nexgen_tedarikci_id, eslestirme_durumu)
                VALUES (?, 'BEKLIYOR')
                """,
                (ids['ted2'],),
            ),
            con.commit(),
        ),
        'tedarikci_eslestirme duplicate nexgen_tedarikci_id reddedilir',
        results,
    )
    con.rollback()

    con.close()


def _check_yetkiler(db: str, results: list) -> dict:
    con = _connect(db)
    yetki_rows = {}
    for kod in YENI_YETKILER:
        rows = con.execute(
            'SELECT Id, Kod FROM sistem_yetki WHERE Kod=?', (kod,),
        ).fetchall()
        if len(rows) != 1:
            results.append(('FAIL', f'Yetki tekil degil: {kod}', len(rows)))
        else:
            results.append(('PASS', f'Yetki tekil: {kod}', int(rows[0]['Id'])))
            yetki_rows[kod] = int(rows[0]['Id'])

    rol_atamalar = []
    for rol_id in (1, 2):
        ad = con.execute('SELECT Ad FROM sistem_rol WHERE Id=?', (rol_id,)).fetchone()
        rol_ad = ad['Ad'] if ad else '?'
        for kod in YENI_YETKILER:
            yid = yetki_rows.get(kod)
            if not yid:
                continue
            ry = con.execute(
                'SELECT can_view, can_manage FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?',
                (rol_id, yid),
            ).fetchone()
            rol_atamalar.append({
                'rol_id': rol_id,
                'rol_ad': rol_ad,
                'yetki': kod,
                'can_view': int(ry['can_view'] or 0) if ry else 0,
                'can_manage': int(ry['can_manage'] or 0) if ry else 0,
            })
    con.close()
    return {'yetkiler': yetki_rows, 'rol_atamalar': rol_atamalar}


def _protected_unchanged(before: dict, after: dict, results: list) -> None:
    for key in ('cari_eslestirme', 'finans_belgesi', 'cari_har', 'cari_kart'):
        if before.get(key) != after.get(key):
            results.append(('FAIL', f'{key} sayisi degisti', f"{before.get(key)} -> {after.get(key)}"))
        else:
            results.append(('PASS', f'{key} korundu', before.get(key)))


def main() -> int:
    ts = _ts()
    backup_dir = ROOT / 'backup' / f'faz_f1_1_migration_131_{ts}'
    files_dir = backup_dir / 'files'
    files_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    results: list[tuple] = []

    def log(msg: str) -> None:
        print(msg)
        lines.append(msg)

    pre_main_sha = iso.db_sha256(MAIN_DB)
    pre_main_counts = iso.db_counts(MAIN_DB)
    pre_fb = _finans_belgesi_summary(MAIN_DB)
    pre_hashes = iso.critical_table_hashes(MAIN_DB)

    log(f'MAIN_DB={MAIN_DB}')
    log(f'pre_main_sha={pre_main_sha}')
    log(f'pre_main_counts={pre_main_counts}')
    log(f'pre_finans_belgesi={pre_fb}')

    if pre_main_sha != BASELINE_SHA:
        log(f'UYARI: Ana DB SHA baseline ile farkli (beklenen {BASELINE_SHA})')

    temp_before = backup_dir / 'temp_db_before.db'
    temp_after = backup_dir / 'temp_db_after.db'
    shutil.copy2(MAIN_DB, temp_before)
    temp_db = str(temp_before)

    mig_src = APP / 'migrations' / '131_finans_cari_kimlik_kopru.py'
    shutil.copy2(mig_src, files_dir / '131_finans_cari_kimlik_kopru.py')
    manifest_src = APP / 'migrations' / 'nexgen_manifest.py'
    shutil.copy2(manifest_src, files_dir / 'nexgen_manifest_snapshot.py')

    schema_before = _schema_snapshot(temp_db)
    with open(backup_dir / 'schema_before.json', 'w', encoding='utf-8') as f:
        json.dump(schema_before, f, ensure_ascii=False, indent=2)

    con_pre = _connect(temp_db)
    counts_before = {
        'cari_eslestirme': int(con_pre.execute('SELECT COUNT(*) FROM cari_eslestirme').fetchone()[0]),
        'finans_belgesi': int(con_pre.execute('SELECT COUNT(*) FROM finans_belgesi').fetchone()[0]),
        'cari_har': int(con_pre.execute('SELECT COUNT(*) FROM Cari_Har').fetchone()[0]),
        'cari_kart': int(con_pre.execute('SELECT COUNT(*) FROM Cari_Kart').fetchone()[0]),
    }
    ctip_anomaly = _ctip_anomaly(con_pre)
    mig130 = con_pre.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='finans_belgesi'"
    ).fetchone()
    con_pre.close()

    mod = importlib.import_module('migrations.131_finans_cari_kimlik_kopru')

    counts_after: dict | None = None
    yetki_info: dict | None = None
    schema_after: dict = {}

    try:
        log('--- Migration 131 ilk calistirma ---')
        mod.run(temp_db)
        results.append(('PASS', 'Migration 131 ilk calistirma', ''))

        log('--- Migration 131 ikinci calistirma (idempotent) ---')
        mod.run(temp_db)
        results.append(('PASS', 'Migration 131 ikinci calistirma idempotent', ''))

        con = _connect(temp_db)
        assert nm.tablo_var(con, 'finans_cari_kimlik'), 'finans_cari_kimlik yok'
        assert nm.tablo_var(con, 'tedarikci_eslestirme'), 'tedarikci_eslestirme yok'
        ver = con.execute(
            'SELECT COUNT(*) FROM schema_migrations WHERE version=?', (MIGRATION_VERSION,),
        ).fetchone()[0]
        assert ver >= 1, 'schema_migrations 131 yok'
        results.append(('PASS', 'schema_migrations version=131', ver))

        for idx in (
            'idx_fck_tip_aktif', 'idx_fck_durum',
            'idx_fck_ckod_musteri_aktif', 'idx_fck_ckod_tedarikci_aktif',
            'idx_te_ckod_aktif', 'idx_te_durum', 'idx_te_aktif',
        ):
            row = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (idx,),
            ).fetchone()
            if row:
                results.append(('PASS', f'index {idx}', 'var'))
            else:
                results.append(('FAIL', f'index {idx}', 'yok'))
        con.close()

        _run_constraint_tests(temp_db, results)
        yetki_info = _check_yetkiler(temp_db, results)

        con_post = _connect(temp_db)
        counts_after = {
            'cari_eslestirme': int(con_post.execute('SELECT COUNT(*) FROM cari_eslestirme').fetchone()[0]),
            'finans_belgesi': int(con_post.execute('SELECT COUNT(*) FROM finans_belgesi').fetchone()[0]),
            'cari_har': int(con_post.execute('SELECT COUNT(*) FROM Cari_Har').fetchone()[0]),
            'cari_kart': int(con_post.execute('SELECT COUNT(*) FROM Cari_Kart').fetchone()[0]),
        }
        con_post.close()
        _protected_unchanged(counts_before, counts_after, results)

        if counts_after['cari_har'] != BASELINE_CARI_HAR:
            results.append(('FAIL', 'Temp DB Cari_Har baseline', counts_after['cari_har']))
        else:
            results.append(('PASS', 'Temp DB Cari_Har 82', counts_after['cari_har']))

        shutil.copy2(temp_db, temp_after)
        schema_after = _schema_snapshot(str(temp_after))
        with open(backup_dir / 'schema_after.json', 'w', encoding='utf-8') as f:
            json.dump(schema_after, f, ensure_ascii=False, indent=2)

    except Exception as exc:
        log(f'HATA: {exc}')
        log(traceback.format_exc())
        results.append(('FAIL', 'exception', str(exc)))

    post_main_sha = iso.db_sha256(MAIN_DB)
    post_main_counts = iso.db_counts(MAIN_DB)
    post_fb = _finans_belgesi_summary(MAIN_DB)
    ok_main, main_msg = iso.assert_main_db_unchanged(
        pre_main_sha, MAIN_DB,
        pre_har=pre_main_counts['cari_har'],
        pre_fb=pre_main_counts['finans_belgesi'],
    )
    results.append(('PASS' if ok_main else 'FAIL', 'Ana DB SHA/count korundu', main_msg))
    ok_log, log_msg = iso.assert_main_db_logical_unchanged(pre_hashes, MAIN_DB)
    results.append(('PASS' if ok_log else 'FAIL', 'Ana DB logical hash korundu', log_msg))

    try:
        from modules.nexgen import mo_tahsilat_config as mtc
        cari_ent = bool(getattr(mtc, 'CARI_ENTEGRASYON_AKTIF', None))
        results.append(('PASS' if not cari_ent else 'FAIL', 'CARI_ENTEGRASYON_AKTIF=False', cari_ent))
    except Exception as exc:
        results.append(('WARN', 'CARI_ENTEGRASYON_AKTIF okunamadi', str(exc)))

    temp_sha = iso.db_sha256(str(temp_after)) if temp_after.exists() else None

    fails = [r for r in results if r[0] == 'FAIL']
    for r in results:
        log(f"[{r[0]}] {r[1]} — {r[2]}")

    evidence = {
        'timestamp': ts,
        'main_db_pre_sha': pre_main_sha,
        'main_db_post_sha': post_main_sha,
        'baseline_sha_expected': BASELINE_SHA,
        'main_db_unchanged': ok_main,
        'main_cari_har_pre': pre_main_counts['cari_har'],
        'main_cari_har_post': post_main_counts['cari_har'],
        'main_finans_belgesi_pre': pre_fb,
        'main_finans_belgesi_post': post_fb,
        'temp_db_sha': temp_sha,
        'temp_counts_before': counts_before,
        'temp_counts_after': counts_after,
        'ctip_anomaly': ctip_anomaly,
        'migration_130_finans_belgesi_exists': bool(mig130),
        'yetki_info': yetki_info,
        'test_results': [{'status': r[0], 'name': r[1], 'detail': r[2]} for r in results],
        'fail_count': len(fails),
    }
    with open(backup_dir / 'db_evidence.json', 'w', encoding='utf-8') as f:
        json.dump(evidence, f, ensure_ascii=False, indent=2)

    with open(backup_dir / 'test_output.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    report = _build_report(
        backup_dir, evidence, schema_after,
        yetki_info or {},
        ctip_anomaly, fails,
    )
    with open(backup_dir / 'RAPOR.md', 'w', encoding='utf-8') as f:
        f.write(report)

    log(f'\nBackup: {backup_dir}')
    log(f'SONUC: {"PASS" if not fails else "FAIL"} ({len(fails)} hata)')
    return 0 if not fails else 1


def _build_report(
    backup_dir: Path,
    evidence: dict,
    schema_after: dict,
    yetki_info: dict,
    ctip_anomaly: list,
    fails: list,
) -> str:
    idx_lines = []
    for name, meta in schema_after.get('indexes', {}).items():
        idx_lines.append(f'- `{name}` ({meta.get("table")}): `{meta.get("sql")}`')

    rol_lines = []
    for ra in yetki_info.get('rol_atamalar', []):
        rol_lines.append(
            f"- Rol {ra['rol_id']} ({ra['rol_ad']}): `{ra['yetki']}` "
            f"view={ra['can_view']} manage={ra['can_manage']}"
        )

    test_lines = []
    for tr in evidence.get('test_results', []):
        test_lines.append(f"- [{tr['status']}] {tr['name']}: {tr['detail']}")

    return f"""# FAZ-F1-1 Migration 131 Raporu

**Tarih:** {evidence.get('timestamp')}
**Backup:** `{backup_dir}`

## 1. Oluşturulan dosyalar

- `app/migrations/131_finans_cari_kimlik_kopru.py`
- `app/migrations/nexgen_manifest.py` (MigEntry 131)
- `_test_faz_f1_migration_131.py`

## 2. Tablo şemaları

Şema snapshot: `schema_after.json`

### finans_cari_kimlik
Kimlik köprüsü — MUSTERI/TEDARIKCI, operasyonel FK RESTRICT, Cari_Kart SET NULL.

### tedarikci_eslestirme
Tedarikçi Cari Köprüsü — nexgen_tedarikci → Cari_Kart.

## 3. Indexler

{chr(10).join(idx_lines) if idx_lines else '(yok)'}

**Not:** Global `idx_fck_cari_kart_aktif` kullanılmadı. CTip=3 dual-mapping için tip-bazlı partial unique indexler tercih edildi.

## 4. Yetkiler

- `nexgen.finans.cari_kimlik.view`
- `nexgen.finans.cari_kimlik.manage`
- `nexgen.finans.tedarikci_kimlik.manage`

## 5. Rol atamaları

{chr(10).join(rol_lines) if rol_lines else '- Admin/Finans ayrı rol yok — yalnızca Yönetim (1) ve Muhasebe (2)'}

Planlama/Depo/Sevkiyat rollerine atama yapılmadı.

## 6. CTip anomali notu

Precheck'te `Cari_Kart.CTip` içinde metin `MUSTERI` değeri tespit edildi. Migration bu veriyi **değiştirmedi**.

Anomali kayıtları: `{json.dumps(ctip_anomaly, ensure_ascii=False)}`

Normalizasyon servis katmanında ele alınacak (F1-2+).

## 7–9. Migration ve constraint testleri

{chr(10).join(test_lines)}

## 10. Ana DB SHA

| | SHA |
|---|---|
| Önce | `{evidence.get('main_db_pre_sha')}` |
| Sonra | `{evidence.get('main_db_post_sha')}` |
| Beklenen baseline | `{evidence.get('baseline_sha_expected')}` |
| Değişmedi | {evidence.get('main_db_unchanged')} |

## 11–12. Cari_Har / finans_belgesi

| Metrik | Önce | Sonra |
|--------|------|-------|
| Cari_Har | {evidence.get('main_cari_har_pre')} | {evidence.get('main_cari_har_post')} |
| finans_belgesi | {json.dumps(evidence.get('main_finans_belgesi_pre'))} | {json.dumps(evidence.get('main_finans_belgesi_post'))} |

## 13. Temp DB SHA

`{evidence.get('temp_db_sha')}`

## 14. Bilinen riskler

1. CTip metin anomalisi — migration dışı
2. Admin/Finans ayrı rol yok — yalnızca Rol 1/2 atandı
3. Ana DB'ye apply yapılmadı — F1-2 öncesi onay gerekli
4. Backfill yok — kimlik tabloları boş

## 15. Ana DB apply öncesi kullanıcı onayı

**Ana DB'ye migration 131 apply edilmedi.** F1-2 servis katmanına geçmeden önce Adem onayı beklenir.

---

**Sonuç:** {"PASS" if not fails else f"FAIL ({len(fails)} hata)"}
"""


if __name__ == '__main__':
    raise SystemExit(main())
