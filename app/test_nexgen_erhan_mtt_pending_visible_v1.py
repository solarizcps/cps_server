# -*- coding: utf-8 -*-
"""NEXGEN_ERHAN_MTT_PENDING_VISIBLE_TO_MEHMET_IMPLEMENT_V1 — temp DB regression T1–T10."""
from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
from copy import deepcopy
from typing import Any

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

os.environ['CPS_TEST_DB_GUARD'] = '1'

from tools.nexgen_tmp_db import (  # noqa: E402
    assert_resolved_db_is_tmp,
    canonical_db_path,
    cleanup_tmp,
    sha256_file,
)
from tools.test_db_guard import bootstrap_adhoc_script_guards  # noqa: E402

PHASE = 'NEXGEN_ERHAN_MTT_PENDING_VISIBLE_TO_MEHMET_IMPLEMENT_V1'
DEFAULT_STATUS_FILTER = (
    'ONAY_BEKLIYOR,YENI,ISLEME_ALINDI,KISMEN_NUMUNEYE_DONUSTU'
)
RESULTS: dict[str, Any] = {'phase': PHASE, 'tests': {}}


def siparis_mtt_onaya_payload(form: dict) -> dict:
    """Minimal Erhan SIPARIS → gorusme+MTT payload (MTT-640 form port)."""
    pb = (form.get('para_birimi') or 'TRY').upper()
    odeme = (form.get('odeme_sekli') or 'NAKIT').upper()
    cek_gun = int(form.get('cek_vade_gun') or 0)
    row = (form.get('kalem_rows') or [{}])[0]
    kg = float(row.get('kg') or 0)
    fiyat = float(row.get('fiyat') or 0)
    urun = row.get('urun') or 'TERLIK'
    renk = (row.get('renk') or '').strip()
    aciklama = (form.get('genel_not') or 'Sipariş talebi')[:500]
    kalem = {
        'sira_no': 1,
        'urun_aciklama': f'{urun} — {renk}',
        'urun_ailesi': urun,
        'renk_aciklama': renk,
        'miktar_kg': kg,
        'konusulan_tonaj': None,
        'verilen_fiyat': fiyat,
        'para_birimi': pb,
        'odeme_tipi': odeme,
        'vade_gun': 0 if odeme in ('NAKIT', 'KREDI_KARTI') else None,
        'cek_vade_gun': cek_gun if odeme == 'CEK' else None,
        'kalem_notu': row.get('not'),
        'iskonto_orani': 0,
        'kalem_tutari': kg * fiyat,
    }
    return {
        'cari_id': int(form['cari_id']),
        'gorusme_tipi': 'Telefon',
        'sonuc_tipi': 'Sipariş Verecek',
        'kisa_not': aciklama[:400],
        'oncelik': 'ACIL',
        'kaynak': 'MUSTERI_OPERASYONU',
        'idempotency_key': f'MO-SIP-MTT-TEST-{uuid.uuid4().hex}',
        'fiyat_verildi': 1,
        'verilen_fiyat': fiyat,
        'fiyat_para_birimi': pb,
        'fiyat_birimi': 'KG',
        'konusulan_tonaj': None,
        'odeme_tipi': odeme,
        'vade_gun': 0 if odeme in ('NAKIT', 'KREDI_KARTI') else None,
        'cek_vade_gun': cek_gun if odeme == 'CEK' else None,
        'talep': {
            'talep_turu': 'SIPARIS',
            'oncelik': 'ACIL',
            'aciklama': aciklama,
            'musteri_notu': form.get('musteri_notu') or '',
            'kalemler': [kalem],
        },
    }


def erhan_form() -> dict:
    return {
        'cari_id': 9,
        'para_birimi': 'TRY',
        'odeme_sekli': 'CEK',
        'cek_vade_gun': 220,
        'genel_not': 'pending visible regression',
        'kalem_rows': [{'urun': 'TERLIK', 'renk': 'siya', 'kg': 3000.0, 'fiyat': 3.0, 'not': 't'}],
    }


