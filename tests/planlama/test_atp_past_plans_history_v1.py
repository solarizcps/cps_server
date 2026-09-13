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
        migs.append('180_arac_plan_ziyaret_durum.py')
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
