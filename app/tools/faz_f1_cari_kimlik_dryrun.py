# -*- coding: utf-8 -*-
"""FAZ-F1-4 — Finans cari kimlik backfill dry-run (READ-ONLY).

Kullanım:
    python app/tools/faz_f1_cari_kimlik_dryrun.py
    python app/tools/faz_f1_cari_kimlik_dryrun.py --output-dir backup/custom

--apply bu fazda devre dışıdır.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app'
DEFAULT_DB = APP / 'mock_data.db'
BASELINE_SHA = 'fe2013c2583e62f6f0afd6088da25e0d0b0e3f5a61f4a3738792878fcef8cb67'

if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.nexgen.finans_cari_kimlik_service import (  # noqa: E402
    hesapla_posting_uygunluk,
    normalize_ctip,
    validate_ctip_for_kimlik,
)
from modules.nexgen.import_normalizer import normalize_metin  # noqa: E402

APPLY_DISABLED_CODE = 'APPLY_DISABLED_USER_APPROVAL_REQUIRED'

KARAR_SINIFLARI = (
    'LINK_EXISTING_VERIFIED',
    'CREATE_IDENTITY_ONLY',
    'AUTO_MATCH_SAFE',
    'MANUAL_REVIEW',
    'NO_MATCHING_CARI_KART',
    'CTIP_MISMATCH',
    'CKOD_CONFLICT',
    'CARD_NOT_FOUND',
    'OPERATIONAL_INACTIVE',
    'DATA_ERROR',
)

KARAR_ETIKETLERI = {
    'NO_MATCHING_CARI_KART': 'Eslesme adayi bulunamadi',
}

CRITICAL_TABLES = (
    'Cari_Har',
    'finans_belgesi',
    'finans_cari_kimlik',
    'tedarikci_eslestirme',
    'cari_eslestirme',
    'Cari_Kart',
    'sistem_yetki',
    'sistem_rol_yetki',
    'schema_migrations',
)

WRITE_SQL_PATTERNS = (
    re.compile(r'^\s*(INSERT|UPDATE|DELETE|REPLACE|DROP|ALTER|CREATE)\s', re.I),
    re.compile(r'^\s*PRAGMA\s+(?!query_only)', re.I),
)


def normalize_code(value: Any) -> str:
    if value is None:
        return ''
    s = str(value).strip().upper()
    s = re.sub(r'[^A-Z0-9._-]+', '', s)
    return s


def unvan_similarity(a: str, b: str) -> float:
    na, nb = normalize_metin(a), normalize_metin(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def db_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def table_hashes(db_path: Path) -> dict[str, dict[str, Any]]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    out: dict[str, dict[str, Any]] = {}
    for t in CRITICAL_TABLES:
        rows = con.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall()
        cols = [d[0] for d in con.execute(f'SELECT * FROM "{t}" LIMIT 0').description]
        payload = [dict(zip(cols, row)) for row in rows]
        h = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        out[t] = {'count': len(rows), 'hash': h}
    con.close()
    return out


def finans_belgesi_snapshot(db_path: Path) -> list[dict[str, Any]]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        'SELECT id, belge_kodu, durum, posting_durumu FROM finans_belgesi ORDER BY id'
    ).fetchall()]
    con.close()
    return rows


def collect_db_evidence(db_path: Path) -> dict[str, Any]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    ev = {
        'db_path': str(db_path),
        'sha256': db_sha256(db_path),
        'size_bytes': db_path.stat().st_size,
        'integrity_check': con.execute('PRAGMA integrity_check').fetchone()[0],
        'max_migration': con.execute(
            'SELECT MAX(CAST(version AS INTEGER)) FROM schema_migrations'
        ).fetchone()[0],
        'cari_har': int(con.execute('SELECT COUNT(*) FROM Cari_Har').fetchone()[0]),
        'finans_belgesi': finans_belgesi_snapshot(db_path),
        'finans_cari_kimlik': int(con.execute('SELECT COUNT(*) FROM finans_cari_kimlik').fetchone()[0]),
        'tedarikci_eslestirme': int(con.execute('SELECT COUNT(*) FROM tedarikci_eslestirme').fetchone()[0]),
        'cari_eslestirme': int(con.execute('SELECT COUNT(*) FROM cari_eslestirme').fetchone()[0]),
        'cari_kart': int(con.execute('SELECT COUNT(*) FROM Cari_Kart').fetchone()[0]),
        'nexgen_cari': int(con.execute('SELECT COUNT(*) FROM nexgen_cari').fetchone()[0]),
        'nexgen_tedarikci': int(con.execute('SELECT COUNT(*) FROM nexgen_tedarikci').fetchone()[0]),
        'sistem_yetki': int(con.execute('SELECT COUNT(*) FROM sistem_yetki').fetchone()[0]),
        'sistem_rol_yetki': int(con.execute('SELECT COUNT(*) FROM sistem_rol_yetki').fetchone()[0]),
        'table_hashes': table_hashes(db_path),
    }
    con.close()
    try:
        from modules.nexgen import mo_tahsilat_config as mtc
        ev['cari_entegrasyon_aktif'] = bool(getattr(mtc, 'CARI_ENTEGRASYON_AKTIF', None))
    except Exception:
        ev['cari_entegrasyon_aktif'] = None
    return ev


def readonly_connect(db_path: Path) -> sqlite3.Connection:
    uri = f'file:{db_path.resolve()}?mode=ro'
    con = sqlite3.connect(uri, uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA query_only = ON')
    return con


def load_cari_kart_map(con: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return {
        str(r['CKod']): dict(r)
        for r in con.execute('SELECT * FROM Cari_Kart ORDER BY CKod').fetchall()
    }


def load_eslestirmeler(con: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    rows = con.execute('SELECT * FROM cari_eslestirme ORDER BY nexgen_cari_id').fetchall()
    return {int(r['nexgen_cari_id']): dict(r) for r in rows}


def load_kimlik_usage(con: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    usage: dict[str, list[dict[str, Any]]] = {}
    for r in con.execute(
        """
        SELECT id, kimlik_tipi, nexgen_cari_id, nexgen_tedarikci_id, cari_kart_ckod, aktif, durum
        FROM finans_cari_kimlik
        WHERE cari_kart_ckod IS NOT NULL AND cari_kart_ckod != ''
        """
    ).fetchall():
        ck = str(r['cari_kart_ckod'])
        usage.setdefault(ck, []).append(dict(r))
    return usage


def score_candidate(
    *,
    kimlik_tipi: str,
    op_kod: str,
    op_unvan: str,
    ck: dict[str, Any],
    eslestirme: dict[str, Any] | None,
    ckod_usage: dict[str, list[dict[str, Any]]],
) -> tuple[int, str, list[str], bool]:
    """Güven puanı: 0-100. secilebilir=False ise AUTO_MATCH_SAFE olamaz."""
    engel_kodlari: list[str] = []
    reasons: list[str] = []

    if eslestirme and int(eslestirme.get('aktif') or 0) and eslestirme.get('cari_kart_ckod') == ck['CKod']:
        if eslestirme.get('eslestirme_durumu') in ('DOGRULANDI', 'MANUEL'):
            return 100, 'Mevcut dogrulanmis cari_eslestirme', ['mevcut_mapping'], True

    ctip_val = validate_ctip_for_kimlik(ck, kimlik_tipi)
    if not ctip_val.get('uygun'):
        engel_kodlari.append(ctip_val.get('blok_kodu') or 'CTIP_UYUMSUZ')
        return 0, ctip_val.get('uyari') or 'CTip uyumsuz', engel_kodlari, False

    score = 0
    if normalize_code(op_kod) and normalize_code(op_kod) == normalize_code(ck['CKod']):
        score += 85
        reasons.append('tam_operasyonel_kod_ckod')
    if normalize_metin(op_unvan) == normalize_metin(ck.get('CName') or ''):
        score += 70
        reasons.append('tam_unvan_eslesme')
    else:
        sim = unvan_similarity(op_unvan, ck.get('CName') or '')
        if sim >= 0.92:
            score += 45
            reasons.append(f'unvan_yuksek_benzerlik:{sim:.2f}')
        elif sim >= 0.75:
            score += 25
            reasons.append(f'unvan_orta_benzerlik:{sim:.2f}')
        elif sim >= 0.55:
            score += 10
            reasons.append(f'unvan_dusuk_benzerlik:{sim:.2f}')

    vn_ck = (ck.get('VergiNo') or '').strip()
    if vn_ck:
        reasons.append('vergi_no_kartta_var_eksik_operasyonel')

    score = min(score, 100)

    same_tip = [
        u for u in ckod_usage.get(ck['CKod'], [])
        if u.get('kimlik_tipi') == kimlik_tipi and int(u.get('aktif') or 0)
    ]
    if same_tip:
        engel_kodlari.append(f'CKOD_AKTIF_{kimlik_tipi}')
        return min(score, 40), 'Ayni CKod aktif kimlikte', reasons + engel_kodlari, False

    secilebilir = score >= 85 and 'tam_operasyonel_kod_ckod' in reasons
    if score >= 40 and not secilebilir and 'unvan' in ''.join(reasons):
        engel_kodlari.append('YALNIZ_UNVAN_YETERLI_DEGIL')

    detail = '; '.join(reasons) if reasons else 'aday_sinyal_yok'
    if engel_kodlari:
        detail += ' | engel:' + ','.join(engel_kodlari)
    return score, detail, reasons, secilebilir


def pick_karar_sinifi(
    *,
    kimlik_tipi: str,
    aktif: int,
    mevcut_kimlik: bool,
    eslestirme: dict[str, Any] | None,
    ck_map: dict[str, dict[str, Any]],
    best: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    engel_kodlari: list[str],
) -> str:
    if not aktif:
        return 'OPERATIONAL_INACTIVE'
    if eslestirme and int(eslestirme.get('aktif') or 0):
        ckod = eslestirme.get('cari_kart_ckod')
        if ckod and ckod not in ck_map:
            return 'CARD_NOT_FOUND'
        if eslestirme.get('eslestirme_durumu') in ('DOGRULANDI', 'MANUEL') and ckod:
            return 'LINK_EXISTING_VERIFIED'
    if engel_kodlari and all(e.startswith('CKOD') or 'CAKISMA' in e for e in engel_kodlari):
        return 'CKOD_CONFLICT'
    valid = [c for c in candidates if c.get('guven_puani', 0) > 0]
    best_valid = valid[0] if valid else None
    secilebilir = [c for c in valid if c.get('secilebilir')]
    if kimlik_tipi == 'TEDARIKCI':
        if not valid:
            return 'NO_MATCHING_CARI_KART'
        if best_valid and not best_valid.get('ctip_uygun'):
            return 'CTIP_MISMATCH'
        if best_valid and best_valid.get('secilebilir') and best_valid.get('guven_puani', 0) >= 85:
            if 'tam_operasyonel_kod_ckod' in (best_valid.get('neden') or ''):
                return 'AUTO_MATCH_SAFE'
        if best_valid and best_valid.get('guven_puani', 0) >= 25:
            return 'MANUAL_REVIEW'
        return 'CREATE_IDENTITY_ONLY'
    if best_valid and not best_valid.get('ctip_uygun'):
        return 'CTIP_MISMATCH'
    if best_valid and best_valid.get('secilebilir') and len(secilebilir) == 1 and best_valid.get('guven_puani', 0) >= 85:
        return 'AUTO_MATCH_SAFE'
    if eslestirme and eslestirme.get('eslestirme_durumu') == 'DOGRULANDI':
        return 'LINK_EXISTING_VERIFIED'
    if best_valid and best_valid.get('guven_puani', 0) >= 30:
        return 'MANUAL_REVIEW'
    if engel_kodlari:
        if any('CTIP' in e for e in engel_kodlari):
            return 'CTIP_MISMATCH'
        if any('CKOD' in e for e in engel_kodlari):
            return 'CKOD_CONFLICT'
    return 'CREATE_IDENTITY_ONLY'


def build_candidates(
    con: sqlite3.Connection,
    *,
    kimlik_tipi: str,
    op_kod: str,
    op_unvan: str,
    eslestirme: dict[str, Any] | None,
    ck_map: dict[str, dict[str, Any]],
    ckod_usage: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    adaylar: list[dict[str, Any]] = []
    for ckod, ck in ck_map.items():
        score, detail, reasons, secilebilir = score_candidate(
            kimlik_tipi=kimlik_tipi,
            op_kod=op_kod,
            op_unvan=op_unvan,
            ck=ck,
            eslestirme=eslestirme,
            ckod_usage=ckod_usage,
        )
        ctip_val = validate_ctip_for_kimlik(ck, kimlik_tipi)
        adaylar.append({
            'cari_kart_ckod': ckod,
            'cari_kart_unvan': ck.get('CName'),
            'ctip_raw': ck.get('CTip'),
            'ctip_normalized': sorted(normalize_ctip(ck.get('CTip'))),
            'ctip_uygun': bool(ctip_val.get('uygun')),
            'guven_puani': score,
            'neden': detail,
            'sinyaller': reasons,
            'secilebilir': secilebilir and bool(ctip_val.get('uygun')),
        })
    adaylar.sort(key=lambda x: (-x['guven_puani'], x['cari_kart_ckod']))
    return adaylar


def analyze_musteri(
    con: sqlite3.Connection,
    row: dict[str, Any],
    eslestirme: dict[str, Any] | None,
    ck_map: dict[str, dict[str, Any]],
    ckod_usage: dict[str, list[dict[str, Any]]],
    mevcut_kimlik: dict[str, Any] | None,
) -> dict[str, Any]:
    candidates = build_candidates(
        con,
        kimlik_tipi='MUSTERI',
        op_kod=row['cari_kod'],
        op_unvan=row['unvan'],
        eslestirme=eslestirme,
        ck_map=ck_map,
        ckod_usage=ckod_usage,
    )
    best = candidates[0] if candidates else None
    engel_kodlari: list[str] = []
    uyarilar: list[str] = []

    ckod_es = eslestirme.get('cari_kart_ckod') if eslestirme else None
    ck_es = ck_map.get(str(ckod_es)) if ckod_es else None
    ctip_raw = ck_es.get('CTip') if ck_es else None
    ctip_norm = sorted(normalize_ctip(ctip_raw)) if ck_es else []
    ctip_uygun = bool(validate_ctip_for_kimlik(ck_es, 'MUSTERI').get('uygun')) if ck_es else None

    if eslestirme and ckod_es and not ck_es:
        engel_kodlari.append('CARD_NOT_FOUND')
        uyarilar.append(f'cari_eslestirme CKod={ckod_es} Cari_Kart yok')
    if eslestirme and ck_es and not ctip_uygun:
        engel_kodlari.append('CTIP_UYUMSUZ')
        uyarilar.append('Mevcut eslestirme CKod CTip musteri icin uygun degil')

    karar = pick_karar_sinifi(
        kimlik_tipi='MUSTERI',
        aktif=int(row.get('aktif') or 0),
        mevcut_kimlik=bool(mevcut_kimlik),
        eslestirme=eslestirme,
        ck_map=ck_map,
        best=best,
        candidates=candidates,
        engel_kodlari=engel_kodlari,
    )

    posting_pot = False
    if karar == 'LINK_EXISTING_VERIFIED' and ck_es and ctip_uygun:
        kimlik_stub = {
            'kimlik_tipi': 'MUSTERI', 'aktif': 1, 'durum': 'DOGRULANDI',
            'cari_kart_ckod': ckod_es,
        }
        posting_pot = bool(hesapla_posting_uygunluk(
            kimlik_stub, operasyonel_aktif=bool(int(row.get('aktif') or 0)),
            cari_kart=ck_es,
        ).get('posting_uygun'))

    return {
        'nexgen_cari_id': row['id'],
        'cari_kod': row['cari_kod'],
        'unvan': row['unvan'],
        'aktif': int(row.get('aktif') or 0),
        'mevcut_finans_kimlik_var': bool(mevcut_kimlik),
        'mevcut_cari_eslestirme_var': bool(eslestirme and int(eslestirme.get('aktif') or 0)),
        'eslestirme_durumu': eslestirme.get('eslestirme_durumu') if eslestirme else None,
        'mevcut_cari_kart_ckod': ckod_es,
        'cari_kart_unvan': ck_es.get('CName') if ck_es else None,
        'ctip_raw': ctip_raw,
        'ctip_normalized': ctip_norm,
        'ctip_uygun': ctip_uygun,
        'posting_uygun_potansiyeli': posting_pot,
        'aday_sayisi': len([c for c in candidates if c['guven_puani'] > 0]),
        'en_iyi_aday': best['cari_kart_ckod'] if best and best['guven_puani'] > 0 else None,
        'en_iyi_aday_nedeni': best.get('neden') if best else None,
        'guven_puani': best.get('guven_puani', 0) if best else 0,
        'karar_sinifi': karar,
        'engel_kodlari': engel_kodlari,
        'uyarilar': uyarilar,
        'adaylar': [c for c in candidates if c['guven_puani'] > 0][:5],
    }


def analyze_tedarikci(
    con: sqlite3.Connection,
    row: dict[str, Any],
    ck_map: dict[str, dict[str, Any]],
    ckod_usage: dict[str, list[dict[str, Any]]],
    mevcut_kimlik: dict[str, Any] | None,
    mevcut_te: dict[str, Any] | None,
) -> dict[str, Any]:
    candidates = build_candidates(
        con,
        kimlik_tipi='TEDARIKCI',
        op_kod=row['kod'],
        op_unvan=row['ad'],
        eslestirme=None,
        ck_map=ck_map,
        ckod_usage=ckod_usage,
    )
    best = candidates[0] if candidates else None
    engel_kodlari: list[str] = []
    uyarilar: list[str] = ['Tedarikci tarafinda golden mapping yok — muhafazakar degerlendirme']

    karar = pick_karar_sinifi(
        kimlik_tipi='TEDARIKCI',
        aktif=int(row.get('aktif') or 0),
        mevcut_kimlik=bool(mevcut_kimlik),
        eslestirme=None,
        ck_map=ck_map,
        best=best,
        candidates=candidates,
        engel_kodlari=engel_kodlari,
    )

    return {
        'nexgen_tedarikci_id': row['id'],
        'kod': row['kod'],
        'unvan_ad': row['ad'],
        'aktif': int(row.get('aktif') or 0),
        'para_birimi': row.get('para_birimi'),
        'varsayilan_vade': row.get('varsayilan_vade'),
        'mevcut_finans_kimlik_var': bool(mevcut_kimlik),
        'mevcut_tedarikci_eslestirme_var': bool(mevcut_te and int(mevcut_te.get('aktif') or 0)),
        'aday_sayisi': len([c for c in candidates if c['guven_puani'] > 0]),
        'en_iyi_aday': best['cari_kart_ckod'] if best and best['guven_puani'] > 0 else None,
        'guven_puani': best.get('guven_puani', 0) if best else 0,
        'ctip_raw': (valid[0].get('ctip_raw') if (valid := [c for c in candidates if c.get('guven_puani', 0) > 0]) else None),
        'ctip_normalized': (valid[0].get('ctip_normalized') if valid else []),
        'ctip_uygun': (valid[0].get('ctip_uygun') if valid else None),
        'karar_sinifi': karar,
        'karar_etiketi': KARAR_ETIKETLERI.get(karar),
        'engel_kodlari': engel_kodlari,
        'uyarilar': uyarilar,
        'adaylar': [c for c in candidates if c['guven_puani'] > 0][:5],
    }


def analyze_conflicts(
    customers: list[dict[str, Any]],
    suppliers: list[dict[str, Any]],
    ck_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []

    ck_musteri: dict[str, list[int]] = {}
    ck_tedarikci: dict[str, list[int]] = {}
    for c in customers:
        ck = c.get('en_iyi_aday') or c.get('mevcut_cari_kart_ckod')
        if ck and c.get('guven_puani', 0) >= 30:
            ck_musteri.setdefault(ck, []).append(c['nexgen_cari_id'])
        if c.get('mevcut_cari_kart_ckod') and c.get('eslestirme_durumu'):
            ck_musteri.setdefault(c['mevcut_cari_kart_ckod'], []).append(c['nexgen_cari_id'])
    for s in suppliers:
        ck = s.get('en_iyi_aday')
        if ck and s.get('guven_puani', 0) >= 30:
            ck_tedarikci.setdefault(ck, []).append(s['nexgen_tedarikci_id'])

    for ck, ids in ck_musteri.items():
        if len(set(ids)) > 1:
            conflicts.append({
                'tip': 'AYNI_CKOD_COKLU_MUSTERI',
                'cari_kart_ckod': ck,
                'nexgen_cari_ids': sorted(set(ids)),
            })
    for ck, ids in ck_tedarikci.items():
        if len(set(ids)) > 1:
            conflicts.append({
                'tip': 'AYNI_CKOD_COKLU_TEDARIKCI',
                'cari_kart_ckod': ck,
                'nexgen_tedarikci_ids': sorted(set(ids)),
            })

    for ck in set(ck_musteri) & set(ck_tedarikci):
        card = ck_map.get(ck, {})
        norm = normalize_ctip(card.get('CTip'))
        izinli = 'MUSTERI' in norm and 'TEDARIKCI' in norm
        conflicts.append({
            'tip': 'AYNI_CKOD_MUSTERI_TEDARIKCI',
            'cari_kart_ckod': ck,
            'ctip_normalized': sorted(norm),
            'izinli_potansiyel': izinli,
            'musteri_ids': sorted(set(ck_musteri.get(ck, []))),
            'tedarikci_ids': sorted(set(ck_tedarikci.get(ck, []))),
            'uyari': None if izinli else 'CTip her iki tip icin uygun degil',
        })

    for c in customers:
        if c.get('mevcut_cari_kart_ckod') and c.get('en_iyi_aday'):
            if (
                c['en_iyi_aday'] != c['mevcut_cari_kart_ckod']
                and c.get('guven_puani', 0) >= 50
                and c.get('karar_sinifi') != 'LINK_EXISTING_VERIFIED'
            ):
                conflicts.append({
                    'tip': 'ESLESTIRME_ADAY_CELISKISI',
                    'nexgen_cari_id': c['nexgen_cari_id'],
                    'mevcut_ckod': c['mevcut_cari_kart_ckod'],
                    'onerilen_ckod': c['en_iyi_aday'],
                })

    return conflicts


def analyze_ctip(ck_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    dagilim: dict[str, int] = {}
    anomalies: list[dict[str, Any]] = []
    for ckod, ck in ck_map.items():
        raw = ck.get('CTip')
        key = str(raw)
        dagilim[key] = dagilim.get(key, 0) + 1
        norm = sorted(normalize_ctip(raw))
        if not norm:
            anomalies.append({'CKod': ckod, 'CTip': raw, 'tip': 'BILINMEYEN'})
    m099 = ck_map.get('M099')
    m099_report = None
    if m099:
        norm = sorted(normalize_ctip(m099.get('CTip')))
        m099_report = {
            'CKod': 'M099',
            'CTip_raw': m099.get('CTip'),
            'normalize_sonuc': norm,
            'musteri_uygun': 'MUSTERI' in norm,
            'tedarikci_uygun': 'TEDARIKCI' in norm,
            'db_duzeltmesi_yapilmadi': True,
            'servis_tolere_edildi': True,
            'not': "CTip='MUSTERI' metin degeri servis normalize_ctip ile MUSTERI kabul edilir",
        }
    return {
        'dagilim': dagilim,
        'anomaliler': anomalies,
        'm099': m099_report,
    }


def simulate_backfill(customers: list[dict[str, Any]], suppliers: list[dict[str, Any]]) -> dict[str, Any]:
    sim = {
        'finans_cari_kimlik_insert_musteri': 0,
        'finans_cari_kimlik_insert_tedarikci': 0,
        'musteri_ckod_sync': 0,
        'tedarikci_eslestirme_insert': 0,
        'tedarikci_ckod_sync': 0,
        'durum_bekliyor': 0,
        'durum_dogrulandi': 0,
        'durum_manuel': 0,
        'engelli': 0,
    }
    for c in customers:
        if c.get('mevcut_finans_kimlik_var'):
            continue
        sim['finans_cari_kimlik_insert_musteri'] += 1
        k = c['karar_sinifi']
        if k == 'LINK_EXISTING_VERIFIED':
            sim['musteri_ckod_sync'] += 1
            sim['durum_dogrulandi'] += 1
        elif k == 'AUTO_MATCH_SAFE':
            sim['musteri_ckod_sync'] += 1
            sim['durum_dogrulandi'] += 1
        elif k in ('CTIP_MISMATCH', 'CKOD_CONFLICT', 'CARD_NOT_FOUND', 'DATA_ERROR', 'OPERATIONAL_INACTIVE'):
            sim['engelli'] += 1
            sim['durum_bekliyor'] += 1
        elif k in ('NO_MATCHING_CARI_KART', 'CREATE_IDENTITY_ONLY'):
            sim['durum_bekliyor'] += 1
        elif k == 'MANUAL_REVIEW':
            sim['durum_manuel'] += 1
        else:
            sim['durum_bekliyor'] += 1
    for s in suppliers:
        if s.get('mevcut_finans_kimlik_var'):
            continue
        sim['finans_cari_kimlik_insert_tedarikci'] += 1
        k = s['karar_sinifi']
        if k == 'AUTO_MATCH_SAFE':
            sim['tedarikci_eslestirme_insert'] += 1
            sim['tedarikci_ckod_sync'] += 1
            sim['durum_dogrulandi'] += 1
        elif k in ('CTIP_MISMATCH', 'CKOD_CONFLICT', 'CARD_NOT_FOUND', 'DATA_ERROR', 'OPERATIONAL_INACTIVE'):
            sim['engelli'] += 1
            sim['durum_bekliyor'] += 1
        elif k in ('NO_MATCHING_CARI_KART', 'CREATE_IDENTITY_ONLY'):
            sim['durum_bekliyor'] += 1
        elif k == 'MANUAL_REVIEW':
            sim['durum_manuel'] += 1
        else:
            sim['durum_bekliyor'] += 1
    sim['finans_cari_kimlik_insert_toplam'] = (
        sim['finans_cari_kimlik_insert_musteri'] + sim['finans_cari_kimlik_insert_tedarikci']
    )
    return sim


def classify_abc(customers: list[dict[str, Any]], suppliers: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    a, b, c = [], [], []
    for row in customers + suppliers:
        k = row['karar_sinifi']
        entry = {
            'tip': 'MUSTERI' if 'nexgen_cari_id' in row else 'TEDARIKCI',
            'id': row.get('nexgen_cari_id') or row.get('nexgen_tedarikci_id'),
            'kod': row.get('cari_kod') or row.get('kod'),
            'karar_sinifi': k,
            'guven_puani': row.get('guven_puani', 0),
            'en_iyi_aday': row.get('en_iyi_aday') or row.get('mevcut_cari_kart_ckod'),
        }
        if k in ('LINK_EXISTING_VERIFIED', 'AUTO_MATCH_SAFE', 'CREATE_IDENTITY_ONLY', 'NO_MATCHING_CARI_KART'):
            if k in ('LINK_EXISTING_VERIFIED', 'AUTO_MATCH_SAFE'):
                a.append(entry)
            elif k == 'NO_MATCHING_CARI_KART':
                a.append({**entry, 'not': KARAR_ETIKETLERI['NO_MATCHING_CARI_KART']})
            else:
                a.append({**entry, 'not': 'yalnizca kimlik olusturma'})
        elif k in ('MANUAL_REVIEW',):
            b.append(entry)
        else:
            c.append(entry)
    return {'A_otomatik_guvenli': a, 'B_manuel_onay': b, 'C_engelli': c}


def proposed_actions(customers: list[dict[str, Any]], suppliers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for c in customers:
        act = {
            'hedef': 'MUSTERI',
            'nexgen_cari_id': c['nexgen_cari_id'],
            'karar_sinifi': c['karar_sinifi'],
            'steps': [],
        }
        if not c.get('mevcut_finans_kimlik_var'):
            act['steps'].append({'action': 'create_kimlik_musteri', 'idempotent': True})
        if c['karar_sinifi'] == 'LINK_EXISTING_VERIFIED':
            act['steps'].append({
                'action': 'sync_musteri_ckod_from_eslestirme',
                'cari_kart_ckod': c.get('mevcut_cari_kart_ckod'),
            })
        elif c['karar_sinifi'] == 'AUTO_MATCH_SAFE':
            act['steps'].append({
                'action': 'sync_musteri_ckod',
                'cari_kart_ckod': c.get('en_iyi_aday'),
            })
        actions.append(act)
    for s in suppliers:
        act = {
            'hedef': 'TEDARIKCI',
            'nexgen_tedarikci_id': s['nexgen_tedarikci_id'],
            'karar_sinifi': s['karar_sinifi'],
            'steps': [],
        }
        if not s.get('mevcut_finans_kimlik_var'):
            act['steps'].append({'action': 'create_kimlik_tedarikci', 'idempotent': True})
        if s['karar_sinifi'] == 'AUTO_MATCH_SAFE':
            act['steps'].append({
                'action': 'create_or_update_tedarikci_eslestirme',
                'cari_kart_ckod': s.get('en_iyi_aday'),
            })
        actions.append(act)
    return actions


def summarize_class(rows: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {k: 0 for k in KARAR_SINIFLARI}
    out['toplam'] = len(rows)
    out['aktif'] = sum(1 for r in rows if int(r.get('aktif') or 0))
    out['pasif'] = out['toplam'] - out['aktif']
    for r in rows:
        k = r.get('karar_sinifi', 'DATA_ERROR')
        out[k] = out.get(k, 0) + 1
    return out


def build_report(
    *,
    output_dir: Path,
    before: dict[str, Any],
    after: dict[str, Any],
    customers: list[dict[str, Any]],
    suppliers: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    ctip: dict[str, Any],
    simulation: dict[str, Any],
    abc: dict[str, Any],
    guven_formulu: str,
) -> str:
    mus_oz = summarize_class(customers)
    ted_oz = summarize_class(suppliers)
    verified = [c for c in customers if c['karar_sinifi'] == 'LINK_EXISTING_VERIFIED']
    manual = [x for x in customers + suppliers if x['karar_sinifi'] == 'MANUAL_REVIEW']
    return f"""# FAZ-F1-4 Finans Cari Kimlik Backfill Dry-Run Raporu

