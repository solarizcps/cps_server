# -*- coding: utf-8 -*-
"""MÜŞTERİ OPERASYONU ana ekran route kayıtları."""
from __future__ import annotations

from flask import abort, jsonify, render_template, request, session

from modules.auth import login_gerekli, kullanici_yetkileri
from modules.nexgen.cari360_yetki import can_cari360_view_all, can_musteri_pazarlama_menu
from modules.nexgen.mo_gorusme_config import GORUSME_TIPLERI, ONCELIKLER, SONUC_TIPLERI
from modules.nexgen.mo_gorusme_service import (
    MoGorusmeError,
    can_mo_gorusme_yaz,
    gorusme_kaydet,
    list_gorusmeler,
    sorumlu_pazarlamaci_adi,
)
from modules.nexgen.musteri_pazarlama_service import dashboard_ozet
from modules.nexgen.mo_numune_talep_service import (
    MoNumuneError,
    mo_talep_detay,
    onaya_gonder,
    ozet_olustur,
    taslak_kaydet,
)
from modules.nexgen.mo_siparis_talep_service import (
    MoSiparisError,
    mo_siparis_detay,
    onaya_gonder as siparis_onaya_gonder,
    ozet_olustur as siparis_ozet_olustur,
    taslak_kaydet as siparis_taslak_kaydet,
)
from modules.nexgen.mo_tahsilat_kayit_service import (
    MoTahsilatError,
    acik_planlar,
    kayit_detay,
    onaya_gonder as tahsilat_onaya_gonder,
    taslak_kaydet as tahsilat_taslak_kaydet,
)


