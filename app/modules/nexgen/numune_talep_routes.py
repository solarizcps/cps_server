# -*- coding: utf-8 -*-
"""Numune Talep routes — FAZ-NUMUNE-TALEP-UYGULAMA-1"""
from __future__ import annotations

import os

from flask import abort, flash, jsonify, redirect, render_template, request, send_file

from modules.auth import login_gerekli, yetki_gerekli, yetki_var
from modules.belge import belge_tam_yol, belge_tek, belge_yukle
from modules.nexgen.numune_talep_service import (
    NumuneTalepError,
    belge_id_guncelle,
    durum_etiket,
    gelisme_liste,
    get_talep,
    gonder_arge,
    isleme_al,
    kaydet_taslak,
    liste_bekleyen,
    liste_pazarlama,
    vedat_kaydet,
)


def register_numune_talep_routes(bp, db_factory, kullanici_id_fn, *, renk_kart_fn, cari_liste_fn, tablet_arge_guard):
    """nexgen_bp üzerine Numune Talep route'larını bağlar."""

    def _con():
        return db_factory()

    def _uid():
        return kullanici_id_fn()

    def _err(e: Exception):
        if isinstance(e, NumuneTalepError):
            return jsonify({'ok': False, 'hata': e.message, 'kod': e.kod}), e.status
        return jsonify({'ok': False, 'hata': str(e)}), 500

    def _can_pzm_read():
        return yetki_var('nexgen.plan.view', 'can_view')

    def _can_pzm_write():
        return yetki_var('nexgen.plan.manage', 'can_manage')

    def _can_vedat():
        return yetki_var('nexgen.tablet.view', 'can_view') and tablet_arge_guard()

    def _render_numune_talep_sayfa(*, talep_id: int | None = None, yeni_route: bool = False):
        con = _con()
        try:
            cariler = cari_liste_fn(con)
            talep = None
            duzenlenebilir = True
            if talep_id:
                talep = get_talep(con, talep_id)
                duzenlenebilir = (talep.get('durum') or '').upper() in ('YENI_TALEP', 'TASLAK')
        except NumuneTalepError:
            talep = None
            duzenlenebilir = True
        finally:
            con.close()
        return render_template(
            'nexgen/numune_talep.html',
            active='nexgen',
            cariler=cariler,
            can_manage=_can_pzm_write() and duzenlenebilir,
            talep=talep,
            duzenlenebilir=duzenlenebilir,
            yeni_route=yeni_route,
            oturum_kullanici_id=_uid(),
        )

    @bp.route('/numune-talep/yeni')
    @login_gerekli
    @yetki_gerekli('nexgen.plan.view', 'can_view')
    def numune_talep_yeni_sayfa():
        talep_id = request.args.get('id', type=int)
        return _render_numune_talep_sayfa(talep_id=talep_id, yeni_route=True)

    @bp.route('/numune-talep')
    @login_gerekli
    @yetki_gerekli('nexgen.plan.view', 'can_view')
    def numune_talep_sayfa():
        talep_id = request.args.get('id', type=int)
        return _render_numune_talep_sayfa(talep_id=talep_id, yeni_route=False)

    @bp.route('/api/numune-talep/cariler')
    @login_gerekli
    @yetki_gerekli('nexgen.plan.view', 'can_view')
    def api_nt_cariler():
        q = (request.args.get('q') or '').strip()
        con = _con()
        try:
            return jsonify({'ok': True, 'cariler': cari_liste_fn(con, q or None)})
        finally:
            con.close()

    @bp.route('/api/numune-talep/pazarlamacilar')
    @login_gerekli
    @yetki_gerekli('nexgen.plan.view', 'can_view')
    def api_nt_pazarlamacilar():
        con = _con()
        try:
            rows = con.execute(
                """
                SELECT Id AS id, KullaniciAdi AS kullanici, AdSoyad AS ad
                FROM sistem_kullanici
                WHERE Aktif=1
                ORDER BY AdSoyad, KullaniciAdi
                """
            ).fetchall()
            return jsonify({'ok': True, 'liste': [dict(r) for r in rows]})
        finally:
            con.close()

    @bp.route('/api/numune-talep/renkler')
    @login_gerekli
    @yetki_gerekli('nexgen.plan.view', 'can_view')
    def api_nt_renkler():
        cari_id = request.args.get('cari_id', type=int)
        con = _con()
        try:
            kartlar = renk_kart_fn(con, cari_id)
            out = []
            for k in kartlar:
                out.append({
                    'id': k.get('id'),
                    'kod': k.get('rf_kod'),
                    'ad': k.get('ad'),
                })
            return jsonify({'ok': True, 'renkler': out})
        finally:
            con.close()

    @bp.route('/api/numune-talep/liste')
    @login_gerekli
    @yetki_gerekli('nexgen.plan.view', 'can_view')
    def api_nt_liste():
        con = _con()
        try:
            return jsonify({'ok': True, 'talepler': liste_pazarlama(con, _uid())})
        finally:
            con.close()

    @bp.route('/api/numune-talep/taslak', methods=['POST'])
    @login_gerekli
    @yetki_gerekli('nexgen.plan.manage', 'can_manage')
    def api_nt_taslak():
        payload = request.get_json(silent=True) or {}
        talep_id = payload.get('id') or payload.get('talep_id')
        try:
            tid = int(talep_id) if talep_id else None
        except (TypeError, ValueError):
            tid = None
        con = _con()
        try:
            out = kaydet_taslak(con, payload, _uid(), tid)
            return jsonify({'ok': True, 'talep': out})
        except NumuneTalepError as e:
            return _err(e)
        finally:
            con.close()

    @bp.route('/api/numune-talep/gonder', methods=['POST'])
    @login_gerekli
    @yetki_gerekli('nexgen.plan.manage', 'can_manage')
    def api_nt_gonder():
        payload = request.get_json(silent=True) or {}
        talep_id = payload.get('id') or payload.get('talep_id')
        try:
            tid = int(talep_id) if talep_id else None
        except (TypeError, ValueError):
            tid = None
        con = _con()
        try:
            out = gonder_arge(con, payload, _uid(), tid)
            return jsonify({'ok': True, 'talep': out, 'mesaj': 'Bekleyen Numuneler listesine gönderildi.'})
        except NumuneTalepError as e:
            return _err(e)
        finally:
            con.close()

    @bp.route('/api/numune-talep/gorsel/<int:belge_id>')
    @login_gerekli
    def api_nt_gorsel_goster(belge_id):
        if not (_can_pzm_read() or _can_vedat()):
            abort(403)
        b = belge_tek(belge_id)
        if not b or b['Modul'] != 'nexgen' or b['AltModul'] != 'numune_talep':
            abort(404)
        con = _con()
        try:
            row = con.execute(
                """
                SELECT id FROM nexgen_numune_talep
                WHERE aktif=1 AND (
                    urun_gorsel_belge_id=? OR ref_gorsel_belge_id=? OR vedat_sonuc_gorsel_belge_id=?
                )
                """,
                (belge_id, belge_id, belge_id),
            ).fetchone()
            if not row:
                abort(404)
        finally:
            con.close()
        yol = belge_tam_yol(b)
        if not os.path.exists(yol):
            abort(404)
        return send_file(yol, download_name=b['OrijinalAd'], as_attachment=False)

    @bp.route('/api/numune-talep/<int:talep_id>/gorsel', methods=['POST'])
    @login_gerekli
    def api_nt_gorsel_yukle(talep_id):
        if not (_can_pzm_write() or _can_vedat()):
            abort(403)
        alan = (request.form.get('alan') or 'urun_gorsel_belge_id').strip()
        f = request.files.get('dosya')
        if not f:
            return jsonify({'ok': False, 'hata': 'Dosya gerekli.'}), 400
        con = _con()
        try:
            belge_id = belge_yukle('nexgen', 'numune_talep', talep_id, f, belge_tipi='GORSEL')
            belge_id_guncelle(con, talep_id, alan, belge_id)
            return jsonify({'ok': True, 'belge_id': belge_id})
        except Exception as e:
            return jsonify({'ok': False, 'hata': str(e)}), 400
        finally:
            con.close()

    @bp.route('/tablet/arge/bekleyen-numuneler')
    @login_gerekli
    @yetki_gerekli('nexgen.tablet.view', 'can_view')
    def tablet_bekleyen_numuneler():
        if not tablet_arge_guard():
            abort(403)
        con = _con()
        try:
            liste = liste_bekleyen(con)
        finally:
            con.close()
        return render_template(
            'nexgen/numune_talep_bekleyen.html',
            active='nexgen',
            liste=liste,
        )

    @bp.route('/tablet/arge/numune-talep/<int:talep_id>')
    @login_gerekli
    @yetki_gerekli('nexgen.tablet.view', 'can_view')
    def tablet_numune_talep_vedat(talep_id):
        if not tablet_arge_guard():
            abort(403)
        con = _con()
        try:
            talep = get_talep(con, talep_id)
            if talep.get('durum') == 'BEKLEYEN_NUMUNE':
                flash('Talep henüz işleme alınmadı. Bekleyen Numuneler popup\'ından İşleme Al kullanın.', 'hata')
                return redirect('/nexgen/tablet/arge')
            gelismeler = gelisme_liste(con, talep_id)
        except NumuneTalepError as e:
            flash(e.message, 'hata')
            return redirect('/nexgen/tablet/arge')
        finally:
            con.close()
        return render_template(
            'nexgen/numune_talep_vedat.html',
            active='nexgen',
            talep=talep,
            gelismeler=gelismeler,
            durum_etiket=durum_etiket,
        )

    @bp.route('/api/numune-talep/<int:talep_id>/vedat', methods=['POST'])
    @login_gerekli
    @yetki_gerekli('nexgen.tablet.view', 'can_view')
    def api_nt_vedat_kaydet(talep_id):
        if not tablet_arge_guard():
            abort(403)
        payload = request.get_json(silent=True) or {}
        con = _con()
        try:
            out = vedat_kaydet(con, talep_id, payload)
            return jsonify({'ok': True, 'talep': out})
        except NumuneTalepError as e:
            return _err(e)
        finally:
            con.close()

    @bp.route('/api/numune-talep/bekleyen')
    @login_gerekli
    @yetki_gerekli('nexgen.tablet.view', 'can_view')
    def api_nt_bekleyen():
        if not tablet_arge_guard():
            abort(403)
        filtre = (request.args.get('filtre') or 'bekleyen').strip().lower()
        q = (request.args.get('q') or '').strip()
        con = _con()
        try:
            return jsonify({'ok': True, 'liste': liste_bekleyen(con, filtre=filtre, q=q or None)})
        finally:
            con.close()

    @bp.route('/api/numune-talep/<int:talep_id>')
    @login_gerekli
    @yetki_gerekli('nexgen.tablet.view', 'can_view')
    def api_nt_detay(talep_id):
        if not tablet_arge_guard():
            abort(403)
        con = _con()
        try:
            talep = get_talep(con, talep_id)
            gelismeler = gelisme_liste(con, talep_id)
            return jsonify({'ok': True, 'talep': talep, 'gelismeler': gelismeler})
        except NumuneTalepError as e:
            return _err(e)
        finally:
            con.close()

    @bp.route('/api/numune-talep/<int:talep_id>/isleme-al', methods=['POST'])
    @login_gerekli
    @yetki_gerekli('nexgen.tablet.view', 'can_view')
    def api_nt_isleme_al(talep_id):
        if not tablet_arge_guard():
            abort(403)
        con = _con()
        try:
            out = isleme_al(con, talep_id, _uid())
            return jsonify({
                'ok': True,
                'talep': out,
                'redirect_url': f'/nexgen/tablet/arge/numune-talep/{talep_id}',
            })
        except NumuneTalepError as e:
            return _err(e)
        finally:
            con.close()
