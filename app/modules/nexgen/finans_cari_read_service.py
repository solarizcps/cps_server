# -*- coding: utf-8 -*-
"""Finans Merkezi — read-only cari hesap görünürlüğü (FAZ-CARI-CEKIRDEK-1A)."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any

from modules.nexgen.cari360_yetki import can_cari360_dosya_ekrani
from modules.nexgen.cari_golden_master_service import get_golden_master_snapshot
from modules.nexgen.finans_belgesi_config import (
    BELGE_TIP_SATIS_SEVKIYAT,
    DURUM_ETIKET,
    DURUM_KAPANDI,
    DURUM_REDDEDILDI,
)
from modules.nexgen.finans_belgesi_repository import (
    FinansBelgesiError,
    resolve_golden_cari_kart,
    tablo_var,
)
from modules.nexgen.finans_ledger_standard import bakiye_float_dict, compute_bakiye

BAKIYE_UYUM_TOLERANSI = 0.01

_GOLDEN_UI = {
    'DOGRULANDI': ('Doğrulandı', 'yesil'),
    'MANUEL': ('Manuel eşleşti', 'mavi'),
    'BEKLIYOR': ('Eşleşme bekliyor', 'sari'),
    'IPTAL': ('İptal', 'gri'),
    'BULUNAMADI': ('Bulunamadı', 'kirmizi'),
    'CAKISMA': ('Çakışmalı', 'kirmizi'),
    'KART_YOK': ('Kart bulunamadı', 'turuncu'),
}


class FinansCariReadError(Exception):
    def __init__(self, mesaj: str, kod: int = 404, hata_kodu: str | None = None):
        self.mesaj = mesaj
        self.kod = kod
        self.hata_kodu = hata_kodu
        super().__init__(mesaj)


def _float(v: Any) -> float:
    if v in (None, ''):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _today_iso() -> str:
    return date.today().isoformat()


def _legacy_finans_cari_erisim(user_dict: dict | None) -> bool:
    """Legacy /finans/cari erişimi — finans/routes guard ile uyumlu read-only kontrol."""
    if not user_dict:
        return False
    kadi = (user_dict.get('KullaniciAdi') or '').strip().lower()
    adsoyad = (user_dict.get('AdSoyad') or '').strip().lower()
    rol = (user_dict.get('RolAd') or user_dict.get('Rol') or '').strip()
    if kadi == 'admin':
        return True
    if kadi in ('adem', 'altan') or 'adem terzi' in adsoyad or 'altan terzi' in adsoyad:
        return True
    return rol in ('Muhasebe', 'Finans')


def _nexgen_cari_get(con: sqlite3.Connection, cari_id: int) -> dict[str, Any] | None:
    if not tablo_var(con, 'nexgen_cari'):
        return None
    row = con.execute(
        'SELECT id, cari_kod, unvan, aktif FROM nexgen_cari WHERE id=?',
        (int(cari_id),),
    ).fetchone()
    return dict(row) if row else None


def _eslestirme_satirlari(con: sqlite3.Connection, cari_id: int) -> list[dict[str, Any]]:
    if not tablo_var(con, 'cari_eslestirme'):
        return []
    rows = con.execute(
        """
        SELECT id, cari_kart_ckod, eslestirme_durumu, eslestirme_yontemi, aktif
        FROM cari_eslestirme
        WHERE nexgen_cari_id=? AND aktif=1
          AND cari_kart_ckod IS NOT NULL AND cari_kart_ckod != ''
        ORDER BY id DESC
        """,
        (int(cari_id),),
    ).fetchall()
    return [dict(r) for r in rows]


def cari_golden_durum_paket(con: sqlite3.Connection, cari_id: int) -> dict[str, Any]:
    """Golden cari durumu — posting exception UI'yı çökertmez."""
    nc = _nexgen_cari_get(con, cari_id)
    base = {
        'ui_durum': 'BULUNAMADI',
        'ui_etiket': _GOLDEN_UI['BULUNAMADI'][0],
        'ui_renk': _GOLDEN_UI['BULUNAMADI'][1],
        'nexgen_cari_id': int(cari_id),
        'nexgen_cari_kod': nc['cari_kod'] if nc else None,
        'nexgen_cari_unvan': nc['unvan'] if nc else None,
        'cari_kart_ckod': None,
        'cari_kart_unvan': None,
        'posting_uygun': False,
        'posting_engel_kodu': 'CARI_ESLESME_YOK',
        'aciklama': 'Golden cari eşleşmesi bulunamadı.',
    }
    if not nc:
        base['aciklama'] = 'NexGen cari kaydı bulunamadı.'
        base['posting_engel_kodu'] = 'NEXGEN_CARI_YOK'
        return base

    snap = get_golden_master_snapshot(con, int(cari_id))
    es = snap.get('eslestirme') or {}
    es_rows = _eslestirme_satirlari(con, cari_id)
    ckodlar = {r['cari_kart_ckod'] for r in es_rows if r.get('cari_kart_ckod')}

    if len(ckodlar) > 1:
        ui_key = 'CAKISMA'
        base.update({
            'ui_durum': ui_key,
            'ui_etiket': _GOLDEN_UI[ui_key][0],
            'ui_renk': _GOLDEN_UI[ui_key][1],
            'posting_engel_kodu': 'CARI_ESLESME_CAKISMA',
            'aciklama': 'Birden fazla cari kart eşleşmesi — posting engellendi.',
        })
    elif not es_rows and (snap.get('eslestirme_durumu') or '') == 'eslesmemis':
        return base
    else:
        durum = (es.get('eslestirme_durumu') or snap.get('eslestirme_durumu') or 'BEKLIYOR').upper()
        ckod = es.get('cari_kart_ckod') or (es_rows[0]['cari_kart_ckod'] if es_rows else None)
        base['cari_kart_ckod'] = ckod

        if durum == 'IPTAL':
            ui_key = 'IPTAL'
            base.update({
                'ui_durum': ui_key,
                'ui_etiket': _GOLDEN_UI[ui_key][0],
                'ui_renk': _GOLDEN_UI[ui_key][1],
                'posting_engel_kodu': 'CARI_ESLESME_IPTAL',
                'aciklama': 'Cari eşleşmesi iptal edilmiş.',
            })
        elif durum == 'BEKLIYOR':
            ui_key = 'BEKLIYOR'
            base.update({
                'ui_durum': ui_key,
                'ui_etiket': _GOLDEN_UI[ui_key][0],
                'ui_renk': _GOLDEN_UI[ui_key][1],
                'posting_engel_kodu': 'CARI_ESLESME_DOGRULANMADI',
                'aciklama': 'Cari eşleşmesi henüz doğrulanmadı.',
            })
        elif durum in ('DOGRULANDI', 'MANUEL'):
            ui_key = durum
            base.update({
                'ui_durum': ui_key,
                'ui_etiket': _GOLDEN_UI[ui_key][0],
                'ui_renk': _GOLDEN_UI[ui_key][1],
            })
            if ckod:
                ck = con.execute(
                    'SELECT CKod, CName FROM Cari_Kart WHERE CKod=?', (ckod,),
                ).fetchone()
                if ck:
                    base['cari_kart_unvan'] = ck['CName']
                else:
                    ui_key = 'KART_YOK'
                    base.update({
                        'ui_durum': ui_key,
                        'ui_etiket': _GOLDEN_UI[ui_key][0],
                        'ui_renk': _GOLDEN_UI[ui_key][1],
                        'posting_engel_kodu': 'CARI_KART_YOK',
                        'aciklama': f'Cari_Kart kaydı bulunamadı: {ckod}',
                    })
        else:
            base['aciklama'] = f'Bilinmeyen eşleşme durumu: {durum}'

    if base.get('cari_kart_ckod') and base['ui_durum'] not in ('CAKISMA', 'KART_YOK', 'IPTAL', 'BEKLIYOR', 'BULUNAMADI'):
        try:
            resolve_golden_cari_kart(con, int(cari_id))
            base['posting_uygun'] = True
            base['posting_engel_kodu'] = None
            if base['ui_durum'] == 'DOGRULANDI':
                base['aciklama'] = 'Golden cari eşleşmesi doğrulandı — posting için uygun.'
            elif base['ui_durum'] == 'MANUEL':
                base['aciklama'] = 'Manuel cari eşleşmesi — posting için uygun.'
        except FinansBelgesiError as e:
            base['posting_uygun'] = False
            base['posting_engel_kodu'] = e.hata_kodu or 'CARI_ESLESME'
            base['aciklama'] = e.mesaj

    return base


