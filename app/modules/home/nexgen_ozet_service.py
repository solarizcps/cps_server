# -*- coding: utf-8 -*-
"""
NexGen Ana Ozet — salt okunur aggregator.

Kaynak: mock_data.db NexGen tablolari (SELECT only).
Yazma / migration / is kurali degisikligi yok.
Gercek uretim = nexgen_rf_kullanim.miktar_kg (aktif=1).
Planlanan kg uretim diye gosterilmez.
"""
from __future__ import annotations

import os
import sqlite3
import time
import traceback
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

_DB_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'mock_data.db')
)

# Durum filtreleri (mevcut enum'lardan — tahmin eklenmedi)
_SIPARIS_ACIK = ('ONAYLANDI', 'MPR_BEKLIYOR', 'PLANLAMAYA_HAZIR', 'URETIMDE', 'TAMAMLANDI')
_PLAN_AKTIF = ('ON_CALISMA', 'PLANLANDI', 'BASLADI', 'URETIMDE')
_PLAN_BEKLEYEN = ('ON_CALISMA', 'PLANLANDI')
_BATCH_AKTIF = ('DEVAM', 'HAZIR', 'BEKLEME')
_PARCA_DEVAM = ('DEVAM',)
_PARCA_ACIK = ('HAZIR', 'DEVAM', 'BEKLEME')
_SEVK_EDILDI = ('SEVK_EDILDI', 'TESLIM_EDILDI', 'TAMAMLANDI')
_SEVK_BEKLEYEN = ('HAZIRLANIYOR', 'YUKLENIYOR')
_RF_ONAYLI = ('ONAYLI',)
_NUMUNE_BEKLEYEN = ('BEKLEYEN_NUMUNE', 'ONAY_BEKLIYOR')
_NUMUNE_DEVAM = ('CALISILIYOR',)
_NUMUNE_REVIZYON = ('REVIZYONDA',)
_RECETE_AKTIF = ('URETIME_ACIK', 'AKTIF')


class NexgenOzetError(Exception):
    pass


def _ymd(d: date) -> str:
    return d.isoformat()


def _num(v) -> float:
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _connect() -> sqlite3.Connection:
    if not os.path.exists(_DB_PATH):
        raise NexgenOzetError('NexGen DB bulunamadi')
    con = sqlite3.connect(_DB_PATH, timeout=8)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _section_ok(data: Any, **meta) -> Dict[str, Any]:
    out = {'available': True, 'error': None, 'data': data}
    out.update(meta)
    return out


def _section_err(msg: str) -> Dict[str, Any]:
    return {'available': False, 'error': msg, 'data': None}


def _kg_block(kg: float) -> Dict[str, float]:
    k = round(_num(kg), 3)
    return {'kg': k, 'ton': round(k / 1000.0, 3)}


def _prod_sum(con, bas: str, bit: str) -> float:
    if not _table_exists(con, 'nexgen_rf_kullanim'):
        return 0.0
    row = con.execute(
        """
        SELECT ROUND(COALESCE(SUM(miktar_kg), 0), 3) AS kg
        FROM nexgen_rf_kullanim
        WHERE aktif = 1
          AND DATE(olusturma_tarihi) >= DATE(?)
          AND DATE(olusturma_tarihi) <= DATE(?)
        """,
        (bas, bit),
    ).fetchone()
    return _num(row['kg'] if row else 0)


