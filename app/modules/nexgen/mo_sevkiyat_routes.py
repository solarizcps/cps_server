# -*- coding: utf-8 -*-
"""Gerçek outbound müşteri sevkiyat API route kayıtları."""
from __future__ import annotations

from flask import abort, jsonify, render_template, request, session

from modules.auth import login_gerekli, kullanici_yetkileri, yetki_var
from modules.nexgen.mo_sevkiyat_config import YETKI_SEVKIYAT_VIEW, YETKI_SEVKIYAT_WRITE
from modules.nexgen.mo_sevkiyat_operasyon_service import (
    liste_sevkiyat_tab,
    operasyon_detay_paket,
    sevkiyata_hazir_siparisler,
    siparis_sevk_form_verisi,
)
from modules.nexgen.mo_sevkiyat_service import (
    MoSevkiyatError,
    can_sevkiyat_oku,
    can_sevkiyat_yaz,
    durum_guncelle,
    kalan_miktarlar,
    liste_siparis,
    sevkiyat_getir,
    sevkiyat_olustur,
    son_sevkiyat_ozet,
    termin_karsilastirma,
)


def register_mo_sevkiyat_routes(bp, db_fn, kullanici_id_fn):
    def _yk():
        return kullanici_yetkileri(session.get('kullanici') or {})

    def _sayfa_yetki():
        yk = _yk()
        return (
            can_sevkiyat_yaz(yk)
            or yetki_var(YETKI_SEVKIYAT_VIEW, 'can_view')
            or yetki_var('nexgen.plan.manage', 'can_manage')
        )

    @bp.route('/sevkiyat')
    @login_gerekli
    def sevkiyat_operasyon_sayfa():
        if not _sayfa_yetki():
            abort(403)
        return render_template(
            'nexgen/sevkiyat.html',
            active='nexgen',
            can_yaz=can_sevkiyat_yaz(_yk()),
        )

    @bp.route('/sevkiyat/<int:sevkiyat_id>')
    @login_gerekli
    def sevkiyat_operasyon_detay_sayfa(sevkiyat_id):
        if not _sayfa_yetki():
            abort(403)
        return render_template(
            'nexgen/sevkiyat_detay.html',
            sevkiyat_id=sevkiyat_id,
            active='nexgen',
            can_yaz=can_sevkiyat_yaz(_yk()),
        )

    @bp.route('/api/sevkiyat-operasyon/liste')
    @login_gerekli
    def api_sevkiyat_operasyon_liste():
        if not _sayfa_yetki():
            abort(403)
        tab = (request.args.get('tab') or 'hazir').strip().lower()
        con = db_fn()
        try:
            if tab == 'hazir':
                liste = sevkiyata_hazir_siparisler(con)
            else:
                liste = liste_sevkiyat_tab(con, tab)
            return jsonify({'ok': True, 'tab': tab, 'liste': liste})
        finally:
            con.close()

    @bp.route('/api/sevkiyat-operasyon/siparis/<int:siparis_id>/form')
    @login_gerekli
    def api_sevkiyat_operasyon_form(siparis_id):
        if not _sayfa_yetki():
            abort(403)
        con = db_fn()
        try:
            from modules.nexgen.mo_sevkiyat_service import _siparis_guard
            sip = _siparis_guard(con, siparis_id)
            if not can_sevkiyat_oku(con, kullanici_id_fn(), int(sip['cari_id']), _yk()):
                abort(403)
            return jsonify({'ok': True, 'form': siparis_sevk_form_verisi(con, siparis_id)})
        except MoSevkiyatError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/sevkiyat-operasyon/<int:sevkiyat_id>/paket')
    @login_gerekli
    def api_sevkiyat_operasyon_paket(sevkiyat_id):
        if not _sayfa_yetki():
            abort(403)
        con = db_fn()
        try:
            paket = operasyon_detay_paket(con, sevkiyat_id, kullanici_id_fn(), _yk())
            return jsonify({'ok': True, 'sevkiyat': paket})
        except MoSevkiyatError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/mo-sevkiyat', methods=['POST'])
    @login_gerekli
    def api_mo_sevkiyat_olustur():
        if not can_sevkiyat_yaz(_yk()):
            abort(403)
        payload = request.get_json(silent=True) or {}
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            kayit = sevkiyat_olustur(con, payload, kullanici_id_fn(), _yk())
            return jsonify({'ok': True, 'sevkiyat': kayit})
        except MoSevkiyatError as e:
            con.rollback()
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/mo-sevkiyat/<int:sevkiyat_id>')
    @login_gerekli
    def api_mo_sevkiyat_detay(sevkiyat_id):
        con = db_fn()
        try:
            kayit = sevkiyat_getir(con, sevkiyat_id, kullanici_id_fn(), _yk())
            return jsonify({'ok': True, 'sevkiyat': kayit})
        except MoSevkiyatError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/mo-sevkiyat/siparis/<int:siparis_id>')
    @login_gerekli
    def api_mo_sevkiyat_siparis_liste(siparis_id):
        con = db_fn()
        try:
            liste = liste_siparis(con, siparis_id, kullanici_id_fn(), _yk())
            return jsonify({'ok': True, 'liste': liste})
        except MoSevkiyatError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/mo-sevkiyat/siparis/<int:siparis_id>/kalan')
    @login_gerekli
    def api_mo_sevkiyat_kalan(siparis_id):
        con = db_fn()
        try:
            from modules.nexgen.mo_sevkiyat_service import _siparis_guard
            sip = _siparis_guard(con, siparis_id)
            if not can_sevkiyat_oku(con, kullanici_id_fn(), int(sip['cari_id']), _yk()):
                abort(403)
            return jsonify({'ok': True, 'kalan': kalan_miktarlar(con, siparis_id)})
        except MoSevkiyatError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/mo-sevkiyat/siparis/<int:siparis_id>/termin')
    @login_gerekli
    def api_mo_sevkiyat_termin(siparis_id):
        con = db_fn()
        try:
            from modules.nexgen.mo_sevkiyat_service import _siparis_guard
            sip = _siparis_guard(con, siparis_id)
            if not can_sevkiyat_oku(con, kullanici_id_fn(), int(sip['cari_id']), _yk()):
                abort(403)
            return jsonify({'ok': True, 'termin': termin_karsilastirma(con, siparis_id)})
        except MoSevkiyatError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/mo-sevkiyat/cari/<int:cari_id>/son')
    @login_gerekli
    def api_mo_sevkiyat_cari_son(cari_id):
        con = db_fn()
        try:
            if not can_sevkiyat_oku(con, kullanici_id_fn(), cari_id, _yk()):
                abort(403)
            ozet = son_sevkiyat_ozet(con, cari_id)
            return jsonify({'ok': True, 'son_sevkiyat': ozet})
        finally:
            con.close()

    @bp.route('/api/mo-sevkiyat/<int:sevkiyat_id>/durum', methods=['POST'])
    @login_gerekli
    def api_mo_sevkiyat_durum(sevkiyat_id):
        if not can_sevkiyat_yaz(_yk()):
            abort(403)
        payload = request.get_json(silent=True) or {}
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            kayit = durum_guncelle(
                con, sevkiyat_id,
                payload.get('durum') or '',
                kullanici_id_fn(), _yk(),
                sevk_tarihi=payload.get('sevk_tarihi'),
                teslim_tarihi=payload.get('teslim_tarihi'),
                teslim_alan=payload.get('teslim_alan'),
                teslim_durumu=payload.get('teslim_durumu'),
            )
            return jsonify({'ok': True, 'sevkiyat': kayit})
        except MoSevkiyatError as e:
            con.rollback()
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()
