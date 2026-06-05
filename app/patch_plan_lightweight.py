"""PATCH: PLAN endpoint lightweight + sure logu.

1) /hedef/v2/plan SADECE OZET donmesin
   - sip_no, musteri, model_kod, hedef, termin, ozet, darbogaz, yuzde, durum_renk
   - emir detaylari, modeller, prosesler GELMEYECEK
2) Sure logu eklenir (Korgun query, JSON, total)
3) Response size logu

Detay endpoint /plan-detay-v2/<sip_no> degismez (lazy load).
DB yapisi degismez.
"""
import io, sys, shutil, time

PP = r'C:\cps_dev\modules\hedef\plan_v2.py'
MARKER = '/* PLAN LIGHTWEIGHT */'

with io.open(PP, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: lightweight zaten uygulanmis')
    sys.exit(0)

OLD = """@plan_v2_bp.route('/plan', methods=['GET'])
def plan_v2_liste():"""

if OLD not in src:
    print('HATA: anchor bulunamadi')
    sys.exit(1)

# Eski fonksiyonu komple yenisi ile degistir
# Anchor ile bir sonraki @plan_v2_bp.route arasini ez
ANCHOR_BAS = OLD
ANCHOR_SON = "@plan_v2_bp.route('/plan-detay/<int:sip_no>'"

bas_idx = src.find(ANCHOR_BAS)
son_idx = src.find(ANCHOR_SON)

if bas_idx < 0 or son_idx < 0 or son_idx < bas_idx:
    print('HATA: range bulunamadi')
    sys.exit(1)

YENI_FONK = '''@plan_v2_bp.route('/plan', methods=['GET'])
def plan_v2_liste():
    """PLAN ana liste - SADECE OZET. /* PLAN LIGHTWEIGHT */

    Donus alanlari:
    - sip_no, musteri, model_kod, model_adi, hedef, termin, belge_no
    - ozet (cikti, hazirlik, uretim_durumu, darbogaz, summary)
    - yapilan, kalan, yuzde, darbogaz_kategori, durum_renk
    - emir_sayisi (sayilar, detay yok)

    Emir detaylari, prosesler, CPS verisi DETAY endpoint'tinde gelir.
    """
    import time as _time
    import json as _json
    from flask import current_app

    t0 = _time.time()

    try:
        t_korgun_bas = _time.time()
        siparisler = _kv2.get_siparis_listesi()
        t_korgun = _time.time() - t_korgun_bas
    except Exception as e:
        return jsonify({
            'ok': False,
            'mesaj': 'Korgun veri katmani hatasi: ' + str(e)[:120],
            'siparisler': [],
        }), 500

    t_proc_bas = _time.time()

    sonuc = []
    for s in siparisler:
        k = s.get('korgun', {})
        d = _darbogaz_hesapla(
            k.get('atki_tamamlanan', 0),
            k.get('govde_tamamlanan', 0),
            k.get('mamul_tamamlanan', 0),
            s.get('hedef', 0)
        )

        # Ozet alanlarini hesapla (helper'dan)
        try:
            kesim_t = 0  # PLAN listesinde Kesim toplam bilinmiyor (detay'da hesaplanir)
            uretim_durumu = _kv2.hesapla_uretim_durumu_v2(d['yapilan'])
            db_durum = 'bekleniyor' if d['yapilan'] == 0 else 'devam ediyor'
            summary = _kv2.hesapla_summary_v2(
                0,  # bitmis_mamul - PLAN listesinde 0 (FINAL_PROSES_MAP bos)
                kesim_t,
                uretim_durumu,
                d['kategori'],
                db_durum
            )
            ozet = {
                'cikti': 0,
                'hazirlik': kesim_t,
                'uretim_durumu': uretim_durumu,
                'darbogaz': d['kategori'],
                'darbogaz_durum': db_durum,
                'summary': summary,
            }
        except Exception:
            ozet = {
                'cikti': 0, 'hazirlik': 0,
                'uretim_durumu': '?', 'darbogaz': d['kategori'],
                'darbogaz_durum': '?', 'summary': '',
            }

        sonuc.append({
            'sip_no': s.get('sip_no'),
            'musteri': s.get('musteri'),
            'model_kod': s.get('model_kod'),
            'model_adi': s.get('model_adi'),
            'hedef': s.get('hedef'),
            'termin': s.get('termin'),
            'belge_no': s.get('belge_no'),
            'emir_sayisi': s.get('emir_sayisi', {}),
            'yapilan': d['yapilan'],
            'kalan': d['kalan'],
            'yuzde': d['yuzde'],
            'darbogaz_kategori': d['kategori'],
            'durum_renk': d['renk'],
            'ozet': ozet,
        })

    t_proc = _time.time() - t_proc_bas

    response = {
        'ok': True,
        'siparis_sayisi': len(sonuc),
        'siparisler': sonuc,
    }

    # Response size hesabi (kabaca)
    try:
        rsp_size_kb = round(len(_json.dumps(response)) / 1024, 1)
    except Exception:
        rsp_size_kb = -1

    t_total = _time.time() - t0

    try:
        print(f'[PLAN /plan] korgun={t_korgun:.2f}s proc={t_proc:.2f}s '
              f'total={t_total:.2f}s sip={len(sonuc)} size={rsp_size_kb}KB')
    except Exception:
        pass

    return jsonify(response)


'''

new_src = src[:bas_idx] + YENI_FONK + src[son_idx:]

bak = PP + '.bak_pre_lightweight_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(PP, bak)
print('Yedek: ' + bak)

with io.open(PP, 'w', encoding='utf-8') as f:
    f.write(new_src)

artis = len(new_src) - len(src)
print(f'OK: PLAN lightweight uygulandi ({artis} byte degisim)')
print('Beklenen iyilesme:')
print('  - Response: 5MB -> ~50KB')
print('  - JSON parse: yavas -> hizli')
print('  - Backend yine 3-5sn (Korgun ping yavas)')
print('  - Konsola sure logu: [PLAN /plan] korgun=Xs proc=Xs total=Xs')