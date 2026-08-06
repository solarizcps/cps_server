# -*- coding: utf-8 -*-
"""
CPS DEV - Ana Uygulama (Faz 1)
===============================
Flask ana giriş noktası. Tüm modülleri kayıt eder, yetki sistemi aktif.

Çalıştır:
    python app.py
Tarayıcıdan:
    http://127.0.0.1:5057/
"""
from flask import Flask, render_template, session, g, redirect, url_for, request, flash, jsonify
from datetime import timedelta, datetime, date
from config import Config

# Blueprint'ler
from modules.auth import (auth_bp, kullanici_yetkileri, yetki_var,
                          sistem_session_gecerli_mi, AUTH_1B_SESSION_MESSAGE)
from modules.nexgen.mo_depo_yetki import is_nexgen_depo_sade_kullanici
from modules.nexgen.mo_arge_tablet_yetki import is_nexgen_arge_tablet_kullanici
from modules.finans import finans_bp
from modules.yonetim import yonetim_bp
from modules.grafik import grafik_bp
from modules.ithalat import ithalat_bp
from modules.hedef import hedef_bp
from modules.hedef import plan_v2_bp
from modules.uretim_giris import uretim_giris_bp
from modules.canli_saha.routes import canli_saha_bp  # CANLI_SAHA_BRIDGE
from modules.personel_giris import personel_giris_bp  # PERSONEL_GIRIS_BRIDGE
from modules.usta import usta_bp
from modules.uretim_yonetim.routes import uretim_yonetim_bp
from modules.planlama.routes import planlama_bp
from modules.planlama.proses_takip import proses_takip_bp
from modules.tasks import tasks_bp
from modules.enjeksiyon import enjeksiyon_bp  # ENJ_F3_IMPORT
from modules.saha import saha_bp  # SAHA_NUMUNE_TALEP_FAZ1
from modules.online_eticaret import online_eticaret_bp  # OET_FAZ0
from modules.fuar_crm import fuar_crm_bp  # FUAR_CRM_FAZ1
from modules.nexgen import nexgen_bp  # NEXGEN_FAZ1A
from modules.home import home_bp  # HOME_KORGUN_BITEN


app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY
app.permanent_session_lifetime = timedelta(days=Config.SESSION_DAYS)
app.config['MAX_CONTENT_LENGTH'] = Config.MAX_UPLOAD_MB * 1024 * 1024
# Flask DEBUG=True modunda errorhandler bypass edilir; bu satir hata sayfasini etkinlestirir
app.config['PROPAGATE_EXCEPTIONS'] = False

# MODÜLLER
app.register_blueprint(auth_bp)
app.register_blueprint(finans_bp)
app.register_blueprint(yonetim_bp)
app.register_blueprint(grafik_bp)
app.register_blueprint(ithalat_bp)
app.register_blueprint(hedef_bp)
app.register_blueprint(plan_v2_bp)
app.register_blueprint(uretim_giris_bp)
app.register_blueprint(usta_bp)
app.register_blueprint(uretim_yonetim_bp)
app.register_blueprint(planlama_bp)
app.register_blueprint(proses_takip_bp)
app.register_blueprint(tasks_bp)
app.register_blueprint(canli_saha_bp)  # CANLI_SAHA_BRIDGE
app.register_blueprint(personel_giris_bp)  # PERSONEL_GIRIS_BRIDGE
app.register_blueprint(enjeksiyon_bp)  # ENJ_F3_REGISTER
app.register_blueprint(saha_bp)  # SAHA_NUMUNE_TALEP_FAZ1 (reload)
app.register_blueprint(online_eticaret_bp)  # OET_FAZ0
app.register_blueprint(fuar_crm_bp)  # FUAR_CRM_FAZ1
app.register_blueprint(nexgen_bp)  # NEXGEN_FAZ1A
app.register_blueprint(home_bp)  # HOME_KORGUN_BITEN


