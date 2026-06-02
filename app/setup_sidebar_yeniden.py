# -*- coding: utf-8 -*-
"""
setup_sidebar_yeniden.py
------------------------
templates/base.html icindeki <nav id="sidebar"> blokunu degistir.

KORUNAN:
  - Header (logo, nav-tabs, header-right)
  - Yetki kontrolleri ({% if yetki(...) %}, {% if g_user.RolAd %})
  - CSS class adlari (.si, .sn-sec, .sn-sub, .sl)
  - sb-tog toggle button + ID/CLASS yapisi
  - Tum mevcut href'ler (sayfalar dokunulmamis)
  - JS

DEGISEN:
  - Sadece sidebar item'larin gruplama duzeni
  - Yeni gruplar: GENEL, FINANS, TICARET, URETIM, KALITE/TASARIM, YONETIM
  - Tedarikci ayrimi: 'Finans Tedarikcileri' + 'Grafik Tedarikcileri'
  - Cin Siparis + Sevkiyat: FINANS > Ithalat altinda

CPS_KURALLAR:
  - Backend dokunulmadi
  - Calisan modul bozulmadi
  - Sadece UI duzenlendi
"""

import os
import shutil
import datetime
import sys
import re

CPS_ROOT = r"C:\cps_dev"
BASE_HTML = os.path.join(CPS_ROOT, "templates", "base.html")

MARKER_BASLA = "<!-- SIDEBAR_YENIDEN_V1 -->"
MARKER_BIT = "<!-- /SIDEBAR_YENIDEN_V1 -->"