def _production(con, today: date, warnings: List[str]) -> Dict[str, Any]:
    if not _table_exists(con, 'nexgen_rf_kullanim'):
        return _section_err('nexgen_rf_kullanim yok')
    try:
        t = _ymd(today)
        dun = _ymd(today - timedelta(days=1))
        ay_bas = _ymd(today.replace(day=1))
        onceki_ay_son = today.replace(day=1) - timedelta(days=1)
        onceki_ay_bas = onceki_ay_son.replace(day=1)
        hafta_bas = _ymd(today - timedelta(days=6))

        bugun = _prod_sum(con, t, t)
        dun_kg = _prod_sum(con, dun, dun)
        ay = _prod_sum(con, ay_bas, t)
        onceki_ay = _prod_sum(con, _ymd(onceki_ay_bas), _ymd(onceki_ay_son))

        def _delta_pct(cur, prev):
            if prev <= 0:
                return None if cur <= 0 else 100.0
            return round(((cur - prev) / prev) * 100.0, 1)

        # son 7 gun seri
        trend = []
        d0 = today - timedelta(days=6)
        while d0 <= today:
            k = _prod_sum(con, _ymd(d0), _ymd(d0))
            trend.append({'tarih': _ymd(d0), **_kg_block(k)})
            d0 += timedelta(days=1)

        aktif_batch = 0
        if _table_exists(con, 'nexgen_uretim_batch'):
            ph = ','.join(['?'] * len(_BATCH_AKTIF))
            aktif_batch = int(con.execute(
                f"SELECT COUNT(*) AS c FROM nexgen_uretim_batch WHERE durum IN ({ph})",
                _BATCH_AKTIF,
            ).fetchone()['c'] or 0)

        devam_parca = 0
        biten_parca_bugun = 0
        if _table_exists(con, 'nexgen_uretim_parca'):
            devam_parca = int(con.execute(
                "SELECT COUNT(*) AS c FROM nexgen_uretim_parca WHERE durum = 'DEVAM'"
            ).fetchone()['c'] or 0)
            biten_parca_bugun = int(con.execute(
                """
                SELECT COUNT(*) AS c FROM nexgen_uretim_parca
                WHERE durum = 'BITTI'
                  AND (
                    DATE(COALESCE(bitis_zamani, updated_at, created_at)) = DATE(?)
                  )
                """,
                (t,),
            ).fetchone()['c'] or 0)

        biten_batch = 0
        if _table_exists(con, 'nexgen_uretim_batch'):
            biten_batch = int(con.execute(
                "SELECT COUNT(*) AS c FROM nexgen_uretim_batch WHERE durum = 'BITTI'"
            ).fetchone()['c'] or 0)

        data = {
            'bugun': _kg_block(bugun),
            'dun': _kg_block(dun_kg),
            'ay': _kg_block(ay),
            'onceki_ay': _kg_block(onceki_ay),
            'bugun_vs_dun_pct': _delta_pct(bugun, dun_kg),
            'ay_vs_onceki_pct': _delta_pct(ay, onceki_ay),
            'trend_7g': trend,
            'aktif_batch': aktif_batch,
            'devam_eden_alt_emir': devam_parca,
            'tamamlanan_alt_emir_bugun': biten_parca_bugun,
            'tamamlanan_batch': biten_batch,
            'filters': {
                'production_source': 'nexgen_rf_kullanim.miktar_kg WHERE aktif=1',
                'aktif_batch_durum': list(_BATCH_AKTIF),
                'alt_emir_devam': list(_PARCA_DEVAM),
            },
        }
        return _section_ok(data, period_range={'bas': hafta_bas, 'bit': t, 'ay_bas': ay_bas})
    except Exception as e:
        warnings.append('production: ' + type(e).__name__)
        return _section_err(str(e))


def _company_distribution(con, today: date, warnings: List[str]) -> Dict[str, Any]:
    if not _table_exists(con, 'nexgen_rf_kullanim'):
        return _section_err('nexgen_rf_kullanim yok')
    try:
        t = _ymd(today)
        ay_bas = _ymd(today.replace(day=1))
        rows = con.execute(
            """
            SELECT
              COALESCE(k.cari_id, p.cari_id) AS cari_id,
              COALESCE(
                NULLIF(TRIM(c.unvan), ''),
                NULLIF(TRIM(p.cari_unvan), ''),
                NULLIF(TRIM(c2.unvan), ''),
                'Diğer / Eşleşmemiş'
              ) AS cari_adi,
              ROUND(SUM(k.miktar_kg), 3) AS uretim_kg,
              COUNT(DISTINCT k.siparis_id) AS siparis_sayisi,
              COUNT(DISTINCT k.tablet_session_id) AS batch_sayisi
            FROM nexgen_rf_kullanim k
            LEFT JOIN nexgen_planlama_siparis p ON p.id = k.siparis_id
            LEFT JOIN nexgen_cari c ON c.id = k.cari_id
            LEFT JOIN nexgen_cari c2 ON c2.id = p.cari_id
            WHERE k.aktif = 1
              AND DATE(k.olusturma_tarihi) >= DATE(?)
              AND DATE(k.olusturma_tarihi) <= DATE(?)
            GROUP BY COALESCE(k.cari_id, p.cari_id), cari_adi
            ORDER BY uretim_kg DESC
            """,
            (ay_bas, t),
        ).fetchall()
        items = []
        toplam = 0.0
        for r in rows:
            kg = _num(r['uretim_kg'])
            toplam += kg
            cid = r['cari_id']
            adi = (r['cari_adi'] or 'Diger / Eslesmemis').strip()
            if cid is None or adi in ('Diger / Eslesmemis', 'Diger', 'Diğer / Eşleşmemiş'):
                adi = 'Diğer / Eşleşmemiş'
            items.append({
                'cari_id': cid,
                'cari_adi': adi,
                'uretim_kg': kg,
                'uretim_ton': round(kg / 1000.0, 3),
                'siparis_sayisi': int(r['siparis_sayisi'] or 0),
                'batch_sayisi': int(r['batch_sayisi'] or 0),
            })
        for it in items:
            it['pay_yuzde'] = round((it['uretim_kg'] / toplam) * 100.0, 1) if toplam > 0 else 0.0
        # Top 4 + Diger birlestir (referans gorunum)
        if len(items) > 5:
            top = items[:4]
            rest = items[4:]
            diger_kg = sum(x['uretim_kg'] for x in rest)
            top.append({
                'cari_id': None,
                'cari_adi': 'Diğer',
                'uretim_kg': round(diger_kg, 3),
                'uretim_ton': round(diger_kg / 1000.0, 3),
                'pay_yuzde': round((diger_kg / toplam) * 100.0, 1) if toplam > 0 else 0.0,
                'siparis_sayisi': sum(x['siparis_sayisi'] for x in rest),
                'batch_sayisi': sum(x['batch_sayisi'] for x in rest),
                'aggregated': True,
            })
            items = top
        return _section_ok(items, total_kg=round(toplam, 3))
    except Exception as e:
        warnings.append('company: ' + type(e).__name__)
        return _section_err(str(e))


