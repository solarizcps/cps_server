# -*- coding: utf-8 -*-
"""
C360-HAFIZA-DEDUPE-LOCK — Timeline/Hafıza duplicate + post-process dar lock.

Temporary in-memory SQLite only — canonical app/mock_data.db kullanılmaz.
HEAD inline duplicate davranışı bu dosyada simüle edilir; production değiştirilmez.
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

SVC = Path(__file__).resolve().parents[2] / 'app'
sys.path.insert(0, str(SVC))

from modules.nexgen.cari360_dosya_service import (  # noqa: E402
    _fmt_tl,
    _hafiza_satir,
    _tablo_var,
    _test_mi,
    hafiza_liste,
)
from modules.nexgen.cari360_timeline_service import build_ops_timeline  # noqa: E402
from modules.nexgen.cari360_yetki import can_cari360_finans_view  # noqa: E402

_CARI_ID = 1
_UID = 1
_YK = {'*'}
_TAHSILAT_ID = 501
_ONAY_ID = 601
_MTT_ONAY_ID = 701
_SIPARIS_ID = 100


def _build_dedupe_fixture_db() -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE sistem_kullanici (
            Id INTEGER PRIMARY KEY, KullaniciAdi TEXT, AdSoyad TEXT, Aktif INTEGER DEFAULT 1
        );
        INSERT INTO sistem_kullanici VALUES (1, 'erhan', 'Erhan Atlar', 1);

        CREATE TABLE nexgen_cari (
            id INTEGER PRIMARY KEY, cari_kod TEXT, unvan TEXT, aktif INTEGER DEFAULT 1,
            created_at TEXT, updated_at TEXT
        );
        INSERT INTO nexgen_cari VALUES
        (1, '120.NX.009', '3E Test', 1, '2026-07-01 08:00:00', '2026-07-01 08:00:00');

        CREATE TABLE cari_sorumlu (
            id INTEGER PRIMARY KEY, cari_id INTEGER, kullanici_id INTEGER,
            sorumluluk_rolu TEXT, aktif INTEGER DEFAULT 1,
            baslangic_tarihi TEXT, bitis_tarihi TEXT, created_at TEXT,
            atayan_kullanici_id INTEGER
        );
        INSERT INTO cari_sorumlu VALUES
        (1, 1, 1, 'ANA', 1, '2026-07-01', NULL, '2026-07-01 08:00:00', 1);

        CREATE TABLE musteri_operasyon_gorusme (
            id INTEGER PRIMARY KEY, cari_id INTEGER, kullanici_id INTEGER,
            olusturan_kullanici_id INTEGER, gorusme_tipi TEXT, sonuc_tipi TEXT,
            kisa_not TEXT, gorusme_tarihi TEXT, olusturma_tarihi TEXT, aktif INTEGER DEFAULT 1,
            takip_durumu TEXT, konu TEXT, numune_talep_id INTEGER, idempotency_key TEXT
        );
        INSERT INTO musteri_operasyon_gorusme VALUES
        (501, 1, 1, 1, 'Telefon', 'Olumlu', 'Gercek gorusme',
         '2026-08-10 12:00:00', '2026-08-10 12:00:00', 1, NULL, 'Konu', NULL, 'gor-501');

        CREATE TABLE musteri_operasyon_ajanda (
            id INTEGER PRIMARY KEY, cari_id INTEGER, kullanici_id INTEGER,
            plan_tarihi TEXT, gorusme_tipi TEXT, plan_notu TEXT, durum TEXT,
            gorusme_id INTEGER, idempotency_key TEXT, aktif INTEGER DEFAULT 1,
            olusturma_tarihi TEXT, guncelleme_tarihi TEXT, olusturan_kullanici_id INTEGER,
            plan_yetkili_metin TEXT, musteri_aday_id INTEGER, firma_adi_gorunum TEXT
        );
        INSERT INTO musteri_operasyon_ajanda VALUES
        (10, 1, 1, '2026-09-01 10:30:00', 'Telefon', 'Plan notu test', 'PLANLANDI',
         NULL, 'aj-plan-10', 1, '2026-08-08 14:00:00', '2026-08-08 14:00:00', 1, NULL, NULL, '3E');

        CREATE TABLE nexgen_planlama_siparis (
            id INTEGER PRIMARY KEY, siparis_no TEXT, cari_id INTEGER, durum TEXT,
            olusturma_tarihi TEXT, guncelleme_tarihi TEXT, olusturan_id INTEGER,
            notlar TEXT, talep_referansi TEXT, idempotency_key TEXT,
            anlasma_birim_fiyat REAL, tahsilat_kurali TEXT, planlanan_tahsilat_tarihi TEXT,
            tahsilat_durumu TEXT, tahsilat_sozu TEXT
        );
        INSERT INTO nexgen_planlama_siparis VALUES
        (100, 'PZM-TEST-100', 1, 'ONAYLANDI', '2026-08-01 10:00:00', '2026-08-01 10:00:00', 1,
         '', '', '', NULL, NULL, NULL, NULL, NULL);

        CREATE TABLE nexgen_uretim_plan (
            id INTEGER PRIMARY KEY, plan_kodu TEXT, durum TEXT, created_at TEXT,
            plan_tarihi TEXT, created_by INTEGER, cari_id INTEGER,
            planlama_siparis_id INTEGER, siparis_no TEXT, termin_tarihi TEXT
        );
        INSERT INTO nexgen_uretim_plan VALUES
        (20, 'NP-TEST-20', 'TAMAMLANDI', '2026-08-02 08:00:00', '2026-08-02', 1, 1, 100, 'PZM-TEST-100', NULL);

        CREATE TABLE nexgen_uretim_batch (id INTEGER PRIMARY KEY, plan_id INTEGER);
        INSERT INTO nexgen_uretim_batch VALUES (1, 20);

        CREATE TABLE nexgen_uretim_parca (
            id INTEGER PRIMARY KEY, plan_id INTEGER, batch_id INTEGER, durum TEXT,
            baslama_zamani TEXT, bitis_zamani TEXT
        );
        INSERT INTO nexgen_uretim_parca VALUES
        (1, 20, 1, 'TAMAMLANDI', '2026-08-03 09:00:00', '2026-08-04 17:00:00');

        CREATE TABLE mo_musteri_sevkiyat (
            id INTEGER PRIMARY KEY, sevkiyat_no TEXT, siparis_id INTEGER, cari_id INTEGER,
            durum TEXT, sevk_tarihi TEXT, olusturma_tarihi TEXT, guncelleme_tarihi TEXT,
            olusturan_id INTEGER, aktif INTEGER DEFAULT 1
        );
        INSERT INTO mo_musteri_sevkiyat VALUES
        (301, 'SV-HAZ', 100, 1, 'HAZIRLANIYOR', NULL, '2026-08-10 08:00:00', '2026-08-10 08:00:00', 1, 1);

        CREATE TABLE mo_tahsilat_kayit (
            id INTEGER PRIMARY KEY, cari_id INTEGER, siparis_id INTEGER,
            durum TEXT, odeme_tipi TEXT, alinan_tarih TEXT, alinan_tutar REAL,
            beklenen_tutar REAL, aktif INTEGER DEFAULT 1, aciklama TEXT,
            kayit_kodu TEXT, guncelleme_tarihi TEXT, revizyon_gerekce TEXT
        );
        INSERT INTO mo_tahsilat_kayit VALUES
        (501, 1, 100, 'ONAYLANDI', 'NAKIT', '2026-08-05 14:30:00', 125000.50,
         125000.50, 1, 'Canonical tahsilat', 'TH-501', '2026-08-05 15:00:00', NULL),
        (502, 1, 100, 'ONAYLANDI', 'NAKIT', '2026-12-31 10:00:00', 999.00,
         999.00, 1, 'Future tahsilat fixture', 'TH-502', '2026-12-31 10:00:00', NULL);

        CREATE TABLE onay_talep (
            id INTEGER PRIMARY KEY, cari_id INTEGER, talep_kod TEXT, talep_tipi TEXT,
            kaynak_modul TEXT, kaynak_id INTEGER, kaynak_kod TEXT, durum TEXT,
            tutar REAL, para_birimi TEXT, talep_tarihi TEXT, created_at TEXT, updated_at TEXT
        );
        INSERT INTO onay_talep VALUES
        (601, 1, 'ON-TEST-601', 'SATIS_SIPARISI', 'PAZARLAMA', 100, 'PZM-TEST-100',
         'ONAYLANDI', 50000, 'TRY', '2026-08-06 09:00:00', '2026-08-06 09:00:00', '2026-08-06 10:00:00'),
        (602, 1, 'ON-TEST-602', 'NUMUNE_TALEBI', 'NUMUNE', 1, 'NP-X',
         'BEKLIYOR', 0, 'TRY', '2026-08-07 09:00:00', '2026-08-07 09:00:00', '2026-08-07 09:00:00');

        CREATE TABLE nexgen_musteri_temsilcisi_talep (
            id INTEGER PRIMARY KEY, cari_id INTEGER, talep_no TEXT, talep_turu TEXT,
            durum TEXT, created_at TEXT, updated_at TEXT,
            isleme_alinma_tarihi TEXT, donusturulme_tarihi TEXT,
            donusturulen_siparis_id INTEGER, donusturulen_numune_talep_id INTEGER
        );
        INSERT INTO nexgen_musteri_temsilcisi_talep VALUES
        (801, 1, 'MTT-801', 'SIPARIS', 'ONAYLANDI', '2026-08-04 08:00:00', '2026-08-04 09:00:00',
         NULL, NULL, NULL, NULL);

        CREATE TABLE nexgen_onay (
            id INTEGER PRIMARY KEY, onay_no TEXT, onay_turu TEXT, durum TEXT,
            kaynak_turu TEXT, kaynak_id INTEGER, karar_tarihi TEXT, red_nedeni TEXT,
            created_at TEXT, onaylayan_kullanici_id INTEGER
        );
        INSERT INTO nexgen_onay VALUES
        (701, 'NX-701', 'SIPARIS_TALEBI_ONAY', 'ONAYLANDI',
         'MUSTERI_TEMSILCISI_TALEP', 801, '2026-08-04 09:30:00', NULL,
         '2026-08-04 08:00:00', 1);

        CREATE TABLE nexgen_arge_test (
            id INTEGER PRIMARY KEY, test_no TEXT, cari_id INTEGER,
            durum TEXT, olusturma_tarihi TEXT, olusturan_id INTEGER,
            rf_renk_id INTEGER, talep_referansi TEXT, yeni_renk_adi TEXT,
            renk_kodu TEXT, formul_grup_adi TEXT, ana_formul_grup_kodu TEXT,
            aktif INTEGER DEFAULT 1
        );
        INSERT INTO nexgen_arge_test VALUES
        (1, 'AR-TEST-1', 1, 'CALISILIYOR', '2026-08-09 10:00:00', 1,
         NULL, NULL, NULL, NULL, NULL, NULL, 1);

        CREATE TABLE nexgen_arge_olay (
            id INTEGER PRIMARY KEY, arge_test_id INTEGER, olay_tipi TEXT,
            aciklama TEXT, eski_durum TEXT, yeni_durum TEXT, olusturma_tarihi TEXT
        );
        INSERT INTO nexgen_arge_olay VALUES
        (1, 1, 'DURUM_DEGISIM', 'Legacy ARGE satir', 'TASLAK', 'CALISILIYOR', '2026-08-09 11:00:00');
        """
    )
    return con


