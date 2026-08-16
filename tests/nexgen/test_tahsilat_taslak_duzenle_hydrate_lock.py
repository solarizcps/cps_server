"""
TAHSİLAT TASLAK DÜZENLE HYDRATE — Lock Tests
=============================================
Kontrat:
  - TASLAK satırında Düzenle butonu görünür
  - Düzenle tıklandığında sayfa navigation OLMAZ
  - Liste modal kapanır, tahsilat modal açılır
  - hydrateTahsilatDraft(id) çağrılır
  - Numeric olmayan id reddedilir
  - Çift tıklama koruması (_tahDuzInProgress) var
  - Hata durumunda toast çıkar
  - Yönetim ?t_revizyon page-load akışı dokunulmamış
  - resetTahsilatModal skipPlanLoad seçeneği var
  - Manuel kur / context reset lock korunmuş
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


class TestDuzenleButton(unittest.TestCase):
    """TEST 1-3: Düzenle buton görünürlük + element tipi"""

    # TEST 1
    def test_01_taslak_duz_btn_gorunu(self):
        """TASLAK satırında Düzenle butonu üretilir."""
        src = _src()
        self.assertIn("mp-tah-liste-duz-btn", src)
        self.assertIn("Düzenle", src)

    # TEST 2
    def test_02_btn_type_button(self):
        """Düzenle elementi type='button' (link değil, navigation yok)."""
        src = _src()
        # type="button" class="mp-tah-liste-duz-btn" kombinasyonu
        self.assertIn('type="button"', src)
        idx = src.find("mp-tah-liste-duz-btn")
        # type="button" duzBtn üretiminde bulunmalı
        snippet = src[max(0, idx - 100): idx + 200]
        self.assertIn('type="button"', snippet)

    # TEST 3
    def test_03_duz_btn_no_href(self):
        """Düzenle butonu href içermez (anchor link değil)."""
        src = _src()
        idx = src.find("mp-tah-liste-duz-btn")
        snippet = src[max(0, idx - 50): idx + 300]
        self.assertNotIn("t_revizyon", snippet)
        self.assertNotIn("href=", snippet)


class TestClickHandler(unittest.TestCase):
    """TEST 4-10: delegated click handler kontratları"""

    def _handler_body(self):
        src = _src()
        m = re.search(
            r"Düzenle butonu.*?event delegation.*?document\.addEventListener\('click'.*?\}\);",
            src,
            re.DOTALL,
        )
        if not m:
            # Alternatif: satır bazlı bul
            idx = src.find("_tahDuzInProgress")
            return src[max(0, idx - 200): idx + 1500] if idx >= 0 else ""
        return m.group(0)

    # TEST 4
    def test_04_prevent_default(self):
        """Click handler e.preventDefault() çağırır."""
        src = _src()
        body = self._handler_body()
        self.assertIn("preventDefault", body)

    # TEST 5
    def test_05_stop_propagation(self):
        """Click handler e.stopPropagation() çağırır (bubble engeli)."""
        body = self._handler_body()
        self.assertIn("stopPropagation", body)

    # TEST 6
    def test_06_no_url_change(self):
        """Handler içinde window.location veya history.push YOK (liste duz handler)."""
        body = self._handler_body()
        self.assertNotIn("window.location", body)
        self.assertNotIn("history.push", body)
        self.assertNotIn("location.href", body)

    # TEST 7
    def test_07_close_liste_called(self):
        """Handler closeTahsilatListesi() çağırır."""
        body = self._handler_body()
        self.assertIn("closeTahsilatListesi", body)

    # TEST 8
    def test_08_tahsilat_modal_acilir(self):
        """Handler tahsilat modalını açar (modals.tahsilat.hidden=false)."""
        src = _src()
        # handler bloğunu daha geniş al — _tahDuzInProgress tanımından itibaren
        idx = src.find("_tahDuzInProgress")
        body = src[max(0, idx - 200): idx + 2000]
        self.assertIn("modals.tahsilat", body)
        self.assertIn("hidden = false", body)

    # TEST 9
    def test_09_hydrate_called(self):
        """Handler hydrateTahsilatDraft(kayitId) çağırır."""
        body = self._handler_body()
        self.assertIn("hydrateTahsilatDraft", body)
        self.assertIn("kayitId", body)

    # TEST 10
    def test_10_numeric_guard(self):
        """Numeric olmayan id reddedilir (isNaN veya parseInt guard)."""
        body = self._handler_body()
        self.assertTrue(
            "isNaN(kayitId)" in body or "parseInt" in body,
            "Numeric guard bulunamadı"
        )


class TestDoubleClickAndError(unittest.TestCase):
    """TEST 10-11: çift tıklama + hata toast"""

    # TEST 10 (kontrat sırası: 10 = çift tıklama)
    def test_10_double_click_guard(self):
        """_tahDuzInProgress değişkeni çift tıklama için kullanılır."""
        src = _src()
        self.assertIn("_tahDuzInProgress", src)
        # Handler içinde hem set hem check bulunmalı
        idx = src.find("_tahDuzInProgress")
        body = src[idx: idx + 1200]
        self.assertIn("_tahDuzInProgress = true", body)
        self.assertIn("_tahDuzInProgress = false", body)

    # TEST 11
    def test_11_hydrate_hata_toast(self):
        """Hydrate hata durumunda toast çağrılır."""
        src = _src()
        idx = src.find("_tahDuzInProgress")
        body = src[idx: idx + 2500]
        self.assertIn("toast(", body)
        self.assertIn("yüklenemedi", body)


class TestRevizyonPageLoadPreserved(unittest.TestCase):
    """TEST 12: ?t_revizyon page-load akışı korunmuş"""

    # TEST 12
    def test_12_t_revizyon_pageload_korunmus(self):
        """`?t_revizyon` Jinja bloğu ve page-load hydrate hâlâ template'de."""
        src = _src()
        self.assertIn("t_revizyon_id", src)
        # Jinja if bloğu
        self.assertIn("{% if t_revizyon_id %}", src)

    def test_12b_skipplanload_secenegi_var(self):
        """resetTahsilatModal skipPlanLoad seçeneğini destekler."""
        src = _src()
        self.assertIn("skipPlanLoad", src)
        self.assertIn("_opts.skipPlanLoad", src)


