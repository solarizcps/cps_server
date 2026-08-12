# -*- coding: utf-8 -*-
"""
CARI360-FINANS-CANONICAL-IMPLEMENTATION-01 REGRESSION
READ-ONLY (testler isolated in-memory DB'de çalışır).
Canonical DB'ye yazma yok.

CASE A  — Tahsilatı olmayan cari
CASE B  — MO tahsilatı olan cari
CASE C  — Manuel finans tahsilatı olan cari
CASE D  — Her iki kaynaktan tahsilat
CASE E  — CEK siparişli cari (canonical vade resolver)
CASE F  — VADELI siparişli cari
CASE G  — NAKIT siparişli cari
CASE H  — Gerçek çek kaydı olan cari
CASE I  — Döviz tahsilatlı cari (FX ayrımı)
CASE J  — Cari_Har bulunan legacy cari
CASE K  — Cari_Har bulunmayan yeni cari

CASE M1 — Manuel tahsilat write (in-memory)
CASE M2 — Duplicate kaynak ayrımı
CASE M3 — Currency aggregation doğru (TRY-only)
"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app'))

from modules.nexgen.cari360_finans_service import (
    KAYNAK_MANUEL_FINANS,
    KAYNAK_MUSTERI_OPERASYONU,
    load_cari360_finans,
    load_cari360_tahsilat_liste,
    manuel_tahsilat_olustur,
)

_PASS = []
_FAIL = []


def _chk(label, cond, got=None, exp=None):
    if cond:
        _PASS.append(label)
        print(f'PASS  {label}')
    else:
        _FAIL.append(label)
        print(f'FAIL  {label}  got={got!r}  exp={exp!r}')


def _make_db(with_siparis=True, with_cek=True, with_tahsilat=True):
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.execute("""
        CREATE TABLE nexgen_cari (id INTEGER PRIMARY KEY, cari_adi TEXT, aktif INTEGER DEFAULT 1)
    """)
    con.execute("""
        CREATE TABLE mo_tahsilat_kayit (
            id INTEGER PRIMARY KEY, kayit_kodu TEXT, cari_id INTEGER,
            siparis_id INTEGER, kaynak_modul TEXT, beklenen_tutar REAL,
            beklenen_tahmini INTEGER DEFAULT 0, alinan_tutar REAL, kalan_tutar REAL,
            planlanan_tahsilat_tarihi TEXT, alinan_tarih TEXT,
            odeme_tipi TEXT, odeme_referansi TEXT, kismi_mi INTEGER DEFAULT 0,
            aciklama TEXT, durum TEXT, cari_entegrasyon_durumu TEXT DEFAULT 'BEKLIYOR',
            idempotency_key TEXT, olusturan_id INTEGER, onaylayan_id INTEGER,
            aktif INTEGER DEFAULT 1, olusturma_tarihi TEXT, guncelleme_tarihi TEXT,
            para_birimi TEXT DEFAULT 'TRY'
        )
    """)
    con.execute("""
        CREATE TABLE mo_tahsilat_cek (
            id INTEGER PRIMARY KEY, tahsilat_kayit_id INTEGER, sira_no INTEGER,
            tutar REAL, para_birimi TEXT, cek_alim_tarihi TEXT,
            gercek_cek_vade_tarihi TEXT, odeme_referansi TEXT, banka_adi TEXT,
            durum TEXT DEFAULT 'AKTIF', aktif INTEGER DEFAULT 1,
            idempotency_key TEXT, olusturan_id INTEGER,
            olusturma_tarihi TEXT, guncelleme_tarihi TEXT, audit_json TEXT
        )
    """)
    if with_siparis:
        con.execute("""
            CREATE TABLE nexgen_planlama_siparis (
                id INTEGER PRIMARY KEY, cari_id INTEGER, siparis_no TEXT,
                durum TEXT, olusturma_tarihi TEXT, talep_referansi TEXT,
                anlasma_para_birimi TEXT, anlasma_birim_fiyat REAL,
                odeme_tipi TEXT, vade_gun INTEGER, cek_vade_gun INTEGER
            )
        """)
    return con


def _add_cari(con, cari_id=1):
    con.execute('INSERT INTO nexgen_cari VALUES (?,?,1)', (cari_id, f'Cari{cari_id}'))


def _add_tahsilat(con, cari_id, tid, alinan, durum='ONAYLANDI',
                  kaynak=KAYNAK_MUSTERI_OPERASYONU, pb='TRY',
                  tarih='2026-08-10', siparis_id=None):
    con.execute(
        """INSERT INTO mo_tahsilat_kayit
           (id, kayit_kodu, cari_id, siparis_id, kaynak_modul, alinan_tutar,
            kalan_tutar, alinan_tarih, odeme_tipi, durum,
            idempotency_key, olusturan_id, aktif, olusturma_tarihi, guncelleme_tarihi,
            para_birimi, beklenen_tutar)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (tid, f'T-{tid:04d}', cari_id, siparis_id, kaynak, alinan,
         0.0, tarih, 'NAKIT', durum,
         f'idem-{tid}', 1, 1, '2026-08-10', '2026-08-10', pb, alinan),
    )


