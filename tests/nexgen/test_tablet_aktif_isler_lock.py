# -*- coding: utf-8 -*-
"""TABLET-AKTIF-ISLER-LOCK — yalnız aktif operasyon listesi.

Kilitlenen davranış:
- Biten sekmesi/sayacı yok
- BITTI sınıflı kartlar hiçbir sekmede görünmez
- Tümü = hazir + devam + bekleme; Aktif İş rozeti ile aynı
- Plan/sipariş/batch/cari/ürün/renk araması korunur
- Backend BITTI payload dışlama kontratı korunur (routes statik)
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TMPL = ROOT / 'app' / 'templates' / 'nexgen' / 'tablet.html'
ROUTES = ROOT / 'app' / 'modules' / 'nexgen' / 'routes.py'

AKTIF_SIP = {
    'musteri_adi': 'Aktif Cari A.Ş.',
    'siparis_no': 'PZM-AKTIF-001',
    'kalemler': [{
        'plan_kodu': 'NP-AKTIF-001',
        'batch_kodu': 'NG-AKTIF-001',
        'formul_ad': 'Terlik 18-28',
        'renk_ad': 'MAVI',
        'rf_kod': '0100',
        'rf_renk_ad': 'MAVI',
        'durum': 'DEVAM',
        'boyut_kirilim': [{'durum': 'DEVAM', 'parca_hazir': 1, 'parca_toplam': 1}],
    }],
}

PSEUDO_BITTI_SIP = {
    'musteri_adi': 'Beoss Ayakkabı',
    'siparis_no': 'NSP-2026-00001',
    'kalemler': [{
        'plan_kodu': 'NP-NSP-001',
        'batch_kodu': 'NG-NSP-001',
        'formul_ad': 'Taban Formül',
        'renk_ad': 'SIYAH',
        'rf_kod': '0001',
        'rf_renk_ad': 'SIYAH',
        'durum': 'DEVAM',
        'boyut_kirilim': [{'durum': 'BITTI', 'parca_biten': 12, 'parca_toplam': 12}],
    }],
}

BEKLEME_SIP = {
    'musteri_adi': 'Bekleyen Cari',
    'siparis_no': 'PZM-BEK-001',
    'kalemler': [{
        'plan_kodu': 'NP-BEK-001',
        'batch_kodu': 'NG-BEK-001',
        'formul_ad': 'Dökme',
        'renk_ad': 'BEJ',
        'durum': 'BEKLEME',
        'boyut_kirilim': [{'durum': 'BEKLEME', 'parca_bekleme': 2, 'parca_toplam': 2}],
    }],
}

HAZIR_SIP = {
    'musteri_adi': 'Hazır Cari',
    'siparis_no': 'PZM-HAZ-001',
    'kalemler': [{
        'plan_kodu': 'NP-HAZ-001',
        'batch_kodu': None,
        'formul_ad': 'Terlik',
        'renk_ad': 'KIRMIZI',
        'durum': 'PLANLI',
        'boyut_kirilim': [{'durum': 'PLANLI', 'parca_hazir': 3, 'parca_toplam': 3}],
    }],
}


def _renk_kimlik_metin(kalem: dict) -> str:
    kod = str(kalem.get('rf_kod') or '').strip()
    ad = str(kalem.get('rf_renk_ad') or kalem.get('renk_ad') or '').strip()
    if kod and ad:
        return f'{kod} {ad}'
    return kod or ad or ''


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
    gd = _siparis_durum(sip)
    vm_filtre = DURUM_VM.get(gd, 'hazir')
    if vm_filtre == 'bitti':
        return False
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


def tablet_sayac(gruplar: list[dict]) -> dict[str, int]:
    sayac = {'tumu': 0, 'hazir': 0, 'devam': 0, 'bekleme': 0}
    for sip in gruplar:
        f = DURUM_VM.get(_siparis_durum(sip), 'hazir')
        if f == 'bitti':
            continue
        sayac['tumu'] += 1
        if f == 'hazir':
            sayac['hazir'] += 1
        elif f == 'devam':
            sayac['devam'] += 1
        elif f == 'bekleme':
            sayac['bekleme'] += 1
    return sayac


class TabletAktifIslerLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = TMPL.read_text(encoding='utf-8')
        cls.routes = ROUTES.read_text(encoding='utf-8')
        cls.filtre_start = cls.src.index('function filtrele()')
        cls.filtre_block = cls.src[cls.filtre_start:cls.src.index('function sayacGuncelle()', cls.filtre_start)]
        cls.sayac_block = cls.src[cls.src.index('function sayacGuncelle()'):cls.src.index('function render()', cls.filtre_start)]

    def test_01_biten_butonu_yok(self) -> None:
        self.assertNotIn("data-filtre=\"bitti\"", self.src)
        self.assertNotIn("filtreUygula('bitti'", self.src)
        self.assertNotIn('id="fs-bitti"', self.src)

    def test_02_filtrele_bitti_haric(self) -> None:
        self.assertIn("if (vm.filtre === 'bitti') return false;", self.filtre_block)

    def test_03_sayac_bitti_yok(self) -> None:
        self.assertNotIn('fs-bitti', self.sayac_block)
        self.assertNotIn('sayac.bitti', self.sayac_block)
        self.assertIn('if (f === \'bitti\') return;', self.sayac_block)

    def test_04_aktif_rozet_tumu_ile_esit(self) -> None:
        self.assertIn('aktifSayi.textContent = sayac.tumu;', self.sayac_block)
        self.assertNotIn('sayac.devam + sayac.hazir', self.sayac_block)

    def test_05_pseudo_bitti_tumu_disinda(self) -> None:
        self.assertEqual(_siparis_durum(PSEUDO_BITTI_SIP), 'BITTI')
        self.assertFalse(tablet_filtre_eslesir(PSEUDO_BITTI_SIP, ''))

    def test_06_aktif_kart_tumu_icinde(self) -> None:
        self.assertTrue(tablet_filtre_eslesir(AKTIF_SIP, ''))

    def test_07_tumu_sayisi_aktif_toplam(self) -> None:
        gruplar = [AKTIF_SIP, PSEUDO_BITTI_SIP, BEKLEME_SIP, HAZIR_SIP]
        s = tablet_sayac(gruplar)
        self.assertEqual(s['tumu'], 3)
        self.assertEqual(s['tumu'], s['hazir'] + s['devam'] + s['bekleme'])

    def test_08_baslama_filtresi(self) -> None:
        self.assertTrue(tablet_filtre_eslesir(HAZIR_SIP, '', 'hazir'))
        self.assertFalse(tablet_filtre_eslesir(AKTIF_SIP, '', 'hazir'))

    def test_09_devam_filtresi(self) -> None:
        self.assertTrue(tablet_filtre_eslesir(AKTIF_SIP, '', 'devam'))
        self.assertFalse(tablet_filtre_eslesir(BEKLEME_SIP, '', 'devam'))

    def test_10_bekleme_filtresi(self) -> None:
        self.assertTrue(tablet_filtre_eslesir(BEKLEME_SIP, '', 'bekleme'))
        self.assertFalse(tablet_filtre_eslesir(AKTIF_SIP, '', 'bekleme'))

    def test_11_plan_kodu_arama_korunur(self) -> None:
        self.assertTrue(tablet_filtre_eslesir(AKTIF_SIP, 'NP-AKTIF-001'))

    def test_12_siparis_arama_korunur(self) -> None:
        self.assertTrue(tablet_filtre_eslesir(AKTIF_SIP, 'PZM-AKTIF-001'))

    def test_13_batch_arama_korunur(self) -> None:
        self.assertTrue(tablet_filtre_eslesir(AKTIF_SIP, 'NG-AKTIF-001'))

    def test_14_cari_urun_renk_arama(self) -> None:
        self.assertTrue(tablet_filtre_eslesir(AKTIF_SIP, 'aktif cari'))
        self.assertTrue(tablet_filtre_eslesir(AKTIF_SIP, 'terlik'))
        self.assertTrue(tablet_filtre_eslesir(AKTIF_SIP, '0100'))

    def test_15_backend_bitti_payload_disi_kontrat(self) -> None:
        self.assertIn("_AKTIF_BATCH = ('TASLAK', 'HAZIR', 'DEVAM', 'BEKLEME')", self.routes)
        self.assertIn("np.durum NOT IN ('BITTI','IPTAL')", self.routes)
        self.assertIn("nb.durum NOT IN ('BITTI')", self.routes)

    def test_16_durum_vm_bitti_rozet_korunur(self) -> None:
        """Kalem içi BITTI gösterimi için DURUM_VM.BITTI kalır."""
        self.assertIn("BITTI:   { filtre: 'bitti'", self.src)


if __name__ == '__main__':
    unittest.main()
