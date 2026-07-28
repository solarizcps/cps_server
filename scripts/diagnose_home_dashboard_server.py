# -*- coding: utf-8 -*-
"""
SELECT-only teşhis: Ana Özet Enjeksiyon + Korgun zinciri.

Kullanım (server):
  python scripts/diagnose_home_dashboard_server.py \\
    --date 2026-07-28 --shift GUNDUZ --month 2026-06 --month2 2026-07

KESİNLİKLE YAZMA YOK: INSERT/UPDATE/DELETE/migration yok.
Şifre asla yazılmaz.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import traceback
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# app/ kökünü path'e al
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = os.path.join(_ROOT, 'app')
if _APP not in sys.path:
    sys.path.insert(0, _APP)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _mask_host(host: str) -> str:
    h = (host or '').strip()
    if not h:
        return '(bos)'
    parts = h.split('.')
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return parts[0] + '.' + parts[1] + '.***.***'
    if len(h) <= 4:
        return h[0] + '***'
    return h[:2] + '***' + h[-2:]


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'],
            cwd=_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return (out or '').strip() or '?'
    except Exception:
        return '?'


def _parse_ymd(s: str) -> date:
    return datetime.strptime(s.strip(), '%Y-%m-%d').date()


def _parse_ym(s: str) -> Tuple[date, date]:
    """YYYY-MM → ay başı/sonu (veya bugün ay içiyse bugün)."""
    y, m = s.strip().split('-')
    bas = date(int(y), int(m), 1)
    if m == '12':
        nxt = date(int(y) + 1, 1, 1)
    else:
        nxt = date(int(y), int(m) + 1, 1)
    bit = nxt - timedelta(days=1)
    today = date.today()
    if bas.year == today.year and bas.month == today.month and bit > today:
        bit = today
    return bas, bit


def _norm_shift(s: str) -> str:
    u = (s or 'GUNDUZ').strip().upper()
    if u in ('GUNDUZ', 'GUNDÜZ', 'DAY'):
        return 'gunduz'
    if u in ('GECE', 'NIGHT'):
        return 'gece'
    if u in ('GUNDUZ',) or u.lower() == 'gunduz':
        return 'gunduz'
    return u.lower() if u.lower() in ('gunduz', 'gece') else 'gunduz'


def _print_section(title: str) -> None:
    print()
    print('=' * 72)
    print(title)
    print('=' * 72)


def section_ortam() -> Dict[str, Any]:
    _print_section('A) ORTAM')
    from config import Config

    host = getattr(Config, 'KORGUN_HOST', '') or ''
    db = getattr(Config, 'KORGUN_DB', 'Solariz22')
    cfg_src = getattr(Config, '__module__', 'config')
    env_name = (
        os.environ.get('FLASK_ENV')
        or os.environ.get('CPS_ENV')
        or getattr(Config, 'ENV', None)
        or 'unknown'
    )
    info = {
        'hostname': socket.gethostname(),
        'git_sha': _git_sha(),
        'flask_env': env_name,
        'config_source': str(cfg_src),
        'korgun_host_masked': _mask_host(host),
        'korgun_db': db,
        'korgun_port': getattr(Config, 'KORGUN_PORT', 1433),
        'cwd': os.getcwd(),
        'app_path': _APP,
    }
    for k, v in info.items():
        print(f'  {k}: {v}')
    print('  password: (asla yazilmaz)')
    return info


def _row_net(ozet: Optional[dict]) -> float:
    if not ozet:
        return 0.0
    if ozet.get('net') is not None:
        try:
            return float(ozet.get('net') or 0)
        except Exception:
            return 0.0
    try:
        return float(ozet.get('toplam_uretim') or 0)
    except Exception:
        return 0.0


def section_enjeksiyon(rapor_tarih: date, shift: str) -> Dict[str, Any]:
    _print_section('B) ENJEKSIYON')
    print(f'  tarih={rapor_tarih.isoformat()} shift={shift}')

    import app as flask_mod
    flask_app = flask_mod.app

    out: Dict[str, Any] = {
        'date': rapor_tarih.isoformat(),
        'shift': shift,
        'machines': {},
        'totals': {},
        'api': {},
    }
    t0 = rapor_tarih.isoformat()
    dun = (rapor_tarih - timedelta(days=1)).isoformat()
    week_start = (rapor_tarih - timedelta(days=6)).isoformat()
    month_start = rapor_tarih.replace(day=1).isoformat()

    with flask_app.test_client() as c:
        # Makine listesi
        r = c.get('/enjeksiyon/api/makine')
        out['api']['makine'] = {'status': r.status_code}
        try:
            mj = r.get_json(silent=True) or {}
        except Exception:
            mj = {}
        machines = mj.get('veri') or mj.get('kayitlar') or []
        print(f'  GET /enjeksiyon/api/makine → {r.status_code} n={len(machines)}')

        bugun_tot = hafta_tot = ay_tot = 0.0
        aktif_n = 0

        for mid in (1, 2, 3, 4):
            mrow = next((m for m in machines if int(m.get('id') or 0) == mid), None)
            mkod = (mrow or {}).get('kod') or f'M{mid}'

            q = (
                f'/enjeksiyon/api/raporlar?makine_id={mid}'
                f'&tarih_baslangic={t0}&tarih_bitis={t0}&limit=50'
            )
            rr = c.get(q)
            rj = rr.get_json(silent=True) or {}
            kayitlar = rj.get('kayitlar') or [] if rj.get('ok') else []
            shift_list = [x for x in kayitlar if (x.get('vardiya') or '') == shift]
            shift_list.sort(
                key=lambda x: (x.get('son_guncelleme') or x.get('olusturma_tarih') or '', x.get('id') or 0),
                reverse=True,
            )
            rapor = shift_list[0] if shift_list else (kayitlar[0] if kayitlar else None)
            rapor_id = rapor.get('id') if rapor else None

            det = None
            ab = None
            pl = None
            det_status = None
            pl_status = None
            if rapor_id:
                dr = c.get(f'/enjeksiyon/api/raporlar/{rapor_id}/detay')
                det_status = dr.status_code
                det = dr.get_json(silent=True) or {}
                ar = c.get(f'/enjeksiyon/api/rapor/{rapor_id}/ab-ozet')
                ab = ar.get_json(silent=True) if ar.status_code < 500 else None
                pr = c.get(
                    f'/planlama/api/operasyon/makine/{mid}'
                    f'?tarih={t0}&vardiya={shift}'
                )
                pl_status = pr.status_code
                plj = pr.get_json(silent=True) or {}
                pl = plj.get('makine') if plj.get('ok') else None

            slotlar = (det or {}).get('slotlar') or []
            aktif_slot = 0
            for s in slotlar:
                d = str(s.get('durum') or '').upper()
                if s.get('aktif') in (1, True) or d == 'AKTIF' or 'CALIS' in d or 'ÇALIŞ' in d:
                    aktif_slot += 1

            anlik = (pl or {}).get('anlik_durum') or {}
            tip = str(anlik.get('tip') or '')
            durum = tip or ('rapor_yok' if not rapor_id else (rapor.get('durum') or '?'))
            if tip.upper() in ('TUMUYLA_AKTIF', 'HIBRIT') or (anlik.get('sayim') or {}).get('AKTIF', 0) > 0:
                aktif_n += 1

            ozet = (det or {}).get('ozet') or (rapor or {}).get('ozet') or {}
            uretim_pl = (pl or {}).get('uretim') or {}
            personel = (rapor or {}).get('personel_sayisi')
            if personel is None and pl:
                personel = pl.get('personel_sayisi') or pl.get('personel')

            a_cift = uretim_pl.get('uretilen_a')
            b_cift = uretim_pl.get('uretilen_b')
            if a_cift is None:
                a_cift = ozet.get('toplam_uretim_a')
            if b_cift is None:
                b_cift = ozet.get('toplam_uretim_b')
            tur_a = uretim_pl.get('tur_a', ozet.get('toplam_tur_a'))
            tur_b = uretim_pl.get('tur_b', ozet.get('toplam_tur_b'))
            net = _row_net(ozet)

            # dönem toplamları (makine)
            for label, a, b in (
                ('bugun', t0, t0),
                ('hafta', week_start, t0),
                ('ay', month_start, t0),
                ('dun', dun, dun),
            ):
                qr = c.get(
                    f'/enjeksiyon/api/raporlar?makine_id={mid}'
                    f'&tarih_baslangic={a}&tarih_bitis={b}&limit=200'
                )
                qj = qr.get_json(silent=True) or {}
                rows = qj.get('kayitlar') or [] if qj.get('ok') else []
                ssum = sum(_row_net(x.get('ozet')) for x in rows)
                if label == 'bugun':
                    bugun_tot += ssum
                elif label == 'hafta':
                    hafta_tot += ssum
                elif label == 'ay':
                    ay_tot += ssum

            # dün aynı vardiya
            qr_dun = c.get(
                f'/enjeksiyon/api/raporlar?makine_id={mid}'
                f'&tarih_baslangic={dun}&tarih_bitis={dun}&vardiya={shift}&limit=50'
            )
            dun_rows = (qr_dun.get_json(silent=True) or {}).get('kayitlar') or []
            dun_vardiya = sum(_row_net(x.get('ozet')) for x in dun_rows)

            row = {
                'kod': mkod,
                'durum': durum,
                'aktif_slot': aktif_slot,
                'toplam_slot': len(slotlar),
                'personel': personel,
                'tur_a': tur_a,
                'tur_b': tur_b,
                'uretim_a': a_cift,
                'uretim_b': b_cift,
                'net': net,
                'report_id': rapor_id,
                'detay_status': det_status,
                'planlama_status': pl_status,
                'dun_vardiya': dun_vardiya,
                'endpoint_raporlar': q,
                'endpoint_planlama': f'/planlama/api/operasyon/makine/{mid}?tarih={t0}&vardiya={shift}',
            }
            out['machines'][f'M{mid}'] = row
            print(
                f"  M{mid}({mkod}): durum={durum} aktif_slot={aktif_slot}/{len(slotlar)} "
                f"personel={personel} net={net} rapor_id={rapor_id} "
                f"A={a_cift} B={b_cift} dun_vardiya={dun_vardiya}"
            )

        out['totals'] = {
            'bugun': bugun_tot,
            'hafta': hafta_tot,
            'ay': ay_tot,
            'aktif_makine': aktif_n,
            'note': 'dun_ayni_saat saatlik kesim UI tarafinda; burada toplam net doner',
        }
        print(f"  TOPLAM bugun={bugun_tot} hafta={hafta_tot} ay={ay_tot} aktif={aktif_n}")
    return out


def _sum_cikan(cur, bas: date, bit: date, codes: List[str], locs: Optional[List[str]]) -> float:
    if not codes:
        return 0.0
    ph_c = ','.join(['%s'] * len(codes))
    params: List[Any] = [bas.isoformat(), bit.isoformat()] + [str(c).strip() for c in codes]
    loc_sql = ''
    if locs is not None:
        ph_l = ','.join(['%s'] * len(locs))
        loc_sql = f" AND LTRIM(RTRIM(ISNULL(ue.Location,''))) IN ({ph_l}) "
        params.extend(locs)
        join = " INNER JOIN Urt_Emir ue WITH (NOLOCK) ON ue.EmirNo = g.EmirNo "
    else:
        join = ''
    cur.execute(
        f"""
        SELECT COALESCE(SUM(ISNULL(g.Cikan,0)),0)
        FROM Urt_con_gch g WITH (NOLOCK)
        {join}
        WHERE g.Cikan > 0 AND g.EndTarih IS NOT NULL
          AND UPPER(LTRIM(RTRIM(ISNULL(g.Birim,'')))) = 'CIFT'
          AND CAST(g.EndTarih AS DATE) >= CAST(%s AS DATE)
          AND CAST(g.EndTarih AS DATE) <= CAST(%s AS DATE)
          AND LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20)))) IN ({ph_c})
          {loc_sql}
        """,
        tuple(params),
    )
    row = cur.fetchone()
    return float(row[0] or 0) if row else 0.0


def _discover_codes(cur, aliases: Tuple[str, ...]) -> List[Tuple[str, str]]:
    """Proses_M'den alias ile kod keşfi (SELECT)."""
    found: List[Tuple[str, str]] = []
    for alias in aliases:
        like = f'%{alias}%'
        cur.execute(
            """
            SELECT LTRIM(RTRIM(CAST(Pro AS VARCHAR(20)))), ISNULL(Tanim,'')
            FROM Proses_M WITH (NOLOCK)
            WHERE LOWER(ISNULL(Tanim,'')) LIKE LOWER(%s)
            ORDER BY Pro
            """,
            (like,),
        )
        for kod, tanim in cur.fetchall() or []:
            k = str(kod or '').strip()
            if k and (k, str(tanim or '').strip()) not in found:
                found.append((k, str(tanim or '').strip()))
    return found


