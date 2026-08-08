# -*- coding: utf-8 -*-
"""MÜŞTERİ OPERASYONU ana ekran — operasyon özeti."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from modules.nexgen.cari_sorumlu_service import (
    get_musteri_operasyonu_kapsami,
    get_pazarlama_cari_kapsami,
    load_kullanici_yetkileri,
)
from modules.nexgen.mo_gorusme_config import GORUSME_GUN_ESIK, SIPARIS_ZIYARET_ESIK_GUN, TABLO
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
    atanmamis_ids: set[int] | None = None,
) -> list[dict[str, Any]]:
    if not cari_ids:
        return []
    atanmamis_ids = atanmamis_ids or set()
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
        atanmamis = cid in atanmamis_ids
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
            'entity_type': 'CARI',
            'cari_id': cid,
            'aday_id': None,
            'cari_kod': r['cari_kod'],
            'unvan': r['unvan'],
            'atanmamis': atanmamis,
            'sorumlu_etiket': 'Atanmamış' if atanmamis else None,
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
            'olusturan_adi': None,
            'yetkili_adi': None,
            'telefon': None,
            'gorusme_yazabilir': can_mo_gorusme_yaz(con, kullanici_id, cid, yk),
        })
    return kartlar


def _aday_kartlari(
    con: sqlite3.Connection,
    kullanici_id: int,
    yk: set[str],
) -> list[dict[str, Any]]:
    from modules.nexgen.musteri_aday_service import DURUM_ADAY, aday_listele, can_aday_yaz
    from modules.nexgen.mo_gorusme_config import TABLO as GORUSME_TABLO

    if not _tablo_var(con, 'nexgen_musteri_aday'):
        return []
    yazabilir = can_aday_yaz(con, kullanici_id, yk)
    kartlar: list[dict[str, Any]] = []
    for a in aday_listele(con, kullanici_id, yk, durum=DURUM_ADAY, limit=60):
        aid = int(a['id'])
        son_gorusme_metin = None
        gecmis: list[dict[str, Any]] = []
        if _tablo_var(con, GORUSME_TABLO):
            rows = con.execute(
                f"""
                SELECT gorusme_tarihi, gorusme_tipi, sonuc_tipi, kisa_not
                FROM {GORUSME_TABLO}
                WHERE musteri_aday_id=? AND aktif=1
                ORDER BY gorusme_tarihi DESC, id DESC
                LIMIT 3
                """,
                (aid,),
            ).fetchall()
            if rows:
                sg = rows[0]
                son_gorusme_metin = (
                    f"{(sg['gorusme_tarihi'] or '')[:10]} — "
                    f"{sg['gorusme_tipi']} ({sg['sonuc_tipi']})"
                )
                for g in rows:
                    gecmis.append({
                        'tarih': (g['gorusme_tarihi'] or '')[:10],
                        'tip': g['gorusme_tipi'],
                        'sonuc': g['sonuc_tipi'],
                        'not': (g['kisa_not'] or '')[:80],
                    })
        kisa = []
        if a.get('yetkili_adi'):
            kisa.append(str(a['yetkili_adi']))
        if a.get('telefon'):
            kisa.append(str(a['telefon']))
        kartlar.append({
            'entity_type': 'ADAY',
            'cari_id': None,
            'aday_id': aid,
            'cari_kod': None,
            'unvan': a.get('firma_adi') or '—',
            'atanmamis': False,
            'sorumlu_etiket': None,
            'son_siparis': None,
            'son_gorusme': son_gorusme_metin,
            'son_gorusmeler': gecmis,
            'numune': None,
            'risk': None,
            'vade': None,
            'durum': a.get('durum') or DURUM_ADAY,
            'olusturan_adi': a.get('olusturan_adi') or '—',
            'yetkili_adi': a.get('yetkili_adi'),
            'telefon': a.get('telefon'),
            'sehir': a.get('sehir'),
            'kisa_bilgi': ' · '.join(kisa) if kisa else None,
            'gorusme_yazabilir': yazabilir,
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


def _ajanda_zorunlu_gate_items(
    con,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> list[dict[str, Any]]:
    try:
        from modules.nexgen.mo_ajanda_service import ajanda_zorunlu_sonuc_listele
        kayitlar = ajanda_zorunlu_sonuc_listele(con, kullanici_id, yk)
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    for k in kayitlar:
        plan_tarih = k.get('tarih') or ''
        plan_saat = k.get('saat') or '—'
        bek = int(k.get('bekleyen_gun') or 0)
        items.append({
            'ajanda_id': k.get('id'),
            'cari_id': k.get('cari_id'),
            'musteri': k.get('musteri') or '-',
            'tarih': plan_tarih,
            'saat': plan_saat,
            'gorusme_tipi': k.get('gorusme_tipi') or '',
            'plan_notu': k.get('plan_notu') or '',
            'bekleyen_gun': bek,
            'bekleyen_metin': f'{bek} gündür' if bek else '—',
            'durum_gorunum': k.get('durum_gorunum') or 'ZORUNLU_SONUC_BEKLIYOR',
            'durum_etiket': k.get('durum_etiket') or 'Zorunlu Sonuç Bekliyor',
        })
    return items


def _ajanda_bugun_isler(
    con,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> dict[str, Any]:
    """Bugun Benim Isim — Ajanda V1 ozeti."""
    try:
        from modules.nexgen.mo_ajanda_service import ajanda_ozet_bugun
        oz = ajanda_ozet_bugun(con, kullanici_id, yk)
    except Exception:
        return {'mod': 'bos', 'kayitlar': [], 'kayitlar_tum': [], 'bos_mesaj': None}

    items: list[dict[str, Any]] = []
    for k in oz.get('kayitlar') or []:
        dg = (k.get('durum_gorunum') or 'PLANLANDI').upper()
        aksiyon = 'Görüşme Sonucunu Gir' if dg in ('SONUC_BEKLIYOR', 'ZORUNLU_SONUC_BEKLIYOR') else 'Görüşme Aç'
        plan_tarih = k.get('tarih') or ''
        plan_saat = k.get('saat') or '—'
        neden = f"{plan_tarih} {plan_saat} — {k.get('gorusme_tipi') or ''}".strip(' —')
        items.append({
            'tip': 'ajanda',
            'cari_id': k.get('cari_id'),
            'musteri': k.get('musteri') or '-',
            'saat': plan_saat,
            'gorusme_tipi': k.get('gorusme_tipi') or '',
            'plan_notu': k.get('plan_notu') or '',
            'ajanda_id': k.get('id'),
            'durum_gorunum': k.get('durum_gorunum') or 'PLANLANDI',
            'durum_etiket': k.get('durum_etiket') or 'Planlandı',
            'neden': neden,
            'surec_asama': k.get('durum_etiket') or 'Planlandı',
            'aksiyon_tip': 'gorusme',
            'aksiyon': aksiyon,
        })
    return {
        'mod': oz.get('mod') or 'bos',
        'kayitlar': items[:4],
        'kayitlar_tum': items,
        'bos_mesaj': oz.get('bos_mesaj'),
    }


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
        item['is_turu'] = o.get('surec_tipi') or o.get('baslik') or 'İş'
        item['durum_ozet'] = o.get('surec_asama') or o.get('neden') or '—'
        item['bekleme_ozet'] = alt or '—'
        item['is_durum'] = f"{item['is_turu']} · {item['durum_ozet']}"
        tip = (o.get('surec_tipi') or 'İş')[:1].upper()
        item['tip_isaret'] = {'T': '₺', 'N': '◆', 'Z': '◎', 'S': '▣'}.get(tip, '•')
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _asama_etiketler(items: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    """Açık süreç özetini kısa etiketlere böler (UI okunabilirlik)."""
    sayac: dict[str, int] = {}
    for it in items:
        a = (it.get('surec_asama') or '—').strip() or '—'
        sayac[a] = sayac.get(a, 0) + 1
    return [
        {'adet': n, 'etiket': a}
        for a, n in sorted(sayac.items(), key=lambda x: -x[1])[:limit]
    ]


def _asama_grup_ozet(items: list[dict[str, Any]]) -> str:
    return ' · '.join(f"{x['adet']} {x['etiket']}" for x in _asama_etiketler(items))


def _numune_gruplu_ozet(liste: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    buckets: dict[int, list[dict[str, Any]]] = {}
    for n in liste:
        cid = n.get('cari_id')
        if not cid:
            continue
        buckets.setdefault(int(cid), []).append(n)
    out: list[dict[str, Any]] = []
    for cid, items in sorted(buckets.items(), key=lambda x: -len(x[1])):
        etiketler = _asama_etiketler(items)
        son = items[-1] if items else {}
        out.append({
            'cari_id': cid,
            'musteri': items[0].get('musteri') or '—',
            'toplam': len(items),
            'asama_ozet': _asama_grup_ozet(items),
            'asama_etiketler': etiketler,
            'son_durum': son.get('surec_asama') or '—',
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
        etiketler = _asama_etiketler(items)
        son = items[-1] if items else {}
        out.append({
            'cari_id': cid,
            'musteri': items[0].get('musteri') or '—',
            'toplam': len(items),
            'asama_ozet': _asama_grup_ozet(items),
            'asama_etiketler': etiketler,
            'son_durum': son.get('surec_asama') or '—',
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


def dashboard_ozet(
    con,
    kullanici_id: int,
    yk: set[str] | None = None,
    *,
    karar_seen_ts: str | None = None,
) -> dict[str, Any]:
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    kapsam = get_musteri_operasyonu_kapsami(con, kullanici_id, yk)
    cari_ids = kapsam['cari_id_listesi']
    atanmamis_ids = set(kapsam.get('atanmamis_cari_ids') or [])

    bugunun = {
        'bugun_cek_alinacak': _is_gorevi('Bugün çek alınacak', 0),
        'bugun_ziyaret': _is_gorevi('Bugün ziyaret', 0),
        'bugun_aranacak': _is_gorevi('Takip Bekleyen', 0),
        'onay_bekleyen': _is_gorevi('Yeni Kararlar', 0),
        'riskli_musteri': _is_gorevi('Riskli müşteri', 0),
        'numune_sonucu_geldi': _is_gorevi('Numune Süreçleri', 0),
        'siparis_onaylandi': _is_gorevi('Sipariş Süreçleri', 0),
    }

    if not cari_ids and not kapsam['tumunu_gorebilir_mi']:
        from modules.nexgen.musteri_aday_service import aday_havuz_liste
        aday_kartlar = aday_havuz_liste(con, kullanici_id, yk)
        aj_is = _ajanda_bugun_isler(con, kullanici_id, yk)
        zorunlu_gate = _ajanda_zorunlu_gate_items(con, kullanici_id, yk)
        return {
            'bugunun_isleri': bugunun,
            'akilli_oneriler': [],
            'oncelikli_isler': aj_is['kayitlar'],
            'oncelikli_isler_tum': aj_is['kayitlar_tum'],
            'ajanda_ozet_mod': aj_is['mod'],
            'ajanda_bos_mesaj': aj_is['bos_mesaj'],
            'zorunlu_sonuc_gate': zorunlu_gate,
            'hafta_ziyaretleri': [],
            'tahsilat_takibi': [],
            'numune_gruplu': [],
            'siparis_gruplu': [],
            'genel_bugun_sayi': 0,
            'musteriler': [],
            'adaylar': aday_kartlar,
            'numune_bekleyenler': [],
            'siparis_bekleyenler': {'onay_bekleyen': [], 'revizyon_bekleyen': [], 'red_kayit': [], 'onaylandi': [], 'uretim_bekleyen': []},
            'kapsam_bos': not bool(aday_kartlar),
            'coklu_sorumlu_cari_ids': kapsam.get('coklu_sorumlu_cari_ids') or [],
        }

    cari_map = _cari_unvan_map(con, cari_ids)
    riskli_ids = _riskli_cari_ids(con, cari_ids)
    bugunun['riskli_musteri']['sayi'] = len(riskli_ids)

    if cari_ids:
        c_ph, _ = _in_ph(cari_ids)

        # Yeni Kararlar: yalnız okunmamış Onaylandı/Reddedildi (session seen)
        try:
            from modules.nexgen.onay_service import pazarlamaci_okunmamis_karar_sayisi
            bugunun['onay_bekleyen']['sayi'] = pazarlamaci_okunmamis_karar_sayisi(
                con, kullanici_id, karar_seen_ts,
            )
            bugunun['onay_bekleyen']['baslik'] = 'Yeni Kararlar'
        except Exception:
            bugunun['onay_bekleyen']['sayi'] = 0

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
        bugunun['bugun_aranacak']['baslik'] = 'Takip Bekleyen'

    musteriler = _musteri_kartlari(
        con, cari_ids, riskli_ids, kullanici_id, yk, atanmamis_ids=atanmamis_ids,
    )
    # Cariler ve adaylar karışmaz — payload entity_type kesin
    from modules.nexgen.musteri_aday_service import aday_havuz_liste
    adaylar = aday_havuz_liste(con, kullanici_id, yk)
    oneriler = _akilli_oneriler(con, cari_ids, riskli_ids, cari_map)
    aj_is = _ajanda_bugun_isler(con, kullanici_id, yk)
    zorunlu_gate = _ajanda_zorunlu_gate_items(con, kullanici_id, yk)
    numune_bek = _numune_bekleyenler(con, cari_ids, cari_map)
    siparis_bek = _siparis_bekleyenler(con, cari_ids, cari_map)
    # Ana şerit sayaçları = panel listeleri ile aynı sorgu politikası
    bugunun['numune_sonucu_geldi']['sayi'] = len(numune_bek)
    bugunun['numune_sonucu_geldi']['baslik'] = 'Numune Süreçleri'
    siparis_acik = sum(len(v or []) for v in (siparis_bek or {}).values())
    bugunun['siparis_onaylandi']['sayi'] = siparis_acik
    bugunun['siparis_onaylandi']['baslik'] = 'Sipariş Süreçleri'
    genel_bugun = (
        int(bugunun['bugun_aranacak'].get('sayi') or 0)
        + int(bugunun['onay_bekleyen'].get('sayi') or 0)
        + int(bugunun['numune_sonucu_geldi'].get('sayi') or 0)
        + int(bugunun['siparis_onaylandi'].get('sayi') or 0)
    )
    return {
        'bugunun_isleri': bugunun,
        'akilli_oneriler': oneriler,
        'oncelikli_isler': aj_is['kayitlar'],
        'oncelikli_isler_tum': aj_is['kayitlar_tum'],
        'ajanda_ozet_mod': aj_is['mod'],
        'ajanda_bos_mesaj': aj_is['bos_mesaj'],
        'zorunlu_sonuc_gate': zorunlu_gate,
        'hafta_ziyaretleri': _hafta_ziyaretleri(con, cari_ids, cari_map),
        'tahsilat_takibi': _tahsilat_takibi(con, cari_ids, cari_map),
        'numune_gruplu': _numune_gruplu_ozet(numune_bek, 4),
        'siparis_gruplu': _siparis_gruplu_ozet(siparis_bek, 4),
        'genel_bugun_sayi': genel_bugun,
        'musteriler': musteriler,
        'adaylar': adaylar,
        'numune_bekleyenler': numune_bek,
        'siparis_bekleyenler': siparis_bek,
        'kapsam_bos': False,
        'coklu_sorumlu_cari_ids': kapsam.get('coklu_sorumlu_cari_ids') or [],
    }


# ---------------------------------------------------------------------------
# ERHAN UI-3A — dashboard_v2: read-only finans/tahsilat/çek/üretim/KPI
# ---------------------------------------------------------------------------

def _v2_bakiye_ozet(con: sqlite3.Connection, cari_id: int) -> dict[str, Any]:
    """nexgen_cari → cari_eslestirme DOGRULANDI → Cari_Har compute_bakiye."""
    from modules.nexgen.cari360_finans_service import _legacy_ckod, _legacy_bakiye
    ckod = _legacy_ckod(con, cari_id)
    bak = _legacy_bakiye(con, ckod)
    if not bak.get('eslesme'):
        return {'eslesme': False, 'muhasebe_bakiye': None, 'bakiye_yonu': None,
                'son_hareket_tarihi': None, 'kaynak': None}
    raw = bak.get('bakiye')
    if raw is None:
        return {'eslesme': True, 'muhasebe_bakiye': None, 'bakiye_yonu': None,
                'son_hareket_tarihi': bak.get('son_islem'), 'kaynak': bak.get('kaynak')}
    try:
        b = float(raw)
    except (TypeError, ValueError):
        b = 0.0
    if b > 0.01:
        yon = 'BORC'
    elif b < -0.01:
        yon = 'ALACAK'
    else:
        yon = 'SIFIR'
    return {
        'eslesme': True,
        'muhasebe_bakiye': round(b, 2),
        'bakiye_yonu': yon,
        'son_hareket_tarihi': (bak.get('son_islem') or '')[:10] or None,
        'kaynak': bak.get('kaynak', 'Cari_Har'),
    }


def _v2_tahsilat_vade(
    con: sqlite3.Connection,
    cari_ids: list[int],
    today: date,
) -> tuple[list[dict], dict[str, Any]]:
    """mo_tahsilat_kayit → vade takvimi. NULL tarihleri takvime koyma."""
    if not cari_ids or not _tablo_var(con, 'mo_tahsilat_kayit'):
        return [], {'BUGUN': [], '1_2_GUN': [], '3_5_GUN': [], '6_7_GUN': [],
                    '8_10_GUN': [], 'VADESI_GECEN': [], 'TARIHI_YOK': []}

    ph, params = _in_ph(cari_ids)
    rows = con.execute(
        f"""SELECT id, cari_id, kayit_kodu, beklenen_tutar, alinan_tutar, kalan_tutar,
                   planlanan_tahsilat_tarihi, alinan_tarih, odeme_tipi, durum, olusturan_id
            FROM mo_tahsilat_kayit
            WHERE cari_id IN ({ph})
              AND COALESCE(aktif, 1)=1
              AND durum NOT IN ('IPTAL', 'TAMAMLANDI')
            ORDER BY planlanan_tahsilat_tarihi ASC, id ASC""",
        params,
    ).fetchall()

    kayitlar: list[dict] = []
    takvim: dict[str, list] = {
        'BUGUN': [], '1_2_GUN': [], '3_5_GUN': [], '6_7_GUN': [],
        '8_10_GUN': [], 'VADESI_GECEN': [], 'TARIHI_YOK': [],
    }

    for r in rows:
        tarih_str = r['planlanan_tahsilat_tarihi']
        tarih_d: date | None = None
        if tarih_str:
            try:
                tarih_d = date.fromisoformat(str(tarih_str)[:10])
            except ValueError:
                pass

        gecikme_gun: int | None = None
        vade_grup: str | None = None
        if tarih_d:
            delta = (today - tarih_d).days
            if today == tarih_d:
                vade_grup = 'BUGUN'
            elif today < tarih_d:
                gun = (tarih_d - today).days
                if gun <= 2:
                    vade_grup = '1_2_GUN'
                elif gun <= 5:
                    vade_grup = '3_5_GUN'
                elif gun <= 7:
                    vade_grup = '6_7_GUN'
                elif gun <= 10:
                    vade_grup = '8_10_GUN'
                else:
                    vade_grup = None
            else:
                gecikme_gun = delta
                vade_grup = 'VADESI_GECEN'
        else:
            vade_grup = 'TARIHI_YOK'

        kayit: dict = {
            'id': r['id'],
            'cari_id': r['cari_id'],
            'kayit_kodu': r['kayit_kodu'],
            'beklenen_tutar': r['beklenen_tutar'],
            'alinan_tutar': r['alinan_tutar'],
            'kalan_tutar': r['kalan_tutar'],
            'planlanan_tahsilat_tarihi': tarih_str,
            'odeme_tipi': r['odeme_tipi'],
            'durum': r['durum'],
            'gecikme_gun': gecikme_gun,
            'vade_grubu': vade_grup,
        }
        kayitlar.append(kayit)
        if vade_grup and vade_grup in takvim:
            tutar = r['kalan_tutar'] or r['beklenen_tutar'] or 0
            takvim[vade_grup].append({
                'cari_id': r['cari_id'],
                'kayit_kodu': r['kayit_kodu'],
                'tutar': tutar,
                'gecikme_gun': gecikme_gun,
                'tarih': tarih_str,
            })

    return kayitlar, takvim


def _v2_cek_sozu(
    con: sqlite3.Connection,
    cari_ids: list[int],
) -> list[dict]:
    """Operasyonel çek sözü — muhasebe çeki değil.
    Kaynak: musteri_operasyon_gorusme + nexgen_planlama_siparis.
    Gerçek çek no / banka bilgisi döndürülmez.
    """
    if not cari_ids:
        return []
    ph, params = _in_ph(cari_ids)
    sozler: list[dict] = []

    if _tablo_var(con, 'musteri_operasyon_gorusme'):
        rows = con.execute(
            f"""SELECT id, cari_id, gorusme_tarihi, cek_alim_tarihi,
                       cek_vade_gun, cek_adedi, odeme_tipi
                FROM musteri_operasyon_gorusme
                WHERE cari_id IN ({ph})
                  AND COALESCE(aktif, 1)=1
                  AND odeme_tipi='CEK'
                  AND cek_adedi > 0
                ORDER BY gorusme_tarihi DESC""",
            params,
        ).fetchall()
        for r in rows:
            sozler.append({
                'cari_id': r['cari_id'],
                'kaynak_tipi': 'GORUSME',
                'kaynak_id': r['id'],
                'cek_sozu_tarihi': (r['cek_alim_tarihi'] or r['gorusme_tarihi'] or '')[:10] or None,
                'planlanan_vade_gun': r['cek_vade_gun'],
                'cek_adedi': r['cek_adedi'],
                'not': 'Çek Sözü — muhasebe kaydı değil',
            })

    if _tablo_var(con, 'nexgen_planlama_siparis'):
        sip_cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)')}
        extra = ''
        if 'cek_teslim_tarihi' in sip_cols:
            extra += ', cek_teslim_tarihi'
        if 'cek_vadesi' in sip_cols:
            extra += ', cek_vadesi'
        rows2 = con.execute(
            f"""SELECT id, siparis_no, cari_id, odeme_tipi{extra}
                FROM nexgen_planlama_siparis
                WHERE cari_id IN ({ph})
                  AND (odeme_tipi='CEK' OR odeme_tipi='SENET')
                  AND durum NOT IN ('TASLAK','REDDEDILDI','IPTAL','REVIZYON')
                ORDER BY id DESC LIMIT 50""",
            params,
        ).fetchall()
        for r in rows2:
            teslim = r['cek_teslim_tarihi'] if 'cek_teslim_tarihi' in sip_cols else None
            vade = r['cek_vadesi'] if 'cek_vadesi' in sip_cols else None
            sozler.append({
                'cari_id': r['cari_id'],
                'kaynak_tipi': 'SIPARIS_PLANI',
                'kaynak_id': r['id'],
                'siparis_no': r['siparis_no'],
                'cek_sozu_tarihi': (teslim or '')[:10] or None,
                'planlanan_vade': (vade or '')[:10] or None,
                'odeme_tipi': r['odeme_tipi'],
                'not': 'Planlanan Çek — muhasebe kaydı değil',
            })

    return sozler


def _v2_numune_ozet(
    con: sqlite3.Connection,
    cari_ids: list[int],
    cari_map: dict[int, dict],
) -> list[dict]:
    """Açık numune talepleri — Erhan scope."""
    if not cari_ids or not _tablo_var(con, 'nexgen_numune_talep'):
        return []
    ph, params = _in_ph(cari_ids)
    _ACIK = (
        'YENI_TALEP', 'TASLAK', 'BEKLEYEN_NUMUNE', 'CALISILIYOR',
        'REVIZYONDA', 'FERHAT_TESTINDE', 'ONAY_BEKLIYOR',
        'REVIZYON_ISTENDI', 'ONAYLANDI',
    )
    n_ph = ','.join(['?'] * len(_ACIK))
    rows = con.execute(
        f"""SELECT nt.id, nt.cari_id, nt.talep_kodu, nt.durum,
                   nt.urun_tipi, nt.urun_adi, nt.urun_aciklama,
                   nt.renk_kodu, nt.yeni_renk_aciklama, nt.renk_tipi,
                   nt.olusturma_tarihi, nt.arge_test_id
            FROM nexgen_numune_talep nt
            WHERE nt.cari_id IN ({ph})
              AND nt.durum IN ({n_ph})
              AND COALESCE(nt.aktif, 1)=1
            ORDER BY nt.id DESC LIMIT 100""",
        [*params, *_ACIK],
    ).fetchall()

    # AR-GE durumu
    arge_map: dict[int, str] = {}
    arge_ids = [int(r['arge_test_id']) for r in rows if r['arge_test_id']]
    if arge_ids and _tablo_var(con, 'nexgen_arge_test'):
        a_ph = ','.join(['?'] * len(arge_ids))
        for ar in con.execute(
            f"SELECT id, durum FROM nexgen_arge_test WHERE id IN ({a_ph})", arge_ids
        ).fetchall():
            arge_map[int(ar['id'])] = ar['durum']

    sonuc: list[dict] = []
    for r in rows:
        cid = int(r['cari_id'])
        arge_d = arge_map.get(int(r['arge_test_id'])) if r['arge_test_id'] else None
        sonuc.append({
            'id': r['id'],
            'cari_id': cid,
            'cari_unvan': (cari_map.get(cid) or {}).get('unvan'),
            'talep_no': r['talep_kodu'],
            'durum': r['durum'],
            'arge_durum': arge_d,
            'urun_tipi': r['urun_tipi'],
            'urun_adi': r['urun_adi'],
            'renk': _renk_goster(dict(r)),
            'olusturma_tarihi': (r['olusturma_tarihi'] or '')[:10],
        })
    return sonuc


def _v2_siparis_uretim_sevk(
    con: sqlite3.Connection,
    cari_ids: list[int],
    cari_map: dict[int, dict],
) -> list[dict]:
    """nexgen_planlama_siparis → uretim_plan → sevkiyat özet.
    Cari360 geniş yetki gerektirmez.
    """
    if not cari_ids or not _tablo_var(con, 'nexgen_planlama_siparis'):
        return []
    ph, params = _in_ph(cari_ids)
    sip_rows = con.execute(
        f"""SELECT id, siparis_no, cari_id, durum, olusturma_tarihi,
                   termin_tarihi, musteri_termin
            FROM nexgen_planlama_siparis
            WHERE cari_id IN ({ph})
              AND durum NOT IN ('TASLAK', 'REDDEDILDI', 'IPTAL')
            ORDER BY id DESC LIMIT 200""",
        params,
    ).fetchall()
    if not sip_rows:
        return []

    sip_ids = [int(r['id']) for r in sip_rows]
    sip_ph = ','.join(['?'] * len(sip_ids))

    # Üretim planı durumu (son plan / sipariş başına)
    uretim_map: dict[int, str] = {}
    if _tablo_var(con, 'nexgen_uretim_plan'):
        u_rows = con.execute(
            f"""SELECT planlama_siparis_id, durum
                FROM nexgen_uretim_plan
                WHERE planlama_siparis_id IN ({sip_ph})
                ORDER BY id DESC""",
            sip_ids,
        ).fetchall()
        for ur in u_rows:
            sid = int(ur['planlama_siparis_id'])
            if sid not in uretim_map:
                uretim_map[sid] = ur['durum']

    # Sevkiyat durumu (son sevk / sipariş başına)
    sevk_map: dict[int, dict] = {}
    if _tablo_var(con, 'mo_musteri_sevkiyat'):
        sv_rows = con.execute(
            f"""SELECT siparis_id, durum, sevk_tarihi
                FROM mo_musteri_sevkiyat
                WHERE siparis_id IN ({sip_ph})
                  AND COALESCE(aktif, 1)=1
                ORDER BY sevk_tarihi DESC, id DESC""",
            sip_ids,
        ).fetchall()
        for sv in sv_rows:
            sid = int(sv['siparis_id'])
            if sid not in sevk_map:
                sevk_map[sid] = {'sevk_durum': sv['durum'], 'sevk_tarihi': sv['sevk_tarihi']}

    sonuc: list[dict] = []
    for r in sip_rows:
        sid = int(r['id'])
        cid = int(r['cari_id'])
        sv = sevk_map.get(sid, {})
        sonuc.append({
            'siparis_id': sid,
            'siparis_no': r['siparis_no'],
            'cari_id': cid,
            'cari_unvan': (cari_map.get(cid) or {}).get('unvan'),
            'siparis_durum': r['durum'],
            'siparis_tarihi': (r['olusturma_tarihi'] or '')[:10],
            'termin': (r['termin_tarihi'] or r['musteri_termin'] or '')[:10] or None,
            'uretim_durum': uretim_map.get(sid),
            'sevk_durum': sv.get('sevk_durum'),
            'sevk_tarihi': (sv.get('sevk_tarihi') or '')[:10] or None,
        })
    return sonuc


def _v2_bu_ay_kpi(
    con: sqlite3.Connection,
    cari_ids: list[int],
    today: date,
) -> dict[str, Any]:
    """Erhan'ın 13 carisi için bu ay KPI — yalnız gerçek aggregation."""
    ay_prefix = today.strftime('%Y-%m')
    if not cari_ids:
        return {}
    ph, params = _in_ph(cari_ids)

    def _agg(tablo: str, tarih_kol: str, extra_where: str = '') -> int | None:
        if not _tablo_var(con, tablo):
            return None
        try:
            n = con.execute(
                f"""SELECT COUNT(*) as n FROM {tablo}
                    WHERE cari_id IN ({ph})
                      AND strftime('%Y-%m', {tarih_kol}) = ?
                      {extra_where}""",
                [*params, ay_prefix],
            ).fetchone()['n']
            return int(n or 0)
        except Exception:
            return None

    gorusme_n = _agg('musteri_operasyon_gorusme', 'gorusme_tarihi',
                     "AND COALESCE(aktif,1)=1")
    numune_n = _agg('nexgen_numune_talep', 'olusturma_tarihi',
                    "AND COALESCE(aktif,1)=1")
    siparis_n = _agg('nexgen_planlama_siparis', 'olusturma_tarihi',
                     "AND durum NOT IN ('TASLAK','REDDEDILDI','IPTAL')")

    # Tahsilat alınan (ONAYLANDI, alinan_tarih bu ay)
    alinan_tahsilat = None
    if _tablo_var(con, 'mo_tahsilat_kayit'):
        try:
            row = con.execute(
                f"""SELECT COALESCE(SUM(alinan_tutar), 0) as toplam
                    FROM mo_tahsilat_kayit
                    WHERE cari_id IN ({ph})
                      AND durum='ONAYLANDI'
                      AND strftime('%Y-%m', alinan_tarih) = ?
                      AND COALESCE(aktif,1)=1""",
                [*params, ay_prefix],
            ).fetchone()
            alinan_tahsilat = round(float(row['toplam'] or 0), 2)
        except Exception:
            pass

    # Bekleyen tahsilat (ONAYLANDI durumunda, kalan > 0)
    bekleyen_tahsilat = None
    if _tablo_var(con, 'mo_tahsilat_kayit'):
        try:
            row = con.execute(
                f"""SELECT COALESCE(SUM(kalan_tutar), 0) as toplam
                    FROM mo_tahsilat_kayit
                    WHERE cari_id IN ({ph})
                      AND durum='ONAYLANDI'
                      AND (kalan_tutar IS NULL OR kalan_tutar > 0)
                      AND COALESCE(aktif,1)=1""",
                params,
            ).fetchone()
            bekleyen_tahsilat = round(float(row['toplam'] or 0), 2)
        except Exception:
            pass

    # Geciken tahsilat (planlanan_tarih < bugün, henüz ONAYLANDI + kalan > 0)
    geciken_tahsilat = None
    if _tablo_var(con, 'mo_tahsilat_kayit'):
        try:
            today_str = today.isoformat()
            row = con.execute(
                f"""SELECT COALESCE(SUM(kalan_tutar), 0) as toplam
                    FROM mo_tahsilat_kayit
                    WHERE cari_id IN ({ph})
                      AND durum='ONAYLANDI'
                      AND planlanan_tahsilat_tarihi < ?
                      AND (kalan_tutar IS NULL OR kalan_tutar > 0)
                      AND COALESCE(aktif,1)=1""",
                [*params, today_str],
            ).fetchone()
            geciken_tahsilat = round(float(row['toplam'] or 0), 2)
        except Exception:
            pass

    # Sipariş tutarı — tahmini (fiyat * kalem kg toplamı), güvenilir değilse None
    siparis_tutar = None
    if _tablo_var(con, 'nexgen_planlama_siparis') and _tablo_var(con, 'nexgen_planlama_siparis_kalem'):
        try:
            rows = con.execute(
                f"""SELECT ps.anlasma_birim_fiyat, k.miktar_kg
                    FROM nexgen_planlama_siparis ps
                    JOIN nexgen_planlama_siparis_kalem k ON k.siparis_id = ps.id
                    WHERE ps.cari_id IN ({ph})
                      AND strftime('%Y-%m', ps.olusturma_tarihi) = ?
                      AND ps.durum NOT IN ('TASLAK','REDDEDILDI','IPTAL')""",
                [*params, ay_prefix],
            ).fetchall()
            if rows:
                toplam = sum(
                    float(r['anlasma_birim_fiyat'] or 0) * float(r['miktar_kg'] or 0)
                    for r in rows
                )
                siparis_tutar = round(toplam, 2)
        except Exception:
            siparis_tutar = None

    return {
        'bu_ay_gorusme_adedi': gorusme_n,
        'bu_ay_numune_adedi': numune_n,
        'bu_ay_siparis_adedi': siparis_n,
        'bu_ay_siparis_tutari': siparis_tutar,
        'bu_ay_siparis_tutar_notu': 'Tahmini (birim_fiyat × kg)' if siparis_tutar is not None else 'Hesaplanamadı',
        'bu_ay_alinan_tahsilat': alinan_tahsilat,
        'bekleyen_tahsilat': bekleyen_tahsilat,
        'geciken_tahsilat': geciken_tahsilat,
        'ay': ay_prefix,
    }


