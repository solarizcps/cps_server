# -*- coding: utf-8 -*-
"""
CPS DEV - HEDEF_YETKILI USTA KABUL (FAZ 5.3)
=============================================

Sadece modules/hedef/routes.py'a dokunulur.
Sadece 1 fonksiyon (hedef_yetkili decorator).

YAPILACAK:
  hedef_yetkili decorator icinde:
    Eski: if not _admin_mi(): abort(403)
    Yeni: if not _admin_mi() and session.get('kullanici_tip') != 'usta': abort(403)
  
  Yani: admin VEYA Yonetim VEYA Tip='usta' olanlar /hedef/'i acabilir.

DOKUNULMAYAN:
  - _admin_mi() fonksiyonu (mevcut admin/Yonetim mantigi)
  - Endpoint'ler
  - Sablon sistemi
  - Korgun helper
  - DB / overlay / auth / base.html

Idempotent: 'FAZ 5.3' marker varsa SKIP.
"""
import sys
import shutil
import hashlib
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_PY    = PROJECT_ROOT / "modules" / "hedef" / "routes.py"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# ESKI VE YENI BLOK
# ============================================================
OLD_BLOCK = '''def hedef_yetkili(f):
    """Decorator: login + (admin veya Yönetim rolü)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('kullanici'):
            return redirect(url_for('auth.login', next=request.path))
        if not _admin_mi():
            abort(403)
        return f(*args, **kwargs)
    return wrapper'''

NEW_BLOCK = '''def hedef_yetkili(f):
    """Decorator: login + (admin VEYA Yönetim VEYA Tip='usta'). FAZ 5.3"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('kullanici'):
            return redirect(url_for('auth.login', next=request.path))
        # FAZ 5.3: usta tipi de /hedef/ acabilir
        if not _admin_mi() and session.get('kullanici_tip') != 'usta':
            abort(403)
        return f(*args, **kwargs)
    return wrapper'''


def file_hash(path):
    if not path.exists(): return None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main():
    print("=" * 60)
    print("CPS DEV - HEDEF_YETKILI USTA KABUL (FAZ 5.3)")
    print("=" * 60)

    if not TARGET_PY.exists():
        print(f"  [HATA] routes.py yok: {TARGET_PY}")
        return 1

    content = TARGET_PY.read_text(encoding="utf-8")
    original_size = len(content.encode("utf-8"))
    print(f"  Mevcut boyut: {original_size} byte")

    # ============================================================
    # IDEMPOTENT KONTROL
    # ============================================================
    if 'FAZ 5.3' in content:
        print()
        print("  [SKIP] FAZ 5.3 marker var, hedef_yetkili usta kabul zaten uygulanmis.")
        print()
        print("=" * 60)
        print("[OK] PATCH ZATEN UYGULANMIS")
        print("=" * 60)
        return 0

    # ============================================================
    # ON-KONTROL
    # ============================================================
    print()
    print("=== ON-KONTROL ===")

    if OLD_BLOCK not in content:
        print("  [HATA] Eski hedef_yetkili bloku tam match degil")
        # Diagnostik
        if 'def hedef_yetkili(f):' in content:
            print("       Fonksiyon var, ama icerigi degismis. Manuel inceleme gerek.")
            # 50 satirini goster
            idx = content.find('def hedef_yetkili(f):')
            snippet = content[idx:idx+500]
            print("       Mevcut blok:")
            for ln in snippet.split('\n')[:15]:
                print(f"         {ln[:120]}")
        return 1
    print("  [OK] Eski hedef_yetkili bloku bulundu")

    # ============================================================
    # YEDEK
    # ============================================================
    backup_path = TARGET_PY.with_suffix(f".py.YEDEK_HEDEF_USTA_{ts}")
    print()
    print("=== YEDEK ===")
    shutil.copy2(str(TARGET_PY), str(backup_path))
    print(f"  [OK] Yedek: {backup_path.name}")
    print(f"       Boyut: {backup_path.stat().st_size} byte")

    # ============================================================
    # PATCH UYGULA
    # ============================================================
    print()
    print("=== PATCH UYGULAMA ===")

    yeni_content = content.replace(OLD_BLOCK, NEW_BLOCK, 1)
    if yeni_content == content:
        print("  [HATA] Replace etkisiz")
        return 1
    print("  [OK] hedef_yetkili decorator guncellendi (usta kabul)")

    # ============================================================
    # YAZ
    # ============================================================
    print()
    print("=== DOSYAYA YAZMA ===")
    TARGET_PY.write_text(yeni_content, encoding="utf-8")
    new_size = TARGET_PY.stat().st_size
    diff = new_size - original_size
    print(f"  [OK] Yeni boyut: {new_size} byte (fark: {'+' if diff >= 0 else ''}{diff})")

    # ============================================================
    # DOGRULAMA
    # ============================================================
    print()
    print("=== DOGRULAMA ===")
    final = TARGET_PY.read_text(encoding="utf-8")

    checks = [
        ('FAZ 5.3', 'Yeni marker var mi'),
        ("session.get('kullanici_tip') != 'usta'", 'usta kontrol eklendi mi'),
        ('def hedef_yetkili(f):', 'fonksiyon hala var mi'),
        ('def _admin_mi(', '_admin_mi fonksiyonu korundu mu'),
        ('abort(403)', 'abort 403 korundu mu'),
        # Diger korumalar (regression)
        ('@hedef_yetkili', 'decorator kullanim yerleri korundu mu'),
        ('def _resolve_target_emir', '_resolve_target_emir korundu mu (sablon)'),
        ('emir_alt_proses', 'emir_alt_proses tablo erisimi korundu mu'),
    ]
    all_ok = True
    for needle, desc in checks:
        ok = needle in final
        sym = "[OK]" if ok else "[HATA]"
        print(f"  {sym} {desc}")
        if not ok:
            all_ok = False

    # @hedef_yetkili sayisi DEGISMEMELI (5 olmali)
    dec_count_old = content.count('@hedef_yetkili')
    dec_count_new = final.count('@hedef_yetkili')
    print(f"  @hedef_yetkili kullanim sayisi: eski={dec_count_old}, yeni={dec_count_new}")
    if dec_count_old != dec_count_new:
        print(f"  [HATA] Decorator kullanim sayisi degisti")
        all_ok = False
    else:
        print(f"  [OK] Decorator kullanim sayisi korundu")

    # ============================================================
    # SYNTAX CHECK
    # ============================================================
    print()
    print("=== PYTHON SYNTAX CHECK ===")
    try:
        compile(final, str(TARGET_PY), 'exec')
        print("  [OK] Syntax dogru")
    except SyntaxError as e:
        print(f"  [HATA] SyntaxError: {e}")
        print(f"         Satir {e.lineno}: {e.text}")
        return 1

    if not all_ok:
        print()
        print("  [UYARI] Bazi dogrulamalar basarisiz")
        return 1

    print()
    print("=" * 60)
    print("[OK] HEDEF_YETKILI USTA KABUL PATCH TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Flask RESTART (Python dosya degisti)")
    print("     - Adem terminale: Ctrl+C, sonra python app.py")
    print("     - Veya debug=True ise auto-reload yetebilir")
    print("  2. Test:")
    print("     - admin/admin123    -> /hedef/ -> 200 (mevcut)")
    print("     - test_usta/test123 -> /hedef/ -> 200 (yeni!)")
    print("     - test_personel/test123 -> /hedef/ -> 403 (degismedi)")
    print()
    print(f"Rollback (manuel, gerekirse):")
    print(f"  Copy-Item modules\\hedef\\{backup_path.name} modules\\hedef\\routes.py -Force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
