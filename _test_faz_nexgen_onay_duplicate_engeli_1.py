# -*- coding: utf-8 -*-
"""FAZ-NEXGEN-ONAY-DUPLICATE-ENGELI — local unit/concurrency."""
from __future__ import annotations

import io
import os
import sqlite3
import sys
import threading
import uuid

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'app')
DB = os.path.join(APP, 'mock_data.db')
sys.path.insert(0, APP)

from modules.nexgen.cari_sorumlu_service import load_kullanici_yetkileri  # noqa: E402
from modules.nexgen.musteri_temsilcisi_talep_service import (  # noqa: E402
    kaydet_gorusme_opsiyonel_talep,
)
from modules.nexgen.onay_service import (  # noqa: E402
    OnayError,
    ensure_onay_indexes,
    onay_by_kaynak,
    onay_olustur,
    onay_olustur_mtt,
    onay_onayla,
)

PASS = FAIL = 0
CLEANUP: list[int] = []


def ok(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  PASS  {name}')
    else:
        FAIL += 1
        print(f'  FAIL  {name} {detail}')


def con():
    c = sqlite3.connect(DB, timeout=60)
    c.row_factory = sqlite3.Row
    return c


def base_payload(cari_id):
    return {
        'cari_id': int(cari_id),
        'gorusme_tipi': 'Telefon',
        'sonuc_tipi': 'Fiyat İstedi',
        'kisa_not': f'DUP-ENGEL {uuid.uuid4().hex[:6]}',
        'gorusme_tarihi': '2026-07-30 19:00:00',
        'oncelik': 'NORMAL',
        'kaynak': 'MUSTERI_OPERASYONU',
        'idempotency_key': f'MO-GOR-DUPENG-{uuid.uuid4().hex}',
        'fiyat_verildi': 1,
        'verilen_fiyat': 1.85,
        'fiyat_para_birimi': 'USD',
        'fiyat_birimi': 'KG',
        'konusulan_tonaj': 1.0,
        'odeme_tipi': 'VADELI',
        'vade_gun': 30,
        'talep': {
            'talep_turu': 'SIPARIS',
            'oncelik': 'NORMAL',
            'aciklama': 'dup engel',
            'kalemler': [{
                'urun_aciklama': 'EVA taban',
                'urun_ailesi': 'TABAN',
                'renk_aciklama': 'Siyah',
                'miktar_kg': 100,
                'verilen_fiyat': 1.85,
                'para_birimi': 'USD',
            }],
        },
    }


def cleanup(c):
    for tid in CLEANUP:
        try:
            c.execute(
                'DELETE FROM nexgen_musteri_temsilcisi_talep_kalem WHERE talep_id=?',
                (tid,),
            )
            c.execute(
                "DELETE FROM nexgen_onay WHERE kaynak_turu='MUSTERI_TEMSILCISI_TALEP' AND kaynak_id=?",
                (tid,),
            )
            c.execute(
                'DELETE FROM nexgen_musteri_temsilcisi_talep WHERE id=?',
                (tid,),
            )
        except Exception:
            pass
    c.commit()


def main():
    print('=' * 60)
    print('FAZ-NEXGEN-ONAY-DUPLICATE-ENGELI')
    print('=' * 60)
    c = con()
    try:
        ensure_onay_indexes(c)
        c.commit()
        idx = c.execute(
            "SELECT sql FROM sqlite_master WHERE name='uq_nonay_aktif_kaynak'"
        ).fetchone()
        ok('UNIQUE aktif kaynak index', bool(idx and 'ONAY_BEKLIYOR' in (idx['sql'] or '')))

        admin = c.execute("SELECT Id FROM sistem_kullanici WHERE KullaniciAdi='admin'").fetchone()
        cari = c.execute(
            'SELECT id FROM nexgen_cari WHERE COALESCE(aktif,1)=1 ORDER BY id LIMIT 1'
        ).fetchone()
        aid = int(admin['Id'])
        ayk = load_kullanici_yetkileri(c, aid)

        out = kaydet_gorusme_opsiyonel_talep(c, base_payload(cari['id']), aid, ayk)
        tid = int(out['talep_id'])
        CLEANUP.append(tid)
        onay = onay_by_kaynak(c, 'MUSTERI_TEMSILCISI_TALEP', tid)
        o1 = c.execute('SELECT COUNT(*) n FROM nexgen_onay').fetchone()['n']

        # Test isimleri (yonetim suite ile aynı):
        # 1) duplicate engeli
        # 2) duplicate yeni satir yok
        dup = onay_olustur_mtt(c, tid, aid, f'DUP-{uuid.uuid4().hex}', commit=True)
        ok(
            'duplicate engeli',
            dup.get('idempotent') is True and int(dup['kayit']['id']) == int(onay['id']),
            f"idem={dup.get('idempotent')} id={dup.get('kayit',{}).get('id')} vs {onay['id']}",
        )
        o_after = c.execute('SELECT COUNT(*) n FROM nexgen_onay').fetchone()['n']
        ok('duplicate yeni satir yok', o_after == o1, f'{o_after} vs {o1}')

        # Farklı onay_turu (explicit OLUSTURMA) → 409
        try:
            onay_olustur(
                c,
                kaynak_turu='MUSTERI_TEMSILCISI_TALEP',
                kaynak_id=tid,
                onay_turu='OLUSTURMA',
                olusturan_kullanici_id=aid,
                idempotency_key=f'ONY-DIFF-{uuid.uuid4().hex}',
                commit=True,
            )
            ok('farkli payload 409', False)
        except OnayError as e:
            ok('farkli payload 409', e.kod == 409, str(e.kod))

        # Aynı idem → idempotent
        key = f'SAME-{uuid.uuid4().hex}'
        # yeni MTT
        out2 = kaydet_gorusme_opsiyonel_talep(c, base_payload(cari['id']), aid, ayk)
        tid2 = int(out2['talep_id'])
        CLEANUP.append(tid2)
        # force: use onay_olustur twice same key — first already created with different key
        # retry same MTT idem from create path
        idem_mtt = out2.get('kayit', {}).get('idempotency_key') or f'RETRY-{uuid.uuid4().hex}'
        # Actually MTT create already made onay — retry with same ONY- key
        onay2 = onay_by_kaynak(c, 'MUSTERI_TEMSILCISI_TALEP', tid2)
        same = onay_olustur(
            c,
            kaynak_turu='MUSTERI_TEMSILCISI_TALEP',
            kaynak_id=tid2,
            onay_turu=onay2['onay_turu'],
            olusturan_kullanici_id=aid,
            idempotency_key=onay2['idempotency_key'],
            commit=True,
        )
        ok('ayni payload idempotent', same.get('idempotent') is True)

        # Concurrency: iki thread aynı kaynak, farklı idem
        out3 = kaydet_gorusme_opsiyonel_talep(c, base_payload(cari['id']), aid, ayk)
        tid3 = int(out3['talep_id'])
        CLEANUP.append(tid3)
        # sil onay to race create? better: use fresh kaynak without onay — hard via MTT path
        # Instead: delete onay for tid3 then concurrent recreate
        c.execute(
            "DELETE FROM nexgen_onay WHERE kaynak_turu='MUSTERI_TEMSILCISI_TALEP' AND kaynak_id=?",
            (tid3,),
        )
        c.commit()
        before = c.execute('SELECT COUNT(*) n FROM nexgen_onay').fetchone()['n']
        results = []
        lock = threading.Lock()

        def worker(i):
            cc = sqlite3.connect(DB, timeout=60)
            cc.row_factory = sqlite3.Row
            try:
                r = onay_olustur(
                    cc,
                    kaynak_turu='MUSTERI_TEMSILCISI_TALEP',
                    kaynak_id=tid3,
                    onay_turu='SIPARIS_TALEBI_ONAY',
                    olusturan_kullanici_id=aid,
                    idempotency_key=f'ONY-RACE-{i}-{uuid.uuid4().hex}',
                    commit=True,
                )
                with lock:
                    results.append(('ok', r))
            except Exception as e:
                with lock:
                    results.append(('err', e))
            finally:
                cc.close()

        t_a = threading.Thread(target=worker, args=(1,))
        t_b = threading.Thread(target=worker, args=(2,))
        t_a.start()
        t_b.start()
        t_a.join()
        t_b.join()
        after = c.execute('SELECT COUNT(*) n FROM nexgen_onay').fetchone()['n']
        n_aktif = c.execute(
            """
            SELECT COUNT(*) n FROM nexgen_onay
            WHERE kaynak_turu='MUSTERI_TEMSILCISI_TALEP' AND kaynak_id=? AND durum='ONAY_BEKLIYOR'
            """,
            (tid3,),
        ).fetchone()['n']
        nos = c.execute(
            """
            SELECT DISTINCT onay_no FROM nexgen_onay
            WHERE kaynak_turu='MUSTERI_TEMSILCISI_TALEP' AND kaynak_id=?
            """,
            (tid3,),
        ).fetchall()
        ok('concurrency tek aktif', n_aktif == 1, f'aktif={n_aktif} results={results}')
        ok('concurrency tek onay_no', len(nos) == 1, str([x['onay_no'] for x in nos]))
        ok('concurrency sayac +1', after == before + 1, f'{before}->{after}')

        # Çift onayla
        r1 = onay_onayla(c, int(onay['id']), aid, ayk)
        r2 = onay_onayla(c, int(onay['id']), aid, ayk)
        ok('cift onayla ilk', r1['kayit']['durum'] == 'ONAYLANDI' and r1.get('idempotent') is False)
        ok('cift onayla ikinci idem', r2.get('idempotent') is True and r2['kayit']['durum'] == 'ONAYLANDI')

    finally:
        cleanup(c)
        c.close()

    print('-' * 60)
    print(f'SONUC: {PASS} PASS / {FAIL} FAIL')
    return 0 if FAIL == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
