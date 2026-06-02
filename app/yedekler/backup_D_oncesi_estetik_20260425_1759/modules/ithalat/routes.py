# -*- coding: utf-8 -*-
"""
CPS DEV - Ithalat Modulu - Routes
==================================
Blueprint: ithalat_bp

BLOK 4.5: Parti listesi + detay + maliyet/odeme/belge/durum CRUD
BLOK 4.6-MVP: Upload sonrasi parser dispatch
BLOK 4.6-IDEMPOTENT: PI No tabanli idempotency + yeniden isle + insan onayi
BLOK URUN-KARTI: /api/ithalat/urun/kart endpoint'i
"""
import logging
import os
from datetime import date, timedelta
from flask import Blueprint, render_template, request, jsonify, abort, session
from modules.auth import yetki_gerekli, login_gerekli, kullanici_adi
from modules.ithalat import queries as ith
from modules.ithalat import parser as ith_parser
from modules import belge as belge_svc
from config import Config

log = logging.getLogger("cps.ithalat.routes")

ithalat_bp = Blueprint('ithalat', __name__)


# =====================================================================
# YARDIMCILAR
# =====================================================================
def _tarih_filtresi_cevir(tarih_kodu):
    if not tarih_kodu or tarih_kodu == 'tum':
        return None
    bugun = date.today()
    if tarih_kodu == 'son-3-ay':
        return (bugun - timedelta(days=90)).isoformat()
    if tarih_kodu == 'son-6-ay':
        return (bugun - timedelta(days=180)).isoformat()
    if tarih_kodu == 'son-12-ay':
        return (bugun - timedelta(days=365)).isoformat()
    return None


def _json_body():
    try:
        if request.is_json:
            return request.get_json(silent=True) or {}
        return request.form.to_dict() or {}
    except Exception:
        return {}


def _ok(data=None, **kwargs):
    out = {'ok': True}
    if data is not None:
        out.update(data)
    out.update(kwargs)
    return jsonify(out)


def _hata(mesaj, kod=400):
    return jsonify({'ok': False, 'hata': mesaj}), kod


def _flt(val, default=None):
    if val is None or val == '':
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _int(val, default=None):
    if val is None or val == '':
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _parse_cevap_olustur(uygulama_sonuc, parse_sonuc=None):
    if isinstance(uygulama_sonuc, dict):
        durum = uygulama_sonuc.get('parse_durum', 'HATA')
        mesaj = uygulama_sonuc.get('mesaj', '')
        uygulanan = uygulama_sonuc.get('uygulanan', 0)
        atlanan = uygulama_sonuc.get('atlanan', 0)
        hata = uygulama_sonuc.get('hata', 0)
        kalem_idler = uygulama_sonuc.get('kalem_idler', [])
        kaynak_ref = uygulama_sonuc.get('kaynak_belge_ref')
        iptal_sayisi = uygulama_sonuc.get('onceki_kalemler_iptal', 0)
        onay_hazir = uygulama_sonuc.get('onay_hazir', None)
    else:
        durum = 'HATA'
        mesaj = 'Uygulama sonucu okunamadi'
        uygulanan = atlanan = hata = iptal_sayisi = 0
        kalem_idler = []
        kaynak_ref = None
        onay_hazir = None

    kalem_adaylari = []
    guven_skoru = None
    guven_seviyesi = None
    matematik_ok = None
    if parse_sonuc is not None:
        try:
            if hasattr(parse_sonuc, 'kalemler'):
                kalem_adaylari = list(parse_sonuc.kalemler or [])
            if hasattr(parse_sonuc, 'guven_skoru'):
                guven_skoru = parse_sonuc.guven_skoru
            if hasattr(parse_sonuc, 'guven_seviyesi'):
                guven_seviyesi = parse_sonuc.guven_seviyesi
            if hasattr(parse_sonuc, 'matematik_ok'):
                matematik_ok = parse_sonuc.matematik_ok
            # BEKLIYOR_ONAY veya REDDEDILDI veya ONERI_BEKLIYOR durumunda
            # parse.durum'u override et
            if hasattr(parse_sonuc, 'durum'):
                _ps_durum = parse_sonuc.durum
                if _ps_durum in ('BEKLIYOR_ONAY', 'ONERI_BEKLIYOR') and \
                   durum in ('BEKLIYOR_ONAY', 'ONERI_BEKLIYOR'):
                    mesaj = parse_sonuc.mesaj or mesaj
                    kaynak_ref = parse_sonuc.kaynak_ref
                elif _ps_durum == 'META_GUNCELLENDI':
                    # Packing List gibi - basari durumu
                    if durum != 'META_GUNCELLENDI':
                        durum = 'META_GUNCELLENDI'
                    mesaj = parse_sonuc.mesaj or mesaj
                    kaynak_ref = parse_sonuc.kaynak_ref
                elif _ps_durum == 'REDDEDILDI':
                    durum = 'REDDEDILDI'
                    mesaj = parse_sonuc.mesaj or mesaj
        except Exception:
            pass

    cevap = {
        'denendi': True,
        'durum': durum,
        'mesaj': mesaj,
        'uygulanan': uygulanan,
        'atlanan': atlanan,
        'hata': hata,
        'kalem_idler': kalem_idler,
        'kaynak_ref': kaynak_ref,
        'onceki_kalemler_iptal': iptal_sayisi,
        'kalem_adaylari': (
            kalem_adaylari if durum == 'INSAN_ONAYI_BEKLIYOR' else []
        ),
        # YENI: Guven skoru bilgisi
        'guven_skoru':    guven_skoru,
        'guven_seviyesi': guven_seviyesi,
        'matematik_ok':   matematik_ok,
    }

    # BEKLIYOR_ONAY veya ONERI_BEKLIYOR durumunda onay URL'i + hazir flag
    if durum in ('BEKLIYOR_ONAY', 'ONERI_BEKLIYOR'):
        cevap['onay_bekleniyor'] = True
        cevap['onay_hazir'] = bool(onay_hazir) if onay_hazir is not None else True

    # PARSE_JSON_HATA - ozel yonlendirme
    if durum == 'PARSE_JSON_HATA':
        cevap['onay_bekleniyor'] = False
        cevap['onay_hazir'] = False

    return cevap


# =====================================================================
# HTML SAYFALAR
# =====================================================================
@ithalat_bp.route('/ithalat/parti/liste', methods=['GET'])
@yetki_gerekli('ithalat.parti.goruntule')
def parti_liste_sayfa():
    return render_template('ithalat_parti_liste.html')


@ithalat_bp.route('/ithalat/parti/<int:parti_id>', methods=['GET'])
@yetki_gerekli('ithalat.parti.goruntule')
def parti_detay_sayfa(parti_id):
    parti = ith.parti_getir(parti_id)
    if not parti:
        abort(404)
    return render_template(
        'ithalat_parti_detay.html',
        parti_id=parti_id,
        parti_kod=parti['Kod'],
    )


