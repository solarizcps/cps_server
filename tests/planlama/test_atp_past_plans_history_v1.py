# -*- coding: utf-8 -*-
"""ATP Geçmiş Planlar — read-only history list/detail tests."""
from __future__ import annotations

import importlib.util
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

_APP_DIR = Path(__file__).resolve().parents[2] / 'app'
_MIGRATIONS = _APP_DIR / 'migrations'
CANONICAL_SOURCE = Path(r'C:\Solariz_CPS_SERVER\app\mock_data.db')
PLAN_PROVIDER = 'TURKCELL_FILOM'


def _run_migration(db_path: str, filename: str) -> None:
    spec = importlib.util.spec_from_file_location(filename, _MIGRATIONS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(db_path)


@contextmanager
def _patched_db(db_path: str):
    import config

    with patch.object(config.Config, 'MOCK_DB_PATH', db_path):
        yield db_path


def _bootstrap_db(db_path: str, *, with_visit: bool = False) -> None:
    migs = [
        '176_arac_takip_v13.py',
        '177_arac_operasyon_ayar.py',
        '178_arac_is_talebi_ux_v2_fields.py',
    ]
    if with_visit:
        # 179 arac_plan_olay tablosunu kurar; 180 geofence, 191 AUTO_TAMAMLANDI
        # olay tiplerini CHECK'e ekler (production şema zinciri).
        migs.append('179_arac_gps_snapshot_p1.py')
        migs.append('180_arac_plan_ziyaret_durum.py')
        migs.append('191_arac_plan_olay_auto_tamamlandi.py')
    for mig in migs:
        _run_migration(db_path, mig)


_talep_seq = 0


def _insert_talep(con: sqlite3.Connection, *, firma: str, yapilacak: str = 'Test') -> int:
    global _talep_seq
    _talep_seq += 1
    now = '2026-08-01 10:00:00'
    cur = con.execute(
        """
        INSERT INTO arac_is_talebi (
            talep_no, talep_eden_user_id, talep_eden_adi_snapshot, talep_tarihi,
            firma_adi, adres, yapilacak_is, oncelik, durum,
            created_at, created_by, updated_at, updated_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (f'T-{_talep_seq}-{firma}', 1, 'tester', '2026-08-01', firma, 'Adres', yapilacak, 'NORMAL', 'PLANA_ALINDI', now, 1, now, 1),
    )
    return int(cur.lastrowid)


def _insert_plan_with_items(
    con: sqlite3.Connection,
    *,
    plan_date: str,
    ext_id: str = '45077045',
    plaka: str = '34 MOR 049',
    sofor_id: int = 1,
    sofor: str = 'oktay',
    item_statuses: list[str],
) -> int:
    now = '2026-08-01 10:00:00'
    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            sofor_id, sofor_adi_snapshot, durum, created_at, updated_at, created_by, updated_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (plan_date, PLAN_PROVIDER, ext_id, plaka, sofor_id, sofor, 'AKTIF', now, now, 1, 1),
    )
    plan_id = int(cur.lastrowid)
    for i, st in enumerate(item_statuses, start=1):
        talep_id = _insert_talep(con, firma=f'Firma{i}', yapilacak=f'Is{i}')
        con.execute(
            """
            INSERT INTO arac_gunluk_plan_is (
                plan_id, is_talebi_id, sira, durum, created_at, created_by
            ) VALUES (?,?,?,?,?,?)
            """,
            (plan_id, talep_id, i, st, now, 1),
        )
    con.commit()
    return plan_id


@pytest.fixture
def synthetic_db():
    tmpdir = tempfile.mkdtemp(prefix='atp_hist_syn_')
    db_path = str(Path(tmpdir) / 'test.db')
    _bootstrap_db(db_path)
    try:
        with _patched_db(db_path):
            yield db_path
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def synthetic_db_with_visit():
    tmpdir = tempfile.mkdtemp(prefix='atp_hist_visit_syn_')
    db_path = str(Path(tmpdir) / 'test.db')
    _bootstrap_db(db_path, with_visit=True)
    try:
        with _patched_db(db_path):
            yield db_path
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _insert_empty_plan(con: sqlite3.Connection, *, plan_date: str) -> int:
    now = '2026-08-01 10:00:00'
    cur = con.execute(
        """
        INSERT INTO arac_gunluk_plan (
            plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
            sofor_id, sofor_adi_snapshot, durum, created_at, updated_at, created_by, updated_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (plan_date, PLAN_PROVIDER, '45077045', '34 MOR 049', 1, 'oktay', 'AKTIF', now, now, 1, 1),
    )
    con.commit()
    return int(cur.lastrowid)


def _insert_olay(
    con: sqlite3.Connection,
    *,
    plan_id: int,
    plan_is_id: int,
    olay_turu: str,
    olay_zamani: str,
    metadata_json: str = '{}',
) -> None:
    now = '2026-08-24 12:00:00'
    con.execute(
        """
        INSERT INTO arac_plan_olay (
            plan_id, plan_is_id, arac_external_id, olay_turu, mesaj,
            metadata_json, olay_zamani, created_at, created_by
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (plan_id, plan_is_id, '45077045', olay_turu, olay_turu, metadata_json, olay_zamani, now, 1),
    )
    con.commit()


def _insert_visit(
    con: sqlite3.Connection,
    *,
    plan_id: int,
    plan_is_id: int,
    arrived_at: str | None = None,
    departed_at: str | None = None,
    dwell_seconds: int | None = None,
    state: str = 'DEPARTED_PENDING',
    result_status: str | None = 'SONUC_BEKLIYOR',
) -> None:
    now = '2026-08-24 12:00:00'
    con.execute(
        """
        INSERT INTO arac_plan_is_ziyaret_durum (
            plan_id, plan_is_id, arac_external_id, state,
            geofence_radius_m, exit_radius_m,
            consecutive_inside, consecutive_outside,
            arrived_at, departed_at, dwell_seconds, result_status, updated_at, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            plan_id, plan_is_id, '45077045', state,
            200, 300, 0, 0,
            arrived_at, departed_at, dwell_seconds, result_status, now, now,
        ),
    )
    con.commit()


@pytest.fixture
def canonical_copy_db():
    if not CANONICAL_SOURCE.is_file():
        pytest.skip(f'Canonical DB not found: {CANONICAL_SOURCE}')
    tmpdir = tempfile.mkdtemp(prefix='atp_hist_canonical_copy_')
    db_path = str(Path(tmpdir) / 'canonical_copy.db')
    shutil.copy2(CANONICAL_SOURCE, db_path)
    try:
        with _patched_db(db_path):
            yield db_path
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestHistoryPlansSynthetic:
    def test_past_aktif_plan_listed(self, synthetic_db):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db)
        _insert_plan_with_items(con, plan_date='2026-08-20', item_statuses=['PLANLANDI', 'TAMAMLANDI'])
        con.close()

        res = list_history_plans(baslangic='2026-08-01', bitis='2026-08-31', today='2026-09-13')
        assert res['ok'] is True
        assert res['count'] == 1
        row = res['rows'][0]
        assert row['plan_durum'] == 'AKTIF'
        assert row['total_jobs'] == 2

    def test_completed_and_not_visited_same_plan(self, synthetic_db):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db)
        _insert_plan_with_items(
            con,
            plan_date='2026-08-21',
            item_statuses=['TAMAMLANDI', 'TAMAMLANDI', 'PLANLANDI', 'PLANLANDI', 'IPTAL'],
        )
        con.close()

        row = list_history_plans(today='2026-09-13')['rows'][0]
        assert row['completed'] == 2
        assert row['not_visited'] == 2
        assert row['cancelled'] == 1
        assert row['active_jobs'] == 4

    def test_iptal_excluded_from_ratio(self, synthetic_db):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db)
        _insert_plan_with_items(con, plan_date='2026-08-22', item_statuses=['TAMAMLANDI', 'IPTAL'])
        con.close()

        row = list_history_plans(today='2026-09-13')['rows'][0]
        assert row['active_jobs'] == 1
        assert row['completion_ratio'] == 100.0

    def test_all_completed_plan(self, synthetic_db):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db)
        _insert_plan_with_items(con, plan_date='2026-08-23', item_statuses=['TAMAMLANDI', 'TAMAMLANDI'])
        con.close()

        row = list_history_plans(today='2026-09-13')['rows'][0]
        assert row['status'] == 'TAMAMLANDI'

    def test_none_visited_plan(self, synthetic_db):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db)
        _insert_plan_with_items(con, plan_date='2026-08-24', item_statuses=['PLANLANDI', 'PLANLANDI'])
        con.close()

        row = list_history_plans(today='2026-09-13')['rows'][0]
        assert row['status'] == 'GIDILMEDI'
        assert row['completed'] == 0

    def test_all_cancelled_plan(self, synthetic_db):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db)
        _insert_plan_with_items(con, plan_date='2026-08-25', item_statuses=['IPTAL', 'IPTAL'])
        con.close()

        row = list_history_plans(today='2026-09-13')['rows'][0]
        assert row['status'] == 'IPTAL'

    def test_date_filter(self, synthetic_db):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db)
        _insert_plan_with_items(con, plan_date='2026-08-10', item_statuses=['PLANLANDI'])
        _insert_plan_with_items(con, plan_date='2026-08-20', item_statuses=['PLANLANDI'])
        con.close()

        res = list_history_plans(baslangic='2026-08-15', bitis='2026-08-31', today='2026-09-13')
        assert res['count'] == 1
        assert res['rows'][0]['date'] == '2026-08-20'

    def test_vehicle_filter(self, synthetic_db):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db)
        _insert_plan_with_items(con, plan_date='2026-08-18', ext_id='45077045', item_statuses=['PLANLANDI'])
        _insert_plan_with_items(con, plan_date='2026-08-19', ext_id='45074345', plaka='34 GFK 183', item_statuses=['PLANLANDI'])
        con.close()

        res = list_history_plans(vehicle_id='45077045', today='2026-09-13')
        assert res['count'] == 1
        assert res['rows'][0]['vehicle_external_id'] == '45077045'

    def test_driver_filter(self, synthetic_db):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db)
        _insert_plan_with_items(con, plan_date='2026-08-17', sofor_id=1, sofor='Ali', item_statuses=['PLANLANDI'])
        _insert_plan_with_items(con, plan_date='2026-08-16', sofor_id=2, sofor='Veli', item_statuses=['PLANLANDI'])
        con.close()

        res = list_history_plans(sofor_id='2', today='2026-09-13')
        assert res['count'] == 1
        assert res['rows'][0]['driver'] == 'Veli'

    def test_combined_filter(self, synthetic_db):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db)
        _insert_plan_with_items(con, plan_date='2026-08-14', ext_id='45077045', sofor_id=1, item_statuses=['PLANLANDI'])
        _insert_plan_with_items(con, plan_date='2026-08-14', ext_id='45074345', sofor_id=1, item_statuses=['PLANLANDI'])
        con.close()

        res = list_history_plans(
            baslangic='2026-08-14', bitis='2026-08-14',
            vehicle_id='45077045', sofor_id='1', today='2026-09-13',
        )
        assert res['count'] == 1

    def test_today_plan_excluded(self, synthetic_db):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db)
        _insert_plan_with_items(con, plan_date='2026-09-13', item_statuses=['PLANLANDI'])
        _insert_plan_with_items(con, plan_date='2026-08-12', item_statuses=['PLANLANDI'])
        con.close()

        res = list_history_plans(today='2026-09-13')
        assert all(r['date'] != '2026-09-13' for r in res['rows'])
        assert any(r['date'] == '2026-08-12' for r in res['rows'])

    def test_future_plan_excluded(self, synthetic_db):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db)
        _insert_plan_with_items(con, plan_date='2026-11-14', item_statuses=['PLANLANDI'])
        con.close()

        res = list_history_plans(today='2026-09-13')
        assert res['count'] == 0

    def test_detail_returns_all_tasks(self, synthetic_db):
        from modules.planlama.arac_takip_repo import get_history_plan_detail

        con = sqlite3.connect(synthetic_db)
        plan_id = _insert_plan_with_items(
            con,
            plan_date='2026-08-11',
            item_statuses=['TAMAMLANDI', 'PLANLANDI', 'IPTAL', 'BASLADI'],
        )
        con.close()

        detail = get_history_plan_detail(plan_id)
        assert detail['ok'] is True
        assert len(detail['items']) == 4
        statuses = {it['task_status'] for it in detail['items']}
        assert statuses == {'TAMAMLANDI', 'PLANLANDI', 'IPTAL', 'BASLADI'}

    def test_empty_result(self, synthetic_db):
        from modules.planlama.arac_takip_repo import list_history_plans

        res = list_history_plans(baslangic='2020-01-01', bitis='2020-01-31', today='2026-09-13')
        assert res['ok'] is True
        assert res['count'] == 0

    def test_pagination_and_sort(self, synthetic_db):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db)
        for d in ('2026-08-10', '2026-08-11', '2026-08-12'):
            _insert_plan_with_items(con, plan_date=d, item_statuses=['PLANLANDI'])
        con.close()

        page1 = list_history_plans(page=1, page_size=2, today='2026-09-13')
        page2 = list_history_plans(page=2, page_size=2, today='2026-09-13')
        assert page1['count'] == 2
        assert page2['count'] == 1
        assert page1['rows'][0]['date'] == '2026-08-12'
        assert page1['rows'][1]['date'] == '2026-08-11'

    def test_canonical_db_write_guard(self):
        from tools.nexgen_tmp_db import CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST, LiveDbWriteError, canonical_db_path

        with pytest.raises(LiveDbWriteError) as exc:
            sqlite3.connect(canonical_db_path())
        assert CANONICAL_DB_WRITE_FORBIDDEN_IN_TEST in str(exc.value)

    def test_empty_plan_bos_plan_status(self, synthetic_db):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db)
        _insert_empty_plan(con, plan_date='2026-08-26')
        con.close()

        row = list_history_plans(today='2026-09-13')['rows'][0]
        assert row['total_jobs'] == 0
        assert row['active_jobs'] == 0
        assert row['status'] == 'BOS_PLAN'
        assert row['status_label'] == 'Boş Plan'


