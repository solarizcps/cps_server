# -*- coding: utf-8 -*-
"""
CPS - Online E-Ticaret Routes
===============================
FAZ1-C : Gerçek Trendyol GET verisi.
FAZ2-A : Sipariş Operasyon Listesi — görsel, pagination, filtre, arama.
         Sadece görüntüleme. PUT/POST yok. Korgun yok. Stok yok. DB yok.
"""
import time

from flask import Blueprint, render_template, session, redirect, url_for
from modules.auth import login_gerekli

from modules.online_eticaret.config_store import get_store, is_store_configured, STORE_NAMES
from modules.online_eticaret.trendyol_client import (
    fetch_orders, fetch_product_info, TrendyolError,
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
FETCH_STATUSES = ['Picking', 'Created']
FETCH_DAYS     = 3
SIPARIS_LIMIT  = 25       # KPI kartı altındaki özet tablo limiti

# FAZ0-B korunan (çoklu statü dağılımı FAZ2-B'de yapılacak)
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

# ── HEADERS indeksleri ────────────────────────────────────────────────────
_IDX_MAGAZA  = HEADERS.index('Mağaza')
_IDX_GECIKME = HEADERS.index('Gecikme Durumu')
_IDX_NO      = HEADERS.index('Sipariş No')
_IDX_URUN    = HEADERS.index('Ürün Adı')
_IDX_ADET    = HEADERS.index('Adet')
_IDX_MODEL   = HEADERS.index('Model Kodu')
_IDX_RENK    = HEADERS.index('Renk')
_IDX_BEDEN   = HEADERS.index('Beden')
_IDX_BARKOD  = HEADERS.index('Barkod')
_IDX_KARGO   = HEADERS.index('Kargo Firması')


# ── Servis fonksiyonları ──────────────────────────────────────────────────

def _ms_aralik(gun):
    now_ms   = int(time.time() * 1000)
    start_ms = now_ms - gun * 24 * 60 * 60 * 1000
    return start_ms, now_ms


def _aciliyet(gecikme_str):
    """
    0 = gecikmiş   (GECİKTİ)
    1 = bugün çıkacak  (Kalan: saat bazında — gün yok)
    2 = yakın (Kalan: X gün)
    3 = yeni / belirsiz
    """
    s = str(gecikme_str or '')
    if s.startswith('GECİKTİ'):
        return 0
    if s.startswith('Kalan:'):
        return 1 if 'gün' not in s else 2
    return 3


def _renk_ve_durum(gecikme_str):
    s = str(gecikme_str or '')
    if s.startswith('GECİKTİ'):
        return 'GECİKTİ', '#b91c1c', s
    if s.startswith('Kalan:'):
        return 'TOPLANIYOR', '#b45309', s
    return 'YENI', '#1e3a8a', '—'


def _rows_to_siparis(tum_rows, limit=SIPARIS_LIMIT):
    """Özet KPI tablosu için (üst panel)."""
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


def _build_operasyon_listesi(rows_by_store, image_map_global):
    """
    Tam operasyon listesi (tüm satırlar, görsel URL dahil).
    Template'e JSON olarak gömülür; JS tarafında filtre/arama/pagination yapılır.
    API key/secret bu fonksiyona girmez.
    """
    result = []
    for store_name, rows in rows_by_store.items():
        for row in rows:
            barkod  = str(row[_IDX_BARKOD] or '')
            gecikme = row[_IDX_GECIKME]
            durum, durum_renk, kalan = _renk_ve_durum(gecikme)
            result.append({
                'magaza':     str(row[_IDX_MAGAZA] or ''),
                'aciliyet':   _aciliyet(gecikme),
                'gorsel':     image_map_global.get(barkod, ''),
                'no':         str(row[_IDX_NO]    or ''),
                'urun':       str(row[_IDX_URUN]  or ''),
                'model':      str(row[_IDX_MODEL] or ''),
                'renk_urun':  str(row[_IDX_RENK]  or ''),
                'beden':      str(row[_IDX_BEDEN] or ''),
                'adet':       row[_IDX_ADET]      or 0,
                'barkod':     barkod,
                'kargo':      str(row[_IDX_KARGO] or ''),
                'kalan':      kalan,
                'durum':      durum,
                'durum_renk': durum_renk,
            })
    result.sort(key=lambda x: x['aciliyet'])
    return result


def _cek_magaza(store_name, start_ms, end_ms):
    """
    Döner: (siparisler, model_map, image_map, hata_mesaji_veya_None)
    API key/secret ASLA loglanmaz.
    """
    if not is_store_configured(store_name):
        return [], {}, {}, f"{store_name}: API bilgileri eksik"

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
            return [], {}, {}, f"{store_name} API hatası: {exc}"

    model_map = {}
    image_map = {}
    try:
        info      = fetch_product_info(seller_id, api_key, api_secret)
        model_map = {bc: v['model'] for bc, v in info.items() if v.get('model')}
        image_map = {bc: v['image'] for bc, v in info.items() if v.get('image')}
    except Exception:
        pass   # görsel opsiyonel

    return tum_siparisler, model_map, image_map, None


# ── Route ─────────────────────────────────────────────────────────────────

@online_eticaret_bp.route('/')
@online_eticaret_bp.route('')
@login_gerekli
def index():
    if not session.get('kullanici'):
        return redirect(url_for('auth.login', next='/online-eticaret/'))

    now_ms           = int(time.time() * 1000)
    start_ms, end_ms = _ms_aralik(FETCH_DAYS)
    hatalar          = []
    magaza_orders    = {}
    magaza_maps      = {}
    image_map_global = {}
    rows_by_store    = {}

    for store_name in STORE_NAMES:
        orders, model_map, image_map, hata = _cek_magaza(store_name, start_ms, end_ms)
        if hata:
            hatalar.append(hata)
        else:
            magaza_orders[store_name] = orders
            magaza_maps[store_name]   = model_map
            image_map_global.update(image_map)

    if not magaza_orders:
        return render_template(
            'online_eticaret/index.html',
            api_hata=True,
            hata_mesajlari=hatalar,
            kpi={}, magaza={},
            dagitim=MOCK_DAGITIM, siparisler=[],
            operasyon=MOCK_OPERASYON,
            operasyon_listesi=[],
        )

    kpi          = {'toplam_siparis': 0, 'urun_adedi': 0,
                    'geciken': 0, 'bugun_cikacak': 0,
                    'esleme_eksik': 0, 'paketlenen': 0}
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
        rows_by_store[store_name] = rows
        tum_rows.extend(rows)

    def _siralama_key(row):
        g = str(row[_IDX_GECIKME] or '')
        if g.startswith('GECİKTİ'): return 0
        if g.startswith('Kalan:'):  return 1
        return 2

    tum_rows.sort(key=_siralama_key)
    siparisler        = _rows_to_siparis(tum_rows)
    operasyon_listesi = _build_operasyon_listesi(rows_by_store, image_map_global)

    return render_template(
        'online_eticaret/index.html',
        api_hata=bool(hatalar),
        hata_mesajlari=hatalar,
        kpi=kpi,
        magaza=magaza_stats,
        dagitim=MOCK_DAGITIM,
        siparisler=siparisler,
        operasyon=MOCK_OPERASYON,
        operasyon_listesi=operasyon_listesi,
    )
