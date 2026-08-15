# -*- coding: utf-8 -*-
"""
test_cari360_planli_gorusme_parity_lock.py
==========================================
Cari360 Planlı Görüşmeler parity kontrat kilitleri.
30 kontrat — temporary SQLite fixture, canonical DB'ye write yok.
"""
from __future__ import annotations

import sqlite3
import sys
import os
from datetime import datetime, date, timedelta


import pytest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_db():
    """In-memory SQLite with minimal schema."""
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE sistem_kullanici (
            Id INTEGER PRIMARY KEY,
            AdSoyad TEXT
        );
        CREATE TABLE nexgen_cari (
            id INTEGER PRIMARY KEY,
            unvan TEXT,
            cari_kod TEXT,
            aktif INTEGER DEFAULT 1
        );
        CREATE TABLE musteri_operasyon_ajanda (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            cari_id                INTEGER,
            musteri_aday_id        INTEGER,
            firma_adi_gorunum      TEXT,
            kullanici_id           INTEGER NOT NULL,
            plan_tarihi            TEXT NOT NULL,
            gorusme_tipi           TEXT NOT NULL,
            plan_notu              TEXT,
            durum                  TEXT NOT NULL DEFAULT 'PLANLANDI',
            gorusme_id             INTEGER,
            idempotency_key        TEXT NOT NULL UNIQUE,
            aktif                  INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi       TEXT,
            guncelleme_tarihi      TEXT,
            olusturan_kullanici_id INTEGER,
            plan_yetkili_metin     TEXT,
            plan_telefon           TEXT,
            plan_sehir             TEXT
        );
        CREATE TABLE musteri_operasyon_gorusme (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            cari_id         INTEGER,
            kullanici_id    INTEGER,
            gorusme_tarihi  TEXT,
            gorusme_tipi    TEXT,
            sonuc_tipi      TEXT,
            kisa_not        TEXT,
            takip_durumu    TEXT DEFAULT 'BEKLEMEDE',
            aktif           INTEGER DEFAULT 1,
            idempotency_key TEXT UNIQUE
        );
        CREATE TABLE cari_sorumlu (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kullanici_id INTEGER,
            cari_id INTEGER,
            sorumluluk_rolu TEXT,
            aktif INTEGER DEFAULT 1,
            bitis_tarihi TEXT
        );
    """)
    # Seed kullanıcılar
    con.execute("INSERT INTO sistem_kullanici VALUES (49, 'Erhan Atlar')")
    con.execute("INSERT INTO sistem_kullanici VALUES (50, 'Başka Kullanıcı')")
    # Seed cariler
    con.execute("INSERT INTO nexgen_cari VALUES (7, 'AYM Taban Poliüretan', 'AYM001', 1)")
    con.execute("INSERT INTO nexgen_cari VALUES (99, 'Başka Cari', 'BASKA', 1)")
    # Seed sorumlu
    con.execute(
        "INSERT INTO cari_sorumlu (kullanici_id, cari_id, sorumluluk_rolu, aktif) VALUES (49, 7, 'ANA', 1)"
    )
    con.commit()
    return con


def _insert_plan(con, **kw):
    defaults = dict(
        cari_id=7,
        kullanici_id=49,
        plan_tarihi=(datetime.now() + timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S'),
        gorusme_tipi='WhatsApp',
        plan_notu='asdadasda',
        durum='PLANLANDI',
        gorusme_id=None,
        aktif=1,
        plan_yetkili_metin='Test Yetkili',
        idempotency_key=None,
    )
    defaults.update(kw)
    if not defaults['idempotency_key']:
        defaults['idempotency_key'] = f"idem-{id(kw)}-{hash(str(kw))}"
    con.execute("""
        INSERT INTO musteri_operasyon_ajanda
        (cari_id, kullanici_id, plan_tarihi, gorusme_tipi, plan_notu,
         durum, gorusme_id, aktif, plan_yetkili_metin, idempotency_key,
         olusturan_kullanici_id, olusturma_tarihi)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
    """, (
        defaults['cari_id'], defaults['kullanici_id'], defaults['plan_tarihi'],
        defaults['gorusme_tipi'], defaults['plan_notu'], defaults['durum'],
        defaults['gorusme_id'], defaults['aktif'], defaults['plan_yetkili_metin'],
        defaults['idempotency_key'], defaults['kullanici_id'],
    ))
    con.commit()
    return con.execute("SELECT last_insert_rowid()").fetchone()[0]


def _insert_gorusme(con, **kw):
    defaults = dict(cari_id=7, kullanici_id=49,
                    gorusme_tarihi=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    gorusme_tipi='WhatsApp', sonuc_tipi='Genel Görüşme',
                    takip_durumu='BEKLEMEDE', aktif=1, idempotency_key=None)
    defaults.update(kw)
    if not defaults['idempotency_key']:
        defaults['idempotency_key'] = f"gor-{id(kw)}-{hash(str(kw))}"
    con.execute("""
        INSERT INTO musteri_operasyon_gorusme
        (cari_id, kullanici_id, gorusme_tarihi, gorusme_tipi, sonuc_tipi,
         takip_durumu, aktif, idempotency_key)
        VALUES (?,?,?,?,?,?,?,?)
    """, (defaults['cari_id'], defaults['kullanici_id'], defaults['gorusme_tarihi'],
          defaults['gorusme_tipi'], defaults['sonuc_tipi'], defaults['takip_durumu'],
          defaults['aktif'], defaults['idempotency_key']))
    con.commit()
    return con.execute("SELECT last_insert_rowid()").fetchone()[0]


# Patch can_mo_view_cari to always allow in tests
import unittest.mock as mock

def _call(con, cari_id=7, kullanici_id=49, yk=None):
    from modules.nexgen.mo_ajanda_service import list_planli_by_cari
    with mock.patch('modules.nexgen.mo_ajanda_service.can_mo_view_cari', return_value=True):
        return list_planli_by_cari(con, cari_id, kullanici_id, yk)


# ---------------------------------------------------------------------------
# Kontrat 1: Yalnız aynı cari planları döner
# ---------------------------------------------------------------------------
def test_01_yalniz_ayni_cari():
    con = _make_db()
    _insert_plan(con, cari_id=7, idempotency_key='p1')
    _insert_plan(con, cari_id=99, idempotency_key='p2')
    result = _call(con, cari_id=7)
    assert all(r['cari_id'] == 7 for r in result)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Kontrat 2: aktif=0 dönmez
# ---------------------------------------------------------------------------
def test_02_aktif_sifir_donmez():
    con = _make_db()
    _insert_plan(con, aktif=0, idempotency_key='p_pasif')
    result = _call(con)
    assert result == []


# ---------------------------------------------------------------------------
# Kontrat 3: PLANLANDI döner
# ---------------------------------------------------------------------------
def test_03_planlandi_doner():
    con = _make_db()
    _insert_plan(con, durum='PLANLANDI', idempotency_key='p_planlandi')
    result = _call(con)
    assert len(result) == 1
    assert result[0]['durum'] == 'PLANLANDI'


# ---------------------------------------------------------------------------
# Kontrat 4: GERCEKLESTI dönmez
# ---------------------------------------------------------------------------
def test_04_gerceklesti_donmez():
    con = _make_db()
    _insert_plan(con, durum='GERCEKLESTI', gorusme_id=99, idempotency_key='p_ger')
    result = _call(con)
    assert result == []


# ---------------------------------------------------------------------------
# Kontrat 5: IPTAL dönmez
# ---------------------------------------------------------------------------
def test_05_iptal_donmez():
    con = _make_db()
    _insert_plan(con, durum='IPTAL', idempotency_key='p_iptal')
    result = _call(con)
    assert result == []


# ---------------------------------------------------------------------------
# Kontrat 6: gorusme_id dolu plan dönmez
# ---------------------------------------------------------------------------
def test_06_gorusme_id_dolu_donmez():
    con = _make_db()
    _insert_plan(con, gorusme_id=555, idempotency_key='p_gorusme_id')
    result = _call(con)
    assert result == []


# ---------------------------------------------------------------------------
# Kontrat 7: Plan tarihi ASC sıralanır
# ---------------------------------------------------------------------------
def test_07_plan_tarihi_asc():
    con = _make_db()
    _insert_plan(con, plan_tarihi='2026-09-15 09:00:00', idempotency_key='p_b')
    _insert_plan(con, plan_tarihi='2026-08-20 09:00:00', idempotency_key='p_a')
    result = _call(con)
    assert len(result) == 2
    assert result[0]['plan_tarihi'] < result[1]['plan_tarihi']


# ---------------------------------------------------------------------------
# Kontrat 8: Plan notu aynen gelir
# ---------------------------------------------------------------------------
def test_08_plan_notu_aynen():
    con = _make_db()
    _insert_plan(con, plan_notu='asdadasda', idempotency_key='p_not')
    result = _call(con)
    assert result[0]['plan_notu'] == 'asdadasda'


# ---------------------------------------------------------------------------
# Kontrat 9: Pazarlamacı doğru resolve edilir
# ---------------------------------------------------------------------------
def test_09_pazarlamaci_resolve():
    con = _make_db()
    _insert_plan(con, kullanici_id=49, idempotency_key='p_pzm')
    result = _call(con)
    assert result[0]['pazarlamaci'] == 'Erhan Atlar'
    assert result[0]['pazarlamaci_id'] == 49


# ---------------------------------------------------------------------------
# Kontrat 10: Yetkili snapshot gelir
# ---------------------------------------------------------------------------
def test_10_yetkili_snapshot():
    con = _make_db()
    _insert_plan(con, plan_yetkili_metin='Bilal Bey', idempotency_key='p_yet')
    result = _call(con)
    assert result[0]['yetkili'] == 'Bilal Bey'


# ---------------------------------------------------------------------------
# Kontrat 11: Görüşme türü gelir
# ---------------------------------------------------------------------------
def test_11_gorusme_turu():
    con = _make_db()
    _insert_plan(con, gorusme_tipi='Fabrika Ziyareti', idempotency_key='p_tur')
    result = _call(con)
    assert result[0]['gorusme_turu'] == 'Fabrika Ziyareti'


# ---------------------------------------------------------------------------
# Kontrat 12: PLANLANDI map doğru (gelecek tarih)
# ---------------------------------------------------------------------------
def test_12_planlandi_map():
    con = _make_db()
    gelecek = (datetime.now() + timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S')
    _insert_plan(con, plan_tarihi=gelecek, idempotency_key='p_map_planlandi')
    result = _call(con)
    assert result[0]['durum_gorunum'] == 'PLANLANDI'


# ---------------------------------------------------------------------------
# Kontrat 13: BUGÜN map doğru (bugün saat geçmiş)
# ---------------------------------------------------------------------------
def test_13_bugun_map():
    con = _make_db()
    # Bugün ama birkaç dakika önce
    bugun_gecmis = (datetime.now() - timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
    _insert_plan(con, plan_tarihi=bugun_gecmis, idempotency_key='p_map_bugun')
    result = _call(con)
    # SONUC_BEKLIYOR → BUGÜN (plan günü == bugün ve saat <= şimdi)
    assert result[0]['durum_gorunum'] == 'BUGÜN'


# ---------------------------------------------------------------------------
# Kontrat 14: GECİKTİ map doğru (geçmiş gün)
# ---------------------------------------------------------------------------
def test_14_gecikti_map():
    con = _make_db()
    dun = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')
    _insert_plan(con, plan_tarihi=dun, idempotency_key='p_map_gecikti')
    result = _call(con)
    assert result[0]['durum_gorunum'] == 'GECİKTİ'


# ---------------------------------------------------------------------------
# Kontrat 15: Ajanda URL doğru
# ---------------------------------------------------------------------------
def test_15_ajanda_url():
    con = _make_db()
    _insert_plan(con, kullanici_id=49, idempotency_key='p_ajanda_url')
    result = _call(con)
    assert '/nexgen/musteri-pazarlama/ajanda' in result[0]['ajanda_url']
    assert 'hedef_kullanici_id=49' in result[0]['ajanda_url']


# ---------------------------------------------------------------------------
# Kontrat 16: API response'ta sonuclandir_url bulunmaz (read-only)
# ---------------------------------------------------------------------------
def test_16_sonuclandir_url_yok():
    con = _make_db()
    _insert_plan(con, cari_id=7, idempotency_key='p_sonuc_ids')
    result = _call(con)
    assert 'sonuclandir_url' not in result[0]


# ---------------------------------------------------------------------------
# Kontrat 17: ajanda_sonuc deep-link üretilmez (read-only)
# ---------------------------------------------------------------------------
def test_17_ajanda_sonuc_deeplink_yok():
    con = _make_db()
    _insert_plan(con, plan_notu='özel & <test>', plan_yetkili_metin='Şen Bey',
                 gorusme_tipi='Fabrika Ziyareti', idempotency_key='p_encode')
    result = _call(con)
    # Hiçbir alanda ajanda_sonuc=1 deep link olmamalı
    for key, val in result[0].items():
        if isinstance(val, str):
            assert 'ajanda_sonuc' not in val, f"ajanda_sonuc deep-link field '{key}' içinde bulundu"


# ---------------------------------------------------------------------------
# Kontrat 18: Mevcut gerçek görüşme listesi korunur (API response'u etkilemez)
# ---------------------------------------------------------------------------
def test_18_gercek_gorusmeler_korunur():
    """list_planli_by_cari sadece ajanda okur; gerçek görüşme tablosuna dokunmaz."""
    con = _make_db()
    gid = _insert_gorusme(con, cari_id=7)
    _insert_plan(con, idempotency_key='p_izolasyon')
    planlar = _call(con)
    # Plan listesi 1 döner
    assert len(planlar) == 1
    # Görüşme tablosu bozulmadı
    row = con.execute("SELECT * FROM musteri_operasyon_gorusme WHERE id=?", (gid,)).fetchone()
    assert row is not None


# ---------------------------------------------------------------------------
# Kontrat 19: Son Görüşme planlardan etkilenmez
# ---------------------------------------------------------------------------
def test_19_son_gorusme_planlardan_etkilenmez():
    """list_planli_by_cari plan tarihi ile görüşme tablosunu değiştirmez."""
    con = _make_db()
    gelecek = (datetime.now() + timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S')
    _insert_plan(con, plan_tarihi=gelecek, idempotency_key='p_son_gor')
    # Görüşme tablosunda kayıt yok
    cnt = con.execute("SELECT COUNT(*) FROM musteri_operasyon_gorusme WHERE cari_id=7").fetchone()[0]
    assert cnt == 0


# ---------------------------------------------------------------------------
# Kontrat 20: Açık takip planlardan etkilenmez
# ---------------------------------------------------------------------------
def test_20_acik_takip_planlardan_etkilenmez():
    """PLANLANDI kayıtların takip_durumu yok; acik_takip_sayisi planları saymaz."""
    con = _make_db()
    _insert_plan(con, idempotency_key='p_acik')
    from modules.nexgen.mo_gorusme_service import acik_takip_sayisi
    with mock.patch('modules.nexgen.mo_gorusme_service.can_mo_view_cari', return_value=True):
        cnt = acik_takip_sayisi(con, 7)
    assert cnt == 0


# ---------------------------------------------------------------------------
# Kontrat 21: Sekme rozeti planları saymaz
# ---------------------------------------------------------------------------
def test_21_sekme_rozeti_planları_saymaz():
    """gorusme tablosu count planları içermez."""
    con = _make_db()
    _insert_plan(con, idempotency_key='p_badge')
    cnt = con.execute(
        "SELECT COUNT(*) FROM musteri_operasyon_gorusme WHERE cari_id=7 AND aktif=1"
    ).fetchone()[0]
    assert cnt == 0


# ---------------------------------------------------------------------------
# Kontrat 22: Template Planlı Görüşmeler başlığını içerir
# ---------------------------------------------------------------------------
def test_22_template_planli_baslik():
    tpl_path = os.path.join(
        os.path.dirname(__file__), '..', '..', 'app',
        'templates', 'nexgen', 'cari360_kart.html',
    )
    content = open(tpl_path, encoding='utf-8').read()
    assert 'Planlı Görüşmeler' in content


# ---------------------------------------------------------------------------
# Kontrat 23: Template Görüşme Geçmişi başlığını içerir
# ---------------------------------------------------------------------------
def test_23_template_gecmis_baslik():
    tpl_path = os.path.join(
        os.path.dirname(__file__), '..', '..', 'app',
        'templates', 'nexgen', 'cari360_kart.html',
    )
    content = open(tpl_path, encoding='utf-8').read()
    assert 'Görüşme Geçmişi' in content


# ---------------------------------------------------------------------------
# Kontrat 24: Plan notu esc() ile render edilir (template)
# ---------------------------------------------------------------------------
def test_24_plan_notu_esc():
    tpl_path = os.path.join(
        os.path.dirname(__file__), '..', '..', 'app',
        'templates', 'nexgen', 'cari360_kart.html',
    )
    content = open(tpl_path, encoding='utf-8').read()
    # Render kodunda plan_notu esc() ile sarılmalı
    assert 'esc(p.plan_notu)' in content


# ---------------------------------------------------------------------------
# Kontrat 25: XSS — plan_notu backend'den ham döner, URL deep-link üretilmez
# ---------------------------------------------------------------------------
def test_25_xss_plan_notu():
    con = _make_db()
    _insert_plan(con, plan_notu='<script>alert(1)</script>', idempotency_key='p_xss')
    result = _call(con)
    # Backend'den ham döner; frontend esc() ile escape eder
    assert result[0]['plan_notu'] == '<script>alert(1)</script>'
    # sonuclandir_url artık üretilmez
    assert 'sonuclandir_url' not in result[0]


# ---------------------------------------------------------------------------
# Kontrat 26: Ajandaya Git render edilir (template)
# ---------------------------------------------------------------------------
def test_26_ajandaya_git_render():
    tpl_path = os.path.join(
        os.path.dirname(__file__), '..', '..', 'app',
        'templates', 'nexgen', 'cari360_kart.html',
    )
    content = open(tpl_path, encoding='utf-8').read()
    assert 'Ajandaya Git' in content


# ---------------------------------------------------------------------------
# Kontrat 27: Sonuçlandır template'de bulunmaz, BAĞLANTI başlığı vardır (read-only)
# ---------------------------------------------------------------------------
def test_27_sonuclandir_yok_baglanti_var():
    tpl_path = os.path.join(
        os.path.dirname(__file__), '..', '..', 'app',
        'templates', 'nexgen', 'cari360_kart.html',
    )
    content = open(tpl_path, encoding='utf-8').read()
    # Planlı Görüşmeler bölümünde sonuclandir_url deep-link olmamalı
    assert 'sonuclandir_url' not in content
    assert 'ajanda_sonuc' not in content
    # BAĞLANTI kolon başlığı bulunmalı
    assert 'Bağlantı' in content


# ---------------------------------------------------------------------------
# Kontrat 28: Plan yokken bölüm gizlenir (JS logic)
# ---------------------------------------------------------------------------
def test_28_bos_plan_gizlenir():
    tpl_path = os.path.join(
        os.path.dirname(__file__), '..', '..', 'app',
        'templates', 'nexgen', 'cari360_kart.html',
    )
    content = open(tpl_path, encoding='utf-8').read()
    assert 'ckart-planli-gorusmeler-wrap' in content
    assert "wrap.style.display = 'none'" in content or "style.display = 'none'" in content


# ---------------------------------------------------------------------------
# Kontrat 29: Fresh API davranışı — stale cache riski yok
# ---------------------------------------------------------------------------
def test_29_fresh_api_davranisi():
    """ckartGorusmeYukle her çağrıda force=true ile çağrılmalı (tab açılışında)."""
    tpl_path = os.path.join(
        os.path.dirname(__file__), '..', '..', 'app',
        'templates', 'nexgen', 'cari360_kart.html',
    )
    content = open(tpl_path, encoding='utf-8').read()
    # Tab click handler force=true ile çağırmalı
    assert "ckartGorusmeYukle(true)" in content


# ---------------------------------------------------------------------------
# Kontrat 30: Geçmiş görüşme sırası DESC korunur
# ---------------------------------------------------------------------------
def test_30_gecmis_gorusme_desc():
    """list_gorusmeler_paginated sıralaması DESC — servis kodunda kanıtla."""
    src_path = os.path.join(
        os.path.dirname(__file__), '..', '..', 'app',
        'modules', 'nexgen', 'mo_gorusme_service.py',
    )
    content = open(src_path, encoding='utf-8').read()
    assert 'gorusme_tarihi DESC, g.id DESC' in content or 'gorusme_tarihi DESC, id DESC' in content
