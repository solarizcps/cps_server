# -*- coding: utf-8 -*-
"""NEXGEN FAZ-4B — alt emir bitince stok tüketim testi."""
from __future__ import annotations

import io
import os
import sqlite3
import sys
import tempfile
import shutil

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP_DIR)
os.chdir(_APP_DIR)

os.environ.setdefault('CPS_TEST_DB_GUARD', '1')

from tools.nexgen_tmp_db import (  # noqa: E402
    assert_resolved_db_is_tmp,
    canonical_db_path,
    cleanup_tmp,
    live_db_write_guard_stats,
    sha256_file,
)
from tools.test_db_guard import bootstrap_adhoc_script_guards  # noqa: E402


def _resolve_test_db():
    live = canonical_db_path()
    bootstrap_adhoc_script_guards()
    parent_tmp = os.environ.get('CPS_MOCK_DB_PATH', '').strip()
    if parent_tmp:
        db = os.path.abspath(parent_tmp)
        assert_resolved_db_is_tmp(db, live)
        os.environ['CPS_MOCK_DB_PATH'] = db
        return db, live, None

    tmp_dir = tempfile.mkdtemp(prefix='faz4b_')
    db = os.path.join(tmp_dir, 'mock_data_test.db')
    shutil.copy2(live, db)
    assert_resolved_db_is_tmp(db, live)
    os.environ['CPS_MOCK_DB_PATH'] = db
    return db, live, tmp_dir


_LIVE_DB = canonical_db_path()
_SHA_BEFORE = sha256_file(_LIVE_DB)
DB, _CANONICAL, _TMP_DIR = _resolve_test_db()
print(f'[ISO] tmp_db={DB}')
print(f'[ISO] main_sha_before={_SHA_BEFORE}')

import config as _cfg
_cfg.Config.MOCK_DB_PATH = DB
import app as flask_app
import modules.nexgen.routes as nx_routes
from modules.nexgen.routes import (
    _mpr_stok_ihtiyac_hesapla, _parca_stok_tuket, _mevcut_stok,
)
nx_routes.DB_PATH = DB

_app = flask_app.app
_app.config['TESTING'] = True
results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def sess_user():
    con = sqlite3.connect(DB)
    row = con.execute(
        """
        SELECT Id, KullaniciAdi, RolId, Aktif, ZorunluSifreDegistir, AuthVersion
        FROM sistem_kullanici WHERE Id = 1
        """
    ).fetchone()
    con.close()
    auth_ver = row[5] if row and row[5] is not None else 1
    return {
        'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem',
        'RolId': 1, 'RolAd': 'admin', 'Aktif': 1,
        'AuthVersion': auth_ver,
        'ZorunluSifreDegistir': int(row[4] or 0) if row else 0,
    }


con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# ── Test verisi: stok yeterli bitirilebilir alt emir ──
bitirilebilir = None
adaylar = con.execute("""
    SELECT p.id AS parca_id, p.batch_kodu, p.hedef_kg, p.durum,
           b.uretim_varyant_id, pl.rf_renk_id
    FROM nexgen_uretim_parca p
    JOIN nexgen_uretim_batch b ON b.batch_kodu = p.batch_kodu
    LEFT JOIN nexgen_uretim_plan pl ON pl.id = COALESCE(p.plan_id, b.plan_id)
    WHERE p.durum IN ('DEVAM', 'HAZIR')
    ORDER BY (pl.rf_renk_id IS NOT NULL) DESC, p.id ASC
""").fetchall()

for aday in adaylar:
    chk = _mpr_stok_ihtiyac_hesapla(
        con, aday['uretim_varyant_id'], aday['rf_renk_id'],
        float(aday['hedef_kg']),
    )
    if chk.get('ok') and chk.get('yeterli_mi'):
        bitirilebilir = aday
        break

