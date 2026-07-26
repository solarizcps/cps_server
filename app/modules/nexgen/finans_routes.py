# -*- coding: utf-8 -*-
"""Finans / Muhasebe Merkezi API route kayıtları."""
from __future__ import annotations

from flask import abort, jsonify, render_template, request, session

from modules.auth import login_gerekli, kullanici_yetkileri
from modules.nexgen.finans_api_serializer import (
    api_hata,
    api_ok,
    belge_detay_satir,
    belge_liste_satir,
)
from modules.nexgen.cari360_yetki import can_cari360_dosya_ekrani
from modules.nexgen.finans_belgesi_repository import FinansBelgesiError
from modules.nexgen.finans_cari_read_service import FinansCariReadError, cari_hesap_paket
from modules.nexgen.finans_read_service import DEFAULT_PAGE_SIZE, detay_paket, liste_belgeler
from modules.nexgen.finans_yetki import (
    can_finans_approve,
    can_finans_manage,
    can_finans_post,
    can_finans_reject,
    can_finans_review,
    can_finans_view,
    finans_erisim_engelli,
    is_pazarlamaci_finans_kisitli,
)
from modules.nexgen.finance_workflow_service import FinanceWorkflowService
from modules.nexgen.financial_posting_service import FinancialPostingService
from modules.nexgen.finans_cari_kimlik_yetki import (
    can_cari_kimlik_view,
    cari_kimlik_erisim_engelli,
)
from modules.nexgen.mo_tahsilat_config import CARI_ENTEGRASYON_AKTIF


