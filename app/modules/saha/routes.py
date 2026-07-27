# -*- coding: utf-8 -*-

"""Solariz CPS — Saha Gelen İşler (Ferhat enjeksiyon doğrulama)."""

from __future__ import annotations



import os

import sqlite3

from functools import wraps



from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for



from modules.auth import is_superadmin, yetki_var

from modules.belge import belge_yukle

from modules.nexgen.nx_ar_service import (

    NxArError,

    calisma_tipi_etiket,

    ferhat_ac,

    ferhat_bekleyen_liste,

    ferhat_kalip_kaydet,

    ferhat_sonuc_kaydet,

    ferhat_wizard_baslik,

    ferhat_wizard_sonuc_metinleri,

    get_nx_ar,

)



saha_bp = Blueprint(

    'saha',

    __name__,

    url_prefix='/saha',

    template_folder='../../templates/saha',

)



DB_PATH = os.path.normpath(

    os.path.join(os.path.dirname(__file__), '..', '..', 'mock_data.db')

)



_FERHAT_DURUMLAR = frozenset({'FERHAT_BEKLIYOR', 'DENEMEDE'})





def _db():

    con = sqlite3.connect(DB_PATH)

    con.row_factory = sqlite3.Row

    return con





def _uid():

    u = session.get('kullanici')

    return u.get('Id') if u else None





def _kullanici_ad():

    u = session.get('kullanici')

    return u.get('KullaniciAdi', 'sistem') if u else 'sistem'





def ferhat_islem_gerekli(f):

    """Yalnız admin veya saha.ferhat_islem yetkisi."""

    @wraps(f)

    def wrapper(*args, **kwargs):

        u = session.get('kullanici')

        if not u:

            return redirect(url_for('auth.login', next=request.path))

        if is_superadmin(u) or yetki_var('saha.ferhat_islem', 'can_view'):

            return f(*args, **kwargs)

        abort(403)

    return wrapper





def _err(e: Exception):

    if isinstance(e, NxArError):

        return jsonify({'ok': False, 'hata': e.message, 'kod': e.kod}), e.status

    return jsonify({'ok': False, 'hata': str(e)}), 500





def _boyut_etiket_kisa(boyut: str) -> str:

    m = {'LARGE': 'L', 'SMALL': 'S', 'MEDIUM': 'M'}

    return m.get((boyut or '').upper(), boyut or '—')





def _kalip_dto(deneme: dict | None) -> dict | None:

    if not deneme:

        return None

    kid = deneme.get('kalip_id')

    if not kid:

        return None

    return {

        'kalip_id': kid,

        'kalip_kodu': deneme.get('kalip_kodu_snapshot'),

        'kalip_adi': deneme.get('kalip_adi_snapshot'),

        'beden_araligi': deneme.get('kalip_beden_snapshot'),

        'makine': deneme.get('kalip_makine_snapshot'),

        'kilitli': False,

    }





def _kalip_liste(con) -> list[dict]:

    rows = con.execute(

        """

        SELECT id, kalip_kod, model_ad, model_kod, asorti, kalip_tipi,

               COALESCE(kalip_durumu, 'AKTIF') AS kalip_durumu, aktif

        FROM enj_kalip

        WHERE aktif=1

          AND COALESCE(kalip_durumu, 'AKTIF') IN ('AKTIF', '')

        ORDER BY kalip_kod, model_kod, asorti

        """

    ).fetchall()

    out = []

    for r in rows:

        kod = (r['kalip_kod'] or '').strip()

        ad = (r['model_ad'] or r['model_kod'] or kod).strip()

        out.append({

            'kalip_id': r['id'],

            'kalip_kodu': kod,

            'kalip_adi': ad,

            'beden_araligi': (r['asorti'] or '').strip() or None,

            'makine': (r['kalip_tipi'] or '').strip() or None,

            'aktif': int(r['aktif'] or 0),

        })

    return out





