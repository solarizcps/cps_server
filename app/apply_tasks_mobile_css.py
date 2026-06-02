# -*- coding: utf-8 -*-
"""
CPS DEV - TASKS MOBIL CSS (FAZ 6.1)
====================================

Sadece templates/tasks/index.html'a dokunulur.
Sadece <style> bloğu eklenir (CSS injection).

YAPILACAK:
  - tasks-table-wrap: overflow-x: auto + touch scrolling
  - @media (max-width: 768px): font/padding kuculme
  - min-width tabloya: 800px (mobilde scroll devreye girsin)
  - .tasks-table-card max-width: 100%

DOKUNULMAYAN:
  - HTML yapisi (tasks-table-wrap zaten var)
  - tasks.js
  - Diger sayfalar (CSS scoped: .tasks-* selector'leri)

Idempotent: 'FAZ 6.1' marker varsa SKIP.
Yedek: index.html.YEDEK_TASKSCSS_<ts>
"""
import sys
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_HTML  = PROJECT_ROOT / "templates" / "tasks" / "index.html"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# EKLENECEK STYLE BLOK
# ============================================================
NEW_STYLE = '''<style>
/* FAZ 6.1 - Tasks mobil CSS injection */
.tasks-table-wrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  max-width: 100%;
  -webkit-overflow-scrolling: touch;
}
.tasks-table-card {
  max-width: 100%;
  overflow: hidden;
}
@media (max-width: 768px) {
  .tasks-table {
    font-size: 12px;
    min-width: 800px;
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


def main():
    print("=" * 60)
    print("CPS DEV - TASKS MOBIL CSS (FAZ 6.1)")
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
    if 'FAZ 6.1' in content or 'FAZ 6.1 - Tasks mobil' in content:
        print()
        print("  [SKIP] FAZ 6.1 marker var, mobil CSS zaten uygulanmis.")
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

    # tasks-table-wrap class'i var mi
    if 'tasks-table-wrap' not in content:
        print("  [HATA] 'tasks-table-wrap' class'i bulunamadi")
        return 1
    print("  [OK] tasks-table-wrap class mevcut (HTML yapisi sağlam)")

    # tasks-table class'i var mi
    if 'class="tasks-table"' not in content:
        print("  [HATA] tasks-table class'i bulunamadi")
        return 1
    print("  [OK] tasks-table class mevcut")

    # Anchor: ya {% extends %} sonu ya da ilk satira yakin yerleştirelim
    # Daha guvenli: ilk anchor noktasi ara
    
    # Eğer "{% block content %}" varsa onun hemen ardına
    # Yoksa dosyanin basina (ilk HTML elementi öncesi)
    
    if "{% block " in content:
        # Block sonrasi ilk satir
        m_block = content.find('{% block ')
        m_block_end = content.find('%}', m_block)
        if m_block_end > 0:
            # Block etiketi sonrasi insert et
            anchor = content[m_block:m_block_end+2]
            print(f"  [OK] Anchor: '{anchor[:60]}...' bulundu")
            anchor_pos = m_block_end + 2
        else:
            print("  [HATA] block etiketi tamamlanamadi")
            return 1
    else:
        # Block yoksa dosya basina ekle
        anchor_pos = 0
        print("  [INFO] {% block %} yok, dosya basina eklenecek")

    # ============================================================
    # YEDEK
    # ============================================================
    backup_path = TARGET_HTML.with_suffix(f".html.YEDEK_TASKSCSS_{ts}")
    print()
    print("=== YEDEK ===")
    shutil.copy2(str(TARGET_HTML), str(backup_path))
    print(f"  [OK] Yedek: {backup_path.name}")
    print(f"       Boyut: {backup_path.stat().st_size} byte")

    # ============================================================
    # PATCH UYGULA
    # ============================================================
    print()
    print("=== PATCH UYGULAMA ===")

    # Style bloğunu anchor sonrasina insert et
    yeni_content = content[:anchor_pos] + '\n' + NEW_STYLE + content[anchor_pos:]
    
    if yeni_content == content:
        print("  [HATA] Insert etkisiz")
        return 1
    print("  [OK] Style bloku dosya basina eklendi")
    print("  [OK] tasks-table-wrap overflow-x:auto")
    print("  [OK] @media (max-width: 768px) eklendi")
    print("  [OK] @media (max-width: 480px) eklendi")

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
        ('FAZ 6.1', 'Yeni marker var mi'),
        ('overflow-x: auto', 'tasks-table-wrap overflow-x kuralı'),
        ('-webkit-overflow-scrolling: touch', 'iOS smooth scroll'),
        ('@media (max-width: 768px)', '768px breakpoint'),
        ('@media (max-width: 480px)', '480px breakpoint'),
        ('min-width: 800px', 'tablo min-width (mobilde scroll için)'),
        # Mevcut yapilar KORUNDU mu
        ('tasks-table-wrap', 'wrap class korundu'),
        ('class="tasks-table"', 'tablo class korundu'),
        ('id="tasks-table"', 'tablo ID korundu'),
        ('tasks-summary', 'tasks-summary korundu'),
        ('tasks-filter-grid', 'tasks-filter-grid korundu'),
        ('tasks-btn-yenile', 'yenile butonu korundu'),
        ('tasks-btn-yeni', 'yeni gorev butonu korundu'),
    ]
    all_ok = True
    for needle, desc in checks:
        ok = needle in final
        sym = "[OK]" if ok else "[HATA]"
        print(f"  {sym} {desc}")
        if not ok:
            all_ok = False

    # <style> tag sayisi 1 olmali (yenisi eklendi)
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
        print("  [SKIP] jinja2 yok, syntax atlandi")
    except Exception as e:
        print(f"  [UYARI] Jinja: {e}")

    print()
    print("=" * 60)
    print("[OK] FAZ 6.1 TASKS MOBIL CSS PATCH TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Flask hot reload (Jinja template, restart gerekmez)")
    print("  2. Tarayicida hard refresh: Ctrl+Shift+R")
    print("  3. Test:")
    print("     - Masaustu /tasks: gorunum bozulmadi mi")
    print("     - Tablet /tasks: tablo ekrani tasirsa kaydirma calisiyor mu")
    print("     - Sayfanin tamami kayiyor mu (HAYIR olmali)")
    print()
    print(f"Rollback (manuel, gerekirse):")
    print(f"  Copy-Item templates\\tasks\\{backup_path.name} templates\\tasks\\index.html -Force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
