# -*- coding: utf-8 -*-
"""
NX-AR API — FAZ-ARGE-2D2 + FAZ-RENK-MERKEZI-ONAY-1

POST /nexgen/api/arge/nx-ar
GET  /nexgen/api/arge/nx-ar
GET  /nexgen/api/arge/nx-ar/<id>
POST /nexgen/api/arge/nx-ar/<id>/saha-karar
GET  /nexgen/api/arge/nx-ar/ferhat-bekleyen
POST /nexgen/api/arge/nx-ar/<id>/ferhat-ac
POST /nexgen/api/arge/nx-ar/<id>/ferhat-sonuc
POST /nexgen/api/arge/nx-ar/<id>/yonetim-karar
GET  /nexgen/api/arge/nx-ar/<id>/olaylar
"""
from __future__ import annotations

from flask import jsonify, request

from modules.auth import yetki_gerekli, yetki_var, login_gerekli
from modules.nexgen.nx_ar_service import (
    NxArError,
    create_nx_ar,
    ferhat_ac,
    ferhat_bekleyen_liste,
    ferhat_sonuc_kaydet,
    get_nx_ar,
    list_nx_ar,
    olay_liste,
    saha_karar_kaydet,
    yonetim_karar,
)


def register_nx_ar_routes(bp, db_factory, kullanici_id_fn):
    """nexgen_bp üzerine NX-AR route'larını bağlar."""

    def _con():
        return db_factory()

    def _uid():
        return kullanici_id_fn()

    def _nx_ar_okuma_yetkisi():
        return (
            yetki_var('nexgen.recete.view', 'can_view')
            or yetki_var('nexgen.tablet.view', 'can_view')
        )

    def _nx_ar_onay_yetkisi():
        return (
            yetki_var('nexgen.recete.approve', 'can_approve')
            or yetki_var('nexgen.yonetim.manage', 'can_view')
        )

    def _err(e: Exception):
        if isinstance(e, NxArError):
            return jsonify({'ok': False, 'hata': e.message, 'kod': e.kod}), e.status
        return jsonify({'ok': False, 'hata': str(e)}), 500

    @bp.route('/api/arge/nx-ar', methods=['POST'])
    @yetki_gerekli('nexgen.tablet.view', 'can_view')
    def api_nx_ar_create():
        if not (
            yetki_var('nexgen.tablet.view', 'can_view')
            or yetki_var('nexgen.recete.create', 'can_create')
        ):
            return jsonify({'ok': False, 'hata': 'Yetki yok'}), 403
        data = request.get_json(silent=True) or {}
        con = _con()
        try:
            out = create_nx_ar(con, data, kullanici_id=_uid())
            return jsonify(out), 201
        except Exception as e:
            return _err(e)
        finally:
            con.close()

    @bp.route('/api/arge/nx-ar', methods=['GET'])
    @login_gerekli
    def api_nx_ar_list():
        if not _nx_ar_okuma_yetkisi():
            return jsonify({'ok': False, 'hata': 'Yetki yok'}), 403
        con = _con()
        try:
            limit = request.args.get('limit', 50)
            offset = request.args.get('offset', 0)
            return jsonify(list_nx_ar(con, limit=limit, offset=offset))
        except Exception as e:
            return _err(e)
        finally:
            con.close()

    @bp.route('/api/arge/nx-ar/ferhat-bekleyen', methods=['GET'])
    @yetki_gerekli('nexgen.tablet.view', 'can_view')
    def api_nx_ar_ferhat_bekleyen():
        con = _con()
        try:
            limit = request.args.get('limit', 100)
            return jsonify(ferhat_bekleyen_liste(con, limit=limit))
        except Exception as e:
            return _err(e)
        finally:
            con.close()

    @bp.route('/api/arge/nx-ar/<int:arge_test_id>', methods=['GET'])
    @login_gerekli
    def api_nx_ar_get(arge_test_id):
        if not _nx_ar_okuma_yetkisi():
            return jsonify({'ok': False, 'hata': 'Yetki yok'}), 403
        con = _con()
        try:
            return jsonify(get_nx_ar(con, arge_test_id))
        except Exception as e:
            return _err(e)
        finally:
            con.close()

    @bp.route('/api/arge/nx-ar/<int:arge_test_id>/saha-karar', methods=['POST'])
    @login_gerekli
    def api_nx_ar_saha_karar(arge_test_id):
        if not _nx_ar_onay_yetkisi():
            return jsonify({'ok': False, 'hata': 'Yetki yok'}), 403
        data = request.get_json(silent=True) or {}
        con = _con()
        try:
            return jsonify(saha_karar_kaydet(con, arge_test_id, data, kullanici_id=_uid()))
        except Exception as e:
            return _err(e)
        finally:
            con.close()

    @bp.route('/api/arge/nx-ar/<int:arge_test_id>/ferhat-ac', methods=['POST'])
    @yetki_gerekli('nexgen.tablet.view', 'can_view')
    def api_nx_ar_ferhat_ac(arge_test_id):
        con = _con()
        try:
            return jsonify(ferhat_ac(con, arge_test_id, kullanici_id=_uid()))
        except Exception as e:
            return _err(e)
        finally:
            con.close()

    @bp.route('/api/arge/nx-ar/<int:arge_test_id>/ferhat-sonuc', methods=['POST'])
    @yetki_gerekli('nexgen.tablet.view', 'can_view')
    def api_nx_ar_ferhat_sonuc(arge_test_id):
        data = request.get_json(silent=True) or {}
        con = _con()
        try:
            return jsonify(ferhat_sonuc_kaydet(con, arge_test_id, data, kullanici_id=_uid()))
        except Exception as e:
            return _err(e)
        finally:
            con.close()

    @bp.route('/api/arge/nx-ar/<int:arge_test_id>/yonetim-karar', methods=['POST'])
    @login_gerekli
    def api_nx_ar_yonetim_karar(arge_test_id):
        if not _nx_ar_onay_yetkisi():
            return jsonify({'ok': False, 'hata': 'Yetki yok'}), 403
        data = request.get_json(silent=True) or {}
        con = _con()
        try:
            return jsonify(yonetim_karar(con, arge_test_id, data, kullanici_id=_uid()))
        except Exception as e:
            return _err(e)
        finally:
            con.close()

    @bp.route('/api/arge/nx-ar/<int:arge_test_id>/olaylar', methods=['GET'])
    @login_gerekli
    def api_nx_ar_olaylar(arge_test_id):
        if not _nx_ar_okuma_yetkisi():
            return jsonify({'ok': False, 'hata': 'Yetki yok'}), 403
        con = _con()
        try:
            return jsonify({'ok': True, 'items': olay_liste(con, arge_test_id)})
        except Exception as e:
            return _err(e)
        finally:
            con.close()