def _v2_trendler(
    con: sqlite3.Connection,
    cari_ids: list[int],
    today: date,
    gun: int = 30,
) -> dict[str, list[dict]]:
    """Son N gün sipariş/numune/tahsilat trendi — yalnız gerçek aggregation.
    Verisi olmayan günler 0 olarak takvim bucket'ı döner (sahte değer değil).
    """
    if not cari_ids:
        return {'siparis': [], 'numune': [], 'tahsilat': []}
    ph, params = _in_ph(cari_ids)
    baslangic = today - timedelta(days=gun - 1)
    tarihler = [(baslangic + timedelta(days=i)).isoformat() for i in range(gun)]

    def _seri(tablo: str, tarih_kol: str, extra_where: str = '') -> list[dict]:
        if not _tablo_var(con, tablo):
            return [{'tarih': t, 'deger': 0} for t in tarihler]
        try:
            rows = con.execute(
                f"""SELECT strftime('%Y-%m-%d', {tarih_kol}) as gun, COUNT(*) as n
                    FROM {tablo}
                    WHERE cari_id IN ({ph})
                      AND {tarih_kol} >= ?
                      {extra_where}
                    GROUP BY gun""",
                [*params, baslangic.isoformat()],
            ).fetchall()
            agg = {r['gun']: int(r['n']) for r in rows}
        except Exception:
            agg = {}
        return [{'tarih': t, 'deger': agg.get(t, 0)} for t in tarihler]

    return {
        'siparis': _seri('nexgen_planlama_siparis', 'olusturma_tarihi',
                         "AND durum NOT IN ('TASLAK','REDDEDILDI','IPTAL')"),
        'numune': _seri('nexgen_numune_talep', 'olusturma_tarihi',
                        "AND COALESCE(aktif,1)=1"),
        'tahsilat': _seri('mo_tahsilat_kayit', 'alinan_tarih',
                          "AND durum='ONAYLANDI'"),
    }


