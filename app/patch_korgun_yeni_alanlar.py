"""PATCH: korgun_v2.py - mock'taki biten/baslayacak/devam alanlarini oku.

Mantik:
- proses.get('biten') varsa -> kullan (yeni format)
- yoksa proses.get('yapilan') -> biten kabul et (eski format)
- baslayacak ve devam alanlari yoksa 0
"""
import io, sys, shutil, time

KP = r'C:\cps_dev\modules\hedef\korgun_v2.py'
MARKER = '/* YENI ALANLAR: biten/baslayacak/devam */'

with io.open(KP, 'r', encoding='utf-8') as f:
    ksrc = f.read()

if MARKER in ksrc:
    print('SKIP: yeni alanlar zaten okuyor')
    sys.exit(0)

# proses_tablosu_uret fonksiyonunu guncelle - biten/baslayacak/devam okusun
OLD = """def proses_tablosu_uret(emirler, hedef):
    \"\"\"Bir emir listesi icin proses bazli tabloyu uretir.

    Donus: list of {proses_adi, proses_kod, kategori, baslayacak, devam, biten, kalan, hedef, renk}
    Sadece var olan prosesler doner. Korgun'da yoksa satir koymaz.

    G2 (mock): baslayacak=0, devam=0, biten=yapilan, kalan=hedef-biten
    \"\"\"
    # proses_kod bazinda topla, ayni proses_kod -> ayni satir
    bucket = {}  # (proses_kod, kategori) -> {biten, proses_adi}
    for e in emirler or []:
        kategori = e.get('kategori', 'MAMUL')
        for p in e.get('prosesler', []) or []:
            kod = str(p.get('proses_kod', '')).strip()
            if not kod:
                continue
            adi = p.get('proses_adi') or kod
            yp = int(p.get('yapilan', 0) or 0)
            anahtar = (kod, kategori)
            if anahtar not in bucket:
                bucket[anahtar] = {
                    'proses_kod': kod,
                    'proses_adi': adi,
                    'kategori': kategori,
                    'biten': 0,
                }
            bucket[anahtar]['biten'] += yp"""

NEW = """def proses_tablosu_uret(emirler, hedef):
    \"\"\"Bir emir listesi icin proses bazli tabloyu uretir.

    YENI ALANLAR: biten/baslayacak/devam (mock'tan veya yapilan'dan)
    \"\"\"
    # /* YENI ALANLAR: biten/baslayacak/devam */
    bucket = {}
    for e in emirler or []:
        kategori = e.get('kategori', 'MAMUL')
        for p in e.get('prosesler', []) or []:
            kod = str(p.get('proses_kod', '')).strip()
            if not kod:
                continue
            adi = p.get('proses_adi') or kod
            # Yeni format: biten/baslayacak/devam ayri alanlar
            # Eski format: sadece yapilan -> biten kabul et
            biten = p.get('biten')
            if biten is None:
                biten = p.get('yapilan', 0)
            biten = int(biten or 0)
            baslayacak = int(p.get('baslayacak', 0) or 0)
            devam = int(p.get('devam', 0) or 0)
            anahtar = (kod, kategori)
            if anahtar not in bucket:
                bucket[anahtar] = {
                    'proses_kod': kod,
                    'proses_adi': adi,
                    'kategori': kategori,
                    'biten': 0,
                    'baslayacak': 0,
                    'devam': 0,
                }
            bucket[anahtar]['biten'] += biten
            bucket[anahtar]['baslayacak'] += baslayacak
            bucket[anahtar]['devam'] += devam"""

if OLD not in ksrc:
    print('HATA: proses_tablosu_uret anchor bulunamadi')
    sys.exit(1)

new_src = ksrc.replace(OLD, NEW, 1)

# Sonra "for satir in liste" donguyu da guncelle - artik baslayacak/devam bucket'ten gelir
OLD2 = """    # Her satir icin tablo alanlari
    sonuc = []
    for satir in liste:
        biten = satir['biten']
        kalan = max(0, hedef - biten)
        devam = 0  # G2: bilinmiyor, 0
        baslayacak = 0  # G2: bilinmiyor, 0
        renk = _proses_renk(biten, kalan, devam, hedef)"""

NEW2 = """    # Her satir icin tablo alanlari
    sonuc = []
    for satir in liste:
        biten = satir['biten']
        baslayacak = satir.get('baslayacak', 0)
        devam = satir.get('devam', 0)
        kalan = max(0, hedef - biten)
        renk = _proses_renk(biten, kalan, devam, hedef)"""

if OLD2 not in new_src:
    print('UYARI: dongu anchor bulunamadi (devam)')
else:
    new_src = new_src.replace(OLD2, NEW2, 1)

# son olarak yapilan'i biten ile degistir (helper fonksiyonlarda)
# hesapla_kesim_toplam ve hesapla_kategori_durum
OLD3 = """def hesapla_kesim_toplam(mamul_emirler):
    \"\"\"Kesim (kod=02) toplam yapilan miktari.\"\"\"
    toplam = 0
    for e in mamul_emirler or []:
        for p in e.get('prosesler', []) or []:
            if str(p.get('proses_kod', '')).strip() == KESIM_PROSES_KODU:
                toplam += int(p.get('yapilan', 0) or 0)
    return toplam"""

NEW3 = """def hesapla_kesim_toplam(mamul_emirler):
    \"\"\"Kesim (kod=02) toplam biten miktari (eski: yapilan).\"\"\"
    toplam = 0
    for e in mamul_emirler or []:
        for p in e.get('prosesler', []) or []:
            if str(p.get('proses_kod', '')).strip() == KESIM_PROSES_KODU:
                bt = p.get('biten')
                if bt is None:
                    bt = p.get('yapilan', 0)
                toplam += int(bt or 0)
    return toplam"""

if OLD3 in new_src:
    new_src = new_src.replace(OLD3, NEW3, 1)

# hesapla_kategori_durum icindeki yapilan -> biten
OLD4 = """    def _kategori_uretim_kontrol(emirler, kategori):
        biten_toplam = 0
        kesim_disi_var = False
        for e in emirler or []:
            for p in e.get('prosesler', []) or []:
                kod = str(p.get('proses_kod', '')).strip()
                yp = int(p.get('yapilan', 0) or 0)
                if yp <= 0:
                    continue
                biten_toplam += yp
                if kod != KESIM_PROSES_KODU:
                    kesim_disi_var = True"""

NEW4 = """    def _kategori_uretim_kontrol(emirler, kategori):
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

if OLD4 in new_src:
    new_src = new_src.replace(OLD4, NEW4, 1)

bak = KP + '.bak_pre_yenialan_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(KP, bak)
print('Yedek: ' + bak)

with io.open(KP, 'w', encoding='utf-8') as f:
    f.write(new_src)

artis = len(new_src) - len(ksrc)
print('OK: yeni alanlar okuyor (' + str(artis) + ' byte)')
print('  - proses_tablosu_uret: biten/baslayacak/devam')
print('  - hesapla_kesim_toplam: biten')
print('  - hesapla_kategori_durum: biten')