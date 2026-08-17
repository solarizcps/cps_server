# -*- coding: utf-8 -*-
"""Aday görüşme → ajanda parity lock (PLANLA / YAPILDI kontratları)."""
from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.mo_ajanda_service import (
    DURUM_GERCEKLESTI,
    DURUM_PLANLANDI,
    MoAjandaError,
    ajanda_listele,
    ajanda_tamamla,
    mo_ajanda_owner_kullanici_id,
)
from modules.nexgen.mo_gorusme_service import (
    MoGorusmeError,
    ajanda_senkron_sonuc_zorunlu,
    gorusme_kaydet,
)
from modules.nexgen.musteri_aday_service import aday_olustur
from modules.nexgen.musteri_pazarlama_service import (
    _ajanda_bugun_isler,
    ajanda_tarih_araligi_listele,
)
from modules.nexgen.musteri_temsilcisi_talep_service import kaydet_gorusme_opsiyonel_talep

UID = 49
UID_ADMIN = 1
UID_OTHER = 88
YK = {'cari360.view': {'can_view': True}, 'cari360.crm_write': {'can_write': True}}
YK_ADMIN = {'cari360.view': {'can_view': True}, 'cari360.crm_write': {'can_write': True}}
HTML = (Path(__file__).resolve().parents[2] / 'app/templates/nexgen/musteri_pazarlama.html').read_text(
    encoding='utf-8',
)
AJANDA_HTML = (
    Path(__file__).resolve().parents[2] / 'app/templates/nexgen/musteri_pazarlama_ajanda.html'
).read_text(encoding='utf-8')


