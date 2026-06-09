# -*- coding: utf-8 -*-
"""
CPS - Online E-Ticaret Routes
===============================
FAZ0-B: Mock verili operasyon paneli.
FAZ1-A: trendyol_client + excel_export motorları taşındı (import hazır, çağrı yok).
FAZ1-B: config_store hazır — fetch_orders henüz bağlanmadı.
Trendyol API çağrısı yok. Korgun yok. Stok düşme yok. DB yazma yok.
"""
from flask import Blueprint, render_template, session, redirect, url_for

# FAZ1-B: Credential okuyucu — API çağrısı YAPMIYOR, sadece config dosyasını okur.
# Gerçek fetch_orders bağlantısı FAZ1-C'de yapılacak.
from modules.online_eticaret.config_store import get_store, is_store_configured, STORE_NAMES

online_eticaret_bp = Blueprint(
    'online_eticaret',
    __name__,
    url_prefix='/online-eticaret',
)

# FAZ0 MOCK VERİSİ — Gerçek API bağlantısı yapılmadan önce gösterim amaçlı
MOCK_KPI = {
    'toplam_siparis': 325,
    'urun_adedi': 480,
    'geciken': 12,
    'bugun_cikacak': 54,
    'esleme_eksik': 7,
    'paketlenen': 41,
}

MOCK_MAGAZA = {
    'Solariz': {'siparis': 176, 'adet': 268, 'geciken': 8},
    'Epona':   {'siparis': 149, 'adet': 212, 'geciken': 4},
}

MOCK_DAGITIM = [
    {'durum': 'Yeni',            'kod': 'YENI',             'adet': 87,  'renk': '#1e3a8a'},
    {'durum': 'Toplanıyor',      'kod': 'TOPLANIYOR',       'adet': 45,  'renk': '#b45309'},
    {'durum': 'Toplandı',        'kod': 'TOPLANDI',         'adet': 38,  'renk': '#15803d'},
    {'durum': 'Barkod Basıldı',  'kod': 'BARKOD_BASILDI',  'adet': 62,  'renk': '#6d28d9'},
    {'durum': 'Paketlemede',     'kod': 'PAKETLEMEDE',      'adet': 29,  'renk': '#c2410c'},
    {'durum': 'Paketlendi',      'kod': 'PAKETLENDI',       'adet': 41,  'renk': '#0369a1'},
    {'durum': 'Kargoya Teslim',  'kod': 'KARGOYA_TESLIM',  'adet': 23,  'renk': '#15803d'},
    {'durum': 'Stok Fişi Oluştu','kod': 'STOK_FISI_OLUSTU','adet': 17, 'renk': '#0369a1'},
]

MOCK_OPERASYON = {
    'toplayan': 'Mehmet A.',
    'paketleyen': 'Ayşe K.',
    'son_siparis': 'TY50077069',
}

MOCK_SIPARISLER = [
    {'no': 'TY98864789', 'magaza': 'Solariz', 'urun': 'CRF-8240 Beyaz 38',     'adet': 3, 'kalan': '2 saat',   'durum': 'TOPLANIYOR',      'renk': '#b45309'},
    {'no': 'TY98801245', 'magaza': 'Epona',   'urun': 'V-COMFRT Siyah 40',     'adet': 1, 'kalan': '3 saat',   'durum': 'YENI',             'renk': '#1e3a8a'},
    {'no': 'TY50077069', 'magaza': 'Solariz', 'urun': 'Unicorn Terlik Pembe 29','adet': 2, 'kalan': '5 saat',   'durum': 'TOPLANIYOR',      'renk': '#b45309'},
    {'no': 'TY11233448', 'magaza': 'Epona',   'urun': 'KPC-3301 Mavi 37',      'adet': 1, 'kalan': '12 saat',  'durum': 'BARKOD_BASILDI',  'renk': '#6d28d9'},
    {'no': 'TY98800977', 'magaza': 'Solariz', 'urun': 'TRL-992 Turuncu 35',    'adet': 4, 'kalan': '1 gün',    'durum': 'PAKETLENDI',      'renk': '#0369a1'},
    {'no': 'TY66120341', 'magaza': 'Epona',   'urun': 'PRF-7719 Yeşil 42',     'adet': 2, 'kalan': 'GECİKTİ', 'durum': 'HATA',            'renk': '#b91c1c'},
]


@online_eticaret_bp.route('/')
@online_eticaret_bp.route('')
def index():
    if not session.get('kullanici'):
        return redirect(url_for('auth.login', next='/online-eticaret/'))
    return render_template(
        'online_eticaret/index.html',
        kpi=MOCK_KPI,
        magaza=MOCK_MAGAZA,
        dagitim=MOCK_DAGITIM,
        siparisler=MOCK_SIPARISLER,
        operasyon=MOCK_OPERASYON,
    )
