# -*- coding: utf-8 -*-
"""
CPS DEV - MINI FAZ B PATCH
==========================

Bu script:
  1. static/js/usta.js'i .YEDEK_MFB_v42_<ts> olarak yedekler
  2. Yeni mini usta.js'i (Faz 4.3 mantigi) yerine yerlestirir

YENI usta.js:
  - Hayalet endpoint /api/v2/usta/* CAGIRILMAZ
  - Gercek endpoint /usta/api/gorevler kullanilir
  - ATANDI -> OKUNDU -> BASLADI -> TAMAMLANDI durum makinesi
  - GIRIS sekmesi 'Yakinda' mesaji
  - ONAY sekmesi TAMAMLANDI islerini gosterir (read-only)

DOKUNULMAYAN:
  - HTML (index.html)
  - CSS (usta.css)
  - Backend (modules/usta/, modules/hedef/)
  - DB
  - Sablon sistemi
  - Faz 3 overlay

Idempotent: Yeni dosya zaten yerinde ise SKIP.
"""
import sys
import os
import shutil
import hashlib
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_JS    = PROJECT_ROOT / "static" / "js" / "usta.js"
NEW_JS_SRC   = PROJECT_ROOT / "usta.mini.js"  # Indirilen yeni dosya

ts = datetime.now().strftime("%Y%m%d_%H%M%S")


def file_hash(path):
    """Dosyanin SHA256 hash'i (idempotent kontrol icin)."""
    if not path.exists():
        return None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main():
    print("=" * 60)
    print("CPS DEV - MINI FAZ B PATCH (yeni usta.js)")
    print("=" * 60)

    # 1) Kaynak dosya kontrol
    if not NEW_JS_SRC.exists():
        print(f"  [HATA] Yeni JS dosyasi yok: {NEW_JS_SRC}")
        print(f"         Indir: usta.mini.js -> C:\\cps_dev\\")
        return 1

    if not TARGET_JS.exists():
        print(f"  [HATA] Hedef dosya yok: {TARGET_JS}")
        return 1

    # 2) Idempotent kontrol - yeni dosya ile mevcut ayni mi?
    new_hash = file_hash(NEW_JS_SRC)
    cur_hash = file_hash(TARGET_JS)

    if new_hash == cur_hash:
        print()
        print("  [SKIP] usta.js zaten yeni surumde (hash eslesti)")
        print(f"  Hash: {new_hash[:16]}...")
        # Yine de NEW_JS_SRC'yi sil (calisma alanini temizle)
        try:
            NEW_JS_SRC.unlink()
            print(f"  [OK] Calisma dosyasi silindi: {NEW_JS_SRC.name}")
        except Exception:
            pass
        print()
        print("=" * 60)
        print("[OK] PATCH ZATEN UYGULANMIS")
        print("=" * 60)
        return 0

    # 3) Yedek al (sadece henuz yedek yoksa veya farkli ise)
    backup_path = TARGET_JS.with_suffix(f".js.YEDEK_MFB_v42_{ts}")

    print()
    print("=== YEDEK ALMA ===")
    shutil.copy2(str(TARGET_JS), str(backup_path))
    print(f"  [OK] Yedek: {backup_path.name}")
    print(f"       Boyut: {backup_path.stat().st_size} byte")

    # 4) Yeni dosyayi yerine koy
    print()
    print("=== YENI usta.js YERLESTIRME ===")
    shutil.copy2(str(NEW_JS_SRC), str(TARGET_JS))
    print(f"  [OK] Yeni dosya yerlesti: {TARGET_JS.name}")
    print(f"       Boyut: {TARGET_JS.stat().st_size} byte")

    # 5) Calisma dosyasini sil
    try:
        NEW_JS_SRC.unlink()
        print(f"  [OK] Calisma dosyasi silindi: {NEW_JS_SRC.name}")
    except Exception:
        pass

    # 6) Dogrulama
    print()
    print("=== DOGRULAMA ===")
    final_hash = file_hash(TARGET_JS)
    print(f"  Yeni dosya hash:     {final_hash[:16]}...")
    print(f"  Beklenen hash:       {new_hash[:16]}...")
    print(f"  Hash eslesti mi:     {final_hash == new_hash}")

    # Hayalet endpoint check
    content = TARGET_JS.read_text(encoding="utf-8")
    hayalet_count = content.count("/api/v2/usta/")
    gercek_count = content.count("/usta/api/gorevler") + content.count("/usta/api/gorev/")
    print(f"  Hayalet /api/v2/usta/* sayisi:  {hayalet_count}  (0 bekleniyor)")
    print(f"  Gercek /usta/api/* sayisi:      {gercek_count}  (>=4 bekleniyor)")

    if hayalet_count > 0:
        print(f"  [UYARI] Hayalet endpoint hala var!")
        return 1
    if gercek_count < 4:
        print(f"  [UYARI] Gercek endpoint sayisi az!")
        return 1

    print()
    print("=" * 60)
    print("[OK] MINI FAZ B PATCH TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Tarayicida hard refresh: Ctrl+Shift+R")
    print("  2. Ac: http://127.0.0.1:5057/usta/")
    print("  3. F12 Console + Network kontrol")
    print("  4. Acik isler listesi yuklenip yuklenmedigi")
    print("  5. /api/v2/usta/* cagrisi YOK olmali")
    print("  6. /usta/api/gorevler 200 donmeli")
    return 0


if __name__ == "__main__":
    sys.exit(main())
