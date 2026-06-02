# -*- coding: utf-8 -*-
"""
base.html'e PLANLAMA sidebar grubu ekler.
Konum: URETIM grubunun ALTINA, KALITE grubunun USTUNE.
"""
import shutil
from datetime import datetime

BASE_PATH = r'C:\cps_dev\templates\base.html'
YEDEK_PATH = BASE_PATH + '.YEDEK_PLANLAMA_' + datetime.now().strftime('%Y%m%d_%H%M%S')

shutil.copy(BASE_PATH, YEDEK_PATH)
print(f"OK Yedek: {YEDEK_PATH}")

with open(BASE_PATH, 'r', encoding='utf-8') as f:
    icerik = f.read()
print(f"OK Okundu: {len(icerik)} karakter")

# Zaten ekli mi?
if "data-grup=\"planlama\"" in icerik:
    print("UYARI: planlama grubu zaten var, ekleme yapilmiyor.")
    exit(0)

# 1. AKTIF GRUP MANTIGINA SATIR EKLE
# Mevcut: {% if active == 'yonetim' %}{% set aktif_grup = 'yonetim' %}{% endif %}
# Bunun ALTINA: {% if active == 'planlama' %}{% set aktif_grup = 'planlama' %}{% endif %}
arama_aktif = "{% if active == 'yonetim' %}{% set aktif_grup = 'yonetim' %}{% endif %}"
yeni_aktif = arama_aktif + "\n      {% if active == 'planlama' %}{% set aktif_grup = 'planlama' %}{% endif %}"
if arama_aktif not in icerik:
    print(f"HATA: aktif_grup mantigi bulunamadi!")
    exit(1)
icerik = icerik.replace(arama_aktif, yeni_aktif, 1)
print("OK aktif_grup mantigi guncellendi")

# 2. PLANLAMA GRUBU EKLE
# URETIM grubu kapanis </div> sonrasi {% endif %} sonrasi -> KALITE oncesi
# Yani: <!-- ============ KALITE / TASARIM ============ --> isaretinden ONCEYE ekle
PLANLAMA_GRUBU = """
      <!-- ============ PLANLAMA ============ -->
      {% if g_user.RolAd == 'Yönetim' or g_user.KullaniciAdi == 'admin' %}
      <div class="sn-sec sn-toggle{% if aktif_grup == 'planlama' %} acik{% endif %}" data-grup="planlama">
        <span class="sn-arrow">{% if aktif_grup == 'planlama' %}▼{% else %}►{% endif %}</span>
        <svg class="sn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M9 14l2 2 4-4"/></svg>
        <span class="sn-baslik">Planlama</span>
        <span class="sn-count">1</span>
      </div>
      <div class="sn-grup{% if aktif_grup != 'planlama' %} kapali{% endif %}" data-grup="planlama">

        <a href="/planlama/proses-takip" class="si {% if '/planlama/proses-takip' in rp %}active{% endif %}" title="Proses Takip">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11H5a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7a2 2 0 0 0-2-2h-4"/><path d="M12 11V3"/><path d="m8 7 4-4 4 4"/></svg></span>
          <span class="sl">Proses Takip</span>
        </a>

      </div>
      {% endif %}

      """

KALITE_MARKER = "<!-- ============ KALITE / TASARIM ============ -->"
if KALITE_MARKER not in icerik:
    print(f"HATA: KALITE marker bulunamadi!")
    exit(1)

icerik = icerik.replace(KALITE_MARKER, PLANLAMA_GRUBU + KALITE_MARKER, 1)
print("OK Planlama grubu eklendi (URETIM altina, KALITE ustune)")

with open(BASE_PATH, 'w', encoding='utf-8') as f:
    f.write(icerik)
print(f"OK base.html guncellendi: {len(icerik)} karakter")

# Dogrulama
with open(BASE_PATH, 'r', encoding='utf-8') as f:
    final = f.read()
sayac = final.count('data-grup="planlama"')
print(f"\n=== DOGRULAMA ===")
print(f"data-grup='planlama' sayisi: {sayac} (2 olmali: bir sn-sec, bir sn-grup)")
print(f"aktif_grup planlama: {'planlama' in final and 'aktif_grup' in final}")
if sayac == 2:
    print("\nBASARILI!")
else:
    print(f"\nHATA - Yedek: {YEDEK_PATH}")