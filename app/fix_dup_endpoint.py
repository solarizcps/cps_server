# -*- coding: utf-8 -*-
"""
routes.py icindeki TEKRAR EDEN darbogaz_ozet endpoint'ini siler.
Sadece SONUNCUSUNU birakir.
"""
import re
import shutil
from datetime import datetime

PATH = r'C:\cps_dev\modules\hedef\routes.py'
YEDEK = PATH + '.YEDEK_DUPFIX_' + datetime.now().strftime('%Y%m%d_%H%M%S')

# 1. Yedek
shutil.copy(PATH, YEDEK)
print(f"OK Yedek: {YEDEK}")

# 2. Dosyayi oku
with open(PATH, 'r', encoding='utf-8') as f:
    icerik = f.read()
print(f"OK Okundu: {len(icerik)} karakter")

# 3. Tum darbogaz_ozet bloklarini bul
# Pattern: "# DARBOGAZ ENTEGRASYONU" yorum bloğundan sonraki tum endpoint
# Daha basit: @hedef_bp.route('/darbogaz-ozet'...) ile baslayan ve def darbogaz_ozet() icinden olusan blogu yakala

# Marker bul
marker = '@hedef_bp.route(\'/darbogaz-ozet\''
sayim = icerik.count(marker)
print(f"Bulunan endpoint sayisi: {sayim}")

if sayim < 2:
    print("UYARI: 2'den az endpoint var, duplicate yok!")
    print("Sorun baska yerde olabilir.")
    exit(0)

# 4. SONUNCUSUNU bul ve oncesini sakla
# Strateji: dosyayi marker'a gore split et, son block kalsin
parts = icerik.split(marker)
# parts[0] = en bastaki kod (marker oncesi)
# parts[1], parts[2], ... = her marker sonrasi
# Son blok: parts[-1] (en sondaki endpoint)

print(f"Parts: {len(parts)}")

# Yontem: ilk N-1 marker blogunu sil, son blogu birak
# parts[0] + (son markerli blok)
# Ancak parts[1] blogu sonu marker ile bitmiyor, kendi icinde bitmis
# Bu yuzden parts[1]...parts[-2] arasini at, parts[-1]'i marker ile birlikte ekle

if len(parts) > 2:
    # Birden fazla duplicate var
    yeni_icerik = parts[0] + marker + parts[-1]
elif len(parts) == 2:
    # Tek bir marker var ama sayim 2 dedi? Kontrol
    yeni_icerik = parts[0] + marker + parts[-1]

# 5. Eski tekrar bloklarinin SONUNDAKI yetim "exception" kismini temizle
# (Genelde def darbogaz_ozet() bloğu sonunda return jsonify([]) ile biter)
# Ek temizlik gerekirse buraya

# 6. Yaz
with open(PATH, 'w', encoding='utf-8') as f:
    f.write(yeni_icerik)
print(f"OK Yazildi: {len(yeni_icerik)} karakter (fark: {len(icerik) - len(yeni_icerik)})")

# 7. Dogrulama
with open(PATH, 'r', encoding='utf-8') as f:
    final = f.read()
yeni_sayim = final.count(marker)
print(f"\n=== DOGRULAMA ===")
print(f"Endpoint sayisi: {yeni_sayim} (1 olmali)")

if yeni_sayim == 1:
    print("BASARILI! Flask'i restart edebilirsin.")
else:
    print("HATA: Hala duplicate var, yedekten geri al!")
    print(f"Yedek: {YEDEK}")