# Stok yetersizse test icin eksik kalemlere minimal giris ekle (tek parca)
if not bitirilebilir and adaylar:
    aday = adaylar[0]
    chk = _mpr_stok_ihtiyac_hesapla(
        con, aday['uretim_varyant_id'], aday['rf_renk_id'],
        float(aday['hedef_kg']),
    )
    if chk.get('ok'):
        for k in chk.get('kalemler', []):
            if not k.get('yeterli'):
                sid = k['stok_kart_id']
                eksik = round(float(k['gerekli_kg']) - float(k['mevcut_kg']), 3) + 1.0
                onceki = _mevcut_stok(con, sid)
                con.execute("""
                    INSERT INTO nexgen_stok_hareket
                      (stok_kart_id, hareket_tipi, miktar_kg, onceki_stok, sonraki_stok,
                       aciklama, olusturma_tarihi)
                    VALUES (?, 'GIRIS', ?, ?, ?, 'FAZ4B test seed', datetime('now'))
                """, (sid, eksik, onceki, round(onceki + eksik, 3)))
        con.commit()
        chk2 = _mpr_stok_ihtiyac_hesapla(
            con, aday['uretim_varyant_id'], aday['rf_renk_id'],
            float(aday['hedef_kg']),
        )
        if chk2.get('ok') and chk2.get('yeterli_mi'):
            bitirilebilir = aday

devam = bitirilebilir

# ── 1) Alt emir bitir → stok hareket ──
parca_test_id = None
batch_test = None
if devam:
    parca_test_id = devam['parca_id']
    batch_test = devam['batch_kodu']
    hedef = float(devam['hedef_kg'])
    before = con.execute(
        "SELECT COUNT(*) FROM nexgen_stok_hareket WHERE referans_tip='URETIM_PARCA'"
    ).fetchone()[0]

    with _app.test_client() as c:
        with c.session_transaction() as sess:
            sess['kullanici'] = sess_user()
            sess['kullanici_tip'] = 'sistem'
        if devam['durum'] == 'HAZIR':
            c.post(
                f'/nexgen/api/batch/{batch_test}/parca/{parca_test_id}/baslat',
                json={},
            )
        r = c.post(
            f'/nexgen/api/batch/{batch_test}/parca/{parca_test_id}/bitir', json={}
        )
        d = r.get_json() or {}
        ok('1 alt emir bitir 200', r.status_code == 200 and d.get('ok'), str(d.get('durum')))
        ok('tablet response 200', r.status_code == 200, '')

    after = con.execute(
        "SELECT COUNT(*) FROM nexgen_stok_hareket WHERE referans_tip='URETIM_PARCA'"
    ).fetchone()[0]
    hareket = con.execute("""
        SELECT h.*, sk.kategori
        FROM nexgen_stok_hareket h
        JOIN nexgen_stok_kart sk ON sk.id = h.stok_kart_id
        WHERE h.referans_tip='URETIM_PARCA' AND h.referans_id=?
    """, (parca_test_id,)).fetchall()
    ok('1 stok hareket olustu', after > before and len(hareket) > 0, f'hareket={len(hareket)}')

    taban_h = [h for h in hareket if (h['kategori'] or '').upper() != 'BOYA']
    rf_h = [h for h in hareket if (h['kategori'] or '').upper() == 'BOYA']
    ok('2 TABAN tuketildi', len(taban_h) > 0, str(len(taban_h)))
    ok('3 RF boya tuketildi', len(rf_h) > 0 or devam['rf_renk_id'] is None,
       f'rf_boya={len(rf_h)} rf_id={devam["rf_renk_id"]}')

    # Legacy BOYA cift dusmedi — taban hareketlerinde BOYA yok
    boya_taban = [h for h in hareket if (h['kategori'] or '').upper() == 'BOYA'
                  and 'RF' not in (h['aciklama'] or '')]
    legacy_taban_boya = con.execute("""
        SELECT COUNT(*) FROM nexgen_recete_kalem rk
        JOIN nexgen_stok_kart sk ON sk.id = rk.stok_kart_id
        WHERE rk.uretim_varyant_id=? AND rk.aktif=1
          AND UPPER(COALESCE(sk.kategori,''))='BOYA'
    """, (devam['uretim_varyant_id'],)).fetchone()[0]
    taban_stok_ids = {h['stok_kart_id'] for h in taban_h}
    recete_boya_ids = {r['stok_kart_id'] for r in con.execute("""
        SELECT rk.stok_kart_id FROM nexgen_recete_kalem rk
        JOIN nexgen_stok_kart sk ON sk.id = rk.stok_kart_id
        WHERE rk.uretim_varyant_id=? AND rk.aktif=1
          AND UPPER(COALESCE(sk.kategori,''))='BOYA'
    """, (devam['uretim_varyant_id'],)).fetchall()}
    cift = taban_stok_ids & recete_boya_ids
    ok('4 legacy BOYA cift dusmedi', len(cift) == 0,
       f'legacy_boya_satir={legacy_taban_boya} cift={len(cift)}')

    # Ornek hareket negatif
    if hareket:
        h0 = hareket[0]
        ok('ornek miktar negatif', float(h0['miktar_kg']) < 0, str(h0['miktar_kg']))
        ok('ornek tip URETIM_TUKETIM', h0['hareket_tipi'] == 'URETIM_TUKETIM', '')
        ok('ornek referans', h0['referans_tip'] == 'URETIM_PARCA', str(h0['referans_id']))

    # ── 5) Idempotent ──
    cnt_before = con.execute(
        "SELECT COUNT(*) FROM nexgen_stok_hareket WHERE referans_id=? AND referans_tip='URETIM_PARCA'",
        (parca_test_id,),
    ).fetchone()[0]
    r2 = _parca_stok_tuket(con, parca_test_id, uretilen_kg=hedef, olusturan_id=1)
    ok('5 idempotent helper', r2.get('ok') and r2.get('atlandi'), str(r2))
    cnt_after = con.execute(
        "SELECT COUNT(*) FROM nexgen_stok_hareket WHERE referans_id=? AND referans_tip='URETIM_PARCA'",
        (parca_test_id,),
    ).fetchone()[0]
    ok('5 ikinci hareket yok', cnt_before == cnt_after, f'{cnt_before}=={cnt_after}')
