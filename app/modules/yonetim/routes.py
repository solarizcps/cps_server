# -*- coding: utf-8 -*-
"""CPS DEV - Yönetim Routes"""
from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, abort, send_file, flash, jsonify)
from functools import wraps
import os

from modules.yonetim import queries as qr
from db import q as _q, qscalar as _qscalar, get_conn as _get_conn
from modules import audit, belge as belge_srv
from modules.auth import yetki_var, is_superadmin, yetki_gerekli
from config import Config

yonetim_bp = Blueprint('yonetim', __name__, url_prefix='/yonetim')


def _u():
    k = session.get('kullanici')
    return k['KullaniciAdi'] if k else 'sistem'






# ============== PANEL ==============
@yonetim_bp.route('/')
@yetki_gerekli('yonetim', 'can_view')
def panel():
    return render_template('yonetim/panel.html',
                           kpi=qr.yonetim_kpi(),
                           son_loglar=audit.son_loglar(limit=20))


# ============== KULLANICI ==============
@yonetim_bp.route('/kullanici')
@yetki_gerekli('yonetim.kullanici', 'can_view')
def kullanici_liste():
    return render_template('yonetim/kullanici_liste.html',
                           kullanicilar=qr.kullanici_liste(),
                           roller=qr.yetki_secimlik_liste())


@yonetim_bp.route('/kullanici/yeni', methods=['POST'])
@yetki_gerekli('yonetim.kullanici', 'can_create')
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
@yetki_gerekli('yonetim.kullanici', 'can_update')
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
@yetki_gerekli('yonetim.kullanici', 'can_update')
def kullanici_sifre_sifirla(kullanici_id):
    yeni = request.form.get('yeni_sifre', '').strip() or '1234'
    qr.kullanici_sifre_sifirla(kullanici_id, yeni, kullanici=_u())
    flash(f'Şifre sıfırlandı. Yeni: {yeni}', 'ok')
    return redirect(url_for('yonetim.kullanici_liste'))


@yonetim_bp.route('/kullanici/<int:kullanici_id>/pasif', methods=['POST'])
@yetki_gerekli('yonetim.kullanici', 'can_update')
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
@yetki_gerekli('yonetim.rol', 'can_view')
def rol_liste():
    return render_template('yonetim/rol_liste.html', roller=qr.rol_liste())


@yonetim_bp.route('/rol/yeni', methods=['POST'])
@yetki_gerekli('yonetim.rol', 'can_create')
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
@yetki_gerekli('yonetim.rol', 'can_view')
def rol_detay(rol_id):
    rol = qr.rol_tek(rol_id)
    if not rol:
        abort(404)
    tum = qr.yetki_liste()
    mevcut = qr.rol_yetkileri(rol_id)
    metrik = qr.rol_metrik(rol_id)
    gruplar = {}
    for y in tum:
        k = f"{y['Modul']}/{y['AltModul'] or '-'}"
        gruplar.setdefault(k, {'modul': y['Modul'], 'alt_modul': y['AltModul'] or '',
                               'yetkiler': []})['yetkiler'].append(y)
    return render_template('yonetim/rol_detay.html',
                           rol=rol, gruplar=gruplar, mevcut=mevcut,
                           metrik=metrik)


@yonetim_bp.route('/rol/<int:rol_id>/kaydet', methods=['POST'])
@yetki_gerekli('yonetim.rol', 'can_update')
def rol_kaydet(rol_id):
    ad = request.form.get('Ad', '').strip()
    ac = request.form.get('Aciklama', '').strip() or None
    if ad:
        qr.rol_guncelle(rol_id, ad, ac, kullanici=_u())
    yetki_map = {}
    V2_ACTIONS = ('can_view', 'can_create', 'can_update', 'can_delete',
                  'can_approve', 'can_report', 'can_manage')
    for y in qr.yetki_liste():
        yid = y['Id']
        v2 = {}
        for action in V2_ACTIONS:
            v2[action] = 1 if request.form.get(f'v2_{action}_{yid}') == '1' else 0
        # Eski kolon mapping (geriye uyum)
        g = 1 if v2['can_view'] else 0
        d = 1 if (v2['can_create'] or v2['can_update']) else 0
        v2['gor'] = g
        v2['duz'] = d
        yetki_map[yid] = v2
    qr.rol_yetki_kaydet(rol_id, yetki_map, kullanici=_u())
    flash('Rol ve yetkiler kaydedildi.', 'ok')
    return redirect(url_for('yonetim.rol_detay', rol_id=rol_id))


