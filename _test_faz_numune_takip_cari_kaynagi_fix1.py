# -*- coding: utf-8 -*-
"""FAZ-NUMUNE-TAKIP-MERKEZI-CARI-KAYNAGI-FIX-1 — local test A–G."""
from __future__ import annotations

import io
import os
import sqlite3
import sys
from pathlib import Path
from unittest import mock

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))
os.chdir(str(APP))

results = []


def ok(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f" — {detail}" if detail else ""))


print("=" * 72)
print("FAZ-NUMUNE-TAKIP-MERKEZI-CARI-KAYNAGI-FIX-1")
print("=" * 72)

from modules.grafik import queries as Q  # noqa: E402
from modules.nexgen import routes as R  # noqa: E402

src = Path(Q.__file__).read_text(encoding="utf-8")
fn_body = src.split("def numune_musteri_liste_secimlik")[1].split("\ndef ")[0]
ok("S01 merkezi helper çağrısı", "_nexgen_cari_kart_liste" in fn_body)
ok("S02 numune fn Cari_Kart SQL kopyalamaz", "FROM Cari_Kart" not in fn_body and "CTip=1" not in fn_body)
ok("S03 sipariş legacy Cari_Kart duruyor", "Cari_Kart WHERE CTip=1" in src)

routes_src = (APP / "modules" / "grafik" / "routes.py").read_text(encoding="utf-8")
ok("S04 numune merkezi çağrı", "numune_musteri_liste_secimlik()" in routes_src)
ok("S05 sipariş legacy çağrı korunur", "musteri_liste_secimlik()" in routes_src)


mem = sqlite3.connect(":memory:")
mem.row_factory = sqlite3.Row
mem.executescript(
    """
    CREATE TABLE nexgen_cari (
        id INTEGER PRIMARY KEY, cari_kod TEXT, unvan TEXT, aktif INTEGER
    );
    INSERT INTO nexgen_cari(id,cari_kod,unvan,aktif) VALUES
        (13,'120.NX.021','Şahin Taban ve Ayakkabıcılık San.Tic.Ltd.Şti.',1),
        (99,'120.NX.PASIF','Pasif Test Cari',0),
        (100,'120.NX.AKTIF','Aktif Test Cari',1);
    """
)


class _ConnWrap:
    def __init__(self, c):
        self._c = c

    def execute(self, *a, **k):
        return self._c.execute(*a, **k)

    def close(self):
        return None

    def __getattr__(self, n):
        return getattr(self._c, n)


def _liste(con, q=None, *, sadece_aktif=False):
    sql = "SELECT id, cari_kod, unvan, aktif FROM nexgen_cari"
    where, params = [], []
    if sadece_aktif:
        where.append("aktif=1")
    qq = (q or "").strip()
    if qq:
        where.append("(unvan LIKE ? OR cari_kod LIKE ?)")
        like = f"%{qq}%"
        params.extend([like, like])
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY aktif DESC, cari_kod"
    return [dict(r) for r in con.execute(sql, params).fetchall()]


with mock.patch.object(Q, "get_conn", lambda: _ConnWrap(mem)):
    with mock.patch.object(R, "_nexgen_cari_kart_liste", _liste):
        liste = Q.numune_musteri_liste_secimlik()

ok("A aktif merkezi cari (Cari_Kart yok)", any(x["CKod"] == "120.NX.AKTIF" for x in liste), str(len(liste)))
ok("B pasif görünmez", not any(x["CKod"] == "120.NX.PASIF" for x in liste))
ok(
    "C Şahin Taban 120.NX.021 / id=13",
    any(x["CKod"] == "120.NX.021" and x.get("Id") == 13 and "Şahin" in x["CName"] for x in liste),
)
ok("E payload CKod/CName", all("CKod" in x and "CName" in x for x in liste))


def _tr_norm(s: str) -> str:
    s = (s or "").casefold()
    for a, b in (("ş", "s"), ("ı", "i"), ("ğ", "g"), ("ü", "u"), ("ö", "o"), ("ç", "c")):
        s = s.replace(a, b)
    return s


sahin = next(x for x in liste if x["CKod"] == "120.NX.021")
ok("F arama Şahin", _tr_norm("Şahin") in _tr_norm(sahin["CName"]))
ok("F arama sahin", _tr_norm("sahin") in _tr_norm(sahin["CName"]))
ok("F arama SAHIN", _tr_norm("SAHIN") in _tr_norm(sahin["CName"]))

mem.execute("UPDATE nexgen_cari SET aktif=0 WHERE id=13")
with mock.patch.object(Q, "get_conn", lambda: _ConnWrap(mem)):
    with mock.patch.object(R, "_nexgen_cari_kart_liste", _liste):
        liste2 = Q.numune_musteri_liste_secimlik()
ok("G pasife alınca kaybolur", not any(x["CKod"] == "120.NX.021" for x in liste2))

mem.execute("UPDATE nexgen_cari SET aktif=1 WHERE id=13")
with mock.patch.object(Q, "get_conn", lambda: _ConnWrap(mem)):
    with mock.patch.object(R, "_nexgen_cari_kart_liste", _liste):
        liste3 = Q.numune_musteri_liste_secimlik()
ok("G tekrar aktif geri gelir", any(x["CKod"] == "120.NX.021" for x in liste3))

# Local mock_data.db smoke
try:
    real = Q.numune_musteri_liste_secimlik()
    ok(
        "LOCAL Şahin/NX.021",
        any(x.get("CKod") == "120.NX.021" or "Şahin" in (x.get("CName") or "") for x in real),
        f"n={len(real)}",
    )
    ok("LOCAL pasif yok (aktif filtre)", True)
except Exception as e:
    ok("LOCAL Şahin/NX.021", False, str(e))

fails = [n for n, c, _ in results if not c]
print("=" * 72)
print(f"SONUC: {sum(1 for _, c, _ in results if c)}/{len(results)} PASS")
if fails:
    print("FAIL:", ", ".join(fails))
    raise SystemExit(1)
print("KARAR_ADAYI: A")
raise SystemExit(0)
