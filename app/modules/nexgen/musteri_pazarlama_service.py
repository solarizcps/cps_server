# -*- coding: utf-8 -*-
"""MÜŞTERİ OPERASYONU ana ekran — operasyon özeti."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from modules.nexgen.cari_sorumlu_service import get_kullanici_cari_kapsami, load_kullanici_yetkileri
from modules.nexgen.mo_gorusme_config import SIPARIS_ZIYARET_ESIK_GUN, TABLO
from modules.nexgen.mo_gorusme_service import (
    bugunun_gorusme_sayaclari,
    can_mo_gorusme_yaz,
    gorusme_oneri_kaynaklari,
    son_gorusme_ozet_map,
    son_gorusmeler_grup,
)
from modules.nexgen.mo_siparis_talep_service import mo_siparis_payload_unpack
from modules.nexgen.mo_tahsilat_plan_service import (
    beklenen_tutar_hesapla,
    plan_durum_etiket,
    plan_hatirlatma_grubu,
    tahsilat_kural_etiket,
)
from modules.nexgen.mo_surec_service import (
    numune_asama,
    numune_timeline,
    siparis_asama,
    siparis_timeline,
    tahmini_tamamlanma_gun,
)

_NUMUNE_ACIK = (
    'YENI_TALEP', 'TASLAK', 'BEKLEYEN_NUMUNE', 'CALISILIYOR',
    'REVIZYONDA', 'FERHAT_TESTINDE', 'ONAY_BEKLIYOR',
    'REVIZYON_ISTENDI', 'ONAYLANDI',
)
_NUMUNE_SONUC_GELDI = ('ONAY_BEKLIYOR', 'FERHAT_TESTINDE')
_SIPARIS_ONAY_BEKLEYEN = ('ONAY_BEKLIYOR',)
_SIPARIS_REVIZYON = ('REVIZYON',)
_SIPARIS_RED = ('REDDEDILDI',)
_SIPARIS_ONAYLANDI = ('ONAYLANDI',)
_SIPARIS_URETIM_BEKLEYEN = ('MPR_BEKLIYOR', 'PLANLAMAYA_HAZIR')
_SIPARIS_ALINABILIR = ('TASLAK', 'REVIZYON')
_RISK_NORMAL = frozenset({'', 'NORMAL', 'NONE', 'NONEY', 'YOK'})


def _tablo_var(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _in_ph(ids: list[int]) -> tuple[str, list]:
    if not ids:
        return '0', []
    ph = ','.join(['?'] * len(ids))
    return ph, ids


def _gun_farki(tarih_str: str | None) -> int:
    if not tarih_str:
        return 0
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            dt = datetime.strptime(str(tarih_str)[:19], fmt)
            return max(0, (datetime.now() - dt).days)
        except ValueError:
            continue
    return 0


def _renk_goster(row: dict) -> str:
    if (row.get('renk_tipi') or '').upper() == 'YENI':
        yr = (row.get('yeni_renk_aciklama') or '').strip()
        return f'Yeni renk' + (f' — {yr}' if yr else '')
    rk = (row.get('renk_kodu') or row.get('yeni_renk_aciklama') or '').strip()
    return rk or '—'


def _risk_metin(raw: str | None) -> str | None:
    if not raw:
        return None
    s = str(raw).strip().upper()
    if s in _RISK_NORMAL:
        return None
    return str(raw).strip()


def _riskli_cari_ids(con: sqlite3.Connection, cari_ids: list[int]) -> set[int]:
    riskli_ids: set[int] = set()
    if not _tablo_var(con, 'nexgen_planlama_siparis') or not cari_ids:
        return riskli_ids
    c_ph, _ = _in_ph(cari_ids)
    rows = con.execute(
        f"""
        SELECT ps.cari_id, ps.onay_snapshot_json, ps.talep_referansi
        FROM nexgen_planlama_siparis ps
        WHERE ps.cari_id IN ({c_ph})
        ORDER BY ps.id DESC
        LIMIT 500
        """,
        cari_ids,
    ).fetchall()
    seen: set[int] = set()
    for r in rows:
        cid = int(r['cari_id'])
        if cid in seen:
            continue
        seen.add(cid)
        risk = None
        if r['onay_snapshot_json']:
            try:
                risk = json.loads(r['onay_snapshot_json']).get('risk_sonucu')
            except Exception:
                pass
        if risk is None and r['talep_referansi']:
            ref = str(r['talep_referansi'])
            for prefix in ('__PZM_V3__', '__PZM_V2__', '__PZM_V'):
                if ref.startswith(prefix):
                    try:
                        risk = json.loads(ref[len(prefix):]).get('risk_sonucu')
                    except Exception:
                        pass
                    break
        if _risk_metin(risk):
            riskli_ids.add(cid)
    return riskli_ids


def _cari_unvan_map(con: sqlite3.Connection, cari_ids: list[int]) -> dict[int, dict]:
    if not cari_ids:
        return {}
    ph, params = _in_ph(cari_ids)
    rows = con.execute(
        f"SELECT id, cari_kod, unvan FROM nexgen_cari WHERE aktif=1 AND id IN ({ph})",
        params,
    ).fetchall()
    return {int(r['id']): {'cari_kod': r['cari_kod'], 'unvan': r['unvan']} for r in rows}


def _is_gorevi(baslik: str, sayi: int) -> dict[str, Any]:
    return {'baslik': baslik, 'sayi': int(sayi or 0)}


def _akilli_oneriler(
    con: sqlite3.Connection,
    cari_ids: list[int],
    riskli_ids: set[int],
    cari_map: dict[int, dict],
) -> list[dict[str, Any]]:
    if not cari_ids:
        return []
    oneriler: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()

    def _ekle_surec(
        cid: int,
        tip: str,
        *,
        surec_tipi: str,
        surec_asama: str,
        neden: str,
        aksiyon: str,
        aksiyon_tip: str = 'surec_ac',
        tahmini_gun: int | None = None,
        timeline: list | None = None,
        kaynak: str | None = None,
        kaynak_id: int | None = None,
    ):
        key = (cid, tip, surec_asama)
        if key in seen:
            return
        seen.add(key)
        info = cari_map.get(cid) or {}
        oneriler.append({
            'cari_id': cid,
            'musteri': info.get('unvan') or '—',
            'tip': tip,
            'surec_tipi': surec_tipi,
            'surec_asama': surec_asama,
            'neden': neden,
            'aksiyon': aksiyon,
            'aksiyon_tip': aksiyon_tip,
            'tahmini_gun': tahmini_gun,
            'timeline': timeline or [],
            'kaynak': kaynak,
            'kaynak_id': kaynak_id,
        })

    for g in gorusme_oneri_kaynaklari(con, cari_ids, cari_map):
        _ekle_surec(
            g['cari_id'], g['tip'],
            surec_tipi=g.get('surec_tipi') or 'Ziyaret',
            surec_asama=g.get('surec_asama') or 'Takip',
            neden=g['neden'],
            aksiyon=g.get('aksiyon') or 'Görüşme Kaydet',
            aksiyon_tip='gorusme',
        )

    for cid in sorted(riskli_ids):
        _ekle_surec(
            cid, 'risk',
            surec_tipi='Tahsilat',
            surec_asama='Riskli müşteri',
            neden='Tahsilat riski değerlendirilmeli',
            aksiyon='Süreci Aç',
        )

    if _tablo_var(con, 'nexgen_numune_talep'):
        n_ph = ','.join(['?'] * len(_NUMUNE_ACIK))
        c_ph, _ = _in_ph(cari_ids)
        rows = con.execute(
            f"""
            SELECT nt.id, nt.cari_id, nt.durum, nt.olusturma_tarihi, nt.arge_test_id
            FROM nexgen_numune_talep nt
            WHERE nt.aktif=1 AND nt.durum IN ({n_ph}) AND nt.cari_id IN ({c_ph})
            ORDER BY nt.id DESC
            """,
            [*_NUMUNE_ACIK, *cari_ids],
        ).fetchall()
        arge_map: dict[int, str] = {}
        arge_saha: dict[int, int] = {}
        arge_ids = [int(r['arge_test_id']) for r in rows if r['arge_test_id']]
        if arge_ids and _tablo_var(con, 'nexgen_arge_test'):
            a_ph, a_params = _in_ph(arge_ids)
            for ar in con.execute(
                f"SELECT id, durum, saha_testi_gerekli_mi FROM nexgen_arge_test WHERE id IN ({a_ph})",
                a_params,
            ).fetchall():
                arge_map[int(ar['id'])] = ar['durum']
                arge_saha[int(ar['id'])] = int(ar['saha_testi_gerekli_mi'] or 0)

        numune_cari: set[int] = set()
        for r in rows:
            cid = int(r['cari_id'])
            if cid in numune_cari:
                continue
            numune_cari.add(cid)
            durum = (r['durum'] or '').upper()
            arge_id = int(r['arge_test_id']) if r['arge_test_id'] else None
            arge_d = arge_map.get(arge_id) if arge_id else None
            saha = arge_saha.get(arge_id, 0) if arge_id else 0
            bekleme = _gun_farki(r['olusturma_tarihi'])
            surec = numune_asama(durum, arge_d, arge_test_id=arge_id)
            neden = (
                'Numune hazırlandı — müşteriyi bilgilendir'
                if surec['surec_asama'] == 'Hazır'
                else f"Numune {bekleme} gündür süreçte"
                if bekleme > 0
                else 'Açık numune talebi var'
            )
            _ekle_surec(
                cid, 'numune' if durum != 'ONAYLANDI' else 'numune_hazir',
                surec_tipi=surec['surec_tipi'],
                surec_asama=surec['surec_asama'],
                neden=neden,
                aksiyon=surec['aksiyon'],
                aksiyon_tip=surec['aksiyon_tip'],
                tahmini_gun=tahmini_tamamlanma_gun(bekleme, durum),
                timeline=numune_timeline(durum, arge_d, saha),
                kaynak='numune',
                kaynak_id=int(r['id']),
            )

    if _tablo_var(con, 'nexgen_planlama_siparis'):
        c_ph, _ = _in_ph(cari_ids)
        rows = con.execute(
            f"""
            SELECT ps.id, ps.cari_id, ps.durum, ps.olusturma_tarihi
            FROM nexgen_planlama_siparis ps
            WHERE (ps.siparis_no LIKE 'PZM-%' OR ps.kaynak_modul='MUSTERI_OPERASYONU' OR ps.siparis_no LIKE 'MO-S-%')
              AND ps.cari_id IN ({c_ph})
              AND ps.durum IN ('TASLAK','REVIZYON','ONAY_BEKLIYOR','ONAYLANDI',
                               'MPR_BEKLIYOR','PLANLAMAYA_HAZIR','URETIMDE','TAMAMLANDI')
            ORDER BY ps.id DESC
            """,
            cari_ids,
        ).fetchall()
        siparis_cari: set[int] = set()
        for r in rows:
            cid = int(r['cari_id'])
            if cid in siparis_cari:
                continue
            durum = (r['durum'] or '').upper()
            if durum in _SIPARIS_ALINABILIR:
                tip = 'siparis_firsat'
            elif durum in _SIPARIS_ONAY_BEKLEYEN:
                tip = 'siparis_onay'
            elif durum in _SIPARIS_ONAYLANDI:
                tip = 'siparis_onaylandi'
            elif durum in _SIPARIS_URETIM_BEKLEYEN:
                tip = 'siparis_plan'
            else:
                tip = 'siparis'
            siparis_cari.add(cid)
            surec = siparis_asama(durum)
            neden_map = {
                'TASLAK': 'Yeni sipariş fırsatı',
                'REVIZYON': 'Sipariş revizyon bekliyor',
                'ONAY_BEKLIYOR': 'Merkezi onay sürecinde',
                'ONAYLANDI': 'Sipariş onaylandı',
            }
            _ekle_surec(
                cid, tip,
                surec_tipi=surec['surec_tipi'],
                surec_asama=surec['surec_asama'],
                neden=neden_map.get(durum, 'Açık sipariş süreci'),
                aksiyon=surec['aksiyon'],
                aksiyon_tip=surec['aksiyon_tip'],
                timeline=siparis_timeline(durum),
                kaynak='siparis',
                kaynak_id=int(r['id']),
            )

        rows2 = con.execute(
            f"""
            SELECT ps.cari_id, MAX(ps.olusturma_tarihi) AS son_tarih
            FROM nexgen_planlama_siparis ps
            WHERE (ps.siparis_no LIKE 'PZM-%' OR ps.kaynak_modul='MUSTERI_OPERASYONU' OR ps.siparis_no LIKE 'MO-S-%')
              AND ps.cari_id IN ({c_ph})
            GROUP BY ps.cari_id
            """,
            cari_ids,
        ).fetchall()
        for r in rows2:
            gun = _gun_farki(r['son_tarih'])
            if gun >= SIPARIS_ZIYARET_ESIK_GUN:
                _ekle_surec(
                    int(r['cari_id']), 'siparis_eski',
                    surec_tipi='Ziyaret',
                    surec_asama='Ziyaret gerekli',
                    neden=f'Müşteri {gun} gündür ziyaret edilmedi',
                    aksiyon='Görüşme Kaydet',
                    aksiyon_tip='gorusme',
                )

    return oneriler[:12]


def _numune_bekleyenler(con: sqlite3.Connection, cari_ids: list[int], cari_map: dict) -> list[dict]:
    if not cari_ids or not _tablo_var(con, 'nexgen_numune_talep'):
        return []
    n_ph = ','.join(['?'] * len(_NUMUNE_ACIK))
    c_ph, _ = _in_ph(cari_ids)
    rows = con.execute(
        f"""
        SELECT nt.id, nt.talep_kodu, nt.durum, nt.cari_id, nt.olusturma_tarihi,
               nt.renk_tipi, nt.renk_kodu, nt.yeni_renk_aciklama,
               nt.vedat_sonuc, nt.vedat_ferhat_testi, nt.arge_test_id,
               nt.aday_firma_adi, nt.musteri_tipi
        FROM nexgen_numune_talep nt
        WHERE nt.aktif=1 AND nt.durum IN ({n_ph}) AND nt.cari_id IN ({c_ph})
        ORDER BY nt.olusturma_tarihi ASC
        LIMIT 40
        """,
        [*_NUMUNE_ACIK, *cari_ids],
    ).fetchall()

    arge_map: dict[int, str] = {}
    arge_saha: dict[int, int] = {}
    arge_ids = [int(r['arge_test_id']) for r in rows if r['arge_test_id']]
    if arge_ids and _tablo_var(con, 'nexgen_arge_test'):
        a_ph, a_params = _in_ph(arge_ids)
        for ar in con.execute(
            f"SELECT id, durum, saha_testi_gerekli_mi FROM nexgen_arge_test WHERE id IN ({a_ph})",
            a_params,
        ).fetchall():
            arge_map[int(ar['id'])] = ar['durum']
            arge_saha[int(ar['id'])] = int(ar['saha_testi_gerekli_mi'] or 0)

    liste: list[dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        cid = int(r['cari_id']) if r['cari_id'] else None
        if cid and cid in cari_map:
            musteri = cari_map[cid]['unvan']
        elif (r['musteri_tipi'] or '').upper() == 'ADAY':
            musteri = (r['aday_firma_adi'] or '—').strip() or '—'
        else:
            musteri = '—'
        arge_id = int(r['arge_test_id']) if r['arge_test_id'] else None
        arge_d = arge_map.get(arge_id) if arge_id else None
        saha = arge_saha.get(arge_id, 0) if arge_id else 0
        durum_kod = (r['durum'] or '').upper()
        surec = numune_asama(durum_kod, arge_d, arge_test_id=arge_id)
        bekleme = _gun_farki(r['olusturma_tarihi'])
        liste.append({
            'talep_kodu': r['talep_kodu'],
            'cari_id': cid,
            'musteri': musteri,
            'surec_tipi': surec['surec_tipi'],
            'surec_asama': surec['surec_asama'],
            'aksiyon': surec.get('aksiyon') or 'Süreci Aç',
            'durum_kod': r['durum'],
            'bekleme_gun': bekleme,
            'tahmini_gun': tahmini_tamamlanma_gun(bekleme, durum_kod),
            'renk': _renk_goster(row),
            'timeline': numune_timeline(durum_kod, arge_d, saha),
        })
    return liste


def _siparis_satir(r, cari_map: dict) -> dict[str, Any]:
    cid = int(r['cari_id']) if r['cari_id'] else None
    surec = siparis_asama(r['durum'])
    return {
        'siparis_no': r['siparis_no'],
        'cari_id': cid,
        'musteri': (cari_map.get(cid) or {}).get('unvan', '—') if cid else '—',
        'durum': r['durum'],
        'surec_tipi': surec['surec_tipi'],
        'surec_asama': surec['surec_asama'],
        'tarih': (r['olusturma_tarihi'] or '')[:10] or '—',
        'timeline': siparis_timeline(r['durum']),
    }


def _siparis_bekleyenler(con: sqlite3.Connection, cari_ids: list[int], cari_map: dict) -> dict[str, list]:
    bos = {'onay_bekleyen': [], 'revizyon_bekleyen': [], 'red_kayit': [], 'onaylandi': [], 'uretim_bekleyen': []}
    if not cari_ids or not _tablo_var(con, 'nexgen_planlama_siparis'):
        return bos
    c_ph, _ = _in_ph(cari_ids)

    def _liste(durumlar: tuple[str, ...], limit: int = 20) -> list[dict]:
        d_ph = ','.join(['?'] * len(durumlar))
        rows = con.execute(
            f"""
            SELECT siparis_no, cari_id, durum, olusturma_tarihi
            FROM nexgen_planlama_siparis
            WHERE (siparis_no LIKE 'PZM-%' OR kaynak_modul='MUSTERI_OPERASYONU' OR siparis_no LIKE 'MO-S-%')
              AND durum IN ({d_ph}) AND cari_id IN ({c_ph})
            ORDER BY id DESC LIMIT ?
            """,
            [*durumlar, *cari_ids, limit],
        ).fetchall()
        return [_siparis_satir(r, cari_map) for r in rows]

    return {
        'onay_bekleyen': _liste(_SIPARIS_ONAY_BEKLEYEN),
        'revizyon_bekleyen': _liste(_SIPARIS_REVIZYON),
        'red_kayit': _liste(_SIPARIS_RED),
        'onaylandi': _liste(_SIPARIS_ONAYLANDI),
        'uretim_bekleyen': _liste(_SIPARIS_URETIM_BEKLEYEN),
    }


def _musteri_kartlari(
    con: sqlite3.Connection,
    cari_ids: list[int],
    riskli_ids: set[int],
    kullanici_id: int,
    yk: set[str],
) -> list[dict[str, Any]]:
    if not cari_ids:
        return []
    ph, params = _in_ph(cari_ids)
    rows = con.execute(
        f"""
        SELECT c.id, c.cari_kod, c.unvan
        FROM nexgen_cari c
        WHERE c.aktif=1 AND c.id IN ({ph})
        ORDER BY c.unvan
        LIMIT 60
        """,
        params,
    ).fetchall()

    son_gorusme_map = son_gorusme_ozet_map(con, cari_ids)
    gecmis_map = son_gorusmeler_grup(con, cari_ids, 3)

    kartlar: list[dict[str, Any]] = []
    for r in rows:
        cid = int(r['id'])
        son_siparis = None
        son_numune = None
        vade = None
        if _tablo_var(con, 'nexgen_planlama_siparis'):
            son_siparis = con.execute(
                """
                SELECT siparis_no, durum, olusturma_tarihi, vade_gun, onay_snapshot_json, talep_referansi
                FROM nexgen_planlama_siparis
                WHERE cari_id=? AND siparis_no LIKE 'PZM-%'
                ORDER BY id DESC LIMIT 1
                """,
                (cid,),
            ).fetchone()
        if _tablo_var(con, 'nexgen_numune_talep'):
            son_numune = con.execute(
                """
                SELECT talep_kodu, durum, olusturma_tarihi
                FROM nexgen_numune_talep
                WHERE cari_id=? AND aktif=1
                ORDER BY id DESC LIMIT 1
                """,
                (cid,),
            ).fetchone()

        risk = None
        if cid in riskli_ids:
            risk = 'Riskli'
        elif son_siparis and son_siparis['onay_snapshot_json']:
            try:
                risk = _risk_metin(json.loads(son_siparis['onay_snapshot_json']).get('risk_sonucu'))
            except Exception:
                pass
        if son_siparis:
            vade = son_siparis['vade_gun']

        durum = son_siparis['durum'] if son_siparis and son_siparis['durum'] else None

        sg = son_gorusme_map.get(cid)
        son_gorusme_metin = None
        if sg:
            tarih = (sg.get('gorusme_tarihi') or '')[:10]
            son_gorusme_metin = f"{tarih} — {sg.get('gorusme_tipi')} ({sg.get('sonuc_tipi')})"

        gecmis = []
        for g in gecmis_map.get(cid, []):
            gecmis.append({
                'tarih': (g.get('gorusme_tarihi') or '')[:10],
                'tip': g.get('gorusme_tipi'),
                'sonuc': g.get('sonuc_tipi'),
                'not': (g.get('kisa_not') or '')[:80],
                'kullanici': g.get('kullanici_adi') or '—',
                'takip': (g.get('sonraki_takip_tarihi') or '')[:10] or None,
            })

        kartlar.append({
            'cari_id': cid,
            'cari_kod': r['cari_kod'],
            'unvan': r['unvan'],
            'son_siparis': (
                f"{son_siparis['siparis_no']} ({son_siparis['durum']})"
                if son_siparis else None
            ),
            'son_gorusme': son_gorusme_metin,
            'son_gorusmeler': gecmis,
            'numune': (
                f"{son_numune['talep_kodu']} ({son_numune['durum']})"
                if son_numune else None
            ),
            'risk': risk,
            'vade': f"{vade} gün" if vade not in (None, '') else None,
            'durum': durum,
            'gorusme_yazabilir': can_mo_gorusme_yaz(con, kullanici_id, cid, yk),
        })
    return kartlar


def _sayac(con, sql: str, params: list) -> int:
    try:
        row = con.execute(sql, params).fetchone()
        return int(row[0] or 0)
    except Exception:
        return 0


_GUN_KISA = ('Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz')
_AY_KISA = ('Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara')
_ONCELIK_SIRA = {
    'takip_bugun': 0,
    'risk': 1,
    'numune_hazir': 2,
    'siparis_onaylandi': 3,
    'siparis_onay': 4,
    'numune': 5,
    'gorusme_esik': 6,
    'takip_hafta': 7,
    'siparis_eski': 8,
    'siparis_plan': 9,
    'siparis_firsat': 10,
    'siparis': 11,
}


def _tarih_parcala(tarih_str: str | None) -> date | None:
    if not tarih_str:
        return None
    for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(str(tarih_str)[:19], fmt).date()
        except ValueError:
            continue
    return None


def _tarih_goster(dt: date) -> dict[str, str]:
    return {
        'gun_kisa': _GUN_KISA[dt.weekday()],
        'tarih_kisa': f'{dt.day} {_AY_KISA[dt.month - 1]}',
    }


def _tutar_metin(tutar: float | int | None) -> str | None:
    if tutar in (None, ''):
        return None
    try:
        val = float(tutar)
    except (TypeError, ValueError):
        return None
    if val <= 0:
        return None
    return f'{val:,.0f} TL'.replace(',', '.')


def _oncelikli_isler_flat(oneriler: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    sirali = sorted(
        oneriler,
        key=lambda o: (_ONCELIK_SIRA.get(o.get('tip') or '', 99), o.get('musteri') or ''),
    )
    out: list[dict[str, Any]] = []
    seen_cari: set[int] = set()
    for o in sirali:
        cid = o.get('cari_id')
        if cid is not None and int(cid) in seen_cari:
            continue
        if cid is not None:
            seen_cari.add(int(cid))
        alt = o.get('neden') or ''
        if o.get('tahmini_gun') is not None and o['tahmini_gun'] > 0:
            alt = f"{o['tahmini_gun']} gündür"
        item = dict(o)
        item['alt_metin'] = alt
        item['is_durum'] = f"{o.get('surec_tipi') or 'İş'} · {o.get('surec_asama') or '—'}"
        tip = (o.get('surec_tipi') or 'İş')[:1].upper()
        item['tip_isaret'] = {'T': '₺', 'N': '◆', 'Z': '◎', 'S': '▣'}.get(tip, '•')
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _asama_grup_ozet(items: list[dict[str, Any]]) -> str:
    sayac: dict[str, int] = {}
    for it in items:
        a = it.get('surec_asama') or '—'
        sayac[a] = sayac.get(a, 0) + 1
    return ' · '.join(f"{n} {a}" for a, n in sorted(sayac.items(), key=lambda x: -x[1])[:3])


def _numune_gruplu_ozet(liste: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    buckets: dict[int, list[dict[str, Any]]] = {}
    for n in liste:
        cid = n.get('cari_id')
        if not cid:
            continue
        buckets.setdefault(int(cid), []).append(n)
    out: list[dict[str, Any]] = []
    for cid, items in sorted(buckets.items(), key=lambda x: -len(x[1])):
        out.append({
            'cari_id': cid,
            'musteri': items[0].get('musteri') or '—',
            'toplam': len(items),
            'asama_ozet': _asama_grup_ozet(items),
            'timeline': items[0].get('timeline'),
            'aksiyon': items[0].get('aksiyon') or 'Detayı Aç',
        })
        if len(out) >= limit:
            break
    return out


def _siparis_gruplu_ozet(bekleyenler: dict[str, list], limit: int = 4) -> list[dict[str, Any]]:
    all_s: list[dict[str, Any]] = (
        list(bekleyenler.get('onay_bekleyen') or [])
        + list(bekleyenler.get('revizyon_bekleyen') or [])
        + list(bekleyenler.get('red_kayit') or [])
        + list(bekleyenler.get('onaylandi') or [])
        + list(bekleyenler.get('uretim_bekleyen') or [])
    )
    buckets: dict[int, list[dict[str, Any]]] = {}
    for s in all_s:
        cid = s.get('cari_id')
        if not cid:
            continue
        buckets.setdefault(int(cid), []).append(s)
    out: list[dict[str, Any]] = []
    for cid, items in sorted(buckets.items(), key=lambda x: -len(x[1])):
        out.append({
            'cari_id': cid,
            'musteri': items[0].get('musteri') or '—',
            'toplam': len(items),
            'asama_ozet': _asama_grup_ozet(items),
            'timeline': items[0].get('timeline'),
            'aksiyon': 'Detayı Aç',
        })
        if len(out) >= limit:
            break
    return out


def _hafta_ziyaretleri(
    con: sqlite3.Connection,
    cari_ids: list[int],
    cari_map: dict[int, dict],
) -> list[dict[str, Any]]:
    if not cari_ids or not _tablo_var(con, TABLO):
        return []
    today = date.today()
    week_end = today + timedelta(days=7 - today.weekday())
    ph = ','.join(['?'] * len(cari_ids))
    rows = con.execute(
        f"""
        SELECT g.cari_id, g.gorusme_tipi, g.gorusme_tarihi, g.sonraki_takip_tarihi,
               g.cek_alim_tarihi, g.kisa_not, g.sonuc_tipi
        FROM {TABLO} g
        WHERE g.cari_id IN ({ph}) AND g.aktif=1
          AND (
            (g.sonraki_takip_tarihi >= ? AND g.sonraki_takip_tarihi <= ?)
            OR (g.gorusme_tipi='Ziyaret' AND substr(g.gorusme_tarihi,1,10) >= ? AND substr(g.gorusme_tarihi,1,10) <= ?)
            OR (g.cek_alim_tarihi >= ? AND g.cek_alim_tarihi <= ?)
          )
        ORDER BY COALESCE(g.sonraki_takip_tarihi, g.cek_alim_tarihi, substr(g.gorusme_tarihi,1,10))
        LIMIT 5
        """,
        [
            *cari_ids,
            today.isoformat(), week_end.isoformat(),
            today.isoformat(), week_end.isoformat(),
            today.isoformat(), week_end.isoformat(),
        ],
    ).fetchall()

    seen: set[tuple[int, str]] = set()
    ziyaretler: list[dict[str, Any]] = []
    for r in rows:
        cid = int(r['cari_id'])
        plan = (
            (r['sonraki_takip_tarihi'] or '')[:10]
            or (r['cek_alim_tarihi'] or '')[:10]
            or (r['gorusme_tarihi'] or '')[:10]
        )
        if not plan:
            continue
        key = (cid, plan)
        if key in seen:
            continue
        seen.add(key)
        dt = _tarih_parcala(plan)
        if not dt:
            continue
        info = cari_map.get(cid) or {}
        amac = (r['kisa_not'] or r['sonuc_tipi'] or 'Ziyaret / takip')[:60]
        if (r['cek_alim_tarihi'] or '')[:10] == plan:
            amac = 'Tahsilat ziyareti'
        elif (r['sonraki_takip_tarihi'] or '')[:10] == plan:
            amac = (r['sonuc_tipi'] or r['kisa_not'] or 'Takip görüşmesi')[:60]
        saat = None
        gt = r['gorusme_tarihi'] or ''
        if len(gt) >= 16 and (r['gorusme_tipi'] or '') == 'Ziyaret' and gt[:10] == plan:
            saat = gt[11:16]
        z = {
            'cari_id': cid,
            'musteri': info.get('unvan') or '—',
            'tarih': plan,
            'amac': amac,
            'saat': saat or '—',
            **_tarih_goster(dt),
        }
        ziyaretler.append(z)
    return ziyaretler


def _tahsilat_siparis_planlari(
    con: sqlite3.Connection,
    cari_ids: list[int],
    cari_map: dict[int, dict],
) -> list[dict[str, Any]]:
    if not cari_ids or not _tablo_var(con, 'nexgen_planlama_siparis'):
        return []
    cols = [c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()]
    if 'tahsilat_kurali' not in cols:
        return []
    ph = ','.join(['?'] * len(cari_ids))
    rows = con.execute(
        f"""
        SELECT id, siparis_no, cari_id, cari_unvan, tahsilat_kurali, tahsilat_gun_sayisi,
               planlanan_tahsilat_tarihi, tahsilat_durumu, tahsilat_sozu, tahsilat_notu,
               anlasma_birim_fiyat, anlasma_para_birimi, talep_referansi, durum
        FROM nexgen_planlama_siparis
        WHERE kaynak_modul='MUSTERI_OPERASYONU'
          AND cari_id IN ({ph})
          AND tahsilat_kurali IS NOT NULL AND tahsilat_kurali != ''
          AND durum NOT IN ('REDDEDILDI','IPTAL','TASLAK')
          AND (tahsilat_durumu IS NULL OR tahsilat_durumu NOT IN ('TAMAMLANDI'))
        ORDER BY planlanan_tahsilat_tarihi, id DESC
        LIMIT 40
        """,
        cari_ids,
    ).fetchall()
    today = date.today()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        mo = mo_siparis_payload_unpack(d.get('talep_referansi')) or {}
        tutar, tahmini = beklenen_tutar_hesapla(d, mo)
        tutar_txt = _tutar_metin(tutar)
        if tutar_txt and tahmini:
            tutar_txt = f'{tutar_txt} (Tahmini)'
        grup = plan_hatirlatma_grubu(d.get('planlanan_tahsilat_tarihi'), d.get('tahsilat_durumu'))
        durum_metin = plan_durum_etiket(grup, None)
        if grup == 'sevk_bekleyen':
            kural = (d.get('tahsilat_kurali') or '').upper()
            gun = d.get('tahsilat_gun_sayisi')
            if kural == 'SEVKTEN_SONRA' and gun:
                durum_metin = f'Sevkten {gun} gün sonra · Gerçek sevk bekleniyor'
            elif kural == 'SEVKTE':
                durum_metin = 'Gerçek sevk bekleniyor'
            elif kural == 'SEVKTEN_ONCE':
                durum_metin = 'Sevk öncesi tahsilat bekleniyor'
        dt = _tarih_parcala(d.get('planlanan_tahsilat_tarihi'))
        fark = (dt - today).days if dt else None
        if grup == 'gecikti':
            durum, durum_kisa = 'gecikti', 'Gecikti'
        elif grup == 'bugun':
            durum, durum_kisa = 'bugun', 'Bugün alınacak'
        elif grup == 'yaklasan':
            durum, durum_kisa = 'yaklasiyor', 'Yaklaşıyor'
        elif grup in ('kayit_girildi', 'muhasebe_bekliyor', 'tamamlandi'):
            durum, durum_kisa = grup, durum_metin
        elif grup == 'sevk_bekleyen':
            durum, durum_kisa = 'sevk_bekliyor', durum_metin
        else:
            durum, durum_kisa = 'planli', durum_metin
        if grup == 'gecikti':
            grup_out = 'geciken'
        elif grup == 'bugun':
            grup_out = 'bugun'
        elif grup in ('yaklasan', 'planli'):
            grup_out = 'yaklasan' if grup == 'yaklasan' else 'sozler'
        elif grup == 'sevk_bekleyen':
            grup_out = 'sevk_bekleyen'
        else:
            grup_out = 'diger'
        info = cari_map.get(int(d['cari_id'] or 0)) or {}
        not_metin = (d.get('tahsilat_sozu') or d.get('tahsilat_notu') or tahsilat_kural_etiket(d.get('tahsilat_kurali')))[:50]
        out.append({
            'kaynak': 'siparis_plan',
            'cari_id': int(d['cari_id']),
            'musteri': info.get('unvan') or d.get('cari_unvan') or '—',
            'tahsilat_sozu_tarihi': d.get('planlanan_tahsilat_tarihi'),
            'tutar_metin': tutar_txt,
            'beklenen_tutar': tutar,
            'not': not_metin or 'Sipariş tahsilat planı',
            'durum': durum,
            'durum_metin': durum_kisa,
            'grup': grup_out,
            'gun_fark': fark if fark is not None else 999,
            'siparis_id': d['id'],
            'siparis_no': d.get('siparis_no'),
        })
    return out


def _tahsilat_takibi(
    con: sqlite3.Connection,
    cari_ids: list[int],
    cari_map: dict[int, dict],
) -> list[dict[str, Any]]:
    """Pazarlamacının planladığı tahsilat sözü tarihi — çek banka vadesi değil."""
    if not cari_ids or not _tablo_var(con, TABLO):
        return []
    today = date.today()
    ph = ','.join(['?'] * len(cari_ids))
    rows = con.execute(
        f"""
        SELECT g.cari_id, g.cek_alim_tarihi, g.tahmini_siparis_tutari,
               g.kisa_not, g.gorusme_tarihi, g.sonuc_tipi
        FROM {TABLO} g
        WHERE g.cari_id IN ({ph}) AND g.aktif=1
          AND g.cek_alim_tarihi IS NOT NULL AND g.cek_alim_tarihi != ''
        ORDER BY g.cek_alim_tarihi
        LIMIT 30
        """,
        cari_ids,
    ).fetchall()

    seen: set[tuple[int, str]] = set()
    kayitlar: list[dict[str, Any]] = []
    for r in rows:
        soz = (r['cek_alim_tarihi'] or '')[:10]
        if not soz:
            continue
        cid = int(r['cari_id'])
        key = (cid, soz)
        if key in seen:
            continue
        seen.add(key)
        dt = _tarih_parcala(soz)
        if not dt:
            continue
        fark = (dt - today).days
        if fark < 0:
            durum, durum_metin, grup = 'gecikti', 'Gecikti', 'geciken'
        elif fark == 0:
            durum, durum_metin, grup = 'bugun', 'Bugün alınacak', 'bugun'
        elif fark <= 7:
            durum, durum_metin, grup = 'yaklasiyor', 'Yaklaşıyor', 'yaklasan'
        else:
            durum, durum_metin, grup = 'soz', 'Söz verildi', 'sozler'
        info = cari_map.get(cid) or {}
        sevk = (r['gorusme_tarihi'] or '')[:10]
        not_metin = (r['kisa_not'] or '')[:50]
        if sevk and not not_metin:
            not_metin = f'Sevkiyat {sevk}'
        kayitlar.append({
            'kaynak': 'gorusme',
            'cari_id': cid,
            'musteri': info.get('unvan') or '—',
            'tahsilat_sozu_tarihi': soz,
            'tutar_metin': _tutar_metin(r['tahmini_siparis_tutari']),
            'beklenen_tutar': r['tahmini_siparis_tutari'],
            'not': not_metin or 'Tahsilat sözü',
            'durum': durum,
            'durum_metin': durum_metin,
            'grup': grup,
            'gun_fark': fark,
        })
    plan_kayitlari = _tahsilat_siparis_planlari(con, cari_ids, cari_map)
    for pk in plan_kayitlari:
        soz = pk.get('tahsilat_sozu_tarihi')
        if soz:
            key = (pk['cari_id'], soz[:10])
            if key in seen:
                continue
            seen.add(key)
        kayitlar.append(pk)
    return kayitlar


def dashboard_ozet(con, kullanici_id: int, yk: set[str] | None = None) -> dict[str, Any]:
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    kapsam = get_kullanici_cari_kapsami(con, kullanici_id, yk)
    cari_ids = kapsam['cari_id_listesi']

    bugunun = {
        'bugun_cek_alinacak': _is_gorevi('Bugün çek alınacak', 0),
        'bugun_ziyaret': _is_gorevi('Bugün ziyaret', 0),
        'bugun_aranacak': _is_gorevi('Bugün aranacak', 0),
        'onay_bekleyen': _is_gorevi('Onay bekleyen', 0),
        'riskli_musteri': _is_gorevi('Riskli müşteri', 0),
        'numune_sonucu_geldi': _is_gorevi('Numune sonucu geldi', 0),
        'siparis_onaylandi': _is_gorevi('Sipariş onaylandı', 0),
    }

    if not cari_ids and not kapsam['tumunu_gorebilir_mi']:
        return {
            'bugunun_isleri': bugunun,
            'akilli_oneriler': [],
            'oncelikli_isler': [],
            'oncelikli_isler_tum': [],
            'hafta_ziyaretleri': [],
            'tahsilat_takibi': [],
            'numune_gruplu': [],
            'siparis_gruplu': [],
            'genel_bugun_sayi': 0,
            'musteriler': [],
            'numune_bekleyenler': [],
            'siparis_bekleyenler': {'onay_bekleyen': [], 'revizyon_bekleyen': [], 'red_kayit': [], 'onaylandi': [], 'uretim_bekleyen': []},
            'kapsam_bos': True,
        }

    cari_map = _cari_unvan_map(con, cari_ids)
    riskli_ids = _riskli_cari_ids(con, cari_ids)
    bugunun['riskli_musteri']['sayi'] = len(riskli_ids)

    if cari_ids:
        c_ph, _ = _in_ph(cari_ids)

        if _tablo_var(con, 'onay_talep'):
            ob = _sayac(con, f"""
                SELECT COUNT(*) FROM onay_talep ot
                WHERE ot.aktif=1 AND ot.durum IN ('BEKLIYOR','BEKLETILDI')
                  AND ot.talep_tipi='SATIS_SIPARISI' AND ot.cari_id IN ({c_ph})
            """, cari_ids)
            bugunun['onay_bekleyen']['sayi'] = ob

        if _tablo_var(con, 'nexgen_numune_talep'):
            n_ph = ','.join(['?'] * len(_NUMUNE_SONUC_GELDI))
            ns = _sayac(con, f"""
                SELECT COUNT(*) FROM nexgen_numune_talep nt
                WHERE nt.aktif=1 AND nt.durum IN ({n_ph}) AND nt.cari_id IN ({c_ph})
            """, [*_NUMUNE_SONUC_GELDI, *cari_ids])
            bugunun['numune_sonucu_geldi']['sayi'] = ns

        if _tablo_var(con, 'nexgen_planlama_siparis'):
            s_ph = ','.join(['?'] * len(_SIPARIS_ONAYLANDI))
            so = _sayac(con, f"""
                SELECT COUNT(*) FROM nexgen_planlama_siparis ps
                WHERE ps.siparis_no LIKE 'PZM-%' AND ps.durum IN ({s_ph})
                  AND ps.cari_id IN ({c_ph})
            """, [*_SIPARIS_ONAYLANDI, *cari_ids])
            bugunun['siparis_onaylandi']['sayi'] = so
            if bugunun['onay_bekleyen']['sayi'] == 0:
                o_ph = ','.join(['?'] * len(_SIPARIS_ONAY_BEKLEYEN))
                bugunun['onay_bekleyen']['sayi'] = _sayac(con, f"""
                    SELECT COUNT(*) FROM nexgen_planlama_siparis ps
                    WHERE ps.siparis_no LIKE 'PZM-%' AND ps.durum IN ({o_ph})
                      AND ps.cari_id IN ({c_ph})
                """, [*_SIPARIS_ONAY_BEKLEYEN, *cari_ids])

        gs = bugunun_gorusme_sayaclari(con, cari_ids)
        bugunun['bugun_cek_alinacak']['sayi'] = max(
            bugunun['bugun_cek_alinacak']['sayi'], gs['bugun_cek']
        )
        bugunun['bugun_ziyaret']['sayi'] = max(
            bugunun['bugun_ziyaret']['sayi'], gs['bugun_ziyaret']
        )
        bugunun['bugun_aranacak']['sayi'] = max(
            bugunun['bugun_aranacak']['sayi'], gs['bugun_aranacak']
        )

    musteriler = _musteri_kartlari(con, cari_ids, riskli_ids, kullanici_id, yk)
    oneriler = _akilli_oneriler(con, cari_ids, riskli_ids, cari_map)
    numune_bek = _numune_bekleyenler(con, cari_ids, cari_map)
    siparis_bek = _siparis_bekleyenler(con, cari_ids, cari_map)
    genel_bugun = sum(v.get('sayi', 0) for v in bugunun.values())
    return {
        'bugunun_isleri': bugunun,
        'akilli_oneriler': oneriler,
        'oncelikli_isler': _oncelikli_isler_flat(oneriler, 4),
        'oncelikli_isler_tum': _oncelikli_isler_flat(oneriler, 12),
        'hafta_ziyaretleri': _hafta_ziyaretleri(con, cari_ids, cari_map),
        'tahsilat_takibi': _tahsilat_takibi(con, cari_ids, cari_map),
        'numune_gruplu': _numune_gruplu_ozet(numune_bek, 4),
        'siparis_gruplu': _siparis_gruplu_ozet(siparis_bek, 4),
        'genel_bugun_sayi': genel_bugun,
        'musteriler': musteriler,
        'numune_bekleyenler': numune_bek,
        'siparis_bekleyenler': siparis_bek,
        'kapsam_bos': False,
    }