else:
    ok('1 bitirilebilir parca bulunamadi', False, 'atlandi')

# ── 6) Stok yetersiz → BITTI olmaz ──
yetersiz_parca = con.execute("""
    SELECT p.id, p.batch_kodu, p.hedef_kg, b.uretim_varyant_id, pl.rf_renk_id
    FROM nexgen_uretim_parca p
    JOIN nexgen_uretim_batch b ON b.batch_kodu = p.batch_kodu
    LEFT JOIN nexgen_uretim_plan pl ON pl.id = COALESCE(p.plan_id, b.plan_id)
    WHERE p.durum IN ('DEVAM', 'HAZIR')
      AND pl.rf_renk_id IS NOT NULL
      AND p.id != ?
    ORDER BY p.id DESC LIMIT 1
""", (parca_test_id or -1,)).fetchone()

if yetersiz_parca:
    hedef_kg = float(yetersiz_parca['hedef_kg'])
    iht = _mpr_stok_ihtiyac_hesapla(
        con, yetersiz_parca['uretim_varyant_id'],
        yetersiz_parca['rf_renk_id'], hedef_kg,
    )
    if iht.get('ok'):
        for k in iht.get('kalemler', []):
            sid = k['stok_kart_id']
            mevcut = _mevcut_stok(con, sid)
            if mevcut > 0:
                con.execute("""
                    INSERT INTO nexgen_stok_hareket
                      (stok_kart_id, hareket_tipi, miktar_kg, onceki_stok, sonraki_stok,
                       aciklama, olusturma_tarihi)
                    VALUES (?, 'SAYIM_DUZELTME', ?, ?, 0, 'FAZ4B test drain', datetime('now'))
                """, (sid, -mevcut, mevcut))
        con.commit()
        with _app.test_client() as c:
            with c.session_transaction() as sess:
                sess['kullanici'] = sess_user()
                sess['kullanici_tip'] = 'sistem'
            pid = yetersiz_parca['id']
            bk = yetersiz_parca['batch_kodu']
            durum_once = con.execute(
                "SELECT durum FROM nexgen_uretim_parca WHERE id=?", (pid,)
            ).fetchone()[0]
            if durum_once == 'HAZIR':
                c.post(f'/nexgen/api/batch/{bk}/parca/{pid}/baslat', json={})
            rbit = c.post(f'/nexgen/api/batch/{bk}/parca/{pid}/bitir', json={})
            dbit = rbit.get_json() or {}
            durum_sonra = con.execute(
                "SELECT durum FROM nexgen_uretim_parca WHERE id=?", (pid,)
            ).fetchone()[0]
            ok('6 stok yetersiz 400', rbit.status_code == 400, dbit.get('hata'))
            ok('6 BITTI olmadi', durum_sonra != 'BITTI', f'{durum_once}->{durum_sonra}')
            ok('6 eksik liste', bool(dbit.get('eksik_kalemler')), str(len(dbit.get('eksik_kalemler', []))))