def _product_distribution(con, today: date, warnings: List[str]) -> Dict[str, Any]:
    if not _table_exists(con, 'nexgen_rf_kullanim'):
        return _section_err('nexgen_rf_kullanim yok')
    try:
        t = _ymd(today)
        ay_bas = _ymd(today.replace(day=1))
        def _norm_aile(raw: str) -> str:
            a = (raw or '').strip().upper().replace('İ', 'I')
            if a in ('TERLIK', 'TERLİK'):
                return 'TERLIK'
            if a == 'TABAN':
                return 'TABAN'
            if a in ('DOKME', 'DÖKME'):
                return 'DOKME'
            return 'DIGER'

        # Satir bazinda: kalem agirligi → formul.urun_ailesi → DIGER
        rows = con.execute(
            """
            SELECT k.id, k.siparis_id, k.formul_id, k.miktar_kg
            FROM nexgen_rf_kullanim k
            WHERE k.aktif = 1
              AND DATE(k.olusturma_tarihi) >= DATE(?)
              AND DATE(k.olusturma_tarihi) <= DATE(?)
              AND COALESCE(k.miktar_kg, 0) > 0
            """,
            (ay_bas, t),
        ).fetchall()
        tip_kg = {'TERLIK': 0.0, 'TABAN': 0.0, 'DOKME': 0.0, 'DIGER': 0.0}
        has_kalem = _table_exists(con, 'nexgen_planlama_siparis_kalem')
        has_formul = _table_exists(con, 'nexgen_formul')
        for r in rows:
            pkg = _num(r['miktar_kg'])
            sid = r['siparis_id']
            allocated = False
            if has_kalem and sid is not None:
                kals = con.execute(
                    """
                    SELECT UPPER(COALESCE(urun_ailesi, '')) AS aile,
                           COALESCE(miktar_l,0)+COALESCE(miktar_s,0)+COALESCE(miktar_m,0) AS kg
                    FROM nexgen_planlama_siparis_kalem
                    WHERE planlama_siparis_id = ?
                    """,
                    (int(sid),),
                ).fetchall()
                weights = []
                for k in kals:
                    aile = _norm_aile(k['aile'])
                    if aile == 'DIGER':
                        continue
                    weights.append((aile, max(_num(k['kg']), 0.0)))
                wsum = sum(w for _, w in weights)
                if wsum > 0:
                    for aile, w in weights:
                        tip_kg[aile] += pkg * (w / wsum)
                    allocated = True
            if not allocated and has_formul and r['formul_id'] is not None:
                fr = con.execute(
                    "SELECT urun_ailesi FROM nexgen_formul WHERE id = ?",
                    (int(r['formul_id']),),
                ).fetchone()
                aile = _norm_aile(fr['urun_ailesi'] if fr else '')
                tip_kg[aile] += pkg
                allocated = True
            if not allocated:
                tip_kg['DIGER'] += pkg

        toplam = sum(tip_kg.values())
        label = {'TERLIK': 'TERLİK', 'TABAN': 'TABAN', 'DOKME': 'DÖKME', 'DIGER': 'DİĞER'}
        items = []
        for tip in ('TERLIK', 'TABAN', 'DOKME', 'DIGER'):
            kg = round(tip_kg[tip], 3)
            if kg <= 0:
                continue
            items.append({
                'urun_tipi': tip,
                'urun_tipi_label': label[tip],
                'uretim_kg': kg,
                'uretim_ton': round(kg / 1000.0, 3),
                'pay_yuzde': round((kg / toplam) * 100.0, 1) if toplam > 0 else 0.0,
            })
        return _section_ok(items, total_kg=round(toplam, 3))
    except Exception as e:
        warnings.append('product: ' + type(e).__name__)
        return _section_err(str(e))


