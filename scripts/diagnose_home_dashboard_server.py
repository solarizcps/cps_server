# -*- coding: utf-8 -*-
"""
SELECT-only teshis: Ana Ozet Enjeksiyon + Korgun zinciri.

Kullanim:
  python scripts/diagnose_home_dashboard_server.py ^
    --date 2026-07-28 --shift GUNDUZ --month 2026-06 --month2 2026-07 ^
    --order 33595 --emirs 110362,110363,110364,110365,110366,110367

YAZMA YOK. Sifre yazilmaz. Unicode ok isareti yok (ASCII).
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

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = os.path.join(_ROOT, 'app')
if _APP not in sys.path:
    sys.path.insert(0, _APP)


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
    u = (s or 'GUNDUZ').strip().upper().replace('U', 'U')
    if u in ('GUNDUZ', 'GUNDÜZ', 'DAY'):
        return 'gunduz'
    if u in ('GECE', 'NIGHT'):
        return 'gece'
    low = (s or '').strip().lower()
    return low if low in ('gunduz', 'gece') else 'gunduz'


def _print_section(title: str) -> None:
    print()
    print('=' * 72)
    print(title)
    print('=' * 72)


def section_ortam() -> Dict[str, Any]:
    _print_section('A) ORTAM')
    from config import Config

    host = getattr(Config, 'KORGUN_HOST', '') or ''
    info = {
        'hostname': socket.gethostname(),
        'git_sha': _git_sha(),
        'flask_env': os.environ.get('FLASK_ENV') or os.environ.get('CPS_ENV') or 'unknown',
        'config_source': str(getattr(Config, '__module__', 'config')),
        'korgun_host_masked': _mask_host(host),
        'korgun_db': getattr(Config, 'KORGUN_DB', 'Solariz22'),
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
    }
    t0 = rapor_tarih.isoformat()
    dun = (rapor_tarih - timedelta(days=1)).isoformat()
    week_start = (rapor_tarih - timedelta(days=6)).isoformat()
    month_start = rapor_tarih.replace(day=1).isoformat()

    with flask_app.test_client() as c:
        r = c.get('/enjeksiyon/api/makine')
        mj = r.get_json(silent=True) or {}
        machines = mj.get('veri') or mj.get('kayitlar') or []
        print(f'  GET /enjeksiyon/api/makine -> {r.status_code} n={len(machines)}')
        bugun_tot = hafta_tot = ay_tot = 0.0
        aktif_n = 0
        for mid in (1, 2, 3, 4):
            q = (
                f'/enjeksiyon/api/raporlar?makine_id={mid}'
                f'&tarih_baslangic={t0}&tarih_bitis={t0}&limit=50'
            )
            rr = c.get(q)
            rj = rr.get_json(silent=True) or {}
            kayitlar = rj.get('kayitlar') or [] if rj.get('ok') else []
            shift_list = [x for x in kayitlar if (x.get('vardiya') or '') == shift]
            shift_list.sort(
                key=lambda x: (
                    x.get('son_guncelleme') or x.get('olusturma_tarih') or '',
                    x.get('id') or 0,
                ),
                reverse=True,
            )
            rapor = shift_list[0] if shift_list else (kayitlar[0] if kayitlar else None)
            rapor_id = rapor.get('id') if rapor else None
            det = None
            pl = None
            if rapor_id:
                dr = c.get(f'/enjeksiyon/api/raporlar/{rapor_id}/detay')
                det = dr.get_json(silent=True) or {}
                pr = c.get(
                    f'/planlama/api/operasyon/makine/{mid}?tarih={t0}&vardiya={shift}'
                )
                plj = pr.get_json(silent=True) or {}
                pl = plj.get('makine') if plj.get('ok') else None
            slotlar = (det or {}).get('slotlar') or []
            aktif_slot = 0
            for s in slotlar:
                d = str(s.get('durum') or '').upper()
                if s.get('aktif') in (1, True) or d == 'AKTIF' or 'CALIS' in d:
                    aktif_slot += 1
            anlik = (pl or {}).get('anlik_durum') or {}
            tip = str(anlik.get('tip') or '')
            if tip.upper() in ('TUMUYLA_AKTIF', 'HIBRIT') or (anlik.get('sayim') or {}).get('AKTIF', 0) > 0:
                aktif_n += 1
            ozet = (det or {}).get('ozet') or (rapor or {}).get('ozet') or {}
            net = _row_net(ozet)
            for label, a, b in (
                ('bugun', t0, t0),
                ('hafta', week_start, t0),
                ('ay', month_start, t0),
            ):
                qr = c.get(
                    f'/enjeksiyon/api/raporlar?makine_id={mid}'
                    f'&tarih_baslangic={a}&tarih_bitis={b}&limit=200'
                )
                rows = ((qr.get_json(silent=True) or {}).get('kayitlar') or [])
                ssum = sum(_row_net(x.get('ozet')) for x in rows)
                if label == 'bugun':
                    bugun_tot += ssum
                elif label == 'hafta':
                    hafta_tot += ssum
                else:
                    ay_tot += ssum
            qr_dun = c.get(
                f'/enjeksiyon/api/raporlar?makine_id={mid}'
                f'&tarih_baslangic={dun}&tarih_bitis={dun}&vardiya={shift}&limit=50'
            )
            dun_vardiya = sum(
                _row_net(x.get('ozet'))
                for x in ((qr_dun.get_json(silent=True) or {}).get('kayitlar') or [])
            )
            print(
                f'  M{mid}: tip={tip or "-"} aktif_slot={aktif_slot}/{len(slotlar)} '
                f'net={net} rapor_id={rapor_id} dun_vardiya={dun_vardiya}'
            )
            out['machines'][f'M{mid}'] = {
                'tip': tip,
                'aktif_slot': aktif_slot,
                'toplam_slot': len(slotlar),
                'net': net,
                'report_id': rapor_id,
                'dun_vardiya': dun_vardiya,
            }
        out['totals'] = {
            'bugun': bugun_tot,
            'hafta': hafta_tot,
            'ay': ay_tot,
            'aktif_makine': aktif_n,
        }
        print(f'  TOPLAM bugun={bugun_tot} hafta={hafta_tot} ay={ay_tot} aktif={aktif_n}')
    return out


def section_order_trace(order: int, emirs: List[int]) -> Dict[str, Any]:
    _print_section('C) SIPARIS/EMIR SATIR IZI (filtre kaybi)')
    from modules.common.korgun_biten_proses import (
        ALLOWED_PRODUCTION_LOCATIONS,
        _BASE_WHERE_G,
        _EMIR_JOINS,
        _GCH_UNION,
        _LOC_EXPR,
        _baglan,
    )

    out: Dict[str, Any] = {'order': order, 'emirs': emirs, 'rows': [], 'funnel': {}}
    print(f'  order={order} emirs={emirs}')
    wl = list(ALLOWED_PRODUCTION_LOCATIONS)
    ph_e = ','.join(['%s'] * len(emirs)) if emirs else 'NULL'
    ph_l = ','.join(['%s'] * len(wl))

    con = _baglan()
    cur = con.cursor()
    try:
        # Table presence counts
        for label, sql, params in (
            ('Urt_con_gch', f'SELECT COUNT(*) FROM Urt_con_gch WITH (NOLOCK) WHERE EmirNo IN ({ph_e})', tuple(emirs)),
            ('Urtx_con_gch', f'SELECT COUNT(*) FROM Urtx_con_gch WITH (NOLOCK) WHERE EmirNo IN ({ph_e})', tuple(emirs)),
            ('Urt_Emir', f'SELECT COUNT(*) FROM Urt_Emir WITH (NOLOCK) WHERE EmirNo IN ({ph_e})', tuple(emirs)),
            ('Urtx_Emir', f'SELECT COUNT(*) FROM Urtx_Emir WITH (NOLOCK) WHERE EmirNo IN ({ph_e})', tuple(emirs)),
        ):
            cur.execute(sql, params)
            n = int(cur.fetchone()[0] or 0)
            out['funnel'][label] = n
            print(f'  {label}: {n}')

        # Funnel steps on UNION
        steps = [
            ('Ham UNION emir', f"""
                SELECT COUNT(*) FROM {_GCH_UNION}
                WHERE g.EmirNo IN ({ph_e})
            """, tuple(emirs)),
            ('Cikan>0 EndTarih NOT NULL', f"""
                SELECT COUNT(*) FROM {_GCH_UNION}
                WHERE g.EmirNo IN ({ph_e}) AND g.Cikan > 0 AND g.EndTarih IS NOT NULL
            """, tuple(emirs)),
            ('Birim CIFT', f"""
                SELECT COUNT(*) FROM {_GCH_UNION}
                WHERE g.EmirNo IN ({ph_e}) AND {_BASE_WHERE_G}
            """, tuple(emirs)),
            ('FisNo=order', f"""
                SELECT COUNT(*) FROM {_GCH_UNION}
                WHERE g.EmirNo IN ({ph_e}) AND {_BASE_WHERE_G} AND g.FisNo = %s
            """, tuple(emirs) + (order,)),
            ('Emir INNER Urt_Emir only', f"""
                SELECT COUNT(*) FROM {_GCH_UNION}
                INNER JOIN Urt_Emir ue WITH (NOLOCK) ON ue.EmirNo = g.EmirNo
                WHERE g.EmirNo IN ({ph_e}) AND {_BASE_WHERE_G}
            """, tuple(emirs)),
            ('Emir COALESCE Urt+Urtx', f"""
                SELECT COUNT(*) FROM {_GCH_UNION}
                {_EMIR_JOINS}
                WHERE g.EmirNo IN ({ph_e}) AND {_BASE_WHERE_G}
                  AND {_LOC_EXPR} <> ''
            """, tuple(emirs)),
            ('Location whitelist', f"""
                SELECT COUNT(*) FROM {_GCH_UNION}
                {_EMIR_JOINS}
                WHERE g.EmirNo IN ({ph_e}) AND {_BASE_WHERE_G}
                  AND {_LOC_EXPR} IN ({ph_l})
            """, tuple(emirs) + tuple(wl)),
            ('FULL dashboard filter', f"""
                SELECT COUNT(*) FROM {_GCH_UNION}
                {_EMIR_JOINS}
                WHERE g.EmirNo IN ({ph_e}) AND {_BASE_WHERE_G}
                  AND {_LOC_EXPR} IN ({ph_l})
            """, tuple(emirs) + tuple(wl)),
        ]
        print('\n  | Adim | Kalan satir |')
        print('  |---|---:|')
        for name, sql, params in steps:
            cur.execute(sql, params)
            n = int(cur.fetchone()[0] or 0)
            out['funnel'][name] = n
            print(f'  | {name} | {n} |')

        # Per aggregated Excel-like row
        cur.execute(
            f"""
            SELECT g.EmirNo,
                   LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20)))) AS proses,
                   ISNULL(MAX(pm.Tanim), '') AS proses_adi,
                   MAX(g.AltProses) AS alt,
                   MAX(g.Birim) AS birim,
                   SUM(ISNULL(g.Cikan,0)) AS cikan,
                   SUM(ISNULL(g.Giren,0)) AS giren,
                   SUM(ISNULL(g.Fire,0)) AS fire,
                   MIN(g.StartTarih) AS start_t,
                   MAX(g.EndTarih) AS end_t,
                   MAX(g.FisNo) AS fis,
                   MAX(LTRIM(RTRIM(COALESCE(ue.Location, uxe.Location, '')))) AS loc,
                   MAX(CASE WHEN ue.EmirNo IS NULL THEN 0 ELSE 1 END) AS has_urt_emir,
                   MAX(CASE WHEN uxe.EmirNo IS NULL THEN 0 ELSE 1 END) AS has_urtx_emir,
                   MAX(CASE WHEN pm.Pro IS NULL THEN 0 ELSE 1 END) AS pm_match
            FROM {_GCH_UNION}
            {_EMIR_JOINS}
            LEFT JOIN Proses_M pm WITH (NOLOCK)
              ON LTRIM(RTRIM(CAST(pm.Pro AS VARCHAR(20))))
               = LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20))))
            WHERE g.EmirNo IN ({ph_e})
              AND (g.FisNo = %s OR %s = 0)
            GROUP BY g.EmirNo, LTRIM(RTRIM(CAST(g.Proses AS VARCHAR(20))))
            ORDER BY g.EmirNo, 2
            """,
            tuple(emirs) + (order, order),
        )
        print('\n  | Emir | Proses | Biten(=Cikan) | Cikan | Birim | Location | Tarih(End) | Dashboard dahil mi | Elenme nedeni |')
        print('  |---|---|---:|---:|---|---|---|---|---|')
        for r in cur.fetchall():
            emir, proses, padi, alt, birim, cikan, giren, fire, st, et, fis, loc, hu, hx, pm = r
            reasons = []
            ok = True
            if not (cikan and float(cikan) > 0):
                ok = False
                reasons.append('Cikan<=0')
            if et is None:
                ok = False
                reasons.append('EndTarih NULL')
            if str(birim or '').strip().upper() != 'CIFT':
                ok = False
                reasons.append('Birim!=' + repr(birim))
            if int(hu or 0) == 0 and int(hx or 0) == 0:
                ok = False
                reasons.append('Emir yok (Urt+Urtx)')
            elif str(loc or '').strip() not in wl:
                ok = False
                reasons.append('Location not WL:' + repr(loc))
            # table source note
            src = 'Urtx_con_gch' if int(hx or 0) or True else 'Urt_con_gch'
            row = {
                'emir': int(emir),
                'proses': str(proses),
                'proses_adi': str(padi or ''),
                'biten_excel_equiv': float(cikan or 0),
                'cikan': float(cikan or 0),
                'giren': float(giren or 0),
                'birim': birim,
                'location': loc,
                'end_tarih': str(et)[:19] if et else None,
                'start_tarih': str(st)[:19] if st else None,
                'siparis': fis,
                'dashboard_dahil': ok,
                'elenme': '; '.join(reasons) or '-',
                'has_urt_emir': bool(hu),
                'has_urtx_emir': bool(hx),
                'pm_match': bool(pm),
                'table': src,
            }
            out['rows'].append(row)
            print(
                f'  | {emir} | {proses} {padi} | {float(cikan or 0):.0f} | {float(cikan or 0):.0f} | '
                f'{birim} | {loc or "-"} | {str(et)[:10] if et else "-"} | '
                f'{"EVET" if ok else "HAYIR"} | {row["elenme"]} |'
            )

        # Siparis tarihi
        cur.execute(
            "SELECT SipNo, SipTar FROM Siparis_Kay WITH (NOLOCK) WHERE SipNo = %s",
            (order,),
        )
        sk = cur.fetchone()
        out['siparis_kay'] = {
            'SipNo': sk[0] if sk else None,
            'SipTar': str(sk[1])[:19] if sk and sk[1] else None,
        }
        print(f"\n  Siparis_Kay.SipTar={out['siparis_kay']['SipTar']} (Excel 'Siparis Tarihi' alani)")
        print('  Dashboard donem filtresi: EndTarih (bitis), SipTar DEGIL')
        print('  Excel Biten = SUM(Cikan); Giren bu ornekte Cikan ile ayni')
    finally:
        con.close()
    return out


def section_korgun(months: List[str]) -> Dict[str, Any]:
    _print_section('D) KORGUN DONEM OZET')
    from modules.common.korgun_biten_proses import (
        ALLOWED_PRODUCTION_LOCATIONS,
        PROCESS_GROUPS,
        get_home_biten_prosesler,
    )

    out: Dict[str, Any] = {'months': {}, 'whitelist': list(ALLOWED_PRODUCTION_LOCATIONS)}
    targets = [
        'monta_baslayacak', 'montaj', 'temizleme', 'enjeksiyon',
        'kesim', 'silte', 'digital', 'lazer', 'planlama_depo',
    ]
    for ym in months:
        bas, bit = _parse_ym(ym)
        print(f'\n  --- month {ym} ({bas} .. {bit}) ---')
        try:
            api = get_home_biten_prosesler(period='ay', today=bit)
            by = {p['proses_kodu']: p['toplam_cift'] for p in api.get('proses_kartlari') or []}
        except Exception as e:
            print('  API ERR', type(e).__name__, str(e)[:160])
            by = {}
        month_block = {}
        for gkey in targets:
            codes = list((PROCESS_GROUPS.get(gkey) or {}).get('codes') or ())
            val = sum(float(by.get(c, 0) or 0) for c in codes) if codes else None
            month_block[gkey] = {'codes': codes, 'api_value': val}
            print(f'  {gkey:18} codes={codes or "-"} api={val}')
        out['months'][ym] = month_block
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description='Home dashboard SELECT-only diagnose')
    ap.add_argument('--date', default=date.today().isoformat())
    ap.add_argument('--shift', default='GUNDUZ')
    ap.add_argument('--month', default=None)
    ap.add_argument('--month2', default=None)
    ap.add_argument('--order', type=int, default=0, help='Coklu siparis / FisNo ornegin 33595')
    ap.add_argument('--emirs', default='', help='Virgullu EmirNo listesi')
    ap.add_argument('--json-out', default='')
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

    emirs: List[int] = []
    if args.emirs.strip():
        emirs = [int(x.strip()) for x in args.emirs.split(',') if x.strip()]
    elif args.order:
        emirs = [110362, 110363, 110364, 110365, 110366, 110367]

    print('diagnose_home_dashboard_server.py - SELECT-only')
    print('started', datetime.now().isoformat(timespec='seconds'))

    summary: Dict[str, Any] = {}
    try:
        summary['ortam'] = section_ortam()
    except Exception as e:
        traceback.print_exc()
        summary['ortam'] = {'error': str(e)}

    try:
        summary['enjeksiyon'] = section_enjeksiyon(rapor_tarih, shift)
    except Exception as e:
        traceback.print_exc()
        summary['enjeksiyon'] = {'error': f'{type(e).__name__}: {e}'}

    if args.order or emirs:
        try:
            summary['order_trace'] = section_order_trace(int(args.order or 0), emirs)
        except Exception as e:
            traceback.print_exc()
            summary['order_trace'] = {'error': f'{type(e).__name__}: {e}'}

    try:
        summary['korgun'] = section_korgun(months)
    except Exception as e:
        traceback.print_exc()
        summary['korgun'] = {'error': f'{type(e).__name__}: {e}'}

    _print_section('JSON OZET')
    text = json.dumps(summary, ensure_ascii=True, indent=2, default=str)
    print(text[:6000] + ('\n... truncated ...' if len(text) > 6000 else ''))
    if args.json_out:
        with open(args.json_out, 'w', encoding='utf-8') as f:
            f.write(text)
        print('wrote', args.json_out)
    print('\nDONE', datetime.now().isoformat(timespec='seconds'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
