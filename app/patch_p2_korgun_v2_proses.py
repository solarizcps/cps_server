"""PATCH 2/4: korgun_v2.py - proses_tablosu + kategori_durum + ozet hesaplari.

KURAL:
- Sadece var olan Korgun prosesleri tabloda gosterilir
- Kesim hazirlik, uretim sayilmaz
- yapilan_darbogaz=0 ise uretim_durumu='Baslamadi'
- ATKI/GOVDE/MAMUL kategorisi icin ayri durum
- Renk: yesil=biten, sari=devam, kirmizi=kalan, gri=baslamadi
"""
import io, sys, shutil, time

KP = r'C:\cps_dev\modules\hedef\korgun_v2.py'
MARKER = 'def proses_tablosu_uret'

with io.open(KP, 'r', encoding='utf-8') as f:
    ksrc = f.read()

if MARKER in ksrc:
    print('SKIP: PATCH 2 zaten uygulanmis')
    sys.exit(0)

NEW_FUNCS = '''


# === PATCH 2/4: proses_tablosu + kategori_durum + ozet ===

# Kesim proses kodu (uretim sayilmaz, sadece hazirlik)
KESIM_PROSES_KODU = '02'


def _proses_renk(biten, kalan, devam, hedef):
    """Bir proses satiri icin renk."""
    if biten >= hedef and hedef > 0:
        return 'yesil'
    if devam > 0:
        return 'sari'
    if biten == 0 and devam == 0:
        return 'gri'
    return 'kirmizi'  # kalan > 0


def proses_tablosu_uret(emirler, hedef):
    """Bir emir listesi icin proses bazli tabloyu uretir.

    Donus: list of {proses_adi, proses_kod, kategori, baslayacak, devam, biten, kalan, hedef, renk}
    Sadece var olan prosesler doner. Korgun'da yoksa satir koymaz.

    G2 (mock): baslayacak=0, devam=0, biten=yapilan, kalan=hedef-biten
    """
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
            bucket[anahtar]['biten'] += yp

    # Liste yap, kod numerik artan sirala
    liste = list(bucket.values())

    def _sira_key(item):
        try:
            return int(item['proses_kod'])
        except Exception:
            return 999

    liste.sort(key=_sira_key)

    # Her satir icin tablo alanlari
    sonuc = []
    for satir in liste:
        biten = satir['biten']
        kalan = max(0, hedef - biten)
        devam = 0  # G2: bilinmiyor, 0
        baslayacak = 0  # G2: bilinmiyor, 0
        renk = _proses_renk(biten, kalan, devam, hedef)
        sonuc.append({
            'proses_adi': satir['proses_adi'],
            'proses_kod': satir['proses_kod'],
            'kategori': satir['kategori'],
            'baslayacak': baslayacak,
            'devam': devam,
            'biten': biten,
            'kalan': kalan,
            'hedef': hedef,
            'renk': renk,
        })
    return sonuc


def hesapla_kategori_durum(atki_emirler, govde_emirler, mamul_emirler, hedef):
    """ATKI/GOVDE/MAMUL kategori durumu.

    KURAL:
    - MAMUL: sadece Kesim varsa "Sadece kesim/hazirlik tamam" - baslamadi
    - MAMUL: Kesim disinda proses varsa baslamis
    - ATKI/GOVDE: hic yapilan yoksa baslamadi, varsa devam ediyor
    """
    def _kategori_uretim_kontrol(emirler, kategori):
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
                    kesim_disi_var = True

        if biten_toplam == 0:
            return {
                'baslamis': False,
                'biten': 0,
                'hedef': hedef,
                'renk': 'gri',
                'mesaj': 'Baslamadi',
            }

        # MAMUL ozel kural: sadece Kesim varsa "hazirlik tamam"
        if kategori == 'MAMUL' and not kesim_disi_var:
            return {
                'baslamis': False,
                'biten': biten_toplam,
                'hedef': hedef,
                'renk': 'gri',
                'mesaj': 'Sadece kesim/hazirlik tamam',
            }

        # Devam veya tamamlandi
        if biten_toplam >= hedef:
            return {
                'baslamis': True,
                'biten': biten_toplam,
                'hedef': hedef,
                'renk': 'yesil',
                'mesaj': 'Tamamlandi',
            }
        return {
            'baslamis': True,
            'biten': biten_toplam,
            'hedef': hedef,
            'renk': 'kirmizi' if biten_toplam == 0 else 'sari',
            'mesaj': 'Devam ediyor',
        }

    return {
        'ATKI': _kategori_uretim_kontrol(atki_emirler, 'ATKI'),
        'GOVDE': _kategori_uretim_kontrol(govde_emirler, 'GOVDE'),
        'MAMUL': _kategori_uretim_kontrol(mamul_emirler, 'MAMUL'),
    }


def hesapla_kesim_toplam(mamul_emirler):
    """Kesim (kod=02) toplam yapilan miktari."""
    toplam = 0
    for e in mamul_emirler or []:
        for p in e.get('prosesler', []) or []:
            if str(p.get('proses_kod', '')).strip() == KESIM_PROSES_KODU:
                toplam += int(p.get('yapilan', 0) or 0)
    return toplam


def hesapla_uretim_durumu_v2(yapilan_darbogaz):
    """yapilan_darbogaz=0 ise 'Baslamadi', degilse 'Devam ediyor'."""
    yp = int(yapilan_darbogaz or 0)
    if yp == 0:
        return 'Baslamadi'
    return 'Devam ediyor'


def hesapla_summary_v2(cikti, hazirlik, uretim_durumu, darbogaz_kategori, darbogaz_durum):
    """Sade dil:
    - Baslamadi + hazirlik var: "X kesim hazir - uretim baslamadi - Y bekleniyor"
    - Devam: "X cikti - Y asamasinda - Z'da devam ediyor" (devam edende kirmizi degil)
    - Tamam: "X cikti - tamamlandi"
    """
    db = darbogaz_kategori or '-'
    if uretim_durumu == 'Baslamadi':
        if hazirlik > 0:
            return str(hazirlik) + ' kesim hazir - uretim baslamadi - ' + db + ' bekleniyor'
        return 'Henuz hazirlik yok - ' + db + ' bekleniyor'
    if uretim_durumu == 'Tamamlandi':
        return str(cikti) + ' cikti - tamamlandi'
    return str(cikti) + ' cikti - ' + uretim_durumu + ' - ' + db + ' bekleniyor'


def hesapla_ozet(modeller, darbogaz_kategori, hedef):
    """Siparis ozet: cikti, hazirlik, uretim_durumu, darbogaz, summary.

    cikti = bitmis_mamul (FINAL_PROSES_MAP bos -> 0)
    hazirlik = tum mamul emirlerin Kesim toplami
    uretim_durumu = 'Baslamadi' / 'Devam ediyor' / 'Tamamlandi'
    """
    # Tum emirleri kategoriye ayir
    tum_atki = []
    tum_govde = []
    tum_mamul = []
    for m in modeller or []:
        for me in m.get('mamul_emirler', []) or []:
            korgun = me.get('korgun') or {}
            mamul = korgun.get('mamul') or {}
            tum_mamul.append({
                'emir_no': mamul.get('emir_no'),
                'prosesler': mamul.get('prosesler', []),
                'kategori': 'MAMUL',
            })
            for ae in (korgun.get('atki') or {}).get('emirler', []):
                tum_atki.append({
                    'emir_no': ae.get('emir_no'),
                    'prosesler': ae.get('prosesler', []),
                    'kategori': 'ATKI',
                })
            for ge in (korgun.get('govde') or {}).get('emirler', []):
                tum_govde.append({
                    'emir_no': ge.get('emir_no'),
                    'prosesler': ge.get('prosesler', []),
                    'kategori': 'GOVDE',
                })

    cikti = hesapla_bitmis_mamul(tum_mamul)
    hazirlik = hesapla_kesim_toplam(tum_mamul)

    # Darbogaz yapilan = min(ATKI, GOVDE, MAMUL ilerleme - kesim disi)
    # Ama hesabi caller (plan_v2) yapacak, biz simdilik ozet alanini kuruyoruz
    return {
        'cikti': cikti,
        'hazirlik': hazirlik,
        'tum_atki': tum_atki,
        'tum_govde': tum_govde,
        'tum_mamul': tum_mamul,
    }
'''

bak = KP + '.bak_pre_p2_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(KP, bak)
print('Yedek: ' + bak)

with io.open(KP, 'w', encoding='utf-8') as f:
    f.write(ksrc.rstrip() + NEW_FUNCS + '\n')

artis = len(NEW_FUNCS) + 1
print('OK: PATCH 2 fonksiyonlari eklendi (' + str(artis) + ' byte)')
print('Eklenen fonksiyonlar:')
print('  - proses_tablosu_uret(emirler, hedef)')
print('  - hesapla_kategori_durum(atki, govde, mamul, hedef)')
print('  - hesapla_kesim_toplam(mamul_emirler)')
print('  - hesapla_uretim_durumu_v2(yapilan_darbogaz)')
print('  - hesapla_summary_v2(...)')
print('  - hesapla_ozet(modeller, darbogaz_kategori, hedef)')