@yonetim_bp.route('/rol/<int:rol_id>/sil', methods=['POST'])
@yetki_gerekli('yonetim.rol', 'can_delete')
def rol_sil(rol_id):
    try:
        qr.rol_sil(rol_id, kullanici=_u())
        flash('Rol silindi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('yonetim.rol_liste'))


# ============== KUR ==============
@yonetim_bp.route('/kur')
@yetki_gerekli('yonetim.kur', 'can_view')
def kur_liste():
    from datetime import date
    return render_template('yonetim/kur_liste.html',
                           kurlar=qr.kur_liste(limit=120),
                           usd=qr.kur_guncel('USD'),
                           eur=qr.kur_guncel('EUR'),
                           cny=qr.kur_guncel('CNY'),
                           bugun=date.today().strftime('%Y-%m-%d'))


@yonetim_bp.route('/kur/yeni', methods=['POST'])
@yetki_gerekli('yonetim.kur', 'can_create')
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
@yetki_gerekli('yonetim.kur', 'can_delete')
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
@yetki_gerekli('yonetim.log', 'can_view')
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
    """
    F2.8-A (21.05.2026): goruntule suffix kaldirildi.
    Belge sahip modulunun can_view yetkisi yeterli.
    CORE is_superadmin + yetki_var(kod, can_view) kullaniliyor.
    """
    u = session.get('kullanici')
    if not u:
        return redirect(url_for('auth.login', next=request.path))
    b = belge_srv.belge_tek(belge_id)
    if not b:
        abort(404)
    kod = f"{b['Modul']}.{b['AltModul']}" if b['AltModul'] else b['Modul']
    if not is_superadmin(u) and not yetki_var(kod, 'can_view'):
        abort(403)
    yol = belge_srv.belge_tam_yol(b)
    if not os.path.exists(yol):
        abort(404)
    return send_file(yol, download_name=b['OrijinalAd'], as_attachment=False)


@yonetim_bp.route('/belge/<int:belge_id>/sil', methods=['POST'])
@yetki_gerekli('yonetim.belge', 'can_delete')
def belge_sil_route(belge_id):
    belge_srv.belge_sil(belge_id, kullanici=_u())
    flash('Belge silindi.', 'ok')
    return redirect(request.form.get('ref') or url_for('yonetim.panel'))

# ================================================================
# FAZ 7 - STANDART SURE ENDPOINT'LERI
# ================================================================
import sqlite3 as _faz7_sqlite3
from flask import session as _faz7_session, request as _faz7_request, jsonify as _faz7_jsonify

_FAZ7_DB_PATH = r"C:\cps_dev\mock_data.db"


def _faz7_admin_kontrol():
    """Sprint 1.3c: auth.is_superadmin standardina baglanildi."""
    from modules.auth import is_superadmin as _isa
    u = _faz7_session.get('kullanici')
    return _isa(u)


def _faz7_db_baglan():
    """proses_kategori icin DB baglanti."""
    conn = _faz7_sqlite3.connect(_FAZ7_DB_PATH)
    conn.row_factory = _faz7_sqlite3.Row
    return conn


@yonetim_bp.route('/proses-kategori/liste', methods=['GET'])
def faz7_proses_kategori_liste():
    """Tum proses_kategori kayitlarini standart_saniye dahil dondur."""
    if not _faz7_admin_kontrol():
        return _faz7_jsonify({'ok': False, 'mesaj': 'Yetkisiz erisim'}), 403
    
    try:
        conn = _faz7_db_baglan()
        cur = conn.cursor()
        cur.execute("""
            SELECT proses_kod, proses_adi, kategori, sira, standart_saniye
              FROM proses_kategori
             ORDER BY kategori, sira
        """)
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            rows.append({
                'proses_kod': d.get('proses_kod') or '',
                'proses_adi': d.get('proses_adi') or '',
                'kategori': d.get('kategori') or '',
                'sira': int(d.get('sira') or 0),
                'standart_saniye': float(d['standart_saniye']) if d.get('standart_saniye') is not None else None
            })
        conn.close()
        return _faz7_jsonify({
            'ok': True,
            'success': True,
            'kayit_sayisi': len(rows),
            'kayitlar': rows
        })
    except Exception as e:
        return _faz7_jsonify({
            'ok': False,
            'success': False,
            'mesaj': f'{type(e).__name__}: {str(e)[:200]}'
        }), 500


@yonetim_bp.route('/proses-kategori/<proses_kod>/sure', methods=['PUT'])
def faz7_proses_kategori_sure_guncelle(proses_kod):
    """Bir prosesin standart_saniye degerini guncelle."""
    if not _faz7_admin_kontrol():
        return _faz7_jsonify({'ok': False, 'mesaj': 'Yetkisiz erisim'}), 403
    
    try:
        data = _faz7_request.get_json(silent=True) or {}
        sure_raw = data.get('standart_saniye')
        
        # NULL silme: standart_saniye = None gonderilirse temizle
        if sure_raw is None or sure_raw == '' or sure_raw == 'null':
            yeni_sure = None
        else:
            try:
                yeni_sure = float(sure_raw)
                if yeni_sure < 0 or yeni_sure > 7200:  # 0-7200 sn (2 saat max)
                    return _faz7_jsonify({
                        'ok': False,
                        'mesaj': 'Sure 0-7200 saniye arasi olmali'
                    }), 400
            except (TypeError, ValueError):
                return _faz7_jsonify({
                    'ok': False,
                    'mesaj': 'Gecersiz sayi formati'
                }), 400
        
        # proses_kod sanitize
        if not proses_kod or len(proses_kod) > 20:
            return _faz7_jsonify({
                'ok': False,
                'mesaj': 'Gecersiz proses_kod'
            }), 400
        
        conn = _faz7_db_baglan()
        cur = conn.cursor()
        
        # Once var mi kontrol
        cur.execute("SELECT proses_kod, proses_adi FROM proses_kategori WHERE proses_kod = ?", (proses_kod,))
        kayit = cur.fetchone()
        if not kayit:
            conn.close()
            return _faz7_jsonify({
                'ok': False,
                'mesaj': f'proses_kod={proses_kod} bulunamadi'
            }), 404
        
        # Guncelle
        cur.execute("UPDATE proses_kategori SET standart_saniye = ? WHERE proses_kod = ?",
                    (yeni_sure, proses_kod))
        conn.commit()
        affected = cur.rowcount
        conn.close()
        
        return _faz7_jsonify({
            'ok': True,
            'success': True,
            'mesaj': f'{kayit["proses_adi"]} guncellendi',
            'proses_kod': proses_kod,
            'standart_saniye': yeni_sure,
            'affected': affected
        })
    except Exception as e:
        return _faz7_jsonify({
            'ok': False,
            'success': False,
            'mesaj': f'{type(e).__name__}: {str(e)[:200]}'
        }), 500


@yonetim_bp.route('/proses-kategori/yeni', methods=['POST'])
def faz7_proses_kategori_yeni():
    """Yeni proses ekle (Capak, Rivet, Tampon vb)."""
    if not _faz7_admin_kontrol():
        return _faz7_jsonify({'ok': False, 'mesaj': 'Yetkisiz erisim'}), 403
    
    try:
        data = _faz7_request.get_json(silent=True) or {}
        
        proses_kod = (data.get('proses_kod') or '').strip()
        proses_adi = (data.get('proses_adi') or '').strip()
        kategori = (data.get('kategori') or '').strip().upper()
        sira = data.get('sira', 0)
        standart_saniye = data.get('standart_saniye')
        
        # Validasyon
        if not proses_kod or len(proses_kod) > 20:
            return _faz7_jsonify({'ok': False, 'mesaj': 'proses_kod gerekli (1-20 karakter)'}), 400
        if not proses_adi or len(proses_adi) > 100:
            return _faz7_jsonify({'ok': False, 'mesaj': 'proses_adi gerekli (1-100 karakter)'}), 400
        if not kategori or kategori not in ['ATKI', 'GOVDE', 'MAMUL']:
            return _faz7_jsonify({'ok': False, 'mesaj': 'kategori ATKI/GOVDE/MAMUL olmali'}), 400
        try:
            sira = int(sira)
            if sira < 0 or sira > 999:
                return _faz7_jsonify({'ok': False, 'mesaj': 'sira 0-999 arasi olmali'}), 400
        except (TypeError, ValueError):
            return _faz7_jsonify({'ok': False, 'mesaj': 'sira sayi olmali'}), 400
        
        if standart_saniye is not None and standart_saniye != '':
            try:
                standart_saniye = float(standart_saniye)
                if standart_saniye < 0 or standart_saniye > 7200:
                    return _faz7_jsonify({'ok': False, 'mesaj': 'standart_saniye 0-7200 olmali'}), 400
            except (TypeError, ValueError):
                return _faz7_jsonify({'ok': False, 'mesaj': 'standart_saniye sayi olmali'}), 400
        else:
            standart_saniye = None
        
        conn = _faz7_db_baglan()
        cur = conn.cursor()
        
        # Duplicate check
        cur.execute("SELECT proses_kod FROM proses_kategori WHERE proses_kod = ?", (proses_kod,))
        if cur.fetchone():
            conn.close()
            return _faz7_jsonify({
                'ok': False,
                'mesaj': f'proses_kod={proses_kod} zaten var'
            }), 409
        
        # INSERT
        cur.execute("""
            INSERT INTO proses_kategori (proses_kod, proses_adi, kategori, sira, standart_saniye)
            VALUES (?, ?, ?, ?, ?)
        """, (proses_kod, proses_adi, kategori, sira, standart_saniye))
        conn.commit()
        conn.close()
        
        return _faz7_jsonify({
            'ok': True,
            'success': True,
            'mesaj': f'{proses_adi} eklendi',
            'proses_kod': proses_kod,
            'proses_adi': proses_adi,
            'kategori': kategori,
            'sira': sira,
            'standart_saniye': standart_saniye
        })
    except Exception as e:
        return _faz7_jsonify({
            'ok': False,
            'success': False,
            'mesaj': f'{type(e).__name__}: {str(e)[:200]}'
        }), 500
# === FAZ 7 ADIM 2 SONU ===

# === FAZ 7 - HTML render endpoint ===
@yonetim_bp.route('/proses-kategori', methods=['GET'])
def faz7_proses_kategori_sayfa():
    """Proses kategori yonetim sayfasi (HTML)."""
    if not _faz7_admin_kontrol():
        try:
            from flask import redirect, url_for
            return redirect(url_for('auth.giris'))
        except Exception:
            from flask import redirect
            return redirect('/giris')
    try:
        from flask import render_template
        return render_template('yonetim/proses_kategori.html')
    except Exception as e:
        from flask import jsonify as _jsonify
        return _jsonify({'ok': False, 'mesaj': f'{type(e).__name__}: {str(e)[:200]}'}), 500
# === FAZ 7 ROUTE SONU ===

# === D6.0.1 PROSES ALIAS ROUTES BASLANGIC ===
# D6.0.1 sprint - SADECE gorunurluk. UPDATE/INSERT/DELETE yok.

@yonetim_bp.route('/proses-alias/liste', methods=['GET'])
def proses_alias_liste():
    """proses_alias kayitlarini listele - read-only JSON.

    Response: { ok, toplam, onayli, bekleyen, aliaslar:[] }
    """
    if not _faz7_admin_kontrol():
        return _faz7_jsonify({'ok': False, 'mesaj': 'Yetkisiz erisim'}), 403
    try:
        import sqlite3 as _pa_sqlite3, os as _pa_os
        # Canli DB - faz7 helper hardcoded eski yol kullanmiyor
        _pa_db_path = _pa_os.path.join(
            _pa_os.path.dirname(_pa_os.path.dirname(_pa_os.path.dirname(_pa_os.path.abspath(__file__)))),
            'mock_data.db'
        )
        _pa_conn = _pa_sqlite3.connect(_pa_db_path)
        _pa_conn.row_factory = _pa_sqlite3.Row
        cur = _pa_conn.cursor()
        cur.execute("""
            SELECT id, saha_adi, standart_kod, standart_adi, kategori,
                   guven_skoru, karar_kaynak, onayli_mi, olusturma
              FROM proses_alias
             ORDER BY standart_kod, saha_adi
        """)
        aliaslar = []
        toplam = 0
        onayli = 0
        bekleyen = 0
        for r in cur.fetchall():
            d = dict(r)
            aliaslar.append({
                'id': d['id'],
                'saha_adi': d['saha_adi'],
                'standart_kod': d['standart_kod'],
                'standart_adi': d['standart_adi'],
                'kategori': d.get('kategori') or '',
                'guven_skoru': int(d.get('guven_skoru') or 0),
                'karar_kaynak': d.get('karar_kaynak') or '',
                'onayli_mi': int(d.get('onayli_mi') or 0),
                'olusturma': d.get('olusturma') or ''
            })
            toplam += 1
            if d.get('onayli_mi'):
                onayli += 1
            else:
                bekleyen += 1
        _pa_conn.close()
        return _faz7_jsonify({
            'ok': True,
            'success': True,
            'toplam': toplam,
            'onayli': onayli,
            'bekleyen': bekleyen,
            'aliaslar': aliaslar
        })
    except Exception as e:
        return _faz7_jsonify({
            'ok': False,
            'success': False,
            'mesaj': f'{type(e).__name__}: {str(e)[:200]}'
        }), 500


@yonetim_bp.route('/proses-alias', methods=['GET'])
def proses_alias_sayfa():
    """proses_alias yonetim sayfasi - read-only gorunurluk."""
    if not _faz7_admin_kontrol():
        return _faz7_jsonify({'ok': False, 'mesaj': 'Yetkisiz erisim'}), 403
    try:
        return render_template('yonetim/proses_alias.html')
    except Exception as e:
        from flask import jsonify as _pa_jsonify
        return _pa_jsonify({
            'ok': False,
            'mesaj': f'{type(e).__name__}: {str(e)[:200]}'
        }), 500

# === D6.0.1 PROSES ALIAS ROUTES SONU ===


# === D6.1-B SINYAL ENGINE ENDPOINT BASLANGIC ===

@yonetim_bp.route('/sinyal-engine/test', methods=['POST'])
def sinyal_engine_test():
    """D6.1-B manuel sinyal motoru test endpoint.

    Body (JSON):
      - dry_run: true (default) - INSERT/UPDATE yapma
      - rule_id: opsiyonel, sadece tek kural calistir
    """
    if not _faz7_admin_kontrol():
        return _faz7_jsonify({'ok': False, 'mesaj': 'Yetkisiz erisim'}), 403

    try:
        from flask import request as _se_request
        import sys as _se_sys, os as _se_os
        import sqlite3 as _se_sqlite3
        import traceback as _se_traceback

        body = _se_request.get_json(silent=True) or {}
        dry_run = bool(body.get('dry_run', True))
        rule_filter = body.get('rule_id')

        # Project root path
        _se_root = _se_os.path.dirname(_se_os.path.dirname(_se_os.path.dirname(_se_os.path.abspath(__file__))))
        if _se_root not in _se_sys.path:
            _se_sys.path.insert(0, _se_root)

        from services import sinyal_engine

        _se_db = _se_os.path.join(_se_root, 'mock_data.db')
        _se_conn = _se_sqlite3.connect(_se_db)
        _se_conn.row_factory = _se_sqlite3.Row

        sonuc = sinyal_engine.run_all_rules(_se_conn, dry_run=dry_run, rule_filter=rule_filter)

        if not dry_run:
            _se_conn.commit()
        _se_conn.close()

        return _faz7_jsonify({'ok': True, 'sonuc': sonuc})

    except Exception as _e:
        import traceback as _t
        return _faz7_jsonify({
            'ok': False,
            'mesaj': f'{type(_e).__name__}: {str(_e)[:200]}',
            'traceback': _t.format_exc()[:500]
        }), 500

# === D6.1-B SINYAL ENGINE ENDPOINT SONU ===


# === D6.1-C SINYAL CRUD ENDPOINTS BASLANGIC ===


def _sc_get_db_path():
    """Sinyal CRUD endpoint'ler icin DB path - D6.1-B fix mantigi."""
    import os as _o
    _root = _o.path.dirname(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
    return _o.path.join(_root, 'mock_data.db')


def _sc_conn():
    """Sinyal CRUD endpoint baglanti."""
    import sqlite3 as _s
    c = _s.connect(_sc_get_db_path())
    c.row_factory = _s.Row
    return c


def _sc_kullanici():
    """Session'dan kullanici (Id, KullaniciAdi)."""
    from flask import session as _ses
    u = _ses.get('kullanici') or {}
    return (u.get('Id'), u.get('KullaniciAdi') or 'bilinmiyor')


@yonetim_bp.route('/sinyaller', methods=['GET'])
def sinyaller_liste():
    """D6.1-C: Sinyal listesi (filtreli)."""
    if not _faz7_admin_kontrol():
        return _faz7_jsonify({'ok': False, 'mesaj': 'Yetkisiz'}), 403
    try:
        from flask import request as _rq
        from services import sinyal_engine as _se

        durum = _rq.args.get('durum', 'AKTIF')
        if durum not in ('AKTIF', 'GORULDU', 'DISMISS', 'RESOLVED', 'TUM'):
            return _faz7_jsonify({'ok': False, 'mesaj': 'Gecersiz durum'}), 400

        seviye = _rq.args.get('seviye') or None
        if seviye and seviye not in ('INFO', 'WARN', 'CRITIC'):
            return _faz7_jsonify({'ok': False, 'mesaj': 'Gecersiz seviye'}), 400

        rule_id = _rq.args.get('rule_id') or None
        try:
            limit = min(int(_rq.args.get('limit', 100)), 500)
        except (ValueError, TypeError):
            limit = 100
        try:
            offset = max(int(_rq.args.get('offset', 0)), 0)
        except (ValueError, TypeError):
            offset = 0

        c = _sc_conn()
        sonuc = _se.list_signals(c, durum=durum, seviye=seviye, rule_id=rule_id,
                                   limit=limit, offset=offset)
        c.close()
        return _faz7_jsonify(sonuc)
    except Exception as _e:
        import traceback as _t
        return _faz7_jsonify({
            'ok': False,
            'mesaj': f'{type(_e).__name__}: {str(_e)[:200]}',
            'traceback': _t.format_exc()[:500]
        }), 500


@yonetim_bp.route('/sinyaller/<int:signal_id>', methods=['GET'])
def sinyaller_detay(signal_id):
    """D6.1-C: Sinyal detay."""
    if not _faz7_admin_kontrol():
        return _faz7_jsonify({'ok': False, 'mesaj': 'Yetkisiz'}), 403
    try:
        from services import sinyal_engine as _se
        c = _sc_conn()
        sig = _se.get_signal(c, signal_id)
        c.close()
        if not sig:
            return _faz7_jsonify({'ok': False, 'mesaj': 'Sinyal yok'}), 404
        return _faz7_jsonify({'ok': True, 'sinyal': sig})
    except Exception as _e:
        return _faz7_jsonify({
            'ok': False,
            'mesaj': f'{type(_e).__name__}: {str(_e)[:200]}'
        }), 500


@yonetim_bp.route('/sinyaller/<int:signal_id>/dismiss', methods=['POST'])
def sinyaller_dismiss(signal_id):
    """D6.1-C: Sinyal dismiss (yanlis alarm)."""
    if not _faz7_admin_kontrol():
        return _faz7_jsonify({'ok': False, 'mesaj': 'Yetkisiz'}), 403
    try:
        from flask import request as _rq
        from services import sinyal_engine as _se

        body = _rq.get_json(silent=True) or {}
        aciklama = (body.get('aciklama') or '').strip()
        if len(aciklama) < 3:
            return _faz7_jsonify({
                'ok': False, 'mesaj': 'aciklama >=3 char zorunlu'
            }), 400

        kid, kadi = _sc_kullanici()
        c = _sc_conn()
        sonuc = _se.dismiss_signal(c, signal_id, kid, kadi, aciklama)
        c.commit()
        c.close()

        if not sonuc.get('ok'):
            return _faz7_jsonify(sonuc), sonuc.get('kod', 500)
        return _faz7_jsonify(sonuc)
    except Exception as _e:
        return _faz7_jsonify({
            'ok': False,
            'mesaj': f'{type(_e).__name__}: {str(_e)[:200]}'
        }), 500


@yonetim_bp.route('/sinyaller/<int:signal_id>/resolved', methods=['POST'])
def sinyaller_resolved(signal_id):
    """D6.1-C: Sinyal resolved (cozuldu)."""
    if not _faz7_admin_kontrol():
        return _faz7_jsonify({'ok': False, 'mesaj': 'Yetkisiz'}), 403
    try:
        from flask import request as _rq
        from services import sinyal_engine as _se

        body = _rq.get_json(silent=True) or {}
        aciklama = (body.get('aciklama') or '').strip()
        if len(aciklama) < 3:
            return _faz7_jsonify({
                'ok': False, 'mesaj': 'aciklama >=3 char zorunlu'
            }), 400

        kid, kadi = _sc_kullanici()
        c = _sc_conn()
        sonuc = _se.resolve_signal(c, signal_id, kid, kadi, aciklama)
        c.commit()
        c.close()

        if not sonuc.get('ok'):
            return _faz7_jsonify(sonuc), sonuc.get('kod', 500)
        return _faz7_jsonify(sonuc)
    except Exception as _e:
        return _faz7_jsonify({
            'ok': False,
            'mesaj': f'{type(_e).__name__}: {str(_e)[:200]}'
        }), 500


@yonetim_bp.route('/sinyaller/ozet', methods=['GET'])
def sinyaller_ozet():
    """D6.1-C: KPI ozet (dashboard badge icin)."""
    if not _faz7_admin_kontrol():
        return _faz7_jsonify({'ok': False, 'mesaj': 'Yetkisiz'}), 403
    try:
        from services import sinyal_engine as _se
        c = _sc_conn()
        sonuc = _se.get_ozet(c)
        c.close()
        return _faz7_jsonify(sonuc)
    except Exception as _e:
        return _faz7_jsonify({
            'ok': False,
            'mesaj': f'{type(_e).__name__}: {str(_e)[:200]}'
        }), 500


# === D6.1-C SINYAL CRUD ENDPOINTS SONU ===


# === D6.1-D SINYAL UI ROUTE BASLANGIC ===


@yonetim_bp.route('/sinyaller-ui', methods=['GET'])
def sinyaller_ui():
    """D6.1-D: Operasyon Sinyalleri UI ekrani (template render)."""
    if not _faz7_admin_kontrol():
        from flask import abort as _abort
        return _abort(403)
    try:
        from flask import render_template as _rt
        return _rt('yonetim/sinyaller.html')
    except Exception as _e:
        from flask import jsonify as _j
        return _j({
            'ok': False,
            'mesaj': f'{type(_e).__name__}: {str(_e)[:200]}'
        }), 500


# === D6.1-D SINYAL UI ROUTE SONU ===



# F_KY_YETKI_GENISLET - Esnek yetki kontrolu
_KY_YETKILI_ROLLER = {"Yonetim", "Yönetim", "Planlama", "Enjeksiyon", "Kalite", "Uretim", "İdari İşler"}

def ky_kalip_yetki(f):
    """Sprint 1.5: is_superadmin standardina baglanildi.
    F_KY_YETKI_GENISLET: yonetim.kalip DB kodu eklenince @yetki_gerekli ile tam replace.
    """
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("kullanici"):
            return redirect(url_for("auth.login"))
        if not is_superadmin(session.get("kullanici")):
            abort(403)
        return f(*args, **kwargs)
    return wrapper

# === BEGIN: F_KALIP_YONETIM_ENDPOINT ===
# F_KALIP_YONETIM_ENDPOINT - Master Data sayfasi icin endpoint'ler
# Tarih: 20260522
import sqlite3 as _sqlite3_ky
from flask import jsonify as _jsonify_ky
import os as _os_ky


def _ky_db_path():
    """CPS standart DB yolu - app/mock_data.db"""
    base = _os_ky.path.dirname(_os_ky.path.dirname(_os_ky.path.dirname(_os_ky.path.abspath(__file__))))
    return _os_ky.path.join(base, 'mock_data.db')


@yonetim_bp.route('/kalip-yonetimi', methods=['GET'])
@yetki_gerekli('planlama.enjeksiyon.kalip', 'can_view')  # KALIP_FAZ_A: merkezi yetki sistemine alindi
def ky_kalip_yonetimi_sayfa():
    """Kalip Yonetimi sayfasi (Master Data)."""
    return render_template('yonetim/kalip_yonetimi.html')


@yonetim_bp.route('/api/kaliplar', methods=['GET'])
@yetki_gerekli('planlama.enjeksiyon.kalip', 'can_view')  # KALIP_FAZ_A: merkezi yetki sistemine alindi
def ky_api_kaliplar():
    """Tum kaliplar listesi (master data)."""
    try:
        con = _sqlite3_ky.connect(_ky_db_path())
        cur = con.cursor()
        cur.execute("""
            SELECT id, kalip_kod, kalip_tipi, model_kod, model_ad, asorti,
                   kalip_basi_cift, varsayilan_bagli_kalip, renk, gorsel_dosya, aktif,
                   kapasite_cift
            FROM enj_kalip
            ORDER BY aktif DESC, kalip_kod, model_kod, asorti
        """)
        rows = cur.fetchall()
        con.close()
        
        kayitlar = []
        for r in rows:
            kayitlar.append({
                'id': r[0],
                'kalip_kod': r[1],
                'kalip_tipi': r[2],
                'model_kod': r[3],
                'model_ad': r[4],
                'asorti': r[5],
                'kalip_basi_cift': r[6],
                'varsayilan_bagli_kalip': r[7],
                'renk': r[8],
                'gorsel_dosya': r[9],
                'aktif': r[10],
                'kapasite_cift': r[11],
            })
        return _jsonify_ky({'ok': True, 'sayi': len(kayitlar), 'kayitlar': kayitlar})
    except Exception as e:
        return _jsonify_ky({'ok': False, 'hata': str(e)}), 500


_KY_PATCH_WHITELIST = {
    'kalip_kod', 'kalip_tipi', 'model_kod', 'model_ad', 'asorti',
    'kalip_basi_cift', 'varsayilan_bagli_kalip', 'renk', 'gorsel_dosya', 'aktif',
    'kapasite_cift',
}


@yonetim_bp.route('/api/kalip/<int:kalip_id>', methods=['PATCH'])
@yetki_gerekli('planlama.enjeksiyon.kalip', 'can_update')  # KALIP_FAZ_A: merkezi yetki sistemine alindi
def ky_api_kalip_patch(kalip_id):
    """Kalip duzenleme - master data update."""
    try:
        body = request.get_json(silent=True) or {}
        guncel = {k: body[k] for k in _KY_PATCH_WHITELIST if k in body}
        if not guncel:
            return _jsonify_ky({'ok': False, 'hata': 'guncellenecek alan yok'}), 400
        
        # Validasyon
        if 'kalip_basi_cift' in guncel:
            try:
                v = int(guncel['kalip_basi_cift'])
                if v < 1 or v > 20:
                    return _jsonify_ky({'ok': False, 'hata': 'KBC 1-20 arasinda olmali'}), 400
                guncel['kalip_basi_cift'] = v
            except (ValueError, TypeError):
                return _jsonify_ky({'ok': False, 'hata': 'KBC sayisal olmali'}), 400
        
        if 'aktif' in guncel:
            guncel['aktif'] = 1 if guncel['aktif'] else 0
        
        if 'kalip_tipi' in guncel and guncel['kalip_tipi'] not in ('GOVDE', 'ATKI'):
            return _jsonify_ky({'ok': False, 'hata': 'kalip_tipi GOVDE veya ATKI olmali'}), 400
        
        con = _sqlite3_ky.connect(_ky_db_path())
        cur = con.cursor()
        cur.execute('SELECT id, kalip_kod FROM enj_kalip WHERE id = ?', (kalip_id,))
        eski = cur.fetchone()
        if not eski:
            con.close()
            return _jsonify_ky({'ok': False, 'hata': 'kalip bulunamadi'}), 404
        
        set_parts = [k + ' = ?' for k in guncel.keys()]
        params = list(guncel.values()) + [kalip_id]
        cur.execute(
            'UPDATE enj_kalip SET ' + ', '.join(set_parts) + ', guncelleme_tarihi = CURRENT_TIMESTAMP WHERE id = ?',
            params
        )
        affected = cur.rowcount
        con.commit()
        
        # Guncel kayit
        cur.execute("""
            SELECT id, kalip_kod, kalip_tipi, model_kod, model_ad, asorti,
                   kalip_basi_cift, varsayilan_bagli_kalip, renk, gorsel_dosya, aktif,
                   kapasite_cift
            FROM enj_kalip WHERE id = ?
        """, (kalip_id,))
        r = cur.fetchone()
        con.close()
        
        guncel_kayit = {
            'id': r[0], 'kalip_kod': r[1], 'kalip_tipi': r[2], 'model_kod': r[3],
            'model_ad': r[4], 'asorti': r[5], 'kalip_basi_cift': r[6],
            'varsayilan_bagli_kalip': r[7], 'renk': r[8], 'gorsel_dosya': r[9],
            'aktif': r[10], 'kapasite_cift': r[11],
        }
        
        # Audit log
        try:
            audit.log(_u(), 'kalip_guncelle', f'kalip_id={kalip_id} kod={eski[1]} alanlar={list(guncel.keys())}')
        except Exception:
            pass
        
        return _jsonify_ky({
            'ok': True,
            'guncellenen': affected,
            'kayit': guncel_kayit,
            'guncellenen_alanlar': list(guncel.keys())
        })
    except Exception as e:
        return _jsonify_ky({'ok': False, 'hata': str(e)}), 500

# === BEGIN: F_KALIP_EKLE ===
@yonetim_bp.route('/api/kalip/ekle', methods=['POST'])
@yetki_gerekli('planlama.enjeksiyon.kalip', 'can_create')
def ky_api_kalip_ekle():
    """Yeni kalip olustur. Zorunlu: kalip_kod, kalip_tipi, model_kod."""
    try:
        body = request.get_json(silent=True) or {}

        kalip_kod = (body.get('kalip_kod') or '').strip()
        kalip_tipi = (body.get('kalip_tipi') or 'GOVDE').strip().upper()
        model_kod = (body.get('model_kod') or '').strip()

        if not kalip_kod:
            return _jsonify_ky({'ok': False, 'hata': 'kalip_kod zorunlu'}), 400
        if not model_kod:
            return _jsonify_ky({'ok': False, 'hata': 'model_kod zorunlu'}), 400
        if kalip_tipi not in ('GOVDE', 'ATKI'):
            return _jsonify_ky({'ok': False, 'hata': 'kalip_tipi GOVDE veya ATKI olmali'}), 400

        model_ad = (body.get('model_ad') or '').strip() or None
        asorti = (body.get('asorti') or '').strip() or None
        renk = (body.get('renk') or '').strip() or None

        try:
            kalip_basi_cift = int(body.get('kalip_basi_cift') or 1)
            if kalip_basi_cift < 1:
                kalip_basi_cift = 1
        except (ValueError, TypeError):
            kalip_basi_cift = 1

        try:
            varsayilan_bagli_kalip = int(body.get('varsayilan_bagli_kalip') or 8)
        except (ValueError, TypeError):
            varsayilan_bagli_kalip = 8

        try:
            kapasite_cift = int(body.get('kapasite_cift') or 0) or None
        except (ValueError, TypeError):
            kapasite_cift = None

        aktif = 1 if body.get('aktif', 1) not in (0, '0', False) else 0

        con = _sqlite3_ky.connect(_ky_db_path())
        cur = con.cursor()

        existing = cur.execute(
            'SELECT id FROM enj_kalip WHERE kalip_kod = ?', (kalip_kod,)
        ).fetchone()
        if existing:
            con.close()
            return _jsonify_ky({
                'ok': False,
                'hata': f'Kalip kodu zaten mevcut: {kalip_kod}',
                'tip': 'DUPLICATE_KOD',
            }), 400

        cur.execute("""
            INSERT INTO enj_kalip
            (kalip_kod, kalip_tipi, model_kod, model_ad, asorti,
             kalip_basi_cift, varsayilan_bagli_kalip, renk, kapasite_cift, aktif,
             olusturma_tarihi, guncelleme_tarihi)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (kalip_kod, kalip_tipi, model_kod, model_ad, asorti,
              kalip_basi_cift, varsayilan_bagli_kalip, renk, kapasite_cift, aktif))
        con.commit()
        yeni_id = cur.lastrowid

        r = cur.execute("""
            SELECT id, kalip_kod, kalip_tipi, model_kod, model_ad, asorti,
                   kalip_basi_cift, varsayilan_bagli_kalip, renk, gorsel_dosya, aktif
            FROM enj_kalip WHERE id = ?
        """, (yeni_id,)).fetchone()
        con.close()

        kayit = {
            'id': r[0], 'kalip_kod': r[1], 'kalip_tipi': r[2], 'model_kod': r[3],
            'model_ad': r[4], 'asorti': r[5], 'kalip_basi_cift': r[6],
            'varsayilan_bagli_kalip': r[7], 'renk': r[8], 'gorsel_dosya': r[9],
            'aktif': r[10],
        }
        audit.log(_u(), 'kalip_ekle', 'enj_kalip', yeni_id,
                  aciklama=f'kod={kalip_kod} tip={kalip_tipi}')
        return _jsonify_ky({'ok': True, 'kalip': kayit, 'id': yeni_id}), 201

    except Exception as e:
        return _jsonify_ky({'ok': False, 'hata': str(e)}), 500
# === END: F_KALIP_EKLE ===


# === END: F_KALIP_YONETIM_ENDPOINT ===


# === BEGIN: F_KALIP_GORSEL_UPLOAD ===
# F_KALIP_GORSEL_UPLOAD - Kalip gorsel yukleme
# Tarih: 20260522
from werkzeug.utils import secure_filename as _ky_secure
import datetime as _ky_dt
import re as _ky_re


_KY_IMG_KLASOR = None

def _ky_img_klasor():
    global _KY_IMG_KLASOR
    if _KY_IMG_KLASOR is None:
        base = _os_ky.path.dirname(_os_ky.path.dirname(_os_ky.path.dirname(_os_ky.path.abspath(__file__))))
        _KY_IMG_KLASOR = _os_ky.path.join(base, 'static', 'img', 'kaliplar')
        _os_ky.makedirs(_KY_IMG_KLASOR, exist_ok=True)
    return _KY_IMG_KLASOR


def _ky_uzanti_ok(ad):
    return ad.lower().rsplit('.', 1)[-1] in ('jpg', 'jpeg', 'png', 'webp', 'gif')


@yonetim_bp.route('/api/kalip/<int:kalip_id>/gorsel', methods=['POST'])
@yetki_gerekli('planlama.enjeksiyon.kalip', 'can_create')  # KALIP_FAZ_A: merkezi yetki sistemine alindi
def ky_api_kalip_gorsel_upload(kalip_id):
    """Kalip gorsel yukle. Eski gorseli korur (asla silmez)."""
    try:
        if 'file' not in request.files:
            return _jsonify_ky({'ok': False, 'hata': 'dosya yok (file alani)'}), 400
        f = request.files['file']
        if not f or not f.filename:
            return _jsonify_ky({'ok': False, 'hata': 'dosya secilmedi'}), 400
        if not _ky_uzanti_ok(f.filename):
            return _jsonify_ky({'ok': False, 'hata': 'sadece jpg/jpeg/png/webp/gif'}), 400
        
        # Kalip bilgisi al
        con = _sqlite3_ky.connect(_ky_db_path())
        cur = con.cursor()
        cur.execute('SELECT kalip_kod, kalip_tipi FROM enj_kalip WHERE id = ?', (kalip_id,))
        r = cur.fetchone()
        if not r:
            con.close()
            return _jsonify_ky({'ok': False, 'hata': 'kalip bulunamadi'}), 404
        kalip_kod, kalip_tipi = r[0], r[1]
        
        # Yeni dosya adi: {kod}_{timestamp}.{ext}
        uzanti = f.filename.rsplit('.', 1)[-1].lower()
        ts = _ky_dt.datetime.now().strftime('%Y%m%d_%H%M%S')
        # kod icindeki ozel karakterleri temizle
        kod_safe = _ky_re.sub(r'[^A-Za-z0-9_-]', '_', kalip_kod or 'kalip')
        yeni_ad = f'{kod_safe}_{ts}.{uzanti}'
        
        klasor = _ky_img_klasor()
        tam_yol = _os_ky.path.join(klasor, yeni_ad)
        f.save(tam_yol)
        
        # DB guncelle
        cur.execute(
            'UPDATE enj_kalip SET gorsel_dosya = ?, guncelleme_tarihi = CURRENT_TIMESTAMP WHERE id = ?',
            (yeni_ad, kalip_id)
        )
        con.commit()
        
        # Guncel kayit
        cur.execute("""
            SELECT id, kalip_kod, kalip_tipi, model_kod, model_ad, asorti,
                   kalip_basi_cift, varsayilan_bagli_kalip, renk, gorsel_dosya, aktif
            FROM enj_kalip WHERE id = ?
        """, (kalip_id,))
        r2 = cur.fetchone()
        con.close()
        
        kayit = {
            'id': r2[0], 'kalip_kod': r2[1], 'kalip_tipi': r2[2], 'model_kod': r2[3],
            'model_ad': r2[4], 'asorti': r2[5], 'kalip_basi_cift': r2[6],
            'varsayilan_bagli_kalip': r2[7], 'renk': r2[8], 'gorsel_dosya': r2[9],
            'aktif': r2[10],
        }
        
        try:
            audit.log(_u(), 'kalip_gorsel_yukle', f'kalip_id={kalip_id} kod={kalip_kod} dosya={yeni_ad}')
        except Exception:
            pass
        
        return _jsonify_ky({'ok': True, 'gorsel_dosya': yeni_ad, 'kayit': kayit})
    except Exception as e:
        return _jsonify_ky({'ok': False, 'hata': str(e)}), 500

# === END: F_KALIP_GORSEL_UPLOAD ===


# ════════════════════════════════════════════════════════════════
# CORE_ILISKI FAZ5 SPRINT 5.1 — Organizasyon API + Sayfa
# BEGIN CORE_ORGANIZASYON
# ════════════════════════════════════════════════════════════════

@yonetim_bp.route('/core-organizasyon', methods=['GET'])
@yetki_gerekli('yonetim', 'can_view')
def core_organizasyon():
    return render_template('yonetim/core_organizasyon.html')


@yonetim_bp.route('/api/core/organizasyon/ozet', methods=['GET'])
@yetki_gerekli('yonetim', 'can_view')
def core_organizasyon_ozet():
    con = _get_conn()
    try:
        toplam_profil    = con.execute("SELECT COUNT(*) FROM kullanici_profil WHERE aktif=1").fetchone()[0]
        toplam_departman = con.execute("SELECT COUNT(*) FROM departman_master WHERE aktif=1").fetchone()[0]
        toplam_ekip      = con.execute("SELECT COUNT(*) FROM ekip_master WHERE aktif=1").fetchone()[0]
        toplam_proses    = con.execute("SELECT COUNT(*) FROM proses_master_ref WHERE aktif=1").fetchone()[0]
        bridge_bagli     = con.execute("SELECT COUNT(*) FROM personel_kullanici WHERE SistemKullaniciId IS NOT NULL").fetchone()[0]
        bridge_eksik     = con.execute("SELECT COUNT(*) FROM personel_kullanici WHERE SistemKullaniciId IS NULL AND aktif=1").fetchone()[0]
        ekip_eksik       = con.execute("""
            SELECT COUNT(*) FROM kullanici_profil kp
            WHERE kp.aktif=1
              AND NOT EXISTS (SELECT 1 FROM kullanici_ekip ke WHERE ke.kullanici_profil_id=kp.id AND ke.aktif=1)
        """).fetchone()[0]
        proses_eksik     = con.execute("""
            SELECT COUNT(*) FROM kullanici_profil kp
            WHERE kp.aktif=1
              AND NOT EXISTS (SELECT 1 FROM kullanici_proses kup WHERE kup.kullanici_profil_id=kp.id AND kup.aktif=1)
        """).fetchone()[0]
        usta_personel_iliski_sayisi = con.execute(
            "SELECT COUNT(*) FROM usta_personel_iliskisi WHERE aktif=1"
        ).fetchone()[0]
    finally:
        con.close()
    return jsonify({
        "ok": True,
        "toplam_profil":    toplam_profil,
        "toplam_departman": toplam_departman,
        "toplam_ekip":      toplam_ekip,
        "toplam_proses":    toplam_proses,
        "bridge_bagli":     bridge_bagli,
        "bridge_eksik":     bridge_eksik,
        "ekip_eksik":       ekip_eksik,
        "proses_eksik":     proses_eksik,
        "usta_personel_iliski_sayisi": usta_personel_iliski_sayisi,
    })


@yonetim_bp.route('/api/core/organizasyon/kullanicilar', methods=['GET'])
@yetki_gerekli('yonetim', 'can_view')
def core_organizasyon_kullanicilar():
    con = _get_conn()
    try:
        rows = con.execute("""
            SELECT
                kp.id                                       AS profil_id,
                kp.gercek_ad                                AS ad_soyad,
                kp.kullanici_adi,
                kp.profil_tipi,
                kp.aktif,
                dm.ad                                       AS departman,
                dm.kod                                      AS departman_kod,
                GROUP_CONCAT(DISTINCT em.ad)                AS ekipler,
                GROUP_CONCAT(DISTINCT ke.rol)               AS ekip_rolleri,
                GROUP_CONCAT(DISTINCT pm.kod)               AS proses_kodlar,
                GROUP_CONCAT(DISTINCT pm.ad)                AS proses_adlar,
                GROUP_CONCAT(DISTINCT kup.iliski_tipi)      AS proses_iliskiler,
                CASE WHEN pk.id IS NOT NULL THEN 1 ELSE 0 END AS bridge_var_mi
            FROM kullanici_profil kp
            LEFT JOIN departman_master   dm  ON dm.id  = kp.departman_id
            LEFT JOIN kullanici_ekip     ke  ON ke.kullanici_profil_id = kp.id AND ke.aktif=1
            LEFT JOIN ekip_master        em  ON em.id  = ke.ekip_id
            LEFT JOIN kullanici_proses   kup ON kup.kullanici_profil_id = kp.id AND kup.aktif=1
            LEFT JOIN proses_master_ref  pm  ON pm.id  = kup.proses_id
            LEFT JOIN personel_kullanici pk  ON pk.SistemKullaniciId = (
                SELECT sk.Id FROM sistem_kullanici sk
                WHERE sk.KullaniciAdi = kp.kullanici_adi LIMIT 1)
            GROUP BY kp.id
            ORDER BY dm.sira, kp.gercek_ad
        """).fetchall()
    finally:
        con.close()
    FONKSIYONEL = {'admin', 'muhasebe', 'cin.ofis'}
    liste = []
    for r in rows:
        ekip_r   = r["ekipler"].split(",")[0]  if r["ekipler"]  else None
        ekipr_r  = r["ekip_rolleri"].split(",")[0] if r["ekip_rolleri"] else None
        proses_r = r["proses_adlar"].split(",")[0] if r["proses_adlar"] else None
        proses_n = len(r["proses_kodlar"].split(",")) if r["proses_kodlar"] else 0
        liste.append({
            "profil_id":         r["profil_id"],
            "ad_soyad":          r["ad_soyad"],
            "kullanici_adi":     r["kullanici_adi"],
            "profil_tipi":       r["profil_tipi"],
            "aktif":             r["aktif"],
            "departman":         r["departman"],
            "departman_kod":     r["departman_kod"],
            "ekip":              ekip_r,
            "ekip_rolu":         ekipr_r,
            "proses_sayisi":     proses_n,
            "proses_ozet":       (proses_r + ("..." if proses_n > 1 else "")) if proses_r else None,
            "proses_iliskiler":  r["proses_iliskiler"],
            "bridge_var_mi":     bool(r["bridge_var_mi"]),
            "fonksiyonel_hesap": r["kullanici_adi"] in FONKSIYONEL or r["profil_tipi"] in ("sistem","ofis"),
        })
    return jsonify({"ok": True, "kullanicilar": liste})

# END CORE_ORGANIZASYON
# ════

# ════════════════════════════════════════════════════════════════
# CORE_ILISKI FAZ5 SPRINT 5.2 — Detay Drawer API
# BEGIN CORE_DRAWER
# ════════════════════════════════════════════════════════════════

@yonetim_bp.route('/api/core/organizasyon/kullanici/<int:profil_id>', methods=['GET'])
@yetki_gerekli('yonetim', 'can_view')
def core_kullanici_detay(profil_id):
    con = _get_conn()
    try:
        kp = con.execute("""
            SELECT kp.id, kp.gercek_ad, kp.kullanici_adi, kp.profil_tipi, kp.aktif,
                   dm.ad dept_ad, dm.kod dept_kod
            FROM kullanici_profil kp
            LEFT JOIN departman_master dm ON dm.id=kp.departman_id
            WHERE kp.id=?
        """, (profil_id,)).fetchone()
        if not kp:
            return jsonify({"ok": False, "hata": "Profil bulunamadı"}), 404

        ekipler = con.execute("""
            SELECT em.ad ekip_ad, em.kod ekip_kod, ke.rol, ev.vardiya_adi
            FROM kullanici_ekip ke
            JOIN ekip_master em ON em.id=ke.ekip_id
            LEFT JOIN ekip_vardiya ev ON ev.ekip_id=em.id
            WHERE ke.kullanici_profil_id=? AND ke.aktif=1
        """, (profil_id,)).fetchall()

        prosesler = con.execute("""
            SELECT pm.kod, pm.ad, pm.kategori, kup.iliski_tipi, kup.kaynak
            FROM kullanici_proses kup
            JOIN proses_master_ref pm ON pm.id=kup.proses_id
            WHERE kup.kullanici_profil_id=? AND kup.aktif=1
            ORDER BY pm.sira
        """, (profil_id,)).fetchall()

        # Bridge: sifre ASLA donme
        bridge = con.execute("""
            SELECT pk.id, pk.ad, pk.IdentityDurum, pk.GuvenSkoru,
                   pk.SistemKullaniciId, pk.aktif
            FROM personel_kullanici pk
            WHERE pk.SistemKullaniciId=(
                SELECT sk.Id FROM sistem_kullanici sk
                WHERE sk.KullaniciAdi=? LIMIT 1)
        """, (kp["kullanici_adi"],)).fetchone()

        # FAZ1C-4A: SAHA_PERSONEL icin aktif usta baglantisi
        bagli_usta_id = bagli_usta_ad = iliski_id = None
        if kp["profil_tipi"] == "SAHA_PERSONEL":
            upi = con.execute("""
                SELECT upi.id AS iliski_id, u.id AS usta_id, u.gercek_ad AS usta_ad
                FROM usta_personel_iliskisi upi
                JOIN kullanici_profil u ON u.id = upi.usta_profil_id
                WHERE upi.personel_profil_id = ? AND upi.aktif = 1
                ORDER BY upi.id DESC
                LIMIT 1
            """, (profil_id,)).fetchone()
            if upi:
                bagli_usta_id = upi["usta_id"]
                bagli_usta_ad = upi["usta_ad"]
                iliski_id = upi["iliski_id"]

    finally:
        con.close()

    return jsonify({
        "ok": True,
        "profil": {
            "id":           kp["id"],
            "ad_soyad":     kp["gercek_ad"],
            "kullanici_adi":kp["kullanici_adi"],
            "profil_tipi":  kp["profil_tipi"],
            "aktif":        kp["aktif"],
            "departman":    kp["dept_ad"],
            "departman_kod":kp["dept_kod"],
        },
        "ekipler": [{"ad": r["ekip_ad"], "kod": r["ekip_kod"],
                     "rol": r["rol"], "vardiya": r["vardiya_adi"]} for r in ekipler],
        "prosesler": [{"kod": r["kod"], "ad": r["ad"],
                       "kategori": r["kategori"], "iliski": r["iliski_tipi"]} for r in prosesler],
        "bridge": {
            "var": bool(bridge),
            "pk_ad":          bridge["ad"]            if bridge else None,
            "identity_durum": bridge["IdentityDurum"] if bridge else None,
            "guven_skoru":    bridge["GuvenSkoru"]     if bridge else None,
        } if bridge else {"var": False},
        "bagli_usta_id":  bagli_usta_id,
        "bagli_usta_ad":  bagli_usta_ad,
        "iliski_id":      iliski_id,
    })


@yonetim_bp.route('/api/core/organizasyon/ekip/<int:ekip_id>', methods=['GET'])
@yetki_gerekli('yonetim', 'can_view')
def core_ekip_detay(ekip_id):
    con = _get_conn()
    try:
        em = con.execute("""
            SELECT em.id, em.ad, em.kod, em.ekip_tipi,
                   dm.ad dept_ad, dm.kod dept_kod,
                   kp.gercek_ad lider_ad, kp.kullanici_adi lider_kadi,
                   ev.vardiya_adi
            FROM ekip_master em
            LEFT JOIN departman_master dm ON dm.id=em.departman_id
            LEFT JOIN kullanici_profil kp ON kp.id=em.lider_kullanici_profil_id
            LEFT JOIN ekip_vardiya ev ON ev.ekip_id=em.id
            WHERE em.id=?
        """, (ekip_id,)).fetchone()
        if not em:
            return jsonify({"ok": False, "hata": "Ekip bulunamadı"}), 404

        uyeler = con.execute("""
            SELECT kp.id, kp.gercek_ad, kp.kullanici_adi, kp.profil_tipi,
                   ke.rol, dm.ad dept_ad
            FROM kullanici_ekip ke
            JOIN kullanici_profil kp ON kp.id=ke.kullanici_profil_id
            LEFT JOIN departman_master dm ON dm.id=kp.departman_id
            WHERE ke.ekip_id=? AND ke.aktif=1
            ORDER BY ke.rol DESC, kp.gercek_ad
        """, (ekip_id,)).fetchall()

        prosesler = con.execute("""
            SELECT pm.kod, pm.ad, pm.kategori
            FROM ekip_proses ep
            JOIN proses_master_ref pm ON pm.id=ep.proses_id
            WHERE ep.ekip_id=? AND ep.aktif=1
            ORDER BY pm.sira
        """, (ekip_id,)).fetchall()

    finally:
        con.close()

    return jsonify({
        "ok": True,
        "ekip": {
            "id":         em["id"],
            "ad":         em["ad"],
            "kod":        em["kod"],
            "ekip_tipi":  em["ekip_tipi"],
            "departman":  em["dept_ad"],
            "vardiya":    em["vardiya_adi"],
            "lider_ad":   em["lider_ad"],
            "lider_kadi": em["lider_kadi"],
            "uye_sayisi": len(uyeler),
        },
        "uyeler": [{"id": r["id"], "ad": r["gercek_ad"],
                    "kullanici_adi": r["kullanici_adi"],
                    "rol": r["rol"], "dept": r["dept_ad"]} for r in uyeler],
        "prosesler": [{"kod": r["kod"], "ad": r["ad"],
                       "kategori": r["kategori"]} for r in prosesler],
    })

# END CORE_DRAWER
# ════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════
# FAZ1C-2 — Usta-Personel Bağlama API
# BEGIN USTA_PERSONEL_BAGLA
# ════════════════════════════════════════════════════════════════

@yonetim_bp.route('/api/core/usta-personel/bagla', methods=['POST'])
@yetki_gerekli('yonetim', 'can_create')
def core_usta_personel_bagla():
    """
    Bir SAHA_USTASI ile bir SAHA_PERSONEL arasında usta_personel_iliskisi kaydı oluşturur.

    Body (JSON):
      usta_profil_id     int  zorunlu  — kullanici_profil.id (profil_tipi=SAHA_USTASI)
      personel_profil_id int  zorunlu  — kullanici_profil.id (profil_tipi=SAHA_PERSONEL)
      proses_id          int  opsiyonel
      departman_id       int  opsiyonel

    Validasyon:
      - usta profil_tipi = SAHA_USTASI olmalı
      - personel profil_tipi = SAHA_PERSONEL olmalı
      - aynı (usta, personel, proses_id) ile aktif kayıt varsa duplicate yazılmaz
    """
    data = request.get_json(silent=True) or {}

    usta_profil_id     = data.get('usta_profil_id')
    personel_profil_id = data.get('personel_profil_id')
    proses_id          = data.get('proses_id') or None
    departman_id       = data.get('departman_id') or None

    if not usta_profil_id or not personel_profil_id:
        return jsonify({'ok': False, 'hata': 'usta_profil_id ve personel_profil_id zorunlu'}), 400

    try:
        usta_profil_id     = int(usta_profil_id)
        personel_profil_id = int(personel_profil_id)
        if proses_id    is not None: proses_id    = int(proses_id)
        if departman_id is not None: departman_id = int(departman_id)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'hata': 'id alanları sayısal olmalı'}), 400

    con = _get_conn()
    try:
        # Usta kontrolü
        usta = con.execute(
            "SELECT id, gercek_ad, profil_tipi FROM kullanici_profil WHERE id=? AND aktif=1",
            (usta_profil_id,)
        ).fetchone()
        if not usta:
            return jsonify({'ok': False, 'hata': f'usta_profil_id={usta_profil_id} bulunamadı'}), 404
        if usta['profil_tipi'] != 'SAHA_USTASI':
            return jsonify({
                'ok': False,
                'hata': f"'{usta['gercek_ad']}' profil_tipi={usta['profil_tipi']} — SAHA_USTASI olmalı"
            }), 422

        # Personel kontrolü
        personel = con.execute(
            "SELECT id, gercek_ad, profil_tipi FROM kullanici_profil WHERE id=? AND aktif=1",
            (personel_profil_id,)
        ).fetchone()
        if not personel:
            return jsonify({'ok': False, 'hata': f'personel_profil_id={personel_profil_id} bulunamadı'}), 404
        if personel['profil_tipi'] != 'SAHA_PERSONEL':
            return jsonify({
                'ok': False,
                'hata': f"'{personel['gercek_ad']}' profil_tipi={personel['profil_tipi']} — SAHA_PERSONEL olmalı"
            }), 422

        # Duplicate kontrolü: aynı (usta, personel, proses_id) ile aktif kayıt
        dup = con.execute("""
            SELECT id FROM usta_personel_iliskisi
            WHERE usta_profil_id=? AND personel_profil_id=?
              AND (proses_id IS ? OR (proses_id IS NULL AND ? IS NULL))
              AND aktif=1
        """, (usta_profil_id, personel_profil_id, proses_id, proses_id)).fetchone()
        if dup:
            return jsonify({
                'ok': False,
                'hata': 'Bu usta-personel-proses kombinasyonu zaten aktif',
                'mevcut_iliski_id': dup['id']
            }), 409

        # Kaydet
        olusturan_id = (session.get('kullanici') or {}).get('Id')
        con.execute("""
            INSERT INTO usta_personel_iliskisi
              (usta_profil_id, personel_profil_id, proses_id, departman_id,
               aktif, kaynak, olusturan_id)
            VALUES (?, ?, ?, ?, 1, 'manuel', ?)
        """, (usta_profil_id, personel_profil_id, proses_id, departman_id, olusturan_id))
        con.commit()
        yeni_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

    finally:
        con.close()

    audit.log(_u(), 'usta_personel_bagla', 'usta_personel_iliskisi', yeni_id,
              aciklama=f'usta={usta["gercek_ad"]} personel={personel["gercek_ad"]}')

    return jsonify({
        'ok': True,
        'iliski_id': yeni_id,
        'usta':     {'id': usta['id'],     'ad': usta['gercek_ad']},
        'personel': {'id': personel['id'], 'ad': personel['gercek_ad']},
        'proses_id':    proses_id,
        'departman_id': departman_id,
    }), 201

# END USTA_PERSONEL_BAGLA
# ════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════
# CORE_ILISKI FAZ1C-3 — Usta Listesi API
# BEGIN USTA_PERSONEL_USTALAR
# ════════════════════════════════════════════════════════════════

@yonetim_bp.route('/api/core/usta-personel/ustalar', methods=['GET'])
@yetki_gerekli('yonetim', 'can_view')
def core_usta_personel_ustalar():
    """
    Aktif SAHA_USTASI listesini ve her birinin bağlı personel sayısını döner.
    Drawer dropdown için kullanılır.
    """
    con = _get_conn()
    try:
        rows = con.execute("""
            SELECT
                kp.id,
                kp.gercek_ad AS ad_soyad,
                COUNT(upi.id) AS bagli_personel_sayisi
            FROM kullanici_profil kp
            LEFT JOIN usta_personel_iliskisi upi
                   ON upi.usta_profil_id = kp.id AND upi.aktif = 1
            WHERE kp.profil_tipi = 'SAHA_USTASI' AND kp.aktif = 1
            GROUP BY kp.id
            ORDER BY kp.gercek_ad
        """).fetchall()
    finally:
        con.close()
    return jsonify({
        "ok": True,
        "ustalar": [
            {
                "id":                   r["id"],
                "ad_soyad":             r["ad_soyad"],
                "bagli_personel_sayisi": r["bagli_personel_sayisi"]
            }
            for r in rows
        ]
    })

# END USTA_PERSONEL_USTALAR
# ════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════
# TASKS ADMIN TAKİP PANELİ
# BEGIN GOREV_TAKIP
# ════════════════════════════════════════════════════════════════

@yonetim_bp.route('/gorev-takip', methods=['GET'])
@yetki_gerekli('yonetim', 'can_view')
def gorev_takip():
    return render_template('yonetim/gorev_takip.html')


@yonetim_bp.route('/api/gorev-takip', methods=['GET'])
@yetki_gerekli('yonetim', 'can_view')
def api_gorev_takip():
    from flask import request as _req
    from datetime import datetime as _dt

    status_filtre = _req.args.get('status', '')
    source_filtre = _req.args.get('source', '')
    atanan_filtre = _req.args.get('assigned_to', '')

    con = _get_conn()
    try:
        sql = """
            SELECT
                t.id                                                        AS task_id,
                t.title,
                t.task_type,
                t.priority,
                t.status,
                t.assigned_to,
                COALESCE(tu_h.ad, t.assigned_to)                            AS assigned_to_ad,
                t.created_by,
                COALESCE(tu_o.ad, t.created_by)                             AS created_by_ad,
                t.related_order_no,
                t.baglam_ozet,
                t.baglam_tipi,
                t.auto_source,
                t.created_at,
                t.seen_at,
                t.started_at,
                t.completed_at,
                t.due_date,
                ROUND((julianday('now','localtime') -
                       julianday(t.created_at)) * 24, 1)                    AS age_hours,
                CAST((julianday('now','localtime') -
                      julianday(t.created_at)) AS INTEGER)                  AS age_days,
                COUNT(DISTINCT bl.id)                                       AS notification_count,
                MAX(bl.gonderim_zamani)                                     AS last_notification_at,
                SUM(CASE WHEN bl.okundu_mu=1 THEN 1 ELSE 0 END)            AS okundu_sayisi,
                COALESCE(MAX(bl.dismiss_count), 0)                          AS max_dismiss
            FROM tasks t
            LEFT JOIN tasks_users tu_h  ON tu_h.kullanici_adi  = t.assigned_to
            LEFT JOIN tasks_users tu_o  ON tu_o.kullanici_adi  = t.created_by
            LEFT JOIN bildirim_log bl
                ON bl.veri_json LIKE '%"task_id":' || t.id || '%'
                AND bl.tip LIKE 'gorev_%'
            WHERE 1=1
        """
        params = []

        if status_filtre:
            placeholders = ','.join(['?' for s in status_filtre.split(',')])
            sql += f" AND t.status IN ({placeholders})"
            params.extend([s.strip() for s in status_filtre.split(',')])

        if source_filtre:
            sql += " AND t.auto_source = ?"
            params.append(source_filtre)

        if atanan_filtre:
            sql += " AND t.assigned_to = ?"
            params.append(atanan_filtre)

        sql += """
            GROUP BY t.id
            ORDER BY
                CASE t.status
                    WHEN 'bekliyor'     THEN 1
                    WHEN 'devam_ediyor' THEN 2
                    WHEN 'tamamlandi'   THEN 3
                    ELSE 4 END,
                CASE t.priority
                    WHEN 'kritik'  THEN 1
                    WHEN 'yuksek'  THEN 2
                    WHEN 'orta'    THEN 3
                    ELSE 4 END,
                t.created_at DESC
        """

        rows = con.execute(sql, params).fetchall()

        # SLA overdue hesabı
        SLA_SAAT = {'kritik': 0.25, 'yuksek': 0.5, 'orta': 1.0, 'dusuk': 4.0}
        tasks = []
        for r in rows:
            age_h = r['age_hours'] or 0
            sla   = SLA_SAAT.get(r['priority'] or 'orta', 1.0)
            done  = r['status'] in ('tamamlandi', 'iptal')
            overdue = 0
            if not done:
                if r['due_date'] and r['due_date'] < _dt.now().strftime('%Y-%m-%d'):
                    overdue = 1
                elif age_h > sla:
                    overdue = 1

            # renk
            if done:
                renk = 'yesil'
            elif overdue:
                renk = 'kirmizi'
            elif age_h > sla * 0.5:
                renk = 'sari'
            else:
                renk = 'yesil'

            tasks.append({
                'task_id':              r['task_id'],
                'title':                r['title'],
                'task_type':            r['task_type'],
                'priority':             r['priority'],
                'status':               r['status'],
                'assigned_to':          r['assigned_to'],
                'assigned_to_ad':       r['assigned_to_ad'],
                'created_by':           r['created_by'],
                'created_by_ad':        r['created_by_ad'],
                'related_order_no':     r['related_order_no'],
                'baglam_ozet':          r['baglam_ozet'],
                'baglam_tipi':          r['baglam_tipi'],
                'auto_source':          r['auto_source'],
                'created_at':           r['created_at'],
                'seen_at':              r['seen_at'],
                'started_at':           r['started_at'],
                'completed_at':         r['completed_at'],
                'age_hours':            round(age_h, 1),
                'age_days':             r['age_days'] or 0,
                'notification_count':   r['notification_count'] or 0,
                'last_notification_at': r['last_notification_at'],
                'okundu_sayisi':        r['okundu_sayisi'] or 0,
                'max_dismiss':          r['max_dismiss'] or 0,
                'overdue':              overdue,
                'renk':                 renk,
                'sla_saat':             sla,
            })

        acik    = sum(1 for t in tasks if t['status'] in ('bekliyor','devam_ediyor'))
        gecikis = sum(1 for t in tasks if t['overdue'])

        return jsonify({
            'ok':      True,
            'toplam':  len(tasks),
            'acik':    acik,
            'gecikis': gecikis,
            'tasks':   tasks,
        })

    except Exception as e:
        import traceback
        return jsonify({'ok': False, 'hata': str(e), 'tb': traceback.format_exc()}), 500
    finally:
        con.close()

# END GOREV_TAKIP
# ════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════
# FAZ43 SPRINT 9 — Escalation Motoru
# BEGIN ESCALATION_CHECK
# ════════════════════════════════════════════════════════════════

@yonetim_bp.route('/api/escalation/check', methods=['POST'])
@yetki_gerekli('yonetim', 'can_create')
def api_escalation_check():
    """
    Bekleyen/geciken görevler için escalation bildirimi üret.
    Manuel tetiklemeli — otomatik cron YOK.
    """
    from datetime import datetime as _dt
    import json as _json

    SLA_SAAT = {
        'kritik': 0.25,   # 15 dk
        'yuksek': 0.5,    # 30 dk
        'orta':   1.0,    # 1 saat
        'dusuk':  4.0,    # 4 saat
    }
    SPAM_GUARD_DK = 60   # aynı task için 60 dk içinde tekrar yok
    MAX_DISMISS   = 5    # 5 kez kapandıysa dur

    con = _get_conn()
    try:
        now_str = _dt.now().strftime('%Y-%m-%d %H:%M:%S')

        # Açık görevleri çek
        gorevler = con.execute("""
            SELECT t.id, t.title, t.priority, t.status,
                   t.assigned_to, t.related_order_no, t.baglam_ozet,
                   t.auto_source,
                   ROUND((julianday('now','localtime') -
                          julianday(t.created_at)) * 24, 2) AS age_hours,
                   t.started_at
            FROM tasks t
            WHERE t.status IN ('bekliyor', 'devam_ediyor')
        """).fetchall()

        # Yönetim kullanıcısı (escalation seviye 3 hedefi)
        yonetim_user = con.execute(
            "SELECT id, rol FROM tasks_users WHERE rol='admin' AND aktif=1 LIMIT 1"
        ).fetchone()

        detay    = []
        uretilen = 0
        atlanan  = 0

        for g in gorevler:
            task_id  = g['id']
            age_h    = g['age_hours'] or 0
            priority = g['priority'] or 'orta'
            sla_h    = SLA_SAAT.get(priority, 1.0)
            assigned = g['assigned_to'] or ''

            # SLA geçmedi mi?
            if age_h < sla_h:
                continue

            # Spam guard: son 60 dk içinde bu task için escalation var mı?
            son_esc = con.execute("""
                SELECT id, dismiss_count FROM bildirim_log
                WHERE veri_json LIKE '%"task_id":' || ? || '%'
                  AND tip = 'gorev_escalation'
                ORDER BY gonderim_zamani DESC LIMIT 1
            """, (task_id,)).fetchone()

            if son_esc:
                if son_esc['dismiss_count'] >= MAX_DISMISS:
                    detay.append({'task_id': task_id, 'durum': 'atlandi_dismiss',
                                  'sebep': f"dismiss_count={son_esc['dismiss_count']}"})
                    atlanan += 1
                    continue
                # 60 dk geçmedi mi?
                son_esc2 = con.execute("""
                    SELECT id FROM bildirim_log
                    WHERE veri_json LIKE '%"task_id":' || ? || '%'
                      AND tip = 'gorev_escalation'
                      AND gonderim_zamani > datetime('now','localtime','-' || ? || ' minutes')
                    LIMIT 1
                """, (task_id, SPAM_GUARD_DK)).fetchone()
                if son_esc2:
                    detay.append({'task_id': task_id, 'durum': 'atlandi_spam',
                                  'sebep': f"{SPAM_GUARD_DK}dk içinde zaten gönderildi"})
                    atlanan += 1
                    continue

            # Escalation seviyesi belirle
            eskalasyon_seviye = 1
            if age_h >= sla_h * 4:
                eskalasyon_seviye = 3
            elif age_h >= sla_h * 2:
                eskalasyon_seviye = 2

            veri = {
                'task_id':            task_id,
                'title':              g['title'],
                'age_hours':          round(age_h, 1),
                'priority':           priority,
                'escalation_level':   eskalasyon_seviye,
                'siparis_no':         g['related_order_no'] or '',
                'auto_source':        g['auto_source'] or '',
            }
            veri_str = _json.dumps(veri, ensure_ascii=False)

            def _bildirim_gonder(hedef_kullanici_adi, seviye_ad):
                tu = con.execute(
                    "SELECT id, rol FROM tasks_users WHERE kullanici_adi=? AND aktif=1 LIMIT 1",
                    (hedef_kullanici_adi,)
                ).fetchone()
                if not tu:
                    return False
                mesaj = (f"[Seviye {seviye_ad}] '{g['title']}' görevi "
                         f"{round(age_h,1)} saattir bekliyor")
                con.execute("""
                    INSERT INTO bildirim_log
                      (kullanici_id, rol, tip, mesaj, veri_json,
                       gonderim_zamani, okundu_mu, push_gonderildi_mi)
                    VALUES (?,?,?,?,?,?,0,0)
                """, (tu[0], tu[1], 'gorev_escalation',
                      mesaj, veri_str, now_str))
                return True

            # Seviye 1: atanan kişi
            ok1 = _bildirim_gonder(assigned, '1-Atanan')
            g_uretilen = 1 if ok1 else 0

            # Seviye 2: ekip lideri
            if eskalasyon_seviye >= 2:
                lider = con.execute("""
                    SELECT kp2.kullanici_adi
                    FROM kullanici_profil kp
                    JOIN kullanici_ekip ke ON ke.kullanici_profil_id=kp.id AND ke.aktif=1
                    JOIN ekip_master em    ON em.id=ke.ekip_id
                    JOIN kullanici_profil kp2 ON kp2.id=em.lider_kullanici_profil_id
                    WHERE kp.kullanici_adi=? LIMIT 1
                """, (assigned,)).fetchone()
                if lider and lider[0] != assigned:
                    ok2 = _bildirim_gonder(lider[0], '2-Lider')
                    if ok2: g_uretilen += 1

            # Seviye 3: yönetim
            if eskalasyon_seviye >= 3 and yonetim_user:
                yonetim_kadi = con.execute(
                    "SELECT kullanici_adi FROM tasks_users WHERE id=? LIMIT 1",
                    (yonetim_user['id'],)
                ).fetchone()
                if yonetim_kadi and yonetim_kadi[0] != assigned:
                    ok3 = _bildirim_gonder(yonetim_kadi[0], '3-Yönetim')
                    if ok3: g_uretilen += 1

            con.commit()
            uretilen += g_uretilen
            detay.append({
                'task_id':   task_id,
                'title':     g['title'],
                'durum':     'escalation_uretildi',
                'age_hours': round(age_h, 1),
                'seviye':    eskalasyon_seviye,
                'uretilen':  g_uretilen,
            })

        return jsonify({
            'ok':                True,
            'kontrol_sayisi':    len(gorevler),
            'escalation_uretildi': uretilen,
            'spam_atlandi':      atlanan,
            'detay':             detay,
        })

    except Exception as e:
        con.rollback()
        import traceback
        return jsonify({'ok': False, 'hata': str(e),
                        'tb': traceback.format_exc()}), 500
    finally:
        con.close()

# END ESCALATION_CHECK
# ════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════
# FAZ43 SPRINT 10 — Operasyon Timeline
# BEGIN OPERASYON_TIMELINE
# ════════════════════════════════════════════════════════════════

@yonetim_bp.route('/api/gorev/<int:task_id>/timeline', methods=['GET'])
@yetki_gerekli('yonetim', 'can_view')
def api_gorev_timeline(task_id):
    """
    Bir görevin tüm olay akışını kronolojik sırayla döndürür.
    Kaynak: tasks + bildirim_log + task_logs
    """
    import json as _json

    con = _get_conn()
    try:
        # Görev var mı?
        task = con.execute(
            "SELECT id,title,status,priority,assigned_to,created_by,"
            "created_at,started_at,completed_at,approved_at,rejected_at "
            "FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        if not task:
            return jsonify({"ok": False, "hata": "Görev bulunamadı"}), 404

        olaylar = []

        # ── 1. Görev oluşturuldu ────────────────────────────────
        olaylar.append({
            "tip":      "gorev_olusturuldu",
            "zaman":    task["created_at"],
            "kullanici": task["created_by"],
            "mesaj":    f"Görev oluşturuldu: {task['title']}",
            "renk":     "mavi",
            "kaynak":   "tasks",
        })

        # ── 2. bildirim_log olayları ────────────────────────────
        bildirimler = con.execute("""
            SELECT bl.id, bl.tip, bl.mesaj, bl.gonderim_zamani,
                   bl.veri_json, tu.kullanici_adi
            FROM bildirim_log bl
            LEFT JOIN tasks_users tu ON tu.id = bl.kullanici_id
            WHERE bl.veri_json LIKE '%"task_id":' || ? || '%'
            ORDER BY bl.gonderim_zamani ASC
        """, (task_id,)).fetchall()

        TIP_RENK = {
            "gorev_yeni":        "mavi",
            "gorev_basladi":     "yesil",
            "gorev_tamamlandi":  "yesil",
            "gorev_iptal":       "gri",
            "gorev_escalation":  "turuncu",
            "gorev_gecikme":     "kirmizi",
        }
        TIP_ETIKET = {
            "gorev_yeni":       "Bildirim gönderildi",
            "gorev_basladi":    "Başladı bildirimi",
            "gorev_tamamlandi": "Tamamlandı bildirimi",
            "gorev_iptal":      "İptal bildirimi",
            "gorev_escalation": "Escalation",
            "gorev_gecikme":    "Gecikme uyarısı",
        }

        for b in bildirimler:
            tip   = b["tip"] or ""
            veri  = {}
            try:
                veri = _json.loads(b["veri_json"] or "{}")
            except Exception:
                pass

            eskalasyon_seviye = veri.get("escalation_level", 0)
            if eskalasyon_seviye == 2:
                tip_goster = "escalation_lvl2"
            elif eskalasyon_seviye == 3:
                tip_goster = "escalation_lvl3"
            elif tip == "gorev_escalation":
                tip_goster = "escalation_lvl1"
            else:
                tip_goster = tip

            olaylar.append({
                "tip":      tip_goster,
                "zaman":    b["gonderim_zamani"],
                "kullanici": b["kullanici_adi"] or "sistem",
                "mesaj":    b["mesaj"],
                "renk":     TIP_RENK.get(tip, "gri"),
                "kaynak":   "bildirim_log",
                "meta": {
                    "bildirim_id": b["id"],
                    "escalation_level": eskalasyon_seviye or None,
                },
            })

        # ── 3. task_logs olayları ───────────────────────────────
        logs = con.execute("""
            SELECT action, old_status, new_status, note, created_at, user_id
            FROM task_logs WHERE task_id=? ORDER BY created_at ASC
        """, (task_id,)).fetchall()

        LOG_RENK = {
            "started":   "yesil",
            "completed": "yesil",
            "cancelled": "gri",
            "approved":  "yesil",
            "rejected":  "kirmizi",
            "created":   "mavi",
        }
        LOG_MESAJ = {
            "started":   "Göreve başlandı",
            "completed": "Görev tamamlandı",
            "cancelled": "Görev iptal edildi",
            "approved":  "Görev onaylandı",
            "rejected":  "Görev reddedildi",
            "created":   "Görev kaydedildi",
        }

        for lg in logs:
            action = lg["action"] or ""
            if action == "created":
                continue  # zaten oluşturuldu olayı var
            olaylar.append({
                "tip":      "gorev_" + action,
                "zaman":    lg["created_at"],
                "kullanici": lg["user_id"] or "sistem",
                "mesaj":    LOG_MESAJ.get(action, action) +
                            (f" ({lg['old_status']} → {lg['new_status']})" if lg['old_status'] else ""),
                "renk":     LOG_RENK.get(action, "gri"),
                "kaynak":   "task_logs",
            })

        # ── Kronolojik sırala ───────────────────────────────────
        olaylar.sort(key=lambda x: x.get("zaman") or "")

        return jsonify({
            "ok":       True,
            "task_id":  task_id,
            "title":    task["title"],
            "status":   task["status"],
            "priority": task["priority"],
            "olay_sayisi": len(olaylar),
            "olaylar":  olaylar,
        })

    except Exception as e:
        import traceback
        return jsonify({"ok": False, "hata": str(e),
                        "tb": traceback.format_exc()}), 500
    finally:
        con.close()

# END OPERASYON_TIMELINE
# ════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════
# FAZ43 SPRINT 11 — Canlı Operasyon Akışı
# BEGIN CANLI_OPERASYON
# ════════════════════════════════════════════════════════════════

@yonetim_bp.route('/canli-operasyon', methods=['GET'])
@yetki_gerekli('yonetim', 'can_view')
def canli_operasyon():
    return render_template('yonetim/canli_operasyon.html')


@yonetim_bp.route('/api/operasyon/canli-akis', methods=['GET'])
@yetki_gerekli('yonetim', 'can_view')
def api_canli_akis():
    """
    Fabrika geneli son olaylar — tüm kaynaklardan birleşik.
    Filtre: ?sure=1h | 6h | bugun (varsayılan 6h)
    Limit: ?limit=100
    """
    from flask import request as _req
    import json as _json

    sure  = _req.args.get('sure', '6h')
    limit = min(int(_req.args.get('limit', 100)), 200)

    # Zaman filtresi
    if sure == '1h':
        since_sql = "datetime('now','localtime','-1 hours')"
    elif sure == 'bugun':
        since_sql = "date('now','localtime')"
    else:  # 6h varsayılan
        since_sql = "datetime('now','localtime','-6 hours')"

    con = _get_conn()
    try:
        olaylar = []

        # ── A. bildirim_log tüm olaylar ──────────────────────────
        bld_rows = con.execute(f"""
            SELECT
                bl.id, bl.tip, bl.mesaj, bl.gonderim_zamani AS zaman,
                bl.veri_json,
                tu.kullanici_adi, tu.ad AS kullanici_ad, tu.rol
            FROM bildirim_log bl
            LEFT JOIN tasks_users tu ON tu.id = bl.kullanici_id
            WHERE bl.gonderim_zamani >= {since_sql}
              AND bl.tip LIKE 'gorev_%'
            ORDER BY bl.gonderim_zamani DESC
            LIMIT ?
        """, (limit,)).fetchall()

        TIP_RENK = {
            'gorev_yeni':        'mavi',
            'gorev_basladi':     'yesil',
            'gorev_tamamlandi':  'yesil',
            'gorev_iptal':       'gri',
            'gorev_escalation':  'turuncu',
            'gorev_gecikme':     'kirmizi',
        }
        TIP_IKON = {
            'gorev_yeni':        '🔔',
            'gorev_basladi':     '▶️',
            'gorev_tamamlandi':  '✅',
            'gorev_iptal':       '❌',
            'gorev_escalation':  '⚡',
            'gorev_gecikme':     '⚠️',
        }

        for b in bld_rows:
            veri = {}
            try: veri = _json.loads(b['veri_json'] or '{}')
            except: pass

            tip = b['tip'] or ''
            esc_lvl = veri.get('escalation_level', 0)
            if tip == 'gorev_escalation' and esc_lvl >= 3:
                tip_goster = 'escalation_lvl3'
                renk = 'kirmizi'
                ikon = '🚨'
            elif tip == 'gorev_escalation' and esc_lvl == 2:
                tip_goster = 'escalation_lvl2'
                renk = 'turuncu'
                ikon = '⚠️'
            elif tip == 'gorev_escalation':
                tip_goster = 'escalation_lvl1'
                renk = 'turuncu'
                ikon = '⚡'
            else:
                tip_goster = tip
                renk = TIP_RENK.get(tip, 'gri')
                ikon = TIP_IKON.get(tip, '•')

            olaylar.append({
                'tip':        tip_goster,
                'zaman':      b['zaman'],
                'kullanici':  b['kullanici_ad'] or b['kullanici_adi'] or 'sistem',
                'mesaj':      b['mesaj'],
                'renk':       renk,
                'ikon':       ikon,
                'kaynak':     'bildirim',
                'task_id':    veri.get('task_id'),
                'siparis':    veri.get('siparis_no', ''),
                'proses':     veri.get('proses', ''),
            })

        # ── B. task_logs durum değişimleri ───────────────────────
        log_rows = con.execute(f"""
            SELECT tl.task_id, tl.action, tl.old_status, tl.new_status,
                   tl.created_at AS zaman, tl.user_id,
                   t.title, t.priority, t.related_order_no, t.assigned_to,
                   tu.ad AS kullanici_ad
            FROM task_logs tl
            JOIN tasks t ON t.id = tl.task_id
            LEFT JOIN tasks_users tu ON tu.kullanici_adi = tl.user_id
            WHERE tl.created_at >= {since_sql}
              AND tl.action NOT IN ('created')
            ORDER BY tl.created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()

        LOG_RENK = {
            'started':   'yesil',
            'completed': 'yesil',
            'cancelled': 'gri',
            'approved':  'yesil',
            'rejected':  'kirmizi',
        }
        LOG_IKON = {
            'started':   '▶️',
            'completed': '✅',
            'cancelled': '❌',
            'approved':  '✔️',
            'rejected':  '🚫',
        }
        LOG_MSG = {
            'started':   'Göreve başlandı',
            'completed': 'Görev tamamlandı',
            'cancelled': 'Görev iptal edildi',
            'approved':  'Görev onaylandı',
            'rejected':  'Görev reddedildi',
        }

        for lg in log_rows:
            action = lg['action'] or ''
            olaylar.append({
                'tip':      'gorev_' + action,
                'zaman':    lg['zaman'],
                'kullanici': lg['kullanici_ad'] or lg['user_id'] or 'sistem',
                'mesaj':    (LOG_MSG.get(action, action) + ': ' + (lg['title'] or '')),
                'renk':     LOG_RENK.get(action, 'gri'),
                'ikon':     LOG_IKON.get(action, '•'),
                'kaynak':   'task_log',
                'task_id':  lg['task_id'],
                'siparis':  lg['related_order_no'] or '',
                'proses':   '',
                'oncelik':  lg['priority'],
            })

        # ── Kronolojik sırala ────────────────────────────────────
        olaylar.sort(key=lambda x: x.get('zaman') or '', reverse=True)
        olaylar = olaylar[:limit]

        # ── KPI ─────────────────────────────────────────────────
        aktif_gorev = con.execute(
            "SELECT COUNT(*) FROM tasks WHERE status IN ('bekliyor','devam_ediyor')"
        ).fetchone()[0]
        escalation_sayisi = sum(
            1 for o in olaylar if 'escalation' in o.get('tip','')
        )
        tamamlanan = sum(
            1 for o in olaylar if 'tamamland' in o.get('tip','')
        )
        kritik = sum(
            1 for o in olaylar if o.get('renk') == 'kirmizi'
        )

        return jsonify({
            'ok':             True,
            'sure':           sure,
            'olay_sayisi':    len(olaylar),
            'kpi': {
                'aktif_gorev':     aktif_gorev,
                'son_olay_sayisi': len(olaylar),
                'escalation':      escalation_sayisi,
                'kritik':          kritik,
                'tamamlanan':      tamamlanan,
            },
            'olaylar': olaylar,
        })

    except Exception as e:
        import traceback
        return jsonify({'ok': False, 'hata': str(e),
                        'tb': traceback.format_exc()}), 500
    finally:
        con.close()

# END CANLI_OPERASYON
# ════════════════════════════════════════════════════════════════
