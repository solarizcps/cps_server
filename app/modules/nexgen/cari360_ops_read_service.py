# -*- coding: utf-8 -*-
"""
Cari 360 — read-only operasyon özeti.

Kaynaklar (doğrulanmış):
- nexgen_cari.id
- nexgen_planlama_siparis.cari_id → nexgen_cari.id
- nexgen_planlama_siparis_kalem.planlama_siparis_id → nexgen_planlama_siparis.id
- nexgen_uretim_plan.cari_id / planlama_siparis_id
- nexgen_uretim_batch.plan_id → nexgen_uretim_parca (alt emir)
- mo_musteri_sevkiyat.cari_id → nexgen_cari.id
- mo_musteri_sevkiyat_kalem.sevkiyat_id → mo_musteri_sevkiyat.id
- musteri_operasyon_gorusme.cari_id (mevcut)

Finans / Cari_Har / open_item yok.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from modules.nexgen.cari360_omurga_link import backfill_kalem_uretim_planlari
from modules.nexgen.cari_sorumlu_service import can_view_cari

# Sonuçlanmış sipariş durumları — mock dağılım + sistemde görülen kapanış kodları.
# ONAYLANDI / URETIMDE vb. hâlâ süreçte → aktif sayılır.
_SIPARIS_PASIF = frozenset({
    'REDDEDILDI', 'IPTAL', 'IPTAL_EDILDI', 'TAMAMLANDI', 'KAPANDI', 'IPTALEDILDI',
})


class Cari360OpsError(Exception):
    def __init__(self, mesaj: str, kod: int = 400):
        self.mesaj = mesaj
        self.kod = kod
        super().__init__(mesaj)


def _tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _fmt_dt(v: Any) -> str | None:
    """Görüntü tarihi: YYYY-MM-DD veya YYYY-MM-DD HH:MM."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if 'T' in s:
        s = s.replace('T', ' ', 1)
    if len(s) >= 16 and s[10] == ' ':
        return s[:16]
    if len(s) >= 10:
        return s[:10]
    return s


def _assert_cari(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None,
) -> dict[str, Any]:
    try:
        cid = int(cari_id)
    except (TypeError, ValueError):
        raise Cari360OpsError('Geçersiz cari id.', 400)
    if cid <= 0:
        raise Cari360OpsError('Geçersiz cari id.', 400)
    if not can_view_cari(con, kullanici_id, cid, yk):
        raise Cari360OpsError('Bu cari için görüntüleme yetkiniz yok.', 403)
    row = con.execute(
        'SELECT id, cari_kod, unvan, aktif, created_at, updated_at '
        'FROM nexgen_cari WHERE id=?',
        (cid,),
    ).fetchone()
    if not row:
        raise Cari360OpsError('Cari bulunamadı.', 404)
    return {
        'id': int(row['id']),
        'cari_kod': row['cari_kod'] or '',
        'unvan': row['unvan'] or '',
        'aktif': int(row['aktif'] or 0),
        'created_at': _fmt_dt(row['created_at']),
        'updated_at': _fmt_dt(row['updated_at']),
    }


def _fmt_num(v: Any) -> float | int | None:
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        if abs(f - int(f)) < 1e-9:
            return int(f)
        return round(f, 2)
    except (TypeError, ValueError):
        return None