class TestHistoryVisitTruthClassification:
    """Ziyaret kanıtına göre sınıflandırma — R2."""

    def test_planlandi_with_visit_is_visited_pending(self, synthetic_db_with_visit):
        from modules.planlama.arac_takip_repo import get_history_plan_detail, list_history_plans

        con = sqlite3.connect(synthetic_db_with_visit)
        plan_id = _insert_plan_with_items(con, plan_date='2026-08-27', item_statuses=['PLANLANDI'])
        item_id = con.execute('SELECT id FROM arac_gunluk_plan_is WHERE plan_id=?', (plan_id,)).fetchone()[0]
        _insert_visit(con, plan_id=plan_id, plan_is_id=item_id, arrived_at='2026-08-27 10:00:00')
        con.close()

        row = list_history_plans(today='2026-09-13')['rows'][0]
        assert row['visited_pending'] == 1
        assert row['not_visited'] == 0
        detail = get_history_plan_detail(plan_id)
        assert detail['items'][0]['category'] == 'ZIYARET_SONUC_BEKLIYOR'

    def test_basladi_with_visit_is_visited_pending(self, synthetic_db_with_visit):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db_with_visit)
        plan_id = _insert_plan_with_items(con, plan_date='2026-08-28', item_statuses=['BASLADI'])
        item_id = con.execute('SELECT id FROM arac_gunluk_plan_is WHERE plan_id=?', (plan_id,)).fetchone()[0]
        _insert_visit(con, plan_id=plan_id, plan_is_id=item_id, departed_at='2026-08-28 11:00:00')
        con.close()

        row = list_history_plans(today='2026-09-13')['rows'][0]
        assert row['visited_pending'] == 1
        assert row['started_without_visit'] == 0

    def test_basladi_without_visit_is_started_without(self, synthetic_db_with_visit):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db_with_visit)
        _insert_plan_with_items(con, plan_date='2026-08-29', item_statuses=['BASLADI'])
        con.close()

        row = list_history_plans(today='2026-09-13')['rows'][0]
        assert row['started_without_visit'] == 1
        assert row['visited_pending'] == 0

    def test_tamamlandi_is_completed(self, synthetic_db_with_visit):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db_with_visit)
        _insert_plan_with_items(con, plan_date='2026-08-30', item_statuses=['TAMAMLANDI'])
        con.close()

        row = list_history_plans(today='2026-09-13')['rows'][0]
        assert row['completed'] == 1
        assert row['visited_pending'] == 0

    def test_iptal_is_cancelled(self, synthetic_db_with_visit):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db_with_visit)
        _insert_plan_with_items(con, plan_date='2026-08-31', item_statuses=['IPTAL'])
        con.close()

        row = list_history_plans(today='2026-09-13')['rows'][0]
        assert row['cancelled'] == 1
        assert row['active_jobs'] == 0
        assert row['status'] == 'IPTAL'

    def test_planlandi_without_visit_is_not_visited(self, synthetic_db_with_visit):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db_with_visit)
        _insert_plan_with_items(con, plan_date='2026-09-01', item_statuses=['PLANLANDI'])
        con.close()

        row = list_history_plans(today='2026-09-13')['rows'][0]
        assert row['not_visited'] == 1

    def test_active_jobs_reconcile(self, synthetic_db_with_visit):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db_with_visit)
        plan_id = _insert_plan_with_items(
            con,
            plan_date='2026-09-02',
            item_statuses=['TAMAMLANDI', 'PLANLANDI', 'BASLADI', 'IPTAL'],
        )
        rows = con.execute('SELECT id, durum FROM arac_gunluk_plan_is WHERE plan_id=? ORDER BY sira', (plan_id,)).fetchall()
        _insert_visit(con, plan_id=plan_id, plan_is_id=rows[1][0], arrived_at='2026-09-02 09:00:00')
        con.close()

        row = list_history_plans(today='2026-09-13')['rows'][0]
        assert row['active_jobs'] == (
            row['completed'] + row['visited_pending'] + row['started_without_visit'] + row['not_visited']
        )

    def test_summary_shows_all_nonzero_categories(self, synthetic_db_with_visit):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db_with_visit)
        plan_id = _insert_plan_with_items(
            con,
            plan_date='2026-09-03',
            item_statuses=['TAMAMLANDI', 'PLANLANDI', 'PLANLANDI', 'BASLADI', 'IPTAL'],
        )
        rows = con.execute('SELECT id FROM arac_gunluk_plan_is WHERE plan_id=? ORDER BY sira', (plan_id,)).fetchall()
        _insert_visit(con, plan_id=plan_id, plan_is_id=rows[1][0], arrived_at='2026-09-03 10:00:00')
        con.execute(
            'UPDATE arac_gunluk_plan_is SET planlanan_saat=? WHERE id=?',
            ('16:00', rows[3][0]),
        )
        _insert_visit(
            con, plan_id=plan_id, plan_is_id=rows[3][0],
            arrived_at='2026-09-03 16:00:00', departed_at='2026-09-03 12:00:00',
        )
        con.commit()
        con.close()

        summary = list_history_plans(today='2026-09-13')['rows'][0]['summary_line']
        assert 'tamamlandı' in summary
        assert 'gidildi/sonuç bekliyor' in summary
        assert 'gidilmedi' in summary
        assert 'başladı/ziyaret doğrulanamadı' in summary
        assert 'plan dışı' in summary

    def test_completion_ratio_excludes_visited_pending(self, synthetic_db_with_visit):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db_with_visit)
        plan_id = _insert_plan_with_items(
            con, plan_date='2026-09-04', item_statuses=['TAMAMLANDI', 'PLANLANDI'],
        )
        item_id = con.execute('SELECT id FROM arac_gunluk_plan_is WHERE plan_id=? AND durum=?', (plan_id, 'PLANLANDI')).fetchone()[0]
        _insert_visit(con, plan_id=plan_id, plan_is_id=item_id, arrived_at='2026-09-04 12:00:00')
        con.close()

        row = list_history_plans(today='2026-09-13')['rows'][0]
        assert row['completion_ratio'] == 50.0

    def test_ambiguous_gps_without_visit_record_not_counted(self, synthetic_db_with_visit):
        """GPS kanıtı history sorgusuna sessizce eklenmez — yalnız ziyaret tablosu."""
        from modules.planlama.arac_takip_repo import _classify_history_item

        cls = _classify_history_item('PLANLANDI', None)
        assert cls['category'] == 'GIDILMEDI'

    def test_duplicate_visit_not_double_counted(self, synthetic_db_with_visit):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db_with_visit)
        plan_id = _insert_plan_with_items(con, plan_date='2026-09-05', item_statuses=['PLANLANDI'])
        item_id = con.execute('SELECT id FROM arac_gunluk_plan_is WHERE plan_id=?', (plan_id,)).fetchone()[0]
        _insert_visit(
            con, plan_id=plan_id, plan_is_id=item_id,
            arrived_at='2026-09-05 10:00:00', departed_at='2026-09-05 10:30:00',
        )
        con.close()

        row = list_history_plans(today='2026-09-13')['rows'][0]
        assert row['visited_pending'] == 1
        assert row['active_jobs'] == 1


