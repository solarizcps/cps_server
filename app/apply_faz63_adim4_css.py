# -*- coding: utf-8 -*-
"""
CPS DEV - HEDEF OPERASYON CSS (FAZ 6.3 ADIM 4)
================================================

YAPILACAK:
  1. YENI dosya: static/css/hedef_operasyon.css
     - 5 KPI kart stili (CSS class'lari)
     - Sticky position
     - Sade hover effect
     - 3 breakpoint responsive (mobile/tablet/desktop)
     - Renk class'lari (kritik/uyari/iyi)
  
  2. templates/hedef/index.html'a CSS link ekle:
     {% block head %} icine

DOKUNULMAYAN:
  - Mevcut hedef.css
  - Mevcut darbogaz_uyari.css
  - hedef_operasyon.js (inline style'lar fallback olarak duruyor)
  - HTML icerigi

NOT:
  hedef_operasyon.js inline style'lar HALA AKTIF.
  CSS class'lar inline style'lari OVERRIDE eder (CSS specificity).
  ADIM 5 opsiyonel: JS'deki inline style'lari temizle.

Idempotent: hedef_operasyon.css linki varsa SKIP.
Yedek: index.html.YEDEK_FAZ63_CSS_<ts>
"""
import sys
import re
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_CSS = PROJECT_ROOT / "static" / "css" / "hedef_operasyon.css"
TARGET_HTML = PROJECT_ROOT / "templates" / "hedef" / "index.html"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# CSS ICERIK - hedef_operasyon.css
# ============================================================
CSS_CONTENT = '''/* ================================================================
   CPS DEV - Hedef Operasyon KPI Bandi (FAZ 6.3)
   ----------------------------------------------------------------
   Hedef ID: #kpi-band-faz63
   Container: .faz63-kpi-band
   Kart:      .faz63-kpi-card
   ================================================================ */

/* === KPI BAND CONTAINER === */
.faz63-kpi-band {
    display: flex;
    gap: 8px;
    margin: 12px 0 16px 0;
    flex-wrap: nowrap;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: thin;
    /* Sticky DESKTOP - scroll edilince ust hizada kalir */
    position: sticky;
    top: 0;
    z-index: 9;
    padding: 4px 0 8px 0;
    background: #fff;
}

.faz63-kpi-band::-webkit-scrollbar {
    height: 4px;
}
.faz63-kpi-band::-webkit-scrollbar-thumb {
    background: #ddd;
    border-radius: 2px;
}

/* === KPI KART === */
.faz63-kpi-card {
    flex: 1 1 0;
    min-width: 130px;
    padding: 10px 14px;
    background: #fff;
    border: 1px solid #e8e8e8;
    border-radius: 6px;
    box-shadow: 0 1px 2px rgba(0, 0, 0, .03);
    transition: box-shadow .15s ease, transform .15s ease, border-color .15s ease;
    cursor: default;
}

.faz63-kpi-card:hover {
    box-shadow: 0 2px 6px rgba(0, 0, 0, .06);
    border-color: #d0d0d0;
    transform: translateY(-1px);
}

/* === KART ICERIK === */
.faz63-kpi-card .faz63-baslik {
    font-size: 10.5px;
    color: #888;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .6px;
    margin-bottom: 4px;
    line-height: 1.3;
}

.faz63-kpi-card .faz63-sayi {
    font-size: 26px;
    font-weight: 700;
    line-height: 1.1;
    color: #1a1a1a;
}

.faz63-kpi-card .faz63-etiket {
    font-size: 10px;
    color: #888;
    margin-top: 2px;
    font-weight: 500;
}

/* === RENK MODIFIERS === */
.faz63-kpi-card.faz63-kritik {
    background: #ffebee;
    border-color: #ffcdd2;
}
.faz63-kpi-card.faz63-kritik .faz63-sayi { color: #c62828; }
.faz63-kpi-card.faz63-kritik .faz63-etiket { color: #c62828; }

.faz63-kpi-card.faz63-uyari {
    background: #fff3e0;
    border-color: #ffcc80;
}
.faz63-kpi-card.faz63-uyari .faz63-sayi { color: #ef6c00; }
.faz63-kpi-card.faz63-uyari .faz63-etiket { color: #ef6c00; }

.faz63-kpi-card.faz63-iyi {
    background: #e8f5e9;
    border-color: #c8e6c9;
}
.faz63-kpi-card.faz63-iyi .faz63-sayi { color: #2e7d32; }
.faz63-kpi-card.faz63-iyi .faz63-etiket { color: #2e7d32; }

/* ================================================================
   RESPONSIVE BREAKPOINTS
   ================================================================ */

/* TABLET: 769-1366 px */
@media (max-width: 1366px) {
    .faz63-kpi-band {
        gap: 6px;
    }
    .faz63-kpi-card {
        min-width: 110px;
        padding: 8px 10px;
    }
    .faz63-kpi-card .faz63-baslik {
        font-size: 9.5px;
        letter-spacing: .4px;
    }
    .faz63-kpi-card .faz63-sayi {
        font-size: 22px;
    }
}

/* MOBILE: <768 px */
@media (max-width: 768px) {
    .faz63-kpi-band {
        gap: 4px;
        margin: 8px 0 12px 0;
        position: sticky;
        top: 0;
    }
    .faz63-kpi-card {
        min-width: 80px;
        padding: 6px 8px;
    }
    .faz63-kpi-card .faz63-baslik {
        font-size: 8.5px;
        letter-spacing: .3px;
        margin-bottom: 2px;
    }
    .faz63-kpi-card .faz63-sayi {
        font-size: 18px;
    }
    .faz63-kpi-card .faz63-etiket {
        font-size: 9px;
    }
}

/* === DAR EKRAN: alt-etiket gizle === */
@media (max-width: 480px) {
    .faz63-kpi-card .faz63-etiket {
        display: none;
    }
}
'''


