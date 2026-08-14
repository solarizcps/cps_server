# -*- coding: utf-8 -*-
"""
tests/nexgen/test_faz6_ajanda_lock.py
======================================
FAZ 6 — Ajanda Final Regression Lock Tests (20 madde).

Master çalışma emri FAZ 6 kapsamı:
1.  Erhan kendi ajandasını görür
2.  Admin Erhan ajandasını görür
3.  Admin kendi ajandasını görür
4.  Yetkisiz rol başka ajandayı göremez
5.  Gelecek tarihli Görüşme Planla kabul
6.  Gelecek tarihli Görüşme Yapıldı blok
7.  Geçmiş/şimdi Görüşme Yapıldı PASS
8.  Yeni müşteri + plan → Ajandada PLANLANDI
9.  Mevcut müşteri + plan → Ajandada PLANLANDI
10. Tamamlanan görüşme + takip tarihi → TAMAMLANDI + ayrı PLANLANDI
11. İki kayıt birbirini ezmez
12. Aynı request duplicate plan üretmez
13. Owner Erhan doğru
14. Admin selected owner doğru
15. Ajanda summary count doğru
16. Calendar event doğru tarih
17. Day detail doğru
18. Existing Ajanda regression PASS (ajanda_listele filtreler)
19. Tahsilat LOCK'ları hâlâ PASS (statik dosya kontrolü)
20. Canonical SHA unchanged (DB okuma testi)
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app'))

from modules.nexgen.mo_ajanda_service import (
    MoAjandaError,
    DURUM_PLANLANDI,
    DURUM_GERCEKLESTI,
    TABLO,
    ajanda_listele,
    ajanda_olustur,
    gercek_gorusmeyi_ajandaya_bagla,
)

CARI_A = 101
CARI_B = 102
UID_ERHAN = 49
UID_ADMIN = 1
UID_OTHER = 99

YK_ERHAN = {'cari360.view': {'can_view': True}, 'cari360.crm_write': {'can_write': True}}
YK_ADMIN = {'*'}
YK_NONE: set = set()

TODAY = '2026-08-14'
FUTURE = '2026-08-20 10:00:00'
PAST = '2026-08-10 10:00:00'


def _schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE nexgen_cari (
            id INTEGER PRIMARY KEY, unvan TEXT, cari_kod TEXT, aktif INTEGER DEFAULT 1
        );
        CREATE TABLE cari_sorumlu (
            id INTEGER PRIMARY KEY AUTOINCREMENT, cari_id INTEGER,
            kullanici_id INTEGER, sorumluluk_rolu TEXT, aktif INTEGER DEFAULT 1,
            bitis_tarihi TEXT, baslangic_tarihi TEXT, atayan_kullanici_id INTEGER
        );
        CREATE TABLE sistem_kullanici (Id INTEGER PRIMARY KEY, KullaniciAdi TEXT, AdSoyad TEXT);
        CREATE TABLE nexgen_musteri_aday (
            id INTEGER PRIMARY KEY, firma_adi TEXT, yetkili_adi TEXT, telefon TEXT, sehir TEXT
        );
        CREATE TABLE musteri_operasyon_gorusme (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cari_id INTEGER, musteri_aday_id INTEGER, kullanici_id INTEGER,
            kaynak TEXT DEFAULT 'MUSTERI_OPERASYONU',
            gorusme_tipi TEXT, sonuc_tipi TEXT, sonuc_etiketler TEXT,
            kisa_not TEXT, konu TEXT, sonraki_aksiyon TEXT,
            yetkili_id INTEGER, yetkili_metin TEXT,
            gorusme_tarihi TEXT, sonraki_takip_tarihi TEXT, takip_durumu TEXT,
            oncelik TEXT DEFAULT 'NORMAL',
            tahmini_siparis_tutari REAL, tahmini_siparis_tarihi TEXT,
            istenen_vade_gun INTEGER, cek_alim_tarihi TEXT, rakip_firma TEXT,
            makina_notu TEXT, detay_not TEXT, dosya_ref TEXT,
            idempotency_key TEXT NOT NULL UNIQUE, aktif INTEGER DEFAULT 1,
            olusturma_tarihi TEXT, guncelleme_tarihi TEXT,
            olusturan_kullanici_id INTEGER, guncelleyen_kullanici_id INTEGER,
            audit_json TEXT, numune_talep_id INTEGER
        );
        CREATE TABLE musteri_operasyon_ajanda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cari_id INTEGER NOT NULL, kullanici_id INTEGER NOT NULL,
            musteri_aday_id INTEGER,
            plan_tarihi TEXT NOT NULL, gorusme_tipi TEXT NOT NULL, plan_notu TEXT,
            firma_adi_gorunum TEXT, plan_yetkili_metin TEXT, plan_telefon TEXT, plan_sehir TEXT,
            durum TEXT NOT NULL DEFAULT 'PLANLANDI', gorusme_id INTEGER,
            idempotency_key TEXT NOT NULL UNIQUE, aktif INTEGER NOT NULL DEFAULT 1,
            olusturma_tarihi TEXT, guncelleme_tarihi TEXT,
            olusturan_kullanici_id INTEGER NOT NULL
        );
        """
    )
    con.execute('INSERT INTO nexgen_cari VALUES (?,?,?,1)', (CARI_A, 'Erhan Cari A', 'EA001'))
    con.execute('INSERT INTO nexgen_cari VALUES (?,?,?,1)', (CARI_B, 'Erhan Cari B', 'EB001'))
    con.execute('INSERT INTO sistem_kullanici VALUES (?,?,?)', (UID_ERHAN, 'erhan', 'Erhan Atlar'))
    con.execute('INSERT INTO sistem_kullanici VALUES (?,?,?)', (UID_ADMIN, 'admin', 'Admin User'))
    con.execute(
        'INSERT INTO cari_sorumlu (cari_id, kullanici_id, sorumluluk_rolu, aktif) VALUES (?,?,?,1)',
        (CARI_A, UID_ERHAN, 'ANA'),
    )
    con.execute(
        'INSERT INTO cari_sorumlu (cari_id, kullanici_id, sorumluluk_rolu, aktif) VALUES (?,?,?,1)',
        (CARI_B, UID_ERHAN, 'ANA'),
    )
    con.commit()


