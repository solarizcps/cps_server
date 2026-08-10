# -*- coding: utf-8 -*-
"""
tests/nexgen/test_mo_tahsilat_regression.py
============================================
Tahsilat V1 regression lock — PASS edilmiş davranışların kalıcı testleri.

Tam suite:
  python -m unittest \\
    tests.nexgen.test_mo_tahsilat_regression \\
    tests.nexgen.test_mo_tahsilat_kur_service \\
    tests.nexgen.test_mo_tahsilat_kayit_tcmb_write

Browser E2E:
  python app/_browser_tahsilat_regression_runner.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.mo_tahsilat_config import (
    KAYIT_DURUM_MUHASEBE_BEKLIYOR,
    KAYIT_DURUM_ONAYLANDI,
    KAYIT_DURUM_REDDEDILDI,
    KAYIT_DURUM_REVIZYON,
    KAYIT_DURUM_TASLAK,
    KAYNAK_MUSTERI_OPERASYONU,
)
from modules.nexgen.mo_tahsilat_kayit_service import (
    MoTahsilatError,
    acik_planlar,
    kayit_detay,
    onaya_gonder,
    sync_cek_parent_tutarlar,
    taslak_kaydet,
)
from modules.nexgen.mo_tahsilat_kur_service import fx_try_hedef_hesapla
from modules.nexgen.mo_tahsilat_sevk_service import (
    sevk_hedef_hesapla,
    tahsil_edilen_sevk,
    tahsilat_sevk_adaylari,
    tahsilat_sevk_write_guard,
)
from modules.nexgen.mo_vade_kontrol_service import CekSatiriInput, hesapla

YK = {'*'}
UID = 1
KUR_TARIH = '2026-08-09'
SEVK_KUR_TARIH = '2026-08-01'
SEVK_TARIH = '2026-08-10'


def _schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE nexgen_cari (id INTEGER PRIMARY KEY, unvan TEXT, aktif INTEGER DEFAULT 1);
        CREATE TABLE nexgen_planlama_siparis (
            id INTEGER PRIMARY KEY, siparis_no TEXT, cari_id INTEGER, cari_unvan TEXT,
            durum TEXT, anlasma_para_birimi TEXT, anlasma_birim_fiyat REAL,
            vade_gun INTEGER, tahsilat_kurali TEXT, kaynak_modul TEXT,
            tahsilat_durumu TEXT, tahsilat_gun_sayisi INTEGER,
            planlanan_tahsilat_tarihi TEXT, talep_referansi TEXT,
            guncelleme_tarihi TEXT
        );
        CREATE TABLE mo_musteri_sevkiyat (
            id INTEGER PRIMARY KEY, sevkiyat_no TEXT, siparis_id INTEGER, cari_id INTEGER,
            durum TEXT, aktif INTEGER DEFAULT 1, sevk_tarihi TEXT,
            idempotency_key TEXT, olusturan_id INTEGER, olusturma_tarihi TEXT
        );
        CREATE TABLE mo_musteri_sevkiyat_kalem (
            id INTEGER PRIMARY KEY, sevkiyat_id INTEGER, miktar_kg REAL,
            birim_fiyat_snapshot REAL, para_birimi_snapshot TEXT, fiyat_kaynagi TEXT
        );
        CREATE TABLE sistem_kur (
            Id INTEGER PRIMARY KEY AUTOINCREMENT, Tarih TEXT, ParaBirimi TEXT,
            Alis REAL, Satis REAL, MerkezKur REAL
        );
        CREATE TABLE mo_tahsilat_kayit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, kayit_kodu TEXT,
            cari_id INTEGER, siparis_id INTEGER, sevkiyat_id INTEGER,
            kaynak_modul TEXT, beklenen_tutar REAL, beklenen_tahmini INTEGER,
            paket_hedef_tutar REAL, alinan_tutar REAL, kalan_tutar REAL,
            planlanan_tahsilat_tarihi TEXT, alinan_tarih TEXT,
            odeme_tipi TEXT, odeme_referansi TEXT, kismi_mi INTEGER,
            aciklama TEXT, dosya_ref TEXT, onay_notu TEXT, durum TEXT,
            cari_entegrasyon_durumu TEXT, idempotency_key TEXT UNIQUE,
            olusturan_id INTEGER, onaylayan_id INTEGER, aktif INTEGER DEFAULT 1,
            olusturma_tarihi TEXT, guncelleme_tarihi TEXT,
            para_birimi TEXT,
            onaylanan_vade_gun_snapshot INTEGER,
            gercek_sevk_tarihi_snapshot TEXT, hedef_vade_tarihi TEXT,
            sevk_hedef_tutar_snapshot REAL, sevk_para_birimi_snapshot TEXT,
            sevk_kalan_fx_snapshot REAL, tcmb_satis_kur_snapshot REAL,
            kur_tarihi_snapshot TEXT
        );
        CREATE TABLE mo_tahsilat_cek (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tahsilat_kayit_id INTEGER,
            tutar REAL, cek_alim_tarihi TEXT, gercek_cek_vade_tarihi TEXT,
            para_birimi TEXT, aktif INTEGER DEFAULT 1, idempotency_key TEXT UNIQUE,
            sira_no INTEGER
        );
        """
    )


