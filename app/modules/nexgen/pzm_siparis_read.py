# -*- coding: utf-8 -*-
"""
Pazarlama Merkezi BE-1 — Sipariş okuma katmanı (Header + Kalemler)

Yalnız okuma. Legacy siparişlerde talep_referansi JSON korunur;
kalem tablosu boşsa sanal kalem üretilir.
"""
from __future__ import annotations

import json
import re
from typing import Any

PZM_JSON_PREFIX = '__PZM_V1__'
PZM_V2_JSON_PREFIX = '__PZM_V2__'
PZM_TALEP_LIKE = '__PZM_V%'


def pzm_kalem_tablosu_var(con) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='nexgen_planlama_siparis_kalem'"
    ).fetchone()
    return row is not None


def pzm_payload_unpack(ref) -> dict | None:
    if not ref:
        return None
    s = str(ref)
    for prefix in (PZM_V2_JSON_PREFIX, PZM_JSON_PREFIX):
        if s.startswith(prefix):
            try:
                return json.loads(s[len(prefix):])
            except Exception:
                return None
    return None


def pzm_siparis_v2_mi(ref) -> bool:
    return bool(ref) and str(ref).startswith(PZM_V2_JSON_PREFIX)


def pzm_siparis_finans_alanlari(hdr: dict, payload: dict | None = None) -> dict[str, Any]:
    """DB kolonları veya V2 meta JSON'dan finans alanlarını birleştirir."""
    pb = hdr.get('anlasma_para_birimi')
    vg = hdr.get('vade_gun')
    bf = hdr.get('anlasma_birim_fiyat')
    if payload:
        if not pb:
            pb = payload.get('anlasma_para_birimi')
        if vg in (None, ''):
            vg = payload.get('vade_gun')
        if not bf:
            bf = payload.get('anlasma_birim_fiyat')
    return {
        'anlasma_para_birimi': pb,
        'vade_gun': vg,
        'anlasma_birim_fiyat': bf,
    }


def _miktar_to_boyut_dict(ml: float, ms: float, mm: float) -> dict[str, float]:
    out: dict[str, float] = {}
    if ml and ml > 0:
        out['LARGE'] = round(float(ml), 3)
    if ms and ms > 0:
        out['SMALL'] = round(float(ms), 3)
    if mm and mm > 0:
        out['STANDART'] = round(float(mm), 3)
    return out


def _toplam_kg(ml: float, ms: float, mm: float) -> float:
    return round(float(ml or 0) + float(ms or 0) + float(mm or 0), 3)


def pzm_kalem_dict_from_row(row) -> dict[str, Any]:
    """DB satırını API sözlüğüne çevirir."""
    d = dict(row)
    ml = float(d.get('miktar_l') or 0)
    ms = float(d.get('miktar_s') or 0)
    mm = float(d.get('miktar_m') or 0)
    d['boyut_miktar'] = _miktar_to_boyut_dict(ml, ms, mm)
    d['toplam_kg'] = _toplam_kg(ml, ms, mm)
    d['kaynak'] = 'KALEM' if not d.get('legacy_kaynak') else 'KALEM_LEGACY'
    return d


