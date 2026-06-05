"""ADIM 3: PLAN-v2 backend'e bitmis_mamul + uretim_asamasi + summary ekle.

KURAL:
- bitmis_mamul = 0 (FINAL_PROSES_MAP bos)
- uretim_asamasi: SIPARIS GENELI Korgun emirler/prosesler (CPS dahil DEGIL)
- darbogaz: min(ATKI, GOVDE, MAMUL) - mevcut hesap (sadece Korgun)
- summary: sade format "0 cikti - Kesim - ATKI'da tikandik"
"""
import io, sys, shutil, time

# ============================================================
# 1) korgun_v2.py - yeni helper fonksiyonlar
# ============================================================
KP = r'C:\cps_dev\modules\hedef\korgun_v2.py'
KMARKER = 'FINAL_PROSES_MAP'

with io.open(KP, 'r', encoding='utf-8') as f:
    ksrc = f.read()

if KMARKER in ksrc:
    print('SKIP-KORGUN: zaten uygulanmis')
else:
    OLD_K = "MOCK_MODE = True\nMOCK_FILE = r'C:\\cps_dev\\mock_korgun_data.json'"

    NEW_K = """MOCK_MODE = True
MOCK_FILE = r'C:\\cps_dev\\mock_korgun_data.json'

# Final proses mapping (bos - simdilik tum bitmis_mamul = 0)
# Ileride: {'MAMUL': 35, 'ATKI': 50, 'GOVDE': 50}
FINAL_PROSES_MAP = {}


def hesapla_bitmis_mamul(mamul_emirler):
    \"\"\"Final proses esigini gecen MAMUL emirlerin toplam yapilan miktari.

    FINAL_PROSES_MAP bos ise her zaman 0 doner.
    \"\"\"
    if 'MAMUL' not in FINAL_PROSES_MAP:
        return 0
    threshold = FINAL_PROSES_MAP['MAMUL']
    toplam = 0
    for e in mamul_emirler or []:
        for p in e.get('prosesler', []) or []:
            try:
                kod = int(p.get('proses_kod', 0))
            except Exception:
                continue
            if kod >= threshold:
                toplam += int(p.get('yapilan', 0) or 0)
    return toplam


def hesapla_uretim_asamasi(tum_emirler):
    \"\"\"Siparis genelinde Korgun emirler/prosesler arasinda EN YUKSEK
    proses kodunun ADI. CPS dahil DEGIL.

    None doner -> uretim henuz baslamamis.
    \"\"\"
    en_yuksek_kod = -1
    en_ileri_adi = None
    for e in tum_emirler or []:
        for p in e.get('prosesler', []) or []:
            try:
                kod = int(p.get('proses_kod', 0))
            except Exception:
                continue
            yp = int(p.get('yapilan', 0) or 0)
            if yp <= 0:
                continue  # Yapilan 0 ise asama sayilmaz
            if kod > en_yuksek_kod:
                en_yuksek_kod = kod
                en_ileri_adi = p.get('proses_adi')
    return en_ileri_adi


def yapilandir_summary(bitmis_mamul, uretim_asamasi, darbogaz_kategori):
    \"\"\"Sade format: '0 cikti - Kesim - ATKI'da tikandik'

    Donen string Turkce, mock veya canli farketmez.
    \"\"\"
    asama = uretim_asamasi if uretim_asamasi else 'henuz baslamadi'
    db = darbogaz_kategori if darbogaz_kategori else '-'
    return str(bitmis_mamul) + ' cikti - ' + str(asama) + ' - ' + str(db) + chr(39) + 'da tikandik'
"""

    if OLD_K not in ksrc:
        print('HATA: korgun_v2.py anchor (MOCK_MODE) bulunamadi')
        sys.exit(1)

    knew = ksrc.replace(OLD_K, NEW_K, 1)

    bak_k = KP + '.bak_pre_summary_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(KP, bak_k)
    print('Yedek korgun: ' + bak_k)

    with io.open(KP, 'w', encoding='utf-8') as f:
        f.write(knew)
    print('OK-KORGUN: helper fonksiyonlar eklendi (' + str(len(knew) - len(ksrc)) + ' byte)')


# ============================================================
# 2) plan_v2.py - response'a yeni alanlar ekle
# ============================================================
PP = r'C:\cps_dev\modules\hedef\plan_v2.py'
PMARKER = 'bitmis_mamul'

with io.open(PP, 'r', encoding='utf-8') as f:
    psrc = f.read()

if PMARKER in psrc:
    print('SKIP-PLAN: zaten uygulanmis')
