# -*- coding: utf-8 -*-
"""
diagnose_plan.py
----------------
PLAN endpoint'i icin gerekli kesfi:
  1) Korgun korgun.py icindeki mevcut connection helper'i kullanarak
     Urt_Emir, Siparis_Har, Siparis_Kay tablolarinin CSV gibi ornek 1 satirini cek
  2) mock_data.db.uretim_kayit emir_no kolonunun tipi (integer mi text mi)
     ve farkli emir_no degerleri
  3) modules/hedef/templates icinde PLAN sekmesinin tablo body id'si
     ('planBody' mi yoksa baska mi)
  4) static/js/hedef.js icindeki PLAN ile ilgili kodu listele
"""

import os
import sys
import sqlite3
import ast

CPS_ROOT = r"C:\cps_dev"
DB_PATH = os.path.join(CPS_ROOT, "mock_data.db")
HEDEF_JS = os.path.join(CPS_ROOT, "static", "js", "hedef.js")
KORGUN_PY = os.path.join(CPS_ROOT, "modules", "common", "korgun.py")


def section(t):
    print()
    print("=" * 72)
    print(t)
    print("=" * 72)


# 1) KORGUN TEST - mevcut korgun.py helper'ini kullan
section("1) KORGUN MSSQL - SEMA ORNEKLERI")
try:
    sys.path.insert(0, CPS_ROOT)
    from modules.common import korgun as _kk
    print(f"  korgun helper'i yuklendi: {_kk.__file__}")

    # Korgun'a query sokmanin yolu nedir? Once kaynak kodu inceleyelim
    with open(KORGUN_PY, 'r', encoding='utf-8') as f:
        ksrc = f.read()

    # connection function'i bul
    print("\n  korgun.py icindeki public fonksiyonlar:")
    tree = ast.parse(ksrc)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and not node.name.startswith('_'):
            args = [a.arg for a in node.args.args]
            print(f"    def {node.name}({', '.join(args)})")

    # Manuel deneme - pytds direct
    print("\n  pytds ile direkt baglanti deneme:")
    try:
        import pytds
        # korgun.py'den config oku
        sys.path.insert(0, CPS_ROOT)
        from config import KORGUN_HOST, KORGUN_PORT, KORGUN_DB, KORGUN_USER, KORGUN_PASS
        conn = pytds.connect(
            server=KORGUN_HOST, port=KORGUN_PORT,
            database=KORGUN_DB, user=KORGUN_USER, password=KORGUN_PASS,
            login_timeout=10
        )
        cur = conn.cursor()

        # 1A) Urt_Emir orneik 1 satir
        print("\n  --- Urt_Emir TOP 1 ---")
        cur.execute("SELECT TOP 1 * FROM Urt_Emir ORDER BY EmirNo DESC")
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        if row:
            for c, v in zip(cols, row):
                vs = repr(v)
                if len(vs) > 100:
                    vs = vs[:100] + '...'
                print(f"    {c:<25} = {vs}")
        else:
            print("    (kayit yok)")

        # 1B) En son 5 emir no'su
        print("\n  --- En son 5 emir (EmirNo, ModelKod, Tip) ---")
        cur.execute("SELECT TOP 5 EmirNo, ModelKod, Tip FROM Urt_Emir ORDER BY EmirNo DESC")
        for r in cur.fetchall():
            print(f"    {r}")

        # 1C) Siparis_Har emirden hedef bulma
        print("\n  --- Siparis_Har TOP 1 (kolonlar) ---")
        cur.execute("SELECT TOP 1 * FROM Siparis_Har")
        cols = [d[0] for d in cur.description]
        print(f"    Kolonlar: {cols[:10]}...")
        row = cur.fetchone()
        if row:
            for c, v in zip(cols[:15], row[:15]):
                vs = repr(v)[:60]
                print(f"    {c:<25} = {vs}")

        # 1D) Mevcut korgun.py'deki get_emir_ozet ornek
        print("\n  --- get_emir_ozet(110626) sonucu ---")
        try:
            ozet = _kk.get_emir_ozet(110626)
            for k, v in ozet.items():
                print(f"    {k:<20} = {v!r}")
        except Exception as e:
            print(f"    HATA: {e}")

        conn.close()
    except Exception as e:
        print(f"  pytds baglanti HATASI: {type(e).__name__}: {e}")
except Exception as e:
    print(f"  korgun.py yuklenirken hata: {type(e).__name__}: {e}")


