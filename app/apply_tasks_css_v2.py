# -*- coding: utf-8 -*-
"""
CPS DEV - TASKS CSS V2 - 4 KOLON GIZLE (FAZ 6.1.1)
====================================================

Sadece templates/tasks/index.html'a dokunulur.
Mevcut FAZ 6.1 <style> bloğunu YENİSİ ile DEĞİŞTİRİR.

YAPILACAK:
  1024px altında 4 kolon gizlenir:
    - .col-dept     (Departman)
    - .col-order    (Siparis)
    - .col-creator  (Olusturan)
    - .col-updated  (Guncelleme)
  
  Tablet/mobil min-width 800 -> 600 (7 kolon yeterli)

DOKUNULMAYAN:
  - HTML yapisi
  - tasks.js (colspan=11 KORUNUR, gizleme DOM disi degil sadece display:none)
  - Sort, filter, pagination
  - Backend
  - Diger sayfalar (CSS scoped to .tasks-table)

Idempotent: 'FAZ 6.1.1' marker varsa SKIP.
Yedek: index.html.YEDEK_TASKSCSS_V2_<ts>
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
# YENI <style> BLOGU
# ============================================================
NEW_STYLE = '''<style>
/* FAZ 6.1.1 - Tasks mobil/tablet CSS - 4 kolon gizle */
.tasks-table-wrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  max-width: 100%;
}
.tasks-table-card {
  max-width: 100%;
  overflow: hidden;
}

/* Tablet ve alti: 4 kolonu gizle (Departman, Siparis, Olusturan, Guncelleme) */
@media (max-width: 1024px) {
  .tasks-table .col-dept,
  .tasks-table .col-order,
  .tasks-table .col-creator,
  .tasks-table .col-updated {
    display: none;
  }
  .tasks-table {
    min-width: 600px;
  }
}

/* 768px ve alti - font/padding kuculme */
@media (max-width: 768px) {
  .tasks-table {
    font-size: 12px;
    min-width: 600px;
  }
  .tasks-table th,
  .tasks-table td {
    padding: 4px 6px;
    white-space: nowrap;
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
</style>
'''

# ============================================================
# ESKI FAZ 6.1 BLOK PATTERN (replace icin)
# ============================================================
# Mevcut blok 'FAZ 6.1 - Tasks mobil' marker ile basliyor
# <style> ile baslayan + </style> ile biten blogun TAMAMINI eslestir
OLD_STYLE_REGEX = re.compile(
    r"<style>\s*\n?/\*\s*FAZ 6\.1[^*]*\*/.*?</style>\s*\n?",
    re.DOTALL
)


def main():
    print("=" * 60)
    print("CPS DEV - TASKS CSS V2 - 4 KOLON GIZLE (FAZ 6.1.1)")
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
    if 'FAZ 6.1.1' in content:
        print()
        print("  [SKIP] FAZ 6.1.1 marker var, kolon gizleme zaten uygulanmis.")
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

    if 'FAZ 6.1' not in content:
        print("  [HATA] FAZ 6.1 onceki patch yok. Once apply_tasks_mobile_css.py calistir.")
        return 1
    print("  [OK] FAZ 6.1 onceki patch mevcut")

    # Mevcut style blok eslesmesi
    matches = OLD_STYLE_REGEX.findall(content)
    print(f"  Eslesen FAZ 6.1 <style> blok sayisi: {len(matches)}")
    if len(matches) != 1:
        print(f"  [HATA] Tek bir FAZ 6.1 style blok beklenir, {len(matches)} bulundu")
        if len(matches) == 0:
            print("       Pattern eslesmedi. Manuel inceleme gerek.")
        return 1
    print("  [OK] Mevcut FAZ 6.1 style blok ESSIZ")

    # Class kontrol (col-dept, col-order, col-creator, col-updated)
    required_classes = ['col-dept', 'col-order', 'col-creator', 'col-updated']
    for cls in required_classes:
        if cls not in content:
            print(f"  [HATA] '.{cls}' class HTML'de bulunamadi - kolon gizleme calismaz")
            return 1
        else:
            print(f"  [OK] .{cls} class mevcut")

    # ============================================================
    # YEDEK
    # ============================================================
    backup_path = TARGET_HTML.with_suffix(f".html.YEDEK_TASKSCSS_V2_{ts}")
    print()
    print("=== YEDEK ===")
    shutil.copy2(str(TARGET_HTML), str(backup_path))
    print(f"  [OK] Yedek: {backup_path.name}")
    print(f"       Boyut: {backup_path.stat().st_size} byte")

    # ============================================================
    # PATCH UYGULA - REPLACE
    # ============================================================
    print()
    print("=== PATCH UYGULAMA ===")

    yeni_content = OLD_STYLE_REGEX.sub(NEW_STYLE, content, count=1)
    
    if yeni_content == content:
        print("  [HATA] Replace etkisiz")
        return 1
    print("  [OK] Eski FAZ 6.1 style blok DEGISTIRILDI")
    print("  [OK] Yeni FAZ 6.1.1 style blok yerlesti")
    print("  [OK] 1024px breakpoint - 4 kolon gizle eklendi")

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
        ('FAZ 6.1.1', 'Yeni marker var mi'),
        ('@media (max-width: 1024px)', '1024px breakpoint'),
        ('.col-dept,', 'Departman gizleme kurali'),
        ('.col-order,', 'Siparis gizleme kurali'),
        ('.col-creator,', 'Olusturan gizleme kurali'),
        ('.col-updated', 'Guncelleme gizleme kurali'),
        ('@media (max-width: 768px)', '768px breakpoint'),
        ('@media (max-width: 480px)', '480px breakpoint'),
        ('overflow-x: auto', 'wrap overflow korundu'),
        ('-webkit-overflow-scrolling: touch', 'iOS scroll korundu'),
        ('min-width: 600px', '7 kolon icin min-width'),
        # Eski FAZ 6.1 marker'i artik OLMAMALI
        # Mevcut yapi KORUNDU mu
        ('class="tasks-table-wrap"', 'wrap class korundu'),
        ('class="tasks-table"', 'tablo class korundu'),
        ('id="tasks-table"', 'tablo ID korundu'),
        ('col-dept', 'col-dept HTML korundu'),
        ('col-order', 'col-order HTML korundu'),
        ('col-creator', 'col-creator HTML korundu'),
        ('col-updated', 'col-updated HTML korundu'),
        ('colspan="11"', 'colspan=11 korundu (bos mesaj icin)'),
        ('tasks-summary', 'tasks-summary korundu'),
    ]
    all_ok = True
    for needle, desc in checks:
        ok = needle in final
        sym = "[OK]" if ok else "[HATA]"
        print(f"  {sym} {desc}")
        if not ok:
            all_ok = False

    # Eski FAZ 6.1 olmamali (olmadiginin onayi olarak: spesifik eski string)
    if 'FAZ 6.1 - Tasks mobil CSS injection' in final:
        print("  [HATA] Eski FAZ 6.1 marker hala var! Replace tam olmadi.")
        all_ok = False
    else:
        print("  [OK] Eski FAZ 6.1 marker temizlendi")

    # <style> tag dengesi
    style_open = final.count('<style>')
    style_close = final.count('</style>')
    print(f"  <style> tag: open={style_open}, close={style_close}")
    if style_open != style_close:
        print("  [HATA] <style> tag dengesi bozuk")
        all_ok = False

    if not all_ok:
        print()
        print("  [UYARI] Bazi dogrulamalar basarisiz")
        return 1

    # ============================================================
    # JINJA SYNTAX BASIT KONTROL
    # ============================================================
    print()
    print("=== JINJA SYNTAX BASIT KONTROL ===")
    try:
        from jinja2 import Environment
        env = Environment()
        env.parse(final)
        print("  [OK] Jinja parse sorunsuz")
    except ImportError:
        print("  [SKIP] jinja2 yok")
    except Exception as e:
        print(f"  [UYARI] Jinja: {e}")

    print()
    print("=" * 60)
    print("[OK] FAZ 6.1.1 - 4 KOLON GIZLEME PATCH TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Tarayicida Ctrl+Shift+R (hot reload)")
    print("  2. Test:")
    print("     - Masaustu Chrome (>1024px): 11 kolon hepsi gorunur")
    print("     - Tablet/Chrome devtools (1024px ve alti): 7 kolon")
    print("     - Mobil (768px ve alti): 7 kolon kucuk font")
    print("  3. Gizlenen kolonlar:")
    print("     - Departman, Siparis, Olusturan, Guncelleme")
    print()
    print(f"Rollback:")
    print(f"  Copy-Item templates\\tasks\\{backup_path.name} templates\\tasks\\index.html -Force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
