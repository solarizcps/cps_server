# -*- coding: utf-8 -*-
"""
CPS DEV - TASKS BREAKFIX (FAZ 6.1.3)
=====================================

GERCEK KOK SEBEP COZULDU:
  tasks.css icinde .tasks-table { min-width: 1200px; table-layout: fixed; }
  Bu kural responsive davranisi tamamen eziyordu.
  4 kolon gizlense bile tablo kendini 1200px+ genislige zorluyordu.

YAPILACAK:
  Mevcut FAZ 6.1.2 inline <style> bloku update edilir.
  
  1024px altinda:
    - 4 kolon display:none !important
    - .tasks-table {
        min-width: unset !important;     (1200px ezilir)
        width: 100% !important;
        table-layout: auto !important;   (fixed ezilir)
      }

DOKUNULMAYAN:
  - tasks.css core dosyasi (DOKUNULMAZ)
  - JS
  - Backend
  - block title
  - block content (HTML yapısı)
  - Diger sayfalar

Idempotent: 'FAZ 6.1.3' marker varsa SKIP.
Yedek: index.html.YEDEK_BREAKFIX_<ts>
"""
import sys
import re
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_HTML  = PROJECT_ROOT / "templates" / "tasks" / "index.html"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# YENI <style> BLOK (FAZ 6.1.3)
# ============================================================
NEW_STYLE = '''<style>
  /* FAZ 6.1.3 - Tasks responsive FIX (min-width:1200 ve table-layout:fixed override) */

  /* Tablet ve alti (1024px) - asil iyilestirme */
  @media (max-width: 1024px) {
    /* GIZLENEN 4 KOLON */
    .tasks-table .col-dept,
    .tasks-table .col-order,
    .tasks-table .col-creator,
    .tasks-table .col-updated {
      display: none !important;
    }

    /* tasks.css'deki min-width:1200px + table-layout:fixed override */
    .tasks-table {
      min-width: unset !important;
      width: 100% !important;
      table-layout: auto !important;
    }

    /* Wrap container - taşmayı içeride tut */
    .tasks-table-wrap {
      overflow-x: auto !important;
      -webkit-overflow-scrolling: touch;
      max-width: 100%;
    }
    .tasks-table-card {
      max-width: 100%;
      overflow: hidden;
    }
  }

  /* 768px ve alti - font/padding kuculme */
  @media (max-width: 768px) {
    .tasks-table {
      font-size: 12px;
    }
    .tasks-table th,
    .tasks-table td {
      padding: 4px 6px !important;
      white-space: normal;
    }
    .tasks-filter-grid,
    .tasks-form-row {
      grid-template-columns: 1fr !important;
    }
    .tasks-summary {
      flex-wrap: wrap;
    }
    .tasks-page-size-wrap {
      flex-wrap: wrap;
      gap: 6px;
    }
  }

  /* 480px ve alti - daha kucuk */
  @media (max-width: 480px) {
    .tasks-table {
      font-size: 11px;
    }
    .tasks-btn {
      padding: 6px 10px;
      font-size: 12px;
    }
  }
</style>'''


# ============================================================
# ESKI FAZ 6.1.2 BLOK PATTERN
# ============================================================
OLD_STYLE_REGEX = re.compile(
    r"<style>\s*\n?\s*/\*\s*FAZ 6\.1\.2[^*]*\*/.*?</style>",
    re.DOTALL
)


