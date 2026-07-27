# -*- coding: utf-8 -*-
"""Finans / Muhasebe Merkezi API route kayıtları."""
from __future__ import annotations

from flask import abort, jsonify, redirect, render_template, request, session
from urllib.parse import unquote

from modules.auth import login_gerekli, kullanici_yetkileri
from modules.nexgen.finans_api_serializer import (
    api_hata,
    api_ok,
    belge_detay_satir,
    belge_liste_satir,
)
from modules.nexgen.cari360_yetki import can_cari360_dosya_ekrani
from modules.nexgen.finans_belgesi_repository import FinansBelgesiError
from modules.nexgen.finans_cari_read_service import FinansCariReadError, cari_hesap_paket
from modules.nexgen.finans_cari_hesap_read_service import (
    FinansCariHesapReadError,
    CARI_TIP_MUSTERI,
    CARI_TIP_TEDARIKCI,
    cari_aylik_durum,
    cari_bilgileri,
    cari_finans_belgeleri,
    cari_fiyatlar,
    cari_genel_durum,
    cari_hareketler,
    cari_hesap_detay,
    cari_hesap_workspace,
    cari_kart_kimlik,
    cari_liste,
    cari_odemeler,
    cari_ozet,
    cari_risk,
    cari_sevkiyatlar,
    cari_siparisler,
    cari_tahsilatlar,
    cari_vadeler,
    cari_yetkililer,
)
from modules.nexgen.finans_cari_demo_context import demo_badge_payload, finans_db_connect
from modules.nexgen.finans_read_service import DEFAULT_PAGE_SIZE, detay_paket, liste_belgeler
from modules.nexgen.finans_yetki import (
    can_finans_approve,
    can_finans_manage,
    can_finans_post,
    can_finans_reject,
    can_finans_review,
    can_finans_view,
    finans_erisim_engelli,
    is_pazarlamaci_finans_kisitli,
)
from modules.nexgen.finance_workflow_service import FinanceWorkflowService
from modules.nexgen.financial_posting_service import FinancialPostingService
from modules.nexgen.finans_cari_kimlik_yetki import (
    can_cari_kimlik_view,
    cari_kimlik_erisim_engelli,
)
from modules.nexgen.mo_tahsilat_config import CARI_ENTEGRASYON_AKTIF

_FINANS_RETURN_DEFAULT = '/nexgen/finans/belgeler'


def _guvenli_finans_return_url(raw: str | None) -> str:
    """Open redirect engeli — yalnız NexGen finans iç route."""
    if not raw:
        return _FINANS_RETURN_DEFAULT
    s = unquote(str(raw).strip())
    if not s.startswith('/nexgen/finans'):
        return _FINANS_RETURN_DEFAULT
    if '://' in s or s.startswith('//'):
        return _FINANS_RETURN_DEFAULT
    if '\n' in s or '\r' in s:
        return _FINANS_RETURN_DEFAULT
    return s


def _finans_return_from_request() -> str:
    """Return param — encode edilmemiş & içeren URL'leri de güvenli okur."""
    qs = request.query_string.decode('utf-8', errors='replace')
    marker = 'return='
    if marker in qs:
        raw = qs.split(marker, 1)[1]
        return _guvenli_finans_return_url(unquote(raw))
    val = request.args.get('return')
    if val:
        return _guvenli_finans_return_url(val)
    return _FINANS_RETURN_DEFAULT


