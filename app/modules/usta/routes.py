# -*- coding: utf-8 -*-
"""CPS DEV - Usta Routes (Faz 4.2)

Mobile-first usta paneli. Sayfa render eder.
Veri MES v2 API'sinden (port 5070) JS tarafindan fetch edilir.

Endpoint'ler:
    GET /usta/  - Ana panel (3 sekme: acik isler, veri giris, onay)

Yetki:
    Login yapmis herhangi bir kullanici (rol 'usta', 'admin', 'Yonetim').
    Yonetim ve admin de panele girebilir (test/yonetim icin).
"""
from flask import (Blueprint, render_template, redirect, url_for,
                   request, session, abort)
from functools import wraps

usta_bp = Blueprint('usta', __name__, url_prefix='/usta')


def _usta_yetkili_mi():
    u = session.get('kullanici')
    if not u:
        return False
    # Login yapmis herkes USTA panele erisebilir.
    # Hedef sayfasi sadece admin/yonetim, USTA panel daha genis kapsam.
    # Veri kapsamini service_usta.py icindeki rol parametresi ayarliyor.
    return True


def usta_yetkili(f):
    """Decorator: login zorunlu. Rol kontrolu MES v2 servis katmaninda."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('kullanici'):
            return redirect(url_for('auth.login', next=request.path))
        if not _usta_yetkili_mi():
            abort(403)
        return f(*args, **kwargs)
    return wrapper


# ============== ANA PANEL ==============
@usta_bp.route('/')
@usta_yetkili
def panel():
    """Usta ana paneli - 3 sekme."""
    return render_template('usta/index.html')


# ============== FAZ 4.3 - GOREV ENDPOINTLERI ==============
# Karar Masasi -> Usta Paneli pilot baglantisi
# uretim_kayit ile iliskisi yok, tamamen izole sandbox

from flask import jsonify, request as _flask_request
from . import gorev_db as _gorev_db


@usta_bp.route('/api/gorevler', methods=['GET'])
@usta_yetkili
def gorevler_liste():
    """
    Usta gorev listesi.

    Query parametreleri:
        durum=acik|tamam|iptal|hepsi (default: acik)
        atanan=Hasan (opsiyonel, NULL olanlar da dahil)
    """
    durum_filtresi = _flask_request.args.get('durum', 'acik')
    atanan = _flask_request.args.get('atanan')

    sonuc = _gorev_db.gorev_listele(
        durum_filtresi=durum_filtresi,
        atanan=atanan
    )
    return jsonify(sonuc)


@usta_bp.route('/api/gorev/<int:gorev_id>/okudu', methods=['POST'])
@usta_yetkili
def gorev_okudu_endpoint(gorev_id):
    """ATANDI -> OKUNDU"""
    sonuc = _gorev_db.gorev_okudu(gorev_id)
    if not sonuc.get("ok"):
        if sonuc.get("hata") == "bulunamadi":
            return jsonify(sonuc), 404
        if sonuc.get("hata") == "durum_uyumsuz":
            return jsonify(sonuc), 409
        return jsonify(sonuc), 400
    return jsonify(sonuc)


@usta_bp.route('/api/gorev/<int:gorev_id>/basladi', methods=['POST'])
@usta_yetkili
def gorev_basladi_endpoint(gorev_id):
    """OKUNDU -> BASLADI"""
    sonuc = _gorev_db.gorev_basladi(gorev_id)
    if not sonuc.get("ok"):
        if sonuc.get("hata") == "bulunamadi":
            return jsonify(sonuc), 404
        if sonuc.get("hata") == "durum_uyumsuz":
            return jsonify(sonuc), 409
        return jsonify(sonuc), 400
    return jsonify(sonuc)


@usta_bp.route('/api/gorev/<int:gorev_id>/bitti', methods=['POST'])
@usta_yetkili
def gorev_bitti_endpoint(gorev_id):
    """BASLADI -> TAMAMLANDI (opsiyonel usta_notu)"""
    body = _flask_request.get_json(silent=True) or {}
    usta_notu = body.get('usta_notu')

    sonuc = _gorev_db.gorev_bitti(gorev_id, usta_notu=usta_notu)
    if not sonuc.get("ok"):
        if sonuc.get("hata") == "bulunamadi":
            return jsonify(sonuc), 404
        if sonuc.get("hata") == "durum_uyumsuz":
            return jsonify(sonuc), 409
        return jsonify(sonuc), 400
    return jsonify(sonuc)