def section_korgun(months: List[str]) -> Dict[str, Any]:
    _print_section('C) KORGUN')
    from modules.common.korgun_biten_proses import (
        ALLOWED_PRODUCTION_LOCATIONS,
        PROCESS_GROUPS,
        get_home_biten_prosesler,
        _baglan,
    )

    targets = [
        ('montaj', 'Montaj'),
        ('temizleme', 'Temizleme'),
        ('enjeksiyon', 'Enjeksiyon'),
        ('kesim', 'Kesim'),
        ('silte', 'Şilte'),
        ('digital', 'Digital'),
        ('lazer', 'Lazer'),
        ('planlama_depo', 'Planlama-Depo'),
    ]

    out: Dict[str, Any] = {'months': {}, 'whitelist': list(ALLOWED_PRODUCTION_LOCATIONS)}
    print('  whitelist:', ', '.join(ALLOWED_PRODUCTION_LOCATIONS))

    con = None
    try:
        con = _baglan()
        cur = con.cursor()
    except Exception as e:
        print('  KORGUN BAGLANTI HATASI:', type(e).__name__, str(e)[:200])
        out['error'] = f'{type(e).__name__}: {e}'
        return out

    try:
        for ym in months:
            bas, bit = _parse_ym(ym)
            print(f'\n  --- month {ym} ({bas} .. {bit}) ---')
            month_block: Dict[str, Any] = {}

            # API (servis katmanı — HTTP auth bypass; aynı hesap)
            api_by_kod: Dict[str, float] = {}
            api_err = None
            try:
                # period=ay için today'i ay sonuna sabitle (diagnose)
                api = get_home_biten_prosesler(period='ay', today=bit)
                for p in api.get('proses_kartlari') or []:
                    api_by_kod[str(p.get('proses_kodu'))] = float(p.get('toplam_cift') or 0)
            except Exception as e:
                api_err = f'{type(e).__name__}: {e}'
                print('  API hata:', api_err)

            for gkey, label in targets:
                meta = PROCESS_GROUPS.get(gkey) or {}
                codes = [str(c) for c in (meta.get('codes') or ())]
                aliases = tuple(meta.get('label_aliases') or ())
                discovered = _discover_codes(cur, aliases)
                for kod, _ad in discovered:
                    if kod not in codes:
                        codes.append(kod)
                codes = list(dict.fromkeys(codes))

                # lokasyon / birim dağılımı
                loc_dist: List[Any] = []
                birim_dist: List[Any] = []
                names: List[str] = []
                if codes:
                    ph = ','.join(['%s'] * len(codes))
                    cur.execute(
                        f"""
                        SELECT LTRIM(RTRIM(CAST(Pro AS VARCHAR(20)))), ISNULL(Tanim,'')
                        FROM Proses_M WITH (NOLOCK)
                        WHERE LTRIM(RTRIM(CAST(Pro AS VARCHAR(20)))) IN ({ph})
                        """,
                        tuple(codes),
                    )
                    names = [f'{a}={b}' for a, b in (cur.fetchall() or [])]

                    cur.execute(
                        f"""
                        SELECT LTRIM(RTRIM(ISNULL(ue.Location,''))), COUNT(*), SUM(ISNULL(g.Cikan,0))
                        FROM Urt_con_gch g WITH (NOLOCK)
                        INNER JOIN Urt_Emir ue WITH (NOLOCK) ON ue.EmirNo = g.EmirNo
                        WHERE g.Cikan > 0 AND g.EndTarih IS NOT NULL
                          AND UPPER(LTRIM(RTRIM(ISNULL(g.Birim,'')))) = 'CIFT'
                          AND CAST(g.EndTarih AS DATE) >= CAST(%s AS DATE)
                          AND CAST(g.EndTarih AS DATE) <= CAST(%s AS DATE)
                          AND LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20)))) IN ({ph})
                        GROUP BY LTRIM(RTRIM(ISNULL(ue.Location,'')))
                        ORDER BY SUM(ISNULL(g.Cikan,0)) DESC
                        """,
                        (bas.isoformat(), bit.isoformat()) + tuple(codes),
                    )
                    loc_dist = [
                        {'loc': r[0], 'n': int(r[1] or 0), 'qty': float(r[2] or 0)}
                        for r in (cur.fetchall() or [])
                    ]

                    cur.execute(
                        f"""
                        SELECT UPPER(LTRIM(RTRIM(ISNULL(g.Birim,'')))), COUNT(*), SUM(ISNULL(g.Cikan,0))
                        FROM Urt_con_gch g WITH (NOLOCK)
                        WHERE g.Cikan > 0 AND g.EndTarih IS NOT NULL
                          AND CAST(g.EndTarih AS DATE) >= CAST(%s AS DATE)
                          AND CAST(g.EndTarih AS DATE) <= CAST(%s AS DATE)
                          AND LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20)))) IN ({ph})
                        GROUP BY UPPER(LTRIM(RTRIM(ISNULL(g.Birim,''))))
                        ORDER BY SUM(ISNULL(g.Cikan,0)) DESC
                        """,
                        (bas.isoformat(), bit.isoformat()) + tuple(codes),
                    )
                    birim_dist = [
                        {'birim': r[0], 'n': int(r[1] or 0), 'qty': float(r[2] or 0)}
                        for r in (cur.fetchall() or [])
                    ]

                filtresiz = _sum_cikan(cur, bas, bit, codes, None) if codes else 0.0
                filtreli = (
                    _sum_cikan(cur, bas, bit, codes, list(ALLOWED_PRODUCTION_LOCATIONS))
                    if codes else 0.0
                )
                api_val = sum(api_by_kod.get(c, 0.0) for c in codes) if codes else None
                fark = (None if api_val is None else (filtreli - float(api_val)))

                block = {
                    'label': label,
                    'group_key': gkey,
                    'codes': codes,
                    'proses_adlari': names,
                    'discovered': [{'kod': a, 'ad': b} for a, b in discovered],
                    'lokasyon_dagilimi': loc_dist[:12],
                    'birim_dagilimi': birim_dist[:12],
                    'filtresiz_sum_cikan': filtresiz,
                    'filtreli_sum_cikan': filtreli,
                    'api_value': api_val,
                    'fark_filtreli_minus_api': fark,
                    'api_error': api_err,
                }
                month_block[gkey] = block
                print(
                    f"  {label:14} codes={codes or '-'} filtresiz={filtresiz:.0f} "
                    f"filtreli={filtreli:.0f} api={api_val} fark={fark}"
                )
                if loc_dist[:5]:
                    print('    loc_top:', ', '.join(f"{x['loc']}={x['qty']:.0f}" for x in loc_dist[:5]))

            out['months'][ym] = month_block
    except Exception as e:
        out['error'] = f'{type(e).__name__}: {e}'
        print('  EXCEPTION:', out['error'])
        traceback.print_exc()
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass
    return out


