# -*- coding: utf-8 -*-
"""FAZ-BE-3B — Tam formül KG / formül adedi testleri."""
import io
import math
import os
import sqlite3
import sys
from unittest.mock import patch

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

PASS = FAIL = 0


def ok(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  [PASS] {name}' + (f' — {detail}' if detail else ''))
    else:
        FAIL += 1
        print(f'  [FAIL] {name}' + (f' — {detail}' if detail else ''))


def test_pure_formula():
    """İş kuralı: ceil(talep / tam_formul) × tam_formul."""
    print('\n=== SAF FORMÜL TEST ===')
    cases = [
        (1000, 85, 12, 1020, 20),
        (1000, 80, 13, 1040, 40),
        (1000, 82.5, 13, 1072.5, 72.5),
        (1000, 86, 12, 1032, 32),
        (1000, 91, 11, 1001, 1),
    ]
    for talep, tam, exp_adet, exp_uret, exp_fazla in cases:
        adet = int(math.ceil(talep / tam))
        uret = round(adet * tam, 3)
        fazla = round(uret - talep, 3)
        ok(
            f'talep={talep} tam={tam}',
            adet == exp_adet and uret == exp_uret and fazla == exp_fazla,
            f'adet={adet} uret={uret} fazla={fazla}',
        )


def test_batch_uretim_hesapla_mock():
    """_batch_uretim_hesapla mock ana+rf ile."""
    from modules.nexgen.routes import _batch_uretim_hesapla

    con = sqlite3.connect(':memory:')
    print('\n=== MOCK _batch_uretim_hesapla ===')

    def run(talep, ana, boya, exp_adet, exp_uret, exp_fazla):
        tam = round(ana + boya, 3)
        with patch('modules.nexgen.routes._ana_recete_kg_hesapla', return_value=ana), \
             patch('modules.nexgen.routes._rf_boya_kg_birim_hesapla', return_value=boya):
            r = _batch_uretim_hesapla(con, 1, talep, rf_renk_id=28 if boya else None)
        ok(
            f'mock talep={talep} tam={tam}',
            r.get('ok')
            and r['formul_adedi'] == exp_adet
            and r['uretilecek_kg'] == exp_uret
            and r['fazla_kg'] == exp_fazla
            and r['tam_formul_kg'] == tam
            and r['ana_recete_kg'] == ana
            and r['rf_boya_kg'] == boya
            and r['talep_kg'] == talep,
            f"adet={r.get('formul_adedi')} uret={r.get('uretilecek_kg')} fazla={r.get('fazla_kg')}",
        )

    run(1000, 83, 2, 12, 1020, 20)
    run(1000, 80, 0, 13, 1040, 40)
    run(1000, 80, 2.5, 13, 1072.5, 72.5)
    run(1000, 83.5, 2.5, 12, 1032, 32)
    run(1000, 88, 3, 11, 1001, 1)


def test_real_db_terlik():
    """Gerçek DB — TERLİK 18-28 LARGE + RF 28."""
    db = os.path.join(_APP, 'mock_data.db')
    try:
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
    except Exception as e:
        print(f'\n=== GERÇEK DB ATLANDI: {e} ===')
        return

    from modules.nexgen.routes import _batch_uretim_hesapla, _ana_recete_kg_hesapla, _rf_boya_kg_birim_hesapla

    print('\n=== GERÇEK DB (1BA-FL01 uv=10100 rf=28) ===')
    uv_id = 10100
    rf_id = 28
    ana = _ana_recete_kg_hesapla(con, uv_id)
    boya = _rf_boya_kg_birim_hesapla(con, rf_id)
    tam = round(ana + boya, 3)
    r = _batch_uretim_hesapla(con, uv_id, 1000, rf_renk_id=rf_id)
    ok('DB ana+boya=tam', tam > ana and boya > 0, f'ana={ana} boya={boya} tam={tam}')
    if tam > 0:
        exp_adet = int(math.ceil(1000 / tam))
        ok(
            'DB 1000kg hesap',
            r.get('ok') and r['formul_adedi'] == exp_adet,
            f"adet={r.get('formul_adedi')} uret={r.get('uretilecek_kg')} fazla={r.get('fazla_kg')}",
        )
    con.close()


if __name__ == '__main__':
    print('=' * 60)
    print('FAZ-BE-3B TAM FORMÜL KG TEST')
    print('=' * 60)
    test_pure_formula()
    test_batch_uretim_hesapla_mock()
    test_real_db_terlik()
    print('\n' + '=' * 60)
    print(f'SONUC: {PASS} PASS / {FAIL} FAIL')
    print('=' * 60)
    sys.exit(1 if FAIL else 0)