def _planning(con, warnings: List[str]) -> Dict[str, Any]:
    try:
        data = {
            'acik_siparis_sayisi': 0,
            'acik_siparis_kg': 0.0,
            'planlanan_siparis_sayisi': 0,
            'planlanan_kg': 0.0,
            'bekleyen_plan': 0,
            'aktif_plan': 0,
            'filters': {
                'acik_siparis_durum': list(_SIPARIS_ACIK),
                'aktif_plan_durum': list(_PLAN_AKTIF),
                'bekleyen_plan_durum': list(_PLAN_BEKLEYEN),
            },
        }
        if _table_exists(con, 'nexgen_planlama_siparis'):
            ph = ','.join(['?'] * len(_SIPARIS_ACIK))
            data['acik_siparis_sayisi'] = int(con.execute(
                f"SELECT COUNT(*) AS c FROM nexgen_planlama_siparis WHERE durum IN ({ph})",
                _SIPARIS_ACIK,
            ).fetchone()['c'] or 0)
            # kg: kalem toplam (planlanan siparis kg — etiket acik)
            if _table_exists(con, 'nexgen_planlama_siparis_kalem'):
                row = con.execute(
                    f"""
                    SELECT ROUND(COALESCE(SUM(
                      COALESCE(k.miktar_l,0)+COALESCE(k.miktar_s,0)+COALESCE(k.miktar_m,0)
                    ),0),3) AS kg
                    FROM nexgen_planlama_siparis_kalem k
                    JOIN nexgen_planlama_siparis s ON s.id = k.planlama_siparis_id
                    WHERE s.durum IN ({ph})
                    """,
                    _SIPARIS_ACIK,
                ).fetchone()
                data['acik_siparis_kg'] = _num(row['kg'] if row else 0)

        if _table_exists(con, 'nexgen_uretim_plan'):
            ph_a = ','.join(['?'] * len(_PLAN_AKTIF))
            ph_b = ','.join(['?'] * len(_PLAN_BEKLEYEN))
            data['aktif_plan'] = int(con.execute(
                f"SELECT COUNT(*) AS c FROM nexgen_uretim_plan WHERE durum IN ({ph_a})",
                _PLAN_AKTIF,
            ).fetchone()['c'] or 0)
            data['bekleyen_plan'] = int(con.execute(
                f"SELECT COUNT(*) AS c FROM nexgen_uretim_plan WHERE durum IN ({ph_b})",
                _PLAN_BEKLEYEN,
            ).fetchone()['c'] or 0)
            row = con.execute(
                f"""
                SELECT ROUND(COALESCE(SUM(planlanan_kg),0),3) AS kg,
                       COUNT(DISTINCT COALESCE(planlama_siparis_id, siparis_no)) AS sc
                FROM nexgen_uretim_plan
                WHERE durum IN ({ph_a})
                """,
                _PLAN_AKTIF,
            ).fetchone()
            data['planlanan_kg'] = _num(row['kg'] if row else 0)
            data['planlanan_siparis_sayisi'] = int(row['sc'] or 0) if row else 0

        # malzeme eksik: guvenilir global sayac yok → kart gizlenecek
        data['malzeme_eksik_available'] = False
        data['malzeme_eksik_plan'] = None
        return _section_ok(data)
    except Exception as e:
        warnings.append('planning: ' + type(e).__name__)
        return _section_err(str(e))


