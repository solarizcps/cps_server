"""
TAHSİLAT DRAFT SİPARİŞ + VADE HYDRATE — Lock Tests v3
=======================================================
Kontrat (tek fetch / tek hydrate / tek preview):
  - window.hydrateTahsilatDraft: tek public giriş noktası
  - hydrateTahsilatDraft(kayitId, _ctx) — _ctx.siparisNo draftOpt label için
  - mpHydrateCekSatirlar: yalnız DOM doldurur — preview/timer yok
  - runFinalHydratePreview → mpTriggerCekPreviewSession(session)
  - tahsilatPreviewSession: stale preview response engeli
  - updateTahsilatCekUi({ skipPreview, skipBaglam }) hydrate sırasında
  - _tahDuzSiparisNo global YOK — siparisNo local context ile taşınır
  - Tek fetch: window.hydrateTahsilatDraft → hydrateTahsilatDraft — ikinci fetch yok
  - Çek satırları afterSevkHydrate sonrası, preview en sonda tek kez
  - Plan/sevkiyat async response çekleri temizleyemez
  - Yeni kayıt akışında draft-only option eklenmez

28 statik + servis kontrat testi.
"""
import sys
import re
import sqlite3
import unittest

sys.path.insert(0, "app")

_SRC = None


def _src():
    global _SRC
    if _SRC is None:
        with open("app/templates/nexgen/musteri_pazarlama.html", encoding="utf-8") as f:
            _SRC = f.read()
    return _SRC


# ---------------------------------------------------------------------------
# DDL — temp DB fixture
# ---------------------------------------------------------------------------
_DDL = """
CREATE TABLE IF NOT EXISTS nexgen_cari (id INTEGER PRIMARY KEY, unvan TEXT);
CREATE TABLE IF NOT EXISTS nexgen_planlama_siparis (
    id INTEGER PRIMARY KEY, siparis_no TEXT, cari_id INTEGER,
    durum TEXT, tahsilat_kurali TEXT, odeme_tipi TEXT
);
CREATE TABLE IF NOT EXISTS mo_musteri_sevkiyat (
    id INTEGER PRIMARY KEY, sevkiyat_no TEXT, siparis_id INTEGER, aktif INTEGER DEFAULT 1, sevk_tarihi TEXT
);
CREATE TABLE IF NOT EXISTS mo_tahsilat_kayit (
    id INTEGER PRIMARY KEY, kayit_kodu TEXT, cari_id INTEGER,
    siparis_id INTEGER, sevkiyat_id INTEGER, odeme_tipi TEXT DEFAULT 'NAKIT',
    para_birimi TEXT DEFAULT 'TRY', paket_hedef_tutar REAL, beklenen_tutar REAL,
    alinan_tutar REAL DEFAULT 0, kalan_tutar REAL, durum TEXT DEFAULT 'TASLAK',
    aktif INTEGER DEFAULT 1, olusturma_tarihi TEXT DEFAULT '2026-01-01T00:00:00',
    tcmb_satis_kur_snapshot REAL, hedef_vade_tarihi TEXT,
    onaylanan_vade_gun_snapshot INTEGER, gercek_sevk_tarihi_snapshot TEXT,
    kaynak_modul TEXT
);
CREATE TABLE IF NOT EXISTS nexgen_musteri_cari_sorumlu (
    id INTEGER PRIMARY KEY, cari_id INTEGER, kullanici_id INTEGER, aktif INTEGER DEFAULT 1
);
"""


def _make_db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(_DDL)
    con.execute("INSERT INTO nexgen_cari VALUES (11, 'NEZİH AYAKKABI')")
    con.execute("ALTER TABLE nexgen_planlama_siparis ADD COLUMN cari_unvan TEXT")
    con.execute("INSERT INTO nexgen_planlama_siparis(id,siparis_no,cari_id,durum,tahsilat_kurali,odeme_tipi,cari_unvan) VALUES (760,'PZM-2026-0222',11,'TAMAMLANDI',NULL,'CEK','NEZİH')")
    con.execute("INSERT INTO nexgen_planlama_siparis(id,siparis_no,cari_id,durum,tahsilat_kurali,odeme_tipi,cari_unvan) VALUES (19,'NSP-2026-00019',11,'TALEP','serbest','NAKIT','NEZİH')")
    con.execute("INSERT INTO mo_musteri_sevkiyat VALUES (228,'MSV-2026-0166',760,1,'2026-08-10')")
    con.execute("""INSERT INTO mo_tahsilat_kayit
        (id,kayit_kodu,cari_id,siparis_id,sevkiyat_id,odeme_tipi,para_birimi,
         paket_hedef_tutar,beklenen_tutar,alinan_tutar,kalan_tutar,durum,aktif,olusturma_tarihi,
         tcmb_satis_kur_snapshot,hedef_vade_tarihi,onaylanan_vade_gun_snapshot,gercek_sevk_tarihi_snapshot)
        VALUES (180,'MO-T-2026-0078',11,760,228,'CEK','TRY',
                189000,NULL,100000,89000,'TASLAK',1,'2026-08-01T10:00:00',
                47.25,'2027-02-11',185,'2026-08-10')""")
    con.execute("INSERT INTO nexgen_musteri_cari_sorumlu VALUES (1,11,1,1)")
    con.commit()
    return con