# =====================================================================
# API - LISTE + KPI + LOOKUP
# =====================================================================
@ithalat_bp.route('/api/ithalat/parti/olustur', methods=['POST'])
@yetki_gerekli('ithalat.parti.duzenle')
def api_parti_olustur():
    """
    Yeni ithalat partisi olustur.

    Body (JSON) zorunlu alanlar:
        baslik (str) - 3-200 karakter
        tedarikci_ad (str) - 1-200 karakter (manuel ya da autocomplete)
        para_birimi (str) - USD/EUR/TRY/CNY/GBP
        toplam_cift (int) - 0'dan buyuk

    Opsiyonel:
        tedarikci_kod (str) - autocomplete'dan seciliyse doluyor
        yukleme_tarih (str: YYYY-MM-DD)
        tahmini_varis_tarih (str: YYYY-MM-DD)
        toplam_kg (float)
        aciklama (str)

    Tedarikci ERP'de olmak zorunda degil; manuel metin kabul edilir.
    """
    try:
        data = _json_body() or {}
        kul = kullanici_adi()

        # Zorunlu: baslik
        baslik = (data.get('baslik') or '').strip()
        if not baslik:
            return _hata('Başlık zorunludur', 400)
        if len(baslik) < 3:
            return _hata('Başlık en az 3 karakter olmalı', 400)
        if len(baslik) > 200:
            baslik = baslik[:200]

        # Zorunlu: tedarikci_ad
        tedarikci_ad = (data.get('tedarikci_ad') or '').strip()
        if not tedarikci_ad:
            return _hata('Tedarikçi adı zorunludur', 400)
        if len(tedarikci_ad) > 200:
            tedarikci_ad = tedarikci_ad[:200]

        # Zorunlu: para_birimi
        para_birimi = (data.get('para_birimi') or '').strip().upper()
        if not para_birimi:
            return _hata('Para birimi seçilmeli', 400)
        if para_birimi not in ('USD', 'EUR', 'TRY', 'CNY', 'GBP'):
            return _hata('Geçerli para birimi: USD/EUR/TRY/CNY/GBP', 400)

        # Zorunlu: toplam_cift > 0
        toplam_cift_raw = data.get('toplam_cift')
        try:
            toplam_cift = int(float(toplam_cift_raw)) if toplam_cift_raw not in (None, '') else 0
        except Exception:
            return _hata('Toplam çift sayısal olmalı', 400)
        if toplam_cift <= 0:
            return _hata('Toplam çift 0\'dan büyük olmalı', 400)

        # Opsiyoneller
        def _temiz(k):
            v = data.get(k)
            if v is None: return None
            if isinstance(v, str):
                v = v.strip()
                return v if v else None
            return v

        def _float_opt(k):
            v = _temiz(k)
            if v is None or v == '': return None
            try: return float(v)
            except Exception: return None

        def _tarih_opt(k):
            """Tarih ISO format (YYYY-MM-DD) kontrolu. Hatali format None doner."""
            v = _temiz(k)
            if not v: return None
            # YYYY-MM-DD kontrol
            import re as _re
            if _re.match(r'^\d{4}-\d{2}-\d{2}$', v):
                return v
            return None

        tedarikci_kod = _temiz('tedarikci_kod')
        if tedarikci_kod and len(tedarikci_kod) > 50:
            tedarikci_kod = tedarikci_kod[:50]

        yukleme_tarih = _tarih_opt('yukleme_tarih')
        tahmini_varis_tarih = _tarih_opt('tahmini_varis_tarih')
        toplam_kg = _float_opt('toplam_kg')
        if toplam_kg is not None and toplam_kg < 0:
            return _hata('Toplam kg negatif olamaz', 400)

        aciklama = _temiz('aciklama')
        if aciklama and len(aciklama) > 1000:
            aciklama = aciklama[:1000]

        # Olustur
        parti_id = ith.parti_olustur(
            baslik=baslik,
            olusturan=kul,
            para_birimi=para_birimi,
            tedarikci_kod=tedarikci_kod,
            tedarikci_ad=tedarikci_ad,
            yukleme_tarih=yukleme_tarih,
            tahmini_varis_tarih=tahmini_varis_tarih,
            toplam_cift=toplam_cift,
            toplam_kg=toplam_kg,
            aciklama=aciklama,
        )

        if not parti_id:
            return _hata('Parti oluşturulamadı (iç hata)', 500)

        parti = ith.parti_getir(parti_id)
        return jsonify({
            'ok': True,
            'parti_id': parti_id,
            'parti_kod': parti.get('Kod') if parti else None,
            'mesaj': 'İthalat partisi başarıyla oluşturuldu.',
        })

    except Exception as e:
        log.exception("api_parti_olustur hata: %s", e)
        return _hata(f'Sunucu hatası: {str(e)[:100]}', 500)


@ithalat_bp.route('/api/ithalat/tedarikci/arama', methods=['GET'])
@yetki_gerekli('ithalat.parti.goruntule')
def api_tedarikci_arama():
    """
    Tedarikci autocomplete.

    Query params:
        q (str, zorunlu, min 1 karakter)
        limit (int, default=10, max=50)

    Donus: {"ok": true, "sonuclar": [{"kod":"WUXI","ad":"Wuxi Rubber Co."}, ...]}
    """
    try:
        q_str = (request.args.get('q', '') or '').strip()
        if not q_str:
            return jsonify({'ok': True, 'sonuclar': []})
        limit = _int(request.args.get('limit'), 10) or 10
        sonuclar = ith.tedarikci_arama(q_str, limit=limit)
        return jsonify({'ok': True, 'sonuclar': sonuclar})
    except Exception as e:
        log.exception("api_tedarikci_arama hata: %s", e)
        return jsonify({'ok': False, 'sonuclar': [], 'hata': str(e)[:100]})


@ithalat_bp.route('/api/ithalat/parti/liste', methods=['GET'])
@yetki_gerekli('ithalat.parti.goruntule')
def api_parti_liste():
    try:
        durum = (request.args.get('durum', '') or '').strip() or None
        tedarikci_kod = (request.args.get('tedarikci_kod', '') or '').strip() or None
        tarih_kodu = (request.args.get('tarih', '') or '').strip()
        ara = (request.args.get('ara', '') or '').strip() or None
        tarih_bas = _tarih_filtresi_cevir(tarih_kodu)

        liste = ith.parti_liste(
            durum=durum, tedarikci_kod=tedarikci_kod, ara=ara,
            tarih_bas=tarih_bas, limit=500,
        )
        return jsonify(liste or [])
    except Exception as e:
        log.exception("api_parti_liste hata: %s", e)
        return jsonify([])


@ithalat_bp.route('/api/ithalat/parti/liste/kpi', methods=['GET'])
@yetki_gerekli('ithalat.parti.goruntule')
def api_parti_liste_kpi():
    try:
        return jsonify(ith.parti_liste_kpi())
    except Exception as e:
        log.exception("api_parti_liste_kpi hata: %s", e)
        return jsonify({})


@ithalat_bp.route('/api/lookup/tedarikciler', methods=['GET'])
@login_gerekli
def api_lookup_tedarikciler():
    try:
        return jsonify(ith.tedarikci_lookup())
    except Exception as e:
        log.exception("api_lookup_tedarikciler hata: %s", e)
        return jsonify([])