# ============================================================
# GLOBAL BEFORE/AFTER
# ============================================================
@app.before_request
def oturum_kontrol():
    g.user = session.get('kullanici')

    yol = request.path
    acik = (yol.startswith('/static')
            or yol.startswith('/giris')
            or yol.startswith('/personel-giris')
            or yol == '/favicon.ico')

    if g.user and not acik and not sistem_session_gecerli_mi(g.user):
        session.clear()
        flash(AUTH_1B_SESSION_MESSAGE, 'uyari')
        return redirect(url_for('auth.login'))

    # Yetki cache
    if g.user:
        g.yetkiler = kullanici_yetkileri(g.user)
    else:
        g.yetkiler = set()

    # Login gerektirmeyen
    if acik:
        return

    if not g.user:
        return redirect(url_for('auth.login', next=yol))

    # Zorunlu şifre değiştir ise sadece o sayfaya izin
    if g.user.get('ZorunluSifreDegistir') and yol not in ('/sifre-degistir', '/cikis'):
        return redirect(url_for('auth.sifre_degistir'))

    # VEDAT_APP_GUARD: AR-GE tablet kullanıcısı için app-level URL kilidi
    if is_nexgen_arge_tablet_kullanici(g.user):
        from modules.nexgen.mo_arge_tablet_yetki import nexgen_arge_tablet_path_ok
        if not nexgen_arge_tablet_path_ok(yol):
            if yol.startswith('/nexgen/api/') or yol.startswith('/api/'):
                from flask import jsonify
                return jsonify(error='Yetkisiz'), 403
            return redirect('/nexgen/tablet/arge')


# ============================================================
# ROUTES
# ============================================================
@app.route('/')
def index():
    if session.get('kullanici') and is_nexgen_arge_tablet_kullanici(session.get('kullanici')):
        return redirect('/nexgen/tablet/arge')
    return render_template('index.html', db_mode=Config.DB_MODE)


# ============================================================
# CONTEXT / FILTER'lar
# ============================================================
@app.context_processor
def inject_globals():
    u = session.get('kullanici')
    yetkiler = g.get('yetkiler', set()) if u else set()
    can_mo_menu = False
    if u:
        try:
            from modules.auth import kullanici_yetkileri
            from modules.nexgen.cari360_yetki import can_musteri_pazarlama_menu
            can_mo_menu = bool(can_musteri_pazarlama_menu(kullanici_yetkileri(u)))
        except Exception:
            can_mo_menu = False
    return {
        'DB_MODE':    Config.DB_MODE,
        'APP_NAME':   'CPS Dev',
        'now':        date.today().strftime('%Y-%m-%d'),
        'g_user':     u,
        'g_yetkiler': yetkiler,
        'yetki':      yetki_var,
        'depo_sade_mod': is_nexgen_depo_sade_kullanici(u) if u else False,
        'arge_tablet_mod': is_nexgen_arge_tablet_kullanici(session.get('kullanici')) if session.get('kullanici') else False,
        'can_musteri_operasyonu_menu': can_mo_menu,
    }


@app.template_filter('tarih_obj')
def filter_tarih_obj(value):
    if not value:
        return date.today()
    s = str(value)[:10]
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except Exception:
        return date.today()


@app.template_filter('tl')
def format_tl(value):
    if value is None:
        return '—'
    try:
        f = float(value)
        sign = '-' if f < 0 else ''
        f = abs(f)
        s = f"{f:,.2f}"
        s = s.replace(',', 'X').replace('.', ',').replace('X', '.')
        return f"{sign}{s} ₺"
    except (TypeError, ValueError):
        return str(value)


@app.template_filter('usd')
def format_usd(value):
    if value is None:
        return '—'
    try:
        f = float(value)
        sign = '-' if f < 0 else ''
        f = abs(f)
        s = f"{f:,.2f}"
        s = s.replace(',', 'X').replace('.', ',').replace('X', '.')
        return f"{sign}${s}"
    except (TypeError, ValueError):
        return str(value)


@app.template_filter('para')
def format_para(value, birim='TRY'):
    """Genel para formatı, birime göre sembol."""
    if value is None:
        return '—'
    sembol = {'TRY': '₺', 'USD': '$', 'EUR': '€', 'CNY': '¥'}.get(birim, birim)
    try:
        f = float(value)
        sign = '-' if f < 0 else ''
        f = abs(f)
        s = f"{f:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        if birim == 'TRY':
            return f"{sign}{s} ₺"
        return f"{sign}{sembol}{s}"
    except (TypeError, ValueError):
        return str(value)


