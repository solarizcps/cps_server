# -*- coding: utf-8 -*-
"""
Araç Takip test verisi ekleme — temp DB only.

UNIQUE constraint: arac_gunluk_plan_is(is_talebi_id)
Çözüm: Her iş için ayrı is_talebi satırı oluştur.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import time as _time

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.join(_ROOT, 'app')
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

os.environ.setdefault('CPS_TEST_DB_GUARD', '1')

from tools.nexgen_tmp_db import (  # noqa: E402
    assert_resolved_db_is_tmp,
    canonical_db_path,
)
from tools.test_db_guard import (  # noqa: E402
    bootstrap_adhoc_script_guards,
    guard_is_active,
    run_adhoc_with_tmp_db,
)


def run_seed(db_path: str, *, backup_dir: str | None = None) -> None:
    """Insert ATP demo seed rows into the given non-canonical DB path."""
    live = canonical_db_path()
    assert_resolved_db_is_tmp(os.path.abspath(db_path), live)

    if backup_dir:
        os.makedirs(backup_dir, exist_ok=True)
        backup = os.path.join(backup_dir, 'mock_data_before_seed.db')
        shutil.copy2(db_path, backup)
        print(f'Backup (temp): {backup}')

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    TODAY = '2026-08-24'
    MOR_EXT = '45077045'
    GFK_EXT = '45074345'

    r = con.execute(
        "SELECT MAX(CAST(REPLACE(talep_no,'AIT-2026-','') AS INT)) FROM arac_is_talebi"
    ).fetchone()
    counter = [int(r[0]) if r[0] else 202]

    def next_no():
        counter[0] += 1
        return f'AIT-2026-{counter[0]:04d}'

    cols = [row[1] for row in con.execute('PRAGMA table_info(arac_is_talebi)').fetchall()]
    saat_col = 'istened_saat' if 'istened_saat' in cols else 'istenen_saat'
    print(f'Saat kolonu: {saat_col}')

    def new_is2(firma, is_tipi, saat, lat, lng, adres='İstanbul'):
        talep_no = next_no()
        cur.execute(
            f"""
        INSERT INTO arac_is_talebi
          (talep_no, talep_eden_user_id, talep_eden_adi_snapshot,
           talep_tarihi, {saat_col}, firma_adi, adres, yapilacak_is,
           latitude, longitude, durum, oncelik,
           created_at, created_by, updated_at, updated_by, save_to_master)
        VALUES (?, 1, 'Sistem', ?, ?, ?, ?, ?, ?, ?, 'PLANA_ALINDI', 'NORMAL',
                datetime('now'), 1, datetime('now'), 1, 0)
    """,
            (talep_no, TODAY, saat, firma, adres, is_tipi, lat, lng),
        )
        return cur.lastrowid

    cur.execute(
        "UPDATE arac_gunluk_plan SET sofor_adi_snapshot='Oktay KAŞIKÇI' "
        'WHERE plan_tarihi=? AND arac_external_id=?',
        (TODAY, MOR_EXT),
    )
    plan7 = con.execute(
        'SELECT id FROM arac_gunluk_plan WHERE plan_tarihi=? AND arac_external_id=?',
        (TODAY, MOR_EXT),
    ).fetchone()
    plan7_id = plan7['id']
    print(f'MOR plan id: {plan7_id}')

    cur.execute('DELETE FROM arac_plan_is_ziyaret_durum WHERE plan_id=?', (plan7_id,))
    cur.execute('DELETE FROM arac_gunluk_plan_is WHERE plan_id=?', (plan7_id,))
    con.commit()

    mor_jobs = [
        ('AVEL Avrupa Elektrik', 'Numune teslimi', '09:30', 40.9987, 28.8235, 'Tuzla, İstanbul', 1, 'TAMAMLANDI'),
        ('MAP14A / Malzeme', 'Malzeme alınacak', '11:00', 41.0231, 28.9476, 'Bağcılar, İstanbul', 2, 'TAMAMLANDI'),
        ('B Lojistik', 'Evrak teslimi', '14:30', 41.0612, 29.0087, 'Ümraniye, İstanbul', 3, 'TAMAMLANDI'),
        ('C Otomotiv', 'Ürün alınacak', '16:00', 40.9765, 29.1234, 'Kartal, İstanbul', 4, 'BASLADI'),
        ('AVEL Avrupa Elektrik', '2. ziyaret', '17:30', 40.9987, 28.8235, 'Tuzla, İstanbul', 5, 'PLANLANDI'),
    ]
    mor_gpi = []
    for firma, is_tipi, saat, lat, lng, adres, sira, durum in mor_jobs:
        is_id = new_is2(firma, is_tipi, saat, lat, lng, adres)
        cur.execute(
            """
        INSERT INTO arac_gunluk_plan_is (plan_id, is_talebi_id, sira, planlanan_saat, durum, created_at, created_by)
        VALUES (?, ?, ?, ?, ?, datetime('now'), 1)
    """,
            (plan7_id, is_id, sira, saat, durum),
        )
        mor_gpi.append((sira, cur.lastrowid))
    con.commit()

    gpi_by_sira = dict(mor_gpi)
    mor_visits = [
        (1, '09:28', '09:46', 'DEPARTED', 'TAMAMLANDI'),
        (2, '11:02', '11:23', 'DEPARTED', 'TAMAMLANDI'),
        (3, '14:27', '14:46', 'DEPARTED', 'TAMAMLANDI'),
        (4, '16:00', None, 'ARRIVED', None),
    ]
    for sira, arr, dep, state, res in mor_visits:
        gpi_id = gpi_by_sira.get(sira)
        if not gpi_id:
            continue
        arr_dt = f'{TODAY} {arr}:00' if arr else None
        dep_dt = f'{TODAY} {dep}:00' if dep else None
        dwell = None
        if arr and dep:
            ah, am = map(int, arr.split(':'))
            dh, dm = map(int, dep.split(':'))
            dwell = (dh * 60 + dm - ah * 60 - am) * 60
        cur.execute(
            """
        INSERT INTO arac_plan_is_ziyaret_durum
          (plan_id, plan_is_id, arac_external_id, state,
           arrived_at, departed_at, dwell_seconds, result_status,
           updated_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
    """,
            (plan7_id, gpi_id, MOR_EXT, state, arr_dt, dep_dt, dwell, res),
        )
    con.commit()
    print('MOR 049 güncellendi: 5 iş (3 tamamlandı, 1 yolda, 1 planlandı)')

    existing_gfk = con.execute(
        'SELECT id FROM arac_gunluk_plan WHERE plan_tarihi=? AND arac_external_id=?',
        (TODAY, GFK_EXT),
    ).fetchone()
    if existing_gfk:
        gfk_plan_id = existing_gfk['id']
        cur.execute('DELETE FROM arac_plan_is_ziyaret_durum WHERE plan_id=?', (gfk_plan_id,))
        cur.execute('DELETE FROM arac_gunluk_plan_is WHERE plan_id=?', (gfk_plan_id,))
        cur.execute(
            "UPDATE arac_gunluk_plan SET sofor_adi_snapshot='Serhat GÜLMEN' WHERE id=?",
            (gfk_plan_id,),
        )
        print(f'GFK plan mevcut (id={gfk_plan_id}), güncelleniyor')
    else:
        cur.execute(
            """
        INSERT INTO arac_gunluk_plan
          (plan_tarihi, arac_provider, arac_external_id, arac_plaka_snapshot,
           sofor_id, sofor_adi_snapshot, durum, created_at, created_by, updated_at, updated_by)
        VALUES (?, 'TURKCELL_FILOM', ?, '34 GFK 183', 1, 'Serhat GÜLMEN', 'AKTIF',
                datetime('now'), 1, datetime('now'), 1)
    """,
            (TODAY, GFK_EXT),
        )
        gfk_plan_id = cur.lastrowid
        print(f'GFK yeni plan: id={gfk_plan_id}')
    con.commit()

    gfk_jobs = [
        ('MAP14A / Malzeme', 'Malzeme alınacak', '11:00', 41.0231, 28.9476, 'Bağcılar, İstanbul', 1, 'TAMAMLANDI'),
        ('B Lojistik', 'Evrak teslimi', '13:30', 41.0612, 29.0087, 'Ümraniye, İstanbul', 2, 'TAMAMLANDI'),
        ('C Otomotiv', 'Ürün alınacak', '15:10', 40.9765, 29.1234, 'Kartal, İstanbul', 3, 'PLANLANDI'),
        ('AVEL Avrupa Elektrik', 'Numune teslimi', '17:00', 40.9987, 28.8235, 'Tuzla, İstanbul', 4, 'PLANLANDI'),
    ]
    gfk_gpi = []
    for firma, is_tipi, saat, lat, lng, adres, sira, durum in gfk_jobs:
        is_id = new_is2(firma, is_tipi, saat, lat, lng, adres)
        cur.execute(
            """
        INSERT INTO arac_gunluk_plan_is (plan_id, is_talebi_id, sira, planlanan_saat, durum, created_at, created_by)
        VALUES (?, ?, ?, ?, ?, datetime('now'), 1)
    """,
            (gfk_plan_id, is_id, sira, saat, durum),
        )
        gfk_gpi.append((sira, cur.lastrowid))
    con.commit()

    gfk_by_sira = dict(gfk_gpi)
    gfk_visits = [
        (1, '11:05', '11:34'),
        (2, '13:42', '14:05'),
    ]
    for sira, arr, dep in gfk_visits:
        gpi_id = gfk_by_sira.get(sira)
        if not gpi_id:
            continue
        arr_dt = f'{TODAY} {arr}:00'
        dep_dt = f'{TODAY} {dep}:00'
        ah, am = map(int, arr.split(':'))
        dh, dm = map(int, dep.split(':'))
        dwell = (dh * 60 + dm - ah * 60 - am) * 60
        cur.execute(
            """
        INSERT INTO arac_plan_is_ziyaret_durum
          (plan_id, plan_is_id, arac_external_id, state,
           arrived_at, departed_at, dwell_seconds, result_status,
           updated_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'TAMAMLANDI', datetime('now'), datetime('now'))
    """,
            (gfk_plan_id, gpi_id, GFK_EXT, 'DEPARTED', arr_dt, dep_dt, dwell),
        )

    dedup = f'{GFK_EXT}_{int(_time.time())}'
    cur.execute(
        """
    INSERT INTO arac_gps_snapshot
      (arac_external_id, arac_provider, plate_snapshot, gps_timestamp, received_at,
       latitude, longitude, speed_kmh, activity_status, ignition_status,
       odometer_km, is_stale, dedup_key, created_at)
    VALUES (?, 'TURKCELL_FILOM', '34 GFK 183',
            datetime('now','-3 minutes'), datetime('now'),
            41.0612, 29.0087, 35.0, 'HAREKETLI', 'Açık', 152560.0, 0, ?, datetime('now'))
""",
        (GFK_EXT, dedup),
    )

    con.commit()
    print('GFK 183: 4 iş (2 tamamlandı, 2 planlandı) + GPS snapshot')

    print('\n=== SONUÇ ===')
    rows = con.execute(
        """
    SELECT gp.arac_plaka_snapshot AS plaka, gp.sofor_adi_snapshot AS sofor,
           COUNT(gpi.id) as toplam,
           SUM(CASE WHEN gpi.durum='TAMAMLANDI' THEN 1 ELSE 0 END) as tamam,
           SUM(CASE WHEN gpi.durum='BASLADI'    THEN 1 ELSE 0 END) as devam,
           SUM(CASE WHEN gpi.durum='PLANLANDI'  THEN 1 ELSE 0 END) as planli
    FROM arac_gunluk_plan gp
    LEFT JOIN arac_gunluk_plan_is gpi ON gpi.plan_id=gp.id
    WHERE gp.plan_tarihi=?
    GROUP BY gp.id
""",
        (TODAY,),
    ).fetchall()
    for row in rows:
        print(' ', dict(row))

    zc = con.execute('SELECT COUNT(*) FROM arac_plan_is_ziyaret_durum').fetchone()[0]
    print(f'  Ziyaret kayıtları: {zc}')
    con.close()
    print('\nDB seed OK (temp DB).')


def main(db_path: str | None = None) -> None:
    """Run seed against a unique temp DB, or an explicit non-canonical path."""
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    os.environ['CPS_TEST_DB_GUARD'] = '1'
    live = canonical_db_path()

    if db_path:
        resolved = os.path.abspath(db_path)
        assert_resolved_db_is_tmp(resolved, live)
        if not guard_is_active():
            bootstrap_adhoc_script_guards()
        run_seed(resolved, backup_dir=os.path.join(os.path.dirname(resolved), 'backup'))
        return

    with run_adhoc_with_tmp_db(prefix='db_test_seed_') as info:
        run_seed(info['tmp_db'], backup_dir=info['tmp_dir'])


if __name__ == '__main__':
    explicit = sys.argv[1] if len(sys.argv) > 1 else None
    if explicit and os.path.abspath(explicit) == os.path.abspath(canonical_db_path()):
        raise SystemExit(
            f'Refusing canonical DB target: {explicit!r}. Use default temp mode or a non-canonical path.'
        )
    main(explicit)