# =====================================================================
# API - DETAY
# =====================================================================
@ithalat_bp.route('/api/ithalat/parti/<int:parti_id>', methods=['GET'])
@yetki_gerekli('ithalat.parti.goruntule')
def api_parti_detay(parti_id):
    try:
        iptal_dahil = (request.args.get('iptal_dahil', '') or '').strip() in ('1', 'true', 'yes')
        detay = ith.parti_detay(parti_id, iptal_dahil=iptal_dahil)
        if not detay:
            return _hata('Parti bulunamadi', 404)
        return jsonify(detay)
    except Exception as e:
        log.exception("api_parti_detay hata: %s", e)
        return _hata('Detay yuklenemedi', 500)


@ithalat_bp.route('/api/ithalat/parti/<int:parti_id>/guncelle', methods=['POST'])
@yetki_gerekli('ithalat.parti.duzenle')
def api_parti_guncelle(parti_id):
    try:
        data = _json_body()
        kul = kullanici_adi()

        alanlar = {}
        IZINLI_STR = ['baslik', 'tedarikci_kod', 'tedarikci_ad', 'aciklama']
        IZINLI_INT = ['tedarikci_id', 'siparis_id', 'toplam_cift']
        IZINLI_FLOAT = ['toplam_kg']
        IZINLI_DATE = ['yukleme_tarih', 'tahmini_varis_tarih',
                       'gerceklesen_varis_tarih']

        for key in IZINLI_STR:
            if key in data:
                alanlar[key] = (data[key] or '').strip() or None
        for key in IZINLI_INT:
            if key in data:
                alanlar[key] = _int(data[key])
        for key in IZINLI_FLOAT:
            if key in data:
                alanlar[key] = _flt(data[key])
        for key in IZINLI_DATE:
            if key in data:
                alanlar[key] = (data[key] or '').strip()[:10] or None

        ok = ith.parti_guncelle(parti_id, kul, **alanlar)
        if not ok:
            return _hata('Guncelleme basarisiz', 500)
        return _ok()
    except Exception as e:
        log.exception("api_parti_guncelle hata: %s", e)
        return _hata('Istek islenemedi', 500)


@ithalat_bp.route('/api/ithalat/parti/<int:parti_id>/durum', methods=['POST'])
@yetki_gerekli('ithalat.parti.duzenle')
def api_parti_durum(parti_id):
    try:
        data = _json_body()
        yeni_durum = (data.get('durum', '') or '').strip().upper()
        not_metni = (data.get('not', '') or '').strip() or None
        kul = kullanici_adi()

        if not yeni_durum:
            return _hata('Durum zorunlu')

        ok = ith.parti_durum_degistir(parti_id, yeni_durum, kul, not_metni=not_metni)
        if not ok:
            return _hata('Durum degistirilemedi', 400)
        return _ok()
    except Exception as e:
        log.exception("api_parti_durum hata: %s", e)
        return _hata('Istek islenemedi', 500)


# =====================================================================
# API - MALIYET
# =====================================================================
@ithalat_bp.route('/api/ithalat/maliyet/ekle', methods=['POST'])
@yetki_gerekli('ithalat.maliyet.duzenle')
def api_maliyet_ekle():
    try:
        data = _json_body()
        kul = kullanici_adi()

        parti_id = _int(data.get('parti_id'))
        tip = (data.get('tip', '') or '').strip().upper()
        tutar = _flt(data.get('tutar'))
        para = (data.get('para_birimi', '') or '').strip().upper() or 'USD'
        kaynak = (data.get('kaynak', '') or '').strip().upper()

        if not parti_id or not tip or tutar is None or not kaynak:
            return _hata('parti_id, tip, tutar, kaynak zorunlu')

        kalem_id = ith.maliyet_kalem_ekle(
            parti_id=parti_id, tip=tip, tutar=tutar,
            para_birimi=para, kaynak=kaynak, kullanici=kul,
            aciklama=(data.get('aciklama') or '').strip() or None,
            alt_kod=(data.get('alt_kod') or '').strip() or None,
            manuel_kur=_flt(data.get('manuel_kur')),
            fatura_no=(data.get('fatura_no') or '').strip() or None,
            fatura_tarih=(data.get('fatura_tarih') or '').strip()[:10] or None,
            cari_kod=(data.get('cari_kod') or '').strip() or None,
            cari_ad=(data.get('cari_ad') or '').strip() or None,
            odeme_plan_id=_int(data.get('odeme_plan_id')),
            not_metni=(data.get('not_metni') or '').strip() or None,
        )
        if not kalem_id:
            return _hata('Kalem eklenemedi', 500)
        return _ok(id=kalem_id)
    except Exception as e:
        log.exception("api_maliyet_ekle hata: %s", e)
        return _hata('Istek islenemedi', 500)


@ithalat_bp.route('/api/ithalat/maliyet/<int:kalem_id>/guncelle', methods=['POST'])
@yetki_gerekli('ithalat.maliyet.duzenle')
def api_maliyet_guncelle(kalem_id):
    try:
        data = _json_body()
        kul = kullanici_adi()
        alanlar = {}
        for key in ['tip', 'alt_kod', 'aciklama', 'kaynak',
                    'para_birimi', 'fatura_no', 'fatura_tarih',
                    'cari_kod', 'cari_ad', 'not_metni']:
            if key in data:
                v = (data[key] or '').strip()
                if key in ('tip', 'kaynak', 'para_birimi'):
                    v = v.upper()
                if key == 'fatura_tarih':
                    v = v[:10]
                alanlar[key] = v or None
        for key in ['tutar', 'manuel_kur']:
            if key in data:
                alanlar[key] = _flt(data[key])
        for key in ['cari_id', 'odeme_plan_id']:
            if key in data:
                alanlar[key] = _int(data[key])

        ok = ith.maliyet_kalem_guncelle(kalem_id, kul, **alanlar)
        if not ok:
            return _hata('Guncelleme basarisiz', 400)
        return _ok()
    except Exception as e:
        log.exception("api_maliyet_guncelle hata: %s", e)
        return _hata('Istek islenemedi', 500)


@ithalat_bp.route('/api/ithalat/maliyet/<int:kalem_id>/sil', methods=['POST'])
@yetki_gerekli('ithalat.maliyet.duzenle')
def api_maliyet_sil(kalem_id):
    try:
        kul = kullanici_adi()
        ok = ith.maliyet_kalem_sil(kalem_id, kul)
        if not ok:
            return _hata('Silinemedi', 400)
        return _ok()
    except Exception as e:
        log.exception("api_maliyet_sil hata: %s", e)
        return _hata('Istek islenemedi', 500)


