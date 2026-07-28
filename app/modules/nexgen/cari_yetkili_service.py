# -*- coding: utf-8 -*-
"""
cari_yetkili_service.py
=======================
FAZ-CARI-YETKILI-MODEL-1

Müşteri tarafı yetkili kişiler (nexgen_cari altında).
cari_sorumlu (iç pazarlamacı) ile karıştırılmaz.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from modules.nexgen.cari360_yetki import (
    can_cari360_crm_write,
    can_cari360_view_all,
)
from modules.nexgen.cari_sorumlu_service import (
    can_view_cari,
    can_write_crm,
    load_kullanici_yetkileri,
)

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _norm_ad(s: str | None) -> str:
    return re.sub(r'\s+', ' ', (s or '').strip().casefold())


def _norm_eposta(s: str | None) -> str:
    return (s or '').strip().casefold()


def _norm_tel(s: str | None) -> str:
    return re.sub(r'\D+', '', (s or '').strip())


def _aktif_cari(con, cari_id: int) -> dict[str, Any] | None:
    row = con.execute(
        'SELECT id, cari_kod, unvan, aktif FROM nexgen_cari WHERE id=?',
        (cari_id,),
    ).fetchone()
    return dict(row) if row else None


def can_read_yetkili(con, kullanici_id: int, cari_id: int, yk: set[str] | None = None) -> bool:
    return can_view_cari(con, kullanici_id, cari_id, yk)


def can_write_yetkili(con, kullanici_id: int, cari_id: int, yk: set[str] | None = None) -> bool:
    """Admin (view_all) veya atanmış CRM yazma yetkilisi.

    FAZ-YONETIM-CARI360-GENEL-BILGILER-TAMAMLAMA-1:
    cari360.crm.write + atama varsa yetkili yazılabilir (plan.manage engeli kaldırıldı).
    """
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    return can_write_crm(con, kullanici_id, cari_id, yk)


def list_cari_yetkilileri(
    con,
    cari_id: int,
    *,
    sadece_aktif: bool = False,
) -> list[dict[str, Any]]:
    sql = """
        SELECT cy.*,
               sk1.KullaniciAdi AS created_by_adi,
               sk2.KullaniciAdi AS updated_by_adi
        FROM cari_yetkili cy
        LEFT JOIN sistem_kullanici sk1 ON sk1.Id = cy.created_by
        LEFT JOIN sistem_kullanici sk2 ON sk2.Id = cy.updated_by
        WHERE cy.cari_id=?
    """
    if sadece_aktif:
        sql += ' AND cy.aktif=1'
    sql += ' ORDER BY cy.aktif DESC, cy.ana_yetkili DESC, cy.ad_soyad COLLATE NOCASE'
    rows = con.execute(sql, (cari_id,)).fetchall()
    return [dict(r) for r in rows]


def get_yetkili(con, yetkili_id: int) -> dict[str, Any] | None:
    row = con.execute('SELECT * FROM cari_yetkili WHERE id=?', (yetkili_id,)).fetchone()
    return dict(row) if row else None


def _validate_payload(
    con,
    cari_id: int,
    ad_soyad: str,
    eposta: str | None,
    telefon: str | None,
    cep_telefonu: str | None,
    *,
    exclude_id: int | None = None,
    require_aktif_cari: bool = True,
) -> dict[str, Any]:
    cari = _aktif_cari(con, cari_id)
    if not cari:
        return {'ok': False, 'hata': 'Cari bulunamadı'}
    if require_aktif_cari and int(cari.get('aktif') or 0) != 1:
        return {'ok': False, 'hata': 'Pasif cari için yetkili eklenemez/güncellenemez'}

    ad = (ad_soyad or '').strip()
    if not ad:
        return {'ok': False, 'hata': 'ad_soyad zorunludur'}

    ep = (eposta or '').strip() or None
    if ep and not _EMAIL_RE.match(ep):
        return {'ok': False, 'hata': 'eposta formatı geçersiz'}

    # Duplicate soft-check (kör UNIQUE yok; boş alanlar eşleşmez)
    nad = _norm_ad(ad)
    nep = _norm_eposta(ep)
    ntel = _norm_tel(telefon)
    ncep = _norm_tel(cep_telefonu)

    aktifler = con.execute(
        'SELECT id, ad_soyad, eposta, telefon, cep_telefonu FROM cari_yetkili '
        'WHERE cari_id=? AND aktif=1',
        (cari_id,),
    ).fetchall()
    for r in aktifler:
        rid = int(r['id'])
        if exclude_id is not None and rid == exclude_id:
            continue
        if _norm_ad(r['ad_soyad']) == nad and nad:
            return {
                'ok': False,
                'hata': 'Aynı caride benzer ad_soyad ile aktif yetkili zaten var',
                'duplicate_id': rid,
            }
        if nep and _norm_eposta(r['eposta']) == nep:
            return {
                'ok': False,
                'hata': 'Aynı caride aynı eposta ile aktif yetkili zaten var',
                'duplicate_id': rid,
            }
        if ntel and (_norm_tel(r['telefon']) == ntel or _norm_tel(r['cep_telefonu']) == ntel):
            return {
                'ok': False,
                'hata': 'Aynı caride aynı telefon ile aktif yetkili zaten var',
                'duplicate_id': rid,
            }
        if ncep and (_norm_tel(r['telefon']) == ncep or _norm_tel(r['cep_telefonu']) == ncep):
            return {
                'ok': False,
                'hata': 'Aynı caride aynı cep telefonu ile aktif yetkili zaten var',
                'duplicate_id': rid,
            }

    return {'ok': True, 'ad_soyad': ad, 'eposta': ep, 'cari': cari}


def yetkili_ekle(
    con,
    cari_id: int,
    ad_soyad: str,
    *,
    unvan: str | None = None,
    departman: str | None = None,
    telefon: str | None = None,
    cep_telefonu: str | None = None,
    eposta: str | None = None,
    ana_yetkili: int = 0,
    notlar: str | None = None,
    kullanici_id: int | None = None,
) -> dict[str, Any]:
    v = _validate_payload(
        con, cari_id, ad_soyad, eposta, telefon, cep_telefonu, require_aktif_cari=True,
    )
    if not v.get('ok'):
        return v

    ana = 1 if int(ana_yetkili or 0) else 0
    ts = _now()

    try:
        if ana:
            con.execute(
                'UPDATE cari_yetkili SET ana_yetkili=0, updated_at=?, updated_by=? '
                'WHERE cari_id=? AND ana_yetkili=1 AND aktif=1',
                (ts, kullanici_id, cari_id),
            )
        con.execute(
            """
            INSERT INTO cari_yetkili
                (cari_id, ad_soyad, unvan, departman, telefon, cep_telefonu, eposta,
                 ana_yetkili, aktif, notlar, created_at, updated_at, created_by, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (
                cari_id,
                v['ad_soyad'],
                (unvan or '').strip() or None,
                (departman or '').strip() or None,
                (telefon or '').strip() or None,
                (cep_telefonu or '').strip() or None,
                v['eposta'],
                ana,
                (notlar or '').strip() or None,
                ts,
                ts,
                kullanici_id,
                kullanici_id,
            ),
        )
        new_id = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
        return {'ok': True, 'id': new_id}
    except Exception as e:
        msg = str(e)
        if 'uq_cari_yetkili_ana_aktif' in msg or 'UNIQUE' in msg.upper():
            return {'ok': False, 'hata': 'Bu caride zaten aktif ana yetkili var'}
        raise