# 2) uretim_kayit - emir_no tipi
section("2) mock_data.db.uretim_kayit - emir_no DEGER TIPI")
try:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(uretim_kayit)")
    for c in cur.fetchall():
        if c[1] == 'emir_no':
            print(f"  Sema tip: {c[2]}")

    cur.execute("""
        SELECT emir_no, COUNT(*) as adet,
               SUM(CASE WHEN onay_durum='onaylandi' THEN miktar ELSE 0 END) as onayli_miktar,
               SUM(CASE WHEN onay_durum='bekliyor' THEN miktar ELSE 0 END) as bekleyen_miktar
          FROM uretim_kayit
         GROUP BY emir_no
         ORDER BY emir_no DESC
    """)
    rows = cur.fetchall()
    print(f"\n  emir_no bazinda gruplu (toplam {len(rows)} farkli emir):")
    for r in rows:
        print(f"    emir_no={r[0]!r} (tip={type(r[0]).__name__})  toplam_kayit={r[1]}  onayli={r[2]}  bekleyen={r[3]}")
    conn.close()
except Exception as e:
    print(f"  HATA: {e}")


# 3) hedef template - PLAN tablo body id
section("3) /hedef/ PLAN SEKMESI - HTML")
hedef_templates = []
for d in [os.path.join(CPS_ROOT, "modules", "hedef", "templates"),
          os.path.join(CPS_ROOT, "templates")]:
    if os.path.exists(d):
        for dp, dns, fns in os.walk(d):
            dns[:] = [x for x in dns if x not in ('__pycache__',)]
            for fn in fns:
                if fn.endswith('.html'):
                    hedef_templates.append(os.path.join(dp, fn))

target = None
for hf in hedef_templates:
    try:
        with open(hf, 'r', encoding='utf-8') as f:
            txt = f.read()
    except Exception:
        continue
    score = 0
    for sig in ['planBody', 'data-tab="plan"', 'PLAN', 'Hedef Yönetimi', 'h-tab', 'onayBody']:
        if sig in txt:
            score += 1
    if score >= 3:
        target = hf
        break

if not target:
    print("  /hedef/ template'i bulunamadi. Aday dosyalar:")
    for hf in hedef_templates[:8]:
        print(f"    {os.path.relpath(hf, CPS_ROOT)}")
else:
    print(f"  HTML: {os.path.relpath(target, CPS_ROOT)}")
    with open(target, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    keywords = ['planBody', 'data-tab="plan', 'PLAN', '<th', 'plan-tab',
                'h-tab', 'tabloBas', 'tablePlan']
    matched = set()
    for i, ln in enumerate(lines):
        for k in keywords:
            if k in ln:
                matched.add(i)
                break

    if not matched:
        print("  (eslesen yok)")
    else:
        sorted_idx = sorted(matched)
        ranges = []
        for i in sorted_idx:
            s = max(0, i - 1)
            e = min(len(lines), i + 3)
            if ranges and s <= ranges[-1][1] + 2:
                ranges[-1] = (ranges[-1][0], max(ranges[-1][1], e))
            else:
                ranges.append((s, e))
        for s, e in ranges[:15]:
            print(f"\n  --- satir {s+1}-{e} ---")
            for j in range(s, e):
                m = '>' if j in matched else ' '
                print(f"  {m} [{j+1:>4}] {lines[j].rstrip()[:140]}")


# 4) hedef.js PLAN ile ilgili kodu
section("4) hedef.js - PLAN FETCH/RENDER")
if os.path.exists(HEDEF_JS):
    with open(HEDEF_JS, 'r', encoding='utf-8') as f:
        jslines = f.readlines()
    keywords = ['plan', 'PLAN', 'planBody', 'planYukle', 'renderPlan',
                '/api/v2/hedef/liste', '_planYuklendi']
    matched = set()
    for i, ln in enumerate(jslines):
        for k in keywords:
            if k in ln:
                matched.add(i)
                break
    sorted_idx = sorted(matched)
    ranges = []
    for i in sorted_idx:
        s = max(0, i - 1)
        e = min(len(jslines), i + 3)
        if ranges and s <= ranges[-1][1] + 2:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], e))
        else:
            ranges.append((s, e))
    for s, e in ranges[:12]:
        print(f"\n  --- satir {s+1}-{e} ---")
        for j in range(s, e):
            m = '>' if j in matched else ' '
            print(f"  {m} [{j+1:>4}] {jslines[j].rstrip()[:140]}")

print()
print("BITTI. 4 bolum yukarida.")
