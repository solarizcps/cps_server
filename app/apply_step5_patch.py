# -*- coding: utf-8 -*-
"""
CPS DEV - FAZ 3 ADIM 5 PATCH UYGULAYICI (base.html)
====================================================

Bu script:
  1. base.html'i yedekler (YEDEK_FAZ3_ADIM5_<ts>)
  2. </head> oncesine global_overlay.css link'i ekler
  3. </body> oncesine global_task_listener.js script'i ekler
  4. Her ikisi de {% if g_user %} ile sarili (auth guard)
  5. Idempotent: zaten varsa SKIP

Yaklasim:
  - {% block head %} / {% block scripts %} bloklarina DOKUNMAZ
    (child template override'i bozmamak icin)
  - Direkt </head> ve </body> oncesine raw insertion
  - Hem server-side guard ({% if g_user %})
    hem client-side guard (JS init'te /giris kontrolu) var

Kontrol:
  - Mevcut base.html: 2459 satir, 42 KB
  - </head> satir: 45 (bizim ekleme: 44'e gidecek)
  - </body> satir: 821 (bizim ekleme: 820'ye gidecek)
"""
import sys
import os
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
BASE_HTML = PROJECT_ROOT / "templates" / "base.html"

ts = datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# EKLENECEK SATIRLAR
# ============================================================
# Marker yorumu ile baslar - idempotent kontrol icin

CSS_INSERTION = '''
  {# === FAZ 3 GLOBAL OVERLAY CSS === #}
  {% if g_user %}
  <link rel="stylesheet" href="{{ url_for('static', filename='css/global_overlay.css') }}">
  {% endif %}
'''

JS_INSERTION = '''
  {# === FAZ 3 GLOBAL TASK LISTENER === #}
  {% if g_user %}
  <script src="{{ url_for('static', filename='js/global_task_listener.js') }}"></script>
  {% endif %}
'''

CSS_MARKER = "FAZ 3 GLOBAL OVERLAY CSS"
JS_MARKER  = "FAZ 3 GLOBAL TASK LISTENER"


def patch_base_html():
    print()
    print("=== BASE.HTML PATCH ===")

    if not BASE_HTML.exists():
        print(f"  [HATA] Dosya yok: {BASE_HTML}")
        return False

    content = BASE_HTML.read_text(encoding="utf-8")

    # Idempotent check
    has_css = CSS_MARKER in content
    has_js = JS_MARKER in content

    if has_css and has_js:
        print("  [SKIP] FAZ 3 patch'i zaten uygulanmis (CSS+JS markeri var)")
        return True

    # Yedek
    backup_path = BASE_HTML.with_suffix(f".html.YEDEK_FAZ3_ADIM5_{ts}")
    backup_path.write_text(content, encoding="utf-8")
    print(f"  [OK] Yedek: {backup_path.name}")

    # </head> bul
    head_close_pos = content.rfind("</head>")
    if head_close_pos == -1:
        print("  [HATA] </head> tag'i bulunamadi!")
        return False

    # </body> bul
    body_close_pos = content.rfind("</body>")
    if body_close_pos == -1:
        print("  [HATA] </body> tag'i bulunamadi!")
        return False

    # Once </body>'den ekle (sondan), boylece head_close_pos invalid olmaz
    # Ama ikisini ayri ayri yapmak yerine, baslayan ucuna gore once </head>'e

    new_content = content

    # 1. CSS ekle (eger zaten yoksa) - </head> oncesine
    if not has_css:
        # </head> on satirinin basina git, oraya CSS ekle
        head_close_pos = new_content.rfind("</head>")
        new_content = (
            new_content[:head_close_pos]
            + CSS_INSERTION.lstrip("\n")
            + new_content[head_close_pos:]
        )
        print("  [OK] global_overlay.css link eklendi (</head> oncesi)")

    # 2. JS ekle (eger zaten yoksa) - </body> oncesine
    if not has_js:
        # </body> pozisyonunu yeniden bul (CSS eklendigi icin shift oldu)
        body_close_pos = new_content.rfind("</body>")
        new_content = (
            new_content[:body_close_pos]
            + JS_INSERTION.lstrip("\n")
            + new_content[body_close_pos:]
        )
        print("  [OK] global_task_listener.js script eklendi (</body> oncesi)")

    # Yaz
    BASE_HTML.write_text(new_content, encoding="utf-8")

    old_size = len(content)
    new_size = len(new_content)
    print(f"  [OK] base.html guncellendi: {old_size} -> {new_size} byte (+{new_size - old_size})")

    return True


def verify():
    """Patch sonrasi dogrulama."""
    print()
    print("=== DOGRULAMA ===")
    content = BASE_HTML.read_text(encoding="utf-8")

    has_css_marker = CSS_MARKER in content
    has_js_marker  = JS_MARKER in content
    has_css_link   = "global_overlay.css" in content
    has_js_script  = "global_task_listener.js" in content
    has_g_user     = "{% if g_user %}" in content

    print(f"  CSS marker yorumu: {has_css_marker}")
    print(f"  JS marker yorumu:  {has_js_marker}")
    print(f"  CSS link tag'i:    {has_css_link}")
    print(f"  JS script tag'i:   {has_js_script}")
    print(f"  Auth guard ({{ if g_user }}): {has_g_user}")

    # </head> ve </body> hala var mi
    head_count = content.count("</head>")
    body_count = content.count("</body>")
    print(f"  </head> sayisi: {head_count} (1 olmali)")
    print(f"  </body> sayisi: {body_count} (1 olmali)")

    all_ok = (has_css_marker and has_js_marker and has_g_user
              and head_count == 1 and body_count == 1)

    return all_ok


def main():
    print("=" * 60)
    print("CPS DEV - FAZ 3 ADIM 5 (base.html entegrasyon)")
    print("=" * 60)

    if not patch_base_html():
        return 1

    if not verify():
        print("\n[UYARI] Dogrulamada problem var, base.html'i kontrol edin!")
        return 1

    print()
    print("=" * 60)
    print("[OK] ADIM 5 PATCH TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Flask restart")
    print("  2. Browser test - tarayicida F12 console")
    print("  3. Yeni gorev olustur -> overlay duser mi?")
    print("  4. Regression: 7 modul kontrolu")
    return 0


if __name__ == "__main__":
    sys.exit(main())
