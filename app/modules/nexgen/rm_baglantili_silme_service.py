# -*- coding: utf-8 -*-
"""Renk Merkezi — bağlantılı test kaydı silme analizi ve hazırlık (apply faz-2)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from modules.nexgen.rm_toplu_silme_service import (
    MAX_TOPLU_SECIM,
    _analyze_one,
    _count_delete_impact,
    _dedup_ids,
    _deneme_ids,
    _numune_ids,
    _plan_kalem_count,
    _resolve_arge,
    _rf_adi,
    _rf_links,
    _safe_count,
    _scan_unexpected_fk,
    _table_cols,
    _table_exists,
    _uretim_baglanti_count,
)

AUDIT_BAGLANTILI_TIPI = 'RENK_MERKEZI_BAGLANTILI_TOPLU_SILME'
HAZIRLIK_MODU = False  # PILOT-2: lokal pilot apply

BAGLANTILI_DELETE_ORDER = [
    ('nexgen_arge_deneme_kalem', 'deneme_id', 'via_deneme', 'delete'),
    ('nexgen_arge_boyut_sonuc', 'arge_test_id', 'direct', 'delete'),
    ('nexgen_arge_deneme_boyut_oran', 'arge_test_id', 'direct', 'delete'),
    ('nexgen_arge_deneme', 'arge_test_id', 'direct', 'delete'),
    ('nexgen_arge_kaynak_uv', 'arge_test_id', 'direct', 'delete'),
    ('nexgen_arge_test_kalem', 'arge_test_id', 'direct', 'delete'),
    ('nexgen_arge_revizyon', 'arge_test_id', 'direct', 'delete'),
    ('nexgen_arge_olay', 'arge_test_id', 'direct', 'delete'),
    ('nexgen_numune_talep_gelisme', 'talep_id', 'via_numune', 'delete'),
    ('nexgen_numune_talep', 'arge_test_id', 'direct', 'numune_pasif'),
    ('nexgen_arge_test', 'id', 'root', 'soft_delete'),
]


def _is_test_marker(arge: dict | None, rf_adi: str | None) -> bool:
    if not arge:
        return False
    for raw in (
        arge.get('test_no'),
        arge.get('yeni_renk_adi'),
        arge.get('talep_referansi'),
        rf_adi,
    ):
        s = (str(raw or '')).strip()
        if not s:
            continue
        su = s.upper()
        if su in ('TEST', 'X'):
            return True
        if 'TEST' in su:
            return True
    return False


def _kesin_engel_nedenleri(con, arge: dict | None) -> tuple[list[str], dict[str, Any]]:
    """Numune/Ferhat hariç kesin engeller."""
    blocks: list[str] = []
    meta: dict[str, Any] = {
        'numune_talep': [],
        'ferhat_karar': None,
        'deneme_sayisi': 0,
        'uv_sayisi': 0,
        'olay_sayisi': 0,
        'revizyon_sayisi': 0,
        'rf_baglantilar': [],
        'plan_kalem': 0,
        'uretim_baglanti': 0,
        'rf_ids': [],
        'den_ids': [],
    }
    if not arge:
        return ['Kayıt bulunamadı.'], meta

    if int(arge.get('aktif') or 0) != 1:
        blocks.append('Kayıt zaten pasif veya silinmiş.')

    arge_kodu = (arge.get('arge_kodu') or '')
    if not arge_kodu.startswith('NX-AR-'):
        blocks.append('Çekirdek RF kaydı — yalnız NX-AR test kayıtları silinebilir.')

    calisma = (arge.get('calisma_tipi') or '').upper()
    if calisma not in ('MUSTERI_RENK', 'YENI_RF', 'YENI_FORMUL'):
        blocks.append('Geçersiz çalışma tipi.')

    durum = (arge.get('durum') or '').upper()
    if durum in ('ONAYLANDI',):
        blocks.append('ONAYLI renk kaydı.')

    aid = int(arge['id'])
    meta['numune_talep'] = _numune_ids(con, aid)
    meta['ferhat_karar'] = (arge.get('ferhat_genel_karar') or '').strip() or None
    meta['den_ids'] = _deneme_ids(con, aid)
    meta['deneme_sayisi'] = len(meta['den_ids'])

    if _table_exists(con, 'nexgen_arge_kaynak_uv'):
        meta['uv_sayisi'] = _safe_count(
            con, 'nexgen_arge_kaynak_uv', 'arge_test_id=?', (aid,),
        )
    if _table_exists(con, 'nexgen_arge_olay'):
        meta['olay_sayisi'] = _safe_count(con, 'nexgen_arge_olay', 'arge_test_id=?', (aid,))
    if _table_exists(con, 'nexgen_arge_revizyon'):
        meta['revizyon_sayisi'] = _safe_count(con, 'nexgen_arge_revizyon', 'arge_test_id=?', (aid,))

    rfs = _rf_links(con, aid, arge.get('rf_renk_id'))
    meta['rf_baglantilar'] = rfs
    rf_ids: list[int] = []
    for rf in rfs:
        rf_ids.append(int(rf['id']))
        durum_rf = (rf.get('durum') or '').upper()
        aktif_rf = int(rf.get('aktif') or 0)
        if durum_rf in ('ONAYLI', 'AKTIF', 'URETIME_ACIK'):
            blocks.append(f'ONAYLI/AKTIF RF bağlantısı: {rf.get("rf_kod") or rf["id"]}')
        elif aktif_rf == 1 and durum_rf not in ('', 'TASLAK', 'IPTAL', 'PASIF'):
            blocks.append(f'Aktif üretim kodu bağlantısı: {rf.get("rf_kod") or rf["id"]}')

    meta['rf_ids'] = rf_ids
    meta['plan_kalem'] = _plan_kalem_count(con, rf_ids)
    if meta['plan_kalem']:
        blocks.append(f'Plan/sipariş kalemi bağlantısı: {meta["plan_kalem"]} satır.')

    meta['uretim_baglanti'] = _uretim_baglanti_count(con, rf_ids)
    if meta['uretim_baglanti']:
        blocks.append(f'Üretim/formül bağlantısı: {meta["uretim_baglanti"]} satır.')

    unexpected = _scan_unexpected_fk(con, aid)
    meta['beklenmeyen_fk'] = unexpected
    for u in unexpected:
        blocks.append(f'Beklenmeyen bağımlılık: {u["tablo"]} ({u["satir"]} satır).')

    return blocks, meta


def _baglantili_etki(con, arge_id: int, meta: dict) -> dict[str, int]:
    """Bağlantılı silme tahmini satır etkisi."""
    rf_ids = meta.get('rf_ids') or []
    den_ids = meta.get('den_ids') or []
    nt_ids = [int(x['id']) for x in meta.get('numune_talep') or []]
    impact: dict[str, int] = {}

    for tbl, col, mode, action in BAGLANTILI_DELETE_ORDER:
        if not _table_exists(con, tbl):
            continue
        if action == 'numune_pasif':
            impact[tbl] = len(nt_ids)
        elif action == 'soft_delete':
            impact[tbl] = 1 if _safe_count(con, tbl, 'id=? AND aktif=1', (arge_id,)) else 0
        elif mode == 'via_deneme' and den_ids:
            ph = ','.join('?' * len(den_ids))
            impact[tbl] = _safe_count(con, tbl, f'{col} IN ({ph})', tuple(den_ids))
        elif mode == 'direct':
            impact[tbl] = _safe_count(con, tbl, f'{col}=?', (arge_id,))
        elif mode == 'via_numune' and nt_ids:
            ph = ','.join('?' * len(nt_ids))
            impact[tbl] = _safe_count(con, tbl, f'{col} IN ({ph})', tuple(nt_ids))
    impact = {k: v for k, v in impact.items() if v}
    return impact


def analyze_baglantili_one(con, arge_test_id: int) -> dict[str, Any]:
    """Tek kayıt — temiz / bağlantılı / kesin engel sınıflandırması."""
    arge = _resolve_arge(con, int(arge_test_id))
    temiz = _analyze_one(con, int(arge_test_id))
    kesin, meta = _kesin_engel_nedenleri(con, arge)

    rf_adi = _rf_adi(con, arge) if arge else None
    test_marker = _is_test_marker(arge, rf_adi)

    has_soft = bool(
        meta.get('numune_talep')
        or meta.get('ferhat_karar')
        or meta.get('deneme_sayisi')
        or meta.get('uv_sayisi')
        or meta.get('olay_sayisi')
    )

    if temiz.get('silinebilir'):
        sinif = 'TEMIZ'
        baglantili = False
        kesin_engel = False
    elif kesin:
        sinif = 'KESIN_ENGEL'
        baglantili = False
        kesin_engel = True
    elif has_soft:
        sinif = 'BAGLANTILI'
        baglantili = True
        kesin_engel = False
    else:
        sinif = 'KESIN_ENGEL'
        baglantili = False
        kesin_engel = True
        kesin = kesin or ['Bağlantı profili silmeye uygun değil.']

    aid = int(arge_test_id)
    etki = _baglantili_etki(con, aid, meta) if baglantili else {}

    baglanti_test = (
        baglantili
        and test_marker
        and (meta.get('numune_talep') or meta.get('ferhat_karar'))
        and not kesin
    )

    rozet = None
    tooltip = None
    if sinif == 'TEMIZ':
        pass
    elif sinif == 'BAGLANTILI':
        if meta.get('numune_talep'):
            rozet = 'Numune Bağlı'
            tooltip = 'Numune talebi bağlı. Bağlantıları inceleyerek kontrollü silme yapılabilir.'
        elif meta.get('ferhat_karar'):
            rozet = 'Ferhat Sonucu'
            tooltip = 'Ferhat sonucu mevcut. Bağlantıları inceleyerek kontrollü silme yapılabilir.'
        else:
            rozet = 'Test Verisi'
            tooltip = 'Test/deneme verisi bağlı. Bağlantıları inceleyerek kontrollü silme yapılabilir.'
    else:
        joined = ' '.join(kesin).lower()
        if 'onayli' in joined and 'rf' in joined:
            rozet, tooltip = 'Aktif RF', 'ONAYLI/AKTIF RF bağlantısı nedeniyle silinemez.'
        elif 'plan' in joined:
            rozet, tooltip = 'Plan Bağlı', 'Plan/sipariş bağlantısı nedeniyle silinemez.'
        elif 'üretim' in joined or 'uretim' in joined:
            rozet, tooltip = 'Üretim Bağlı', 'Üretim bağlantısı nedeniyle silinemez.'
        else:
            rozet, tooltip = 'Korumalı', kesin[0] if kesin else 'Silinemez.'

    return {
        'arge_test_id': aid,
        'at_kodu': arge.get('test_no') if arge else None,
        'rf_adi': rf_adi,
        'durum': arge.get('durum') if arge else None,
        'sinif': sinif,
        'temiz_silinebilir': sinif == 'TEMIZ',
        'baglantili_silinebilir': baglantili,
        'baglanti_test_filtre': baglanti_test,
        'kesin_engel': kesin_engel,
        'kesin_engel_nedenleri': kesin,
        'test_marker': test_marker,
        'bagimlilik': {
            'numune_talep': meta.get('numune_talep') or [],
            'ferhat_karar': meta.get('ferhat_karar'),
            'deneme_sayisi': meta.get('deneme_sayisi', 0),
            'uv_sayisi': meta.get('uv_sayisi', 0),
            'olay_sayisi': meta.get('olay_sayisi', 0),
            'revizyon_sayisi': meta.get('revizyon_sayisi', 0),
            'rf_baglantilar': meta.get('rf_baglantilar') or [],
            'plan_kalem': meta.get('plan_kalem', 0),
            'uretim_baglanti': meta.get('uretim_baglanti', 0),
            'siparis_baglanti': meta.get('plan_kalem', 0),
        },
        'silme_etkisi': etki,
        'toplam_etki_satir': sum(etki.values()),
        'rozet': rozet,
        'tooltip': tooltip,
    }


def liste_silme_ux_meta(con, arge_test_id: int) -> dict[str, Any]:
    """Liste kartı UX alanları — mevcut güvenli silme + bağlantılı profil."""
    rec = analyze_baglantili_one(con, int(arge_test_id))
    return {
        'toplu_sil_sinif': rec['sinif'],
        'toplu_sil_silinebilir': rec['temiz_silinebilir'],
        'toplu_sil_baglantili': rec['baglantili_silinebilir'],
        'toplu_sil_baglanti_test': rec['baglanti_test_filtre'],
        'toplu_sil_kesin_engel': rec['kesin_engel'],
        'toplu_sil_engel_rozet': rec.get('rozet'),
        'toplu_sil_engel_tooltip': rec.get('tooltip'),
    }


def baglantili_sil_incele(con, arge_test_ids: list, *, is_admin: bool) -> dict[str, Any]:
    if not is_admin:
        return {'ok': False, 'hata': 'Yalnız Admin.', 'http': 403}
    ids = _dedup_ids(arge_test_ids)
    if not ids:
        return {'ok': False, 'hata': 'Boş liste.', 'http': 400}
    if len(ids) > MAX_TOPLU_SECIM:
        return {'ok': False, 'hata': f'Maksimum {MAX_TOPLU_SECIM} kayıt.', 'http': 400}

    kayitlar = [analyze_baglantili_one(con, i) for i in ids]
    uygun = [k for k in kayitlar if k['baglantili_silinebilir']]
    engelli = [k for k in kayitlar if not k['baglantili_silinebilir']]

    return {
        'ok': True,
        'toplam': len(kayitlar),
        'uygun_sayisi': len(uygun),
        'engelli_sayisi': len(engelli),
        'kayitlar': kayitlar,
        'uygun': uygun,
        'engelli': engelli,
    }


def baglantili_sil_onkontrol(con, arge_test_ids: list, *, is_admin: bool) -> dict[str, Any]:
    out = baglantili_sil_incele(con, arge_test_ids, is_admin=is_admin)
    if not out.get('ok'):
        return out
    if out.get('engelli_sayisi'):
        return {
            'ok': False,
            'hata': 'Batch içinde kesin engelli kayıt var.',
            'engelli': out['engelli'],
            'http': 409,
        }
    if not out.get('uygun_sayisi'):
        return {'ok': False, 'hata': 'Bağlantılı silinebilir kayıt yok.', 'http': 400}
    out['hazirlik_modu'] = HAZIRLIK_MODU
    return out


def _audit_bagl_yaz(con, rec: dict, kullanici_id, kullanici_ad: str, gercek: dict):
    bag = rec.get('bagimlilik') or {}
    payload = {
        'islem': AUDIT_BAGLANTILI_TIPI,
        'kullanici': kullanici_ad,
        'at_kodu': rec.get('at_kodu'),
        'arge_test_id': rec.get('arge_test_id'),
        'numune_talepleri': [
            {'id': x.get('id'), 'talep_kodu': x.get('talep_kodu'), 'durum': x.get('durum')}
            for x in bag.get('numune_talep') or []
        ],
        'eski_ferhat_karar': bag.get('ferhat_karar'),
        'silinen_satirlar': gercek,
        'toplam_satir': sum(gercek.values()),
    }
    con.execute(
        """
        INSERT INTO nexgen_arge_olay
            (arge_test_id, kullanici_id, eski_durum, yeni_durum, olay_tipi, aciklama)
        VALUES (?, ?, ?, 'SILINDI', ?, ?)
        """,
        (
            rec['arge_test_id'],
            kullanici_id,
            rec.get('durum'),
            AUDIT_BAGLANTILI_TIPI,
            json.dumps(payload, ensure_ascii=False),
        ),
    )


def _delete_olay_except_audit_bagl(con, arge_id: int) -> int:
    if not _table_exists(con, 'nexgen_arge_olay'):
        return 0
    cur = con.execute(
        """
        DELETE FROM nexgen_arge_olay
        WHERE arge_test_id=? AND (olay_tipi IS NULL OR olay_tipi != ?)
        """,
        (arge_id, AUDIT_BAGLANTILI_TIPI),
    )
    return cur.rowcount


def _numune_pasif(con, arge_id: int, nt_ids: list[int]) -> int:
    if not nt_ids or not _table_exists(con, 'nexgen_numune_talep'):
        return 0
    n = 0
    for tid in nt_ids:
        cur = con.execute(
            """
            UPDATE nexgen_numune_talep
            SET aktif=0, durum='IPTAL', arge_test_id=NULL,
                guncelleme_tarihi=datetime('now','localtime')
            WHERE id=? AND arge_test_id=? AND aktif=1
            """,
            (int(tid), int(arge_id)),
        )
        n += cur.rowcount
    return n


def _execute_bagl_one(
    con, rec: dict, kullanici_id, kullanici_ad: str,
) -> dict[str, int]:
    """Tek kayit baglantili silme — transaction icinde."""
    aid = int(rec['arge_test_id'])
    fresh = analyze_baglantili_one(con, aid)
    if not fresh.get('baglantili_silinebilir'):
        raise RuntimeError(
            f"{fresh.get('at_kodu') or aid}: {'; '.join(fresh.get('kesin_engel_nedenleri') or ['engel'])}"
        )

    beklenen = fresh['silme_etkisi']
    den_ids = _deneme_ids(con, aid)
    nt_ids = [int(x['id']) for x in (fresh.get('bagimlilik') or {}).get('numune_talep') or []]
    gercek: dict[str, int] = {}

    _audit_bagl_yaz(con, fresh, kullanici_id, kullanici_ad, beklenen)

    for tbl, col, mode, action in BAGLANTILI_DELETE_ORDER:
        exp = beklenen.get(tbl, 0)
        if tbl == 'nexgen_arge_olay':
            if exp:
                n = _delete_olay_except_audit_bagl(con, aid)
                if n != exp:
                    raise RuntimeError(f'{fresh.get("at_kodu")}/olay: beklenen {exp}, gercek {n}')
                gercek[tbl] = n
            continue
        if action == 'numune_pasif':
            if exp:
                n = _numune_pasif(con, aid, nt_ids)
                if n != exp:
                    raise RuntimeError(f'{fresh.get("at_kodu")}/numune: beklenen {exp}, gercek {n}')
                gercek[tbl] = n
            continue
        if action == 'soft_delete':
            if exp:
                cur = con.execute(
                    'UPDATE nexgen_arge_test SET aktif=0 WHERE id=? AND aktif=1', (aid,),
                )
                if cur.rowcount != exp:
                    raise RuntimeError(f'{fresh.get("at_kodu")}/arge_test: beklenen {exp}, gercek {cur.rowcount}')
                gercek[tbl] = cur.rowcount
            continue
        if exp == 0:
            if mode == 'direct' and col in _table_cols(con, tbl):
                aktual = _safe_count(con, tbl, f'{col}=?', (aid,))
                if aktual:
                    raise RuntimeError(f'{fresh.get("at_kodu")}/{tbl}: beklenen 0 ama {aktual} satir')
            continue
        if mode == 'via_deneme' and den_ids:
            ph = ','.join('?' * len(den_ids))
            cur = con.execute(f'DELETE FROM {tbl} WHERE {col} IN ({ph})', den_ids)
        elif mode == 'via_numune' and nt_ids:
            ph = ','.join('?' * len(nt_ids))
            cur = con.execute(f'DELETE FROM {tbl} WHERE {col} IN ({ph})', nt_ids)
        elif mode == 'direct' and col in _table_cols(con, tbl):
            cur = con.execute(f'DELETE FROM {tbl} WHERE {col}=?', (aid,))
        else:
            continue
        n = cur.rowcount
        if n != exp:
            raise RuntimeError(f'{fresh.get("at_kodu")}/{tbl}: beklenen {exp}, gercek {n}')
        gercek[tbl] = n

    return gercek


def _audit_onizleme(rec: dict, kullanici_ad: str) -> dict:
    bag = rec.get('bagimlilik') or {}
    return {
        'islem': AUDIT_BAGLANTILI_TIPI,
        'kullanici': kullanici_ad,
        'at_kodu': rec.get('at_kodu'),
        'arge_test_id': rec.get('arge_test_id'),
        'numune_talepleri': [
            {'id': x.get('id'), 'talep_kodu': x.get('talep_kodu'), 'durum': x.get('durum')}
            for x in bag.get('numune_talep') or []
        ],
        'eski_ferhat_karar': bag.get('ferhat_karar'),
        'silme_etkisi': rec.get('silme_etkisi'),
        'toplam_satir': rec.get('toplam_etki_satir'),
    }


def baglantili_sil_uygula(
    con,
    arge_test_ids: list,
    *,
    is_admin: bool,
    kullanici_id,
    kullanici_ad: str,
    at_dogrulama: dict | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Baglantili silme — apply=True ise gercek COMMIT."""
    if not is_admin:
        return {'ok': False, 'hata': 'Yalnız Admin.', 'http': 403}

    dry_run = not apply
    ids = _dedup_ids(arge_test_ids)
    if not ids:
        return {'ok': False, 'hata': 'Boş liste.', 'http': 400}

    onkontrol = baglantili_sil_onkontrol(con, ids, is_admin=True)
    if not onkontrol.get('ok'):
        return onkontrol

    at_map = at_dogrulama or {}
    for rec in onkontrol['uygun']:
        beklenen = (rec.get('at_kodu') or '').strip()
        girilen = (at_map.get(str(rec['arge_test_id'])) or at_map.get(rec['arge_test_id']) or '').strip()
        if beklenen and girilen.upper() != beklenen.upper():
            return {
                'ok': False,
                'hata': f"AT doğrulama hatası: {rec.get('at_kodu')}",
                'http': 400,
            }

    if dry_run:
        plan = []
        audit_onizleme = []
        for rec in onkontrol['uygun']:
            adimlar = []
            for tbl, col, mode, action in BAGLANTILI_DELETE_ORDER:
                n = (rec.get('silme_etkisi') or {}).get(tbl, 0)
                if n:
                    adimlar.append({'tablo': tbl, 'islem': action, 'beklenen_satir': n})
            plan.append({
                'arge_test_id': rec['arge_test_id'],
                'at_kodu': rec.get('at_kodu'),
                'adimlar': adimlar,
                'toplam_satir': rec.get('toplam_etki_satir'),
            })
            audit_onizleme.append(_audit_onizleme(rec, kullanici_ad))
        return {
            'ok': True,
            'hazirlik_modu': True,
            'silme_yapildi': False,
            'rollback': False,
            'commit': False,
            'mesaj': f'{len(plan)} kayıt plan hazır — DB değişmedi.',
            'plan': plan,
            'audit_onizleme': audit_onizleme,
            'toplam_kayit': len(plan),
            'toplam_satir': sum(p.get('toplam_satir') or 0 for p in plan),
        }

    result: dict[str, Any] = {
        'ok': False,
        'hazirlik_modu': False,
        'silme_yapildi': False,
        'rollback': False,
        'commit': False,
        'silinen_kayitlar': [],
    }
    try:
        con.execute('BEGIN IMMEDIATE')
        silinen_liste = []
        toplam_satir = 0
        for rec in onkontrol['uygun']:
            gercek = _execute_bagl_one(con, rec, kullanici_id, kullanici_ad)
            satir = sum(gercek.values())
            toplam_satir += satir
            silinen_liste.append({
                'arge_test_id': rec['arge_test_id'],
                'at_kodu': rec.get('at_kodu'),
                'silinen_satirlar': gercek,
                'toplam_satir': satir,
            })
        con.execute('COMMIT')
        result['ok'] = True
        result['silme_yapildi'] = True
        result['commit'] = True
        result['silinen_kayitlar'] = silinen_liste
        result['toplam_satir'] = toplam_satir
        result['silinen_sayisi'] = len(silinen_liste)
        result['mesaj'] = f'{len(silinen_liste)} baglantili test kaydi silindi.'
    except Exception as exc:
        con.execute('ROLLBACK')
        result['hata'] = str(exc)
        result['rollback'] = True

    return result