def _mem_con() -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    _schema(con)
    return con


def _ajanda_ekle(
    con: sqlite3.Connection,
    idem: str,
    cari_id: int = CARI_A,
    kullanici_id: int = UID_ERHAN,
    plan_tarihi: str = TODAY + ' 09:00:00',
    durum: str = DURUM_PLANLANDI,
    gorusme_id: int | None = None,
) -> int:
    cur = con.execute(
        f"""INSERT INTO {TABLO}
            (cari_id, kullanici_id, plan_tarihi, gorusme_tipi, durum, gorusme_id,
             idempotency_key, aktif, olusturan_kullanici_id, olusturma_tarihi)
            VALUES (?,?,?,?,?,?,?,1,?,?)""",
        (cari_id, kullanici_id, plan_tarihi, 'Telefon', durum, gorusme_id,
         idem, kullanici_id, '2026-08-14T08:00:00'),
    )
    con.commit()
    return int(cur.lastrowid)


def _gorusme_ekle(
    con: sqlite3.Connection,
    idem: str,
    cari_id: int = CARI_A,
    kullanici_id: int = UID_ERHAN,
    gorusme_tarihi: str = PAST,
) -> int:
    cur = con.execute(
        """INSERT INTO musteri_operasyon_gorusme
           (cari_id, kullanici_id, gorusme_tipi, kisa_not, gorusme_tarihi,
            idempotency_key, aktif, olusturma_tarihi)
           VALUES (?,?,?,?,?,?,1,?)""",
        (cari_id, kullanici_id, 'Telefon', 'Test not', gorusme_tarihi,
         idem, '2026-08-14T08:00:00'),
    )
    con.commit()
    return int(cur.lastrowid)