def register_musteri_pazarlama_routes(bp, db_fn, kullanici_id_fn):
    def _yetki_kontrol():
        u = session.get('kullanici') or {}
        yk = kullanici_yetkileri(u)
        if not can_musteri_pazarlama_menu(yk):
            abort(403)
        return u, yk

    @bp.route('/musteri-pazarlama')
    @login_gerekli
    def musteri_pazarlama_sayfa():
        u, yk = _yetki_kontrol()
        con = db_fn()
        try:
            uid = kullanici_id_fn()
            ozet = dashboard_ozet(con, uid, yk)
        finally:
            con.close()
        return render_template(
            'nexgen/musteri_pazarlama.html',
            active='nexgen',
            ozet=ozet,
            kullanici_ad=u.get('KullaniciAdi') or '',
            gorusme_tipleri=GORUSME_TIPLERI,
            sonuc_tipleri=SONUC_TIPLERI,
            oncelikler=ONCELIKLER,
        )

    @bp.route('/api/musteri-pazarlama/ozet')
    @login_gerekli
    def api_musteri_pazarlama_ozet():
        u, yk = _yetki_kontrol()
        con = db_fn()
        try:
            return jsonify({'ok': True, **dashboard_ozet(con, kullanici_id_fn(), yk)})
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/gorusme', methods=['POST'])
    @login_gerekli
    def api_mo_gorusme_kaydet():
        _yetki_kontrol()
        payload = request.get_json(silent=True) or {}
        con = db_fn()
        try:
            kayit = gorusme_kaydet(con, payload, kullanici_id_fn(), kullanici_yetkileri(session.get('kullanici') or {}))
            return jsonify({'ok': True, 'kayit': kayit, 'mesaj': 'Görüşme kaydı oluşturuldu.'})
        except MoGorusmeError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/gorusme')
    @login_gerekli
    def api_mo_gorusme_liste():
        _yetki_kontrol()
        cari_id = request.args.get('cari_id', type=int)
        if not cari_id:
            return jsonify({'ok': False, 'mesaj': 'cari_id zorunlu.'}), 400
        con = db_fn()
        try:
            liste = list_gorusmeler(
                con, cari_id, kullanici_id_fn(),
                kullanici_yetkileri(session.get('kullanici') or {}),
            )
            sorumlu = sorumlu_pazarlamaci_adi(con, cari_id)
            return jsonify({'ok': True, 'liste': liste, 'sorumlu_pazarlamaci': sorumlu})
        except MoGorusmeError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/gorusme-yetki/<int:cari_id>')
    @login_gerekli
    def api_mo_gorusme_yetki(cari_id):
        _yetki_kontrol()
        con = db_fn()
        try:
            yk = kullanici_yetkileri(session.get('kullanici') or {})
            yazabilir = can_mo_gorusme_yaz(con, kullanici_id_fn(), cari_id, yk)
            return jsonify({'ok': True, 'yazabilir': yazabilir})
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/numune-talep', methods=['POST'])
    @login_gerekli
    def api_mo_numune_taslak():
        _yetki_kontrol()
        payload = request.get_json(silent=True) or {}
        talep_id = payload.get('talep_id')
        if talep_id not in (None, ''):
            try:
                talep_id = int(talep_id)
            except (TypeError, ValueError):
                talep_id = None
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            kayit = taslak_kaydet(
                con, payload, kullanici_id_fn(),
                kullanici_yetkileri(session.get('kullanici') or {}),
                talep_id=talep_id,
            )
            return jsonify({'ok': True, 'kayit': kayit, 'mesaj': 'Taslak kaydedildi.'})
        except MoNumuneError as e:
            con.rollback()
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/numune-talep/<int:talep_id>')
    @login_gerekli
    def api_mo_numune_detay(talep_id):
        _yetki_kontrol()
        con = db_fn()
        try:
            kayit = mo_talep_detay(
                con, talep_id, kullanici_id_fn(),
                kullanici_yetkileri(session.get('kullanici') or {}),
            )
            return jsonify({'ok': True, 'kayit': kayit})
        except MoNumuneError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/numune-talep/<int:talep_id>/ozet')
    @login_gerekli
    def api_mo_numune_ozet(talep_id):
        _yetki_kontrol()
        con = db_fn()
        try:
            ozet = ozet_olustur(
                con, talep_id, kullanici_id_fn(),
                kullanici_yetkileri(session.get('kullanici') or {}),
            )
            return jsonify({'ok': True, 'ozet': ozet})
        except MoNumuneError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/numune-talep/<int:talep_id>/onaya-gonder', methods=['POST'])
    @login_gerekli
    def api_mo_numune_onaya_gonder(talep_id):
        _yetki_kontrol()
        payload = request.get_json(silent=True) or {}
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            r = onaya_gonder(
                con, talep_id, kullanici_id_fn(),
                kullanici_yetkileri(session.get('kullanici') or {}),
                payload=payload or None,
            )
            return jsonify(r)
        except MoNumuneError as e:
            con.rollback()
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/siparis-talep', methods=['POST'])
    @login_gerekli
    def api_mo_siparis_taslak():
        _yetki_kontrol()
        payload = request.get_json(silent=True) or {}
        siparis_id = payload.get('siparis_id')
        if siparis_id not in (None, ''):
            try:
                siparis_id = int(siparis_id)
            except (TypeError, ValueError):
                siparis_id = None
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            kayit = siparis_taslak_kaydet(
                con, payload, kullanici_id_fn(),
                kullanici_yetkileri(session.get('kullanici') or {}),
                siparis_id=siparis_id,
            )
            return jsonify({'ok': True, 'kayit': kayit, 'mesaj': 'Taslak kaydedildi.'})
        except MoSiparisError as e:
            con.rollback()
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/siparis-talep/<int:siparis_id>')
    @login_gerekli
    def api_mo_siparis_detay(siparis_id):
        _yetki_kontrol()
        con = db_fn()
        try:
            kayit = mo_siparis_detay(
                con, siparis_id, kullanici_id_fn(),
                kullanici_yetkileri(session.get('kullanici') or {}),
            )
            return jsonify({'ok': True, 'kayit': kayit})
        except MoSiparisError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/siparis-talep/<int:siparis_id>/ozet')
    @login_gerekli
    def api_mo_siparis_ozet(siparis_id):
        _yetki_kontrol()
        con = db_fn()
        try:
            ozet = siparis_ozet_olustur(
                con, siparis_id, kullanici_id_fn(),
                kullanici_yetkileri(session.get('kullanici') or {}),
            )
            return jsonify({'ok': True, 'ozet': ozet})
        except MoSiparisError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/siparis-talep/<int:siparis_id>/onaya-gonder', methods=['POST'])
    @login_gerekli
    def api_mo_siparis_onaya_gonder(siparis_id):
        _yetki_kontrol()
        payload = request.get_json(silent=True) or {}
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            r = siparis_onaya_gonder(
                con, siparis_id, kullanici_id_fn(),
                kullanici_yetkileri(session.get('kullanici') or {}),
                payload=payload or None,
            )
            return jsonify(r)
        except MoSiparisError as e:
            con.rollback()
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/tahsilat-acik-planlar')
    @login_gerekli
    def api_mo_tahsilat_acik_planlar():
        _yetki_kontrol()
        cid = request.args.get('cari_id')
        try:
            cari_id = int(cid or 0)
        except (TypeError, ValueError):
            cari_id = 0
        if not cari_id:
            return jsonify({'ok': False, 'mesaj': 'cari_id gerekli.'}), 400
        con = db_fn()
        try:
            planlar = acik_planlar(con, [cari_id])
            return jsonify({'ok': True, 'planlar': planlar})
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/tahsilat-kayit', methods=['POST'])
    @login_gerekli
    def api_mo_tahsilat_kayit():
        _yetki_kontrol()
        payload = request.get_json(silent=True) or {}
        kayit_id = payload.get('kayit_id')
        if kayit_id not in (None, ''):
            try:
                kayit_id = int(kayit_id)
            except (TypeError, ValueError):
                kayit_id = None
        con = db_fn()
        try:
            kayit = tahsilat_taslak_kaydet(
                con, payload, kullanici_id_fn(),
                kullanici_yetkileri(session.get('kullanici') or {}),
                kayit_id=kayit_id,
            )
            return jsonify({'ok': True, 'kayit': kayit})
        except MoTahsilatError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/tahsilat-kayit/<int:kayit_id>')
    @login_gerekli
    def api_mo_tahsilat_detay(kayit_id):
        _yetki_kontrol()
        con = db_fn()
        try:
            kayit = kayit_detay(
                con, kayit_id, kullanici_id_fn(),
                kullanici_yetkileri(session.get('kullanici') or {}),
            )
            return jsonify({'ok': True, 'kayit': kayit})
        except MoTahsilatError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/tahsilat-kayit/<int:kayit_id>/onaya-gonder', methods=['POST'])
    @login_gerekli
    def api_mo_tahsilat_onaya_gonder(kayit_id):
        _yetki_kontrol()
        payload = request.get_json(silent=True) or {}
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            r = tahsilat_onaya_gonder(
                con, kayit_id, kullanici_id_fn(),
                kullanici_yetkileri(session.get('kullanici') or {}),
                payload=payload or None,
            )
            return jsonify(r)
        except MoTahsilatError as e:
            con.rollback()
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/design/musteri-operasyonu-canvas')
    @login_gerekli
    def design_musteri_operasyonu_canvas():
        """Statik tasarım preview — menüde yok; yalnız admin / view_all."""
        u = session.get('kullanici') or {}
        yk = kullanici_yetkileri(u)
        if '*' not in yk and not can_cari360_view_all(yk) and int(u.get('RolId') or 0) != 1:
            abort(403)
        return render_template(
            'nexgen/_design_musteri_operasyonu_canvas.html',
            active='nexgen',
            kullanici_ad=u.get('KullaniciAdi') or '',
        )