def _liste_kart(row: dict) -> dict:

    durum = (row.get('durum') or '').upper()

    ui_durum = 'devam' if durum == 'DENEMEDE' else 'bekliyor'

    ui_lbl = 'Devam Ediyor' if durum == 'DENEMEDE' else 'Bekliyor'

    ct = row.get('calisma_tipi')

    wiz_lbl = ferhat_wizard_baslik(ct, durum=durum)

    return {

        'arge_test_id': row.get('arge_test_id'),

        'kod': row.get('test_no') or '—',

        'turLbl': wiz_lbl,

        'urun': row.get('hedef_renk_adi') or row.get('formul_grup_adi') or '—',

        'gonderen': row.get('cari_unvan') or 'AR-GE',

        'tarih': (row.get('olusturma_tarihi') or '')[:10] or '—',

        'durum': ui_durum,

        'durumLbl': ui_lbl,

        'detayBaslik': wiz_lbl,

        'calisma_tipi': ct,

        'nx_durum': durum,

    }





def _detay_dto(kart: dict) -> dict:

    deneme = kart.get('deneme') or {}

    ct = kart.get('calisma_tipi')

    nx_durum_raw = (kart.get('durum') or '').upper()

    wiz_lbl = ferhat_wizard_baslik(ct, durum=nx_durum_raw)

    shore_hedef = kart.get('shore_hedef')

    try:

        shore_def = int(float(shore_hedef)) if shore_hedef not in (None, '') else 42

    except (TypeError, ValueError):

        shore_def = 42

    aciklama_parcalar = []

    if kart.get('saha_testi_nedeni'):

        aciklama_parcalar.append(str(kart.get('saha_testi_nedeni')))

    if kart.get('talep_referansi'):

        aciklama_parcalar.append(str(kart.get('talep_referansi')))

    boyutlar = kart.get('boyutlar') or []

    kalip = _kalip_dto(deneme)

    nx_durum = (kart.get('durum') or '').upper()

    if kalip and nx_durum not in _FERHAT_DURUMLAR:

        kalip = dict(kalip, kilitli=True)

    return {

        'ok': True,

        'arge_test_id': kart.get('arge_test_id'),

        'kod': kart.get('test_no') or '—',

        'nx_durum': kart.get('durum'),

        'detayBaslik': wiz_lbl,

        'turLbl': wiz_lbl,

        'calisma_tipi': ct,

        'sonucMetinleri': ferhat_wizard_sonuc_metinleri(ct),

        'urun': kart.get('hedef_renk_adi') or kart.get('formul_grup_adi') or '—',

        'renk': kart.get('hedef_renk_adi') or kart.get('renk_kodu') or '—',

        'formul': kart.get('formul_grup_adi') or kart.get('ana_formul_grup_kodu') or '—',

        'cari': kart.get('cari_unvan') or '—',

        'boyutlar': boyutlar,

        'boyut_etiketleri': {_boyut_etiket_kisa(b): b for b in boyutlar},

        'kalip': kalip,

        'info': {

            'hammadde': kart.get('formul_grup_adi') or kart.get('ana_formul_grup_kodu') or '—',

            'tedarikci': kart.get('cari_unvan') or '—',

            'lot': deneme.get('lot_no') or kart.get('talep_referansi') or '—',

            'gonderen': kart.get('olusturan_ad') or '—',

            'aciklama': ' · '.join(aciklama_parcalar) if aciklama_parcalar else (kart.get('formul_grup_adi') or '—'),

            'boyut': kart.get('boyut_etiket') or ', '.join(_boyut_etiket_kisa(b) for b in boyutlar),

        },

        'olcum_defaults': {

            'pisme': 245,

            'enjeksiyon': 12,

            'shore': shore_def,

            'gramaj': 182,

        },

        'deneme_olcum': kart.get('deneme_olcum'),

        'boyut_kullanim_oranlari': kart.get('boyut_kullanim_oranlari') or [],

    }





def _ferhat_is_acik(con, arge_test_id: int) -> tuple[str, dict]:

    kart = get_nx_ar(con, arge_test_id)

    durum = (kart.get('durum') or '').upper()

    if durum not in _FERHAT_DURUMLAR:

        raise NxArError('Bu iş Ferhat operasyonunda değil.', 409, 'DURUM')

    if int(kart.get('saha_testi_gerekli_mi') or 0) != 1:

        raise NxArError('Enjeksiyon denemesi gerekli değil.', 409, 'SAHA')

    return durum, kart





@saha_bp.route('/numune-talep')

@ferhat_islem_gerekli

def numune_talep_sayfa():

    """Ferhat Gelen İşler — enjeksiyon doğrulama wizard."""

    return render_template('saha/numune_talep.html')





@saha_bp.route('/api/kaliplar')

@ferhat_islem_gerekli

def api_kaliplar():

    con = _db()

    try:

        items = _kalip_liste(con)

        return jsonify({'ok': True, 'items': items})

    finally:

        con.close()