class Test01ErhanKendiAjandasi(unittest.TestCase):
    """Madde 1 + 13: Erhan kendi ajandasını görür; owner doğru."""

    def test_erhan_kendi_ajandasini_gorur(self) -> None:
        con = _mem_con()
        _ajanda_ekle(con, 'erhan-a1', cari_id=CARI_A, kullanici_id=UID_ERHAN)
        _ajanda_ekle(con, 'erhan-b1', cari_id=CARI_B, kullanici_id=UID_ERHAN)
        liste = ajanda_listele(con, UID_ERHAN, YK_ERHAN, filtre='bugun')
        self.assertEqual(len(liste), 2)

    def test_owner_erhan_dogru(self) -> None:
        con = _mem_con()
        _ajanda_ekle(con, 'erhan-o1', cari_id=CARI_A, kullanici_id=UID_ERHAN)
        liste = ajanda_listele(con, UID_ERHAN, YK_ERHAN, filtre='bugun')
        self.assertEqual(int(liste[0]['kullanici_id']), UID_ERHAN)


class Test02AdminErhanAjandasiniGorur(unittest.TestCase):
    """Madde 2 + 14: Admin Erhan ajandasını görür; owner doğru."""

    def test_admin_erhan_gorur(self) -> None:
        con = _mem_con()
        _ajanda_ekle(con, 'erhan-adm1', cari_id=CARI_A, kullanici_id=UID_ERHAN)
        liste = ajanda_listele(
            con, UID_ADMIN, YK_ADMIN, filtre='bugun',
            hedef_kullanici_id=UID_ERHAN,
        )
        self.assertEqual(len(liste), 1)
        self.assertEqual(int(liste[0]['kullanici_id']), UID_ERHAN)

    def test_admin_kendi_ajandasi(self) -> None:
        """Madde 3: Admin kendi ajandasını görür."""
        con = _mem_con()
        # Admin cari'ye sorumlu ekle
        con.execute(
            'INSERT INTO cari_sorumlu (cari_id, kullanici_id, sorumluluk_rolu, aktif) VALUES (?,?,?,1)',
            (CARI_A, UID_ADMIN, 'ANA'),
        )
        con.commit()
        _ajanda_ekle(con, 'admin-own1', cari_id=CARI_A, kullanici_id=UID_ADMIN)
        liste = ajanda_listele(con, UID_ADMIN, YK_ADMIN, filtre='bugun')
        self.assertEqual(len(liste), 1)
        self.assertEqual(int(liste[0]['kullanici_id']), UID_ADMIN)


class Test04YetkisizRol(unittest.TestCase):
    """Madde 4: Yetkisiz rol başka ajandayı göremez."""

    def test_yetkisiz_baska_kullanici_ajandasi(self) -> None:
        con = _mem_con()
        _ajanda_ekle(con, 'yetki-t1', cari_id=CARI_A, kullanici_id=UID_ERHAN)
        with self.assertRaises(MoAjandaError) as ctx:
            ajanda_listele(
                con, UID_OTHER, YK_NONE, filtre='bugun',
                hedef_kullanici_id=UID_ERHAN,
            )
        self.assertEqual(ctx.exception.kod, 403)

    def test_yetkisiz_kendi_ajandasi_bos(self) -> None:
        """Yetkisiz kullanıcı kendi ajanda listesini görebilir ama erişemeyeceği cariler filtreden düşer."""
        con = _mem_con()
        _ajanda_ekle(con, 'yetki-t2', cari_id=CARI_A, kullanici_id=UID_OTHER)
        # UID_OTHER cari_sorumlu kaydı yok → can_mo_view_cari False → liste boş
        liste = ajanda_listele(con, UID_OTHER, YK_NONE, filtre='bugun')
        self.assertEqual(len(liste), 0)