# =====================================================================
# API - ODEME PLAN
# =====================================================================
@ithalat_bp.route('/api/ithalat/odeme-plan/ekle', methods=['POST'])
@yetki_gerekli('ithalat.odeme.duzenle')
def api_odeme_plan_ekle():
    try:
        data = _json_body()
        kul = kullanici_adi()

        parti_id = _int(data.get('parti_id'))
        tarih = (data.get('planlanan_tarih', '') or '').strip()[:10]
        tutar = _flt(data.get('tutar'))
        para = (data.get('para_birimi', '') or '').strip().upper() or 'USD'

        if not parti_id or not tarih or tutar is None:
            return _hata('parti_id, planlanan_tarih, tutar zorunlu')

        plan_id = ith.odeme_plan_ekle(
            parti_id=parti_id, planlanan_tarih=tarih, tutar=tutar,
            para_birimi=para, kullanici=kul,
            sira=_int(data.get('sira')),
            aciklama=(data.get('aciklama') or '').strip() or None,
            odeme_tipi=(data.get('odeme_tipi') or '').strip().upper() or None,
            cari_kod=(data.get('cari_kod') or '').strip() or None,
            cari_ad=(data.get('cari_ad') or '').strip() or None,
            not_metni=(data.get('not_metni') or '').strip() or None,
        )
        if not plan_id:
            return _hata('Plan eklenemedi', 500)
        return _ok(id=plan_id)
    except Exception as e:
        log.exception("api_odeme_plan_ekle hata: %s", e)
        return _hata('Istek islenemedi', 500)


@ithalat_bp.route('/api/ithalat/odeme-plan/<int:plan_id>/guncelle', methods=['POST'])
@yetki_gerekli('ithalat.odeme.duzenle')
def api_odeme_plan_guncelle(plan_id):
    try:
        data = _json_body()
        kul = kullanici_adi()
        alanlar = {}
        for key in ['aciklama', 'planlanan_tarih', 'para_birimi',
                    'odeme_tipi', 'cari_kod', 'cari_ad', 'not_metni']:
            if key in data:
                v = (data[key] or '').strip()
                if key == 'para_birimi' or key == 'odeme_tipi':
                    v = v.upper()
                if key == 'planlanan_tarih':
                    v = v[:10]
                alanlar[key] = v or None
        for key in ['tutar']:
            if key in data:
                alanlar[key] = _flt(data[key])
        for key in ['cari_id', 'sira']:
            if key in data:
                alanlar[key] = _int(data[key])

        ok = ith.odeme_plan_guncelle(plan_id, kul, **alanlar)
        if not ok:
            return _hata('Guncelleme basarisiz', 400)
        return _ok()
    except Exception as e:
        log.exception("api_odeme_plan_guncelle hata: %s", e)
        return _hata('Istek islenemedi', 500)


@ithalat_bp.route('/api/ithalat/odeme-plan/<int:plan_id>/iptal', methods=['POST'])
@yetki_gerekli('ithalat.odeme.duzenle')
def api_odeme_plan_iptal(plan_id):
    try:
        data = _json_body()
        kul = kullanici_adi()
        sebep = (data.get('sebep') or '').strip() or None
        ok = ith.odeme_plan_iptal(plan_id, kul, sebep=sebep)
        if not ok:
            return _hata('Iptal edilemedi (hareket var olabilir)', 400)
        return _ok()
    except Exception as e:
        log.exception("api_odeme_plan_iptal hata: %s", e)
        return _hata('Istek islenemedi', 500)


# =====================================================================
# API - ODEME HAREKET
# =====================================================================
@ithalat_bp.route('/api/ithalat/hareket/ekle', methods=['POST'])
@yetki_gerekli('ithalat.odeme.duzenle')
def api_hareket_ekle():
    try:
        data = _json_body()
        kul = kullanici_adi()

        parti_id = _int(data.get('parti_id'))
        tarih = (data.get('tarih', '') or '').strip()[:10]
        tutar = _flt(data.get('tutar'))
        para = (data.get('para_birimi', '') or '').strip().upper() or 'USD'

        if not parti_id or not tarih or tutar is None:
            return _hata('parti_id, tarih, tutar zorunlu')

        hareket_id = ith.odeme_hareket_ekle(
            parti_id=parti_id, tarih=tarih, tutar=tutar, para_birimi=para,
            kullanici=kul,
            odeme_plan_id=_int(data.get('odeme_plan_id')),
            odeme_yontemi=(data.get('odeme_yontemi') or '').strip().upper() or None,
            banka_ref=(data.get('banka_ref') or '').strip() or None,
            cari_kod=(data.get('cari_kod') or '').strip() or None,
            cari_ad=(data.get('cari_ad') or '').strip() or None,
            manuel_kur=_flt(data.get('manuel_kur')),
            not_metni=(data.get('not_metni') or '').strip() or None,
        )
        if not hareket_id:
            return _hata('Hareket eklenemedi', 500)
        return _ok(id=hareket_id)
    except Exception as e:
        log.exception("api_hareket_ekle hata: %s", e)
        return _hata('Istek islenemedi', 500)


@ithalat_bp.route('/api/ithalat/hareket/<int:hareket_id>/iptal', methods=['POST'])
@yetki_gerekli('ithalat.odeme.duzenle')
def api_hareket_iptal(hareket_id):
    try:
        data = _json_body()
        kul = kullanici_adi()
        sebep = (data.get('sebep') or '').strip() or None
        ok = ith.odeme_hareket_iptal(hareket_id, kul, sebep=sebep)
        if not ok:
            return _hata('Iptal edilemedi', 400)
        return _ok()
    except Exception as e:
        log.exception("api_hareket_iptal hata: %s", e)
        return _hata('Istek islenemedi', 500)


# =====================================================================
# API - BELGELER + PARSER
# =====================================================================
@ithalat_bp.route('/api/ithalat/parti/<int:parti_id>/belgeler', methods=['GET'])
@yetki_gerekli('ithalat.parti.goruntule')
def api_parti_belgeler(parti_id):
    try:
        belge_tipi = (request.args.get('tip', '') or '').strip() or None
        liste = belge_svc.belge_liste(
            modul='ithalat', alt_modul='parti',
            kayit_id=parti_id, belge_tipi=belge_tipi,
        )
        for b in (liste or []):
            b['belge_tipi_ad'] = belge_svc.belge_tipi_adi(b.get('BelgeTipi'))
            parse_kayit = ith.belge_parse_durum_getir(b.get('Id'))
            if parse_kayit:
                pd = parse_kayit.get('ParseDurum')
                b['parse_durum']        = pd
                b['parse_mesaj']        = parse_kayit.get('ParseMesaj')
                b['parse_kaynak_ref']   = parse_kayit.get('KaynakBelgeRef')
                b['parse_kalem_sayisi'] = parse_kayit.get('UygulananKalemSayisi')
                b['parse_tarih']        = parse_kayit.get('ParseTarih')

                # YENI: UYGULANDI rozeti sadece GERCEKTEN aktif kalem varsa
                # META_GUNCELLENDI durumu zaten "kalem uretmez" davranisinda
                # dogru durumdur - UYGULANDI_BOS'a cevirme.
                if pd in ('UYGULANDI', 'OK', 'YENIDEN_ISLENDI'):
                    aktif_adet = ith.aktif_maliyet_kalem_belge_id_kontrol(b.get('Id'))
                    if aktif_adet == 0:
                        b['parse_durum'] = 'UYGULANDI_BOS'
                        b['parse_kalem_sayisi'] = 0
            else:
                b['parse_durum']        = None
        return jsonify(liste or [])
    except Exception as e:
        log.exception("api_parti_belgeler hata: %s", e)
        return jsonify([])