def numune_payload() -> dict:
    return {
        'cari_id': 9,
        'gorusme_tipi': 'Telefon',
        'sonuc_tipi': 'Numune İstedi',
        'kisa_not': 'numune regression',
        'oncelik': 'NORMAL',
        'kaynak': 'MUSTERI_OPERASYONU',
        'idempotency_key': f'MO-NUM-REG-{uuid.uuid4().hex}',
        'fiyat_verildi': 0,
        'talep': {
            'talep_turu': 'NUMUNE',
            'oncelik': 'NORMAL',
            'aciklama': 'Numune regression',
            'musteri_notu': 'Numune regression',
            'kalemler': [{
                'urun_aciklama': 'Taban — siyah',
                'urun_ailesi': 'TABAN',
                'renk_aciklama': 'siyah',
                'miktar_kg': 1,
            }],
        },
    }


def db_counts(con: sqlite3.Connection) -> dict[str, int]:
    def cnt(sql: str) -> int:
        return int(con.execute(sql).fetchone()[0])
    return {
        'gorusme': cnt('SELECT COUNT(*) FROM musteri_operasyon_gorusme'),
        'mtt': cnt('SELECT COUNT(*) FROM nexgen_musteri_temsilcisi_talep'),
        'kalem': cnt('SELECT COUNT(*) FROM nexgen_musteri_temsilcisi_talep_kalem'),
        'onay': cnt('SELECT COUNT(*) FROM nexgen_onay'),
    }


def user_row(con: sqlite3.Connection, uid: int) -> dict:
    row = con.execute(
        """
        SELECT k.Id, k.KullaniciAdi, k.AdSoyad, k.RolId, k.Aktif,
               k.ZorunluSifreDegistir, k.AuthVersion, r.Ad AS RolAd
        FROM sistem_kullanici k
        LEFT JOIN sistem_rol r ON r.Id = k.RolId
        WHERE k.Id = ?
        """,
        (uid,),
    ).fetchone()
    if not row:
        raise RuntimeError(f'user {uid} missing')
    return {
        'Id': row['Id'],
        'KullaniciAdi': row['KullaniciAdi'],
        'AdSoyad': row['AdSoyad'],
        'Tip': 'sistem',
        'RolId': row['RolId'],
        'RolAd': row['RolAd'],
        'Aktif': row['Aktif'],
        'ZorunluSifreDegistir': int(row['ZorunluSifreDegistir'] or 0),
        'AuthVersion': int(row['AuthVersion'] or 1),
    }


def session_user(client, user: dict) -> None:
    with client.session_transaction() as sess:
        sess['kullanici'] = user
        sess['kullanici_tip'] = 'sistem'


def setup_temp_db() -> tuple[str, str, str]:
    bootstrap_adhoc_script_guards()
    live = canonical_db_path()
    tmp_dir = tempfile.mkdtemp(prefix='mtt_pending_vis_')
    db = os.path.join(tmp_dir, 'mock_data_test.db')
    shutil.copy2(live, db)
    assert_resolved_db_is_tmp(db, live)
    os.environ['CPS_MOCK_DB_PATH'] = db
    return db, live, tmp_dir


def make_client(db: str):
    import config as cfg
    cfg.Config.MOCK_DB_PATH = db
    import app as flask_app
    flask_app.app.config['TESTING'] = True
    return flask_app.app.test_client()


def record(name: str, ok: bool, **extra: Any) -> None:
    RESULTS['tests'][name] = {'pass': ok, **extra}
    print(f'[{name}] {"PASS" if ok else "FAIL"}', json.dumps(extra, ensure_ascii=False)[:500])