def load_cari360_ozet(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None,
) -> dict[str, Any]:
    """Üst KPI özeti — gerçek sayımlar."""
    cari = _assert_cari(con, cari_id, kullanici_id, yk)
    cid = int(cari_id)

    toplam_siparis = 0
    aktif_siparis = 0
    if _tablo_var(con, 'nexgen_planlama_siparis'):
        toplam_siparis = int(con.execute(
            'SELECT COUNT(*) FROM nexgen_planlama_siparis WHERE cari_id=?',
            (cid,),
        ).fetchone()[0])
        rows = con.execute(
            'SELECT durum FROM nexgen_planlama_siparis WHERE cari_id=?',
            (cid,),
        ).fetchall()
        for r in rows:
            d = (r['durum'] or '').strip().upper()
            if d and d not in _SIPARIS_PASIF:
                aktif_siparis += 1

    toplam_sevkiyat = 0
    toplam_sevk_kg = 0.0
    son_sevkiyat_tarihi = None
    if _tablo_var(con, 'mo_musteri_sevkiyat'):
        toplam_sevkiyat = int(con.execute(
            'SELECT COUNT(*) FROM mo_musteri_sevkiyat '
            'WHERE cari_id=? AND COALESCE(aktif, 1)=1',
            (cid,),
        ).fetchone()[0])
        if _tablo_var(con, 'mo_musteri_sevkiyat_kalem'):
            kg_row = con.execute(
                """
                SELECT COALESCE(SUM(k.miktar_kg), 0)
                FROM mo_musteri_sevkiyat_kalem k
                JOIN mo_musteri_sevkiyat s ON s.id = k.sevkiyat_id
                WHERE s.cari_id=? AND COALESCE(s.aktif, 1)=1
                """,
                (cid,),
            ).fetchone()
            toplam_sevk_kg = float(kg_row[0] or 0)
        son = con.execute(
            """
            SELECT COALESCE(sevk_tarihi, olusturma_tarihi) AS t
            FROM mo_musteri_sevkiyat
            WHERE cari_id=? AND COALESCE(aktif, 1)=1
            ORDER BY COALESCE(sevk_tarihi, olusturma_tarihi) DESC, id DESC
            LIMIT 1
            """,
            (cid,),
        ).fetchone()
        if son and son['t']:
            son_sevkiyat_tarihi = son['t']

    son_gorusme_tarihi = None
    gorusme_sayisi = 0
    acik_takip = 0
    if _tablo_var(con, 'musteri_operasyon_gorusme'):
        gorusme_sayisi = int(con.execute(
            'SELECT COUNT(*) FROM musteri_operasyon_gorusme '
            'WHERE cari_id=? AND COALESCE(aktif, 1)=1',
            (cid,),
        ).fetchone()[0])
        acik_takip = int(con.execute(
            "SELECT COUNT(*) FROM musteri_operasyon_gorusme "
            "WHERE cari_id=? AND COALESCE(aktif, 1)=1 AND takip_durumu='ACIK'",
            (cid,),
        ).fetchone()[0])
        g = con.execute(
            """
            SELECT gorusme_tarihi FROM musteri_operasyon_gorusme
            WHERE cari_id=? AND COALESCE(aktif, 1)=1
            ORDER BY gorusme_tarihi DESC, id DESC
            LIMIT 1
            """,
            (cid,),
        ).fetchone()
        if g and g['gorusme_tarihi']:
            son_gorusme_tarihi = g['gorusme_tarihi']

    yetkili_sayisi = 0
    if _tablo_var(con, 'cari_yetkili'):
        yetkili_sayisi = int(con.execute(
            'SELECT COUNT(*) FROM cari_yetkili WHERE cari_id=? AND COALESCE(aktif, 1)=1',
            (cid,),
        ).fetchone()[0])

    return {
        'cari': cari,
        'kpi': {
            'toplam_siparis': toplam_siparis,
            'aktif_siparis': aktif_siparis,
            'toplam_sevkiyat': toplam_sevkiyat,
            'toplam_sevk_kg': _fmt_num(toplam_sevk_kg) or 0,
            'son_sevkiyat_tarihi': _fmt_dt(son_sevkiyat_tarihi),
            'son_gorusme_tarihi': _fmt_dt(son_gorusme_tarihi),
        },
        'yetkili_sayisi': yetkili_sayisi,
        'gorusme_sayisi': gorusme_sayisi,
        'acik_takip': acik_takip,
    }


