# -*- coding: utf-8 -*-
"""FAZ-MTT-F5 — dönüşüm köprüsü local test (commit/push yok)."""
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

mig = importlib.import_module('migrations.146_nexgen_musteri_temsilcisi_talep')
from modules.nexgen.musteri_temsilcisi_talep_service import (  # noqa: E402
    MusteriTemsilcisiTalepError,
    talep_listele,
)
from modules.nexgen.mtt_donusum_service import (  # noqa: E402
    MSG_ADAY_SIPARIS,
    assert_donusum_izin,
    numune_hazirla,
    numune_mtt_ile_kaydet,
    siparis_hazirla,
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


def _seed(c, *, tur='SIPARIS', durum='ISLEME_ALINDI', cari=None, aday=None, atanan=None, n_kalem=1):
    now = '2026-07-30 12:00:00'
    if cari is None and aday is None:
        row = c.execute(
            'SELECT id FROM nexgen_cari WHERE COALESCE(aktif,1)=1 ORDER BY id LIMIT 1'
        ).fetchone()
        cari = int(row['id']) if row else None
    if cari is None and aday is None:
        raise RuntimeError('cari/aday yok')
    g = c.execute(
        """
        SELECT id FROM musteri_operasyon_gorusme
        WHERE COALESCE(aktif,1)=1
          AND ((? IS NOT NULL AND cari_id=?) OR (? IS NOT NULL AND musteri_aday_id=?))
        ORDER BY id DESC LIMIT 1
        """,
        (cari, cari, aday, aday),
    ).fetchone()
    if not g:
        uid = c.execute('SELECT Id FROM sistem_kullanici ORDER BY Id LIMIT 1').fetchone()
        uid = int(uid['Id']) if uid else 1
        cur = c.execute(
            """
            INSERT INTO musteri_operasyon_gorusme (
              cari_id, musteri_aday_id, kullanici_id, kisa_not, gorusme_tarihi,
              verilen_fiyat, fiyat_para_birimi, konusulan_tonaj, odeme_tipi, vade_gun, aktif
            ) VALUES (?,?,?,?,?,?,?,?,?,?,1)
            """,
            (
                cari, aday, uid, 'F5 test gorusme', now,
                12.5, 'USD', 2.0, 'VADE', 30,
            ),
        )
        gid = int(cur.lastrowid)
    else:
        gid = int(g['id'])
    if atanan is None:
        u = c.execute('SELECT Id FROM sistem_kullanici ORDER BY Id LIMIT 1').fetchone()
        atanan = int(u['Id']) if u else 1
    olusturan = atanan
    tno = f'MTT-F5-{uuid.uuid4().hex[:8].upper()}'
    cur = c.execute(
        """
        INSERT INTO nexgen_musteri_temsilcisi_talep (
          talep_no, talep_turu, durum, gorusme_id, cari_id, musteri_aday_id,
          olusturan_kullanici_id, atanan_kullanici_id, oncelik, aciklama,
          idempotency_key, isleme_alinma_tarihi, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            tno, tur, durum, gid, cari, aday, olusturan,
            atanan if durum == 'ISLEME_ALINDI' else None,
            'NORMAL', 'F5 test', f'IDEM-F5-{uuid.uuid4().hex}',
            now if durum == 'ISLEME_ALINDI' else None, now, now,
        ),
    )
    tid = int(cur.lastrowid)
    for i in range(n_kalem):
        c.execute(
            """
            INSERT INTO nexgen_musteri_temsilcisi_talep_kalem (
              talep_id, sira_no, urun_aciklama, renk_aciklama, miktar_kg,
              konusulan_tonaj, verilen_fiyat, para_birimi, fiyat_birimi, kalem_notu,
              created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                tid, i + 1, 'Eva Terlik Tabanı' if i == 0 else f'Kalem {i + 1}',
                'Siyah', 500, 2.0, 12.5, 'USD', 'KG', 'not', now, now,
            ),
        )
    c.commit()
    return tid


def main():
    print('F5 MTT donusum koprusu test')
    print(f'DB={DB}')
    c = con()
    try:
        mig._ensure_talep(c)
        mig._ensure_kalem(c)
        c.commit()

        print('\n== siparis hazirla ==')
        tid = _seed(c, tur='SIPARIS', durum='ISLEME_ALINDI')
        h = siparis_hazirla(c, tid, 1, {'*'})
        ok('siparis-hazirla ok', bool(h.get('ok') and h.get('donusum_izin')))
        ok('hydrate cari', bool(h.get('hydrate', {}).get('cari_id')))
        ok('hydrate kalem>=1', len(h.get('hydrate', {}).get('kalemler') or []) >= 1)
        ok('eksik alan listesi', isinstance(h.get('eksik_zorunlu_alanlar'), list))

        print('\n== aday siparis engel ==')
        aday = c.execute(
            'SELECT id FROM nexgen_musteri_aday ORDER BY id LIMIT 1'
        ).fetchone()
        if aday:
            tid_a = _seed(c, tur='SIPARIS', durum='ISLEME_ALINDI', cari=None, aday=int(aday['id']))
            ha = siparis_hazirla(c, tid_a, 1, {'*'})
            ok('aday_siparis_engel', ha.get('aday_siparis_engel') is True)
            ok('aday izin false', ha.get('donusum_izin') is False)
            try:
                assert_donusum_izin(
                    {
                        'durum': 'ISLEME_ALINDI', 'talep_turu': 'SIPARIS',
                        'musteri_aday_id': int(aday['id']), 'cari_id': None,
                        'atanan_kullanici_id': 1,
                        'donusturulen_siparis_id': None,
                        'donusturulen_numune_talep_id': None,
                    },
                    1, 'SIPARIS', {'*'},
                )
                ok('aday 409', False)
            except MusteriTemsilcisiTalepError as e:
                ok('aday 409', e.kod == 409 and MSG_ADAY_SIPARIS[:20] in e.mesaj)
        else:
            ok('aday tablo yok — skip', True)

        print('\n== YENI engel ==')
        tid_y = _seed(c, tur='SIPARIS', durum='YENI')
        hy = siparis_hazirla(c, tid_y, 1, {'*'})
        ok('YENI izin false', hy.get('donusum_izin') is False)

        print('\n== numune aday ==')
        if aday:
            tid_n = _seed(c, tur='NUMUNE', durum='ISLEME_ALINDI', cari=None, aday=int(aday['id']))
            hn = numune_hazirla(c, tid_n, 1, {'*'})
            ok('numune hazirla', bool(hn.get('ok') and hn.get('donusum_izin')))
            ok('hydrate ADAY', hn.get('hydrate', {}).get('musteri_tipi') == 'ADAY')
            ok('aday_desteklenir', hn.get('cari_veya_aday', {}).get('aday_desteklenir') is True)
        else:
            ok('numune aday skip', True)

        print('\n== liste istenen urun / bekleme ==')
        tid_l = _seed(c, tur='SIPARIS', durum='ISLEME_ALINDI', n_kalem=3)
        rows = talep_listele(c, durum='ISLEME_ALINDI', limit=200)
        row = next((r for r in rows if r['id'] == tid_l), None)
        ok('liste row', row is not None)
        ok('istenen +2 kalem', row is not None and '+2 kalem' in (row.get('istenen_urun') or ''))
        ok('bekleme', row is not None and bool(row.get('bekleme')))

        print('\n== cok kalem numune secim zorunlu (F5B) ==')
        tid_ck = _seed(c, tur='NUMUNE', durum='ISLEME_ALINDI', n_kalem=2)
        hck = numune_hazirla(c, tid_ck, 1, {'*'})
        ok('cok_kalem / secim_gerekli', hck.get('cok_kalem') is True and hck.get('secim_gerekli') is True)
        try:
            numune_mtt_ile_kaydet(
                c, tid_ck,
                {'musteri_tipi': 'MEVCUT', 'cari_id': hck['hydrate'].get('cari_id') or 1},
                1, {'*'},
            )
            ok('secimsiz reddedilir', False)
        except MusteriTemsilcisiTalepError as e:
            ok('secimsiz reddedilir', e.kod in (400, 409))

        print('\n== commit=False imza ==')
        import inspect
        from modules.nexgen.pzm_siparis_write import pzm_v2_taslak_kaydet
        from modules.nexgen.numune_talep_service import kaydet_taslak
        ok('pzm commit param', 'commit' in inspect.signature(pzm_v2_taslak_kaydet).parameters)
        ok('numune commit param', 'commit' in inspect.signature(kaydet_taslak).parameters)

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
