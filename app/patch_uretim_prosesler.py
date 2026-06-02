# -*- coding: utf-8 -*-
"""
patch_uretim_prosesler.py
-------------------------
C:\\cps_dev\\modules\\uretim_giris\\routes.py icindeki
uretim_emir_prosesler fonksiyonunu, AST kullanarak guvenli sekilde
yeniden yazar. Default 8 proses donen versiyondan,
mock_data.db.emir_alt_proses tablosundan okuyan versiyona gecirir.

Calistirma:
    cd C:\\cps_dev
    py patch_uretim_prosesler.py
"""

import ast
import os
import shutil
import datetime
import sys

ROUTES_PATH = r"C:\cps_dev\modules\uretim_giris\routes.py"
FUNC_NAME = "uretim_emir_prosesler"

NEW_FUNC = '''@uretim_giris_bp.route('/uretim/emir/<emir_no>/prosesler', methods=['GET'])
def uretim_emir_prosesler(emir_no):
    """Emir'in alt proseslerini mock_data.db.emir_alt_proses'ten dondur."""
    import sqlite3
    import os as _os
    from flask import jsonify, current_app

    # mock_data.db yolu: app root'ta, yoksa cwd'de ara
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
            # Frontend uyumu icin alias alanlar
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

    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == FUNC_NAME:
            target = node
            break

    if target is None:
        print(f"[HATA] '{FUNC_NAME}' fonksiyonu routes.py icinde bulunamadi.")
        print("Manuel ekleme gerek. Asagidaki kodu routes.py sonuna ekle:")
        print("-" * 60)
        print(NEW_FUNC)
        sys.exit(2)

    # Decorator'leri de kapsayan baslangic satiri
    start_line = target.lineno
    if target.decorator_list:
        start_line = min(d.lineno for d in target.decorator_list)
    end_line = target.end_lineno  # 1-indexed, inclusive

    # Backup
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = ROUTES_PATH + f'.bak_{ts}'
    shutil.copy2(ROUTES_PATH, backup_path)
    print(f"[OK] Yedek alindi: {backup_path}")

    # Replace
    new_block = NEW_FUNC
    if not new_block.endswith('\n'):
        new_block += '\n'

    # Eger end_line'dan sonra hemen bos satir yoksa, ekle
    new_lines = lines[:start_line - 1] + [new_block] + lines[end_line:]
    new_src = ''.join(new_lines)

    # Once dogrula: yeni icerik parse edilebiliyor mu?
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"[HATA] Yeni icerik parse edilemiyor, yazilmadi: {e}")
        print("Yedek bozulmadi, orijinal dosya korunuyor.")
        sys.exit(3)

    with open(ROUTES_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)

    print(f"[OK] {FUNC_NAME} guncellendi. Satirlar: {start_line}-{end_line}")
    print(f"[OK] Yeni dosya boyutu: {len(new_src)} bayt")
    print()
    print("SONRAKI ADIMLAR:")
    print("  1) CPS server'i yeniden baslat (Ctrl+C, sonra py app.py)")
    print("  2) Test et:")
    print("     PowerShell: Invoke-WebRequest http://127.0.0.1:5057/uretim/emir/110626/prosesler | Select -Expand Content")
    print("     Beklenen: 6 proses (Capak Alma, Tampon Baski, Rivet Takma, Atki, Temizleme, Paketleme)")


if __name__ == '__main__':
    main()
