# -*- coding: utf-8 -*-
"""CPS DEV - Auth modülü"""
from flask import Blueprint, request, redirect, url_for, session, render_template, g, flash, abort
from functools import wraps
from db import qone, q, qexec
from modules import audit

auth_bp = Blueprint('auth', __name__)


def login_kullanici(kadi, sifre):
    return qone("""
        SELECT * FROM sistem_kullanici
        WHERE KullaniciAdi = ? AND Sifre = ? AND Aktif = 1
    """, (kadi, sifre))


def mevcut_kullanici():
    return session.get('kullanici')


def kullanici_adi():
    k = session.get('kullanici')
    return k['KullaniciAdi'] if k else 'sistem'


def kullanici_yetkileri(user_dict):
    """Set olarak tüm yetki kodları: {'finans.anlasma.goruntule', ...}"""
    if not user_dict:
        return set()
    if user_dict.get('RolAd') == 'Yönetim' or user_dict.get('KullaniciAdi') == 'admin':
        return {'*'}
    rol_id = user_dict.get('RolId')
    if not rol_id:
        return set()
    yetkiler = set()
    rows = q("""
        SELECT y.Kod, ry.Gorebilir, ry.Duzenleyebilir
        FROM sistem_rol_yetki ry
        JOIN sistem_yetki y ON y.Id = ry.YetkiId
        WHERE ry.RolId = ?
    """, (rol_id,))
    for r in rows:
        if r['Gorebilir']:
            yetkiler.add(r['Kod'] + '.goruntule')
        if r['Duzenleyebilir']:
            yetkiler.add(r['Kod'] + '.duzenle')
    return yetkiler


def yetki_var(kod):
    u = session.get('kullanici')
    if not u:
        return False
    yk = g.get('yetkiler')
    if yk is None:
        yk = kullanici_yetkileri(u)
        g.yetkiler = yk
    return '*' in yk or kod in yk


def yetki_gerekli(kod):
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get('kullanici'):
                return redirect(url_for('auth.login', next=request.path))
            if not yetki_var(kod):
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return deco


def login_gerekli(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('kullanici'):
            return redirect(url_for('auth.login', next=request.path))
        return f(*args, **kwargs)
    return wrapper


# ============== ROUTES ==============
@auth_bp.route('/giris', methods=['GET', 'POST'])
def login():
    hata = None
    if request.method == 'POST':
        kadi = request.form.get('kullanici', '').strip().lower()
        sifre = request.form.get('sifre', '').strip()
        u = login_kullanici(kadi, sifre)
        if u:
            if u.get('RolId'):
                rol = qone("SELECT Ad FROM sistem_rol WHERE Id = ?", (u['RolId'],))
                u['RolAd'] = rol['Ad'] if rol else None
            else:
                u['RolAd'] = None

            session['kullanici'] = dict(u)
            session.permanent = True

            audit.log(kadi, 'LOGIN', 'sistem_kullanici', u['Id'],
                      aciklama='Giriş yapıldı',
                      modul='yonetim', alt_modul='kullanici')

            if u.get('ZorunluSifreDegistir'):
                return redirect(url_for('auth.sifre_degistir'))

            nxt = request.args.get('next') or request.form.get('next') or '/'
            return redirect(nxt)
        hata = 'Kullanıcı adı veya şifre hatalı.'
    return render_template('giris.html', hata=hata)


@auth_bp.route('/cikis')
def logout():
    u = session.get('kullanici')
    if u:
        audit.log(u['KullaniciAdi'], 'LOGOUT', 'sistem_kullanici', u['Id'],
                  aciklama='Çıkış yapıldı',
                  modul='yonetim', alt_modul='kullanici')
    session.pop('kullanici', None)
    return redirect(url_for('auth.login'))


@auth_bp.route('/sifre-degistir', methods=['GET', 'POST'])
def sifre_degistir():
    if not session.get('kullanici'):
        return redirect(url_for('auth.login'))
    u = session['kullanici']
    hata = None
    basarili = False
    if request.method == 'POST':
        mevcut = request.form.get('mevcut', '').strip()
        yeni = request.form.get('yeni', '').strip()
        tekrar = request.form.get('tekrar', '').strip()
        if not mevcut or not yeni or not tekrar:
            hata = 'Tüm alanlar zorunludur.'
        elif len(yeni) < 4:
            hata = 'Şifre en az 4 karakter olmalı.'
        elif yeni != tekrar:
            hata = 'Yeni şifreler eşleşmiyor.'
        else:
            kontrol = qone("SELECT Id FROM sistem_kullanici WHERE Id=? AND Sifre=?",
                           (u['Id'], mevcut))
            if not kontrol:
                hata = 'Mevcut şifre hatalı.'
            else:
                qexec("""UPDATE sistem_kullanici
                         SET Sifre = ?, ZorunluSifreDegistir = 0
                         WHERE Id = ?""", (yeni, u['Id']))
                audit.log(u['KullaniciAdi'], 'SIFRE_DEGISTIR', 'sistem_kullanici',
                          u['Id'], aciklama='Şifre değiştirildi',
                          modul='yonetim', alt_modul='kullanici')
                session['kullanici']['Sifre'] = yeni
                session['kullanici']['ZorunluSifreDegistir'] = 0
                basarili = True
    return render_template('sifre_degistir.html',
                           hata=hata, basarili=basarili,
                           zorunlu=bool(u.get('ZorunluSifreDegistir')))


@auth_bp.before_app_request
def attach_user():
    g.user = session.get('kullanici')
    if g.user:
        g.yetkiler = kullanici_yetkileri(g.user)
    else:
        g.yetkiler = set()
