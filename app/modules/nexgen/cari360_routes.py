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
from modules.nexgen.cari360_ops_read_service import (
    Cari360OpsError,
    enrich_gorusmeler_bagli_numuneler,
    load_cari360_numuneler,
    load_cari360_ozet,
    load_cari360_sevkiyatlar,
    load_cari360_siparisler,
    load_cari360_uretim,
    load_cari360_urunler,
)
from modules.nexgen.cari360_ticari_ozet_service import load_cari360_ticari_ozet
from modules.nexgen.cari360_yetki import can_cari360_dosya_ekrani
from modules.nexgen.cari_sorumlu_service import can_view_cari
from modules.nexgen.mo_gorusme_config import (
    GORUSME_TIPLERI,
    SONRAKI_AKSIYON_ORNEKLERI,
    SONUC_TIPLERI,
)
from modules.nexgen.mo_gorusme_service import (
    MoGorusmeError,
    acik_takip_sayisi,
    can_mo_gorusme_yaz,
    gorusme_guncelle,
    gorusme_kaydet,
    list_gorusmeler,
    takip_durum_ayarla,
)

_CARI360_TABS = (
    'genel', 'yetkililer', 'siparisler', 'uretim', 'sevkiyatlar', 'urunler',
    'numuneler', 'gorusmeler',
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
        """Cari Kart shell — operasyon görünümü (read-only ops + mevcut sekmeler)."""
        yk = _yk()
        uid = kullanici_id_fn()
        if not uid:
            abort(401)
        con = db_fn()
        try:
            data = load_cari_kart(con, cari_id, uid, yk)
            acik_takip = acik_takip_sayisi(con, cari_id)
            yetkili_sayisi = 0
            gorusme_sayisi = 0
            try:
                yetkili_sayisi = int(con.execute(
                    'SELECT COUNT(*) FROM cari_yetkili '
                    'WHERE cari_id=? AND COALESCE(aktif, 1)=1',
                    (cari_id,),
                ).fetchone()[0])
            except Exception:
                yetkili_sayisi = 0
            try:
                gorusme_sayisi = int(con.execute(
                    'SELECT COUNT(*) FROM musteri_operasyon_gorusme '
                    'WHERE cari_id=? AND COALESCE(aktif, 1)=1',
                    (cari_id,),
                ).fetchone()[0])
            except Exception:
                gorusme_sayisi = 0
            numune_sayisi = 0
            try:
                numune_sayisi = int(con.execute(
                    'SELECT COUNT(*) FROM nexgen_numune_talep '
                    'WHERE cari_id=? AND COALESCE(aktif, 1)=1',
                    (cari_id,),
                ).fetchone()[0])
            except Exception:
                numune_sayisi = 0
        except Cari360KartError as e:
            abort(e.kod)
        finally:
            con.close()
        tab = (request.args.get('tab') or 'genel').strip().lower()
        if tab not in _CARI360_TABS:
            tab = 'genel'
        return render_template(
            'nexgen/cari360_kart.html',
            cari_id=cari_id,
            data=data,
            aktif_tab=tab,
            acik_takip=acik_takip,
            yetkili_sayisi=yetkili_sayisi,
            gorusme_sayisi=gorusme_sayisi,
            numune_sayisi=numune_sayisi,
            gorusme_tipleri=GORUSME_TIPLERI,
            sonuc_tipleri=SONUC_TIPLERI,
            sonraki_aksiyon_ornekleri=SONRAKI_AKSIYON_ORNEKLERI,
        )

    def _ops_json(fn, cari_id, **kwargs):
        """Read-only ops API — yetki + JSON hata (HTML değil)."""
        yk = _yk()
        uid = kullanici_id_fn()
        if not uid:
            return jsonify({'ok': False, 'mesaj': 'Oturum gerekli.'}), 401
        con = db_fn()
        try:
            data = fn(con, cari_id, uid, yk, **kwargs)
            return jsonify({'ok': True, **data})
        except Cari360OpsError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        except Exception as e:
            return jsonify({
                'ok': False,
                'mesaj': 'Operasyon verisi yüklenemedi.',
                'hata': str(e)[:200],
            }), 500
        finally:
            con.close()

    @bp.route('/api/cari360/<int:cari_id>/ozet', methods=['GET'])
    @login_gerekli
    def api_cari360_ozet(cari_id):
        return _ops_json(load_cari360_ozet, cari_id)

    @bp.route('/api/cari360/<int:cari_id>/siparisler', methods=['GET'])
    @login_gerekli
    def api_cari360_siparisler(cari_id):
        return _ops_json(load_cari360_siparisler, cari_id)

    @bp.route('/api/cari360/<int:cari_id>/ticari-ozet', methods=['GET'])
    @login_gerekli
    def api_cari360_ticari_ozet(cari_id):
        """T4 Ticari Özet — JSON only; yetkisiz 403 JSON."""
        return _ops_json(load_cari360_ticari_ozet, cari_id)

    @bp.route('/api/cari360/<int:cari_id>/uretim', methods=['GET'])
    @login_gerekli
    def api_cari360_uretim(cari_id):
        return _ops_json(load_cari360_uretim, cari_id)

    @bp.route('/api/cari360/<int:cari_id>/sevkiyatlar', methods=['GET'])
    @login_gerekli
    def api_cari360_sevkiyatlar(cari_id):
        return _ops_json(load_cari360_sevkiyatlar, cari_id)

    @bp.route('/api/cari360/<int:cari_id>/urunler', methods=['GET'])
    @login_gerekli
    def api_cari360_urunler(cari_id):
        return _ops_json(load_cari360_urunler, cari_id)

    @bp.route('/api/cari360/<int:cari_id>/numuneler', methods=['GET'])
    @login_gerekli
    def api_cari360_numuneler(cari_id):
        return _ops_json(load_cari360_numuneler, cari_id)

    @bp.route('/api/cari360/<int:cari_id>/gorusme', methods=['GET'])
    @login_gerekli
    def api_cari360_gorusme_liste(cari_id):
        """Aynı list_gorusmeler servisi — Cari Kart Görüşmeler."""
        yk = _yk()
        uid = kullanici_id_fn()
        if not uid:
            return jsonify({'ok': False, 'mesaj': 'Oturum gerekli.'}), 401
        con = db_fn()
        try:
            if not can_view_cari(con, uid, cari_id, yk):
                return jsonify({'ok': False, 'mesaj': 'Bu cari için görüntüleme yetkiniz yok.'}), 403
            row = con.execute(
                'SELECT id FROM nexgen_cari WHERE id=?', (cari_id,),
            ).fetchone()
            if not row:
                return jsonify({'ok': False, 'mesaj': 'Cari bulunamadı.'}), 404
            liste = list_gorusmeler(con, cari_id, uid, yk)
            liste = enrich_gorusmeler_bagli_numuneler(con, cari_id, liste)
            gorusme_sayisi = int(con.execute(
                'SELECT COUNT(*) FROM musteri_operasyon_gorusme '
                'WHERE cari_id=? AND COALESCE(aktif, 1)=1',
                (cari_id,),
            ).fetchone()[0])
            return jsonify({
                'ok': True,
                'liste': liste,
                'count': gorusme_sayisi,
                'acik_takip': acik_takip_sayisi(con, cari_id),
                'can_write': can_mo_gorusme_yaz(con, uid, cari_id, yk),
            })
        except MoGorusmeError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        except Exception as e:
            return jsonify({
                'ok': False,
                'mesaj': 'Görüşmeler yüklenemedi.',
                'hata': str(e)[:200],
            }), 500
        finally:
            con.close()

    @bp.route('/api/cari360/<int:cari_id>/gorusme', methods=['POST'])
    @login_gerekli
    def api_cari360_gorusme_kaydet(cari_id):
        """Aynı gorusme_kaydet servisi — tek DB kaydı. kullanici_id oturumdan."""
        yk = _yk()
        uid = kullanici_id_fn()
        if not uid:
            return jsonify({'ok': False, 'mesaj': 'Oturum gerekli.'}), 401
        payload = request.get_json(silent=True) or {}
        # Frontend kullanıcı spoof yok sayılır
        payload.pop('kullanici_id', None)
        payload.pop('created_by', None)
        payload.pop('olusturan_kullanici_id', None)
        payload['cari_id'] = cari_id
        payload.setdefault('kaynak', 'CARI_KART')
        con = db_fn()
        try:
            row = con.execute(
                'SELECT id FROM nexgen_cari WHERE id=?', (cari_id,),
            ).fetchone()
            if not row:
                return jsonify({'ok': False, 'mesaj': 'Cari bulunamadı.'}), 404
            kayit = gorusme_kaydet(con, payload, uid, yk)
            return jsonify({'ok': True, 'kayit': kayit, 'mesaj': 'Görüşme kaydı oluşturuldu.'})
        except MoGorusmeError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        except Exception as e:
            return jsonify({'ok': False, 'mesaj': 'Görüşme kaydedilemedi.', 'hata': str(e)[:200]}), 500
        finally:
            con.close()

    @bp.route('/api/cari360/<int:cari_id>/gorusme/<int:gorusme_id>', methods=['POST'])
    @login_gerekli
    def api_cari360_gorusme_guncelle(cari_id, gorusme_id):
        yk = _yk()
        uid = kullanici_id_fn()
        if not uid:
            return jsonify({'ok': False, 'mesaj': 'Oturum gerekli.'}), 401
        payload = request.get_json(silent=True) or {}
        payload.pop('kullanici_id', None)
        payload.pop('created_by', None)
        con = db_fn()
        try:
            from modules.nexgen.mo_gorusme_service import gorusme_detay
            mevcut = gorusme_detay(con, gorusme_id, uid, yk)
            if int(mevcut.get('cari_id') or 0) != int(cari_id):
                return jsonify({'ok': False, 'mesaj': 'Başka carinin görüşmesi.'}), 403
            kayit = gorusme_guncelle(con, gorusme_id, payload, uid, yk)
            return jsonify({'ok': True, 'kayit': kayit})
        except MoGorusmeError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        except Exception as e:
            return jsonify({'ok': False, 'mesaj': 'Görüşme güncellenemedi.', 'hata': str(e)[:200]}), 500
        finally:
            con.close()

    @bp.route('/api/cari360/<int:cari_id>/gorusme/<int:gorusme_id>/takip', methods=['POST'])
    @login_gerekli
    def api_cari360_gorusme_takip(cari_id, gorusme_id):
        yk = _yk()
        uid = kullanici_id_fn()
        if not uid:
            return jsonify({'ok': False, 'mesaj': 'Oturum gerekli.'}), 401
        payload = request.get_json(silent=True) or {}
        durum = payload.get('takip_durumu') or payload.get('durum') or 'TAMAMLANDI'
        con = db_fn()
        try:
            from modules.nexgen.mo_gorusme_service import gorusme_detay
            mevcut = gorusme_detay(con, gorusme_id, uid, yk)
            if int(mevcut.get('cari_id') or 0) != int(cari_id):
                return jsonify({'ok': False, 'mesaj': 'Başka carinin görüşmesi.'}), 403
            kayit = takip_durum_ayarla(con, gorusme_id, durum, uid, yk)
            return jsonify({
                'ok': True,
                'kayit': kayit,
                'acik_takip': acik_takip_sayisi(con, cari_id),
            })
        except MoGorusmeError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        except Exception as e:
            return jsonify({'ok': False, 'mesaj': 'Takip güncellenemedi.', 'hata': str(e)[:200]}), 500
        finally:
            con.close()

    @bp.route('/api/cari360/<int:cari_id>/hafiza')
    @login_gerekli
    def api_cari360_hafiza(cari_id):
        """Federasyon hafıza — Cari Kart Son Hareketler + Tümünü Gör (JSON)."""
        con = db_fn()
        try:
            uid = kullanici_id_fn()
            if not uid:
                return jsonify({'ok': False, 'mesaj': 'Oturum gerekli.'}), 401
            if not can_view_cari(con, uid, cari_id, _yk()):
                return jsonify({'ok': False, 'mesaj': 'Bu cari için görüntüleme yetkiniz yok.'}), 403
            nc = con.execute('SELECT id FROM nexgen_cari WHERE id=?', (cari_id,)).fetchone()
            if not nc:
                return jsonify({'ok': False, 'mesaj': 'Cari bulunamadı.'}), 404
            kategori = (request.args.get('kategori') or 'tumu').strip()
            tarih = (request.args.get('tarih') or 'tumu').strip()
            arama = (request.args.get('q') or '').strip() or None
            lim_raw = (request.args.get('limit') or '').strip()
            limit = int(lim_raw) if lim_raw.isdigit() else None
            events = hafiza_liste(
                con, cari_id, uid, _yk(),
                kategori=None if kategori == 'tumu' else kategori,
                tarih_preset=None if tarih == 'tumu' else tarih,
                arama=arama,
                limit=limit,
            )
            return jsonify({'ok': True, 'events': events, 'count': len(events)})
        except Cari360DosyaError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        except Exception as e:
            return jsonify({'ok': False, 'mesaj': 'Hafıza yüklenemedi.', 'hata': str(e)[:200]}), 500
        finally:
            con.close()