else:
    # PLAN ana liste - sonuc.append blogunda 'durum_renk' satirinin sonrasina ekle
    OLD_P1 = """        sonuc.append({
            'sip_no': s['sip_no'],
            'musteri': s['musteri'],
            'model_kod': s['model_kod'],
            'model_adi': s.get('model_adi'),
            'hedef': s['hedef'],
            'termin': s['termin'],
            'belge_no': s.get('belge_no'),
            'emir_sayisi': s.get('emir_sayisi', {}),
            'korgun': k,
            'yapilan': d['yapilan'],
            'kalan': d['kalan'],
            'yuzde': d['yuzde'],
            'darbogaz_kategori': d['kategori'],
            'durum_renk': d['renk'],
        })"""

    NEW_P1 = """        # Siparisin tum emirlerini al (asama + bitmis hesabi icin)
        try:
            _detay = _kv2.get_siparis_detay(s['sip_no']) or {}
        except Exception:
            _detay = {}
        _atki_emirler = (_detay.get('atki') or {}).get('emirler', [])
        _govde_emirler = (_detay.get('govde') or {}).get('emirler', [])
        _mamul_emirler = (_detay.get('mamul') or {}).get('emirler', [])
        _tum_emirler = list(_atki_emirler) + list(_govde_emirler) + list(_mamul_emirler)

        _bitmis = _kv2.hesapla_bitmis_mamul(_mamul_emirler)
        _asama = _kv2.hesapla_uretim_asamasi(_tum_emirler)
        _summary = _kv2.yapilandir_summary(_bitmis, _asama, d['kategori'])

        sonuc.append({
            'sip_no': s['sip_no'],
            'musteri': s['musteri'],
            'model_kod': s['model_kod'],
            'model_adi': s.get('model_adi'),
            'hedef': s['hedef'],
            'termin': s['termin'],
            'belge_no': s.get('belge_no'),
            'emir_sayisi': s.get('emir_sayisi', {}),
            'korgun': k,
            'yapilan': d['yapilan'],
            'kalan': d['kalan'],
            'yuzde': d['yuzde'],
            'darbogaz_kategori': d['kategori'],
            'durum_renk': d['renk'],
            'bitmis_mamul': _bitmis,
            'uretim_asamasi': _asama,
            'darbogaz': d['kategori'],
            'summary': _summary,
        })"""

    if OLD_P1 not in psrc:
        print('HATA: plan_v2.py liste anchor bulunamadi')
        sys.exit(1)

    pnew = psrc.replace(OLD_P1, NEW_P1, 1)

    # PLAN detay - return jsonify oncesi yeni alanlar
    OLD_P2 = """    return jsonify({
        'ok': True,
        'sip_no': d['sip_no'],
        'musteri': d.get('musteri'),
        'model_kod': d.get('model_kod'),
        'model_adi': d.get('model_adi'),
        'hedef': d.get('hedef'),
        'termin': d.get('termin'),
        'belge_no': d.get('belge_no'),
        'korgun': {
            'atki': atki_blok,
            'govde': govde_blok,
            'mamul': mamul_blok,
        },
        'cps': cps,
        'darbogaz': darb,
    })"""

    NEW_P2 = """    # bitmis_mamul + uretim_asamasi + summary (Korgun emirler uzerinden)
    _atki_emirler_dt = atki_blok.get('emirler', [])
    _govde_emirler_dt = govde_blok.get('emirler', [])
    _mamul_emirler_dt = mamul_blok.get('emirler', [])
    _tum_emirler_dt = list(_atki_emirler_dt) + list(_govde_emirler_dt) + list(_mamul_emirler_dt)

    _bitmis_dt = _kv2.hesapla_bitmis_mamul(_mamul_emirler_dt)
    _asama_dt = _kv2.hesapla_uretim_asamasi(_tum_emirler_dt)
    _summary_dt = _kv2.yapilandir_summary(_bitmis_dt, _asama_dt, darb.get('kategori'))

    return jsonify({
        'ok': True,
        'sip_no': d['sip_no'],
        'musteri': d.get('musteri'),
        'model_kod': d.get('model_kod'),
        'model_adi': d.get('model_adi'),
        'hedef': d.get('hedef'),
        'termin': d.get('termin'),
        'belge_no': d.get('belge_no'),
        'korgun': {
            'atki': atki_blok,
            'govde': govde_blok,
            'mamul': mamul_blok,
        },
        'cps': cps,
        'darbogaz': darb,
        'bitmis_mamul': _bitmis_dt,
        'uretim_asamasi': _asama_dt,
        'summary': _summary_dt,
    })"""

    if OLD_P2 not in pnew:
        print('HATA: plan_v2.py detay anchor bulunamadi')
        sys.exit(1)

    pnew2 = pnew.replace(OLD_P2, NEW_P2, 1)

    bak_p = PP + '.bak_pre_summary_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(PP, bak_p)
    print('Yedek plan: ' + bak_p)

    with io.open(PP, 'w', encoding='utf-8') as f:
        f.write(pnew2)
    print('OK-PLAN: response zenginlestirildi (' + str(len(pnew2) - len(psrc)) + ' byte)')

print()
print('TAMAM: ADIM 3 uygulandi')
print('Sunucuyu restart et, sonra test:')
print('  http://localhost:5057/hedef/v2/plan')
print('  http://localhost:5057/hedef/v2/plan-detay/33638')