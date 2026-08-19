# -*- coding: utf-8 -*-
"""Planlama — Enjeksiyon kapasite / tahmini bitiş motoru (READ-ONLY ENJ verisi).

Vardiya saatleri forensic kaynak: enjeksiyon routes.SAATLER / VARDIYA_METIN
  gunduz 07:00–17:00 (10 saat)
  gece   17:00–07:00 (+1 gün, 14 saat)
Pişme süresi kapasite formülüne girmez; geçmiş gerçek tur referansı kullanılır.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from modules.planlama.enj_kapasite_read_service import _speed_references

# Forensic: app/modules/enjeksiyon/routes.py SAATLER — dokunulmadan kopyalandı
VARDIYA_SAAT = {
    'gunduz': {'bas': 7, 'bit': 17, 'sure_saat': 10},
    'gece': {'bas': 17, 'bit': 7, 'sure_saat': 14},
}

CALISMA_MODLARI = frozenset({'GUNDUZ', 'GECE', 'GUNDUZ_GECE'})
HAFTA_SONU = frozenset({'HAYIR', 'EVET'})
HS_VARDIYA = frozenset({'GUNDUZ', 'GECE', 'GUNDUZ_GECE'})
CONFIDENCE_ORDER = {'YUKSEK': 3, 'ORTA': 2, 'DUSUK': 1, 'YETERSIZ': 0}
# Kural A (LOCK): Cuma gece 17:00 → Cmt 07:00 kesintisiz; Cmt 07:00 sonrasi yeni vardiya yok
HAFTA_SONU_KURAL = 'A'


def _spread_metrics(min_tur: int | float, max_tur: int | float, median_tur: float) -> dict:
    spread_abs = float(max_tur) - float(min_tur)
    if median_tur and median_tur > 0:
        spread_ratio = spread_abs / float(median_tur)
    elif spread_abs > 0:
        spread_ratio = None
    else:
        spread_ratio = 0.0
    return {
        'spread_abs': round(spread_abs, 2),
        'spread_ratio': round(spread_ratio, 4) if spread_ratio is not None else None,
    }


def _confidence_from_samples(
    sample_count: int,
    min_tur: int | float,
    max_tur: int | float,
    median_tur: float,
    *,
    is_fallback: bool = False,
) -> str:
    """Gercek veri yayilimina gore guven — n=2 asla YUKSEK degil."""
    n = int(sample_count or 0)
    if n <= 0:
        return 'YETERSIZ'
    spread = _spread_metrics(min_tur, max_tur, median_tur)
    ratio = spread.get('spread_ratio')
    if is_fallback or n < 3:
        return 'DUSUK'
    if n <= 5:
        if ratio is not None and ratio > 1.0:
            return 'DUSUK'
        return 'ORTA'
    # n >= 6
    if ratio is not None and ratio > 0.5:
        return 'ORTA'
    if float(min_tur) > 0 and float(max_tur) / float(min_tur) > 2.0:
        return 'ORTA'
    return 'YUKSEK'


def _worst_confidence(*levels: str) -> str:
    valid = [c for c in levels if c in CONFIDENCE_ORDER]
    if not valid:
        return 'YETERSIZ'
    return min(valid, key=lambda c: CONFIDENCE_ORDER[c])


def _ui_precision(confidence: str) -> str:
    return {
        'YUKSEK': 'saat_dakika',
        'ORTA': 'yaklasik_saat',
        'DUSUK': 'yaklasik_gun_vardiya',
        'YETERSIZ': 'belirsiz',
    }.get(confidence, 'belirsiz')


def _format_tahmini_gosterim(
    end_dt: datetime,
    confidence: str,
    breakdown: list[dict],
) -> str:
    if confidence == 'YUKSEK':
        return end_dt.strftime('%Y-%m-%d %H:%M')
    if confidence == 'ORTA':
        rounded = end_dt.replace(minute=0, second=0, microsecond=0)
        if end_dt.minute >= 30:
            rounded += timedelta(hours=1)
        return rounded.strftime('%Y-%m-%d %H:00') + ' (yaklasik)'
    if breakdown:
        last = breakdown[-1]
        if last.get('tarih') and last.get('vardiya'):
            return f"{last['tarih']} {last['vardiya']} (yaklasik vardiya)"
    return end_dt.strftime('%Y-%m-%d') + ' (yaklasik)'


def _parse_dt(val: str | datetime) -> datetime:
    if isinstance(val, datetime):
        return val.replace(second=0, microsecond=0)
    s = (val or '').strip().replace('T', ' ')
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(s[:19] if fmt.endswith('%S') else s[:16], fmt)
        except ValueError:
            continue
    raise ValueError('Gecersiz datetime: %s' % val)


def _vardiya_for_dt(dt: datetime) -> str:
    h = dt.hour
    return 'gunduz' if 7 <= h < 17 else 'gece'


def _shift_window(dt: datetime, vardiya: str) -> tuple[datetime, datetime]:
    d = dt.date()
    if vardiya == 'gunduz':
        bas = datetime(d.year, d.month, d.day, 7, 0)
        bit = datetime(d.year, d.month, d.day, 17, 0)
        return bas, bit
    if dt.hour >= 17:
        bas = datetime(d.year, d.month, d.day, 17, 0)
        bit = bas + timedelta(hours=14)
    else:
        bit = datetime(d.year, d.month, d.day, 7, 0)
        bas = bit - timedelta(hours=14)
    return bas, bit


def _mode_allows_vardiya(
    calisma_modu: str,
    vardiya: str,
    hafta_sonu_calisma: str,
    hafta_sonu_vardiya: str | None,
    win_bas: datetime,
) -> bool:
    """Kural A: vardiya BASLANGIC gunune gore hafta sonu karari."""
    wd = win_bas.weekday()
    if hafta_sonu_calisma != 'EVET':
        if wd >= 5:
            return False
        mod = calisma_modu
    else:
        mod = hafta_sonu_vardiya or 'GUNDUZ_GECE' if wd >= 5 else calisma_modu
    if mod == 'GUNDUZ_GECE':
        return True
    if mod == 'GUNDUZ':
        return vardiya == 'gunduz'
    if mod == 'GECE':
        return vardiya == 'gece'
    return False


def _lookup_reference(
    references: list[dict],
    slot: str,
    vardiya: str,
    aktif_goz_sayisi: int,
) -> dict:
    slot = slot.upper()
    requested_ag = int(aktif_goz_sayisi)
    ref_type_expected = (
        'median_normalize_tur_10h' if vardiya == 'gunduz'
        else 'median_normalize_tur_14h'
    )

    def _pack(r: dict, *, exact: bool, fallback: bool, fb_reason: str | None = None) -> dict:
        med = float(r['median_normalize_tur'])
        n = int(r['sample_count'])
        is_low_tier = r.get('used_quality_tier') in ('LOW', 'PRIMARY_MIXED')
        only_primary = int(r.get('primary_sample_count') or 0)
        conf = _confidence_from_samples(
            n, r['min_tur'], r['max_tur'], med,
            is_fallback=fallback or (is_low_tier and only_primary < 2),
        )
        spread = _spread_metrics(r['min_tur'], r['max_tur'], med)
        out = {
            'reference_type': r.get('reference_type') or ref_type_expected,
            'reference_value': med,
            'sample_count': n,
            'primary_sample_count': int(r.get('primary_sample_count') or 0),
            'low_quality_sample_count': int(r.get('low_quality_sample_count') or 0),
            'excluded_low_quality_count': int(r.get('excluded_low_quality_count') or 0),
            'used_quality_tier': r.get('used_quality_tier'),
            'confidence': conf,
            'reference_exact': exact,
            'fallback': fallback,
            'requested_ag': requested_ag,
            'fallback_from_ag': None,
            'avg_tur_vardiya': r.get('avg_tur_vardiya'),
            'median_tur_vardiya': med,
            'median_normalize_tur': med,
            'median_raw_tur_vardiya': r.get('median_raw_tur_vardiya'),
            'min_tur': r.get('min_tur'),
            'max_tur': r.get('max_tur'),
            'spread_abs': spread['spread_abs'],
            'spread_ratio': spread['spread_ratio'],
            'avg_tur_saat': r.get('avg_tur_saat'),
            'median_tur_saat': r.get('median_tur_saat'),
            'aktif_goz_sayisi': requested_ag if exact else int(r.get('aktif_goz_sayisi') or 0),
            'vardiya': vardiya,
            'reference_label': (
                f"≈ {round(med)} tur / {vardiya} vardiyası"
            ),
        }
        if fb_reason:
            out['fallback_reason'] = fb_reason
        if is_low_tier:
            out['quality_warning'] = 'Yalnizca dusuk kalite sample (aktif saat < esik)'
        return out

    exact = [
        r for r in references
        if r.get('slot') == slot and r.get('vardiya') == vardiya
        and int(r.get('aktif_goz_sayisi') or 0) == requested_ag
        and int(r.get('sample_count') or 0) > 0
    ]
    if exact:
        return _pack(exact[0], exact=True, fallback=False)

    near = [
        r for r in references
        if r.get('slot') == slot and r.get('vardiya') == vardiya
        and int(r.get('sample_count') or 0) > 0
    ]
    if near:
        near.sort(key=lambda x: abs(int(x.get('aktif_goz_sayisi') or 0) - requested_ag))
        r = near[0]
        fb_ag = int(r.get('aktif_goz_sayisi') or 0)
        packed = _pack(r, exact=False, fallback=True, fb_reason='aktif_goz_eslesmedi')
        packed['fallback_from_ag'] = fb_ag
        packed['aktif_goz_sayisi'] = fb_ag
        return packed

    return {
        'reference_type': None,
        'reference_value': None,
        'sample_count': 0,
        'primary_sample_count': 0,
        'confidence': 'YETERSIZ',
        'reference_exact': False,
        'fallback': False,
        'requested_ag': requested_ag,
        'fallback_from_ag': None,
        'vardiya': vardiya,
    }


def _build_warnings(ref_gunduz: dict, ref_gece: dict, calisma_modu: str) -> list[dict]:
    warnings: list[dict] = []
    used = []
    if calisma_modu in ('GUNDUZ', 'GUNDUZ_GECE'):
        used.append(('gunduz', ref_gunduz))
    if calisma_modu in ('GECE', 'GUNDUZ_GECE'):
        used.append(('gece', ref_gece))
    for vd, ref in used:
        if ref.get('fallback'):
            warnings.append({
                'kod': 'FALLBACK_REFERANS',
                'seviye': 'UYARI',
                'mesaj': (
                    f'{vd.upper()} referans exact degil — '
                    f'{ref.get("requested_ag")} aktif goz yerine '
                    f'{ref.get("fallback_from_ag")} aktif goz gecmisinden (yaklasik)'
                ),
                'requested_ag': ref.get('requested_ag'),
                'fallback_from_ag': ref.get('fallback_from_ag'),
            })
        if ref.get('used_quality_tier') == 'LOW':
            warnings.append({
                'kod': 'DUSUK_KALITE_REFERANS',
                'seviye': 'UYARI',
                'mesaj': (
                    f'{vd.upper()} referans dusuk kalite sample — '
                    f'aktif uretim saati esiginin altinda (n={ref.get("sample_count")})'
                ),
            })
        elif int(ref.get('excluded_low_quality_count') or 0) > 0:
            warnings.append({
                'kod': 'DUSUK_KALITE_HARIC',
                'seviye': 'BILGI',
                'mesaj': (
                    f'{vd.upper()} referans: {ref.get("excluded_low_quality_count")} dusuk kalite '
                    f'sample haric tutuldu (primary n={ref.get("primary_sample_count")})'
                ),
            })
        conf = ref.get('confidence')
        if conf == 'DUSUK':
            warnings.append({
                'kod': 'DUSUK_CONFIDENCE',
                'seviye': 'UYARI',
                'mesaj': (
                    f'{vd.upper()} referans dusuk guven (n={ref.get("sample_count")}, '
                    f'spread={ref.get("spread_ratio")}) — bitis tahmini yaklasik'
                ),
                'confidence': conf,
                'sample_count': ref.get('sample_count'),
                'spread_ratio': ref.get('spread_ratio'),
            })
        elif conf == 'ORTA':
            warnings.append({
                'kod': 'ORTA_CONFIDENCE',
                'seviye': 'BILGI',
                'mesaj': f'{vd.upper()} referans orta guven — bitis saati yaklasik gosterilmeli',
                'confidence': conf,
            })
    return warnings


def _hafta_sonu_gece_kapasite_saat(
    win_bas: datetime,
    win_bit: datetime,
    kural: str,
    hafta_sonu: str,
) -> float:
    """Kural A: vardiya basladigi gune gore tam pencere.
    Kural B: takvim saatine gore hafta sonu 00:00 sonrasi dur."""
    if hafta_sonu != 'HAYIR' or kural == 'A':
        return max(0.0, (win_bit - win_bas).total_seconds() / 3600)
    # Kural B — cumartesi/pazar 00:00 sonrasi uretim yok
    cur = win_bas
    total = 0.0
    while cur < win_bit:
        if cur.weekday() >= 5:
            # hafta sonu gunune gecildi — dur
            break
        # bir sonraki gece yarısına veya vardiya bitisine kadar
        next_midnight = datetime(cur.year, cur.month, cur.day) + timedelta(days=1)
        if cur.weekday() == 4:
            # Cuma gece → Cmt 00:00'da kes
            segment_end = min(win_bit, next_midnight)
        else:
            segment_end = min(win_bit, next_midnight)
            if segment_end.weekday() >= 5:
                segment_end = min(segment_end, next_midnight)
        if segment_end <= cur:
            break
        total += (segment_end - cur).total_seconds() / 3600
        cur = segment_end
        if cur.weekday() >= 5:
            break
    return total


def _hafta_sonu_gece_sinir_analizi(
    plan_bas: datetime,
    gerekli_tur: int,
    ref_gece: dict,
    hafta_sonu: str,
) -> dict | None:
    """Cuma 17:00 gece baslangici — iki kural karsilastirmasi (secim yapilmaz)."""
    if plan_bas.weekday() != 4 or plan_bas.hour < 17:
        return None
    if hafta_sonu != 'HAYIR':
        return None
    ref_tur = float(ref_gece.get('reference_value') or 0)
    if ref_tur <= 0:
        return None

    win_bas = datetime(plan_bas.year, plan_bas.month, plan_bas.day, 17, 0)
    win_bit = win_bas + timedelta(hours=14)
    saat_a = _hafta_sonu_gece_kapasite_saat(win_bas, win_bit, 'A', hafta_sonu)
    saat_b = _hafta_sonu_gece_kapasite_saat(win_bas, win_bit, 'B', hafta_sonu)
    vardiya_saat = VARDIYA_SAAT['gece']['sure_saat']
    tur_a = ref_tur * (saat_a / vardiya_saat)
    tur_b = ref_tur * (saat_b / vardiya_saat)

    def _bitis(kural: str, saat: float, tur: float) -> str:
        if tur >= gerekli_tur:
            frac = min(gerekli_tur / tur, 1.0) if tur else 1.0
            return (win_bas + timedelta(hours=saat * frac)).strftime('%Y-%m-%d %H:%M:%S')
        return (win_bas + timedelta(hours=saat)).strftime('%Y-%m-%d %H:%M:%S')

    return {
        'ornek_baslangic': plan_bas.strftime('%Y-%m-%d %H:%M:%S'),
        'ornek_gerekli_tur': gerekli_tur,
        'secilen_kural': HAFTA_SONU_KURAL,
        'aciklama': (
            'Kural A LOCK: Cuma gece 17:00–Cmt 07:00 kesintisiz devam. '
            'Cmt 07:00 sonrasi hafta sonu kapali ise yeni vardiya baslamaz.'
        ),
        'kural_a_vardiya_baslangic_gunu': {
            'tanim': 'Vardiya basladigi güne (Cuma) göre tam gece penceresi 17:00–Cmt 07:00',
            'kapasite_saat': round(saat_a, 2),
            'tur_kapasitesi': round(tur_a, 2),
            'ornek_tahmini_bitis': _bitis('A', saat_a, tur_a),
            'production': True,
        },
        'kural_b_takvim_saati_debug': {
            'tanim': 'DEBUG ONLY — Cmt 00:00 sonrasi dur (production kullanilmaz)',
            'kapasite_saat': round(saat_b, 2),
            'tur_kapasitesi': round(tur_b, 2),
            'ornek_tahmini_bitis': _bitis('B', saat_b, tur_b),
            'production': False,
        },
    }


def _validate_kalip_basi_cift(
    con: sqlite3.Connection,
    kalip_id: int | None,
    kalip_basi_cift: int | None,
) -> int:
    if kalip_basi_cift and kalip_basi_cift > 0:
        return int(kalip_basi_cift)
    if kalip_id:
        row = con.execute(
            'SELECT kalip_basi_cift FROM enj_kalip WHERE id = ? AND aktif = 1',
            (kalip_id,),
        ).fetchone()
        if row and row[0]:
            return int(row[0])
    raise ValueError('kalip_basi_cift zorunlu (master veya girdi)')


def _check_conflicts(
    con: sqlite3.Connection,
    makine_id: int,
    slot: str,
    istasyonlar: list[int],
    bas: datetime,
    bit: datetime,
    haric_plan_id: int | None = None,
) -> list[dict]:
    conflicts: list[dict] = []
    child_exists = bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='uretim_model_plan_enj_istasyon'"
    ).fetchone())

    for ist in istasyonlar:
        rows: list = []
        if child_exists:
            q = """
                SELECT p.id, p.sip_no, p.mamul_skod, p.renk_adi,
                       p.enj_plan_baslangic, p.enj_plan_bitis, c.istasyon_no AS enj_istasyon_no,
                       p.enj_aktif_goz
                FROM uretim_model_plan p
                JOIN uretim_model_plan_enj_istasyon c ON c.plan_id = p.id
                WHERE p.aktif = 1
                  AND c.enj_makine_id = ?
                  AND c.enj_slot = ?
                  AND c.istasyon_no = ?
                  AND p.enj_plan_baslangic IS NOT NULL
            """
            params: list[Any] = [makine_id, slot, ist]
            if haric_plan_id:
                q += ' AND p.id <> ?'
                params.append(haric_plan_id)
            rows.extend(con.execute(q, params).fetchall())

        q_legacy = """
            SELECT id, sip_no, mamul_skod, renk_adi,
                   enj_plan_baslangic, enj_plan_bitis, enj_istasyon_no, enj_aktif_goz
            FROM uretim_model_plan
            WHERE aktif = 1
              AND enj_makine_id = ?
              AND enj_slot = ?
              AND enj_istasyon_no = ?
              AND enj_plan_baslangic IS NOT NULL
        """
        params_legacy: list[Any] = [makine_id, slot, ist]
        if haric_plan_id:
            q_legacy += ' AND id <> ?'
            params_legacy.append(haric_plan_id)
        if child_exists:
            q_legacy += """
              AND NOT EXISTS (
                  SELECT 1 FROM uretim_model_plan_enj_istasyon c
                   WHERE c.plan_id = uretim_model_plan.id
              )
            """
        rows.extend(con.execute(q_legacy, params_legacy).fetchall())

        seen_ids: set[int] = set()
        for row in rows:
            pid = int(row['id'])
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            try:
                rb = _parse_dt(row['enj_plan_baslangic'])
                re = _parse_dt(row['enj_plan_bitis']) if row['enj_plan_bitis'] else rb + timedelta(hours=1)
            except ValueError:
                continue
            if rb < bit and bas < re:
                conflicts.append({
                    'durum': 'CONFLICT',
                    'plan_id': pid,
                    'sip_no': row['sip_no'],
                    'mamul_skod': row['mamul_skod'],
                    'renk_adi': row['renk_adi'],
                    'istasyon_no': ist,
                    'slot': slot,
                    'plan_baslangic': row['enj_plan_baslangic'],
                    'plan_bitis': row['enj_plan_bitis'],
                })
    return conflicts


def _is_vardiya_boundary(
    dt: datetime,
    calisma_modu: str,
    hafta_sonu: str,
    hs_vardiya: str | None,
) -> bool:
    """Plan baslangici tam vardiya basinda mi (07:00 / 17:00)."""
    dt = dt.replace(second=0, microsecond=0)
    vd = _vardiya_for_dt(dt)
    win_bas, _ = _shift_window(dt, vd)
    if not _mode_allows_vardiya(calisma_modu, vd, hafta_sonu, hs_vardiya, win_bas):
        return False
    return dt == win_bas


def _snap_to_vardiya_boundary(
    dt: datetime,
    calisma_modu: str,
    hafta_sonu: str,
    hs_vardiya: str | None,
) -> datetime:
    """Yeni plan onerisi — vardiya baslangicina normalize (07:00 / 17:00)."""
    dt = dt.replace(second=0, microsecond=0)
    if _is_vardiya_boundary(dt, calisma_modu, hafta_sonu, hs_vardiya):
        return dt
    vd = _vardiya_for_dt(dt)
    _, win_bit = _shift_window(dt, vd)
    nxt = _advance_to_next_slot(
        win_bit + timedelta(minutes=1), calisma_modu, hafta_sonu, hs_vardiya,
    )
    vd2 = _vardiya_for_dt(nxt)
    win_bas2, _ = _shift_window(nxt, vd2)
    return win_bas2


def find_first_available_start(
    con: sqlite3.Connection,
    makine_id: int,
    slot: str,
    istasyonlar: list[int],
    *,
    calisma_modu: str = 'GUNDUZ_GECE',
    hafta_sonu: str = 'HAYIR',
    hs_vardiya: str | None = None,
    from_dt: datetime | None = None,
    haric_plan_id: int | None = None,
) -> datetime:
    """Seçili istasyonlar için çakışmasız ilk vardiya başlangıcını bul."""
    cur = from_dt or datetime.now()
    cur = cur.replace(second=0, microsecond=0)
    cur = _advance_to_next_slot(cur, calisma_modu, hafta_sonu, hs_vardiya)
    probe_end = cur + timedelta(minutes=1)

    for _ in range(500):
        conflicts = _check_conflicts(
            con, makine_id, slot.upper(), istasyonlar, cur, probe_end,
            haric_plan_id=haric_plan_id,
        )
        if not conflicts:
            return _snap_to_vardiya_boundary(
                cur, calisma_modu, hafta_sonu, hs_vardiya,
            )
        latest_end = cur
        for c in conflicts:
            try:
                re = _parse_dt(c['plan_bitis']) if c.get('plan_bitis') else None
            except ValueError:
                re = None
            if re and re > latest_end:
                latest_end = re
        cur = _snap_to_vardiya_boundary(
            latest_end, calisma_modu, hafta_sonu, hs_vardiya,
        )
        probe_end = cur + timedelta(minutes=1)
    raise RuntimeError('Ilk uygun baslangic bulunamadi (takvim asimi)')


def _advance_to_next_slot(
    cur: datetime,
    calisma_modu: str,
    hafta_sonu: str,
    hs_vardiya: str | None,
) -> datetime:
    probe = cur
    for _ in range(500):
        vd = _vardiya_for_dt(probe)
        win_bas, win_bit = _shift_window(probe, vd)
        if probe < win_bas:
            probe = win_bas
        if probe >= win_bit:
            probe = win_bit + timedelta(minutes=1)
            continue
        if _mode_allows_vardiya(calisma_modu, vd, hafta_sonu, hs_vardiya, win_bas):
            return probe
        probe = win_bit + timedelta(minutes=1)
    raise RuntimeError('Uygun vardiya bulunamadi (takvim asimi)')


def _ref_tur_for_vardiya(
    ref_gunduz: dict,
    ref_gece: dict,
    vd: str,
    ref_override: dict | None = None,
) -> float:
    if ref_override and vd in ref_override:
        return float(ref_override[vd])
    ref = ref_gunduz if vd == 'gunduz' else ref_gece
    return float(ref.get('reference_value') or 0)


def simule_takvim(
    plan_bas: datetime,
    remaining_tur: float,
    *,
    calisma_modu: str,
    hafta_sonu: str,
    hs_vardiya: str | None,
    ref_gunduz: dict,
    ref_gece: dict,
    tur_basi_cift: int,
    ref_override: dict | None = None,
) -> dict:
    """Kalan tur icin takvim simulasyonu (Kural A hafta sonu)."""
    cur = plan_bas
    breakdown: list[dict] = []
    weekend_skipped_hours = 0.0
    weekend_crossing = False
    tahmini_calisma_saati = 0.0
    end_dt = plan_bas
    prev_date = None
    rem = float(remaining_tur)

    for _ in range(2000):
        if rem <= 0:
            break
        cur = _advance_to_next_slot(cur, calisma_modu, hafta_sonu, hs_vardiya)
        vd = _vardiya_for_dt(cur)
        win_bas, win_bit = _shift_window(cur, vd)
        if cur > win_bas:
            win_bas = cur

        ref_tur_full = _ref_tur_for_vardiya(ref_gunduz, ref_gece, vd, ref_override)
        if ref_tur_full <= 0:
            return {'ok': False, 'hata': 'Referans tur/vardiya sifir', 'vardiya': vd}

        vardiya_saat = VARDIYA_SAAT[vd]['sure_saat']
        avail_saat = (win_bit - win_bas).total_seconds() / 3600
        if avail_saat <= 0:
            cur = win_bit + timedelta(minutes=1)
            continue

        tur_capacity = ref_tur_full * (avail_saat / vardiya_saat)
        if tur_capacity <= 0:
            cur = win_bit + timedelta(minutes=1)
            continue

        slot_date = win_bas.date()
        ref = ref_gunduz if vd == 'gunduz' else ref_gece

        if rem <= tur_capacity + 1e-9:
            fraction = rem / tur_capacity if tur_capacity else 1
            used_saat = avail_saat * min(fraction, 1.0)
            end_dt = win_bas + timedelta(hours=used_saat)
            cift = int(round(rem * tur_basi_cift))
            breakdown.append({
                'tarih': win_bas.strftime('%Y-%m-%d'),
                'vardiya': vd.upper(),
                'tur': round(rem, 2),
                'cift': cift,
                'kismi_vardiya': avail_saat < vardiya_saat - 0.01 or fraction < 0.999,
                'reference_type': ref.get('reference_type'),
                'reference_value': ref_tur_full,
                'sample_count': ref.get('sample_count'),
            })
            if prev_date and hafta_sonu == 'HAYIR':
                gap = (slot_date - prev_date).days
                if gap >= 2 and prev_date.weekday() <= 4:
                    weekend_crossing = True
            prev_date = slot_date
            tahmini_calisma_saati += used_saat
            rem = 0
        else:
            used_tur = tur_capacity
            rem -= used_tur
            cift = int(round(used_tur * tur_basi_cift))
            breakdown.append({
                'tarih': win_bas.strftime('%Y-%m-%d'),
                'vardiya': vd.upper(),
                'tur': round(used_tur, 2),
                'cift': cift,
                'kismi_vardiya': avail_saat < vardiya_saat - 0.01,
                'reference_type': ref.get('reference_type'),
                'reference_value': ref_tur_full,
                'sample_count': ref.get('sample_count'),
            })
            if prev_date and hafta_sonu == 'HAYIR':
                gap = (slot_date - prev_date).days
                if gap >= 2 and prev_date.weekday() <= 4:
                    weekend_crossing = True
            prev_date = slot_date
            tahmini_calisma_saati += avail_saat
            end_dt = win_bit
            cur = win_bit + timedelta(minutes=1)

    if rem > 0:
        return {'ok': False, 'hata': 'Takvim simulasyonu tamamlanamadi', 'kalan_tur': rem}

    return {
        'ok': True,
        'tahmini_bitis': end_dt,
        'vardiya_breakdown': breakdown,
        'tahmini_calisma_saati': round(tahmini_calisma_saati, 2),
        'weekend_crossing': weekend_crossing,
        'hafta_sonu_atlanan_saat': round(weekend_skipped_hours, 2),
        'tahmini_vardiya_sayisi': len(breakdown),
    }


def simule_takvim_tam_tur(
    plan_bas: datetime,
    gerekli_tam_tur: int,
    *,
    calisma_modu: str,
    hafta_sonu: str,
    hs_vardiya: str | None,
    ref_gunduz: dict,
    ref_gece: dict,
    tur_basi_cift: int,
) -> dict:
    """Tam tur (integer) vardiya dagilimi — UI icin fiziksel tur mantigi."""
    rem = int(gerekli_tam_tur)
    cur = plan_bas
    breakdown: list[dict] = []
    weekend_crossing = False
    tahmini_calisma_saati = 0.0
    end_dt = plan_bas
    prev_date = None

    for _ in range(2000):
        if rem <= 0:
            break
        cur = _advance_to_next_slot(cur, calisma_modu, hafta_sonu, hs_vardiya)
        vd = _vardiya_for_dt(cur)
        win_bas, win_bit = _shift_window(cur, vd)
        cur = win_bas

        ref_tur_full = _ref_tur_for_vardiya(ref_gunduz, ref_gece, vd)
        if ref_tur_full <= 0:
            return {'ok': False, 'hata': 'Referans tur/vardiya sifir', 'vardiya': vd}

        vardiya_saat = VARDIYA_SAAT[vd]['sure_saat']
        max_tur = max(1, int(ref_tur_full))
        slot_tur = min(rem, max_tur)
        ref = ref_gunduz if vd == 'gunduz' else ref_gece
        slot_date = win_bas.date()

        if slot_tur >= rem:
            used_saat = vardiya_saat * (slot_tur / ref_tur_full)
            end_dt = win_bas + timedelta(hours=used_saat)
            kismi = slot_tur < max_tur
        else:
            used_saat = vardiya_saat
            end_dt = win_bit
            kismi = False

        breakdown.append({
            'tarih': win_bas.strftime('%Y-%m-%d'),
            'vardiya': vd.upper(),
            'tur': int(slot_tur),
            'cift': int(slot_tur * tur_basi_cift),
            'kismi_vardiya': kismi,
            'reference_type': ref.get('reference_type'),
            'reference_value': ref_tur_full,
            'sample_count': ref.get('sample_count'),
        })
        if prev_date and hafta_sonu == 'HAYIR':
            gap = (slot_date - prev_date).days
            if gap >= 2 and prev_date.weekday() <= 4:
                weekend_crossing = True
        prev_date = slot_date
        tahmini_calisma_saati += used_saat
        rem -= slot_tur
        cur = win_bit + timedelta(minutes=1)

    if rem > 0:
        return {'ok': False, 'hata': 'Tam tur takvim simulasyonu tamamlanamadi', 'kalan_tur': rem}

    return {
        'ok': True,
        'tahmini_bitis': end_dt,
        'vardiya_breakdown': breakdown,
        'tahmini_calisma_saati': round(tahmini_calisma_saati, 2),
        'weekend_crossing': weekend_crossing,
        'hafta_sonu_atlanan_saat': 0.0,
        'tahmini_vardiya_sayisi': len(breakdown),
    }


def hesapla_kapasite(
    con: sqlite3.Connection,
    payload: dict,
    ref_days: int = 90,
) -> dict:
    makine_kod = payload.get('makine_kod')
    makine_id = payload.get('makine_id')
    if makine_id:
        mk = con.execute(
            'SELECT id, kod, istasyon_sayisi FROM enj_makine WHERE id = ? AND aktif = 1',
            (int(makine_id),),
        ).fetchone()
    elif makine_kod:
        mk = con.execute(
            'SELECT id, kod, istasyon_sayisi FROM enj_makine WHERE kod = ? AND aktif = 1',
            (makine_kod,),
        ).fetchone()
    else:
        return {'ok': False, 'hata': 'makine_kod veya makine_id zorunlu'}

    if not mk:
        return {'ok': False, 'hata': 'Makine bulunamadi'}

    makine_id = int(mk['id'])
    makine_kod = mk['kod']
    istasyon_sayisi = int(mk['istasyon_sayisi'])

    taraf = (payload.get('taraf') or payload.get('slot') or '').upper()
    if taraf not in ('A', 'B'):
        return {'ok': False, 'hata': 'taraf A veya B olmali'}

    istasyonlar = sorted({int(x) for x in (payload.get('istasyonlar') or [])})
    kalip_adedi = int(payload.get('kalip_adedi') or 0)
    if kalip_adedi <= 0:
        kalip_adedi = len(istasyonlar)
    if not istasyonlar:
        return {'ok': False, 'hata': 'istasyonlar zorunlu'}
    if any(i < 1 or i > istasyon_sayisi for i in istasyonlar):
        return {'ok': False, 'hata': 'Gecersiz istasyon no (makine %s, max %s)' % (makine_kod, istasyon_sayisi)}

    try:
        kbc = _validate_kalip_basi_cift(
            con, payload.get('kalip_id'), payload.get('kalip_basi_cift'),
        )
    except ValueError as e:
        return {'ok': False, 'hata': str(e)}

    uretilecek = float(payload.get('uretilecek_cift') or payload.get('gerekli_toplam_cift') or 0)
    if uretilecek <= 0:
        return {'ok': False, 'hata': 'uretilecek_cift > 0 zorunlu'}

    calisma_modu = (payload.get('calisma_modu') or 'GUNDUZ_GECE').upper()
    if calisma_modu not in CALISMA_MODLARI:
        return {'ok': False, 'hata': 'Gecersiz calisma_modu'}

    hafta_sonu = (payload.get('hafta_sonu_calisma') or 'HAYIR').upper()
    if hafta_sonu not in HAFTA_SONU:
        return {'ok': False, 'hata': 'Gecersiz hafta_sonu_calisma'}

    hs_vardiya = payload.get('hafta_sonu_vardiya')
    if hs_vardiya:
        hs_vardiya = hs_vardiya.upper()
        if hs_vardiya not in HS_VARDIYA:
            return {'ok': False, 'hata': 'Gecersiz hafta_sonu_vardiya'}

    try:
        plan_bas = _parse_dt(payload.get('plan_baslangic') or payload.get('baslangic'))
    except ValueError as e:
        return {'ok': False, 'hata': str(e)}

    tur_basi_cift = kalip_adedi * kbc
    teorik_tur = uretilecek / tur_basi_cift
    gerekli_tur = int(math.ceil(teorik_tur))
    teorik_cikan = gerekli_tur * tur_basi_cift
    fazla_cift = int(teorik_cikan - uretilecek) if teorik_cikan > uretilecek else 0

    if not _is_vardiya_boundary(plan_bas, calisma_modu, hafta_sonu, hs_vardiya):
        onerilen = _snap_to_vardiya_boundary(
            plan_bas, calisma_modu, hafta_sonu, hs_vardiya,
        )
        return {
            'ok': False,
            'baslangic_gecersiz': True,
            'hata': (
                'Seçilen saat geçerli vardiya başlangıcı değil. '
                'Gündüz planları 07:00, gece planları 17:00\'de başlamalı.'
            ),
            'onerilen_baslangic': onerilen.strftime('%Y-%m-%d %H:%M:%S'),
            'onerilen_baslangic_gosterim': onerilen.strftime('%d.%m.%Y %H:%M'),
        }

    refs_all = _speed_references(con, makine_id, makine_kod, ref_days=ref_days)
    refs_slot = [r for r in refs_all if r.get('slot') == taraf]

    goz_per_kalip = max(1, int(payload.get('goz_per_kalip') or payload.get('kalip_goz') or 1))
    aktif_goz_toplam = int(
        payload.get('aktif_goz_sayisi') or payload.get('aktif_goz') or 0
    )
    if aktif_goz_toplam <= 0:
        aktif_goz_toplam = kalip_adedi * goz_per_kalip

    ref_gunduz = _lookup_reference(refs_slot, taraf, 'gunduz', aktif_goz_toplam)
    ref_gece = _lookup_reference(refs_slot, taraf, 'gece', aktif_goz_toplam)
    auto_ref_gunduz = dict(ref_gunduz)
    auto_ref_gece = dict(ref_gece)

    reference_mode = (payload.get('reference_mode') or 'AUTO').upper()
    manual_g = payload.get('manual_reference_gunduz')
    manual_e = payload.get('manual_reference_gece')

    def _manual_ref(base: dict, val: float, vardiya: str) -> dict:
        return {
            **base,
            'reference_value': float(val),
            'reference_type': 'MANUEL_PLAN_REFERANSI',
            'confidence': 'MANUEL',
            'sample_count': 0,
            'vardiya': vardiya,
        }

    if reference_mode == 'MANUAL':
        if calisma_modu in ('GUNDUZ', 'GUNDUZ_GECE'):
            try:
                mg = float(manual_g)
            except (TypeError, ValueError):
                mg = 0
            if mg <= 0:
                return {'ok': False, 'hata': 'Manuel gunduz tur/vardiya > 0 zorunlu'}
            ref_gunduz = _manual_ref(auto_ref_gunduz, mg, 'gunduz')
        if calisma_modu in ('GECE', 'GUNDUZ_GECE'):
            try:
                me = float(manual_e)
            except (TypeError, ValueError):
                me = 0
            if me <= 0:
                return {'ok': False, 'hata': 'Manuel gece tur/vardiya > 0 zorunlu'}
            ref_gece = _manual_ref(auto_ref_gece, me, 'gece')
    else:
        if calisma_modu in ('GUNDUZ', 'GUNDUZ_GECE') and ref_gunduz['confidence'] == 'YETERSIZ':
            return {
                'ok': False,
                'hata': 'Gunduz referans yetersiz (sample_count=0)',
                'gunduz_reference': ref_gunduz,
                'gece_reference': ref_gece,
            }
        if calisma_modu in ('GECE', 'GUNDUZ_GECE') and ref_gece['confidence'] == 'YETERSIZ':
            return {
                'ok': False,
                'hata': 'Gece referans yetersiz (sample_count=0)',
                'gunduz_reference': ref_gunduz,
                'gece_reference': ref_gece,
            }

    remaining_tur = int(gerekli_tur)
    sim = simule_takvim_tam_tur(
        plan_bas, remaining_tur,
        calisma_modu=calisma_modu,
        hafta_sonu=hafta_sonu,
        hs_vardiya=hs_vardiya,
        ref_gunduz=ref_gunduz,
        ref_gece=ref_gece,
        tur_basi_cift=tur_basi_cift,
    )
    if not sim.get('ok'):
        return sim

    end_dt = sim['tahmini_bitis']
    breakdown = sim['vardiya_breakdown']
    weekend_crossing = sim['weekend_crossing']
    weekend_skipped_hours = sim['hafta_sonu_atlanan_saat']
    tahmini_calisma_saati = sim['tahmini_calisma_saati']

    conflicts = _check_conflicts(
        con, makine_id, taraf, istasyonlar, plan_bas, end_dt,
        haric_plan_id=payload.get('haric_plan_id'),
    )

    occupied = []
    for ist in istasyonlar:
        occupied.append({
            'istasyon_no': ist,
            'slot': taraf,
            'occupied_from': plan_bas.strftime('%Y-%m-%d %H:%M:%S'),
            'occupied_until': end_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'durum': 'CONFLICT' if conflicts else 'PLANNED',
        })

    bos_istasyonlar = [i for i in range(1, istasyon_sayisi + 1) if i not in istasyonlar]

    refs_used = []
    if calisma_modu in ('GUNDUZ', 'GUNDUZ_GECE'):
        refs_used.append(ref_gunduz.get('confidence', 'YETERSIZ'))
    if calisma_modu in ('GECE', 'GUNDUZ_GECE'):
        refs_used.append(ref_gece.get('confidence', 'YETERSIZ'))
    overall_confidence = _worst_confidence(*refs_used)
    warnings = _build_warnings(ref_gunduz, ref_gece, calisma_modu)
    hs_gece_analiz = _hafta_sonu_gece_sinir_analizi(
        plan_bas, gerekli_tur, ref_gece, hafta_sonu,
    )

    return {
        'ok': True,
        'gerekli_toplam_cift': int(uretilecek) if uretilecek == int(uretilecek) else uretilecek,
        'kalip_adedi': kalip_adedi,
        'goz_per_kalip': goz_per_kalip,
        'aktif_goz_sayisi': aktif_goz_toplam,
        'kalip_basi_cift': kbc,
        'tur_basi_cift': tur_basi_cift,
        'teorik_tur': round(teorik_tur, 4),
        'tahmini_gerekli_tur': gerekli_tur,
        'gerekli_tam_tur': gerekli_tur,
        'siparis_ihtiyaci': int(uretilecek) if uretilecek == int(uretilecek) else uretilecek,
        'teorik_cikan': int(teorik_cikan),
        'fazla_cift': fazla_cift,
        'gunduz_reference': ref_gunduz,
        'gece_reference': ref_gece,
        'auto_gunduz_reference': auto_ref_gunduz,
        'auto_gece_reference': auto_ref_gece,
        'reference_mode': reference_mode,
        'manual_reference_gunduz': float(manual_g) if reference_mode == 'MANUAL' and manual_g is not None else None,
        'manual_reference_gece': float(manual_e) if reference_mode == 'MANUAL' and manual_e is not None else None,
        'overall_confidence': overall_confidence,
        'warnings': warnings,
        'tahmini_bitis_precision': _ui_precision(overall_confidence),
        'tahmini_bitis_gosterim': _format_tahmini_gosterim(end_dt, overall_confidence, breakdown),
        'tahmini_vardiya_sayisi': len(breakdown),
        'tahmini_calisma_saati': round(tahmini_calisma_saati, 2),
        'plan_baslangic': plan_bas.strftime('%Y-%m-%d %H:%M:%S'),
        'tahmini_bitis': end_dt.strftime('%Y-%m-%d %H:%M:%S'),
        'hafta_sonu_atlanan_saat': round(weekend_skipped_hours, 2),
        'weekend_crossing': weekend_crossing,
        'weekend_work': hafta_sonu == 'EVET',
        'hafta_sonu_kural': HAFTA_SONU_KURAL,
        'hafta_sonu_gece_sinir': hs_gece_analiz,
        'makine_kod': makine_kod,
        'makine_id': makine_id,
        'taraf': taraf,
        'istasyonlar': istasyonlar,
        'bos_istasyonlar_ayni_taraf': bos_istasyonlar,
        'occupied_from': plan_bas.strftime('%Y-%m-%d %H:%M:%S'),
        'occupied_until': end_dt.strftime('%Y-%m-%d %H:%M:%S'),
        'istasyon_doluluk': occupied,
        'vardiya_breakdown': breakdown,
        'conflicts': conflicts,
        'conflict_var': len(conflicts) > 0,
        'available': len(conflicts) == 0,
        'pisme_suresi_sn': payload.get('pisme_suresi_sn'),
        'pisme_kapasite_etkisi': 'YOK — tahmin gecmis gercek tur referansindan',
        'vardiya_saatleri_kaynak': 'enjeksiyon routes.SAATLER forensic',
        'vardiya_saatleri': VARDIYA_SAAT,
    }