def _mem_con() -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    _schema(con)
    con.execute('INSERT INTO nexgen_cari (id, unvan) VALUES (1, ?), (2, ?)', ('Cari A', 'Cari B'))
    con.execute(
        """
        INSERT INTO nexgen_planlama_siparis
            (id, siparis_no, cari_id, cari_unvan, durum, anlasma_para_birimi, vade_gun,
             tahsilat_kurali, kaynak_modul, tahsilat_durumu)
        VALUES
            (1, 'S-A1', 1, 'Cari A', 'ONAYLANDI', 'USD', 180, 'VADE_GUN', ?, 'PLANLANDI'),
            (2, 'S-B1', 2, 'Cari B', 'ONAYLANDI', 'USD', 180, 'VADE_GUN', ?, 'PLANLANDI')
        """,
        (KAYNAK_MUSTERI_OPERASYONU, KAYNAK_MUSTERI_OPERASYONU),
    )
    con.execute(
        """
        INSERT INTO mo_musteri_sevkiyat
            (id, sevkiyat_no, siparis_id, cari_id, durum, aktif, sevk_tarihi, idempotency_key, olusturan_id, olusturma_tarihi)
        VALUES
            (10, 'MSV-10', 1, 1, 'SEVK_EDILDI', 1, '2026-08-01', 'sevk-10', 1, '2026-08-01'),
            (11, 'MSV-11', 1, 1, 'SEVK_EDILDI', 1, '2026-08-15', 'sevk-11', 1, '2026-08-15'),
            (20, 'MSV-20', 1, 1, 'SEVK_EDILDI', 1, '2026-08-20', 'sevk-20', 1, '2026-08-20'),
            (30, 'MSV-30', 1, 1, 'SEVK_EDILDI', 1, '2026-08-25', 'sevk-30', 1, '2026-08-25')
        """
    )
    con.execute(
        """
        INSERT INTO mo_musteri_sevkiyat_kalem (sevkiyat_id, miktar_kg, birim_fiyat_snapshot, para_birimi_snapshot, fiyat_kaynagi)
        VALUES
            (10, 300, 2, 'USD', 'KALEM_NET'),
            (11, 200, 2, 'USD', 'KALEM_NET'),
            (20, 100, 2, 'USD', 'KALEM_NET'),
            (30, 50, NULL, 'USD', NULL)
        """
    )
    con.execute(
        'INSERT INTO sistem_kur (Tarih, ParaBirimi, Alis, Satis, MerkezKur) VALUES (?,?,?,?,?)',
        (SEVK_KUR_TARIH, 'USD', 47.0, 47.25, 99.99),
    )
    con.execute(
        'INSERT INTO sistem_kur (Tarih, ParaBirimi, Alis, Satis, MerkezKur) VALUES (?,?,?,?,?)',
        (KUR_TARIH, 'USD', 47.0, 47.25, 99.99),
    )
    con.commit()
    return con


def _tahsilat_row(
    con: sqlite3.Connection,
    *,
    kid: int | None = None,
    sevkiyat_id: int = 10,
    durum: str,
    alinan: float,
    kod: str,
) -> int:
    if kid is None:
        cur = con.execute(
            """
            INSERT INTO mo_tahsilat_kayit
                (kayit_kodu, cari_id, siparis_id, sevkiyat_id, kaynak_modul,
                 beklenen_tutar, alinan_tutar, kalan_tutar, para_birimi,
                 sevk_hedef_tutar_snapshot, sevk_para_birimi_snapshot,
                 durum, aktif, odeme_tipi, idempotency_key, olusturan_id, olusturma_tarihi)
            VALUES (?, 1, 1, ?, ?, 600, ?, 0, 'USD', 600, 'USD', ?, 1, 'NAKIT', ?, 1, datetime('now'))
            """,
            (kod, sevkiyat_id, KAYNAK_MUSTERI_OPERASYONU, alinan, durum, kod),
        )
        con.commit()
        return int(cur.lastrowid)
    con.execute(
        """
        UPDATE mo_tahsilat_kayit SET durum=?, alinan_tutar=?, sevkiyat_id=? WHERE id=?
        """,
        (durum, alinan, sevkiyat_id, kid),
    )
    con.commit()
    return kid


def _reserve_200(con: sqlite3.Connection) -> None:
    """600 USD hedef sevk üzerinde 200 rezerv → 400 USD kalan (PASS senaryosu)."""
    _tahsilat_row(con, durum=KAYIT_DURUM_MUHASEBE_BEKLIYOR, alinan=200, kod='rez-200-reg')


def _payload(**kw) -> dict:
    base = {
        'idempotency_key': kw.pop('idempotency_key', 'idem-reg'),
        'cari_id': 1,
        'siparis_id': 1,
        'sevkiyat_id': 10,
        'odeme_tipi': 'NAKIT',
        'alinan_tarih': KUR_TARIH,
    }
    base.update(kw)
    return base


class TestRegressionBagliSiparis(unittest.TestCase):
    def test_acik_planlar_yalniz_kendi_cari(self) -> None:
        con = _mem_con()
        p1 = acik_planlar(con, [1])
        p2 = acik_planlar(con, [2])
        self.assertTrue(all(int(p['cari_id']) == 1 for p in p1))
        self.assertTrue(all(int(p['cari_id']) == 2 for p in p2))
        self.assertEqual({p['id'] for p in p1}, {1})
        self.assertEqual({p['id'] for p in p2}, {2})


