# -*- coding: utf-8 -*-
"""
Karar Masasi yeniden adlandirma:
1. Encoding fix: 'YÃ¶netim' -> 'Yönetim'
2. URL: /proses-takip -> /karar-masasi
3. Template: 'planlama/proses_takip.html' -> 'planlama/karar_masasi.html'
4. Yorumlar guncelleniyor
"""
import shutil
from datetime import datetime

ROUTES = r'C:\cps_dev\modules\planlama\routes.py'
YEDEK = ROUTES + '.YEDEK_RENAME_' + datetime.now().strftime('%Y%m%d_%H%M%S')

shutil.copy(ROUTES, YEDEK)
print(f"[OK] Yedek: {YEDEK}")

with open(ROUTES, 'rb') as f:
    raw = f.read()
print(f"[OK] Okundu: {len(raw)} byte")

# UTF-8 olarak decode et (encoding bozuksa cp1252 dene)
try:
    icerik = raw.decode('utf-8')
    print("[OK] UTF-8 decode")
except UnicodeDecodeError:
    icerik = raw.decode('cp1252')
    print("[OK] CP1252 decode")

degisiklikler = []

# 1. Encoding fix
if 'YÃ¶netim' in icerik:
    icerik = icerik.replace('YÃ¶netim', 'Yönetim')
    degisiklikler.append("Encoding fix: 'YÃ¶netim' -> 'Yönetim'")

# 2. URL: /proses-takip -> /karar-masasi  (iki yerde)
if "@planlama_bp.route('/proses-takip', methods=['GET'])" in icerik:
    icerik = icerik.replace(
        "@planlama_bp.route('/proses-takip', methods=['GET'])",
        "@planlama_bp.route('/karar-masasi', methods=['GET'])"
    )
    degisiklikler.append("URL: /proses-takip -> /karar-masasi")

if "@planlama_bp.route('/proses-takip/data', methods=['GET'])" in icerik:
    icerik = icerik.replace(
        "@planlama_bp.route('/proses-takip/data', methods=['GET'])",
        "@planlama_bp.route('/karar-masasi/data', methods=['GET'])"
    )
    degisiklikler.append("URL: /proses-takip/data -> /karar-masasi/data")

# 3. Function isimleri (route handler)
if "def proses_takip():" in icerik:
    icerik = icerik.replace("def proses_takip():", "def karar_masasi():")
    degisiklikler.append("Func: proses_takip() -> karar_masasi()")

if "def proses_takip_data():" in icerik:
    icerik = icerik.replace("def proses_takip_data():", "def karar_masasi_data():")
    degisiklikler.append("Func: proses_takip_data() -> karar_masasi_data()")

# 4. Template path
if "'planlama/proses_takip.html'" in icerik:
    icerik = icerik.replace(
        "'planlama/proses_takip.html'",
        "'planlama/karar_masasi.html'"
    )
    degisiklikler.append("Template: proses_takip.html -> karar_masasi.html")

# 5. Yorumlardaki adlandirmalar
icerik = icerik.replace(
    "SOLARIZ CPS - PLANLAMA / PROSES TAKIP (Faz 2)",
    "SOLARIZ CPS - PLANLAMA / KARAR MASASI (Faz 2)"
)

# Yaz
with open(ROUTES, 'w', encoding='utf-8') as f:
    f.write(icerik)
print(f"[OK] routes.py guncellendi: {len(icerik)} karakter")

print("\n=== DEGISIKLIKLER ===")
for d in degisiklikler:
    print(f"  - {d}")

# Dogrulama
with open(ROUTES, 'r', encoding='utf-8') as f:
    final = f.read()

print("\n=== DOGRULAMA ===")
print(f"  /karar-masasi: {'EVET' if '/karar-masasi' in final else 'HAYIR'}")
print(f"  Yönetim: {'EVET' if 'Yönetim' in final else 'HAYIR'}")
print(f"  YÃ¶netim: {'YOK (iyi)' if 'YÃ¶netim' not in final else 'HALA VAR (kotu)'}")
print(f"  karar_masasi.html: {'EVET' if 'karar_masasi.html' in final else 'HAYIR'}")
print(f"  proses_takip.html (eski): {'YOK (iyi)' if 'proses_takip.html' not in final else 'HALA VAR (kotu)'}")
print(f"\n[YEDEK]: {YEDEK}")