# -*- coding: utf-8 -*-
"""Cari360 ilişki / başlangıç tipi politikası (FAZ-3C).

SELECT-only. Timeline ve ops API aynı sınıflandırmayı kullanır.
Merkez: nexgen_cari.id
"""
from __future__ import annotations

import sqlite3
from typing import Any

# Parent type (API contract — kısa kod)
PARENT_CARI = 'CARI'
PARENT_GORUSME = 'GORUSME'
PARENT_NUMUNE = 'NUMUNE'
PARENT_ARGE = 'ARGE'
PARENT_SIPARIS = 'SIPARIS'
PARENT_PLAN = 'PLAN'


def iid(v: Any) -> int | None:
    if v in (None, '', 0, '0'):
        return None
    try:
        i = int(v)
        return i if i > 0 else None
    except (TypeError, ValueError):
        return None


def _tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def zincir_alanlari(
    *,
    parent_type: str | None,
    parent_id: int | None,
    baslangic_tipi: str,
    zincir_eksik: bool = False,
    zincir_uyarilari: list[str] | None = None,
    baglanti_kaynagi: str | None = None,
    dogrudan_operasyon: bool = False,
    manuel_inceleme: bool | None = None,
) -> dict[str, Any]:
    uyarilar = list(zincir_uyarilari or [])
    mi = bool(manuel_inceleme) if manuel_inceleme is not None else bool(zincir_eksik)
    return {
        'parent_type': parent_type,
        'parent_id': parent_id,
        'baslangic_tipi': baslangic_tipi,
        'zincir_eksik': bool(zincir_eksik),
        'zincir_uyarilari': uyarilar,
        'baglanti_kaynagi': baglanti_kaynagi,
        'dogrudan_operasyon': bool(dogrudan_operasyon),
        'manuel_inceleme': mi,
    }


def classify_mo_gorusme_parent(
    mo_gorusme_id: Any,
    cari_id: int,
    gorusme_by_id: dict[int, dict[str, Any]] | None,
    *,
    kind: str,
) -> dict[str, Any]:
    """kind: NUMUNE | SIPARIS → DOGRUDAN_* / GORUSMEDEN_* / ZINCIR_KOPUK."""
    cid = int(cari_id)
    gid = iid(mo_gorusme_id)
    kind_u = (kind or 'NUMUNE').upper()
    if kind_u == 'SIPARIS':
        dogrudan, bagli, kopuk = 'DOGRUDAN_SIPARIS', 'GORUSMEDEN_SIPARIS', 'ZINCIR_KOPUK'
        bag_kaynak_d, bag_kaynak_g = 'DOGRUDAN_CARI', 'MO_GORUSME_ID'
    else:
        dogrudan, bagli, kopuk = 'DOGRUDAN_NUMUNE', 'GORUSMEDEN_NUMUNE', 'ZINCIR_KOPUK'
        bag_kaynak_d, bag_kaynak_g = 'DOGRUDAN_CARI', 'MO_GORUSME_ID'

    if gid is None:
        return zincir_alanlari(
            parent_type=PARENT_CARI,
            parent_id=cid,
            baslangic_tipi=dogrudan,
            zincir_eksik=False,
            baglanti_kaynagi=bag_kaynak_d,
            dogrudan_operasyon=True,
            manuel_inceleme=False,
        )

    gmap = gorusme_by_id or {}
    g = gmap.get(gid)
    if g is None:
        return zincir_alanlari(
            parent_type=None,
            parent_id=None,
            baslangic_tipi=kopuk,
            zincir_eksik=True,
            zincir_uyarilari=['PARENT_BULUNAMADI'],
            baglanti_kaynagi='MO_GORUSME_ID',
            dogrudan_operasyon=False,
            manuel_inceleme=True,
        )
    gc = iid(g.get('cari_id'))
    if gc is not None and gc != cid:
        return zincir_alanlari(
            parent_type=None,
            parent_id=None,
            baslangic_tipi=kopuk,
            zincir_eksik=True,
            zincir_uyarilari=['PARENT_BASKA_CARI'],
            baglanti_kaynagi='MO_GORUSME_ID',
            dogrudan_operasyon=False,
            manuel_inceleme=True,
        )
    return zincir_alanlari(
        parent_type=PARENT_GORUSME,
        parent_id=gid,
        baslangic_tipi=bagli,
        zincir_eksik=False,
        baglanti_kaynagi=bag_kaynak_g,
        dogrudan_operasyon=False,
        manuel_inceleme=False,
    )