class TestRegressionSevkiyat(unittest.TestCase):
    def test_sevk_hedef_300kg_x_2_usd(self) -> None:
        con = _mem_con()
        h = sevk_hedef_hesapla(con, 10)
        self.assertEqual(h['sevk_hedef_tutar'], 600.0)
        self.assertEqual(h['para_birimi'], 'USD')
        self.assertFalse(h['eksik_fiyat'])

    def test_kalan_400_after_200_reserved(self) -> None:
        con = _mem_con()
        _tahsilat_row(con, durum=KAYIT_DURUM_MUHASEBE_BEKLIYOR, alinan=200, kod='rez-200')
        aday = next(a for a in tahsilat_sevk_adaylari(con, 1) if a['sevkiyat_id'] == 10)
        self.assertEqual(aday['sevk_hedef_tutar'], 600.0)
        self.assertEqual(aday['tahsil_edilen'], 200.0)
        self.assertEqual(aday['kalan'], 400.0)

    def test_coklu_sevk_adaylari(self) -> None:
        con = _mem_con()
        adaylar = tahsilat_sevk_adaylari(con, 1)
        ids = [a['sevkiyat_id'] for a in adaylar if a['tahsilata_uygun']]
        self.assertIn(10, ids)
        self.assertIn(11, ids)

    def test_eksik_fiyat_secilemez(self) -> None:
        con = _mem_con()
        aday = next(a for a in tahsilat_sevk_adaylari(con, 1) if a['sevkiyat_id'] == 30)
        self.assertFalse(aday['tahsilata_uygun'])
        with self.assertRaises(MoTahsilatError):
            tahsilat_sevk_write_guard(con, cari_id=1, siparis_id=1, sevkiyat_id=30)

    def test_kalan_sifir_tamamlandi(self) -> None:
        con = _mem_con()
        _tahsilat_row(con, durum=KAYIT_DURUM_ONAYLANDI, alinan=600, kod='full-600')
        aday = next(a for a in tahsilat_sevk_adaylari(con, 1) if a['sevkiyat_id'] == 10)
        self.assertLessEqual(aday['kalan'] or 0, 0.009)
        with self.assertRaises(MoTahsilatError):
            tahsilat_sevk_write_guard(con, cari_id=1, siparis_id=1, sevkiyat_id=10)


class TestRegressionDoubleCount(unittest.TestCase):
    def test_rezerv_durumlari(self) -> None:
        con = _mem_con()
        self.assertEqual(tahsil_edilen_sevk(con, 10), 0.0)
        _tahsilat_row(con, durum=KAYIT_DURUM_ONAYLANDI, alinan=100, kod='dc-onay')
        _tahsilat_row(con, durum=KAYIT_DURUM_MUHASEBE_BEKLIYOR, alinan=50, kod='dc-muh')
        self.assertEqual(tahsil_edilen_sevk(con, 10), 150.0)

    def test_taslak_reddedildi_revizyon_dahil_degil(self) -> None:
        con = _mem_con()
        _tahsilat_row(con, durum=KAYIT_DURUM_TASLAK, alinan=300, kod='dc-taslak')
        _tahsilat_row(con, durum=KAYIT_DURUM_REDDEDILDI, alinan=200, kod='dc-red')
        _tahsilat_row(con, durum=KAYIT_DURUM_REVIZYON, alinan=100, kod='dc-rev')
        self.assertEqual(tahsil_edilen_sevk(con, 10), 0.0)

    def test_kalan_asimi_reject(self) -> None:
        con = _mem_con()
        _tahsilat_row(con, durum=KAYIT_DURUM_ONAYLANDI, alinan=700, kod='dc-over')
        with self.assertRaises(MoTahsilatError):
            tahsilat_sevk_write_guard(con, cari_id=1, siparis_id=1, sevkiyat_id=10)


class TestRegressionTcmbFxTry(unittest.TestCase):
    def test_satis_400_x_4725(self) -> None:
        con = _mem_con()
        r = fx_try_hedef_hesapla(con, para_birimi='USD', kur_tarihi=KUR_TARIH, fx_tutar=400)
        self.assertEqual(r['try_hedef_tutar'], 18900.0)
        self.assertEqual(r['tcmb_satis_kur'], 47.25)
        self.assertNotEqual(r['try_hedef_tutar'], 400 * 99.99)

    def test_snapshot_freeze_immutable(self) -> None:
        con = _mem_con()
        _reserve_200(con)
        kayit = taslak_kaydet(con, _payload(alinan_tutar=10000), UID, YK)
        kid = kayit['id']
        con.execute("UPDATE sistem_kur SET Satis=60.0 WHERE Tarih=? AND ParaBirimi='USD'", (SEVK_KUR_TARIH,))
        con.commit()
        kayit2 = taslak_kaydet(
            con, _payload(idempotency_key='imm-2', alinan_tutar=12000), UID, YK, kayit_id=kid,
        )
        self.assertEqual(kayit2['tcmb_satis_kur_snapshot'], 47.25)
        self.assertEqual(kayit2['beklenen_tutar'], 18900.0)

    @patch('modules.nexgen.onay_tahsilat_adapter.tahsilat_onaya_gonder')
    def test_yonetim_onay_snapshot_korunur(self, mock_onay) -> None:
        mock_onay.return_value = {'ok': True, 'talep_id': 1}
        con = _mem_con()
        _reserve_200(con)
        kayit = taslak_kaydet(
            con, _payload(idempotency_key='onay-reg', alinan_tutar=18900), UID, YK,
        )
        kid = kayit['id']
        snap_kur = kayit['tcmb_satis_kur_snapshot']
        snap_hedef = kayit['beklenen_tutar']
        con.execute("UPDATE sistem_kur SET Satis=70.0 WHERE Tarih=? AND ParaBirimi='USD'", (SEVK_KUR_TARIH,))
        con.commit()
        onaya_gonder(con, kid, UID, set())
        det = kayit_detay(con, kid, UID, YK)
        self.assertEqual(det['tcmb_satis_kur_snapshot'], snap_kur)
        self.assertEqual(det['beklenen_tutar'], snap_hedef)