def _parser_calistir_ve_uygula(belge_id, parti_id, kullanici,
                                yeniden_isle=False,
                                kaynak_ref_override=None):
    belge_row = belge_svc.belge_tek(belge_id)
    if not belge_row:
        return None, {
            'uygulanan': 0, 'atlanan': 0, 'hata': 0,
            'parse_durum': 'HATA',
            'kaynak_belge_ref': None,
            'onceki_kalemler_iptal': 0,
            'kalem_idler': [],
            'mesaj': 'Belge kaydi bulunamadi',
        }

    belge_tipi = (belge_row.get('BelgeTipi') or '').upper()
    if not ith_parser.parser_var_mi(belge_tipi):
        ith.belge_parse_durum_ekle_veya_guncelle(
            belge_id=belge_id, parti_id=parti_id,
            belge_tipi=belge_tipi,
            parse_durum=ith.PARSE_DESTEKLENMIYOR,
            parse_mesaj=f"'{belge_tipi}' tipi icin parser tanimli degil",
            parseden=kullanici,
        )
        return None, {
            'uygulanan': 0, 'atlanan': 0, 'hata': 0,
            'parse_durum': ith.PARSE_DESTEKLENMIYOR,
            'kaynak_belge_ref': None,
            'onceki_kalemler_iptal': 0,
            'kalem_idler': [],
            'mesaj': 'Bu tip icin otomatik okuma yok',
        }

    tam_yol = belge_svc.belge_tam_yol(belge_row)
    dosya_hash = ith.dosya_hash_hesapla(tam_yol)

    parse_sonuc = ith_parser.parser_calistir(belge_row, tam_yol)

    if parse_sonuc and not getattr(parse_sonuc, 'dosya_hash', None):
        try:
            parse_sonuc.dosya_hash = dosya_hash
        except Exception:
            pass

    # YENI: META_GUNCELLENDI (Packing List gibi) - otomatik parti guncelle,
    # onay istemeden basari sayilir. Maliyet kalemi URETMEZ.
    if parse_sonuc and getattr(parse_sonuc, 'durum', '') == 'META_GUNCELLENDI':
        parti_bilgi = getattr(parse_sonuc, 'parti_bilgi', {}) or {}
        guncellemeler = {}
        atlamalar = []

        try:
            parti = ith.parti_getir(parti_id)
            if parti:
                # Toplam Cift - sadece parti'de bos ise doldur
                yeni_cift = parti_bilgi.get('toplam_cift')
                if yeni_cift and yeni_cift > 0:
                    if not parti.get('ToplamCift') or parti.get('ToplamCift') == 0:
                        guncellemeler['toplam_cift'] = int(yeni_cift)
                    else:
                        atlamalar.append(
                            f"Toplam cift zaten dolu ({parti.get('ToplamCift')})")

                # Toplam Kg
                yeni_kg = parti_bilgi.get('toplam_kg')
                if yeni_kg and yeni_kg > 0:
                    if not parti.get('ToplamKg') or parti.get('ToplamKg') == 0:
                        guncellemeler['toplam_kg'] = float(yeni_kg)
                    else:
                        atlamalar.append(
                            f"Toplam kg zaten dolu ({parti.get('ToplamKg')})")

                # Aciklama eki
                yeni_aciklama_ek = parti_bilgi.get('aciklama_ekle')
                if yeni_aciklama_ek:
                    mevcut_aciklama = parti.get('Aciklama') or ''
                    if yeni_aciklama_ek not in mevcut_aciklama:
                        yeni = mevcut_aciklama + ('\n' if mevcut_aciklama else '') + yeni_aciklama_ek
                        guncellemeler['aciklama'] = yeni[:2000]

                if guncellemeler:
                    ith.parti_guncelle(parti_id, kullanici, **guncellemeler)
                    log.info("META_GUNCELLENDI: parti=%s guncellemeler=%s",
                             parti_id, list(guncellemeler.keys()))

            # belge_parse'e META_GUNCELLENDI yaz
            mesaj_ek = parse_sonuc.mesaj
            if guncellemeler:
                mesaj_ek += f" | Guncellendi: {', '.join(guncellemeler.keys())}"
            if atlamalar:
                mesaj_ek += f" | Atlanan: {len(atlamalar)}"

            ith.belge_parse_durum_ekle_veya_guncelle(
                belge_id=belge_id, parti_id=parti_id,
                belge_tipi=belge_tipi,
                parse_durum='META_GUNCELLENDI',
                parse_mesaj=mesaj_ek,
                kaynak_ref=parse_sonuc.kaynak_ref,
                parseden=kullanici,
            )
        except Exception as _e:
            log.exception("META_GUNCELLENDI akisi hata: %s", _e)

        return parse_sonuc, {
            'uygulanan': 0, 'atlanan': 0, 'hata': 0,
            'parse_durum':     'META_GUNCELLENDI',
            'kaynak_belge_ref': parse_sonuc.kaynak_ref,
            'onceki_kalemler_iptal': 0,
            'kalem_idler':     [],
            'mesaj':           (
                parse_sonuc.mesaj
                + (f" ({len(guncellemeler)} alan guncellendi)" if guncellemeler else '')
            ),
            'parti_guncellemeleri': guncellemeler,
            'atlamalar':      atlamalar,
        }

    # YENI: BEKLIYOR_ONAY veya ONERI_BEKLIYOR ise ONCE preview JSON kaydet,
    # SONRA DB guncelle. JSON yazilmadi ise DB'ye de o durum YAZILMAZ.
    # ONERI_BEKLIYOR: Beyanname, Maliyet PDF gibi kullanici secimli akis.
    # BEKLIYOR_ONAY: Proforma/CI gibi guven skorlu akis.
    _oneri_durumlari = ('BEKLIYOR_ONAY', 'ONERI_BEKLIYOR')
    if parse_sonuc and getattr(parse_sonuc, 'durum', '') in _oneri_durumlari:
        akis_durum = parse_sonuc.durum
        preview_yol = None

        # 1. ADIM: Once JSON yazmayi dene
        try:
            ek_bilgi = {
                'dosya_adi':   belge_row.get('OrijinalAd'),
                'belge_tipi':  belge_tipi,
                'dosya_hash':  dosya_hash,
            }
            preview_yol = ith.parse_onay_kaydet(
                belge_id=belge_id, parti_id=parti_id,
                parse_sonuc_dict=parse_sonuc.to_dict(),
                ek_bilgi=ek_bilgi,
            )
        except Exception as _e:
            log.exception("preview JSON kaydetme hatasi (belge_id=%s): %s",
                          belge_id, _e)
            preview_yol = None

        # 2. ADIM: JSON dosyasinin GERCEKTEN yazildigini dogrula
        json_gercekten_var = False
        if preview_yol:
            try:
                import os as _os
                json_gercekten_var = _os.path.isfile(preview_yol)
                if json_gercekten_var:
                    boyut = _os.path.getsize(preview_yol)
                    if boyut < 10:
                        json_gercekten_var = False
                        log.error("Preview JSON cok kucuk (%d byte): %s",
                                  boyut, preview_yol)
            except Exception as _e:
                log.exception("JSON dogrulama hatasi: %s", _e)
                json_gercekten_var = False

        # 3. ADIM: JSON basarili ise durum, degilse PARSE_JSON_HATA
        if json_gercekten_var:
            log.info("PREVIEW KAYDEDILDI: belge_id=%s durum=%s yol=%s",
                     belge_id, akis_durum, preview_yol)
            try:
                ith.belge_parse_durum_ekle_veya_guncelle(
                    belge_id=belge_id, parti_id=parti_id,
                    belge_tipi=belge_tipi,
                    parse_durum=akis_durum,
                    parse_mesaj=parse_sonuc.mesaj,
                    kaynak_ref=parse_sonuc.kaynak_ref,
                    parseden=kullanici,
                )
            except Exception as _e:
                log.exception("belge_parse guncelleme hatasi: %s", _e)

            return parse_sonuc, {
                'uygulanan': 0, 'atlanan': 0, 'hata': 0,
                'parse_durum':     akis_durum,
                'kaynak_belge_ref': parse_sonuc.kaynak_ref,
                'onceki_kalemler_iptal': 0,
                'kalem_idler':     [],
                'mesaj':           parse_sonuc.mesaj,
                'preview_yol':     preview_yol,
                'onay_hazir':      True,
            }

        # ---- JSON YAZILAMADI - PARSE_JSON_HATA ----
        log.error("PREVIEW JSON YAZILAMADI: belge_id=%s", belge_id)
        try:
            ith.belge_parse_durum_ekle_veya_guncelle(
                belge_id=belge_id, parti_id=parti_id,
                belge_tipi=belge_tipi,
                parse_durum='PARSE_JSON_HATA',
                parse_mesaj=(
                    'Parse basarili oldu ama onizleme dosyasi diske '
                    'yazilamadi. Belgeyi tekrar yukleyin.'
                ),
                kaynak_ref=parse_sonuc.kaynak_ref,
                parseden=kullanici,
            )
        except Exception as _e:
            log.exception("belge_parse PARSE_JSON_HATA yazimi: %s", _e)

        return parse_sonuc, {
            'uygulanan': 0, 'atlanan': 0, 'hata': 1,
            'parse_durum':     'PARSE_JSON_HATA',
            'kaynak_belge_ref': parse_sonuc.kaynak_ref,
            'onceki_kalemler_iptal': 0,
            'kalem_idler':     [],
            'mesaj':           (
                'Önizleme verisi eksik — belge kaydedildi ama onay dosyası '
                'yazılamadı. Lütfen belgeyi tekrar yükleyin.'
            ),
            'preview_yol':     None,
            'onay_hazir':      False,
        }

    # REDDEDILDI ise belge_parse'a kaydet ve cik
    if parse_sonuc and getattr(parse_sonuc, 'durum', '') == 'REDDEDILDI':
        try:
            ith.belge_parse_durum_ekle_veya_guncelle(
                belge_id=belge_id, parti_id=parti_id,
                belge_tipi=belge_tipi,
                parse_durum='REDDEDILDI',
                parse_mesaj=parse_sonuc.mesaj,
                parseden=kullanici,
            )
        except Exception:
            pass
        return parse_sonuc, {
            'uygulanan': 0, 'atlanan': 0, 'hata': 0,
            'parse_durum': 'REDDEDILDI',
            'kaynak_belge_ref': None,
            'onceki_kalemler_iptal': 0,
            'kalem_idler': [],
            'mesaj': parse_sonuc.mesaj,
        }

    uygulama = ith.parse_sonuc_uygula(
        parti_id=parti_id,
        belge_id=belge_id,
        parse_sonuc=parse_sonuc,
        kullanici=kullanici,
        kaynak_belge_ref_override=kaynak_ref_override,
        yeniden_isle=yeniden_isle,
    )
    return parse_sonuc, uygulama


