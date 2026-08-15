# -*- coding: utf-8 -*-
"""TABLET-PLAN-KODU-ARAMA-LOCK — /nexgen/tablet arama plan_kodu desteği.

Kilitlenen davranış:
- _BATCHLER payload plan_kodu içerir (_tablet_ana_veri)
- veriGrupla kalem modeli plan_kodu taşır
- filtrele() plan_kodu alanını arar (küçük harf + kısmi eşleşme)
- cari, siparis_no, batch_kodu, urun, renk aramaları korunur
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TMPL = ROOT / 'app' / 'templates' / 'nexgen' / 'tablet.html'
ROUTES = ROOT / 'app' / 'modules' / 'nexgen' / 'routes.py'

# Şahin pilot fixture — canonical DB'ye bağımlı değil
PILOT_SIP = {
    'musteri_adi': 'Şahin Taban ve Ayakkabıcılık San.Tic.Ltd.Şti.',
    'siparis_no': 'PZM-2026-0216',
    'kalemler': [{
        'plan_kodu': 'NP-2026-00112',
        'batch_kodu': 'NG-PRD-2026-00026',
        'formul_ad': 'Terlik 18-28',
        'renk_ad': 'TURUNCU',
        'rf_kod': '0250',
        'rf_renk_ad': 'TURUNCU',
        'durum': 'DEVAM',
        'boyut_kirilim': [{'durum': 'DEVAM', 'parca_hazir': 1, 'parca_toplam': 1}],
    }],
}


def _renk_kimlik_metin(kalem: dict) -> str:
    kod = str(kalem.get('rf_kod') or '').strip()
    ad = str(kalem.get('rf_renk_ad') or kalem.get('renk_ad') or '').strip()
    if kod and ad:
        ku, au = kod.upper(), ad.upper()
        if au == ku:
            ad = ''
        elif au.startswith(ku):
            ad = ad[len(kod):].lstrip(' -.·.')
    if kod and ad:
        return f'{kod} {ad}'
    return kod or ad or ''


def _kalem_durum(kalem: dict) -> str:
    d = 'HAZIR'
    for bk in kalem.get('boyut_kirilim') or []:
        bd = bk.get('durum') or 'HAZIR'
        if bd == 'DEVAM':
            d = 'DEVAM'
        elif bd == 'BEKLEME' and d != 'DEVAM':
            d = 'BEKLEME'
        elif bd == 'BITTI' and d == 'HAZIR':
            d = 'BITTI'
    if kalem.get('durum') == 'PLANLI':
        return 'PLANLI'
    return d


def _siparis_durum(sip: dict) -> str:
    has_devam = has_bekleme = has_hazir = False
    all_bitti = bool(sip.get('kalemler'))
    for k in sip.get('kalemler') or []:
        kirilim = k.get('boyut_kirilim') or [{'durum': k.get('durum', 'HAZIR')}]
        for bk in kirilim:
            d = bk.get('durum') or 'HAZIR'
            if d == 'DEVAM':
                has_devam = True
            elif d == 'BEKLEME':
                has_bekleme = True
            elif d in ('HAZIR', 'PLANLI'):
                has_hazir = True
            if d != 'BITTI':
                all_bitti = False
    if has_devam:
        return 'DEVAM'
    if has_bekleme:
        return 'BEKLEME'
    if all_bitti and sip.get('kalemler'):
        return 'BITTI'
    if has_hazir:
        return 'HAZIR'
    return 'HAZIR'


DURUM_VM = {
    'HAZIR': 'hazir',
    'PLANLI': 'hazir',
    'DEVAM': 'devam',
    'BEKLEME': 'bekleme',
    'BITTI': 'bitti',
}


def tablet_filtre_eslesir(sip: dict, arama: str, aktif_filtre: str = 'tumu') -> bool:
    """tablet.html filtrele() ile aynı arama/durum mantığı (Python simülasyonu)."""
    gd = _siparis_durum(sip)
    vm_filtre = DURUM_VM.get(gd, 'hazir')
    cari = (sip.get('musteri_adi') or '').lower()
    sip_no = (sip.get('siparis_no') or '').lower()
    q = (arama or '').lower()
    plan_kod = ' '.join((k.get('plan_kodu') or '').lower() for k in sip.get('kalemler') or [])
    urun = ' '.join((k.get('formul_ad') or '') for k in sip.get('kalemler') or []).lower()
    batch_kod = ' '.join((k.get('batch_kodu') or '').lower() for k in sip.get('kalemler') or [])
    renk = ' '.join(_renk_kimlik_metin(k).lower() for k in sip.get('kalemler') or [])
    f_pas = (aktif_filtre == 'tumu') or vm_filtre == aktif_filtre
    a_pas = (
        not q
        or q in cari
        or q in sip_no
        or q in plan_kod
        or q in urun
        or q in batch_kod
        or q in renk
    )
    return f_pas and a_pas


class TabletPlanKoduAramaLockTests(unittest.TestCase):
    """Statik kontrat + fixture simülasyon — canonical DB kullanmaz."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = TMPL.read_text(encoding='utf-8')
        cls.routes = ROUTES.read_text(encoding='utf-8')
        start = cls.src.index('function filtrele()')
        end = cls.src.index('function sayacGuncelle()', start)
        cls.filtre_block = cls.src[start:end]
        vg_start = cls.src.index('function veriGrupla()')
        vg_end = cls.src.index('function kalemSatirHtml', vg_start)
        cls.grupla_block = cls.src[vg_start:vg_end]

    def test_01_batch_payload_plan_kodu_backend(self) -> None:
        """_tablet_ana_veri devam_eden satırına plan_kodu ekler."""
        self.assertIn("row['plan_kodu'] = pl.get('plan_kodu')", self.routes)

    def test_02_veriGrupla_batch_kalem_plan_kodu(self) -> None:
        self.assertIn('plan_kodu: b.plan_kodu ||', self.grupla_block)

    def test_03_veriGrupla_plan_kalem_plan_kodu(self) -> None:
        self.assertIn('plan_kodu: p.plan_kodu ||', self.grupla_block)

    def test_04_filtrele_plan_kodu_alani(self) -> None:
        self.assertIn(
            "var planKod = sip.kalemler.map(function(k) { return (k.plan_kodu || '').toLowerCase(); }).join(' ');",
            self.filtre_block,
        )
        self.assertIn('planKod.includes(arama)', self.filtre_block)

    def test_05_arama_np_tam(self) -> None:
        self.assertTrue(tablet_filtre_eslesir(PILOT_SIP, 'NP-2026-00112'))

    def test_06_arama_np_kucuk_harf(self) -> None:
        self.assertTrue(tablet_filtre_eslesir(PILOT_SIP, 'np-2026-00112'))

    def test_07_arama_kismi_00112(self) -> None:
        self.assertTrue(tablet_filtre_eslesir(PILOT_SIP, '00112'))

    def test_08_arama_siparis_korunur(self) -> None:
        self.assertTrue(tablet_filtre_eslesir(PILOT_SIP, 'PZM-2026-0216'))

    def test_09_arama_batch_korunur(self) -> None:
        self.assertTrue(tablet_filtre_eslesir(PILOT_SIP, 'NG-PRD-2026-00026'))

    def test_10_arama_cari_korunur(self) -> None:
        self.assertTrue(tablet_filtre_eslesir(PILOT_SIP, 'Şahin'))

    def test_11_arama_urun_korunur(self) -> None:
        self.assertTrue(tablet_filtre_eslesir(PILOT_SIP, 'Terlik'))

    def test_12_arama_renk_korunur(self) -> None:
        self.assertTrue(tablet_filtre_eslesir(PILOT_SIP, '0250'))

    def test_13_durum_sekmesi_devam_korunur(self) -> None:
        self.assertTrue(tablet_filtre_eslesir(PILOT_SIP, 'NP-2026-00112', 'devam'))
        self.assertFalse(tablet_filtre_eslesir(PILOT_SIP, 'NP-2026-00112', 'bitti'))

    def test_14_bos_arama_tum_kayit(self) -> None:
        self.assertTrue(tablet_filtre_eslesir(PILOT_SIP, ''))

    def test_15_plan_kodu_kartta_gosterilmez(self) -> None:
        """Bu görev yalnız arama — kart HTML'ine plan no eklenmez."""
        kart_start = self.src.index('function kartHtml(sip)')
        kart_end = self.src.index('function lsModalAc', kart_start)
        kart_block = self.src[kart_start:kart_end]
        self.assertNotRegex(kart_block, re.compile(r'plan_kodu', re.I))


if __name__ == '__main__':
    unittest.main()
