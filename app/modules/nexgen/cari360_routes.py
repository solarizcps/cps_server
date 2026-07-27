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
        except Cari360KartError as e:
            abort(e.kod)
        finally:
            con.close()
        tab = (request.args.get('tab') or 'genel').strip().lower()
        if tab not in ('genel', 'yetkililer'):
            tab = 'genel'
        return render_template(
            'nexgen/cari360_kart.html',
            cari_id=cari_id,
            data=data,
            aktif_tab=tab,
        )

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