def _hafiza(con: sqlite3.Connection, **kw) -> list[dict]:
    return hafiza_liste(con, _CARI_ID, _UID, _YK, **kw)


def _by_kod(evs: list[dict], kod: str) -> list[dict]:
    return [e for e in evs if e.get('olay_kodu') == kod]


def _tahsilat_for_id(evs: list[dict], tid: int) -> list[dict]:
    out = []
    for e in evs:
        if e.get('olay_kodu') == 'TAHSILAT' and int(e.get('entity_id') or 0) == tid:
            out.append(e)
        elif e.get('source_type') == 'mo_tahsilat_kayit' and int(e.get('source_id') or 0) == tid:
            out.append(e)
    return out


def _simulate_head_inline_events(con: sqlite3.Connection, cari_id: int, yk: set[str]) -> list[dict]:
    """HEAD d0a154b inline tahsilat + onay loop'larını production dosyasına dokunmadan simüle eder."""
    events: list[dict] = []
    seen: set[str] = set()
    finans_ok = can_cari360_finans_view(yk or set())
    kart_base = f'/nexgen/cari360/{cari_id}'

    def _add(ev: dict) -> None:
        dk = ev.get('dedupe_key')
        if not dk or dk in seen:
            return
        seen.add(dk)
        events.append(ev)

    ops_events, _ = build_ops_timeline(con, cari_id)
    for ev in ops_events:
        _add(ev)

    if finans_ok and _tablo_var(con, 'mo_tahsilat_kayit'):
        for r in con.execute(
            """SELECT tk.*, ps.siparis_no FROM mo_tahsilat_kayit tk
               LEFT JOIN nexgen_planlama_siparis ps ON ps.id=tk.siparis_id
               WHERE tk.cari_id=? AND tk.aktif=1 ORDER BY tk.guncelleme_tarihi DESC""",
            (cari_id,),
        ).fetchall():
            d = dict(r)
            if _test_mi(d.get('aciklama'), d.get('kayit_kodu')):
                continue
            durum = (d.get('durum') or '').upper()
            bas = {
                'ONAYLANDI': 'Tahsilat alındı',
                'MUHASEBE_ONAY_BEKLIYOR': 'Tahsilat — Muhasebe onayında',
                'REVIZYON_ISTENDI': 'Tahsilat — Revizyon istendi',
                'REDDEDILDI': 'Tahsilat — Reddedildi',
            }.get(durum, 'Tahsilat kaydı')
            _add(_hafiza_satir(
                event_date=d.get('alinan_tarih') or d.get('guncelleme_tarihi') or '',
                hareket_turu='Tahsilat',
                baslik=bas,
                aciklama=d.get('aciklama') or d.get('kayit_kodu') or '',
                durum=durum.replace('_', ' '),
                source_type='mo_tahsilat_kayit',
                source_id=d['id'],
                kayit_no=d.get('kayit_kodu') or str(d['id']),
                tutar=_fmt_tl(float(d.get('alinan_tutar') or 0)),
                kategori='tahsilatlar',
                metadata={'revizyon_gerekce': d.get('revizyon_gerekce'), 'siparis_no': d.get('siparis_no')},
                detay_url=f'{kart_base}?tab=siparisler',
                oncelik=89,
            ))

    if _tablo_var(con, 'onay_talep'):
        for r in con.execute(
            "SELECT * FROM onay_talep WHERE cari_id=? ORDER BY talep_tarihi DESC", (cari_id,),
        ).fetchall():
            d = dict(r)
            durum = (d.get('durum') or '').upper()
            if durum not in ('REVIZYON', 'REDDEDILDI', 'ONAYLANDI', 'BEKLIYOR', 'ONAY_BEKLIYOR'):
                continue
            notu = ''
            if _tablo_var(con, 'onay_talep_adim'):
                a = con.execute(
                    """SELECT karar_notu FROM onay_talep_adim
                       WHERE talep_id=? AND durum IN ('REVIZYON','REDDEDILDI','TAMAMLANDI')
                       ORDER BY id DESC LIMIT 1""", (d['id'],),
                ).fetchone()
                if a:
                    notu = a['karar_notu'] or ''
            lbl = {
                'ONAYLANDI': 'Onaylandı', 'REVIZYON': 'Revizyon', 'REDDEDILDI': 'Red',
                'BEKLIYOR': 'Onay bekliyor', 'ONAY_BEKLIYOR': 'Onay bekliyor',
            }.get(durum, durum)
            _add(_hafiza_satir(
                event_date=d.get('updated_at') or d.get('talep_tarihi') or '',
                hareket_turu='Onay',
                baslik=f"Merkezi Onay — {lbl}",
                aciklama=notu or str(d.get('talep_kod') or d['id']),
                durum=lbl,
                source_type='onay_talep',
                source_id=d['id'],
                kayit_no=str(d.get('talep_kod') or d['id']),
                kategori='onaylar',
                detay_url=f'{kart_base}?tab=genel',
                oncelik=84,
            ))

    return events