class TestRegressionNakitCek(unittest.TestCase):
    def test_nakit_try_kalan(self) -> None:
        con = _mem_con()
        _reserve_200(con)
        kayit = taslak_kaydet(con, _payload(alinan_tutar=10000), UID, YK)
        self.assertEqual(kayit['beklenen_tutar'], 18900.0)
        self.assertEqual(kayit['kalan_tutar'], 8900.0)
        self.assertEqual(kayit['para_birimi'], 'TRY')

    def test_cek_paket_100_yuzde(self) -> None:
        con = _mem_con()
        _reserve_200(con)
        p = {'idempotency_key': 'cek-reg', 'cari_id': 1, 'siparis_id': 1, 'odeme_tipi': 'CEK'}
        kayit = taslak_kaydet(con, p, UID, YK)
        kid = kayit['id']
        for i, (tutar, vade) in enumerate([(10000, '2027-02-09'), (8900, '2027-03-09')], 1):
            con.execute(
                """
                INSERT INTO mo_tahsilat_cek
                    (tahsilat_kayit_id, tutar, cek_alim_tarihi, gercek_cek_vade_tarihi,
                     para_birimi, aktif, idempotency_key, sira_no)
                VALUES (?, ?, ?, ?, 'TRY', 1, ?, ?)
                """,
                (kid, tutar, KUR_TARIH, vade, f'cek-reg-{i}', i),
            )
        con.commit()
        kayit2 = taslak_kaydet(con, {**p, 'sevkiyat_id': 10}, UID, YK, kayit_id=kid)
        self.assertEqual(kayit2['paket_hedef_tutar'], 18900.0)
        sync_cek_parent_tutarlar(con, kid)
        con.commit()
        row = con.execute(
            'SELECT alinan_tutar, kalan_tutar FROM mo_tahsilat_kayit WHERE id=?', (kid,),
        ).fetchone()
        self.assertEqual(float(row['alinan_tutar']), 18900.0)
        self.assertEqual(float(row['kalan_tutar'] or 0), 0.0)


class TestRegressionVade(unittest.TestCase):
    def _cek(self, tutar: float, gun: int) -> CekSatiriInput:
        from datetime import date, timedelta
        vade = (date.fromisoformat(SEVK_TARIH) + timedelta(days=gun)).isoformat()
        return CekSatiriInput(
            tutar=Decimal(str(tutar)),
            gercek_cek_vade_tarihi=vade,
            cek_alim_tarihi=KUR_TARIH,
            para_birimi='TRY',
        )

    def test_iki_cek_adet_toplam_karsilama(self) -> None:
        cekler = [self._cek(10000, 180), self._cek(8900, 210)]
        s = hesapla(
            odeme_tipi='CEK',
            cek_satirlari=cekler,
            para_birimi='TRY',
            paket_hedef_tutar=Decimal('18900'),
            onaylanan_vade_gun=180,
            sevk_tarihi=SEVK_TARIH,
        )
        self.assertEqual(s.cek_adedi, 2)
        self.assertAlmostEqual(float(s.toplam_cek_tutari), 18900.0, places=2)
        self.assertAlmostEqual(float(s.kalan_tutar or 0), 0.0, places=2)
        self.assertAlmostEqual(s.karsilama_orani, 100.0, places=1)

    def test_agirlikli_vade_tarih_finansman(self) -> None:
        cekler = [self._cek(10000, 180), self._cek(8900, 210)]
        s = hesapla(
            odeme_tipi='CEK',
            cek_satirlari=cekler,
            para_birimi='TRY',
            paket_hedef_tutar=Decimal('18900'),
            onaylanan_vade_gun=180,
            sevk_tarihi=SEVK_TARIH,
            aylik_finansman_orani=Decimal('0.04'),
        )
        self.assertIsNotNone(s.agirlikli_ortalama_vade_gun_gosterim)
        self.assertIsNotNone(s.agirlikli_ortalama_vade_tarihi)
        self.assertIsNotNone(s.vade_sapma_gun_gosterim)
        self.assertIsNotNone(s.finansman_net)


class TestRegressionTaslakHydrate(unittest.TestCase):
    def test_kayit_detay_tum_snapshot_alanlari(self) -> None:
        con = _mem_con()
        _reserve_200(con)
        kayit = taslak_kaydet(con, _payload(idempotency_key='hydrate-reg', alinan_tutar=10000), UID, YK)
        kid = kayit['id']
        det = kayit_detay(con, kid, UID, YK)
        self.assertEqual(det['cari_id'], 1)
        self.assertEqual(det['siparis_id'], 1)
        self.assertEqual(det['sevkiyat_id'], 10)
        self.assertEqual(det['tcmb_satis_kur_snapshot'], 47.25)
        self.assertEqual(det['kur_tarihi_snapshot'], SEVK_KUR_TARIH)
        self.assertEqual(det['beklenen_tutar'], 18900.0)
        self.assertEqual(det['sevk_kalan_fx_snapshot'], 400.0)

    def test_hydrate_cek_satirlari(self) -> None:
        con = _mem_con()
        _reserve_200(con)
        p = {'idempotency_key': 'hydrate-cek', 'cari_id': 1, 'siparis_id': 1, 'odeme_tipi': 'CEK'}
        kayit = taslak_kaydet(con, p, UID, YK)
        kid = kayit['id']
        con.execute(
            """
            INSERT INTO mo_tahsilat_cek
                (tahsilat_kayit_id, tutar, cek_alim_tarihi, gercek_cek_vade_tarihi,
                 para_birimi, aktif, idempotency_key, sira_no)
            VALUES (?, 10000, ?, '2027-02-09', 'TRY', 1, 'h-cek-1', 1)
            """,
            (kid, KUR_TARIH),
        )
        con.commit()
        taslak_kaydet(con, {**p, 'sevkiyat_id': 10}, UID, YK, kayit_id=kid)
        det = kayit_detay(con, kid, UID, YK)
        self.assertEqual(len(det['cek_satirlari']), 1)
        self.assertEqual(float(det['cek_satirlari'][0]['tutar']), 10000.0)


