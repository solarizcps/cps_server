# -*- coding: utf-8 -*-
"""Ana sayfa salt-okunur API'leri."""
from functools import wraps

from flask import Blueprint, jsonify, request, session

from modules.auth import yetki_var

home_bp = Blueprint('home_api', __name__)

_HOME_KORGUN_USERS = frozenset({'admin', 'altan', 'alpay', 'mehmet'})


def _home_korgun_izinli():
    u = session.get('kullanici') or {}
    if not u:
        return False
    try:
        from flask import g
        if g.get('yetkiler') and '*' in g.yetkiler:
            return True
    except Exception:
        pass
    ka = (u.get('KullaniciAdi') or '').strip().lower()
    if ka in _HOME_KORGUN_USERS:
        return True
    rol = (u.get('RolAd') or u.get('Rol') or '').strip().lower()
    if 'sistem yöneticisi' in rol or 'sistem yoneticisi' in rol or rol == 'admin':
        return True
    if yetki_var('planlama.proses_takip', 'can_view'):
        return True
    return False


def home_korgun_gerekli(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('kullanici'):
            return jsonify({'ok': False, 'error': 'Oturum gerekli'}), 401
        if not _home_korgun_izinli():
            return jsonify({'ok': False, 'error': 'Yetkisiz'}), 403
        return f(*args, **kwargs)
    return wrapper


@home_bp.route('/api/home/korgun/biten-prosesler', methods=['GET'])
@home_korgun_gerekli
def api_home_korgun_biten_prosesler():
    """GET /api/home/korgun/biten-prosesler?period=bugun|dun|hafta|ay"""
    from modules.common.korgun_biten_proses import (
        VALID_PERIODS,
        KorgunBitenBagError,
        KorgunBitenPeriodError,
        get_home_biten_prosesler,
    )
    period = (request.args.get('period') or 'bugun').strip().lower()
    if period not in VALID_PERIODS:
        return jsonify({
            'ok': False,
            'error': 'Geçersiz period. Kullanım: bugun|dun|hafta|ay',
            'period': period,
        }), 400
    try:
        return jsonify(get_home_biten_prosesler(period=period))
    except KorgunBitenPeriodError:
        return jsonify({
            'ok': False,
            'error': 'Geçersiz period. Kullanım: bugun|dun|hafta|ay',
            'period': period,
        }), 400
    except KorgunBitenBagError:
        return jsonify({
            'ok': False,
            'error': 'Korgun bağlantısı kurulamadı',
            'source': 'Korgun Solariz22 / Urt_con_gch',
            'period': period,
        }), 503
    except Exception:
        return jsonify({
            'ok': False,
            'error': 'Korgun bağlantısı kurulamadı',
            'source': 'Korgun Solariz22 / Urt_con_gch',
            'period': period,
        }), 503


@home_bp.route('/api/home/korgun/proses-detay', methods=['GET'])
@home_korgun_gerekli
def api_home_korgun_proses_detay():
    """GET /api/home/korgun/proses-detay?proses=02&period=hafta&chart=hafta|ay"""
    from modules.common.korgun_biten_proses import (
        VALID_PERIODS,
        KorgunBitenBagError,
        KorgunBitenPeriodError,
        get_proses_detay,
    )
    proses = (request.args.get('proses') or '').strip()
    period = (request.args.get('period') or 'hafta').strip().lower()
    chart = (request.args.get('chart') or 'hafta').strip().lower()
    if not proses:
        return jsonify({'ok': False, 'error': 'proses parametresi gerekli'}), 400
    if period not in VALID_PERIODS:
        return jsonify({
            'ok': False,
            'error': 'Geçersiz period. Kullanım: bugun|dun|hafta|ay',
            'period': period,
        }), 400
    try:
        return jsonify(get_proses_detay(proses, period=period, chart_mode=chart))
    except KorgunBitenPeriodError as e:
        return jsonify({'ok': False, 'error': str(e) or 'Geçersiz parametre'}), 400
    except KorgunBitenBagError:
        return jsonify({
            'ok': False,
            'error': 'Korgun bağlantısı kurulamadı',
            'source': 'Korgun Solariz22 / Urt_con_gch',
        }), 503
    except Exception:
        return jsonify({
            'ok': False,
            'error': 'Korgun bağlantısı kurulamadı',
            'source': 'Korgun Solariz22 / Urt_con_gch',
        }), 503


def _home_nexgen_izinli():
    """Ana Özet: oturum + (Korgun allowlist / admin / NexGen view). Depo-sade yok."""
    try:
        from modules.nexgen.mo_depo_yetki import is_nexgen_depo_sade_kullanici
        if is_nexgen_depo_sade_kullanici():
            return False
    except Exception:
        pass
    if _home_korgun_izinli():
        return True
    if yetki_var('nexgen.recete.view', 'can_view'):
        return True
    if yetki_var('nexgen.pazarlama.view', 'can_view'):
        return True
    if yetki_var('nexgen.planlama.view', 'can_view'):
        return True
    return False


def home_nexgen_gerekli(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('kullanici'):
            return jsonify({'ok': False, 'error': 'Oturum gerekli'}), 401
        if not _home_nexgen_izinli():
            return jsonify({'ok': False, 'error': 'Yetkisiz'}), 403
        return f(*args, **kwargs)
    return wrapper


@home_bp.route('/api/home/nexgen/ozet', methods=['GET'])
@home_nexgen_gerekli
def api_home_nexgen_ozet():
    """GET /api/home/nexgen/ozet — salt okunur NexGen Ana Özet aggregator."""
    from modules.home.nexgen_ozet_service import get_nexgen_ana_ozet, NexgenOzetError
    try:
        payload = get_nexgen_ana_ozet()
        if not payload.get('ok'):
            return jsonify(payload), 503
        return jsonify(payload)
    except NexgenOzetError as e:
        return jsonify({'ok': False, 'error': str(e)}), 503
    except Exception:
        return jsonify({'ok': False, 'error': 'NexGen özet alınamadı'}), 503
