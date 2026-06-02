# -*- coding: utf-8 -*-
"""karar_masasi.html icindeki JS src referansini guncelle"""
import shutil
from datetime import datetime

HTML = r'C:\cps_dev\templates\planlama\karar_masasi.html'
YEDEK = HTML + '.YEDEK_' + datetime.now().strftime('%Y%m%d_%H%M%S')

shutil.copy(HTML, YEDEK)

with open(HTML, 'rb') as f:
    raw = f.read()

try:
    icerik = raw.decode('utf-8')
except:
    icerik = raw.decode('cp1252')

degisiklikler = []

if 'planlama_proses_takip.js' in icerik:
    icerik = icerik.replace('planlama_proses_takip.js', 'planlama_karar_masasi.js')
    degisiklikler.append("JS src: planlama_proses_takip.js -> planlama_karar_masasi.js")

# Baslik (gorsel)
icerik = icerik.replace(
    'Planlama / Proses Takip',
    'Planlama / Karar Masası'
)
icerik = icerik.replace(
    'Planlama / Proses Takip · Solariz CPS',
    'Planlama / Karar Masası · Solariz CPS'
)

with open(HTML, 'w', encoding='utf-8') as f:
    f.write(icerik)

print(f"[OK] karar_masasi.html guncellendi")
for d in degisiklikler:
    print(f"  - {d}")
print(f"  - Baslik: 'Planlama / Proses Takip' -> 'Planlama / Karar Masası'")
print(f"\n[YEDEK]: {YEDEK}")