def section_api_home(period: str = 'hafta') -> Dict[str, Any]:
    _print_section('D) API HOME KORGUN')
    import app as flask_mod
    flask_app = flask_mod.app

    out: Dict[str, Any] = {}
    with flask_app.test_client() as c:
        # Oturumsuz — 401 beklenir; servis zaten C'de çağrıldı
        r = c.get(f'/api/home/korgun/biten-prosesler?period={period}')
        body = r.get_json(silent=True) or {}
        out['http_status'] = r.status_code
        out['ok'] = body.get('ok')
        out['error'] = body.get('error')
        out['summary_keys'] = list((body.get('summary') or {}).keys())
        out['kart_n'] = len(body.get('proses_kartlari') or [])
        print(f'  GET /api/home/korgun/biten-prosesler?period={period} → {r.status_code}')
        print(f'  ok={body.get("ok")} error={body.get("error")} kart_n={out["kart_n"]}')
        if r.status_code == 401:
            print('  not: oturum yok (beklenen); servis katmani C bolumunde dogrulandi')
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description='Home dashboard SELECT-only diagnose')
    ap.add_argument('--date', default=date.today().isoformat(), help='YYYY-MM-DD')
    ap.add_argument('--shift', default='GUNDUZ', help='GUNDUZ|GECE')
    ap.add_argument('--month', default=None, help='YYYY-MM (Korgun)')
    ap.add_argument('--month2', default=None, help='YYYY-MM ikinci ay')
    ap.add_argument('--json-out', default='', help='JSON ozet dosya yolu (opsiyonel)')
    args = ap.parse_args()

    rapor_tarih = _parse_ymd(args.date)
    shift = _norm_shift(args.shift)
    months: List[str] = []
    if args.month:
        months.append(args.month.strip())
    if args.month2:
        months.append(args.month2.strip())
    if not months:
        t = date.today()
        months = [t.strftime('%Y-%m'), (t.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')]

    print('diagnose_home_dashboard_server.py — SELECT-only')
    print('started', datetime.now().isoformat(timespec='seconds'))

    summary: Dict[str, Any] = {}
    try:
        summary['ortam'] = section_ortam()
    except Exception as e:
        print('ORTAM HATA', e)
        traceback.print_exc()
        summary['ortam'] = {'error': str(e)}

    try:
        summary['enjeksiyon'] = section_enjeksiyon(rapor_tarih, shift)
    except Exception as e:
        print('ENJEKSIYON HATA', e)
        traceback.print_exc()
        summary['enjeksiyon'] = {'error': f'{type(e).__name__}: {e}'}

    try:
        summary['korgun'] = section_korgun(months)
    except Exception as e:
        print('KORGUN HATA', e)
        traceback.print_exc()
        summary['korgun'] = {'error': f'{type(e).__name__}: {e}'}

    try:
        summary['api'] = section_api_home('hafta')
    except Exception as e:
        print('API HATA', e)
        traceback.print_exc()
        summary['api'] = {'error': f'{type(e).__name__}: {e}'}

    _print_section('JSON OZET')
    text = json.dumps(summary, ensure_ascii=False, indent=2, default=str)
    print(text[:8000] + ('\n... truncated ...' if len(text) > 8000 else ''))
    if args.json_out:
        with open(args.json_out, 'w', encoding='utf-8') as f:
            f.write(text)
        print('wrote', args.json_out)

    print('\nDONE', datetime.now().isoformat(timespec='seconds'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
