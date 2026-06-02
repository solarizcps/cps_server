"""CPS PLAN v2 - Korgun veri katmani.

Yarin: MOCK_MODE = False yapilinca gercek Korgun SQL'e geciyor.
Bugun: Mock JSON'dan okuyor.

KURAL: Korgun ve CPS birlestirilmez. Bu modul SADECE Korgun verisini saglar.
"""
import json
import os
from datetime import datetime

MOCK_MODE = False  # /* CANLI SQL */
MOCK_FILE = r'C:\cps_dev\mock_korgun_data.json'

# Final proses mapping (bos - simdilik tum bitmis_mamul = 0)
# Ileride: {'MAMUL': 35, 'ATKI': 50, 'GOVDE': 50}
FINAL_PROSES_MAP = {}


def hesapla_bitmis_mamul(mamul_emirler):
    """Final proses esigini gecen MAMUL emirlerin toplam yapilan miktari.

    FINAL_PROSES_MAP bos ise her zaman 0 doner.
    """
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
    """Siparis genelinde Korgun emirler/prosesler arasinda EN YUKSEK
    proses kodunun ADI. CPS dahil DEGIL.

    None doner -> uretim henuz baslamamis.
    """
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
    """Sade format: '0 cikti - Kesim - ATKI'da tikandik'

    Donen string Turkce, mock veya canli farketmez.
    """
    asama = uretim_asamasi if uretim_asamasi else 'henuz baslamadi'
    db = darbogaz_kategori if darbogaz_kategori else '-'
    return str(bitmis_mamul) + ' cikti - ' + str(asama) + ' - ' + str(db) + chr(39) + 'da tikandik'



def _read_mock():
    if not os.path.exists(MOCK_FILE):
        return {'siparisler': []}
    try:
        with open(MOCK_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'siparisler': []}


def _kategori_belirle(model_kod, model_adi):
    mk = (model_kod or '').upper()
    ma = (model_adi or '').upper().replace('Ğ', 'G').replace('Ö', 'O').replace('İ', 'I')
    if 'ATKI' in mk or 'ATKI' in ma:
        return 'ATKI'
    if 'GOVDE' in mk or 'GOVDE' in ma or 'EVA CRX-001' in mk:
        return 'GOVDE'
    if 'TABAN' in mk or 'TABAN' in ma:
        return 'TABAN'
    return 'MAMUL'


def _son_proses_yapilan(prosesler):
    """En yuksek proses_kod'lu prosesin BITEN miktari.
    /* SON PROSES BIT EN FIX */
    Yeni format: 'biten' okur. Eski format: 'yapilan' fallback.
    """
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
    return son_yp, son_adi


def get_siparis_listesi():
    if MOCK_MODE:
        data = _read_mock()
    else:
        return []

    sonuc = []
    for sip in data.get('siparisler', []):
        emirler = sip.get('emirler', [])

        atki_emirler = [e for e in emirler if e.get('kategori') == 'ATKI']
        govde_emirler = [e for e in emirler if e.get('kategori') == 'GOVDE']
        mamul_emirler = [e for e in emirler if e.get('kategori') == 'MAMUL']

        atki_t = sum(_son_proses_yapilan(e.get('prosesler', []))[0] for e in atki_emirler)
        govde_t = sum(_son_proses_yapilan(e.get('prosesler', []))[0] for e in govde_emirler)
        mamul_t = sum(_son_proses_yapilan(e.get('prosesler', []))[0] for e in mamul_emirler)

        sonuc.append({
            'sip_no': sip['sip_no'],
            'musteri': sip.get('musteri'),
            'model_kod': sip.get('model_kod'),
            'model_adi': sip.get('model_adi'),
            'hedef': int(sip.get('hedef', 0) or 0),
            'termin': sip.get('termin'),
            'belge_no': sip.get('belge_no'),
            'emir_sayisi': {
                'mamul': len(mamul_emirler),
                'atki': len(atki_emirler),
                'govde': len(govde_emirler),
            },
            'korgun': {
                'atki_tamamlanan': atki_t,
                'govde_tamamlanan': govde_t,
                'mamul_tamamlanan': mamul_t,
            },
        })
    return sonuc