def _hydrate_body():
    """hydrateTahsilatDraft fonksiyon gövdesi."""
    src = _src()
    start = src.find("function hydrateTahsilatDraft(")
    # Tek canonical fonksiyon — window.hydrateTahsilatDraft = satırına kadar
    end = src.find("window.hydrateTahsilatDraft = hydrateTahsilatDraft", start)
    return src[start:end] if end > start else src[start:start + 5000]


# ---------------------------------------------------------------------------
# STATIK (JS/HTML template) TESTLERİ
# ---------------------------------------------------------------------------

class TestSinglePublicEntryPoint(unittest.TestCase):
    """TEST 1-3: Tek canonical giriş noktası kontratı"""

    # TEST 1
    def test_01_window_hydrate_expose_edildi(self):
        """window.hydrateTahsilatDraft = hydrateTahsilatDraft satırı var — tek expose."""
        src = _src()
        self.assertIn("window.hydrateTahsilatDraft = hydrateTahsilatDraft", src)

    # TEST 2
    def test_02_cift_fetch_yok(self):
        """IIFE wrapper ikinci /tahsilat-kayit/ fetch YAPMIYOR — tek fetch garantisi.
        IIFE artık yalnız mpHydrateCekSatirlar publish eder."""
        src = _src()
        # Eski double-fetch wrapper'ı: "_origHydrate" simgesi artık olmamalı
        self.assertNotIn("_origHydrate", src)
        # Eski window.hydrateTahsilatDraft = function(kayitId) { ... _origHydrate wrapper yok
        self.assertNotIn("if (_origHydrate)", src)

    # TEST 3
    def test_03_ctx_siparis_no_kullanilir(self):
        """hydrateTahsilatDraft _ctx.siparisNo draftOpt label için kullanır."""
        body = _hydrate_body()
        self.assertIn("_ctx.siparisNo", body)
        self.assertIn("draftLabel", body)


class TestNoCekFetchInWrapper(unittest.TestCase):
    """TEST 4-5: mpHydrateCekSatirlar yayını"""

    # TEST 4
    def test_04_mp_hydrate_cek_satirlar_publish_edildi(self):
        """window.mpHydrateCekSatirlar IIFE tarafından publish edildi."""
        src = _src()
        self.assertIn("window.mpHydrateCekSatirlar", src)

    # TEST 5
    def test_05_addcekrow_iife_icerisinde(self):
        """addCekRow çağrısı mpHydrateCekSatirlar fonksiyon gövdesinde — tek hydrate yeri."""
        src = _src()
        # Fonksiyon tanımı satırını bul (= function(satirlar...) {)
        idx = src.find("window.mpHydrateCekSatirlar = function")
        # IIFE bloğunun sonu: })(); satırına kadar
        end = src.find("})();", idx)
        block = src[idx:end + 5] if end > idx else src[idx:idx + 1500]
        self.assertIn("addCekRow", block)


class TestDraftSiparisOption(unittest.TestCase):
    """TEST 6-9: Draft sipariş option ekleme kontratı"""

    # TEST 6
    def test_06_draft_option_eklenir_kodu_var(self):
        """hydrateTahsilatDraft: sipariş option yoksa draftOpt oluşturma kodu var."""
        body = _hydrate_body()
        self.assertIn("draftOpt", body)
        self.assertIn("draftOnly", body)

    # TEST 7
    def test_07_select_value_set_edilir(self):
        """sipSel.value hydrate içinde siparis_id ile set edilir."""
        body = _hydrate_body()
        self.assertIn("sipSel.value = sipId", body)

    # TEST 8
    def test_08_draft_option_data_plan_var(self):
        """draftOpt.dataset.plan — vade snapshot JSON'u taşır."""
        body = _hydrate_body()
        self.assertIn("draftOpt.dataset.plan", body)
        self.assertIn("onaylanan_vade_gun_snapshot", body)

    # TEST 9
    def test_09_draft_option_data_draft_only(self):
        """draftOpt.dataset.draftOnly = '1' — yeni kayıt akışından izole."""
        body = _hydrate_body()
        self.assertIn("draftOnly", body)


