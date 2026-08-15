# -*- coding: utf-8 -*-
"""C360-NUMUNE-PARITY-LOCK — Cari360 Numuneler canonical parity regression lock.

Kilitlenen contract'lar (1–20):
  Backend (load_cari360_numuneler, izole temp SQLite):
    1–11  Alan / filtre / durum / enrichment doğruluğu
    12–13 Pagination + sipariş bağlantıları
    18–20 API kontratı, mükerrer satır yok, enrichment ana satırı kaybettirmez
  Template (statik HTML, DB kullanmaz):
    14–16 Modern / legacy AR-GE render + boş AR-GE
    17    Tab tekrar açılışında fresh GET (_opsLoaded.numuneler reset)

DB: Tüm servis testleri temporary SQLite üzerinde; canonical app/mock_data.db kullanılmaz.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

SVC = Path(__file__).resolve().parents[2] / 'app'
TMPL = SVC / 'templates' / 'nexgen' / 'cari360_kart.html'

_CARI_A = 1
_CARI_B = 2
_UID = 1
_YK = {'*'}

# Fixture sabitleri — deterministik sentetik kayıtlar
_NT_TASLAK = 101
_NT_LEGACY = 102
_NT_MODERN = 103
_NT_NO_ARGE = 104
_NT_MULTI_SIP = 105
_NT_INACTIVE = 199
_NT_OTHER_CARI = 201

_ARGE_LEGACY = 301
_ARGE_MODERN = 302

_SIP_A = 401
_SIP_B = 402
_SIP_NO_A = 'PZM-PAR-0401'
_SIP_NO_B = 'PZM-PAR-0402'


def _build_temp_db() -> tuple[sqlite3.Connection, tempfile.TemporaryDirectory]:
    """Minimal schema + sentetik numune/AR-GE/sipariş fixture."""
    tmpdir = tempfile.TemporaryDirectory(prefix='cps_num_parity_')
    db_path = Path(tmpdir.name) / 'test_numune.db'
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        PRAGMA journal_mode=WAL;

        CREATE TABLE sistem_kullanici (
            Id INTEGER PRIMARY KEY,
            KullaniciAdi TEXT,
            AdSoyad TEXT,
            RolId INTEGER,
            Aktif INTEGER DEFAULT 1
        );
        INSERT INTO sistem_kullanici (Id, KullaniciAdi, AdSoyad, RolId, Aktif) VALUES
            (1, 'admin', 'Admin User', NULL, 1),
            (2, 'tester', 'Test Kullanıcı', NULL, 1);

        CREATE TABLE nexgen_cari (
            id INTEGER PRIMARY KEY,
            cari_kod TEXT,
            unvan TEXT,
            aktif INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        );
        INSERT INTO nexgen_cari (id, cari_kod, unvan, aktif) VALUES
            (1, 'PAR-A', 'Parity Cari A', 1),
            (2, 'PAR-B', 'Parity Cari B', 1);

        CREATE TABLE nexgen_numune_talep (
            id INTEGER PRIMARY KEY,
            talep_kodu TEXT,
            cari_id INTEGER,
            olusturma_tarihi TEXT,
            guncelleme_tarihi TEXT,
            urun_tipi TEXT,
            urun_adi TEXT,
            renk_kodu TEXT,
            yeni_renk_aciklama TEXT,
            renk_tipi TEXT,
            talep_nedeni TEXT,
            talep_kaynagi TEXT,
            karsilama_yolu TEXT,
            durum TEXT,
            aktif INTEGER DEFAULT 1,
            rf_renk_id INTEGER,
            arge_test_id INTEGER,
            talep_eden_kullanici_id INTEGER,
            mo_gorusme_id INTEGER,
            vedat_sonuc TEXT,
            vedat_numune_miktari REAL,
            numune_adedi INTEGER
        );

        -- 11 aktif kayıt cari A (pagination); 1 pasif; 1 cari B
        INSERT INTO nexgen_numune_talep VALUES
        (101,'AT-P-0101',1,'2026-08-01 10:00:00','2026-08-11 10:00:00','Terlik','Model-A','RF-101',NULL,'MEVCUT','Standart','PZM','HAZIR_RENK','TASLAK',1,NULL,NULL,2,NULL,NULL,NULL,3),
        (102,'AT-P-0102',1,'2026-08-02 10:00:00','2026-08-12 10:00:00','Terlik','Model-B','RF-102',NULL,'MEVCUT','Standart','PZM','HAZIR_RENK','CALISILIYOR',1,NULL,301,2,NULL,NULL,NULL,5),
        (103,'AT-P-0103',1,'2026-08-03 10:00:00','2026-08-13 10:00:00','Terlik','Model-C','RF-103',NULL,'MEVCUT','Standart','PZM','HAZIR_RENK','ONAYLANDI',1,NULL,302,2,NULL,NULL,NULL,7),
        (104,'AT-P-0104',1,'2026-08-04 10:00:00','2026-08-14 10:00:00','Terlik','Model-D',NULL,'Yeni Mavi','YENI','Standart','PZM','YENI_RENK','REDDEDILDI',1,NULL,NULL,2,NULL,NULL,NULL,2),
        (105,'AT-P-0105',1,'2026-08-05 10:00:00','2026-08-15 10:00:00','Terlik','Model-E','RF-105',NULL,'MEVCUT','Standart','PZM','HAZIR_RENK','CALISILIYOR',1,NULL,NULL,2,NULL,NULL,NULL,4),
        (106,'AT-P-0106',1,'2026-08-06 10:00:00','2026-08-16 10:00:00','Terlik','F-06',NULL,NULL,NULL,NULL,NULL,NULL,'CALISILIYOR',1,NULL,NULL,NULL,NULL,NULL,NULL,1),
        (107,'AT-P-0107',1,'2026-08-07 10:00:00','2026-08-17 10:00:00','Terlik','F-07',NULL,NULL,NULL,NULL,NULL,NULL,'ONAYLANDI',1,NULL,NULL,NULL,NULL,NULL,NULL,1),
        (108,'AT-P-0108',1,'2026-08-08 10:00:00','2026-08-18 10:00:00','Terlik','F-08',NULL,NULL,NULL,NULL,NULL,NULL,'TASLAK',1,NULL,NULL,NULL,NULL,NULL,NULL,1),
        (109,'AT-P-0109',1,'2026-08-09 10:00:00','2026-08-19 10:00:00','Terlik','F-09',NULL,NULL,NULL,NULL,NULL,NULL,'REDDEDILDI',1,NULL,NULL,NULL,NULL,NULL,NULL,1),
        (110,'AT-P-0110',1,'2026-08-10 10:00:00','2026-08-20 10:00:00','Terlik','F-10',NULL,NULL,NULL,NULL,NULL,NULL,'CALISILIYOR',1,NULL,NULL,NULL,NULL,NULL,NULL,1),
        (111,'AT-P-0111',1,'2026-08-11 10:00:00','2026-08-21 10:00:00','Terlik','F-11',NULL,NULL,NULL,NULL,NULL,NULL,'ONAYLANDI',1,NULL,NULL,NULL,NULL,NULL,NULL,1),
        (199,'AT-P-0199',1,'2026-08-12 10:00:00','2026-08-22 10:00:00','Terlik','Pasif',NULL,NULL,NULL,NULL,NULL,NULL,'CALISILIYOR',0,NULL,NULL,NULL,NULL,NULL,NULL,1),
        (201,'AT-P-0201',2,'2026-08-13 10:00:00','2026-08-23 10:00:00','Terlik','Other-Cari',NULL,NULL,NULL,NULL,NULL,NULL,'ONAYLANDI',1,NULL,NULL,NULL,NULL,NULL,NULL,1);

        CREATE TABLE nexgen_arge_test (
            id INTEGER PRIMARY KEY,
            arge_kodu TEXT,
            test_no TEXT,
            durum TEXT,
            aktif INTEGER DEFAULT 1,
            calisma_tipi TEXT,
            olusturma_tarihi TEXT,
            rf_renk_id INTEGER,
            talep_referansi TEXT,
            cari_id INTEGER,
            renk_kodu TEXT,
            yeni_renk_adi TEXT,
            formul_grup_adi TEXT,
            ana_formul_grup_kodu TEXT,
            numune_talep_id INTEGER
        );
        INSERT INTO nexgen_arge_test VALUES
        (301,NULL,'AT-P-0102','ARGE_HAZIR',1,'MUSTERI_RENK','2026-08-02',NULL,'AT-P-0102',1,'RF-102',NULL,'1BA','1BA',102),
        (302,'NX-AR-0001','AT-P-0103','ARGE_HAZIR',1,'MUSTERI_RENK','2026-08-03',NULL,'AT-P-0103',1,'RF-103',NULL,'2BA','2BA',103);

        CREATE TABLE nexgen_planlama_siparis (
            id INTEGER PRIMARY KEY,
            siparis_no TEXT,
            cari_id INTEGER,
            durum TEXT,
            olusturma_tarihi TEXT
        );
        INSERT INTO nexgen_planlama_siparis (id, siparis_no, cari_id, durum, olusturma_tarihi) VALUES
            (401, 'PZM-PAR-0401', 1, 'ONAYLANDI', '2026-08-05'),
            (402, 'PZM-PAR-0402', 1, 'ONAYLANDI', '2026-08-05');

        CREATE TABLE nexgen_planlama_siparis_kalem (
            id INTEGER PRIMARY KEY,
            planlama_siparis_id INTEGER,
            numune_talep_id INTEGER
        );
        INSERT INTO nexgen_planlama_siparis_kalem (id, planlama_siparis_id, numune_talep_id) VALUES
            (501, 401, 105),
            (502, 402, 105),
            (503, 401, 105);
        """
    )
    con.commit()
    return con, tmpdir