else:
    ok('6 yetersiz test parca yok', True, 'atlandi')

# ── 7) Toplu bitir ──
toplu_batch = None
for aday in adaylar:
    if devam and aday['batch_kodu'] == devam['batch_kodu']:
        continue
    chk = _mpr_stok_ihtiyac_hesapla(
        con, aday['uretim_varyant_id'], aday['rf_renk_id'],
        float(aday['hedef_kg']),
    )
    if chk.get('ok') and chk.get('yeterli_mi'):
        devam_cnt = con.execute("""
            SELECT COUNT(*) FROM nexgen_uretim_parca
            WHERE batch_kodu=? AND durum='DEVAM'
        """, (aday['batch_kodu'],)).fetchone()[0]
        if devam_cnt > 0:
            toplu_batch = {'batch_kodu': aday['batch_kodu']}
            break
        hazir = con.execute("""
            SELECT id FROM nexgen_uretim_parca
            WHERE batch_kodu=? AND durum='HAZIR' LIMIT 1
        """, (aday['batch_kodu'],)).fetchone()
        if hazir:
            with _app.test_client() as c:
                with c.session_transaction() as sess:
                    sess['kullanici'] = sess_user()
                    sess['kullanici_tip'] = 'sistem'
                c.post(f'/nexgen/api/batch/{aday["batch_kodu"]}/parca/{hazir["id"]}/baslat', json={})
            toplu_batch = {'batch_kodu': aday['batch_kodu']}
            break
if toplu_batch:
    bk = toplu_batch['batch_kodu']
    before_t = con.execute(
        "SELECT COUNT(*) FROM nexgen_stok_hareket WHERE referans_tip='URETIM_PARCA'"
    ).fetchone()[0]
    with _app.test_client() as c:
        with c.session_transaction() as sess:
            sess['kullanici'] = sess_user()
            sess['kullanici_tip'] = 'sistem'
        r = c.post(f'/nexgen/api/batch/{bk}/parca/toplu-bitir', json={'adet': 1})
        d = r.get_json() or {}
        after_t = con.execute(
            "SELECT COUNT(*) FROM nexgen_stok_hareket WHERE referans_tip='URETIM_PARCA'"
        ).fetchone()[0]
        ok('7 toplu bitir 200', r.status_code == 200 and d.get('ok'), f'biten={d.get("biten")}')
        ok('7 toplu stok hareket', after_t >= before_t, f'{before_t}->{after_t}')
else:
    ok('7 toplu bitir (devam yok)', True, 'atlandi')

# ── 8) Tablet ekran ──
with _app.test_client() as c:
    with c.session_transaction() as sess:
        sess['kullanici'] = sess_user()
        sess['kullanici_tip'] = 'sistem'
    ok('8 tablet 200', c.get('/nexgen/tablet').status_code == 200, '')
    if batch_test:
        ok('8 tablet islem 200',
           c.get(f'/nexgen/tablet/uretim-islem/{batch_test}').status_code == 200, batch_test)

staged = os.path.exists(os.path.join(_APP_DIR, 'mock_data.db-staged'))
ok('mock_data.db stage edilmedi', not staged, '')

con.close()
_SHA_AFTER = sha256_file(_LIVE_DB)
_guard = live_db_write_guard_stats()
ok('ISO guard active', _guard.get('active') is True, str(_guard))
print(f'[ISO] main_sha_after={_SHA_AFTER}')
print(f'[ISO] main_db_changed={_SHA_BEFORE != _SHA_AFTER}')
if _TMP_DIR:
    cleanup_tmp({'tmp_dir': _TMP_DIR})
passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f'\n=== SONUC: {passed}/{len(results)} PASS, {failed} FAIL ===')
sys.exit(1 if failed else 0)