def main() -> int:
    live = canonical_db_path()
    canon_sha_before = sha256_file(live)
    con_ro = sqlite3.connect(f'file:{live}?mode=ro', uri=True)
    canon_counts_before = db_counts(con_ro)
    con_ro.close()

    db, _live, tmp_dir = setup_temp_db()
    client = make_client(db)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    erhan = user_row(con, 49)
    mehmet = user_row(con, 31)
    admin = user_row(con, 1)
    outside = con.execute(
        "SELECT id FROM nexgen_cari WHERE COALESCE(aktif,1)=1 AND id NOT IN "
        "(SELECT cari_id FROM cari_sorumlu WHERE kullanici_id=49 "
        "AND sorumluluk_rolu='ANA' AND aktif=1) ORDER BY id LIMIT 1"
    ).fetchone()
    con.close()

    # T1 — Erhan SIPARIS POST
    payload = siparis_mtt_onaya_payload(erhan_form())
    session_user(client, erhan)
    before = db_counts(sqlite3.connect(db))
    r1 = client.post('/nexgen/api/musteri-pazarlama/gorusme', json=payload)
    body1 = r1.get_json() or {}
    after = db_counts(sqlite3.connect(db))
    delta = {k: after[k] - before[k] for k in before}
    talep_id = body1.get('talep_id')
    onay_id = body1.get('onay_id')
    if not onay_id and talep_id:
        con2 = sqlite3.connect(db)
        con2.row_factory = sqlite3.Row
        onay_id = con2.execute(
            "SELECT id FROM nexgen_onay WHERE kaynak_turu='MUSTERI_TEMSILCISI_TALEP' "
            "AND kaynak_id=? ORDER BY id DESC LIMIT 1",
            (int(talep_id),),
        ).fetchone()
        onay_id = int(onay_id['id']) if onay_id else None
        durum = con2.execute(
            'SELECT durum FROM nexgen_musteri_temsilcisi_talep WHERE id=?', (int(talep_id),),
        ).fetchone()
        mtt_durum = durum['durum'] if durum else None
        con2.close()
    else:
        mtt_durum = body1.get('talep_durum')
    t1_ok = (
        r1.status_code == 200 and body1.get('ok')
        and delta['gorusme'] > 0 and delta['mtt'] > 0
        and delta['kalem'] > 0 and delta['onay'] > 0
        and mtt_durum == 'ONAY_BEKLIYOR'
    )
    record('T1_erhan_siparis_post', t1_ok, status=r1.status_code, delta=delta, mtt_durum=mtt_durum)

    # T2 — Mehmet default list (backend varsayılan kapsam + arama ile doğrula)
    session_user(client, mehmet)
    talep_no = body1.get('talep_no') or ''
    r2 = client.get(f'/nexgen/api/musteri-temsilcisi-talep?q={talep_no}')
    body2 = r2.get_json() or {}
    ids2 = [x.get('id') for x in (body2.get('kayitlar') or [])]
    kuyruk = int(body2.get('kuyruk_sayisi') or 0)
    durumlar2 = {x.get('durum') for x in (body2.get('kayitlar') or [])}
    allowed = {'ONAY_BEKLIYOR', 'YENI', 'ISLEME_ALINDI', 'KISMEN_NUMUNEYE_DONUSTU'}
    t2_ok = (
        r2.status_code == 200 and body2.get('ok')
        and talep_id in ids2 and durumlar2 <= allowed and kuyruk >= 1
    )
    record('T2_mehmet_default_list', t2_ok, in_list=talep_id in ids2, kuyruk=kuyruk, n=len(ids2))

    # T3 — explicit durum filter
    r3a = client.get('/nexgen/api/musteri-temsilcisi-talep?durumlar=YENI')
    r3b = client.get('/nexgen/api/musteri-temsilcisi-talep?durumlar=ONAY_BEKLIYOR')
    a = r3a.get_json() or {}
    b = r3b.get_json() or {}
    only_yeni = all((x.get('durum') == 'YENI') for x in (a.get('kayitlar') or []))
    only_onay = all((x.get('durum') == 'ONAY_BEKLIYOR') for x in (b.get('kayitlar') or []))
    t3_ok = only_yeni and only_onay and talep_id not in [x.get('id') for x in (a.get('kayitlar') or [])]
    record('T3_explicit_durum_filter', t3_ok, yeni_only=only_yeni, onay_only=only_onay)

    # T4 — detail GET
    r4 = client.get(f'/nexgen/api/musteri-temsilcisi-talep/{talep_id}')
    k4 = (r4.get_json() or {}).get('kayit') or {}
    t4_ok = (
        r4.status_code == 200 and k4.get('durum') == 'ONAY_BEKLIYOR'
        and bool(k4.get('talep_no')) and bool(k4.get('kalemler'))
    )
    record('T4_pending_detail', t4_ok, durum=k4.get('durum'), kalemler=len(k4.get('kalemler') or []))

    # T5 — isleme al 409, DB unchanged
    con5 = sqlite3.connect(db)
    snap5 = con5.execute(
        'SELECT durum, atanan_kullanici_id FROM nexgen_musteri_temsilcisi_talep WHERE id=?',
        (int(talep_id),),
    ).fetchone()
    con5.close()
    r5 = client.post(f'/nexgen/api/musteri-temsilcisi-talep/{talep_id}/isleme-al', json={})
    b5 = r5.get_json() or {}
    con5b = sqlite3.connect(db)
    snap5b = con5b.execute(
        'SELECT durum, atanan_kullanici_id FROM nexgen_musteri_temsilcisi_talep WHERE id=?',
        (int(talep_id),),
    ).fetchone()
    con5b.close()
    t5_ok = r5.status_code == 409 and not b5.get('ok') and snap5 == snap5b
    record('T5_pending_isleme_al_409', t5_ok, status=r5.status_code, mesaj=b5.get('mesaj'))

    # T6 — conversion guards (hazirla read-only reddeder; reddet 409; durum korunur)
    r6a = client.get(f'/nexgen/api/musteri-temsilcisi-talep/{talep_id}/siparis-hazirla')
    r6b = client.get(f'/nexgen/api/musteri-temsilcisi-talep/{talep_id}/numune-hazirla')
    r6c = client.post(
        f'/nexgen/api/musteri-temsilcisi-talep/{talep_id}/reddet',
        json={'red_nedeni': 'test'},
    )
    b6a = r6a.get_json() or {}
    b6b = r6b.get_json() or {}
    con6 = sqlite3.connect(db)
    con6.row_factory = sqlite3.Row
    row6 = con6.execute(
        'SELECT durum, donusturulen_siparis_id, donusturulen_numune_talep_id '
        'FROM nexgen_musteri_temsilcisi_talep WHERE id=?',
        (int(talep_id),),
    ).fetchone()
    con6.close()
    t6_ok = (
        r6a.status_code == 200 and b6a.get('donusum_izin') is False
        and r6b.status_code == 200 and b6b.get('donusum_izin') is False
        and r6c.status_code == 409
        and row6['durum'] == 'ONAY_BEKLIYOR'
        and not row6['donusturulen_siparis_id']
        and not row6['donusturulen_numune_talep_id']
    )
    record(
        'T6_pending_conversion_guard', t6_ok,
        siparis_hazirla={'status': r6a.status_code, 'donusum_izin': b6a.get('donusum_izin')},
        numune_hazirla={'status': r6b.status_code, 'donusum_izin': b6b.get('donusum_izin')},
        reddet=r6c.status_code, mtt_durum_after=row6['durum'],
    )

    # T7 — onay → YENI → isleme al
    session_user(client, admin)
    r7a = client.post(f'/nexgen/api/yonetim/onay/{onay_id}/onayla', json={})
    b7a = r7a.get_json() or {}
    session_user(client, mehmet)
    con7 = sqlite3.connect(db)
    dur7 = con7.execute(
        'SELECT durum FROM nexgen_musteri_temsilcisi_talep WHERE id=?', (int(talep_id),),
    ).fetchone()[0]
    con7.close()
    r7b = client.get('/nexgen/api/musteri-temsilcisi-talep?limit=100')
    still_listed = talep_id in [x.get('id') for x in ((r7b.get_json() or {}).get('kayitlar') or [])]
    r7c = client.post(f'/nexgen/api/musteri-temsilcisi-talep/{talep_id}/isleme-al', json={})
    b7c = r7c.get_json() or {}
    t7_ok = (
        r7a.status_code == 200 and b7a.get('ok') and dur7 == 'YENI'
        and still_listed and r7c.status_code == 200 and b7c.get('ok')
        and (b7c.get('kayit') or {}).get('durum') == 'ISLEME_ALINDI'
    )
    record('T7_approval_to_yeni_isleme', t7_ok, durum_after_onay=dur7, isleme_status=r7c.status_code)

    # T8 — Erhan MTT 639–641 regression
    t8_ok = True
    t8_detail: dict[str, Any] = {}
    for mid in (639, 640, 641):
        rl = client.get(f'/nexgen/api/musteri-temsilcisi-talep?gorusme_id=&limit=500')
        rd = client.get(f'/nexgen/api/musteri-temsilcisi-talep/{mid}')
        ok_d = rd.status_code == 200 and (rd.get_json() or {}).get('ok')
        t8_detail[str(mid)] = {'detail': rd.status_code, 'ok': ok_d}
        if not ok_d:
            t8_ok = False
    for mid in (639, 640, 641):
        rd = client.get(f'/nexgen/api/musteri-temsilcisi-talep/{mid}')
        if rd.status_code != 200 or not (rd.get_json() or {}).get('ok'):
            t8_ok = False
    record('T8_erhan_mtt_639_641_regression', t8_ok, **t8_detail)

    # T9 — numune + gorusme flow
    session_user(client, erhan)
    before9 = db_counts(sqlite3.connect(db))
    r9 = client.post('/nexgen/api/musteri-pazarlama/gorusme', json=numune_payload())
    b9 = r9.get_json() or {}
    after9 = db_counts(sqlite3.connect(db))
    t9_ok = (
        r9.status_code == 200 and b9.get('ok')
        and after9['gorusme'] > before9['gorusme']
        and after9['mtt'] > before9['mtt']
    )
    record('T9_numune_gorusme_regression', t9_ok, status=r9.status_code, talep_durum=b9.get('talep_durum'))

    # T10 — auth scope
    session_user(client, erhan)
    r10a = client.get('/nexgen/api/musteri-temsilcisi-talep')
    out_scope = deepcopy(payload)
    out_scope['cari_id'] = int(outside['id']) if outside else 99999
    out_scope['idempotency_key'] = f'MO-SIP-OUT-{uuid.uuid4().hex}'
    r10b = client.post('/nexgen/api/musteri-pazarlama/gorusme', json=out_scope)
    t10_ok = r10a.status_code == 403 and r10b.status_code in (403, 400)
    record(
        'T10_auth_scope', t10_ok,
        mehmet_queue_status=r10a.status_code, out_cari_status=r10b.status_code,
    )

    cleanup_tmp({'tmp_dir': tmp_dir})

    canon_sha_after = sha256_file(live)
    con_ro2 = sqlite3.connect(f'file:{live}?mode=ro', uri=True)
    canon_counts_after = db_counts(con_ro2)
    con_ro2.close()

    all_pass = all(v.get('pass') for v in RESULTS['tests'].values())
    RESULTS['summary'] = {
        'all_pass': all_pass,
        'canonical_sha_unchanged': canon_sha_before == canon_sha_after,
        'canonical_counts_before': canon_counts_before,
        'canonical_counts_after': canon_counts_after,
        'default_status_filter': DEFAULT_STATUS_FILTER,
    }
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        '_audit_out',
        'nexgen_erhan_mtt_pending_visible_v1_results.json',
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump(RESULTS, fh, ensure_ascii=False, indent=2)
    print('\nSUMMARY', json.dumps(RESULTS['summary'], ensure_ascii=False))
    print('results_file', out_path)
    return 0 if all_pass else 1


if __name__ == '__main__':
    raise SystemExit(main())