**Backup:** `{output_dir}`  
**Mod:** READ-ONLY (apply kapalı)

## 1. Yönetici özeti

- {len(customers)} müşteri, {len(suppliers)} tedarikçi analiz edildi.
- Mevcut doğrulanmış `cari_eslestirme`: {sum(1 for c in customers if c.get('mevcut_cari_eslestirme_var'))} kayıt.
- Güvenli otomatik eşleşme (müşteri): {mus_oz.get('AUTO_MATCH_SAFE', 0)}; tedarikçi: {ted_oz.get('AUTO_MATCH_SAFE', 0)}.
- Simüle kimlik INSERT: {simulation.get('finans_cari_kimlik_insert_toplam', 0)} (müşteri {simulation.get('finans_cari_kimlik_insert_musteri', 0)} + tedarikçi {simulation.get('finans_cari_kimlik_insert_tedarikci', 0)}).
- Ana DB SHA değişmedi: `{before['sha256']}`.

## 2. Dry-run kapsamı

- Kaynak DB: `{before['db_path']}`
- Tablolar: nexgen_cari, nexgen_tedarikci, Cari_Kart, cari_eslestirme, finans_cari_kimlik, tedarikci_eslestirme
- Yazma: **YOK** (`PRAGMA query_only`, `--apply` reddedilir)