_TEKNIK_TUR = frozenset({
    'AR-GE', 'RF', 'Numune gelişme', 'Pazarlamacı',
    'Üretim', 'Üretim Planı', 'Cari',
})
_IZINLI_TUR = frozenset({
    'Görüşme', 'Numune', 'Sipariş', 'Çek', 'Tahsilat', 'Tahsilat Planı', 'Sevkiyat', 'Onay',
})


def _apply_wt_postprocess(events: list[dict], *, entity_type: str | None = None) -> list[dict]:
    """Working-tree hafiza_liste post-process mirror (sadece test doğrulama)."""
    out: list[dict] = []
    for e in events:
        if not e.get('event_date') and e.get('olay_tarihi'):
            e = dict(e)
            e['event_date'] = e['olay_tarihi']
        elif not e.get('olay_tarihi') and e.get('event_date'):
            e = dict(e)
            e['olay_tarihi'] = e['event_date']

        tur = e.get('hareket_turu') or ''
        olay_kodu = e.get('olay_kodu') or ''
        if not olay_kodu and tur in _TEKNIK_TUR:
            continue
        if not olay_kodu and tur and tur not in _IZINLI_TUR:
            continue
        if not e.get('baslik') and not olay_kodu:
            continue

        if entity_type:
            et = (e.get('entity_type') or e.get('source_type') or '')
            if et != entity_type and olay_kodu != entity_type:
                continue
        out.append(e)

    out.sort(
        key=lambda x: (
            (x.get('event_date') or x.get('olay_tarihi') or ''),
            x.get('oncelik') or 0,
            int(x['entity_id']) if str(x.get('entity_id', '')).isdigit() else 0,
        ),
        reverse=True,
    )
    return out