def yetkili_guncelle(
    con,
    yetkili_id: int,
    *,
    ad_soyad: str | None = None,
    unvan: str | None = None,
    departman: str | None = None,
    telefon: str | None = None,
    cep_telefonu: str | None = None,
    eposta: str | None = None,
    notlar: str | None = None,
    kullanici_id: int | None = None,
    beklenen_cari_id: int | None = None,
) -> dict[str, Any]:
    row = get_yetkili(con, yetkili_id)
    if not row:
        return {'ok': False, 'hata': 'Yetkili bulunamadı'}
    cari_id = int(row['cari_id'])
    if beklenen_cari_id is not None and cari_id != int(beklenen_cari_id):
        return {'ok': False, 'hata': 'Başka carinin yetkilisi güncellenemez'}

    yeni_ad = ad_soyad if ad_soyad is not None else row['ad_soyad']
    yeni_ep = eposta if eposta is not None else row['eposta']
    yeni_tel = telefon if telefon is not None else row['telefon']
    yeni_cep = cep_telefonu if cep_telefonu is not None else row['cep_telefonu']

    v = _validate_payload(
        con,
        cari_id,
        yeni_ad,
        yeni_ep,
        yeni_tel,
        yeni_cep,
        exclude_id=yetkili_id,
        require_aktif_cari=True,
    )
    if not v.get('ok'):
        return v

    def _field(incoming, mevcut):
        if incoming is None:
            return mevcut
        s = (incoming or '').strip()
        return s or None

    ts = _now()
    con.execute(
        """
        UPDATE cari_yetkili SET
            ad_soyad=?,
            unvan=?,
            departman=?,
            telefon=?,
            cep_telefonu=?,
            eposta=?,
            notlar=?,
            updated_at=?,
            updated_by=?
        WHERE id=?
        """,
        (
            v['ad_soyad'],
            _field(unvan, row['unvan']),
            _field(departman, row['departman']),
            _field(telefon, row['telefon']) if telefon is not None else row['telefon'],
            _field(cep_telefonu, row['cep_telefonu']) if cep_telefonu is not None else row['cep_telefonu'],
            v['eposta'],
            _field(notlar, row['notlar']),
            ts,
            kullanici_id,
            yetkili_id,
        ),
    )
    return {'ok': True, 'id': yetkili_id}


