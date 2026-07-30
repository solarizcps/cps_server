# -*- coding: utf-8 -*-
"""FAZ-NEXGEN-URETIM-KAPANIS-ZINCIRI-FIX-1 — local davranış testleri A–I."""
from __future__ import annotations

import io
import os
import sqlite3
import sys

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

from modules.nexgen import routes as R  # noqa: E402

results = []


def ok(name, cond, detail=''):
    results.append((name, bool(cond), detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def _mem():
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE nexgen_planlama_siparis (
            id INTEGER PRIMARY KEY,
            siparis_no TEXT,
            durum TEXT,
            guncelleme_tarihi TEXT
        );
        CREATE TABLE nexgen_uretim_plan (
            id INTEGER PRIMARY KEY,
            plan_kodu TEXT,
            durum TEXT,
            planlama_siparis_id INTEGER,
            planlanan_kg REAL
        );
        CREATE TABLE nexgen_uretim_batch (
            id INTEGER PRIMARY KEY,
            batch_kodu TEXT UNIQUE,
            durum TEXT,
            plan_id INTEGER,
            planlanan_kg REAL,
            uretim_varyant_id INTEGER,
            notlar TEXT
        );
        CREATE TABLE nexgen_uretim_parca (
            id INTEGER PRIMARY KEY,
            batch_kodu TEXT,
            plan_id INTEGER,
            parca_no INTEGER,
            hedef_kg REAL,
            uretilen_kg REAL,
            formul_batch_kg REAL,
            durum TEXT,
            baslama_zamani TEXT,
            bitis_zamani TEXT,
            updated_at TEXT,
            notlar TEXT
        );
        CREATE TABLE nexgen_rf_kullanim (
            id INTEGER PRIMARY KEY,
            rf_renk_id INTEGER,
            formul_id INTEGER,
            cari_id INTEGER,
            siparis_id INTEGER,
            aciklama TEXT,
            olusturan_id INTEGER,
            aktif INTEGER DEFAULT 1,
            durum TEXT,
            miktar_kg REAL,
            tablet_session_id TEXT,
            uretim_emir_id INTEGER,
            guncelleme_tarihi TEXT,
            olusturma_tarihi TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    return con


def _seed_chain(con, *, sip_id=1, plan_id=10, batch_kodu='B-A',
                sip_durum='URETIMDE', plan_durum='URETIMDE', batch_durum='DEVAM',
                parcalar=None):
    """parcalar: list of (id, durum, hedef_kg)."""
    con.execute(
        "INSERT INTO nexgen_planlama_siparis(id,siparis_no,durum) VALUES (?,?,?)",
        (sip_id, f'PZM-TEST-{sip_id}', sip_durum),
    )
    con.execute(
        "INSERT INTO nexgen_uretim_plan(id,plan_kodu,durum,planlama_siparis_id,planlanan_kg) "
        "VALUES (?,?,?,?,?)",
        (plan_id, f'NP-{plan_id}', plan_durum, sip_id, 100.0),
    )
    con.execute(
        "INSERT INTO nexgen_uretim_batch(id,batch_kodu,durum,plan_id,planlanan_kg,uretim_varyant_id) "
        "VALUES (?,?,?,?,?,?)",
        (plan_id, batch_kodu, batch_durum, plan_id, 100.0, 1),
    )
    for i, (pid, durum, kg) in enumerate(parcalar or [], start=1):
        con.execute(
            "INSERT INTO nexgen_uretim_parca"
            "(id,batch_kodu,plan_id,parca_no,hedef_kg,uretilen_kg,formul_batch_kg,durum) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (pid, batch_kodu, plan_id, 1000 + i, kg, 0 if durum != 'BITTI' else kg, kg, durum),
        )
    con.commit()


def _stub_side_effects(monkey=True):
    """Stok/rezerv/depo/RF yan etkilerini no-op; kapanış zinciri saf test."""
    orig = {}

    def _ok(*a, **k):
        return {'ok': True, 'atlandi': True, 'hareket_sayisi': 0, 'guncellenen': 0}

    def _rf(con, batch_kodu, uretim_emir_id=None, tamamlandi=False):
        durum = 'TAMAMLANDI' if tamamlandi else 'URETIM'
        # miktar = BITTI parça toplamı (mevcut davranışa benzer)
        row = con.execute(
            "SELECT COALESCE(SUM(uretilen_kg),0) AS kg FROM nexgen_uretim_parca "
            "WHERE batch_kodu=? AND durum='BITTI'",
            (batch_kodu,),
        ).fetchone()
        kg = float(row['kg'] or 0)
        mevcut = con.execute(
            "SELECT id, miktar_kg FROM nexgen_rf_kullanim "
            "WHERE tablet_session_id=? AND aktif=1 ORDER BY id DESC LIMIT 1",
            (batch_kodu,),
        ).fetchone()
        if mevcut:
            con.execute(
                "UPDATE nexgen_rf_kullanim SET durum=?, miktar_kg=? WHERE id=?",
                (durum, kg, mevcut['id']),
            )
            return mevcut['id']
        plan = con.execute(
            "SELECT plan_id FROM nexgen_uretim_batch WHERE batch_kodu=?",
            (batch_kodu,),
        ).fetchone()
        con.execute(
            "INSERT INTO nexgen_rf_kullanim"
            "(rf_renk_id,siparis_id,aktif,durum,miktar_kg,tablet_session_id,aciklama) "
            "VALUES (1,?,?,?,?,?,'Tablet uretim')",
            (plan['plan_id'] if plan else None, 1, durum, kg, batch_kodu),
        )
        return con.execute('SELECT last_insert_rowid()').fetchone()[0]

    orig['stok'] = R._parca_stok_tuket
    orig['rezerv'] = R._rezerv_tuket
    orig['depo'] = R._batch_depo_hazir_zorunlu
    orig['rf'] = R._rf_kullanim_tablet_sync
    orig['parca_tablo'] = R._parca_tablosu_var
    orig['plan_ps'] = R._plan_planlama_siparis_kolonu_var
    orig['ps_tablo'] = R._planlama_siparis_tablosu_var

    R._parca_stok_tuket = lambda *a, **k: _ok()
    R._rezerv_tuket = lambda *a, **k: _ok()
    R._batch_depo_hazir_zorunlu = lambda *a, **k: _ok()
    R._rf_kullanim_tablet_sync = _rf
    R._parca_tablosu_var = lambda con: True
    R._plan_planlama_siparis_kolonu_var = lambda con: True
    R._planlama_siparis_tablosu_var = lambda con: True
    return orig


def _restore(orig):
    R._parca_stok_tuket = orig['stok']
    R._rezerv_tuket = orig['rezerv']
    R._batch_depo_hazir_zorunlu = orig['depo']
    R._rf_kullanim_tablet_sync = orig['rf']
    R._parca_tablosu_var = orig['parca_tablo']
    R._plan_planlama_siparis_kolonu_var = orig['plan_ps']
    R._planlama_siparis_tablosu_var = orig['ps_tablo']


def _durum(con, sql, *a):
    r = con.execute(sql, a).fetchone()
    return r[0] if r else None


print('=' * 72)
print('FAZ-NEXGEN-URETIM-KAPANIS-ZINCIRI-FIX-1')
print('=' * 72)

# --- Static presence ---
src = open(os.path.join(_APP, 'modules', 'nexgen', 'routes.py'), encoding='utf-8').read()
ok('S01 helper var', 'def _batch_auto_kapat_if_ready' in src)
ok('S02 multi-batch plan kontrol', 'acik_veya_eksik_batch' in src)
ok('S03 api_parca_bitir bağ',
   '_batch_auto_kapat_if_ready(con, batch_kodu)' in src.split('def api_parca_bitir')[1][:2500])
ok('S04 toplu bitir bağ',
   '_batch_auto_kapat_if_ready(con, batch_kodu)' in src.split('def api_parca_toplu_bitir')[1][:2000])
ok('S05 secili tekilleştir',
   '_batch_auto_kapat_etkilenenler' in src.split('def api_parca_secili_isle')[1][:4500])

orig = _stub_side_effects()
try:
    # A — tek batch son parça
    con = _mem()
    _seed_chain(con, parcalar=[(1, 'DEVAM', 50.0), (2, 'DEVAM', 50.0)])
    r1 = R._parca_bitir_uygula(con, 1, 50.0)
    R._rf_kullanim_tablet_sync(con, 'B-A', uretim_emir_id=1)
    k1 = R._batch_auto_kapat_if_ready(con, 'B-A')
    ok('A1 ilk parça batch açık',
       _durum(con, "SELECT durum FROM nexgen_uretim_batch WHERE batch_kodu='B-A'") == 'DEVAM'
       and not k1.get('kapandi'), str(k1.get('neden')))
    r2 = R._parca_bitir_uygula(con, 2, 50.0)
    R._rf_kullanim_tablet_sync(con, 'B-A', uretim_emir_id=2)
    k2 = R._batch_auto_kapat_if_ready(con, 'B-A')
    ok('A2 son parça batch BITTI',
       _durum(con, "SELECT durum FROM nexgen_uretim_batch WHERE batch_kodu='B-A'") == 'BITTI'
       and k2.get('kapandi'), str(k2))
    ok('A3 plan BITTI',
       _durum(con, 'SELECT durum FROM nexgen_uretim_plan WHERE id=10') == 'BITTI')
    ok('A4 sipariş TAMAMLANDI',
       _durum(con, 'SELECT durum FROM nexgen_planlama_siparis WHERE id=1') == 'TAMAMLANDI')
    rf = con.execute(
        "SELECT durum, miktar_kg FROM nexgen_rf_kullanim WHERE tablet_session_id='B-A' AND aktif=1"
    ).fetchone()
    ok('A5 RF TAMAMLANDI miktar=100',
       rf and rf['durum'] == 'TAMAMLANDI' and abs(float(rf['miktar_kg']) - 100.0) < 0.001,
       dict(rf) if rf else None)
    con.close()

    # B — açık parça
    con = _mem()
    _seed_chain(con, parcalar=[(1, 'BITTI', 50.0), (2, 'HAZIR', 50.0)])
    con.execute("UPDATE nexgen_uretim_parca SET uretilen_kg=50 WHERE id=1")
    k = R._batch_auto_kapat_if_ready(con, 'B-A')
    ok('B açık parça batch kapanmaz',
       not k.get('kapandi')
       and _durum(con, "SELECT durum FROM nexgen_uretim_batch WHERE batch_kodu='B-A'") == 'DEVAM',
       k.get('neden'))
    con.close()

    # C — IPTAL parça
    con = _mem()
    _seed_chain(con, parcalar=[(1, 'BITTI', 50.0), (2, 'IPTAL', 50.0)])
    con.execute("UPDATE nexgen_uretim_parca SET uretilen_kg=50 WHERE id=1")
    k = R._batch_auto_kapat_if_ready(con, 'B-A')
    ok('C IPTAL engellemez batch BITTI',
       k.get('kapandi')
       and _durum(con, "SELECT durum FROM nexgen_uretim_batch WHERE batch_kodu='B-A'") == 'BITTI',
       str(k))
    con.close()

    # D — çok batch, biri açık
    con = _mem()
    _seed_chain(con, batch_kodu='B-A', parcalar=[(1, 'BITTI', 40.0), (2, 'BITTI', 40.0)])
    con.execute("UPDATE nexgen_uretim_parca SET uretilen_kg=hedef_kg WHERE batch_kodu='B-A'")
    con.execute(
        "INSERT INTO nexgen_uretim_batch(id,batch_kodu,durum,plan_id,planlanan_kg,uretim_varyant_id) "
        "VALUES (11,'B-B','DEVAM',10,80.0,1)"
    )
    con.execute(
        "INSERT INTO nexgen_uretim_parca"
        "(id,batch_kodu,plan_id,parca_no,hedef_kg,uretilen_kg,formul_batch_kg,durum) "
        "VALUES (3,'B-B',10,1001,40,0,40,'DEVAM')"
    )
    k = R._batch_auto_kapat_if_ready(con, 'B-A')
    ok('D1 batch A BITTI', k.get('kapandi'))
    ok('D2 plan açık kalır',
       _durum(con, 'SELECT durum FROM nexgen_uretim_plan WHERE id=10') == 'URETIMDE',
       _durum(con, 'SELECT durum FROM nexgen_uretim_plan WHERE id=10'))
    ok('D3 sipariş açık',
       _durum(con, 'SELECT durum FROM nexgen_planlama_siparis WHERE id=1') == 'URETIMDE')
    con.close()

    # E — çok batch tamamı kapalı
    con = _mem()
    _seed_chain(con, batch_kodu='B-A', parcalar=[(1, 'BITTI', 40.0)])
    con.execute("UPDATE nexgen_uretim_parca SET uretilen_kg=40 WHERE id=1")
    con.execute(
        "INSERT INTO nexgen_uretim_batch(id,batch_kodu,durum,plan_id,planlanan_kg,uretim_varyant_id) "
        "VALUES (11,'B-B','DEVAM',10,40.0,1)"
    )
    con.execute(
        "INSERT INTO nexgen_uretim_parca"
        "(id,batch_kodu,plan_id,parca_no,hedef_kg,uretilen_kg,formul_batch_kg,durum) "
        "VALUES (2,'B-B',10,1001,40,0,40,'DEVAM')"
    )
    R._batch_auto_kapat_if_ready(con, 'B-A')  # A kapanır, plan açık
    R._parca_bitir_uygula(con, 2, 40.0)
    R._rf_kullanim_tablet_sync(con, 'B-B', uretim_emir_id=2)
    k = R._batch_auto_kapat_if_ready(con, 'B-B')
    ok('E1 batch B BITTI', k.get('kapandi'))
    ok('E2 plan BITTI',
       _durum(con, 'SELECT durum FROM nexgen_uretim_plan WHERE id=10') == 'BITTI')
    ok('E3 sipariş TAMAMLANDI',
       _durum(con, 'SELECT durum FROM nexgen_planlama_siparis WHERE id=1') == 'TAMAMLANDI')
    con.close()

    # F — idempotency
    con = _mem()
    _seed_chain(con, parcalar=[(1, 'BITTI', 50.0), (2, 'BITTI', 50.0)])
    con.execute("UPDATE nexgen_uretim_parca SET uretilen_kg=hedef_kg")
    con.execute(
        "INSERT INTO nexgen_rf_kullanim(rf_renk_id,siparis_id,aktif,durum,miktar_kg,tablet_session_id) "
        "VALUES (1,10,1,'URETIM',100,'B-A')"
    )
    k1 = R._batch_auto_kapat_if_ready(con, 'B-A')
    rf1 = con.execute(
        "SELECT COUNT(*) c, MAX(miktar_kg) kg, MAX(durum) d FROM nexgen_rf_kullanim "
        "WHERE tablet_session_id='B-A' AND aktif=1"
    ).fetchone()
    k2 = R._batch_auto_kapat_if_ready(con, 'B-A')
    rf2 = con.execute(
        "SELECT COUNT(*) c, MAX(miktar_kg) kg, MAX(durum) d FROM nexgen_rf_kullanim "
        "WHERE tablet_session_id='B-A' AND aktif=1"
    ).fetchone()
    ok('F1 ikinci çağrı hata yok', k2.get('ok') and k2.get('atlandi'))
    ok('F2 RF tek kayıt', rf1['c'] == 1 and rf2['c'] == 1)
    ok('F3 RF miktar değişmez', abs(float(rf1['kg']) - float(rf2['kg'])) < 0.001)
    ok('F4 durum geri düşmez',
       _durum(con, "SELECT durum FROM nexgen_uretim_batch WHERE batch_kodu='B-A'") == 'BITTI'
       and _durum(con, 'SELECT durum FROM nexgen_planlama_siparis WHERE id=1') == 'TAMAMLANDI')
    con.close()

    # G — toplu simülasyon (uyugula döngü + tek kapat)
    con = _mem()
    _seed_chain(con, parcalar=[(1, 'DEVAM', 25.0), (2, 'DEVAM', 25.0), (3, 'DEVAM', 25.0)])
    for pid in (1, 2, 3):
        R._parca_bitir_uygula(con, pid, 25.0)
    R._rf_kullanim_tablet_sync(con, 'B-A', uretim_emir_id=3)
    sonuclar = R._batch_auto_kapat_etkilenenler(con, ['B-A', 'B-A', 'B-A'])
    ok('G1 tekilleştir 1 sonuç', len(sonuclar) == 1)
    ok('G2 toplu sonrası BITTI/TAMAMLANDI',
       _durum(con, "SELECT durum FROM nexgen_uretim_batch WHERE batch_kodu='B-A'") == 'BITTI'
       and _durum(con, 'SELECT durum FROM nexgen_planlama_siparis WHERE id=1') == 'TAMAMLANDI')
    con.close()

    # H — seçili bitir simülasyonu (aynı zincir)
    con = _mem()
    _seed_chain(con, parcalar=[(1, 'DEVAM', 50.0), (2, 'DEVAM', 50.0)])
    etkilenen = []
    for pid in (1, 2):
        b = R._parca_bitir_uygula(con, pid, 50.0)
        etkilenen.append(b['batch_kodu'])
    R._rf_kullanim_tablet_sync(con, 'B-A', uretim_emir_id=2)
    R._batch_auto_kapat_etkilenenler(con, etkilenen)
    ok('H seçili bitir TAMAMLANDI',
       _durum(con, 'SELECT durum FROM nexgen_planlama_siparis WHERE id=1') == 'TAMAMLANDI')
    con.close()

    # I — RF miktar / sevk hesabı yan etkisi yok (kapanış miktarı korur)
    con = _mem()
    _seed_chain(con, parcalar=[(1, 'BITTI', 5030.2)])
    con.execute("UPDATE nexgen_uretim_parca SET uretilen_kg=5030.2 WHERE id=1")
    con.execute(
        "INSERT INTO nexgen_rf_kullanim(rf_renk_id,siparis_id,aktif,durum,miktar_kg,tablet_session_id) "
        "VALUES (1,10,1,'URETIM',5030.2,'B-A')"
    )
    before = 5030.2
    R._batch_auto_kapat_if_ready(con, 'B-A')
    after = con.execute(
        "SELECT miktar_kg, durum FROM nexgen_rf_kullanim WHERE tablet_session_id='B-A'"
    ).fetchone()
    ok('I RF miktar değişmez', abs(float(after['miktar_kg']) - before) < 0.001, dict(after))
    ok('I RF durum TAMAMLANDI (manuel batch BITTI ile aynı)', after['durum'] == 'TAMAMLANDI')
    con.close()

finally:
    _restore(orig)

# Regression: mevcut faz4 string testleri hâlâ geçerli olmalı
ok('R01 batch bitir kontrol metni', 'acik > 0' in src.split('def _tua_batch_bitir_kontrol')[1][:900])
ok('R02 siparis sync acik plan', "NOT IN ('BITTI','IPTAL')" in src.split('def _pzm_siparis_tamamlandi_sync')[1][:1200])

passed = sum(1 for _, c, _ in results if c)
print('=' * 72)
print(f'SONUC: {passed}/{len(results)} PASS')
if passed < len(results):
    for n, c, d in results:
        if not c:
            print('FAIL', n, d)
    sys.exit(1)
print('KARAR_ADAYI: A')
