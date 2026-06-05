# -*- coding: utf-8 -*-
"""
base.html sidebar - mevcut 'Proses Takip' linki -> 'Karar Masasi'
URL: /planlama/proses-takip -> /planlama/karar-masasi
Metin: 'Proses Takip' -> 'Karar Masası'
Title: 'Proses Takip' -> 'Karar Masası'
"""
import shutil
from datetime import datetime

BASE = r'C:\cps_dev\templates\base.html'
YEDEK = BASE + '.YEDEK_KARARMASASI_' + datetime.now().strftime('%Y%m%d_%H%M%S')

shutil.copy(BASE, YEDEK)
print(f"[OK] Yedek: {YEDEK}")

with open(BASE, 'rb') as f:
    raw = f.read()

try:
    icerik = raw.decode('utf-8')
except:
    icerik = raw.decode('cp1252')

print(f"[OK] Okundu: {len(icerik)} karakter")

degisiklikler = []

# 1. URL guncelle (href + active marker)
if "/planlama/proses-takip" in icerik:
    sayi = icerik.count("/planlama/proses-takip")
    icerik = icerik.replace("/planlama/proses-takip", "/planlama/karar-masasi")
    degisiklikler.append(f"URL: /planlama/proses-takip -> /planlama/karar-masasi ({sayi} yer)")

# 2. Title attribute
if 'title="Proses Takip"' in icerik:
    icerik = icerik.replace('title="Proses Takip"', 'title="Karar Masası"')
    degisiklikler.append("Title: 'Proses Takip' -> 'Karar Masası'")

# 3. Link metni (sl span)
if '<span class="sl">Proses Takip</span>' in icerik:
    icerik = icerik.replace(
        '<span class="sl">Proses Takip</span>',
        '<span class="sl">Karar Masası</span>'
    )
    degisiklikler.append("Metin: 'Proses Takip' -> 'Karar Masası'")

with open(BASE, 'w', encoding='utf-8') as f:
    f.write(icerik)
print(f"[OK] base.html guncellendi: {len(icerik)} karakter")

print("\n=== DEGISIKLIKLER ===")
for d in degisiklikler:
    print(f"  - {d}")

# Dogrulama
with open(BASE, 'r', encoding='utf-8') as f:
    final = f.read()

print("\n=== DOGRULAMA ===")
print(f"  /planlama/karar-masasi: {'EVET' if '/planlama/karar-masasi' in final else 'HAYIR'}")
print(f"  /planlama/proses-takip (eski): {'YOK (iyi)' if '/planlama/proses-takip' not in final else 'HALA VAR (kotu)'}")
print(f"  Karar Masası: {'EVET' if 'Karar Masası' in final else 'HAYIR'}")
print(f"  Planlama grubu (data-grup): {'EVET' if 'data-grup=\"planlama\"' in final else 'HAYIR'}")
print(f"\n[YEDEK]: {YEDEK}")