def pzm_kalem_dict_from_payload(
    payload: dict,
    *,
    sira_no: int = 1,
    kalem_id: int | None = None,
    uretim_plan_id: int | None = None,
    legacy_kaynak: bool = True,
) -> dict[str, Any]:
    """Legacy talep_referansi JSON'dan sanal kalem üretir."""
    boyut = payload.get('boyut_miktar') or {}
    ml = ms = mm = 0.0
    if isinstance(boyut, dict):
        for b, v in boyut.items():
            key = (b or '').upper()
            if key == 'MEDIUM':
                key = 'STANDART'
            try:
                kg = round(float(v), 3)
            except (TypeError, ValueError):
                continue
            if kg <= 0:
                continue
            if key == 'LARGE':
                ml = kg
            elif key == 'SMALL':
                ms = kg
            elif key == 'STANDART':
                mm = kg

    return {
        'id': kalem_id,
        'sira_no': sira_no,
        'urun_ailesi': payload.get('urun_ailesi'),
        'formul_id': payload.get('formul_id'),
        'formul_ad': payload.get('formul_ad'),
        'renk_varyant_id': payload.get('renk_varyant_id'),
        'renk_ad': payload.get('renk_ad'),
        'rf_renk_id': payload.get('rf_renk_id'),
        'miktar_l': ml,
        'miktar_s': ms,
        'miktar_m': mm,
        'boyut_miktar': _miktar_to_boyut_dict(ml, ms, mm),
        'toplam_kg': _toplam_kg(ml, ms, mm),
        'termin_tarihi': payload.get('termin_tarihi'),
        'notlar': payload.get('notlar'),
        'uretim_plan_id': uretim_plan_id,
        'durum': 'AKTIF',
        'legacy_kaynak': 1 if legacy_kaynak else 0,
        'kaynak': 'LEGACY_JSON',
    }


def pzm_siparis_kalemleri_getir(con, planlama_siparis_id: int) -> list[dict[str, Any]]:
    """Sipariş kalemlerini döndürür. Kalem yoksa legacy JSON'dan sanal kalem üretir."""
    if pzm_kalem_tablosu_var(con):
        rows = con.execute(
            """
            SELECT id, planlama_siparis_id, sira_no, urun_ailesi,
                   formul_id, formul_ad, renk_varyant_id, renk_ad, rf_renk_id,
                   miktar_l, miktar_s, miktar_m, termin_tarihi, notlar,
                   uretim_plan_id, durum, legacy_kaynak,
                   olusturma_tarihi, guncelleme_tarihi
            FROM nexgen_planlama_siparis_kalem
            WHERE planlama_siparis_id=?
            ORDER BY sira_no, id
            """,
            (planlama_siparis_id,),
        ).fetchall()
        if rows:
            return [pzm_kalem_dict_from_row(r) for r in rows]

    hdr = con.execute(
        'SELECT talep_referansi FROM nexgen_planlama_siparis WHERE id=?',
        (planlama_siparis_id,),
    ).fetchone()
    if not hdr:
        return []

    payload = pzm_payload_unpack(hdr['talep_referansi'])
    if not payload:
        try:
            from modules.nexgen.mo_siparis_talep_service import mo_siparis_payload_unpack
            mo_p = mo_siparis_payload_unpack(hdr['talep_referansi'])
            if mo_p:
                mk = float(mo_p.get('miktar') or 0)
                payload = {
                    'urun_ailesi': mo_p.get('urun_grubu'),
                    'formul_ad': mo_p.get('urun_adi'),
                    'boyut_miktar': {'STANDART': mk} if mk > 0 else {},
                    'termin_tarihi': mo_p.get('onerilen_termin') or mo_p.get('musteri_termin'),
                    'notlar': mo_p.get('musteri_notu'),
                }
        except Exception:
            payload = None
    if not payload:
        return []

    plan_row = con.execute(
        'SELECT id FROM nexgen_uretim_plan WHERE planlama_siparis_id=? ORDER BY id LIMIT 1',
        (planlama_siparis_id,),
    ).fetchone()
    plan_id = plan_row['id'] if plan_row else None
    return [pzm_kalem_dict_from_payload(payload, uretim_plan_id=plan_id)]


def pzm_iso_tarih(val) -> str | None:
    """Geçerli ISO tarih (1970–2100) veya None."""
    if val is None or val == '':
        return None
    s = str(val).strip()
    iso = s[:10]
    if re.match(r'^\d{4}-\d{2}-\d{2}$', iso):
        y = int(iso[:4])
        if 1970 <= y <= 2100:
            return iso
    m = re.match(r'^(\d{1,2})[\.\/-](\d{1,2})[\.\/-](\d{4})$', s)
    if m:
        y = int(m.group(3))
        if 1970 <= y <= 2100:
            return f'{y}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}'
    return None


