# -*- coding: utf-8 -*-
"""
CPS DEV - MINI FAZ A CLEANUP PATCH
==================================

Bu script:
  1. templates/base.html'de "Karar MasasA+-" mojibake'sini "Karar Masasi" yapar
     (gercekte: Karar MasasÄ± -> Karar Masası)
  2. modules/planlama/proses_takip.py'den 4 adet debug print() satirini siler

Yedek: Her iki dosya da YEDEK_MFA_<ts> ile yedeklenir.
Idempotent: Tekrar calistirilirsa zarar vermez (zaten temizse SKIP).

DOKUNULMAYAN:
  - templates/planlama/proses_takip.html
  - static/js/proses_takip.js
  - static/css/proses_takip.css
  - Korgun mantigi
  - Faz 3 overlay
  - Diger modullerin hicbiri
"""
import sys
import os
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
BASE_HTML  = PROJECT_ROOT / "templates" / "base.html"
PROSES_PY  = PROJECT_ROOT / "modules" / "planlama" / "proses_takip.py"

ts = datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# 1) base.html mojibake fix
# ============================================================
# Mojibake bytes: 0x4D 0x61 0x73 0x61 0x73 0xC3 0x84 0xC2 0xB1
#                 M  a  s  a  s  Ã   Ä   Â   ±
# Hedef:        M  a  s  a  s  ı (UTF-8: 0xC4 0xB1)
# Yani "MasasÄ±" -> "Masası"

OLD_MOJI = "Karar MasasÄ±"
NEW_FIX  = "Karar Masası"


# ============================================================
# 2) proses_takip.py'den silinecek satirlarin EXACT pattern'leri
# ============================================================
# Satir 206-208 (3'lu blok):
PY_BLOCK_OLD = """    # Mevcut Korgun helper'ini kullan
    print('[PT_SQL] === SQL ===')
    print(sql)
    print('=========')
    from modules.common import korgun as kk"""

PY_BLOCK_NEW = """    # Mevcut Korgun helper'ini kullan
    from modules.common import korgun as kk"""

# Satir 229 (tekil):
PY_LINE_OLD  = '        print(f"[PT_SQL] row count = {len(rows)}")\n'
PY_LINE_NEW  = ''  # tamamen sil


# ============================================================
# PATCH FONKSIYONLARI
# ============================================================
def patch_base_html():
    print()
    print("=== base.html MOJIBAKE FIX ===")

    if not BASE_HTML.exists():
        print(f"  [HATA] Dosya yok: {BASE_HTML}")
        return False

    content = BASE_HTML.read_text(encoding="utf-8")

    if OLD_MOJI not in content:
        if NEW_FIX in content:
            print(f"  [SKIP] Zaten fix uygulanmis ('{NEW_FIX}' var)")
        else:
            print(f"  [UYARI] Ne mojibake ne fix yok - manuel kontrol edin")
        return True

    # Yedek
    backup = BASE_HTML.with_suffix(f".html.YEDEK_MFA_{ts}")
    backup.write_text(content, encoding="utf-8")
    print(f"  [OK] Yedek: {backup.name}")

    # Replace
    new_content = content.replace(OLD_MOJI, NEW_FIX)

    # Idempotent kontrol
    moji_count = content.count(OLD_MOJI)
    fix_count_after = new_content.count(NEW_FIX)
    print(f"  Mojibake sayisi (once):    {moji_count}")
    print(f"  Fix sayisi (sonra):        {fix_count_after}")

    BASE_HTML.write_text(new_content, encoding="utf-8")
    print(f"  [OK] base.html guncellendi: {len(content)} -> {len(new_content)} byte")
    return True


def patch_proses_py():
    print()
    print("=== proses_takip.py DEBUG PRINT TEMIZLIK ===")

    if not PROSES_PY.exists():
        print(f"  [HATA] Dosya yok: {PROSES_PY}")
        return False

    content = PROSES_PY.read_text(encoding="utf-8")
    original_size = len(content)

    # Idempotent check
    has_block = PY_BLOCK_OLD in content
    has_line  = PY_LINE_OLD in content

    if not has_block and not has_line:
        print("  [SKIP] Temiz - 4 print zaten yok")
        return True

    # Yedek
    backup = PROSES_PY.with_suffix(f".py.YEDEK_MFA_{ts}")
    backup.write_text(content, encoding="utf-8")
    print(f"  [OK] Yedek: {backup.name}")

    # Patch 1: 3'lu blok (sat 206-208)
    new_content = content
    if has_block:
        new_content = new_content.replace(PY_BLOCK_OLD, PY_BLOCK_NEW)
        removed_chars = len(PY_BLOCK_OLD) - len(PY_BLOCK_NEW)
        print(f"  [OK] 3 print silindi (sat 206-208), -{removed_chars} byte")
    else:
        print("  [SKIP] 3'lu blok zaten yok")

    # Patch 2: Tekil satir (sat 229)
    if has_line:
        new_content = new_content.replace(PY_LINE_OLD, PY_LINE_NEW)
        print(f"  [OK] 1 print silindi (sat 229), -{len(PY_LINE_OLD)} byte")
    else:
        print("  [SKIP] Tekil satir zaten yok")

    # Yaz
    PROSES_PY.write_text(new_content, encoding="utf-8")
    print(f"  [OK] proses_takip.py guncellendi: {original_size} -> {len(new_content)} byte")

    # Print sayisi tekrar say (dogrulama)
    import re
    remaining = len(re.findall(r'\bprint\s*\(', new_content))
    print(f"  Kalan print() sayisi: {remaining} (0 bekleniyor)")

    return True


def verify():
    print()
    print("=== DOGRULAMA ===")

    # base.html
    base_content = BASE_HTML.read_text(encoding="utf-8")
    has_moji = OLD_MOJI in base_content
    has_fix  = NEW_FIX in base_content
    print(f"  base.html mojibake var mi: {has_moji} (False bekleniyor)")
    print(f"  base.html fix var mi:      {has_fix}  (True bekleniyor)")

    # proses_takip.py
    py_content = PROSES_PY.read_text(encoding="utf-8")
    import re
    print_count = len(re.findall(r'\bprint\s*\(', py_content))
    print(f"  proses_takip.py print():   {print_count} (0 bekleniyor)")

    # Syntax check
    try:
        compile(py_content, str(PROSES_PY), 'exec')
        print(f"  proses_takip.py syntax:    OK")
    except SyntaxError as e:
        print(f"  [HATA] proses_takip.py syntax:  {e}")
        return False

    all_ok = (not has_moji) and has_fix and (print_count == 0)
    return all_ok


def main():
    print("=" * 60)
    print("CPS DEV - MINI FAZ A CLEANUP")
    print("=" * 60)

    if not patch_base_html():
        return 1
    if not patch_proses_py():
        return 1
    if not verify():
        print("\n[UYARI] Dogrulamada problem var, dosyalari kontrol edin!")
        return 1

    print()
    print("=" * 60)
    print("[OK] MINI FAZ A CLEANUP TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Flask restart")
    print("  2. /planlama/proses-takip - sayfa aciliyor mu, sidebar 'Karar Masasi' temiz mi")
    print("  3. /planlama/proses-takip/data - JSON donuyor mu (Korgun veya mock)")
    print("  4. Regression testi")
    return 0


if __name__ == "__main__":
    sys.exit(main())
