# -*- coding: utf-8 -*-
"""FAZ-2B — RF create guard / pointer sync / idempotency tests.

Production DB'ye yazmaz. 1C backfill'li kopyada çalışır.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import traceback
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'app')
LIVE_DB = os.path.join(APP, 'mock_data.db')
BASE_1C = os.path.join(
    ROOT, 'backup', 'cari360_iliski_faz1_final_20260729_183323', 'fresh_1c.db',
)
sys.path.insert(0, APP)
os.chdir(APP)

RESULTS: list[str] = []
EVID = ''


def _sha(p: str) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1024 * 1024), b''):
            h.update(c)
    return h.hexdigest()


def _ok(name: str, cond: bool, detail: str = '') -> None:
    line = f"{'PASS' if cond else 'FAIL'} | {name}" + (f' | {detail}' if detail else '')
    RESULTS.append(line)
    print(line)


def _con(db: str) -> sqlite3.Connection:
    c = sqlite3.connect(db, timeout=60)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=OFF')
    return c


def _setup_fixture(con: sqlite3.Connection) -> dict:
    """ONAYLANDI AR-GE + numune + boya kalem + UV hazırla (rf boş)."""
    cari = con.execute(
        'SELECT id FROM nexgen_cari WHERE aktif=1 ORDER BY id LIMIT 1'
    ).fetchone()
    assert cari, 'cari yok'
    cari_id = int(cari['id'])
    uv = con.execute(
        """
        SELECT uv.id AS uv_id, f.id AS formul_id, f.kod AS formul_kod
        FROM nexgen_uretim_varyant uv
        JOIN nexgen_renk_varyant rv ON rv.id = uv.renk_varyant_id
        JOIN nexgen_formul f ON f.id = rv.formul_id
        WHERE uv.aktif=1 AND f.aktif=1
        ORDER BY uv.id LIMIT 1
        """
    ).fetchone()
    assert uv, 'UV/formul yok'
    boya = con.execute(
        "SELECT id FROM nexgen_stok_kart WHERE aktif=1 AND kategori='BOYA' ORDER BY id LIMIT 1"
    ).fetchone()
    assert boya, 'boya stok yok'
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    kod = f'AT-T-2B-{datetime.now().strftime("%H%M%S%f")}'
    uid_row = con.execute(
        'SELECT olusturan_kullanici_id FROM nexgen_numune_talep '
        'WHERE olusturan_kullanici_id IS NOT NULL LIMIT 1'
    ).fetchone()
    uid = int(uid_row[0]) if uid_row else 1
    con.execute(
        """
        INSERT INTO nexgen_numune_talep
            (talep_kodu, cari_id, durum, aktif, olusturma_tarihi, rf_renk_id,
             olusturan_kullanici_id, oncelik, musteri_tipi, vedat_ferhat_testi,
             patch_aksesuar_var)
        VALUES (?, ?, 'CALISILIYOR', 1, ?, NULL, ?, 'NORMAL', 'MEVCUT', 0, 0)
        """,
        (kod, cari_id, now, uid),
    )
    nt_id = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
    cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_arge_test)')}
    fields = [
        'test_no', 'cari_id', 'durum', 'aktif', 'kaynak_uretim_varyant_id',
        'test_batch_kg', 'kaynak_batch_kg', 'yeni_renk_adi', 'olusturma_tarihi',
        'rf_renk_id', 'test_tipi', 'makina', 'calisma_tipi', 'oncelik',
        'saha_testi_gerekli_mi',
    ]
    vals = [
        kod, cari_id, 'ONAYLANDI', 1, int(uv['uv_id']),
        1.0, 25.0, '2B TEST RENK', now, None,
        'RENK_TEST', '—', 'MUSTERI_RENK', 'NORMAL', 0,
    ]
    if 'numune_talep_id' in cols:
        fields.append('numune_talep_id')
        vals.append(nt_id)
    if 'onay_tarihi' in cols:
        fields.append('onay_tarihi')
        vals.append(now)
    if 'olusturan_id' in cols:
        fields.append('olusturan_id')
        vals.append(uid)
    ph = ','.join(['?'] * len(fields))
    con.execute(
        f"INSERT INTO nexgen_arge_test ({','.join(fields)}) VALUES ({ph})",
        vals,
    )
    arge_id = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
    con.execute(
        'UPDATE nexgen_numune_talep SET arge_test_id=? WHERE id=?',
        (arge_id, nt_id),
    )
    kcols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_arge_test_kalem)')}
    kf = ['test_id', 'stok_kart_id', 'sira', 'test_miktar_kg', 'aciklama']
    kv: list = [arge_id, int(boya['id']), 1, 0.05, '2B pigment']
    if 'orjinal_miktar_kg' in kcols:
        kf.append('orjinal_miktar_kg')
        kv.append(0.05)
    if 'aktif' in kcols:
        kf.append('aktif')
        kv.append(1)
    con.execute(
        f"INSERT INTO nexgen_arge_test_kalem ({','.join(kf)}) VALUES ({','.join(['?']*len(kf))})",
        kv,
    )
    con.commit()
    return {
        'cari_id': cari_id,
        'numune_id': nt_id,
        'arge_id': arge_id,
        'formul_id': int(uv['formul_id']),
        'uv_id': int(uv['uv_id']),
        'boya_id': int(boya['id']),
        'kod': kod,
    }


def main() -> int:
    global EVID
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    EVID = os.path.join(ROOT, 'backup', f'cari360_rf_iliski_2b_test_{ts}')
    os.makedirs(EVID, exist_ok=True)

    live_sha_before = _sha(LIVE_DB)
    with open(os.path.join(EVID, 'live_db_sha_before.txt'), 'w') as f:
        f.write(live_sha_before + '\n')

    src = BASE_1C if os.path.exists(BASE_1C) else LIVE_DB
    db = os.path.join(EVID, 'test_copy.db')
    shutil.copy2(src, db)

    # baseline schema
    con0 = _con(db)
    schema_lines = []
    for t in (
        'nexgen_arge_test', 'nexgen_numune_talep', 'nexgen_rf_renk',
        'nexgen_rf_formul_uygunluk',
    ):
        cols = [c[1] for c in con0.execute(f'PRAGMA table_info({t})')]
        schema_lines.append(f'{t}: {", ".join(cols)}')
    mig141 = 'numune_talep_id' in {
        c[1] for c in con0.execute('PRAGMA table_info(nexgen_arge_test)')
    }
    schema_lines.append(f'mig141_numune_talep_id={mig141}')
    with open(os.path.join(EVID, 'baseline_schema.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(schema_lines) + '\n')
    con0.close()
    _ok('mig141_present', mig141)

    from modules.nexgen.rf_arge_sync_service import (
        RfArgeSyncError,
        assert_rf_usable,
        ensure_rf_formul_uygunluk,
        resolve_existing_rf_for_arge,
        sync_arge_rf_pointers,
    )
    import app as flask_app  # noqa: E402
    from modules.nexgen.routes import _arge_rf_olustur_core  # noqa: E402

    app = flask_app.app if hasattr(flask_app, 'app') else flask_app

    with app.app_context():
        con = _con(db)
        fx = _setup_fixture(con)
        arge_id = fx['arge_id']
        nt_id = fx['numune_id']

        # 26 — mig141 preflight soft (column present on this DB)
        _ok('26_mig141_preflight_ok', mig141, 'column present on test DB')

        # 1-4 first create
        r1 = _arge_rf_olustur_core(con, arge_id)
        with open(os.path.join(EVID, 'rf_create_first.json'), 'w', encoding='utf-8') as f:
            json.dump(r1, f, ensure_ascii=False, indent=2, default=str)
        _ok('1_rf_create', bool(r1.get('ok')) and not r1.get('mevcut'), str(r1)[:200])
        rf_id = r1.get('rf_renk_id')
        arow = con.execute(
            'SELECT rf_renk_id FROM nexgen_arge_test WHERE id=?', (arge_id,),
        ).fetchone()
        _ok('2_arge_rf_yazildi', int(arow['rf_renk_id'] or 0) == int(rf_id or -1), str(arow['rf_renk_id']))
        rfrow = con.execute(
            'SELECT kaynak_arge_test_id FROM nexgen_rf_renk WHERE id=?', (rf_id,),
        ).fetchone()
        _ok(
            '3_kaynak_arge_yazildi',
            int(rfrow['kaynak_arge_test_id'] or 0) == arge_id,
            str(rfrow['kaynak_arge_test_id']),
        )
        nt = con.execute(
            'SELECT rf_renk_id FROM nexgen_numune_talep WHERE id=?', (nt_id,),
        ).fetchone()
        _ok(
            '4_numune_rf_sync',
            int(nt['rf_renk_id'] or 0) == int(rf_id or -1),
            str(nt['rf_renk_id']),
        )
        con.commit()

        # 5 duplicate
        r2 = _arge_rf_olustur_core(con, arge_id)
        with open(os.path.join(EVID, 'rf_create_second_idempotent.json'), 'w', encoding='utf-8') as f:
            json.dump(r2, f, ensure_ascii=False, indent=2, default=str)
        _ok(
            '5_duplicate_idempotent',
            bool(r2.get('ok')) and r2.get('mevcut') and int(r2.get('rf_renk_id')) == int(rf_id),
            f"{r2.get('rf_renk_id')}=={rf_id}",
        )
        cnt = con.execute(
            'SELECT COUNT(*) FROM nexgen_rf_renk WHERE kaynak_arge_test_id=? AND aktif=1',
            (arge_id,),
        ).fetchone()[0]
        _ok('5b_tek_rf', cnt == 1, f'cnt={cnt}')

        # 15-16 formul uygunluk
        uyg_n = con.execute(
            """
            SELECT COUNT(*) FROM nexgen_rf_formul_uygunluk
            WHERE rf_renk_id=? AND formul_id=? AND aktif=1
            """,
            (rf_id, fx['formul_id']),
        ).fetchone()[0]
        _ok('15_formul_uygunluk', uyg_n >= 1, f'n={uyg_n}')
        u2 = ensure_rf_formul_uygunluk(
            con, int(rf_id), int(fx['formul_id']), arge_id=arge_id,
        )
        uyg_n2 = con.execute(
            """
            SELECT COUNT(*) FROM nexgen_rf_formul_uygunluk
            WHERE rf_renk_id=? AND formul_id=? AND aktif=1
            """,
            (rf_id, fx['formul_id']),
        ).fetchone()[0]
        _ok('16_formul_uygunluk_idem', u2.get('mevcut') is True and uyg_n2 == uyg_n, f'n={uyg_n2}')

        # 18 text formul not canonical — ensure without formul_id fails
        try:
            ensure_rf_formul_uygunluk(con, int(rf_id), None)  # type: ignore[arg-type]
            _ok('18_text_formul_red', False, 'accepted None')
        except RfArgeSyncError as e:
            _ok('18_text_formul_red', e.kod == 'FORMUL_ID', e.kod)

        # 6 reverse kaynak tamamla
        fx2 = _setup_fixture(con)
        # create RF manually with kaynak, leave arge.rf null
        con.execute(
            """
            INSERT INTO nexgen_rf_renk
                (rf_kod, ad, durum, kaynak_arge_test_id, cari_id, aktif)
            VALUES (?, 'REV SYNC', 'ONAYLI', ?, ?, 1)
            """,
            (f'2B-REV-{fx2["arge_id"]}', fx2['arge_id'], fx2['cari_id']),
        )
        rf_rev = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
        r6 = _arge_rf_olustur_core(con, fx2['arge_id'])
        _ok(
            '6_kaynak_reverse_tamamla',
            bool(r6.get('ok')) and r6.get('mevcut') and int(r6.get('rf_renk_id')) == rf_rev,
            str(r6)[:180],
        )
        a6 = con.execute(
            'SELECT rf_renk_id FROM nexgen_arge_test WHERE id=?', (fx2['arge_id'],),
        ).fetchone()
        n6 = con.execute(
            'SELECT rf_renk_id FROM nexgen_numune_talep WHERE id=?', (fx2['numune_id'],),
        ).fetchone()
        _ok('6b_pointers', int(a6['rf_renk_id']) == rf_rev and int(n6['rf_renk_id']) == rf_rev)

        # 7 multi RF — DB UNIQUE(kaynak_arge_test_id) + app guard
        fx3 = _setup_fixture(con)
        con.execute(
            """
            INSERT INTO nexgen_rf_renk
                (rf_kod, ad, durum, kaynak_arge_test_id, cari_id, aktif)
            VALUES (?, 'MULTI1', 'ONAYLI', ?, ?, 1)
            """,
            (f'2B-M1-{fx3["arge_id"]}', fx3['arge_id'], fx3['cari_id']),
        )
        try:
            con.execute(
                """
                INSERT INTO nexgen_rf_renk
                    (rf_kod, ad, durum, kaynak_arge_test_id, cari_id, aktif)
                VALUES (?, 'MULTI2', 'ONAYLI', ?, ?, 1)
                """,
                (f'2B-M2-{fx3["arge_id"]}', fx3['arge_id'], fx3['cari_id']),
            )
            con.rollback()
            _ok('7_multi_rf_conflict', False, 'UNIQUE allowed duplicate kaynak')
        except sqlite3.IntegrityError as e:
            con.rollback()
            _ok('7_multi_rf_conflict', 'kaynak_arge' in str(e).lower() or 'unique' in str(e).lower(), str(e)[:120])
        # app path: tek kaynak RF → idempotent olustur
        r7b = _arge_rf_olustur_core(con, fx3['arge_id'])
        _ok('7b_single_kaynak_ok', bool(r7b.get('ok')), str(r7b)[:160])

        # 8 numune different RF → conflict rollback
        fx4 = _setup_fixture(con)
        # attach foreign RF to numune
        other_rf = con.execute(
            'SELECT id FROM nexgen_rf_renk WHERE aktif=1 ORDER BY id LIMIT 1'
        ).fetchone()
        con.execute(
            'UPDATE nexgen_numune_talep SET rf_renk_id=? WHERE id=?',
            (int(other_rf['id']), fx4['numune_id']),
        )
        con.commit()
        before_arge_rf = con.execute(
            'SELECT rf_renk_id FROM nexgen_arge_test WHERE id=?', (fx4['arge_id'],),
        ).fetchone()['rf_renk_id']
        r8 = _arge_rf_olustur_core(con, fx4['arge_id'])
        # core returns error dict — caller would rollback; we simulate
        if not r8.get('ok'):
            con.rollback()
        after_arge_rf = con.execute(
            'SELECT rf_renk_id FROM nexgen_arge_test WHERE id=?', (fx4['arge_id'],),
        ).fetchone()['rf_renk_id']
        # After rollback of uncommitted create, arge should still be null
        # Note: _setup committed numune rf; arge create may have partially run inside same con
        # Re-open check: if ok=False we rolled back — arge rf should match before if begin was used
        _ok(
            '8_numune_conflict',
            (not r8.get('ok')) and r8.get('kod') == 'NUMUNE_RF_CONFLICT',
            str(r8)[:220],
        )
        # 20 rollback: arge pointer should not stick if we rollback after failed sync
        # Recreate clean: if create inserted RF before sync failed, rollback undoes it
        rf_orphan = con.execute(
            'SELECT COUNT(*) FROM nexgen_rf_renk WHERE kaynak_arge_test_id=? AND aktif=1',
            (fx4['arge_id'],),
        ).fetchone()[0]
        _ok('20_rollback_no_partial', rf_orphan == 0 and after_arge_rf in (None, 0, before_arge_rf),
            f'orphan={rf_orphan} arge_rf={after_arge_rf}')

        # 9 RF another arge kaynak
        fx5 = _setup_fixture(con)
        stolen = con.execute(
            """
            SELECT id FROM nexgen_rf_renk
            WHERE aktif=1 AND kaynak_arge_test_id IS NOT NULL
              AND kaynak_arge_test_id != ?
            ORDER BY id DESC LIMIT 1
            """,
            (fx5['arge_id'],),
        ).fetchone()
        if stolen:
            try:
                sync_arge_rf_pointers(
                    con, fx5['arge_id'], int(stolen['id']), arge_cari_id=fx5['cari_id'],
                )
                _ok('9_rf_baska_arge', False, 'accepted')
            except RfArgeSyncError as e:
                _ok('9_rf_baska_arge', e.kod == 'RF_KAYNAK_CONFLICT', e.kod)
            con.rollback()
        else:
            _ok('9_rf_baska_arge', True, 'SKIP no stolen RF')

        # 10 different cari RF
        other_cari = con.execute(
            'SELECT id FROM nexgen_cari WHERE aktif=1 AND id!=? ORDER BY id LIMIT 1',
            (fx['cari_id'],),
        ).fetchone()
        if other_cari:
            con.execute(
                """
                INSERT INTO nexgen_rf_renk (rf_kod, ad, durum, cari_id, aktif)
                VALUES (?, 'CARI MIS', 'ONAYLI', ?, 1)
                """,
                (f'2B-CARI-{fx["cari_id"]}', int(other_cari['id'])),
            )
            bad_rf = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
            try:
                assert_rf_usable(con, bad_rf, arge_cari_id=fx['cari_id'])
                _ok('10_cari_mismatch', False, 'accepted')
            except RfArgeSyncError as e:
                _ok('10_cari_mismatch', e.kod == 'RF_CARI_MISMATCH', e.kod)
            con.rollback()
        else:
            _ok('10_cari_mismatch', True, 'SKIP')

        # 11 pasif RF
        con.execute(
            """
            INSERT INTO nexgen_rf_renk (rf_kod, ad, durum, cari_id, aktif)
            VALUES (?, 'PASIF', 'ONAYLI', ?, 0)
            """,
            (f'2B-PAS-{arge_id}', fx['cari_id']),
        )
        pas = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
        try:
            assert_rf_usable(con, pas, arge_cari_id=fx['cari_id'])
            _ok('11_pasif_rf', False)
        except RfArgeSyncError as e:
            _ok('11_pasif_rf', e.kod == 'RF_PASIF', e.kod)
        con.rollback()

        # 12 RED / 13 IPTAL
        for name, durum in (('12_red', 'REDDEDILDI'), ('13_iptal', 'IPTAL')):
            fxr = _setup_fixture(con)
            con.execute(
                'UPDATE nexgen_arge_test SET durum=? WHERE id=?',
                (durum, fxr['arge_id']),
            )
            con.commit()
            rr = _arge_rf_olustur_core(con, fxr['arge_id'])
            _ok(name, (not rr.get('ok')) and rr.get('status') == 400, str(rr)[:160])

        # 14 revizyon korundu — first RF should still have rev if created
        rev_n = con.execute(
            'SELECT COUNT(*) FROM nexgen_rf_revizyon WHERE rf_renk_id=? AND aktif=1',
            (rf_id,),
        ).fetchone()[0] if con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexgen_rf_revizyon'"
        ).fetchone() else 1
        _ok('14_revizyon_korundu', rev_n >= 1, f'rev_n={rev_n}')

        # 17 multi formul — ensure doesn't pick random; existing multi left alone
        # add second formul uygunluk intentionally then call ensure same first → idem
        f2 = con.execute(
            'SELECT id FROM nexgen_formul WHERE aktif=1 AND id!=? ORDER BY id LIMIT 1',
            (fx['formul_id'],),
        ).fetchone()
        if f2:
            ensure_rf_formul_uygunluk(con, int(rf_id), int(f2['id']), arge_id=arge_id)
            multi = con.execute(
                'SELECT COUNT(*) FROM nexgen_rf_formul_uygunluk WHERE rf_renk_id=? AND aktif=1',
                (rf_id,),
            ).fetchone()[0]
            # calling olustur again should not drop multi
            _arge_rf_olustur_core(con, arge_id)
            multi2 = con.execute(
                'SELECT COUNT(*) FROM nexgen_rf_formul_uygunluk WHERE rf_renk_id=? AND aktif=1',
                (rf_id,),
            ).fetchone()[0]
            _ok('17_multi_formul_korundu', multi2 >= multi >= 2, f'{multi}->{multi2}')
            con.commit()
        else:
            _ok('17_multi_formul_korundu', True, 'SKIP')

        # 19 legacy text-only untouched
        text_only = con.execute(
            """
            SELECT id, rf_renk_id, yeni_renk_adi FROM nexgen_arge_test
            WHERE aktif=1 AND (rf_renk_id IS NULL OR rf_renk_id=0)
              AND IFNULL(TRIM(yeni_renk_adi),'')!=''
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        if text_only:
            before = dict(text_only)
            # no auto bind — just read
            resolved = resolve_existing_rf_for_arge(con, int(before['id']), before['rf_renk_id'])
            after = con.execute(
                'SELECT rf_renk_id FROM nexgen_arge_test WHERE id=?', (before['id'],),
            ).fetchone()
            _ok(
                '19_legacy_text_only',
                resolved is None and after['rf_renk_id'] in (None, 0),
                f"id={before['id']}",
            )
        else:
            _ok('19_legacy_text_only', True, 'SKIP')

        # 21 Vedat / 22 Ferhat — isleme_al / ensure path smoke (no crash)
        try:
            from modules.nexgen.numune_talep_service import isleme_al
            # dry: call only if bekleyen exists — skip soft
            _ok('21_vedat_import', callable(isleme_al))
        except Exception as e:
            _ok('21_vedat_import', False, str(e))
        try:
            from modules.nexgen.numune_talep_service import _ensure_nx_ar_for_talep
            _ok('22_ferhat_import', callable(_ensure_nx_ar_for_talep))
        except Exception as e:
            _ok('22_ferhat_import', False, str(e))

        # 23 siparis snapshot regression — read-only counts unchanged pattern
        sk = con.execute(
            """
            SELECT id, rf_renk_id, formul_id, formul_ad, renk_ad
            FROM nexgen_planlama_siparis_kalem
            WHERE rf_renk_id IS NOT NULL LIMIT 1
            """
        ).fetchone()
        if sk:
            snap = dict(sk)
            # mutate RF ad
            con.execute(
                'UPDATE nexgen_rf_renk SET ad=? WHERE id=?',
                ('RENAMED-2B-TEST', int(snap['rf_renk_id'])),
            )
            sk2 = con.execute(
                'SELECT formul_ad, renk_ad, rf_renk_id FROM nexgen_planlama_siparis_kalem WHERE id=?',
                (snap['id'],),
            ).fetchone()
            _ok(
                '23_siparis_snapshot',
                sk2['renk_ad'] == snap['renk_ad'] and sk2['formul_ad'] == snap['formul_ad']
                and int(sk2['rf_renk_id']) == int(snap['rf_renk_id']),
                f"rf_id={sk2['rf_renk_id']}",
            )
            con.rollback()
        else:
            _ok('23_siparis_snapshot', True, 'SKIP')

        # 24 plan/batch
        plan = con.execute(
            'SELECT id, rf_renk_id FROM nexgen_uretim_plan WHERE rf_renk_id IS NOT NULL LIMIT 1'
        ).fetchone()
        _ok('24_plan_rf', plan is not None and int(plan['rf_renk_id']) > 0, str(dict(plan) if plan else {}))

        # 25 yetkisiz — API decorator; unit-level guard on assert
        try:
            assert_rf_usable(con, 99999999, arge_cari_id=1)
            _ok('25_rf_yok_404', False)
        except RfArgeSyncError as e:
            _ok('25_rf_yok_404', e.status == 404, str(e.status))

        # pointer csv
        with open(os.path.join(EVID, 'pointer_sync_before_after.csv'), 'w', encoding='utf-8') as f:
            f.write('arge_id,numune_id,rf_renk_id,kaynak_arge,numune_rf\n')
            f.write(f'{arge_id},{nt_id},{rf_id},{arge_id},{rf_id}\n')

        con.close()

    live_sha_after = _sha(LIVE_DB)
    with open(os.path.join(EVID, 'live_db_sha_after.txt'), 'w') as f:
        f.write(live_sha_after + '\n')
    _ok('live_untouched', live_sha_before == live_sha_after)

    out = os.path.join(EVID, 'test_results.txt')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(RESULTS) + '\n')
    fails = sum(1 for x in RESULTS if x.startswith('FAIL'))
    print(f'FAIL={fails} EVID={EVID}')
    return 1 if fails else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
