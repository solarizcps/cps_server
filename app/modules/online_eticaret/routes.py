# -*- coding: utf-8 -*-
"""
CPS - Online E-Ticaret Routes
===============================
FAZ0-B : Mock verili operasyon paneli.
FAZ1-A : trendyol_client + excel_export motorları taşındı.
FAZ1-B : config_store credential okuma hazırlandı.
FAZ1-C : Gerçek Trendyol GET verisi — sadece okuma, yazma YOK.
         Trendyol API: sadece GET. PUT/POST yok. Korgun yok.
         Stok düşme yok. DB yazma yok. Barkod yazdırma yok.
"""
import time

from flask import Blueprint, render_template, session, redirect, url_for

from modules.online_eticaret.config_store import get_store, is_store_configured, STORE_NAMES
from modules.online_eticaret.trendyol_client import (
    fetch_orders, fetch_product_model_map, TrendyolError,
)
from modules.online_eticaret.excel_export import (
    dashboard_stats, orders_to_rows, HEADERS,
)

online_eticaret_bp = Blueprint(
    'online_eticaret',
    __name__,
    url_prefix='/online-eticaret',
)

# ── Sabitler ──────────────────────────────────────────────────────────────
FETCH_STATUSES = ['Picking', 'Created']   # Sadece GET — durum değiştirme yok
FETCH_DAYS     = 3                         # Son 3 gün
SIPARIS_LIMIT  = 25                        # Tabloda gösterilecek max satır

# FAZ0-B'den korunan — çoklu statü dağılımı FAZ2'ye bırakıldı
MOCK_DAGITIM = [
    {'durum': 'Yeni',              'kod': 'YENI',             'adet': 0, 'renk': '#1e3a8a'},
    {'durum': 'Toplanıyor',        'kod': 'TOPLANIYOR',       'adet': 0, 'renk': '#b45309'},
    {'durum': 'Toplandı',          'kod': 'TOPLANDI',         'adet': 0, 'renk': '#15803d'},
    {'durum': 'Barkod Basıldı',    'kod': 'BARKOD_BASILDI',  'adet': 0, 'renk': '#6d28d9'},
    {'durum': 'Paketlemede',       'kod': 'PAKETLEMEDE',      'adet': 0, 'renk': '#c2410c'},
    {'durum': 'Paketlendi',        'kod': 'PAKETLENDI',       'adet': 0, 'renk': '#0369a1'},
    {'durum': 'Kargoya Teslim',    'kod': 'KARGOYA_TESLIM',  'adet': 0, 'renk': '#15803d'},
    {'durum': 'Stok Fişi Oluştu',  'kod': 'STOK_FISI_OLUSTU','adet': 0, 'renk': '#0369a1'},
]

MOCK_OPERASYON = {
    'toplayan':    '—',
    'paketleyen':  '—',
    'son_siparis': '—',
}

# ── Yardımcı indeksler (modül yüklenince hesapla) ─────────────────────────
_IDX_MAGAZA  = HEADERS.index('Mağaza')
_IDX_GECIKME = HEADERS.index('Gecikme Durumu')
_IDX_NO      = HEADERS.index('Sipariş No')
_IDX_URUN    = HEADERS.index('Ürün Adı')
_IDX_ADET    = HEADERS.index('Adet')


# ── Servis katmanı ────────────────────────────────────────────────────────

def _ms_aralik(gun):
    """Son N günün milisaniye epoch aralığını döndürür."""
    now_ms   = int(time.time() * 1000)
    start_ms = now_ms - gun * 24 * 60 * 60 * 1000
    return start_ms, now_ms


def _renk_ve_durum(gecikme_str):
    """
    Gecikme metninden (orders_to_rows çıktısı) template için
    (durum_kodu, renk_hex, kalan_metin) üçlüsü üretir.
    """
    s = str(gecikme_str or '')
    if s.startswith('GECİKTİ'):
        return 'GECİKTİ', '#b91c1c', s
    if s.startswith('Kalan:'):
        return 'TOPLANIYOR', '#b45309', s
    return 'YENI', '#1e3a8a', '—'


