# -*- coding: utf-8 -*-
"""NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1 — temp DB regression T1–T22."""
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
from unittest import mock

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

PHASE = 'NEXGEN_DIRECT_SIPARIS_END_TO_END_REGRESSION_LOCK_V1'
RESULTS: dict[str, Any] = {'phase': PHASE, 'tests': {}}


def siparis_popup_payload(idem: str | None = None) -> dict:
    key = idem or f'MO-SIP-POP-{uuid.uuid4().hex}'
    return {
        'idempotency_key': key,
        'cari_id': 9,
        'para_birimi': 'TRY',
        'odeme_sekli': 'CEK',
        'cek_vade_gun': 180,
        'teslim_sekli': 'FABRIKA_TESLIM',
        'istenen_termin': '2026-10-15',
        'siparis_onceligi': 'ACIL',
        'genel_not': 'canonical siparis popup test',
        'musteri_notu': 'musteri notu test',
        'kdv_durumu': 'GAYRI',
        'kdv_orani': 0,
        'ara_toplam': 9000,
        'kdv_tutari': 0,
        'genel_toplam': 9000,
        'kalemler': [{
            'sira_no': 1,
            'urun_ailesi': 'TERLIK',
            'renk_aciklama': 'siyah',
            'miktar_kg': '3.000',
            'verilen_fiyat': '3',
            'kalem_notu': 'kalem test',
        }],
    }


def normal_gorusme_payload() -> dict:
    return {
        'cari_id': 9,
        'gorusme_tipi': 'Telefon',
        'sonuc_tipi': 'Tamamlandı',
        'kisa_not': 'normal gorusme regression',
        'fiyat_verildi': 0,
        'idempotency_key': f'MO-NORM-{uuid.uuid4().hex}',
        'kaynak': 'MUSTERI_OPERASYONU',
    }


