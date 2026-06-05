# -*- coding: utf-8 -*-
"""
patch_uretim_prosesler_v2.py
----------------------------
routes.py icinde:
  - decorator string'inde '/uretim/emir' VE 'prosesler' gecen bir route varsa,
    o fonksiyonu (adi ne olursa olsun) yeni icerikle degistirir.
  - Yoksa, dosya sonuna yeni rotayi ekler.
  - Once 'uretim_giris_bp' Blueprint'inin tanimli oldugunu dogrular.
  - Yedek alir + yazmadan once syntax dogrulamasi yapar.

Calistirma:
    cd C:\\cps_dev
    py patch_uretim_prosesler_v2.py
"""

import ast
import os
import shutil
import datetime
import sys

ROUTES_PATH = r"C:\cps_dev\modules\uretim_giris\routes.py"
BP_NAME = "uretim_giris_bp"

NEW_FUNC = '''@uretim_giris_bp.route('/uretim/emir/<emir_no>/prosesler', methods=['GET'])
def uretim_emir_prosesler(emir_no):
    """Emir'in alt proseslerini mock_data.db.emir_alt_proses'ten dondur."""
    import sqlite3
    import os as _os
    from flask import jsonify, current_app

    candidates = [
        _os.path.join(current_app.root_path, 'mock_data.db'),
        _os.path.join(_os.path.dirname(current_app.root_path), 'mock_data.db'),
        _os.path.join(_os.getcwd(), 'mock_data.db'),
        r'C:\\cps_dev\\mock_data.db',
    ]
    db_path = next((p for p in candidates if _os.path.exists(p)), candidates[0])

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, emir_no, proses_adi, hedef_adet, aktif, siralama, kaynak
            FROM emir_alt_proses
            WHERE emir_no = ? AND aktif = 1
            ORDER BY siralama ASC, id ASC
            """,
            (str(emir_no),),
        )
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            d['proses_id'] = d['id']
            d['sira'] = d['siralama']
            rows.append(d)
        conn.close()

        return jsonify({
            'success': True,
            'emir_no': emir_no,
            'prosesler': rows,
            'count': len(rows),
            'kaynak_db': db_path,
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'hata': str(e),
            'prosesler': [],
            'kaynak_db': db_path,
        }), 500
'''


def get_decorator_strings(func_node):
    """Bir fonksiyonun decorator'larindaki tum string sabitlerini topla."""
    out = []
    for d in func_node.decorator_list:
        if isinstance(d, ast.Call):
            for a in d.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    out.append(a.value)
            for kw in d.keywords:
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    out.append(kw.value.value)
    return out


def main():
    if not os.path.exists(ROUTES_PATH):
        print(f"[HATA] routes.py bulunamadi: {ROUTES_PATH}")
        sys.exit(1)

    with open(ROUTES_PATH, 'r', encoding='utf-8') as f:
        src = f.read()
    lines = src.splitlines(keepends=True)

    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        print(f"[HATA] routes.py parse edilemedi: {e}")
        sys.exit(1)

    # 1) Blueprint tanimli mi?
    bp_found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == BP_NAME:
                    bp_found = True
                    break
        if bp_found:
            break

    if not bp_found:
        print(f"[UYARI] '{BP_NAME}' adli Blueprint routes.py'de bulunamadi.")
        print("        Yine de devam edilecek (belki import ediliyordur).")

    # 2) /uretim/emir + prosesler iceren bir route var mi?
    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            decstrs = get_decorator_strings(node)
            if any(('/uretim/emir' in s and 'prosesler' in s) for s in decstrs):
                target = node
                break

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = ROUTES_PATH + f'.bak_{ts}'
    shutil.copy2(ROUTES_PATH, backup_path)
    print(f"[OK] Yedek alindi: {backup_path}")

    if target is not None:
        start_line = target.lineno
        if target.decorator_list:
            start_line = min(d.lineno for d in target.decorator_list)
        end_line = target.end_lineno

        new_block = NEW_FUNC if NEW_FUNC.endswith('\n') else NEW_FUNC + '\n'
        new_lines = lines[:start_line - 1] + [new_block] + lines[end_line:]
        new_src = ''.join(new_lines)

        try:
            ast.parse(new_src)
        except SyntaxError as e:
            print(f"[HATA] Yeni icerik parse edilemiyor, yazilmadi: {e}")
            sys.exit(3)

        with open(ROUTES_PATH, 'w', encoding='utf-8') as f:
            f.write(new_src)

        print(f"[OK] Mevcut fonksiyon '{target.name}' degistirildi. Satirlar: {start_line}-{end_line}")
    else:
        # Dosya sonuna ekle
        suffix = '\n\n# --- Eklendi: emir alt proses listesi (mock_data.db kaynak) ---\n'
        new_block = suffix + NEW_FUNC
        if not src.endswith('\n'):
            new_block = '\n' + new_block

        new_src = src + new_block

        try:
            ast.parse(new_src)
        except SyntaxError as e:
            print(f"[HATA] Yeni icerik parse edilemiyor, yazilmadi: {e}")
            sys.exit(3)

        with open(ROUTES_PATH, 'w', encoding='utf-8') as f:
            f.write(new_src)

        print("[OK] Eslesen route bulunamadi; yeni fonksiyon dosya sonuna eklendi.")

    # Dogrulama: yazilan dosyayi tekrar parse et ve route'u tara
    with open(ROUTES_PATH, 'r', encoding='utf-8') as f:
        verify_src = f.read()
    verify_tree = ast.parse(verify_src)
    found_after = False
    for node in ast.walk(verify_tree):
        if isinstance(node, ast.FunctionDef):
            if any(('/uretim/emir' in s and 'prosesler' in s)
                   for s in get_decorator_strings(node)):
                found_after = True
                print(f"[OK] Dogrulama: route fonksiyonu '{node.name}' satir {node.lineno}.")
                break

    if not found_after:
        print("[UYARI] Dogrulama: route hala bulunamadi. Manuel inceleme gerek.")
        sys.exit(4)

    print()
    print("SONRAKI ADIMLAR:")
    print("  1) CPS sunucusunu yeniden baslat")
    print("  2) PowerShell'de:")
    print("     curl.exe http://127.0.0.1:5057/uretim/emir/110626/prosesler")
    print("     (ya da: Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5057/uretim/emir/110626/prosesler | Select -Expand Content)")
    print("  3) Beklenen: 6 proses (Capak Alma, Tampon Baski, Rivet Takma, Atki, Temizleme, Paketleme)")


if __name__ == '__main__':
    main()