class HeadVsWorkingTreeDedupeTests(unittest.TestCase):
    """HEAD duplicate kanıtı vs working-tree tek-event kanıtı."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.con = _build_dedupe_fixture_db()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.con.close()

    def test_head_simulation_duplicate_tahsilat_source(self) -> None:
        head_evs = _simulate_head_inline_events(self.con, _CARI_ID, _YK)
        dup = _tahsilat_for_id(head_evs, _TAHSILAT_ID)
        self.assertEqual(len(dup), 2, 'HEAD: aynı tahsilat source iki farklı dedupe_key ile gelir')
        keys = {e.get('dedupe_key') for e in dup}
        self.assertIn(f'TAHSILAT:{_TAHSILAT_ID}', keys)
        self.assertTrue(any(str(k).startswith('mo_tahsilat_kayit:') for k in keys))

    def test_working_tree_single_tahsilat_event(self) -> None:
        wt_evs = _hafiza(self.con)
        canonical = _by_kod(wt_evs, 'TAHSILAT')
        same_id = [e for e in canonical if int(e.get('entity_id') or 0) == _TAHSILAT_ID]
        self.assertEqual(len(same_id), 1)
        inline = [e for e in wt_evs if e.get('source_type') == 'mo_tahsilat_kayit' and not e.get('olay_kodu')]
        self.assertEqual(len(inline), 0, 'WT: inline tahsilat loop yok')

    def test_head_vs_wt_event_count_delta(self) -> None:
        head = _simulate_head_inline_events(self.con, _CARI_ID, _YK)
        wt = _hafiza(self.con)
        head_dup = len(_tahsilat_for_id(head, _TAHSILAT_ID))
        wt_one = len([e for e in _by_kod(wt, 'TAHSILAT') if int(e.get('entity_id') or 0) == _TAHSILAT_ID])
        self.assertEqual(head_dup, 2)
        self.assertEqual(wt_one, 1)
        self.assertGreater(len(head), len(wt))


class TahsilatDedupeLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.con = _build_dedupe_fixture_db()
        cls.evs = _hafiza(cls.con)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.con.close()

    def test_01_single_tahsilat_event_per_source_id(self) -> None:
        rows = [e for e in _by_kod(self.evs, 'TAHSILAT') if int(e.get('entity_id') or 0) == _TAHSILAT_ID]
        self.assertEqual(len(rows), 1)

    def test_02_tahsilat_tutar_from_canonical_timeline(self) -> None:
        ev = next(e for e in _by_kod(self.evs, 'TAHSILAT') if int(e['entity_id']) == _TAHSILAT_ID)
        self.assertIn('125,000.50', ev.get('aciklama') or '')

    def test_03_tahsilat_tarih_from_canonical_timeline(self) -> None:
        ev = next(e for e in _by_kod(self.evs, 'TAHSILAT') if int(e['entity_id']) == _TAHSILAT_ID)
        self.assertTrue(str(ev.get('olay_tarihi') or ev.get('event_date') or '').startswith('2026-08-05'))

    def test_04_future_tahsilat_not_removed_by_dedupe_fix(self) -> None:
        future = [e for e in _by_kod(self.evs, 'TAHSILAT') if int(e.get('entity_id') or 0) == 502]
        self.assertEqual(len(future), 1)
        self.assertTrue(str(future[0].get('olay_tarihi') or '').startswith('2026-12-31'))


class OnayDedupeLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.con = _build_dedupe_fixture_db()
        cls.evs = _hafiza(cls.con)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.con.close()

    def test_05_single_onay_talep_event_per_source(self) -> None:
        rows = [e for e in _by_kod(self.evs, 'ONAY_TALEBI') if int(e.get('entity_id') or 0) == _ONAY_ID]
        self.assertEqual(len(rows), 1)
        inline = [e for e in self.evs if e.get('source_type') == 'onay_talep' and not e.get('olay_kodu')]
        self.assertEqual(len(inline), 0)

    def test_06_single_mtt_onay_event_per_source(self) -> None:
        rows = [e for e in _by_kod(self.evs, 'MTT_ONAY') if int(e.get('entity_id') or 0) == _MTT_ONAY_ID]
        self.assertEqual(len(rows), 1)

    def test_07_different_onay_sources_both_preserved(self) -> None:
        self.assertEqual(len(_by_kod(self.evs, 'ONAY_TALEBI')), 2)
        self.assertEqual(len(_by_kod(self.evs, 'MTT_ONAY')), 1)

    def test_08_dedupe_only_collapses_same_dedupe_key(self) -> None:
        head = _simulate_head_inline_events(self.con, _CARI_ID, _YK)
        onay601 = [e for e in head if (
            (e.get('olay_kodu') == 'ONAY_TALEBI' and int(e.get('entity_id') or 0) == _ONAY_ID)
            or (e.get('source_type') == 'onay_talep' and not e.get('olay_kodu') and int(e.get('source_id') or 0) == _ONAY_ID)
        )]
        self.assertEqual(len(onay601), 2)


class PostProcessLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.con = _build_dedupe_fixture_db()
        cls.evs = _hafiza(cls.con)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.con.close()

    def test_09_event_date_olay_tarihi_normalized(self) -> None:
        raw = [{'olay_tarihi': '2026-08-10 12:00:00', 'baslik': 'x', 'hareket_turu': 'Sipariş'}]
        out = _apply_wt_postprocess(raw)
        self.assertEqual(out[0]['event_date'], out[0]['olay_tarihi'])

    def test_10_sort_date_desc(self) -> None:
        dates = [(e.get('event_date') or e.get('olay_tarihi') or '') for e in self.evs]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_11_empty_baslik_legacy_filtered(self) -> None:
        raw = [
            {'hareket_turu': 'Cari', 'baslik': '', 'olay_kodu': '', 'event_date': '2026-01-01'},
            {'olay_kodu': 'SIPARIS_CREATED', 'baslik': 'Sipariş', 'event_date': '2026-02-01'},
        ]
        out = _apply_wt_postprocess(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['olay_kodu'], 'SIPARIS_CREATED')

    def test_12_canonical_siparis_event_preserved(self) -> None:
        self.assertTrue(any(e.get('olay_kodu') == 'SIPARIS_CREATED' for e in self.evs))

    def test_13_technical_legacy_arge_filtered(self) -> None:
        self.assertFalse(any(e.get('hareket_turu') == 'AR-GE' and not e.get('olay_kodu') for e in self.evs))

    def test_14_entity_type_filter_uses_olay_kodu(self) -> None:
        filtered = _hafiza(self.con, entity_type='ONAY_TALEBI')
        self.assertTrue(all(
            (e.get('entity_type') == 'onay_talep' or e.get('olay_kodu') == 'ONAY_TALEBI')
            for e in filtered
        ))
        self.assertGreater(len(filtered), 0)


class CanonicalEventPreservationLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.con = _build_dedupe_fixture_db()
        cls.evs = _hafiza(cls.con)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.con.close()

    def test_15_gorusme_events_preserved(self) -> None:
        self.assertTrue(any(e.get('olay_kodu') == 'GORUSME_CREATED' for e in self.evs))

    def test_16_siparis_events_preserved(self) -> None:
        self.assertTrue(any(e.get('olay_kodu', '').startswith('SIPARIS') for e in self.evs))

    def test_17_uretim_events_preserved(self) -> None:
        self.assertTrue(any(e.get('olay_kodu') == 'URETIM_STARTED' for e in self.evs))
        self.assertTrue(any(e.get('olay_kodu') == 'URETIM_COMPLETED' for e in self.evs))

    def test_18_sevkiyat_events_preserved(self) -> None:
        self.assertTrue(any(e.get('olay_kodu') == 'SEVKIYAT' for e in self.evs))

    def test_19_ajanda_plan_events_preserved(self) -> None:
        self.assertTrue(any(e.get('olay_kodu') == 'GORUSME_PLANLANDI' for e in self.evs))

    def test_20_hafiza_liste_no_tahsilat_db_write(self) -> None:
        writes: list[str] = []

        class _TrackCon:
            __slots__ = ('_inner',)

            def __init__(self, inner: sqlite3.Connection) -> None:
                self._inner = inner

            def execute(self, sql, parameters=(), /, **kwargs):
                head = str(sql).lstrip().upper()
                if head.startswith('INSERT') or head.startswith('UPDATE') or head.startswith('DELETE'):
                    writes.append(head)
                return self._inner.execute(sql, parameters, **kwargs)

            def __getattr__(self, name):
                return getattr(self._inner, name)

        _hafiza(_TrackCon(self.con))
        tahsilat_writes = [w for w in writes if 'MO_TAHSILAT' in w]
        self.assertEqual(tahsilat_writes, [])


if __name__ == '__main__':
    unittest.main()
