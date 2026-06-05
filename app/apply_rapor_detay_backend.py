# -*- coding: utf-8 -*-
"""
CPS DEV - HEDEF RAPOR DETAY BACKEND (FAZ 6.2)
==============================================

YAPILACAK:
  hedef_rapor() endpoint'ine YENI bir SELECT eklenir:
    kayit_listesi (raw uretim_kayit satirlari, LIMIT 200)
  
  Mevcut yapi (personel_bazli + proses_bazli + emir_bazli) DOKUNULMAZ.
  Sadece response'a YENI bir alan eklenir.

DOKUNULMAYAN:
  - DB schema
  - Diger endpoint'ler (sapma, onaylar, gecmis, plan, sablon)
  - Frontend (hedef.js, index.html)
  - Mevcut 3 grup ozet sorgular
  - Auth / guard / limit mantigi

ALAN ICERIGI (her satir):
  id, emir_no, proses_kodu, proses_adi, miktar,
  personel_id, personel_ad, tarih, saat,
  onay_durum (onaylandi VEYA bekliyor),
  usta_id, usta_ad, usta_not, not_metin,
  onay_tarihi, olusturma

FILTRE:
  - onay_durum IN ('onaylandi', 'bekliyor')
  - tarih araligi: mevcut bas/bit parametrelerine bagli
  - LIMIT 200
  - ORDER BY olusturma DESC

Idempotent: 'FAZ 6.2' marker varsa SKIP.
Yedek: routes.py.YEDEK_RAPORDETAY_<ts>
"""
import sys
import re
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_PY = PROJECT_ROOT / "modules" / "hedef" / "routes.py"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")

# ============================================================
# OLD: emir_raw cumlesinden conn.close()'a kadar
# ============================================================
OLD_BLOCK = '''        emir_raw = [dict(r) for r in cur.fetchall()]
        conn.close()'''

NEW_BLOCK = '''        emir_raw = [dict(r) for r in cur.fetchall()]

        # FAZ 6.2 - YENI: kayit_listesi (raw uretim_kayit satirlari, detay rapor icin)
        cur.execute("""
            SELECT id, emir_no, proses_kodu, proses_adi, miktar,
                   personel_id, personel_ad, tarih, saat,
                   onay_durum, usta_id, usta_ad, usta_not,
                   not_metin, onay_tarihi, olusturma
              FROM uretim_kayit
             WHERE onay_durum IN ('onaylandi', 'bekliyor')
               AND date(COALESCE(NULLIF(onay_tarihi,''), olusturma)) BETWEEN ? AND ?
             ORDER BY olusturma DESC
             LIMIT 200
        """, (bas, bit))
        kayit_listesi = []
        for r in cur.fetchall():
            d = dict(r)
            kayit_listesi.append({
                'id': d.get('id'),
                'emir_no': str(d.get('emir_no') or ''),
                'proses_kodu': d.get('proses_kodu') or '',
                'proses_adi': d.get('proses_adi') or '',
                'miktar': int(d.get('miktar') or 0),
                'personel_id': d.get('personel_id'),
                'personel_ad': d.get('personel_ad') or '',
                'tarih': d.get('tarih') or '',
                'saat': d.get('saat') or '',
                'onay_durum': d.get('onay_durum') or '',
                'usta_id': d.get('usta_id'),
                'usta_ad': d.get('usta_ad') or '',
                'usta_not': d.get('usta_not') or '',
                'not_metin': d.get('not_metin') or '',
                'onay_tarihi': d.get('onay_tarihi') or '',
                'olusturma': d.get('olusturma') or '',
            })

        conn.close()'''

# ============================================================
# return jsonify icindeki emir_bazli sonrasina kayit_listesi ekle
# ============================================================
OLD_RETURN = '''            'emir_bazli': emir_bazli,
        })'''

NEW_RETURN = '''            'emir_bazli': emir_bazli,
            'kayit_listesi': kayit_listesi,
        })'''


