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

from modules.nexgen.cari_sorumlu_service import can_view_cari, can_view_cari_ticari
from modules.nexgen.cari360_relation_policy import (
    classify_gorusme_root,
    classify_mo_gorusme_parent,
    classify_siparis_parent,
    load_gorusme_cari_map,
    load_siparis_cari_map,
    resolve_tek_sorumlu,
    siparis_operasyon_uyarilari,
)

# Sonuçlanmış sipariş durumları — mock dağılım + sistemde görülen kapanış kodları.
# ONAYLANDI / URETIMDE vb. hâlâ süreçte → aktif sayılır.
_SIPARIS_PASIF = frozenset({
    'REDDEDILDI', 'IPTAL', 'IPTAL_EDILDI', 'TAMAMLANDI', 'KAPANDI', 'IPTALEDILDI',
})

# Fiziksel olarak gerçekleşmiş sevkiyat durumları.
# HAZIRLANIYOR = hazırlık aşaması, henüz fiziksel sevk değil → SEVK KG'ye dahil edilmez.
_SEVK_GERCEKLESMIS = frozenset({
    'SEVK_EDILDI', 'TESLIM_EDILDI', 'TAMAMLANDI',
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
        # Yalnız fiziksel gerçekleşmiş sevkiyatlar (_SEVK_GERCEKLESMIS)
        _sg_ph = ','.join('?' * len(_SEVK_GERCEKLESMIS))
        _sg_list = list(_SEVK_GERCEKLESMIS)
        toplam_sevkiyat = int(con.execute(
            f'SELECT COUNT(*) FROM mo_musteri_sevkiyat '
            f'WHERE cari_id=? AND COALESCE(aktif, 1)=1 AND durum IN ({_sg_ph})',
            [cid] + _sg_list,
        ).fetchone()[0])
        if _tablo_var(con, 'mo_musteri_sevkiyat_kalem'):
            kg_row = con.execute(
                f"""
                SELECT COALESCE(SUM(k.miktar_kg), 0)
                FROM mo_musteri_sevkiyat_kalem k
                JOIN mo_musteri_sevkiyat s ON s.id = k.sevkiyat_id
                WHERE s.cari_id=? AND COALESCE(s.aktif, 1)=1
                  AND s.durum IN ({_sg_ph})
                """,
                [cid] + _sg_list,
            ).fetchone()
            toplam_sevk_kg = float(kg_row[0] or 0)
        son = con.execute(
            f"""
            SELECT COALESCE(sevk_tarihi, olusturma_tarihi) AS t
            FROM mo_musteri_sevkiyat
            WHERE cari_id=? AND COALESCE(aktif, 1)=1 AND durum IN ({_sg_ph})
            ORDER BY COALESCE(sevk_tarihi, olusturma_tarihi) DESC, id DESC
            LIMIT 1
            """,
            [cid] + _sg_list,
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

    # Tahsilat özeti — mo_tahsilat_kayit üzerinden (yetki gerektirmez; sadece özet)
    tahsilat_ozet: dict[str, Any] = {
        'son_tahsilat_tarihi': None,
        'son_tahsilat_tutari': None,
        'toplam_alinan': None,
        'bekleyen_adet': 0,
    }
    if _tablo_var(con, 'mo_tahsilat_kayit'):
        son = con.execute(
            """SELECT alinan_tarih, alinan_tutar FROM mo_tahsilat_kayit
               WHERE cari_id=? AND COALESCE(aktif,1)=1 AND durum='ONAYLANDI'
               ORDER BY alinan_tarih DESC, id DESC LIMIT 1""",
            (cid,),
        ).fetchone()
        if son and son['alinan_tarih']:
            tahsilat_ozet['son_tahsilat_tarihi'] = _fmt_dt(son['alinan_tarih'])
            tahsilat_ozet['son_tahsilat_tutari'] = _fmt_num(son['alinan_tutar'])
        top = con.execute(
            """SELECT COALESCE(SUM(alinan_tutar), 0) FROM mo_tahsilat_kayit
               WHERE cari_id=? AND COALESCE(aktif,1)=1 AND durum='ONAYLANDI'""",
            (cid,),
        ).fetchone()
        if top:
            tahsilat_ozet['toplam_alinan'] = _fmt_num(top[0])
        bek = con.execute(
            """SELECT COUNT(*) FROM mo_tahsilat_kayit
               WHERE cari_id=? AND COALESCE(aktif,1)=1
               AND durum NOT IN ('ONAYLANDI','IPTAL','REDDEDILDI')""",
            (cid,),
        ).fetchone()
        tahsilat_ozet['bekleyen_adet'] = int(bek[0] or 0)

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
        'tahsilat_ozet': tahsilat_ozet,
    }


def _siparis_date_next_day(iso_date: str) -> str:
    """Bitiş tarihi filtresi: < ertesi gün."""
    import datetime
    try:
        dt = datetime.date.fromisoformat(iso_date.strip()[:10])
        return (dt + datetime.timedelta(days=1)).isoformat()
    except ValueError:
        return iso_date.strip()[:10]


def _build_siparis_filter_sql(
    con: sqlite3.Connection,
    *,
    siparis_no: str | None = None,
    tarih_baslangic: str | None = None,
    tarih_bitis: str | None = None,
    durumlar: list[str] | None = None,
    termin_baslangic: str | None = None,
    termin_bitis: str | None = None,
    odeme_tipleri: list[str] | None = None,
    vade_min: int | None = None,
    vade_max: int | None = None,
    para_birimleri: list[str] | None = None,
    toplam_min: float | None = None,
    toplam_max: float | None = None,
    plan_kodu: str | None = None,
    batch_kodu: str | None = None,
    sevk_baslangic: str | None = None,
    sevk_bitis: str | None = None,
    try_min: float | None = None,
    try_max: float | None = None,
    fiyat_tipleri: list[str] | None = None,
    fiyat_min: float | None = None,
    fiyat_max: float | None = None,
    uretilen_kg_min: float | None = None,
    uretilen_kg_max: float | None = None,
    kalem_min: int | None = None,
    kalem_max: int | None = None,
    numune_durumlari: list[str] | None = None,
    sevk_kg_min: float | None = None,
    sevk_kg_max: float | None = None,
) -> tuple[str, list[Any]]:
    """Sipariş listesi COUNT/SELECT için parameterized WHERE parçaları."""
    filter_clauses: list[str] = []
    filter_params: list[Any] = []
    scols = _kolonlar(con, 'nexgen_planlama_siparis') if _tablo_var(con, 'nexgen_planlama_siparis') else set()
    has_kalem_tbl = _tablo_var(con, 'nexgen_planlama_siparis_kalem')
    has_plan_tbl = _tablo_var(con, 'nexgen_uretim_plan')
    has_batch_tbl = _tablo_var(con, 'nexgen_uretim_batch')
    has_sevk_tbl = _tablo_var(con, 'mo_musteri_sevkiyat')
    has_sevk_kalem_tbl = _tablo_var(con, 'mo_musteri_sevkiyat_kalem')
    has_parca_tbl = _tablo_var(con, 'nexgen_uretim_parca')
    kcols = _kolonlar(con, 'nexgen_planlama_siparis_kalem') if has_kalem_tbl else set()

    if siparis_no and siparis_no.strip():
        filter_clauses.append('siparis_no LIKE ?')
        filter_params.append('%' + siparis_no.strip() + '%')

    if tarih_baslangic and tarih_baslangic.strip():
        filter_clauses.append("COALESCE(olusturma_tarihi, '') >= ?")
        filter_params.append(tarih_baslangic.strip()[:10])

    if tarih_bitis and tarih_bitis.strip():
        filter_clauses.append("COALESCE(olusturma_tarihi, '') < ?")
        filter_params.append(_siparis_date_next_day(tarih_bitis))

    if durumlar:
        clean = [d.strip().upper() for d in durumlar if d and d.strip()]
        if clean:
            ph = ','.join('?' * len(clean))
            filter_clauses.append(f'durum IN ({ph})')
            filter_params.extend(clean)

    if termin_baslangic and termin_baslangic.strip():
        filter_clauses.append("COALESCE(termin_tarihi, '') >= ?")
        filter_params.append(termin_baslangic.strip()[:10])

    if termin_bitis and termin_bitis.strip():
        filter_clauses.append("COALESCE(termin_tarihi, '') < ?")
        filter_params.append(_siparis_date_next_day(termin_bitis))

    if odeme_tipleri and 'odeme_tipi' in scols:
        parts: list[str] = []
        normal = [o.strip().upper() for o in odeme_tipleri if o and o.strip() and o.strip().upper() != 'BELIRTILMEMIS']
        if normal:
            ph = ','.join('?' * len(normal))
            parts.append(f'UPPER(TRIM(COALESCE(odeme_tipi, ""))) IN ({ph})')
            filter_params.extend(normal)
        if any(o.strip().upper() == 'BELIRTILMEMIS' for o in odeme_tipleri if o):
            parts.append("(odeme_tipi IS NULL OR TRIM(COALESCE(odeme_tipi, '')) = '')")
        if parts:
            filter_clauses.append('(' + ' OR '.join(parts) + ')')

    if vade_min is not None and 'vade_gun' in scols:
        filter_clauses.append('CAST(vade_gun AS INTEGER) >= ?')
        filter_params.append(int(vade_min))

    if vade_max is not None and 'vade_gun' in scols:
        filter_clauses.append('CAST(vade_gun AS INTEGER) <= ?')
        filter_params.append(int(vade_max))

    if para_birimleri and 'anlasma_para_birimi' in scols:
        pbs = [p.strip().upper() for p in para_birimleri if p and p.strip()]
        if pbs:
            ph = ','.join('?' * len(pbs))
            filter_clauses.append(f'UPPER(TRIM(COALESCE(anlasma_para_birimi, ""))) IN ({ph})')
            filter_params.extend(pbs)

    if has_kalem_tbl and (toplam_min is not None or toplam_max is not None):
        if 'satir_tutari' in kcols and 'birim_fiyat' in kcols:
            sum_expr = (
                '(SELECT SUM(CASE WHEN k.birim_fiyat IS NOT NULL THEN k.satir_tutari END) '
                'FROM nexgen_planlama_siparis_kalem k '
                'WHERE k.planlama_siparis_id = nexgen_planlama_siparis.id)'
            )
            if toplam_min is not None:
                filter_clauses.append(f'{sum_expr} >= ?')
                filter_params.append(float(toplam_min))
            if toplam_max is not None:
                filter_clauses.append(f'{sum_expr} <= ?')
                filter_params.append(float(toplam_max))

    if plan_kodu and plan_kodu.strip() and has_plan_tbl:
        filter_clauses.append(
            """
            EXISTS (
                SELECT 1 FROM nexgen_uretim_plan p
                WHERE p.planlama_siparis_id = nexgen_planlama_siparis.id
                  AND COALESCE(p.durum, '') NOT IN ('IPTAL')
                  AND p.plan_kodu LIKE ?
            )
            """
        )
        filter_params.append('%' + plan_kodu.strip() + '%')

    if batch_kodu and batch_kodu.strip() and has_plan_tbl and has_batch_tbl:
        filter_clauses.append(
            """
            EXISTS (
                SELECT 1 FROM nexgen_uretim_batch b
                JOIN nexgen_uretim_plan p ON p.id = b.plan_id
                WHERE p.planlama_siparis_id = nexgen_planlama_siparis.id
                  AND COALESCE(p.durum, '') NOT IN ('IPTAL')
                  AND b.batch_kodu LIKE ?
            )
            """
        )
        filter_params.append('%' + batch_kodu.strip() + '%')

    if has_sevk_tbl and (sevk_baslangic or sevk_bitis):
        sevk_expr = (
            '(SELECT MAX(COALESCE(sevk_tarihi, olusturma_tarihi)) '
            'FROM mo_musteri_sevkiyat sv '
            'WHERE sv.siparis_id = nexgen_planlama_siparis.id AND COALESCE(sv.aktif, 1)=1)'
        )
        if sevk_baslangic and sevk_baslangic.strip():
            filter_clauses.append(f"COALESCE({sevk_expr}, '') >= ?")
            filter_params.append(sevk_baslangic.strip()[:10])
        if sevk_bitis and sevk_bitis.strip():
            filter_clauses.append(f"COALESCE({sevk_expr}, '') < ?")
            filter_params.append(_siparis_date_next_day(sevk_bitis))

    if has_kalem_tbl and (try_min is not None or try_max is not None):
        if 'satir_tutari_try' in kcols and 'birim_fiyat' in kcols:
            try_expr = (
                '(SELECT SUM(CASE WHEN k.birim_fiyat IS NOT NULL THEN k.satir_tutari_try END) '
                'FROM nexgen_planlama_siparis_kalem k '
                'WHERE k.planlama_siparis_id = nexgen_planlama_siparis.id)'
            )
            if try_min is not None:
                filter_clauses.append(f'{try_expr} >= ?')
                filter_params.append(float(try_min))
            if try_max is not None:
                filter_clauses.append(f'{try_expr} <= ?')
                filter_params.append(float(try_max))

    if has_kalem_tbl and 'birim_fiyat' in kcols and (
        fiyat_tipleri or fiyat_min is not None or fiyat_max is not None
    ):
        fiyatli_n = (
            '(SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem k '
            'WHERE k.planlama_siparis_id = nexgen_planlama_siparis.id '
            'AND COALESCE(k.net_birim_fiyat, k.birim_fiyat) IS NOT NULL)'
        )
        fiyat_min_expr = (
            '(SELECT MIN(COALESCE(k.net_birim_fiyat, k.birim_fiyat)) '
            'FROM nexgen_planlama_siparis_kalem k '
            'WHERE k.planlama_siparis_id = nexgen_planlama_siparis.id '
            'AND COALESCE(k.net_birim_fiyat, k.birim_fiyat) IS NOT NULL)'
        )
        fiyat_max_expr = (
            '(SELECT MAX(COALESCE(k.net_birim_fiyat, k.birim_fiyat)) '
            'FROM nexgen_planlama_siparis_kalem k '
            'WHERE k.planlama_siparis_id = nexgen_planlama_siparis.id '
            'AND COALESCE(k.net_birim_fiyat, k.birim_fiyat) IS NOT NULL)'
        )
        if fiyat_tipleri:
            tip_parts: list[str] = []
            tips = {t.strip().upper() for t in fiyat_tipleri if t and t.strip()}
            if 'TEK_FIYAT' in tips:
                tip_parts.append(f'({fiyatli_n} > 0 AND {fiyat_min_expr} = {fiyat_max_expr})')
            if 'COKLU' in tips:
                tip_parts.append(f'({fiyatli_n} > 0 AND {fiyat_min_expr} != {fiyat_max_expr})')
            if 'BELIRTILMEMIS' in tips:
                tip_parts.append(f'({fiyatli_n} = 0)')
            if tip_parts:
                filter_clauses.append('(' + ' OR '.join(tip_parts) + ')')
        if fiyat_min is not None:
            filter_clauses.append(f'{fiyat_min_expr} >= ?')
            filter_params.append(float(fiyat_min))
        if fiyat_max is not None:
            filter_clauses.append(f'{fiyat_max_expr} <= ?')
            filter_params.append(float(fiyat_max))

    if has_plan_tbl and has_parca_tbl and (uretilen_kg_min is not None or uretilen_kg_max is not None):
        uretilen_expr = (
            '(SELECT COALESCE(SUM(pr.uretilen_kg), 0) '
            'FROM nexgen_uretim_parca pr '
            'JOIN nexgen_uretim_plan p ON p.id = pr.plan_id '
            'WHERE p.planlama_siparis_id = nexgen_planlama_siparis.id '
            "AND COALESCE(p.durum, '') NOT IN ('IPTAL'))"
        )
        if uretilen_kg_min is not None:
            filter_clauses.append(f'{uretilen_expr} >= ?')
            filter_params.append(float(uretilen_kg_min))
        if uretilen_kg_max is not None:
            filter_clauses.append(f'{uretilen_expr} <= ?')
            filter_params.append(float(uretilen_kg_max))

    if has_kalem_tbl and (kalem_min is not None or kalem_max is not None):
        kalem_expr = (
            '(SELECT COUNT(*) FROM nexgen_planlama_siparis_kalem k '
            'WHERE k.planlama_siparis_id = nexgen_planlama_siparis.id)'
        )
        if kalem_min is not None:
            filter_clauses.append(f'{kalem_expr} >= ?')
            filter_params.append(int(kalem_min))
        if kalem_max is not None:
            filter_clauses.append(f'{kalem_expr} <= ?')
            filter_params.append(int(kalem_max))

    if has_kalem_tbl and numune_durumlari and 'numune_talep_id' in kcols:
        numune_parts: list[str] = []
        nd = {n.strip().upper() for n in numune_durumlari if n and n.strip()}
        numune_exists = (
            'EXISTS (SELECT 1 FROM nexgen_planlama_siparis_kalem k '
            'WHERE k.planlama_siparis_id = nexgen_planlama_siparis.id '
            'AND k.numune_talep_id IS NOT NULL)'
        )
        if 'VAR' in nd:
            numune_parts.append(numune_exists)
        if 'YOK' in nd:
            numune_parts.append(f'NOT {numune_exists}')
        if numune_parts:
            filter_clauses.append('(' + ' OR '.join(numune_parts) + ')')

    if has_sevk_tbl and has_sevk_kalem_tbl and (sevk_kg_min is not None or sevk_kg_max is not None):
        sevk_kg_expr = (
            '(SELECT COALESCE(SUM(k.miktar_kg), 0) '
            'FROM mo_musteri_sevkiyat_kalem k '
            'JOIN mo_musteri_sevkiyat s ON s.id = k.sevkiyat_id '
            'WHERE s.siparis_id = nexgen_planlama_siparis.id AND COALESCE(s.aktif, 1)=1)'
        )
        if sevk_kg_min is not None:
            filter_clauses.append(f'{sevk_kg_expr} >= ?')
            filter_params.append(float(sevk_kg_min))
        if sevk_kg_max is not None:
            filter_clauses.append(f'{sevk_kg_expr} <= ?')
            filter_params.append(float(sevk_kg_max))

    filter_sql = (' AND ' + ' AND '.join(filter_clauses)) if filter_clauses else ''
    return filter_sql, filter_params


def load_cari360_siparisler(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None,
    *,
    limit: int = 50,
    offset: int = 0,
    siparis_no: str | None = None,
    tarih_baslangic: str | None = None,
    tarih_bitis: str | None = None,
    durumlar: list[str] | None = None,
    termin_baslangic: str | None = None,
    termin_bitis: str | None = None,
    odeme_tipleri: list[str] | None = None,
    vade_min: int | None = None,
    vade_max: int | None = None,
    para_birimleri: list[str] | None = None,
    toplam_min: float | None = None,
    toplam_max: float | None = None,
    plan_kodu: str | None = None,
    batch_kodu: str | None = None,
    sevk_baslangic: str | None = None,
    sevk_bitis: str | None = None,
    try_min: float | None = None,
    try_max: float | None = None,
    fiyat_tipleri: list[str] | None = None,
    fiyat_min: float | None = None,
    fiyat_max: float | None = None,
    uretilen_kg_min: float | None = None,
    uretilen_kg_max: float | None = None,
    kalem_min: int | None = None,
    kalem_max: int | None = None,
    numune_durumlari: list[str] | None = None,
    sevk_kg_min: float | None = None,
    sevk_kg_max: float | None = None,
) -> dict[str, Any]:
    """Son N sipariş — read-only. Pagination: limit/offset. Filtre: server-side WHERE."""
    _assert_cari(con, cari_id, kullanici_id, yk)
    cid = int(cari_id)
    limit = max(1, min(int(limit or 50), 100))
    offset = max(0, int(offset or 0))

    if not _tablo_var(con, 'nexgen_planlama_siparis'):
        return {'liste': [], 'count': 0, 'total_count': 0, 'page': 1, 'page_size': limit, 'total_pages': 0}

    filter_sql, filter_params = _build_siparis_filter_sql(
        con,
        siparis_no=siparis_no,
        tarih_baslangic=tarih_baslangic,
        tarih_bitis=tarih_bitis,
        durumlar=durumlar,
        termin_baslangic=termin_baslangic,
        termin_bitis=termin_bitis,
        odeme_tipleri=odeme_tipleri,
        vade_min=vade_min,
        vade_max=vade_max,
        para_birimleri=para_birimleri,
        toplam_min=toplam_min,
        toplam_max=toplam_max,
        plan_kodu=plan_kodu,
        batch_kodu=batch_kodu,
        sevk_baslangic=sevk_baslangic,
        sevk_bitis=sevk_bitis,
        try_min=try_min,
        try_max=try_max,
        fiyat_tipleri=fiyat_tipleri,
        fiyat_min=fiyat_min,
        fiyat_max=fiyat_max,
        uretilen_kg_min=uretilen_kg_min,
        uretilen_kg_max=uretilen_kg_max,
        kalem_min=kalem_min,
        kalem_max=kalem_max,
        numune_durumlari=numune_durumlari,
        sevk_kg_min=sevk_kg_min,
        sevk_kg_max=sevk_kg_max,
    )

    # Filtrelenmiş toplam — COUNT aynı WHERE'i kullanır
    total_count = con.execute(
        f'SELECT COUNT(*) FROM nexgen_planlama_siparis WHERE cari_id=?{filter_sql}',
        [cid] + filter_params,
    ).fetchone()[0]

    # FAZ-3C: Cari360 GET read-only — soft-write/backfill çağrılmaz
    # (backfill_kalem_uretim_planlari omurga_link içinde kalır; yazma ekranları kullanabilir)

    has_kalem = _tablo_var(con, 'nexgen_planlama_siparis_kalem')
    has_sevk = _tablo_var(con, 'mo_musteri_sevkiyat')
    has_sevk_kalem = _tablo_var(con, 'mo_musteri_sevkiyat_kalem')
    has_plan = _tablo_var(con, 'nexgen_uretim_plan')
    has_batch = _tablo_var(con, 'nexgen_uretim_batch')
    has_parca = _tablo_var(con, 'nexgen_uretim_parca')

    scols = _kolonlar(con, 'nexgen_planlama_siparis')
    mo_sel = ', mo_gorusme_id' if 'mo_gorusme_id' in scols else ', NULL AS mo_gorusme_id'
    rows = con.execute(
        f"""
        SELECT id, siparis_no, olusturma_tarihi, durum,
               termin_tarihi, musteri_termin, onerilen_termin
               {mo_sel}
        FROM nexgen_planlama_siparis
        WHERE cari_id=?{filter_sql}
        ORDER BY COALESCE(olusturma_tarihi, '') DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        [cid] + filter_params + [limit, offset],
    ).fetchall()

    gorusme_ids = {
        int(r['mo_gorusme_id'])
        for r in rows
        if r['mo_gorusme_id'] not in (None, '', 0)
    }
    gorusme_by_id = load_gorusme_cari_map(con, gorusme_ids)
    sorumlu_meta = resolve_tek_sorumlu(con, cid)

    # ─── Batch ön-yükleme (N+1 önlemi) ───────────────────────────────────────
    siparis_ids = [int(r['id']) for r in rows]
    kcols_set = _kolonlar(con, 'nexgen_planlama_siparis_kalem') if has_kalem else set()
    has_nt_col = 'numune_talep_id' in kcols_set
    has_rf_col = 'rf_renk_id' in kcols_set

    # Ticari yetkiyi şimdi hesapla (batch'ten önce bilinmeli)
    from modules.nexgen.cari360_ticari_ozet_service import enrich_siparis_listesi_ticari
    ticari_ok = can_view_cari_ticari(con, kullanici_id, cid, yk)

    # Kalem batch — tek query
    kalem_map: dict[int, list[dict[str, Any]]] = {}
    if has_kalem and siparis_ids:
        kalem_map = _load_siparis_kalemleri_batch(con, siparis_ids, ticari_ok)

    # Aggregate counts — tek query (COUNT + RF + numune)
    agg_count: dict[int, int] = {}
    agg_rf: dict[int, int] = {}
    if has_kalem and siparis_ids:
        ph = ','.join('?' * len(siparis_ids))
        for agg_row in con.execute(
            f'SELECT planlama_siparis_id AS sid, COUNT(*) AS cnt'
            f' FROM nexgen_planlama_siparis_kalem'
            f' WHERE planlama_siparis_id IN ({ph})'
            f' GROUP BY planlama_siparis_id',
            siparis_ids,
        ).fetchall():
            agg_count[int(agg_row['sid'])] = int(agg_row['cnt'])
        if has_rf_col:
            for agg_row in con.execute(
                f'SELECT planlama_siparis_id AS sid, COUNT(*) AS cnt'
                f' FROM nexgen_planlama_siparis_kalem'
                f' WHERE planlama_siparis_id IN ({ph})'
                f'   AND rf_renk_id IS NOT NULL AND rf_renk_id!=0'
                f' GROUP BY planlama_siparis_id',
                siparis_ids,
            ).fetchall():
                agg_rf[int(agg_row['sid'])] = int(agg_row['cnt'])

    # Numune batch — tek query
    numune_map: dict[int, list[dict[str, Any]]] = {sid: [] for sid in siparis_ids}
    if has_kalem and has_nt_col and _tablo_var(con, 'nexgen_numune_talep') and siparis_ids:
        ph = ','.join('?' * len(siparis_ids))
        for nr in con.execute(
            f"""
            SELECT DISTINCT k.planlama_siparis_id AS sid, k.numune_talep_id AS nid, n.talep_kodu
            FROM nexgen_planlama_siparis_kalem k
            JOIN nexgen_numune_talep n ON n.id = k.numune_talep_id
            WHERE k.planlama_siparis_id IN ({ph})
              AND k.numune_talep_id IS NOT NULL
            ORDER BY k.planlama_siparis_id, n.talep_kodu
            """,
            siparis_ids,
        ).fetchall():
            nid = int(nr['nid'])
            sid_n = int(nr['sid'])
            numune_map.setdefault(sid_n, []).append({
                'id': nid,
                'talep_kodu': nr['talep_kodu'] or f'#{nid}',
                'detay_url': f'/nexgen/numune-talep?id={nid}',
            })
    # ─── /Batch ───────────────────────────────────────────────────────────────

    liste: list[dict[str, Any]] = []
    for r in rows:
        sid = int(r['id'])
        termin = r['termin_tarihi'] or r['musteri_termin'] or r['onerilen_termin']

        kalem_sayisi = agg_count.get(sid, 0)
        rf_kalem_sayisi = agg_rf.get(sid, 0)
        bagli_numuneler = numune_map.get(sid, [])
        bagli_numune_sayisi = len(bagli_numuneler)

        if False:  # N+1 döngüsü kaldırıldı; batch yukarıda
            pass

        # Sipariş kaleminde kg kolonu yok (L/S/M). Toplam KG uydurulmaz.
        toplam_kg = None
        sevk_kg = None
        kalan_kg = None
        son_sevk = None
        if has_sevk:
            _sp_ph = ','.join('?' * len(_SEVK_GERCEKLESMIS))
            _sp_list = list(_SEVK_GERCEKLESMIS)
            son_row = con.execute(
                f"""
                SELECT COALESCE(sevk_tarihi, olusturma_tarihi) AS t
                FROM mo_musteri_sevkiyat
                WHERE siparis_id=? AND COALESCE(aktif, 1)=1
                  AND durum IN ({_sp_ph})
                ORDER BY COALESCE(sevk_tarihi, olusturma_tarihi) DESC, id DESC
                LIMIT 1
                """,
                [sid] + _sp_list,
            ).fetchone()
            if son_row and son_row['t']:
                son_sevk = son_row['t']
            if has_sevk_kalem:
                kg_row = con.execute(
                    f"""
                    SELECT COALESCE(SUM(k.miktar_kg), 0)
                    FROM mo_musteri_sevkiyat_kalem k
                    JOIN mo_musteri_sevkiyat s ON s.id = k.sevkiyat_id
                    WHERE s.siparis_id=? AND COALESCE(s.aktif, 1)=1
                      AND s.durum IN ({_sp_ph})
                    """,
                    [sid] + _sp_list,
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

        rel = classify_mo_gorusme_parent(
            r['mo_gorusme_id'], cid, gorusme_by_id, kind='SIPARIS',
        )
        op_uyari = siparis_operasyon_uyarilari(
            durum=r['durum'],
            kalem_sayisi=kalem_sayisi,
            rf_kalem_sayisi=rf_kalem_sayisi,
            uretim_plan_sayisi=plan_sayisi,
        )
        zincir_uy = list(rel['zincir_uyarilari']) + op_uyari
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
            'mo_gorusme_id': (
                int(r['mo_gorusme_id'])
                if r['mo_gorusme_id'] not in (None, '', 0) else None
            ),
            'parent_type': rel['parent_type'],
            'parent_id': rel['parent_id'],
            'baslangic_tipi': rel['baslangic_tipi'],
            'zincir_eksik': rel['zincir_eksik'],
            'zincir_uyarilari': zincir_uy,
            'baglanti_kaynagi': rel['baglanti_kaynagi'],
            'dogrudan_operasyon': rel['dogrudan_operasyon'],
            'manuel_inceleme': rel['manuel_inceleme'],
            # C360-2: batch kalem detayları (ticari_ok zaten uygulandı)
            'kalemler': kalem_map.get(sid, []),
        })

    # T4: hassas ticari alanlar yalnız can_view_cari_ticari ile
    # ticari_ok ve import batch'ten önce yapıldı; burada yeniden hesaplamıyoruz
    liste = enrich_siparis_listesi_ticari(con, liste, ticari_gorunur=ticari_ok)
    import math as _math
    total_pages = max(1, _math.ceil(total_count / limit)) if total_count else 1
    current_page = (offset // limit) + 1
    return {
        'liste': liste,
        'count': len(liste),
        'total_count': total_count,
        'page': current_page,
        'page_size': limit,
        'total_pages': total_pages,
        'ticari_gorunur': ticari_ok,
        'sorumlu': sorumlu_meta.get('sorumlu'),
        'sorumlu_uyarilari': sorumlu_meta.get('sorumlu_uyarilari') or [],
        'sorumlu_atanmamis': bool(sorumlu_meta.get('sorumlu_atanmamis')),
    }


def _siparis_batch_kodlari(con: sqlite3.Connection, siparis_id: int | None) -> list[str]:
    """Canonical batch_kodu listesi — nexgen_uretim_batch üzerinden."""
    if not siparis_id or not _tablo_var(con, 'nexgen_uretim_batch'):
        return []
    if not _tablo_var(con, 'nexgen_uretim_plan'):
        return []
    rows = con.execute(
        """
        SELECT DISTINCT b.batch_kodu
        FROM nexgen_uretim_batch b
        JOIN nexgen_uretim_plan p ON p.id = b.plan_id
        WHERE p.planlama_siparis_id=?
          AND COALESCE(p.durum, '') NOT IN ('IPTAL')
          AND b.batch_kodu IS NOT NULL AND TRIM(b.batch_kodu) != ''
        ORDER BY b.id ASC
        """,
        (int(siparis_id),),
    ).fetchall()
    return [str(r['batch_kodu']) for r in rows if r['batch_kodu']]


def _siparis_plan_url(con: sqlite3.Connection, siparis_id: int | None) -> str | None:
    if not siparis_id or not _tablo_var(con, 'nexgen_uretim_plan'):
        return None
    row = con.execute(
        """
        SELECT id FROM nexgen_uretim_plan
        WHERE planlama_siparis_id=? AND COALESCE(durum, '') NOT IN ('IPTAL')
        ORDER BY id ASC LIMIT 1
        """,
        (int(siparis_id),),
    ).fetchone()
    if not row:
        return None
    return f'/nexgen/uretim-emirleri?vurgu={int(row["id"])}'


def load_cari360_sevkiyatlar(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None,
    *,
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    """Canonical mo_musteri_sevkiyat — cari_id doğrudan filtre, pagination."""
    from modules.nexgen.mo_sevkiyat_config import DURUM_ETIKET

    _assert_cari(con, cari_id, kullanici_id, yk)
    cid = int(cari_id)
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 10), 100))
    offset = (page - 1) * page_size

    empty = {
        'liste': [], 'count': 0, 'total_count': 0,
        'page': page, 'page_size': page_size, 'total_pages': 0,
    }

    if not _tablo_var(con, 'mo_musteri_sevkiyat'):
        return empty

    has_kalem = _tablo_var(con, 'mo_musteri_sevkiyat_kalem')
    has_sip = _tablo_var(con, 'nexgen_planlama_siparis')

    total_count = int(con.execute(
        """
        SELECT COUNT(*) FROM mo_musteri_sevkiyat
        WHERE cari_id=? AND COALESCE(aktif, 1)=1
        """,
        (cid,),
    ).fetchone()[0])
    total_pages = max(1, (total_count + page_size - 1) // page_size) if total_count else 0

    rows = con.execute(
        """
        SELECT id, sevkiyat_no, irsaliye_no, sevk_tarihi, olusturma_tarihi,
               hazirlik_tarihi, teslim_tarihi, durum, siparis_id,
               arac_plaka, sofor, kargo_firmasi, kargo_takip_no,
               teslim_alan, teslim_durumu, notlar
        FROM mo_musteri_sevkiyat
        WHERE cari_id=? AND COALESCE(aktif, 1)=1
        ORDER BY COALESCE(sevk_tarihi, olusturma_tarihi) DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (cid, page_size, offset),
    ).fetchall()

    sip_ids = {
        int(r['siparis_id']) for r in rows if r['siparis_id'] not in (None, '', 0)
    }
    sip_cari_map = load_siparis_cari_map(con, sip_ids)
    sorumlu_meta = resolve_tek_sorumlu(con, cid)

    liste: list[dict[str, Any]] = []
    for r in rows:
        sevk_id = int(r['id'])
        siparis_no = None
        siparis_tarihi = None
        siparis_id = r['siparis_id']
        if siparis_id and has_sip:
            sn = con.execute(
                """
                SELECT siparis_no, olusturma_tarihi, durum
                FROM nexgen_planlama_siparis WHERE id=?
                """,
                (int(siparis_id),),
            ).fetchone()
            if sn:
                siparis_no = sn['siparis_no']
                siparis_tarihi = _fmt_dt(sn['olusturma_tarihi'])

        kalemler: list[dict[str, Any]] = []
        sevk_toplam_kg = 0.0
        if has_kalem:
            krows = con.execute(
                """
                SELECT siparis_kalem_id, urun_adi, renk_ad, formul_ad,
                       miktar_kg, miktar_adet, notlar
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
                    'siparis_kalem_id': int(k['siparis_kalem_id']) if k['siparis_kalem_id'] else None,
                    'urun': k['urun_adi'] or '—',
                    'renk': k['renk_ad'] or '—',
                    'formul_ad': k['formul_ad'] or '',
                    'sevk_kg': _fmt_num(kg) or 0,
                    'miktar_adet': k['miktar_adet'],
                    'notlar': k['notlar'] or '',
                })

        ilk = kalemler[0] if kalemler else {'urun': '—', 'renk': '—', 'sevk_kg': 0}
        batch_kodlari = _siparis_batch_kodlari(con, int(siparis_id) if siparis_id else None)
        batch_kodu = batch_kodlari[0] if batch_kodlari else ''
        plan_url = _siparis_plan_url(con, int(siparis_id) if siparis_id else None)

        rel = classify_siparis_parent(
            siparis_id, cid, sip_cari_map, null_tipi='DOGRUDAN_SEVKIYAT',
        )
        uretim_var = bool(batch_kodlari)
        zincir_uy = list(rel['zincir_uyarilari'])
        if siparis_id and not uretim_var:
            zincir_uy.append('URETIM_BILGISI_YOK')

        durum_raw = r['durum'] or ''
        gercek_sevk = (r['sevk_tarihi'] or '').strip()
        liste.append({
            'id': sevk_id,
            'sevkiyat_no': r['sevkiyat_no'] or '',
            'irsaliye_no': r['irsaliye_no'] or '',
            'gercek_sevk_tarihi': _fmt_dt(gercek_sevk) if gercek_sevk else None,
            'tarih': _fmt_dt(gercek_sevk or r['olusturma_tarihi']),
            'hazirlik_tarihi': _fmt_dt(r['hazirlik_tarihi']) if r['hazirlik_tarihi'] else None,
            'teslim_tarihi': _fmt_dt(r['teslim_tarihi']) if r['teslim_tarihi'] else None,
            'siparis_id': int(siparis_id) if siparis_id else None,
            'siparis_no': siparis_no or '',
            'siparis_tarihi': siparis_tarihi,
            'siparis_url': (
                f'/nexgen/pazarlama?siparis={int(siparis_id)}' if siparis_id else None
            ),
            'sevkiyat_url': f'/nexgen/sevkiyat/{sevk_id}',
            'plan_url': plan_url,
            'batch_kodu': batch_kodu,
            'batch_kodlari': batch_kodlari,
            'batch_sayisi': len(batch_kodlari),
            'urun': ilk['urun'],
            'renk': ilk['renk'],
            'sevk_kg': _fmt_num(sevk_toplam_kg) or 0,
            'kalem_kg_ozet': ilk['sevk_kg'] if len(kalemler) == 1 else None,
            'durum': durum_raw,
            'durum_etiket': DURUM_ETIKET.get(durum_raw, durum_raw),
            'kalem_sayisi': len(kalemler),
            'kalemler': kalemler,
            'arac_plaka': r['arac_plaka'] or '',
            'sofor': r['sofor'] or '',
            'kargo_firmasi': r['kargo_firmasi'] or '',
            'kargo_takip_no': r['kargo_takip_no'] or '',
            'teslim_alan': r['teslim_alan'] or '',
            'teslim_durumu': r['teslim_durumu'] or '',
            'notlar': r['notlar'] or '',
            'parent_type': rel['parent_type'] or 'SIPARIS',
            'parent_id': rel['parent_id'],
            'baslangic_tipi': 'SEVKIYAT',
            'zincir_eksik': rel['zincir_eksik'],
            'zincir_uyarilari': zincir_uy,
            'baglanti_kaynagi': rel['baglanti_kaynagi'],
            'dogrudan_operasyon': rel['dogrudan_operasyon'],
            'manuel_inceleme': rel['manuel_inceleme'],
            'uretim_bilgisi_var': uretim_var,
        })

    return {
        'liste': liste,
        'count': len(liste),
        'total_count': total_count,
        'page': page,
        'page_size': page_size,
        'total_pages': total_pages,
        'sorumlu': sorumlu_meta.get('sorumlu'),
        'sorumlu_uyarilari': sorumlu_meta.get('sorumlu_uyarilari') or [],
        'sorumlu_atanmamis': bool(sorumlu_meta.get('sorumlu_atanmamis')),
    }


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


def _load_kalem_sevk_tarihleri_batch(
    con: sqlite3.Connection,
    kalem_ids: list[int],
) -> dict[int, dict[str, Any]]:
    """Kalem bazlı sevkiyat özeti — mo_musteri_sevkiyat_kalem.siparis_kalem_id FK.

    Döndürür: {kalem_id: {sevk_tarihi, sevkiyat_id, sevkiyat_no, sevkiyat_count}}
    - sevk_tarihi: MIN(sevk_tarihi) — ilk gerçek sevkiyat tarihi
    - sevkiyat_id: ilk sevkiyatın id'si (link için)
    - sevkiyat_no: ilk sevkiyatın no'su
    - sevkiyat_count: kaç aktif sevkiyat var (kısmi sevk tespiti)
    Filtre: aktif=1, durum IN ('SEVK_EDILDI','TESLIM_EDILDI','TAMAMLANDI'), sevk_tarihi NOT NULL.
    """
    if not kalem_ids or not _tablo_var(con, 'mo_musteri_sevkiyat_kalem'):
        return {}
    if not _tablo_var(con, 'mo_musteri_sevkiyat'):
        return {}
    ph = ','.join('?' * len(kalem_ids))
    # İlk sevkiyat (MIN tarih) için id ve no'yu subquery ile çek
    rows = con.execute(
        f"""
        SELECT
            k.siparis_kalem_id,
            COUNT(*) AS sevkiyat_count,
            MIN(s.sevk_tarihi) AS sevk_tarihi,
            MIN(s.id) AS ilk_sevkiyat_id
        FROM mo_musteri_sevkiyat_kalem k
        JOIN mo_musteri_sevkiyat s ON s.id = k.sevkiyat_id
        WHERE k.siparis_kalem_id IN ({ph})
          AND COALESCE(s.aktif, 1)=1
          AND s.sevk_tarihi IS NOT NULL AND s.sevk_tarihi != ''
          AND s.durum IN ('SEVK_EDILDI','TESLIM_EDILDI','TAMAMLANDI')
        GROUP BY k.siparis_kalem_id
        """,
        kalem_ids,
    ).fetchall()

    # sevkiyat_no için ayrı lookup (MIN id'nin no'su)
    ilk_ids = [r['ilk_sevkiyat_id'] for r in rows if r['ilk_sevkiyat_id'] is not None]
    sev_no_map: dict[int, str] = {}
    if ilk_ids:
        ph2 = ','.join('?' * len(ilk_ids))
        sev_rows = con.execute(
            f'SELECT id, sevkiyat_no FROM mo_musteri_sevkiyat WHERE id IN ({ph2})',
            ilk_ids,
        ).fetchall()
        for sr in sev_rows:
            sev_no_map[int(sr['id'])] = sr['sevkiyat_no'] or ''

    out: dict[int, dict[str, Any]] = {}
    for r in rows:
        kid = r['siparis_kalem_id']
        st = r['sevk_tarihi']
        if kid is None or not st:
            continue
        sev_id = r['ilk_sevkiyat_id']
        out[int(kid)] = {
            'sevk_tarihi': _fmt_dt(st) or '',
            'sevkiyat_id': int(sev_id) if sev_id else None,
            'sevkiyat_no': sev_no_map.get(int(sev_id), '') if sev_id else '',
            'sevkiyat_count': int(r['sevkiyat_count']),
        }
    return out


def _load_siparis_kalemleri_batch(
    con: sqlite3.Connection,
    siparis_ids: list[int],
    ticari_gorunur: bool,
) -> dict[int, list[dict[str, Any]]]:
    """Tek query ile tüm sipariş kalemlerini çek; N+1 önlenir.

    RF label ve plan kodu JOIN ile getir.
    Ticari alanlar (birim_fiyat, satir_tutari vb.) yalnızca ticari_gorunur=True ise eklenir.
    """
    if not siparis_ids or not _tablo_var(con, 'nexgen_planlama_siparis_kalem'):
        return {}

    kcols = _kolonlar(con, 'nexgen_planlama_siparis_kalem')
    has_rf = 'rf_renk_id' in kcols
    has_plan = _tablo_var(con, 'nexgen_uretim_plan')
    has_rf_tbl = _tablo_var(con, 'nexgen_rf_renk')

    ph = ','.join('?' * len(siparis_ids))

    # RF label JOIN (LEFT JOIN; yoksa NULL)
    rf_join = ''
    rf_sel = ''
    if has_rf and has_rf_tbl:
        rf_sel = ', rf.rf_kod AS _rf_kod, rf.ad AS _rf_ad, rf.durum AS _rf_durum'
        rf_join = ' LEFT JOIN nexgen_rf_renk rf ON rf.id = k.rf_renk_id'

    # Üretim plan_kodu JOIN
    plan_join = ''
    plan_sel = ''
    if has_plan and 'uretim_plan_id' in kcols:
        plan_sel = ', p.plan_kodu AS _plan_kodu'
        plan_join = ' LEFT JOIN nexgen_uretim_plan p ON p.id = k.uretim_plan_id'

    sql = (
        f'SELECT k.*{rf_sel}{plan_sel}'
        f' FROM nexgen_planlama_siparis_kalem k{rf_join}{plan_join}'
        f' WHERE k.planlama_siparis_id IN ({ph})'
        f' ORDER BY k.planlama_siparis_id, k.sira_no'
    )
    kalem_rows = con.execute(sql, siparis_ids).fetchall()
    sevk_map = _load_kalem_sevk_tarihleri_batch(
        con, [int(kr['id']) for kr in kalem_rows],
    )

    result: dict[int, list[dict[str, Any]]] = {sid: [] for sid in siparis_ids}
    for kr in kalem_rows:
        sid = int(kr['planlama_siparis_id'])
        # miktar_kg = L + S + M  (L/S/M birim ton değil; proje convention: doğrudan kg)
        ml = float(kr['miktar_l'] or 0)
        ms = float(kr['miktar_s'] or 0)
        mm = float(kr['miktar_m'] or 0)
        miktar_kg = _fmt_num(ml + ms + mm)

        # RF label
        rf_label: str | None = None
        if has_rf and has_rf_tbl:
            rf_kod = (kr['_rf_kod'] or '').strip() if '_rf_kod' in kr.keys() else ''
            rf_ad = (kr['_rf_ad'] or '').strip() if '_rf_ad' in kr.keys() else ''
            rf_durum = (kr['_rf_durum'] or '').strip() if '_rf_durum' in kr.keys() else ''
            if rf_kod and rf_durum and rf_durum != rf_kod:
                rf_label = f'{rf_kod} / {rf_durum}'
            elif rf_kod:
                rf_label = rf_kod
            elif rf_ad:
                rf_label = rf_ad

        # plan kodu
        plan_kodu: str | None = None
        if '_plan_kodu' in kr.keys():
            plan_kodu = kr['_plan_kodu'] or None

        kalem: dict[str, Any] = {
            'id': int(kr['id']),
            'sira_no': kr['sira_no'],
            'urun_ailesi': kr['urun_ailesi'] or '',
            'formul_id': kr['formul_id'],
            'formul_ad': kr['formul_ad'] or '',
            'renk_varyant_id': kr['renk_varyant_id'],
            'renk_ad': kr['renk_ad'] or '',
            'rf_renk_id': kr['rf_renk_id'] if has_rf else None,
            'rf_label': rf_label,
            'miktar_l': _fmt_num(ml),
            'miktar_s': _fmt_num(ms),
            'miktar_m': _fmt_num(mm),
            'miktar_kg': miktar_kg,
            'termin_tarihi': _fmt_dt(kr['termin_tarihi']),
            'uretim_plan_id': kr['uretim_plan_id'] if 'uretim_plan_id' in kcols else None,
            'plan_kodu': plan_kodu,
            'numune_talep_id': kr['numune_talep_id'] if 'numune_talep_id' in kcols else None,
            'durum': kr['durum'] or '',
            'mtt_kalem_id': kr['mtt_kalem_id'] if 'mtt_kalem_id' in kcols else None,
            'sevk_tarihi': (sevk_map.get(int(kr['id'])) or {}).get('sevk_tarihi'),
            'sevkiyat_id': (sevk_map.get(int(kr['id'])) or {}).get('sevkiyat_id'),
            'sevkiyat_no': (sevk_map.get(int(kr['id'])) or {}).get('sevkiyat_no'),
            'sevkiyat_count': (sevk_map.get(int(kr['id'])) or {}).get('sevkiyat_count', 0),
        }
        # Ticari alanlar — yetki korumalı
        if ticari_gorunur:
            kalem['birim_fiyat'] = _fmt_num(kr['birim_fiyat']) if 'birim_fiyat' in kcols else None
            kalem['iskonto_orani'] = _fmt_num(kr['iskonto_orani']) if 'iskonto_orani' in kcols else None
            kalem['net_birim_fiyat'] = _fmt_num(kr['net_birim_fiyat']) if 'net_birim_fiyat' in kcols else None
            kalem['satir_tutari'] = _fmt_num(kr['satir_tutari']) if 'satir_tutari' in kcols else None
            kalem['satir_tutari_try'] = _fmt_num(kr['satir_tutari_try']) if 'satir_tutari_try' in kcols else None

        result[sid].append(kalem)
    return result


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


def _rf_row_to_payload(
    r: sqlite3.Row | dict,
    *,
    baglanti_kaynagi: str,
    legacy_baglanti: bool = False,
) -> dict[str, Any]:
    """Canonical RF response card (FAZ-2D)."""
    d = dict(r) if not isinstance(r, dict) else r
    rid = int(d['id'])
    kod = (d.get('rf_kod') or '').strip() or None
    ad = (d.get('ad') or '').strip() or None
    label = f'{kod} — {ad}' if kod and ad and kod != ad else (kod or ad)
    return {
        'id': rid,
        'rf_renk_id': rid,
        'rf_kod': kod,
        'ad': ad,
        'rf_adi': ad,
        'rf_label': label,
        'durum': d.get('durum') or None,
        'rf_durum': d.get('durum') or None,
        'aktif': int(d.get('aktif') or 0),
        'rf_aktif': int(d.get('aktif') or 0),
        'rev_no': d.get('aktif_rev_no'),
        'aktif_rev_no': d.get('aktif_rev_no'),
        'kaynak_arge_test_id': (
            int(d['kaynak_arge_test_id'])
            if d.get('kaynak_arge_test_id') not in (None, '', 0)
            else None
        ),
        'ilk_talep_cari_id': (
            int(d['ilk_talep_cari_id'])
            if d.get('ilk_talep_cari_id') not in (None, '', 0)
            else None
        ),
        'cari_id': (
            int(d['cari_id']) if d.get('cari_id') not in (None, '', 0) else None
        ),
        'baglanti_kaynagi': baglanti_kaynagi,
        'legacy_baglanti': bool(legacy_baglanti),
        'pointer_uyumsuzlugu': False,
    }


def _rf_map_batch(con: sqlite3.Connection, rf_ids: set[int]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    ids = [i for i in rf_ids if i and i > 0]
    if not ids or not _tablo_var(con, 'nexgen_rf_renk'):
        return out
    ph = ','.join('?' * len(ids))
    cols = _kolonlar(con, 'nexgen_rf_renk')
    extra = ''
    for c in ('kaynak_arge_test_id', 'ilk_talep_cari_id', 'cari_id'):
        if c in cols:
            extra += f', {c}'
        else:
            extra += f', NULL AS {c}'
    for r in con.execute(
        f"""
        SELECT id, rf_kod, ad, durum, aktif, aktif_rev_no{extra}
        FROM nexgen_rf_renk WHERE id IN ({ph})
        """,
        ids,
    ):
        out[int(r['id'])] = _rf_row_to_payload(r, baglanti_kaynagi='RF_ID')
    return out


def _rf_by_kaynak_arge_batch(
    con: sqlite3.Connection,
    arge_ids: list[int],
    cari_id: int,
) -> dict[int, dict[str, Any]]:
    """arge_id → tek aktif RF (kaynak_arge_test_id). Multi → atla."""
    out: dict[int, dict[str, Any]] = {}
    aids = [i for i in arge_ids if i and i > 0]
    if not aids or not _tablo_var(con, 'nexgen_rf_renk'):
        return out
    cols = _kolonlar(con, 'nexgen_rf_renk')
    if 'kaynak_arge_test_id' not in cols:
        return out
    ph = ','.join('?' * len(aids))
    buckets: dict[int, list[sqlite3.Row]] = {}
    for r in con.execute(
        f"""
        SELECT id, rf_kod, ad, durum, aktif, aktif_rev_no,
               kaynak_arge_test_id, ilk_talep_cari_id, cari_id
        FROM nexgen_rf_renk
        WHERE COALESCE(aktif,1)=1 AND kaynak_arge_test_id IN ({ph})
        ORDER BY id
        """,
        aids,
    ):
        # leak: RF cari doluysa bu cari ile uyumlu olmalı
        if r['cari_id'] not in (None, 0) and int(r['cari_id']) != int(cari_id):
            continue
        kid = int(r['kaynak_arge_test_id'])
        buckets.setdefault(kid, []).append(r)
    for kid, rows in buckets.items():
        if len(rows) != 1:
            continue
        out[kid] = _rf_row_to_payload(
            rows[0], baglanti_kaynagi='RF_KAYNAK_ARGE_TEST_ID',
        )
    return out


def _formul_uygunluk_batch(
    con: sqlite3.Connection,
    rf_ids: set[int],
) -> dict[int, dict[str, Any]]:
    """rf_id → bagli_formuller / tekil_formul / formul_belirsiz (FAZ-2D)."""
    empty_tpl = {
        'bagli_formuller': [],
        'formul_sayisi': 0,
        'tekil_formul': None,
        'formul_belirsiz': False,
        'uygunluk_durumu': None,
    }
    out: dict[int, dict[str, Any]] = {i: dict(empty_tpl) for i in rf_ids if i}
    ids = [i for i in rf_ids if i and i > 0]
    if not ids:
        return out
    if not _tablo_var(con, 'nexgen_rf_formul_uygunluk') or not _tablo_var(con, 'nexgen_formul'):
        return out
    ph = ','.join('?' * len(ids))
    by_rf: dict[int, list[dict[str, Any]]] = {i: [] for i in ids}
    for r in con.execute(
        f"""
        SELECT u.id AS uygunluk_id, u.rf_renk_id, u.formul_id, u.durum AS uygunluk_durum,
               u.aktif AS uygunluk_aktif, u.kaynak_arge_test_id, u.ilk_talep_cari_id,
               f.kod AS formul_kod, f.ad AS formul_ad, f.aktif AS formul_aktif,
               f.durum AS formul_durum
        FROM nexgen_rf_formul_uygunluk u
        JOIN nexgen_formul f ON f.id = u.formul_id
        WHERE u.rf_renk_id IN ({ph}) AND COALESCE(u.aktif,1)=1
        ORDER BY u.id
        """,
        ids,
    ):
        rid = int(r['rf_renk_id'])
        fid = int(r['formul_id'])
        by_rf.setdefault(rid, []).append({
            'id': fid,
            'kod': (r['formul_kod'] or '').strip() or None,
            'ad': (r['formul_ad'] or '').strip() or None,
            'aktif': int(r['formul_aktif'] or 0),
            'durum': r['formul_durum'] or None,
            'uygunluk_id': int(r['uygunluk_id']),
            'uygunluk_durumu': r['uygunluk_durum'] or None,
            'uygunluk_aktif': int(r['uygunluk_aktif'] or 0),
            'kaynak_arge_test_id': (
                int(r['kaynak_arge_test_id'])
                if r['kaynak_arge_test_id'] not in (None, 0) else None
            ),
            'ilk_talep_cari_id': (
                int(r['ilk_talep_cari_id'])
                if r['ilk_talep_cari_id'] not in (None, 0) else None
            ),
            'baglanti_kaynagi': 'RF_FORMUL_UYGUNLUK',
            'pasif_formul': int(r['formul_aktif'] or 0) != 1,
        })
    for rid, flist in by_rf.items():
        n = len(flist)
        out[rid] = {
            'bagli_formuller': flist,
            'formul_sayisi': n,
            'tekil_formul': flist[0] if n == 1 else None,
            'formul_belirsiz': n > 1,
            'uygunluk_durumu': (flist[0].get('uygunluk_durumu') if n == 1 else None),
        }
    return out


def _rf_revizyon_batch(
    con: sqlite3.Connection,
    rf_ids: set[int],
) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {i: [] for i in rf_ids if i}
    ids = [i for i in rf_ids if i and i > 0]
    if not ids or not _tablo_var(con, 'nexgen_rf_revizyon'):
        return out
    ph = ','.join('?' * len(ids))
    cols = _kolonlar(con, 'nexgen_rf_revizyon')
    # esnek kolon seçimi
    sel = ['id', 'rf_renk_id', 'rev_no', 'durum', 'aktif']
    for c in ('formul_id', 'olusturma_tarihi', 'onay_tarihi', 'aciklama', 'kilitli_mi'):
        if c in cols:
            sel.append(c)
    for r in con.execute(
        f"""
        SELECT {', '.join(sel)}
        FROM nexgen_rf_revizyon
        WHERE rf_renk_id IN ({ph}) AND COALESCE(aktif,1)=1
        ORDER BY rf_renk_id, rev_no DESC, id DESC
        """,
        ids,
    ):
        rid = int(r['rf_renk_id'])
        item = {
            'id': int(r['id']),
            'rf_renk_id': rid,
            'rev_no': r['rev_no'],
            'durum': r['durum'] or None,
            'aktif': int(r['aktif'] or 0),
            'formul_id': (
                int(r['formul_id']) if 'formul_id' in r.keys() and r['formul_id'] not in (None, 0) else None
            ),
            'tarih': _fmt_dt(
                r['onay_tarihi'] if 'onay_tarihi' in r.keys() and r['onay_tarihi']
                else (r['olusturma_tarihi'] if 'olusturma_tarihi' in r.keys() else None)
            ),
            'aciklama': (
                (r['aciklama'] or None) if 'aciklama' in r.keys() else None
            ),
            'kilitli_mi': (
                int(r['kilitli_mi'] or 0) if 'kilitli_mi' in r.keys() else None
            ),
        }
        out.setdefault(rid, []).append(item)
    return out


def _attach_formul_rev(
    rf_payload: dict[str, Any] | None,
    formul_map: dict[int, dict[str, Any]],
    rev_map: dict[int, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    if not rf_payload:
        return None
    rid = int(rf_payload['id'])
    fm = formul_map.get(rid) or {
        'bagli_formuller': [], 'formul_sayisi': 0,
        'tekil_formul': None, 'formul_belirsiz': False, 'uygunluk_durumu': None,
    }
    revs = rev_map.get(rid) or []
    out = dict(rf_payload)
    out['bagli_formuller'] = fm['bagli_formuller']
    out['formul_sayisi'] = fm['formul_sayisi']
    out['tekil_formul'] = fm['tekil_formul']
    out['formul_belirsiz'] = fm['formul_belirsiz']
    out['uygunluk_durumu'] = fm.get('uygunluk_durumu')
    out['rf_revizyonlari'] = revs
    out['son_revizyon'] = revs[0] if revs else None
    return out


def _resolve_rf_bundle_for_numune(
    *,
    numune_rf_id: Any,
    arge_rf_id: Any,
    arge_id: Any,
    rf_map: dict[int, dict[str, Any]],
    rf_by_kaynak: dict[int, dict[str, Any]],
    formul_map: dict[int, dict[str, Any]],
    rev_map: dict[int, list[dict[str, Any]]],
    legacy_renk: str | None,
    legacy_formul: str | None,
) -> dict[str, Any]:
    """FAZ-2D RF resolve — mismatch'te tek sonuç seçilmez."""
    def _iid(v: Any) -> int | None:
        if v in (None, '', 0, '0'):
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    n_rf = _iid(numune_rf_id)
    a_rf = _iid(arge_rf_id)
    aid = _iid(arge_id)

    numune_rf = None
    if n_rf and n_rf in rf_map:
        numune_rf = _attach_formul_rev(
            {**rf_map[n_rf], 'baglanti_kaynagi': 'NUMUNE_RF_RENK_ID'},
            formul_map, rev_map,
        )
    arge_rf = None
    if a_rf and a_rf in rf_map:
        arge_rf = _attach_formul_rev(
            {**rf_map[a_rf], 'baglanti_kaynagi': 'ARGE_RF_RENK_ID'},
            formul_map, rev_map,
        )

    mismatch = bool(n_rf and a_rf and n_rf != a_rf)
    if mismatch:
        return {
            'aktif_rf': None,
            'numune_rf': numune_rf,
            'arge_rf': arge_rf,
            'bagli_formuller': [],
            'tekil_formul': None,
            'formul_belirsiz': False,
            'rf_revizyonlari': [],
            'pointer_uyumsuzlugu': True,
            'manuel_inceleme': True,
            'legacy_baglanti': False,
            'baglanti_kaynagi': None,
            'legacy_rf_text': None,
            'legacy_formul_text': None,
        }

    # öncelik: AR-GE → numune → kaynak reverse
    aktif = None
    kaynak = None
    if arge_rf:
        aktif = arge_rf
        kaynak = 'ARGE_RF_RENK_ID'
    elif numune_rf:
        aktif = numune_rf
        kaynak = 'NUMUNE_RF_RENK_ID'
    elif aid and aid in rf_by_kaynak:
        aktif = _attach_formul_rev(
            dict(rf_by_kaynak[aid]), formul_map, rev_map,
        )
        kaynak = 'RF_KAYNAK_ARGE_TEST_ID'

    if aktif:
        aktif = dict(aktif)
        aktif['baglanti_kaynagi'] = kaynak
        aktif['legacy_baglanti'] = False
        return {
            'aktif_rf': aktif,
            'numune_rf': numune_rf,
            'arge_rf': arge_rf or (aktif if kaynak == 'ARGE_RF_RENK_ID' else None),
            'bagli_formuller': aktif.get('bagli_formuller') or [],
            'tekil_formul': aktif.get('tekil_formul'),
            'formul_belirsiz': bool(aktif.get('formul_belirsiz')),
            'rf_revizyonlari': aktif.get('rf_revizyonlari') or [],
            'pointer_uyumsuzlugu': False,
            'manuel_inceleme': False,
            'legacy_baglanti': False,
            'baglanti_kaynagi': kaynak,
            'legacy_rf_text': None,
            'legacy_formul_text': None,
        }

    # legacy text — canonical yok
    has_leg = bool((legacy_renk or '').strip() or (legacy_formul or '').strip())
    return {
        'aktif_rf': None,
        'numune_rf': None,
        'arge_rf': None,
        'bagli_formuller': [],
        'tekil_formul': None,
        'formul_belirsiz': False,
        'rf_revizyonlari': [],
        'pointer_uyumsuzlugu': False,
        'manuel_inceleme': False,
        'legacy_baglanti': has_leg,
        'baglanti_kaynagi': 'LEGACY_TEXT' if has_leg else None,
        'legacy_rf_text': (legacy_renk or '').strip() or None,
        'legacy_formul_text': (legacy_formul or '').strip() or None,
    }


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
        'arge_kodu': (d.get('arge_kodu') or '').strip() or None,
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


def enrich_gorusmeler_zincir_flags(
    con: sqlite3.Connection,
    cari_id: int,
    liste: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """FAZ-3C: görüşme zincir alanları + gorusmeyi_yapan / cari_sorumlusu ayrımı."""
    cid = int(cari_id)
    root = classify_gorusme_root(cid)
    sm = resolve_tek_sorumlu(con, cid)
    cari_sorumlusu = sm.get('sorumlu')
    nt_ptrs = {
        int(d['numune_talep_id'])
        for d in liste
        if d.get('numune_talep_id') not in (None, '', 0)
    }
    nt_cari: dict[int, int | None] = {}
    if nt_ptrs and _tablo_var(con, 'nexgen_numune_talep'):
        ph = ','.join('?' * len(nt_ptrs))
        for r in con.execute(
            f'SELECT id, cari_id FROM nexgen_numune_talep WHERE id IN ({ph})',
            list(nt_ptrs),
        ):
            nt_cari[int(r['id'])] = int(r['cari_id']) if r['cari_id'] is not None else None
    for d in liste:
        d.update({
            'parent_type': root['parent_type'],
            'parent_id': root['parent_id'],
            'baslangic_tipi': root['baslangic_tipi'],
            'zincir_eksik': False,
            'zincir_uyarilari': [],
            'baglanti_kaynagi': root['baglanti_kaynagi'],
            'dogrudan_operasyon': False,
            'manuel_inceleme': False,
            'cari_sorumlusu': cari_sorumlusu,
            'sorumlu_uyarilari': sm.get('sorumlu_uyarilari') or [],
        })
        gy_id = d.get('kullanici_id') or d.get('olusturan_kullanici_id')
        gy_ad = (
            d.get('kullanici_adi') or d.get('olusturan_adi')
            or d.get('pazarlamaci') or d.get('talep_eden')
        )
        d['gorusmeyi_yapan'] = {
            'kullanici_id': int(gy_id) if gy_id not in (None, '', 0) else None,
            'ad_soyad': gy_ad,
        }
        uyarilar: list[str] = []
        for n in (d.get('bagli_numuneler') or []):
            if n.get('legacy_baglanti'):
                uyarilar.append('LEGACY_NUMUNE_BAGLANTI')
        nt_ptr = d.get('numune_talep_id')
        if nt_ptr not in (None, '', 0):
            nid = int(nt_ptr)
            if nid not in nt_cari:
                uyarilar.append('CHILD_NUMUNE_BULUNAMADI')
                d['zincir_eksik'] = True
                d['manuel_inceleme'] = True
            elif nt_cari[nid] is not None and nt_cari[nid] != cid:
                uyarilar.append('CHILD_NUMUNE_BASKA_CARI')
                d['zincir_eksik'] = True
                d['manuel_inceleme'] = True
        d['zincir_uyarilari'] = uyarilar
    return liste, sm


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
        'id, arge_kodu, test_no, durum, aktif, calisma_tipi, olusturma_tarihi, '
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

    # RF batch (+ kaynak reverse)
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
    arge_id_list = list(arge_by_id.keys())
    rf_by_kaynak = _rf_by_kaynak_arge_batch(con, arge_id_list, cid)
    for rp in rf_by_kaynak.values():
        rf_ids.add(int(rp['id']))
    rf_map = _rf_map_batch(con, rf_ids)
    formul_map = _formul_uygunluk_batch(con, rf_ids)
    rev_map = _rf_revizyon_batch(con, rf_ids)
    stats['q_rf'] = 1 if rf_ids else 0
    stats['q_formul'] = 1 if rf_ids else 0
    stats['q_revizyon'] = 1 if rf_ids else 0
    stats['q_rf_kaynak'] = 1 if arge_id_list else 0

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
            if rf_info is None and aid in rf_by_kaynak:
                rf_info = rf_by_kaynak[aid]
            rf_full = _attach_formul_rev(rf_info, formul_map, rev_map) if rf_info else None
            card = _arge_card(ad, baglanti_kaynagi=src, legacy=legacy, rf_info=rf_info)
            # FAZ-2D opsiyonel RF/formül alanları
            card['aktif_rf'] = rf_full
            card['bagli_formuller'] = (rf_full or {}).get('bagli_formuller') or []
            card['tekil_formul'] = (rf_full or {}).get('tekil_formul')
            card['formul_belirsiz'] = bool((rf_full or {}).get('formul_belirsiz'))
            card['rf_revizyonlari'] = (rf_full or {}).get('rf_revizyonlari') or []
            if rf_full is None and not legacy:
                leg_r = (ad.get('yeni_renk_adi') or ad.get('renk_kodu') or '').strip()
                leg_f = (ad.get('formul_grup_adi') or ad.get('ana_formul_grup_kodu') or '').strip()
                if leg_r or leg_f:
                    card['legacy_baglanti'] = True
                    card['baglanti_kaynagi_rf'] = 'LEGACY_TEXT'
                    card['legacy_rf_text'] = leg_r or None
                    card['legacy_formul_text'] = leg_f or None
            cards.append(card)
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

    return by_nt, aktif, {
        'stats': stats,
        'multi_flags': multi_flags,
        'rf_map': rf_map,
        'rf_by_kaynak': rf_by_kaynak,
        'formul_map': formul_map,
        'rev_map': rev_map,
    }


def load_cari360_numuneler(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None,
    *,
    limit: int = 50,
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    """Numune talepleri — yalnız nexgen_numune_talep.cari_id = nexgen_cari.id.

    cari_id NULL (ADAY) kayıtlar gelmez. RF: numune.rf → arge.rf → —.
    Pagination: page/page_size parametreleri kullanılır; limit parametre artık yok sayılır.
    """
    _assert_cari(con, cari_id, kullanici_id, yk)
    cid = int(cari_id)
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 10), 100))
    offset = (page - 1) * page_size
    limit = page_size  # backward compat için local limit

    empty = {
        'liste': [], 'count': 0,
        'page': page, 'page_size': page_size,
        'total_count': 0, 'total_pages': 0,
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
    vedat_sonuc_sel = ', vedat_sonuc' if 'vedat_sonuc' in ncols else ', NULL AS vedat_sonuc'
    vedat_miktar_sel = ', vedat_numune_miktari' if 'vedat_numune_miktari' in ncols else ', NULL AS vedat_numune_miktari'
    numune_adedi_sel = ', numune_adedi' if 'numune_adedi' in ncols else ', NULL AS numune_adedi'

    total_count = con.execute(
        'SELECT COUNT(*) FROM nexgen_numune_talep WHERE cari_id=? AND COALESCE(aktif, 1)=1',
        (cid,),
    ).fetchone()[0]
    import math as _math
    total_pages = max(1, _math.ceil(total_count / page_size)) if total_count > 0 else 0

    rows = con.execute(
        f"""
        SELECT id, talep_kodu, olusturma_tarihi, guncelleme_tarihi,
               urun_tipi, urun_adi, renk_kodu, yeni_renk_aciklama, renk_tipi,
               talep_nedeni, talep_kaynagi, karsilama_yolu, durum, aktif,
               rf_renk_id, arge_test_id, talep_eden_kullanici_id
               {mo_sel}{vedat_sonuc_sel}{vedat_miktar_sel}{numune_adedi_sel}
        FROM nexgen_numune_talep
        WHERE cari_id=? AND COALESCE(aktif, 1)=1
        ORDER BY COALESCE(guncelleme_tarihi, olusturma_tarihi, '') DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (cid, page_size, offset),
    ).fetchall()

    # Toplu AR-GE / RF / formül / revizyon (N+1 yok)
    arge_by_nt: dict[int, list[dict]] = {}
    aktif_by_nt: dict[int, dict | None] = {}
    multi_flags: dict[int, bool] = {}
    rf_map: dict[int, dict] = {}
    rf_by_kaynak: dict[int, dict] = {}
    formul_map: dict[int, dict] = {}
    rev_map: dict[int, list] = {}
    qstats: dict[str, Any] = {}
    if has_arge and rows:
        arge_by_nt, aktif_by_nt, meta = _batch_load_arge_for_numuneler(con, cid, list(rows))
        multi_flags = meta.get('multi_flags') or {}
        rf_map = meta.get('rf_map') or {}
        rf_by_kaynak = meta.get('rf_by_kaynak') or {}
        formul_map = meta.get('formul_map') or {}
        rev_map = meta.get('rev_map') or {}
        qstats = meta.get('stats') or {}
    elif rows:
        # AR-GE tablosu yoksa yine de numune RF master okunabilir
        rf_ids: set[int] = set()
        for r in rows:
            if r['rf_renk_id'] not in (None, ''):
                try:
                    rf_ids.add(int(r['rf_renk_id']))
                except (TypeError, ValueError):
                    pass
        rf_map = _rf_map_batch(con, rf_ids)
        formul_map = _formul_uygunluk_batch(con, rf_ids)
        rev_map = _rf_revizyon_batch(con, rf_ids)
        qstats = {'q_rf': 1 if rf_ids else 0, 'q_formul': 1 if rf_ids else 0, 'q_revizyon': 1 if rf_ids else 0}

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

    gorusme_by_id = load_gorusme_cari_map(
        con,
        {
            int(x['mo_gorusme_id'])
            for x in rows
            if x['mo_gorusme_id'] not in (None, '', 0)
        },
    )
    sorumlu_meta = resolve_tek_sorumlu(con, cid)

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

        arge_rf_id = (aktif_arge or {}).get('rf_renk_id') if aktif_arge else None
        # aktif_arge kartında nested aktif_rf varsa oradan da
        if arge_rf_id is None and aktif_arge and (aktif_arge.get('aktif_rf') or {}).get('id'):
            arge_rf_id = aktif_arge['aktif_rf']['id']
        leg_renk = None
        leg_formul = None
        if aktif_arge:
            leg_renk = (aktif_arge.get('yeni_renk_adi') or aktif_arge.get('renk_kodu') or '').strip() or None
            leg_formul = (
                aktif_arge.get('formul_grup_adi') or aktif_arge.get('ana_formul_grup_kodu') or ''
            ).strip() or None
        if not leg_renk:
            leg_renk = renk

        bundle = _resolve_rf_bundle_for_numune(
            numune_rf_id=r['rf_renk_id'],
            arge_rf_id=arge_rf_id,
            arge_id=(aktif_arge or {}).get('id') or r['arge_test_id'],
            rf_map=rf_map,
            rf_by_kaynak=rf_by_kaynak,
            formul_map=formul_map,
            rev_map=rev_map,
            legacy_renk=leg_renk,
            legacy_formul=leg_formul,
        )
        aktif_rf = bundle.get('aktif_rf')
        rf_id = (aktif_rf or {}).get('id') if aktif_rf else None
        if rf_id is None and not bundle.get('pointer_uyumsuzlugu'):
            # backward: eski tek id alanı
            if r['rf_renk_id'] not in (None, ''):
                try:
                    rf_id = int(r['rf_renk_id'])
                except (TypeError, ValueError):
                    rf_id = None
        rf_label = (aktif_rf or {}).get('rf_label')
        if not rf_label and rf_id and not bundle.get('pointer_uyumsuzlugu'):
            rf_label = (rf_map.get(int(rf_id)) or {}).get('rf_label')
        if bundle.get('pointer_uyumsuzlugu'):
            rf_label = None  # tek sonuç üretme
        rf_kaynak = None
        if bundle.get('baglanti_kaynagi') == 'ARGE_RF_RENK_ID':
            rf_kaynak = 'arge'
        elif bundle.get('baglanti_kaynagi') == 'NUMUNE_RF_RENK_ID':
            rf_kaynak = 'numune'
        elif bundle.get('baglanti_kaynagi'):
            rf_kaynak = bundle.get('baglanti_kaynagi')

        talep_eden = None
        if r['talep_eden_kullanici_id'] and int(r['talep_eden_kullanici_id']) in user_map:
            talep_eden = user_map[int(r['talep_eden_kullanici_id'])] or None

        bagli_siparisler = siparis_by_nt.get(tid, [])

        rel = classify_mo_gorusme_parent(
            r['mo_gorusme_id'], cid, gorusme_by_id, kind='NUMUNE',
        )
        manuel = bool(bundle.get('manuel_inceleme') or rel['manuel_inceleme'])
        zincir_uy = list(rel['zincir_uyarilari'])
        if bundle.get('pointer_uyumsuzlugu'):
            zincir_uy.append('RF_POINTER_UYUSMAZLIGI')
            manuel = True

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
            'rf_kod': (aktif_rf or {}).get('rf_kod'),
            'formul_grup_adi': (aktif_arge or {}).get('formul_grup_adi') or None,
            'ana_formul_grup_kodu': (aktif_arge or {}).get('ana_formul_grup_kodu') or None,
            'durum': r['durum'] or None,
            'vedat_sonuc': r['vedat_sonuc'] or None,
            'vedat_numune_miktari': r['vedat_numune_miktari'] or None,
            'numune_adedi': r['numune_adedi'] if r['numune_adedi'] not in (None, 0, '') else None,
            'son_guncelleme': _fmt_dt(r['guncelleme_tarihi'] or r['olusturma_tarihi']),
            'mo_gorusme_id': int(r['mo_gorusme_id']) if r['mo_gorusme_id'] not in (None, 0, '') else None,
            'arge_test_id': int(r['arge_test_id']) if r['arge_test_id'] not in (None, 0, '') else None,
            'bagli_arge_testleri': bagli_arge,
            'aktif_arge_testi': aktif_arge,
            'legacy_multi_manuel': bool(multi_flags.get(tid)),
            # FAZ-2D opsiyonel alanlar
            'aktif_rf': aktif_rf,
            'numune_rf': bundle.get('numune_rf'),
            'arge_rf': bundle.get('arge_rf'),
            'bagli_formuller': bundle.get('bagli_formuller') or [],
            'tekil_formul': bundle.get('tekil_formul'),
            'formul_belirsiz': bool(bundle.get('formul_belirsiz')),
            'rf_revizyonlari': bundle.get('rf_revizyonlari') or [],
            'pointer_uyumsuzlugu': bool(bundle.get('pointer_uyumsuzlugu')),
            'manuel_inceleme': manuel,
            'legacy_baglanti': bool(bundle.get('legacy_baglanti')),
            'baglanti_kaynagi': rel.get('baglanti_kaynagi') or bundle.get('baglanti_kaynagi'),
            'legacy_rf_text': bundle.get('legacy_rf_text'),
            'legacy_formul_text': bundle.get('legacy_formul_text'),
            'bagli_siparis_sayisi': len(bagli_siparisler),
            'bagli_siparisler': bagli_siparisler,
            'detay_url': f'/nexgen/numune-talep?id={tid}',
            # FAZ-3C zincir
            'parent_type': rel['parent_type'],
            'parent_id': rel['parent_id'],
            'baslangic_tipi': rel['baslangic_tipi'],
            'zincir_eksik': bool(rel['zincir_eksik'] or bundle.get('pointer_uyumsuzlugu')),
            'zincir_uyarilari': zincir_uy,
            'dogrudan_operasyon': rel['dogrudan_operasyon'],
        })

    out = {
        'liste': liste,
        'count': ozet['toplam'],
        'page': page,
        'page_size': page_size,
        'total_count': total_count,
        'total_pages': total_pages,
        'ozet': ozet,
        'sorumlu': sorumlu_meta.get('sorumlu'),
        'sorumlu_uyarilari': sorumlu_meta.get('sorumlu_uyarilari') or [],
        'sorumlu_atanmamis': bool(sorumlu_meta.get('sorumlu_atanmamis')),
    }
    if qstats:
        out['query_stats'] = qstats
    return out


def _uretim_uretilen_kg(con: sqlite3.Connection, plan_id: int, has_rfk: bool, has_parca: bool) -> float:
    """Canonical üretilen KG: önce nexgen_rf_kullanim (siparis_id=plan.id), sonra parca SUM."""
    if has_rfk:
        row = con.execute(
            'SELECT COALESCE(SUM(miktar_kg),0) FROM nexgen_rf_kullanim WHERE siparis_id=? AND aktif=1',
            (plan_id,),
        ).fetchone()
        kg = float(row[0] or 0)
        if kg > 0.001:
            return kg
    if has_parca:
        row = con.execute(
            'SELECT COALESCE(SUM(uretilen_kg),0) FROM nexgen_uretim_parca WHERE plan_id=?',
            (plan_id,),
        ).fetchone()
        return float(row[0] or 0)
    return 0.0


def load_cari360_uretim(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None,
    *,
    page: int = 1,
    page_size: int = 20,
    durum_filtre: str | None = None,
) -> dict[str, Any]:
    """Üretim planı — cari_id üzerinden read-only. Pagination + formül/renk/ürün detayı."""
    _assert_cari(con, cari_id, kullanici_id, yk)
    cid = int(cari_id)
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 100))
    offset = (page - 1) * page_size

    if not _tablo_var(con, 'nexgen_uretim_plan'):
        return {
            'liste': [], 'count': 0,
            'page': page, 'page_size': page_size, 'total_count': 0, 'total_pages': 0,
        }

    has_batch = _tablo_var(con, 'nexgen_uretim_batch')
    has_parca = _tablo_var(con, 'nexgen_uretim_parca')
    has_sip = _tablo_var(con, 'nexgen_planlama_siparis')
    has_kalem = _tablo_var(con, 'nexgen_planlama_siparis_kalem')
    has_formul = _tablo_var(con, 'nexgen_formul')
    has_rfk = _tablo_var(con, 'nexgen_rf_kullanim')

    # Durum filtresi
    durum_exclude = ('IPTAL',)
    extra_where = ''
    extra_params: list[Any] = []
    if durum_filtre:
        allowed = [d.strip().upper() for d in durum_filtre.split(',') if d.strip()]
        if allowed:
            ph = ','.join('?' * len(allowed))
            extra_where = f' AND durum IN ({ph})'
            extra_params = allowed

    where_base = f"cari_id=? AND COALESCE(durum,'') NOT IN ('IPTAL'){extra_where}"
    base_params: list[Any] = [cid] + extra_params

    total_count = int(con.execute(
        f'SELECT COUNT(*) FROM nexgen_uretim_plan WHERE {where_base}',
        base_params,
    ).fetchone()[0])
    total_pages = max(1, (total_count + page_size - 1) // page_size) if total_count else 0

    rows = con.execute(
        f"""
        SELECT id, plan_kodu, durum, planlanan_kg, planlama_siparis_id,
               siparis_no, rf_renk_id, renk_kodu, created_at, plan_tarihi,
               termin_tarihi, ana_formul_kodu, kalip_carpani, uretim_varyant_id
        FROM nexgen_uretim_plan
        WHERE {where_base}
        ORDER BY COALESCE(plan_tarihi, created_at, '') DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        base_params + [page_size, offset],
    ).fetchall()

    sip_ids = {
        int(r['planlama_siparis_id'])
        for r in rows
        if r['planlama_siparis_id'] not in (None, '', 0)
    }
    sip_cari_map = load_siparis_cari_map(con, sip_ids)
    sorumlu_meta = resolve_tek_sorumlu(con, cid)

    liste: list[dict[str, Any]] = []
    for r in rows:
        pid = int(r['id'])
        sid = r['planlama_siparis_id']
        siparis_no = r['siparis_no'] or ''
        siparis_durum = None
        termin_tarihi_sip = None

        if sid and has_sip:
            srow = con.execute(
                'SELECT siparis_no, durum, termin_tarihi FROM nexgen_planlama_siparis WHERE id=?',
                (int(sid),),
            ).fetchone()
            if srow:
                siparis_no = siparis_no or srow['siparis_no'] or ''
                siparis_durum = srow['durum']
                termin_tarihi_sip = _fmt_dt(srow['termin_tarihi'])

        # Sipariş kalemi: formül, renk, ürün
        kalem_bagli = False
        kalem_id = None
        siparis_formul_id = None
        siparis_formul_kodu = None
        siparis_formul_ad = None
        siparis_rf_renk_id = None
        siparis_renk_ad = None
        urun_ailesi = None

        if has_kalem:
            krow = con.execute(
                """
                SELECT id, formul_id, formul_ad, rf_renk_id, renk_ad, urun_ailesi
                FROM nexgen_planlama_siparis_kalem
                WHERE uretim_plan_id=? LIMIT 1
                """,
                (pid,),
            ).fetchone()
            if krow:
                kalem_bagli = True
                kalem_id = int(krow['id'])
                siparis_formul_id = krow['formul_id']
                siparis_formul_ad = krow['formul_ad'] or ''
                siparis_rf_renk_id = krow['rf_renk_id']
                siparis_renk_ad = krow['renk_ad'] or ''
                urun_ailesi = krow['urun_ailesi'] or ''
                if siparis_formul_id and has_formul and not siparis_formul_ad:
                    frow = con.execute(
                        'SELECT kod, ad FROM nexgen_formul WHERE id=?',
                        (int(siparis_formul_id),),
                    ).fetchone()
                    if frow:
                        siparis_formul_kodu = frow['kod'] or ''
                        siparis_formul_ad = frow['ad'] or siparis_formul_ad
                elif siparis_formul_id and has_formul:
                    frow = con.execute(
                        'SELECT kod FROM nexgen_formul WHERE id=?',
                        (int(siparis_formul_id),),
                    ).fetchone()
                    if frow:
                        siparis_formul_kodu = frow['kod'] or ''

        # Üretim formülü (plan.ana_formul_kodu)
        plan_formul_kodu = (r['ana_formul_kodu'] or '').strip()
        formul_ad = siparis_formul_ad or ''
        if plan_formul_kodu and has_formul and not formul_ad:
            frow2 = con.execute(
                'SELECT ad FROM nexgen_formul WHERE kod=? LIMIT 1',
                (plan_formul_kodu,),
            ).fetchone()
            if frow2:
                formul_ad = frow2['ad'] or ''

        formul_farkli = bool(
            siparis_formul_kodu and plan_formul_kodu
            and siparis_formul_kodu.upper() != plan_formul_kodu.upper()
        )
        renk_farkli = bool(
            siparis_rf_renk_id and r['rf_renk_id']
            and int(siparis_rf_renk_id) != int(r['rf_renk_id'])
        )

        # Batch
        batch_sayisi = 0
        batch_kodlari: list[str] = []
        batch_durum_ozet: dict[str, int] = {}
        if has_batch:
            brows = con.execute(
                'SELECT id, batch_kodu, durum FROM nexgen_uretim_batch WHERE plan_id=? ORDER BY id',
                (pid,),
            ).fetchall()
            batch_sayisi = len(brows)
            batch_kodlari = [(b['batch_kodu'] or f"#{b['id']}") for b in brows[:5]]
            for b in brows:
                bd = (b['durum'] or 'HAZIR').upper()
                batch_durum_ozet[bd] = batch_durum_ozet.get(bd, 0) + 1

        # Parça
        alt_emir_sayisi = 0
        hedef_kg_parca = 0.0
        parcalar_ozet: dict[str, int] = {}
        if has_parca:
            pr = con.execute(
                """
                SELECT COUNT(*) AS n, COALESCE(SUM(hedef_kg),0) AS hedef,
                       durum
                FROM nexgen_uretim_parca
                WHERE plan_id=?
                GROUP BY durum
                """,
                (pid,),
            ).fetchall()
            for pr_row in pr:
                alt_emir_sayisi += int(pr_row['n'] or 0)
                hedef_kg_parca += float(pr_row['hedef'] or 0)
                pd_key = (pr_row['durum'] or 'HAZIR').upper()
                parcalar_ozet[pd_key] = parcalar_ozet.get(pd_key, 0) + int(pr_row['n'] or 0)

        # Hedef KG: parça SUM varsa o, yoksa plan.planlanan_kg
        hedef_kg_val = hedef_kg_parca if hedef_kg_parca > 0.001 else float(r['planlanan_kg'] or 0)

        # Üretilen KG — canonical helper
        uretilen_kg_val = _uretim_uretilen_kg(con, pid, has_rfk, has_parca)

        kalan_kg_val = max(hedef_kg_val - uretilen_kg_val, 0.0)
        tamamlanma = 0
        if hedef_kg_val > 0:
            tamamlanma = min(round(uretilen_kg_val / hedef_kg_val * 100), 100)

        rel = classify_siparis_parent(
            sid, cid, sip_cari_map, null_tipi='LEGACY_URETIM',
        )

        liste.append({
            'id': pid,
            'plan_kodu': r['plan_kodu'] or '',
            'durum': r['durum'] or '',
            'siparis_id': int(sid) if sid else None,
            'siparis_no': siparis_no,
            'siparis_durum': siparis_durum,
            'siparis_url': f'/nexgen/pazarlama?siparis={int(sid)}' if sid else None,
            'plan_url': f'/nexgen/uretim-emirleri?vurgu={pid}',
            'plan_tarihi': _fmt_dt(r['plan_tarihi'] or r['created_at']),
            'termin_tarihi': r['termin_tarihi'] and _fmt_dt(r['termin_tarihi']) or termin_tarihi_sip,
            'urun': urun_ailesi or '',
            'urun_ailesi': urun_ailesi or '',
            'formul_kodu': plan_formul_kodu or siparis_formul_kodu or '',
            'formul_ad': formul_ad,
            'siparis_formul_kodu': siparis_formul_kodu or '',
            'siparis_formul_ad': siparis_formul_ad or '',
            'formul_farkli': formul_farkli,
            'rf_renk_id': r['rf_renk_id'],
            'renk_kodu': r['renk_kodu'] or '',
            'renk_ad': siparis_renk_ad or '',
            'siparis_rf_renk_id': siparis_rf_renk_id,
            'renk_farkli': renk_farkli,
            'kalip_carpani': r['kalip_carpani'],
            'hedef_kg': _fmt_num(hedef_kg_val),
            'uretilen_kg': _fmt_num(uretilen_kg_val),
            'kalan_kg': _fmt_num(kalan_kg_val),
            'tamamlanma_yuzdesi': tamamlanma,
            'planlanan_kg': _fmt_num(r['planlanan_kg']),
            'kalem_bagli': kalem_bagli,
            'kalem_id': kalem_id,
            'batch_sayisi': batch_sayisi,
            'batch_kodlari': batch_kodlari,
            'batch_durum_ozet': batch_durum_ozet,
            'alt_emir_sayisi': alt_emir_sayisi,
            'parcalar_ozet': parcalar_ozet,
            'zincir_eksik': rel['zincir_eksik'],
            'zincir_uyarilari': rel['zincir_uyarilari'],
        })

    return {
        'liste': liste,
        'count': len(liste),
        'page': page,
        'page_size': page_size,
        'total_count': total_count,
        'total_pages': total_pages,
        'sorumlu': sorumlu_meta.get('sorumlu'),
        'sorumlu_uyarilari': sorumlu_meta.get('sorumlu_uyarilari') or [],
        'sorumlu_atanmamis': bool(sorumlu_meta.get('sorumlu_atanmamis')),
    }


def load_cari360_onaylar(
    con,
    cari_id: int,
    kullanici_id: int,
    yk,
    *,
    limit: int = 50,
    offset: int = 0,
    durum_filtre: str | None = None,
):
    """Onay Merkezi kayitlari - read-only, cari_id filtreli.
    Kaynak: onay_talep + onay_talep_adim.
    Write yapilmaz. Satir no, filtre, pagination, ozet destekler.
    """
    def _tv(n):
        return bool(con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (n,)
        ).fetchone())

    cid = int(cari_id)
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))

    row = con.execute("SELECT id FROM nexgen_cari WHERE id=?", (cid,)).fetchone()
    if not row:
        raise ValueError(f"Cari bulunamadi: {cid}")

    if not _tv("onay_talep"):
        return {"liste": [], "count": 0, "toplam": 0, "has_more": False,
                "ozet": {"bekleyen": 0, "onaylandi": 0, "reddedildi": 0}}

    has_adim = _tv("onay_talep_adim")

    # Ozet sayimlar — aktif filtresi YOK, tüm geçmiş görünsün
    ozet_rows = con.execute(
        "SELECT durum, COUNT(*) AS n FROM onay_talep WHERE cari_id=? GROUP BY durum",
        (cid,),
    ).fetchall()
    ozet: dict[str, int] = {"bekleyen": 0, "onaylandi": 0, "reddedildi": 0}
    for oz in ozet_rows:
        d = (oz["durum"] or "").upper()
        if d in ("BEKLIYOR", "BEKLETILDI"):
            ozet["bekleyen"] += int(oz["n"] or 0)
        elif d == "ONAYLANDI":
            ozet["onaylandi"] += int(oz["n"] or 0)
        elif d in ("REDDEDILDI", "REVIZYON"):
            ozet["reddedildi"] += int(oz["n"] or 0)

    # Filtreli liste — aktif filtresi YOK, tüm durum geçmişi listelenir
    base_where = "cari_id=?"
    params: list = [cid]
    if durum_filtre and durum_filtre.upper() != "TUMU":
        df = durum_filtre.upper()
        if df == "BEKLIYOR":
            base_where += " AND durum IN ('BEKLIYOR','BEKLETILDI')"
        else:
            base_where += " AND durum=?"
            params.append(df)

    toplam_row = con.execute(
        f"SELECT COUNT(*) AS n FROM onay_talep WHERE {base_where}", params
    ).fetchone()
    toplam = int(toplam_row["n"] or 0) if toplam_row else 0

    list_where = base_where.replace("cari_id=?", "t.cari_id=?").replace(" AND durum", " AND t.durum")
    karar_join = ""
    order_by = "ORDER BY COALESCE(t.talep_tarihi, t.created_at) DESC, t.id DESC"
    if has_adim:
        karar_join = """
        LEFT JOIN (
            SELECT talep_id, MAX(tarih) AS karar_zaman
            FROM onay_talep_adim
            WHERE durum IN ('TAMAMLANDI','ONAYLANDI','REDDEDILDI','REVIZYON')
            GROUP BY talep_id
        ) _kz ON _kz.talep_id = t.id"""
        order_by = """
        ORDER BY
          CASE WHEN t.durum IN ('BEKLIYOR','BEKLETILDI')
               THEN COALESCE(t.talep_tarihi, t.created_at)
               ELSE COALESCE(_kz.karar_zaman, t.updated_at, t.talep_tarihi, t.created_at)
          END DESC,
          t.id DESC"""

    sql = (
        f"SELECT t.id, t.talep_kod, t.talep_tipi, t.kaynak_modul, t.kaynak_id, t.kaynak_kod, "
        f"t.durum, t.tutar, t.para_birimi, t.vade_gun, t.talep_tarihi, t.created_at, t.updated_at "
        f"FROM onay_talep t{karar_join} WHERE {list_where} {order_by} LIMIT ? OFFSET ?"
    )
    rows = con.execute(sql, params + [limit, offset]).fetchall()

    talep_ids = [int(r["id"]) for r in rows]
    # karar_map: talep_id -> {notu, veren, tarihi}
    karar_map: dict[int, dict] = {}
    if has_adim and talep_ids:
        ph = ",".join("?" * len(talep_ids))
        # Hangi kolonlar mevcut? kullanici_ad_snapshot yoksa boş döner
        adim_cols = [c[1] for c in con.execute(
            "PRAGMA table_info(onay_talep_adim)"
        ).fetchall()]
        veren_col = "kullanici_ad_snapshot" if "kullanici_ad_snapshot" in adim_cols else "''"
        # tarih: gerçek karar zamanı; created_at kullanılmaz
        tarih_col = "tarih" if "tarih" in adim_cols else ("updated_at" if "updated_at" in adim_cols else "created_at")
        adim_sql = (
            f"SELECT talep_id, karar_notu, {veren_col} AS karar_veren, "
            f"{tarih_col} AS karar_tarihi "
            f"FROM onay_talep_adim "
            f"WHERE talep_id IN ({ph}) "
            f"AND durum IN ('REVIZYON','REDDEDILDI','TAMAMLANDI','ONAYLANDI') "
            f"ORDER BY id DESC"
        )
        for a in con.execute(adim_sql, talep_ids).fetchall():
            tid = int(a["talep_id"])
            if tid not in karar_map:
                _kt = str(a["karar_tarihi"] or "")
                # Tarih+saat göster ([:16] → "YYYY-MM-DD HH:MM"); [:10] yasak
                karar_map[tid] = {
                    "notu": a["karar_notu"] or "",
                    "veren": a["karar_veren"] or "",
                    "tarihi": _kt[:16] if _kt else "",
                }

    _TIP = {
        "SATIS_SIPARISI": "Satis Siparisi",
        "NUMUNE_TALEBI": "Numune",
        "TAHSILAT_KAYDI": "Tahsilat",
        "SATIN_ALMA_SIPARISI": "Satin Alma",
    }
    _RENK = {
        "ONAYLANDI": "yesil", "REDDEDILDI": "kirmizi",
        "REVIZYON": "sari", "BEKLIYOR": "mavi", "BEKLETILDI": "gri",
    }

    liste = []
    for sira, r in enumerate(rows, start=offset + 1):
        tid = int(r["id"])
        durum = (r["durum"] or "").upper()
        try:
            tutar_fmt = str(round(float(r["tutar"]), 2)) if r["tutar"] not in (None, "") else None
        except (TypeError, ValueError):
            tutar_fmt = None
        tarih = str(r["talep_tarihi"] or r["created_at"] or "")[:16]
        liste.append({
            "sira": sira,
            "id": tid,
            "talep_kod": r["talep_kod"] or "",
            "talep_tipi": r["talep_tipi"] or "",
            "talep_tipi_etiket": _TIP.get(r["talep_tipi"] or "", r["talep_tipi"] or ""),
            "kaynak_modul": r["kaynak_modul"] or "",
            "kaynak_id": r["kaynak_id"],
            "kaynak_kod": r["kaynak_kod"] or "",
            "durum": durum,
            "durum_renk": _RENK.get(durum, "gri"),
            "tutar": tutar_fmt,
            "para_birimi": r["para_birimi"] or "",
            "vade_gun": r["vade_gun"],
            "talep_tarihi": tarih,
            "son_karar_notu": (karar_map.get(tid) or {}).get("notu") or "",
            "karar_veren": (karar_map.get(tid) or {}).get("veren") or "",
            "karar_tarihi": (karar_map.get(tid) or {}).get("tarihi") or "",
            "detay_url": "/nexgen/onay-merkezi",
        })

    # MTT Yönetim Onayları (nexgen_onay) — Cari360 federasyonu
    # nexgen_onay.cari_id yok; nexgen_musteri_temsilcisi_talep.cari_id üzerinden filtrele
    if _tv("nexgen_onay") and _tv("nexgen_musteri_temsilcisi_talep"):
        _MTIP = {
            "SIPARIS_TALEBI_ONAY": "Sipariş Talebi",
            "NUMUNE_TALEBI_ONAY": "Numune Talebi",
        }
        _MRENK = {
            "ONAYLANDI": "yesil", "REDDEDILDI": "kirmizi", "ONAY_BEKLIYOR": "mavi",
        }
        # Ozet sayaçlarına MTT bekleyenleri ekle
        mtt_bek = con.execute(
            """SELECT COUNT(*) AS n FROM nexgen_onay o
               JOIN nexgen_musteri_temsilcisi_talep m ON m.id=o.kaynak_id
               WHERE o.kaynak_turu='MUSTERI_TEMSILCISI_TALEP'
                 AND o.durum='ONAY_BEKLIYOR'
                 AND m.cari_id=?""",
            (cid,),
        ).fetchone()
        if mtt_bek:
            ozet["bekleyen"] += int(mtt_bek["n"] or 0)
        mtt_on = con.execute(
            """SELECT COUNT(*) AS n FROM nexgen_onay o
               JOIN nexgen_musteri_temsilcisi_talep m ON m.id=o.kaynak_id
               WHERE o.kaynak_turu='MUSTERI_TEMSILCISI_TALEP'
                 AND o.durum='ONAYLANDI'
                 AND m.cari_id=?""",
            (cid,),
        ).fetchone()
        if mtt_on:
            ozet["onaylandi"] += int(mtt_on["n"] or 0)
        mtt_red = con.execute(
            """SELECT COUNT(*) AS n FROM nexgen_onay o
               JOIN nexgen_musteri_temsilcisi_talep m ON m.id=o.kaynak_id
               WHERE o.kaynak_turu='MUSTERI_TEMSILCISI_TALEP'
                 AND o.durum='REDDEDILDI'
                 AND m.cari_id=?""",
            (cid,),
        ).fetchone()
        if mtt_red:
            ozet["reddedildi"] += int(mtt_red["n"] or 0)

        # Durum filtresi uygula
        mtt_durum_where = ""
        mtt_params: list = [cid]
        if durum_filtre and durum_filtre.upper() != "TUMU":
            df = durum_filtre.upper()
            if df == "BEKLIYOR":
                mtt_durum_where = "AND o.durum='ONAY_BEKLIYOR'"
            elif df == "ONAYLANDI":
                mtt_durum_where = "AND o.durum='ONAYLANDI'"
            elif df == "REDDEDILDI":
                mtt_durum_where = "AND o.durum='REDDEDILDI'"
            else:
                mtt_durum_where = "AND 1=0"  # diğer filtreler MTT'yi kapsamaz

        mtt_rows = con.execute(
            f"""SELECT o.id, o.onay_no, o.onay_turu, o.durum,
                       o.aciklama, o.karar_tarihi, o.red_nedeni, o.created_at,
                       sk_on.KullaniciAdi AS karar_veren,
                       m.id AS mtt_id, m.talep_no, m.talep_turu, m.cari_id,
                       m.durum AS mtt_durum,
                       m.isleme_alinma_tarihi, m.donusturulme_tarihi,
                       m.donusturulen_siparis_id, m.donusturulen_numune_talep_id,
                       m.gorusme_id
                FROM nexgen_onay o
                JOIN nexgen_musteri_temsilcisi_talep m ON m.id=o.kaynak_id
                LEFT JOIN sistem_kullanici sk_on ON sk_on.Id=o.onaylayan_kullanici_id
                WHERE o.kaynak_turu='MUSTERI_TEMSILCISI_TALEP'
                  AND m.cari_id=?
                  {mtt_durum_where}
                ORDER BY COALESCE(o.karar_tarihi, o.created_at) DESC""",
            mtt_params,
        ).fetchall()

        # MTT yaşam döngüsü etiketleri
        _MTT_ISLEM_LBL = {
            'ONAY_BEKLIYOR': 'Onay Bekliyor',
            'YENI': "Mehmet'e Aktarıldı",
            'ISLEME_ALINDI': 'Mehmet İşleme Aldı',
            'SIPARISE_DONUSTU': 'Siparişe Dönüştü',
            'NUMUNEYE_DONUSTU': 'Numuneye Dönüştü',
            'KISMEN_NUMUNEYE_DONUSTU': 'Kısmen Numuneye Dönüştü',
            'REDDEDILDI': 'Reddedildi',
            'IPTAL': 'İptal',
            'EKSIK_BILGI': 'Eksik Bilgi',
        }

        # Dönüşüm kodlarını toplu çek (N+1'den kaçın)
        sip_ids = [int(r['donusturulen_siparis_id']) for r in mtt_rows
                   if r['donusturulen_siparis_id']]
        num_ids = [int(r['donusturulen_numune_talep_id']) for r in mtt_rows
                   if r['donusturulen_numune_talep_id']]
        sip_kod_map: dict[int, str] = {}
        num_kod_map: dict[int, str] = {}
        if sip_ids and _tv("nexgen_planlama_siparis"):
            ph_s = ','.join('?' * len(sip_ids))
            for sr in con.execute(
                f"SELECT id, siparis_no FROM nexgen_planlama_siparis WHERE id IN ({ph_s})",
                sip_ids,
            ).fetchall():
                sip_kod_map[int(sr['id'])] = sr['siparis_no'] or ''
        if num_ids and _tv("nexgen_numune_talep"):
            ph_n = ','.join('?' * len(num_ids))
            for nr in con.execute(
                f"SELECT id, talep_kodu FROM nexgen_numune_talep WHERE id IN ({ph_n})",
                num_ids,
            ).fetchall():
                num_kod_map[int(nr['id'])] = nr['talep_kodu'] or ''

        for mrow in mtt_rows:
            m = dict(mrow)
            ot_durum_raw = (m.get("durum") or "").upper()
            mtt_durum_val = (m.get("mtt_durum") or "").upper()
            # Cari360 onay durum normalleştirmesi: ONAY_BEKLIYOR → BEKLIYOR
            durum_norm = "BEKLIYOR" if ot_durum_raw == "ONAY_BEKLIYOR" else ot_durum_raw
            kt = str(m.get("karar_tarihi") or "")
            talep_t = str(m.get("created_at") or "")[:16]
            # Dönüşüm bilgileri
            sip_id = m.get("donusturulen_siparis_id")
            num_id = m.get("donusturulen_numune_talep_id")
            donusum_kodu = ""
            if sip_id and int(sip_id) in sip_kod_map:
                donusum_kodu = sip_kod_map[int(sip_id)]
            elif num_id and int(num_id) in num_kod_map:
                donusum_kodu = num_kod_map[int(num_id)]
            # İşlem durumu etiketi (MTT tarafının son durumu)
            islem_durumu_etiket = _MTT_ISLEM_LBL.get(mtt_durum_val, mtt_durum_val)
            # Canonical zaman: dönüşüm > işleme alınma > karar > oluşturma
            donusturulme = str(m.get("donusturulme_tarihi") or "")
            isleme_alinma = str(m.get("isleme_alinma_tarihi") or "")
            liste.append({
                "sira": None,
                "id": int(m["id"]),
                "talep_kod": m.get("onay_no") or f"MTT-{m['id']}",
                "talep_tipi": m.get("onay_turu") or "",
                "talep_tipi_etiket": _MTIP.get(m.get("onay_turu") or "", "MTT Onayı"),
                "kaynak_modul": "nexgen_onay",
                "kaynak_id": m["id"],
                "kaynak_kod": m.get("talep_no") or "",
                "durum": durum_norm,
                "durum_renk": _MRENK.get(ot_durum_raw, "gri"),
                "tutar": None,
                "para_birimi": "",
                "vade_gun": None,
                "talep_tarihi": talep_t,
                "son_karar_notu": m.get("red_nedeni") or m.get("aciklama") or "",
                "karar_veren": m.get("karar_veren") or "",
                "karar_tarihi": kt[:16] if kt else "",
                "detay_url": "/nexgen/onay-merkezi",
                "kaynak_etiket": "Müşteri Operasyonu",
                # MTT yaşam döngüsü alanları
                "mtt_id": int(m.get("mtt_id") or m["id"]),
                "mtt_kod": m.get("talep_no") or "",
                "mtt_tipi": m.get("talep_turu") or "",
                "mtt_durum": mtt_durum_val,
                "mtt_durum_etiket": islem_durumu_etiket,
                "islem_durumu": mtt_durum_val,
                "islem_durumu_etiket": islem_durumu_etiket,
                "gorusme_id": m.get("gorusme_id"),
                "donusturulen_siparis_id": sip_id,
                "donusturulen_numune_talep_id": num_id,
                "donusum_kodu": donusum_kodu,
                "isleme_alinma_tarihi": isleme_alinma[:16] if isleme_alinma else "",
                "donusturulme_tarihi": donusturulme[:16] if donusturulme else "",
            })

        # Sıra numaralarını güncelle (tüm liste birleşince)
        liste.sort(
            key=lambda x: (x.get("karar_tarihi") or x.get("talep_tarihi") or ""),
            reverse=True,
        )
        for idx, item in enumerate(liste, start=offset + 1):
            item["sira"] = idx

    return {
        "liste": liste,
        "count": len(liste),
        "toplam": toplam,
        "has_more": (offset + limit) < toplam,
        "offset": offset,
        "limit": limit,
        "ozet": ozet,
        "bekleyen": ozet["bekleyen"],
    }