def pzm_en_erken_gecerli_termin(degerler) -> str | None:
    gecerli = []
    for v in degerler:
        iso = pzm_iso_tarih(v)
        if iso:
            gecerli.append(iso)
    return min(gecerli) if gecerli else None


def pzm_siparis_termin_coz(
    header_termin,
    kalemler: list[dict] | None,
) -> str | None:
    """Header geçerliyse header; değilse kalemlerden en erken geçerli termin."""
    header_iso = pzm_iso_tarih(header_termin)
    if header_iso:
        return header_iso
    kalem_termins = [
        k.get('termin_tarihi')
        for k in (kalemler or [])
        if k.get('termin_tarihi')
    ]
    return pzm_en_erken_gecerli_termin(kalem_termins)


def pzm_siparis_ozet(
    kalemler: list[dict],
    header_termin=None,
) -> dict[str, Any]:
    toplam = round(sum(float(k.get('toplam_kg') or 0) for k in kalemler), 3)
    terlik = taban = dokme = 0.0
    for k in kalemler:
        aile = (k.get('urun_ailesi') or '').upper()
        kg = float(k.get('toplam_kg') or 0)
        if aile == 'TERLIK':
            terlik += kg
        elif aile == 'DOKME':
            dokme += float(k.get('miktar_m') or kg)
        elif aile == 'TABAN':
            taban += kg
    return {
        'kalem_sayisi': len(kalemler),
        'toplam_kg': toplam,
        'terlik_kg': round(terlik, 3),
        'taban_kg': round(taban, 3),
        'dokme_kg': round(dokme, 3),
        'en_yakin_termin': pzm_siparis_termin_coz(header_termin, kalemler),
    }


def pzm_siparis_header_getir(con, siparis_id: int) -> dict | None:
    cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()}
    extra = [c for c in ('anlasma_para_birimi', 'vade_gun', 'anlasma_birim_fiyat') if c in cols]
    extra_sql = (', ' + ', '.join(extra)) if extra else ''
    row = con.execute(
        f"""
        SELECT id, siparis_no, cari_id, cari_unvan, termin_tarihi,
               talep_referansi, durum, notlar, olusturan_id,
               olusturma_tarihi, guncelleme_tarihi{extra_sql}
        FROM nexgen_planlama_siparis
        WHERE id=?
        """,
        (siparis_id,),
    ).fetchone()
    return dict(row) if row else None


def pzm_siparis_oku(con, siparis_id: int) -> dict | None:
    """Header + kalemler + legacy bayrakları."""
    hdr = pzm_siparis_header_getir(con, siparis_id)
    if not hdr:
        return None

    payload = pzm_payload_unpack(hdr.get('talep_referansi'))
    kalemler = pzm_siparis_kalemleri_getir(con, siparis_id)
    kalem_tablo = pzm_kalem_tablosu_var(con)
    kalem_db = 0
    if kalem_tablo:
        kalem_db = con.execute(
            'SELECT COUNT(*) AS n FROM nexgen_planlama_siparis_kalem WHERE planlama_siparis_id=?',
            (siparis_id,),
        ).fetchone()['n']

    ozet = pzm_siparis_ozet(kalemler, header_termin=hdr.get('termin_tarihi'))
    finans = pzm_siparis_finans_alanlari(hdr, payload)
    return {
        **hdr,
        **finans,
        'payload': payload,
        'kalemler': kalemler,
        'kalem_sayisi': ozet['kalem_sayisi'],
        'toplam_kg': ozet['toplam_kg'],
        'okuma_modu': 'HEADER_KALEM' if kalem_db else ('LEGACY_JSON' if payload else 'BOS'),
        'legacy_json_korundu': payload is not None,
    }
