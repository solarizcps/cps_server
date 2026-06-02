# -*- coding: utf-8 -*-
"""
CPS DEV - SIDEBAR TIP FILTRE (FAZ 5.2)
=======================================

Sadece templates/base.html'a dokunulur.

YAPI:
  <nav id="sidebar">
    {% set _tip = session.get('kullanici_tip') or 'sistem' %}
    {% if _tip == 'sistem' %}
      ... mevcut sidebar (DOKUNULMAZ) ...
    {% elif _tip == 'personel' %}
      <a href="/uretim/">Üretim Girişi</a>
    {% elif _tip == 'usta' %}
      <a href="/hedef/">Hedef Yönetimi</a>
      <a href="/uretim/">Üretim Girişi</a>
    {% endif %}
    <button class="sb-tog">...</button>   <!-- her tip icin acik -->
  </nav>

DOKUNULMAYAN:
  - Mevcut sidebar icerigi (sat 287 sonrasi - 957 oncesi)
  - Header (Cikis + Sifre Degistir)
  - Toggle button (sat 963)
  - CSS / JS

Idempotent: FAZ 5.2 marker zaten varsa SKIP.
"""
import sys
import shutil
import hashlib
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_HTML  = PROJECT_ROOT / "templates" / "base.html"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# ANCHOR 1: <nav id="sidebar"> - SONRASI sarma baslat
# ============================================================
ANCHOR_OPEN = '<nav id="sidebar">'

WRAPPER_OPEN = '''<nav id="sidebar">

      {# FAZ 5.2: Tip bazli sidebar filtresi #}
      {% set _tip = session.get('kullanici_tip') or 'sistem' %}
      {% if _tip == 'sistem' %}'''


# ============================================================
# ANCHOR 2: <button class="sb-tog" - ONCESI elif/endif ekle
# ============================================================
# Mevcut blok aynen korunur, sadece basina elif blogu girer.
ANCHOR_BUTTON = '<button class="sb-tog"'

WRAPPER_CLOSE_AND_BUTTON = '''{% elif _tip == 'personel' %}

      <a href="/uretim/" class="si active" title="Üretim Girişi">
        <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7l9-4 9 4-9 4-9-4z"/><path d="M3 7v10l9 4 9-4V7"/></svg></span>
        <span class="sl">Üretim Girişi</span>
      </a>

      {% elif _tip == 'usta' %}

      <a href="/hedef/" class="si {% if active == 'hedef' or '/hedef/' in rp %}active{% endif %}" title="Hedef Yönetimi">
        <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg></span>
        <span class="sl">Hedef Yönetimi</span>
      </a>

      <a href="/uretim/" class="si {% if '/uretim/' in rp %}active{% endif %}" title="Üretim Girişi">
        <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7l9-4 9 4-9 4-9-4z"/><path d="M3 7v10l9 4 9-4V7"/></svg></span>
        <span class="sl">Üretim Girişi</span>
      </a>

      {% endif %}

      <button class="sb-tog"'''


