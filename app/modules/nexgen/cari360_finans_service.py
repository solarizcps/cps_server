# -*- coding: utf-8 -*-
"""Cari360 Finans Sekmesi — read-only özet.

Kaynaklar:
  1. mo_tahsilat_kayit (cari_id direkt)
  2. nexgen_planlama_siparis (vade / çek)
  3. Cari_Har + Cari_Kart — yalnız cari_eslestirme.aktif=1
                             ve eslestirme_durumu='DOGRULANDI' olan carilerde.
     Eşleşme yoksa → "Finans eşleşmesi yok" mesajı, 0 değil.

YASAK: risk skoru, cari limit, sahte veri.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from modules.nexgen.finans_ledger_standard import bakiye_float_dict, compute_bakiye


def _tablo_var(con: sqlite3.Connection, ad: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (ad,)
    ).fetchone())


def _cols(con: sqlite3.Connection, tablo: str) -> set[str]:
    return {r[1] for r in con.execute(f'PRAGMA table_info({tablo})')}


def _float(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Legacy köprü — cari_eslestirme → Cari_Har / Cari_Kart
# ---------------------------------------------------------------------------

def _legacy_ckod(con: sqlite3.Connection, cari_id: int) -> str | None:
    """Yalnız aktif=1 ve DOGRULANDI eşleşmesi döndürür."""
    if not _tablo_var(con, 'cari_eslestirme'):
        return None
    row = con.execute(
        """SELECT cari_kart_ckod FROM cari_eslestirme
           WHERE nexgen_cari_id=? AND aktif=1
             AND eslestirme_durumu='DOGRULANDI'
             AND cari_kart_ckod IS NOT NULL AND cari_kart_ckod != ''
           ORDER BY id DESC LIMIT 1""",
        (int(cari_id),),
    ).fetchone()
    return row['cari_kart_ckod'] if row else None


def _legacy_bakiye(con: sqlite3.Connection, ckod: str | None) -> dict[str, Any]:
    """Cari_Har bakiyesi + Cari_Kart.Bakiye fallback bilgisi."""
    if not ckod:
        return {'eslesme': False, 'mesaj': 'Finans eşleşmesi yok'}

    bpak = bakiye_float_dict(compute_bakiye(con, ckod))

    if not bpak.get('mevcut'):
        # Cari_Har satırı yok — Cari_Kart.Bakiye fallback
        kart_bak = bpak.get('cari_kart_bakiye')
        if kart_bak is not None:
            return {
                'eslesme': True,
                'ckod': ckod,
                'kaynak': 'Cari_Kart (kart bakiyesi)',
                'bakiye': float(kart_bak),
                'borc': None,
                'alacak': None,
                'acik_bakiye': None,
                'uyari': 'Cari_Har hareketi bulunamadı — Cari_Kart.Bakiye gösterilmektedir.',
            }
        return {'eslesme': True, 'ckod': ckod, 'mesaj': 'Finans eşleşmesi var ama hareket kaydı yok'}

    return {
        'eslesme': True,
        'ckod': ckod,
        'kaynak': 'Cari_Har',
        'bakiye': bpak.get('bakiye'),
        'borc': bpak.get('toplam_borc'),
        'alacak': bpak.get('toplam_alacak'),
        'acik_bakiye': bpak.get('bakiye'),
        'hareket_sayisi': bpak.get('hareket_sayisi'),
        'ilk_islem': bpak.get('ilk_islem_tarihi'),
        'son_islem': bpak.get('son_islem_tarihi'),
        'cari_kart_bakiye': bpak.get('cari_kart_bakiye'),
        'uyumlu': bpak.get('uyumlu'),
        'bakiye_farki': bpak.get('bakiye_farki'),
    }


# ---------------------------------------------------------------------------
# Tahsilat özeti — mo_tahsilat_kayit
# ---------------------------------------------------------------------------

def _tahsilat_ozet(con: sqlite3.Connection, cari_id: int) -> dict[str, Any]:
    if not _tablo_var(con, 'mo_tahsilat_kayit'):
        return {}
    cid = int(cari_id)

    rows = con.execute(
        """SELECT durum, alinan_tutar, beklenen_tutar, kalan_tutar,
                  alinan_tarih, planlanan_tahsilat_tarihi
           FROM mo_tahsilat_kayit
           WHERE cari_id=? AND COALESCE(aktif,1)=1""",
        (cid,),
    ).fetchall()

    alinan_top = 0.0
    bekleyen_top = 0.0
    kalan_top = 0.0
    gecikme_n = 0
    son_tarih = None
    son_tutar = None

    for r in rows:
        d = (r['durum'] or '').upper()
        if d == 'ONAYLANDI':
            t = _float(r['alinan_tutar'])
            alinan_top += t
            at = r['alinan_tarih'] or ''
            if at and (son_tarih is None or at > son_tarih):
                son_tarih = at
                son_tutar = t
            pt = r['planlanan_tahsilat_tarihi'] or ''
            if pt and at and at > pt:
                gecikme_n += 1
        elif d not in ('IPTAL', 'REDDEDILDI'):
            bekleyen_top += _float(r['beklenen_tutar'])
            kalan_top += _float(r['kalan_tutar'])

    return {
        'alinan_toplam': round(alinan_top, 2),
        'bekleyen_toplam': round(bekleyen_top, 2),
        'kalan_toplam': round(kalan_top, 2),
        'son_tahsilat_tarihi': son_tarih,
        'son_tahsilat_tutari': round(son_tutar, 2) if son_tutar is not None else None,
        'gecikme_sayisi': gecikme_n,
    }


# ---------------------------------------------------------------------------
# Vade / Çek özeti — nexgen_planlama_siparis
# ---------------------------------------------------------------------------

def _vade_cek_ozet(con: sqlite3.Connection, cari_id: int) -> dict[str, Any]:
    if not _tablo_var(con, 'nexgen_planlama_siparis'):
        return {}
    cid = int(cari_id)
    # Ticari olarak geçerli durumlar — TASLAK/REDDEDILDI/IPTAL/REVIZYON hariç
    _VADE_CEK_HARIC = frozenset({
        'TASLAK', 'REDDEDILDI', 'REVIZYON',
        'IPTAL', 'IPTAL_EDILDI', 'IPTALEDILDI',
    })

    scols = _cols(con, 'nexgen_planlama_siparis')
    extra_cek = ', cek_vadesi' if 'cek_vadesi' in scols else ''

    all_rows = con.execute(
        f"SELECT vade_gun, odeme_tipi{extra_cek}, UPPER(TRIM(COALESCE(durum,''))) AS d "
        "FROM nexgen_planlama_siparis WHERE cari_id=?",
        (cid,),
    ).fetchall()

    vade_list = [
        _float(r['vade_gun']) for r in all_rows
        if _float(r['vade_gun']) > 0
        and r['d'] not in _VADE_CEK_HARIC
    ]
    ort_vade = round(sum(vade_list) / len(vade_list), 1) if vade_list else None

    cek_rows = [
        r for r in all_rows
        if (r['odeme_tipi'] or '').upper().strip() == 'CEK'
        and r['d'] not in _VADE_CEK_HARIC
    ]
    cek_sayisi = len(cek_rows)
    cek_vadeleri = sorted({
        r['cek_vadesi'] for r in cek_rows
        if 'cek_vadesi' in scols and r['cek_vadesi']
    })

    return {
        'ortalama_vade_gun': ort_vade,
        'vade_ornekleri_n': len(vade_list),
        'cekli_siparis_sayisi': cek_sayisi,
        'cek_vadeleri': cek_vadeleri[:10],
        'kapsam_notu': 'TASLAK/REDDEDILDI/IPTAL/REVIZYON hariç.',
    }


# ---------------------------------------------------------------------------
# Ana yükleme fonksiyonu
# ---------------------------------------------------------------------------

def load_cari360_finans(
    con: sqlite3.Connection,
    cari_id: int,
) -> dict[str, Any]:
    """Cari360 finans sekmesi payload — yalnız gerçek kaynaklar."""
    cid = int(cari_id)

    ckod = _legacy_ckod(con, cid)
    legacy = _legacy_bakiye(con, ckod)
    tahsilat = _tahsilat_ozet(con, cid)
    vade_cek = _vade_cek_ozet(con, cid)

    return {
        'cari_id': cid,
        'eslesme': legacy,
        'tahsilat': tahsilat,
        'vade_cek': vade_cek,
        'risk': None,
        'limit': None,
        'risk_notu': 'Risk kaynağı tanımlı değil.',
        'limit_notu': 'Cari limit kaynağı tanımlı değil.',
    }
