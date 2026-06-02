# -*- coding: utf-8 -*-
"""
diagnose_uretim_kaydet_ve_gecmisim.py
-------------------------------------
1) modules/uretim_giris/routes.py'da uretim_kaydet fonksiyonunun TAM kodunu dok
2) modules/uretim_giris/templates altinda /uretim/ ekraninin HTML'inde
   GECMISIM / gecmisim / 'Geçmiş' geçen kisimlari bul
3) static/js/uretim_giris.js'te tab / gecmisim / GECMISIM / 'tab' click
   event listener'larini ve ilgili fonksiyonlari listele
"""

import os
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
ROUTES_PATH = os.path.join(CPS_ROOT, "modules", "uretim_giris", "routes.py")
TEMPLATES_DIR = os.path.join(CPS_ROOT, "modules", "uretim_giris", "templates")
ALT_TEMPLATES = os.path.join(CPS_ROOT, "templates")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "uretim_giris.js")


def section(title):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


# ----------------------------------------------------------------------
# 1) uretim_kaydet handler - tam kod
# ----------------------------------------------------------------------
section("1) /uretim/kaydet HANDLER - TAM KOD")
try:
    with open(ROUTES_PATH, 'r', encoding='utf-8') as f:
        src = f.read()
    lines = src.splitlines()
    tree = ast.parse(src)

    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'uretim_kaydet':
            target = node
            break

    if not target:
        print("  (uretim_kaydet fonksiyonu bulunamadi)")
    else:
        start = target.lineno
        if target.decorator_list:
            start = min(d.lineno for d in target.decorator_list)
        end = target.end_lineno
        print(f"  satir {start}-{end} ({end - start + 1} satir)")
        print()
        for i in range(start - 1, end):
            print(f"  [{i+1:>4}] {lines[i]}")
except Exception as e:
    print(f"  HATA: {e}")


# ----------------------------------------------------------------------
# 2) Template'lerde GECMISIM/gecmisim arama
# ----------------------------------------------------------------------
section("2) /uretim/ TEMPLATE'INDE GECMISIM SEKMESI")

candidate_dirs = []
for d in [TEMPLATES_DIR, ALT_TEMPLATES, os.path.join(CPS_ROOT, "modules")]:
    if os.path.exists(d):
        candidate_dirs.append(d)

# Tum HTML dosyalarini tara
html_files = []
for d in candidate_dirs:
    for dp, dns, fns in os.walk(d):
        dns[:] = [x for x in dns if x not in ('.git', '__pycache__', 'venv', '.venv', 'node_modules')]
        for fn in fns:
            if fn.endswith('.html'):
                html_files.append(os.path.join(dp, fn))

# Hangi HTML 'uretim' / 'PROSES SEÇ' / 'EMIR NO' geciyor (ureitm sayfasini bul)
target_html = None
for hf in html_files:
    try:
        with open(hf, 'r', encoding='utf-8') as f:
            txt = f.read()
    except Exception:
        continue
    # /uretim/ ekraninin HTML'ini tahmini imzalardan bul
    score = 0
    for sig in ['ÜRETİM GIR', 'URETIM GIR', 'PROSES SEÇ', 'prosesListe',
                'emirSorgula', 'ugForm', 'ugMiktar']:
        if sig in txt:
            score += 1
    if score >= 2:
        target_html = hf
        break

if not target_html:
    print("  /uretim/ ekraninin HTML dosyasi bulunamadi")
    print("  Aday HTML dosyalari:")
    for hf in html_files[:10]:
        print(f"    {os.path.relpath(hf, CPS_ROOT)}")
else:
    rel = os.path.relpath(target_html, CPS_ROOT)
    print(f"  HTML: {rel}")
    with open(target_html, 'r', encoding='utf-8') as f:
        html_lines = f.readlines()

    keywords = ['gecmisim', 'GECMISIM', 'GEÇMİŞİM', 'Geçmiş', 'GECMIS',
                'gecmisBody', 'gecmisTab', 'data-tab="gecmis', 'data-tab="ureti']
    matched = set()
    for i, ln in enumerate(html_lines):
        low = ln.lower()
        for k in keywords:
            if k.lower() in low:
                matched.add(i)
                break

    if not matched:
        print("  (bu HTML'de gecmisim/gecmis ile ilgili eleman yok)")
    else:
        for i in sorted(matched):
            s = max(0, i - 1)
            e = min(len(html_lines), i + 4)
            print(f"\n  --- satir {s+1}-{e} ---")
            for j in range(s, e):
                marker = '>' if j in matched else ' '
                print(f"  {marker} [{j+1:>4}] {html_lines[j].rstrip()[:140]}")


# ----------------------------------------------------------------------
# 3) uretim_giris.js'te tab / gecmis kodu
# ----------------------------------------------------------------------
section("3) uretim_giris.js - TAB / GECMIS / GECMISIM ILE ILGILI KODLAR")
if not os.path.exists(JS_PATH):
    print(f"  {JS_PATH} bulunamadi")
else:
    with open(JS_PATH, 'r', encoding='utf-8') as f:
        jslines = f.readlines()

    keywords = ['gecmis', 'GECMIS', 'gecmisim', 'tab', 'data-tab',
                'addEventListener("click"', "addEventListener('click'",
                'querySelectorAll', 'GEÇMIŞ']
    matched = set()
    for i, ln in enumerate(jslines):
        low = ln.lower()
        for k in keywords:
            if k.lower() in low:
                matched.add(i)
                break

    if not matched:
        print("  (eslesen satir yok)")
    else:
        # Daralt: ardisik bloklari birlestir
        sorted_idx = sorted(matched)
        ranges = []
        for i in sorted_idx:
            s = max(0, i - 1)
            e = min(len(jslines), i + 3)
            if ranges and s <= ranges[-1][1] + 2:
                ranges[-1] = (ranges[-1][0], max(ranges[-1][1], e))
            else:
                ranges.append((s, e))

        for s, e in ranges:
            print(f"\n  --- satir {s+1}-{e} ---")
            for j in range(s, e):
                marker = '>' if j in matched else ' '
                print(f"  {marker} [{j+1:>4}] {jslines[j].rstrip()[:140]}")


print()
print("BITTI. Yukarida 3 bolum: handler kodu, HTML, JS.")