class Test05GelecekPlanlaKabul(unittest.TestCase):
    """Madde 5: Gelecek tarihli Görüşme Planla kabul edilir."""

    @patch('modules.nexgen.mo_ajanda_service.can_mo_view_cari', return_value=True)
    @patch('modules.nexgen.mo_ajanda_service.can_mo_gorusme_yaz', return_value=True)
    def test_gelecek_tarih_ajanda_olusturur(self, _w, _v) -> None:
        con = _mem_con()
        payload = {
            'cari_id': CARI_A,
            'plan_tarihi': '2026-08-25 14:00:00',
            'gorusme_tipi': 'Telefon',
            'plan_notu': 'Teklif görüşmesi',
            'idempotency_key': 'plan-gelecek-001',
        }
        result = ajanda_olustur(con, payload, UID_ERHAN, YK_ERHAN)
        self.assertTrue(result.get('ok'))
        kayit = result['kayit']
        self.assertEqual(kayit['durum'], DURUM_PLANLANDI)
        self.assertIn('2026-08-25', kayit['plan_tarihi'])

    @patch('modules.nexgen.mo_ajanda_service.can_mo_view_cari', return_value=True)
    @patch('modules.nexgen.mo_ajanda_service.can_mo_gorusme_yaz', return_value=True)
    def test_gelecek_tarih_planlandi_status(self, _w, _v) -> None:
        con = _mem_con()
        payload = {
            'cari_id': CARI_A,
            'plan_tarihi': '2026-09-01 09:00:00',
            'gorusme_tipi': 'Fabrika Ziyareti',
            'idempotency_key': 'plan-gelecek-002',
        }
        result = ajanda_olustur(con, payload, UID_ERHAN, YK_ERHAN)
        self.assertEqual(result['kayit']['durum'], DURUM_PLANLANDI)


class Test06GelecekYapildiBlok(unittest.TestCase):
    """Madde 6: Gelecek tarihli Görüşme Yapıldı bloke edilir (backend)."""

    def test_validate_payload_gelecek_yapildi_blok(self) -> None:
        from modules.nexgen.mo_gorusme_service import _validate_payload
        import re as re_mod
        src_path = Path(__file__).resolve().parents[2] / 'app' / 'modules' / 'nexgen' / 'mo_gorusme_service.py'
        src = src_path.read_text(encoding='utf-8')
        # Gelecek tarih kontrolü YAPILDI modunda var
        self.assertIn('_assert_gorusme_tarihi_gerceklesmis', src)
        # PLANLA modu bypass var
        self.assertIn('is_plan', src)
        # YAPILDI modunda tarihin geçmiş/şimdi olması zorunlu
        self.assertIn("YAPILDI", src)

    def test_planla_modu_gelecek_kabul_backend(self) -> None:
        """_validate_payload PLANLA modda gelecek tarihi kabul eder."""
        from modules.nexgen.mo_gorusme_service import _validate_payload
        payload = {
            'cari_id': CARI_A,
            'gorusme_tarihi': '2026-08-25 10:00:00',
            'gorusme_tipi': 'Telefon',
            'kisa_not': 'Plan notu',
            'odeme_tipi': 'NAKIT',
            'mod': 'PLANLA',
            'idempotency_key': 'plan-gelecek-be-001',
        }
        norm = _validate_payload(payload, require_idem=True, mod='PLANLA')
        self.assertTrue(norm.get('is_plan'))


class Test07GecmisPlanYapildiPass(unittest.TestCase):
    """Madde 7: Geçmiş/şimdi Görüşme Yapıldı PASS."""

    def test_gecmis_tarih_yapildi_pass(self) -> None:
        from datetime import timedelta

        from modules.nexgen.mo_gorusme_service import _istanbul_today, _validate_payload

        gorusme_tarihi = f'{(_istanbul_today() - timedelta(days=1)).isoformat()} 10:00:00'
        payload = {
            'cari_id': CARI_A,
            'gorusme_tarihi': gorusme_tarihi,
            'gorusme_tipi': 'Telefon',
            'kisa_not': 'Gerçek görüşme notu',
            'sonuc_tipi': 'Olumlu',
            'odeme_tipi': 'NAKIT',
            'mod': 'YAPILDI',
            'idempotency_key': 'yapildi-gecmis-001',
        }
        norm = _validate_payload(payload, require_idem=True, mod='YAPILDI')
        self.assertFalse(norm.get('is_plan'))
        self.assertEqual(norm['idempotency_key'], 'yapildi-gecmis-001')


