"""CPS PLAN v2 - Endpoint'ler.

KURAL:
- PLAN siparis bazli (her satir = 1 siparis)
- Korgun ve CPS ASLA birlestirilmez
- Darbogaz = min(ATKI, GOVDE, MAMUL) sadece Korgun verisi
- CPS sadece bilgi olarak gosterilir, hesaba dahil edilmez
"""
from flask import Blueprint, jsonify, render_template, request
from modules.auth import yetki_gerekli
from modules.hedef import korgun_v2 as _kv2
from modules.hedef import cps_v2 as _cv2

plan_v2_bp = Blueprint('plan_v2', __name__, url_prefix='/hedef/v2')


def _darbogaz_hesapla(atki_t, govde_t, mamul_t, hedef):
    """min(ATKI, GOVDE, MAMUL) - sadece Korgun verisi.

    NULL=0 kabul edilir (sablon yoksa o parca 0 sayilir).
    Her zaman 3 deger uzerinden min alinir.
    """
    a = int(atki_t or 0)
    g = int(govde_t or 0)
    m = int(mamul_t or 0)

    yapilan = min(a, g, m)
    kalan = max(0, hedef - yapilan)
    yuzde = round((yapilan / hedef * 100), 1) if hedef > 0 else 0.0

    # Darbogaz = en kuculuk olan kategori
    if a <= g and a <= m:
        kategori = 'ATKI'
    elif g <= a and g <= m:
        kategori = 'GOVDE'
    else:
        kategori = 'MAMUL'

    # Renk
    if yapilan == 0:
        renk = 'kirmizi'
    elif yuzde < 50:
        renk = 'sari'
    else:
        renk = 'yesil'

    return {
        'yapilan': yapilan,
        'kalan': kalan,
        'yuzde': yuzde,
        'kategori': kategori,
        'renk': renk,
    }


@plan_v2_bp.route('/', methods=['GET'])
@yetki_gerekli('hedef', 'can_view')
def plan_v2_sayfa():
    """Yeni PLAN sayfasi (HTML)."""
    return render_template('hedef/plan_v2.html')


@plan_v2_bp.route('/plan', methods=['GET'])
@yetki_gerekli('hedef', 'can_view')
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

    # PAGINATION_V1
    try:
        sayfa = int(request.args.get('page', 1))
    except:
        sayfa = 1
    if sayfa < 1: sayfa = 1
    limit = 10
    toplam = len(sonuc)
    toplam_sayfa = max(1, (toplam + limit - 1) // limit)
    if sayfa > toplam_sayfa: sayfa = toplam_sayfa
    bas = (sayfa - 1) * limit
    response = {
        'ok': True,
        'siparis_sayisi': toplam,
        'mevcut_sayfa': sayfa,
        'toplam_sayfa': toplam_sayfa,
        'limit': limit,
        'siparisler': sonuc[bas:bas+limit],
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


@plan_v2_bp.route('/plan-detay/<int:sip_no>', methods=['GET'])
@yetki_gerekli('hedef', 'can_view')
def plan_v2_detay(sip_no):
    """Siparis detay - Korgun + CPS ayri bloklar.

    Donus:
    {
        ok, sip_no, musteri, model_kod, hedef, termin,
        korgun: {atki: {...}, govde: {...}, mamul: {...}},
        cps: {sablon_prosesleri, personel_uretim, prim_performans},
        darbogaz: {kategori, yapilan, kalan, yuzde, renk}
    }
    """
    try:
        d = _kv2.get_siparis_detay(sip_no)
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

    # Tum emir nolarini topla (CPS sorgulari icin)
    tum_emirler = []
    for kat in ('atki', 'govde', 'mamul'):
        blok = d.get(kat, {})
        for e in blok.get('emirler', []):
            try:
                tum_emirler.append(int(e['emir_no']))
            except Exception:
                pass

    # CPS verisi (gercek SQLite'tan)
    try:
        cps = _cv2.get_cps_siparis(sip_no, tum_emirler)
    except Exception as e:
        cps = {
            'sablon_prosesleri': [],
            'personel_uretim': [],
            'prim_performans': None,
            'hata': str(e)[:120],
        }

    # Darbogaz hesabi (sadece Korgun)
    atki_blok = d.get('atki', {})
    govde_blok = d.get('govde', {})
    mamul_blok = d.get('mamul', {})

    darb = _darbogaz_hesapla(
        atki_blok.get('tamamlanan', 0),
        govde_blok.get('tamamlanan', 0),
        mamul_blok.get('tamamlanan', 0),
        d.get('hedef', 0)
    )

    # bitmis_mamul + uretim_asamasi + summary (Korgun emirler uzerinden)
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
    })


