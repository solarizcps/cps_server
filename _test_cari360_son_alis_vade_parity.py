# -*- coding: utf-8 -*-
"""
CARI360-SON-ALIS-FIYATI-VADE-PARITY-01 REGRESSION
READ-ONLY — DB'ye yazma yok.

Canonical contract:
Son Alış Fiyatı kartının son_gosterilecek_vade_gun değeri
enrich_siparis_listesi_ticari ile aynı resolver'ı kullanmalı.

CASE A — CEK, cek_vade_gun DB kolonu
CASE B — CEK, JSON fallback (cek_vade_gun kolon yok)
CASE C — VADELI
CASE D — NAKIT
CASE E — BELIRTILMEMIS / veri yok
CASE F — fiyat seçilen sipariş ile vade siparişi aynı (identity)
CASE G — legacy header fiyatlı sipariş + vade aynı kaynaktan
"""
import json
import os
import sqlite3
import sys
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app'))

from modules.nexgen.cari360_ticari_ozet_service import load_cari360_ticari_ozet

_PASS = []
_FAIL = []


def _chk(label, cond, got=None, exp=None):
    if cond:
        _PASS.append(label)
        print(f'PASS  {label}')
    else:
        _FAIL.append(label)
        print(f'FAIL  {label}  got={got!r}  exp={exp!r}')


def _make_db():
    """In-memory SQLite fixture: nexgen_cari + nexgen_planlama_siparis + kalem."""
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.execute("""
        CREATE TABLE nexgen_cari (
            id INTEGER PRIMARY KEY,
            cari_adi TEXT,
            cari_kodu TEXT,
            aktif INTEGER DEFAULT 1
        )
    """)
    con.execute("""
        CREATE TABLE nexgen_planlama_siparis (
            id INTEGER PRIMARY KEY,
            cari_id INTEGER,
            siparis_no TEXT,
            durum TEXT,
            olusturma_tarihi TEXT,
            talep_referansi TEXT,
            anlasma_para_birimi TEXT,
            anlasma_birim_fiyat REAL,
            odeme_tipi TEXT,
            vade_gun INTEGER,
            cek_vade_gun INTEGER,
            kur REAL,
            kur_tarihi TEXT,
            kur_kaynagi TEXT
        )
    """)
    con.execute("""
        CREATE TABLE nexgen_planlama_siparis_kalem (
            id INTEGER PRIMARY KEY,
            planlama_siparis_id INTEGER,
            formul_id INTEGER,
            formul_ad TEXT,
            renk_varyant_id INTEGER,
            renk_ad TEXT,
            rf_renk_id INTEGER,
            urun_ailesi TEXT,
            miktar_l REAL,
            miktar_s REAL,
            miktar_m REAL,
            birim_fiyat REAL,
            iskonto_orani REAL,
            iskonto_tutari REAL,
            net_birim_fiyat REAL,
            satir_tutari REAL,
            net_birim_fiyat_try REAL,
            satir_tutari_try REAL
        )
    """)
    return con


def _stub_auth(cari_id):
    """Yetki kontrol bypass stubları."""
    return (
        mock.patch('modules.nexgen.cari360_ticari_ozet_service._assert_cari',
                   return_value={'id': cari_id, 'cari_adi': 'TEST', 'cari_kodu': 'T00'}),
        mock.patch('modules.nexgen.cari360_ticari_ozet_service.can_view_cari_ticari',
                   return_value=True),
    )


def _add_siparis(con, sid, cari_id=1, siparis_no='PZM-TEST', durum='ONAYLANDI',
                 odeme_tipi=None, vade_gun=None, cek_vade_gun=None,
                 anlasma_para_birimi='TRY', anlasma_birim_fiyat=None,
                 talep_referansi=None):
    con.execute(
        """INSERT INTO nexgen_planlama_siparis
           (id, cari_id, siparis_no, durum, olusturma_tarihi,
            talep_referansi, anlasma_para_birimi, anlasma_birim_fiyat,
            odeme_tipi, vade_gun, cek_vade_gun)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (sid, cari_id, siparis_no, durum, '2026-08-10T10:00:00',
         talep_referansi, anlasma_para_birimi, anlasma_birim_fiyat,
         odeme_tipi, vade_gun, cek_vade_gun),
    )


def _add_kalem(con, kid, siparis_id, formul_ad='UrunA', renk_ad='Mavi',
               birim_fiyat=None, net_birim_fiyat=None):
    con.execute(
        """INSERT INTO nexgen_planlama_siparis_kalem
           (id, planlama_siparis_id, formul_ad, renk_ad,
            miktar_l, miktar_s, miktar_m, birim_fiyat, net_birim_fiyat)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (kid, siparis_id, formul_ad, renk_ad, 100.0, 0.0, 0.0,
         birim_fiyat, net_birim_fiyat),
    )


def _call(con, cari_id=1):
    with _stub_auth(cari_id)[0], _stub_auth(cari_id)[1]:
        return load_cari360_ticari_ozet(con, cari_id, kullanici_id=1, yk={'NEXGEN_ADMIN'})