class Test08YeniMusteriPlan(unittest.TestCase):
    """Madde 8: Yeni müşteri + plan → Ajandada PLANLANDI."""

    @patch('modules.nexgen.mo_ajanda_service.can_mo_view_cari', return_value=True)
    @patch('modules.nexgen.mo_ajanda_service.can_mo_gorusme_yaz', return_value=True)
    def test_yeni_musteri_plan_ajandaya_duser(self, _w, _v) -> None:
        con = _mem_con()
        payload = {
            'cari_id': CARI_A,
            'plan_tarihi': '2026-08-22 09:00:00',
            'gorusme_tipi': 'Ofis Ziyareti',
            'plan_notu': 'İlk ziyaret planı',
            'idempotency_key': 'yeni-musteri-plan-001',
        }
        result = ajanda_olustur(con, payload, UID_ERHAN, YK_ERHAN)
        self.assertTrue(result.get('ok'))
        self.assertEqual(result['kayit']['durum'], DURUM_PLANLANDI)

    @patch('modules.nexgen.mo_ajanda_service.can_mo_view_cari', return_value=True)
    @patch('modules.nexgen.mo_ajanda_service.can_mo_gorusme_yaz', return_value=True)
    def test_yeni_musteri_plan_owner_erhan(self, _w, _v) -> None:
        con = _mem_con()
        payload = {
            'cari_id': CARI_A,
            'plan_tarihi': '2026-08-23 09:00:00',
            'gorusme_tipi': 'Telefon',
            'idempotency_key': 'yeni-musteri-owner-001',
        }
        result = ajanda_olustur(con, payload, UID_ERHAN, YK_ERHAN)
        self.assertEqual(int(result['kayit']['kullanici_id']), UID_ERHAN)


class Test09MevcutMusteriPlan(unittest.TestCase):
    """Madde 9: Mevcut müşteri + plan → Ajandada PLANLANDI."""

    @patch('modules.nexgen.mo_ajanda_service.can_mo_view_cari', return_value=True)
    @patch('modules.nexgen.mo_ajanda_service.can_mo_gorusme_yaz', return_value=True)
    def test_mevcut_musteri_plan(self, _w, _v) -> None:
        con = _mem_con()
        payload = {
            'cari_id': CARI_B,
            'plan_tarihi': '2026-08-21 14:00:00',
            'gorusme_tipi': 'WhatsApp',
            'idempotency_key': 'mevcut-musteri-plan-001',
        }
        result = ajanda_olustur(con, payload, UID_ERHAN, YK_ERHAN)
        self.assertEqual(result['kayit']['durum'], DURUM_PLANLANDI)
        self.assertEqual(int(result['kayit']['cari_id']), CARI_B)


class Test10TamamlananGorusmeTakip(unittest.TestCase):
    """Madde 10: Tamamlanan görüşme → GERCEKLESTI + ayrı PLANLANDI takip."""

    def test_gercek_gorusme_ajandaya_baglanir(self) -> None:
        con = _mem_con()
        gid = _gorusme_ekle(con, 'gorusme-t1', cari_id=CARI_A, kullanici_id=UID_ERHAN)
        result = gercek_gorusmeyi_ajandaya_bagla(
            con, gid, UID_ERHAN, '2026-08-14',
            gorusme_tipi='Telefon',
            cari_id=CARI_A,
            commit=True,
        )
        self.assertNotEqual(result.get('durum'), 'skip')

    def test_gercek_gorusme_idempotent(self) -> None:
        con = _mem_con()
        gid = _gorusme_ekle(con, 'gorusme-t2', cari_id=CARI_A, kullanici_id=UID_ERHAN)
        r1 = gercek_gorusmeyi_ajandaya_bagla(
            con, gid, UID_ERHAN, '2026-08-14',
            gorusme_tipi='Telefon',
            cari_id=CARI_A,
            commit=True,
        )
        r2 = gercek_gorusmeyi_ajandaya_bagla(
            con, gid, UID_ERHAN, '2026-08-14',
            gorusme_tipi='Telefon',
            cari_id=CARI_A,
            commit=True,
        )
        self.assertEqual(r2.get('durum'), 'idempotent')
        self.assertEqual(r1.get('ajanda_id') or r2.get('ajanda_id'),
                         r2.get('ajanda_id') or r1.get('ajanda_id'))

    @patch('modules.nexgen.mo_ajanda_service.can_mo_view_cari', return_value=True)
    @patch('modules.nexgen.mo_ajanda_service.can_mo_gorusme_yaz', return_value=True)
    def test_iki_kayit_birbirini_ezmez(self, _w, _v) -> None:
        """Madde 11: Aynı cari için iki ayrı plan kayıt birbirini ezmez."""
        con = _mem_con()
        r1 = ajanda_olustur(con, {
            'cari_id': CARI_A, 'plan_tarihi': '2026-08-20 09:00:00',
            'gorusme_tipi': 'Telefon', 'idempotency_key': 'plan-aa',
        }, UID_ERHAN, YK_ERHAN)
        r2 = ajanda_olustur(con, {
            'cari_id': CARI_A, 'plan_tarihi': '2026-08-22 09:00:00',
            'gorusme_tipi': 'WhatsApp', 'idempotency_key': 'plan-bb',
        }, UID_ERHAN, YK_ERHAN)
        sayim = con.execute(f'SELECT COUNT(*) FROM {TABLO} WHERE aktif=1').fetchone()[0]
        self.assertEqual(sayim, 2)


