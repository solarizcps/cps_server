# -*- coding: utf-8 -*-
"""MÜŞTERİ OPERASYONU ana ekran route kayıtları."""
from __future__ import annotations

from flask import abort, jsonify, render_template, request, session

from modules.auth import login_gerekli, kullanici_yetkileri
from modules.nexgen.cari360_yetki import can_cari360_view_all, can_musteri_pazarlama_menu
from modules.nexgen.cari_sorumlu_service import can_mo_view_cari
from modules.nexgen.mo_gorusme_config import GORUSME_TIPLERI, GORUSME_TIPLERI_ALL, ONCELIKLER, SONUC_TIPLERI
from modules.nexgen.mo_gorusme_service import (
    MoGorusmeError,
    acik_takip_sayisi,
    can_mo_gorusme_yaz,
    can_mo_gorusme_yaz_aday,
    gorusme_guncelle,
    gorusme_kaydet,
    list_gorusmeler,
    sorumlu_pazarlamaci_adi,
    takip_durum_ayarla,
)
from modules.nexgen.musteri_aday_service import (
    DURUM_ADAY,
    MusteriAdayError,
    aday_havuz_liste,
    aday_iptal_et,
    aday_kart_detay,
    aday_guncelle,
    aday_ve_ilk_gorusme_kaydet,
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
    cari_tahsilat_listele,
    kayit_detay,
    onaya_gonder as tahsilat_onaya_gonder,
    taslak_kaydet as tahsilat_taslak_kaydet,
)
from modules.nexgen.mo_tahsilat_sevk_service import tahsilat_sevk_adaylari
from modules.nexgen.mo_tahsilat_config import (
    KAYIT_DURUM_ISTISNA_ONAY_BEKLIYOR,
    KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR,
)


