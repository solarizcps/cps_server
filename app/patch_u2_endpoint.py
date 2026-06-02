"""ADIM U2: plan_v2.py'ye yeni endpoint /plan-detay-v2/<sip_no>.

KURAL:
- Mevcut /plan-detay degismez (frontend hala onu kullaniyor)
- Yeni endpoint hiyerarsik response doner
- CPS verisi mamul emir bazinda toplanir
- Korgun ve CPS yine ASLA birlestirilmez
- bitmis_mamul, uretim_asamasi, summary mevcut helper'lar ile
"""
import io, sys, shutil, time

PP = r'C:\cps_dev\modules\hedef\plan_v2.py'
MARKER = "@plan_v2_bp.route('/plan-detay-v2"

with io.open(PP, 'r', encoding='utf-8') as f:
    psrc = f.read()

if MARKER in psrc:
    print('SKIP: U2 zaten uygulanmis')
    sys.exit(0)

# Anchor: saglik endpoint'inin oncesine ekle
ANCHOR = """@plan_v2_bp.route('/saglik', methods=['GET'])"""

if ANCHOR not in psrc:
    print('HATA: saglik endpoint anchor bulunamadi')
    sys.exit(1)

NEW_ENDPOINT = '''@plan_v2_bp.route('/plan-detay-v2/<int:sip_no>', methods=['GET'])
def plan_v2_detay_hiyerarsik(sip_no):
    """Hiyerarsik detay: Siparis -> Model -> Mamul Emir -> Korgun + CPS.

    KURAL:
    - Korgun ve CPS asla birlestirilmez
    - Her mamul emir icin Korgun blok (atki/govde/mamul) ve CPS blok ayri
    - Siparis bazinda toplam darbogaz hesaplanir (sadece Korgun)
    - bitmis_mamul, uretim_asamasi, summary mevcut helper'lar
    """
    try:
        d = _kv2.get_siparis_detay_v2(sip_no)
    except Exception as e:
        return jsonify({
            'ok': False,
            'mesaj': 'Korgun veri katmani hatasi: ' + str(e)[:120],
        }), 500

    if not d:
        return jsonify({
            'ok': False,
            'mesaj': 'Siparis bulunamadi: ' + str(sip_no),
        }), 404

    # Her mamul emir icin CPS verisi (CPS sadece bilgi, hesaba dahil degil)
    # Tum mamul emir nolarini topla -> bir kerede CPS sorgu
    tum_mamul_emirler = []
    for m in d.get('modeller', []):
        for me in m.get('mamul_emirler', []):
            try:
                tum_mamul_emirler.append(int(me['emir_no']))
            except Exception:
                pass

    try:
        cps_genel = _cv2.get_cps_siparis(sip_no, tum_mamul_emirler)
    except Exception as e:
        cps_genel = {
            'sablon_prosesleri': [],
            'personel_uretim': [],
            'prim_performans': None,
            'hata': str(e)[:120],
        }

    # Her mamul emir icin CPS verisi - bu emirin emir_no + alt emir nolari
    # cps_v2.get_cps_siparis tum emir listesi alabilir
    for m in d.get('modeller', []):
        for me in m.get('mamul_emirler', []):
            emir_listesi_e = [int(me['emir_no'])]
            korgun = me.get('korgun', {})
            for ae in korgun.get('atki', {}).get('emirler', []):
                try:
                    emir_listesi_e.append(int(ae['emir_no']))
                except Exception:
                    pass
            for ge in korgun.get('govde', {}).get('emirler', []):
                try:
                    emir_listesi_e.append(int(ge['emir_no']))
                except Exception:
                    pass
            try:
                me['cps'] = _cv2.get_cps_siparis(sip_no, emir_listesi_e)
            except Exception:
                me['cps'] = {
                    'sablon_prosesleri': [],
                    'personel_uretim': [],
                    'prim_performans': None,
                }

    # Toplam darbogaz (siparis bazinda, sadece Korgun)
    toplam = d.get('toplam_korgun', {})
    darb = _darbogaz_hesapla(
        toplam.get('atki_tamamlanan', 0),
        toplam.get('govde_tamamlanan', 0),
        toplam.get('mamul_tamamlanan', 0),
        d.get('hedef', 0)
    )

    # bitmis_mamul + uretim_asamasi + summary
    # Tum emirleri topla (sadece Korgun)
    tum_emirler_for_helper = []
    tum_mamul_for_helper = []
    for m in d.get('modeller', []):
        for me in m.get('mamul_emirler', []):
            korgun = me.get('korgun', {})
            mamul_emir_obj = {
                'emir_no': korgun.get('mamul', {}).get('emir_no'),
                'prosesler': korgun.get('mamul', {}).get('prosesler', []),
            }
            tum_mamul_for_helper.append(mamul_emir_obj)
            tum_emirler_for_helper.append(mamul_emir_obj)
            for ae in korgun.get('atki', {}).get('emirler', []):
                tum_emirler_for_helper.append({
                    'emir_no': ae.get('emir_no'),
                    'prosesler': ae.get('prosesler', []),
                })
            for ge in korgun.get('govde', {}).get('emirler', []):
                tum_emirler_for_helper.append({
                    'emir_no': ge.get('emir_no'),
                    'prosesler': ge.get('prosesler', []),
                })

    bitmis = _kv2.hesapla_bitmis_mamul(tum_mamul_for_helper)
    asama = _kv2.hesapla_uretim_asamasi(tum_emirler_for_helper)
    summary = _kv2.yapilandir_summary(bitmis, asama, darb.get('kategori'))

    return jsonify({
        'ok': True,
        'sip_no': d['sip_no'],
        'musteri': d.get('musteri'),
        'cari_kod': d.get('cari_kod'),
        'hedef': d.get('hedef'),
        'termin': d.get('termin'),
        'belge_no': d.get('belge_no'),
        'model_sayisi': d.get('model_sayisi', 0),
        'modeller': d.get('modeller', []),
        'cps_genel': cps_genel,
        'toplam_korgun': d.get('toplam_korgun', {}),
        'darbogaz': darb,
        'bitmis_mamul': bitmis,
        'uretim_asamasi': asama,
        'summary': summary,
    })


'''

# Anchor'in onune ekle
new_psrc = psrc.replace(ANCHOR, NEW_ENDPOINT + ANCHOR, 1)

if new_psrc == psrc:
    print('HATA: insertion yapilamadi')
    sys.exit(1)

bak = PP + '.bak_pre_u2_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(PP, bak)
print('Yedek: ' + bak)

with io.open(PP, 'w', encoding='utf-8') as f:
    f.write(new_psrc)

artis = len(new_psrc) - len(psrc)
print('OK: U2 endpoint eklendi (' + str(artis) + ' byte)')
print('Test: http://localhost:5057/hedef/v2/plan-detay-v2/33638')