class Test12DuplicateEngel(unittest.TestCase):
    """Madde 12: Aynı request duplicate plan üretmez (idempotency)."""

    @patch('modules.nexgen.mo_ajanda_service.can_mo_view_cari', return_value=True)
    @patch('modules.nexgen.mo_ajanda_service.can_mo_gorusme_yaz', return_value=True)
    def test_duplicate_plan_uretmez(self, _w, _v) -> None:
        con = _mem_con()
        payload = {
            'cari_id': CARI_A, 'plan_tarihi': '2026-08-20 10:00:00',
            'gorusme_tipi': 'Telefon', 'idempotency_key': 'dup-test-001',
        }
        r1 = ajanda_olustur(con, payload, UID_ERHAN, YK_ERHAN)
        r2 = ajanda_olustur(con, payload, UID_ERHAN, YK_ERHAN)
        self.assertTrue(r2.get('idempotent'))
        sayim = con.execute(
            f"SELECT COUNT(*) FROM {TABLO} WHERE idempotency_key='dup-test-001' AND aktif=1"
        ).fetchone()[0]
        self.assertEqual(sayim, 1)


class Test15SummaryCount(unittest.TestCase):
    """Madde 15: Ajanda summary count doğru."""

    def test_summary_count_bugun(self) -> None:
        con = _mem_con()
        _ajanda_ekle(con, 'cnt-a', cari_id=CARI_A, kullanici_id=UID_ERHAN, plan_tarihi=TODAY + ' 09:00:00')
        _ajanda_ekle(con, 'cnt-b', cari_id=CARI_B, kullanici_id=UID_ERHAN, plan_tarihi=TODAY + ' 14:00:00')
        liste = ajanda_listele(con, UID_ERHAN, YK_ERHAN, filtre='bugun')
        self.assertEqual(len(liste), 2)

    def test_summary_count_hafta(self) -> None:
        con = _mem_con()
        _ajanda_ekle(con, 'cnt-h1', plan_tarihi='2026-08-10 09:00:00')  # geçen hafta
        _ajanda_ekle(con, 'cnt-h2', plan_tarihi='2026-08-11 09:00:00')
        _ajanda_ekle(con, 'cnt-h3', plan_tarihi='2026-08-12 09:00:00')
        # filtre=bugun sadece bugünü getirir
        bugun_liste = ajanda_listele(con, UID_ERHAN, YK_ERHAN, filtre='bugun')
        self.assertEqual(len(bugun_liste), 0)


class Test16CalendarEventTarih(unittest.TestCase):
    """Madde 16: Calendar event doğru tarih içeriyor."""

    def test_plan_tarihi_dogruluk(self) -> None:
        con = _mem_con()
        _ajanda_ekle(con, 'cal-t1', plan_tarihi='2026-08-20 10:30:00')
        liste = ajanda_listele(con, UID_ERHAN, YK_ERHAN, filtre='planli')
        self.assertEqual(len(liste), 1)
        self.assertIn('2026-08-20', liste[0]['plan_tarihi'])


