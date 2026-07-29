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
from modules.nexgen.cari_sorumlu_service import can_view_cari, can_view_cari_ticari

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
        bagli_numune_sayisi = 0
        bagli_numuneler: list[dict[str, Any]] = []
        if has_kalem:
            kalem_sayisi = int(con.execute(
                'SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem '
                'WHERE planlama_siparis_id=?',
                (sid,),
            ).fetchone()[0])
            has_nt_col = 'numune_talep_id' in {
                c[1] for c in con.execute(
                    'PRAGMA table_info(nexgen_planlama_siparis_kalem)'
                ).fetchall()
            }
            if has_nt_col and _tablo_var(con, 'nexgen_numune_talep'):
                nrows = con.execute(
                    """
                    SELECT DISTINCT k.numune_talep_id AS nid, n.talep_kodu
                    FROM nexgen_planlama_siparis_kalem k
                    JOIN nexgen_numune_talep n ON n.id = k.numune_talep_id
                    WHERE k.planlama_siparis_id=?
                      AND k.numune_talep_id IS NOT NULL
                    ORDER BY n.talep_kodu, k.numune_talep_id
                    """,
                    (sid,),
                ).fetchall()
                for nr in nrows:
                    nid = int(nr['nid'])
                    bagli_numuneler.append({
                        'id': nid,
                        'talep_kodu': nr['talep_kodu'] or f'#{nid}',
                        'detay_url': f'/nexgen/numune-talep?id={nid}',
                    })
                bagli_numune_sayisi = len(bagli_numuneler)

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
            'bagli_numune_sayisi': bagli_numune_sayisi,
            'bagli_numuneler': bagli_numuneler,
            'plan_sayisi': plan_sayisi,
            'batch_sayisi': batch_sayisi,
            'uretilen_kg': uretilen_kg,
            'son_sevkiyat_tarihi': _fmt_dt(son_sevk),
            'sevk_edilen_kg': sevk_kg,
            'kalan_kg': kalan_kg,
            'detay_url': f'/nexgen/pazarlama?siparis={sid}',
            'cari360_url': f'/nexgen/cari360/{cid}?tab=siparisler',
        })

    # T4: hassas ticari alanlar yalnız can_view_cari_ticari ile
    from modules.nexgen.cari360_ticari_ozet_service import enrich_siparis_listesi_ticari
    ticari_ok = can_view_cari_ticari(con, kullanici_id, cid, yk)
    liste = enrich_siparis_listesi_ticari(con, liste, ticari_gorunur=ticari_ok)
    return {'liste': liste, 'count': len(liste), 'ticari_gorunur': ticari_ok}


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


_NUMUNE_KY_LABEL = {
    'HAZIR_RENK': 'Hazır Renk',
    'YENI_RENK': 'Yeni Renk',
    'YENI_FORMUL': 'Yeni Formül',
}
_NUMUNE_AKTIF_DURUM = frozenset({
    'BEKLEYEN_NUMUNE', 'CALISILIYOR', 'REVIZYONDA', 'ONAY_BEKLIYOR',
    'FERHAT_TESTINDE', 'FERHAT_BEKLIYOR', 'DENEMEDE',
})
_MULTI_LEGACY_EXCLUDE = 'AT-M-2026-0147'


def _kolonlar(con: sqlite3.Connection, table: str) -> set[str]:
    if not _tablo_var(con, table):
        return set()
    return {c[1] for c in con.execute(f'PRAGMA table_info({table})').fetchall()}


def _norm_kod(v: Any) -> str:
    return (str(v) if v is not None else '').strip()


def _numune_rf_label(con: sqlite3.Connection, rf_id: Any) -> str | None:
    if rf_id is None:
        return None
    try:
        rid = int(rf_id)
    except (TypeError, ValueError):
        return None
    if rid <= 0 or not _tablo_var(con, 'nexgen_rf_renk'):
        return None
    row = con.execute(
        'SELECT rf_kod, ad FROM nexgen_rf_renk WHERE id=?', (rid,),
    ).fetchone()
    if not row:
        return None
    kod = (row['rf_kod'] or '').strip()
    ad = (row['ad'] or '').strip()
    if kod and ad and kod != ad:
        return f'{kod} — {ad}'
    return kod or ad or None