## 3. Ana DB koruma kanıtı

| Metrik | Önce | Sonra |
|--------|------|-------|
| SHA-256 | `{before['sha256']}` | `{after['sha256']}` |
| Boyut | {before['size_bytes']} | {after['size_bytes']} |
| integrity | {before['integrity_check']} | {after['integrity_check']} |
| Cari_Har | {before['cari_har']} | {after['cari_har']} |
| finans_cari_kimlik | {before['finans_cari_kimlik']} | {after['finans_cari_kimlik']} |

## 4. Müşteri sonuçları

{json.dumps(mus_oz, ensure_ascii=False, indent=2)}

## 5. Tedarikçi sonuçları

{json.dumps(ted_oz, ensure_ascii=False, indent=2)}

## 6. Mevcut doğrulanmış eşleşmeler

{chr(10).join(f"- cari_id={c['nexgen_cari_id']} → CKod {c.get('mevcut_cari_kart_ckod')} ({c.get('eslestirme_durumu')})" for c in verified) or '- Yok'}

## 7. Otomatik eşleşme adayları

- Müşteri AUTO_MATCH_SAFE: {mus_oz.get('AUTO_MATCH_SAFE', 0)}
- Tedarikçi AUTO_MATCH_SAFE: {ted_oz.get('AUTO_MATCH_SAFE', 0)}

