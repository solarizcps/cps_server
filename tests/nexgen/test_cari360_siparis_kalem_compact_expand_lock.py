# -*- coding: utf-8 -*-
"""C360 Sipariş Geçmişi — kompakt kalem expand UI LOCK."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / 'app' / 'templates' / 'nexgen' / 'cari360_kart.html'


class Cari360SiparisKalemCompactExpandLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = TEMPLATE.read_text(encoding='utf-8')

    def test_a_default_collapsed_all_kalemler(self) -> None:
        """Tüm kalem satırları ilk yüklemede gizli."""
        self.assertIn('class="ckart-siparis-kalem-row" style="display:none"', self.src)
        self.assertNotRegex(
            self.src,
            r"kalemler\.length\s*===\s*1\s*\?\s*'true'\s*:\s*'false'",
            msg='tek kalem auto-expand kaldırılmalı',
        )
        self.assertNotRegex(
            self.src,
            r"kalemler\.length\s*===\s*1\s*\?\s*''\s*:\s*'\s*style=\"display:none\"'",
            msg='tek kalem auto-show kaldırılmalı',
        )

    def test_b_disclosure_aria_default_false(self) -> None:
        self.assertIn('aria-expanded="false"', self.src)
        self.assertIn('function ckartSipDisclosureIcon', self.src)
        self.assertIn('ckartSipDisclosureIcon(false)', self.src)

    def test_c_disclosure_in_siparis_no_not_kalem_column(self) -> None:
        self.assertIn('class="ckart-sip-disclosure"', self.src)
        self.assertIn('ckart-kalem-count', self.src)
        self.assertNotIn('ckart-kalem-toggle', self.src)
        block = self.src[self.src.index('var disclosureBtn'):self.src.index('var kalemCell')]
        self.assertIn('ckart-sip-disclosure', block)
        kalem_block = self.src[self.src.index('var kalemCell'):self.src.index('var sipNoCell')]
        self.assertNotIn('ckart-sip-disclosure', kalem_block)

    def test_d_kalem_detail_subtable_structure(self) -> None:
        for marker in (
            'ckart-kalem-detail-wrap',
            'ckart-kalem-detail-hdr',
            'ckart-kalem-detail-tablo',
            'ckart-kalem-detail-ftr',
            'function ckartKalemDetailTableHtml',
            'function ckartPlanLinkHtml',
            'function ckartKalemDetailFooterHtml',
        ):
            self.assertIn(marker, self.src, msg=f'missing {marker}')
        self.assertNotIn('ckart-kalem-compakt-hdr', self.src)
        self.assertIn('ckart-sip-expand-panels', self.src)
        self.assertIn('ckart-sip-expand-row1', self.src)
        self.assertIn('ckart-sip-expand-row2', self.src)
        self.assertIn('function ckartSiparisBilgiHtml', self.src)
        hdr = self.src[self.src.index('ckart-kalem-detail-tablo"><thead><tr>'):self.src.index('</tr></thead><tbody>')]
        self.assertIn('<th>Ürün Tipi</th>', hdr)
        self.assertIn('<th>Formül</th>', hdr)
        self.assertIn('<th>Müşteri Rengi</th>', hdr)
        self.assertIn('<th>Üretim Rengi</th>', hdr)
        self.assertIn('<th>Tutar</th>', hdr)
        self.assertNotIn('<th>Termin</th>', hdr)
        self.assertNotIn('<th>Renk</th>', hdr)
        self.assertNotIn('<th>Sevk Tarihi</th>', hdr)
        self.assertNotIn('<th>Fatura</th>', hdr)
        self.assertNotIn('<th>Ürün Ailesi</th>', hdr)
        self.assertNotIn('<th>RF</th>', hdr)
        self.assertNotIn('MTT Kalem</th>', hdr)
        self.assertNotIn('Net Satır TRY</th>', hdr)
        self.assertEqual(hdr.count('<th>'), 7, msg='kalem detay 8 ana kolon (1i style ile)')
        self.assertIn('<th style="width:24px">#</th>', hdr)
        self.assertIn('ck-kalem-meta-row', self.src)
        # Termin meta satırda olmalı
        meta_fn = self.src[self.src.index('function ckartKalemDetailTableHtml'):]
        meta_fn = meta_fn[:meta_fn.index('window.ckartSiparisYukle')]
        self.assertIn("'Termin'", meta_fn)

    def test_e_kalem_fields_preserved_in_render(self) -> None:
        block = self.src[self.src.index('function ckartKdvDurumuLabel'):]
        block = block[:block.index('window.ckartSiparisYukle')]
        for field in (
            'plan_kodu', 'uretim_plan_id', 'formul_ad', 'renk_ad',
            'urun_ailesi', 'musteri_rengi', 'uretim_rengi', 'kalem_notu',
            'miktar_kg', 'birim_fiyat', 'termin_tarihi', 'satir_tutari',
            'sevk_tarihi', 'kdv_durumu', 'son_sevkiyat_tarihi', 'toplam_tutar', 'toplam_tutar_try',
            'pazarlamaci', 'genel_not', 'teslim_sekli', 'siparis_onceligi',
        ):
            self.assertIn(field, block, msg=f'missing kalem field {field}')
        table_fn = self.src[self.src.index('function ckartKalemDetailTableHtml'):]
        table_fn = table_fn[:table_fn.index('window.ckartSiparisYukle')]
        self.assertIn('urun_ailesi', table_fn)
        self.assertIn('musteri_rengi', table_fn)
        self.assertIn('uretim_rengi', table_fn)
        self.assertIn('kalem_notu', table_fn)
        self.assertNotIn('mtt_kalem_id', table_fn)
        self.assertNotIn('rf_label', table_fn)
        self.assertNotIn('satir_tutari_try', table_fn)
        self.assertNotIn('ckartKalemFormulCellHtml', table_fn)

    def test_f_disclosure_open_close_handler(self) -> None:
        self.assertIn('btn.textContent = ckartSipDisclosureIcon(!open)', self.src)
        self.assertIn("row.style.display = open ? 'none' : ''", self.src)
        self.assertIn('.ckart-sip-disclosure', self.src)

    def test_g_siparis_durum_and_odeme_badges(self) -> None:
        self.assertIn('function ckartSiparisDurumBadge', self.src)
        self.assertIn('function ckartOdemeBadge', self.src)
        self.assertIn('ckart-sip-durum-badge', self.src)
        self.assertIn('ckart-odeme-cek', self.src)

    def test_h_eleven_columns_preserved(self) -> None:
        self.assertIn("'<th style=\"text-align:right\">İşlem</th>'", self.src)
        head_block = self.src[self.src.index('if (ticari)'):self.src.index('} else {', self.src.index('if (ticari)'))]
        # ticari modda: Sipariş No, Sipariş Tarihi, Durum, Ödeme, Vade, PB, Toplam, Fiyat, Termin, Kalem = 10 <th> + 1 style th = 11 toplam
        self.assertEqual(head_block.count('<th>'), 10)
        self.assertIn('text-align:right', head_block)
        # kaldırılan kolonlar
        self.assertNotIn("'TRY'", head_block)
        self.assertNotIn("'Plan'", head_block)
        self.assertNotIn("'Batch'", head_block)
        self.assertNotIn("'Üretilen KG'", head_block)
        self.assertNotIn("'Numune'", head_block)
        self.assertNotIn("'Son Sevkiyat'", head_block)
        self.assertNotIn("'Sevk KG'", head_block)

    def test_i_old_large_kalem_card_removed(self) -> None:
        self.assertNotIn('ckart-kalem-kart-header', self.src)
        self.assertNotIn('ckart-kalem-kart-body', self.src)
        self.assertNotIn('function ckartKalemCompaktHtml', self.src)

    def test_j_rm_color_tokens_used(self) -> None:
        siparis_css = self.src[self.src.index('C360 Sipariş'):self.src.index('.ckart-tablo { width:')]
        self.assertIn('#006a8e', siparis_css)
        self.assertIn('#16a34a', siparis_css)
        self.assertIn('#f1f5f9', siparis_css)
        self.assertIn('#e2e8f0', siparis_css)

    def test_k_data_target_siparis_relation(self) -> None:
        self.assertRegex(
            self.src,
            r"var sipRowId = 'ckart-sip-' \+ esc\(s\.id",
        )
        self.assertIn("data-target=\"' + sipRowId + '\"", self.src)
        self.assertIn("id=\"' + sipRowId + '\"", self.src)

    def test_l_ticari_ozet_panel_kaldirildi(self) -> None:
        """C360-UX-REV2: Ticari Özet paneli tamamen kaldırıldı."""
        # Panel HTML yok
        self.assertNotIn('id="ckart-ticari-ozet"', self.src)
        self.assertNotIn('Ticari Özet</h3>', self.src)
        self.assertNotIn('ckart-ticari-baslik', self.src)
        # Panel içindeki Ticari Özet label'ları yok (ticari-satir span'ları)
        self.assertNotIn('"lbl">Son Sipariş<', self.src)
        self.assertNotIn('"lbl">Sipariş Dağılımı<', self.src)
        self.assertNotIn('"lbl">Ödeme Dağılımı<', self.src)
        self.assertNotIn('"lbl">Ortalama Vade<', self.src)
        # Backend bağımlılıklar korunuyor
        self.assertIn('function ckartOdemeDagilimiHtml', self.src)
        self.assertIn('legacy_odeme_yok_adet', self.src)
        # API çağrısı korunuyor (Son Alış Fiyatı için)
        self.assertIn('ticari-ozet', self.src)
        self.assertIn('ckartTicariOzetYukle', self.src)
        # Son Alış Fiyatı kartı korunuyor
        self.assertIn('ckart-son-alis-kart', self.src)
        self.assertIn('urun_fiyatlari', self.src)

    def test_m_siparis_section_title(self) -> None:
        self.assertIn('ckart-siparis-section-hdr', self.src)
        self.assertIn('ckart-siparis-section-title', self.src)

    def test_n_plan_link_canonical_route(self) -> None:
        self.assertIn('/nexgen/uretim-emirleri?vurgu=', self.src)
        self.assertIn('k.uretim_plan_id', self.src)
        self.assertIn('sevk_tarihi', self.src)
        self.assertIn('kdv_durumu', self.src)
        self.assertIn('function ckartKdvDurumuLabel', self.src)
        self.assertIn('Toplam Tutar', self.src)
        self.assertIn('TRY Karşılığı', self.src)

    def test_o_ana_fiyat_helpers(self) -> None:
        """C360-SIPARIS-ANA-SATIR-FIYAT-LOCK: ana satır fiyat presentation."""
        # Yardımcı fonksiyonlar mevcut
        self.assertIn('function ckartAnaFiyat', self.src)
        self.assertIn('function ckartFmtDate', self.src)
        self.assertIn('function ckartFmtBinlik', self.src)
        # net_birim_fiyat öncelikli
        self.assertIn('net_birim_fiyat', self.src)
        self.assertIn('birim_fiyat', self.src)
        # Çoklu fiyat durumu
        self.assertIn('Çoklu', self.src)
        # Tarih dönüşüm pattern
        self.assertIn('DD.MM.YYYY', self.src)
        # fiyat_durumu artık FİYAT kolonunda değil (ana satır)
        self.assertIn('ckartAnaFiyat(s)', self.src)
        self.assertNotIn("ckartTicariKaynakEtiket(s.fiyat_durumu)", self.src)
        # Toplam + TRY formatlanmış
        self.assertIn('formatDecimalTrim(s.toplam_tutar)', self.src)
        self.assertIn('ckartFmtBinlik(s.toplam_tutar_try)', self.src)
        # layout
        self.assertIn('max-width: 100%', self.src)

    def test_p_son_alis_kart_son_vade(self) -> None:
        """Son Alış kartında Son Vade her zaman görünür."""
        self.assertIn('ckart-son-alis-kart', self.src)
        self.assertIn('Son Vade: —', self.src)
        self.assertIn('Son Vade: Nakit', self.src)
        self.assertIn('Son Vade:', self.src)
        # vade her zaman set ediliyor (null guard yok)
        self.assertIn('if (elVade) elVade.textContent = vadeStr', self.src)


if __name__ == '__main__':
    unittest.main()
