# -*- coding: utf-8 -*-
"""
base.html sidebar:
- 'Karar Masası' linkinin USTUNE 'Proses Takip' linki ekle
- sn-count: 1 -> 2
"""
import shutil
from datetime import datetime

BASE = r'C:\cps_dev\templates\base.html'
YEDEK = BASE + '.YEDEK_PROSES_TAKIP_LINK_' + datetime.now().strftime('%Y%m%d_%H%M%S')

shutil.copy(BASE, YEDEK)
print(f"[OK] Yedek: {YEDEK}")

with open(BASE, 'rb') as f:
    raw = f.read()
try:
    icerik = raw.decode('utf-8')
except:
    icerik = raw.decode('cp1252')

print(f"[OK] Okundu: {len(icerik)} karakter")

# Zaten ekli mi?
if '/planlama/proses-takip' in icerik:
    print("[UYARI] /planlama/proses-takip linki zaten var, ekleme yapilmiyor.")
    exit(0)

# 1. PROSES TAKIP linkini Karar Masasi'nin USTUNE ekle
PROSES_TAKIP_LINK = '''        <a href="/planlama/proses-takip" class="si {% if '/planlama/proses-takip' in rp %}active{% endif %}" title="Proses Takip">
          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg></span>
          <span class="sl">Proses Takip</span>
        </a>

'''

# Karar Masasi linkini bul ve ustune ekle
KARAR_MASASI_LINK = '<a href="/planlama/karar-masasi"'
if KARAR_MASASI_LINK not in icerik:
    print(f"[HATA] Karar Masasi linki bulunamadi: '{KARAR_MASASI_LINK}'")
    exit(1)

# Tam satir (indent ile birlikte) bul
idx = icerik.find(KARAR_MASASI_LINK)
# Geriye dogru git, satirin basini bul
satir_basi = icerik.rfind('\n', 0, idx) + 1
# Indent ile birlikte ekle
icerik = icerik[:satir_basi] + PROSES_TAKIP_LINK + icerik[satir_basi:]
print("[OK] Proses Takip linki eklendi (Karar Masasi ustune)")

# 2. sn-count: 1 -> 2 (sadece Planlama grubunda)
# Aramak: 'data-grup="planlama"' bloğunda 'sn-count">1</span>'
import re
# Hedef: planlama grubu sn-sec içindeki <span class="sn-count">1</span>
desen = r'(data-grup="planlama">[^<]*<span class="sn-arrow">[^<]*</span>\s*<svg[^>]*>.*?</svg>\s*<span class="sn-baslik">Planlama</span>\s*<span class="sn-count">)1(</span>)'
yeni_icerik, sayi = re.subn(desen, r'\g<1>2\g<2>', icerik, count=1, flags=re.DOTALL)

if sayi > 0:
    icerik = yeni_icerik
    print(f"[OK] sn-count: 1 -> 2 ({sayi} yer)")
else:
    # Daha basit fallback: planlama grubu yakinindaki tek 1 -> 2
    # Manuel str_replace
    arama = '<span class="sn-baslik">Planlama</span>\n        <span class="sn-count">1</span>'
    yeni = '<span class="sn-baslik">Planlama</span>\n        <span class="sn-count">2</span>'
    if arama in icerik:
        icerik = icerik.replace(arama, yeni, 1)
        print("[OK] sn-count: 1 -> 2 (fallback)")
    else:
        print("[UYARI] sn-count guncellenmedi - manuel kontrol gerekebilir")

with open(BASE, 'w', encoding='utf-8') as f:
    f.write(icerik)
print(f"[OK] base.html guncellendi: {len(icerik)} karakter")

# Dogrulama
with open(BASE, 'r', encoding='utf-8') as f:
    final = f.read()
print("\n=== DOGRULAMA ===")
print(f"  /planlama/proses-takip: {'EVET' if '/planlama/proses-takip' in final else 'HAYIR'}")
print(f"  /planlama/karar-masasi: {'EVET' if '/planlama/karar-masasi' in final else 'HAYIR'}")
print(f"  Proses Takip metni: {'EVET' if '<span class=\"sl\">Proses Takip</span>' in final else 'HAYIR'}")
print(f"  Karar Masası metni: {'EVET' if '<span class=\"sl\">Karar Masası</span>' in final else 'HAYIR'}")
print(f"\n[YEDEK]: {YEDEK}")