def register_finans_routes(bp, db_fn, kullanici_id_fn):
    def _u():
        return session.get('kullanici') or {}

    def _yk():
        return kullanici_yetkileri(_u())

    def _finans_erisim():
        u, yk = _u(), _yk()
        if finans_erisim_engelli(u, yk):
            return False
        return can_finans_view(yk)

    @bp.route('/finans')
    @bp.route('/finans/')
    @login_gerekli
    def finans_merkezi_sayfa():
        u, yk = _u(), _yk()
        if finans_erisim_engelli(u, yk) or not can_finans_view(yk):
            abort(403)
        return render_template(
            'nexgen/finans_merkezi.html',
            active='nexgen',
            can_review=can_finans_review(yk) and not is_pazarlamaci_finans_kisitli(yk),
            can_approve=can_finans_approve(yk) and not is_pazarlamaci_finans_kisitli(yk),
            can_post=can_finans_post(yk) and not is_pazarlamaci_finans_kisitli(yk),
            cari_entegrasyon_aktif=CARI_ENTEGRASYON_AKTIF,
            can_cari_kimlik_koprusu=(
                can_cari_kimlik_view(yk) and not cari_kimlik_erisim_engelli(u, yk)
            ),
        )

    def _json_hata(e: FinansBelgesiError):
        return jsonify(api_hata(e.hata_kodu or 'FINANS_HATA', e.mesaj)), int(e.kod or 400)

    def _body():
        return request.get_json(silent=True) or {}

    def _int_arg(args, key: str):
        v = args.get(key)
        if v in (None, ''):
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    @bp.route('/api/finans-belgeleri')
    @login_gerekli
    def api_finans_liste():
        if not _finans_erisim():
            abort(403)
        args = request.args
        con = db_fn()
        try:
            paket = liste_belgeler(
                con,
                belge_tipi=(args.get('belge_tipi') or '').strip() or None,
                durum=(args.get('durum') or '').strip() or None,
                posting_durumu=(args.get('posting_durumu') or '').strip() or None,
                cari_id=_int_arg(args, 'cari_id'),
                siparis_id=_int_arg(args, 'siparis_id'),
                sevkiyat_id=_int_arg(args, 'sevkiyat_id'),
                tahsilat_id=_int_arg(args, 'tahsilat_id'),
                tarih_bas=(args.get('tarih_bas') or args.get('tarih_baslangic') or '').strip() or None,
                tarih_bit=(args.get('tarih_bit') or args.get('tarih_bitis') or '').strip() or None,
                arama=(args.get('arama') or args.get('q') or '').strip() or None,
                page=int(args.get('page') or 1),
                page_size=int(args.get('page_size') or DEFAULT_PAGE_SIZE),
            )
            return jsonify(api_ok(
                liste=[belge_liste_satir(r) for r in paket['liste']],
                sayfalama=paket['sayfalama'],
                ozet=paket.get('ozet') or {},
                cari360_erisim=can_cari360_dosya_ekrani(_yk()),
            ))
        except FinansBelgesiError as e:
            return _json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans-belgesi/<int:belge_id>')
    @login_gerekli
    def api_finans_detay(belge_id):
        if not _finans_erisim():
            abort(403)
        con = db_fn()
        try:
            paket = detay_paket(con, belge_id, _yk(), user_dict=_u())
            return jsonify(api_ok(
                belge=belge_detay_satir(
                    paket['belge'],
                    kaynak_ozet=paket['kaynak_ozet'],
                    audit=paket['audit'],
                    durum_gecisleri=paket['durum_gecisleri'],
                    aksiyonlar=paket['aksiyonlar'],
                    posting_onizleme=paket['posting_onizleme'],
                ),
                cari_hesap=paket.get('cari_hesap'),
            ))
        except FinansBelgesiError as e:
            return _json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans-cari/<int:cari_id>/hesap')
    @login_gerekli
    def api_finans_cari_hesap(cari_id):
        if not _finans_erisim():
            abort(403)
        con = db_fn()
        try:
            paket = cari_hesap_paket(con, cari_id, yk=_yk(), user_dict=_u())
            return jsonify(api_ok(cari_hesap=paket))
        except FinansCariReadError as e:
            return jsonify(api_hata(e.hata_kodu or 'CARI_HATA', e.mesaj)), int(e.kod or 404)
        finally:
            con.close()

    @bp.route('/api/finans-belgesi/sevkiyat/<int:sevkiyat_id>', methods=['POST'])
    @login_gerekli
    def api_finans_belge_sevkiyat(sevkiyat_id):
        yk = _yk()
        if finans_erisim_engelli(_u(), yk) or not can_finans_review(yk):
            abort(403)
        if is_pazarlamaci_finans_kisitli(yk):
            abort(403)
        u = _u()
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            belge = FinanceWorkflowService.belge_olustur_sevkiyat(
                con, sevkiyat_id, kullanici_id_fn(), u.get('KullaniciAdi') or u.get('AdSoyad'),
            )
            con.commit()
            return jsonify(api_ok(belge=belge_detay_satir(belge), idempotent=True))
        except FinansBelgesiError as e:
            con.rollback()
            return _json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans-belgesi/tahsilat/<int:tahsilat_id>', methods=['POST'])
    @login_gerekli
    def api_finans_belge_tahsilat(tahsilat_id):
        yk = _yk()
        if finans_erisim_engelli(_u(), yk) or not can_finans_review(yk):
            abort(403)
        if is_pazarlamaci_finans_kisitli(yk):
            abort(403)
        u = _u()
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            belge = FinanceWorkflowService.belge_olustur_tahsilat(
                con, tahsilat_id, kullanici_id_fn(), u.get('KullaniciAdi') or u.get('AdSoyad'),
            )
            con.commit()
            return jsonify(api_ok(belge=belge_detay_satir(belge), idempotent=True))
        except FinansBelgesiError as e:
            con.rollback()
            return _json_hata(e)
        finally:
            con.close()

    def _durum_islem(belge_id: int, fn, yetki_fn, **kwargs):
        yk = _yk()
        if finans_erisim_engelli(_u(), yk) or not yetki_fn(yk):
            abort(403)
        if is_pazarlamaci_finans_kisitli(yk) and yetki_fn != can_finans_review:
            abort(403)
        u = _u()
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            belge = fn(
                con, belge_id, kullanici_id_fn(), u.get('KullaniciAdi') or u.get('AdSoyad'), **kwargs,
            )
            con.commit()
            return jsonify(api_ok(belge=belge_detay_satir(belge)))
        except FinansBelgesiError as e:
            con.rollback()
            return _json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans-belgesi/<int:belge_id>/incelemeye-al', methods=['POST'])
    @login_gerekli
    def api_finans_incelemeye_al(belge_id):
        d = _body()
        return _durum_islem(
            belge_id, FinanceWorkflowService.incelemeye_al, can_finans_review,
        )

    @bp.route('/api/finans-belgesi/<int:belge_id>/onayla', methods=['POST'])
    @login_gerekli
    def api_finans_onayla(belge_id):
        d = _body()
        return _durum_islem(
            belge_id, FinanceWorkflowService.onayla, can_finans_approve,
            notu=(d.get('not') or d.get('notu') or '').strip() or None,
        )

    @bp.route('/api/finans-belgesi/<int:belge_id>/duzeltmeye-gonder', methods=['POST'])
    @login_gerekli
    def api_finans_duzeltmeye_gonder(belge_id):
        d = _body()
        return _durum_islem(
            belge_id, FinanceWorkflowService.duzeltmeye_gonder, can_finans_review,
            notu=(d.get('not') or d.get('aciklama') or '').strip() or None,
        )

    @bp.route('/api/finans-belgesi/<int:belge_id>/reddet', methods=['POST'])
    @login_gerekli
    def api_finans_reddet(belge_id):
        d = _body()
        gerekce = (d.get('gerekce') or d.get('not') or '').strip()
        if not gerekce:
            return jsonify(api_hata('RED_GEREKCE', 'Red gerekçesi zorunlu.')), 400
        return _durum_islem(
            belge_id, FinanceWorkflowService.reddet, can_finans_reject,
            gerekce=gerekce,
        )

    @bp.route('/api/finans-belgesi/<int:belge_id>/kapat', methods=['POST'])
    @login_gerekli
    def api_finans_kapat(belge_id):
        yk = _yk()
        if finans_erisim_engelli(_u(), yk):
            abort(403)
        if not (can_finans_manage(yk) or can_finans_approve(yk)):
            abort(403)
        return _durum_islem(belge_id, FinanceWorkflowService.kapat, can_finans_manage)

    @bp.route('/api/finans-belgesi/<int:belge_id>/posting-dry-run', methods=['POST'])
    @login_gerekli
    def api_finans_posting_dry_run(belge_id):
        yk = _yk()
        if finans_erisim_engelli(_u(), yk) or not can_finans_post(yk):
            abort(403)
        if is_pazarlamaci_finans_kisitli(yk):
            abort(403)
        u = _u()
        con = db_fn()
        try:
            from modules.nexgen.finans_belgesi_repository import get_by_id
            belge = get_by_id(con, belge_id)
            tip = belge.get('belge_tipi')
            con.execute('BEGIN IMMEDIATE')
            if tip == 'SATIS_SEVKIYAT':
                sonuc = FinancialPostingService.post_borc(
                    con, belge_id, kullanici_id_fn(), u.get('KullaniciAdi'), force_live=False,
                )
            elif tip == 'TAHSILAT':
                sonuc = FinancialPostingService.post_alacak(
                    con, belge_id, kullanici_id_fn(), u.get('KullaniciAdi'), force_live=False,
                )
            else:
                raise FinansBelgesiError('Desteklenmeyen belge tipi.', 409, 'BELGE_TIP_UYUMSUZ')
            con.commit()
            paket = detay_paket(con, belge_id, _yk(), user_dict=_u())
            return jsonify(api_ok(
                dry_run=True,
                cari_entegrasyon_aktif=CARI_ENTEGRASYON_AKTIF,
                sonuc=sonuc,
                belge=belge_detay_satir(
                    paket['belge'],
                    kaynak_ozet=paket.get('kaynak_ozet'),
                    audit=paket.get('audit'),
                    durum_gecisleri=paket.get('durum_gecisleri'),
                    aksiyonlar=paket.get('aksiyonlar'),
                    posting_onizleme=paket.get('posting_onizleme'),
                ),
                cari_hesap=paket.get('cari_hesap'),
            ))
        except FinansBelgesiError as e:
            con.rollback()
            return _json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans-belgesi/<int:belge_id>/posting-kontrol', methods=['POST'])
    @login_gerekli
    def api_finans_posting_kontrol(belge_id):
        """Yan etkisiz validasyon — Cari_Har yazmaz."""
        if not _finans_erisim() or not can_finans_post(_yk()):
            abort(403)
        con = db_fn()
        try:
            from modules.nexgen.finans_read_service import posting_onizleme
            from modules.nexgen.finans_belgesi_repository import get_by_id
            belge = get_by_id(con, belge_id)
            oniz = posting_onizleme(con, belge)
            return jsonify(api_ok(
                dry_run=True,
                cari_entegrasyon_aktif=CARI_ENTEGRASYON_AKTIF,
                onizleme=oniz,
            ))
        except FinansBelgesiError as e:
            return _json_hata(e)
        finally:
            con.close()

    @bp.route('/api/finans-belgesi/<int:belge_id>/posting', methods=['POST'])
    @login_gerekli
    def api_finans_posting_live(belge_id):
        """Gerçek Cari_Har posting — CARI_ENTEGRASYON_AKTIF=True ve can_post gerekir."""
        yk = _yk()
        if finans_erisim_engelli(_u(), yk) or not can_finans_post(yk):
            abort(403)
        if is_pazarlamaci_finans_kisitli(yk):
            abort(403)
        if not CARI_ENTEGRASYON_AKTIF:
            return jsonify(api_hata(
                'POSTING_KAPALI',
                'Gerçek Cari_Har posting kapalı (CARI_ENTEGRASYON_AKTIF=False).',
            )), 403
        u = _u()
        con = db_fn()
        try:
            from modules.nexgen.finans_belgesi_repository import get_by_id
            belge = get_by_id(con, belge_id)
            tip = belge.get('belge_tipi')
            con.execute('BEGIN IMMEDIATE')
            if tip == 'SATIS_SEVKIYAT':
                sonuc = FinancialPostingService.post_borc(
                    con, belge_id, kullanici_id_fn(), u.get('KullaniciAdi'), force_live=True,
                )
            elif tip == 'TAHSILAT':
                sonuc = FinancialPostingService.post_alacak(
                    con, belge_id, kullanici_id_fn(), u.get('KullaniciAdi'), force_live=True,
                )
            else:
                raise FinansBelgesiError('Desteklenmeyen belge tipi.', 409, 'BELGE_TIP_UYUMSUZ')
            con.commit()
            paket = detay_paket(con, belge_id, _yk(), user_dict=_u())
            return jsonify(api_ok(
                dry_run=False,
                cari_entegrasyon_aktif=CARI_ENTEGRASYON_AKTIF,
                sonuc=sonuc,
                belge=belge_detay_satir(
                    paket['belge'],
                    kaynak_ozet=paket.get('kaynak_ozet'),
                    audit=paket.get('audit'),
                    durum_gecisleri=paket.get('durum_gecisleri'),
                    aksiyonlar=paket.get('aksiyonlar'),
                    posting_onizleme=paket.get('posting_onizleme'),
                ),
                cari_hesap=paket.get('cari_hesap'),
            ))
        except FinansBelgesiError as e:
            con.rollback()
            return _json_hata(e)
        finally:
            con.close()