# Yeni sidebar HTML — orijinal class adlari aynen korundu
YENI_SIDEBAR = '''    <!-- SIDEBAR -->
    <!-- SIDEBAR_YENIDEN_V1 -->
    <nav id="sidebar">
      {% set active = request.path.split('/')[1] or 'home' %}

      <!-- ============ GENEL ============ -->
      <div class="sn-sec">Genel</div>
      <a href="/" class="si {% if active == 'home' %}active{% endif %}" title="Özet">
        <svg viewBox="0 0 20 20" fill="none"><path d="M3 9.5L10 3l7 6.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M5 8.5v7h3.5v-3h3v3H15v-7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span class="sl">Özet</span>
      </a>

      <!-- ============ FINANS ============ -->
      {% if yetki('finans') or g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' %}
      <div class="sn-sec">Finans</div>

      <a href="/finans/" class="si {% if active == 'finans' and '/anlasma' not in request.path and '/cari' not in request.path and '/simulator' not in request.path and '/cin-ofis' not in request.path %}active{% endif %}" title="Finans Paneli">
        <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="currentColor" stroke-width="1.5"/><path d="M10 6v8M8 8h3.5a1.5 1.5 0 010 3H8.5a1.5 1.5 0 000 3H12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        <span class="sl">Finans Paneli</span>
      </a>

      <a href="/finans/anlasma" class="si {% if '/anlasma' in request.path %}active{% endif %}" title="Anlaşmalar">
        <svg viewBox="0 0 20 20" fill="none"><rect x="3" y="4" width="14" height="13" rx="2" stroke="currentColor" stroke-width="1.5"/><path d="M7 2v4M13 2v4M3 9h14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="7" cy="13" r="1" fill="currentColor"/><circle cx="10" cy="13" r="1" fill="currentColor"/><circle cx="13" cy="13" r="1" fill="currentColor"/></svg>
        <span class="sl">Anlaşmalar</span>
      </a>

      <a href="/finans/simulator" class="si {% if '/finans/simulator' in request.path %}active{% endif %}" title="Maliyet Simülatörü">
        <svg viewBox="0 0 20 20" fill="none"><path d="M4 4h12v12H4z" stroke="currentColor" stroke-width="1.5"/><path d="M4 8h12M8 4v12" stroke="currentColor" stroke-width="1.5"/></svg>
        <span class="sl">Maliyet Simülatörü</span>
      </a>

      <div class="sn-sub">İthalat</div>

      <a href="/finans/cin-ofis" class="si {% if '/finans/cin-ofis' in request.path %}active{% endif %}" title="Çin Ofis İçe Aktarma">
        <svg viewBox="0 0 20 20" fill="none"><path d="M3 10l7-6 7 6v7H3v-7z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M8 17v-5h4v5" stroke="currentColor" stroke-width="1.5"/></svg>
        <span class="sl">Çin Ofis İçe Aktarma</span>
      </a>

      {% if yetki('grafik.cin_siparis') or g_user.RolAd == 'Yönetim' %}
      <a href="/grafik/siparis" class="si {% if '/grafik/siparis' in request.path %}active{% endif %}" title="Çin Sipariş">
        <svg viewBox="0 0 20 20" fill="none"><rect x="3" y="4" width="14" height="12" rx="2" stroke="currentColor" stroke-width="1.5"/><path d="M7 2v4M13 2v4M3 8h14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        <span class="sl">Çin Sipariş</span>
      </a>
      {% endif %}

      {% if yetki('grafik.maliyet') or g_user.RolAd == 'Yönetim' %}
      <a href="/grafik/sevkiyat" class="si {% if '/grafik/sevkiyat' in request.path %}active{% endif %}" title="Sevkiyat & Maliyet">
        <svg viewBox="0 0 20 20" fill="none"><path d="M3 7h11l2 4v5h-2a2 2 0 01-4 0H8a2 2 0 01-4 0H3V7z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
        <span class="sl">Sevkiyat & Maliyet</span>
      </a>
      {% endif %}
      {% endif %}

      <!-- ============ TICARET ============ -->
      {% if yetki('finans') or yetki('grafik.tedarikci') or g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' %}
      <div class="sn-sec">Ticaret</div>

      {% if yetki('finans') or g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' %}
      <a href="/finans/cari?tip=1" class="si {% if active == 'finans' and request.args.get('tip') == '1' %}active{% endif %}" title="Müşteriler">
        <svg viewBox="0 0 20 20" fill="none"><circle cx="7" cy="7" r="3" stroke="currentColor" stroke-width="1.5"/><path d="M2 17c0-2.76 2.24-5 5-5s5 2.24 5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="14" cy="7" r="2.5" stroke="currentColor" stroke-width="1.5"/><path d="M18 17c0-2.2-1.8-4-4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        <span class="sl">Müşteriler</span>
      </a>

      <a href="/finans/cari?tip=2" class="si {% if active == 'finans' and request.args.get('tip') == '2' %}active{% endif %}" title="Finans Tedarikçileri">
        <svg viewBox="0 0 20 20" fill="none"><path d="M3 7h11l2 4v5h-2a2 2 0 01-4 0H8a2 2 0 01-4 0H3V7z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><circle cx="6" cy="16" r="1.5" stroke="currentColor" stroke-width="1.5"/><circle cx="13" cy="16" r="1.5" stroke="currentColor" stroke-width="1.5"/></svg>
        <span class="sl">Finans Tedarikçileri</span>
      </a>
      {% endif %}

      {% if yetki('grafik.tedarikci') or g_user.RolAd == 'Yönetim' %}
      <a href="/grafik/tedarikci" class="si {% if '/grafik/tedarikci' in request.path %}active{% endif %}" title="Grafik Tedarikçileri">
        <svg viewBox="0 0 20 20" fill="none"><path d="M10 11a3 3 0 100-6 3 3 0 000 6z" stroke="currentColor" stroke-width="1.5"/><path d="M3 18v-1a4 4 0 014-4h6a4 4 0 014 4v1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        <span class="sl">Grafik Tedarikçileri</span>
      </a>
      {% endif %}
      {% endif %}

      <!-- ============ URETIM ============ -->
      {% if g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' %}
      <div class="sn-sec">Üretim</div>

      <a href="/hedef/" class="si {% if active == 'hedef' and '/sapma' not in request.path %}active{% endif %}" title="Hedef Paneli">
        <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="currentColor" stroke-width="1.5"/><circle cx="10" cy="10" r="4" stroke="currentColor" stroke-width="1.5"/><circle cx="10" cy="10" r="1" fill="currentColor"/></svg>
        <span class="sl">Hedef Paneli</span>
      </a>

      <a href="/hedef/sablon" class="si {% if '/hedef/sablon' in request.path %}active{% endif %}" title="Şablon / Proses">
        <svg viewBox="0 0 20 20" fill="none"><rect x="3" y="3" width="14" height="14" rx="2" stroke="currentColor" stroke-width="1.5"/><path d="M3 8h14M8 3v14" stroke="currentColor" stroke-width="1.5"/></svg>
        <span class="sl">Şablon / Proses</span>
      </a>

      <a href="/hedef/sapma" class="si {% if '/hedef/sapma' in request.path %}active{% endif %}" title="Sapma Analizi">
        <svg viewBox="0 0 20 20" fill="none"><path d="M3 17l4-6 4 3 6-9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M14 5h3v3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        <span class="sl">Sapma Analizi</span>
      </a>
      {% endif %}

      <!-- ============ KALITE / TASARIM ============ -->
      {% if yetki('grafik.urun') or yetki('grafik.numune') or g_user.RolAd == 'Yönetim' %}
      <div class="sn-sec">Kalite / Tasarım</div>

      <a href="/grafik/" class="si {% if active == 'grafik' and request.path == '/grafik/' %}active{% endif %}" title="Grafik Paneli">
        <svg viewBox="0 0 20 20" fill="none"><path d="M10 2L3 7v11h14V7l-7-5z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M8 18V12h4v6" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
        <span class="sl">Grafik Paneli</span>
      </a>

      {% if yetki('grafik.urun') or g_user.RolAd == 'Yönetim' %}
      <a href="/grafik/urun" class="si {% if '/grafik/urun' in request.path or '/grafik/kategori' in request.path %}active{% endif %}" title="Ürün & Varyant">
        <svg viewBox="0 0 20 20" fill="none"><path d="M3 7l7-4 7 4v6l-7 4-7-4V7z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M3 7l7 4 7-4M10 11v6" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
        <span class="sl">Ürün & Varyant</span>
      </a>
      {% endif %}

      {% if yetki('grafik.numune') or g_user.RolAd == 'Yönetim' %}
      <a href="/grafik/numune" class="si {% if '/grafik/numune' in request.path %}active{% endif %}" title="Numune Takip">
        <svg viewBox="0 0 20 20" fill="none"><path d="M8 3v7l-3 5h10l-3-5V3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M7 3h6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        <span class="sl">Numune Takip</span>
      </a>
      {% endif %}
      {% endif %}

      <!-- ============ YONETIM ============ -->
      {% if g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' %}
      <div class="sn-sec">Yönetim</div>

      <a href="/yonetim/" class="si {% if active == 'yonetim' and request.path == '/yonetim/' %}active{% endif %}" title="Yönetim Paneli">
        <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="3" stroke="currentColor" stroke-width="1.5"/><path d="M10 3v2M10 15v2M3 10h2M15 10h2M5.6 5.6l1.4 1.4M13 13l1.4 1.4M5.6 14.4l1.4-1.4M13 7l1.4-1.4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        <span class="sl">Yönetim Paneli</span>
      </a>

      <a href="/yonetim/kullanici" class="si {% if '/yonetim/kullanici' in request.path %}active{% endif %}" title="Kullanıcılar">
        <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="7" r="3" stroke="currentColor" stroke-width="1.5"/><path d="M3 17c0-3.87 3.13-7 7-7s7 3.13 7 7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        <span class="sl">Kullanıcılar</span>
      </a>

      <a href="/yonetim/rol" class="si {% if '/yonetim/rol' in request.path %}active{% endif %}" title="Roller ve Yetkiler">
        <svg viewBox="0 0 20 20" fill="none"><path d="M10 3l7 3v4c0 4-3 7-7 8-4-1-7-4-7-8V6l7-3z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
        <span class="sl">Roller / Yetkiler</span>
      </a>

      <a href="/yonetim/kur" class="si {% if '/yonetim/kur' in request.path %}active{% endif %}" title="Kur Tanımları">
        <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="currentColor" stroke-width="1.5"/><path d="M13 7l-6 6M7 7h3M13 13h-3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        <span class="sl">Kur Tanımları</span>
      </a>

      <a href="/yonetim/log" class="si {% if '/yonetim/log' in request.path %}active{% endif %}" title="Audit Log">
        <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="currentColor" stroke-width="1.5"/><path d="M10 6v4l3 2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        <span class="sl">Audit Log</span>
      </a>
      {% endif %}

      <button class="sb-tog" onclick="var s=document.getElementById('sidebar');s.classList.toggle('expanded');this.textContent=s.classList.contains('expanded')?'◀':'▶'">▶</button>
    </nav>
    <!-- /SIDEBAR_YENIDEN_V1 -->
'''