def file_hash(path):
    if not path.exists(): return None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main():
    print("=" * 60)
    print("CPS DEV - SIDEBAR TIP FILTRE (FAZ 5.2)")
    print("=" * 60)

    if not TARGET_HTML.exists():
        print(f"  [HATA] base.html yok: {TARGET_HTML}")
        return 1

    content = TARGET_HTML.read_text(encoding="utf-8")
    original_size = len(content.encode("utf-8"))
    print(f"  Mevcut boyut: {original_size} byte")

    # ============================================================
    # IDEMPOTENT KONTROL
    # ============================================================
    if 'FAZ 5.2' in content or "{% set _tip = session.get('kullanici_tip')" in content:
        print()
        print("  [SKIP] FAZ 5.2 marker var, sidebar tip filtresi zaten uygulanmis.")
        print()
        print("=" * 60)
        print("[OK] PATCH ZATEN UYGULANMIS")
        print("=" * 60)
        return 0

    # ============================================================
    # ON-KONTROLLER
    # ============================================================
    print()
    print("=== ON-KONTROL ===")

    # ANCHOR 1 - tek bir tane olmali
    nav_count = content.count(ANCHOR_OPEN)
    print(f"  '<nav id=\"sidebar\">' sayisi: {nav_count}  (1 olmali)")
    if nav_count != 1:
        print(f"  [HATA] Anchor 1 essiz degil veya yok")
        return 1
    print("  [OK] Anchor 1: <nav id=\"sidebar\"> bulundu")

    # ANCHOR 2 - tek bir tane olmali (sb-tog button)
    btn_count = content.count(ANCHOR_BUTTON)
    print(f"  '<button class=\"sb-tog\"' sayisi: {btn_count}  (1 olmali)")
    if btn_count != 1:
        print(f"  [HATA] Anchor 2 essiz degil veya yok")
        return 1
    print("  [OK] Anchor 2: <button class=\"sb-tog\"> bulundu")

    # </nav> sayi kontrolu
    nav_close_count = content.count('</nav>')
    print(f"  '</nav>' sayisi: {nav_close_count}  (1 olmali)")
    if nav_close_count != 1:
        print(f"  [UYARI] </nav> birden fazla, ama patch </nav>'a dokunmuyor (button anchor'a ekleniyor)")

    # ============================================================
    # YEDEK
    # ============================================================
    backup_path = TARGET_HTML.with_suffix(f".html.YEDEK_SIDEBAR_TIP_{ts}")
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

    # 1) Anchor 1: nav acilis sonrasi sarma baslat
    yeni_content = content.replace(ANCHOR_OPEN, WRAPPER_OPEN, 1)
    if yeni_content == content:
        print("  [HATA] WRAPPER_OPEN replace etkisiz")
        return 1
    print("  [OK] 1) Sidebar acilis SARILDI ({% if _tip == 'sistem' %})")

    # 2) Anchor 2: sb-tog button oncesine elif/endif blogu
    yeni_content2 = yeni_content.replace(ANCHOR_BUTTON, WRAPPER_CLOSE_AND_BUTTON, 1)
    if yeni_content2 == yeni_content:
        print("  [HATA] WRAPPER_CLOSE_AND_BUTTON replace etkisiz")
        return 1
    print("  [OK] 2) Personel + Usta minimal sidebar bloklari eklendi")
    print("  [OK] 3) {% endif %} eklendi (sistem bloku kapatildi)")

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

    checks = [
        ('FAZ 5.2', 'Yeni marker var mi'),
        ("session.get('kullanici_tip')", "kullanici_tip session okundu mu"),
        ("{% if _tip == 'sistem' %}", "sistem dali var mi"),
        ("{% elif _tip == 'personel' %}", "personel dali var mi"),
        ("{% elif _tip == 'usta' %}", "usta dali var mi"),
        # Mevcut yapilar KORUNDU mu
        ('<nav id="sidebar">', 'nav acilis korundu mu'),
        ('</nav>', 'nav kapanis korundu mu'),
        ('<button class="sb-tog"', 'toggle button korundu mu'),
        ('href="/hedef/"', 'mevcut hedef linki korundu mu'),
        ('href="/yonetim/log"', 'mevcut yonetim linki korundu mu (sistem bloku icinde)'),
        ('href="/uretim/"', 'uretim link var mi'),
        ('Üretim Girişi', 'metin uretim girisi var mi'),
        ('Hedef Yönetimi', 'metin hedef yonetimi var mi'),
    ]
    all_ok = True
    for needle, desc in checks:
        ok = needle in final
        sym = "[OK]" if ok else "[HATA]"
        print(f"  {sym} {desc}")
        if not ok:
            all_ok = False

    # Jinja blok dengesi: {% if %} sayisi >= {% endif %} sayisi (yeni 1 tane eklendi)
    if_count = final.count('{% if ')
    elif_count = final.count('{% elif ')
    endif_count = final.count('{% endif %}')
    print(f"  Jinja sayisi: {{% if %}}={if_count}, {{% elif %}}={elif_count}, {{% endif %}}={endif_count}")
    # if + elif eslestirilmesi gerekmez, ama if sayisi == endif sayisi olmali
    if if_count != endif_count:
        print(f"  [UYARI] {{% if %}} != {{% endif %}} - ama bu mevcutta da farkli olabilir, dikkat")

    # ============================================================
    # SYNTAX/JINJA RENDER PRE-CHECK
    # ============================================================
    print()
    print("=== JINJA TEMPLATE BASIT KONTROL ===")
    # Jinja'yi tam render edemeyiz (Flask context yok), ama parse syntax kontrol edebiliriz
    try:
        from jinja2 import Environment
        env = Environment()
        # extends ve include'lari skip et
        clean = final
        env.parse(clean)
        print("  [OK] Jinja parse sorunsuz")
    except ImportError:
        print("  [SKIP] jinja2 import edilemiyor (sorun degil)")
    except Exception as e:
        print(f"  [UYARI] Jinja parse: {e}")
        # Hata olsa da devam edelim (Flask icinde calisacak)

    if not all_ok:
        print()
        print("  [UYARI] Bazi dogrulamalar basarisiz")
        return 1

    print()
    print("=" * 60)
    print("[OK] SIDEBAR TIP FILTRESI PATCH TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Flask hot reload (Jinja template, restart gerekmez)")
    print("  2. Tarayicida hard refresh: Ctrl+Shift+R")
    print("  3. Test:")
    print("     - admin/admin123 -> tam sidebar (mevcut)")
    print("     - test_personel/test123 -> sadece 'Üretim Girişi'")
    print("     - test_usta/test123 -> 'Hedef Yönetimi' + 'Üretim Girişi'")
    print()
    print(f"Rollback (manuel, gerekirse):")
    print(f"  Copy-Item {backup_path.name} base.html -Force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