def dashboard_v2(
    con: sqlite3.Connection,
    kullanici_id: int,
    yk: set | None = None,
) -> dict[str, Any]:
    """ERHAN UI-3A — read-only dashboard veri paketi.

    Güvenlik: scope daima get_pazarlama_cari_kapsami (cari_sorumlu atamaları).
    uid hardcode yok. Cari360 geniş finans yetkisi açılmaz.
    """
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)

    kapsam = get_pazarlama_cari_kapsami(con, kullanici_id, yk)
    cari_ids: list[int] = kapsam['cari_id_listesi']

    if not cari_ids:
        return {
            'kapsam': {'cari_ids': [], 'sayi': 0},
            'musteriler': [],
            'tahsilat_kayitlar': [],
            'vade_takvimi': {},
            'cek_sozleri': [],
            'numuneler': [],
            'siparisler': [],
            'kpi': {},
            'trendler': {'siparis': [], 'numune': [], 'tahsilat': []},
            'kapsam_bos': True,
        }

    today = date.today()
    cari_map = _cari_unvan_map(con, cari_ids)

    # 1. Müşteri listesi + bakiye
    musteriler: list[dict] = []
    for cid in sorted(cari_ids):
        info = cari_map.get(cid) or {}
        bak = _v2_bakiye_ozet(con, cid)
        musteriler.append({
            'cari_id': cid,
            'cari_kod': info.get('cari_kod'),
            'unvan': info.get('unvan'),
            'muhasebe_bakiye': bak.get('muhasebe_bakiye'),
            'bakiye_yonu': bak.get('bakiye_yonu'),
            'son_hareket_tarihi': bak.get('son_hareket_tarihi'),
            'bakiye_kaynak': bak.get('kaynak'),
            'bakiye_eslesme': bak.get('eslesme'),
        })

    # 2. Tahsilat/vade
    tahsilat_kayitlar, vade_takvimi = _v2_tahsilat_vade(con, cari_ids, today)

    # 3. Çek sözü
    cek_sozleri = _v2_cek_sozu(con, cari_ids)

    # 4. Numune özeti
    numuneler = _v2_numune_ozet(con, cari_ids, cari_map)

    # 5. Sipariş → üretim → sevk
    siparisler = _v2_siparis_uretim_sevk(con, cari_ids, cari_map)

    # 6. KPI
    kpi = _v2_bu_ay_kpi(con, cari_ids, today)

    # 7. Trendler
    trendler = _v2_trendler(con, cari_ids, today)

    # Vade takvimi özet (sayı + tutar)
    vade_ozet: dict[str, dict] = {}
    for grup, kayitlar in vade_takvimi.items():
        vade_ozet[grup] = {
            'sayi': len(kayitlar),
            'toplam_tutar': round(sum(float(k['tutar'] or 0) for k in kayitlar), 2),
        }

    return {
        'kapsam': {
            'cari_ids': sorted(cari_ids),
            'sayi': len(cari_ids),
        },
        'musteriler': musteriler,
        'tahsilat_kayitlar': tahsilat_kayitlar,
        'vade_takvimi': vade_takvimi,
        'vade_ozet': vade_ozet,
        'cek_sozleri': cek_sozleri,
        'numuneler': numuneler,
        'siparisler': siparisler,
        'kpi': kpi,
        'trendler': trendler,
        'kapsam_bos': False,
    }


