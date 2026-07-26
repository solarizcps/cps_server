# -*- coding: utf-8 -*-
"""Finans cari kimlik JSON API route kayitlari (FAZ-F1-3)."""
from __future__ import annotations

import logging
from typing import Any

from flask import abort, jsonify, render_template, request, session

from modules.auth import login_gerekli, kullanici_yetkileri
from modules.nexgen.finans_cari_kimlik_read_service import (
    detay,
    eslestirme_adaylari,
    kpi,
    liste,
)
from modules.nexgen.finans_cari_kimlik_service import (
    FinansCariKimlikError,
    apply_manuel_kimlik_override,
    create_kimlik_musteri,
    create_kimlik_tedarikci,
    deactivate_kimlik,
    reactivate_kimlik,
    resolve_kimlik,
    sync_musteri_ckod_from_eslestirme,
)
from modules.nexgen.finans_cari_kimlik_yetki import (
    can_cari_kimlik_manuel_override,
    can_cari_kimlik_view,
    can_cari_kimlik_write_musteri,
    can_cari_kimlik_write_tedarikci,
    cari_kimlik_erisim_engelli,
    is_planlama_depo_sevkiyat,
)
from modules.nexgen.tedarikci_eslestirme_service import (
    create_or_update_tedarikci_eslestirme,
    dogrula_tedarikci_eslestirme,
    iptal_tedarikci_eslestirme,
    sync_tedarikci_kimlik_ckod,
)

_log = logging.getLogger(__name__)

MAX_LIST_LIMIT = 200
DEFAULT_LIST_LIMIT = 100
VALID_KIMLIK_TIPLERI = ('MUSTERI', 'TEDARIKCI')