def _enrich_tahsilat_sevkiyat_secim(con, sevkiyatlar: list[dict]) -> list[dict]:
    """Response mapping: seçim engeli etiketleri için meta alanlar."""
    if not sevkiyatlar:
        return sevkiyatlar
    tbl = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mo_tahsilat_kayit'"
    ).fetchone()
    if not tbl:
        return sevkiyatlar
    for s in sevkiyatlar:
        if s.get('onay_bekleyen_tahsilat') is None:
            sid = int(s.get('sevkiyat_id') or 0)
            row = con.execute(
                """
                SELECT COUNT(*) AS c FROM mo_tahsilat_kayit
                WHERE sevkiyat_id=? AND aktif=1
                  AND durum IN (?, ?)
                """,
                (sid, KAYIT_DURUM_YONETIM_ONAY_BEKLIYOR, KAYIT_DURUM_ISTISNA_ONAY_BEKLIYOR),
            ).fetchone()
            s['onay_bekleyen_adet'] = int(row['c'] or 0) if row else 0
            s['onay_bekleyen_tahsilat'] = s['onay_bekleyen_adet'] > 0
        if 'secilebilir' not in s:
            kalan = s.get('kalan_fx', s.get('kalan'))
            s['secilebilir'] = bool(
                s.get('tahsilata_uygun')
                and not s.get('kur_hesap_hatasi')
                and kalan is not None
                and float(kalan) > 0.009
            )
    return sevkiyatlar


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
        from flask import request as _req
        u, yk = _yetki_kontrol()
        con = db_fn()
        try:
            uid = kullanici_id_fn()
            seen = session.get('mtt_ux_karar_seen')
            ozet = dashboard_ozet(con, uid, yk, karar_seen_ts=seen)
            from modules.nexgen.musteri_pazarlama_service import dashboard_v2
            v2 = dashboard_v2(con, uid, yk)
            from modules.nexgen.onay_service import (
                pazarlamaci_karar_listele,
                pazarlamaci_okunmamis_karar_sayisi,
            )
            talep_sonuclari = pazarlamaci_karar_listele(con, uid, limit=30)
            okunmamis = pazarlamaci_okunmamis_karar_sayisi(con, uid, seen)
            popup_karar = None
            if okunmamis > 0:
                yeniler = pazarlamaci_karar_listele(con, uid, limit=1, after_ts=seen)
                popup_karar = yeniler[0] if yeniler else None
            # Revizyon parametresi: bildirimden "KAYDI AÇ" tıklandığında
            t_revizyon_id = None
            _rv = _req.args.get('t_revizyon', '').strip()
            if _rv and _rv.isdigit():
                _rv_int = int(_rv)
                # Güvenlik: yalnız Erhan'ın kendi kaydı
                _rv_row = con.execute(
                    "SELECT id, cari_id, kayit_kodu, durum FROM mo_tahsilat_kayit "
                    "WHERE id=? AND olusturan_id=?",
                    (_rv_int, int(uid)),
                ).fetchone()
                if _rv_row and _rv_row['durum'] == 'REVIZYON_ISTENDI':
                    t_revizyon_id = _rv_int
        finally:
            con.close()
        return render_template(
            'nexgen/musteri_pazarlama.html',
            active='nexgen',
            ozet=ozet,
            v2=v2,
            kullanici_ad=u.get('KullaniciAdi') or '',
            gorusme_tipleri=GORUSME_TIPLERI,
            gorusme_tipleri_all=GORUSME_TIPLERI_ALL,
            sonuc_tipleri=SONUC_TIPLERI,
            oncelikler=ONCELIKLER,
            talep_sonuclari=talep_sonuclari,
            mp_karar_okunmamis=okunmamis,
            mp_popup_karar=popup_karar,
            t_revizyon_id=t_revizyon_id,
        )

    @bp.route('/api/musteri-pazarlama/ozet')
    @login_gerekli
    def api_musteri_pazarlama_ozet():
        u, yk = _yetki_kontrol()
        con = db_fn()
        try:
            seen = session.get('mtt_ux_karar_seen')
            return jsonify({
                'ok': True,
                **dashboard_ozet(con, kullanici_id_fn(), yk, karar_seen_ts=seen),
            })
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/talep-sonuclari', methods=['GET'])
    @login_gerekli
    def api_musteri_pazarlama_talep_sonuclari():
        _yetki_kontrol()
        con = db_fn()
        try:
            from modules.nexgen.onay_service import (
                pazarlamaci_karar_listele,
                pazarlamaci_okunmamis_karar_sayisi,
            )
            uid = kullanici_id_fn()
            seen = session.get('mtt_ux_karar_seen')
            liste = pazarlamaci_karar_listele(con, uid, limit=30)
            return jsonify({
                'ok': True,
                'liste': liste,
                'okunmamis': pazarlamaci_okunmamis_karar_sayisi(con, uid, seen),
            })
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/bildirimler', methods=['GET'])
    @login_gerekli
    def api_musteri_pazarlama_bildirimler():
        _yetki_kontrol()
        con = db_fn()
        try:
            from modules.nexgen.onay_service import pazarlamaci_bildirimler
            uid = kullanici_id_fn()
            liste = pazarlamaci_bildirimler(con, uid, limit=15)
            resp = jsonify({'ok': True, 'liste': liste, 'toplam': len(liste)})
            resp.headers['Cache-Control'] = 'no-store'
            return resp
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/dashboard-v2', methods=['GET'])
    @login_gerekli
    def api_musteri_pazarlama_dashboard_v2():
        """ERHAN UI-3A — read-only finans/tahsilat/çek/üretim/KPI paketi."""
        u, yk = _yetki_kontrol()
        con = db_fn()
        try:
            from modules.nexgen.musteri_pazarlama_service import dashboard_v2
            uid = kullanici_id_fn()
            data = dashboard_v2(con, uid, yk)
            return jsonify({'ok': True, **data})
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/karar-okundu', methods=['POST'])
    @login_gerekli
    def api_musteri_pazarlama_karar_okundu():
        _yetki_kontrol()
        from datetime import datetime as _dt
        session['mtt_ux_karar_seen'] = _dt.now().strftime('%Y-%m-%d %H:%M:%S')
        session.modified = True
        return jsonify({'ok': True, 'seen': session['mtt_ux_karar_seen']})

    @bp.route('/api/musteri-pazarlama/mtt/<int:talep_id>', methods=['GET'])
    @login_gerekli
    def api_mo_mtt_readonly(talep_id):
        """MO Talebi Aç — kendi oluşturduğu MTT özeti (yazma/aksiyon yok)."""
        u, yk = _yetki_kontrol()
        from modules.nexgen.musteri_temsilcisi_talep_service import (
            MusteriTemsilcisiTalepError,
            talep_detay_getir,
        )
        con = db_fn()
        try:
            kayit = talep_detay_getir(con, talep_id, kullanici_id=kullanici_id_fn())
            uid = int(kullanici_id_fn() or 0)
            olusturan = int(kayit.get('olusturan_kullanici_id') or 0)
            if olusturan != uid and not can_cari360_view_all(yk):
                return jsonify({
                    'ok': False,
                    'mesaj': 'Talep kaydı bulunamadı veya artık erişilemiyor.',
                }), 404
            return jsonify({'ok': True, 'kayit': kayit})
        except MusteriTemsilcisiTalepError as e:
            kod = e.kod if e.kod in (404, 403) else 404
            return jsonify({
                'ok': False,
                'mesaj': 'Talep kaydı bulunamadı veya artık erişilemiyor.',
            }), kod
        finally:
            con.close()

    @bp.route('/musteri-pazarlama/ajanda')
    @login_gerekli
    def musteri_pazarlama_ajanda_sayfa():
        from datetime import date as _date
        from modules.nexgen.mo_ajanda_service import mo_ajanda_cross_hedef_kullanici_id
        u, yk = _yetki_kontrol()
        hafta_arg = (request.args.get('hafta') or '').strip()
        hafta_ref = None
        if hafta_arg:
            try:
                hafta_ref = _date.fromisoformat(hafta_arg[:10])
            except ValueError:
                hafta_ref = None
        uid = kullanici_id_fn()
        con = db_fn()
        try:
            from modules.nexgen.musteri_pazarlama_service import ajanda_sayfa_verisi
            cross_hedef = mo_ajanda_cross_hedef_kullanici_id(uid, yk)
            hedef_uid = cross_hedef
            ajanda_readonly = cross_hedef is not None
            aj_veri = ajanda_sayfa_verisi(
                con, uid, yk, hafta_ref=hafta_ref, hedef_kullanici_id=cross_hedef,
            )
        finally:
            con.close()
        return render_template(
            'nexgen/musteri_pazarlama_ajanda.html',
            active='nexgen',
            aj=aj_veri,
            kullanici_ad=u.get('KullaniciAdi') or '',
            gorusme_tipleri_all=GORUSME_TIPLERI_ALL,
            hedef_kullanici_id=hedef_uid,
            ajanda_readonly=ajanda_readonly,
        )

    @bp.route('/api/musteri-pazarlama/ajanda', methods=['GET'])
    @login_gerekli
    def api_mo_ajanda_liste():
        _yetki_kontrol()
        filtre = (request.args.get('filtre') or 'bugun').strip().lower()
        bas = (request.args.get('bas') or '').strip()
        bit = (request.args.get('bit') or '').strip()
        uid = kullanici_id_fn()
        yk = kullanici_yetkileri(session.get('kullanici') or {})
        from modules.nexgen.mo_ajanda_service import mo_ajanda_cross_hedef_kullanici_id
        cross_hedef = mo_ajanda_cross_hedef_kullanici_id(uid, yk)
        hedef_raw = (request.args.get('hedef_kullanici_id') or '').strip()
        if cross_hedef is not None:
            hedef_uid = cross_hedef
        elif hedef_raw.isdigit():
            hedef_uid = int(hedef_raw)
        else:
            hedef_uid = None
        con = db_fn()
        try:
            if bas and bit:
                from modules.nexgen.musteri_pazarlama_service import ajanda_tarih_araligi_listele
                from modules.nexgen.mo_ajanda_service import MoAjandaError
                try:
                    liste = ajanda_tarih_araligi_listele(
                        con, uid, yk, bas, bit, hedef_kullanici_id=hedef_uid,
                    )
                except MoAjandaError as e:
                    return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
                return jsonify({
                    'ok': True,
                    'liste': liste,
                    'bas': bas,
                    'bit': bit,
                    'hedef_kullanici_id': hedef_uid,
                })
            from modules.nexgen.mo_ajanda_service import ajanda_listele, MoAjandaError
            try:
                liste = ajanda_listele(con, uid, yk, filtre=filtre, hedef_kullanici_id=hedef_uid)
            except MoAjandaError as e:
                return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
            return jsonify({'ok': True, 'liste': liste, 'filtre': filtre,
                            'hedef_kullanici_id': hedef_uid})
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/ajanda', methods=['POST'])
    @login_gerekli
    def api_mo_ajanda_olustur():
        _yetki_kontrol()
        payload = request.get_json(silent=True) or {}
        uid = kullanici_id_fn()
        yk = kullanici_yetkileri(session.get('kullanici') or {})
        con = db_fn()
        try:
            from modules.nexgen.mo_ajanda_service import MoAjandaError, ajanda_olustur
            sonuc = ajanda_olustur(con, payload, uid, yk)
            return jsonify(sonuc)
        except MoAjandaError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/ajanda/zorunlu-sonuc', methods=['GET'])
    @login_gerekli
    def api_mo_ajanda_zorunlu_sonuc():
        u, yk = _yetki_kontrol()
        con = db_fn()
        try:
            from modules.nexgen.musteri_pazarlama_service import _ajanda_zorunlu_gate_items
            items = _ajanda_zorunlu_gate_items(con, kullanici_id_fn(), yk)
            return jsonify({'ok': True, 'kayitlar': items, 'zorunlu_sonuc_gate': items})
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/ajanda/<int:ajanda_id>/iptal', methods=['POST'])
    @login_gerekli
    def api_mo_ajanda_iptal(ajanda_id):
        _yetki_kontrol()
        uid = kullanici_id_fn()
        yk = kullanici_yetkileri(session.get('kullanici') or {})
        con = db_fn()
        try:
            from modules.nexgen.mo_ajanda_service import MoAjandaError, ajanda_iptal
            sonuc = ajanda_iptal(con, ajanda_id, uid, yk)
            return jsonify(sonuc)
        except MoAjandaError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/gorusme', methods=['POST'])
    @login_gerekli
    def api_mo_gorusme_kaydet():
        """Görüşme (+ opsiyonel MTT) tek transaction — FAZ F3."""
        _yetki_kontrol()
        payload = request.get_json(silent=True) or {}
        yk = kullanici_yetkileri(session.get('kullanici') or {})
        uid = kullanici_id_fn()
        con = db_fn()
        try:
            from modules.nexgen.musteri_temsilcisi_talep_service import (
                MusteriTemsilcisiTalepError,
                kaydet_gorusme_opsiyonel_talep,
            )
            sonuc = kaydet_gorusme_opsiyonel_talep(con, payload, uid, yk)
            return jsonify(sonuc)
        except MusteriTemsilcisiTalepError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj, **e.ekstra}), e.kod
        except MusteriAdayError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        except MoGorusmeError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        except Exception as e:
            from modules.nexgen.mo_ajanda_service import MoAjandaError
            if isinstance(e, MoAjandaError):
                return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
            raise
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/aday-ilk-gorusme', methods=['POST'])
    @login_gerekli
    def api_mo_aday_ilk_gorusme():
        """Yeni aday + ilk görüşme (+ opsiyonel MTT) — orchestrator."""
        _yetki_kontrol()
        payload = request.get_json(silent=True) or {}
        yk = kullanici_yetkileri(session.get('kullanici') or {})
        uid = kullanici_id_fn()
        con = db_fn()
        try:
            from modules.nexgen.musteri_temsilcisi_talep_service import (
                MusteriTemsilcisiTalepError,
                kaydet_gorusme_opsiyonel_talep,
            )
            payload = dict(payload)
            payload['yeni_musteri'] = True
            sonuc = kaydet_gorusme_opsiyonel_talep(con, payload, uid, yk)
            return jsonify(sonuc)
        except MusteriTemsilcisiTalepError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj, **e.ekstra}), e.kod
        except MusteriAdayError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        except MoGorusmeError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/adaylar')
    @login_gerekli
    def api_mo_adaylar_liste():
        """Yeni Müşteriler havuzu — varsayılan yalnız ADAY."""
        _yetki_kontrol()
        durum = (request.args.get('durum') or DURUM_ADAY).strip().upper() or DURUM_ADAY
        if durum == 'TUMU':
            durum = None
        con = db_fn()
        try:
            yk = kullanici_yetkileri(session.get('kullanici') or {})
            liste = aday_havuz_liste(con, kullanici_id_fn(), yk, durum=durum)
            return jsonify({'ok': True, 'liste': liste, 'entity_type': 'ADAY'})
        except MusteriAdayError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/aday/<int:aday_id>')
    @login_gerekli
    def api_mo_aday_kart(aday_id):
        _yetki_kontrol()
        con = db_fn()
        try:
            yk = kullanici_yetkileri(session.get('kullanici') or {})
            kart = aday_kart_detay(con, aday_id, kullanici_id_fn(), yk)
            return jsonify({'ok': True, 'kart': kart, 'entity_type': 'ADAY'})
        except MusteriAdayError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/aday/<int:aday_id>', methods=['PATCH', 'POST'])
    @login_gerekli
    def api_mo_aday_guncelle(aday_id):
        _yetki_kontrol()
        payload = request.get_json(silent=True) or {}
        con = db_fn()
        try:
            yk = kullanici_yetkileri(session.get('kullanici') or {})
            if (payload.get('aksiyon') or '').upper() == 'IPTAL':
                kayit = aday_iptal_et(con, aday_id, kullanici_id_fn(), yk)
                return jsonify({'ok': True, 'aday': kayit, 'mesaj': 'Aday iptal edildi.'})
            kayit = aday_guncelle(con, aday_id, payload, kullanici_id_fn(), yk)
            return jsonify({'ok': True, 'aday': kayit, 'mesaj': 'Aday bilgileri güncellendi.'})
        except MusteriAdayError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/aday/<int:aday_id>/iptal', methods=['POST'])
    @login_gerekli
    def api_mo_aday_iptal(aday_id):
        _yetki_kontrol()
        con = db_fn()
        try:
            yk = kullanici_yetkileri(session.get('kullanici') or {})
            kayit = aday_iptal_et(con, aday_id, kullanici_id_fn(), yk)
            return jsonify({'ok': True, 'aday': kayit, 'mesaj': 'Aday iptal edildi.'})
        except MusteriAdayError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/gorusme/<int:gorusme_id>', methods=['POST', 'PUT', 'PATCH'])
    @login_gerekli
    def api_mo_gorusme_guncelle(gorusme_id):
        _yetki_kontrol()
        payload = request.get_json(silent=True) or {}
        con = db_fn()
        try:
            kayit = gorusme_guncelle(
                con, gorusme_id, payload, kullanici_id_fn(),
                kullanici_yetkileri(session.get('kullanici') or {}),
            )
            return jsonify({'ok': True, 'kayit': kayit, 'mesaj': 'Görüşme güncellendi.'})
        except MoGorusmeError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/gorusme/<int:gorusme_id>/takip', methods=['POST'])
    @login_gerekli
    def api_mo_gorusme_takip(gorusme_id):
        _yetki_kontrol()
        payload = request.get_json(silent=True) or {}
        durum = payload.get('takip_durumu') or payload.get('durum') or 'TAMAMLANDI'
        con = db_fn()
        try:
            kayit = takip_durum_ayarla(
                con, gorusme_id, durum, kullanici_id_fn(),
                kullanici_yetkileri(session.get('kullanici') or {}),
            )
            return jsonify({'ok': True, 'kayit': kayit, 'mesaj': 'Takip durumu güncellendi.'})
        except MoGorusmeError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/gorusme')
    @login_gerekli
    def api_mo_gorusme_liste():
        _yetki_kontrol()
        cari_id = request.args.get('cari_id', type=int)
        aday_id = request.args.get('aday_id', type=int) or request.args.get('musteri_aday_id', type=int)
        if not cari_id and not aday_id:
            return jsonify({'ok': False, 'mesaj': 'cari_id veya aday_id zorunlu.'}), 400
        con = db_fn()
        try:
            yk = kullanici_yetkileri(session.get('kullanici') or {})
            uid = kullanici_id_fn()
            from modules.nexgen.musteri_temsilcisi_talep_service import (
                gorusmelere_talep_ozeti_ekle,
            )
            if aday_id:
                liste = list_gorusmeler(
                    con, None, uid, yk, musteri_aday_id=aday_id,
                )
                liste = gorusmelere_talep_ozeti_ekle(con, liste)
                return jsonify({
                    'ok': True,
                    'liste': liste,
                    'entity_type': 'ADAY',
                    'aday_id': aday_id,
                    'sorumlu_pazarlamaci': None,
                    'acik_takip': 0,
                    'can_write': can_mo_gorusme_yaz_aday(con, uid, aday_id, yk),
                })
            liste = list_gorusmeler(con, cari_id, uid, yk)
            liste = gorusmelere_talep_ozeti_ekle(con, liste)
            sorumlu = sorumlu_pazarlamaci_adi(con, cari_id)
            return jsonify({
                'ok': True,
                'liste': liste,
                'entity_type': 'CARI',
                'cari_id': cari_id,
                'sorumlu_pazarlamaci': sorumlu,
                'acik_takip': acik_takip_sayisi(con, cari_id),
                'can_write': can_mo_gorusme_yaz(con, uid, cari_id, yk),
            })
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
        """Eski doğrudan MO numune taslak yazımı — V1 kapalı (410)."""
        _yetki_kontrol()
        return jsonify({
            'ok': False,
            'mesaj': (
                'Bu yol kapatıldı. Numune talebini '
                'POST /nexgen/api/musteri-pazarlama/numune-mtt-onaya ile '
                'Yönetim Onay Merkezi akışına gönderin.'
            ),
            'kod': 'LEGACY_MO_NUMUNE_TASLAK_KAPALI',
        }), 410

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
        """Eski doğrudan numune→onay_talep yolu — popup artık kullanmaz (410)."""
        _yetki_kontrol()
        return jsonify({
            'ok': False,
            'mesaj': (
                'Bu yol kapatıldı. Numune talebini Yönetim Onay Merkezi için '
                'POST /nexgen/api/musteri-pazarlama/numune-mtt-onaya ile gönderin.'
            ),
            'kod': 'LEGACY_NUMUNE_ONAY_KAPALI',
        }), 410

    @bp.route('/api/musteri-pazarlama/numune-mtt-onaya', methods=['POST'])
    @login_gerekli
    def api_mo_numune_mtt_onaya():
        """Numune popup → görüşme + MTT NUMUNE + nexgen_onay (tek TX)."""
        _yetki_kontrol()
        from modules.nexgen.musteri_temsilcisi_talep_service import (
            MusteriTemsilcisiTalepError,
            numune_popup_mtt_onaya_gonder,
        )
        payload = request.get_json(silent=True) or {}
        con = db_fn()
        try:
            out = numune_popup_mtt_onaya_gonder(
                con, payload, kullanici_id_fn(),
                kullanici_yetkileri(session.get('kullanici') or {}),
            )
            if not out.get('onay_id'):
                return jsonify({
                    'ok': False,
                    'mesaj': 'Onay kaydı oluşmadan success verilemez.',
                }), 500
            return jsonify(out)
        except MusteriTemsilcisiTalepError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj, **e.ekstra}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/siparis-talep', methods=['POST'])
    @login_gerekli
    def api_mo_siparis_taslak():
        """Eski doğrudan MO sipariş taslak yazımı — V1 kapalı (410)."""
        _yetki_kontrol()
        return jsonify({
            'ok': False,
            'mesaj': (
                'Bu yol kapatıldı. Sipariş talebini görüşme üzerinden MTT + '
                'NexGen Onay akışına gönderin '
                '(POST /nexgen/api/musteri-pazarlama/gorusme + talep).'
            ),
            'kod': 'LEGACY_MO_SIPARIS_TASLAK_KAPALI',
        }), 410

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
        """Eski doğrudan sipariş→onay_talep yolu — V1 kapalı (410)."""
        _yetki_kontrol()
        return jsonify({
            'ok': False,
            'mesaj': (
                'Bu yol kapatıldı. Sipariş talebini görüşme + MTT + '
                'NexGen Onay Merkezi akışıyla gönderin.'
            ),
            'kod': 'LEGACY_MO_SIPARIS_ONAY_KAPALI',
            'siparis_id': int(siparis_id),
        }), 410

    @bp.route('/api/musteri-pazarlama/tahsilat-acik-planlar')
    @login_gerekli
    def api_mo_tahsilat_acik_planlar():
        u, yk = _yetki_kontrol()
        cid = request.args.get('cari_id')
        try:
            cari_id = int(cid or 0)
        except (TypeError, ValueError):
            cari_id = 0
        if not cari_id:
            return jsonify({'ok': False, 'mesaj': 'cari_id gerekli.'}), 400
        uid = kullanici_id_fn()
        con = db_fn()
        try:
            if not can_mo_view_cari(con, uid, cari_id, yk):
                return jsonify({'ok': False, 'mesaj': 'Bu müşteri için erişim yetkiniz yok.'}), 403
            planlar = acik_planlar(con, [cari_id])
            return jsonify({'ok': True, 'planlar': planlar})
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/tahsilat-kayitlari')
    @login_gerekli
    def api_mo_tahsilat_kayitlari():
        """Cari bazlı tahsilat kayıt listesi — read-only, IDOR korumalı."""
        u, yk = _yetki_kontrol()
        cid = request.args.get('cari_id')
        try:
            cari_id = int(cid or 0)
        except (TypeError, ValueError):
            cari_id = 0
        if not cari_id:
            return jsonify({'ok': False, 'mesaj': 'cari_id gerekli.'}), 400
        uid = kullanici_id_fn()
        con = db_fn()
        try:
            kayitlar = cari_tahsilat_listele(con, cari_id, uid, yk)
            return jsonify({'ok': True, 'kayitlar': kayitlar})
        except MoTahsilatError as e:
            return jsonify({'ok': False, 'mesaj': str(e)}), e.args[1] if len(e.args) > 1 else 400
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/tahsilat-sevkiyatlar')
    @login_gerekli
    def api_mo_tahsilat_sevkiyatlar():
        u, yk = _yetki_kontrol()
        try:
            siparis_id = int(request.args.get('siparis_id') or 0)
        except (TypeError, ValueError):
            siparis_id = 0
        if not siparis_id:
            return jsonify({'ok': False, 'mesaj': 'siparis_id gerekli.'}), 400
        cari_arg = request.args.get('cari_id')
        uid = kullanici_id_fn()
        con = db_fn()
        try:
            row = con.execute(
                'SELECT id, cari_id FROM nexgen_planlama_siparis WHERE id=?',
                (siparis_id,),
            ).fetchone()
            if not row:
                return jsonify({'ok': False, 'mesaj': 'Sipariş bulunamadı.'}), 404
            cari_id = int(row['cari_id'] or 0)
            if cari_arg not in (None, ''):
                try:
                    if int(cari_arg) != cari_id:
                        return jsonify({'ok': False, 'mesaj': 'Sipariş müşteri uyuşmuyor.'}), 400
                except (TypeError, ValueError):
                    return jsonify({'ok': False, 'mesaj': 'Geçersiz cari_id.'}), 400
            if not can_mo_view_cari(con, uid, cari_id, yk):
                return jsonify({'ok': False, 'mesaj': 'Bu sipariş için erişim yetkiniz yok.'}), 403
            sevkiyatlar = tahsilat_sevk_adaylari(con, siparis_id)
            sevkiyatlar = _enrich_tahsilat_sevkiyat_secim(con, sevkiyatlar)
            return jsonify({'ok': True, 'sevkiyatlar': sevkiyatlar, 'siparis_id': siparis_id})
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
        vade_asim_aciklamasi = payload.pop('vade_asim_aciklamasi', None) or None
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            r = tahsilat_onaya_gonder(
                con, kayit_id, kullanici_id_fn(),
                kullanici_yetkileri(session.get('kullanici') or {}),
                payload=payload or None,
                vade_asim_aciklamasi=vade_asim_aciklamasi,
            )
            return jsonify(r)
        except MoTahsilatError as e:
            con.rollback()
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    # ------------------------------------------------------------------
    # Vade Kontrol — Preview + Sipariş Bağlamı + Çek CRUD
    # ------------------------------------------------------------------

    @bp.route('/api/musteri-pazarlama/vade-kontrol/preview', methods=['POST'])
    @login_gerekli
    def api_vade_kontrol_preview():
        _yetki_kontrol()
        from decimal import Decimal
        from modules.nexgen.mo_vade_kontrol_service import CekSatiriInput, hesapla
        payload = request.get_json(silent=True) or {}
        try:
            siparis_id = int(payload['siparis_id']) if payload.get('siparis_id') else None
            tahsilat_kayit_id = int(payload['tahsilat_kayit_id']) if payload.get('tahsilat_kayit_id') else None
            paket_hedef = payload.get('paket_hedef_tutar')
            paket_hedef_d = Decimal(str(paket_hedef)) if paket_hedef not in (None, '') else None
            pb = (payload.get('para_birimi') or 'TRY').strip().upper()
            satirlar_raw = payload.get('cek_satirlari') or []
            cek_satirlari = []
            for s in satirlar_raw:
                cek_satirlari.append(CekSatiriInput(
                    tutar=Decimal(str(s['tutar'])),
                    gercek_cek_vade_tarihi=str(s['gercek_cek_vade_tarihi']),
                    para_birimi=(s.get('para_birimi') or pb).upper(),
                    cek_alim_tarihi=s.get('cek_alim_tarihi') or None,
                    odeme_referansi=s.get('odeme_referansi') or None,
                    banka_adi=s.get('banka_adi') or None,
                ))
            con = db_fn()
            try:
                con.row_factory = __import__('sqlite3').Row
                sonuc = hesapla(
                    siparis_id=siparis_id,
                    tahsilat_kayit_id=tahsilat_kayit_id,
                    odeme_tipi='CEK',
                    cek_satirlari=cek_satirlari,
                    paket_hedef_tutar=paket_hedef_d,
                    para_birimi=pb,
                    onaylanan_vade_gun=payload.get('onaylanan_vade_gun'),
                    sevk_tarihi=payload.get('sevk_tarihi') or None,
                    con=con,
                )
            finally:
                con.close()
            return jsonify({'ok': True, 'sonuc': sonuc.to_dict()})
        except Exception as e:
            return jsonify({'ok': False, 'mesaj': str(e)}), 400

    @bp.route('/api/musteri-pazarlama/vade-kontrol/siparis/<int:siparis_id>/beklenen')
    @login_gerekli
    def api_vade_kontrol_siparis_beklenen(siparis_id):
        _yetki_kontrol()
        from modules.nexgen.mo_vade_kontrol_service import siparis_vade_baglam, _gercek_sevk_tarihi_from_db
        from modules.nexgen.mo_tahsilat_plan_service import beklenen_tutar_hesapla
        from modules.nexgen.mo_siparis_talep_service import mo_siparis_payload_unpack
        from datetime import date, timedelta
        con = db_fn()
        try:
            con.row_factory = __import__('sqlite3').Row
            baglam = siparis_vade_baglam(con, siparis_id)
            if not baglam:
                return jsonify({'ok': False, 'mesaj': 'Sipariş bulunamadı.'}), 404
            row = con.execute(
                """
                SELECT anlasma_birim_fiyat, anlasma_para_birimi, talep_referansi, kur, kur_tarihi
                FROM nexgen_planlama_siparis WHERE id=?
                """,
                (siparis_id,),
            ).fetchone()
            if row:
                d = dict(row)
                mo = mo_siparis_payload_unpack(d.get('talep_referansi')) or {}
                tutar, tahmini = beklenen_tutar_hesapla(d, mo)
                baglam['siparis_toplami'] = tutar
                baglam['siparis_toplami_tahmini'] = tahmini
                baglam['siparis_para_birimi'] = d.get('anlasma_para_birimi') or 'TRY'
                baglam['siparis_kur'] = d.get('kur')
                baglam['siparis_kur_tarihi'] = (d.get('kur_tarihi') or '')[:10] or None
            sevk = _gercek_sevk_tarihi_from_db(con, siparis_id)
            baglam['gercek_sevk_tarihi'] = sevk
            hedef = None
            if sevk and baglam.get('onaylanan_vade_gun') is not None:
                try:
                    d = date.fromisoformat(sevk[:10])
                    hedef = (d + timedelta(days=int(baglam['onaylanan_vade_gun']))).isoformat()
                except (ValueError, TypeError):
                    pass
            baglam['hedef_vade_tarihi'] = hedef
            return jsonify({'ok': True, 'baglam': baglam})
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/tahsilat-kayit/<int:kayit_id>/cekler')
    @login_gerekli
    def api_cek_listele(kayit_id):
        _yetki_kontrol()
        from modules.nexgen.mo_tahsilat_cek_service import MoCekError, cek_listele
        from modules.nexgen.mo_vade_kontrol_service import hesapla
        con = db_fn()
        try:
            con.row_factory = __import__('sqlite3').Row
            cekler = cek_listele(con, kayit_id)
            # parent bilgisi
            parent = con.execute(
                'SELECT para_birimi, paket_hedef_tutar, onaylanan_vade_gun_snapshot, '
                'gercek_sevk_tarihi_snapshot, odeme_tipi, siparis_id '
                'FROM mo_tahsilat_kayit WHERE id=?', (kayit_id,)
            ).fetchone()
            vade_sonuc = None
            if parent and (parent['odeme_tipi'] or '').upper() == 'CEK':
                from decimal import Decimal
                from modules.nexgen.mo_vade_kontrol_service import CekSatiriInput
                satirlar = [
                    CekSatiriInput(
                        tutar=Decimal(str(c['tutar'])),
                        gercek_cek_vade_tarihi=c['gercek_cek_vade_tarihi'],
                        para_birimi=c['para_birimi'],
                    )
                    for c in cekler
                ]
                hedef_d = Decimal(str(parent['paket_hedef_tutar'])) if parent['paket_hedef_tutar'] else None
                try:
                    sonuc = hesapla(
                        tahsilat_kayit_id=kayit_id,
                        odeme_tipi='CEK',
                        cek_satirlari=satirlar,
                        paket_hedef_tutar=hedef_d,
                        para_birimi=parent['para_birimi'] or 'TRY',
                        onaylanan_vade_gun=parent['onaylanan_vade_gun_snapshot'],
                        sevk_tarihi=parent['gercek_sevk_tarihi_snapshot'],
                        con=con,
                    )
                    vade_sonuc = sonuc.to_dict()
                except Exception:
                    pass
            return jsonify({'ok': True, 'cekler': cekler, 'vade_sonuc': vade_sonuc})
        except MoCekError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/tahsilat-kayit/<int:kayit_id>/cekler', methods=['POST'])
    @login_gerekli
    def api_cek_ekle(kayit_id):
        _yetki_kontrol()
        from modules.nexgen.mo_tahsilat_cek_service import MoCekError, cek_ekle
        payload = request.get_json(silent=True) or {}
        con = db_fn()
        try:
            row = cek_ekle(con, kayit_id, payload, kullanici_id_fn())
            con.commit()
            return jsonify({'ok': True, 'cek': row})
        except MoCekError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/tahsilat-kayit/<int:kayit_id>/cekler/<int:cek_id>', methods=['PUT'])
    @login_gerekli
    def api_cek_guncelle(kayit_id, cek_id):
        _yetki_kontrol()
        from modules.nexgen.mo_tahsilat_cek_service import MoCekError, cek_guncelle
        payload = request.get_json(silent=True) or {}
        con = db_fn()
        try:
            row = cek_guncelle(con, kayit_id, cek_id, payload, kullanici_id_fn())
            con.commit()
            return jsonify({'ok': True, 'cek': row})
        except MoCekError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/tahsilat-kayit/<int:kayit_id>/cekler/<int:cek_id>', methods=['DELETE'])
    @login_gerekli
    def api_cek_sil(kayit_id, cek_id):
        _yetki_kontrol()
        from modules.nexgen.mo_tahsilat_cek_service import MoCekError, cek_soft_delete
        con = db_fn()
        try:
            r = cek_soft_delete(con, kayit_id, cek_id, kullanici_id_fn())
            con.commit()
            return jsonify({'ok': True, **r})
        except MoCekError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-pazarlama/tahsilat-kayit/<int:kayit_id>/cekler/bulk', methods=['POST'])
    @login_gerekli
    def api_cek_bulk(kayit_id):
        _yetki_kontrol()
        from modules.nexgen.mo_tahsilat_cek_service import MoCekError, cek_batch_replace
        payload = request.get_json(silent=True) or {}
        satirlar = payload.get('cek_satirlari') or []
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            rows = cek_batch_replace(con, kayit_id, satirlar, kullanici_id_fn())
            from modules.nexgen.mo_tahsilat_kayit_service import sync_cek_parent_tutarlar, _freeze_cek_snapshots
            sync_cek_parent_tutarlar(con, kayit_id)
            parent = con.execute(
                'SELECT siparis_id FROM mo_tahsilat_kayit WHERE id=?', (kayit_id,)
            ).fetchone()
            if parent and parent['siparis_id']:
                _freeze_cek_snapshots(con, kayit_id, int(parent['siparis_id']))
            con.commit()
            return jsonify({'ok': True, 'cekler': rows, 'cek_adedi': len(rows)})
        except MoCekError as e:
            con.rollback()
            return jsonify({'ok': False, 'mesaj': e.mesaj}), e.kod
        finally:
            con.close()

    # ------------------------------------------------------------------
    # Müşteri Temsilcisi Talebi — API omurga (UI yok; Mehmet liste/detay)
    # ------------------------------------------------------------------
    def _mtt_yetki():
        u = session.get('kullanici') or {}
        yk = kullanici_yetkileri(u)
        from modules.nexgen.musteri_temsilcisi_talep_service import can_mtt_kuyruk_gor
        if not can_mtt_kuyruk_gor(yk):
            abort(403)
        return u, yk

    def _mtt_aksiyon_yetki():
        u, yk = _mtt_yetki()
        from modules.nexgen.musteri_temsilcisi_talep_service import can_mtt_isleme_aksiyon
        if not can_mtt_isleme_aksiyon(yk):
            abort(403)
        return u, yk

    @bp.route('/api/musteri-temsilcisi-talep', methods=['GET'])
    @login_gerekli
    def api_mtt_liste():
        _mtt_yetki()
        from modules.nexgen.musteri_temsilcisi_talep_service import (
            MusteriTemsilcisiTalepError,
            kuyruk_sayaci,
            talep_listele,
            talep_sayaclari,
        )
        con = db_fn()
        try:
            durum = request.args.get('durum')
            durumlar = None
            if 'durumlar' in request.args:
                durumlar_raw = request.args.get('durumlar') or ''
                if durumlar_raw.strip():
                    durumlar = [x.strip() for x in durumlar_raw.split(',') if x.strip()]
                # boş durumlar= → tüm durumlar (filtre yok)
            elif not durum:
                # F4/F5B varsayılan kuyruk (kısmi numune dahil)
                durumlar = ['YENI', 'ISLEME_ALINDI', 'KISMEN_NUMUNEYE_DONUSTU']
            kayitlar = talep_listele(
                con,
                durum=durum,
                durumlar=durumlar,
                talep_turu=request.args.get('talep_turu'),
                gorusme_id=request.args.get('gorusme_id', type=int),
                cari_id=request.args.get('cari_id', type=int),
                musteri_aday_id=request.args.get('musteri_aday_id', type=int),
                olusturan_kullanici_id=request.args.get('olusturan_kullanici_id', type=int),
                atanan_kullanici_id=request.args.get('atanan_kullanici_id', type=int),
                q=request.args.get('q'),
                limit=request.args.get('limit', default=100, type=int),
                offset=request.args.get('offset', default=0, type=int),
            )
            sc = talep_sayaclari(con)
            from modules.nexgen.onay_service import mehmet_okunmamis_yeni_sayisi
            seen = session.get('mtt_ux_kuyruk_seen')
            return jsonify({
                'ok': True,
                'kayitlar': kayitlar,
                'sayaclar': sc,
                'kuyruk_sayisi': kuyruk_sayaci(con),
                'okunmamis_yeni': mehmet_okunmamis_yeni_sayisi(con, seen),
            })
        except MusteriTemsilcisiTalepError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj, **e.ekstra}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-temsilcisi-talep/kuyruk-okundu', methods=['POST'])
    @login_gerekli
    def api_mtt_kuyruk_okundu():
        _mtt_yetki()
        from datetime import datetime as _dt
        session['mtt_ux_kuyruk_seen'] = _dt.now().strftime('%Y-%m-%d %H:%M:%S')
        session.modified = True
        return jsonify({'ok': True, 'seen': session['mtt_ux_kuyruk_seen']})

    @bp.route('/api/musteri-temsilcisi-talep/<int:talep_id>', methods=['GET'])
    @login_gerekli
    def api_mtt_detay(talep_id):
        _mtt_yetki()
        from modules.nexgen.musteri_temsilcisi_talep_service import (
            MusteriTemsilcisiTalepError,
            talep_detay_getir,
        )
        con = db_fn()
        try:
            kayit = talep_detay_getir(con, talep_id, kullanici_id=kullanici_id_fn())
            return jsonify({'ok': True, 'kayit': kayit})
        except MusteriTemsilcisiTalepError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj, **e.ekstra}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-temsilcisi-talep', methods=['POST'])
    @login_gerekli
    def api_mtt_olustur():
        _u, yk = _mtt_yetki()
        from modules.nexgen.musteri_temsilcisi_talep_service import (
            MusteriTemsilcisiTalepError,
            can_mtt_talep_olustur,
            gorusme_satiri_getir,
            talep_olustur,
        )
        payload = request.get_json(silent=True) or {}
        con = db_fn()
        try:
            gid = payload.get('gorusme_id')
            if not gid:
                return jsonify({'ok': False, 'mesaj': 'gorusme_id zorunlu.'}), 400
            g = gorusme_satiri_getir(con, int(gid))
            if not can_mtt_talep_olustur(con, kullanici_id_fn(), g, yk):
                return jsonify({'ok': False, 'mesaj': 'Talep oluşturma yetkiniz yok.'}), 403
            out = talep_olustur(con, payload, kullanici_id_fn())
            return jsonify({'ok': True, **out})
        except MusteriTemsilcisiTalepError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj, **e.ekstra}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-temsilcisi-talep/<int:talep_id>/isleme-al', methods=['POST'])
    @login_gerekli
    def api_mtt_isleme_al(talep_id):
        _mtt_aksiyon_yetki()
        from modules.nexgen.musteri_temsilcisi_talep_service import (
            MusteriTemsilcisiTalepError,
            kuyruk_sayaci,
            talep_isleme_al,
            talep_sayaclari,
        )
        con = db_fn()
        try:
            out = talep_isleme_al(con, talep_id, kullanici_id_fn())
            return jsonify({
                'ok': True,
                **out,
                'sayaclar': talep_sayaclari(con),
                'kuyruk_sayisi': kuyruk_sayaci(con),
            })
        except MusteriTemsilcisiTalepError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj, **e.ekstra}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-temsilcisi-talep/<int:talep_id>/eksik-bilgi', methods=['POST'])
    @login_gerekli
    def api_mtt_eksik(talep_id):
        _mtt_aksiyon_yetki()
        from modules.nexgen.musteri_temsilcisi_talep_service import (
            MusteriTemsilcisiTalepError,
            kuyruk_sayaci,
            talep_eksik_bilgiye_gonder,
            talep_sayaclari,
        )
        payload = request.get_json(silent=True) or {}
        con = db_fn()
        try:
            out = talep_eksik_bilgiye_gonder(
                con, talep_id, kullanici_id_fn(),
                payload.get('geri_gonderme_notu') or payload.get('not') or '',
            )
            return jsonify({
                'ok': True,
                **out,
                'sayaclar': talep_sayaclari(con),
                'kuyruk_sayisi': kuyruk_sayaci(con),
            })
        except MusteriTemsilcisiTalepError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj, **e.ekstra}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-temsilcisi-talep/<int:talep_id>/tekrar-gonder', methods=['POST'])
    @login_gerekli
    def api_mtt_tekrar(talep_id):
        # Tekrar gönder = pazarlamacı (MO) — kuyruk görme yetkisi yeterli değil;
        # F4'te PZM'de yok; MO tarafı sonra. Şimdilik isleme yetkisi kapalı tut.
        _mtt_yetki()
        from modules.nexgen.musteri_temsilcisi_talep_service import (
            MusteriTemsilcisiTalepError,
            talep_tekrar_gonder,
        )
        con = db_fn()
        try:
            out = talep_tekrar_gonder(con, talep_id, kullanici_id_fn())
            return jsonify({'ok': True, **out})
        except MusteriTemsilcisiTalepError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj, **e.ekstra}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-temsilcisi-talep/<int:talep_id>/reddet', methods=['POST'])
    @login_gerekli
    def api_mtt_reddet(talep_id):
        _mtt_aksiyon_yetki()
        from modules.nexgen.musteri_temsilcisi_talep_service import (
            MusteriTemsilcisiTalepError,
            kuyruk_sayaci,
            talep_reddet,
            talep_sayaclari,
        )
        payload = request.get_json(silent=True) or {}
        con = db_fn()
        try:
            out = talep_reddet(
                con, talep_id, kullanici_id_fn(),
                payload.get('red_nedeni') or '',
            )
            return jsonify({
                'ok': True,
                **out,
                'sayaclar': talep_sayaclari(con),
                'kuyruk_sayisi': kuyruk_sayaci(con),
            })
        except MusteriTemsilcisiTalepError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj, **e.ekstra}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-temsilcisi-talep/<int:talep_id>/iptal', methods=['POST'])
    @login_gerekli
    def api_mtt_iptal(talep_id):
        _mtt_yetki()
        from modules.nexgen.musteri_temsilcisi_talep_service import (
            MusteriTemsilcisiTalepError,
            talep_iptal_et,
        )
        con = db_fn()
        try:
            out = talep_iptal_et(con, talep_id, kullanici_id_fn())
            return jsonify({'ok': True, **out})
        except MusteriTemsilcisiTalepError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj, **e.ekstra}), e.kod
        finally:
            con.close()

    # ------------------------------------------------------------------
    # F5 — Dönüşüm köprüsü (hazirla = read-only)
    # ------------------------------------------------------------------
    @bp.route('/api/musteri-temsilcisi-talep/<int:talep_id>/siparis-hazirla', methods=['GET'])
    @login_gerekli
    def api_mtt_siparis_hazirla(talep_id):
        u, yk = _mtt_aksiyon_yetki()
        from modules.nexgen.musteri_temsilcisi_talep_service import MusteriTemsilcisiTalepError
        from modules.nexgen.mtt_donusum_service import siparis_hazirla
        con = db_fn()
        try:
            out = siparis_hazirla(con, talep_id, kullanici_id_fn(), yk)
            return jsonify(out)
        except MusteriTemsilcisiTalepError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj, **e.ekstra}), e.kod
        finally:
            con.close()

    @bp.route('/api/musteri-temsilcisi-talep/<int:talep_id>/numune-hazirla', methods=['GET'])
    @login_gerekli
    def api_mtt_numune_hazirla(talep_id):
        u, yk = _mtt_aksiyon_yetki()
        from modules.nexgen.musteri_temsilcisi_talep_service import MusteriTemsilcisiTalepError
        from modules.nexgen.mtt_donusum_service import numune_hazirla
        con = db_fn()
        try:
            out = numune_hazirla(con, talep_id, kullanici_id_fn(), yk)
            return jsonify(out)
        except MusteriTemsilcisiTalepError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj, **e.ekstra}), e.kod
        finally:
            con.close()

    # ------------------------------------------------------------------
    # Onay Merkezi V1 — Yönetim (yalnız MTT kaynağı)
    # ------------------------------------------------------------------
    def _onay_yetki():
        u = session.get('kullanici') or {}
        yk = kullanici_yetkileri(u)
        from modules.nexgen.onay_service import can_onay_liste_gor
        if not can_onay_liste_gor(yk):
            abort(403)
        return u, yk

    def _onay_karar_yetki():
        u = session.get('kullanici') or {}
        yk = kullanici_yetkileri(u)
        from modules.nexgen.onay_service import can_onay_karar
        if not can_onay_karar(yk):
            abort(403)
        return u, yk

    @bp.route('/api/yonetim/onaylar', methods=['GET'])
    @login_gerekli
    def api_yonetim_onaylar():
        _onay_yetki()
        from modules.nexgen.onay_service import OnayError, onay_kuyruk_sayaci, onay_listele
        con = db_fn()
        try:
            liste = onay_listele(
                con,
                durum=request.args.get('durum'),
                kaynak_turu=request.args.get('kaynak_turu') or 'MUSTERI_TEMSILCISI_TALEP',
                q=request.args.get('q'),
                limit=int(request.args.get('limit') or 100),
            )
            return jsonify({
                'ok': True,
                'liste': liste,
                'kuyruk_sayisi': onay_kuyruk_sayaci(con),
            })
        except OnayError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj, **e.ekstra}), e.kod
        finally:
            con.close()

    @bp.route('/api/yonetim/onay/<int:onay_id>', methods=['GET'])
    @login_gerekli
    def api_yonetim_onay_detay(onay_id):
        _onay_yetki()
        from modules.nexgen.onay_service import OnayError, onay_detay_getir
        con = db_fn()
        try:
            return jsonify({'ok': True, 'kayit': onay_detay_getir(con, onay_id)})
        except OnayError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj, **e.ekstra}), e.kod
        finally:
            con.close()

    @bp.route('/api/yonetim/onay/<int:onay_id>/onayla', methods=['POST'])
    @login_gerekli
    def api_yonetim_onayla(onay_id):
        _, yk = _onay_karar_yetki()
        from modules.nexgen.onay_service import OnayError, onay_kuyruk_sayaci, onay_onayla
        con = db_fn()
        try:
            out = onay_onayla(con, onay_id, kullanici_id_fn(), yk)
            return jsonify({
                'ok': True, **out,
                'kuyruk_sayisi': onay_kuyruk_sayaci(con),
            })
        except OnayError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj, **e.ekstra}), e.kod
        finally:
            con.close()

    @bp.route('/api/yonetim/onay/<int:onay_id>/reddet', methods=['POST'])
    @login_gerekli
    def api_yonetim_reddet(onay_id):
        _, yk = _onay_karar_yetki()
        from modules.nexgen.onay_service import OnayError, onay_kuyruk_sayaci, onay_reddet
        payload = request.get_json(silent=True) or {}
        con = db_fn()
        try:
            out = onay_reddet(
                con, onay_id, kullanici_id_fn(),
                payload.get('red_nedeni') or '', yk,
            )
            return jsonify({
                'ok': True, **out,
                'kuyruk_sayisi': onay_kuyruk_sayaci(con),
            })
        except OnayError as e:
            return jsonify({'ok': False, 'mesaj': e.mesaj, **e.ekstra}), e.kod
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
