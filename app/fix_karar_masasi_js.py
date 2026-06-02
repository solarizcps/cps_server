# -*- coding: utf-8 -*-
"""planlama_karar_masasi.js icindeki URL'i guncelle"""
import shutil
from datetime import datetime

JS = r'C:\cps_dev\static\js\planlama_karar_masasi.js'
YEDEK = JS + '.YEDEK_' + datetime.now().strftime('%Y%m%d_%H%M%S')

shutil.copy(JS, YEDEK)

with open(JS, 'rb') as f:
    raw = f.read()

try:
    icerik = raw.decode('utf-8')
except:
    icerik = raw.decode('cp1252')

degisiklikler = []

# Ana URL fix
if "'/planlama/proses-takip/data'" in icerik:
    icerik = icerik.replace(
        "'/planlama/proses-takip/data'",
        "'/planlama/karar-masasi/data'"
    )
    degisiklikler.append("URL: /planlama/proses-takip/data -> /planlama/karar-masasi/data")

# Yorumlar
icerik = icerik.replace(
    'PLANLAMA / PROSES TAKIP',
    'PLANLAMA / KARAR MASASI'
)
icerik = icerik.replace(
    'Karar masasi gorunumu',
    'Karar masasi gorunumu'
)

with open(JS, 'w', encoding='utf-8') as f:
    f.write(icerik)

print(f"[OK] planlama_karar_masasi.js guncellendi")
for d in degisiklikler:
    print(f"  - {d}")

# Dogrulama
with open(JS, 'r', encoding='utf-8') as f:
    final = f.read()
print(f"\n=== DOGRULAMA ===")
print(f"  /karar-masasi/data: {'EVET' if '/karar-masasi/data' in final else 'HAYIR'}")
print(f"  /proses-takip/data (eski): {'YOK (iyi)' if '/proses-takip/data' not in final else 'HALA VAR (kotu)'}")
print(f"\n[YEDEK]: {YEDEK}")