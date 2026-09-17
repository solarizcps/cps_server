# -*- coding: utf-8 -*-
"""CUSTOMER_TABLE_COLUMN_FILTER_PARITY_WITH_SUPPLIER_V1 — test suite."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from typing import Any, Dict, List

_THIS = os.path.dirname(__file__)
_APP = os.path.normpath(os.path.join(_THIS, '..', '..', 'app'))
if _APP not in sys.path:
    sys.path.insert(0, _APP)


def _af():
    try:
        from modules.finans.read_model.rm_receivable_reader import _apply_customer_filters
    except ImportError:
        from app.modules.finans.read_model.rm_receivable_reader import _apply_customer_filters
    return _apply_customer_filters


def _today_iso():
    return date.today().isoformat()


def _days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


def _sample(n=4):
    today = _today_iso()
    days60 = _days_ago(60)
    days200 = _days_ago(200)
    return [
        # 0: acik alacak, tahsilat var (son 30), satis var, cek var, aktif takip
        {'cari_kod': '120.1', 'cari_adi': 'Ahmet', 'location': 'SA001', 'para_birimi': 'TRY',
         'net': '1000', 'borc': '1000', 'alacak': '0', 'bakiye_durumu': 'Açık Alacak',
         'son_odeme_tarih': _days_ago(20), 'son_alim_tarih': _days_ago(15),
         'portfoy_cek_cnt': 2, 'aktif_takip': True},
        # 1: fazla odeme, tahsilat yok, satis yok, cek yok, takip yok
        {'cari_kod': '120.2', 'cari_adi': 'Mehmet', 'location': 'SA001', 'para_birimi': 'TRY',
         'net': '-500', 'borc': '0', 'alacak': '500', 'bakiye_durumu': 'Müşteri Avansı',
         'son_odeme_tarih': None, 'son_alim_tarih': None,
         'portfoy_cek_cnt': 0, 'aktif_takip': False},
        # 2: sifir bakiye, tahsilat eski (60g), satis eski, cek yok
        {'cari_kod': '120.3', 'cari_adi': 'Zeynep', 'location': 'SA001', 'para_birimi': 'TRY',
         'net': '0', 'bakiye_durumu': 'Yok',
         'son_odeme_tarih': days60, 'son_alim_tarih': days60,
         'portfoy_cek_cnt': 0, 'aktif_takip': False},
        # 3: acik alacak, tahsilat cok eski (200g), satis cok eski, cek var, takip yok
        {'cari_kod': '120.4', 'cari_adi': 'Ali', 'location': 'SA001', 'para_birimi': 'TRY',
         'net': '2000', 'borc': '2000', 'alacak': '0', 'bakiye_durumu': 'Açık Alacak',
         'son_odeme_tarih': days200, 'son_alim_tarih': days200,
         'portfoy_cek_cnt': 1, 'aktif_takip': False},
    ]


class TestCustomerColumnFilters(unittest.TestCase):

    def _call(self, rows, **kwargs):
        return _af()(rows, bakiye_f=None, musteri_q=None, pb_filter=None, **kwargs)

    # 1. mf_bakiye=acik_alacak
    def test_01_mf_bakiye_acik_alacak(self):
        rows = _sample()
        result = self._call(rows, mf_bakiye='acik_alacak')
        codes = [r['cari_kod'] for r in result]
        self.assertIn('120.1', codes)
        self.assertIn('120.4', codes)
        self.assertNotIn('120.2', codes)
        self.assertNotIn('120.3', codes)

    # 2. mf_bakiye=fazla_odeme
    def test_02_mf_bakiye_fazla_odeme(self):
        rows = _sample()
        result = self._call(rows, mf_bakiye='fazla_odeme')
        codes = [r['cari_kod'] for r in result]
        self.assertIn('120.2', codes)
        self.assertNotIn('120.1', codes)

    # 3. mf_bakiye=sifir
    def test_03_mf_bakiye_sifir(self):
        rows = _sample()
        result = self._call(rows, mf_bakiye='sifir')
        codes = [r['cari_kod'] for r in result]
        self.assertIn('120.3', codes)
        self.assertNotIn('120.1', codes)

    # 4. mf_durum=aktif_takip
    def test_04_mf_durum_aktif_takip(self):
        rows = _sample()
        result = self._call(rows, mf_durum='aktif_takip')
        codes = [r['cari_kod'] for r in result]
        self.assertIn('120.1', codes)
        self.assertNotIn('120.2', codes)

    # 5. mf_tahsilat=var
    def test_05_mf_tahsilat_var(self):
        rows = _sample()
        result = self._call(rows, mf_tahsilat='var')
        codes = [r['cari_kod'] for r in result]
        # 120.1 (20g), 120.3 (60g), 120.4 (200g) — hepsinin son_odeme_tarih var
        self.assertIn('120.1', codes)
        self.assertNotIn('120.2', codes)  # tahsilat yok

    # 6. mf_tahsilat=yok
    def test_06_mf_tahsilat_yok(self):
        rows = _sample()
        result = self._call(rows, mf_tahsilat='yok')
        codes = [r['cari_kod'] for r in result]
        self.assertIn('120.2', codes)
        self.assertNotIn('120.1', codes)

    # 7. mf_tahsilat=son_30
    def test_07_mf_tahsilat_son_30(self):
        rows = _sample()
        result = self._call(rows, mf_tahsilat='son_30')
        codes = [r['cari_kod'] for r in result]
        self.assertIn('120.1', codes)  # 20 gün önce
        self.assertNotIn('120.4', codes)  # 200 gün önce

    # 8. mf_satis=var
    def test_08_mf_satis_var(self):
        rows = _sample()
        result = self._call(rows, mf_satis='var')
        codes = [r['cari_kod'] for r in result]
        self.assertIn('120.1', codes)
        self.assertNotIn('120.2', codes)

    # 9. mf_satis=yok
    def test_09_mf_satis_yok(self):
        rows = _sample()
        result = self._call(rows, mf_satis='yok')
        codes = [r['cari_kod'] for r in result]
        self.assertIn('120.2', codes)
        self.assertNotIn('120.1', codes)

    # 10. mf_cek=var
    def test_10_mf_cek_var(self):
        rows = _sample()
        result = self._call(rows, mf_cek='var')
        codes = [r['cari_kod'] for r in result]
        self.assertIn('120.1', codes)
        self.assertIn('120.4', codes)
        self.assertNotIn('120.2', codes)
        self.assertNotIn('120.3', codes)

    # 11. mf_cek=yok
    def test_11_mf_cek_yok(self):
        rows = _sample()
        result = self._call(rows, mf_cek='yok')
        codes = [r['cari_kod'] for r in result]
        self.assertIn('120.2', codes)
        self.assertIn('120.3', codes)
        self.assertNotIn('120.1', codes)

    # 12. mf_takip=aktif
    def test_12_mf_takip_aktif(self):
        rows = _sample()
        result = self._call(rows, mf_takip='aktif')
        codes = [r['cari_kod'] for r in result]
        self.assertIn('120.1', codes)
        self.assertNotIn('120.2', codes)

    # 13. mf_takip=pasif
    def test_13_mf_takip_pasif(self):
        rows = _sample()
        result = self._call(rows, mf_takip='pasif')
        codes = [r['cari_kod'] for r in result]
        self.assertNotIn('120.1', codes)
        self.assertIn('120.2', codes)

    # 14. mf_sort=adi_az
    def test_14_mf_sort_adi_az(self):
        rows = _sample()
        result = self._call(rows, mf_sort='adi_az')
        names = [r['cari_adi'] for r in result]
        self.assertEqual(names, sorted(names, key=str.lower))

    # 15. mf_sort=adi_za
    def test_15_mf_sort_adi_za(self):
        rows = _sample()
        result = self._call(rows, mf_sort='adi_za')
        names = [r['cari_adi'] for r in result]
        self.assertEqual(names, sorted(names, key=str.lower, reverse=True))

    # 16. mf_sort=bakiye_desc
    def test_16_mf_sort_bakiye_desc(self):
        rows = _sample()
        result = self._call(rows, mf_sort='bakiye_desc')
        # 120.4: |net|=2000, 120.1: 1000, ...
        self.assertEqual(result[0]['cari_kod'], '120.4')

    # 17. mf_sort=bakiye_asc
    def test_17_mf_sort_bakiye_asc(self):
        rows = _sample()
        result = self._call(rows, mf_sort='bakiye_asc')
        # 120.3: |net|=0 — en kucuk
        self.assertEqual(result[0]['cari_kod'], '120.3')

    # 18. iki kolon filtresi birlikte: mf_bakiye=acik_alacak + mf_cek=var
    def test_18_combined_two_col_filters(self):
        rows = _sample()
        result = self._call(rows, mf_bakiye='acik_alacak', mf_cek='var')
        codes = [r['cari_kod'] for r in result]
        self.assertIn('120.1', codes)
        self.assertIn('120.4', codes)
        self.assertNotIn('120.2', codes)
        self.assertNotIn('120.3', codes)

    # 19. kolon filtresi + bakiye_f birlikte
    def test_19_col_filter_plus_bakiye_f(self):
        rows = _sample()
        # bakiye_f=hareketli — 120.3 (net=0, aktif_takip=False) dislanir
        af = _af()
        result = af(rows, bakiye_f='hareketli', musteri_q=None, pb_filter=None, mf_cek='var')
        codes = [r['cari_kod'] for r in result]
        self.assertNotIn('120.3', codes)  # hareketsiz

    # 20. template'de op-fh-btn musteri tablosunda mevcut
    def test_20_template_has_mf_fh_buttons(self):
        tmpl_path = os.path.join(_APP, 'templates', 'finans', 'odeme_plani.html')
        with open(tmpl_path, encoding='utf-8') as f:
            content = f.read()
        for col in ('mf_cari', 'mf_bakiye', 'mf_durum', 'mf_tahsilat', 'mf_satis', 'mf_cek', 'mf_takip'):
            self.assertIn('data-fh-col="{}"'.format(col), content,
                          'data-fh-col="{}" bulunamadi'.format(col))

    # 21. template'de op-fh-pop musteri kolonlari mevcut
    def test_21_template_has_mf_fh_pops(self):
        tmpl_path = os.path.join(_APP, 'templates', 'finans', 'odeme_plani.html')
        with open(tmpl_path, encoding='utf-8') as f:
            content = f.read()
        for pop in ('mf_cari', 'mf_bakiye', 'mf_durum', 'mf_tahsilat', 'mf_satis', 'mf_cek', 'mf_takip'):
            self.assertIn('data-fh-pop="{}"'.format(pop), content,
                          'data-fh-pop="{}" bulunamadi'.format(pop))

    # 22. JS mState ve buildMusteriFilterUrl mevcut
    def test_22_js_mstate_present(self):
        tmpl_path = os.path.join(_APP, 'templates', 'finans', 'odeme_plani.html')
        with open(tmpl_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('mState', content)
        self.assertIn('buildMusteriFilterUrl', content)
        self.assertIn('opMusteriTable', content)

    # 23. routes.py mf_ parametrelerini reader'a iletiyor
    def test_23_routes_passes_mf_params(self):
        routes_path = os.path.join(_APP, 'modules', 'finans', 'routes.py')
        with open(routes_path, encoding='utf-8') as f:
            content = f.read()
        for param in ('mf_bakiye', 'mf_durum', 'mf_tahsilat', 'mf_satis', 'mf_cek', 'mf_takip', 'mf_sort'):
            self.assertIn(param, content, '{} routes.py icinde bulunamadi'.format(param))

    # 24. read_receivable_snapshot imzasinda mf_ parametreleri var
    def test_24_reader_signature_has_mf_params(self):
        reader_path = os.path.join(_APP, 'modules', 'finans', 'read_model', 'rm_receivable_reader.py')
        with open(reader_path, encoding='utf-8') as f:
            content = f.read()
        for p in ('mf_bakiye', 'mf_durum', 'mf_tahsilat', 'mf_satis', 'mf_cek', 'mf_takip', 'mf_sort'):
            self.assertIn(p, content)

    # 25. tedarikci op-fh-btn ve state hala mevcut (regression)
    def test_25_supplier_fh_regression(self):
        tmpl_path = os.path.join(_APP, 'templates', 'finans', 'odeme_plani.html')
        with open(tmpl_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('data-fh-col="tedarikci"', content)
        self.assertIn('data-fh-col="bakiye"', content)
        self.assertIn('data-fh-col="karar"', content)
        self.assertIn("var state = {", content)
        self.assertIn("fh_bakiye", content)
        self.assertIn("fh_karar", content)

    # 26. mf_satis=son_90 (90 gun icinde)
    def test_26_mf_satis_son_90(self):
        rows = _sample()
        result = self._call(rows, mf_satis='son_90')
        codes = [r['cari_kod'] for r in result]
        self.assertIn('120.1', codes)   # 15 gun oncesi
        self.assertIn('120.3', codes)   # 60 gun oncesi
        self.assertNotIn('120.4', codes)  # 200 gun oncesi

    # 27. op-fh-pop ESC kapama JS mevcut
    def test_27_js_escape_close_present(self):
        tmpl_path = os.path.join(_APP, 'templates', 'finans', 'odeme_plani.html')
        with open(tmpl_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn("'Escape'", content)
        self.assertIn("mClosePop", content)

    # 28. op-fh-pop position:fixed (overflow:auto parent'ı aşmak için)
    def test_28_css_fh_pop_fixed_position(self):
        css_path = os.path.join(_APP, 'templates', 'finans', '_odeme_plani_styles.inc.html')
        with open(css_path, encoding='utf-8') as f:
            content = f.read()
        # position: fixed olmalı (overflow:auto parent'ı kesmemeli)
        import re
        m = re.search(r'\.op-fh-pop\s*\{([^}]+)\}', content)
        self.assertIsNotNone(m, '.op-fh-pop CSS kuralı bulunamadı')
        rule = m.group(1)
        self.assertIn('fixed', rule, '.op-fh-pop position:fixed değil')

    # 29. JS popup fixed konumlandırma (getBoundingClientRect + style.top) mevcut
    def test_29_js_fixed_positioning_present(self):
        tmpl_path = os.path.join(_APP, 'templates', 'finans', 'odeme_plani.html')
        with open(tmpl_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('getBoundingClientRect', content)
        self.assertIn('btnRect.bottom', content)
        self.assertIn('btnRect.left', content)

    # 30. Template: "Müşteri Avansı" badge metni ve "Hesap Kapalı" mevcut
    def test_30_musteri_avans_label(self):
        tmpl_path = os.path.join(_APP, 'templates', 'finans', 'odeme_plani.html')
        with open(tmpl_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('Müşteri Avansı', content)
        self.assertIn('Hesap Kapalı', content)
        self.assertIn('Açık Alacak', content)

    # 31. CSS: müşteri badge sınıfları mevcut
    def test_31_css_musteri_badge_classes(self):
        css_path = os.path.join(_APP, 'templates', 'finans', '_odeme_plani_styles.inc.html')
        with open(css_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('op-musteri-borc', content)
        self.assertIn('op-musteri-avans', content)
        self.assertIn('op-musteri-kapali', content)

    # 32. Son tahsilat yöntem pill CSS sınıfları mevcut
    def test_32_css_tahsilat_yontem_pills(self):
        css_path = os.path.join(_APP, 'templates', 'finans', '_odeme_plani_styles.inc.html')
        with open(css_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('op-cell-type-nakit', content)
        self.assertIn('op-cell-type-havale', content)
        self.assertIn('op-cell-type-cek', content)

    # 33. Reader: son_tahsilat_yontem alanı mevcut
    def test_33_reader_son_tahsilat_yontem(self):
        reader_path = os.path.join(_APP, 'modules', 'finans', 'read_model', 'rm_receivable_reader.py')
        with open(reader_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('son_tahsilat_yontem', content)
        self.assertIn('fa_turu', content)

    # 34. Template: Detay butonu ve ••• butonu mevcut
    def test_34_template_detay_and_more_buttons(self):
        tmpl_path = os.path.join(_APP, 'templates', 'finans', 'odeme_plani.html')
        with open(tmpl_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('Detay', content)
        self.assertIn('•••', content)

    # 35. Template: net_val ile avans/borç/kapali ayrımı yapılıyor
    def test_35_net_val_bakiye_logic(self):
        tmpl_path = os.path.join(_APP, 'templates', 'finans', 'odeme_plani.html')
        with open(tmpl_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('net_val', content)
        self.assertIn('net_val < 0', content)
        self.assertIn('net_val > 0', content)

    # 36. _apply_customer_filters acik_alacak → net<0 olanlar
    def test_36_filter_net_logic(self):
        rows = _sample()
        result = self._call(rows, mf_bakiye='acik_alacak')
        for r in result:
            self.assertGreater(float(r['net']), 0)

    # 37. Son tahsilat yöntem normalize — template'de yon kontrolleri
    def test_37_tahsilat_yontem_template_logic(self):
        tmpl_path = os.path.join(_APP, 'templates', 'finans', 'odeme_plani.html')
        with open(tmpl_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn("'NAK' in yon", content)
        self.assertIn("'HAV' in yon", content)
        self.assertIn("'CEK' in yon", content)


if __name__ == '__main__':
    unittest.main(verbosity=2)
