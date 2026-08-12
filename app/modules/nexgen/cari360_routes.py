# -*- coding: utf-8 -*-
"""Cari 360 / Cari Kart route kayıtları.

FAZ-CARI-KART-SHELL-VE-YETKILILER-UI-1
- /cari360/<id> → Cari Kart shell (Genel + Yetkililer)
- Ağır dijital dosya sorgusu bu route'ta çalışmaz.
"""
from __future__ import annotations

from flask import abort, jsonify, render_template, request, session

from modules.auth import login_gerekli, kullanici_yetkileri
from modules.nexgen.cari360_finans_service import load_cari360_finans
from modules.nexgen.cari360_kart_service import Cari360KartError, load_cari_kart
from modules.nexgen.cari360_dosya_service import (
    Cari360DosyaError,
    cari_liste,
    hafiza_liste,
)
from modules.nexgen.cari360_ops_read_service import (
    Cari360OpsError,
    enrich_gorusmeler_bagli_numuneler,
    enrich_gorusmeler_zincir_flags,
    load_cari360_numuneler,
    load_cari360_onaylar,
    load_cari360_ozet,
    load_cari360_sevkiyatlar,
    load_cari360_siparisler,
    load_cari360_uretim,
    load_cari360_urunler,
)
from modules.nexgen.cari360_relation_policy import (
    clamp_limit,
    clamp_offset,
    parse_iso_date,
    resolve_tek_sorumlu,
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
    'genel', 'siparisler', 'uretim', 'sevkiyatlar', 'urunler',
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
        """Cari Kart shell — operasyon görünümü (read-only ops + mevcut sekmeler).

        Erişim: can_cari360_dosya_ekrani — yalnız cari360.view_own (pazarlamacı) geçemez.
        """
        yk = _yk()
        uid = kullanici_id_fn()
        if not uid:
            abort(401)
        if not can_cari360_dosya_ekrani(yk):
            abort(403)
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
        page_size = max(1, min(int(request.args.get('page_size') or 50), 100))
        page = max(1, int(request.args.get('page') or 1))
        offset = (page - 1) * page_size
        # C360-FILTER-SIPARIS-01/02: filtre parametreleri
        siparis_no = (request.args.get('siparis_no') or '').strip() or None
        tarih_baslangic = (request.args.get('tarih_baslangic') or '').strip() or None
        tarih_bitis = (request.args.get('tarih_bitis') or '').strip() or None
        durum_raw = (request.args.get('durum') or '').strip()
        durumlar = [d.strip() for d in durum_raw.split(',') if d.strip()] if durum_raw else None
        termin_baslangic = (request.args.get('termin_baslangic') or '').strip() or None
        termin_bitis = (request.args.get('termin_bitis') or '').strip() or None
        odeme_raw = (request.args.get('odeme') or '').strip()
        odeme_tipleri = [d.strip() for d in odeme_raw.split(',') if d.strip()] if odeme_raw else None
        pb_raw = (request.args.get('pb') or '').strip()
        para_birimleri = [d.strip() for d in pb_raw.split(',') if d.strip()] if pb_raw else None
        plan_kodu = (request.args.get('plan_kodu') or '').strip() or None
        batch_kodu = (request.args.get('batch_kodu') or '').strip() or None
        sevk_baslangic = (request.args.get('sevk_baslangic') or '').strip() or None
        sevk_bitis = (request.args.get('sevk_bitis') or '').strip() or None
        fiyat_raw = (request.args.get('fiyat_tipi') or '').strip()
        fiyat_tipleri = [d.strip() for d in fiyat_raw.split(',') if d.strip()] if fiyat_raw else None
        numune_raw = (request.args.get('numune') or '').strip()
        numune_durumlari = [d.strip() for d in numune_raw.split(',') if d.strip()] if numune_raw else None

        def _parse_int_opt(key: str):
            raw = (request.args.get(key) or '').strip()
            if not raw:
                return None
            try:
                return int(raw)
            except ValueError:
                return None

        def _parse_float_opt(key: str):
            raw = (request.args.get(key) or '').strip().replace(',', '.')
            if not raw:
                return None
            try:
                return float(raw)
            except ValueError:
                return None

        return _ops_json(
            load_cari360_siparisler, cari_id,
            limit=page_size, offset=offset,
            siparis_no=siparis_no,
            tarih_baslangic=tarih_baslangic,
            tarih_bitis=tarih_bitis,
            durumlar=durumlar,
            termin_baslangic=termin_baslangic,
            termin_bitis=termin_bitis,
            odeme_tipleri=odeme_tipleri,
            vade_min=_parse_int_opt('vade_min'),
            vade_max=_parse_int_opt('vade_max'),
            para_birimleri=para_birimleri,
            toplam_min=_parse_float_opt('toplam_min'),
            toplam_max=_parse_float_opt('toplam_max'),
            plan_kodu=plan_kodu,
            batch_kodu=batch_kodu,
            sevk_baslangic=sevk_baslangic,
            sevk_bitis=sevk_bitis,
            try_min=_parse_float_opt('try_min'),
            try_max=_parse_float_opt('try_max'),
            fiyat_tipleri=fiyat_tipleri,
            fiyat_min=_parse_float_opt('fiyat_min'),
            fiyat_max=_parse_float_opt('fiyat_max'),
            uretilen_kg_min=_parse_float_opt('uretilen_kg_min'),
            uretilen_kg_max=_parse_float_opt('uretilen_kg_max'),
            kalem_min=_parse_int_opt('kalem_min'),
            kalem_max=_parse_int_opt('kalem_max'),
            numune_durumlari=numune_durumlari,
            sevk_kg_min=_parse_float_opt('sevk_kg_min'),
            sevk_kg_max=_parse_float_opt('sevk_kg_max'),
        )

    @bp.route('/api/cari360/<int:cari_id>/ticari-ozet', methods=['GET'])
    @login_gerekli
    def api_cari360_ticari_ozet(cari_id):
        """T4 Ticari Özet — JSON only; yetkisiz 403 JSON."""
        return _ops_json(load_cari360_ticari_ozet, cari_id)

    @bp.route('/api/cari360/<int:cari_id>/uretim', methods=['GET'])
    @login_gerekli
    def api_cari360_uretim(cari_id):
        page = max(1, int(request.args.get('page') or 1))
        page_size = max(1, min(int(request.args.get('page_size') or 20), 100))
        durum_filtre = (request.args.get('durum') or '').strip() or None
        return _ops_json(load_cari360_uretim, cari_id,
                         page=page, page_size=page_size, durum_filtre=durum_filtre)

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
        page = max(1, int(request.args.get('page') or 1))
        page_size = max(1, min(int(request.args.get('page_size') or 10), 100))
        return _ops_json(load_cari360_numuneler, cari_id,
                         page=page, page_size=page_size)

    @bp.route('/api/cari360/<int:cari_id>/tahsilat', methods=['GET'])
    @login_gerekli
    def api_cari360_tahsilat(cari_id):
        """Tahsilat kayıtları — mo_tahsilat_kayit üzerinden."""
        yk = _yk()
        uid = kullanici_id_fn()
        if not uid:
            return jsonify({'ok': False, 'mesaj': 'Oturum gerekli.'}), 401
        con = db_fn()
        try:
            if not can_view_cari(con, uid, cari_id, yk):
                return jsonify({'ok': False, 'mesaj': 'Yetki yok.'}), 403
            row = con.execute('SELECT id FROM nexgen_cari WHERE id=?', (cari_id,)).fetchone()
            if not row:
                return jsonify({'ok': False, 'mesaj': 'Cari bulunamadı.'}), 404

            def _tablo_var(n):
                return bool(con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (n,)
                ).fetchone())

            if not _tablo_var('mo_tahsilat_kayit'):
                return jsonify({'ok': True, 'liste': [], 'ozet': {}})

            rows = con.execute(
                """SELECT tk.id, tk.siparis_id, tk.durum, tk.odeme_tipi,
                          tk.alinan_tarih, tk.alinan_tutar, tk.beklenen_tutar,
                          tk.kalan_tutar, tk.aktif,
                          ps.siparis_no
                   FROM mo_tahsilat_kayit tk
                   LEFT JOIN nexgen_planlama_siparis ps ON ps.id = tk.siparis_id
                   WHERE tk.cari_id=? AND COALESCE(tk.aktif,1)=1
                   ORDER BY COALESCE(tk.alinan_tarih,'') DESC, tk.id DESC""",
                (cari_id,),
            ).fetchall()
            liste = [dict(r) for r in rows]
            toplam_alinan = sum(
                float(r['alinan_tutar'] or 0) for r in liste if r['durum'] == 'ONAYLANDI'
            )
            bekleyen = [r for r in liste if r['durum'] not in ('ONAYLANDI', 'IPTAL', 'REDDEDILDI')]
            son = next((r for r in liste if r['durum'] == 'ONAYLANDI'), None)
            ozet = {
                'toplam_alinan': round(toplam_alinan, 2),
                'bekleyen_adet': len(bekleyen),
                'son_tahsilat_tarihi': (son['alinan_tarih'] if son else None),
                'son_tahsilat_tutari': (float(son['alinan_tutar'] or 0) if son else None),
            }
            return jsonify({'ok': True, 'liste': liste, 'count': len(liste), 'ozet': ozet})
        except Exception as e:
            return jsonify({'ok': False, 'mesaj': str(e)}), 500

    @bp.route('/api/cari360/<int:cari_id>/finans', methods=['GET'])
    @login_gerekli
    def api_cari360_finans(cari_id):
        """Finans sekmesi — gerçek kaynaklardan: tahsilat, vade, çek, legacy bakiye."""
        yk = _yk()
        uid = kullanici_id_fn()
        if not uid:
            return jsonify({'ok': False, 'mesaj': 'Oturum gerekli.'}), 401
        con = db_fn()
        try:
            if not can_view_cari(con, uid, cari_id, yk):
                return jsonify({'ok': False, 'mesaj': 'Yetki yok.'}), 403
            row = con.execute('SELECT id FROM nexgen_cari WHERE id=?', (cari_id,)).fetchone()
            if not row:
                return jsonify({'ok': False, 'mesaj': 'Cari bulunamadı.'}), 404
            data = load_cari360_finans(con, cari_id)
            return jsonify({'ok': True, **data})
        except Exception as e:
            return jsonify({'ok': False, 'mesaj': str(e)}), 500
        finally:
            con.close()

    @bp.route('/api/cari360/<int:cari_id>/onaylar', methods=['GET'])
    @login_gerekli
    def api_cari360_onaylar(cari_id):
        """Onay Merkezi kayıtları — read-only, cari_id filtreli."""
        yk = _yk()
        uid = kullanici_id_fn()
        if not uid:
            return jsonify({'ok': False, 'mesaj': 'Oturum gerekli.'}), 401
        con = db_fn()
        try:
            if not can_view_cari(con, uid, cari_id, yk):
                return jsonify({'ok': False, 'mesaj': 'Yetki yok.'}), 403
            row = con.execute('SELECT id FROM nexgen_cari WHERE id=?', (cari_id,)).fetchone()
            if not row:
                return jsonify({'ok': False, 'mesaj': 'Cari bulunamadı.'}), 404
            limit = max(1, min(int(request.args.get('limit') or 50), 200))
            offset = max(0, int(request.args.get('offset') or 0))
            durum_filtre = (request.args.get('durum') or '').strip() or None
            data = load_cari360_onaylar(
                con, cari_id, uid, yk,
                limit=limit, offset=offset, durum_filtre=durum_filtre,
            )
            return jsonify({'ok': True, **data})
        except Exception as e:
            return jsonify({'ok': False, 'mesaj': str(e)}), 500
        finally:
            con.close()

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
            liste, sm = enrich_gorusmeler_zincir_flags(con, cari_id, liste)
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
                'sorumlu': sm.get('sorumlu'),
                'sorumlu_uyarilari': sm.get('sorumlu_uyarilari') or [],
                'sorumlu_atanmamis': bool(sm.get('sorumlu_atanmamis')),
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
            entity_type = (request.args.get('entity_type') or '').strip() or None
            try:
                date_from = parse_iso_date(request.args.get('date_from'), field='date_from')
                date_to = parse_iso_date(request.args.get('date_to'), field='date_to')
            except ValueError as e:
                return jsonify({'ok': False, 'mesaj': str(e)}), 400
            if date_from and date_to and date_from > date_to:
                return jsonify({
                    'ok': False,
                    'mesaj': 'date_from date_to değerinden büyük olamaz.',
                }), 400
            limit = clamp_limit(request.args.get('limit'), default=50, maximum=200)
            offset = clamp_offset(request.args.get('offset'))
            events, ops_meta = hafiza_liste(
                con, cari_id, uid, _yk(),
                kategori=None if kategori == 'tumu' else kategori,
                tarih_preset=None if tarih == 'tumu' else tarih,
                arama=arama,
                limit=None,  # pagination route tarafında
                return_meta=True,
                date_from=date_from,
                date_to=date_to,
                entity_type=entity_type,
            )
            toplam = len(events)
            page = events[offset:offset + limit]
            has_more = (offset + limit) < toplam
            sm = resolve_tek_sorumlu(con, cari_id)
            # FAZ-3B/3C: mevcut events/count + pagination
            return jsonify({
                'ok': True,
                'events': page,
                'count': len(page),
                'olaylar': page,
                'toplam': toplam,
                'limit': limit,
                'offset': offset,
                'has_more': has_more,
                'zincir_uyari_sayisi': int(ops_meta.get('zincir_uyari_sayisi') or 0),
                'dogrudan_numune_sayisi': int(ops_meta.get('dogrudan_numune_sayisi') or 0),
                'dogrudan_siparis_sayisi': int(ops_meta.get('dogrudan_siparis_sayisi') or 0),
                'sorumlu': sm.get('sorumlu') or ops_meta.get('sorumlu'),
                'sorumlu_uyarilari': sm.get('sorumlu_uyarilari') or ops_meta.get('sorumlu_uyarilari') or [],
                'sorumlu_atanmamis': bool(
                    sm.get('sorumlu_atanmamis')
                    if sm.get('sorumlu') is None
                    else sm.get('sorumlu_atanmamis')
                ),
                'query_stats': ops_meta.get('query_stats') or {},
            })
        except Cari360DosyaError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        except Exception as e:
            return jsonify({'ok': False, 'mesaj': 'Hafıza yüklenemedi.', 'hata': str(e)[:200]}), 500
        finally:
            con.close()