def _rows_to_siparis(tum_rows, limit=SIPARIS_LIMIT):
    """
    orders_to_rows() listesini template dict'lerine çevirir.
    API key/secret bu fonksiyona hiç girmez.
    """
    result = []
    for row in tum_rows[:limit]:
        durum, renk, kalan = _renk_ve_durum(row[_IDX_GECIKME])
        result.append({
            'no':     str(row[_IDX_NO]    or ''),
            'magaza': str(row[_IDX_MAGAZA] or ''),
            'urun':   str(row[_IDX_URUN]   or ''),
            'adet':   row[_IDX_ADET]       or 0,
            'kalan':  kalan,
            'durum':  durum,
            'renk':   renk,
        })
    return result


def _cek_magaza(store_name, start_ms, end_ms):
    """
    Bir mağazanın FETCH_STATUSES siparişlerini çeker.
    Döner: (siparisler, model_map, hata_mesaji_veya_None)
    API key/secret ASLA loglanmaz; hata mesajlarına eklenmez.
    """
    if not is_store_configured(store_name):
        return [], {}, f"{store_name}: API bilgileri eksik"

    cfg        = get_store(store_name)
    seller_id  = cfg['sellerId']
    api_key    = cfg['apiKey']
    api_secret = cfg['apiSecret']

    tum_siparisler = []
    for status in FETCH_STATUSES:
        try:
            orders = fetch_orders(
                seller_id, api_key, api_secret,
                status, start_ms, end_ms,
            )
            tum_siparisler.extend(orders)
        except TrendyolError as exc:
            return [], {}, f"{store_name} API hatası: {exc}"

    try:
        model_map = fetch_product_model_map(seller_id, api_key, api_secret)
    except Exception:
        model_map = {}   # model haritası opsiyonel — yoksa ad'dan tahmin edilir

    return tum_siparisler, model_map, None


# ── Route ─────────────────────────────────────────────────────────────────

@online_eticaret_bp.route('/')
@online_eticaret_bp.route('')
def index():
    if not session.get('kullanici'):
        return redirect(url_for('auth.login', next='/online-eticaret/'))

    now_ms               = int(time.time() * 1000)
    start_ms, end_ms     = _ms_aralik(FETCH_DAYS)
    hatalar              = []
    magaza_orders        = {}
    magaza_maps          = {}

    # Her mağaza için bağımsız çek — bir mağaza hata verse diğeri çalışmaya devam eder
    for store_name in STORE_NAMES:
        orders, model_map, hata = _cek_magaza(store_name, start_ms, end_ms)
        if hata:
            hatalar.append(hata)
        else:
            magaza_orders[store_name] = orders
            magaza_maps[store_name]   = model_map

    # Tüm mağazalar başarısız → hata ekranı
    if not magaza_orders:
        return render_template(
            'online_eticaret/index.html',
            api_hata=True,
            hata_mesajlari=hatalar,
            kpi={}, magaza={},
            dagitim=MOCK_DAGITIM, siparisler=[],
            operasyon=MOCK_OPERASYON,
        )

    # KPI ve per-mağaza istatistikleri
    kpi = {
        'toplam_siparis': 0, 'urun_adedi': 0,
        'geciken': 0, 'bugun_cikacak': 0,
        'esleme_eksik': 0, 'paketlenen': 0,
    }
    magaza_stats = {}
    tum_rows     = []

    for store_name, orders in magaza_orders.items():
        mmap  = magaza_maps.get(store_name, {})
        stats = dashboard_stats(orders, mmap, now_ms)
        rows  = orders_to_rows(orders, store_name, mmap, now_ms)

        kpi['toplam_siparis'] += stats['total_orders']
        kpi['urun_adedi']     += stats['total_lines']
        kpi['geciken']        += stats['delayed_orders']
        kpi['bugun_cikacak']  += stats['urgent']

        magaza_stats[store_name] = {
            'siparis': stats['total_orders'],
            'adet':    stats['total_qty'],
            'geciken': stats['delayed_orders'],
        }
        tum_rows.extend(rows)

    # Aciliyet sırası: gecikmiş → kalan var → tarihsiz
    def _siralama_key(row):
        g = str(row[_IDX_GECIKME] or '')
        if g.startswith('GECİKTİ'): return 0
        if g.startswith('Kalan:'):  return 1
        return 2

    tum_rows.sort(key=_siralama_key)
    siparisler = _rows_to_siparis(tum_rows)

    return render_template(
        'online_eticaret/index.html',
        api_hata=bool(hatalar),
        hata_mesajlari=hatalar,
        kpi=kpi,
        magaza=magaza_stats,
        dagitim=MOCK_DAGITIM,
        siparisler=siparisler,
        operasyon=MOCK_OPERASYON,
    )
