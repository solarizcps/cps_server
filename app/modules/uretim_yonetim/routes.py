# -*- coding: utf-8 -*-
"""
SOLARIZ CPS - FAZ 1
Backend Routes + Kilit Middleware

Endpoint'ler:
  GET  /uretim-yonetim/plan             -> Aktif siparisler + darbogaz ozeti
  GET  /uretim-yonetim/plan-detay/<sno> -> Tek siparisin tum proses detayi
  GET  /uretim-yonetim/kilit/durum      -> Kullanicinin kilit durumu
  POST /uretim-yonetim/sebep            -> Sebep gir + kilit kapat

Kilit korumasi:
  Plan/plan-detay endpoint'leri kullanici kilitliyse 403 doner.
  Sebep endpoint'i her zaman calisir.
"""
import sqlite3
from flask import Blueprint, jsonify, request, session, render_template
from config import Config
from modules.uretim_yonetim import darbogaz as db_motor
from modules.uretim_yonetim import sapma as sapma_motor


uretim_yonetim_bp = Blueprint(
    'uretim_yonetim_bp',
    __name__,
    url_prefix='/uretim-yonetim'
)


def _conn():
    conn = sqlite3.connect(Config.MOCK_DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _aktif_kullanici():
    """
    Faz 1 pilot: session'da kullanici varsa al, yoksa 'halil' fallback.
    Auth modulu dict donduruyor, KullaniciAdi alanini cek.
    """
    u = session.get('kullanici')
    if isinstance(u, dict):
        return u.get('KullaniciAdi') or 'halil'
    return u or 'halil'


def _kilit_durum(kullanici):
    """
    Kullanicinin kilit durumunu doner.
    Returns: dict {kilit_aktif, sapma_olay_id, baslangic, sapma_detay}
    """
    c = _conn()
    try:
        cur = c.cursor()
        cur.execute("""
            SELECT 
                ukd.kullanici,
                ukd.kilit_aktif,
                ukd.sapma_olay_id,
                ukd.baslangic,
                so.siparis_no,
                so.proses_kod,
                so.olmasi_gereken,
                so.gercek,
                so.sapma_yuzde,
                so.seviye,
                pk.proses_adi
            FROM usta_kilit_durum ukd
            LEFT JOIN sapma_olay so ON so.id = ukd.sapma_olay_id
            LEFT JOIN proses_kategori pk ON pk.proses_kod = so.proses_kod
            WHERE ukd.kullanici = ?
        """, (kullanici,))
        row = cur.fetchone()
        return dict(row) if row else {'kilit_aktif': 0}
    finally:
        c.close()


# =====================================================
# ENDPOINT 1: GET /uretim-yonetim/kilit/durum
# Frontend her sayfa yuklenirken bunu cagirir
# =====================================================
@uretim_yonetim_bp.route('/kilit/durum', methods=['GET'])
def kilit_durum():
    kullanici = _aktif_kullanici()
    durum = _kilit_durum(kullanici)
    
    return jsonify({
        'kullanici': kullanici,
        'kilit_aktif': bool(durum.get('kilit_aktif', 0)),
        'sapma_olay_id': durum.get('sapma_olay_id'),
        'sapma_detay': {
            'siparis_no': durum.get('siparis_no'),
            'proses_kod': durum.get('proses_kod'),
            'proses_adi': durum.get('proses_adi'),
            'olmasi_gereken': durum.get('olmasi_gereken'),
            'gercek': durum.get('gercek'),
            'sapma_yuzde': durum.get('sapma_yuzde'),
            'seviye': durum.get('seviye'),
        } if durum.get('sapma_olay_id') else None,
        'baslangic': durum.get('baslangic'),
    })


# =====================================================
# ENDPOINT 2: GET /uretim-yonetim/plan
# Kilitliyse 403 doner, degilse aktif siparisleri doner
# =====================================================
@uretim_yonetim_bp.route('/plan', methods=['GET'])
def plan():
    kullanici = _aktif_kullanici()
    durum = _kilit_durum(kullanici)
    
    # KILIT KORUMA
    if durum.get('kilit_aktif', 0) == 1:
        return jsonify({
            'hata': 'KILIT_AKTIF',
            'mesaj': 'Sebep girilmeden plan goruntulenemez.',
            'redirect': '/uretim-yonetim/kilit-ekrani',
        }), 403
    
    # Tum siparisleri ve darbogazlarini doner
    c = _conn()
    try:
        cur = c.cursor()
        cur.execute("""
            SELECT 
                siparis_no, model_kod, musteri, hedef_toplam,
                atki_yuzde, govde_yuzde, mamul_yuzde,
                ana_darbogaz, alt_darbogaz_proses, kilitlenecek_usta,
                sapma_yuzde, seviye, guncelleme
            FROM siparis_darbogaz
            ORDER BY 
                CASE seviye
                    WHEN 'BUYUK_SAPMA' THEN 1
                    WHEN 'IZLE' THEN 2
                    ELSE 3
                END,
                sapma_yuzde DESC
        """)
        siparisler = [dict(r) for r in cur.fetchall()]
    finally:
        c.close()
    
    return jsonify({
        'kullanici': kullanici,
        'siparis_sayisi': len(siparisler),
        'siparisler': siparisler,
    })


# =====================================================
# ENDPOINT 3: GET /uretim-yonetim/plan-detay/<siparis_no>
# Tek siparisin tum proses detayi
# =====================================================
@uretim_yonetim_bp.route('/plan-detay/<siparis_no>', methods=['GET'])
def plan_detay(siparis_no):
    kullanici = _aktif_kullanici()
    durum = _kilit_durum(kullanici)
    
    # KILIT KORUMA
    if durum.get('kilit_aktif', 0) == 1:
        return jsonify({
            'hata': 'KILIT_AKTIF',
            'mesaj': 'Sebep girilmeden detay goruntulenemez.',
        }), 403
    
    # Darbogaz ozeti
    db_ozet = db_motor.darbogaz_ozet(siparis_no)
    if not db_ozet:
        return jsonify({'hata': f'Siparis {siparis_no} bulunamadi'}), 404
    
    # Tum proses detayi
    prosesler = db_motor.proses_yuzde_hesapla(siparis_no)
    
    return jsonify({
        'siparis_no': siparis_no,
        'ozet': db_ozet,
        'prosesler': prosesler,
    })


# =====================================================
# ENDPOINT 4: POST /uretim-yonetim/sebep
# Sebep gir + kilit kapat
# Body: {sebep_kategori, aciklama}
# =====================================================
@uretim_yonetim_bp.route('/sebep', methods=['POST'])
def sebep_gir():
    kullanici = _aktif_kullanici()
    durum = _kilit_durum(kullanici)
    
    if durum.get('kilit_aktif', 0) != 1:
        return jsonify({
            'hata': 'KILIT_YOK',
            'mesaj': 'Aktif kilit yok, sebep girilemez.',
        }), 400
    
    sapma_olay_id = durum.get('sapma_olay_id')
    if not sapma_olay_id:
        return jsonify({'hata': 'sapma_olay_id bulunamadi'}), 500
    
    # Body al
    data = request.get_json(silent=True) or request.form.to_dict()
    sebep_kategori = (data.get('sebep_kategori') or '').strip()
    aciklama = (data.get('aciklama') or '').strip()
    
    # Validasyon
    GECERLI_SEBEPLER = ['PERSONEL_EKSIK', 'MAKINA_ARIZA', 'ELEKTRIK', 'MALZEME', 'DIGER']
    if sebep_kategori not in GECERLI_SEBEPLER:
        return jsonify({
            'hata': 'GECERSIZ_SEBEP',
            'mesaj': f'Sebep su listeden olmali: {GECERLI_SEBEPLER}',
        }), 400
    
    if len(aciklama) < 5:
        return jsonify({
            'hata': 'ACIKLAMA_KISA',
            'mesaj': 'Aciklama en az 5 karakter olmali.',
        }), 400
    
    # 1. usta_aksiyon kaydi
    c = _conn()
    try:
        cur = c.cursor()
        cur.execute("""
            INSERT INTO usta_aksiyon (
                sapma_olay_id, usta, sebep_kategori, aciklama,
                supheli_flag, sistem_yorumu
            ) VALUES (?, ?, ?, ?, 0, 'Faz 1: dogrulama yapilmadi')
        """, (sapma_olay_id, kullanici, sebep_kategori, aciklama))
        aksiyon_id = cur.lastrowid
        
        # 2. sapma_olay durumunu kapat
        cur.execute("""
            UPDATE sapma_olay 
            SET durum = 'KAPALI', kapanis_zamani = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (sapma_olay_id,))
        
        # 3. Kilit kapat
        cur.execute("""
            UPDATE usta_kilit_durum 
            SET kilit_aktif = 0, sapma_olay_id = NULL, baslangic = NULL
            WHERE kullanici = ?
        """, (kullanici,))
        
        c.commit()
    finally:
        c.close()
    
    return jsonify({
        'durum': 'OK',
        'aksiyon_id': aksiyon_id,
        'mesaj': 'Sebep kaydedildi, kilit acildi.',
        'redirect': '/uretim-yonetim/plan-ekrani',
    })


# =====================================================
# FRONTEND ROUTE'LARI (HTML servis)
# =====================================================
@uretim_yonetim_bp.route('/plan-ekrani', methods=['GET'])
def plan_ekrani():
    return render_template('uretim_yonetim/plan_ekrani.html')


@uretim_yonetim_bp.route('/kilit-ekrani', methods=['GET'])
def kilit_ekrani():
    return render_template('uretim_yonetim/kilit_ekrani.html')