## 8. Manuel inceleme gerekenler

{len(manual)} kayıt — detay: `customer_candidates.json` / `supplier_candidates.json`

## 9. CTip anomali analizi

{json.dumps(ctip.get('m099'), ensure_ascii=False, indent=2) if ctip.get('m099') else 'M099 yok'}

Dağılım: {json.dumps(ctip.get('dagilim'), ensure_ascii=False)}

## 10. CKod çakışmaları

Toplam: {len(conflicts)} — detay: `conflicts.json`

## 11. Pasif ve hatalı kayıtlar

- OPERATIONAL_INACTIVE müşteri: {mus_oz.get('OPERATIONAL_INACTIVE', 0)}
- OPERATIONAL_INACTIVE tedarikçi: {ted_oz.get('OPERATIONAL_INACTIVE', 0)}

## 12. Simüle backfill sonucu

{json.dumps(simulation, ensure_ascii=False, indent=2)}

## 13. Apply sırasında önerilen sıralama

1. finans_cari_kimlik MUSTERI create (idempotent)
2. LINK_EXISTING_VERIFIED müşteri CKod sync
3. finans_cari_kimlik TEDARIKCI create (idempotent)
4. Manuel onaylı tedarikçi eşleştirmeleri

## 14. Apply transaction planı

- Her kayıt: BEGIN → servis çağrısı (commit=False) → route commit
- Hata: ROLLBACK, sonraki kayda geç

