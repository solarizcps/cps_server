# -*- coding: utf-8 -*-
"""
CPS DEV - URETIM_YETKI TIP ONCELIK FIX (FAZ 5.5)
=================================================

Sadece modules/uretim_giris/routes.py'a dokunulur.
Sadece _uretim_yetkili_mi() fonksiyonu degisir.

YAPILACAK:
  Mevcut mantik (sadece RolAd kontrol):
    rol = u.get('RolAd') or ''
    return rol in ('Personel', 'Usta', 'Yönetim', 'Üretim')
  
  Yeni mantik (FAZ 5.5):
    1. session['kullanici_tip'] in ('personel', 'usta') -> True
    2. u['KullaniciAdi'] == 'admin' -> True
    3. Rol kontrolu (guvenli okuma): RolAd / Rol / rol_ad / rol

DOKUNULMAYAN:
  - uretim_yetkili decorator
  - Endpoint'ler (panel, kaydet, vb)
  - auth.py / base.html / hedef
  - DB / overlay / Korgun

Idempotent: 'FAZ 5.5' marker varsa SKIP.
"""
import sys
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_PY    = PROJECT_ROOT / "modules" / "uretim_giris" / "routes.py"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# ESKI VE YENI BLOK
# ============================================================
OLD_BLOCK = '''def _uretim_yetkili_mi():
    u = session.get('kullanici')
    if not u:
        return False

    if u.get('KullaniciAdi') == 'admin':
        return True

    rol = u.get('RolAd') or ''
    return rol in ('Personel', 'Usta', 'Yönetim', 'Üretim')'''

NEW_BLOCK = '''def _uretim_yetkili_mi():
    """FAZ 5.5: Tip oncelikli + admin + rol fallback."""
    u = session.get('kullanici')
    if not u:
        return False

    # FAZ 5.5: Tip kontrolu (personel ve usta her zaman /uretim/ acabilir)
    tip = session.get('kullanici_tip')
    if tip in ('personel', 'usta'):
        return True

    # Admin kisayolu
    if u.get('KullaniciAdi') == 'admin':
        return True

    # Rol kontrolu - guvenli okuma (RolAd, Rol, rol_ad, rol)
    rol = (u.get('RolAd') or u.get('Rol') or u.get('rol_ad') or u.get('rol') or '').strip()
    return rol in ('Personel', 'Usta', 'Yönetim', 'Üretim')'''


def main():
    print("=" * 60)
    print("CPS DEV - URETIM_YETKI TIP ONCELIK FIX (FAZ 5.5)")
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
    if 'FAZ 5.5' in content:
        print()
        print("  [SKIP] FAZ 5.5 marker var, _uretim_yetkili_mi tip oncelik zaten uygulanmis.")
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
        print("  [HATA] Eski _uretim_yetkili_mi bloku tam match degil")
        if 'def _uretim_yetkili_mi(' in content:
            print("       Fonksiyon var, ama icerigi farkli. Manuel inceleme gerek.")
            idx = content.find('def _uretim_yetkili_mi(')
            snippet = content[idx:idx+400]
            print("       Mevcut blok:")
            for ln in snippet.split('\n')[:12]:
                print(f"         {ln[:130]}")
        return 1
    print("  [OK] Eski _uretim_yetkili_mi bloku bulundu")

    # ============================================================
    # YEDEK
    # ============================================================
    backup_path = TARGET_PY.with_suffix(f".py.YEDEK_URETIMYETKI_{ts}")
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
    print("  [OK] _uretim_yetkili_mi guncellendi (tip oncelikli + rol fallback)")

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
        ('FAZ 5.5', 'Yeni marker var mi'),
        ("session.get('kullanici_tip')", 'tip session okumu eklendi mi'),
        ("tip in ('personel', 'usta')", 'personel + usta kabul'),
        ("u.get('KullaniciAdi') == 'admin'", 'admin kisayolu korundu mu'),
        ("u.get('Rol')", 'fallback Rol okuma'),
        ("u.get('rol_ad')", 'fallback rol_ad okuma'),
        ("u.get('rol')", 'fallback rol okuma'),
        ("'Personel', 'Usta', 'Yönetim', 'Üretim'", 'rol tuple korundu'),
        ('def _uretim_yetkili_mi(', 'fonksiyon var'),
        ('def uretim_yetkili(f):', 'decorator korundu'),
        ('@uretim_yetkili', 'decorator kullanim yerleri korundu'),
        # Limit fix korundu mu (regression)
        ('proses_kodu', 'limit fix anchor korundu'),
        ('FAZ 5.0', 'limit fix marker korundu'),
        ('emir_alt_proses', 'emir_alt_proses tablo erisimi korundu'),
    ]
    all_ok = True
    for needle, desc in checks:
        ok = needle in final
        sym = "[OK]" if ok else "[HATA]"
        print(f"  {sym} {desc}")
        if not ok:
            all_ok = False

    # @uretim_yetkili sayisi DEGISMEMELI
    dec_count_old = content.count('@uretim_yetkili')
    dec_count_new = final.count('@uretim_yetkili')
    print(f"  @uretim_yetkili kullanim sayisi: eski={dec_count_old}, yeni={dec_count_new}")
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
        return 1

    if not all_ok:
        print()
        print("  [UYARI] Bazi dogrulamalar basarisiz")
        return 1

    print()
    print("=" * 60)
    print("[OK] FAZ 5.5 URETIM_YETKI TIP ONCELIK FIX TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Flask RESTART (Python dosya degisti)")
    print("  2. 8 senaryo test")
    print()
    print(f"Rollback (manuel, gerekirse):")
    print(f"  Copy-Item modules\\uretim_giris\\{backup_path.name} modules\\uretim_giris\\routes.py -Force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