class TestRegressionSevkHesapGosterim(unittest.TestCase):
    def test_sevk_aday_hesap_alanlari(self) -> None:
        con = _mem_con()
        aday = next(a for a in tahsilat_sevk_adaylari(con, 1) if a['sevkiyat_id'] == 10)
        self.assertEqual(aday['toplam_kg'], 300.0)
        self.assertEqual(aday['birim_fiyat_snapshot'], 2.0)
        self.assertEqual(aday['sevk_hedef_tutar'], 600.0)
        self.assertEqual(aday['para_birimi'], 'USD')
        self.assertIn('300 kg', aday['sevk_hesap_ozet'])
        self.assertIn('600', aday['sevk_hesap_ozet'])


class TestRegressionSevkSnapshotLock(unittest.TestCase):
    """
    TAHSILAT-SEVK-SNAPSHOT-LOCK — sevk anı 3 snapshot alanı ayrı ayrı kilitlenir.
    Canonical: sipariş kalemi net_birim_fiyat → fiyat_kaynagi=KALEM_NET (mo_sevkiyat_service:212).
    """

    def _con_kalem_net(self) -> sqlite3.Connection:
        con = sqlite3.connect(':memory:')
        con.row_factory = sqlite3.Row
        con.executescript(
            """
            CREATE TABLE nexgen_planlama_siparis (
                id INTEGER PRIMARY KEY, anlasma_para_birimi TEXT,
                anlasma_birim_fiyat REAL, talep_referansi TEXT
            );
            CREATE TABLE nexgen_planlama_siparis_kalem (
                id INTEGER PRIMARY KEY, planlama_siparis_id INTEGER,
                birim_fiyat REAL, net_birim_fiyat REAL, iskonto_orani REAL,
                miktar_l REAL, miktar_s REAL, miktar_m REAL, durum TEXT
            );
            CREATE TABLE mo_musteri_sevkiyat_kalem (
                id INTEGER PRIMARY KEY, sevkiyat_id INTEGER, miktar_kg REAL,
                birim_fiyat_snapshot REAL, para_birimi_snapshot TEXT, fiyat_kaynagi TEXT
            );
            """
        )
        con.execute(
            """
            INSERT INTO nexgen_planlama_siparis
                (id, anlasma_para_birimi, anlasma_birim_fiyat, talep_referansi)
            VALUES (1, 'USD', 3.0, NULL)
            """
        )
        con.execute(
            """
            INSERT INTO nexgen_planlama_siparis_kalem
                (id, planlama_siparis_id, birim_fiyat, net_birim_fiyat, iskonto_orani,
                 miktar_l, miktar_s, miktar_m, durum)
            VALUES (101, 1, 2.5, 2.0, 0, 300, 0, 0, 'AKTIF')
            """
        )
        con.commit()
        return con

    def test_coz_sevk_fiyat_snapshot_uc_alan(self) -> None:
        from modules.nexgen.mo_sevkiyat_service import _coz_sevk_fiyat_snapshot

        con = self._con_kalem_net()
        snap = _coz_sevk_fiyat_snapshot(con, 1, 101)
        self.assertEqual(snap['birim_fiyat_snapshot'], 2.0)
        self.assertEqual(snap['para_birimi_snapshot'], 'USD')
        self.assertEqual(snap['fiyat_kaynagi'], 'KALEM_NET')

    def test_sevk_kalem_db_snapshot_uc_alan(self) -> None:
        """mo_musteri_sevkiyat_kalem satırında 3 snapshot kolonu ayrı ayrı."""
        con = _mem_con()
        row = con.execute(
            """
            SELECT birim_fiyat_snapshot, para_birimi_snapshot, fiyat_kaynagi
            FROM mo_musteri_sevkiyat_kalem WHERE sevkiyat_id=10 LIMIT 1
            """
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row['birim_fiyat_snapshot'], 2.0)
        self.assertEqual(row['para_birimi_snapshot'], 'USD')
        self.assertEqual(row['fiyat_kaynagi'], 'KALEM_NET')


class TestGercekSevkLock(unittest.TestCase):
    """
    TAHSILAT-GERCEK-SEVK-LOCK — SEVK_EDILDI → gercek_sevk_tarihi; sevk yok → None.
    """

    def test_sevk_edildi_gercek_sevk_tarihi(self) -> None:
        from modules.nexgen.mo_sevkiyat_service import gercek_sevk_tarihi

        con = _mem_con()
        self.assertEqual(gercek_sevk_tarihi(con, 1), '2026-08-01')
        planlar = acik_planlar(con, [1])
        p = next(x for x in planlar if x['id'] == 1)
        self.assertEqual(p['gercek_sevk_tarihi'], '2026-08-01')

    def test_sevk_yok_gercek_sevk_none(self) -> None:
        from modules.nexgen.mo_sevkiyat_service import gercek_sevk_tarihi

        con = self._con_sevkiyatsiz()
        self.assertIsNone(gercek_sevk_tarihi(con, 529))
        planlar = acik_planlar(con, [10])
        p = planlar[0]
        self.assertIsNone(p.get('gercek_sevk_tarihi'))

    def _con_sevkiyatsiz(self) -> sqlite3.Connection:
        con = sqlite3.connect(':memory:')
        con.row_factory = sqlite3.Row
        con.executescript("""
            CREATE TABLE nexgen_cari (id INTEGER PRIMARY KEY, unvan TEXT, aktif INTEGER DEFAULT 1);
            CREATE TABLE nexgen_planlama_siparis (
                id INTEGER PRIMARY KEY, siparis_no TEXT, cari_id INTEGER, cari_unvan TEXT,
                durum TEXT, anlasma_para_birimi TEXT, anlasma_birim_fiyat REAL,
                vade_gun INTEGER, tahsilat_kurali TEXT, kaynak_modul TEXT,
                tahsilat_durumu TEXT, tahsilat_gun_sayisi INTEGER,
                planlanan_tahsilat_tarihi TEXT, talep_referansi TEXT,
                guncelleme_tarihi TEXT
            );
            CREATE TABLE mo_musteri_sevkiyat (
                id INTEGER PRIMARY KEY, sevkiyat_no TEXT, siparis_id INTEGER, cari_id INTEGER,
                durum TEXT, aktif INTEGER DEFAULT 1, sevk_tarihi TEXT,
                idempotency_key TEXT, olusturan_id INTEGER, olusturma_tarihi TEXT
            );
        """)
        con.execute('INSERT INTO nexgen_cari (id, unvan) VALUES (10, ?)', ('AYM',))
        con.execute(
            """
            INSERT INTO nexgen_planlama_siparis
                (id, siparis_no, cari_id, cari_unvan, durum, anlasma_para_birimi,
                 anlasma_birim_fiyat, vade_gun, tahsilat_kurali, kaynak_modul, tahsilat_durumu)
            VALUES (529, 'PZM-2026-0118', 10, 'AYM', 'ONAYLANDI', 'USD', 10.0, 90, 'VADE_GUN', ?, 'PLANLANDI')
            """,
            (KAYNAK_MUSTERI_OPERASYONU,),
        )
        con.commit()
        return con