@ithalat_bp.route('/api/ithalat/parti/<int:parti_id>/belge/yukle', methods=['POST'])
@yetki_gerekli('ithalat.parti.duzenle')
def api_parti_belge_yukle(parti_id):
    try:
        kul = kullanici_adi()

        parti = ith.parti_getir(parti_id)
        if not parti:
            return _hata('Parti bulunamadi', 404)

        dosya = request.files.get('dosya')
        if not dosya:
            return _hata('Dosya secilmedi')

        belge_tipi = (request.form.get('belge_tipi', '') or '').strip().upper() or 'DIGER'
        aciklama = (request.form.get('aciklama', '') or '').strip() or None

        belge_id = belge_svc.belge_yukle(
            modul='ithalat', alt_modul='parti',
            kayit_id=parti_id, dosya_storage=dosya,
            belge_tipi=belge_tipi, aciklama=aciklama,
            kullanici=kul,
        )

        parse_sonuc, uygulama = _parser_calistir_ve_uygula(
            belge_id=belge_id, parti_id=parti_id, kullanici=kul,
            yeniden_isle=False, kaynak_ref_override=None,
        )

        parse_cevap = _parse_cevap_olustur(uygulama, parse_sonuc)

        return _ok(id=belge_id, parse=parse_cevap)

    except ValueError as e:
        return _hata(str(e), 400)
    except Exception as e:
        log.exception("api_parti_belge_yukle hata: %s", e)
        return _hata('Yukleme basarisiz', 500)


@ithalat_bp.route('/api/ithalat/belge/<int:belge_id>/yeniden-isle', methods=['POST'])
@yetki_gerekli('ithalat.maliyet.duzenle')
def api_belge_yeniden_isle(belge_id):
    try:
        kul = kullanici_adi()

        belge_row = belge_svc.belge_tek(belge_id)
        if not belge_row:
            return _hata('Belge bulunamadi', 404)

        parti_id = _int(belge_row.get('KayitId'))
        if not parti_id:
            return _hata('Belge bir partiye bagli degil', 400)

        parse_sonuc, uygulama = _parser_calistir_ve_uygula(
            belge_id=belge_id, parti_id=parti_id, kullanici=kul,
            yeniden_isle=True, kaynak_ref_override=None,
        )

        parse_cevap = _parse_cevap_olustur(uygulama, parse_sonuc)

        return _ok(id=belge_id, parse=parse_cevap)

    except Exception as e:
        log.exception("api_belge_yeniden_isle hata: %s", e)
        return _hata('Yeniden isleme basarisiz', 500)