def get_siparis_detay(sip_no):
    if MOCK_MODE:
        data = _read_mock()
    else:
        return None

    sip = None
    for s in data.get('siparisler', []):
        if str(s.get('sip_no')) == str(sip_no):
            sip = s
            break

    if not sip:
        return None

    hedef = int(sip.get('hedef', 0) or 0)
    emirler = sip.get('emirler', [])

    def _kategori_blok(kategori_emirler):
        tamamlanan = 0
        emir_listesi = []
        for e in kategori_emirler:
            son_yp, son_adi = _son_proses_yapilan(e.get('prosesler', []))
            tamamlanan += son_yp
            emir_listesi.append({
                'emir_no': e['emir_no'],
                'yaz_say': int(e.get('yaz_say', 0) or 0),
                'son_proses': son_adi,
                'son_yapilan': son_yp,
                'prosesler': e.get('prosesler', []),
                'parent_emir': e.get('parent_emir'),
            })
        yuzde = round((tamamlanan / hedef * 100), 1) if hedef > 0 else 0.0
        return {
            'tamamlanan': tamamlanan,
            'hedef': hedef,
            'yuzde': yuzde,
            'emir_sayisi': len(kategori_emirler),
            'emirler': emir_listesi,
        }

    atki_emirler = [e for e in emirler if e.get('kategori') == 'ATKI']
    govde_emirler = [e for e in emirler if e.get('kategori') == 'GOVDE']
    mamul_emirler = [e for e in emirler if e.get('kategori') == 'MAMUL']

    return {
        'sip_no': sip['sip_no'],
        'musteri': sip.get('musteri'),
        'model_kod': sip.get('model_kod'),
        'model_adi': sip.get('model_adi'),
        'hedef': hedef,
        'termin': sip.get('termin'),
        'belge_no': sip.get('belge_no'),
        'atki': _kategori_blok(atki_emirler),
        'govde': _kategori_blok(govde_emirler),
        'mamul': _kategori_blok(mamul_emirler),
    }


# === ADIM U1: Hiyerarsik detay (Siparis -> Model -> Mamul Emir -> Korgun) ===
def _kategori_ayir_emirler(emirler):
    """Bir model icindeki emirleri kategoriye gore ayir."""
    atki = [e for e in emirler if e.get('kategori') == 'ATKI']
    govde = [e for e in emirler if e.get('kategori') == 'GOVDE']
    mamul = [e for e in emirler if e.get('kategori') == 'MAMUL']
    return atki, govde, mamul


def _emir_korgun_blok(mamul_emir, atki_emirler_iliskili, govde_emirler_iliskili):
    """Bir mamul emir icin Korgun real blok.
    parent_emir uzerinden iliski kurar.

    mamul_emir: {emir_no, yaz_say, prosesler}
    atki_emirler_iliskili: parent_emir = bu mamul_emir.emir_no olan ATKI emirler
    govde_emirler_iliskili: ayni - GOVDE
    """
    mamul_son_yp, mamul_son_adi = _son_proses_yapilan(mamul_emir.get('prosesler', []))

    # ATKI iliskili
    atki_blok = {'tamamlanan': 0, 'son_proses': None, 'emirler': []}
    for ae in atki_emirler_iliskili:
        son_yp, son_adi = _son_proses_yapilan(ae.get('prosesler', []))
        atki_blok['emirler'].append({
            'emir_no': ae['emir_no'],
            'yaz_say': int(ae.get('yaz_say', 0) or 0),
            'son_proses': son_adi,
            'son_yapilan': son_yp,
            'prosesler': ae.get('prosesler', []),
        })
        atki_blok['tamamlanan'] += son_yp
        if son_yp > 0 and not atki_blok['son_proses']:
            atki_blok['son_proses'] = son_adi

    # GOVDE iliskili
    govde_blok = {'tamamlanan': 0, 'son_proses': None, 'emirler': []}
    for ge in govde_emirler_iliskili:
        son_yp, son_adi = _son_proses_yapilan(ge.get('prosesler', []))
        govde_blok['emirler'].append({
            'emir_no': ge['emir_no'],
            'yaz_say': int(ge.get('yaz_say', 0) or 0),
            'son_proses': son_adi,
            'son_yapilan': son_yp,
            'prosesler': ge.get('prosesler', []),
        })
        govde_blok['tamamlanan'] += son_yp
        if son_yp > 0 and not govde_blok['son_proses']:
            govde_blok['son_proses'] = son_adi

    # MAMUL kendisi
    mamul_blok = {
        'emir_no': mamul_emir['emir_no'],
        'yaz_say': int(mamul_emir.get('yaz_say', 0) or 0),
        'son_proses': mamul_son_adi,
        'son_yapilan': mamul_son_yp,
        'prosesler': mamul_emir.get('prosesler', []),
    }

    return {
        'atki': atki_blok,
        'govde': govde_blok,
        'mamul': mamul_blok,
    }


