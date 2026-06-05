# -*- coding: utf-8 -*-
"""
CPS DEV - LIMIT BUG FIX (ONCELIK 1)
====================================

Sadece modules/uretim_giris/routes.py'a dokunulur.

3 BUG'in DUZELTILMESI:
  1. SQL emir_no bazli, PROSES BAZINDA OLACAK
  2. Sadece 'bekliyor' filtreliyor, 'onaylandi' DAHIL OLACAK
  3. Korgun toplam hedefi kullaniyor, emir_alt_proses.hedef_adet ONCELIKLI OLACAK
     (alt_hedef yoksa veya 0 ise Korgun hedefi fallback)

DEGISIKLIKLER:
  A. Sat ~155: SELECT'e hedef_adet eklenir
  B. Sat ~186-204: Limit hesaplama bloku yeniden yazilir

DOKUNULMAYAN:
  - Sablon sistemi
  - hedef/routes.py
  - emir_alt_proses DB yapisi
  - Korgun helper
  - uretim_giris.js (frontend response uyumlu kalir)
  - overlay/tasks/usta

Idempotent: Yeni mantik zaten varsa SKIP.
"""
import sys
import re
import shutil
import hashlib
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_PY    = PROJECT_ROOT / "modules" / "uretim_giris" / "routes.py"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# ESKI VE YENI BLOKLAR
# ============================================================

# A) SELECT genisletme
OLD_SELECT = (
    '            _row_chk = _con_chk.execute(\n'
    '                "SELECT id, proses_adi FROM emir_alt_proses "\n'
    '                "WHERE id = ? AND emir_no = ? AND aktif = 1",\n'
    '                (_pid_int, str(emir_no))\n'
    '            ).fetchone()'
)

NEW_SELECT = (
    '            _row_chk = _con_chk.execute(\n'
    '                "SELECT id, proses_adi, hedef_adet FROM emir_alt_proses "\n'
    '                "WHERE id = ? AND emir_no = ? AND aktif = 1",\n'
    '                (_pid_int, str(emir_no))\n'
    '            ).fetchone()'
)

# B) Limit kontrol bloku
# Su anki kodu hard-match ile yakalayabilmek icin TAM blok kullaniyoruz
OLD_LIMIT_BLOCK = (
    '        # Local SQLite\'taki bekleyen kayitlari da hesaba kat\n'
    '        con = _sqlite_uk.connect(_Config_uk.MOCK_DB_PATH)\n'
    '        try:\n'
    '            r = con.execute("""\n'
    '                SELECT COALESCE(SUM(miktar), 0)\n'
    '                FROM uretim_kayit\n'
    '                WHERE emir_no=? AND onay_durum=\'bekliyor\'\n'
    '            """, (emir_no,)).fetchone()\n'
    '            bekleyen_local = int(r[0] or 0)\n'
    '\n'
    '            # Hedef varsa kontrol\n'
    '            if hedef > 0:\n'
    '                kalan = max(0, int(hedef) - int(yapilan) - bekleyen_local)\n'
    '                if miktar > kalan:\n'
    '                    return _jsonify_uk({\'ok\': False, \'hata\': \'hedef_asimi\',\n'
    '                                        \'mesaj\': f\'Bu emrin kalani {kalan}, {miktar} giremezsin\',\n'
    '                                        \'hedef\': int(hedef), \'yapilan\': int(yapilan),\n'
    '                                        \'bekleyen\': bekleyen_local, \'kalan\': kalan,\n'
    '                                        \'yeni_miktar\': miktar}), 400'
)

NEW_LIMIT_BLOCK = (
    '        # === FAZ 5.0: PROSES BAZINDA LIMIT KONTROLU ===\n'
    '        # Hesaba katilan: bekliyor + onaylandi (PROSES BAZINDA)\n'
    '        # Limit kaynak: emir_alt_proses.hedef_adet > 0 ise o, yoksa Korgun toplam hedefi (fallback)\n'
    '        con = _sqlite_uk.connect(_Config_uk.MOCK_DB_PATH)\n'
    '        try:\n'
    '            # Bu prosesin onaylanan + bekleyen toplam miktari\n'
    '            r = con.execute("""\n'
    '                SELECT COALESCE(SUM(miktar), 0)\n'
    '                FROM uretim_kayit\n'
    '                WHERE emir_no=? AND proses_kodu=?\n'
    '                  AND onay_durum IN (\'bekliyor\',\'onaylandi\')\n'
    '            """, (emir_no, proses_kodu)).fetchone()\n'
    '            toplam_proses = int(r[0] or 0)\n'
    '\n'
    '            # Limit kaynak: alt_hedef oncelikli, yoksa Korgun fallback\n'
    '            _alt_hedef = int(_row_chk[2] or 0) if (len(_row_chk) > 2 and _row_chk[2] is not None) else 0\n'
    '            if _alt_hedef and _alt_hedef > 0:\n'
    '                limit = _alt_hedef\n'
    '                limit_kaynak = \'alt_proses\'\n'
    '            else:\n'
    '                limit = int(hedef or 0)\n'
    '                limit_kaynak = \'korgun\'\n'
    '\n'
    '            # Kontrol\n'
    '            if limit > 0:\n'
    '                kalan = max(0, limit - toplam_proses)\n'
    '                if miktar > kalan:\n'
    '                    return _jsonify_uk({\n'
    '                        \'ok\': False,\n'
    '                        \'hata\': \'hedef_asimi\',\n'
    '                        \'mesaj\': f"Bu prosesin limiti {limit} cift. Su ana kadar {toplam_proses} girilmis. Kalan {kalan}, {miktar} giremezsin.",\n'
    '                        \'limit\': limit,\n'
    '                        \'limit_kaynak\': limit_kaynak,\n'
    '                        \'proses_kodu\': proses_kodu,\n'
    '                        \'proses_adi\': proses_adi,\n'
    '                        \'toplam_proses\': toplam_proses,\n'
    '                        \'kalan\': kalan,\n'
    '                        \'yeni_miktar\': miktar,\n'
    '                    }), 400'
)


