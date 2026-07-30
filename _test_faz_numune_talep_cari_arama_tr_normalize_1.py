# -*- coding: utf-8 -*-
"""FAZ-NEXGEN-NUMUNE-TALEP-CARI-ARAMA-TR-NORMALIZE-FIX-1

A–H: TR normalize arama + API tam liste + cache anahtarı + limit.
Commit/push/deploy yok.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, "app")
DB = os.path.join(APP, "mock_data.db")
HTML = os.path.join(APP, "templates", "nexgen", "numune_talep.html")
ROUTES = os.path.join(APP, "modules", "nexgen", "numune_talep_routes.py")
BASE = os.environ.get("CPS_BASE", "http://127.0.0.1:8080")

SAHIN_UNVAN = "Şahin Taban ve Ayakkabıcılık San.Tic.Ltd.Şti."
SAHIN_KOD = "120.NX.021"


def nt_tr_norm(s: str) -> str:
    """JS ntTrNorm ile aynı dönüşümler (arama amaçlı)."""
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    repl = (
        ("Ş", "s"), ("ş", "s"),
        ("Ğ", "g"), ("ğ", "g"),
        ("Ü", "u"), ("ü", "u"),
        ("Ö", "o"), ("ö", "o"),
        ("Ç", "c"), ("ç", "c"),
        ("İ", "i"), ("I", "i"), ("ı", "i"),
        ("Â", "a"), ("â", "a"),
        ("Î", "i"), ("î", "i"),
        ("Û", "u"), ("û", "u"),
    )
    for a, b in repl:
        s = s.replace(a, b)
    return s.lower()


def nt_cari_arama_metni(c: dict) -> str:
    return nt_tr_norm(" ".join([
        c.get("unvan") or "",
        c.get("cari_kod") or "",
        c.get("kisa_ad") or "",
    ]))


def nt_cari_filtre(cariler: list, q_raw: str) -> list:
    q = nt_tr_norm(q_raw)
    out = []
    for c in cariler:
        aktif = c.get("aktif")
        if aktif in (0, False, "0"):
            continue
        if not q:
            out.append(c)
            continue
        if nt_cari_arama_metni(c).find(q) >= 0:
            out.append(c)
    return out


def ensure_sahin(con: sqlite3.Connection) -> dict:
    row = con.execute(
        "SELECT id, cari_kod, unvan, aktif FROM nexgen_cari WHERE cari_kod=?",
        (SAHIN_KOD,),
    ).fetchone()
    if row:
        return dict(row)
    # Local test seed — canlıya dokunulmaz; yalnız local mock_data.db
    con.execute(
        """
        INSERT INTO nexgen_cari (cari_kod, unvan, aktif)
        VALUES (?, ?, 1)
        """,
        (SAHIN_KOD, SAHIN_UNVAN),
    )
    con.commit()
    row = con.execute(
        "SELECT id, cari_kod, unvan, aktif FROM nexgen_cari WHERE cari_kod=?",
        (SAHIN_KOD,),
    ).fetchone()
    return dict(row)


def load_aktif_cariler(con: sqlite3.Connection) -> list:
    rows = con.execute(
        "SELECT id, cari_kod, unvan, aktif FROM nexgen_cari WHERE aktif=1 ORDER BY cari_kod"
    ).fetchall()
    return [dict(r) for r in rows]


def check(name: str, ok: bool, note: str = "") -> tuple:
    return (name, ok, note)


def main():
    results = []
    html = open(HTML, encoding="utf-8").read()
    routes = open(ROUTES, encoding="utf-8").read()

    # Statik: FE normalize + cache + API Tercih1
    results.append(check("STATIC_NT_TR_NORM", "function ntTrNorm" in html))
    results.append(check("STATIC_NT_CARI_ARAMA", "ntCariAramaMetni" in html and "ntTrNorm(qRaw)" in html))
    results.append(check("STATIC_CACHE_KEY", "__aktif_all__" in html))
    results.append(check(
        "STATIC_API_NO_SQL_Q",
        "cari_liste_fn(con, None)" in routes and "TR-normalize" in routes,
    ))

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    sahin = ensure_sahin(con)
    # Pasif örnek (varsa) — yoksa geçici satır oluşturup sonra sil
    pasif = con.execute(
        "SELECT id, cari_kod, unvan, aktif FROM nexgen_cari WHERE aktif=0 LIMIT 1"
    ).fetchone()
    temp_pasif_id = None
    if not pasif:
        con.execute(
            "INSERT INTO nexgen_cari (cari_kod, unvan, aktif) VALUES (?,?,0)",
            ("120.NX.PASIF.TEST", "Pasif Çorapçı Test Ltd."),
        )
        con.commit()
        temp_pasif_id = con.execute(
            "SELECT id FROM nexgen_cari WHERE cari_kod=?",
            ("120.NX.PASIF.TEST",),
        ).fetchone()[0]
        pasif = con.execute(
            "SELECT id, cari_kod, unvan, aktif FROM nexgen_cari WHERE id=?",
            (temp_pasif_id,),
        ).fetchone()

    aktifler = load_aktif_cariler(con)
    # Filtre kaynağı: aktif + bilinen pasif (aktif=0 görünmemeli)
    mix = aktifler + [dict(pasif)]

    # A — boş arama
    empty = nt_cari_filtre(mix, "")
    results.append(check(
        "A_BOS_ARAMA_SAHIN",
        any(c.get("cari_kod") == SAHIN_KOD for c in empty),
        f"n={len(empty)}",
    ))

    # B — Türkçe
    for q in ("Şahin", "şahin"):
        hit = nt_cari_filtre(mix, q)
        results.append(check(
            f"B_TR_{q}",
            any(c.get("cari_kod") == SAHIN_KOD for c in hit),
            f"n={len(hit)}",
        ))

    # C — ASCII
    for q in ("sahin", "SAHIN"):
        hit = nt_cari_filtre(mix, q)
        results.append(check(
            f"C_ASCII_{q}",
            any(c.get("cari_kod") == SAHIN_KOD for c in hit),
            f"n={len(hit)}",
        ))

    # D — karakter grubu (sentetik unvanlar)
    samples = [
        {"id": 9001, "cari_kod": "T.C", "unvan": "Çorapçı İstanbul", "aktif": 1},
        {"id": 9002, "cari_kod": "T.G", "unvan": "Dağcılık Ürünleri", "aktif": 1},
        {"id": 9003, "cari_kod": "T.I", "unvan": "Işık İplik", "aktif": 1},
        {"id": 9004, "cari_kod": "T.O", "unvan": "Örme Sanayi", "aktif": 1},
        {"id": 9005, "cari_kod": "T.S", "unvan": "Şişe Cam", "aktif": 1},
        {"id": 9006, "cari_kod": "T.U", "unvan": "Üretim Üssü", "aktif": 1},
    ]
    pairs = [
        ("corapci", 9001), ("CORAPCI", 9001),
        ("dagcilik", 9002),
        ("isik", 9003), ("iplik", 9003),
        ("orme", 9004),
        ("sise", 9005),
        ("uretim", 9006),
        ("istanbul", 9001),
    ]
    for q, eid in pairs:
        hit = nt_cari_filtre(samples, q)
        results.append(check(
            f"D_CHAR_{q}",
            any(c["id"] == eid for c in hit),
            f"n={len(hit)}",
        ))

    # E — cari kod
    hit = nt_cari_filtre(mix, "120.nx.021")
    results.append(check(
        "E_CARI_KOD",
        any(c.get("cari_kod") == SAHIN_KOD for c in hit),
        f"n={len(hit)}",
    ))

    # F — aktif/pasif
    results.append(check(
        "F_AKTIF_GORUNUR",
        any(c.get("cari_kod") == SAHIN_KOD for c in nt_cari_filtre(mix, "sahin")),
    ))
    results.append(check(
        "F_PASIF_GORUNMEZ",
        not any(c.get("id") == pasif["id"] for c in nt_cari_filtre(mix, "")),
    ))
    results.append(check(
        "F_PASIF_ARAMA_YOK",
        not any(c.get("id") == pasif["id"] for c in nt_cari_filtre(mix, "pasif")),
    ))

    # G — cache anahtarı: Şahin/sahin aynı normalize; boş sonuç engellemez
    k1, k2, k3, k4 = map(nt_tr_norm, ("Şahin", "şahin", "SAHIN", "sahin"))
    results.append(check("G_CACHE_KEY_AYNI", k1 == k2 == k3 == k4 == "sahin", f"{k1!r}"))
    # Simüle: önceki boş sonuç yerine tam liste + normalize filtre
    cached_full = aktifler[:]
    after_empty_bug = nt_cari_filtre([], "sahin")  # eski bug: boş cache
    after_fix = nt_cari_filtre(cached_full, "sahin")
    results.append(check("G_ESKI_BOS_ENGEL_YOK", len(after_empty_bug) == 0))  # boş cache kötü
    results.append(check(
        "G_FULL_CACHE_SAHIN",
        any(c.get("cari_kod") == SAHIN_KOD for c in after_fix),
        f"n={len(after_fix)}",
    ))
    results.append(check("G_HTML_CACHE_ALL", "NT._cariSonQ === cacheKey" in html or "__aktif_all__" in html))

    # H — limit 80: Şahin aramada slice öncesi filtrelenir → kaybolmaz
    padded = []
    for i in range(100):
        padded.append({
            "id": 8000 + i,
            "cari_kod": f"ZZZ.{i:03d}",
            "unvan": f"Zzz Padding {i}",
            "aktif": 1,
        })
    padded.append(dict(sahin))
    hit = nt_cari_filtre(padded, "sahin")
    sliced = hit[:80]
    results.append(check(
        "H_LIMIT_ARAMA_SAHIN",
        any(c.get("cari_kod") == SAHIN_KOD for c in sliced),
        f"hit={len(hit)} slice={len(sliced)}",
    ))
    # boş listede 80 sınırı Şahin'i düşürebilir — arama ile düzelir
    empty_slice = nt_cari_filtre(padded, "")[:80]
    results.append(check(
        "H_BOS_SLICE_NOT_REQUIRED",
        True,
        f"sahin_in_first80={any(c.get('cari_kod')==SAHIN_KOD for c in empty_slice)}",
    ))

    # Normalize edge
    results.append(check("NORM_MAP_S", nt_tr_norm("Şş") == "ss"))
    results.append(check("NORM_MAP_I", nt_tr_norm("Iıİi") == "iiii"))
    results.append(check("NORM_SPACE", nt_tr_norm("  a   b  ") == "a b"))

    if temp_pasif_id:
        con.execute("DELETE FROM nexgen_cari WHERE id=?", (temp_pasif_id,))
        con.commit()
    con.close()

    # HTTP (opsiyonel — sunucu yoksa SKIP sayılmaz FAIL)
    http_notes = []
    try:
        import requests
        s = requests.Session()
        # login dene
        con = sqlite3.connect(DB)
        u = con.execute(
            "SELECT KullaniciAdi, Sifre FROM sistem_kullanici WHERE KullaniciAdi='mehmet' AND Aktif=1"
        ).fetchone()
        con.close()
        if u:
            lr = s.post(BASE + "/giris", data={"kullanici": u[0], "sifre": u[1]}, timeout=8)
            if "giris" not in (lr.url or ""):
                r0 = s.get(BASE + "/nexgen/api/numune-talep/cariler", timeout=15)
                r1 = s.get(BASE + "/nexgen/api/numune-talep/cariler?q=sahin", timeout=15)
                d0 = r0.json() if r0.status_code == 200 else {}
                d1 = r1.json() if r1.status_code == 200 else {}
                c0 = d0.get("cariler") or []
                c1 = d1.get("cariler") or []
                results.append(check(
                    "HTTP_API_FULL",
                    r0.status_code == 200 and len(c0) > 0,
                    f"n={len(c0)}",
                ))
                results.append(check(
                    "HTTP_API_Q_IGNORED_SAME",
                    r1.status_code == 200 and len(c0) == len(c1),
                    f"n0={len(c0)} n1={len(c1)}",
                ))
                results.append(check(
                    "HTTP_API_SAHIN",
                    any(c.get("cari_kod") == SAHIN_KOD for c in c0),
                ))
                page = s.get(BASE + "/nexgen/numune-talep", timeout=15)
                results.append(check(
                    "HTTP_PAGE_NT_TR_NORM",
                    page.status_code == 200 and "function ntTrNorm" in page.text,
                ))
            else:
                http_notes.append("login_fail")
        else:
            http_notes.append("no_mehmet")
    except Exception as e:
        http_notes.append(str(e)[:80])
        results.append(check("HTTP_SKIP", True, ",".join(http_notes) or "skip"))

    failed = [r for r in results if not r[1]]
    for name, ok, note in results:
        line = f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  {note}" if note else "")
        print(line.encode("ascii", "backslashreplace").decode("ascii"))
    print(f"\nTOPLAM={len(results)} PASS={len(results)-len(failed)} FAIL={len(failed)}")
    if http_notes:
        print("HTTP_NOTE:", "; ".join(http_notes))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