def cari_hareket_ozet(con: sqlite3.Connection, ckod: str) -> dict[str, Any]:
    if not ckod:
        return bakiye_float_dict(compute_bakiye(con, None))
    return bakiye_float_dict(compute_bakiye(con, ckod))


def cari_hareket_liste(
    con: sqlite3.Connection,
    ckod: str,
    limit: int = 15,
) -> list[dict[str, Any]]:
    if not tablo_var(con, 'Cari_Har') or not ckod:
        return []

    rows = con.execute(
        """
        SELECT Id, Tarih, BelgeNo, BelgeTip, Aciklama, Borc, Alacak
        FROM Cari_Har WHERE CKod=?
        ORDER BY Tarih ASC, Id ASC
        """,
        (ckod,),
    ).fetchall()

    bakiye = 0.0
    enriched: list[dict[str, Any]] = []
    fb_map: dict[int, dict[str, Any]] = {}
    if tablo_var(con, 'finans_belgesi') and rows:
        ids = [int(r['Id']) for r in rows]
        placeholders = ','.join('?' * len(ids))
        fb_rows = con.execute(
            f"""
            SELECT id, belge_kodu, cari_har_id
            FROM finans_belgesi
            WHERE cari_har_id IN ({placeholders}) AND aktif=1
            """,
            ids,
        ).fetchall()
        fb_map = {int(r['cari_har_id']): dict(r) for r in fb_rows if r['cari_har_id']}

    for r in rows:
        borc = round(_float(r['Borc']), 2)
        alacak = round(_float(r['Alacak']), 2)
        bakiye = round(bakiye + borc - alacak, 2)
        har_id = int(r['Id'])
        fb = fb_map.get(har_id)
        enriched.append({
            'id': har_id,
            'tarih': r['Tarih'],
            'belge_no': r['BelgeNo'],
            'belge_tip': r['BelgeTip'],
            'aciklama': r['Aciklama'],
            'borc': borc,
            'alacak': alacak,
            'bakiye_sonrasi': bakiye,
            'finans_belgesi_id': fb['id'] if fb else None,
            'finans_belgesi_kodu': fb['belge_kodu'] if fb else None,
            'legacy_kaynak': fb is None,
        })

    enriched.reverse()
    return enriched[: max(1, int(limit or 15))]