def _shipment(con, today: date, warnings: List[str]) -> Dict[str, Any]:
    if not _table_exists(con, 'mo_musteri_sevkiyat'):
        return _section_err('mo_musteri_sevkiyat yok')
    try:
        t = _ymd(today)
        ay_bas = _ymd(today.replace(day=1))
        ph_e = ','.join(['?'] * len(_SEVK_EDILDI))
        ph_b = ','.join(['?'] * len(_SEVK_BEKLEYEN))

        def sevk_kg(bas, bit):
            if not _table_exists(con, 'mo_musteri_sevkiyat_kalem'):
                return 0.0
            row = con.execute(
                f"""
                SELECT ROUND(COALESCE(SUM(k.miktar_kg),0),3) AS kg
                FROM mo_musteri_sevkiyat_kalem k
                JOIN mo_musteri_sevkiyat s ON s.id = k.sevkiyat_id
                WHERE s.aktif = 1
                  AND s.durum IN ({ph_e})
                  AND DATE(COALESCE(s.sevk_tarihi, s.olusturma_tarihi)) >= DATE(?)
                  AND DATE(COALESCE(s.sevk_tarihi, s.olusturma_tarihi)) <= DATE(?)
                """,
                _SEVK_EDILDI + (bas, bit),
            ).fetchone()
            return _num(row['kg'] if row else 0)

        bugun_kg = sevk_kg(t, t)
        ay_kg = sevk_kg(ay_bas, t)
        bugun_adet = int(con.execute(
            f"""
            SELECT COUNT(*) AS c FROM mo_musteri_sevkiyat
            WHERE aktif=1 AND durum IN ({ph_e})
              AND DATE(COALESCE(sevk_tarihi, olusturma_tarihi)) = DATE(?)
            """,
            _SEVK_EDILDI + (t,),
        ).fetchone()['c'] or 0)

        bekleyen_adet = int(con.execute(
            f"SELECT COUNT(*) AS c FROM mo_musteri_sevkiyat WHERE aktif=1 AND durum IN ({ph_b})",
            _SEVK_BEKLEYEN,
        ).fetchone()['c'] or 0)

        # bekleyen kg: hazirlaniyor/yukleniyor kalemleri
        bekleyen_kg = 0.0
        if _table_exists(con, 'mo_musteri_sevkiyat_kalem'):
            row = con.execute(
                f"""
                SELECT ROUND(COALESCE(SUM(k.miktar_kg),0),3) AS kg
                FROM mo_musteri_sevkiyat_kalem k
                JOIN mo_musteri_sevkiyat s ON s.id = k.sevkiyat_id
                WHERE s.aktif=1 AND s.durum IN ({ph_b})
                """,
                _SEVK_BEKLEYEN,
            ).fetchone()
            bekleyen_kg = _num(row['kg'] if row else 0)

        hazir_adet = int(con.execute(
            "SELECT COUNT(*) AS c FROM mo_musteri_sevkiyat WHERE aktif=1 AND durum='HAZIRLANIYOR'"
        ).fetchone()['c'] or 0)

        # operasyon servisi ile acik siparis kg (varsa)
        acik_siparis_kg = None
        try:
            from modules.nexgen.mo_sevkiyat_operasyon_service import operasyon_ozet
            oz = operasyon_ozet(con)
            acik_siparis_kg = _num(oz.get('acik_siparis_kg'))
            # sevke hazir kg (computed) — etiketle ayri
            sevke_hazir_kg = _num(oz.get('bugun_sevke_hazir_kg'))
            sevke_hazir_siparis = int(oz.get('sevke_hazir_siparis') or 0)
        except Exception:
            sevke_hazir_kg = None
            sevke_hazir_siparis = None
            warnings.append('shipment.operasyon_ozet unavailable')

        data = {
            'bugun_sevk': _kg_block(bugun_kg),
            'bugun_sevkiyat_adet': bugun_adet,
            'ay_sevk': _kg_block(ay_kg),
            'bekleyen_kg': round(bekleyen_kg, 3),
            'bekleyen_adet': bekleyen_adet,
            'hazirlanan_adet': hazir_adet,
            'sevke_hazir_kg': sevke_hazir_kg,
            'sevke_hazir_siparis': sevke_hazir_siparis,
            'acik_siparis_kg': acik_siparis_kg,
            'arac_bekliyor_available': False,  # guvenilir alan yok
            'filters': {
                'sevk_edildi_durum': list(_SEVK_EDILDI),
                'bekleyen_durum': list(_SEVK_BEKLEYEN),
            },
        }
        return _section_ok(data)
    except Exception as e:
        warnings.append('shipment: ' + type(e).__name__)
        return _section_err(str(e))


