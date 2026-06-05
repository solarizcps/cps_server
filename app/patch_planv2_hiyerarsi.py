"""ADIM U1: korgun_v2.py - get_siparis_detay() hiyerarsik donus.

KURAL:
- Siparis -> Model -> Mamul Emir -> Korgun(ATKI/GOVDE/MAMUL)
- Tek modelli ya da coklu model destegi (modeller[] her zaman list)
- Mock data dokunulmuyor
- Mevcut get_siparis_listesi degismiyor (korunacak alanlar zaten var)
"""
import io, sys, shutil, time

KP = r'C:\cps_dev\modules\hedef\korgun_v2.py'
MARKER = 'def get_siparis_detay_v2'

with io.open(KP, 'r', encoding='utf-8') as f:
    ksrc = f.read()

if MARKER in ksrc:
    print('SKIP: U1 zaten uygulanmis')
    sys.exit(0)

# Dosyanin sonuna yeni hiyerarsik fonksiyon ekle
NEW_FUNC = '''


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
'''

bak = KP + '.bak_pre_u1_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(KP, bak)
print('Yedek: ' + bak)

with io.open(KP, 'w', encoding='utf-8') as f:
    f.write(ksrc.rstrip() + NEW_FUNC + '\n')

artis = len(NEW_FUNC) + 1
print('OK: get_siparis_detay_v2 eklendi (' + str(artis) + ' byte)')
print('Test: import edip cagir veya plan_v2.py adapte et (U2)')