# -*- coding: utf-8 -*-
"""Renk Merkezi — Admin toplu silme ön kontrol ve atomik silme servisi."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

MAX_TOPLU_SECIM = 50
AUDIT_OLAY_TIPI = 'RENK_MERKEZI_TOPLU_SILME'

# Silme sırası — whitelist cleanup script ile uyumlu (numune cascade yok)
DELETE_ORDER = [
    ('nexgen_arge_deneme_kalem', 'deneme_id', 'via_deneme'),
    ('nexgen_arge_boyut_sonuc', 'arge_test_id', 'direct'),
    ('nexgen_arge_deneme_boyut_oran', 'arge_test_id', 'direct'),
    ('nexgen_arge_deneme', 'arge_test_id', 'direct'),
    ('nexgen_arge_kaynak_uv', 'arge_test_id', 'direct'),
    ('nexgen_arge_test_kalem', 'arge_test_id', 'direct'),
    ('nexgen_arge_revizyon', 'arge_test_id', 'direct'),
    ('nexgen_rf_kalem', 'rf_renk_id', 'via_rf'),
    ('nexgen_rf_formul_uygunluk', 'rf_renk_id', 'via_rf'),
    ('nexgen_rf_revizyon', 'rf_renk_id', 'via_rf'),
    ('nexgen_rf_renk', 'kaynak_arge_test_id', 'via_kaynak_arge'),
    ('nexgen_arge_test', 'id', 'root'),
]

KNOWN_TABLES = {t[0] for t in DELETE_ORDER} | {'nexgen_arge_olay', 'nexgen_numune_talep', 'nexgen_numune_talep_gelisme'}


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _table_cols(con, name: str) -> set[str]:
    if not _table_exists(con, name):
        return set()
    return {r[1] for r in con.execute(f'PRAGMA table_info({name})').fetchall()}


def _safe_count(con, table: str, where: str, params: tuple) -> int:
    if not _table_exists(con, table):
        return 0
    try:
        return int(con.execute(f'SELECT COUNT(*) FROM {table} WHERE {where}', params).fetchone()[0])
    except sqlite3.OperationalError:
        return 0


def _deneme_ids(con, arge_id: int) -> list[int]:
    rows = con.execute(
        'SELECT id FROM nexgen_arge_deneme WHERE arge_test_id=?', (arge_id,)
    ).fetchall()
    return [int(r[0]) for r in rows]


def _numune_ids(con, arge_id: int) -> list[dict]:
    if not _table_exists(con, 'nexgen_numune_talep'):
        return []
    rows = con.execute(
        'SELECT id, talep_kodu, durum FROM nexgen_numune_talep WHERE arge_test_id=? AND aktif=1',
        (arge_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _rf_links(con, arge_id: int, rf_renk_id) -> list[dict]:
    out: list[dict] = []
    if rf_renk_id:
        r = con.execute(
            'SELECT id, rf_kod, durum, aktif FROM nexgen_rf_renk WHERE id=?',
            (int(rf_renk_id),),
        ).fetchone()
        if r:
            out.append(dict(r))
    rows = con.execute(
        'SELECT id, rf_kod, durum, aktif FROM nexgen_rf_renk WHERE kaynak_arge_test_id=?',
        (arge_id,),
    ).fetchall()
    for r in rows:
        d = dict(r)
        if not any(x['id'] == d['id'] for x in out):
            out.append(d)
    return out


def _plan_kalem_count(con, rf_ids: list[int]) -> int:
    if not rf_ids or not _table_exists(con, 'nexgen_planlama_siparis_kalem'):
        return 0
    ph = ','.join('?' * len(rf_ids))
    return _safe_count(con, 'nexgen_planlama_siparis_kalem', f'rf_renk_id IN ({ph})', tuple(rf_ids))


def _uretim_baglanti_count(con, rf_ids: list[int]) -> int:
    """Aktif formül uygunluk / üretim kodu bağlantısı."""
    if not rf_ids or not _table_exists(con, 'nexgen_rf_formul_uygunluk'):
        return 0
    ph = ','.join('?' * len(rf_ids))
    return _safe_count(
        con, 'nexgen_rf_formul_uygunluk',
        f'rf_renk_id IN ({ph}) AND aktif=1',
        tuple(rf_ids),
    )


def _scan_unexpected_fk(con, arge_id: int) -> list[dict]:
    unexpected = []
    for (tbl,) in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'nexgen%' ORDER BY name"
    ).fetchall():
        if tbl in KNOWN_TABLES:
            continue
        cols = _table_cols(con, tbl)
        if 'arge_test_id' not in cols:
            continue
        n = _safe_count(con, tbl, 'arge_test_id=?', (arge_id,))
        if n:
            unexpected.append({'tablo': tbl, 'satir': n})
    return unexpected


def _count_delete_impact(
    con, arge_id: int, rf_ids: list[int], den_ids: list[int],
) -> dict[str, int]:
    impact: dict[str, int] = {}
    for tbl, col, mode in DELETE_ORDER:
        if not _table_exists(con, tbl):
            impact[tbl] = 0
            continue
        if mode == 'direct' and col in _table_cols(con, tbl):
            impact[tbl] = _safe_count(con, tbl, f'{col}=?', (arge_id,))
        elif mode == 'via_deneme' and den_ids:
            ph = ','.join('?' * len(den_ids))
            impact[tbl] = _safe_count(con, tbl, f'{col} IN ({ph})', tuple(den_ids))
        elif mode == 'via_rf' and rf_ids:
            ph = ','.join('?' * len(rf_ids))
            impact[tbl] = _safe_count(con, tbl, f'{col} IN ({ph})', tuple(rf_ids))
        elif mode == 'via_kaynak_arge':
            impact[tbl] = _safe_count(con, tbl, 'kaynak_arge_test_id=?', (arge_id,))
        elif mode == 'root':
            impact[tbl] = 1 if _safe_count(con, tbl, 'id=? AND aktif=1', (arge_id,)) else 0
        else:
            impact[tbl] = 0
    # olay satırları (audit hariç)
    if _table_exists(con, 'nexgen_arge_olay'):
        impact['nexgen_arge_olay'] = _safe_count(
            con, 'nexgen_arge_olay',
            'arge_test_id=? AND (olay_tipi IS NULL OR olay_tipi != ?)',
            (arge_id, AUDIT_OLAY_TIPI),
        )
    return {k: v for k, v in impact.items() if v}


def _resolve_arge(con, arge_test_id: int) -> dict | None:
    row = con.execute(
        """
        SELECT id, test_no, arge_kodu, durum, calisma_tipi, rf_renk_id,
               ferhat_genel_karar, aktif, yeni_renk_adi, talep_referansi
        FROM nexgen_arge_test
        WHERE id=?
        ORDER BY id DESC LIMIT 1
        """,
        (int(arge_test_id),),
    ).fetchone()
    return dict(row) if row else None


def _rf_adi(con, arge: dict) -> str:
    ad = (arge.get('yeni_renk_adi') or '').strip()
    if ad:
        return ad
    rf_id = arge.get('rf_renk_id')
    if rf_id:
        r = con.execute('SELECT ad FROM nexgen_rf_renk WHERE id=?', (int(rf_id),)).fetchone()
        if r and r['ad']:
            return str(r['ad'])
    return (arge.get('test_no') or '—')


def _analyze_one(con, arge_test_id: int) -> dict[str, Any]:
    """Tek kayıt silme analizi."""
    blocks: list[str] = []
    arge = _resolve_arge(con, arge_test_id)

    if not arge:
        return {
            'arge_test_id': int(arge_test_id),
            'at_kodu': None,
            'rf_adi': None,
            'durum': None,
            'silinebilir': False,
            'engel_nedenleri': ['Kayıt bulunamadı.'],
            'silme_etkisi': {},
            'toplam_etki_satir': 0,
        }

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

    nt = _numune_ids(con, aid)
    if nt:
        blocks.append('Numune talebi bağlantısı mevcut.')

    fk = (arge.get('ferhat_genel_karar') or '').strip()
    if fk:
        blocks.append('Ferhat sonucu mevcut.')

    rfs = _rf_links(con, aid, arge.get('rf_renk_id'))
    rf_ids: list[int] = []
    for rf in rfs:
        rf_ids.append(int(rf['id']))
        durum_rf = (rf.get('durum') or '').upper()
        aktif_rf = int(rf.get('aktif') or 0)
        if durum_rf in ('ONAYLI', 'AKTIF', 'URETIME_ACIK'):
            blocks.append(f'ONAYLI/AKTIF RF bağlantısı: {rf.get("rf_kod") or rf["id"]}')
        elif aktif_rf == 1 and durum_rf not in ('', 'TASLAK', 'IPTAL', 'PASIF'):
            blocks.append(f'Aktif üretim kodu bağlantısı: {rf.get("rf_kod") or rf["id"]}')

    pk = _plan_kalem_count(con, rf_ids)
    if pk:
        blocks.append(f'Plan/sipariş kalemi bağlantısı: {pk} satır.')

    uk = _uretim_baglanti_count(con, rf_ids)
    if uk:
        blocks.append(f'Üretim/formül bağlantısı: {uk} satır.')

    unexpected = _scan_unexpected_fk(con, aid)
    for u in unexpected:
        blocks.append(f'Beklenmeyen bağımlılık: {u["tablo"]} ({u["satir"]} satır).')

    den_ids = _deneme_ids(con, aid)
    impact = _count_delete_impact(con, aid, rf_ids, den_ids) if not blocks else {}
    toplam = sum(impact.values())

    return {
        'arge_test_id': aid,
        'at_kodu': arge.get('test_no'),
        'rf_adi': _rf_adi(con, arge),
        'durum': arge.get('durum'),
        'silinebilir': len(blocks) == 0,
        'engel_nedenleri': blocks,
        'silme_etkisi': impact,
        'toplam_etki_satir': toplam,
        '_rf_ids': rf_ids,
        '_den_ids': den_ids,
    }


def _engel_ux(blocks: list[str]) -> tuple[str | None, str | None]:
    """Engel nedenlerinden liste rozeti + tooltip üret."""
    if not blocks:
        return None, None
    joined = ' '.join(blocks).lower()
    if 'numune' in joined:
        return 'Numune Bağlı', 'Bu kayıt numune talebine bağlı olduğu için silinemez.'
    if 'ferhat' in joined:
        return 'Ferhat Sonucu', 'Bu kayıtta Ferhat sonucu olduğu için silinemez.'
    if 'onayli' in joined and 'rf' in joined:
        return 'Aktif RF', 'Bu kayıt ONAYLI/AKTIF RF bağlantısı olduğu için silinemez.'
    if 'aktif rf' in joined or 'uretime_acik' in joined:
        return 'Aktif RF', 'Bu kayıt aktif RF bağlantısı olduğu için silinemez.'
    if 'aktif üretim' in joined or 'üretim/formül' in joined or 'uretim' in joined:
        return 'Üretim Bağlı', 'Bu kayıt üretim/formül bağlantısı olduğu için silinemez.'
    if 'plan' in joined or 'sipariş' in joined:
        return 'Plan Bağlı', 'Bu kayıt plan/sipariş bağlantısı olduğu için silinemez.'
    if 'onayli renk' in joined or 'onaylandı' in joined:
        return 'Onaylı', 'Bu kayıt onaylı olduğu için silinemez.'
    return 'Korumalı', blocks[0]


def liste_toplu_sil_ux(con, arge_test_id: int) -> dict[str, Any]:
    """Liste kartı için silinebilirlik meta (Admin UX — silme mantığı _analyze_one ile aynı)."""
    rec = _analyze_one(con, int(arge_test_id))
    rozet, tooltip = _engel_ux(rec.get('engel_nedenleri') or [])
    return {
        'toplu_sil_silinebilir': bool(rec.get('silinebilir')),
        'toplu_sil_engel_rozet': rozet,
        'toplu_sil_engel_tooltip': tooltip,
    }


def _dedup_ids(ids: list) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for raw in ids or []:
        try:
            i = int(raw)
        except (TypeError, ValueError):
            continue
        if i <= 0 or i in seen:
            continue
        seen.add(i)
        out.append(i)
    return out


def toplu_sil_onkontrol(con, arge_test_ids: list, *, is_admin: bool) -> dict[str, Any]:
    if not is_admin:
        return {'ok': False, 'hata': 'Yalnız Admin.', 'http': 403}

    ids = _dedup_ids(arge_test_ids)
    if not ids:
        return {'ok': False, 'hata': 'Boş liste.', 'http': 400}
    if len(ids) > MAX_TOPLU_SECIM:
        return {'ok': False, 'hata': f'Maksimum {MAX_TOPLU_SECIM} kayıt seçilebilir.', 'http': 400}

    kayitlar = []
    for aid in ids:
        rec = _analyze_one(con, aid)
        kayitlar.append({k: v for k, v in rec.items() if not k.startswith('_')})

    silinebilir = [k for k in kayitlar if k['silinebilir']]
    engelli = [k for k in kayitlar if not k['silinebilir']]

    return {
        'ok': True,
        'toplam': len(kayitlar),
        'silinebilir_sayisi': len(silinebilir),
        'engelli_sayisi': len(engelli),
        'kayitlar': kayitlar,
        'silinebilir': silinebilir,
        'engelli': engelli,
    }


def _delete_olay_except_audit(con, arge_id: int) -> int:
    if not _table_exists(con, 'nexgen_arge_olay'):
        return 0
    cur = con.execute(
        """
        DELETE FROM nexgen_arge_olay
        WHERE arge_test_id=? AND (olay_tipi IS NULL OR olay_tipi != ?)
        """,
        (arge_id, AUDIT_OLAY_TIPI),
    )
    return cur.rowcount


def _delete_one_table(
    con, tbl: str, col: str, mode: str, arge_id: int,
    den_ids: list[int], rf_ids: list[int],
) -> int:
    if tbl == 'nexgen_arge_olay':
        return _delete_olay_except_audit(con, arge_id)
    if not _table_exists(con, tbl):
        return 0
    if mode == 'via_deneme' and den_ids:
        ph = ','.join('?' * len(den_ids))
        cur = con.execute(f'DELETE FROM {tbl} WHERE {col} IN ({ph})', den_ids)
        return cur.rowcount
    if mode == 'direct' and col in _table_cols(con, tbl):
        cur = con.execute(f'DELETE FROM {tbl} WHERE {col}=?', (arge_id,))
        return cur.rowcount
    if mode == 'via_rf' and rf_ids:
        ph = ','.join('?' * len(rf_ids))
        cur = con.execute(f'DELETE FROM {tbl} WHERE {col} IN ({ph})', rf_ids)
        return cur.rowcount
    if mode == 'via_kaynak_arge':
        cur = con.execute(f'DELETE FROM {tbl} WHERE kaynak_arge_test_id=?', (arge_id,))
        return cur.rowcount
    if mode == 'root':
        cur = con.execute(f'UPDATE {tbl} SET aktif=0 WHERE id=? AND aktif=1', (arge_id,))
        return cur.rowcount
    return 0


def _audit_yaz(con, arge_id: int, kullanici_id, kullanici_ad: str, rec: dict, silinen: dict):
    payload = {
        'islem': AUDIT_OLAY_TIPI,
        'kullanici': kullanici_ad,
        'arge_test_id': arge_id,
        'at_kodu': rec.get('at_kodu'),
        'silinen_satirlar': silinen,
        'toplam_satir': sum(silinen.values()),
    }
    con.execute(
        """
        INSERT INTO nexgen_arge_olay
            (arge_test_id, kullanici_id, eski_durum, yeni_durum, olay_tipi, aciklama)
        VALUES (?, ?, ?, 'SILINDI', ?, ?)
        """,
        (
            arge_id,
            kullanici_id,
            rec.get('durum'),
            AUDIT_OLAY_TIPI,
            json.dumps(payload, ensure_ascii=False),
        ),
    )


def toplu_sil_uygula(
    con,
    arge_test_ids: list,
    *,
    is_admin: bool,
    kullanici_id,
    kullanici_ad: str,
) -> dict[str, Any]:
    if not is_admin:
        return {'ok': False, 'hata': 'Yalnız Admin.', 'http': 403}

    ids = _dedup_ids(arge_test_ids)
    if not ids:
        return {'ok': False, 'hata': 'Boş liste.', 'http': 400}
    if len(ids) > MAX_TOPLU_SECIM:
        return {'ok': False, 'hata': f'Maksimum {MAX_TOPLU_SECIM} kayıt.', 'http': 400}

    analizler = [_analyze_one(con, aid) for aid in ids]
    engelli = [a for a in analizler if not a['silinebilir']]
    if engelli:
        nedenler = []
        for e in engelli:
            nedenler.append(f"{e.get('at_kodu') or e['arge_test_id']}: {'; '.join(e['engel_nedenleri'])}")
        return {
            'ok': False,
            'hata': 'Batch içinde engelli kayıt var — hiçbir kayıt silinmedi.',
            'engelli': [{k: v for k, v in e.items() if not k.startswith('_')} for e in engelli],
            'engel_detay': nedenler,
            'rollback': True,
            'http': 409,
        }

    result: dict[str, Any] = {
        'ok': False,
        'silinen_kayitlar': [],
        'toplam_satir': 0,
        'rollback': False,
    }

    try:
        con.execute('BEGIN IMMEDIATE')
        silinen_toplam = 0
        silinen_liste = []

        for rec in analizler:
            aid = int(rec['arge_test_id'])
            # Transaction içinde yeniden doğrula
            fresh = _analyze_one(con, aid)
            if not fresh['silinebilir']:
                raise RuntimeError(
                    f"{fresh.get('at_kodu') or aid}: {'; '.join(fresh['engel_nedenleri'])}"
                )

            beklenen = fresh['silme_etkisi']
            den_ids = fresh['_den_ids']
            rf_ids = fresh['_rf_ids']
            gercek: dict[str, int] = {}

            # Önce audit
            _audit_yaz(con, aid, kullanici_id, kullanici_ad, fresh, beklenen)

            # Olay silme (audit hariç)
            exp_olay = beklenen.get('nexgen_arge_olay', 0)
            if exp_olay:
                n_olay = _delete_olay_except_audit(con, aid)
                if n_olay != exp_olay:
                    raise RuntimeError(f'{fresh.get("at_kodu")}/nexgen_arge_olay: beklenen {exp_olay}, gerçek {n_olay}')
                gercek['nexgen_arge_olay'] = n_olay

            for tbl, col, mode in DELETE_ORDER:
                exp = beklenen.get(tbl, 0)
                if exp == 0 and mode != 'root':
                    if mode == 'direct' and col in _table_cols(con, tbl):
                        aktual = _safe_count(con, tbl, f'{col}=?', (aid,))
                        if aktual:
                            raise RuntimeError(f'{fresh.get("at_kodu")}/{tbl}: beklenen 0 ama {aktual} satır var')
                    continue
                n = _delete_one_table(con, tbl, col, mode, aid, den_ids, rf_ids)
                if exp and n != exp:
                    raise RuntimeError(f'{fresh.get("at_kodu")}/{tbl}: beklenen {exp}, gerçek {n}')
                if n:
                    gercek[tbl] = n

            satir = sum(gercek.values())
            silinen_toplam += satir
            silinen_liste.append({
                'arge_test_id': aid,
                'at_kodu': fresh.get('at_kodu'),
                'silinen_satirlar': gercek,
                'toplam_satir': satir,
            })

        con.execute('COMMIT')
        result['ok'] = True
        result['silinen_kayitlar'] = silinen_liste
        result['toplam_satir'] = silinen_toplam
        result['silinen_sayisi'] = len(silinen_liste)
        result['mesaj'] = f'{len(silinen_liste)} test kaydı silindi.'
    except Exception as exc:
        con.execute('ROLLBACK')
        result['hata'] = str(exc)
        result['rollback'] = True

    return result
