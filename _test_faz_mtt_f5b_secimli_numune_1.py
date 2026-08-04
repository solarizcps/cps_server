# -*- coding: utf-8 -*-
"""FAZ-MTT-F5B — seçimli / kısmi numune dönüşüm testleri (local)."""
from __future__ import annotations

import importlib
import os
import sqlite3
import sys
import traceback
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'app')
sys.path.insert(0, APP)

mig147 = importlib.import_module('migrations.147_nexgen_mtt_kalem_numune_pointer')
from modules.nexgen.musteri_temsilcisi_talep_service import (  # noqa: E402
    MusteriTemsilcisiTalepError,
)
from modules.nexgen.mtt_donusum_service import (  # noqa: E402
    numune_hazirla,
    numune_mtt_ile_kaydet,
)

DB = os.path.join(APP, 'mock_data.db')
PASS = 0
FAIL = 0


def ok(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  PASS  {name}')
    else:
        FAIL += 1
        print(f'  FAIL  {name} {detail}')


def con():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _seed_numune(c, n_kalem=3, durum='ISLEME_ALINDI'):
    now = '2026-07-30 15:00:00'
    cari = c.execute('SELECT id FROM nexgen_cari WHERE COALESCE(aktif,1)=1 LIMIT 1').fetchone()
    g = c.execute(
        'SELECT id FROM musteri_operasyon_gorusme WHERE cari_id=? LIMIT 1',
        (cari['id'],),
    ).fetchone()
    u = c.execute(
        "SELECT Id FROM sistem_kullanici WHERE lower(KullaniciAdi)='mehmet' LIMIT 1"
    ).fetchone()
    mid = int(u['Id']) if u else 1
    tno = f'MTT-F5B-{uuid.uuid4().hex[:8].upper()}'
    cur = c.execute(
        """
        INSERT INTO nexgen_musteri_temsilcisi_talep (
          talep_no, talep_turu, durum, gorusme_id, cari_id, musteri_aday_id,
          olusturan_kullanici_id, atanan_kullanici_id, oncelik, aciklama,
          idempotency_key, isleme_alinma_tarihi, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            tno, 'NUMUNE', durum, int(g['id']), int(cari['id']), None,
            mid, mid, 'NORMAL', 'F5B', f'IDEM-F5B-{uuid.uuid4().hex}',
            now, now, now,
        ),
    )
    tid = int(cur.lastrowid)
    kids = []
    for i in range(n_kalem):
        curk = c.execute(
            """
            INSERT INTO nexgen_musteri_temsilcisi_talep_kalem (
              talep_id, sira_no, urun_aciklama, renk_aciklama, miktar_kg,
              fiyat_birimi, donusturme_durumu, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                tid, i + 1, f'EVA Taban {i + 1}',
                ['Siyah', 'Lacivert', 'Beyaz'][i % 3],
                500 - i * 100, 'KG', 'BEKLIYOR', now, now,
            ),
        )
        kids.append(int(curk.lastrowid))
    c.commit()
    return tid, kids, mid


def _payload(kid, cari_id):
    return {
        'musteri_tipi': 'MEVCUT',
        'cari_id': cari_id,
        'mtt_kalem_id': kid,
        'urun_tipi': 'TERLIK',
        'urun_adi': f'Urun {kid}',
        'karsilama_yolu': 'YENI_RENK',
        'yeni_renk_aciklama': 'test renk',
        'oncelik': 'NORMAL',
    }


def main():
    print('F5B secimli numune donusum test')
    print(f'DB={DB}')
    mig147.run(DB)
    c = con()
    try:
        cari = c.execute('SELECT id FROM nexgen_cari WHERE COALESCE(aktif,1)=1 LIMIT 1').fetchone()
        cid = int(cari['id'])

        # 1 tek kalem
        print('\n== 1 tek kalem ==')
        tid1, kids1, mid = _seed_numune(c, n_kalem=1)
        h1 = numune_hazirla(c, tid1, mid, {'*'})
        ok('tek secim_gerekli false', h1.get('secim_gerekli') is False)
        r1 = numune_mtt_ile_kaydet(c, tid1, {
            'secilen_kalem_ids': kids1,
            'kalem_payloads': [_payload(kids1[0], cid)],
            'idempotency_key': f'IDEM-T1-{tid1}',
        }, mid, {'*'})
        ok('tek donusum', r1.get('mtt_durum') == 'NUMUNEYE_DONUSTU')
        rowk = c.execute(
            'SELECT donusturme_durumu, donusturulen_numune_talep_id FROM nexgen_musteri_temsilcisi_talep_kalem WHERE id=?',
            (kids1[0],),
        ).fetchone()
        ok('tek kalem pointer', rowk['donusturme_durumu'] == 'NUMUNEYE_DONUSTU' and rowk['donusturulen_numune_talep_id'])

        # 2-3 hazirla varsayilan secim bos
        print('\n== 2-3 secim bos ==')
        tid, kids, mid = _seed_numune(c, n_kalem=3)
        h = numune_hazirla(c, tid, mid, {'*'})
        ok('cok secim_gerekli', h.get('secim_gerekli') is True)
        ok('varsayilan secim bos', all(not x.get('secili_varsayilan') for x in h.get('kalem_secim') or []))
        try:
            numune_mtt_ile_kaydet(c, tid, {'musteri_tipi': 'MEVCUT', 'cari_id': cid}, mid, {'*'})
            ok('secimsiz reddedilir', False)
        except MusteriTemsilcisiTalepError as e:
            ok('secimsiz reddedilir', e.kod in (400, 409))

        # 4-8 kısmi 2/3
        print('\n== 4-8 kismi 2/3 ==')
        sel = [kids[0], kids[2]]
        left = kids[1]
        idem = f'IDEM-P-{tid}'
        r = numune_mtt_ile_kaydet(c, tid, {
            'secilen_kalem_ids': sel,
            'kalem_payloads': [_payload(sel[0], cid), _payload(sel[1], cid)],
            'idempotency_key': idem,
        }, mid, {'*'})
        ok('kismi durum', r.get('mtt_durum') == 'KISMEN_NUMUNEYE_DONUSTU')
        ok('2 numune', len(r.get('numune_talepleri') or []) == 2)
        k0 = c.execute('SELECT donusturme_durumu FROM nexgen_musteri_temsilcisi_talep_kalem WHERE id=?', (sel[0],)).fetchone()
        k1 = c.execute('SELECT donusturme_durumu, donusturulen_numune_talep_id FROM nexgen_musteri_temsilcisi_talep_kalem WHERE id=?', (left,)).fetchone()
        k2 = c.execute('SELECT donusturme_durumu FROM nexgen_musteri_temsilcisi_talep_kalem WHERE id=?', (sel[1],)).fetchone()
        ok('secilenler donustu', k0['donusturme_durumu'] == 'NUMUNEYE_DONUSTU' and k2['donusturme_durumu'] == 'NUMUNEYE_DONUSTU')
        ok('secilmeyen bekliyor', k1['donusturme_durumu'] == 'BEKLIYOR' and not k1['donusturulen_numune_talep_id'])
        hdr = c.execute('SELECT durum, donusturulen_numune_talep_id FROM nexgen_musteri_temsilcisi_talep WHERE id=?', (tid,)).fetchone()
        ok('header kismen', hdr['durum'] == 'KISMEN_NUMUNEYE_DONUSTU' and hdr['donusturulen_numune_talep_id'])

        # 9-10 tekrar açılış
        print('\n== 9-10 tekrar acilis ==')
        h2 = numune_hazirla(c, tid, mid, {'*'})
        ok('tekrar donusum_izin', h2.get('donusum_izin') is True)
        sec = h2.get('kalem_secim') or []
        ok('donusen disabled', all(
            (x['disabled'] and not x['secilebilir']) if x['id'] in sel else x['secilebilir']
            for x in sec
        ))
        ok('numune linki', any(x.get('numune_talep_kodu') for x in sec if x['id'] in sel))

        # 11-12 kalan kalem
        print('\n== 11-12 kalan ==')
        r2 = numune_mtt_ile_kaydet(c, tid, {
            'secilen_kalem_ids': [left],
            'kalem_payloads': [_payload(left, cid)],
            'idempotency_key': f'IDEM-L-{tid}',
        }, mid, {'*'})
        ok('tamamlandi', r2.get('mtt_durum') == 'NUMUNEYE_DONUSTU')
        hdr2 = c.execute('SELECT durum FROM nexgen_musteri_temsilcisi_talep WHERE id=?', (tid,)).fetchone()
        ok('header NUMUNEYE', hdr2['durum'] == 'NUMUNEYE_DONUSTU')

        # 13 tekrar engel
        print('\n== 13-15 idem ==')
        try:
            numune_mtt_ile_kaydet(c, tid, {
                'secilen_kalem_ids': [sel[0]],
                'kalem_payloads': [_payload(sel[0], cid)],
                'idempotency_key': f'IDEM-DUP-{tid}',
            }, mid, {'*'})
            ok('donusmus engel', False)
        except MusteriTemsilcisiTalepError as e:
            ok('donusmus engel 409', e.kod == 409)

        # 14 aynı idem
        tid3, kids3, mid = _seed_numune(c, n_kalem=2)
        idem3 = f'IDEM-SAME-{tid3}'
        body3 = {
            'secilen_kalem_ids': [kids3[0]],
            'kalem_payloads': [_payload(kids3[0], cid)],
            'idempotency_key': idem3,
        }
        a = numune_mtt_ile_kaydet(c, tid3, body3, mid, {'*'})
        b = numune_mtt_ile_kaydet(c, tid3, body3, mid, {'*'})
        ok('idempotent duplicate yok', b.get('idempotent') is True)
        ok('ayni numune', a['numune_talepleri'][0]['id'] == b['numune_talepleri'][0]['id'])
        # 15 farklı set aynı key
        try:
            numune_mtt_ile_kaydet(c, tid3, {
                'secilen_kalem_ids': [kids3[1]],
                'kalem_payloads': [_payload(kids3[1], cid)],
                'idempotency_key': idem3,
            }, mid, {'*'})
            ok('idem conflict', False)
        except MusteriTemsilcisiTalepError as e:
            ok('idem conflict', e.kod == 409)

        # 16 rollback — ikinci kaydet_taslak zorla hata (seçilen grup atomik)
        print('\n== 16-17 rollback ==')
        import modules.nexgen.mtt_donusum_service as mds
        from modules.nexgen.numune_talep_service import NumuneTalepError, kaydet_taslak as _orig_kt
        tid4, kids4, mid = _seed_numune(c, n_kalem=2)
        before = [
            dict(r) for r in c.execute(
                'SELECT id, donusturme_durumu, donusturulen_numune_talep_id '
                'FROM nexgen_musteri_temsilcisi_talep_kalem WHERE talep_id=? ORDER BY id',
                (tid4,),
            ).fetchall()
        ]
        n_nt_before = c.execute('SELECT COUNT(*) AS c FROM nexgen_numune_talep').fetchone()['c']
        calls = {'n': 0}

        def _flaky(con, payload, olusturan_id, talep_id=None, *, commit=True):
            calls['n'] += 1
            if calls['n'] >= 2:
                raise NumuneTalepError('F5B rollback test zorla hata', 400)
            return _orig_kt(con, payload, olusturan_id, talep_id, commit=commit)

        mds.kaydet_taslak = _flaky
        try:
            try:
                numune_mtt_ile_kaydet(c, tid4, {
                    'secilen_kalem_ids': kids4,
                    'kalem_payloads': [_payload(kids4[0], cid), _payload(kids4[1], cid)],
                    'idempotency_key': f'IDEM-RB-{tid4}',
                }, mid, {'*'})
                ok('rollback tetiklendi', False)
            except MusteriTemsilcisiTalepError:
                ok('rollback tetiklendi', True)
        finally:
            mds.kaydet_taslak = _orig_kt
        after = [
            dict(r) for r in c.execute(
                'SELECT id, donusturme_durumu, donusturulen_numune_talep_id '
                'FROM nexgen_musteri_temsilcisi_talep_kalem WHERE talep_id=? ORDER BY id',
                (tid4,),
            ).fetchall()
        ]
        ok('kalemler degismedi', before == after)
        hdr4 = c.execute('SELECT durum FROM nexgen_musteri_temsilcisi_talep WHERE id=?', (tid4,)).fetchone()
        ok('header hâlâ ISLEME', hdr4['durum'] == 'ISLEME_ALINDI')
        n_nt_after = c.execute('SELECT COUNT(*) AS c FROM nexgen_numune_talep').fetchone()['c']
        ok('numune sayisi ayni (rollback)', n_nt_after == n_nt_before)

        # UI strings
        print('\n== UI ==')
        tpl = open(os.path.join(APP, 'templates', 'nexgen', 'pazarlama_merkezi.html'), encoding='utf-8').read()
        ok('UI secim modal', 'mtt-numune-secim-modal' in tpl and 'Seçilenleri Numuneye Dönüştür' in tpl)
        ok('UI varsayilan secim yok', 'secili_varsayilan' in tpl or 'mttNumuneSecimAc' in tpl)

        # migration columns
        cols = {r[1] for r in c.execute('PRAGMA table_info(nexgen_musteri_temsilcisi_talep_kalem)').fetchall()}
        ok('kolon pointer', 'donusturulen_numune_talep_id' in cols and 'donusturme_durumu' in cols)
        sql = c.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='nexgen_musteri_temsilcisi_talep'"
        ).fetchone()[0]
        ok('KISMEN CHECK', 'KISMEN_NUMUNEYE_DONUSTU' in sql)

    except Exception:
        traceback.print_exc()
        global FAIL
        FAIL += 1
    finally:
        c.close()

    print(f'\nSONUC: {PASS} pass / {FAIL} fail')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
