# -*- coding: utf-8 -*-
"""
CPS DEV - TASKS TITLE FIX (FAZ 6.1.2)
======================================

ONCEKI HATAYI DUZELTIR:
  FAZ 6.1.1 patch <style> bloğunu yanlislikla {% block title %} icine yerlestirdi.
  Tarayici sekme adi "<style> /* FAZ 6.1.1 ... */" gozukuyor.

YAPILACAK:
  1. {% block title %} icinde sadece "Gorevler - Solariz CPS" kalsin
  2. <style>...60 satir CSS...</style> bloku {% block head %} icine 
     (mevcut link'lerin SONUNA) tasinsin
  3. Marker FAZ 6.1.1 -> FAZ 6.1.2 (yeni)
  4. CSS kurallari AYNI (sadece YERI degisiyor)

DOKUNULMAYAN:
  - HTML body
  - tasks.js
  - block content / block scripts
  - Tum mevcut <link> etiketleri korunur
  - Backend
  - Diger sayfalar

Idempotent: 'FAZ 6.1.2' marker varsa SKIP.
Yedek: index.html.YEDEK_TITLEFIX_<ts>
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
# YENI <style> BLOK (FAZ 6.1.2 marker ile)
# ============================================================
NEW_STYLE = '''<style>
/* FAZ 6.1.2 - Tasks mobil/tablet CSS - 4 kolon gizle (block head'de) */
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
</style>'''


def main():
    print("=" * 60)
    print("CPS DEV - TASKS TITLE FIX (FAZ 6.1.2)")
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
    if 'FAZ 6.1.2' in content:
        print()
        print("  [SKIP] FAZ 6.1.2 marker var, title fix zaten uygulanmis.")
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

    if 'FAZ 6.1.1' not in content:
        print("  [HATA] FAZ 6.1.1 marker yok. Patch sirasi bozuk.")
        return 1
    print("  [OK] FAZ 6.1.1 onceki patch tespit edildi")

    # block title icinde <style> var mi (bug burada)
    title_block_re = re.compile(
        r"({%\s*block\s+title\s*%})(.*?)({%\s*endblock\s*%})",
        re.DOTALL
    )
    title_match = title_block_re.search(content)
    if not title_match:
        print("  [HATA] {% block title %} bulunamadi")
        return 1
    
    title_content = title_match.group(2)
    if '<style>' not in title_content:
        print("  [SKIP] block title'da <style> yok, fix gerekmez")
        return 0
    print("  [OK] block title icinde <style> tespit edildi (bug yeri)")
    
    # Gercek title metni - "Gorevler - Solariz CPS"
    if 'Gorevler - Solariz CPS' not in title_content:
        print("  [HATA] 'Gorevler - Solariz CPS' title metni bulunamadi")
        return 1
    print("  [OK] 'Gorevler - Solariz CPS' title metni mevcut")

    # block head var mi
    head_block_re = re.compile(
        r"({%\s*block\s+head\s*%})(.*?)({%\s*endblock\s*%})",
        re.DOTALL
    )
    head_match = head_block_re.search(content)
    if not head_match:
        print("  [HATA] {% block head %} bulunamadi")
        return 1
    print("  [OK] {% block head %} mevcut (style buraya tasinacak)")

    # ============================================================
    # YEDEK
    # ============================================================
    backup_path = TARGET_HTML.with_suffix(f".html.YEDEK_TITLEFIX_{ts}")
    print()
    print("=== YEDEK ===")
    shutil.copy2(str(TARGET_HTML), str(backup_path))
    print(f"  [OK] Yedek: {backup_path.name}")

    # ============================================================
    # PATCH 1: block title duzelt
    # ============================================================
    print()
    print("=== PATCH 1: block title temizle ===")

    new_title = title_match.group(1) + 'Gorevler - Solariz CPS' + title_match.group(3)
    yeni_content = (
        content[:title_match.start()] +
        new_title +
        content[title_match.end():]
    )
    
    if yeni_content == content:
        print("  [HATA] Title replace etkisiz")
        return 1
    print("  [OK] block title icerigi: 'Gorevler - Solariz CPS'")

    # ============================================================
    # PATCH 2: block head'e style bloku ekle
    # ============================================================
    print()
    print("=== PATCH 2: block head'e style ekle ===")

    # Yeni content'te tekrar head bloku bul (offset degisti)
    head_match2 = head_block_re.search(yeni_content)
    if not head_match2:
        print("  [HATA] block head 2. arama basarisiz")
        return 1
    
    # Mevcut head icerigini koru, sonuna NEW_STYLE ekle
    head_open  = head_match2.group(1)
    head_inner = head_match2.group(2)
    head_close = head_match2.group(3)
    
    # head_inner sonunda whitespace varsa koru, NEW_STYLE'i once tek satir bos sonra style olarak ekle
    new_head_inner = head_inner.rstrip() + '\n\n  ' + NEW_STYLE + '\n\n'
    new_head = head_open + new_head_inner + head_close
    
    yeni_content2 = (
        yeni_content[:head_match2.start()] +
        new_head +
        yeni_content[head_match2.end():]
    )
    
    if yeni_content2 == yeni_content:
        print("  [HATA] Head replace etkisiz")
        return 1
    print("  [OK] <style> bloku block head'e eklendi (link'lerden sonra)")

    # ============================================================
    # YAZ
    # ============================================================
    print()
    print("=== DOSYAYA YAZMA ===")
    TARGET_HTML.write_text(yeni_content2, encoding="utf-8")
    new_size = TARGET_HTML.stat().st_size
    diff = new_size - original_size
    print(f"  [OK] Yeni boyut: {new_size} byte (fark: {'+' if diff >= 0 else ''}{diff})")

    # ============================================================
    # DOGRULAMA
    # ============================================================
    print()
    print("=== DOGRULAMA ===")
    final = TARGET_HTML.read_text(encoding="utf-8")

    # block title kontrol
    final_title = title_block_re.search(final)
    if final_title:
        title_inner = final_title.group(2).strip()
        print(f"  block title icerik: '{title_inner[:80]}'")
        if title_inner == 'Gorevler - Solariz CPS':
            print("  [OK] block title temiz, sadece metin")
        else:
            print("  [HATA] block title icinde fazla icerik")
            return 1
    
    # block title'da <style> KESIN OLMAMALI
    if final_title and '<style>' in final_title.group(2):
        print("  [HATA] block title icinde hala <style> var")
        return 1
    print("  [OK] block title icinde <style> YOK")
    
    # block head'de <style> VAR olmali
    final_head = head_block_re.search(final)
    if final_head and '<style>' in final_head.group(2):
        print("  [OK] block head icinde <style> VAR")
    else:
        print("  [HATA] block head icinde <style> YOK")
        return 1

    # block head mevcut link'leri korundu mu
    if 'fonts.googleapis.com' in final_head.group(2) and 'tasks.css' in final_head.group(2):
        print("  [OK] block head'deki link'ler korundu")
    else:
        print("  [HATA] block head'deki link'ler eksik")
        return 1

    checks = [
        ('FAZ 6.1.2', 'Yeni marker'),
        ('@media (max-width: 1024px)', '1024px breakpoint'),
        ('.col-dept,', 'Departman gizleme'),
        ('.col-order,', 'Siparis gizleme'),
        ('.col-creator,', 'Olusturan gizleme'),
        ('.col-updated', 'Guncelleme gizleme'),
        ('overflow-x: auto', 'wrap overflow'),
        ('@media (max-width: 768px)', '768px breakpoint'),
        ('@media (max-width: 480px)', '480px breakpoint'),
        ('Gorevler - Solariz CPS', 'Sayfa basligi metni'),
        # HTML yapisi korundu mu
        ('class="tasks-table-wrap"', 'tasks-table-wrap'),
        ('class="tasks-table"', 'tasks-table'),
        ('id="tasks-table"', 'tasks-table ID'),
        ('class="col-dept', 'col-dept HTML'),
        ('class="col-order', 'col-order HTML'),
        ('class="col-creator', 'col-creator HTML'),
        ('class="col-updated', 'col-updated HTML'),
        ('colspan="11"', 'colspan=11'),
        ('tasks-summary', 'tasks-summary'),
        # Mevcut link'ler korundu
        ('fonts.googleapis.com', 'Google Fonts'),
        ("url_for('static', filename='css/tasks.css')", 'tasks.css'),
        # Eski yanlis FAZ 6.1.1 marker'i artik OLMAMALI
    ]
    all_ok = True
    for needle, desc in checks:
        ok = needle in final
        sym = "[OK]" if ok else "[HATA]"
        print(f"  {sym} {desc}")
        if not ok:
            all_ok = False

    # Eski FAZ 6.1.1 marker olmamali
    if 'FAZ 6.1.1' in final:
        print("  [HATA] Eski FAZ 6.1.1 marker hala var")
        all_ok = False
    else:
        print("  [OK] Eski FAZ 6.1.1 marker temizlendi (FAZ 6.1.2 ile replace)")

    # <style> tag dengesi
    style_open = final.count('<style>')
    style_close = final.count('</style>')
    print(f"  <style> tag: open={style_open}, close={style_close}")
    if style_open != 1 or style_close != 1:
        print("  [HATA] <style> tag dengesi bozuk (1 olmali)")
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
    # JINJA SYNTAX BASIT KONTROL
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
    print("[OK] FAZ 6.1.2 TITLE FIX TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Tarayicida Ctrl+Shift+R (hot reload)")
    print("  2. Sekme adi: 'Gorevler - Solariz CPS' olmali")
    print("  3. CSS hala calisiyor:")
    print("     - Masaustu (>1024px): 11 kolon")
    print("     - Tablet (1024px ve alti): 7 kolon (4 gizli)")
    print()
    print(f"Rollback (manuel, gerekirse):")
    print(f"  Copy-Item templates\\tasks\\{backup_path.name} templates\\tasks\\index.html -Force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
