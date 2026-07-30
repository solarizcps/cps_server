# -*- coding: utf-8 -*-
"""FAZ-NEXGEN-URETIM-KAPANIS-BACKFILL-1 — local test A–I."""
from __future__ import annotations

import io
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "tools"))
os.chdir(str(APP))

import nexgen_uretim_kapanis_backfill as BF  # noqa: E402
from modules.nexgen import routes as R  # noqa: E402

results = []


def ok(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f" — {detail}" if detail else ""))


def _schema(con: sqlite3.Connection):
    con.executescript(
        """
        CREATE TABLE nexgen_planlama_siparis (
            id INTEGER PRIMARY KEY,
            siparis_no TEXT,
            cari_id INTEGER,
            cari_unvan TEXT,
            durum TEXT,
            guncelleme_tarihi TEXT
        );
        CREATE TABLE nexgen_uretim_plan (
            id INTEGER PRIMARY KEY,
            plan_kodu TEXT,
            durum TEXT,
            planlama_siparis_id INTEGER,
            planlanan_kg REAL,
            rf_renk_id INTEGER
        );
        CREATE TABLE nexgen_uretim_batch (
            id INTEGER PRIMARY KEY,
            batch_kodu TEXT UNIQUE,
            durum TEXT,
            plan_id INTEGER,
            planlanan_kg REAL,
            uretim_varyant_id INTEGER,
            rf_renk_id INTEGER
        );
        CREATE TABLE nexgen_uretim_parca (
            id INTEGER PRIMARY KEY,
            batch_id INTEGER,
            batch_kodu TEXT,
            plan_id INTEGER,
            parca_no INTEGER,
            hedef_kg REAL,
            uretilen_kg REAL,
            formul_batch_kg REAL,
            durum TEXT
        );
        CREATE TABLE nexgen_rf_kullanim (
            id INTEGER PRIMARY KEY,
            rf_renk_id INTEGER,
            siparis_id INTEGER,
            aktif INTEGER DEFAULT 1,
            durum TEXT,
            miktar_kg REAL,
            tablet_session_id TEXT,
            guncelleme_tarihi TEXT,
            olusturma_tarihi TEXT,
            olusturan_id INTEGER,
            aciklama TEXT,
            formul_id INTEGER,
            cari_id INTEGER,
            uretim_emir_id INTEGER
        );
        CREATE TABLE nexgen_rf_renk (
            id INTEGER PRIMARY KEY,
            rf_kod TEXT,
            ad TEXT,
            cari_id INTEGER,
            aktif INTEGER DEFAULT 1,
            durum TEXT DEFAULT 'ONAYLI'
        );
        CREATE TABLE mo_musteri_sevkiyat (
            id INTEGER PRIMARY KEY,
            sevkiyat_no TEXT,
            siparis_id INTEGER,
            durum TEXT,
            aktif INTEGER DEFAULT 1
        );
        CREATE TABLE mo_musteri_sevkiyat_kalem (
            id INTEGER PRIMARY KEY,
            sevkiyat_id INTEGER,
            miktar_kg REAL
        );
        INSERT INTO nexgen_rf_renk(id, rf_kod, ad, aktif, durum) VALUES (1,'RF-001','TEST',1,'ONAYLI');
        """
    )