class TestGlobalStateKaldirildi(unittest.TestCase):
    """TEST 10-11: _tahDuzSiparisNo global state kaldırıldı"""

    # TEST 10
    def test_10_tah_duz_siparis_no_global_yok(self):
        """_tahDuzSiparisNo global değişkeni artık tanımlı değil."""
        src = _src()
        # var _tahDuzSiparisNo satırı olmamalı
        self.assertNotIn("var _tahDuzSiparisNo", src)

    # TEST 11
    def test_11_duz_handler_window_hydrate_cagiriyor(self):
        """Düzenle handler window.hydrateTahsilatDraft çağırıyor — local fonksiyon değil."""
        src = _src()
        # Düzenle event delegation handler bloğunu bul
        idx = src.find("mp-tah-liste-duz-btn")
        # Düzenle handler'ı için JS bloğunu bul — closest('.mp-tah-liste-duz-btn')
        handler_idx = src.find("closest('.mp-tah-liste-duz-btn')", idx)
        if handler_idx == -1:
            handler_idx = src.find('closest(".mp-tah-liste-duz-btn")', idx)
        # Handler bloğu — 1500 char yeterli
        block = src[handler_idx:handler_idx + 1500]
        self.assertIn("window.hydrateTahsilatDraft", block)


class TestVadeSnapshot(unittest.TestCase):
    """TEST 12-13: Vade snapshot hydrate kontratı"""

    # TEST 12
    def test_12_vade_snapshot_kullanilir(self):
        """Vade UI boşsa onaylanan_vade_gun_snapshot ile doldurulur."""
        body = _hydrate_body()
        self.assertIn("onaylanan_vade_gun_snapshot", body)
        self.assertIn("gün", body)

    # TEST 13
    def test_13_hedef_vade_snapshot_kullanilir(self):
        """hedef_vade_tarihi snapshot UI'a yazılır."""
        body = _hydrate_body()
        self.assertIn("hedef_vade_tarihi", body)
        self.assertIn("mp-t-hedef-vade-tarihi", body)


class TestEligibilityPreserved(unittest.TestCase):
    """TEST 14: Yeni kayıt akışında draft-only option eklenmez"""

    # TEST 14
    def test_14_draft_option_yalniz_hydrate_icerisinde(self):
        """draftOpt createElement kodu hydrateTahsilatDraft içinde, resetTahsilatModal dışında."""
        src = _src()
        body = _hydrate_body()
        self.assertIn("draftOpt", body)
        reset_start = src.find("function resetTahsilatModal(")
        reset_end = src.find("\n  function ", reset_start + 1)
        reset_body = src[reset_start:reset_end]
        self.assertNotIn("draftOpt", reset_body)


class TestServiceContract(unittest.TestCase):
    """TEST 15-18: Servis katmanı read-only kontratları"""

    def setUp(self):
        self.con = _make_db()

    def tearDown(self):
        self.con.close()

    # TEST 15
    def test_15_kayit_detay_snapshot_alanlari(self):
        """kayit_detay(180) onaylanan_vade_gun_snapshot + hedef_vade_tarihi döndürür."""
        from modules.nexgen.mo_tahsilat_kayit_service import kayit_detay
        import modules.nexgen.mo_gorusme_service as _gor
        orig = _gor.can_mo_gorusme_yaz
        _gor.can_mo_gorusme_yaz = lambda *a, **kw: True
        try:
            d = kayit_detay(self.con, 180, kullanici_id=1, yk={'*'})
        finally:
            _gor.can_mo_gorusme_yaz = orig
        self.assertEqual(d['onaylanan_vade_gun_snapshot'], 185)
        self.assertEqual(d['hedef_vade_tarihi'], '2027-02-11')
        self.assertEqual(d['gercek_sevk_tarihi_snapshot'], '2026-08-10')

    # TEST 16
    def test_16_kayit_detay_siparis_id(self):
        """kayit_detay(180) siparis_id=760 döndürür."""
        from modules.nexgen.mo_tahsilat_kayit_service import kayit_detay
        import modules.nexgen.mo_gorusme_service as _gor
        orig = _gor.can_mo_gorusme_yaz
        _gor.can_mo_gorusme_yaz = lambda *a, **kw: True
        try:
            d = kayit_detay(self.con, 180, kullanici_id=1, yk={'*'})
        finally:
            _gor.can_mo_gorusme_yaz = orig
        self.assertEqual(d['siparis_id'], 760)

    # TEST 17
    def test_17_kur_ve_hedef_snapshot_korunur(self):
        """tcmb_satis_kur_snapshot=47.25, paket_hedef=189k, alinan=100k, kalan=89k."""
        from modules.nexgen.mo_tahsilat_kayit_service import kayit_detay
        import modules.nexgen.mo_gorusme_service as _gor
        orig = _gor.can_mo_gorusme_yaz
        _gor.can_mo_gorusme_yaz = lambda *a, **kw: True
        try:
            d = kayit_detay(self.con, 180, kullanici_id=1, yk={'*'})
        finally:
            _gor.can_mo_gorusme_yaz = orig
        self.assertEqual(d['tcmb_satis_kur_snapshot'], 47.25)
        self.assertEqual(d['paket_hedef_tutar'], 189000.0)
        self.assertEqual(d['alinan_tutar'], 100000.0)
        self.assertEqual(d['kalan_tutar'], 89000.0)

    # TEST 18
    def test_18_eligibility_kontrat(self):
        """Kontrat: draftOpt ekleme mantığı yalnız hydrateTahsilatDraft içinde — resetTahsilatModal değil."""
        src = _src()
        body = _hydrate_body()
        self.assertIn("if (!sipOpt)", body)
        self.assertIn("draftOpt", body)
        reset_start = src.find("function resetTahsilatModal(")
        reset_end = src.find("\n  function ", reset_start + 1)
        reset_body = src[reset_start:reset_end]
        self.assertNotIn("draftOpt", reset_body)


