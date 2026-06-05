# -*- coding: utf-8 -*-
"""
diagnose_hedef_onaylar.py
-------------------------
1) mock_data.db.uretim_kayit semasi + 2 ornek kayit
2) cps_dev altinda 'hedef' Blueprint'inin tanimli oldugu dosyayi bul,
   icindeki Blueprint adi + tum route tanimlarini listele
3) static/js/hedef.js icindeki ONAYLAR / fetch / api / render kisimlari
"""

import os
import sys
import sqlite3
import ast

CPS_ROOT = r"C:\cps_dev"
DB_PATH = os.path.join(CPS_ROOT, "mock_data.db")
HEDEF_JS = os.path.join(CPS_ROOT, "static", "js", "hedef.js")


def section(title):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


# ------------------------------------------------------------------
# 1) uretim_kayit semasi
# ------------------------------------------------------------------
section("1) uretim_kayit TABLOSU - SEMA")
try:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(uretim_kayit)")
    cols = cur.fetchall()
    if not cols:
        print("  (tablo bos veya yok)")
    for c in cols:
        # (cid, name, type, notnull, default, pk)
        nn = "NOT NULL" if c[3] else "        "
        dflt = f"default={c[4]!r}" if c[4] is not None else ""
        pk = "  [PK]" if c[5] else ""
        print(f"  [{c[0]:>2}] {c[1]:<25} {c[2]:<10} {nn} {dflt}{pk}")

    section("   uretim_kayit - SON 2 KAYIT")
    cur.execute("SELECT * FROM uretim_kayit ORDER BY id DESC LIMIT 2")
    rows = cur.fetchall()
    col_names = [d[0] for d in cur.description]
    if not rows:
        print("  (kayit yok)")
    for r in rows:
        print()
        for name, val in zip(col_names, r):
            print(f"    {name:<25} = {val!r}")
    conn.close()
except Exception as e:
    print(f"  HATA: {e}")


# ------------------------------------------------------------------
# 2) hedef Blueprint dosyasi
# ------------------------------------------------------------------
section("2) HEDEF BLUEPRINT - DOSYA + ROUTE TANIMLARI")

hedef_bp_files = []
for dirpath, dirnames, filenames in os.walk(CPS_ROOT):
    dirnames[:] = [d for d in dirnames if d not in ('.git', '__pycache__', 'venv', '.venv', 'node_modules')]
    for fn in filenames:
        if not fn.endswith('.py'):
            continue
        full = os.path.join(dirpath, fn)
        try:
            with open(full, 'r', encoding='utf-8') as f:
                src = f.read()
        except Exception:
            continue
        try:
            tree = ast.parse(src)
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                fn_node = node.value.func
                fn_name = ''
                if isinstance(fn_node, ast.Name):
                    fn_name = fn_node.id
                elif isinstance(fn_node, ast.Attribute):
                    fn_name = fn_node.attr
                if fn_name == 'Blueprint':
                    args = []
                    for a in node.value.args:
                        try:
                            args.append(ast.unparse(a))
                        except Exception:
                            args.append('?')
                    if any('hedef' in a.lower() for a in args):
                        for t in node.targets:
                            if isinstance(t, ast.Name):
                                rel = os.path.relpath(full, CPS_ROOT)
                                hedef_bp_files.append((rel, t.id, args, src))

if not hedef_bp_files:
    print("  (hedef ile iliskili Blueprint bulunamadi)")
else:
    for rel, var_name, args, src in hedef_bp_files:
        print(f"\n  DOSYA: {rel}")
        print(f"  Blueprint nesnesi: {var_name} = Blueprint({', '.join(args)})")

        # Bu dosyadaki tum route'lari sirala
        try:
            tree = ast.parse(src)
        except Exception:
            continue
        print(f"  Route'lar:")
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for d in node.decorator_list:
                    if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == 'route':
                        try:
                            bp = ast.unparse(d.func.value)
                            path_str = ast.unparse(d.args[0]) if d.args else '?'
                            methods = '?'
                            for kw in d.keywords:
                                if kw.arg == 'methods':
                                    methods = ast.unparse(kw.value)
                            print(f"    [satir {node.lineno:>4}] @{bp}.route({path_str}, methods={methods}) -> def {node.name}")
                        except Exception:
                            pass


# ------------------------------------------------------------------
# 3) hedef.js icindeki onaylar/render kisimlari
# ------------------------------------------------------------------
section("3) hedef.js ICINDEKI ONAYLAR / FETCH / RENDER KISIMLARI")
if not os.path.exists(HEDEF_JS):
    print(f"  HATA: {HEDEF_JS} bulunamadi")
else:
    with open(HEDEF_JS, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    keywords = ['onaylar', 'onayla', 'reddet', 'gecmis', 'geçmiş', 'Yukleniyor',
                'Yükleniyor', 'fetch(', 'api/v2', '/hedef/', 'render', 'tabloOna']
    matched_lines = set()
    for i, line in enumerate(lines):
        low = line.lower()
        for k in keywords:
            if k.lower() in low:
                matched_lines.add(i)
                break

    if not matched_lines:
        print("  (eslesen satir yok)")
    else:
        # Satirlari context ile goster (her eslesmenin etrafinda 2 satir)
        shown = set()
        ranges = []
        for i in sorted(matched_lines):
            start = max(0, i - 1)
            end = min(len(lines), i + 3)
            ranges.append((start, end))

        # Birlesik araliklari yazdir
        merged = []
        for s, e in ranges:
            if merged and s <= merged[-1][1] + 2:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))

        for s, e in merged:
            print(f"\n  --- satir {s+1}-{e} ---")
            for i in range(s, e):
                marker = ">" if i in matched_lines else " "
                print(f"  {marker} [{i+1:>4}] {lines[i].rstrip()[:140]}")


print()
print("BITTI. Yukaridaki tum ciktiyi (3 bolum) yapistir.")