@ithalat_bp.route('/api/ithalat/belge/<int:belge_id>/insan-onayi-uygula', methods=['POST'])
@yetki_gerekli('ithalat.maliyet.duzenle')
def api_belge_insan_onayi_uygula(belge_id):
    try:
        kul = kullanici_adi()
        data = _json_body()
        kaynak_ref = (data.get('kaynak_ref') or '').strip()[:100]

        if not kaynak_ref:
            return _hata('kaynak_ref (PI No vb.) zorunlu')

        belge_row = belge_svc.belge_tek(belge_id)
        if not belge_row:
            return _hata('Belge bulunamadi', 404)

        parti_id = _int(belge_row.get('KayitId'))
        if not parti_id:
            return _hata('Belge bir partiye bagli degil', 400)

        onceki = ith.belge_parse_ref_kontrol(parti_id, kaynak_ref)
        if onceki:
            return _hata(
                f"Bu ref ({kaynak_ref}) zaten islenmis "
                f"(belge #{onceki.get('BelgeId')}, "
                f"{(onceki.get('ParseTarih') or '')[:16]}). "
                f"Yeniden islemek icin yeni belge yukleyin veya "
                f"'Yeniden Isle' kullanin.",
                400,
            )

        parse_sonuc, uygulama = _parser_calistir_ve_uygula(
            belge_id=belge_id, parti_id=parti_id, kullanici=kul,
            yeniden_isle=False, kaynak_ref_override=kaynak_ref,
        )

        parse_cevap = _parse_cevap_olustur(uygulama, parse_sonuc)
        return _ok(id=belge_id, parse=parse_cevap)

    except Exception as e:
        log.exception("api_belge_insan_onayi_uygula hata: %s", e)
        return _hata('Uygulama basarisiz', 500)


@ithalat_bp.route('/api/ithalat/belge/<int:belge_id>/parse-durum', methods=['GET'])
@yetki_gerekli('ithalat.parti.goruntule')
def api_belge_parse_durum(belge_id):
    try:
        kayit = ith.belge_parse_durum_getir(belge_id)
        return jsonify(kayit or {})
    except Exception as e:
        log.exception("api_belge_parse_durum hata: %s", e)
        return jsonify({})


# =====================================================================
# YENI: API - URUN KARTI
# =====================================================================
@ithalat_bp.route('/api/ithalat/urun/kart', methods=['GET'])
@yetki_gerekli('ithalat.parti.goruntule')
def api_urun_kart():
    """
    Urun bazli gecmis maliyet karti + kiyaslama.

    Query params:
        arama (str, zorunlu): Aranacak urun kodu/GTIP/terim
        son_limit (int, opsiyonel, default=3): Gosterim icin son N parti
        bu_parti_id (int, opsiyonel): Kiyaslama icin 'bu parti' referansi.
            Verilirse response'taki 'kiyas' alani bu parti ile digerlerinin
            ortalamasi arasindaki sapmayi verir.

    Donus: dict - urun_kart_getir() ciktisi
    """
    try:
        arama = (request.args.get('arama', '') or '').strip()
        if not arama:
            return jsonify({
                'arama': '',
                'bulundu': False,
                'strateji': None,
                'toplam_alim': 0,
                'son_alim_tarihi': None,
                'bu_parti_id': None,
                'mesaj': 'Arama terimi bos (query param: arama)',
                'partiler': [],
                'ortalama': None,
                'kiyas': None,
                'tedarikci_kirilim': [],
                'tasima_kirilim': [],
            })

        son_limit = _int(request.args.get('son_limit'), 3) or 3
        if son_limit < 1: son_limit = 1
        if son_limit > 20: son_limit = 20

        # Opsiyonel: kiyaslama icin 'bu parti' ID'si
        bu_parti_id = _int(request.args.get('bu_parti_id'), None)

        sonuc = ith.urun_kart_getir(
            arama,
            son_gosterim_limit=son_limit,
            bu_parti_id=bu_parti_id,
        )
        return jsonify(sonuc)

    except Exception as e:
        log.exception("api_urun_kart hata: %s", e)
        return jsonify({
            'arama': request.args.get('arama', '') or '',
            'bulundu': False,
            'strateji': None,
            'toplam_alim': 0,
            'son_alim_tarihi': None,
            'bu_parti_id': None,
            'mesaj': f'Hata: {str(e)[:100]}',
            'partiler': [],
            'ortalama': None,
            'kiyas': None,
            'tedarikci_kirilim': [],
            'tasima_kirilim': [],
        })


# =====================================================================
# PARSE ONAY ENDPOINT'LERI (guven skoru sistemi, Faz 1+2)
# =====================================================================