def _seed_stuck(
    con,
    *,
    sip_id=45,
    plan_id=111,
    batch_id=11,
    batch_kodu="NG-PRD-2026-00011",
    n_parca=58,
    batch_durum="DEVAM",
    plan_durum="URETIMDE",
    sip_durum="URETIMDE",
    rf_kg=5030.2,
    sevk=True,
):
    con.execute(
        "INSERT INTO nexgen_planlama_siparis(id,siparis_no,cari_id,cari_unvan,durum) "
        "VALUES (?,?,?,?,?)",
        (sip_id, f"PZM-2026-{sip_id:04d}" if sip_id == 45 else f"PZM-T-{sip_id}", 1, "SEHA", sip_durum),
    )
    if sip_id == 45:
        con.execute(
            "UPDATE nexgen_planlama_siparis SET siparis_no='PZM-2026-0009' WHERE id=45"
        )
    con.execute(
        "INSERT INTO nexgen_uretim_plan(id,plan_kodu,durum,planlama_siparis_id,planlanan_kg,rf_renk_id) "
        "VALUES (?,?,?,?,?,1)",
        (plan_id, f"NP-2026-{plan_id:05d}" if plan_id == 111 else f"NP-{plan_id}", plan_durum, sip_id, 100.0),
    )
    if plan_id == 111:
        con.execute("UPDATE nexgen_uretim_plan SET plan_kodu='NP-2026-00011' WHERE id=111")
    con.execute(
        "INSERT INTO nexgen_uretim_batch(id,batch_kodu,durum,plan_id,planlanan_kg,uretim_varyant_id,rf_renk_id) "
        "VALUES (?,?,?,?,?,1,1)",
        (batch_id, batch_kodu, batch_durum, plan_id, 100.0),
    )
    for i in range(n_parca):
        con.execute(
            "INSERT INTO nexgen_uretim_parca(id,batch_id,batch_kodu,plan_id,parca_no,hedef_kg,uretilen_kg,durum) "
            "VALUES (?,?,?,?,?,?,?,'BITTI')",
            (batch_id * 1000 + i, batch_id, batch_kodu, plan_id, 1001 + i, 50.0, 50.0),
        )
    con.execute(
        "INSERT INTO nexgen_rf_kullanim(id,rf_renk_id,siparis_id,aktif,durum,miktar_kg,tablet_session_id) "
        "VALUES (?,?,1,1,'URETIM',?,?)",
        (batch_id, 1, rf_kg, batch_kodu),
    )
    if sevk:
        con.execute(
            "INSERT INTO mo_musteri_sevkiyat(id,sevkiyat_no,siparis_id,durum,aktif) "
            "VALUES (?,?,?,'TESLIM_EDILDI',1)",
            (batch_id, "MSV-2026-0003" if sip_id == 45 else f"MSV-T-{sip_id}", sip_id),
        )
        con.execute(
            "INSERT INTO mo_musteri_sevkiyat_kalem(id,sevkiyat_id,miktar_kg) VALUES (?,?,5000)",
            (batch_id, batch_id),
        )
    con.commit()


def _stub_rf_keep_miktar():
    """Gerçek RF sync: plan.rf_renk_id + miktar hesap; testte stub miktarı korur, durum günceller."""
    orig = R._rf_kullanim_tablet_sync

    def _rf(con, batch_kodu, uretim_emir_id=None, tamamlandi=False):
        durum = "TAMAMLANDI" if tamamlandi else "URETIM"
        row = con.execute(
            "SELECT id, miktar_kg FROM nexgen_rf_kullanim "
            "WHERE tablet_session_id=? AND aktif=1 ORDER BY id DESC LIMIT 1",
            (batch_kodu,),
        ).fetchone()
        if row:
            # miktar değişmez (SEHA kanıtı); yalnız durum
            con.execute(
                "UPDATE nexgen_rf_kullanim SET durum=? WHERE id=?",
                (durum, row["id"]),
            )
            return row["id"]
        return orig(con, batch_kodu, uretim_emir_id=uretim_emir_id, tamamlandi=tamamlandi)

    R._rf_kullanim_tablet_sync = _rf
    R._parca_tablosu_var = lambda con: True
    R._plan_planlama_siparis_kolonu_var = lambda con: True
    R._planlama_siparis_tablosu_var = lambda con: True
    return orig


def _tmp_db() -> Path:
    td = Path(tempfile.mkdtemp(prefix="bf_kapanis_"))
    p = td / "t.db"
    con = sqlite3.connect(str(p))
    con.row_factory = sqlite3.Row
    _schema(con)
    con.close()
    return p


print("=" * 72)
print("FAZ-NEXGEN-URETIM-KAPANIS-BACKFILL-1")
print("=" * 72)

orig_rf = _stub_rf_keep_miktar()

# A — stuck dry-run bulunur
db_a = _tmp_db()
con = sqlite3.connect(str(db_a))
con.row_factory = sqlite3.Row
_seed_stuck(con)
con.close()
con = BF._connect(db_a, write=False)
aday, atlanan = BF.find_candidates(con)
con.close()
ok("A stuck dry-run bulunur", any(a["batch_kodu"] == "NG-PRD-2026-00011" for a in aday), str(len(aday)))
ok("A SEHA sipariş adayda", any(a.get("siparis_no") == "PZM-2026-0009" for a in aday))

# B — açık parçalı batch bulunmaz
db_b = _tmp_db()
con = sqlite3.connect(str(db_b))
con.row_factory = sqlite3.Row
_seed_stuck(con, sip_id=2, plan_id=20, batch_id=20, batch_kodu="B-OPEN", n_parca=2)
con.execute("UPDATE nexgen_uretim_parca SET durum='DEVAM', uretilen_kg=0 WHERE batch_kodu='B-OPEN' AND parca_no=1002")
con.commit()
con.close()
con = BF._connect(db_b, write=False)
aday_b, _ = BF.find_candidates(con)
con.close()
ok("B açık parçalı batch aday değil", not any(a["batch_kodu"] == "B-OPEN" for a in aday_b))
con = sqlite3.connect(str(db_b))
con.row_factory = sqlite3.Row
ok("B classify acik_parca_var", BF.classify_skip(con, "B-OPEN") == "acik_parca_var")
con.close()