def _ajanda_hafta_araligi(ref: date | None = None) -> tuple[str, str]:
    d = ref or date.today()
    bas = d - timedelta(days=d.weekday())
    bit = bas + timedelta(days=6)
    return bas.isoformat(), bit.isoformat()


def ajanda_tarih_araligi_listele(
    con: sqlite3.Connection,
    kullanici_id: int,
    yk: set[str] | None,
    bas_tarih: str,
    bit_tarih: str,
) -> list[dict[str, Any]]:
    """Ajanda sayfası — belirli hafta aralığındaki planlar."""
    from modules.nexgen.mo_ajanda_config import TABLO as AJ_TABLO
    from modules.nexgen.mo_ajanda_service import _cari_map, _row_dict, _tablo_var
    from modules.nexgen.cari_sorumlu_service import can_mo_view_cari

    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if not _tablo_var(con, AJ_TABLO):
        return []
    rows = con.execute(
        f"""
        SELECT a.*, c.unvan AS cari_unvan
        FROM {AJ_TABLO} a
        LEFT JOIN nexgen_cari c ON c.id = a.cari_id
        WHERE a.aktif=1 AND a.kullanici_id=?
          AND substr(a.plan_tarihi, 1, 10) BETWEEN ? AND ?
        ORDER BY a.plan_tarihi ASC, a.id ASC
        """,
        (kullanici_id, bas_tarih[:10], bit_tarih[:10]),
    ).fetchall()
    cari_ids = sorted({int(r['cari_id']) for r in rows if r['cari_id']})
    cm = _cari_map(con, cari_ids)
    out: list[dict[str, Any]] = []
    for r in rows:
        if not can_mo_view_cari(con, kullanici_id, int(r['cari_id']), yk):
            continue
        out.append(_row_dict(r, cm))
    from modules.nexgen.mo_ajanda_service import ajanda_enrich_gorusme_ozet
    return ajanda_enrich_gorusme_ozet(con, out)


