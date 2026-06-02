"""PATCH: _son_proses_yapilan biten okusun + kategori_durum son proses miktari.

Bug 1: _son_proses_yapilan eski 'yapilan' okuyor -> 'biten' okumali
Bug 2: hesapla_kategori_durum tum proseslerin biten'ini TOPLUYOR -> son prosesin biten'ini almali
"""
import io, sys, shutil, time

KP = r'C:\cps_dev\modules\hedef\korgun_v2.py'
MARKER = '/* SON PROSES BIT EN FIX */'

with io.open(KP, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: zaten uygulanmis')
    sys.exit(0)

# === BUG 1: _son_proses_yapilan biten okusun ===
OLD1 = """def _son_proses_yapilan(prosesler):
    if not prosesler:
        return 0, None
    max_kod = -1
    son_yp = 0
    son_adi = None
    for p in prosesler:
        kod = p.get('proses_kod', '')
        try:
            kod_int = int(kod)
        except Exception:
            continue
        if kod_int > max_kod:
            max_kod = kod_int
            son_yp = int(p.get('yapilan', 0) or 0)
            son_adi = p.get('proses_adi')
    return son_yp, son_adi"""

NEW1 = """def _son_proses_yapilan(prosesler):
    \"\"\"En yuksek proses_kod'lu prosesin BITEN miktari.
    /* SON PROSES BIT EN FIX */
    Yeni format: 'biten' okur. Eski format: 'yapilan' fallback.
    \"\"\"
    if not prosesler:
        return 0, None
    max_kod = -1
    son_yp = 0
    son_adi = None
    for p in prosesler:
        kod = p.get('proses_kod', '')
        try:
            kod_int = int(kod)
        except Exception:
            continue
        if kod_int > max_kod:
            max_kod = kod_int
            bt = p.get('biten')
            if bt is None:
                bt = p.get('yapilan', 0)
            son_yp = int(bt or 0)
            son_adi = p.get('proses_adi')
    return son_yp, son_adi"""

if OLD1 not in src:
    print('HATA: _son_proses_yapilan anchor bulunamadi')
    sys.exit(1)

new_src = src.replace(OLD1, NEW1, 1)

# === BUG 2: kategori_durum'da son proses miktari (toplama degil) ===
# Mevcut kod TUM proseslerin biten'ini topluyor.
# Dogrusu: son siralanan prosesin biten'i.
OLD2 = """    def _kategori_uretim_kontrol(emirler, kategori):
        biten_toplam = 0
        kesim_disi_var = False
        for e in emirler or []:
            for p in e.get('prosesler', []) or []:
                kod = str(p.get('proses_kod', '')).strip()
                bt = p.get('biten')
                if bt is None:
                    bt = p.get('yapilan', 0)
                yp = int(bt or 0)
                if yp <= 0:
                    continue
                biten_toplam += yp
                if kod != KESIM_PROSES_KODU:
                    kesim_disi_var = True"""

NEW2 = """    def _kategori_uretim_kontrol(emirler, kategori):
        \"\"\"Bu kategoride: SON proses miktari (toplama DEGIL).
        Her emir kendi son prosesinin biten miktarini katkilar.
        \"\"\"
        biten_toplam = 0
        kesim_disi_var = False
        for e in emirler or []:
            # Bu emirin SON prosesini bul (max proses_kod)
            son_yp, son_adi = _son_proses_yapilan(e.get('prosesler', []))
            biten_toplam += son_yp
            # Kesim disi proses var mi kontrolu (kategori_durum mesaji icin)
            for p in e.get('prosesler', []) or []:
                kod = str(p.get('proses_kod', '')).strip()
                bt = p.get('biten')
                if bt is None:
                    bt = p.get('yapilan', 0)
                if int(bt or 0) > 0 and kod != KESIM_PROSES_KODU:
                    kesim_disi_var = True"""

if OLD2 not in new_src:
    print('HATA: _kategori_uretim_kontrol anchor bulunamadi')
    sys.exit(1)

new_src = new_src.replace(OLD2, NEW2, 1)

# === BUG 3: hesapla_kesim_toplam zaten biten okuyor ama kontrol et ===
# (zaten dogru - degistirme)

bak = KP + '.bak_pre_sonproses_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(KP, bak)
print('Yedek: ' + bak)

with io.open(KP, 'w', encoding='utf-8') as f:
    f.write(new_src)

artis = len(new_src) - len(src)
print('OK: 2 bug fixed (' + str(artis) + ' byte)')
print('  - _son_proses_yapilan: biten okur (yapilan fallback)')
print('  - _kategori_uretim_kontrol: SON proses (toplama yok)')