class TestHistoryVisitTimelineIntegrity:
    """Geçmiş ziyaret zaman bütünlüğü — R3."""

    def test_departure_after_arrival_valid(self):
        from modules.planlama.arac_takip_repo import _build_history_visit_timeline

        tl = _build_history_visit_timeline({
            'arrived_at': '2026-08-24 10:00:00',
            'departed_at': '2026-08-24 10:30:00',
            'dwell_seconds': 1800,
        })
        assert tl['timeline_valid'] is True
        assert tl['departed_at_display'] == '2026-08-24 10:30:00'
        assert tl['dwell_label'] is not None

    def test_departure_equal_arrival_valid(self):
        from modules.planlama.arac_takip_repo import _build_history_visit_timeline

        tl = _build_history_visit_timeline({
            'arrived_at': '2026-08-24 10:00:00',
            'departed_at': '2026-08-24 10:00:00',
            'dwell_seconds': 0,
        })
        assert tl['timeline_valid'] is True

    def test_departure_before_arrival_invalid(self):
        from modules.planlama.arac_takip_repo import _build_history_visit_timeline

        tl = _build_history_visit_timeline({
            'arrived_at': '2026-08-24 16:00:00',
            'departed_at': '2026-08-24 12:26:13',
            'dwell_seconds': -12827,
        })
        assert tl['timeline_valid'] is False
        assert tl['timeline_warning'] == 'Zaman kaydı tutarsız'
        assert tl['departed_at_display'] is None
        assert tl['dwell_label'] is None
        assert 'doğrulanamadı' in (tl['visit_times_line'] or '')

    def test_negative_dwell_invalid(self):
        from modules.planlama.arac_takip_repo import _validate_visit_timeline

        v = _validate_visit_timeline('2026-08-24 10:00:00', '2026-08-24 11:00:00', -60)
        assert v['timeline_valid'] is False
        assert v['timeline_issue'] == 'negative_dwell'

    def test_arrival_only(self):
        from modules.planlama.arac_takip_repo import _build_history_visit_timeline

        tl = _build_history_visit_timeline({'arrived_at': '2026-08-24 09:00:00'})
        assert tl['timeline_valid'] is True
        assert 'Varış:' in tl['visit_times_line']
        assert tl['departed_at_display'] is None

    def test_departure_only_missing_arrival_warning(self):
        from modules.planlama.arac_takip_repo import _build_history_visit_timeline

        tl = _build_history_visit_timeline({'departed_at': '2026-08-24 12:00:00'})
        assert tl['timeline_warning'] == 'Eksik varış kaydı'
        assert tl['departed_at_display'] == '2026-08-24 12:00:00'

    def test_planned_arrival_without_konuma_varildi_not_visited_pending(self, synthetic_db_with_visit):
        from modules.planlama.arac_takip_repo import list_history_plans

        con = sqlite3.connect(synthetic_db_with_visit)
        plan_id = _insert_plan_with_items(con, plan_date='2026-09-06', item_statuses=['PLANLANDI'])
        item_id = con.execute('SELECT id FROM arac_gunluk_plan_is WHERE plan_id=?', (plan_id,)).fetchone()[0]
        con.execute(
            'UPDATE arac_gunluk_plan_is SET planlanan_saat=? WHERE id=?',
            ('16:00', item_id),
        )
        _insert_visit(
            con, plan_id=plan_id, plan_is_id=item_id,
            arrived_at='2026-09-06 16:00:00', departed_at='2026-09-06 12:00:00', dwell_seconds=-3600,
        )
        con.commit()
        con.close()

        row = list_history_plans(today='2026-09-13')['rows'][0]
        assert row['visited_pending'] == 0
        assert row['not_visited'] == 1

    def test_basladi_unverified_visit_category(self, synthetic_db_with_visit):
        from modules.planlama.arac_takip_repo import get_history_plan_detail

        con = sqlite3.connect(synthetic_db_with_visit)
        plan_id = _insert_plan_with_items(con, plan_date='2026-09-07', item_statuses=['BASLADI'])
        item_id = con.execute('SELECT id FROM arac_gunluk_plan_is WHERE plan_id=?', (plan_id,)).fetchone()[0]
        con.execute(
            'UPDATE arac_gunluk_plan_is SET planlanan_saat=? WHERE id=?',
            ('16:00', item_id),
        )
        _insert_visit(
            con, plan_id=plan_id, plan_is_id=item_id,
            arrived_at='2026-09-07 16:00:00', departed_at='2026-09-07 12:00:00',
        )
        con.commit()
        con.close()

        item = get_history_plan_detail(plan_id)['items'][0]
        assert item['category'] == 'BASLADI_ZIYARET_DOGRULANAMADI'
        assert item['category_label'] == 'Başladı · Ziyaret doğrulanamadı'
        assert 'Gidildi / Sonuç bekliyor' not in item['visit_times_line']