def cari_acik_belgeler(con: sqlite3.Connection, cari_id: int) -> dict[str, Any]:
    if not tablo_var(con, 'finans_belgesi'):
        return {
            'aktif_belge_sayisi': 0,
            'aktif_belge_tutar_toplami': 0.0,
            'vadesi_gecen_belge_sayisi': 0,
            'vadesi_gecen_tutar': 0.0,
            'belgeler': [],
        }

    bugun = _today_iso()
    rows = con.execute(
        """
        SELECT id, belge_kodu, belge_tipi, durum, toplam_tutar, para_birimi, vade_tarihi
        FROM finans_belgesi
        WHERE cari_id=? AND aktif=1
          AND durum NOT IN (?, ?)
        ORDER BY id DESC
        LIMIT 50
        """,
        (int(cari_id), DURUM_KAPANDI, DURUM_REDDEDILDI),
    ).fetchall()

    belgeler: list[dict[str, Any]] = []
    aktif_toplam = 0.0
    vadesi_gecen_sayisi = 0
    vadesi_gecen_tutar = 0.0

    for r in rows:
        d = dict(r)
        tutar = round(_float(d.get('toplam_tutar')), 2)
        aktif_toplam += tutar
        vade = (d.get('vade_tarihi') or '')[:10] or None
        vadesi_gecti = (
            (d.get('belge_tipi') or '') == BELGE_TIP_SATIS_SEVKIYAT
            and vade is not None
            and vade < bugun
        )
        if vadesi_gecti:
            vadesi_gecen_sayisi += 1
            vadesi_gecen_tutar += tutar
        durum = d.get('durum')
        belgeler.append({
            'id': d['id'],
            'belge_kodu': d['belge_kodu'],
            'belge_tipi': d['belge_tipi'],
            'durum': durum,
            'durum_etiket': DURUM_ETIKET.get(durum, durum),
            'toplam_tutar': tutar,
            'para_birimi': d.get('para_birimi') or 'TRY',
            'vade_tarihi': vade,
            'vadesi_gecti': vadesi_gecti,
        })

    return {
        'aktif_belge_sayisi': len(belgeler),
        'aktif_belge_tutar_toplami': round(aktif_toplam, 2),
        'vadesi_gecen_belge_sayisi': vadesi_gecen_sayisi,
        'vadesi_gecen_tutar': round(vadesi_gecen_tutar, 2),
        'belgeler': belgeler,
    }