def main():
    print("=" * 60)
    print("CPS DEV - TASKS BREAKFIX (FAZ 6.1.3)")
    print("=" * 60)

    if not TARGET_HTML.exists():
        print(f"  [HATA] dosya yok: {TARGET_HTML}")
        return 1

    content = TARGET_HTML.read_text(encoding="utf-8")
    original_size = len(content.encode("utf-8"))
    print(f"  Mevcut boyut: {original_size} byte")

    # ============================================================
    # IDEMPOTENT KONTROL
    # ============================================================
    if 'FAZ 6.1.3' in content:
        print()
        print("  [SKIP] FAZ 6.1.3 marker var, breakfix zaten uygulanmis.")
        print("=" * 60)
        return 0

    # ============================================================
    # ON-KONTROL
    # ============================================================
    print()
    print("=== ON-KONTROL ===")

    if 'FAZ 6.1.2' not in content:
        print("  [HATA] FAZ 6.1.2 onceki patch yok. Patch sirasi bozuk.")
        return 1
    print("  [OK] FAZ 6.1.2 onceki patch tespit edildi")

    matches = OLD_STYLE_REGEX.findall(content)
    print(f"  Eslesen FAZ 6.1.2 <style> blok sayisi: {len(matches)}")
    if len(matches) != 1:
        print(f"  [HATA] Tek FAZ 6.1.2 style blok beklenir, {len(matches)} bulundu")
        if len(matches) == 0:
            # Yardimci: ilk 200 char goster
            idx = content.find('FAZ 6.1.2')
            if idx >= 0:
                start = max(0, idx-100)
                snippet = content[start:idx+300]
                print(f"       FAZ 6.1.2 etrafi: {snippet[:300]!r}")
        return 1
    print("  [OK] Mevcut FAZ 6.1.2 style blok ESSIZ")

    # block head icinde mi (sigli kontrol)
    head_block_match = re.search(
        r"({%\s*block\s+head\s*%})(.*?)({%\s*endblock\s*%})",
        content, re.DOTALL
    )
    if head_block_match:
        head_inner = head_block_match.group(2)
        if 'FAZ 6.1.2' in head_inner:
            print("  [OK] FAZ 6.1.2 block head icinde (dogru yer)")
        else:
            print("  [UYARI] FAZ 6.1.2 block head disinda - yine de devam")

    # ============================================================
    # YEDEK
    # ============================================================
    backup_path = TARGET_HTML.with_suffix(f".html.YEDEK_BREAKFIX_{ts}")
    print()
    print("=== YEDEK ===")
    shutil.copy2(str(TARGET_HTML), str(backup_path))
    print(f"  [OK] Yedek: {backup_path.name}")

    # ============================================================
    # PATCH UYGULA - REPLACE
    # ============================================================
    print()
    print("=== PATCH UYGULAMA ===")

    yeni_content = OLD_STYLE_REGEX.sub(NEW_STYLE, content, count=1)
    
    if yeni_content == content:
        print("  [HATA] Replace etkisiz")
        return 1
    print("  [OK] Eski FAZ 6.1.2 style blok DEGISTIRILDI")
    print("  [OK] Yeni FAZ 6.1.3 - min-width override eklendi")
    print("  [OK] table-layout: auto !important eklendi")

    # ============================================================
    # YAZ
    # ============================================================
    print()
    print("=== DOSYAYA YAZMA ===")
    TARGET_HTML.write_text(yeni_content, encoding="utf-8")
    new_size = TARGET_HTML.stat().st_size
    diff = new_size - original_size
    print(f"  [OK] Yeni boyut: {new_size} byte (fark: {'+' if diff >= 0 else ''}{diff})")

    # ============================================================
    # DOGRULAMA
    # ============================================================
    print()
    print("=== DOGRULAMA ===")
    final = TARGET_HTML.read_text(encoding="utf-8")

    checks = [
        ('FAZ 6.1.3', 'Yeni marker'),
        ('@media (max-width: 1024px)', '1024px breakpoint'),
        ('display: none !important', 'display:none !important'),
        ('min-width: unset !important', 'min-width unset override (kritik)'),
        ('table-layout: auto !important', 'table-layout auto override (kritik)'),
        ('width: 100% !important', 'width 100% override'),
        ('.col-dept,', 'col-dept gizleme'),
        ('.col-order,', 'col-order gizleme'),
        ('.col-creator,', 'col-creator gizleme'),
        ('.col-updated', 'col-updated gizleme'),
        ('@media (max-width: 768px)', '768px breakpoint'),
        ('@media (max-width: 480px)', '480px breakpoint'),
        ('overflow-x: auto !important', 'wrap overflow !important'),
        # HTML yapısı korundu
        ('Gorevler - Solariz CPS', 'sayfa basligi (block title)'),
        ('class="tasks-table-wrap"', 'tasks-table-wrap'),
        ('class="tasks-table"', 'tasks-table'),
        ('id="tasks-table"', 'tasks-table ID'),
        ('class="col-dept', 'col-dept HTML'),
        ('class="col-order', 'col-order HTML'),
        ('class="col-creator', 'col-creator HTML'),
        ('class="col-updated', 'col-updated HTML'),
        ('colspan="11"', 'colspan=11'),
        ('fonts.googleapis.com', 'Google Fonts korundu'),
        ("url_for('static', filename='css/tasks.css')", 'tasks.css link korundu'),
    ]
    all_ok = True
    for needle, desc in checks:
        ok = needle in final
        sym = "[OK]" if ok else "[HATA]"
        print(f"  {sym} {desc}")
        if not ok:
            all_ok = False

    # Eski FAZ 6.1.2 marker olmamali
    if 'FAZ 6.1.2' in final:
        print("  [HATA] Eski FAZ 6.1.2 marker hala var")
        all_ok = False
    else:
        print("  [OK] Eski FAZ 6.1.2 marker temizlendi")

    # <style> tag dengesi
    style_open = final.count('<style>')
    style_close = final.count('</style>')
    print(f"  <style> tag: open={style_open}, close={style_close}")
    if style_open != 1 or style_close != 1:
        print("  [HATA] <style> tag dengesi bozuk")
        all_ok = False

    # block dengesi
    block_open = len(re.findall(r"{%\s*block\s+\w+\s*%}", final))
    block_close = len(re.findall(r"{%\s*endblock\s*%}", final))
    print(f"  Jinja block: open={block_open}, close={block_close}")
    if block_open != block_close:
        print("  [HATA] Jinja block dengesi bozuk")
        all_ok = False

    if not all_ok:
        return 1

    # ============================================================
    # JINJA SYNTAX
    # ============================================================
    print()
    print("=== JINJA SYNTAX KONTROL ===")
    try:
        from jinja2 import Environment
        env = Environment()
        env.parse(final)
        print("  [OK] Jinja parse sorunsuz")
    except ImportError:
        print("  [SKIP] jinja2 yok")
    except Exception as e:
        print(f"  [HATA] Jinja: {e}")
        return 1

    print()
    print("=" * 60)
    print("[OK] FAZ 6.1.3 BREAKFIX TAMAM")
    print("=" * 60)
    print()
    print("ANAHTAR DEGISIKLIK:")
    print("  tasks.css'deki min-width:1200px + table-layout:fixed")
    print("  artık 1024px altinda EZILIYOR (override)")
    print()
    print("Sonraki:")
    print("  1. Tarayicida Ctrl+Shift+R")
    print("  2. Tablette test:")
    print("     - 4 kolon gizli mi")
    print("     - Tablo ekrana oturdu mu (scroll ciddi azaldi mi)")
    print("  3. Masaustu:")
    print("     - 1024px uzerinde 11 kolon hala gorunur")
    print()
    print(f"Rollback (manuel):")
    print(f"  Copy-Item templates\\tasks\\{backup_path.name} templates\\tasks\\index.html -Force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