class TestHistoryPlan7CanonicalCopy:
    """Plan ID=7 doğrulama — byte-copy TEMP DB, kaynak: production canonical."""

    def test_plan_7_visible_in_history(self, canonical_copy_db):
        from modules.planlama.arac_takip_repo import get_history_plan_detail, list_history_plans

        res = list_history_plans(
            baslangic='2026-08-24', bitis='2026-08-24',
            vehicle_id='45077045', today='2026-09-13',
        )
        assert res['count'] >= 1
        row = next(r for r in res['rows'] if r['plan_id'] == 7)
        assert row['date'] == '2026-08-24'
        assert 'MOR 049' in row['vehicle']
        assert row['plan_durum'] == 'AKTIF'
        assert row['total_jobs'] == 12
        assert row['cancelled'] == 1
        assert row['completed'] == 3
        assert row['visited_pending'] == 1
        assert row['not_visited'] == 6
        assert row['started_without_visit'] == 1
        assert row['active_jobs'] == 11
        assert row['status'] == 'KISMI_TAMAMLANDI'
        assert row['summary_line'] == (
            '3/11 tamamlandı · 1 gidildi/sonuç bekliyor · '
            '1 başladı/ziyaret doğrulanamadı · 6 gidilmedi · 1 plan dışı'
        )
        assert row['completion_ratio'] == round(100.0 * 3 / 11, 1)

        detail = get_history_plan_detail(7)
        assert detail['ok'] is True
        assert len(detail['items']) == 12

        by_firma = {it['company_name'].lower(): it for it in detail['items']}
        coto = by_firma['c otomotiv']
        sahin = by_firma['şahin']
        assert coto['category'] == 'BASLADI_ZIYARET_DOGRULANAMADI'
        assert coto['category_label'] == 'Başladı · Ziyaret doğrulanamadı'
        assert coto['timeline_valid'] is False
        assert coto['arrived_at'] is None
        assert coto['departed_at'] is None
        assert coto['dwell_label'] is None
        assert 'Gidildi / Sonuç bekliyor' not in (coto['visit_times_line'] or '')
        assert sahin['category'] == 'ZIYARET_SONUC_BEKLIYOR'
        assert sahin['timeline_valid'] is True
        assert sahin['departed_at'] == '2026-08-24 19:29:03'
        assert sahin['dwell_label'] is not None
        assert by_firma['violet etiket']['category'] == 'GIDILMEDI'

        assert detail['plan']['visited_pending'] == 1
        assert detail['plan']['started_without_visit'] == 1
        assert detail['plan']['not_visited'] == 6
        assert (
            detail['plan']['active_jobs']
            == detail['plan']['completed']
            + detail['plan']['visited_pending']
            + detail['plan']['started_without_visit']
            + detail['plan']['not_visited']
        )


