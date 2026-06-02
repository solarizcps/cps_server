"""PATCH 3/4: plan_v2.py response zenginlestirme.

KURAL:
- /plan-detay-v2 response'una:
    proses_tablosu (siparis bazli)
    kategori_durum (ATKI/GOVDE/MAMUL)
    ozet (cikti, hazirlik, uretim_durumu, darbogaz, summary)
- Her model'in kendi proses_tablosu olur
- Mevcut alanlar bozulmaz (geriye uyum)
- /plan response'una sadece ozet eklenir (liste icin)
"""
import io, sys, shutil, time

PP = r'C:\cps_dev\modules\hedef\plan_v2.py'
MARKER = "'proses_tablosu':"

with io.open(PP, 'r', encoding='utf-8') as f:
    psrc = f.read()

if MARKER in psrc:
    print('SKIP: PATCH 3 zaten uygulanmis')
    sys.exit(0)

# === 1) /plan-detay-v2 response zenginlestir ===
OLD_DETAY_RETURN = """    return jsonify({
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
    })"""

NEW_DETAY_RETURN = """    # PATCH 3: proses_tablosu (siparis bazli) + kategori_durum + ozet
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
    })"""

if OLD_DETAY_RETURN not in psrc:
    print('HATA: /plan-detay-v2 return anchor bulunamadi')
    sys.exit(1)

new_psrc = psrc.replace(OLD_DETAY_RETURN, NEW_DETAY_RETURN, 1)

# === 2) /plan response'una ozet alani ekle ===
OLD_LISTE_APPEND = """        sonuc.append({
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

NEW_LISTE_APPEND = """        # PATCH 3: ozet hesabi (PLAN listesi)
        try:
            _detay_full_p3 = _kv2.get_siparis_detay_v2(s['sip_no']) or {}
        except Exception:
            _detay_full_p3 = {}
        _modeller_full_p3 = _detay_full_p3.get('modeller', [])
        _tum_mamul_p3 = []
        for _m_full_p3 in _modeller_full_p3:
            for _me_full_p3 in _m_full_p3.get('mamul_emirler', []):
                _korgun_full_p3 = _me_full_p3.get('korgun') or {}
                _mamul_blok_full_p3 = _korgun_full_p3.get('mamul') or {}
                _tum_mamul_p3.append({
                    'emir_no': _mamul_blok_full_p3.get('emir_no'),
                    'prosesler': _mamul_blok_full_p3.get('prosesler', []),
                    'kategori': 'MAMUL',
                })

        _hazirlik_liste_p3 = _kv2.hesapla_kesim_toplam(_tum_mamul_p3)
        _uretim_durumu_liste_p3 = _kv2.hesapla_uretim_durumu_v2(d['yapilan'])
        _summary_liste_p3 = _kv2.hesapla_summary_v2(
            _bitmis, _hazirlik_liste_p3, _uretim_durumu_liste_p3,
            d['kategori'], d['renk']
        )

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
            'summary': _summary_liste_p3,
            'ozet': {
                'cikti': _bitmis,
                'hazirlik': _hazirlik_liste_p3,
                'uretim_durumu': _uretim_durumu_liste_p3,
                'darbogaz': d['kategori'],
                'darbogaz_durum': 'bekleniyor' if d['yapilan'] == 0 else 'devam ediyor',
                'summary': _summary_liste_p3,
            },
        })"""

if OLD_LISTE_APPEND not in new_psrc:
    print('HATA: /plan liste anchor bulunamadi')
    sys.exit(1)

new_psrc2 = new_psrc.replace(OLD_LISTE_APPEND, NEW_LISTE_APPEND, 1)

bak = PP + '.bak_pre_p3_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(PP, bak)
print('Yedek: ' + bak)

with io.open(PP, 'w', encoding='utf-8') as f:
    f.write(new_psrc2)

artis = len(new_psrc2) - len(psrc)
print('OK: PATCH 3 response zenginlestirildi (' + str(artis) + ' byte)')
print()
print('Test:')
print('  http://localhost:5057/hedef/v2/plan')
print('  http://localhost:5057/hedef/v2/plan-detay-v2/33638')