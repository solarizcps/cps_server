# -*- coding: utf-8 -*-
"""
CPS DEV - TIP GUARD BEFORE_REQUEST HOOK (FAZ 5.4)
==================================================

Sadece modules/auth.py'a dokunulur.
Yeni bir before_app_request hook eklenir: _tip_guard()

KURAL:
  - Bypass: /static/*, /favicon.ico, /giris, /cikis, /sifre-degistir
  - Session yoksa: dokunma (mevcut decorator'lar engellesin)
  - tip='sistem' icin: engel YOK
  - tip='personel' icin: SADECE /uretim/* izinli, diger → /uretim/
  - tip='usta' icin: /hedef/* + /uretim/* izinli, diger → /hedef/

DOKUNULMAYAN:
  - login_kullanici, login(), logout, sifre_degistir
  - attach_user() (mevcut hook)
  - yetki_gerekli, login_gerekli decorator'lari
  - sistem_kullanici, pers_kullanici, usta_kullanici sorgu mantigi
  - DB / Sidebar / Tasks / Overlay / Korgun

Idempotent: 'FAZ 5.4 TIP GUARD' marker varsa SKIP.
"""
import sys
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_PY    = PROJECT_ROOT / "modules" / "auth.py"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# EKLENECEK YENI BLOK (auth.py sonuna append)
# ============================================================
NEW_BLOCK = '''

# ============================================================
# FAZ 5.4 TIP GUARD - URL ALLOWLIST
# ============================================================

_TIP_GUARD_BYPASS_PREFIXES = ('/static/',)
_TIP_GUARD_BYPASS_PATHS = ('/favicon.ico', '/giris', '/cikis', '/sifre-degistir')


@auth_bp.before_app_request
def _tip_guard():
    """FAZ 5.4 TIP GUARD: Tip bazli URL allowlist.
    
    - sistem: hicbir engel
    - personel: /uretim/* + bypass disinda -> /uretim/'e redirect
    - usta: /hedef/* + /uretim/* + bypass disinda -> /hedef/'e redirect
    - login yoksa: dokunma (mevcut decorator'lar engelleyecek)
    """
    path = request.path or '/'
    
    # 1) Bypass: prefix
    for _p in _TIP_GUARD_BYPASS_PREFIXES:
        if path.startswith(_p):
            return
    
    # 2) Bypass: tam yol
    if path in _TIP_GUARD_BYPASS_PATHS:
        return
    
    # 3) Login yoksa: dokunma
    if not session.get('kullanici'):
        return
    
    # 4) Tip al
    tip = session.get('kullanici_tip')
    if not tip or tip == 'sistem':
        return  # sistem icin engel yok
    
    # 5) Personel: sadece /uretim/*
    if tip == 'personel':
        if not path.startswith('/uretim/'):
            return redirect('/uretim/')
        return
    
    # 6) Usta: /hedef/* + /uretim/*
    if tip == 'usta':
        if not (path.startswith('/hedef/') or path.startswith('/uretim/')):
            return redirect('/hedef/')
        return
    
    # Bilinmeyen tip -> dokunma (mevcut decorator'lar engellesin)
    return
'''


