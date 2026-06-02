# -*- coding: utf-8 -*-
"""
app.py'ye proses_takip_bp blueprint'i ekler.
Once yedek alir, sonra import + register satirlari ekler.
"""
import shutil
from datetime import datetime

APP = r'C:\cps_dev\app.py'
YEDEK = APP + '.YEDEK_PROSES_TAKIP_' + datetime.now().strftime('%Y%m%d_%H%M%S')

shutil.copy(APP, YEDEK)
print(f"[OK] Yedek: {YEDEK}")

with open(APP, 'r', encoding='utf-8') as f:
    icerik = f.read()
print(f"[OK] Okundu: {len(icerik)} karakter")

if 'proses_takip_bp' in icerik:
    print("[UYARI] proses_takip_bp zaten kayitli, ekleme yapilmiyor.")
    exit(0)

# 1. Import satiri
arama1 = 'from modules.planlama.routes import planlama_bp'
yeni1 = arama1 + '\nfrom modules.planlama.proses_takip import proses_takip_bp'
if arama1 not in icerik:
    print(f"[HATA] Import satiri bulunamadi: '{arama1}'")
    exit(1)
icerik = icerik.replace(arama1, yeni1, 1)
print("[OK] Import satiri eklendi")

# 2. Register satiri
arama2 = 'app.register_blueprint(planlama_bp)'
yeni2 = arama2 + '\napp.register_blueprint(proses_takip_bp)'
if arama2 not in icerik:
    print(f"[HATA] Register satiri bulunamadi: '{arama2}'")
    exit(1)
icerik = icerik.replace(arama2, yeni2, 1)
print("[OK] Register satiri eklendi")

with open(APP, 'w', encoding='utf-8') as f:
    f.write(icerik)
print(f"[OK] app.py guncellendi: {len(icerik)} karakter")

# Dogrulama
with open(APP, 'r', encoding='utf-8') as f:
    final = f.read()
imp_var = 'from modules.planlama.proses_takip import proses_takip_bp' in final
reg_var = 'app.register_blueprint(proses_takip_bp)' in final

print("\n=== DOGRULAMA ===")
print(f"  Import: {imp_var}")
print(f"  Register: {reg_var}")
if imp_var and reg_var:
    print("\n[BASARILI] proses_takip_bp kaydi tamam.")
else:
    print(f"\n[HATA] Geri yuklemek icin yedek: {YEDEK}")