def get_siparis_detay_v2(sip_no):
    """Hiyerarsik detay: Siparis -> Model -> Mamul Emir -> Korgun.

    Donus:
    {
        'sip_no', 'musteri', 'hedef', 'termin', 'belge_no',
        'model_sayisi': int,
        'modeller': [
            {
                'model_kod', 'model_adi', 'hedef_pay': int,
                'mamul_emirler': [
                    {
                        'emir_no', 'yaz_say',
                        'korgun': {
                            'atki': {tamamlanan, son_proses, emirler[]},
                            'govde': {...},
                            'mamul': {emir_no, prosesler, son_proses, son_yapilan},
                        }
                    },
                    ...
                ],
                'kategori_ozet': {atki_t, govde_t, mamul_t}
            },
            ...
        ]
    }
    """
    if MOCK_MODE:
        data = _read_mock()
    else:
        return None

    sip = None
    for s in data.get('siparisler', []):
        if str(s.get('sip_no')) == str(sip_no):
            sip = s
            break

    if not sip:
        return None

    hedef = int(sip.get('hedef', 0) or 0)
    emirler = sip.get('emirler', [])

    # Modele gore grupla (mamul emirin ModelKod'una gore)
    # Tek modelliyse 1 grup, coklu modelliyse N grup
    model_gruplari = {}  # model_kod -> {model_adi, mamul_emirler[]}

    atki_emirler, govde_emirler, mamul_emirler = _kategori_ayir_emirler(emirler)

    # Mamul emirleri model bazinda grupla
    for me in mamul_emirler:
        mk = me.get('model_kod', '?')
        ma = sip.get('model_adi') if mk == sip.get('model_kod') else mk
        if mk not in model_gruplari:
            model_gruplari[mk] = {
                'model_kod': mk,
                'model_adi': ma,
                'mamul_emirler': [],
            }
        model_gruplari[mk]['mamul_emirler'].append(me)

    # Eger hic mamul emir yoksa ama model_kod varsa, bos grup ekle
    if not model_gruplari and sip.get('model_kod'):
        model_gruplari[sip['model_kod']] = {
            'model_kod': sip['model_kod'],
            'model_adi': sip.get('model_adi', sip['model_kod']),
            'mamul_emirler': [],
        }

    # Her grupta mamul emirler icin Korgun blok hesapla
    modeller_listesi = []
    for mk, grup in model_gruplari.items():
        mamul_emir_detaylari = []
        kat_atki_t = 0
        kat_govde_t = 0
        kat_mamul_t = 0

        for me in grup['mamul_emirler']:
            # Bu mamul emire iliskili ATKI/GOVDE emirler (parent_emir)
            atki_iliskili = [a for a in atki_emirler if a.get('parent_emir') == me['emir_no']]
            govde_iliskili = [g for g in govde_emirler if g.get('parent_emir') == me['emir_no']]

            korgun = _emir_korgun_blok(me, atki_iliskili, govde_iliskili)
            mamul_emir_detaylari.append({
                'emir_no': me['emir_no'],
                'yaz_say': int(me.get('yaz_say', 0) or 0),
                'korgun': korgun,
            })

            kat_atki_t += korgun['atki']['tamamlanan']
            kat_govde_t += korgun['govde']['tamamlanan']
            kat_mamul_t += korgun['mamul']['son_yapilan']

        modeller_listesi.append({
            'model_kod': grup['model_kod'],
            'model_adi': grup['model_adi'],
            'hedef_pay': hedef,  # mock'ta tek model, hedef tum siparise ait
            'mamul_emirler': mamul_emir_detaylari,
            'kategori_ozet': {
                'atki_tamamlanan': kat_atki_t,
                'govde_tamamlanan': kat_govde_t,
                'mamul_tamamlanan': kat_mamul_t,
            },
        })

    # Toplam kategori ozeti (tum modeller arasi)
    toplam_atki = sum(m['kategori_ozet']['atki_tamamlanan'] for m in modeller_listesi)
    toplam_govde = sum(m['kategori_ozet']['govde_tamamlanan'] for m in modeller_listesi)
    toplam_mamul = sum(m['kategori_ozet']['mamul_tamamlanan'] for m in modeller_listesi)

    return {
        'sip_no': sip['sip_no'],
        'musteri': sip.get('musteri'),
        'cari_kod': sip.get('cari_kod'),
        'hedef': hedef,
        'termin': sip.get('termin'),
        'belge_no': sip.get('belge_no'),
        'model_sayisi': len(modeller_listesi),
        'modeller': modeller_listesi,
        'toplam_korgun': {
            'atki_tamamlanan': toplam_atki,
            'govde_tamamlanan': toplam_govde,
            'mamul_tamamlanan': toplam_mamul,
        },
    }


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

    YENI ALANLAR: biten/baslayacak/devam (mock'tan veya yapilan'dan)
    """
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
            bucket[anahtar]['devam'] += devam

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
        baslayacak = satir.get('baslayacak', 0)
        devam = satir.get('devam', 0)
        kalan = max(0, hedef - biten)
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
        """Bu kategoride: SON proses miktari (toplama DEGIL).
        Her emir kendi son prosesinin biten miktarini katkilar.
        """
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
    """Kesim (kod=02) toplam biten miktari (eski: yapilan)."""
    toplam = 0
    for e in mamul_emirler or []:
        for p in e.get('prosesler', []) or []:
            if str(p.get('proses_kod', '')).strip() == KESIM_PROSES_KODU:
                bt = p.get('biten')
                if bt is None:
                    bt = p.get('yapilan', 0)
                toplam += int(bt or 0)
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


# === CANLI SQL FONKSIYONLARI === /* CANLI SQL */
def _korgun_baglan():
    """Korgun MSSQL baglantisi."""
    import pytds
    from config import Config
    return pytds.connect(
        server=getattr(Config, 'KORGUN_HOST', '25.7.184.221'),
        database=getattr(Config, 'KORGUN_DB', 'Solariz22'),
        user=getattr(Config, 'KORGUN_USER', 'claude'),
        password=getattr(Config, 'KORGUN_PASS', '104099'),
        port=int(getattr(Config, 'KORGUN_PORT', 1433)),
        timeout=30, login_timeout=10,
    )


def _sql_get_siparis_listesi():
    """Aktif siparisler + emir/proses ozeti."""
    con = _korgun_baglan()
    try:
        cur = con.cursor()

        # 1) Aktif siparisler /* CHUNK 2100 FIX */ DISTINCT eklendi
        cur.execute("""
            SELECT DISTINCT
                sk.SipNo,
                ISNULL(ck.CName, '-') AS CariAdi,
                sh.SKOD AS ModelKod,
                ISNULL(sm.Tanim, sh.SKOD) AS ModelAdi,
                sh.Miktar AS Hedef,
                CONVERT(VARCHAR(10), sh.TerminTarihi, 120) AS Termin,
                sk.BelgeNo,
                sk.CariKod
            FROM Siparis_Kay sk WITH (NOLOCK)
            INNER JOIN Siparis_Har sh WITH (NOLOCK) ON sh.SipNo = sk.SipNo
            LEFT JOIN Cari_Kart ck WITH (NOLOCK) ON ck.CKod = sk.CariKod
            LEFT JOIN StokKart sm WITH (NOLOCK) ON sm.SKod = sh.SKOD
            WHERE LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
              AND EXISTS (
                  SELECT 1 FROM Urt_Em_gch g WITH (NOLOCK)
                  WHERE g.FisNo = sk.SipNo
              )
            ORDER BY sk.SipNo DESC
        """)

        siparisler = []
        for r in cur.fetchall():
            siparisler.append({
                'sip_no': int(r[0]),
                'musteri': r[1],
                'model_kod': r[2],
                'model_adi': r[3],
                'hedef': int(float(r[4] or 0)),
                'termin': r[5],
                'belge_no': r[6],
                'cari_kod': r[7],
            })

        cur.close()
        return siparisler
    finally:
        con.close()


def _sql_get_siparis_emirler(sip_no):
    """Bir siparisin tum emirleri (ana + alt) + her emir icin prosesler.

    Donus: list of {emir_no, kategori (MAMUL/GOVDE/ATKI), tip, yaz_say,
                    parent_emir, model_kod, prosesler[]}

    prosesler[]: {proses_kod, proses_adi, biten, baslayacak, devam}
    """
    con = _korgun_baglan()
    try:
        cur = con.cursor()

        # 1) Bu siparisin ana emirleri (Tip='M')
        # Once Urt_Em_gch'den FisNo=sip_no olan emir listesi
        cur.execute("""
            SELECT DISTINCT g.EmirNo
            FROM Urt_Em_gch g WITH (NOLOCK)
            WHERE g.FisNo = %s

            UNION

            SELECT DISTINCT g2.EmirNo
            FROM Urt_Em_gch g2 WITH (NOLOCK)
            WHERE g2.FisNo = %s
        """, (sip_no, sip_no))
        gch_emirler = [int(r[0]) for r in cur.fetchall()]

        if not gch_emirler:
            return []

        # 2) Her emirin Urt_Emir veya Urtx_Emir bilgisi
        ph = ','.join(['%s'] * len(gch_emirler))
        cur.execute(f"""
            SELECT e.EmirNo, e.ModelKod, UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) AS Tip,
                   ISNULL(e.YazSay, 0) AS YazSay,
                   ISNULL(sk.Tanim, e.ModelKod) AS ModelAdi
            FROM Urt_Emir e WITH (NOLOCK)
            LEFT JOIN StokKart sk WITH (NOLOCK) ON sk.SKod = e.ModelKod
            WHERE e.EmirNo IN ({ph})

            UNION ALL

            SELECT e.EmirNo, e.ModelKod, UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) AS Tip,
                   ISNULL(e.YazSay, 0) AS YazSay,
                   ISNULL(sk.Tanim, e.ModelKod) AS ModelAdi
            FROM Urtx_Emir e WITH (NOLOCK)
            LEFT JOIN StokKart sk WITH (NOLOCK) ON sk.SKod = e.ModelKod
            WHERE e.EmirNo IN ({ph})
        """, tuple(gch_emirler) + tuple(gch_emirler))

        emir_meta = {}
        for r in cur.fetchall():
            en = int(r[0])
            if en in emir_meta:
                continue
            mk = r[1] or ''
            tip = r[2] or 'M'
            yaz = int(float(r[3] or 0))  # YAZSAY_FIX_GIREN: lot sayisi, gercek cift asagidaki sorgudan
            ma = r[4] or mk
            kat = _kategori_belirle(mk, ma)
            emir_meta[en] = {
                'emir_no': en,
                'model_kod': mk,
                'model_adi': ma,
                'tip': tip,
                'kategori': kat,
                'yaz_say': yaz,
                'parent_emir': None,
                'prosesler': [],
            }

        # 3) Em2Em ile parent baglanti
        cur.execute(f"""
            SELECT em.EmirNo AS Parent, em.EmirNo_YM AS Alt
            FROM Urt_Em2Em em WITH (NOLOCK)
            WHERE em.EmirNo IN ({ph}) OR em.EmirNo_YM IN ({ph})
        """, tuple(gch_emirler) + tuple(gch_emirler))
        for r in cur.fetchall():
            parent = int(r[0])
            alt = int(r[1])
            if alt in emir_meta:
                emir_meta[alt]['parent_emir'] = parent

        # YAZSAY_FIX_GIREN - gercek cift hedef (Urt_Em_gch SUM Giren)
        cur.execute(f"""
            SELECT EmirNo, SUM(ISNULL(Giren, 0)) AS Hedef
            FROM Urt_Em_gch WITH (NOLOCK)
            WHERE EmirNo IN ({ph})
            GROUP BY EmirNo
        """, tuple(gch_emirler))
        for r in cur.fetchall():
            en = int(r[0])
            if en in emir_meta:
                gercek = int(float(r[1] or 0))
                if gercek > 0:
                    emir_meta[en]['yaz_say'] = gercek

        # 4) BITEN: Urt_con_gch + Urtx_con_gch UNION
        cur.execute(f"""
            SELECT g.EmirNo, g.Proses, SUM(g.Cikan) AS Biten
            FROM Urt_con_gch g WITH (NOLOCK)
            WHERE g.EmirNo IN ({ph})
              AND g.Cikan > 0
            GROUP BY g.EmirNo, g.Proses

            UNION ALL

            SELECT g.EmirNo, g.Proses, SUM(g.Cikan) AS Biten
            FROM Urtx_con_gch g WITH (NOLOCK)
            WHERE g.EmirNo IN ({ph})
              AND g.Cikan > 0
            GROUP BY g.EmirNo, g.Proses
        """, tuple(gch_emirler) + tuple(gch_emirler))

        # Aynı emir+proses iki tabloda varsa topla
        biten_map = {}  # (emir, proses) -> biten
        for r in cur.fetchall():
            en = int(r[0])
            pr = str(r[1]).strip()
            bt = int(float(r[2] or 0))
            anahtar = (en, pr)
            biten_map[anahtar] = biten_map.get(anahtar, 0) + bt

        # 5) BAŞLAYACAK: Urt_wait_gch + Urtx_wait_gch UNION
        cur.execute(f"""
            SELECT g.EmirNo, g.Proses, SUM(ISNULL(g.Giren, 0)) AS Baslayacak
            FROM Urt_wait_gch g WITH (NOLOCK)
            WHERE g.EmirNo IN ({ph})
            GROUP BY g.EmirNo, g.Proses

            UNION ALL

            SELECT g.EmirNo, g.Proses, SUM(ISNULL(g.Giren, 0)) AS Baslayacak
            FROM Urtx_wait_gch g WITH (NOLOCK)
            WHERE g.EmirNo IN ({ph})
            GROUP BY g.EmirNo, g.Proses
        """, tuple(gch_emirler) + tuple(gch_emirler))

        baslayacak_map = {}
        for r in cur.fetchall():
            en = int(r[0])
            pr = str(r[1]).strip()
            bs = int(float(r[2] or 0))
            anahtar = (en, pr)
            baslayacak_map[anahtar] = baslayacak_map.get(anahtar, 0) + bs

        # 6) Proses adlari (Proses_M)
        tum_proses_kodlari = set()
        for k in biten_map.keys():
            tum_proses_kodlari.add(k[1])
        for k in baslayacak_map.keys():
            tum_proses_kodlari.add(k[1])

        proses_adlari = {}
        if tum_proses_kodlari:
            ph_p = ','.join(['%s'] * len(tum_proses_kodlari))
            cur.execute(f"""
                SELECT Pro, Tanim
                FROM Proses_M WITH (NOLOCK)
                WHERE Pro IN ({ph_p})
            """, tuple(tum_proses_kodlari))
            for r in cur.fetchall():
                proses_adlari[str(r[0]).strip()] = r[1]

        # 7) Her emir icin proses listesi olustur
        for (en, pr), bt in biten_map.items():
            if en not in emir_meta:
                continue
            adi = proses_adlari.get(pr, pr)
            bs = baslayacak_map.pop((en, pr), 0)  # baslayacak da varsa al
            emir_meta[en]['prosesler'].append({
                'proses_kod': pr,
                'proses_adi': adi,
                'biten': bt,
                'baslayacak': bs,
                'devam': 0,
            })

        # 8) Sadece baslayacak (biten yok) olanlar
        for (en, pr), bs in baslayacak_map.items():
            if en not in emir_meta:
                continue
            adi = proses_adlari.get(pr, pr)
            emir_meta[en]['prosesler'].append({
                'proses_kod': pr,
                'proses_adi': adi,
                'biten': 0,
                'baslayacak': bs,
                'devam': 0,
            })

        cur.close()
        return list(emir_meta.values())
    finally:
        con.close()


def _sql_siparis_listesi_full():
    """Tum aktif siparisleri ozet bilgi ile dondurur.
    /* CANLI BATCH FIX */ - tek sorguda tum siparis+emir+proses bilgisi.
    PLAN listesi icin hizli, detay tıklayinca ayri sorgu.
    """
    siparisler = _sql_get_siparis_listesi()
    if not siparisler:
        return []

    sip_no_listesi = [s['sip_no'] for s in siparisler]

    # Tek batch: tum siparislerin tum emirlerini cek
    con = _korgun_baglan()
    try:
        cur = con.cursor()
        ph_sip = ','.join(['%s'] * len(sip_no_listesi))

        # 1) Tum sip -> emir map
        cur.execute(f"""
            SELECT DISTINCT g.FisNo, g.EmirNo
            FROM Urt_Em_gch g WITH (NOLOCK)
            WHERE g.FisNo IN ({ph_sip})
        """, tuple(sip_no_listesi))

        sip_emir_map = {}  # sip_no -> [emir_no_list]
        tum_emirler = set()
        for r in cur.fetchall():
            sn = int(r[0])
            en = int(r[1])
            if sn not in sip_emir_map:
                sip_emir_map[sn] = []
            sip_emir_map[sn].append(en)
            tum_emirler.add(en)

        if not tum_emirler:
            cur.close()
            sonuc_bos = []
            for sip in siparisler:
                sip_kopya = dict(sip)
                sip_kopya['emir_sayisi'] = {'mamul': 0, 'atki': 0, 'govde': 0}
                sip_kopya['korgun'] = {'atki_tamamlanan': 0, 'govde_tamamlanan': 0, 'mamul_tamamlanan': 0}
                sonuc_bos.append(sip_kopya)
            return sonuc_bos

        emir_listesi = list(tum_emirler)
        emir_meta = {}

        # /* CHUNK 2100 FIX */ - 500'erli chunk
        CHUNK = 500
        for i in range(0, len(emir_listesi), CHUNK):
            chunk = emir_listesi[i:i+CHUNK]
            ph_em = ','.join(['%s'] * len(chunk))

            # 2) Emir bilgisi (Urt + Urtx) - 2x parametre = 1000 max
            cur.execute(f"""
                SELECT e.EmirNo, e.ModelKod, UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) AS Tip,
                       ISNULL(e.YazSay, 0) AS YazSay,
                       ISNULL(sk.Tanim, e.ModelKod) AS ModelAdi
                FROM Urt_Emir e WITH (NOLOCK)
                LEFT JOIN StokKart sk WITH (NOLOCK) ON sk.SKod = e.ModelKod
                WHERE e.EmirNo IN ({ph_em})

                UNION ALL

                SELECT e.EmirNo, e.ModelKod, UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) AS Tip,
                       ISNULL(e.YazSay, 0) AS YazSay,
                       ISNULL(sk.Tanim, e.ModelKod) AS ModelAdi
                FROM Urtx_Emir e WITH (NOLOCK)
                LEFT JOIN StokKart sk WITH (NOLOCK) ON sk.SKod = e.ModelKod
                WHERE e.EmirNo IN ({ph_em})
            """, tuple(chunk) + tuple(chunk))

            for r in cur.fetchall():
                en = int(r[0])
                if en in emir_meta:
                    continue
                mk = r[1] or ''
                ma = r[4] or mk
                emir_meta[en] = {
                    'emir_no': en,
                    'model_kod': mk,
                    'tip': r[2] or 'M',
                    'yaz_say': int(float(r[3] or 0)),
                    'kategori': _kategori_belirle(mk, ma),
                    'son_proses_kod': -1,
                    'son_proses_biten': 0,
                }

            # 3) Her emirin SON prosesi - chunk
            cur.execute(f"""
                SELECT g.EmirNo, g.Proses, SUM(g.Cikan) AS Biten
                FROM Urt_con_gch g WITH (NOLOCK)
                WHERE g.EmirNo IN ({ph_em}) AND g.Cikan > 0
                GROUP BY g.EmirNo, g.Proses

                UNION ALL

                SELECT g.EmirNo, g.Proses, SUM(g.Cikan) AS Biten
                FROM Urtx_con_gch g WITH (NOLOCK)
                WHERE g.EmirNo IN ({ph_em}) AND g.Cikan > 0
                GROUP BY g.EmirNo, g.Proses
            """, tuple(chunk) + tuple(chunk))

            for r in cur.fetchall():
                en = int(r[0])
                pr = str(r[1]).strip()
                try:
                    pr_int = int(pr)
                except Exception:
                    continue
                bt = int(float(r[2] or 0))
                if en not in emir_meta:
                    continue
                if pr_int > emir_meta[en]['son_proses_kod']:
                    emir_meta[en]['son_proses_kod'] = pr_int
                    emir_meta[en]['son_proses_biten'] = bt

        cur.close()
    finally:
        con.close()

    # 4) Her siparis icin ozet hesapla
    sonuc = []
    for sip in siparisler:
        sn = sip['sip_no']
        emir_nos = sip_emir_map.get(sn, [])

        atki_t = 0
        govde_t = 0
        mamul_t = 0
        atki_count = 0
        govde_count = 0
        mamul_count = 0

        for en in emir_nos:
            meta = emir_meta.get(en)
            if not meta:
                continue
            kat = meta['kategori']
            if kat == 'ATKI':
                atki_count += 1
                atki_t += meta['son_proses_biten']
            elif kat == 'GOVDE':
                govde_count += 1
                govde_t += meta['son_proses_biten']
            elif kat == 'MAMUL':
                mamul_count += 1
                mamul_t += meta['son_proses_biten']

        sip_kopya = dict(sip)
        sip_kopya['emir_sayisi'] = {
            'mamul': mamul_count,
            'atki': atki_count,
            'govde': govde_count,
        }
        sip_kopya['korgun'] = {
            'atki_tamamlanan': atki_t,
            'govde_tamamlanan': govde_t,
            'mamul_tamamlanan': mamul_t,
        }
        sonuc.append(sip_kopya)

    return sonuc


# get_siparis_listesi'i guncelle - MOCK kontrol
_orig_get_siparis_listesi = get_siparis_listesi if 'get_siparis_listesi' in dir() else None


def get_siparis_listesi_canli():
    """CANLI Korgun'dan siparis listesi."""
    if MOCK_MODE:
        return _orig_get_siparis_listesi() if _orig_get_siparis_listesi else []
    try:
        sonuc = _sql_siparis_listesi_full()
        # _emirler_cache alanini cikar (sadece liste icin)
        for s in sonuc:
            s.pop('_emirler_cache', None)
        return sonuc
    except Exception as e:
        try:
            print(f'[korgun_v2 SQL liste hata]: {e}')
        except Exception:
            pass
        return []


