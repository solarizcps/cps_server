# -*- coding: utf-8 -*-
"""Cari 360 — Müşteri Dijital Dosyası route kayıtları."""
from __future__ import annotations

from flask import abort, jsonify, render_template, request, session

from modules.auth import login_gerekli, kullanici_yetkileri
from modules.nexgen.cari360_dosya_service import (
    Cari360DosyaError,
    cari_liste,
    dosya_yukle,
    hafiza_liste,
)
from modules.nexgen.cari360_yetki import can_cari360_dosya_ekrani


def register_cari360_routes(bp, db_fn, kullanici_id_fn):
    def _yk():
        return kullanici_yetkileri(session.get('kullanici') or {})

    @bp.route('/cari360')
    @login_gerekli
    def cari360_liste_sayfa():
        if not can_cari360_dosya_ekrani(_yk()):
            abort(403)
        con = db_fn()
        try:
            cariler = cari_liste(con, kullanici_id_fn(), _yk())
        except Cari360DosyaError as e:
            abort(e.kod)
        finally:
            con.close()
        return render_template('nexgen/cari360_liste.html', cariler=cariler)

    @bp.route('/cari360/<int:cari_id>')
    @login_gerekli
    def cari360_dosya_sayfa(cari_id):
        if not can_cari360_dosya_ekrani(_yk()):
            abort(403)
        con = db_fn()
        try:
            uid = kullanici_id_fn()
            data = dosya_yukle(con, cari_id, uid, _yk())
            hafiza = hafiza_liste(con, cari_id, uid, _yk())
        except Cari360DosyaError as e:
            abort(e.kod)
        finally:
            con.close()
        return render_template(
            'nexgen/cari360.html',
            cari_id=cari_id,
            data=data,
            hafiza=hafiza,
        )

    @bp.route('/api/cari360/<int:cari_id>/hafiza')
    @login_gerekli
    def api_cari360_hafiza(cari_id):
        if not can_cari360_dosya_ekrani(_yk()):
            abort(403)
        kategori = (request.args.get('kategori') or 'tumu').strip()
        tarih = (request.args.get('tarih') or 'tumu').strip()
        arama = (request.args.get('q') or '').strip() or None
        con = db_fn()
        try:
            events = hafiza_liste(
                con, cari_id, kullanici_id_fn(), _yk(),
                kategori=None if kategori == 'tumu' else kategori,
                tarih_preset=None if tarih == 'tumu' else tarih,
                arama=arama,
            )
            return jsonify({'ok': True, 'events': events, 'count': len(events)})
        except Cari360DosyaError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()