def _load(con: sqlite3.Connection, **kw):
    if str(SVC) not in sys.path:
        sys.path.insert(0, str(SVC))
    from modules.nexgen.cari360_ops_read_service import load_cari360_numuneler

    return load_cari360_numuneler(con, _CARI_A, _UID, _YK, **kw)


def _by_id(data: dict, nid: int) -> dict:
    for item in data['liste']:
        if int(item['id']) == nid:
            return item
    raise AssertionError(f'numune id={nid} listede yok')


class NumuneParityServiceTests(unittest.TestCase):
    """Backend kontratları 1–13, 18–20 — izole temp DB."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.con, cls.tmpdir = _build_temp_db()
        cls.all_data = _load(cls.con, page=1, page_size=50)
        cls.page1 = _load(cls.con, page=1, page_size=5)
        cls.page2 = _load(cls.con, page=2, page_size=5)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.con.close()
        cls.tmpdir.cleanup()

    # ── 1. Cari filtresi ────────────────────────────────────────────────

    def test_01_cari_filtresi(self) -> None:
        ids = {int(x['id']) for x in self.all_data['liste']}
        self.assertNotIn(_NT_OTHER_CARI, ids)
        self.assertIn(_NT_TASLAK, ids)
        if str(SVC) not in sys.path:
            sys.path.insert(0, str(SVC))
        from modules.nexgen.cari360_ops_read_service import load_cari360_numuneler

        cari_b = load_cari360_numuneler(self.con, _CARI_B, _UID, _YK, page=1, page_size=50)
        self.assertEqual([int(x['id']) for x in cari_b['liste']], [_NT_OTHER_CARI])

    # ── 2–3. aktif filtresi ─────────────────────────────────────────────

    def test_02_aktif_kayitlar_listelenir(self) -> None:
        self.assertEqual(self.all_data['total_count'], 11)
        self.assertEqual(self.all_data['count'], 11)

    def test_03_pasif_kayit_listelenmez(self) -> None:
        ids = {int(x['id']) for x in self.all_data['liste']}
        self.assertNotIn(_NT_INACTIVE, ids)

    # ── 4–5. Durumlar dönüştürülmez ─────────────────────────────────────

    def test_04_durumlar_kendi_haliyle(self) -> None:
        beklenen = {
            _NT_TASLAK: 'TASLAK',
            _NT_LEGACY: 'CALISILIYOR',
            _NT_MODERN: 'ONAYLANDI',
            _NT_NO_ARGE: 'REDDEDILDI',
        }
        for nid, durum in beklenen.items():
            self.assertEqual(_by_id(self.all_data, nid)['durum'], durum)

    def test_05_durum_backend_transform_yok(self) -> None:
        row = self.con.execute(
            'SELECT durum FROM nexgen_numune_talep WHERE id=?', (_NT_TASLAK,)
        ).fetchone()
        self.assertEqual(_by_id(self.all_data, _NT_TASLAK)['durum'], row['durum'])

    # ── 6–11. Alan doğruluğu ────────────────────────────────────────────

    def test_06_numune_no(self) -> None:
        self.assertEqual(_by_id(self.all_data, _NT_TASLAK)['talep_kodu'], 'AT-P-0101')

    def test_07_talep_tarihi(self) -> None:
        self.assertEqual(_by_id(self.all_data, _NT_TASLAK)['tarih'], '2026-08-01 10:00')

    def test_08_urun_model(self) -> None:
        item = _by_id(self.all_data, _NT_TASLAK)
        self.assertEqual(item['urun_tipi'], 'Terlik')
        self.assertEqual(item['urun_adi'], 'Model-A')

    def test_09_renk(self) -> None:
        self.assertEqual(_by_id(self.all_data, _NT_TASLAK)['renk'], 'RF-101')
        self.assertEqual(_by_id(self.all_data, _NT_NO_ARGE)['renk'], 'Yeni Mavi')

    def test_10_miktar_adet(self) -> None:
        self.assertEqual(_by_id(self.all_data, _NT_TASLAK)['numune_adedi'], 3)

    def test_11_talep_eden(self) -> None:
        self.assertEqual(_by_id(self.all_data, _NT_TASLAK)['talep_eden'], 'Test Kullanıcı')

    # ── 12. Pagination ──────────────────────────────────────────────────

    def test_12_pagination_kontrat(self) -> None:
        d = self.page1
        self.assertEqual(d['total_count'], 11)
        self.assertEqual(d['page'], 1)
        self.assertEqual(d['page_size'], 5)
        self.assertEqual(d['total_pages'], 3)
        self.assertEqual(len(d['liste']), 5)

    def test_12b_limit_offset_sayfa2(self) -> None:
        p1_ids = {int(x['id']) for x in self.page1['liste']}
        p2_ids = {int(x['id']) for x in self.page2['liste']}
        self.assertFalse(p1_ids & p2_ids)
        self.assertEqual(len(p2_ids), 5)

    # ── 13. Sipariş bağlantıları ────────────────────────────────────────

    def test_13_coklu_siparis_eksiksiz(self) -> None:
        item = _by_id(self.all_data, _NT_MULTI_SIP)
        sip = item['bagli_siparisler']
        self.assertEqual(item['bagli_siparis_sayisi'], 2)
        nos = sorted(s['siparis_no'] for s in sip)
        self.assertEqual(nos, [_SIP_NO_A, _SIP_NO_B])

    def test_13b_siparis_id_eslesme(self) -> None:
        item = _by_id(self.all_data, _NT_MULTI_SIP)
        by_no = {s['siparis_no']: int(s['id']) for s in item['bagli_siparisler']}
        self.assertEqual(by_no[_SIP_NO_A], _SIP_A)
        self.assertEqual(by_no[_SIP_NO_B], _SIP_B)

    def test_13c_siparis_duplicate_yok(self) -> None:
        item = _by_id(self.all_data, _NT_MULTI_SIP)
        ids = [int(s['id']) for s in item['bagli_siparisler']]
        self.assertEqual(len(ids), len(set(ids)))

    # ── 14–15. AR-GE API enrichment ───────────────────────────────────

    def test_14_modern_arge_api(self) -> None:
        ar = _by_id(self.all_data, _NT_MODERN)['aktif_arge_testi']
        self.assertIsNotNone(ar)
        self.assertEqual(ar['arge_kodu'], 'NX-AR-0001')
        self.assertEqual(ar['durum'], 'ARGE_HAZIR')

    def test_15_legacy_arge_api(self) -> None:
        ar = _by_id(self.all_data, _NT_LEGACY)['aktif_arge_testi']
        self.assertIsNotNone(ar)
        self.assertIsNone(ar['arge_kodu'])
        self.assertEqual(ar['test_no'], 'AT-P-0102')
        self.assertEqual(ar['durum'], 'ARGE_HAZIR')

    def test_15b_arge_yok(self) -> None:
        self.assertIsNone(_by_id(self.all_data, _NT_NO_ARGE)['aktif_arge_testi'])

    # ── 18. API sayfalama kontratı ────────────────────────────────────

    def test_18_api_zorunlu_alanlar(self) -> None:
        for alan in ('liste', 'count', 'page', 'page_size', 'total_count', 'total_pages', 'ozet'):
            self.assertIn(alan, self.all_data)

    # ── 19. Mükerrer satır yok ──────────────────────────────────────────

    def test_19_liste_mukerrer_yok(self) -> None:
        ids = [int(x['id']) for x in self.all_data['liste']]
        self.assertEqual(len(ids), len(set(ids)))

    # ── 20. Enrichment ana satırı kaybettirmez ──────────────────────────

    def test_20_enrichment_ana_satir_korunur(self) -> None:
        for nid in (_NT_LEGACY, _NT_MODERN, _NT_MULTI_SIP):
            item = _by_id(self.all_data, nid)
            self.assertIn('talep_kodu', item)
            self.assertIn('durum', item)
            self.assertIsNotNone(item['talep_kodu'])
            self.assertIsNotNone(item['durum'])


class NumuneParityTemplateTests(unittest.TestCase):
    """Template kontratları 14–17 — statik HTML."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = TMPL.read_text(encoding='utf-8')
        start = cls.src.index('function _numDetayHtml(n)')
        end = cls.src.index('function _numunePaginationRender', start)
        cls.detay = cls.src[start:end]

    def test_14_modern_nx_ar_link_render(self) -> None:
        self.assertIn("_argeKod.indexOf('NX-AR-') === 0", self.detay)
        self.assertIn("href=\"/nexgen/arge/nx-ar/' + esc(String(arge.id))", self.detay)

    def test_15_legacy_duz_metin_link_yok(self) -> None:
        self.assertIn(': esc(_argeLabel);', self.detay)
        self.assertNotIn(
            "+ '<a class=\"ckart-link\" href=\"/nexgen/arge/nx-ar/' + esc(String(arge.id)) + '\">' + esc(_argeLabel) + ' ↗</a>'\n        + '</span></div>';",
            self.detay,
        )

    def test_16_arge_yok_em_dash(self) -> None:
        self.assertIn("esc('—')", self.detay)

    def test_17_tab_refresh_fresh_get(self) -> None:
        self.assertIn('_opsLoaded.numuneler = false', self.src)
        self.assertIn("if (_opsLoaded.numuneler && !force) return;", self.src)
        self.assertIn("if (tab === 'numuneler') { _opsLoaded.numuneler = false; ckartNumuneYukle(true); }", self.src)

    def test_17b_numune_api_url_pagination(self) -> None:
        self.assertIn("CARI_ID + '/numuneler?page=' + _numunePage + '&page_size=' + _numunePageSize", self.src)


if __name__ == '__main__':
    unittest.main()