def get_siparis_detay_v2_canli(sip_no):
    """CANLI Korgun'dan siparis detayi (hiyerarsik)."""
    if MOCK_MODE:
        return get_siparis_detay_v2(sip_no) if 'get_siparis_detay_v2' in dir() else None

    try:
        # Once siparisin meta bilgisini al
        siparisler = _sql_get_siparis_listesi()
        sip = None
        for s in siparisler:
            if int(s['sip_no']) == int(sip_no):
                sip = s
                break

        if not sip:
            return None

        # Emirler
        emirler = _sql_get_siparis_emirler(int(sip_no))

        if not emirler:
            return None

        hedef = int(sip.get('hedef', 0) or 0)

        atki_emirler = [e for e in emirler if e.get('kategori') == 'ATKI']
        govde_emirler = [e for e in emirler if e.get('kategori') == 'GOVDE']
        mamul_emirler = [e for e in emirler if e.get('kategori') == 'MAMUL']

        # Modeller bazli grupla
        model_gruplari = {}
        for me in mamul_emirler:
            mk = me.get('model_kod', '?')
            ma = me.get('model_adi', mk)
            if mk not in model_gruplari:
                model_gruplari[mk] = {
                    'model_kod': mk,
                    'model_adi': ma,
                    'mamul_emirler': [],
                }
            model_gruplari[mk]['mamul_emirler'].append(me)

        if not model_gruplari and sip.get('model_kod'):
            model_gruplari[sip['model_kod']] = {
                'model_kod': sip['model_kod'],
                'model_adi': sip.get('model_adi', sip['model_kod']),
                'mamul_emirler': [],
            }

        modeller_listesi = []
        for mk, grup in model_gruplari.items():
            mamul_emir_detaylari = []
            kat_atki_t = 0
            kat_govde_t = 0
            kat_mamul_t = 0

            for me in grup['mamul_emirler']:
                atki_iliskili = [a for a in atki_emirler if a.get('parent_emir') == me['emir_no']]
                govde_iliskili = [g for g in govde_emirler if g.get('parent_emir') == me['emir_no']]
                korgun = _emir_korgun_blok(me, atki_iliskili, govde_iliskili)
                mamul_emir_detaylari.append({
                    'emir_no': me['emir_no'],
                    'yaz_say': int(me.get('yaz_say', 0) or 0),
                    'korgun': korgun,
                })
                kat_atki_t += korgun['atki']['tamamlanan']
                kat_govde_t += korgun['govde']['tamamlanan']
                kat_mamul_t += korgun['mamul']['son_yapilan']

            # Parent_emir'i olmayan ATKI/GOVDE varsa bunlari da ek olarak goster
            # (mamul_emir bagi bulunamadi)
            modeller_listesi.append({
                'model_kod': grup['model_kod'],
                'model_adi': grup['model_adi'],
                'hedef_pay': hedef,
                'mamul_emirler': mamul_emir_detaylari,
                'kategori_ozet': {
                    'atki_tamamlanan': kat_atki_t,
                    'govde_tamamlanan': kat_govde_t,
                    'mamul_tamamlanan': kat_mamul_t,
                },
            })

        # Toplam
        toplam_atki = sum(_son_proses_yapilan(e.get('prosesler', []))[0] for e in atki_emirler)
        toplam_govde = sum(_son_proses_yapilan(e.get('prosesler', []))[0] for e in govde_emirler)
        toplam_mamul = sum(_son_proses_yapilan(e.get('prosesler', []))[0] for e in mamul_emirler)

        return {
            'sip_no': int(sip_no),
            'musteri': sip.get('musteri'),
            'cari_kod': sip.get('cari_kod'),
            'model_kod': sip.get('model_kod'),
            'model_adi': sip.get('model_adi'),
            'hedef': hedef,
            'termin': sip.get('termin'),
            'belge_no': sip.get('belge_no'),
            'model_sayisi': len(modeller_listesi),
            'modeller': modeller_listesi,
            'toplam_korgun': {
                'atki_tamamlanan': toplam_atki,
                'govde_tamamlanan': toplam_govde,
                'mamul_tamamlanan': toplam_mamul,
            },
        }
    except Exception as e:
        try:
            print(f'[korgun_v2 SQL detay hata sip {sip_no}]: {e}')
            import traceback
            traceback.print_exc()
        except Exception:
            pass
        return None


# Mevcut fonksiyonlari override et (canli moda gec)
_orig_get_siparis_listesi_v2 = get_siparis_listesi
get_siparis_listesi = get_siparis_listesi_canli

_orig_get_siparis_detay_v2 = get_siparis_detay_v2
get_siparis_detay_v2 = get_siparis_detay_v2_canli