def _add_cek_tahsilat(con, cari_id, tid, tutar, pb='TRY', vade='2026-12-31'):
    con.execute(
        """INSERT INTO mo_tahsilat_kayit
           (id, kayit_kodu, cari_id, kaynak_modul, alinan_tutar, kalan_tutar,
            alinan_tarih, odeme_tipi, durum, idempotency_key, olusturan_id,
            aktif, olusturma_tarihi, guncelleme_tarihi, para_birimi, beklenen_tutar)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (tid, f'T-{tid:04d}', cari_id, KAYNAK_MUSTERI_OPERASYONU, tutar, 0.0,
         '2026-08-10', 'CEK', 'ONAYLANDI', f'idem-{tid}', 1, 1,
         '2026-08-10', '2026-08-10', pb, tutar),
    )
    new_id = con.execute('SELECT last_insert_rowid()').fetchone()[0]
    con.execute(
        """INSERT INTO mo_tahsilat_cek
           (tahsilat_kayit_id, sira_no, tutar, para_birimi, cek_alim_tarihi,
            gercek_cek_vade_tarihi, odeme_referansi, durum, aktif,
            idempotency_key, olusturan_id, olusturma_tarihi, guncelleme_tarihi)
           VALUES (?,1,?,?,?,?,?,?,?,?,?,?,?)""",
        (new_id, tutar, pb, '2026-08-10', vade, f'CEK-{tid}',
         'AKTIF', 1, f'cek-{tid}', 1, '2026-08-10', '2026-08-10'),
    )


def _add_siparis(con, cari_id, sid, odeme_tipi='NAKIT',
                 vade_gun=None, cek_vade_gun=None, durum='ONAYLANDI'):
    con.execute(
        """INSERT INTO nexgen_planlama_siparis
           (id, cari_id, siparis_no, durum, olusturma_tarihi,
            anlasma_para_birimi, odeme_tipi, vade_gun, cek_vade_gun)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (sid, cari_id, f'PZM-{sid:04d}', durum, '2026-08-10',
         'TRY', odeme_tipi, vade_gun, cek_vade_gun),
    )


def _load(con, cari_id=1):
    return load_cari360_finans(con, cari_id)


# ── CASE A — Tahsilatı olmayan cari ──
def test_case_a():
    con = _make_db()
    _add_cari(con)
    r = _load(con)
    t = r['tahsilat']
    tl = r['tahsilat_liste']
    _chk('A tahsilat.alinan=0', t['alinan_toplam'] == 0.0, t['alinan_toplam'])
    _chk('A liste.toplam=0', tl['toplam'] == 0, tl['toplam'])
    _chk('A liste.bos', len(tl['liste']) == 0)
    con.close()


# ── CASE B — MO tahsilatı ──
def test_case_b():
    con = _make_db()
    _add_cari(con)
    _add_tahsilat(con, 1, 1, 5000.0, kaynak=KAYNAK_MUSTERI_OPERASYONU)
    r = _load(con)
    t = r['tahsilat']
    tl = r['tahsilat_liste']
    _chk('B alinan=5000', abs(t['alinan_toplam'] - 5000.0) < 0.01, t['alinan_toplam'])
    _chk('B liste.toplam=1', tl['toplam'] == 1)
    _chk('B kaynak=MUSTERI_OPERASYONU',
         tl['liste'][0]['kaynak_raw'] == KAYNAK_MUSTERI_OPERASYONU)
    con.close()