def register_finans_routes(bp, db_fn, kullanici_id_fn):

    def _finans_con():
        return finans_db_connect(db_fn, request)

    def _api_demo_wrap(data: dict, meta: dict):
        badge = demo_badge_payload(meta)
        if badge:
            data = {**data, **badge}
        return jsonify(api_ok(data=data, demo=badge))
    def _u():
        return session.get('kullanici') or {}

    def _yk():
        return kullanici_yetkileri(_u())

    def _finans_erisim():
        u, yk = _u(), _yk()
        if finans_erisim_engelli(u, yk):
            return False
        return can_finans_view(yk)

    def _finans_sayfa_ctx(yk, u):
        return {
            'active': 'nexgen',
            'can_review': can_finans_review(yk) and not is_pazarlamaci_finans_kisitli(yk),
            'can_approve': can_finans_approve(yk) and not is_pazarlamaci_finans_kisitli(yk),
            'can_post': can_finans_post(yk) and not is_pazarlamaci_finans_kisitli(yk),
            'can_manage': can_finans_manage(yk),
            'cari_entegrasyon_aktif': CARI_ENTEGRASYON_AKTIF,
            'can_cari_yonetimi': (
                can_cari_kimlik_view(yk) and not cari_kimlik_erisim_engelli(u, yk)
            ),
            # geriye dönük template alias
            'can_cari_kimlik_koprusu': (
                can_cari_kimlik_view(yk) and not cari_kimlik_erisim_engelli(u, yk)
            ),
        }

    @bp.route('/finans')
    @bp.route('/finans/')
    @login_gerekli
    def finans_merkezi_sayfa():
        u, yk = _u(), _yk()
        if finans_erisim_engelli(u, yk) or not can_finans_view(yk):
            abort(403)
        ctx = _finans_sayfa_ctx(yk, u)
        ctx['fm_tab'] = 'genel'
        return render_template('nexgen/finans_merkezi.html', **ctx)

    @bp.route('/finans/belgeler')
    @login_gerekli
    def finans_belgeleri_sayfa():
        u, yk = _u(), _yk()
        if finans_erisim_engelli(u, yk) or not can_finans_view(yk):
            abort(403)
        ctx = _finans_sayfa_ctx(yk, u)
        ctx['fm_tab'] = 'belgeler'
        return render_template('nexgen/finans_belgeleri.html', **ctx)

    @bp.route('/finans/cari-hesaplar')
    @login_gerekli
    def finans_cari_hesaplar_sayfa():
        u, yk = _u(), _yk()
        if finans_erisim_engelli(u, yk) or not can_finans_view(yk):
            abort(403)
        tip = (request.args.get('tip') or '').strip().upper()
        oid_raw = request.args.get('id')
        if tip in (CARI_TIP_MUSTERI, CARI_TIP_TEDARIKCI) and oid_raw:
            try:
                oid = int(oid_raw)
                sekme = (request.args.get('sekme') or '').strip()
                q = f'?sekme={sekme}' if sekme else ''
                return redirect(f'/nexgen/finans/cari-hesaplar/{tip}/{oid}{q}')
            except (TypeError, ValueError):
                pass
        ctx = _finans_sayfa_ctx(yk, u)
        ctx['fm_tab'] = 'cari_hesaplar'
        _, demo_meta = _finans_con()
        ctx['finans_demo_modu'] = bool(demo_meta.get('demo_modu'))
        return render_template('nexgen/finans_cari_secim.html', **ctx)

    @bp.route('/finans/cari-hesaplar/<tip>/<int:operasyonel_id>')
    @login_gerekli
    def finans_cari_kart_sayfa(tip, operasyonel_id):
        u, yk = _u(), _yk()
        if finans_erisim_engelli(u, yk) or not can_finans_view(yk):
            abort(403)
        t = (tip or '').strip().upper()
        if t not in (CARI_TIP_MUSTERI, CARI_TIP_TEDARIKCI):
            abort(404)
        ctx = _finans_sayfa_ctx(yk, u)
        ctx['fm_tab'] = 'cari_hesaplar'
        ctx['cari_tipi'] = t
        ctx['operasyonel_id'] = int(operasyonel_id)
        ctx['varsayilan_sekme'] = (request.args.get('sekme') or 'hesap_detaylari').strip()
        _, demo_meta = _finans_con()
        ctx['finans_demo_modu'] = bool(demo_meta.get('demo_modu'))
        return render_template('nexgen/finans_cari_kart.html', **ctx)

    @bp.route('/finans/belge/<int:belge_id>')
    @login_gerekli
    def finans_belge_workspace_sayfa(belge_id):
        u, yk = _u(), _yk()
        if finans_erisim_engelli(u, yk) or not can_finans_view(yk):
            abort(403)
        ctx = _finans_sayfa_ctx(yk, u)
        ctx['fm_tab'] = 'belgeler'
        ctx['belge_id'] = belge_id
        ctx['return_url'] = _finans_return_from_request()
        return render_template('nexgen/finans_belge_workspace.html', **ctx)

    def _json_hata(e: FinansBelgesiError):
        return jsonify(api_hata(e.hata_kodu or 'FINANS_HATA', e.mesaj)), int(e.kod or 400)

    def _body():
        return request.get_json(silent=True) or {}

    def _int_arg(args, key: str):
        v = args.get(key)
        if v in (None, ''):
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    @bp.route('/api/finans-belgeleri')
    @login_gerekli
    def api_finans_liste():
        if not _finans_erisim():
            abort(403)
        args = request.args
        con = db_fn()
        try:
            paket = liste_belgeler(
                con,
                belge_tipi=(args.get('belge_tipi') or '').strip() or None,
                durum=(args.get('durum') or '').strip() or None,
                posting_durumu=(args.get('posting_durumu') or '').strip() or None,
                cari_id=_int_arg(args, 'cari_id'),
                siparis_id=_int_arg(args, 'siparis_id'),
                sevkiyat_id=_int_arg(args, 'sevkiyat_id'),
                tahsilat_id=_int_arg(args, 'tahsilat_id'),
                tarih_bas=(args.get('tarih_bas') or args.get('tarih_baslangic') or '').strip() or None,
                tarih_bit=(args.get('tarih_bit') or args.get('tarih_bitis') or '').strip() or None,
                arama=(args.get('arama') or args.get('q') or '').strip() or None,
                page=int(args.get('page') or 1),
                page_size=int(args.get('page_size') or DEFAULT_PAGE_SIZE),
            )
            return jsonify(api_ok(
                liste=[belge_liste_satir(r) for r in paket['liste']],
                sayfalama=paket['sayfalama'],
                ozet=paket.get('ozet') or {},
                cari360_erisim=can_cari360_dosya_ekrani(_yk()),
            ))
        except FinansBelgesiError as e:
            return _json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans-belgesi/<int:belge_id>')
    @login_gerekli
    def api_finans_detay(belge_id):
        if not _finans_erisim():
            abort(403)
        con = db_fn()
        try:
            paket = detay_paket(con, belge_id, _yk(), user_dict=_u())
            return jsonify(api_ok(
                belge=belge_detay_satir(
                    paket['belge'],
                    kaynak_ozet=paket['kaynak_ozet'],
                    siparis_ozet=paket.get('siparis_ozet'),
                    kalemler=paket.get('kalemler'),
                    audit=paket['audit'],
                    durum_gecisleri=paket['durum_gecisleri'],
                    aksiyonlar=paket['aksiyonlar'],
                    posting_onizleme=paket['posting_onizleme'],
                ),
                cari_hesap=paket.get('cari_hesap'),
            ))
        except FinansBelgesiError as e:
            return _json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans-cari/<int:cari_id>/hesap')
    @login_gerekli
    def api_finans_cari_hesap(cari_id):
        if not _finans_erisim():
            abort(403)
        con = db_fn()
        try:
            paket = cari_hesap_paket(con, cari_id, yk=_yk(), user_dict=_u())
            return jsonify(api_ok(cari_hesap=paket))
        except FinansCariReadError as e:
            return jsonify(api_hata(e.hata_kodu or 'CARI_HATA', e.mesaj)), int(e.kod or 404)
        finally:
            con.close()

    def _cari_hesap_json_hata(e: FinansCariHesapReadError):
        return jsonify(api_hata(e.hata_kodu or 'CARI_HESAP_HATA', e.mesaj)), int(e.kod or 400)

    @bp.route('/api/finans/cari-hesaplar')
    @login_gerekli
    def api_finans_cari_hesaplar_liste():
        if not _finans_erisim():
            abort(403)
        args = request.args
        con, demo_meta = _finans_con()
        try:
            paket = cari_liste(
                con,
                cari_tipi=(args.get('tip') or CARI_TIP_MUSTERI).strip().upper(),
                arama=(args.get('arama') or '').strip() or None,
                aktif=(args.get('aktif') or '').strip() or None,
                bakiye_filtre=(args.get('bakiye') or '').strip().upper() or None,
                yalniz_eslesme_eksik=args.get('eslesme_eksik') == '1',
                secim_modu=args.get('admin') != '1',
                limit=int(args.get('limit') or 80),
                offset=int(args.get('offset') or 0),
            )
            badge = demo_badge_payload(demo_meta)
            payload = {'data': paket}
            if badge:
                payload['demo'] = badge
            return jsonify(api_ok(**payload))
        except FinansCariHesapReadError as e:
            return _cari_hesap_json_hata(e)
        finally:
            con.close()

    def _cari_hesap_tip_id(tip: str, operasyonel_id: int):
        t = (tip or '').strip().upper()
        if t not in (CARI_TIP_MUSTERI, CARI_TIP_TEDARIKCI):
            raise FinansCariHesapReadError('Geçersiz cari tipi.', 400, 'CARI_TIP_GECERSIZ')
        return t, int(operasyonel_id)

    @bp.route('/api/finans/cari-hesap/<tip>/<int:operasyonel_id>/ozet')
    @login_gerekli
    def api_finans_cari_hesap_ozet(tip, operasyonel_id):
        if not _finans_erisim():
            abort(403)
        con = db_fn()
        try:
            t, oid = _cari_hesap_tip_id(tip, operasyonel_id)
            paket = cari_ozet(con, t, oid, yk=_yk(), user_dict=_u())
            return jsonify(api_ok(data=paket))
        except (FinansCariHesapReadError, FinansCariReadError) as e:
            if isinstance(e, FinansCariReadError):
                return jsonify(api_hata(e.hata_kodu or 'CARI_HATA', e.mesaj)), int(e.kod or 404)
            return _cari_hesap_json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans/cari-hesap/<tip>/<int:operasyonel_id>/hareketler')
    @login_gerekli
    def api_finans_cari_hesap_hareketler(tip, operasyonel_id):
        if not _finans_erisim():
            abort(403)
        args = request.args
        con = db_fn()
        try:
            t, oid = _cari_hesap_tip_id(tip, operasyonel_id)
            paket = cari_hareketler(
                con, t, oid,
                tarih_bas=(args.get('tarih_bas') or '').strip() or None,
                tarih_bit=(args.get('tarih_bit') or '').strip() or None,
                islem_turu=(args.get('islem_turu') or '').strip() or None,
                belge_no=(args.get('belge_no') or '').strip() or None,
                kaynak=(args.get('kaynak') or 'NEXGEN').strip().upper() or 'NEXGEN',
                limit=int(args.get('limit') or 100),
                offset=int(args.get('offset') or 0),
            )
            return jsonify(api_ok(data=paket))
        except FinansCariHesapReadError as e:
            return _cari_hesap_json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans/cari-hesap/<tip>/<int:operasyonel_id>/belgeler')
    @login_gerekli
    def api_finans_cari_hesap_belgeler(tip, operasyonel_id):
        if not _finans_erisim():
            abort(403)
        args = request.args
        con = db_fn()
        try:
            t, oid = _cari_hesap_tip_id(tip, operasyonel_id)
            paket = cari_finans_belgeleri(
                con, t, oid,
                page=int(args.get('page') or 1),
                page_size=int(args.get('page_size') or 50),
            )
            liste = [belge_liste_satir(r) for r in paket.get('liste') or []]
            return jsonify(api_ok(data={'liste': liste, 'sayfalama': paket.get('sayfalama'), 'uyari': paket.get('uyari')}))
        except FinansCariHesapReadError as e:
            return _cari_hesap_json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans/cari-hesap/<tip>/<int:operasyonel_id>/kart-kimlik')
    @login_gerekli
    def api_finans_cari_kart_kimlik(tip, operasyonel_id):
        if not _finans_erisim():
            abort(403)
        con = db_fn()
        try:
            t, oid = _cari_hesap_tip_id(tip, operasyonel_id)
            return jsonify(api_ok(data=cari_kart_kimlik(con, t, oid)))
        except FinansCariHesapReadError as e:
            return _cari_hesap_json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans/cari-hesap/<tip>/<int:operasyonel_id>/hesap-detay')
    @login_gerekli
    def api_finans_cari_hesap_detay(tip, operasyonel_id):
        if not _finans_erisim():
            abort(403)
        args = request.args
        con, demo_meta = _finans_con()
        try:
            t, oid = _cari_hesap_tip_id(tip, operasyonel_id)
            args = request.args
            paket = cari_hesap_detay(
                con, t, oid,
                kaynak=(args.get('kaynak') or 'TUMU').strip().upper(),
                tarih_bas=(args.get('tarih_bas') or '').strip() or None,
                tarih_bit=(args.get('tarih_bit') or '').strip() or None,
                islem_turu=(args.get('islem_turu') or '').strip() or None,
                belge_no=(args.get('belge_no') or '').strip() or None,
                tutar_min=float(args['tutar_min']) if args.get('tutar_min') else None,
                tutar_max=float(args['tutar_max']) if args.get('tutar_max') else None,
            )
            return _api_demo_wrap(paket, demo_meta)
        except FinansCariHesapReadError as e:
            return _cari_hesap_json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans/cari-hesap/<tip>/<int:operasyonel_id>/genel-durum')
    @login_gerekli
    def api_finans_cari_genel_durum(tip, operasyonel_id):
        if not _finans_erisim():
            abort(403)
        con, demo_meta = _finans_con()
        try:
            t, oid = _cari_hesap_tip_id(tip, operasyonel_id)
            args = request.args
            paket = cari_genel_durum(
                con, t, oid,
                para_birimi=(args.get('para_birimi') or '').strip() or None,
                tum_islem_turleri=args.get('tum_islem_turleri') == '1',
            )
            return _api_demo_wrap(paket, demo_meta)
        except FinansCariHesapReadError as e:
            return _cari_hesap_json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans/cari-hesap/<tip>/<int:operasyonel_id>/aylik-durum')
    @login_gerekli
    def api_finans_cari_aylik_durum(tip, operasyonel_id):
        if not _finans_erisim():
            abort(403)
        con, demo_meta = _finans_con()
        try:
            t, oid = _cari_hesap_tip_id(tip, operasyonel_id)
            args = request.args
            yil_raw = args.get('yil')
            paket = cari_aylik_durum(
                con, t, oid,
                yil=int(yil_raw) if yil_raw else None,
                para_birimi=(args.get('para_birimi') or '').strip() or None,
            )
            return _api_demo_wrap(paket, demo_meta)
        except FinansCariHesapReadError as e:
            return _cari_hesap_json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans/cari-hesap/<tip>/<int:operasyonel_id>/risk')
    @login_gerekli
    def api_finans_cari_risk(tip, operasyonel_id):
        if not _finans_erisim():
            abort(403)
        con, demo_meta = _finans_con()
        try:
            t, oid = _cari_hesap_tip_id(tip, operasyonel_id)
            paket = cari_risk(con, t, oid, demo_modu=bool(demo_meta.get('demo_modu')))
            return _api_demo_wrap(paket, demo_meta)
        except FinansCariHesapReadError as e:
            return _cari_hesap_json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans/cari-hesap/<tip>/<int:operasyonel_id>/yetkililer')
    @login_gerekli
    def api_finans_cari_yetkililer(tip, operasyonel_id):
        if not _finans_erisim():
            abort(403)
        con, demo_meta = _finans_con()
        try:
            t, oid = _cari_hesap_tip_id(tip, operasyonel_id)
            paket = cari_yetkililer(con, t, oid, demo_modu=bool(demo_meta.get('demo_modu')))
            return _api_demo_wrap(paket, demo_meta)
        except FinansCariHesapReadError as e:
            return _cari_hesap_json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans/cari-hesap/<tip>/<int:operasyonel_id>/fiyatlar')
    @login_gerekli
    def api_finans_cari_fiyatlar(tip, operasyonel_id):
        if not _finans_erisim():
            abort(403)
        con, demo_meta = _finans_con()
        try:
            t, oid = _cari_hesap_tip_id(tip, operasyonel_id)
            paket = cari_fiyatlar(con, t, oid, demo_modu=bool(demo_meta.get('demo_modu')))
            return _api_demo_wrap(paket, demo_meta)
        except FinansCariHesapReadError as e:
            return _cari_hesap_json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans/cari-hesap/<tip>/<int:operasyonel_id>/siparisler')
    @login_gerekli
    def api_finans_cari_siparisler(tip, operasyonel_id):
        if not _finans_erisim():
            abort(403)
        con = db_fn()
        try:
            t, oid = _cari_hesap_tip_id(tip, operasyonel_id)
            return jsonify(api_ok(data=cari_siparisler(con, t, oid)))
        except FinansCariHesapReadError as e:
            return _cari_hesap_json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans/cari-hesap/<tip>/<int:operasyonel_id>/hesap')
    @login_gerekli
    def api_finans_cari_hesap_workspace(tip, operasyonel_id):
        if not _finans_erisim():
            abort(403)
        args = request.args
        con = db_fn()
        try:
            t, oid = _cari_hesap_tip_id(tip, operasyonel_id)
            paket = cari_hesap_workspace(
                con, t, oid,
                gorunum=(args.get('gorunum') or 'aciklar').strip().lower(),
                limit=int(args.get('limit') or 200),
                offset=int(args.get('offset') or 0),
            )
            return jsonify(api_ok(data=paket))
        except FinansCariHesapReadError as e:
            return _cari_hesap_json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans/cari-hesap/<tip>/<int:operasyonel_id>/sevkiyatlar')
    @login_gerekli
    def api_finans_cari_hesap_sevkiyatlar(tip, operasyonel_id):
        if not _finans_erisim():
            abort(403)
        con = db_fn()
        try:
            t, oid = _cari_hesap_tip_id(tip, operasyonel_id)
            return jsonify(api_ok(data=cari_sevkiyatlar(con, t, oid)))
        except FinansCariHesapReadError as e:
            return _cari_hesap_json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans/cari-hesap/<tip>/<int:operasyonel_id>/tahsilatlar')
    @login_gerekli
    def api_finans_cari_hesap_tahsilatlar(tip, operasyonel_id):
        if not _finans_erisim():
            abort(403)
        con = db_fn()
        try:
            t, oid = _cari_hesap_tip_id(tip, operasyonel_id)
            return jsonify(api_ok(data=cari_tahsilatlar(con, t, oid)))
        except FinansCariHesapReadError as e:
            return _cari_hesap_json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans/cari-hesap/<tip>/<int:operasyonel_id>/odemeler')
    @login_gerekli
    def api_finans_cari_hesap_odemeler(tip, operasyonel_id):
        if not _finans_erisim():
            abort(403)
        con = db_fn()
        try:
            t, oid = _cari_hesap_tip_id(tip, operasyonel_id)
            return jsonify(api_ok(data=cari_odemeler(con, t, oid)))
        except FinansCariHesapReadError as e:
            return _cari_hesap_json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans/cari-hesap/<tip>/<int:operasyonel_id>/vadeler')
    @login_gerekli
    def api_finans_cari_hesap_vadeler(tip, operasyonel_id):
        if not _finans_erisim():
            abort(403)
        con = db_fn()
        try:
            t, oid = _cari_hesap_tip_id(tip, operasyonel_id)
            return jsonify(api_ok(data=cari_vadeler(con, t, oid)))
        except FinansCariHesapReadError as e:
            return _cari_hesap_json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans/cari-hesap/<tip>/<int:operasyonel_id>/bilgiler')
    @login_gerekli
    def api_finans_cari_hesap_bilgiler(tip, operasyonel_id):
        if not _finans_erisim():
            abort(403)
        con = db_fn()
        try:
            t, oid = _cari_hesap_tip_id(tip, operasyonel_id)
            return jsonify(api_ok(data=cari_bilgileri(con, t, oid)))
        except (FinansCariHesapReadError, FinansCariReadError) as e:
            if isinstance(e, FinansCariReadError):
                return jsonify(api_hata(e.hata_kodu or 'CARI_HATA', e.mesaj)), int(e.kod or 404)
            return _cari_hesap_json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans-belgesi/sevkiyat/<int:sevkiyat_id>', methods=['POST'])
    @login_gerekli
    def api_finans_belge_sevkiyat(sevkiyat_id):
        yk = _yk()
        if finans_erisim_engelli(_u(), yk) or not can_finans_review(yk):
            abort(403)
        if is_pazarlamaci_finans_kisitli(yk):
            abort(403)
        u = _u()
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            belge = FinanceWorkflowService.belge_olustur_sevkiyat(
                con, sevkiyat_id, kullanici_id_fn(), u.get('KullaniciAdi') or u.get('AdSoyad'),
            )
            con.commit()
            return jsonify(api_ok(belge=belge_detay_satir(belge), idempotent=True))
        except FinansBelgesiError as e:
            con.rollback()
            return _json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans-belgesi/tahsilat/<int:tahsilat_id>', methods=['POST'])
    @login_gerekli
    def api_finans_belge_tahsilat(tahsilat_id):
        yk = _yk()
        if finans_erisim_engelli(_u(), yk) or not can_finans_review(yk):
            abort(403)
        if is_pazarlamaci_finans_kisitli(yk):
            abort(403)
        u = _u()
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            belge = FinanceWorkflowService.belge_olustur_tahsilat(
                con, tahsilat_id, kullanici_id_fn(), u.get('KullaniciAdi') or u.get('AdSoyad'),
            )
            con.commit()
            return jsonify(api_ok(belge=belge_detay_satir(belge), idempotent=True))
        except FinansBelgesiError as e:
            con.rollback()
            return _json_hata(e)
        finally:
            con.close()

    def _durum_islem(belge_id: int, fn, yetki_fn, **kwargs):
        yk = _yk()
        if finans_erisim_engelli(_u(), yk) or not yetki_fn(yk):
            abort(403)
        if is_pazarlamaci_finans_kisitli(yk) and yetki_fn != can_finans_review:
            abort(403)
        u = _u()
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            belge = fn(
                con, belge_id, kullanici_id_fn(), u.get('KullaniciAdi') or u.get('AdSoyad'), **kwargs,
            )
            con.commit()
            return jsonify(api_ok(belge=belge_detay_satir(belge)))
        except FinansBelgesiError as e:
            con.rollback()
            return _json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans-belgesi/<int:belge_id>/incelemeye-al', methods=['POST'])
    @login_gerekli
    def api_finans_incelemeye_al(belge_id):
        d = _body()
        return _durum_islem(
            belge_id, FinanceWorkflowService.incelemeye_al, can_finans_review,
        )

    @bp.route('/api/finans-belgesi/<int:belge_id>/onayla', methods=['POST'])
    @login_gerekli
    def api_finans_onayla(belge_id):
        d = _body()
        return _durum_islem(
            belge_id, FinanceWorkflowService.onayla, can_finans_approve,
            notu=(d.get('not') or d.get('notu') or '').strip() or None,
        )

    @bp.route('/api/finans-belgesi/<int:belge_id>/duzeltmeye-gonder', methods=['POST'])
    @login_gerekli
    def api_finans_duzeltmeye_gonder(belge_id):
        d = _body()
        return _durum_islem(
            belge_id, FinanceWorkflowService.duzeltmeye_gonder, can_finans_review,
            notu=(d.get('not') or d.get('aciklama') or '').strip() or None,
        )

    @bp.route('/api/finans-belgesi/<int:belge_id>/reddet', methods=['POST'])
    @login_gerekli
    def api_finans_reddet(belge_id):
        d = _body()
        gerekce = (d.get('gerekce') or d.get('not') or '').strip()
        if not gerekce:
            return jsonify(api_hata('RED_GEREKCE', 'Red gerekçesi zorunlu.')), 400
        return _durum_islem(
            belge_id, FinanceWorkflowService.reddet, can_finans_reject,
            gerekce=gerekce,
        )

    @bp.route('/api/finans-belgesi/<int:belge_id>/kapat', methods=['POST'])
    @login_gerekli
    def api_finans_kapat(belge_id):
        yk = _yk()
        if finans_erisim_engelli(_u(), yk):
            abort(403)
        if not (can_finans_manage(yk) or can_finans_approve(yk)):
            abort(403)
        return _durum_islem(belge_id, FinanceWorkflowService.kapat, can_finans_manage)

    @bp.route('/api/finans-belgesi/<int:belge_id>/posting-dry-run', methods=['POST'])
    @login_gerekli
    def api_finans_posting_dry_run(belge_id):
        yk = _yk()
        if finans_erisim_engelli(_u(), yk) or not can_finans_post(yk):
            abort(403)
        if is_pazarlamaci_finans_kisitli(yk):
            abort(403)
        u = _u()
        con = db_fn()
        try:
            from modules.nexgen.finans_belgesi_repository import get_by_id
            belge = get_by_id(con, belge_id)
            tip = belge.get('belge_tipi')
            con.execute('BEGIN IMMEDIATE')
            if tip == 'SATIS_SEVKIYAT':
                sonuc = FinancialPostingService.post_borc(
                    con, belge_id, kullanici_id_fn(), u.get('KullaniciAdi'), force_live=False,
                )
            elif tip == 'TAHSILAT':
                sonuc = FinancialPostingService.post_alacak(
                    con, belge_id, kullanici_id_fn(), u.get('KullaniciAdi'), force_live=False,
                )
            else:
                raise FinansBelgesiError('Desteklenmeyen belge tipi.', 409, 'BELGE_TIP_UYUMSUZ')
            con.commit()
            paket = detay_paket(con, belge_id, _yk(), user_dict=_u())
            return jsonify(api_ok(
                dry_run=True,
                cari_entegrasyon_aktif=CARI_ENTEGRASYON_AKTIF,
                sonuc=sonuc,
                belge=belge_detay_satir(
                    paket['belge'],
                    kaynak_ozet=paket.get('kaynak_ozet'),
                    audit=paket.get('audit'),
                    durum_gecisleri=paket.get('durum_gecisleri'),
                    aksiyonlar=paket.get('aksiyonlar'),
                    posting_onizleme=paket.get('posting_onizleme'),
                ),
                cari_hesap=paket.get('cari_hesap'),
            ))
        except FinansBelgesiError as e:
            con.rollback()
            return _json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans-belgesi/<int:belge_id>/posting-kontrol', methods=['POST'])
    @login_gerekli
    def api_finans_posting_kontrol(belge_id):
        """Yan etkisiz validasyon — Cari_Har yazmaz."""
        if not _finans_erisim() or not can_finans_post(_yk()):
            abort(403)
        con = db_fn()
        try:
            from modules.nexgen.finans_read_service import posting_onizleme
            from modules.nexgen.finans_belgesi_repository import get_by_id
            belge = get_by_id(con, belge_id)
            oniz = posting_onizleme(con, belge)
            return jsonify(api_ok(
                dry_run=True,
                cari_entegrasyon_aktif=CARI_ENTEGRASYON_AKTIF,
                onizleme=oniz,
            ))
        except FinansBelgesiError as e:
            return _json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans-belgesi/<int:belge_id>/posting', methods=['POST'])
    @login_gerekli
    def api_finans_posting_live(belge_id):
        """Gerçek Cari_Har posting — CARI_ENTEGRASYON_AKTIF=True ve can_post gerekir."""
        yk = _yk()
        if finans_erisim_engelli(_u(), yk) or not can_finans_post(yk):
            abort(403)
        if is_pazarlamaci_finans_kisitli(yk):
            abort(403)
        if not CARI_ENTEGRASYON_AKTIF:
            return jsonify(api_hata(
                'POSTING_KAPALI',
                'Gerçek Cari_Har posting kapalı (CARI_ENTEGRASYON_AKTIF=False).',
            )), 403
        u = _u()
        con = db_fn()
        try:
            from modules.nexgen.finans_belgesi_repository import get_by_id
            belge = get_by_id(con, belge_id)
            tip = belge.get('belge_tipi')
            con.execute('BEGIN IMMEDIATE')
            if tip == 'SATIS_SEVKIYAT':
                sonuc = FinancialPostingService.post_borc(
                    con, belge_id, kullanici_id_fn(), u.get('KullaniciAdi'), force_live=True,
                )
            elif tip == 'TAHSILAT':
                sonuc = FinancialPostingService.post_alacak(
                    con, belge_id, kullanici_id_fn(), u.get('KullaniciAdi'), force_live=True,
                )
            else:
                raise FinansBelgesiError('Desteklenmeyen belge tipi.', 409, 'BELGE_TIP_UYUMSUZ')
            con.commit()
            paket = detay_paket(con, belge_id, _yk(), user_dict=_u())
            return jsonify(api_ok(
                dry_run=False,
                cari_entegrasyon_aktif=CARI_ENTEGRASYON_AKTIF,
                sonuc=sonuc,
                belge=belge_detay_satir(
                    paket['belge'],
                    kaynak_ozet=paket.get('kaynak_ozet'),
                    audit=paket.get('audit'),
                    durum_gecisleri=paket.get('durum_gecisleri'),
                    aksiyonlar=paket.get('aksiyonlar'),
                    posting_onizleme=paket.get('posting_onizleme'),
                ),
                cari_hesap=paket.get('cari_hesap'),
            ))
        except FinansBelgesiError as e:
            con.rollback()
            return _json_hata(e)
        finally:
            con.close()