def _top(result):
    ul = result.get('urun_fiyatlari') or []
    return ul[0] if ul else None


# ──────────────────────────────────────────────────────────────────────────────
# CASE A — CEK, cek_vade_gun DB kolonu
# ──────────────────────────────────────────────────────────────────────────────
def test_case_a():
    con = _make_db()
    con.execute("INSERT INTO nexgen_cari VALUES (1,'TestCari','T01',1)")
    _add_siparis(con, 1, cari_id=1, siparis_no='PZM-A001', durum='ONAYLANDI',
                 odeme_tipi='CEK', cek_vade_gun=220,
                 anlasma_para_birimi='USD', anlasma_birim_fiyat=4.0)
    _add_kalem(con, 10, 1, birim_fiyat=4.0, net_birim_fiyat=4.0)
    r = _call(con)
    top = _top(r)
    _chk('CASE_A son_odeme_tipi=CEK', top and top['son_odeme_tipi'] == 'CEK',
         got=top and top['son_odeme_tipi'])
    _chk('CASE_A son_gosterilecek_vade_gun=220',
         top and int(top['son_gosterilecek_vade_gun'] or 0) == 220,
         got=top and top['son_gosterilecek_vade_gun'], exp=220)
    _chk('CASE_A son_vade_gun=220',
         top and int(top['son_vade_gun'] or 0) == 220,
         got=top and top['son_vade_gun'], exp=220)
    con.close()


# ──────────────────────────────────────────────────────────────────────────────
# CASE B — CEK, JSON fallback (cek_vade_gun kolon NULL → talep_referansi)
# ──────────────────────────────────────────────────────────────────────────────
def test_case_b():
    con = _make_db()
    con.execute("INSERT INTO nexgen_cari VALUES (1,'TestCari','T01',1)")
    tr = '__PZM_V1__' + json.dumps({'cek_vade_gun': 180, 'siparis_tarihi': '2026-08-10'})
    _add_siparis(con, 1, cari_id=1, siparis_no='PZM-B001', durum='ONAYLANDI',
                 odeme_tipi='CEK', cek_vade_gun=None,  # DB kolonu yok
                 talep_referansi=tr,
                 anlasma_para_birimi='USD', anlasma_birim_fiyat=5.0)
    _add_kalem(con, 10, 1, birim_fiyat=5.0, net_birim_fiyat=5.0)
    r = _call(con)
    top = _top(r)
    _chk('CASE_B son_gosterilecek_vade_gun=180 (JSON fallback)',
         top and int(top['son_gosterilecek_vade_gun'] or 0) == 180,
         got=top and top['son_gosterilecek_vade_gun'], exp=180)
    con.close()


# ──────────────────────────────────────────────────────────────────────────────
# CASE C — VADELI
# ──────────────────────────────────────────────────────────────────────────────
def test_case_c():
    con = _make_db()
    con.execute("INSERT INTO nexgen_cari VALUES (1,'TestCari','T01',1)")
    _add_siparis(con, 1, cari_id=1, siparis_no='PZM-C001', durum='ONAYLANDI',
                 odeme_tipi='VADELI', vade_gun=90,
                 anlasma_para_birimi='TRY', anlasma_birim_fiyat=100.0)
    _add_kalem(con, 10, 1, birim_fiyat=100.0, net_birim_fiyat=100.0)
    r = _call(con)
    top = _top(r)
    _chk('CASE_C son_odeme_tipi=VADELI', top and top['son_odeme_tipi'] == 'VADELI',
         got=top and top['son_odeme_tipi'])
    _chk('CASE_C son_gosterilecek_vade_gun=90',
         top and int(top['son_gosterilecek_vade_gun'] or 0) == 90,
         got=top and top['son_gosterilecek_vade_gun'], exp=90)
    con.close()


# ──────────────────────────────────────────────────────────────────────────────
# CASE D — NAKIT
# ──────────────────────────────────────────────────────────────────────────────
def test_case_d():
    con = _make_db()
    con.execute("INSERT INTO nexgen_cari VALUES (1,'TestCari','T01',1)")
    _add_siparis(con, 1, cari_id=1, siparis_no='PZM-D001', durum='ONAYLANDI',
                 odeme_tipi='NAKIT',
                 anlasma_para_birimi='TRY', anlasma_birim_fiyat=80.0)
    _add_kalem(con, 10, 1, birim_fiyat=80.0, net_birim_fiyat=80.0)
    r = _call(con)
    top = _top(r)
    _chk('CASE_D son_odeme_tipi=NAKIT', top and top['son_odeme_tipi'] == 'NAKIT',
         got=top and top['son_odeme_tipi'])
    _chk('CASE_D son_gosterilecek_vade_gun=None (NAKIT=None, vade=0 internal)',
         top and top['son_gosterilecek_vade_gun'] is None,
         got=top and top['son_gosterilecek_vade_gun'], exp=None)
    _chk('CASE_D son_vade_gun=0 (NAKIT internal)',
         top and top['son_vade_gun'] == 0,
         got=top and top['son_vade_gun'], exp=0)
    con.close()