# ============================================================
# HTML PATCH - CSS link {% block head %} icine ekle
# ============================================================
OLD_HEAD_BLOCK = '''<link rel="stylesheet" href="{{ url_for('static', filename='css/darbogaz_uyari.css') }}?v={{ range(100000, 999999) | random }}">
{% endblock %}'''

NEW_HEAD_BLOCK = '''<link rel="stylesheet" href="{{ url_for('static', filename='css/darbogaz_uyari.css') }}?v={{ range(100000, 999999) | random }}">
{# FAZ 6.3 - KPI Operasyon Bandi CSS #}
<link rel="stylesheet" href="{{ url_for('static', filename='css/hedef_operasyon.css') }}?v={{ range(100000, 999999) | random }}">
{% endblock %}'''


def main():
    print("=" * 60)
    print("CPS DEV - HEDEF OPERASYON CSS (FAZ 6.3 ADIM 4)")
    print("=" * 60)

    # Hedef klasor
    css_dir = TARGET_CSS.parent
    if not css_dir.exists():
        print(f"  [HATA] Klasor yok: {css_dir}")
        return 1

    # ============================================================
    # IDEMPOTENT - CSS dosyasi
    # ============================================================
    css_already = False
    if TARGET_CSS.exists():
        existing_css = TARGET_CSS.read_text(encoding="utf-8")
        if 'FAZ 6.3' in existing_css and 'faz63-kpi-band' in existing_css:
            css_already = True
            print(f"  CSS dosyasi zaten var: {TARGET_CSS.stat().st_size} byte")
        else:
            # Yedek
            backup = TARGET_CSS.with_suffix(f".css.YEDEK_FAZ63_{ts}")
            shutil.copy2(str(TARGET_CSS), str(backup))
            print(f"  [UYARI] Var ama markersiz - yedek alindi: {backup.name}")

    # ============================================================
    # IDEMPOTENT - HTML link
    # ============================================================
    html_content = TARGET_HTML.read_text(encoding="utf-8")
    html_already = 'hedef_operasyon.css' in html_content

    # Both already done?
    if css_already and html_already:
        print()
        print("  [SKIP] Hem CSS hem HTML link zaten var.")
        print("=" * 60)
        return 0

    # ============================================================
    # 1. CSS DOSYASI YAZ
    # ============================================================
    if not css_already:
        print()
        print("=== CSS DOSYASI YAZIMI ===")
        TARGET_CSS.write_text(CSS_CONTENT, encoding="utf-8")
        print(f"  [OK] {TARGET_CSS.name} yazildi: {TARGET_CSS.stat().st_size} byte")
    else:
        print("  [SKIP] CSS zaten var (FAZ 6.3 markerli)")

    # ============================================================
    # 2. HTML LINK EKLE
    # ============================================================
    if not html_already:
        print()
        print("=== HTML LINK EKLEME ===")
        # On-kontrol
        anchor_count = html_content.count(OLD_HEAD_BLOCK)
        print(f"  Anchor (head endblock): {anchor_count} adet")
        if anchor_count != 1:
            print(f"  [HATA] Tek esleme bekleniyor, {anchor_count} bulundu")
            return 1

        # Yedek
        backup = TARGET_HTML.with_suffix(f".html.YEDEK_FAZ63_CSS_{ts}")
        shutil.copy2(str(TARGET_HTML), str(backup))
        print(f"  [OK] Yedek: {backup.name}")

        # Replace
        new_html = html_content.replace(OLD_HEAD_BLOCK, NEW_HEAD_BLOCK, 1)
        TARGET_HTML.write_text(new_html, encoding="utf-8")
        print(f"  [OK] CSS link eklendi")
    else:
        print("  [SKIP] HTML link zaten var")

    # ============================================================
    # DOGRULAMA - CSS DOSYASI
    # ============================================================
    print()
    print("=== CSS DOGRULAMA ===")
    final_css = TARGET_CSS.read_text(encoding="utf-8")
    css_checks = [
        ('FAZ 6.3', 'CSS marker'),
        ('.faz63-kpi-band', 'Container class'),
        ('.faz63-kpi-card', 'Kart class'),
        ('.faz63-baslik', 'Baslik class'),
        ('.faz63-sayi', 'Sayi class'),
        ('.faz63-etiket', 'Etiket class'),
        ('.faz63-kritik', 'Kritik renk class'),
        ('.faz63-uyari', 'Uyari renk class'),
        ('.faz63-iyi', 'Iyi renk class'),
        ('position: sticky', 'Sticky position'),
        ('@media (max-width: 1366px)', 'Tablet breakpoint'),
        ('@media (max-width: 768px)', 'Mobile breakpoint'),
        ('@media (max-width: 480px)', 'Dar ekran breakpoint'),
        (':hover', 'Hover effect'),
    ]
    css_ok = True
    for needle, desc in css_checks:
        ok = needle in final_css
        sym = "[OK]" if ok else "[HATA]"
        print(f"  {sym} {desc}")
        if not ok:
            css_ok = False

    # CSS brace dengesi
    open_b = final_css.count('{')
    close_b = final_css.count('}')
    print(f"  CSS brace: {{={open_b}, }}={close_b}, fark={open_b - close_b}")
    if open_b != close_b:
        print("  [HATA] CSS brace dengesi sapmis")
        css_ok = False

    # ============================================================
    # DOGRULAMA - HTML
    # ============================================================
    print()
    print("=== HTML DOGRULAMA ===")
    final_html = TARGET_HTML.read_text(encoding="utf-8")
    html_checks = [
        ('hedef_operasyon.css', 'Yeni CSS link'),
        ('hedef_operasyon.js', 'JS script (ADIM 2)'),
        ('kpi-band-faz63', 'KPI div'),
        ('hedef.css', 'Mevcut hedef.css korundu'),
        ('darbogaz_uyari.css', 'darbogaz_uyari.css korundu'),
        ('hedef.js', 'hedef.js script korundu'),
        ('class="h-tabs"', 'Sekme nav korundu'),
        ('id="pane-plan"', 'pane-plan korundu'),
    ]
    html_ok = True
    for needle, desc in html_checks:
        ok = needle in final_html
        sym = "[OK]" if ok else "[HATA]"
        print(f"  {sym} {desc}")
        if not ok:
            html_ok = False

    if not (css_ok and html_ok):
        return 1

    print()
    print("=" * 60)
    print("[OK] FAZ 6.3 ADIM 4 CSS TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Tarayicida Ctrl+Shift+R")
    print("  2. /hedef/ acin")
    print("  3. Beklenen:")
    print("     - 5 KPI kart hala duzgun gorunur")
    print("     - Sticky: sayfa scroll edilince ust hizada kalir")
    print("     - Hover: kartin uzerine geldiginizde hafif yukseliyor")
    print("     - Mobile/tablet: kucuk ekran breakpoint'leri devreye girer")
    print()
    print(f"Rollback (manuel):")
    print(f"  Remove-Item static\\css\\hedef_operasyon.css -Force")
    print(f"  # HTML icin yedek dosyayi geri getir (CSS link silinir)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