def _arge(con, warnings: List[str]) -> Dict[str, Any]:
    try:
        data = {
            'onayli_renk': None,
            'bekleyen_renk': None,
            'onayli_rf': None,
            'bekleyen_rf': None,
            'aktif_recete': None,
            'bekleyen_numune': None,
            'devam_eden_numune': None,
            'revizyonda': None,
            'kritik_stok': None,
            'kritik_stok_available': False,
            'filters': {},
        }
        if _table_exists(con, 'nexgen_rf_renk'):
            data['onayli_rf'] = int(con.execute(
                "SELECT COUNT(*) AS c FROM nexgen_rf_renk WHERE aktif=1 AND durum='ONAYLI'"
            ).fetchone()['c'] or 0)
            # Renk karti = RF renk master (ayri bekleyen durum yoksa gizle)
            data['onayli_renk'] = data['onayli_rf']
            bek = con.execute(
                """
                SELECT COUNT(*) AS c FROM nexgen_rf_renk
                WHERE aktif=1 AND UPPER(COALESCE(durum,'')) NOT IN ('ONAYLI','IPTAL','REDDEDILDI','PASIF')
                """
            ).fetchone()
            data['bekleyen_rf'] = int(bek['c'] or 0)
            data['bekleyen_renk'] = data['bekleyen_rf']
            data['filters']['rf_onayli'] = list(_RF_ONAYLI)

        if _table_exists(con, 'nexgen_uretim_varyant'):
            ph = ','.join(['?'] * len(_RECETE_AKTIF))
            data['aktif_recete'] = int(con.execute(
                f"""
                SELECT COUNT(*) AS c FROM nexgen_uretim_varyant
                WHERE COALESCE(aktif,1)=1 AND recete_durum IN ({ph})
                """,
                _RECETE_AKTIF,
            ).fetchone()['c'] or 0)
            data['filters']['recete_aktif'] = list(_RECETE_AKTIF)

        if _table_exists(con, 'nexgen_numune_talep'):
            ph_b = ','.join(['?'] * len(_NUMUNE_BEKLEYEN))
            data['bekleyen_numune'] = int(con.execute(
                f"SELECT COUNT(*) AS c FROM nexgen_numune_talep WHERE durum IN ({ph_b})",
                _NUMUNE_BEKLEYEN,
            ).fetchone()['c'] or 0)
            data['devam_eden_numune'] = int(con.execute(
                "SELECT COUNT(*) AS c FROM nexgen_numune_talep WHERE durum='CALISILIYOR'"
            ).fetchone()['c'] or 0)
            data['revizyonda'] = int(con.execute(
                "SELECT COUNT(*) AS c FROM nexgen_numune_talep WHERE durum='REVIZYONDA'"
            ).fetchone()['c'] or 0)
            data['filters']['numune_bekleyen'] = list(_NUMUNE_BEKLEYEN)

        # Kritik stok: son hareket sonraki_stok <= kritik_stok
        if _table_exists(con, 'nexgen_stok_kart') and _table_exists(con, 'nexgen_stok_hareket'):
            row = con.execute(
                """
                SELECT COUNT(*) AS c FROM (
                  SELECT sk.id,
                         sk.kritik_stok,
                         (
                           SELECT h.sonraki_stok FROM nexgen_stok_hareket h
                           WHERE h.stok_kart_id = sk.id
                           ORDER BY h.id DESC LIMIT 1
                         ) AS stok
                  FROM nexgen_stok_kart sk
                  WHERE COALESCE(sk.aktif,1)=1
                    AND COALESCE(sk.kritik_stok,0) > 0
                ) t
                WHERE t.stok IS NOT NULL AND t.stok <= t.kritik_stok
                """
            ).fetchone()
            data['kritik_stok'] = int(row['c'] or 0)
            data['kritik_stok_available'] = True

        return _section_ok(data)
    except Exception as e:
        warnings.append('arge: ' + type(e).__name__)
        return _section_err(str(e))