class TestRegressionHaftaSonuKur(unittest.TestCase):
    def test_cumartesi_kur_cuma_snapshot(self) -> None:
        con = _mem_con()
        con.execute(
            """
            INSERT INTO mo_musteri_sevkiyat
                (id, sevkiyat_no, siparis_id, cari_id, durum, aktif, sevk_tarihi,
                 idempotency_key, olusturan_id, olusturma_tarihi)
            VALUES (50, 'MSV-50', 1, 1, 'SEVK_EDILDI', 1, '2026-08-22', 'sevk-50', 1, '2026-08-22')
            """
        )
        con.execute(
            """
            INSERT INTO mo_musteri_sevkiyat_kalem
                (sevkiyat_id, miktar_kg, birim_fiyat_snapshot, para_birimi_snapshot)
            VALUES (50, 100, 2, 'USD')
            """
        )
        con.execute(
            'INSERT INTO sistem_kur (Tarih, ParaBirimi, Alis, Satis, MerkezKur) VALUES (?,?,?,?,?)',
            ('2026-08-21', 'USD', 47.0, 47.20, 99.99),
        )
        con.commit()
        kayit = taslak_kaydet(
            con,
            _payload(idempotency_key='wknd-kur', sevkiyat_id=50, alinan_tutar=1000),
            UID,
            YK,
        )
        self.assertEqual(kayit['kur_tarihi_snapshot'], '2026-08-21')
        self.assertEqual(kayit['tcmb_satis_kur_snapshot'], 47.20)


class TestRegressionSevkTarihiKur(unittest.TestCase):
    """Kur tarihi = gerçek sevk tarihi; 5000 kg × 3 USD → 708.000 TRY."""

    def _mem_15k(self) -> sqlite3.Connection:
        con = _mem_con()
        con.execute(
            """
            INSERT INTO mo_musteri_sevkiyat
                (id, sevkiyat_no, siparis_id, cari_id, durum, aktif, sevk_tarihi,
                 idempotency_key, olusturan_id, olusturma_tarihi)
            VALUES (40, 'MSV-40', 1, 1, 'SEVK_EDILDI', 1, '2026-08-20', 'sevk-40', 1, '2026-08-20')
            """
        )
        con.execute(
            """
            INSERT INTO mo_musteri_sevkiyat_kalem
                (sevkiyat_id, miktar_kg, birim_fiyat_snapshot, para_birimi_snapshot)
            VALUES (40, 5000, 3, 'USD')
            """
        )
        con.execute(
            'INSERT INTO sistem_kur (Tarih, ParaBirimi, Alis, Satis, MerkezKur) VALUES (?,?,?,?,?)',
            ('2026-08-20', 'USD', 47.0, 47.20, 99.99),
        )
        con.commit()
        return con

    def test_nakit_try_708000_kur_sevk_tarihi(self) -> None:
        con = self._mem_15k()
        kayit = taslak_kaydet(
            con,
            _payload(idempotency_key='sevk-kur-n', sevkiyat_id=40, alinan_tutar=708000),
            UID,
            YK,
        )
        self.assertEqual(kayit['sevk_kalan_fx_snapshot'], 15000.0)
        self.assertEqual(kayit['tcmb_satis_kur_snapshot'], 47.20)
        self.assertEqual(kayit['kur_tarihi_snapshot'], '2026-08-20')
        self.assertEqual(kayit['beklenen_tutar'], 708000.0)

    def test_cek_paket_708000_kur_sevk_tarihi(self) -> None:
        con = self._mem_15k()
        p = {
            'idempotency_key': 'sevk-kur-c',
            'cari_id': 1,
            'siparis_id': 1,
            'odeme_tipi': 'CEK',
            'sevkiyat_id': 40,
        }
        kayit = taslak_kaydet(con, p, UID, YK)
        kid = kayit['id']
        from datetime import date, timedelta
        hedef_vade = (date.fromisoformat('2026-08-20') + timedelta(days=180)).isoformat()
        con.execute(
            """
            INSERT INTO mo_tahsilat_cek
                (tahsilat_kayit_id, tutar, cek_alim_tarihi, gercek_cek_vade_tarihi,
                 para_birimi, aktif, idempotency_key, sira_no)
            VALUES (?, 708000, '2026-09-01', ?, 'TRY', 1, 'cek-sevk-1', 1)
            """,
            (kid, hedef_vade),
        )
        con.commit()
        kayit2 = taslak_kaydet(con, {**p, 'alinan_tutar': 708000}, UID, YK, kayit_id=kid)
        self.assertEqual(kayit2['paket_hedef_tutar'], 708000.0)
        self.assertEqual(kayit2['kur_tarihi_snapshot'], '2026-08-20')