def yetkili_aktif_ayarla(
    con,
    yetkili_id: int,
    aktif: int,
    *,
    kullanici_id: int | None = None,
    beklenen_cari_id: int | None = None,
) -> dict[str, Any]:
    row = get_yetkili(con, yetkili_id)
    if not row:
        return {'ok': False, 'hata': 'Yetkili bulunamadı'}
    cari_id = int(row['cari_id'])
    if beklenen_cari_id is not None and cari_id != int(beklenen_cari_id):
        return {'ok': False, 'hata': 'Başka carinin yetkilisi güncellenemez'}

    aktif_i = 1 if int(aktif or 0) else 0
    ts = _now()

    # Pasifleştirmede ana bayrak temizlenir
    if aktif_i == 0:
        con.execute(
            """
            UPDATE cari_yetkili
            SET aktif=0, ana_yetkili=0, updated_at=?, updated_by=?
            WHERE id=?
            """,
            (ts, kullanici_id, yetkili_id),
        )
        return {'ok': True, 'id': yetkili_id, 'aktif': 0, 'ana_yetkili': 0}

    # Yeniden aktif — cari aktif olmalı
    cari = _aktif_cari(con, cari_id)
    if not cari or int(cari.get('aktif') or 0) != 1:
        return {'ok': False, 'hata': 'Pasif cari için yetkili aktifleştirilemez'}

    con.execute(
        """
        UPDATE cari_yetkili
        SET aktif=1, updated_at=?, updated_by=?
        WHERE id=?
        """,
        (ts, kullanici_id, yetkili_id),
    )
    return {'ok': True, 'id': yetkili_id, 'aktif': 1}


def ana_yetkili_yap(
    con,
    yetkili_id: int,
    *,
    kullanici_id: int | None = None,
    beklenen_cari_id: int | None = None,
) -> dict[str, Any]:
    """Aynı transaction içinde eski ana yetkiliyi kapatır, yeniyi açar."""
    row = get_yetkili(con, yetkili_id)
    if not row:
        return {'ok': False, 'hata': 'Yetkili bulunamadı'}
    cari_id = int(row['cari_id'])
    if beklenen_cari_id is not None and cari_id != int(beklenen_cari_id):
        return {'ok': False, 'hata': 'Başka carinin yetkilisi güncellenemez'}
    if int(row.get('aktif') or 0) != 1:
        return {'ok': False, 'hata': 'Pasif yetkili ana yetkili olamaz'}

    cari = _aktif_cari(con, cari_id)
    if not cari or int(cari.get('aktif') or 0) != 1:
        return {'ok': False, 'hata': 'Pasif cari için ana yetkili atanamaz'}

    ts = _now()
    try:
        con.execute(
            'UPDATE cari_yetkili SET ana_yetkili=0, updated_at=?, updated_by=? '
            'WHERE cari_id=? AND ana_yetkili=1 AND aktif=1 AND id<>?',
            (ts, kullanici_id, cari_id, yetkili_id),
        )
        con.execute(
            'UPDATE cari_yetkili SET ana_yetkili=1, updated_at=?, updated_by=? WHERE id=?',
            (ts, kullanici_id, yetkili_id),
        )
        # Guard: en fazla bir aktif ana
        cnt = con.execute(
            'SELECT COUNT(*) FROM cari_yetkili '
            'WHERE cari_id=? AND ana_yetkili=1 AND aktif=1',
            (cari_id,),
        ).fetchone()[0]
        if int(cnt) != 1:
            raise RuntimeError('Ana yetkili tekliği bozuldu')
        return {'ok': True, 'id': yetkili_id, 'cari_id': cari_id}
    except Exception as e:
        msg = str(e)
        if 'uq_cari_yetkili_ana_aktif' in msg or 'UNIQUE' in msg.upper():
            return {'ok': False, 'hata': 'Bu caride zaten aktif ana yetkili var'}
        raise


# re-export helpers used by routes
__all__ = [
    'can_read_yetkili',
    'can_write_yetkili',
    'list_cari_yetkilileri',
    'get_yetkili',
    'yetkili_ekle',
    'yetkili_guncelle',
    'yetkili_aktif_ayarla',
    'ana_yetkili_yap',
    'load_kullanici_yetkileri',
    'can_cari360_crm_write',
    'can_cari360_view_all',
]
