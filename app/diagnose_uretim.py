# -*- coding: utf-8 -*-
"""
diagnose_uretim.py
------------------
1) modules/uretim_giris/routes.py icindeki Blueprint tanimlarini ve route'lari listeler.
2) C:\\cps_dev altindaki tum .py dosyalarinda register_blueprint(...) cagrilarini bulur.
3) Blueprint nesnesinin url_prefix degerini de gosterir.

Calistirma:
    cd C:\\cps_dev
    py diagnose_uretim.py
"""

import ast
import os
import sys

CPS_ROOT = r"C:\cps_dev"
ROUTES_PATH = os.path.join(CPS_ROOT, "modules", "uretim_giris", "routes.py")


def unparse_safe(node):
    try:
        return ast.unparse(node)
    except Exception:
        return f"<{type(node).__name__}>"


def analyze_blueprints_in_file(path):
    """Bir dosyadaki Blueprint tanimlarini bul."""
    out = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        tree = ast.parse(src)
    except Exception as e:
        return out

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            fn = node.value.func
            fn_name = ''
            if isinstance(fn, ast.Name):
                fn_name = fn.id
            elif isinstance(fn, ast.Attribute):
                fn_name = fn.attr
            if fn_name == 'Blueprint':
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        args = [unparse_safe(a) for a in node.value.args]
                        kwargs = {kw.arg: unparse_safe(kw.value) for kw in node.value.keywords}
                        out.append({
                            'var': t.id,
                            'line': node.lineno,
                            'args': args,
                            'kwargs': kwargs,
                        })
    return out


def analyze_routes_in_file(path):
    """Bir dosyadaki @<bp>.route(...) decorator'larini bul."""
    out = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        tree = ast.parse(src)
    except Exception:
        return out

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == 'route':
                    bp = unparse_safe(d.func.value)
                    path_str = unparse_safe(d.args[0]) if d.args else '?'
                    methods = '?'
                    for kw in d.keywords:
                        if kw.arg == 'methods':
                            methods = unparse_safe(kw.value)
                    out.append({
                        'line': node.lineno,
                        'func': node.name,
                        'bp': bp,
                        'path': path_str,
                        'methods': methods,
                    })
    return out


def find_register_blueprint_calls(root):
    """root altindaki tum .py dosyalarinda register_blueprint(...) cagrilarini bul."""
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        # gereksiz klasorleri atla
        dirnames[:] = [d for d in dirnames if d not in ('.git', '__pycache__', 'venv', '.venv', 'node_modules')]
        for fn in filenames:
            if not fn.endswith('.py'):
                continue
            full = os.path.join(dirpath, fn)
            try:
                with open(full, 'r', encoding='utf-8') as f:
                    src = f.read()
                tree = ast.parse(src)
            except Exception:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'register_blueprint':
                    args = [unparse_safe(a) for a in node.args]
                    kwargs = {kw.arg: unparse_safe(kw.value) for kw in node.keywords}
                    hits.append({
                        'file': os.path.relpath(full, root),
                        'line': node.lineno,
                        'caller': unparse_safe(node.func.value),
                        'args': args,
                        'kwargs': kwargs,
                    })
    return hits


def main():
    print("=" * 70)
    print("1) routes.py BLUEPRINT TANIMLARI")
    print("=" * 70)
    bps = analyze_blueprints_in_file(ROUTES_PATH)
    if not bps:
        print("  (Bu dosyada Blueprint(...) tanimi yok)")
    for b in bps:
        prefix = b['kwargs'].get('url_prefix', '<yok>')
        print(f"  [satir {b['line']:>3}] {b['var']} = Blueprint({', '.join(b['args'])}, url_prefix={prefix})")

    print()
    print("=" * 70)
    print("2) routes.py ICINDEKI ROUTE TANIMLARI")
    print("=" * 70)
    rs = analyze_routes_in_file(ROUTES_PATH)
    if not rs:
        print("  (Hic @<bp>.route bulunamadi)")
    for r in rs:
        print(f"  [satir {r['line']:>3}] @{r['bp']}.route({r['path']}, methods={r['methods']}) -> def {r['func']}")

    print()
    print("=" * 70)
    print("3) cps_dev ICINDE TUM register_blueprint(...) CAGRILARI")
    print("=" * 70)
    regs = find_register_blueprint_calls(CPS_ROOT)
    if not regs:
        print("  (Hicbir register_blueprint cagrisi bulunamadi!)")
    for h in regs:
        prefix = h['kwargs'].get('url_prefix', '<yok>')
        args = ', '.join(h['args'])
        print(f"  {h['file']} [satir {h['line']:>3}] {h['caller']}.register_blueprint({args}, url_prefix={prefix})")

    print()
    print("=" * 70)
    print("4) ARAMA: 'uretim_giris_bp' kelimesi gecen dosyalar")
    print("=" * 70)
    for dirpath, dirnames, filenames in os.walk(CPS_ROOT):
        dirnames[:] = [d for d in dirnames if d not in ('.git', '__pycache__', 'venv', '.venv', 'node_modules')]
        for fn in filenames:
            if not fn.endswith('.py'):
                continue
            full = os.path.join(dirpath, fn)
            try:
                with open(full, 'r', encoding='utf-8') as f:
                    text = f.read()
            except Exception:
                continue
            if 'uretim_giris_bp' in text:
                # Satir numaralari
                lines = [(i + 1, line.strip()) for i, line in enumerate(text.splitlines()) if 'uretim_giris_bp' in line]
                rel = os.path.relpath(full, CPS_ROOT)
                print(f"  {rel}:")
                for ln, content in lines[:8]:
                    print(f"     [satir {ln:>3}] {content[:100]}")


if __name__ == '__main__':
    main()
