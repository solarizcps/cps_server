# -*- coding: utf-8 -*-
"""Numune Talep routes — FAZ-NUMUNE-TALEP-UYGULAMA-1"""
from __future__ import annotations

import os

from flask import abort, flash, jsonify, redirect, render_template, request, send_file, session

from modules.auth import login_gerekli, kullanici_yetkileri, yetki_gerekli, yetki_var
from modules.nexgen.cari360_yetki import can_musteri_pazarlama_menu
from modules.belge import belge_tam_yol, belge_tek, belge_yukle
from modules.nexgen.numune_talep_service import (
    NumuneTalepError,
    belge_id_guncelle,
    durum_etiket,
    gelisme_liste,
    get_talep,
    get_takip_liste_readonly,
    gonder_arge,
    isleme_al,
    isleme_al_redirect_url,
    kaydet_taslak,
    liste_bekleyen,
    liste_pazarlama,
    vedat_kaydet,
    DUZENLENEBILIR_DURUMLAR,
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

    def _mo_pazarlamaci_block():
        """MO pazarlamacı Mehmet numune route'larına erişemez."""
        yk = kullanici_yetkileri(session.get('kullanici') or {})
        if can_musteri_pazarlama_menu(yk) and not yetki_var('nexgen.plan.manage', 'can_manage'):
            abort(403)

    @bp.before_request
    def _nt_mo_route_guard():
        # Yalnız Mehmet/PZM /numune-talep* modülü.
        # MO /musteri-pazarlama/numune-* yolları burada 403 olmamalı (legacy 410 ayrı).
        path = request.path or ''
        if '/musteri-pazarlama/' in path:
            return
        if 'numune-talep' in path:
            _mo_pazarlamaci_block()

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
        """Aktif nexgen_cari tam liste — Yönetim SoT (_pzm_aktif_cari_liste).

        FAZ-NEXGEN-NUMUNE-TALEP-CARI-ARAMA-TR-NORMALIZE-FIX-1:
        q parametresi SQL LIKE ile filtrelenmez (ş/s kırığı).
        Arama yalnız frontend'de TR-normalize ile yapılır.
        """
        con = _con()
        try:
            return jsonify({'ok': True, 'cariler': cari_liste_fn(con, None)})
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
            mtt_raw = payload.get('kaynak_mtt_talep_id')
            if mtt_raw not in (None, '', 0, '0') and tid is None:
                from flask import session
                from modules.auth import kullanici_yetkileri
                from modules.nexgen.musteri_temsilcisi_talep_service import (
                    MusteriTemsilcisiTalepError,
                )
                from modules.nexgen.mtt_donusum_service import numune_mtt_ile_kaydet
                yk = kullanici_yetkileri(session.get('kullanici') or {})
                try:
                    out = numune_mtt_ile_kaydet(
                        con, int(mtt_raw), payload, _uid(), yk,
                    )
                    return jsonify(out)
                except MusteriTemsilcisiTalepError as e:
                    return jsonify({
                        'ok': False, 'mesaj': e.mesaj, 'hata': e.mesaj, **e.ekstra,
                    }), e.kod
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
            return jsonify({
                'ok': True,
                'talep': out,
                'arge_test_id': out.get('arge_test_id'),
                'mesaj': 'AR-GE\'ye gönderildi — Renk Merkezi listesine düştü.',
            })
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
    @yetki_gerekli('nexgen.plan.manage', 'can_manage')
    def api_nt_gorsel_yukle(talep_id):
        alan = (request.form.get('alan') or 'urun_gorsel_belge_id').strip()
        if alan not in ('urun_gorsel_belge_id', 'ref_gorsel_belge_id', 'vedat_sonuc_gorsel_belge_id'):
            return jsonify({'ok': False, 'hata': 'Geçersiz alan.'}), 400
        f = request.files.get('dosya')
        if not f:
            return jsonify({'ok': False, 'hata': 'Dosya gerekli.'}), 400
        con = _con()
        try:
            row = con.execute(
                "SELECT id, durum FROM nexgen_numune_talep WHERE id=? AND aktif=1",
                (talep_id,),
            ).fetchone()
            if not row:
                return jsonify({'ok': False, 'hata': 'Talep bulunamadı.'}), 404
            if (row['durum'] or '').upper() not in DUZENLENEBILIR_DURUMLAR:
                return jsonify({'ok': False, 'hata': 'Bu talep düzenlenemez — görsel yüklenemez.'}), 409
            belge_id = belge_yukle('nexgen', 'numune_talep', talep_id, f, belge_tipi='GORSEL')
            belge_id_guncelle(con, talep_id, alan, belge_id)
            return jsonify({'ok': True, 'belge_id': belge_id})
        except NumuneTalepError as e:
            return _err(e)
        except Exception as e:
            return jsonify({'ok': False, 'hata': str(e)}), 400
        finally:
            con.close()

    @bp.route('/numune-talep/bekleyen-numuneler')
    @login_gerekli
    @yetki_gerekli('nexgen.plan.view', 'can_view')
    def pazarlama_bekleyen_numuneler():
        con = _con()
        try:
            liste = liste_bekleyen(con)
        finally:
            con.close()
        return render_template(
            'nexgen/numune_talep_bekleyen.html',
            active='nexgen',
            liste=liste,
            geri_url='/nexgen/pazarlama',
        )

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
            geri_url='/nexgen/tablet/arge',
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

    @bp.route('/api/numune-talep/takip-listesi')
    @login_gerekli
    @yetki_gerekli('nexgen.plan.view', 'can_view')
    def api_nt_takip_liste():
        """Mehmet toplu Numune Takip listesi — yalnız SELECT."""
        filtre = request.args.get('durum') or 'tumu'
        q = request.args.get('q') or request.args.get('arama')
        limit = min(max(request.args.get('limit', 100, type=int), 1), 200)
        offset = max(request.args.get('offset', 0, type=int), 0)
        admin = _can_pzm_write()
        con = _con()
        try:
            return jsonify(get_takip_liste_readonly(
                con, _uid(), admin=admin, filtre=filtre, q=q, limit=limit, offset=offset,
            ))
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
            once = get_talep(con, talep_id)
            zaten = once.get('durum') in ('CALISILIYOR', 'REVIZYONDA')
            out = isleme_al(con, talep_id, _uid())
            redirect_url = isleme_al_redirect_url(out)
            return jsonify({
                'ok': True,
                'talep': out,
                'arge_test_id': out.get('arge_test_id'),
                'talep_kodu': out.get('talep_kodu'),
                'zaten_islemede': zaten,
                'redirect_url': redirect_url,
                'mesaj': (
                    'Zaten işleme alınmış — mevcut AR-GE kaydı açılıyor.'
                    if zaten else
                    'İşleme alındı — mevcut Yeni Renk Çalışması açılıyor.'
                ),
            })
        except NumuneTalepError as e:
            return _err(e)
        finally:
            con.close()
