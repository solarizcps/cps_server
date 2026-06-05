# -*- coding: utf-8 -*-
"""
setup_sidebar_lucide_ikonlar.py
-------------------------------
Sidebar'a Lucide tarzi inline SVG ikonlar:
  - Tum item ikonlari ayni stilde (outline, stroke 1.5)
  - 36x36 kutu, 8px radius
  - Aktif: turuncu BG + beyaz icon
  - Hover: soft turuncu BG
  - Grup basliklarina da ikon eklendi
  - Collapsible yapi (sn-toggle, sn-grup) KORUNDU

CPS_KURALLAR:
  - Sadece UI
  - Backend dokunulmadi
  - Yetki kontrolleri korundu
  - Ust nav-tabs/header dokunulmadi
"""

import os
import shutil
import datetime
import sys
import re

CPS_ROOT = r"C:\cps_dev"
BASE_HTML = os.path.join(CPS_ROOT, "templates", "base.html")

MARKER = "<!-- SIDEBAR_LUCIDE_V3 -->"


# ====================================================================
# Yeni sidebar - hem collapsible hem Lucide ikonlu
# ====================================================================
YENI_SIDEBAR = '''    <!-- SIDEBAR -->
    <!-- SIDEBAR_LUCIDE_V3 -->
    <nav id="sidebar">
      {% set active = request.path.split('/')[1] or 'home' %}
      {% set rp = request.path %}

      {# Aktif grubu hesapla #}
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
        <svg class="sn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
        <span class="sn-baslik">Genel</span>
        <span class="sn-count">1</span>
      </div>
      <div class="sn-grup{% if aktif_grup != 'genel' %} kapali{% endif %}" data-grup="genel">
        <a href="/" class="si {% if active == 'home' %}active{% endif %}" title="Özet">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg></span>
          <span class="sl">Özet</span>
        </a>
      </div>

      <!-- ============ FINANS ============ -->
      {% if yetki('finans') or g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' %}
      <div class="sn-sec sn-toggle{% if aktif_grup == 'finans' %} acik{% endif %}" data-grup="finans">
        <span class="sn-arrow">{% if aktif_grup == 'finans' %}▼{% else %}►{% endif %}</span>
        <svg class="sn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>
        <span class="sn-baslik">Finans</span>
        <span class="sn-count">6</span>
      </div>
      <div class="sn-grup{% if aktif_grup != 'finans' %} kapali{% endif %}" data-grup="finans">

        <a href="/finans/" class="si {% if active == 'finans' and '/anlasma' not in rp and '/cari' not in rp and '/simulator' not in rp and '/cin-ofis' not in rp %}active{% endif %}" title="Finans Paneli">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M19 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-2"/><path d="M3 5h12"/><path d="M21 12a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v0a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2"/></svg></span>
          <span class="sl">Finans Paneli</span>
        </a>

        <a href="/finans/anlasma" class="si {% if '/anlasma' in rp %}active{% endif %}" title="Anlaşmalar">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"/><line x1="9" y1="9" x2="10" y2="9"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="15" y2="17"/></svg></span>
          <span class="sl">Anlaşmalar</span>
        </a>

        <a href="/finans/simulator" class="si {% if '/finans/simulator' in rp %}active{% endif %}" title="Maliyet Simülatörü">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="2" width="16" height="20" rx="2"/><line x1="8" y1="6" x2="16" y2="6"/><line x1="16" y1="14" x2="16" y2="18"/><line x1="16" y1="10" x2="16" y2="10"/><line x1="12" y1="10" x2="12" y2="10"/><line x1="8" y1="10" x2="8" y2="10"/><line x1="12" y1="14" x2="12" y2="14"/><line x1="8" y1="14" x2="8" y2="14"/><line x1="12" y1="18" x2="12" y2="18"/><line x1="8" y1="18" x2="8" y2="18"/></svg></span>
          <span class="sl">Maliyet Sim.</span>
        </a>

        <div class="sn-sub">İthalat</div>

        <a href="/finans/cin-ofis" class="si {% if '/finans/cin-ofis' in rp %}active{% endif %}" title="Çin Ofis İçe Aktarma">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16.5 9.4 7.55 4.24"/><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg></span>
          <span class="sl">Çin Ofis</span>
        </a>

        {% if yetki('grafik.cin_siparis') or g_user.RolAd == 'Yönetim' %}
        <a href="/grafik/siparis" class="si {% if '/grafik/siparis' in rp %}active{% endif %}" title="Çin Sipariş">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg></span>
          <span class="sl">Çin Sipariş</span>
        </a>
        {% endif %}

        {% if yetki('grafik.maliyet') or g_user.RolAd == 'Yönetim' %}
        <a href="/grafik/sevkiyat" class="si {% if '/grafik/sevkiyat' in rp %}active{% endif %}" title="Sevkiyat & Maliyet">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 18H3c-.6 0-1-.4-1-1V7c0-.6.4-1 1-1h10c.6 0 1 .4 1 1v11"/><path d="M14 9h4l4 4v4c0 .6-.4 1-1 1h-2"/><circle cx="7" cy="18" r="2"/><path d="M15 18H9"/><circle cx="17" cy="18" r="2"/></svg></span>
          <span class="sl">Sevkiyat</span>
        </a>
        {% endif %}
      </div>
      {% endif %}

      <!-- ============ TICARET ============ -->
      {% if yetki('finans') or yetki('grafik.tedarikci') or g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' %}
      <div class="sn-sec sn-toggle{% if aktif_grup == 'ticaret' %} acik{% endif %}" data-grup="ticaret">
        <span class="sn-arrow">{% if aktif_grup == 'ticaret' %}▼{% else %}►{% endif %}</span>
        <svg class="sn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/></svg>
        <span class="sn-baslik">Ticaret</span>
        <span class="sn-count">3</span>
      </div>
      <div class="sn-grup{% if aktif_grup != 'ticaret' %} kapali{% endif %}" data-grup="ticaret">

        {% if yetki('finans') or g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' %}
        <a href="/finans/cari?tip=1" class="si {% if active == 'finans' and request.args.get('tip') == '1' %}active{% endif %}" title="Müşteriler">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></span>
          <span class="sl">Müşteriler</span>
        </a>

        <a href="/finans/cari?tip=2" class="si {% if active == 'finans' and request.args.get('tip') == '2' %}active{% endif %}" title="Finans Tedarikçileri">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18"/><path d="M5 21V7l8-4v18"/><path d="M19 21V11l-6-4"/><path d="M9 9v.01"/><path d="M9 12v.01"/><path d="M9 15v.01"/><path d="M9 18v.01"/></svg></span>
          <span class="sl">Finans Tedarik.</span>
        </a>
        {% endif %}

        {% if yetki('grafik.tedarikci') or g_user.RolAd == 'Yönetim' %}
        <a href="/grafik/tedarikci" class="si {% if '/grafik/tedarikci' in rp %}active{% endif %}" title="Grafik Tedarikçileri">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01"/><path d="M16 6h.01"/><path d="M12 6h.01"/><path d="M12 10h.01"/><path d="M12 14h.01"/><path d="M16 10h.01"/><path d="M16 14h.01"/><path d="M8 10h.01"/><path d="M8 14h.01"/></svg></span>
          <span class="sl">Grafik Tedarik.</span>
        </a>
        {% endif %}
      </div>
      {% endif %}

      <!-- ============ URETIM ============ -->
      {% if g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' %}
      <div class="sn-sec sn-toggle{% if aktif_grup == 'uretim' %} acik{% endif %}" data-grup="uretim">
        <span class="sn-arrow">{% if aktif_grup == 'uretim' %}▼{% else %}►{% endif %}</span>
        <svg class="sn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 20a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8l-7 5V8l-7 5V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M17 18h1"/><path d="M12 18h1"/><path d="M7 18h1"/></svg>
        <span class="sn-baslik">Üretim</span>
        <span class="sn-count">3</span>
      </div>
      <div class="sn-grup{% if aktif_grup != 'uretim' %} kapali{% endif %}" data-grup="uretim">

        <a href="/hedef/" class="si {% if active == 'hedef' and '/sapma' not in rp and '/sablon' not in rp %}active{% endif %}" title="Hedef Paneli">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg></span>
          <span class="sl">Hedef Paneli</span>
        </a>

        <a href="/hedef/sablon" class="si {% if '/hedef/sablon' in rp %}active{% endif %}" title="Şablon / Proses">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M12 11h4"/><path d="M12 16h4"/><path d="M8 11h.01"/><path d="M8 16h.01"/></svg></span>
          <span class="sl">Şablon / Proses</span>
        </a>

        <a href="/hedef/sapma" class="si {% if '/hedef/sapma' in rp %}active{% endif %}" title="Sapma Analizi">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg></span>
          <span class="sl">Sapma Analizi</span>
        </a>
      </div>
      {% endif %}

      <!-- ============ KALITE / TASARIM ============ -->
      {% if yetki('grafik.urun') or yetki('grafik.numune') or g_user.RolAd == 'Yönetim' %}
      <div class="sn-sec sn-toggle{% if aktif_grup == 'kalite' %} acik{% endif %}" data-grup="kalite">
        <span class="sn-arrow">{% if aktif_grup == 'kalite' %}▼{% else %}►{% endif %}</span>
        <svg class="sn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2"/><path d="M8.5 2h7"/><path d="M7 16h10"/></svg>
        <span class="sn-baslik">Kalite / Tasarım</span>
        <span class="sn-count">3</span>
      </div>
      <div class="sn-grup{% if aktif_grup != 'kalite' %} kapali{% endif %}" data-grup="kalite">

        <a href="/grafik/" class="si {% if active == 'grafik' and rp == '/grafik/' %}active{% endif %}" title="Grafik Paneli">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="13.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="10.5" r="2.5"/><circle cx="8.5" cy="7.5" r="2.5"/><circle cx="6.5" cy="12.5" r="2.5"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/></svg></span>
          <span class="sl">Grafik Paneli</span>
        </a>

        {% if yetki('grafik.urun') or g_user.RolAd == 'Yönetim' %}
        <a href="/grafik/urun" class="si {% if '/grafik/urun' in rp or '/grafik/kategori' in rp %}active{% endif %}" title="Ürün & Varyant">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2.97 12.92A2 2 0 0 0 2 14.63v3.24a2 2 0 0 0 .97 1.71l3 1.8a2 2 0 0 0 2.06 0L12 19v-5.5l-5-3-4.03 2.42Z"/><path d="m7 16.5-4.74-2.85"/><path d="m7 16.5 5-3"/><path d="M7 16.5v5.17"/><path d="M12 13.5V19l3.97 2.38a2 2 0 0 0 2.06 0l3-1.8a2 2 0 0 0 .97-1.71v-3.24a2 2 0 0 0-.97-1.71L17 10.5l-5 3Z"/><path d="m17 16.5-5-3"/><path d="m17 16.5 4.74-2.85"/><path d="M17 16.5v5.17"/><path d="M7.97 4.42A2 2 0 0 0 7 6.13v4.37l5 3 5-3V6.13a2 2 0 0 0-.97-1.71l-3-1.8a2 2 0 0 0-2.06 0l-3 1.8Z"/><path d="M12 8 7.26 5.15"/><path d="m12 8 4.74-2.85"/><path d="M12 13.5V8"/></svg></span>
          <span class="sl">Ürün & Varyant</span>
        </a>
        {% endif %}

        {% if yetki('grafik.numune') or g_user.RolAd == 'Yönetim' %}
        <a href="/grafik/numune" class="si {% if '/grafik/numune' in rp %}active{% endif %}" title="Numune Takip">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2"/><path d="M8.5 2h7"/><path d="M7 16h10"/></svg></span>
          <span class="sl">Numune Takip</span>
        </a>
        {% endif %}
      </div>
      {% endif %}

      <!-- ============ YONETIM ============ -->
      {% if g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' %}
      <div class="sn-sec sn-toggle{% if aktif_grup == 'yonetim' %} acik{% endif %}" data-grup="yonetim">
        <span class="sn-arrow">{% if aktif_grup == 'yonetim' %}▼{% else %}►{% endif %}</span>
        <svg class="sn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>
        <span class="sn-baslik">Yönetim</span>
        <span class="sn-count">5</span>
      </div>
      <div class="sn-grup{% if aktif_grup != 'yonetim' %} kapali{% endif %}" data-grup="yonetim">

        <a href="/yonetim/" class="si {% if active == 'yonetim' and rp == '/yonetim/' %}active{% endif %}" title="Yönetim Paneli">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg></span>
          <span class="sl">Yönetim Paneli</span>
        </a>

        <a href="/yonetim/kullanici" class="si {% if '/yonetim/kullanici' in rp %}active{% endif %}" title="Kullanıcılar">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/></svg></span>
          <span class="sl">Kullanıcılar</span>
        </a>

        <a href="/yonetim/rol" class="si {% if '/yonetim/rol' in rp %}active{% endif %}" title="Roller / Yetkiler">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/></svg></span>
          <span class="sl">Roller</span>
        </a>

        <a href="/yonetim/kur" class="si {% if '/yonetim/kur' in rp %}active{% endif %}" title="Kur Tanımları">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="M7 6h1v4"/><path d="m16.71 13.88.7.71-2.82 2.82"/></svg></span>
          <span class="sl">Kur</span>
        </a>

        <a href="/yonetim/log" class="si {% if '/yonetim/log' in rp %}active{% endif %}" title="Audit Log">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/></svg></span>
          <span class="sl">Audit Log</span>
        </a>
      </div>
      {% endif %}

      <button class="sb-tog" onclick="var s=document.getElementById('sidebar');s.classList.toggle('expanded');this.textContent=s.classList.contains('expanded')?'◀':'▶'">▶</button>
    </nav>

    <!-- SIDEBAR_LUCIDE_V3 - inline CSS + JS -->
    <style>
      /* ============ SIDEBAR ITEM (link) ============ */
      #sidebar .si {
        display: flex !important;
        align-items: center;
        gap: 10px;
        padding: 4px 8px !important;
        margin: 2px 6px;
        min-height: 36px !important;
        font-size: 13px !important;
        text-decoration: none;
        color: var(--text2);
        border-radius: 8px;
        transition: background 0.12s, color 0.12s;
        position: relative;
      }
      /* Icon kutusu */
      #sidebar .si .si-icon {
        flex: 0 0 32px;
        height: 32px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 8px;
        background: transparent;
        color: var(--text3);
        transition: background 0.12s, color 0.12s;
      }
      #sidebar .si .si-icon svg {
        width: 18px;
        height: 18px;
      }
      /* Hover */
      #sidebar .si:hover {
        background: rgba(249, 115, 22, 0.06);
      }
      #sidebar .si:hover .si-icon {
        background: rgba(249, 115, 22, 0.10);
        color: var(--sol, #f97316);
      }
      /* Aktif */
      #sidebar .si.active {
        background: rgba(249, 115, 22, 0.08);
        color: var(--sol-dark, #c2410c);
        font-weight: 600;
      }
      #sidebar .si.active .si-icon {
        background: var(--sol, #f97316);
        color: #fff;
      }
      #sidebar .si .sl {
        flex: 1;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      /* ============ GRUP BASLIGI (sn-toggle) ============ */
      #sidebar .sn-sec.sn-toggle {
        cursor: pointer;
        user-select: none;
        padding: 6px 10px;
        margin: 8px 6px 2px 6px;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.6px;
        text-transform: uppercase;
        color: var(--text3);
        display: flex;
        align-items: center;
        gap: 8px;
        border-radius: 6px;
        transition: background 0.12s;
      }
      #sidebar .sn-sec.sn-toggle:hover {
        background: rgba(0,0,0,0.04);
        color: var(--text2);
      }
      #sidebar .sn-sec.sn-toggle.acik {
        color: var(--text);
      }
      #sidebar .sn-sec.sn-toggle .sn-icon {
        width: 16px;
        height: 16px;
        flex-shrink: 0;
      }
      #sidebar .sn-arrow {
        font-size: 9px;
        color: var(--text3);
        width: 10px;
        flex-shrink: 0;
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

      /* ============ Collapsible animasyonu ============ */
      #sidebar .sn-grup {
        max-height: 800px;
        overflow: hidden;
        transition: max-height 0.18s ease-out;
      }
      #sidebar .sn-grup.kapali {
        max-height: 0;
      }
      #sidebar .sn-sub {
        padding: 4px 14px;
        margin-top: 4px;
        font-size: 9px;
        font-weight: 600;
        letter-spacing: 0.5px;
        color: var(--text3);
        text-transform: uppercase;
        opacity: 0.7;
      }
      /* Collapsed sidebar (icon-only) */
      #sidebar:not(.expanded) .sn-grup {
        max-height: none !important;
      }
      #sidebar:not(.expanded) .sn-sec.sn-toggle .sn-baslik,
      #sidebar:not(.expanded) .sn-sec.sn-toggle .sn-count,
      #sidebar:not(.expanded) .sn-sec.sn-toggle .sn-arrow,
      #sidebar:not(.expanded) .sn-sub,
      #sidebar:not(.expanded) .sl {
        display: none;
      }
      #sidebar:not(.expanded) .sn-sec.sn-toggle {
        padding: 4px;
        margin: 8px 8px 2px 8px;
        justify-content: center;
        background: rgba(0,0,0,0.03);
      }
      #sidebar:not(.expanded) .si {
        justify-content: center;
        padding: 4px !important;
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
            var simdiKapali = body.classList.toggle('kapali');
            h.classList.toggle('acik', !simdiKapali);
            var ar = h.querySelector('.sn-arrow');
            if (ar) ar.textContent = simdiKapali ? '►' : '▼';
          });
        });
      })();
    </script>
'''