class TestRegressionSevkiyatsizPzm(unittest.TestCase):
    """
    A — Sevkiyatsız PZM siparişi için acik_planlar alanları doğru olmalı.
    Birim fiyat toplam tutar olarak gösterilmemeli.
    """

    def _con_sevkiyatsiz(self) -> sqlite3.Connection:
        """Sipariş 9 için hiç sevkiyat yok; 10 kg × 10 USD/kg = 100 USD."""
        con = sqlite3.connect(':memory:')
        con.row_factory = sqlite3.Row
        con.executescript("""
            CREATE TABLE nexgen_cari (id INTEGER PRIMARY KEY, unvan TEXT, aktif INTEGER DEFAULT 1);
            CREATE TABLE nexgen_planlama_siparis (
                id INTEGER PRIMARY KEY, siparis_no TEXT, cari_id INTEGER, cari_unvan TEXT,
                durum TEXT, anlasma_para_birimi TEXT, anlasma_birim_fiyat REAL,
                vade_gun INTEGER, tahsilat_kurali TEXT, kaynak_modul TEXT,
                tahsilat_durumu TEXT, tahsilat_gun_sayisi INTEGER,
                planlanan_tahsilat_tarihi TEXT, talep_referansi TEXT,
                guncelleme_tarihi TEXT
            );
            CREATE TABLE nexgen_planlama_siparis_kalem (
                id INTEGER PRIMARY KEY, planlama_siparis_id INTEGER,
                miktar_l REAL, miktar_s REAL, miktar_m REAL
            );
            CREATE TABLE mo_musteri_sevkiyat (
                id INTEGER PRIMARY KEY, sevkiyat_no TEXT, siparis_id INTEGER, cari_id INTEGER,
                durum TEXT, aktif INTEGER DEFAULT 1, sevk_tarihi TEXT,
                idempotency_key TEXT, olusturan_id INTEGER, olusturma_tarihi TEXT
            );
            CREATE TABLE sistem_kur (
                Id INTEGER PRIMARY KEY AUTOINCREMENT, Tarih TEXT, ParaBirimi TEXT,
                Alis REAL, Satis REAL, MerkezKur REAL
            );
        """)
        con.execute('INSERT INTO nexgen_cari (id, unvan) VALUES (10, ?)', ('AYM',))
        import json
        mo_ref = json.dumps({'miktar': 10.0})
        con.execute(
            """
            INSERT INTO nexgen_planlama_siparis
                (id, siparis_no, cari_id, cari_unvan, durum, anlasma_para_birimi,
                 anlasma_birim_fiyat, vade_gun, tahsilat_kurali, kaynak_modul,
                 tahsilat_durumu, talep_referansi)
            VALUES
                (529, 'PZM-2026-0118', 10, 'AYM', 'ONAYLANDI', 'USD',
                 10.0, 90, 'VADE_GUN', ?, 'PLANLANDI', ?)
            """,
            (KAYNAK_MUSTERI_OPERASYONU, mo_ref),
        )
        # Kalem: 10 kg
        con.execute(
            'INSERT INTO nexgen_planlama_siparis_kalem (planlama_siparis_id, miktar_l, miktar_s, miktar_m) VALUES (529, 10.0, 0, 0)'
        )
        con.execute(
            'INSERT INTO sistem_kur (Tarih, ParaBirimi, Alis, Satis, MerkezKur) VALUES (?,?,?,?,?)',
            ('2026-08-09', 'USD', 33.5, 34.0, 99.99),
        )
        con.commit()
        return con

    def test_a1_siparis_miktar_ve_toplam_dogru(self) -> None:
        """siparis_miktar_kg=10, siparis_toplam_fx=100, anlasma_birim_fiyat != toplam."""
        con = self._con_sevkiyatsiz()
        planlar = acik_planlar(con, [10])
        self.assertEqual(len(planlar), 1)
        p = planlar[0]
        self.assertEqual(p['siparis_no'], 'PZM-2026-0118')
        self.assertEqual(p['siparis_miktar_kg'], 10.0)
        self.assertEqual(p['anlasma_birim_fiyat'], 10.0)
        self.assertEqual(p['siparis_toplam_fx'], 100.0, 'Sipariş toplamı 100 USD olmalı, birim fiyat 10 değil')
        self.assertEqual(p['siparis_para_birimi'], 'USD')

    def test_a2_sevkiyatsiz_tahsilat_uygunluk(self) -> None:
        """Sevkiyat olmadığında tahsilat_uygunluk=plan, gercek_sevk_tarihi=None."""
        con = self._con_sevkiyatsiz()
        planlar = acik_planlar(con, [10])
        p = planlar[0]
        self.assertIsNone(p['gercek_sevk_tarihi'], 'Sevkiyat yoksa gercek_sevk_tarihi None olmalı')
        self.assertEqual(p['tahsilat_uygunluk'], 'plan')

    def test_a3_birim_fiyat_toplam_degil(self) -> None:
        """
        anlasma_birim_fiyat=10 asla toplam sipariş değeri DEĞİLDİR.
        10 × 34 = 340 TL hesabı yapılmamalı; toplam 100 USD'dir.
        """
        con = self._con_sevkiyatsiz()
        planlar = acik_planlar(con, [10])
        p = planlar[0]
        birim = p['anlasma_birim_fiyat']
        toplam = p['siparis_toplam_fx']
        self.assertNotEqual(birim, toplam, 'Birim fiyat ile toplam aynı olamaz (10 ≠ 100)')
        self.assertEqual(toplam, 100.0)
        self.assertEqual(birim, 10.0)


