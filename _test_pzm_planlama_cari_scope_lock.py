#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0 — pzm_cari_dogrula() planlama capability cari-scope lock
7 kanonical case.

Çalıştır:
  python _test_pzm_planlama_cari_scope_lock.py
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from modules.nexgen.pzm_siparis_write import pzm_cari_dogrula, PzmWriteError

# ---------------------------------------------------------------------------
# In-memory DB kurulum
# ---------------------------------------------------------------------------

def make_db():
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE nexgen_cari (
            id INTEGER PRIMARY KEY,
            unvan TEXT,
            aktif INTEGER DEFAULT 1
        );
        CREATE TABLE sistem_kullanici (
            Id INTEGER PRIMARY KEY,
            KullaniciAdi TEXT,
            RolId INTEGER,
            Aktif INTEGER DEFAULT 1
        );
        CREATE TABLE sistem_rol (
            Id INTEGER PRIMARY KEY,
            Ad TEXT
        );
        CREATE TABLE sistem_yetki (
            Id INTEGER PRIMARY KEY,
            Kod TEXT,
            Ad TEXT,
            Modul TEXT
        );
        CREATE TABLE sistem_rol_yetki (
            Id INTEGER PRIMARY KEY,
            RolId INTEGER,
            YetkiId INTEGER,
            can_view INTEGER DEFAULT 0,
            can_create INTEGER DEFAULT 0,
            can_update INTEGER DEFAULT 0,
            can_delete INTEGER DEFAULT 0,
            can_approve INTEGER DEFAULT 0,
            can_report INTEGER DEFAULT 0,
            can_manage INTEGER DEFAULT 0
        );
        CREATE TABLE user_permission_override (
            Id INTEGER PRIMARY KEY,
            KullaniciId INTEGER,
            YetkiId INTEGER,
            can_view INTEGER DEFAULT 0,
            can_create INTEGER DEFAULT 0,
            can_update INTEGER DEFAULT 0,
            can_delete INTEGER DEFAULT 0,
            can_approve INTEGER DEFAULT 0,
            can_report INTEGER DEFAULT 0,
            can_manage INTEGER DEFAULT 0
        );
        CREATE TABLE cari_sorumlu (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cari_id INTEGER,
            kullanici_id INTEGER,
            sorumluluk_rolu TEXT,
            baslangic_tarihi TEXT,
            bitis_tarihi TEXT,
            aktif INTEGER DEFAULT 1,
            atayan_kullanici_id INTEGER,
            atama_notu TEXT,
            created_at TEXT,
            updated_at TEXT
        );
    """)

    # Cariler
    con.execute("INSERT INTO nexgen_cari VALUES (1, 'Beoss Ayakkabi', 1)")
    con.execute("INSERT INTO nexgen_cari VALUES (2, 'Diger Aktif Cari', 1)")
    con.execute("INSERT INTO nexgen_cari VALUES (3, 'Pasif Cari', 0)")

    # Roller
    con.execute("INSERT INTO sistem_rol VALUES (32, 'Planlama')")
    con.execute("INSERT INTO sistem_rol VALUES (45, 'Musteri Temsilcisi')")

    # Yetkiler
    con.execute("INSERT INTO sistem_yetki VALUES (1, 'nexgen.plan.manage', 'NexGen Plan', 'nexgen')")
    con.execute("INSERT INTO sistem_yetki VALUES (2, 'cari360.view', 'Cari360 View All', 'cari360')")
    con.execute("INSERT INTO sistem_yetki VALUES (3, 'cari360.view_own', 'Cari360 View Own', 'cari360')")
    con.execute("INSERT INTO sistem_yetki VALUES (4, 'cari360.crm.write', 'Cari360 CRM Write', 'cari360')")

    # Kullanıcılar
    # uid=31: Mehmet (Planlama) — nexgen.plan.manage:can_manage + cari360.view_own override
    con.execute("INSERT INTO sistem_kullanici VALUES (31, 'mehmet', 32, 1)")
    # uid=49: Erhan (Müşteri Temsilcisi) — cari360.view_own + crm.write
    con.execute("INSERT INTO sistem_kullanici VALUES (49, 'erhan', 45, 1)")
    # uid=99: Yetkisiz — hiç yetki yok
    con.execute("INSERT INTO sistem_kullanici VALUES (99, 'yetkisiz', NULL, 1)")
    # uid=1: Admin
    con.execute("INSERT INTO sistem_kullanici VALUES (1, 'admin', 1, 1)")

    # Mehmet permission overrides
    con.execute("""
        INSERT INTO user_permission_override
        (KullaniciId, YetkiId, can_manage) VALUES (31, 1, 1)
    """)  # nexgen.plan.manage:can_manage
    con.execute("""
        INSERT INTO user_permission_override
        (KullaniciId, YetkiId, can_view) VALUES (31, 3, 1)
    """)  # cari360.view_own:can_view

    # Erhan permission overrides
    con.execute("""
        INSERT INTO user_permission_override
        (KullaniciId, YetkiId, can_view) VALUES (49, 3, 1)
    """)  # cari360.view_own:can_view
    con.execute("""
        INSERT INTO user_permission_override
        (KullaniciId, YetkiId, can_view, can_create, can_update) VALUES (49, 4, 1, 1, 1)
    """)  # cari360.crm.write

    # Erhan → Beoss aktif atama (cari_id=1)
    con.execute("""
        INSERT INTO cari_sorumlu
        (cari_id, kullanici_id, sorumluluk_rolu, aktif, bitis_tarihi)
        VALUES (1, 49, 'ANA', 1, NULL)
    """)

    # Mehmet → Beoss EXPIRED atama (aktif=0) — bu durum gerçek DB'yi yansıtır
    con.execute("""
        INSERT INTO cari_sorumlu
        (cari_id, kullanici_id, sorumluluk_rolu, aktif, bitis_tarihi)
        VALUES (1, 31, 'ANA', 0, '2026-08-07')
    """)

    con.commit()
    return con


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

PASS_COUNT = 0
FAIL_COUNT = 0


def check(name, got_pass, expected_pass, got_msg=None, expected_msg=None):
    global PASS_COUNT, FAIL_COUNT
    ok = (got_pass == expected_pass)
    if expected_msg and got_msg and expected_msg not in got_msg:
        ok = False
    if ok:
        PASS_COUNT += 1
        print(f"  [PASS] {name}")
    else:
        FAIL_COUNT += 1
        print(f"  [FAIL] {name}")
        print(f"         expected_pass={expected_pass} got_pass={got_pass}")
        if expected_msg:
            print(f"         expected_msg='{expected_msg}' got_msg='{got_msg}'")


def run_gate(con, cari_id, uid):
    """Returns (passed: bool, message: str | None)"""
    try:
        pzm_cari_dogrula(con, cari_id, uid=uid)
        return True, None
    except PzmWriteError as e:
        return False, e.message


# ---------------------------------------------------------------------------
# CASES
# ---------------------------------------------------------------------------

def test_case1_mehmet_beoss(con):
    """CASE 1: Mehmet + Beoss — plan.manage TRUE, cari_sorumlu expired → PASS"""
    passed, msg = run_gate(con, 1, 31)
    check("C1 Mehmet+Beoss PASS", passed, True)


def test_case2_mehmet_other_cari(con):
    """CASE 2: Mehmet + cari_id=2 (ataması yok) → PASS"""
    passed, msg = run_gate(con, 2, 31)
    check("C2 Mehmet+OtherCari PASS (no assignment)", passed, True)


def test_case3_erhan_own_cari(con):
    """CASE 3: Erhan + Beoss (aktif cari_sorumlu=ANA) → PASS"""
    passed, msg = run_gate(con, 1, 49)
    check("C3 Erhan+OwnCari PASS", passed, True)


def test_case4_erhan_nonown_cari(con):
    """CASE 4: Erhan + cari_id=2 (atama yok) → DENY 403"""
    passed, msg = run_gate(con, 2, 49)
    check("C4 Erhan+NonOwnCari DENY", passed, False,
          got_msg=msg, expected_msg='Bu cari için işlem yetkiniz yok.')


def test_case5_unauthorized_user(con):
    """CASE 5: uid=99 (hiç yetki yok) → pzm_cari_dogrula PASS
       (gate yalnız view_own/crm_write kullanıcıları için tetiklenir)"""
    # Yetkisiz kullanıcı için gate hiç girmez (ne view_own ne crm_write ne plan.manage)
    # Bu "silent pass" — cari aktif mi kontrolü geçer, scope gate'i atlar
    passed, msg = run_gate(con, 1, 99)
    # Mevcut davranış: yetkisiz kullanıcı için gate yok (uid=99 hic branch'e girmiyor)
    # Yani bu da PASS — scope check only for users who declare view_own/crm_write
    check("C5 Unauthorized silent pass (no capability → no scope gate)", passed, True)


def test_case6_admin_view_all(con):
    """CASE 6: Admin → view_all bypass → PASS her zaman"""
    # admin KullaniciAdi → load_kullanici_yetkileri → {'*'}
    passed, msg = run_gate(con, 1, 1)
    check("C6 Admin view_all PASS", passed, True)


def test_case7_pasif_cari(con):
    """CASE 7: Mehmet + cari_id=3 (pasif) → DENY (aktif kontrolü)"""
    passed, msg = run_gate(con, 3, 31)
    check("C7 Pasif cari DENY", passed, False,
          got_msg=msg, expected_msg='Seçilen cari bulunamadı.')


# ---------------------------------------------------------------------------
# BONUS: Erhan scope regression — eski behavior korunuyor mu?
# ---------------------------------------------------------------------------

def test_erhan_scope_preserved(con):
    """Erhan'ın cari scope'u bozulmadı — own=PASS, non-own=DENY"""
    p1, _ = run_gate(con, 1, 49)  # own
    p2, _ = run_gate(con, 2, 49)  # non-own
    check("B1 Erhan own→PASS", p1, True)
    check("B2 Erhan non-own→DENY", p2, False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    print("=== pzm_planlama_cari_scope LOCK ===")
    con = make_db()

    test_case1_mehmet_beoss(con)
    test_case2_mehmet_other_cari(con)
    test_case3_erhan_own_cari(con)
    test_case4_erhan_nonown_cari(con)
    test_case5_unauthorized_user(con)
    test_case6_admin_view_all(con)
    test_case7_pasif_cari(con)
    test_erhan_scope_preserved(con)

    print()
    print(f"TOPLAM: {PASS_COUNT + FAIL_COUNT}  PASS: {PASS_COUNT}  FAIL: {FAIL_COUNT}")
    sys.exit(0 if FAIL_COUNT == 0 else 1)