# ──────────────────────────────────────────────────────────────────────────────
# CASE E — BELIRTILMEMIS / veri yok
# ──────────────────────────────────────────────────────────────────────────────
def test_case_e():
    con = _make_db()
    con.execute("INSERT INTO nexgen_cari VALUES (1,'TestCari','T01',1)")
    _add_siparis(con, 1, cari_id=1, siparis_no='PZM-E001', durum='ONAYLANDI',
                 odeme_tipi=None,
                 anlasma_para_birimi='TRY', anlasma_birim_fiyat=60.0)
    _add_kalem(con, 10, 1, birim_fiyat=60.0, net_birim_fiyat=60.0)
    r = _call(con)
    top = _top(r)
    _chk('CASE_E son_gosterilecek_vade_gun=None',
         top and top['son_gosterilecek_vade_gun'] is None,
         got=top and top['son_gosterilecek_vade_gun'], exp=None)
    con.close()


# ──────────────────────────────────────────────────────────────────────────────
# CASE F — fiyat seçilen sipariş == vade siparişi (identity)
# ──────────────────────────────────────────────────────────────────────────────
def test_case_f():
    con = _make_db()
    con.execute("INSERT INTO nexgen_cari VALUES (1,'TestCari','T01',1)")
    # Sipariş 1: eski, daha düşük fiyat — CEK 90
    _add_siparis(con, 1, cari_id=1, siparis_no='PZM-F001', durum='ONAYLANDI',
                 odeme_tipi='CEK', cek_vade_gun=90,
                 anlasma_para_birimi='USD', anlasma_birim_fiyat=3.0)
    _add_kalem(con, 10, 1, birim_fiyat=3.0, net_birim_fiyat=3.0)
    # Sipariş 2: yeni, daha yüksek fiyat — CEK 220 → SON sipariş olmalı
    _add_siparis(con, 2, cari_id=1, siparis_no='PZM-F002', durum='ONAYLANDI',
                 odeme_tipi='CEK', cek_vade_gun=220,
                 anlasma_para_birimi='USD', anlasma_birim_fiyat=4.0)
    _add_kalem(con, 20, 2, birim_fiyat=4.0, net_birim_fiyat=4.0)
    r = _call(con)
    top = _top(r)
    price_sip_id = top['son_siparis_id'] if top else None
    vade_val = int(top['son_gosterilecek_vade_gun'] or 0) if top else None
    _chk('CASE_F son_siparis_id=2 (en yeni)',
         price_sip_id == 2, got=price_sip_id, exp=2)
    _chk('CASE_F son_gosterilecek_vade_gun=220 (aynı sipariş)',
         vade_val == 220, got=vade_val, exp=220)
    _chk('CASE_F fiyat ve vade aynı sipariş (identity)',
         price_sip_id == 2 and vade_val == 220)
    con.close()


# ──────────────────────────────────────────────────────────────────────────────
# CASE G — legacy header fiyatlı sipariş + vade aynı sipariş
# ──────────────────────────────────────────────────────────────────────────────
def test_case_g():
    con = _make_db()
    con.execute("INSERT INTO nexgen_cari VALUES (1,'TestCari','T01',1)")
    # legacy: kalem birim_fiyat=NULL, anlasma_birim_fiyat mevcut, tek kalem, CEK 120
    _add_siparis(con, 1, cari_id=1, siparis_no='PZM-G001', durum='ONAYLANDI',
                 odeme_tipi='CEK', cek_vade_gun=120,
                 anlasma_para_birimi='USD', anlasma_birim_fiyat=3.5)
    _add_kalem(con, 10, 1, birim_fiyat=None, net_birim_fiyat=None)  # legacy
    r = _call(con)
    top = _top(r)
    _chk('CASE_G fiyat_kaynagi=ESKI_BASLIK_FIYATI',
         top and top['fiyat_kaynagi'] == 'ESKI_BASLIK_FIYATI',
         got=top and top['fiyat_kaynagi'])
    _chk('CASE_G son_gosterilecek_vade_gun=120 (legacy fiyat + aynı sipariş)',
         top and int(top['son_gosterilecek_vade_gun'] or 0) == 120,
         got=top and top['son_gosterilecek_vade_gun'], exp=120)
    _chk('CASE_G son_siparis_id=1 (fiyat ve vade identity)',
         top and top['son_siparis_id'] == 1,
         got=top and top['son_siparis_id'], exp=1)
    con.close()


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    test_case_a()
    test_case_b()
    test_case_c()
    test_case_d()
    test_case_e()
    test_case_f()
    test_case_g()

    print()
    print(f'PASS: {len(_PASS)}  FAIL: {len(_FAIL)}')
    if _FAIL:
        print('FAILED:', _FAIL)
        raise SystemExit(1)
    print('ALL PASS')
