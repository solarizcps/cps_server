# -*- coding: utf-8 -*-
"""
app.py'ye uretim_yonetim blueprint'i ekler.
Once yedek alir, sonra ekler.
"""
import os
import shutil
from datetime import datetime

APP_PATH = r'C:\cps_dev\app.py'
YEDEK_PATH = r'C:\cps_dev\app.py.YEDEK_PATCH_' + datetime.now().strftime('%Y%m%d_%H%M%S')

# 1. Yedek al
shutil.copy(APP_PATH, YEDEK_PATH)
print(f"OK Yedek alindi: {YEDEK_PATH}")

# 2. Mevcut icerigi oku
with open(APP_PATH, 'r', encoding='utf-8') as f:
    icerik = f.read()
print(f"OK app.py okundu: {len(icerik)} karakter")

# 3. Zaten eklenmis mi kontrol et
if 'uretim_yonetim' in icerik:
    print("UYARI: 'uretim_yonetim' zaten var, ekleme yapilmiyor.")
    exit(0)

# 4. IMPORT satirini ekle (usta_bp import'undan sonra)
arama1 = 'from modules.usta import usta_bp'
yeni1 = 'from modules.usta import usta_bp\nfrom modules.uretim_yonetim.routes import uretim_yonetim_bp'

if arama1 not in icerik:
    print(f"HATA: '{arama1}' bulunamadi!")
    exit(1)
icerik = icerik.replace(arama1, yeni1, 1)
print("OK Import satiri eklendi")

# 5. REGISTER_BLUEPRINT satirini ekle
arama2 = 'app.register_blueprint(usta_bp)'
yeni2 = 'app.register_blueprint(usta_bp)\napp.register_blueprint(uretim_yonetim_bp)'

if arama2 not in icerik:
    print(f"HATA: '{arama2}' bulunamadi!")
    exit(1)
icerik = icerik.replace(arama2, yeni2, 1)
print("OK Register satiri eklendi")

# 6. Yaz
with open(APP_PATH, 'w', encoding='utf-8') as f:
    f.write(icerik)
print(f"OK app.py guncellendi: {len(icerik)} karakter")

# 7. Dogrula
with open(APP_PATH, 'r', encoding='utf-8') as f:
    final = f.read()

import_var = 'from modules.uretim_yonetim.routes import uretim_yonetim_bp' in final
register_var = 'app.register_blueprint(uretim_yonetim_bp)' in final

print("\n=== DOGRULAMA ===")
print(f"Import satiri var mi      : {import_var}")
print(f"Register satiri var mi    : {register_var}")

if import_var and register_var:
    print("\nBASARILI! Flask'i restart edebilirsin.")
else:
    print("\nHATA: Eksik bir sey var, yedekten geri al!")