# -*- coding: utf-8 -*-
"""
CPS DEV - HEDEF KPI BAND HTML (FAZ 6.3 ADIM 2)
================================================

YAPILACAK:
  templates/hedef/index.html'a 2 kucuk degisiklik:
    1. Toolbar SONRASINA (h-tabs ONCESINE) bos KPI div ekle:
       <div id="kpi-band-faz63"></div>
    2. Mevcut script'lerin SONUNA hedef_operasyon.js ekle

DOKUNULMAYAN:
  - Toolbar (basliklar, butonlar)
  - 7 sekme nav (h-tabs)
  - 7 pane-* div'leri
  - Mevcut 2 CSS link (hedef.css, darbogaz_uyari.css)
  - Mevcut 2 script (hedef.js, darbogaz_uyari.js)
  - DARBOGAZ_BAND include
  - Reddet modal
  - Tum JS render mantigi

Idempotent: 'kpi-band-faz63' marker varsa SKIP.
Yedek: index.html.YEDEK_FAZ63_<ts>
"""
import sys
import re
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_HTML = PROJECT_ROOT / "templates" / "hedef" / "index.html"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# DEGISIKLIK 1: KPI div - h-toolbar SONRASINA, h-tabs ONCESINE
# ============================================================
OLD_TOOLBAR_END = '''  </div>
</div>

<div class="h-tabs" role="tablist">'''

NEW_TOOLBAR_END = '''  </div>
</div>

{# FAZ 6.3 - KPI Operasyon Bandi - hedef_operasyon.js doldurur #}
<div id="kpi-band-faz63" data-kpi-band="1"></div>

<div class="h-tabs" role="tablist">'''

# ============================================================
# DEGISIKLIK 2: Yeni script tag, mevcut darbogaz_uyari.js SONRASINA
# ============================================================
OLD_SCRIPTS = '''<script src="{{ url_for('static', filename='js/hedef.js') }}?v={{ range(100000, 999999) | random }}"></script>
<script src="{{ url_for('static', filename='js/darbogaz_uyari.js') }}?v={{ range(100000, 999999) | random }}"></script>'''

NEW_SCRIPTS = '''<script src="{{ url_for('static', filename='js/hedef.js') }}?v={{ range(100000, 999999) | random }}"></script>
<script src="{{ url_for('static', filename='js/darbogaz_uyari.js') }}?v={{ range(100000, 999999) | random }}"></script>
{# FAZ 6.3 - KPI Operasyon Bandi #}
<script src="{{ url_for('static', filename='js/hedef_operasyon.js') }}?v={{ range(100000, 999999) | random }}"></script>'''