class TestExistingLocksPreserved(unittest.TestCase):
    """TEST 13-14: mevcut lock testlerinin bağımlı olduğu kontratlar"""

    # TEST 13
    def test_13_manuel_kur_context_reset_korunmus(self):
        """clearTahsilatFinancialContext + tahsilatModalSession hâlâ var."""
        src = _src()
        self.assertIn("clearTahsilatFinancialContext", src)
        self.assertIn("tahsilatModalSession", src)
        self.assertIn("tahsilatPlanAbort", src)

    # TEST 14
    def test_14_reset_modal_signature_backward_compat(self):
        """resetTahsilatModal imzası geri uyumlu (eski çağrılar bozulmadı)."""
        src = _src()
        # Eski çağrı biçimi: resetTahsilatModal(cariId, planCtx) — _opts opsiyonel
        m = re.search(r"function resetTahsilatModal\(([^)]+)\)", src)
        self.assertIsNotNone(m, "resetTahsilatModal tanımı bulunamadı")
        params = m.group(1)
        self.assertIn("cariId", params)
        self.assertIn("planCtx", params)
        # Üçüncü param _opts — opsiyonel (default {} atanmış olmalı)
        self.assertIn("_opts = _opts || {}", src)


class TestSecondOpenFix(unittest.TestCase):
    """TEST 15-16: İkinci açılış kontratı — style.display reset + Promise lock release"""

    def _handler_body(self):
        src = _src()
        idx = src.find("_tahDuzInProgress")
        return src[max(0, idx - 200):idx + 2500] if idx >= 0 else ""

    # TEST 15
    def test_15_style_display_reset_on_open(self):
        """Düzenle handler modal açarken style.display='' set eder.
        closeModal style.display='none' yapar — sıfırlanmadan ikinci açılış görünmez."""
        body = self._handler_body()
        # style.display = '' set edilmeli — hidden=false tek başına yetmez
        self.assertIn("style.display = ''", body)

    # TEST 16
    def test_16_lock_release_via_promise_not_timer(self):
        """_tahDuzInProgress Promise finally/then ile serbest bırakılır — setTimeout değil.
        setTimeout 600ms ile serbest bırakma kaldırıldı; erken lock release engellendi."""
        body = self._handler_body()
        # _releaseDuzLock: Promise then/catch ile çağrılır
        self.assertIn("_releaseDuzLock", body)
        self.assertIn(".then(_releaseDuzLock", body)
        # Eski: setTimeout(...600) artık olmamalı
        self.assertNotIn("setTimeout(function() { _tahDuzInProgress = false; }, 600)", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