def _schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE nexgen_cari (
            id INTEGER PRIMARY KEY, unvan TEXT, cari_kod TEXT, aktif INTEGER DEFAULT 1
        );
        CREATE TABLE cari_sorumlu (
            id INTEGER PRIMARY KEY AUTOINCREMENT, cari_id INTEGER, kullanici_id INTEGER,
            sorumluluk_rolu TEXT, aktif INTEGER DEFAULT 1, bitis_tarihi TEXT,
            baslangic_tarihi TEXT, atayan_kullanici_id INTEGER
        );
        CREATE TABLE sistem_kullanici (Id INTEGER PRIMARY KEY, KullaniciAdi TEXT, AdSoyad TEXT);
        CREATE TABLE nexgen_musteri_aday (
            id INTEGER PRIMARY KEY AUTOINCREMENT, firma_adi TEXT NOT NULL, yetkili_adi TEXT,
            telefon TEXT, sehir TEXT, not_metni TEXT, durum TEXT NOT NULL DEFAULT 'ADAY',
            olusturan_kullanici_id INTEGER NOT NULL, nexgen_cari_id INTEGER,
            idempotency_key TEXT UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT, donusturulme_tarihi TEXT
        );
        CREATE TABLE musteri_operasyon_ajanda (
            id INTEGER PRIMARY KEY AUTOINCREMENT, cari_id INTEGER, musteri_aday_id INTEGER,
            firma_adi_gorunum TEXT, plan_yetkili_metin TEXT, plan_telefon TEXT, plan_sehir TEXT,
            kullanici_id INTEGER NOT NULL, plan_tarihi TEXT NOT NULL, gorusme_tipi TEXT NOT NULL,
            plan_notu TEXT, durum TEXT NOT NULL DEFAULT 'PLANLANDI', gorusme_id INTEGER,
            idempotency_key TEXT NOT NULL UNIQUE, aktif INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            guncelleme_tarihi TEXT, olusturan_kullanici_id INTEGER NOT NULL,
            CHECK ((cari_id IS NOT NULL AND musteri_aday_id IS NULL)
                OR (cari_id IS NULL AND musteri_aday_id IS NOT NULL)),
            CHECK (durum IN ('PLANLANDI','GERCEKLESTI','IPTAL')),
            CHECK ((durum = 'GERCEKLESTI' AND gorusme_id IS NOT NULL)
                OR (durum IN ('PLANLANDI','IPTAL')))
        );
        CREATE TABLE musteri_operasyon_gorusme (
            id INTEGER PRIMARY KEY AUTOINCREMENT, cari_id INTEGER, musteri_aday_id INTEGER,
            kullanici_id INTEGER, kaynak TEXT, gorusme_tipi TEXT, sonuc_tipi TEXT,
            sonuc_etiketler TEXT, kisa_not TEXT, konu TEXT, sonraki_aksiyon TEXT,
            yetkili_id INTEGER, yetkili_metin TEXT, gorusme_tarihi TEXT,
            sonraki_takip_tarihi TEXT, takip_durumu TEXT, oncelik TEXT DEFAULT 'NORMAL',
            tahmini_siparis_tutari REAL, tahmini_siparis_tarihi TEXT, istenen_vade_gun INTEGER,
            cek_alim_tarihi TEXT, rakip_firma TEXT, makina_notu TEXT, detay_not TEXT,
            dosya_ref TEXT, idempotency_key TEXT UNIQUE, aktif INTEGER DEFAULT 1,
            olusturma_tarihi TEXT, guncelleme_tarihi TEXT, olusturan_kullanici_id INTEGER,
            guncelleyen_kullanici_id INTEGER, audit_json TEXT, numune_talep_id INTEGER,
            fiyat_verildi INTEGER DEFAULT 0, verilen_fiyat REAL, fiyat_para_birimi TEXT,
            fiyat_birimi TEXT, konusulan_tonaj REAL, odeme_tipi TEXT, vade_gun INTEGER,
            cek_vade_gun INTEGER, cek_adedi INTEGER, ticari_not TEXT, cek_notu TEXT
        );
        INSERT INTO nexgen_cari VALUES (9001, 'Cari Lock', 'CL01', 1);
        INSERT INTO cari_sorumlu (cari_id, kullanici_id, sorumluluk_rolu, aktif)
            VALUES (9001, 49, 'ANA', 1);
        INSERT INTO sistem_kullanici VALUES (49, 'erhan', 'Erhan');
        INSERT INTO sistem_kullanici VALUES (1, 'admin', 'Admin');
        INSERT INTO sistem_kullanici VALUES (88, 'other', 'Other');
        """
    )
    con.commit()


def _mem() -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    _schema(con)
    return con


PATCHES = (
    patch('modules.nexgen.musteri_aday_service.can_aday_yaz', return_value=True),
    patch('modules.nexgen.musteri_aday_service.can_aday_gor', return_value=True),
    patch('modules.nexgen.mo_gorusme_service.can_mo_gorusme_yaz_aday', return_value=True),
    patch('modules.nexgen.mo_gorusme_service.can_mo_gorusme_yaz', return_value=True),
)


class AdayGorusmeAjandaParityLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.con = _mem()

    def tearDown(self) -> None:
        self.con.close()

    def _plan_yeni(self, idem: str = 'plan-yeni-1') -> dict:
        with PATCHES[0], PATCHES[1], PATCHES[2]:
            return kaydet_gorusme_opsiyonel_talep(
                self.con,
                {
                    'mod': 'PLANLA',
                    'yeni_musteri': True,
                    'firma_adi': 'yeni taban firmasi',
                    'yetkili_adi': 'Ali Bey',
                    'telefon': '0555',
                    'sehir': 'Urfa',
                    'gorusme_tipi': 'Telefon',
                    'gorusme_tarihi': '2026-08-25 10:00:00',
                    'kisa_not': 'plan notu',
                    'idempotency_key': idem,
                    'kaynak': 'MUSTERI_OPERASYONU',
                },
                UID,
                YK,
            )

    def test_01_aday_gelecek_plan_planlandi(self) -> None:
        out = self._plan_yeni()
        self.assertTrue(out['ok'])
        aj = out['ajanda']
        self.assertEqual(aj['durum'], DURUM_PLANLANDI)
        row = self.con.execute(
            'SELECT * FROM musteri_operasyon_ajanda WHERE id=?', (aj['id'],),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertIsNone(row['cari_id'])
        self.assertIsNotNone(row['musteri_aday_id'])

    def test_02_aday_xor_null_cari(self) -> None:
        out = self._plan_yeni('plan-yeni-2')
        row = self.con.execute(
            'SELECT cari_id, musteri_aday_id FROM musteri_operasyon_ajanda WHERE id=?',
            (out['ajanda']['id'],),
        ).fetchone()
        self.assertIsNone(row['cari_id'])
        self.assertIsNotNone(row['musteri_aday_id'])

    def test_03_firma_adi_gorunum(self) -> None:
        out = self._plan_yeni('plan-yeni-3')
        self.assertEqual(out['ajanda']['firma_adi_gorunum'], 'yeni taban firmasi')

    def test_04_snapshot_alanlari(self) -> None:
        out = self._plan_yeni('plan-yeni-4')
        row = self.con.execute(
            'SELECT plan_yetkili_metin, plan_telefon, plan_sehir '
            'FROM musteri_operasyon_ajanda WHERE id=?',
            (out['ajanda']['id'],),
        ).fetchone()
        self.assertEqual(row['plan_yetkili_metin'], 'Ali Bey')
        self.assertEqual(row['plan_telefon'], '0555')
        self.assertEqual(row['plan_sehir'], 'Urfa')

    def test_05_gecmis_yapildi_gerceklesti_ajanda(self) -> None:
        with PATCHES[0], PATCHES[1], PATCHES[2], patch(
            'modules.nexgen.mo_gorusme_service._istanbul_today',
            return_value=__import__('datetime').date(2026, 8, 17),
        ):
            aid = aday_olustur(
                self.con,
                {'firma_adi': 'aday gecmis', 'idempotency_key': 'aday-g-1'},
                UID,
            )
            kayit = gorusme_kaydet(
                self.con,
                {
                    'mod': 'YAPILDI',
                    'musteri_aday_id': aid,
                    'gorusme_tipi': 'Telefon',
                    'gorusme_tarihi': '2026-08-17 10:00:00',
                    'kisa_not': 'yapildi not',
                    'sonuc_tipi': 'Genel Görüşme',
                    'idempotency_key': 'gor-yap-1',
                },
                UID,
                YK,
                commit=True,
            )
        aj = self.con.execute(
            'SELECT durum, musteri_aday_id, gorusme_id FROM musteri_operasyon_ajanda '
            'WHERE musteri_aday_id=?',
            (aid,),
        ).fetchone()
        self.assertIsNotNone(aj)
        self.assertEqual(aj['durum'], DURUM_GERCEKLESTI)
        self.assertEqual(int(aj['gorusme_id']), int(kayit['id']))

    def test_06_plan_sonuclandirma_ayni_ajanda(self) -> None:
        out = self._plan_yeni('plan-sonuc-1')
        aj_id = int(out['ajanda']['id'])
        aid = int(out['aday']['id'])
        with PATCHES[0], PATCHES[1], PATCHES[2], patch(
            'modules.nexgen.mo_gorusme_service._istanbul_today',
            return_value=__import__('datetime').date(2026, 8, 17),
        ):
            kayit = kaydet_gorusme_opsiyonel_talep(
                self.con,
                {
                    'mod': 'YAPILDI',
                    'musteri_aday_id': aid,
                    'ajanda_id': aj_id,
                    'gorusme_tipi': 'Telefon',
                    'gorusme_tarihi': '2026-08-17 11:00:00',
                    'kisa_not': 'sonuc not',
                    'sonuc_tipi': 'Genel Görüşme',
                    'idempotency_key': 'gor-sonuc-1',
                },
                UID,
                YK,
            )
        rows = self.con.execute(
            'SELECT id, durum, gorusme_id FROM musteri_operasyon_ajanda '
            'WHERE musteri_aday_id=? AND aktif=1',
            (aid,),
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0]['id']), aj_id)
        self.assertEqual(rows[0]['durum'], DURUM_GERCEKLESTI)
        self.assertEqual(int(rows[0]['gorusme_id']), int(kayit['kayit']['id']))

    def test_07_duplicate_plan_idempotent(self) -> None:
        p = {
            'mod': 'PLANLA',
            'yeni_musteri': True,
            'firma_adi': 'dup aday',
            'gorusme_tipi': 'Telefon',
            'gorusme_tarihi': '2026-08-27 10:00:00',
            'kisa_not': 'dup',
            'idempotency_key': 'dup-plan-1',
            'kaynak': 'MUSTERI_OPERASYONU',
        }
        with PATCHES[0], PATCHES[1], PATCHES[2]:
            r1 = kaydet_gorusme_opsiyonel_talep(self.con, p, UID, YK)
            r2 = kaydet_gorusme_opsiyonel_talep(self.con, p, UID, YK)
        self.assertTrue(r2.get('idempotent'))
        cnt = self.con.execute('SELECT COUNT(*) FROM musteri_operasyon_ajanda').fetchone()[0]
        self.assertEqual(cnt, 1)
        self.assertEqual(int(r1['ajanda']['id']), int(r2['ajanda']['id']))

    def test_08_cari_plan_korunur(self) -> None:
        with PATCHES[0], PATCHES[1], PATCHES[2], PATCHES[3], patch(
            'modules.nexgen.mo_ajanda_service.can_mo_gorusme_yaz', return_value=True,
        ):
            out = kaydet_gorusme_opsiyonel_talep(
                self.con,
                {
                    'mod': 'PLANLA',
                    'cari_id': 9001,
                    'gorusme_tipi': 'Telefon',
                    'gorusme_tarihi': '2026-08-28 09:00:00',
                    'kisa_not': 'cari plan',
                    'idempotency_key': 'cari-plan-1',
                    'kaynak': 'MUSTERI_OPERASYONU',
                },
                UID,
                YK,
            )
        row = self.con.execute(
            'SELECT cari_id, musteri_aday_id, durum FROM musteri_operasyon_ajanda WHERE id=?',
            (out['ajanda']['id'],),
        ).fetchone()
        self.assertEqual(int(row['cari_id']), 9001)
        self.assertIsNone(row['musteri_aday_id'])
        self.assertEqual(row['durum'], DURUM_PLANLANDI)

    def test_09_yetkisiz_aday_403(self) -> None:
        with PATCHES[0], patch(
            'modules.nexgen.musteri_aday_service.can_aday_gor', return_value=False,
        ), patch('modules.nexgen.mo_gorusme_service.can_mo_gorusme_yaz_aday', return_value=False):
            aid = aday_olustur(
                self.con,
                {'firma_adi': 'yetkisiz aday', 'idempotency_key': 'aday-y-1'},
                UID_OTHER,
            )
            with self.assertRaises(MoGorusmeError) as ctx:
                kaydet_gorusme_opsiyonel_talep(
                    self.con,
                    {
                        'mod': 'PLANLA',
                        'musteri_aday_id': aid,
                        'gorusme_tipi': 'Telefon',
                        'gorusme_tarihi': '2026-08-29 10:00:00',
                        'kisa_not': 'x',
                        'idempotency_key': 'yetkisiz-1',
                    },
                    UID,
                    YK,
                )
        self.assertEqual(ctx.exception.kod, 403)

    def test_10_gecersiz_aday_404(self) -> None:
        with PATCHES[0], PATCHES[1], PATCHES[2]:
            with self.assertRaises(MoGorusmeError) as ctx:
                kaydet_gorusme_opsiyonel_talep(
                    self.con,
                    {
                        'mod': 'PLANLA',
                        'musteri_aday_id': 99999,
                        'gorusme_tipi': 'Telefon',
                        'gorusme_tarihi': '2026-08-29 11:00:00',
                        'kisa_not': 'x',
                        'idempotency_key': 'yok-1',
                    },
                    UID,
                    YK,
                )
        self.assertEqual(ctx.exception.kod, 404)

    def test_11_plan_without_ajanda_fail(self) -> None:
        with PATCHES[0], PATCHES[1], PATCHES[2], patch(
            'modules.nexgen.mo_gorusme_service.gorusme_planla_kaydet',
            return_value={'ok': True, 'ajanda': {}, 'mesaj': 'broken'},
        ):
            with self.assertRaises(MoGorusmeError):
                kaydet_gorusme_opsiyonel_talep(
                    self.con,
                    {
                        'mod': 'PLANLA',
                        'yeni_musteri': True,
                        'firma_adi': 'fail aday',
                        'gorusme_tipi': 'Telefon',
                        'gorusme_tarihi': '2026-08-30 10:00:00',
                        'idempotency_key': 'fail-plan-1',
                    },
                    UID,
                    YK,
                )

    def test_12_frontend_payload_musteri_aday_id(self) -> None:
        self.assertIn("payload.musteri_aday_id = parseInt(adayId, 10)", HTML)
        self.assertIn('delete payload.yeni_musteri', HTML)

    def test_13_frontend_no_cari_on_aday(self) -> None:
        self.assertIn('delete payload.cari_id', HTML)
        block = HTML.split('else if (adayId)')[1].split('} else {')[0]
        self.assertNotIn('payload.cari_id =', block)

    def test_14_haftalik_liste_aday_plan(self) -> None:
        out = self._plan_yeni('hafta-plan-1')
        with PATCHES[0], PATCHES[1], PATCHES[2], patch(
            'modules.nexgen.mo_ajanda_service._today', return_value='2026-08-17',
        ), patch(
            'modules.nexgen.mo_ajanda_service._hafta_araligi',
            return_value=('2026-08-17', '2026-08-31'),
        ):
            liste = ajanda_listele(self.con, UID, YK, filtre='hafta')
        ids = {int(x['id']) for x in liste}
        self.assertIn(int(out['ajanda']['id']), ids)

    def test_15_haftalik_saya_parity(self) -> None:
        self._plan_yeni('hafta-plan-2')
        with PATCHES[0], PATCHES[1], PATCHES[2], patch(
            'modules.nexgen.mo_ajanda_service._today', return_value='2026-08-17',
        ), patch(
            'modules.nexgen.mo_ajanda_service._hafta_araligi',
            return_value=('2026-08-17', '2026-08-23'),
        ):
            liste = ajanda_listele(self.con, UID, YK, filtre='hafta')
        db_cnt = self.con.execute(
            """
            SELECT COUNT(*) FROM musteri_operasyon_ajanda
            WHERE aktif=1 AND kullanici_id=? AND durum='PLANLANDI'
              AND substr(plan_tarihi,1,10) BETWEEN '2026-08-17' AND '2026-08-23'
              AND musteri_aday_id IS NOT NULL
            """,
            (UID,),
        ).fetchone()[0]
        aday_list = [x for x in liste if x.get('musteri_aday_id')]
        self.assertEqual(len(aday_list), db_cnt)

    def test_16_ajanda_skip_fail_closed(self) -> None:
        with self.assertRaises(MoGorusmeError):
            ajanda_senkron_sonuc_zorunlu({'durum': 'skip', 'sebep': 'aday_migration_eksik'}, baglam='t')

    def test_17_html_explicit_mod_payload(self) -> None:
        self.assertIn('payload.mod = getGorusmeMod()', HTML)

    def test_18_mo_gorusme_no_silent_pass_on_takip(self) -> None:
        src = (
            Path(__file__).resolve().parents[2]
            / 'app/modules/nexgen/mo_gorusme_service.py'
        ).read_text(encoding='utf-8')
        self.assertNotRegex(src, r'ajanda_olustur\(con, takip_payload[\s\S]{0,120}except Exception:\s+pass')

    def _admin_plan_aday(self, idem: str) -> dict:
        with PATCHES[0], PATCHES[1], PATCHES[2], patch(
            'modules.nexgen.mo_ajanda_service.can_mo_gorusme_yaz', return_value=True,
        ):
            return kaydet_gorusme_opsiyonel_talep(
                self.con,
                {
                    'mod': 'PLANLA',
                    'yeni_musteri': True,
                    'firma_adi': 'admin aday plan',
                    'yetkili_adi': 'Veli',
                    'telefon': '0500',
                    'sehir': 'Mardin',
                    'gorusme_tipi': 'Telefon',
                    'gorusme_tarihi': '2026-08-26 09:00:00',
                    'kisa_not': 'admin plan',
                    'idempotency_key': idem,
                    'kaynak': 'MUSTERI_OPERASYONU',
                },
                UID_ADMIN,
                YK_ADMIN,
            )

    def test_19_admin_aday_plan_owner_erhan(self) -> None:
        out = self._admin_plan_aday('admin-aday-owner-1')
        row = self.con.execute(
            'SELECT kullanici_id, olusturan_kullanici_id, cari_id, musteri_aday_id, '
            'plan_yetkili_metin, plan_telefon, plan_sehir, durum '
            'FROM musteri_operasyon_ajanda WHERE id=?',
            (out['ajanda']['id'],),
        ).fetchone()
        self.assertEqual(int(row['kullanici_id']), UID)
        self.assertEqual(int(row['olusturan_kullanici_id']), UID_ADMIN)
        self.assertIsNone(row['cari_id'])
        self.assertIsNotNone(row['musteri_aday_id'])
        self.assertEqual(row['plan_yetkili_metin'], 'Veli')
        self.assertEqual(row['plan_telefon'], '0500')
        self.assertEqual(row['plan_sehir'], 'Mardin')
        self.assertEqual(row['durum'], DURUM_PLANLANDI)

    def test_20_admin_cari_plan_owner_erhan(self) -> None:
        with PATCHES[0], PATCHES[1], PATCHES[2], patch(
            'modules.nexgen.mo_gorusme_service.can_mo_gorusme_yaz', return_value=True,
        ):
            out = kaydet_gorusme_opsiyonel_talep(
                self.con,
                {
                    'mod': 'PLANLA',
                    'cari_id': 9001,
                    'gorusme_tipi': 'Telefon',
                    'gorusme_tarihi': '2026-08-27 09:00:00',
                    'kisa_not': 'admin cari plan',
                    'idempotency_key': 'admin-cari-owner-1',
                    'kaynak': 'MUSTERI_OPERASYONU',
                },
                UID_ADMIN,
                YK_ADMIN,
            )
        row = self.con.execute(
            'SELECT kullanici_id, olusturan_kullanici_id, cari_id, musteri_aday_id '
            'FROM musteri_operasyon_ajanda WHERE id=?',
            (out['ajanda']['id'],),
        ).fetchone()
        self.assertEqual(int(row['kullanici_id']), UID)
        self.assertEqual(int(row['olusturan_kullanici_id']), UID_ADMIN)
        self.assertEqual(int(row['cari_id']), 9001)
        self.assertIsNone(row['musteri_aday_id'])

    def test_21_admin_main_and_ajanda_same_plan_ids(self) -> None:
        out = self._admin_plan_aday('admin-parity-1')
        aj_id = int(out['ajanda']['id'])
        with PATCHES[0], PATCHES[1], PATCHES[2], patch(
            'modules.nexgen.mo_ajanda_service._today', return_value='2026-08-17',
        ), patch(
            'modules.nexgen.mo_ajanda_service._hafta_araligi',
            return_value=('2026-08-17', '2026-08-31'),
        ):
            ana = _ajanda_bugun_isler(self.con, UID_ADMIN, YK_ADMIN)
            sayfa = ajanda_tarih_araligi_listele(
                self.con, UID_ADMIN, YK_ADMIN, '2026-08-17', '2026-08-31',
            )
        ana_ids = {int(x['ajanda_id']) for x in ana['kayitlar_tum'] if x.get('ajanda_id')}
        sayfa_ids = {int(x['id']) for x in sayfa}
        self.assertIn(aj_id, ana_ids)
        self.assertIn(aj_id, sayfa_ids)

    def test_22_erhan_sees_own_plan(self) -> None:
        out = self._plan_yeni('erhan-own-1')
        aj_id = int(out['ajanda']['id'])
        with PATCHES[0], PATCHES[1], PATCHES[2], patch(
            'modules.nexgen.mo_ajanda_service._today', return_value='2026-08-17',
        ), patch(
            'modules.nexgen.mo_ajanda_service._hafta_araligi',
            return_value=('2026-08-17', '2026-08-31'),
        ):
            liste = ajanda_listele(self.con, UID, YK, filtre='hafta')
        self.assertIn(aj_id, {int(x['id']) for x in liste})

    def test_23_admin_no_hidden_uid1_plans(self) -> None:
        self._admin_plan_aday('admin-no-hidden-1')
        cnt = self.con.execute(
            'SELECT COUNT(*) FROM musteri_operasyon_ajanda WHERE kullanici_id=?',
            (UID_ADMIN,),
        ).fetchone()[0]
        self.assertEqual(cnt, 0)

    def test_24_admin_finalize_same_ajanda_id(self) -> None:
        out = self._admin_plan_aday('admin-finalize-1')
        aj_id = int(out['ajanda']['id'])
        aid = int(out['aday']['id'])
        with PATCHES[0], PATCHES[1], PATCHES[2], patch(
            'modules.nexgen.mo_gorusme_service._istanbul_today',
            return_value=__import__('datetime').date(2026, 8, 17),
        ):
            kayit = kaydet_gorusme_opsiyonel_talep(
                self.con,
                {
                    'mod': 'YAPILDI',
                    'musteri_aday_id': aid,
                    'ajanda_id': aj_id,
                    'gorusme_tipi': 'Telefon',
                    'gorusme_tarihi': '2026-08-17 11:00:00',
                    'kisa_not': 'admin sonuc',
                    'sonuc_tipi': 'Genel Görüşme',
                    'idempotency_key': 'admin-finalize-g1',
                },
                UID_ADMIN,
                YK_ADMIN,
            )
        rows = self.con.execute(
            'SELECT id, kullanici_id, durum, gorusme_id FROM musteri_operasyon_ajanda '
            'WHERE musteri_aday_id=? AND aktif=1',
            (aid,),
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0]['id']), aj_id)
        self.assertEqual(int(rows[0]['kullanici_id']), UID)
        self.assertEqual(rows[0]['durum'], DURUM_GERCEKLESTI)
        self.assertEqual(int(rows[0]['gorusme_id']), int(kayit['kayit']['id']))

    def test_25_unauthorized_hedef_owner_403(self) -> None:
        with self.assertRaises(MoAjandaError):
            mo_ajanda_owner_kullanici_id(UID_OTHER, set(), hedef_kullanici_id=UID)

    def test_26_ajanda_html_sonuc_readonly_ayrimi(self) -> None:
        block = AJANDA_HTML.split('function planAksiyonGerekli(k)')[1].split('function planAksiyonMetin')[0]
        self.assertNotIn('ajandaReadonly', block)
        detay = AJANDA_HTML.split('/* ── Aksiyon butonu ── */')[1].split('body.innerHTML = html')[0]
        self.assertNotIn('!ajandaReadonly', detay)

    def test_27_aday_finalize_snapshot_korunur(self) -> None:
        out = self._plan_yeni('snap-final-1')
        aj_id = int(out['ajanda']['id'])
        aid = int(out['aday']['id'])
        with PATCHES[0], PATCHES[1], PATCHES[2], patch(
            'modules.nexgen.mo_gorusme_service._istanbul_today',
            return_value=__import__('datetime').date(2026, 8, 17),
        ):
            kaydet_gorusme_opsiyonel_talep(
                self.con,
                {
                    'mod': 'YAPILDI',
                    'musteri_aday_id': aid,
                    'ajanda_id': aj_id,
                    'gorusme_tipi': 'Telefon',
                    'gorusme_tarihi': '2026-08-17 11:00:00',
                    'kisa_not': 'sonuc not',
                    'sonuc_tipi': 'Genel Görüşme',
                    'idempotency_key': 'snap-final-g1',
                },
                UID,
                YK,
            )
        row = self.con.execute(
            'SELECT cari_id, musteri_aday_id, firma_adi_gorunum, plan_yetkili_metin, '
            'plan_telefon, plan_sehir, plan_notu, durum '
            'FROM musteri_operasyon_ajanda WHERE id=?',
            (aj_id,),
        ).fetchone()
        self.assertIsNone(row['cari_id'])
        self.assertEqual(int(row['musteri_aday_id']), aid)
        self.assertEqual(row['firma_adi_gorunum'], 'yeni taban firmasi')
        self.assertEqual(row['plan_yetkili_metin'], 'Ali Bey')
        self.assertEqual(row['plan_telefon'], '0555')
        self.assertEqual(row['plan_sehir'], 'Urfa')
        self.assertEqual(row['plan_notu'], 'plan notu')
        self.assertEqual(row['durum'], DURUM_GERCEKLESTI)
        aj2 = self.con.execute(
            'SELECT gorusme_id FROM musteri_operasyon_ajanda WHERE id=?', (aj_id,),
        ).fetchone()
        g = self.con.execute(
            'SELECT cari_id, musteri_aday_id FROM musteri_operasyon_gorusme WHERE id=?',
            (aj2['gorusme_id'],),
        ).fetchone()
        self.assertIsNone(g['cari_id'])
        self.assertEqual(int(g['musteri_aday_id']), aid)

    def test_28_cari_plan_finalize_regression(self) -> None:
        with PATCHES[0], PATCHES[1], PATCHES[2], PATCHES[3], patch(
            'modules.nexgen.mo_ajanda_service.can_mo_gorusme_yaz', return_value=True,
        ):
            out = kaydet_gorusme_opsiyonel_talep(
                self.con,
                {
                    'mod': 'PLANLA',
                    'cari_id': 9001,
                    'gorusme_tipi': 'Telefon',
                    'gorusme_tarihi': '2026-08-28 09:00:00',
                    'kisa_not': 'cari plan',
                    'idempotency_key': 'cari-final-1',
                    'kaynak': 'MUSTERI_OPERASYONU',
                },
                UID,
                YK,
            )
        aj_id = int(out['ajanda']['id'])
        with PATCHES[0], PATCHES[1], PATCHES[2], PATCHES[3], patch(
            'modules.nexgen.mo_ajanda_service.can_mo_gorusme_yaz', return_value=True,
        ), patch(
            'modules.nexgen.mo_gorusme_service._istanbul_today',
            return_value=__import__('datetime').date(2026, 8, 17),
        ):
            kayit = kaydet_gorusme_opsiyonel_talep(
                self.con,
                {
                    'mod': 'YAPILDI',
                    'cari_id': 9001,
                    'ajanda_id': aj_id,
                    'gorusme_tipi': 'Telefon',
                    'gorusme_tarihi': '2026-08-17 10:00:00',
                    'kisa_not': 'cari sonuc',
                    'sonuc_tipi': 'Genel Görüşme',
                    'idempotency_key': 'cari-final-g1',
                },
                UID,
                YK,
            )
        rows = self.con.execute(
            'SELECT id, durum, cari_id, musteri_aday_id, gorusme_id '
            'FROM musteri_operasyon_ajanda WHERE cari_id=9001 AND aktif=1',
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0]['id']), aj_id)
        self.assertEqual(rows[0]['durum'], DURUM_GERCEKLESTI)
        self.assertIsNone(rows[0]['musteri_aday_id'])
        self.assertEqual(int(rows[0]['gorusme_id']), int(kayit['kayit']['id']))

    def test_29_ikinci_finalize_fail_safe(self) -> None:
        out = self._plan_yeni('dup-final-1')
        aj_id = int(out['ajanda']['id'])
        aid = int(out['aday']['id'])
        payload = {
            'mod': 'YAPILDI',
            'musteri_aday_id': aid,
            'ajanda_id': aj_id,
            'gorusme_tipi': 'Telefon',
            'gorusme_tarihi': '2026-08-17 11:00:00',
            'kisa_not': 'sonuc',
            'sonuc_tipi': 'Genel Görüşme',
            'idempotency_key': 'dup-final-g1',
        }
        with PATCHES[0], PATCHES[1], PATCHES[2], patch(
            'modules.nexgen.mo_gorusme_service._istanbul_today',
            return_value=__import__('datetime').date(2026, 8, 17),
        ):
            kaydet_gorusme_opsiyonel_talep(self.con, payload, UID, YK)
            with self.assertRaises(MoAjandaError) as ctx:
                ajanda_tamamla(self.con, aj_id, 9999, UID, None, YK, musteri_aday_id=aid, commit=False)
        self.assertIn(ctx.exception.kod, (404, 409))
        cnt = self.con.execute('SELECT COUNT(*) FROM musteri_operasyon_ajanda WHERE aktif=1').fetchone()[0]
        self.assertEqual(cnt, 1)

    def test_30_haftalik_saya_finalize_sonrasi(self) -> None:
        with PATCHES[0], PATCHES[1], PATCHES[2]:
            out = kaydet_gorusme_opsiyonel_talep(
                self.con,
                {
                    'mod': 'PLANLA',
                    'yeni_musteri': True,
                    'firma_adi': 'hafta saya aday',
                    'yetkili_adi': 'Ali',
                    'telefon': '0555',
                    'sehir': 'Urfa',
                    'gorusme_tipi': 'Telefon',
                    'gorusme_tarihi': '2026-08-20 10:00:00',
                    'kisa_not': 'plan notu',
                    'idempotency_key': 'hafta-final-1',
                    'kaynak': 'MUSTERI_OPERASYONU',
                },
                UID,
                YK,
            )
        aj_id = int(out['ajanda']['id'])
        aid = int(out['aday']['id'])
        with PATCHES[0], PATCHES[1], PATCHES[2], patch(
            'modules.nexgen.mo_ajanda_service._today', return_value='2026-08-17',
        ), patch(
            'modules.nexgen.mo_ajanda_service._hafta_araligi',
            return_value=('2026-08-17', '2026-08-23'),
        ):
            onceki = ajanda_listele(self.con, UID, YK, filtre='hafta')
        plan_once = sum(1 for x in onceki if (x.get('durum') or '').upper() == DURUM_PLANLANDI)
        tam_once = sum(1 for x in onceki if (x.get('durum') or '').upper() == DURUM_GERCEKLESTI)
        with PATCHES[0], PATCHES[1], PATCHES[2], patch(
            'modules.nexgen.mo_gorusme_service._istanbul_today',
            return_value=__import__('datetime').date(2026, 8, 17),
        ):
            kaydet_gorusme_opsiyonel_talep(
                self.con,
                {
                    'mod': 'YAPILDI',
                    'musteri_aday_id': aid,
                    'ajanda_id': aj_id,
                    'gorusme_tipi': 'Telefon',
                    'gorusme_tarihi': '2026-08-17 11:00:00',
                    'kisa_not': 'sonuc',
                    'sonuc_tipi': 'Genel Görüşme',
                    'idempotency_key': 'hafta-final-g1',
                },
                UID,
                YK,
            )
        with PATCHES[0], PATCHES[1], PATCHES[2], patch(
            'modules.nexgen.mo_ajanda_service._today', return_value='2026-08-17',
        ), patch(
            'modules.nexgen.mo_ajanda_service._hafta_araligi',
            return_value=('2026-08-17', '2026-08-23'),
        ):
            sonra = ajanda_listele(self.con, UID, YK, filtre='hafta')
        plan_sonra = sum(1 for x in sonra if (x.get('durum') or '').upper() == DURUM_PLANLANDI)
        tam_sonra = sum(1 for x in sonra if (x.get('durum') or '').upper() == DURUM_GERCEKLESTI)
        self.assertEqual(plan_sonra, plan_once - 1)
        self.assertEqual(tam_sonra, tam_once + 1)

    def test_31_finalize_yetkisiz_403(self) -> None:
        out = self._plan_yeni('yetkisiz-final-1')
        aj_id = int(out['ajanda']['id'])
        aid = int(out['aday']['id'])
        with PATCHES[0], patch(
            'modules.nexgen.musteri_aday_service.can_aday_gor', return_value=False,
        ), patch('modules.nexgen.mo_gorusme_service.can_mo_gorusme_yaz_aday', return_value=False):
            with self.assertRaises(MoGorusmeError) as ctx:
                kaydet_gorusme_opsiyonel_talep(
                    self.con,
                    {
                        'mod': 'YAPILDI',
                        'musteri_aday_id': aid,
                        'ajanda_id': aj_id,
                        'gorusme_tipi': 'Telefon',
                        'gorusme_tarihi': '2026-08-17 11:00:00',
                        'kisa_not': 'yetkisiz not',
                        'sonuc_tipi': 'Genel Görüşme',
                        'idempotency_key': 'yetkisiz-final-g1',
                    },
                    UID_OTHER,
                    YK,
                )
        self.assertEqual(ctx.exception.kod, 403)

    def test_32_gecersiz_ajanda_finalize_404(self) -> None:
        out = self._plan_yeni('gecersiz-final-1')
        aid = int(out['aday']['id'])
        with PATCHES[0], PATCHES[1], PATCHES[2], patch(
            'modules.nexgen.mo_gorusme_service._istanbul_today',
            return_value=__import__('datetime').date(2026, 8, 17),
        ):
            with self.assertRaises(MoGorusmeError) as ctx:
                kaydet_gorusme_opsiyonel_talep(
                    self.con,
                    {
                        'mod': 'YAPILDI',
                        'musteri_aday_id': aid,
                        'ajanda_id': 99999,
                        'gorusme_tipi': 'Telefon',
                        'gorusme_tarihi': '2026-08-17 11:00:00',
                        'kisa_not': 'gecersiz not',
                        'sonuc_tipi': 'Genel Görüşme',
                        'idempotency_key': 'gecersiz-final-g1',
                    },
                    UID,
                    YK,
                )
        self.assertEqual(ctx.exception.kod, 404)

    def test_33_ajanda_zorunlu_gate_aday_param(self) -> None:
        self.assertIn('musteri_aday_id={{ z.musteri_aday_id }}', AJANDA_HTML)
        self.assertIn('ajanda_sonuc=1', AJANDA_HTML.split('mpa-zorunlu-uyari-liste')[1][:800])


if __name__ == '__main__':
    unittest.main()
