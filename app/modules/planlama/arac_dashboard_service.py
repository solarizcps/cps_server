# -*- coding: utf-8 -*-
"""Araç Takip & Plan — mock dashboard DTO (V1.1). data_source=mock."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

_TR_AY = (
    '', 'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran',
    'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık',
)
_TR_GUN = ('Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar')

PRIORITY_LABEL = {
    'DUSUK': 'Düşük', 'NORMAL': 'Normal', 'YUKSEK': 'Yüksek', 'ACIL': 'Acil',
}
STATUS_LABEL = {
    'BEKLIYOR': 'Bekliyor', 'PLANLANDI': 'Planlandı', 'YOLDA': 'Yolda',
    'TAMAMLANDI': 'Tamamlandı', 'GIDILMEDI': 'Gidilmedi', 'IPTAL': 'İptal',
    'BASLANGIC': 'Başlangıç',
}


def _date_label(d: date) -> str:
    return f'{d.day} {_TR_AY[d.month]} {d.year} {_TR_GUN[d.weekday()]}'


def _build_plan_map_dto(tasks: List[dict], base_row: dict | None) -> dict:
    from modules.planlama.arac_location_resolver import resolve_base_location

    base = resolve_base_location(base_row)
    stops = []
    for t in sorted(tasks, key=lambda x: x.get('order_no') or 0):
        stops.append({
            'id': t.get('id'),
            'plan_item_id': t.get('plan_item_id'),
            'is_talebi_id': t.get('is_talebi_id'),
            'order_no': t.get('order_no'),
            'company_name': t.get('company_name'),
            'job_title': t.get('job_title'),
            'planned_time': t.get('planned_time'),
            'address_text': t.get('address_text'),
            'priority_label': t.get('priority_label'),
            'latitude': t.get('latitude'),
            'longitude': t.get('longitude'),
            'location_status': t.get('location_status'),
            'location_source': t.get('location_source'),
            'location_source_label': t.get('location_source_label'),
            'has_coordinates': bool(t.get('has_coordinates')),
            'kayitli_yer_id': t.get('kayitli_yer_id'),
        })
    ready = sum(1 for s in stops if s['has_coordinates'])
    missing = len(stops) - ready
    return {
        'base': base,
        'stops': stops,
        'completeness': {
            'total_stops': len(stops),
            'ready': ready,
            'missing': missing,
            'base_configured': base.get('has_coordinates', False),
        },
    }


def _default_tasks() -> List[dict]:
    return [
        {
            'id': 't1', 'order_no': 1, 'planned_time': '08:30',
            'job_title': 'Anıl Torna', 'company_name': 'Anıl Torna',
            'address_text': 'Pendik, İstanbul', 'priority': 'YUKSEK',
            'priority_label': 'Yüksek', 'distance_km': 0, 'status': 'BASLANGIC',
            'status_label': 'Başlangıç', 'phone': '', 'location_url': '',
            'latitude': 40.876, 'longitude': 29.234,
        },
        {
            'id': 't2', 'order_no': 2, 'planned_time': '09:15',
            'job_title': 'Ziyaret', 'company_name': 'A Firması',
            'address_text': 'Tuzla OSB Mah.', 'priority': 'YUKSEK',
            'priority_label': 'Yüksek', 'distance_km': 18, 'status': 'BEKLIYOR',
            'status_label': 'Bekliyor', 'phone': '0532 111 2233',
            'location_url': 'https://maps.google.com/?q=Tuzla+OSB',
            'latitude': 40.818, 'longitude': 29.305,
        },
        {
            'id': 't3', 'order_no': 3, 'planned_time': '10:45',
            'job_title': 'Ziyaret', 'company_name': 'B Lojistik',
            'address_text': 'Çayırova Mah.', 'priority': 'NORMAL',
            'priority_label': 'Normal', 'distance_km': 22, 'status': 'BEKLIYOR',
            'status_label': 'Bekliyor', 'phone': '0533 222 3344',
            'location_url': 'https://maps.google.com/?q=Cayirova',
            'latitude': 40.824, 'longitude': 29.372,
        },
        {
            'id': 't4', 'order_no': 4, 'planned_time': '12:30',
            'job_title': 'Ziyaret', 'company_name': 'C Otomotiv',
            'address_text': 'Gebze OSB', 'priority': 'YUKSEK',
            'priority_label': 'Yüksek', 'distance_km': 15, 'status': 'BEKLIYOR',
            'status_label': 'Bekliyor', 'phone': '0534 333 4455',
            'location_url': 'https://maps.google.com/?q=Gebze+OSB',
            'latitude': 40.802, 'longitude': 29.430,
        },
        {
            'id': 't5', 'order_no': 5, 'planned_time': '14:00',
            'job_title': 'Ziyaret', 'company_name': 'D Metal Sanayi',
            'address_text': 'Dilovası OSB', 'priority': 'NORMAL',
            'priority_label': 'Normal', 'distance_km': 19, 'status': 'BEKLIYOR',
            'status_label': 'Bekliyor', 'phone': '0535 444 5566',
            'location_url': 'https://maps.google.com/?q=Dilovasi+OSB',
            'latitude': 40.785, 'longitude': 29.512,
        },
        {
            'id': 't6', 'order_no': 6, 'planned_time': '15:30',
            'job_title': 'Ziyaret', 'company_name': 'E Teknik',
            'address_text': 'Darıca Mah.', 'priority': 'DUSUK',
            'priority_label': 'Düşük', 'distance_km': 12, 'status': 'BEKLIYOR',
            'status_label': 'Bekliyor', 'phone': '0536 555 6677',
            'location_url': 'https://maps.google.com/?q=Darıca',
            'latitude': 40.769, 'longitude': 29.385,
        },
        {
            'id': 't7', 'order_no': 7, 'planned_time': '17:30',
            'job_title': 'Fabrika (Dönüş)', 'company_name': 'Solariz Fabrika',
            'address_text': 'Pendik, İstanbul', 'priority': 'NORMAL',
            'priority_label': '—', 'distance_km': 26, 'status': 'PLANLANDI',
            'status_label': 'Planlandı', 'phone': '', 'location_url': '',
            'latitude': 40.876, 'longitude': 29.234,
        },
    ]


def _default_vehicles() -> List[dict]:
    return [
        {'id': 'v1', 'plaka': '34 ABC 123', 'sofor': 'Ahmet Yılmaz', 'speed_kmh': 48,
         'status': 'HAREKETLI', 'status_label': 'Hareketli', 'kontak': 'Açık',
         'last_location': 'Tuzla', 'last_seen_at': '09:12', 'total_km': 1420,
         'latitude': 40.818, 'longitude': 29.305},
        {'id': 'v2', 'plaka': '34 DEF 456', 'sofor': 'Mehmet Arslan', 'speed_kmh': 62,
         'status': 'HAREKETLI', 'status_label': 'Hareketli', 'kontak': 'Açık',
         'last_location': 'Gebze', 'last_seen_at': '09:10', 'total_km': 980,
         'latitude': 40.802, 'longitude': 29.430},
        {'id': 'v3', 'plaka': '34 GHI 789', 'sofor': 'Ali Demir', 'speed_kmh': 32,
         'status': 'ROLANTI', 'status_label': 'Duruyor', 'kontak': 'Açık',
         'last_location': 'Çayırova', 'last_seen_at': '09:08', 'total_km': 756,
         'latitude': 40.824, 'longitude': 29.372},
        {'id': 'v4', 'plaka': '34 JKL 012', 'sofor': 'Hasan Yıldız', 'speed_kmh': 0,
         'status': 'DURAN', 'status_label': 'Duran', 'kontak': 'Kapalı',
         'last_location': 'Pendik', 'last_seen_at': '08:45', 'total_km': 1102,
         'latitude': 40.876, 'longitude': 29.234},
        {'id': 'v5', 'plaka': '34 MNO 345', 'sofor': 'Burak Kılıç', 'speed_kmh': 0,
         'status': 'PASIF', 'status_label': 'Pasif', 'kontak': 'Kapalı',
         'last_location': '—', 'last_seen_at': '—', 'total_km': 640,
         'latitude': None, 'longitude': None},
    ]


def _weekly_summary(ref: date) -> List[dict]:
    mon = ref - timedelta(days=ref.weekday())
    samples = [
        (12, 3, 186), (16, 4, 284), (14, 3, 245), (18, 4, 312),
        (11, 2, 198), (6, 1, 92), (0, 0, 0),
    ]
    out = []
    for i, (jobs, veh, km) in enumerate(samples):
        d = mon + timedelta(days=i)
        out.append({
            'day_key': d.isoformat(),
            'label': _TR_GUN[i][:3],
            'date_label': f'{d.day} {_TR_AY[d.month]}',
            'task_count': jobs, 'vehicle_count': veh, 'total_km': km,
            'completed': max(0, jobs - 4) if jobs else 0,
        })
    return out


def _history_rows() -> List[dict]:
    return [
        {
            'date': '2026-08-20', 'vehicle': '34 ABC 123', 'driver': 'Ahmet Yılmaz',
            'total_jobs': 7, 'completed': 6, 'total_km': 112, 'planned_km': 108,
            'km_diff': 4, 'status': 'TAMAMLANDI', 'status_label': 'Tamamlandı',
        },
        {
            'date': '2026-08-19', 'vehicle': '34 DEF 456', 'driver': 'Mehmet Arslan',
            'total_jobs': 5, 'completed': 5, 'total_km': 84, 'planned_km': 90,
            'km_diff': -6, 'status': 'TAMAMLANDI', 'status_label': 'Tamamlandı',
        },
        {
            'date': '2026-08-18', 'vehicle': '34 GHI 789', 'driver': 'Ali Demir',
            'total_jobs': 6, 'completed': 4, 'total_km': 98, 'planned_km': 95,
            'km_diff': 3, 'status': 'KISMI', 'status_label': 'Kısmi',
        },
    ]


def get_arac_dashboard_dto(
    plan_date: Optional[date] = None,
    active_tab: str = 'gunluk',
    vehicle_id: Optional[str] = None,
    driver_id: Optional[str] = None,
    daily_tasks: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """Dashboard DTO — V1.3 canonical when DB tables exist."""
    from modules.planlama.arac_request_user_service import search_cps_users
    from modules.planlama.arac_takip_repo import list_bekleyen_talepler, tables_ready

    d = plan_date or date.today()
    canonical = tables_ready()
    tasks = daily_tasks if daily_tasks is not None else ([] if canonical else _default_tasks())
    base_row = None
    if canonical:
        from modules.planlama.arac_operasyon_ayar_repo import get_active_base, operasyon_ayar_ready
        if operasyon_ayar_ready():
            base_row = get_active_base()
    plan_map = _build_plan_map_dto(tasks, base_row) if canonical else {
        'base': {'configured': False, 'has_coordinates': False},
        'stops': [],
        'completeness': {'total_stops': 0, 'ready': 0, 'missing': 0, 'base_configured': False},
    }
    drivers_raw = search_cps_users('', limit=40) if canonical else []
    drivers = [
        {'id': str(u['id']), 'ad': u['display_name']}
        for u in drivers_raw
    ] if drivers_raw else [
        {'id': 'd1', 'ad': 'Ahmet Yılmaz'},
        {'id': 'd2', 'ad': 'Mehmet Arslan'},
        {'id': 'd3', 'ad': 'Ali Demir'},
        {'id': 'd4', 'ad': 'Hasan Yıldız'},
    ]
    sel_vehicle = vehicle_id or ''
    sel_driver = driver_id or (drivers[0]['id'] if drivers else '')
    v_plate = '—'
    v_sofor = next((x['ad'] for x in drivers if str(x['id']) == str(sel_driver)), '—')
    total_km_plan = 0 if canonical else sum(t.get('distance_km') or 0 for t in tasks)
    bekleyen = list_bekleyen_talepler() if canonical else []
    tamamlanan = sum(1 for t in tasks if t.get('status') == 'TAMAMLANDI')
    return {
        'data_source': 'canonical' if canonical else 'mock',
        'date': d.isoformat(),
        'date_label': _date_label(d),
        'active_tab': active_tab,
        'selected_vehicle_id': sel_vehicle,
        'selected_driver_id': sel_driver,
        'selected_plate': v_plate,
        'selected_driver_name': v_sofor,
        'kpi': {
            'aktif_arac': None,
            'aktif_arac_toplam': None,
            'hareket_halinde': None,
            'hareket_pct': None,
            'toplam_km_bugun': total_km_plan if not canonical else None,
            'toplam_km_label': '—' if canonical else '284 km',
            'toplam_is': len(tasks),
            'tamamlanan': tamamlanan,
            'tamamlanan_pct': round(100 * tamamlanan / len(tasks), 1) if tasks else 0,
            'yakit_l': None if canonical else 28.6,
            'yakit_label': '—' if canonical else '28.6 L',
        },
        'vehicles': [],
        'drivers': drivers,
        'daily_tasks': tasks,
        'bekleyen_talepler': bekleyen,
        'bekleyen_count': len(bekleyen),
        'daily_totals': {
            'distance_km': '—' if canonical else total_km_plan,
            'duration_label': '—' if canonical else '3s 10dk',
        },
        'weekly_summary': _weekly_summary(d),
        'history_rows': _history_rows(),
        'activities': [
            {'activity_type': 'plan', 'message': 'A Firması ziyareti planlandı.', 'created_at': '09:17'},
        ] if not canonical else [],
        'route_analysis': {
            'current': {'km': '—', 'duration_label': '—'},
            'recommended': {'km': '—', 'duration_label': '—'},
            'gain': {'km': '—', 'pct': '—'},
            'fuel_saving': {'liters': '—', 'try_amount': '—'},
        } if canonical else {
            'current': {'km': 112, 'duration_label': '3s 10dk'},
            'recommended': {'km': 84, 'duration_label': '2s 35dk'},
            'gain': {'km': 28, 'pct': 25},
            'fuel_saving': {'liters': 4.2, 'try_amount': 60.5},
        },
        'map_pins': [
            {'order': t.get('order_no'), 'lat': t.get('latitude'), 'lng': t.get('longitude'), 'label': t.get('company_name')}
            for t in tasks if t.get('has_coordinates')
        ],
        'plan_map': plan_map,
        'base_location': plan_map.get('base'),
        'location_completeness': plan_map.get('completeness'),
        'meta': {
            'planned_km': total_km_plan if not canonical else None,
            'actual_km': None,
            'planned_duration_min': None if canonical else 190,
            'actual_duration_min': None,
            'generated_at': datetime.now().isoformat(timespec='seconds'),
        },
    }