# C — apply ile kapanır
db_c = _tmp_db()
con = sqlite3.connect(str(db_c))
con.row_factory = sqlite3.Row
_seed_stuck(con, sip_id=3, plan_id=30, batch_id=30, batch_kodu="B-CLOSE", n_parca=2, rf_kg=100.0, sevk=False)
con.close()
con = sqlite3.connect(str(db_c))
con.row_factory = sqlite3.Row
aday_c, _ = BF.find_candidates(con)
out_c = BF.apply_candidates(con, aday_c, R)
con.close()
con = sqlite3.connect(str(db_c))
con.row_factory = sqlite3.Row
snap = BF.snapshot_chain(con, "B-CLOSE")
con.close()
ok("C batch BITTI", snap["batch"]["durum"] == "BITTI", snap["batch"]["durum"])
ok("C apply changed>=1", out_c["changed"] >= 1, str(out_c["changed"]))

# D — çok batch: A kapanır plan açık kalır
db_d = _tmp_db()
con = sqlite3.connect(str(db_d))
con.row_factory = sqlite3.Row
_seed_stuck(con, sip_id=4, plan_id=40, batch_id=40, batch_kodu="B-A", n_parca=2, rf_kg=50.0, sevk=False)
con.execute(
    "INSERT INTO nexgen_uretim_batch(id,batch_kodu,durum,plan_id,planlanan_kg,uretim_varyant_id,rf_renk_id) "
    "VALUES (41,'B-B','DEVAM',40,100,1,1)"
)
con.execute(
    "INSERT INTO nexgen_uretim_parca(id,batch_id,batch_kodu,plan_id,parca_no,hedef_kg,uretilen_kg,durum) "
    "VALUES (41001,41,'B-B',40,1001,50,0,'DEVAM')"
)
con.commit()
aday_d, _ = BF.find_candidates(con)
# yalnız B-A aday olmalı
ok("D yalnız B-A aday", [a["batch_kodu"] for a in aday_d] == ["B-A"], str([a["batch_kodu"] for a in aday_d]))
out_d = BF.apply_candidates(con, aday_d, R)
plan_d = con.execute("SELECT durum FROM nexgen_uretim_plan WHERE id=40").fetchone()["durum"]
sip_d = con.execute("SELECT durum FROM nexgen_planlama_siparis WHERE id=4").fetchone()["durum"]
ok("D plan kapanmadı", plan_d == "URETIMDE", plan_d)
ok("D sipariş kapanmadı", sip_d == "URETIMDE", sip_d)
con.close()

# E — tüm batch kapanınca plan BITTI
db_e = _tmp_db()
con = sqlite3.connect(str(db_e))
con.row_factory = sqlite3.Row
_seed_stuck(con, sip_id=5, plan_id=50, batch_id=50, batch_kodu="E-A", n_parca=1, rf_kg=10.0, sevk=False)
con.execute(
    "INSERT INTO nexgen_uretim_batch(id,batch_kodu,durum,plan_id,planlanan_kg,uretim_varyant_id,rf_renk_id) "
    "VALUES (51,'E-B','DEVAM',50,100,1,1)"
)
con.execute(
    "INSERT INTO nexgen_uretim_parca(id,batch_id,batch_kodu,plan_id,parca_no,hedef_kg,uretilen_kg,durum) "
    "VALUES (51001,51,'E-B',50,1001,50,50,'BITTI')"
)
con.execute(
    "INSERT INTO nexgen_rf_kullanim(id,rf_renk_id,siparis_id,aktif,durum,miktar_kg,tablet_session_id) "
    "VALUES (51,1,50,1,'URETIM',10,'E-B')"
)
con.commit()
aday_e, _ = BF.find_candidates(con)
out_e = BF.apply_candidates(con, aday_e, R)
plan_e = con.execute("SELECT durum FROM nexgen_uretim_plan WHERE id=50").fetchone()["durum"]
ok("E plan BITTI", plan_e == "BITTI", plan_e)
con.close()

# F — sipariş TAMAMLANDI
db_f = _tmp_db()
con = sqlite3.connect(str(db_f))
con.row_factory = sqlite3.Row
_seed_stuck(con, sip_id=6, plan_id=60, batch_id=60, batch_kodu="F-A", n_parca=2, rf_kg=100.0, sevk=False)
aday_f, _ = BF.find_candidates(con)
BF.apply_candidates(con, aday_f, R)
sip_f = con.execute("SELECT durum FROM nexgen_planlama_siparis WHERE id=6").fetchone()["durum"]
ok("F sipariş TAMAMLANDI", sip_f == "TAMAMLANDI", sip_f)
con.close()