def _navigasyon_paket(
    con: sqlite3.Connection,
    cari_id: int,
    ckod: str | None,
    yk: set[str] | frozenset[str] | None,
    user_dict: dict | None,
) -> dict[str, Any]:
    nc = _nexgen_cari_get(con, cari_id)
    c360 = bool(nc and yk is not None and can_cari360_dosya_ekrani(yk))
    legacy = bool(ckod and _legacy_finans_cari_erisim(user_dict))
    return {
        'cari360_url': f'/nexgen/cari360/{int(cari_id)}' if c360 else None,
        'cari360_erisim': c360,
        'legacy_cari_url': f'/finans/cari/{ckod}' if legacy and ckod else None,
        'legacy_cari_erisim': legacy,
    }


def cari_hesap_paket(
    con: sqlite3.Connection,
    cari_id: int,
    yk: set[str] | frozenset[str] | None = None,
    user_dict: dict | None = None,
) -> dict[str, Any]:
    nc = _nexgen_cari_get(con, cari_id)
    if not nc:
        raise FinansCariReadError('NexGen cari bulunamadı.', 404, 'NEXGEN_CARI_YOK')

    golden = cari_golden_durum_paket(con, cari_id)
    ckod = golden.get('cari_kart_ckod')
    uyarilar: list[dict[str, str]] = []

    bakiye: dict[str, Any] = {
        'hareket_sayisi': 0,
        'toplam_borc': 0.0,
        'toplam_alacak': 0.0,
        'bakiye': 0.0,
        'cari_har_bakiye': 0.0,
        'cari_kart_bakiye': None,
        'bakiye_farki': None,
        'uyumlu': True,
        'kaynak': 'Cari_Har',
        'mevcut': False,
    }
    son_hareketler: list[dict[str, Any]] = []

    if not golden.get('posting_uygun') and golden.get('ui_durum') != 'DOGRULANDI':
        if golden.get('ui_durum') in ('BULUNAMADI', 'BEKLIYOR', 'CAKISMA', 'KART_YOK', 'IPTAL'):
            uyarilar.append({
                'kod': golden.get('posting_engel_kodu') or 'GOLDEN_EKSIK',
                'mesaj': golden.get('aciklama') or 'Golden cari eşleşmesi eksik.',
            })

    if ckod and golden.get('ui_durum') not in ('CAKISMA', 'KART_YOK'):
        bakiye = cari_hareket_ozet(con, ckod)
        bakiye['mevcut'] = bakiye['hareket_sayisi'] > 0
        son_hareketler = cari_hareket_liste(con, ckod, limit=15)
        legacy_count = sum(1 for h in son_hareketler if h.get('legacy_kaynak'))
        if legacy_count > 0:
            uyarilar.append({
                'kod': 'LEGACY_HAREKET',
                'mesaj': (
                    f'Son hareketler arasında {legacy_count} legacy/mock kayıt var. '
                    'NexGen finans belgesi bağlantısı yalnızca post edilmiş belgelerde görünür.'
                ),
            })
        if not bakiye.get('uyumlu'):
            uyarilar.append({
                'kod': 'BAKIYE_UYUMSUZ',
                'mesaj': (
                    f'Cari_Kart.Bakiye ({bakiye.get("cari_kart_bakiye")}) ile '
                    f'Cari_Har türetilmiş bakiye ({bakiye.get("cari_har_bakiye")}) uyumsuz '
                    f'(fark: {bakiye.get("bakiye_farki")}). Ekranda Cari_Har kaynak alınır.'
                ),
            })
    elif not ckod:
        uyarilar.append({
            'kod': 'HAREKET_YOK_GOLDEN',
            'mesaj': 'Golden eşleşme olmadan Cari_Har hareketleri gösterilemez.',
        })

    acik = cari_acik_belgeler(con, cari_id)

    return {
        'nexgen_cari': {
            'id': nc['id'],
            'cari_kod': nc['cari_kod'],
            'unvan': nc['unvan'],
            'aktif': bool(nc.get('aktif', 1)),
        },
        'golden': golden,
        'bakiye': bakiye,
        'acik_belgeler': acik,
        'son_hareketler': son_hareketler,
        'navigasyon': _navigasyon_paket(con, cari_id, ckod, yk, user_dict),
        'uyarilar': uyarilar,
    }
