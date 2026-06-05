# -*- coding: utf-8 -*-
"""CPS DEV - Yönetim Routes"""
from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, abort, send_file, flash)
from functools import wraps
import os

from modules.yonetim import queries as qr
from modules import audit, belge as belge_srv
from modules.auth import yetki_var
from config import Config

yonetim_bp = Blueprint('yonetim', __name__, url_prefix='/yonetim')


def _u():
    k = session.get('kullanici')
    return k['KullaniciAdi'] if k else 'sistem'


def _admin_mi():
    u = session.get('kullanici')
    if not u:
        return False
    if u.get('KullaniciAdi') == 'admin':
        return True
    return u.get('RolAd') == 'Yönetim'


def admin_gerekli(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('kullanici'):
            return redirect(url_for('auth.login', next=request.path))
        if not _admin_mi():
            abort(403)
        return f(*args, **kwargs)
    return wrapper


# ============== PANEL ==============
@yonetim_bp.route('/')
@admin_gerekli
def panel():
    return render_template('yonetim/panel.html',
                           kpi=qr.yonetim_kpi(),
                           son_loglar=audit.son_loglar(limit=20))


# ============== KULLANICI ==============
@yonetim_bp.route('/kullanici')
@admin_gerekli
def kullanici_liste():
    return render_template('yonetim/kullanici_liste.html',
                           kullanicilar=qr.kullanici_liste(),
                           roller=qr.yetki_secimlik_liste())


@yonetim_bp.route('/kullanici/yeni', methods=['POST'])
@admin_gerekli
def kullanici_yeni():
    try:
        veri = {
            'KullaniciAdi': request.form.get('KullaniciAdi', '').strip().lower(),
            'AdSoyad': request.form.get('AdSoyad', '').strip(),
            'Email': request.form.get('Email', '').strip() or None,
            'Sifre': request.form.get('Sifre', '').strip() or '1234',
            'RolId': request.form.get('RolId') or None,
            'Aktif': 1,
        }
        qr.kullanici_ekle(veri, kullanici=_u())
        flash('Kullanıcı eklendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('yonetim.kullanici_liste'))


@yonetim_bp.route('/kullanici/<int:kullanici_id>/guncelle', methods=['POST'])
@admin_gerekli
def kullanici_guncelle(kullanici_id):
    veri = {
        'AdSoyad': request.form.get('AdSoyad', '').strip(),
        'Email':   request.form.get('Email', '').strip() or None,
        'RolId':   request.form.get('RolId') or None,
        'Aktif':   1 if request.form.get('Aktif') else 0,
    }
    try:
        qr.kullanici_guncelle(kullanici_id, veri, kullanici=_u())
        flash('Güncellendi.', 'ok')
    except Exception as e:
        flash(str(e), 'hata')
    return redirect(url_for('yonetim.kullanici_liste'))


@yonetim_bp.route('/kullanici/<int:kullanici_id>/sifre-sifirla', methods=['POST'])
@admin_gerekli
def kullanici_sifre_sifirla(kullanici_id):
    yeni = request.form.get('yeni_sifre', '').strip() or '1234'
    qr.kullanici_sifre_sifirla(kullanici_id, yeni, kullanici=_u())
    flash(f'Şifre sıfırlandı. Yeni: {yeni}', 'ok')
    return redirect(url_for('yonetim.kullanici_liste'))


@yonetim_bp.route('/kullanici/<int:kullanici_id>/pasif', methods=['POST'])
@admin_gerekli
def kullanici_pasif(kullanici_id):
    u = session.get('kullanici')
    if u and int(u.get('Id', 0)) == kullanici_id:
        flash('Kendinizi pasif edemezsiniz.', 'hata')
        return redirect(url_for('yonetim.kullanici_liste'))
    aktif = request.form.get('aktif') == '1'
    qr.kullanici_pasif(kullanici_id, kullanici=_u(), aktif=aktif)
    flash('Durum güncellendi.', 'ok')
    return redirect(url_for('yonetim.kullanici_liste'))


# ============== ROL ==============
@yonetim_bp.route('/rol')
@admin_gerekli
def rol_liste():
    return render_template('yonetim/rol_liste.html', roller=qr.rol_liste())


@yonetim_bp.route('/rol/yeni', methods=['POST'])
@admin_gerekli
def rol_yeni():
    ad = request.form.get('Ad', '').strip()
    ac = request.form.get('Aciklama', '').strip() or None
    if not ad:
        flash('Rol adı zorunlu', 'hata')
        return redirect(url_for('yonetim.rol_liste'))
    try:
        rid = qr.rol_ekle(ad, ac, kullanici=_u())
        return redirect(url_for('yonetim.rol_detay', rol_id=rid))
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('yonetim.rol_liste'))


@yonetim_bp.route('/rol/<int:rol_id>')
@admin_gerekli
def rol_detay(rol_id):
    rol = qr.rol_tek(rol_id)
    if not rol:
        abort(404)
    tum = qr.yetki_liste()
    mevcut = qr.rol_yetkileri(rol_id)
    gruplar = {}
    for y in tum:
        k = f"{y['Modul']}/{y['AltModul'] or '-'}"
        gruplar.setdefault(k, {'modul': y['Modul'], 'alt_modul': y['AltModul'] or '',
                               'yetkiler': []})['yetkiler'].append(y)
    return render_template('yonetim/rol_detay.html',
                           rol=rol, gruplar=gruplar, mevcut=mevcut)


@yonetim_bp.route('/rol/<int:rol_id>/kaydet', methods=['POST'])
@admin_gerekli
def rol_kaydet(rol_id):
    ad = request.form.get('Ad', '').strip()
    ac = request.form.get('Aciklama', '').strip() or None
    if ad:
        qr.rol_guncelle(rol_id, ad, ac, kullanici=_u())
    yetki_map = {}
    for y in qr.yetki_liste():
        yid = y['Id']
        g = request.form.get(f'gor_{yid}') == '1'
        d = request.form.get(f'duz_{yid}') == '1'
        yetki_map[yid] = {'gor': g, 'duz': d}
    qr.rol_yetki_kaydet(rol_id, yetki_map, kullanici=_u())
    flash('Rol ve yetkiler kaydedildi.', 'ok')
    return redirect(url_for('yonetim.rol_detay', rol_id=rol_id))


@yonetim_bp.route('/rol/<int:rol_id>/sil', methods=['POST'])
@admin_gerekli
def rol_sil(rol_id):
    try:
        qr.rol_sil(rol_id, kullanici=_u())
        flash('Rol silindi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('yonetim.rol_liste'))


# ============== KUR ==============
@yonetim_bp.route('/kur')
@admin_gerekli
def kur_liste():
    from datetime import date
    return render_template('yonetim/kur_liste.html',
                           kurlar=qr.kur_liste(limit=120),
                           usd=qr.kur_guncel('USD'),
                           eur=qr.kur_guncel('EUR'),
                           cny=qr.kur_guncel('CNY'),
                           bugun=date.today().strftime('%Y-%m-%d'))


@yonetim_bp.route('/kur/yeni', methods=['POST'])
@admin_gerekli
def kur_yeni():
    try:
        tarih = request.form.get('Tarih', '').strip()
        pb = request.form.get('ParaBirimi', '').strip().upper()
        alis = float(request.form.get('Alis') or 0)
        satis = float(request.form.get('Satis') or 0)
        if not tarih or pb not in ('USD', 'EUR', 'CNY'):
            raise ValueError('Geçersiz veri')
        if alis <= 0 or satis <= 0:
            raise ValueError('Alış ve satış > 0 olmalı')
        qr.kur_ekle(tarih, pb, alis, satis, kullanici=_u())
        flash('Kur kaydedildi.', 'ok')
    except Exception as e:
        flash(str(e), 'hata')
    return redirect(url_for('yonetim.kur_liste'))


@yonetim_bp.route('/kur/<int:kur_id>/sil', methods=['POST'])
@admin_gerekli
def kur_sil(kur_id):
    qr.kur_sil(kur_id, kullanici=_u())
    flash('Kur silindi.', 'ok')
    return redirect(url_for('yonetim.kur_liste'))


# ============== KUR MINI-API (Parça 5.5) ==============
# Masraf modal + teklif modal UI için: seçilen PB için kur var mı? canlı check.
@yonetim_bp.route('/kur/api')
def kur_api():
    """
    GET /yonetim/kur/api?pb=USD
    → JSON: { ok: bool, kur: float|null, tarih: str|null, hata: str|null }

    Yetki: giriş yapmış kullanıcı + ilgili rollerden biri (Yönetim / Grafik / Muhasebe / Çin Ofis).
    Kur bilgisi operasyonel — sadece teknik kontrol amaçlı, salt-okunur.
    """
    from flask import jsonify
    u = session.get('kullanici')
    if not u:
        return jsonify({'ok': False, 'hata': 'Giriş gerekli'}), 401
    rol = u.get('RolAd') or ''
    # Sadece iş rollerine açık (public API değil)
    if rol not in ('Yönetim', 'Grafik', 'Muhasebe', 'Çin Ofis'):
        return jsonify({'ok': False, 'hata': 'Yetkisiz'}), 403

    pb = (request.args.get('pb') or '').strip().upper()
    if pb == 'TRY':
        return jsonify({'ok': True, 'kur': 1.0, 'tarih': None, 'kaynak': 'SABIT'})
    if pb not in ('USD', 'EUR', 'CNY'):
        return jsonify({'ok': False, 'hata': f'Geçersiz para birimi: {pb}'}), 400

    kr = qr.kur_guncel(pb)
    if not kr:
        return jsonify({'ok': False, 'hata': f'{pb} kuru tanımlı değil',
                        'kur': None, 'tarih': None}), 200
    return jsonify({
        'ok': True,
        'kur': float(kr['MerkezKur']),
        'tarih': kr['Tarih'],
        'kaynak': kr.get('Kaynak') or 'MANUEL',
    }), 200


# ============== AUDIT LOG ==============
@yonetim_bp.route('/log')
@admin_gerekli
def log_liste():
    f = {
        'modul':     request.args.get('modul') or None,
        'alt_modul': request.args.get('alt_modul') or None,
        'kullanici': request.args.get('kullanici') or None,
        'islem':     request.args.get('islem') or None,
        'bas':       request.args.get('bas') or None,
        'bit':       request.args.get('bit') or None,
    }
    return render_template('yonetim/log_liste.html',
                           loglar=audit.son_loglar(limit=500, **f),
                           f=f,
                           kullanicilar=qr.kullanici_liste())


# ============== BELGE ==============
@yonetim_bp.route('/belge/<int:belge_id>')
def belge_indir(belge_id):
    if not session.get('kullanici'):
        return redirect(url_for('auth.login', next=request.path))
    b = belge_srv.belge_tek(belge_id)
    if not b:
        abort(404)
    kod = f"{b['Modul']}.{b['AltModul']}.goruntule" if b['AltModul'] else f"{b['Modul']}.goruntule"
    if not _admin_mi() and not yetki_var(kod):
        abort(403)
    yol = belge_srv.belge_tam_yol(b)
    if not os.path.exists(yol):
        abort(404)
    return send_file(yol, download_name=b['OrijinalAd'], as_attachment=False)


@yonetim_bp.route('/belge/<int:belge_id>/sil', methods=['POST'])
@admin_gerekli
def belge_sil_route(belge_id):
    belge_srv.belge_sil(belge_id, kullanici=_u())
    flash('Belge silindi.', 'ok')
    return redirect(request.form.get('ref') or url_for('yonetim.panel'))