@saha_bp.route('/api/gelen-isler')

@ferhat_islem_gerekli

def api_gelen_isler_liste():

    con = _db()

    try:

        data = ferhat_bekleyen_liste(con, limit=100)

        items = [_liste_kart(r) for r in (data.get('items') or [])]

        bekleyen = sum(1 for i in items if i.get('nx_durum') == 'FERHAT_BEKLIYOR')

        devam = sum(1 for i in items if i.get('nx_durum') == 'DENEMEDE')

        return jsonify({

            'ok': True,

            'items': items,

            'kpi': {'bekleyen': bekleyen, 'devam': devam, 'bugun': 0},

        })

    except Exception as e:

        return _err(e)

    finally:

        con.close()





@saha_bp.route('/api/gelen-isler/<int:arge_test_id>')

@ferhat_islem_gerekli

def api_gelen_isler_detay(arge_test_id):

    con = _db()

    try:

        _, kart = _ferhat_is_acik(con, arge_test_id)

        dto = _detay_dto(kart)

        durum = (kart.get('durum') or '').upper()

        dto['durum'] = 'devam' if durum == 'DENEMEDE' else 'bekliyor'

        dto['durumLbl'] = 'Devam Ediyor' if durum == 'DENEMEDE' else 'Bekliyor'

        return jsonify(dto)

    except Exception as e:

        return _err(e)

    finally:

        con.close()





@saha_bp.route('/api/gelen-isler/<int:arge_test_id>/ac', methods=['POST'])

@ferhat_islem_gerekli

def api_gelen_isler_ac(arge_test_id):

    con = _db()

    try:

        out = ferhat_ac(con, arge_test_id, kullanici_id=_uid())

        dto = _detay_dto(out)

        dto['durum'] = 'devam'

        dto['durumLbl'] = 'Devam Ediyor'

        dto['nx_durum'] = out.get('durum')

        return jsonify(dto)

    except Exception as e:

        return _err(e)

    finally:

        con.close()





@saha_bp.route('/api/gelen-isler/<int:arge_test_id>/kalip', methods=['POST'])

@ferhat_islem_gerekli

def api_gelen_isler_kalip(arge_test_id):

    data = request.get_json(silent=True) or {}

    kalip_id = data.get('kalip_id')

    if not kalip_id:

        return jsonify({'ok': False, 'hata': 'kalip_id zorunlu.'}), 400

    con = _db()

    try:

        out = ferhat_kalip_kaydet(con, arge_test_id, int(kalip_id), kullanici_id=_uid())

        dto = _detay_dto(out)

        return jsonify({'ok': True, 'kalip': dto.get('kalip')})

    except Exception as e:

        return _err(e)

    finally:

        con.close()





@saha_bp.route('/api/gelen-isler/<int:arge_test_id>/sonuc', methods=['POST'])

@ferhat_islem_gerekli

def api_gelen_isler_sonuc(arge_test_id):

    data = request.get_json(silent=True) or {}

    con = _db()

    try:

        out = ferhat_sonuc_kaydet(con, arge_test_id, data, kullanici_id=_uid())

        return jsonify({'ok': True, 'durum': out.get('durum'), 'arge_test_id': arge_test_id})

    except Exception as e:

        return _err(e)

    finally:

        con.close()





@saha_bp.route('/api/gelen-isler/<int:arge_test_id>/gorsel', methods=['POST'])

@ferhat_islem_gerekli

def api_gelen_isler_gorsel(arge_test_id):

    f = request.files.get('file') or request.files.get('gorsel')

    if not f:

        return jsonify({'ok': False, 'hata': 'Dosya gerekli.'}), 400

    con = _db()

    try:

        durum, _ = _ferhat_is_acik(con, arge_test_id)

        if durum not in _FERHAT_DURUMLAR:

            return jsonify({'ok': False, 'hata': 'Fotoğraf yüklemesi bu durumda kapalı.'}), 409

        belge_id = belge_yukle(

            'nexgen', 'arge_ferhat', arge_test_id, f,

            belge_tipi='GORSEL', kullanici=_kullanici_ad(),

        )

        return jsonify({'ok': True, 'belge_id': belge_id})

    except ValueError as e:

        return jsonify({'ok': False, 'hata': str(e)}), 400

    except Exception as e:

        return _err(e)

    finally:

        con.close()