@app.template_filter('sayi')
def format_sayi(value):
    if value is None:
        return '—'
    try:
        return f"{int(value):,}".replace(',', '.')
    except (TypeError, ValueError):
        return str(value)


@app.template_filter('tarih')
def format_tarih(value):
    if not value:
        return '—'
    s = str(value)[:10]
    try:
        y, m, d = s.split('-')
        return f"{d}.{m}.{y}"
    except ValueError:
        return s


@app.template_filter('tarih_saat')
def format_tarih_saat(value):
    if not value:
        return '—'
    s = str(value)
    if len(s) < 16:
        return format_tarih(s)
    try:
        t = s[:10]; sa = s[11:16]
        y, m, d = t.split('-')
        return f"{d}.{m}.{y} {sa}"
    except Exception:
        return s


@app.template_filter('boyut')
def format_boyut(b):
    """1024 -> 1 KB, 1048576 -> 1 MB"""
    if b is None:
        return '—'
    try:
        b = int(b)
    except Exception:
        return str(b)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if b < 1024:
            return f"{b} {unit}"
        b //= 1024
    return f"{b} TB"


# ============================================================
# HATA SAYFALARI
# ============================================================
def _wants_json_error_response() -> bool:
    """API/fetch isteklerinde HTML hata sayfası / referer redirect JSON'u bozar.

    FAZ-GLOBAL-UNEXPECTED-TOKEN-HTML-ROOTCAUSE-FIX:
    /yonetim/api/*, /enjeksiyon/api/* vb. path.startswith('/api/') ile
    yakalanmıyordu; 404/500 → Referer HTML → Unexpected token '<'.
    """
    path = request.path or ''
    if '/api/' in path:
        return True
    accept = (request.headers.get('Accept') or '')
    if 'application/json' in accept:
        return True
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    return False


@app.errorhandler(413)
def hata_413(e):
    if _wants_json_error_response():
        return jsonify({
            'ok': False,
            'error': 'PAYLOAD_TOO_LARGE',
            'hata': 'Yüklenen dosya boyut limitini aşıyor.',
        }), 413
    ref = request.referrer
    if ref and request.host in ref:
        try:
            from urllib.parse import urlparse
            if urlparse(ref).path != request.path:
                flash('⚠ Yüklenen dosya çok büyük. Lütfen daha küçük bir dosya seçin.', 'hata')
                return redirect(ref)
        except Exception:
            pass
    return render_template('hata.html',
                           kod=413, baslik='Dosya Çok Büyük',
                           mesaj='Yüklenen dosya boyut limitini aşıyor.'), 413


@app.errorhandler(403)
def hata_403(e):
    if _wants_json_error_response():
        return jsonify({
            'ok': False,
            'error': 'FORBIDDEN',
            'hata': 'Bu işlem için yetkiniz yok.',
        }), 403
    return render_template('hata.html',
                           kod=403, baslik='Yetkisiz Erişim',
                           mesaj='Bu sayfaya erişim yetkiniz yok.'), 403


@app.errorhandler(404)
def hata_404(e):
    # FAZ-DEPLOY-MIGRATION-KALICI-DUZELTME-1 + GLOBAL-UNEXPECTED-TOKEN fix
    path = request.path or ''
    try:
        app.logger.warning('404 path=%s ref=%s', path, request.referrer)
    except Exception:
        pass
    if _wants_json_error_response():
        return jsonify({
            'ok': False,
            'error': 'NOT_FOUND',
            'hata': 'İstenen servis bulunamadı.',
            'path': path,
        }), 404

    ref = request.referrer
    if ref and request.host in ref:
        try:
            from urllib.parse import urlparse
            ref_path = urlparse(ref).path
            if ref_path != path:
                # Aynı flash'ı oturumda biriktirme
                msgs = session.get('_flashes') or []
                already = any(
                    (isinstance(m, tuple) and len(m) > 1 and 'Sayfa bulunamadı' in str(m[1]))
                    for m in msgs
                )
                if not already:
                    flash('⚠ Sayfa bulunamadı — önceki sayfaya döndünüz.', 'uyari')
                return redirect(ref)
        except Exception:
            pass
    return render_template('hata.html',
                           kod=404, baslik='Sayfa Bulunamadı',
                           mesaj='Aradığınız sayfa bulunamadı.'), 404