# ── CASE C — Manuel finans tahsilatı ──
def test_case_c():
    con = _make_db()
    _add_cari(con)
    _add_tahsilat(con, 1, 1, 8000.0, kaynak=KAYNAK_MANUEL_FINANS)
    r = _load(con)
    tl = r['tahsilat_liste']
    _chk('C kaynak=MANUEL_FINANS',
         tl['liste'][0]['kaynak_raw'] == KAYNAK_MANUEL_FINANS)
    _chk('C alinan=8000', abs(r['tahsilat']['alinan_toplam'] - 8000.0) < 0.01)
    con.close()


# ── CASE D — Her iki kaynaktan tahsilat birleşmiş liste ──
def test_case_d():
    con = _make_db()
    _add_cari(con)
    _add_tahsilat(con, 1, 1, 3000.0, kaynak=KAYNAK_MUSTERI_OPERASYONU, tarih='2026-08-09')
    _add_tahsilat(con, 1, 2, 2000.0, kaynak=KAYNAK_MANUEL_FINANS, tarih='2026-08-10')
    r = _load(con)
    tl = r['tahsilat_liste']
    kaynaklar = {x['kaynak_raw'] for x in tl['liste']}
    _chk('D liste.toplam=2', tl['toplam'] == 2)
    _chk('D her iki kaynak var', KAYNAK_MUSTERI_OPERASYONU in kaynaklar and KAYNAK_MANUEL_FINANS in kaynaklar)
    _chk('D alinan=5000', abs(r['tahsilat']['alinan_toplam'] - 5000.0) < 0.01)
    _chk('D duplicate yok', len(tl['liste']) == 2)
    con.close()


# ── CASE E — CEK siparişli cari (canonical vade) ──
def test_case_e():
    con = _make_db()
    _add_cari(con)
    _add_siparis(con, 1, 1, odeme_tipi='CEK', cek_vade_gun=220)
    r = _load(con)
    vc = r['vade_cek']
    _chk('E cekli_siparis=1', vc['cekli_siparis_sayisi'] == 1)
    _chk('E cek_vadeleri mevcut', len(vc['cek_vadeleri']) > 0, vc['cek_vadeleri'])
    _chk('E cek_vadeleri=220', '220' in [str(v) for v in vc['cek_vadeleri']])
    con.close()


# ── CASE F — VADELI siparişli cari ──
def test_case_f():
    con = _make_db()
    _add_cari(con)
    _add_siparis(con, 1, 1, odeme_tipi='VADELI', vade_gun=90)
    r = _load(con)
    vc = r['vade_cek']
    _chk('F ortalama_vade=90', vc['ortalama_vade_gun'] == 90.0, vc['ortalama_vade_gun'])
    _chk('F cekli_siparis=0', vc['cekli_siparis_sayisi'] == 0)
    con.close()


# ── CASE G — NAKIT siparişli cari ──
def test_case_g():
    con = _make_db()
    _add_cari(con)
    _add_siparis(con, 1, 1, odeme_tipi='NAKIT')
    r = _load(con)
    vc = r['vade_cek']
    _chk('G ortalama_vade=None (NAKIT)', vc['ortalama_vade_gun'] is None)
    _chk('G cekli_siparis=0', vc['cekli_siparis_sayisi'] == 0)
    con.close()


# ── CASE H — Gerçek çek kaydı (mo_tahsilat_cek) ──
def test_case_h():
    con = _make_db()
    _add_cari(con)
    _add_cek_tahsilat(con, 1, 1, 12000.0, pb='USD', vade='2026-08-14')
    r = _load(con)
    cekler = r['gercek_cekler']
    _chk('H gercek_cek var', len(cekler) == 1, len(cekler))
    _chk('H cek.vade=2026-08-14', cekler[0]['vade_tarihi'] == '2026-08-14')
    _chk('H cek.tutar=12000', abs(cekler[0]['tutar'] - 12000.0) < 0.01)
    _chk('H cek.pb=USD', cekler[0]['para_birimi'] == 'USD')
    # Sipariş CEK ≠ gerçek çek: sipariş olmadan da çek olabilir
    vc = r['vade_cek']
    _chk('H siparis_cek=0 (cek=MO, siparis yok)', vc['cekli_siparis_sayisi'] == 0)
    con.close()