def main():
    print("=" * 60)
    print("CPS DEV - HEDEF KPI BAND HTML (FAZ 6.3 ADIM 2)")
    print("=" * 60)

    if not TARGET_HTML.exists():
        print(f"  [HATA] dosya yok: {TARGET_HTML}")
        return 1

    content = TARGET_HTML.read_text(encoding="utf-8")
    original_size = len(content.encode("utf-8"))
    print(f"  Mevcut boyut: {original_size} byte")

    # ============================================================
    # IDEMPOTENT
    # ============================================================
    if 'kpi-band-faz63' in content or 'hedef_operasyon.js' in content:
        print()
        print("  [SKIP] KPI band zaten eklenmis.")
        print("=" * 60)
        return 0

    # ============================================================
    # ON-KONTROL
    # ============================================================
    print()
    print("=== ON-KONTROL ===")

    # 1. Toolbar end + h-tabs anchor
    block1_count = content.count(OLD_TOOLBAR_END)
    print(f"  Toolbar/h-tabs anchor: {block1_count} adet")
    if block1_count != 1:
        print(f"  [HATA] Tek esleme bekleniyor, {block1_count} bulundu")
        return 1
    print("  [OK] OLD_TOOLBAR_END essiz")

    # 2. Scripts anchor
    block2_count = content.count(OLD_SCRIPTS)
    print(f"  Mevcut script tag'leri anchor: {block2_count} adet")
    if block2_count != 1:
        print(f"  [HATA] Tek esleme bekleniyor, {block2_count} bulundu")
        return 1
    print("  [OK] OLD_SCRIPTS essiz")

    # 3. h-tabs var mi
    if '<div class="h-tabs"' not in content:
        print("  [HATA] h-tabs bulunamadi")
        return 1
    print("  [OK] h-tabs nav mevcut")

    # 4. Mevcut script'ler korunacak mi
    for needed in ['hedef.js', 'darbogaz_uyari.js', 'block scripts']:
        if needed in content:
            print(f"  [OK] '{needed}' mevcut (dokunulmayacak)")
        else:
            print(f"  [UYARI] '{needed}' yok")

    # ============================================================
    # YEDEK
    # ============================================================
    backup_path = TARGET_HTML.with_suffix(f".html.YEDEK_FAZ63_{ts}")
    print()
    print("=== YEDEK ===")
    shutil.copy2(str(TARGET_HTML), str(backup_path))
    print(f"  [OK] Yedek: {backup_path.name}")
    print(f"       Boyut: {backup_path.stat().st_size} byte")

    # ============================================================
    # PATCH UYGULA - 2 REPLACE
    # ============================================================
    print()
    print("=== PATCH UYGULAMA ===")

    # 1. Toolbar sonrasina KPI div ekle
    new_content = content.replace(OLD_TOOLBAR_END, NEW_TOOLBAR_END, 1)
    if new_content == content:
        print("  [HATA] OLD_TOOLBAR_END replace etkisiz")
        return 1
    print("  [OK] kpi-band-faz63 div eklendi")

    # 2. Scripts sonrasina yeni script tag ekle
    new_content2 = new_content.replace(OLD_SCRIPTS, NEW_SCRIPTS, 1)
    if new_content2 == new_content:
        print("  [HATA] OLD_SCRIPTS replace etkisiz")
        return 1
    print("  [OK] hedef_operasyon.js script tag eklendi")

    # ============================================================
    # YAZ
    # ============================================================
    print()
    print("=== DOSYAYA YAZMA ===")
    TARGET_HTML.write_text(new_content2, encoding="utf-8")
    new_size = TARGET_HTML.stat().st_size
    diff = new_size - original_size
    print(f"  [OK] Yeni boyut: {new_size} byte (fark: +{diff})")

    # ============================================================
    # DOGRULAMA
    # ============================================================
    print()
    print("=== DOGRULAMA ===")
    final = TARGET_HTML.read_text(encoding="utf-8")

    checks = [
        ('kpi-band-faz63', 'KPI div ID'),
        ('data-kpi-band="1"', 'KPI marker attribute'),
        ('hedef_operasyon.js', 'Script tag'),
        # Mevcut yapi KORUNDU mu
        ('h-toolbar', 'Toolbar korundu'),
        ('btnYeniHedef', 'Yeni Hedef butonu korundu'),
        ('btnSistemOner', 'Sistem Oner butonu korundu'),
        ('class="h-tabs"', 'Sekme nav korundu'),
        ('data-tab="plan"', 'PLAN tab korundu'),
        ('data-tab="rapor"', 'RAPOR tab korundu'),
        ('data-tab="onay"', 'ONAY tab korundu'),
        ('id="pane-plan"', 'pane-plan korundu'),
        ('id="pane-rapor"', 'pane-rapor korundu'),
        ('id="pane-onay"', 'pane-onay korundu'),
        ('id="reddetModal"', 'Reddet modal korundu'),
        ('hedef.js', 'hedef.js script korundu'),
        ('darbogaz_uyari.js', 'darbogaz_uyari.js script korundu'),
        ("hedef.css", 'hedef.css link korundu'),
        ('_darbogaz_band.html', 'darbogaz_band include korundu'),
    ]
    all_ok = True
    for needle, desc in checks:
        ok = needle in final
        sym = "[OK]" if ok else "[HATA]"
        print(f"  {sym} {desc}")
        if not ok:
            all_ok = False

    # KPI div sayisi (TEK olmali)
    kpi_count = final.count('id="kpi-band-faz63"')
    print(f"  KPI div sayisi: {kpi_count}")
    if kpi_count != 1:
        print("  [HATA] KPI div tek olmali")
        all_ok = False

    # Script tag sayisi
    script_count = final.count('hedef_operasyon.js')
    print(f"  hedef_operasyon.js script tag sayisi: {script_count}")
    if script_count != 1:
        print("  [HATA] Script tag tek olmali")
        all_ok = False

    if not all_ok:
        return 1

    # ============================================================
    # JINJA SYNTAX CHECK (basit)
    # ============================================================
    print()
    print("=== JINJA SYNTAX CHECK ===")
    open_blocks = len(re.findall(r"\{%\s*block\s+\w+\s*%\}", final))
    end_blocks = len(re.findall(r"\{%\s*endblock\s*%\}", final))
    print(f"  block / endblock dengesi: {open_blocks} / {end_blocks}")
    if open_blocks != end_blocks:
        print("  [UYARI] Block dengesi sapmis")

    open_if = len(re.findall(r"\{%\s*if\b", final))
    end_if = len(re.findall(r"\{%\s*endif\s*%\}", final))
    print(f"  if / endif dengesi: {open_if} / {end_if}")

    open_inc = len(re.findall(r"\{%\s*include\b", final))
    print(f"  include sayisi: {open_inc} (degismedi mi?)")

    print()
    print("=" * 60)
    print("[OK] FAZ 6.3 ADIM 2 HTML TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Flask RESTART GEREKMEZ (sadece HTML degisti)")
    print("  2. Tarayicida Ctrl+Shift+R")
    print("  3. /hedef/ acin")
    print("  4. F12 Network sekmesinde:")
    print("     - hedef_operasyon.js -> 404 olacak (dosya henuz yok)")
    print("     - Bu BEKLENEN davranis - ADIM 3'te yaratilacak")
    print("  5. F12 Console -> 'Failed to load resource: hedef_operasyon.js' olabilir")
    print("     - Bu BEKLENEN")
    print()
    print("ADIM 3: static/js/hedef_operasyon.js (yeni dosya)")
    print()
    print(f"Rollback (manuel):")
    print(f"  Copy-Item templates\\hedef\\{backup_path.name} templates\\hedef\\index.html -Force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