def register_finans_cari_kimlik_routes(bp, db_fn, kullanici_id_fn):
    def _u():
        return session.get('kullanici') or {}

    def _yk():
        return kullanici_yetkileri(_u())

    def _uid():
        try:
            return int(kullanici_id_fn() or 0) or None
        except (TypeError, ValueError):
            return None

    def _body() -> dict[str, Any]:
        return request.get_json(silent=True) or {}

    def _api_ok(data: Any = None, **extra: Any):
        out: dict[str, Any] = {'ok': True}
        if data is not None:
            out['data'] = data
        out.update(extra)
        return jsonify(out)

    def _api_err(code: str, message: str, http_status: int = 400, details: dict | None = None):
        return jsonify({
            'ok': False,
            'error': {
                'code': code,
                'message': message,
                'details': details or {},
            },
        }), int(http_status)

    def _domain_err(e: FinansCariKimlikError):
        return _api_err(e.code, e.message, e.http_status, e.details)

    def _read_guard():
        u, yk = _u(), _yk()
        if cari_kimlik_erisim_engelli(u, yk) or is_planlama_depo_sevkiyat(u):
            abort(403)
        if not can_cari_kimlik_view(yk):
            abort(403)

    def _write_musteri_guard():
        u, yk = _u(), _yk()
        if cari_kimlik_erisim_engelli(u, yk) or is_planlama_depo_sevkiyat(u):
            abort(403)
        if not can_cari_kimlik_write_musteri(yk):
            abort(403)

    def _write_tedarikci_guard():
        u, yk = _u(), _yk()
        if cari_kimlik_erisim_engelli(u, yk) or is_planlama_depo_sevkiyat(u):
            abort(403)
        if not can_cari_kimlik_write_tedarikci(yk):
            abort(403)

    def _manuel_guard(*, tedarikci: bool = False):
        yk = _yk()
        if not can_cari_kimlik_manuel_override(yk, tedarikci=tedarikci):
            abort(403)

    def _int_arg(args, key: str, default: int | None = None) -> int | None:
        v = args.get(key)
        if v in (None, ''):
            return default
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    def _audit_meta(action: str, target_type: str, target_id: int, **extra: Any) -> dict[str, Any]:
        return {
            'action': action,
            'target_type': target_type,
            'target_id': target_id,
            'user_id': _uid(),
            **extra,
        }

    @bp.route('/finans/cari-kimlik-koprusu')
    @login_gerekli
    def fck_koprusu_sayfa():
        u, yk = _u(), _yk()
        if cari_kimlik_erisim_engelli(u, yk) or is_planlama_depo_sevkiyat(u):
            abort(403)
        if not can_cari_kimlik_view(yk):
            abort(403)
        return render_template(
            'nexgen/finans_cari_kimlik_koprusu.html',
            active='nexgen',
            can_write_musteri=can_cari_kimlik_write_musteri(yk),
            can_write_tedarikci=can_cari_kimlik_write_tedarikci(yk),
            can_manuel_override=can_cari_kimlik_manuel_override(yk),
        )

    @bp.route('/api/finans-cari-kimlik/liste')
    @login_gerekli
    def api_fck_liste():
        _read_guard()
        args = request.args
        kimlik_tipi = (args.get('kimlik_tipi') or '').strip().upper() or None
        if kimlik_tipi and kimlik_tipi not in VALID_KIMLIK_TIPLERI:
            return _api_err('PARAMETRE_HATASI', 'Gecersiz kimlik_tipi.', 400)
        limit = _int_arg(args, 'limit', DEFAULT_LIST_LIMIT) or DEFAULT_LIST_LIMIT
        limit = min(max(1, limit), MAX_LIST_LIMIT)
        offset = _int_arg(args, 'offset', 0) or 0
        offset = max(0, offset)
        yalniz_eksik = str(args.get('yalniz_eksik') or '').lower() in ('1', 'true', 'yes')
        con = db_fn()
        try:
            paket = liste(
                con,
                kimlik_tipi=kimlik_tipi,
                durum=(args.get('durum') or '').strip().upper() or None,
                arama=(args.get('arama') or '').strip() or None,
                yalniz_eksik=yalniz_eksik,
                limit=limit,
                offset=offset,
            )
            kp = kpi(con)
            return _api_ok(
                data={
                    'items': paket['kayitlar'],
                    'kpi': kp,
                    'pagination': {
                        'toplam': paket['toplam'],
                        'limit': paket['limit'],
                        'offset': paket['offset'],
                    },
                    'filters_applied': {
                        'kimlik_tipi': kimlik_tipi,
                        'durum': (args.get('durum') or '').strip() or None,
                        'arama': (args.get('arama') or '').strip() or None,
                        'yalniz_eksik': yalniz_eksik,
                    },
                },
            )
        except FinansCariKimlikError as e:
            return _domain_err(e)
        except Exception:
            _log.exception('fck liste hatasi')
            return _api_err('SUNUCU_HATASI', 'Liste alinamadi.', 500)
        finally:
            con.close()

    @bp.route('/api/finans-cari-kimlik/<int:kimlik_id>')
    @login_gerekli
    def api_fck_detay(kimlik_id):
        _read_guard()
        con = db_fn()
        try:
            paket = detay(con, kimlik_id)
            return _api_ok(data={'kimlik': paket, 'uyarilar': paket.get('uyarilar') or []})
        except FinansCariKimlikError as e:
            return _domain_err(e)
        except Exception:
            _log.exception('fck detay hatasi kimlik_id=%s', kimlik_id)
            return _api_err('SUNUCU_HATASI', 'Detay alinamadi.', 500)
        finally:
            con.close()

    @bp.route('/api/finans-cari-kimlik/musteri/<int:nexgen_cari_id>')
    @login_gerekli
    def api_fck_musteri_resolve(nexgen_cari_id):
        _read_guard()
        con = db_fn()
        try:
            paket = resolve_kimlik(con, nexgen_cari_id=nexgen_cari_id)
            return _api_ok(data={'kimlik': paket})
        except FinansCariKimlikError as e:
            return _domain_err(e)
        finally:
            con.close()

    @bp.route('/api/finans-cari-kimlik/tedarikci/<int:nexgen_tedarikci_id>')
    @login_gerekli
    def api_fck_tedarikci_resolve(nexgen_tedarikci_id):
        _read_guard()
        con = db_fn()
        try:
            paket = resolve_kimlik(con, nexgen_tedarikci_id=nexgen_tedarikci_id)
            return _api_ok(data={'kimlik': paket})
        except FinansCariKimlikError as e:
            return _domain_err(e)
        finally:
            con.close()

    @bp.route('/api/finans-cari-kimlik/<kimlik_tipi>/<int:operasyonel_id>/adaylar')
    @login_gerekli
    def api_fck_adaylar(kimlik_tipi, operasyonel_id):
        _read_guard()
        tip = (kimlik_tipi or '').strip().upper()
        if tip not in VALID_KIMLIK_TIPLERI:
            return _api_err('PARAMETRE_HATASI', 'Gecersiz kimlik_tipi.', 400)
        limit = _int_arg(request.args, 'limit', 20) or 20
        limit = min(max(1, limit), MAX_LIST_LIMIT)
        con = db_fn()
        try:
            adaylar = eslestirme_adaylari(
                con, tip, operasyonel_id,
                arama=(request.args.get('arama') or '').strip() or None,
                limit=limit,
            )
            return _api_ok(data={'adaylar': adaylar})
        except FinansCariKimlikError as e:
            return _domain_err(e)
        finally:
            con.close()

    @bp.route('/api/finans-cari-kimlik/musteri/<int:nexgen_cari_id>/olustur', methods=['POST'])
    @login_gerekli
    def api_fck_musteri_olustur(nexgen_cari_id):
        _write_musteri_guard()
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            paket = create_kimlik_musteri(con, nexgen_cari_id, user_id=_uid(), commit=False)
            con.commit()
            created = not paket.get('idempotent')
            status = 201 if created else 200
            return _api_ok(
                data={'created': created, 'kimlik': paket},
                audit=_audit_meta('create_musteri_kimlik', 'finans_cari_kimlik', paket['id']),
            ), status
        except FinansCariKimlikError as e:
            con.rollback()
            return _domain_err(e)
        except Exception:
            con.rollback()
            _log.exception('fck musteri olustur hatasi')
            return _api_err('SUNUCU_HATASI', 'Kimlik olusturulamadi.', 500)
        finally:
            con.close()

    @bp.route('/api/finans-cari-kimlik/tedarikci/<int:nexgen_tedarikci_id>/olustur', methods=['POST'])
    @login_gerekli
    def api_fck_tedarikci_olustur(nexgen_tedarikci_id):
        _write_tedarikci_guard()
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            paket = create_kimlik_tedarikci(con, nexgen_tedarikci_id, user_id=_uid(), commit=False)
            con.commit()
            created = not paket.get('idempotent')
            status = 201 if created else 200
            return _api_ok(
                data={'created': created, 'kimlik': paket},
                audit=_audit_meta('create_tedarikci_kimlik', 'finans_cari_kimlik', paket['id']),
            ), status
        except FinansCariKimlikError as e:
            con.rollback()
            return _domain_err(e)
        except Exception:
            con.rollback()
            _log.exception('fck tedarikci olustur hatasi')
            return _api_err('SUNUCU_HATASI', 'Kimlik olusturulamadi.', 500)
        finally:
            con.close()

    @bp.route('/api/finans-cari-kimlik/<int:kimlik_id>/musteri-sync', methods=['POST'])
    @login_gerekli
    def api_fck_musteri_sync(kimlik_id):
        _write_musteri_guard()
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            before = detay(con, kimlik_id)
            paket = sync_musteri_ckod_from_eslestirme(
                con, kimlik_id, user_id=_uid(), commit=False,
            )
            con.commit()
            return _api_ok(
                data={'kimlik': paket, 'idempotent': before.get('cari_kart_ckod') == paket.get('cari_kart_ckod')},
                audit=_audit_meta(
                    'musteri_sync', 'finans_cari_kimlik', kimlik_id,
                    before_ckod=before.get('cari_kart_ckod'),
                    after_ckod=paket.get('cari_kart_ckod'),
                ),
            )
        except FinansCariKimlikError as e:
            con.rollback()
            return _domain_err(e)
        except Exception:
            con.rollback()
            _log.exception('fck musteri sync hatasi')
            return _api_err('SUNUCU_HATASI', 'Sync basarisiz.', 500)
        finally:
            con.close()

    @bp.route('/api/finans-cari-kimlik/tedarikci/<int:nexgen_tedarikci_id>/eslestir', methods=['POST'])
    @login_gerekli
    def api_fck_tedarikci_eslestir(nexgen_tedarikci_id):
        data = _body()
        manuel = bool(data.get('manuel_override'))
        if manuel:
            _manuel_guard(tedarikci=True)
        else:
            _write_tedarikci_guard()
        ckod = (data.get('cari_kart_ckod') or '').strip()
        if not ckod:
            return _api_err('CKOD_ZORUNLU', 'cari_kart_ckod zorunlu.', 400)
        override_reason = (data.get('override_reason') or '').strip()
        if manuel and not override_reason:
            return _api_err('OVERRIDE_REASON_ZORUNLU', 'override_reason zorunlu.', 400)
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            es = create_or_update_tedarikci_eslestirme(
                con, nexgen_tedarikci_id, ckod,
                eslestirme_yontemi=(data.get('eslestirme_yontemi') or 'MANUEL').strip(),
                notlar=data.get('notlar'),
                user_id=_uid(),
                manuel_override=manuel,
                manuel_not=override_reason or None,
                commit=False,
            )
            kimlik = None
            row = con.execute(
                'SELECT id FROM finans_cari_kimlik WHERE nexgen_tedarikci_id=?',
                (nexgen_tedarikci_id,),
            ).fetchone()
            if row:
                kimlik = sync_tedarikci_kimlik_ckod(
                    con, int(row['id']), user_id=_uid(),
                    manuel_override=manuel,
                    manuel_not=override_reason or None,
                    commit=False,
                )
            con.commit()
            return _api_ok(
                data={'eslestirme': es, 'kimlik': kimlik},
                audit=_audit_meta('tedarikci_eslestir', 'tedarikci_eslestirme', nexgen_tedarikci_id),
            )
        except FinansCariKimlikError as e:
            con.rollback()
            return _domain_err(e)
        except Exception:
            con.rollback()
            _log.exception('fck tedarikci eslestir hatasi')
            return _api_err('SUNUCU_HATASI', 'Eslestirme basarisiz.', 500)
        finally:
            con.close()

    @bp.route('/api/finans-cari-kimlik/tedarikci/<int:nexgen_tedarikci_id>/dogrula', methods=['POST'])
    @login_gerekli
    def api_fck_tedarikci_dogrula(nexgen_tedarikci_id):
        _write_tedarikci_guard()
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            es = dogrula_tedarikci_eslestirme(con, nexgen_tedarikci_id, user_id=_uid(), commit=False)
            con.commit()
            return _api_ok(data={'eslestirme': es})
        except FinansCariKimlikError as e:
            con.rollback()
            return _domain_err(e)
        finally:
            con.close()

    @bp.route('/api/finans-cari-kimlik/tedarikci/<int:nexgen_tedarikci_id>/iptal', methods=['POST'])
    @login_gerekli
    def api_fck_tedarikci_iptal(nexgen_tedarikci_id):
        _write_tedarikci_guard()
        reason = (_body().get('reason') or '').strip()
        if not reason:
            return _api_err('NEDEN_ZORUNLU', 'reason zorunlu.', 400)
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            es = iptal_tedarikci_eslestirme(
                con, nexgen_tedarikci_id, reason, user_id=_uid(), commit=False,
            )
            con.commit()
            return _api_ok(data={'eslestirme': es})
        except FinansCariKimlikError as e:
            con.rollback()
            return _domain_err(e)
        finally:
            con.close()

    @bp.route('/api/finans-cari-kimlik/<int:kimlik_id>/manuel-override', methods=['POST'])
    @login_gerekli
    def api_fck_manuel_override(kimlik_id):
        _manuel_guard()
        data = _body()
        override_reason = (data.get('override_reason') or '').strip()
        if not override_reason:
            return _api_err('OVERRIDE_REASON_ZORUNLU', 'override_reason zorunlu.', 400)
        ckod = (data.get('cari_kart_ckod') or '').strip()
        if not ckod:
            return _api_err('CKOD_ZORUNLU', 'cari_kart_ckod zorunlu.', 400)
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            before = detay(con, kimlik_id)
            paket = apply_manuel_kimlik_override(
                con, kimlik_id, ckod, override_reason,
                user_id=_uid(), notlar=data.get('notlar'), commit=False,
            )
            con.commit()
            return _api_ok(
                data={'kimlik': paket},
                audit=_audit_meta(
                    'manuel_override', 'finans_cari_kimlik', kimlik_id,
                    reason=override_reason,
                    before_durum=before.get('durum'),
                    after_durum=paket.get('durum'),
                ),
            )
        except FinansCariKimlikError as e:
            con.rollback()
            return _domain_err(e)
        except Exception:
            con.rollback()
            _log.exception('fck manuel override hatasi')
            return _api_err('SUNUCU_HATASI', 'Manuel override basarisiz.', 500)
        finally:
            con.close()

    @bp.route('/api/finans-cari-kimlik/<int:kimlik_id>/pasife-al', methods=['POST'])
    @login_gerekli
    def api_fck_pasife_al(kimlik_id):
        con_pre = db_fn()
        try:
            pre = detay(con_pre, kimlik_id)
        except FinansCariKimlikError as e:
            con_pre.close()
            return _domain_err(e)
        con_pre.close()
        if pre.get('kimlik_tipi') == 'MUSTERI':
            _write_musteri_guard()
        else:
            _write_tedarikci_guard()
        reason = (_body().get('reason') or '').strip()
        if not reason:
            return _api_err('NEDEN_ZORUNLU', 'reason zorunlu.', 400)
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            paket = deactivate_kimlik(con, kimlik_id, reason, user_id=_uid(), commit=False)
            con.commit()
            return _api_ok(
                data={'kimlik': paket},
                audit=_audit_meta('deactivate', 'finans_cari_kimlik', kimlik_id, reason=reason),
            )
        except FinansCariKimlikError as e:
            con.rollback()
            return _domain_err(e)
        finally:
            con.close()

    @bp.route('/api/finans-cari-kimlik/<int:kimlik_id>/yeniden-aktif', methods=['POST'])
    @login_gerekli
    def api_fck_yeniden_aktif(kimlik_id):
        con_pre = db_fn()
        try:
            pre = detay(con_pre, kimlik_id)
        except FinansCariKimlikError as e:
            con_pre.close()
            return _domain_err(e)
        con_pre.close()
        if pre.get('kimlik_tipi') == 'MUSTERI':
            _write_musteri_guard()
        else:
            _write_tedarikci_guard()
        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            paket = reactivate_kimlik(con, kimlik_id, user_id=_uid(), commit=False)
            con.commit()
            return _api_ok(
                data={'kimlik': paket},
                audit=_audit_meta('reactivate', 'finans_cari_kimlik', kimlik_id),
            )
        except FinansCariKimlikError as e:
            con.rollback()
            return _domain_err(e)
        finally:
            con.close()
