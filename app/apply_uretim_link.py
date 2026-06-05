# -*- coding: utf-8 -*-
"""
CPS DEV - SIDEBAR /uretim/ LINK EKLE
=====================================

Sadece templates/base.html'e dokunulur.

Yapilan:
  1. Planlama grubu sn-count: 2 -> 3
  2. Karar Masasi <a> blogundan sonra yeni <a href="/uretim/"> blogu

DOKUNULMAYAN:
  - Diger sidebar gruplari
  - JS / CSS / DB / Routes
  - Faz 3 overlay
  - Sablon / Hedef / Korgun

Idempotent: Eger /uretim/ linki zaten varsa SKIP.
"""
import sys
import re
import shutil
import hashlib
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
BASE_HTML    = PROJECT_ROOT / "templates" / "base.html"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


def main():
    print("=" * 60)
    print("CPS DEV - SIDEBAR /uretim/ LINK EKLE")
    print("=" * 60)

    if not BASE_HTML.exists():
        print(f"  [HATA] base.html yok: {BASE_HTML}")
        return 1

    # UTF-8 oku
    content = BASE_HTML.read_text(encoding="utf-8")
    original_size = len(content.encode("utf-8"))
    print(f"  Mevcut boyut: {original_size} byte")

    # ============================================================
    # IDEMPOTENT KONTROL
    # ============================================================
    if 'href="/uretim/"' in content:
        print()
        print("  [SKIP] Sidebar'da /uretim/ linki ZATEN VAR.")
        # Detay
        m = re.search(r'href="/uretim/"[^>]*>', content)
        if m:
            print(f"  Mevcut tag: {m.group(0)[:120]}...")
        print()
        print("=" * 60)
        print("[OK] PATCH ZATEN UYGULANMIS")
        print("=" * 60)
        return 0

    # ============================================================
    # ON-KONTROLLER (anchor noktalari)
    # ============================================================
    # 1. Planlama grubu var mi
    if 'data-grup="planlama"' not in content:
        print("  [HATA] Planlama grubu (data-grup=\"planlama\") bulunamadi.")
        return 1

    # 2. sn-count="2" Planlama yakininda mi?
    # Karar Masasi <a> bloku
    karar_pattern = re.compile(
        r'(<a href="/planlama/karar-masasi"[^>]*>.*?</a>)',
        re.DOTALL
    )
    karar_match = karar_pattern.search(content)
    if not karar_match:
        print("  [HATA] Karar Masasi <a> blogu bulunamadi.")
        return 1

    karar_block = karar_match.group(1)
    karar_end = karar_match.end()
    print(f"  [OK] Karar Masasi anchor bulundu (sat ~730)")
    print(f"       Karar Masasi <a> blogu sonu: char index {karar_end}")

    # 3. sn-count icindeki 2 sayisini bul (Planlama grubu)
    # Pattern: data-grup="planlama" ... <span class="sn-count">2</span>
    count_pattern = re.compile(
        r'(<div class="sn-sec sn-toggle[^"]*"[^>]*data-grup="planlama"[^>]*>.*?<span class="sn-count">)(\d+)(</span>)',
        re.DOTALL
    )
    count_match = count_pattern.search(content)
    if not count_match:
        print("  [HATA] Planlama sn-count span bulunamadi.")
        return 1

    eski_count = int(count_match.group(2))
    yeni_count = eski_count + 1
    print(f"  [OK] Planlama sn-count bulundu: {eski_count} -> {yeni_count}")

    # ============================================================
    # YEDEK
    # ============================================================
    backup_path = BASE_HTML.with_suffix(f".html.YEDEK_LINK_{ts}")
    print()
    print("=== YEDEK ===")
    shutil.copy2(str(BASE_HTML), str(backup_path))
    print(f"  [OK] Yedek: {backup_path.name}")
    print(f"       Boyut: {backup_path.stat().st_size} byte")

    # ============================================================
    # YENI LINK BLOGU
    # ============================================================
    yeni_link = (
        '\n\n'
        '        <a href="/uretim/" class="si {% if \'/uretim/\' in rp %}active{% endif %}" title="Üretim Girişi">\n'
        '          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7l9-4 9 4-9 4-9-4z"/><path d="M3 7v10l9 4 9-4V7"/></svg></span>\n'
        '          <span class="sl">Üretim Girişi</span>\n'
        '        </a>'
    )

    # ============================================================
    # 1. INSERT - Karar Masasi sonuna yeni <a> ekle
    # ============================================================
    print()
    print("=== INSERT: yeni <a href=\"/uretim/\"> blogu ===")
    yeni_content = content[:karar_end] + yeni_link + content[karar_end:]

    # ============================================================
    # 2. UPDATE - sn-count: 2 -> 3
    # ============================================================
    print("=== UPDATE: sn-count ===")
    # count_match yeni_content'te aynı pozisyonda DEGIL artik (insert yapildi)
    # Ama Planlama grubu Karar Masasi'ndan ONCE olduğu için hala dogru pozisyonda
    # Yine de yeniden match yapalim:
    count_match2 = count_pattern.search(yeni_content)
    if not count_match2:
        print("  [HATA] sn-count yeniden bulunamadi (insert sonrasi)")
        return 1

    yeni_content = (
        yeni_content[:count_match2.start(2)]
        + str(yeni_count)
        + yeni_content[count_match2.end(2):]
    )
    print(f"  [OK] sn-count: {eski_count} -> {yeni_count}")

    # ============================================================
    # YAZ
    # ============================================================
    print()
    print("=== DOSYAYA YAZMA ===")
    BASE_HTML.write_text(yeni_content, encoding="utf-8")
    new_size = BASE_HTML.stat().st_size
    diff = new_size - original_size
    print(f"  [OK] Yeni boyut: {new_size} byte (fark: +{diff})")

    # ============================================================
    # DOGRULAMA
    # ============================================================
    print()
    print("=== DOGRULAMA ===")
    final = BASE_HTML.read_text(encoding="utf-8")

    checks = [
        ('href="/uretim/"', 'Yeni link var mi'),
        ('Üretim Girişi', 'Link metni dogru mu (UTF-8)'),
        ('<span class="sl">Üretim Girişi</span>', 'sl span dogru mu'),
        (f'<span class="sn-count">{yeni_count}</span>', f'sn-count {yeni_count} oldu mu'),
        ('href="/planlama/proses-takip"', 'Proses Takip korundu mu'),
        ('href="/planlama/karar-masasi"', 'Karar Masasi korundu mu'),
    ]
    all_ok = True
    for needle, desc in checks:
        ok = needle in final
        sym = "[OK]" if ok else "[HATA]"
        print(f"  {sym} {desc}")
        if not ok:
            all_ok = False

    if not all_ok:
        print()
        print("  [UYARI] Bazi kontroller basarisiz - yedekten geri yukleme onerilir")
        return 1

    # /uretim/ link sayisi (1 olmali)
    sayi = final.count('href="/uretim/"')
    print(f"  /uretim/ link sayisi: {sayi} (1 olmali)")
    if sayi != 1:
        print("  [UYARI] Beklenenden farkli sayida link var")
        return 1

    print()
    print("=" * 60)
    print("[OK] SIDEBAR /uretim/ LINK EKLENDI")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Tarayicida hard refresh: Ctrl+Shift+R")
    print("  2. Sidebar'da Planlama altinda 'Uretim Girisi' linki gorunmeli")
    print("  3. Tikla -> /uretim/ acilmali")
    print()
    print("Rollback (manuel, gerekirse):")
    print(f"  Copy-Item {backup_path.name} base.html -Force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
