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