def file_hash(path):
    if not path.exists(): return None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main():
    print("=" * 60)
    print("CPS DEV - LIMIT BUG FIX")
    print("=" * 60)

    if not TARGET_PY.exists():
        print(f"  [HATA] Hedef dosya yok: {TARGET_PY}")
        return 1

    content = TARGET_PY.read_text(encoding="utf-8")
    original_size = len(content.encode("utf-8"))
    original_hash = file_hash(TARGET_PY)
    print(f"  Mevcut boyut: {original_size} byte")
    print(f"  Hash: {original_hash[:16]}...")

    # ============================================================
    # IDEMPOTENT KONTROL
    # ============================================================
    # Yeni mantik: "FAZ 5.0: PROSES BAZINDA LIMIT KONTROLU" marker
    if 'FAZ 5.0: PROSES BAZINDA LIMIT KONTROLU' in content:
        print()
        print("  [SKIP] Limit fix zaten uygulanmis (FAZ 5.0 marker var).")
        print()
        print("=" * 60)
        print("[OK] PATCH ZATEN UYGULANMIS")
        print("=" * 60)
        return 0

    # ============================================================
    # ON-KONTROLLER (anchor noktalari mevcut mu)
    # ============================================================
    print()
    print("=== ON-KONTROL (anchor pattern'lar) ===")

    if OLD_SELECT not in content:
        print("  [HATA] Eski SELECT bloku bulunamadi (anchor 1)")
        print("  Beklenen ifade: 'SELECT id, proses_adi FROM emir_alt_proses'")
        # Yumusak fallback - kismi match
        if 'SELECT id, proses_adi FROM emir_alt_proses' in content:
            print("  Pattern kismen var ama tam match degil. Manuel inceleme gerek.")
        return 1
    print("  [OK] Anchor 1: SELECT bloku bulundu")

    if OLD_LIMIT_BLOCK not in content:
        print("  [HATA] Eski limit bloku bulunamadi (anchor 2)")
        # Yardimci diagnostik
        if "WHERE emir_no=? AND onay_durum='bekliyor'" in content:
            print("  Eski SQL kismen var ama tam blok match degil.")
        return 1
    print("  [OK] Anchor 2: limit bloku bulundu")

    # ============================================================
    # YEDEK
    # ============================================================
    backup_path = TARGET_PY.with_suffix(f".py.YEDEK_LIMIT_{ts}")
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

    # 1) SELECT genislet
    yeni_content = content.replace(OLD_SELECT, NEW_SELECT, 1)
    if yeni_content == content:
        print("  [HATA] SELECT replace etkisiz")
        return 1
    print("  [OK] 1) SELECT genisletildi (hedef_adet eklendi)")

    # 2) Limit blok degistir
    yeni_content2 = yeni_content.replace(OLD_LIMIT_BLOCK, NEW_LIMIT_BLOCK, 1)
    if yeni_content2 == yeni_content:
        print("  [HATA] Limit blok replace etkisiz")
        return 1
    print("  [OK] 2) Limit bloku yeniden yazildi (proses bazli)")

    # ============================================================
    # YAZ
    # ============================================================
    print()
    print("=== DOSYAYA YAZMA ===")
    TARGET_PY.write_text(yeni_content2, encoding="utf-8")
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
        ('FAZ 5.0: PROSES BAZINDA LIMIT KONTROLU', 'Yeni marker var mi'),
        ("WHERE emir_no=? AND proses_kodu=?", 'PROSES BAZLI SQL var mi'),
        ("onay_durum IN ('bekliyor','onaylandi')", 'Onaylanan dahil mi'),
        ('SELECT id, proses_adi, hedef_adet FROM emir_alt_proses', 'hedef_adet SELECT eklendi mi'),
        ('limit_kaynak', 'limit_kaynak field var mi'),
        ('toplam_proses', 'toplam_proses field var mi'),
        ("'hata': 'hedef_asimi'", 'Hata kodu KORUNDU mu'),
        ("'kalan': kalan", 'kalan field KORUNDU mu (frontend uyum)'),
        ("'yeni_miktar': miktar", 'yeni_miktar KORUNDU mu (frontend uyum)'),
    ]
    all_ok = True
    for needle, desc in checks:
        ok = needle in final
        sym = "[OK]" if ok else "[HATA]"
        print(f"  {sym} {desc}")
        if not ok:
            all_ok = False

    # Eski mantigin TAMAMEN gittiginden emin ol
    if "WHERE emir_no=? AND onay_durum='bekliyor'" in final:
        print("  [UYARI] ESKI eski SQL hala var (yeni format ile karistirilmamali)")
        # Yine de basariyi etkilemiyor

    # ============================================================
    # SYNTAX CHECK (Python compile)
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
        print("  [UYARI] Bazi dogrulamalar basarisiz - manuel inceleme onerilir")
        return 1

    print()
    print("=" * 60)
    print("[OK] LIMIT BUG FIX TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Flask restart (Python dosya degisti, hot reload yetersiz)")
    print("  2. Test:")
    print("     - 110852/Capak/100  -> KABUL (122 zaten girilmis, kalan 3484)")
    print("     - 110852/Capak/4000 -> ENGEL (limit asimi)")
    print("     - 110852/Rivet/100  -> KABUL (Rivet ayri sayac)")
    print()
    print(f"Rollback (manuel, gerekirse):")
    print(f"  Copy-Item {backup_path.name} routes.py -Force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