@ithalat_bp.route('/api/ithalat/belge/<int:belge_id>/parse-onay', methods=['GET'])
@yetki_gerekli('ithalat.parti.goruntule')
def api_parse_onay_getir(belge_id):
    """
    Preview icin saklanan parse verisini getir.
    UI parse onay modalinda bu response'u kullanir.

    JSON yoksa teknik debug bilgisi doner:
      - beklenen_yol
      - klasor_var
      - dosya_var
      - parse_durum (belge_parse tablosu)
    """
    try:
        belge_row = belge_svc.belge_tek(belge_id)
        if not belge_row:
            return jsonify({
                'ok': False,
                'hata': 'Belge kaydi bulunamadi',
                'belge_id': belge_id,
            }), 404

        parti_id = _int(belge_row.get('KayitId'))

        onay = ith.parse_onay_getir(belge_id)
        if not onay:
            # Teknik debug bilgisi topla
            debug = ith.parse_onay_debug(belge_id)

            parse_kayit = ith.belge_parse_durum_getir(belge_id)
            parse_durum = parse_kayit.get('ParseDurum') if parse_kayit else None
            parse_mesaj = parse_kayit.get('ParseMesaj') if parse_kayit else None

            log.warning(
                "PREVIEW BULUNAMADI: belge_id=%s, debug=%r, parse_durum=%s",
                belge_id, debug, parse_durum,
            )

            # Kullanici dostu mesaj
            if parse_durum == 'UYGULANDI':
                user_mesaj = 'Bu belge zaten onaylanıp uygulandı. Maliyet sekmesini kontrol edin.'
            elif parse_durum == 'REDDEDILDI':
                user_mesaj = 'Bu belge reddedildi. Maliyet kalemi oluşturulmadı.'
            elif parse_durum == 'PARSE_JSON_HATA':
                user_mesaj = ('Önizleme verisi eksik, belgeyi tekrar yükleyin. '
                              '(Parser başarılı oldu ama önizleme dosyası yazılamadı.)')
            else:
                user_mesaj = ('Önizleme verisi eksik, belgeyi tekrar yükleyin.')

            return jsonify({
                'ok': False,
                'hata': user_mesaj,
                'belge_id': belge_id,
                'parti_id': parti_id,
                'debug': {
                    'beklenen_yol':      debug.get('beklenen_yol'),
                    'klasor':            debug.get('klasor'),
                    'klasor_var':        debug.get('klasor_var'),
                    'dosya_var':         debug.get('dosya_var'),
                    'dosya_boyut':       debug.get('dosya_boyut'),
                    'cwd':               debug.get('cwd'),
                    'parse_durum_db':    parse_durum,
                    'parse_mesaj_db':    parse_mesaj,
                    'belge_orig_ad':     belge_row.get('OrijinalAd'),
                    'belge_disk_yol':    belge_row.get('DiskYol'),
                },
            }), 200

        parse_data = onay.get('parse') or {}
        ek_bilgi = onay.get('ek_bilgi') or {}

        # YENI: Tedarikci gorunen ad (Cince->Latin normalize)
        parti_bilgi = parse_data.get('parti_bilgi') or {}
        ted_ad_orijinal = parti_bilgi.get('tedarikci_ad')
        tedarikci_info = ith.tedarikci_normalize(ted_ad_orijinal) \
            if ted_ad_orijinal else {
                'orijinal_ad': None, 'gorunen_ad': None, 'cari_kod': None,
            }

        return jsonify({
            'ok': True,
            'belge_id':       belge_id,
            'parti_id':       parti_id,
            'dosya_adi':      ek_bilgi.get('dosya_adi') or belge_row.get('OrijinalAd'),
            'belge_tipi':     ek_bilgi.get('belge_tipi') or belge_row.get('BelgeTipi'),
            'olusma_tarih':   onay.get('olusma_tarih'),
            # Parser sonucu
            'guven_skoru':    parse_data.get('guven_skoru'),
            'guven_seviyesi': parse_data.get('guven_seviyesi'),
            'guven_detay':    parse_data.get('guven_detay') or [],
            'matematik_ok':   parse_data.get('matematik_ok'),
            'kaynak_ref':     parse_data.get('kaynak_ref'),
            'tespit_edilen_kolonlar': parse_data.get('tespit_edilen_kolonlar') or {},
            'kalemler':       parse_data.get('kalemler') or [],
            'ekstra_kalemler': parse_data.get('ekstra_kalemler') or [],
            'uyarilar':       parse_data.get('uyarilar') or [],
            'mantiksizlik_uyarilari': parse_data.get('mantiksizlik_uyarilari') or [],
            'parti_bilgi':    parti_bilgi,
            'mesaj':          parse_data.get('mesaj') or '',
            # Duplicate bilgisi
            'is_duplicate':   bool(onay.get('is_duplicate')),
            'existing_ref':   onay.get('existing_ref') or None,
            # Tedarikci 3 parca
            'tedarikci': {
                'orijinal_ad': tedarikci_info.get('orijinal_ad'),
                'gorunen_ad':  tedarikci_info.get('gorunen_ad'),
                'cari_kod':    tedarikci_info.get('cari_kod'),
            },
            # YENI: Oneri akisi (beyanname, maliyet_pdf icin)
            'oneriler':       parse_data.get('oneriler') or [],
            'meta':           parse_data.get('meta') or {},
        })

    except Exception as e:
        log.exception("api_parse_onay_getir hata: %s", e)
        return jsonify({
            'ok': False,
            'hata': f'Sunucu hatasi: {str(e)[:200]}',
            'belge_id': belge_id,
        }), 500


@ithalat_bp.route('/api/ithalat/belge/<int:belge_id>/parse-onay/uygula',
                  methods=['POST'])
@yetki_gerekli('ithalat.maliyet.duzenle')
def api_parse_onay_uygula(belge_id):
    """
    Kullanici preview modal'da "Onayla ve Uygula" basti.

    Body parametreleri (opsiyonel):
        ekstra_kalemler_dahil (bool)
        override_duplicate (bool)
        secilen_oneriler (list): ONERI_BEKLIYOR akisi - sectikleri kalemler
    """
    try:
        kul = kullanici_adi()
        data = _json_body() or {}
        ekstra_dahil = bool(data.get('ekstra_kalemler_dahil', False))
        override_dup = bool(data.get('override_duplicate', False))
        secilen_oneriler = data.get('secilen_oneriler')
        # None veya bos liste -> eski akis; doluysa ONERI akisi
        if secilen_oneriler is not None and not isinstance(secilen_oneriler, list):
            secilen_oneriler = None

        belge_row = belge_svc.belge_tek(belge_id)
        if not belge_row:
            return _hata('Belge bulunamadi', 404)

        parti_id = _int(belge_row.get('KayitId'))
        if not parti_id:
            return _hata('Belge bir partiye bagli degil', 400)

        sonuc = ith.parse_onay_uygula(
            belge_id=belge_id,
            parti_id=parti_id,
            kullanici=kul,
            ekstra_kalemler_dahil=ekstra_dahil,
            override_duplicate=override_dup,
            secilen_oneriler=secilen_oneriler,
        )

        # Duplicate uyarisi - hata degil, 200 doner ama 'duplicate: true' flag'i var
        if sonuc.get('duplicate'):
            return jsonify({
                'ok': False,
                'duplicate': True,
                'duplicate_uyari': sonuc.get('duplicate_uyari'),
                'kaynak_ref': sonuc.get('kaynak_ref'),
                'mesaj': sonuc.get('duplicate_uyari'),
            }), 200  # 200 - UI bunu 'uyari' olarak gosterecek

        if not sonuc.get('ok'):
            return _hata(sonuc.get('hata') or 'Uygulanamadi', 400)

        cevap = {
            'ok': True,
            'belge_id': belge_id,
            'parti_id': parti_id,
            'uygulanan_kalem_sayisi': sonuc.get('uygulanan_kalem_sayisi', 0),
            'mesaj': sonuc.get('mesaj') or 'Kalemler maliyete eklendi',
        }
        # Packing List ozel alanlari
        if sonuc.get('packing_list'):
            cevap['packing_list'] = True
            cevap['parti_guncellemeleri'] = sonuc.get('parti_guncellemeleri') or {}
            cevap['atlamalar'] = sonuc.get('atlamalar') or []

        return jsonify(cevap)

    except Exception as e:
        log.exception("api_parse_onay_uygula hata: %s", e)
        return _hata(f'Sunucu hatasi: {str(e)[:100]}', 500)


@ithalat_bp.route('/api/ithalat/belge/<int:belge_id>/parse-onay/reddet',
                  methods=['POST'])
@yetki_gerekli('ithalat.maliyet.duzenle')
def api_parse_onay_reddet(belge_id):
    """
    Kullanici preview modal'da "Reddet" basti.
    Preview JSON silinir, belge diske kalir.
    """
    try:
        kul = kullanici_adi()
        data = _json_body() or {}
        sebep = (data.get('sebep') or '').strip()[:500] or None

        belge_row = belge_svc.belge_tek(belge_id)
        if not belge_row:
            return _hata('Belge bulunamadi', 404)

        parti_id = _int(belge_row.get('KayitId'))

        sonuc = ith.parse_onay_reddet(
            belge_id=belge_id,
            parti_id=parti_id,
            kullanici=kul,
            sebep=sebep,
        )

        if not sonuc.get('ok'):
            return _hata(sonuc.get('hata') or 'Reddedilemedi', 400)

        return jsonify({
            'ok': True,
            'belge_id': belge_id,
            'mesaj': sonuc.get('mesaj') or 'Reddedildi',
        })

    except Exception as e:
        log.exception("api_parse_onay_reddet hata: %s", e)
        return _hata(f'Sunucu hatasi: {str(e)[:100]}', 500)