def load_cari360_siparisler(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    """Son N sipariş — read-only."""
    _assert_cari(con, cari_id, kullanici_id, yk)
    cid = int(cari_id)
    limit = max(1, min(int(limit or 50), 100))

    if not _tablo_var(con, 'nexgen_planlama_siparis'):
        return {'liste': [], 'count': 0}

    # Soft repair: kalem↔plan (NULL olanlar)
    try:
        backfill_kalem_uretim_planlari(con, cari_id=cid, limit=200)
        con.commit()
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass

    has_kalem = _tablo_var(con, 'nexgen_planlama_siparis_kalem')
    has_sevk = _tablo_var(con, 'mo_musteri_sevkiyat')
    has_sevk_kalem = _tablo_var(con, 'mo_musteri_sevkiyat_kalem')
    has_plan = _tablo_var(con, 'nexgen_uretim_plan')
    has_batch = _tablo_var(con, 'nexgen_uretim_batch')
    has_parca = _tablo_var(con, 'nexgen_uretim_parca')

    rows = con.execute(
        """
        SELECT id, siparis_no, olusturma_tarihi, durum,
               termin_tarihi, musteri_termin, onerilen_termin
        FROM nexgen_planlama_siparis
        WHERE cari_id=?
        ORDER BY COALESCE(olusturma_tarihi, '') DESC, id DESC
        LIMIT ?
        """,
        (cid, limit),
    ).fetchall()

    liste: list[dict[str, Any]] = []
    for r in rows:
        sid = int(r['id'])
        termin = r['termin_tarihi'] or r['musteri_termin'] or r['onerilen_termin']

        kalem_sayisi = 0
        if has_kalem:
            kalem_sayisi = int(con.execute(
                'SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem '
                'WHERE planlama_siparis_id=?',
                (sid,),
            ).fetchone()[0])

        # Sipariş kaleminde kg kolonu yok (L/S/M). Toplam KG uydurulmaz.
        toplam_kg = None
        sevk_kg = None
        kalan_kg = None
        son_sevk = None
        if has_sevk:
            son_row = con.execute(
                """
                SELECT COALESCE(sevk_tarihi, olusturma_tarihi) AS t
                FROM mo_musteri_sevkiyat
                WHERE siparis_id=? AND COALESCE(aktif, 1)=1
                ORDER BY COALESCE(sevk_tarihi, olusturma_tarihi) DESC, id DESC
                LIMIT 1
                """,
                (sid,),
            ).fetchone()
            if son_row and son_row['t']:
                son_sevk = son_row['t']
            if has_sevk_kalem:
                kg_row = con.execute(
                    """
                    SELECT COALESCE(SUM(k.miktar_kg), 0)
                    FROM mo_musteri_sevkiyat_kalem k
                    JOIN mo_musteri_sevkiyat s ON s.id = k.sevkiyat_id
                    WHERE s.siparis_id=? AND COALESCE(s.aktif, 1)=1
                    """,
                    (sid,),
                ).fetchone()
                sevk_kg = _fmt_num(kg_row[0] or 0)

        plan_sayisi = 0
        batch_sayisi = 0
        uretilen_kg = None
        if has_plan:
            plan_sayisi = int(con.execute(
                """
                SELECT COUNT(*) FROM nexgen_uretim_plan
                WHERE planlama_siparis_id=?
                  AND COALESCE(durum, '') NOT IN ('IPTAL')
                """,
                (sid,),
            ).fetchone()[0])
            if has_batch and plan_sayisi:
                batch_sayisi = int(con.execute(
                    """
                    SELECT COUNT(*) FROM nexgen_uretim_batch b
                    JOIN nexgen_uretim_plan p ON p.id = b.plan_id
                    WHERE p.planlama_siparis_id=?
                      AND COALESCE(p.durum, '') NOT IN ('IPTAL')
                    """,
                    (sid,),
                ).fetchone()[0])
            if has_parca and plan_sayisi:
                uk = con.execute(
                    """
                    SELECT COALESCE(SUM(pr.uretilen_kg), 0)
                    FROM nexgen_uretim_parca pr
                    JOIN nexgen_uretim_plan p ON p.id = pr.plan_id
                    WHERE p.planlama_siparis_id=?
                      AND COALESCE(p.durum, '') NOT IN ('IPTAL')
                    """,
                    (sid,),
                ).fetchone()
                uretilen_kg = _fmt_num(uk[0] or 0)

        liste.append({
            'id': sid,
            'siparis_no': r['siparis_no'] or '',
            'siparis_tarihi': _fmt_dt(r['olusturma_tarihi']),
            'durum': r['durum'] or '',
            'termin': _fmt_dt(termin),
            'toplam_kg': toplam_kg,
            'kalem_sayisi': kalem_sayisi,
            'plan_sayisi': plan_sayisi,
            'batch_sayisi': batch_sayisi,
            'uretilen_kg': uretilen_kg,
            'son_sevkiyat_tarihi': _fmt_dt(son_sevk),
            'sevk_edilen_kg': sevk_kg,
            'kalan_kg': kalan_kg,
            'detay_url': f'/nexgen/pazarlama?siparis={sid}',
            'cari360_url': f'/nexgen/cari360/{cid}?tab=siparisler',
        })

    return {'liste': liste, 'count': len(liste)}


def load_cari360_sevkiyatlar(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    """Son N sevkiyat + kalem satırları."""
    _assert_cari(con, cari_id, kullanici_id, yk)
    cid = int(cari_id)
    limit = max(1, min(int(limit or 50), 100))

    if not _tablo_var(con, 'mo_musteri_sevkiyat'):
        return {'liste': [], 'count': 0}

    has_kalem = _tablo_var(con, 'mo_musteri_sevkiyat_kalem')
    has_sip = _tablo_var(con, 'nexgen_planlama_siparis')

    rows = con.execute(
        """
        SELECT id, sevkiyat_no, irsaliye_no, sevk_tarihi, olusturma_tarihi,
               durum, siparis_id
        FROM mo_musteri_sevkiyat
        WHERE cari_id=? AND COALESCE(aktif, 1)=1
        ORDER BY COALESCE(sevk_tarihi, olusturma_tarihi) DESC, id DESC
        LIMIT ?
        """,
        (cid, limit),
    ).fetchall()

    liste: list[dict[str, Any]] = []
    for r in rows:
        sevk_id = int(r['id'])
        siparis_no = None
        siparis_id = r['siparis_id']
        if siparis_id and has_sip:
            sn = con.execute(
                'SELECT siparis_no FROM nexgen_planlama_siparis WHERE id=?',
                (int(siparis_id),),
            ).fetchone()
            if sn:
                siparis_no = sn['siparis_no']

        kalemler: list[dict[str, Any]] = []
        sevk_toplam_kg = 0.0
        if has_kalem:
            krows = con.execute(
                """
                SELECT urun_adi, renk_ad, miktar_kg
                FROM mo_musteri_sevkiyat_kalem
                WHERE sevkiyat_id=?
                ORDER BY id ASC
                """,
                (sevk_id,),
            ).fetchall()
            for k in krows:
                kg = float(k['miktar_kg'] or 0)
                sevk_toplam_kg += kg
                kalemler.append({
                    'urun': k['urun_adi'] or '—',
                    'renk': k['renk_ad'] or '—',
                    'sevk_kg': _fmt_num(kg) or 0,
                })

        # Tablo satırı: ilk kalem + expand için tüm kalemler
        ilk = kalemler[0] if kalemler else {'urun': '—', 'renk': '—', 'sevk_kg': 0}
        batch_sayisi = 0
        if siparis_id and _tablo_var(con, 'nexgen_uretim_plan') and _tablo_var(con, 'nexgen_uretim_batch'):
            batch_sayisi = int(con.execute(
                """
                SELECT COUNT(*) FROM nexgen_uretim_batch b
                JOIN nexgen_uretim_plan p ON p.id = b.plan_id
                WHERE p.planlama_siparis_id=?
                  AND COALESCE(p.durum, '') NOT IN ('IPTAL')
                """,
                (int(siparis_id),),
            ).fetchone()[0])

        liste.append({
            'id': sevk_id,
            'sevkiyat_no': r['sevkiyat_no'] or '',
            'irsaliye_no': r['irsaliye_no'] or '',
            'tarih': _fmt_dt(r['sevk_tarihi'] or r['olusturma_tarihi']),
            'siparis_id': int(siparis_id) if siparis_id else None,
            'siparis_no': siparis_no or '',
            'siparis_url': (
                f'/nexgen/pazarlama?siparis={int(siparis_id)}' if siparis_id else None
            ),
            'batch_sayisi': batch_sayisi,
            'urun': ilk['urun'],
            'renk': ilk['renk'],
            'sevk_kg': _fmt_num(sevk_toplam_kg) or 0,
            'kalem_kg_ozet': ilk['sevk_kg'] if len(kalemler) == 1 else None,
            'durum': r['durum'] or '',
            'kalem_sayisi': len(kalemler),
            'kalemler': kalemler,
        })

    return {'liste': liste, 'count': len(liste)}


def load_cari360_urunler(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None,
    *,
    limit: int = 30,
) -> dict[str, Any]:
    """Ürün+renk aggregate — sevkiyat kalemlerinden."""
    _assert_cari(con, cari_id, kullanici_id, yk)
    cid = int(cari_id)
    limit = max(1, min(int(limit or 30), 100))

    if not (
        _tablo_var(con, 'mo_musteri_sevkiyat')
        and _tablo_var(con, 'mo_musteri_sevkiyat_kalem')
    ):
        return {'liste': [], 'count': 0}

    rows = con.execute(
        """
        SELECT
          COALESCE(NULLIF(TRIM(k.urun_adi), ''), '—') AS urun,
          COALESCE(NULLIF(TRIM(k.renk_ad), ''), '—') AS renk,
          COALESCE(SUM(k.miktar_kg), 0) AS toplam_kg,
          COUNT(DISTINCT s.id) AS sevkiyat_sayisi,
          MAX(COALESCE(s.sevk_tarihi, s.olusturma_tarihi)) AS son_alis_tarihi
        FROM mo_musteri_sevkiyat_kalem k
        JOIN mo_musteri_sevkiyat s ON s.id = k.sevkiyat_id
        WHERE s.cari_id=? AND COALESCE(s.aktif, 1)=1
        GROUP BY
          COALESCE(NULLIF(TRIM(k.urun_adi), ''), '—'),
          COALESCE(NULLIF(TRIM(k.renk_ad), ''), '—')
        ORDER BY son_alis_tarihi DESC, toplam_kg DESC
        LIMIT ?
        """,
        (cid, limit),
    ).fetchall()

    liste: list[dict[str, Any]] = []
    for r in rows:
        urun = r['urun']
        renk = r['renk']
        son_tarih = r['son_alis_tarihi']
        son_kg = None
        if son_tarih:
            sk = con.execute(
                """
                SELECT k.miktar_kg
                FROM mo_musteri_sevkiyat_kalem k
                JOIN mo_musteri_sevkiyat s ON s.id = k.sevkiyat_id
                WHERE s.cari_id=? AND COALESCE(s.aktif, 1)=1
                  AND COALESCE(NULLIF(TRIM(k.urun_adi), ''), '—') = ?
                  AND COALESCE(NULLIF(TRIM(k.renk_ad), ''), '—') = ?
                  AND COALESCE(s.sevk_tarihi, s.olusturma_tarihi) = ?
                ORDER BY s.id DESC, k.id DESC
                LIMIT 1
                """,
                (cid, urun, renk, son_tarih),
            ).fetchone()
            if sk:
                son_kg = _fmt_num(sk['miktar_kg'])

        liste.append({
            'urun': urun,
            'renk': renk,
            'toplam_alinan_kg': _fmt_num(r['toplam_kg']) or 0,
            'sevkiyat_sayisi': int(r['sevkiyat_sayisi'] or 0),
            'son_alis_tarihi': _fmt_dt(son_tarih),
            'son_alinan_kg': son_kg if son_kg is not None else 0,
        })

    return {'liste': liste, 'count': len(liste)}


def load_cari360_uretim(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    """Üretim planı / batch / alt emir (parça) — cari_id üzerinden read-only."""
    _assert_cari(con, cari_id, kullanici_id, yk)
    cid = int(cari_id)
    limit = max(1, min(int(limit or 50), 100))

    try:
        backfill_kalem_uretim_planlari(con, cari_id=cid, limit=200)
        con.commit()
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass

    if not _tablo_var(con, 'nexgen_uretim_plan'):
        return {'liste': [], 'count': 0}

    has_batch = _tablo_var(con, 'nexgen_uretim_batch')
    has_parca = _tablo_var(con, 'nexgen_uretim_parca')
    has_sip = _tablo_var(con, 'nexgen_planlama_siparis')
    has_kalem = _tablo_var(con, 'nexgen_planlama_siparis_kalem')

    rows = con.execute(
        """
        SELECT id, plan_kodu, durum, planlanan_kg, planlama_siparis_id,
               siparis_no, rf_renk_id, renk_kodu, created_at, plan_tarihi
        FROM nexgen_uretim_plan
        WHERE cari_id=?
          AND COALESCE(durum, '') NOT IN ('IPTAL')
        ORDER BY COALESCE(plan_tarihi, created_at, '') DESC, id DESC
        LIMIT ?
        """,
        (cid, limit),
    ).fetchall()

    liste: list[dict[str, Any]] = []
    for r in rows:
        pid = int(r['id'])
        sid = r['planlama_siparis_id']
        siparis_no = r['siparis_no'] or ''
        if sid and has_sip and not siparis_no:
            sn = con.execute(
                'SELECT siparis_no FROM nexgen_planlama_siparis WHERE id=?',
                (int(sid),),
            ).fetchone()
            if sn:
                siparis_no = sn['siparis_no'] or ''

        kalem_bagli = False
        if has_kalem:
            kalem_bagli = bool(con.execute(
                'SELECT 1 FROM nexgen_planlama_siparis_kalem WHERE uretim_plan_id=? LIMIT 1',
                (pid,),
            ).fetchone())

        batch_sayisi = 0
        batch_kodlari: list[str] = []
        if has_batch:
            brows = con.execute(
                """
                SELECT id, batch_kodu FROM nexgen_uretim_batch
                WHERE plan_id=? ORDER BY id
                """,
                (pid,),
            ).fetchall()
            batch_sayisi = len(brows)
            batch_kodlari = [(b['batch_kodu'] or f"#{b['id']}") for b in brows[:3]]

        alt_emir_sayisi = 0
        hedef_kg = None
        uretilen_kg = None
        if has_parca:
            pr = con.execute(
                """
                SELECT COUNT(*) AS n,
                       COALESCE(SUM(hedef_kg), 0) AS hedef,
                       COALESCE(SUM(uretilen_kg), 0) AS uretilen
                FROM nexgen_uretim_parca
                WHERE plan_id=?
                """,
                (pid,),
            ).fetchone()
            alt_emir_sayisi = int(pr['n'] or 0)
            hedef_kg = _fmt_num(pr['hedef'])
            uretilen_kg = _fmt_num(pr['uretilen'])

        liste.append({
            'id': pid,
            'plan_kodu': r['plan_kodu'] or '',
            'durum': r['durum'] or '',
            'planlanan_kg': _fmt_num(r['planlanan_kg']),
            'siparis_id': int(sid) if sid else None,
            'siparis_no': siparis_no,
            'renk': r['renk_kodu'] or '',
            'rf_renk_id': r['rf_renk_id'],
            'kalem_bagli': kalem_bagli,
            'batch_sayisi': batch_sayisi,
            'batch_kodlari': batch_kodlari,
            'alt_emir_sayisi': alt_emir_sayisi,
            'hedef_kg': hedef_kg,
            'uretilen_kg': uretilen_kg,
            'tarih': _fmt_dt(r['plan_tarihi'] or r['created_at']),
            'siparis_url': f'/nexgen/pazarlama?siparis={int(sid)}' if sid else None,
        })

    return {'liste': liste, 'count': len(liste)}