def _ajanda_gun_farki(tarih_str: str | None) -> int:
    if not tarih_str:
        return 9999
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            dt = datetime.strptime(str(tarih_str)[:19], fmt)
            return max(0, (datetime.now() - dt).days)
        except ValueError:
            continue
    return 9999


def ajanda_gorusulmeyen_firmalar(
    con: sqlite3.Connection,
    kullanici_id: int,
    yk: set[str] | None = None,
    *,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Erhan cari scope + son_gorusme_ozet_map — eşik üstü veya hiç görüşülmemiş."""
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    kapsam = get_musteri_operasyonu_kapsami(con, kullanici_id, yk)
    cari_ids = list(kapsam.get('cari_id_listesi') or [])
    if not cari_ids:
        return []
    cari_map = _cari_unvan_map(con, cari_ids)
    son_map = son_gorusme_ozet_map(con, cari_ids)
    out: list[dict[str, Any]] = []
    for cid in cari_ids:
        info = cari_map.get(cid) or {}
        son = son_map.get(cid)
        if son:
            if _ajanda_gun_farki(son.get('gorusme_tarihi')) < GORUSME_GUN_ESIK:
                continue
            tarih = (son.get('gorusme_tarihi') or '')[:10]
            tip = son.get('gorusme_tipi') or ''
            son_metin = f'{tarih} — {tip}' if tarih else tip or '—'
        else:
            son_metin = 'Henüz görüşme yok'
        out.append({
            'cari_id': cid,
            'unvan': info.get('unvan') or '—',
            'cari_kod': info.get('cari_kod') or '',
            'son_gorusme': son_metin,
        })
    out.sort(key=lambda x: (x.get('unvan') or '').lower())
    return out[:limit]


def ajanda_hafta_ozet(planlar: list[dict[str, Any]]) -> dict[str, int]:
    toplam = len(planlar)
    tamamlanan = sum(1 for p in planlar if (p.get('durum') or '').upper() == 'GERCEKLESTI')
    planlanan = sum(1 for p in planlar if (p.get('durum') or '').upper() == 'PLANLANDI')
    iptal = sum(1 for p in planlar if (p.get('durum') or '').upper() == 'IPTAL')
    return {
        'toplam': toplam,
        'tamamlanan': tamamlanan,
        'planlanan': planlanan,
        'iptal': iptal,
    }


def ajanda_sayfa_verisi(
    con: sqlite3.Connection,
    kullanici_id: int,
    yk: set[str] | None = None,
    *,
    hafta_ref: date | None = None,
) -> dict[str, Any]:
    """Ajanda tam sayfa — haftalık planlar, özet, görüşülmeyen firmalar."""
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    hafta_bas, hafta_bit = _ajanda_hafta_araligi(hafta_ref)
    planlar = ajanda_tarih_araligi_listele(con, kullanici_id, yk, hafta_bas, hafta_bit)
    ozet = ajanda_hafta_ozet(planlar)
    gorusulmeyen = ajanda_gorusulmeyen_firmalar(con, kullanici_id, yk)
    ozet['gorusulmeyen_firmalar'] = len(gorusulmeyen)

    kapsam = get_musteri_operasyonu_kapsami(con, kullanici_id, yk)
    cari_ids = list(kapsam.get('cari_id_listesi') or [])
    musteriler: list[dict[str, Any]] = []
    if cari_ids:
        cm = _cari_unvan_map(con, cari_ids)
        for cid in sorted(cari_ids, key=lambda c: (cm.get(c) or {}).get('unvan') or ''):
            info = cm.get(cid) or {}
            musteriler.append({
                'cari_id': cid,
                'unvan': info.get('unvan') or '—',
                'cari_kod': info.get('cari_kod') or '',
            })

    zorunlu_gate = _ajanda_zorunlu_gate_items(con, kullanici_id, yk)

    return {
        'hafta_bas': hafta_bas,
        'hafta_bit': hafta_bit,
        'planlar': planlar,
        'ozet': ozet,
        'gorusulmeyen_firmalar': gorusulmeyen,
        'musteriler': musteriler,
        'zorunlu_sonuc': zorunlu_gate,
    }
