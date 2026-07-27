# -*- coding: utf-8 -*-
"""Cari 360 / Cari Kart route kayıtları.

FAZ-CARI-KART-SHELL-VE-YETKILILER-UI-1
- /cari360/<id> → Cari Kart shell (Genel + Yetkililer)
- Ağır dijital dosya sorgusu bu route'ta çalışmaz.
"""
from __future__ import annotations

from flask import abort, jsonify, render_template, request, session

from modules.auth import login_gerekli, kullanici_yetkileri
from modules.nexgen.cari360_kart_service import Cari360KartError, load_cari_kart
from modules.nexgen.cari360_dosya_service import (
    Cari360DosyaError,
    cari_liste,
    hafiza_liste,
)
from modules.nexgen.cari360_yetki import can_cari360_dosya_ekrani
from modules.nexgen.cari_sorumlu_service import can_view_cari
from modules.nexgen.mo_gorusme_config import GORUSME_TIPLERI, SONUC_TIPLERI
from modules.nexgen.mo_gorusme_service import (
    MoGorusmeError,
    acik_takip_sayisi,
    can_mo_gorusme_yaz,
    gorusme_guncelle,
    gorusme_kaydet,
    list_gorusmeler,
    takip_durum_ayarla,
)


def register_cari360_routes(bp, db_fn, kullanici_id_fn):
    def _yk():
        return kullanici_yetkileri(session.get('kullanici') or {})

    @bp.route('/cari360', strict_slashes=False)
    @login_gerekli
    def cari360_liste_sayfa():
        """Liste (opsiyonel). Trailing slash (/cari360/) 404 olmamalı.

        Yönetim Merkezi Cari Kart linkleri her zaman /cari360/<id> kullanır.
        Boş /cari360/ isteğinde Yönetim cari sekmesine yönlendir.
        """
        from flask import redirect

        # /cari360/ → id yok; kart değil. Yönetim'e dön (404 yerine).
        path = (request.path or '').rstrip('/')
        if path.endswith('/cari360') and request.path.endswith('/'):
            return redirect('/nexgen/yonetim/#cari', code=302)

        if not can_cari360_dosya_ekrani(_yk()):
            # Liste yetkisi yoksa yine Yönetim'e yönlendir (404 değil)
            return redirect('/nexgen/yonetim/#cari', code=302)
        con = db_fn()
        try:
            cariler = cari_liste(con, kullanici_id_fn(), _yk())
        except Cari360DosyaError as e:
            abort(e.kod)
        finally:
            con.close()
        return render_template('nexgen/cari360_liste.html', cariler=cariler)

    @bp.route('/cari360/<int:cari_id>', strict_slashes=False)
    @login_gerekli
    def cari360_dosya_sayfa(cari_id):
        """Cari Kart shell — Genel Bilgiler + Yetkililer."""
        yk = _yk()
        uid = kullanici_id_fn()
        if not uid:
            abort(401)
        con = db_fn()
        try:
            data = load_cari_kart(con, cari_id, uid, yk)
            acik_takip = acik_takip_sayisi(con, cari_id)
        except Cari360KartError as e:
            abort(e.kod)
        finally:
            con.close()
        tab = (request.args.get('tab') or 'genel').strip().lower()
        if tab not in ('genel', 'yetkililer', 'gorusmeler'):
            tab = 'genel'
        return render_template(
            'nexgen/cari360_kart.html',
            cari_id=cari_id,
            data=data,
            aktif_tab=tab,
            acik_takip=acik_takip,
            gorusme_tipleri=GORUSME_TIPLERI,
            sonuc_tipleri=SONUC_TIPLERI,
        )

    @bp.route('/api/cari360/<int:cari_id>/gorusme', methods=['GET'])
    @login_gerekli
    def api_cari360_gorusme_liste(cari_id):
        """Aynı list_gorusmeler servisi — Cari Kart Görüşmeler."""
        yk = _yk()
        uid = kullanici_id_fn()
        con = db_fn()
        try:
            liste = list_gorusmeler(con, cari_id, uid, yk)
            return jsonify({
                'ok': True,
                'liste': liste,
                'acik_takip': acik_takip_sayisi(con, cari_id),
                'can_write': can_mo_gorusme_yaz(con, uid, cari_id, yk),
            })
        except MoGorusmeError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/cari360/<int:cari_id>/gorusme', methods=['POST'])
    @login_gerekli
    def api_cari360_gorusme_kaydet(cari_id):
        """Aynı gorusme_kaydet servisi — tek DB kaydı."""
        yk = _yk()
        uid = kullanici_id_fn()
        payload = request.get_json(silent=True) or {}
        payload['cari_id'] = cari_id
        payload.setdefault('kaynak', 'CARI_KART')
        con = db_fn()
        try:
            kayit = gorusme_kaydet(con, payload, uid, yk)
            return jsonify({'ok': True, 'kayit': kayit, 'mesaj': 'Görüşme kaydı oluşturuldu.'})
        except MoGorusmeError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/cari360/<int:cari_id>/gorusme/<int:gorusme_id>', methods=['POST'])
    @login_gerekli
    def api_cari360_gorusme_guncelle(cari_id, gorusme_id):
        yk = _yk()
        uid = kullanici_id_fn()
        payload = request.get_json(silent=True) or {}
        con = db_fn()
        try:
            kayit = gorusme_guncelle(con, gorusme_id, payload, uid, yk)
            if int(kayit.get('cari_id') or 0) != int(cari_id):
                return jsonify({'ok': False, 'mesaj': 'Başka carinin görüşmesi.'}), 403
            return jsonify({'ok': True, 'kayit': kayit})
        except MoGorusmeError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/cari360/<int:cari_id>/gorusme/<int:gorusme_id>/takip', methods=['POST'])
    @login_gerekli
    def api_cari360_gorusme_takip(cari_id, gorusme_id):
        yk = _yk()
        uid = kullanici_id_fn()
        payload = request.get_json(silent=True) or {}
        durum = payload.get('takip_durumu') or payload.get('durum') or 'TAMAMLANDI'
        con = db_fn()
        try:
            kayit = takip_durum_ayarla(con, gorusme_id, durum, uid, yk)
            if int(kayit.get('cari_id') or 0) != int(cari_id):
                return jsonify({'ok': False, 'mesaj': 'Başka carinin görüşmesi.'}), 403
            return jsonify({'ok': True, 'kayit': kayit})
        except MoGorusmeError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/cari360/<int:cari_id>/hafiza')
    @login_gerekli
    def api_cari360_hafiza(cari_id):
        """Eski hafıza API — Cari Kart shell kullanmaz; geriye uyum."""
        if not can_cari360_dosya_ekrani(_yk()):
            abort(403)
        con = db_fn()
        try:
            if not can_view_cari(con, kullanici_id_fn(), cari_id, _yk()):
                abort(403)
            kategori = (request.args.get('kategori') or 'tumu').strip()
            tarih = (request.args.get('tarih') or 'tumu').strip()
            arama = (request.args.get('q') or '').strip() or None
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
