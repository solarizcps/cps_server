# -*- coding: utf-8 -*-
"""Cari360 Görüşmeler — tam genişlik Görüşme Notu layout LOCK (C360-GOR-NOT-FULL-01)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / 'app' / 'templates' / 'nexgen' / 'cari360_kart.html'


def esc(s) -> str:
    return (
        str('' if s is None else s)
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )


def render_gorusme_not_block(g: dict) -> str:
    """Yalnız Görüşme Notu tam genişlik bloğu — _gorDetayHtml ile aynı kontrat."""
    gor_not = (g.get('kisa_not') or '').strip()
    if not gor_not:
        return ''
    return (
        '<div class="ckart-gor-not-full">'
        '<div class="ckart-gor-not-label">Görüşme Notu</div>'
        f'<div class="ckart-gor-not-value">{esc(g.get("kisa_not"))}</div>'
        '</div>'
    )


def extract_gor_detay_html_fn(src: str) -> str:
    m = re.search(r'function _gorDetayHtml\(g\)\s*\{', src)
    if not m:
        raise AssertionError('_gorDetayHtml bulunamadı')
    start = m.start()
    depth = 0
    i = src.find('{', start)
    for j in range(i, len(src)):
        if src[j] == '{':
            depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0:
                return src[start: j + 1]
    raise AssertionError('_gorDetayHtml kapanışı bulunamadı')


class Cari360GorusmeNotFullLayoutLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = TEMPLATE.read_text(encoding='utf-8')
        cls.fn = extract_gor_detay_html_fn(cls.src)

    def _css_block(self) -> str:
        m = re.search(
            r'/\* C360-GORUSME-NOT-FULL-01.*?\*/(.*?)(?=\.ckart-urt-progress-bar)',
            self.src,
            re.DOTALL,
        )
        self.assertIsNotNone(m, 'ckart-gor-not CSS bloğu yok')
        return m.group(1)

    def test_01_not_not_inside_a_group_field(self) -> None:
        a_block = re.search(
            r'A — Görüşme Bilgisi.*?(?=B — Ticari Bilgi)',
            self.fn,
            re.DOTALL,
        )
        self.assertIsNotNone(a_block)
        self.assertNotIn('Görüşme Notu', a_block.group(0))
        self.assertNotIn('ckart-gor-not-full', a_block.group(0))

    def test_02_not_after_abcd_groups(self) -> None:
        d_end = self.fn.find('D — Bağlantılar')
        self.assertGreater(d_end, 0)
        not_pos = self.fn.find('ckart-gor-not-full')
        self.assertGreater(not_pos, d_end)

    def test_03_full_width_class_present(self) -> None:
        self.assertIn('ckart-gor-not-full', self.fn)
        self.assertIn('ckart-gor-not-label', self.fn)
        self.assertIn('ckart-gor-not-value', self.fn)

    def test_04_css_grid_column_span(self) -> None:
        css = self._css_block()
        self.assertIn('grid-column: 1 / -1', css)

    def test_05_css_pre_wrap(self) -> None:
        self.assertIn('white-space: pre-wrap', self._css_block())

    def test_06_css_overflow_wrap_anywhere(self) -> None:
        self.assertIn('overflow-wrap: anywhere', self._css_block())

    def test_07_css_word_break(self) -> None:
        self.assertIn('word-break: break-word', self._css_block())

    def test_08_no_line_clamp(self) -> None:
        css = self._css_block()
        self.assertNotIn('line-clamp', css)
        self.assertNotIn('-webkit-line-clamp', css)

    def test_09_no_ellipsis(self) -> None:
        css = self._css_block()
        self.assertNotIn('text-overflow', css)
        self.assertNotIn('ellipsis', css)

    def test_10_no_max_height_or_hidden_scroll(self) -> None:
        css = self._css_block()
        self.assertNotIn('max-height', css)
        self.assertNotIn('overflow: hidden', css)
        self.assertNotIn('overflow-y: auto', css)
        self.assertNotIn('overflow-y: scroll', css)

    def test_11_esc_kisa_not_in_template(self) -> None:
        self.assertIn("esc(g.kisa_not)", self.fn)

    def test_12_xss_html_escaped(self) -> None:
        html = render_gorusme_not_block({'kisa_not': '<img onerror=alert(1)>'})
        self.assertIn('&lt;img', html)
        self.assertNotIn('<img onerror', html)

    def test_13_newlines_preserved_in_output(self) -> None:
        note = 'Satır1\nSatır2'
        html = render_gorusme_not_block({'kisa_not': note})
        self.assertIn('Satır1\nSatır2', html)

    def test_14_300_char_not_not_truncated(self) -> None:
        note = 'z' * 300
        html = render_gorusme_not_block({'kisa_not': note})
        self.assertIn(note, html)
        self.assertGreater(len(html), 300)

    def test_15_1000_char_not_not_truncated(self) -> None:
        note = 'y' * 1000
        html = render_gorusme_not_block({'kisa_not': note})
        self.assertIn(note, html)
        self.assertGreater(len(html), 1000)

    def test_16_long_url_present_unbroken_in_html(self) -> None:
        url = 'https://example.com/' + ('x' * 120)
        html = render_gorusme_not_block({'kisa_not': url})
        self.assertIn(url, html)
        css = self._css_block()
        self.assertIn('overflow-wrap: anywhere', css)
        self.assertIn('word-break: break-word', css)

    def test_17_abcd_groups_preserved(self) -> None:
        for title in (
            'A — Görüşme Bilgisi',
            'B — Ticari Bilgi',
            'C — Sonuç / Takip',
            'D — Bağlantılar',
        ):
            self.assertIn(title, self.fn)

    def test_18_ticari_takip_baglanti_fields_preserved(self) -> None:
        markers = (
            'Verilen Fiyat',
            'Konuşulan Tonaj',
            'Takip Durumu',
            'Sonraki Aksiyon',
            'Bağlı Numune',
            'Bağlı Sipariş',
            'ckartTakipTamamla',
            'ckartGorusmeDuzenle',
        )
        for m in markers:
            self.assertIn(m, self.fn, msg=f'missing: {m}')

    def test_19_shared_urt_detail_css_unchanged(self) -> None:
        self.assertIn('grid-template-columns: repeat(auto-fit, minmax(220px, 1fr))', self.src)
        self.assertIn('.ckart-urt-detail-field .lbl {', self.src)
        num_fn = re.search(r'function _numDetayHtml\(n\).*?return html;', self.src, re.DOTALL)
        self.assertIsNotNone(num_fn)
        self.assertNotIn('ckart-gor-not-full', num_fn.group(0))
        sevk_fn = re.search(
            r"html \+= '<div class=\"ckart-urt-detail-group-title\">Sevkiyat Bilgisi",
            self.src,
        )
        self.assertIsNotNone(sevk_fn)
        self.assertEqual(self.src.count('ckart-gor-not-full'), 2)

    def test_20_empty_note_block_not_rendered(self) -> None:
        self.assertIn("var gorNot = (g.kisa_not || '').trim()", self.fn)
        self.assertIn('if (gorNot)', self.fn)
        self.assertEqual('', render_gorusme_not_block({'kisa_not': ''}))
        self.assertEqual('', render_gorusme_not_block({'kisa_not': '   '}))


if __name__ == '__main__':
    unittest.main()
