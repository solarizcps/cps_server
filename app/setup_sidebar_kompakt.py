# -*- coding: utf-8 -*-
"""
setup_sidebar_kompakt_collapsible.py
------------------------------------
Sidebar:
  - Tum gruplar collapsible (acilir-kapanir)
  - Aktif sayfanin grubu default ACIK
  - Diger gruplar default KAPALI
  - Kompakt spacing (.si padding dusuk, .sn-sec dusuk margin)
  - Grup basligi: '▼ FINANS (6)' / '► FINANS (6)'

KORUNAN:
  - Header, nav-tabs, header-right
  - Tum yetki kontrolleri
  - Tum href'ler
  - sb-tog mevcut toggle button
  - Backend
"""

import os
import shutil
import datetime
import sys
import re

CPS_ROOT = r"C:\cps_dev"
BASE_HTML = os.path.join(CPS_ROOT, "templates", "base.html")

MARKER = "<!-- SIDEBAR_COMPACT_V2 -->"


# ====================================================================
# Yeni sidebar template — Jinja ile aktif grubu hesaplar
# Her grup divinin data-grup attribute'u var
# ====================================================================
YENI_SIDEBAR = '''    <!-- SIDEBAR -->
    <!-- SIDEBAR_COMPACT_V2 -->
    <nav id="sidebar">
      {% set active = request.path.split('/')[1] or 'home' %}
      {% set rp = request.path %}

      {# Aktif grubu hesapla: Hangi grup default acik gelecek #}
      {% set aktif_grup = 'genel' %}
      {% if active == 'finans' %}{% set aktif_grup = 'finans' %}{% endif %}
      {% if '/grafik/siparis' in rp or '/grafik/sevkiyat' in rp %}{% set aktif_grup = 'finans' %}{% endif %}
      {% if active == 'finans' and request.args.get('tip') in ['1', '2'] %}{% set aktif_grup = 'ticaret' %}{% endif %}
      {% if '/grafik/tedarikci' in rp %}{% set aktif_grup = 'ticaret' %}{% endif %}
      {% if active == 'hedef' %}{% set aktif_grup = 'uretim' %}{% endif %}
      {% if active == 'grafik' and aktif_grup != 'finans' and aktif_grup != 'ticaret' %}{% set aktif_grup = 'kalite' %}{% endif %}
      {% if active == 'yonetim' %}{% set aktif_grup = 'yonetim' %}{% endif %}

      <!-- ============ GENEL ============ -->
      <div class="sn-sec sn-toggle{% if aktif_grup == 'genel' %} acik{% endif %}" data-grup="genel">
        <span class="sn-arrow">{% if aktif_grup == 'genel' %}▼{% else %}►{% endif %}</span>
        <span class="sn-baslik">Genel</span>
        <span class="sn-count">1</span>
      </div>
      <div class="sn-grup{% if aktif_grup != 'genel' %} kapali{% endif %}" data-grup="genel">
        <a href="/" class="si {% if active == 'home' %}active{% endif %}" title="Özet">
          <svg viewBox="0 0 20 20" fill="none"><path d="M3 9.5L10 3l7 6.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M5 8.5v7h3.5v-3h3v3H15v-7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <span class="sl">Özet</span>
        </a>
      </div>

      <!-- ============ FINANS ============ -->
      {% if yetki('finans') or g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' %}
      {% set fin_count = 6 %}
      <div class="sn-sec sn-toggle{% if aktif_grup == 'finans' %} acik{% endif %}" data-grup="finans">
        <span class="sn-arrow">{% if aktif_grup == 'finans' %}▼{% else %}►{% endif %}</span>
        <span class="sn-baslik">Finans</span>
        <span class="sn-count">{{ fin_count }}</span>
      </div>
      <div class="sn-grup{% if aktif_grup != 'finans' %} kapali{% endif %}" data-grup="finans">

        <a href="/finans/" class="si {% if active == 'finans' and '/anlasma' not in rp and '/cari' not in rp and '/simulator' not in rp and '/cin-ofis' not in rp %}active{% endif %}" title="Finans Paneli">
          <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="currentColor" stroke-width="1.5"/><path d="M10 6v8M8 8h3.5a1.5 1.5 0 010 3H8.5a1.5 1.5 0 000 3H12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          <span class="sl">Finans Paneli</span>
        </a>

        <a href="/finans/anlasma" class="si {% if '/anlasma' in rp %}active{% endif %}" title="Anlaşmalar">
          <svg viewBox="0 0 20 20" fill="none"><rect x="3" y="4" width="14" height="13" rx="2" stroke="currentColor" stroke-width="1.5"/><path d="M7 2v4M13 2v4M3 9h14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="7" cy="13" r="1" fill="currentColor"/><circle cx="10" cy="13" r="1" fill="currentColor"/><circle cx="13" cy="13" r="1" fill="currentColor"/></svg>
          <span class="sl">Anlaşmalar</span>
        </a>

        <a href="/finans/simulator" class="si {% if '/finans/simulator' in rp %}active{% endif %}" title="Maliyet Simülatörü">
          <svg viewBox="0 0 20 20" fill="none"><path d="M4 4h12v12H4z" stroke="currentColor" stroke-width="1.5"/><path d="M4 8h12M8 4v12" stroke="currentColor" stroke-width="1.5"/></svg>
          <span class="sl">Maliyet Sim.</span>
        </a>

        <div class="sn-sub">İthalat</div>

        <a href="/finans/cin-ofis" class="si {% if '/finans/cin-ofis' in rp %}active{% endif %}" title="Çin Ofis İçe Aktarma">
          <svg viewBox="0 0 20 20" fill="none"><path d="M3 10l7-6 7 6v7H3v-7z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M8 17v-5h4v5" stroke="currentColor" stroke-width="1.5"/></svg>
          <span class="sl">Çin Ofis</span>
        </a>

        {% if yetki('grafik.cin_siparis') or g_user.RolAd == 'Yönetim' %}
        <a href="/grafik/siparis" class="si {% if '/grafik/siparis' in rp %}active{% endif %}" title="Çin Sipariş">
          <svg viewBox="0 0 20 20" fill="none"><rect x="3" y="4" width="14" height="12" rx="2" stroke="currentColor" stroke-width="1.5"/><path d="M7 2v4M13 2v4M3 8h14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          <span class="sl">Çin Sipariş</span>
        </a>
        {% endif %}

        {% if yetki('grafik.maliyet') or g_user.RolAd == 'Yönetim' %}
        <a href="/grafik/sevkiyat" class="si {% if '/grafik/sevkiyat' in rp %}active{% endif %}" title="Sevkiyat & Maliyet">
          <svg viewBox="0 0 20 20" fill="none"><path d="M3 7h11l2 4v5h-2a2 2 0 01-4 0H8a2 2 0 01-4 0H3V7z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
          <span class="sl">Sevkiyat</span>
        </a>
        {% endif %}
      </div>
      {% endif %}

      <!-- ============ TICARET ============ -->
      {% if yetki('finans') or yetki('grafik.tedarikci') or g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' %}
      <div class="sn-sec sn-toggle{% if aktif_grup == 'ticaret' %} acik{% endif %}" data-grup="ticaret">
        <span class="sn-arrow">{% if aktif_grup == 'ticaret' %}▼{% else %}►{% endif %}</span>
        <span class="sn-baslik">Ticaret</span>
        <span class="sn-count">3</span>
      </div>
      <div class="sn-grup{% if aktif_grup != 'ticaret' %} kapali{% endif %}" data-grup="ticaret">

        {% if yetki('finans') or g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' %}
        <a href="/finans/cari?tip=1" class="si {% if active == 'finans' and request.args.get('tip') == '1' %}active{% endif %}" title="Müşteriler">
          <svg viewBox="0 0 20 20" fill="none"><circle cx="7" cy="7" r="3" stroke="currentColor" stroke-width="1.5"/><path d="M2 17c0-2.76 2.24-5 5-5s5 2.24 5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="14" cy="7" r="2.5" stroke="currentColor" stroke-width="1.5"/><path d="M18 17c0-2.2-1.8-4-4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          <span class="sl">Müşteriler</span>
        </a>

        <a href="/finans/cari?tip=2" class="si {% if active == 'finans' and request.args.get('tip') == '2' %}active{% endif %}" title="Finans Tedarikçileri">
          <svg viewBox="0 0 20 20" fill="none"><path d="M3 7h11l2 4v5h-2a2 2 0 01-4 0H8a2 2 0 01-4 0H3V7z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><circle cx="6" cy="16" r="1.5" stroke="currentColor" stroke-width="1.5"/><circle cx="13" cy="16" r="1.5" stroke="currentColor" stroke-width="1.5"/></svg>
          <span class="sl">Finans Tedarik.</span>
        </a>
        {% endif %}

        {% if yetki('grafik.tedarikci') or g_user.RolAd == 'Yönetim' %}
        <a href="/grafik/tedarikci" class="si {% if '/grafik/tedarikci' in rp %}active{% endif %}" title="Grafik Tedarikçileri">
          <svg viewBox="0 0 20 20" fill="none"><path d="M10 11a3 3 0 100-6 3 3 0 000 6z" stroke="currentColor" stroke-width="1.5"/><path d="M3 18v-1a4 4 0 014-4h6a4 4 0 014 4v1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          <span class="sl">Grafik Tedarik.</span>
        </a>
        {% endif %}
      </div>
      {% endif %}

      <!-- ============ URETIM ============ -->
      {% if g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' %}
      <div class="sn-sec sn-toggle{% if aktif_grup == 'uretim' %} acik{% endif %}" data-grup="uretim">
        <span class="sn-arrow">{% if aktif_grup == 'uretim' %}▼{% else %}►{% endif %}</span>
        <span class="sn-baslik">Üretim</span>
        <span class="sn-count">3</span>
      </div>
      <div class="sn-grup{% if aktif_grup != 'uretim' %} kapali{% endif %}" data-grup="uretim">

        <a href="/hedef/" class="si {% if active == 'hedef' and '/sapma' not in rp %}active{% endif %}" title="Hedef Paneli">
          <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="currentColor" stroke-width="1.5"/><circle cx="10" cy="10" r="4" stroke="currentColor" stroke-width="1.5"/><circle cx="10" cy="10" r="1" fill="currentColor"/></svg>
          <span class="sl">Hedef Paneli</span>
        </a>

        <a href="/hedef/sablon" class="si {% if '/hedef/sablon' in rp %}active{% endif %}" title="Şablon / Proses">
          <svg viewBox="0 0 20 20" fill="none"><rect x="3" y="3" width="14" height="14" rx="2" stroke="currentColor" stroke-width="1.5"/><path d="M3 8h14M8 3v14" stroke="currentColor" stroke-width="1.5"/></svg>
          <span class="sl">Şablon / Proses</span>
        </a>

        <a href="/hedef/sapma" class="si {% if '/hedef/sapma' in rp %}active{% endif %}" title="Sapma Analizi">
          <svg viewBox="0 0 20 20" fill="none"><path d="M3 17l4-6 4 3 6-9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M14 5h3v3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          <span class="sl">Sapma Analizi</span>
        </a>
      </div>
      {% endif %}

      <!-- ============ KALITE / TASARIM ============ -->
      {% if yetki('grafik.urun') or yetki('grafik.numune') or g_user.RolAd == 'Yönetim' %}
      <div class="sn-sec sn-toggle{% if aktif_grup == 'kalite' %} acik{% endif %}" data-grup="kalite">
        <span class="sn-arrow">{% if aktif_grup == 'kalite' %}▼{% else %}►{% endif %}</span>
        <span class="sn-baslik">Kalite / Tasarım</span>
        <span class="sn-count">3</span>
      </div>
      <div class="sn-grup{% if aktif_grup != 'kalite' %} kapali{% endif %}" data-grup="kalite">

        <a href="/grafik/" class="si {% if active == 'grafik' and rp == '/grafik/' %}active{% endif %}" title="Grafik Paneli">
          <svg viewBox="0 0 20 20" fill="none"><path d="M10 2L3 7v11h14V7l-7-5z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M8 18V12h4v6" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
          <span class="sl">Grafik Paneli</span>
        </a>

        {% if yetki('grafik.urun') or g_user.RolAd == 'Yönetim' %}
        <a href="/grafik/urun" class="si {% if '/grafik/urun' in rp or '/grafik/kategori' in rp %}active{% endif %}" title="Ürün & Varyant">
          <svg viewBox="0 0 20 20" fill="none"><path d="M3 7l7-4 7 4v6l-7 4-7-4V7z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M3 7l7 4 7-4M10 11v6" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
          <span class="sl">Ürün & Varyant</span>
        </a>
        {% endif %}

        {% if yetki('grafik.numune') or g_user.RolAd == 'Yönetim' %}
        <a href="/grafik/numune" class="si {% if '/grafik/numune' in rp %}active{% endif %}" title="Numune Takip">
          <svg viewBox="0 0 20 20" fill="none"><path d="M8 3v7l-3 5h10l-3-5V3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M7 3h6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          <span class="sl">Numune Takip</span>
        </a>
        {% endif %}
      </div>
      {% endif %}

      <!-- ============ YONETIM ============ -->
      {% if g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' %}
      <div class="sn-sec sn-toggle{% if aktif_grup == 'yonetim' %} acik{% endif %}" data-grup="yonetim">
        <span class="sn-arrow">{% if aktif_grup == 'yonetim' %}▼{% else %}►{% endif %}</span>
        <span class="sn-baslik">Yönetim</span>
        <span class="sn-count">5</span>
      </div>
      <div class="sn-grup{% if aktif_grup != 'yonetim' %} kapali{% endif %}" data-grup="yonetim">

        <a href="/yonetim/" class="si {% if active == 'yonetim' and rp == '/yonetim/' %}active{% endif %}" title="Yönetim Paneli">
          <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="3" stroke="currentColor" stroke-width="1.5"/><path d="M10 3v2M10 15v2M3 10h2M15 10h2M5.6 5.6l1.4 1.4M13 13l1.4 1.4M5.6 14.4l1.4-1.4M13 7l1.4-1.4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          <span class="sl">Yönetim Paneli</span>
        </a>

        <a href="/yonetim/kullanici" class="si {% if '/yonetim/kullanici' in rp %}active{% endif %}" title="Kullanıcılar">
          <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="7" r="3" stroke="currentColor" stroke-width="1.5"/><path d="M3 17c0-3.87 3.13-7 7-7s7 3.13 7 7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          <span class="sl">Kullanıcılar</span>
        </a>

        <a href="/yonetim/rol" class="si {% if '/yonetim/rol' in rp %}active{% endif %}" title="Roller / Yetkiler">
          <svg viewBox="0 0 20 20" fill="none"><path d="M10 3l7 3v4c0 4-3 7-7 8-4-1-7-4-7-8V6l7-3z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
          <span class="sl">Roller</span>
        </a>

        <a href="/yonetim/kur" class="si {% if '/yonetim/kur' in rp %}active{% endif %}" title="Kur Tanımları">
          <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="currentColor" stroke-width="1.5"/><path d="M13 7l-6 6M7 7h3M13 13h-3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          <span class="sl">Kur</span>
        </a>

        <a href="/yonetim/log" class="si {% if '/yonetim/log' in rp %}active{% endif %}" title="Audit Log">
          <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="currentColor" stroke-width="1.5"/><path d="M10 6v4l3 2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          <span class="sl">Audit Log</span>
        </a>
      </div>
      {% endif %}

      <button class="sb-tog" onclick="var s=document.getElementById('sidebar');s.classList.toggle('expanded');this.textContent=s.classList.contains('expanded')?'◀':'▶'">▶</button>
    </nav>

    <!-- SIDEBAR_COMPACT_V2 - inline CSS + JS -->
    <style>
      /* Compact spacing */
      #sidebar .si {
        padding: 6px 10px !important;
        min-height: 28px !important;
        font-size: 12.5px !important;
      }
      #sidebar .si svg {
        width: 16px;
        height: 16px;
      }
      /* Section toggle baslik */
      #sidebar .sn-sec.sn-toggle {
        cursor: pointer;
        user-select: none;
        padding: 6px 10px;
        margin: 6px 0 2px 0;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.6px;
        text-transform: uppercase;
        color: var(--text3);
        display: flex;
        align-items: center;
        gap: 6px;
        border-radius: 4px;
        transition: background 0.12s;
      }
      #sidebar .sn-sec.sn-toggle:hover {
        background: rgba(0,0,0,0.04);
        color: var(--text2);
      }
      #sidebar .sn-arrow {
        font-size: 9px;
        color: var(--text3);
        width: 10px;
        display: inline-block;
      }
      #sidebar .sn-baslik {
        flex: 1;
      }
      #sidebar .sn-count {
        font-size: 9px;
        background: var(--bg3, #f3f4f6);
        padding: 1px 6px;
        border-radius: 8px;
        color: var(--text3);
        font-weight: 600;
      }
      #sidebar .sn-sec.sn-toggle.acik {
        color: var(--text2);
      }
      #sidebar .sn-grup {
        max-height: 800px;
        overflow: hidden;
        transition: max-height 0.18s ease-out;
      }
      #sidebar .sn-grup.kapali {
        max-height: 0;
      }
      #sidebar .sn-sub {
        padding: 4px 12px;
        margin-top: 4px;
        font-size: 9px;
        font-weight: 600;
        letter-spacing: 0.5px;
        color: var(--text3);
        text-transform: uppercase;
        opacity: 0.7;
      }
      /* Collapsed sidebar (icon only) modunda gruplar tamamen acik gorunsun */
      #sidebar:not(.expanded) .sn-grup {
        max-height: none !important;
      }
      #sidebar:not(.expanded) .sn-sec.sn-toggle .sn-baslik,
      #sidebar:not(.expanded) .sn-sec.sn-toggle .sn-count,
      #sidebar:not(.expanded) .sn-sec.sn-toggle .sn-arrow,
      #sidebar:not(.expanded) .sn-sub {
        display: none;
      }
      #sidebar:not(.expanded) .sn-sec.sn-toggle {
        padding: 2px;
        margin: 4px 8px;
        height: 1px;
        background: var(--border);
        border-radius: 0;
      }
    </style>

    <script>
      (function(){
        var sb = document.getElementById('sidebar');
        if (!sb) return;
        sb.querySelectorAll('.sn-sec.sn-toggle').forEach(function(h){
          h.addEventListener('click', function(){
            var grup = h.dataset.grup;
            var body = sb.querySelector('.sn-grup[data-grup="' + grup + '"]');
            if (!body) return;
            var acildi = body.classList.toggle('kapali');
            // acildi=true ise simdi KAPALI demek
            h.classList.toggle('acik', !acildi);
            var ar = h.querySelector('.sn-arrow');
            if (ar) ar.textContent = acildi ? '►' : '▼';
          });
        });
      })();
    </script>
'''