class TestSinglePreviewContract(unittest.TestCase):
    """TEST 19-28: Tek preview / preview susturma kontratı"""

    # TEST 19
    def test_19_mp_hydrate_no_trigger_preview(self):
        """mpHydrateCekSatirlar içinde triggerPreview çağrısı yok."""
        src = _src()
        idx = src.find("window.mpHydrateCekSatirlar = function")
        end = src.find("};", idx + 100)
        block = src[idx:end + 2]
        self.assertNotIn("triggerPreview()", block)

    # TEST 20
    def test_20_mp_hydrate_no_settimeout_400(self):
        """mpHydrateCekSatirlar yapay 400ms bekleme kullanmıyor."""
        src = _src()
        idx = src.find("window.mpHydrateCekSatirlar = function")
        end = src.find("};", idx + 100)
        block = src[idx:end + 2]
        self.assertNotIn("setTimeout(resolve, 400)", block)

    # TEST 21
    def test_21_mp_hydrate_skip_preview_ui(self):
        """mpHydrateCekSatirlar updateTahsilatCekUi skipPreview ile çağırır."""
        src = _src()
        idx = src.find("window.mpHydrateCekSatirlar = function")
        end = src.find("};", idx + 100)
        block = src[idx:end + 2]
        self.assertIn("skipPreview: true", block)
        self.assertIn("skipBaglam: true", block)

    # TEST 22
    def test_22_update_cek_ui_skip_preview_option(self):
        """updateTahsilatCekUi opts.skipPreview ile preview susturulabilir."""
        src = _src()
        idx = src.find("function updateTahsilatCekUi(")
        end = src.find("\n  function validateTahsilatCekSubmit", idx)
        block = src[idx:end]
        self.assertIn("opts.skipPreview", block)
        self.assertIn("opts.skipBaglam", block)

    # TEST 23
    def test_23_preview_session_var(self):
        """tahsilatPreviewSession tanımlı — stale preview engeli."""
        src = _src()
        self.assertIn("var tahsilatPreviewSession = 0", src)

    # TEST 24
    def test_24_preview_session_guard_in_trigger(self):
        """triggerPreview session guard: myPreviewSession !== tahsilatPreviewSession."""
        src = _src()
        idx = src.find("function triggerPreview(previewSession)")
        end = src.find("window.mpTriggerCekPreview = function", idx)
        block = src[idx:end]
        self.assertIn("myPreviewSession !== tahsilatPreviewSession", block)

    # TEST 25
    def test_25_final_preview_session_exposed(self):
        """window.mpTriggerCekPreviewSession hydrate final preview için expose edildi."""
        src = _src()
        self.assertIn("window.mpTriggerCekPreviewSession = function", src)

    # TEST 26
    def test_26_hydrate_final_preview_once(self):
        """hydrateTahsilatDraft runFinalHydratePreview ile tek final preview çağırır."""
        body = _hydrate_body()
        self.assertIn("runFinalHydratePreview", body)
        self.assertIn("mpTriggerCekPreviewSession", body)
        self.assertNotIn("cekHydratePromise", body)

    # TEST 27
    def test_27_cek_satirlari_after_aftersevk(self):
        """Çek satırları afterSevkHydrate sonrası hydrateCekSatirlari ile doldurulur."""
        body = _hydrate_body()
        after_idx = body.find("afterSevkHydrate(k)")
        cek_idx = body.find("hydrateCekSatirlari(k)")
        self.assertGreater(cek_idx, after_idx, "hydrateCekSatirlari afterSevkHydrate sonrasında olmalı")

    # TEST 28
    def test_28_draft_option_label_from_ctx_when_exists(self):
        """Mevcut sipOpt varsa ctxSipNo ile label güncellenir."""
        body = _hydrate_body()
        self.assertIn("else if (ctxSipNo)", body)
        self.assertIn("sipOpt.textContent = draftLabel", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
