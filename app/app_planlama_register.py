# -*- coding: utf-8 -*-
"""
app.py'ye planlama blueprint'i ekler.
Once yedek alir, sonra ekler.
"""
import shutil
from datetime import datetime

APP_PATH = r'C:\cps_dev\app.py'
YEDEK_PATH = APP_PATH + '.YEDEK_PLANLAMA_' + datetime.now().strftime('%Y%m%d_%H%M%S')

shutil.copy(APP_PATH, YEDEK_PATH)
print(f"OK Yedek: {YEDEK_PATH}")

with open(APP_PATH, 'r', encoding='utf-8') as f:
    icerik = f.read()
print(f"OK Okundu: {len(icerik)} karakter")

if 'modules.planlama' in icerik:
    print("UYARI: planlama zaten kayitli, ekleme yapilmiyor.")
    exit(0)

# Import satiri ekle (uretim_yonetim sonrasina)
arama1 = 'from modules.uretim_yonetim.routes import uretim_yonetim_bp'
yeni1 = arama1 + '\nfrom modules.planlama.routes import planlama_bp'
if arama1 not in icerik:
    print(f"HATA: '{arama1}' bulunamadi!")
    exit(1)
icerik = icerik.replace(arama1, yeni1, 1)
print("OK Import satiri eklendi")

# Register satiri ekle
arama2 = 'app.register_blueprint(uretim_yonetim_bp)'
yeni2 = arama2 + '\napp.register_blueprint(planlama_bp)'
if arama2 not in icerik:
    print(f"HATA: '{arama2}' bulunamadi!")
    exit(1)
icerik = icerik.replace(arama2, yeni2, 1)
print("OK Register satiri eklendi")

with open(APP_PATH, 'w', encoding='utf-8') as f:
    f.write(icerik)
print(f"OK app.py guncellendi: {len(icerik)} karakter")

# Dogrulama
with open(APP_PATH, 'r', encoding='utf-8') as f:
    final = f.read()
imp_var = 'from modules.planlama.routes import planlama_bp' in final
reg_var = 'app.register_blueprint(planlama_bp)' in final

print("\n=== DOGRULAMA ===")
print(f"Import: {imp_var}")
print(f"Register: {reg_var}")
if imp_var and reg_var:
    print("\nBASARILI!")
else:
    print(f"\nHATA - Yedek: {YEDEK_PATH}")