def main():
    print("=" * 64)
    print("Sidebar Compact + Collapsible")
    print("=" * 64)

    if not os.path.exists(BASE_HTML):
        print(f"  [HATA] {BASE_HTML} yok.")
        return 1

    with open(BASE_HTML, 'r', encoding='utf-8') as f:
        src = f.read()

    if MARKER in src:
        print("  [BILGI] Compact v2 zaten ekli.")
        return 0

    # Eski sidebar'i bul: '<!-- SIDEBAR -->' baslangic, '</nav>' bitis
    # (Onceki SIDEBAR_YENIDEN_V1 patch'i veya orijinal)
    pattern = re.compile(
        r"    <!-- SIDEBAR -->.*?</nav>\s*\n",
        re.DOTALL
    )
    m = pattern.search(src)
    if not m:
        print("  [HATA] Mevcut sidebar bloku bulunamadi.")
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
    print("  [OK] Sidebar compact + collapsible uygulandi.")
    print()
    print("YAPILACAK:")
    print("  1) Browser Ctrl+F5 (sunucu restart gerekmez)")
    print()
    print("Beklenen davranis:")
    print("  - Acilan sayfanin grubu OTOMATIK ACIK gelir (▼)")
    print("  - Diger gruplar KAPALI (►)")
    print("  - Grup basligina tiklayinca toggle olur")
    print("  - Toplam yer: ~6 baslik + aktif grubun item'lari")
    print()
    print("Test:")
    print("  /hedef/ -> 'Uretim' grubu acik gelmeli")
    print("  /finans/ -> 'Finans' grubu acik gelmeli")
    print("  / -> 'Genel' grubu acik gelmeli")
    return 0


if __name__ == '__main__':
    sys.exit(main())