def _chain(con, today: date, warnings: List[str]) -> Dict[str, Any]:
    try:
        t = _ymd(today)
        steps = []

        def add(key, label, value, note):
            steps.append({
                'key': key, 'label': label,
                'value': int(value or 0), 'note': note,
            })

        acik_sip = 0
        if _table_exists(con, 'nexgen_planlama_siparis'):
            ph = ','.join(['?'] * len(_SIPARIS_ACIK))
            acik_sip = con.execute(
                f"SELECT COUNT(*) AS c FROM nexgen_planlama_siparis WHERE durum IN ({ph})",
                _SIPARIS_ACIK,
            ).fetchone()['c']
        add('siparis', 'Sipariş', acik_sip, 'Açık sipariş')

        aktif_plan = 0
        if _table_exists(con, 'nexgen_uretim_plan'):
            ph = ','.join(['?'] * len(_PLAN_AKTIF))
            aktif_plan = con.execute(
                f"SELECT COUNT(*) AS c FROM nexgen_uretim_plan WHERE durum IN ({ph})",
                _PLAN_AKTIF,
            ).fetchone()['c']
        add('plan', 'Plan', aktif_plan, 'Aktif üretim planı')

        aktif_batch = 0
        if _table_exists(con, 'nexgen_uretim_batch'):
            ph = ','.join(['?'] * len(_BATCH_AKTIF))
            aktif_batch = con.execute(
                f"SELECT COUNT(*) AS c FROM nexgen_uretim_batch WHERE durum IN ({ph})",
                _BATCH_AKTIF,
            ).fetchone()['c']
        add('batch', 'Batch', aktif_batch, 'Açık batch')

        acik_parca = 0
        uretimde = 0
        if _table_exists(con, 'nexgen_uretim_parca'):
            ph = ','.join(['?'] * len(_PARCA_ACIK))
            acik_parca = con.execute(
                f"SELECT COUNT(*) AS c FROM nexgen_uretim_parca WHERE durum IN ({ph})",
                _PARCA_ACIK,
            ).fetchone()['c']
            uretimde = con.execute(
                "SELECT COUNT(*) AS c FROM nexgen_uretim_parca WHERE durum='DEVAM'"
            ).fetchone()['c']
        add('alt_emir', 'Alt Emir', acik_parca, 'Açık alt emir')
        add('uretimde', 'Üretimde', uretimde, 'DEVAM alt emir')

        biten_batch = 0
        if _table_exists(con, 'nexgen_uretim_batch'):
            biten_batch = con.execute(
                "SELECT COUNT(*) AS c FROM nexgen_uretim_batch WHERE durum='BITTI'"
            ).fetchone()['c']
        add('tamamlandi', 'Tamamlandı', biten_batch, 'Tamamlanan batch')

        sevk_sip = 0
        if _table_exists(con, 'mo_musteri_sevkiyat'):
            ph = ','.join(['?'] * len(_SEVK_EDILDI))
            sevk_sip = con.execute(
                f"""
                SELECT COUNT(DISTINCT siparis_id) AS c
                FROM mo_musteri_sevkiyat
                WHERE aktif=1 AND durum IN ({ph})
                  AND DATE(COALESCE(sevk_tarihi, olusturma_tarihi)) = DATE(?)
                """,
                _SEVK_EDILDI + (t,),
            ).fetchone()['c']
        add('sevk', 'Sevk', sevk_sip, 'Bugün sevk sipariş')

        return _section_ok({'steps': steps})
    except Exception as e:
        warnings.append('chain: ' + type(e).__name__)
        return _section_err(str(e))