def main():
    print("=" * 64)
    print("Sidebar Lucide Icons + 36x36 kutu + turuncu aktif")
    print("=" * 64)

    if not os.path.exists(BASE_HTML):
        print(f"  [HATA] {BASE_HTML} yok.")
        return 1

    with open(BASE_HTML, 'r', encoding='utf-8') as f:
        src = f.read()

    if MARKER in src:
        print("  [BILGI] Lucide v3 zaten ekli.")
        return 0

    # Eski sidebar bloku - hangi marker olursa olsun, '<!-- SIDEBAR -->' baslangic
    pattern = re.compile(
        r"    <!-- SIDEBAR -->.*?</nav>\s*\n(?:\s*<!--[^-]*-->\s*<style>.*?</style>\s*<script>.*?</script>\s*\n)?",
        re.DOTALL
    )
    m = pattern.search(src)
    if not m:
        # Eski format icin daha gevsek pattern
        pattern2 = re.compile(
            r"    <!-- SIDEBAR -->.*?</nav>\s*\n",
            re.DOTALL
        )
        m = pattern2.search(src)
        if not m:
            print("  [HATA] Mevcut sidebar bloku bulunamadi.")
            return 1
        # eski stil/script sonrasi var mi kontrol
        after = src[m.end():m.end()+2000]
        if "SIDEBAR_COMPACT_V2" in after or "<!-- inline CSS" in after:
            # Eski compact v2 stil/script bloklarini da kaldir
            sidescript_pattern = re.compile(
                r"    <!-- SIDEBAR_COMPACT_V2[^-]*-->\s*<style>.*?</style>\s*<script>.*?</script>",
                re.DOTALL
            )
            ss = sidescript_pattern.search(src, m.end())
            if ss:
                # Genis pattern: hem sidebar hem stil/script
                end_pos = ss.end() + 1
                while end_pos < len(src) and src[end_pos] in '\n\r':
                    end_pos += 1
                m = type('M', (), {'start': lambda s=m.start(): s, 'end': lambda e=end_pos: e})()

    # Yedek
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = BASE_HTML + f'.bak_{ts}'
    shutil.copy2(BASE_HTML, bp)
    print(f"  [OK] Yedek: {bp}")

    # Eski compact v2 stili da varsa kaldirilsin
    new_src = src[:m.start()] + YENI_SIDEBAR + src[m.end():]

    # SIDEBAR_COMPACT_V2 stil ve script'i temizle (yeni v3 zaten icinde var)
    cleanup_pattern = re.compile(
        r"\s*<!-- SIDEBAR_COMPACT_V2[^-]*-->\s*<style>.*?</style>\s*<script>.*?</script>\s*",
        re.DOTALL
    )
    new_src = cleanup_pattern.sub('\n', new_src)

    with open(BASE_HTML, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Sidebar Lucide ikonlu, kompakt, kutulu uygulandi.")
    print()
    print("YAPILACAK:")
    print("  1) Browser Ctrl+F5")
    print()
    print("Beklenen:")
    print("  - Tum ikonlar Lucide tarzi outline")
    print("  - 36x36 kutu, 8px radius")
    print("  - Aktif: turuncu BG + beyaz icon")
    print("  - Hover: soft turuncu BG")
    print("  - Grup basligi = ikon + yazi + sayi")
    print("  - Acik grup: koyu yazi, kapali: gri")
    print()
    print("Geri donus:")
    print(f"  copy \"{bp}\" \"{BASE_HTML}\"")
    return 0


if __name__ == '__main__':
    sys.exit(main())