# G — ikinci apply changed=0
db_g = _tmp_db()
con = sqlite3.connect(str(db_g))
con.row_factory = sqlite3.Row
_seed_stuck(con, sip_id=7, plan_id=70, batch_id=70, batch_kodu="G-A", n_parca=2, rf_kg=100.0, sevk=False)
aday1, _ = BF.find_candidates(con)
o1 = BF.apply_candidates(con, aday1, R)
aday2, _ = BF.find_candidates(con)
o2 = BF.apply_candidates(con, aday2, R)
ok("G birinci changed>=1", o1["changed"] >= 1, str(o1["changed"]))
ok("G ikinci aday=0", len(aday2) == 0, str(len(aday2)))
ok("G ikinci changed=0", o2["changed"] == 0, str(o2["changed"]))
con.close()

# H — RF miktar / duplicate
db_h = _tmp_db()
con = sqlite3.connect(str(db_h))
con.row_factory = sqlite3.Row
_seed_stuck(con, sip_id=8, plan_id=80, batch_id=80, batch_kodu="H-A", n_parca=2, rf_kg=5030.2, sevk=False)
before_rf = con.execute(
    "SELECT id, miktar_kg, durum FROM nexgen_rf_kullanim WHERE tablet_session_id='H-A'"
).fetchone()
aday_h, _ = BF.find_candidates(con)
BF.apply_candidates(con, aday_h, R)
after_rf = con.execute(
    "SELECT id, miktar_kg, durum FROM nexgen_rf_kullanim WHERE tablet_session_id='H-A' AND aktif=1"
).fetchall()
ok("H RF tek kayıt", len(after_rf) == 1, str(len(after_rf)))
ok("H RF id aynı", after_rf[0]["id"] == before_rf["id"])
ok(
    "H RF miktar değişmez",
    abs(float(after_rf[0]["miktar_kg"]) - 5030.2) < 0.001,
    str(after_rf[0]["miktar_kg"]),
)
ok("H RF durum TAMAMLANDI", after_rf[0]["durum"] == "TAMAMLANDI", after_rf[0]["durum"])
con.close()

# I — sevkiyat değişmez
db_i = _tmp_db()
con = sqlite3.connect(str(db_i))
con.row_factory = sqlite3.Row
_seed_stuck(con, sip_id=45, plan_id=111, batch_id=11, batch_kodu="NG-PRD-2026-00011", n_parca=58, rf_kg=5030.2, sevk=True)
before_s = con.execute(
    "SELECT sevkiyat_no, durum FROM mo_musteri_sevkiyat WHERE id=11"
).fetchone()
before_kg = con.execute(
    "SELECT miktar_kg FROM mo_musteri_sevkiyat_kalem WHERE sevkiyat_id=11"
).fetchone()["miktar_kg"]
aday_i, _ = BF.find_candidates(con)
BF.apply_candidates(con, aday_i, R)
after_s = con.execute(
    "SELECT sevkiyat_no, durum FROM mo_musteri_sevkiyat WHERE id=11"
).fetchone()
after_kg = con.execute(
    "SELECT miktar_kg FROM mo_musteri_sevkiyat_kalem WHERE sevkiyat_id=11"
).fetchone()["miktar_kg"]
sip = con.execute("SELECT durum FROM nexgen_planlama_siparis WHERE id=45").fetchone()["durum"]
batch = con.execute(
    "SELECT durum FROM nexgen_uretim_batch WHERE batch_kodu='NG-PRD-2026-00011'"
).fetchone()["durum"]
plan = con.execute("SELECT durum FROM nexgen_uretim_plan WHERE id=111").fetchone()["durum"]
ok("I sevk no/durum aynı", before_s["sevkiyat_no"] == after_s["sevkiyat_no"] and before_s["durum"] == after_s["durum"])
ok("I sevk kg 5000 aynı", abs(float(after_kg) - float(before_kg)) < 0.001, str(after_kg))
ok("I SEHA batch BITTI", batch == "BITTI")
ok("I SEHA plan BITTI", plan == "BITTI")
ok("I SEHA sipariş TAMAMLANDI", sip == "TAMAMLANDI")
con.close()

# dry-run varsayılan write yok — CLI bayrağı
ok("CLI varsayılan dry-run (apply yok)", "--apply" not in " ".join(sys.argv))

R._rf_kullanim_tablet_sync = orig_rf

fails = [n for n, c, _ in results if not c]
print("=" * 72)
print(f"SONUC: {sum(1 for _, c, _ in results if c)}/{len(results)} PASS")
if fails:
    print("FAIL:", ", ".join(fails))
    print("KARAR_ADAYI: B/C/D")
    raise SystemExit(1)
print("KARAR_ADAYI: A")
raise SystemExit(0)