def _recent_events(con, today: date, warnings: List[str]) -> Dict[str, Any]:
    """Read-only UNION ALL olay listesi — yeni event tablosu yok."""
    try:
        parts = []
        params: List[Any] = []

        # Batch BITTI icin guvenilir bitis zamani yok → olay listesine alinmaz
        if _table_exists(con, 'nexgen_uretim_parca'):
            parts.append(
                """
                SELECT 'alt_emir_tamamlandi' AS event_type,
                       bitis_zamani AS event_time,
                       'Alt emir tamamlandı' AS title,
                       COALESCE(parca_no, batch_kodu, '') AS subtitle,
                       COALESCE(parca_no, '') AS reference_code,
                       NULL AS cari,
                       0 AS amount_kg_plan,
                       COALESCE(uretilen_kg, 0) AS amount_kg,
                       'nexgen_uretim_parca' AS source
                FROM nexgen_uretim_parca
                WHERE durum = 'BITTI'
                  AND bitis_zamani IS NOT NULL
                """
            )
        if _table_exists(con, 'mo_musteri_sevkiyat') and _table_exists(con, 'mo_musteri_sevkiyat_kalem'):
            parts.append(
                """
                SELECT 'sevkiyat' AS event_type,
                       COALESCE(s.tamamlanma_tarihi, s.guncelleme_tarihi, s.olusturma_tarihi) AS event_time,
                       'Sevkiyat gerçekleştirildi' AS title,
                       COALESCE(s.sevkiyat_no, '') AS subtitle,
                       COALESCE(s.sevkiyat_no, CAST(s.id AS TEXT)) AS reference_code,
                       COALESCE(c.unvan, CAST(s.cari_id AS TEXT)) AS cari,
                       0 AS amount_kg_plan,
                       COALESCE((
                         SELECT SUM(k.miktar_kg) FROM mo_musteri_sevkiyat_kalem k
                         WHERE k.sevkiyat_id = s.id
                       ), 0) AS amount_kg,
                       'mo_musteri_sevkiyat' AS source
                FROM mo_musteri_sevkiyat s
                LEFT JOIN nexgen_cari c ON c.id = s.cari_id
                WHERE s.aktif=1 AND s.durum IN ('SEVK_EDILDI','TESLIM_EDILDI','TAMAMLANDI')
                  AND COALESCE(s.tamamlanma_tarihi, s.guncelleme_tarihi, s.olusturma_tarihi) IS NOT NULL
                """
            )
        if _table_exists(con, 'nexgen_rf_renk'):
            parts.append(
                """
                SELECT 'rf_onay' AS event_type,
                       COALESCE(onay_tarihi, olusturma_tarihi) AS event_time,
                       'RF onaylandı' AS title,
                       COALESCE(rf_kod, ad, '') AS subtitle,
                       COALESCE(rf_kod, CAST(id AS TEXT)) AS reference_code,
                       NULL AS cari,
                       0 AS amount_kg_plan,
                       0 AS amount_kg,
                       'nexgen_rf_renk' AS source
                FROM nexgen_rf_renk
                WHERE durum = 'ONAYLI' AND COALESCE(onay_tarihi, olusturma_tarihi) IS NOT NULL
                """
            )
        if _table_exists(con, 'nexgen_numune_talep'):
            parts.append(
                """
                SELECT 'numune' AS event_type,
                       COALESCE(guncelleme_tarihi, olusturma_tarihi) AS event_time,
                       'Numune güncellendi' AS title,
                       COALESCE(talep_kodu, '') AS subtitle,
                       COALESCE(talep_kodu, CAST(id AS TEXT)) AS reference_code,
                       NULL AS cari,
                       0 AS amount_kg_plan,
                       0 AS amount_kg,
                       'nexgen_numune_talep' AS source
                FROM nexgen_numune_talep
                WHERE durum IN ('ONAYLANDI','CALISILIYOR')
                  AND COALESCE(guncelleme_tarihi, olusturma_tarihi) IS NOT NULL
                """
            )
        if _table_exists(con, 'nexgen_rf_kullanim'):
            parts.append(
                """
                SELECT 'uretim_basladi' AS event_type,
                       olusturma_tarihi AS event_time,
                       'Üretim kaydı' AS title,
                       COALESCE(tablet_session_id, CAST(id AS TEXT)) AS subtitle,
                       COALESCE(tablet_session_id, CAST(id AS TEXT)) AS reference_code,
                       NULL AS cari,
                       0 AS amount_kg_plan,
                       COALESCE(miktar_kg, 0) AS amount_kg,
                       'nexgen_rf_kullanim' AS source
                FROM nexgen_rf_kullanim
                WHERE aktif=1 AND olusturma_tarihi IS NOT NULL
                """
            )

        if not parts:
            return _section_ok([])

        sql = " UNION ALL ".join(parts) + " ORDER BY event_time DESC LIMIT 40"
        rows = con.execute(sql).fetchall()
        seen = set()
        events = []
        for r in rows:
            key = (r['event_type'], r['reference_code'], str(r['event_time'])[:16])
            if key in seen:
                continue
            seen.add(key)
            et = r['event_time']
            if not et:
                continue
            events.append({
                'event_type': r['event_type'],
                'event_time': str(et)[:19],
                'title': r['title'],
                'subtitle': r['subtitle'] or '',
                'reference_code': r['reference_code'] or '',
                'cari': r['cari'],
                'amount_kg': round(_num(r['amount_kg']), 3),
                'source': r['source'],
            })
            if len(events) >= 10:
                break
        return _section_ok(events)
    except Exception as e:
        warnings.append('events: ' + type(e).__name__)
        return _section_err(str(e))


def get_nexgen_ana_ozet(today: Optional[date] = None) -> Dict[str, Any]:
    """Tek aggregator response."""
    t0 = time.perf_counter()
    today = today or date.today()
    warnings: List[str] = []
    sources = [
        'nexgen_rf_kullanim',
        'nexgen_uretim_batch',
        'nexgen_uretim_parca',
        'nexgen_uretim_plan',
        'nexgen_planlama_siparis',
        'mo_musteri_sevkiyat',
        'nexgen_rf_renk',
        'nexgen_numune_talep',
        'nexgen_uretim_varyant',
        'nexgen_stok_kart',
    ]

    con = None
    try:
        con = _connect()
        production = _production(con, today, warnings)
        planning = _planning(con, warnings)
        shipment = _shipment(con, today, warnings)
        arge = _arge(con, warnings)
        chain = _chain(con, today, warnings)
        company = _company_distribution(con, today, warnings)
        product = _product_distribution(con, today, warnings)
        events = _recent_events(con, today, warnings)
    except Exception as e:
        return {
            'ok': False,
            'error': str(e),
            'generated_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            'warnings': warnings + [traceback.format_exc(limit=2)],
        }
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {
        'ok': True,
        'generated_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'period': {
            'today': _ymd(today),
            'month_start': _ymd(today.replace(day=1)),
            'week_start': _ymd(today - timedelta(days=6)),
        },
        'production': production,
        'planning': planning,
        'shipment': shipment,
        'arge': arge,
        'chain': chain,
        'company_distribution': company,
        'product_distribution': product,
        'recent_events': events,
        'sources': sources,
        'warnings': warnings,
        'elapsed_ms': elapsed_ms,
        'db_path_basename': os.path.basename(_DB_PATH),
    }