## 15. Rollback planı

- Apply öncesi timestamp'li DB backup
- Kayıt bazlı geri alma: finans_cari_kimlik pasife al / tedarikci_eslestirme iptal

## 16. Manuel karar gereken kayıtlar

Grup B: {len(abc.get('B_manuel_onay', []))} kayıt — `summary.json` → `abc_classification`

## 17. Ana DB SHA önce/sonra

`{before['sha256']}` = `{after['sha256']}`

## 18. Mantıksal hash önce/sonra

Tüm kritik tablo hash'leri eşit.

## 19. Bilinen riskler

1. Operasyonel kod ile Cari_Kart CKod farklı namespace (120.NX.* vs M00*)
2. Tedarikçi otomatik eşleşme bilinçli olarak muhafazakâr
3. M099 CTip metin anomalisi servis katmanında tolere edilir

## 20. F1-5 UI veya apply öncesi öneri

Grup A/B/C listesini inceleyin; apply ayrı onay emri ile açılacaktır.

---

## Güven puanı formülü

{guven_formulu}
"""


def run_dryrun(db_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    before = collect_db_evidence(db_path)
    lines.append(f"pre_sha={before['sha256']}")

    con = readonly_connect(db_path)
    try:
        ck_map = load_cari_kart_map(con)
        eslestirmeler = load_eslestirmeler(con)
        ckod_usage = load_kimlik_usage(con)

        kimlik_map = {
            int(r['nexgen_cari_id']): dict(r)
            for r in con.execute(
                'SELECT * FROM finans_cari_kimlik WHERE kimlik_tipi=\'MUSTERI\''
            ).fetchall()
            if r['nexgen_cari_id']
        }
        ted_kimlik = {
            int(r['nexgen_tedarikci_id']): dict(r)
            for r in con.execute(
                'SELECT * FROM finans_cari_kimlik WHERE kimlik_tipi=\'TEDARIKCI\''
            ).fetchall()
            if r['nexgen_tedarikci_id']
        }
        ted_es_map = {
            int(r['nexgen_tedarikci_id']): dict(r)
            for r in con.execute('SELECT * FROM tedarikci_eslestirme').fetchall()
        }

        customers = []
        for row in con.execute('SELECT * FROM nexgen_cari ORDER BY id').fetchall():
            r = dict(row)
            customers.append(analyze_musteri(
                con, r, eslestirmeler.get(int(r['id'])), ck_map, ckod_usage,
                kimlik_map.get(int(r['id'])),
            ))

        suppliers = []
        for row in con.execute('SELECT * FROM nexgen_tedarikci ORDER BY id').fetchall():
            r = dict(row)
            suppliers.append(analyze_tedarikci(
                con, r, ck_map, ckod_usage, ted_kimlik.get(int(r['id'])),
                ted_es_map.get(int(r['id'])),
            ))

        conflicts = analyze_conflicts(customers, suppliers, ck_map)
        ctip = analyze_ctip(ck_map)
        simulation = simulate_backfill(customers, suppliers)
        abc = classify_abc(customers, suppliers)
        actions = proposed_actions(customers, suppliers)

    finally:
        con.close()

    after = collect_db_evidence(db_path)
    lines.append(f"post_sha={after['sha256']}")

    if before['sha256'] != after['sha256']:
        raise RuntimeError(f"Ana DB SHA degisti: {before['sha256']} -> {after['sha256']}")
    if before['table_hashes'] != after['table_hashes']:
        raise RuntimeError('Ana DB mantiksal hash degisti')

    guven_formulu = """