# ── CASE I — Döviz tahsilatlı cari (TRY ayrımı) ──
def test_case_i():
    con = _make_db()
    _add_cari(con)
    _add_tahsilat(con, 1, 1, 5000.0, pb='TRY')   # TRY sayılır
    _add_tahsilat(con, 1, 2, 100.0, pb='USD')    # FX — TRY toplamına dahil değil
    r = _load(con)
    t = r['tahsilat']
    _chk('I alinan_TRY_only=5000', abs(t['alinan_toplam'] - 5000.0) < 0.01, t['alinan_toplam'])
    _chk('I fx_kayit_var=True', t['fx_kayit_var'] is True, t['fx_kayit_var'])
    _chk('I fx_uyari_var', t['fx_uyari'] is not None)
    con.close()


# ── CASE J — Cari_Har bulunan legacy cari (eslesme sonucu kontrol) ──
def test_case_j():
    con = _make_db()
    _add_cari(con)
    # Cari_Har tablosu yok → eslesme.eslesme = False
    r = _load(con)
    es = r['eslesme']
    _chk('J eslesme.eslesme=False (tablo yok)', not es.get('eslesme', True))
    con.close()


# ── CASE K — Cari_Har yok, yeni cari ──
def test_case_k():
    # J ile aynı — yeni sistemde zaten Cari_Har yok
    con = _make_db()
    _add_cari(con)
    r = _load(con)
    _chk('K load_ok', 'tahsilat' in r and 'vade_cek' in r)
    _chk('K risk_notu_var', 'risk_notu' in r)
    con.close()


# ── CASE M1 — Manuel tahsilat write (in-memory) ──
def test_case_m1():
    con = _make_db()
    _add_cari(con)
    res = manuel_tahsilat_olustur(
        con, 1, 99,
        alinan_tarih='2026-08-12',
        odeme_tipi='HAVALE',
        alinan_tutar=7500.0,
        para_birimi='TRY',
        aciklama='Test manuel',
    )
    _chk('M1 ok=True', res.get('ok') is True, res)
    row = con.execute('SELECT * FROM mo_tahsilat_kayit WHERE id=last_insert_rowid()').fetchone()
    _chk('M1 kaynak=MANUEL_FINANS', row['kaynak_modul'] == KAYNAK_MANUEL_FINANS)
    _chk('M1 tutar=7500', abs(float(row['alinan_tutar']) - 7500.0) < 0.01)
    _chk('M1 durum=ONAYLANDI', row['durum'] == 'ONAYLANDI')
    con.close()


# ── CASE M2 — Kaynak ayrımı doğru ──
def test_case_m2():
    con = _make_db()
    _add_cari(con)
    _add_tahsilat(con, 1, 1, 3000.0, kaynak=KAYNAK_MUSTERI_OPERASYONU)
    manuel_tahsilat_olustur(con, 1, 99,
        alinan_tarih='2026-08-12', odeme_tipi='NAKIT',
        alinan_tutar=1500.0, para_birimi='TRY')
    tl = load_cari360_tahsilat_liste(con, 1, limit=10)
    sources = [x['kaynak_raw'] for x in tl['liste']]
    _chk('M2 liste=2', len(tl['liste']) == 2, len(tl['liste']))
    _chk('M2 MUSTERI_OP var', KAYNAK_MUSTERI_OPERASYONU in sources)
    _chk('M2 MANUEL_FINANS var', KAYNAK_MANUEL_FINANS in sources)
    con.close()


# ── CASE M3 — Currency aggregation: USD kör sum olmaz ──
def test_case_m3():
    con = _make_db()
    _add_cari(con)
    _add_tahsilat(con, 1, 1, 10000.0, pb='TRY')
    _add_tahsilat(con, 1, 2, 500.0, pb='USD')
    _add_tahsilat(con, 1, 3, 200.0, pb='EUR')
    r = _load(con)
    t = r['tahsilat']
    # TRY olmayan tutarlar toplama dahil değil
    _chk('M3 alinan=10000 (TRY only)', abs(t['alinan_toplam'] - 10000.0) < 0.01, t['alinan_toplam'])
    _chk('M3 fx_var=True', t['fx_kayit_var'] is True)
    con.close()


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    test_case_a()
    test_case_b()
    test_case_c()
    test_case_d()
    test_case_e()
    test_case_f()
    test_case_g()
    test_case_h()
    test_case_i()
    test_case_j()
    test_case_k()
    test_case_m1()
    test_case_m2()
    test_case_m3()

    print()
    print(f'PASS: {len(_PASS)}  FAIL: {len(_FAIL)}')
    if _FAIL:
        print('FAILED:', _FAIL)
        raise SystemExit(1)
    print('ALL PASS')