def main():
    print("=" * 60)
    print("CPS DEV - HEDEF RAPOR DETAY BACKEND (FAZ 6.2)")
    print("=" * 60)

    if not TARGET_PY.exists():
        print(f"  [HATA] dosya yok: {TARGET_PY}")
        return 1

    content = TARGET_PY.read_text(encoding="utf-8")
    original_size = len(content.encode("utf-8"))
    print(f"  Mevcut boyut: {original_size} byte")

    # ============================================================
    # IDEMPOTENT
    # ============================================================
    if 'FAZ 6.2' in content and 'kayit_listesi' in content:
        print()
        print("  [SKIP] FAZ 6.2 marker var, rapor detay zaten uygulanmis.")
        print("=" * 60)
        return 0

    # ============================================================
    # ON-KONTROL
    # ============================================================
    print()
    print("=== ON-KONTROL ===")

    # OLD_BLOCK essiz mi
    block_count = content.count(OLD_BLOCK)
    print(f"  emir_raw + conn.close blok: {block_count} adet")
    if block_count != 1:
        print(f"  [HATA] Tek esleme bekleniyor, {block_count} bulundu")
        if block_count == 0:
            # Yardimci: emir_raw etrafini goster
            idx = content.find('emir_raw')
            if idx >= 0:
                print(f"  emir_raw etrafi: {content[idx:idx+200]!r}")
        return 1
    print("  [OK] OLD_BLOCK essiz")

    # OLD_RETURN essiz mi
    ret_count = content.count(OLD_RETURN)
    print(f"  return jsonify emir_bazli sonu: {ret_count} adet")
    if ret_count != 1:
        print(f"  [HATA] Tek esleme bekleniyor, {ret_count} bulundu")
        return 1
    print("  [OK] OLD_RETURN essiz")

    # hedef_rapor fonksiyonu var mi
    if 'def hedef_rapor(' not in content:
        print("  [HATA] hedef_rapor fonksiyonu yok")
        return 1
    print("  [OK] hedef_rapor() fonksiyonu mevcut")

    # ============================================================
    # YEDEK
    # ============================================================
    backup_path = TARGET_PY.with_suffix(f".py.YEDEK_RAPORDETAY_{ts}")
    print()
    print("=== YEDEK ===")
    shutil.copy2(str(TARGET_PY), str(backup_path))
    print(f"  [OK] Yedek: {backup_path.name}")

    # ============================================================
    # PATCH UYGULA
    # ============================================================
    print()
    print("=== PATCH UYGULAMA ===")

    # 1. Yeni SELECT bloku ekle
    yeni_content = content.replace(OLD_BLOCK, NEW_BLOCK, 1)
    if yeni_content == content:
        print("  [HATA] OLD_BLOCK replace etkisiz")
        return 1
    print("  [OK] kayit_listesi SELECT eklendi")

    # 2. Return jsonify'a kayit_listesi alani ekle
    yeni_content2 = yeni_content.replace(OLD_RETURN, NEW_RETURN, 1)
    if yeni_content2 == yeni_content:
        print("  [HATA] OLD_RETURN replace etkisiz")
        return 1
    print("  [OK] response'a 'kayit_listesi' alani eklendi")

    # ============================================================
    # YAZ
    # ============================================================
    print()
    print("=== DOSYAYA YAZMA ===")
    TARGET_PY.write_text(yeni_content2, encoding="utf-8")
    new_size = TARGET_PY.stat().st_size
    diff = new_size - original_size
    print(f"  [OK] Yeni boyut: {new_size} byte (fark: +{diff})")

    # ============================================================
    # DOGRULAMA
    # ============================================================
    print()
    print("=== DOGRULAMA ===")
    final = TARGET_PY.read_text(encoding="utf-8")

    checks = [
        ('FAZ 6.2', 'Yeni marker'),
        ('kayit_listesi = []', 'kayit_listesi list olusturma'),
        ("'kayit_listesi':", 'response anahtari'),
        ("WHERE onay_durum IN ('onaylandi', 'bekliyor')", 'filtre kurali'),
        ('LIMIT 200', 'LIMIT 200'),
        ('ORDER BY olusturma DESC', 'ORDER BY'),
        # Mevcut yapi korundu
        ('personel_bazli', 'personel_bazli korundu'),
        ('proses_bazli', 'proses_bazli korundu'),
        ('emir_bazli', 'emir_bazli korundu'),
        ('def hedef_rapor(', 'hedef_rapor fonksiyon var'),
        # Diger endpointler korundu
        ('def hedef_onayla(', 'onayla endpoint korundu'),
        ('def hedef_reddet(', 'reddet endpoint korundu'),
        ('def hedef_gecmis(', 'gecmis endpoint korundu'),
        ('def sapma(', 'sapma endpoint korundu'),
    ]
    all_ok = True
    for needle, desc in checks:
        ok = needle in final
        sym = "[OK]" if ok else "[HATA]"
        print(f"  {sym} {desc}")
        if not ok:
            all_ok = False

    if not all_ok:
        return 1

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
    print("[OK] FAZ 6.2 BACKEND RAPOR DETAY TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Flask RESTART (Python dosya degisti)")
    print("  2. Test:")
    print("     curl -c cookie.txt -d 'kullanici=admin&sifre=admin123' http://127.0.0.1:5057/giris")
    print("     curl -b cookie.txt http://127.0.0.1:5057/hedef/rapor")
    print("     -> response'da 'kayit_listesi': [...] olmali")
    print()
    print(f"Rollback (manuel):")
    print(f"  Copy-Item modules\\hedef\\{backup_path.name} modules\\hedef\\routes.py -Force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