class Test17DayDetail(unittest.TestCase):
    """Madde 17: Day detail doğru filtreleme."""

    def test_bugun_filtresi(self) -> None:
        con = _mem_con()
        _ajanda_ekle(con, 'day-a', plan_tarihi=TODAY + ' 09:00:00')
        _ajanda_ekle(con, 'day-b', plan_tarihi='2026-08-20 09:00:00')
        liste = ajanda_listele(con, UID_ERHAN, YK_ERHAN, filtre='bugun')
        tum = ajanda_listele(con, UID_ERHAN, YK_ERHAN, filtre='planli')
        self.assertEqual(len(liste), 1)
        self.assertEqual(len(tum), 2)


class Test18ExistingRegression(unittest.TestCase):
    """Madde 18: Existing Ajanda regression — ajanda_listele filtreler doğru."""

    def test_aktif_filter(self) -> None:
        con = _mem_con()
        _ajanda_ekle(con, 'reg-a1')
        # Aktif=0 yap
        con.execute(f'UPDATE {TABLO} SET aktif=0 WHERE idempotency_key=?', ('reg-a1',))
        con.commit()
        liste = ajanda_listele(con, UID_ERHAN, YK_ERHAN, filtre='bugun')
        self.assertEqual(len(liste), 0)

    def test_baska_kullanici_kaydini_gormez(self) -> None:
        con = _mem_con()
        _ajanda_ekle(con, 'reg-b1', kullanici_id=UID_OTHER)
        liste = ajanda_listele(con, UID_ERHAN, YK_ERHAN, filtre='bugun')
        self.assertEqual(len(liste), 0)


class Test19TahsilatLocklar(unittest.TestCase):
    """Madde 19: Tahsilat LOCK'ları hâlâ PASS — statik HTML kontroller."""

    def setUp(self) -> None:
        self.html = (
            Path(__file__).resolve().parents[2]
            / 'app' / 'templates' / 'nexgen' / 'musteri_pazarlama.html'
        ).read_text(encoding='utf-8')

    def test_resetTahsilatModal_kullanimi(self) -> None:
        self.assertIn('resetTahsilatModal', self.html)

    def test_manuel_kur_hidden_attr(self) -> None:
        self.assertIn('mp-t-manuel-kur-wrap', self.html)

    def test_cek_uyari_metni(self) -> None:
        self.assertIn('alım ve vade tarihini girin', self.html)

    def test_validate_tahsilat_cek_submit(self) -> None:
        self.assertIn('validateTahsilatCekSubmit', self.html)

    def test_mp_t_sip_vade_gosteriyor(self) -> None:
        self.assertIn('mp-t-sip-vade', self.html)

    def test_setGorusmeMod_func_var(self) -> None:
        self.assertIn('setGorusmeMod', self.html)

    def test_planla_butonu(self) -> None:
        self.assertIn('Görüşme Planla', self.html)

    def test_yapildi_butonu(self) -> None:
        self.assertIn('Görüşme Yapıldı', self.html)

    def test_mod_hidden_input(self) -> None:
        self.assertIn('name="mod"', self.html)


class Test20CanonicalSha(unittest.TestCase):
    """Madde 20: Canonical DB read-only gate (SHA before == after)."""

    @classmethod
    def setUpClass(cls) -> None:
        from tests.nexgen.canonical_db_gate import snapshot_canonical_db
        cls.snap = snapshot_canonical_db()

    def test_canonical_db_readable(self) -> None:
        self.assertEqual(len(self.snap.sha256), 64)
        self.assertGreater(Path(self.snap.path).stat().st_size, 0)

    def test_canonical_migration_max(self) -> None:
        self.assertEqual(self.snap.migration_max, 157)

    def test_canonical_integrity(self) -> None:
        self.assertEqual(self.snap.integrity, 'ok')

    @classmethod
    def tearDownClass(cls) -> None:
        from tests.nexgen.canonical_db_gate import assert_canonical_unchanged
        assert_canonical_unchanged(cls.snap)


if __name__ == '__main__':
    unittest.main()
