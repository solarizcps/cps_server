# -*- coding: utf-8 -*-
"""
CPS DEV - FAZ 7 ADIM 2 BUG FIX
================================

HATA:
  ADIM 2'de Blueprint degisken adi YANLIS yazildi.
  @yonetim.route(...) → Blueprint NAME (string)
  @yonetim_bp.route(...) → DOGRU (Python degisken)

DUZELTME:
  Sadece FAZ 7 markerdan sonraki bolumde:
    @yonetim.route → @yonetim_bp.route

Idempotent: @yonetim. yoksa SKIP
Yedek: routes.py.YEDEK_FAZ7_BUGFIX_<ts>
"""
import sys
import re
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_PY = PROJECT_ROOT / "modules" / "yonetim" / "routes.py"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


def main():
    print("=" * 60)
    print("CPS DEV - FAZ 7 ADIM 2 BUG FIX")
    print("=" * 60)

    if not TARGET_PY.exists():
        print(f"  [HATA] dosya yok: {TARGET_PY}")
        return 1

    content = TARGET_PY.read_text(encoding="utf-8")
    print(f"  Mevcut boyut: {len(content.encode('utf-8'))} byte")

    # ============================================================
    # ON-KONTROL
    # ============================================================
    print()
    print("=== ON-KONTROL ===")
    
    # FAZ 7 marker var mi
    if 'FAZ 7' not in content:
        print("  [HATA] FAZ 7 marker yok - ADIM 2 calisitirilmamis")
        return 1
    print("  [OK] FAZ 7 marker bulundu")
    
    # FAZ 7 bolumunu ayir
    faz7_marker_pos = content.find('# FAZ 7 - STANDART SURE ENDPOINT')
    if faz7_marker_pos < 0:
        # Alternatif marker
        faz7_marker_pos = content.find('FAZ 7')
    if faz7_marker_pos < 0:
        print("  [HATA] FAZ 7 bolumu bulunamadi")
        return 1
    
    once = content[:faz7_marker_pos]
    sonra = content[faz7_marker_pos:]
    
    # Hatayi say (sadece FAZ 7 bolumunde)
    hata_sayisi = sonra.count('@yonetim.route')
    print(f"  '@yonetim.route' (HATALI) sayisi: {hata_sayisi}")
    
    # IDEMPOTENT
    if hata_sayisi == 0:
        if '@yonetim_bp.route' in sonra:
            print()
            print("  [SKIP] Bug zaten duzeltilmis (@yonetim_bp.route var)")
            print("=" * 60)
            return 0
        else:
            print()
            print("  [UYARI] @yonetim.route bulunamadi - belki manuel duzelttin?")
            print("=" * 60)
            return 0
    
    if hata_sayisi != 3:
        print(f"  [UYARI] 3 esleme bekleniyor, {hata_sayisi} bulundu")
        # Yine de devam et

    # ============================================================
    # YEDEK
    # ============================================================
    backup_path = TARGET_PY.with_suffix(f".py.YEDEK_FAZ7_BUGFIX_{ts}")
    print()
    print("=== YEDEK ===")
    shutil.copy2(str(TARGET_PY), str(backup_path))
    print(f"  [OK] Yedek: {backup_path.name}")

    # ============================================================
    # FIX UYGULA - SADECE FAZ 7 BOLUMUNDE
    # ============================================================
    print()
    print("=== FIX UYGULAMA ===")
    
    sonra_fixed = sonra.replace('@yonetim.route', '@yonetim_bp.route')
    yeni_content = once + sonra_fixed
    
    TARGET_PY.write_text(yeni_content, encoding="utf-8")
    new_size = TARGET_PY.stat().st_size
    print(f"  [OK] FAZ 7 bolumunde @yonetim. → @yonetim_bp. degistirildi")
    print(f"  Yeni boyut: {new_size} byte")

    # ============================================================
    # DOGRULAMA
    # ============================================================
    print()
    print("=== DOGRULAMA ===")
    final = TARGET_PY.read_text(encoding="utf-8")
    
    # FAZ 7 bolumunde @yonetim.route artik OLMAMALI
    final_pos = final.find('FAZ 7')
    final_once = final[:final_pos]
    final_sonra = final[final_pos:]
    
    if '@yonetim.route' in final_sonra:
        print("  [HATA] Hala @yonetim.route var FAZ 7 bolumunde")
        return 1
    print("  [OK] FAZ 7 bolumunde @yonetim.route YOK")
    
    if '@yonetim_bp.route' in final_sonra:
        print("  [OK] @yonetim_bp.route mevcut")
    else:
        print("  [HATA] @yonetim_bp.route bulunamadi")
        return 1
    
    # 3 yeni route hala var
    checks = [
        "@yonetim_bp.route('/proses-kategori/liste'",
        "@yonetim_bp.route('/proses-kategori/<proses_kod>/sure'",
        "@yonetim_bp.route('/proses-kategori/yeni'",
        "faz7_proses_kategori_liste",
        "faz7_proses_kategori_sure_guncelle",
        "faz7_proses_kategori_yeni",
    ]
    for c in checks:
        if c in final:
            print(f"  [OK] {c[:60]}")
        else:
            print(f"  [HATA] {c[:60]}")
            return 1
    
    # Mevcut /kur/api ve /belge/ korundu mu (FAZ 7 ONCESI bolum)
    if '/kur/api' in final_once and '/belge/' in final_once:
        print("  [OK] /kur/api ve /belge/ korundu")
    else:
        print("  [UYARI] /kur/api veya /belge/ bulunamadi")

    # ============================================================
    # PYTHON SYNTAX CHECK
    # ============================================================
    print()
    print("=== PYTHON SYNTAX CHECK ===")
    try:
        compile(final, str(TARGET_PY), 'exec')
        print("  [OK] Syntax dogru")
    except SyntaxError as e:
        print(f"  [HATA] SyntaxError: {e}")
        return 1

    print()
    print("=" * 60)
    print("[OK] FAZ 7 BUG FIX TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Flask BASLAT: python app.py")
    print("  2. Otomatik test bloğunu calıştır (önceki test bloğu)")
    print()
    print(f"Rollback (manuel):")
    print(f"  Copy-Item modules\\yonetim\\{backup_path.name} modules\\yonetim\\routes.py -Force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