# ─────────────────────────────────────────────────
# KAPI 1 — Filter options endpoint tests
# ─────────────────────────────────────────────────
class TestHistoryFilterOptions:
    """list_history_filter_options — read-only, derived from past plans."""

    def _make_db(self, *, plan_date='2026-08-01') -> tuple:
        """Returns (tmpdir, db_path) with two past plans under different vehicles/drivers."""
        tmpdir = tempfile.mkdtemp(prefix='atp_filt_')
        db_path = str(Path(tmpdir) / 'test.db')
        _bootstrap_db(db_path)
        return tmpdir, db_path

    def test_vehicles_only_from_history(self, tmp_path):
        """Vehicle options must come from arac_gunluk_plan, not live catalog."""
        db_path = str(tmp_path / 'test.db')
        _bootstrap_db(db_path)
        con = sqlite3.connect(db_path)
        now = '2026-01-10 10:00:00'
        for ext_id, plaka in [('V001', '34 ABC 001'), ('V002', '34 XYZ 002')]:
            con.execute(
                """INSERT INTO arac_gunluk_plan
                   (plan_tarihi,arac_provider,arac_external_id,arac_plaka_snapshot,
                    sofor_id,sofor_adi_snapshot,durum,created_at,updated_at,created_by,updated_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                ('2026-01-09', PLAN_PROVIDER, ext_id, plaka, 1, 'Test', 'AKTIF', now, now, 1, 1),
            )
        con.commit()
        con.close()
        from modules.planlama.arac_takip_repo import list_history_filter_options
        with _patched_db(db_path):
            result = list_history_filter_options(today='2026-01-10')
        assert result['ok'] is True
        vehicle_ids = {v['vehicle_id'] for v in result['vehicles']}
        assert 'V001' in vehicle_ids
        assert 'V002' in vehicle_ids

    def test_general_users_not_in_drivers(self, tmp_path):
        """General users (not appearing as sofor in past plans) must not appear."""
        db_path = str(tmp_path / 'test.db')
        _bootstrap_db(db_path)
        con = sqlite3.connect(db_path)
        now = '2026-01-10 10:00:00'
        # Only sofor_id=5 / 'Serhat' is in a past plan
        con.execute(
            """INSERT INTO arac_gunluk_plan
               (plan_tarihi,arac_provider,arac_external_id,arac_plaka_snapshot,
                sofor_id,sofor_adi_snapshot,durum,created_at,updated_at,created_by,updated_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            ('2026-01-09', PLAN_PROVIDER, 'V001', '34 ABC 001', 5, 'Serhat', 'AKTIF', now, now, 1, 1),
        )
        con.commit()
        con.close()
        from modules.planlama.arac_takip_repo import list_history_filter_options
        with _patched_db(db_path):
            result = list_history_filter_options(today='2026-01-10')
        driver_names = [d['name'] for d in result['drivers']]
        assert 'Serhat' in driver_names
        # No "Ali", "muhasebe", "sistem yöneticisi" etc. that were never assigned as sofor
        for bad_name in ['Ali', 'muhasebe', 'sistem yöneticisi', 'üretim operatörü']:
            assert bad_name not in driver_names, f'{bad_name} must not appear in driver options'

    def test_vehicle_deduplicated_same_ext_id(self, tmp_path):
        """Same vehicle_id in multiple plans must appear only once (plate dedup)."""
        db_path = str(tmp_path / 'test.db')
        _bootstrap_db(db_path)
        con = sqlite3.connect(db_path)
        now = '2026-01-10 10:00:00'
        for plan_date in ['2026-01-08', '2026-01-09']:
            con.execute(
                """INSERT INTO arac_gunluk_plan
                   (plan_tarihi,arac_provider,arac_external_id,arac_plaka_snapshot,
                    sofor_id,sofor_adi_snapshot,durum,created_at,updated_at,created_by,updated_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (plan_date, PLAN_PROVIDER, 'V001', '34 ABC 001', 1, 'Test', 'AKTIF', now, now, 1, 1),
            )
        con.commit()
        con.close()
        from modules.planlama.arac_takip_repo import list_history_filter_options
        with _patched_db(db_path):
            result = list_history_filter_options(today='2026-01-10')
        plates = [v['plate'] for v in result['vehicles']]
        assert plates.count('34 ABC 001') == 1, 'vehicle plate dedup must be 1'

    def test_vehicle_deduplicated_diff_ext_id_same_plate(self, tmp_path):
        """Same plate with different external_ids → only one entry, winner = newest plan."""
        db_path = str(tmp_path / 'test.db')
        _bootstrap_db(db_path)
        con = sqlite3.connect(db_path)
        now = '2026-01-10 10:00:00'
        # Older plan: ext_id=OLD001, newer plan: ext_id=NEW001, same plate
        for plan_date, ext_id in [('2026-01-07', 'OLD001'), ('2026-01-09', 'NEW001')]:
            con.execute(
                """INSERT INTO arac_gunluk_plan
                   (plan_tarihi,arac_provider,arac_external_id,arac_plaka_snapshot,
                    sofor_id,sofor_adi_snapshot,durum,created_at,updated_at,created_by,updated_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (plan_date, PLAN_PROVIDER, ext_id, '34 ABC 001', 1, 'Test', 'AKTIF', now, now, 1, 1),
            )
        con.commit()
        con.close()
        from modules.planlama.arac_takip_repo import list_history_filter_options
        with _patched_db(db_path):
            result = list_history_filter_options(today='2026-01-10')
        assert len(result['vehicles']) == 1, 'same plate different ext_id → 1 entry'
        assert result['vehicles'][0]['plate'] == '34 ABC 001'
        assert result['vehicles'][0]['vehicle_id'] == 'NEW001', 'winner must be newest plan'

    def test_driver_deduplicated(self, tmp_path):
        """Same sofor_id in multiple plans must appear only once."""
        db_path = str(tmp_path / 'test.db')
        _bootstrap_db(db_path)
        con = sqlite3.connect(db_path)
        now = '2026-01-10 10:00:00'
        for plan_date in ['2026-01-08', '2026-01-09']:
            con.execute(
                """INSERT INTO arac_gunluk_plan
                   (plan_tarihi,arac_provider,arac_external_id,arac_plaka_snapshot,
                    sofor_id,sofor_adi_snapshot,durum,created_at,updated_at,created_by,updated_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (plan_date, PLAN_PROVIDER, 'V001', '34 ABC 001', 7, 'Ahmet', 'AKTIF', now, now, 1, 1),
            )
        con.commit()
        con.close()
        from modules.planlama.arac_takip_repo import list_history_filter_options
        with _patched_db(db_path):
            result = list_history_filter_options(today='2026-01-10')
        sofor_ids = [d['sofor_id'] for d in result['drivers']]
        assert sofor_ids.count(7) == 1, 'driver dedup must be 1'

    def test_vehicle_filter_by_plate_applies_to_list(self, tmp_path):
        """list_history_plans with plate filter returns only matching plans."""
        db_path = str(tmp_path / 'test.db')
        _bootstrap_db(db_path)
        con = sqlite3.connect(db_path)
        now = '2026-01-10 10:00:00'
        for ext_id, plaka in [('V001', '34 ABC 001'), ('V002', '34 XYZ 002')]:
            con.execute(
                """INSERT INTO arac_gunluk_plan
                   (plan_tarihi,arac_provider,arac_external_id,arac_plaka_snapshot,
                    sofor_id,sofor_adi_snapshot,durum,created_at,updated_at,created_by,updated_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                ('2026-01-09', PLAN_PROVIDER, ext_id, plaka, 1, 'Test', 'AKTIF', now, now, 1, 1),
            )
        con.commit()
        con.close()
        from modules.planlama.arac_takip_repo import list_history_plans
        with _patched_db(db_path):
            result = list_history_plans(plate='34 ABC 001', today='2026-01-10')
        assert result['ok'] is True
        assert len(result['rows']) == 1
        assert result['rows'][0]['vehicle_external_id'] == 'V001'

    def test_plate_filter_gets_all_related_plans_across_ext_ids(self, tmp_path):
        """Plate filter must return all plans with that plate even if ext_ids differ."""
        db_path = str(tmp_path / 'test.db')
        _bootstrap_db(db_path)
        con = sqlite3.connect(db_path)
        now = '2026-01-10 10:00:00'
        # Two plans with same plate but different external_ids
        for plan_date, ext_id in [('2026-01-07', 'OLD001'), ('2026-01-09', 'NEW001')]:
            con.execute(
                """INSERT INTO arac_gunluk_plan
                   (plan_tarihi,arac_provider,arac_external_id,arac_plaka_snapshot,
                    sofor_id,sofor_adi_snapshot,durum,created_at,updated_at,created_by,updated_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (plan_date, PLAN_PROVIDER, ext_id, '34 ABC 001', 1, 'Test', 'AKTIF', now, now, 1, 1),
            )
        con.commit()
        con.close()
        from modules.planlama.arac_takip_repo import list_history_plans
        with _patched_db(db_path):
            result = list_history_plans(plate='34 ABC 001', today='2026-01-10')
        assert result['ok'] is True
        # Both plans (OLD001 and NEW001) must be returned
        assert len(result['rows']) == 2, 'plate filter must return all plans with that plate'

    def test_driver_filter_by_name_applies_to_list(self, tmp_path):
        """list_history_plans with sofor_name filter returns only matching plans."""
        db_path = str(tmp_path / 'test.db')
        _bootstrap_db(db_path)
        con = sqlite3.connect(db_path)
        now = '2026-01-10 10:00:00'
        con.execute(
            """INSERT INTO arac_gunluk_plan
               (plan_tarihi,arac_provider,arac_external_id,arac_plaka_snapshot,
                sofor_id,sofor_adi_snapshot,durum,created_at,updated_at,created_by,updated_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            ('2026-01-09', PLAN_PROVIDER, 'V001', '34 ABC 001', 5, 'Serhat', 'AKTIF', now, now, 1, 1),
        )
        con.execute(
            """INSERT INTO arac_gunluk_plan
               (plan_tarihi,arac_provider,arac_external_id,arac_plaka_snapshot,
                sofor_id,sofor_adi_snapshot,durum,created_at,updated_at,created_by,updated_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            ('2026-01-09', PLAN_PROVIDER, 'V002', '34 XYZ 002', 9, 'Mehmet', 'AKTIF', now, now, 1, 1),
        )
        con.commit()
        con.close()
        from modules.planlama.arac_takip_repo import list_history_plans
        with _patched_db(db_path):
            result = list_history_plans(sofor_name='serhat', today='2026-01-10')
        assert result['ok'] is True
        assert len(result['rows']) == 1
        assert result['rows'][0]['driver'].lower().strip() == 'serhat'

    def test_driver_casefold_dedup(self, tmp_path):
        """Same driver name with different case must appear only once."""
        db_path = str(tmp_path / 'test.db')
        _bootstrap_db(db_path)
        con = sqlite3.connect(db_path)
        now = '2026-01-10 10:00:00'
        for plan_date, name in [('2026-01-08', 'Ahmet'), ('2026-01-09', 'AHMET')]:
            con.execute(
                """INSERT INTO arac_gunluk_plan
                   (plan_tarihi,arac_provider,arac_external_id,arac_plaka_snapshot,
                    sofor_id,sofor_adi_snapshot,durum,created_at,updated_at,created_by,updated_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (plan_date, PLAN_PROVIDER, 'V001', '34 ABC 001', None, name, 'AKTIF', now, now, 1, 1),
            )
        con.commit()
        con.close()
        from modules.planlama.arac_takip_repo import list_history_filter_options
        with _patched_db(db_path):
            result = list_history_filter_options(today='2026-01-10')
        driver_names_cf = [d['name'].casefold() for d in result['drivers']]
        assert driver_names_cf.count('ahmet') == 1, 'casefold dedup must give 1 entry'

    def test_date_range_filters_correctly(self, tmp_path):
        """baslangic/bitis params must limit results to that range."""
        db_path = str(tmp_path / 'test.db')
        _bootstrap_db(db_path)
        con = sqlite3.connect(db_path)
        now = '2026-01-20 10:00:00'
        for plan_date in ['2026-01-10', '2026-01-15', '2026-01-18']:
            con.execute(
                """INSERT INTO arac_gunluk_plan
                   (plan_tarihi,arac_provider,arac_external_id,arac_plaka_snapshot,
                    sofor_id,sofor_adi_snapshot,durum,created_at,updated_at,created_by,updated_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (plan_date, PLAN_PROVIDER, 'V001', '34 ABC 001', 1, 'Test', 'AKTIF', now, now, 1, 1),
            )
        con.commit()
        con.close()
        from modules.planlama.arac_takip_repo import list_history_plans
        with _patched_db(db_path):
            result = list_history_plans(baslangic='2026-01-14', bitis='2026-01-16', today='2026-01-20')
        assert result['ok'] is True
        dates = [r['date'] for r in result['rows']]
        assert '2026-01-15' in dates
        assert '2026-01-10' not in dates
        assert '2026-01-18' not in dates

    def test_empty_options_when_no_history(self, tmp_path):
        """No past plans → empty vehicles and drivers lists."""
        db_path = str(tmp_path / 'test.db')
        _bootstrap_db(db_path)
        from modules.planlama.arac_takip_repo import list_history_filter_options
        with _patched_db(db_path):
            result = list_history_filter_options(today='2026-01-10')
        assert result['ok'] is True
        assert result['vehicles'] == []
        assert result['drivers'] == []

    def test_canonical_db_not_written(self, tmp_path):
        """Filter options must never write to canonical DB."""
        if not CANONICAL_SOURCE.exists():
            pytest.skip('Canonical DB not available')
        import hashlib
        canonical_path = str(CANONICAL_SOURCE)
        h_before = hashlib.sha256(CANONICAL_SOURCE.read_bytes()).hexdigest()
        db_path = str(tmp_path / 'test.db')
        _bootstrap_db(db_path)
        from modules.planlama.arac_takip_repo import list_history_filter_options
        with _patched_db(db_path):
            list_history_filter_options()
        h_after = hashlib.sha256(CANONICAL_SOURCE.read_bytes()).hexdigest()
        assert h_before == h_after, 'Canonical DB must not be modified'

    def test_single_day_filter(self, tmp_path):
        """baslangic == bitis → returns only plans on that exact date."""
        db_path = str(tmp_path / 'test.db')
        _bootstrap_db(db_path)
        con = sqlite3.connect(db_path)
        now = '2026-08-25 10:00:00'
        for plan_date in ['2026-08-23', '2026-08-24', '2026-08-25']:
            con.execute(
                """INSERT INTO arac_gunluk_plan
                   (plan_tarihi,arac_provider,arac_external_id,arac_plaka_snapshot,
                    sofor_id,sofor_adi_snapshot,durum,created_at,updated_at,created_by,updated_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (plan_date, PLAN_PROVIDER, 'V001', '34 ABC 001', 1, 'Test', 'AKTIF', now, now, 1, 1),
            )
        con.commit()
        con.close()
        from modules.planlama.arac_takip_repo import list_history_plans
        with _patched_db(db_path):
            result = list_history_plans(baslangic='2026-08-24', bitis='2026-08-24', today='2026-08-26')
        assert result['ok'] is True
        dates = [r['date'] for r in result['rows']]
        assert dates == ['2026-08-24'], f'Expected only 2026-08-24, got {dates}'

    def test_two_day_filter(self, tmp_path):
        """Two-day range returns exactly those two days, nothing outside."""
        db_path = str(tmp_path / 'test.db')
        _bootstrap_db(db_path)
        con = sqlite3.connect(db_path)
        now = '2026-08-25 10:00:00'
        for plan_date in ['2026-08-21', '2026-08-22', '2026-08-23']:
            con.execute(
                """INSERT INTO arac_gunluk_plan
                   (plan_tarihi,arac_provider,arac_external_id,arac_plaka_snapshot,
                    sofor_id,sofor_adi_snapshot,durum,created_at,updated_at,created_by,updated_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (plan_date, PLAN_PROVIDER, 'V001', '34 ABC 001', 1, 'Test', 'AKTIF', now, now, 1, 1),
            )
        con.commit()
        con.close()
        from modules.planlama.arac_takip_repo import list_history_plans
        with _patched_db(db_path):
            result = list_history_plans(baslangic='2026-08-21', bitis='2026-08-22', today='2026-08-26')
        assert result['ok'] is True
        dates = sorted([r['date'] for r in result['rows']])
        assert '2026-08-21' in dates
        assert '2026-08-22' in dates
        assert '2026-08-23' not in dates

    def test_reversed_date_guard_no_results(self, tmp_path):
        """baslangic > bitis → API returns empty rows (no crash)."""
        db_path = str(tmp_path / 'test.db')
        _bootstrap_db(db_path)
        con = sqlite3.connect(db_path)
        now = '2026-08-25 10:00:00'
        con.execute(
            """INSERT INTO arac_gunluk_plan
               (plan_tarihi,arac_provider,arac_external_id,arac_plaka_snapshot,
                sofor_id,sofor_adi_snapshot,durum,created_at,updated_at,created_by,updated_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            ('2026-08-24', PLAN_PROVIDER, 'V001', '34 ABC 001', 1, 'Test', 'AKTIF', now, now, 1, 1),
        )
        con.commit()
        con.close()
        from modules.planlama.arac_takip_repo import list_history_plans
        with _patched_db(db_path):
            # baslangic=2026-08-24, bitis=2026-08-01 → inverted range
            result = list_history_plans(baslangic='2026-08-24', bitis='2026-08-01', today='2026-08-26')
        # SQL WHERE plan_tarihi >= 2026-08-24 AND plan_tarihi <= 2026-08-01 → 0 rows
        assert result['ok'] is True
        assert result['rows'] == [], 'reversed date range must return empty list'


# ── Compact detail modal display contracts (UI-only; no history math) ──
_HDM_MONTHS = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara']
_HDM_PILLS = {
    'TAMAMLANDI': 'Tamamlandı',
    'ZIYARET_SONUC_BEKLIYOR': 'Gidildi / Bekliyor',
    'BASLADI_ZIYARET_DOGRULANAMADI': 'Başladı',
    'GIDILMEDI': 'Gidilmedi',
    'IPTAL': 'Plan dışı',
}
_JS_PATH = _APP_DIR / 'static' / 'js' / 'planlama_arac_takip.js'
_HTML_PATH = _APP_DIR / 'templates' / 'planlama' / 'arac_takip_plan.html'
_CSS_PATH = _APP_DIR / 'static' / 'css' / 'planlama_arac_takip.css'


def _hdm_is_maps_url(text: str) -> bool:
    t = (text or '').lower()
    return any(x in t for x in ('google.com/maps', 'maps.google.', 'maps.app.goo.gl', 'goo.gl/maps'))


def _hdm_address_visible(address_text: str) -> str:
    if _hdm_is_maps_url(address_text):
        return ''
    return (address_text or '').strip()


def _hdm_safe_href(url: str) -> str:
    t = (url or '').strip()
    return t if t.startswith(('http://', 'https://')) else ''


def _hdm_clock(raw: str | None, plan_date: str) -> str:
    if not raw:
        return ''
    s = str(raw).replace('T', ' ')
    date_part = s[:10]
    time_part = s[11:16] if len(s) >= 16 else ''
    if plan_date and date_part == str(plan_date)[:10]:
        return time_part
    parts = date_part.split('-')
    if len(parts) >= 3:
        d = int(parts[2])
        m = int(parts[1]) - 1
        return f'{d} {_HDM_MONTHS[m]} {time_part}'
    return time_part


def _hdm_pct(completed: int, active_jobs: int) -> str:
    if not active_jobs:
        return '—'
    return f'{round(100.0 * completed / active_jobs, 1):.1f}'.replace('.', ',')


class TestHistoryDetailModalCompactUi:
    def test_five_summary_cards_bound_to_dto_fields(self):
        js = _JS_PATH.read_text(encoding='utf-8')
        for field, label in [
            ('completed', 'Tamamlandı'),
            ('visited_pending', 'Gidildi / Bekliyor'),
            ('started_without_visit', 'Başladı'),
            ('not_visited', 'Gidilmedi'),
            ('cancelled', 'Plan dışı'),
        ]:
            assert f'p.{field}' in js
            assert label in js
        assert "_hdmCard('done'" in js
        assert "_hdmCard('visit'" in js
        assert "_hdmCard('start'" in js
        assert "_hdmCard('miss'" in js
        assert "_hdmCard('cancel'" in js
        assert 'Özet:' not in js.split('function openHistoryDetailModal')[1].split('function closeHistoryDetailModal')[0]

    def test_progress_formula_completed_over_active(self):
        assert _hdm_pct(2, 6) == '33,3'
        assert _hdm_pct(3, 11) == '27,3'
        assert _hdm_pct(0, 0) == '—'
        js = _JS_PATH.read_text(encoding='utf-8')
        assert 'completion_ratio' in js
        assert 'visited_pending' in js
        assert 'Gerçekleşme' in js

    def test_raw_google_maps_url_hidden(self):
        url = 'https://maps.google.com/?q=40.818,29.305'
        assert _hdm_address_visible(url) == ''
        assert _hdm_address_visible('Ümraniye, İstanbul') == 'Ümraniye, İstanbul'
        js = _JS_PATH.read_text(encoding='utf-8')
        assert '_hdmIsMapsUrl' in js
        assert '_hdmAddressCell' in js
        assert 'Haritada Aç' in js

    def test_safe_map_link_contract(self):
        assert _hdm_safe_href('https://maps.google.com/?q=1,2') == 'https://maps.google.com/?q=1,2'
        assert _hdm_safe_href('javascript:alert(1)') == ''
        assert _hdm_safe_href('/local/path') == ''
        js = _JS_PATH.read_text(encoding='utf-8')
        assert 'target="_blank"' in js
        assert 'rel="noopener noreferrer"' in js
        assert 'Haritada Aç' in js

    def test_result_pills_by_category(self):
        assert _HDM_PILLS['TAMAMLANDI'] == 'Tamamlandı'
        assert _HDM_PILLS['ZIYARET_SONUC_BEKLIYOR'] == 'Gidildi / Bekliyor'
        assert _HDM_PILLS['BASLADI_ZIYARET_DOGRULANAMADI'] == 'Başladı'
        assert _HDM_PILLS['GIDILMEDI'] == 'Gidilmedi'
        assert _HDM_PILLS['IPTAL'] == 'Plan dışı'
        js = _JS_PATH.read_text(encoding='utf-8')
        for label in _HDM_PILLS.values():
            assert label in js
        assert 'priority_label' in js
        assert 'task_status_label' not in js.split('function openHistoryDetailModal')[1].split('function closeHistoryDetailModal')[0]

    def test_same_day_clock_and_other_day(self):
        assert _hdm_clock('2026-08-24 13:42:00', '2026-08-24') == '13:42'
        assert _hdm_clock('2026-08-23 19:05:00', '2026-08-24') == '23 Ağu 19:05'
        js = _JS_PATH.read_text(encoding='utf-8')
        assert '_hdmClock' in js

    def test_empty_visit_dash_and_unverified(self):
        js = _JS_PATH.read_text(encoding='utf-8')
        assert "cat === 'GIDILMEDI'" in js
        assert 'Ziyaret doğrulanamadı' in js
        assert "hdm-visit-empty" in js

    def test_invalid_timeline_warning_kept(self):
        js = _JS_PATH.read_text(encoding='utf-8')
        assert 'timeline_warning' in js
        assert 'timeline_valid' in js
        assert 'hist-timeline-warn' in js
        assert 'timeline_tooltip' in js

    def test_modal_close_controls(self):
        html = _HTML_PATH.read_text(encoding='utf-8')
        assert 'id="atpHistDetailClose"' in html
        assert 'id="atpHistDetailDismiss"' in html
        js = _JS_PATH.read_text(encoding='utf-8')
        assert 'atpHistDetailClose' in js
        assert "e.key === 'Escape'" in js or "e.key !== 'Escape'" in js
        assert '_hdmPrevFocus' in js

    def test_backdrop_click_does_not_close(self):
        js = _JS_PATH.read_text(encoding='utf-8')
        assert "histDetailBackdrop.addEventListener('click'" in js
        block = js.split("histDetailBackdrop.addEventListener('click'")[1].split('});')[0]
        assert 'closeHistoryDetailModal' not in block
        assert 'stopPropagation' in block

    def test_modal_blank_click_does_not_close(self):
        js = _JS_PATH.read_text(encoding='utf-8')
        assert "histDetailModal.addEventListener('click'" in js
        modal_block = js.split("histDetailModal.addEventListener('click'")[1].split(');')[0]
        assert 'closeHistoryDetailModal' not in modal_block
        assert 'stopPropagation' in modal_block

    def test_close_x_closes(self):
        html = _HTML_PATH.read_text(encoding='utf-8')
        js = _JS_PATH.read_text(encoding='utf-8')
        assert 'id="atpHistDetailClose"' in html
        assert "'atpHistDetailClose'" in js
        assert 'closeHistoryDetailModal' in js.split("['atpHistDetailClose'")[1].split('histDetailBackdrop')[0]

    def test_close_button_closes(self):
        html = _HTML_PATH.read_text(encoding='utf-8')
        js = _JS_PATH.read_text(encoding='utf-8')
        assert 'id="atpHistDetailDismiss"' in html
        assert "'atpHistDetailDismiss'" in js
        assert 'Kapat' in html.split('id="atpHistDetailDismiss"')[1][:80]

    def test_escape_closes(self):
        js = _JS_PATH.read_text(encoding='utf-8')
        esc = js.split("e.key !== 'Escape'")[1].split('closeTimelineModal')[0]
        assert 'histOpen' in esc
        assert 'closeHistoryDetailModal()' in esc

    def test_focus_returns_to_opener(self):
        js = _JS_PATH.read_text(encoding='utf-8')
        assert 'openHistoryDetailModal(pid, btn)' in js
        assert '_hdmPrevFocus = returnFocusEl' in js
        close_fn = js.split('function closeHistoryDetailModal')[1].split('atpHistDetailClose')[0]
        assert '_hdmPrevFocus.focus' in close_fn

    def test_location_url_passthrough_and_plan7_counts(self, canonical_copy_db):
        from modules.planlama.arac_takip_repo import get_history_plan_detail

        detail = get_history_plan_detail(7)
        assert detail['ok'] is True
        p = detail['plan']
        assert p['completed'] == 3
        assert p['visited_pending'] == 1
        assert p['started_without_visit'] == 1
        assert p['not_visited'] == 6
        assert p['cancelled'] == 1
        assert p['active_jobs'] == 11
        assert p['completed'] + p['visited_pending'] + p['started_without_visit'] + p['not_visited'] == p['active_jobs']
        items = detail['items']
        assert all('location_url' in it for it in items)
        by = {it['company_name'].lower(): it for it in items}
        assert by['c otomotiv']['category'] == 'BASLADI_ZIYARET_DOGRULANAMADI'
        assert by['şahin']['category'] == 'ZIYARET_SONUC_BEKLIYOR'
        assert by['violet etiket']['category'] == 'GIDILMEDI'
        for it in items:
            assert _hdm_address_visible(it['address_text']) == (
                '' if _hdm_is_maps_url(it['address_text']) else (it['address_text'] or '').strip()
            )

    def test_canonical_db_not_written_by_detail(self, canonical_copy_db):
        import hashlib

        if not CANONICAL_SOURCE.exists():
            pytest.skip('Canonical DB not available')
        h_before = hashlib.sha256(CANONICAL_SOURCE.read_bytes()).hexdigest()
        from modules.planlama.arac_takip_repo import get_history_plan_detail
        get_history_plan_detail(7)
        h_after = hashlib.sha256(CANONICAL_SOURCE.read_bytes()).hexdigest()
        assert h_before == h_after


class TestHistoryDatePanelForcedClose:
    def test_apply_closes_before_fetch(self):
        js = _JS_PATH.read_text(encoding='utf-8')
        apply_block = js.split("applyBtn.addEventListener('click'")[1].split('document.addEventListener')[0]
        assert 'e.preventDefault()' in apply_block
        assert 'e.stopPropagation()' in apply_block
        assert apply_block.index('closeHistoryDatePanel()') < apply_block.index('loadHistory()')

    def test_render_does_not_reopen_date_panel(self):
        js = _JS_PATH.read_text(encoding='utf-8')
        load_fn = js.split('function loadHistory()')[1].split('function renderHistoryRows')[0]
        render_fn = js.split('function renderHistoryRows')[1].split('var HDM_MONTHS')[0]
        opts_fn = js.split('function _hfbLoadFilterOptions()')[1].split('function _ensureHistDefaultDates')[0]
        for block in (load_fn, render_fn, opts_fn):
            assert 'openHistoryDatePanel' not in block
            assert "panel.style.display = 'flex'" not in block

    def test_detail_open_closes_all_filter_panels(self):
        js = _JS_PATH.read_text(encoding='utf-8')
        head = js.split('function openHistoryDetailModal')[1][:220]
        assert 'closeAllHistoryFilterPanels();' in head
        assert 'function closeAllHistoryFilterPanels' in js
        assert 'function closeHistoryDatePanel' in js
        assert 'function closeVehicleDropdown' in js
        assert 'function closeDriverDropdown' in js

    def test_modal_has_higher_layer_than_filters(self):
        css = _CSS_PATH.read_text(encoding='utf-8')
        assert 'z-index:40' in css or 'z-index: 40' in css
        assert 'z-index:1100' in css or 'z-index: 1100' in css
        assert 'z-index:1101' in css or 'z-index: 1101' in css

    def test_modal_close_does_not_restore_filter_panel(self):
        js = _JS_PATH.read_text(encoding='utf-8')
        close_fn = js.split('function closeHistoryDetailModal')[1].split("['atpHistDetailClose'")[0]
        assert 'openHistoryDatePanel' not in close_fn
        assert 'openPanel' not in close_fn

    def test_single_fetch_on_apply(self):
        js = _JS_PATH.read_text(encoding='utf-8')
        apply_block = js.split("applyBtn.addEventListener('click'")[1].split('document.addEventListener')[0]
        assert apply_block.count('loadHistory()') == 1

    def test_filter_and_clear_close_panels(self):
        js = _JS_PATH.read_text(encoding='utf-8')
        filter_block = js.split("filterBtn.addEventListener('click'")[1].split('/* Clear button */')[0]
        clear_block = js.split("clearBtn.addEventListener('click'")[1].split('function _histStatusBadgeCls')[0]
        assert 'closeAllHistoryFilterPanels()' in filter_block
        assert 'closeAllHistoryFilterPanels()' in clear_block