def analiz_raporu(con) -> dict[str, Any]:
    """Tüm aktif NX-AR kayıtları için özet rapor."""
    rows = con.execute(
        """
        SELECT id FROM nexgen_arge_test
        WHERE aktif=1 AND arge_kodu LIKE 'NX-AR-%'
          AND calisma_tipi IN ('MUSTERI_RENK','YENI_RF','YENI_FORMUL')
        ORDER BY id
        """
    ).fetchall()
    temiz: list = []
    baglantili: list = []
    kesin: list = []
    baglanti_test: list = []
    detay = []
    for (aid,) in rows:
        rec = analyze_baglantili_one(con, int(aid))
        detay.append({
            'arge_test_id': rec['arge_test_id'],
            'at_kodu': rec.get('at_kodu'),
            'rf_adi': rec.get('rf_adi'),
            'sinif': rec['sinif'],
            'bagimlilik': rec.get('bagimlilik'),
            'toplam_etki_satir': rec.get('toplam_etki_satir'),
            'kesin_engel_nedenleri': rec.get('kesin_engel_nedenleri'),
        })
        if rec['sinif'] == 'TEMIZ':
            temiz.append(rec)
        elif rec['sinif'] == 'BAGLANTILI':
            baglantili.append(rec)
        else:
            kesin.append(rec)
        if rec.get('baglanti_test_filtre'):
            baglanti_test.append(rec)

    return {
        'toplam_nx_ar': len(rows),
        'temiz_silinebilir': len(temiz),
        'baglantili_silinebilir': len(baglantili),
        'kesin_engelli': len(kesin),
        'baglanti_test_filtre': len(baglanti_test),
        'kayitlar': detay,
    }