def main():
    print("=" * 60)
    print("CPS DEV - FAZ 5.4 TIP GUARD HOOK")
    print("=" * 60)

    if not TARGET_PY.exists():
        print(f"  [HATA] auth.py yok: {TARGET_PY}")
        return 1

    content = TARGET_PY.read_text(encoding="utf-8")
    original_size = len(content.encode("utf-8"))
    print(f"  Mevcut boyut: {original_size} byte")

    # ============================================================
    # IDEMPOTENT KONTROL
    # ============================================================
    if 'FAZ 5.4 TIP GUARD' in content or 'def _tip_guard(' in content:
        print()
        print("  [SKIP] FAZ 5.4 TIP GUARD marker var, hook zaten uygulanmis.")
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

    # auth_bp tanimi olmali
    if 'auth_bp = Blueprint' not in content:
        print("  [HATA] auth_bp Blueprint tanimi yok")
        return 1
    print("  [OK] auth_bp Blueprint tanimi var")

    # FAZ 5.1 olmali (kullanici_tip session)
    if "session['kullanici_tip']" not in content:
        print("  [UYARI] FAZ 5.1 session['kullanici_tip'] yok - tip guard etkisiz olabilir")
    else:
        print("  [OK] FAZ 5.1 session['kullanici_tip'] mevcut")

    # before_app_request var mi (attach_user)
    bafr_count_before = content.count('@auth_bp.before_app_request')
    print(f"  Mevcut @auth_bp.before_app_request sayisi: {bafr_count_before}")

    # request, session, redirect zaten import edilmis mi (auth.py sat 3)
    if 'from flask import' not in content:
        print("  [HATA] flask import yok")
        return 1
    if 'request' in content and 'session' in content and 'redirect' in content:
        print("  [OK] request, session, redirect kullanimda")
    else:
        print("  [HATA] gerekli flask sembolleri eksik")
        return 1

    # ============================================================
    # YEDEK
    # ============================================================
    backup_path = TARGET_PY.with_suffix(f".py.YEDEK_TIPGUARD_{ts}")
    print()
    print("=== YEDEK ===")
    shutil.copy2(str(TARGET_PY), str(backup_path))
    print(f"  [OK] Yedek: {backup_path.name}")
    print(f"       Boyut: {backup_path.stat().st_size} byte")

    # ============================================================
    # PATCH UYGULA - DOSYA SONUNA APPEND
    # ============================================================
    print()
    print("=== PATCH UYGULAMA ===")

    # Mevcut content sonu newline ile bitsin
    if not content.endswith('\n'):
        content = content + '\n'
    
    yeni_content = content + NEW_BLOCK

    print("  [OK] Yeni hook _tip_guard() dosya sonuna eklendi")

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
        ('FAZ 5.4 TIP GUARD', 'Yeni marker var mi'),
        ('def _tip_guard():', 'Hook fonksiyonu var mi'),
        ('_TIP_GUARD_BYPASS_PREFIXES', 'Bypass prefix sabiti'),
        ('_TIP_GUARD_BYPASS_PATHS', 'Bypass path sabiti'),
        ("'/static/'", '/static/ bypass'),
        ("'/favicon.ico'", 'favicon bypass'),
        ("'/giris'", 'giris bypass'),
        ("'/cikis'", 'cikis bypass'),
        ("'/sifre-degistir'", 'sifre-degistir bypass'),
        ("session.get('kullanici_tip')", 'tip session okumu'),
        ("if tip == 'personel':", 'personel dali'),
        ("if tip == 'usta':", 'usta dali'),
        ("redirect('/uretim/')", 'personel redirect'),
        ("redirect('/hedef/')", 'usta redirect'),
        # Mevcut sistem korundu mu
        ('def login_kullanici(', 'login_kullanici korundu'),
        ('def login():', 'login route korundu'),
        ('def attach_user():', 'attach_user korundu'),
        ('def logout():', 'logout korundu'),
        ('def sifre_degistir():', 'sifre_degistir korundu'),
        ('FAZ 5.1', 'FAZ 5.1 marker korundu'),
    ]
    all_ok = True
    for needle, desc in checks:
        ok = needle in final
        sym = "[OK]" if ok else "[HATA]"
        print(f"  {sym} {desc}")
        if not ok:
            all_ok = False

    # before_app_request sayisi 1 -> 2 olmali
    bafr_count_after = final.count('@auth_bp.before_app_request')
    print(f"  @auth_bp.before_app_request sayisi: {bafr_count_before} -> {bafr_count_after}")
    if bafr_count_after != bafr_count_before + 1:
        print(f"  [HATA] Yeni hook eklenmemis veya cift eklenmis")
        all_ok = False
    else:
        print(f"  [OK] Yeni hook eklendi (1 artti)")

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
    print("[OK] FAZ 5.4 TIP GUARD HOOK PATCH TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Flask RESTART (Python dosya degisti)")
    print("  2. Test: 18 senaryo")
    print()
    print(f"Rollback (manuel, gerekirse):")
    print(f"  Copy-Item modules\\{backup_path.name} modules\\auth.py -Force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