def main():
    print("=" * 64)
    print("CPS Sidebar Yeniden Duzenleme")
    print("=" * 64)

    if not os.path.exists(BASE_HTML):
        print(f"  [HATA] {BASE_HTML} yok.")
        return 1

    with open(BASE_HTML, 'r', encoding='utf-8') as f:
        src = f.read()

    if MARKER_BASLA in src:
        print("  [BILGI] Sidebar zaten yeniden duzenlenmis (marker var).")
        print("  Tekrar uygulamak icin marker'i sil veya yedekten geri yukle.")
        return 0

    # Eski sidebar'i bul: <!-- SIDEBAR --> ... </nav>
    # Marker'i kullaniyoruz: '    <!-- SIDEBAR -->\n    <nav id="sidebar">'
    pattern = re.compile(
        r"    <!-- SIDEBAR -->\s*\n\s*<nav id=\"sidebar\">.*?</nav>\s*\n",
        re.DOTALL
    )
    m = pattern.search(src)
    if not m:
        print("  [HATA] Mevcut sidebar bloku bulunamadi.")
        print("  '<!-- SIDEBAR -->' ve '<nav id=\"sidebar\">' arananı.")
        return 1

    # Yedek
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = BASE_HTML + f'.bak_{ts}'
    shutil.copy2(BASE_HTML, bp)
    print(f"  [OK] Yedek: {bp}")

    # Replace
    new_src = src[:m.start()] + YENI_SIDEBAR + src[m.end():]

    with open(BASE_HTML, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Sidebar yeniden duzenlendi.")
    print()
    print("YAPILACAK:")
    print("  1) Browser Ctrl+F5 (sunucu restart gerekmez - sadece template)")
    print("  2) Sayfayi yenile")
    print()
    print("Beklenen 6 grup:")
    print("  GENEL:           Ozet")
    print("  FINANS:          Finans Paneli, Anlasmalar, Maliyet Simulatoru")
    print("                   Ithalat: Cin Ofis, Cin Siparis, Sevkiyat & Maliyet")
    print("  TICARET:         Musteriler, Finans Tedarikcileri, Grafik Tedarikcileri")
    print("  URETIM:          Hedef Paneli, Sablon/Proses, Sapma Analizi")
    print("  KALITE/TASARIM:  Grafik Paneli, Urun & Varyant, Numune Takip")
    print("  YONETIM:         Yonetim Paneli, Kullanicilar, Roller, Kur, Audit Log")
    print()
    print("Geri donus icin:")
    print(f"  copy \"{bp}\" \"{BASE_HTML}\"")
    return 0


if __name__ == '__main__':
    sys.exit(main())