def _rf_map_batch(con: sqlite3.Connection, rf_ids: set[int]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    ids = [i for i in rf_ids if i and i > 0]
    if not ids or not _tablo_var(con, 'nexgen_rf_renk'):
        return out
    ph = ','.join('?' * len(ids))
    for r in con.execute(
        f"""
        SELECT id, rf_kod, ad, durum, aktif, aktif_rev_no
        FROM nexgen_rf_renk WHERE id IN ({ph})
        """,
        ids,
    ):
        rid = int(r['id'])
        kod = (r['rf_kod'] or '').strip()
        ad = (r['ad'] or '').strip()
        label = f'{kod} — {ad}' if kod and ad and kod != ad else (kod or ad or None)
        out[rid] = {
            'rf_renk_id': rid,
            'rf_kod': kod or None,
            'rf_adi': ad or None,
            'rf_label': label,
            'rf_durum': r['durum'] or None,
            'rf_aktif': int(r['aktif'] or 0),
            'aktif_rev_no': r['aktif_rev_no'],
        }
    return out


def _arge_card(
    r: sqlite3.Row | dict,
    *,
    baglanti_kaynagi: str,
    legacy: bool,
    rf_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    d = dict(r) if not isinstance(r, dict) else r
    aid = int(d['id'])
    rf = rf_info or {}
    return {
        'id': aid,
        'test_no': d.get('test_no') or f'#{aid}',
        'durum': d.get('durum') or None,
        'aktif': int(d.get('aktif') or 0),
        'calisma_tipi': d.get('calisma_tipi') or None,
        'olusturma_tarihi': _fmt_dt(d.get('olusturma_tarihi')),
        'rf_renk_id': int(d['rf_renk_id']) if d.get('rf_renk_id') not in (None, '') else None,
        'talep_referansi': d.get('talep_referansi') or None,
        'renk_kodu': d.get('renk_kodu') or None,
        'yeni_renk_adi': d.get('yeni_renk_adi') or None,
        'formul_grup_adi': d.get('formul_grup_adi') or None,
        'ana_formul_grup_kodu': d.get('ana_formul_grup_kodu') or None,
        'rf_kod': rf.get('rf_kod'),
        'rf_adi': rf.get('rf_adi'),
        'rf_label': rf.get('rf_label'),
        'rf_durum': rf.get('rf_durum'),
        'legacy_baglanti': bool(legacy),
        'baglanti_kaynagi': baglanti_kaynagi,
        'detay_url': f'/nexgen/tablet/arge/musteri-renk?arge_test_id={aid}',
    }


def _numune_card_for_gorusme(
    r: sqlite3.Row | dict,
    *,
    baglanti_kaynagi: str,
    legacy: bool,
) -> dict[str, Any]:
    d = dict(r) if not isinstance(r, dict) else r
    tid = int(d['id'])
    return {
        'id': tid,
        'talep_kodu': d.get('talep_kodu') or f'#{tid}',
        'durum': d.get('durum') or None,
        'olusturma_tarihi': _fmt_dt(d.get('olusturma_tarihi')),
        'urun_tipi': d.get('urun_tipi') or None,
        'urun_adi': d.get('urun_adi') or None,
        'arge_test_id': int(d['arge_test_id']) if d.get('arge_test_id') not in (None, 0, '') else None,
        'legacy_baglanti': bool(legacy),
        'baglanti_kaynagi': baglanti_kaynagi,
        'detay_url': f'/nexgen/numune-talep?id={tid}',
    }


def enrich_gorusmeler_bagli_numuneler(
    con: sqlite3.Connection,
    cari_id: int,
    liste: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Görüşme listesine bagli_numuneler ekler (toplu sorgu, N+1 yok)."""
    if not liste:
        return liste
    for d in liste:
        d.setdefault('bagli_numuneler', [])
    if not _tablo_var(con, 'nexgen_numune_talep'):
        return liste

    cid = int(cari_id)
    gids = [int(d['id']) for d in liste if d.get('id') is not None]
    if not gids:
        return liste

    by_g: dict[int, list[dict[str, Any]]] = {g: [] for g in gids}
    seen: dict[int, set[int]] = {g: set() for g in gids}
    ncols = _kolonlar(con, 'nexgen_numune_talep')

    def _add(gid: int, card: dict[str, Any]) -> None:
        nid = int(card['id'])
        if nid in seen.get(gid, set()):
            return
        # başka cari leak koruması card içinde cari kontrolü ile geldi
        seen.setdefault(gid, set()).add(nid)
        by_g.setdefault(gid, []).append(card)

    ph = ','.join('?' * len(gids))
    if 'mo_gorusme_id' in ncols:
        for r in con.execute(
            f"""
            SELECT id, talep_kodu, durum, olusturma_tarihi, urun_tipi, urun_adi,
                   arge_test_id, mo_gorusme_id, cari_id
            FROM nexgen_numune_talep
            WHERE COALESCE(aktif,1)=1
              AND mo_gorusme_id IN ({ph})
              AND cari_id=?
            ORDER BY id DESC
            """,
            (*gids, cid),
        ):
            _add(
                int(r['mo_gorusme_id']),
                _numune_card_for_gorusme(r, baglanti_kaynagi='MO_GORUSME_ID', legacy=False),
            )

    # Legacy reverse: gorusme.numune_talep_id — yalnız mo_gorusme_id boşsa
    gcols = _kolonlar(con, 'musteri_operasyon_gorusme')
    if 'numune_talep_id' in gcols:
        rev_pairs: list[tuple[int, int]] = []
        for d in liste:
            gid = int(d['id'])
            nid = d.get('numune_talep_id') or d.get('kaynak_numune_talep_id')
            if nid in (None, '', 0):
                continue
            if seen.get(gid):
                # canonical zaten varsa reverse ekleme (aynı id duplicate olmasın)
                if int(nid) in seen[gid]:
                    continue
            # mo bağlı başka numune yoksa VEYA bu reverse henüz listede değilse ekle
            # kural: yalnız mo_gorusme_id boş olan numune için reverse
            rev_pairs.append((gid, int(nid)))
        if rev_pairs:
            nids = list({n for _, n in rev_pairs})
            phn = ','.join('?' * len(nids))
            nmap = {
                int(r['id']): r
                for r in con.execute(
                    f"""
                    SELECT id, talep_kodu, durum, olusturma_tarihi, urun_tipi, urun_adi,
                           arge_test_id, mo_gorusme_id, cari_id
                    FROM nexgen_numune_talep
                    WHERE id IN ({phn}) AND COALESCE(aktif,1)=1 AND cari_id=?
                    """,
                    (*nids, cid),
                )
            }
            for gid, nid in rev_pairs:
                r = nmap.get(nid)
                if not r:
                    continue
                if r['mo_gorusme_id'] not in (None, 0, ''):
                    # canonical mo dolu — reverse fallback kullanma
                    continue
                _add(
                    gid,
                    _numune_card_for_gorusme(
                        r, baglanti_kaynagi='GORUSME_REVERSE_LEGACY', legacy=True,
                    ),
                )

    for d in liste:
        gid = int(d['id'])
        d['bagli_numuneler'] = by_g.get(gid, [])
    return liste


def _batch_load_arge_for_numuneler(
    con: sqlite3.Connection,
    cari_id: int,
    numune_rows: list[sqlite3.Row],
) -> tuple[dict[int, list[dict]], dict[int, dict | None], dict[str, Any]]:
    """numune_id → AR-GE kartları; aktif pointer; meta (query stats / multi flags)."""
    cid = int(cari_id)
    tids = [int(r['id']) for r in numune_rows]
    by_nt: dict[int, list[dict[str, Any]]] = {t: [] for t in tids}
    aktif: dict[int, dict | None] = {t: None for t in tids}
    multi_flags: dict[int, bool] = {t: False for t in tids}
    stats = {'q_canonical': 0, 'q_pointer': 0, 'q_legacy': 0, 'q_rf': 0}

    if not tids or not _tablo_var(con, 'nexgen_arge_test'):
        return by_nt, aktif, {'stats': stats, 'multi_flags': multi_flags}

    acols = _kolonlar(con, 'nexgen_arge_test')
    has_ntp = 'numune_talep_id' in acols
    seen_aide: dict[int, set[int]] = {t: set() for t in tids}
    arge_by_id: dict[int, dict] = {}

    def _remember(aid: int, rowdict: dict) -> None:
        arge_by_id[aid] = rowdict

    sel = (
        'id, test_no, durum, aktif, calisma_tipi, olusturma_tarihi, '
        'rf_renk_id, talep_referansi, cari_id, renk_kodu, yeni_renk_adi, '
        'formul_grup_adi, ana_formul_grup_kodu'
    )
    if has_ntp:
        sel += ', numune_talep_id'

    # 1) canonical numune_talep_id
    if has_ntp:
        ph = ','.join('?' * len(tids))
        rows = list(con.execute(
            f"""
            SELECT {sel}
            FROM nexgen_arge_test
            WHERE COALESCE(aktif,1)=1 AND numune_talep_id IN ({ph})
            ORDER BY id DESC
            """,
            tids,
        ))
        stats['q_canonical'] = 1
        for r in rows:
            # cari leak: arge.cari doluysa cari ile uyumlu olmalı; boşsa numune cari zaten filtrelendi
            if r['cari_id'] not in (None, 0) and int(r['cari_id']) != cid:
                continue
            nid = int(r['numune_talep_id'])
            aid = int(r['id'])
            _remember(aid, dict(r))
            seen_aide[nid].add(aid)

    # 2) aktif pointer
    ptr_ids = [
        int(r['arge_test_id'])
        for r in numune_rows
        if r['arge_test_id'] not in (None, 0, '')
    ]
    ptr_ids = list({i for i in ptr_ids if i > 0})
    if ptr_ids:
        ph = ','.join('?' * len(ptr_ids))
        for r in con.execute(
            f'SELECT {sel} FROM nexgen_arge_test WHERE id IN ({ph})',
            ptr_ids,
        ):
            if int(r['aktif'] or 0) != 1:
                continue
            if r['cari_id'] not in (None, 0) and int(r['cari_id']) != cid:
                continue
            _remember(int(r['id']), dict(r))
        stats['q_pointer'] = 1

    # 3) legacy exact text — yalnız canonical+pointer boş olanlar
    need_legacy: list[sqlite3.Row] = []
    for r in numune_rows:
        tid = int(r['id'])
        if seen_aide[tid]:
            continue
        if r['arge_test_id'] not in (None, 0, '') and int(r['arge_test_id']) in arge_by_id:
            continue
        kod = _norm_kod(r['talep_kodu'])
        if not kod or kod == _MULTI_LEGACY_EXCLUDE:
            if kod == _MULTI_LEGACY_EXCLUDE:
                multi_flags[tid] = True
            continue
        need_legacy.append(r)

    if need_legacy:
        kodlar = list({_norm_kod(r['talep_kodu']) for r in need_legacy})
        # multi sayımı
        ph = ','.join('?' * len(kodlar))
        cnt_rows = con.execute(
            f"""
            SELECT talep_referansi AS kod, COUNT(*) AS n
            FROM nexgen_arge_test
            WHERE COALESCE(aktif,1)=1 AND talep_referansi IN ({ph})
            GROUP BY talep_referansi
            """,
            kodlar,
        ).fetchall()
        cnt_map = {_norm_kod(x['kod']): int(x['n']) for x in cnt_rows}
        single_kods = [k for k, n in cnt_map.items() if n == 1]
        ar_by_kod: dict[str, dict] = {}
        if single_kods:
            phs = ','.join('?' * len(single_kods))
            for ar in con.execute(
                f"""
                SELECT {sel} FROM nexgen_arge_test
                WHERE COALESCE(aktif,1)=1 AND talep_referansi IN ({phs})
                """,
                single_kods,
            ):
                ar_by_kod[_norm_kod(ar['talep_referansi'])] = dict(ar)
        for r in need_legacy:
            tid = int(r['id'])
            kod = _norm_kod(r['talep_kodu'])
            n = cnt_map.get(kod, 0)
            if n > 1:
                multi_flags[tid] = True
                continue
            if n != 1:
                continue
            ar = ar_by_kod.get(kod)
            if not ar:
                continue
            if ar['cari_id'] not in (None, 0) and int(ar['cari_id']) != cid:
                continue
            if has_ntp and ar.get('numune_talep_id') not in (None, 0) and int(ar['numune_talep_id']) != tid:
                continue
            aid = int(ar['id'])
            rd = dict(ar)
            rd['_legacy'] = True
            _remember(aid, rd)
            seen_aide[tid].add(aid)
        stats['q_legacy'] = 2 if need_legacy else 0

    # RF batch
    rf_ids: set[int] = set()
    for ad in arge_by_id.values():
        if ad.get('rf_renk_id') not in (None, ''):
            try:
                rf_ids.add(int(ad['rf_renk_id']))
            except (TypeError, ValueError):
                pass
    for r in numune_rows:
        if r['rf_renk_id'] not in (None, ''):
            try:
                rf_ids.add(int(r['rf_renk_id']))
            except (TypeError, ValueError):
                pass
    rf_map = _rf_map_batch(con, rf_ids)
    stats['q_rf'] = 1 if rf_ids else 0

    # assemble
    for r in numune_rows:
        tid = int(r['id'])
        cards: list[dict[str, Any]] = []
        order_aids: list[int] = []
        # canonical first
        if has_ntp:
            for aid, ad in arge_by_id.items():
                if ad.get('numune_talep_id') not in (None, 0) and int(ad['numune_talep_id']) == tid:
                    if aid not in order_aids:
                        order_aids.append(aid)
        # pointer
        if r['arge_test_id'] not in (None, 0, ''):
            pid = int(r['arge_test_id'])
            if pid in arge_by_id and pid not in order_aids:
                order_aids.append(pid)
        # legacy leftovers in seen
        for aid in seen_aide[tid]:
            if aid not in order_aids:
                order_aids.append(aid)

        for aid in order_aids:
            ad = arge_by_id[aid]
            legacy = bool(ad.get('_legacy'))
            if legacy:
                src = 'TALEP_REFERANSI_LEGACY'
            elif has_ntp and ad.get('numune_talep_id') not in (None, 0) and int(ad['numune_talep_id']) == tid:
                src = 'NUMUNE_TALEP_ID'
            elif r['arge_test_id'] not in (None, 0, '') and int(r['arge_test_id']) == aid:
                src = 'AKTIF_ARGE_POINTER'
            else:
                src = 'NUMUNE_TALEP_ID'
            rf_id = ad.get('rf_renk_id')
            rf_info = rf_map.get(int(rf_id)) if rf_id not in (None, '') else None
            cards.append(_arge_card(ad, baglanti_kaynagi=src, legacy=legacy, rf_info=rf_info))
        by_nt[tid] = cards

        # aktif pointer card
        if r['arge_test_id'] not in (None, 0, ''):
            pid = int(r['arge_test_id'])
            for c in cards:
                if c['id'] == pid:
                    aktif[tid] = c
                    break
            if aktif[tid] is None and pid in arge_by_id:
                ad = arge_by_id[pid]
                rf_id = ad.get('rf_renk_id')
                rf_info = rf_map.get(int(rf_id)) if rf_id not in (None, '') else None
                aktif[tid] = _arge_card(
                    ad, baglanti_kaynagi='AKTIF_ARGE_POINTER', legacy=False, rf_info=rf_info,
                )
        elif cards:
            # canonical ilk aktif
            aktif[tid] = cards[0]

    return by_nt, aktif, {'stats': stats, 'multi_flags': multi_flags, 'rf_map': rf_map}


def load_cari360_numuneler(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    """Numune talepleri — yalnız nexgen_numune_talep.cari_id = nexgen_cari.id.

    cari_id NULL (ADAY) kayıtlar gelmez. RF: numune.rf → arge.rf → —.
    """
    _assert_cari(con, cari_id, kullanici_id, yk)
    cid = int(cari_id)
    limit = max(1, min(int(limit or 50), 50))

    empty = {
        'liste': [], 'count': 0,
        'ozet': {
            'toplam': 0, 'aktif': 0, 'onaylanan': 0,
            'revizyonda': 0, 'reddedilen': 0,
        },
    }
    if not _tablo_var(con, 'nexgen_numune_talep'):
        return empty

    has_arge = _tablo_var(con, 'nexgen_arge_test')
    has_user = _tablo_var(con, 'sistem_kullanici')

    # Özet — tüm aktif kayıtlar (limit dışı)
    ozet = {
        'toplam': 0, 'aktif': 0, 'onaylanan': 0,
        'revizyonda': 0, 'reddedilen': 0,
    }
    for dr in con.execute(
        """
        SELECT durum, COUNT(*) AS n
        FROM nexgen_numune_talep
        WHERE cari_id=? AND COALESCE(aktif, 1)=1
        GROUP BY durum
        """,
        (cid,),
    ).fetchall():
        n = int(dr['n'] or 0)
        ozet['toplam'] += n
        d = (dr['durum'] or '').strip().upper()
        if d in _NUMUNE_AKTIF_DURUM:
            ozet['aktif'] += n
        if d == 'ONAYLANDI':
            ozet['onaylanan'] += n
        if d == 'REVIZYONDA':
            ozet['revizyonda'] += n
        if d == 'REDDEDILDI':
            ozet['reddedilen'] += n

    ncols = _kolonlar(con, 'nexgen_numune_talep')
    mo_sel = ', mo_gorusme_id' if 'mo_gorusme_id' in ncols else ', NULL AS mo_gorusme_id'
    rows = con.execute(
        f"""
        SELECT id, talep_kodu, olusturma_tarihi, guncelleme_tarihi,
               urun_tipi, urun_adi, renk_kodu, yeni_renk_aciklama, renk_tipi,
               talep_nedeni, talep_kaynagi, karsilama_yolu, durum, aktif,
               rf_renk_id, arge_test_id, talep_eden_kullanici_id
               {mo_sel}
        FROM nexgen_numune_talep
        WHERE cari_id=? AND COALESCE(aktif, 1)=1
        ORDER BY COALESCE(guncelleme_tarihi, olusturma_tarihi, '') DESC, id DESC
        LIMIT ?
        """,
        (cid, limit),
    ).fetchall()

    # Toplu AR-GE / RF (N+1 yok)
    arge_by_nt: dict[int, list[dict]] = {}
    aktif_by_nt: dict[int, dict | None] = {}
    multi_flags: dict[int, bool] = {}
    rf_map: dict[int, dict] = {}
    qstats: dict[str, Any] = {}
    if has_arge and rows:
        arge_by_nt, aktif_by_nt, meta = _batch_load_arge_for_numuneler(con, cid, list(rows))
        multi_flags = meta.get('multi_flags') or {}
        rf_map = meta.get('rf_map') or {}
        qstats = meta.get('stats') or {}

    # Toplu kullanıcı
    user_map: dict[int, str] = {}
    if has_user and rows:
        uids = list({
            int(r['talep_eden_kullanici_id'])
            for r in rows
            if r['talep_eden_kullanici_id'] not in (None, 0, '')
        })
        if uids:
            ph = ','.join('?' * len(uids))
            for ur in con.execute(
                f'SELECT Id, AdSoyad, KullaniciAdi FROM sistem_kullanici WHERE Id IN ({ph})',
                uids,
            ):
                user_map[int(ur['Id'])] = (
                    (ur['AdSoyad'] or ur['KullaniciAdi'] or '').strip() or None
                ) or ''

    # Toplu bağlı siparişler
    siparis_by_nt: dict[int, list[dict[str, Any]]] = {int(r['id']): [] for r in rows}
    has_kalem_nt = (
        _tablo_var(con, 'nexgen_planlama_siparis_kalem')
        and 'numune_talep_id' in _kolonlar(con, 'nexgen_planlama_siparis_kalem')
        and _tablo_var(con, 'nexgen_planlama_siparis')
    )
    if has_kalem_nt and rows:
        tids = [int(r['id']) for r in rows]
        ph = ','.join('?' * len(tids))
        for sr in con.execute(
            f"""
            SELECT DISTINCT k.numune_talep_id AS nid, s.id, s.siparis_no
            FROM nexgen_planlama_siparis_kalem k
            JOIN nexgen_planlama_siparis s ON s.id = k.planlama_siparis_id
            WHERE k.numune_talep_id IN ({ph}) AND s.cari_id=?
            ORDER BY s.id DESC
            """,
            (*tids, cid),
        ):
            nid = int(sr['nid'])
            sid = int(sr['id'])
            siparis_by_nt.setdefault(nid, []).append({
                'id': sid,
                'siparis_no': sr['siparis_no'] or f'#{sid}',
                'detay_url': f'/nexgen/pazarlama?siparis={sid}',
            })

    liste: list[dict[str, Any]] = []
    for r in rows:
        tid = int(r['id'])
        renk = (r['renk_kodu'] or '').strip() or (r['yeni_renk_aciklama'] or '').strip() or None

        ky = (r['karsilama_yolu'] or '').strip().upper()
        talep_turu = _NUMUNE_KY_LABEL.get(ky)
        if not talep_turu:
            talep_turu = (r['talep_nedeni'] or '').strip() or None
        if not talep_turu:
            rt = (r['renk_tipi'] or '').strip().upper()
            if rt == 'YENI':
                talep_turu = 'Yeni Renk'
            elif rt == 'MEVCUT':
                talep_turu = 'Hazır Renk'

        aktif_arge = aktif_by_nt.get(tid) if has_arge else None
        bagli_arge = arge_by_nt.get(tid, []) if has_arge else []

        rf_id = r['rf_renk_id']
        rf_kaynak = 'numune' if rf_id else None
        if rf_id is None and aktif_arge and aktif_arge.get('rf_renk_id') is not None:
            rf_id = aktif_arge['rf_renk_id']
            rf_kaynak = 'arge'
        rf_info = rf_map.get(int(rf_id)) if rf_id not in (None, '') else None
        rf_label = (rf_info or {}).get('rf_label') or _numune_rf_label(con, rf_id)

        talep_eden = None
        if r['talep_eden_kullanici_id'] and int(r['talep_eden_kullanici_id']) in user_map:
            talep_eden = user_map[int(r['talep_eden_kullanici_id'])] or None

        bagli_siparisler = siparis_by_nt.get(tid, [])

        liste.append({
            'id': tid,
            'talep_kodu': r['talep_kodu'] or f'#{tid}',
            'tarih': _fmt_dt(r['olusturma_tarihi']),
            'talep_eden': talep_eden,
            'urun_tipi': r['urun_tipi'] or None,
            'urun_adi': r['urun_adi'] or None,
            'renk': renk,
            'talep_turu': talep_turu,
            'rf': rf_label,
            'rf_renk_id': int(rf_id) if rf_id is not None else None,
            'rf_kaynak': rf_kaynak,
            'rf_kod': (rf_info or {}).get('rf_kod'),
            'formul_grup_adi': (aktif_arge or {}).get('formul_grup_adi'),
            'ana_formul_grup_kodu': (aktif_arge or {}).get('ana_formul_grup_kodu'),
            'durum': r['durum'] or None,
            'son_guncelleme': _fmt_dt(r['guncelleme_tarihi'] or r['olusturma_tarihi']),
            'mo_gorusme_id': int(r['mo_gorusme_id']) if r['mo_gorusme_id'] not in (None, 0, '') else None,
            'arge_test_id': int(r['arge_test_id']) if r['arge_test_id'] not in (None, 0, '') else None,
            'bagli_arge_testleri': bagli_arge,
            'aktif_arge_testi': aktif_arge,
            'legacy_multi_manuel': bool(multi_flags.get(tid)),
            'bagli_siparis_sayisi': len(bagli_siparisler),
            'bagli_siparisler': bagli_siparisler,
            'detay_url': f'/nexgen/numune-talep?id={tid}',
        })

    # opsiyonel debug — response kökünde; istemciye zorunlu değil
    out = {'liste': liste, 'count': ozet['toplam'], 'ozet': ozet}
    if qstats:
        out['query_stats'] = qstats
    return out


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