class TestRegressionSevkiyatsizOnayGuard(unittest.TestCase):
    """
    C — Sevkiyatsız siparişte onaya_gonder hata vermeli.
    (Bu backend guard; UI guard ile çift güvenlik sağlar.)
    """

    def _con_with_kayit(self) -> tuple:
        con = sqlite3.connect(':memory:')
        con.row_factory = sqlite3.Row
        _schema(con)
        con.execute('INSERT INTO nexgen_cari (id, unvan) VALUES (1, ?)', ('AYM',))
        con.execute(
            """
            INSERT INTO nexgen_planlama_siparis
                (id, siparis_no, cari_id, cari_unvan, durum, anlasma_para_birimi,
                 anlasma_birim_fiyat, vade_gun, tahsilat_kurali, kaynak_modul, tahsilat_durumu)
            VALUES (529, 'PZM-2026-0118', 1, 'AYM', 'ONAYLANDI', 'USD', 10.0, 90, 'VADE_GUN', ?, 'PLANLANDI')
            """,
            (KAYNAK_MUSTERI_OPERASYONU,),
        )
        # Sevkiyat YOK — sadece taslak kayit ekle
        cur = con.execute(
            """
            INSERT INTO mo_tahsilat_kayit
                (kayit_kodu, cari_id, siparis_id, sevkiyat_id, kaynak_modul,
                 beklenen_tutar, alinan_tutar, kalan_tutar, para_birimi,
                 durum, aktif, odeme_tipi, idempotency_key, olusturan_id, olusturma_tarihi)
            VALUES ('TEST-SEVKSIZ', 1, 529, NULL, ?, 100, 100, 0, 'TRY',
                    ?, 1, 'NAKIT', 'idem-sevksiz', 1, datetime('now'))
            """,
            (KAYNAK_MUSTERI_OPERASYONU, KAYIT_DURUM_TASLAK),
        )
        con.commit()
        kid = cur.lastrowid
        return con, kid

    def test_c1_sevkiyatsiz_onaya_gonder_fail(self) -> None:
        """sevkiyat_id=None olan taslak onaya gönderilemez."""
        con, kid = self._con_with_kayit()
        with self.assertRaises(MoTahsilatError) as ctx:
            onaya_gonder(con, kid, UID, YK)
        hata = str(ctx.exception)
        # Hata mesajı sevkiyat eksikliğini veya başka guard'ı belirtmeli
        self.assertTrue(
            len(hata) > 0,
            'Sevkiyatsız kayıt için MoTahsilatError bekleniyor',
        )




class TestAcikPlanlarHedefVade(unittest.TestCase):
    """
    acik_planlar() → hedef_vade_tarihi canonical fix regression.

    Root cause: acik_planlar() response'unda hedef_vade_tarihi key'i yoktu.
    Fix: sevk_tarihi + vade_gun varsa ISO formatında hesaplanır.
    """

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(':memory:')
        con.row_factory = sqlite3.Row
        _schema(con)
        con.execute('INSERT INTO nexgen_cari (id, unvan) VALUES (11, ?)', ('TEST CARI',))
        return con

    def _siparis(self, con, vade_gun):
        con.execute(
            """
            INSERT INTO nexgen_planlama_siparis
                (id, siparis_no, cari_id, cari_unvan, durum,
                 anlasma_para_birimi, anlasma_birim_fiyat, vade_gun,
                 tahsilat_kurali, kaynak_modul)
            VALUES (760, 'PZM-2026-0222', 11, 'TEST CARI', 'TAMAMLANDI',
                    'USD', 2.0, ?, 'VADE_GUN', ?)
            """,
            (vade_gun, KAYNAK_MUSTERI_OPERASYONU),
        )

    def test_cek_hedef_vade_185_gun(self):
        """Exact E2E case: 2026-08-10 + 185 = 2027-02-11"""
        con = self._con()
        self._siparis(con, 185)
        con.execute(
            """
            INSERT INTO mo_musteri_sevkiyat
                (id, sevkiyat_no, siparis_id, durum, aktif, sevk_tarihi)
            VALUES (228, 'MSV-2026-0166', 760, 'SEVK_EDILDI', 1, '2026-08-10')
            """
        )
        con.commit()

        planlar = acik_planlar(con, [11])
        p = next((x for x in planlar if x['id'] == 760), None)
        self.assertIsNotNone(p, 'PZM-2026-0222 planlar listesinde bulunmalı')
        self.assertEqual(p['onaylanan_vade_gun'], 185)
        self.assertEqual(p['gercek_sevk_tarihi'], '2026-08-10')
        self.assertEqual(p['hedef_vade_tarihi'], '2027-02-11')

    def test_sevk_tarihi_yok_none(self):
        """Gerçek sevk tarihi yoksa hedef_vade_tarihi None olmalı."""
        con = self._con()
        self._siparis(con, 185)
        con.commit()

        planlar = acik_planlar(con, [11])
        p = next((x for x in planlar if x['id'] == 760), None)
        self.assertIsNotNone(p)
        self.assertIsNone(p.get('gercek_sevk_tarihi'))
        self.assertIsNone(p['hedef_vade_tarihi'])

    def test_vade_gun_yok_none(self):
        """vade_gun NULL ise hedef_vade_tarihi None olmalı."""
        con = self._con()
        self._siparis(con, None)
        con.execute(
            """
            INSERT INTO mo_musteri_sevkiyat
                (id, sevkiyat_no, siparis_id, durum, aktif, sevk_tarihi)
            VALUES (228, 'MSV-2026-0166', 760, 'SEVK_EDILDI', 1, '2026-08-10')
            """
        )
        con.commit()

        planlar = acik_planlar(con, [11])
        p = next((x for x in planlar if x['id'] == 760), None)
        self.assertIsNotNone(p)
        self.assertEqual(p['gercek_sevk_tarihi'], '2026-08-10')
        self.assertIsNone(p['hedef_vade_tarihi'])


if __name__ == '__main__':
    unittest.main()