def classify_gorusme_root(cari_id: int) -> dict[str, Any]:
    return zincir_alanlari(
        parent_type=PARENT_CARI,
        parent_id=int(cari_id),
        baslangic_tipi='GORUSME',
        zincir_eksik=False,
        baglanti_kaynagi='CARI',
        dogrudan_operasyon=False,
        manuel_inceleme=False,
    )


def classify_siparis_parent(
    planlama_siparis_id: Any,
    cari_id: int,
    siparis_cari_map: dict[int, int | None],
    *,
    null_tipi: str = 'LEGACY_URETIM',
) -> dict[str, Any]:
    """Üretim/sevkiyat için sipariş parent sınıflandırması."""
    cid = int(cari_id)
    sid = iid(planlama_siparis_id)
    if sid is None:
        return zincir_alanlari(
            parent_type=PARENT_CARI,
            parent_id=cid,
            baslangic_tipi=null_tipi,
            zincir_eksik=False,
            baglanti_kaynagi='DOGRUDAN_OR_LEGACY',
            dogrudan_operasyon=True,
            manuel_inceleme=False,
        )
    if sid not in siparis_cari_map:
        return zincir_alanlari(
            parent_type=None,
            parent_id=None,
            baslangic_tipi='ZINCIR_KOPUK',
            zincir_eksik=True,
            zincir_uyarilari=['PARENT_BULUNAMADI'],
            baglanti_kaynagi='PLANLAMA_SIPARIS_ID',
            dogrudan_operasyon=False,
            manuel_inceleme=True,
        )
    sc = siparis_cari_map[sid]
    if sc is not None and sc != cid:
        return zincir_alanlari(
            parent_type=None,
            parent_id=None,
            baslangic_tipi='ZINCIR_KOPUK',
            zincir_eksik=True,
            zincir_uyarilari=['PARENT_BASKA_CARI'],
            baglanti_kaynagi='PLANLAMA_SIPARIS_ID',
            dogrudan_operasyon=False,
            manuel_inceleme=True,
        )
    return zincir_alanlari(
        parent_type=PARENT_SIPARIS,
        parent_id=sid,
        baslangic_tipi='SIPARISTEN',
        zincir_eksik=False,
        baglanti_kaynagi='PLANLAMA_SIPARIS_ID',
        dogrudan_operasyon=False,
        manuel_inceleme=False,
    )


def siparis_operasyon_uyarilari(
    *,
    durum: str | None,
    kalem_sayisi: int,
    rf_kalem_sayisi: int = 0,
    uretim_plan_sayisi: int = 0,
) -> list[str]:
    """Operasyonel bilgi — zincir hatası değil."""
    out: list[str] = []
    d = (durum or '').upper()
    if kalem_sayisi <= 0:
        if d in ('', 'TASLAK', 'ONAY_BEKLIYOR'):
            out.append('KALEM_BEKLENIYOR')
        else:
            out.append('KALEM_YOK')
    if kalem_sayisi > 0 and rf_kalem_sayisi <= 0:
        out.append('RF_KALEM_YOK')  # hata değil; RF gerektirmeyen olabilir
    if uretim_plan_sayisi <= 0 and d not in ('TASLAK', 'ONAY_BEKLIYOR', 'REDDEDILDI', ''):
        out.append('URETIM_HENUZ_YOK')
    return out