def numune_popup_payload() -> dict:
    return {
        'musteri_tipi': 'MEVCUT',
        'cari_id': 9,
        'urun_adi': 'Taban test',
        'urun_tipi': 'TABAN',
        'referans_renk': 'siyah',
        'musteri_talebi': 'numune popup regression',
        'oncelik': 'NORMAL',
        'idempotency_key': f'MO-NUM-POP-{uuid.uuid4().hex}',
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
    tmp_dir = tempfile.mkdtemp(prefix='siparis_pop_guard_')
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
    print(f'[{name}] {"PASS" if ok else "FAIL"}', json.dumps(extra, ensure_ascii=False)[:600])


def contract_ok(body: dict) -> bool:
    return bool(
        body.get('ok')
        and body.get('gorusme_id')
        and body.get('talep_id')
        and body.get('talep_no')
        and body.get('onay_id')
        and body.get('onay_no')
        and body.get('talep_durum') == 'ONAY_BEKLIYOR'
        and body.get('onay_durum') == 'ONAY_BEKLIYOR'
    )


def onay_row(con: sqlite3.Connection, onay_id: int) -> dict | None:
    row = con.execute(
        'SELECT id, durum, onaylayan_kullanici_id, karar_tarihi, kaynak_id FROM nexgen_onay WHERE id=?',
        (onay_id,),
    ).fetchone()
    return dict(row) if row else None


def header_has_pending(client, admin_user: dict, onay_id: int, talep_no: str) -> bool:
    session_user(client, admin_user)
    r = client.get('/nexgen/api/onay-merkezi/bekleyen-ozet')
    body = r.get_json() or {}
    for item in body.get('liste') or []:
        if item.get('source') == 'MTT' and (
            int(item.get('id') or 0) == int(onay_id)
            or (item.get('mtt_kod') or item.get('talep_kod')) == talep_no
        ):
            return True
    return False


def management_has_pending(client, admin_user: dict, onay_id: int, talep_no: str) -> bool:
    session_user(client, admin_user)
    r = client.get(
        '/nexgen/api/yonetim/onaylar?kaynak_turu=MUSTERI_TEMSILCISI_TALEP&durum=ONAY_BEKLIYOR&limit=200',
    )
    body = r.get_json() or {}
    for item in body.get('liste') or []:
        if int(item.get('id') or 0) == int(onay_id) or item.get('talep_no') == talep_no:
            return True
    return False


def mehmet_has_mtt(client, mehmet_user: dict, talep_id: int, *, durum: str | None = None) -> bool:
    session_user(client, mehmet_user)
    url = '/nexgen/api/musteri-temsilcisi-talep?talep_turu=SIPARIS&limit=200'
    if durum:
        url += f'&durum={durum}'
    r = client.get(url)
    body = r.get_json() or {}
    for item in body.get('kayitlar') or []:
        if int(item.get('id') or 0) == int(talep_id):
            return (not durum) or (item.get('durum') or '').upper() == durum.upper()
    return False


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
    con.close()

    session_user(client, erhan)

    # T1 — tam sipariş popup payload
    payload = siparis_popup_payload()
    before = db_counts(sqlite3.connect(db))
    r1 = client.post('/nexgen/api/musteri-pazarlama/siparis-mtt-onaya', json=payload)
    b1 = r1.get_json() or {}
    after = db_counts(sqlite3.connect(db))
    delta = {k: after[k] - before[k] for k in before}
    talep_id = b1.get('talep_id')
    onay_id = b1.get('onay_id')
    con1 = sqlite3.connect(db)
    con1.row_factory = sqlite3.Row
    mtt_row = con1.execute(
        'SELECT durum, olusturan_kullanici_id, talep_turu FROM nexgen_musteri_temsilcisi_talep WHERE id=?',
        (int(talep_id),),
    ).fetchone() if talep_id else None
    o_row = con1.execute(
        "SELECT durum, kaynak_turu, kaynak_id FROM nexgen_onay WHERE id=?",
        (int(onay_id),),
    ).fetchone() if onay_id else None
    kalem_c = int(con1.execute(
        'SELECT COUNT(*) FROM nexgen_musteri_temsilcisi_talep_kalem WHERE talep_id=?',
        (int(talep_id),),
    ).fetchone()[0]) if talep_id else 0
    con1.close()
    t1_ok = (
        r1.status_code == 200 and contract_ok(b1)
        and delta['gorusme'] == 1 and delta['mtt'] == 1 and delta['onay'] == 1
        and delta['kalem'] >= 1
        and mtt_row and mtt_row['durum'] == 'ONAY_BEKLIYOR'
        and mtt_row['talep_turu'] == 'SIPARIS'
        and int(mtt_row['olusturan_kullanici_id']) == 49
        and o_row and o_row['durum'] == 'ONAY_BEKLIYOR'
        and o_row['kaynak_turu'] == 'MUSTERI_TEMSILCISI_TALEP'
        and int(o_row['kaynak_id']) == int(talep_id)
        and kalem_c >= 1
    )
    record('T1_full_siparis_popup', t1_ok, status=r1.status_code, delta=delta, mesaj=b1.get('mesaj'))

    # T2 — onay oluşturma başarısız → rollback
    before2 = db_counts(sqlite3.connect(db))
    p2 = siparis_popup_payload(f'MO-SIP-FAIL-{uuid.uuid4().hex}')
    with mock.patch(
        'modules.nexgen.onay_service.onay_olustur_mtt',
        side_effect=RuntimeError('onay_fail_test'),
    ):
        r2 = client.post('/nexgen/api/musteri-pazarlama/siparis-mtt-onaya', json=p2)
    after2 = db_counts(sqlite3.connect(db))
    d2 = {k: after2[k] - before2[k] for k in before2}
    t2_ok = r2.status_code >= 400 and all(v == 0 for v in d2.values())
    record('T2_rollback_onay_fail', t2_ok, status=r2.status_code, delta=d2)

    # T3 — kalem eksik
    before3 = db_counts(sqlite3.connect(db))
    p3 = siparis_popup_payload(f'MO-SIP-NOKLM-{uuid.uuid4().hex}')
    p3['kalemler'] = []
    r3 = client.post('/nexgen/api/musteri-pazarlama/siparis-mtt-onaya', json=p3)
    after3 = db_counts(sqlite3.connect(db))
    d3 = {k: after3[k] - before3[k] for k in before3}
    t3_ok = r3.status_code in (400, 422) and all(v == 0 for v in d3.values())
    record('T3_missing_kalem', t3_ok, status=r3.status_code, delta=d3)

    # T4 — cari eksik
    before4 = db_counts(sqlite3.connect(db))
    p4 = siparis_popup_payload(f'MO-SIP-NOCARI-{uuid.uuid4().hex}')
    del p4['cari_id']
    r4 = client.post('/nexgen/api/musteri-pazarlama/siparis-mtt-onaya', json=p4)
    after4 = db_counts(sqlite3.connect(db))
    d4 = {k: after4[k] - before4[k] for k in before4}
    t4_ok = r4.status_code in (400, 422) and all(v == 0 for v in d4.values())
    record('T4_missing_cari', t4_ok, status=r4.status_code)

    # T5 — termin/para/odeme eksik
    before5 = db_counts(sqlite3.connect(db))
    p5 = siparis_popup_payload(f'MO-SIP-NOTER-{uuid.uuid4().hex}')
    p5.pop('istenen_termin')
    p5.pop('para_birimi')
    p5.pop('odeme_sekli')
    r5 = client.post('/nexgen/api/musteri-pazarlama/siparis-mtt-onaya', json=p5)
    after5 = db_counts(sqlite3.connect(db))
    d5 = {k: after5[k] - before5[k] for k in before5}
    t5_ok = r5.status_code in (400, 422) and all(v == 0 for v in d5.values())
    record('T5_missing_header_fields', t5_ok, status=r5.status_code)

    # T6 — duplicate idempotency
    idem6 = f'MO-SIP-DUP-{uuid.uuid4().hex}'
    p6 = siparis_popup_payload(idem6)
    r6a = client.post('/nexgen/api/musteri-pazarlama/siparis-mtt-onaya', json=p6)
    before6 = db_counts(sqlite3.connect(db))
    r6b = client.post('/nexgen/api/musteri-pazarlama/siparis-mtt-onaya', json=deepcopy(p6))
    after6 = db_counts(sqlite3.connect(db))
    b6a = r6a.get_json() or {}
    b6b = r6b.get_json() or {}
    d6 = {k: after6[k] - before6[k] for k in before6}
    t6_ok = (
        contract_ok(b6a) and contract_ok(b6b)
        and b6a.get('talep_id') == b6b.get('talep_id')
        and all(v == 0 for v in d6.values())
    )
    record('T6_idempotency', t6_ok, delta=d6)

    # T7 — response contract (T1 body)
    t7_ok = contract_ok(b1) and b1.get('mesaj') == 'Talebiniz yönetim onayına gönderildi.'
    record('T7_response_contract', t7_ok, body_keys=sorted(b1.keys()))

    # T13 — kendi kendine onay yok (T1)
    con13 = sqlite3.connect(db)
    con13.row_factory = sqlite3.Row
    orow = onay_row(con13, int(onay_id)) if onay_id else None
    con13.close()
    t13_ok = bool(
        orow
        and orow.get('durum') == 'ONAY_BEKLIYOR'
        and orow.get('onaylayan_kullanici_id') in (None, 0, '')
        and orow.get('karar_tarihi') in (None, '')
    )
    record('T13_no_self_approval', t13_ok, onay=orow)

    # T14 — header Onaylar API görünürlüğü
    t14_ok = header_has_pending(client, admin, int(onay_id), b1.get('talep_no') or '')
    record('T14_header_visibility', t14_ok, onay_id=onay_id, talep_no=b1.get('talep_no'))

    # T15 — yönetim onay API görünürlüğü
    t15_ok = management_has_pending(client, admin, int(onay_id), b1.get('talep_no') or '')
    record('T15_management_visibility', t15_ok, onay_id=onay_id)

    # T16 — red akışı (ayrı kayıt; Mehmet YENI kuyruğuna düşmez)
    session_user(client, erhan)
    p16 = siparis_popup_payload(f'MO-SIP-REJ-{uuid.uuid4().hex}')
    r16a = client.post('/nexgen/api/musteri-pazarlama/siparis-mtt-onaya', json=p16)
    b16 = r16a.get_json() or {}
    rej_talep = int(b16.get('talep_id') or 0)
    rej_onay = int(b16.get('onay_id') or 0)
    session_user(client, admin)
    r16b = client.post(
        f'/nexgen/api/yonetim/onay/{rej_onay}/reddet',
        json={'red_nedeni': 'regression reject test'},
    )
    con16 = sqlite3.connect(db)
    con16.row_factory = sqlite3.Row
    rej_mtt_d = con16.execute('SELECT durum FROM nexgen_musteri_temsilcisi_talep WHERE id=?', (rej_talep,)).fetchone()
    rej_on_d = con16.execute('SELECT durum FROM nexgen_onay WHERE id=?', (rej_onay,)).fetchone()
    con16.close()
    t16_ok = (
        contract_ok(b16)
        and r16b.status_code == 200
        and rej_mtt_d and rej_mtt_d['durum'] == 'REDDEDILDI'
        and rej_on_d and rej_on_d['durum'] == 'REDDEDILDI'
        and not mehmet_has_mtt(client, mehmet, rej_talep, durum='YENI')
    )
    record('T16_reject_flow', t16_ok, rej_talep=rej_talep, rej_onay=rej_onay)

    # T8 — numune popup regression
    session_user(client, erhan)
    before8 = db_counts(sqlite3.connect(db))
    r8 = client.post('/nexgen/api/musteri-pazarlama/numune-mtt-onaya', json=numune_popup_payload())
    b8 = r8.get_json() or {}
    after8 = db_counts(sqlite3.connect(db))
    t8_ok = r8.status_code == 200 and b8.get('ok') and after8['mtt'] > before8['mtt']
    record('T8_numune_popup_unchanged', t8_ok, status=r8.status_code)

    # T9 — normal görüşme regression
    before9 = db_counts(sqlite3.connect(db))
    r9 = client.post('/nexgen/api/musteri-pazarlama/gorusme', json=normal_gorusme_payload())
    b9 = r9.get_json() or {}
    after9 = db_counts(sqlite3.connect(db))
    t9_ok = (
        r9.status_code == 200 and b9.get('ok')
        and after9['gorusme'] > before9['gorusme']
        and after9['mtt'] == before9['mtt']
        and not b9.get('talep_olusturuldu')
    )
    record('T9_normal_gorusme_unchanged', t9_ok, status=r9.status_code)

    # T10 — Alpay/Adem onay → YENI (T1 talep)
    session_user(client, admin)
    r10 = client.post(f'/nexgen/api/yonetim/onay/{onay_id}/onayla', json={})
    b10 = r10.get_json() or {}
    con10 = sqlite3.connect(db)
    con10.row_factory = sqlite3.Row
    dur10 = con10.execute(
        'SELECT durum FROM nexgen_musteri_temsilcisi_talep WHERE id=?', (int(talep_id),),
    ).fetchone()[0]
    apr10 = onay_row(con10, int(onay_id))
    con10.close()
    t10_ok = (
        r10.status_code == 200 and b10.get('ok') and dur10 == 'YENI'
        and apr10 and apr10.get('durum') == 'ONAYLANDI'
        and apr10.get('onaylayan_kullanici_id') not in (None, 0, '')
    )
    record('T10_approval_flow', t10_ok, durum=dur10, onay=apr10)

    # T17 — Mehmet kuyruğunda YENI Sipariş Talebi
    t17_ok = mehmet_has_mtt(client, mehmet, int(talep_id), durum='YENI')
    record('T17_mehmet_yeni_visible', t17_ok, talep_id=talep_id)

    # T11 — Mehmet isleme al
    session_user(client, mehmet)
    r11 = client.post(f'/nexgen/api/musteri-temsilcisi-talep/{talep_id}/isleme-al', json={})
    b11 = r11.get_json() or {}
    t11_ok = r11.status_code == 200 and b11.get('ok')
    record('T11_mehmet_isleme_al', t11_ok, status=r11.status_code)

    # T18 — dönüşüm prefill (siparis-hazirla)
    r18 = client.get(f'/nexgen/api/musteri-temsilcisi-talep/{talep_id}/siparis-hazirla')
    b18 = r18.get_json() or {}
    hydrate = b18.get('hydrate') or {}
    ticari = b18.get('ticari_snapshot') or {}
    hk = (hydrate.get('kalemler') or [{}])[0]
    t18_ok = (
        r18.status_code == 200 and b18.get('ok')
        and int(hydrate.get('cari_id') or 0) == int(payload['cari_id'])
        and (hydrate.get('anlasma_para_birimi') or ticari.get('para_birimi')) == payload['para_birimi']
        and hydrate.get('odeme_tipi') or ticari.get('odeme_tipi')
        and hydrate.get('mo_meta', {}).get('teslim_sekli') == payload['teslim_sekli']
        and hydrate.get('siparis_onceligi') == payload['siparis_onceligi']
        and (hydrate.get('istenen_termin') or ticari.get('istenen_termin')) == payload['istenen_termin']
        and (hk.get('miktar_l') or hk.get('miktar_m') or 0)
        and hk.get('birim_fiyat') is not None
        and float(ticari.get('genel_toplam') or hydrate.get('genel_toplam') or 0) == float(payload['genel_toplam'])
    )
    record('T18_conversion_prefill', t18_ok, eksik=b18.get('eksik_zorunlu_alanlar'))

    # T19 — teknik guard: eksik alanlar + taslak kayıt engeli
    eksik = b18.get('eksik_zorunlu_alanlar') or []
    t19_guard_list = any(
        'formul' in str(x).lower() or 'renk' in str(x).lower() or 'termin' in str(x).lower()
        for x in eksik
    )
    save_payload = dict(hydrate)
    save_payload['kaynak_mtt_talep_id'] = int(talep_id)
    save_payload['kalemler'] = hydrate.get('kalemler') or []
    r19 = client.post('/nexgen/api/pazarlama/taslak-kaydet', json=save_payload)
    b19 = r19.get_json() or {}
    t19_ok = t19_guard_list and r19.status_code >= 400 and not b19.get('ok')
    record('T19_technical_guard', t19_ok, eksik=eksik[:5], status=r19.status_code)

    # T20 — Erhan sonuç bildirimi (onay sonrası)
    session_user(client, erhan)
    r20 = client.get('/nexgen/api/musteri-pazarlama/bildirimler')
    b20 = r20.get_json() or {}
    hits = [
        x for x in (b20.get('liste') or [])
        if (x.get('talep_no') == b1.get('talep_no') or int(x.get('mtt_id') or 0) == int(talep_id))
    ]
    t20_ok = r20.status_code == 200 and b20.get('ok') and len(hits) >= 1
    record('T20_erhan_notification', t20_ok, hits=len(hits))

    # T12 — legacy kapalı
    session_user(client, erhan)
    r12 = client.post('/nexgen/api/musteri-pazarlama/siparis-talep', json={})
    b12 = r12.get_json() or {}
    t12_ok = r12.status_code == 410 and b12.get('kod') == 'LEGACY_MO_SIPARIS_TASLAK_KAPALI'
    record('T12_legacy_still_closed', t12_ok, status=r12.status_code)

    # T21 — legacy siparis onaya-gonder kapalı
    r21 = client.post('/nexgen/api/musteri-pazarlama/siparis-talep/0/onaya-gonder', json={})
    b21 = r21.get_json() or {}
    t21_ok = r21.status_code == 410 and b21.get('kod') == 'LEGACY_MO_SIPARIS_ONAY_KAPALI'
    record('T21_legacy_onaya_gonder_closed', t21_ok, status=r21.status_code)

    # T22 — Erhan header onay API erişemez
    session_user(client, erhan)
    r22 = client.get('/nexgen/api/onay-merkezi/bekleyen-ozet')
    t22_ok = r22.status_code in (302, 403)
    record('T22_erhan_no_header_onay', t22_ok, status=r22.status_code)

    cleanup_tmp({'tmp_dir': tmp_dir})

    canon_sha_after = sha256_file(live)
    con_ro2 = sqlite3.connect(f'file:{live}?mode=ro', uri=True)
    canon_counts_after = db_counts(con_ro2)
    con_ro2.close()

    all_pass = all(v.get('pass') for v in RESULTS['tests'].values())
    RESULTS['summary'] = {
        'all_pass': all_pass,
        'canonical_sha_before': canon_sha_before,
        'canonical_sha_after': canon_sha_after,
        'canonical_sha_unchanged': canon_sha_before == canon_sha_after,
        'canonical_counts_before': canon_counts_before,
        'canonical_counts_after': canon_counts_after,
    }
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        '_audit_out',
        'nexgen_siparis_end_to_end_regression_lock_v1_results.json',
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=2)
    print('SUMMARY', json.dumps(RESULTS['summary'], ensure_ascii=False))
    print('results_file', out_path)
    return 0 if all_pass else 1


if __name__ == '__main__':
    raise SystemExit(main())