@plan_v2_bp.route('/plan-detay-v2/<int:sip_no>', methods=['GET'])
@yetki_gerekli('hedef', 'can_view')
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

    # PATCH 3: proses_tablosu (siparis bazli) + kategori_durum + ozet
    # Tum emirleri tek listeye topla
    _tum_emirler_p3 = []
    _tum_atki_p3 = []
    _tum_govde_p3 = []
    _tum_mamul_p3 = []
    _modeller_p3 = d.get('modeller', [])
    for _m_p3 in _modeller_p3:
        for _me_p3 in _m_p3.get('mamul_emirler', []):
            _korgun_p3 = _me_p3.get('korgun') or {}
            _mamul_blok_p3 = _korgun_p3.get('mamul') or {}
            _mamul_emir_obj_p3 = {
                'emir_no': _mamul_blok_p3.get('emir_no'),
                'prosesler': _mamul_blok_p3.get('prosesler', []),
                'kategori': 'MAMUL',
            }
            _tum_emirler_p3.append(_mamul_emir_obj_p3)
            _tum_mamul_p3.append(_mamul_emir_obj_p3)
            for _ae_p3 in (_korgun_p3.get('atki') or {}).get('emirler', []):
                _ae_obj_p3 = {
                    'emir_no': _ae_p3.get('emir_no'),
                    'prosesler': _ae_p3.get('prosesler', []),
                    'kategori': 'ATKI',
                }
                _tum_emirler_p3.append(_ae_obj_p3)
                _tum_atki_p3.append(_ae_obj_p3)
            for _ge_p3 in (_korgun_p3.get('govde') or {}).get('emirler', []):
                _ge_obj_p3 = {
                    'emir_no': _ge_p3.get('emir_no'),
                    'prosesler': _ge_p3.get('prosesler', []),
                    'kategori': 'GOVDE',
                }
                _tum_emirler_p3.append(_ge_obj_p3)
                _tum_govde_p3.append(_ge_obj_p3)

    _hedef_p3 = d.get('hedef', 0) or 0
    _proses_tab_p3 = _kv2.proses_tablosu_uret(_tum_emirler_p3, _hedef_p3)
    _kategori_durum_p3 = _kv2.hesapla_kategori_durum(
        _tum_atki_p3, _tum_govde_p3, _tum_mamul_p3, _hedef_p3
    )
    _hazirlik_p3 = _kv2.hesapla_kesim_toplam(_tum_mamul_p3)
    _uretim_durumu_p3 = _kv2.hesapla_uretim_durumu_v2(darb.get('yapilan', 0))
    _summary_v2_p3 = _kv2.hesapla_summary_v2(
        bitmis, _hazirlik_p3, _uretim_durumu_p3,
        darb.get('kategori'), darb.get('durum')
    )

    # Her model icin kendi proses_tablosu uret
    for _m_p3 in _modeller_p3:
        _model_emirler_p3 = []
        for _me_p3 in _m_p3.get('mamul_emirler', []):
            _korgun_p3 = _me_p3.get('korgun') or {}
            _model_emirler_p3.append({
                'kategori': 'MAMUL',
                'prosesler': (_korgun_p3.get('mamul') or {}).get('prosesler', []),
            })
            for _ae_p3 in (_korgun_p3.get('atki') or {}).get('emirler', []):
                _model_emirler_p3.append({
                    'kategori': 'ATKI',
                    'prosesler': _ae_p3.get('prosesler', []),
                })
            for _ge_p3 in (_korgun_p3.get('govde') or {}).get('emirler', []):
                _model_emirler_p3.append({
                    'kategori': 'GOVDE',
                    'prosesler': _ge_p3.get('prosesler', []),
                })
        _model_hedef_p3 = _m_p3.get('hedef_pay', _hedef_p3) or _hedef_p3
        _m_p3['proses_tablosu'] = _kv2.proses_tablosu_uret(_model_emirler_p3, _model_hedef_p3)

    # Ozet objesi
    _ozet_p3 = {
        'cikti': bitmis,
        'hazirlik': _hazirlik_p3,
        'uretim_durumu': _uretim_durumu_p3,
        'darbogaz': darb.get('kategori'),
        'darbogaz_durum': darb.get('durum') or 'bekleniyor',
        'summary': _summary_v2_p3,
    }

    return jsonify({
        'ok': True,
        'sip_no': d['sip_no'],
        'musteri': d.get('musteri'),
        'cari_kod': d.get('cari_kod'),
        'hedef': d.get('hedef'),
        'termin': d.get('termin'),
        'belge_no': d.get('belge_no'),
        'model_sayisi': d.get('model_sayisi', 0),
        'modeller': _modeller_p3,
        'cps_genel': cps_genel,
        'toplam_korgun': d.get('toplam_korgun', {}),
        'darbogaz': darb,
        'bitmis_mamul': bitmis,
        'uretim_asamasi': asama,
        'summary': summary,
        'proses_tablosu': _proses_tab_p3,
        'kategori_durum': _kategori_durum_p3,
        'ozet': _ozet_p3,
    })


@plan_v2_bp.route('/saglik', methods=['GET'])
@yetki_gerekli('hedef', 'can_view')
def plan_v2_saglik():
    """Sistem saglik kontrolu."""
    return jsonify({
        'ok': True,
        'mock_mode': _kv2.MOCK_MODE,
        'mesaj': 'PLAN v2 calisiyor' + (' (MOCK)' if _kv2.MOCK_MODE else ' (CANLI)'),
    })