def resolve_tek_sorumlu(con: sqlite3.Connection, cari_id: int) -> dict[str, Any]:
    """V1 tek aktif pazarlamacı. DB update yok."""
    empty = {
        'sorumlu': None,
        'sorumlu_uyarilari': ['SORUMLU_ATANMAMIS'],
        'sorumlu_atanmamis': True,
        'coklu_aktif': False,
        'aktif_kayit_sayisi': 0,
    }
    if not _tablo_var(con, 'cari_sorumlu'):
        return empty
    rows = con.execute(
        """
        SELECT cs.id, cs.kullanici_id, cs.sorumluluk_rolu, cs.aktif,
               cs.baslangic_tarihi, cs.created_at, cs.atayan_kullanici_id,
               sk.KullaniciAdi AS kullanici_adi, sk.AdSoyad AS ad_soyad
        FROM cari_sorumlu cs
        LEFT JOIN sistem_kullanici sk ON sk.Id = cs.kullanici_id
        WHERE cs.cari_id=? AND cs.aktif=1
          AND (cs.bitis_tarihi IS NULL OR cs.bitis_tarihi=''
               OR cs.bitis_tarihi > datetime('now','localtime'))
        ORDER BY
          CASE cs.sorumluluk_rolu
            WHEN 'ANA' THEN 0
            WHEN 'YEDEK' THEN 1
            WHEN 'DESTEK' THEN 2
            WHEN 'YONETICI' THEN 3
            ELSE 9
          END,
          COALESCE(cs.baslangic_tarihi, cs.created_at, '') DESC,
          cs.id DESC
        """,
        (int(cari_id),),
    ).fetchall()
    if not rows:
        return empty
    ana_rows = [r for r in rows if (r['sorumluluk_rolu'] or '').upper() == 'ANA']
    if ana_rows:
        # eşitlikte deterministik: id DESC
        secilen = sorted(ana_rows, key=lambda r: int(r['id']), reverse=True)[0]
    else:
        secilen = rows[0]
    uyarilar: list[str] = []
    if len(rows) > 1:
        uyarilar.append('COKLU_AKTIF_SORUMLU')
    kid = iid(secilen['kullanici_id'])
    ad = (
        (secilen['ad_soyad'] or secilen['kullanici_adi'] or '').strip()
        or (str(kid) if kid else None)
    )
    return {
        'sorumlu': {
            'id': int(secilen['id']),
            'kullanici_id': kid,
            'ad_soyad': ad,
            'kullanici_adi': ad,
            'rol': (secilen['sorumluluk_rolu'] or '').upper() or None,
            'sorumluluk_rolu': (secilen['sorumluluk_rolu'] or '').upper() or None,
            'baslangic_tarihi': secilen['baslangic_tarihi'] or secilen['created_at'],
            'atayan_kullanici_id': iid(secilen['atayan_kullanici_id']),
        },
        'sorumlu_uyarilari': uyarilar,
        'sorumlu_atanmamis': False,
        'coklu_aktif': len(rows) > 1,
        'aktif_kayit_sayisi': len(rows),
    }


def load_gorusme_cari_map(
    con: sqlite3.Connection,
    gorusme_ids: set[int] | list[int],
) -> dict[int, dict[str, Any]]:
    ids = [i for i in gorusme_ids if i]
    out: dict[int, dict[str, Any]] = {}
    if not ids or not _tablo_var(con, 'musteri_operasyon_gorusme'):
        return out
    ph = ','.join('?' * len(ids))
    for r in con.execute(
        f'SELECT id, cari_id, aktif FROM musteri_operasyon_gorusme WHERE id IN ({ph})',
        ids,
    ):
        out[int(r['id'])] = dict(r)
    return out


def load_siparis_cari_map(
    con: sqlite3.Connection,
    siparis_ids: set[int] | list[int],
) -> dict[int, int | None]:
    ids = [i for i in siparis_ids if i]
    out: dict[int, int | None] = {}
    if not ids or not _tablo_var(con, 'nexgen_planlama_siparis'):
        return out
    ph = ','.join('?' * len(ids))
    for r in con.execute(
        f'SELECT id, cari_id FROM nexgen_planlama_siparis WHERE id IN ({ph})',
        ids,
    ):
        out[int(r['id'])] = iid(r['cari_id'])
    return out


def parse_iso_date(val: str | None, *, field: str) -> str | None:
    """YYYY-MM-DD → aynı; geçersizde ValueError."""
    if val is None or str(val).strip() == '':
        return None
    s = str(val).strip()[:10]
    if len(s) != 10 or s[4] != '-' or s[7] != '-':
        raise ValueError(f'{field} ISO YYYY-MM-DD olmalı')
    y, m, d = s.split('-')
    if not (y.isdigit() and m.isdigit() and d.isdigit()):
        raise ValueError(f'{field} ISO YYYY-MM-DD olmalı')
    yi, mi, di = int(y), int(m), int(d)
    if not (1 <= mi <= 12 and 1 <= di <= 31):
        raise ValueError(f'{field} geçersiz tarih')
    return s


def clamp_limit(limit: Any, *, default: int = 50, maximum: int = 200) -> int:
    if limit is None or limit == '':
        return default
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return default
    if n < 1:
        return default
    return min(n, maximum)


def clamp_offset(offset: Any) -> int:
    if offset is None or offset == '':
        return 0
    try:
        n = int(offset)
    except (TypeError, ValueError):
        return 0
    return max(0, n)