@app.errorhandler(500)
def hata_500(e):
    # 1) Audit log'a yaz (teknik detay kullanıcıya gösterilmez)
    try:
        from modules import audit
        from flask import session as _s
        kullanici = _s.get('kullanici', 'anonim')
        exc_ozet = type(e).__name__ + ': ' + (str(e)[:240] if str(e) else 'N/A')
        audit.log_olay(kullanici, 'SISTEM_HATASI', 'system', 0,
                       aciklama=f"500 hatası: path={request.path}, exc={exc_ozet}",
                       modul='system', alt_modul='error')
    except Exception:
        # Log kendi hata verdiyse (audit tablosu down olabilir) sessiz geç
        pass

    # 2) API/fetch → JSON (Referer HTML redirect JSON.parse'i bozar)
    if _wants_json_error_response():
        return jsonify({
            'ok': False,
            'error': 'SERVER_ERROR',
            'hata': 'Beklenmedik bir sunucu hatası oluştu.',
            'path': request.path or '',
        }), 500

    # 3) Sayfa istekleri: friendly mesaj + referer varsa geri yönlendir
    ref = request.referrer
    if ref and request.host in ref:
        try:
            from urllib.parse import urlparse
            if urlparse(ref).path != request.path:
                flash('⚠ Sistem hatası oluştu — önceki sayfaya döndünüz. '
                      'Sorun devam ederse teknik ekibe bildirin.', 'hata')
                return redirect(ref)
        except Exception:
            pass
    return render_template('hata.html',
                           kod=500, baslik='Sunucu Hatası',
                           mesaj='Beklenmedik bir hata oluştu. '
                                 'Teknik ekibe otomatik bildirildi.'), 500


# ============================================================
# BAŞLAT
# ============================================================
if __name__ == '__main__':
    # -------------------------------------------------------
    # BAŞLANGIÇ KORUMASI: mock_data.db yoksa sessizce devam etme
    # -------------------------------------------------------
    import os as _os
    _db_check = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'mock_data.db')
    if not _os.path.exists(_db_check):
        print("=" * 60)
        print("  [KRITIK HATA] Canlı veritabanı bulunamadı!")
        print(f"  Beklenen konum: {_db_check}")
        print("  Uygulama başlatılmadı.")
        print("  Çözüm: mock_data.db dosyasını bu konuma kopyalayın,")
        print("         ardından uygulamayı yeniden başlatın.")
        print("=" * 60)
        import sys as _sys
        _sys.exit(1)
    elif _os.path.getsize(_db_check) < 1024:
        print("=" * 60)
        print("  [KRITIK HATA] Veritabanı dosyası boş veya bozuk!")
        print(f"  Konum: {_db_check}")
        print(f"  Boyut: {_os.path.getsize(_db_check)} bytes (min 1024 bekleniyor)")
        print("  Uygulama başlatılmadı.")
        print("=" * 60)
        import sys as _sys
        _sys.exit(1)
    # -------------------------------------------------------
    print("=" * 60)
    print(f"  CPS DEV — Faz 1")
    print(f"  DB_MODE: {Config.DB_MODE}")
    print(f"  URL:     http://127.0.0.1:{Config.PORT}/")
    print(f"  Giris:   http://127.0.0.1:{Config.PORT}/giris")
    print(f"  Yonetim: http://127.0.0.1:{Config.PORT}/yonetim/")
    print(f"  Finans:  http://127.0.0.1:{Config.PORT}/finans/")
    print(f"  Ithalat: http://127.0.0.1:{Config.PORT}/ithalat/parti/liste")
    print("=" * 60)
    # CPS_DEBUG_ENV_AWARE_V1: FLASK_DEBUG env varsa onu kullan
    import os as _os
    _dbg_env = _os.environ.get('FLASK_DEBUG')
    if _dbg_env is not None:
        _dbg = _dbg_env not in ('0', 'false', 'False', '')
    else:
        _dbg = Config.DEBUG
    app.run(host=Config.HOST, port=Config.PORT, debug=_dbg)

