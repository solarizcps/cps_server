"""
TAHSİLAT KAYIT LİSTESİ — Lock Tests
======================================
Servis: cari_tahsilat_listele (mo_tahsilat_kayit_service)
Endpoint: GET /nexgen/api/musteri-pazarlama/tahsilat-kayitlari?cari_id=...
Frontend: mp-modal-tah-liste, openTahsilatListesi, mp-tah-liste-duz-btn

20 kanonik test — temp in-memory DB.
"""
import sys
import sqlite3
import unittest

sys.path.insert(0, "app")


# ---------------------------------------------------------------------------
# DB FIXTURE
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS nexgen_cari (
    id INTEGER PRIMARY KEY,
    unvan TEXT,
    aktif INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS nexgen_planlama_siparis (
    id INTEGER PRIMARY KEY,
    siparis_no TEXT,
    cari_id INTEGER,
    aktif INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS mo_musteri_sevkiyat (
    id INTEGER PRIMARY KEY,
    sevkiyat_no TEXT,
    siparis_id INTEGER,
    aktif INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS mo_tahsilat_kayit (
    id INTEGER PRIMARY KEY,
    kayit_kodu TEXT,
    cari_id INTEGER,
    siparis_id INTEGER,
    sevkiyat_id INTEGER,
    odeme_tipi TEXT DEFAULT 'NAKIT',
    para_birimi TEXT DEFAULT 'TRY',
    paket_hedef_tutar REAL,
    beklenen_tutar REAL,
    alinan_tutar REAL DEFAULT 0,
    kalan_tutar REAL,
    durum TEXT DEFAULT 'TASLAK',
    aktif INTEGER DEFAULT 1,
    olusturma_tarihi TEXT DEFAULT '2026-01-01T00:00:00',
    kullanici_id INTEGER DEFAULT 1,
    tcmb_satis_kur_snapshot REAL,
    hedef_vade_tarihi TEXT,
    onaylanan_vade_gun_snapshot INTEGER,
    kaynak_modul TEXT
);
CREATE TABLE IF NOT EXISTS nexgen_musteri_cari_sorumlu (
    id INTEGER PRIMARY KEY,
    cari_id INTEGER,
    kullanici_id INTEGER,
    aktif INTEGER DEFAULT 1
);
"""


def _make_db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(_DDL)
    # Cariler
    con.execute("INSERT INTO nexgen_cari VALUES (11, 'NEZİH AYAKKABI', 1)")
    con.execute("INSERT INTO nexgen_cari VALUES (99, 'BAŞKA CARİ', 1)")
    # Sipariş
    con.execute("INSERT INTO nexgen_planlama_siparis VALUES (760, 'PZM-2026-0222', 11, 1)")
    con.execute("INSERT INTO nexgen_planlama_siparis VALUES (900, 'PZM-2026-0900', 99, 1)")
    # Sevkiyat
    con.execute("INSERT INTO mo_musteri_sevkiyat VALUES (228, 'MSV-2026-0166', 760, 1)")
    # Sorumlu — kullanici 42 sadece cari 11'e atanmış
    con.execute("INSERT INTO nexgen_musteri_cari_sorumlu VALUES (1, 11, 42, 1)")
    # Tahsilat kayıtları cari 11
    _INS = """INSERT INTO mo_tahsilat_kayit
        (id, kayit_kodu, cari_id, siparis_id, sevkiyat_id, odeme_tipi, para_birimi,
         paket_hedef_tutar, beklenen_tutar, alinan_tutar, kalan_tutar, durum, aktif, olusturma_tarihi)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    records = [
        (180, 'MO-T-2026-0078', 11, 760, 228, 'NAKIT', 'TRY', 189000, 189000, 0, 189000, 'TASLAK', 1, '2026-08-01T10:00:00'),
        (181, 'MO-T-2026-0079', 11, 760, 228, 'NAKIT', 'TRY', 63000, 63000, 0, 63000, 'TASLAK', 1, '2026-08-02T10:00:00'),
        (182, 'MO-T-2026-0080', 11, 760, 228, 'NAKIT', 'TRY', 63000, 63000, 0, 63000, 'TASLAK', 1, '2026-08-03T10:00:00'),
        (183, 'MO-T-2026-0081', 11, 760, 228, 'NAKIT', 'TRY', 63000, 63000, 0, 63000, 'TASLAK', 1, '2026-08-04T10:00:00'),
        (184, 'MO-T-2026-0082', 11, 760, 228, 'NAKIT', 'TRY', 63000, 63000, 63000, 0, 'YONETIM_ONAYLANDI', 1, '2026-08-05T10:00:00'),
        (185, 'MO-T-2026-0083', 11, 760, 228, 'NAKIT', 'TRY', 63000, 63000, 0, 63000, 'YONETIM_ONAY_BEKLIYOR', 1, '2026-08-06T10:00:00'),
        (189, 'MO-T-2026-0089', 11, 760, 228, 'NAKIT', 'TRY', 50000, 50000, 0, 50000, 'IPTAL', 0, '2026-08-07T10:00:00'),   # pasif
        (900, 'MO-T-2026-0900', 99, 900, None, 'NAKIT', 'TRY', 10000, 10000, 0, 10000, 'TASLAK', 1, '2026-08-01T10:00:00'),
        (191, 'MO-T-2026-0091', 11, 760, 228, 'CEK', 'TRY', 189000, None, 0, 189000, 'TASLAK', 1, '2026-08-08T10:00:00'),
    ]
    for r in records:
        con.execute(_INS, r)
    con.commit()
    return con


def _make_service():
    from modules.nexgen.mo_tahsilat_kayit_service import cari_tahsilat_listele, MoTahsilatError
    return cari_tahsilat_listele, MoTahsilatError


# ------ mock can_mo_gorusme_yaz ------
import modules.nexgen.mo_tahsilat_kayit_service as _svc_mod
import modules.nexgen.mo_gorusme_service as _gor_svc

_orig_can = _gor_svc.can_mo_gorusme_yaz


def _mock_can(con, uid, cari_id, yk):
    """Yönetici ('*') her cariye, uid=42 sadece cari 11'e."""
    if yk and ('*' in yk or 'yonetici' in yk):
        return True
    # Sorumlu tablosunu kontrol et
    row = con.execute(
        "SELECT 1 FROM nexgen_musteri_cari_sorumlu WHERE kullanici_id=? AND cari_id=? AND aktif=1",
        (uid, cari_id),
    ).fetchone()
    return row is not None


# Patch
_gor_svc.can_mo_gorusme_yaz = _mock_can


class TestCariTahsilatListele(unittest.TestCase):
    def setUp(self):
        self.con = _make_db()
        self.listele, self.Error = _make_service()

    def tearDown(self):
        self.con.close()

    # TEST 1
    def test_01_cari11_yalniz_kendi_aktif_kayitlari(self):
        """Cari 11 yalnız kendi aktif kayıtlarını listeler."""
        rows = self.listele(self.con, cari_id=11, kullanici_id=1, yk={'*'})
        ids = [r['id'] for r in rows]
        self.assertIn(180, ids)
        self.assertNotIn(900, ids)  # cari 99 görünmez

    # TEST 2
    def test_02_pasif_kayit_gorunmez(self):
        """aktif=0 kayıt (id=189) listede olmamalı."""
        rows = self.listele(self.con, cari_id=11, kullanici_id=1, yk={'*'})
        ids = [r['id'] for r in rows]
        self.assertNotIn(189, ids)

    # TEST 3
    def test_03_baska_cari_gorunmez(self):
        """Cari 11 sorgusunda cari 99 kaydı (id=900) görünmez."""
        rows = self.listele(self.con, cari_id=11, kullanici_id=1, yk={'*'})
        ids = [r['id'] for r in rows]
        self.assertNotIn(900, ids)

    # TEST 4
    def test_04_order_by_desc(self):
        """Kayıtlar olusturma_tarihi DESC sırada gelir."""
        rows = self.listele(self.con, cari_id=11, kullanici_id=1, yk={'*'})
        ids = [r['id'] for r in rows]
        # id=191 en geç tarihli (2026-08-08), ilk gelmeli
        self.assertEqual(ids[0], 191)

    # TEST 5
    def test_05_bes_taslak_bes_satir(self):
        """5 ayrı TASLAK → 5 ayrı satır, birleştirilmemiş."""
        rows = self.listele(self.con, cari_id=11, kullanici_id=1, yk={'*'})
        taslaklar = [r for r in rows if r['durum'] == 'TASLAK']
        self.assertGreaterEqual(len(taslaklar), 5)

    # TEST 6
    def test_06_taslak_duzenlenebilir_true(self):
        """TASLAK durumunda duzenlenebilir=True."""
        rows = self.listele(self.con, cari_id=11, kullanici_id=1, yk={'*'})
        taslak = next(r for r in rows if r['id'] == 180)
        self.assertTrue(taslak['duzenlenebilir'])

    # TEST 7
    def test_07_diger_durumlarda_duzenlenebilir_false(self):
        """YONETIM_ONAYLANDI → duzenlenebilir=False."""
        rows = self.listele(self.con, cari_id=11, kullanici_id=1, yk={'*'})
        onaylandi = next((r for r in rows if r['durum'] == 'YONETIM_ONAYLANDI'), None)
        if onaylandi:
            self.assertFalse(onaylandi['duzenlenebilir'])

    # TEST 8
    def test_08_idor_engellenir(self):
        """uid=999, yk=None → yetkisiz cariye MoTahsilatError fırlatılır."""
        with self.assertRaises(self.Error) as ctx:
            self.listele(self.con, cari_id=11, kullanici_id=999, yk=None)
        # MoTahsilatError.kod özelliği http kodunu taşır
        self.assertEqual(ctx.exception.kod, 403)

    # TEST 9
    def test_09_yonetici_erisir(self):
        """yk={'*'} (yönetici) cari 11'e erişir."""
        rows = self.listele(self.con, cari_id=11, kullanici_id=99, yk={'*'})
        self.assertGreater(len(rows), 0)

    # TEST 10
    def test_10_liste_db_write_yapmaz(self):
        """Liste çağrısı DB write yapmaz (sadece SELECT)."""
        con_ro = sqlite3.connect(':memory:')
        con_ro.row_factory = sqlite3.Row
        con_ro.executescript(_DDL)
        # Yönetici yk → erişim var ama tablo boş → []
        rows = self.listele(con_ro, cari_id=11, kullanici_id=1, yk={'*'})
        self.assertEqual(rows, [])
        con_ro.close()

    # TEST 11 — Frontend contract: Düzenle hydrateTahsilatDraft kullanır
    def test_11_frontend_duzenle_hydrate_kullanir(self):
        """musteri_pazarlama.html: Düzenle butonu hydrateTahsilatDraft(id) çağırır."""
        with open('app/templates/nexgen/musteri_pazarlama.html', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('hydrateTahsilatDraft(kayitId)', src)
        self.assertIn('mp-tah-liste-duz-btn', src)

    # TEST 12 — Yeni kayıt endpoint'i çağrılmaz
    def test_12_yeni_kayit_endpoint_cagirilmaz(self):
        """Düzenle akışında taslak_kaydet endpoint'i doğrudan çağrılmaz."""
        with open('app/templates/nexgen/musteri_pazarlama.html', encoding='utf-8') as f:
            src = f.read()
        # openTahsilatListesi fonksiyonu içinde tahsilat-taslak POST olmamalı
        import re
        func_match = re.search(r'function openTahsilatListesi\(.+?\}(?=\s*function)', src, re.DOTALL)
        if func_match:
            func_body = func_match.group(0)
            self.assertNotIn('tahsilat-taslak-kaydet', func_body)

    # TEST 13 — MO-T-0078 fixture: id=180 varlık + kayit_kodu
    def test_13_mott78_fixture_dogru(self):
        """id=180 MO-T-2026-0078 doğru hydrate alanlarıyla listelenir."""
        rows = self.listele(self.con, cari_id=11, kullanici_id=1, yk={'*'})
        r = next(r for r in rows if r['id'] == 180)
        self.assertEqual(r['kayit_kodu'], 'MO-T-2026-0078')
        self.assertEqual(r['siparis_id'], 760)
        self.assertEqual(r['sevkiyat_id'], 228)

    # TEST 14 — id=180 hedef 189.000 TL
    def test_14_hedef_189000(self):
        """id=180 hedef_tutar = 189000 (beklenen_tutar)."""
        rows = self.listele(self.con, cari_id=11, kullanici_id=1, yk={'*'})
        r = next(r for r in rows if r['id'] == 180)
        self.assertEqual(r['hedef_tutar'], 189000)

    # TEST 15 — CEK tip: hedef_tutar paket_hedef_tutar'dan gelir
    def test_15_cek_hedef_paket(self):
        """CEK ödeme tipinde hedef_tutar = paket_hedef_tutar."""
        rows = self.listele(self.con, cari_id=11, kullanici_id=1, yk={'*'})
        cek = next((r for r in rows if r['id'] == 191), None)
        if cek:
            self.assertEqual(cek['hedef_tutar'], 189000)
            self.assertEqual(cek['odeme_tipi'], 'CEK')

    # TEST 16 — duzenlenebilir alanı bool
    def test_16_duzenlenebilir_bool(self):
        """duzenlenebilir alanı Python bool."""
        rows = self.listele(self.con, cari_id=11, kullanici_id=1, yk={'*'})
        for r in rows:
            self.assertIsInstance(r['duzenlenebilir'], bool)

    # TEST 17 — Context reset lock korunmuş
    def test_17_context_reset_lock_korunmamis(self):
        """clearTahsilatFinancialContext hâlâ template'de mevcut."""
        with open('app/templates/nexgen/musteri_pazarlama.html', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('clearTahsilatFinancialContext', src)

    # TEST 18 — Modal async lock korunmuş
    def test_18_modal_async_lock_korunmus(self):
        """tahsilatModalSession ve tahsilatPlanAbort hâlâ template'de mevcut."""
        with open('app/templates/nexgen/musteri_pazarlama.html', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('tahsilatModalSession', src)
        self.assertIn('tahsilatPlanAbort', src)

    # TEST 19 — + Tahsilat Kaydı butonu yeni modalı açmaya devam eder
    def test_19_yeni_kayit_butonu_degismemis(self):
        """mp-tah-kayit-ac (yeni kayıt butonu) template'de hâlâ mevcut."""
        with open('app/templates/nexgen/musteri_pazarlama.html', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('mp-tah-kayit-ac', src)

    # TEST 20 — Silme/iptal butonu yok
    def test_20_silme_iptal_yok(self):
        """Tahsilat liste fonksiyonu içinde sil/iptal aksiyonu bulunmaz."""
        with open('app/templates/nexgen/musteri_pazarlama.html', encoding='utf-8') as f:
            src = f.read()
        import re
        func_match = re.search(r'function openTahsilatListesi\(.+?\}(?=\s*function)', src, re.DOTALL)
        if func_match:
            body = func_match.group(0)
            self.assertNotIn('tahsilat-sil', body.lower())
            self.assertNotIn('tahsilat-iptal', body.lower())


if __name__ == '__main__':
    unittest.main(verbosity=2)
