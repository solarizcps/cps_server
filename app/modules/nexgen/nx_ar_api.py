# -*- coding: utf-8 -*-
"""
NX-AR API iskeleti — FAZ-ARGE-2D2

POST /nexgen/api/arge/nx-ar
GET  /nexgen/api/arge/nx-ar
GET  /nexgen/api/arge/nx-ar/<id>
"""
from __future__ import annotations

from flask import jsonify, request

from modules.auth import yetki_gerekli, yetki_var, login_gerekli
from modules.nexgen.nx_ar_service import NxArError, create_nx_ar, get_nx_ar, list_nx_ar


def register_nx_ar_routes(bp, db_factory, kullanici_id_fn):
    """nexgen_bp üzerine NX-AR route'larını bağlar."""

    def _con():
        return db_factory()

    def _uid():
        return kullanici_id_fn()

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
        except NxArError as e:
            return jsonify({'ok': False, 'hata': e.message, 'kod': e.kod}), e.status
        except Exception as e:
            return jsonify({'ok': False, 'hata': str(e)}), 500
        finally:
            con.close()

    def _nx_ar_okuma_yetkisi():
        return (
            yetki_var('nexgen.recete.view', 'can_view')
            or yetki_var('nexgen.tablet.view', 'can_view')
        )

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
        except NxArError as e:
            return jsonify({'ok': False, 'hata': e.message, 'kod': e.kod}), e.status
        except Exception as e:
            return jsonify({'ok': False, 'hata': str(e)}), 500
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
        except NxArError as e:
            return jsonify({'ok': False, 'hata': e.message, 'kod': e.kod}), e.status
        except Exception as e:
            return jsonify({'ok': False, 'hata': str(e)}), 500
        finally:
            con.close()