- Mevcut dogrulanmis cari_eslestirme + ayni CKod: 100 (AUTO/LINK)
- Tam operasyonel kod = CKod + CTip uygun: +85 (AUTO icin zorunlu sinyal)
- Tam unvan eslesmesi + CTip uygun: +70 (tek basina AUTO icin yeterli degil)
- Unvan benzerligi >=0.92: +45; >=0.75: +25; >=0.55: +10 (MANUAL_REVIEW)
- CTip uyumsuz/bilinmeyen: 0 (CTIP_MISMATCH / engelli)
- Ayni CKod aktif ayni tip kimlikte: secilebilir=False (CKOD_CONFLICT)
- Tedarikci: AUTO yalniz tam kod eslesmesi + CTip uygun
"""

    summary = {
        'timestamp': datetime.now().strftime('%Y%m%d_%H%M%S'),
        'mode': 'READ_ONLY',
        'baseline_sha_expected': BASELINE_SHA,
        'db_before_sha': before['sha256'],
        'db_after_sha': after['sha256'],
        'musteri_ozet': summarize_class(customers),
        'tedarikci_ozet': summarize_class(suppliers),
        'simulation': simulation,
        'abc_counts': {k: len(v) for k, v in abc.items()},
        'conflict_count': len(conflicts),
        'guven_puan_formulu': guven_formulu.strip(),
    }

    outputs = {
        'summary.json': summary,
        'customer_candidates.json': customers,
        'supplier_candidates.json': suppliers,
        'conflicts.json': conflicts,
        'ctip_analysis.json': ctip,
        'proposed_actions.json': actions,
        'db_evidence_before.json': before,
        'db_evidence_after.json': after,
    }
    for name, payload in outputs.items():
        (output_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding='utf-8',
        )

    summary['abc_classification'] = abc
    (output_dir / 'summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding='utf-8',
    )

    report = build_report(
        output_dir=output_dir,
        before=before,
        after=after,
        customers=customers,
        suppliers=suppliers,
        conflicts=conflicts,
        ctip=ctip,
        simulation=simulation,
        abc=abc,
        guven_formulu=guven_formulu.strip(),
    )
    (output_dir / 'RAPOR.md').write_text(report, encoding='utf-8')

    files_dir = output_dir / 'files'
    files_dir.mkdir(exist_ok=True)
    shutil.copy2(Path(__file__), files_dir / 'faz_f1_cari_kimlik_dryrun.py')

    (output_dir / 'script_output.txt').write_text('\n'.join(lines), encoding='utf-8')
    lines.append(f'output_dir={output_dir}')
    lines.append('SONUC=PASS')
    return {
        'ok': True,
        'output_dir': str(output_dir),
        'summary': summary,
        'lines': lines,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='FAZ-F1-4 finans cari kimlik backfill dry-run')
    parser.add_argument('--db', default=str(DEFAULT_DB), help='SQLite DB yolu')
    parser.add_argument('--output-dir', default='', help='Cikti klasoru')
    parser.add_argument('--apply', action='store_true', help='DISABLED in F1-4')
    args = parser.parse_args(argv)

    if args.apply:
        print(json.dumps({
            'ok': False,
            'error': {'code': APPLY_DISABLED_CODE, 'message': 'Apply F1-4 kapsaminda kapali'},
        }, ensure_ascii=False))
        return 2

    db_path = Path(args.db)
    if not db_path.exists():
        print(f'DB bulunamadi: {db_path}')
        return 1

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = Path(args.output_dir) if args.output_dir else ROOT / 'backup' / f'faz_f1_4_cari_kimlik_dryrun_{ts}'

    try:
        result = run_dryrun(db_path, output_dir)
        for line in result['lines']:
            print(line)
        return 0
    except Exception as exc:
        print(f'FAIL: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
