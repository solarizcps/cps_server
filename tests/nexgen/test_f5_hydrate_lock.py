# -*- coding: utf-8 -*-
"""F5 tahsilat hydrate minimum fix — LOCK tests."""
from __future__ import annotations

import json
import os
import pathlib
import re
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.mo_tahsilat_config import KAYNAK_MUSTERI_OPERASYONU
from modules.nexgen.mo_tahsilat_kayit_service import acik_planlar, canonical_siparis_odeme_tipi

HTML = (pathlib.Path(__file__).parents[2] / 'app/templates/nexgen/musteri_pazarlama.html').read_text(encoding='utf-8')


def _schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE nexgen_cari (id INTEGER PRIMARY KEY, unvan TEXT);
        CREATE TABLE nexgen_planlama_siparis (
            id INTEGER PRIMARY KEY, siparis_no TEXT, cari_id INTEGER, cari_unvan TEXT,
            durum TEXT, anlasma_para_birimi TEXT, anlasma_birim_fiyat REAL,
            vade_gun INTEGER, tahsilat_kurali TEXT, kaynak_modul TEXT,
            tahsilat_durumu TEXT, planlanan_tahsilat_tarihi TEXT, talep_referansi TEXT,
            odeme_tipi TEXT, tahsilat_odeme_sekli TEXT, tahsilat_gun_sayisi INTEGER
        );
        CREATE TABLE mo_musteri_sevkiyat (
            id INTEGER PRIMARY KEY, sevkiyat_no TEXT, siparis_id INTEGER,
            durum TEXT, aktif INTEGER DEFAULT 1, sevk_tarihi TEXT
        );
        """
    )


class TestAcikPlanlarOdemeTipi(unittest.TestCase):
    def test_pzm_payload_cek(self) -> None:
        con = sqlite3.connect(':memory:')
        con.row_factory = sqlite3.Row
        _schema(con)
        payload = {
            'v': 2,
            'anlasma_para_birimi': 'USD',
            'vade_gun': 185,
            'odeme_tipi': 'CEK',
        }
        ref = '__PZM_V2__' + json.dumps(payload, separators=(',', ':'))
        con.execute(
            """
            INSERT INTO nexgen_planlama_siparis
                (id, siparis_no, cari_id, cari_unvan, durum, anlasma_para_birimi,
                 anlasma_birim_fiyat, vade_gun, tahsilat_kurali, kaynak_modul, talep_referansi)
            VALUES (760, 'PZM-2026-0222', 11, 'NEZIH', 'TAMAMLANDI', 'USD', 2.0, 185, 'VADE_GUN', ?, ?)
            """,
            (KAYNAK_MUSTERI_OPERASYONU, ref),
        )
        con.execute(
            """
            INSERT INTO mo_musteri_sevkiyat
                (id, sevkiyat_no, siparis_id, durum, aktif, sevk_tarihi)
            VALUES (228, 'MSV-2026-0166', 760, 'SEVK_EDILDI', 1, '2026-08-10')
            """
        )
        con.commit()
        planlar = acik_planlar(con, [11])
        p = next(x for x in planlar if x['id'] == 760)
        self.assertEqual(p['odeme_tipi'], 'CEK')

    def test_column_odeme_oncelikli(self) -> None:
        row = {
            'odeme_tipi': 'NAKIT',
            'talep_referansi': '__PZM_V2__{"odeme_tipi":"CEK"}',
        }
        self.assertEqual(canonical_siparis_odeme_tipi(row), 'NAKIT')


class TestF5HydrateTemplateLock(unittest.TestCase):
    def test_apply_plan_odeme_hydrate(self) -> None:
        assert 'function applyTahsilatPlanOdemeFromPlan' in HTML
        assert 'applyTahsilatPlanOdemeFromPlan(p)' in HTML

    def test_sevk_selectable_helper(self) -> None:
        assert 'function sevkSelectable(s)' in HTML

    def test_tek_selectable_auto_select(self) -> None:
        assert 'selectable.length === 1' in HTML

    def test_stale_seq_guard(self) -> None:
        assert 'if (seq !== tahsilatSevkLoadSeq) return;' in HTML

    def test_last_sevk_session_storage(self) -> None:
        assert 'mo_tahsilat_last_sevk_' in HTML

    def test_zero_selectable_uyari(self) -> None:
        assert 'mp-t-sevk-secim-uyari' in HTML
        assert 'function updateSevkiyatSecimUyarisi' in HTML

    def test_belirsiz_tamamlandi_etiketi_yok(self) -> None:
        assert '[Tamamlandı]' not in HTML

    def test_tahsilat_tamamlandi_etiketi(self) -> None:
        assert '[Tahsilat hedefi tamamen karşılandı.]' in HTML

    def test_onay_bekleyen_etiketi(self) -> None:
        assert 'yönetim onayı bekleyen tahsilat hesaba dahil edilmiştir' in HTML

    def test_manuel_kur_sevk_bound(self) -> None:
        assert 'tahsilatSevkBound' in HTML
        assert 'manuelWrap.hidden = !isFx' in HTML or 'manuelWrap.hidden = false' in HTML

    def test_cek_hydrate_single_preview_contract(self) -> None:
        """Hydrate: baglam/preview susturulur; final preview tek kez session-guard ile."""
        upd_m = re.search(r'function updateTahsilatCekUi\(opts\)\s*\{', HTML)
        self.assertIsNotNone(upd_m, 'updateTahsilatCekUi(opts) bulunamadı')
        upd_body = HTML[upd_m.start():upd_m.start() + 2500]
        self.assertIn('skipBaglam', upd_body)
        self.assertIn('!opts.skipBaglam && typeof window.mpLoadCekBaglam', upd_body)
        self.assertIn('!opts.skipPreview && typeof window.mpTriggerCekPreview', upd_body)

        hyd_start = HTML.find('function hydrateTahsilatDraft(')
        self.assertGreater(hyd_start, 0, 'hydrateTahsilatDraft bulunamadı')
        hyd_body = HTML[hyd_start:hyd_start + 5000]
        self.assertIn('skipPreview: true, skipBaglam: true', hyd_body)
        self.assertIn('updateTahsilatCekUi(uiOpts)', hyd_body)
        self.assertIn('function runFinalHydratePreview', hyd_body)

        preview_m = re.search(
            r'function runFinalHydratePreview\(k\)\s*\{[^}]*mpTriggerCekPreviewSession\(myPreviewSession\)',
            HTML[hyd_start:hyd_start + 6500],
        )
        self.assertIsNotNone(preview_m, 'runFinalHydratePreview → mpTriggerCekPreviewSession kontratı yok')
        finish_m = re.search(
            r'function finishHydrate\(k\)\s*\{[^}]*return runFinalHydratePreview\(k\)',
            HTML[hyd_start:hyd_start + 7000],
        )
        self.assertIsNotNone(finish_m, 'finishHydrate tek final preview çağrısı yok')

        mp_start = HTML.find('window.mpHydrateCekSatirlar = function')
        self.assertGreater(mp_start, 0, 'mpHydrateCekSatirlar bulunamadı')
        mp_body = HTML[mp_start:mp_start + 800]
        self.assertIn('updateTahsilatCekUi({ skipPreview: true, skipBaglam: true })', mp_body)
        self.assertNotIn('triggerPreview(', mp_body)


if __name__ == '__main__':
    unittest.main()
